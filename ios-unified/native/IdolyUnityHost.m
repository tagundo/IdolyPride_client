#import "IdolyUnityHost.h"
#import "IdolyClientData.h"
#include "UnityHostPolicy.h"
#import <objc/runtime.h>
#import <objc/message.h>
#include <dlfcn.h>
#include <limits.h>
#include <string.h>
#include <stdlib.h>
#import <dispatch/dispatch.h>
#if IDOLY_UNITY_HOST_FOUNDATION_TESTING
#import "tests/UnityHostFoundationUIKit.h"
#else
#import <UIKit/UIKit.h>
#endif
#if !IDOLY_SMOKE_SIMULATOR
#include "UnityHostProfile.h"
#include <mach-o/loader.h>
#include <mach/vm_prot.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#endif

@interface IDUnityHostDelegate : NSObject <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@end

static IDUnityHostPolicy host;
static IDUnityHostReadyCallback readyCallback;
static Class frameworkClass;
static Method runMainMethod, warmupMethod;
static IMP originalEmbedded, originalWarmup;
static id capturedFramework, unityController;
static int capturedArgc;
static char **capturedArgv;
static NSDictionary *launchOptions;
static NSString *expectedRoot, *selectedLanguage, *hostError;
static BOOL beforeMatch, afterMatch, firstWarmupMatch, unityWindowBound;
static UIWindow *hostPlaceholderWindow;
static unsigned warmupCalls, lifecycleCalls, deliveredEvents;
static NSMutableArray *pendingEvents;
#if IDOLY_SMOKE_SIMULATOR
static IDUnityHostSmokeHooks smoke;
static BOOL smokeRegistered;
#else
static const struct mach_header_64 *unityHeader;
static const unsigned char *noGraphicsFlag, *graphicsFlag;
static const char *(*originalBundleRoot)(void);
#endif

static BOOL HostFail(NSString *code, NSString **error) {
    hostError = code;
    if (error) *error = code;
    return NO;
}
static BOOL Type(Method m, unsigned index, const char *expected) {
    char *value = method_copyArgumentType(m, index);
    BOOL valid = value && !strcmp(value, expected);
    free(value);
    return valid;
}
static BOOL Signature(Method m, unsigned arguments, const char *result) {
    if (!m || method_getNumberOfArguments(m) != arguments) return NO;
    char *value = method_copyReturnType(m);
    BOOL valid = value && !strcmp(value, result) && Type(m, 0, "@") && Type(m, 1, ":");
    free(value);
    return valid;
}
static BOOL ArgvMethod(Method m, BOOL embedded) {
    return Signature(m, embedded ? 5 : 4, "v") && Type(m, 2, "i") && Type(m, 3, "^*")
        && (!embedded || Type(m, 4, "@"));
}

