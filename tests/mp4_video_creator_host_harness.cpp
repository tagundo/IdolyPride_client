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
bool source_loop=true;
mp4video::Source source_spec(){return {director,asset,track,source_vp,bound_image,source_clip,7,9,source_loop};}
void reset_case(){assert(roots.empty());ctor_mode=add_mode=destroy_mode=setter_throw=setters=stops=destroys=goctors=source_checks=lose_source_at=0;source_current=clock_held=detached=fenced=true;audio_tracks=0;}

namespace idoly_mp4_paused_frame {struct Descriptor{int32_t width=0,height=0,samples=0,depth=0,mips=0,format=0,stencil=0,depth_stencil=0,dimension=0,shadow=0,vr=0,flags=0,memoryless=0;};}
using Descriptor=idoly_mp4_paused_frame::Descriptor;
Class texture2d_class{},rt_class{};
struct Tex{int32_t width=64,height=32,format=mp4camp::ExtraLayout::video_rgba_srgb,mips=1,dimension=2;bool created=true;Descriptor descriptor{};};
std::map<void*,Tex> textures;void* source_tex=nullptr;int32_t copy_flags=13;bool quiet=true,pubs=true,draw_done=true,gpu_ready=true,gpu_dispatched=true;uint64_t last_recipe=0,last_ticket=0;int copy_calls=0,retire_calls=0;
enum class Mp4SceneResult:int{ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};
Mp4SceneResult mp4_gpu_auxiliary_begin(uint64_t e,uint64_t j,uint64_t r,uint64_t*t){assert(e==7&&j==9);last_recipe=r;*t=++last_ticket;return Mp4SceneResult::ok;}
Mp4SceneResult mp4_gpu_auxiliary_complete(uint64_t t,bool success){assert(t&&t==last_ticket);return success?Mp4SceneResult::waiting:Mp4SceneResult::failed;}
bool mp4_gpu_auxiliary_dispatched(uint64_t t){assert(t==last_ticket);return gpu_dispatched;}
Mp4SceneResult mp4_gpu_auxiliary_poll(uint64_t t){assert(t==last_ticket);return gpu_ready?Mp4SceneResult::ok:Mp4SceneResult::waiting;}
bool mp4_gpu_auxiliary_retire(uint64_t t){assert(t==last_ticket);++retire_calls;return gpu_ready;}
void*vp_texture(void*p,Method*){assert(p==source_vp);return source_tex;}
int32_t tex_width(void*p,Method*){return textures[p].width;}int32_t tex_height(void*p,Method*){return textures[p].height;}int32_t tex_format(void*p,Method*){return textures[p].format;}int32_t tex_mips(void*p,Method*){return textures[p].mips;}int32_t tex_dimension(void*p,Method*){return textures[p].dimension;}
int32_t flags_get(Method*){return copy_flags;}
void desc_ctor(Descriptor*d,int32_t w,int32_t h,int32_t f,int32_t depth,int32_t mips,Method*){assert(!depth&&mips==1);*d={w,h,1,1,1,f,0,0,2,0,0,0,0};}
Descriptor desc_get(void*p,Method*){return textures[p].descriptor;}
void rt_ctor(void*p,Descriptor d,Method*){write(p,16,reinterpret_cast<uintptr_t>(p)+0x8000);auto&t=textures[p];t.width=d.width;t.height=d.height;t.format=d.format;t.mips=d.mips;t.descriptor=d;t.created=false;}
bool rt_create(void*p,Method*){textures[p].created=true;return true;}bool rt_created(void*p,Method*){return textures[p].created;}
void copy_mip(void*s,int32_t a,int32_t b,void*d,int32_t c,int32_t e,Method*){assert(s==source_tex&&s!=d&&!a&&!b&&!c&&!e);++copy_calls;}
#include "video_texture_host.inc"
bool quiesced(const mp4video::Source&s,void*t){return quiet&&source_ok(s)&&t==source_tex;}
bool detached_texture(const mp4video::Backup&){return pubs;}bool draw_fenced(uint64_t e,uint64_t j,uint64_t r){return draw_done&&e==7&&j==9&&r;}
void init_texture(){
 texture2d_class.unity=rt_class.unity=true;classes[mp4_cam_types.video_texture_2d.rva]=&texture2d_class;classes[mp4_cam_types.video_backup_rt.rva]=&rt_class;
 const auto set=[](mp4camp::Binding&b,uintptr_t p){b.rva=p;};
 set(mp4_cam_profile.video_texture,reinterpret_cast<uintptr_t>(vp_texture));set(mp4_cam_profile.video_texture_width,reinterpret_cast<uintptr_t>(tex_width));set(mp4_cam_profile.video_texture_height,reinterpret_cast<uintptr_t>(tex_height));set(mp4_cam_profile.video_texture_format,reinterpret_cast<uintptr_t>(tex_format));set(mp4_cam_profile.video_texture_mips,reinterpret_cast<uintptr_t>(tex_mips));set(mp4_cam_profile.video_texture_dimension,reinterpret_cast<uintptr_t>(tex_dimension));set(mp4_cam_profile.frame_copy_support,reinterpret_cast<uintptr_t>(flags_get));set(mp4_cam_profile.video_descriptor_ctor,reinterpret_cast<uintptr_t>(desc_ctor));set(mp4_cam_profile.frame_rt_ctor,reinterpret_cast<uintptr_t>(rt_ctor));set(mp4_cam_profile.frame_rt_create,reinterpret_cast<uintptr_t>(rt_create));set(mp4_cam_profile.frame_rt_created,reinterpret_cast<uintptr_t>(rt_created));set(mp4_cam_profile.frame_rt_descriptor,reinterpret_cast<uintptr_t>(desc_get));set(mp4_cam_profile.video_copy_mip,reinterpret_cast<uintptr_t>(copy_mip));
 mp4_video_source_frame_quiesced=quiesced;mp4_video_texture_publications_detached=detached_texture;mp4_video_texture_draw_fenced=draw_fenced;
}
void reset_texture(){reset_case();copy_calls=retire_calls=0;copy_flags=13;quiet=pubs=draw_done=gpu_ready=gpu_dispatched=true;source_tex=make(&texture2d_class);textures[source_tex]=Tex{};}
void drop(mp4video::Backup&r){assert(mp4_video_texture_destroy(r));assert(mp4_video_texture_finish(7,9,true)&&roots.empty());}

