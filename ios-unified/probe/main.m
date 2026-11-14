// Simulator-only UIKit host. This fake Unity class never enters a game IPA.
#import <UIKit/UIKit.h>
#import <WebKit/WebKit.h>
#import "IdolyEmbeddedServer.h"
#import <CommonCrypto/CommonCryptor.h>
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <math.h>
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
    if (!documents || ![NSFileManager.defaultManager createDirectoryAtURL:documents
            withIntermediateDirectories:YES attributes:nil error:nil]) return NO;
    return [raw writeToURL:[documents URLByAppendingPathComponent:name] options:NSDataWritingAtomic error:nil];
}

static void ProbeFindButtons(UIViewController *screen, NSString *identifier, NSMutableArray<UIBarButtonItem *> *items) {
    if (!screen) return;
    if ([screen isKindOfClass:UINavigationController.class]) {
        UINavigationController *navigation = (UINavigationController *)screen;
        UINavigationItem *bar = navigation.topViewController.navigationItem;
        NSMutableOrderedSet<UIBarButtonItem *> *buttons = [NSMutableOrderedSet orderedSet];
        if (bar.leftBarButtonItem) [buttons addObject:bar.leftBarButtonItem];
        if (bar.rightBarButtonItem) [buttons addObject:bar.rightBarButtonItem];
        if (bar.leftBarButtonItems) [buttons addObjectsFromArray:bar.leftBarButtonItems];
        if (bar.rightBarButtonItems) [buttons addObjectsFromArray:bar.rightBarButtonItems];
        for (UIBarButtonItem *item in buttons) {
            if ([item.accessibilityIdentifier isEqualToString:identifier]
                    && navigation.topViewController.viewIfLoaded.window && ![items containsObject:item]) {
                [items addObject:item];
            }
        }
    }
    for (UIViewController *child in screen.childViewControllers) ProbeFindButtons(child, identifier, items);
    ProbeFindButtons(screen.presentedViewController, identifier, items);
}

static NSArray<UIBarButtonItem *> *ProbeVisibleLaunchButtons(void) {
    NSMutableOrderedSet<UIWindow *> *windows = [NSMutableOrderedSet orderedSetWithArray:UIApplication.sharedApplication.windows];
    for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
        if ([scene isKindOfClass:UIWindowScene.class]) {
            [windows addObjectsFromArray:((UIWindowScene *)scene).windows];
        }
    }
    NSMutableArray<UIBarButtonItem *> *items = [NSMutableArray array];
    for (UIWindow *window in windows) {
        if (!window.hidden && window.alpha > 0) ProbeFindButtons(window.rootViewController, @"idoly.game-start", items);
    }
    return items;
}

static NSDictionary *ProbeCornerGesture(UIWindow *window) {
    NSUInteger matching = 0, oneFinger = 0, threeFinger = 0;
    UILongPressGestureRecognizer *corner = nil;
    for (UIGestureRecognizer *recognizer in window.gestureRecognizers) {
        if (![recognizer.name isEqualToString:@"idoly.server-menu-corner"]) continue;
        ++matching;
        if (![recognizer isKindOfClass:UILongPressGestureRecognizer.class]) continue;
        UILongPressGestureRecognizer *hold = (UILongPressGestureRecognizer *)recognizer;
        if (hold.numberOfTouchesRequired == 1) { ++oneFinger; corner = hold; }
        if (hold.numberOfTouchesRequired == 3) ++threeFinger;
    }
    return @{@"game_window_key":@(window.isKeyWindow), @"matching_count":@(matching),
        @"recognizer_name":corner.name ?: (id)NSNull.null, @"one_finger_count":@(oneFinger),
        @"three_finger_count":@(threeFinger), @"minimum_press_seconds":@(corner.minimumPressDuration),
        @"allowable_movement_points":@(corner.allowableMovement), @"delegate_present":@((BOOL)(corner.delegate != nil)),
        @"delays_touches_began":@(corner.delaysTouchesBegan), @"delays_touches_ended":@(corner.delaysTouchesEnded),
        @"cancels_touches_in_view":@(corner.cancelsTouchesInView)};
}

