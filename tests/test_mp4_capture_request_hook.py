"""Actual CaptureRequest hook/guard nesting; Unity body/services are modeled."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def hook(tmp_path_factory):
    header = (ROOT / "client-presentation/native/mp4_camera_owner.hpp").read_text()
    guard = header.split("// BEGIN_MP4_CAPTURE_PUBLICATION_GUARD", 1)[1].split("// END_MP4_CAPTURE_PUBLICATION_GUARD", 1)[0]
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    actual = bridge.split("// BEGIN_MP4_CAPTURE_REQUEST_HOOK", 1)[1].split("// END_MP4_CAPTURE_REQUEST_HOOK", 1)[0]
    model = r'''
#include <cstdint>
#include <cassert>
#include <string>
#include <stdexcept>
// GUARD
using Method=const void;using VoidMethod=void(*)(void*,Method*);
void*ptr(uintptr_t n){return reinterpret_cast<void*>(n);}
bool owner=true,inflight=true,bound=true,fail=false,nested=false,body_running=false;int original_calls=0,enters=0,ends=0,ordinary=0,suppressed=0,depth=0;
bool game_call(){return owner;}
namespace idoly_mp4_runtime{struct Game{uint64_t capture_request_origin_serial(void*p){assert(owner);return inflight&&p==ptr(12)?13:0;}}game;}
// HOOK
mp4publication::Api api(){mp4publication::Api a{};a.thread=[](){return owner;};a.issued=[](void*c,void*camera,void*d,uint64_t e,uint64_t j,uint64_t serial){return c==ptr(10)&&camera==ptr(11)&&d==ptr(12)&&e==7&&j==9&&serial==13;};a.publication_origin=[](void*,void*c,uint64_t serial){return c==ptr(12)&&serial==13;};a.current=[](void*c,uint64_t e,uint64_t j){return c==ptr(10)&&e==7&&j==9;};
 a.owned_request=[](void*,void*c,void*d,uint64_t s){return inflight&&c==ptr(11)&&d==ptr(12)&&s==13;};
 a.current_capture=[](void*,void*,void**w,void**t){*w=ptr(21);*t=ptr(22);return true;};
 a.private_capture=[](void*,void*,void*w,void*t){return w==ptr(21)&&t==ptr(22);};a.source_program=[](void*,uint64_t,uint64_t){return true;};return a;}
void enter(mp4publication::Request&r,void*c,uint64_t serial)noexcept{assert(owner);++enters;(void)r.enter(api(),ptr(10),ptr(11),c,7,9,serial,55,0x923d4e4);}
void complete(void*c,uint64_t s,const mp4publication::Receipt&r,bool returned)noexcept{
 assert(owner&&!body_running&&inflight);++ends;
 if(c==ptr(12)&&s==13){assert(r.request==13&&r.valid&&r.suppressed==1);assert(returned!=fail);}
 else assert(!r.valid&&!r.suppressed);
}
void publication(){if(mp4publication::Request::suppress(55,ptr(22),0x923d4e4))++suppressed;else ++ordinary;}
void original(void*c,Method*m){assert(m==ptr(99));++original_calls;++depth;
 if(c==ptr(12)&&nested){const bool saved=body_running;body_running=false;mp4_capture_request_hook(ptr(14),m);body_running=saved;}
 body_running=true;publication();body_running=false;--depth;if(fail&&c==ptr(12))throw std::runtime_error("original");}
int main(int argc,char**argv){assert(argc==2);const std::string mode=argv[1];
 owner=mode!="offthread";inflight=mode!="unowned";bound=mode!="unbound";fail=mode=="throw";nested=mode=="nested";
 mp4_capture_request_original=original;if(bound){mp4_capture_publication_frontend.enter=enter;mp4_capture_publication_frontend.complete=complete;}
 bool threw=false;try{mp4_capture_request_hook(ptr(12),ptr(99));}catch(const std::runtime_error&){threw=true;}
 assert(threw==fail&&!depth&&!body_running&&original_calls==(nested?2:1));
 const bool owns=owner&&inflight&&bound;assert(suppressed==(owns?1:0)&&ordinary==(nested?1:owns?0:1));
 assert(enters==(owner&&bound?(nested?2:1):0)&&ends==enters);
 assert(!mp4publication::Request::suppress(55,ptr(22),0x923d4e4));
}
'''
    # Unowned invocations have no private completion obligation.
    model = model.replace('assert(owner&&!body_running&&inflight);', 'assert(owner&&!body_running);')
    folder = tmp_path_factory.mktemp("capture-request-hook")
    source, binary = folder / "hook.cpp", folder / "hook"
    source.write_text(model.replace("// GUARD", guard).replace("// HOOK", actual))
    result = subprocess.run([shutil.which("g++") or "clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-g", "-O1", "-fsanitize=address,undefined", "-fno-pie", "-no-pie", str(source), "-o", str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize("mode", ["owned", "unowned", "unbound", "offthread", "throw", "nested"])
def test_original_body_receipt_order_and_nested_mask(hook, mode):
    result = subprocess.run([str(hook), mode], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
