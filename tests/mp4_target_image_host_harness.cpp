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
using Method=void;
#include "target_image_scope.inc"
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
void* field(void*c,const char*n){if(!c)return nullptr;auto& fs=static_cast<Class*>(c)->fields;auto i=fs.find(n);return i==fs.end()?nullptr:&i->second;}
void*(*font_field)(void*,const char*)=field;
void*(*font_field_type)(void*)=[](void*p)->void*{return p;};
void*(*font_class_type)(void*)=[](void*p)->void*{return p?static_cast<Field*>(p)->type:nullptr;};
void*(*class_parent)(void*)=[](void*p)->void*{return p?static_cast<Class*>(p)->parent:nullptr;};
const char*(*class_name)(void*)=[](void*p){return static_cast<Class*>(p)->name.c_str();};
const char*(*class_namespace)(void*)=[](void*p){return static_cast<Class*>(p)->space.c_str();};
size_t offset(const void*p){return static_cast<const Field*>(p)->offset;}
uint32_t flags(const void*p){return static_cast<const Field*>(p)->flags;}
void static_get(void*p,void*out){*static_cast<void**>(out)=static_cast<Field*>(p)->value;}
bool mp4_root_track_field(void*p,const char*n,size_t at){void*f=field(object_class(p),n);return f&&offset(f)==at;}
bool on_thread=true,source_current=true,clock_held=true,plan_closed=true;
unsigned writes=0,barriers=0,asset_queries=0,binding_queries=0;
bool game_call(){return on_thread;}
bool mp4_prefix(const mp4game::Binding&){return true;}
bool mp4_hook_was_statically_verified(const mp4game::Binding&){return false;}
bool mp4_alive(void*p){uintptr_t native=0;return p&&mp4_actor_field(p,16,native)&&native;}
Class controller_class{},texture_class{},wrapper_class{},transform_class{},image_class{},track_class{},clip_class{},behaviour_class{},mixer_class{},director_class{},asset_class{},event_class{},calls_class{},group_class{},list_class{},element_class{},base_class{},singleton_class{};
bool mp4_type_is(void*p,const char*t){if(!p)return false;auto*c=static_cast<Obj*>(p)->klass;
 return (c==&wrapper_class&&!std::strcmp(t,"VL.VLRenderTexture"))||(c==&texture_class&&!std::strcmp(t,"UnityEngine.RenderTexture"))
  ||(c==&event_class&&!std::strcmp(t,"UnityEngine.Events.UnityEventBase"));}
struct Mp4SceneWitness{void*player=nullptr,*controller=nullptr;uint64_t generation=0;};
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.player==b.player&&a.controller==b.controller&&a.generation==b.generation;}
struct {Mp4SceneWitness source{};bool active=true;}mp4_scene_host;
bool mp4_scene_source_current(){return source_current;}
namespace idoly_mp4_runtime{struct Game{bool selected_scene_witness(Mp4SceneWitness&out){if(!source_current)return false;out=mp4_scene_host.source;return true;}}game;struct Clock{bool held(){return clock_held;}};Clock clock;Clock&native_clock_scope(){return clock;}}
enum class Mp4TimelineProofPhase:uint8_t{admission,active,source_restore_plan,source_restore=source_restore_plan,source_restored,source_bootstrap_plan};
bool mp4_timeline_source_plan_phase(Mp4TimelineProofPhase phase){return phase==Mp4TimelineProofPhase::admission||phase==Mp4TimelineProofPhase::source_bootstrap_plan;}
enum class Mp4TimelineVerdict:uint8_t{unrecognized,closed,unclosed};
struct Mp4TimelineContext{Mp4TimelineProofPhase phase=Mp4TimelineProofPhase::admission;Mp4SceneWitness witness{};void*director=nullptr,*asset=nullptr;
 void*tracks[8]{};mp4actor::Handle compiled[8]{};size_t track_count=0;void*elements[8]{};mp4actor::Handle runtime_playables[8]{},runtime_mixers[8]{};size_t element_count=0;
 void*clips[8]{},*clip_tracks[8]{};size_t clip_count=0;};
struct Mp4TimelineRuntime{void*element=nullptr,*clip=nullptr,*track=nullptr;mp4actor::Handle playable{},mixer{};uint8_t kind=0;};
struct Mp4TimelineProducer{Mp4TimelineVerdict(*node)(const Mp4TimelineContext&,mp4actor::Handle,void*)=nullptr;
 bool(*userdata)(const Mp4TimelineContext&,mp4actor::Handle,void*,void*)=nullptr;Mp4TimelineVerdict(*runtime)(const Mp4TimelineContext&,const Mp4TimelineRuntime&)=nullptr;};