// Simulator probe only; requires #import <WebKit/WebKit.h> and -framework WebKit.
// Inspect the real presented settings WKWebView. Does not mutate DOM/settings.
static WKWebView *ProbeFindSettingsWebBounded(UIView *root, NSUInteger *remaining) {
    if (!root || !*remaining) return nil;
    --(*remaining);
    if ([root isKindOfClass:WKWebView.class]) return (WKWebView *)root;
    for (UIView *child in root.subviews) {
        WKWebView *found = ProbeFindSettingsWebBounded(child, remaining);
        if (found) return found;
    }
    return nil;
}
static WKWebView *ProbeFindSettingsWeb(UIView *root) {
    NSUInteger remaining = 512;
    return ProbeFindSettingsWebBounded(root, &remaining);
}

static NSString *const ProbeSettingsDOMScript =
    @"(() => { const d=document.documentElement, b=document.body;"
     "const o=document.getElementById('options-fields'), p=document.getElementById('presentation-fields');"
     "const s=document.getElementById('render_scale_preset'), m=document.getElementById('max_buffer_pixel_preset');"
     "const has=(e,v)=>!!e&&Array.from(e.options).some(x=>x.value===v);"
     "const w=d?d.clientWidth:0, c=Math.max(d?d.scrollWidth:0,b?b.scrollWidth:0);"
     "return {ready:document.readyState==='complete'&&!!o&&!!p&&!o.disabled&&!p.disabled,"
     "forms_present:!!o&&!!p,scale_2_present:has(s,'2'),buffer_4096_present:has(m,'4096'),"
     "viewport_width:w,content_width:c,no_horizontal_overflow:w>0&&c<=w+2,"
     "select_count:document.querySelectorAll('select').length}; })()";

static void ProbeSettingsDOMAttempt(WKWebView *__weak weakWeb, NSMutableDictionary *state,
                                    void (^finish)(NSDictionary *)) {
    if ([state[@"finished"] boolValue]) return;
    WKWebView *web = weakWeb;
    if (!web) { finish(@{@"web_found":@NO, @"timed_out":@NO}); return; }
    [web evaluateJavaScript:ProbeSettingsDOMScript completionHandler:^(id value, NSError *error) {
        if ([state[@"finished"] boolValue]) return;
        NSMutableDictionary *metrics = [NSMutableDictionary dictionaryWithDictionary:
            @{@"web_found":@YES, @"timed_out":@NO, @"evaluation_succeeded":@((BOOL)(!error && [value isKindOfClass:NSDictionary.class]))}];
        if (!error && [value isKindOfClass:NSDictionary.class]) {
            for (NSString *key in @[@"ready", @"forms_present", @"scale_2_present", @"buffer_4096_present",
                    @"viewport_width", @"content_width", @"no_horizontal_overflow", @"select_count"]) {
                id scalar = value[key];
                if ([scalar isKindOfClass:NSNumber.class]) metrics[key] = scalar;
            }
        }
        state[@"last"] = metrics;
        // Retry only page/bridge readiness. A ready page with a wrong preset or
        // overflow is returned immediately for the caller's strict validator.
        if ([metrics[@"ready"] isEqual:@YES]) { finish(metrics); return; }
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC / 4), dispatch_get_main_queue(), ^{
            ProbeSettingsDOMAttempt(weakWeb, state, finish);
        });
    }];
}

static void ProbeSettingsDOM(WKWebView *web, void (^completion)(NSDictionary *)) {
    NSCAssert(NSThread.isMainThread, @"WK inspection belongs on main thread");
    BOOL webFound = web != nil;
    NSMutableDictionary *state = [NSMutableDictionary dictionaryWithDictionary:@{@"finished":@NO}];
    void (^finish)(NSDictionary *) = ^(NSDictionary *metrics) {
        if ([state[@"finished"] boolValue]) return;
        state[@"finished"] = @YES;
        completion(metrics);
    };
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        NSMutableDictionary *metrics = [state[@"last"] mutableCopy] ?: [NSMutableDictionary dictionary];
        metrics[@"web_found"] = @(webFound);
        metrics[@"timed_out"] = @YES;
        finish(metrics);
    });
    ProbeSettingsDOMAttempt(web, state, finish);
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

