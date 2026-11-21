#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cmath>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
#include "client-presentation/native/mp4_camera_owner.hpp"
using Method=void;using VoidMethod=void(*)(void*,Method*);
namespace mp4camp=idoly_mp4_camera_profile;
namespace mp4game {using Binding=mp4camp::Binding;}
struct Klass{const char*name;};
Klass kBrain{"Cinemachine.CinemachineBrain"},kGo{"UnityEngine.GameObject"},kVolume{"UnityEngine.Rendering.Volume"},kTransform{"UnityEngine.Transform"},kString{"System.String"},kList{"System.Collections.Generic.List`1"},kArray{"System.Array"},kType{"System.Type"},kCine{"Cinemachine.PostFX.CinemachineVolumeSettings"};
struct Object{Klass*klass;uintptr_t monitor=0;uint8_t body[2048]{};explicit Object(Klass*k):klass(k){}};
struct State{void*go=nullptr,*transform=nullptr,*parent=nullptr;int32_t layer=3,hide=61;bool active=true,enabled=true;void*name=nullptr;std::vector<void*> children,components;};
std::vector<std::unique_ptr<Object>> objects;std::unordered_map<void*,State> states;std::unordered_map<uint32_t,void*> roots;uint32_t nextRoot=1;size_t queries=0,writes=0,updates=0;bool current=true,throw_static=false;void* sourceAsset=nullptr,*manager=nullptr,*ownerName=nullptr,*staticList=nullptr,*runtimeVolume=nullptr,*runtimeComponent=nullptr;int fieldOwner,fieldList,ctor;
Object* make(Klass*k,bool alive=true){auto v=std::make_unique<Object>(k);auto*p=v.get();objects.push_back(std::move(v));uintptr_t native=alive?reinterpret_cast<uintptr_t>(p):0;std::memcpy(p->body,&native,8);states[p]={};return p;}
bool mp4_actor_mapped(const void*p,size_t n,bool){++queries;auto a=reinterpret_cast<uintptr_t>(p);for(auto&v:objects){auto b=reinterpret_cast<uintptr_t>(v.get());if(a>=b&&a<=b+sizeof(Object)&&n<=b+sizeof(Object)-a)return true;}return false;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(!p||!mp4_actor_mapped(static_cast<uint8_t*>(p)+at,sizeof(T),false))return false;std::memcpy(&out,static_cast<uint8_t*>(p)+at,sizeof(T));return true;}
template<class T>void field(void*p,size_t at,T value){assert(mp4_actor_mapped(static_cast<uint8_t*>(p)+at,sizeof(T),true));std::memcpy(static_cast<uint8_t*>(p)+at,&value,sizeof(T));}
bool mp4_type_is(void*p,const char*n){return p&&static_cast<Object*>(p)->klass->name==std::string(n);}
bool mp4_exact_type(void*p,const char*n){return mp4_type_is(p,n);}
bool mp4_alive(void*p){uintptr_t n=0;return p&&mp4_actor_field(p,16,n)&&n;}
void*object_class(void*p){return p?static_cast<Object*>(p)->klass:nullptr;}
uint32_t mp4_retain(void*p){if(!p)return 0;auto r=nextRoot++;roots[r]=p;return r;}
void*weak_get(uint32_t r){auto a=roots.find(r);return a==roots.end()?nullptr:a->second;}
void weak_free(uint32_t r){assert(roots.erase(r)==1);}
struct Mp4ActorTempRoot{uint32_t root=0;explicit Mp4ActorTempRoot(void*v):root(mp4_retain(v)){}~Mp4ActorTempRoot(){if(root)weak_free(root);}void*get()const{return root?weak_get(root):nullptr;}};
bool mp4_actor_refresh_maps(){return true;}
size_t mp4_array_length(void*p){uintptr_t n=0;assert(mp4_actor_field(p,24,n));return n;}
void*mp4_array_data(void*p){return static_cast<uint8_t*>(p)+32;}
Object* array(const std::vector<void*>&v){auto*a=make(&kArray);field<uintptr_t>(a,16,0);field<uintptr_t>(a,24,v.size());if(!v.empty())std::memcpy(static_cast<uint8_t*>(static_cast<void*>(a))+32,v.data(),v.size()*8);return a;}
void list_set(void*p,const std::vector<void*>&v){field<void*>(p,16,array(v));field<int32_t>(p,24,static_cast<int32_t>(v.size()));}
bool mp4_actor_list(void*p,void***v,size_t*n,size_t cap){int32_t count=0;void*a=nullptr;if(!p||!mp4_actor_field(p,16,a)||!mp4_actor_field(p,24,count)||count<0||size_t(count)>cap)return false;*n=size_t(count);*v=static_cast<void**>(mp4_array_data(a));return true;}
void*get_go(void*p,Method*){++queries;return states[p].go;}
void*get_transform(void*p,Method*){++queries;return states[p].transform;}
bool get_active(void*p,Method*){++queries;return states[p].active;}
bool get_enabled(void*p,Method*){++queries;return states[p].enabled;}
int32_t get_layer(void*p,Method*){++queries;return states[p].layer;}
void set_layer(void*p,int32_t n,Method*){++writes;states[p].layer=n;}
int32_t get_hide(void*p,Method*){++queries;return states[p].hide;}
void*get_name(void*p,Method*){++queries;return states[p].name;}
bool equal(void*a,void*b,Method*){return a==b;}
int32_t child_count(void*p,Method*){return int32_t(states[p].children.size());}
void*child(void*p,int32_t i,Method*){return states[p].children[size_t(i)];}
void*parent(void*p,Method*){return states[p].parent;}
struct {void*(*transform_parent)(void*,Method*)=parent;} actorApi;
auto mp4_actor_state_api(){return actorApi;}
void*get_components(void*go,void*type,bool,bool,bool,bool,void*,Method*){std::vector<void*> found;for(auto c:states[go].components)if(type==runtimeComponent||(type==runtimeVolume&&mp4_exact_type(c,"UnityEngine.Rendering.Volume")))found.push_back(c);return array(found);}
void update(void*v,Method*){++updates;int32_t layer=states[states[v].go].layer;float priority=0;assert(mp4_actor_field(v,36,priority));field<int32_t>(v,56,layer);field<float>(v,60,priority);}
void barrier(void*owner,void**at,void*v){++writes;std::memcpy(at,&v,8);(void)owner;}
void mp4_camera_barrier(void*owner,void**at,void*v){barrier(owner,at,v);}
void static_get(const void*f,void*out){++queries;void*v=f==&fieldOwner?ownerName:staticList;std::memcpy(out,&v,8);}
void static_set(const void*f,void*v){++writes;assert(f==&fieldList);staticList=v;if(throw_static){throw_static=false;throw std::runtime_error("setter after write");}}
void*volume_instance(Method*){return manager;}
void destroy(void*p,bool,Method*){++writes;field<uintptr_t>(p,16,0);if(mp4_exact_type(p,"UnityEngine.GameObject")){for(void*c:states[p].components)field<uintptr_t>(c,16,0);void*t=states[p].transform,*par=states[t].parent;if(par){auto&v=states[par].children;for(auto i=v.begin();i!=v.end();++i)if(*i==t){v.erase(i);break;}}}void*l=nullptr;assert(mp4_actor_field(manager,40,l));void**v=nullptr;size_t n=0;assert(mp4_actor_list(l,&v,&n,64));std::vector<void*> remaining;for(size_t i=0;i<n;++i)if(mp4_alive(v[i]))remaining.push_back(v[i]);list_set(l,remaining);}
uintptr_t image_base=0;
mp4camp::Profile mp4_cam_profile{};const auto&mp4_cam_types=mp4camp::android_types;
template<class F>F mp4_cam_call(const mp4camp::Binding&v){return reinterpret_cast<F>(v.rva);}
bool mp4_prefix(const mp4game::Binding&){return true;}
bool mp4_hook_was_statically_verified(const mp4game::Binding&){return true;}
bool game_call(bool=false){return true;}
using Mp4CameraStatic=void(*)(const void*,void*);using Mp4CameraInvoke=void*(*)(const void*,void*,void**,void**);
void*font_field_type(void*f){assert(f==&fieldList);return &kList;}
void*font_class_type(const void*p){return const_cast<void*>(p);}
const void*font_method_impl(void*k,const char*n,int){return k==&kList&&!std::strcmp(n,".ctor")?&ctor:nullptr;}
void*font_new_impl(void*k){return make(static_cast<Klass*>(k));}
const void*(*font_method)(void*,const char*,int)=font_method_impl;
void*(*font_new)(void*)=font_new_impl;
void*runtime_invoke(const void*m,void*object,void**,void**ex){assert(m==&ctor);list_set(object,{});*ex=nullptr;return nullptr;}
bool mp4_camera_generic_class(void*k){return k==&kList;}
void*mp4_camera_static_field(void*,const char*n,uint32_t){return !std::strcmp(n,"sVolumeOwnerName")?static_cast<void*>(&fieldOwner):static_cast<void*>(&fieldList);}
void*mp4_resolved_type_class(const mp4camp::Binding&,const char*,const char*){return &kCine;}
void*get_type(const void*p){return reinterpret_cast<uintptr_t>(p)==mp4_cam_types.volume.rva?runtimeVolume:runtimeComponent;}
void*(*mp4_type_get_object)(const void*)=get_type;
struct Mp4SceneWitness{void*brain=nullptr,*director=nullptr;uint64_t generation=7;};
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.brain==b.brain&&a.director==b.director&&a.generation==b.generation;}
struct DummyScope{bool granted=true;bool frame_granted()const{return granted;}};
struct {DummyScope scope{};bool verified=true,invalidated=false;const char*error="none";Mp4SceneWitness source{};}mp4_camera_host;
namespace idoly_mp4_runtime {struct {bool selected_scene_witness(Mp4SceneWitness&out){++queries;if(!current)return false;out=mp4_camera_host.source;return true;}}game;}
void*get_asset(void*,Method*){++queries;return sourceAsset;}
struct {void*(*director_get_asset)(void*,Method*)=get_asset;}mp4_api;
void original(void*,Method*){}void original_ctor(void*,void*,Method*){}
VoidMethod mp4_volume_update_original=update,mp4_cine_apply_original=original,mp4_cine_volume_enable_original=original;
void(*mp4_cine_game_object_ctor_original)(void*,void*,Method*)=original_ctor;
#include "cine_volume_host.inc"
struct Fixture{Object*brain=make(&kBrain),*go=make(&kGo),*bt=make(&kTransform),*vg=make(&kGo),*vt=make(&kTransform),*volume=make(&kVolume),*sourceList=make(&kList);Fixture(){current=true;mp4_camera_host.invalidated=false;ownerName=make(&kString);sourceAsset=make(&kType);runtimeVolume=make(&kType);runtimeComponent=make(&kType);manager=make(&kType);auto*master=make(&kList);list_set(master,{volume});field<void*>(manager,40,master);states[brain].go=go;states[brain].transform=bt;states[go].transform=bt;states[go].components={bt,brain};states[bt].go=go;states[bt].transform=bt;states[bt].children={vt};states[vg].name=ownerName;states[vg].transform=vt;states[vg].components={vt,volume};states[vt].go=vg;states[vt].parent=bt;states[vt].transform=vt;states[volume].go=vg;states[volume].transform=vt;field<uint8_t>(volume,32,1);field<float>(volume,36,1);field<float>(volume,40,0);field<float>(volume,44,.4f);field<void*>(volume,48,nullptr);field<int32_t>(volume,56,3);field<float>(volume,60,1);field<void*>(volume,64,nullptr);staticList=sourceList;list_set(sourceList,{volume});mp4_camera_host.source={brain,brain,7};if(!mp4_cine_capture()){fprintf(stderr,"scope %s\n",mp4_cine_host.scope.error());assert(false);}}~Fixture(){assert(mp4_cine_cleanup(false));assert(roots.empty());objects.clear();states.clear();}};

