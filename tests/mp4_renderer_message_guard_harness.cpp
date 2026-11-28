#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <map>
#include <vector>
#include <string>
struct Method{};
namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}
struct Mp4RendererMessagePins{mp4game::Binding find_all,game_object,capture_enabled,types[7],vfx_code[5];uintptr_t vfx_manager_cell=0;}mp4_renderer_message_pins;
uintptr_t image_base=0,mp4_native_base=0x1000;
bool main_thread=true,mp4_source_verified=true,mp4_actor_source_verified=true;
std::atomic<bool>mp4_native_clock_source_ready{true};
struct Class{uint32_t initialized=1;const char*name="Other";const char*space="";};Class classes[7],set_class{1,"HashSet`1","System.Collections.Generic"},int_class{1,"Int32","System"},wrong_class{1,"Single","System"};
struct Field{void*type;size_t offset;uint32_t flags=0;};Field capture_field{&set_class,32},count_field{&int_class,64},last_field{&int_class,68};
void*font_field_impl(void*k,const char*n){if(k==&classes[5]&&!std::strcmp(n,"_captureRequests"))return &capture_field;if(k==&set_class&&!std::strcmp(n,"_count"))return &count_field;if(k==&set_class&&!std::strcmp(n,"_lastIndex"))return &last_field;return nullptr;}
const void*font_field_type_impl(void*f){return static_cast<Field*>(f)->type;}void*font_class_type_impl(const void*p){return const_cast<void*>(p);}const char*class_name(void*k){return static_cast<Class*>(k)->name;}const char*class_namespace(void*k){return static_cast<Class*>(k)->space;}
auto font_field=&font_field_impl;auto font_field_type=&font_field_type_impl;auto font_class_type=&font_class_type_impl;
uint32_t field_flags(void*f){return static_cast<Field*>(f)->flags;}size_t field_offset(void*f){return static_cast<Field*>(f)->offset;}
struct{mp4game::Binding field_flags,field_offset;}mp4_cam_profile;
struct Object{int kind=0;void*klass=nullptr;void*go=nullptr;bool alive=true;void*requests=nullptr;};
struct Array{uintptr_t header[3]{};uintptr_t count=0;void*items[8]{};};
Object camera{1},go{2},request_set{4,&set_class};int32_t capture_count=1,capture_last=1;Array arrays[6];std::vector<Object*>owned;
std::map<uint32_t,void*>roots;uint32_t nextroot=1;int root_fail=0,find_throw=0;bool array_wrong=false,resolve_bad=false,prefix_ok=true,capture_enabled=false,map_ok=true;
std::map<void*,size_t>arraytypes;
bool game_call(){return main_thread;}bool mp4_prefix(const mp4game::Binding&){return prefix_ok;}
void*object_class(void*p){return static_cast<Object*>(p)->klass;}
bool mp4_alive(void*p){return p&&static_cast<Object*>(p)->alive;}
bool mp4_type_is(void*p,const char*s){if(!p)return false;if(!std::strcmp(s,"UnityEngine.Camera"))return p==&camera;if(!std::strcmp(s,"UnityEngine.Object[]"))return !array_wrong&&arraytypes.count(p);return false;}
bool mp4_actor_mapped(void*,size_t n,bool){return map_ok&&n>0;}
size_t mp4_array_length(void*p){return static_cast<Array*>(p)->count;}void*mp4_array_data(void*p){return static_cast<Array*>(p)->items;}
uint32_t mp4_retain(void*p){if(!p||root_fail)return 0;roots[nextroot]=p;return nextroot++;}void*weak_get(uint32_t r){return roots.count(r)?roots[r]:nullptr;}void weak_free(uint32_t r){assert(roots.erase(r)==1);}
struct Mp4ActorTempRoot{uint32_t root;explicit Mp4ActorTempRoot(void*p):root(mp4_retain(p)){}~Mp4ActorTempRoot(){if(root)weak_free(root);}void*get()const{return weak_get(root);}};
void*mp4_resolved_type_class(const mp4game::Binding&b,const char*,const char*){return !resolve_bad&&b.rva>=1&&b.rva<=7?&classes[b.rva-1]:nullptr;}
void*type_object(const void*p){return const_cast<void*>(p);}void*(*mp4_type_get_object)(const void*)=type_object;
template<class T>bool mp4_actor_field(void*p,size_t offset,T&out){if(!p||!map_ok)return false;if(offset==0xe0){uint32_t v=static_cast<Class*>(p)->initialized;assert(sizeof(T)==4);std::memcpy(&out,&v,4);return true;}if(p==&request_set&&(offset==64||offset==68)){int32_t v=offset==64?capture_count:capture_last;std::memcpy(&out,&v,4);return true;}if(offset==32){void*v=static_cast<Object*>(p)->requests;assert(sizeof(T)==8);std::memcpy(&out,&v,8);return true;}return false;}
void*find_all(void*t,const Method*){size_t i=reinterpret_cast<uintptr_t>(t)-1;if(find_throw&&i==size_t(find_throw-1))throw std::runtime_error("find");return i<6?&arrays[i]:nullptr;}
void*game_object(void*p,const Method*){return static_cast<Object*>(p)->go;}bool get_enabled(const Method*){return capture_enabled;}
unsigned char native_code[5][16]{};unsigned char manager[128]{};uintptr_t manager_cell=reinterpret_cast<uintptr_t>(manager);bool changed_manager=false;int manager_reads=0;
bool mp4_native_mapped(uintptr_t p,size_t n,int){return p&&n==16&&map_ok;}
bool mp4_gpu_host_read(void*,uintptr_t p,void*out,size_t n){if(!map_ok)return false;if(p==reinterpret_cast<uintptr_t>(&manager_cell)){++manager_reads;uintptr_t v=manager_cell;if(changed_manager&&manager_reads>1)v+=8;std::memcpy(out,&v,n);return true;}std::memcpy(out,reinterpret_cast<void*>(p),n);return true;}
// ACTUAL_CAPTURE_IDLE
// ACTUAL_MESSAGE_GUARD
void setup(){mp4_cam_profile.field_flags.rva=reinterpret_cast<uintptr_t>(&field_flags);mp4_cam_profile.field_offset.rva=reinterpret_cast<uintptr_t>(&field_offset);camera.go=&go;for(size_t i=0;i<7;++i)mp4_renderer_message_pins.types[i].rva=i+1;for(size_t i=0;i<6;++i)arraytypes[&arrays[i]]=i;mp4_renderer_message_pins.find_all.rva=reinterpret_cast<uintptr_t>(&find_all);mp4_renderer_message_pins.game_object.rva=reinterpret_cast<uintptr_t>(&game_object);mp4_renderer_message_pins.capture_enabled.rva=reinterpret_cast<uintptr_t>(&get_enabled);for(size_t i=0;i<5;++i)mp4_renderer_message_pins.vfx_code[i].rva=reinterpret_cast<uintptr_t>(native_code[i])-mp4_native_base;mp4_renderer_message_pins.vfx_manager_cell=reinterpret_cast<uintptr_t>(&manager_cell)-mp4_native_base;}
void add(size_t i,bool selected,bool requests=false){Object*p=new Object{3,&classes[i],selected?static_cast<void*>(&go):reinterpret_cast<void*>(0x1234),true,requests?static_cast<void*>(&request_set):nullptr};owned.push_back(p);arrays[i].items[arrays[i].count++]=p;}
int main(int argc,char**argv){assert(argc==2);setup();int c=std::atoi(argv[1]);bool expected=false,vfx=false;
 if(c==0){expected=true;}
 else if(c>=1&&c<=4){add(c-1,true);}
 else if(c==5){add(4,true);}
 else if(c==6){add(4,false);expected=true;}
 else if(c==7){add(5,true,true);}
 else if(c==8){add(5,true,false);expected=true;}
 else if(c==9){add(5,false,true);expected=true;}
 else if(c==10){capture_enabled=true;}
 else if(c==11){classes[6].initialized=0;}
 else if(c==12){root_fail=1;}
 else if(c==13){array_wrong=true;}
 else if(c==14){resolve_bad=true;}
 else if(c==15){prefix_ok=false;}
 else if(c==16){main_thread=false;}
 else if(c==17){mp4_source_verified=false;}
 else if(c==18){arrays[4].count=4097;}
 else if(c==19){find_throw=2;}
 else if(c==20){vfx=true;expected=true;}
 else if(c==21){vfx=true;uint64_t one=1;std::memcpy(manager+0x78,&one,8);}
 else if(c==22){vfx=true;manager_cell=0;}
 else if(c==23){vfx=true;changed_manager=true;}
 else if(c==24){vfx=true;manager_cell+=1;}
 else if(c==25){vfx=true;mp4_native_clock_source_ready=false;}
 else if(c==26){vfx=true;map_ok=false;}
 else if(c==27){vfx=true;native_code[0][0]=1;}
 else if(c==28){add(5,true,true);capture_count=capture_last=0;expected=true;}
 else if(c==29){add(5,true,true);capture_count=1;capture_last=0;}
 else if(c==30){add(5,true,true);capture_count=0;capture_last=1;}
 else if(c==31){add(5,true,true);capture_count=capture_last=0;request_set.klass=&wrong_class;}
 else if(c==32){add(5,true,true);capture_count=capture_last=0;capture_field.flags=16;}
 else if(c==33){add(5,true,true);capture_count=capture_last=0;capture_field.offset=40;}
 else if(c==34){add(5,true,true);capture_count=capture_last=0;count_field.type=&wrong_class;}
 else if(c==35){add(5,true,true);capture_count=capture_last=0;count_field.offset=132;}
 else if(c==36){add(5,true,true);capture_count=capture_last=0;set_class.name="List`1";}
 else{assert(false);}
 bool result=false;try{result=vfx?mp4_renderer_vfx_zero_closed():((c==7||c==8||c==9||c>=28)?mp4_renderer_capture_idle(&camera):mp4_renderer_messages_closed(&camera));}catch(...){assert(c==19);}
 assert(result==expected&&roots.empty());for(auto*p:owned)delete p;std::printf("case %d passed\n",c);
}
