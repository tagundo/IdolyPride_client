#import "IdolyEmbeddedServer.h"
#import "IdolyNativeUI.h"
#import <UIKit/UIKit.h>
#import <WebKit/WebKit.h>
#import <objc/runtime.h>
#include <stdatomic.h>

static atomic_bool settingsVisible;
static UIWindow *failureWindow;
static __weak UIWindow *previousKeyWindow;
static NSString *pendingFailure;
static const NSUInteger maxJSON = 65536;

static UIWindow *gameWindow(void) {
    for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
        if (![scene isKindOfClass:UIWindowScene.class]) continue;
        for (UIWindow *window in ((UIWindowScene *)scene).windows)
            if (window != failureWindow && window.isKeyWindow) return window;
    }
    for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
        if (![scene isKindOfClass:UIWindowScene.class]) continue;
        for (UIWindow *window in ((UIWindowScene *)scene).windows)
            if (window != failureWindow && !window.hidden && window.rootViewController) return window;
    }
    // Unity 6.1.1 uses a classic UIApplicationDelegate and may have no scenes.
    for (UIWindow *window in UIApplication.sharedApplication.windows)
        if (window != failureWindow && window.isKeyWindow) return window;
    for (UIWindow *window in UIApplication.sharedApplication.windows)
        if (window != failureWindow && !window.hidden && window.rootViewController) return window;
    return nil;
}
static UIViewController *presenter(void) {
    UIViewController *controller = gameWindow().rootViewController;
    while (controller.presentedViewController && !controller.presentedViewController.isBeingDismissed)
        controller = controller.presentedViewController;
    return controller;
}
static NSString *encode(id object) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:object options:0 error:NULL];
    return data && data.length <= maxJSON ? [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] : nil;
}

@interface IDSettingsController : UIViewController <WKScriptMessageHandler, WKNavigationDelegate, UIDocumentPickerDelegate, UIAdaptivePresentationControllerDelegate>
@property (nonatomic,strong) WKWebView *web;
@property (nonatomic,strong) NSURL *page;
@property (nonatomic,copy) NSDictionary *pendingImport;
@property (nonatomic) BOOL pendingExport;
@property (nonatomic,copy) NSString *lastExportPath;
- (void)event:(NSString *)json;
- (void)releaseWeb;
- (void)exportPath:(NSString *)path;
- (void)retireExport;
- (void)closeSettings;
- (void)dispatchRequest:(NSDictionary *)request;
- (void)sendRequest:(NSDictionary *)request;
- (void)sendReply:(NSNumber *)identifier json:(NSString *)json;
- (void)localFailure:(NSNumber *)identifier message:(NSString *)message;
@end
static __weak IDSettingsController *settingsController;

