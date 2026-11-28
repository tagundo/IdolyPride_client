#import "IdolyLocalHTTP.h"
#include <errno.h>
#include <math.h>

static const NSUInteger maximumBodyBytes = 16384;

@interface IDLocalHTTPProbe : NSObject <NSURLSessionDataDelegate>
@property (nonatomic, strong) NSLock *lock;
@property (nonatomic, strong) NSMutableData *body;
@property (nonatomic, strong) dispatch_semaphore_t done;
@property (nonatomic) BOOL finished;
@property (nonatomic) NSInteger status;
@property (nonatomic, copy) NSString *failure;
@property (nonatomic, copy) NSString *errorDomain;
@property (nonatomic, strong) NSNumber *errorCode;
- (void)finishWithCode:(NSString *)code error:(NSError *)error;
- (NSDictionary *)snapshot;
@end

static NSString *safeErrorDomain(NSError *error) {
    if (!error) return nil;
    for (NSString *domain in @[NSURLErrorDomain, NSPOSIXErrorDomain, NSCocoaErrorDomain, NSOSStatusErrorDomain])
        if ([error.domain isEqualToString:domain]) return domain;
    return @"Other";
}

static NSString *transportErrorCode(NSError *error) {
    if ([error.domain isEqualToString:NSURLErrorDomain]) {
        switch (error.code) {
            case NSURLErrorTimedOut: return @"timeout";
            case NSURLErrorCannotFindHost:
            case NSURLErrorCannotConnectToHost:
            case NSURLErrorNetworkConnectionLost:
            case NSURLErrorDNSLookupFailed:
            case NSURLErrorNotConnectedToInternet: return @"connection";
            default: return @"transport";
        }
    }
    if ([error.domain isEqualToString:NSPOSIXErrorDomain]) {
        if (error.code == ETIMEDOUT) return @"timeout";
        if (error.code == ECONNREFUSED || error.code == ENETDOWN
                || error.code == ENETUNREACH || error.code == EHOSTUNREACH) return @"connection";
    }
    return @"transport";
}

