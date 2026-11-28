#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdlib>
#include <cassert>
#include <array>
#include <map>
#include "history.hpp"
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4world{using AnimationOutput=mp4actor::Handle;struct DirectorGraphIdentity{uintptr_t native=0;};}
struct Method{};struct Mp4SceneWitness{uint64_t generation=7;};
struct Mp4TimelineList{void*owner=nullptr,*list=nullptr,*array=nullptr,*element=nullptr;size_t owner_offset=0,stride=0;int32_t count=0,version=0;uint8_t*data=nullptr;};
struct Mp4TimelineContext{void*director=(void*)1,*asset=(void*)2,*root_script=nullptr;Mp4SceneWitness witness{};mp4world::DirectorGraphIdentity identity{0x1000};mp4actor::Handle graph{100,2,0},root{200,2,0},nodes[8]{},compiled[8]{},runtime_playables[8]{};void*tracks[8]{},*elements[8]{},*clips[8]{},*clip_tracks[8]{},*scripts[8]{};size_t track_count=0,element_count=0,clip_count=0,node_count=0,list_count=0;Mp4TimelineList lists[8]{};};
struct Model{bool current=true,lists=true,path=true,cache=true;int mode=0;int root,tree,runtime,clip,track,callback,notification,target;alignas(8)uint8_t entry[24]{},active[8]{},scratch[8]{},callbacks[8]{},weights[40]{},output_native[0x50]{},output_slot[0x40]{};std::map<std::pair<void*,size_t>,std::array<uint8_t,16>>fields;Mp4TimelineContext context{};}model;
template<class T>void set(void*p,size_t at,T value){auto&bytes=model.fields[{p,at}];std::memcpy(bytes.data(),&value,sizeof(T));}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){auto i=model.fields.find({p,at});if(i==model.fields.end())return false;std::memcpy(&out,i->second.data(),sizeof(T));return true;}
bool mp4_timeline_current(const Mp4TimelineContext&){return model.current;}bool mp4_timeline_lists_current(const Mp4TimelineContext&){return model.lists;}
bool mp4_timeline_field(void*,const char*,size_t){return model.mode!=3;}bool mp4_timeline_dynamic_field(void*p,const char*,size_t*out){if(p!=&model.tree||model.mode==4)return false;*out=16;return true;}bool mp4_timeline_ref(void*p,const char*,size_t,void**out){if(p!=&model.root)return false;*out=&model.tree;return true;}
struct Method;struct Binding{uintptr_t rva=0;};int32_t port(mp4world::AnimationOutput*,Method*);struct{int clip=1,scheduled=2,infinite=3,weight=4,notification=5;Binding output_port{(uintptr_t)port};}mp4_timeline_pins;
bool mp4_timeline_exact(void*p,int pin){return (p==&model.runtime&&pin==2)||(p==&model.callback&&pin==4)||(p==&model.notification&&pin==5);}
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;}
int mp4_timeline_node_index(const Mp4TimelineContext&c,mp4actor::Handle h){for(size_t i=0;i<c.node_count;++i)if(mp4_actor_same_handle(c.nodes[i],h))return i;return -1;}
bool mp4_root_history_path(const Mp4TimelineContext&c,mp4actor::Handle h,mp4_root_history::Path*out){if(!model.path||mp4_timeline_node_index(c,h)<0)return false;*out={};out->present=true;if(h.handle!=c.root.handle){out->length=h.handle==202?2:1;out->slots[0]=h.handle==203?1:0;out->slots[1]=0;}return true;}
bool mp4_source_plan_keep(Mp4TimelineContext&,void*){return model.mode!=5;}bool mp4_root_history_flags(Mp4TimelineContext&,void*,mp4_root_history::View&v){v.tree_dirty=0;v.mute_audio_scrubbing=0;return model.mode!=29;}
bool mp4_root_history_cache(Mp4TimelineContext&,mp4_root_history::View&v,mp4_root_history::List*,size_t*used){*used=0;v.cache_count=1;v.cache_capacity=3;return model.cache;}
uintptr_t image_base=0;int32_t port(mp4world::AnimationOutput*,Method*){return 0;}void*target(mp4world::AnimationOutput*,Method*){return &model.target;}
struct{Binding output_port{(uintptr_t)port};}unused_output_pins;
bool mp4_timeline_output_branch(const Mp4TimelineContext&c,mp4world::AnimationOutput,mp4actor::Handle*out){*out=c.compiled[0];return model.mode!=6;}
int32_t count(mp4actor::Handle*,Method*){return model.mode==7?2049:1;}void get(mp4actor::Handle*,int32_t,mp4world::AnimationOutput*out,Method*){*out={(uintptr_t)model.output_slot,2,0};}void*type(mp4world::AnimationOutput*,Method*){return (void*)(uintptr_t)(model.mode==8?0x999:0x103);}
struct{Binding graph_output_count{(uintptr_t)count},graph_output{(uintptr_t)get},output_type{(uintptr_t)type},output_target{(uintptr_t)target};}mp4_world_profile;
struct{struct{size_t slot_output=0x28;}native_output;}mp4_actor_profile;
uint32_t mp4_output_types[3]={0x101,0x102,0x103};void*weak_get(uint32_t x){return (void*)(uintptr_t)x;}
bool mp4_director_output_source(mp4world::AnimationOutput,mp4actor::Handle*out){*out=model.context.root;return model.mode!=9;}
bool mp4_director_output_userdata(mp4world::DirectorGraphIdentity,uintptr_t,void**out){*out=nullptr;return model.mode!=10;}
namespace idoly_mp4_runtime{struct{size_t selected_audio_track_count(){return 0;}bool selected_audio_track(size_t,void*&,void*&,void*&,void*&){return false;}}game;}
void initialize(){auto&m=model;auto&c=m.context;c.root_script=&m.root;c.track_count=c.element_count=c.clip_count=1;c.node_count=4;c.tracks[0]=&m.track;c.clips[0]=&m.clip;c.clip_tracks[0]=&m.track;c.elements[0]=&m.runtime;c.compiled[0]={201,2,0};c.runtime_playables[0]={202,2,0};c.nodes[0]=c.root;c.nodes[1]=c.compiled[0];c.nodes[2]=c.runtime_playables[0];c.nodes[3]={203,2,0};c.scripts[3]=&m.notification;
 set(&m.root,40,int32_t(1));set(&m.runtime,16,int32_t(1));set(&m.runtime,24,(void*)&m.clip);set(&m.runtime,64,.1);set(&m.runtime,72,.2);set(&m.runtime,80,uint8_t(1));
 int64_t start=1,end=10;std::memcpy(m.entry,&start,8);std::memcpy(m.entry+8,&end,8);void*runtime=&m.runtime,*callback=&m.callback;std::memcpy(m.entry+16,&runtime,8);std::memcpy(m.active,&runtime,8);std::memcpy(m.scratch,&runtime,8);std::memcpy(m.callbacks,&callback,8);
 mp4actor::Handle a{201,2,0},b{200,2,0};std::memcpy(m.weights,&a,16);std::memcpy(m.weights+16,&b,16);set(&m.callback,16,mp4world::AnimationOutput{301,2,0});set(&m.callback,32,a);set(&m.notification,24,2.);set(&m.notification,32,uint8_t(0));set(&m.notification,40,b);
 c.lists[0]={&m.tree,(void*)0x10,(void*)0x11,(void*)0x12,16,24,1,3,m.entry};c.lists[1]={&m.root,(void*)0x20,(void*)0x21,(void*)0x22,24,8,1,3,m.active};c.lists[2]={&m.root,(void*)0x30,(void*)0x31,(void*)0x32,32,8,1,3,m.scratch};c.lists[3]={&m.root,(void*)0x40,(void*)0x41,(void*)0x42,48,8,1,3,m.callbacks};c.lists[4]={&m.callback,(void*)0x50,(void*)0x51,(void*)0x52,48,40,1,3,m.weights};c.list_count=5;
 set(m.output_slot,0x28,(uintptr_t)m.output_native);set(m.output_native,0x40,1.f);set(m.output_native,0x44,int32_t(0));
}
