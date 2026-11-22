// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <initializer_list>
#include <atomic>
#include <pthread.h>
#endif
namespace idoly_mp4_game {
// Receiver and Type must come from the already verified timeline camera and
// pinned controller descriptor. This helper never discovers a camera, creates
// a component, or substitutes a different output camera.
struct CameraOwnerCalls {
    bool(*is_type)(void*,const char*)=nullptr;
    bool(*alive)(void*)=nullptr;
    uint32_t(*retain)(void*)=nullptr;
    void*(*retained)(uint32_t)=nullptr;
    void(*release)(uint32_t)=nullptr;
    void*(*get_component)(void*,void*,const void*)=nullptr;
    void*(*controller_camera)(void*,const void*)=nullptr;
};
struct CameraOwnerResult {
    // Nonzero handle transfers ownership to the caller. Retain/use the target
    // in the selected-scene adapter before releasing this temporary handle.
    uint32_t handle=0;
    const char* error="selected_camera_controller_absent";
};
inline CameraOwnerResult recover_camera_controller(void* camera,void* controller_type,const CameraOwnerCalls& api) {
    if(!api.is_type||!api.alive||!api.retain||!api.retained||!api.release||!api.get_component||!api.controller_camera)
        return {0,"camera_owner_api_unavailable"};
    struct Root {
        const CameraOwnerCalls& api;uint32_t handle=0;
        Root(const CameraOwnerCalls& a,void* value):api(a),handle(value?api.retain(value):0){}
        ~Root(){if(handle)api.release(handle);}
        void* get()const{return handle?api.retained(handle):nullptr;}
        uint32_t transfer(){const uint32_t value=handle;handle=0;return value;}
    };
    try {
        if(!api.is_type(camera,"UnityEngine.Camera")||!api.alive(camera))return {0,"selected_output_camera_invalid"};
        if(!api.is_type(controller_type,"System.Type"))return {0,"selected_controller_type_unavailable"};
        Root receiver(api,camera),type(api,controller_type);
        if(receiver.get()!=camera)return {0,"selected_camera_handle_failed"};
        if(type.get()!=controller_type)return {0,"selected_controller_type_handle_failed"};
        void* value=api.get_component(receiver.get(),type.get(),nullptr);
        if(!value)return {0,"selected_camera_controller_absent"};
        Root result(api,value);
        if(result.get()!=value)return {0,"selected_camera_controller_handle_failed"};
        if(!api.is_type(value,"VL.Rendering.VLSRPCameraController")||!api.alive(value))
            return {0,"selected_camera_controller_wrong_type"};
        if(api.controller_camera(value,nullptr)!=receiver.get()||!api.alive(receiver.get()))
            return {0,"selected_camera_controller_camera_mismatch"};
        return {result.transfer(),"none"};
    } catch(...) {return {0,"selected_camera_controller_lookup_exception"};}
}
} // namespace idoly_mp4_game

// Bounded camera/audio restoration for one exact selected scene. The native
// source host supplies verified original calls and class-layout descriptions;
// descriptors may not cover IL2CPP headers, native object pointers, unknown
// mutable object families, or unowned scene components.
namespace idoly_mp4_camera_state {
using Method=void;
enum class Result:int {ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};
enum class Follow:int {leaf=0,owned=1,reject=-1};
enum class Role:uint8_t {ordinary,brain,brain_frame,core_status,tracker_status};
struct Vec3 {float x=0,y=0,z=0;};
struct Quat {float x=0,y=0,z=0,w=1;};
struct LensImage {
    float fov=0,aspect=0,near_clip=0,far_clip=0,orthographic_size=0,focal_length=0;
    float sensor_x=0,sensor_y=0,lens_x=0,lens_y=0;
    bool orthographic=false,physical=false,automatic_aspect=false,enabled=false;
    int32_t gate_fit=0,projection_mode=0;
};
struct ComponentImage {
    void* transform=nullptr;void* game_object=nullptr;
    Vec3 local_position{},local_scale{1,1,1};Quat local_rotation{};
    bool enabled=false,active_self=false;
};
struct GlobalImage {
    float core_time=0,tracker_time=0;int32_t core_fixed=0;
    void* tracker_status=nullptr;void* tracker_delete=nullptr;
};
struct Owner {
    void* player=nullptr;void* director=nullptr;void* camera=nullptr;void* controller=nullptr;
    void* brain=nullptr;void* bgm=nullptr;void* voice=nullptr;uint64_t generation=0;
};
constexpr size_t max_nodes=512,max_references=8192,max_node_refs=256,max_mixers=32,max_path=32;
constexpr size_t max_bytes=16u*1024u*1024u;
struct Description {
    void* klass=nullptr;uint8_t* data=nullptr;size_t bytes=0;
    size_t references=0;uint32_t reference_offsets[max_node_refs]{};
    bool unity_component=false;Role role=Role::ordinary;
    // Verified source-field offsets relative to data. Unused slots are -1.
    int32_t identity_offset=-1,next_id_offset=-1,last_frame_offset=-1,window_frame_offset=-1;
};
struct Mixer {
    void* director=nullptr;void* brain=nullptr;void* instance=nullptr;
    uint16_t path_size=0,path[max_path]{};int32_t id=-1;
};
struct AudioApi {
    void*(*clip)(void*,Method*)=nullptr;void(*set_clip)(void*,void*,Method*)=nullptr;
    int32_t(*samples)(void*,Method*)=nullptr;void(*set_samples)(void*,int32_t,Method*)=nullptr;
    bool(*playing)(void*,Method*)=nullptr;float(*volume)(void*,Method*)=nullptr;
    void(*set_volume)(void*,float,Method*)=nullptr;float(*pitch)(void*,Method*)=nullptr;
    void(*set_pitch)(void*,float,Method*)=nullptr;bool(*loop)(void*,Method*)=nullptr;
    void(*set_loop)(void*,bool,Method*)=nullptr;bool(*mute)(void*,Method*)=nullptr;
    void(*set_mute)(void*,bool,Method*)=nullptr;void(*play)(void*,Method*)=nullptr;
    void(*stop)(void*,Method*)=nullptr;void(*pause)(void*,Method*)=nullptr;void(*unpause)(void*,Method*)=nullptr;
    // The originals have no managed pause getter. This reads only the proven
    // native Pause/UnPause bit using a verified same native receiver witness.
    bool(*paused)(void*,bool*)=nullptr;
    bool(*timeline_output)(void*,void*)=nullptr;
    int32_t(*clip_samples)(void*,Method*)=nullptr;
    bool(*state_supported)(void*,void*,bool has_clip,bool playing,bool paused)=nullptr;
    // Held saved-time logical programme proof. Natural DSP readiness is
    // verified after clock/global-loop detachment by the coordinator.
    bool(*timeline_logical_restored)(void*,void*,bool playing,bool paused)=nullptr;
};
struct Api {
    bool(*current)(void*,const Owner&)=nullptr;bool(*held)(void*)=nullptr;
    bool(*mapped)(const void*,size_t,bool)=nullptr;bool(*alive)(void*)=nullptr;
    uint32_t(*retain)(void*)=nullptr;void*(*target)(uint32_t)=nullptr;void(*release)(uint32_t)=nullptr;
    // Read-only scene admission includes all scoped impulse listeners/sources,
    // not merely the manager's currently empty event list.
    bool(*admit)(void*,const Owner&)=nullptr;
    bool(*roots)(void*,void**,size_t,size_t*)=nullptr;
    bool(*describe)(void*,void*,Description&)=nullptr;
    Follow(*follow)(void*,void*,void*)=nullptr;
    // Exact exported IL2CPP write barrier, serialized on the Unity thread.
    void(*write_reference)(void*,void**,void*)=nullptr;
    bool(*component_capture)(void*,void*,ComponentImage&)=nullptr;
    bool(*component_restore)(void*,void*,const ComponentImage&)=nullptr;
    bool(*component_verify)(void*,void*,const ComponentImage&)=nullptr;
    bool(*lens_capture)(void*,void*,LensImage&)=nullptr;
    bool(*lens_restore)(void*,void*,const LensImage&)=nullptr;
    bool(*lens_verify)(void*,void*,const LensImage&)=nullptr;
    bool(*global_capture)(void*,GlobalImage&)=nullptr;
    bool(*global_restore)(void*,const GlobalImage&)=nullptr;
    bool(*global_verify)(void*,const GlobalImage&)=nullptr;
    // Read-only traversal of exact graph paths to typed .CinemachineMixer
    // instances. Restored graphs must have matching paths, not old handles.
    bool(*mixers)(void*,Mixer*,size_t,size_t*)=nullptr;
    int32_t(*frame_count)()=nullptr;
    bool(*reset_history)(void*,const Owner&)=nullptr;
    AudioApi audio{};
};
enum class RendererResolve:uint8_t {forward,owned,error};
struct RendererResolution {
    RendererResolve kind=RendererResolve::forward;void* renderer=nullptr;bool original_called=false;
};
struct RendererPublicationApi {
    // Independent retained source/data provenance. Neither callback may call
    // this publication's resolve() or the patched getter recursively.
    bool(*source_current)(void*)=nullptr;bool(*private_ready)(void*)=nullptr;
    void*(*original_renderer)(void*,void*)=nullptr;
    // Own native GPU/readback cleanup fence, not a source-scene ownership test.
    bool(*cleanup_ready)(void*)=nullptr;
    uint32_t(*retain)(void*)=nullptr;void*(*target)(uint32_t)=nullptr;void(*release)(uint32_t)=nullptr;
};
class RendererPublication {
    struct Reader {uint64_t token=0;};
    static constexpr size_t max_readers=16;
    inline static uint64_t next_reader_=0;
    RendererPublicationApi api_{};void* context_=nullptr;
    void* additional_=nullptr;void* source_=nullptr;void* private_=nullptr;
    uint32_t roots_[3]{};Reader readers_[max_readers]{};size_t reader_count_=0;
    uint64_t generation_=0;bool configured_=false,published_=false,invalidated_=false;
    const char* error_="none";
    Result fail(Result value,const char* text){error_=text;return value;}
    bool references_current()const{
        void* values[3]={additional_,source_,private_};
        for(size_t i=0;i<3;++i)if(!roots_[i]||api_.target(roots_[i])!=values[i])return false;
        return true;
    }
    bool current()const{return configured_&&!invalidated_&&references_current()
        &&api_.source_current(context_)&&api_.private_ready(context_);}
public:
    bool active()const{return configured_;}
    bool published()const{return configured_&&published_&&!invalidated_;}
    size_t readers()const{return reader_count_;}
    uint64_t generation()const{return generation_;}
    const char* error()const{return error_;}
    Result configure(RendererPublicationApi api,void* context,void* additional,void* source,void* replacement,uint64_t generation){
        if(configured_)return fail(Result::invalid,"private_renderer_already_owned");
        if(!context||!additional||!source||!replacement||source==replacement||!generation
            ||!api.source_current||!api.private_ready||!api.original_renderer||!api.cleanup_ready
            ||!api.retain||!api.target||!api.release)return fail(Result::unsupported,"private_renderer_publication_api_unavailable");
        api_=api;context_=context;additional_=additional;source_=source;private_=replacement;generation_=generation;configured_=true;
        void* values[3]={additional,source,replacement};
        for(size_t i=0;i<3;++i){roots_[i]=api_.retain(values[i]);if(!roots_[i]||api_.target(roots_[i])!=values[i])return fail(Result::failed,"private_renderer_publication_root_failed");}
        if(!current())return fail(Result::stale,"private_renderer_source_changed");
        error_="none";return Result::ok;
    }
    Result publish(){
        if(!current())return fail(Result::stale,"private_renderer_source_changed");
        // This is the verified raw original getter. It must never resolve back
        // through the publication currently being prepared.
        void* actual=nullptr;
        try{actual=api_.original_renderer(context_,additional_);}
        catch(...){before_source_change();error_="private_renderer_original_getter_failed";throw;}
        if(!current()||actual!=source_)return fail(Result::stale,"private_renderer_source_changed");
        published_=true;error_="none";return Result::ok;
    }
    RendererResolution resolve(void* additional){
        if(!published()||additional!=additional_)return {};
        if(!current()){before_source_change();error_="private_renderer_source_changed";return {RendererResolve::error,nullptr,false};}
        void* actual=nullptr;
        try{actual=api_.original_renderer(context_,additional);}
        catch(...){before_source_change();error_="private_renderer_original_getter_failed";throw;}
        if(!current()||actual!=source_){
            before_source_change();error_="private_renderer_source_changed";
            // A normal source getter has already executed. Preserve its exact
            // result (including null) instead of calling it a second time.
            return {RendererResolve::error,actual,true};
        }
        return {RendererResolve::owned,private_,true};
    }
    uint64_t begin_draw(void* renderer){
        if(!published()||renderer!=private_||!current()||reader_count_==max_readers||next_reader_==~uint64_t(0)){
            error_="private_renderer_draw_not_owned";return 0;
        }
        for(auto& reader:readers_)if(!reader.token){reader.token=++next_reader_;++reader_count_;return reader.token;}
        error_="private_renderer_reader_limit";return 0;
    }
    bool end_draw(uint64_t token){
        // A reentrant pre-init withdraws publication but cannot discard the
        // private renderer while its former draw is still on the native stack.
        // Ending that exact reader never reads or writes the replacement scene.
        if(!token)return false;
        for(auto& reader:readers_)if(reader.token==token){reader.token=0;--reader_count_;return true;}
        return false;
    }
    void before_source_change()noexcept{published_=false;invalidated_=true;}
    void abandon_globals_before_source_change()noexcept{before_source_change();}
    void withdraw()noexcept{published_=false;}
    Result release(bool){
        if(!configured_)return Result::ok;
        published_=false;
        if(reader_count_||!api_.cleanup_ready(context_))return fail(Result::waiting,"private_renderer_cleanup_pending");
        // No source query, getter, setter, graph rebuild or replacement-camera
        // lookup belongs on either cleanup path.
        for(auto& root:roots_)if(root){const auto value=root;root=0;api_.release(value);}
        *this=RendererPublication{};return Result::ok;
    }
};
class Scope {
    struct Ref {uint32_t offset=0,root=0;void* value=nullptr;};
    struct Node {void* object=nullptr;uint32_t root=0;Description description{};uint8_t* saved=nullptr;Ref* refs=nullptr;ComponentImage component{};uint32_t transform_root=0,game_object_root=0;int32_t normalized_values[4]{};bool have_component=false,normalized=false;};
    struct Audio {void* source=nullptr;uint32_t root=0,clip_root=0;void* clip=nullptr;int32_t samples=0;float volume=0,pitch=1;bool playing=false,paused=false,loop=false,mute=false,timeline=false,applied=false;};
    Api api_{};Owner owner_{};void* context_=nullptr;
    Node* nodes_=nullptr;size_t count_=0,bytes_=0,references_=0;
    Mixer mixers_[max_mixers]{};size_t mixers_count_=0;
    Audio audio_[2]{};LensImage lens_{};GlobalImage globals_{};uint32_t global_roots_[2]{},owner_roots_[6]{};
    int32_t frame_=0;bool configured_=false,captured_=false,changed_=false,reset_=false,managed_restored_=false,native_restored_=false,restored_=false;
    bool camera_granted_=false,render_granted_=false,render_consumed_=false;uint64_t tick_=0;bool have_tick_=false;
    const char* error_="none";
    Result fail(Result value,const char* text){error_=text;return value;}
    bool current()const{return configured_&&api_.current(context_,owner_);}
    bool complete()const{
        const auto& a=api_.audio;
        return api_.current&&api_.held&&api_.mapped&&api_.alive&&api_.retain&&api_.target&&api_.release&&api_.admit
            &&api_.roots&&api_.describe&&api_.follow&&api_.write_reference&&api_.component_capture&&api_.component_restore
            &&api_.component_verify&&api_.lens_capture&&api_.lens_restore&&api_.lens_verify&&api_.global_capture&&api_.global_restore&&api_.global_verify&&api_.mixers&&api_.frame_count
            &&api_.reset_history&&a.clip&&a.set_clip&&a.samples&&a.set_samples&&a.playing&&a.volume&&a.set_volume
            &&a.pitch&&a.set_pitch&&a.loop&&a.set_loop&&a.mute&&a.set_mute&&a.play&&a.stop&&a.pause&&a.unpause&&a.paused&&a.timeline_output
            &&a.clip_samples&&a.state_supported;
    }
    bool root(uint32_t& handle,void* object){if(!object)return false;handle=api_.retain(object);return handle&&api_.target(handle)==object;}
    bool description_current(const Node& node){
        if(!node.root||api_.target(node.root)!=node.object)return false;
        Description value{};if(!api_.describe(context_,node.object,value))return false;
        const auto& old=node.description;
        if(value.klass!=old.klass||value.data!=old.data||value.bytes!=old.bytes||value.references!=old.references
            ||value.unity_component!=old.unity_component||value.role!=old.role||value.identity_offset!=old.identity_offset
            ||value.next_id_offset!=old.next_id_offset||value.last_frame_offset!=old.last_frame_offset||value.window_frame_offset!=old.window_frame_offset)return false;
        for(size_t i=0;i<old.references;++i)if(value.reference_offsets[i]!=old.reference_offsets[i])return false;
        return api_.mapped(value.data,value.bytes,true)&&(!old.unity_component||api_.alive(node.object));
    }
    Result append(void* object){
        if(!object)return Result::ok;
        for(size_t i=0;i<count_;++i)if(nodes_[i].object==object)return Result::ok;
        if(count_==max_nodes)return fail(Result::unsupported,"camera_state_node_limit");
        auto& node=nodes_[count_++];node.object=object;
        if(!root(node.root,object))return fail(Result::failed,"camera_state_root_failed");
        if(!api_.describe(context_,object,node.description))return fail(Result::unsupported,"camera_state_schema_unavailable");
        const auto& d=node.description;
        if(!d.klass||!d.data||!d.bytes||d.bytes>max_bytes-bytes_||d.references>max_node_refs
            ||d.references>max_references-references_||!api_.mapped(d.data,d.bytes,true))
            return fail(Result::unsupported,"camera_state_layout_invalid");
        uint32_t previous=0;
        for(size_t i=0;i<d.references;++i){
            const uint32_t at=d.reference_offsets[i];
            if(at>d.bytes||sizeof(void*)>d.bytes-at||(i&&at<previous+sizeof(void*))
                ||((reinterpret_cast<uintptr_t>(d.data)+at)&(alignof(void*)-1)))return fail(Result::unsupported,"camera_state_ref_layout_invalid");
            previous=at;
        }
        node.saved=static_cast<uint8_t*>(::malloc(d.bytes));if(!node.saved)return fail(Result::failed,"camera_state_allocation_failed");
        ::memcpy(node.saved,d.data,d.bytes);bytes_+=d.bytes;references_+=d.references;
        if(d.references){node.refs=static_cast<Ref*>(::malloc(d.references*sizeof(Ref)));if(!node.refs)return fail(Result::failed,"camera_state_allocation_failed");for(size_t i=0;i<d.references;++i)node.refs[i]=Ref{};}
        for(size_t i=0;i<d.references;++i){auto& ref=node.refs[i];ref.offset=d.reference_offsets[i];::memcpy(&ref.value,node.saved+ref.offset,sizeof(void*));if(ref.value&&!root(ref.root,ref.value))return fail(Result::failed,"camera_state_reference_root_failed");}
        if(d.unity_component){if(!api_.component_capture(context_,object,node.component))return fail(Result::unsupported,"camera_component_snapshot_failed");
            if(!root(node.transform_root,node.component.transform)||!root(node.game_object_root,node.component.game_object))return fail(Result::failed,"camera_component_reference_root_failed");
            node.have_component=true;}
        return current()?Result::ok:fail(Result::stale,"selected_scene_changed");
    }
    Result capture_audio(Audio& out,void* source){
        if(!source)return Result::ok;
        out.source=source;if(!api_.alive(source)||!root(out.root,source))return fail(Result::stale,"camera_audio_source_changed");
        const auto& a=api_.audio;out.clip=a.clip(source,nullptr);out.playing=a.playing(source,nullptr);
        if(!a.paused(source,&out.paused))return fail(Result::unsupported,"camera_audio_pause_state_unavailable");
        if(!a.state_supported(context_,source,out.clip!=nullptr,out.playing,out.paused))return fail(Result::unsupported,"camera_audio_native_state_unclosed");
        out.volume=a.volume(source,nullptr);out.pitch=a.pitch(source,nullptr);out.loop=a.loop(source,nullptr);out.mute=a.mute(source,nullptr);
        if(!__builtin_isfinite(out.volume)||out.volume<0||out.volume>1||!__builtin_isfinite(out.pitch)||out.pitch< -3||out.pitch>3)
            return fail(Result::unsupported,"camera_audio_properties_invalid");
        if(out.clip){if(!root(out.clip_root,out.clip))return fail(Result::failed,"camera_audio_clip_root_failed");out.samples=a.samples(source,nullptr);const int32_t length=a.clip_samples(out.clip,nullptr);if(out.samples<0||length<=0||out.samples>=length)return fail(Result::unsupported,"camera_audio_samples_invalid");}
        else {out.timeline=a.timeline_output(context_,source);
            if(out.timeline&&!a.timeline_logical_restored)
                return fail(Result::unsupported,"camera_timeline_audio_logical_api_unavailable");
            if(out.playing&&!out.timeline)
                return fail(Result::unsupported,"camera_clipless_audio_channel_unclosed");
        }
        return current()?Result::ok:fail(Result::stale,"selected_scene_changed");
    }
    Result restore_audio(Audio& state,bool playback_resumed){
        if(!state.source)return Result::ok;
        const auto& a=api_.audio;
        if(!current()||api_.target(state.root)!=state.source||!api_.alive(state.source)
            ||(state.clip&&api_.target(state.clip_root)!=state.clip))return fail(Result::stale,"camera_audio_source_changed");
        if(!state.applied){
            state.applied=true;
            if(a.clip(state.source,nullptr)!=state.clip)a.set_clip(state.source,state.clip,nullptr);
            if(!current())return fail(Result::stale,"selected_scene_changed");
            a.set_pitch(state.source,state.pitch,nullptr);a.set_loop(state.source,state.loop,nullptr);a.set_mute(state.source,state.mute,nullptr);
            if(state.clip){
                if(state.playing||state.paused)a.play(state.source,nullptr);else a.stop(state.source,nullptr);
                if(!current())return fail(Result::stale,"selected_scene_changed");
                a.pause(state.source,nullptr);a.set_samples(state.source,state.samples,nullptr);
                if(a.samples(state.source,nullptr)!=state.samples)return fail(Result::failed,"camera_audio_position_restore_failed");
            }
            // A clipless Timeline output is restored by its reconstructed
            // graph at saved source time. Never Play/Stop/seek such an output.
            if(state.paused)a.pause(state.source,nullptr);else a.unpause(state.source,nullptr);
            a.set_volume(state.source,state.volume,nullptr);
        }
        bool paused=false;
        if(!a.paused(state.source,&paused))return fail(Result::unsupported,"camera_audio_pause_state_unavailable");
        if(a.clip(state.source,nullptr)!=state.clip||paused!=state.paused||a.loop(state.source,nullptr)!=state.loop
            ||a.mute(state.source,nullptr)!=state.mute||a.volume(state.source,nullptr)!=state.volume||a.pitch(state.source,nullptr)!=state.pitch)
            return fail(Result::failed,"camera_audio_restore_mismatch");
        if(playback_resumed){
            if(state.timeline){
                if(!a.timeline_logical_restored||!a.timeline_logical_restored(context_,state.source,state.playing,state.paused))
                    return fail(Result::failed,"camera_timeline_audio_logical_restore_failed");
            }else if(a.playing(state.source,nullptr)!=state.playing)
                return fail(Result::failed,"camera_audio_playback_restore_failed");
        }
        if(state.clip&&(!state.playing||state.paused)&&a.samples(state.source,nullptr)!=state.samples)
            return fail(Result::failed,"camera_audio_position_restore_failed");
        return Result::ok;
    }
    static bool same_mixer(const Mixer& a,const Mixer& b){
        if(a.director!=b.director||a.brain!=b.brain||a.path_size!=b.path_size)return false;
        for(size_t i=0;i<a.path_size;++i)if(a.path[i]!=b.path[i])return false;
        return true;
    }
    bool managed_matches(const Node& node)const{
        if(!node.normalized)return false;
        const auto& d=node.description;
        const int32_t offsets[4]={d.identity_offset,d.next_id_offset,d.last_frame_offset,d.window_frame_offset};
        for(size_t j=0;j<d.bytes;++j){uint8_t expected=node.saved[j];
            for(size_t k=0;k<4;++k)if(offsets[k]>=0&&j>=static_cast<size_t>(offsets[k])&&j<static_cast<size_t>(offsets[k])+4)
                expected=reinterpret_cast<const uint8_t*>(&node.normalized_values[k])[j-offsets[k]];
            if(d.data[j]!=expected)return false;
        }
        return true;
    }
    Result restore_managed(){
        Mixer fresh[max_mixers]{};size_t number=0;
        if(!api_.mixers(context_,fresh,max_mixers,&number)||number!=mixers_count_)return fail(Result::unsupported,"camera_mixer_restore_mapping_unavailable");
        int32_t ids[max_mixers]{};int32_t maximum_id=0;
        for(size_t i=0;i<mixers_count_;++i){size_t found=number;
            for(size_t j=0;j<number;++j)if(same_mixer(mixers_[i],fresh[j])){if(found!=number)return fail(Result::unsupported,"camera_mixer_restore_mapping_ambiguous");found=j;}
            if(found==number||mixers_[i].id<0||fresh[found].id<0)return fail(Result::unsupported,"camera_mixer_restore_mapping_invalid");
            ids[i]=fresh[found].id;if(ids[i]>maximum_id)maximum_id=ids[i];
        }
        if(maximum_id==0x7fffffff)return fail(Result::unsupported,"camera_mixer_id_exhausted");
        const uint32_t elapsed=static_cast<uint32_t>(api_.frame_count())-static_cast<uint32_t>(frame_);
        struct Semantic {int32_t value[4]{};} semantic[max_nodes]{};
        // Preflight every identity and rooted reference before invoking native
        // activation callbacks. Saved bytes are immutable across retries.
        for(size_t i=0;i<count_;++i){const auto& node=nodes_[i];const auto& d=node.description;
            if(!description_current(node))return fail(Result::stale,"camera_state_object_changed");
            if(node.have_component&&(api_.target(node.transform_root)!=node.component.transform||api_.target(node.game_object_root)!=node.component.game_object))return fail(Result::stale,"camera_component_reference_changed");
            for(size_t j=0;j<d.references;++j)if(node.refs[j].root&&api_.target(node.refs[j].root)!=node.refs[j].value)return fail(Result::stale,"camera_state_reference_changed");
            const int32_t offsets[4]={d.identity_offset,d.next_id_offset,d.last_frame_offset,d.window_frame_offset};
            for(size_t j=0;j<4;++j)if(offsets[j]>=0){const size_t at=static_cast<size_t>(offsets[j]);
                if(at>d.bytes||4>d.bytes-at)return fail(Result::unsupported,"camera_semantic_layout_invalid");
                for(size_t k=0;k<d.references;++k)if(at<d.reference_offsets[k]+sizeof(void*)&&at+4>d.reference_offsets[k])return fail(Result::unsupported,"camera_semantic_reference_overlap");
                ::memcpy(&semantic[i].value[j],node.saved+at,4);
            }
            if(d.identity_offset>=0){if(d.role!=Role::brain_frame)return fail(Result::unsupported,"camera_frame_role_invalid");
                const int32_t old=semantic[i].value[0];bool match=old==0;
                for(size_t j=0;j<mixers_count_;++j)if(mixers_[j].id==old){semantic[i].value[0]=ids[j];match=true;break;}
                if(!match)return fail(Result::unsupported,"camera_frame_unowned_override");
            }
            if(d.next_id_offset>=0){if(d.role!=Role::brain)return fail(Result::unsupported,"camera_next_id_role_invalid");
                int32_t live=0;::memcpy(&live,d.data+d.next_id_offset,4);int32_t& next=semantic[i].value[1];
                if(next<0||live<0)return fail(Result::unsupported,"camera_next_id_invalid");
                if(next<live)next=live;
                if(next<=maximum_id)next=maximum_id+1;
            }
            if(d.last_frame_offset>=0){if(d.role!=Role::core_status&&d.role!=Role::tracker_status)return fail(Result::unsupported,"camera_frame_role_invalid");
                if(semantic[i].value[2]>=0){uint32_t normalized=static_cast<uint32_t>(semantic[i].value[2])+elapsed;::memcpy(&semantic[i].value[2],&normalized,4);}
            }
            if(d.window_frame_offset>=0){if(d.role!=Role::tracker_status)return fail(Result::unsupported,"camera_window_role_invalid");
                if(semantic[i].value[3]>=0){uint32_t normalized=static_cast<uint32_t>(semantic[i].value[3])+elapsed;::memcpy(&semantic[i].value[3],&normalized,4);}
            }
        }
        // Native activation callbacks must finish before restoring Core's
        // lists/caches. Each native operation revalidates scene ownership.
        for(size_t i=0;i<count_;++i)if(nodes_[i].have_component){if(!current()||!api_.component_restore(context_,nodes_[i].object,nodes_[i].component))return fail(Result::stale,"camera_component_restore_failed");}
        for(size_t i=0;i<2;++i)if(global_roots_[i]&&api_.target(global_roots_[i])!=(i?globals_.tracker_delete:globals_.tracker_status))return fail(Result::stale,"camera_global_reference_changed");
        if(!api_.global_restore(context_,globals_)||!api_.global_verify(context_,globals_))return fail(Result::failed,"camera_global_restore_mismatch");
        for(size_t i=0;i<count_;++i){auto& node=nodes_[i];const auto& d=node.description;if(!current()||!description_current(node))return fail(Result::stale,"camera_state_object_changed");
            size_t at=0;
            for(size_t j=0;j<d.references;++j){auto& ref=node.refs[j];if(ref.root&&api_.target(ref.root)!=ref.value)return fail(Result::stale,"camera_state_reference_changed");if(ref.offset>at)::memcpy(d.data+at,node.saved+at,ref.offset-at);api_.write_reference(node.object,reinterpret_cast<void**>(d.data+ref.offset),ref.value);at=ref.offset+sizeof(void*);}
            if(at<d.bytes)::memcpy(d.data+at,node.saved+at,d.bytes-at);
            const int32_t offsets[4]={d.identity_offset,d.next_id_offset,d.last_frame_offset,d.window_frame_offset};
            for(size_t j=0;j<4;++j){node.normalized_values[j]=semantic[i].value[j];if(offsets[j]>=0)::memcpy(d.data+offsets[j],&semantic[i].value[j],4);}
            // Verify normalized payload, including actual GC-barrier writes.
            node.normalized=true;if(!managed_matches(node))return fail(Result::failed,"camera_state_restore_mismatch");
        }
        return Result::ok;
    }
public:
    const char* error()const{return error_;}
    bool captured()const{return captured_;}bool restored()const{return restored_;}
    bool frame_granted()const{return configured_&&reset_&&camera_granted_;}
    // Abort may already have lost its source/clock. Revoke scalar permission
    // before any owner query or native/job fence; this performs no Unity call.
    void revoke_grants(){camera_granted_=render_granted_=false;}
    bool restoration_verified()const{return restored_;}
    bool active()const{return configured_;}
    bool admit(Api api,void* context,const Owner& owner){return api.current&&api.admit&&api.current(context,owner)&&api.admit(context,owner);}
    Result configure(Api api,void* context,const Owner& owner){
        if(configured_)return fail(Result::invalid,"camera_state_already_owned");
        api_=api;context_=context;owner_=owner;
        if(!context||!owner.player||!owner.director||!owner.camera||!owner.controller||!owner.brain||!owner.bgm||!owner.generation||!complete())return fail(Result::unsupported,"camera_state_api_unavailable");
        configured_=true;if(!current()||!api_.admit(context_,owner_))return fail(Result::unsupported,"camera_state_admission_failed");
        void* objects[6]={owner.player,owner.director,owner.camera,owner.controller,owner.brain,owner.bgm};
        for(size_t i=0;i<6;++i)if(!root(owner_roots_[i],objects[i]))return fail(Result::failed,"camera_state_owner_root_failed");
        nodes_=static_cast<Node*>(::malloc(max_nodes*sizeof(Node)));if(!nodes_)return fail(Result::failed,"camera_state_allocation_failed");for(size_t i=0;i<max_nodes;++i)nodes_[i]=Node{};
        error_="none";return Result::ok;
    }
    Result quiesce(){return current()&&api_.held(context_)?Result::ok:fail(current()?Result::waiting:Result::stale,current()?"original_engine_clock_not_held":"selected_scene_changed");}
    Result capture(){
        auto status=quiesce();if(status!=Result::ok)return status;if(captured_)return Result::ok;
        if(count_)return fail(Result::invalid,"camera_state_partial_capture");
        if(!api_.global_capture(context_,globals_))return fail(Result::unsupported,"camera_globals_unavailable");
        void* global_values[2]={globals_.tracker_status,globals_.tracker_delete};
        for(size_t i=0;i<2;++i)if(global_values[i]&&!root(global_roots_[i],global_values[i]))return fail(Result::failed,"camera_global_root_failed");
        void* roots[max_nodes]{};size_t roots_count=0;
        if(!api_.roots(context_,roots,max_nodes,&roots_count)||!roots_count||roots_count>max_nodes)return fail(Result::unsupported,"camera_state_roots_unavailable");
        for(size_t i=0;i<roots_count;++i){status=append(roots[i]);if(status!=Result::ok)return status;}
        for(size_t i=0;i<count_;++i){auto& node=nodes_[i];for(size_t j=0;j<node.description.references;++j){void* value=node.refs[j].value;if(!value)continue;auto mode=api_.follow(context_,node.object,value);if(mode==Follow::reject)return fail(Result::unsupported,"camera_state_unowned_reference");if(mode==Follow::owned){status=append(value);if(status!=Result::ok)return status;}}}
        if(!api_.lens_capture(context_,owner_.camera,lens_)||!api_.mixers(context_,mixers_,max_mixers,&mixers_count_)||mixers_count_>max_mixers)return fail(Result::unsupported,"camera_state_native_snapshot_failed");
        for(size_t i=0;i<mixers_count_;++i){if(mixers_[i].brain!=owner_.brain||mixers_[i].path_size>max_path||mixers_[i].id<0)return fail(Result::unsupported,"camera_state_mixer_identity_invalid");for(size_t j=0;j<i;++j)if(same_mixer(mixers_[i],mixers_[j])||mixers_[i].id==mixers_[j].id)return fail(Result::unsupported,"camera_state_mixer_identity_ambiguous");}
        // Reject foreign overrides during the read-only capture, before any
        // native audio/camera/source mutation or fresh-graph construction.
        for(size_t i=0;i<count_;++i){const auto& node=nodes_[i];const auto& d=node.description;
            if(d.identity_offset<0)continue;
            if(d.role!=Role::brain_frame||static_cast<size_t>(d.identity_offset)>d.bytes||4>d.bytes-static_cast<size_t>(d.identity_offset))return fail(Result::unsupported,"camera_frame_id_layout_invalid");
            int32_t id=0;::memcpy(&id,node.saved+d.identity_offset,4);bool owned=id==0;
            for(size_t j=0;j<mixers_count_;++j)if(id==mixers_[j].id){owned=true;break;}
            if(!owned)return fail(Result::unsupported,"camera_frame_unowned_override");
        }
        status=capture_audio(audio_[0],owner_.bgm);if(status!=Result::ok)return status;
        status=capture_audio(audio_[1],owner_.voice==owner_.bgm?nullptr:owner_.voice);if(status!=Result::ok)return status;
        frame_=api_.frame_count();captured_=true;error_="none";return Result::ok;
    }
    Result prepare(){
        auto status=quiesce();if(status!=Result::ok)return status;
        if(!captured_)return fail(Result::invalid,"camera_state_not_captured");
        changed_=true;
        for(auto& state:audio_)if(state.source){
            if(!current())return fail(Result::stale,"selected_scene_changed");
            api_.audio.set_volume(state.source,0,nullptr);
            if(!current())return fail(Result::stale,"selected_scene_changed");
            // Export audio is privately decoded. Stop the original native
            // source from continuing its direct DSP channel behind the mute.
            api_.audio.pause(state.source,nullptr);
        }
        return current()?Result::ok:fail(Result::stale,"selected_scene_changed");
    }
    Result reset(){auto status=quiesce();if(status!=Result::ok)return status;if(!captured_)return fail(Result::invalid,"camera_state_not_captured");if(reset_)return Result::ok;changed_=true;if(!api_.reset_history(context_,owner_))return fail(Result::unsupported,"camera_state_reset_failed");reset_=true;return Result::ok;}
    Result hold(){auto status=quiesce();if(status!=Result::ok)return status;camera_granted_=render_granted_=false;return Result::ok;}
    Result grant(uint64_t tick){if(!current()||!reset_)return fail(Result::stale,"camera_state_not_running");if(have_tick_&&(tick_==~uint64_t(0)||tick!=tick_+1))return fail(Result::invalid,"camera_state_tick_out_of_order");if(!have_tick_&&tick)return fail(Result::invalid,"camera_state_tick_out_of_order");tick_=tick;have_tick_=camera_granted_=render_granted_=true;render_consumed_=false;return Result::ok;}
    // Pure ticket bookkeeping. The source host must validate the exact camera,
    // epoch and native route before consuming this ticket. Each accepted simulation tick (60/120Hz)
    // renders once, including ticks omitted from a 30fps file.
    // Held readback retries reuse the completed target and do not render again.
    bool consume_render_grant(){
        if(!configured_||!captured_||!reset_||!render_granted_||render_consumed_)return false;
        render_consumed_=true;return true;
    }
    // Readback setup may finish after the accepted simulation loop. The host
    // revalidates source/domain before arming the first draw of this same tick.
    // This never reopens Brain/Core or repeats an already consumed draw.
    bool arm_render_retry(uint64_t tick){
        if(!configured_||!captured_||!reset_||!have_tick_||tick!=tick_||render_consumed_)return false;
        render_granted_=true;return true;
    }
    bool render_tick(uint64_t& value)const{
        if(!configured_||!reset_||!have_tick_)return false;
        value=tick_;return true;
    }
    bool permit_brain_update(void* brain){
        if(!configured_||brain!=owner_.brain)return true;
        // The native driver grants one loop. Preserve all natural original
        // callbacks within it (including SceneLoaded then LateUpdate); only
        // the original frame/filter cache decides duplicate camera work.
        return reset_&&camera_granted_&&current();
    }
    Result restore(){
        auto status=quiesce();if(status!=Result::ok)return status;if(!captured_)return Result::ok;
        if(!managed_restored_){status=restore_managed();if(status!=Result::ok)return status;managed_restored_=true;}
        if(!native_restored_){
            if(!api_.lens_restore(context_,owner_.camera,lens_)||!api_.lens_verify(context_,owner_.camera,lens_))return fail(Result::failed,"camera_lens_restore_failed");
            for(size_t i=0;i<count_;++i)if(nodes_[i].have_component&&!api_.component_verify(context_,nodes_[i].object,nodes_[i].component))return fail(Result::failed,"camera_component_restore_mismatch");
            native_restored_=true;
        }
        status=restore_audio(audio_[0],false);if(status!=Result::ok)return status;status=restore_audio(audio_[1],false);if(status!=Result::ok)return status;error_="none";return Result::ok;
    }
    Result verify_source_restored(){
        const auto quiet=quiesce();if(quiet!=Result::ok)return quiet;
        if(!captured_||!managed_restored_||!native_restored_)return fail(Result::invalid,"camera_state_restore_incomplete");
        for(size_t i=0;i<count_;++i)if(!description_current(nodes_[i])||!managed_matches(nodes_[i]))return fail(Result::failed,"camera_state_restore_mismatch");
        if(!api_.global_verify(context_,globals_)||!api_.lens_verify(context_,owner_.camera,lens_))return fail(Result::failed,"camera_state_restore_mismatch");
        for(size_t i=0;i<count_;++i)if(nodes_[i].have_component&&!api_.component_verify(context_,nodes_[i].object,nodes_[i].component))return fail(Result::failed,"camera_component_restore_mismatch");
        auto status=restore_audio(audio_[0],true);if(status!=Result::ok)return status;status=restore_audio(audio_[1],true);if(status!=Result::ok)return status;
        restored_=true;error_="none";return Result::ok;
    }
    Result release(bool scene_owned){
        if(!configured_)return Result::ok;
        if(scene_owned&&changed_&&!restored_){auto status=restore();if(status!=Result::ok)return status;}
        if(scene_owned&&changed_&&!restored_)return fail(Result::waiting,"camera_source_playback_unverified");
        if(nodes_){for(size_t i=0;i<count_;++i){auto& n=nodes_[i];for(size_t j=0;n.refs&&j<n.description.references;++j)if(n.refs[j].root)api_.release(n.refs[j].root);if(n.transform_root)api_.release(n.transform_root);if(n.game_object_root)api_.release(n.game_object_root);if(n.root)api_.release(n.root);::free(n.refs);::free(n.saved);}::free(nodes_);}
        for(auto& state:audio_){if(state.root)api_.release(state.root);if(state.clip_root)api_.release(state.clip_root);}
        for(auto& handle:global_roots_)if(handle)api_.release(handle);
        for(auto& handle:owner_roots_)if(handle)api_.release(handle);
        *this=Scope{};return Result::ok;
    }
};
} // namespace idoly_mp4_camera_state

// BEGIN_MP4_PRIVATE_VOLUME
// Selected-render Volume transaction. Embed in the existing Camera header.
// Pinned source: mp4-volume-isolation-audit/{inventory,camera-volume-methods,
// curve-inventory,generic-curve-methods,volume-isolation-proof}.json.
// This owns draw scratch, NOT arbitrary source Volume producers or a whole
// VolumeManager clone. Runtime source-profile/roster closure is mandatory.
namespace idoly_mp4_private_volume {
enum class Result { ok, waiting, invalid, stale, failed };
struct Frame {
    void* stack=nullptr;void* sorted=nullptr;void* sort_needed=nullptr;void* colliders=nullptr;
};
struct Api {
    void* context=nullptr;
    bool (*owner_thread)()=nullptr;bool (*current)(void*,uint64_t)=nullptr;
    bool (*routes_verified)(void*)=nullptr;
    bool (*source_inputs_current)(void*,void*)=nullptr;
    uint32_t (*retain)(void*)=nullptr;void* (*target)(uint32_t)=nullptr;void (*release)(uint32_t)=nullptr;
    bool (*reference)(void*,uint32_t,void**)=nullptr;
    void (*reference_set)(void*,uint32_t,void*)=nullptr; // original GC barrier
    bool (*mode)(void*,int32_t*)=nullptr;void (*mode_set)(void*,int32_t)=nullptr;
    bool (*manager_type)(void*)=nullptr;bool (*camera_type)(void*)=nullptr;
    // A factory retains partial allocations independently until dispose_frame.
    // New, empty actual closed generic dictionaries/list are required per draw.
    bool (*create_frame)(void*,void*,Frame*)=nullptr;
    bool (*frame_owned)(void*,const Frame*)=nullptr;
    bool (*frame_fenced)(void*,const Frame*)=nullptr;
    bool (*dispose_frame)(void*,const Frame*)=nullptr;
    void (*update_original)(void*,void*)=nullptr; // original static (Camera,UACD)
    // ReplaceData/OverrideData can alias source reference payloads. Rebind all
    // admitted mutable reference-valued parameters AFTER the original update.
    // Fresh TextureCurve must own a freshly constructed native AnimationCurve,
    // no source texture/looping curve; verify exact keys/wrap/scalars. Unknown
    // mutable reference types reject. Immutable source textures stay read-only.
    bool (*privatize_payloads)(void*,void*)=nullptr;
};
class Scope {
    struct Ref {void* object=nullptr;uint32_t field=0;void* ambient=nullptr;void* private_value=nullptr;
        uint32_t ambient_root=0;bool duty=false;};
    Api api_{};Frame frame_{};void* manager_=nullptr;void* camera_=nullptr;
    uint32_t manager_root_=0,camera_root_=0,frame_roots_[4]{};
    Ref refs_[6]{};void* readonly_[3]{};uint32_t readonly_roots_[3]{};
    int32_t ambient_mode_=0,private_mode_=0;bool mode_duty_=false;
    uint64_t epoch_=0,sequence_=0,token_=0;
    bool configured_=false,active_=false,prepared_=false,suspended_=false,failed_=false,frame_duty_=false,invalidated_=false,orphaned_=false;
    const char* error_="none";
    bool fail(const char* message){failed_=true;error_=message;return false;}
    bool complete_api()const{return api_.owner_thread&&api_.current&&api_.routes_verified&&api_.source_inputs_current
        &&api_.retain&&api_.target&&api_.release&&api_.reference&&api_.reference_set&&api_.mode&&api_.mode_set
        &&api_.manager_type&&api_.camera_type&&api_.create_frame&&api_.frame_owned&&api_.frame_fenced
        &&api_.dispose_frame&&api_.update_original&&api_.privatize_payloads;}
    bool thread()const{return api_.owner_thread&&api_.owner_thread();}
    bool roots()const{return manager_root_&&camera_root_&&api_.target(manager_root_)==manager_
        &&api_.target(camera_root_)==camera_&&api_.manager_type(manager_)&&api_.camera_type(camera_);}
    bool owner()const{return configured_&&thread()&&roots()&&api_.current(api_.context,epoch_)
        &&api_.routes_verified(api_.context)&&api_.source_inputs_current(api_.context,manager_);}
    bool frame_roots()const{
        void* values[]={frame_.stack,frame_.sorted,frame_.sort_needed,frame_.colliders};
        for(size_t i=0;i<4;++i)if(!values[i]||!frame_roots_[i]||api_.target(frame_roots_[i])!=values[i])return false;
        return api_.frame_owned(api_.context,&frame_);
    }
    bool readonly_current()const{
        constexpr uint32_t fields[]={24,40,56};
        for(size_t i=0;i<3;++i){void* value=nullptr;
            if(!api_.reference(manager_,fields[i],&value)||value!=readonly_[i]
                ||(value&&(!readonly_roots_[i]||api_.target(readonly_roots_[i])!=value)))return false;}
        return true;
    }
    void drop_ambient(){
        for(auto& r:refs_)if(r.ambient_root){api_.release(r.ambient_root);r.ambient_root=0;}
        for(auto& root:readonly_roots_)if(root){api_.release(root);root=0;}
    }
    bool capture_ambient(){
        drop_ambient();
        const Ref layout[]={ {manager_,16,nullptr,frame_.stack,0,false},
            {manager_,32,nullptr,frame_.sorted,0,false},{manager_,48,nullptr,frame_.sort_needed,0,false},
            {manager_,64,nullptr,frame_.colliders,0,false},{manager_,72,nullptr,frame_.stack,0,false},
            {camera_,120,nullptr,nullptr,0,false} };
        for(size_t i=0;i<6;++i){refs_[i]=layout[i];auto& r=refs_[i];
            if(!api_.reference(r.object,r.field,&r.ambient))return fail("private_volume_ambient_unreadable");
            if(r.ambient){r.ambient_root=api_.retain(r.ambient);
                if(!r.ambient_root||api_.target(r.ambient_root)!=r.ambient)return fail("private_volume_ambient_root_failed");}}
        constexpr uint32_t fields[]={24,40,56};
        for(size_t i=0;i<3;++i){if(!api_.reference(manager_,fields[i],&readonly_[i]))return false;
            if(readonly_[i]){readonly_roots_[i]=api_.retain(readonly_[i]);
                if(!readonly_roots_[i]||api_.target(readonly_roots_[i])!=readonly_[i])return false;}}
        return api_.mode(camera_,&ambient_mode_)&&ambient_mode_>=0&&ambient_mode_<=2;
    }
    bool set(Ref& r,void* value){
        r.private_value=value;r.duty=true; // BEFORE a barrier which may write then throw.
        api_.reference_set(r.object,r.field,value);void* live=nullptr;
        return api_.reference(r.object,r.field,&live)&&live==value;
    }
    bool set_mode(int32_t mode){mode_duty_=true;private_mode_=mode;api_.mode_set(camera_,mode);int32_t live=-1;
        return api_.mode(camera_,&live)&&live==mode;}
    bool installed()const{
        for(const auto& r:refs_){void* live=nullptr;
            if(!r.duty||!api_.reference(r.object,r.field,&live)||live!=r.private_value)return false;}
        int32_t mode=-1;return mode_duty_&&api_.mode(camera_,&mode)&&mode==1&&readonly_current();
    }
    bool bind(bool compute){
        if(!capture_ambient())return fail("private_volume_ambient_capture_failed");
        active_=true;suspended_=false;
        // Order is important: never expose a nonnull ambient camera stack to
        // the original EveryFrame route, which would dispose that stack.
        if(!set(refs_[5],nullptr)||!set_mode(0))return fail("private_volume_camera_bind_failed");
        for(size_t i=0;i<5;++i)if(!set(refs_[i],refs_[i].private_value))return fail("private_volume_manager_bind_failed");
        if(compute){
            api_.update_original(api_.context,camera_);
            if(!owner()||!readonly_current())return fail("private_volume_update_source_changed");
            // Natural EveryFrame code must have selected only our stack, and
            // must not have allocated/disposed a cached camera stack.
            void* stack=nullptr;void* cached=nullptr;
            if(!api_.reference(manager_,16,&stack)||stack!=frame_.stack
                ||!api_.reference(camera_,120,&cached)||cached)return fail("private_volume_update_route_changed");
            if(!api_.privatize_payloads(api_.context,frame_.stack)||!frame_roots())return fail("private_volume_payload_isolation_failed");
            prepared_=true;
        }
        if(invalidated_||!owner()||!readonly_current())return fail("private_volume_payload_source_changed");
        // The natural outer renderer still invokes UpdateVolumeFramework.
        // ViaScripting uses our prepared cached stack, with no second reset or
        // interpolation that could alias profile TextureCurve values again.
        if(!set(refs_[5],frame_.stack)||!set_mode(1)||!installed())return fail("private_volume_cached_bind_failed");
        return true;
    }
    bool unbind(){
        if(!active_)return true;
        // This is also the before-source-init handoff. Use the rooted exact
        // objects and compare-before-restore; do not require the old scene to
        // remain current, and never overwrite an unrelated supersession.
        if(!thread()||!roots()||!api_.routes_verified(api_.context))return fail("private_volume_restore_owner_unavailable");
        bool good=true;
        for(size_t i=6;i>0;--i){auto& r=refs_[i-1];if(!r.duty)continue;
            try{void* live=nullptr;
                if(!api_.reference(r.object,r.field,&live)){good=false;continue;}
                if(live!=r.private_value&&live!=r.ambient){r.duty=false;good=false;continue;}
                if(live==r.private_value)api_.reference_set(r.object,r.field,r.ambient);
                if(!api_.reference(r.object,r.field,&live)||live!=r.ambient){good=false;continue;}
                r.duty=false;
            }catch(...){good=false;}}
        if(mode_duty_){try{int32_t mode=-1;
            if(!api_.mode(camera_,&mode))good=false;
            else if(mode!=private_mode_&&mode!=ambient_mode_){mode_duty_=false;good=false;}
            else{if(mode!=ambient_mode_)api_.mode_set(camera_,ambient_mode_);
                if(!api_.mode(camera_,&mode)||mode!=ambient_mode_)good=false;else mode_duty_=false;}
        }catch(...){good=false;}}
        bool pending=mode_duty_;for(const auto& r:refs_)pending=pending||r.duty;
        active_=pending;
        if(!good)return fail("private_volume_ambient_restore_failed");
        return !active_;
    }
    Result retire_frame(){
        if(active_||suspended_)return Result::invalid;
        if(!frame_duty_)return Result::ok;
        if(!api_.frame_fenced(api_.context,&frame_))return Result::waiting;
        // Host disposal inspects every parameter and detaches any source alias
        // even after partial privatization; it must never Release source curves.
        if(!api_.dispose_frame(api_.context,&frame_))return Result::failed;
        for(auto& root:frame_roots_)if(root){api_.release(root);root=0;}
        frame_={};prepared_=false;frame_duty_=false;return Result::ok;
    }
public:
    Scope()=default;Scope(const Scope&)=delete;Scope& operator=(const Scope&)=delete;
    const char* error()const{return error_;}bool active()const{return active_;}
    bool prepared()const{return prepared_;}bool suspended()const{return suspended_;}
    // This is a scalar lease ledger, not a GPU fence or actual-field proof.
    // Final factory destruction must additionally inspect all rooted global
    // slots for aliases and fence its submitted GPU/readback work.
    bool globals_withdrawn()const noexcept{
        if(active_||suspended_||orphaned_||mode_duty_)return false;
        for(const auto& r:refs_)if(r.duty)return false;
        return true;
    }
    bool configure(Api api,uint64_t epoch,void* manager,void* camera){
        if(configured_||manager_root_||camera_root_||frame_duty_||active_||suspended_||orphaned_||!epoch||!manager||!camera)return false;
        // A fully released scope can serve another job. Keep the monotonic
        // token sequence, but no failure/handoff flag or old receiver tuple
        // may leak into that job or authorize an old finally callback.
        failed_=invalidated_=prepared_=mode_duty_=false;token_=0;error_="none";
        for(auto& r:refs_)r={};
        for(auto& value:readonly_)value=nullptr;
        api_=api;epoch_=epoch;manager_=manager;camera_=camera;
        if(!complete_api()||!thread()||!api_.routes_verified(api_.context)
            ||!api_.manager_type(manager)||!api_.camera_type(camera))return fail("private_volume_configuration_unverified");
        manager_root_=api_.retain(manager);camera_root_=api_.retain(camera);
        configured_=true;return owner();
    }
    Result begin_draw(uint64_t* token){
        if(token)*token=0;
        if(!token||failed_||invalidated_||active_||suspended_||!owner()||sequence_==~uint64_t(0))return Result::invalid;
        const Result retired=retire_frame();if(retired!=Result::ok)return retired;
        try{
            frame_duty_=true;
            if(!api_.create_frame(api_.context,manager_,&frame_))return fail("private_volume_frame_creation_failed"),Result::failed;
            void* values[]={frame_.stack,frame_.sorted,frame_.sort_needed,frame_.colliders};
            for(size_t i=0;i<4;++i){if(!values[i]||!(frame_roots_[i]=api_.retain(values[i]))
                ||api_.target(frame_roots_[i])!=values[i])return fail("private_volume_frame_root_failed"),Result::failed;}
            if(!frame_roots())return fail("private_volume_frame_not_owned"),Result::failed;
            token_=++sequence_;
            if(!bind(true)){unbind();return Result::failed;}
            *token=token_;return Result::ok;
        }catch(...){fail("private_volume_begin_exception");try{unbind();}catch(...){}return Result::failed;}
    }
    bool end_draw(uint64_t token){
        if(!token||token!=token_||suspended_||invalidated_)return false;
        if(!active_)return !failed_;
        bool good=false;try{good=installed()&&owner();}catch(...){good=false;}
        const bool restored=unbind();
        if(!good)fail("private_volume_draw_source_changed");
        return good&&restored&&!failed_;
    }
    // A nested/unowned camera must see ambient stack/scratch. Its actual
    // changes are captured as a NEW ambient baseline when our draw resumes.
    bool suspend(uint64_t token){
        if(!token||token!=token_||!active_||suspended_||!installed()||!owner())return false;
        if(!unbind())return false;
        suspended_=true;return true;
    }
    bool resume(uint64_t token){
        if(!token||token!=token_||active_||!suspended_||failed_||!prepared_||!owner()||!frame_roots())return false;
        try{if(!bind(false)){unbind();return false;}return true;}
        catch(...){fail("private_volume_resume_exception");try{unbind();}catch(...){}return false;}
    }
    bool before_source_change(){
        invalidated_=true;suspended_=false;
        return !orphaned_&&unbind();
    }
    // Exceptional lifecycle catch: no Unity/GC/field query or setter. Old
    // finally paths must never restore a baseline over replacement init.
    // Any unresolved published reference keeps its resources quarantined.
    void abandon_globals()noexcept{
        bool pending=mode_duty_;
        for(const auto& r:refs_)pending=pending||r.duty;
        orphaned_=orphaned_||pending;invalidated_=failed_=true;
        active_=suspended_=false;error_="private_volume_handoff_abandoned";
    }
    Result cleanup(){
        if(orphaned_)return Result::waiting;
        if(!thread())return Result::invalid;
        if(!before_source_change())return Result::failed;
        const Result result=retire_frame();if(result!=Result::ok)return result;
        drop_ambient();
        if(camera_root_)api_.release(camera_root_);
        if(manager_root_)api_.release(manager_root_);
        camera_root_=manager_root_=0;configured_=false;return Result::ok;
    }
};
} // namespace idoly_mp4_private_volume
// END_MP4_PRIVATE_VOLUME

// BEGIN_MP4_PRIVATE_RENDER_CONSTRUCTION
// Bounded private-render constructor ownership component. Embed in the existing
// Camera header; it is NOT a whole renderer/RTHandle/ComputeShader snapshot.
// Host must verify the exact original ctor route, all source shader inputs,
// no user renderer-feature callbacks, and the two before-original receiver hooks.
namespace idoly_mp4_private_render_construction {
constexpr size_t max_materials=64,max_libraries=8;
struct Api {
    void* context=nullptr;
    bool (*owner_thread)()=nullptr;bool (*current)(void*,uint64_t)=nullptr;
    bool (*routes_verified)(void*)=nullptr;bool (*constructor_admitted)(void*)=nullptr;
    uint32_t (*retain)(void*)=nullptr;void* (*target)(uint32_t)=nullptr;void (*release)(uint32_t)=nullptr;
    bool (*mapped)(const void*,size_t,bool)=nullptr;
    bool (*int32_array7)(void*,void**)=nullptr;
    void* (*static_get)(void*,unsigned)=nullptr;
    // Exact original static object-reference ABI: object itself, NOT &object.
    void (*static_set_ref)(void*,unsigned,void*)=nullptr;
    bool (*root_type)(void*,void*)=nullptr;void* (*allocate_root)(void*)=nullptr;
    bool (*construct_original)(void*,void*)=nullptr;
    bool (*root_complete)(void*,void*)=nullptr;
    // Both observers run BEFORE the retained original ctor. A fresh Material
    // must have nativePtr==0. Admission maps actual shader/source ctor context,
    // not simply arbitrary Material/Shader instances in the process.
    bool (*fresh_material_receiver)(void*,void*,void*)=nullptr;
    bool (*fresh_library_receiver)(void*,void*)=nullptr;
    bool (*material_alive)(void*)=nullptr;void (*material_destroy)(void*)=nullptr;
    bool (*cleanup_fenced)(void*)=nullptr;
};
class Factory {
    struct StaticArray {void* object=nullptr;void* data=nullptr;uint32_t root=0;int32_t values[7]{};bool duty=false;};
    struct Resource {void* object=nullptr;uint32_t root=0;};
    Api api_{};uint64_t epoch_=0;Resource root_{},materials_[max_materials]{},libraries_[max_libraries]{};
    StaticArray arrays_[2]{};size_t material_count_=0,library_count_=0,expected_materials_=0;
    bool active_=false,constructed_=false,published_=false,failed_=false,static_restored_=false,static_abandoned_=false,constructing_=false,quarantined_=false;
    const char* error_="none";
    bool fail(const char* error){error_=error;failed_=true;return false;}
    bool owner()const{return api_.owner_thread&&api_.owner_thread()&&api_.current&&api_.current(api_.context,epoch_);}
    bool root_current(const Resource& r)const{return r.root&&api_.target(r.root)==r.object;}
    bool complete_api()const{return api_.owner_thread&&api_.current&&api_.routes_verified&&api_.constructor_admitted
        &&api_.retain&&api_.target&&api_.release&&api_.mapped&&api_.int32_array7&&api_.static_get&&api_.static_set_ref
        &&api_.root_type&&api_.allocate_root&&api_.construct_original&&api_.root_complete
        &&api_.fresh_material_receiver&&api_.fresh_library_receiver&&api_.material_alive&&api_.material_destroy&&api_.cleanup_fenced;}
    bool inspect(void* object,void*& data)const{return object&&api_.int32_array7(object,&data)&&data&&api_.mapped(data,28,true);}
    bool hold(Resource& r,void* value){r.object=value;r.root=api_.retain(value);return root_current(r);}
    void drop(Resource& r){if(r.root)api_.release(r.root);r={};}
    bool current_new_arrays()const{
        for(unsigned i=0;i<2;++i){void* object=api_.static_get(api_.context,i);void* data=nullptr;
            if(!inspect(object,data)||::memcmp(data,arrays_[i].values,28))return false;}
        return true;
    }
public:
    Factory()=default;Factory(const Factory&)=delete;Factory& operator=(const Factory&)=delete;
    // No implicit destructor cleanup: a published private renderer may still be
    // used by GPU work. Caller owns explicit post-fence release/retirement.
    const char* error()const{return error_;}bool active()const{return active_;}
    bool constructed()const{return constructed_;}bool published()const{return published_;}
    bool construction_in_progress()const{return constructing_;}bool globals_abandoned()const{return static_abandoned_;}
    size_t material_count()const{return material_count_;}size_t library_count()const{return library_count_;}
    void* root()const{return root_current(root_)?root_.object:nullptr;}
    bool static_restored()const{return static_restored_&&!static_abandoned_;}
    bool owns_material(void* object)const{for(size_t i=0;i<material_count_;++i)if(materials_[i].object==object)return root_current(materials_[i])&&api_.material_alive(object);return false;}
    bool owns_library(void* object)const{for(size_t i=0;i<library_count_;++i)if(libraries_[i].object==object)return root_current(libraries_[i]);return false;}
    bool begin(Api api,uint64_t epoch,size_t expected_materials){
        if(active_||root_.root||material_count_||library_count_||!epoch||!expected_materials||expected_materials>max_materials)return false;
        api_=api;epoch_=epoch;expected_materials_=expected_materials;failed_=constructed_=published_=false;static_restored_=static_abandoned_=constructing_=quarantined_=false;error_="none";
        if(!complete_api()||!owner()||!api_.routes_verified(api_.context)||!api_.constructor_admitted(api_.context))return fail("private_render_ctor_not_admitted");
        for(unsigned i=0;i<2;++i){auto& a=arrays_[i];a.object=api_.static_get(api_.context,i);
            if(!inspect(a.object,a.data)||!(a.root=api_.retain(a.object))||api_.target(a.root)!=a.object)return fail("private_render_static_array_unavailable");
            ::memcpy(a.values,a.data,28);
        }
        // Establish rollback duty BEFORE any original constructor runs. Even
        // a throw between the two static assignments cannot lose this lease.
        for(auto& a:arrays_)a.duty=true;
        active_=true;return true;
    }
    // Called by exact Material(Shader) hook only inside this synchronous owner
    // construction lease, before original native material creation can throw.
    bool material_before(void* receiver,void* shader){
        if(!active_||failed_||!owner()||!api_.fresh_material_receiver(api_.context,receiver,shader))return fail("private_render_material_receiver_rejected");
        for(size_t i=0;i<material_count_;++i)if(materials_[i].object==receiver)return fail("private_render_material_receiver_reused");
        if(material_count_==max_materials||material_count_==expected_materials_)return fail("private_render_material_limit");
        auto& r=materials_[material_count_];if(!hold(r,receiver)){r={};return fail("private_render_material_root_failed");}
        ++material_count_;
        return true;
    }
    bool library_before(void* receiver){
        if(!active_||failed_||!owner()||!api_.fresh_library_receiver(api_.context,receiver))return fail("private_render_library_receiver_rejected");
        for(size_t i=0;i<library_count_;++i)if(libraries_[i].object==receiver)return fail("private_render_library_receiver_reused");
        if(library_count_==max_libraries)return fail("private_render_library_limit");
        auto& r=libraries_[library_count_];if(!hold(r,receiver)){r={};return fail("private_render_library_root_failed");}
        ++library_count_;
        return true;
    }
    // Exception observer fallback. No source/Unity/static getter/setter call;
    // old finally is forbidden from overwriting newly initialized scene refs.
    void abandon_static_before_source_change(){
        for(auto& a:arrays_)a.duty=false;
        static_abandoned_=true;quarantined_=true;static_restored_=false;failed_=true;active_=false;error_="private_render_static_handoff_abandoned";
    }
    bool restore_static(){
        if(static_abandoned_)return false; // Never report source restoration after abandonment.
        bool duty=false;for(const auto& a:arrays_)duty|=a.duty;
        if(!duty){static_restored_=true;return true;}
        if(!api_.owner_thread||!api_.owner_thread()||!api_.routes_verified||!api_.routes_verified(api_.context))return false;
        // This process-wide source class is pinned separately from scene epoch.
        // Scene handoff hook must call this before original new-scene init;
        // do not wait for the old constructor stack to unwind after handoff.
        try{for(unsigned i=0;i<2;++i){auto& a=arrays_[i];if(!a.duty)continue;void* data=nullptr;
            if(!a.root||api_.target(a.root)!=a.object||!inspect(a.object,data)||data!=a.data)return fail("private_render_static_owner_changed");
            if(::memcmp(data,a.values,28))::memcpy(data,a.values,28);
            if(api_.static_get(api_.context,i)!=a.object)api_.static_set_ref(api_.context,i,a.object);
            if(api_.static_get(api_.context,i)!=a.object)return fail("private_render_static_restore_failed");
            a.duty=false;
        }}catch(...){return fail("private_render_static_restore_exception");}
        static_restored_=true;return true;
    }
    bool construct(){
        if(!active_||failed_||constructed_||!owner())return fail("private_render_ctor_state_invalid");
        void* value=api_.allocate_root(api_.context);
        if(!value||!api_.root_type(api_.context,value)||!hold(root_,value))return fail("private_render_root_allocation_failed");
        bool result=false;
        constructing_=true;
        try{result=api_.construct_original(api_.context,value);constructing_=false;}
        catch(...){constructing_=false;failed_=true;error_="private_render_ctor_exception";active_=false;try{restore_static();}catch(...){error_="private_render_static_restore_exception";}return false;}
        // Constructor may have written both class static refs even if its final
        // MaterialLibrary field is still NULL. Receiver roots are independent.
        const bool arrays_valid=current_new_arrays();active_=false;
        if(!restore_static())return false;
        if(!result||failed_||!owner()||!root_current(root_)||material_count_!=expected_materials_
            ||!library_count_||!arrays_valid||!api_.root_complete(api_.context,value))return fail("private_render_ctor_incomplete");
        for(size_t i=0;i<material_count_;++i)if(!root_current(materials_[i])||!api_.material_alive(materials_[i].object))return fail("private_render_material_incomplete");
        constructed_=true;return true;
    }
    bool publish(){
        if(!constructed_||failed_||active_||!static_restored_||!owner()||!root_current(root_))return false;
        published_=true;return true;
    }
    bool release(){
        if(!api_.owner_thread||!api_.owner_thread()||constructing_)return false;
        active_=false;
        if(!static_abandoned_&&!restore_static())return false;
        // Observer failure leaves publication status uncertain. Quarantined
        // receivers/roots remain owned until the actual private GPU fence.
        if((published_||quarantined_)&&!api_.cleanup_fenced(api_.context))return false;
        // These are exactly freshly allocated receivers retained BEFORE native
        // creation; never enumerate source material fields to claim ownership.
        for(size_t i=0;i<material_count_;++i){auto& r=materials_[i];
            if(!r.object&&!r.root)continue;
            if(!root_current(r))return fail("private_render_material_root_changed");
            try{if(api_.material_alive(r.object))api_.material_destroy(r.object);}
            catch(...){return fail("private_render_material_destroy_exception");}
            drop(r);
        }
        material_count_=0;
        for(size_t i=0;i<library_count_;++i){drop(libraries_[i]);}
        library_count_=0;
        drop(root_);
        for(auto& a:arrays_){if(a.root)api_.release(a.root);a={};}
        constructed_=published_=failed_=false;epoch_=expected_materials_=0;static_restored_=static_abandoned_=constructing_=quarantined_=false;return true;
    }
};
} // namespace idoly_mp4_private_render_construction
// END_MP4_PRIVATE_RENDER_CONSTRUCTION

// BEGIN_MP4_PRIVATE_RENDERER_DATA
// Concrete source-data provenance and actual Unity.Object.Instantiate ownership.
// Embed in existing Camera header. This does NOT use MemberwiseClone or duplicate
// opaque renderer/RTHandle bytes. Original VLSRPRenderer ctor receives privateData.
namespace idoly_mp4_private_renderer_data {
struct Api {
    void* context=nullptr;bool (*owner_thread)()=nullptr;bool (*current)(void*,uint64_t)=nullptr;
    bool (*routes_verified)(void*)=nullptr;bool (*refresh_maps)()=nullptr;
    bool (*mapped)(const void*,size_t,bool)=nullptr;bool (*is_type)(void*,const char*)=nullptr;bool (*exact_type)(void*,const char*)=nullptr;
    void* (*class_of)(void*)=nullptr;bool (*alive)(void*)=nullptr;
    uint32_t (*retain)(void*)=nullptr;void* (*target)(uint32_t)=nullptr;void (*release)(uint32_t)=nullptr;
    size_t (*array_length)(void*)=nullptr;void* (*array_data)(void*)=nullptr;
    // Retained static UniversalRenderPipeline.get_asset, no Asset.GetRenderer
    // lazy creation is used by the read-only provenance query.
    void* (*render_asset)()=nullptr;
    void* (*instantiate)(void*)=nullptr;void (*destroy)(void*)=nullptr;
    // Original il2cpp_gc_wbarrier_set_field(privateObject,&field,value).
    void (*write_ref)(void*,void**,void*)=nullptr;
    bool (*cleanup_fenced)(void*)=nullptr;bool (*private_phase_held)(void*)=nullptr;bool (*variant_warmed)(void*)=nullptr;
};
struct Layout {
    size_t pipeline_renderers=32,pipeline_data=64,pipeline_default=72,additional_index=56;
    size_t features=32,feature_map=40,data_post=48,post_compute=96,post_use_compute=88,cached_native=16,data_rendering_mode=92,renderer_rendering_mode=936,post_shader_variants=80,data_xr=56;
};
class Lease {
    struct Root {void* object=nullptr;uint32_t root=0;};
    struct Clone {Root held{};void* source=nullptr;void* klass=nullptr;uintptr_t native=0;};
    struct Source {void* additional=nullptr;void* renderer=nullptr;void* asset=nullptr;void* renderers=nullptr;void* data_array=nullptr;
        void* data=nullptr;void* xr=nullptr;void* post=nullptr;void* compute=nullptr;void* variants=nullptr;void* features=nullptr;void* feature_map=nullptr;int32_t configured=-2,index=-1;bool use_compute=false;};
    Api api_{};Layout layout_{};uint64_t epoch_=0;Source source_{};Root roots_[16]{};size_t root_count_=0;
    Clone clones_[3]{};size_t clone_count_=0;bool captured_=false,prepared_=false,published_=false;const char* error_="none";
    bool fail(const char* error){error_=error;return false;}
    template<class T>bool read(void* object,size_t at,T& out)const{
        if(!object||!api_.mapped(static_cast<uint8_t*>(object)+at,sizeof(T),false))return false;
        ::memcpy(&out,static_cast<uint8_t*>(object)+at,sizeof(T));return true;
    }
    bool hold(Root& root,void* object){root.object=object;root.root=api_.retain(object);return root.root&&api_.target(root.root)==object;}
    bool keep(void* object){if(!object)return true;for(size_t i=0;i<root_count_;++i)if(roots_[i].object==object)return api_.target(roots_[i].root)==object;
        if(root_count_==16){return false;}
        auto& root=roots_[root_count_];if(!hold(root,object)){root={};return false;}++root_count_;return true;}
    bool empty_list(void* list)const{int32_t count=-1;return list&&api_.is_type(list,"System.Collections.Generic.List`1")&&read(list,24,count)&&count==0;}
    bool array_item(void* array,int32_t index,void*& value)const{
        if(!array||index<0||!api_.is_type(array,"System.Array"))return false;
        const size_t count=api_.array_length(array);if(count>64||static_cast<size_t>(index)>=count)return false;
        void* data=api_.array_data(array);if(!data||!api_.mapped(data,count*sizeof(void*),false))return false;
        ::memcpy(&value,static_cast<uint8_t*>(data)+static_cast<size_t>(index)*sizeof(void*),sizeof value);return value!=nullptr;
    }
    bool inspect(Source& out,void* additional,void* renderer)const{
        out.additional=additional;out.renderer=renderer;
        if(!additional||!renderer||!api_.is_type(additional,"UnityEngine.Rendering.Universal.UniversalAdditionalCameraData")
            ||!api_.alive(additional)||!api_.exact_type(renderer,"VL.Rendering.VLSRPRenderer")||!api_.class_of(renderer)
            ||!read(additional,layout_.additional_index,out.configured)||out.configured<-1)return false;
        out.asset=api_.render_asset();int32_t default_index=-1;
        if(!out.asset||!api_.is_type(out.asset,"UnityEngine.Rendering.Universal.UniversalRenderPipelineAsset")||!api_.alive(out.asset)
            ||!read(out.asset,layout_.pipeline_renderers,out.renderers)||!read(out.asset,layout_.pipeline_data,out.data_array)
            ||!read(out.asset,layout_.pipeline_default,default_index))return false;
        out.index=out.configured==-1?default_index:out.configured;void* actual_renderer=nullptr;
        if(!array_item(out.renderers,out.index,actual_renderer)||actual_renderer!=renderer||!array_item(out.data_array,out.index,out.data)
            ||!api_.exact_type(out.data,"VL.Rendering.VLSRPRendererData")||!api_.alive(out.data)
            ||!read(out.data,layout_.features,out.features)||!read(out.data,layout_.feature_map,out.feature_map)
            ||!empty_list(out.features)||!empty_list(out.feature_map)||!read(out.data,layout_.data_xr,out.xr)||!read(out.data,layout_.data_post,out.post)
            ||!out.post||!api_.exact_type(out.post,"VL.Rendering.VLPostProcessData")||!api_.alive(out.post)
            ||!read(out.post,layout_.post_compute,out.compute))return false;
        int32_t data_mode=-1,renderer_mode=-1;
        if(!read(out.data,layout_.data_rendering_mode,data_mode)||data_mode!=0||!read(renderer,layout_.renderer_rendering_mode,renderer_mode)||renderer_mode!=0)return false;
        if(!read(out.post,layout_.post_shader_variants,out.variants))return false;
        if(out.variants&&api_.alive(out.variants)){
            if(!api_.is_type(out.variants,"UnityEngine.ShaderVariantCollection")||!api_.variant_warmed(out.variants))return false;
        }else out.variants=nullptr; // Original Unity-object null check skips it.
        uint8_t use_compute=0;if(!read(out.post,layout_.post_use_compute,use_compute)||use_compute>1)return false;out.use_compute=use_compute!=0;
        return (!out.compute||(api_.is_type(out.compute,"UnityEngine.ComputeShader")&&api_.alive(out.compute)))&&(!out.use_compute||out.compute);
    }
    bool same(const Source& a,const Source& b)const{return a.additional==b.additional&&a.renderer==b.renderer&&a.asset==b.asset&&a.renderers==b.renderers
        &&a.data_array==b.data_array&&a.data==b.data&&a.xr==b.xr&&a.post==b.post&&a.compute==b.compute&&a.variants==b.variants&&a.features==b.features&&a.feature_map==b.feature_map
        &&a.configured==b.configured&&a.index==b.index&&a.use_compute==b.use_compute;}
    bool clone(void* original,const char* type,Clone& out){
        if(!current()||!api_.private_phase_held(api_.context))return false;
        void* value=api_.instantiate(original);
        if(!value||value==original||!api_.refresh_maps())return false;
        void* klass=api_.class_of(value);uintptr_t source_native=0,native=0;
        if(!klass||klass!=api_.class_of(original)||!api_.exact_type(value,type)||!api_.alive(value)
            ||!read(original,layout_.cached_native,source_native)||!read(value,layout_.cached_native,native)
            ||!source_native||!native||source_native==native)return false;
        void* originals[]={source_.additional,source_.asset,source_.data,source_.post,source_.compute};
        for(void* object:originals){uintptr_t pointer=0;if(object&&(!read(object,layout_.cached_native,pointer)||pointer==native))return false;}
        for(size_t i=0;i<clone_count_;++i)if(&clones_[i]!=&out&&(clones_[i].held.object==value||clones_[i].native==native))return false;
        // Ownership exists only after real native uniqueness is proved. A
        // MemberwiseClone alias must NEVER acquire source-native destroy duty.
        if(!hold(out.held,value)){out.held={};if(api_.alive(value))api_.destroy(value);return false;}
        out.source=original;out.klass=klass;out.native=native;return current()&&api_.private_phase_held(api_.context);
    }
    bool set_ref(Clone& owner,size_t offset,void* value){
        if(!current()||!owner.held.root||api_.target(owner.held.root)!=owner.held.object
            ||!api_.mapped(static_cast<uint8_t*>(owner.held.object)+offset,sizeof(void*),true))return false;
        auto** slot=reinterpret_cast<void**>(static_cast<uint8_t*>(owner.held.object)+offset);
        api_.write_ref(owner.held.object,slot,value);void* actual=nullptr;
        return read(owner.held.object,offset,actual)&&actual==value&&current();
    }
public:
    Lease()=default;Lease(const Lease&)=delete;Lease& operator=(const Lease&)=delete;
    const char* error()const{return error_;}bool prepared()const{return prepared_;}
    bool current()const{
        if(!captured_||!api_.owner_thread()||!api_.current(api_.context,epoch_)||!api_.routes_verified(api_.context))return false;
        for(size_t i=0;i<root_count_;++i)if(!roots_[i].root||api_.target(roots_[i].root)!=roots_[i].object)return false;
        for(size_t i=0;i<clone_count_;++i){const auto& c=clones_[i];if(!c.native)continue;uintptr_t native=0;
            if(!c.held.root||api_.target(c.held.root)!=c.held.object||api_.class_of(c.held.object)!=c.klass
                ||!read(c.held.object,layout_.cached_native,native)||native!=c.native||!api_.alive(c.held.object))return false;}
        Source now{};return inspect(now,source_.additional,source_.renderer)&&same(now,source_);
    }
    bool capture(Api api,Layout layout,uint64_t epoch,void* additional,void* renderer){
        if(captured_||root_count_||clone_count_||!epoch){return false;}
        api_=api;layout_=layout;epoch_=epoch;
        if(!api.owner_thread||!api.current||!api.routes_verified||!api.refresh_maps||!api.mapped||!api.is_type||!api.exact_type||!api.class_of||!api.alive
            ||!api.retain||!api.target||!api.release||!api.array_length||!api.array_data||!api.render_asset||!api.instantiate||!api.destroy||!api.write_ref||!api.cleanup_fenced||!api.private_phase_held||!api.variant_warmed
            ||!api.owner_thread()||!api.current(api.context,epoch)||!api.routes_verified(api.context)||!inspect(source_,additional,renderer))return fail("private_renderer_source_data_unavailable");
        void* values[]={source_.additional,source_.renderer,source_.asset,source_.renderers,source_.data_array,source_.data,source_.xr,source_.post,source_.compute,source_.variants,source_.features,source_.feature_map};
        for(void* value:values)if(!keep(value))return fail("private_renderer_source_root_failed");
        captured_=true;return current();
    }
    bool prepare(){
        if(prepared_){return current();}
        if(!current()||!api_.private_phase_held(api_.context))return fail("private_renderer_source_changed");
        // Own every actual Unity clone immediately after Instantiate returns.
        // A clone failure never authorizes a write to original source fields.
        if(source_.compute){clone_count_=1;if(!clone(source_.compute,"UnityEngine.ComputeShader",clones_[0]))return fail("private_renderer_compute_clone_failed");}
        clone_count_=2;if(!clone(source_.post,"VL.Rendering.VLPostProcessData",clones_[1]))return fail("private_renderer_post_clone_failed");
        if(!set_ref(clones_[1],layout_.post_compute,source_.compute?clones_[0].held.object:nullptr))return fail("private_renderer_compute_bind_failed");
        clone_count_=3;if(!clone(source_.data,"VL.Rendering.VLSRPRendererData",clones_[2]))return fail("private_renderer_data_clone_failed");
        if(!set_ref(clones_[2],layout_.data_post,clones_[1].held.object))return fail("private_renderer_post_bind_failed");
        // The ordinary non-XR selected camera never consumes XR passes. The
        // original renderer ctor nevertheless calls shared XRSystem.Initialize:
        // nonnull XRData destroys/replaces its global materials. Clear ONLY the
        // private renderer-data clone before ctor; the source asset is retained.
        if(!set_ref(clones_[2],layout_.data_xr,nullptr))return fail("private_renderer_xr_detach_failed");
        prepared_=true;return true;
    }
    // Source-role/shader validation runs BEFORE any private Instantiate and
    // remains tied to exact retained asset/index/source renderer provenance.
    void* source_renderer_data()const{return current()?source_.data:nullptr;}
    void* source_post_data()const{return current()?source_.post:nullptr;}
    void* source_compute_shader()const{return current()?source_.compute:nullptr;}
    void* renderer_data()const{return prepared_&&current()?clones_[2].held.object:nullptr;}
    void* post_data()const{return prepared_&&current()?clones_[1].held.object:nullptr;}
    void* compute_shader()const{return prepared_&&current()?clones_[0].held.object:nullptr;}
    bool publish(){if(!prepared_||!current())return false;published_=true;return true;}
    bool release(){
        if(!api_.owner_thread||!api_.owner_thread()||(published_&&!api_.cleanup_fenced(api_.context)))return false;
        // Reverse lifetime order: renderer-data -> post-data -> compute. These
        // clones are destroyed only after private renderer original Dispose.
        for(size_t i=clone_count_;i>0;--i){auto& c=clones_[i-1];if(!c.held.object&&!c.held.root)continue;
            if(!c.held.root||api_.target(c.held.root)!=c.held.object)return fail("private_renderer_clone_root_changed");
            uintptr_t native=0;
            if(!read(c.held.object,layout_.cached_native,native))return fail("private_renderer_clone_unmapped");
            if(native&&c.native&&native!=c.native)return fail("private_renderer_clone_native_changed");
            if(native&&c.native&&api_.alive(c.held.object))api_.destroy(c.held.object);
            api_.release(c.held.root);c={};
        }
        clone_count_=0;for(size_t i=0;i<root_count_;++i)if(roots_[i].root){api_.release(roots_[i].root);roots_[i]={};}
        root_count_=0;source_={};captured_=prepared_=published_=false;epoch_=0;return true;
    }
};
} // namespace idoly_mp4_private_renderer_data

// END_MP4_PRIVATE_RENDERER_DATA

// BEGIN_MP4_PRIVATE_RENDERER_ROOT
// Exact source-role validation for original fresh VLSRPRenderer constructors.
// No opaque render-target/history bytes are copied. Native source bodies and
// metadata pin these offsets; host pins exact class identities for Role.
namespace idoly_mp4_private_renderer_root {
enum class Role:uint8_t {renderer,post_pass,material_library,lut_pass,compute_pass};
struct Api {
    void* context=nullptr;bool (*mapped)(const void*,size_t,bool)=nullptr;
    bool (*role)(void*,Role)=nullptr;bool (*shader_alive)(void*)=nullptr;
    bool (*material_alive)(void*)=nullptr;
    bool (*owns_material)(void*,void*)=nullptr;bool (*owns_library)(void*,void*)=nullptr;
};
struct Source {
    void* renderer=nullptr;bool material_present[36]{};void* shaders[21]{};size_t material_count=0;
};
class Check {
    Api api_{};Source source_{};bool captured_=false;const char* error_="none";
    template<class T>bool read(void* object,size_t at,T& out)const{
        if(!object||!api_.mapped(static_cast<uint8_t*>(object)+at,sizeof(T),false))return false;
        ::memcpy(&out,static_cast<uint8_t*>(object)+at,sizeof(T));return true;
    }
    bool fail(const char* code){error_=code;return false;}
    bool materials(void* root,void** out,bool private_check)const{
        if(!api_.role(root,Role::renderer)){return false;}
        size_t slot=0;
        for(size_t at=952;at<=1008;at+=8)if(!read(root,at,out[slot++]))return false;
        void* lut=nullptr;if(!read(root,152,lut)||!api_.role(lut,Role::lut_pass)
            ||!read(lut,128,out[slot++])||!read(lut,136,out[slot++]))return false;
        constexpr size_t pass_offsets[]={328,336};
        for(size_t at:pass_offsets){void* pass=nullptr;void* library=nullptr;void* blit=nullptr;
            if(!read(root,at,pass)||!api_.role(pass,Role::post_pass)||!read(pass,376,library)||!api_.role(library,Role::material_library)
                ||!read(pass,536,blit)||blit!=out[0]||(private_check&&!api_.owns_library(api_.context,library)))return false;
            for(size_t field=16;field<=112;field+=8)if(!read(library,field,out[slot++]))return false;
        }
        return slot==36;
    }
    bool shaders(void* data,void* post,void** out)const{
        void* renderer_shaders=nullptr;void* post_shaders=nullptr;size_t slot=0;
        if(!read(data,64,renderer_shaders)||!read(post,24,post_shaders))return false;
        // Five used URP renderer shaders, plus VL blend-downscale. TileDepth /
        // TileDeferred48/56 and error72/80 are NOT read by this ctor route.
        constexpr size_t used_renderer_shaders[]={16,24,40,32,64};
        for(size_t at:used_renderer_shaders)if(!read(renderer_shaders,at,out[slot++]))return false;
        if(!read(data,104,out[slot++]))return false;
        // Nine PostMaterialLibrary shaders + the two ColorGradingLut shaders.
        for(size_t at=16;at<=96;at+=8)if(!read(post_shaders,at,out[slot++]))return false;
        for(size_t at=48;at<=72;at+=8)if(!read(post,at,out[slot++]))return false;
        return slot==21;
    }
public:
    const char* error()const{return error_;}size_t expected_materials()const{return captured_?source_.material_count:0;}
    bool capture(Api api,void* source_renderer,void* source_data,void* source_post){
        if(captured_){return false;}
        api_=api;
        if(!api_.mapped||!api_.role||!api_.shader_alive||!api_.material_alive||!api_.owns_material||!api_.owns_library)return fail("private_renderer_role_api_missing");
        int32_t data_mode=-1,renderer_mode=-1;
        if(!read(source_data,92,data_mode)||data_mode!=0||!read(source_renderer,936,renderer_mode)||renderer_mode!=0)return fail("private_renderer_deferred_route_unsupported");
        void* values[36]{};if(!materials(source_renderer,values,false)||!shaders(source_data,source_post,source_.shaders))return fail("private_renderer_source_roles_missing");
        for(void* shader:source_.shaders)if(!shader||!api_.shader_alive(shader))return fail("private_renderer_null_shader_unsupported");
        if(values[4]||values[5])return fail("private_renderer_lazy_material_route_unsupported");
        for(size_t i=0;i<36;++i){source_.material_present[i]=values[i]!=nullptr;
            if(values[i]){if(!api_.material_alive(values[i]))return fail("private_renderer_source_material_dead");++source_.material_count;}}
        if(!source_.material_count||source_.material_count>36)return fail("private_renderer_source_material_count_invalid");
        source_.renderer=source_renderer;captured_=true;return true;
    }
    bool shader_admitted(void* shader)const{
        if(!captured_||!shader||!api_.shader_alive(shader))return false;
        for(void* expected:source_.shaders){if(expected==shader)return true;}
        return false;
    }
    bool private_complete(void* renderer,void* private_data,void* private_post,void* private_compute){
        if(!captured_||renderer==source_.renderer)return fail("private_renderer_instance_not_private");
        void* values[36]{};void* shader_values[21]{};
        if(!materials(renderer,values,true)||!shaders(private_data,private_post,shader_values))return fail("private_renderer_private_roles_missing");
        for(size_t i=0;i<21;++i)if(shader_values[i]!=source_.shaders[i])return fail("private_renderer_shader_input_changed");
        for(size_t i=0;i<36;++i){if((values[i]!=nullptr)!=source_.material_present[i])return fail("private_renderer_material_support_changed");
            if(values[i]&&!api_.owns_material(api_.context,values[i]))return fail("private_renderer_unowned_material");}
        constexpr size_t passes[]={328,336};
        for(size_t at:passes){void* pass=nullptr;void* data=nullptr;
            if(!read(renderer,at,pass)||!read(pass,384,data)||data!=private_post)return fail("private_renderer_post_data_not_private");}
        void* compute_pass=nullptr;void* shader=nullptr;
        if(!read(renderer,160,compute_pass)||!api_.role(compute_pass,Role::compute_pass)||!read(compute_pass,128,shader)||shader!=private_compute)
            return fail("private_renderer_compute_not_private");
        return true;
    }
};
} // namespace idoly_mp4_private_renderer_root
// END_MP4_PRIVATE_RENDERER_ROOT

// BEGIN_MP4_FOCUS_EXTRA_STATE
// Exact CinemachineExtension.mExtraState reference lease. No old dictionary
// contents/native handles are copied. The host supplies the pinned closed class
// and original constructor, and source identity excludes this leased field.
namespace idoly_mp4_focus_private {
struct Owner {void*extension=nullptr;void*camera=nullptr;void*target=nullptr;uintptr_t native_extension=0;float offset=0;};
struct ExtraApi {
 bool(*current)(void*,uint64_t,const Owner&)=nullptr;bool(*owner_thread)()=nullptr;bool(*held)(void*)=nullptr;
 bool(*dictionary_class)(void*,const Owner&,void**)=nullptr;
 void*(*dictionary_get)(void*)=nullptr;
 bool(*dictionary_set)(void*,void*expected,void*replacement)=nullptr; // compare then original GC barrier
 void*(*dictionary_new)(void*,void*klass)=nullptr;
 void(*dictionary_ctor)(void*,void*)=nullptr;
 bool(*dictionary_is)(void*,void*,void*klass)=nullptr;
 uint32_t(*retain)(void*)=nullptr;void*(*retained)(uint32_t)=nullptr;void(*release)(uint32_t)=nullptr;
 bool(*detached)(void*,const Owner&,void*private_dictionary)=nullptr;
};
struct Suspension {uint64_t epoch=0;uint32_t depth=0;bool active=false;};
class ExtraStateLease {
 ExtraApi api_{};void*context_=nullptr;Owner owner_{};uint64_t epoch_=0;void*klass_=nullptr,*old_=nullptr,*private_=nullptr;
 uint32_t roots_[3]{},old_root_=0,private_root_=0,depth_=0;bool captured_=false,constructed_=false,duty_=false,ever_installed_=false;
 bool constructing_=false,abandoned_=false,poisoned_=false;const char*error_="none";
 bool fail(const char*s){poisoned_=true;error_=s;return false;}
 bool keep(void*p,uint32_t&root){if(!p){root=0;return true;}root=api_.retain(p);return root&&api_.retained(root)==p;}
 bool source()const{return captured_&&!abandoned_&&api_.owner_thread()&&api_.current(context_,epoch_,owner_)
  &&api_.retained(roots_[0])==owner_.extension&&api_.retained(roots_[1])==owner_.camera
  &&(!owner_.target||api_.retained(roots_[2])==owner_.target)
  &&(!old_||api_.retained(old_root_)==old_)&&(!private_||api_.retained(private_root_)==private_);}
 bool valid_dictionary(void*p)const{return !p||api_.dictionary_is(context_,p,klass_);}
 void drop(uint32_t&root){if(root)api_.release(root);root=0;}
public:
 bool capture(ExtraApi api,void*ctx,uint64_t epoch,const Owner&owner){
  if(captured_||epoch_||!ctx||!epoch||!owner.extension||!owner.camera||!owner.native_extension||!std::isfinite(owner.offset)
   ||!api.current||!api.owner_thread||!api.held||!api.dictionary_class||!api.dictionary_get||!api.dictionary_set
   ||!api.dictionary_new||!api.dictionary_ctor||!api.dictionary_is||!api.retain||!api.retained||!api.release||!api.detached
   ||!api.owner_thread()||!api.current(ctx,epoch,owner))return false;
  api_=api;context_=ctx;epoch_=epoch;owner_=owner;
  if(!keep(owner.extension,roots_[0])||!keep(owner.camera,roots_[1])||!keep(owner.target,roots_[2])
   ||!api_.dictionary_class(ctx,owner,&klass_)||!klass_)return fail("focus_extra_class_or_roots");
  old_=api_.dictionary_get(owner.extension);
  if(!valid_dictionary(old_)||!keep(old_,old_root_)||!api_.current(ctx,epoch,owner))return fail("focus_extra_baseline");
  captured_=true;return true;
 }
 bool prepare(){
  if(!source()||poisoned_||depth_||!api_.held(context_))return fail("focus_extra_prepare_owner");
  if(duty_)return constructed_&&api_.dictionary_get(owner_.extension)==private_;
  if(private_||api_.dictionary_get(owner_.extension)!=old_)return fail("focus_extra_prepare_changed");
  private_=api_.dictionary_new(context_,klass_);
  if(!private_||private_==old_||private_==owner_.extension||private_==owner_.camera
   ||!valid_dictionary(private_)||!keep(private_,private_root_))return fail("focus_extra_new_dictionary");
  constructing_=true;
  try{api_.dictionary_ctor(context_,private_);}catch(...){constructing_=false;fail("focus_extra_dictionary_ctor");throw;}
  constructing_=false;
  if(!source()||!valid_dictionary(private_))return fail("focus_extra_ctor_owner");
  constructed_=true;duty_=true;ever_installed_=true; // before first possibly throwing GC barrier
  if(!api_.dictionary_set(owner_.extension,old_,private_)||api_.dictionary_get(owner_.extension)!=private_)return fail("focus_extra_install");
  return source();
 }
 bool installed()const{return duty_&&!depth_&&!abandoned_;}
 bool current(){return source()&&!poisoned_&&constructed_&&duty_&&!depth_&&api_.dictionary_get(owner_.extension)==private_;}
 bool suspend(Suspension&token){
  if(token.active)return false;
  token={};
  if(!duty_||abandoned_)return true;
  if(!source()||poisoned_)return fail("focus_extra_suspend_owner");
  token.epoch=epoch_;token.depth=depth_+1;
  if(!depth_&&!api_.dictionary_set(owner_.extension,private_,old_))return fail("focus_extra_suspend_reference");
  ++depth_;token.active=true;return true;
 }
 bool resume(Suspension&token){
  if(!token.active)return true;
  if(abandoned_||!duty_||token.epoch!=epoch_){token.active=false;return false;}
  if(token.depth!=depth_||!source()){abandon();token.active=false;return false;}
  if(depth_==1){
   void*latest=api_.dictionary_get(owner_.extension);
   if(latest==private_||!valid_dictionary(latest)){abandon();token.active=false;return fail("focus_extra_ambient_dictionary");}
   uint32_t root=0;if(latest!=old_&&!keep(latest,root)){abandon();token.active=false;return fail("focus_extra_ambient_root");}
   if(latest!=old_){drop(old_root_);old_root_=root;old_=latest;}
   if(!api_.dictionary_set(owner_.extension,latest,private_)){abandon();token.active=false;return fail("focus_extra_resume_reference");}
  }
  --depth_;token.active=false;return source();
 }
 // Must run before original source restore Rebuild/Evaluate so normal Focus
 // cache creation belongs to the original dictionary, not the export cache.
 bool restore_reference(){
  if(abandoned_)return false;
  if(!captured_||constructing_||!source()||depth_||!api_.held(context_))return false;
  if(!duty_)return true;
  void*actual=api_.dictionary_get(owner_.extension);
  if(actual==private_){if(!api_.dictionary_set(owner_.extension,private_,old_))return fail("focus_extra_restore_reference");}
  else if(actual!=old_)return fail("focus_extra_restore_changed");
  duty_=false;return true;
 }
 // Trusted raw source initializer/End observer, BEFORE original source work.
 // An accepted render/clock grant can still be on stack. Withdraw only this
 // field publication; actual readers/constructed resources remain retained.
 bool withdraw_before_source_change(){
  if(abandoned_)return true;
  if(!captured_||!duty_){abandoned_=true;return true;}
  if(constructing_||!source())return fail("focus_extra_withdraw_owner");
  void*actual=api_.dictionary_get(owner_.extension);
  if(depth_){
   // Unrelated nested execution currently owns its ambient field. Preserve any
   // progress it made; an outstanding resume must never reinstall private.
   if(actual==private_)return fail("focus_extra_withdraw_suspension");
  }else if(actual==private_){
   if(!api_.dictionary_set(owner_.extension,private_,old_))return fail("focus_extra_withdraw_reference");
  }else if(actual!=old_)return fail("focus_extra_withdraw_changed");
  duty_=false;abandoned_=true;error_="focus_extra_withdrawn";return true;
 }
 // Pure observer-failure path. Never get/set a former/new source dictionary.
 void abandon(){abandoned_=true;duty_=false;poisoned_=true;error_="focus_extra_abandoned";}
 bool release(){
  if(constructing_||(depth_&&!abandoned_)||duty_)return false;
  if(private_&&ever_installed_&&!api_.detached(context_,owner_,private_))return false;
  drop(private_root_);
  drop(old_root_);
  for(auto&root:roots_)drop(root);
  captured_=constructed_=ever_installed_=constructing_=abandoned_=poisoned_=false;epoch_=depth_=0;context_=klass_=old_=private_=nullptr;owner_={};return true;
 }
 void*private_dictionary()const{return private_;}
 bool abandoned()const{return abandoned_;}
 uint64_t epoch()const{return epoch_;}
 const char*error()const{return error_;}
};
} // namespace idoly_mp4_focus_private

// END_MP4_FOCUS_EXTRA_STATE

// BEGIN_MP4_FOCUS_FACTORY_LEDGER
// Exact Focus ScriptableObject CreateInstance request ledger. The engine binds
// native.cachedPtr before managed construction. ENTRY/RESULT provenance is
// mandatory; a global active flag plus matching class is not ownership proof.
namespace idoly_mp4_focus_private {
enum class Role:uint32_t{profile=1,dof=2};
enum class Observe:uint8_t{forward,owned,reject};
struct FactoryApi {
 bool(*current)(void*,uint64_t)=nullptr;bool(*owner_thread)()=nullptr;
 bool(*entry)(void*,uint64_t,uint64_t,Role)=nullptr; // exact owned Focus callback + factory entry
 bool(*receiver)(void*,uint64_t,Role,void*,uintptr_t)=nullptr; // exact factory request including late RESULT
 uint32_t(*retain)(void*)=nullptr;void*(*retained)(uint32_t)=nullptr;void(*release)(uint32_t)=nullptr;
 bool(*detached)(void*,uint64_t)=nullptr; // all private publications + actual GPU fence
 bool(*alive)(void*,void*,uintptr_t)=nullptr; // exact managed/native pair, no old pointer reuse
 bool(*destroy)(void*,void*,uintptr_t)=nullptr; // original Unity destroy; private only
};
class FactoryLedger {
 struct Record{void*object=nullptr;uintptr_t native=0;uint32_t root=0;Role role=Role::profile;bool destroy_requested=false;};
 static constexpr size_t capacity=512;FactoryApi api_{};void*context_=nullptr;uint64_t epoch_=0,serial_=0,last_serial_=0;
 Role role_=Role::profile;Record records_[capacity]{};size_t count_=0;void*unrooted_=nullptr;
 bool active_=false,request_seen_=false,abandoned_=false,failed_=false,unknown_=false;const char*error_="none";
 bool fail(const char*s){failed_=true;error_=s;return false;}
 bool current()const{return epoch_&&!abandoned_&&api_.owner_thread()&&api_.current(context_,epoch_);}
 Observe remember(uint64_t serial,Role role,void*object,uintptr_t native){
  if(!active_||serial!=serial_||role!=role_)return Observe::forward;
  if(!object||!native||!api_.owner_thread()||!api_.receiver(context_,serial,role,object,native)){unknown_=true;fail("focus_factory_receiver");return Observe::reject;}
  for(size_t i=0;i<count_;++i){auto&r=records_[i];
   if(r.object==object||r.native==native){if(r.object==object&&r.native==native&&r.role==role&&api_.retained(r.root)==object){request_seen_=true;return Observe::owned;}unknown_=true;fail("focus_factory_alias");return Observe::reject;}
  }
  if(count_==capacity){unknown_=true;fail("focus_factory_capacity");return Observe::reject;}
  uint32_t root=api_.retain(object);
  if(!root||api_.retained(root)!=object){if(root)api_.release(root);unrooted_=object;unknown_=true;fail("focus_factory_root");return Observe::reject;}
  records_[count_++]={object,native,root,role,false};
  request_seen_=true;
  if(unrooted_==object){unrooted_=nullptr;unknown_=false;}
  return Observe::owned;
 }
public:
 bool configure(FactoryApi api,void*ctx,uint64_t epoch){
  if(epoch_||!ctx||!epoch||!api.current||!api.owner_thread||!api.entry||!api.receiver||!api.retain||!api.retained||!api.release||!api.detached||!api.alive||!api.destroy||!api.owner_thread()||!api.current(ctx,epoch))return false;
  api_=api;context_=ctx;epoch_=epoch;return true;
 }
 bool begin(uint64_t serial,Role role){
  if(!current()||failed_||active_||!serial||serial<=last_serial_||(role!=Role::profile&&role!=Role::dof)||!api_.entry(context_,epoch_,serial,role))return fail("focus_factory_entry");
  serial_=serial;last_serial_=serial;role_=role;active_=true;request_seen_=false;return true;
 }
 // before-base is already native-bound. Result fallback covers a derived ctor
 // exception before base. An old in-flight result can still be rooted after a
 // source handoff using the exact recorded factory receipt, never source writes.
 Observe before_base(uint64_t serial,Role role,void*object,uintptr_t native){return remember(serial,role,object,native);}
 Observe result(uint64_t serial,Role role,void*object,uintptr_t native){return remember(serial,role,object,native);}
 bool end(uint64_t serial,bool factory_failed_without_receiver=false){
  if(!active_||serial!=serial_)return fail("focus_factory_end");
  if(factory_failed_without_receiver||!request_seen_){unknown_=true;fail("focus_factory_unobservable_failure");}
  active_=false;serial_=0;return !failed_;
 }
 // Pure source-observer failure: no Unity/getter/current/destroy callbacks.
 // Preserve active receipt so its unavoidable late RESULT can be quarantined.
 void abandon(){abandoned_=true;failed_=true;error_="focus_factory_abandoned";}
 bool cleanup(){
  if(!epoch_)return true;
  if(active_||unknown_||!api_.owner_thread()||!api_.detached(context_,epoch_))return false;
  for(size_t i=count_;i>0;--i){auto&r=records_[i-1];
   if(api_.retained(r.root)!=r.object)return fail("focus_factory_lost_root");
   if(!api_.alive(context_,r.object,r.native))continue;
   if(r.destroy_requested)return false;
   r.destroy_requested=true; // before a potentially throwing original destroy
   if(!api_.destroy(context_,r.object,r.native))return fail("focus_factory_destroy");
  }
  return true;
 }
 bool release(){
  if(!epoch_)return true;
  if(!cleanup())return false;
  for(size_t i=0;i<count_;++i){const auto&r=records_[i];if(api_.retained(r.root)!=r.object||api_.alive(context_,r.object,r.native))return false;}
  for(size_t i=0;i<count_;++i){api_.release(records_[i].root);records_[i]={};}
  epoch_=serial_=last_serial_=0;count_=0;context_=nullptr;active_=request_seen_=abandoned_=failed_=unknown_=false;unrooted_=nullptr;return true;
 }
 // Raw birth identity only: does not query Unity/source/current or prove live
 // native state. Roots remain ledger-owned through abandon/quarantine.
 bool owns_object_raw(void*object)const noexcept{
  if(!object)return false;
  for(size_t i=0;i<count_;++i)if(records_[i].root&&records_[i].object==object)return true;
  return false;
 }
 void*object_at(size_t i)const{
  return i<count_&&records_[i].root&&api_.retained(records_[i].root)==records_[i].object?records_[i].object:nullptr;
 }
 Role role_at(size_t i)const noexcept{return i<count_?records_[i].role:static_cast<Role>(0);}
 uintptr_t native_at(size_t i)const noexcept{return i<count_?records_[i].native:0;}
 bool in_progress()const{return active_;}bool abandoned()const{return abandoned_;}size_t count()const{return count_;}
 const char*error()const{return error_;}
};
} // namespace idoly_mp4_focus_private

// END_MP4_FOCUS_FACTORY_LEDGER

// BEGIN_MP4_CINE_VOLUME_PRODUCER
// Exact selected CinemachineVolumeSettings.ApplyPostFX ownership transaction.
// The concrete host must pin its original callbacks and hidden-child creator
// routes. This helper does not claim arbitrary camera events or Volume writers.
namespace idoly_mp4_cine_volume_producer {
enum class Kind:uint8_t {game_object,volume};
enum class Observe:uint8_t {forward,owned,reject};
enum class Result:uint8_t {ok,waiting,invalid,stale,failed};
struct VolumeImage {
    void* object=nullptr;void* game_object=nullptr;void* shared_profile=nullptr;void* internal_profile=nullptr;
    float priority=0,blend_distance=0,weight=0,previous_priority=0;int32_t previous_layer=0;
    bool global=false,enabled=false,active=false;
};
struct GameObjectImage {void* object=nullptr;int32_t layer=0;bool active=false;};
struct Receipt {void* object=nullptr;void* game_object=nullptr;void* profile=nullptr;void* owner=nullptr;void* asset=nullptr;uintptr_t producer=0;uint64_t epoch=0,serial=0;bool newly_created=false;};
struct Api {
    void* context=nullptr;bool(*owner_thread)()=nullptr;bool(*current)(void*,uint64_t)=nullptr;
    bool(*routes_verified)(void*)=nullptr;bool(*membership_current)(void*)=nullptr;
    uint32_t(*retain)(void*)=nullptr;void*(*target)(uint32_t)=nullptr;void(*release)(uint32_t)=nullptr;
    bool(*inventory)(void*,void*,GameObjectImage*,size_t,size_t*,VolumeImage*,size_t,size_t*)=nullptr;
    bool(*volume_current)(void*,const VolumeImage&)=nullptr;bool(*game_object_current)(void*,const GameObjectImage&)=nullptr;
    bool(*restore_game_object)(void*,const GameObjectImage&)=nullptr;bool(*verify_game_object)(void*,const GameObjectImage&)=nullptr;
    // Must reconcile actual manager layer membership before restoring the
    // captured previous-layer cache. Raw previousLayer assignment alone is not
    // a layer-cache restoration when the original producer changed GO.layer.
    bool(*restore_volume)(void*,const VolumeImage&)=nullptr;bool(*verify_volume)(void*,const VolumeImage&)=nullptr;
    bool(*fresh_game_object)(void*,void*,void*)=nullptr;
    bool(*volume_subject)(void*,void*,void**)=nullptr;
    bool(*created_current)(void*,void*,Kind,void*)=nullptr;
    bool(*destroy_created_immediate)(void*,void*,Kind)=nullptr;
    bool(*created_unregistered)(void*,void*,Kind)=nullptr;
    bool(*withdraw_created)(void*,void*,Kind,void*)=nullptr;
    bool(*created_withdrawn)(void*,void*,Kind,void*)=nullptr;
    bool(*cleanup_fenced)(void*)=nullptr;
    bool(*destroy_detached)(void*,void*,Kind,void*)=nullptr;
    bool(*detached_destroyed)(void*,void*,Kind)=nullptr;
    // After a failed pre-init handoff these published scene resources may have
    // been adopted by the replacement scene. Relinquish our ledger without
    // touching those scene objects; do not later destroy them as old resources.
    void(*abandon_created)(void*,void*,Kind)noexcept=nullptr;
    bool(*current_profile)(void*,void*,void**)=nullptr;
    uintptr_t producer_method=0;void* source_asset=nullptr;
};
class Scope {
    static constexpr size_t max_gos=16,max_volumes=64,max_created=80,max_readers=16;
    struct Held {void* object=nullptr;uint32_t root=0;};
    struct Created {Held held{};Kind kind=Kind::volume;void* game_object=nullptr;uint64_t serial=0;bool retired=false,detached=false;};
    inline static uint64_t next_reader_=0;
    Api api_{};void* brain_=nullptr;Held brain_root_{},asset_root_{};
    GameObjectImage gos_[max_gos]{};VolumeImage volumes_[max_volumes]{};
    Held source_roots_[max_gos+max_volumes*4]{};size_t source_count_=0,go_count_=0,volume_count_=0;
    Created created_[max_created]{};size_t created_count_=0;
    uint64_t readers_[max_readers]{},epoch_=0,sequence_=0;size_t reader_count_=0;
    bool configured_=false,restored_=false,withdrawn_=false,abandoned_=false,failed_=false;
    const char* error_="none";
    bool fail(const char* text){failed_=true;error_=text;return false;}
    bool complete()const{return api_.owner_thread&&api_.current&&api_.routes_verified&&api_.retain&&api_.target&&api_.release
        &&api_.inventory&&api_.membership_current&&api_.volume_current&&api_.game_object_current&&api_.restore_game_object&&api_.verify_game_object
        &&api_.restore_volume&&api_.verify_volume&&api_.fresh_game_object&&api_.volume_subject&&api_.created_current
        &&api_.destroy_created_immediate&&api_.created_unregistered&&api_.withdraw_created&&api_.created_withdrawn
        &&api_.cleanup_fenced&&api_.destroy_detached&&api_.detached_destroyed&&api_.abandon_created&&api_.current_profile&&api_.producer_method&&api_.source_asset;}
    bool current()const{return configured_&&!withdrawn_&&!abandoned_&&!failed_&&api_.owner_thread()
        &&brain_root_.root&&api_.target(brain_root_.root)==brain_&&asset_root_.root&&api_.target(asset_root_.root)==api_.source_asset&&api_.current(api_.context,epoch_)&&api_.routes_verified(api_.context);}
    bool hold(Held& out,void* object){out.object=object;out.root=object?api_.retain(object):0;return !object||(out.root&&api_.target(out.root)==object);}
    bool keep(void* object){if(!object)return true;for(size_t i=0;i<source_count_;++i)if(source_roots_[i].object==object)return api_.target(source_roots_[i].root)==object;
        return source_count_<max_gos+max_volumes*4&&hold(source_roots_[source_count_++],object);}
    bool source_current()const{
        for(size_t i=0;i<source_count_;++i)if(!source_roots_[i].root||api_.target(source_roots_[i].root)!=source_roots_[i].object)return false;
        for(size_t i=0;i<go_count_;++i)if(!api_.game_object_current(api_.context,gos_[i]))return false;
        for(size_t i=0;i<volume_count_;++i)if(!api_.volume_current(api_.context,volumes_[i]))return false;
        return api_.membership_current(api_.context);
    }
    bool in_original()const{return current()&&reader_count_;}
public:
    const char* error()const{return error_;}bool active()const{return configured_;}
    bool in_apply()const{return in_original();}bool restored()const{return restored_&&!abandoned_;}
    size_t readers()const{return reader_count_;}
    // Pure birth ledger: strong roots prevent raw managed receiver reuse. Old
    // detached Volume.Update stays suppressed while source ownership is gone.
    bool owns_created_volume_raw(void* object)const noexcept {
        if(!configured_||abandoned_||!object)return false;
        for(size_t i=0;i<created_count_;++i){const auto& c=created_[i];
            if(c.kind==Kind::volume&&!c.retired&&c.held.root&&c.held.object==object)return true;}
        return false;
    }
    // Cleanup publication proof over exact retained birth records only. This
    // never rediscovers a replacement Brain/scene/manager roster.
    bool created_volume_publications_withdrawn(bool(*profile_slots_clear)(void*))const{
        if(!configured_)return true;
        if(reader_count_||!profile_slots_clear||!api_.owner_thread||!api_.owner_thread())return false;
        for(size_t i=0;i<created_count_;++i){const auto& c=created_[i];
            if(c.kind!=Kind::volume||c.retired)continue;
            if(!c.detached||!c.held.root||api_.target(c.held.root)!=c.held.object
                ||!api_.created_withdrawn(api_.context,c.held.object,c.kind,c.game_object)
                ||!profile_slots_clear(c.held.object))return false;
        }
        return true;
    }
    bool capture(Api api,uint64_t epoch,void* brain){
        if(configured_||!epoch||!brain)return false;
        api_=api;epoch_=epoch;brain_=brain;configured_=true;
        if(!complete()||!hold(brain_root_,brain)||!hold(asset_root_,api_.source_asset)||!current())return fail("cine_volume_source_unavailable");
        if(!api_.inventory(api_.context,brain,gos_,max_gos,&go_count_,volumes_,max_volumes,&volume_count_)
            ||go_count_>max_gos||volume_count_>max_volumes)return fail("cine_volume_source_inventory_failed");
        for(size_t i=0;i<go_count_;++i)if(!keep(gos_[i].object))return fail("cine_volume_source_root_failed");
        for(size_t i=0;i<volume_count_;++i){const auto& v=volumes_[i];
            if(!keep(v.object)||!keep(v.game_object)||!keep(v.shared_profile)||!keep(v.internal_profile))return fail("cine_volume_source_root_failed");}
        return source_current()||fail("cine_volume_source_identity_changed");
    }
    uint64_t begin_apply(void* brain){
        if(brain!=brain_||!current()||!source_current()||reader_count_==max_readers||next_reader_==~uint64_t(0))return 0;
        for(auto& reader:readers_)if(!reader){reader=++next_reader_;sequence_=reader;++reader_count_;restored_=false;return reader;}
        return 0;
    }
    bool end_apply(uint64_t token){
        if(!token)return false;
        for(auto& reader:readers_){if(reader==token){reader=0;--reader_count_;return !abandoned_&&!failed_;}}
        return false;
    }
    Observe game_object_before(void* object,void* name){
        if(!in_original())return Observe::forward;
        if(created_count_==max_created||!api_.fresh_game_object(api_.context,object,name)){fail("cine_volume_game_object_creator_unclosed");return Observe::reject;}
        for(size_t i=0;i<created_count_;++i)if(created_[i].held.object==object)return Observe::reject;
        auto& item=created_[created_count_++];item.kind=Kind::game_object;item.game_object=object;item.serial=sequence_;
        return hold(item.held,object)?Observe::owned:(fail("cine_volume_created_root_failed"),Observe::reject);
    }
    Observe volume_before_enable(void* object){
        if(!in_original())return Observe::forward;
        for(size_t i=0;i<volume_count_;++i)if(volumes_[i].object==object)return Observe::owned;
        for(size_t i=0;i<created_count_;++i)if(created_[i].held.object==object)return Observe::owned;
        void* go=nullptr;if(!api_.volume_subject(api_.context,object,&go))return Observe::forward;
        bool owned=false;for(size_t i=0;i<go_count_;++i)owned|=gos_[i].object==go;
        for(size_t i=0;i<created_count_;++i)owned|=created_[i].kind==Kind::game_object&&created_[i].held.object==go;
        if(!owned||created_count_==max_created){fail("cine_volume_component_creator_unclosed");return Observe::reject;}
        auto& item=created_[created_count_++];item.kind=Kind::volume;item.game_object=go;item.serial=sequence_;
        return hold(item.held,object)?Observe::owned:(fail("cine_volume_created_root_failed"),Observe::reject);
    }
    bool receipt(void* volume,Receipt& out)const{
        if(!configured_||abandoned_||withdrawn_)return false;
        for(size_t i=0;i<created_count_;++i){const auto& c=created_[i];if(c.kind!=Kind::volume||c.held.object!=volume||c.retired)continue;
            if(!c.held.root||api_.target(c.held.root)!=volume||!api_.created_current(api_.context,volume,c.kind,c.game_object))return false;
            void* profile=nullptr;if(!api_.current_profile(api_.context,volume,&profile))return false;
            out={volume,c.game_object,profile,brain_,api_.source_asset,api_.producer_method,epoch_,c.serial,true};return true;}
        return false;
    }
    size_t source_volume_count()const{return volume_count_;}
    bool source_receipt(size_t index,VolumeImage& image,Receipt& out)const{
        if(!configured_||abandoned_||index>=volume_count_)return false;
        image=volumes_[index];void* profile=nullptr;
        if(!api_.current_profile(api_.context,image.object,&profile))return false;
        out={image.object,image.game_object,profile,brain_,api_.source_asset,api_.producer_method,epoch_,index+1,false};return true;
    }
    bool delegated_restored(void* volume)const{
        if(!restored()||!source_current())return false;
        for(size_t i=0;i<volume_count_;++i)if(volumes_[i].object==volume)
            return api_.verify_volume(api_.context,volumes_[i]);
        return false;
    }
    bool delegated_source(void* volume)const{if(!configured_||abandoned_)return false;for(size_t i=0;i<volume_count_;++i)if(volumes_[i].object==volume)return true;return false;}
    bool verify_restored()const{
        if(!restored()||!source_current())return false;
        for(size_t i=0;i<go_count_;++i)if(!api_.verify_game_object(api_.context,gos_[i]))return false;
        for(size_t i=0;i<volume_count_;++i)if(!api_.verify_volume(api_.context,volumes_[i]))return false;
        return true;
    }
    Result restore(){
        if(!configured_)return Result::ok;
        if(abandoned_)return Result::stale;
        if(created_count_&&!api_.cleanup_fenced(api_.context))return Result::waiting;
        if(!api_.owner_thread()||!api_.current(api_.context,epoch_)||!source_current())return Result::stale;
        // Complete identity preflight precedes the first native scene write.
        for(size_t i=0;i<created_count_;++i){const auto& c=created_[i];if(!c.retired&&(!c.held.root||api_.target(c.held.root)!=c.held.object||!api_.created_current(api_.context,c.held.object,c.kind,c.game_object)))return Result::stale;}
        for(size_t i=created_count_;i>0;--i){auto& c=created_[i-1];if(c.retired)continue;
            if(!api_.destroy_created_immediate(api_.context,c.held.object,c.kind)||!api_.created_unregistered(api_.context,c.held.object,c.kind))return Result::failed;
            c.retired=true;}
        for(size_t i=0;i<go_count_;++i)if(!api_.restore_game_object(api_.context,gos_[i]))return Result::failed;
        for(size_t i=0;i<volume_count_;++i)if(!api_.restore_volume(api_.context,volumes_[i]))return Result::failed;
        restored_=true;return verify_restored()?Result::ok:Result::failed;
    }
    Result before_source_change(){
        if(!configured_)return Result::ok;
        if(abandoned_||!api_.owner_thread()||!api_.current(api_.context,epoch_)||!source_current())return Result::stale;
        for(size_t i=0;i<created_count_;++i){const auto& c=created_[i];
            if(!c.retired&&!c.detached&&(!c.held.root||api_.target(c.held.root)!=c.held.object
                ||!api_.created_current(api_.context,c.held.object,c.kind,c.game_object)))return Result::stale;}
        // This is source withdrawal, not resource destruction. Reverse order
        // unregisters/disables Volumes before removing their private child GO.
        for(size_t i=created_count_;i>0;--i){auto& c=created_[i-1];if(c.retired||c.detached)continue;
            if(!api_.withdraw_created(api_.context,c.held.object,c.kind,c.game_object)
                ||!api_.created_withdrawn(api_.context,c.held.object,c.kind,c.game_object))return Result::failed;
            c.detached=true;}
        for(size_t i=0;i<go_count_;++i)if(!api_.restore_game_object(api_.context,gos_[i]))return Result::failed;
        for(size_t i=0;i<volume_count_;++i)if(!api_.restore_volume(api_.context,volumes_[i]))return Result::failed;
        restored_=true;withdrawn_=true;return verify_restored()?Result::ok:Result::failed;
    }
    void abandon_before_source_change()noexcept{withdrawn_=abandoned_=true;restored_=false;}
    Result release(bool owned){
        if(!configured_)return Result::ok;
        if(reader_count_)return Result::waiting;
        if(owned&&!abandoned_&&!withdrawn_){const auto r=restore();if(r!=Result::ok)return r;}
        if(owned&&!abandoned_&&withdrawn_&&!verify_restored())return Result::stale;
        if(created_count_&&!api_.cleanup_fenced(api_.context))return Result::waiting;
        for(size_t i=created_count_;i>0;--i){auto& c=created_[i-1];if(c.retired||!c.detached)continue;
            if(!c.held.root||api_.target(c.held.root)!=c.held.object
                ||!api_.created_withdrawn(api_.context,c.held.object,c.kind,c.game_object))return Result::stale;
            if(!api_.destroy_detached(api_.context,c.held.object,c.kind,c.game_object)
                ||!api_.detached_destroyed(api_.context,c.held.object,c.kind))return Result::failed;
            c.retired=true;}
        for(auto& c:created_)if(c.held.root){if((abandoned_||!owned)&&!c.retired)api_.abandon_created(api_.context,c.held.object,c.kind);api_.release(c.held.root);c.held={};}
        for(auto& r:source_roots_)if(r.root){api_.release(r.root);r={};}
        if(brain_root_.root)api_.release(brain_root_.root);
        if(asset_root_.root)api_.release(asset_root_.root);
        *this=Scope{};return Result::ok;
    }
};
} // namespace idoly_mp4_cine_volume_producer

// END_MP4_CINE_VOLUME_PRODUCER

// BEGIN_MP4_SOURCE_VOLUME_INPUT
// Shared-only integration snippet: embed into an EXISTING native owner header.
// No additional native input/translation unit is required. Bind Api only to the
// exact original methods in volume-source-input-pins.json and retained source
// owner/field-schema records; no scene-ancestry or name-only ownership fallback.
#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <cmath>
#endif
namespace idoly_mp4_volume_source {
// Bounded support for source-audited normal stage clb-001: 617 authored
// Volume targets, 600 profiles, 2253 components and 14221 parameter records.
// Larger source inputs are explicitly unsupported, never truncated.
inline constexpr size_t source_max_volumes=1024,source_max_profiles=1024,
 source_max_components=4096,source_max_parameters=16384,source_max_roots=32768;
enum class Result:int {ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};
enum class ValueKind:uint8_t {flat,texture2d,cubemap,mesh,curve,texture3d};
enum class ProfileAccess:uint8_t {readonly_input,mutable_owned};
enum Capability:uint32_t {restore_flat=1,restore_enabled=2,restore_layer=4,external_restore=8,activation_restore=16,profile_restore=32};
struct OwnerWitness {void*volume=nullptr;void*game_object=nullptr;uintptr_t owner=0,asset=0;uint64_t epoch=0,receipt=0;uint32_t capabilities=0;};
// A genuine completed Source Scope image; no native graph/operation authority.
struct CapturedVolumeImage {OwnerWitness owner{};void*shared=nullptr,*internal=nullptr;
 uint8_t scalar[16]{};int32_t layer=0,previous_layer=0;float previous_priority=0;
 bool enabled=false,active=false;uint64_t capture=0;};
struct DynamicVolumeWitness {void*volume=nullptr,*game_object=nullptr,*profile=nullptr;uintptr_t producer_method=0,asset=0;uint64_t epoch=0,receipt=0;bool newly_created=false;};
struct ProfileWitness {void*profile=nullptr;uintptr_t asset=0;uint64_t epoch=0,receipt=0;ProfileAccess access=ProfileAccess::readonly_input;};
struct FieldSpan {uint16_t offset=0,bytes=0;uint8_t float_lanes=0;};
struct ParameterShape {
    void*klass=nullptr;uintptr_t release=0;ValueKind kind=ValueKind::flat;
    uint16_t instance_bytes=0,value_offset=24,value_bytes=0,value_float_mask=0;uint8_t value_float_lanes=0,tail_count=0;
    FieldSpan tail[8]{}; // exact primitive-only declared fields (e.g. clamp/color flags)
};
struct Api {
    bool(*thread)()=nullptr;bool(*routes_ready)()=nullptr;bool(*current)(void*)=nullptr;
    uint64_t(*epoch)(void*)=nullptr;uintptr_t(*asset)(void*)=nullptr;void*(*manager)(void*)=nullptr;
    bool(*mapped)(uintptr_t,size_t,bool)=nullptr;bool(*exact_type)(void*,const char*)=nullptr;
    void*(*class_of)(void*)=nullptr;bool(*alive)(void*)=nullptr;
    uint32_t(*retain)(void*)=nullptr;void*(*retained)(uint32_t)=nullptr;void(*release_root)(uint32_t)=nullptr;
    size_t(*array_length)(void*)=nullptr;void*(*array_data)(void*)=nullptr;
    // Must include disabled owned volumes absent from manager40. These are
    // actual Stage/Camera source records, not FindObjects/ancestry guesses.
    bool(*owned_volumes)(void*,void**,size_t,size_t*)=nullptr;
    bool(*owner)(void*,void*,OwnerWitness*)=nullptr;
    bool(*profile_witness)(void*,void*,ProfileWitness*)=nullptr;
    bool(*dynamic_volume)(void*,void*,DynamicVolumeWitness*)=nullptr;
    bool(*delegated_restored)(void*,void*,const OwnerWitness&)=nullptr;
    uintptr_t cine_apply_postfx=0;
    // Exact closed runtime field/type schema and current virtual Release method
    // identity. Unknown mutable refs/ObjectParameter MUST NOT produce a shape.
    bool(*parameter_shape)(void*,ParameterShape*)=nullptr;
    bool(*component_parameters)(void*,void**,size_t)=nullptr;
    uintptr_t base_release=0,curve_release=0;
    bool(*immutable_asset)(void*,void*,ValueKind,void*,void*)=nullptr;
    void*(*curve_keys)(void*)=nullptr; // original AnimationCurve.get_keys; array Keyframe28
    void*(*game_object)(void*)=nullptr;bool(*enabled)(void*)=nullptr;
    int32_t(*layer)(void*)=nullptr;bool(*active_hierarchy)(void*)=nullptr;
    // All original setters/routes preverified. Reference writes MUST use the
    // source-pinned GC write-barrier route (owner,address,ref); never memcpy refs.
    bool(*write_value)(void*,size_t,const void*,size_t)=nullptr;
    bool(*write_reference)(void*,size_t,void*)=nullptr;
    bool(*set_enabled)(void*,bool)=nullptr;bool(*set_layer)(void*,int32_t)=nullptr;
    bool(*original_volume_update)(void*)=nullptr;
    bool(*list_remove_at)(void*,size_t)=nullptr;bool(*list_insert)(void*,size_t,void*)=nullptr;
    void*(*empty_cache)(void*,unsigned)=nullptr; // exact fresh Dictionary constructors, sorted32 / dirty48
    bool(*empty_cache_verified)(void*,void*,unsigned)=nullptr;
    bool(*fenced)(void*)=nullptr;
};
class Scope {
    static constexpr size_t volumes_max=source_max_volumes,profiles_max=source_max_profiles,
        components_max=source_max_components,parameters_max=source_max_parameters,
        roots_max=source_max_roots,curve_bytes_max=65536;
    struct Root {void*object=nullptr;uint32_t token=0;};
    struct List {void*object=nullptr,*array=nullptr;void**data=nullptr;int32_t count=0,version=0;};
    struct Volume {void*object=nullptr,*go=nullptr,*shared=nullptr,*internal=nullptr;OwnerWitness owner{};
        uint8_t scalar[16]{};int32_t previous_layer=0,layer=0;float previous_priority=0;
        bool owned=false,enabled=false,active=false,in_roster=false;};
    struct Profile {void*object=nullptr;ProfileWitness witness{};List list{};uint8_t dirty=0;size_t component_start=0,component_count=0;};
    struct Component {void*object=nullptr,*readonly_collection=nullptr;List list{};uint16_t profile=0;uint8_t active=0;size_t parameter_start=0,parameter_count=0;};
    struct Parameter {void*object=nullptr;ParameterShape shape{};uint16_t component=0;uint8_t override_state=0;
        uint8_t value[64]{},tail[8][16]{};void*reference=nullptr;void*curve=nullptr,*animation_curve=nullptr;
        uint8_t curve_scalar[16]{};size_t key_offset=0,key_bytes=0;};
    Api api_{};void*context_=nullptr,*manager_=nullptr,*roster_=nullptr,*baseline_sorted_=nullptr,*baseline_dirty_=nullptr,*published_sorted_=nullptr,*published_dirty_=nullptr;uint64_t epoch_=0;uintptr_t asset_=0;
    Root roots_[roots_max]{};Volume volumes_[volumes_max]{};Profile profiles_[profiles_max]{};
    Component components_[components_max]{};Parameter parameters_[parameters_max]{};
    void* saved_order_[volumes_max]{};uint8_t curve_bytes_[curve_bytes_max]{};
    size_t roots_count_=0,volume_count_=0,profile_count_=0,component_count_=0,parameter_count_=0,
        order_count_=0,curve_used_=0;uint64_t capture_receipt_=0;bool captured_=false,writes_done_=false;const char*error_="none";
    Result fail(Result r,const char*text){error_=text;return r;}
    template<class T>bool read(void*object,size_t offset,T&out)const{
        const uintptr_t p=reinterpret_cast<uintptr_t>(object),at=p+offset;
        if(!object||at<p||at+sizeof(T)<at||!api_.mapped(at,sizeof(T),false))return false;
        ::memcpy(&out,reinterpret_cast<const void*>(at),sizeof(T));return true;
    }
    bool bytes(void*object,size_t offset,void*out,size_t n)const{
        const uintptr_t p=reinterpret_cast<uintptr_t>(object),at=p+offset;
        if(!object||at<p||at+n<at||!api_.mapped(at,n,false))return false;
        ::memcpy(out,reinterpret_cast<const void*>(at),n);return true;
    }
    bool writable(void*object,size_t offset,size_t n)const{
        const uintptr_t p=reinterpret_cast<uintptr_t>(object),at=p+offset;
        return object&&at>=p&&at+n>=at&&api_.mapped(at,n,true);
    }
    static bool scalar_same(const uint8_t*a,const uint8_t*b){
        return a[0]==b[0]&&!::memcmp(a+4,b+4,12); // omit managed padding33..35
    }
    static bool shape_same(const ParameterShape&a,const ParameterShape&b){
        if(a.klass!=b.klass||a.release!=b.release||a.kind!=b.kind||a.instance_bytes!=b.instance_bytes
            ||a.value_offset!=b.value_offset||a.value_bytes!=b.value_bytes||a.value_float_mask!=b.value_float_mask||a.value_float_lanes!=b.value_float_lanes
            ||a.tail_count!=b.tail_count)return false;
        for(size_t i=0;i<a.tail_count;++i)if(a.tail[i].offset!=b.tail[i].offset||a.tail[i].bytes!=b.tail[i].bytes
            ||a.tail[i].float_lanes!=b.tail[i].float_lanes)return false;
        return true;
    }
    bool keep(void*object){
        if(!object)return true;
        for(size_t i=0;i<roots_count_;++i)if(roots_[i].object==object)return api_.retained(roots_[i].token)==object;
        if(roots_count_==roots_max)return false;
        const uint32_t token=api_.retain(object);
        if(!token||api_.retained(token)!=object){if(token)api_.release_root(token);return false;}
        roots_[roots_count_++]={object,token};return true;
    }
    bool current()const{
        if(!context_||!api_.thread()||!api_.current(context_)||api_.epoch(context_)!=epoch_||api_.asset(context_)!=asset_
            ||api_.manager(context_)!=manager_)return false;
        for(size_t i=0;i<roots_count_;++i)if(api_.retained(roots_[i].token)!=roots_[i].object)return false;
        return true;
    }
    bool list(void*object,List&out,size_t limit,bool root){
        if(!object||!read(object,16,out.array)||!read(object,24,out.count)||!read(object,28,out.version)
            ||out.count<0||size_t(out.count)>limit)return false;
        out.object=object;out.data=out.array?static_cast<void**>(api_.array_data(out.array)):nullptr;
        if(out.count&&(!out.array||api_.array_length(out.array)<size_t(out.count)||!out.data
            ||!api_.mapped(reinterpret_cast<uintptr_t>(out.data),size_t(out.count)*8,false)))return false;
        return !root||(keep(object)&&keep(out.array));
    }
    static bool same(const List&a,const List&b){return a.object==b.object&&a.array==b.array&&a.data==b.data&&a.count==b.count&&a.version==b.version;}
    bool list_item(const List&l,size_t index,void*&value)const{
        if(index>=size_t(l.count))return false;
        ::memcpy(&value,l.data+index,8);return value!=nullptr;
    }
    int volume_index(void*object)const{for(size_t i=0;i<volume_count_;++i)if(volumes_[i].object==object)return int(i);return -1;}
    bool finite(const uint8_t*value,size_t bytes,unsigned lanes)const{
        if(lanes&&size_t(lanes)*4!=bytes)return false;
        for(unsigned i=0;i<lanes;++i){float v=0;::memcpy(&v,value+i*4,4);if(!std::isfinite(v))return false;}
        return true;
    }
    bool value_finite(const uint8_t*value,const ParameterShape&s)const{
        if(!finite(value,s.value_bytes,s.value_float_lanes))return false;
        for(unsigned lane=0;lane<16;++lane)if(s.value_float_mask&(1u<<lane)){
            if(size_t(lane)*4+4>s.value_bytes)return false;
            float v=0;::memcpy(&v,value+lane*4,4);if(!std::isfinite(v))return false;
        }
        return true;
    }
    bool component_allowed(void*object)const{
        const char*names[]={"Solis.Rendering.VolumetricHeightFog","Solis.Common.GlobalActorWindParameter","Solis.Common.GlobalWindParameter","Solis.Common.Water.WaterCausticsVolume",
            "VL.PostProcessing.VLDOF","VL.PostProcessing.VLParaffin","VL.PostProcessing.VLStarStreak","VL.Rendering.VLTonemapping","VL.Rendering.PostProcess.VLActorParameter","VL.Rendering.PostProcess.VLBloom",
            "VL.Rendering.PostProcess.VLDensityFogVolume","VL.Rendering.PostProcess.VLFogVolume","VL.Rendering.PostProcess.VLLightmapVolume",
            "VL.Rendering.PostProcess.VLMirrorVolumeComponent","VL.Rendering.PostProcess.VLActorShadow",
            "UnityEngine.Rendering.Universal.Bloom","UnityEngine.Rendering.Universal.ChannelMixer","UnityEngine.Rendering.Universal.ChromaticAberration",
            "UnityEngine.Rendering.Universal.ColorAdjustments","UnityEngine.Rendering.Universal.ColorCurves","UnityEngine.Rendering.Universal.ColorLookup",
            "UnityEngine.Rendering.Universal.DepthOfField","UnityEngine.Rendering.Universal.FilmGrain","UnityEngine.Rendering.Universal.LensDistortion",
            "UnityEngine.Rendering.Universal.LiftGammaGain","UnityEngine.Rendering.Universal.MotionBlur","UnityEngine.Rendering.Universal.PaniniProjection",
            "UnityEngine.Rendering.Universal.ShadowsMidtonesHighlights","UnityEngine.Rendering.Universal.SplitToning","UnityEngine.Rendering.Universal.Tonemapping",
            "UnityEngine.Rendering.Universal.Vignette","UnityEngine.Rendering.Universal.WhiteBalance"};
        for(const char* name:names)if(api_.exact_type(object,name))return true;
        return false;
    }
    bool shape(void*object,ParameterShape&out)const{
        out=ParameterShape{};
        if(!api_.parameter_shape(object,&out)||!out.klass||out.klass!=api_.class_of(object)||out.value_offset<17||out.value_offset>24
            ||!out.value_bytes||out.value_bytes>64||out.instance_bytes<out.value_offset+out.value_bytes||out.tail_count>8)return false;
        if(out.kind==ValueKind::flat){if(out.release!=api_.base_release)return false;}
        else if(out.kind==ValueKind::curve){if(out.release!=api_.curve_release||out.value_bytes!=8)return false;}
        else if(out.kind==ValueKind::texture2d||out.kind==ValueKind::cubemap||out.kind==ValueKind::mesh||out.kind==ValueKind::texture3d){if(out.release!=api_.base_release||out.value_bytes!=8)return false;}
        else return false;
        if(out.kind!=ValueKind::flat&&(out.value_float_lanes||out.value_float_mask))return false;
        for(size_t i=0;i<out.tail_count;++i){const auto&s=out.tail[i];
            if(!s.bytes||s.bytes>16||s.offset<out.value_offset+out.value_bytes||size_t(s.offset)+s.bytes>out.instance_bytes)return false;
            for(size_t j=0;j<i;++j)if(s.offset<out.tail[j].offset+out.tail[j].bytes&&out.tail[j].offset<s.offset+s.bytes)return false;
        }
        return true;
    }
    bool owner(void*object,OwnerWitness&out)const{
        return api_.owner(context_,object,&out)&&out.volume==object&&out.game_object==api_.game_object(object)
            &&out.epoch==epoch_&&out.asset==asset_&&out.receipt&&out.owner;
    }
    bool dynamic(void*object)const{
        if(!api_.dynamic_volume||!api_.cine_apply_postfx)return false;
        DynamicVolumeWitness w{};void*internal=nullptr,*shared=nullptr;
        return api_.dynamic_volume(context_,object,&w)&&w.volume==object&&w.newly_created
            &&w.producer_method==api_.cine_apply_postfx&&w.asset==asset_&&w.epoch==epoch_&&w.receipt
            &&api_.exact_type(object,"UnityEngine.Rendering.Volume")&&api_.alive(object)
            &&w.game_object==api_.game_object(object)&&api_.alive(w.game_object)
            &&read(object,48,shared)&&read(object,64,internal)&&w.profile==(internal?internal:shared);
    }
    Result add_volume(void*object,bool in_roster){
        const int old=volume_index(object);if(old>=0){volumes_[size_t(old)].in_roster|=in_roster;return Result::ok;}
        if(volume_count_==volumes_max||!api_.exact_type(object,"UnityEngine.Rendering.Volume")||!api_.alive(object)||!keep(object))
            return fail(Result::unsupported,"volume_source_object_unverified");
        Volume&v=volumes_[volume_count_++];v=Volume{};v.object=object;v.in_roster=in_roster;v.go=api_.game_object(object);
        if(!v.go||!api_.alive(v.go)||!keep(v.go)||!bytes(object,32,v.scalar,16)||!read(object,48,v.shared)||!read(object,64,v.internal)
            ||!read(object,56,v.previous_layer)||!read(object,60,v.previous_priority)||!keep(v.shared)||!keep(v.internal))
            return fail(Result::stale,"volume_source_fields_unreadable");
        v.enabled=api_.enabled(object);v.active=api_.active_hierarchy(v.go);v.layer=api_.layer(v.go);v.owned=owner(object,v.owner);
        if(v.owned&&(v.owner.capabilities&(external_restore|activation_restore|profile_restore))&&!api_.delegated_restored)
            return fail(Result::unsupported,"volume_source_delegated_restore_unavailable");
        float priority=0;::memcpy(&priority,v.scalar+4,4);
        if(v.scalar[0]>1||!finite(v.scalar+4,12,3)||!std::isfinite(v.previous_priority)||v.layer<0||v.layer>31)
            return fail(Result::unsupported,"volume_source_value_invalid");
        if(v.in_roster&&v.enabled&&v.active&&(v.previous_layer!=v.layer||v.previous_priority!=priority))
            return fail(Result::waiting,"volume_source_registration_history_not_settled");
        if(v.in_roster!=bool(v.enabled&&v.active))return fail(Result::waiting,"volume_source_registration_not_settled");
        return Result::ok;
    }
    Result curve(Parameter&p,bool capture){
        if(!p.reference||!api_.exact_type(p.reference,"UnityEngine.Rendering.TextureCurve"))return fail(Result::unsupported,"volume_source_curve_unverified");
        uint8_t scalar[16]{};void*animation=nullptr;
        if(!bytes(p.reference,16,scalar,16)||!read(p.reference,32,animation)||!animation
            ||!api_.exact_type(animation,"UnityEngine.AnimationCurve")||!keep(animation))return fail(Result::stale,"volume_source_curve_changed");
        void*keys=api_.curve_keys(animation);if(!keys)return fail(Result::failed,"volume_source_curve_keys_failed");
        const uint32_t token=api_.retain(keys);
        if(!token||api_.retained(token)!=keys){if(token)api_.release_root(token);return fail(Result::failed,"volume_source_curve_keys_failed");}
        struct TemporaryRoot{Api&api;uint32_t token;~TemporaryRoot(){api.release_root(token);}} root{api_,token};
        const size_t count=api_.array_length(keys);void*data=api_.array_data(keys);
        if(count>1024||(count&&(!data||!api_.mapped(reinterpret_cast<uintptr_t>(data),count*28,false))))
            return fail(Result::unsupported,"volume_source_curve_keys_invalid");
        const size_t n=count*28;
        if(capture){if(n>curve_bytes_max-curve_used_)return fail(Result::unsupported,"volume_source_curve_budget_exceeded");
            p.curve=p.reference;p.animation_curve=animation;::memcpy(p.curve_scalar,scalar,16);p.key_offset=curve_used_;p.key_bytes=n;
            if(n)::memcpy(curve_bytes_+curve_used_,data,n);
            curve_used_+=n;
        }else if(p.curve!=p.reference||p.animation_curve!=animation||p.key_bytes!=n||::memcmp(p.curve_scalar,scalar,16)
            ||(n&&::memcmp(curve_bytes_+p.key_offset,data,n)))return fail(Result::stale,"volume_source_readonly_curve_changed");
        return api_.retained(token)==keys?Result::ok:fail(Result::stale,"volume_source_curve_keys_changed");
    }
    Result parameter(void*object,size_t component){
        if(parameter_count_==parameters_max||!keep(object))return fail(Result::unsupported,"volume_source_parameter_budget");
        for(size_t i=0;i<parameter_count_;++i)if(parameters_[i].object==object
            &&(profiles_[components_[parameters_[i].component].profile].witness.access==ProfileAccess::mutable_owned
                ||profiles_[components_[component].profile].witness.access==ProfileAccess::mutable_owned))
            return fail(Result::unsupported,"volume_source_mutable_parameter_alias");
        Parameter&p=parameters_[parameter_count_++];p=Parameter{};p.object=object;p.component=uint16_t(component);
        if(!shape(object,p.shape)||!read(object,16,p.override_state)||p.override_state>1
            ||!bytes(object,p.shape.value_offset,p.value,p.shape.value_bytes)||!value_finite(p.value,p.shape))
            return fail(Result::unsupported,"volume_source_parameter_schema_unverified");
        if(p.shape.kind==ValueKind::flat&&p.shape.value_bytes==1&&p.value[0]>1)return fail(Result::unsupported,"volume_source_bool_invalid");
        for(size_t i=0;i<p.shape.tail_count;++i)if(!bytes(object,p.shape.tail[i].offset,p.tail[i],p.shape.tail[i].bytes)
            ||!finite(p.tail[i],p.shape.tail[i].bytes,p.shape.tail[i].float_lanes)||(p.shape.tail[i].bytes==1&&p.tail[i][0]>1))return fail(Result::unsupported,"volume_source_parameter_value_invalid");
        if(p.shape.kind!=ValueKind::flat){::memcpy(&p.reference,p.value,8);if(!keep(p.reference))return fail(Result::failed,"volume_source_parameter_root_failed");
            const Profile&profile=profiles_[components_[component].profile];
            if(p.shape.kind==ValueKind::curve){if(profile.witness.access!=ProfileAccess::readonly_input)
                    return fail(Result::unsupported,"volume_source_mutable_curve_inputs_unverified");
                return curve(p,true);
            }
            if(p.reference&&!api_.immutable_asset(context_,p.reference,p.shape.kind,components_[component].object,object))return fail(Result::unsupported,"volume_source_texture_not_immutable");
        }
        return Result::ok;
    }
    Result profile(void*object,bool foreign){
        if(!object)return Result::ok;
        for(size_t i=0;i<profile_count_;++i)if(profiles_[i].object==object){
            if(foreign&&profiles_[i].witness.access==ProfileAccess::mutable_owned)return fail(Result::unsupported,"volume_source_profile_shared_with_unowned");
            return Result::ok;
        }
        if(profile_count_==profiles_max||!api_.exact_type(object,"UnityEngine.Rendering.VolumeProfile")||!api_.alive(object)||!keep(object))
            return fail(Result::unsupported,"volume_source_profile_unverified");
        const size_t id=profile_count_++;Profile&p=profiles_[id];p=Profile{};p.object=object;
        if(!api_.profile_witness(context_,object,&p.witness)||p.witness.profile!=object||p.witness.epoch!=epoch_
            ||p.witness.asset!=asset_||!p.witness.receipt||(foreign&&p.witness.access!=ProfileAccess::readonly_input))
            return fail(Result::unsupported,"volume_source_profile_owner_unverified");
        void*list_object=nullptr;
        if(!read(object,24,list_object)||!list(list_object,p.list,components_max,true)||!read(object,32,p.dirty)||p.dirty>1)
            return fail(Result::unsupported,"volume_source_profile_components_unverified");
        p.component_start=component_count_;p.component_count=size_t(p.list.count);
        for(size_t i=0;i<size_t(p.list.count);++i){void*value=nullptr;
            if(!list_item(p.list,i,value)||!api_.alive(value)||!component_allowed(value)||!keep(value)||component_count_==components_max)
                return fail(Result::unsupported,"volume_source_component_unverified");
            for(size_t q=0;q<component_count_;++q)if(components_[q].object==value
                &&(profiles_[components_[q].profile].witness.access==ProfileAccess::mutable_owned
                    ||p.witness.access==ProfileAccess::mutable_owned))return fail(Result::unsupported,"volume_source_mutable_component_alias");
            const size_t cid=component_count_++;Component&c=components_[cid];c=Component{};c.object=value;c.profile=uint16_t(id);void*items=nullptr;
            if(!read(value,24,c.active)||c.active>1||!read(value,40,c.readonly_collection)||!keep(c.readonly_collection)
                ||!read(c.readonly_collection,16,items)||!list(items,c.list,parameters_max,true)
                ||!api_.component_parameters(value,c.list.data,size_t(c.list.count)))
                return fail(Result::unsupported,"volume_source_component_parameters_unverified");
            c.parameter_start=parameter_count_;c.parameter_count=size_t(c.list.count);
            for(size_t j=0;j<size_t(c.list.count);++j){void*param=nullptr;
                if(!list_item(c.list,j,param))return fail(Result::stale,"volume_source_parameter_changed");
                Result result=parameter(param,cid);if(result!=Result::ok)return result;
            }
        }
        return Result::ok;
    }
    Result roster(List&out,bool allow_dynamic=true){void*object=nullptr;
        if(!current()||!read(manager_,40,object)||object!=roster_||!list(object,out,volumes_max,false))
            return fail(Result::stale,"volume_source_roster_changed");
        // Preserve every unowned identity AND relative order. Only the known
        // owned subset may have registered/unregistered during this lease.
        size_t foreign=0;
        for(size_t i=0;i<size_t(out.count);++i){void*value=nullptr;if(!list_item(out,i,value))return fail(Result::stale,"volume_source_roster_changed");
            for(size_t j=0;j<i;++j)if(out.data[j]==value)return fail(Result::stale,"volume_source_duplicate_roster_entry");
            const int index=volume_index(value);
            if(index<0){if(dynamic(value)){if(!allow_dynamic)return fail(Result::waiting,"volume_source_private_producer_cleanup_pending");continue;}
                return fail(Result::stale,"volume_source_unowned_roster_changed");}
            if(!volumes_[size_t(index)].owned){
                while(foreign<order_count_&&volumes_[size_t(volume_index(saved_order_[foreign]))].owned)++foreign;
                if(foreign==order_count_||saved_order_[foreign++]!=value)return fail(Result::stale,"volume_source_unowned_roster_changed");
            }
        }
        while(foreign<order_count_&&volumes_[size_t(volume_index(saved_order_[foreign]))].owned)++foreign;
        if(foreign!=order_count_)return fail(Result::stale,"volume_source_unowned_roster_changed");
        return Result::ok;
    }
    Result preflight(bool restore,bool require_fence=true){
        if(!captured_||!current()||!api_.routes_ready()||(require_fence&&!api_.fenced(context_)))return fail(Result::stale,"volume_source_owner_lost");
        List current_roster{};Result result=roster(current_roster,!restore);if(result!=Result::ok)return result;
        for(size_t i=0;i<volume_count_;++i){const Volume&v=volumes_[i];void*go=api_.game_object(v.object),*shared=nullptr,*internal=nullptr;uint8_t scalar[16]{};
            if(!api_.alive(v.object)||go!=v.go||!api_.alive(go)||!read(v.object,48,shared)||!read(v.object,64,internal)
                ||!bytes(v.object,32,scalar,16))return fail(Result::stale,"volume_source_reference_changed");
            const bool delegated=v.owned&&(v.owner.capabilities&(external_restore|profile_restore));
            if(!delegated&&(shared!=v.shared||internal!=v.internal))return fail(Result::stale,"volume_source_reference_changed");
            if(scalar[0]>1||!finite(scalar+4,12,3))return fail(Result::unsupported,"volume_source_value_invalid");
            const bool enabled=api_.enabled(v.object),active=api_.active_hierarchy(go);const int32_t layer=api_.layer(go);
            int32_t previous_layer=0;float previous_priority=0;
            if(!read(v.object,56,previous_layer)||!read(v.object,60,previous_priority))return fail(Result::stale,"volume_source_history_changed");
            if(v.owned){OwnerWitness w{};
                if(!owner(v.object,w)||w.owner!=v.owner.owner||w.receipt!=v.owner.receipt||w.capabilities!=v.owner.capabilities)
                    return fail(Result::stale,"volume_source_owner_changed");
                if(w.capabilities&external_restore){
                    if(restore&&(!api_.delegated_restored(context_,v.object,w)||active!=v.active||enabled!=v.enabled||layer!=v.layer
                        ||shared!=v.shared||internal!=v.internal||previous_layer!=v.previous_layer||previous_priority!=v.previous_priority||!scalar_same(scalar,v.scalar)))
                        return fail(Result::waiting,"volume_source_delegated_owner_not_restored");
                    continue;
                }
                // Exact Mono restores only profile/cache references; this Source
                // Scope still owns Timeline-changed priority/weight/registration.
                if((w.capabilities&profile_restore)&&restore
                    &&(!api_.delegated_restored(context_,v.object,w)||shared!=v.shared||internal!=v.internal))
                    return fail(Result::waiting,"volume_source_profile_owner_not_restored");
                if(w.capabilities&activation_restore){
                    if(restore&&(!api_.delegated_restored(context_,v.object,w)||active!=v.active))return fail(Result::waiting,"volume_source_activation_owner_not_restored");
                }else if(active!=v.active)return fail(Result::unsupported,"volume_source_activation_not_restored");
                if(restore&&((enabled!=v.enabled&&!(w.capabilities&restore_enabled))||(layer!=v.layer&&!(w.capabilities&restore_layer))
                    ||(!scalar_same(v.scalar,scalar)&&!(w.capabilities&restore_flat))))
                    return fail(Result::unsupported,"volume_source_write_not_owned");
            }else if(enabled!=v.enabled||active!=v.active||layer!=v.layer||previous_layer!=v.previous_layer
                ||previous_priority!=v.previous_priority||!scalar_same(scalar,v.scalar))return fail(Result::stale,"volume_source_unowned_input_changed");
        }
        for(size_t i=0;i<profile_count_;++i){Profile&p=profiles_[i];ProfileWitness w{};List after{};void*object=nullptr;uint8_t dirty=0;
            if(!api_.alive(p.object)||!api_.profile_witness(context_,p.object,&w)||w.profile!=p.object||w.epoch!=epoch_
                ||w.asset!=asset_||w.receipt!=p.witness.receipt||w.access!=p.witness.access||!read(p.object,24,object)
                ||object!=p.list.object||!list(object,after,components_max,false)||!same(after,p.list)||!read(p.object,32,dirty)||dirty>1)
                return fail(Result::stale,"volume_source_profile_changed");
            for(size_t j=0;j<p.component_count;++j)if(after.data[j]!=components_[p.component_start+j].object)
                return fail(Result::stale,"volume_source_profile_contents_changed");
            if(w.access==ProfileAccess::readonly_input&&dirty!=p.dirty)return fail(Result::stale,"volume_source_readonly_profile_changed");
        }
        for(size_t i=0;i<component_count_;++i){const Component&c=components_[i];void*collection=nullptr,*items=nullptr;List after{};uint8_t active=0;
            if(!api_.alive(c.object)||!component_allowed(c.object)||!read(c.object,24,active)||active>1||!read(c.object,40,collection)
                ||collection!=c.readonly_collection||!read(collection,16,items)||items!=c.list.object
                ||!list(items,after,parameters_max,false)||!same(after,c.list)
                ||!api_.component_parameters(c.object,after.data,size_t(after.count)))return fail(Result::stale,"volume_source_component_changed");
            for(size_t j=0;j<c.parameter_count;++j)if(after.data[j]!=parameters_[c.parameter_start+j].object)
                return fail(Result::stale,"volume_source_component_contents_changed");
            if(profiles_[c.profile].witness.access==ProfileAccess::readonly_input&&active!=c.active)
                return fail(Result::stale,"volume_source_readonly_component_changed");
        }
        for(size_t i=0;i<parameter_count_;++i){Parameter&p=parameters_[i];ParameterShape after{};uint8_t value[64]{},override_state=0;
            if(!shape(p.object,after)||!shape_same(after,p.shape)||!read(p.object,16,override_state)
                ||override_state>1||!bytes(p.object,p.shape.value_offset,value,p.shape.value_bytes)||!value_finite(value,p.shape)
                ||(p.shape.kind==ValueKind::flat&&p.shape.value_bytes==1&&value[0]>1))
                return fail(Result::stale,"volume_source_parameter_changed");
            const bool readonly=profiles_[components_[p.component].profile].witness.access==ProfileAccess::readonly_input;
            if(readonly&&(override_state!=p.override_state||::memcmp(value,p.value,p.shape.value_bytes)))return fail(Result::stale,"volume_source_readonly_parameter_changed");
            for(size_t j=0;j<p.shape.tail_count;++j){uint8_t tail[16]{};
                if(!bytes(p.object,p.shape.tail[j].offset,tail,p.shape.tail[j].bytes)||!finite(tail,p.shape.tail[j].bytes,p.shape.tail[j].float_lanes)||(p.shape.tail[j].bytes==1&&tail[0]>1)
                    ||(readonly&&::memcmp(tail,p.tail[j],p.shape.tail[j].bytes)))return fail(Result::stale,"volume_source_parameter_changed");
            }
            if(p.shape.kind==ValueKind::curve){Result r=curve(p,false);if(r!=Result::ok)return r;}
            else if(p.shape.kind!=ValueKind::flat){void*reference=nullptr;::memcpy(&reference,value,8);
                if(reference&&!api_.immutable_asset(context_,reference,p.shape.kind,components_[p.component].object,p.object))return fail(Result::unsupported,"volume_source_texture_not_immutable");}
        }
        if(restore){
            if(!writable(manager_,32,8)||!writable(manager_,48,8)||!writable(roster_,16,16))
                return fail(Result::unsupported,"volume_source_write_mapping_unverified");
            for(size_t i=0;i<volume_count_;++i){const auto&v=volumes_[i];
                if(v.owned&&!(v.owner.capabilities&external_restore)&&(!writable(v.object,32,16)||!writable(v.object,56,8)))
                    return fail(Result::unsupported,"volume_source_write_mapping_unverified");}
            for(size_t i=0;i<profile_count_;++i)if(profiles_[i].witness.access==ProfileAccess::mutable_owned&&!writable(profiles_[i].object,32,1))
                return fail(Result::unsupported,"volume_source_write_mapping_unverified");
            for(size_t i=0;i<component_count_;++i)if(profiles_[components_[i].profile].witness.access==ProfileAccess::mutable_owned&&!writable(components_[i].object,24,1))
                return fail(Result::unsupported,"volume_source_write_mapping_unverified");
            for(size_t i=0;i<parameter_count_;++i){const auto&p=parameters_[i];
                if(profiles_[components_[p.component].profile].witness.access!=ProfileAccess::mutable_owned)continue;
                if(!writable(p.object,16,1)||!writable(p.object,p.shape.value_offset,p.shape.value_bytes))return fail(Result::unsupported,"volume_source_write_mapping_unverified");
                for(size_t j=0;j<p.shape.tail_count;++j)if(!writable(p.object,p.shape.tail[j].offset,p.shape.tail[j].bytes))
                    return fail(Result::unsupported,"volume_source_write_mapping_unverified");}
        }
        return current()?Result::ok:fail(Result::stale,"volume_source_owner_lost");
    }
    bool write(void*object,size_t offset,const void*value,size_t n){
        if(!current()||!api_.write_value(object,offset,value,n))return false;
        uint8_t check[64]{};
        return n<=64&&bytes(object,offset,check,n)&&!::memcmp(check,value,n)&&current();
    }
    Result reorder(){List list_now{};Result result=roster(list_now);if(result!=Result::ok)return result;
        bool equal=size_t(list_now.count)==order_count_;
        for(size_t i=0;equal&&i<order_count_;++i)equal=list_now.data[i]==saved_order_[i];
        if(equal)return Result::ok;
        for(size_t i=size_t(list_now.count);i>0;--i){const int index=volume_index(list_now.data[i-1]);
            if(index>=0&&volumes_[size_t(index)].owned){if(!current()||!api_.list_remove_at(roster_,i-1))return fail(Result::failed,"volume_source_roster_write_failed");}}
        for(size_t i=0;i<order_count_;++i){const int index=volume_index(saved_order_[i]);
            if(index>=0&&volumes_[size_t(index)].owned){if(!current()||!api_.list_insert(roster_,i,saved_order_[i]))return fail(Result::failed,"volume_source_roster_write_failed");}}
        return Result::ok;
    }
public:
    Scope()=default;Scope(const Scope&)=delete;Scope&operator=(const Scope&)=delete;
    ~Scope(){clear();}const char*error()const{return error_;}
    void clear(){for(size_t i=roots_count_;i>0;--i)if(roots_[i-1].token)api_.release_root(roots_[i-1].token);
        roots_count_=volume_count_=profile_count_=component_count_=parameter_count_=order_count_=curve_used_=0;
        capture_receipt_=0;captured_=writes_done_=false;context_=manager_=roster_=baseline_sorted_=baseline_dirty_=published_sorted_=published_dirty_=nullptr;epoch_=0;asset_=0;}
    Result capture_attempt(Api api,void*context){
        if(captured_||roots_count_)return fail(Result::invalid,"volume_source_already_captured");
        api_=api;context_=context;
        if(!api.thread||!api.routes_ready||!api.current||!api.epoch||!api.asset||!api.manager||!api.mapped||!api.exact_type||!api.class_of||!api.alive
            ||!api.retain||!api.retained||!api.release_root||!api.array_length||!api.array_data||!api.owned_volumes||!api.owner||!api.profile_witness
            ||!api.parameter_shape||!api.component_parameters||!api.base_release||!api.curve_release||!api.immutable_asset||!api.curve_keys||!api.game_object||!api.enabled||!api.layer
            ||!api.active_hierarchy||!api.write_value||!api.write_reference||!api.set_enabled||!api.set_layer||!api.original_volume_update
            ||!api.list_remove_at||!api.list_insert||!api.empty_cache||!api.empty_cache_verified||!api.fenced||!api.routes_ready()||!api.thread())
            return fail(Result::unsupported,"volume_source_api_unverified");
        epoch_=api.epoch(context);asset_=api.asset(context);manager_=api.manager(context);
        if(!epoch_||!asset_||!manager_||!keep(manager_)||!current()||!api.fenced(context))return fail(Result::stale,"volume_source_owner_lost");
        List original{};if(!read(manager_,32,baseline_sorted_)||!read(manager_,48,baseline_dirty_)||!keep(baseline_sorted_)||!keep(baseline_dirty_)
            ||!read(manager_,40,roster_)||!list(roster_,original,volumes_max,true))return fail(Result::unsupported,"volume_source_roster_unverified");
        for(size_t i=0;i<size_t(original.count);++i){void*value=nullptr;if(!list_item(original,i,value))return fail(Result::stale,"volume_source_roster_changed");
            if(volume_index(value)>=0)return fail(Result::unsupported,"volume_source_duplicate_roster_entry");
            if(dynamic(value))return fail(Result::invalid,"volume_source_capture_after_private_creation");
            saved_order_[order_count_++]=value;Result r=add_volume(value,true);if(r!=Result::ok)return r;}
        void*owned[volumes_max]{};size_t count=0;
        if(!api.owned_volumes(context,owned,volumes_max,&count)||count>volumes_max)return fail(Result::unsupported,"volume_source_owned_inventory_unverified");
        for(size_t i=0;i<count;++i){Result r=add_volume(owned[i],false);if(r!=Result::ok)return r;
            const int index=volume_index(owned[i]);if(index<0||!volumes_[size_t(index)].owned)return fail(Result::unsupported,"volume_source_owned_inventory_unverified");}
        for(size_t i=0;i<volume_count_;++i){const auto&v=volumes_[i];Result r=profile(v.shared,!v.owned);if(r==Result::ok)r=profile(v.internal,!v.owned);if(r!=Result::ok)return r;}
        List after{};if(!list(roster_,after,volumes_max,false)||!same(original,after)||!current())return fail(Result::stale,"volume_source_roster_changed");
        captured_=true;Result result=preflight(false);
        if(result==Result::ok){static uint64_t sequence=0;
            if(sequence==~uint64_t(0))return fail(Result::unsupported,"volume_source_capture_receipt_exhausted");
            capture_receipt_=++sequence;error_="none";
        }return result;
    }
    Result capture(Api api,void*context){
        if(captured_||roots_count_)return fail(Result::invalid,"volume_source_already_captured");
        const Result result=capture_attempt(api,context);
        if(result!=Result::ok){const char*reason=error_;clear();error_=reason;}return result;
    }
    // Read-only saved image query. It never reads a saved/retired native graph.
    // All source roots, exact owner capability and actual held fence are checked
    // independently of captured_, including failed-final-preflight captures.
    bool captured_image(void*object,CapturedVolumeImage*out)noexcept{try{
        if(out)*out={};
        if(!out||!capture_receipt_||!captured_||!current()||!api_.fenced(context_))return false;
        const int index=volume_index(object);if(index<0)return false;const auto&v=volumes_[size_t(index)];OwnerWitness now{};
        if(!v.owned||!owner(object,now)||now.owner!=v.owner.owner||now.receipt!=v.owner.receipt
            ||now.capabilities!=v.owner.capabilities||!api_.alive(v.object)||!api_.alive(v.go)||api_.game_object(v.object)!=v.go)return false;
        CapturedVolumeImage saved{};saved.owner=v.owner;saved.shared=v.shared;saved.internal=v.internal;
        ::memcpy(saved.scalar,v.scalar,16);saved.layer=v.layer;saved.previous_layer=v.previous_layer;saved.previous_priority=v.previous_priority;
        saved.enabled=v.enabled;saved.active=v.active;saved.capture=capture_receipt_;
        if(!current()||!api_.fenced(context_))return false;
        *out=saved;return true;
    }catch(...){if(out)*out={};return false;}}
    uint64_t capture_receipt_raw()const noexcept{return captured_?capture_receipt_:0;}
    bool owns_volume(void*object){
        if(!captured_||!current())return false;
        const int index=volume_index(object);
        if(index>=0){const auto&v=volumes_[size_t(index)];OwnerWitness now{};
            return v.owned&&owner(object,now)&&now.owner==v.owner.owner&&now.receipt==v.owner.receipt;
        }
        return dynamic(object);
    }
    Result validate(){return preflight(false);}
    // Read-only input guard during an owned draw. Caller supplies its actual
    // phase/read-owner receipt; restoration/capture still require fenced().
    Result validate_inputs(){return preflight(false,false);}
    Result restore(){
        if(writes_done_)return verify();
        Result result=preflight(true);if(result!=Result::ok)return result;
        void*sorted=api_.empty_cache(context_,0),*dirty=api_.empty_cache(context_,1);
        void*live_sorted=nullptr,*live_dirty=nullptr;
        if(!read(manager_,32,live_sorted)||!read(manager_,48,live_dirty))return fail(Result::stale,"volume_source_cache_changed");
        if(!sorted||!dirty||sorted==dirty||sorted==baseline_sorted_||sorted==baseline_dirty_||dirty==baseline_sorted_||dirty==baseline_dirty_
            ||sorted==live_sorted||sorted==live_dirty||dirty==live_sorted||dirty==live_dirty
            ||!keep(sorted)||!keep(dirty)||!api_.empty_cache_verified(context_,sorted,0)
            ||!api_.empty_cache_verified(context_,dirty,1))return fail(Result::unsupported,"volume_source_cache_factory_unverified");
        // Allocation/GC may have run: repeat WHOLE preflight before first write.
        result=preflight(true);if(result!=Result::ok)return result;
        for(size_t i=0;i<volume_count_;++i){auto&v=volumes_[i];if(!v.owned||(v.owner.capabilities&external_restore))continue;
            uint8_t now[16]{};if(!bytes(v.object,32,now,16))return fail(Result::stale,"volume_source_fields_unreadable");
            if(now[0]!=v.scalar[0]&&!write(v.object,32,v.scalar,1))return fail(Result::failed,"volume_source_value_restore_failed");
            for(size_t field=36;field<=44;field+=4)if(::memcmp(now+field-32,v.scalar+field-32,4)&&!write(v.object,field,v.scalar+field-32,4))
                return fail(Result::failed,"volume_source_value_restore_failed");
            if(api_.layer(v.go)!=v.layer&&(!current()||!api_.set_layer(v.go,v.layer)))return fail(Result::failed,"volume_source_layer_restore_failed");
            if(api_.enabled(v.object)!=v.enabled&&(!current()||!api_.set_enabled(v.object,v.enabled)))return fail(Result::failed,"volume_source_enabled_restore_failed");
            if(v.enabled&&v.active&&(!current()||!api_.original_volume_update(v.object)))return fail(Result::failed,"volume_source_registration_restore_failed");
            if(!write(v.object,56,&v.previous_layer,4)||!write(v.object,60,&v.previous_priority,4))return fail(Result::failed,"volume_source_history_restore_failed");
        }
        for(size_t i=0;i<profile_count_;++i)if(profiles_[i].witness.access==ProfileAccess::mutable_owned)
            if(!write(profiles_[i].object,32,&profiles_[i].dirty,1))return fail(Result::failed,"volume_source_profile_restore_failed");
        for(size_t i=0;i<component_count_;++i)if(profiles_[components_[i].profile].witness.access==ProfileAccess::mutable_owned)
            if(!write(components_[i].object,24,&components_[i].active,1))return fail(Result::failed,"volume_source_component_restore_failed");
        for(size_t i=0;i<parameter_count_;++i){auto&p=parameters_[i];if(profiles_[components_[p.component].profile].witness.access!=ProfileAccess::mutable_owned)continue;
            if(!write(p.object,16,&p.override_state,1))return fail(Result::failed,"volume_source_parameter_restore_failed");
            if(p.shape.kind==ValueKind::flat){if(!write(p.object,p.shape.value_offset,p.value,p.shape.value_bytes))return fail(Result::failed,"volume_source_parameter_restore_failed");}
            else if(!current()||!api_.write_reference(p.object,p.shape.value_offset,p.reference))return fail(Result::failed,"volume_source_reference_restore_failed");
            for(size_t j=0;j<p.shape.tail_count;++j)if(!write(p.object,p.shape.tail[j].offset,p.tail[j],p.shape.tail[j].bytes))return fail(Result::failed,"volume_source_parameter_restore_failed");
        }
        result=reorder();if(result!=Result::ok)return result;
        if(!current()||!api_.write_reference(manager_,32,sorted)||!current()||!api_.write_reference(manager_,48,dirty))
            return fail(Result::failed,"volume_source_cache_publish_failed");
        void*actual_sorted=nullptr,*actual_dirty=nullptr;
        if(!read(manager_,32,actual_sorted)||actual_sorted!=sorted||!read(manager_,48,actual_dirty)||actual_dirty!=dirty)
            return fail(Result::failed,"volume_source_cache_publish_failed");
        published_sorted_=sorted;published_dirty_=dirty;writes_done_=true;return verify();
    }
    Result verify(){
        Result result=preflight(true);if(result!=Result::ok)return result;List now{};result=roster(now);if(result!=Result::ok)return result;
        if(writes_done_){void*sorted=nullptr,*dirty=nullptr;
            if(!read(manager_,32,sorted)||sorted!=published_sorted_||!read(manager_,48,dirty)||dirty!=published_dirty_)
                return fail(Result::failed,"volume_source_cache_publish_failed");}
        if(size_t(now.count)!=order_count_)return fail(Result::waiting,"volume_source_registration_not_settled");
        for(size_t i=0;i<order_count_;++i)if(now.data[i]!=saved_order_[i])return fail(Result::failed,"volume_source_roster_restore_failed");
        for(size_t i=0;i<volume_count_;++i){const auto&v=volumes_[i];uint8_t scalar[16]{};int32_t layer=0;float priority=0;
            if(!bytes(v.object,32,scalar,16)||!scalar_same(scalar,v.scalar)||api_.enabled(v.object)!=v.enabled||api_.layer(v.go)!=v.layer
                ||!read(v.object,56,layer)||layer!=v.previous_layer||!read(v.object,60,priority)||priority!=v.previous_priority)
                return fail(Result::failed,"volume_source_restore_verification_failed");}
        for(size_t i=0;i<profile_count_;++i){uint8_t dirty=0;if(!read(profiles_[i].object,32,dirty)||dirty!=profiles_[i].dirty)
            return fail(Result::failed,"volume_source_profile_restore_failed");}
        for(size_t i=0;i<component_count_;++i){uint8_t active=0;if(!read(components_[i].object,24,active)||active!=components_[i].active)
            return fail(Result::failed,"volume_source_component_restore_failed");}
        for(size_t i=0;i<parameter_count_;++i){const auto&p=parameters_[i];uint8_t value[64]{},override_state=0;
            if(!read(p.object,16,override_state)||override_state!=p.override_state||!bytes(p.object,p.shape.value_offset,value,p.shape.value_bytes)
                ||::memcmp(value,p.value,p.shape.value_bytes))return fail(Result::failed,"volume_source_parameter_restore_failed");
            for(size_t j=0;j<p.shape.tail_count;++j){uint8_t tail[16]{};
                if(!bytes(p.object,p.shape.tail[j].offset,tail,p.shape.tail[j].bytes)||::memcmp(tail,p.tail[j],p.shape.tail[j].bytes))
                    return fail(Result::failed,"volume_source_parameter_restore_failed");}}
        error_="none";return Result::ok;
    }
};
} // namespace idoly_mp4_volume_source

// END_MP4_SOURCE_VOLUME_INPUT

// BEGIN_MP4_TARGET_IMAGE_SCOPE
// Finite SolisTargetImageTrack UI state lease. The host owns the exact Root
// Timeline track/mixer/output provenance and source-controller RT role mapping.
namespace idoly_mp4_target_image {
enum class Result:int {ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};
enum class TextureRole:uint8_t {null_value,readonly_asset,source_controller_rt};
struct Rect {float x=0,y=0,width=0,height=0;};
struct Color {float r=1,g=1,b=1,a=1;};
struct Owner {void*director=nullptr,*asset=nullptr,*track=nullptr,*image=nullptr;uint64_t epoch=0,job=0;};
struct Program {void*mixer=nullptr,*cached_image=nullptr;bool initial_enabled=false;};
struct Image {void*object=nullptr,*texture=nullptr,*rect_transform=nullptr;uintptr_t native=0;Rect uv{};bool enabled=false;TextureRole role=TextureRole::null_value;Color color{};};
struct Api {
 bool(*thread)()=nullptr;bool(*current)(void*,uint64_t,uint64_t)=nullptr;bool(*held)(void*)=nullptr;
 bool(*inventory)(void*,Owner*,Program*,size_t,size_t*)=nullptr;
 bool(*owner_current)(void*,const Owner&)=nullptr;
 // Exact native flags + direct m_Texture/uvRect, not get_texture's white fallback.
 bool(*image)(void*,void*,Image*)=nullptr;bool(*image_admitted)(void*,const Owner&,const Image&)=nullptr;
 // Only the authorized fresh Root Rebuild -> same track/source binding may
 // replace a mixer. Historical state is never copied into arbitrary scripts.
 bool(*restored_program)(void*,const Owner&,Program*)=nullptr;
 bool(*set_program_cache)(void*,const Owner&,const Program&actual,const Program&saved)=nullptr;
 // A controller output resize retires the old native RT. Map that exact
 // captured logical role to the restored controller's new current texture.
 bool(*resolve_texture)(void*,const Owner&,const Image&,void**)=nullptr;
 bool(*set_texture)(void*,void*,void*)=nullptr;bool(*set_uv)(void*,void*,Rect)=nullptr;bool(*set_enabled)(void*,void*,bool)=nullptr;bool(*set_color)(void*,void*,Color)=nullptr;
 uint32_t(*retain)(void*)=nullptr;void*(*retained)(uint32_t)=nullptr;void(*release_root)(uint32_t)=nullptr;
};
struct CapturedImage {Owner owner{};Program program{};Image image{};uint64_t receipt=0;bool has_image=false;};
inline uint64_t completed_capture_sequence=0;
class Scope {
 static constexpr size_t tracks_max=64,images_max=64,roots_max=tracks_max*5+images_max*3;
 struct Track {Owner owner{};Program saved{};};struct Root{void*object=nullptr;uint32_t token=0;};
 Api api_{};void*ctx_=nullptr;uint64_t epoch_=0,job_=0;Track tracks_[tracks_max]{};Image images_[images_max]{};Root roots_[roots_max]{};
 uint64_t capture_receipt_=0;size_t track_count_=0,image_count_=0,root_count_=0;bool captured_=false,restored_=false;const char*error_="none";
 Result fail(Result r,const char*s){error_=s;return r;}
 bool keep(void*object){if(!object)return true;for(size_t i=0;i<root_count_;++i)if(roots_[i].object==object)return api_.retained(roots_[i].token)==object;
  if(root_count_==roots_max)return false;
  auto&r=roots_[root_count_++];r.object=object;r.token=api_.retain(object);return r.token&&api_.retained(r.token)==object;}
 bool current()const{if(!captured_||!api_.thread()||!api_.current(ctx_,epoch_,job_))return false;
  for(size_t i=0;i<root_count_;++i)if(!roots_[i].token||api_.retained(roots_[i].token)!=roots_[i].object)return false;
  for(size_t i=0;i<track_count_;++i)if(!api_.owner_current(ctx_,tracks_[i].owner))return false;
  return true;}
 static bool rect_ok(Rect r){return __builtin_isfinite(r.x)&&__builtin_isfinite(r.y)&&__builtin_isfinite(r.width)&&__builtin_isfinite(r.height);}
 static bool color_ok(Color c){return __builtin_isfinite(c.r)&&__builtin_isfinite(c.g)&&__builtin_isfinite(c.b)&&__builtin_isfinite(c.a);}
 static bool same_color(Color a,Color b){return a.r==b.r&&a.g==b.g&&a.b==b.b&&a.a==b.a;}
 static bool same_rect(Rect a,Rect b){return a.x==b.x&&a.y==b.y&&a.width==b.width&&a.height==b.height;}
 bool complete()const{return api_.thread&&api_.current&&api_.held&&api_.inventory&&api_.owner_current&&api_.image&&api_.image_admitted
  &&api_.restored_program&&api_.set_program_cache&&api_.resolve_texture&&api_.set_texture&&api_.set_uv&&api_.set_enabled&&api_.set_color&&api_.retain&&api_.retained&&api_.release_root;}
 const Owner*owner_for(void*image)const{for(size_t i=0;i<track_count_;++i)if(tracks_[i].owner.image==image)return &tracks_[i].owner;return nullptr;}
 bool image_identity(const Image&saved,Image&now)const{return api_.image(ctx_,saved.object,&now)&&now.object==saved.object&&now.native==saved.native
  &&now.rect_transform==saved.rect_transform&&rect_ok(now.uv)&&color_ok(now.color);}
 bool verify()const{
  for(size_t i=0;i<image_count_;++i){Image now{};void*texture=nullptr;const auto*owner=owner_for(images_[i].object);
   if(!owner||!image_identity(images_[i],now)||!api_.resolve_texture(ctx_,*owner,images_[i],&texture)
    ||now.texture!=texture||now.enabled!=images_[i].enabled||!same_rect(now.uv,images_[i].uv)||!same_color(now.color,images_[i].color))return false;}
  for(size_t i=0;i<track_count_;++i){Program p{};const auto&t=tracks_[i];if(!api_.restored_program(ctx_,t.owner,&p)||!p.mixer
   ||p.cached_image!=t.saved.cached_image||p.initial_enabled!=t.saved.initial_enabled)return false;}
  return true;
 }
public:
 const char*error()const{return error_;}bool captured()const{return captured_;}bool restored()const{return restored_;}
 Result capture(Api api,void*ctx,uint64_t epoch,uint64_t job){
  if(captured_||root_count_||!ctx||!epoch||!job)return fail(Result::invalid,"target_image_capture_state");
  api_=api;ctx_=ctx;epoch_=epoch;job_=job;
  if(!complete()||!api_.thread()||!api_.current(ctx,epoch,job)||!api_.held(ctx))return fail(Result::unsupported,"target_image_api_or_phase");
  Owner owners[tracks_max]{};Program programs[tracks_max]{};size_t count=0;
  if(!api_.inventory(ctx,owners,programs,tracks_max,&count)||count>tracks_max)return fail(Result::unsupported,"target_image_inventory");
  for(size_t i=0;i<count;++i){const auto&o=owners[i];const auto&p=programs[i];
   if(o.epoch!=epoch||o.job!=job||!o.director||!o.asset||!o.track||!api_.owner_current(ctx,o)
    ||!p.mixer||(p.cached_image&&p.cached_image!=o.image))return fail(Result::unsupported,"target_image_owner");
   for(size_t j=0;j<i;++j)if(owners[j].director==o.director&&owners[j].track==o.track)return fail(Result::unsupported,"target_image_duplicate_track");
   tracks_[track_count_++]={o,p};
   for(void*object:{o.director,o.asset,o.track,o.image,p.mixer})if(!keep(object))return fail(Result::failed,"target_image_owner_root");
   if(!o.image)continue;
   bool seen=false;for(size_t j=0;j<image_count_;++j)seen|=images_[j].object==o.image;if(seen)continue;
   if(image_count_==images_max)return fail(Result::unsupported,"target_image_budget");
   Image value{};
   if(!api_.image(ctx,o.image,&value)||value.object!=o.image||!value.native||!value.rect_transform||!rect_ok(value.uv)||!color_ok(value.color)
    ||!api_.image_admitted(ctx,o,value)||(value.role==TextureRole::null_value&&value.texture)
    ||(value.role!=TextureRole::null_value&&!value.texture))return fail(Result::unsupported,"target_image_native_or_texture_role");
   if(!keep(value.texture)||!keep(value.rect_transform))return fail(Result::failed,"target_image_value_root");
   images_[image_count_++]=value;
  }
  captured_=true;if(!current())return fail(Result::stale,"target_image_source_changed");
  if(completed_capture_sequence==~uint64_t(0))return fail(Result::unsupported,"target_image_receipt_exhausted");
  capture_receipt_=++completed_capture_sequence;return Result::ok;
 }
 // Read-only exact saved image. A completed capture receipt is separate from
 // captured_, which may remain true after a failed final source recheck.
 bool captured_image(const Owner&expected,CapturedImage*out)const noexcept{try{
  if(out)*out={};
  if(!out||!capture_receipt_||!current()||!api_.held(ctx_)||expected.epoch!=epoch_||expected.job!=job_)return false;
  const Track*track=nullptr;size_t matches=0;
  for(size_t i=0;i<track_count_;++i){const auto&o=tracks_[i].owner;
   if(o.director==expected.director&&o.asset==expected.asset&&o.track==expected.track&&o.image==expected.image
    &&o.epoch==expected.epoch&&o.job==expected.job){track=&tracks_[i];++matches;}}
  if(matches!=1||!track)return false;
  CapturedImage saved{};saved.owner=track->owner;saved.program=track->saved;saved.receipt=capture_receipt_;
  if(track->owner.image){size_t images=0;for(size_t i=0;i<image_count_;++i)if(images_[i].object==track->owner.image){
    Image now{};if(!image_identity(images_[i],now)||!api_.image_admitted(ctx_,track->owner,now))return false;saved.image=images_[i];++images;}
   if(images!=1)return false;
   saved.has_image=true;}
  if(!current()||!api_.held(ctx_)||saved.receipt!=capture_receipt_)return false;
  *out=saved;return true;
 }catch(...){if(out)*out={};return false;}}
 bool capture_current()const noexcept{try{return capture_receipt_&&current()&&api_.held(ctx_);}catch(...){return false;}}
 uint64_t capture_receipt_raw()const noexcept{return captured_?capture_receipt_:0;}
 bool owns_image_raw(void*object)const noexcept {for(size_t i=0;i<image_count_;++i)if(images_[i].object==object)return true;return false;}
 Result restore(){
  if(!captured_)return fail(Result::invalid,"target_image_not_captured");
  if(restored_)return Result::ok; // historical receipt; do not compare after logical detach.
  if(!current())return fail(Result::stale,"target_image_source_changed");
  if(!api_.held(ctx_))return fail(Result::waiting,"target_image_clock_not_held");
  Program fresh[tracks_max]{};void*textures[images_max]{};
  // Whole preflight before any setter. No old mixer identity is written into
  // the fresh source graph; only its finite logical binding/cache is restored.
  for(size_t i=0;i<track_count_;++i)if(!api_.restored_program(ctx_,tracks_[i].owner,&fresh[i])||!fresh[i].mixer
   ||(fresh[i].cached_image&&fresh[i].cached_image!=tracks_[i].owner.image))return fail(Result::stale,"target_image_fresh_program");
  for(size_t i=0;i<image_count_;++i){Image now{};const auto*owner=owner_for(images_[i].object);if(!owner||!image_identity(images_[i],now)
   ||!api_.image_admitted(ctx_,*owner,now)||!api_.resolve_texture(ctx_,*owner,images_[i],&textures[i]))return fail(Result::stale,"target_image_native_changed");}
  for(size_t i=0;i<image_count_;++i){const auto&v=images_[i];
   if(!current()||!api_.set_texture(ctx_,v.object,textures[i])||!current()||!api_.set_uv(ctx_,v.object,v.uv)
    ||!current()||!api_.set_color(ctx_,v.object,v.color)||!current()||!api_.set_enabled(ctx_,v.object,v.enabled)||!current())return fail(Result::stale,"target_image_restore_interrupted");}
  for(size_t i=0;i<track_count_;++i)if(!current()||!api_.set_program_cache(ctx_,tracks_[i].owner,fresh[i],tracks_[i].saved))return fail(Result::stale,"target_image_cache_restore_interrupted");
  if(!current()||!verify())return fail(Result::failed,"target_image_restore_mismatch");
  restored_=true;return Result::ok;
 }
 // Once logical source state is verified and ordinary callbacks resume, only
 // CPU roots/storage may retire. Never re-query old scene/flags/history here.
 Result release(){if(!api_.release_root&&root_count_)return Result::failed;
  for(size_t i=0;i<root_count_;++i){if(roots_[i].token)api_.release_root(roots_[i].token);roots_[i]={};}
  root_count_=track_count_=image_count_=0;capture_receipt_=0;captured_=restored_=false;ctx_=nullptr;epoch_=job_=0;return Result::ok;}
};
} // namespace idoly_mp4_target_image
// END_MP4_TARGET_IMAGE_SCOPE

// BEGIN_MP4_PAUSED_FRAME_SCOPE
// Preserve the selected controller's displayed RT, not an older screenshot.
// Typed original GPU copies and independently retired real queue fences only.
namespace idoly_mp4_paused_frame {
using Result=idoly_mp4_camera_state::Result;
struct Descriptor {int32_t width=0,height=0,samples=0,depth=0,mips=0,format=0,stencil=0,depth_stencil=0,dimension=0,shadow=0,vr=0,flags=0,memoryless=0;};
static_assert(sizeof(Descriptor)==52,"Original RenderTextureDescriptor value ABI");
struct Texture {void*object=nullptr;uintptr_t native=0;Descriptor descriptor{};};
struct Image {void*controller=nullptr,*camera=nullptr,*target_wrapper=nullptr,*captured_wrapper=nullptr;Texture target{};bool capture_idle=false;};
struct Api {
 bool(*thread)()=nullptr;bool(*current)(void*,uint64_t,uint64_t)=nullptr;bool(*held)(void*)=nullptr;
 bool(*image)(void*,Image*)=nullptr;bool(*texture)(void*,void*,Texture*)=nullptr;
 // Writes the output immediately after allocating the managed object, before
 // invoking its original constructor/Create. Partial creation remains owned.
 // Synchronous constructor/Create: OK or terminal failure; never WAIT.
 Result(*allocate)(void*,const Descriptor&,Texture*)=nullptr;
 bool(*copy_supported)(void*,const Texture&,const Texture&)=nullptr;
 // Non-OK begin leaves ticket0. Complete is OK after a real fence enqueue,
 // otherwise terminal quarantine; it never asks the raw copy to run again.
 Result(*copy_begin)(void*,const Texture&,const Texture&,uint64_t*)=nullptr;
 void(*copy_original)(void*,void*,void*)=nullptr;
 Result(*copy_complete)(void*,uint64_t,bool)=nullptr;Result(*copy_poll)(void*,uint64_t)=nullptr;
 bool(*copy_retire)(void*,uint64_t)=nullptr;
 // Exact A0 field-only comparison/write barrier. Never publish/guess a
 // global texture here: the separate global lease owns that baseline.
 bool(*capture_slot)(void*,void*expected,void*replacement)=nullptr;
 // Only a wrapper created by the actual owned CaptureRequest may retire.
 bool(*export_capture_owned)(void*,void*)=nullptr;
 // Independent retained-resource proof covers global/material/UI aliases,
 // including a superseding identical write that preserves the private image.
 bool(*capture_unreferenced)(void*,void*)=nullptr;
 // On source handoff, transfer either the detached ORIGINAL screenshot or
 // this job's observed private capture and its native/GC duty to a real
 // retirement owner. The callback distinguishes actual retained provenance;
 // it must not discover an old controller's current fields after handoff.
 bool(*preserve_detached_capture)(void*,void*)=nullptr;
 // Destroy requires this transaction's actual GPU and alias retirement proof.
 bool(*destroy_capture)(void*,void*)=nullptr;bool(*destroy_texture)(void*,Texture&)=nullptr;
 uint32_t(*retain)(void*)=nullptr;void*(*retained)(uint32_t)=nullptr;void(*release_root)(uint32_t)=nullptr;
};
class Scope {
 struct Root {void*object=nullptr;uint32_t handle=0;};
 Api api_{};void*ctx_=nullptr;uint64_t epoch_=0,job_=0,ticket_=0;Image saved_{};Texture backup_{},restored_target_{};
 Root roots_[10]{};size_t root_count_=0;void*export_capture_=nullptr,*restored_wrapper_=nullptr;
 bool captured_=false,backup_valid_=false,slot_detached_=false,restore_started_=false,restored_=false,abandoned_=false,uncertain_=false,allocation_failed_=false;
 const char*error_="none";
 Result fail(Result r,const char*s){error_=s;return r;}
 bool keep(void*object){if(!object)return true;for(size_t i=0;i<root_count_;++i)if(roots_[i].object==object)return api_.retained(roots_[i].handle)==object;
  if(root_count_==10)return false;
  const uint32_t handle=api_.retain(object);
  if(!handle||api_.retained(handle)!=object){if(handle)api_.release_root(handle);return false;}
  roots_[root_count_++]={object,handle};return true;}
 bool current()const{if(!captured_||abandoned_||!api_.thread()||!api_.current(ctx_,epoch_,job_))return false;
  for(size_t i=0;i<root_count_;++i)if(!roots_[i].handle||api_.retained(roots_[i].handle)!=roots_[i].object)return false;
  return true;}
 bool complete()const{return api_.thread&&api_.current&&api_.held&&api_.image&&api_.texture&&api_.allocate&&api_.copy_supported&&api_.copy_begin
  &&api_.copy_original&&api_.copy_complete&&api_.copy_poll&&api_.copy_retire&&api_.capture_slot&&api_.export_capture_owned&&api_.destroy_capture
  &&api_.capture_unreferenced&&api_.preserve_detached_capture&&api_.destroy_texture&&api_.retain&&api_.retained&&api_.release_root;}
 static bool usable(const Texture&t){const auto&d=t.descriptor;return t.object&&t.native&&d.width>0&&d.height>0&&d.width<=16384&&d.height<=16384
  &&d.samples==1&&d.depth==1&&d.mips==1&&d.format>0&&d.dimension==2&&!d.vr&&!d.memoryless;}
 static bool same_descriptor(const Descriptor&a,const Descriptor&b){return !std::memcmp(&a,&b,sizeof(a));}
 bool source_image(Image&now)const{return current()&&api_.held(ctx_)&&api_.image(ctx_,&now)&&now.controller==saved_.controller
  &&now.camera==saved_.camera&&now.capture_idle;}
 Result poll(){if(!ticket_)return Result::ok;const Result r=api_.copy_poll(ctx_,ticket_);if(r!=Result::ok)return r;
  if(!api_.copy_retire(ctx_,ticket_))return fail(Result::waiting,"paused_frame_copy_retire_wait");
  ticket_=0;return Result::ok;}
 Result dispatch(const Texture&src,const Texture&dst){
  if(ticket_||uncertain_||!usable(src)||!usable(dst)||src.object==dst.object||src.native==dst.native
   ||!same_descriptor(src.descriptor,dst.descriptor)||!api_.copy_supported(ctx_,src,dst))return fail(Result::unsupported,"paused_frame_copy_format");
  const Result start=api_.copy_begin(ctx_,src,dst,&ticket_);
  if(start!=Result::ok){if(ticket_){uncertain_=true;return fail(Result::failed,"paused_frame_reservation_contract");}return start;}
  if(!ticket_)return fail(Result::failed,"paused_frame_copy_receipt_missing");
  try{api_.copy_original(ctx_,src.object,dst.object);}catch(...){uncertain_=true;api_.copy_complete(ctx_,ticket_,false);return fail(Result::failed,"paused_frame_copy_exception");}
  const Result done=api_.copy_complete(ctx_,ticket_,true);if(done!=Result::ok){uncertain_=true;return done;}
  return Result::waiting;
 }
public:
 const char*error()const{return error_;}bool restored()const{return restored_;}bool ready()const{return backup_valid_&&slot_detached_&&!abandoned_;}
 bool released()const{return !captured_&&!root_count_&&!backup_.object&&!ticket_;}
 Result capture(Api api,void*ctx,uint64_t epoch,uint64_t job){
  if(captured_||root_count_||!ctx||!epoch||!job)return fail(Result::invalid,"paused_frame_capture_state");
  api_=api;ctx_=ctx;epoch_=epoch;job_=job;
  if(!complete()||!api_.thread()||!api_.current(ctx,epoch,job)||!api_.held(ctx))return fail(Result::unsupported,"paused_frame_api_or_phase");
  if(!api_.image(ctx,&saved_)||!saved_.controller||!saved_.camera||!saved_.target_wrapper||!saved_.capture_idle||!usable(saved_.target))
   return fail(Result::unsupported,"paused_frame_source_image");
  for(void*object:{saved_.controller,saved_.camera,saved_.target_wrapper,saved_.target.object,saved_.captured_wrapper})
   if(!keep(object))return fail(Result::failed,"paused_frame_source_root");
  captured_=true;
  return current()?Result::ok:fail(Result::stale,"paused_frame_source_changed");
 }
 // Must finish before source geometry can destroy target98 or CaptureRequest
 // can resize/destroy old capturedA0. WAIT performs no duplicate GPU copy.
 Result prepare(){
  if(!current())return fail(Result::stale,"paused_frame_source_changed");
  if(!api_.held(ctx_))return Result::waiting;
  if(uncertain_)return fail(Result::failed,"paused_frame_copy_quarantined");
  if(allocation_failed_)return fail(Result::failed,"paused_frame_backup_allocation");
  if(ready())return Result::ok;
  if(ticket_){const Result r=poll();if(r!=Result::ok)return r;backup_valid_=true;}
  Image now{};if(!source_image(now)||now.target_wrapper!=saved_.target_wrapper||now.target.object!=saved_.target.object
   ||now.target.native!=saved_.target.native||!same_descriptor(now.target.descriptor,saved_.target.descriptor)
   ||now.captured_wrapper!=saved_.captured_wrapper)return fail(Result::stale,"paused_frame_source_texture_changed");
  if(!backup_valid_){
   if(!backup_.object){Result r=Result::failed;try{r=api_.allocate(ctx_,saved_.target.descriptor,&backup_);}catch(...){r=Result::failed;}
    if(backup_.object&&!keep(backup_.object))return fail(Result::failed,"paused_frame_backup_root");
    if(r!=Result::ok){allocation_failed_=true;return fail(Result::failed,"paused_frame_backup_allocation");}}
   Texture actual{};if(!api_.texture(ctx_,backup_.object,&actual)||!usable(actual)||actual.native!=backup_.native
    ||!same_descriptor(actual.descriptor,saved_.target.descriptor))return fail(Result::failed,"paused_frame_backup_shape");
   return dispatch(saved_.target,backup_);
  }
  if(!current()||!api_.capture_slot(ctx_,saved_.captured_wrapper,nullptr))return fail(Result::stale,"paused_frame_capture_detach");
  slot_detached_=true;return Result::ok;
 }
 // Called immediately by the real capture-production owner, including a
 // partially completed original request. Never defer discovery until restore:
 // a source handoff may happen first. This receipt is not a capture-pass or
 // GPU completion receipt and cannot authorize destruction on its own.
 Result observe_export_capture(void*wrapper){
  if(!wrapper||wrapper==saved_.captured_wrapper)return fail(Result::invalid,"paused_frame_private_capture_identity");
  if(!current()||!api_.held(ctx_)||(!slot_detached_&&!restore_started_))return fail(Result::stale,"paused_frame_private_capture_phase");
  if(export_capture_&&export_capture_!=wrapper)return fail(Result::stale,"paused_frame_private_capture_replaced");
  if(!api_.export_capture_owned(ctx_,wrapper))return fail(Result::stale,"paused_frame_private_capture_provenance");
  export_capture_=wrapper; // Retain cleanup duty even if this extra root fails.
  if(!keep(wrapper))return fail(Result::failed,"paused_frame_private_capture_root");
  return Result::ok;
 }
 // Called after the original saved geometry has been recreated, while held.
 Result restore(){
  if(restored_)return Result::ok;
  if(!current())return fail(Result::stale,"paused_frame_source_changed");
  if(!api_.held(ctx_))return Result::waiting;
  if(ticket_){const Result r=poll();if(r!=Result::ok)return r;if(restore_started_)restored_=true;else backup_valid_=true;}
  if(restored_){Image final{};if(!source_image(final)||final.target_wrapper!=restored_wrapper_||final.target.object!=restored_target_.object||final.target.native!=restored_target_.native
   ||!same_descriptor(final.target.descriptor,restored_target_.descriptor)||final.captured_wrapper!=saved_.captured_wrapper){restored_=false;return fail(Result::stale,"paused_frame_restore_changed");}
   return Result::ok;}
  if(!slot_detached_&&!restore_started_){
   Image unchanged{};if(!source_image(unchanged)||unchanged.target_wrapper!=saved_.target_wrapper
    ||unchanged.target.object!=saved_.target.object||unchanged.target.native!=saved_.target.native
    ||!same_descriptor(unchanged.target.descriptor,saved_.target.descriptor)||unchanged.captured_wrapper!=saved_.captured_wrapper)
    return fail(Result::stale,"paused_frame_unmodified_source_changed");
   restored_=true;return Result::ok; // no geometry mutation was admitted.
  }
  Image now{};if(!source_image(now)||!usable(now.target)||!same_descriptor(now.target.descriptor,saved_.target.descriptor))
   return fail(Result::stale,"paused_frame_restored_geometry");
  if(!restore_started_){
   if(now.captured_wrapper&&now.captured_wrapper!=saved_.captured_wrapper&&!api_.export_capture_owned(ctx_,now.captured_wrapper))
    return fail(Result::stale,"paused_frame_foreign_capture");
   if(now.captured_wrapper&&now.captured_wrapper!=saved_.captured_wrapper){
    const Result observed=observe_export_capture(now.captured_wrapper);if(observed!=Result::ok)return observed;
   }
   if(!keep(now.target.object))return fail(Result::failed,"paused_frame_restore_root");
   restored_target_=now.target;restored_wrapper_=now.target_wrapper;
   // Clear only the captured slot actually owned by this transaction. Keep
   // its native image alive until the real copy fence retires.
   if(!api_.capture_slot(ctx_,now.captured_wrapper,saved_.captured_wrapper))return fail(Result::stale,"paused_frame_capture_restore");
   slot_detached_=false;restore_started_=true;
   return dispatch(backup_,restored_target_);
  }
  if(now.target_wrapper!=restored_wrapper_||now.target.object!=restored_target_.object||now.target.native!=restored_target_.native||now.captured_wrapper!=saved_.captured_wrapper)
   return fail(Result::stale,"paused_frame_restore_changed");
  return dispatch(backup_,restored_target_);
 }
 // Independent source loss drops no old scene flags/fields. Owned GPU objects
 // and roots still retire only through their actual completion receipt.
 void abandon()noexcept{abandoned_=true;}
 // Final held checkpoint is distinct from the historical restore receipt:
 // later module restoration must not replace the image we just restored.
 Result verify_held(){
  if(!restored_)return fail(Result::invalid,"paused_frame_not_restored");
  if(!current())return fail(Result::stale,"paused_frame_source_changed");
  if(!api_.held(ctx_))return Result::waiting;
  Image now{};if(!source_image(now))return fail(Result::stale,"paused_frame_checkpoint_source");
  const auto&expected=restore_started_?restored_target_:saved_.target;
  void*wrapper=restore_started_?restored_wrapper_:saved_.target_wrapper;
  if(ticket_||now.target_wrapper!=wrapper||now.target.object!=expected.object||now.target.native!=expected.native
   ||!same_descriptor(now.target.descriptor,expected.descriptor)||now.captured_wrapper!=saved_.captured_wrapper)
   return fail(Result::stale,"paused_frame_checkpoint_image");
  return Result::ok;
 }
 Result release(){
  if(!captured_&&!root_count_&&!backup_.object&&!ticket_)return Result::ok;
  if(!api_.thread())return Result::invalid;
  const Result r=poll();if(r!=Result::ok)return r;
  if(uncertain_)return fail(Result::waiting,"paused_frame_copy_quarantined");
  if(!abandoned_&&(slot_detached_||(restore_started_&&!restored_)))return fail(Result::invalid,"paused_frame_restore_owed");
  if(abandoned_&&slot_detached_){
   if(saved_.captured_wrapper&&!api_.preserve_detached_capture(ctx_,saved_.captured_wrapper))return Result::waiting;
   slot_detached_=false;
  }
  if(export_capture_){
   if(!api_.capture_unreferenced(ctx_,export_capture_)){
    if(!abandoned_||!api_.preserve_detached_capture(ctx_,export_capture_))return Result::waiting;
   }else if(!api_.destroy_capture(ctx_,export_capture_))return Result::waiting;
   export_capture_=nullptr;
  }
  if(backup_.object&&!api_.destroy_texture(ctx_,backup_))return Result::waiting;
  for(size_t i=0;i<root_count_;++i){if(roots_[i].handle)api_.release_root(roots_[i].handle);roots_[i]={};}
  *this=Scope{};return Result::ok;
 }
};
} // namespace idoly_mp4_paused_frame
// END_MP4_PAUSED_FRAME_SCOPE

// BEGIN_MP4_CAPTURE_GLOBAL_NATIVE
// Native ShaderPropertySheet publication observer, not a managed Shader hook.
// Bind only after the source-program admission has closed EVERY write route to
// the exact global sheet. The pinned leaf alone is deliberately insufficient:
// copying one texture property / the whole sheet and clearing a retired texture
// write records directly. They must use mutation() below or reject admission.
#ifdef IDOLY_DARWIN_BRIDGE
extern "C" int pthread_mutex_trylock(pthread_mutex_t*);
#endif
namespace idoly_mp4_capture_global_native {
// Public pthread ABI also supported by the SDK-free Darwin builder. Reentry is
// limited to this same CPU publication thread (e.g. an ordinary native log callback).
class Gate {
    pthread_mutex_t mutex_=PTHREAD_MUTEX_INITIALIZER;
    std::atomic<uintptr_t> owner_{0};uint32_t depth_=0;
    inline static thread_local char identity_=0;
    static uintptr_t token(){return reinterpret_cast<uintptr_t>(&identity_);}
public:
    void lock(){const uintptr_t id=token();if(owner_.load(std::memory_order_acquire)==id){++depth_;return;}
        pthread_mutex_lock(&mutex_);depth_=1;owner_.store(id,std::memory_order_release);}
    bool try_lock(){const uintptr_t id=token();if(owner_.load(std::memory_order_acquire)==id){++depth_;return true;}
        if(pthread_mutex_trylock(&mutex_))return false;
        depth_=1;owner_.store(id,std::memory_order_release);return true;}
    void unlock(){if(--depth_)return;owner_.store(0,std::memory_order_release);pthread_mutex_unlock(&mutex_);}
};
class Lock {
    Gate*gate_=nullptr;
public:
    explicit Lock(Gate&gate,bool try_only=false){if(try_only){if(gate.try_lock())gate_=&gate;}else{gate.lock();gate_=&gate;}}
    ~Lock(){if(gate_)gate_->unlock();}bool owns_lock()const{return gate_!=nullptr;}
    Lock(const Lock&)=delete;Lock&operator=(const Lock&)=delete;
};
struct Key { int32_t property; int32_t auxiliary[3]; };
static_assert(sizeof(Key)==16,"original native property key ABI");

class Observer {
    // This gate is NEVER held across the Texture virtual helpers in the core
    // setter, camera rendering, a fence, or a GPU readback. It protects only the
    // final native CPU publication / bounded sheet mutation / stable getter.
    mutable Gate gate_;
    uint32_t busy_=0;
    std::atomic<uint64_t> serial_{1};
    std::atomic<bool> lost_{true};
    void* sheet_=nullptr;
    int32_t property_=0;
    struct Origin {
        Observer* observer=nullptr; Origin* parent=nullptr;
        bool matching=false; bool owned=false; uint64_t expected=0;
        uint32_t publications=0; uint64_t after=0; bool rejected=false;
    };
    inline static thread_local Origin* origin_=nullptr;
    void finish_write() noexcept {
        const uint64_t before=serial_.load(std::memory_order_acquire);
        if(before==~uint64_t(0))lost_.store(true,std::memory_order_release);
        else serial_.store(before+1,std::memory_order_release);
    }
    struct Busy {
        Observer& observer;
        explicit Busy(Observer& x):observer(x){__atomic_fetch_add(&observer.busy_,1,__ATOMIC_ACQ_REL);}
        ~Busy(){__atomic_fetch_sub(&observer.busy_,1,__ATOMIC_ACQ_REL);}
    };
public:
    Observer()=default; Observer(const Observer&)=delete; Observer&operator=(const Observer&)=delete;
    // source_closed is the actual finite source-program result, not a default
    // assertion that Unity APIs are main-thread-only. Caller pins/install receipts
    // include both native texture cores AND direct-copy/clear/retirement routes.
    bool bind(void* sheet,int32_t property,bool source_closed) {
        Lock lock(gate_);
        if(__atomic_load_n(&busy_,__ATOMIC_ACQUIRE)||!sheet||!source_closed){invalidate();return false;}
        sheet_=sheet; property_=property;serial_.store(1,std::memory_order_release);
        lost_.store(false,std::memory_order_release);return true;
    }
    void invalidate() noexcept {lost_.store(true,std::memory_order_release);}
    bool matches(void* sheet,const Key* key)const noexcept {
        return sheet==sheet_&&key&&key->property==property_;
    }
    uint64_t serial()const noexcept {
        if(lost_.load(std::memory_order_acquire)||__atomic_load_n(&busy_,__ATOMIC_ACQUIRE))return 0;
        const uint64_t result=serial_.load(std::memory_order_acquire);
        return lost_.load(std::memory_order_acquire)||__atomic_load_n(&busy_,__ATOMIC_ACQUIRE)?0:result;
    }
    // Surround BOTH original core bodies. No lock is held while they resolve
    // Texture data/dimensions. Native CB execution enters the same cores and is
    // observed even when its value equals the current value.
    template<class Original> void core(void* sheet,const Key* key,Original&& original) {
        const bool matching=matches(sheet,key);
        const bool sheet_matching=sheet==sheet_;
        Origin scope{};scope.observer=this;scope.parent=origin_;scope.matching=matching;
        // An owned request is transferred only into its first actual core on
        // this thread. Nested ordinary calls never inherit owned authorization.
        if(matching&&origin_&&origin_->observer==this&&origin_->owned&&!origin_->matching){
            scope.owned=true;scope.expected=origin_->expected;
        }
        if(sheet_matching)__atomic_fetch_add(&busy_,1,__ATOMIC_ACQ_REL);
        origin_=&scope;
        try {static_cast<Original&&>(original)();}
        catch(...){origin_=scope.parent;if(sheet_matching)__atomic_fetch_sub(&busy_,1,__ATOMIC_ACQ_REL);invalidate();throw;}
        origin_=scope.parent;
        if(scope.owned&&scope.parent){scope.parent->publications+=scope.publications;
            scope.parent->after=scope.after;scope.parent->rejected|=scope.rejected;}
        if(sheet_matching)__atomic_fetch_sub(&busy_,1,__ATOMIC_ACQ_REL);
    }
    // Hook the actual record publication leaf. `original` receives every exact
    // original argument. Only OUR failed expected-serial restore is suppressed;
    // every ordinary call is forwarded exactly once, including unknown keys.
    template<class Original> bool publish(const Key* key,Original&& original) {
        Origin* scope=origin_;
        if(!key||key->property!=property_||!scope||scope->observer!=this||!scope->matching){
            // A matching property with no sheet provenance may be an unobserved
            // writer. Preserve its normal behavior, but end our restoration duty.
            if(key&&key->property==property_&&(!scope||scope->observer!=this))invalidate();
            static_cast<Original&&>(original)();return true;
        }
        Lock lock(gate_);
        if(scope->owned&&(lost_.load(std::memory_order_acquire)||scope->publications||
                serial_.load(std::memory_order_acquire)!=scope->expected)){
            scope->rejected=true;return false;
        }
        try {static_cast<Original&&>(original)();}
        catch(...){finish_write();invalidate();throw;}
        finish_write();++scope->publications;
        scope->after=serial_.load(std::memory_order_acquire);return true;
    }
    // A source-pinned CPU-only direct copy/clear/retirement route. This guard
    // excludes the stable getter and serializes it with publication. Conservatively
    // count the route once even if a copy was identical or cleared no record.
    template<class Original> void mutation(void* destination,Original&& original) {
        if(destination!=sheet_){static_cast<Original&&>(original)();return;}
        Busy busy(*this);Lock lock(gate_);
        try {static_cast<Original&&>(original)();}
        catch(...){finish_write();invalidate();throw;}
        finish_write();
    }
    // GetIndex/record-storage growth may move the containing allocation while
    // leaving this binding unchanged. Serialize that CPU-only layout work with
    // reads/publications, without inventing an extra texture publication serial.
    template<class Original> void layout(void* sheet,Original&& original) {
        if(sheet!=sheet_){static_cast<Original&&>(original)();return;}
        Busy busy(*this);Lock lock(gate_);
        try {static_cast<Original&&>(original)();}
        catch(...){invalidate();throw;}
    }
    // End the lease under the getter gate, then release it BEFORE native
    // destruction (which may release textures or wait for render work).
    template<class Original> void retire(Original&& original) {
        {Lock lock(gate_);invalidate();}
        static_cast<Original&&>(original)();
    }
    template<class Getter> bool read(uint64_t expected,Getter&& getter)const {
        if(!expected||serial()!=expected)return false;
        Lock lock(gate_,true);
        if(!lock.owns_lock()||serial()!=expected)return false;
        if(!static_cast<Getter&&>(getter)())return false;
        return serial()==expected;
    }
    // The exact native static setter is called outside the publication gate.
    // Expected-serial comparison happens INSIDE publish(), directly before the
    // actual CPU store, so an intervening ordinary write cannot be overwritten.
    template<class Setter> bool set_original(uint64_t expected,uint64_t* after,Setter&& setter) {
        if(after)*after=0;
        if(!after||!expected||serial()!=expected||origin_)return false;
        Origin request{};request.observer=this;request.owned=true;request.expected=expected;
        origin_=&request;
        try {static_cast<Setter&&>(setter)();}
        catch(...){origin_=nullptr;invalidate();throw;}
        origin_=nullptr;
        if(request.rejected||request.publications!=1||expected==~uint64_t(0)||
                request.after!=expected+1||serial()!=request.after)return false;
        *after=request.after;return true;
    }
};
// Exact ABI adapters for the source-pinned native origins below. Bridge hooks
// provide installed trampolines, never the detoured entrypoint itself. These
// adapters keep ordinary arguments/return values and call count unchanged.
struct Calls {
    using Core=void(*)(void*,uint32_t,const Key*,void*,uint32_t);
    using RawCore=void(*)(void*,const Key*,uint32_t,void*,uint32_t);
    using Publish=void(*)(void*,uint32_t,uint32_t,uint32_t,uint32_t,const Key*);
    using PropertyCopy=void(*)(void*,const Key*,const void*);
    using SheetCopy=void(*)(void*,const void*);
    using RetiredTexture=void(*)(void*,uint32_t);
    using GetIndex=int32_t(*)(void*,const Key*,uint32_t);
    Core core=nullptr;RawCore raw_core=nullptr;Publish publish=nullptr;
    PropertyCopy property_copy=nullptr;SheetCopy sheet_copy=nullptr;
    RetiredTexture retired_texture=nullptr;GetIndex get_index=nullptr;
    void(*global_destroy)()=nullptr;
    bool complete()const{return core&&raw_core&&publish&&property_copy&&sheet_copy&&retired_texture&&get_index&&global_destroy;}
};
class NativeHost {
    Observer observer_;Calls calls_{};
public:
    Observer& observer(){return observer_;}
    bool bind(void* sheet,int32_t property,const Calls& calls,bool actual_source_closed){
        if(!calls.complete()){observer_.invalidate();return false;}
        calls_=calls;return observer_.bind(sheet,property,actual_source_closed);
    }
    void core(void* sheet,uint32_t index,const Key* key,void* texture,uint32_t subelement){
        observer_.core(sheet,key,[&]{calls_.core(sheet,index,key,texture,subelement);});}
    void raw_core(void* sheet,const Key* key,uint32_t index,void* texture,uint32_t mip){
        observer_.core(sheet,key,[&]{calls_.raw_core(sheet,key,index,texture,mip);});}
    void publish(void* record,uint32_t id,uint32_t dimension,uint32_t subelement,uint32_t flags,const Key* key){
        observer_.publish(key,[&]{calls_.publish(record,id,dimension,subelement,flags,key);});}
    void property_copy(void* target,const Key* key,const void* source){
        observer_.mutation(target,[&]{calls_.property_copy(target,key,source);});}
    void sheet_copy(void* target,const void* source){
        observer_.mutation(target,[&]{calls_.sheet_copy(target,source);});}
    void retired_texture(void* sheet,uint32_t id){
        observer_.mutation(sheet,[&]{calls_.retired_texture(sheet,id);});}
    int32_t get_index(void* sheet,const Key* key,uint32_t kind){int32_t result=-1;
        observer_.layout(sheet,[&]{result=calls_.get_index(sheet,key,kind);});return result;}
    void global_destroy(){observer_.retire([&]{calls_.global_destroy();});}
};
} // namespace idoly_mp4_capture_global_native
// END_MP4_CAPTURE_GLOBAL_NATIVE

// BEGIN_MP4_CAPTURE_GLOBAL_NATIVE_PROFILE
namespace idoly_mp4_capture_global_native {
struct Binding {uintptr_t rva;uint8_t prefix[16];};
struct Profile {uintptr_t global_sheet_cell;bool indirect_cell;Binding static_set,static_get,core,raw_core,publish,property_copy,sheet_copy,retired_texture,global_destroy,sheet_get,get_index;};
inline constexpr Profile android_profile={0x1459088,true,
 {0x5e5790,{0xff,0x83,0x00,0xd1,0xfe,0x0b,0x00,0xf9,0xa8,0x73,0x00,0x90,0x08,0x45,0x40,0xf9}}, // static_set
 {0x5e59b4,{0xa8,0x73,0x00,0x90,0x08,0x45,0x40,0xf9,0xe1,0x03,0x00,0x2a,0x08,0x01,0x40,0xf9}}, // static_get
 {0x685668,{0xea,0x0f,0x1a,0xfc,0xe9,0xa3,0x00,0x6d,0xfe,0x0f,0x00,0xf9,0xfa,0x67,0x02,0xa9}}, // core
 {0x685890,{0xea,0x0f,0x1a,0xfc,0xe9,0xa3,0x00,0x6d,0xfe,0x0f,0x00,0xf9,0xfa,0x67,0x02,0xa9}}, // raw_core
 {0x5f13b8,{0xff,0x83,0x03,0xd1,0xfe,0x67,0x0a,0xa9,0xf8,0x5f,0x0b,0xa9,0xf6,0x57,0x0c,0xa9}}, // publish
 {0x684e08,{0xff,0x03,0x01,0xd1,0xfe,0x0b,0x00,0xf9,0xf6,0x57,0x02,0xa9,0xf4,0x4f,0x03,0xa9}}, // property_copy
 {0x67906c,{0xfe,0x5f,0xbd,0xa9,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0x35,0x10,0x40,0xf9}}, // sheet_copy
 {0x6868b0,{0x08,0x24,0x49,0xa9,0x29,0x01,0x08,0xcb,0x3f,0x05,0x00,0x71,0x8b,0x02,0x00,0x54}}, // retired_texture
 {0x684a88,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xd4,0x72,0x00,0xf0,0x93,0xfe,0x45,0xf9}}, // global_destroy
 {0x686bfc,{0xfe,0x4f,0xbf,0xa9,0xe1,0x03,0x01,0x2a,0x82,0x00,0x80,0x52,0xf3,0x03,0x00,0xaa}}, // sheet_get
 {0x6854e8,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xf3,0x03,0x01,0xaa,0x21,0x00,0x40,0xb9}}, // get_index
};
inline constexpr Profile ios_profile={0xa93c518,false,
 {0xc6ee5c,{0xff,0x83,0x00,0xd1,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xe2,0x03,0x01,0xaa}}, // static_set
 {0xc6f0b8,{0xe1,0x03,0x00,0xaa,0x68,0xe6,0x04,0xb0,0x08,0x61,0x14,0x91,0x00,0x01,0x40,0xf9}}, // static_get
 {0xd108cc,{0xeb,0x2b,0xb9,0x6d,0xe9,0x23,0x01,0x6d,0xfa,0x67,0x02,0xa9,0xf8,0x5f,0x03,0xa9}}, // core
 {0xd10afc,{0xeb,0x2b,0xb9,0x6d,0xe9,0x23,0x01,0x6d,0xfa,0x67,0x02,0xa9,0xf8,0x5f,0x03,0xa9}}, // raw_core
 {0xc778ac,{0xff,0x03,0x04,0xd1,0xf8,0x5f,0x0c,0xa9,0xf6,0x57,0x0d,0xa9,0xf4,0x4f,0x0e,0xa9}}, // publish
 {0xd10138,{0xff,0x03,0x01,0xd1,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xfd,0x7b,0x03,0xa9}}, // property_copy
 {0xd04074,{0xf8,0x5f,0xbc,0xa9,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xfd,0x7b,0x03,0xa9}}, // sheet_copy
 {0xd11b7c,{0x08,0x24,0x49,0xa9,0x29,0x01,0x08,0xcb,0x3f,0x05,0x00,0x71,0x8b,0x02,0x00,0x54}}, // retired_texture
 {0xd0feb0,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x74,0xe1,0x04,0xb0}}, // global_destroy
 {0xd11dc0,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}}, // sheet_get
 {0xd1072c,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // get_index
};
} // namespace idoly_mp4_capture_global_native
// END_MP4_CAPTURE_GLOBAL_NATIVE_PROFILE

// BEGIN_MP4_CAPTURE_PUBLICATION_GUARD
// The owned capture pass consumes A0.identifier directly and the exporter reads
// A0.texture directly. Preserve the paused display's shader binding by omitting
// ONLY that owned request's exact UpdateCapturedTexture publication, before the
// native Shader icall mutates a sheet. Ordinary shader writes remain unchanged.
namespace idoly_mp4_capture_publication {
struct Api {
    bool(*thread)()=nullptr;
    // Claims a real begin-issued operation ONCE. This is historical provenance,
    // not a new live-current grant inferred from non-null enter arguments.
    bool(*issued)(void*,void*,void*,uint64_t,uint64_t,uint64_t)=nullptr;
    bool(*publication_origin)(void*,void*,uint64_t)=nullptr;
    bool(*current)(void*,uint64_t,uint64_t)=nullptr;
    bool(*owned_request)(void*,void* camera,void* controller,uint64_t request)=nullptr;
    bool(*current_capture)(void*,void* controller,void** wrapper,void** texture)=nullptr;
    bool(*private_capture)(void*,void* controller,void* wrapper,void* texture)=nullptr;
    // Actual selected renderer/capture-pass consumer closure, not a default true.
    bool(*source_program)(void*,uint64_t,uint64_t)=nullptr;
};
struct Receipt {
    uint64_t epoch=0,job=0,request=0;void*controller=nullptr;void*wrapper=nullptr;void*texture=nullptr;
    uint32_t suppressed=0;bool valid=false,issued=false;
};
class Request {
    Api api_{};void*ctx_=nullptr;void*camera_=nullptr;void*controller_=nullptr;
    uint64_t epoch_=0,job_=0,request_=0;int32_t property_=0;uintptr_t origin_=0;
    Request*parent_=nullptr;void*wrapper_=nullptr;void*texture_=nullptr;
    uint32_t suppressed_=0;bool active_=false,authorized_=false,valid_=false,historical_=false;
    inline static thread_local Request*current_=nullptr;
    bool current()const noexcept{try{return authorized_&&valid_&&api_.thread()&&api_.current(ctx_,epoch_,job_)
        &&api_.owned_request(ctx_,camera_,controller_,request_)&&api_.source_program(ctx_,epoch_,job_);}catch(...){return false;}}
public:
    Request()=default;Request(const Request&)=delete;Request&operator=(const Request&)=delete;
    ~Request(){if(active_)finish();}
    struct Abort {};
    static bool stack_unwound()noexcept{return current_==nullptr;}
    static bool historical_origin(void*controller,uint64_t*serial=nullptr)noexcept{
        if(serial)*serial=0;
        const auto*s=current_;
        if(!s||!s->active_||!s->historical_||controller!=s->controller_)return false;
        if(serial)*serial=s->request_;
        return true;
    }
    bool must_abort()const noexcept{return historical_&&!current();}
    static bool valid_origin(void*controller,uint64_t serial)noexcept{
        const auto*s=current_;return s&&s->active_&&s->historical_&&s->valid_&&s->authorized_
            &&s->controller_==controller&&s->request_==serial;
    }
    // Called for EVERY actual typed CaptureRequest invocation. An ordinary or
    // nested unowned request still masks its parent, then forwards all writes.
    bool enter(Api api,void*ctx,void*camera,void*controller,uint64_t epoch,uint64_t job,
            uint64_t request,int32_t property,uintptr_t pinned_original_return){
        if(active_)return false;
        wrapper_=nullptr;texture_=nullptr;suppressed_=0;historical_=false;
        api_=api;ctx_=ctx;camera_=camera;controller_=controller;epoch_=epoch;job_=job;request_=request;
        property_=property;origin_=pinned_original_return;parent_=current_;current_=this;active_=true;
        authorized_=api.thread&&api.issued&&api.publication_origin&&api.current&&api.owned_request&&api.current_capture&&api.private_capture&&api.source_program
            &&ctx&&camera&&controller&&epoch&&job&&request&&origin_;
        for(auto*p=parent_;p;p=p->parent_)if(p->active_&&p->historical_&&p->controller_==controller
            &&p->epoch_==epoch&&p->job_==job&&p->request_==request)authorized_=false;
        if(authorized_)try{historical_=api.thread()&&api.issued(ctx,camera,controller,epoch,job,request);}catch(...){historical_=false;}
        authorized_=authorized_&&historical_;
        valid_=authorized_;
        if(authorized_&&!current())valid_=false;
        return valid_;
    }
    // Called at native Shader.SetGlobalTextureImpl entry with its actual x30.
    // The source-pinned managed wrappers tail-dispatch that icall, preserving
    // UpdateCapturedTexture's return site on both platforms. No return-site guess
    // or current MV UI state grants authority to suppress a call.
    static bool suppress(int32_t property,void*managed_texture,uintptr_t actual_original_return){
        Request*scope=current_;
        if(!scope||!scope->active_||!scope->historical_||property!=scope->property_||actual_original_return!=scope->origin_)return false;
        try{if(!scope->api_.publication_origin(scope->ctx_,scope->controller_,scope->request_))return false;}catch(...){return false;}
        // This exact publication belongs to the already-issued export even
        // after live ownership withdraws. Omit it, but grant no frame/resource
        // ownership. Forwarding here would overwrite the protected baseline.
        if(!scope->current()||scope->suppressed_){scope->valid_=false;if(scope->suppressed_!=~uint32_t(0))++scope->suppressed_;return true;}
        void*wrapper=nullptr;void*texture=nullptr;
        try{if(!scope->api_.current_capture(scope->ctx_,scope->controller_,&wrapper,&texture)
                ||!wrapper||!texture||managed_texture!=texture
                ||!scope->api_.private_capture(scope->ctx_,scope->controller_,wrapper,texture)
                ||!scope->current()){
            scope->valid_=false;++scope->suppressed_;return true;
        }}catch(...){scope->valid_=false;++scope->suppressed_;return true;}
        scope->wrapper_=wrapper;scope->texture_=texture;++scope->suppressed_;return true;
    }
    Receipt finish(){
        Receipt receipt{};
        if(!active_||current_!=this)return receipt;
        receipt={epoch_,job_,request_,controller_,wrapper_,texture_,suppressed_,current(),historical_};
        current_=parent_;active_=false;return receipt;
    }
};
} // namespace idoly_mp4_capture_publication
// END_MP4_CAPTURE_PUBLICATION_GUARD

// BEGIN_MP4_CAPTURE_PUBLICATION_PROFILE
namespace idoly_mp4_capture_publication {
using Binding=idoly_mp4_capture_global_native::Binding;
struct Profile {Binding native_entry;uintptr_t original_return,icall_slot;Binding update,wrapper,shader_string,wrapper_ctor,texture_ctor,descriptor_dynamic_scale;uintptr_t update_return,wrapper_return,texture_return;};
inline constexpr Profile android_profile={{0x45b670,{0xff,0x3,0x1,0xd1,0xfe,0x57,0x2,0xa9,0xf4,0x4f,0x3,0xa9,0xf5,0x7f,0x0,0xd0}},0x923d4e4,0xa077c20,{0x923d228,{0xff,0x3,0x6,0xd1,0xfd,0x7b,0x15,0xa9,0xf6,0x57,0x16,0xa9,0xf4,0x4f,0x17,0xa9}},{0x9236624,{0xfe,0x4f,0xbf,0xa9,0xf3,0x3,0x0,0xaa,0x0,0x20,0x40,0xf9,0xe1,0x3,0x1f,0xaa}},{0x8f526c4,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x1,0xa9,0x35,0x89,0x0,0xb0,0xa8,0xea,0x45,0xf9}},{0x92364fc,{0xff,0x83,0x2,0xd1,0xfe,0x5f,0x7,0xa9,0xf6,0x57,0x8,0xa9,0xf4,0x4f,0x9,0xa9}},{0x8f69e7c,{0xff,0xc3,0x2,0xd1,0xfe,0x43,0x0,0xf9,0xf6,0x57,0x9,0xa9,0xf4,0x4f,0xa,0xa9}},{0x8f6b458,{0x8,0x2c,0x40,0xb9,0x3f,0x0,0x0,0x72,0x9,0x80,0x80,0x52,0x29,0x11,0x9f,0x1a}},0x923d50c,0x923d380,0x9236580};
inline constexpr Profile ios_profile={{0xb04424,{0xff,0x3,0x1,0xd1,0xf4,0x4f,0x2,0xa9,0xfd,0x7b,0x3,0xa9,0xfd,0xc3,0x0,0x91}},0x7bcb81c,0xa91b680,{0x7bcb2f8,{0xff,0x3,0x4,0xd1,0xf8,0x5f,0xc,0xa9,0xf6,0x57,0xd,0xa9,0xf4,0x4f,0xe,0xa9}},{0,{}},{0x7811830,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}},{0x7bc3348,{0xff,0x3,0x2,0xd1,0xf8,0x5f,0x4,0xa9,0xf6,0x57,0x5,0xa9,0xf4,0x4f,0x6,0xa9}},{0x7830f20,{0xff,0xc3,0x1,0xd1,0xf6,0x57,0x4,0xa9,0xf4,0x4f,0x5,0xa9,0xfd,0x7b,0x6,0xa9}},{0x7832eb0,{0x8,0x2c,0x40,0xb9,0x8,0x79,0x15,0x12,0x3f,0x0,0x0,0x71,0x9,0x80,0x80,0x52}},0x7bcb850,0x7bcb6b4,0x7bc33d4};
} // namespace idoly_mp4_capture_publication
// END_MP4_CAPTURE_PUBLICATION_PROFILE

// BEGIN_MP4_CAPTURE_PRODUCTION_BANK
namespace idoly_mp4_capture_production {
struct Descriptor {int32_t fields[13]{};};
static_assert(sizeof(Descriptor)==52,"original indirect RenderTextureDescriptor ABI");
struct Api {
 bool(*thread)()=nullptr;bool(*current)(void*,uint64_t,uint64_t)=nullptr;
 bool(*assignment_current)(void*,uint64_t,uint64_t)=nullptr;
 bool(*owned_request)(void*,void*,uint64_t)=nullptr;
 bool(*owned_origin)(void*,void*,uint64_t)=nullptr;
 bool(*descriptor)(void*,const Descriptor&)=nullptr;bool(*capture_name)(void*,void*)=nullptr;
 bool(*current_capture)(void*,void*,void**,void**)=nullptr;
 bool(*wrapper_texture)(void*,void**)=nullptr;bool(*texture_native)(void*,uintptr_t*)=nullptr;
 uint32_t(*retain)(void*)=nullptr;void*(*retained)(uint32_t)=nullptr;void(*release)(uint32_t)=nullptr;
};
struct Resource {
 uint64_t epoch=0,job=0,request=0;void*wrapper=nullptr;void*texture=nullptr;
 uint32_t wrapper_root=0,texture_root=0;uintptr_t native=0;Descriptor descriptor{};
 bool wrapper_returned=false,texture_returned=false,native_known=false,assigned=false;
};
// A finite record for each actual private allocation, independent of a later
// CaptureRequest/end success. A partial RT ctor is rooted BEFORE its body and
// before the wrapper's texture field is assigned. No former controller is read
// during historical resource transfer after source handoff.
class Bank {
 static constexpr uint32_t max_resources=8;
 struct Row {Resource value{};bool transferred=false;};
 enum class Kind {update,wrapper,texture};
 struct Cursor {Bank*bank=nullptr;Cursor*parent=nullptr;Kind kind=Kind::update;
  void*controller=nullptr;uint64_t request=0;uint32_t row=max_resources;bool authorized=false,origin=false;};
 inline static thread_local Cursor*cursor_=nullptr;
 Api api_{};void*ctx_=nullptr,*controller_=nullptr;uint64_t epoch_=0,job_=0;
 uintptr_t update_return_=0,wrapper_return_=0,texture_return_=0;Row rows_[max_resources]{};uint32_t count_=0;
 bool configured_=false,invalid_=false;
 bool roots(const Resource&r)const{return r.wrapper_root&&api_.retained(r.wrapper_root)==r.wrapper
  &&(!r.texture||(r.texture_root&&api_.retained(r.texture_root)==r.texture));}
 bool current(uint64_t request)const noexcept{try{return configured_&&!invalid_&&api_.thread()
  &&api_.current(ctx_,epoch_,job_)&&api_.owned_request(ctx_,controller_,request);}catch(...){return false;}}
 bool assignment_current(uint64_t request)const noexcept{try{return configured_&&api_.thread()
  &&api_.assignment_current(ctx_,epoch_,job_)&&api_.owned_origin(ctx_,controller_,request);}catch(...){return false;}}
 bool shape(const Descriptor*a,const Descriptor*b)const{return a&&b&&!__builtin_memcmp(a,b,sizeof(*a));}
 bool observe_current(uint64_t request){
  if(!assignment_current(request))return false;
  void*wrapper=nullptr,*texture=nullptr;
  if(!api_.current_capture(ctx_,controller_,&wrapper,&texture))return false;
  return observe_assignment(controller_,request,wrapper,texture);
 }
public:
 class Scope {
  Bank*bank_=nullptr;Cursor cursor_{};bool active_=false;
  friend class Bank;
  Scope(Bank&bank,Kind kind,void*object,const Descriptor*descriptor,void*name,uintptr_t caller,uint64_t request)
   :bank_(&bank){
   cursor_.bank=&bank;cursor_.kind=kind;
   cursor_.parent=Bank::cursor_;cursor_.request=request;cursor_.controller=object;
   const Cursor*parent=cursor_.parent;
   try{if(kind==Kind::update){
    cursor_.origin=object==bank.controller_&&request&&caller==bank.update_return_
     &&bank.api_.owned_origin(bank.ctx_,object,request);
    cursor_.authorized=cursor_.origin&&bank.current(request);
   }else if(parent&&parent->bank==&bank&&parent->origin){
    cursor_.request=parent->request;cursor_.controller=parent->controller;
    if(kind==Kind::wrapper&&parent->kind==Kind::update&&caller==bank.wrapper_return_){
     cursor_.origin=true;
     if(bank.current(parent->request)&&object&&descriptor&&bank.api_.descriptor(bank.ctx_,*descriptor)&&bank.api_.capture_name(bank.ctx_,name)){
     bool duplicate=false;for(uint32_t i=0;i<bank.count_;++i)duplicate|=bank.rows_[i].value.wrapper==object;
     if(bank.count_==max_resources||duplicate){bank.invalid_=true;}
     else{
      cursor_.row=bank.count_++;auto&r=bank.rows_[cursor_.row].value;
      r.epoch=bank.epoch_;r.job=bank.job_;r.request=parent->request;r.wrapper=object;r.descriptor=*descriptor;
      r.wrapper_root=bank.api_.retain(object);cursor_.authorized=bank.roots(r);
      if(!cursor_.authorized){
       if(r.wrapper_root)bank.api_.release(r.wrapper_root);
       bank.rows_[cursor_.row]={};bank.rows_[cursor_.row].transferred=true;cursor_.row=max_resources;
      }
     }
     }
    }else if(kind==Kind::texture&&parent->kind==Kind::wrapper&&caller==bank.texture_return_){
     cursor_.origin=true;
     if(bank.current(parent->request)&&object&&parent->row<bank.count_){
     cursor_.row=parent->row;auto&r=bank.rows_[cursor_.row].value;
     if(!r.texture&&bank.shape(descriptor,&r.descriptor)&&bank.roots(r)){
      r.texture=object;r.texture_root=bank.api_.retain(object);cursor_.authorized=bank.roots(r);
      if(!cursor_.authorized){
       if(r.texture_root)bank.api_.release(r.texture_root);
       r.texture_root=0;r.texture=nullptr;cursor_.row=max_resources;
      }
     }else bank.invalid_=true;
     }
    }
   }
   if(cursor_.origin&&!cursor_.authorized)bank.invalid_=true;
   }catch(...){bank.invalid_=true;cursor_.authorized=false;}
   Bank::cursor_=&cursor_;active_=true;
  }
 public:
  Scope(const Scope&)=delete;Scope&operator=(const Scope&)=delete;
  ~Scope(){if(active_)finish(false);}
  bool owned()const{return cursor_.authorized;}
  bool owned_origin()const{return cursor_.origin;}
  bool must_abort()const noexcept{return cursor_.origin&&(!cursor_.authorized||!bank_->current(cursor_.request));}
  // Always called after the exact original body, including its exceptional
  // path. Result describes origin/root processing, NOT original-body success;
  // the separate returned flags retain that truth. Failure drops no resource.
  bool finish(bool original_returned)noexcept{
   if(!active_||Bank::cursor_!=&cursor_){if(bank_)bank_->invalid_=true;return false;}
   Bank&bank=*bank_;bool result=cursor_.authorized;
   try{
    if(cursor_.row<bank.count_){auto&r=bank.rows_[cursor_.row].value;
     if(!bank.roots(r)){bank.invalid_=true;result=false;}
     else if(cursor_.kind==Kind::texture){
      uintptr_t native=0;r.texture_returned=original_returned;
      r.native_known=bank.api_.texture_native(r.texture,&native);r.native=native;
      if(!r.native_known||(original_returned&&!native)){bank.invalid_=true;result=false;}
     }else if(cursor_.kind==Kind::wrapper){
      r.wrapper_returned=original_returned;
      void*texture=nullptr;const bool read=bank.api_.wrapper_texture(r.wrapper,&texture);
      if(!read||(original_returned&&(!r.texture_returned||texture!=r.texture||!r.native_known||!r.native))){bank.invalid_=true;result=false;}
     }
    }else if(cursor_.kind==Kind::update&&cursor_.origin){
     // An Update body may throw AFTER assigning the new private A0. That
     // assignment is still real production, not a successful capture receipt.
     if(bank.assignment_current(cursor_.request))bank.observe_current(cursor_.request);
    }
   }catch(...){bank.invalid_=true;result=false;}
   Bank::cursor_=cursor_.parent;active_=false;return result;
  }
 };
 bool bind(Api api,void*ctx,void*controller,uint64_t epoch,uint64_t job,
           uintptr_t update_return,uintptr_t wrapper_return,uintptr_t texture_return){
  if(configured_||count_||!ctx||!controller||!epoch||!job||!update_return||!wrapper_return||!texture_return
   ||!api.thread||!api.current||!api.assignment_current||!api.owned_request||!api.owned_origin||!api.descriptor||!api.capture_name||!api.current_capture
   ||!api.wrapper_texture||!api.texture_native||!api.retain||!api.retained||!api.release)return false;
  api_=api;ctx_=ctx;controller_=controller;epoch_=epoch;job_=job;
  update_return_=update_return;wrapper_return_=wrapper_return;texture_return_=texture_return;configured_=true;
  try{if(api_.thread()&&api_.current(ctx_,epoch_,job_))return true;}catch(...){}
  invalid_=true;return false;
 }
 bool valid()const{return configured_&&!invalid_;}uint32_t count()const{return count_;}
 // Historical typed stack closure, independent of a former source validity.
 bool scopes_unwound()const noexcept{try{if(!configured_||!api_.thread||!api_.thread())return false;
  for(auto*scope=cursor_;scope;scope=scope->parent)if(scope->bank==this)return false;
  return true;}catch(...){return false;}}
 static bool all_scopes_unwound()noexcept{return cursor_==nullptr;}
 bool publication_origin(void*controller,uint64_t request)const noexcept{
  const auto*s=cursor_;return s&&s->bank==this&&s->kind==Kind::update&&s->origin
   &&s->controller==controller&&s->request==request;
 }
 bool transferred(uint32_t index)const{return index<count_&&rows_[index].transferred;}
 bool can_prepare()const noexcept{try{return valid()&&count_<max_resources&&api_.thread()
  &&api_.current(ctx_,epoch_,job_);}catch(...){return false;}}
 Scope update(void*controller,uint64_t request,uintptr_t caller){return Scope(*this,Kind::update,controller,nullptr,nullptr,caller,request);}
 Scope wrapper(void*object,const Descriptor*descriptor,void*name,uintptr_t caller){return Scope(*this,Kind::wrapper,object,descriptor,name,caller,0);}
 Scope texture(void*object,const Descriptor*descriptor,uintptr_t caller){return Scope(*this,Kind::texture,object,descriptor,nullptr,caller,0);}
 // May be called from the exact native publication guard AFTER its x30/id
 // match, before suppression, while Update's scope is still on the stack.
 bool observe_assignment(void*controller,uint64_t request,void*wrapper,void*texture){
  const Cursor*scope=cursor_;
  if(!scope||scope->bank!=this||scope->kind!=Kind::update||!scope->origin||controller!=controller_
   ||scope->request!=request||!assignment_current(request))return false;
  for(uint32_t i=0;i<count_;++i){auto&r=rows_[i].value;
   if(!rows_[i].transferred&&r.wrapper==wrapper&&r.texture==texture&&r.wrapper_returned&&r.texture_returned
    &&r.native_known&&r.native&&roots(r)){
    void*actual_wrapper=nullptr,*actual_texture=nullptr;
    if(!api_.current_capture(ctx_,controller_,&actual_wrapper,&actual_texture)
     ||actual_wrapper!=wrapper||actual_texture!=texture||!assignment_current(request))return false;
    uintptr_t native=0;if(!api_.texture_native(texture,&native)||native!=r.native)return false;
    r.assigned=true;return true;
   }
  }return false;
 }
 // Historical private production is sufficient for restore/destroy ownership,
 // regardless of a later CaptureRequest-body/end failure. Never query A0 here.
 bool produced(void*wrapper,void*texture,Resource*out=nullptr)const{
  if(!configured_||!api_.thread())return false;
  for(uint32_t i=0;i<count_;++i){const auto&r=rows_[i].value;
   if(!rows_[i].transferred&&r.wrapper==wrapper&&r.texture==texture&&r.assigned
    &&r.wrapper_returned&&r.texture_returned&&r.native_known&&r.native&&roots(r)){
    if(out)*out=r;
    return true;
   }
  }return false;
 }
 bool historical(uint32_t index,Resource*out)const{
  if(!out||index>=count_||rows_[index].transferred||!api_.thread()||!roots(rows_[index].value))return false;
  *out=rows_[index].value;return true;
 }
 // Sink acquires its OWN strong/native-retirement duties before returning true.
 // No root is dropped on rejection, and no old scene owner is queried.
 bool transfer(uint32_t index,void*sink,bool(*adopt)(void*,const Resource&)){
  for(Cursor*scope=cursor_;scope;scope=scope->parent)if(scope->bank==this)return false;
  Resource resource{};if(!sink||!adopt||!historical(index,&resource)||!adopt(sink,resource))return false;
  auto&r=rows_[index];if(!roots(r.value))return false;
  if(r.value.wrapper_root)api_.release(r.value.wrapper_root);
  if(r.value.texture_root)api_.release(r.value.texture_root);
  r.value.wrapper_root=r.value.texture_root=0;r.transferred=true;return true;
 }
 bool finish(){if(!configured_||!api_.thread())return false;
  for(Cursor*scope=cursor_;scope;scope=scope->parent)if(scope->bank==this)return false;
  for(uint32_t i=0;i<count_;++i)if(!rows_[i].transferred)return false;
  *this=Bank{};return true;
 }
};
} // namespace idoly_mp4_capture_production
// END_MP4_CAPTURE_PRODUCTION_BANK

// BEGIN_MP4_CAPTURE_GLOBAL_LEASE
// One actual _VLCapturedTexture binding. The native sheet observer supplies a
// monotonic serial for ALL writes, including identical and queued GPU writes.
namespace idoly_mp4_capture_global {
using Result=idoly_mp4_camera_state::Result;
struct Value {void*object=nullptr;uintptr_t native=0;};
struct Api {
 bool(*thread)()=nullptr;bool(*current)(void*,uint64_t,uint64_t)=nullptr;bool(*held)(void*)=nullptr;
 bool(*quiet)(void*)=nullptr;uint64_t(*serial)(void*,int32_t)=nullptr;
 bool(*get)(void*,int32_t,Value*)=nullptr;
 // Null, a real immutable texture asset, or the paused-frame lease's exact
 // protected old captured RT. Never a root-only alias of retiring target98.
 bool(*baseline_lifetime)(void*,const Value&)=nullptr;
 // Actual unchanged typed CaptureRequest receipt, native observed +1 write,
 // exact returned wrapper.texture and property. Not merely a matching value.
 bool(*capture_write)(void*,uint64_t before,uint64_t after,const Value&)=nullptr;
 // Exact known original with native observer accounting and expected serial.
 bool(*set_original)(void*,int32_t,const Value&,uint64_t before,uint64_t*after)=nullptr;
 uint32_t(*retain)(void*)=nullptr;void*(*retained)(uint32_t)=nullptr;void(*release_root)(uint32_t)=nullptr;
};
class Lease {
 Api api_{};void*ctx_=nullptr;uint64_t epoch_=0,job_=0,serial_=0;int32_t property_=0;
 Value source_{},last_{};uint32_t source_root_=0,last_root_=0;
 bool active_=false,duty_=false,changed_=false,restored_=false,lost_=false,abandoned_=false,inflight_=false;
 const char*error_="none";
 Result fail(Result r,const char*s){error_=s;return r;}
 static bool same(const Value&a,const Value&b){return a.object==b.object&&a.native==b.native;}
 bool complete()const{return api_.thread&&api_.current&&api_.held&&api_.quiet&&api_.serial&&api_.get&&api_.baseline_lifetime
  &&api_.capture_write&&api_.set_original&&api_.retain&&api_.retained&&api_.release_root;}
 bool roots()const{return (!source_.object||(source_root_&&api_.retained(source_root_)==source_.object))
  &&(!last_.object||(last_root_&&api_.retained(last_root_)==last_.object));}
 bool current()const{return active_&&!abandoned_&&!lost_&&api_.thread()&&api_.current(ctx_,epoch_,job_)&&roots();}
 bool read_stable(Value&out,uint64_t expected)const{return api_.serial(ctx_,property_)==expected&&api_.get(ctx_,property_,&out)
  &&((out.object&&out.native)||(!out.object&&!out.native))&&api_.serial(ctx_,property_)==expected;}
 bool keep_last(const Value&v){uint32_t root=v.object?api_.retain(v.object):0;
  if(v.object&&(!root||api_.retained(root)!=v.object)){if(root)api_.release_root(root);return false;}
  if(last_root_)api_.release_root(last_root_);
  last_root_=root;last_=v;return true;}
public:
 const char*error()const{return error_;}bool restored()const{return restored_;}bool active()const{return active_;}
 Result capture(Api api,void*ctx,uint64_t epoch,uint64_t job,int32_t property){
  if(active_||source_root_||last_root_||!ctx||!epoch||!job)return fail(Result::invalid,"capture_global_state");
  api_=api;ctx_=ctx;epoch_=epoch;job_=job;property_=property;
  if(!complete()||!api_.thread()||!api_.current(ctx,epoch,job)||!api_.held(ctx)||!api_.quiet(ctx))return fail(Result::unsupported,"capture_global_api_or_phase");
  serial_=api_.serial(ctx,property);if(!serial_||!read_stable(source_,serial_)||!api_.baseline_lifetime(ctx,source_))return fail(Result::unsupported,"capture_global_source_lifetime");
  active_=true;duty_=false;
  if(source_.object){source_root_=api_.retain(source_.object);if(!source_root_||api_.retained(source_root_)!=source_.object)return fail(Result::failed,"capture_global_source_root");}
  if(!keep_last(source_))return fail(Result::failed,"capture_global_last_root");
  if(!current())return fail(Result::stale,"capture_global_source_changed");
  duty_=true;return Result::ok;
 }
 // Called only after our actual source CaptureRequest returned. Repeated
 // captures that do not publish a new global require the unchanged serial.
 Result observe_capture(uint64_t before,uint64_t after,const Value&expected){
  if(!current()||inflight_||before!=serial_)return fail(Result::stale,"capture_global_receipt_changed");
  Value actual{};
  if(!read_stable(actual,after)||!same(actual,expected))return fail(Result::stale,"capture_global_value_changed");
  if(after==before){return same(last_,actual)?Result::ok:fail(Result::stale,"capture_global_unobserved_write");}
  if(before==~uint64_t(0)||after!=before+1||!api_.capture_write(ctx_,before,after,expected)){
   lost_=true;return fail(Result::stale,"capture_global_external_write");}
  if(!current()||!keep_last(actual)||!current())return fail(Result::failed,"capture_global_value_root");
  serial_=after;changed_=true;return Result::ok;
 }
 Result restore(){
  if(restored_)return Result::ok;
  if(!current())return fail(Result::stale,"capture_global_source_changed");
  if(!api_.held(ctx_)||!api_.quiet(ctx_))return Result::waiting;
  if(inflight_)return fail(Result::invalid,"capture_global_original_inflight");
  Value live{};if(!read_stable(live,serial_)||!same(live,last_)){
   lost_=true;duty_=false;return fail(Result::stale,"capture_global_superseded");}
  if(!changed_){duty_=false;restored_=true;return Result::ok;}
  if(!api_.baseline_lifetime(ctx_,source_))return fail(Result::stale,"capture_global_source_retired");
  uint64_t after=0;inflight_=true;bool written=false;
  try{written=api_.set_original(ctx_,property_,source_,serial_,&after);}catch(...){inflight_=false;lost_=true;return fail(Result::failed,"capture_global_restore_exception");}
  inflight_=false;
  if(!current()||serial_==~uint64_t(0)||after!=serial_+1||!written||!read_stable(live,after)||!same(live,source_)){
   lost_=true;return fail(Result::failed,"capture_global_restore_receipt");}
  serial_=after;duty_=false;restored_=true;return Result::ok;
 }
 void abandon()noexcept{abandoned_=true;duty_=false;}
 Result verify_held(){
  if(!restored_||!active_)return fail(Result::invalid,"capture_global_not_restored");
  if(!current())return fail(Result::stale,"capture_global_source_changed");
  if(!api_.held(ctx_)||!api_.quiet(ctx_))return Result::waiting;
  Value value{};if(!read_stable(value,serial_)||!same(value,source_)||!api_.baseline_lifetime(ctx_,source_))
   return fail(Result::stale,"capture_global_checkpoint_changed");
  return Result::ok;
 }
 Result release(){
  if((active_||source_root_||last_root_)&&(!api_.thread||!api_.thread()))return Result::invalid;
  if(inflight_)return Result::waiting;
  if(duty_&&!lost_&&!abandoned_)return fail(Result::invalid,"capture_global_restore_owed");
  if(source_root_)api_.release_root(source_root_);
  if(last_root_)api_.release_root(last_root_);
  *this=Lease{};return Result::ok;
 }
};
} // namespace idoly_mp4_capture_global
// END_MP4_CAPTURE_GLOBAL_LEASE

// BEGIN_ORIGINAL_CAMERA_STATE_PROFILE
namespace idoly_mp4_camera_profile {
struct Binding {uintptr_t rva;uint8_t prefix[16];};
struct Profile {
 Binding frame_rt_descriptor;
 Binding frame_rt_ctor;
 Binding frame_rt_create;
 Binding frame_rt_created;
 Binding frame_copy;
 Binding frame_copy_support;
 Binding frame_wrapper_destroy;
 Binding frame_wrapper_publish;
 Binding audio_clip;
 Binding audio_set_clip;
 Binding audio_samples;
 Binding audio_set_samples;
 Binding audio_playing;
 Binding audio_volume;
 Binding audio_set_volume;
 Binding audio_pitch;
 Binding audio_set_pitch;
 Binding audio_loop;
 Binding audio_set_loop;
 Binding audio_mute;
 Binding audio_set_mute;
 Binding audio_play;
 Binding audio_stop;
 Binding audio_pause;
 Binding audio_unpause;
 Binding audio_clip_samples;
 Binding core_instance;
 Binding core_brain_count;
 Binding core_brain;
 Binding core_vcam_count;
 Binding core_vcam;
 Binding brain_frame_ctor;
 Binding blend_ctor;
 Binding status_ctor;
 Binding default_camera_state;
 Binding vcam_previous_set;
 Binding playable_script;
 Binding component_transform;
 Binding component_object;
 Binding component_enabled;
 Binding component_set_enabled;
 Binding object_active;
 Binding object_set_active;
 Binding local_position;
 Binding local_rotation;
 Binding local_scale;
 Binding set_local_pose;
 Binding set_local_scale;
 Binding camera_near;
 Binding camera_set_near;
 Binding camera_far;
 Binding camera_set_far;
 Binding camera_size;
 Binding camera_set_size;
 Binding camera_set_orthographic;
 Binding camera_set_physical;
 Binding camera_set_gate;
 Binding camera_set_sensor;
 Binding camera_set_lens;
 Binding camera_reset_projection;
 Binding find_objects;
 Binding get_components;
 Binding vcam_get_components;
 Binding core_fixed_get;
 Binding core_fixed_set;
 Binding random_get;
 Binding random_set;
 Binding render_stack;
 Binding render_camera;
 Binding render_camera_data;
 Binding selected_renderer;
 Binding renderer_setup;
 Binding renderer_ctor;
 Binding renderer_dispose;
 Binding instantiate;
 Binding render_asset;
 Binding asset_renderer;
 Binding library_ctor;
 Binding motion_data_ctor;
 Binding motion_data_update;
 Binding post_process_ctor;
 Binding post_process_cleanup;
 Binding post_process_reset;
 Binding post_process_grain;
 Binding post_process_dither;
 Binding volume_instance;
 Binding volume_create_stack;
 Binding volume_destroy_stack;
 Binding volume_update_framework;
 Binding volume_stack_component;
 Binding volume_stack_ctor;
 Binding volume_stack_reload;
 Binding texture_curve_ctor;
 Binding texture_curve_release;
 Binding texture_curve_set_dirty;
 Binding animation_curve_keys;
 Binding animation_curve_set_keys;
 Binding shader_variant_warmed;
 Binding use_structured_buffer;
 Binding cine_apply_postfx;
 Binding cine_dynamic_volumes;
 Binding object_name;
 Binding object_hide_flags;
 Binding object_destroy_immediate;
 Binding game_object_ctor_name;
 Binding game_object_layer;
 Binding game_object_transform;
 Binding game_object_set_layer;
 Binding object_active_hierarchy;
 Binding transform_children;
 Binding transform_child;
 Binding transform_parent;
 Binding transform_set_parent;
 Binding string_equal;
 Binding volume_enable;
 Binding volume_disable;
 Binding volume_update;
 Binding focus_callback;
 Binding height_callback;
 Binding height_virtual_human;
 Binding scriptable_ctor;
 Binding scriptable_create_type;
 Binding target_image_process;
 Binding target_image_destroy;
 Binding target_image_mixer;
 Binding target_image_create;
 Binding raw_image_set_texture;
 Binding raw_image_set_uv;
 Binding graphic_set_color;
 Binding video_clip;
 Binding video_set_clip;
 Binding video_source;
 Binding video_set_source;
 Binding video_audio_mode;
 Binding video_set_audio_mode;
 Binding video_audio_tracks;
 Binding video_controlled_tracks;
 Binding video_render_mode;
 Binding video_set_render_mode;
 Binding video_play_on_awake;
 Binding video_set_play_on_awake;
 Binding video_loop;
 Binding video_set_loop;
 Binding video_skip;
 Binding video_set_skip;
 Binding video_wait_first;
 Binding video_set_wait_first;
 Binding video_update_mode;
 Binding video_set_update_mode;
 Binding video_speed;
 Binding video_set_speed;
 Binding video_time_ref;
 Binding video_set_time_ref;
 Binding video_playing;
 Binding video_paused;
 Binding video_prepared;
 Binding video_prepare;
 Binding video_time;
 Binding video_set_time;
 Binding video_frame;
 Binding video_set_frame;
 Binding video_set_external_reference_time;
 Binding video_texture_width;
 Binding video_texture_height;
 Binding video_texture_format;
 Binding video_texture_dimension;
 Binding video_texture_mips;
 Binding video_copy_mip;
 Binding video_descriptor_ctor;
 Binding video_texture;
 Binding video_pause;
 Binding video_stop;
 Binding video_step;
 Binding video_send_frames;
 Binding video_set_send_frames;
 Binding video_clip_frames;
 Binding video_clip_rate;
 Binding video_clip_length;
 Binding video_clip_audio;
 Binding video_image_enable;
 Binding video_image_disable;
 Binding video_image_late;
 Binding maskable_image_enable;
 Binding video_mixer_create;
 Binding video_playable_create;
 Binding video_playable_destroy;
 Binding video_prepare_frame;
 Binding video_process_frame;
 Binding video_update;
 Binding video_sync;
 Binding playable_input_weight;
 Binding video_stop_behaviour;
 Binding video_frame_ready;
 Binding video_seek_completed;
 Binding video_prepare_completed;
 Binding game_object_add_component;
 Binding game_object_get_component;
 Binding object_persist;
 Binding object_set_hide_flags;
 Binding field_offset;
 Binding field_flags;
 Binding class_fields;
 Binding class_size;
 Binding class_value_size;
 Binding class_element;
 Binding class_rank;
 Binding class_value_type;
 Binding class_type;
 Binding write_barrier;
 Binding field_static_get;
 Binding field_static_set;
 Binding runtime_invoke;
};
struct ExtraLayout {
 static constexpr uint32_t brain_update=0x30;
 static constexpr uint32_t brain_blend_update=0x34;
 static constexpr uint32_t shot_camera=0x10;
 static constexpr uint32_t vcam_pipeline=0x1b0;
 static constexpr uint32_t vcam_extensions=0x50;
 static constexpr uint32_t component_owner=0x20;
 static constexpr uint32_t perlin_time=0x78;
 static constexpr uint32_t impulse_active=0x18;
 static constexpr uint32_t event_calls=0x10;
 static constexpr uint32_t event_persistent_group=0x18;
 static constexpr uint32_t event_runtime_list=0x18;
 static constexpr uint32_t event_persistent_list=0x10;
 static constexpr uint32_t event_executing_list=0x20;
 static constexpr uint32_t persistent_group_list=0x10;
 static constexpr int32_t camera_base=0;
 static constexpr int32_t projection_explicit=0;
 static constexpr int32_t projection_implicit=1;
 static constexpr int32_t projection_physical=2;
 static constexpr int32_t camera_late=1;
 static constexpr int32_t camera_smart=2;
 static constexpr int32_t cache_disabled=0;
 static constexpr int32_t blend_late=1;
 static constexpr int32_t video_audio_none=0;
 static constexpr int32_t video_render_api=4;
 static constexpr int32_t video_source_clip=0;
 static constexpr int32_t private_hide_flags=61;
 static constexpr int32_t video_copy_basic=1;
 static constexpr int32_t video_copy_different_types=4;
 static constexpr int32_t video_copy_texture_to_rt=8;
 static constexpr int32_t video_rgba_unorm=8;
 static constexpr int32_t video_rgba_srgb=4;
 static constexpr int32_t video_bgra_unorm=59;
 static constexpr int32_t video_bgra_srgb=57;
};
struct RenderLayout {
 static constexpr uint32_t video_image_player=0xf0;
 static constexpr uint32_t video_track_loop=0xa0;
 static constexpr uint32_t video_mixer_videoplayer=0x10;
 static constexpr uint32_t video_mixer_videoimage=0x18;
 static constexpr uint32_t video_mixer_isrecording=0x20;
 static constexpr uint32_t video_mixer_isplaymode=0x21;
 static constexpr uint32_t video_mixer_loop=0x22;
 static constexpr uint32_t video_mixer_playedonce=0x23;
 static constexpr uint32_t video_mixer_preparing=0x24;
 static constexpr uint32_t video_mixer_drifted=0x25;
 static constexpr uint32_t video_mixer_driftedtime=0x28;
 static constexpr uint32_t video_mixer_seektime=0x30;
 static constexpr uint32_t video_event_preparecompleted=0x18;
 static constexpr uint32_t video_event_looppointreached=0x20;
 static constexpr uint32_t video_event_started=0x28;
 static constexpr uint32_t video_event_framedropped=0x30;
 static constexpr uint32_t video_event_errorreceived=0x38;
 static constexpr uint32_t video_event_seekcompleted=0x40;
 static constexpr uint32_t video_event_clockresyncoccurred=0x48;
 static constexpr uint32_t video_event_frameready=0x50;
 static constexpr uint32_t target_controller_instance=0x0;
 static constexpr uint32_t target_mixer_image=0x10;
 static constexpr uint32_t target_mixer_enabled=0x18;
 static constexpr uint32_t target_clip_template=0x28;
 static constexpr uint32_t target_clip_reference=0x18;
 static constexpr uint32_t target_behaviour_target=0x10;
 static constexpr uint32_t target_behaviour_alpha=0x18;
 static constexpr uint32_t target_behaviour_center=0x1c;
 static constexpr uint32_t target_behaviour_scale=0x24;
 static constexpr uint32_t raw_image_texture=0xd8;
 static constexpr uint32_t raw_image_uv=0xe0;
 static constexpr uint32_t graphic_rect=0x50;
 static constexpr uint32_t graphic_color=0x28;
 static constexpr uint32_t graphic_dirty_layout=0x70;
 static constexpr uint32_t graphic_dirty_vertices=0x78;
 static constexpr uint32_t graphic_dirty_material=0x80;
 static constexpr uint32_t graphic_mask_material=0xa8;
 static constexpr uint32_t graphic_parent_mask=0xb0;
 static constexpr uint32_t graphic_cull_event=0xc0;
 static constexpr uint32_t graphic_stencil=0xcc;
 static constexpr uint32_t controller_additional=0x60;
 static constexpr uint32_t additional_camera=0x60;
 static constexpr uint32_t additional_camera_type=0x2c;
 static constexpr uint32_t additional_camera_stack=0x30;
 static constexpr uint32_t additional_motion=0x70;
 static constexpr uint32_t additional_post_processing=0x4c;
 static constexpr uint32_t renderer_post_process=0x148;
 static constexpr uint32_t renderer_final_post_process=0x150;
 static constexpr uint32_t renderer_lut_pass=0x98;
 static constexpr uint32_t renderer_compute_pass=0xa0;
 static constexpr uint32_t renderer_forward_lights=0x398;
 static constexpr uint32_t forward_structured=0x48;
 static constexpr uint32_t lut_ldr_material=0x80;
 static constexpr uint32_t lut_hdr_material=0x88;
 static constexpr uint32_t compute_pass_shader=0x80;
 static constexpr uint32_t post_library=0x178;
 static constexpr uint32_t renderer_data_features=0x20;
 static constexpr uint32_t renderer_data_feature_map=0x28;
 static constexpr uint32_t renderer_data_post=0x30;
 static constexpr uint32_t renderer_data_shaders=0x40;
 static constexpr uint32_t renderer_data_xr=0x38;
 static constexpr uint32_t renderer_data_mode=0x5c;
 static constexpr uint32_t renderer_mode=0x3a8;
 static constexpr uint32_t renderer_data_blend_shader=0x68;
 static constexpr uint32_t post_shaders=0x18;
 static constexpr uint32_t pipeline_renderers=0x20;
 static constexpr uint32_t pipeline_renderer_data=0x40;
 static constexpr uint32_t pipeline_default_renderer=0x48;
 static constexpr uint32_t additional_renderer_index=0x38;
 static constexpr uint32_t post_compute_shader=0x60;
 static constexpr uint32_t post_shader_variants=0x50;
 static constexpr uint32_t post_data=0x180;
 static constexpr uint32_t post_compute=0x188;
 static constexpr uint32_t post_blit_material=0x218;
 static constexpr uint32_t post_reset=0x1f8;
 static constexpr uint32_t post_dither_index=0x1fc;
 static constexpr uint32_t post_bokeh_kernel=0x208;
 static constexpr uint32_t post_bokeh_hash=0x210;
 static constexpr uint32_t post_event=0x10;
 static constexpr uint32_t motion_view=0x10;
 static constexpr uint32_t motion_previous_view=0x18;
 static constexpr uint32_t motion_last_frame=0x20;
 static constexpr uint32_t motion_previous_aspect=0x28;
 static constexpr uint32_t extension_owner=0x20;
 static constexpr uint32_t extension_extra_state=0x28;
 static constexpr uint32_t focus_offset=0x30;
 static constexpr uint32_t focus_target=0x38;
 static constexpr uint32_t focus_state_profile=0x10;
 static constexpr uint32_t height_virtual=0x30;
 static constexpr uint32_t height_actor=0x38;
 static constexpr uint32_t volume_global=0x20;
 static constexpr uint32_t volume_priority=0x24;
 static constexpr uint32_t volume_blend=0x28;
 static constexpr uint32_t volume_weight=0x2c;
 static constexpr uint32_t volume_shared=0x30;
 static constexpr uint32_t volume_previous_layer=0x38;
 static constexpr uint32_t volume_previous_priority=0x3c;
 static constexpr uint32_t volume_internal=0x40;
 static constexpr uint32_t height_virtual_controller=0x38;
 static constexpr uint32_t state_custom0=0x98;
 static constexpr uint32_t state_custom1=0xa8;
 static constexpr uint32_t state_custom2=0xb8;
 static constexpr uint32_t state_custom3=0xc8;
 static constexpr uint32_t state_custom_overflow=0xd8;
 static constexpr uint32_t state_custom_count=0xe0;
 static constexpr uint32_t camera_data_camera=0x80;
 static constexpr uint32_t camera_data_aspect=0xe4;
 static constexpr uint32_t camera_data_xr=0x100;
 static constexpr uint32_t camera_data_dither=0x131;
 static constexpr uint32_t root_materials[8]={0x3b8,0x3c0,0x3c8,0x3d0,0x3d8,0x3e0,0x3e8,0x3f0};
 static constexpr uint32_t library_materials[13]={0x10,0x18,0x20,0x28,0x30,0x38,0x40,0x48,0x50,0x58,0x60,0x68,0x70};
 static constexpr uint32_t renderer_shaders[7]={0x10,0x18,0x20,0x28,0x30,0x38,0x40};
 static constexpr uint32_t renderer_ctor_shaders[5]={0x10,0x18,0x28,0x20,0x40};
 static constexpr uint32_t post_standard_shaders[11]={0x10,0x18,0x20,0x28,0x30,0x38,0x40,0x48,0x50,0x58,0x60};
 static constexpr uint32_t post_vl_shaders[4]={0x30,0x38,0x40,0x48};
 static constexpr uint32_t forward_light_arrays[5]={0x20,0x28,0x30,0x38,0x40};
};
inline constexpr Profile android_profile={
 {0x8f6a4c4,{0xff,0x83,0x02,0xd1,0xfe,0x57,0x08,0xa9,0xf4,0x4f,0x09,0xa9,0x75,0x88,0x00,0xd0}}, // frame_rt_descriptor
 {0x8f69e7c,{0xff,0xc3,0x02,0xd1,0xfe,0x43,0x00,0xf9,0xf6,0x57,0x09,0xa9,0xf4,0x4f,0x0a,0xa9}}, // frame_rt_ctor
 {0x8f69a28,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x74,0x88,0x00,0xf0,0x81,0xde,0x45,0xf9}}, // frame_rt_create
 {0x8f69aa0,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x74,0x88,0x00,0xf0,0x81,0xe6,0x45,0xf9}}, // frame_rt_created
 {0x8f4b068,{0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0x75,0x89,0x00,0x90}}, // frame_copy
 {0x8f883ac,{0xfe,0x4f,0xbf,0xa9,0x93,0x87,0x00,0xb0,0x60,0xda,0x42,0xf9,0xa0,0x00,0x00,0xb5}}, // frame_copy_support
 {0x92366e0,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x54,0x72,0x00,0x90,0xd5,0x35,0x00,0xf0}}, // frame_wrapper_destroy
 {0x9236624,{0xfe,0x4f,0xbf,0xa9,0xf3,0x03,0x00,0xaa,0x00,0x20,0x40,0xf9,0xe1,0x03,0x1f,0xaa}}, // frame_wrapper_publish
 {0x8f309d4,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xd0,0x81,0xbe,0x41,0xf9}}, // audio_clip
 {0x8f30a10,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x35,0x8a,0x00,0xd0,0xa2,0xc2,0x41,0xf9}}, // audio_set_clip
 {0x8f30954,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xd0,0x81,0xb6,0x41,0xf9}}, // audio_samples
 {0x8f30990,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x35,0x8a,0x00,0xd0,0xa2,0xba,0x41,0xf9}}, // audio_set_samples
 {0x8f30e68,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xd0,0x81,0xe2,0x41,0xf9}}, // audio_playing
 {0x8f307bc,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xd0,0x81,0xa6,0x41,0xf9}}, // audio_volume
 {0x8f307f8,{0xe8,0x0f,0x1e,0xfc,0xfe,0x07,0x00,0xf9,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xd0}}, // audio_set_volume
 {0x8f30844,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xd0,0x81,0x7e,0x41,0xf9}}, // audio_pitch
 {0x8f30880,{0xe8,0x0f,0x1e,0xfc,0xfe,0x07,0x00,0xf9,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xd0}}, // audio_set_pitch
 {0x8f311b4,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xb0,0x81,0xee,0x41,0xf9}}, // audio_loop
 {0x8f311f0,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x35,0x8a,0x00,0xb0,0xa2,0xf2,0x41,0xf9}}, // audio_set_loop
 {0x8f31a28,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xb0,0x81,0x6e,0x42,0xf9}}, // audio_mute
 {0x8f31a64,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x35,0x8a,0x00,0xb0,0xa2,0x72,0x42,0xf9}}, // audio_set_mute
 {0x8f30ad4,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xd0,0x82,0x86,0x41,0xf9}}, // audio_play
 {0x8f30db0,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xd0,0x82,0x92,0x41,0xf9}}, // audio_stop
 {0x8f30df0,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xd0,0x81,0xda,0x41,0xf9}}, // audio_pause
 {0x8f30e2c,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xd0,0x81,0xde,0x41,0xf9}}, // audio_unpause
 {0x8f2f4f4,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xf0,0x81,0x2a,0x41,0xf9}}, // audio_clip_samples
 {0x5a10f38,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x73,0x32,0x02,0xf0,0x14,0xfb,0x01,0xb0}}, // core_instance
 {0x5a110e0,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x74,0x32,0x02,0xd0,0x88,0x4e,0x6a,0x39}}, // core_brain_count
 {0x5a11128,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x75,0x32,0x02,0xd0,0xa8,0x52,0x6a,0x39}}, // core_brain
 {0x5a11240,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x74,0x32,0x02,0xd0,0x88,0x5e,0x6a,0x39}}, // core_vcam_count
 {0x5a11288,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x75,0x32,0x02,0xd0,0xa8,0x62,0x6a,0x39}}, // core_vcam
 {0x59e8490,{0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xb4,0x33,0x02,0xf0}}, // brain_frame_ctor
 {0x5a0e5a0,{0xe9,0x23,0xbc,0x6d,0xfe,0x0b,0x00,0xf9,0xf6,0x57,0x02,0xa9,0xf4,0x4f,0x03,0xa9}}, // blend_ctor
 {0x5a124f8,{0xfe,0x4f,0xbf,0xa9,0xe1,0x03,0x1f,0xaa,0xf3,0x03,0x00,0xaa,0xbb,0xb5,0xb1,0x94}}, // status_ctor
 {0x5a0014c,{0xff,0x83,0x05,0xd1,0xef,0x3b,0x0e,0x6d,0xed,0x33,0x0f,0x6d,0xeb,0x2b,0x10,0x6d}}, // default_camera_state
 {0x5a155c4,{0x28,0x00,0x00,0x12,0x08,0x60,0x01,0x39,0xc0,0x03,0x5f,0xd6,0xeb,0x2b,0xbc,0x6d}}, // vcam_previous_set
 {0x8fae150,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x74,0x86,0x00,0x90,0x81,0x2e,0x42,0xf9}}, // playable_script
 {0x8f7c58c,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xf4,0x87,0x00,0x90,0x81,0xe2,0x47,0xf9}}, // component_transform
 {0x8f7c5c8,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xf4,0x87,0x00,0x90,0x81,0xe6,0x47,0xf9}}, // component_object
 {0x8f7bad0,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xf4,0x87,0x00,0xb0,0x81,0xce,0x47,0xf9}}, // component_enabled
 {0x8f7bb0c,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xf5,0x87,0x00,0xb0,0xa2,0xd2,0x47,0xf9}}, // component_set_enabled
 {0x8f7fd9c,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xd4,0x87,0x00,0xd0,0x81,0x6e,0x40,0xf9}}, // object_active
 {0x8f7fd58,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xd5,0x87,0x00,0xd0,0xa2,0x6a,0x40,0xf9}}, // object_set_active
 {0x8f8be8c,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x75,0x87,0x00,0xd0,0xa2,0xf6,0x44,0xf9}}, // local_position
 {0x8f8c61c,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x75,0x87,0x00,0xb0,0xa2,0x12,0x45,0xf9}}, // local_rotation
 {0x8f8c800,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x75,0x87,0x00,0xb0,0xa2,0x1a,0x45,0xf9}}, // local_scale
 {0x8f8cd0c,{0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0x76,0x87,0x00,0xb0}}, // set_local_pose
 {0x8f8c898,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x75,0x87,0x00,0xb0,0xa2,0x1e,0x45,0xf9}}, // set_local_scale
 {0x8f3b428,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xd4,0x89,0x00,0xf0,0x81,0xe2,0x45,0xf9}}, // camera_near
 {0x8f3b464,{0xe8,0x0f,0x1e,0xfc,0xfe,0x07,0x00,0xf9,0xf4,0x4f,0x01,0xa9,0xd4,0x89,0x00,0xf0}}, // camera_set_near
 {0x8f3b4b0,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xd4,0x89,0x00,0xf0,0x81,0xea,0x45,0xf9}}, // camera_far
 {0x8f3b4ec,{0xe8,0x0f,0x1e,0xfc,0xfe,0x07,0x00,0xf9,0xf4,0x4f,0x01,0xa9,0xd4,0x89,0x00,0xf0}}, // camera_set_far
 {0x8f3b8b8,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xd4,0x89,0x00,0xf0,0x81,0x2a,0x46,0xf9}}, // camera_size
 {0x8f3b8f4,{0xe8,0x0f,0x1e,0xfc,0xfe,0x07,0x00,0xf9,0xf4,0x4f,0x01,0xa9,0xd4,0x89,0x00,0xf0}}, // camera_set_size
 {0x8f3b97c,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xd5,0x89,0x00,0xf0,0xa2,0x36,0x46,0xf9}}, // camera_set_orthographic
 {0x8f3c82c,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xd5,0x89,0x00,0xd0,0xa2,0xce,0x46,0xf9}}, // camera_set_physical
 {0x8f3d030,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xd5,0x89,0x00,0xb0,0xa2,0x16,0x47,0xf9}}, // camera_set_gate
 {0x8f3ce94,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xd5,0x89,0x00,0xf0,0xa2,0x22,0x40,0xf9}}, // camera_set_sensor
 {0x8f3cfb0,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xd5,0x89,0x00,0xf0,0xa2,0x2a,0x40,0xf9}}, // camera_set_lens
 {0x8f3ddd4,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xd4,0x89,0x00,0xb0,0x81,0x52,0x47,0xf9}}, // camera_reset_projection
 {0x8f84ae0,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xb5,0x87,0x00,0xb0,0xa2,0x6a,0x41,0xf9}}, // find_objects
 {0x8f7f524,{0xfe,0x0f,0x1b,0xf8,0xfa,0x67,0x01,0xa9,0xf8,0x5f,0x02,0xa9,0xf6,0x57,0x03,0xa9}}, // get_components
 {0x59ff19c,{0xfe,0x4f,0xbf,0xa9,0xf3,0x03,0x00,0xaa,0x0a,0x00,0x00,0x94,0x60,0xda,0x40,0xf9}}, // vcam_get_components
 {0x5a118c8,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x74,0x32,0x02,0xd0,0x13,0xfb,0x01,0x90}}, // core_fixed_get
 {0x5a11920,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x75,0x32,0x02,0xd0,0x14,0xfb,0x01,0x90}}, // core_fixed_set
 {0x8f7a2c8,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xf4,0x87,0x00,0xd0,0x81,0x82,0x47,0xf9}}, // random_get
 {0x8f7a344,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xf4,0x87,0x00,0xd0,0x81,0x86,0x47,0xf9}}, // random_set
 {0x8e28798,{0xfd,0x7b,0xba,0xa9,0xfc,0x6f,0x01,0xa9,0xfa,0x67,0x02,0xa9,0xf8,0x5f,0x03,0xa9}}, // render_stack
 {0x8e29be4,{0xfd,0x7b,0xbd,0xa9,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xff,0xc3,0x0a,0xd1}}, // render_camera
 {0x8e2a13c,{0xfd,0x7b,0xba,0xa9,0xfc,0x6f,0x01,0xa9,0xfa,0x67,0x02,0xa9,0xf8,0x5f,0x03,0xa9}}, // render_camera_data
 {0x8e26a78,{0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0x75,0x92,0x00,0xd0}}, // selected_renderer
 {0x8e000ac,{0xfd,0x7b,0xba,0xa9,0xfc,0x6f,0x01,0xa9,0xfa,0x67,0x02,0xa9,0xf8,0x5f,0x03,0xa9}}, // renderer_setup
 {0x8dfed54,{0xff,0x03,0x02,0xd1,0xfd,0x7b,0x02,0xa9,0xfc,0x6f,0x03,0xa9,0xfa,0x67,0x04,0xa9}}, // renderer_ctor
 {0x8dfffa8,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xb4,0x93,0x00,0xb0,0x88,0xda,0x58,0x39}}, // renderer_dispose
 {0x8f84450,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xb5,0x87,0x00,0xb0,0x74,0x4b,0x00,0xb0}}, // instantiate
 {0x8e26ff8,{0xfe,0x4f,0xbf,0xa9,0x73,0x92,0x00,0xd0,0x68,0x4a,0x5d,0x39,0xc8,0x00,0x00,0x37}}, // render_asset
 {0x8e10518,{0xff,0x03,0x01,0xd1,0xfe,0x5f,0x01,0xa9,0xf6,0x57,0x02,0xa9,0xf4,0x4f,0x03,0xa9}}, // asset_renderer
 {0x8e0daf8,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xf4,0x03,0x01,0xaa,0xe1,0x03,0x1f,0xaa}}, // library_ctor
 {0x8e1bf3c,{0xff,0x83,0x04,0xd1,0xfd,0x7b,0x0c,0xa9,0xfc,0x6f,0x0d,0xa9,0xfa,0x67,0x0e,0xa9}}, // motion_data_ctor
 {0x8e1526c,{0xe9,0x23,0xbb,0x6d,0xfd,0x0b,0x00,0xf9,0xfe,0x5f,0x02,0xa9,0xf6,0x57,0x03,0xa9}}, // motion_data_update
 {0x8dff914,{0xff,0x03,0x06,0xd1,0xfd,0x7b,0x12,0xa9,0xfc,0x6f,0x13,0xa9,0xfa,0x67,0x14,0xa9}}, // post_process_ctor
 {0x8e00090,{0xfe,0x0f,0x1f,0xf8,0x00,0xbc,0x40,0xf9,0x80,0x00,0x00,0xb4,0xe1,0x03,0x1f,0xaa}}, // post_process_cleanup
 {0x8e02be8,{0x28,0x00,0x80,0x52,0x08,0xe0,0x07,0x39,0xc0,0x03,0x5f,0xd6,0xe0,0x03,0x1f,0x2a}}, // post_process_reset
 {0x8e09098,{0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0x56,0x93,0x00,0xf0}}, // post_process_grain
 {0x8e09158,{0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0x56,0x93,0x00,0xf0}}, // post_process_dither
 {0x8de72bc,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x74,0x94,0x00,0xb0,0x53,0x5f,0x00,0xd0}}, // volume_instance
 {0x8de7814,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x74,0x94,0x00,0xb0,0x55,0x60,0x00,0xb0}}, // volume_create_stack
 {0x8de7a04,{0x61,0x00,0x00,0xb4,0xe0,0x03,0x01,0xaa,0x03,0x00,0x00,0x14,0xfe,0x0f,0x1f,0xf8}}, // volume_destroy_stack
 {0x8e29918,{0xff,0x03,0x01,0xd1,0xfe,0x0b,0x00,0xf9,0xf6,0x57,0x02,0xa9,0xf4,0x4f,0x03,0xa9}}, // volume_update_framework
 {0x8de8350,{0xff,0xc3,0x00,0xd1,0xfe,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0x75,0x94,0x00,0x90}}, // volume_stack_component
 {0x8de7880,{0xe1,0x03,0x1f,0xaa,0xdb,0x60,0xe2,0x17,0xfe,0x67,0xbc,0xa9,0xf8,0x5f,0x01,0xa9}}, // volume_stack_ctor
 {0x8de7888,{0xfe,0x67,0xbc,0xa9,0xf8,0x5f,0x01,0xa9,0xf6,0x57,0x02,0xa9,0xf4,0x4f,0x03,0xa9}}, // volume_stack_reload
 {0x8de519c,{0xe9,0x23,0xbb,0x6d,0xfe,0x0b,0x00,0xf9,0xf8,0x5f,0x02,0xa9,0xf6,0x57,0x03,0xa9}}, // texture_curve_ctor
 {0x8de52ac,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x75,0x94,0x00,0xf0,0x34,0x5e,0x00,0x90}}, // texture_curve_release
 {0x8de530c,{0x28,0x20,0x80,0x52,0x08,0x70,0x00,0x79,0xc0,0x03,0x5f,0xd6,0xfe,0x4f,0xbf,0xa9}}, // texture_curve_set_dirty
 {0x8f380a8,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xf4,0x89,0x00,0xd0,0x81,0x1a,0x45,0xf9}}, // animation_curve_keys
 {0x8f38120,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xf5,0x89,0x00,0xd0,0xa2,0x16,0x45,0xf9}}, // animation_curve_set_keys
 {0x8f87848,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x94,0x87,0x00,0xd0,0x81,0x56,0x42,0xf9}}, // shader_variant_warmed
 {0x8e220dc,{0xe0,0x03,0x1f,0x2a,0xc0,0x03,0x5f,0xd6,0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9}}, // use_structured_buffer
 {0x5a1d398,{0xff,0x83,0x05,0xd1,0xe8,0x7b,0x00,0xfd,0xfd,0x7b,0x10,0xa9,0xfc,0x6f,0x11,0xa9}}, // cine_apply_postfx
 {0x5a1d630,{0xff,0xc3,0x01,0xd1,0xfd,0x7b,0x01,0xa9,0xfc,0x6f,0x02,0xa9,0xfa,0x67,0x03,0xa9}}, // cine_dynamic_volumes
 {0x8f83df8,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xb4,0x87,0x00,0xd0,0x75,0x4b,0x00,0xd0}}, // object_name
 {0x8f84c3c,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xb4,0x87,0x00,0xb0,0x81,0x7a,0x41,0xf9}}, // object_hide_flags
 {0x8f849ac,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xb5,0x87,0x00,0xb0,0xa2,0x62,0x41,0xf9}}, // object_destroy_immediate
 {0x8f8013c,{0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xd5,0x87,0x00,0xb0}}, // game_object_ctor_name
 {0x8f7fc58,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xd4,0x87,0x00,0xd0,0x81,0x5a,0x40,0xf9}}, // game_object_layer
 {0x8f7fc1c,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xd4,0x87,0x00,0xd0,0x81,0x56,0x40,0xf9}}, // game_object_transform
 {0x8f7fc94,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xd5,0x87,0x00,0xd0,0xa2,0x5e,0x40,0xf9}}, // game_object_set_layer
 {0x8f7fdd8,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xd4,0x87,0x00,0xd0,0x81,0x72,0x40,0xf9}}, // object_active_hierarchy
 {0x8f8e92c,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x54,0x87,0x00,0xf0,0x81,0x9a,0x44,0xf9}}, // transform_children
 {0x8f8ef48,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x55,0x87,0x00,0xf0,0xa2,0xce,0x44,0xf9}}, // transform_child
 {0x8f8bc60,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x74,0x87,0x00,0xd0,0x81,0x52,0x44,0xf9}}, // transform_parent
 {0x8f8cab0,{0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0x76,0x87,0x00,0xb0}}, // transform_set_parent
 {0x84cac24,{0x47,0xff,0xff,0x17,0xfe,0x0f,0x1f,0xf8,0x45,0xff,0xff,0x97,0xe8,0x03,0x20,0x2a}}, // string_equal
 {0x8de5e34,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x74,0x94,0x00,0xf0,0x88,0x92,0x54,0x39}}, // volume_enable
 {0x8de5ebc,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x74,0x94,0x00,0xf0,0x75,0x5f,0x00,0x90}}, // volume_disable
 {0x8de5f48,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x74,0x94,0x00,0xf0,0x88,0x9a,0x54,0x39}}, // volume_update
 {0x9218768,{0xff,0x03,0x02,0xd1,0xee,0x0b,0x00,0xfd,0xed,0x33,0x02,0x6d,0xeb,0x2b,0x03,0x6d}}, // focus_callback
 {0x8842808,{0xff,0x43,0x03,0xd1,0xeb,0x2b,0x08,0x6d,0xe9,0x23,0x09,0x6d,0xfe,0x53,0x00,0xf9}}, // height_callback
 {0x8836f60,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xd4,0xc1,0x00,0xf0,0x88,0x2e,0x40,0x39}}, // height_virtual_human
 {0x8f81d18,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xd4,0x87,0x00,0x90,0x95,0x4b,0x00,0x90}}, // scriptable_ctor
 {0x8f81e14,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xd5,0x87,0x00,0x90,0xa2,0x2a,0x41,0xf9}}, // scriptable_create_type
 {0x8811670,{0xff,0x43,0x03,0xd1,0xee,0x1b,0x00,0xfd,0xed,0x33,0x04,0x6d,0xeb,0x2b,0x05,0x6d}}, // target_image_process
 {0x88115e8,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xf5,0xc2,0x00,0xf0,0x14,0x87,0x00,0x90}}, // target_image_destroy
 {0x8811d40,{0xfe,0x5f,0xbd,0xa9,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xf7,0xc2,0x00,0xf0}}, // target_image_mixer
 {0x8811484,{0xff,0x03,0x01,0xd1,0xfe,0x5f,0x01,0xa9,0xf6,0x57,0x02,0xa9,0xf4,0x4f,0x03,0xa9}}, // target_image_create
 {0x91d1aa8,{0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0x76,0x75,0x00,0x90}}, // raw_image_set_texture
 {0x91d1b60,{0x04,0xe0,0x40,0xbd,0x80,0x20,0x20,0x1e,0x61,0x01,0x00,0x54,0x04,0xec,0x40,0xbd}}, // raw_image_set_uv
 {0x906f250,{0xfe,0x4f,0xbf,0xa9,0xf3,0x03,0x00,0xaa,0x00,0xa0,0x00,0x91,0xe1,0x03,0x1f,0xaa}}, // graphic_set_color
 {0x91fc420,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0x4e,0x47,0xf9}}, // video_clip
 {0x91fc45c,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x15,0x74,0x00,0xb0,0xa2,0x52,0x47,0xf9}}, // video_set_clip
 {0x91fc2a0,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0x36,0x47,0xf9}}, // video_source
 {0x91fc2dc,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x15,0x74,0x00,0xb0,0xa2,0x3a,0x47,0xf9}}, // video_set_source
 {0x91fd6a8,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0x66,0x40,0xf9}}, // video_audio_mode
 {0x91fd6e4,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x15,0x74,0x00,0xb0,0xa2,0x6a,0x40,0xf9}}, // video_set_audio_mode
 {0x91fd324,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0x42,0x40,0xf9}}, // video_audio_tracks
 {0x91fd454,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0x56,0x40,0xf9}}, // video_controlled_tracks
 {0x91fc4a0,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0x56,0x47,0xf9}}, // video_render_mode
 {0x91fc4dc,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x15,0x74,0x00,0xb0,0xa2,0x5a,0x47,0xf9}}, // video_set_render_mode
 {0x91fca18,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0xae,0x47,0xf9}}, // video_play_on_awake
 {0x91fca54,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x15,0x74,0x00,0xb0,0xa2,0xb2,0x47,0xf9}}, // video_set_play_on_awake
 {0x91fce80,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0xf6,0x47,0xf9}}, // video_loop
 {0x91fcebc,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x15,0x74,0x00,0xb0,0xa2,0xfa,0x47,0xf9}}, // video_set_loop
 {0x91fd100,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0x1e,0x40,0xf9}}, // video_skip
 {0x91fd13c,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x15,0x74,0x00,0xb0,0xa2,0x22,0x40,0xf9}}, // video_set_skip
 {0x91fc998,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0xa6,0x47,0xf9}}, // video_wait_first
 {0x91fc9d4,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x15,0x74,0x00,0xb0,0xa2,0xaa,0x47,0xf9}}, // video_set_wait_first
 {0x91fc320,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0x3e,0x47,0xf9}}, // video_update_mode
 {0x91fc35c,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x15,0x74,0x00,0xb0,0xa2,0x42,0x47,0xf9}}, // video_set_update_mode
 {0x91fcdf8,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0xee,0x47,0xf9}}, // video_speed
 {0x91fce34,{0xe8,0x0f,0x1e,0xfc,0xfe,0x07,0x00,0xf9,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0}}, // video_set_speed
 {0x91fcfbc,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xd0,0x81,0x0a,0x40,0xf9}}, // video_time_ref
 {0x91fcff8,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x15,0x74,0x00,0xb0,0xa2,0x0e,0x40,0xf9}}, // video_set_time_ref
 {0x91fcb4c,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0xc2,0x47,0xf9}}, // video_playing
 {0x91fcb88,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0xc6,0x47,0xf9}}, // video_paused
 {0x91fc95c,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0xa2,0x47,0xf9}}, // video_prepared
 {0x91fc920,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0x9e,0x47,0xf9}}, // video_prepare
 {0x91fcc00,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0xce,0x47,0xf9}}, // video_time
 {0x91fcc3c,{0xe8,0x0f,0x1e,0xfc,0xfe,0x07,0x00,0xf9,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0}}, // video_set_time
 {0x91fcc88,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0xd6,0x47,0xf9}}, // video_frame
 {0x91fccc4,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x15,0x74,0x00,0xb0,0xa2,0xda,0x47,0xf9}}, // video_set_frame
 {0x91fd078,{0xe8,0x0f,0x1e,0xfc,0xfe,0x07,0x00,0xf9,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0}}, // video_set_external_reference_time
 {0x8f61c44,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xb4,0x88,0x00,0xf0,0x81,0x52,0x43,0xf9}}, // video_texture_width
 {0x8f61cb8,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xb4,0x88,0x00,0xf0,0x81,0x56,0x43,0xf9}}, // video_texture_height
 {0x8f61b38,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xb4,0x88,0x00,0xf0,0x95,0x54,0x00,0xb0}}, // video_texture_format
 {0x8f61d2c,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xb4,0x88,0x00,0xf0,0x81,0x5a,0x43,0xf9}}, // video_texture_dimension
 {0x8f61afc,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xb4,0x88,0x00,0xf0,0x81,0x4a,0x43,0xf9}}, // video_texture_mips
 {0x8f4b0ec,{0xfe,0x0f,0x1b,0xf8,0xfa,0x67,0x01,0xa9,0xf8,0x5f,0x02,0xa9,0xf6,0x57,0x03,0xa9}}, // video_copy_mip
 {0x8f6be70,{0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0x00,0xe4,0x00,0x6f}}, // video_descriptor_ctor
 {0x91fc8e4,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0x9a,0x47,0xf9}}, // video_texture
 {0x91fcad4,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0xba,0x47,0xf9}}, // video_pause
 {0x91fcb10,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0xbe,0x47,0xf9}}, // video_stop
 {0x91fcd80,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0xe6,0x47,0xf9}}, // video_step
 {0x91fe1b4,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0x90,0x81,0x92,0x40,0xf9}}, // video_send_frames
 {0x91fe1f0,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x15,0x74,0x00,0x90,0xa2,0x96,0x40,0xf9}}, // video_set_send_frames
 {0x91fbfb8,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xd0,0x81,0x06,0x47,0xf9}}, // video_clip_frames
 {0x91fbff4,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xd0,0x81,0x0a,0x47,0xf9}}, // video_clip_rate
 {0x91fc030,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0x0e,0x47,0xf9}}, // video_clip_length
 {0x91fc198,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x74,0x00,0xb0,0x81,0x26,0x47,0xf9}}, // video_clip_audio
 {0x8864a5c,{0xff,0xc3,0x00,0xd1,0xfe,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0x75,0xc0,0x00,0xb0}}, // video_image_enable
 {0x8864b5c,{0xfe,0x4f,0xbf,0xa9,0xe1,0x03,0x1f,0xaa,0xf3,0x03,0x00,0xaa,0xe4,0xad,0x25,0x94}}, // video_image_disable
 {0x8864b80,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0x75,0xc0,0x00,0xb0,0x74,0x84,0x00,0xb0}}, // video_image_late
 {0x91d0154,{0xfe,0x4f,0xbf,0xa9,0xe1,0x03,0x1f,0xaa,0xf3,0x03,0x00,0xaa,0x5a,0x81,0xfa,0x97}}, // maskable_image_enable
 {0x8812f04,{0xff,0x43,0x01,0xd1,0xfe,0x67,0x01,0xa9,0xf8,0x5f,0x02,0xa9,0xf6,0x57,0x03,0xa9}}, // video_mixer_create
 {0x8812a34,{0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xf5,0xc2,0x00,0xd0}}, // video_playable_create
 {0x8812c14,{0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xf5,0xc2,0x00,0xd0}}, // video_playable_destroy
 {0x8812368,{0xe8,0x0f,0x1b,0xfc,0xfe,0x07,0x00,0xf9,0xfa,0x67,0x01,0xa9,0xf8,0x5f,0x02,0xa9}}, // video_prepare_frame
 {0x881260c,{0xfe,0x0f,0x1b,0xf8,0xfa,0x67,0x01,0xa9,0xf8,0x5f,0x02,0xa9,0xf6,0x57,0x03,0xa9}}, // video_process_frame
 {0x8812078,{0xe8,0x0f,0x1e,0xfc,0xfe,0x07,0x00,0xf9,0xf4,0x4f,0x01,0xa9,0x08,0x80,0x40,0x39}}, // video_update
 {0x8812260,{0xe8,0x0f,0x1d,0xfc,0xfe,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xf4,0xc2,0x00,0xd0}}, // video_sync
 {0x8faca30,{0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0x75,0x86,0x00,0xd0}}, // playable_input_weight
 {0x881289c,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xf5,0xc2,0x00,0xd0,0xf4,0x86,0x00,0xf0}}, // video_stop_behaviour
 {0x91fe3a0,{0xfe,0x0f,0x1f,0xf8,0x80,0x01,0x00,0xb4,0x08,0x28,0x40,0xf9,0xe2,0x03,0x01,0xaa}}, // video_frame_ready
 {0x91fe4ac,{0xfe,0x0f,0x1f,0xf8,0x60,0x01,0x00,0xb4,0x08,0x20,0x40,0xf9,0xe1,0x03,0x00,0xaa}}, // video_seek_completed
 {0x91fe36c,{0xfe,0x0f,0x1f,0xf8,0x60,0x01,0x00,0xb4,0x08,0x0c,0x40,0xf9,0xe1,0x03,0x00,0xaa}}, // video_prepare_completed
 {0x8f7fa40,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xd5,0x87,0x00,0xd0,0xa2,0x46,0x40,0xf9}}, // game_object_add_component
 {0x8f7c67c,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xf5,0x87,0x00,0xb0,0xa2,0x1a,0x40,0xf9}}, // game_object_get_component
 {0x8f84c00,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0xb4,0x87,0x00,0xb0,0x81,0x76,0x41,0xf9}}, // object_persist
 {0x8f84c78,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x01,0xa9,0xb5,0x87,0x00,0xb0,0xa2,0x7e,0x41,0xf9}}, // object_set_hide_flags
 {0x419e188,{0xb2,0xf1,0x00,0x14,0xa5,0xcf,0x00,0x14,0xb2,0xf1,0x00,0x14,0x24,0xf2,0x00,0x14}}, // field_offset
 {0x419e180,{0xb1,0xf1,0x00,0x14,0x79,0x86,0xfe,0x17,0xb2,0xf1,0x00,0x14,0xa5,0xcf,0x00,0x14}}, // field_flags
 {0x419dacc,{0x18,0x87,0xfe,0x17,0x2a,0x88,0xfe,0x17,0x76,0x87,0xfe,0x17,0x67,0x88,0xfe,0x17}}, // class_fields
 {0x419dafc,{0x6a,0x87,0xfe,0x17,0x59,0x88,0xfe,0x17,0x08,0x28,0x40,0xb9,0x00,0x7d,0x1f,0x53}}, // class_size
 {0x419db1c,{0xa4,0x88,0xfe,0x17,0x00,0x18,0x41,0xb9,0xc0,0x03,0x5f,0xd6,0x08,0x60,0x44,0x39}}, // class_value_size
 {0x419dac4,{0xdf,0x86,0xfe,0x17,0xe5,0x86,0xfe,0x17,0x18,0x87,0xfe,0x17,0x2a,0x88,0xfe,0x17}}, // class_element
 {0x419db98,{0x00,0xc8,0x44,0x39,0xc0,0x03,0x5f,0xd6,0x00,0x0c,0x41,0xb9,0xc0,0x03,0x5f,0xd6}}, // class_rank
 {0x419db04,{0x08,0x28,0x40,0xb9,0x00,0x7d,0x1f,0x53,0xc0,0x03,0x5f,0xd6,0x08,0xd8,0x44,0x39}}, // class_value_type
 {0x419db6c,{0x00,0x80,0x00,0x91,0xc0,0x03,0x5f,0xd6,0x00,0x1c,0x41,0xb9,0xc0,0x03,0x5f,0xd6}}, // class_type
 {0x419e294,{0xe0,0x03,0x01,0xaa,0xe1,0x03,0x02,0xaa,0x41,0x4d,0xff,0x17,0xe0,0x03,0x1f,0x2a}}, // write_barrier
 {0x419e1a4,{0x85,0xf3,0x00,0x14,0xb1,0xf3,0x00,0x14,0x08,0x04,0x40,0xf9,0x08,0x21,0x40,0x39}}, // field_static_get
 {0x419e1a8,{0xb1,0xf3,0x00,0x14,0x08,0x04,0x40,0xf9,0x08,0x21,0x40,0x39,0x00,0x19,0x06,0x53}}, // field_static_set
 {0x419e3dc,{0x3d,0xf9,0x00,0x14,0xe6,0xf1,0x00,0x14,0xd0,0xfa,0x00,0x14,0xd1,0xfa,0x00,0x14}}, // runtime_invoke
};
inline constexpr Profile ios_profile={
 {0x7831718,{0xff,0xc3,0x02,0xd1,0xf6,0x57,0x08,0xa9,0xf4,0x4f,0x09,0xa9,0xfd,0x7b,0x0a,0xa9}}, // frame_rt_descriptor
 {0x7830f20,{0xff,0xc3,0x01,0xd1,0xf6,0x57,0x04,0xa9,0xf4,0x4f,0x05,0xa9,0xfd,0x7b,0x06,0xa9}}, // frame_rt_ctor
 {0x78308c0,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x87,0x01,0x90}}, // frame_rt_create
 {0x7830960,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x87,0x01,0x90}}, // frame_rt_created
 {0x78076e4,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // frame_copy
 {0x7859c0c,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x13,0x86,0x01,0xf0}}, // frame_copy_support
 {0x7bc3578,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // frame_wrapper_destroy
 {0x7bc347c,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}}, // frame_wrapper_publish
 {0x77e12a4,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0x90}}, // audio_clip
 {0x77e12f4,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // audio_set_clip
 {0x77e11f0,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0x90}}, // audio_samples
 {0x77e1240,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // audio_set_samples
 {0x77e1888,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0x90}}, // audio_playing
 {0x77e0fd4,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0xb0}}, // audio_volume
 {0x77e1024,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // audio_set_volume
 {0x77e1088,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0x90}}, // audio_pitch
 {0x77e10d8,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // audio_set_pitch
 {0x77e1c74,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0x90}}, // audio_loop
 {0x77e1cc4,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // audio_set_loop
 {0x77e2820,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xb3,0x89,0x01,0xf0}}, // audio_mute
 {0x77e2870,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // audio_set_mute
 {0x77e140c,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0x90}}, // audio_play
 {0x77e1790,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0x90}}, // audio_stop
 {0x77e17e8,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0x90}}, // audio_pause
 {0x77e1838,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0x90}}, // audio_unpause
 {0x77df754,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0xd0}}, // audio_clip_samples
 {0x3418650,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0xa7,0x03,0x90}}, // core_instance
 {0x3418848,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}}, // core_brain_count
 {0x3418894,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // core_brain
 {0x3418a18,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}}, // core_vcam_count
 {0x3418a64,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // core_vcam
 {0x33e8058,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // brain_frame_ctor
 {0x341470c,{0xe9,0x23,0xbc,0x6d,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xfd,0x7b,0x03,0xa9}}, // blend_ctor
 {0x341a204,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}}, // status_ctor
 {0x3403574,{0xff,0x83,0x03,0xd1,0xed,0x33,0x07,0x6d,0xeb,0x2b,0x08,0x6d,0xe9,0x23,0x09,0x6d}}, // default_camera_state
 {0x341ecf4,{0x01,0x60,0x01,0x39,0xc0,0x03,0x5f,0xd6,0xeb,0x2b,0xbb,0x6d,0xe9,0x23,0x01,0x6d}}, // vcam_previous_set
 {0x78951e8,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x53,0x84,0x01,0x90}}, // playable_script
 {0x7849a24,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x93,0x86,0x01,0xf0}}, // component_transform
 {0x7849a74,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x93,0x86,0x01,0xf0}}, // component_object
 {0x7848abc,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xb3,0x86,0x01,0x90}}, // component_enabled
 {0x7848b0c,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // component_set_enabled
 {0x784e59c,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x86,0x01,0xd0}}, // object_active
 {0x784e538,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // object_set_active
 {0x785f694,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // local_position
 {0x7860754,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // local_rotation
 {0x78609e8,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // local_scale
 {0x7861070,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // set_local_pose
 {0x7860ac0,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // set_local_scale
 {0x77f0d54,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x53,0x89,0x01,0xd0}}, // camera_near
 {0x77f0da4,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // camera_set_near
 {0x77f0e08,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x53,0x89,0x01,0xd0}}, // camera_far
 {0x77f0e58,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // camera_set_far
 {0x77f1394,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x53,0x89,0x01,0xb0}}, // camera_size
 {0x77f13e4,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // camera_set_size
 {0x77f1498,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // camera_set_orthographic
 {0x77f2884,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // camera_set_physical
 {0x77f3394,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // camera_set_gate
 {0x77f314c,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // camera_set_sensor
 {0x77f32e0,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // camera_set_lens
 {0x77f4674,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x33,0x89,0x01,0xd0}}, // camera_reset_projection
 {0x7854ed8,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // find_objects
 {0x784d904,{0xfa,0x67,0xbb,0xa9,0xf8,0x5f,0x01,0xa9,0xf6,0x57,0x02,0xa9,0xf4,0x4f,0x03,0xa9}}, // get_components
 {0x34023d8,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}}, // vcam_get_components
 {0x34191f8,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x54,0xa7,0x03,0xf0}}, // core_fixed_get
 {0x3419274,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // core_fixed_set
 {0x784697c,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xb3,0x86,0x01,0xd0}}, // random_get
 {0x7846a30,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xb3,0x86,0x01,0xd0}}, // random_set
 {0x76ab114,{0xfc,0x6f,0xba,0xa9,0xfa,0x67,0x01,0xa9,0xf8,0x5f,0x02,0xa9,0xf6,0x57,0x03,0xa9}}, // render_stack
 {0x76ac7e0,{0xfc,0x6f,0xbc,0xa9,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xfd,0x7b,0x03,0xa9}}, // render_camera
 {0x76ace98,{0xfc,0x6f,0xba,0xa9,0xfa,0x67,0x01,0xa9,0xf8,0x5f,0x02,0xa9,0xf6,0x57,0x03,0xa9}}, // render_camera_data
 {0x76a8b9c,{0xf8,0x5f,0xbc,0xa9,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xfd,0x7b,0x03,0xa9}}, // selected_renderer
 {0x767ed5c,{0xfc,0x6f,0xba,0xa9,0xfa,0x67,0x01,0xa9,0xf8,0x5f,0x02,0xa9,0xf6,0x57,0x03,0xa9}}, // renderer_setup
 {0x767d8ac,{0xff,0x03,0x02,0xd1,0xfc,0x6f,0x02,0xa9,0xfa,0x67,0x03,0xa9,0xf8,0x5f,0x04,0xa9}}, // renderer_ctor
 {0x767ec4c,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}}, // renderer_dispose
 {0x785434c,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // instantiate
 {0x76a94d0,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x93,0x01,0xf0}}, // render_asset
 {0x7690928,{0xff,0x43,0x01,0xd1,0xf8,0x5f,0x01,0xa9,0xf6,0x57,0x02,0xa9,0xf4,0x4f,0x03,0xa9}}, // asset_renderer
 {0x768db28,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf4,0x03,0x01,0xaa}}, // library_ctor
 {0x769cfc8,{0xfc,0x6f,0xba,0xa9,0xfa,0x67,0x01,0xa9,0xf8,0x5f,0x02,0xa9,0xf6,0x57,0x03,0xa9}}, // motion_data_ctor
 {0x7695994,{0xe9,0x23,0xbb,0x6d,0xf8,0x5f,0x01,0xa9,0xf6,0x57,0x02,0xa9,0xf4,0x4f,0x03,0xa9}}, // motion_data_update
 {0x767e5b8,{0xff,0xc3,0x06,0xd1,0xfc,0x6f,0x15,0xa9,0xfa,0x67,0x16,0xa9,0xf8,0x5f,0x17,0xa9}}, // post_process_ctor
 {0x767ed40,{0x00,0xbc,0x40,0xf9,0x60,0x00,0x00,0xb4,0x01,0x00,0x80,0xd2,0x5a,0x3c,0x00,0x14}}, // post_process_cleanup
 {0x7681da8,{0x28,0x00,0x80,0x52,0x08,0xe0,0x07,0x39,0xc0,0x03,0x5f,0xd6,0x00,0x00,0x80,0x52}}, // post_process_reset
 {0x7688e24,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // post_process_grain
 {0x7688ee8,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // post_process_dither
 {0x7662c80,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xb4,0x95,0x01,0xd0}}, // volume_instance
 {0x7663264,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // volume_create_stack
 {0x766345c,{0x61,0x00,0x00,0xb4,0xe0,0x03,0x01,0xaa,0x04,0x00,0x00,0x14,0xfd,0x7b,0xbf,0xa9}}, // volume_destroy_stack
 {0x76ac4e8,{0xff,0x83,0x01,0xd1,0xf8,0x5f,0x02,0xa9,0xf6,0x57,0x03,0xa9,0xf4,0x4f,0x04,0xa9}}, // volume_update_framework
 {0x7663e38,{0xff,0x03,0x01,0xd1,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xfd,0x7b,0x03,0xa9}}, // volume_stack_component
 {0x76632dc,{0x01,0x00,0x80,0xd2,0xe0,0x88,0xdc,0x17,0xfa,0x67,0xbb,0xa9,0xf8,0x5f,0x01,0xa9}}, // volume_stack_ctor
 {0x76632e4,{0xfa,0x67,0xbb,0xa9,0xf8,0x5f,0x01,0xa9,0xf6,0x57,0x02,0xa9,0xf4,0x4f,0x03,0xa9}}, // volume_stack_reload
 {0x7660970,{0xe9,0x23,0xbb,0x6d,0xf8,0x5f,0x01,0xa9,0xf6,0x57,0x02,0xa9,0xf4,0x4f,0x03,0xa9}}, // texture_curve_ctor
 {0x7660a9c,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // texture_curve_release
 {0x7660bc0,{0x28,0x20,0x80,0x52,0x08,0x70,0x00,0x79,0xc0,0x03,0x5f,0xd6,0xf4,0x4f,0xbe,0xa9}}, // texture_curve_set_dirty
 {0x77ec5ec,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x89,0x01,0xd0}}, // animation_curve_keys
 {0x77ec68c,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // animation_curve_set_keys
 {0x7858a04,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x33,0x86,0x01,0x90}}, // shader_variant_warmed
 {0x76a3750,{0x00,0x00,0x80,0x52,0xc0,0x03,0x5f,0xd6,0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9}}, // use_structured_buffer
 {0x3429918,{0xff,0x43,0x05,0xd1,0xfc,0x6f,0x0f,0xa9,0xfa,0x67,0x10,0xa9,0xf8,0x5f,0x11,0xa9}}, // cine_apply_postfx
 {0x3429c6c,{0xff,0xc3,0x01,0xd1,0xfc,0x6f,0x01,0xa9,0xfa,0x67,0x02,0xa9,0xf8,0x5f,0x03,0xa9}}, // cine_dynamic_volumes
 {0x78538cc,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // object_name
 {0x78550a0,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x33,0x86,0x01,0xf0}}, // object_hide_flags
 {0x7854d0c,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // object_destroy_immediate
 {0x784eaac,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // game_object_ctor_name
 {0x784e3d0,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x86,0x01,0xd0}}, // game_object_layer
 {0x784e380,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x86,0x01,0xd0}}, // game_object_transform
 {0x784e420,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // game_object_set_layer
 {0x784e5ec,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x86,0x01,0xd0}}, // object_active_hierarchy
 {0x7863a44,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x85,0x01,0xb0}}, // transform_children
 {0x786422c,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // transform_child
 {0x785f254,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x85,0x01,0xd0}}, // transform_parent
 {0x7860d84,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // transform_set_parent
 {0x6b6b488,{0x1f,0x00,0x01,0xeb,0xa0,0x01,0x00,0x54,0x08,0x00,0x80,0x52,0xc0,0x01,0x00,0xb4}}, // string_equal
 {0x76617d0,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}}, // volume_enable
 {0x766185c,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // volume_disable
 {0x76618f4,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}}, // volume_update
 {0x7b9df10,{0xff,0x83,0x02,0xd1,0xef,0x3b,0x02,0x6d,0xed,0x33,0x03,0x6d,0xeb,0x2b,0x04,0x6d}}, // focus_callback
 {0x6f99c54,{0xff,0x43,0x03,0xd1,0xeb,0x2b,0x08,0x6d,0xe9,0x23,0x09,0x6d,0xf6,0x57,0x0a,0xa9}}, // height_callback
 {0x6f8cd0c,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}}, // height_virtual_human
 {0x7850df4,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // scriptable_ctor
 {0x7850f60,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // scriptable_create_type
 {0x6f60894,{0xff,0x83,0x03,0xd1,0xef,0x3b,0x04,0x6d,0xed,0x33,0x05,0x6d,0xeb,0x2b,0x06,0x6d}}, // target_image_process
 {0x6f607d8,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // target_image_destroy
 {0x6f60ffc,{0xf8,0x5f,0xbc,0xa9,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xfd,0x7b,0x03,0xa9}}, // target_image_mixer
 {0x6f60660,{0xff,0x43,0x01,0xd1,0xf8,0x5f,0x01,0xa9,0xf6,0x57,0x02,0xa9,0xf4,0x4f,0x03,0xa9}}, // target_image_create
 {0x7b3dc88,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // raw_image_set_texture
 {0x7b3dd68,{0x04,0x38,0xc0,0x3d,0x05,0x1c,0xa0,0x4e,0x25,0x04,0x0c,0x6e,0x45,0x04,0x14,0x6e}}, // raw_image_set_uv
 {0x798e4a8,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}}, // graphic_set_color
 {0x7b743e8,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_clip
 {0x7b74438,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_set_clip
 {0x7b741cc,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_source
 {0x7b7421c,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_set_source
 {0x7b75d08,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0x90}}, // video_audio_mode
 {0x7b75d58,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_set_audio_mode
 {0x7b75874,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0x90}}, // video_audio_tracks
 {0x7b75a30,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0x90}}, // video_controlled_tracks
 {0x7b7449c,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_render_mode
 {0x7b744ec,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_set_render_mode
 {0x7b74c30,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_play_on_awake
 {0x7b74c80,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_set_play_on_awake
 {0x7b75220,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0x90}}, // video_loop
 {0x7b75270,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_set_loop
 {0x7b75590,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0x90}}, // video_skip
 {0x7b755e0,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_set_skip
 {0x7b74b7c,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_wait_first
 {0x7b74bcc,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_set_wait_first
 {0x7b74280,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_update_mode
 {0x7b742d0,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_set_update_mode
 {0x7b7516c,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0x90}}, // video_speed
 {0x7b751bc,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_set_speed
 {0x7b753d8,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0x90}}, // video_time_ref
 {0x7b75428,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_set_time_ref
 {0x7b74dd4,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_playing
 {0x7b74e24,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_paused
 {0x7b74b2c,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_prepared
 {0x7b74adc,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_prepare
 {0x7b74ec4,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_time
 {0x7b74f14,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_set_time
 {0x7b74f78,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_frame
 {0x7b74fc8,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_set_frame
 {0x7b754dc,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_set_external_reference_time
 {0x7825a74,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xb3,0x87,0x01,0xd0}}, // video_texture_width
 {0x7825b04,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xb3,0x87,0x01,0xd0}}, // video_texture_height
 {0x78258fc,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_texture_format
 {0x7825b94,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xb3,0x87,0x01,0xd0}}, // video_texture_dimension
 {0x78258ac,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xb3,0x87,0x01,0xd0}}, // video_texture_mips
 {0x780779c,{0xfa,0x67,0xbb,0xa9,0xf8,0x5f,0x01,0xa9,0xf6,0x57,0x02,0xa9,0xf4,0x4f,0x03,0xa9}}, // video_copy_mip
 {0x78343cc,{0xf8,0x5f,0xbc,0xa9,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xfd,0x7b,0x03,0xa9}}, // video_descriptor_ctor
 {0x7b74a8c,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_texture
 {0x7b74d34,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_pause
 {0x7b74d84,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_stop
 {0x7b750cc,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0x90}}, // video_step
 {0x7b76980,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x53,0x6d,0x01,0xf0}}, // video_send_frames
 {0x7b769d0,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_set_send_frames
 {0x7b73dd0,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xd0}}, // video_clip_frames
 {0x7b73e20,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xd0}}, // video_clip_rate
 {0x7b73e70,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xd0}}, // video_clip_length
 {0x7b74050,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x73,0x6d,0x01,0xb0}}, // video_clip_audio
 {0x6fbfe14,{0xff,0x03,0x01,0xd1,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xfd,0x7b,0x03,0xa9}}, // video_image_enable
 {0x6fbff20,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}}, // video_image_disable
 {0x6fbff50,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_image_late
 {0x7b3bd34,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}}, // maskable_image_enable
 {0x6f627c0,{0xff,0x83,0x01,0xd1,0xfa,0x67,0x01,0xa9,0xf8,0x5f,0x02,0xa9,0xf6,0x57,0x03,0xa9}}, // video_mixer_create
 {0x6f62190,{0xf8,0x5f,0xbc,0xa9,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xfd,0x7b,0x03,0xa9}}, // video_playable_create
 {0x6f623b0,{0xf8,0x5f,0xbc,0xa9,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xfd,0x7b,0x03,0xa9}}, // video_playable_destroy
 {0x6f618fc,{0xe9,0x23,0xba,0x6d,0xfa,0x67,0x01,0xa9,0xf8,0x5f,0x02,0xa9,0xf6,0x57,0x03,0xa9}}, // video_prepare_frame
 {0x6f61be0,{0xfa,0x67,0xbb,0xa9,0xf8,0x5f,0x01,0xa9,0xf6,0x57,0x02,0xa9,0xf4,0x4f,0x03,0xa9}}, // video_process_frame
 {0x6f613e0,{0xe9,0x23,0xbc,0x6d,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xfd,0x7b,0x03,0xa9}}, // video_update
 {0x6f6175c,{0xe9,0x23,0xbc,0x6d,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xfd,0x7b,0x03,0xa9}}, // video_sync
 {0x7891edc,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // playable_input_weight
 {0x6f61eac,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // video_stop_behaviour
 {0x7b76bac,{0x40,0x01,0x00,0xb4,0xe2,0x03,0x01,0xaa,0xe1,0x03,0x00,0xaa,0x08,0x28,0x40,0xf9}}, // video_frame_ready
 {0x7b76ca4,{0x20,0x01,0x00,0xb4,0xe1,0x03,0x00,0xaa,0x08,0x20,0x40,0xf9,0xa8,0x00,0x00,0xb4}}, // video_seek_completed
 {0x7b76b7c,{0x20,0x01,0x00,0xb4,0xe1,0x03,0x00,0xaa,0x08,0x0c,0x40,0xf9,0xa8,0x00,0x00,0xb4}}, // video_prepare_completed
 {0x784e10c,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // game_object_add_component
 {0x7849b64,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // game_object_get_component
 {0x7855050,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0x33,0x86,0x01,0xf0}}, // object_persist
 {0x78550f0,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}, // object_set_hide_flags
 {0x81ea684,{0x9a,0x6e,0x01,0x14,0x8a,0xd4,0x05,0x16,0x9a,0x6e,0x01,0x14,0x0e,0x6f,0x01,0x14}}, // field_offset
 {0x81ea67c,{0x99,0x6e,0x01,0x14,0x88,0xcd,0x3d,0x16,0x9a,0x6e,0x01,0x14,0x8a,0xd4,0x05,0x16}}, // field_flags
 {0x81e9f34,{0xf8,0x80,0x01,0x14,0x19,0x82,0x01,0x14,0x5e,0x81,0x01,0x14,0x56,0x82,0x01,0x14}}, // class_fields
 {0x81e9f64,{0x52,0x81,0x01,0x14,0x4a,0x82,0x01,0x14,0x08,0x28,0x40,0xb9,0x00,0x7d,0x1f,0x53}}, // class_size
 {0x81e9f84,{0x9a,0x82,0x01,0x14,0x00,0x18,0x41,0xb9,0xc0,0x03,0x5f,0xd6,0x08,0x60,0x44,0x39}}, // class_value_size
 {0x81e9f2c,{0x53,0x3e,0xb6,0x17,0xc1,0x80,0x01,0x14,0xf8,0x80,0x01,0x14,0x19,0x82,0x01,0x14}}, // class_element
 {0x81ea000,{0x00,0xc8,0x44,0x39,0xc0,0x03,0x5f,0xd6,0x00,0x0c,0x41,0xb9,0xc0,0x03,0x5f,0xd6}}, // class_rank
 {0x81e9f6c,{0x08,0x28,0x40,0xb9,0x00,0x7d,0x1f,0x53,0xc0,0x03,0x5f,0xd6,0x08,0xd8,0x44,0x39}}, // class_value_type
 {0x81e9fd4,{0x00,0x80,0x00,0x91,0xc0,0x03,0x5f,0xd6,0x00,0x1c,0x41,0xb9,0xc0,0x03,0x5f,0xd6}}, // class_type
 {0x81ea79c,{0xe0,0x03,0x01,0xaa,0xe1,0x03,0x02,0xaa,0x87,0x1f,0x2d,0x16,0x00,0x00,0x80,0x52}}, // write_barrier
 {0x81ea6a0,{0xb5,0x70,0x01,0x14,0xe0,0x70,0x01,0x14,0x08,0x04,0x40,0xf9,0x08,0x21,0x40,0x39}}, // field_static_get
 {0x81ea6a4,{0xe0,0x70,0x01,0x14,0x08,0x04,0x40,0xf9,0x08,0x21,0x40,0x39,0x00,0x19,0x06,0x53}}, // field_static_set
 {0x81ea8ec,{0x21,0x76,0x01,0x14,0xd9,0x6e,0x01,0x14,0xbd,0x77,0x01,0x14,0xbe,0x77,0x01,0x14}}, // runtime_invoke
};
struct FocusFactory {Binding shared,creator;uintptr_t method_cells[2],return_sites[2];Binding call_sites[2];};
inline constexpr FocusFactory android_focus_factory={{0x60993a8,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x08,0x1c,0x40,0xf9,0xf3,0x03,0x00,0xaa}},{0x9218a1c,{0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0x36,0x73,0x00,0xd0}},{0x9d03bf0,0x9d03be8},{0x9218a84,0x9218a90},{{0x9218a80,{0x4a,0x02,0x3a,0x97,0x60,0x0a,0x00,0xf9,0x80,0x02,0x40,0xf9,0x47,0x02,0x3a,0x97}},{0x9218a8c,{0x47,0x02,0x3a,0x97,0x68,0x0a,0x40,0xf9,0x28,0x04,0x00,0xb4,0xe1,0x03,0x00,0xaa}}}};
inline constexpr FocusFactory ios_focus_factory={{0x3bb24f8,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}},{0x7b9e220,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}},{0xa46f328,0xa46f320},{0x7b9e2a0,0x7b9e2ac},{{0x7b9e29c,{0x97,0x50,0x00,0x97,0x60,0x0a,0x00,0xf9,0xa0,0x02,0x40,0xf9,0x94,0x50,0x00,0x97}},{0x7b9e2a8,{0x94,0x50,0x00,0x97,0x68,0x0a,0x40,0xf9,0x28,0x08,0x00,0xb4,0xe1,0x03,0x00,0xaa}}}};
struct TypeName {const char* space;const char* leaf;};
struct TypeNames {
 TypeName tracker;
 TypeName target_cache;
 TypeName impulse_listener;
 TypeName impulse_source;
 TypeName impulse_independent;
 TypeName transform;
 TypeName impulse_manager;
 TypeName motion_data;
 TypeName post_process;
 TypeName post_shader_constants;
 TypeName renderer;
 TypeName renderer_data;
 TypeName post_data;
 TypeName compute_shader;
 TypeName post_library;
 TypeName lut_pass;
 TypeName compute_pass;
 TypeName shader_variants;
 TypeName forward_lights;
 TypeName cine_volume;
 TypeName volume;
 TypeName volume_profile;
 TypeName focus_extension;
 TypeName focus_state;
 TypeName focus_dof;
 TypeName height_extension;
 TypeName virtual_actor;
 TypeName component;
 TypeName material;
 TypeName shader;
 TypeName target_image_track;
 TypeName target_image_clip;
 TypeName target_image_mixer;
 TypeName target_image_behaviour;
 TypeName raw_image;
 TypeName rect_transform;
 TypeName video_player;
 TypeName video_clip;
 TypeName video_texture_2d;
 TypeName video_backup_rt;
 TypeName video_image;
 TypeName video_track;
 TypeName video_mixer;
 TypeName video_clip_asset;
 TypeName game_object;
};
inline constexpr TypeNames type_names={
 {"Cinemachine","UpdateTracker"}, // tracker
 {"Cinemachine","TargetPositionCache"}, // target_cache
 {"Cinemachine","CinemachineImpulseListener"}, // impulse_listener
 {"Cinemachine","CinemachineImpulseSource"}, // impulse_source
 {"Cinemachine","CinemachineIndependentImpulseListener"}, // impulse_independent
 {"UnityEngine","Transform"}, // transform
 {"Cinemachine","CinemachineImpulseManager"}, // impulse_manager
 {"UnityEngine.Rendering.Universal","MotionVectorsPersistentData"}, // motion_data
 {"VL.Rendering.Internal","VLPostProcessPass"}, // post_process
 {"","ShaderConstants"}, // post_shader_constants
 {"VL.Rendering","VLSRPRenderer"}, // renderer
 {"VL.Rendering","VLSRPRendererData"}, // renderer_data
 {"VL.Rendering","VLPostProcessData"}, // post_data
 {"UnityEngine","ComputeShader"}, // compute_shader
 {"","MaterialLibrary"}, // post_library
 {"UnityEngine.Rendering.Universal.Internal","ColorGradingLutPass"}, // lut_pass
 {"VL.Rendering","ColorGradingComputePass"}, // compute_pass
 {"UnityEngine","ShaderVariantCollection"}, // shader_variants
 {"UnityEngine.Rendering.Universal.Internal","ForwardLights"}, // forward_lights
 {"Cinemachine.PostFX","CinemachineVolumeSettings"}, // cine_volume
 {"UnityEngine.Rendering","Volume"}, // volume
 {"UnityEngine.Rendering","VolumeProfile"}, // volume_profile
 {"VL","VLCinemachineFocusPoint"}, // focus_extension
 {"","VcamFocusPointState"}, // focus_state
 {"VL.PostProcessing","VLDOF"}, // focus_dof
 {"Solis.Common","SolisCinemachineHeightController"}, // height_extension
 {"Solis.Common","SolisVirtualActorController"}, // virtual_actor
 {"UnityEngine","Component"}, // component
 {"UnityEngine","Material"}, // material
 {"UnityEngine","Shader"}, // shader
 {"Solis.Timeline","SolisTargetImageTrack"}, // target_image_track
 {"Solis.Timeline","SolisTargetImageClip"}, // target_image_clip
 {"Solis.Timeline","SolisTargetImageTrackBehaviour"}, // target_image_mixer
 {"Solis.Timeline","SolisTargetImageClipBehaviour"}, // target_image_behaviour
 {"UnityEngine.UI","RawImage"}, // raw_image
 {"UnityEngine","RectTransform"}, // rect_transform
 {"UnityEngine.Video","VideoPlayer"}, // video_player
 {"UnityEngine.Video","VideoClip"}, // video_clip
 {"UnityEngine","Texture2D"}, // video_texture_2d
 {"UnityEngine","RenderTexture"}, // video_backup_rt
 {"Solis.Common","VideoImage"}, // video_image
 {"Solis.Timeline","SolisVideoPlayerTrack"}, // video_track
 {"Solis.Timeline","SolisVideoPlayerTrackBehaviour"}, // video_mixer
 {"Solis.Timeline","SolisVideoPlayerClip"}, // video_clip_asset
 {"UnityEngine","GameObject"}, // game_object
};
struct Types {
 Binding tracker;
 Binding target_cache;
 Binding impulse_listener;
 Binding impulse_source;
 Binding impulse_independent;
 Binding transform;
 Binding impulse_manager;
 Binding motion_data;
 Binding post_process;
 Binding post_shader_constants;
 Binding renderer;
 Binding renderer_data;
 Binding post_data;
 Binding compute_shader;
 Binding post_library;
 Binding lut_pass;
 Binding compute_pass;
 Binding shader_variants;
 Binding forward_lights;
 Binding cine_volume;
 Binding volume;
 Binding volume_profile;
 Binding focus_extension;
 Binding focus_state;
 Binding focus_dof;
 Binding height_extension;
 Binding virtual_actor;
 Binding component;
 Binding material;
 Binding shader;
 Binding target_image_track;
 Binding target_image_clip;
 Binding target_image_mixer;
 Binding target_image_behaviour;
 Binding raw_image;
 Binding rect_transform;
 Binding video_player;
 Binding video_clip;
 Binding video_texture_2d;
 Binding video_backup_rt;
 Binding video_image;
 Binding video_track;
 Binding video_mixer;
 Binding video_clip_asset;
 Binding game_object;
};
inline constexpr Types android_types={
 {0x9dfe990,{0xd8,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // tracker
 {0x9df6970,{0xd5,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // target_cache
 {0x9da08d0,{0xe6,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // impulse_listener
 {0x9da0900,{0xee,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // impulse_source
 {0x9da0910,{0xef,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // impulse_independent
 {0x9d8c4f0,{0x05,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // transform
 {0x9da08e0,{0xed,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // impulse_manager
 {0x9dd48e0,{0x79,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // motion_data
 {0x9e00f60,{0x3e,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // post_process
 {0x9e51920,{0x3c,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // post_shader_constants
 {0x9e01080,{0x39,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // renderer
 {0x9e01090,{0x3a,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // renderer_data
 {0x9e00f40,{0x2f,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // post_data
 {0x9da3ed0,{0xec,0x5d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // compute_shader
 {0x9e51900,{0x3b,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // post_library
 {0x9da18b0,{0xea,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // lut_pass
 {0x9da1890,{0x1f,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // compute_pass
 {0x9debdb0,{0xf0,0x5d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // shader_variants
 {0x9db6200,{0xe6,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // forward_lights
 {0x9da0b80,{0xf3,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // cine_volume
 {0x9e02a40,{0xe6,0x6d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // volume
 {0x9e02b30,{0x16,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // volume_profile
 {0x9e00d10,{0x15,0x82,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // focus_extension
 {0x9e51830,{0x14,0x82,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // focus_state
 {0x9e00d30,{0x10,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // focus_dof
 {0x9df0e50,{0xd3,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // height_extension
 {0x9df1710,{0xa6,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // virtual_actor
 {0x9d870b0,{0xb2,0x5d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // component
 {0x9d89630,{0x1e,0x5d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // material
 {0x9debbb0,{0x1d,0x5d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // shader
 {0x9df1620,{0x1a,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // target_image_track
 {0x9df15f0,{0x18,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // target_image_clip
 {0x9df1630,{0x19,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // target_image_mixer
 {0x9df1600,{0x17,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // target_image_behaviour
 {0x9de4fa0,{0x77,0x6b,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // raw_image
 {0x9d8a870,{0x02,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // rect_transform
 {0x9e024e0,{0xb4,0x81,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_player
 {0x9e023b0,{0xa7,0x81,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_clip
 {0x9d8c170,{0x5b,0x5d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_texture_2d
 {0x9d8ab10,{0x60,0x5d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_backup_rt
 {0x9e02420,{0x5b,0x5b,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_image
 {0x9df16f0,{0x1d,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_track
 {0x9df1700,{0x1c,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_mixer
 {0x9df16e0,{0x1b,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_clip_asset
 {0x9d881e0,{0xbf,0x5d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // game_object
};
inline constexpr Types ios_types={
 {0xa568500,{0x09,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // tracker
 {0xa560490,{0x06,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // target_cache
 {0xa50a2e0,{0x17,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // impulse_listener
 {0xa50a310,{0x1f,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // impulse_source
 {0xa50a320,{0x20,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // impulse_independent
 {0xa4f60e0,{0x34,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // transform
 {0xa50a2f0,{0x1e,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // impulse_manager
 {0xa53e6f0,{0xaa,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // motion_data
 {0xa56ab40,{0x6f,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // post_process
 {0xa5bbe00,{0x6d,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // post_shader_constants
 {0xa56ac60,{0x6a,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // renderer
 {0xa56ac70,{0x6b,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // renderer_data
 {0xa56ab20,{0x60,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // post_data
 {0xa50d8d0,{0x1b,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // compute_shader
 {0xa5bbde0,{0x6c,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // post_library
 {0xa50b2c0,{0x1b,0x63,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // lut_pass
 {0xa50b2a0,{0x50,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // compute_pass
 {0xa555900,{0x1f,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // shader_variants
 {0xa51fc00,{0x17,0x63,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // forward_lights
 {0xa50a590,{0x24,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // cine_volume
 {0xa56c610,{0x17,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // volume
 {0xa56c700,{0x47,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // volume_profile
 {0xa56a8f0,{0x84,0x82,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // focus_extension
 {0xa5bbd10,{0x83,0x82,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // focus_state
 {0xa56a910,{0x41,0x62,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // focus_dof
 {0xa55a9a0,{0x01,0x5b,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // height_extension
 {0xa55b260,{0xd4,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // virtual_actor
 {0xa4f0c90,{0xe2,0x5d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // component
 {0xa4f3210,{0x4e,0x5d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // material
 {0xa555700,{0x4d,0x5d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // shader
 {0xa55b170,{0x48,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // target_image_track
 {0xa55b140,{0x46,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // target_image_clip
 {0xa55b180,{0x47,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // target_image_mixer
 {0xa55b150,{0x45,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // target_image_behaviour
 {0xa54ebb0,{0xa8,0x6b,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // raw_image
 {0xa4f4450,{0x31,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // rect_transform
 {0xa56c0c0,{0x23,0x82,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_player
 {0xa56bf90,{0x16,0x82,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_clip
 {0xa4f5d50,{0x8b,0x5d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_texture_2d
 {0xa4f46f0,{0x90,0x5d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_backup_rt
 {0xa56c000,{0x89,0x5b,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_image
 {0xa55b240,{0x4b,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_track
 {0xa55b250,{0x4a,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_mixer
 {0xa55b230,{0x49,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // video_clip_asset
 {0xa4f1dc0,{0xef,0x5d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00}}, // game_object
};
struct NativeAudio {const char*sha256;uint32_t cached_ptr,paused_offset,fast_flag,primary,supplementary_head,supplementary_tail,supplementary_count;Binding pause,unpause,playing;};
inline constexpr NativeAudio android_native_audio={"c36ea39e5040fbcd0577f7c49d08e149e2e7dc62449d90aadce761118a816c85",16,940,917,864,792,800,1024,{0x9393e4,{0x28,0x00,0x80,0x52,0x08,0xb0,0x0e,0x39,0x0a,0xdd,0xff,0x17,0xfe,0x0f,0x1c,0xf8}},{0x939030,{0x1f,0xb0,0x0e,0x39,0xf8,0xdd,0xff,0x17,0xff,0x83,0x02,0xd1,0xfe,0x3b,0x00,0xf9}},{0x9300fc,{0xff,0x83,0x00,0xd1,0xfe,0x4f,0x01,0xa9,0x08,0x54,0x4e,0x39,0xa8,0x00,0x00,0x34}}};
inline constexpr NativeAudio ios_native_audio={"b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf",16,940,917,864,792,800,1024,{0xf90740,{0x28,0x00,0x80,0x52,0x08,0xb0,0x0e,0x39,0x1d,0xdc,0xff,0x17,0xf8,0x5f,0xbc,0xa9}},{0xf90374,{0x1f,0xb0,0x0e,0x39,0x11,0xdd,0xff,0x17,0xff,0x83,0x02,0xd1,0xf6,0x57,0x07,0xa9}},{0xf8707c,{0xff,0xc3,0x00,0xd1,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}}};
struct NativeCamera {const char*sha256;uint32_t cached_ptr,automatic_aspect_offset;Binding reset,set,projection,reset_store,set_store;};
inline constexpr NativeCamera android_native_camera={"c36ea39e5040fbcd0577f7c49d08e149e2e7dc62449d90aadce761118a816c85",16,1314,{0xbe5da8,{0xe9,0x23,0xbd,0x6d,0xfe,0x0b,0x00,0xf9,0xf4,0x4f,0x02,0xa9,0xe1,0x03,0x1f,0x2a}},{0xbe8828,{0xe9,0x23,0xbe,0x6d,0xfe,0x4f,0x01,0xa9,0x08,0x14,0x45,0xb9,0x29,0x20,0x80,0x52}},{0xbf4b44,{0x28,0x00,0x80,0x52,0x29,0x20,0x80,0x52,0x08,0x14,0x05,0xb9,0x09,0x20,0x0a,0x79}},{0xbe5e6c,{0x74,0x8a,0x14,0x39,0xe1,0x06,0x00,0x54,0x68,0x3a,0x40,0xf9,0x69,0x12,0x24,0x91}},{0xbe8844,{0x1f,0x88,0x14,0x39,0x01,0x07,0x00,0x54,0x08,0x38,0x40,0xf9,0x09,0x10,0x24,0x91}}};
inline constexpr NativeCamera ios_native_camera={"b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf",16,1314,{0x11b8730,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}},{0x11bb360,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}},{0x11c87b4,{0x28,0x00,0x80,0x52,0x08,0x14,0x05,0xb9,0x29,0x20,0x80,0x52,0x09,0x20,0x0a,0x79}},{0x11b87f8,{0x74,0x8a,0x14,0x39,0x68,0x16,0x45,0xb9,0x1f,0x09,0x00,0x71,0xe1,0x06,0x00,0x54}},{0x11bb37c,{0x1f,0x88,0x14,0x39,0x08,0x14,0x45,0xb9,0x1f,0x09,0x00,0x71,0x01,0x07,0x00,0x54}}};
struct Layout {
 static constexpr uint32_t brain_frames=0x78;
 static constexpr uint32_t brain_next_id=0x80;
 static constexpr uint32_t brain_current_blend=0x88;
 static constexpr uint32_t brain_previous=0x90;
 static constexpr uint32_t brain_state=0x98;
 static constexpr uint32_t core_status=0x30;
 static constexpr uint32_t core_fixed_frame=0x4c;
 static constexpr uint32_t mixer_brain=0x10;
 static constexpr uint32_t mixer_id=0x18;
};
struct Schema {const char*name;const char*space;const char*leaf;uint32_t definition,begin,bytes;uintptr_t type_rva;uint8_t type_prefix[16];const uint32_t*refs;uint32_t references;int32_t identity,next_id,last_frame,window_frame;};
inline constexpr uint32_t android_refs_0[]={0,8,16,24};
inline constexpr uint32_t android_refs_2[]={0,8,24};
inline constexpr uint32_t android_refs_4[]={0};
inline constexpr uint32_t android_refs_10[]={0,8,16,32};
inline constexpr uint32_t android_refs_11[]={0};
inline constexpr uint32_t android_refs_12[]={0,8,16};
inline constexpr uint32_t android_refs_13[]={0,8};
inline constexpr uint32_t android_refs_15[]={0,8,24};
inline constexpr uint32_t android_refs_24[]={16,32};
inline constexpr uint32_t android_refs_25[]={0};
inline constexpr uint32_t android_refs_26[]={0};
inline constexpr uint32_t android_refs_27[]={0};
inline constexpr uint32_t android_refs_28[]={0,8,24,40};
inline constexpr uint32_t android_refs_29[]={0,8,48,64,80,88,104,112,120,128,288,304,320,336,352,376};
inline constexpr uint32_t android_refs_32[]={8,16,24};
inline constexpr uint32_t android_refs_33[]={8,16};
inline constexpr uint32_t android_refs_34[]={8,32,40,48,56,64,72,80,88,104,112,272,288,304,320,336};
inline constexpr uint32_t android_refs_36[]={0,8,48,64,80,88,104,136,144,152,312,328,344,360,376,400,408,424,432};
inline constexpr uint32_t android_refs_37[]={40};
inline constexpr uint32_t android_refs_38[]={0,8,24,80,88};
inline constexpr uint32_t android_refs_40[]={0,8,24,32,40,56};
inline constexpr uint32_t android_refs_41[]={0};
inline constexpr uint32_t android_refs_42[]={0,8,48,64,80,88,248,264,280,296,312,328};
inline constexpr uint32_t android_refs_44[]={0,8};
inline constexpr uint32_t android_refs_47[]={0,8,48,64,80,88,160,200,264,336,400,464,632,648,664,680,696,712,720,728,736,752,768,776,784};
inline constexpr uint32_t android_refs_48[]={0,8,48,64,264,280,296,312,328,344,352,360,368,376};
inline constexpr uint32_t android_refs_49[]={8,16,24,56};
inline constexpr uint32_t android_refs_51[]={0,8};
inline constexpr uint32_t android_refs_52[]={8,16,24,56,64,72};
inline constexpr uint32_t android_refs_53[]={0,8,48,64,80,88,96,112,120,136,144,152,160,168,328,344,360,376,392,408,432,464,480,488,496,504};
inline constexpr uint32_t android_refs_54[]={0,8,16,24};
inline constexpr uint32_t android_refs_55[]={0,8,24,80};
inline constexpr uint32_t android_refs_57[]={16};
inline constexpr uint32_t android_refs_61[]={0,8,48,64,80,88,152,320,336,352,368,384,400,408,416,424};
inline constexpr uint32_t android_refs_62[]={0,8,16,24,32,40,48,96};
inline constexpr uint32_t android_refs_63[]={0,8,16,24,32,40,48,56};
inline constexpr uint32_t android_refs_64[]={0,8,16,24,32,40,48,184};
inline constexpr uint32_t android_refs_65[]={0,8,16,24,32,40,48,192};
inline constexpr uint32_t android_refs_66[]={0,8,16,24,32,40,48,184};
inline constexpr uint32_t android_refs_67[]={0,8,16,24,32,40,48};
inline constexpr uint32_t android_refs_68[]={0,8,16,24,32,40,48};
inline constexpr uint32_t android_refs_71[]={0,8,16,24,32,40,48,168,240,304,336,360,368,376};
inline constexpr uint32_t android_refs_72[]={0,8,16,24,32,40,48,88,152,224,288};
inline constexpr uint32_t android_refs_73[]={0,8,16,24,32,40,48};
inline constexpr uint32_t android_refs_74[]={0,8,16,24,32,40,48,56};
inline constexpr uint32_t android_refs_75[]={0,8,16,24,32,40,48,168};
inline constexpr uint32_t android_refs_77[]={0,8,16};
inline constexpr uint32_t android_refs_78[]={0,16,24,184,200,216,232,248};
inline constexpr uint32_t android_refs_79[]={0,16,24,184,200,216,232,248};
inline constexpr uint32_t android_refs_80[]={0};
inline constexpr uint32_t android_refs_81[]={0,8,16,24,32,40,48};
inline constexpr uint32_t android_refs_85[]={0,8,16,24,32};
inline constexpr uint32_t android_refs_86[]={0,8};
inline constexpr uint32_t android_refs_88[]={8,16,24};
inline constexpr uint32_t android_refs_100[]={0,8,48,64};
inline constexpr uint32_t android_refs_102[]={0,8};
inline constexpr uint32_t android_refs_106[]={8};
inline constexpr uint32_t android_refs_107[]={0,8};
inline constexpr uint32_t android_refs_112[]={8,16,40,64,80,104,112};
inline constexpr uint32_t android_refs_113[]={32};
inline constexpr uint32_t android_refs_114[]={0,16,32,40};
inline constexpr uint32_t android_refs_115[]={0,8,16};
inline constexpr uint32_t android_refs_117[]={0};
inline constexpr uint32_t android_refs_118[]={8,32,40};
inline constexpr uint32_t android_refs_119[]={0,8};
inline constexpr uint32_t android_refs_122[]={8,16,40};
inline constexpr uint32_t android_refs_123[]={0,8};
inline constexpr uint32_t android_refs_124[]={0};
inline constexpr uint32_t android_refs_126[]={0,8};
inline constexpr uint32_t android_refs_127[]={0};
inline constexpr uint32_t android_refs_128[]={0,8,24,40};
inline constexpr uint32_t android_refs_137[]={0};
inline constexpr uint32_t android_refs_142[]={0,8,24};
inline constexpr Schema android_schemas[]={
 {"Solis.Common.SolisCinemachineHeightController","Solis.Common","SolisCinemachineHeightController",23251,32,32,0x9df0e50,{0xd3,0x5a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_0,4,-1,-1,-1,-1},
 {"UnityEngine.Events.UnityEventTools","UnityEngine.Events","UnityEventTools",24098,16,0,0x9dfde90,{0x22,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"UnityEngine.Events.ArgumentCache","UnityEngine.Events","ArgumentCache",24099,16,40,0x9d95dd0,{0x23,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_2,3,-1,-1,-1,-1},
 {"UnityEngine.Events.BaseInvokableCall","UnityEngine.Events","BaseInvokableCall",24100,16,0,0x9d9a000,{0x24,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"UnityEngine.Events.InvokableCall","UnityEngine.Events","InvokableCall",24101,16,8,0x9dc4df0,{0x25,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_4,1,-1,-1,-1,-1},
 {"UnityEngine.Events.PersistentCall","UnityEngine.Events","PersistentCall",24108,16,48,0x9dda3a0,{0x2c,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_10,4,-1,-1,-1,-1},
 {"UnityEngine.Events.PersistentCallGroup","UnityEngine.Events","PersistentCallGroup",24109,16,8,0x9dda3b0,{0x2d,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_11,1,-1,-1,-1,-1},
 {"UnityEngine.Events.InvokableCallList","UnityEngine.Events","InvokableCallList",24110,16,32,0x9dc4e00,{0x2e,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_12,3,-1,-1,-1,-1},
 {"UnityEngine.Events.UnityEventBase","UnityEngine.Events","UnityEventBase",24111,16,24,0x9dfde40,{0x2f,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_13,2,-1,-1,-1,-1},
 {"UnityEngine.Events.UnityEvent","UnityEngine.Events","UnityEvent",24113,16,32,0x9d8cd80,{0x31,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_15,3,-1,-1,-1,-1},
 {"UnityEngine.Rendering.Volume","UnityEngine.Rendering","Volume",28134,32,40,0x9e02a40,{0xe6,0x6d,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_24,2,-1,-1,-1,-1},
 {"UnityEngine.Rendering.VolumeProfile","UnityEngine.Rendering","VolumeProfile",28182,24,16,0x9e02b30,{0x16,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_25,1,-1,-1,-1,-1},
 {".CinemachineMixer","","CinemachineMixer",28232,16,16,0x9da0940,{0x48,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_26,1,-1,-1,-1,-1},
 {".CinemachineShotPlayable","","CinemachineShotPlayable",28234,16,8,0x9da0a40,{0x4a,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_27,1,-1,-1,-1,-1},
 {"Cinemachine.Cinemachine3rdPersonAim","Cinemachine","Cinemachine3rdPersonAim",28238,32,48,0x9da0610,{0x4e,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_28,4,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBlendListCamera","Cinemachine","CinemachineBlendListCamera",28240,32,384,0x9da0670,{0x50,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_29,16,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBrain/BrainEvent","","BrainEvent",28243,48,0,0x9e12a90,{0x53,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBrain/VcamActivatedEvent","","VcamActivatedEvent",28244,48,0,0x9e12b30,{0x54,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBrain/BrainFrame","","BrainFrame",28245,16,40,0x9e12ac0,{0x55,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_32,3,0,-1,-1,-1},
 {"Cinemachine.CinemachineBrain/<AfterPhysics>d__32","","<AfterPhysics>d__32",28246,16,24,0x9e12a80,{0x56,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_33,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBrain","Cinemachine","CinemachineBrain",28247,32,352,0x9da06c0,{0x57,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_34,16,-1,96,-1,-1},
 {"Cinemachine.CinemachineClearShot/<>c","","<>c",28249,16,0,0x9e12b50,{0x59,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineClearShot","Cinemachine","CinemachineClearShot",28250,32,440,0x9da0710,{0x5a,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_36,19,-1,-1,-1,-1},
 {"Cinemachine.CinemachineCollider/VcamExtraState","","VcamExtraState",28252,16,56,0x9d8df50,{0x5c,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_37,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineCollider","Cinemachine","CinemachineCollider",28253,32,96,0x9da0720,{0x5d,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_38,5,-1,-1,-1,-1},
 {"Cinemachine.CinemachineConfiner/VcamExtraState","","VcamExtraState",28255,16,24,0x9e12c00,{0x5f,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineConfiner","Cinemachine","CinemachineConfiner",28256,32,72,0x9da0770,{0x60,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_40,6,-1,-1,-1,-1},
 {"Cinemachine.CinemachineDollyCart","Cinemachine","CinemachineDollyCart",28258,32,24,0x9da07b0,{0x62,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_41,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineExternalCamera","Cinemachine","CinemachineExternalCamera",28259,32,344,0x9da07e0,{0x63,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_42,12,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFollowZoom/VcamExtraState","","VcamExtraState",28260,16,8,0x9e12d10,{0x64,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFollowZoom","Cinemachine","CinemachineFollowZoom",28261,32,32,0x9da0800,{0x65,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_44,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFreeLook","Cinemachine","CinemachineFreeLook",28265,32,792,0x9da0820,{0x69,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_47,25,-1,-1,-1,-1},
 {"Cinemachine.CinemachineMixingCamera","Cinemachine","CinemachineMixingCamera",28266,32,384,0x9da0950,{0x6a,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_48,14,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePath","Cinemachine","CinemachinePath",28268,32,64,0x9da0990,{0x6c,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_49,4,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePipeline","Cinemachine","CinemachinePipeline",28269,32,0,0x9da09e0,{0x6d,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePixelPerfect","Cinemachine","CinemachinePixelPerfect",28270,32,16,0x9da09f0,{0x6e,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_51,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachineSmoothPath","Cinemachine","CinemachineSmoothPath",28272,32,88,0x9da0a50,{0x70,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_52,6,-1,-1,-1,-1},
 {"Cinemachine.CinemachineStateDrivenCamera","Cinemachine","CinemachineStateDrivenCamera",28276,32,512,0x9da0a60,{0x74,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_53,26,-1,-1,-1,-1},
 {"Cinemachine.CinemachineStoryboard/CanvasInfo","","CanvasInfo",28278,16,32,0x9e13000,{0x76,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_54,4,-1,-1,-1,-1},
 {"Cinemachine.CinemachineStoryboard","Cinemachine","CinemachineStoryboard",28279,32,88,0x9da0a70,{0x77,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_55,4,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTargetGroup","Cinemachine","CinemachineTargetGroup",28285,32,64,0x9da0a80,{0x7d,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_57,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineVirtualCamera/<>c","","<>c",28288,16,0,0x9e131b0,{0x80,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineVirtualCamera","Cinemachine","CinemachineVirtualCamera",28289,32,432,0x9da0b10,{0x81,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_61,16,-1,-1,-1,-1},
 {"Cinemachine.Cinemachine3rdPersonFollow","Cinemachine","Cinemachine3rdPersonFollow",28290,32,128,0x9da0620,{0x82,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_62,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBasicMultiChannelPerlin","Cinemachine","CinemachineBasicMultiChannelPerlin",28291,32,104,0x9da0630,{0x83,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_63,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineComposer","Cinemachine","CinemachineComposer",28293,32,272,0x9da0750,{0x85,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_64,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFramingTransposer","Cinemachine","CinemachineFramingTransposer",28296,32,328,0x9da0810,{0x88,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_65,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineGroupComposer","Cinemachine","CinemachineGroupComposer",28299,32,416,0x9da0840,{0x8b,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_66,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineHardLockToTarget","Cinemachine","CinemachineHardLockToTarget",28300,32,72,0x9da0850,{0x8c,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_67,7,-1,-1,-1,-1},
 {"Cinemachine.CinemachineHardLookAt","Cinemachine","CinemachineHardLookAt",28301,32,56,0x9da0860,{0x8d,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_68,7,-1,-1,-1,-1},
 {"Cinemachine.CinemachineOrbitalTransposer/<>c","","<>c",28305,16,0,0x9e12eb0,{0x91,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineOrbitalTransposer","Cinemachine","CinemachineOrbitalTransposer",28306,32,400,0x9da0970,{0x92,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_71,14,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePOV","Cinemachine","CinemachinePOV",28308,32,336,0x9da0980,{0x94,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_72,11,-1,-1,-1,-1},
 {"Cinemachine.CinemachineSameAsFollowTarget","Cinemachine","CinemachineSameAsFollowTarget",28309,32,80,0x9da0a20,{0x95,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_73,7,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTrackedDolly","Cinemachine","CinemachineTrackedDolly",28312,32,160,0x9da0ac0,{0x98,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_74,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTransposer","Cinemachine","CinemachineTransposer",28315,32,176,0x9da0ae0,{0x9b,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_75,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBlend","Cinemachine","CinemachineBlend",28323,16,32,0x9d86d20,{0xa3,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_77,3,-1,-1,-1,-1},
 {"Cinemachine.StaticPointVirtualCamera","Cinemachine","StaticPointVirtualCamera",28326,16,264,0x9df36b0,{0xa6,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_78,8,-1,-1,-1,-1},
 {"Cinemachine.BlendSourceVirtualCamera","Cinemachine","BlendSourceVirtualCamera",28327,16,264,0x9d9b3f0,{0xa7,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_79,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBlenderSettings","Cinemachine","CinemachineBlenderSettings",28329,24,8,0x9da0680,{0xa9,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_80,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineComponentBase","Cinemachine","CinemachineComponentBase",28330,32,56,0x9da0740,{0xaa,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_81,7,-1,-1,-1,-1},
 {"Cinemachine.CinemachineCore/UpdateStatus","","UpdateStatus",28334,16,16,0x9e12cb0,{0xae,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,0,-1},
 {"Cinemachine.CinemachineCore","Cinemachine","CinemachineCore",28336,16,48,0x9da0780,{0xb0,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_85,5,-1,-1,-1,-1},
 {"Cinemachine.CinemachineExtension","Cinemachine","CinemachineExtension",28337,32,16,0x9da07d0,{0xb1,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_86,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePathBase/Appearance","","Appearance",28340,16,40,0x9e12f60,{0xb4,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePathBase","Cinemachine","CinemachinePathBase",28342,32,48,0x9da09b0,{0xb6,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_88,3,-1,-1,-1,-1},
 {"Cinemachine.AxisStatePropertyAttribute","Cinemachine","AxisStatePropertyAttribute",28343,16,0,0x9d97f10,{0xb7,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.OrbitalTransposerHeadingPropertyAttribute","Cinemachine","OrbitalTransposerHeadingPropertyAttribute",28344,16,0,0x9dd8580,{0xb8,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.LensSettingsPropertyAttribute","Cinemachine","LensSettingsPropertyAttribute",28345,16,0,0x9dc82c0,{0xb9,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.VcamTargetPropertyAttribute","Cinemachine","VcamTargetPropertyAttribute",28346,16,0,0x9e017d0,{0xba,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBlendDefinitionPropertyAttribute","Cinemachine","CinemachineBlendDefinitionPropertyAttribute",28347,16,0,0x9da0660,{0xbb,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.SaveDuringPlayAttribute","Cinemachine","SaveDuringPlayAttribute",28348,16,0,0x9de9ef0,{0xbc,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.NoSaveDuringPlayAttribute","Cinemachine","NoSaveDuringPlayAttribute",28349,16,0,0x9dd6110,{0xbd,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.TagFieldAttribute","Cinemachine","TagFieldAttribute",28350,16,0,0x9df6670,{0xbe,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.NoiseSettingsPropertyAttribute","Cinemachine","NoiseSettingsPropertyAttribute",28351,16,0,0x9dd6210,{0xbf,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineEmbeddedAssetPropertyAttribute","Cinemachine","CinemachineEmbeddedAssetPropertyAttribute",28352,16,8,0x9da07c0,{0xc0,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.DocumentationSortingAttribute","Cinemachine","DocumentationSortingAttribute",28354,16,8,0x9dac8e0,{0xc2,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineVirtualCameraBase","Cinemachine","CinemachineVirtualCameraBase",28358,32,80,0x9da0b50,{0xc6,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_100,4,-1,-1,-1,-1},
 {"Cinemachine.NoiseSettings","Cinemachine","NoiseSettings",28363,24,16,0x9dd61f0,{0xcb,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_102,2,-1,-1,-1,-1},
 {"Cinemachine.RuntimeUtility","Cinemachine","RuntimeUtility",28364,16,0,0x9de9190,{0xcc,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.SignalSourceAsset","Cinemachine","SignalSourceAsset",28366,24,0,0x9def340,{0xce,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.TargetPositionCache/CacheCurve","","CacheCurve",28369,16,16,0x9e4a740,{0xd1,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_106,1,-1,-1,-1,-1},
 {"Cinemachine.TargetPositionCache/CacheEntry","","CacheEntry",28371,16,48,0x9e4a760,{0xd3,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_107,2,-1,-1,-1,-1},
 {"Cinemachine.TargetPositionCache","Cinemachine","TargetPositionCache",28373,16,0,0x9df6970,{0xd5,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.UpdateTracker/UpdateStatus","","UpdateStatus",28375,16,88,0x9e50060,{0xd7,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,16,0},
 {"Cinemachine.UpdateTracker","Cinemachine","UpdateTracker",28376,16,0,0x9dfe990,{0xd8,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineInputProvider","Cinemachine","CinemachineInputProvider",28377,32,0,0x9da0930,{0xd9,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTriggerAction","Cinemachine","CinemachineTriggerAction",28382,32,120,0x9da0af0,{0xde,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_112,7,-1,-1,-1,-1},
 {"Cinemachine.GroupWeightManipulator","Cinemachine","GroupWeightManipulator",28383,32,40,0x9db9900,{0xdf,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_113,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineCollisionImpulseSource","Cinemachine","CinemachineCollisionImpulseSource",28384,32,48,0x9da0730,{0xe0,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_114,4,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFixedSignal","Cinemachine","CinemachineFixedSignal",28385,24,24,0x9da07f0,{0xe1,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_115,3,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseDefinitionPropertyAttribute","Cinemachine","CinemachineImpulseDefinitionPropertyAttribute",28386,16,0,0x9da08b0,{0xe2,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseDefinition/SignalSource","","SignalSource",28388,16,24,0x9e12e60,{0xe4,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_117,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseDefinition","Cinemachine","CinemachineImpulseDefinition",28389,16,88,0x9da0880,{0xe5,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_118,3,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseListener","Cinemachine","CinemachineImpulseListener",28390,32,32,0x9da08d0,{0xe6,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_119,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseEnvelopePropertyAttribute","Cinemachine","CinemachineImpulseEnvelopePropertyAttribute",28391,16,0,0x9da08c0,{0xe7,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseChannelPropertyAttribute","Cinemachine","CinemachineImpulseChannelPropertyAttribute",28392,16,0,0x9da0870,{0xe8,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseManager/ImpulseEvent","","ImpulseEvent",28396,16,88,0x9e12e90,{0xec,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_122,3,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseManager","Cinemachine","CinemachineImpulseManager",28397,16,24,0x9da08e0,{0xed,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_123,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseSource","Cinemachine","CinemachineImpulseSource",28398,32,8,0x9da0900,{0xee,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_124,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineIndependentImpulseListener","Cinemachine","CinemachineIndependentImpulseListener",28399,32,40,0x9da0910,{0xef,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.PostFX.CinemachinePostProcessing","Cinemachine.PostFX","CinemachinePostProcessing",28400,32,16,0x9da0a00,{0xf0,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_126,2,-1,-1,-1,-1},
 {"Cinemachine.PostFX.CinemachineVolumeSettings/VcamExtraState","","VcamExtraState",28402,16,8,0x9e132b0,{0xf2,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_127,1,-1,-1,-1,-1},
 {"Cinemachine.PostFX.CinemachineVolumeSettings","Cinemachine.PostFX","CinemachineVolumeSettings",28403,32,48,0x9da0b80,{0xf3,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_128,4,-1,-1,-1,-1},
 {"Cinemachine.Utility.CinemachineDebug","Cinemachine.Utility","CinemachineDebug",28405,16,0,0x9da07a0,{0xf5,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.GaussianWindow1D_Vector3","Cinemachine.Utility","GaussianWindow1D_Vector3",28407,40,0,0x9db8110,{0xf7,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.GaussianWindow1D_Quaternion","Cinemachine.Utility","GaussianWindow1D_Quaternion",28408,40,0,0x9db8100,{0xf8,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.GaussianWindow1D_CameraRotation","Cinemachine.Utility","GaussianWindow1D_CameraRotation",28409,40,0,0x9db80f0,{0xf9,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.PositionPredictor","Cinemachine.Utility","PositionPredictor",28410,16,48,0x9ddfd50,{0xfa,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.Damper","Cinemachine.Utility","Damper",28411,16,0,0x9da7930,{0xfb,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.HeadingTracker","Cinemachine.Utility","HeadingTracker",28413,16,56,0x9dbb0b0,{0xfd,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_137,1,-1,-1,-1,-1},
 {"Cinemachine.Utility.SplineHelpers","Cinemachine.Utility","SplineHelpers",28414,16,0,0x9df24e0,{0xfe,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.UnityVectorExtensions","Cinemachine.Utility","UnityVectorExtensions",28415,16,0,0x9dfe400,{0xff,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.UnityQuaternionExtensions","Cinemachine.Utility","UnityQuaternionExtensions",28416,16,0,0x9dfdfd0,{0x00,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.UnityRectExtensions","Cinemachine.Utility","UnityRectExtensions",28417,16,0,0x9dfdfe0,{0x01,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"VL.VLCinemachineFocusPoint","VL","VLCinemachineFocusPoint",33301,32,32,0x9e00d10,{0x15,0x82,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},android_refs_142,3,-1,-1,-1,-1},
};
inline constexpr uint32_t ios_refs_0[]={0,8,16,24};
inline constexpr uint32_t ios_refs_2[]={0,8,24};
inline constexpr uint32_t ios_refs_4[]={0};
inline constexpr uint32_t ios_refs_10[]={0,8,16,32};
inline constexpr uint32_t ios_refs_11[]={0};
inline constexpr uint32_t ios_refs_12[]={0,8,16};
inline constexpr uint32_t ios_refs_13[]={0,8};
inline constexpr uint32_t ios_refs_15[]={0,8,24};
inline constexpr uint32_t ios_refs_24[]={16,32};
inline constexpr uint32_t ios_refs_25[]={0};
inline constexpr uint32_t ios_refs_26[]={0};
inline constexpr uint32_t ios_refs_27[]={0};
inline constexpr uint32_t ios_refs_28[]={0,8,24,40};
inline constexpr uint32_t ios_refs_29[]={0,8,48,64,80,88,104,112,120,128,288,304,320,336,352,376};
inline constexpr uint32_t ios_refs_32[]={8,16,24};
inline constexpr uint32_t ios_refs_33[]={8,16};
inline constexpr uint32_t ios_refs_34[]={8,32,40,48,56,64,72,80,88,104,112,272,288,304,320,336};
inline constexpr uint32_t ios_refs_36[]={0,8,48,64,80,88,104,136,144,152,312,328,344,360,376,400,408,424,432};
inline constexpr uint32_t ios_refs_37[]={40};
inline constexpr uint32_t ios_refs_38[]={0,8,24,80,88};
inline constexpr uint32_t ios_refs_40[]={0,8,24,32,40,56};
inline constexpr uint32_t ios_refs_41[]={0};
inline constexpr uint32_t ios_refs_42[]={0,8,48,64,80,88,248,264,280,296,312,328};
inline constexpr uint32_t ios_refs_44[]={0,8};
inline constexpr uint32_t ios_refs_47[]={0,8,48,64,80,88,160,200,264,336,400,464,632,648,664,680,696,712,720,728,736,752,768,776,784};
inline constexpr uint32_t ios_refs_48[]={0,8,48,64,264,280,296,312,328,344,352,360,368,376};
inline constexpr uint32_t ios_refs_49[]={8,16,24,56};
inline constexpr uint32_t ios_refs_51[]={0,8};
inline constexpr uint32_t ios_refs_52[]={8,16,24,56,64,72};
inline constexpr uint32_t ios_refs_53[]={0,8,48,64,80,88,96,112,120,136,144,152,160,168,328,344,360,376,392,408,432,464,480,488,496,504};
inline constexpr uint32_t ios_refs_54[]={0,8,16,24};
inline constexpr uint32_t ios_refs_55[]={0,8,24,80};
inline constexpr uint32_t ios_refs_57[]={16};
inline constexpr uint32_t ios_refs_61[]={0,8,48,64,80,88,152,320,336,352,368,384,400,408,416,424};
inline constexpr uint32_t ios_refs_62[]={0,8,16,24,32,40,48,96};
inline constexpr uint32_t ios_refs_63[]={0,8,16,24,32,40,48,56};
inline constexpr uint32_t ios_refs_64[]={0,8,16,24,32,40,48,184};
inline constexpr uint32_t ios_refs_65[]={0,8,16,24,32,40,48,192};
inline constexpr uint32_t ios_refs_66[]={0,8,16,24,32,40,48,184};
inline constexpr uint32_t ios_refs_67[]={0,8,16,24,32,40,48};
inline constexpr uint32_t ios_refs_68[]={0,8,16,24,32,40,48};
inline constexpr uint32_t ios_refs_71[]={0,8,16,24,32,40,48,168,240,304,336,360,368,376};
inline constexpr uint32_t ios_refs_72[]={0,8,16,24,32,40,48,88,152,224,288};
inline constexpr uint32_t ios_refs_73[]={0,8,16,24,32,40,48};
inline constexpr uint32_t ios_refs_74[]={0,8,16,24,32,40,48,56};
inline constexpr uint32_t ios_refs_75[]={0,8,16,24,32,40,48,168};
inline constexpr uint32_t ios_refs_77[]={0,8,16};
inline constexpr uint32_t ios_refs_78[]={0,16,24,184,200,216,232,248};
inline constexpr uint32_t ios_refs_79[]={0,16,24,184,200,216,232,248};
inline constexpr uint32_t ios_refs_80[]={0};
inline constexpr uint32_t ios_refs_81[]={0,8,16,24,32,40,48};
inline constexpr uint32_t ios_refs_85[]={0,8,16,24,32};
inline constexpr uint32_t ios_refs_86[]={0,8};
inline constexpr uint32_t ios_refs_88[]={8,16,24};
inline constexpr uint32_t ios_refs_100[]={0,8,48,64};
inline constexpr uint32_t ios_refs_102[]={0,8};
inline constexpr uint32_t ios_refs_106[]={8};
inline constexpr uint32_t ios_refs_107[]={0,8};
inline constexpr uint32_t ios_refs_112[]={8,16,40,64,80,104,112};
inline constexpr uint32_t ios_refs_113[]={32};
inline constexpr uint32_t ios_refs_114[]={0,16,32,40};
inline constexpr uint32_t ios_refs_115[]={0,8,16};
inline constexpr uint32_t ios_refs_117[]={0};
inline constexpr uint32_t ios_refs_118[]={8,32,40};
inline constexpr uint32_t ios_refs_119[]={0,8};
inline constexpr uint32_t ios_refs_122[]={8,16,40};
inline constexpr uint32_t ios_refs_123[]={0,8};
inline constexpr uint32_t ios_refs_124[]={0};
inline constexpr uint32_t ios_refs_126[]={0,8};
inline constexpr uint32_t ios_refs_127[]={0};
inline constexpr uint32_t ios_refs_128[]={0,8,24,40};
inline constexpr uint32_t ios_refs_137[]={0};
inline constexpr uint32_t ios_refs_142[]={0,8,24};
inline constexpr Schema ios_schemas[]={
 {"Solis.Common.SolisCinemachineHeightController","Solis.Common","SolisCinemachineHeightController",23297,32,32,0xa55a9a0,{0x01,0x5b,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_0,4,-1,-1,-1,-1},
 {"UnityEngine.Events.UnityEventTools","UnityEngine.Events","UnityEventTools",24145,16,0,0xa5679f0,{0x51,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"UnityEngine.Events.ArgumentCache","UnityEngine.Events","ArgumentCache",24146,16,40,0xa4ff790,{0x52,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_2,3,-1,-1,-1,-1},
 {"UnityEngine.Events.BaseInvokableCall","UnityEngine.Events","BaseInvokableCall",24147,16,0,0xa503a20,{0x53,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"UnityEngine.Events.InvokableCall","UnityEngine.Events","InvokableCall",24148,16,8,0xa52e820,{0x54,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_4,1,-1,-1,-1,-1},
 {"UnityEngine.Events.PersistentCall","UnityEngine.Events","PersistentCall",24155,16,48,0xa544000,{0x5b,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_10,4,-1,-1,-1,-1},
 {"UnityEngine.Events.PersistentCallGroup","UnityEngine.Events","PersistentCallGroup",24156,16,8,0xa544010,{0x5c,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_11,1,-1,-1,-1,-1},
 {"UnityEngine.Events.InvokableCallList","UnityEngine.Events","InvokableCallList",24157,16,32,0xa52e830,{0x5d,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_12,3,-1,-1,-1,-1},
 {"UnityEngine.Events.UnityEventBase","UnityEngine.Events","UnityEventBase",24158,16,24,0xa5679a0,{0x5e,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_13,2,-1,-1,-1,-1},
 {"UnityEngine.Events.UnityEvent","UnityEngine.Events","UnityEvent",24160,16,32,0xa4f6970,{0x60,0x5e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_15,3,-1,-1,-1,-1},
 {"UnityEngine.Rendering.Volume","UnityEngine.Rendering","Volume",28183,32,40,0xa56c610,{0x17,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_24,2,-1,-1,-1,-1},
 {"UnityEngine.Rendering.VolumeProfile","UnityEngine.Rendering","VolumeProfile",28231,24,16,0xa56c700,{0x47,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_25,1,-1,-1,-1,-1},
 {".CinemachineMixer","","CinemachineMixer",28281,16,16,0xa50a350,{0x79,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_26,1,-1,-1,-1,-1},
 {".CinemachineShotPlayable","","CinemachineShotPlayable",28283,16,8,0xa50a450,{0x7b,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_27,1,-1,-1,-1,-1},
 {"Cinemachine.Cinemachine3rdPersonAim","Cinemachine","Cinemachine3rdPersonAim",28287,32,48,0xa50a020,{0x7f,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_28,4,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBlendListCamera","Cinemachine","CinemachineBlendListCamera",28289,32,384,0xa50a080,{0x81,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_29,16,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBrain/BrainEvent","","BrainEvent",28292,48,0,0xa57c9b0,{0x84,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBrain/VcamActivatedEvent","","VcamActivatedEvent",28293,48,0,0xa57ca50,{0x85,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBrain/BrainFrame","","BrainFrame",28294,16,40,0xa57c9e0,{0x86,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_32,3,0,-1,-1,-1},
 {"Cinemachine.CinemachineBrain/<AfterPhysics>d__32","","<AfterPhysics>d__32",28295,16,24,0xa57c9a0,{0x87,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_33,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBrain","Cinemachine","CinemachineBrain",28296,32,352,0xa50a0d0,{0x88,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_34,16,-1,96,-1,-1},
 {"Cinemachine.CinemachineClearShot/<>c","","<>c",28298,16,0,0xa57ca70,{0x8a,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineClearShot","Cinemachine","CinemachineClearShot",28299,32,440,0xa50a120,{0x8b,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_36,19,-1,-1,-1,-1},
 {"Cinemachine.CinemachineCollider/VcamExtraState","","VcamExtraState",28301,16,56,0xa4f7af0,{0x8d,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_37,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineCollider","Cinemachine","CinemachineCollider",28302,32,96,0xa50a130,{0x8e,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_38,5,-1,-1,-1,-1},
 {"Cinemachine.CinemachineConfiner/VcamExtraState","","VcamExtraState",28304,16,24,0xa57cb20,{0x90,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineConfiner","Cinemachine","CinemachineConfiner",28305,32,72,0xa50a180,{0x91,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_40,6,-1,-1,-1,-1},
 {"Cinemachine.CinemachineDollyCart","Cinemachine","CinemachineDollyCart",28307,32,24,0xa50a1c0,{0x93,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_41,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineExternalCamera","Cinemachine","CinemachineExternalCamera",28308,32,344,0xa50a1f0,{0x94,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_42,12,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFollowZoom/VcamExtraState","","VcamExtraState",28309,16,8,0xa57cc30,{0x95,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFollowZoom","Cinemachine","CinemachineFollowZoom",28310,32,32,0xa50a210,{0x96,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_44,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFreeLook","Cinemachine","CinemachineFreeLook",28314,32,792,0xa50a230,{0x9a,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_47,25,-1,-1,-1,-1},
 {"Cinemachine.CinemachineMixingCamera","Cinemachine","CinemachineMixingCamera",28315,32,384,0xa50a360,{0x9b,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_48,14,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePath","Cinemachine","CinemachinePath",28317,32,64,0xa50a3a0,{0x9d,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_49,4,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePipeline","Cinemachine","CinemachinePipeline",28318,32,0,0xa50a3f0,{0x9e,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePixelPerfect","Cinemachine","CinemachinePixelPerfect",28319,32,16,0xa50a400,{0x9f,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_51,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachineSmoothPath","Cinemachine","CinemachineSmoothPath",28321,32,88,0xa50a460,{0xa1,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_52,6,-1,-1,-1,-1},
 {"Cinemachine.CinemachineStateDrivenCamera","Cinemachine","CinemachineStateDrivenCamera",28325,32,512,0xa50a470,{0xa5,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_53,26,-1,-1,-1,-1},
 {"Cinemachine.CinemachineStoryboard/CanvasInfo","","CanvasInfo",28327,16,32,0xa57cf20,{0xa7,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_54,4,-1,-1,-1,-1},
 {"Cinemachine.CinemachineStoryboard","Cinemachine","CinemachineStoryboard",28328,32,88,0xa50a480,{0xa8,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_55,4,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTargetGroup","Cinemachine","CinemachineTargetGroup",28334,32,64,0xa50a490,{0xae,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_57,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineVirtualCamera/<>c","","<>c",28337,16,0,0xa57d0d0,{0xb1,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineVirtualCamera","Cinemachine","CinemachineVirtualCamera",28338,32,432,0xa50a520,{0xb2,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_61,16,-1,-1,-1,-1},
 {"Cinemachine.Cinemachine3rdPersonFollow","Cinemachine","Cinemachine3rdPersonFollow",28339,32,128,0xa50a030,{0xb3,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_62,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBasicMultiChannelPerlin","Cinemachine","CinemachineBasicMultiChannelPerlin",28340,32,104,0xa50a040,{0xb4,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_63,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineComposer","Cinemachine","CinemachineComposer",28342,32,272,0xa50a160,{0xb6,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_64,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFramingTransposer","Cinemachine","CinemachineFramingTransposer",28345,32,328,0xa50a220,{0xb9,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_65,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineGroupComposer","Cinemachine","CinemachineGroupComposer",28348,32,416,0xa50a250,{0xbc,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_66,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineHardLockToTarget","Cinemachine","CinemachineHardLockToTarget",28349,32,72,0xa50a260,{0xbd,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_67,7,-1,-1,-1,-1},
 {"Cinemachine.CinemachineHardLookAt","Cinemachine","CinemachineHardLookAt",28350,32,56,0xa50a270,{0xbe,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_68,7,-1,-1,-1,-1},
 {"Cinemachine.CinemachineOrbitalTransposer/<>c","","<>c",28354,16,0,0xa57cdd0,{0xc2,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineOrbitalTransposer","Cinemachine","CinemachineOrbitalTransposer",28355,32,400,0xa50a380,{0xc3,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_71,14,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePOV","Cinemachine","CinemachinePOV",28357,32,336,0xa50a390,{0xc5,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_72,11,-1,-1,-1,-1},
 {"Cinemachine.CinemachineSameAsFollowTarget","Cinemachine","CinemachineSameAsFollowTarget",28358,32,80,0xa50a430,{0xc6,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_73,7,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTrackedDolly","Cinemachine","CinemachineTrackedDolly",28361,32,160,0xa50a4d0,{0xc9,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_74,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTransposer","Cinemachine","CinemachineTransposer",28364,32,176,0xa50a4f0,{0xcc,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_75,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBlend","Cinemachine","CinemachineBlend",28372,16,32,0xa4f0900,{0xd4,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_77,3,-1,-1,-1,-1},
 {"Cinemachine.StaticPointVirtualCamera","Cinemachine","StaticPointVirtualCamera",28375,16,264,0xa55d1d0,{0xd7,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_78,8,-1,-1,-1,-1},
 {"Cinemachine.BlendSourceVirtualCamera","Cinemachine","BlendSourceVirtualCamera",28376,16,264,0xa504e00,{0xd8,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_79,8,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBlenderSettings","Cinemachine","CinemachineBlenderSettings",28378,24,8,0xa50a090,{0xda,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_80,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineComponentBase","Cinemachine","CinemachineComponentBase",28379,32,56,0xa50a150,{0xdb,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_81,7,-1,-1,-1,-1},
 {"Cinemachine.CinemachineCore/UpdateStatus","","UpdateStatus",28383,16,16,0xa57cbd0,{0xdf,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,0,-1},
 {"Cinemachine.CinemachineCore","Cinemachine","CinemachineCore",28385,16,48,0xa50a190,{0xe1,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_85,5,-1,-1,-1,-1},
 {"Cinemachine.CinemachineExtension","Cinemachine","CinemachineExtension",28386,32,16,0xa50a1e0,{0xe2,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_86,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePathBase/Appearance","","Appearance",28389,16,40,0xa57ce80,{0xe5,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePathBase","Cinemachine","CinemachinePathBase",28391,32,48,0xa50a3c0,{0xe7,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_88,3,-1,-1,-1,-1},
 {"Cinemachine.AxisStatePropertyAttribute","Cinemachine","AxisStatePropertyAttribute",28392,16,0,0xa501930,{0xe8,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.OrbitalTransposerHeadingPropertyAttribute","Cinemachine","OrbitalTransposerHeadingPropertyAttribute",28393,16,0,0xa542250,{0xe9,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.LensSettingsPropertyAttribute","Cinemachine","LensSettingsPropertyAttribute",28394,16,0,0xa531d30,{0xea,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.VcamTargetPropertyAttribute","Cinemachine","VcamTargetPropertyAttribute",28395,16,0,0xa56b3b0,{0xeb,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBlendDefinitionPropertyAttribute","Cinemachine","CinemachineBlendDefinitionPropertyAttribute",28396,16,0,0xa50a070,{0xec,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.SaveDuringPlayAttribute","Cinemachine","SaveDuringPlayAttribute",28397,16,0,0xa553a50,{0xed,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.NoSaveDuringPlayAttribute","Cinemachine","NoSaveDuringPlayAttribute",28398,16,0,0xa53ff20,{0xee,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.TagFieldAttribute","Cinemachine","TagFieldAttribute",28399,16,0,0xa560190,{0xef,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.NoiseSettingsPropertyAttribute","Cinemachine","NoiseSettingsPropertyAttribute",28400,16,0,0xa540020,{0xf0,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineEmbeddedAssetPropertyAttribute","Cinemachine","CinemachineEmbeddedAssetPropertyAttribute",28401,16,8,0xa50a1d0,{0xf1,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.DocumentationSortingAttribute","Cinemachine","DocumentationSortingAttribute",28403,16,8,0xa5162e0,{0xf3,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineVirtualCameraBase","Cinemachine","CinemachineVirtualCameraBase",28407,32,80,0xa50a560,{0xf7,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_100,4,-1,-1,-1,-1},
 {"Cinemachine.NoiseSettings","Cinemachine","NoiseSettings",28412,24,16,0xa540000,{0xfc,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_102,2,-1,-1,-1,-1},
 {"Cinemachine.RuntimeUtility","Cinemachine","RuntimeUtility",28413,16,0,0xa552ce0,{0xfd,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.SignalSourceAsset","Cinemachine","SignalSourceAsset",28415,24,0,0xa558e90,{0xff,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.TargetPositionCache/CacheCurve","","CacheCurve",28418,16,16,0xa5b4c40,{0x02,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_106,1,-1,-1,-1,-1},
 {"Cinemachine.TargetPositionCache/CacheEntry","","CacheEntry",28420,16,48,0xa5b4c60,{0x04,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_107,2,-1,-1,-1,-1},
 {"Cinemachine.TargetPositionCache","Cinemachine","TargetPositionCache",28422,16,0,0xa560490,{0x06,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.UpdateTracker/UpdateStatus","","UpdateStatus",28424,16,88,0xa5ba540,{0x08,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,16,0},
 {"Cinemachine.UpdateTracker","Cinemachine","UpdateTracker",28425,16,0,0xa568500,{0x09,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineInputProvider","Cinemachine","CinemachineInputProvider",28426,32,0,0xa50a340,{0x0a,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTriggerAction","Cinemachine","CinemachineTriggerAction",28431,32,120,0xa50a500,{0x0f,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_112,7,-1,-1,-1,-1},
 {"Cinemachine.GroupWeightManipulator","Cinemachine","GroupWeightManipulator",28432,32,40,0xa523300,{0x10,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_113,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineCollisionImpulseSource","Cinemachine","CinemachineCollisionImpulseSource",28433,32,48,0xa50a140,{0x11,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_114,4,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFixedSignal","Cinemachine","CinemachineFixedSignal",28434,24,24,0xa50a200,{0x12,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_115,3,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseDefinitionPropertyAttribute","Cinemachine","CinemachineImpulseDefinitionPropertyAttribute",28435,16,0,0xa50a2c0,{0x13,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseDefinition/SignalSource","","SignalSource",28437,16,24,0xa57cd80,{0x15,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_117,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseDefinition","Cinemachine","CinemachineImpulseDefinition",28438,16,88,0xa50a290,{0x16,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_118,3,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseListener","Cinemachine","CinemachineImpulseListener",28439,32,32,0xa50a2e0,{0x17,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_119,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseEnvelopePropertyAttribute","Cinemachine","CinemachineImpulseEnvelopePropertyAttribute",28440,16,0,0xa50a2d0,{0x18,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseChannelPropertyAttribute","Cinemachine","CinemachineImpulseChannelPropertyAttribute",28441,16,0,0xa50a280,{0x19,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseManager/ImpulseEvent","","ImpulseEvent",28445,16,88,0xa57cdb0,{0x1d,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_122,3,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseManager","Cinemachine","CinemachineImpulseManager",28446,16,24,0xa50a2f0,{0x1e,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_123,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseSource","Cinemachine","CinemachineImpulseSource",28447,32,8,0xa50a310,{0x1f,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_124,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineIndependentImpulseListener","Cinemachine","CinemachineIndependentImpulseListener",28448,32,40,0xa50a320,{0x20,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.PostFX.CinemachinePostProcessing","Cinemachine.PostFX","CinemachinePostProcessing",28449,32,16,0xa50a410,{0x21,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_126,2,-1,-1,-1,-1},
 {"Cinemachine.PostFX.CinemachineVolumeSettings/VcamExtraState","","VcamExtraState",28451,16,8,0xa57d1d0,{0x23,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_127,1,-1,-1,-1,-1},
 {"Cinemachine.PostFX.CinemachineVolumeSettings","Cinemachine.PostFX","CinemachineVolumeSettings",28452,32,48,0xa50a590,{0x24,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_128,4,-1,-1,-1,-1},
 {"Cinemachine.Utility.CinemachineDebug","Cinemachine.Utility","CinemachineDebug",28454,16,0,0xa50a1b0,{0x26,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.GaussianWindow1D_Vector3","Cinemachine.Utility","GaussianWindow1D_Vector3",28456,40,0,0xa521b30,{0x28,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.GaussianWindow1D_Quaternion","Cinemachine.Utility","GaussianWindow1D_Quaternion",28457,40,0,0xa521b20,{0x29,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.GaussianWindow1D_CameraRotation","Cinemachine.Utility","GaussianWindow1D_CameraRotation",28458,40,0,0xa521b10,{0x2a,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.PositionPredictor","Cinemachine.Utility","PositionPredictor",28459,16,48,0xa549920,{0x2b,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.Damper","Cinemachine.Utility","Damper",28460,16,0,0xa511310,{0x2c,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.HeadingTracker","Cinemachine.Utility","HeadingTracker",28462,16,56,0xa524ab0,{0x2e,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_137,1,-1,-1,-1,-1},
 {"Cinemachine.Utility.SplineHelpers","Cinemachine.Utility","SplineHelpers",28463,16,0,0xa55c030,{0x2f,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.UnityVectorExtensions","Cinemachine.Utility","UnityVectorExtensions",28464,16,0,0xa567f50,{0x30,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.UnityQuaternionExtensions","Cinemachine.Utility","UnityQuaternionExtensions",28465,16,0,0xa567b20,{0x31,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.UnityRectExtensions","Cinemachine.Utility","UnityRectExtensions",28466,16,0,0xa567b30,{0x32,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"VL.VLCinemachineFocusPoint","VL","VLCinemachineFocusPoint",33412,32,32,0xa56a8f0,{0x84,0x82,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x12,0x00,0x00,0x00,0x00,0x00},ios_refs_142,3,-1,-1,-1,-1},
};
inline constexpr uint32_t android_value_refs_0[]={0,24};
inline constexpr uint32_t android_value_refs_10[]={8};
inline constexpr uint32_t android_value_refs_14[]={0};
inline constexpr uint32_t android_value_refs_31[]={24,88};
inline constexpr uint32_t android_value_refs_33[]={0};
inline constexpr uint32_t android_value_refs_34[]={152,168,184,200,216};
inline constexpr uint32_t android_value_refs_36[]={8};
inline constexpr uint32_t android_value_refs_37[]={0,8,24};
inline constexpr uint32_t android_value_refs_41[]={16};
inline constexpr uint32_t android_value_refs_46[]={8};
inline constexpr uint32_t android_value_refs_53[]={8,32};
inline constexpr uint32_t android_value_refs_55[]={0,8};
inline constexpr Schema android_values[]={
 {"Cinemachine.CinemachineBlendListCamera/Instruction","","Instruction",28239,0,32,0x9e12a60,{0x4f,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},android_value_refs_0,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBrain/UpdateMethod","","UpdateMethod",28241,0,4,0x9e12b00,{0x51,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBrain/BrainUpdateMethod","","BrainUpdateMethod",28242,0,4,0x9e12ad0,{0x52,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineClearShot/Pair","","Pair",28248,0,8,0x9e12b70,{0x58,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineCollider/ResolutionStrategy","","ResolutionStrategy",28251,0,4,0x9e12b80,{0x5b,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineConfiner/Mode","","Mode",28254,0,4,0x9e12bd0,{0x5e,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineDollyCart/UpdateMethod","","UpdateMethod",28257,0,4,0x9e12ce0,{0x61,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFreeLook/Orbit","","Orbit",28262,0,8,0x9e12dc0,{0x66,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePath/Waypoint","","Waypoint",28267,0,28,0x9e12f50,{0x6b,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineSmoothPath/Waypoint","","Waypoint",28271,0,16,0x9e12fb0,{0x6f,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineStateDrivenCamera/Instruction","","Instruction",28273,0,24,0x9e12fd0,{0x71,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},android_value_refs_10,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineStateDrivenCamera/ParentHash","","ParentHash",28274,0,8,0x9e12ff0,{0x72,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineStateDrivenCamera/HashPair","","HashPair",28275,0,8,0x9e12fc0,{0x73,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineStoryboard/FillStrategy","","FillStrategy",28277,0,4,0x9e13010,{0x75,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTargetGroup/Target","","Target",28281,0,16,0x9e130a0,{0x79,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},android_value_refs_14,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTargetGroup/PositionMode","","PositionMode",28282,0,4,0x9e13040,{0x7a,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTargetGroup/RotationMode","","RotationMode",28283,0,4,0x9e13070,{0x7b,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTargetGroup/UpdateMethod","","UpdateMethod",28284,0,4,0x9e130b0,{0x7c,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineComposer/FovCache","","FovCache",28292,0,80,0x9e12bb0,{0x84,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFramingTransposer/FramingMode","","FramingMode",28294,0,4,0x9e12d50,{0x86,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFramingTransposer/AdjustmentMode","","AdjustmentMode",28295,0,4,0x9e12d20,{0x87,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineGroupComposer/FramingMode","","FramingMode",28297,0,4,0x9e12e00,{0x89,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineGroupComposer/AdjustmentMode","","AdjustmentMode",28298,0,4,0x9e12dd0,{0x8a,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineOrbitalTransposer/Heading","","Heading",28303,0,12,0x9e12ed0,{0x8f,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePOV/RecenterTargetMode","","RecenterTargetMode",28307,0,4,0x9e12f20,{0x93,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTrackedDolly/CameraUpMode","","CameraUpMode",28310,0,4,0x9e13100,{0x96,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTrackedDolly/AutoDolly","","AutoDolly",28311,0,16,0x9e130e0,{0x97,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTransposer/BindingMode","","BindingMode",28313,0,4,0x9e13160,{0x99,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTransposer/AngularDampingMode","","AngularDampingMode",28314,0,4,0x9e13130,{0x9a,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.AxisState/SpeedMode","","SpeedMode",28316,0,4,0x9e0d810,{0x9c,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.AxisState/Recentering","","Recentering",28318,0,28,0x9d8dd60,{0x9e,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.AxisState","Cinemachine","AxisState",28319,0,104,0x9d86190,{0x9f,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},android_value_refs_31,2,-1,-1,-1,-1},
 {"Cinemachine.CameraState/BlendHintValue","","BlendHintValue",28320,0,4,0x9e103e0,{0xa0,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CameraState/CustomBlendable","","CustomBlendable",28321,0,16,0x9e10410,{0xa1,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},android_value_refs_33,1,-1,-1,-1,-1},
 {"Cinemachine.CameraState","Cinemachine","CameraState",28322,0,232,0x9d86930,{0xa2,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},android_value_refs_34,5,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBlendDefinition/Style","","Style",28324,0,4,0x9e12a30,{0xa4,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBlendDefinition","Cinemachine","CinemachineBlendDefinition",28325,0,16,0x9da0640,{0xa5,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},android_value_refs_36,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBlenderSettings/CustomBlend","","CustomBlend",28328,0,32,0x9e12a70,{0xa8,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},android_value_refs_37,3,-1,-1,-1,-1},
 {"Cinemachine.CinemachineCore/Stage","","Stage",28331,0,4,0x9e12c50,{0xab,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineCore/UpdateFilter","","UpdateFilter",28335,0,4,0x9e12c80,{0xaf,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.AxisBase","Cinemachine","AxisBase",28338,0,16,0x9d86170,{0xb2,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineInputAxisDriver","Cinemachine","CinemachineInputAxisDriver",28339,0,32,0x9da0920,{0xb3,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},android_value_refs_41,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePathBase/PositionUnits","","PositionUnits",28341,0,4,0x9e12f80,{0xb5,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.DocumentationSortingAttribute/Level","","Level",28353,0,4,0x9e1ba10,{0xc1,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineVirtualCameraBase/StandbyUpdateMode","","StandbyUpdateMode",28355,0,4,0x9e13250,{0xc3,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineVirtualCameraBase/BlendHint","","BlendHint",28356,0,4,0x9e13210,{0xc4,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineVirtualCameraBase/TransitionParams","","TransitionParams",28357,0,16,0x9d8df70,{0xc5,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},android_value_refs_46,1,-1,-1,-1,-1},
 {"Cinemachine.LensSettings","Cinemachine","LensSettings",28360,0,48,0x9d89280,{0xc8,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.NoiseSettings/NoiseParams","","NoiseParams",28361,0,12,0x9e33e10,{0xc9,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.NoiseSettings/TransformNoiseParams","","TransformNoiseParams",28362,0,36,0x9e33e30,{0xca,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.TargetPositionCache/Mode","","Mode",28367,0,4,0x9e4a770,{0xcf,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.TargetPositionCache/TimeRange","","TimeRange",28372,0,8,0x9e4a7a0,{0xd4,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.UpdateTracker/UpdateClock","","UpdateClock",28374,0,4,0x9e50020,{0xd6,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTriggerAction/ActionSettings","","ActionSettings",28381,0,40,0x9e13190,{0xdd,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},android_value_refs_53,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseDefinition/RepeatMode","","RepeatMode",28387,0,4,0x9e12e30,{0xe3,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseManager/EnvelopeDefinition","","EnvelopeDefinition",28393,0,32,0x9e12e70,{0xe9,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},android_value_refs_55,2,-1,-1,-1,-1},
 {"Cinemachine.PostFX.CinemachineVolumeSettings/FocusTrackingMode","","FocusTrackingMode",28401,0,4,0x9e13280,{0xf1,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.HeadingTracker/Item","","Item",28412,0,20,0x9e25460,{0xfc,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
};
inline constexpr uint32_t ios_value_refs_0[]={0,24};
inline constexpr uint32_t ios_value_refs_10[]={8};
inline constexpr uint32_t ios_value_refs_14[]={0};
inline constexpr uint32_t ios_value_refs_31[]={24,88};
inline constexpr uint32_t ios_value_refs_33[]={0};
inline constexpr uint32_t ios_value_refs_34[]={152,168,184,200,216};
inline constexpr uint32_t ios_value_refs_36[]={8};
inline constexpr uint32_t ios_value_refs_37[]={0,8,24};
inline constexpr uint32_t ios_value_refs_41[]={16};
inline constexpr uint32_t ios_value_refs_46[]={8};
inline constexpr uint32_t ios_value_refs_53[]={8,32};
inline constexpr uint32_t ios_value_refs_55[]={0,8};
inline constexpr Schema ios_values[]={
 {"Cinemachine.CinemachineBlendListCamera/Instruction","","Instruction",28288,0,32,0xa57c980,{0x80,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},ios_value_refs_0,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBrain/UpdateMethod","","UpdateMethod",28290,0,4,0xa57ca20,{0x82,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBrain/BrainUpdateMethod","","BrainUpdateMethod",28291,0,4,0xa57c9f0,{0x83,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineClearShot/Pair","","Pair",28297,0,8,0xa57ca90,{0x89,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineCollider/ResolutionStrategy","","ResolutionStrategy",28300,0,4,0xa57caa0,{0x8c,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineConfiner/Mode","","Mode",28303,0,4,0xa57caf0,{0x8f,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineDollyCart/UpdateMethod","","UpdateMethod",28306,0,4,0xa57cc00,{0x92,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFreeLook/Orbit","","Orbit",28311,0,8,0xa57cce0,{0x97,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePath/Waypoint","","Waypoint",28316,0,28,0xa57ce70,{0x9c,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineSmoothPath/Waypoint","","Waypoint",28320,0,16,0xa57ced0,{0xa0,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineStateDrivenCamera/Instruction","","Instruction",28322,0,24,0xa57cef0,{0xa2,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},ios_value_refs_10,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineStateDrivenCamera/ParentHash","","ParentHash",28323,0,8,0xa57cf10,{0xa3,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineStateDrivenCamera/HashPair","","HashPair",28324,0,8,0xa57cee0,{0xa4,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineStoryboard/FillStrategy","","FillStrategy",28326,0,4,0xa57cf30,{0xa6,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTargetGroup/Target","","Target",28330,0,16,0xa57cfc0,{0xaa,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},ios_value_refs_14,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTargetGroup/PositionMode","","PositionMode",28331,0,4,0xa57cf60,{0xab,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTargetGroup/RotationMode","","RotationMode",28332,0,4,0xa57cf90,{0xac,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTargetGroup/UpdateMethod","","UpdateMethod",28333,0,4,0xa57cfd0,{0xad,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineComposer/FovCache","","FovCache",28341,0,80,0xa57cad0,{0xb5,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFramingTransposer/FramingMode","","FramingMode",28343,0,4,0xa57cc70,{0xb7,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineFramingTransposer/AdjustmentMode","","AdjustmentMode",28344,0,4,0xa57cc40,{0xb8,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineGroupComposer/FramingMode","","FramingMode",28346,0,4,0xa57cd20,{0xba,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineGroupComposer/AdjustmentMode","","AdjustmentMode",28347,0,4,0xa57ccf0,{0xbb,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineOrbitalTransposer/Heading","","Heading",28352,0,12,0xa57cdf0,{0xc0,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePOV/RecenterTargetMode","","RecenterTargetMode",28356,0,4,0xa57ce40,{0xc4,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTrackedDolly/CameraUpMode","","CameraUpMode",28359,0,4,0xa57d020,{0xc7,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTrackedDolly/AutoDolly","","AutoDolly",28360,0,16,0xa57d000,{0xc8,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTransposer/BindingMode","","BindingMode",28362,0,4,0xa57d080,{0xca,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTransposer/AngularDampingMode","","AngularDampingMode",28363,0,4,0xa57d050,{0xcb,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.AxisState/SpeedMode","","SpeedMode",28365,0,4,0xa577650,{0xcd,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.AxisState/Recentering","","Recentering",28367,0,28,0xa4f7900,{0xcf,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.AxisState","Cinemachine","AxisState",28368,0,104,0xa4efd70,{0xd0,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},ios_value_refs_31,2,-1,-1,-1,-1},
 {"Cinemachine.CameraState/BlendHintValue","","BlendHintValue",28369,0,4,0xa57a300,{0xd1,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CameraState/CustomBlendable","","CustomBlendable",28370,0,16,0xa57a330,{0xd2,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},ios_value_refs_33,1,-1,-1,-1,-1},
 {"Cinemachine.CameraState","Cinemachine","CameraState",28371,0,232,0xa4f0510,{0xd3,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},ios_value_refs_34,5,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBlendDefinition/Style","","Style",28373,0,4,0xa57c950,{0xd5,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBlendDefinition","Cinemachine","CinemachineBlendDefinition",28374,0,16,0xa50a050,{0xd6,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},ios_value_refs_36,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachineBlenderSettings/CustomBlend","","CustomBlend",28377,0,32,0xa57c990,{0xd9,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},ios_value_refs_37,3,-1,-1,-1,-1},
 {"Cinemachine.CinemachineCore/Stage","","Stage",28380,0,4,0xa57cb70,{0xdc,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineCore/UpdateFilter","","UpdateFilter",28384,0,4,0xa57cba0,{0xe0,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.AxisBase","Cinemachine","AxisBase",28387,0,16,0xa4efd50,{0xe3,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineInputAxisDriver","Cinemachine","CinemachineInputAxisDriver",28388,0,32,0xa50a330,{0xe4,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},ios_value_refs_41,1,-1,-1,-1,-1},
 {"Cinemachine.CinemachinePathBase/PositionUnits","","PositionUnits",28390,0,4,0xa57cea0,{0xe6,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.DocumentationSortingAttribute/Level","","Level",28402,0,4,0xa585910,{0xf2,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineVirtualCameraBase/StandbyUpdateMode","","StandbyUpdateMode",28404,0,4,0xa57d170,{0xf4,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineVirtualCameraBase/BlendHint","","BlendHint",28405,0,4,0xa57d130,{0xf5,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineVirtualCameraBase/TransitionParams","","TransitionParams",28406,0,16,0xa4f7b10,{0xf6,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},ios_value_refs_46,1,-1,-1,-1,-1},
 {"Cinemachine.LensSettings","Cinemachine","LensSettings",28409,0,48,0xa4f2e60,{0xf9,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.NoiseSettings/NoiseParams","","NoiseParams",28410,0,12,0xa59e1b0,{0xfa,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.NoiseSettings/TransformNoiseParams","","TransformNoiseParams",28411,0,36,0xa59e1d0,{0xfb,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.TargetPositionCache/Mode","","Mode",28416,0,4,0xa5b4c70,{0x00,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.TargetPositionCache/TimeRange","","TimeRange",28421,0,8,0xa5b4ca0,{0x05,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.UpdateTracker/UpdateClock","","UpdateClock",28423,0,4,0xa5ba500,{0x07,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineTriggerAction/ActionSettings","","ActionSettings",28430,0,40,0xa57d0b0,{0x0e,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},ios_value_refs_53,2,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseDefinition/RepeatMode","","RepeatMode",28436,0,4,0xa57cd50,{0x14,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.CinemachineImpulseManager/EnvelopeDefinition","","EnvelopeDefinition",28442,0,32,0xa57cd90,{0x1a,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},ios_value_refs_55,2,-1,-1,-1,-1},
 {"Cinemachine.PostFX.CinemachineVolumeSettings/FocusTrackingMode","","FocusTrackingMode",28450,0,4,0xa57d1a0,{0x22,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
 {"Cinemachine.Utility.HeadingTracker/Item","","Item",28461,0,20,0xa58f390,{0x2d,0x6f,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x11,0x80,0x00,0x00,0x00,0x00},nullptr,0,-1,-1,-1,-1},
};
} // namespace idoly_mp4_camera_profile
// END_ORIGINAL_CAMERA_STATE_PROFILE

// BEGIN_MP4_VIDEO_FRAME
// A private paused VideoPlayer receives exact frame requests. These receipts
// describe the original Unity frame-ready/seek events, observed only after the
// original native transfer's scripting-invocation drain has completed.
namespace idoly_mp4_video_frame {
enum class Result : int { ready=0, waiting=1, invalid=-1, stale=-2, failed=-3 };
struct Identity {
    void* player=nullptr; void* clip=nullptr;
    uintptr_t player_native=0, clip_native=0;
    uint64_t epoch=0, job=0;
};
inline bool same(const Identity& a,const Identity& b) noexcept {
    return a.player==b.player&&a.clip==b.clip&&a.player_native==b.player_native
        &&a.clip_native==b.clip_native&&a.epoch==b.epoch&&a.job==b.job;
}
inline bool valid(const Identity& a) noexcept {
    return a.player&&a.clip&&a.player_native&&a.clip_native&&a.epoch&&a.job;
}
struct State {
    Identity identity{};void* texture=nullptr;uintptr_t texture_native=0;
    int64_t frame=-1;bool prepared=false,paused=false,playing=false,seek_pending=true;
};
struct Ops {
    void* context=nullptr;
    // Must also check the finite programme, source generation, private birth,
    // retained native IDs and held engine clock. No source VP is admitted.
    bool (*read)(void*,const Identity&,State*)=nullptr;
    bool (*set_frame)(void*,const Identity&,int64_t)=nullptr;
};
inline bool frame_for_normalized_time(double time,double rate,uint64_t count,int64_t* out) noexcept {
    // time is the value passed by unchanged SyncVideoToPlayable after its real
    // fmod(clip.length). Never round clip.frameRate to an integral export FPS.
    if(!out||!std::isfinite(time)||!std::isfinite(rate)||rate<=0||!count
        ||count>(~uint64_t(0)>>1))return false;
    const double frame=__builtin_floor(time*rate);
    if(!std::isfinite(frame))return false;
    if(frame<=0){*out=0;return true;}
    // Inexact length/rate metadata may describe a position past the final
    // decoded frame. The actual finite clip bounds are authoritative.
    const int64_t last=static_cast<int64_t>(count)-1;
    if(frame>=static_cast<double>(last)){*out=last;return true;}
    *out=static_cast<int64_t>(frame);return true;
}
class Scope {
    Ops ops_{};Identity identity_{};
    bool bound_=false,inflight_=false,failed_=false,issuing_=false;
    bool frame_event_=false,seek_event_=false,request_needs_seek_=false;
    uint64_t event_serial_=0,request_start_=0,drained_=0,receipt_=0;
    int64_t wanted_=-1,event_frame_=-1,accepted_frame_=-1;
    void* accepted_texture_=nullptr;uintptr_t accepted_native_=0;
    bool state(State& out) const {
        return bound_&&ops_.read&&ops_.read(ops_.context,identity_,&out)&&same(out.identity,identity_);
    }
    static bool usable(const State& out) noexcept {
        return out.prepared&&out.paused&&!out.playing&&out.texture&&out.texture_native;
    }
public:
    bool bind(Ops ops,const Identity& identity) noexcept {
        if(bound_||!valid(identity)||!ops.read||!ops.set_frame)return false;
        ops_=ops;identity_=identity;bound_=true;return true;
    }
    const Identity& identity()const noexcept{return identity_;}
    uint64_t receipt()const noexcept{return receipt_;}
    int64_t accepted_frame()const noexcept{return accepted_frame_;}
    bool inflight()const noexcept{return inflight_;}
    bool current_receipt(State* out=nullptr) const {
        if(!bound_||failed_||inflight_||!receipt_)return false;
        State now{};
        if(!state(now)||!usable(now)||now.seek_pending||now.frame!=accepted_frame_
            ||now.texture!=accepted_texture_||now.texture_native!=accepted_native_)return false;
        if(out)*out=now;
        return true;
    }
    Result request(double normalized_time,double clip_rate,uint64_t clip_frames) {
        int64_t frame=-1;if(!frame_for_normalized_time(normalized_time,clip_rate,clip_frames,&frame))return Result::invalid;
        return request_frame(frame,clip_frames);
    }
    Result request_frame(int64_t frame,uint64_t clip_frames) {
        if(!bound_||failed_||frame<0||!clip_frames||clip_frames>(~uint64_t(0)>>1)
            ||static_cast<uint64_t>(frame)>=clip_frames)return Result::invalid;
        if(inflight_)return frame==wanted_?Result::waiting:Result::invalid;
        State current{};if(!state(current)){failed_=true;return Result::stale;}
        if(!usable(current))return Result::waiting;
        // 120 Hz simulation can reuse a 30 Hz source frame only after a real
        // prior receipt, with the same live texture and no outstanding seek.
        if(receipt_&&frame==accepted_frame_&&!current.seek_pending&&current.frame==frame
            &&current.texture==accepted_texture_&&current.texture_native==accepted_native_)return Result::ready;
        wanted_=frame;request_start_=event_serial_;request_needs_seek_=true;
        frame_event_=seek_event_=false;event_frame_=-1;inflight_=true;issuing_=true;
        bool issued=false;
        try{issued=ops_.set_frame(ops_.context,identity_,frame);}
        catch(...){issuing_=false;failed_=true;throw;}
        issuing_=false;
        if(!issued){failed_=true;return Result::failed;}
        return Result::waiting;
    }
    // Call from only the original native-backed static callback for this
    // exact private player, before/after forwarding its original callback.
    bool frame_ready(const Identity& identity,int64_t frame) noexcept {
        if(!bound_||failed_||!same(identity,identity_)||frame<0)return false;
        ++event_serial_;if(!event_serial_){failed_=true;return false;}
        if(!inflight_||event_serial_>request_start_){frame_event_=true;event_frame_=frame;}
        return true;
    }
    bool seek_completed(const Identity& identity) noexcept {
        if(!bound_||failed_||!same(identity,identity_))return false;
        ++event_serial_;if(!event_serial_){failed_=true;return false;}
        if(inflight_&&event_serial_>request_start_)seek_event_=true;
        return true;
    }
    // This is the actual post-transfer native invocation-drain boundary, not
    // an Update count or a fabricated get_frame receipt. Reentrant setters
    // cannot close their own asynchronous operation while still executing.
    bool native_drain_completed(const Identity& identity) noexcept {
        if(!bound_||failed_||issuing_||!same(identity,identity_))return false;
        drained_=event_serial_;return true;
    }
    Result prepared_frame() {
        // Initial Prepare can already have transferred frame zero. Adopt that
        // genuine prepared receipt rather than seeking to the same frame and
        // waiting for a new-frame event the original engine does not emit.
        if(!bound_||failed_||inflight_)return Result::invalid;
        State current{};if(!state(current)){failed_=true;return Result::stale;}
        if(!usable(current)||current.seek_pending||!frame_event_||current.frame!=event_frame_
            ||!drained_||drained_!=event_serial_)return Result::waiting;
        accepted_frame_=current.frame;accepted_texture_=current.texture;accepted_native_=current.texture_native;
        ++receipt_;if(!receipt_){failed_=true;return Result::failed;}
        frame_event_=false;return Result::ready;
    }
    Result poll() {
        if(!bound_||failed_)return Result::invalid;
        if(!inflight_)return current_receipt()?Result::ready:Result::invalid;
        State current{};if(!state(current)){failed_=true;return Result::stale;}
        if(!usable(current)||current.seek_pending||!frame_event_||event_frame_!=wanted_||current.frame!=wanted_
            ||(request_needs_seek_&&!seek_event_)||drained_!=event_serial_||drained_<=request_start_)return Result::waiting;
        accepted_frame_=wanted_;accepted_texture_=current.texture;accepted_native_=current.texture_native;
        ++receipt_;if(!receipt_){failed_=true;return Result::failed;}
        inflight_=false;return Result::ready;
    }
    void abandon()noexcept{failed_=true;}
};
} // namespace idoly_mp4_video_frame
// END_MP4_VIDEO_FRAME
