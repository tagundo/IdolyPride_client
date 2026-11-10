"""Portable safety checks; actual Unity/translated execution is a separate CI check."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ui_native_build", HERE / "build_native.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def test_profile_covers_every_loaded_export(tmp_path):
    profile = json.loads((HERE / "runtime-profile.json").read_text())
    loaded = {"il2cpp_" + name for name in re.findall(r"LOAD\((\w+)\);", (HERE / "ui_bridge.c").read_text())}
    assert loaded == {row["name"] for row in profile["exports"]}
    assert len(loaded) == 26
    build.header(profile, tmp_path / "ui_profile.h")
    assert "UI_EXPORT_COUNT" in (tmp_path / "ui_profile.h").read_text()
    for field, value in [("schema", 2), ("architecture", "x86_64"), ("client_version", "6.1.0")]:
        with pytest.raises(ValueError):
            build.header(dict(profile, **{field: value}), tmp_path / "invalid.h")


def test_duplicate_export_rejected(tmp_path):
    profile = json.loads((HERE / "runtime-profile.json").read_text())
    profile["exports"].append(profile["exports"][0])
    with pytest.raises(ValueError):
        build.header(profile, tmp_path / "invalid.h")


HARNESS = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdarg.h>
#include "ui_bridge.c"
static bool main_thread = true, active_value = true, enabled_value = true, interactable_value = false;
static int32_t id_value = 123;
static int alive_m, game_m, active_m, enabled_m, interact_m, id_m, dispatch_m, virtual_m;
static int free_count, invoke_count;
static const Method *seen_method;
static bool throw_managed;
static jclass jf(JNIEnv *e, const char *n) { (void)e;(void)n;return (jclass)1; }
static jmethodID jm(JNIEnv *e,jclass c,const char *n,const char *s) { (void)e;(void)c;(void)n;(void)s;return (jmethodID)1; }
static jobject jcallstatic(JNIEnv *e,jclass c,jmethodID m,...) { (void)e;(void)c;(void)m;return (jobject)1; }
static jobject jcall(JNIEnv *e,jobject c,jmethodID m,...) { (void)e;(void)c;(void)m;return (jobject)1; }
static const char *jchars(JNIEnv *e,jstring s,jboolean *c) { (void)e;(void)s;(void)c;return main_thread?"UnityMain":"worker"; }
static void jrelease(JNIEnv *e,jstring s,const char *c) { (void)e;(void)s;(void)c; }
static void jdelete(JNIEnv *e,jobject s) { (void)e;(void)s; }
static jboolean jexception(JNIEnv *e) { (void)e;return JNI_FALSE; }
static void jclear(JNIEnv *e) { (void)e; }
static jstring jnew(JNIEnv *e,const char *s) { (void)e;return (jstring)strdup(s); }
static const struct JNINativeInterface_ table = {
 .FindClass=jf,.GetStaticMethodID=jm,.GetMethodID=jm,.CallStaticObjectMethod=jcallstatic,
 .CallObjectMethod=jcall,.GetStringUTFChars=jchars,.ReleaseStringUTFChars=jrelease,
 .DeleteLocalRef=jdelete,.ExceptionCheck=jexception,.ExceptionClear=jclear,.NewStringUTF=jnew
};
static void *current(void) { return (void*)1; }
static void *unbox(Obj *o) { return o; }
static Obj *target(uint32_t n) { return n?(Obj*)1:NULL; }
static void release(uint32_t n) { assert(n);++free_count; }
static const Method *virtual_method(Obj *o,const Method *m) { assert(o);return m==&dispatch_m?&virtual_m:m; }
static Obj *call(const Method *m,Obj *o,void **p,Obj **exception) {
 (void)o;(void)p;++invoke_count;seen_method=m;
 if(throw_managed){*exception=(Obj*)0xdead;return NULL;}
 static bool truth=true;
 if(m==&alive_m||m==&enabled_m)return &truth;
 if(m==&game_m)return (Obj*)1;
 if(m==&active_m)return &active_value;
 if(m==&interact_m)return &interactable_value;
 if(m==&id_m)return &id_value;
 return NULL;
}
static void expect(JNIEnv *e,int id,long version,const char *message) {
 jstring result=Java_game_qualiarts_idolypride_qa_ui_NativeUiBridge_nativeClick(e,NULL,id,version);
 assert(result&&strcmp((char*)result,message)==0);free(result);
}
int main(void) {
 char data[128]={0};struct ui_json j={data,sizeof(data),0,false};
 uint16_t value[]={34,92,10,0x65e5,0xd83d,0xde00};
 ui_utf16(&j,value,6,6);assert(!j.failed);
 assert(strcmp(data,"\"\\\"\\\\\\u000a\\u65e5\\ud83d\\ude00\"")==0);
 char small[8]={0};struct ui_json limited={small,sizeof(small),0,false};
 ui_raw(&limited,"1234567");assert(!limited.failed);ui_raw(&limited,"8");assert(limited.failed);assert(small[7]==0);
 JNIEnv env=&table;
 api.thread_current=current;api.object_unbox=unbox;api.gchandle_get_target=target;api.gchandle_free=release;
 api.runtime_invoke=call;api.object_get_virtual_method=virtual_method;
 methods.alive=&alive_m;methods.game_object=&game_m;methods.active=&active_m;
 methods.enabled=&enabled_m;methods.interactable=&interact_m;methods.id=&id_m;
 initialized=true;generation=9;snapshot_time=now_ms();buttons[0]=(struct retained){123,1,false};button_count=1;
 expect(&env,123,8,"{\"ok\":false,\"error\":\"stale_generation\"}");assert(invoke_count==0);
 expect(&env,124,9,"{\"ok\":false,\"error\":\"node_not_found\"}");assert(invoke_count==0);
 expect(&env,123,9,"{\"ok\":false,\"error\":\"node_not_interactable\"}");assert(generation==9);
 active_value=false;interactable_value=true;
 expect(&env,123,9,"{\"ok\":false,\"error\":\"node_not_interactable\"}");
 active_value=true;main_thread=false;
 expect(&env,123,9,"{\"ok\":false,\"error\":\"wrong_thread\"}");main_thread=true;
 expect(&env,123,9,"{\"ok\":false,\"error\":\"native_click_disabled_use_adb\"}");assert(generation==9);
 snapshot_time=now_ms()-3001;
 expect(&env,123,9,"{\"ok\":false,\"error\":\"stale_generation\"}");
 bool ok=true;invoke(&dispatch_m,(Obj*)1,NULL,true,&ok);assert(ok&&seen_method==&virtual_m);
 throw_managed=true;ok=true;assert(invoke(&dispatch_m,(Obj*)1,NULL,true,&ok)==NULL&&!ok);throw_managed=false;
 ok=true;assert(!value_bool(NULL,&ok)&&!ok);
 clear_buttons();assert(free_count==1&&button_count==0);
 generation=INT64_MAX;advance();assert(generation==1);
 puts("host safety checks passed");return 0;
}
'''


def test_host_native_safety(tmp_path):
    compiler = shutil.which("cc")
    java = Path(os.environ.get("JAVA_HOME", "/usr/lib/jvm/java-21-openjdk-amd64"))
    if not compiler or not (java / "include/jni.h").is_file():
        pytest.skip("Host C compiler and JAVA_HOME JNI headers required")
    build.header(json.loads((HERE / "runtime-profile.json").read_text()), tmp_path / "ui_profile.h")
    source = tmp_path / "harness.c"; source.write_text(HARNESS)
    executable = tmp_path / "harness"
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-variable",
        "-I", str(HERE), "-I", str(tmp_path), "-I", str(java / "include"), "-I", str(java / "include/linux"),
        str(source), "-ldl", "-lpthread", "-lm", "-o", str(executable)], check=True, capture_output=True)
    result = subprocess.run([str(executable)], check=True, text=True, capture_output=True)
    assert result.stdout == "host safety checks passed\n"
