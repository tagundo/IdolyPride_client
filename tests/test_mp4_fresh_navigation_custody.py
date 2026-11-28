"""Join the actual Photo navigation producer to the actual Fresh Replay owner.

Only managed objects, original task calls and SceneLoad are host leaves. The
receipt's state 3 comes from the shipping status/GetResult cancellation path.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

from test_mp4_native_boundary import definition
from test_mp4_photography_navigation import PRELUDE, AFTER_STRUCTS, function
from test_mp4_replay import HARNESS as REPLAY_FIXTURE


ROOT = Path(__file__).resolve().parents[1]


DRIVER = r'''
using namespace idoly_mp4_replay;
// SHIPPING_DESCRIPTOR_FIXTURE
idoly_mp4_replay::Api joined_api(){
 idoly_mp4_replay::Api a{};a.is_type=mp4_type_is;a.alive=mp4_alive;a.retain=mp4_retain;a.retained=weak_get;a.release=weak_free;
 a.new_object=[](Kind)->void*{assert(false);return nullptr;};a.new_string=[](const char*)->void*{assert(false);return nullptr;};
 a.new_field_list=[](void*,const char*)->void*{assert(false);return nullptr;};a.list_add=[](void*,void*){assert(false);return false;};
 a.set_object=[](void*,const char*,void*){assert(false);return false;};a.set_i32=[](void*,const char*,int32_t){assert(false);return false;};a.set_bool=[](void*,const char*,bool){assert(false);return false;};
 a.out_game_param_ctor=[](void*,void*,void*,Method*){assert(false);};a.actor_descriptor_ctor=[](void*,Method*){assert(false);};a.transition_param_ctor=a.actor_descriptor_ctor;
 a.param_add_actor=[](void*,void*,void*,int32_t,int32_t,int32_t,int32_t,Method*){assert(false);};
 a.scene_instance=[](Method*)->void*{return nullptr;};a.scene_busy=[](void*,Method*){return true;};
 a.live_state=[](Method*)->void*{assert(false);return nullptr;};a.tree_with_param=[](void*,void*,Method*)->void*{assert(false);return nullptr;};
 a.open_tree=[](void*,void*,void*,Method*){assert(false);};a.top_screen=[](void*,Method*)->void*{return nullptr;};
 a.presenter_end=[](void*,CancellationToken8,Method*)->UniTask16{assert(false);return {};};
 a.task_status=[](UniTask16*,Method*)->int32_t{assert(false);return 0;};a.task_get_awaiter=[](UniTask16*,Method*)->UniTask16{assert(false);return {};};a.task_get_result=[](UniTask16*,Method*){assert(false);};
 a.player_ready=[](void*p,Method*){return mp4_alive(p);};
 a.photography_can_route=mp4_photography_can_route;a.photography_open=mp4_photography_open;a.photography_cancel=mp4_photography_cancel;
 a.photography_error=[]()->const char*{return mp4_photography_navigation.error;};
 a.photography_current=[](void*p,void*v){return p==mp4_photography_presenter.get()&&v==idoly_mp4_runtime::game.selected_player();};
 a.photography_navigation_receipt=mp4_photography_navigation_receipt;return a;
}
int main(int argc,char**argv){
 assert(argc==2);const std::string scenario=argv[1];setup();Descriptor target=photo_descriptor('a');
 Replay replay(joined_api());uint64_t serial=99,identity=99;void*player=reinterpret_cast<void*>(99);
 assert(!replay.fresh_request_scope(&serial,&identity,&player)&&!serial&&!identity&&!player);
 assert(replay.begin(target,0,true));replay.tick(0);
 assert(replay.phase()==Phase::waiting_for_open&&preload_calls==1&&!load_calls&&!result_calls);
 const auto issued=mp4_photography_navigation_receipt();assert(issued.serial&&issued.state==1);
 assert(replay.fresh_request_scope(&serial,&identity,&player)&&serial&&!identity&&!player);const auto request=serial;
 assert(!replay.fresh_request(target,12,&serial)&&!serial); // No actual SceneLoad yet.
 if(scenario=="cancel_pending"||scenario=="cancel_pending_foreign_receipt"){
  replay.cancel();assert(mp4_photography_navigation.cancel_requested);
  for(int i=0;i<3;++i){mp4_advance_photography_navigation();replay.tick(i+1);assert(replay.active()&&!replay.reset());
   assert(replay.fresh_request_scope(&serial,&identity,&player)&&serial==request&&!identity&&!player);
   assert(last_source->alive&&!result_calls&&!load_calls&&mp4_photography_navigation_receipt().state==1);}
  finish(1,true);mp4_advance_photography_navigation();assert(result_calls==1&&awaiter_calls==1&&!load_calls);
  const auto consumed=mp4_photography_navigation_receipt();assert(consumed.serial==issued.serial&&consumed.state==3);
  if(scenario=="cancel_pending_foreign_receipt"){
   ++mp4_photography_navigation.request_serial;assert(replay.fresh_request_scope(&serial,&identity,&player)&&serial==request);
   mp4_photography_navigation.request_serial=issued.serial;
  }
  assert(!replay.fresh_request_scope(&serial,&identity,&player)&&!serial&&!identity&&!player);
  replay.tick(5);assert(replay.phase()==Phase::cancelled&&replay.reset());
 }else{
  assert(scenario=="scene_load_cancel_clear"||scenario=="ready_selected_clear");
  finish(1,true);mp4_advance_photography_navigation();const auto dispatched=mp4_photography_navigation_receipt();
  assert(dispatched.serial==issued.serial&&dispatched.state==2&&load_calls==1&&result_calls==1);
  if(scenario=="scene_load_cancel_clear"){
   replay.cancel();for(int i=0;i<3;++i){mp4_advance_photography_navigation();replay.tick(i+1);
    assert(replay.fresh_request_scope(&serial,&identity,&player)&&serial==request&&!identity&&!player&&replay.active()&&!replay.reset());}
  }
  Class actual_player_class{"Solis.Common.Photography.PhotographyLive3DPresenter"};
  Object*actual_player=allocate(&actual_player_class,"actual-fresh-player");engine_roots.push_back(actual_player);
  Object*actual_presenter=static_cast<Object*>(mp4_photography_presenter.get());
  idoly_mp4_runtime::game.selected=actual_player;original_built_generation(true,true);
  assert(!mp4_photography_navigation.pending&&replay.observe(actual_presenter,actual_player,target,12));
  assert(replay.fresh_request(target,12,&serial)&&serial==request);replay.tick(8);
  assert(replay.phase()==(scenario=="scene_load_cancel_clear"?Phase::cancelled:Phase::ready));
  assert(replay.fresh_request_scope(&serial,&identity,&player)&&serial==request&&identity==12&&player==actual_player);
  // The UI now clears its selected pointer, then observes another initializer.
  // Only the exact request-owned GC root may retain the former fresh player.
  idoly_mp4_runtime::game.selected=nullptr;engine_roots.clear();collect();
  assert(actual_player->alive&&replay.fresh_request_scope(&serial,&identity,&player)&&player==actual_player);
  Object*foreign_player=allocate(&actual_player_class,"foreign-player");engine_roots.push_back(foreign_player);
  assert(replay.observe(actual_presenter,foreign_player,target,13));collect();
  assert(actual_player->alive&&replay.fresh_request_scope(&serial,&identity,&player)&&identity==12&&player==actual_player);
  assert(!replay.fresh_request(target,13,&serial)&&!serial&&!replay.retain_fresh_request_player(foreign_player,13));
  assert(replay.reset());collect();assert(!actual_player->alive);
 }
 assert(!replay.fresh_request_scope(&serial,&identity,&player)&&!serial&&!identity&&!player);
 mp4_release_photography_navigation_inputs();factory.clear();engine_roots.clear();collect();assert(handles.empty());
}
'''


@pytest.fixture(scope="module")
def joined_navigation_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler required")
    source = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    structs = source.split("struct Mp4PhotographyBoolTask", 1)[1].split("char mp4_photography_binding_error", 1)[0]
    navigation = source.split("// BEGIN_MP4_PHOTOGRAPHY_NAVIGATION", 1)[1].split("// END_MP4_PHOTOGRAPHY_NAVIGATION", 1)[0]
    bodies = "\n".join(function(source, name) for name in (
        "mp4_photography_navigation_receipt", "mp4_observe_photography_presenter", "mp4_unity_tick"))
    descriptors = "\n".join(definition(REPLAY_FIXTURE, name) for name in (
        "Descriptor descriptor(char letter)", "Descriptor photo_descriptor(char letter)"))
    body = PRELUDE + "\nstruct Mp4PhotographyBoolTask" + structs + navigation + bodies
    body += AFTER_STRUCTS.split("int main(", 1)[0]
    body += DRIVER.replace("// SHIPPING_DESCRIPTOR_FIXTURE", descriptors)
    directory = tmp_path_factory.mktemp("fresh-navigation-custody")
    cpp, binary = directory / "joined.cpp", directory / "joined"
    cpp.write_text(body)
    result = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation",
                             "-I", str(ROOT / "client-presentation/native"), str(cpp), "-o", str(binary)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("scenario", ["cancel_pending", "cancel_pending_foreign_receipt", "scene_load_cancel_clear", "ready_selected_clear"])
def test_actual_navigation_receipt_and_fresh_request_custody(joined_navigation_binary, scenario):
    result = subprocess.run([str(joined_navigation_binary), scenario], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
