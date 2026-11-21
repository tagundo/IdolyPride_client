// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
// Sequential MV replay through the original screen router. All entry points
// run on the Unity thread. Logical descriptors are copied; managed references
// are ephemeral GC handles and never enter the persistent queue journal.
#include "mp4_queue.hpp"

namespace idoly_mp4_replay {
using Descriptor=idoly_mp4_queue::Descriptor;
using Actor=idoly_mp4_queue::Actor;
using Method=const void;
struct UniTask16 { void* source=nullptr; uint64_t token_and_padding=0; };
struct CancellationToken8 { void* source=nullptr; };
static_assert(sizeof(UniTask16)==16&&sizeof(CancellationToken8)==8,"Audited ARM64 UniTask/CancellationToken ABI");
enum class Kind : int { out_game_param=1,actor_descriptor=2,transition_param=3 };
enum class Phase { idle,closing,waiting_for_close,opening,waiting_for_open,ready,failed,cancelled };
struct Api {
    bool(*is_type)(void*,const char*)=nullptr;
    bool(*alive)(void*)=nullptr;
    uint32_t(*retain)(void*)=nullptr;
    void*(*retained)(uint32_t)=nullptr;
    void(*release)(uint32_t)=nullptr;
    // Factories use the audited readonly type references and the original
    // declared List<String> field type. They must not instantiate Unity objects.
    void*(*new_object)(Kind)=nullptr;
    void*(*new_string)(const char*)=nullptr;
    void*(*new_field_list)(void*,const char*)=nullptr;
    bool(*list_add)(void*,void*)=nullptr;
    // Resolve the exact named field in its declaring hierarchy; verify its
    // managed kind; use public il2cpp_field_set_value (including GC barriers).
    bool(*set_object)(void*,const char*,void*)=nullptr;
    bool(*set_i32)(void*,const char*,int32_t)=nullptr;
    bool(*set_bool)(void*,const char*,bool)=nullptr;
    void(*out_game_param_ctor)(void*,void*,void*,Method*)=nullptr;
    void(*actor_descriptor_ctor)(void*,Method*)=nullptr;
    void(*transition_param_ctor)(void*,Method*)=nullptr;
    void(*param_add_actor)(void*,void*,void*,int32_t,int32_t,int32_t,int32_t,Method*)=nullptr;
    void*(*scene_instance)(Method*)=nullptr;
    bool(*scene_busy)(void*,Method*)=nullptr;
    void*(*live_state)(Method*)=nullptr;
    void*(*tree_with_param)(void*,void*,Method*)=nullptr;
    void(*open_tree)(void*,void*,void*,Method*)=nullptr;
    void*(*top_screen)(void*,Method*)=nullptr;
    UniTask16(*presenter_end)(void*,CancellationToken8,Method*)=nullptr;
    int32_t(*task_status)(UniTask16*,Method*)=nullptr;
    UniTask16(*task_get_awaiter)(UniTask16*,Method*)=nullptr;
    void(*task_get_result)(UniTask16*,Method*)=nullptr;
    bool(*player_ready)(void*,Method*)=nullptr;
};
inline bool descriptor_equal(const Descriptor&a,const Descriptor&b){
    if(strcmp(a.stage_asset,b.stage_asset)||strcmp(a.timeline_asset,b.timeline_asset)
       ||a.actor_count!=b.actor_count||a.stage_max_capacity!=b.stage_max_capacity
       ||a.detach_actors_on_player_destroyed!=b.detach_actors_on_player_destroyed)return false;
    for(size_t i=0;i<a.actor_count;++i){const Actor&x=a.actors[i];const Actor&y=b.actors[i];
        if(strcmp(x.character_id,y.character_id)||strcmp(x.descriptor_name,y.descriptor_name)
           ||x.name_is_null!=y.name_is_null||x.actor_index!=y.actor_index||x.track_index!=y.track_index
           ||x.audience_amount!=y.audience_amount||x.psyllium_color_type!=y.psyllium_color_type
           ||x.asset_count!=y.asset_count||x.collider_type!=y.collider_type
           ||x.render_layer_base!=y.render_layer_base||x.humanoid!=y.humanoid||x.trigger!=y.trigger
           ||x.auto_blink_disabled!=y.auto_blink_disabled||x.use_adv_settings!=y.use_adv_settings)return false;
        for(size_t j=0;j<x.asset_count;++j)if(strcmp(x.assets[j],y.assets[j]))return false;
    }return true;
}
class Replay {
public:
    explicit Replay(Api api={}):api_(api){}
    ~Replay(){clear_all();}
    Replay(const Replay&)=delete;Replay&operator=(const Replay&)=delete;
    bool set_api(Api api){if(active())return false;reset();api_=api;return valid_api();}
    // Supply only a descriptor associated with THIS presenter's actual player.
    // Capture.selected(player, descriptor) is the integration boundary.
    bool observe(void*presenter,void*player,const Descriptor&descriptor){
        if(!valid_api()||!idoly_mp4_queue::detail::descriptor(descriptor))return false;
        try{
            if(!live_type(presenter,"Solis.OutGame.LivePlayerScreenPresenter")
                ||!live_type(player,"Solis.Common.SolisLivePlayer"))return false;
            if(get(observed_presenter_)==presenter&&get(observed_player_)==player
                &&descriptor_equal(observed_,descriptor))return true;
            uint32_t p=api_.retain(presenter);if(!p)return false;
            uint32_t v=api_.retain(player);if(!v){api_.release(p);return false;}
            drop(observed_presenter_);drop(observed_player_);observed_presenter_=p;observed_player_=v;
            observed_=descriptor;return true;
        }catch(...){fail("original_selection_observer_failed");return false;}
    }
    bool begin(const Descriptor&descriptor,uint64_t now){
        if(active())return false;
        release_attempt();error_="none";phase_=Phase::idle;cancel_requested_=false;
        if(!valid_api()){fail("replay_api_unavailable");return false;}
        if(!idoly_mp4_queue::detail::descriptor(descriptor)){fail("invalid_mv_descriptor");return false;}
        target_=descriptor;started_=now;phase_=Phase::closing;return true;
    }
    // Read-only readiness for accepting Queue Run. A loaded native bridge or
    // server settings window alone does not imply an original game router.
    bool can_route()const{
        if(!valid_api())return false;
        try{void*scene=api_.scene_instance(nullptr);return scene&&api_.alive(scene)&&!api_.scene_busy(scene,nullptr);}
        catch(...){return false;}
    }
    void tick(uint64_t now){
        if(!active())return;
        if(now<started_){fail("replay_clock_invalid");return;}
        const uint64_t timeout=phase_==Phase::closing||phase_==Phase::waiting_for_close?60000:300000;
        if(now-started_>timeout){fail(phase_==Phase::closing||phase_==Phase::waiting_for_close
            ?"previous_mv_close_timeout":"queued_mv_load_timeout");return;}
        try{
            if(phase_==Phase::closing){
                void*scene=api_.scene_instance(nullptr);if(!scene||!api_.alive(scene)||api_.scene_busy(scene,nullptr))return;
                void*presenter=get(observed_presenter_),*player=get(observed_player_);
                if(api_.top_screen(scene,nullptr)==presenter&&live_type(presenter,"Solis.OutGame.LivePlayerScreenPresenter")&&live_type(player,"Solis.Common.SolisLivePlayer")){
                    // End assumes the original player has finished binding.
                    // Never tear down a half-initialized original MV ourselves.
                    if(!api_.player_ready(player,nullptr))return;
                    if(descriptor_equal(observed_,target_)){
                        if(!keep(result_presenter_,presenter)||!keep(result_player_,player)){fail("replay_gc_handle_failed");return;}
                        phase_=Phase::ready;return;
                    }
                    if(!keep(closing_presenter_,presenter)||!keep(closing_player_,player)){fail("replay_gc_handle_failed");return;}
                    // Keep the original source/token and consume exactly once.
                    // Forget and polling the same pooled source must not mix.
                    closing_task_=api_.presenter_end(presenter,CancellationToken8{},nullptr);
                    if(closing_task_.source&&!keep(closing_task_source_,closing_task_.source)){fail("replay_gc_handle_failed");return;}
                    close_consumed_=false;phase_=Phase::waiting_for_close;started_=now;return;
                }
                phase_=Phase::opening;started_=now;
            }
            if(phase_==Phase::waiting_for_close){
                if(!close_consumed_){
                    if(closing_task_source_)closing_task_.source=get(closing_task_source_);
                    int32_t status=api_.task_status(&closing_task_,nullptr);if(status==0)return;
                    if(status<1||status>3){fail("original_task_status_invalid");return;}
                    UniTask16 awaiter=api_.task_get_awaiter(&closing_task_,nullptr);
                    close_consumed_=true;api_.task_get_result(&awaiter,nullptr);
                    drop(closing_task_source_);closing_task_=UniTask16{};
                }
                void*old=get(closing_presenter_);void*scene=api_.scene_instance(nullptr);
                if(!scene||!api_.alive(scene)||api_.scene_busy(scene,nullptr)||api_.top_screen(scene,nullptr)==old)return;
                if(cancel_requested_){finish_cancel();return;}
                // A newly selected unrelated MV belongs to the user, so do not
                // recursively close it while trying to acquire the queue scene.
                void*selected=get(observed_presenter_);
                if(selected&&selected!=old&&api_.alive(selected)){fail("queue_selection_changed");return;}
                phase_=Phase::opening;started_=now;
            }
            if(phase_==Phase::opening){
                void*scene=api_.scene_instance(nullptr);if(!scene||!api_.alive(scene)||api_.scene_busy(scene,nullptr))return;
                if(!construct_transition()){fail("queued_mv_construction_failed");return;}
                Root state(api_,api_.live_state(nullptr));if(!state){fail("live_player_state_unavailable");return;}
                Root tree(api_,api_.tree_with_param(state.get(),get(transition_),nullptr));if(!tree){fail("live_player_tree_unavailable");return;}
                if(!keep(tree_,tree.get())){fail("replay_gc_handle_failed");return;}
                // Set the phase BEFORE original OpenTree: its original async
                // initializer may synchronously publish the new player.
                phase_=Phase::waiting_for_open;started_=now;api_.open_tree(scene,tree.get(),nullptr,nullptr);return;
            }
            if(phase_==Phase::waiting_for_open){
                void*presenter=get(observed_presenter_),*player=get(observed_player_);
                if(!presenter||!api_.alive(presenter)||!api_.alive(player))return;
                void*scene=api_.scene_instance(nullptr);if(!scene||!api_.alive(scene)||api_.scene_busy(scene,nullptr)
                    ||api_.top_screen(scene,nullptr)!=presenter||!api_.player_ready(player,nullptr))return;
                // The original pool can reuse a presenter/player pair. The
                // exact current top screen, ready player and associated frozen
                // descriptor matter; pointer novelty is not a lifecycle proof.
                if(!descriptor_equal(observed_,target_)){fail("queue_selection_changed");return;}
                if(cancel_requested_){finish_cancel();return;}
                if(!keep(result_presenter_,presenter)||!keep(result_player_,player)){fail("replay_gc_handle_failed");return;}
                drop(transition_);drop(tree_);drop(closing_presenter_);drop(closing_player_);phase_=Phase::ready;
            }
        }catch(...){fail("original_navigation_exception");}
    }
    // The owner calls this after a lifecycle suspension; suspended wall-clock
    // time must not become an asset-load or screen-close timeout.
    void resume_clock(uint64_t now){if(active())started_=now;}
    // An original navigation already in flight must settle before the queue
    // starts another job. Cancellation stops export, not the original UI task.
    void cancel(){if(active()){cancel_requested_=true;if(phase_==Phase::closing||phase_==Phase::opening)finish_cancel();}}
    bool reset(){if(active())return false;clear_all();return true;}
    Phase phase()const{return phase_;}
    const char*error()const{return error_;}
    bool active()const{return phase_==Phase::closing||phase_==Phase::waiting_for_close||phase_==Phase::opening||phase_==Phase::waiting_for_open;}
    void*presenter()const{return phase_==Phase::ready?get(result_presenter_):nullptr;}
    void*player()const{return phase_==Phase::ready?get(result_player_):nullptr;}
private:
    class Root {
    public:
        Root(const Api&a,void*p):api_(a),handle_(p?a.retain(p):0){}
        ~Root(){if(handle_)api_.release(handle_);}
        Root(const Root&)=delete;Root&operator=(const Root&)=delete;
        void*get()const{return handle_?api_.retained(handle_):nullptr;}
        explicit operator bool()const{return get()!=nullptr;}
    private:const Api&api_;uint32_t handle_=0;
    };
    bool valid_api()const{return api_.is_type&&api_.alive&&api_.retain&&api_.retained&&api_.release
        &&api_.new_object&&api_.new_string&&api_.new_field_list&&api_.list_add&&api_.set_object&&api_.set_i32&&api_.set_bool
        &&api_.out_game_param_ctor&&api_.actor_descriptor_ctor&&api_.transition_param_ctor&&api_.param_add_actor
        &&api_.scene_instance&&api_.scene_busy&&api_.live_state&&api_.tree_with_param&&api_.open_tree&&api_.top_screen
        &&api_.presenter_end&&api_.task_status&&api_.task_get_awaiter&&api_.task_get_result&&api_.player_ready;}
    void*get(uint32_t h)const{return h&&api_.retained?api_.retained(h):nullptr;}
    bool keep(uint32_t&h,void*p){if(!p)return false;uint32_t next=api_.retain(p);if(!next)return false;drop(h);h=next;return true;}
    void drop(uint32_t&h){if(h&&api_.release)api_.release(h);h=0;}
    bool live_type(void*p,const char*name)const{return p&&api_.alive(p)&&api_.is_type(p,name);}
    void release_attempt(){drop(transition_);drop(tree_);drop(closing_presenter_);drop(closing_player_);drop(result_presenter_);drop(result_player_);drop(closing_task_source_);closing_task_=UniTask16{};close_consumed_=false;}
    void finish_cancel(){release_attempt();phase_=Phase::cancelled;error_="cancelled";}
    void clear_all(){release_attempt();drop(observed_presenter_);drop(observed_player_);phase_=Phase::idle;error_="none";}
    void fail(const char*error){release_attempt();phase_=Phase::failed;error_=error;}
    bool construct_transition(){
        Root param(api_,api_.new_object(Kind::out_game_param));
        Root stage(api_,api_.new_string(target_.stage_asset)),timeline(api_,api_.new_string(target_.timeline_asset));
        if(!param||!stage||!timeline)return false;
        api_.out_game_param_ctor(param.get(),stage.get(),timeline.get(),nullptr);
        if(!api_.set_i32(param.get(),"stageMaxCapacity",target_.stage_max_capacity)
            ||!api_.set_bool(param.get(),"detachActorsOnPlayerDestroyed",target_.detach_actors_on_player_destroyed!=0))return false;
        for(size_t i=0;i<target_.actor_count;++i){const Actor&a=target_.actors[i];
            Root descriptor(api_,api_.new_object(Kind::actor_descriptor));if(!descriptor)return false;
            api_.actor_descriptor_ctor(descriptor.get(),nullptr);
            Root assets(api_,api_.new_field_list(descriptor.get(),"_assets"));if(!assets)return false;
            for(size_t j=0;j<a.asset_count;++j){Root asset(api_,api_.new_string(a.assets[j]));if(!asset||!api_.list_add(assets.get(),asset.get()))return false;}
            if(!api_.set_object(descriptor.get(),"_assets",assets.get())||!api_.set_object(descriptor.get(),"_gameObjects",nullptr))return false;
            Root name(api_,a.name_is_null?nullptr:api_.new_string(a.descriptor_name));
            if((!a.name_is_null&&!name)||!api_.set_object(descriptor.get(),"_name",name.get())
                ||!api_.set_bool(descriptor.get(),"_humanoid",a.humanoid!=0)
                ||!api_.set_i32(descriptor.get(),"_colliderType",a.collider_type)
                ||!api_.set_bool(descriptor.get(),"_colliderTrigger",a.trigger!=0)
                ||!api_.set_bool(descriptor.get(),"_autoBlinkDisabled",a.auto_blink_disabled!=0)
                ||!api_.set_bool(descriptor.get(),"_useADVSettings",a.use_adv_settings!=0)
                ||!api_.set_i32(descriptor.get(),"_renderingLayerMaskBaseIndex",a.render_layer_base))return false;
            Root character(api_,api_.new_string(a.character_id));if(!character)return false;
            api_.param_add_actor(param.get(),character.get(),descriptor.get(),a.audience_amount,
                a.psyllium_color_type,a.actor_index,a.track_index,nullptr);
        }
        Root transition(api_,api_.new_object(Kind::transition_param));if(!transition)return false;
        api_.transition_param_ctor(transition.get(),nullptr);
        return api_.set_object(transition.get(),"liveParam",param.get())
            &&api_.set_bool(transition.get(),"isDebugMode",false)&&keep(transition_,transition.get());
    }
    Api api_{};Descriptor observed_{},target_{};
    Phase phase_=Phase::idle;const char*error_="none";uint64_t started_=0;
    UniTask16 closing_task_{};bool close_consumed_=false,cancel_requested_=false;
    uint32_t observed_presenter_=0,observed_player_=0,closing_presenter_=0,closing_player_=0,
        transition_=0,tree_=0,result_presenter_=0,result_player_=0,closing_task_source_=0;
};
} // namespace idoly_mp4_replay
