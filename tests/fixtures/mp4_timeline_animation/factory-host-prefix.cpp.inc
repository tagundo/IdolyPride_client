#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdlib>
#include <cmath>
#include <atomic>
#include <new>
#include <cassert>
#include <map>
#include <string>
#include <vector>
using Method=void;
namespace mp4game {struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}
struct Mp4TimelineTypePin{const char*name=nullptr;mp4game::Binding binding{};};
namespace mp4actor {struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4world {using AnimationGraph=mp4actor::Handle;}
namespace mp4child {using Graph=mp4actor::Handle;}
namespace mp4_source_factory {
struct Ticket{uint64_t serial=0,generation=0;uint16_t depth=0;};
struct Input{uintptr_t asset=0,game_object=0,method=0,return_pc=0;mp4world::AnimationGraph graph{};};
struct Image{uintptr_t graph_native=0;uint32_t graph_version=0;};
struct Context{Ticket ticket{};Input input{};Image image{};};
struct Receipt{Context source{};mp4actor::Handle root{};};
}
namespace mp4_director_birth {struct Receipt{uintptr_t native=0;mp4actor::Handle root{};};}
struct Mp4ChildFactoryContext{
 struct Input{uintptr_t asset=0,game_object=0;mp4child::Graph graph{};}input;
 struct Birth{uint64_t factory_receipt=0,epoch=0;struct Graph{uintptr_t native=0;uint32_t version=0;}graph;}birth;
};
struct Model{bool thread=true,pins=true,ordinary=true,private_context=false,settled=true,private_settled=true,valid_node=true,legacy=false,human=false;size_t events=0;int broken_offset=-1;bool stale=false,static_callback=false,static_missing=false;size_t releases=0;uint32_t next=0;std::map<uint32_t,void*>roots;std::map<void*,uintptr_t>classes;std::vector<std::pair<uintptr_t,size_t>>ranges;
 mp4_source_factory::Context source{};Mp4ChildFactoryContext child{};};
Model model;
uintptr_t image_base=0;
bool game_call(){return model.thread;}
bool mp4_prefix(const mp4game::Binding&){return model.pins;}bool mp4_hook_was_statically_verified(const mp4game::Binding&){return false;}
void*mp4_timeline_class(const Mp4TimelineTypePin&p){return model.pins?reinterpret_cast<void*>(p.binding.rva):nullptr;}
void*object_class(void*p){auto at=model.classes.find(p);return at==model.classes.end()?nullptr:reinterpret_cast<void*>(at->second);}
bool mp4_timeline_exact(void*p,const Mp4TimelineTypePin&t){return p&&object_class(p)==reinterpret_cast<void*>(t.binding.rva);}
bool mp4_alive(void*p){return p&&!model.stale&&model.classes.count(p);}
bool mp4_actor_mapped(const void*p,size_t n,bool){uintptr_t a=reinterpret_cast<uintptr_t>(p);for(auto x:model.ranges)if(a>=x.first&&a+n>=a&&a+n<=x.first+x.second)return true;return false;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&v){if(!p||!mp4_actor_mapped(static_cast<uint8_t*>(p)+at,sizeof(T),false))return false;std::memcpy(&v,static_cast<uint8_t*>(p)+at,sizeof(T));return true;}
bool mp4_root_track_field(void*,const char*,size_t offset){return model.broken_offset!=int(offset);}
bool mp4_type_is(void*p,const char*){return p&&model.classes.count(p);}
uint32_t mp4_retain(void*p){uint32_t h=++model.next;model.roots[h]=p;return h;}void*weak_get(uint32_t h){auto at=model.roots.find(h);return at==model.roots.end()?nullptr:at->second;}void weak_free(uint32_t h){assert(model.roots.erase(h)==1);++model.releases;}
struct Mp4ActorTempRoot{uint32_t h=0;explicit Mp4ActorTempRoot(void*p):h(p?mp4_retain(p):0){}~Mp4ActorTempRoot(){if(h)weak_free(h);}void*get()const{return h?weak_get(h):nullptr;}};
size_t mp4_array_length(void*){return model.events;}
alignas(16) uint8_t events_object[32]{};
void*get_events(void*,Method*){return events_object;}bool get_legacy(void*,Method*){return model.legacy;}bool get_human(void*,Method*){return model.human;}
bool mp4_source_factory_context(mp4world::AnimationGraph g,mp4_source_factory::Context*out){if(!model.ordinary||g.handle!=model.source.input.graph.handle||g.version!=model.source.input.graph.version)return false;*out=model.source;return true;}
bool mp4_source_factory_receipt(mp4_source_factory::Ticket t,mp4_source_factory::Receipt*out){if(!model.settled||t.serial!=model.source.ticket.serial||t.generation!=model.source.ticket.generation||t.depth!=model.source.ticket.depth)return false;*out={model.source,{0xa000,2,0}};return true;}
bool mp4_child_factory_context(mp4child::Graph g,Mp4ChildFactoryContext*out){if(!model.private_context||g.handle!=model.child.input.graph.handle||g.version!=model.child.input.graph.version)return false;*out=model.child;return true;}
bool mp4_child_completed_factory(const Mp4ChildFactoryContext&s,mp4_director_birth::Receipt*out){if(!model.private_settled||s.birth.factory_receipt!=model.child.birth.factory_receipt)return false;*out={s.birth.graph.native,{0xb000,2,0}};return true;}
bool mp4_timeline_actor_graph(mp4actor::Handle node,mp4actor::Handle graph){return model.valid_node&&node.handle&&node.version==2&&graph.handle==0x2000&&graph.version==2;}

void*class_parent(void*){return reinterpret_cast<void*>(1);}const char*class_name(void*){return "TrackAsset";}const char*class_namespace(void*){return "UnityEngine.Timeline";}
void static_get(void*,void*out){void*value=model.static_callback?reinterpret_cast<void*>(1):nullptr;std::memcpy(out,&value,8);}
void*mp4_camera_static_field(void*,const char*,uint32_t kind){return kind==21&&!model.static_missing?reinterpret_cast<void*>(1):nullptr;}
struct{mp4game::Binding field_static_get{reinterpret_cast<uintptr_t>(static_get),{}};}mp4_cam_profile;
