"""Finite original SRP controller lease with modeled typed hook/API leaves."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include "mp4_actor_state.hpp"
#include <cassert>
#include <map>
#include <string>
using namespace idoly_mp4_srp;
struct Fixture {
 ControllerLease lease;Image image{};FramePlan plan{true,1};std::map<uint32_t,void*> roots;
 int controller,camera,queue,array,grown,action,other,cameras;uint32_t next=1;int writes=0;
 bool source=true,held=true,entry=true,action_ok=true,drop_write=false,lose_root=false;Operation operation=Operation::add;
 Fixture(){image.controller=&controller;image.camera=&camera;image.first=true;}
}*f;
bool current(void* p,void* c,void* camera){assert(p==f);return f->source&&c==&f->controller&&camera==&f->camera;}
bool held(void* p){assert(p==f);return f->held;}
bool read(void* p,Image& value){assert(p==f);value=f->image;return true;}
uint32_t retain(void* p){auto h=f->next++;f->roots[h]=p;return h;}
void* target(uint32_t h){return f->lose_root?nullptr:f->roots.at(h);}
void release(uint32_t h){assert(f->roots.erase(h)==1);}
bool entered(void* p,Operation op,void* receiver,void*){assert(p==f&&receiver==&f->controller);return f->entry&&op==f->operation;}
bool plan(void* p,void* cameras,FramePlan& out){assert(p==f&&cameras==&f->cameras);out=f->plan;return true;}
bool action(void* p,void* a){assert(p==f&&a==&f->action);return f->action_ok;}
bool restore(void* p,const Image& v){assert(p==f);++f->writes;if(!f->drop_write)f->image=v;return true;}
Api api(){return {current,held,read,retain,target,release,entered,plan,action,restore};}
void queue(size_t n=1,size_t capacity=4){f->image.queue=&f->queue;f->image.array=&f->array;f->image.capacity=capacity;f->image.count=n;f->image.version=4;for(size_t i=0;i<n;++i)f->image.items[i]=&f->action;}
void append(){auto&v=f->image;if(!v.queue){v.queue=&f->queue;v.array=&f->array;}
 if(v.count==v.capacity){v.capacity=v.capacity?v.capacity*2:4;v.array=&f->grown;}v.items[v.count++]=&f->action;++v.version;}
void clear_queue(){auto&v=f->image;if(v.queue){for(size_t i=0;i<v.count;++i)v.items[i]=nullptr;v.count=0;++v.version;}}
Token begin(Operation op){f->operation=op;Token token;const bool ok=op==Operation::add?f->lease.begin_add(&f->controller,&f->action,token):op==Operation::invoke?f->lease.begin_invoke(&f->controller,token):f->lease.begin_frame(&f->controller,&f->cameras,token);assert(ok);return token;}
void frame(){auto token=begin(Operation::frame);f->image.first=f->image.first&&!f->plan.clears_first;
 for(size_t i=0;i<f->plan.selected_invocations;++i){auto invoke=begin(Operation::invoke);clear_queue();assert(f->lease.end_invoke(invoke));}
 assert(f->lease.end_frame(token));}
int main(int argc,char** argv){assert(argc==2);Fixture fixture;f=&fixture;const std::string s=argv[1];
 if(s!="null"&&s!="lazy_add")queue(s=="empty"?0:s=="grow"?4:1,s=="grow"?4:4);
 if(s=="bad_tail"){f->image.items[3]=&f->other;assert(!f->lease.capture(api(),f));return 0;}
 if(s=="bad_capacity"){f->image.capacity=max_capacity+1;assert(!f->lease.capture(api(),f));return 0;}
 if(s=="capture_unheld"){f->held=false;assert(!f->lease.capture(api(),f));return 0;}
 if(s=="capture_source_lost"){f->source=false;assert(!f->lease.capture(api(),f));return 0;}
 Image saved=f->image;assert(f->lease.capture(api(),f));Token token;
 if(s=="unknown_add"){f->entry=false;assert(!f->lease.begin_add(&f->controller,&f->action,token));}
 else if(s=="foreign_action"){f->action_ok=false;assert(!f->lease.begin_add(&f->controller,&f->action,token));}
 else if(s=="unobserved_add"){append();assert(!f->lease.restore()&&!f->writes);}
 else if(s=="unobserved_first"){f->image.first=false;assert(!f->lease.restore()&&!f->writes);}
 else if(s=="wrong_invoke_origin"){f->operation=Operation::invoke;assert(!f->lease.begin_invoke(&f->controller,token));}
 else if(s=="frame_missing_invoke"){token=begin(Operation::frame);f->image.first=false;assert(!f->lease.end_frame(token));}
 else if(s=="frame_extra_invoke"){token=begin(Operation::frame);f->image.first=false;auto invoke=begin(Operation::invoke);clear_queue();assert(f->lease.end_invoke(invoke));assert(!f->lease.begin_invoke(&f->controller,invoke));}
 else if(s=="frame_first_wrong"){token=begin(Operation::frame);auto invoke=begin(Operation::invoke);clear_queue();assert(f->lease.end_invoke(invoke));assert(!f->lease.end_frame(token));}
 else if(s=="frame_flag_reverts"){token=begin(Operation::frame);f->image.first=false;auto invoke=begin(Operation::invoke);clear_queue();assert(f->lease.end_invoke(invoke));f->image.first=true;assert(!f->lease.end_frame(token));}
 else if(s=="invoke_replaces_list"){token=begin(Operation::frame);f->image.first=false;auto invoke=begin(Operation::invoke);clear_queue();f->image.queue=&f->other;assert(!f->lease.end_invoke(invoke));}
 else if(s=="invoke_wrong_version"){token=begin(Operation::frame);f->image.first=false;auto invoke=begin(Operation::invoke);clear_queue();--f->image.version;assert(!f->lease.end_invoke(invoke));}
 else if(s=="add_wrong_version"){token=begin(Operation::add);append();--f->image.version;assert(!f->lease.end_add(token));}
 else if(s=="add_wrong_prefix"){token=begin(Operation::add);append();f->image.items[0]=&f->other;assert(!f->lease.end_add(token));}
 else if(s=="add_wrong_growth"){token=begin(Operation::add);append();++f->image.capacity;assert(!f->lease.end_add(token));}
 else if(s=="stale_token"){token=begin(Operation::add);append();++token.id;assert(!f->lease.end_add(token));}
 else if(s=="exception"){token=begin(Operation::add);append();f->lease.reject();assert(!f->lease.restore()&&!f->writes);}
 else if(s=="held_restore"){frame();f->held=false;assert(!f->lease.restore()&&!f->writes);}
 else if(s=="source_handoff"){frame();f->source=false;f->lease.clear();assert(!f->writes&&f->roots.empty());return 0;}
 else if(s=="root_lost"){f->lose_root=true;assert(!f->lease.restore()&&!f->writes);}
 else if(s=="restore_verify"){frame();f->drop_write=true;assert(!f->lease.restore()&&f->writes==1);}
 else {
  if(s=="lazy_add"||s=="add"||s=="grow"){token=begin(Operation::add);append();assert(f->lease.end_add(token));}
  if(s=="two_cameras")f->plan.selected_invocations=2;
  if(s=="no_camera"){f->plan.selected_invocations=0;f->plan.clears_first=false;}
  if(s=="version_wrap")f->image.version=saved.version=0xffffffffu;
  if(s=="version_wrap"){f->lease.clear();assert(f->lease.capture(api(),f));}
  frame();assert(f->lease.restore()&&f->writes==1);assert(f->image.queue==saved.queue&&f->image.array==saved.array&&f->image.version==saved.version&&f->image.count==saved.count&&f->image.first==saved.first);
  assert(f->lease.restore()&&f->writes==1);assert(!f->lease.poisoned());f->lease.clear();assert(f->roots.empty());return 0;
 }
 assert(f->lease.poisoned());f->lease.clear();assert(f->roots.empty());return 0;
}
'''


@pytest.fixture(scope="module")
def binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp("mp4-srp-state")
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
    "null", "empty", "queue", "lazy_add", "add", "grow", "two_cameras", "no_camera", "version_wrap",
    "bad_tail", "bad_capacity", "capture_unheld", "capture_source_lost", "unknown_add", "foreign_action",
    "unobserved_add", "unobserved_first", "wrong_invoke_origin", "frame_missing_invoke", "frame_extra_invoke",
    "frame_first_wrong", "frame_flag_reverts", "invoke_replaces_list", "invoke_wrong_version", "add_wrong_version",
    "add_wrong_prefix", "add_wrong_growth", "stale_token", "exception", "held_restore", "source_handoff", "root_lost", "restore_verify",
])
def test_finite_original_srp_controller_lease(binary, case):
    result = subprocess.run([str(binary), case], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
