#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdlib>
#include <atomic>
#include <map>
#include <cassert>
#include "/workspace/IdolyPride_client/client-presentation/native/mp4_engine_clock.hpp"
namespace mp4world=idoly_mp4_world;
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4_director_birth{struct Playable{uintptr_t handle=0;uint32_t version=0,padding=0;};struct SourcePins{uintptr_t factory=0,internal_return=0;};}
namespace mp4_source_factory{
struct Object{uintptr_t object=0,klass=0,native=0;uint32_t instance=0;};struct Input{uintptr_t asset=0,game_object=0,method=0,return_pc=0;mp4world::AnimationGraph graph{};};struct Image{Object asset{},game_object{};uintptr_t graph_native=0;uint32_t graph_version=0;};struct Ticket{uint64_t serial=0,generation=0;uint16_t depth=0;};struct Context{Ticket ticket{},parent{};Input input{};Image image{};};struct Receipt{Context source{};mp4_director_birth::Playable root{};};struct Journal{bool find(const Input&,mp4_director_birth::Playable,Receipt*)const;};}
struct Method{};namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};struct Layout{size_t player_director_controller=0,controller_directors=0;};struct PlayableGraph{uintptr_t handle=0;uint32_t version=0,padding=0;};}
struct Mp4SceneWitness{void*player=nullptr,*director=nullptr,*camera_director=nullptr;uint64_t generation=1;};
enum class Mp4TimelineProofPhase:uint8_t{admission=0,active=1,source_bootstrap_plan=4};
struct Mp4AudioProgramImage{};struct{bool active=false;}mp4_scene_host;struct{unsigned depth=0;}mp4_raw_original_operation;
struct{mp4game::Binding get_game_object;}mp4_actor_profile;uintptr_t image_base=0x1000;mp4_director_birth::SourcePins mp4_child_birth_pins{0x1000,0x2000};
std::atomic<bool>mp4_source_factory_configured{true};mp4_source_factory::Journal mp4_source_factory_journal;
struct Root{alignas(8)uint8_t director[24]{},native[0xb0]{},asset[24]{},go[24]{},klass[0x1a8]{},graph[48]{},graph_native[0x100]{};uintptr_t method=0;mp4actor::Handle root{},leaf{};mp4_source_factory::Receipt receipt{};};
struct Model{Root roots[2];void*roster[2]{};void*list=nullptr,*controller=nullptr,*player=nullptr;alignas(8)uint8_t list_image[40]{};Mp4SceneWitness witness{};bool owner=true,phase=true,hooks=true,pins=true,lists=true,bootstrap=false;unsigned next=0,roots_queries=0;int mode=0;std::map<uint32_t,void*>gc;}model;
bool game_call(){return model.owner;}
uint32_t mp4_retain(void*p){if(!p)return 0;if(model.mode==17&&p==model.roots[1].asset)return 0;unsigned id=++model.next;model.gc[id]=p;return id;}
void*weak_get(uint32_t id){auto i=model.gc.find(id);return i==model.gc.end()?nullptr:i->second;}
void weak_free(uint32_t id){assert(model.gc.erase(id)==1);}
struct Mp4ActorTempRoot{uint32_t root;explicit Mp4ActorTempRoot(void*p):root(mp4_retain(p)){}~Mp4ActorTempRoot(){if(root)weak_free(root);}void*get(){return weak_get(root);}};
// ACTUAL_SOURCE_CONTEXT
Root*by_director(void*p){for(auto&r:model.roots)if(r.director==p)return &r;return nullptr;}
Root*by_graph(uintptr_t p){for(auto&r:model.roots)if((uintptr_t)r.graph==p)return &r;return nullptr;}
bool mp4_timeline_source_plan_phase(Mp4TimelineProofPhase p){return p==Mp4TimelineProofPhase::admission||p==Mp4TimelineProofPhase::source_bootstrap_plan;}
bool mp4_timeline_hooks_ready(){return model.hooks;}bool mp4_timeline_pins_current(){return model.pins;}
bool mp4_timeline_phase_witness_current(Mp4TimelineProofPhase phase,const Mp4SceneWitness&w){return mp4_timeline_source_plan_phase(phase)&&(mp4_scene_host.active?model.bootstrap&&phase==Mp4TimelineProofPhase::source_bootstrap_plan:phase==Mp4TimelineProofPhase::admission)&&model.phase&&w.generation==model.witness.generation&&w.player==model.witness.player;}
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.player==b.player&&a.generation==b.generation;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(!p)return false;std::memcpy(&out,(uint8_t*)p+at,sizeof out);return true;}
bool mp4_actor_list(void*p,void***out,size_t*count,size_t){if(p!=model.list)return false;*out=model.roster;*count=model.mode==8?64:2;return true;}
bool mp4_root_track_field(void*,const char*,size_t){return model.mode!=9;}
bool mp4_exact_type(void*p,const char*){return by_director(p)&&!(model.mode==11&&p==model.roots[1].director);}
bool mp4_alive(void*p){return p&&!(model.mode==12&&p==model.roots[1].director);}
bool mp4_prefix(const mp4game::Binding&){return true;}
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;}
void*get_go(void*d,Method*){auto*r=by_director(d);return r?r->go:nullptr;}
void get_graph(void*d,mp4game::PlayableGraph*out,Method*){auto*r=by_director(d);assert(r);*out={(uintptr_t)r->graph,2,0};}
struct{decltype(&get_graph)director_graph_injected=get_graph;}mp4_api;
bool mp4_receipt_graph(mp4actor::Handle g,uintptr_t*native,uint32_t*version){auto*r=by_graph(g.handle);if(!r||model.mode==13)return false;*native=(uintptr_t)r->graph_native;*version=2;return true;}
bool mp4_timeline_current(const Mp4TimelineContext&c){auto*r=by_director(c.director);return r&&model.phase&&c.asset==r->asset&&c.graph.handle==(uintptr_t)r->graph&&c.identity.native==(uintptr_t)r->graph_native;}
bool mp4_timeline_lists_current(const Mp4TimelineContext&){return model.lists;}
bool mp4_timeline_director(Mp4TimelineContext&c){auto*r=by_graph(c.graph.handle);if(!r)return false;c.director=r->director;c.asset=r->asset;return c.keep(c.director)&&c.keep(c.asset)&&c.keep(model.player)&&c.keep(model.controller)&&c.keep(model.list);}
bool mp4_director_graph_nodes(const mp4world::DirectorGraphIdentity&i,mp4actor::Handle*out,size_t,size_t*used){auto*r=by_graph(i.slot);if(!r)return false;*used=model.mode==14?0:2;out[0]=r->root;out[1]=r->leaf;return true;}
int32_t root_count(mp4actor::Handle*,Method*){return model.mode==15?2:1;}
void get_root(mp4actor::Handle*g,int32_t,mp4actor::Handle*out,Method*){*out=by_graph(g->handle)->root;}
struct Api{decltype(&root_count)graph_root_count=root_count;decltype(&get_root)graph_root=get_root;};Api mp4_actor_state_api(){return {};}
void*mp4_timeline_script(mp4actor::Handle h){return (void*)h.handle;}
struct{int root=1;}mp4_timeline_pins;bool mp4_timeline_exact(void*,int){return model.mode!=16;}
bool mp4_timeline_tracks(Mp4TimelineContext&){return model.mode!=18;}
bool mp4_timeline_entries(Mp4TimelineContext&){return model.mode!=19;}
bool mp4_timeline_runtime_elements(Mp4TimelineContext&,bool verify){assert(!verify);return model.mode!=20;}
bool mp4_source_factory_receipt(mp4_source_factory::Ticket ticket,mp4_source_factory::Receipt*out){for(auto&r:model.roots)if(r.receipt.source.ticket.serial==ticket.serial){*out=r.receipt;return true;}return false;}
bool mp4_source_factory::Journal::find(const Input&i,mp4_director_birth::Playable root,Receipt*out)const{
 auto*r=by_graph(i.graph.handle);if(!r||model.mode==21||i.asset!=(uintptr_t)r->asset||i.game_object!=(uintptr_t)r->go||i.method!=(uintptr_t)&r->method
  ||i.return_pc!=image_base+mp4_child_birth_pins.internal_return||root.handle!=r->root.handle||root.version!=r->root.version)return false;
 *out=r->receipt;return true;}
