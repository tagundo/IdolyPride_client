#import <Foundation/Foundation.h>
#import <dispatch/dispatch.h>
#import <objc/runtime.h>
#import "../IdolyUnityHost.h"
#import "../IdolyClientData.h"
#import "UnityHostFoundationUIKit.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <sys/socket.h>
#include <unistd.h>
#include <errno.h>

#if !IDOLY_SMOKE_SIMULATOR || !IDOLY_UNITY_HOST_FOUNDATION_TESTING
#error This fixture requires the explicit Foundation-only smoke configuration.
#endif

@interface IDUnityHostFixtureConstructor : NSObject
+ (NSDictionary *)fixtureInfo;
@end
@interface UIWindow (FixtureObservation)
+ (UIWindow *)fixtureKeyWindow;
+ (unsigned)fixtureWindowCreations;
@end
@interface NSObject (FixtureApplicationCallbacks)
@property(nonatomic, strong) UIWindow *window;
- (BOOL)application:(UIApplication *)app didFinishLaunchingWithOptions:(NSDictionary *)options;
- (void)applicationWillEnterForeground:(UIApplication *)app;
- (void)applicationDidBecomeActive:(UIApplication *)app;
- (BOOL)application:(UIApplication *)app openURL:(NSURL *)url options:(NSDictionary *)options;
- (BOOL)application:(UIApplication *)app continueUserActivity:(NSUserActivity *)activity
    restorationHandler:(void (^)(NSArray *))handler;
@end

static void Require(BOOL condition, const char *message) {
    if (!condition) { fprintf(stderr, "FAIL_UNITY_HOST: %s\n", message); exit(1); }
}
static BOOL runtimeInitialized;
static unsigned adapterMainCalls, originalMainCalls, embeddedCalls, originalWarmups;
static unsigned sigpipeEpipeWrites;
static unsigned readyObserverCalls, canaryReads, setterCalls, restorationCalls, cachedRootReads;
static NSString *cachedRoot, *warmupCanary;
static UIApplication *fixtureApplication;
static id hostDelegate;
static UIWindow *placeholder;
static NSMutableArray *lifecycle, *events;
static NSDictionary *fixtureLaunchOptions;

@interface IDFixtureUnityController : NSObject
@property(nonatomic, strong) UIWindow *window;
@end
@implementation IDFixtureUnityController
- (BOOL)application:(UIApplication *)app didFinishLaunchingWithOptions:(NSDictionary *)options {
    Require(app == fixtureApplication && [options isEqual:fixtureLaunchOptions], "embedded_launch_options_changed");
    Require(self.window && self.window != placeholder, "unity_window_not_distinct");
    [self.window makeKeyAndVisible];
    [lifecycle addObject:@"finish"];
    return YES;
}
- (void)applicationWillEnterForeground:(UIApplication *)app {
    Require(app == fixtureApplication, "foreground_application_changed");
    [lifecycle addObject:@"foreground"];
}
- (void)applicationDidBecomeActive:(UIApplication *)app {
    Require(app == fixtureApplication, "active_application_changed");
    [lifecycle addObject:@"active"];
}
- (BOOL)application:(UIApplication *)app openURL:(NSURL *)url options:(NSDictionary *)options {
    Require(app == fixtureApplication && url != nil && lifecycle.count >= 3, "url_delivered_before_runtime");
    [events addObject:options[@"index"]];
    return YES;
}
- (BOOL)application:(UIApplication *)app continueUserActivity:(NSUserActivity *)activity
    restorationHandler:(void (^)(NSArray *))handler {
    Require(app == fixtureApplication && lifecycle.count >= 3, "activity_delivered_before_runtime");
    [events addObject:activity.userInfo[@"index"]];
    handler(@[]);
    return YES;
}
@end
static IDFixtureUnityController *unityController;

