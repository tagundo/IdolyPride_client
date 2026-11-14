/* A bounded, verifying native CDN transport for the embedded Python server.
 * NSURLSession owns TLS verification. There is deliberately no challenge
 * override, background session, shared credential store, or whole-body buffer.
 */
#import <Foundation/Foundation.h>
#include <math.h>
#include <string.h>
#include "IdolyHTTP.h"

enum { IDHTTPBufferBytes = 64 * 1024, IDHTTPHeaderBytes = 16 * 1024 };
typedef NS_ENUM(NSInteger, IDHTTPFailure) {
    IDHTTPFailureNone, IDHTTPFailureTimeout, IDHTTPFailureConnection,
    IDHTTPFailureRedirect, IDHTTPFailureClosed, IDHTTPFailureTLS, IDHTTPFailureDNS
};

/* This is the same immutable CDN origin accepted by octo_cache._cdn_origin.
 * The Python manifest/cache additionally checks the exact requested object.
 */
static BOOL IDAllowedURL(NSURL *url) {
    if (!url || !IDHTTPAllowedOriginParts(url.scheme.lowercaseString.UTF8String,
        url.host.lowercaseString.UTF8String, url.port ? url.port.longValue : -1,
        url.user != nil, url.password != nil, url.fragment != nil)) return NO;
    NSString *text = url.absoluteString;
    if (!text.length || [text lengthOfBytesUsingEncoding:NSUTF8StringEncoding] > 8192) return NO;
    return [text rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location == NSNotFound;
}

static NSMutableURLRequest *IDRequest(NSURL *url, NSTimeInterval timeout) {
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url
        cachePolicy:NSURLRequestReloadIgnoringLocalCacheData timeoutInterval:timeout];
    request.HTTPMethod = @"GET";
    request.HTTPShouldHandleCookies = NO;
    [request setValue:@"identity" forHTTPHeaderField:@"Accept-Encoding"];
    [request setValue:@"IdolyLocalAssets/0.1" forHTTPHeaderField:@"User-Agent"];
    return request;
}

@interface IDHTTPStream : NSObject <NSURLSessionDataDelegate, NSURLSessionTaskDelegate> {
    NSCondition *_condition;
    NSURLSession *_session;
    NSURLSessionDataTask *_task;
    NSOperationQueue *_delegateQueue;
    unsigned char _bytes[IDHTTPBufferBytes];
    NSUInteger _head, _used, _redirects;
    BOOL _headersReady, _done, _closed, _suspended;
    IDHTTPFailure _failure;
    NSTimeInterval _deadline, _absoluteDeadline, _timeout;
    NSDictionary<NSString *, NSString *> *_headers;
    NSString *_finalURL;
    NSInteger _status;
}
- (instancetype)initWithURL:(NSURL *)url timeout:(NSTimeInterval)timeout;
- (IDHTTPFailure)waitForHeaders;
- (IDHTTPFailure)copyBytes:(char *)output maximum:(NSUInteger)maximum count:(NSUInteger *)count;
- (void)close;
- (NSDictionary<NSString *, NSString *> *)headers;
- (NSString *)finalURL;
- (NSInteger)status;
@end

@implementation IDHTTPStream
- (instancetype)initWithURL:(NSURL *)url timeout:(NSTimeInterval)timeout {
    self = [super init];
    if (self) {
        _condition = [NSCondition new];
        _headers = @{};
        _finalURL = url.absoluteString;
        NSTimeInterval now = NSProcessInfo.processInfo.systemUptime;
        _timeout = timeout;
        _deadline = now + timeout;
        _absoluteDeadline = now + 900;
        _delegateQueue = [NSOperationQueue new];
        _delegateQueue.name = @"IdolyEmbeddedServer.CDN";
        _delegateQueue.maxConcurrentOperationCount = 1;
        _delegateQueue.qualityOfService = NSQualityOfServiceUtility;
        NSURLSessionConfiguration *configuration = NSURLSessionConfiguration.ephemeralSessionConfiguration;
        configuration.URLCache = nil;
        configuration.URLCredentialStorage = nil;
        configuration.HTTPCookieStorage = nil;
        configuration.HTTPShouldSetCookies = NO;
        configuration.requestCachePolicy = NSURLRequestReloadIgnoringLocalCacheData;
        configuration.timeoutIntervalForRequest = timeout;
        /* urllib's timeout is an individual blocked-I/O timeout, not a cap on
         * a continuously progressing large object. The cache independently
         * enforces its per-object budget (at most 900s for bulk downloads).
         */
        configuration.timeoutIntervalForResource = 900;
        configuration.HTTPMaximumConnectionsPerHost = 1;
        _session = [NSURLSession sessionWithConfiguration:configuration delegate:self delegateQueue:_delegateQueue];
        _task = [_session dataTaskWithRequest:IDRequest(url, timeout)];
        [_task resume];
    }
    return self;
}