struct {bool(*restoration_closed)(const Mp4TimelineContext&)=[](const Mp4TimelineContext&){return plan_closed;};}mp4_timeline_hooks;
struct {Class*clip=&element_class;}mp4_timeline_pins;
bool mp4_timeline_exact(void*p,Class*c){return p&&object_class(p)==c;}
bool mp4_timeline_current(const Mp4TimelineContext&){return source_current;}
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;}
std::map<uintptr_t,void*> scripts;
void*mp4_timeline_script(mp4actor::Handle h){auto i=scripts.find(h.handle);return i==scripts.end()?nullptr:i->second;}
Mp4TimelineContext context{};
bool mp4_timeline_visit_owned_contexts(Mp4TimelineProofPhase phase,bool(*visitor)(const Mp4TimelineContext&,void*),void*opaque){
 if(!clock_held||!source_current)return false;
 auto previous=context.phase;context.phase=phase;bool ok=visitor(context,opaque);context.phase=previous;return ok;}
void*director=nullptr,*asset=nullptr,*bound_image=nullptr,*image_transform=nullptr,*wrapper=nullptr,*source_texture=nullptr;
void*get_asset(void*d,Method*){++asset_queries;return d==director?asset:nullptr;}
void*get_binding(void*d,void*t,Method*){++binding_queries;return d==director&&t==context.tracks[0]?bound_image:nullptr;}
struct {void*(*director_get_asset)(void*,Method*)=get_asset;void*(*director_get_binding)(void*,void*,Method*)=get_binding;}mp4_api;
void*(*rt_target)(void*,Method*)=[](void*c,Method*)->void*{return c==mp4_scene_host.source.controller?wrapper:nullptr;};
void*(*target_to_texture)(void*,Method*)=[](void*w,Method*)->void*{return w==wrapper?source_texture:nullptr;};
void*get_transform(void*p,Method*){return p==bound_image?image_transform:nullptr;}
bool get_enabled(void*p,Method*){bool b=false;mp4_actor_field(p,208,b);return b;}
void set_enabled(void*p,bool b,Method*){++writes;write(p,208,b);}
void set_texture(void*p,void*t,Method*){++writes;write(p,mp4camp::RenderLayout::raw_image_texture,t);}
void set_uv(void*p,idoly_mp4_target_image::Rect r,Method*){++writes;write(p,mp4camp::RenderLayout::raw_image_uv,r);}
void set_color(void*p,idoly_mp4_target_image::Color c,Method*){++writes;write(p,mp4camp::RenderLayout::graphic_color,c);}
void mp4_camera_barrier(void*,void**slot,void*value){++barriers;*slot=value;}
std::map<void*,size_t> lists;
bool mp4_actor_list(void*p,void***out,size_t*count,size_t cap){auto i=lists.find(p);if(i==lists.end()||i->second>cap)return false;*out=nullptr;*count=i->second;return true;}
mp4camp::Profile mp4_cam_profile=mp4camp::android_profile;
constexpr const auto&mp4_cam_types=mp4camp::android_types;
template<class F>F mp4_cam_call(const mp4camp::Binding&b){return reinterpret_cast<F>(b.rva);}
#include "target_image_host.inc"
void bind(const mp4camp::Binding&b,Class&c,bool unity=false){classes[b.rva]=&c;c.unity=unity;}
void fields(Class&c,std::initializer_list<std::pair<const char*,size_t>> values){for(auto&v:values)c.fields[v.first]={v.second,0,nullptr};}
void init(){
 using L=mp4camp::RenderLayout;using E=mp4camp::ExtraLayout;
 bind(mp4_cam_types.target_image_track,track_class,true);bind(mp4_cam_types.target_image_clip,clip_class,true);
 bind(mp4_cam_types.target_image_mixer,mixer_class);bind(mp4_cam_types.target_image_behaviour,behaviour_class);
 bind(mp4_cam_types.raw_image,image_class,true);bind(mp4_cam_types.rect_transform,transform_class,true);
 controller_class.parent=&singleton_class;singleton_class.parent=&base_class;singleton_class.name="VLCameraControllerSingleton`1";singleton_class.space="VL";base_class.name="VLMonoBehaviourSingleton`1";base_class.space="VL.Core";controller_class.unity=texture_class.unity=director_class.unity=asset_class.unity=true;
 fields(mixer_class,{{"_rawImage",L::target_mixer_image},{"_rawImageInitialStateEnabled",L::target_mixer_enabled}});
 fields(behaviour_class,{{"trackingTarget",L::target_behaviour_target},{"alpha",L::target_behaviour_alpha},{"center",L::target_behaviour_center},{"scale",L::target_behaviour_scale}});
 fields(clip_class,{{"behaviour",L::target_clip_template}});
 fields(image_class,{{"m_Texture",L::raw_image_texture},{"m_UVRect",L::raw_image_uv},{"m_Color",L::graphic_color},
  {"m_OnDirtyLayoutCallback",L::graphic_dirty_layout},{"m_OnDirtyVertsCallback",L::graphic_dirty_vertices},{"m_OnDirtyMaterialCallback",L::graphic_dirty_material},
  {"m_MaskMaterial",L::graphic_mask_material},{"m_ParentMask",L::graphic_parent_mask},{"m_OnCullStateChanged",L::graphic_cull_event},
  {"m_StencilValue",L::graphic_stencil},{"m_RectTransform",L::graphic_rect}});
 fields(event_class,{{"m_Calls",E::event_calls},{"m_PersistentCalls",E::event_persistent_group}});
 fields(calls_class,{{"m_RuntimeCalls",E::event_runtime_list},{"m_PersistentCalls",E::event_persistent_list},{"m_ExecutingCalls",E::event_executing_list}});
 fields(group_class,{{"m_Calls",E::persistent_group_list}});base_class.fields["_instance"]={0,16,nullptr,&controller_class};
 director=make(&director_class);asset=make(&asset_class);bound_image=make(&image_class);image_transform=make(&transform_class);wrapper=make(&wrapper_class);source_texture=make(&texture_class);
 auto*controller=make(&controller_class);base_class.fields["_instance"].value=controller;mp4_scene_host.source={controller,controller,7};
 context={};context.witness=mp4_scene_host.source;context.director=director;context.asset=asset;context.tracks[0]=make(&track_class);context.compiled[0]={1,1,0};context.track_count=1;
 auto*mixer=make(&mixer_class);write(mixer,L::target_mixer_image,bound_image);write(mixer,L::target_mixer_enabled,false);scripts[1]=mixer;
 auto*clip=make(&clip_class);auto*model=make(&behaviour_class);auto*live=make(&behaviour_class);write(clip,L::target_clip_template,model);
 for(void*p:{static_cast<void*>(model),static_cast<void*>(live)}){write(p,L::target_behaviour_alpha,1.f);write(p,L::target_behaviour_scale,1.f);}
 auto*timeline_clip=make(&asset_class);write(timeline_clip,40,clip);context.clips[0]=timeline_clip;context.clip_tracks[0]=context.tracks[0];context.clip_count=1;
 auto*element=make(&element_class);write(element,24,static_cast<void*>(timeline_clip));context.elements[0]=element;context.element_count=1;
 context.runtime_playables[0]={2,1,0};context.runtime_mixers[0]={1,1,0};scripts[2]=live;
 write(bound_image,L::raw_image_texture,source_texture);write(bound_image,L::raw_image_uv,idoly_mp4_target_image::Rect{.1f,.2f,.6f,.7f});
 write(bound_image,L::graphic_color,idoly_mp4_target_image::Color{.5f,.6f,.7f,.8f});write(bound_image,208,true);
 auto*event=make(&event_class);auto*calls=make(&calls_class);auto*group=make(&group_class);write(bound_image,L::graphic_cull_event,static_cast<void*>(event));
 write(event,E::event_calls,static_cast<void*>(calls));write(event,E::event_persistent_group,static_cast<void*>(group));
 for(size_t off:{E::event_runtime_list,E::event_persistent_list,E::event_executing_list}){auto*l=make(&list_class);lists[l]=0;write(calls,off,static_cast<void*>(l));}
 auto*l=make(&list_class);lists[l]=0;write(group,E::persistent_group_list,static_cast<void*>(l));
 mp4_cam_profile.field_offset.rva=reinterpret_cast<uintptr_t>(::offset);mp4_cam_profile.field_flags.rva=reinterpret_cast<uintptr_t>(::flags);
 mp4_cam_profile.field_static_get.rva=reinterpret_cast<uintptr_t>(::static_get);mp4_cam_profile.component_transform.rva=reinterpret_cast<uintptr_t>(::get_transform);
 mp4_cam_profile.component_enabled.rva=reinterpret_cast<uintptr_t>(::get_enabled);mp4_cam_profile.component_set_enabled.rva=reinterpret_cast<uintptr_t>(::set_enabled);
 mp4_cam_profile.raw_image_set_texture.rva=reinterpret_cast<uintptr_t>(::set_texture);mp4_cam_profile.raw_image_set_uv.rva=reinterpret_cast<uintptr_t>(::set_uv);
 mp4_cam_profile.graphic_set_color.rva=reinterpret_cast<uintptr_t>(::set_color);
}
int main(){init();int cases=0;using R=mp4target::Result;using V=Mp4TimelineVerdict;using L=mp4camp::RenderLayout;
 auto producer=mp4_target_image_producer();auto mixer=context.compiled[0];auto leaf=context.runtime_playables[0];
 assert(producer.node(context,mixer,scripts[1])==V::closed&&producer.node(context,leaf,scripts[2])==V::closed);
 assert(producer.userdata(context,mixer,scripts[1],bound_image)&&producer.userdata(context,leaf,scripts[2],bound_image));++cases;
 context.phase=Mp4TimelineProofPhase::active;assert(producer.node(context,mixer,scripts[1])==V::unclosed);++cases;
 assert(mp4_target_image_capture(9)==R::ok&&mp4_target_image_host.scope.captured());assert(producer.node(context,mixer,scripts[1])==V::closed);++cases;
 {auto saved=context.compiled[0];context.compiled[0]={3,1,0};assert(producer.node(context,mixer,scripts[1])==V::unclosed);context.compiled[0]=saved;++cases;}
 {void*old=bound_image;bound_image=make(&image_class);assert(producer.node(context,mixer,scripts[1])==V::unclosed);bound_image=old;++cases;}
 {write(scripts[2],L::target_behaviour_target,image_transform);assert(producer.node(context,leaf,scripts[2])==V::unclosed);write(scripts[2],L::target_behaviour_target,static_cast<void*>(nullptr));++cases;}
 {write(scripts[2],L::target_behaviour_scale,2.f);assert(producer.node(context,leaf,scripts[2])==V::unclosed);write(scripts[2],L::target_behaviour_scale,1.f);++cases;}
 {write(bound_image,L::graphic_dirty_vertices,image_transform);assert(producer.node(context,mixer,scripts[1])==V::unclosed);write(bound_image,L::graphic_dirty_vertices,static_cast<void*>(nullptr));++cases;}
 {base_class.fields["_instance"].value=image_transform;assert(producer.node(context,mixer,scripts[1])==V::unclosed);base_class.fields["_instance"].value=mp4_scene_host.source.controller;++cases;}
 {base_class.fields["_instance"].type=&singleton_class;assert(producer.node(context,mixer,scripts[1])==V::unclosed);base_class.fields["_instance"].type=&controller_class;++cases;}
 {base_class.fields["_instance"].flags=0;assert(producer.node(context,mixer,scripts[1])==V::unclosed);base_class.fields["_instance"].flags=16;++cases;}
 {singleton_class.name="OtherSingleton`1";assert(producer.node(context,mixer,scripts[1])==V::unclosed);singleton_class.name="VLCameraControllerSingleton`1";++cases;}
 {base_class.fields["_instance"].offset=8;assert(producer.node(context,mixer,scripts[1])==V::unclosed);base_class.fields["_instance"].offset=0;++cases;}
 {plan_closed=false;assert(producer.node(context,mixer,scripts[1])==V::unclosed);plan_closed=true;++cases;}
 // Simulate authorized fresh saved-time child Evaluate after geometry restored:
 // the current controller RT has changed; no retired source RT is reassigned.
 auto*fresh=make(&mixer_class);write(fresh,L::target_mixer_image,bound_image);write(fresh,L::target_mixer_enabled,true);scripts[1]=fresh;
 source_texture=make(&texture_class);write(bound_image,L::raw_image_texture,source_texture);write(bound_image,L::raw_image_uv,mp4target::Rect{0,0,1,1});
 write(bound_image,L::graphic_color,mp4target::Color{1,1,1,1});write(bound_image,208,false);
 assert(mp4_target_image_restore()==R::ok&&mp4_target_image_host.scope.restored());mp4target::Image actual{};assert(mp4_target_image_read(nullptr,bound_image,&actual));
 assert(actual.texture==source_texture&&actual.enabled&&actual.uv.x==.1f&&actual.color.a==.8f);bool cache=true;mp4_actor_field(fresh,L::target_mixer_enabled,cache);assert(!cache);++cases;
 const auto old_queries=asset_queries+binding_queries,old_writes=writes+barriers;source_current=false;
 assert(mp4_target_image_restore()==R::ok&&mp4_target_image_release()==R::ok&&roots.empty());
 assert(old_queries==asset_queries+binding_queries&&old_writes==writes+barriers);++cases;
 std::printf("%d actual TargetImage host provenance/UI/sourceRT scenarios passed; modeled native services, no GPU/device claim\n",cases);
}
