#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdlib>
#include <cassert>
#include <map>
#include <string>
#include "history.hpp"
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
struct Class{const char*space=nullptr,*name=nullptr;size_t stride=0;bool value=false;Class*element=nullptr;};
struct Field{size_t offset=0;Class*type=nullptr;};struct Object{Class*klass=nullptr;};
struct Array{Class*klass=nullptr;uint8_t bytes[128]{};size_t length=0;};
struct Mp4TimelineContext{void*root_script=nullptr,*tracks[512]{};mp4actor::Handle compiled[512]{},root{};int identity=1;size_t track_count=0,kept=0;bool keep(void*);};
struct Model{bool current=true,mapped=true,keep=true,lookup=true;int mode=0;Object root{},dictionary{},track[3]{};Array entries{},buckets{};Class dictionary_type{},entry_type{},entry_array{},bucket_array{},int_type{},track_type{},plain{},root_type{};std::map<std::pair<void*,size_t>,uint64_t>values;std::map<std::pair<void*,std::string>,Field>fields;Mp4TimelineContext context{};}model;
bool Mp4TimelineContext::keep(void*p){if(!p)return false;if(!model.keep)return false;++kept;return true;}
bool mp4_source_plan_keep(Mp4TimelineContext&c,void*p){return p?c.keep(p):true;}
bool mp4_timeline_current(const Mp4TimelineContext&){return model.current;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&v){auto it=model.values.find({p,at});if(it==model.values.end())return false;std::memcpy(&v,&it->second,sizeof(T));return true;}
void set(void*p,size_t at,uint64_t v){model.values[{p,at}]=v;}
void*object_class(void*p){return p?*(Class**)p:nullptr;}
void*font_field_type(void*p){return p?((Field*)p)->type:nullptr;}void*font_class_type(void*p){return p;}
void*font_field(void*p,const char*n){auto it=model.fields.find({p,n});return it==model.fields.end()?nullptr:&it->second;}
const char*class_name(void*p){return p?((Class*)p)->name:nullptr;}const char*class_namespace(void*p){return p?((Class*)p)->space:nullptr;}
bool mp4_timeline_field(void*p,const char*n,size_t at,void**out=nullptr){auto*f=(Field*)font_field(object_class(p),n);if(!f||f->offset!=at)return false;if(out)*out=f;return true;}
bool mp4_timeline_dynamic_field(void*p,const char*n,size_t*out){auto*f=(Field*)font_field(object_class(p),n);if(!f)return false;*out=f->offset;return true;}
size_t mp4_array_length(void*p){return ((Array*)p)->length;}void*mp4_array_data(void*p){return ((Array*)p)->bytes;}bool mp4_actor_mapped(void*,size_t,bool){return model.mapped;}
struct Binding{uintptr_t rva=0;};uintptr_t image_base=0;
void*element(void*p){return ((Class*)p)->element;}bool value(void*p){return ((Class*)p)->value;}int32_t size(void*p,uint32_t*alignment){*alignment=8;return ((Class*)p)->stride;}size_t offset(const void*p){return ((Field*)p)->offset;}
struct{Binding class_element{(uintptr_t)element},class_value_type{(uintptr_t)value},class_value_size{(uintptr_t)size};}mp4_cam_profile;
struct{Binding field_offset{(uintptr_t)offset};}mp4_actor_profile;template<class T>T mp4_cam_call(Binding b){return (T)b.rva;}
struct{int plain=1;}mp4_timeline_pins;void*mp4_timeline_class(int){return &model.plain;}
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;}
bool mp4_root_track_cache_lookup(int,mp4actor::Handle,void*p,mp4actor::Handle*out){if(!model.lookup)return false;for(size_t i=0;i<model.context.track_count;++i)if(model.context.tracks[i]==p){*out=model.context.compiled[i];return true;}return false;}
void entry(size_t at,int32_t hash,int32_t next,void*track,mp4actor::Handle handle){auto*p=model.entries.bytes+at*32;std::memcpy(p,&hash,4);std::memcpy(p+4,&next,4);std::memcpy(p+8,&track,8);std::memcpy(p+16,&handle,16);}
void bucket(size_t at,int32_t value){std::memcpy(model.buckets.bytes+at*4,&value,4);}
void initialize(){auto&m=model;m.root_type={"UnityEngine.Timeline","TimelinePlayable"};m.dictionary_type={"System.Collections.Generic","Dictionary`2"};m.entry_type={"","Entry",32,true};m.int_type={"System","Int32",4,true};m.track_type={"UnityEngine.Timeline","TrackAsset"};m.plain={"UnityEngine.Playables","Playable",16,true};m.entry_array={"","Entry[]",0,false,&m.entry_type};m.bucket_array={"","Int32[]",0,false,&m.int_type};m.root.klass=&m.root_type;m.dictionary.klass=&m.dictionary_type;m.entries.klass=&m.entry_array;m.buckets.klass=&m.bucket_array;
 m.fields[{&m.root_type,"m_PlayableCache"}]={56,&m.dictionary_type};
 const char*names[]={"_buckets","_entries","_count","_version","_freeList","_freeCount"};size_t ats[]={16,24,32,36,40,44};for(size_t i=0;i<6;++i)m.fields[{&m.dictionary_type,names[i]}]={ats[i],i==0?&m.bucket_array:i==1?&m.entry_array:&m.int_type};
 const char*entry_names[]={"hashCode","next","key","value"};size_t entry_ats[]={16,20,24,32};for(size_t i=0;i<4;++i)m.fields[{&m.entry_type,entry_names[i]}]={entry_ats[i],i<2?&m.int_type:i==2?&m.track_type:&m.plain};
 set(&m.root,56,(uintptr_t)&m.dictionary);set(&m.dictionary,16,(uintptr_t)&m.buckets);set(&m.dictionary,24,(uintptr_t)&m.entries);set(&m.dictionary,32,2);set(&m.dictionary,36,3);set(&m.dictionary,40,uint32_t(-1));set(&m.dictionary,44,0);
 m.entries.length=3;m.buckets.length=3;m.context.root_script=&m.root;m.context.track_count=2;for(size_t i=0;i<2;++i){m.track[i].klass=&m.track_type;m.context.tracks[i]=&m.track[i];m.context.compiled[i]={100+i*2,2,0};entry(i,i,-1,&m.track[i],m.context.compiled[i]);bucket(i,i+1);} }