@implementation IDLocalHTTPProbe
- (instancetype)init {
    self = [super init];
    if (self) {
        _lock = [NSLock new]; _body = [NSMutableData data];
        _done = dispatch_semaphore_create(0);
    }
    return self;
}
- (void)finishWithCode:(NSString *)code error:(NSError *)error {
    [self.lock lock];
    BOOL first = !self.finished;
    if (first) {
        self.finished = YES; self.failure = code;
        self.errorDomain = safeErrorDomain(error);
        self.errorCode = error ? @(error.code) : nil;
    }
    [self.lock unlock];
    if (first) dispatch_semaphore_signal(self.done);
}
- (NSDictionary *)snapshot {
    [self.lock lock];
    NSDictionary *value = @{@"body":[self.body copy], @"http_status":@(self.status),
        @"error_code":self.failure ?: @"transport", @"ns_error_domain":self.errorDomain ?: (id)NSNull.null,
        @"ns_error_code":self.errorCode ?: (id)NSNull.null};
    [self.lock unlock];
    return value;
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task
        didReceiveResponse:(NSURLResponse *)response
        completionHandler:(void (^)(NSURLSessionResponseDisposition))completionHandler {
    (void)session; (void)task;
    if (![response isKindOfClass:NSHTTPURLResponse.class]) {
        [self finishWithCode:@"transport" error:nil]; completionHandler(NSURLSessionResponseCancel); return;
    }
    NSInteger status = ((NSHTTPURLResponse *)response).statusCode;
    [self.lock lock];
    BOOL finished = self.finished;
    if (!finished) self.status = status >= 100 && status <= 599 ? status : 0;
    [self.lock unlock];
    if (finished) { completionHandler(NSURLSessionResponseCancel); return; }
    if (status != 200) {
        [self finishWithCode:@"http_status" error:nil]; completionHandler(NSURLSessionResponseCancel); return;
    }
    if (response.expectedContentLength > (long long)maximumBodyBytes) {
        [self finishWithCode:@"response_too_large" error:nil]; completionHandler(NSURLSessionResponseCancel); return;
    }
    completionHandler(NSURLSessionResponseAllow);
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveData:(NSData *)data {
    (void)session;
    [self.lock lock];
    BOOL excessive = NO;
    if (!self.finished) {
        NSUInteger available = maximumBodyBytes - self.body.length;
        excessive = data.length > available;
        if (excessive) {
            if (available) [self.body appendBytes:data.bytes length:available];
        } else [self.body appendData:data];
    }
    [self.lock unlock];
    if (excessive) { [self finishWithCode:@"response_too_large" error:nil]; [task cancel]; }
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
        willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)request
        completionHandler:(void (^)(NSURLRequest *))completionHandler {
    (void)session; (void)request;
    [self.lock lock];
    if (!self.finished) self.status = response.statusCode >= 100 && response.statusCode <= 599 ? response.statusCode : 0;
    [self.lock unlock];
    // Do not inspect, log, or follow the server-supplied destination.
    [self finishWithCode:@"redirect" error:nil]; completionHandler(nil); [task cancel];
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
        didReceiveChallenge:(NSURLAuthenticationChallenge *)challenge
        completionHandler:(void (^)(NSURLSessionAuthChallengeDisposition, NSURLCredential *))completionHandler {
    (void)session; (void)task; (void)challenge;
    completionHandler(NSURLSessionAuthChallengeCancelAuthenticationChallenge, nil);
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task didCompleteWithError:(NSError *)error {
    (void)session; (void)task;
    [self finishWithCode:error ? transportErrorCode(error) : @"none" error:error];
}
@end

NSDictionary *IDLocalHTTPReadiness(NSUInteger port, NSTimeInterval timeout) {
    BOOL onMain = NSThread.isMainThread;
    BOOL validPort = port >= 1 && port <= 65535;
    NSString *url = validPort ? [NSString stringWithFormat:@"http://127.0.0.1:%lu/client/playback", (unsigned long)port] : nil;
    NSMutableDictionary *result = [@{@"schema":@1, @"ok":@NO, @"transport":@"NSURLSession",
        @"url":url ?: (id)NSNull.null, @"http_status":@0, @"error_code":@"transport",
        @"body_is_json":@NO, @"received_bytes":@0, @"worker_main_thread":@(onMain),
        @"ns_error_domain":NSNull.null, @"ns_error_code":NSNull.null} mutableCopy];
    if (onMain) { result[@"error_code"] = @"main_thread"; return result; }
    if (!validPort) { result[@"error_code"] = @"invalid_port"; return result; }
    if (!isfinite(timeout) || timeout <= 0) return result;
    NSTimeInterval boundedTimeout = fmin(timeout, 10.0);
    dispatch_time_t deadline = dispatch_time(DISPATCH_TIME_NOW, (int64_t)ceil(boundedTimeout * NSEC_PER_SEC));
    IDLocalHTTPProbe *probe = [IDLocalHTTPProbe new];
    NSOperationQueue *delegates = [NSOperationQueue new];
    delegates.name = @"local.idoly.loopback-preflight"; delegates.maxConcurrentOperationCount = 1;
    delegates.qualityOfService = NSQualityOfServiceUtility;
    NSURLSessionConfiguration *configuration = NSURLSessionConfiguration.ephemeralSessionConfiguration;
    configuration.requestCachePolicy = NSURLRequestReloadIgnoringLocalCacheData;
    configuration.URLCache = nil; configuration.HTTPCookieStorage = nil; configuration.URLCredentialStorage = nil;
    configuration.HTTPShouldSetCookies = NO; configuration.HTTPMaximumConnectionsPerHost = 1;
    configuration.connectionProxyDictionary = @{};
    configuration.waitsForConnectivity = NO; configuration.allowsCellularAccess = NO;
    configuration.timeoutIntervalForRequest = boundedTimeout;
    configuration.timeoutIntervalForResource = boundedTimeout;
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:[NSURL URLWithString:url]
        cachePolicy:NSURLRequestReloadIgnoringLocalCacheData timeoutInterval:boundedTimeout];
    request.HTTPMethod = @"GET"; request.HTTPShouldHandleCookies = NO;
    NSURLSession *session = [NSURLSession sessionWithConfiguration:configuration delegate:probe delegateQueue:delegates];
    NSURLSessionDataTask *task = [session dataTaskWithRequest:request];
    [task resume];
    if (dispatch_semaphore_wait(probe.done, deadline) != 0) {
        [probe finishWithCode:@"timeout" error:nil]; [task cancel];
    }
    NSDictionary *observed = [probe snapshot];
    [session invalidateAndCancel];
    for (NSString *key in @[@"http_status", @"error_code", @"ns_error_domain", @"ns_error_code"])
        result[key] = observed[key];
    NSData *body = observed[@"body"];
    result[@"received_bytes"] = @(body.length);
    if ([result[@"error_code"] isEqual:@"none"]) {
        id value = [NSJSONSerialization JSONObjectWithData:body options:0 error:NULL];
        BOOL dictionary = [value isKindOfClass:NSDictionary.class];
        result[@"body_is_json"] = @(dictionary);
        result[@"ok"] = dictionary && [result[@"http_status"] isEqual:@200] ? @YES : @NO;
        if (!dictionary) result[@"error_code"] = @"invalid_json";
    }
    return result;
}
