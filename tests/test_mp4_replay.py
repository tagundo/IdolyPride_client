"""Exercise actual queue replay state machine against an instrumented original UI.

Native handles represent managed roots; the fake original async source and UI
pool expose the lifecycle races that a list of queued encoder options misses.
"""
from pathlib import Path
import json
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]

HARNESS=r'''
#include "mp4_replay.hpp"
#include <cassert>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
using namespace idoly_mp4_replay;
struct Object {
 std::string type,text;bool alive=true,ready=true;
 std::map<std::string,Object*>refs;std::map<std::string,int>values;
 std::vector<Object*>items;
};
struct Host {
 std::vector<std::unique_ptr<Object>>objects;
 std::map<uint32_t,Object*>handles;std::map<Object*,int>roots;
 uint32_t next=1;Object*scene=nullptr,*top=nullptr,*home=nullptr,*old=nullptr,*oldplayer=nullptr,*source=nullptr,*tree=nullptr;
 int ends=0,opens=0,consumed=0,status=0,ctor_params=0,ctor_desc=0,ctor_transition=0;
 bool busy=false,throw_end=false,throw_result=false,fail_field=false,fail_allocation=false;
 uint64_t task_token=0;
 Object*new_obj(const char*type){if(fail_allocation)return nullptr;objects.emplace_back(new Object);objects.back()->type=type;return objects.back().get();}
 Host(){scene=new_obj("Solis.OutGame.OutGameScenePresenter");home=new_obj("Home");old=new_obj("Solis.OutGame.LivePlayerScreenPresenter");oldplayer=new_obj("Solis.Common.SolisLivePlayer");top=old;}
}*h;
Object*o(void*p){return static_cast<Object*>(p);}
bool type(void*p,const char*name){return p&&o(p)->type==name;}
bool alive(void*p){return p&&o(p)->alive;}
uint32_t retain(void*p){if(!p)return 0;uint32_t id=h->next++;h->handles[id]=o(p);++h->roots[o(p)];return id;}
void*retained(uint32_t id){auto it=h->handles.find(id);return it==h->handles.end()?nullptr:it->second;}
void release(uint32_t id){auto it=h->handles.find(id);assert(it!=h->handles.end());assert(h->roots[it->second]>0);--h->roots[it->second];h->handles.erase(it);}
void*new_object(Kind k){return h->new_obj(k==Kind::out_game_param?"OutGameParam":k==Kind::actor_descriptor?"Descriptor":"TransitionParam");}
void*new_string(const char*s){Object*v=h->new_obj("String");if(v)v->text=s;return v;}
void*new_list(void*owner,const char*field){Object*v=h->new_obj("List<String>");if(v)o(owner)->refs[field]=v;return v;}
bool list_add(void*list,void*str){assert(h->roots[o(list)]>0&&h->roots[o(str)]>0);o(list)->items.push_back(o(str));return true;}
bool set_object(void*p,const char*field,void*v){if(h->fail_field)return false;assert(h->roots[o(p)]>0);o(p)->refs[field]=o(v);return true;}
bool set_i32(void*p,const char*field,int32_t v){if(h->fail_field)return false;o(p)->values[field]=v;return true;}
bool set_bool(void*p,const char*field,bool v){return set_i32(p,field,v?1:0);}
void param_ctor(void*p,void*stage,void*timeline,Method*){assert(h->roots[o(p)]>0&&h->roots[o(stage)]>0&&h->roots[o(timeline)]>0);++h->ctor_params;o(p)->refs["stage"]=o(stage);o(p)->refs["timeline"]=o(timeline);}
void descriptor_ctor(void*p,Method*){assert(h->roots[o(p)]>0);++h->ctor_desc;}
void transition_ctor(void*p,Method*){assert(h->roots[o(p)]>0);++h->ctor_transition;}
void add_actor(void*p,void*character,void*descriptor,int32_t audience,int32_t color,int32_t actor,int32_t track,Method*){
 assert(h->roots[o(p)]>0&&h->roots[o(character)]>0&&h->roots[o(descriptor)]>0);
 o(descriptor)->refs["character"]=o(character);o(descriptor)->values["audience"]=audience;o(descriptor)->values["color"]=color;
 o(descriptor)->values["actor"]=actor;o(descriptor)->values["track"]=track;o(p)->items.push_back(o(descriptor));
}
void*scene(Method*){return h->scene;}
bool busy(void*,Method*){return h->busy;}
void*live_state(Method*){return h->new_obj("ScreenState.LivePlayer");}
void*tree_param(void*state,void*param,Method*){Object*t=h->new_obj("TransitionTree");if(t){t->refs["state"]=o(state);t->refs["param"]=o(param);}return t;}
void open_tree(void*s,void*t,void*optional,Method*){assert(s==h->scene&&!optional);++h->opens;h->tree=o(t);assert(h->roots[o(t)]>0);}
void*top(void*,Method*){return h->top;}
UniTask16 end(void*p,CancellationToken8 ct,Method*){
 assert(p==h->old&&!ct.source);++h->ends;if(h->throw_end)throw std::runtime_error("original end failed");
 h->source=h->new_obj("UniTaskSource");++h->task_token;return {h->source,h->task_token};
}
int32_t status(UniTask16*t,Method*){assert(t->source==h->source&&t->token_and_padding==h->task_token&&h->roots[h->source]>0);return h->status;}
UniTask16 get_awaiter(UniTask16*t,Method*){assert(t->source==h->source);return *t;}
void get_result(UniTask16*t,Method*){assert(t->source==h->source&&t->token_and_padding==h->task_token&&h->status>0);++h->consumed;if(h->throw_result)throw std::runtime_error("original task faulted");}
bool ready(void*p,Method*){return p&&o(p)->ready;}
Api api(){Api a{};a.is_type=type;a.alive=alive;a.retain=retain;a.retained=retained;a.release=release;a.new_object=new_object;a.new_string=new_string;a.new_field_list=new_list;a.list_add=list_add;a.set_object=set_object;a.set_i32=set_i32;a.set_bool=set_bool;a.out_game_param_ctor=param_ctor;a.actor_descriptor_ctor=descriptor_ctor;a.transition_param_ctor=transition_ctor;a.param_add_actor=add_actor;a.scene_instance=scene;a.scene_busy=busy;a.live_state=live_state;a.tree_with_param=tree_param;a.open_tree=open_tree;a.top_screen=top;a.presenter_end=end;a.task_status=status;a.task_get_awaiter=get_awaiter;a.task_get_result=get_result;a.player_ready=ready;return a;}
Descriptor descriptor(char letter){Descriptor d{};snprintf(d.stage_asset,sizeof d.stage_asset,"scn_live_%c",letter);snprintf(d.timeline_asset,sizeof d.timeline_asset,"tln_live_%c",letter);d.actor_count=2;d.stage_max_capacity=501;d.detach_actors_on_player_destroyed=1;
 for(unsigned i=0;i<2;++i){auto&a=d.actors[i];snprintf(a.character_id,sizeof a.character_id,"chr_%c_%u",letter,i);snprintf(a.descriptor_name,sizeof a.descriptor_name,"display_%c_%u",letter,i);a.actor_index=int(i);a.track_index=int(3-i);a.audience_amount=111+int(i);a.psyllium_color_type=3+int(i);a.asset_count=2;a.collider_type=1;a.render_layer_base=7+int(i);a.humanoid=1;a.trigger=i;a.auto_blink_disabled=1;a.use_adv_settings=1;snprintf(a.assets[0],sizeof a.assets[0],"mdl_%c_%u",letter,i);snprintf(a.assets[1],sizeof a.assets[1],"costume_%c_%u",letter,i);}
 d.actors[1].name_is_null=1;d.actors[1].descriptor_name[0]=0;assert(idoly_mp4_queue::detail::descriptor(d));return d;}
void verify_constructed(const Descriptor&d){assert(h->tree);Object*t=h->tree->refs["param"],*p=t->refs["liveParam"];assert(p&&p->refs["stage"]->text==d.stage_asset&&p->refs["timeline"]->text==d.timeline_asset&&p->items.size()==d.actor_count);assert(t->values["isDebugMode"]==0&&p->values["stageMaxCapacity"]==d.stage_max_capacity&&p->values["detachActorsOnPlayerDestroyed"]==d.detach_actors_on_player_destroyed);
 for(unsigned i=0;i<d.actor_count;++i){Object*a=p->items[i];const auto&expected=d.actors[i];assert(a->refs["character"]->text==expected.character_id&&a->values["audience"]==expected.audience_amount&&a->values["color"]==expected.psyllium_color_type&&a->values["actor"]==expected.actor_index&&a->values["track"]==expected.track_index);assert(a->refs["_assets"]->items.size()==2&&a->refs["_assets"]->items[1]->text==expected.assets[1]);assert(!a->refs["_gameObjects"]);if(expected.name_is_null)assert(!a->refs["_name"]);else assert(a->refs["_name"]->text==expected.descriptor_name);assert(a->values["_humanoid"]==expected.humanoid&&a->values["_colliderType"]==expected.collider_type&&a->values["_colliderTrigger"]==expected.trigger&&a->values["_autoBlinkDisabled"]==expected.auto_blink_disabled&&a->values["_useADVSettings"]==expected.use_adv_settings&&a->values["_renderingLayerMaskBaseIndex"]==expected.render_layer_base);}
}
int main(int argc,char**argv){assert(argc==2);std::string test=argv[1];Host host;h=&host;Descriptor a=descriptor('a'),b=descriptor('b');{
 Replay r(api());assert(r.observe(h->old,h->oldplayer,a));
 if(test=="route_ready"){
  assert(r.can_route());h->busy=true;assert(!r.can_route());h->busy=false;Object*saved=h->scene;h->scene=nullptr;assert(!r.can_route());h->scene=saved;h->scene->alive=false;assert(!r.can_route());h->scene->alive=true;assert(r.can_route());
 }else if(test=="close_unready"){
  h->oldplayer->ready=false;assert(r.begin(b,0));r.tick(0);r.tick(1);assert(h->ends==0&&h->opens==0&&r.active());h->oldplayer->ready=true;r.tick(2);assert(h->ends==1&&r.phase()==Phase::waiting_for_close);
 }else if(test=="reuse"){
  assert(r.begin(a,10));assert(!r.begin(b,11));a.stage_asset[0]='x';r.tick(11);assert(r.phase()==Phase::ready&&r.presenter()==h->old&&h->ends==0&&h->opens==0);assert(r.reset());
 }else if(test=="distinct"){
  Descriptor frozen=b;assert(r.begin(b,0));b.actors[0].assets[1][0]='x';r.tick(0);assert(r.phase()==Phase::waiting_for_close&&h->ends==1);
  h->top=h->home;r.tick(1);r.tick(2);assert(h->opens==0&&h->ends==1&&h->consumed==0&&h->roots[h->source]>0);
  h->status=1;h->busy=true;r.tick(3);assert(h->consumed==1&&h->opens==0);r.tick(4);assert(h->consumed==1);
  h->busy=false;r.tick(5);assert(r.phase()==Phase::waiting_for_open&&h->opens==1&&h->old->alive);verify_constructed(frozen);
  h->oldplayer->ready=false;h->top=h->old;assert(r.observe(h->old,h->oldplayer,frozen));r.tick(6);assert(r.phase()==Phase::waiting_for_open);h->oldplayer->ready=true;r.tick(7);assert(r.phase()==Phase::ready&&r.player()==h->oldplayer);r.tick(8);assert(h->opens==1&&h->consumed==1);
 }else if(test=="cancel_close"){
  assert(r.begin(b,0));r.tick(0);r.cancel();assert(r.active()&&!r.reset()&&!r.begin(a,1));r.tick(1);assert(h->opens==0);h->status=1;h->top=h->home;r.tick(2);assert(r.phase()==Phase::cancelled&&h->consumed==1&&h->opens==0);assert(r.reset());
 }else if(test=="cancel_open"){
  h->top=h->home;assert(r.begin(b,0));r.tick(0);assert(h->opens==1);r.cancel();assert(r.active());h->top=h->old;h->oldplayer->ready=false;assert(r.observe(h->old,h->oldplayer,b));r.tick(1);assert(r.active());h->oldplayer->ready=true;r.tick(2);assert(r.phase()==Phase::cancelled&&!r.player());
 }else if(test=="cancel_early"){
  assert(r.begin(b,0));r.cancel();assert(r.phase()==Phase::cancelled&&h->ends==0&&h->opens==0);
 }else if(test=="same_pooled"){
  h->top=h->home;assert(r.begin(a,0));r.tick(0);assert(h->opens==1&&h->ends==0);h->top=h->old;r.tick(1);assert(r.phase()==Phase::ready&&r.presenter()==h->old);
 }else if(test=="faulted_task"){
  assert(r.begin(b,0));r.tick(0);h->status=2;h->throw_result=true;r.tick(1);assert(r.phase()==Phase::failed&&h->consumed==1&&h->opens==0);r.tick(2);assert(h->consumed==1&&h->roots[h->source]==0);
 }else if(test=="close_exception"){
  h->throw_end=true;assert(r.begin(b,0));r.tick(0);assert(r.phase()==Phase::failed&&h->ends==1&&h->opens==0);
 }else if(test=="construction_failure"){
  h->top=h->home;h->fail_field=true;assert(r.begin(b,0));r.tick(0);assert(r.phase()==Phase::failed&&h->opens==0&&h->handles.size()==2);
 }else if(test=="allocation_failure"){
  h->top=h->home;h->fail_allocation=true;assert(r.begin(b,0));r.tick(0);assert(r.phase()==Phase::failed&&h->opens==0&&h->handles.size()==2);
 }else if(test=="timeout"){
  assert(r.begin(b,0));r.tick(0);r.tick(60001);assert(r.phase()==Phase::failed&&std::string(r.error())=="previous_mv_close_timeout"&&h->opens==0);
 }else if(test=="suspend_clock"){
  assert(r.begin(b,0));r.tick(0);r.resume_clock(600000);r.tick(600001);assert(r.active()&&h->ends==1);h->status=1;h->top=h->home;r.tick(600002);assert(h->opens==1);
 }else if(test=="wrong_selection"){
  h->top=h->home;assert(r.begin(b,0));r.tick(0);h->top=h->old;assert(r.observe(h->old,h->oldplayer,descriptor('c')));r.tick(1);assert(r.phase()==Phase::failed&&std::string(r.error())=="queue_selection_changed");
 }else if(test=="unready_selected"){
  h->top=h->home;assert(r.begin(b,0));r.tick(0);h->busy=true;h->top=h->old;assert(r.observe(h->old,h->oldplayer,b));r.tick(1);assert(r.active());h->busy=false;h->oldplayer->ready=false;r.tick(2);assert(r.active());h->oldplayer->ready=true;r.tick(3);assert(r.phase()==Phase::ready);
 }else if(test=="invalid"){
  b.actor_count=33;assert(!r.begin(b,0)&&r.phase()==Phase::failed&&h->opens==0);Api broken=api();broken.task_get_result=nullptr;assert(r.set_api(broken)==false);assert(!r.begin(a,1));
 }else assert(false);
 }assert(h->handles.empty());for(auto&kv:h->roots)assert(kv.second==0);
}
'''