// Public Unity data API stand-in; no original device code is executed here.
// The stock public keyboard getter lazily creates the same keyboard singleton
// that Unity's initializer requires to be absent. Model that side effect so a
// launcher/UIKit query can expose the ordering regression in this fake host.
static UITextField *probeKeyboardField;
static NSUInteger probeKeyboardGetterCalls, probeKeyboardCreations;
@interface UnityFramework : NSObject
+ (instancetype)getInstance;
- (void)setDataBundleId:(const char *)identifier;
- (UITextField *)keyboardTextField;
@end
@implementation UnityFramework
+ (instancetype)getInstance {
    static UnityFramework *instance; static dispatch_once_t once;
    dispatch_once(&once, ^{ instance = [UnityFramework new]; }); return instance;
}
- (void)setDataBundleId:(const char *)identifier {
    NSString *name = identifier ? [NSString stringWithUTF8String:identifier] : nil;
    NSCAssert([name isEqualToString:@"local.idoly.client-data"], @"Unexpected data bundle");
    NSBundle *bundle = [NSBundle bundleWithIdentifier:name];
    NSCAssert(bundle && [NSFileManager.defaultManager fileExistsAtPath:
        [bundle.bundlePath stringByAppendingPathComponent:@"Data/Managed/Metadata/global-metadata.dat"]], @"Prepared language data missing");
}
- (UITextField *)keyboardTextField {
    ++probeKeyboardGetterCalls;
    if (!probeKeyboardField) {
        probeKeyboardField = [[UITextField alloc] initWithFrame:CGRectZero];
        ++probeKeyboardCreations;
    }
    return probeKeyboardField;
}
@end

static NSDictionary *ProbeKeyboardObservation(void) {
    UITextField *field = [[UnityFramework getInstance] keyboardTextField];
    NSDictionary *status = ProbeObject(IdolyEmbeddedServerStatusJSON());
    BOOL returnedNil = field == nil;
    BOOL initializedField = field != nil && field == probeKeyboardField;
    return @{@"guard_installed":ProbeScalar(status,@"keyboard_guard_installed"),
        @"ready":ProbeScalar(status,@"keyboard_ready"), @"phase":ProbeScalar(status,@"phase"),
        @"returned_nil":@(returnedNil), @"returned_initialized_field":@(initializedField),
        @"original_calls":@(probeKeyboardGetterCalls), @"field_creation_count":@(probeKeyboardCreations)};
}

@interface UnityAppController : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@property(nonatomic, strong) UILabel *label;
@property(nonatomic, strong) NSTimer *waitingTimer;
@property(nonatomic) NSUInteger originalCount;
@property(nonatomic) BOOL reportScheduled;
@property(nonatomic, strong) NSMutableDictionary *launcherProbe;
@property(nonatomic, copy) NSString *probeError;
@property(nonatomic) NSTimeInterval readySince;
@property(nonatomic) BOOL launchDispatched;
@property(nonatomic) BOOL captureDispatched;
@property(nonatomic, strong) NSDictionary *earlyStatus;
@property(nonatomic, strong) NSDictionary *menuCloseObservation;
@property(nonatomic, strong) NSMutableDictionary *keyboardProbe;
- (void)initUnityWithApplication:(UIApplication *)application __attribute__((objc_method_family(none)));
- (void)probeLauncher:(NSDictionary *)status;
- (void)recordCheckpoint:(NSString *)stage;
- (void)failProbe:(NSString *)code;
- (BOOL)observeKeyboard:(NSString *)name phase:(NSUInteger)phase ready:(BOOL)ready failure:(NSString *)code;
- (void)probeAfterOriginalReturnedOnMain:(BOOL)originalOnMain applicationMatches:(BOOL)argumentMatches;
- (void)probeMenuAfterLaunch:(NSMutableDictionary *)report;
- (void)observeMenuDismissal:(UINavigationController *)navigation report:(NSMutableDictionary *)report
                       menu:(NSMutableDictionary *)menu started:(NSTimeInterval)started observations:(NSUInteger)observations;
- (void)finishReport:(NSDictionary *)report;
@end

