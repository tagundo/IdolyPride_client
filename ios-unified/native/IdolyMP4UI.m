// SPDX-License-Identifier: AGPL-3.0-or-later
#import "IdolyMP4UI.h"
#import "IdolyEmbeddedServer.h"
#import "MP4FinalizationPolicy.h"

static NSString *IDMP4Language = @"system";
static BOOL IDMP4FileSheetVisible;
static IDMP4FinalizationPolicy IDMP4Finalization;
static void IDMP4EndFinalizationGeneration(uint64_t generation) {
    uintptr_t identifier = 0;
    if (IDMP4FinalizationEnd(&IDMP4Finalization,generation,&identifier))
        [UIApplication.sharedApplication endBackgroundTask:(UIBackgroundTaskIdentifier)identifier];
}
static void IDMP4EndFinalizationTask(void) { IDMP4EndFinalizationGeneration(0); }
static void IDMP4AllowFinalization(void) {
    // Only the encoder's already captured frames may finish here. This bounded
    // assertion never promises background Unity rendering or begins another MV.
    if (!IdolyEmbeddedServerMP4IsFinishing()) return;
    uint64_t generation = IDMP4FinalizationBegin(&IDMP4Finalization);
    if (!generation) return;
    UIBackgroundTaskIdentifier task = [UIApplication.sharedApplication beginBackgroundTaskWithName:@"Idoly MP4 finalization"
        expirationHandler:^{ IDMP4EndFinalizationGeneration(generation); }];
    BOOL valid = task != UIBackgroundTaskInvalid;
    if (!IDMP4FinalizationGrant(&IDMP4Finalization,generation,(uintptr_t)task,valid)) {
        if (valid) [UIApplication.sharedApplication endBackgroundTask:task];
        return;
    }
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 25 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        IDMP4EndFinalizationGeneration(generation);
    });
}
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
static void IDMP4Save(UIViewController *presenter, NSString *jobID, void (^completion)(BOOL)) {
    if (IDMP4FileSheetVisible || !presenter.viewIfLoaded.window) { completion(NO); return; }
    IDMP4FileSheetVisible = YES;
    IdolyEmbeddedServerMP4ExportJob(jobID, ^(NSURL *file, NSString *error) {
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
@property(nonatomic,strong) UIButton *pauseButton;
@property(nonatomic,strong) NSTimer *timer;
@property(nonatomic,weak) UIWindow *gameWindow;
@property(nonatomic) BOOL polling;
@property(nonatomic) BOOL terminal;
@property(nonatomic) BOOL completed;
@property(nonatomic) BOOL paused;
@property(nonatomic) BOOL pausePending;
@property(nonatomic) BOOL queueMode;
- (void)show:(UIWindow *)window;
- (void)tick;
- (void)buttonPressed;
- (void)pausePressed;
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
    _pauseButton = [UIButton buttonWithType:UIButtonTypeSystem];
    [_pauseButton setTitle:IDMP4Text(@"일시 정지",@"一時停止",@"Pause") forState:UIControlStateNormal];
    [_pauseButton addTarget:self action:@selector(pausePressed) forControlEvents:UIControlEventTouchUpInside];
    _pauseButton.titleLabel.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleHeadline]
        scaledFontForFont:[UIFont systemFontOfSize:17*scale weight:UIFontWeightSemibold]];
    _pauseButton.titleLabel.adjustsFontForContentSizeCategory = YES;
    [_pauseButton.heightAnchor constraintGreaterThanOrEqualToConstant:44*scale].active = YES;
    _button = [UIButton buttonWithType:UIButtonTypeSystem];
    [_button setTitle:IDMP4Text(@"취소",@"キャンセル",@"Cancel") forState:UIControlStateNormal];
    [_button addTarget:self action:@selector(buttonPressed) forControlEvents:UIControlEventTouchUpInside];
    _button.titleLabel.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleHeadline]
        scaledFontForFont:[UIFont systemFontOfSize:17*scale weight:UIFontWeightSemibold]];
    _button.titleLabel.adjustsFontForContentSizeCategory = YES;
    [_button.heightAnchor constraintGreaterThanOrEqualToConstant:44*scale].active = YES;
    UIStackView *controls = [[UIStackView alloc] initWithArrangedSubviews:@[_pauseButton,_button]];
    controls.axis = UILayoutConstraintAxisHorizontal; controls.distribution = UIStackViewDistributionFillEqually;
    controls.spacing = 12*scale;
    UIStackView *stack = [[UIStackView alloc] initWithArrangedSubviews:@[_label,_progress,controls]];
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
    NSString *request = _queueMode ? @"{\"id\":1,\"action\":\"mp4_queue_status\"}" : @"{\"id\":1,\"action\":\"mp4_status\"}";
    IdolyEmbeddedServerMP4Command(request, ^(NSString *reply) {
        IDMP4Progress *owner = weakSelf; if (!owner) return; owner.polling = NO;
        NSDictionary *envelope = IDMP4Decode(reply);
        NSDictionary *result = [envelope[@"result"] isKindOfClass:NSDictionary.class] ? envelope[@"result"] : @{};
        NSDictionary *status = owner.queueMode && [result[@"session"] isKindOfClass:NSDictionary.class] ? result[@"session"] : result;
        NSString *phase = status[@"phase"];
        NSUInteger done = 0, remaining = 0, failures = 0;
        if (owner.queueMode) {
            for (NSDictionary *row in result[@"jobs"]) {
                if ([row[@"state"] isEqual:@"completed"]) ++done;
                if ([@[@"pending",@"running",@"paused"] containsObject:row[@"state"]]) ++remaining;
                if ([@[@"failed",@"interrupted"] containsObject:row[@"state"]]) ++failures;
            }
            BOOL running = [result[@"running"] isEqual:@YES], paused = [result[@"paused"] isEqual:@YES];
            BOOL terminal = !running && !paused && ![result[@"command_pending"] isEqual:@YES] && remaining == 0;
            if (![envelope[@"ok"] isEqual:@YES] || ![result[@"available"] isEqual:@YES]) phase = @"failed";
            else if (terminal) phase = failures ? @"failed" : done ? @"completed" : @"cancelled";
            else if (paused) phase = @"paused";
            else if (!running || [@[@"idle",@"completed",@"cancelled",@"failed"] containsObject:phase]) phase = @"queued";
        }
        owner.paused = [phase isEqual:@"paused"] || [phase isEqual:@"pausing"] || [status[@"pause_requested"] isEqual:@YES];
        BOOL completed = [phase isEqual:@"completed"], failed = [phase isEqual:@"failed"], cancelled = [phase isEqual:@"cancelled"];
        owner.completed = completed; owner.terminal = completed || failed || cancelled;
        NSString *text = completed ? IDMP4Text(@"MP4 완료",@"MP4完了",@"MP4 complete")
            : failed ? IDMP4Text(@"MP4 실패",@"MP4に失敗",@"MP4 failed")
            : cancelled ? IDMP4Text(@"취소됨",@"キャンセル済み",@"Cancelled")
            : [phase isEqual:@"paused"] ? ([status[@"pause_reason"] isEqual:@"user_paused"]
                ? IDMP4Text(@"내보내기 일시 정지",@"書き出しを一時停止中",@"Export paused")
                : IDMP4Text(@"앱으로 돌아오면 계속합니다",@"アプリに戻ると再開します",@"Resumes when you return to the app"))
            : [phase isEqual:@"pausing"] ? IDMP4Text(@"안전하게 일시 정지 중",@"安全に一時停止しています",@"Pausing safely")
            : [phase isEqual:@"preparing_audio"] ? IDMP4Text(@"음원 준비 중",@"音源を準備中",@"Preparing soundtrack")
            : [phase isEqual:@"finishing"] ? IDMP4Text(@"MP4 마무리 중",@"MP4を仕上げ中",@"Finalizing MP4")
            : [phase isEqual:@"cancelling"] ? IDMP4Text(@"취소 중",@"キャンセル中",@"Cancelling")
            : [phase isEqual:@"queued"] ? IDMP4Text(@"다음 MV 준비 중",@"次のMVを準備中",@"Preparing the next MV")
            : IDMP4Text(@"MP4 렌더링",@"MP4レンダリング",@"Rendering MP4");
        unsigned long long frames = [status[@"frames"] unsignedLongLongValue], total = [status[@"total_frames"] unsignedLongLongValue];
        owner.label.text = total ? [NSString stringWithFormat:@"%@ · %llu / %llu\n%@ × %@",text,frames,total,status[@"width"] ?: @0,status[@"height"] ?: @0] : text;
        if (owner.queueMode) {
            owner.label.numberOfLines = 3;
            owner.label.text = [owner.label.text stringByAppendingFormat:@"\n%@ · %lu / %lu MV",IDMP4Text(@"작업 목록",@"処理リスト",@"Queue"),(unsigned long)done,(unsigned long)[result[@"jobs"] count]];
            [owner.button setTitle:owner.terminal ? IDMP4Text(@"닫기",@"閉じる",@"Close") : IDMP4Text(@"숨기기",@"非表示",@"Hide") forState:UIControlStateNormal];
        }
        owner.progress.progress = total ? (float)MIN(1.0,(double)frames/(double)total) : 0;
        owner.pauseButton.hidden = owner.terminal;
        owner.pauseButton.enabled = !owner.pausePending && (owner.paused || [phase isEqual:@"preparing_audio"] || [phase isEqual:@"rendering"] || (owner.queueMode && [phase isEqual:@"queued"]));
        [owner.pauseButton setTitle:owner.paused ? IDMP4Text(@"계속",@"再開",@"Resume")
            : IDMP4Text(@"일시 정지",@"一時停止",@"Pause") forState:UIControlStateNormal];
        if (owner.terminal) {
            IDMP4EndFinalizationTask();
            [owner.timer invalidate]; owner.timer = nil;
            owner.button.enabled = YES;
            [owner.button setTitle:completed && !owner.queueMode ? IDMP4Text(@"저장·공유",@"保存・共有",@"Save / Share") : IDMP4Text(@"닫기",@"閉じる",@"Close") forState:UIControlStateNormal];
            NSString *errorCode = owner.queueMode ? result[@"error_code"] : status[@"error_code"];
            if (failed && [errorCode isKindOfClass:NSString.class]) owner.label.text = [text stringByAppendingFormat:@"\n%@",errorCode];
        }
    });
}
- (void)pausePressed {
    if (_terminal || _pausePending) return;
    _pausePending = YES; _pauseButton.enabled = NO;
    NSString *action = _queueMode ? (_paused ? @"mp4_queue_resume" : @"mp4_queue_pause") : (_paused ? @"mp4_resume" : @"mp4_pause");
    NSString *request = IDMP4Encode(@{@"id":@1,@"action":action});
    __weak IDMP4Progress *weakSelf = self;
    IdolyEmbeddedServerMP4Command(request, ^(NSString *reply) {
        (void)reply; IDMP4Progress *owner = weakSelf;
        if (!owner) return; owner.pausePending = NO; [owner tick];
    });
}
- (void)buttonPressed {
    if (_queueMode) {
        // Hiding this progress view does not cancel pending jobs. Per-job
        // cancellation and saved outputs remain in the server queue panel.
        [_timer invalidate]; _timer = nil; [_panel removeFromSuperview]; IDMP4ActiveProgress = nil;
    } else if (_completed) {
        UIViewController *presenter = IDMP4TopPresenter(_gameWindow.rootViewController);
        if (presenter) IDMP4Save(presenter, nil, ^(BOOL presented) {
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
        [NSNotificationCenter.defaultCenter addObserverForName:UIApplicationWillResignActiveNotification
            object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *notification) {
                (void)notification; IdolyEmbeddedServerMP4SetLifecycleActive(NO);
            }];
        [NSNotificationCenter.defaultCenter addObserverForName:UIApplicationDidEnterBackgroundNotification
            object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *notification) {
                (void)notification;
                IdolyEmbeddedServerMP4SetLifecycleActive(NO); IDMP4AllowFinalization();
            }];
        [NSNotificationCenter.defaultCenter addObserverForName:UIApplicationDidBecomeActiveNotification
            object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *notification) {
                (void)notification; IDMP4EndFinalizationTask(); IdolyEmbeddedServerMP4SetLifecycleActive(YES);
                [IDMP4ActiveProgress tick];
            }];
    });
}
void IDMP4HandleRequest(NSDictionary *request, UIViewController *presenter, UIWindow *window, void (^reply)(NSString *)) {
    NSNumber *identifier = request[@"id"];
    if ([request[@"action"] isEqual:@"mp4_save"]) {
        NSString *jobID = [request[@"job_id"] isKindOfClass:NSString.class] ? request[@"job_id"] : nil;
        NSCharacterSet *invalid = [[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"] invertedSet];
        BOOL queueJob = request.count == 3 && jobID.length == 32 && [jobID rangeOfCharacterFromSet:invalid].location == NSNotFound;
        if (!(request.count == 2 && !request[@"job_id"]) && !queueJob) { reply(IDMP4Encode(@{@"id":identifier,@"ok":@NO,@"error":@{@"code":@"invalid_request",@"message":@"invalid_request"}})); return; }
        IDMP4Save(presenter, jobID, ^(BOOL presented) {
            reply(IDMP4Encode(@{@"id":identifier,@"ok":@(presented),@"result":@{@"presented":@(presented)}}));
        }); return;
    }
    IdolyEmbeddedServerMP4Command(IDMP4Encode(request), ^(NSString *response) {
        if ([@[@"mp4_start",@"mp4_queue_run",@"mp4_queue_resume"] containsObject:request[@"action"]]
                && [IDMP4Decode(response)[@"ok"] isEqual:@YES] && window) {
            IDMP4Progress *progress = [IDMP4Progress new]; progress.queueMode = ![request[@"action"] isEqual:@"mp4_start"]; [progress show:window];
        }
        reply(response);
    });
}
