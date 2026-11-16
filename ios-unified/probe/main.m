// Simulator-only UIKit host. This fake Unity class never enters a game IPA.
#import <UIKit/UIKit.h>
#import <WebKit/WebKit.h>
#import "IdolyEmbeddedServer.h"
#import <CommonCrypto/CommonCryptor.h>
#import <CommonCrypto/CommonDigest.h>
#import "../native/IdolyUnityHost.h"
#include <sys/stat.h>
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <math.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
#if IDOLY_SMOKE_SIMULATOR
#import "../native/IdolyOctoBudget.h"
#include "../native/tests/OctoBudgetFixture.h"
#endif

@class IDProbeCoordinator, UnityAppController;
static IDProbeCoordinator *probeCoordinator;
static NSString *probeExpectedLanguage, *probeBundleIdentifier, *probeCachedRoot;
static NSUInteger probeRunIndex;
static NSDictionary *probeCanaryIndex;
static NSMutableDictionary *probeHostProof;
static UIWindow *probePlaceholderWindow;
static __weak id probeHostDelegate;
static BOOL probeRuntimeStarted;
static unsigned probeOriginalRunMainCalls, probeUIKitMainCalls, probeOriginalWarmupCalls;
static void ProbeBeforeHostReady(id application,id delegate);
static NSDictionary *ProbeSignalObservation(void) {
    struct sigaction action={0}; BOOL readPolicy=sigaction(SIGPIPE,NULL,&action)==0;
    BOOL ignored=readPolicy && action.sa_handler==SIG_IGN;
    int pair[2]={-1,-1}; BOOL created=ignored && socketpair(AF_UNIX,SOCK_STREAM,0,pair)==0;
    BOOL peerClosed=created && close(pair[1])==0;
    if (peerClosed) pair[1]=-1;
    BOOL epiped=NO,survived=NO;
    if (peerClosed) {
        unsigned char byte=0; errno=0;
        ssize_t result=write(pair[0],&byte,1); int observedErrno=errno;
        survived=YES; epiped=result==-1 && observedErrno==EPIPE;
    }
    if (pair[0]>=0) close(pair[0]);
    if (pair[1]>=0) close(pair[1]);
    return @{@"schema":@1,@"sigaction_read":@(readPolicy),@"sigpipe_ignored":@(ignored),
        @"socketpair_created":@(created),@"peer_closed":@(peerClosed),@"write_epipe":@(epiped),
        @"process_survived":@(survived),@"main_thread":@(NSThread.isMainThread)};
}
static BOOL ProbeSignalValid(NSDictionary *value,BOOL mainThread) {
    for (NSString *key in @[@"sigaction_read",@"sigpipe_ignored",@"socketpair_created",
            @"peer_closed",@"write_epipe",@"process_survived"])
        if (![value[key] isEqual:@YES]) return NO;
    return [value[@"main_thread"] isEqual:@(mainThread)];
}
static const char *ProbeCachedBundleRoot(void) {
    if (!probeCachedRoot) {
        NSBundle *bundle = [NSBundle bundleWithIdentifier:probeBundleIdentifier ?: @"local.idoly.client-data"];
        probeCachedRoot = [(bundle.bundlePath ?: NSBundle.mainBundle.bundlePath) copy];
    }
    return probeCachedRoot.fileSystemRepresentation;
}
static NSDictionary *ProbeResourceHash(NSString *path) {
    int fd = open(path.fileSystemRepresentation,O_RDONLY|O_NOFOLLOW);
    if (fd < 0) return @{};
    struct stat before={0},after={0}; CC_SHA256_CTX hash; CC_SHA256_Init(&hash);
    unsigned char buffer[65536],digest[CC_SHA256_DIGEST_LENGTH]; unsigned long long count=0;
    BOOL good = fstat(fd,&before)==0 && S_ISREG(before.st_mode) && before.st_size>0 && before.st_size<=128*1024*1024;
    while (good) {
        ssize_t got=read(fd,buffer,sizeof buffer);
        if (got<0) { good=NO; break; }
        if (!got) break;
        count+=(unsigned long long)got;
        if (count>(unsigned long long)before.st_size) { good=NO; break; }
        CC_SHA256_Update(&hash,buffer,(CC_LONG)got);
    }
    good=good && fstat(fd,&after)==0 && count==(unsigned long long)before.st_size && after.st_size==before.st_size;
    close(fd); if (!good) return @{};
    CC_SHA256_Final(digest,&hash); NSMutableString *hex=[NSMutableString stringWithCapacity:64];
    for (NSUInteger index=0;index<sizeof digest;++index) [hex appendFormat:@"%02x",digest[index]];
    return @{@"sha256":hex,@"bytes":@(count),@"identity":@[@(before.st_dev),@(before.st_ino),
        @(before.st_size),@(before.st_mtimespec.tv_sec),@(before.st_mtimespec.tv_nsec)]};
}
static NSArray<NSString *> *ProbeRunLanguages(void) { return @[@"ko",@"en",@"ja",@"en",@"ko"]; }
static NSString *ProbeNextLanguage(void) { return @[@"en",@"ja",@"en",@"ko",@"ko"][probeRunIndex]; }
static NSString *ProbeReportStem(void) {
    return @[@"embedded-probe",@"embedded-language-en",@"embedded-language-ja",
        @"embedded-language-en-return",@"embedded-language-ko-return"][probeRunIndex];
}
static BOOL ProbeRememberCacheIdentity(NSArray *identities) {
    BOOL returning=probeRunIndex>=3;
    probeHostProof[@"cache_return"]=@(returning);
    probeHostProof[@"cache_identity_recorded"]=@NO;
    probeHostProof[@"cache_files_same_identity"]=returning ? @NO : (id)NSNull.null;
    NSURL *documents=[NSFileManager.defaultManager URLsForDirectory:NSDocumentDirectory
        inDomains:NSUserDomainMask].firstObject;
    NSURL *file=[documents URLByAppendingPathComponent:@"probe-cache-identities.json"];
    struct stat info={0}; int exists=file ? lstat(file.path.fileSystemRepresentation,&info) : -1;
    NSMutableDictionary *state;
    if (probeRunIndex==0) {
        if (!file || exists==0 || errno!=ENOENT) return NO;
        state=[@{@"schema":@1,@"next_run":@0,@"languages":@{}} mutableCopy];
    } else {
        if (exists!=0 || !S_ISREG(info.st_mode) || info.st_size<=0 || info.st_size>8192) return NO;
        int fd=open(file.path.fileSystemRepresentation,O_RDONLY|O_NOFOLLOW);
        if (fd<0) return NO;
        unsigned char bytes[8193]; size_t count=0; BOOL readable=YES;
        while (count<sizeof bytes) {
            ssize_t got=read(fd,bytes+count,sizeof bytes-count);
            if (got<0) { readable=NO; break; }
            if (!got) break;
            count+=(size_t)got;
        }
        close(fd);
        if (!readable || count!=(size_t)info.st_size || count>8192) return NO;
        id parsed=[NSJSONSerialization JSONObjectWithData:[NSData dataWithBytes:bytes length:count]
            options:NSJSONReadingMutableContainers error:nil];
        if (![parsed isKindOfClass:NSMutableDictionary.class]) return NO;
        state=parsed;
    }
    NSDictionary *old=state[@"languages"];
    NSSet *keys=probeRunIndex==0 ? [NSSet set] : probeRunIndex==1 ? [NSSet setWithArray:@[@"ko"]]
        : probeRunIndex==2 ? [NSSet setWithArray:@[@"ko",@"en"]] : [NSSet setWithArray:@[@"ko",@"en",@"ja"]];
    if (state.count!=3 || ![state[@"schema"] isEqual:@1] || ![state[@"next_run"] isEqual:@(probeRunIndex)]
            || ![old isKindOfClass:NSDictionary.class] || ![[NSSet setWithArray:old.allKeys] isEqual:keys]
            || identities.count!=2) return NO;
    for (NSArray *pair in [old.allValues arrayByAddingObject:identities]) {
        if (![pair isKindOfClass:NSArray.class] || pair.count!=2) return NO;
        for (NSArray *identity in pair) {
            if (![identity isKindOfClass:NSArray.class] || identity.count!=5) return NO;
            for (NSNumber *number in identity)
                if (![number isKindOfClass:NSNumber.class]
                        || CFGetTypeID((__bridge CFTypeRef)number)==CFBooleanGetTypeID()
                        || CFNumberIsFloatType((__bridge CFNumberRef)number)) return NO;
        }
    }
    if (returning && ![old[probeExpectedLanguage] isEqual:identities]) return NO;
    if (!returning && old[probeExpectedLanguage]) return NO;
    NSMutableDictionary *languages=[old mutableCopy]; languages[probeExpectedLanguage]=identities;
    state[@"languages"]=languages; state[@"next_run"]=@(probeRunIndex+1);
    NSData *raw=[NSJSONSerialization dataWithJSONObject:state options:NSJSONWritingSortedKeys error:nil];
    if (!raw || raw.length>8192 || ![raw writeToURL:file options:NSDataWritingAtomic error:nil]) return NO;
    probeHostProof[@"cache_identity_recorded"]=@YES;
    if (returning) probeHostProof[@"cache_files_same_identity"]=@YES;
    return YES;
}
static NSString *ProbeDataSHA(NSData *data) {
    unsigned char bytes[CC_SHA256_DIGEST_LENGTH]; CC_SHA256(data.bytes,(CC_LONG)data.length,bytes);
    NSMutableString *hex=[NSMutableString stringWithCapacity:64];
    for (NSUInteger index=0;index<sizeof bytes;++index) [hex appendFormat:@"%02x",bytes[index]];
    return hex;
}
static void ProbeConsumeLanguageData(void) {
    NSString *root=[NSString stringWithUTF8String:ProbeCachedBundleRoot()];
    NSBundle *bundle=[NSBundle bundleWithPath:root];
    NSString *language=[bundle.infoDictionary[@"IdolyClientLanguage"] isKindOfClass:NSString.class]
        ? bundle.infoDictionary[@"IdolyClientLanguage"] : @"invalid";
    NSDictionary *expected=probeCanaryIndex[@"languages"][probeExpectedLanguage];
    NSMutableDictionary *canaries=[NSMutableDictionary dictionary];
    NSMutableArray *identities=[NSMutableArray array]; BOOL match=[language isEqual:probeExpectedLanguage];
    for (NSString *name in @[@"Data/resources.assets",@"Data/Managed/Metadata/global-metadata.dat"]) {
        NSDictionary *wanted=expected[name],*actual=ProbeResourceHash([root stringByAppendingPathComponent:name]);
        BOOL same=[wanted[@"sha256"] isEqual:actual[@"sha256"]] && [wanted[@"bytes"] isEqual:actual[@"bytes"]];
        match=match && same;
        if ([actual[@"identity"] isKindOfClass:NSArray.class]) [identities addObject:actual[@"identity"]];
        canaries[name]=@{@"expected_sha256":wanted[@"sha256"] ?: @"",@"actual_sha256":actual[@"sha256"] ?: @"",
            @"expected_bytes":wanted[@"bytes"] ?: @0,@"actual_bytes":actual[@"bytes"] ?: @0};
    }
    probeHostProof[@"consumed_bundle_language"]=language;
    probeHostProof[@"canaries_match"]=@(match);
    probeHostProof[@"canaries"]=canaries;
    if (!match || !ProbeRememberCacheIdentity(identities)) probeHostProof[@"cache_identity_recorded"]=@NO;
}

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
    if ([name hasPrefix:@"embedded-probe"])
        name = [ProbeReportStem() stringByAppendingString:[name substringFromIndex:@"embedded-probe".length]];
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
     "const knownIDs=new Set([\"interface_language\",\"refresh\",\"options-fields\",\"presentation-fields\",\"accounts-fields\",\"accounts-current\",\"accounts-summary\",\"accounts-user-detail\",\"accounts-select\",\"accounts-export\",\"accounts-clone\",\"accounts-new-profile\",\"accounts-manager-name\",\"accounts-restore-point\",\"accounts-feedback\",\"accounts-refresh\",\"diagnostics\",\"message\"]),knownTags=new Set([\"MAIN\",\"SECTION\",\"HEADER\",\"DIV\",\"LABEL\",\"SPAN\",\"BUTTON\",\"SELECT\",\"INPUT\",\"FIELDSET\",\"P\",\"DETAILS\",\"SUMMARY\",\"PRE\",\"OTHER\"]),overflow=[];"
     "if(w>0&&c>w+2)for(const e of Array.from(b?b.querySelectorAll('*'):[]).slice(0,512).reverse()){"
     "const r=e.getBoundingClientRect();if(r.width<=0||r.height<=0||!(r.right>w+2||r.left<-2||e.scrollWidth>r.width+2))continue;"
     "const right=Math.round(r.right*100)/100,width=Math.round(r.width*100)/100,scroll_width=e.scrollWidth;"
     "if(![right,width,scroll_width].every(Number.isFinite)||Math.abs(right)>16384||width>16384||scroll_width<0||scroll_width>16384)continue;"
     "overflow.push({tag:knownTags.has(e.tagName)?e.tagName:'OTHER',id:knownIDs.has(e.id)?e.id:'',right,width,scroll_width});if(overflow.length===8)break;}"
     "return {ready:document.readyState==='complete'&&!!o&&!!p&&!o.disabled&&!p.disabled,"
     "forms_present:!!o&&!!p,document_complete:document.readyState==='complete',"
     "options_fields_enabled:!!o&&!o.disabled,presentation_fields_enabled:!!p&&!p.disabled,"
     "bridge_reply_present:typeof window.idolyServerReply==='function',"
     "launcher_document_marker_absent:window.__idolyProbeLauncherDocument!==true,"
     "scale_2_present:has(s,'2'),buffer_4096_present:has(m,'4096'),"
     "viewport_width:w,content_width:c,no_horizontal_overflow:w>0&&c<=w+2,"
     "select_count:document.querySelectorAll('select').length,overflow_elements:overflow}; })()";

