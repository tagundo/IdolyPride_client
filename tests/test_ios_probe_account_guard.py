"""Run the actual account-probe guard/projection with Apple's Foundation."""
from pathlib import Path
import platform
import shutil
import subprocess

import pytest


ROOT=Path(__file__).resolve().parents[1]


def test_account_probe_rejects_null_or_nonobject_status_and_projects_no_account_values(tmp_path):
    if platform.system()!="Darwin" or not shutil.which("xcrun"):
        pytest.skip("Actual Apple Foundation SDK required")
    main=(ROOT/"ios-unified/probe/main.m").read_text()
    guards=main.split("// BEGIN_ACCOUNT_STATUS_GUARD",1)[1].split("// END_ACCOUNT_STATUS_GUARD",1)[0]
    begin=main.index("static void ProbeAccountCheckpoint(")
    projection=main[begin:main.index("static void ProbeAccountPoll(",begin)]
    source=tmp_path/"probe-guard.m";output=tmp_path/"probe-guard"
    source.write_text(r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdio.h>
''' + guards + projection + r'''
static NSDictionary *Good(void) {
 return @{@"ok":@YES,@"result":@{@"runtime":@{@"running":@YES,@"profile":@"sandbox",@"media_mode":@YES},@"paths":@{@"exports":@"/owned/test/exports"}}};
}
static void Rejected(id value,NSString *expected) {
 NSString *failure=nil;assert(ProbeAccountStatusContext(value,&failure)==nil);assert([failure isEqual:expected]);
}
int main(void){@autoreleasepool{
 NSString *failure=nil;NSDictionary *context=ProbeAccountStatusContext(Good(),&failure);
 assert(context&&failure==nil&&[context[@"mode"]isEqual:@"media"]&&[context[@"profile"]isEqual:@"sandbox"]);
 Rejected(NSNull.null,@"account_ui_status_envelope_invalid");Rejected(@[],@"account_ui_status_envelope_invalid");
 for(id ok in @[@NO,@1,@"true",NSNull.null])Rejected(@{@"ok":ok,@"result":Good()[@"result"]},@"account_ui_status_reply_rejected");
 for(id bad in @[NSNull.null,@[],@"not-an-object",@17]) {
  Rejected(@{@"ok":@YES,@"result":bad},@"account_ui_status_result_invalid");
  Rejected(@{@"ok":@YES,@"result":@{@"runtime":bad,@"paths":@{}}},@"account_ui_status_runtime_invalid");
  Rejected(@{@"ok":@YES,@"result":@{@"runtime":Good()[@"result"][@"runtime"],@"paths":bad}},@"account_ui_status_paths_invalid");
 }
 NSMutableDictionary *result=[Good()[@"result"]mutableCopy],*runtime=[result[@"runtime"]mutableCopy];result[@"runtime"]=runtime;
 for(id bad in @[NSNull.null,@[],@42,@"relative/path"]) {result[@"paths"]=@{@"exports":bad};Rejected(@{@"ok":@YES,@"result":result},@"account_ui_status_exports_invalid");}
 result[@"paths"]=Good()[@"result"][@"paths"];
 for(id bad in @[NSNull.null,@[],@42,@""]) {runtime[@"profile"]=bad;Rejected(@{@"ok":@YES,@"result":result},@"account_ui_status_profile_invalid");}
 runtime[@"profile"]=@"sandbox";
 for(id bad in @[NSNull.null,@[],@42,@0,@1,@"false"]) {runtime[@"media_mode"]=bad;Rejected(@{@"ok":@YES,@"result":result},@"account_ui_status_mode_invalid");}
 runtime[@"media_mode"]=@NO;failure=nil;context=ProbeAccountStatusContext(@{@"ok":@YES,@"result":result},&failure);assert(context&&[context[@"mode"]isEqual:@"normal"]);
 for(id bad in @[NSNull.null,@1,@NO,@"true"]) {runtime[@"running"]=bad;Rejected(@{@"ok":@YES,@"result":result},@"account_ui_status_not_running");}
 __block NSDictionary *observed=nil;__block NSString *stage=nil;
 NSMutableDictionary *state=[@{@"started":@(NSProcessInfo.processInfo.systemUptime),@"observations":@3,
 @"metrics":@{@"error_code":@"account_ui_status_runtime_invalid",@"profile":@"PRIVATE_PROFILE_SENTINEL",@"nonce":@"PRIVATE_NONCE_SENTINEL"},
 @"documents":@"/PRIVATE_PATH_SENTINEL",@"config":@{@"profile":@"PRIVATE_STATE_SENTINEL"}}mutableCopy];
 state[@"checkpoint"]=[^(NSString*s,NSDictionary*p){stage=s;observed=p;}copy];
 ProbeAccountCheckpoint(state,@"settings_account_status_received",@"status_received",@"accounts_status");
 assert([stage isEqual:@"settings_account_status_received"]&&[observed[@"error_code"]isEqual:@"account_ui_status_runtime_invalid"]&&observed.count==6);
 NSString *json=[[NSString alloc]initWithData:[NSJSONSerialization dataWithJSONObject:observed options:0 error:NULL]encoding:NSUTF8StringEncoding];
 assert([json rangeOfString:@"PRIVATE_"].location==NSNotFound);
 state[@"metrics"]=@{@"error_code":@"account_ui_/PRIVATE_PATH_SENTINEL"};ProbeAccountCheckpoint(state,@"settings_account_management_finished",@"finished",@"none");assert(observed[@"error_code"]==nil);
 puts("PASS account probe status guard and private progress projection");
}return 0;}
''')
    compiler=subprocess.check_output(["xcrun","--sdk","macosx","--find","clang"],text=True,stderr=subprocess.STDOUT).strip()
    sdk=subprocess.check_output(["xcrun","--sdk","macosx","--show-sdk-path"],text=True,stderr=subprocess.STDOUT).strip()
    result=subprocess.run([compiler,"-isysroot",sdk,"-mmacosx-version-min=12.0","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror",str(source),"-framework","Foundation","-o",str(output)],capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
    result=subprocess.run([str(output)],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
    assert result.stdout.strip()=="PASS account probe status guard and private progress projection"
