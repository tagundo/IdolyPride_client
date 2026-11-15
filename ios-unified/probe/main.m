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
#if IDOLY_SMOKE_SIMULATOR
#include "../native/tests/OctoBudgetFixture.h"

// The weak provider is defined only by this disposable Simulator host. The
// shipped device framework instead resolves its audited original IL2CPP APIs.
__attribute__((visibility("default"))) BOOL IDOctoBudgetSmokeAPIs(IDOctoBudgetAPIs *apis) {
    if (!apis) return NO;
    *apis = IDOctoBudgetFixtureAPIs();
    return YES;
}
#endif

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

static void ProbeFindButtonsBounded(UIView *view, NSString *identifier, NSMutableArray<UIButton *> *items,
                                    NSUInteger *remaining) {
    if (!view || !*remaining || view.hidden || view.alpha <= 0) return;
    --(*remaining);
    if ([view isKindOfClass:UIButton.class] && [view.accessibilityIdentifier isEqualToString:identifier]
            && view.window && ![items containsObject:(UIButton *)view]) [items addObject:(UIButton *)view];
    for (UIView *child in view.subviews) ProbeFindButtonsBounded(child, identifier, items, remaining);
}

static void ProbeFindButtons(UIView *view, NSString *identifier, NSMutableArray<UIButton *> *items) {
    NSUInteger remaining = 2048;
    ProbeFindButtonsBounded(view, identifier, items, &remaining);
}

static UIView *ProbeFindIdentifiedView(UIView *view, NSString *identifier, NSUInteger *remaining) {
    if (!view || !*remaining) return nil;
    --(*remaining);
    if ([view.accessibilityIdentifier isEqualToString:identifier]) return view;
    for (UIView *child in view.subviews) {
        UIView *found = ProbeFindIdentifiedView(child, identifier, remaining);
        if (found) return found;
    }
    return nil;
}

static UIView *ProbeHeaderView(UIView *view, NSString *identifier) {
    NSUInteger remaining = 2048;
    return ProbeFindIdentifiedView(view, identifier, &remaining);
}

static UIViewController *ProbeButtonOwner(UIButton *button) {
    for (id target in button.allTargets) {
        if ([target isKindOfClass:UIViewController.class]
                && [NSStringFromClass([target class]) isEqualToString:@"IDSettingsController"]) return target;
    }
    return nil;
}

static BOOL ProbeButtonHasTouchAction(UIButton *button) {
    UIViewController *owner = ProbeButtonOwner(button);
    return owner && [button actionsForTarget:owner forControlEvent:UIControlEventTouchUpInside].count == 1;
}

static BOOL ProbeDispatchButton(UIButton *button) {
    if (!button.enabled || !button.userInteractionEnabled || !button.window || !ProbeButtonHasTouchAction(button)) return NO;
    // Exercise the actual UIControl registration, rather than calling the
    // controller's selector directly. Subsequent state checks prove its effect.
    [button sendActionsForControlEvents:UIControlEventTouchUpInside];
    return YES;
}

static NSArray<UIButton *> *ProbeVisibleLaunchButtons(void) {
    NSMutableOrderedSet<UIWindow *> *windows = [NSMutableOrderedSet orderedSetWithArray:UIApplication.sharedApplication.windows];
    for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
        if ([scene isKindOfClass:UIWindowScene.class]) {
            [windows addObjectsFromArray:((UIWindowScene *)scene).windows];
        }
    }
    NSMutableArray<UIButton *> *items = [NSMutableArray array];
    for (UIWindow *window in windows) {
        if (!window.hidden && window.alpha > 0) ProbeFindButtons(window, @"idoly.game-start", items);
    }
    return items;
}

static void ProbeLayoutOwnedRoot(UIViewController *owner, UIView *root) {
    // Font changes made in viewDidLayoutSubviews need a subsequent constraint
    // pass. Bound those synchronous passes; do not change a Simulator window.
    for (NSUInteger index = 0; index < 3; ++index) {
        [root setNeedsLayout]; [root layoutIfNeeded];
        [owner.view setNeedsLayout]; [owner.view layoutIfNeeded];
    }
}

