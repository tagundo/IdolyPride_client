"""Execute actual bridge global ActorSwing roster admission on a modeled heap.

No Unity scene, worker execution, original native loop or GPU is claimed here.
The separately pinned original getter/loop ARM tests cover their CPU boundary.
"""
from pathlib import Path
import shutil,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'client-presentation/native'

def function(source,signature):
 start=source.index(signature);opening=source.index('{',start);depth=1;end=opening+1
 while depth:depth+=(source[end]=='{')-(source[end]=='}');end+=1
 return source[start:end]

@pytest.fixture(scope='module')
def roster(tmp_path_factory):
 compiler=shutil.which('c++')
 if not compiler:pytest.skip('Host C++ compiler required')
 source=(NATIVE/'bridge.cpp').read_text()
 root='struct Mp4WorldQueryRoot {'+source.split('struct Mp4WorldQueryRoot {',1)[1].split('};',1)[0]+'};'
 actual='\n'.join(function(source,s)for s in['template<class T> bool mp4_actor_field(','bool mp4_actor_list(','bool mp4_world_actor_jobs_closed('])
 prefix=r'''
#include "mp4_engine_clock.hpp"
#include "mp4_game_adapter.hpp"
#include <array>
#include <cassert>
#include <map>
#include <memory>
#include <string>
#include <vector>
namespace mp4game=idoly_mp4_game;
using Method=const void;
struct Object{alignas(16)std::array<unsigned char,4096>memory{};std::string type;bool live=true,active=true;void* object=nullptr;};
std::vector<std::unique_ptr<Object>> heap;std::map<void*,Object*>objects;
void*make(const char*type){auto object=std::make_unique<Object>();object->type=type;void*raw=object->memory.data();objects[raw]=object.get();heap.push_back(std::move(object));return raw;}
template<class T>void put(void*p,size_t at,T value){memcpy(static_cast<unsigned char*>(p)+at,&value,sizeof(value));}
template<class T>T get(void*p,size_t at){T value{};memcpy(&value,static_cast<unsigned char*>(p)+at,sizeof(value));return value;}
bool mp4_actor_mapped(const void*p,size_t bytes,bool){uintptr_t a=reinterpret_cast<uintptr_t>(p);for(auto&item:heap){uintptr_t b=reinterpret_cast<uintptr_t>(item->memory.data());if(a>=b&&bytes<=4096&&a-b<=4096-bytes)return true;}return false;}
std::string mode;bool current=true,routes=true,mutation=false,lose_root=false;unsigned registry_calls=0;
void*actors=nullptr;void*other_actors=nullptr;void*cast=nullptr;void*extensions=nullptr;void*owned_actor=nullptr;void*foreign_actor=nullptr;
std::map<uint32_t,void*>roots;uint32_t nextroot=1;
uint32_t mp4_retain(void*p){if(!p||mode=="root_failed")return 0;if(mode=="extension_changed"&&p==extensions){put(p,0x1c,get<int32_t>(p,0x1c)+1);mutation=true;}roots[nextroot]=p;return nextroot++;}
void*weak_get(uint32_t n){auto it=roots.find(n);return it==roots.end()||(lose_root&&it->second==actors)?nullptr:it->second;}
void weak_free(uint32_t n){roots.erase(n);}
bool mp4_type_is(void*p,const char*n){auto it=objects.find(p);if(it==objects.end())return false;return it->second->type==n;}
bool mp4_alive(void*p){auto it=objects.find(p);return it!=objects.end()&&it->second->live;}
size_t mp4_array_length(void*p){return get<uintptr_t>(p,0x18);}
void*mp4_array_data(void*p){return static_cast<unsigned char*>(p)+0x20;}
void*list(std::initializer_list<void*>items){void*array=make("System.Array");put(array,0x18,uintptr_t(items.size()));size_t i=0;for(void*p:items)put(array,0x20+i++*sizeof(void*),p);void*value=make("System.Collections.Generic.List`1");put(value,0x10,array);put(value,0x18,int32_t(items.size()));put(value,0x1c,int32_t(17));return value;}
void*actor(bool swing){void*value=make("VL.Core.VLActorController");void*object=make("UnityEngine.GameObject");objects[value]->object=object;void*extension_list=swing?list({make("VL.VLActorActorSwing")}):list({});put(value,0x40,extension_list);return value;}
struct Host{struct Source{void*player=nullptr;}source;}mp4_world_host;
auto mp4_world_profile=idoly_mp4_world::android_world_profile;uintptr_t image_base=0;
bool mp4_world_source_current(void*){return current;}
bool mp4_world_routes(){return routes;}
void*registry(Method*){++registry_calls;return mode=="registry_replaced"&&registry_calls>1?other_actors:actors;}
void*game_object(void*actor,Method*){return objects.at(actor)->object;}
bool active(void*object,Method*){
 if(!mutation){mutation=true;
  if(mode=="registry_changed")put(actors,0x1c,get<int32_t>(actors,0x1c)+1);
  if(mode=="cast_changed")put(cast,0x1c,get<int32_t>(cast,0x1c)+1);
  if(mode=="source_changed")current=false;
  if(mode=="root_lost")lose_root=true;
 }
 return objects.at(object)->active;
}
'''
 driver=r'''
int main(int argc,char**argv){assert(argc==2);mode=argv[1];
 owned_actor=actor(true);foreign_actor=actor(mode!="foreign_without_swing");
 extensions=get<void*>(owned_actor,0x40);
 cast=list({owned_actor});actors=list({owned_actor,foreign_actor});other_actors=list({owned_actor,foreign_actor});
 void*player=make("Solis.Common.Live.SolisLivePlayerBase");void*binder=make("Solis.Common.Live.SolisLiveBinder");
 put(player,mp4game::Layout{}.player_binder,binder);put(binder,mp4game::Layout{}.binder_actors,cast);mp4_world_host.source.player=player;
 objects[objects[foreign_actor]->object]->active=mode=="foreign_active"||mode=="foreign_without_swing";
 if(mode=="dead_actor")objects[owned_actor]->live=false;
 if(mode=="dead_object")objects[objects[owned_actor]->object]->live=false;
 if(mode=="bad_extensions")put(owned_actor,0x40,player);
 if(mode=="no_source")current=false;
 if(mode=="no_routes")routes=false;
 mp4_world_profile.actor_registry.rva=reinterpret_cast<uintptr_t>(&registry);
 mp4_world_profile.game_object.rva=reinterpret_cast<uintptr_t>(&game_object);
 mp4_world_profile.active_hierarchy.rva=reinterpret_cast<uintptr_t>(&active);
 bool result=mp4_world_actor_jobs_closed(nullptr);
 const bool expected=mode=="owned_and_inactive_home"||mode=="foreign_without_swing";
 assert(result==expected);assert(roots.empty());
 return 0;
}
'''
 d=tmp_path_factory.mktemp('mp4-world-host');s=d/'host.cpp';b=d/'host';s.write_text(prefix+'\n'+root+'\n'+actual+'\n'+driver)
 r=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(NATIVE),str(s),'-o',str(b)],capture_output=True,text=True)
 assert r.returncode==0,r.stderr
 return b

@pytest.mark.parametrize('mode',['owned_and_inactive_home','foreign_active','foreign_without_swing','registry_replaced','registry_changed','cast_changed','extension_changed','source_changed','root_lost','root_failed','dead_actor','dead_object','bad_extensions','no_source','no_routes'])
def test_production_global_roster_closure(roster,mode):
 r=subprocess.run([str(roster),mode],capture_output=True,text=True)
 assert r.returncode==0,r.stderr