static void ProbeSettingsDOMAttempt(WKWebView *__weak weakWeb, NSMutableDictionary *state,
                                    void (^finish)(NSDictionary *)) {
    if ([state[@"finished"] boolValue]) return;
    WKWebView *web = weakWeb;
    if (!web) { finish(@{@"web_found":@NO, @"timed_out":@NO}); return; }
    state[@"observations"]=@([state[@"observations"] unsignedIntegerValue]+1);
    double progress=web.estimatedProgress;
    BOOL attached=web.window!=nil, fileURL=web.URL.isFileURL, loading=web.isLoading;
    NSMutableDictionary *metrics=[@{@"web_found":@YES,@"timed_out":@NO,
        @"navigation_loading":@(loading),@"navigation_file_url":@(fileURL),@"web_attached":@(attached),
        @"navigation_progress":@(isfinite(progress) ? progress : -1),
        @"evaluation_started":@NO,@"evaluation_completed":@NO} mutableCopy];
    state[@"last"]=metrics;
    // A new settings WK view navigates asynchronously. Do not enqueue a DOM
    // evaluation across its initial file navigation/Page creation transition.
    BOOL navigationReady=!loading && fileURL && attached && progress==1.0;
    if (!navigationReady) {
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/20),dispatch_get_main_queue(),^{
            ProbeSettingsDOMAttempt(weakWeb,state,finish);
        });
        return;
    }
    metrics[@"evaluation_started"]=@YES;
    [web evaluateJavaScript:ProbeSettingsDOMScript completionHandler:^(id value, NSError *error) {
        if ([state[@"finished"] boolValue]) return;
        BOOL wkError=error && [error.domain isEqual:WKErrorDomain];
        metrics[@"evaluation_completed"]=@YES;
        metrics[@"evaluation_succeeded"]=@((BOOL)(!error && [value isKindOfClass:NSDictionary.class]));
        metrics[@"error_is_wk_domain"]=@(wkError);
        if (!error || (error.code>=-100 && error.code<=100)) metrics[@"evaluation_error_code"]=@(error ? error.code : 0);
        if (!error && [value isKindOfClass:NSDictionary.class]) {
            for (NSString *key in @[@"ready", @"forms_present", @"scale_2_present", @"buffer_4096_present",
                    @"viewport_width", @"content_width", @"no_horizontal_overflow", @"select_count",
                    @"document_complete",@"options_fields_enabled",@"presentation_fields_enabled",@"bridge_reply_present",@"launcher_document_marker_absent"]) {
                id scalar = value[key];
                if ([scalar isKindOfClass:NSNumber.class]) metrics[key] = scalar;
            }
            id overflow=value[@"overflow_elements"];
            if ([overflow isKindOfClass:NSArray.class] && [overflow count]<=8) metrics[@"overflow_elements"]=overflow;
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
    NSMutableDictionary *state = [NSMutableDictionary dictionaryWithDictionary:@{@"finished":@NO,@"observations":@0}];
    NSTimeInterval started=NSProcessInfo.processInfo.systemUptime;
    void (^finish)(NSDictionary *) = ^(NSDictionary *metrics) {
        if ([state[@"finished"] boolValue]) return;
        state[@"finished"] = @YES;
        NSMutableDictionary *observed=[metrics mutableCopy];
        observed[@"observations"]=state[@"observations"];
        observed[@"elapsed_seconds"]=@(MAX(0.0,MIN(600.0,NSProcessInfo.processInfo.systemUptime-started)));
        completion(observed);
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

static NSString *const ProbeReplyHook =
    @"if(!window.__idolyProbeHook){const old=window.idolyServerReply;"
     "window.idolyServerReply=function(id,envelope){let v=envelope;try{if(typeof v==='string')v=JSON.parse(v);}catch(e){}"
     "if(v&&v.id===id&&v.ok===true&&v.result){if(typeof v.result.interface_language==='string')"
     "window.__idolyProbeInterfaceAck={id:v.id,language:v.result.interface_language};"
     "const q=window.__idolyProbeOptionsRequest;"
     "if(q&&q.action==='save_options'&&q.id===id&&v.result.options)window.__idolyProbeGameAck={id:v.id,"
     "language:v.result.options.language,effective:v.result.effective_options?v.result.effective_options.language:null};}"
     "return old.apply(this,arguments);};window.__idolyProbeHook=true;}";
static void ProbePollLanguageAttempt(WKWebView *__weak weakWeb,NSString *script,NSTimeInterval deadline,
                                    BOOL (^nativeReady)(void),NSMutableDictionary *state,void (^completion)(NSDictionary *)) {
    if ([state[@"finished"] boolValue]) return;
    WKWebView *web=weakWeb;
    if (!web || NSProcessInfo.processInfo.systemUptime>=deadline) {
        NSMutableDictionary *last=[state[@"last"] mutableCopy] ?: [NSMutableDictionary dictionary];
        last[@"ready"]=@NO; last[@"timed_out"]=@YES; completion(last); return;
    }
    [web evaluateJavaScript:script completionHandler:^(id value,NSError *error){
        if ([state[@"finished"] boolValue]) return;
        if (!error && [value isKindOfClass:NSDictionary.class]) state[@"last"]=[value copy];
        if (!error && [value isKindOfClass:NSDictionary.class] && [value[@"ready"] isEqual:@YES]
                && (!nativeReady || nativeReady())) { completion(value); return; }
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/10),dispatch_get_main_queue(),^{
            ProbePollLanguageAttempt(weakWeb,script,deadline,nativeReady,state,completion);
        });
    }];
}
static void ProbePollLanguage(WKWebView *__weak weakWeb,NSString *script,NSTimeInterval deadline,
                             BOOL (^nativeReady)(void),void (^completion)(NSDictionary *)) {
    ProbePollLanguageAttempt(weakWeb,script,deadline,nativeReady,[NSMutableDictionary dictionary],completion);
}
static void ProbeAutoSaveLanguage(WKWebView *web,NSString *next,NSString *effective,void (^completion)(NSDictionary *)) {
    NSTimeInterval deadline=NSProcessInfo.processInfo.systemUptime+15;
    NSMutableDictionary *state=[@{@"finished":@NO,@"last":@{}} mutableCopy];
    void (^finish)(NSDictionary *)=^(NSDictionary *metrics){
        if ([state[@"finished"] boolValue]) return;
        state[@"finished"]=@YES; completion(metrics);
    };
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,15*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        NSMutableDictionary *last=[state[@"last"] mutableCopy] ?: [NSMutableDictionary dictionary];
        last[@"ready"]=@NO; last[@"timed_out"]=@YES; finish(last);
    });
    // createBridge reads this handler for every send; it does not bind it in
    // advance. Observe metadata and forward the original message exactly once.
    NSString *setup=[ProbeReplyHook stringByAppendingFormat:
        @"(()=>{const s=document.getElementById('language'),f=document.getElementById('options-form'),"
         "h=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.idolyServer;"
         "if(!s||!f||!h||typeof h.postMessage!=='function')return false;"
         "if(!window.__idolyProbeTransportObserver){const original=h.postMessage;const observe=function(r){"
         "if(r&&r.action==='save_options'&&Number.isInteger(r.id))window.__idolyProbeOptionsRequest={id:r.id,action:r.action,language:r.language};"
         "return original.apply(h,arguments);};h.postMessage=observe;if(h.postMessage!==observe)return false;"
         "window.__idolyProbeTransportObserver=true;}"
         "window.__idolyProbeOptionsRequest=null;window.__idolyProbeGameAck=null;"
         "s.value='%@';s.dispatchEvent(new Event('change',{bubbles:true}));return true;})()",next];
    [web evaluateJavaScript:setup completionHandler:^(id value,NSError *error){
        if ([state[@"finished"] boolValue]) return;
        if (error || ![value isEqual:@YES]) { finish(@{@"ready":@NO,@"timed_out":@NO}); return; }
        NSString *poll=[NSString stringWithFormat:
            @"(()=>{const a=window.__idolyProbeGameAck,r=window.__idolyProbeOptionsRequest,f=document.getElementById('options-fields'),"
             "m=document.getElementById('options-save-feedback');const observed=!!r&&r.action==='save_options'&&r.language==='%@',"
             "correlated=observed&&!!a&&a.id===r.id,acknowledged=correlated&&a.language==='%@'&&a.effective==='%@',"
             "enabled=!!f&&!f.disabled,saved=!!m&&m.dataset.state==='saved';"
             "return {ready:acknowledged&&enabled&&saved,request_observed:observed,ack_correlated:correlated,acknowledged,"
             "options_fields_reenabled:enabled,form_feedback_saved:saved,request_id:r?r.id:0,ack_id:a?a.id:0,"
             "request_action:r&&r.action==='save_options'?'save_options':'unknown',"
             "request_language:r&&['ko','en','ja'].includes(r.language)?r.language:'unknown',"
             "ack_language:a&&['ko','en','ja'].includes(a.language)?a.language:'unknown',"
             "ack_effective_language:a&&['ko','en','ja'].includes(a.effective)?a.effective:'unknown',"
             "feedback_state:m&&['ready','pending','saving','saved','invalid','failed'].includes(m.dataset.state)?m.dataset.state:'unknown'};})()",next,next,effective];
        ProbePollLanguageAttempt(web,poll,deadline,nil,state,^(NSDictionary *ack){
            if ([state[@"finished"] boolValue]) return;
            state[@"last"]=ack;
            if (![ack[@"ready"] isEqual:@YES]) { finish(ack); return; }
            NSString *request=[NSString stringWithFormat:@"{\"id\":%lu,\"action\":\"status\"}",(unsigned long)(7900+probeRunIndex)];
            IdolyEmbeddedServerCommand(request,^(NSString *reply){
                if ([state[@"finished"] boolValue]) return;
                NSDictionary *envelope=ProbeObject(reply);
                NSDictionary *status=[envelope[@"result"] isKindOfClass:NSDictionary.class] ? envelope[@"result"] : @{};
                NSDictionary *options=[status[@"options"] isKindOfClass:NSDictionary.class] ? status[@"options"] : @{};
                NSDictionary *activeOptions=[status[@"effective_options"] isKindOfClass:NSDictionary.class] ? status[@"effective_options"] : @{};
                NSString *persisted=options[@"language"],*active=activeOptions[@"language"];
                NSArray *languages=@[@"ko",@"en",@"ja"];
                if (![persisted isKindOfClass:NSString.class] || ![languages containsObject:persisted]) persisted=@"unknown";
                if (![active isKindOfClass:NSString.class] || ![languages containsObject:active]) active=@"unknown";
                BOOL received=[envelope[@"ok"] isEqual:@YES] && [status[@"state"] isEqual:@"ready"] && [status[@"running"] isEqual:@YES];
                BOOL matches=received && [persisted isEqual:next], effectiveMatches=received && [active isEqual:effective];
                BOOL timedOut=NSProcessInfo.processInfo.systemUptime>=deadline;
                NSMutableDictionary *metrics=[ack mutableCopy];
                metrics[@"persisted_language"]=persisted; metrics[@"effective_language"]=active;
                metrics[@"server_status_received"]=@(received); metrics[@"server_language_matches"]=@(matches);
                metrics[@"server_effective_matches"]=@(effectiveMatches); metrics[@"timed_out"]=@(timedOut);
                metrics[@"ready"]=@((BOOL)(matches && effectiveMatches && !timedOut)); state[@"last"]=metrics; finish(metrics);
            });
        });
    }];
}
static NSString *ProbeChromeTitle(NSString *language) {
    return [language isEqual:@"ja"] ? @"アイプラサーバー" : [language isEqual:@"en"] ? @"Idoly Server" : @"아이프라 서버";
}
static NSString *ProbeChromeStart(NSString *language) {
    return [language isEqual:@"ja"] ? @"ゲーム開始" : [language isEqual:@"en"] ? @"Start Game" : @"게임 시작";
}
static NSString *ProbeChromeReady(NSString *language) {
    return [language isEqual:@"ja"] ? @"サーバー稼働中" : [language isEqual:@"en"] ? @"Server Running" : @"서버 실행 중";
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

// Exercise the shipping WK action and public UIKit picker contract on stock
// Simulator. Cancellation is a delegate callback plus programmatic dismissal;
// this does not simulate a Files row tap or LiveContainer's provider/hooks.
static void ProbeZIPImportBegin(WKWebView *__weak web, UIViewController *__weak presenter,
                                NSMutableDictionary *state, void (^finish)(void));
static void ProbeZIPImportObserve(WKWebView *__weak weakWeb, UIViewController *__weak weakPresenter,
                                  NSMutableDictionary *state, void (^finish)(void)) {
    if ([state[@"finished"] boolValue]) return;
    WKWebView *web=weakWeb; UIViewController *presenter=weakPresenter;
    if (!web || !presenter) { finish(); return; }
    state[@"observations"]=@([state[@"observations"] unsignedIntegerValue]+1);
    NSMutableDictionary *pass=[state[@"passes"] lastObject];
    UIDocumentPickerViewController *picker=state[@"picker"];
    if (!picker) {
        UIViewController *shown=presenter.presentedViewController;
        if ([shown isKindOfClass:UIDocumentPickerViewController.class]
                && shown.viewIfLoaded.window && !shown.isBeingPresented) {
            picker=(UIDocumentPickerViewController *)shown; state[@"picker"]=picker;
            pass[@"picker_presented"]=@YES; pass[@"document_picker_mode"]=@(picker.documentPickerMode);
            pass[@"single_selection"]=@((BOOL)(!picker.allowsMultipleSelection));
            pass[@"delegate_is_settings"]=@((BOOL)(picker.delegate==(id)presenter));
            if (![picker.delegate respondsToSelector:@selector(documentPickerWasCancelled:)]) { finish(); return; }
            [picker.delegate documentPickerWasCancelled:picker]; pass[@"cancel_delegate_invoked"]=@YES;
            [picker dismissViewControllerAnimated:NO completion:nil]; pass[@"dismissed_programmatically"]=@YES;
        }
    } else if (!presenter.presentedViewController && !picker.viewIfLoaded.window) {
        pass[@"picker_detached"]=@YES;
        [web evaluateJavaScript:@"(() => {const b=document.getElementById('resources-import');return !!b&&!b.disabled;})()"
            completionHandler:^(id value,NSError *error) {
                if ([state[@"finished"] boolValue]) return;
                if (!error && [value isEqual:@YES]) {
                    pass[@"button_restored"]=@YES;
                    if ([state[@"passes"] count]==1) {
                        [state removeObjectForKey:@"picker"];
                        ProbeZIPImportBegin(weakWeb,weakPresenter,state,finish);
                    } else dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0),^{
                        BOOL grpc=ProbePort(50051), assets=ProbePort(8080);
                        dispatch_async(dispatch_get_main_queue(),^{
                            if ([state[@"finished"] boolValue]) return;
                            state[@"metrics"][@"grpc_connected_after_cancel"]=@(grpc);
                            state[@"metrics"][@"assets_connected_after_cancel"]=@(assets);
                            finish();
                        });
                    });
                } else dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/10),dispatch_get_main_queue(),^{
                    ProbeZIPImportObserve(weakWeb,weakPresenter,state,finish);
                });
            }];
        return;
    }
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/10),dispatch_get_main_queue(),^{
        ProbeZIPImportObserve(weakWeb,weakPresenter,state,finish);
    });
}
static void ProbeZIPImportBegin(WKWebView *__weak weakWeb, UIViewController *__weak weakPresenter,
                                NSMutableDictionary *state, void (^finish)(void)) {
    if ([state[@"finished"] boolValue]) return;
    WKWebView *web=weakWeb; UIViewController *presenter=weakPresenter;
    if (!web || !presenter || presenter.presentedViewController) { finish(); return; }
    // Account-list initialization also serializes the file buttons. Wait for
    // the real control to become enabled inside the existing 12-second budget;
    // retain one pass per actual click rather than recording retries as clicks.
    NSMutableDictionary *pass=state[@"begin_pass"];
    if (!pass) {
        pass=[NSMutableDictionary dictionary];state[@"begin_pass"]=pass;[state[@"passes"] addObject:pass];
    }
    state[@"observations"]=@([state[@"observations"] unsignedIntegerValue]+1);
    NSString *script=@"(() => {const b=document.getElementById('resources-import');const e=!!b&&!b.disabled;"
        "if(e)b.click();return {button_found:!!b,enabled_before:e,click_dispatched:e,button_disabled_while_pending:!!b&&b.disabled};})()";
    [web evaluateJavaScript:script completionHandler:^(id value,NSError *error) {
        if ([state[@"finished"] boolValue]) return;
        if (error || ![value isKindOfClass:NSDictionary.class]) { finish(); return; }
        for (NSString *key in @[@"button_found",@"enabled_before",@"click_dispatched",@"button_disabled_while_pending"])
            pass[key]=@((BOOL)[value[key] isEqual:@YES]);
        if (![pass[@"click_dispatched"] isEqual:@YES]) {
            if (![pass[@"button_found"] isEqual:@YES]) { finish();return; }
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/10),dispatch_get_main_queue(),^{
                ProbeZIPImportBegin(weakWeb,weakPresenter,state,finish);
            });
            return;
        }
        [state removeObjectForKey:@"begin_pass"];
        ProbeZIPImportObserve(weakWeb,weakPresenter,state,finish);
    }];
}
static void ProbeZIPImportPicker(WKWebView *web,UIViewController *presenter,void (^completion)(NSDictionary *)) {
    NSCAssert(NSThread.isMainThread,@"ZIP picker probe belongs on main thread");
    NSMutableArray *passes=[NSMutableArray array];
    NSMutableDictionary *metrics=[@{@"scope":@"stock-simulator",@"cancel_trigger":@"delegate-callback",
        @"timed_out":@NO,@"passes":passes} mutableCopy];
    NSMutableDictionary *state=[@{@"finished":@NO,@"observations":@0,@"passes":passes,@"metrics":metrics} mutableCopy];
    NSTimeInterval started=NSProcessInfo.processInfo.systemUptime;
    void (^finish)(void)=^{
        if ([state[@"finished"] boolValue]) return;
        state[@"finished"]=@YES; metrics[@"observations"]=state[@"observations"];
        metrics[@"elapsed_seconds"]=@(MAX(0.0,MIN(600.0,NSProcessInfo.processInfo.systemUptime-started)));
        completion(metrics.copy);
    };
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,12*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        if ([state[@"finished"] boolValue]) return;
        metrics[@"timed_out"]=@YES; finish();
    });
    ProbeZIPImportBegin(web,presenter,state,finish);
}

