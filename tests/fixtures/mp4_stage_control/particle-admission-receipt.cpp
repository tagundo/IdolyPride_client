#include <cassert>
#include <atomic>
#include <thread>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <map>
#include <string>
#include <vector>
using Method=void;
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4game{using PlayableGraph=mp4actor::Handle;}
struct Mp4SceneWitness{void*presenter=nullptr,*player=nullptr,*director=nullptr,*controller=nullptr,*camera=nullptr,*brain=nullptr,*bgm=nullptr,*voice=nullptr,*environment=nullptr,*camera_director=nullptr,*camera_asset=nullptr,*camera_track=nullptr;uint64_t generation=0;};
struct Mp4StagePath{uint16_t director=0,root=0,length=0,inputs[64]{};};
namespace mp4stage{constexpr size_t max_particles=256;struct Owner{void*particle=nullptr,*producer=nullptr;uint8_t producer_kind=0;};struct Layout{static constexpr size_t control_particle=16,control_random_seed=24,live_particle_system=24;};}
enum Type:uint64_t{unknown,particle,go,director,asset,script,equipment};
struct Native{uint64_t pad=0;int32_t id=1;uint32_t pad2=0;};
struct Obj{uint64_t kind=unknown,monitor=0;Native*native=nullptr;void*target=nullptr;mp4actor::Handle graph{};};
struct Script{uint64_t kind=script,monitor=0;void*particle=nullptr;uint32_t seed=7,pad=0;};
struct Node{mp4actor::Handle value{};void*script=nullptr;std::vector<uintptr_t>inputs;};
std::map<uintptr_t,Node>nodes;
struct StageHost{Mp4SceneWitness source{};mp4stage::Owner owners[256]{};void*current_producers[256]{},*producer_particles[256]{};uint32_t source_seeds[256]{};Mp4StagePath control_paths[256]{};size_t count=0,director_count=0;void*directors[64]{},*director_assets[64]{};uint64_t timeline_receipts[64]{};mp4actor::Handle graph_receipts[64]{};bool admitting=false,configured=false,rebuilding=false,graph_receipt=false;}mp4_stage_host;
Native natives[12];Obj objects[8];Script scripts[2];Obj producer_equipment;Mp4SceneWitness selected;
size_t release_calls=0;bool withdraw_during_retain=false;
bool game=true,source_ok=true,held=true,stage_owner=true,controls_ok=true,roots_ok=true,retain_ok=true;
bool mp4_source_verified=true,mp4_stage_source_verified=true;
uint64_t fingerprints[2]{61,62};size_t old_graph_queries=0;uint32_t root_sequence=0;std::map<uint32_t,void*>roots;
bool game_call(){return game;}
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation&&a.generation==b.generation&&a.presenter==b.presenter&&a.player==b.player&&a.director==b.director&&a.controller==b.controller&&a.camera==b.camera&&a.brain==b.brain&&a.bgm==b.bgm&&a.voice==b.voice&&a.environment==b.environment&&a.camera_director==b.camera_director&&a.camera_asset==b.camera_asset&&a.camera_track==b.camera_track;}
namespace idoly_mp4_runtime{struct Game{bool selected_scene_witness(Mp4SceneWitness&w){w=selected;return source_ok;}}game;}
void mp4_stage_admission_withdraw() noexcept;
uint32_t mp4_retain(void*p){if(withdraw_during_retain){withdraw_during_retain=false;mp4_stage_admission_withdraw();}if(!retain_ok)return 0;roots[++root_sequence]=p;return root_sequence;}
void*weak_get(uint32_t h){auto i=roots.find(h);return roots_ok&&i!=roots.end()?i->second:nullptr;}
void weak_free(uint32_t h){assert(game);++release_calls;assert(roots.erase(h)==1);}
bool mp4_type_is(void*p,const char*type){if(!p)return false;auto k=*static_cast<uint64_t*>(p);return !std::strcmp(type,"UnityEngine.ParticleSystem")?k==particle:!std::strcmp(type,"Solis.Live.Equipment.Environment.LiveParticleEffect")?k==equipment:false;}
bool mp4_alive(void*p){if(!p)return false;auto&o=*static_cast<Obj*>(p);return o.native&&o.native->id!=0;}
template<class T>bool mp4_actor_field(void*p,size_t offset,T&out){if(!p)return false;std::memcpy(&out,static_cast<uint8_t*>(p)+offset,sizeof(T));return true;}
struct{int particle=1;}mp4_stage_other_pins;
bool mp4_timeline_exact(void*p,int){return p&&*static_cast<uint64_t*>(p)==script;}
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;}
struct GameApi{
 void*component_game_object(void*p,Method*){return static_cast<Obj*>(p)->target;}
 void*director_get_asset(void*p,Method*){return static_cast<Obj*>(p)->target;}
 void director_graph_injected(void*p,mp4game::PlayableGraph*out,Method*){*out=static_cast<Obj*>(p)->graph;}
}mp4_api;
void*get_script(mp4actor::Handle*n,Method*){return nodes[n->handle].script;}
uintptr_t image_base=reinterpret_cast<uintptr_t>(&get_script);
struct{struct{uintptr_t rva=0;}playable_script;}mp4_stage_profile;
struct ActorApi{
 bool graph_valid(mp4actor::Handle*g,Method*){for(size_t d=0;d<2;++d)if(mp4_actor_same_handle(objects[4+d].graph,*g))return true;++old_graph_queries;return false;}
 int32_t graph_root_count(mp4actor::Handle*,Method*){return 1;}
 void graph_root(mp4actor::Handle*g,int32_t,mp4actor::Handle*out,Method*){*out=nodes[100+(g->handle-10)].value;}
 bool playable_valid(mp4actor::Handle*n,Method*){auto i=nodes.find(n->handle);return i!=nodes.end()&&mp4_actor_same_handle(i->second.value,*n);}
 int32_t playable_input_count(mp4actor::Handle*n,Method*){return static_cast<int32_t>(nodes[n->handle].inputs.size());}
 void playable_input(mp4actor::Handle*n,int32_t index,mp4actor::Handle*out,Method*){*out=nodes[nodes[n->handle].inputs[index]].value;}
};
ActorApi mp4_actor_state_api(){return {};}
bool mp4_stage_tracks(void*a,void*,uint64_t&hash){for(size_t i=0;i<2;++i)if(a==&objects[6+i]){hash=fingerprints[i];return true;}return false;}
bool mp4_stage_owner(void*){return stage_owner&&mp4_scene_same_source(mp4_stage_host.source,selected);}
bool mp4_stage_clock_held(void*){return held;}
bool mp4_stage_control_current(void*,const mp4stage::Owner&o){if(o.producer_kind==2)return static_cast<Obj*>(o.producer)->target==o.particle;auto*s=static_cast<Script*>(o.producer);return s->particle==o.particle;}
bool mp4_stage_graph_controls(void**out,uint32_t*seed){if(!controls_ok)return false;for(size_t i=0;i<mp4_stage_host.count;++i)if(mp4_stage_host.owners[i].producer_kind==1){out[i]=mp4_stage_host.current_producers[i];seed[i]=static_cast<Script*>(out[i])->seed;}return true;}
#include "particle-admission-receipt-host.cpp"
void setup(){for(size_t i=0;i<12;++i)natives[i].id=int32_t(i+1);for(size_t i=0;i<8;++i)objects[i].native=&natives[i];
 for(size_t i=0;i<2;++i){objects[i].kind=particle;objects[i].target=&objects[2+i];objects[2+i].kind=go;objects[4+i].kind=director;objects[4+i].target=&objects[6+i];objects[4+i].graph={10+i,1,0};objects[6+i].kind=asset;scripts[i].particle=&objects[i];scripts[i].seed=7+uint32_t(i);nodes[100+i]={{100+i,1,0},nullptr,{200+i}};nodes[200+i]={{200+i,1,0},&scripts[i],{}};}
 selected={&objects[2],&objects[3],&objects[4],nullptr,&objects[2],nullptr,nullptr,nullptr,&objects[3],nullptr,nullptr,nullptr,9};
 auto&h=mp4_stage_host;h.source=selected;h.count=2;h.director_count=2;h.admitting=true;h.graph_receipt=true;
 for(size_t i=0;i<2;++i){h.owners[i]={&objects[i],&scripts[i],1};h.current_producers[i]=&scripts[i];h.source_seeds[i]=7+uint32_t(i);h.control_paths[i].director=uint16_t(i);h.control_paths[i].length=1;h.directors[i]=&objects[4+i];h.director_assets[i]=&objects[6+i];h.timeline_receipts[i]=fingerprints[i];h.graph_receipts[i]=objects[4+i].graph;}
}
bool classify(){return mp4_stage_admission_particle(selected,&objects[4],&objects[6],objects[4].graph,nodes[200].value,&scripts[0],&objects[0],7);}
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];setup();
 if(mode=="equipment"||mode=="equipment_root_changed"){
 producer_equipment.kind=equipment;producer_equipment.native=&natives[11];producer_equipment.target=&objects[1];
 mp4_stage_host.owners[1]={&objects[1],&producer_equipment,2};mp4_stage_host.current_producers[1]=&producer_equipment;mp4_stage_host.producer_particles[1]=&objects[1];mp4_stage_host.director_count=1;
 }
 auto saved=mp4_stage_host;
 if(mode=="begin_source"){source_ok=false;assert(!mp4_stage_admission_begin(selected));}
 else if(mode=="sequence_exhausted"){mp4_stage_admission_particle_sequence=~uint64_t(0);assert(!mp4_stage_admission_begin(selected));}
 else if(mode=="begin_withdraw_race"){withdraw_during_retain=true;assert(!mp4_stage_admission_begin(selected)&&roots.empty());}
 else if(mode=="begin_retain"){retain_ok=false;assert(!mp4_stage_admission_begin(selected)&&roots.empty());}
 else {
 const auto attempt=mp4_stage_admission_begin(selected);assert(attempt&&!classify());
 if(mode=="duplicate")mp4_stage_host.owners[1]=mp4_stage_host.owners[0],mp4_stage_host.current_producers[1]=&scripts[0];
 if(mode=="observe_no_controls")controls_ok=false;
 if(mode=="observe_no_owner")stage_owner=false;
 if(mode=="observe_no_graph")mp4_stage_host.graph_receipt=false;
 if(mode=="observe_retain")retain_ok=false;
 bool observed=mp4_stage_admission_observe(attempt,selected);
 if(mode=="duplicate"||mode.rfind("observe_",0)==0){assert(!observed);assert(!mp4_stage_admission_seal(attempt,false)&&roots.empty());}
 else {
 assert(observed&&!classify());
 if(mode=="seal_failure"){assert(!mp4_stage_admission_seal(attempt,false)&&roots.empty());}
 else if(mode=="seal_before_cleanup"){assert(!mp4_stage_admission_seal(attempt,true)&&roots.empty());}
 else if(mode=="wrong_attempt"){assert(!mp4_stage_admission_seal(attempt+1,true)&&roots.empty());}
 else {
 mp4_stage_host={}; // Actual readonly-admit temporary Stage cleanup.
 assert(mp4_stage_admission_seal(attempt,true)&&classify()&&!roots.empty());
 if(mode=="source_change"){++selected.generation;assert(!classify()&&roots.empty());}
 else if(mode=="same_generation_source_change"){selected.presenter=&objects[0];assert(!classify()&&roots.empty());}
 else if(mode=="offthread_source"||mode=="offthread_drop"||mode=="offthread_particle"||mode=="scalar_withdraw"||mode=="offthread_begin"||mode=="offthread_seal"||mode=="concurrent_observer"){
 const auto held_roots=roots.size(),released=release_calls;
 if(mode=="scalar_withdraw")mp4_stage_admission_withdraw();
 else if(mode=="concurrent_observer"){std::thread observer([]{for(size_t i=0;i<128;++i)mp4_stage_admission_withdraw();});observer.join();}
 else {game=false;if(mode=="offthread_source")assert(!mp4_stage_admission_source(selected));else if(mode=="offthread_drop")mp4_stage_admission_drop();else if(mode=="offthread_begin")assert(!mp4_stage_admission_begin(selected));else if(mode=="offthread_seal")assert(!mp4_stage_admission_seal(attempt,true));else assert(!classify());game=true;}
 assert(roots.size()==held_roots&&release_calls==released);assert(!classify()&&roots.empty());
 }
 else if(mode=="weak_lost"){roots_ok=false;assert(!classify()&&roots.empty());roots_ok=true;}
 else if(mode=="native_changed"){objects[0].native=&natives[10];assert(!classify());}
 else if(mode=="instance_changed"){natives[0].id=50;assert(!classify());}
 else if(mode=="go_changed"){objects[0].target=&objects[3];assert(!classify());}
 else if(mode=="go_native_changed"){objects[2].native=&natives[10];assert(!classify());}
 else if(mode=="producer_target_changed"){scripts[0].particle=&objects[1];assert(!classify());}
 else if(mode=="seed_changed"){scripts[0].seed=8;assert(!classify());}
 else if(mode=="graph_changed"){objects[4].graph.version=2;assert(!classify()&&old_graph_queries==0);}
 else if(mode=="asset_changed"){objects[4].target=&objects[7];assert(!classify());}
 else if(mode=="asset_fingerprint_changed"){++fingerprints[0];assert(!classify());}
 else if(mode=="path_changed"){nodes[100].inputs[0]=201;assert(!classify());}
 else if(mode=="script_changed"){nodes[200].script=&scripts[1];assert(!classify());}
 else if(mode=="wrong_node"){assert(!mp4_stage_admission_particle(selected,&objects[4],&objects[6],objects[4].graph,nodes[201].value,&scripts[0],&objects[0],7));}
 else if(mode=="wrong_director"){assert(!mp4_stage_admission_particle(selected,&objects[5],&objects[6],objects[4].graph,nodes[200].value,&scripts[0],&objects[0],7));}
 else if(mode=="wrong_asset"){assert(!mp4_stage_admission_particle(selected,&objects[4],&objects[7],objects[4].graph,nodes[200].value,&scripts[0],&objects[0],7));}
 else if(mode=="new_admit"){assert(mp4_stage_admission_begin(selected)>attempt&&!classify());}
 else {
 mp4_stage_host=saved;mp4_stage_host.admitting=false;mp4_stage_host.configured=true;
 if(mode=="equipment_root_changed")producer_equipment.target=&objects[0];
 if(mode=="capture_unheld")held=false;
 if(mode=="capture_count")--mp4_stage_host.count;
 if(mode=="capture_extra")++mp4_stage_host.count;
 if(mode=="capture_kind")mp4_stage_host.owners[0].producer_kind=2;
 if(mode=="capture_owner")mp4_stage_host.owners[0].particle=&objects[1];
 if(mode=="capture_path")mp4_stage_host.control_paths[0].inputs[0]=1;
 if(mode=="capture_director")mp4_stage_host.directors[0]=&objects[5];
 if(mode=="capture_graph")++mp4_stage_host.graph_receipts[0].version;
 if(mode=="capture_seed")++mp4_stage_host.source_seeds[0];
 if(mode=="capture_root_owner")stage_owner=false;
 bool capture=mode.rfind("capture_",0)!=0&&mode!="equipment_root_changed";assert(mp4_stage_admission_before_capture(selected)==capture);
 }
 }
 }
 }
 mp4_stage_admission_drop();assert(roots.empty());
}