static NSDictionary *ProbeHeaderMetrics(UIViewController *owner) {
    UIView *root = owner.view;
    UIView *header = ProbeHeaderView(root,@"idoly.native-header");
    UIView *actions = ProbeHeaderView(root,@"idoly.native-actions");
    UILabel *title = (UILabel *)ProbeHeaderView(root,@"idoly.native-title");
    UILabel *status = (UILabel *)ProbeHeaderView(root,@"idoly.server-status");
    UILabel *hint = (UILabel *)ProbeHeaderView(root,@"idoly.server-hint");
    BOOL titleFound = [title isKindOfClass:UILabel.class] && !title.hidden && title.text.length > 0;
    BOOL statusFound = [status isKindOfClass:UILabel.class] && !status.hidden && status.text.length > 0;
    BOOL hintFound = [hint isKindOfClass:UILabel.class] && !hint.hidden && hint.text.length > 0;
    NSMutableArray<UIButton *> *buttons = [NSMutableArray array];
    ProbeFindButtons(header,@"idoly.server-start",buttons);
    ProbeFindButtons(header,@"idoly.game-start",buttons);
    ProbeFindButtons(header,@"idoly.server-close",buttons);
    CGFloat minimumFont = CGFLOAT_MAX, minimumHeight = CGFLOAT_MAX;
    BOOL controlsInside = buttons.count == 2, titlesFit = buttons.count == 2, rowNoOverlap = buttons.count == 2;
    CGRect previous = CGRectNull;
    for (UIButton *button in buttons) {
        CGFloat font = button.titleLabel.font.pointSize;
        minimumFont = MIN(minimumFont,font); minimumHeight = MIN(minimumHeight,CGRectGetHeight(button.bounds));
        CGRect frame = [button convertRect:button.bounds toView:actions];
        controlsInside = controlsInside && CGRectContainsRect(CGRectInset(actions.bounds,-1,-1),frame);
        if (!CGRectIsNull(previous) && CGRectIntersectsRect(CGRectInset(previous,0.5,0.5),CGRectInset(frame,0.5,0.5))) rowNoOverlap = NO;
        previous = frame;
        UIEdgeInsets insets = button.contentEdgeInsets;
        CGFloat width = MAX(0,CGRectGetWidth(button.bounds)-insets.left-insets.right);
        CGFloat height = MAX(0,CGRectGetHeight(button.bounds)-insets.top-insets.bottom);
        NSString *text = [button titleForState:UIControlStateNormal] ?: @"";
        CGRect needed = [text boundingRectWithSize:CGSizeMake(width,CGFLOAT_MAX)
            options:NSStringDrawingUsesLineFragmentOrigin | NSStringDrawingUsesFontLeading
            attributes:@{NSFontAttributeName:button.titleLabel.font} context:nil];
        titlesFit = titlesFit && text.length > 0 && width > 0 && ceil(needed.size.width) <= width+1
            && ceil(needed.size.height) <= height+1;
    }
    CGRect headerFrame = header ? [header convertRect:header.bounds toView:root] : CGRectZero;
    BOOL headerInside = header && CGRectContainsRect(CGRectInset(root.bounds,-1,-1),headerFrame);
    BOOL headerFound = [header isKindOfClass:UIStackView.class] && header.window != nil;
    BOOL actionsFound = [actions isKindOfClass:UIStackView.class] && actions.window != nil;
    BOOL navHidden = owner.navigationController && owner.navigationController.navigationBarHidden;
    return @{@"header_found":@(headerFound),@"actions_found":@(actionsFound),@"title_found":@(titleFound),
        @"status_found":@(statusFound),@"hint_found":@(hintFound),@"nav_bar_hidden":@(navHidden),
        @"header_inside":@(headerInside),@"controls_inside":@(controlsInside),@"row_no_overlap":@(rowNoOverlap),
        @"button_titles_fit":@(titlesFit),@"button_count":@(buttons.count),
        @"root_width":@(CGRectGetWidth(root.bounds)),@"root_height":@(CGRectGetHeight(root.bounds)),
        @"header_width":@(CGRectGetWidth(header.bounds)),@"header_height":@(CGRectGetHeight(header.bounds)),
        @"actions_width":@(CGRectGetWidth(actions.bounds)),@"min_button_height":@(buttons.count ? minimumHeight : 0),
        @"button_min_font":@(buttons.count ? minimumFont : 0),@"title_font":@(titleFound ? title.font.pointSize : 0),
        @"status_font":@(statusFound ? status.font.pointSize : 0),@"hint_font":@(hintFound ? hint.font.pointSize : 0)};
}

