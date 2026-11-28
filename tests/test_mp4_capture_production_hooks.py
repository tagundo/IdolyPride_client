"""Shipping typed producer wrappers; modeled bank leaves are not a GPU run."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def hooks(tmp_path_factory):
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    actual = bridge.split("// BEGIN_MP4_CAPTURE_PRODUCTION_HOOKS\n", 1)[1].split("// END_MP4_CAPTURE_PRODUCTION_HOOKS", 1)[0]
    model = r'''
#include <cassert>
#include <cstdint>
#include <string>
#include <stdexcept>
using Method=const void;using VoidMethod=void(*)(void*,Method*);
bool owner=true,published=true,throws=false,abort_before=false,abort_after=false;int original_count=0,queries=0,foreign_count=0,begin_count=0,returned_count=0,failed_count=0,depth=0;
int receiver,name,method;void*expected_receiver=&receiver;const void*expected_descriptor=nullptr;uintptr_t last_caller=0;uint64_t last_request=0;
bool game_call(){return owner;}
namespace idoly_mp4_runtime{struct Game{uint64_t owned_capture_request_serial(void*p){assert(owner);return p==&receiver?71:0;}}game;}
namespace idoly_mp4_capture_publication{struct Request{struct Abort{};};}
namespace idoly_mp4_capture_production{
struct Descriptor{int32_t fields[13]{};};
struct Bank{
 struct Scope{bool active=true;Scope(){++begin_count;++depth;}~Scope(){if(active){++failed_count;--depth;}}bool must_abort()const{return active?abort_before:abort_after;}void finish(bool returned){assert(active&&returned);active=false;++returned_count;--depth;}};
 Scope update(void*p,uint64_t serial,uintptr_t caller){assert(owner&&p==&receiver&&caller);last_request=serial;return Scope{};}
 Scope wrapper(void*p,const Descriptor*d,void*n,uintptr_t caller){assert(owner&&p==&receiver&&d==expected_descriptor&&n==&name);last_caller=caller;return Scope{};}
 Scope texture(void*p,const Descriptor*d,uintptr_t caller){assert(owner&&p==&receiver&&d==expected_descriptor);last_caller=caller;return Scope{};}
}bank;
}
// SHIPPING
idoly_mp4_capture_production::Bank*active(){++queries;assert(owner);return published?&idoly_mp4_capture_production::bank:nullptr;}
void foreign()noexcept{assert(!owner);++foreign_count;}
void update_original(void*p,Method*m){assert(p==&receiver&&m==&method);++original_count;if(throws)throw std::runtime_error("original");}
void wrapper_original(void*p,const mp4capture::Descriptor*d,void*n,Method*m){assert(p==&receiver&&d==expected_descriptor&&n==&name&&m==&method);++original_count;if(throws)throw std::runtime_error("original");}
void texture_original(void*p,const mp4capture::Descriptor*d,Method*m){assert(p==&receiver&&d==expected_descriptor&&m==&method);++original_count;if(throws)throw std::runtime_error("original");}
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];mp4capture::Descriptor descriptor{};expected_descriptor=&descriptor;
 mp4_capture_production_frontend.active=active;mp4_capture_production_frontend.foreign=foreign;
 mp4_capture_update_original=update_original;mp4_capture_wrapper_ctor_original=wrapper_original;mp4_capture_texture_ctor_original=texture_original;
 owner=mode.find("foreign")==std::string::npos;published=mode.find("unbound")==std::string::npos;throws=mode.find("throw")!=std::string::npos;abort_before=mode.find("abort_before")!=std::string::npos;abort_after=mode.find("abort_after")!=std::string::npos;
 bool threw=false,aborted=false;try{
  if(mode.find("wrapper")!=std::string::npos)mp4_capture_wrapper_ctor_hook(&receiver,&descriptor,&name,&method);
  else if(mode.find("texture")!=std::string::npos)mp4_capture_texture_ctor_hook(&receiver,&descriptor,&method);
  else mp4_capture_update_hook(&receiver,&method);
 }catch(const std::runtime_error&){threw=true;}catch(const idoly_mp4_capture_publication::Request::Abort&){aborted=true;}
 assert(threw==throws&&aborted==(abort_before||abort_after)&&original_count==(abort_before?0:1)&&!depth);
 assert(queries==(owner?1:0)&&foreign_count==(owner?0:1));
 const bool scoped=owner&&published;assert(begin_count==(scoped?1:0));
 assert(returned_count==(scoped&&!throws&&!abort_before?1:0)&&failed_count==(scoped&&(throws||abort_before)?1:0));
 if(scoped){if(mode.find("wrapper")!=std::string::npos||mode.find("texture")!=std::string::npos)assert(last_caller);else assert(last_request==71);}
}
'''
    directory = tmp_path_factory.mktemp("mp4-production-hooks")
    source, binary = directory / "hooks.cpp", directory / "hooks"
    source.write_text(model.replace("// SHIPPING", actual))
    result = subprocess.run([shutil.which("g++") or "clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-O1", "-g", "-fsanitize=address,undefined", "-fno-pie", "-no-pie", str(source), "-o", str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize("operation", ["update", "wrapper", "texture"])
@pytest.mark.parametrize("state", ["owned", "throw", "foreign", "foreign_throw", "unbound", "unbound_throw", "abort_before", "abort_after"])
def test_exact_arguments_original_and_exception_duties(hooks, operation, state):
    result = subprocess.run([str(hooks), operation + "_" + state], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