#if IDOLY_SMOKE_SIMULATOR
BOOL IDUnityHostRegisterSmokeHooks(const IDUnityHostSmokeHooks *hooks) {
    if (!NSThread.isMainThread || smokeRegistered || host.captured || !hooks
            || !hooks->application_main || !hooks->pre_runtime || !hooks->run_count
            || !hooks->cached_bundle_root || !hooks->app_controller || !hooks->before_host_ready) return NO;
    smoke = *hooks;
    smokeRegistered = YES;
    return YES;
}
static BOOL OriginalMethod(Method method) {
    Dl_info owner;
    return method && dladdr((const void *)method_getImplementation(method), &owner)
        && owner.dli_fname && [NSBundle.mainBundle.executablePath.stringByResolvingSymlinksInPath
            isEqualToString:[NSString stringWithUTF8String:owner.dli_fname].stringByResolvingSymlinksInPath];
}
static unsigned RunCount(void) { return smoke.run_count(capturedFramework); }
static BOOL PreRuntime(void) { return smokeRegistered && smoke.pre_runtime() && RunCount() == 0; }
static const char *BundleRoot(void) { return smoke.cached_bundle_root(); }
static id AppController(void) { return smoke.app_controller(capturedFramework); }
#else
static BOOL Pin(Method method, IDUnityHostPin pin, const void *base) {
    Dl_info owner;
    IMP imp = method ? method_getImplementation(method) : NULL;
    return imp && dladdr((const void *)imp, &owner) && owner.dli_fbase == base
        && pin.rva <= UINTPTR_MAX - (uintptr_t)base
        && (uintptr_t)imp == (uintptr_t)base + pin.rva
        && !memcmp((const void *)imp, pin.code, pin.size);
}
static BOOL AuditImage(Method run, Method embedded, Method warmup, Method controller) {
    Dl_info owner;
    if (!dladdr((const void *)method_getImplementation(run), &owner) || !owner.dli_fbase
            || !owner.dli_fname || !strstr(owner.dli_fname, "/UnityFramework.framework/UnityFramework")) return NO;
    const struct mach_header_64 *h = owner.dli_fbase;
    if (h->magic != MH_MAGIC_64 || h->cputype != CPU_TYPE_ARM64 || h->filetype != MH_DYLIB
            || h->ncmds > 4096 || h->sizeofcmds > 1024 * 1024) return NO;
    const unsigned char *commands = (const unsigned char *)(h + 1);
    size_t offset = 0;
    BOOL uuid = NO, text = NO, earlyFlag = NO, lateFlag = NO;
    for (uint32_t i = 0; i < h->ncmds; ++i) {
        if (offset > h->sizeofcmds || h->sizeofcmds - offset < sizeof(struct load_command)) return NO;
        const struct load_command *c = (const void *)(commands + offset);
        if (c->cmdsize < sizeof *c || c->cmdsize > h->sizeofcmds - offset) return NO;
        if (c->cmd == LC_UUID) {
            if (uuid || c->cmdsize != sizeof(struct uuid_command)
                    || memcmp(((const struct uuid_command *)c)->uuid, IDUnityHostUUID, 16)) return NO;
            uuid = YES;
        }
        if (c->cmd == LC_SEGMENT_64) {
            if (c->cmdsize < sizeof(struct segment_command_64)) return NO;
            const struct segment_command_64 *s = (const void *)c;
            if (s->nsects > (c->cmdsize - sizeof *s) / sizeof(struct section_64)) return NO;
            if (!memcmp(s->segname, "__TEXT\0", 7))
                text = s->vmaddr == 0 && s->fileoff == 0 && (s->initprot & VM_PROT_EXECUTE)
                    && s->vmsize > IDUnityHostRunEmbeddedPin.rva + IDUnityHostRunEmbeddedPin.size;
            if (!memcmp(s->segname, "__DATA\0", 7) && s->initprot == (VM_PROT_READ | VM_PROT_WRITE)) {
                const struct section_64 *sections = (const void *)(s + 1);
                for (uint32_t j = 0; j < s->nsects; ++j) {
                    const struct section_64 *section = &sections[j];
                    if (memcmp(section->sectname, "__common\0", 9)
                            || (section->flags & SECTION_TYPE) != S_ZEROFILL) continue;
                    earlyFlag |= section->addr <= IDUnityHostNoGraphicsFlagRVA
                        && IDUnityHostNoGraphicsFlagRVA - section->addr < section->size;
                    lateFlag |= section->addr <= IDUnityHostGraphicsFlagRVA
                        && IDUnityHostGraphicsFlagRVA - section->addr < section->size;
                }
            }
        }
        offset += c->cmdsize;
    }
    if (!uuid || !text || !earlyFlag || !lateFlag || offset != h->sizeofcmds
            || !Pin(run, IDUnityHostRunMainPin, h) || !Pin(embedded, IDUnityHostRunEmbeddedPin, h)
            || !Pin(warmup, IDUnityHostWarmupPin, h) || !Pin(controller, IDUnityHostAppControllerPin, h)
            || memcmp((const unsigned char *)h + IDUnityHostBundleRootPin.rva,
                      IDUnityHostBundleRootPin.code, IDUnityHostBundleRootPin.size)
            || memcmp((const unsigned char *)h + IDUnityHostAppControllerGlobalPin.rva,
                      IDUnityHostAppControllerGlobalPin.code, IDUnityHostAppControllerGlobalPin.size)
            || memcmp((const unsigned char *)h + IDUnityHostNoGraphicsPin.rva,
                      IDUnityHostNoGraphicsPin.code, IDUnityHostNoGraphicsPin.size)) return NO;
    unityHeader = h;
    noGraphicsFlag = (const unsigned char *)h + IDUnityHostNoGraphicsFlagRVA;
    graphicsFlag = (const unsigned char *)h + IDUnityHostGraphicsFlagRVA;
    originalBundleRoot = (const char *(*)(void))((const unsigned char *)h + IDUnityHostBundleRootPin.rva);
    return YES;
}
static unsigned RunCount(void) {
    unsigned value;
    memcpy(&value, (const unsigned char *)(__bridge const void *)capturedFramework
           + IDUnityHostRunCountOffset, sizeof value);
    return value;
}
static BOOL PreRuntime(void) { return unityHeader && *noGraphicsFlag == 0 && *graphicsFlag == 0 && RunCount() == 0; }
static const char *BundleRoot(void) { return originalBundleRoot(); }
static id AppController(void) {
    return ((id (*)(id, SEL))objc_msgSend)(capturedFramework, sel_registerName("appController"));
}
#endif