static NSDictionary *ProbeHeaderLayouts(UIButton *button) {
    UIViewController *owner = ProbeButtonOwner(button);
    UIView *root = owner.navigationController.view;
    BOOL owned = owner && root && root.window == button.window && owner.navigationController.topViewController == owner;
    if (!owned) return @{@"owned_root_only":@NO,@"restore_succeeded":@NO};
    CGRect savedFrame = root.frame, savedBounds = root.bounds;
    CGRect savedOwnerFrame = owner.view.frame, savedOwnerBounds = owner.view.bounds;
    NSMutableDictionary *result = [NSMutableDictionary dictionaryWithDictionary:@{@"owned_root_only":@YES}];
    ProbeLayoutOwnedRoot(owner,root); result[@"current"] = ProbeHeaderMetrics(owner);
    @try {
        NSArray<NSString *> *names = @[@"wide",@"ultrawide"];
        NSArray<NSValue *> *sizes = @[[NSValue valueWithCGSize:CGSizeMake(1920,1080)],
                                      [NSValue valueWithCGSize:CGSizeMake(3840,2160)]];
        for (NSUInteger index=0; index<names.count; ++index) {
            CGSize size = sizes[index].CGSizeValue;
            root.frame = CGRectMake(savedFrame.origin.x,savedFrame.origin.y,size.width,size.height);
            root.bounds = CGRectMake(0,0,size.width,size.height);
            owner.view.frame = root.bounds; owner.view.bounds = root.bounds;
            ProbeLayoutOwnedRoot(owner,root); result[names[index]] = ProbeHeaderMetrics(owner);
        }
    } @finally {
        root.frame = savedFrame; root.bounds = savedBounds;
        owner.view.frame = savedOwnerFrame; owner.view.bounds = savedOwnerBounds;
        ProbeLayoutOwnedRoot(owner,root);
    }
    BOOL restored = CGRectEqualToRect(root.frame,savedFrame) && CGRectEqualToRect(root.bounds,savedBounds)
        && CGRectEqualToRect(owner.view.frame,savedOwnerFrame) && CGRectEqualToRect(owner.view.bounds,savedOwnerBounds);
    result[@"restore_succeeded"] = @(restored); result[@"restored"] = ProbeHeaderMetrics(owner);
    return result;
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

static void ProbeDiagnosticsCopyAttempt(WKWebView *__weak weakWeb, NSMutableDictionary *state,
                                        void (^finish)(void)) {
    if ([state[@"finished"] boolValue]) return;
    WKWebView *web = weakWeb;
    if (!web) { finish(); return; }
    NSString *script = @"(() => { const f=document.getElementById('diagnostics-copy-feedback');"
        "return {completed:!!f&&!f.hidden,success:!!f&&!f.hidden&&f.dataset.error==='false'}; })()";
    [web evaluateJavaScript:script completionHandler:^(id value,NSError *error) {
        if ([state[@"finished"] boolValue]) return;
        NSMutableDictionary *metrics = state[@"metrics"];
        if (!error && [value isKindOfClass:NSDictionary.class] && [value[@"completed"] isEqual:@YES]) {
            BOOL success = [value[@"success"] isEqual:@YES];
            metrics[@"completed"] = @YES; metrics[@"feedback_success"] = @(success);
            // The test seeded this clipboard before clicking. Read only the
            // value resulting from our own request, never an earlier clipboard.
            NSString *expected = state[@"expected"];
            BOOL matches = success && expected && [UIPasteboard.generalPasteboard.string isEqualToString:expected];
            metrics[@"pasteboard_matches"] = @(matches); finish(); return;
        }
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/10),dispatch_get_main_queue(), ^{
            ProbeDiagnosticsCopyAttempt(weakWeb,state,finish);
        });
    }];
}