static void ProbeZIPRoundTripPoll(WKWebView *__weak web,UIViewController *__weak presenter,
                                  NSMutableDictionary *state,void (^finish)(void));
static void ProbeZIPRoundTripPicker(WKWebView *__weak weakWeb,UIViewController *__weak weakPresenter,
                                    NSMutableDictionary *state,void (^finish)(void)) {
    if ([state[@"finished"] boolValue]) return;
    UIViewController *presenter=weakPresenter; UIViewController *shown=presenter.presentedViewController;
    if ([shown isKindOfClass:UIDocumentPickerViewController.class] && shown.viewIfLoaded.window && !shown.isBeingPresented) {
        UIDocumentPickerViewController *picker=(UIDocumentPickerViewController *)shown;
        NSMutableDictionary *metrics=state[@"metrics"];
        metrics[@"picker_presented"]=@YES; metrics[@"picker_import_mode"]=@((BOOL)(picker.documentPickerMode==UIDocumentPickerModeImport));
        metrics[@"picker_single_selection"]=@((BOOL)(!picker.allowsMultipleSelection));
        if (![picker.delegate respondsToSelector:@selector(documentPicker:didPickDocumentsAtURLs:)]) { finish(); return; }
        [picker.delegate documentPicker:picker didPickDocumentsAtURLs:@[[NSURL fileURLWithPath:state[@"source"]]]];
        metrics[@"selection_delegate_invoked"]=@YES;
        [picker dismissViewControllerAnimated:NO completion:nil]; metrics[@"dismissed_programmatically"]=@YES;
        state[@"phase"]=@"import"; ProbeZIPRoundTripPoll(weakWeb,weakPresenter,state,finish); return;
    }
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/4),dispatch_get_main_queue(),^{
        ProbeZIPRoundTripPicker(weakWeb,weakPresenter,state,finish);
    });
}
static void ProbeZIPRoundTripOpen(WKWebView *web,UIViewController *presenter,NSMutableDictionary *state,void (^finish)(void)) {
    NSString *script=@"(() => {const b=document.getElementById('resources-import');if(!b||b.disabled)return {ready:false};"
        "const q=window.__idolyZIPRoundTripObserved={request_id:null,queued:false,copied_bytes:0,total_bytes:0,reply_accepted:false};"
        "const event=window.idolyServerEvent,reply=window.idolyServerReply;"
        "window.idolyServerEvent=function(v){if(v&&v.event==='resource_import_progress'){"
        "if(q.request_id===null)q.request_id=v.request_id;if(q.request_id===v.request_id){"
        "q.queued=q.queued||v.stage==='queued';q.copied_bytes=v.copied_bytes;q.total_bytes=v.total_bytes;}}return event.apply(this,arguments);};"
        "window.idolyServerReply=function(id,v){let x=v;try{if(typeof x==='string')x=JSON.parse(x);}catch(_){}"
        "if(id===q.request_id&&x&&x.ok===true&&x.result&&x.result.accepted===true)q.reply_accepted=true;return reply.apply(this,arguments);};"
        "b.click();return {ready:true,button_disabled:b.disabled};})()";
    ProbePollLanguage(web,script,[state[@"deadline"] doubleValue],nil,^(NSDictionary *value){
        if ([state[@"finished"] boolValue]) return;
        state[@"metrics"][@"wk_import_dispatched"]=@((BOOL)([value[@"ready"] isEqual:@YES] && [value[@"button_disabled"] isEqual:@YES]));
        if (![value[@"ready"] isEqual:@YES]) { finish(); return; }
        ProbeZIPRoundTripPicker(web,presenter,state,finish);
    });
}
static void ProbeZIPRoundTripPoll(WKWebView *__weak weakWeb,UIViewController *__weak weakPresenter,
                                  NSMutableDictionary *state,void (^finish)(void)) {
    if ([state[@"finished"] boolValue]) return;
    IdolyEmbeddedServerCommand(@"{\"id\":7302,\"action\":\"status\"}",^(NSString *reply){
        if ([state[@"finished"] boolValue]) return;
        NSDictionary *envelope=ProbeObject(reply), *status=envelope[@"result"];
        NSDictionary *operation=[status[@"resource_operation"] isKindOfClass:NSDictionary.class] ? status[@"resource_operation"] : @{};
        NSDictionary *job=[operation[@"job"] isKindOfClass:NSDictionary.class] ? operation[@"job"] : @{};
        NSMutableDictionary *metrics=state[@"metrics"];
        if ([state[@"phase"] isEqual:@"export"] && [operation[@"ready"] isEqual:@YES] && [job[@"action"] isEqual:@"export"]) {
            metrics[@"export_ready"]=@([operation[@"accepted"] isEqual:@YES]);
            metrics[@"export_archive_complete"]=@([job[@"archive_complete"] isEqual:@YES]);
            metrics[@"exported_files"]=job[@"exported_files"] ?: @0;
            NSString *source=operation[@"output_path"], *imports=status[@"paths"][@"imports"];
            if (![source isKindOfClass:NSString.class] || ![imports isKindOfClass:NSString.class]) { finish(); return; }
            state[@"source"]=source; state[@"imports"]=imports;
            dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0),^{
                NSDictionary *hash=ProbeResourceHash(source);
                NSArray *before=[NSFileManager.defaultManager contentsOfDirectoryAtPath:imports error:NULL] ?: @[];
                dispatch_async(dispatch_get_main_queue(),^{
                    if ([state[@"finished"] boolValue]) return;
                    if (!hash[@"sha256"]) { finish(); return; }
                    state[@"source_hash"]=hash; state[@"before_imports"]=[NSSet setWithArray:before];
                    metrics[@"source_bytes"]=hash[@"bytes"]; metrics[@"source_sha256"]=hash[@"sha256"];
                    ProbeZIPRoundTripOpen(weakWeb,weakPresenter,state,finish);
                });
            }); return;
        }
        if ([state[@"phase"] isEqual:@"import"] && [operation[@"ready"] isEqual:@YES] && [job[@"action"] isEqual:@"import"]) {
            metrics[@"backend_ready"]=@YES;
            metrics[@"backend_success"]=@((BOOL)([operation[@"accepted"] isEqual:@YES] && [job[@"platform"] isEqual:@"ios"]
                && [@[@"completed",@"partial"] containsObject:job[@"state"]] && [job[@"failed_files"] isEqual:@0]));
            metrics[@"imported_files"]=job[@"imported_files"] ?: @0; metrics[@"failed_files"]=job[@"failed_files"] ?: @(-1);
            NSNumber *requests=status[@"runtime"][@"resource_transfer"][@"session_http_requests"];
            metrics[@"upstream_requests_unchanged"]=@([requests isEqual:state[@"upstream_requests"]]);
            NSString *script=@"(() => {const q=window.__idolyZIPRoundTripObserved||{},b=document.getElementById('resources-import'),"
                "s=document.getElementById('resource-state');return {reply_accepted:q.reply_accepted===true,queued:q.queued===true,"
                "copied_bytes:q.copied_bytes||0,total_bytes:q.total_bytes||0,button_restored:!!b&&!b.disabled,"
                "ready:!!s&&['완료','일부 완료','Complete','Partially complete','完了','一部完了'].includes(s.textContent)&&!!b&&!b.disabled};})()";
            ProbePollLanguage(weakWeb,script,[state[@"deadline"] doubleValue],nil,^(NSDictionary *value){
                if ([state[@"finished"] boolValue]) return;
                metrics[@"import_reply_accepted"]=@([value[@"reply_accepted"] isEqual:@YES]);
                metrics[@"native_copy_queued"]=@([value[@"queued"] isEqual:@YES]);
                metrics[@"copied_bytes"]=value[@"copied_bytes"] ?: @0; metrics[@"total_bytes"]=value[@"total_bytes"] ?: @0;
                metrics[@"dom_completed"]=@([value[@"ready"] isEqual:@YES]);
                metrics[@"button_restored"]=@([value[@"button_restored"] isEqual:@YES]);
                metrics[@"picker_detached"]=@((BOOL)(weakPresenter.presentedViewController==nil));
                dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0),^{
                    NSString *imports=state[@"imports"], *copyPath=nil;
                    for (NSString *name in [NSFileManager.defaultManager contentsOfDirectoryAtPath:imports error:NULL])
                        if (![state[@"before_imports"] containsObject:name] && [name.pathExtension.lowercaseString isEqual:@"zip"]) {
                            if (copyPath) { copyPath=nil; break; } copyPath=[imports stringByAppendingPathComponent:name];
                        }
                    NSDictionary *copied=copyPath ? ProbeResourceHash(copyPath) : @{}, *source=ProbeResourceHash(state[@"source"]);
                    dispatch_async(dispatch_get_main_queue(),^{
                        if ([state[@"finished"] boolValue]) return;
                        NSDictionary *original=state[@"source_hash"];
                        metrics[@"owned_copy_found"]=@((BOOL)(copied[@"sha256"]!=nil));
                        metrics[@"copy_source_distinct"]=@((BOOL)(copied[@"identity"] && ![copied[@"identity"] isEqual:original[@"identity"]]));
                        metrics[@"source_preserved"]=@((BOOL)([source[@"sha256"] isEqual:original[@"sha256"]] && [source[@"bytes"] isEqual:original[@"bytes"]]));
                        metrics[@"copy_bytes_match"]=@((BOOL)([copied[@"bytes"] isEqual:original[@"bytes"]]
                            && [metrics[@"copied_bytes"] isEqual:original[@"bytes"]] && [metrics[@"total_bytes"] isEqual:original[@"bytes"]]));
                        metrics[@"source_copy_sha256_match"]=@([copied[@"sha256"] isEqual:original[@"sha256"]]);
                        metrics[@"copied_sha256"]=copied[@"sha256"] ?: @""; finish();
                    });
                });
            }); return;
        }
        if ([operation[@"accepted"] isEqual:@NO]) { finish(); return; }
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/4),dispatch_get_main_queue(),^{
            ProbeZIPRoundTripPoll(weakWeb,weakPresenter,state,finish);
        });
    });
}
static void ProbeZIPRoundTrip(WKWebView *web,UIViewController *presenter,void (^completion)(NSDictionary *)) {
    if (probeRunIndex!=0) { completion(@{@"performed":@NO,@"reason":@"first-cold-run-only"}); return; }
    NSMutableDictionary *metrics=[@{@"performed":@YES,@"scope":@"stock-simulator",
        @"selection_trigger":@"delegate-callback",@"timed_out":@NO} mutableCopy];
    NSTimeInterval started=NSProcessInfo.processInfo.systemUptime;
    NSMutableDictionary *state=[@{@"finished":@NO,@"metrics":metrics,@"phase":@"export",@"deadline":@(started+120)} mutableCopy];
    void (^finish)(void)=^{
        if ([state[@"finished"] boolValue]) return;
        state[@"finished"]=@YES; metrics[@"elapsed_seconds"]=@(MAX(0.0,NSProcessInfo.processInfo.systemUptime-started));
        completion(metrics.copy);
    };
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,120*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        if ([state[@"finished"] boolValue]) return; metrics[@"timed_out"]=@YES; finish();
    });
    IdolyEmbeddedServerCommand(@"{\"id\":7300,\"action\":\"status\"}",^(NSString *reply){
        if ([state[@"finished"] boolValue]) return;
        NSDictionary *status=ProbeObject(reply)[@"result"];
        state[@"upstream_requests"]=status[@"runtime"][@"resource_transfer"][@"session_http_requests"] ?: @(-1);
        IdolyEmbeddedServerCommand(@"{\"id\":7301,\"action\":\"resources_export\"}",^(NSString *exportReply){
            if ([state[@"finished"] boolValue]) return;
            NSDictionary *value=ProbeObject(exportReply);
            metrics[@"export_accepted"]=@((BOOL)([value[@"ok"] isEqual:@YES] && [value[@"result"][@"accepted"] isEqual:@YES]));
            if (![metrics[@"export_accepted"] isEqual:@YES]) { finish(); return; }
            ProbeZIPRoundTripPoll(web,presenter,state,finish);
        });
    });
}

