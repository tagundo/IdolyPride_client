"""Scoped local downloads retain the original Android result-processing flow."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

NATIVE = Path(__file__).resolve().parents[1]


def compile_run(tmp_path, source):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("Host C++ compiler unavailable")
    binary = tmp_path / "local-resources"
    subprocess.run([compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
                    "-I", str(NATIVE), str(source), "-o", str(binary)],
                   check=True, capture_output=True, timeout=20)
    subprocess.run([str(binary)], check=True, capture_output=True, timeout=5)


def test_gateway_object_urls_and_remote_or_malformed_urls(tmp_path):
    compile_run(tmp_path, NATIVE / "tests/local_resource_policy_test.cpp")


def test_actual_hook_preserves_original_calls_and_post_http_error_md5_checks(tmp_path):
    bridge = (NATIVE / "bridge.cpp").read_text()
    fragment = bridge.split("// BEGIN_LOCAL_RESOURCE_REACHABILITY_HOOK\n", 1)[1].split(
        "// END_LOCAL_RESOURCE_REACHABILITY_HOOK", 1)[0]
    source = tmp_path / "hook.cpp"
    source.write_text(r'''
#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstring>
#include <stdexcept>
#include <string>
#include "local_resource_policy.hpp"
using namespace idoly::presentation;
using Method=const void;
std::atomic<bool> ready{true};
template<class T>T read(void*object,size_t offset){T value{};std::memcpy(&value,(char*)object+offset,sizeof value);return value;}
''' + fragment + r'''
struct ManagedString {void*klass{};void*monitor{};int32_t length{};uint16_t data[256]{};};
struct Request {void*klass{};void*monitor{};ManagedString*url{};uint64_t untouched=0x123456789abcdef0;};
static_assert(offsetof(Request,url)==0x10&&offsetof(ManagedString,length)==0x10&&offsetof(ManagedString,data)==0x14);
ManagedString text(const char*ascii){ManagedString value;value.length=(int32_t)std::strlen(ascii);for(int i=0;i<value.length;++i)value.data[i]=(unsigned char)ascii[i];return value;}
bool internet=false,throw_original=false;int original_calls=0,errors_classified=0;void*seen_self{};Method*seen_method{};
bool original(void*self,Method*method){++original_calls;seen_self=self;seen_method=method;if(throw_original)throw std::runtime_error("original");if(!internet)++errors_classified;return internet;}
Method*info=(Method*)0x1234;
enum class Result{IoError,Unreachable,NativeError,HashDiffered,Success};
// Captured original HTTP200 callback ordering: IO before CanReach, then
// IsError and CreateSuccess(expectedMd5,actualMd5). The latter's original
// constructor records hash inequality, which later verification still sees.
Result completed_200(Request&request,bool io,bool native_error,const char*expected,const char*actual,bool adapter){
 if(io)return Result::IoError;
 bool reachable=adapter?resource_can_reach_hook(&request,info):original(&request,info);
 if(!reachable)return Result::Unreachable;
 if(native_error)return Result::NativeError;
 if(std::strcmp(expected,actual))return Result::HashDiffered;
 return Result::Success;
}
int main(){
 resource_can_reach_original=original;
 const char*urls[]={
  "http://127.0.0.1:8080/octo/202050/assetbundle/EiDd9n/1768822424265240",
  "http://127.0.0.1:8080/octo/202050/assetbundle/yFD8qT/1768822424267701",
  "http://127.0.0.1:8080/octo/202050/assetbundle/JTAnvR/1768822424398894",
  "http://127.0.0.1:8080/octo/202050/assetbundle/nTGbK7/1768822424602282"};
 for(auto url:urls){auto value=text(url);Request request;request.url=&value;
  for(int attempt=0;attempt<5;++attempt){assert(completed_200(request,false,false,"md5","md5",false)==Result::Unreachable);assert(completed_200(request,false,false,"md5","md5",true)==Result::Success);}
  assert(completed_200(request,true,false,"md5","md5",true)==Result::IoError);
  assert(completed_200(request,false,true,"md5","md5",true)==Result::NativeError);
  assert(completed_200(request,false,false,"md5","different",true)==Result::HashDiffered);
  assert(request.untouched==0x123456789abcdef0&&!internet);
 }
 assert(original_calls==20&&errors_classified==20);
 auto remote=text("https://d2ilil7yh5oi1v.cloudfront.net/a");Request request;request.url=&remote;
 assert(completed_200(request,false,false,"md5","md5",true)==Result::Unreachable);
 assert(seen_self==&request&&seen_method==info);internet=true;
 assert(completed_200(request,false,false,"md5","md5",true)==Result::Success);
 throw_original=true;try{resource_can_reach_hook(&request,info);assert(false);}catch(const std::runtime_error&){}throw_original=false;
 auto local=text(urls[0]);request.url=&local;ready=false;internet=false;
 assert(completed_200(request,false,false,"md5","md5",true)==Result::Unreachable);ready=true;
 request.url=nullptr;assert(!resource_can_reach_hook(&request,info));
 local.length=-1;request.url=&local;assert(!resource_can_reach_hook(&request,info));
 local.length=200;assert(!resource_can_reach_hook(&request,info));
 local=text(urls[0]);assert(!resource_can_reach_hook(&request,nullptr)&&seen_self==&request&&seen_method==nullptr);
 assert(!resource_can_reach_hook(nullptr,info)&&seen_self==nullptr&&seen_method==info);
}
''')
    compile_run(tmp_path, source)


def test_hook_and_fields_are_android_only_and_version_pinned():
    profile = json.loads((NATIVE / "profile.json").read_text())
    alias = profile["aliases"]["resource_can_reach"]
    assert alias["rva"] == "0x8149f68" and alias["prefix16"] == "fe57bea9f44f01a934f9009055bd00b0"
    assert alias["mode"] == "HOOK" and alias["is_static"] is False and alias["parameters"] == []
    assert alias["return_type"]["class"] == "System.Boolean"
    assert profile["local_resource_reachability"]["request_url_offset"] == 0x10
    assert profile["local_resource_reachability"]["string_length_offset"] == 0x10
    assert profile["local_resource_reachability"]["string_utf16_offset"] == 0x14
    ios = json.loads((NATIVE.parent / "ios/profile.json").read_text())
    assert "resource_can_reach" not in ios["aliases"]
    bridge = (NATIVE / "bridge.cpp").read_text()
    body = bridge.split("#ifndef IDOLY_DARWIN_BRIDGE\n// BEGIN_LOCAL_RESOURCE_REACHABILITY_HOOK\n", 1)[1].split("\n#endif", 1)[0]
    assert "resource_can_reach_original(self, method)" in body
    assert "game_call" not in body and "image_base" not in body
    assert "HOOK(resource_can_reach,resource_can_reach_hook,resource_can_reach_original)" in bridge
    # The installer pauses after its first hook so fonts can be captured during
    # initial graphics readiness. A new network hook must not precede it.
    hooks = bridge.split("Hook hooks[] = {", 1)[1].split("};", 1)[0]
    assert hooks.lstrip().startswith("HOOK(font_awake,font_awake_hook,font_awake_original)")