static void ProbeDiagnosticsCopy(WKWebView *web,void (^completion)(NSDictionary *)) {
    NSCAssert(NSThread.isMainThread,@"Clipboard probe belongs on main thread");
    NSMutableDictionary *metrics = [@{@"button_found":@NO,@"enabled_before":@NO,@"click_dispatched":@NO,
        @"completed":@NO,@"feedback_success":@NO,@"pasteboard_matches":@NO,@"clipboard_seeded":@NO,
        @"clipboard_cleared":@NO,@"timed_out":@NO,@"text_bytes":@0} mutableCopy];
    NSMutableDictionary *state = [@{@"finished":@NO,@"metrics":metrics} mutableCopy];
    UIPasteboard.generalPasteboard.string = @"Idoly disposable probe clipboard marker";
    BOOL seeded = [UIPasteboard.generalPasteboard.string isEqualToString:@"Idoly disposable probe clipboard marker"];
    metrics[@"clipboard_seeded"] = @(seeded);
    void (^finish)(void) = ^{
        if ([state[@"finished"] boolValue]) return;
        state[@"finished"] = @YES;
        UIPasteboard.generalPasteboard.string = @"";
        BOOL cleared = UIPasteboard.generalPasteboard.string.length == 0;
        metrics[@"clipboard_cleared"] = @(cleared);
        completion(metrics.copy);
    };
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,10*NSEC_PER_SEC),dispatch_get_main_queue(), ^{
        if ([state[@"finished"] boolValue]) return;
        metrics[@"timed_out"] = @YES; finish();
    });
    if (!web || !seeded) { finish(); return; }
    // Snapshot and click in the same JavaScript turn: a diagnostics refresh
    // cannot change the text between the expected value and the real handler.
    NSString *script = @"(() => { const b=document.getElementById('diagnostics-copy'),"
        "p=document.getElementById('diagnostics'); const t=p?p.textContent:'';"
        "const r=b?b.getBoundingClientRect():null; const e=!!r&&r.width>0&&r.height>0&&!b.hidden&&!b.disabled&&!!t; if(e)b.click();"
        "return {button_found:!!b,enabled_before:e,click_dispatched:e,text:t}; })()";
    [web evaluateJavaScript:script completionHandler:^(id value,NSError *error) {
        if ([state[@"finished"] boolValue]) return;
        if (error || ![value isKindOfClass:NSDictionary.class]) { finish(); return; }
        for (NSString *key in @[@"button_found",@"enabled_before",@"click_dispatched"])
            metrics[key] = @((BOOL)[value[key] isEqual:@YES]);
        NSString *text = [value[@"text"] isKindOfClass:NSString.class] ? value[@"text"] : nil;
        NSUInteger count = [text lengthOfBytesUsingEncoding:NSUTF8StringEncoding];
        if (!count || count > 32768 || ![metrics[@"click_dispatched"] isEqual:@YES]) { finish(); return; }
        state[@"expected"] = text; metrics[@"text_bytes"] = @(count);
        ProbeDiagnosticsCopyAttempt(web,state,finish);
    }];
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
// Model the real warm state: public getters may create the keyboard before
// Unity's explicit +Initialize, whose unmodified implementation asserts nil.
// The lifecycle hook must reuse that initialized object, preserving the field.
static UITextField *probeFirstKeyboardField;
static NSUInteger probeKeyboardGetterCalls, probeKeyboardCreations;
@interface KeyboardDelegate : NSObject
@property(nonatomic, strong) UITextField *field;
+ (void)Initialize;
+ (instancetype)Instance;
+ (instancetype)idolyCurrentInstance;
@end
static KeyboardDelegate *probeKeyboardInstance;
@implementation KeyboardDelegate
- (instancetype)init {
    self = [super init];
    if (self) {
        _field = [[UITextField alloc] initWithFrame:CGRectZero];
        ++probeKeyboardCreations;
    }
    return self;
}
+ (void)Initialize {
    NSCAssert(!probeKeyboardInstance, @"[KeyboardDelegate Initialize] called after creating keyboard");
    probeKeyboardInstance = [[KeyboardDelegate alloc] init];
}
+ (instancetype)Instance {
    if (!probeKeyboardInstance) probeKeyboardInstance = [[KeyboardDelegate alloc] init];
    return probeKeyboardInstance;
}
+ (instancetype)idolyCurrentInstance { return probeKeyboardInstance; }
@end

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
    return [KeyboardDelegate Instance].field;
}
@end

static NSDictionary *ProbeKeyboardLifecycle(NSDictionary *status) {
    NSDictionary *value = [status[@"keyboard_lifecycle"] isKindOfClass:NSDictionary.class]
        ? status[@"keyboard_lifecycle"] : @{};
    return @{@"installed":ProbeScalar(value,@"installed"), @"strategy":ProbeScalar(value,@"strategy"),
        @"initialize_calls":ProbeScalar(value,@"initialize_calls"),
        @"original_initialize_calls":ProbeScalar(value,@"original_initialize_calls"),
        @"reused_existing_calls":ProbeScalar(value,@"reused_existing_calls")};
}