static NSString *const ProbeAccountScenario =
    @"(function(config){\n"
    "  const q=window.__idolyAccountProbe={done:false,error:null,pause:null,expected:null,request:null,reply:null,\n"
    "    ui_actions:[],flags:{},preview_evidence:[],copy:null,seedAck:null,exportReady:false,pendingObserved:false,originalObserved:false,previewRound:0};\n"
    "  const h=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.idolyServer;\n"
    "  if(!h||typeof h.postMessage!=='function')return false;\n"
    "  const oldPost=h.postMessage,oldReply=window.idolyServerReply,oldEvent=window.idolyServerEvent;\n"
    "  h.postMessage=function(r){if(r&&r.action===q.expected&&q.request===null&&Number.isInteger(r.id)){\n"
    "    q.request={id:r.id,action:r.action};q.ui_actions.push(r.action);}\n"
    "    return oldPost.apply(h,arguments);};\n"
    "  window.idolyServerReply=function(id,envelope){let v=envelope;try{if(typeof v==='string')v=JSON.parse(v);}catch(_){}\n"
    "    if(q.request&&q.request.id===id&&v&&v.id===id)q.reply=v;return oldReply.apply(this,arguments);};\n"
    "  window.idolyServerEvent=function(v){if(v&&v.event==='account_import_progress'&&q.expected==='accounts_preview'\n"
    "      &&q.request&&v.request_id===q.request.id){q.copy=q.copy||{queued:false,copied_bytes:0,total_bytes:0};\n"
    "      q.copy.queued=q.copy.queued||v.stage==='queued';q.copy.copied_bytes=v.copied_bytes;q.copy.total_bytes=v.total_bytes;}\n"
    "    return oldEvent.apply(this,arguments);};\n"
    "  const until=async f=>{while(!f()){if(q.error||Date.now()>config.deadline)throw Error('account_ui_timeout');await new Promise(r=>setTimeout(r,75));}};\n"
    "  const current=profile=>{const s=document.getElementById('accounts-current'),v=JSON.stringify([config.mode,profile]);\n"
    "    if(!s||!Array.from(s.options).some(o=>o.value===v))throw Error('account_ui_account_missing');\n"
    "    s.value=v;s.dispatchEvent(new Event('change',{bubbles:true}));};\n"
    "  const set=(id,value)=>{const e=document.getElementById(id);if(!e)throw Error('account_ui_control_missing');e.value=value;};\n"
    "  const click=async(action,setup,ok=true)=>{\n"
    "    const id=action==='status'?'accounts-refresh':'accounts-'+action,b=document.getElementById(id);\n"
    "    const fields=document.getElementById('accounts-fields');if(!b||!fields)throw Error('account_ui_control_missing');\n"
    "    await until(()=>!b.disabled);if(setup)setup();await until(()=>!b.disabled);\n"
    "    q.expected='accounts_'+action;q.request=null;q.reply=null;if(action==='preview')q.copy=null;\n"
    "    b.scrollIntoView({block:'center'});b.click();\n"
    "    await until(()=>q.request&&q.reply&&q.reply.id===q.request.id&&!fields.disabled);\n"
    "    if(q.reply.ok!==ok)throw Error('account_ui_request_failed');\n"
    "    if(ok&&(!q.reply.result||q.reply.result.action!==q.expected))throw Error('account_ui_reply_mismatch');\n"
    "    return ok?q.reply.result:q.reply.error;\n"
    "  };\n"
    "  const seed=async phase=>{q.seedAck=null;q.pause='seed-'+phase;await until(()=>q.seedAck&&q.seedAck.phase===phase);\n"
    "    if(phase==='source')q.sourceFixture=q.seedAck;else q.targetFixture=q.seedAck;q.pause=null;await click('status');};\n"
    "  const preview=async()=>{q.previewRound++;q.pause='preview';const v=await click('preview');q.pause=null;\n"
    "    q.preview_evidence.push(q.copy||{});if(!v.archive||v.archive.mode!==config.mode)throw Error('account_ui_preview_mismatch');return v;};\n"
    "  async function run(){\n"
    "    await click('status');q.flags.management_controls_ready=true;\n"
    "    await click('clone',()=>{current(config.active);set('accounts-new-profile',config.source);});\n"
    "    q.flags.inactive_clone_created=true;\n"
    "    await seed('source');current(config.source);\n"
    "    q.export=await click('export');q.pause='export';await until(()=>q.exportReady);q.pause=null;\n"
    "    q.flags.export_reply_correlated=true;\n"
    "    await preview();\n"
    "    const blocked=await click('import',()=>{current(config.active);document.getElementById('accounts-replace').checked=true;},false);\n"
    "    if(!blocked||blocked.code!=='account_restart_required')throw Error('account_ui_active_guard_failed');\n"
    "    q.flags.active_account_replace_rejected=true;\n"
    "    await click('import',()=>{document.getElementById('accounts-replace').checked=false;set('accounts-new-profile',config.target);});\n"
    "    q.flags.new_import_completed=true;\n"
    "    await seed('target');\n"
    "    await preview();\n"
    "    const replaced=await click('import',()=>{current(config.target);document.getElementById('accounts-replace').checked=true;});\n"
    "    const point=replaced.status&&replaced.status.restore_points.find(r=>r.mode===config.mode&&r.profile===config.target&&r.revision===q.targetFixture.bundle_revision);\n"
    "    if(!point)throw Error('account_ui_restore_point_missing');\n"
    "    q.flags.automatic_restore_point_created=true;\n"
    "    const restored=await click('restore',()=>{current(config.target);set('accounts-restore-point',point.id);\n"
    "      document.getElementById('accounts-restore-point').dispatchEvent(new Event('change',{bubbles:true}));});\n"
    "    const target=restored.status&&restored.status.accounts.find(r=>r.mode===config.mode&&r.profile===config.target);\n"
    "    if(!target||target.revision!==q.targetFixture.bundle_revision)throw Error('account_ui_restore_revision_differs');\n"
    "    q.flags.inactive_replace_completed=true;q.flags.restore_revision_matches=true;\n"
    "    const selected=await click('select',()=>current(config.source));\n"
    "    if(!selected.status||selected.status.selected[config.mode]!==config.source)throw Error('account_ui_selection_failed');\n"
    "    q.flags.next_start_selection_saved=true;q.pause='pending';await until(()=>q.pendingObserved);q.pause=null;\n"
    "    const original=await click('select',()=>current(config.active));\n"
    "    if(!original.status||original.status.selected[config.mode]!==config.active)throw Error('account_ui_selection_failed');\n"
    "    q.flags.original_selection_saved=true;q.pause='original';await until(()=>q.originalObserved);q.pause=null;\n"
    "    const feedback=document.getElementById('accounts-feedback'),fields=document.getElementById('accounts-fields');\n"
    "    q.flags.feedback_present=!!feedback&&!!feedback.textContent.trim();\n"
    "    q.flags.fields_reenabled=!!fields&&!fields.disabled;\n"
    "    q.flags.native_copy_queued=q.preview_evidence.length===2&&q.preview_evidence.every(v=>v.queued===true);\n"
    "    q.flags.native_copy_bytes_match=q.preview_evidence.length===2&&q.preview_evidence.every(v=>v.copied_bytes===q.export.bytes&&v.total_bytes===q.export.bytes);\n"
    "    q.done=true;\n"
    "  }\n"
    "  run().catch(e=>{q.error=/^account_ui_[a-z_]+$/.test(String(e&&e.message))?e.message:'account_ui_flow_failed';});\n"
    "  return true;\n"
    "})";

static NSString *ProbeAccountJSON(id value) {
    NSData *raw=[NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingSortedKeys error:NULL];
    return raw ? [[NSString alloc] initWithData:raw encoding:NSUTF8StringEncoding] : nil;
}
static NSDictionary *ProbeAccountSmallFile(NSString *path) {
    struct stat before,after;
    if (lstat(path.fileSystemRepresentation,&before)!=0 || !S_ISREG(before.st_mode) || before.st_nlink!=1
            || before.st_size<=0 || before.st_size>8192) return nil;
    NSData *raw=[NSData dataWithContentsOfFile:path];
    if (!raw || raw.length!=(NSUInteger)before.st_size || lstat(path.fileSystemRepresentation,&after)!=0
            || before.st_dev!=after.st_dev || before.st_ino!=after.st_ino || before.st_size!=after.st_size
            || before.st_mtimespec.tv_sec!=after.st_mtimespec.tv_sec || before.st_mtimespec.tv_nsec!=after.st_mtimespec.tv_nsec) return nil;
    id value=[NSJSONSerialization JSONObjectWithData:raw options:0 error:NULL];
    return [value isKindOfClass:NSDictionary.class] ? value : nil;
}
static void ProbeAccountPoll(WKWebView *__weak weakWeb,UIViewController *__weak weakPresenter,
                             NSMutableDictionary *state,void (^finish)(void));