@implementation UnityAppController
- (void)failProbe:(NSString *)code {
    self.probeError = code;
    ProbeWrite(@"embedded-probe-status.json", @{@"schema":@1,
        @"original_called":@(self.originalCount), @"server_status":ProbeObject(IdolyEmbeddedServerStatusJSON()),
        @"probe_error":code, @"menu_close":self.menuCloseObservation ?: @{},
        @"keyboard":self.keyboardProbe.copy ?: @{}});
}
- (void)recordCheckpoint:(NSString *)stage {
    NSDictionary *status = ProbeObject(IdolyEmbeddedServerStatusJSON());
    ProbeWrite(@"embedded-probe-checkpoint.json", @{@"schema":@1, @"stage":stage,
        @"original_called":@(self.originalCount), @"phase":ProbeScalar(status, @"phase"),
        @"application_state":@(UIApplication.sharedApplication.applicationState),
        @"launch_requested":ProbeScalar(status, @"launch_requested"),
        @"launch_prepared":ProbeScalar(status, @"launch_prepared"),
        @"launcher_visible":ProbeScalar(status, @"launcher_visible"),
        @"keyboard_guard_installed":ProbeScalar(status,@"keyboard_guard_installed"),
        @"keyboard_ready":ProbeScalar(status,@"keyboard_ready"),
        @"menu_close":self.menuCloseObservation ?: @{}, @"keyboard":self.keyboardProbe.copy ?: @{}});
}
- (BOOL)observeKeyboard:(NSString *)name phase:(NSUInteger)phase ready:(BOOL)ready failure:(NSString *)code {
    NSDictionary *value = ProbeKeyboardObservation();
    self.keyboardProbe[name] = value;
    NSNumber *expectedCalls = ready ? @1 : @0;
    BOOL correct = [value[@"guard_installed"] isEqual:@YES] && [value[@"ready"] isEqual:@(ready)]
        && [value[@"phase"] isEqual:@(phase)] && [value[@"returned_nil"] isEqual:@((BOOL)!ready)]
        && [value[@"returned_initialized_field"] isEqual:@(ready)]
        && [value[@"original_calls"] isEqual:expectedCalls]
        && [value[@"field_creation_count"] isEqual:expectedCalls];
    if (!correct) [self failProbe:code];
    return correct;
}
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)application; (void)options;
    [self recordCheckpoint:@"delegate_entered"];
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *screen = [UIViewController new]; screen.view.backgroundColor = UIColor.systemBackgroundColor;
    self.label = [[UILabel alloc] initWithFrame:screen.view.bounds];
    self.label.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    self.label.textAlignment = NSTextAlignmentCenter; self.label.numberOfLines = 0;
    self.label.text = @"Embedded server probe: waiting for READY";
    [screen.view addSubview:self.label]; self.window.rootViewController = screen; [self.window makeKeyAndVisible];
    self.launcherProbe = [NSMutableDictionary dictionary];
    self.keyboardProbe = [NSMutableDictionary dictionary];
    [self recordCheckpoint:@"window_ready"];
    self.waitingTimer = [NSTimer scheduledTimerWithTimeInterval:0.25 repeats:YES block:^(NSTimer *timer) {
        (void)timer;
        NSDictionary *status = ProbeObject(IdolyEmbeddedServerStatusJSON());
        [self recordCheckpoint:[status[@"phase"] isEqual:@2] ? @"server_ready" : @"server_starting"];
        [self probeLauncher:status];
        ProbeWrite(@"embedded-probe-status.json", @{@"schema":@1,
            @"original_called":@(self.originalCount),
            @"server_status":status, @"probe_error":self.probeError ?: NSNull.null,
            @"keyboard":self.keyboardProbe.copy});
    }];
    dispatch_async(dispatch_get_main_queue(), ^{
        // The process-owned server must start before Unity reaches its hook.
        // An early launch request cannot create or forward a Unity invocation.
        IdolyEmbeddedServerLaunchGame();
        NSDictionary *status = ProbeObject(IdolyEmbeddedServerStatusJSON());
        self.launcherProbe[@"premature_phase"] = ProbeScalar(status, @"phase");
        self.launcherProbe[@"premature_original_called"] = @(self.originalCount);
        self.launcherProbe[@"premature_launch_requested"] = ProbeScalar(status, @"launch_requested");
        self.launcherProbe[@"premature_captured"] = ProbeScalar(status, @"captured");
        if (![status[@"phase"] isEqual:@1] || ![status[@"captured"] isEqual:@0] || self.originalCount != 0
                || ![status[@"launch_requested"] isEqual:@NO]) {
            self.probeError = @"premature_launch_not_ignored";
        }
        IdolyEmbeddedServerCommand(@"{\"id\":2718,\"action\":\"status\"}", ^(NSString *reply) {
            NSDictionary *value = ProbeObject(reply);
            NSDictionary *result = [value[@"result"] isKindOfClass:NSDictionary.class] ? value[@"result"] : @{};
            NSDictionary *native = [result[@"native"] isKindOfClass:NSDictionary.class] ? result[@"native"] : @{};
            self.earlyStatus = @{@"id":ProbeScalar(value,@"id"), @"ok":ProbeScalar(value,@"ok"),
                @"state":ProbeScalar(result,@"state"), @"running":ProbeScalar(result,@"running"),
                @"phase":ProbeScalar(native,@"phase"), @"captured":ProbeScalar(native,@"captured"),
                @"completion_main_thread":@(NSThread.isMainThread)};
            if (![value[@"id"] isEqual:@2718] || ![value[@"ok"] isEqual:@YES]
                    || ![result[@"state"] isEqual:@"starting"] || ![result[@"running"] isEqual:@NO]
                    || ![native[@"phase"] isEqual:@1] || ![native[@"captured"] isEqual:@0]
                    || !NSThread.isMainThread) [self failProbe:@"early_status_correlation_failed"];
        });
        [self recordCheckpoint:@"premature_launch_checked"];
    });
    return YES;
}

