// SPDX-License-Identifier: AGPL-3.0-or-later
#import "IdolyMP4UI.h"
#import "IdolyEmbeddedServer.h"
#import "MP4FinalizationPolicy.h"
#import <objc/runtime.h>

static NSString *IDMP4Language = @"system";
static BOOL IDMP4FileSheetVisible;
NSString * const IDMP4SaveStateDidChangeNotification=@"IdolyMP4SaveStateDidChange";
BOOL IDMP4CanCloseSettings(void) { return !IDMP4FileSheetVisible; }
static void IDMP4SetSaving(BOOL saving) {
    if(IDMP4FileSheetVisible==saving)return;
    IDMP4FileSheetVisible=saving;
    [NSNotificationCenter.defaultCenter postNotificationName:IDMP4SaveStateDidChangeNotification object:nil];
}
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
@property(nonatomic) uint64_t lease;
@end
static IDMP4SaveDelegate *IDMP4PickerDelegate;
@implementation IDMP4SaveDelegate
- (void)retire {
    if (IDMP4PickerDelegate == self) { IdolyEmbeddedServerMP4EndSave(_lease); IDMP4PickerDelegate = nil; IDMP4SetSaving(NO); }
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
static BOOL IDMP4PresenterAvailable(UIViewController *target) {
    return target.viewIfLoaded.window && !target.isBeingDismissed && !target.isBeingPresented
        && !target.navigationController.isBeingDismissed && !target.navigationController.isBeingPresented;
}
static void IDMP4AfterChoice(UIViewController *choice,UIViewController *target,
                            IDMP4SaveDelegate *owner,void (^present)(void)) {
    void (^ready)(void)=^{
        if(IDMP4PickerDelegate!=owner || !IDMP4FileSheetVisible || !IDMP4PresenterAvailable(target) || target.presentedViewController){[owner retire];return;}
        present();
    };
    // Dismiss only our choice, never its settings/game presenter. UIAlert's
    // action may already be dismissing it; join that actual transition instead
    // of racing another presentation or sleeping for an assumed animation.
    id<UIViewControllerTransitionCoordinator> transition=choice.transitionCoordinator;
    if(choice.isBeingDismissed && transition) {
        BOOL joined=[transition animateAlongsideTransition:nil completion:^(id<UIViewControllerTransitionCoordinatorContext> context){(void)context;dispatch_async(dispatch_get_main_queue(),ready);}];
        if(!joined)dispatch_async(dispatch_get_main_queue(),ready);
    } else if(choice.presentingViewController)[choice dismissViewControllerAnimated:YES completion:ready];
    else dispatch_async(dispatch_get_main_queue(),ready);
}
@interface IDMP4SaveLifetime : NSObject
@property(nonatomic,weak) IDMP4SaveDelegate *owner;
@end
@implementation IDMP4SaveLifetime
- (void)dealloc {
    IDMP4SaveDelegate *owner=_owner;
    dispatch_async(dispatch_get_main_queue(),^{[owner retire];});
}
@end
static void IDMP4OwnPresentation(UIViewController *controller,IDMP4SaveDelegate *owner) {
    static const char lifetimeKey;
    IDMP4SaveLifetime *lifetime=[IDMP4SaveLifetime new];lifetime.owner=owner;
    objc_setAssociatedObject(controller,&lifetimeKey,lifetime,OBJC_ASSOCIATION_RETAIN_NONATOMIC);
}
static void IDMP4PresentOwned(UIViewController *controller,UIViewController *target,IDMP4SaveDelegate *owner) {
    IDMP4OwnPresentation(controller,owner);
    [target presentViewController:controller animated:YES completion:^{
        if(!controller.presentingViewController || !controller.viewIfLoaded.window)[owner retire];
    }];
    // UIKit refuses an invalid presentation synchronously without necessarily
    // invoking its completion. Do not leave the source leased in that case.
    if(!controller.presentingViewController)[owner retire];
}
static void IDMP4Save(UIViewController *presenter, NSString *jobID,NSString *exportID, void (^completion)(BOOL,NSString *)) {
    if (IDMP4FileSheetVisible) { completion(NO,@"mp4_save_busy"); return; }
    if (!IDMP4PresenterAvailable(presenter)) { completion(NO,@"mp4_presenter_unavailable"); return; }
    IDMP4SetSaving(YES);
    void (^prepared)(NSURL *,NSString *,uint64_t)=^(NSURL *file, NSString *error,uint64_t lease) {
        UIViewController *target = IDMP4TopPresenter(presenter);
        if (!file || !IDMP4PresenterAvailable(target) || target.presentedViewController) {
            IdolyEmbeddedServerMP4EndSave(lease); IDMP4SetSaving(NO); completion(NO,error ?: @"mp4_presenter_unavailable"); return;
        }
        UIAlertController *choice = [UIAlertController alertControllerWithTitle:IDMP4Text(@"MP4 저장",@"MP4を保存",@"Save MP4")
            message:nil preferredStyle:UIAlertControllerStyleActionSheet];
        __weak UIAlertController *weakChoice=choice;
        IDMP4SaveDelegate *choiceOwner=[IDMP4SaveDelegate new];choiceOwner.lease=lease;IDMP4PickerDelegate=choiceOwner;
        [choice addAction:[UIAlertAction actionWithTitle:IDMP4Text(@"파일에 저장",@"ファイルに保存",@"Save to Files")
            style:UIAlertActionStyleDefault handler:^(UIAlertAction *action) {
                (void)action;
                UIDocumentPickerViewController *picker = [[UIDocumentPickerViewController alloc]
                    initWithURL:file inMode:UIDocumentPickerModeExportToService];
                IDMP4SaveDelegate *pickerOwner=[IDMP4SaveDelegate new];pickerOwner.lease=lease;IDMP4PickerDelegate=pickerOwner;picker.delegate=pickerOwner;
                picker.presentationController.delegate=pickerOwner;
                IDMP4AfterChoice(weakChoice,target,pickerOwner,^{ IDMP4PresentOwned(picker,target,pickerOwner); });
            }]];
        [choice addAction:[UIAlertAction actionWithTitle:IDMP4Text(@"공유",@"共有",@"Share")
            style:UIAlertActionStyleDefault handler:^(UIAlertAction *action) {
                (void)action;
                UIActivityViewController *sheet = [[UIActivityViewController alloc] initWithActivityItems:@[file] applicationActivities:nil];
                IDMP4SaveDelegate *sheetOwner=[IDMP4SaveDelegate new];sheetOwner.lease=lease;IDMP4PickerDelegate=sheetOwner;
                sheet.completionWithItemsHandler = ^(UIActivityType type, BOOL completed, NSArray *items, NSError *failure) {
                    (void)type; (void)completed; (void)items; (void)failure; [sheetOwner retire];
                };
                sheet.popoverPresentationController.sourceView = target.view;
                sheet.popoverPresentationController.sourceRect = CGRectMake(CGRectGetMidX(target.view.bounds),CGRectGetMaxY(target.view.bounds)-20,1,1);
                sheet.presentationController.delegate = IDMP4PickerDelegate;
                sheet.popoverPresentationController.delegate = IDMP4PickerDelegate;
                IDMP4AfterChoice(weakChoice,target,sheetOwner,^{ IDMP4PresentOwned(sheet,target,sheetOwner); });
            }]];
        [choice addAction:[UIAlertAction actionWithTitle:IDMP4Text(@"취소",@"キャンセル",@"Cancel")
            style:UIAlertActionStyleCancel handler:^(UIAlertAction *action) { (void)action; [choiceOwner retire]; }]];
        choice.presentationController.delegate = choiceOwner;
        choice.popoverPresentationController.sourceView = target.view;
        choice.popoverPresentationController.delegate = choiceOwner;
        choice.popoverPresentationController.sourceRect = CGRectMake(CGRectGetMidX(target.view.bounds),CGRectGetMaxY(target.view.bounds)-20,1,1);
        IDMP4OwnPresentation(choice,choiceOwner);
        __block BOOL replied=NO;
        void (^finish)(BOOL)=^(BOOL shown){if(replied)return;replied=YES;if(!shown)[choiceOwner retire];completion(shown,shown?nil:@"mp4_presenter_unavailable");};
        [target presentViewController:choice animated:YES completion:^{finish(choice.presentingViewController!=nil&&choice.viewIfLoaded.window!=nil);}];
        if(!choice.presentingViewController)finish(NO);
    };
    IdolyEmbeddedServerMP4BeginSave(jobID,exportID,prepared);
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
@property(nonatomic,copy) NSString *completedExportID;
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
        [_panel.topAnchor constraintEqualToAnchor:window.topAnchor],
        [_panel.bottomAnchor constraintEqualToAnchor:window.bottomAnchor],
        [_panel.leadingAnchor constraintEqualToAnchor:window.leadingAnchor],
        [_panel.trailingAnchor constraintEqualToAnchor:window.trailingAnchor],
        [stack.centerXAnchor constraintEqualToAnchor:safe.centerXAnchor],
        [stack.centerYAnchor constraintEqualToAnchor:safe.centerYAnchor],
        [stack.leadingAnchor constraintGreaterThanOrEqualToAnchor:safe.leadingAnchor constant:12*scale],
        [stack.trailingAnchor constraintLessThanOrEqualToAnchor:safe.trailingAnchor constant:-12*scale],
        [stack.widthAnchor constraintLessThanOrEqualToConstant:440*scale]]];
    NSLayoutConstraint *width = [stack.widthAnchor constraintEqualToConstant:360*scale]; width.priority = UILayoutPriorityDefaultHigh; width.active = YES;
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
        // The current job's own failure stays visible through its original
        // cleanup join; only an older job's terminal row yields to the next MV.
        NSString *cleanupStage = [status[@"cleanup_stage"] isKindOfClass:NSString.class] && ![status[@"cleanup_stage"] isEqual:@"none"] ? status[@"cleanup_stage"] : nil;
        BOOL ownsCurrentJob = cleanupStage != nil;
        if (owner.queueMode && !ownsCurrentJob && [status[@"export_id"] isKindOfClass:NSString.class] && [result[@"current_job_id"] isKindOfClass:NSString.class])
            for (NSDictionary *row in result[@"jobs"])
                if ([row isKindOfClass:NSDictionary.class] && [row[@"job_id"] isEqual:result[@"current_job_id"]])
                    ownsCurrentJob = [row[@"output_id"] isEqual:status[@"export_id"]] && [status[@"export_id"] length] > 0;
        NSString *sessionPhase = phase;
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
        if(completed&&!owner.queueMode&&[status[@"export_id"]isKindOfClass:NSString.class])owner.completedExportID=status[@"export_id"];
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
            NSString *preparationError=[result[@"error_code"]isKindOfClass:NSString.class]?result[@"error_code"]:nil;
            NSString *queuePhase=[result[@"phase"]isKindOfClass:NSString.class]?result[@"phase"]:@"";
            BOOL queueCleanup=preparationError.length&&![preparationError isEqual:@"none"]&&([queuePhase isEqual:@"draining_navigation"]||[queuePhase isEqual:@"restoring_selection"]);
            BOOL currentTerminal=!owner.terminal&&([sessionPhase isEqual:@"failed"]||[sessionPhase isEqual:@"cancelled"])&&ownsCurrentJob;
            BOOL sameFailure=[sessionPhase isEqual:@"failed"]&&preparationError.length&&![preparationError isEqual:@"none"]&&[preparationError isEqual:status[@"error_code"]];
            if(!owner.terminal&&(sameFailure||currentTerminal||queueCleanup)){
                NSString *failure=currentTerminal&&[status[@"error_code"]isKindOfClass:NSString.class]?status[@"error_code"]:preparationError;
                NSString *stage=cleanupStage?:(queuePhase.length?queuePhase:@"cleanup");
                unsigned long long seconds=[status[@"cleanup_wait_ms"]unsignedLongLongValue]/1000ULL;
                NSString *wait=[NSString stringWithFormat:@"%@ · %@ (%llus)",IDMP4Text(@"원본 장면 정리 대기 중",@"元のシーンの後処理を待っています",@"Waiting for the original scene cleanup"),stage,seconds];
                if(seconds>=60)wait=[wait stringByAppendingFormat:@"\n%@",IDMP4Text(@"계속 멈춰 있으면 앱을 완전히 종료한 뒤 다시 실행하세요.",@"止まったままの場合はアプリを完全に終了してから再起動してください。",@"If it stays stuck, fully close the app and start it again.")];
                owner.label.numberOfLines=6;
                owner.label.text=[NSString stringWithFormat:@"%@\n%@\n%@",[sessionPhase isEqual:@"cancelled"]&&currentTerminal?IDMP4Text(@"취소됨",@"キャンセル済み",@"Cancelled"):IDMP4Text(@"MP4 실패",@"MP4に失敗",@"MP4 failed"),failure?:@"export_failed",wait];
            }else if(!owner.terminal&&[phase isEqual:@"queued"]&&queuePhase.length)
                owner.label.text=[owner.label.text stringByAppendingFormat:@" (%@)",queuePhase];
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
        if (presenter) IDMP4Save(presenter, nil, _completedExportID, ^(BOOL presented,NSString *error) { (void)presented;(void)error; });
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
        NSString *exportID=[request[@"export_id"]isKindOfClass:NSString.class]?request[@"export_id"]:nil;
        NSCharacterSet *invalid = [[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"] invertedSet];
        BOOL queueJob = request.count == 3 && jobID.length == 32 && [jobID rangeOfCharacterFromSet:invalid].location == NSNotFound;
        BOOL catalogRecord=request.count==3&&exportID.length==32&&[exportID rangeOfCharacterFromSet:invalid].location==NSNotFound;
        if (!(request.count == 2 && !request[@"job_id"]&&!request[@"export_id"]) && !queueJob && !catalogRecord) { reply(IDMP4Encode(@{@"id":identifier,@"ok":@NO,@"error":@{@"code":@"invalid_request",@"message":@"invalid_request"}})); return; }
        IDMP4Save(presenter, jobID, exportID, ^(BOOL presented,NSString *error) {
            reply(IDMP4Encode(presented?@{@"id":identifier,@"ok":@YES,@"result":@{@"presented":@YES}}
                :@{@"id":identifier,@"ok":@NO,@"error":@{@"code":error ?: @"mp4_export_not_ready",@"message":error ?: @"mp4_export_not_ready"}}));
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
