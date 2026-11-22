#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdlib>
#include <string>
#include <array>
#include <unordered_map>
#include <initializer_list>
using Method=void;
namespace mp4game {struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};struct PropertyName4{uint32_t value=0;};}

namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4stage{struct Layout{static constexpr size_t clip_asset=40;};}
struct Mp4TimelineTypePin{const char*name;mp4game::Binding binding;};
struct Obj {void*klass=nullptr;bool alive=true;std::array<uint8_t,128>fields{};};
struct Source{void*camera_director=nullptr,*camera_asset=nullptr,*brain=nullptr;uint64_t generation=7;};
enum class Mp4TimelineVerdict:uint8_t{unrecognized,closed,unclosed};
struct Mp4TimelineRuntime{void*element=nullptr,*clip=nullptr,*track=nullptr;mp4actor::Handle playable{},mixer{};uint8_t kind=0;};
struct Mp4TimelineContext {Source witness{};void*director=nullptr,*asset=nullptr;void*tracks[4]{};mp4actor::Handle compiled[4]{};size_t track_count=0;void*clips[4]{},*clip_tracks[4]{};size_t clip_count=0;void*elements[4]{};size_t element_count=0;};
uintptr_t image_base=0;bool thread_ok=true,pins_ok=true,current_ok=true,source_ok=true,shot_owned=true,mixer_owned=true,handle_owned=true,reference_valid=true;
void*ptr(uintptr_t x){return reinterpret_cast<void*>(x);}
bool game_call(){return thread_ok;}bool mp4_prefix(const mp4game::Binding&){return pins_ok;}bool mp4_hook_was_statically_verified(const mp4game::Binding&){return false;}
void*mp4_timeline_class(const Mp4TimelineTypePin&pin){return pins_ok?ptr(pin.binding.rva):nullptr;}
void*object_class(void*object){return object?static_cast<Obj*>(object)->klass:nullptr;}
bool mp4_timeline_exact(void*object,const Mp4TimelineTypePin&pin){return object&&object_class(object)==ptr(pin.binding.rva);}
bool mp4_timeline_pins_current(){return pins_ok;}bool mp4_timeline_current(const Mp4TimelineContext&){return current_ok;}
bool mp4_scene_same_source(const Source&a,const Source&b){return a.camera_director==b.camera_director&&a.camera_asset==b.camera_asset&&a.brain==b.brain&&a.generation==b.generation;}
struct{bool verified=true;Source source{};void*cameras[2]{};size_t camera_count=1;}mp4_camera_host;
bool mp4_camera_source_current(void*){return source_ok;}bool mp4_alive(void*p){return p&&static_cast<Obj*>(p)->alive;}
bool mp4_exact_type(void*object,const char*name){return object&&((std::strcmp(name,"UnityEngine.GameObject")==0&&object_class(object)==ptr(200))||(std::strcmp(name,"System.Array")==0&&object_class(object)==ptr(201)));}
bool mp4_type_is(void*object,const char*name){return mp4_exact_type(object,name);}
template<class T>bool mp4_actor_field(void*object,size_t offset,T&out){if(!object||offset+sizeof out>128)return false;std::memcpy(&out,static_cast<Obj*>(object)->fields.data()+offset,sizeof out);return true;}
template<class T>void put(Obj&object,size_t offset,const T&value){assert(offset+sizeof value<=128);std::memcpy(object.fields.data()+offset,&value,sizeof value);}
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;}
std::unordered_map<uintptr_t,void*>scripts;
void*mp4_timeline_script(mp4actor::Handle h){return scripts[h.handle];}
bool mp4_camera_script_producer_owned(void*script){return scripts[11]==script?shot_owned:mixer_owned;}
bool mp4_camera_owns_playable_handle(mp4actor::Handle){return handle_owned;}
bool mp4_camera_in(void*value,void*const*items,size_t count){for(size_t i=0;i<count;++i)if(items[i]==value)return true;return false;}
struct{Mp4TimelineTypePin clip{"RuntimeClip",{300,{}}};}mp4_timeline_pins;
struct Mp4CameraSchema{const char*name;uintptr_t type_rva;};
Mp4CameraSchema schema{"Cinemachine.CinemachineBrain",202};const Mp4CameraSchema*mp4_camera_schema(void*){return &schema;}
void*mp4_type_get_object(void*type){return type;}
struct Mp4ActorTempRoot{void*value;explicit Mp4ActorTempRoot(void*p):value(p){}void*get()const{return value;}};
Obj array;void*array_items[2]{};size_t array_count=1;
size_t mp4_array_length(void*){return array_count;}void*mp4_array_data(void*){return array_items;}
bool mp4_actor_refresh_maps(){return true;}bool mp4_actor_mapped(void*,size_t,bool){return true;}
void*get_components(void*,void*,bool,bool,bool,bool,void*,Method*){return &array;}
struct{mp4game::Binding get_components{reinterpret_cast<uintptr_t>(::get_components),{}};}mp4_cam_profile;
template<class F>F mp4_cam_call(const mp4game::Binding&pin){return reinterpret_cast<F>(pin.rva);}
void*binding=nullptr,*brain_go=nullptr,*resolved=nullptr;
struct Api{void*(*director_get_binding)(void*,void*,Method*)=nullptr;void*(*component_game_object)(void*,Method*)=nullptr;void*(*director_get_reference)(void*,mp4game::PropertyName4,bool*,Method*)=nullptr;}mp4_api;
void*get_binding(void*,void*,Method*){return binding;}void*get_go(void*,Method*){return brain_go;}void*get_reference(void*,mp4game::PropertyName4,bool*valid,Method*){*valid=reference_valid;return resolved;}
// SHIPPING_TIMELINE_CAMERA_PINS_AND_HOST
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];
 Obj director{},asset{},brain{},go{},track{},clip{},shot_asset{},shot{},mixer{},camera{},element{},other{};
 go.klass=ptr(200);array.klass=ptr(201);track.klass=ptr(mp4_timeline_camera_pins.track.binding.rva);
 shot_asset.klass=ptr(mp4_timeline_camera_pins.shot.binding.rva);shot.klass=ptr(mp4_timeline_camera_pins.playable.binding.rva);mixer.klass=ptr(mp4_timeline_camera_pins.mixer.binding.rva);element.klass=ptr(300);
 Mp4TimelineContext c{};c.witness={&director,&asset,&brain,7};mp4_camera_host.source=c.witness;c.director=&director;c.asset=&asset;c.tracks[0]=&track;c.compiled[0]={12,1,0};c.track_count=1;c.clips[0]=&clip;c.clip_tracks[0]=&track;c.clip_count=1;c.elements[0]=&element;c.element_count=1;
 mp4_camera_host.cameras[0]=&camera;binding=&brain;brain_go=&go;array_items[0]=&brain;resolved=&camera;
 mp4_api={get_binding,get_go,get_reference};scripts[11]=&shot;scripts[12]=&mixer;
 put(clip,40,static_cast<void*>(&shot_asset));put(shot_asset,32,mp4game::PropertyName4{7});put(shot_asset,40,static_cast<void*>(&camera));put(shot,16,static_cast<void*>(&camera));put(element,24,static_cast<void*>(&clip));put(element,32,mp4actor::Handle{11,1,0});put(element,48,mp4actor::Handle{12,1,0});
 if(mode=="gameobject_binding"||mode=="gameobject_two_brains"||mode=="gameobject_wrong_brain")binding=&go;
 if(mode=="gameobject_two_brains"){array_count=2;array_items[1]=&other;}
 if(mode=="gameobject_wrong_brain")array_items[0]=&other;
 if(mode=="foreign_binding")binding=&other;
 if(mode=="null_binding")binding=nullptr;
 if(mode=="foreign_context")current_ok=false;
 if(mode=="foreign_director")c.director=&other;
 if(mode=="foreign_asset")c.asset=&other;
 if(mode=="shot_fallback")reference_valid=false;
 if(mode=="shot_null_resolved")resolved=nullptr;
 if(mode=="shot_wrong_camera")put(shot,16,static_cast<void*>(&other));
 if(mode=="shot_dead_camera")camera.alive=false;
 if(mode=="wrong_compiled_mixer")c.compiled[0]={13,1,0};
 if(mode=="missing_track")c.track_count=0;
 if(mode=="duplicate_track"){c.track_count=2;c.tracks[1]=&track;c.compiled[1]={12,1,0};}
 if(mode=="unowned_shot")shot_owned=false;
 if(mode=="unowned_mixer")mixer_owned=false;
 if(mode=="source_lost")source_ok=false;
 if(mode=="wrong_handle")handle_owned=false;
 if(mode=="missing_element")c.element_count=0;
 if(mode=="duplicate_element"){c.element_count=2;c.elements[1]=&element;}if(mode=="foreign_runtime_element")element.klass=ptr(301);
 if(mode=="unknown_clip")put(clip,40,static_cast<void*>(&other));
 if(mode=="light_runtime")track.klass=ptr(302);
 if(mode=="mismatched_runtime_mixer")put(element,48,mp4actor::Handle{13,1,0});
 if(mode=="invalid_reference_metadata")pins_ok=false;
 Mp4TimelineRuntime runtime{};runtime.element=&element;runtime.clip=&clip;runtime.track=&track;runtime.playable={11,1,0};runtime.mixer={12,1,0};
 const bool success=mode=="brain_binding"||mode=="gameobject_binding"||mode=="shot_fallback"||mode=="userdata_ignored"||mode=="mixer_userdata_wrong";
 const auto shot_result=mp4_timeline_camera_node(c,{11,1,0},&shot);
 assert((shot_result==Mp4TimelineVerdict::closed)==success);
 if(mode=="userdata_ignored")assert(mp4_timeline_camera_userdata(c,{11,1,0},&shot,&other));
 if(mode=="mixer_userdata_wrong")assert(!mp4_timeline_camera_userdata(c,{12,1,0},&mixer,&other));
 if(mode=="unknown_clip"||mode=="light_runtime")assert(mp4_timeline_camera_runtime(c,runtime)!=Mp4TimelineVerdict::closed);
 if(mode=="brain_binding"||mode=="gameobject_binding"||mode=="shot_fallback")assert(mp4_timeline_camera_runtime(c,runtime)==Mp4TimelineVerdict::closed);
}