@implementation IDSettingsController
- (void)viewDidLoad {
    [super viewDidLoad];
    self.title = @"아이프라 서버 설정";
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    self.navigationItem.rightBarButtonItem = [[UIBarButtonItem alloc] initWithBarButtonSystemItem:UIBarButtonSystemItemDone
        target:self action:@selector(closeSettings)];
    _page = [NSBundle.mainBundle.bundleURL URLByAppendingPathComponent:@"LocalServer/settings/index.html"];
    WKWebViewConfiguration *configuration = [WKWebViewConfiguration new];
    configuration.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
    [configuration.userContentController addScriptMessageHandler:self name:@"idolyServer"];
    _web = [[WKWebView alloc] initWithFrame:self.view.bounds configuration:configuration];
    _web.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    _web.navigationDelegate = self; [self.view addSubview:_web];
    [_web loadFileURL:_page allowingReadAccessToURL:_page.URLByDeletingLastPathComponent];
}
- (void)viewDidAppear:(BOOL)animated { [super viewDidAppear:animated]; atomic_store(&settingsVisible, true); }
- (void)viewWillDisappear:(BOOL)animated { [super viewWillDisappear:animated]; atomic_store(&settingsVisible, false); }
- (void)viewDidDisappear:(BOOL)animated {
    [super viewDidDisappear:animated];
    if (self.isBeingDismissed || self.navigationController.isBeingDismissed) [self releaseWeb];
}
- (void)releaseWeb {
    atomic_store(&settingsVisible, false);
    [_web.configuration.userContentController removeScriptMessageHandlerForName:@"idolyServer"];
    [_web stopLoading]; _web.navigationDelegate = nil;
    [_web removeFromSuperview]; _web = nil; settingsController = nil;
}
- (void)presentationControllerDidDismiss:(UIPresentationController *)presentationController {
    (void)presentationController; [self releaseWeb];
}
- (void)closeSettings {
    [self releaseWeb];
    [self dismissViewControllerAnimated:YES completion:nil];
}
- (void)dealloc { [_web.configuration.userContentController removeScriptMessageHandlerForName:@"idolyServer"]; }
- (void)webView:(WKWebView *)web decidePolicyForNavigationAction:(WKNavigationAction *)action
    decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
    (void)web;
    BOOL local = action.request.URL.isFileURL
        && [action.request.URL.URLByStandardizingPath.path isEqualToString:_page.URLByStandardizingPath.path];
    decisionHandler(local ? WKNavigationActionPolicyAllow : WKNavigationActionPolicyCancel);
}
- (void)sendReply:(NSNumber *)identifier json:(NSString *)json {
    if (!atomic_load(&settingsVisible) || !_web) return;
    NSData *bytes = [json dataUsingEncoding:NSUTF8StringEncoding];
    id value = bytes && bytes.length <= maxJSON ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL] : nil;
    NSString *array = value ? encode(@[identifier, value]) : nil;
    if (array) [_web evaluateJavaScript:[@"window.idolyServerReply.apply(null," stringByAppendingFormat:@"%@)",array] completionHandler:nil];
}
- (void)localFailure:(NSNumber *)identifier message:(NSString *)message {
    [self sendReply:identifier json:encode(@{@"id":identifier, @"ok":@NO,
        @"error":@{@"code":@"native_files", @"message":message}})];
}
- (void)dispatchRequest:(NSDictionary *)request {
    if (![request[@"action"] isEqual:@"resources_export"]) { [self sendRequest:request]; return; }
    // A completed export may outlive its closed settings page. Before the next
    // explicit export, retire only our own completed temporary ZIP namespace.
    // Never touch .part files or race an active host archive operation.
    NSString *statusRequest = encode(@{@"id":request[@"id"], @"action":@"status"});
    __weak typeof(self) weakSelf = self;
    IdolyEmbeddedServerCommand(statusRequest, ^(NSString *reply) {
        NSData *bytes = [reply dataUsingEncoding:NSUTF8StringEncoding];
        NSDictionary *envelope = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL] : nil;
        NSDictionary *status = [envelope isKindOfClass:NSDictionary.class] && [envelope[@"result"] isKindOfClass:NSDictionary.class] ? envelope[@"result"] : nil;
        NSDictionary *operation = [status[@"resource_operation"] isKindOfClass:NSDictionary.class] ? status[@"resource_operation"] : nil;
        BOOL active = [operation[@"accepted"] isEqual:@YES] && ![operation[@"ready"] isEqual:@YES];
        if (!status || active) { [weakSelf sendRequest:request]; return; }
        NSString *root = [IDNativeDataDirectory() stringByAppendingPathComponent:@"tmp/exports"];
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0), ^{
            NSURL *directory = root ? [NSURL fileURLWithPath:root isDirectory:YES] : nil;
            NSArray<NSURL *> *files = directory ? [NSFileManager.defaultManager contentsOfDirectoryAtURL:directory
                includingPropertiesForKeys:@[NSURLIsRegularFileKey,NSURLIsSymbolicLinkKey] options:0 error:NULL] : nil;
            NSRegularExpression *name = [NSRegularExpression regularExpressionWithPattern:@"^IdolyPride-Resources-ios-[0-9a-f]{32}\\.zip$" options:0 error:NULL];
            if (files.count <= 32) for (NSURL *url in files) {
                NSString *leaf = url.lastPathComponent; NSNumber *regular = nil, *link = nil;
                [url getResourceValue:&regular forKey:NSURLIsRegularFileKey error:NULL];
                [url getResourceValue:&link forKey:NSURLIsSymbolicLinkKey error:NULL];
                if (regular.boolValue && !link.boolValue && [name numberOfMatchesInString:leaf options:0 range:NSMakeRange(0,leaf.length)] == 1)
                    [NSFileManager.defaultManager removeItemAtURL:url error:NULL];
            }
            dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf sendRequest:request]; });
        });
    });
}
- (void)sendRequest:(NSDictionary *)request {
    NSNumber *identifier = request[@"id"];
    NSString *raw = encode(request);
    if (!raw) { [self localFailure:identifier message:@"요청이 너무 큽니다."]; return; }
    if ([request[@"action"] isEqual:@"resources_export"]) _pendingExport = YES;
    __weak typeof(self) weakSelf = self;
    IdolyEmbeddedServerCommand(raw, ^(NSString *reply) {
        IDSettingsController *strongSelf = weakSelf;
        if (!strongSelf) return;
        [strongSelf sendReply:identifier json:reply];
        if ([request[@"action"] isEqual:@"resources_export"]) {
            NSData *bytes = [reply dataUsingEncoding:NSUTF8StringEncoding];
            NSDictionary *value = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL] : nil;
            NSString *path = [value isKindOfClass:NSDictionary.class] && [value[@"ok"] isEqual:@YES]
                && [value[@"result"] isKindOfClass:NSDictionary.class] ? value[@"result"][@"output_path"] : nil;
            if ([value[@"result"] isKindOfClass:NSDictionary.class] && [value[@"result"][@"ready"] isEqual:@YES])
                [strongSelf exportPath:path];
            else if (![value[@"ok"] isEqual:@YES]) strongSelf.pendingExport = NO;
        }
    });
}
- (void)exportPath:(NSString *)path {
    if (!_pendingExport || ![path isKindOfClass:NSString.class] || [path isEqual:_lastExportPath]) return;
    NSString *root = [IDNativeDataDirectory() stringByAppendingPathComponent:@"tmp/exports"];
    NSURL *url = [NSURL fileURLWithPath:path]; NSNumber *regular = nil, *symlink = nil;
    [url getResourceValue:&regular forKey:NSURLIsRegularFileKey error:NULL];
    [url getResourceValue:&symlink forKey:NSURLIsSymbolicLinkKey error:NULL];
    NSString *resolvedRoot = root.stringByResolvingSymlinksInPath;
    BOOL inside = root && regular.boolValue && !symlink.boolValue && [url.pathExtension.lowercaseString isEqual:@"zip"]
        && [url.URLByResolvingSymlinksInPath.path hasPrefix:[resolvedRoot stringByAppendingString:@"/"]];
    if (inside && atomic_load(&settingsVisible) && !self.presentedViewController) {
        _pendingExport = NO; _lastExportPath = path;
        UIDocumentPickerViewController *picker = [[UIDocumentPickerViewController alloc]
            initWithURL:url inMode:UIDocumentPickerModeExportToService];
        picker.delegate = self; [self presentViewController:picker animated:YES completion:nil];
    }
}
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    (void)controller;
    // Main frame plus exact trusted on-disk page, checked on every message.
    if (!message.frameInfo.isMainFrame || !_web.URL.isFileURL
        || ![_web.URL.URLByStandardizingPath.path isEqual:_page.URLByStandardizingPath.path]
        || ![message.frameInfo.request.URL.URLByStandardizingPath.path isEqual:_page.URLByStandardizingPath.path]
        || ![message.body isKindOfClass:NSDictionary.class]) return;
    NSDictionary *request = message.body; NSNumber *identifier = request[@"id"]; NSString *action = request[@"action"];
    if (![identifier isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)identifier) == CFBooleanGetTypeID()
        || identifier.doubleValue != identifier.longLongValue || identifier.longLongValue < 1 || identifier.longLongValue > INT32_MAX
        || ![action isKindOfClass:NSString.class] || !encode(request)) return;
    NSSet *actions = [NSSet setWithArray:@[@"status",@"save_options",@"save_presentation",@"save_playback",@"save_media",
        @"resources_preview",@"resources_download",@"resources_cancel",@"resources_import",@"resources_export"]];
    if (![actions containsObject:action] || request[@"path"] || request[@"output_path"]) {
        [self localFailure:identifier message:@"허용되지 않은 서버 요청입니다."]; return;
    }
    if ([action isEqual:@"resources_import"]) {
        if (_pendingImport) { [self localFailure:identifier message:@"이미 파일을 선택하고 있습니다."]; return; }
        _pendingImport = request;
        UIDocumentPickerViewController *picker = [[UIDocumentPickerViewController alloc]
            initWithDocumentTypes:@[@"public.zip-archive"] inMode:UIDocumentPickerModeOpen];
        picker.allowsMultipleSelection = NO; picker.delegate = self;
        [self presentViewController:picker animated:YES completion:nil];
    } else [self dispatchRequest:request];
}
- (void)documentPickerWasCancelled:(UIDocumentPickerViewController *)controller {
    (void)controller;
    if (_pendingImport) [self localFailure:_pendingImport[@"id"] message:@"파일 선택을 취소했습니다."];
    _pendingImport = nil;
    [self retireExport];
}
- (void)retireExport {
    NSString *path = _lastExportPath; _lastExportPath = nil;
    NSString *root = [IDNativeDataDirectory() stringByAppendingPathComponent:@"tmp/exports"];
    if (!path || !root || ![path.stringByResolvingSymlinksInPath hasPrefix:[root.stringByResolvingSymlinksInPath stringByAppendingString:@"/"]]) return;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0), ^{
        [NSFileManager.defaultManager removeItemAtPath:path error:NULL];
    });
}
- (void)documentPicker:(UIDocumentPickerViewController *)controller didPickDocumentsAtURLs:(NSArray<NSURL *> *)urls {
    (void)controller;
    NSDictionary *request = _pendingImport; _pendingImport = nil;
    if (!request) { [self retireExport]; return; } // Export picker completion.
    NSURL *source = urls.count == 1 ? urls[0] : nil;
    NSString *data = IDNativeDataDirectory();
    if (!source.isFileURL || !data || ![source.pathExtension.lowercaseString isEqual:@"zip"]) {
        [self localFailure:request[@"id"] message:@"ZIP 파일을 선택해 주세요."]; return;
    }
    __weak typeof(self) weakSelf = self;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0), ^{
        BOOL scoped = [source startAccessingSecurityScopedResource];
        NSURL *directory = [NSURL fileURLWithPath:[data stringByAppendingPathComponent:@"imports"] isDirectory:YES];
        NSURL *destination = [directory URLByAppendingPathComponent:[NSUUID.UUID.UUIDString stringByAppendingString:@".zip"]];
        __block NSError *failure = nil;
        [NSFileManager.defaultManager createDirectoryAtURL:directory withIntermediateDirectories:YES
            attributes:@{NSFilePosixPermissions:@0700} error:&failure];
        if (!failure) {
            NSFileCoordinator *coordinator = [NSFileCoordinator new];
            NSError *coordinationError = nil;
            __block NSError *copyError = nil;
            [coordinator coordinateReadingItemAtURL:source options:0 error:&coordinationError byAccessor:^(NSURL *readURL) {
                NSInputStream *in = [NSInputStream inputStreamWithURL:readURL];
                NSOutputStream *out = [NSOutputStream outputStreamWithURL:destination append:NO];
                [in open]; [out open]; uint8_t buffer[65536]; NSInteger size;
                while ((size = [in read:buffer maxLength:sizeof buffer]) > 0) {
                    if (!weakSelf) { copyError = [NSError errorWithDomain:NSCocoaErrorDomain code:NSUserCancelledError userInfo:nil]; break; }
                    NSInteger used = 0;
                    while (used < size) {
                        NSInteger n = [out write:buffer+used maxLength:(NSUInteger)(size-used)];
                        if (n <= 0) { copyError = out.streamError ?: [NSError errorWithDomain:@"IdolyImport" code:1 userInfo:nil]; break; }
                        used += n;
                    }
                    if (copyError) break;
                }
                if (size < 0) copyError = in.streamError ?: [NSError errorWithDomain:@"IdolyImport" code:2 userInfo:nil];
                [in close]; [out close];
            }];
            // Keep accessor errors separate from the NSError** ARC writeback.
            failure = coordinationError ?: copyError;
        }
        if (scoped) [source stopAccessingSecurityScopedResource];
        if (failure) [NSFileManager.defaultManager removeItemAtURL:destination error:NULL];
        dispatch_async(dispatch_get_main_queue(), ^{
            IDSettingsController *strongSelf = weakSelf;
            if (!strongSelf) {
                dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0), ^{
                    [NSFileManager.defaultManager removeItemAtURL:destination error:NULL];
                });
                return;
            }
            if (failure) [strongSelf localFailure:request[@"id"] message:@"ZIP 파일을 앱 보관 폴더로 가져오지 못했습니다."];
            else { NSMutableDictionary *approved = request.mutableCopy; approved[@"path"] = destination.path; [strongSelf dispatchRequest:approved]; }
        });
    });
}
- (void)event:(NSString *)json {
    if (!_web || !atomic_load(&settingsVisible)) return;
    NSData *bytes = [json dataUsingEncoding:NSUTF8StringEncoding];
    id object = bytes && bytes.length <= maxJSON ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL] : nil;
    NSString *array = object ? encode(@[object]) : nil;
    if (array) [_web evaluateJavaScript:[@"window.idolyServerEvent.apply(null," stringByAppendingFormat:@"%@)",array] completionHandler:nil];
    if ([object isKindOfClass:NSDictionary.class] && [object[@"event"] isEqual:@"resource_result"]
        && [object[@"ready"] isEqual:@YES]) [self exportPath:object[@"output_path"]];
}
@end