static void ProbeAccountResume(WKWebView *web,NSString *script) {
    [web evaluateJavaScript:script completionHandler:^(id value,NSError *error){(void)value;(void)error;}];
}
static void ProbeAccountSeed(WKWebView *web,NSMutableDictionary *state,NSString *phase,void (^finish)(void)) {
    if ([state[[@"seed_done_" stringByAppendingString:phase]] boolValue]) return;
    NSString *documents=state[@"documents"],*requestPath=[documents stringByAppendingPathComponent:@"embedded-probe-account-seed.json"];
    NSString *ackPath=[documents stringByAppendingPathComponent:@"embedded-probe-account-seed-ack.json"];
    NSString *key=[@"seed_request_" stringByAppendingString:phase];
    NSDictionary *request=state[key];
    if (!request) {
        NSDictionary *config=state[@"config"];
        NSString *nonceSource=[config[@"nonce"] stringByAppendingFormat:@":%@",phase];
        NSData *nonceBytes=[nonceSource dataUsingEncoding:NSUTF8StringEncoding];
        request=@{@"schema":@1,@"run_index":@0,@"nonce":[ProbeDataSHA(nonceBytes) substringToIndex:32],@"phase":phase,
            @"mode":config[@"mode"],@"profile":[phase isEqual:@"source"]?config[@"source"]:config[@"target"],
            @"active_profile":config[@"active"]};
        NSData *raw=[NSJSONSerialization dataWithJSONObject:request options:NSJSONWritingSortedKeys error:NULL];
        if (!raw || !ProbeWrite(@"embedded-probe-account-seed.json",request)) { finish(); return; }
        state[key]=request; state[[key stringByAppendingString:@"_sha"]]=ProbeDataSHA(raw);
    }
    NSDictionary *ack=ProbeAccountSmallFile(ackPath);
    if (!ack) return;
    NSString *hash=state[[key stringByAppendingString:@"_sha"]];
    BOOL valid=[ack[@"schema"] isEqual:@1] && [ack[@"ready"] isEqual:@YES]
        && [ack[@"nonce"] isEqual:request[@"nonce"]] && [ack[@"phase"] isEqual:phase]
        && [ack[@"request_sha256"] isEqual:hash] && [ack[@"mode"] isEqual:request[@"mode"]]
        && [ack[@"profile"] isEqual:request[@"profile"]];
    NSDictionary *rows=[ack[@"table_rows"] isKindOfClass:NSDictionary.class]?ack[@"table_rows"]:@{};
    for (NSString *table in @[@"profiles",@"snapshots",@"profile_settings",@"starter_profiles",
            @"profile_lesson_progress",@"preference_receipts",@"main_live_attempts"])
        valid=valid && [rows[table] isKindOfClass:NSNumber.class]
            && CFGetTypeID((__bridge CFTypeRef)rows[table])!=CFBooleanGetTypeID()
            && [rows[table] unsignedIntegerValue]>0 && [rows[table] unsignedIntegerValue]<=20000;
    if (!valid) { finish(); return; }
    state[[@"seed_done_" stringByAppendingString:phase]]=@YES;
    NSMutableDictionary *safe=[ack mutableCopy];
    [safe removeObjectForKey:@"nonce"];[safe removeObjectForKey:@"profile"];[safe removeObjectForKey:@"mode"];
    state[@"metrics"][[@"fixture_" stringByAppendingString:phase]]=safe.copy;
    [NSFileManager.defaultManager removeItemAtPath:ackPath error:NULL];
    [NSFileManager.defaultManager removeItemAtPath:requestPath error:NULL];
    ProbeAccountResume(web,[NSString stringWithFormat:@"window.__idolyAccountProbe.seedAck=%@;",ProbeAccountJSON(ack)]);
}
static void ProbeAccountPoll(WKWebView *__weak weakWeb,UIViewController *__weak weakPresenter,
                             NSMutableDictionary *state,void (^finish)(void)) {
    if ([state[@"finished"] boolValue]) return;
    WKWebView *web=weakWeb;UIViewController *presenter=weakPresenter;
    if (!web || !presenter) { finish(); return; }
    NSString *script=@"(()=>{const q=window.__idolyAccountProbe;return q?{done:q.done,error:q.error,pause:q.pause,flags:q.flags,ui_actions:q.ui_actions,"
        "previewRound:q.previewRound,preview_evidence:q.preview_evidence,export_meta:q.export?{filename:q.export.filename,bytes:q.export.bytes,sha256:q.export.sha256}:null}:null;})()";
    [web evaluateJavaScript:script completionHandler:^(id value,NSError *error){
        if ([state[@"finished"] boolValue]) return;
        if (error || ![value isKindOfClass:NSDictionary.class]) { finish(); return; }
        NSMutableDictionary *metrics=state[@"metrics"];
        metrics[@"ui_flags"]=value[@"flags"] ?: @{};
        metrics[@"ui_actions"]=value[@"ui_actions"] ?: @[];
        metrics[@"preview_copies"]=value[@"preview_evidence"] ?: @[];
        if ([value[@"error"] isKindOfClass:NSString.class]) { metrics[@"error_code"]=value[@"error"];finish();return; }
        if ([value[@"done"] isEqual:@YES]) { metrics[@"completed"]=@YES;finish();return; }
        NSString *phase=[value[@"pause"] isKindOfClass:NSString.class]?value[@"pause"]:@"";
        if ([phase hasPrefix:@"seed-"]) ProbeAccountSeed(web,state,[phase substringFromIndex:5],finish);
        else if ([phase isEqual:@"export"] && ![state[@"export_started"] boolValue]) {
            UIViewController *shown=presenter.presentedViewController;
            NSDictionary *meta=[value[@"export_meta"] isKindOfClass:NSDictionary.class]?value[@"export_meta"]:@{};
            NSString *name=[meta[@"filename"] isKindOfClass:NSString.class]?meta[@"filename"]:nil;
            NSRegularExpression *known=[NSRegularExpression regularExpressionWithPattern:@"^IdolyPride-Account-[0-9a-f]{32}\\.zip$" options:0 error:NULL];
            if ([shown isKindOfClass:UIDocumentPickerViewController.class] && shown.viewIfLoaded.window && !shown.isBeingPresented
                    && name && [known numberOfMatchesInString:name options:0 range:NSMakeRange(0,name.length)]==1) {
                UIDocumentPickerViewController *picker=(UIDocumentPickerViewController *)shown;
                if (picker.documentPickerMode!=UIDocumentPickerModeExportToService) { finish();return; }
                state[@"export_started"]=@YES;state[@"export_picker"]=picker;metrics[@"export_picker_presented"]=@YES;
                NSString *source=[state[@"exports"] stringByAppendingPathComponent:name];
                NSString *target=state[@"source"];
                dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0),^{
                    NSDictionary *original=ProbeResourceHash(source);
                    BOOL copied=original[@"sha256"] && ![NSFileManager.defaultManager fileExistsAtPath:target]
                        && [NSFileManager.defaultManager copyItemAtPath:source toPath:target error:NULL];
                    NSDictionary *copy=copied?ProbeResourceHash(target):@{};
                    dispatch_async(dispatch_get_main_queue(),^{
                        if ([state[@"finished"] boolValue]) return;
                        BOOL equal=[original[@"sha256"] isEqual:meta[@"sha256"]] && [copy[@"sha256"] isEqual:original[@"sha256"]]
                            && [original[@"bytes"] isEqual:meta[@"bytes"]] && [copy[@"bytes"] isEqual:original[@"bytes"]];
                        metrics[@"archive_sha256"]=copy[@"sha256"] ?: @"";
                        metrics[@"archive_bytes"]=copy[@"bytes"] ?: @0;metrics[@"archive_copy_sha256_verified"]=@((BOOL)equal);
                        if (!equal || ![picker.delegate respondsToSelector:@selector(documentPickerWasCancelled:)]) { finish();return; }
                        [picker.delegate documentPickerWasCancelled:picker];
                        state[@"export_cancel_requested"]=@YES;
                        [picker dismissViewControllerAnimated:NO completion:nil];
                    });
                });
            }
        } else if ([phase isEqual:@"export"] && [state[@"export_cancel_requested"] boolValue]
                && ![state[@"export_detached"] boolValue]) {
            // A cancellation delegate callback does not finish UIKit dismissal.
            // Do not send the preview action while the export sheet is attached.
            UIDocumentPickerViewController *picker=state[@"export_picker"];
            if (picker && !presenter.presentedViewController && !picker.viewIfLoaded.window && !picker.isBeingDismissed) {
                state[@"export_detached"]=@YES;metrics[@"export_picker_cancelled"]=@YES;
                ProbeAccountResume(web,@"window.__idolyAccountProbe.exportReady=true;");
            }
        } else if ([phase isEqual:@"preview"]) {
            NSUInteger round=[value[@"previewRound"] unsignedIntegerValue];
            UIViewController *shown=presenter.presentedViewController;
            if (round>[state[@"preview_round"] unsignedIntegerValue] && [shown isKindOfClass:UIDocumentPickerViewController.class]
                    && shown.viewIfLoaded.window && !shown.isBeingPresented && !shown.isBeingDismissed) {
                UIDocumentPickerViewController *picker=(UIDocumentPickerViewController *)shown;
                BOOL valid=picker.documentPickerMode==UIDocumentPickerModeImport && !picker.allowsMultipleSelection
                    && [picker.delegate respondsToSelector:@selector(documentPicker:didPickDocumentsAtURLs:)];
                if (!valid) { metrics[@"error_code"]=@"account_ui_preview_picker_contract_failed";finish();return; }
                state[@"preview_round"]=@(round);metrics[@"preview_picker_count"]=@(round);
                [picker.delegate documentPicker:picker didPickDocumentsAtURLs:@[[NSURL fileURLWithPath:state[@"source"]]]];
                [picker dismissViewControllerAnimated:NO completion:nil];
            }
        } else if (([phase isEqual:@"pending"] || [phase isEqual:@"original"]) && ![state[[phase stringByAppendingString:@"_requested"]] boolValue]) {
            state[[phase stringByAppendingString:@"_requested"]]=@YES;
            IdolyEmbeddedServerCommand(@"{\"id\":7410,\"action\":\"status\"}",^(NSString *reply){
                if ([state[@"finished"] boolValue]) return;
                NSDictionary *status=ProbeObject(reply)[@"result"],*runtime=status[@"runtime"],*selection=runtime[@"account_selection"];
                NSDictionary *config=state[@"config"];
                BOOL original=[phase isEqual:@"original"];
                BOOL matches=[runtime[@"running"] isEqual:@YES] && [runtime[@"profile"] isEqual:config[@"active"]]
                    && [selection[@"selected_for_next_start"] isEqual:original?config[@"active"]:config[@"source"]]
                    && [selection[@"restart_required"] isEqual:original?@NO:@YES];
                if (original) {
                    metrics[@"original_runtime_preserved"]=@((BOOL)matches);
                    metrics[@"listeners_survived"]=@((BOOL)(ProbePort(50051)&&ProbePort(8080)));
                } else metrics[@"next_selection_pending_only"]=@((BOOL)matches);
                if (!matches) { finish();return; }
                ProbeAccountResume(web,original?@"window.__idolyAccountProbe.originalObserved=true;":@"window.__idolyAccountProbe.pendingObserved=true;");
            });
        }
        if (![state[@"finished"] boolValue]) dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/10),dispatch_get_main_queue(),^{
            ProbeAccountPoll(weakWeb,weakPresenter,state,finish);
        });
    }];
}
static void ProbeAccountManagement(WKWebView *web,UIViewController *presenter,void (^completion)(NSDictionary *)) {
    if (probeRunIndex!=0) { completion(@{@"performed":@NO,@"reason":@"first-cold-run-only"});return; }
    NSTimeInterval started=NSProcessInfo.processInfo.systemUptime;
    NSURL *documents=[NSFileManager.defaultManager URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask].firstObject;
    NSDictionary *fixture=ProbeAccountSmallFile([[documents path] stringByAppendingPathComponent:@"probe-account-fixture.json"]);
    NSString *nonce=[fixture[@"nonce"] isKindOfClass:NSString.class]?fixture[@"nonce"]:nil;
    NSMutableDictionary *metrics=[@{@"performed":@YES,@"scope":@"stock-simulator",@"ui_trigger":@"dom-click",
        @"selection_trigger":@"delegate-callback",@"seed_fixture_used":@YES,@"gameplay_tested":@NO,
        @"timed_out":@NO,@"completed":@NO} mutableCopy];
    NSMutableDictionary *state=[@{@"finished":@NO,@"metrics":metrics,@"documents":documents.path ?: @""} mutableCopy];
    void (^finish)(void)=^{
        if ([state[@"finished"] boolValue]) return;
        state[@"finished"]=@YES;metrics[@"elapsed_seconds"]=@(MAX(0,NSProcessInfo.processInfo.systemUptime-started));
        completion(metrics.copy);
    };
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,120*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        if (![state[@"finished"] boolValue]) { metrics[@"timed_out"]=@YES;finish(); }
    });
    NSRegularExpression *hex=[NSRegularExpression regularExpressionWithPattern:@"^[0-9a-f]{32}$" options:0 error:NULL];
    if (!nonce || ![fixture[@"schema"] isEqual:@1] || [hex numberOfMatchesInString:nonce options:0 range:NSMakeRange(0,nonce.length)]!=1) {finish();return;}
    IdolyEmbeddedServerCommand(@"{\"id\":7400,\"action\":\"status\"}",^(NSString *reply){
        if ([state[@"finished"] boolValue]) return;
        NSDictionary *host=ProbeObject(reply)[@"result"],*runtime=host[@"runtime"];
        NSString *exports=host[@"paths"][@"exports"];
        if (![exports isKindOfClass:NSString.class] || !exports.isAbsolutePath) {finish();return;}
        state[@"exports"]=exports;
        NSString *active=runtime[@"profile"],*mode=[runtime[@"media_mode"] isEqual:@YES]?@"media":@"normal";
        if (![active isEqual:@"sandbox"] || ![runtime[@"running"] isEqual:@YES]) {finish();return;}
        NSDictionary *config=@{@"nonce":nonce,@"active":active,@"mode":mode,
            @"source":[@"probe-acct-" stringByAppendingFormat:@"%@-clone",[nonce substringToIndex:12]],
            @"target":[@"probe-acct-" stringByAppendingFormat:@"%@-import",[nonce substringToIndex:12]],
            @"deadline":@((long long)((NSDate.date.timeIntervalSince1970+115)*1000))};
        state[@"config"]=config;
        state[@"source"]=[documents.path stringByAppendingPathComponent:[@"probe-account-" stringByAppendingFormat:@"%@.zip",nonce]];
        NSString *script=[ProbeAccountScenario stringByAppendingFormat:@"(%@);",ProbeAccountJSON(config)];
        [web evaluateJavaScript:script completionHandler:^(id value,NSError *error){
            if ([state[@"finished"] boolValue]) return;
            if (error || ![value isEqual:@YES]) { finish();return; }
            ProbeAccountPoll(web,presenter,state,finish);
        }];
    });
}

static NSString *const ProbeOfficialPromptScript =
    @"(()=>{const h=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.idolyServer;"
    "if(!h||typeof h.postMessage!=='function'||typeof window.idolyServerReply!=='function')return false;"
    "const q=window.__idolyOfficialPromptProbe={request:null,empty_payload:false,cancelled:false,forbidden:false,enabled_before:false,click_dispatched:false};"
    "q.oldPost=h.postMessage;q.oldReply=window.idolyServerReply;"
    "q.post=function(r){if(r&&r.action==='official_inspect'){q.request=r.id;q.empty_payload=Object.keys(r).length===2&&Number.isInteger(r.id);"
    "if(Object.keys(r).some(k=>!['id','action'].includes(k)))q.forbidden=true;}"
    "if(r&&['official_fetch','official_apply'].includes(r.action))q.forbidden=true;return q.oldPost.apply(h,arguments);};"
    "q.reply=function(id,v){if(id===q.request&&v&&v.id===id)q.cancelled=v.ok===true&&!!v.result&&v.result.action==='official_inspect'&&v.result.cancelled===true;"
    "return q.oldReply.apply(this,arguments);};h.postMessage=q.post;window.idolyServerReply=q.reply;return true;})()";