namespace idoly_mp4_target_image {struct Rect{float x=0,y=0,width=1,height=1;};struct Color{float r=1,g=1,b=1,a=1;};}
#include "video_frame.inc"
bool mp4_actor_mapped(void*p,size_t bytes,bool){return p&&bytes;}
void mp4_camera_barrier(void*,void**slot,void*value){*slot=value;}
Class image_class{};bool callbacks_closed=true,natural_ready=false,image_fence=true;void*natural_texture=nullptr;unsigned image_writes=0,base_enables=0;
void image_texture(void*p,void*t,Method*){++image_writes;write(p,mp4camp::RenderLayout::raw_image_texture,t);}
void image_uv(void*p,idoly_mp4_target_image::Rect r,Method*){++image_writes;write(p,mp4camp::RenderLayout::raw_image_uv,r);}
void image_color(void*p,idoly_mp4_target_image::Color c,Method*){++image_writes;write(p,mp4camp::RenderLayout::graphic_color,c);}
bool image_enabled(void*p,Method*){if(object_class(p)==&vp_class)return true;bool b=false;mp4_actor_field(p,208,b);return b;}void image_enable(void*p,bool b,Method*){++image_writes;write(p,208,b);}
void maskable_enable(void*,Method*){++base_enables;}
#include "video_image_host.inc"
bool callbacks(const mp4video::Source&s,void*image){return callbacks_closed&&source_ok(s)&&image==bound_image;}
bool natural(const mp4video::Source&s,void**out,uintptr_t*n,uint64_t*r){if(!natural_ready||!source_ok(s))return false;*out=natural_texture;mp4_actor_field(*out,16,*n);*r=11;return true;}
bool final_image_fence(uint64_t e,uint64_t j){return image_fence&&e==7&&j==9;}
void init_image(){
 classes[mp4_cam_types.video_image.rva]=&image_class;image_class.unity=true;static_cast<Obj*>(bound_image)->klass=&image_class;write(bound_image,16,reinterpret_cast<uintptr_t>(bound_image)+0x8000);
 const auto set=[](mp4camp::Binding&b,uintptr_t p){b.rva=p;};set(mp4_cam_profile.raw_image_set_texture,reinterpret_cast<uintptr_t>(image_texture));set(mp4_cam_profile.raw_image_set_uv,reinterpret_cast<uintptr_t>(image_uv));set(mp4_cam_profile.graphic_set_color,reinterpret_cast<uintptr_t>(image_color));set(mp4_cam_profile.component_enabled,reinterpret_cast<uintptr_t>(image_enabled));set(mp4_cam_profile.component_set_enabled,reinterpret_cast<uintptr_t>(image_enable));set(mp4_cam_profile.maskable_image_enable,reinterpret_cast<uintptr_t>(maskable_enable));
 mp4_video_image_callbacks_closed=callbacks;mp4_video_source_natural_frame=natural;mp4_video_image_final_draw_fenced=final_image_fence;
}
void reset_image(){reset_texture();callbacks_closed=image_fence=true;natural_ready=false;image_writes=base_enables=0;write(bound_image,mp4camp::RenderLayout::video_image_player,static_cast<void*>(source_vp));write(bound_image,mp4camp::RenderLayout::raw_image_texture,source_tex);write(bound_image,mp4camp::RenderLayout::raw_image_uv,idoly_mp4_target_image::Rect{.1f,.2f,.7f,.8f});write(bound_image,mp4camp::RenderLayout::graphic_color,idoly_mp4_target_image::Color{.2f,.3f,.4f,.8f});write(bound_image,208,true);}
void prepared_backup(mp4video::Factory&f,mp4video::Backup*&b){assert(mp4_video_factory_create(f,source_spec())==mp4video::Result::ok);b=mp4_video_texture_reserve(source_spec());assert(b&&mp4_video_texture_allocate(*b,source_spec(),source_tex)==mp4video::Result::ok);assert(mp4_video_texture_copy(*b)==mp4video::Result::waiting);assert(mp4_video_texture_poll(*b)==mp4video::Result::ok);}
void finish_image(mp4video::ImageLease&l,mp4video::Factory&f,mp4video::Backup&b){assert(mp4_video_image_release(l));assert(mp4_video_factory_release(f)==mp4video::Result::ok);assert(mp4_video_texture_destroy(b));assert(mp4_video_texture_finish(7,9,true));assert(roots.empty());}
idoly_mp4_video_frame::State private_frame{};
bool private_frame_read(void*,const idoly_mp4_video_frame::Identity&id,idoly_mp4_video_frame::State*out){if(!idoly_mp4_video_frame::same(id,private_frame.identity))return false;*out=private_frame;return true;}
bool private_frame_set(void*,const idoly_mp4_video_frame::Identity&,int64_t){return true;}