@interface IDGestureTarget : NSObject
- (void)open:(UILongPressGestureRecognizer *)gesture;
- (void)attach;
@end
@implementation IDGestureTarget
- (void)open:(UILongPressGestureRecognizer *)gesture {
    if (gesture.state != UIGestureRecognizerStateBegan || settingsController) return;
    UIViewController *parent = presenter(); if (!parent) return;
    IDSettingsController *settings = [IDSettingsController new]; settingsController = settings;
    UINavigationController *navigation = [[UINavigationController alloc] initWithRootViewController:settings];
    navigation.modalPresentationStyle = UIModalPresentationFormSheet;
    [parent presentViewController:navigation animated:YES completion:nil];
    navigation.presentationController.delegate = settings;
}
- (void)attach {
    UIWindow *window = gameWindow(); if (!window) return;
    static const void *key = &key;
    if (objc_getAssociatedObject(window,key)) return;
    UILongPressGestureRecognizer *gesture = [[UILongPressGestureRecognizer alloc] initWithTarget:self action:@selector(open:)];
    gesture.numberOfTouchesRequired = 3; gesture.minimumPressDuration = 0.8;
    gesture.cancelsTouchesInView = NO;
    [window addGestureRecognizer:gesture]; objc_setAssociatedObject(window,key,gesture,OBJC_ASSOCIATION_RETAIN_NONATOMIC);
}
@end
void IDNativeInstallSettings(void) {
    static IDGestureTarget *target; static dispatch_once_t once;
    dispatch_once(&once, ^{
        target = [IDGestureTarget new];
        for (NSString *name in @[UIApplicationDidBecomeActiveNotification, UIWindowDidBecomeKeyNotification])
            [NSNotificationCenter.defaultCenter addObserverForName:name object:nil queue:NSOperationQueue.mainQueue
                usingBlock:^(NSNotification *note) { (void)note; [target attach]; if (pendingFailure) IDNativeStartupFailure(pendingFailure); }];
        [target attach];
    });
}
void IDNativeEvent(NSString *json) {
    if (!atomic_load(&settingsVisible)) return;
    dispatch_async(dispatch_get_main_queue(), ^{ [settingsController event:json]; });
}
void IDNativeStartupFailure(NSString *message) {
    NSCAssert(NSThread.isMainThread, @"Startup UI belongs to main thread");
    pendingFailure = message;
    if (failureWindow) return;
    UIWindowScene *scene = nil;
    for (UIScene *candidate in UIApplication.sharedApplication.connectedScenes)
        if ([candidate isKindOfClass:UIWindowScene.class] && candidate.activationState != UISceneActivationStateUnattached) { scene = (id)candidate; break; }
    previousKeyWindow = gameWindow();
    failureWindow = scene ? [[UIWindow alloc] initWithWindowScene:scene]
        : [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    failureWindow.windowLevel = UIWindowLevelAlert + 1; failureWindow.rootViewController = [UIViewController new];
    failureWindow.rootViewController.view.backgroundColor = UIColor.systemBackgroundColor;
    [failureWindow makeKeyAndVisible];
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:@"로컬 서버 시작 실패"
        message:message preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:@"다시 시도" style:UIAlertActionStyleDefault handler:^(UIAlertAction *action) {
        (void)action; IDNativeDismissFailure(); IdolyEmbeddedServerRetry();
    }]];
    [failureWindow.rootViewController presentViewController:alert animated:YES completion:nil];
}
void IDNativeDismissFailure(void) {
    pendingFailure = nil; failureWindow.hidden = YES; failureWindow.rootViewController = nil; failureWindow = nil;
    [previousKeyWindow makeKeyWindow]; previousKeyWindow = nil;
}