static void ProbeOfficialSnapshot(void (^completion)(NSDictionary *)) {
    IdolyEmbeddedServerCommand(@"{\"id\":7500,\"action\":\"accounts_status\"}",^(NSString *reply){
        NSDictionary *account=ProbeObject(reply),*status=account[@"result"][@"status"];
        NSData *raw=[status isKindOfClass:NSDictionary.class]?[NSJSONSerialization dataWithJSONObject:status options:NSJSONWritingSortedKeys error:NULL]:nil;
        NSString *digest=raw?ProbeDataSHA(raw):nil;
        IdolyEmbeddedServerCommand(@"{\"id\":7501,\"action\":\"status\"}",^(NSString *hostReply){
            NSDictionary *host=ProbeObject(hostReply),*value=host[@"result"],*runtime=value[@"runtime"];
            NSDictionary *job=[value[@"official_import"] isKindOfClass:NSDictionary.class]?value[@"official_import"]:nil;
            BOOL absent=!job || job[@"job_id"]==(id)NSNull.null;
            BOOL valid=[account[@"ok"] isEqual:@YES]&&digest&&[host[@"ok"] isEqual:@YES]
                &&[runtime[@"running"] isEqual:@YES]&&[runtime[@"profile"] isKindOfClass:NSString.class];
            completion(@{@"valid":@((BOOL)valid),@"digest":digest?:@"",@"profile":runtime[@"profile"]?:@"",
                @"media":@((BOOL)[runtime[@"media_mode"] isEqual:@YES]),@"absent":@((BOOL)absent)});
        });
    });
}
static BOOL ProbeOfficialActivateCancel(id element,NSString *title,NSUInteger *remaining,NSHashTable *visited) {
    if (!element||!*remaining||[visited containsObject:element]) return NO;
    [visited addObject:element];--*remaining;
    if ([[element accessibilityLabel] isEqual:title]&&([element accessibilityTraits]&UIAccessibilityTraitButton)
            &&[element accessibilityActivate]) return YES;
    if ([element isKindOfClass:UIButton.class]&&[[(UIButton *)element titleForState:UIControlStateNormal] isEqual:title]) {
        [(UIButton *)element sendActionsForControlEvents:UIControlEventTouchUpInside];return YES;
    }
    // UIKit alerts may expose virtual action elements only through the public
    // container protocol; they need not appear in UIView.subviews or an array.
    if ([element respondsToSelector:@selector(accessibilityElementCount)]
            &&[element respondsToSelector:@selector(accessibilityElementAtIndex:)]) {
        NSInteger count=[element accessibilityElementCount];
        if (count!=NSNotFound&&count>0) for (NSInteger index=0;index<MIN(count,64)&&*remaining;++index)
            if (ProbeOfficialActivateCancel([element accessibilityElementAtIndex:index],title,remaining,visited)) return YES;
    }
    if ([element respondsToSelector:@selector(accessibilityElements)]) {
        id children=[element accessibilityElements];
        if ([children isKindOfClass:NSArray.class]) for (id child in [children subarrayWithRange:NSMakeRange(0,MIN([children count],64))])
            if (ProbeOfficialActivateCancel(child,title,remaining,visited)) return YES;
    }
    if ([element isKindOfClass:UIView.class]) for (UIView *child in [(UIView *)element subviews])
        if (ProbeOfficialActivateCancel(child,title,remaining,visited)) return YES;
    return NO;
}
static void ProbeOfficialPromptPoll(WKWebView *__weak weakWeb,UIViewController *__weak weakPresenter,
                                    NSMutableDictionary *state,void (^finish)(void)) {
    if ([state[@"finished"] boolValue]) return;
    WKWebView *web=weakWeb;UIViewController *presenter=weakPresenter;
    if (!web||!presenter) {finish();return;}
    NSMutableDictionary *metrics=state[@"metrics"];
    [web evaluateJavaScript:@"(()=>{const q=window.__idolyOfficialPromptProbe,b=document.getElementById('official-inspect');if(!q)return null;"
        "if(!q.request&&b&&!b.disabled){q.enabled_before=!b.disabled;b.click();q.click_dispatched=Number.isInteger(q.request);}return {button_found:!!b,enabled_before:q.enabled_before,click_dispatched:q.click_dispatched,empty_web_payload:q.empty_payload,web_reply_cancelled:q.cancelled,forbidden:q.forbidden};})()"
        completionHandler:^(id value,NSError *error){
        if ([state[@"finished"] boolValue]) return;
        if (error||![value isKindOfClass:NSDictionary.class]||[value[@"forbidden"] isEqual:@YES]) {finish();return;}
        for (NSString *key in @[@"button_found",@"enabled_before",@"click_dispatched",@"empty_web_payload",@"web_reply_cancelled"])
            metrics[key]=@((BOOL)[value[key] isEqual:@YES]);
        UIViewController *shown=presenter.presentedViewController;
        if (![state[@"cancel_requested"] boolValue]&&[shown isKindOfClass:UIAlertController.class]
                &&shown.viewIfLoaded.window&&!shown.isBeingPresented) {
            UIAlertController *prompt=(UIAlertController *)shown;state[@"prompt"]=prompt;
            metrics[@"prompt_presented"]=@YES;
            metrics[@"field_count_two"]=@((BOOL)(prompt.textFields.count==2));
            metrics[@"secure_password_field"]=@((BOOL)(prompt.textFields.count==2&&!prompt.textFields[0].secureTextEntry&&prompt.textFields[1].secureTextEntry));
            UIAlertAction *cancel=nil;NSUInteger platforms=0,cancels=0;
            for (UIAlertAction *action in prompt.actions) {
                if (action.style==UIAlertActionStyleCancel) {cancel=action;++cancels;}
                else if (action.style==UIAlertActionStyleDefault&&([action.title hasPrefix:@"iOS"]||[action.title hasPrefix:@"Android"])) ++platforms;
            }
            metrics[@"platform_actions_present"]=@((BOOL)(prompt.actions.count==3&&platforms==2));
            metrics[@"cancel_action_present"]=@((BOOL)(cancels==1));
            if (![metrics[@"secure_password_field"] isEqual:@YES]||![metrics[@"platform_actions_present"] isEqual:@YES]||cancels!=1) {finish();return;}
            prompt.textFields[0].text=@"ProbeNeverSubmit_ID";prompt.textFields[1].text=@"ProbeNeverSubmit_Pass";
            metrics[@"synthetic_inputs_set"]=@((BOOL)(prompt.textFields[0].text.length>0&&prompt.textFields[1].text.length>0));
            NSUInteger remaining=512;
            NSHashTable *visited=[NSHashTable hashTableWithOptions:NSPointerFunctionsObjectPointerPersonality|NSPointerFunctionsStrongMemory];
            BOOL activated=ProbeOfficialActivateCancel(prompt.view,cancel.title,&remaining,visited);
            // A public accessibility Escape on this inspected cancel-bearing
            // alert is Cancel, never the default action. Require the real Web
            // cancellation ACK, cleared fields and detached sheet afterwards.
            if (!activated&&!prompt.isBeingDismissed&&prompt.viewIfLoaded.window)
                activated=[prompt.view accessibilityPerformEscape];
            if (!activated&&!prompt.isBeingDismissed&&prompt.viewIfLoaded.window)
                activated=[prompt accessibilityPerformEscape];
            if (activated) {
                state[@"cancel_requested"]=@YES;metrics[@"cancel_action_activated"]=@YES;
            }
        }
        UIAlertController *prompt=state[@"prompt"];
        if ([state[@"cancel_requested"] boolValue]&&prompt&&!presenter.presentedViewController&&!prompt.viewIfLoaded.window&&!prompt.isBeingDismissed
                &&[metrics[@"web_reply_cancelled"] isEqual:@YES]&&![state[@"observing_after"] boolValue]) {
            state[@"observing_after"]=@YES;metrics[@"prompt_detached"]=@YES;
            metrics[@"fields_cleared"]=@((BOOL)(prompt.textFields.count==2&&!prompt.textFields[0].text.length&&!prompt.textFields[1].text.length));
            ProbeOfficialSnapshot(^(NSDictionary *after){
                if ([state[@"finished"] boolValue]) return;NSDictionary *before=state[@"before"];
                metrics[@"official_job_absent_after"]=after[@"absent"];
                metrics[@"account_data_unchanged"]=@((BOOL)([after[@"valid"] isEqual:@YES]&&[after[@"digest"] isEqual:before[@"digest"]]));
                metrics[@"runtime_identity_unchanged"]=@((BOOL)([after[@"valid"] isEqual:@YES]&&[after[@"profile"] isEqual:before[@"profile"]]&&[after[@"media"] isEqual:before[@"media"]]));
                metrics[@"completed"]=@YES;finish();
            });return;
        }
        if (![state[@"finished"] boolValue]) dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/10),dispatch_get_main_queue(),^{
            ProbeOfficialPromptPoll(weakWeb,weakPresenter,state,finish);
        });
    }];
}
static void ProbeOfficialPrompt(WKWebView *web,UIViewController *presenter,void (^completion)(NSDictionary *)) {
    if (probeRunIndex!=0) {completion(@{@"performed":@NO,@"reason":@"first-cold-run-only"});return;}
    NSTimeInterval started=NSProcessInfo.processInfo.systemUptime;
    NSMutableDictionary *metrics=[@{@"performed":@YES,@"scope":@"stock-simulator",@"ui_trigger":@"dom-click",
        @"cancel_trigger":@"accessibility-or-control-action",@"credential_submission_performed":@NO,@"timed_out":@NO,@"completed":@NO} mutableCopy];
    NSMutableDictionary *state=[@{@"finished":@NO,@"metrics":metrics} mutableCopy];
    void (^finish)(void)=^{
        if ([state[@"finished"] boolValue]) return;state[@"finished"]=@YES;
        metrics[@"elapsed_seconds"]=@(MAX(0,NSProcessInfo.processInfo.systemUptime-started));
        [web evaluateJavaScript:@"(()=>{const q=window.__idolyOfficialPromptProbe,h=window.webkit.messageHandlers.idolyServer;if(!q)return;"
            "if(h.postMessage===q.post)h.postMessage=q.oldPost;if(window.idolyServerReply===q.reply)window.idolyServerReply=q.oldReply;delete window.__idolyOfficialPromptProbe;})()" completionHandler:nil];
        completion(metrics.copy);
    };
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,30*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        if (![state[@"finished"] boolValue]) {metrics[@"timed_out"]=@YES;finish();}
    });
    ProbeOfficialSnapshot(^(NSDictionary *before){
        if ([state[@"finished"] boolValue]) return;state[@"before"]=before;metrics[@"official_job_absent_before"]=before[@"absent"];
        if (![before[@"valid"] isEqual:@YES]||![before[@"absent"] isEqual:@YES]) {finish();return;}
        [web evaluateJavaScript:ProbeOfficialPromptScript completionHandler:^(id value,NSError *error){
            if ([state[@"finished"] boolValue]) return;if(error||![value isEqual:@YES]){finish();return;}
            ProbeOfficialPromptPoll(web,presenter,state,finish);
        }];
    });
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

@interface UnityAppController : UIResponder <UIApplicationDelegate>
@property(nonatomic,strong) UIWindow *window;
- (void)initUnityWithApplication:(UIApplication *)application __attribute__((objc_method_family(none)));
@end
@interface UnityFramework : NSObject {
    unsigned _runCount;
}
@property(nonatomic,strong) UnityAppController *controller;
+ (instancetype)getInstance;
- (void)setDataBundleId:(const char *)identifier;
- (UITextField *)keyboardTextField;
- (void)runUIApplicationMainWithArgc:(int)argc argv:(char **)argv;
- (void)runEmbeddedWithArgc:(int)argc argv:(char **)argv appLaunchOpts:(NSDictionary *)options;
- (void)frameworkWarmup:(int)argc argv:(char **)argv;
- (id)appController;
- (unsigned)probeRunCount;
@end
@implementation UnityFramework
+ (instancetype)getInstance {
    static UnityFramework *instance; static dispatch_once_t once;
    dispatch_once(&once,^{instance=[UnityFramework new];}); return instance;
}
- (void)setDataBundleId:(const char *)identifier {
    probeBundleIdentifier=identifier ? [NSString stringWithUTF8String:identifier] : nil;
    NSCAssert([probeBundleIdentifier isEqual:@"local.idoly.client-data"],@"Unexpected data bundle");
}
- (UITextField *)keyboardTextField { ++probeKeyboardGetterCalls; return [KeyboardDelegate Instance].field; }
- (void)frameworkWarmup:(int)argc argv:(char **)argv {
    (void)argc;(void)argv; ++probeOriginalWarmupCalls; probeRuntimeStarted=YES;
    ProbeConsumeLanguageData();
}
- (void)runUIApplicationMainWithArgc:(int)argc argv:(char **)argv {
    ++probeOriginalRunMainCalls;
    [self frameworkWarmup:argc argv:argv];
    UIApplicationMain(argc,argv,nil,NSStringFromClass(UnityAppController.class));
}
- (void)runEmbeddedWithArgc:(int)argc argv:(char **)argv appLaunchOpts:(NSDictionary *)options {
    [self frameworkWarmup:argc argv:argv];
    self.controller=[UnityAppController new];
    [self.controller application:UIApplication.sharedApplication didFinishLaunchingWithOptions:options];
    if ([self.controller respondsToSelector:@selector(applicationWillEnterForeground:)])
        [self.controller applicationWillEnterForeground:UIApplication.sharedApplication];
    if ([self.controller respondsToSelector:@selector(applicationDidBecomeActive:)])
        [self.controller applicationDidBecomeActive:UIApplication.sharedApplication];
    ++_runCount;
}
- (id)appController { return self.controller; }
- (unsigned)probeRunCount { return _runCount; }
@end
static int ProbeUIKitMain(int argc,char **argv,NSString *principal,NSString *delegate) {
    ++probeUIKitMainCalls;
    return UIApplicationMain(argc,argv,principal,delegate);
}
static BOOL ProbePreRuntime(void) { return !probeRuntimeStarted && [UnityFramework getInstance].probeRunCount==0; }
static unsigned ProbeRunCount(id framework) { return [(UnityFramework *)framework probeRunCount]; }
static id ProbeAppController(id framework) { return [(UnityFramework *)framework appController]; }

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

@interface IDProbeCoordinator : NSObject
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
@property(nonatomic, strong) NSDictionary *settingsWebObservation;
@property(nonatomic, strong) WKWebsiteDataStore *launcherWebsiteDataStore;
@property(nonatomic, weak) WKWebView *launcherSettingsWeb;
@property(nonatomic) BOOL launcherStoreNonpersistent;
@property(nonatomic, strong) NSMutableDictionary *keyboardProbe;
@property(nonatomic, strong) NSDictionary *nativeHeaderProbe;
@property(nonatomic, strong) NSDictionary *diagnosticsCopyObservation;
@property(nonatomic, strong) NSDictionary *zipImportObservation;
@property(nonatomic, strong) NSDictionary *zipRoundTripObservation;
@property(nonatomic, strong) NSDictionary *accountManagementObservation;
@property(nonatomic, strong) NSDictionary *officialPromptObservation;
@property(nonatomic, strong) NSMutableDictionary *octoBudgetProbe;
@property(nonatomic) NSUInteger firstOctoQueuedSnapshotCount;
@property(nonatomic,strong) NSMutableArray *interfaceLanguageCycle;
@property(nonatomic,strong) NSDictionary *languageSave;
@property(nonatomic) BOOL interfaceChecked;
@property(nonatomic) BOOL interfaceInFlight;
@property(nonatomic) BOOL signalChecked;
@property(nonatomic) BOOL signalInFlight;
- (void)startWithApplication:(UIApplication *)application hostDelegate:(id)hostDelegate;
- (void)originalUnityInitialized:(UIApplication *)application controller:(UnityAppController *)controller;
- (void)probeLauncher:(NSDictionary *)status;
- (void)recordCheckpoint:(NSString *)stage;
- (void)failProbe:(NSString *)code;
- (BOOL)observeKeyboard:(NSString *)name phase:(NSUInteger)phase ready:(BOOL)ready calls:(NSUInteger)calls failure:(NSString *)code;
- (void)probeAfterOriginalReturnedOnMain:(BOOL)originalOnMain applicationMatches:(BOOL)argumentMatches;
- (BOOL)observeOctoBudgetBeforeOriginal;
- (BOOL)observeOctoBudgetFirstQueuedWork;
- (void)probeMenuAfterLaunch:(NSMutableDictionary *)report;
- (void)checkInterfaceWithButton:(UIButton *)button;
- (void)interfaceStep:(NSUInteger)step web:(WKWebView *)web button:(UIButton *)button;
- (void)saveNextLanguage:(WKWebView *)web completion:(void (^)(BOOL))completion;
- (void)observeMenuDismissal:(UINavigationController *)navigation report:(NSMutableDictionary *)report
                       menu:(NSMutableDictionary *)menu started:(NSTimeInterval)started observations:(NSUInteger)observations;
- (void)finishReport:(NSDictionary *)report;
@end

