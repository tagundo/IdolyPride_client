#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cmath>
#include <cstdlib>
#include <initializer_list>
#include <map>
#include <string>
#include <vector>
#include <memory>
#include <cstdio>
#include <stdexcept>
using Method=void;
#include "camera_profile.inc"
namespace mp4camp=idoly_mp4_camera_profile;
namespace mp4game {struct Binding{uintptr_t rva;uint8_t prefix[16];};}
namespace mp4actor {struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4stage {struct Layout{static constexpr size_t clip_asset=40;};}
struct Class;
struct Field{size_t offset=0;uint32_t flags=0;void* value=nullptr;Class* type=nullptr;};
struct Class{std::map<std::string,Field> fields;bool unity=false;std::string name,space;Class*parent=nullptr;};
struct Obj{Class*klass=nullptr;void*monitor=nullptr;uint8_t bytes[240]{};};
std::vector<std::unique_ptr<Obj>> objects;
std::map<uintptr_t,Class*> classes;
std::map<uint32_t,void*> roots;uint32_t next_root=1;
uint32_t mp4_retain(void*p){if(!p)return 0;roots[next_root]=p;return next_root++;}
void*weak_get(uint32_t n){auto i=roots.find(n);return i==roots.end()?nullptr:i->second;}
void weak_free(uint32_t n){assert(roots.erase(n)==1);}
template<class T>void write(void*p,size_t at,const T& v){assert(p&&at+sizeof v<=sizeof(Obj));std::memcpy(static_cast<uint8_t*>(p)+at,&v,sizeof v);}
template<class T>bool mp4_actor_field(void*p,size_t at,T&v){if(!p||at+sizeof v>sizeof(Obj))return false;std::memcpy(&v,static_cast<uint8_t*>(p)+at,sizeof v);return true;}
Obj* make(Class*c){objects.emplace_back(new Obj);auto*p=objects.back().get();p->klass=c;if(c->unity)write(p,16,reinterpret_cast<uintptr_t>(p)+0x8000);return p;}
void*object_class(void*p){return p?static_cast<Obj*>(p)->klass:nullptr;}
void*mp4_resolved_type_class(const mp4camp::Binding&b,const char*,const char*){auto i=classes.find(b.rva);return i==classes.end()?nullptr:i->second;}
bool on_thread=true,source_current=true,clock_held=true;
bool game_call(){return on_thread;}
bool mp4_prefix(const mp4game::Binding&){return true;}
bool mp4_hook_was_statically_verified(const mp4game::Binding&){return false;}
bool mp4_alive(void*p){uintptr_t native=0;return p&&mp4_actor_field(p,16,native)&&native;}
namespace idoly_mp4_runtime {struct Clock{bool held(){return clock_held;}};Clock clock;Clock&native_clock_scope(){return clock;}}
void*director=nullptr,*asset=nullptr,*track=nullptr,*bound_image=nullptr;
mp4camp::Profile mp4_cam_profile=mp4camp::android_profile;
constexpr const auto&mp4_cam_types=mp4camp::android_types;
template<class F>F mp4_cam_call(const mp4camp::Binding&b){return reinterpret_cast<F>(b.rva);}
Class go_class{},vp_class{},video_clip_class{},opaque_class{};
struct V{void*clip=nullptr,*go=nullptr;int source=0,audio=2,render=0,update=2,reference=0;bool awake=true,loop=false,skip=false,wait=true,frames=false;float speed=1;};
std::map<void*,V> videos;std::map<void*,void*> components;std::map<void*,bool> active;std::map<void*,bool> persistent;
int ctor_mode=0,add_mode=0,destroy_mode=0,setter_throw=0,setters=0,stops=0,destroys=0,goctors=0,source_checks=0,lose_source_at=0;bool detached=true,fenced=true;uint16_t audio_tracks=0;void* reflected_type=nullptr;
Obj* source_vp=nullptr;Obj* source_clip=nullptr;Obj* source_go=nullptr;
void*new_object(void*c){auto*p=make(static_cast<Class*>(c));write(p,16,uintptr_t(0));return p;}void*(*font_new)(void*)=new_object;
void*new_string(const char*){return make(&opaque_class);}void*(*mp4_string_new)(const char*)=new_string;
void*type_object(void*){return reflected_type;}void*(*mp4_type_get_object)(void*)=type_object;
uintptr_t image_base=0;bool mp4_actor_refresh_maps(){return true;}
void go_ctor(void*p,void*,Method*){++goctors;if(ctor_mode==1)throw std::runtime_error("unobservable ctor");write(p,16,reinterpret_cast<uintptr_t>(p)+0x8000);active[p]=true;if(ctor_mode==2)throw std::runtime_error("observable ctor");}
void set_active(void*p,bool b,Method*){active[p]=b;}bool get_active(void*p,Method*){return active[p];}
void hide(void*,int32_t n,Method*){assert(n==61);}void persist(void*p,Method*){persistent[p]=true;}
void*add(void*go,void*t,Method*){assert(t==reflected_type&&!active[go]);if(add_mode==2)return source_vp;auto*p=make(&vp_class);videos[p].go=go;components[go]=p;if(add_mode==1)throw std::runtime_error("attached component");return p;}
void*get_component(void*p,void*t,Method*){assert(t==reflected_type);return components[p];}
void*component_go(void*p,Method*){return videos[p].go;}
bool player_enabled(void*,Method*){return true;}
void destroy(void*p,bool allow,Method*){assert(!allow);++destroys;if(destroy_mode==1)throw std::runtime_error("destroy");if(destroy_mode==2)return;write(p,16,uintptr_t(0));if(components[p])write(components[p],16,uintptr_t(0));}
void video_stop(void*p,Method*){assert(p!=source_vp);++stops;}
void*clip_get(void*p,Method*){return videos[p].clip;}
void changed(){++setters;if(setter_throw&&setters==setter_throw)throw std::runtime_error("property");}
void clip_set(void*p,void*v,Method*){assert(p!=source_vp);changed();videos[p].clip=v;}
#define INT_PROP(NAME,FIELD) int32_t NAME##_get(void*p,Method*){return videos[p].FIELD;}void NAME##_set(void*p,int32_t v,Method*){assert(p!=source_vp);changed();videos[p].FIELD=v;}
#define BOOL_PROP(NAME,FIELD) bool NAME##_get(void*p,Method*){return videos[p].FIELD;}void NAME##_set(void*p,bool v,Method*){assert(p!=source_vp);changed();videos[p].FIELD=v;}
INT_PROP(source,source) INT_PROP(audio,audio) INT_PROP(render,render) INT_PROP(update,update) INT_PROP(reference,reference)
BOOL_PROP(awake,awake) BOOL_PROP(loop,loop) BOOL_PROP(skip,skip) BOOL_PROP(wait,wait) BOOL_PROP(frames,frames)
float speed_get(void*p,Method*){return videos[p].speed;}void speed_set(void*p,float v,Method*){assert(p!=source_vp);changed();videos[p].speed=v;}
uint16_t tracks(void*,Method*){return audio_tracks;}
#include "private_video_factory.inc"
bool source_ok(const mp4video::Source&s){++source_checks;if(lose_source_at&&source_checks==lose_source_at)source_current=false;return source_current&&s.director==director&&s.asset==asset&&s.track==track&&s.image==bound_image&&s.player==source_vp&&s.clip==source_clip&&s.epoch==7&&s.job==9;}
bool detached_ok(const mp4video::Factory&){return detached;}bool gpu_ok(uint64_t e,uint64_t j){return fenced&&e==7&&j==9;}
void init(){
 classes[mp4_cam_types.game_object.rva]=&go_class;classes[mp4_cam_types.video_player.rva]=&vp_class;classes[mp4_cam_types.video_clip.rva]=&video_clip_class;
 director=make(&opaque_class);asset=make(&opaque_class);track=make(&opaque_class);bound_image=make(&opaque_class);
 go_class.unity=vp_class.unity=video_clip_class.unity=true;source_go=make(&go_class);source_vp=make(&vp_class);source_clip=make(&video_clip_class);videos[source_vp].clip=source_clip;videos[source_vp].go=source_go;reflected_type=make(&opaque_class);
 mp4_video_source_current=source_ok;mp4_video_factory_publications_detached=detached_ok;mp4_video_factory_gpu_fenced=gpu_ok;
 const auto set=[](mp4camp::Binding&b,uintptr_t p){b.rva=p;};
 set(mp4_cam_profile.game_object_ctor_name,reinterpret_cast<uintptr_t>(go_ctor));set(mp4_cam_profile.object_set_active,reinterpret_cast<uintptr_t>(set_active));set(mp4_cam_profile.object_active,reinterpret_cast<uintptr_t>(get_active));
 set(mp4_cam_profile.object_set_hide_flags,reinterpret_cast<uintptr_t>(hide));set(mp4_cam_profile.object_persist,reinterpret_cast<uintptr_t>(persist));set(mp4_cam_profile.game_object_add_component,reinterpret_cast<uintptr_t>(add));set(mp4_cam_profile.game_object_get_component,reinterpret_cast<uintptr_t>(get_component));set(mp4_cam_profile.component_object,reinterpret_cast<uintptr_t>(component_go));set(mp4_cam_profile.component_enabled,reinterpret_cast<uintptr_t>(player_enabled));set(mp4_cam_profile.object_destroy_immediate,reinterpret_cast<uintptr_t>(destroy));set(mp4_cam_profile.video_stop,reinterpret_cast<uintptr_t>(video_stop));
 set(mp4_cam_profile.video_clip,reinterpret_cast<uintptr_t>(clip_get));set(mp4_cam_profile.video_set_clip,reinterpret_cast<uintptr_t>(clip_set));set(mp4_cam_profile.video_clip_audio,reinterpret_cast<uintptr_t>(tracks));set(mp4_cam_profile.video_audio_tracks,reinterpret_cast<uintptr_t>(tracks));set(mp4_cam_profile.video_controlled_tracks,reinterpret_cast<uintptr_t>(tracks));
#define PIN(NAME,FIELD) set(mp4_cam_profile.video_##NAME,reinterpret_cast<uintptr_t>(FIELD##_get));set(mp4_cam_profile.video_set_##NAME,reinterpret_cast<uintptr_t>(FIELD##_set));
 PIN(source,source) PIN(audio_mode,audio) PIN(render_mode,render) PIN(update_mode,update) PIN(time_ref,reference) PIN(play_on_awake,awake) PIN(loop,loop) PIN(skip,skip) PIN(wait_first,wait) PIN(send_frames,frames) PIN(speed,speed)
}
mp4video::Source source_spec(){return {director,asset,track,source_vp,bound_image,source_clip,7,9,true};}
void reset_case(){assert(roots.empty());ctor_mode=add_mode=destroy_mode=setter_throw=setters=stops=destroys=goctors=source_checks=lose_source_at=0;source_current=clock_held=detached=fenced=true;audio_tracks=0;}

#include <atomic>
#include "video_native_pins.inc"
uintptr_t mp4_native_base=0x40000000;std::atomic<bool>mp4_native_clock_source_ready{true};struct{const char*native_sha256=mp4_video_native_pins.sha256;}mp4_native_profile;
bool mp4_native_mapped(uintptr_t at,size_t bytes,unsigned flags){return at>=mp4_native_base&&bytes==16&&flags==5;}
bool mp4_actor_mapped(const void*p,size_t bytes,bool){return p&&bytes;}
#include "video_native_host.inc"
bool drain_authorized=true,hook_current=true;unsigned drain_calls=0;uint8_t native_player[256]{},queue_data[0x260]{};
bool current_hook(const mp4camp::Binding&b,uintptr_t p){return hook_current&&b.rva==mp4_video_native_pins.drain.rva&&p==reinterpret_cast<uintptr_t>(mp4_video_native_drain_original);}
bool authorize_drain(const mp4video::Source&s,void*p,uintptr_t n){return drain_authorized&&source_ok(s)&&p==source_vp&&n==reinterpret_cast<uintptr_t>(native_player);}
void drain_native(void*p){assert(p==native_player&&mp4_video_callbacks_null(source_vp));++drain_calls;uintptr_t begin=0;mp4_actor_field(p,0x98,begin);write(p,0xa0,begin);}
void reset_drain(){reset_case();drain_authorized=hook_current=true;drain_calls=0;std::memset(native_player,0,sizeof native_player);write(source_vp,16,reinterpret_cast<uintptr_t>(native_player));uintptr_t begin=reinterpret_cast<uintptr_t>(queue_data);write(native_player,0x98,begin);write(native_player,0xa0,begin+0x130);mp4_video_native_drain_original=drain_native;mp4_video_native_hook_current=current_hook;mp4_video_stopped_drain_authorized=authorize_drain;}
int main(){init();int cases=0;const auto id=reinterpret_cast<uintptr_t>(native_player);
 {reset_drain();assert(mp4_video_drain_stopped(source_spec(),source_vp,id)&&drain_calls==1);uintptr_t begin=0,end=0;assert(mp4_video_native_queue(id,begin,end)&&begin==end);assert(mp4_video_drain_stopped(source_spec(),source_vp,id)&&drain_calls==1);++cases;}
 {reset_drain();drain_authorized=false;assert(!mp4_video_drain_stopped(source_spec(),source_vp,id)&&!drain_calls);++cases;}
 {reset_drain();hook_current=false;assert(!mp4_video_drain_stopped(source_spec(),source_vp,id)&&!drain_calls);++cases;}
 {reset_drain();void*event=make(&opaque_class);write(source_vp,mp4camp::RenderLayout::video_event_preparecompleted,event);assert(!mp4_video_drain_stopped(source_spec(),source_vp,id)&&!drain_calls);write(source_vp,mp4camp::RenderLayout::video_event_preparecompleted,static_cast<void*>(nullptr));++cases;}
 {reset_drain();write(native_player,0x40,uintptr_t(123));assert(!mp4_video_drain_stopped(source_spec(),source_vp,id)&&!drain_calls);++cases;}
 {reset_drain();write(native_player,0xa0,reinterpret_cast<uintptr_t>(queue_data)+1);assert(!mp4_video_drain_stopped(source_spec(),source_vp,id)&&!drain_calls);++cases;}
 {reset_drain();write(native_player,0xa0,reinterpret_cast<uintptr_t>(queue_data)+0x130*257);assert(!mp4_video_drain_stopped(source_spec(),source_vp,id)&&!drain_calls);++cases;}
 {reset_drain();assert(!mp4_video_drain_stopped(source_spec(),source_vp,id+16)&&!drain_calls);++cases;}
 std::printf("%d stopped native Video callback-drain cases passed; native gateway/authorization modeled\n",cases);
}