static NSDictionary *ProbeKeyboardObservation(void) {
    UITextField *field = [[UnityFramework getInstance] keyboardTextField];
    NSDictionary *status = ProbeObject(IdolyEmbeddedServerStatusJSON());
    if (!probeFirstKeyboardField && field) probeFirstKeyboardField = field;
    BOOL returnedNil = field == nil;
    BOOL initializedField = field != nil && field == [KeyboardDelegate idolyCurrentInstance].field;
    BOOL sameField = field != nil && field == probeFirstKeyboardField;
    return @{@"ready":ProbeScalar(status,@"keyboard_ready"), @"phase":ProbeScalar(status,@"phase"),
        @"returned_nil":@(returnedNil), @"returned_initialized_field":@(initializedField),
        @"returned_same_field":@(sameField), @"original_calls":@(probeKeyboardGetterCalls),
        @"field_creation_count":@(probeKeyboardCreations), @"lifecycle":ProbeKeyboardLifecycle(status)};
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
@property(nonatomic, strong) NSDictionary *nativeHeaderProbe;
@property(nonatomic, strong) NSDictionary *diagnosticsCopyObservation;
@property(nonatomic, strong) NSMutableDictionary *octoBudgetProbe;
@property(nonatomic) NSUInteger firstOctoQueuedSnapshotCount;
- (void)initUnityWithApplication:(UIApplication *)application __attribute__((objc_method_family(none)));
- (void)probeLauncher:(NSDictionary *)status;
- (void)recordCheckpoint:(NSString *)stage;
- (void)failProbe:(NSString *)code;
- (BOOL)observeKeyboard:(NSString *)name phase:(NSUInteger)phase ready:(BOOL)ready calls:(NSUInteger)calls failure:(NSString *)code;
- (void)probeAfterOriginalReturnedOnMain:(BOOL)originalOnMain applicationMatches:(BOOL)argumentMatches;
- (BOOL)observeOctoBudgetBeforeOriginal;
- (BOOL)observeOctoBudgetFirstQueuedWork;
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
        @"keyboard":self.keyboardProbe.copy ?: @{}, @"native_header":self.nativeHeaderProbe ?: @{},
        @"diagnostics_copy":self.diagnosticsCopyObservation ?: @{}, @"octo_budget_probe":self.octoBudgetProbe.copy ?: @{}});
}
- (void)recordCheckpoint:(NSString *)stage {
    NSDictionary *status = ProbeObject(IdolyEmbeddedServerStatusJSON());
    ProbeWrite(@"embedded-probe-checkpoint.json", @{@"schema":@1, @"stage":stage,
        @"original_called":@(self.originalCount), @"phase":ProbeScalar(status, @"phase"),
        @"application_state":@(UIApplication.sharedApplication.applicationState),
        @"launch_requested":ProbeScalar(status, @"launch_requested"),
        @"launch_prepared":ProbeScalar(status, @"launch_prepared"),
        @"launcher_visible":ProbeScalar(status, @"launcher_visible"),
        @"keyboard_lifecycle":ProbeKeyboardLifecycle(status),
        @"keyboard_ready":ProbeScalar(status,@"keyboard_ready"),
        @"menu_close":self.menuCloseObservation ?: @{}, @"keyboard":self.keyboardProbe.copy ?: @{},
        @"native_header":self.nativeHeaderProbe ?: @{}, @"diagnostics_copy":self.diagnosticsCopyObservation ?: @{},
        @"octo_budget":status[@"octo_budget"] ?: @{}, @"octo_budget_probe":self.octoBudgetProbe.copy ?: @{}});
}
- (BOOL)observeOctoBudgetBeforeOriginal {
#if IDOLY_SMOKE_SIMULATOR
    NSDictionary *native = ProbeObject(IdolyEmbeddedServerStatusJSON());
    NSDictionary *budget = [native[@"octo_budget"] isKindOfClass:NSDictionary.class] ? native[@"octo_budget"] : @{};
    IDOctoBudgetFixtureData *state = IDOctoBudgetFixtureState();
    BOOL untouched = [budget[@"prepared"] isEqual:@YES] && [budget[@"configured"] isEqual:@NO]
        && !state->initialized && state->initializations == 0 && state->reads == 0 && state->writes == 0
        && state->value == 0.0f;
    self.octoBudgetProbe[@"prepared_without_managed_callbacks"] = @(untouched);
    if (!untouched) { [self failProbe:@"octo_budget_preinit_failed"]; return NO; }
    // An inline SDK read during the original initializer still sees its own
    // ten-second default. The next queued work is checked separately below.
    float seconds = IDOctoBudgetFixtureSnapshot();
    BOOL configured = [budget[@"configured"] isEqual:@YES];
    self.octoBudgetProbe[@"during_original_seconds"] = @(seconds);
    self.octoBudgetProbe[@"during_original_configured"] = @(configured);
    BOOL original = seconds == 10.0f && !configured && state->initialized
        && state->initializations == 1 && state->reads == 0 && state->writes == 0;
    if (!original) { [self failProbe:@"octo_budget_original_failed"]; return NO; }
    [self recordCheckpoint:@"octo_budget_original_observed"];
    return YES;
#else
    [self failProbe:@"octo_budget_preinit_failed"]; return NO;
#endif
}
- (BOOL)observeOctoBudgetFirstQueuedWork {
#if IDOLY_SMOKE_SIMULATOR
    NSDictionary *native = ProbeObject(IdolyEmbeddedServerStatusJSON());
    NSDictionary *budget = [native[@"octo_budget"] isKindOfClass:NSDictionary.class] ? native[@"octo_budget"] : @{};
    BOOL configured = [budget[@"configured"] isEqual:@YES];
    float seconds = IDOctoBudgetFixtureSnapshot();
    IDOctoBudgetFixtureData *state = IDOctoBudgetFixtureState();
    ++self.firstOctoQueuedSnapshotCount;
    [self.octoBudgetProbe addEntriesFromDictionary:@{@"first_queued_seconds":@(seconds),
        @"configured_before_first_queued_work":@(configured), @"queued_work_on_main_thread":@(NSThread.isMainThread),
        @"class_initialized":@((BOOL)state->initialized), @"initializations":@(state->initializations),
        @"reads":@(state->reads), @"writes":@(state->writes),
        @"writes_before_initialization":@(state->writes_before_initialization), @"last_snapshot":@(state->last_snapshot),
        @"first_queued_snapshot_count":@(self.firstOctoQueuedSnapshotCount)}];
    BOOL ready = configured && NSThread.isMainThread && [native[@"keyboard_ready"] isEqual:@YES]
        && seconds == 330.0f && state->last_snapshot == 330.0f && state->initialized
        && state->initializations == 1 && state->reads == 2 && state->writes == 1
        && state->writes_before_initialization == 0
        && self.firstOctoQueuedSnapshotCount == 1;
    if (!ready) { [self failProbe:@"octo_budget_queued_work_failed"]; return NO; }
    [self recordCheckpoint:@"octo_budget_first_queued_work_observed"];
    return YES;
#else
    [self failProbe:@"octo_budget_queued_work_failed"]; return NO;
#endif
}
- (BOOL)observeKeyboard:(NSString *)name phase:(NSUInteger)phase ready:(BOOL)ready calls:(NSUInteger)calls failure:(NSString *)code {
    NSDictionary *value = ProbeKeyboardObservation();
    self.keyboardProbe[name] = value;
    BOOL installed = phase == 4;
    NSDictionary *lifecycle = value[@"lifecycle"];
    NSNumber *expectedInitializations = installed ? @1 : @0;
    BOOL correct = [value[@"ready"] isEqual:@(ready)]
        && [value[@"phase"] isEqual:@(phase)] && [value[@"returned_nil"] isEqual:@NO]
        && [value[@"returned_initialized_field"] isEqual:@YES] && [value[@"returned_same_field"] isEqual:@YES]
        && [value[@"original_calls"] isEqual:@(calls)] && [value[@"field_creation_count"] isEqual:@1]
        && [lifecycle[@"installed"] isEqual:@(installed)] && [lifecycle[@"strategy"] isEqual:@"reuse-existing"]
        && [lifecycle[@"initialize_calls"] isEqual:expectedInitializations]
        && [lifecycle[@"reused_existing_calls"] isEqual:expectedInitializations]
        && [lifecycle[@"original_initialize_calls"] isEqual:@0];
    if (!correct) [self failProbe:code];
    return correct;
}
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)application; (void)options;
#if IDOLY_SMOKE_SIMULATOR
    IDOctoBudgetFixtureReset();
