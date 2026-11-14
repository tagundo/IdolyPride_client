// Simulator-only UIKit host. This fake Unity class never enters a game IPA.
#import <UIKit/UIKit.h>
#import "IdolyEmbeddedServer.h"
#import <CommonCrypto/CommonCryptor.h>
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static NSDictionary *ProbeObject(NSString *text) {
    NSData *raw = [text dataUsingEncoding:NSUTF8StringEncoding];
    if (!raw || raw.length > 65536) return @{@"probe_error": @"invalid_status_size"};
    id value = [NSJSONSerialization JSONObjectWithData:raw options:0 error:nil];
    return [value isKindOfClass:NSDictionary.class] ? value : @{@"probe_error": @"invalid_status_json"};
}

static id ProbeScalar(NSDictionary *value, NSString *key) {
    id item = value[key];
    if ([item isKindOfClass:NSString.class]) return [item length] <= 256 ? item : @"oversize_field";
    if ([item isKindOfClass:NSNumber.class]) return item;
    return NSNull.null;
}

static NSDictionary *ProbeHostStatus(NSString *reply) {
    NSDictionary *value = ProbeObject(reply);
    NSDictionary *result = [value[@"result"] isKindOfClass:NSDictionary.class] ? value[@"result"] : @{};
    NSDictionary *runtime = [result[@"runtime"] isKindOfClass:NSDictionary.class] ? result[@"runtime"] : @{};
    return @{@"id":ProbeScalar(value, @"id"), @"ok":ProbeScalar(value, @"ok"),
        @"result":@{@"state":ProbeScalar(result, @"state"), @"running":ProbeScalar(result, @"running"),
            @"last_error":ProbeScalar(result, @"last_error"),
            @"runtime":@{@"running":ProbeScalar(runtime, @"running"),
                @"grpc_address":ProbeScalar(runtime, @"grpc_address"),
                @"asset_url":ProbeScalar(runtime, @"asset_url")}}};
}

static BOOL ProbeWrite(NSString *name, NSDictionary *value) {
    NSData *raw = [NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingSortedKeys error:nil];
    if (!raw || raw.length > 65536) return NO;
    NSURL *documents = [NSFileManager.defaultManager URLsForDirectory:NSDocumentDirectory
                                                           inDomains:NSUserDomainMask].firstObject;
    return [raw writeToURL:[documents URLByAppendingPathComponent:name] options:NSDataWritingAtomic error:nil];
}

static BOOL ProbePort(uint16_t port) {
    int descriptor = socket(AF_INET, SOCK_STREAM, 0);
    if (descriptor < 0) return NO;
    BOOL ready = NO;
    if (fcntl(descriptor, F_SETFL, O_NONBLOCK) == 0) {
        struct sockaddr_in target = {0}; target.sin_family = AF_INET;
        target.sin_port = htons(port); target.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        int result = connect(descriptor, (struct sockaddr *)&target, sizeof(target));
        if (result == 0) ready = YES;
        else if (errno == EINPROGRESS) {
            struct pollfd event = {.fd = descriptor, .events = POLLOUT};
            if (poll(&event, 1, 1000) > 0 && (event.revents & POLLOUT)) {
                int error = 0; socklen_t amount = sizeof(error);
                ready = getsockopt(descriptor, SOL_SOCKET, SO_ERROR, &error, &amount) == 0 && error == 0;
            }
        }
    }
    close(descriptor); return ready;
}

static BOOL ProbeAES(const unsigned char *key, size_t keySize, const unsigned char *expected) {
    const unsigned char iv[16] = {0x00,0x01,0x02,0x03,0x04,0x05,0x06,0x07,
                                  0x08,0x09,0x0a,0x0b,0x0c,0x0d,0x0e,0x0f};
    const unsigned char plain[16] = {0x6b,0xc1,0xbe,0xe2,0x2e,0x40,0x9f,0x96,
                                     0xe9,0x3d,0x7e,0x11,0x73,0x93,0x17,0x2a};
    unsigned char encrypted[16] = {0}, decrypted[16] = {0}; size_t count = 0;
    if (CCCrypt(kCCEncrypt, kCCAlgorithmAES, 0, key, keySize, iv, plain, sizeof(plain),
                encrypted, sizeof(encrypted), &count) != kCCSuccess
        || count != 16 || memcmp(encrypted, expected, 16) != 0) return NO;
    return CCCrypt(kCCDecrypt, kCCAlgorithmAES, 0, key, keySize, iv, encrypted, sizeof(encrypted),
                   decrypted, sizeof(decrypted), &count) == kCCSuccess
        && count == 16 && memcmp(decrypted, plain, 16) == 0;
}