static NSString *ReadRoot(const char *pointer) {
    if (!pointer) return nil;
    char bytes[PATH_MAX];
#if IDOLY_SMOKE_SIMULATOR
    size_t count = strnlen(pointer, sizeof bytes);
    if (!count || count == sizeof bytes) return nil;
    memcpy(bytes, pointer, count);
#else
    mach_vm_address_t address = (mach_vm_address_t)pointer, region = address;
    mach_vm_size_t size = 0;
    vm_region_basic_info_data_64_t info;
    mach_msg_type_number_t infoCount = VM_REGION_BASIC_INFO_COUNT_64;
    mach_port_t object = MACH_PORT_NULL;
    kern_return_t status = mach_vm_region(mach_task_self(), &region, &size, VM_REGION_BASIC_INFO_64,
        (vm_region_info_t)&info, &infoCount, &object);
    if (object != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), object);
    if (status != KERN_SUCCESS || region > address || !(info.protection & VM_PROT_READ)
            || size <= address - region) return nil;
    size_t available = (size_t)MIN((mach_vm_size_t)sizeof bytes, size - (address - region));
    mach_vm_size_t copied = 0;
    if (mach_vm_read_overwrite(mach_task_self(), address, available,
            (mach_vm_address_t)bytes, &copied) != KERN_SUCCESS || copied != available) return nil;
    const char *end = memchr(bytes, 0, available);
    if (!end || end == bytes) return nil;
    size_t count = (size_t)(end - bytes);
