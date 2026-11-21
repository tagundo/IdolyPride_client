"""Execute native Save callback ownership and completed-overlay actions.

These are narrow Foundation logic tests. They do not emulate UIKit or assert
that a real Files provider was presented; the actual UIKit SDK compile is a
separate required producer check.
"""
from pathlib import Path
import platform
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
UI=ROOT/"ios-unified/native/IdolyMP4UI.m"


def objc_method(text,signature):
    start=text.index(signature);opening=text.index("{",start);depth=1;at=opening+1
    while depth:
        depth += (text[at]=="{")-(text[at]=="}");at+=1
    return text[start:at]


def test_save_callbacks_and_completed_overlay_use_captured_output_ownership(tmp_path):
    if platform.system()!="Darwin" or not shutil.which("xcrun"):
        pytest.skip("Actual Apple Foundation SDK required")
    text=UI.read_text()
    owner=text[text.index("@interface IDMP4SaveDelegate"):text.index("static BOOL IDMP4PresenterAvailable")]
    action=objc_method(text,"- (void)buttonPressed {")
    can_close=objc_method(text,"BOOL IDMP4CanCloseSettings(void)")
    set_saving=objc_method(text,"static void IDMP4SetSaving(BOOL saving)")
    close_settings=objc_method((ROOT/"ios-unified/native/IdolySettings.m").read_text(),"- (void)closeSettings {")
    source,output=tmp_path/"save-logic.m",tmp_path/"save-logic"
    source.write_text(r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
// Only the callback protocols/types are declared here. No fake UIKit SDK is
// supplied and no platform presentation behavior is inferred from this test.
@protocol UIDocumentPickerDelegate @end
@protocol UIAdaptivePresentationControllerDelegate @end
@protocol UIPopoverPresentationControllerDelegate @end
@class UIDocumentPickerViewController,UIPresentationController,UIPopoverPresentationController;
static BOOL IDMP4FileSheetVisible;
NSString * const IDMP4SaveStateDidChangeNotification=@"IdolyMP4SaveStateDidChange";
''' + can_close + "\n" + set_saving + r'''
static unsigned retireCalls;static uint64_t retiredLease;
static void IdolyEmbeddedServerMP4EndSave(uint64_t token){++retireCalls;retiredLease=token;}
''' + owner + r'''
@interface TestPanel:NSObject
@property(nonatomic) unsigned removals;
- (void)removeFromSuperview;
@end
@implementation TestPanel
- (void)removeFromSuperview{++_removals;}
@end
@interface UIViewController:NSObject @end
@implementation UIViewController @end
@interface TestWindow:NSObject
@property(nonatomic,strong) UIViewController *rootViewController;
@end
@implementation TestWindow @end
@interface TestButton:NSObject
@property(nonatomic) BOOL enabled;
@end
@implementation TestButton @end
static UIViewController *IDMP4TopPresenter(UIViewController *p){return p;}
static NSString *savedOutput;static unsigned saves,cancels;static BOOL sheetPresented;
static void IDMP4Save(UIViewController*p,NSString*job,NSString*output,void(^done)(BOOL,NSString*)){
 assert(p&&!job);savedOutput=[output copy];++saves;done(sheetPresented,sheetPresented?nil:@"cancelled");
}
static void IdolyEmbeddedServerMP4Command(NSString*request,void(^done)(NSString*)){
 assert([request containsString:@"mp4_cancel"]);++cancels;done(@"{}");
}
@interface TestProgress:NSObject
@property(nonatomic,strong) NSTimer *timer;
@property(nonatomic,strong) TestPanel *panel;
@property(nonatomic,strong) TestWindow *gameWindow;
@property(nonatomic,strong) TestButton *button;
@property(nonatomic) BOOL queueMode,completed,terminal;
@property(nonatomic,copy) NSString *completedExportID;
- (void)buttonPressed;
@end
static TestProgress *IDMP4ActiveProgress;
@implementation TestProgress
''' + action + r'''
@end
@interface TestSettings:NSObject
@property(nonatomic) BOOL launcherMode;
@property(nonatomic) unsigned releases,dismissals;
- (void)releaseWeb;
- (void)dismissViewControllerAnimated:(BOOL)animated completion:(void(^)(void))completion;
- (void)closeSettings;
@end
@implementation TestSettings
- (void)releaseWeb{++_releases;}
- (void)dismissViewControllerAnimated:(BOOL)animated completion:(void(^)(void))completion{(void)animated;++_dismissals;if(completion)completion();}
''' + close_settings + r'''
@end
int main(void){@autoreleasepool{
 __block unsigned notifications=0;
 id observer=[NSNotificationCenter.defaultCenter addObserverForName:IDMP4SaveStateDidChangeNotification object:nil queue:nil usingBlock:^(NSNotification*note){(void)note;++notifications;}];
 TestSettings *settings=[TestSettings new];
 IDMP4SetSaving(YES);assert(!IDMP4CanCloseSettings());[settings closeSettings];assert(!settings.releases&&!settings.dismissals);
 IDMP4SetSaving(NO);assert(IDMP4CanCloseSettings());[settings closeSettings];assert(settings.releases==1&&settings.dismissals==1&&notifications==2);
 settings.launcherMode=YES;[settings closeSettings];assert(settings.dismissals==1);
 [NSNotificationCenter.defaultCenter removeObserver:observer];
 IDMP4SaveDelegate *choice=[IDMP4SaveDelegate new],*picker=[IDMP4SaveDelegate new],*newPicker=[IDMP4SaveDelegate new];
 choice.lease=1;picker.lease=1;newPicker.lease=2;
 IDMP4PickerDelegate=choice;IDMP4FileSheetVisible=YES;
 // Handoff replaces the owner while retaining exactly the same file lease.
 IDMP4PickerDelegate=picker;[choice presentationControllerDidDismiss:nil];
 assert(IDMP4PickerDelegate==picker&&IDMP4FileSheetVisible&&retireCalls==0);
 [picker documentPickerWasCancelled:nil];assert(!IDMP4PickerDelegate&&!IDMP4FileSheetVisible&&retireCalls==1&&retiredLease==1);
 IDMP4PickerDelegate=newPicker;IDMP4FileSheetVisible=YES;
 [picker documentPicker:nil didPickDocumentsAtURLs:@[]];assert(IDMP4PickerDelegate==newPicker&&IDMP4FileSheetVisible&&retireCalls==1);
 [newPicker documentPicker:nil didPickDocumentsAtURLs:@[]];assert(!IDMP4PickerDelegate&&!IDMP4FileSheetVisible&&retireCalls==2&&retiredLease==2);
 TestProgress*p=[TestProgress new];p.panel=[TestPanel new];p.button=[TestButton new];p.gameWindow=[TestWindow new];p.gameWindow.rootViewController=[UIViewController new];
 p.completed=YES;p.terminal=YES;p.completedExportID=@"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";IDMP4ActiveProgress=p;
 // Cancel, successful sheet admission, and repeated Save leave the completed
 // overlay available and keep its original output, even after native changed.
 for(unsigned i=0;i<3;++i){sheetPresented=i!=0;[p buttonPressed];assert(IDMP4ActiveProgress==p&&p.panel.removals==0&&[savedOutput isEqual:p.completedExportID]);}
 assert(saves==3&&cancels==0);
 p.completed=NO;p.terminal=NO;p.button.enabled=YES;[p buttonPressed];assert(cancels==1&&!p.button.enabled&&p.panel.removals==0);
 p.queueMode=YES;[p buttonPressed];assert(!IDMP4ActiveProgress&&p.panel.removals==1&&cancels==1);
 puts("PASS native save ownership and retained completed overlay");
 }return 0;}
''')
    compiler=subprocess.check_output(["xcrun","--sdk","macosx","--find","clang"],text=True).strip()
    sdk=subprocess.check_output(["xcrun","--sdk","macosx","--show-sdk-path"],text=True).strip()
    compiled=subprocess.run([compiler,"-isysroot",sdk,"-mmacosx-version-min=12.0","-fobjc-arc","-fblocks",
                             "-Wall","-Wextra","-Werror",str(source),"-framework","Foundation","-o",str(output)],
                            capture_output=True,text=True,timeout=60)
    assert compiled.returncode==0,"Save callback Foundation compile failed:\n"+compiled.stdout+compiled.stderr
    result=subprocess.run([str(output)],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
    assert result.stdout.strip()=="PASS native save ownership and retained completed overlay"
