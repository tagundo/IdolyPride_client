#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <memory>
#include <vector>
#include "client-presentation/native/mp4_camera_owner.hpp"
namespace mp4camp=idoly_mp4_camera_profile;
using Method=void;
struct Klass {const char* space;const char* name;int rank=0;Klass* element=nullptr;int bytes=0;};
Klass kCamera{"UnityEngine","Camera"},kController{"VL.Rendering","VLSRPCameraController"},kAdditional{"UnityEngine.Rendering.Universal","UniversalAdditionalCameraData"};
Klass kMotion{"UnityEngine.Rendering.Universal","MotionVectorsPersistentData"},kMatrix{"UnityEngine","Matrix4x4",0,nullptr,64},kInt{"System","Int32",0,nullptr,4},kFloat{"System","Single",0,nullptr,4};
Klass kMatrices{"","Matrix4x4[]",1,&kMatrix},kInts{"","Int32[]",1,&kInt},kFloats{"","Single[]",1,&kFloat},kList{"System.Collections.Generic","List`1"};
struct Object {Klass* klass;uintptr_t monitor=0;alignas(16) uint8_t payload[1024]{};explicit Object(Klass* k):klass(k){}};
std::vector<std::unique_ptr<Object>> objects;std::unordered_map<uint32_t,void*> roots;uint32_t nextRoot=1;bool source_current=true,throw_barrier=false;
Object* make(Klass* klass){auto value=std::make_unique<Object>(klass);auto* ptr=value.get();objects.push_back(std::move(value));return ptr;}
size_t mapped_calls=0;
bool mp4_actor_mapped(const void* p,size_t bytes,bool){++mapped_calls;auto start=reinterpret_cast<uintptr_t>(p);for(auto& value:objects){auto base=reinterpret_cast<uintptr_t>(value.get());if(start>=base&&start<=base+sizeof(Object)&&bytes<=base+sizeof(Object)-start)return true;}return false;}
template<class T>bool mp4_actor_field(void* object,size_t at,T& out){auto* p=static_cast<uint8_t*>(object)+at;if(!mp4_actor_mapped(p,sizeof(T),false))return false;std::memcpy(&out,p,sizeof(T));return true;}
template<class T>void field(void* object,size_t at,T value){assert(mp4_actor_mapped(static_cast<uint8_t*>(object)+at,sizeof(T),true));std::memcpy(static_cast<uint8_t*>(object)+at,&value,sizeof(T));}
void* object_class(void* object){return object?static_cast<Object*>(object)->klass:nullptr;}
const char* class_name(void* k){return static_cast<Klass*>(k)->name;}
const char* class_namespace(void* k){return static_cast<Klass*>(k)->space;}
bool mp4_exact_type(void* object,const char* expected){if(!object)return false;auto* k=static_cast<Object*>(object)->klass;std::string name=k->space;if(!name.empty())name+='.';name+=k->name;return name==expected;}
bool mp4_alive(void* object){return object&&mp4_actor_mapped(object,16,false);}
bool mp4_scene_source_current(){return source_current;}
uint32_t mp4_retain(void* object){if(!object)return 0;auto root=nextRoot++;roots[root]=object;return root;}
void* weak_get(uint32_t root){auto found=roots.find(root);return found==roots.end()?nullptr:found->second;}
void weak_free(uint32_t root){assert(roots.erase(root)==1);}
int32_t rank(void* klass){return static_cast<Klass*>(klass)->rank;}
void* element(void* klass){return static_cast<Klass*>(klass)->element;}
int32_t value_size(void* klass,uint32_t* alignment){*alignment=4;return static_cast<Klass*>(klass)->bytes;}
bool mp4_actor_refresh_maps(){return true;}
mp4camp::Profile mp4_cam_profile{};
const auto& mp4_cam_types=mp4camp::android_types;
template<class F>F mp4_cam_call(const mp4camp::Binding& binding){return reinterpret_cast<F>(binding.rva);}
void* mp4_resolved_type_class(const mp4camp::Binding&,const char* space,const char* name){assert(!std::strcmp(space,"UnityEngine.Rendering.Universal")&&!std::strcmp(name,"MotionVectorsPersistentData"));return &kMotion;}
void* font_new(void* klass){return make(static_cast<Klass*>(klass));}
void mp4_camera_barrier(void*,void** slot,void* value){std::memcpy(slot,&value,sizeof(value));if(throw_barrier){throw_barrier=false;throw std::runtime_error("barrier after write");}}
bool mp4_actor_list(void* list,void*** values,size_t* count,size_t){*values=nullptr;int32_t length=0;if(!mp4_actor_field(list,24,length)||length<0)return false;*count=static_cast<size_t>(length);return true;}
struct Mp4SceneWitness {void* controller=nullptr;void* camera=nullptr;};
struct {bool verified=true,invalidated=false;Mp4SceneWitness source{};}mp4_camera_host;
struct {bool active=true;}mp4_scene_host;
bool game_call(){return true;}
bool mp4_scene_same_source(const Mp4SceneWitness& left,const Mp4SceneWitness& right){return left.controller==right.controller&&left.camera==right.camera;}
size_t witness_calls=0;
namespace idoly_mp4_runtime {struct {bool selected_scene_witness(Mp4SceneWitness& out){++witness_calls;if(!source_current)return false;out=mp4_camera_host.source;return true;}}game;}
void motion_ctor(void* motion,Method*){Klass* arrayTypes[]={&kMatrices,&kMatrices,&kInts,&kFloats};const size_t slots[]={16,24,32,40};for(size_t i=0;i<4;++i){auto* array=make(arrayTypes[i]);field<uintptr_t>(array,24,2);field<void*>(motion,slots[i],array);if(i<2){float data[32]{};for(int j=0;j<32;++j)if((j%16)%5==0)data[j]=1;std::memcpy(static_cast<uint8_t*>(static_cast<void*>(array))+32,data,sizeof(data));}else if(i==2){field<int32_t>(array,32,-1);field<int32_t>(array,36,-1);}else{field<float>(array,32,-1);field<float>(array,36,-1);}}}
#include "camera_motion_host.inc"
struct Fixture {
 Object* camera=make(&kCamera);Object* controller=make(&kController);Object* additional=make(&kAdditional);Object* original=nullptr;
 explicit Fixture(bool haveOriginal=true){source_current=true;mp4_camera_host.source={controller,camera};field<void*>(controller,96,additional);field<void*>(additional,96,camera);field<int32_t>(additional,44,0);field<void*>(additional,48,nullptr);if(haveOriginal){original=make(&kMotion);motion_ctor(original,nullptr);}field<void*>(additional,112,original);}
 void* live(){void* value=nullptr;assert(mp4_actor_field(additional,112,value));return value;}
 ~Fixture(){assert(mp4_camera_motion_cleanup());assert(roots.empty());objects.clear();}
};
int main(){
 mp4_cam_profile.class_rank.rva=reinterpret_cast<uintptr_t>(&rank);mp4_cam_profile.class_element.rva=reinterpret_cast<uintptr_t>(&element);mp4_cam_profile.class_value_size.rva=reinterpret_cast<uintptr_t>(&value_size);mp4_cam_profile.motion_data_ctor.rva=reinterpret_cast<uintptr_t>(&motion_ctor);
 {Fixture f;assert(mp4_camera_render_route_admit());assert(mp4_camera_motion_capture());assert(mp4_camera_motion_prepare());assert(f.live()==f.original);const uint64_t ticket=mp4_camera_motion_begin_draw();assert(ticket);auto* privateMotion=f.live();assert(privateMotion&&privateMotion!=f.original);void* frames=nullptr;assert(mp4_actor_field(privateMotion,32,frames));field<int32_t>(frames,32,123);assert(mp4_camera_motion_original_current());assert(mp4_camera_motion_end_draw(ticket));assert(f.live()==f.original);assert(mp4_camera_motion_reset());assert(mp4_actor_field(privateMotion,32,frames));int32_t frame=0;assert(mp4_actor_field(frames,32,frame)&&frame==-1);assert(mp4_camera_motion_restore());assert(f.live()==f.original);assert(mp4_camera_motion_verify());}
 {Fixture f(false);assert(mp4_camera_motion_capture());assert(mp4_camera_motion_prepare());assert(f.live()==nullptr);const uint64_t ticket=mp4_camera_motion_begin_draw();assert(ticket&&f.live()!=nullptr);assert(mp4_camera_motion_end_draw(ticket));assert(mp4_camera_motion_restore());assert(f.live()==nullptr);assert(mp4_camera_motion_verify());}
 {Fixture f;assert(mp4_camera_motion_capture());assert(mp4_camera_motion_prepare());const uint64_t ticket=mp4_camera_motion_begin_draw();assert(ticket);auto* replacement=make(&kMotion);motion_ctor(replacement,nullptr);field<void*>(f.additional,112,replacement);assert(!mp4_camera_motion_restore());assert(f.live()==replacement);field<void*>(f.additional,112,mp4_camera_motion.fresh);assert(mp4_camera_motion_end_draw(ticket));}
 {Fixture f;void* array=nullptr;assert(mp4_actor_field(f.original,16,array));field<uintptr_t>(array,24,3);assert(!mp4_camera_motion_capture());assert(f.live()==f.original);}
 {Fixture f;assert(mp4_camera_motion_capture());assert(mp4_camera_motion_prepare());throw_barrier=true;bool threw=false;try{(void)mp4_camera_motion_begin_draw();}catch(...){threw=true;}assert(threw&&f.live()!=f.original);assert(mp4_camera_motion_restore());assert(f.live()==f.original&&mp4_camera_motion_verify());}
 {Fixture f;assert(mp4_camera_motion_capture());assert(mp4_camera_motion_prepare());void* sourceArray=nullptr;assert(mp4_actor_field(f.original,32,sourceArray));field<int32_t>(sourceArray,32,99);assert(!mp4_camera_motion_restore());int32_t frame=0;assert(mp4_actor_field(sourceArray,32,frame)&&frame==99);}
 {Fixture f;assert(mp4_camera_motion_capture());assert(mp4_camera_motion_prepare());const uint64_t ticket=mp4_camera_motion_begin_draw();assert(ticket);assert(mp4_camera_motion_before_source_change());assert(f.live()==f.original);source_current=false;const auto calls=witness_calls;assert(mp4_camera_motion_end_draw(ticket));assert(witness_calls==calls);}
 {Fixture f;field<int32_t>(f.additional,44,1);assert(!mp4_camera_render_route_admit());field<int32_t>(f.additional,44,0);auto* list=make(&kList);field<int32_t>(list,24,1);field<void*>(f.additional,48,list);assert(!mp4_camera_render_route_admit());}
 {Fixture f;assert(mp4_camera_motion_capture());assert(mp4_camera_motion_prepare());const uint64_t ticket=mp4_camera_motion_begin_draw();assert(ticket);auto* privateMotion=f.live();source_current=false;assert(!mp4_camera_motion_restore());assert(!mp4_camera_motion_cleanup());assert(f.live()==privateMotion);assert(!roots.empty());source_current=true;assert(mp4_camera_motion_before_source_change());assert(mp4_camera_motion_cleanup());assert(roots.empty());}
 {Fixture f;assert(mp4_camera_motion_capture());assert(mp4_camera_motion_prepare());const uint64_t ticket=mp4_camera_motion_begin_draw();assert(ticket);auto* privateMotion=f.live();mp4_camera_motion_abandon_globals_before_source_change();source_current=false;const auto witnesses=witness_calls,reads=mapped_calls;assert(!mp4_camera_motion_end_draw(ticket));assert(!mp4_camera_motion_restore());assert(witness_calls==witnesses&&mapped_calls==reads);assert(mp4_camera_motion_cleanup());assert(witness_calls==witnesses&&mapped_calls==reads&&roots.empty());assert(f.live()==privateMotion);}

}
