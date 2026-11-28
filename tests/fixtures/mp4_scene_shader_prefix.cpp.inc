#include "mp4_actor_state.hpp"
#include <cassert>
#include <array>
#include <vector>
#include <map>
#include <string>
#include <memory>
#include <atomic>
#include <cstring>
#include <initializer_list>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
namespace mp4shader=idoly_mp4_shader_lineage;
namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}
using Method=const void;
struct Class;
struct Obj{std::array<unsigned char,1024>data{};Class*klass=nullptr;bool alive=true,scene=false;std::string text;std::vector<void*>items,components,children;void*game_object=nullptr,*materials=nullptr,*shader=nullptr;int32_t scene_handle=11;};
struct Class:Obj{std::string name;Class*parent=nullptr;};
std::vector<std::unique_ptr<Obj>> objects;std::vector<std::unique_ptr<Class>> classes;std::map<void*,Obj*> memory;std::map<uintptr_t,Class*> resolved;
Class*cls(const char*n,Class*p=nullptr){auto x=std::make_unique<Class>();x->name=n;x->parent=p;auto*r=x.get();memory[r]=r;classes.push_back(std::move(x));return r;}
Obj*obj(Class*c){auto x=std::make_unique<Obj>();x->klass=c;auto*r=x.get();memory[r]=r;objects.push_back(std::move(x));return r;}
template<class T>void put(void*p,size_t at,T value){assert(memory.count(p)&&at+sizeof value<=1024);std::memcpy(memory[p]->data.data()+at,&value,sizeof value);}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){auto it=memory.find(p);if(it==memory.end()||at+sizeof out>1024)return false;std::memcpy(&out,it->second->data.data()+at,sizeof out);return true;}
void*object_class(void*p){return memory.count(p)?memory[p]->klass:nullptr;}
bool mp4_exact_type(void*p,const char*n){auto*c=static_cast<Class*>(object_class(p));return c&&c->name==n;}
bool mp4_type_is(void*p,const char*n){auto*c=static_cast<Class*>(object_class(p));for(;c;c=c->parent)if(c->name==n)return true;return false;}
bool mp4_alive(void*p){return memory.count(p)&&memory[p]->alive;}
bool thread=true,prefix=true,roots_ok=true,source_verified=true,reenter=false,original_throw=false,original_early_event=false;
bool mp4_source_verified=true;uintptr_t image_base=1;
bool game_call(){return thread;}
bool mp4_renderer_srp_code(const mp4game::Binding&){return prefix;}
bool mp4_actor_refresh_maps(){return thread;}
bool mp4_actor_mapped(const void*p,size_t,bool){return p!=nullptr;}
size_t mp4_array_length(void*p){assert(memory.count(p));return memory[p]->items.size();}
void*mp4_array_data(void*p){assert(memory.count(p));return memory[p]->items.data();}
std::map<uint32_t,void*> roots;uint32_t next_root=0;int root_fail=-1;
uint32_t mp4_retain(void*p){if(!roots_ok||root_fail==0)return 0;if(root_fail>0)--root_fail;roots[++next_root]=p;return next_root;}
void*weak_get(uint32_t t){auto i=roots.find(t);return i==roots.end()?nullptr:i->second;}
void weak_free(uint32_t t){assert(roots.erase(t)==1);}
bool retained(void*p){for(const auto&r:roots)if(r.second==p)return true;return false;}
struct Mp4ActorTempRoot{uint32_t root=0;explicit Mp4ActorTempRoot(void*p):root(p?mp4_retain(p):0){}~Mp4ActorTempRoot(){if(root)weak_free(root);}void*get()const{return weak_get(root);}};
void*mp4_resolved_type_class(const mp4game::Binding&p,const char*,const char*){auto i=resolved.find(p.rva);return i==resolved.end()?nullptr:i->second;}
size_t mp4_string_utf8(void*p,char*out,size_t n){auto&s=memory[p]->text;if(s.size()<n)std::memcpy(out,s.c_str(),s.size()+1);return s.size();}
void*reflect(const void*p);
void*(*mp4_type_get_object)(const void*)=reflect;
struct{mp4game::Binding get_components_internal,material_shader;}mp4_actor_profile;
struct{mp4game::Binding instance_id;}mp4_shader_lineage_pins;
struct{mp4game::Binding find_all;}mp4_renderer_message_pins;
bool mp4_shader_lineage_owner(){return thread;}

struct Mp4SceneShaderPins{mp4game::Binding scene_loaded,scene_unloaded,bundle_unload,scene_name,scene_valid,scene_ready,scene_roots,object_scene,object_name,object_transform,component_object,component_children,component_child,shared_materials,shader_supported,bundle_scene,bundle_type,renderer_type,particle_type,mesh_type,object_type,api_type,api_load;};
Mp4SceneShaderPins mp4_scene_shader_pins;
struct Mp4SceneShaderPath{const char*name;int32_t child;};
struct Mp4SceneShaderRole{const Mp4SceneShaderPath*path;size_t depth;uint8_t renderer_kind;uint16_t material_slot;int64_t material_path_id,shader_path_id;};
struct Mp4KnownSceneBundle{size_t bytes;mp4shader::Digest digest;const char*scene;const Mp4SceneShaderRole*roles;size_t role_count;};
const Mp4SceneShaderPath gobo_path[]={{"Gobo",-1}},smoke_path[]={{"ParticleSystem",-1},{"Smoke",0}},particle_path[]={{"ParticleSystem",-1}};
const Mp4SceneShaderRole role_rows[]={{gobo_path,1,1,0,72,4232},{smoke_path,2,0,0,75,4231},{particle_path,1,0,0,77,4233}};
Mp4KnownSceneBundle mp4_known_scene_bundles[]={{4,{},"tln_live_thrx-006",role_rows,3},{8,{},"env_stage",nullptr,0}};

// Model only the independently tested installed frontend certificate.
bool frontend_receipts=true;
bool mp4_scene_shader_frontends_current(){return frontend_receipts;}
bool mp4_scene_shader_frontend_code(const mp4game::Binding&b){return mp4_renderer_srp_code(b);}
std::atomic<bool>mp4_native_clock_source_ready{true};
