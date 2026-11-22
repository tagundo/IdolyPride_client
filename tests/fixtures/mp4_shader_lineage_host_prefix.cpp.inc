#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <array>
#include <map>
#include <vector>
#include <atomic>
#include <stdexcept>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
using Method=const void;using ObjectMethod=void*(*)(void*,Method*);
struct Class{const char*name;};
struct Obj{std::array<uint8_t,64>memory{};Class*klass=nullptr;bool alive=true;int32_t id=1;std::vector<uint8_t>bytes;std::vector<void*>items;std::string text;};
Class shader_class{"UnityEngine.Shader"},bundle_class{"UnityEngine.AssetBundle"},request_class{"UnityEngine.AssetBundleCreateRequest"},bytes_class{"System.Byte[]"},string_class{"System.String"},array_class{"UnityEngine.Object[]"},type_class{"System.Type"};
Obj shader_a,shader_b,bundle,request,input,path,type,empty,array;
bool owner=true,oracle_main=false;int oracle_calls=0;bool source_prefix=true,private_active=false,all_throw=false,original_throw=false,mutate=false,complete=true;int original_calls=0,all_calls=0;
std::map<uint32_t,void*>roots;uint32_t next_root=1;
void put_native(Obj&o,uintptr_t native){std::memcpy(o.memory.data()+16,&native,8);}
bool game_call(bool establish=false){if(establish)owner=true;return owner;}bool mp4_camera_interception_published(){return private_active;}
void*object_class_impl(void*p){return static_cast<Obj*>(p)->klass;}
void*(*object_class)(void*)=object_class_impl;
bool mp4_exact_type(void*p,const char*name){return p&&!std::strcmp(static_cast<Obj*>(p)->klass->name,name);}
bool mp4_alive(void*p){return p&&static_cast<Obj*>(p)->alive;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&value){if(!p||at+sizeof(T)>64)return false;std::memcpy(&value,static_cast<Obj*>(p)->memory.data()+at,sizeof(T));return true;}
bool mp4_actor_mapped(const void*p,size_t,bool){return p!=nullptr;}bool mp4_actor_refresh_maps(){return owner;}
size_t mp4_array_length(void*p){auto*o=static_cast<Obj*>(p);return o->klass==&bytes_class?o->bytes.size():o->items.size();}
void*mp4_array_data(void*p){auto*o=static_cast<Obj*>(p);return o->klass==&bytes_class?static_cast<void*>(o->bytes.data()):static_cast<void*>(o->items.data());}
uint32_t mp4_retain(void*p){roots[next_root]=p;return next_root++;}void*weak_get_impl(uint32_t h){return roots.at(h);}void weak_free_impl(uint32_t h){assert(roots.erase(h)==1);}
void*(*weak_get)(uint32_t)=weak_get_impl;void(*weak_free)(uint32_t)=weak_free_impl;
struct Mp4ActorTempRoot{uint32_t h;explicit Mp4ActorTempRoot(void*p):h(p?mp4_retain(p):0){}~Mp4ActorTempRoot(){if(h)weak_free(h);}void*get()const{return h?weak_get(h):nullptr;}};
void*type_get(const void*p){assert(p==reinterpret_cast<void*>(1));return &type;}void*string_new(const char*s){assert(!s[0]);return &empty;}
void*(*mp4_type_get_object)(const void*)=type_get;void*(*mp4_string_new)(const char*)=string_new;
size_t mp4_string_utf8(void*p,char*out,size_t capacity){auto&s=static_cast<Obj*>(p)->text;if(s.size()>=capacity)return capacity;std::memcpy(out,s.c_str(),s.size()+1);return s.size();}
namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}
uintptr_t image_base=1;
bool mp4_prefix(const mp4game::Binding&){return source_prefix;}bool mp4_hook_was_statically_verified(const mp4game::Binding&){return false;}
void*mp4_resolved_type_class(const mp4game::Binding&,const char*,const char*){return &shader_class;}
struct{mp4game::Binding shader{0,{}};}mp4_cam_types;
struct {mp4game::Binding memory_async,memory_sync,file_async,bundle_result,all_shaders,instance_id,main_thread;}mp4_shader_lineage_pins;
bool retained(void*p){for(const auto&entry:roots)if(entry.second==p)return true;return false;}
int32_t get_id(void*p,Method*){assert(retained(p)||((p==&shader_a||p==&shader_b)&&retained(&array)));return static_cast<Obj*>(p)->id;}
void*all_shaders(void*p,void*n,void*t,Method*m){assert(p==&bundle&&n==&empty&&t==&type&&!m);++all_calls;if(all_throw)throw std::runtime_error("observer load");return &array;}
void*memory_original(void*b,uint32_t crc,Method*m){assert(b==&input&&crc==123&&m==reinterpret_cast<Method*>(456));++original_calls;if(original_throw)throw std::runtime_error("original");if(mutate)input.bytes[0]='x';return &bundle;}
void*async_original(void*b,uint32_t crc,Method*m){memory_original(b,crc,m);return &request;}
void*file_original(void*p,uint32_t crc,uint64_t offset,Method*m){assert(p==&path&&crc==123&&!offset&&m==reinterpret_cast<Method*>(456));++original_calls;if(original_throw)throw std::runtime_error("original");if(mutate){int fd=open(path.text.c_str(),O_WRONLY);assert(fd>=0);assert(write(fd,"xyz",3)==3);close(fd);}return &request;}
void*request_original(void*p,Method*m){assert(p==&request&&m==reinterpret_cast<Method*>(456));++original_calls;return complete?&bundle:nullptr;}

bool actual_main_thread(Method*m){assert(!m);++oracle_calls;return oracle_main;}
