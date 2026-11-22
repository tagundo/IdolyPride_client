"""Bounded shipping iOS diagnostics policy and actual Foundation sanitizer.

Foundation execution requires Apple's SDK; portable tests execute the shipping
byte policy on Linux too. Neither test claims UIKit, device or MP4 rendering.
"""
from pathlib import Path
import platform
import shutil
import subprocess

import pytest

from test_ios_unified_web import run_js

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "ios-unified/native/IdolyEmbeddedServer.m"


def test_shipping_diagnostic_code_policy(tmp_path):
    cc = shutil.which("clang") or shutil.which("cc")
    if not cc:
        pytest.skip("C compiler required")
    policy = HOST.read_text().split("// BEGIN_IDMP4_DIAGNOSTIC_POLICY", 1)[1].split("// END_IDMP4_DIAGNOSTIC_POLICY", 1)[0]
    source, binary = tmp_path / "policy.c", tmp_path / "policy"
    source.write_text("#include <stdbool.h>\n#include <stddef.h>\n#include <assert.h>\n#include <string.h>\n" + policy + r'''
int main(void){
 assert(IDMP4DiagnosticCodeBytes(NULL,0));assert(!IDMP4DiagnosticCodeBytes(NULL,1));
 const char *bad[]={"/private/token","a b","https://secret","a\\b","a\nb","a\rb","a\tb","MV 재생","\"token\""};
 for(size_t i=0;i<sizeof bad/sizeof *bad;++i)assert(!IDMP4DiagnosticCodeBytes((const unsigned char*)bad[i],strlen(bad[i])));
 unsigned char bytes[97];memset(bytes,'a',sizeof bytes);assert(IDMP4DiagnosticCodeBytes(bytes,95));assert(!IDMP4DiagnosticCodeBytes(bytes,96));
 bytes[1]=0;assert(!IDMP4DiagnosticCodeBytes(bytes,2));bytes[1]=0xff;assert(!IDMP4DiagnosticCodeBytes(bytes,2));
 const char *good="native_scene_control_unbound";assert(IDMP4DiagnosticCodeBytes((const unsigned char*)good,strlen(good)));
 return 0;
}
''')
    subprocess.run([cc,"-std=c11","-Wall","-Wextra","-Werror","-fsanitize=address,undefined",str(source),"-o",str(binary)],check=True,capture_output=True,text=True)
    subprocess.run([str(binary)],check=True,capture_output=True,text=True)


def test_diagnostic_copy_includes_current_and_previous_mp4_failure():
    run_js(r'''
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers),ready=status();
ready.native={schema:1,mp4:{phase:'idle',ready:false,diagnostics_available:true,
 export_trace:{schema:1,current_stage:'source_bootstrap',last_error:'native_scene_control_unbound',events:[{sequence:1,stage:'source_bootstrap',code:'native_scene_control_unbound',frame:0,tick:0}],modules:{native_scene_control:false}},
 diagnostic_history:{last_failure:{phase:'failed',export_trace:{schema:1,current_stage:'source_capture',last_error:'video_coordinator_unbound',events:[],modules:{}}},host_events:[{stage:'mp4_save',code:'mp4_export_not_ready'}]}}};
env.respond(env.posted[0],ready);await flush();
const text=env.elements.get('diagnostics').textContent;
for(const code of ['native_scene_control_unbound','video_coordinator_unbound','mp4_export_not_ready','export_trace'])assert.ok(text.includes(code));
assert.ok(Buffer.byteLength(text,'utf8')<=32768);
env.elements.get('diagnostics-copy').fire('click');const copy=env.posted.at(-1);assert.equal(copy.action,'diagnostics_copy');assert.equal(copy.text,text);
env.respond(copy,{copied:true});await flush();app.dispose();
''')


