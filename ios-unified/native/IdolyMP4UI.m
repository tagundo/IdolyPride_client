// SPDX-License-Identifier: AGPL-3.0-or-later
#import "IdolyMP4UI.h"
#import "IdolyEmbeddedServer.h"

static NSString *IDMP4Language = @"system";
static BOOL IDMP4FileSheetVisible;
static NSString *IDMP4Text(NSString *ko, NSString *ja, NSString *en) {
    NSString *language = [IDMP4Language isEqual:@"system"] ? NSLocale.preferredLanguages.firstObject.lowercaseString : IDMP4Language;
    return [language hasPrefix:@"ko"] ? ko : [language hasPrefix:@"ja"] ? ja : en;
}
void IDMP4SetInterfaceLanguage(NSString *language) { IDMP4Language = [language copy]; }
static NSDictionary *IDMP4Decode(NSString *reply) {
    NSData *bytes = [reply dataUsingEncoding:NSUTF8StringEncoding];
    id value = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL] : nil;
    return [value isKindOfClass:NSDictionary.class] ? value : @{};
}
static NSString *IDMP4Encode(id object) {
    NSData *bytes = [NSJSONSerialization dataWithJSONObject:object options:0 error:NULL];
    return bytes ? [[NSString alloc] initWithData:bytes encoding:NSUTF8StringEncoding] : @"{}";
}
static UIViewController *IDMP4TopPresenter(UIViewController *root) {
    while (root.presentedViewController && !root.presentedViewController.isBeingDismissed) root = root.presentedViewController;
    return root;
}
@interface IDMP4SaveDelegate : NSObject <UIDocumentPickerDelegate, UIAdaptivePresentationControllerDelegate, UIPopoverPresentationControllerDelegate>
@end
static IDMP4SaveDelegate *IDMP4PickerDelegate;
@implementation IDMP4SaveDelegate
- (void)retire {
    if (IDMP4PickerDelegate == self) { IDMP4FileSheetVisible = NO; IDMP4PickerDelegate = nil; }
}
- (void)documentPickerWasCancelled:(UIDocumentPickerViewController *)controller {
    (void)controller; [self retire];
}
- (void)documentPicker:(UIDocumentPickerViewController *)controller didPickDocumentsAtURLs:(NSArray<NSURL *> *)urls {
    (void)controller; (void)urls; [self retire];
}
- (void)presentationControllerDidDismiss:(UIPresentationController *)presentationController {
    (void)presentationController; [self retire];
}
- (void)popoverPresentationControllerDidDismissPopover:(UIPopoverPresentationController *)popover {
    (void)popover; [self retire];
}
@end
static void IDMP4Save(UIViewController *presenter, void (^completion)(BOOL)) {
    if (IDMP4FileSheetVisible || !presenter.viewIfLoaded.window) { completion(NO); return; }
    IDMP4FileSheetVisible = YES;
    IdolyEmbeddedServerMP4Export(^(NSURL *file, NSString *error) {
        (void)error;
        UIViewController *target = IDMP4TopPresenter(presenter);
        if (!file || !target.viewIfLoaded.window || target.presentedViewController) {
            IDMP4FileSheetVisible = NO; completion(NO); return;
        }
        UIAlertController *choice = [UIAlertController alertControllerWithTitle:IDMP4Text(@"MP4 저장",@"MP4を保存",@"Save MP4")
            message:nil preferredStyle:UIAlertControllerStyleActionSheet];
        [choice addAction:[UIAlertAction actionWithTitle:IDMP4Text(@"파일에 저장",@"ファイルに保存",@"Save to Files")
            style:UIAlertActionStyleDefault handler:^(UIAlertAction *action) {
                (void)action;
                UIDocumentPickerViewController *picker = [[UIDocumentPickerViewController alloc]
                    initWithURL:file inMode:UIDocumentPickerModeExportToService];
                IDMP4PickerDelegate = [IDMP4SaveDelegate new]; picker.delegate = IDMP4PickerDelegate;
                picker.presentationController.delegate = IDMP4PickerDelegate;
                [target dismissViewControllerAnimated:YES completion:^{ [target presentViewController:picker animated:YES completion:nil]; }];
            }]];
        [choice addAction:[UIAlertAction actionWithTitle:IDMP4Text(@"공유",@"共有",@"Share")
            style:UIAlertActionStyleDefault handler:^(UIAlertAction *action) {
                (void)action;
                UIActivityViewController *sheet = [[UIActivityViewController alloc] initWithActivityItems:@[file] applicationActivities:nil];
                sheet.completionWithItemsHandler = ^(UIActivityType type, BOOL completed, NSArray *items, NSError *failure) {
                    (void)type; (void)completed; (void)items; (void)failure; IDMP4FileSheetVisible = NO;
                    IDMP4PickerDelegate = nil;
                };
                sheet.popoverPresentationController.sourceView = target.view;
                sheet.popoverPresentationController.sourceRect = CGRectMake(CGRectGetMidX(target.view.bounds),CGRectGetMaxY(target.view.bounds)-20,1,1);
                sheet.presentationController.delegate = IDMP4PickerDelegate;
                sheet.popoverPresentationController.delegate = IDMP4PickerDelegate;
                [target dismissViewControllerAnimated:YES completion:^{ [target presentViewController:sheet animated:YES completion:nil]; }];
            }]];
        [choice addAction:[UIAlertAction actionWithTitle:IDMP4Text(@"취소",@"キャンセル",@"Cancel")
            style:UIAlertActionStyleCancel handler:^(UIAlertAction *action) { (void)action; IDMP4FileSheetVisible = NO; IDMP4PickerDelegate = nil; }]];
        IDMP4PickerDelegate = [IDMP4SaveDelegate new];
        choice.presentationController.delegate = IDMP4PickerDelegate;
        choice.popoverPresentationController.sourceView = target.view;
        choice.popoverPresentationController.delegate = IDMP4PickerDelegate;
        choice.popoverPresentationController.sourceRect = CGRectMake(CGRectGetMidX(target.view.bounds),CGRectGetMaxY(target.view.bounds)-20,1,1);
        [target presentViewController:choice animated:YES completion:nil]; completion(YES);
    });
}