@interface UnityFramework : NSObject
@property(nonatomic) unsigned fixtureRunCount;
@property(nonatomic) const char *fixtureIdentifier;
- (void)runUIApplicationMainWithArgc:(int)argc argv:(char **)argv;
- (void)runEmbeddedWithArgc:(int)argc argv:(char **)argv appLaunchOpts:(NSDictionary *)options;
- (void)frameworkWarmup:(int)argc argv:(char **)argv;
- (id)appController;
- (void)setDataBundleId:(const char *)identifier;
@end
@implementation UnityFramework
- (void)runUIApplicationMainWithArgc:(int)argc argv:(char **)argv {
    (void)argc; (void)argv;
    ++originalMainCalls;
}
- (void)frameworkWarmup:(int)argc argv:(char **)argv {
    Require(argc > 0 && argv && !runtimeInitialized && self.fixtureRunCount == 0, "warmup_not_cold");
    ++originalWarmups;
    NSBundle *bundle = [NSBundle bundleWithIdentifier:IDClientDataBundleIdentifier];
    warmupCanary = [NSString stringWithContentsOfFile:
        [bundle.bundlePath stringByAppendingPathComponent:@"Data/fixture.canary"]
        encoding:NSUTF8StringEncoding error:NULL];
    ++canaryReads;
    Require([warmupCanary isEqual:@"fixture-en-data"], "warmup_consumed_wrong_language");
    runtimeInitialized = YES;
}
- (void)runEmbeddedWithArgc:(int)argc argv:(char **)argv appLaunchOpts:(NSDictionary *)options {
    ++embeddedCalls;
    Require(IDUnityHostIsLaunching() && !runtimeInitialized && self.fixtureRunCount == 0,
        "embedded_not_cold");
    [self frameworkWarmup:argc argv:argv];
    unityController.window = [UIWindow new];
    unityController.window.rootViewController = [UIViewController new];
    [unityController application:fixtureApplication didFinishLaunchingWithOptions:options];
    [unityController applicationWillEnterForeground:fixtureApplication];
    [unityController applicationDidBecomeActive:fixtureApplication];
    self.fixtureRunCount += 1;
}
- (id)appController { return unityController; }
- (void)setDataBundleId:(const char *)identifier {
    self.fixtureIdentifier = identifier;
    ++setterCalls;
}
@end

@interface IDUnityHostFixtureObserver : NSObject
+ (void)hostReady;
@end
@implementation IDUnityHostFixtureObserver
+ (void)hostReady {
    ++readyObserverCalls;
    NSDictionary *info = IDUnityHostInfo();
    Require([info[@"host_ready"] isEqual:@YES] && [info[@"runtime_start_calls"] isEqual:@0]
        && cachedRootReads == 0 && !runtimeInitialized, "ready_initialized_unity");
}
@end

static BOOL PreRuntime(void) { return !runtimeInitialized; }
static unsigned RunCount(id framework) { return [(UnityFramework *)framework fixtureRunCount]; }
static const char *CachedBundleRoot(void) {
    ++cachedRootReads;
    if (!cachedRoot) cachedRoot = [NSBundle bundleWithIdentifier:IDClientDataBundleIdentifier].bundlePath;
    return cachedRoot.UTF8String;
}
static id AppController(id framework) { return [(UnityFramework *)framework appController]; }
static void BeforeHostReady(id application, id delegate) {
    fixtureApplication = application;
    hostDelegate = delegate;
    placeholder = [delegate window];
    Require(placeholder != nil && [UIWindow fixtureWindowCreations] == 1, "placeholder_not_created");
    [placeholder makeKeyAndVisible];
    [delegate applicationDidBecomeActive:application];
    Require(lifecycle.count == 0, "lifecycle_forwarded_before_start");
    NSString *huge = [@"x" stringByPaddingToLength:32769 withString:@"x" startingAtIndex:0];
    Require(![delegate application:application openURL:[NSURL URLWithString:@"fixture://invalid"]
        options:@{@"oversized":huge}], "oversized_event_accepted");
    for (unsigned i = 0; i < 8; ++i) {
        BOOL accepted;
        if (!(i & 1)) {
            accepted = [delegate application:application
                openURL:[NSURL URLWithString:[NSString stringWithFormat:@"fixture://event/%u", i]]
                options:@{@"index":@(i)}];
        } else {
            NSUserActivity *activity = [[NSUserActivity alloc] initWithActivityType:@"fixture.activity"];
            activity.userInfo = @{@"index":@(i)};
            accepted = [delegate application:application continueUserActivity:activity
                restorationHandler:^(NSArray *items) { (void)items; ++restorationCalls; }];
        }
        Require(accepted, "bounded_event_rejected");
    }
    Require(![delegate application:application openURL:[NSURL URLWithString:@"fixture://ninth"]
        options:@{@"index":@8}] && events.count == 0, "event_limit_or_deferral_failed");
}
static int ApplicationMain(int argc, char **argv, NSString *principal, NSString *delegateName) {
    Require(argc > 0 && argv && !principal && delegateName.length > 0, "application_main_arguments_changed");
    ++adapterMainCalls;
    UIApplication *app = [UIApplication new];
    id delegate = [NSClassFromString(delegateName) new];
    Require(delegate != nil, "host_delegate_missing");
    app.delegate = delegate;
    Require([delegate application:app didFinishLaunchingWithOptions:fixtureLaunchOptions],
        "host_did_finish_failed");
    [delegate applicationDidBecomeActive:app];
    Require(lifecycle.count == 0 && events.count == 0, "host_forwarded_before_game_start");
    return 0; // Only this Foundation fixture returns from its fake UIKit loop.
}
static NSURL *MakeBundle(NSURL *root, NSString *language) {
    NSURL *bundle = [root URLByAppendingPathComponent:[language stringByAppendingString:@".bundle"] isDirectory:YES];
    NSURL *data = [bundle URLByAppendingPathComponent:@"Data" isDirectory:YES];
    Require([NSFileManager.defaultManager createDirectoryAtURL:data withIntermediateDirectories:YES
        attributes:nil error:NULL], "fixture_bundle_create_failed");
    NSDictionary *info = @{@"CFBundleIdentifier":IDClientDataBundleIdentifier, @"CFBundlePackageType":@"BNDL",
        @"CFBundleVersion":@"1", @"IdolyClientLanguage":language};
    NSData *raw = [NSPropertyListSerialization dataWithPropertyList:info
        format:NSPropertyListXMLFormat_v1_0 options:0 error:NULL];
    Require([raw writeToURL:[bundle URLByAppendingPathComponent:@"Info.plist"] atomically:YES],
        "fixture_info_write_failed");
    Require([[NSString stringWithFormat:@"fixture-%@-data", language]
        writeToURL:[data URLByAppendingPathComponent:@"fixture.canary"] atomically:YES
        encoding:NSUTF8StringEncoding error:NULL], "fixture_canary_write_failed");
    return bundle;
}

