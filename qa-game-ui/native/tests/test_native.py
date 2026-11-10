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
static int parsed_m, array_m, find_m, name_m, transform_m, parent_m, default_m, old_text_m;
static bool requested_old_tmp_getter, text_dirty = true;
static unsigned parsed_calls, old_text_calls;
struct fake_string { int32_t length; uint16_t chars[32]; };
static struct fake_string rendered={13,{'v','e','r','s','i','o','n','.','6','.','1','.','1'}};
static struct fake_string old_text={13,{'v','e','r','s','i','o','n','.','0','.','2','.','0'}};
static struct fake_string label={10,{'A','p','p','V','e','r','s','i','o','n'}};
static const char *images[]={"UnityEngine.CoreModule.dll","mscorlib.dll","UnityEngine.UI.dll","Unity.TextMeshPro.dll","quaunity-ui.Runtime.dll"};
static void *domain(void) { return (void*)1; }
static const void **assemblies(const void *d,size_t *count) { (void)d;*count=5;return (const void**)images; }
static const void *image(const void *a) { return a; }
static const char *image_name(const void *i) { return i; }
static Klass *find_class(const void *i,const char *ns,const char *n) {
 (void)i;(void)ns;return !strcmp(n,"TMP_Text")?(Klass*)0x101:!strcmp(n,"Array")?(Klass*)0x102:(Klass*)0x103;
}
static const Method *find_method(Klass *k,const char *n,int count) {
 (void)count;
 if(k==(Klass*)0x101) {
  if(!strcmp(n,"get_text")){requested_old_tmp_getter=true;return &old_text_m;}
  if(!strcmp(n,"GetParsedText"))return &parsed_m;
 }
 return &default_m;
}
static const Method *next_method(Klass *k,void **iter) { (void)k;if(*iter)return NULL;*iter=(void*)1;return &array_m; }
static const char *method_name(const Method *m) { assert(m==&array_m);return "GetValue"; }
static uint32_t param_count(const Method *m) { (void)m;return 1; }
static const void *param(const Method *m,uint32_t n) { (void)m;assert(n==0);return (void*)1; }
static int type_kind(const void *t) { (void)t;return 8; }
static const void *class_type(Klass *k) { return k; }
static Obj *type_object(const void *t) { return (Obj*)t; }
static uintptr_t array_length(Obj *a) { (void)a;return 1; }
static uint32_t retain(Obj *o,bool pinned_value) { assert(o&&!pinned_value);return 2; }
static int32_t string_length(Obj *s) { return ((struct fake_string*)s)->length; }
static const uint16_t *string_chars(Obj *s) { return ((struct fake_string*)s)->chars; }
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
 if(m==&parsed_m){++parsed_calls;return &rendered;}
 if(m==&old_text_m){++old_text_calls;Obj *s=text_dirty?(Obj*)&rendered:(Obj*)&old_text;text_dirty=false;return s;}
 if(m==&find_m)return (Obj*)0x1234;
 if(m==&array_m)return (Obj*)1;
 if(m==&name_m)return &label;
 if(m==&transform_m)return (Obj*)2;
 if(m==&parent_m)return NULL;
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
 /* Exercise the real initializer, with an adversarial stale get_text API. */
 initialized=false;pinned=(void*)1;
 api.domain_get=domain;api.domain_get_assemblies=assemblies;api.assembly_get_image=image;
 api.image_get_name=image_name;api.class_from_name=find_class;api.class_get_method_from_name=find_method;
 api.class_get_methods=next_method;api.method_get_name=method_name;api.method_get_param_count=param_count;
 api.method_get_param=param;api.type_get_type=type_kind;
 assert(initialize()&&methods.tmp_value==&parsed_m&&!requested_old_tmp_getter);
 methods.find_all=&find_m;methods.array_get=&array_m;methods.id=&id_m;methods.name=&name_m;
 methods.alive=&alive_m;methods.game_object=&game_m;methods.transform=&transform_m;
 methods.active=&active_m;methods.enabled=&enabled_m;methods.parent=&parent_m;methods.rect=NULL;
 api.class_get_type=class_type;api.type_get_object=type_object;api.array_length=array_length;
 api.gchandle_new=retain;api.string_length=string_length;api.string_chars=string_chars;
 for(int read=0;read<2;++read){
  char output[2048]={0};struct ui_json snapshot={output,sizeof(output),0,false};
  size_t nodes=0;bool truncated=false;snapshot_time=now_ms();
  assert(add_kind(&snapshot,methods.tmp,"tmp_text",methods.tmp_value,false,&nodes,&truncated));
  assert(nodes==1&&!snapshot.failed&&!truncated);
  assert(strstr(output,"\"text\":\"version.6.1.1\"")&&!strstr(output,"version.0.2.0"));
 }
 assert(parsed_calls==2&&old_text_calls==0&&text_dirty);
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