#endif
    self.octoBudgetProbe = [NSMutableDictionary dictionary];
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
            @"keyboard":self.keyboardProbe.copy, @"native_header":self.nativeHeaderProbe ?: @{},
            @"octo_budget_probe":self.octoBudgetProbe.copy});
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
        if (![self observeKeyboard:@"before_capture" phase:2 ready:NO calls:1 failure:@"keyboard_before_capture_failed"]) return;
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
    NSArray<UIButton *> *items = ProbeVisibleLaunchButtons();
    if (items.count != 1) {
        self.probeError = items.count ? @"ready_launch_button_ambiguous" : @"ready_launch_button_missing";
        return;
    }
    UIButton *item = items.firstObject;
    if (!item.enabled) { self.probeError = @"ready_launch_button_disabled"; return; }
    NSString *buttonTitle = [item titleForState:UIControlStateNormal];
    if (![@[@"게임 시작", @"ゲーム開始", @"Start Game"] containsObject:buttonTitle]) {
        self.probeError = @"ready_launch_button_title_differs"; return;
    }
    if (!ProbeButtonHasTouchAction(item)) { self.probeError = @"ready_launch_action_missing"; return; }
    NSTimeInterval now = NSProcessInfo.processInfo.systemUptime;
    if (self.readySince == 0) self.readySince = now;
    NSUInteger observations = [self.launcherProbe[@"ready_observations"] unsignedIntegerValue] + 1;
    [self.launcherProbe addEntriesFromDictionary:@{@"ready_phase":@2,
        @"ready_original_called":@(self.originalCount), @"ready_launch_requested":@NO,
        @"ready_launch_prepared":@NO, @"ready_launcher_visible":@YES,
        @"ready_button_found":@YES, @"ready_button_enabled":@(item.enabled),
        @"ready_button_title":buttonTitle, @"ready_button_kind":@"UIButton", @"ready_observations":@(observations),
        @"ready_wait_seconds":@(now - self.readySince)}];
    // Remain Ready for a full second without forwarding Unity. This proves
    // readiness alone does not enter the game, before invoking the real UI.
    if (now - self.readySince < 1.0) return;
    if (!self.nativeHeaderProbe) {
        self.nativeHeaderProbe = ProbeHeaderLayouts(item);
        if (![self.nativeHeaderProbe[@"restore_succeeded"] isEqual:@YES]) {
            [self failProbe:@"native_header_restore_failed"]; return;
        }
        for (NSString *name in @[@"current",@"wide",@"ultrawide",@"restored"]) {
            NSDictionary *metrics = self.nativeHeaderProbe[name];
            BOOL good = [metrics[@"button_count"] isEqual:@2];
            for (NSString *key in @[@"header_found",@"actions_found",@"title_found",@"status_found",@"hint_found",
                    @"nav_bar_hidden",@"header_inside",@"controls_inside",@"row_no_overlap",@"button_titles_fit"])
                good = good && [metrics[key] isEqual:@YES];
            CGFloat minimum = [name isEqual:@"ultrawide"] ? 40 : [name isEqual:@"wide"] ? 20 : 16;
            good = good && [metrics[@"button_min_font"] doubleValue] >= minimum
                && [metrics[@"status_font"] doubleValue] >= minimum && [metrics[@"title_font"] doubleValue] >= 20
                && [metrics[@"hint_font"] doubleValue] >= 12 && [metrics[@"min_button_height"] doubleValue] >= 44;
            if (!good) { [self failProbe:@"native_header_layout_failed"]; return; }
        }
        [self recordCheckpoint:@"native_header_checked"];
    }
    if (![self observeKeyboard:@"before_launch" phase:2 ready:NO calls:2 failure:@"keyboard_before_launch_failed"]) return;
    [self recordCheckpoint:@"keyboard_before_launch_checked"];
    self.launchDispatched = YES;
    self.launcherProbe[@"button_dispatch_count"] = @1;
    [self recordCheckpoint:@"launch_action_requested"];
    BOOL dispatched = ProbeDispatchButton(item);
    self.launcherProbe[@"button_action_dispatched"] = @(dispatched);
    self.launcherProbe[@"button_control_event"] = @"touch-up-inside";
    [self recordCheckpoint:@"launch_action_dispatched"];
    if (!dispatched) { self.probeError = @"ready_launch_action_not_dispatched"; return; }
    // Repeated clicks must not forward Unity a second time.
    IdolyEmbeddedServerLaunchGame();
    self.launcherProbe[@"duplicate_launch_called"] = @YES;
}