- (void)probeLauncher:(NSDictionary *)status {
    if (self.probeError || self.launchDispatched || self.reportScheduled) return;
    if (![status[@"phase"] isEqual:@2]) {
        if (self.readySince != 0) self.probeError = @"server_left_ready_before_launch";
        return;
    }
    if (!self.captureDispatched) {
        if (!self.earlyStatus) return;
        if (![status[@"captured"] isEqual:@0] || ![status[@"attempts"] isEqual:@1] || self.originalCount != 0) {
            [self failProbe:@"server_not_ready_before_capture"]; return;
        }
        self.launcherProbe[@"server_ready_before_capture"] = @YES;
        self.launcherProbe[@"uncaptured_original_called"] = @(self.originalCount);
        self.launcherProbe[@"uncaptured_attempts"] = ProbeScalar(status,@"attempts");
        if (![self observeKeyboard:@"before_capture" phase:2 ready:NO failure:@"keyboard_guard_before_capture_failed"]) return;
        [self recordCheckpoint:@"keyboard_before_capture_checked"];
        self.captureDispatched = YES;
        [self initUnityWithApplication:UIApplication.sharedApplication];
        [self initUnityWithApplication:UIApplication.sharedApplication];
        NSDictionary *captured = ProbeObject(IdolyEmbeddedServerStatusJSON());
        if (![captured[@"captured"] isEqual:@1] || ![captured[@"phase"] isEqual:@2]
                || ![captured[@"attempts"] isEqual:@1] || self.originalCount != 0) {
            [self failProbe:@"ready_capture_restarted_server"]; return;
        }
        self.launcherProbe[@"capture_after_ready_once"] = @YES;
        [self recordCheckpoint:@"unity_requests_captured"];
        return; // Observe the newly presented launcher on the next UIKit tick.
    }
    if (self.originalCount != 0) {
        self.probeError = @"unity_started_before_launch_button"; return;
    }
    if (![status[@"launcher_visible"] isEqual:@YES]) {
        self.probeError = @"ready_launcher_not_visible"; return;
    }
    if (![status[@"launch_requested"] isEqual:@NO] || ![status[@"launch_prepared"] isEqual:@NO]) {
        self.probeError = @"ready_launcher_flags_differ"; return;
    }
    NSArray<UIBarButtonItem *> *items = ProbeVisibleLaunchButtons();
    if (items.count != 1) {
        self.probeError = items.count ? @"ready_launch_button_ambiguous" : @"ready_launch_button_missing";
        return;
    }
    UIBarButtonItem *item = items.firstObject;
    if (!item.enabled) { self.probeError = @"ready_launch_button_disabled"; return; }
    if (![@[@"게임 시작", @"ゲーム開始", @"Start Game"] containsObject:item.title]) {
        self.probeError = @"ready_launch_button_title_differs"; return;
    }
    if (!item.target || !item.action) { self.probeError = @"ready_launch_action_missing"; return; }
    NSTimeInterval now = NSProcessInfo.processInfo.systemUptime;
    if (self.readySince == 0) self.readySince = now;
    NSUInteger observations = [self.launcherProbe[@"ready_observations"] unsignedIntegerValue] + 1;
    [self.launcherProbe addEntriesFromDictionary:@{@"ready_phase":@2,
        @"ready_original_called":@(self.originalCount), @"ready_launch_requested":@NO,
        @"ready_launch_prepared":@NO, @"ready_launcher_visible":@YES,
        @"ready_button_found":@YES, @"ready_button_enabled":@(item.enabled),
        @"ready_button_title":item.title, @"ready_observations":@(observations),
        @"ready_wait_seconds":@(now - self.readySince)}];
    // Remain Ready for a full second without forwarding Unity. This proves
    // readiness alone does not enter the game, before invoking the real UI.
    if (now - self.readySince < 1.0) return;
    if (![self observeKeyboard:@"before_launch" phase:2 ready:NO failure:@"keyboard_guard_before_launch_failed"]) return;
    [self recordCheckpoint:@"keyboard_before_launch_checked"];
    self.launchDispatched = YES;
    self.launcherProbe[@"button_dispatch_count"] = @1;
    [self recordCheckpoint:@"launch_action_requested"];
    BOOL dispatched = [UIApplication.sharedApplication sendAction:item.action to:item.target from:item forEvent:nil];
    self.launcherProbe[@"button_action_dispatched"] = @(dispatched);
    [self recordCheckpoint:@"launch_action_dispatched"];
    if (!dispatched) { self.probeError = @"ready_launch_action_not_dispatched"; return; }
    // Repeated clicks must not forward Unity a second time.
    IdolyEmbeddedServerLaunchGame();
    self.launcherProbe[@"duplicate_launch_called"] = @YES;
}