#endif
    return [[NSString alloc] initWithBytes:bytes length:count encoding:NSUTF8StringEncoding];
}
static BOOL MatchesRoot(void) {
    // This accessor is intentionally never called before the selected fixed-ID
    // bundle has been verified. Calling it early would prime Unity's lazy cache.
    NSString *actual = ReadRoot(BundleRoot());
    return actual && [actual.stringByStandardizingPath.stringByResolvingSymlinksInPath
        isEqualToString:expectedRoot];
}
static BOOL SelectedRoot(NSString *root) {
    if (![root isKindOfClass:NSString.class] || !root.isAbsolutePath
            || [root lengthOfBytesUsingEncoding:NSUTF8StringEncoding] >= PATH_MAX) return NO;
    NSString *canonical = root.stringByStandardizingPath.stringByResolvingSymlinksInPath;
    NSString *language = canonical.lastPathComponent.stringByDeletingPathExtension;
    if (![@[@"ko", @"ja", @"en"] containsObject:language]
            || ![canonical.lastPathComponent isEqual:[language stringByAppendingString:@".bundle"]]) return NO;
    NSDictionary *selection = IDClientDataSelectionInfo();
    if (![selection[@"selected"] isEqual:@YES] || ![selection[@"language"] isEqual:language]) return NO;
    NSBundle *bundle = [NSBundle bundleWithIdentifier:@"local.idoly.client-data"];
    if (![bundle.bundlePath.stringByResolvingSymlinksInPath isEqual:canonical]
            || ![bundle.bundleIdentifier isEqual:@"local.idoly.client-data"]
            || ![bundle.infoDictionary[@"IdolyClientLanguage"] isEqual:language]
            || ![bundle.infoDictionary[@"CFBundlePackageType"] isEqual:@"BNDL"]
            || bundle.infoDictionary[@"CFBundleExecutable"] || bundle.infoDictionary[@"NSPrincipalClass"]
            || ![NSFileManager.defaultManager fileExistsAtPath:[canonical stringByAppendingPathComponent:@"Data"]]) return NO;
    expectedRoot = canonical;
    selectedLanguage = language;
    return YES;
}
static void HostWarmup(id framework, SEL selector, int argc, char **argv) {
    if (!host.launching || framework != capturedFramework || warmupCalls || !PreRuntime() || !MatchesRoot()) {
        HostFail(@"warmup_order_or_bundle_mismatch", NULL);
        @throw [NSException exceptionWithName:@"IdolyUnityHostWarmupRejected" reason:nil userInfo:nil];
    }
    firstWarmupMatch = YES;
    ++warmupCalls;
    ((void (*)(id, SEL, int, char **))originalWarmup)(framework, selector, argc, argv);
}
static void HostRunMain(id framework, SEL selector, int argc, char **argv) {
    (void)selector;
    if (!NSThread.isMainThread || object_getClass(framework) != frameworkClass || argc < 1 || argc > 4096
            || !argv || method_getImplementation(runMainMethod) != (IMP)HostRunMain
            || method_getImplementation(warmupMethod) != (IMP)HostWarmup
            || !IDUnityHostCaptureMain(&host)) { HostFail(@"entry_capture_rejected", NULL); return; }
#if IDOLY_SMOKE_SIMULATOR
    if (!smokeRegistered) { host.failed = true; HostFail(@"smoke_hooks_missing", NULL); return; }
#endif
    capturedFramework = framework;
    capturedArgc = argc;
    capturedArgv = argv;
    if (!PreRuntime()) { host.failed = true; HostFail(@"runtime_initialized_before_host", NULL); return; }
    if (!IDUnityHostEnterApplicationMain(&host)) { HostFail(@"host_main_repeated", NULL); return; }
    NSString *delegate = NSStringFromClass(IDUnityHostDelegate.class);
#if IDOLY_SMOKE_SIMULATOR
    int code = smoke.application_main(argc, argv, nil, delegate);
#else
    int code = UIApplicationMain(argc, argv, nil, delegate);
#endif
    if (code) { host.failed = true; HostFail(@"host_application_main_failed", NULL); }
}