/* Only call while holding _condition. A monotonic deadline bounds every
 * producer/consumer wait even when the other side disappears without close.
 */
- (BOOL)waitForChange {
    NSTimeInterval remaining = MIN(_deadline, _absoluteDeadline) - NSProcessInfo.processInfo.systemUptime;
    if (remaining <= 0) {
        _failure = IDHTTPFailureTimeout;
        _done = YES;
        [_condition broadcast];
        return NO;
    }
    [_condition waitUntilDate:[NSDate dateWithTimeIntervalSinceNow:MIN(remaining, 0.25)]];
    return YES;
}

- (IDHTTPFailure)waitForHeaders {
    [_condition lock];
    while (!_headersReady && !_done && !_closed) [self waitForChange];
    IDHTTPFailure result = _closed ? IDHTTPFailureClosed : _failure;
    if (!_headersReady && result == IDHTTPFailureNone) result = IDHTTPFailureConnection;
    [_condition unlock];
    return result;
}

- (IDHTTPFailure)copyBytes:(char *)output maximum:(NSUInteger)maximum count:(NSUInteger *)count {
    *count = 0;
    NSURLSessionDataTask *resume = nil;
    [_condition lock];
    _deadline = NSProcessInfo.processInfo.systemUptime + _timeout;
    while (!_used && !_done && !_closed) [self waitForChange];
    IDHTTPFailure result = _closed ? IDHTTPFailureClosed : _failure;
    if (result == IDHTTPFailureNone && _used) {
        NSUInteger amount = MIN(maximum, _used);
        NSUInteger first = MIN(amount, (NSUInteger)IDHTTPBufferBytes - _head);
        memcpy(output, _bytes + _head, first);
        if (first != amount) memcpy(output + first, _bytes, amount - first);
        _head = (_head + amount) % IDHTTPBufferBytes;
        _used -= amount;
        *count = amount;
        if (_suspended) { _suspended = NO; resume = _task; }
        [_condition broadcast];
    }
    [_condition unlock];
    [resume resume];
    return result;
}

- (void)close {
    [_condition lock];
    _closed = YES;
    _used = 0;
    NSURLSessionDataTask *task = _task;
    NSURLSession *session = _session;
    _task = nil;
    _session = nil;
    [_condition broadcast];
    [_condition unlock];
    [task cancel];
    [session invalidateAndCancel];
}

- (NSDictionary<NSString *, NSString *> *)headers {
    [_condition lock]; NSDictionary *result = _headers; [_condition unlock]; return result;
}
- (NSString *)finalURL {
    [_condition lock]; NSString *result = _finalURL; [_condition unlock]; return result;
}
- (NSInteger)status {
    [_condition lock]; NSInteger result = _status; [_condition unlock]; return result;
}

- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task
    didReceiveResponse:(NSURLResponse *)response
    completionHandler:(void (^)(NSURLSessionResponseDisposition))completionHandler {
    (void)session; (void)task;
    BOOL valid = [response isKindOfClass:NSHTTPURLResponse.class] && IDAllowedURL(response.URL);
    NSMutableDictionary<NSString *, NSString *> *headers = [NSMutableDictionary new];
    NSUInteger total = 0;
    if (valid) {
        NSHTTPURLResponse *http = (NSHTTPURLResponse *)response;
        valid = http.allHeaderFields.count <= 64 && http.statusCode >= 100 && http.statusCode <= 599;
        for (id rawName in http.allHeaderFields) {
            id rawValue = http.allHeaderFields[rawName];
            if (![rawName isKindOfClass:NSString.class] || ![rawValue isKindOfClass:NSString.class]) { valid = NO; break; }
            NSString *name = rawName, *value = rawValue;
            NSUInteger nameBytes = [name lengthOfBytesUsingEncoding:NSUTF8StringEncoding];
            NSUInteger valueBytes = [value lengthOfBytesUsingEncoding:NSUTF8StringEncoding];
            if (!nameBytes || nameBytes > 256 || valueBytes > 8192 || nameBytes + valueBytes > IDHTTPHeaderBytes - total) { valid = NO; break; }
            total += nameBytes + valueBytes;
            if (total > IDHTTPHeaderBytes || [name rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location != NSNotFound ||
                [value rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location != NSNotFound) { valid = NO; break; }
            if ([name caseInsensitiveCompare:@"Content-Length"] == NSOrderedSame) name = @"Content-Length";
            else if ([name caseInsensitiveCompare:@"Content-Encoding"] == NSOrderedSame) name = @"Content-Encoding";
            if (headers[name] && ![headers[name] isEqualToString:value]) { valid = NO; break; }
            headers[name] = value;
        }
    }
    [_condition lock];
    if (!valid) { _failure = IDHTTPFailureConnection; _done = YES; }
    if (valid && !_closed) {
        _headers = [headers copy];
        _finalURL = response.URL.absoluteString;
        _status = ((NSHTTPURLResponse *)response).statusCode;
        _headersReady = YES;
    }
    BOOL accept = valid && !_closed;
    [_condition broadcast];
    [_condition unlock];
    completionHandler(accept ? NSURLSessionResponseAllow : NSURLSessionResponseCancel);
}

- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveData:(NSData *)data {
    (void)session; (void)task;
    const unsigned char *input = data.bytes;
    NSUInteger position = 0;
    [_condition lock];
    while (position < data.length && !_closed && !_done) {
        while (_used == IDHTTPBufferBytes && !_closed && !_done) {
            /* Pause network delivery as well as the bounded delegate queue.
             * At most one balanced suspend is outstanding. The consumer
             * resumes it after freeing ring space; close instead cancels it.
             */
            if (!_suspended) { _suspended = YES; [task suspend]; }
            [self waitForChange];
        }
        if (_closed || _done) break;
        NSUInteger tail = (_head + _used) % IDHTTPBufferBytes;
        NSUInteger amount = MIN(data.length - position, (NSUInteger)IDHTTPBufferBytes - _used);
        amount = MIN(amount, (NSUInteger)IDHTTPBufferBytes - tail);
        memcpy(_bytes + tail, input + position, amount);
        position += amount; _used += amount;
        if (_used == IDHTTPBufferBytes && !_suspended) { _suspended = YES; [task suspend]; }
        [_condition broadcast];
    }
    BOOL failed = _failure != IDHTTPFailureNone;
    [_condition unlock];
    if (failed) [task cancel];
}

- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
    willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)request
    completionHandler:(void (^)(NSURLRequest *))completionHandler {
    (void)session; (void)task; (void)response;
    [_condition lock];
    NSTimeInterval remaining = _deadline - NSProcessInfo.processInfo.systemUptime;
    BOOL valid = !_closed && IDAllowedURL(request.URL) && ++_redirects <= 5 && remaining > 0;
    if (!valid && !_closed) {
        _failure = remaining <= 0 ? IDHTTPFailureTimeout : IDHTTPFailureRedirect;
        _done = YES;
        [_condition broadcast];
    }
    [_condition unlock];
    completionHandler(valid ? IDRequest(request.URL, remaining) : nil);
}

- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task didCompleteWithError:(NSError *)error {
    (void)session; (void)task;
    [_condition lock];
    if (error && !_closed && _failure == IDHTTPFailureNone) {
        _failure = IDHTTPFailureConnection;
        if ([error.domain isEqualToString:NSURLErrorDomain]) {
            switch (error.code) {
                case NSURLErrorTimedOut: _failure = IDHTTPFailureTimeout; break;
                case NSURLErrorCannotFindHost:
                case NSURLErrorDNSLookupFailed: _failure = IDHTTPFailureDNS; break;
                case NSURLErrorSecureConnectionFailed:
                case NSURLErrorServerCertificateHasBadDate:
                case NSURLErrorServerCertificateUntrusted:
                case NSURLErrorServerCertificateHasUnknownRoot:
                case NSURLErrorServerCertificateNotYetValid:
                case NSURLErrorClientCertificateRejected:
                case NSURLErrorClientCertificateRequired: _failure = IDHTTPFailureTLS; break;
                default: break;
            }
        }
    }
    _done = YES;
    [_condition broadcast];
    [_condition unlock];
    /* Invalidation breaks NSURLSession's delegate retain cycle after its last
     * callback. The Python response still owns this stream until close/dealloc.
     */
    [session finishTasksAndInvalidate];
}
@end

typedef struct { PyObject_HEAD void *stream; } IDHTTPResponse;
static PyTypeObject IDHTTPResponseType = { PyVarObject_HEAD_INIT(NULL, 0) };

static IDHTTPStream *IDStream(IDHTTPResponse *response) {
    return response->stream ? (__bridge IDHTTPStream *)response->stream : nil;
}

static void IDRaiseFailure(IDHTTPFailure failure) {
    if (failure == IDHTTPFailureRedirect || failure == IDHTTPFailureTLS || failure == IDHTTPFailureDNS) {
        const char *code = failure == IDHTTPFailureRedirect ? "upstream_redirect" :
            failure == IDHTTPFailureTLS ? "upstream_tls" : "upstream_dns";
        PyObject *module = PyImport_ImportModule("idoly_local.octo_cache");
        PyObject *type = module ? PyObject_GetAttrString(module, "OctoCacheError") : NULL;
        PyObject *error = type ? PyObject_CallFunction(type, "s", code) : NULL;
        BOOL raised = error != NULL;
        if (error) PyErr_SetObject(type, error);
        Py_XDECREF(error); Py_XDECREF(type); Py_XDECREF(module);
        if (!raised) {
            PyErr_Clear();
            PyErr_SetString(failure == IDHTTPFailureRedirect ? PyExc_ValueError : PyExc_ConnectionError,
                           failure == IDHTTPFailureRedirect ? "CDN origin rejected" : "CDN transport unavailable");
        }
    } else if (failure == IDHTTPFailureTimeout) {
        PyErr_SetString(PyExc_TimeoutError, "CDN request timed out");
    } else if (failure == IDHTTPFailureClosed) {
        PyErr_SetString(PyExc_ValueError, "I/O operation on closed CDN response");
    } else PyErr_SetString(PyExc_ConnectionError, "CDN transport unavailable");
}

static PyObject *IDResponseRead(IDHTTPResponse *response, PyObject *args) {
    Py_ssize_t maximum = IDHTTPBufferBytes;
    if (!PyArg_ParseTuple(args, "|n:read", &maximum)) return NULL;
    if (maximum < 0 || maximum > IDHTTPBufferBytes) {
        PyErr_SetString(PyExc_ValueError, "read size must be between 0 and 65536"); return NULL;
    }
    if (!maximum) return PyBytes_FromStringAndSize("", 0);
    IDHTTPStream *stream = IDStream(response);
    if (!stream) { IDRaiseFailure(IDHTTPFailureClosed); return NULL; }
    PyObject *value = PyBytes_FromStringAndSize(NULL, maximum);
    if (!value) return NULL;
    char *bytes = PyBytes_AS_STRING(value);
    NSUInteger count = 0;
    IDHTTPFailure failure;
    Py_BEGIN_ALLOW_THREADS
    @autoreleasepool { failure = [stream copyBytes:bytes maximum:(NSUInteger)maximum count:&count]; }
    Py_END_ALLOW_THREADS
    if (failure != IDHTTPFailureNone) { [stream close]; Py_DECREF(value); IDRaiseFailure(failure); return NULL; }
    if (_PyBytes_Resize(&value, (Py_ssize_t)count) < 0) return NULL;
    return value;
}

static PyObject *IDResponseClose(IDHTTPResponse *response, PyObject *unused) {
    (void)unused; [IDStream(response) close]; Py_RETURN_NONE;
}
static void IDResponseDealloc(IDHTTPResponse *response) {
    if (response->stream) {
        IDHTTPStream *stream = CFBridgingRelease(response->stream);
        response->stream = NULL;
        [stream close];
    }
    Py_TYPE(response)->tp_free((PyObject *)response);
}
static PyObject *IDResponseGetCode(IDHTTPResponse *response, PyObject *unused) {
    (void)unused; return PyLong_FromLong((long)[IDStream(response) status]);
}
static PyObject *IDResponseGetURL(IDHTTPResponse *response, PyObject *unused) {
    (void)unused; NSString *url = [IDStream(response) finalURL];
    return PyUnicode_FromString(url.UTF8String ?: "");
}
static PyObject *IDResponseEnter(IDHTTPResponse *response, PyObject *unused) {
    (void)unused; return Py_NewRef((PyObject *)response);
}
static PyObject *IDResponseExit(IDHTTPResponse *response, PyObject *args) {
    (void)args; [IDStream(response) close]; Py_RETURN_FALSE;
}
static PyObject *IDResponseStatus(IDHTTPResponse *response, void *closure) {
    (void)closure; return IDResponseGetCode(response, NULL);
}
static PyObject *IDResponseHeaders(IDHTTPResponse *response, void *closure) {
    (void)closure; PyObject *result = PyDict_New();
    if (!result) return NULL;
    NSDictionary<NSString *, NSString *> *headers = [IDStream(response) headers];
    for (NSString *name in headers) {
        PyObject *key = PyUnicode_FromString(name.UTF8String);
        PyObject *value = PyUnicode_FromString(headers[name].UTF8String);
        int failed = !key || !value || PyDict_SetItem(result, key, value) < 0;
        Py_XDECREF(key); Py_XDECREF(value);
        if (failed) { Py_DECREF(result); return NULL; }
    }
    return result;
}
static PyMethodDef IDResponseMethods[] = {
    {"read", (PyCFunction)IDResponseRead, METH_VARARGS, "Read at most 65536 bytes without buffering the complete body."},
    {"close", (PyCFunction)IDResponseClose, METH_NOARGS, "Cancel and release this response."},
    {"getcode", (PyCFunction)IDResponseGetCode, METH_NOARGS, "Return the HTTP status."},
    {"geturl", (PyCFunction)IDResponseGetURL, METH_NOARGS, "Return the final verified CDN URL."},
    {"__enter__", (PyCFunction)IDResponseEnter, METH_NOARGS, NULL},
    {"__exit__", (PyCFunction)IDResponseExit, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};
static PyGetSetDef IDResponseGetSet[] = {
    {"status", (getter)IDResponseStatus, NULL, NULL, NULL},
    {"headers", (getter)IDResponseHeaders, NULL, NULL, NULL},
    {NULL, NULL, NULL, NULL, NULL}
};

int IDHTTPPrepareTypes(void) {
    if (IDHTTPResponseType.tp_flags & Py_TPFLAGS_READY) return 0;
    IDHTTPResponseType.tp_name = "_idoly_ios.HTTPResponse";
    IDHTTPResponseType.tp_basicsize = sizeof(IDHTTPResponse);
    IDHTTPResponseType.tp_flags = Py_TPFLAGS_DEFAULT;
    IDHTTPResponseType.tp_dealloc = (destructor)IDResponseDealloc;
    IDHTTPResponseType.tp_methods = IDResponseMethods;
    IDHTTPResponseType.tp_getset = IDResponseGetSet;
    return PyType_Ready(&IDHTTPResponseType);
}

PyObject *IDOpenURL(PyObject *module, PyObject *args, PyObject *kwargs) {
    (void)module;
    static char *keywords[] = {"url", "timeout", NULL};
    PyObject *urlObject;
    double timeout = 30;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "U|d:open_url", keywords, &urlObject, &timeout)) return NULL;
    if (!isfinite(timeout) || timeout <= 0 || timeout > 300) {
        PyErr_SetString(PyExc_ValueError, "timeout must be finite and between 0 and 300 seconds"); return NULL;
    }
    Py_ssize_t urlLength;
    const char *urlBytes = PyUnicode_AsUTF8AndSize(urlObject, &urlLength);
    if (!urlBytes) return NULL;
    if (!urlLength || urlLength > 8192 || memchr(urlBytes, 0, (size_t)urlLength)) {
        IDRaiseFailure(IDHTTPFailureRedirect); return NULL;
    }
    @autoreleasepool {
        NSString *text = [[NSString alloc] initWithBytes:urlBytes length:(NSUInteger)urlLength encoding:NSUTF8StringEncoding];
        NSURL *url = [NSURL URLWithString:text];
        if (!IDAllowedURL(url)) { IDRaiseFailure(IDHTTPFailureRedirect); return NULL; }
        if (IDHTTPPrepareTypes() < 0) return NULL;
        IDHTTPStream *stream = [[IDHTTPStream alloc] initWithURL:url timeout:timeout];
        if (!stream) return PyErr_NoMemory();
        IDHTTPFailure failure;
        Py_BEGIN_ALLOW_THREADS
        failure = [stream waitForHeaders];
        Py_END_ALLOW_THREADS
        if (failure != IDHTTPFailureNone) { [stream close]; IDRaiseFailure(failure); return NULL; }
        IDHTTPResponse *response = PyObject_New(IDHTTPResponse, &IDHTTPResponseType);
        if (!response) { [stream close]; return NULL; }
        response->stream = (void *)CFBridgingRetain(stream);
        return (PyObject *)response;
    }
}