@pytest.fixture(scope="module")
def replay_binary(tmp_path_factory):
    compiler=shutil.which("g++") or shutil.which("clang++")
    if not compiler:pytest.skip("C++ compiler unavailable")
    directory=tmp_path_factory.mktemp("mp4-replay")
    source=directory/"replay.cpp";source.write_text(HARNESS)
    binary=directory/"replay"
    subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror","-I",str(ROOT/"client-presentation/native"),str(source),"-o",str(binary)],check=True,capture_output=True,text=True)
    return binary


@pytest.mark.parametrize("case",["route_ready","close_unready","reuse","distinct","cancel_close","cancel_open","cancel_early","same_pooled","faulted_task","close_exception","construction_failure","allocation_failure","timeout","suspend_clock","wrong_selection","unready_selected","invalid"])
def test_original_router_task_and_immutable_scene_contract(replay_binary,case):
    subprocess.run([str(replay_binary),case],check=True,capture_output=True,text=True)


def test_replay_profiles_prove_exact_async_value_layouts_and_public_barrier():
    profiles=[json.loads((ROOT/f"client-presentation/native/mp4_replay_{platform}_profile.json").read_text()) for platform in ("android","ios")]
    for profile in profiles:
        assert profile["methods"]["presenter_end"]["native_abi"]=="UniTask16(void*,CancellationToken8,const MethodInfo*)"
        assert profile["methods"]["task_get_awaiter"]["native_abi"]=="UniTask16(void*,const MethodInfo*)"
        assert profile["methods"]["task_get_result"]["native_abi"]=="void(void*,const MethodInfo*)"
        assert profile["structs"]["UniTask"]["bytes"]==16
        assert profile["structs"]["Awaiter"]["bytes"]==16
        assert profile["structs"]["Awaiter"]["fields"]=={"task":0}
        assert profile["exports"]["field_set_value"]["export"]=="il2cpp_field_set_value"
        assert profile["exports"]["field_set_value"]["has_method_info_argument"] is False
        assert profile["scope"]["original_screen_router"] is True
        assert profile["scope"]["runtime_verified"] is False
    assert set(profiles[0]["methods"])==set(profiles[1]["methods"])
    assert {key:row["offset"] for key,row in profiles[0]["fields"].items()}=={key:row["offset"] for key,row in profiles[1]["fields"].items()}