BOOL IDUnityHostInstall(IDUnityHostReadyCallback callback, NSString **error) {
    if (error) *error = nil;
    if (!NSThread.isMainThread || !callback || host.installed) return HostFail(@"install_rejected", error);
#if !IDOLY_SMOKE_SIMULATOR
    if (![NSBundle.mainBundle.infoDictionary[@"IdolyUnifiedLoopbackOrigin"] isEqual:@"http://127.0.0.1:8080"])
        return HostFail(@"unattested_unified_host", error);
#endif
    Class cls = objc_getClass("UnityFramework");
    Method main = cls ? class_getInstanceMethod(cls, sel_registerName("runUIApplicationMainWithArgc:argv:")) : NULL;
    Method embedded = cls ? class_getInstanceMethod(cls, sel_registerName("runEmbeddedWithArgc:argv:appLaunchOpts:")) : NULL;
    Method warmup = cls ? class_getInstanceMethod(cls, sel_registerName("frameworkWarmup:argv:")) : NULL;
    Method controller = cls ? class_getInstanceMethod(cls, sel_registerName("appController")) : NULL;
    if (!cls || !ArgvMethod(main, NO) || !ArgvMethod(embedded, YES) || !ArgvMethod(warmup, NO)
            || !Signature(controller, 2, "@") || class_getInstanceSize(cls) < 12)
        return HostFail(@"framework_entry_abi_mismatch", error);
#if IDOLY_SMOKE_SIMULATOR
    if (!OriginalMethod(main) || !OriginalMethod(embedded) || !OriginalMethod(warmup) || !OriginalMethod(controller))
#else
    if (!AuditImage(main, embedded, warmup, controller))
#endif
        return HostFail(@"framework_entry_origin_mismatch", error);
    frameworkClass = cls;
    runMainMethod = main;
    warmupMethod = warmup;
    originalEmbedded = method_getImplementation(embedded);
    originalWarmup = method_getImplementation(warmup);
    readyCallback = callback;
    pendingEvents = [NSMutableArray new];
    method_setImplementation(warmup, (IMP)HostWarmup);
    method_setImplementation(main, (IMP)HostRunMain);
    if (!IDUnityHostMarkInstalled(&host)) return HostFail(@"install_rejected", error);
    return YES;
}
BOOL IDUnityHostIsLaunching(void) { return host.launching; }

static BOOL BoundedValue(id value, unsigned depth, NSUInteger *bytes) {
    if (!value || depth > 4 || *bytes > 32768) return NO;
    if ([value isKindOfClass:NSString.class]) { *bytes += [value lengthOfBytesUsingEncoding:NSUTF8StringEncoding]; return *bytes <= 32768; }
    if ([value isKindOfClass:NSNumber.class] || value == NSNull.null) { *bytes += 16; return YES; }
    if ([value isKindOfClass:NSDate.class]) { *bytes += 16; return YES; }
    if ([value isKindOfClass:NSData.class]) { *bytes += [value length]; return *bytes <= 32768; }
    if ([value isKindOfClass:NSURL.class]) return BoundedValue([value absoluteString], depth + 1, bytes);
    if ([value isKindOfClass:NSDictionary.class] && [value count] <= 32) {
        for (id key in value) if (![key isKindOfClass:NSString.class] || !BoundedValue(key, depth + 1, bytes)
                || !BoundedValue(value[key], depth + 1, bytes)) return NO;
        return YES;
    }
    if ([value isKindOfClass:NSArray.class] && [value count] <= 32) {
        for (id item in value) if (!BoundedValue(item, depth + 1, bytes)) return NO;
        return YES;
    }
    return NO;
}
static BOOL DeliverEvent(NSDictionary *event, UIApplication *application) {
    if (!IDUnityHostMayForward(&host) || !unityController) return NO;
    BOOL handled = NO;
    if ([event[@"kind"] isEqual:@"url"]) {
        SEL selector = @selector(application:openURL:options:);
        if ([unityController respondsToSelector:selector])
            handled = ((BOOL (*)(id, SEL, id, id, id))objc_msgSend)(unityController, selector,
                application, event[@"url"], event[@"options"]);
    } else {
        SEL selector = @selector(application:continueUserActivity:restorationHandler:);
        if ([unityController respondsToSelector:selector])
            handled = ((BOOL (*)(id, SEL, id, id, id))objc_msgSend)(unityController, selector,
                application, event[@"activity"], event[@"restoration"]);
    }
    if (handled) ++deliveredEvents;
    return handled;
}
static __weak UIApplication *hostApplication;
static BOOL BindUnityWindow(void) {
    id delegate = hostApplication.delegate;
    if (![delegate isKindOfClass:IDUnityHostDelegate.class] || !unityController || !hostPlaceholderWindow) return NO;
    SEL selector = sel_registerName("window");
    Method method = class_getInstanceMethod(object_getClass(unityController), selector);
    if (!Signature(method, 2, "@")) return NO;
    id object = ((id (*)(id, SEL))method_getImplementation(method))(unityController, selector);
    if (![object isKindOfClass:UIWindow.class] || object == hostPlaceholderWindow) return NO;
    UIWindow *gameWindow = object;
    if (![gameWindow.rootViewController isKindOfClass:UIViewController.class]
            || gameWindow.windowLevel != UIWindowLevelNormal) return NO;
    UIWindow *placeholder = hostPlaceholderWindow;
    ((IDUnityHostDelegate *)delegate).window = gameWindow;
    [gameWindow makeKeyAndVisible];
    placeholder.hidden = YES;
    hostPlaceholderWindow = nil;
    unityWindowBound = YES;
    return YES;
}
BOOL IDUnityHostStartGame(NSString *verifiedExpectedBundleRoot, NSString **error) {
    if (error) *error = nil;
    if (!NSThread.isMainThread || !host.host_ready || host.runtime_start_calls || host.failed
            || !capturedFramework) return HostFail(@"start_rejected", error);
    if (!SelectedRoot(verifiedExpectedBundleRoot)) return HostFail(@"selected_bundle_mismatch", error);
    if (!PreRuntime()) return HostFail(@"runtime_initialized_before_selection", error);
    beforeMatch = MatchesRoot();
    if (!beforeMatch || !PreRuntime()) return HostFail(@"cached_bundle_root_mismatch", error);
    if (!IDUnityHostBeginRuntime(&host, beforeMatch, YES)) return HostFail(@"start_rejected", error);
    @try {
        ((void (*)(id, SEL, int, char **, id))originalEmbedded)(capturedFramework,
            sel_registerName("runEmbeddedWithArgc:argv:appLaunchOpts:"), capturedArgc,
            capturedArgv, launchOptions);
    } @catch (NSException *exception) {
        (void)exception;
        IDUnityHostFinishRuntime(&host, false);
        return HostFail(hostError ?: @"embedded_start_failed", error);
    }
    afterMatch = MatchesRoot();
    unityController = AppController();
    BOOL valid = afterMatch && firstWarmupMatch && warmupCalls == 1 && RunCount() == 1 && unityController;
    if (valid) valid = BindUnityWindow();
    IDUnityHostFinishRuntime(&host, valid);
    if (!valid) return HostFail(@"embedded_verification_failed", error);
    hostError = nil;
    NSArray *events = [pendingEvents copy];
    [pendingEvents removeAllObjects];
    IDUnityHostDrainEvents(&host);
    for (NSDictionary *event in events) DeliverEvent(event, hostApplication);
    return YES;
}