// Exact Unity ABI: void return, instance receiver, selector, one object argument.
- (void)initUnityWithApplication:(UIApplication *)application {
    ++self.originalCount;
    self.launcherProbe[@"forwarded_after_button"] = @(self.launchDispatched);
    [self recordCheckpoint:@"unity_forwarded"];
    if (self.reportScheduled) return;
    self.reportScheduled = YES; [self.waitingTimer invalidate]; self.waitingTimer = nil;
    BOOL originalOnMain = NSThread.isMainThread;
    BOOL argumentMatches = application == UIApplication.sharedApplication;
    // phase=Running is already set by the native gate here. Its separate
    // keyboard-ready flag must remain false through the original invocation.
    if (![self observeKeyboard:@"during_init" phase:4 ready:NO failure:@"keyboard_guard_during_init_failed"]) return;
    [self recordCheckpoint:@"keyboard_during_init_checked"];
    if (probeKeyboardField || probeKeyboardCreations != 0) {
        [self failProbe:@"keyboard_created_before_initialize"]; return;
    }
    probeKeyboardField = [[UITextField alloc] initWithFrame:CGRectZero];
    ++probeKeyboardCreations;
    // This continuation cannot execute until the fake original IMP returns
    // and the native gate marks that invocation fully complete.
    dispatch_async(dispatch_get_main_queue(), ^{
        [self probeAfterOriginalReturnedOnMain:originalOnMain applicationMatches:argumentMatches];
    });
}
- (void)probeAfterOriginalReturnedOnMain:(BOOL)originalOnMain applicationMatches:(BOOL)argumentMatches {
    if (![self observeKeyboard:@"after_init" phase:4 ready:YES failure:@"keyboard_guard_after_init_failed"]) return;
    [self recordCheckpoint:@"keyboard_after_init_checked"];
    NSDictionary *status = ProbeObject(IdolyEmbeddedServerStatusJSON());
    IdolyEmbeddedServerCommand(@"{\"id\":1,\"action\":\"status\"}", ^(NSString *reply) {
        [self recordCheckpoint:@"status_received"];
        BOOL completionOnMain = NSThread.isMainThread;
        NSDictionary *hostStatus = ProbeHostStatus(reply);
        IdolyEmbeddedServerCryptoSelfTest(^(NSString *cryptoReply) {
            [self recordCheckpoint:@"crypto_received"];
            BOOL cryptoCompletionOnMain = NSThread.isMainThread;
            NSDictionary *nativeCrypto = ProbeObject(cryptoReply);
            dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
                NSDictionary *ports = @{@"grpc":@50051, @"assets":@8080,
                    @"grpc_connect":@(ProbePort(50051)), @"assets_connect":@(ProbePort(8080))};
                NSDictionary *crypto = ProbeCrypto();
                dispatch_async(dispatch_get_main_queue(), ^{
                    [self recordCheckpoint:@"loopback_checked"];
                    NSMutableDictionary *report = [@{@"schema":@1, @"original_called":@(self.originalCount),
                        @"main_thread":@(originalOnMain), @"application_argument_matches":@(argumentMatches),
                        @"command_completion_main_thread":@(completionOnMain), @"server_status":status,
                        @"launcher":self.launcherProbe.copy,
                        @"keyboard":self.keyboardProbe.copy,
                        @"early_status":self.earlyStatus ?: @{},
                        @"corner_gesture":ProbeCornerGesture(self.window),
                        @"crypto_completion_main_thread":@(cryptoCompletionOnMain), @"native_crypto":nativeCrypto,
                        @"host_status":hostStatus, @"ports":ports, @"commoncrypto":crypto} mutableCopy];
                    [self probeMenuAfterLaunch:report];
                });
            });
        });
    });
}
- (void)finishReport:(NSDictionary *)report {
    BOOL written = ProbeWrite(@"embedded-probe.json", report);
    if (!written) { [self failProbe:@"final_report_write_failed"]; return; }
    [self recordCheckpoint:@"report_written"];
    self.label.text = @"Embedded server probe: startup, menu close and listeners verified";
}
- (void)probeMenuAfterLaunch:(NSMutableDictionary *)report {
    UILongPressGestureRecognizer *corner = nil;
    for (UIGestureRecognizer *item in self.window.gestureRecognizers)
        if ([item.name isEqualToString:@"idoly.server-menu-corner"]
                && [item isKindOfClass:UILongPressGestureRecognizer.class]) corner = (UILongPressGestureRecognizer *)item;
    SEL open = NSSelectorFromString(@"openMenu:");
    id target = corner.delegate;
    if (!corner || ![target respondsToSelector:open]
            || ![UIApplication.sharedApplication sendAction:open to:target from:corner forEvent:nil]) {
        [self failProbe:@"settings_menu_open_failed"]; return;
    }
    [self recordCheckpoint:@"settings_menu_requested"];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC / 2), dispatch_get_main_queue(), ^{
        UIViewController *presented = self.window.rootViewController.presentedViewController;
        if (![presented isKindOfClass:UINavigationController.class] || !presented.viewIfLoaded.window) {
            [self failProbe:@"settings_menu_not_presented"]; return;
        }
        UINavigationController *navigation = (UINavigationController *)presented;
        NSMutableArray<UIBarButtonItem *> *buttons = [NSMutableArray array];
        ProbeFindButtons(navigation, @"idoly.server-close", buttons);
        NSMutableArray<UIBarButtonItem *> *serverButtons = [NSMutableArray array];
        ProbeFindButtons(navigation, @"idoly.server-start", serverButtons);
        CGFloat width = CGRectGetWidth(navigation.view.bounds), windowWidth = CGRectGetWidth(self.window.bounds);
        BOOL fullScreen = navigation.modalPresentationStyle == UIModalPresentationFullScreen;
        BOOL widthMatches = width > 0 && windowWidth > 0 && fabs(width - windowWidth) <= 2.0;
        if (buttons.count != 1 || !buttons.firstObject.target || !buttons.firstObject.action
                || !buttons.firstObject.enabled || serverButtons.count != 1 || serverButtons.firstObject.enabled
                || !fullScreen || !widthMatches) {
            [self failProbe:@"settings_menu_controls_or_layout_failed"]; return;
        }
        UIBarButtonItem *close = buttons.firstObject;
        NSMutableDictionary *menu = [@{@"opened_via_owned_menu_target":@YES,
            @"full_screen":@(fullScreen), @"frame_width_matches":@(widthMatches),
            @"frame_width":@(width), @"window_width":@(windowWidth), @"return_button_found":@YES,
            @"server_control_found":@YES, @"server_control_disabled_while_running":@YES} mutableCopy];
        ProbeSettingsDOM(ProbeFindSettingsWeb(navigation.topViewController.view), ^(NSDictionary *metrics) {
            menu[@"web"] = metrics;
            if (![metrics[@"web_found"] isEqual:@YES] || ![metrics[@"ready"] isEqual:@YES]
                    || ![metrics[@"evaluation_succeeded"] isEqual:@YES]
                    || ![metrics[@"scale_2_present"] isEqual:@YES] || ![metrics[@"buffer_4096_present"] isEqual:@YES]
                    || ![metrics[@"no_horizontal_overflow"] isEqual:@YES]) {
                [self failProbe:@"settings_web_readiness_or_layout_failed"]; return;
            }
            BOOL closed = [UIApplication.sharedApplication sendAction:close.action to:close.target from:close forEvent:nil];
            menu[@"return_action_dispatched"] = @(closed);
            if (!closed) { [self failProbe:@"settings_return_action_failed"]; return; }
            [self recordCheckpoint:@"settings_return_requested"];
            [self observeMenuDismissal:navigation report:report menu:menu
                              started:NSProcessInfo.processInfo.systemUptime observations:0];
        });
    });
}
- (void)observeMenuDismissal:(UINavigationController *)navigation report:(NSMutableDictionary *)report
                       menu:(NSMutableDictionary *)menu started:(NSTimeInterval)started observations:(NSUInteger)observations {
    NSCAssert(NSThread.isMainThread, @"Dismissal observation belongs on main thread");
    UIViewController *presented = self.window.rootViewController.presentedViewController;
    BOOL noPresented = presented == nil, detached = navigation.viewIfLoaded.window == nil;
    BOOL key = self.window.isKeyWindow;
    NSTimeInterval elapsed = NSProcessInfo.processInfo.systemUptime - started;
    BOOL complete = noPresented && detached && key;
    BOOL timedOut = !complete && elapsed >= 6.0;
    self.menuCloseObservation = @{@"presented_controller_remaining":@((BOOL)!noPresented),
        @"settings_controller_still_presented":@((BOOL)(presented == navigation)),
        @"settings_view_attached":@((BOOL)!detached),
        @"settings_is_being_dismissed":@((BOOL)(navigation.isBeingDismissed || navigation.topViewController.isBeingDismissed)),
        @"game_window_key":@(key), @"application_state":@(UIApplication.sharedApplication.applicationState),
        @"observations":@(observations + 1), @"wait_seconds":@(elapsed), @"timed_out":@(timedOut)};
    [self recordCheckpoint:timedOut ? @"settings_return_timeout" : @"settings_return_observed"];
    if (complete) {
        menu[@"dismissed"] = @YES; menu[@"menu_view_detached_after_close"] = @YES;
        menu[@"game_window_key_after_close"] = @YES;
        menu[@"dismiss_observation"] = self.menuCloseObservation;
        [self recordCheckpoint:@"settings_menu_dismissed"];
        IdolyEmbeddedServerCommand(@"{\"id\":2,\"action\":\"status\"}", ^(NSString *reply) {
            menu[@"status_completion_main_thread"] = @(NSThread.isMainThread);
            menu[@"host_status_after_close"] = ProbeHostStatus(reply);
            dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
                BOOL grpc = ProbePort(50051), assets = ProbePort(8080);
                dispatch_async(dispatch_get_main_queue(), ^{
                    menu[@"grpc_connected_after_close"] = @(grpc);
                    menu[@"assets_connected_after_close"] = @(assets);
                    report[@"menu_lifetime"] = menu;
                    [self finishReport:report];
                });
            });
        });
    } else if (timedOut) [self failProbe:@"settings_menu_not_dismissed"];
    else dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC / 10), dispatch_get_main_queue(), ^{
        [self observeMenuDismissal:navigation report:report menu:menu started:started observations:observations + 1];
    });
}
@end

int main(int argc, char *argv[]) {
    @autoreleasepool { return UIApplicationMain(argc, argv, nil, NSStringFromClass(UnityAppController.class)); }
}