@implementation IDProbeCoordinator
- (void)failProbe:(NSString *)code {
    self.probeError = code;
    ProbeWrite(@"embedded-probe-status.json", @{@"schema":@1,
        @"original_called":@(self.originalCount), @"server_status":ProbeObject(IdolyEmbeddedServerStatusJSON()),
        @"probe_error":code, @"menu_close":self.menuCloseObservation ?: @{},
        @"settings_web":self.settingsWebObservation ?: @{},
        @"keyboard":self.keyboardProbe.copy ?: @{}, @"native_header":self.nativeHeaderProbe ?: @{},
        @"diagnostics_copy":self.diagnosticsCopyObservation ?: @{}, @"zip_import_picker":self.zipImportObservation ?: @{}, @"zip_roundtrip":self.zipRoundTripObservation ?: @{}, @"account_management":self.accountManagementObservation ?: @{}, @"official_prompt":self.officialPromptObservation ?: @{}, @"octo_budget_probe":self.octoBudgetProbe.copy ?: @{},
        @"unity_host_probe":probeHostProof.copy ?: @{},
        @"interface_language_cycle":self.interfaceLanguageCycle.copy ?: @[], @"language_save":self.languageSave ?: @{}});
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
        @"menu_close":self.menuCloseObservation ?: @{}, @"settings_web":self.settingsWebObservation ?: @{},
        @"keyboard":self.keyboardProbe.copy ?: @{},
        @"native_header":self.nativeHeaderProbe ?: @{}, @"diagnostics_copy":self.diagnosticsCopyObservation ?: @{}, @"zip_import_picker":self.zipImportObservation ?: @{}, @"zip_roundtrip":self.zipRoundTripObservation ?: @{}, @"account_management":self.accountManagementObservation ?: @{}, @"official_prompt":self.officialPromptObservation ?: @{},
        @"octo_budget":status[@"octo_budget"] ?: @{}, @"octo_budget_probe":self.octoBudgetProbe.copy ?: @{},
        @"unity_host":status[@"unity_host"] ?: @{}, @"unity_host_probe":probeHostProof.copy ?: @{},
        @"interface_language_cycle":self.interfaceLanguageCycle.copy ?: @[], @"language_save":self.languageSave ?: @{}});
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
- (void)startWithApplication:(UIApplication *)application hostDelegate:(id)hostDelegate {
    (void)application;
    self.octoBudgetProbe=[NSMutableDictionary dictionaryWithDictionary:@{@"apis_registered":@YES}];
    self.window=[(id<UIApplicationDelegate>)hostDelegate window];
    probePlaceholderWindow=self.window; probeHostDelegate=hostDelegate;
    probeHostProof[@"host_delegate_owned"]=@((BOOL)(UIApplication.sharedApplication.delegate==hostDelegate
        && [NSStringFromClass([hostDelegate class]) isEqual:@"IDUnityHostDelegate"]));
    self.launcherProbe=[NSMutableDictionary dictionaryWithDictionary:@{@"startup_evidence_version":@2}];
    self.keyboardProbe=[NSMutableDictionary dictionary];
    [self recordCheckpoint:@"host_ready"];
    [self recordCheckpoint:@"window_ready"];
    self.waitingTimer = [NSTimer scheduledTimerWithTimeInterval:0.25 repeats:YES block:^(NSTimer *timer) {
        (void)timer;
        NSDictionary *status = ProbeObject(IdolyEmbeddedServerStatusJSON());
        [self recordCheckpoint:[status[@"phase"] isEqual:@2] ? @"server_ready" : @"server_starting"];
        [self probeLauncher:status];
        ProbeWrite(@"embedded-probe-status.json", @{@"schema":@1,
            @"original_called":@(self.originalCount),
            @"server_status":status, @"probe_error":self.probeError ?: NSNull.null,
            @"settings_web":self.settingsWebObservation ?: @{}, @"keyboard":self.keyboardProbe.copy, @"native_header":self.nativeHeaderProbe ?: @{},
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
        if (![status[@"phase"] isEqual:@1] || ![status[@"captured"] isEqual:@1] || self.originalCount != 0
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
                    || ![native[@"phase"] isEqual:@1] || ![native[@"captured"] isEqual:@1]
                    || !NSThread.isMainThread) [self failProbe:@"early_status_correlation_failed"];
        });
        [self recordCheckpoint:@"premature_launch_checked"];
    });
}


- (void)checkInterfaceWithButton:(UIButton *)button {
    if (self.interfaceInFlight) return;
    self.interfaceInFlight=YES; self.interfaceLanguageCycle=[NSMutableArray array];
    WKWebView *web=ProbeFindSettingsWeb(ProbeButtonOwner(button).view);
    self.launcherSettingsWeb=web; self.launcherWebsiteDataStore=web.configuration.websiteDataStore;
    self.launcherStoreNonpersistent=self.launcherWebsiteDataStore && !self.launcherWebsiteDataStore.persistent;
    ProbeSettingsDOM(web,^(NSDictionary *metrics){
        self.settingsWebObservation=metrics;
        if (![metrics[@"ready"] isEqual:@YES]) { [self failProbe:@"language_interface_cycle_failed"]; return; }
        [self interfaceStep:0 web:web button:button];
    });
}
- (void)interfaceStep:(NSUInteger)step web:(WKWebView *)web button:(UIButton *)button {
    if (step==3) { self.interfaceChecked=YES; self.interfaceInFlight=NO;
        [self recordCheckpoint:@"interface_language_cycle_checked"]; return; }
    NSString *language=@[@"ja",@"en",@"ko"][step];
    NSString *setup=[ProbeReplyHook stringByAppendingFormat:
        @"window.__idolyProbeLauncherDocument=true;window.__idolyProbeInterfaceAck=null;(()=>{const s=document.getElementById('interface_language');"
         "if(!s)return false;s.value='%@';s.dispatchEvent(new Event('change',{bubbles:true}));return true;})()",language];
    [web evaluateJavaScript:setup completionHandler:^(id value,NSError *error){
        if(error || ![value isEqual:@YES]) { [self failProbe:@"language_interface_cycle_failed"]; return; }
        NSString *poll=[NSString stringWithFormat:
            @"(()=>{const a=window.__idolyProbeInterfaceAck,s=document.getElementById('language');"
             "return {ready:!!a&&a.language==='%@'&&document.documentElement.lang==='%@'&&!!s&&s.value==='%@',"
             "ack_id:a?a.id:0};})()",language,language,probeExpectedLanguage];
        BOOL (^chrome)(void)=^BOOL(void){
            UIView *view=ProbeButtonOwner(button).view;
            UILabel *title=(UILabel *)ProbeHeaderView(view,@"idoly.native-title");
            UILabel *status=(UILabel *)ProbeHeaderView(view,@"idoly.server-status");
            UIButton *server=(UIButton *)ProbeHeaderView(view,@"idoly.server-start");
            return [title isKindOfClass:UILabel.class] && [title.text isEqual:ProbeChromeTitle(language)]
                && [[button titleForState:UIControlStateNormal] isEqual:ProbeChromeStart(language)]
                && [status isKindOfClass:UILabel.class] && [status.text isEqual:ProbeChromeReady(language)]
                && [server isKindOfClass:UIButton.class]
                && [[server titleForState:UIControlStateNormal] isEqual:ProbeChromeReady(language)];
        };
        ProbePollLanguage(web,poll,NSProcessInfo.processInfo.systemUptime+10,chrome,^(NSDictionary *ack){
            if (![ack[@"ready"] isEqual:@YES]) { [self failProbe:@"language_interface_cycle_failed"]; return; }
            NSString *request=[NSString stringWithFormat:@"{\"id\":%lu,\"action\":\"status\"}",(unsigned long)(800+step)];
            IdolyEmbeddedServerCommand(request,^(NSString *reply){
                NSDictionary *status=ProbeObject(reply),*result=status[@"result"];
                BOOL unchanged=[status[@"ok"] isEqual:@YES] && [result[@"options"][@"language"] isEqual:probeExpectedLanguage];
                [self.interfaceLanguageCycle addObject:@{@"language":language,@"ack_id":ack[@"ack_id"] ?: @0,
                    @"acknowledged":@YES,@"dom_language_matches":@YES,@"native_title_matches":@YES,
                    @"native_game_button_matches":@YES,@"native_status_label_matches":@YES,
                    @"native_server_button_matches":@YES,@"game_select_unchanged":@YES,
                    @"persisted_game_language_unchanged":@(unchanged)}];
                if (!unchanged) { [self failProbe:@"language_interface_cycle_failed"]; return; }
                [self interfaceStep:step+1 web:web button:button];
            });
        });
    }];
}
- (void)saveNextLanguage:(WKWebView *)web completion:(void (^)(BOOL))completion {
    NSString *next=ProbeNextLanguage();
    void (^finish)(NSDictionary *)=^(NSDictionary *ack){
        BOOL saved=[ack[@"ready"] isEqual:@YES];
        NSString *attempted=[ack[@"attempted_language"] isEqual:@"en"] ? @"en" : next;
        self.languageSave=@{@"current_language":probeExpectedLanguage,@"next_language":attempted,
            @"request_id":ack[@"request_id"] ?: @0,@"ack_id":ack[@"ack_id"] ?: @0,
            @"request_action":ack[@"request_action"] ?: @"unknown",@"request_language":ack[@"request_language"] ?: @"unknown",
            @"request_observed":@([ack[@"request_observed"] isEqual:@YES]),@"ack_correlated":@([ack[@"ack_correlated"] isEqual:@YES]),
            @"acknowledged":@([ack[@"acknowledged"] isEqual:@YES]),
            @"persisted_language":ack[@"persisted_language"] ?: @"unknown",@"effective_language":ack[@"effective_language"] ?: @"unknown",
            @"save_trigger":@"change-autosave",@"feedback_source":@"options-save-feedback",
            @"feedback_state":ack[@"feedback_state"] ?: @"unknown",@"ack_language":ack[@"ack_language"] ?: @"unknown",
            @"ack_effective_language":ack[@"ack_effective_language"] ?: @"unknown",
            @"options_fields_reenabled":@([ack[@"options_fields_reenabled"] isEqual:@YES]),
            @"form_feedback_saved":@([ack[@"form_feedback_saved"] isEqual:@YES]),@"message_success":@([ack[@"form_feedback_saved"] isEqual:@YES]),
            @"server_status_received":@([ack[@"server_status_received"] isEqual:@YES]),
            @"server_language_matches":@([ack[@"server_language_matches"] isEqual:@YES]),
            @"server_effective_matches":@([ack[@"server_effective_matches"] isEqual:@YES]),@"timed_out":@([ack[@"timed_out"] isEqual:@YES])};
        if (saved) [self recordCheckpoint:@"language_saved"];
        completion(saved);
    };
    // The last return is already Korean. Make a real EN edit first so this
    // check cannot pass by resubmitting unchanged values or a stale ACK.
    if (probeRunIndex==4) ProbeAutoSaveLanguage(web,@"en",probeExpectedLanguage,^(NSDictionary *ack){
        if (![ack[@"ready"] isEqual:@YES]) {
            NSMutableDictionary *failed=[ack mutableCopy]; failed[@"attempted_language"]=@"en"; finish(failed); return;
        }
        ProbeAutoSaveLanguage(web,next,probeExpectedLanguage,finish);
    });
    else ProbeAutoSaveLanguage(web,next,probeExpectedLanguage,finish);
}
- (void)probeLauncher:(NSDictionary *)status {
    if (self.probeError || self.launchDispatched || self.reportScheduled) return;
    if (![status[@"phase"] isEqual:@2]) {
        if (self.readySince != 0) self.probeError = @"server_left_ready_before_launch";
        return;
    }
    if (!self.captureDispatched) {
        if (!self.earlyStatus) return;
        BOOL cold=ProbePreRuntime() && [UnityFramework getInstance].probeRunCount==0 && probeOriginalWarmupCalls==0
            && [UnityFramework getInstance].controller==nil;
        probeHostProof[@"cold_before_game_start"]=@(cold);
        probeHostProof[@"runtime_count_before_game_start"]=@([UnityFramework getInstance].probeRunCount);
        probeHostProof[@"warmup_count_before_game_start"]=@(probeOriginalWarmupCalls);
        if (![status[@"captured"] isEqual:@1] || ![status[@"attempts"] isEqual:@1] || self.originalCount || !cold) {
            [self failProbe:@"host_cold_start_failed"]; return;
        }
        self.launcherProbe[@"server_ready_before_runtime"]=@YES;
        self.launcherProbe[@"cold_original_called"]=@(self.originalCount);
        self.launcherProbe[@"cold_attempts"]=ProbeScalar(status,@"attempts");
        self.launcherProbe[@"host_capture_once"]=@YES;
        if (![self observeKeyboard:@"before_capture" phase:2 ready:NO calls:1 failure:@"keyboard_before_capture_failed"]) return;
        self.captureDispatched=YES;
        [self recordCheckpoint:@"host_entry_captured"];
        return;
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
    [self.launcherProbe addEntriesFromDictionary:@{@"ready_phase":@2, @"ready_captured":ProbeScalar(status,@"captured"),
        @"ready_original_called":@(self.originalCount), @"ready_launch_requested":@NO,
        @"ready_launch_prepared":@NO, @"ready_launcher_visible":@YES,
        @"ready_button_found":@YES, @"ready_button_enabled":@(item.enabled),
        @"ready_button_title":buttonTitle, @"ready_button_kind":@"UIButton", @"ready_observations":@(observations),
        @"ready_wait_seconds":@(now - self.readySince)}];
    // Observe the healthy server menu for five seconds without entering
    // Unity, including on both returns to previously prepared language data.
    if (now - self.readySince < 5.0) return;
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
    if (!self.interfaceChecked) { [self checkInterfaceWithButton:item]; return; }
    if (!self.signalChecked) {
        if (self.signalInFlight) return;
        self.signalInFlight=YES;
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0),^{
            NSDictionary *proof=ProbeSignalObservation();
            dispatch_async(dispatch_get_main_queue(),^{
                NSMutableDictionary *signals=[probeHostProof[@"sigpipe"] mutableCopy];
                signals[@"before_game_worker"]=proof; probeHostProof[@"sigpipe"]=signals;
                self.signalChecked=ProbeSignalValid(proof,NO); self.signalInFlight=NO;
                if (!self.signalChecked) { [self failProbe:@"sigpipe_before_game_failed"]; return; }
                [self recordCheckpoint:@"sigpipe_before_game_checked"];
            });
        });
        return;
    }
    BOOL healthy=[status[@"phase"] isEqual:@2] && [status[@"python_initialized"] isEqual:@YES]
        && status[@"error"]==NSNull.null && [status[@"attempts"] isEqual:@1];
    BOOL cold=ProbePreRuntime() && [UnityFramework getInstance].probeRunCount==0
        && probeOriginalWarmupCalls==0 && [UnityFramework getInstance].controller==nil;
    probeHostProof[@"prelaunch_server_healthy"]=@(healthy);
    probeHostProof[@"prelaunch_runtime_cold"]=@(cold);
    if (!healthy || !cold) { [self failProbe:@"host_cold_start_failed"]; return; }
    if (![self observeKeyboard:@"before_launch" phase:2 ready:NO calls:2 failure:@"keyboard_before_launch_failed"]) return;
    [self recordCheckpoint:@"keyboard_before_launch_checked"];
    self.launchDispatched = YES;
    WKWebView *web=ProbeFindSettingsWeb(item.window.rootViewController.view);
    if (!web) { [self failProbe:@"launch_settings_barrier_failed"]; return; }
    NSString *setup=@"(() => {const old=window.idolyServerFlushSettings;if(typeof old!=='function')return false;"
        "const q=window.__idolyProbeLaunchGate={calls:0,held:false,release:null};"
        "window.webkit.messageHandlers.idolyServer.postMessage({id:2000000000,action:'launch_settings_barrier',"
        "nonce:'00000000-0000-4000-8000-000000000000',ready:true});"
        "window.idolyServerFlushSettings=function(nonce){q.calls++;q.held=true;q.release=()=>{"
        "window.idolyServerFlushSettings=old;q.held=false;old(nonce);};};return true;})()";
    [web evaluateJavaScript:setup completionHandler:^(id value,NSError *error){
        if (error || ![value isEqual:@YES]) { [self failProbe:@"launch_settings_barrier_failed"]; return; }
        self.launcherProbe[@"button_dispatch_count"] = @1;
        [self recordCheckpoint:@"launch_action_requested"];
        BOOL dispatched = ProbeDispatchButton(item);
        self.launcherProbe[@"button_action_dispatched"] = @(dispatched);
        self.launcherProbe[@"button_control_event"] = @"touch-up-inside";
        [self recordCheckpoint:@"launch_action_dispatched"];
        if (!dispatched) { [self failProbe:@"ready_launch_action_not_dispatched"]; return; }
        NSString *heldScript=@"(() => {const q=window.__idolyProbeLaunchGate;return {ready:!!q&&q.calls===1&&q.held&&typeof q.release==='function'};})()";
        ProbePollLanguage(web,heldScript,NSProcessInfo.processInfo.systemUptime+5,nil,^(NSDictionary *held){
            NSDictionary *pending=ProbeObject(IdolyEmbeddedServerStatusJSON());
            BOOL stillCold=ProbePreRuntime() && self.originalCount==0 && [UnityFramework getInstance].probeRunCount==0
                && [pending[@"phase"] isEqual:@2] && [pending[@"launch_requested"] isEqual:@NO];
            self.launcherProbe[@"cold_while_settings_flush_held"]=@(stillCold);
            self.launcherProbe[@"game_button_disabled_during_flush"]=@((BOOL)(!item.enabled));
            self.launcherProbe[@"settings_flush_called_once"]=@([held[@"ready"] isEqual:@YES]);
            self.launcherProbe[@"unsolicited_settings_ack_ignored"]=@(stillCold);
            if (![held[@"ready"] isEqual:@YES] || !stillCold || item.enabled) { [self failProbe:@"launch_settings_barrier_failed"]; return; }
            self.launcherProbe[@"settings_flush_released_before_forward"]=@YES;
            [web evaluateJavaScript:@"window.__idolyProbeLaunchGate.release()" completionHandler:^(id released,NSError *releaseError){
                (void)released;
                if (releaseError) [self failProbe:@"launch_settings_barrier_failed"];
            }];
        });
    }];
}