@implementation IDUnityHostDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    hostApplication = application;
    launchOptions = [options copy] ?: @{};
    if (!IDUnityHostMarkReady(&host) || !readyCallback) return NO;
#if IDOLY_UNITY_HOST_FOUNDATION_TESTING
    self.window = [UIWindow new];
#else
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *root = [UIViewController new];
    root.view.backgroundColor = UIColor.systemBackgroundColor;
    self.window.rootViewController = root;
    [self.window makeKeyAndVisible];
#endif
    hostPlaceholderWindow = self.window;
#if IDOLY_SMOKE_SIMULATOR
    smoke.before_host_ready(application, self);
#endif
    readyCallback();
    return YES;
}
- (void)forwardLifecycle:(SEL)selector application:(UIApplication *)application {
    if (IDUnityHostMayForward(&host) && [unityController respondsToSelector:selector]) {
        ++lifecycleCalls;
        ((void (*)(id, SEL, id))objc_msgSend)(unityController, selector, application);
    }
}
- (void)applicationWillResignActive:(UIApplication *)application { [self forwardLifecycle:_cmd application:application]; }
- (void)applicationDidEnterBackground:(UIApplication *)application { [self forwardLifecycle:_cmd application:application]; }
- (void)applicationWillEnterForeground:(UIApplication *)application { [self forwardLifecycle:_cmd application:application]; }
- (void)applicationDidBecomeActive:(UIApplication *)application { [self forwardLifecycle:_cmd application:application]; }
- (void)applicationWillTerminate:(UIApplication *)application { [self forwardLifecycle:_cmd application:application]; }
- (void)applicationDidReceiveMemoryWarning:(UIApplication *)application { [self forwardLifecycle:_cmd application:application]; }
- (UIInterfaceOrientationMask)application:(UIApplication *)application supportedInterfaceOrientationsForWindow:(UIWindow *)window {
    if (IDUnityHostMayForward(&host) && [unityController respondsToSelector:_cmd]) {
        UIInterfaceOrientationMask mask = ((UIInterfaceOrientationMask (*)(id, SEL, id, id))objc_msgSend)
            (unityController, _cmd, application, window);
        if (mask && !(mask & ~(UIInterfaceOrientationMask)30)) return mask;
    }
    return UIInterfaceOrientationMaskAllButUpsideDown;
}
- (BOOL)application:(UIApplication *)application openURL:(NSURL *)url options:(NSDictionary *)options {
    NSUInteger bytes = 0;
    if (![url isKindOfClass:NSURL.class] || url.absoluteString.length > 4096
            || !BoundedValue(options ?: @{}, 0, &bytes)) return NO;
    NSDictionary *event = @{@"kind":@"url", @"url":url, @"options":[options copy] ?: @{}};
    if (IDUnityHostMayForward(&host)) return DeliverEvent(event, application);
    if (!IDUnityHostQueueEvent(&host)) return NO;
    [pendingEvents addObject:event];
    return YES;
}
- (BOOL)application:(UIApplication *)application continueUserActivity:(NSUserActivity *)activity
 restorationHandler:(void (^)(NSArray<id<UIUserActivityRestoring>> *))restorationHandler {
    NSUInteger bytes = 0;
    if (![activity isKindOfClass:NSUserActivity.class] || activity.activityType.length > 256
            || activity.webpageURL.absoluteString.length > 4096
            || !BoundedValue(activity.userInfo ?: @{}, 0, &bytes)) return NO;
    NSDictionary *event = @{@"kind":@"activity", @"activity":activity,
        @"restoration":[restorationHandler copy] ?: (id)[^(NSArray *items) { (void)items; } copy]};
    if (IDUnityHostMayForward(&host)) return DeliverEvent(event, application);
    if (!IDUnityHostQueueEvent(&host)) return NO;
    [pendingEvents addObject:event];
    return YES;
}
- (BOOL)respondsToSelector:(SEL)selector {
    return [super respondsToSelector:selector] || (IDUnityHostMayForward(&host)
        && [NSStringFromSelector(selector) hasPrefix:@"application"] && [unityController respondsToSelector:selector]);
}
- (id)forwardingTargetForSelector:(SEL)selector {
    if (IDUnityHostMayForward(&host) && [NSStringFromSelector(selector) hasPrefix:@"application"]
            && [unityController respondsToSelector:selector]) return unityController;
    return [super forwardingTargetForSelector:selector];
}
@end

NSDictionary *IDUnityHostInfo(void) {
    if (!NSThread.isMainThread) {
        __block NSDictionary *info;
        dispatch_sync(dispatch_get_main_queue(), ^{ info = IDUnityHostInfo(); });
        return info;
    }
    return @{@"schema":@1, @"strategy":@"unity-as-library", @"installed":@(host.installed),
        @"entry_captured":@(host.captured), @"host_ready":@(host.host_ready), @"launching":@(host.launching),
        @"started":@(host.started), @"failed":@(host.failed),
        @"application_main_calls":@(host.application_main_calls), @"runtime_start_calls":@(host.runtime_start_calls),
        @"warmup_calls":@(warmupCalls), @"bundle_match_before":@(beforeMatch), @"bundle_match_after":@(afterMatch),
        @"unity_window_bound":@(unityWindowBound),
        @"first_warmup_bundle_match":@(firstWarmupMatch), @"consumed_bundle_language":firstWarmupMatch ? selectedLanguage : (id)NSNull.null,
        @"queued_events":@(host.queued_events), @"delivered_events":@(deliveredEvents),
        @"lifecycle_forwarded":@(lifecycleCalls), @"error":hostError ?: (id)NSNull.null};
}
