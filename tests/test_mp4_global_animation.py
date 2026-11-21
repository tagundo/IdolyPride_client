"""Production active Animator/Legacy inventory classification on typed fixtures.

These model exact source graph owners and property changes; they do not claim
that an arbitrary Animator or scene is restorable, or execute Unity/GPU code.
"""
from pathlib import Path
import shutil,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'client-presentation/native'
HARNESS=r'''
#include "mp4_engine_clock.hpp"
#include <cassert>
#include <string>
#include <vector>
using namespace idoly_mp4_world;
struct Animator{bool active=true,bound=true,valid=true,owned=true,live=true,bindings=true;int32_t mode=0;AnimationGraph graph{0x1100,7,0};void*controller=nullptr;};
struct Legacy{bool active=true,live=true;int32_t states=0;};
struct Family{std::vector<void*>items;}animators,legacy;
Animator actor,stage,ui;Legacy empty_legacy;
unsigned roots=0;void*held[8]{};bool source=true,query=true,root_live=true;std::string mode;unsigned graph_calls=0,legacy_calls=0;
bool current(void*){return source;}
bool mapped(uintptr_t a,size_t n){for(auto*f:{&animators,&legacy}){uintptr_t b=reinterpret_cast<uintptr_t>(f->items.data());size_t bytes=f->items.size()*sizeof(void*);if(a>=b&&n<=bytes&&a-b<=bytes-n)return true;}return false;}
bool is_type(void*p,const char*n){if(!strcmp(n,"System.Array"))return p==&animators||p==&legacy;if(!strcmp(n,"UnityEngine.Animator"))return p==&actor||p==&stage||p==&ui;if(!strcmp(n,"UnityEngine.Animation"))return p==&empty_legacy;if(!strcmp(n,"UnityEngine.RuntimeAnimatorController"))return p==reinterpret_cast<void*>(0x700);return false;}
bool alive(void*p){if(p==&empty_legacy)return empty_legacy.live;if(p==reinterpret_cast<void*>(0x700))return true;for(auto*a:{&actor,&stage,&ui})if(p==a)return a->live;return false;}
uint32_t retain(void*p){if(mode=="root_failure")return 0;for(unsigned i=0;i<8;++i)if(!held[i]){held[i]=p;++roots;return i+1;}return 0;}
void*target(uint32_t i){return i&&i<=8&&root_live?held[i-1]:nullptr;}void free_root(uint32_t i){assert(i&&i<=8&&held[i-1]);held[i-1]=nullptr;--roots;}
size_t length(void*p){return static_cast<Family*>(p)->items.size();}void*data(void*p){return static_cast<Family*>(p)->items.data();}
void*find(void*type,bool inactive,Method*){assert(!inactive);return query?(type==reinterpret_cast<void*>(1)?&animators:&legacy):nullptr;}
bool active(void*p,Method*){if(p==&empty_legacy)return empty_legacy.active;return static_cast<Animator*>(p)->active;}
void graph(void*p,AnimationGraph*out,Method*){auto&a=*static_cast<Animator*>(p);++graph_calls;*out=a.graph;if(mode=="graph_replaced"&&graph_calls==2)++out->version;if(mode=="source_changed")source=false;if(mode=="root_lost")root_live=false;}
void*controller(void*p,Method*){return static_cast<Animator*>(p)->controller;}bool bound(void*p,Method*){return static_cast<Animator*>(p)->bound;}int32_t update_mode(void*p,Method*){return static_cast<Animator*>(p)->mode;}
bool valid(AnimationGraph*g,Method*){if(!g->handle)return false;for(auto*a:{&actor,&stage,&ui})if(a->graph.handle==g->handle)return a->valid;return false;}
int32_t count(void*p,Method*){++legacy_calls;return static_cast<Legacy*>(p)->states+(mode=="legacy_changed"&&legacy_calls==2);}
bool owned(void*,void*p,const AnimationGraph&g){auto&a=*static_cast<Animator*>(p);return a.owned&&a.graph.handle==g.handle&&a.graph.version==g.version;}
bool bindings(void*,void*p){return static_cast<Animator*>(p)->bindings;}
GlobalAnimationApi api(){GlobalAnimationApi a{};auto&w=a.world;w.source_current=current;w.find_objects=find;w.is_type=is_type;w.alive=alive;w.retain=retain;w.retained=target;w.release_root=free_root;w.array_length=length;w.array_data=data;w.mapped=mapped;
 a.active_enabled=active;a.animator_graph=graph;a.animator_controller=controller;a.animator_bound=bound;a.animator_mode=update_mode;a.graph_valid=valid;a.legacy_state_count=count;a.graph_owned=owned;a.bindings_owned=bindings;a.animator_type=reinterpret_cast<void*>(1);a.animation_type=reinterpret_cast<void*>(2);return a;}
int main(int argc,char**argv){assert(argc==2);mode=argv[1];stage.graph={0x2200,8,0};ui.graph={0x3300,9,0};ui.owned=false;
 animators.items={&actor,&stage};legacy.items={&empty_legacy};Result expected=Result::unsupported;
 if(mode=="cast_and_stage")expected=Result::ok;
 if(mode=="disabled_ui"){ui.active=false;animators.items.push_back(&ui);expected=Result::ok;}
 if(mode=="dormant_ui"){ui.valid=false;ui.bound=false;ui.graph={};animators.items.push_back(&ui);expected=Result::ok;}
 if(mode=="active_ui")animators.items.push_back(&ui);
 if(mode=="owned_controller")actor.controller=reinterpret_cast<void*>(0x700);
 if(mode=="owned_unbound")actor.bound=false;
 if(mode=="extra_binding")actor.bindings=false;
 if(mode=="external_graph"){stage.valid=false;stage.graph={};expected=Result::ok;}
 if(mode=="fixed_animator")actor.mode=1;
 if(mode=="unscaled_animator")actor.mode=2;
 if(mode=="invalid_graph")actor.valid=false;
 if(mode=="missing_bound_graph"){actor.valid=false;actor.graph={};actor.bindings=false;}
 if(mode=="dormant_bad_version"){actor.valid=false;actor.bound=false;actor.graph={0,9,0};}
 if(mode=="stateful_legacy")empty_legacy.states=1;
 if(mode=="disabled_legacy"){empty_legacy.states=5;empty_legacy.active=false;expected=Result::ok;}
 if(mode=="invalid_legacy")empty_legacy.states=-1;
 if(mode=="dead_animator"){actor.live=false;expected=Result::stale;}
 if(mode=="dead_legacy"){empty_legacy.live=false;expected=Result::stale;}
 if(mode=="bad_controller"){actor.controller=reinterpret_cast<void*>(0x701);expected=Result::stale;}
 if(mode=="graph_replaced"||mode=="source_changed"||mode=="root_lost"||mode=="legacy_changed")expected=Result::stale;
 if(mode=="query_missing")query=false;
 if(mode=="root_failure")expected=Result::failed;
 GlobalAnimationAdmission admission;auto a=api();if(mode=="api_missing")a.animator_graph=nullptr;
 int context=1;Result result=admission.admit(a,&context);assert(result==expected&&roots==0);
 if(result==Result::ok){assert(admission.summary().owned_animators==2&&admission.summary().legacy==1);}
 return 0;
}
'''
@pytest.fixture(scope='module')
def binary(tmp_path_factory):
 compiler=shutil.which('c++')
 if not compiler:pytest.skip('Host C++ compiler required')
 d=tmp_path_factory.mktemp('mp4-global-animation');s=d/'test.cpp';b=d/'test';s.write_text(HARNESS)
 r=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(NATIVE),str(s),'-o',str(b)],capture_output=True,text=True);assert r.returncode==0,r.stderr
 return b
@pytest.mark.parametrize('mode',['cast_and_stage','disabled_ui','dormant_ui','active_ui','owned_controller','owned_unbound','extra_binding','external_graph','fixed_animator','unscaled_animator','invalid_graph','missing_bound_graph','dormant_bad_version','stateful_legacy','disabled_legacy','invalid_legacy','dead_animator','dead_legacy','bad_controller','graph_replaced','source_changed','root_lost','legacy_changed','query_missing','root_failure','api_missing'])
def test_production_global_animation_admission(binary,mode):
 r=subprocess.run([str(binary),mode],capture_output=True,text=True);assert r.returncode==0,r.stderr