int main(int argc, char **argv) {
    @autoreleasepool {
        // This is the first fixture action. Installation must come from dyld.
        Require([IDUnityHostInfo()[@"installed"] isEqual:@YES], "constructor_did_not_install_before_main");
        NSDictionary *constructor = [IDUnityHostFixtureConstructor fixtureInfo];
        Require([constructor[@"constructor_calls"] isEqual:@1] && [constructor[@"installed"] isEqual:@YES]
            && [constructor[@"ready_calls"] isEqual:@0], "constructor_visibility_invalid");
        Require([constructor[@"sigpipe_default_before_install"] isEqual:@YES]
            && [constructor[@"sigpipe_ignored_after_install"] isEqual:@YES]
            && [constructor[@"other_signal_handlers_preserved"] isEqual:@YES],
            "constructor_sigpipe_proof_missing");
        struct sigaction pipeAction;
        Require(sigaction(SIGPIPE, NULL, &pipeAction) == 0 && pipeAction.sa_handler == SIG_IGN
            && [IDUnityHostInfo()[@"sigpipe_ignored_before_server"] isEqual:@YES],
            "sigpipe_not_ignored_before_server");
        int descriptors[2];
        Require(socketpair(AF_UNIX, SOCK_STREAM, 0, descriptors) == 0, "plain_socketpair_failed");
        Require(close(descriptors[1]) == 0, "peer_socket_close_failed");
        errno = 0;
        ssize_t written = write(descriptors[0], "x", 1);
        int writeError = errno;
        close(descriptors[0]);
        Require(written == -1 && writeError == EPIPE, "plain_closed_socket_did_not_return_epipe");
        ++sigpipeEpipeWrites;
        NSString *mode = argc == 2 ? [NSString stringWithUTF8String:argv[1]] : nil;
        Require([@[@"--cold", @"--stale-cache", @"--pre-runtime"] containsObject:mode], "invalid_mode");
        lifecycle = [NSMutableArray new]; events = [NSMutableArray new];
        fixtureLaunchOptions = @{@"fixture_launch":@"preserved"};
        unityController = [IDFixtureUnityController new];
        UnityFramework *framework = [UnityFramework new];
        IDUnityHostSmokeHooks hooks = {ApplicationMain, PreRuntime, RunCount, CachedBundleRoot,
            AppController, BeforeHostReady};
        Require(!IDUnityHostRegisterSmokeHooks(NULL), "null_smoke_table_accepted");
        for (unsigned i = 0; i < 6; ++i) {
            IDUnityHostSmokeHooks bad = hooks;
            switch (i) {
                case 0: bad.application_main = NULL; break;
                case 1: bad.pre_runtime = NULL; break;
                case 2: bad.run_count = NULL; break;
                case 3: bad.cached_bundle_root = NULL; break;
                case 4: bad.app_controller = NULL; break;
                default: bad.before_host_ready = NULL; break;
            }
            Require(!IDUnityHostRegisterSmokeHooks(&bad), "partial_smoke_table_accepted");
        }
        __block BOOL offMainRejected = NO;
        dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
            offMainRejected = !IDUnityHostRegisterSmokeHooks(&hooks);
            dispatch_semaphore_signal(semaphore);
        });
        Require(dispatch_semaphore_wait(semaphore, dispatch_time(DISPATCH_TIME_NOW, 5*NSEC_PER_SEC)) == 0
            && offMainRejected, "off_main_smoke_registration_accepted");
        Require(IDUnityHostRegisterSmokeHooks(&hooks), "valid_smoke_registration_failed");
        Require(!IDUnityHostRegisterSmokeHooks(&hooks), "smoke_registration_repeated");
        hooks.application_main = NULL; // The helper must own its registered copy.
        NSString *error = nil;
        Require(!IDUnityHostStartGame(@"/not-selected/en.bundle", &error)
            && [error isEqual:@"start_rejected"] && adapterMainCalls == 0,
            "start_before_capture_entered_uikit");
        BOOL preRuntime = [mode isEqual:@"--pre-runtime"];
        if (preRuntime) runtimeInitialized = YES;
        [framework runUIApplicationMainWithArgc:argc argv:argv];
        Require(originalMainCalls == 0, "original_run_main_not_intercepted");
        NSURL *temporary = nil;
        NSMutableDictionary *checks = [@{@"constructor_before_main":@YES,
            @"registration_after_constructor":@YES, @"smoke_table_copy":@YES,
            @"main_entry_intercepted":@YES, @"start_before_capture_rejected":@YES,
            @"sigpipe_default_before_install":@YES, @"sigpipe_ignored_before_server":@YES,
            @"plain_closed_socket_epipe":@YES, @"other_signal_handlers_preserved":@YES} mutableCopy];
        NSArray *embeddedLifecycle = @[];
        if (preRuntime) {
            NSDictionary *info = IDUnityHostInfo();
            Require([info[@"failed"] isEqual:@YES]
                && [info[@"error"] isEqual:@"runtime_initialized_before_host"]
                && adapterMainCalls == 0 && readyObserverCalls == 0 && embeddedCalls == 0
                && cachedRootReads == 0, "pre_runtime_entered_application_main");
            [checks addEntriesFromDictionary:@{@"runtime_before_capture_rejected":@YES,
                @"application_main_not_entered":@YES, @"runtime_not_started":@YES}];
        } else {
            Require(adapterMainCalls == 1 && readyObserverCalls == 1 && !runtimeInitialized
                && cachedRootReads == 0 && [IDUnityHostInfo()[@"queued_events"] isEqual:@8],
                "host_not_ready_and_cold");
            temporary = [[NSURL fileURLWithPath:NSTemporaryDirectory() isDirectory:YES]
                URLByAppendingPathComponent:[@"idoly-unity-host-" stringByAppendingString:NSUUID.UUID.UUIDString]
                isDirectory:YES];
            NSURL *root = [temporary URLByAppendingPathComponent:@"client-data" isDirectory:YES];
            NSURL *ko = MakeBundle(root, @"ko"), *en = MakeBundle(root, @"en");
            NSError *selectionError = nil;
            Require(IDClientDataSelectBundle(en, root, framework, &selectionError)
                && !selectionError && setterCalls == 1
                && !strcmp(framework.fixtureIdentifier, "local.idoly.client-data"),
                "real_client_data_selection_failed");
            if ([mode isEqual:@"--stale-cache"]) {
                cachedRoot = ko.path;
                Require(!IDUnityHostStartGame(en.path, &error) && [error isEqual:@"cached_bundle_root_mismatch"]
                    && embeddedCalls == 0 && originalWarmups == 0 && events.count == 0
                    && !runtimeInitialized && [IDUnityHostInfo()[@"runtime_start_calls"] isEqual:@0],
                    "stale_ko_cache_started_runtime");
                [checks addEntriesFromDictionary:@{@"stale_cached_ko_rejected":@YES,
                    @"runtime_not_started":@YES, @"queued_events_not_delivered":@YES}];
            } else {
                Require(!IDUnityHostStartGame(ko.path, &error)
                    && [error isEqual:@"selected_bundle_mismatch"] && embeddedCalls == 0,
                    "wrong_selected_root_accepted");
                Require(IDUnityHostStartGame(en.path, &error) && !error, "cold_embedded_start_failed");
                embeddedLifecycle = [lifecycle copy];
                Require([embeddedLifecycle isEqual:@[@"finish", @"foreground", @"active"]],
                    "embedded_lifecycle_order_or_active_replay_changed");
                Require(embeddedCalls == 1 && originalWarmups == 1 && framework.fixtureRunCount == 1
                    && canaryReads == 1 && [warmupCanary isEqual:@"fixture-en-data"],
                    "cold_runtime_or_canary_invalid");
                Require([UIWindow fixtureWindowCreations] == 2 && unityController.window != placeholder
                    && [hostDelegate window] == unityController.window && placeholder.hidden
                    && [unityController.window.rootViewController isKindOfClass:UIViewController.class]
                    && unityController.window.windowLevel == UIWindowLevelNormal
                    && [UIWindow fixtureKeyWindow] == unityController.window
                    && [IDUnityHostInfo()[@"unity_window_bound"] isEqual:@YES],
                    "placeholder_not_retired_for_unity_window");
                Require([events isEqual:@[@0,@1,@2,@3,@4,@5,@6,@7]] && restorationCalls == 4
                    && [IDUnityHostInfo()[@"queued_events"] isEqual:@0]
                    && [IDUnityHostInfo()[@"lifecycle_forwarded"] isEqual:@0], "pending_event_replay_changed");
                [hostDelegate applicationDidBecomeActive:fixtureApplication];
                Require(lifecycle.count == 4 && [lifecycle.lastObject isEqual:@"active"],
                    "post_start_lifecycle_not_forwarded");
                Require([hostDelegate application:fixtureApplication openURL:[NSURL URLWithString:@"fixture://post"]
                    options:@{@"index":@8}] && events.count == 9, "post_start_url_not_forwarded");
                Require(!IDUnityHostStartGame(en.path, &error) && [error isEqual:@"start_rejected"]
                    && embeddedCalls == 1, "duplicate_runtime_start_accepted");
                [checks addEntriesFromDictionary:@{@"selected_bundle_before_warmup":@YES,
                    @"first_warmup_canary_en":@YES, @"single_embedded_start":@YES,
                    @"lifecycle_original_order":@YES, @"no_active_replay":@YES,
                    @"queued_event_limit":@YES, @"queued_event_order":@YES,
                    @"post_start_forwarding":@YES, @"duplicate_start_rejected":@YES,
                    @"wrong_selected_root_rejected":@YES, @"two_distinct_windows":@YES,
                    @"unity_window_adopted":@YES, @"placeholder_retired":@YES,
                    @"normal_game_window":@YES, @"game_root_controller":@YES}];
            }
        }
        NSDictionary *result = @{@"schema":@1, @"status":@"PASS",
            @"mode":[mode substringFromIndex:2], @"actual_macos_foundation_execution":@YES,
            @"actual_dylib_constructor_execution":@YES, @"actualOriginalUnity":@NO,
            @"physical_PlayCover_execution":@NO, @"windows_or_simulators_created":@NO,
            @"constructor_before_main":@YES, @"sigpipe_ignored_before_server":@YES,
            @"sigpipe_plain_write_epipe":@YES, @"other_signal_handlers_preserved":@YES,
            @"constructor":[IDUnityHostFixtureConstructor fixtureInfo],
            @"host":IDUnityHostInfo(), @"checks":checks, @"embedded_lifecycle":embeddedLifecycle,
            @"events":[events copy], @"canary":warmupCanary ?: NSNull.null,
            @"counts":@{@"original_run_main":@(originalMainCalls), @"application_main":@(adapterMainCalls),
                @"original_embedded":@(embeddedCalls), @"original_warmup":@(originalWarmups),
                @"run_count":@(framework.fixtureRunCount), @"canary_reads":@(canaryReads),
                @"setter_calls":@(setterCalls), @"ready_observer":@(readyObserverCalls),
                @"restorations":@(restorationCalls), @"windows":@([UIWindow fixtureWindowCreations]),
                @"sigpipe_epipe_writes":@(sigpipeEpipeWrites)}};
        NSData *json = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingSortedKeys error:NULL];
        Require(json != nil, "fixture_json_serialization_failed");
        fwrite(json.bytes, 1, json.length, stdout); fputc('\n', stdout);
        if (temporary) Require([NSFileManager.defaultManager removeItemAtURL:temporary error:NULL],
            "owned_fixture_cleanup_failed");
    }
    return 0;
}