// Exact Unity ABI: void return, instance receiver, selector, one object argument.
- (void)originalUnityInitialized:(UIApplication *)application controller:(UnityAppController *)controller {
    self.window=controller.window;
    ++self.originalCount;
    if (![self observeOctoBudgetBeforeOriginal]) return;
    self.launcherProbe[@"forwarded_after_button"] = @(self.launchDispatched);
    IdolyEmbeddedServerLaunchGame(); self.launcherProbe[@"duplicate_launch_called"] = @YES;
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
    probeHostProof[@"original_run_main_calls"]=@(probeOriginalRunMainCalls);
    probeHostProof[@"application_main_adapter_calls"]=@(probeUIKitMainCalls);
    BOOL distinct=self.window && self.window!=probePlaceholderWindow;
    BOOL key=self.window.isKeyWindow && !self.window.hidden;
    BOOL adopted=[(id<UIApplicationDelegate>)probeHostDelegate window]==self.window;
    probeHostProof[@"game_window_distinct"]=@(distinct); probeHostProof[@"game_window_key"]=@(key);
    probeHostProof[@"host_delegate_window_is_game"]=@(adopted);
    probeHostProof[@"placeholder_hidden"]=@((BOOL)probePlaceholderWindow.hidden);
    if (!distinct || !key || !adopted || !probePlaceholderWindow.hidden) { [self failProbe:@"unity_window_handoff_failed"]; return; }
    if (![probeHostProof[@"canaries_match"] isEqual:@YES]) { [self failProbe:@"language_canaries_mismatch"]; return; }
    if (![probeHostProof[@"cache_identity_recorded"] isEqual:@YES]
            || (probeRunIndex>=3 && ![probeHostProof[@"cache_files_same_identity"] isEqual:@YES])) {
        [self failProbe:@"language_cache_identity_failed"]; return;
    }
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
                        @"unity_host_probe":probeHostProof.copy,
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
    NSMutableDictionary *complete=[report mutableCopy];
    complete[@"unity_host_probe"]=probeHostProof.copy;
    complete[@"interface_language_cycle"]=self.interfaceLanguageCycle.copy ?: @[];
    complete[@"language_save"]=self.languageSave ?: @{};
    BOOL written = ProbeWrite(@"embedded-probe.json", complete);
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
            WKWebsiteDataStore *store=web.configuration.websiteDataStore;
            BOOL reused=self.launcherWebsiteDataStore && store==self.launcherWebsiteDataStore;
            BOOL nonpersistent=store && !store.persistent;
            BOOL newView=web && web!=self.launcherSettingsWeb;
            NSMutableDictionary *observed=[metrics mutableCopy];
            observed[@"data_store_reused"]=@(reused); observed[@"launcher_store_nonpersistent"]=@(self.launcherStoreNonpersistent);
            observed[@"menu_store_nonpersistent"]=@(nonpersistent); observed[@"web_view_recreated"]=@(newView);
            menu[@"web"] = observed; self.settingsWebObservation=observed;
            [self recordCheckpoint:@"settings_web_observed"];
            if (!reused || !self.launcherStoreNonpersistent || !nonpersistent || !newView
                    || ![metrics[@"launcher_document_marker_absent"] isEqual:@YES]) {
                [self failProbe:@"settings_web_readiness_or_layout_failed"]; return;
            }
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
                ProbeZIPImportPicker(web,navigation.topViewController,^(NSDictionary *zipMetrics) {
                self.zipImportObservation=zipMetrics; menu[@"zip_import_picker"]=zipMetrics;
                BOOL zipOK=[zipMetrics[@"timed_out"] isEqual:@NO] && [zipMetrics[@"passes"] count]==2
                    && [zipMetrics[@"grpc_connected_after_cancel"] isEqual:@YES]
                    && [zipMetrics[@"assets_connected_after_cancel"] isEqual:@YES];
                for (NSDictionary *pass in zipMetrics[@"passes"]) {
                    zipOK=zipOK && [pass[@"document_picker_mode"] isEqual:@(UIDocumentPickerModeImport)];
                    for (NSString *key in @[@"button_found",@"enabled_before",@"click_dispatched",@"button_disabled_while_pending",
                            @"picker_presented",@"single_selection",@"delegate_is_settings",@"cancel_delegate_invoked",
                            @"dismissed_programmatically",@"picker_detached",@"button_restored"])
                        zipOK=zipOK && [pass[key] isEqual:@YES];
                }
                if (!zipOK) { [self failProbe:@"settings_zip_import_picker_failed"]; return; }
                [self recordCheckpoint:@"settings_zip_import_cancelled"];
                ProbeZIPRoundTrip(web,navigation.topViewController,^(NSDictionary *roundtrip) {
                self.zipRoundTripObservation=roundtrip; menu[@"zip_roundtrip"]=roundtrip;
                BOOL roundtripOK=probeRunIndex!=0 && [roundtrip[@"performed"] isEqual:@NO];
                if (probeRunIndex==0) {
                    roundtripOK=[roundtrip[@"timed_out"] isEqual:@NO];
                    for (NSString *key in @[@"export_accepted",@"export_ready",@"export_archive_complete",@"wk_import_dispatched",
                            @"picker_presented",@"picker_import_mode",@"picker_single_selection",@"selection_delegate_invoked",
                            @"dismissed_programmatically",@"picker_detached",@"import_reply_accepted",@"native_copy_queued",
                            @"copy_bytes_match",@"owned_copy_found",@"copy_source_distinct",@"source_preserved",
                            @"source_copy_sha256_match",@"backend_ready",@"backend_success",@"dom_completed",@"button_restored",
                            @"upstream_requests_unchanged"]) roundtripOK=roundtripOK && [roundtrip[key] isEqual:@YES];
                }
                if (!roundtripOK) { [self failProbe:@"settings_zip_roundtrip_failed"]; return; }
                [self recordCheckpoint:@"settings_zip_roundtrip_checked"];
                ProbeAccountManagement(web,navigation.topViewController,^(NSDictionary *account){
                self.accountManagementObservation=account;menu[@"account_management"]=account;
                BOOL accountOK=probeRunIndex==0 ? ([account[@"completed"] isEqual:@YES] && [account[@"timed_out"] isEqual:@NO]) : [account[@"performed"] isEqual:@NO];
                if (!accountOK) { [self failProbe:@"settings_account_management_failed"];return; }
                [self recordCheckpoint:@"settings_account_management_checked"];
                ProbeOfficialPrompt(web,navigation.topViewController,^(NSDictionary *prompt){
                self.officialPromptObservation=prompt;menu[@"official_prompt"]=prompt;
                BOOL promptOK=probeRunIndex!=0&&[prompt[@"performed"] isEqual:@NO];
                if(probeRunIndex==0){
                    promptOK=[prompt[@"timed_out"] isEqual:@NO]&&[prompt[@"credential_submission_performed"] isEqual:@NO];
                    for(NSString *key in @[@"button_found",@"enabled_before",@"click_dispatched",@"empty_web_payload",@"prompt_presented",@"field_count_two",@"secure_password_field",@"platform_actions_present",@"cancel_action_present",@"synthetic_inputs_set",@"cancel_action_activated",@"fields_cleared",@"web_reply_cancelled",@"prompt_detached",@"official_job_absent_before",@"official_job_absent_after",@"account_data_unchanged",@"runtime_identity_unchanged",@"completed"])
                        promptOK=promptOK&&[prompt[key] isEqual:@YES];
                }
                if(!promptOK){[self failProbe:@"settings_official_prompt_failed"];return;}
                [self recordCheckpoint:@"settings_official_prompt_checked"];
                [self saveNextLanguage:web completion:^(BOOL saved){
                if (!saved) { [self failProbe:@"language_save_failed"]; return; }
                BOOL closed = ProbeDispatchButton(close);
                menu[@"return_action_dispatched"] = @(closed);
                menu[@"return_control_event"] = @"touch-up-inside";
                if (!closed) { [self failProbe:@"settings_return_action_failed"]; return; }
                [self recordCheckpoint:@"settings_return_requested"];
                [self observeMenuDismissal:navigation report:report menu:menu
                                  started:NSProcessInfo.processInfo.systemUptime observations:0];
                }];
                });
                });
                });
                });
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

@implementation UnityAppController
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)options; [self initUnityWithApplication:application]; return YES;
}
- (void)initUnityWithApplication:(UIApplication *)application {
    self.window=[[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *screen=[UIViewController new]; screen.view.backgroundColor=UIColor.systemBackgroundColor;
    self.window.rootViewController=screen; [self.window makeKeyAndVisible];
    [probeCoordinator originalUnityInitialized:application controller:self];
}
- (void)applicationWillEnterForeground:(UIApplication *)application { (void)application; }
- (void)applicationDidBecomeActive:(UIApplication *)application { (void)application; }
@end
static void ProbeBeforeHostReady(id application,id delegate) {
    probeCoordinator=[IDProbeCoordinator new];
    [probeCoordinator startWithApplication:application hostDelegate:delegate];
}
int main(int argc,char *argv[]) {
    @autoreleasepool {
        probeExpectedLanguage=@"ko"; BOOL explicitRun=NO;
        for (int index=1;index<argc;++index) {
            NSString *arg=[NSString stringWithUTF8String:argv[index]];
            if ([arg hasPrefix:@"--idoly-probe-language="]) probeExpectedLanguage=[arg substringFromIndex:@"--idoly-probe-language=".length];
            if ([arg hasPrefix:@"--idoly-probe-run-index="]) {
                NSString *number=[arg substringFromIndex:@"--idoly-probe-run-index=".length];
                if (number.length!=1 || [number characterAtIndex:0]<'0' || [number characterAtIndex:0]>'4') return 2;
                probeRunIndex=(NSUInteger)([number characterAtIndex:0]-'0'); explicitRun=YES;
            }
        }
        if (![@[@"ko",@"en",@"ja"] containsObject:probeExpectedLanguage]) return 2;
        if (!explicitRun) probeRunIndex=[ProbeRunLanguages() indexOfObject:probeExpectedLanguage];
        if (![ProbeRunLanguages()[probeRunIndex] isEqual:probeExpectedLanguage]) return 2;
        NSDictionary *entry=IDUnityHostInfo();
        probeHostProof=[NSMutableDictionary dictionaryWithDictionary:@{@"schema":@1,@"expected_language":probeExpectedLanguage,
            @"run_index":@(probeRunIndex),@"cache_return":@((BOOL)(probeRunIndex>=3)),
            @"constructor_installed_before_c_main":@((BOOL)[entry[@"installed"] isEqual:@YES])}];
        ProbeWrite(@"embedded-probe-checkpoint.json",@{@"schema":@1,@"stage":@"c_main_entered",
            @"unity_host_probe":probeHostProof.copy});
        NSDictionary *signalProof=ProbeSignalObservation();
        probeHostProof[@"sigpipe"]=@{@"before_server":signalProof};
        if (!ProbeSignalValid(signalProof,YES)) {
            ProbeWrite(@"embedded-probe-status.json",@{@"probe_error":@"sigpipe_before_server_failed",
                @"unity_host_probe":probeHostProof.copy}); return 2;
        }
        NSURL *source=[NSBundle.mainBundle.bundleURL URLByAppendingPathComponent:@"probe-language-canaries.json"];
        NSData *raw=[NSData dataWithContentsOfURL:source options:NSDataReadingMappedIfSafe error:nil];
        if (!raw || !raw.length || raw.length>65536) { ProbeWrite(@"embedded-probe-status.json",@{@"probe_error":@"language_canaries_mismatch"}); return 2; }
        probeCanaryIndex=[NSJSONSerialization JSONObjectWithData:raw options:0 error:nil];
        if (![probeCanaryIndex isKindOfClass:NSDictionary.class] || ![probeCanaryIndex[@"languages"] isKindOfClass:NSDictionary.class]) return 2;
        probeHostProof[@"canary_source_sha256"]=ProbeDataSHA(raw);
        if (![entry[@"installed"] isEqual:@YES]) { ProbeWrite(@"embedded-probe-status.json",@{@"probe_error":@"host_constructor_not_installed"}); return 2; }
        IDOctoBudgetFixtureReset(); IDOctoBudgetAPIs budget=IDOctoBudgetFixtureAPIs();
        if (!IDOctoBudgetRegisterSmokeAPIs(&budget)) { ProbeWrite(@"embedded-probe-status.json",@{@"probe_error":@"octo_budget_registration_failed"}); return 2; }
        IDUnityHostSmokeHooks hooks={ProbeUIKitMain,ProbePreRuntime,ProbeRunCount,ProbeCachedBundleRoot,ProbeAppController,ProbeBeforeHostReady};
        BOOL registered=IDUnityHostRegisterSmokeHooks(&hooks);
        probeHostProof[@"host_hooks_registered"]=@(registered);
        if (!registered) { ProbeWrite(@"embedded-probe-status.json",@{@"probe_error":@"host_hooks_registration_failed"}); return 2; }
        ProbeWrite(@"embedded-probe-checkpoint.json",@{@"schema":@1,@"stage":@"host_hooks_registered",
            @"unity_host_probe":probeHostProof.copy});
        [[UnityFramework getInstance] runUIApplicationMainWithArgc:argc argv:argv];
        return 0;
    }
}