static NSDictionary *ProbeCrypto(void) {
    // NIST SP800-38A F.2.1/F.2.5, first block; no padding.
    const unsigned char key128[16] = {0x2b,0x7e,0x15,0x16,0x28,0xae,0xd2,0xa6,
                                      0xab,0xf7,0x15,0x88,0x09,0xcf,0x4f,0x3c};
    const unsigned char cipher128[16] = {0x76,0x49,0xab,0xac,0x81,0x19,0xb2,0x46,
                                         0xce,0xe9,0x8e,0x9b,0x12,0xe9,0x19,0x7d};
    const unsigned char key256[32] = {0x60,0x3d,0xeb,0x10,0x15,0xca,0x71,0xbe,
                                      0x2b,0x73,0xae,0xf0,0x85,0x7d,0x77,0x81,
                                      0x1f,0x35,0x2c,0x07,0x3b,0x61,0x08,0xd7,
                                      0x2d,0x98,0x10,0xa3,0x09,0x14,0xdf,0xf4};
    const unsigned char cipher256[16] = {0xf5,0x8c,0x4c,0x04,0xd6,0xe5,0xf1,0xba,
                                         0x77,0x9e,0xab,0xfb,0x5f,0x7b,0xfb,0xd6};
    return @{@"nist_aes128_cbc": @(ProbeAES(key128, sizeof(key128), cipher128)),
             @"nist_aes256_cbc": @(ProbeAES(key256, sizeof(key256), cipher256))};
}

@interface UnityAppController : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@property(nonatomic, strong) UILabel *label;
@property(nonatomic, strong) NSTimer *waitingTimer;
@property(nonatomic) NSUInteger originalCount;
@property(nonatomic) BOOL reportScheduled;
- (void)startUnity:(UIApplication *)application;
@end

@implementation UnityAppController
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)options;
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *screen = [UIViewController new]; screen.view.backgroundColor = UIColor.systemBackgroundColor;
    self.label = [[UILabel alloc] initWithFrame:screen.view.bounds];
    self.label.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    self.label.textAlignment = NSTextAlignmentCenter; self.label.numberOfLines = 0;
    self.label.text = @"Embedded server probe: waiting for READY";
    [screen.view addSubview:self.label]; self.window.rootViewController = screen; [self.window makeKeyAndVisible];
    self.waitingTimer = [NSTimer scheduledTimerWithTimeInterval:0.25 repeats:YES block:^(NSTimer *timer) {
        (void)timer;
        ProbeWrite(@"embedded-probe-status.json", @{@"schema":@1,
            @"original_called":@(self.originalCount),
            @"server_status":ProbeObject(IdolyEmbeddedServerStatusJSON())});
    }];
    dispatch_async(dispatch_get_main_queue(), ^{
        // Two requests also exercise the gate's exactly-once forwarding policy.
        [self startUnity:application]; [self startUnity:application];
    });
    return YES;
}

// Exact Unity ABI: void return, instance receiver, selector, one object argument.
- (void)startUnity:(UIApplication *)application {
    ++self.originalCount;
    if (self.reportScheduled) return;
    self.reportScheduled = YES; [self.waitingTimer invalidate]; self.waitingTimer = nil;
    BOOL originalOnMain = NSThread.isMainThread;
    BOOL argumentMatches = application == UIApplication.sharedApplication;
    NSDictionary *status = ProbeObject(IdolyEmbeddedServerStatusJSON());
    IdolyEmbeddedServerCommand(@"{\"id\":1,\"action\":\"status\"}", ^(NSString *reply) {
        BOOL completionOnMain = NSThread.isMainThread;
        NSDictionary *hostStatus = ProbeHostStatus(reply);
        IdolyEmbeddedServerCryptoSelfTest(^(NSString *cryptoReply) {
            BOOL cryptoCompletionOnMain = NSThread.isMainThread;
            NSDictionary *nativeCrypto = ProbeObject(cryptoReply);
            dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
                NSDictionary *ports = @{@"grpc":@50051, @"assets":@8080,
                    @"grpc_connect":@(ProbePort(50051)), @"assets_connect":@(ProbePort(8080))};
                NSDictionary *crypto = ProbeCrypto();
                dispatch_async(dispatch_get_main_queue(), ^{
                    NSDictionary *report = @{@"schema":@1, @"original_called":@(self.originalCount),
                        @"main_thread":@(originalOnMain), @"application_argument_matches":@(argumentMatches),
                        @"command_completion_main_thread":@(completionOnMain), @"server_status":status,
                        @"crypto_completion_main_thread":@(cryptoCompletionOnMain), @"native_crypto":nativeCrypto,
                        @"host_status":hostStatus, @"ports":ports, @"commoncrypto":crypto};
                    BOOL written = ProbeWrite(@"embedded-probe.json", report);
                    if (!written) NSLog(@"Embedded server probe report write failed");
                    self.label.text = written ? @"Embedded server probe: original Unity start forwarded"
                                              : @"Embedded server probe: report write failed";
                });
            });
        });
    });
}
@end

int main(int argc, char *argv[]) {
    @autoreleasepool { return UIApplicationMain(argc, argv, nil, NSStringFromClass(UnityAppController.class)); }
}