Object* create_owned(Fixture& f){
 auto*go=make(&kGo,false);assert(mp4_cine_game_object_before_impl(go,ownerName)==mp4cine::Observe::owned);field<uintptr_t>(go,16,reinterpret_cast<uintptr_t>(go));auto*t=make(&kTransform);states[go].name=ownerName;states[go].transform=t;states[go].components={t};states[t].go=go;states[t].transform=t;states[t].parent=f.bt;states[f.bt].children.push_back(t);
 auto*v=make(&kVolume);states[v].go=go;states[v].transform=t;states[go].components.push_back(v);field<uint8_t>(v,32,1);field<float>(v,36,1);field<float>(v,40,0);field<float>(v,44,1);field<void*>(v,48,nullptr);field<int32_t>(v,56,3);field<float>(v,60,1);field<void*>(v,64,nullptr);assert(mp4_cine_volume_before_enable_impl(v)==mp4cine::Observe::owned);
 void*list=nullptr;assert(mp4_actor_field(manager,40,list));list_set(list,{f.volume,v});return v;
}
int main(){
#define B(k,f) mp4_cam_profile.k.rva=reinterpret_cast<uintptr_t>(&f)
 B(cine_apply_postfx,original);B(component_object,get_go);B(component_transform,get_transform);B(component_enabled,get_enabled);B(object_active_hierarchy,get_active);B(game_object_layer,get_layer);B(game_object_set_layer,set_layer);B(object_hide_flags,get_hide);B(object_name,get_name);B(string_equal,equal);B(transform_children,child_count);B(transform_child,child);B(transform_parent,parent);B(game_object_transform,get_transform);B(get_components,get_components);B(field_static_get,static_get);B(field_static_set,static_set);B(runtime_invoke,runtime_invoke);B(volume_instance,volume_instance);B(object_destroy_immediate,destroy);
#undef B
 {Fixture f;uint64_t token=0;assert(mp4_cine_enter_impl(f.brain,&token)==mp4cine::Observe::owned&&token);assert(staticList==mp4_cine_host.private_list);states[f.vg].layer=8;field<float>(f.volume,36,99);assert(mp4_cine_leave_impl(token));assert(staticList==f.sourceList);assert(mp4_cine_restore());assert(states[f.vg].layer==3);float value=0;assert(mp4_actor_field(f.volume,36,value)&&value==1);}
 {Fixture f;uint64_t token=0;auto calls=queries;assert(mp4_cine_enter_impl(f.go,&token)==mp4cine::Observe::forward);assert(mp4_cine_game_object_before_impl(f.go,nullptr)==mp4cine::Observe::forward);assert(mp4_cine_volume_before_enable_impl(f.volume)==mp4cine::Observe::forward);assert(calls==queries);}
 {Fixture f;throw_static=true;uint64_t token=0;assert(mp4_cine_enter_impl(f.brain,&token)==mp4cine::Observe::reject);assert(staticList==f.sourceList&&mp4_cine_host.scope.readers()==0&&mp4_camera_host.invalidated);}
 {Fixture f;uint64_t token=0;assert(mp4_cine_enter_impl(f.brain,&token)==mp4cine::Observe::owned);assert(mp4_cine_before_source_change());current=false;const auto q=queries,w=writes;assert(mp4_cine_leave_impl(token));assert(queries==q&&writes==w);}
 {Fixture f;uint64_t token=0;assert(mp4_cine_enter_impl(f.brain,&token)==mp4cine::Observe::owned);mp4_cine_abandon_globals();current=false;const auto q=queries,w=writes;assert(!mp4_cine_leave_impl(token));assert(queries==q&&writes==w);}
 {Fixture f;mp4_camera_host.scope.granted=false;uint64_t token=0;const auto q=queries,w=writes;assert(mp4_cine_enter_impl(f.brain,&token)==mp4cine::Observe::reject);assert(!mp4_camera_host.invalidated&&queries==q&&writes==w);mp4_camera_host.scope.granted=true;}
 {Fixture f;uint64_t token=0;assert(mp4_cine_enter_impl(f.brain,&token)==mp4cine::Observe::owned);auto*v=create_owned(f);mp4cine::Receipt r{};assert(mp4_cine_host.scope.receipt(v,r)&&r.newly_created&&r.object==v&&r.game_object==states[v].go);assert(mp4_cine_leave_impl(token));assert(mp4_cine_restore()&&!mp4_alive(v));assert(states[f.bt].children.size()==1);}
 {Fixture f;uint64_t token=0;assert(mp4_cine_enter_impl(f.brain,&token)==mp4cine::Observe::owned);auto*v=create_owned(f);assert(mp4_cine_leave_impl(token));states[states[v].transform].parent=f.vt;const auto w=writes;assert(!mp4_cine_restore()&&writes==w&&mp4_alive(v));}
 {Fixture f;uint64_t token=0;assert(mp4_cine_enter_impl(f.brain,&token)==mp4cine::Observe::owned);auto*v=make(&kVolume);states[v].go=f.go;states[v].transform=f.bt;assert(mp4_cine_volume_before_enable_impl(v)==mp4cine::Observe::reject);assert(mp4_camera_host.invalidated);assert(!mp4_cine_leave_impl(token));assert(staticList==f.sourceList&&mp4_cine_host.scope.readers()==0);assert(mp4_cine_restore());}
 {Fixture f;list_set(f.sourceList,{});uint64_t token=0;assert(mp4_cine_enter_impl(f.brain,&token)==mp4cine::Observe::reject);assert(mp4_camera_host.invalidated&&mp4_cine_host.scope.readers()==0);}
 {Fixture f;uint64_t token=0;assert(mp4_cine_enter_impl(f.brain,&token)==mp4cine::Observe::owned);auto*go=make(&kGo,false);assert(mp4_cine_game_object_before_impl(go,ownerName)==mp4cine::Observe::owned);field<uintptr_t>(go,16,reinterpret_cast<uintptr_t>(go));states[go].name=ownerName;states[go].hide=0;auto*t=make(&kTransform);states[go].transform=t;states[go].components={t};states[t].go=go;assert(mp4_cine_leave_impl(token));assert(mp4_cine_restore()&&!mp4_alive(go));}

}
