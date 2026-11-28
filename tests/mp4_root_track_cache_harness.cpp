#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
using Method=void;
namespace mp4game{struct Binding{uintptr_t rva;uint8_t prefix[16];};}
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4world{struct DirectorGraphIdentity{uintptr_t native=0,slot=0;uint32_t version=0,mode=0,category=0;uint16_t status=0;};}
struct alignas(16) Mem{uint8_t b[512]{};};
Mem node,slot,script,track,dict,method_blob,klass,field_cache,field_version;
uintptr_t image_base=0;struct{mp4game::Binding field_offset{},script_instance{},playable_graph_get{};}mp4_actor_profile;
mp4actor::Handle graph{0x1000,7,0},root{},mixer{0x3000,7,0},lookup_value{};
int roots=1,inputs=2,root_keeps=0,try_calls=0,frees=0;bool pin=true,current=true,valid=true,found=true,wrong_owner=false,wrong_klass=false;int mutate=0;
template<class T>void put(void*p,size_t at,T v){std::memcpy(static_cast<uint8_t*>(p)+at,&v,sizeof v);}
template<class T>bool mp4_actor_field(void*p,size_t at,T&v){if(!p||at+sizeof(T)>512)return false;std::memcpy(&v,static_cast<uint8_t*>(p)+at,sizeof v);return true;}
bool mp4_alive(void*p){return p==&track;}
bool mp4_type_is(void*p,const char*){return p==&track;}
bool mp4_exact_type(void*p,const char*){return p==&script;}
void*object_class(void*p){if(p==&dict)return wrong_klass?&track:&klass;return p;}
void*font_field_impl(void*k,const char*n){if(k==&script&&!std::strcmp(n,"m_PlayableCache"))return &field_cache;if(k==&klass&&!std::strcmp(n,"_version"))return &field_version;return nullptr;}
const void*font_field_type_impl(void*p){return p==&field_cache?&klass:nullptr;}
void*font_class_type_impl(const void*p){return const_cast<void*>(p);}
const void*font_method_impl(void*k,const char*n,int32_t argc){return k==&klass&&!std::strcmp(n,"TryGetValue")&&argc==2?&method_blob:nullptr;}
bool mp4_prefix(const mp4game::Binding&){return pin;}
struct Mp4ActorTempRoot{void*p;explicit Mp4ActorTempRoot(void*v):p(v){++root_keeps;}~Mp4ActorTempRoot(){--root_keeps;++frees;}void*get()const{return p;}};
bool mp4_director_graph_handle(const mp4world::DirectorGraphIdentity&,mp4actor::Handle*out){*out=graph;return current;}
bool mp4_scene_registry_current_graph(uintptr_t,uintptr_t,uint32_t){return current;}
bool pv(mp4actor::Handle*h,Method*){return valid&&h->handle;}
int32_t gr(mp4actor::Handle*,Method*){return roots;}
void grget(mp4actor::Handle*,int32_t,mp4actor::Handle*out,Method*){*out=root;}
int32_t pc(mp4actor::Handle*,Method*){return inputs;}
void pi(mp4actor::Handle*,int32_t port,mp4actor::Handle*out,Method*){*out=port==1?mixer:mp4actor::Handle{};}
struct API{decltype(&pv)playable_valid;decltype(&gr)graph_root_count;decltype(&grget)graph_root;decltype(&pc)playable_input_count;decltype(&pi)playable_input;};
API mp4_actor_state_api(){return {pv,gr,grget,pc,pi};}
void*script_call(mp4actor::Handle*,Method*){return &script;}
size_t offset_call(const void*p){return p==&field_cache?56:44;}
void graph_call(mp4actor::Handle*,mp4actor::Handle*out,Method*){*out=graph;if(wrong_owner)out->handle++;}
bool lookup_call(void*,void*key,mp4actor::Handle*out,const void*){++try_calls;if(key!=&track||root_keeps!=3)std::abort();*out=lookup_value;if(mutate==1)put<uint32_t>(&dict,44,2);if(mutate==2)put<void*>(&script,56,&track);if(mutate==3)current=false;if(mutate==4)throw std::runtime_error("lookup");return found;}
auto font_field=&font_field_impl;
auto font_field_type=&font_field_type_impl;
auto font_class_type=&font_class_type_impl;
auto font_method=&font_method_impl;
// SHIPPING_ROOT_TRACK_CACHE_HOST
void setup(){slot={};node={};script={};dict={};method_blob={};root={reinterpret_cast<uintptr_t>(&slot),7,0};lookup_value=mixer;
 image_base=reinterpret_cast<uintptr_t>(&lookup_call)-mp4_root_track_try_pin.rva;
 mp4_actor_profile.field_offset.rva=reinterpret_cast<uintptr_t>(&offset_call)-image_base;
 mp4_actor_profile.script_instance.rva=reinterpret_cast<uintptr_t>(&script_call)-image_base;
 mp4_actor_profile.playable_graph_get.rva=reinterpret_cast<uintptr_t>(&graph_call)-image_base;
 put<uintptr_t>(&method_blob,0,image_base+mp4_root_track_try_pin.rva);put<void*>(&method_blob,32,&klass);put<uint8_t>(&method_blob,82,2);
 put<void*>(&script,56,&dict);put<uint32_t>(&dict,44,1);put<uint32_t>(&slot,32,6);put<uintptr_t>(&slot,40,reinterpret_cast<uintptr_t>(&node));put<uint32_t>(&node,56,0x800);
 roots=1;inputs=2;root_keeps=0;try_calls=0;frees=0;pin=true;current=true;valid=true;found=true;wrong_owner=false;wrong_klass=false;mutate=0;
}
int main(int argc,char**argv){if(argc!=2)return 2;setup();int c=std::atoi(argv[1]);bool expected=false,throws=false;switch(c){
 case 0:expected=true;break;case 1:pin=false;break;case 2:roots=2;break;case 3:found=false;break;case 4:lookup_value.version+=2;break;case 5:wrong_owner=true;break;case 6:wrong_klass=true;break;case 7:put<uint8_t>(&method_blob,82,1);break;case 8:put<void*>(&method_blob,32,&track);break;case 9:put<uintptr_t>(&method_blob,0,1);break;case 10:mutate=1;break;case 11:mutate=2;break;case 12:mutate=3;break;case 13:put<uint32_t>(&node,56,0);break;case 14:put<uint32_t>(&slot,32,4);break;case 15:mutate=4;throws=true;break;case 16:inputs=1;break;case 17:valid=false;break;default:return 2;}
 bool result=false,caught=false;try{result=mp4_root_track_port_closed({},root,&track,1,mixer);}catch(const std::runtime_error&){caught=true;}
 if(result!=expected||caught!=throws||root_keeps!=0){std::fprintf(stderr,"case%d result%d expected%d caught%d roots%d\n",c,result,expected,caught,root_keeps);return 1;}
 if(c==0&&(try_calls!=1||frees!=3))return 1;return 0;
}