#include <sys/mman.h>
namespace mp4child {struct Graph{uintptr_t handle=0;uint32_t version=0,padding=0;};}
struct Mp4ChildFactoryContext {struct{uintptr_t director=0,asset=0,game_object=0;uint64_t epoch=0,capture=0;}owner;struct{uint64_t serial=0,original_receipt=0;}operation;struct{uint64_t birth_receipt=0,factory_receipt=0,operation_serial=0;}birth;};
Mp4ChildFactoryContext child_context{};bool child_current=true,recording_creator=true,script_origin=true,returned_root=true,retired_root=true,callbacks_drained=true;
bool mp4_child_factory_context(mp4child::Graph graph,Mp4ChildFactoryContext*out){if(!child_current||graph.handle!=100)return false;*out=child_context;return true;}
std::map<uintptr_t,void*> scripts;void*mp4_timeline_script(mp4actor::Handle h){return scripts[h.handle];}
struct {void*(*director_get_asset)(void*,Method*);void*(*director_get_binding)(void*,void*,Method*);}mp4_api;
void*asset_get(void*p,Method*){return p==director?asset:nullptr;}void*binding_get(void*p,void*t,Method*){return p==director&&t==track?source_vp:nullptr;}
bool mp4_type_is(void*p,const char*name){return p&&object_class(p)==&opaque_class&&!std::strcmp(name,"System.Delegate");}
Class track_class{},mixer_class{};
#include "video_creator_pins.inc"
#include "video_creator_host.inc"
bool creator_mode(const mp4video::Source&s,const Mp4ChildFactoryContext&){return recording_creator&&source_ok(s);}
bool origin_ok(const mp4video::Source&,const Mp4ChildFactoryContext&,void*){return script_origin;}
bool returned_ok(const mp4video::Source&,const Mp4ChildFactoryContext&,mp4actor::Handle h){return returned_root&&h.handle==101;}
bool retired_ok(const mp4video::Source&,const Mp4ChildFactoryContext&,mp4actor::Handle){return retired_root;}
bool drained_ok(const mp4video::Factory&){return callbacks_drained;}
void init_creator(){
 classes[mp4_cam_types.video_track.rva]=&track_class;classes[mp4_cam_types.video_mixer.rva]=&mixer_class;static_cast<Obj*>(track)->klass=&track_class;
 mp4_api.director_get_asset=asset_get;mp4_api.director_get_binding=binding_get;
 mp4_video_recording_creator=creator_mode;mp4_video_creator_script_origin=origin_ok;mp4_video_creator_returned_root=returned_ok;mp4_video_creator_retired_root=retired_ok;mp4_video_private_callbacks_drained=drained_ok;
 std::map<uintptr_t,bool>pages;
 for(unsigned i=0;i<8;++i){const uintptr_t at=mp4_video_creator_pins.returns[i]-4;const uintptr_t page=at&~uintptr_t(4095);
  if(!pages[page]){void*p=mmap(reinterpret_cast<void*>(page),4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);assert(p==reinterpret_cast<void*>(page));pages[page]=true;}
  std::memcpy(reinterpret_cast<void*>(at),&mp4_video_creator_pins.calls[i],4);
 }
}
void reset_creator(){reset_image();source_loop=true;child_current=recording_creator=script_origin=returned_root=retired_root=callbacks_drained=true;write(track,160,uint8_t(1));child_context={};child_context.owner={reinterpret_cast<uintptr_t>(director),reinterpret_cast<uintptr_t>(asset),reinterpret_cast<uintptr_t>(source_go),7,3};child_context.operation={40,5};child_context.birth={11,12,40};scripts.clear();}
void*new_script(){auto*p=make(&mixer_class);write(p,16,static_cast<void*>(source_vp));write(p,24,bound_image);write(p,32,uint8_t(0));write(p,33,uint8_t(1));write(p,34,uint8_t(source_loop));return p;}
void subscriptions(mp4video::Creator&c){const size_t at[]={32,24,64,56};for(size_t i=0;i<4;++i){auto*event=make(&opaque_class);auto*metadata=make(&opaque_class);uintptr_t code=mp4_video_creator_pins.callbacks[i].rva;write(event,16,code);write(event,32,c.script);write(event,40,static_cast<void*>(metadata));write(metadata,8,code);write(event,120,static_cast<void*>(nullptr));write(c.factory->player,at[i],static_cast<void*>(event));}}
void route_all(mp4video::Creator&c){Mp4VideoCreatorEntry guard(&c);for(unsigned i=0;i<4;++i)assert(mp4_video_creator_property(i,source_vp,i==0||(i==3&&c.factory->source.loop),mp4_video_creator_pins.returns[i],nullptr));}
void begin(mp4video::Creator&c,mp4video::Factory&f,mp4video::ImageLease&l,mp4video::Backup*&b){prepared_backup(f,b);assert(mp4_video_image_capture(l,f,b)==mp4video::Result::ok);assert(mp4_video_image_bind_private(l)==mp4video::Result::ok);assert(mp4_video_creator_begin(c,f,l,{100,1,0},track,source_go,nullptr));}
void finish(mp4video::Creator&c,mp4video::ImageLease&l,mp4video::Factory&f,mp4video::Backup&b){
 assert(mp4_video_creator_prepare_destroy(c));c.original_destroyed=true;assert(mp4_video_image_restore_source(l)==mp4video::Result::ok);assert(mp4_video_factory_quiesce(f)==mp4video::Result::ok);assert(mp4_video_creator_release(c));
 natural_texture=make(&texture2d_class);source_tex=natural_texture;natural_ready=true;assert(mp4_video_image_natural_handoff(l)==mp4video::Result::ok);finish_image(l,f,b);
}
bool program_live=true;void*private_texture=nullptr;int64_t decoded_frame=0,target_frame=0;unsigned frame_sets=0,pauses=0;
bool program_ok(const mp4video::Source&s,const Mp4ChildFactoryContext&,mp4actor::Handle h,void*script){return program_live&&source_ok(s)&&h.handle==101&&scripts[101]==script;}
bool prepared_get(void*,Method*){return true;}bool paused_get(void*,Method*){return true;}bool playing_get(void*,Method*){return false;}
int64_t frame_get(void*,Method*){return decoded_frame;}void frame_set(void*p,int64_t frame,Method*){assert(p!=source_vp);++frame_sets;target_frame=frame;}
void*texture_get(void*p,Method*){return p==source_vp?source_tex:private_texture;}double rate_get(void*,Method*){return 29.97;}double length_get(void*,Method*){return 10.;}uint64_t count_get(void*,Method*){return 300;}void pause_get(void*p,Method*){assert(p!=source_vp);++pauses;}
void init_frame(){const auto set=[](mp4camp::Binding&b,uintptr_t p){b.rva=p;};set(mp4_cam_profile.video_prepared,reinterpret_cast<uintptr_t>(prepared_get));set(mp4_cam_profile.video_paused,reinterpret_cast<uintptr_t>(paused_get));set(mp4_cam_profile.video_playing,reinterpret_cast<uintptr_t>(playing_get));set(mp4_cam_profile.video_frame,reinterpret_cast<uintptr_t>(frame_get));set(mp4_cam_profile.video_set_frame,reinterpret_cast<uintptr_t>(frame_set));set(mp4_cam_profile.video_texture,reinterpret_cast<uintptr_t>(texture_get));set(mp4_cam_profile.video_clip_rate,reinterpret_cast<uintptr_t>(rate_get));set(mp4_cam_profile.video_clip_length,reinterpret_cast<uintptr_t>(length_get));set(mp4_cam_profile.video_clip_frames,reinterpret_cast<uintptr_t>(count_get));set(mp4_cam_profile.video_pause,reinterpret_cast<uintptr_t>(pause_get));mp4_video_private_program_current=program_ok;}
int main(){init();init_texture();init_image();init_creator();int cases=0;
 {reset_creator();mp4video::Factory f;mp4video::ImageLease l;mp4video::Backup*b=nullptr;mp4video::Creator c;begin(c,f,l,b);int old=setters;route_all(c);assert(setters==old+4&&c.properties==4&&videos[source_vp].awake);void*script=new_script();assert(mp4_video_creator_on_create(c,script));assert(mp4_video_creator_may_create(c));void*vp=nullptr;mp4_actor_field(script,16,vp);assert(vp==f.player);subscriptions(c);assert(mp4_video_creator_created(c));scripts[101]=script;assert(mp4_video_creator_settle(c,{101,1,0}));finish(c,l,f,*b);++cases;}
 {reset_creator();mp4video::Factory f;mp4video::ImageLease l;mp4video::Backup*b=nullptr;prepared_backup(f,b);assert(mp4_video_image_capture(l,f,b)==mp4video::Result::ok);assert(mp4_video_image_bind_private(l)==mp4video::Result::ok);mp4video::Creator c;child_current=false;assert(!mp4_video_creator_begin(c,f,l,{100,1,0},track,source_go,nullptr)&&!c.entered);child_current=true;assert(mp4_video_image_restore_source(l)==mp4video::Result::ok);natural_texture=make(&texture2d_class);source_tex=natural_texture;natural_ready=true;assert(mp4_video_image_natural_handoff(l)==mp4video::Result::ok);finish_image(l,f,*b);++cases;}
 {reset_creator();mp4video::Factory f;mp4video::ImageLease l;mp4video::Backup*b=nullptr;mp4video::Creator c;begin(c,f,l,b);{Mp4VideoCreatorEntry guard(&c);int old=setters;assert(mp4_video_creator_property(1,source_vp,false,mp4_video_creator_pins.returns[1],nullptr)&&c.failed&&setters==old);}void*script=new_script();assert(mp4_video_creator_on_create(c,script)&&!mp4_video_creator_may_create(c));finish(c,l,f,*b);++cases;}
 {reset_creator();mp4video::Factory f;mp4video::ImageLease l;mp4video::Backup*b=nullptr;mp4video::Creator c;begin(c,f,l,b);{Mp4VideoCreatorEntry guard(&c);int old=setters;assert(!mp4_video_creator_property(0,f.player,true,mp4_video_creator_pins.returns[0],nullptr));assert(!mp4_video_creator_property(0,source_vp,true,1234,nullptr)&&setters==old);}route_all(c);void*script=new_script();assert(mp4_video_creator_on_create(c,script)&&mp4_video_creator_may_create(c));subscriptions(c);assert(mp4_video_creator_created(c));scripts[101]=script;returned_root=false;assert(!mp4_video_creator_settle(c,{101,1,0})&&c.failed);finish(c,l,f,*b);++cases;}
 {reset_creator();mp4video::Factory f;mp4video::ImageLease l;mp4video::Backup*b=nullptr;mp4video::Creator c;begin(c,f,l,b);route_all(c);void*script=new_script();assert(mp4_video_creator_on_create(c,script)&&mp4_video_creator_may_create(c));subscriptions(c);assert(mp4_video_creator_created(c));void*saved=nullptr;mp4_actor_field(f.player,24,saved);void*foreign=make(&opaque_class);write(f.player,24,foreign);assert(!mp4_video_creator_prepare_destroy(c));write(f.player,24,saved);finish(c,l,f,*b);++cases;}
 {reset_creator();mp4video::Factory f;mp4video::ImageLease l;mp4video::Backup*b=nullptr;mp4video::Creator c;begin(c,f,l,b);route_all(c);void*script=new_script();script_origin=false;assert(mp4_video_creator_on_create(c,script)&&c.failed&&!mp4_video_creator_may_create(c));finish(c,l,f,*b);++cases;}
 {reset_creator();init_frame();program_live=true;frame_sets=pauses=0;decoded_frame=0;private_texture=make(&texture2d_class);mp4video::Factory f;mp4video::ImageLease l;mp4video::Backup*b=nullptr;mp4video::Creator c;begin(c,f,l,b);route_all(c);void*script=new_script();assert(mp4_video_creator_on_create(c,script)&&mp4_video_creator_may_create(c));subscriptions(c);assert(mp4_video_creator_created(c));scripts[101]=script;assert(mp4_video_creator_settle(c,{101,1,0}));write(script,mp4camp::RenderLayout::video_mixer_drifted,uint8_t(1));assert(mp4_video_private_loop_before(c));uint8_t drifted=1;mp4_actor_field(script,mp4camp::RenderLayout::video_mixer_drifted,drifted);assert(!drifted);write(script,mp4camp::RenderLayout::video_mixer_drifted,uint8_t(1));assert(mp4_video_private_loop_before(c)&&mp4_video_private_loop_after(c));Mp4VideoPrivateFrameHost h;assert(mp4_video_private_frame_bind(h,c));auto id=h.frames.identity();assert(mp4_video_private_prepared_event(h,id)&&pauses==1);assert(mp4_video_private_frame_event(h,id,0)&&mp4_video_private_drain_event(h,id));assert(h.frames.prepared_frame()==idoly_mp4_video_frame::Result::ready);Mp4VideoPrivateStep first{&h};{Mp4VideoPrivateStepEntry guard(&first);assert(!mp4_video_private_sync_time(source_vp,0.1,false,mp4_video_creator_pins.returns[4]));assert(mp4_video_private_sync_enter(script,1./120.,mp4_video_creator_pins.returns[7]));assert(mp4_video_private_sync_time(f.player,1./120.,false,mp4_video_creator_pins.returns[4]));assert(mp4_video_private_step_forward(f.player,mp4_video_creator_pins.returns[6]));}assert(first.sync&&first.step&&!first.failed&&!frame_sets);Mp4VideoPrivateStep second{&h};{Mp4VideoPrivateStepEntry guard(&second);assert(mp4_video_private_sync_enter(script,.1,mp4_video_creator_pins.returns[7]));assert(mp4_video_private_sync_time(f.player,.1,false,mp4_video_creator_pins.returns[4]));assert(mp4_video_private_step_forward(f.player,mp4_video_creator_pins.returns[6]));}assert(!second.failed&&frame_sets==1&&target_frame==2&&h.seek_pending);decoded_frame=2;assert(mp4_video_private_frame_event(h,id,2));assert(mp4_video_private_drain_event(h,id));assert(h.frames.poll()==idoly_mp4_video_frame::Result::waiting);assert(mp4_video_private_seek_event(h,id));assert(h.frames.poll()==idoly_mp4_video_frame::Result::waiting);assert(mp4_video_private_drain_event(h,id));assert(h.frames.poll()==idoly_mp4_video_frame::Result::ready);assert(mp4_video_image_publish_private(l,h.frames)==mp4video::Result::ok);program_live=false;assert(!h.frames.current_receipt()&&!mp4_video_private_frame_event(h,id,2));program_live=true;mp4_video_private_frame_abandon(h);finish(c,l,f,*b);++cases;}
 {reset_creator();source_loop=false;write(track,160,uint8_t(0));init_frame();program_live=true;frame_sets=pauses=0;decoded_frame=0;private_texture=make(&texture2d_class);mp4video::Factory f;mp4video::ImageLease l;mp4video::Backup*b=nullptr;mp4video::Creator c;begin(c,f,l,b);route_all(c);void*script=new_script();assert(mp4_video_creator_on_create(c,script)&&mp4_video_creator_may_create(c));subscriptions(c);assert(mp4_video_creator_created(c));scripts[101]=script;assert(mp4_video_creator_settle(c,{101,1,0}));Mp4VideoPrivateFrameHost h;assert(mp4_video_private_frame_bind(h,c));auto id=h.frames.identity();assert(mp4_video_private_prepared_event(h,id));mp4_video_private_frame_event(h,id,0);mp4_video_private_drain_event(h,id);assert(h.frames.prepared_frame()==idoly_mp4_video_frame::Result::ready);Mp4VideoPrivateStep first{&h};{Mp4VideoPrivateStepEntry guard(&first);assert(mp4_video_private_sync_enter(script,12.,mp4_video_creator_pins.returns[7]));assert(mp4_video_private_sync_time(f.player,2.,false,mp4_video_creator_pins.returns[4]));assert(mp4_video_private_step_forward(f.player,mp4_video_creator_pins.returns[6]));}assert(!first.failed&&target_frame==299&&frame_sets==1);decoded_frame=299;mp4_video_private_seek_event(h,id);mp4_video_private_frame_event(h,id,299);mp4_video_private_drain_event(h,id);assert(h.frames.poll()==idoly_mp4_video_frame::Result::ready);Mp4VideoPrivateStep second{&h};{Mp4VideoPrivateStepEntry guard(&second);assert(mp4_video_private_sync_enter(script,13.,mp4_video_creator_pins.returns[7]));assert(mp4_video_private_sync_time(f.player,3.,false,mp4_video_creator_pins.returns[4]));assert(mp4_video_private_step_forward(f.player,mp4_video_creator_pins.returns[6]));}assert(!second.failed&&second.result==idoly_mp4_video_frame::Result::ready&&frame_sets==1);write(script,mp4camp::RenderLayout::video_mixer_playedonce,uint8_t(1));assert(mp4_video_private_loop_after(c));uint8_t played=1;mp4_actor_field(script,mp4camp::RenderLayout::video_mixer_playedonce,played);assert(!played);mp4_video_private_frame_abandon(h);finish(c,l,f,*b);++cases;}
 std::printf("%d concrete private Video Creator cases passed; actual factory/native services modeled\n",cases);
}