@interface IDMP4Progress : NSObject
@property(nonatomic,strong) UIView *panel;
@property(nonatomic,strong) UILabel *label;
@property(nonatomic,strong) UIProgressView *progress;
@property(nonatomic,strong) UIButton *button;
@property(nonatomic,strong) NSTimer *timer;
@property(nonatomic,weak) UIWindow *gameWindow;
@property(nonatomic) BOOL polling;
@property(nonatomic) BOOL terminal;
@property(nonatomic) BOOL completed;
- (void)show:(UIWindow *)window;
- (void)tick;
- (void)buttonPressed;
@end
static IDMP4Progress *IDMP4ActiveProgress;
@implementation IDMP4Progress
- (void)show:(UIWindow *)window {
    [IDMP4ActiveProgress.timer invalidate]; [IDMP4ActiveProgress.panel removeFromSuperview];
    IDMP4ActiveProgress = self; self.gameWindow = window;
    // The same virtual-coordinate scale as the server header remains readable
    // when PlayCover runs a high-resolution Unity window.
    CGFloat scale = MIN(64.0,MAX(16.0,MAX(window.bounds.size.width,window.bounds.size.height)*0.0105))/16.0;
    _panel = [UIView new]; _panel.translatesAutoresizingMaskIntoConstraints = NO;
    _panel.backgroundColor = UIColor.secondarySystemBackgroundColor;
    _panel.layer.cornerRadius = 12*scale; _panel.layer.shadowOpacity = 0.2f; _panel.layer.shadowRadius = 6*scale;
    _panel.accessibilityIdentifier = @"idoly.mp4-progress";
    _label = [UILabel new]; _label.numberOfLines = 2;
    _label.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleSubheadline]
        scaledFontForFont:[UIFont systemFontOfSize:15*scale]];
    _label.adjustsFontForContentSizeCategory = YES;
    _label.text = IDMP4Text(@"MP4 준비 중…",@"MP4を準備中…",@"Preparing MP4…");
    _progress = [UIProgressView new];
    _progress.transform = CGAffineTransformMakeScale(1,scale);
    _button = [UIButton buttonWithType:UIButtonTypeSystem];
    [_button setTitle:IDMP4Text(@"취소",@"キャンセル",@"Cancel") forState:UIControlStateNormal];
    [_button addTarget:self action:@selector(buttonPressed) forControlEvents:UIControlEventTouchUpInside];
    _button.titleLabel.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleHeadline]
        scaledFontForFont:[UIFont systemFontOfSize:17*scale weight:UIFontWeightSemibold]];
    _button.titleLabel.adjustsFontForContentSizeCategory = YES;
    [_button.heightAnchor constraintGreaterThanOrEqualToConstant:44*scale].active = YES;
    UIStackView *stack = [[UIStackView alloc] initWithArrangedSubviews:@[_label,_progress,_button]];
    stack.translatesAutoresizingMaskIntoConstraints = NO; stack.axis = UILayoutConstraintAxisVertical; stack.spacing = 8*scale;
    [_panel addSubview:stack]; [window addSubview:_panel];
    UILayoutGuide *safe = window.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [_panel.topAnchor constraintEqualToAnchor:safe.topAnchor constant:12*scale],
        [_panel.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-12*scale],
        [_panel.leadingAnchor constraintGreaterThanOrEqualToAnchor:safe.leadingAnchor constant:12*scale],
        [_panel.widthAnchor constraintLessThanOrEqualToConstant:440*scale],
        [stack.topAnchor constraintEqualToAnchor:_panel.topAnchor constant:12*scale],
        [stack.bottomAnchor constraintEqualToAnchor:_panel.bottomAnchor constant:-8*scale],
        [stack.leadingAnchor constraintEqualToAnchor:_panel.leadingAnchor constant:12*scale],
        [stack.trailingAnchor constraintEqualToAnchor:_panel.trailingAnchor constant:-12*scale]]];
    NSLayoutConstraint *width = [_panel.widthAnchor constraintEqualToConstant:360*scale]; width.priority = UILayoutPriorityDefaultHigh; width.active = YES;
    __weak IDMP4Progress *weakSelf = self;
    _timer = [NSTimer scheduledTimerWithTimeInterval:0.25 repeats:YES block:^(NSTimer *timer) { (void)timer; [weakSelf tick]; }];
    [self tick];
}
- (void)tick {
    if (_polling || _terminal) return; _polling = YES;
    __weak IDMP4Progress *weakSelf = self;
    IdolyEmbeddedServerMP4Command(@"{\"id\":1,\"action\":\"mp4_status\"}", ^(NSString *reply) {
        IDMP4Progress *owner = weakSelf; if (!owner) return; owner.polling = NO;
        NSDictionary *envelope = IDMP4Decode(reply);
        NSDictionary *status = [envelope[@"result"] isKindOfClass:NSDictionary.class] ? envelope[@"result"] : @{};
        NSString *phase = status[@"phase"];
        BOOL completed = [phase isEqual:@"completed"], failed = [phase isEqual:@"failed"], cancelled = [phase isEqual:@"cancelled"];
        owner.completed = completed; owner.terminal = completed || failed || cancelled;
        NSString *text = completed ? IDMP4Text(@"MP4 완료",@"MP4完了",@"MP4 complete")
            : failed ? IDMP4Text(@"MP4 실패",@"MP4に失敗",@"MP4 failed")
            : cancelled ? IDMP4Text(@"취소됨",@"キャンセル済み",@"Cancelled")
            : [phase isEqual:@"preparing_audio"] ? IDMP4Text(@"음원 준비 중",@"音源を準備中",@"Preparing soundtrack")
            : [phase isEqual:@"finishing"] ? IDMP4Text(@"MP4 마무리 중",@"MP4を仕上げ中",@"Finalizing MP4")
            : [phase isEqual:@"cancelling"] ? IDMP4Text(@"취소 중",@"キャンセル中",@"Cancelling")
            : IDMP4Text(@"MP4 렌더링",@"MP4レンダリング",@"Rendering MP4");
        unsigned long long frames = [status[@"frames"] unsignedLongLongValue], total = [status[@"total_frames"] unsignedLongLongValue];
        owner.label.text = total ? [NSString stringWithFormat:@"%@ · %llu / %llu\n%@ × %@",text,frames,total,status[@"width"] ?: @0,status[@"height"] ?: @0] : text;
        owner.progress.progress = total ? (float)MIN(1.0,(double)frames/(double)total) : 0;
        if (owner.terminal) {
            [owner.timer invalidate]; owner.timer = nil;
            owner.button.enabled = YES;
            [owner.button setTitle:completed ? IDMP4Text(@"저장·공유",@"保存・共有",@"Save / Share") : IDMP4Text(@"닫기",@"閉じる",@"Close") forState:UIControlStateNormal];
            if (failed && [status[@"error_code"] isKindOfClass:NSString.class])
                owner.label.text = [text stringByAppendingFormat:@"\n%@",status[@"error_code"]];
        }
    });
}
- (void)buttonPressed {
    if (_completed) {
        UIViewController *presenter = IDMP4TopPresenter(_gameWindow.rootViewController);
        if (presenter) IDMP4Save(presenter, ^(BOOL presented) {
            if (presented) { [self.panel removeFromSuperview]; IDMP4ActiveProgress = nil; }
        });
    } else if (_terminal) {
        [_panel removeFromSuperview]; IDMP4ActiveProgress = nil;
    } else {
        IdolyEmbeddedServerMP4Command(@"{\"id\":1,\"action\":\"mp4_cancel\"}", ^(NSString *reply) { (void)reply; });
        _button.enabled = NO;
    }
}
@end
void IDMP4InstallLifecycle(void) {
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        [NSNotificationCenter.defaultCenter addObserverForName:UIApplicationDidEnterBackgroundNotification
            object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *notification) {
                (void)notification;
                IdolyEmbeddedServerMP4Command(@"{\"id\":1,\"action\":\"mp4_cancel\"}", ^(NSString *reply) { (void)reply; });
            }];
    });
}
void IDMP4HandleRequest(NSDictionary *request, UIViewController *presenter, UIWindow *window, void (^reply)(NSString *)) {
    NSNumber *identifier = request[@"id"];
    if ([request[@"action"] isEqual:@"mp4_save"]) {
        if (request.count != 2) { reply(IDMP4Encode(@{@"id":identifier,@"ok":@NO,@"error":@{@"code":@"invalid_request",@"message":@"invalid_request"}})); return; }
        IDMP4Save(presenter, ^(BOOL presented) {
            reply(IDMP4Encode(@{@"id":identifier,@"ok":@(presented),@"result":@{@"presented":@(presented)}}));
        }); return;
    }
    IdolyEmbeddedServerMP4Command(IDMP4Encode(request), ^(NSString *response) {
        if ([request[@"action"] isEqual:@"mp4_start"] && [IDMP4Decode(response)[@"ok"] isEqual:@YES] && window) {
            IDMP4Progress *progress = [IDMP4Progress new]; [progress show:window];
        }
        reply(response);
    });
}