def test_actual_foundation_diagnostics_and_relaunch(tmp_path):
    if platform.system() != "Darwin" or not shutil.which("xcrun"):
        pytest.skip("Actual Apple Foundation SDK required")
    host=HOST.read_text()
    section=host.split("// BEGIN_IDMP4_DIAGNOSTIC_POLICY",1)[1].split("// END_IDMP4_DIAGNOSTIC_SANITIZER",1)[0]
    source,binary=tmp_path/"diagnostics.m",tmp_path/"diagnostics-host"
    source.write_text(r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <dlfcn.h>
#include <stdio.h>
static id nativeTrace;static BOOL missingDiagnostics;static int diagnosticSizeMode;
static NSString *nativePhase=@"failed";
static size_t statusCopy(char*p,size_t cap){assert(cap==8192);NSData*d=[[NSString stringWithFormat:@"{\"phase\":\"%@\",\"readiness_error\":\"native_scene_control_unbound\",\"frames\":5,\"path\":\"/private/secret\"}",nativePhase]dataUsingEncoding:NSUTF8StringEncoding];memcpy(p,d.bytes,d.length);return d.length;}
static size_t diagnosticCopy(char*p,size_t cap){assert(cap==32768);if(diagnosticSizeMode)return cap;NSData*d=[NSJSONSerialization dataWithJSONObject:@{@"export_trace":nativeTrace?:@{}} options:0 error:NULL];assert(d.length<cap);memcpy(p,d.bytes,d.length);return d.length;}
static int ready(void){return 0;}
static void *testDlsym(void*scope,const char*name){(void)scope;if(!strcmp(name,"IDMP4SessionStatus"))return(void*)statusCopy;if(!strcmp(name,"IDMP4SessionReady"))return(void*)ready;if(!strcmp(name,"IDMP4SessionDiagnostics")&&!missingDiagnostics)return(void*)diagnosticCopy;return NULL;}
#define dlsym testDlsym
''' + section + r'''
int main(int argc,char**argv){@autoreleasepool{
 assert(argc==2);NSString *mode=[NSString stringWithUTF8String:argv[1]];
 if([mode isEqual:@"read"]){NSDictionary*saved=mp4DiagnosticSaved();assert([saved[@"last_failure"][@"export_trace"][@"last_error"]isEqual:@"native_scene_control_unbound"]);assert([saved[@"host_events"]lastObject][@"code"]!=nil);[NSUserDefaults.standardUserDefaults removeObjectForKey:mp4DiagnosticDefaultsKey];return 0;}
 [NSUserDefaults.standardUserDefaults removeObjectForKey:mp4DiagnosticDefaultsKey];
 NSMutableArray*events=[NSMutableArray new];for(unsigned i=1;i<=20;++i)[events addObject:@{@"sequence":@(i),@"stage":@"source_bootstrap",@"code":@"waiting",@"frame":@5,@"tick":@8,@"path":@"/private/secret"}];
 nativeTrace=@{@"schema":@1,@"current_stage":@"source_bootstrap",@"last_error":@"native_scene_control_unbound",@"events":events,@"modules":@{@"native_scene_control":@NO,@"scene_parts":@YES,@"game_api":@1,@"secret":@YES},@"auth":@"secret"};
 NSDictionary*s=mp4DiagnosticSnapshot(),*trace=s[@"export_trace"];
 assert([s[@"diagnostics_available"]isEqual:@YES]&&[s[@"frames"]isEqual:@5]);assert([trace[@"events"]count]==16);assert([trace[@"events"]firstObject][@"sequence"]&&[[trace[@"events"]firstObject][@"sequence"]isEqual:@5]);
 assert([trace[@"modules"]count]==2&&[trace[@"modules"][@"native_scene_control"]isEqual:@NO]);
 NSString*json=[[NSString alloc]initWithData:[NSJSONSerialization dataWithJSONObject:s options:0 error:NULL] encoding:NSUTF8StringEncoding];assert(![json containsString:@"/private/secret"]&&!trace[@"auth"]);
 for(id bad in @[@YES,@-1,@1.5,@9007199254740992.0,@"1",NSNull.null])assert(!mp4DiagnosticInteger(bad));
 assert(!mp4SanitizeExportTrace(@{@"schema":@YES}));assert(!mp4SanitizeExportTrace(@{@"schema":@2}));
 for(id bad in @[@"/private/secret",@"Bearer secret",@"한글",@"a\nb",@42,NSNull.null])assert(!mp4DiagnosticCode(bad));
 NSString*nul=[[NSString alloc]initWithBytes:"a\0b" length:3 encoding:NSASCIIStringEncoding];assert(!mp4DiagnosticCode(nul));
 NSDictionary*dirty=@{@"schema":@1,@"current_stage":@"/private/secret",@"last_error":@"safe_code",@"events":@[@{@"sequence":@YES,@"stage":@"x",@"code":@"x",@"frame":@0,@"tick":@0},@{@"sequence":@2,@"stage":@"x",@"code":@"x",@"frame":@-1,@"tick":@0}],@"modules":@{@"game_api":@YES}};
 NSDictionary*clean=mp4SanitizeExportTrace(dirty);assert(!clean[@"current_stage"]&&[clean[@"events"]count]==0&&[clean[@"modules"]count]==1);
 missingDiagnostics=YES;assert([mp4SessionStatus()[@"diagnostics_available"]isEqual:@NO]);missingDiagnostics=NO;diagnosticSizeMode=1;assert([mp4SessionStatus()[@"diagnostics_available"]isEqual:@NO]);diagnosticSizeMode=0;
 for(unsigned i=0;i<20;++i)mp4DiagnosticHostEvent(@"mp4_save",@"mp4_export_not_ready");mp4DiagnosticHostEvent(@"/private/secret",@"unsafe");assert([mp4DiagnosticSaved()[@"host_events"]count]==8);
 (void)mp4SessionStatus();assert([NSUserDefaults.standardUserDefaults synchronize]);return 0;
}}
''')
    cc=subprocess.check_output(["xcrun","--sdk","macosx","--find","clang"],text=True).strip()
    sdk=subprocess.check_output(["xcrun","--sdk","macosx","--show-sdk-path"],text=True).strip()
    subprocess.run([cc,"-isysroot",sdk,"-mmacosx-version-min=12.0","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror",str(source),"-framework","Foundation","-o",str(binary)],check=True,capture_output=True,text=True,timeout=60)
    for mode in ["write","read"]:
        result=subprocess.run([str(binary),mode],capture_output=True,text=True,timeout=15)
        assert result.returncode==0,result.stdout+result.stderr