// Exact Unity ABI: void return, instance receiver, selector, one object argument.
- (void)initUnityWithApplication:(UIApplication *)application {
    ++self.originalCount;
    if (![self observeOctoBudgetBeforeOriginal]) return;
    self.launcherProbe[@"forwarded_after_button"] = @(self.launchDispatched);
    [self recordCheckpoint:@"unity_forwarded"];
    if (self.reportScheduled) return;
    self.reportScheduled = YES; [self.waitingTimer invalidate]; self.waitingTimer = nil;
    BOOL originalOnMain = NSThread.isMainThread;
    BOOL argumentMatches = application == UIApplication.sharedApplication;
    // The real stock initializer calls this after its UIKit window setup.
    // A prior lazy +Instance must be reused without assertion or replacement.
    KeyboardDelegate *existing = [KeyboardDelegate idolyCurrentInstance];
    [KeyboardDelegate Initialize];
    if (!existing || existing != [KeyboardDelegate idolyCurrentInstance] || probeKeyboardCreations != 1) {
        [self failProbe:@"keyboard_precreated_instance_not_reused"]; return;
    }
    // phase=Running is already set; readiness still waits for normal return.
    if (![self observeKeyboard:@"during_init" phase:4 ready:NO calls:3 failure:@"keyboard_during_init_failed"]) return;
    [self recordCheckpoint:@"keyboard_during_init_checked"];
    // This continuation cannot execute until the fake original IMP returns
    // and the native gate marks that invocation fully complete.
    dispatch_async(dispatch_get_main_queue(), ^{
        [self probeAfterOriginalReturnedOnMain:originalOnMain applicationMatches:argumentMatches];
    });
}
- (void)probeAfterOriginalReturnedOnMain:(BOOL)originalOnMain applicationMatches:(BOOL)argumentMatches {
    if (![self observeOctoBudgetFirstQueuedWork]) return;
    if (![self observeKeyboard:@"after_init" phase:4 ready:YES calls:4 failure:@"keyboard_after_init_failed"]) return;
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
                        @"octo_budget_probe":self.octoBudgetProbe.copy,
                        @"native_header":self.nativeHeaderProbe ?: @{},
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
        NSMutableArray<UIButton *> *buttons = [NSMutableArray array];
        ProbeFindButtons(navigation.view, @"idoly.server-close", buttons);
        NSMutableArray<UIButton *> *serverButtons = [NSMutableArray array];
        ProbeFindButtons(navigation.view, @"idoly.server-start", serverButtons);
        CGFloat width = CGRectGetWidth(navigation.view.bounds), windowWidth = CGRectGetWidth(self.window.bounds);
        BOOL fullScreen = navigation.modalPresentationStyle == UIModalPresentationFullScreen;
        BOOL widthMatches = width > 0 && windowWidth > 0 && fabs(width - windowWidth) <= 2.0;
        if (buttons.count != 1 || !ProbeButtonHasTouchAction(buttons.firstObject)
                || !buttons.firstObject.enabled || serverButtons.count != 1 || serverButtons.firstObject.enabled
                || !fullScreen || !widthMatches) {
            [self failProbe:@"settings_menu_controls_or_layout_failed"]; return;
        }
        UIButton *close = buttons.firstObject;
        NSMutableDictionary *menu = [@{@"opened_via_owned_menu_target":@YES,
            @"full_screen":@(fullScreen), @"frame_width_matches":@(widthMatches),
            @"frame_width":@(width), @"window_width":@(windowWidth), @"return_button_found":@YES,
            @"return_button_kind":@"UIButton", @"server_button_kind":@"UIButton",
            @"server_control_found":@YES, @"server_control_disabled_while_running":@YES} mutableCopy];
        WKWebView *web = ProbeFindSettingsWeb(navigation.topViewController.view);
        ProbeSettingsDOM(web, ^(NSDictionary *metrics) {
            menu[@"web"] = metrics;
            if (![metrics[@"web_found"] isEqual:@YES] || ![metrics[@"ready"] isEqual:@YES]
                    || ![metrics[@"evaluation_succeeded"] isEqual:@YES]
                    || ![metrics[@"scale_2_present"] isEqual:@YES] || ![metrics[@"buffer_4096_present"] isEqual:@YES]
                    || ![metrics[@"no_horizontal_overflow"] isEqual:@YES]) {
                [self failProbe:@"settings_web_readiness_or_layout_failed"]; return;
            }
            ProbeDiagnosticsCopy(web, ^(NSDictionary *copyMetrics) {
                self.diagnosticsCopyObservation = copyMetrics;
                menu[@"diagnostics_copy"] = copyMetrics;
                BOOL copied = [copyMetrics[@"timed_out"] isEqual:@NO]
                    && [copyMetrics[@"text_bytes"] unsignedIntegerValue] > 0;
                for (NSString *key in @[@"button_found",@"enabled_before",@"click_dispatched",@"completed",
                        @"feedback_success",@"pasteboard_matches",@"clipboard_seeded",@"clipboard_cleared"])
                    copied = copied && [copyMetrics[key] isEqual:@YES];
                if (!copied) { [self failProbe:@"settings_diagnostics_copy_failed"]; return; }
                [self recordCheckpoint:@"settings_diagnostics_copied"];
                BOOL closed = ProbeDispatchButton(close);
                menu[@"return_action_dispatched"] = @(closed);
                menu[@"return_control_event"] = @"touch-up-inside";
                if (!closed) { [self failProbe:@"settings_return_action_failed"]; return; }
                [self recordCheckpoint:@"settings_return_requested"];
                [self observeMenuDismissal:navigation report:report menu:menu
                                  started:NSProcessInfo.processInfo.systemUptime observations:0];
            });
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
