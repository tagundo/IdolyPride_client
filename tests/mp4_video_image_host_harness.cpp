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
int main(){init();init_texture();init_image();using R=mp4video::Result;int cases=0;
 {reset_image();mp4video::Factory f;mp4video::Backup*b=nullptr;prepared_backup(f,b);mp4video::ImageLease l;assert(mp4_video_image_capture(l,f,b)==R::ok);assert(mp4_video_image_bind_private(l)==R::ok);void*p=nullptr;mp4_actor_field(bound_image,240,p);assert(p==f.player);assert(mp4_video_image_enable_owned(l,bound_image)&&base_enables==1);assert(mp4_video_image_restore_source(l)==R::ok);mp4_actor_field(bound_image,216,p);assert(p==b->output.object);assert(mp4_video_image_natural_handoff(l)==R::waiting);natural_texture=make(&texture2d_class);textures[natural_texture]=Tex{};source_tex=natural_texture;natural_ready=true;assert(mp4_video_image_natural_handoff(l)==R::ok);mp4_actor_field(bound_image,216,p);assert(p==natural_texture);assert(mp4_video_image_private_detached(l));finish_image(l,f,*b);++cases;}
 {reset_image();mp4video::Factory f;mp4video::Backup*b=nullptr;prepared_backup(f,b);mp4video::ImageLease l;assert(mp4_video_image_capture(l,f,nullptr)==R::unsupported);assert(mp4_video_factory_release(f)==R::ok);drop(*b);++cases;}
 {reset_image();mp4video::Factory f;mp4video::Backup*b=nullptr;prepared_backup(f,b);mp4video::ImageLease l;callbacks_closed=false;assert(mp4_video_image_capture(l,f,b)==R::invalid&&!l.image_root);callbacks_closed=true;assert(mp4_video_factory_release(f)==R::ok);drop(*b);++cases;}
 {reset_image();mp4video::Factory f;mp4video::Backup*b=nullptr;prepared_backup(f,b);mp4video::ImageLease l;assert(mp4_video_image_capture(l,f,b)==R::ok);assert(mp4_video_image_bind_private(l)==R::ok);source_current=false;unsigned before=image_writes;assert(mp4_video_image_restore_source(l)==R::stale&&image_writes==before);assert(!mp4_video_image_release(l));source_current=true;assert(mp4_video_image_restore_source(l)==R::ok);natural_texture=make(&texture2d_class);source_tex=natural_texture;natural_ready=true;assert(mp4_video_image_natural_handoff(l)==R::ok);image_fence=false;assert(!mp4_video_image_release(l));image_fence=true;finish_image(l,f,*b);++cases;}
 {reset_image();mp4video::Factory f;mp4video::Backup*b=nullptr;prepared_backup(f,b);mp4video::ImageLease l;assert(mp4_video_image_capture(l,f,b)==R::ok);assert(mp4_video_image_bind_private(l)==R::ok);void*other=make(&vp_class);write(bound_image,240,other);assert(!mp4_video_image_enable_owned(l,bound_image)&&!base_enables);assert(mp4_video_image_restore_source(l)==R::stale);write(bound_image,240,f.player);assert(mp4_video_image_restore_source(l)==R::ok);natural_texture=make(&texture2d_class);source_tex=natural_texture;natural_ready=true;assert(mp4_video_image_natural_handoff(l)==R::ok);finish_image(l,f,*b);++cases;}
 {reset_image();mp4video::Factory f;mp4video::Backup*b=nullptr;prepared_backup(f,b);mp4video::ImageLease l;assert(mp4_video_image_capture(l,f,b)==R::ok);assert(mp4_video_image_bind_private(l)==R::ok);source_current=false;mp4_video_image_abandon(l);write(bound_image,16,uintptr_t(0));assert(mp4_video_image_private_detached(l));finish_image(l,f,*b);write(bound_image,16,reinterpret_cast<uintptr_t>(bound_image)+0x8000);++cases;}
 {reset_image();mp4video::Factory f;mp4video::Backup*b=nullptr;prepared_backup(f,b);mp4video::ImageLease l;assert(mp4_video_image_capture(l,f,b)==R::ok);assert(mp4_video_image_bind_private(l)==R::ok);void*texture=make(&texture2d_class);private_frame={};private_frame.identity={f.player,f.source.clip,f.player_native,f.source_clip_native,f.source.epoch,f.source.job};private_frame.texture=texture;mp4_actor_field(texture,16,private_frame.texture_native);private_frame.frame=0;private_frame.prepared=private_frame.paused=true;private_frame.seek_pending=false;idoly_mp4_video_frame::Scope frames;assert(frames.bind({nullptr,private_frame_read,private_frame_set},private_frame.identity));assert(mp4_video_image_publish_private(l,frames)==R::stale);frames.frame_ready(private_frame.identity,0);frames.native_drain_completed(private_frame.identity);assert(frames.prepared_frame()==idoly_mp4_video_frame::Result::ready);assert(mp4_video_image_publish_private(l,frames)==R::ok&&!mp4_video_image_private_detached(l));assert(mp4_video_image_restore_source(l)==R::ok&&mp4_video_image_private_detached(l));natural_texture=make(&texture2d_class);source_tex=natural_texture;natural_ready=true;assert(mp4_video_image_natural_handoff(l)==R::ok);finish_image(l,f,*b);++cases;}
 std::printf("%d actual source VideoImage lease cases passed; Unity/UI/native-ready services modeled\n",cases);
}
