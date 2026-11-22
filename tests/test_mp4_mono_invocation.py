"""Pure original-callback invocation evidence; fake leaves are not a Unity run."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include "mp4_actor_state.hpp"
#include <cassert>
#include <stdexcept>
#include <string>
using namespace idoly_mp4_actor;
MonoGate gate;RandomState random_state{{1,2,3,4}};int object,other,gets,sets,checks;
std::string mode;bool owner=true;uint64_t outer_id=0,nested_id=0;
bool current(void*){++checks;return owner;}
bool thread(){++checks;return true;}
void get(RandomState* out,Method*){++gets;MonoInvocation v;if(mode!="suspended")assert(!gate.invocation(v));*out=random_state;}
void set(const RandomState* value,Method*){++sets;random_state=*value;}
void none(void*,Method*){MonoInvocation v;assert(!gate.invocation(v));}
void nested(void*,Method*);
void observed(void* p,Method*){
 MonoInvocation v;const int before=checks;assert(gate.invocation(v));assert(checks==before);
 assert(v.epoch==17&&v.serial==1&&v.receiver==p&&v.callback==observed&&v.phase==MonoPhase::actor_late&&v.random_depth==1&&v.invocation);
 outer_id=v.invocation;
 if(mode=="nested"||mode=="nested_throw"){
  try{gate.invoke(MonoPhase::actor_late,nested,p,nullptr);}catch(const std::runtime_error&){assert(mode=="nested_throw");}
  assert(gate.invocation(v)&&v.callback==observed&&v.invocation==outer_id&&nested_id!=outer_id);
 }else if(mode=="unowned"){
  gate.invoke(MonoPhase::actor_late,none,&other,nullptr);
  assert(gate.invocation(v)&&v.invocation==outer_id);
 }else if(mode=="suspended"){
  RandomSuspension token;assert(gate.suspend_rng_for_unowned(token));assert(!gate.invocation(v));assert(gate.resume_rng_after_unowned(token));assert(gate.invocation(v)&&v.invocation==outer_id);
 }else if(mode=="hold"){assert(gate.hold(17));assert(!gate.invocation(v));}
 else if(mode=="revoke"){assert(gate.revoke(17));assert(!gate.invocation(v));}
 else if(mode=="release"){gate.release(17);assert(!gate.invocation(v));}
 else if(mode=="handoff"){gate.restore_rng_before_source_change();assert(!gate.invocation(v));}
 else if(mode=="abandon"){gate.abandon_rng_before_source_change();assert(!gate.invocation(v));}
 else if(mode=="throw"){throw std::runtime_error("original");}
}
void nested(void* p,Method*){
 MonoInvocation v;assert(gate.invocation(v)&&v.receiver==p&&v.callback==nested&&v.phase==MonoPhase::actor_late&&v.invocation!=outer_id);nested_id=v.invocation;
 if(mode=="nested_throw")throw std::runtime_error("base");
}
int main(int argc,char** argv){assert(argc==2);mode=argv[1];MonoInvocation v;
 assert(!gate.invocation(v));MonoReceiver receivers[]={{&object,MonoPhase::actor_late}};
 assert(gate.publish({current,thread,get,set},&object,17,receivers,1));assert(!gate.invocation(v));
 if(mode=="held"){gate.invoke(MonoPhase::actor_late,observed,&object,nullptr);assert(!outer_id);return 0;}
 assert(gate.grant(17,1));assert(!gate.invocation(v));
 if(mode=="ambient"){assert(gate.isolate([&]{assert(!gate.invocation(v));}));return 0;}
 if(mode=="render"){assert(gate.isolate_render(17,[&]{assert(!gate.invocation(v));}));return 0;}
 if(mode=="wrong_thread"){owner=false;gate.invoke(MonoPhase::actor_late,observed,&object,nullptr);assert(!outer_id&&!gate.invocation(v));return 0;}
 try{gate.invoke(MonoPhase::actor_late,observed,&object,nullptr);}catch(const std::runtime_error&){assert(mode=="throw");}
 assert(!gate.invocation(v)&&outer_id);
}
'''


@pytest.fixture(scope="module")
def binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp("mp4-mono-invocation")
    source = directory / "test.cpp"
    source.write_text(SOURCE)
    output = directory / "test"
    result = subprocess.run([
        shutil.which("g++") or "clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-g", "-O1", "-fsanitize=address,undefined", "-fno-pie", "-no-pie",
        "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(output),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return output


@pytest.mark.parametrize("case", [
    "active", "held", "ambient", "render", "wrong_thread", "nested", "nested_throw",
    "unowned", "suspended", "hold", "revoke", "release", "handoff", "abandon", "throw",
])
def test_actual_entered_original_receipt(binary, case):
    result = subprocess.run([str(binary), case], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
