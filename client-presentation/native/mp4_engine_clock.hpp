// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <cmath>
#include <initializer_list>
#endif

namespace idoly_mp4_engine_clock {
// Native TimeManager fields independently recovered from both pinned Unity
// engines. The host must verify their original code, registry and vtable before
// installing this helper; a managed Time getter is not that verification.
struct Layout {
    static constexpr size_t fixed_time=0x30,fixed_previous=0x38,fixed_unscaled=0x40,
        fixed_delta=0x48,fixed_unscaled_delta=0x4c,fixed_cached_delta=0x50,fixed_inverse_delta=0x58,
        game_time=0x60,game_previous=0x68,unscaled_time=0x70,
        game_delta=0x78,unscaled_delta=0x7c,smooth_delta=0x80,inverse_delta=0x88,
        render_time=0x90,render_previous=0x98,render_unscaled=0xa0,
        render_delta=0xa8,render_unscaled_delta=0xac,render_smooth_delta=0xb0,
        render_inverse_delta=0xb8,capture_delta=0xd8,
        scaled_wall_anchor=0xe0,unscaled_wall_anchor=0xe8,level_offset=0xf0,
        engine_paused=0xf8,time_scale=0xfc,maximum_delta=0x100,maximum_particle_delta=0x104;
};
struct Api {
    // Must establish the exact current native registry receiver, read/write
    // bounds, and original verified vtable. No old receiver may be dereferenced
    // after the registry changes. Called only on the engine's owning thread.
    bool (*current_manager)(void*)=nullptr;
    // Exact native ABI on both originals: double timestamp is in D0, not X1.
    void (*original_update)(void*,double)=nullptr;
};
struct Grant { bool advance=false;uint64_t index=0; };

class Scope {
public:
    bool install(const Api& value){
        if(active_||!value.current_manager||!value.original_update)return false;
        api_=value;error_="none";return true;
    }
    bool active()const{return active_;}
    bool restoring()const{return active_&&restore_rebased_;}
    bool owned_loop_quiescent()const{return active_&&loop_quiescent_;}
    bool held()const{
        if(!active_||!owner_||!api_.current_manager(owner_)||!settings_owned(owner_)
            ||load<double>(owner_,Layout::level_offset)!=saved_level_)return false;
        for(size_t field:{Layout::game_delta,Layout::unscaled_delta,Layout::smooth_delta,
                Layout::render_delta,Layout::render_unscaled_delta,Layout::render_smooth_delta})
            if(load<float>(owner_,field)!=0.f)return false;
        const double elapsed=elapsed_time();
        return load<double>(owner_,Layout::game_time)==epoch_+elapsed
            &&load<double>(owner_,Layout::render_time)==epoch_+elapsed
            &&load<double>(owner_,Layout::unscaled_time)==unscaled_epoch_+elapsed
            &&load<double>(owner_,Layout::render_unscaled)==unscaled_epoch_+elapsed;
    }
    bool have_tick()const{return have_tick_;}
    uint64_t tick()const{return tick_;}
    uint32_t simulation_hz()const{return hz_;}
    double last_wall_timestamp()const{return last_wall_;}
    void* latest_manager()const{return observed_manager_;}
    const char* error()const{return error_;}
    bool acquire(void* manager,double wall,uint32_t hz){
        if(active_)return fail("engine_clock_already_owned");
        if(!api_.current_manager||!api_.original_update)return fail("engine_clock_api_unavailable");
        if(!manager||!api_.current_manager(manager))return fail("engine_clock_owner_unverified");
        if((hz!=60&&hz!=120)||!finite(wall)||wall<0)return fail("engine_clock_options_invalid");
        if(load<uint8_t>(manager,Layout::engine_paused))return fail("engine_clock_engine_paused");
        for(size_t field:double_fields())if(!finite(load<double>(manager,field)))return fail("engine_clock_state_invalid");
        for(size_t field:float_fields())if(!finite(load<float>(manager,field)))return fail("engine_clock_state_invalid");
        const float fixed=load<float>(manager,Layout::fixed_delta),scale=load<float>(manager,Layout::time_scale),capture=load<float>(manager,Layout::capture_delta);
        if(fixed<=0||fixed>10||scale<0||scale>1000||capture<0||capture>10)return fail("engine_clock_state_invalid");
        memcpy(snapshot_,static_cast<uint8_t*>(manager)+snapshot_begin,sizeof(snapshot_));
        saved_capture_=capture;saved_scale_=scale;saved_fixed_=fixed;
        saved_scaled_anchor_=load<double>(manager,Layout::scaled_wall_anchor);
        saved_unscaled_anchor_=load<double>(manager,Layout::unscaled_wall_anchor);
        saved_level_=load<double>(manager,Layout::level_offset);
        epoch_=load<double>(manager,Layout::game_time);unscaled_epoch_=load<double>(manager,Layout::unscaled_time);
        start_wall_=last_wall_=wall;hz_=hz;owned_capture_=1.f/static_cast<float>(hz);
        owner_=manager;tick_=0;have_tick_=false;restore_rebased_=loop_quiescent_=false;active_=true;error_="none";
        store(manager,Layout::capture_delta,owned_capture_);store(manager,Layout::time_scale,1.f);
        // Acquisition/fencing may happen before the next native clock entry.
        // Its original AnimationOutput consumes unscaled delta at +0x7c, so
        // freeze every owned delta immediately without inventing a kernel tick.
        write_frame(manager,epoch_,unscaled_epoch_,0.);
        return true;
    }
    // Called at the original native clock entry before quiescing prior owned
    // jobs and draining their capture. Do not invent a second native kernel
    // invocation just to establish the held state for that boundary.
    bool hold_for_boundary(void* manager,double wall){
        if(!active_)return fail("engine_clock_not_owned");
        if(manager!=owner_||!api_.current_manager(manager))return fail("engine_clock_owner_replaced");
        if(!finite(wall)||wall<last_wall_)return fail("engine_clock_wall_timestamp_invalid");
        if(!settings_owned(manager))return fail("engine_clock_settings_changed");
        if(load<double>(manager,Layout::level_offset)!=saved_level_)return fail("engine_clock_scene_time_changed");
        const double elapsed=elapsed_time();write_frame(manager,epoch_+elapsed,unscaled_epoch_+elapsed,0.);
        last_wall_=wall;return true;
    }
    // true is the coordinator's explicit proof that audio/preparation is
    // complete and ALL owned dependent job/callback/render gates are ready.
    // A held clock alone does not establish that proof. Keep false during
    // passive/preparation work; release clears this mode before async cleanup.
    bool set_owned_loop_quiescent(bool value){
        if(!held())return fail("engine_clock_loop_not_held");
        loop_quiescent_=value;return true;
    }
    // The one native hook calls ONLY this wrapper, never original_update again.
    // Passive/preparation entries keep normal native housekeeping. Once the
    // coordinator proves owned-loop quiescence, held entries preserve logical
    // counters/one-shot flags and only granted simulation ticks run the kernel.
    bool native_tick(void* manager,double wall,Grant grant={}){
        if(!api_.original_update)return fail("engine_clock_api_unavailable");
        observed_manager_=manager;
        if(!active_){if(finite(wall)&&wall>=0)last_wall_=wall;api_.original_update(manager,wall);return true;}
        if(manager!=owner_||!api_.current_manager(manager)){
            active_=loop_quiescent_=false;owner_=nullptr;error_="engine_clock_owner_replaced";
            api_.original_update(manager,wall);return false;
        }
        const bool wall_ok=finite(wall)&&wall>=last_wall_;
        if(wall_ok)last_wall_=wall;
        if(load<double>(manager,Layout::level_offset)!=saved_level_){
            restore(manager,last_wall_,false);error_="engine_clock_scene_time_changed";
            api_.original_update(manager,wall);return false;
        }
        if(!settings_owned(manager)){
            // Another owner changed clock settings. Do not overwrite them or
            // rewind a potentially new scene; relinquish our settings first.
            restore(manager,last_wall_,false);error_="engine_clock_settings_changed";
            api_.original_update(manager,wall);return false;
        }
        const bool ordered=grant.advance&&(!have_tick_?grant.index==0:tick_!=~uint64_t(0)&&grant.index==tick_+1);
        bool valid=wall_ok&&(!grant.advance||ordered);
        if(valid&&grant.advance){
            const double elapsed=static_cast<double>(grant.index)/static_cast<double>(hz_);
            if(!finite(elapsed)||!finite(epoch_+elapsed)||!finite(unscaled_epoch_+elapsed)
                ||elapsed>2147483.)valid=false;
        }
        const bool native_paused=load<uint8_t>(manager,Layout::engine_paused)!=0;
        if(!loop_quiescent_||(valid&&grant.advance&&!restore_rebased_&&!native_paused))
            api_.original_update(manager,wall);
        if(load<uint8_t>(manager,Layout::engine_paused)){
            const double elapsed=elapsed_time();
            write_frame(manager,epoch_+elapsed,unscaled_epoch_+elapsed,0.);
            // Native engine suspension is distinct from a paused preview MV.
            // The proposed grant remains unconsumed. A quiescent owned loop
            // also preserves its counters until native suspension ends.
            return fail("engine_clock_engine_paused");
        }
        if(restore_rebased_){
            write_frame(manager,epoch_,unscaled_epoch_,0.);
            if(grant.advance)return fail("engine_clock_restore_in_progress");
            return true;
        }
        if(valid&&grant.advance){tick_=grant.index;have_tick_=true;}
        const double elapsed=elapsed_time();
        const double delta=valid&&grant.advance&&tick_?1./static_cast<double>(hz_):0.;
        write_frame(manager,epoch_+elapsed,unscaled_epoch_+elapsed,delta);
        if(!valid)return fail(wall_ok?"engine_clock_grant_out_of_order":"engine_clock_wall_timestamp_invalid");
        if(!strcmp(error_,"engine_clock_engine_paused"))error_="none";
        return true;
    }
    // Phase one of selected-scene restoration. The caller must have fenced
    // owned animation and established that restoring these global fixed-time
    // accumulators is safe for the scene's physics world. This helper does not
    // snapshot PhysX/Cloth/Articulation bodies. Reconstruct the original graph,
    // camera and actor history only AFTER this held source epoch is installed.
    bool rebase_for_restore(void* manager,double wall,bool scene_owned){
        if(!active_)return fail("engine_clock_not_owned");
        if(manager!=owner_||!api_.current_manager(manager))return fail("engine_clock_owner_replaced");
        if(!scene_owned||load<double>(manager,Layout::level_offset)!=saved_level_)
            return fail("engine_clock_restore_scene_unowned");
        if(!finite(wall)||wall<last_wall_)return fail("engine_clock_wall_timestamp_invalid");
        if(!settings_owned(manager))return fail("engine_clock_settings_changed");
        if(!held())return fail("engine_clock_restore_not_held");
        if(!restore_rebased_){
            memcpy(static_cast<uint8_t*>(manager)+snapshot_begin,snapshot_,sizeof(snapshot_));
            write_frame(manager,epoch_,unscaled_epoch_,0.);
            restore_rebased_=true;
        }
        last_wall_=wall;error_="none";return true;
    }
    // scene_owned=true is allowed only while the exact selected scene remains
    // owned. A new scene has its own level offset: never combine that offset
    // with old absolute/fixed times. No frame counters or one-shot flags are
    // copied from the snapshot on either cleanup path.
    bool restore(void* manager,double wall,bool scene_owned){
        if(!active_){loop_quiescent_=false;return true;}
        if(manager!=owner_||!api_.current_manager(manager)){
            active_=loop_quiescent_=false;owner_=nullptr;return fail("engine_clock_owner_replaced");
        }
        if(!finite(wall)||wall<start_wall_){wall=last_wall_;scene_owned=false;}
        const bool settings=settings_owned(manager);
        const bool level=load<double>(manager,Layout::level_offset)==saved_level_;
        const bool safe=scene_owned&&settings&&level;
        if(safe){
            // A phase-one rebase already installed coherent source time before
            // camera reconstruction. Do not reset its caches a second time.
            if(!restore_rebased_)memcpy(static_cast<uint8_t*>(manager)+snapshot_begin,snapshot_,sizeof(snapshot_));
            const double elapsed=wall-start_wall_;
            store(manager,Layout::scaled_wall_anchor,saved_scaled_anchor_+elapsed);
            store(manager,Layout::unscaled_wall_anchor,saved_unscaled_anchor_+elapsed);
        }else {
            // Preserve the current scene's absolute/fixed timeline and pair
            // its native wall anchors with the last virtual times instead.
            const double game=load<double>(manager,Layout::game_time),unscaled=load<double>(manager,Layout::unscaled_time);
            if(!finite(game)||!finite(unscaled)){
                active_=loop_quiescent_=false;owner_=nullptr;return fail("engine_clock_state_invalid");
            }
            store(manager,Layout::scaled_wall_anchor,wall-game);
            store(manager,Layout::unscaled_wall_anchor,wall-unscaled);
            write_frame(manager,game,unscaled,0.f);
        }
        // Compare-and-restore only controls still owned by this export.
        if(load<float>(manager,Layout::capture_delta)==owned_capture_)store(manager,Layout::capture_delta,saved_capture_);
        if(load<float>(manager,Layout::time_scale)==1.f)store(manager,Layout::time_scale,saved_scale_);
        last_wall_=wall;active_=loop_quiescent_=false;owner_=nullptr;
        if(scene_owned&&!safe)return fail(settings?"engine_clock_scene_time_changed":"engine_clock_settings_changed");
        return true;
    }
private:
    static constexpr size_t snapshot_begin=0x30,snapshot_end=0xbc;
    struct Fields { const size_t* first;size_t count;const size_t*begin()const{return first;}const size_t*end()const{return first+count;} };
    static Fields double_fields(){static constexpr size_t fields[]={0x30,0x38,0x40,0x60,0x68,0x70,0x90,0x98,0xa0,0xe0,0xe8,0xf0};return {fields,sizeof(fields)/sizeof(*fields)};}
    static Fields float_fields(){static constexpr size_t fields[]={0x48,0x4c,0x50,0x58,0x78,0x7c,0x80,0x84,0x88,0xa8,0xac,0xb0,0xb4,0xb8,0xd8,0xfc};return {fields,sizeof(fields)/sizeof(*fields)};}
    template<class T>static T load(void* value,size_t at){T result{};memcpy(&result,static_cast<uint8_t*>(value)+at,sizeof(result));return result;}
    template<class T>static void store(void* value,size_t at,T field){memcpy(static_cast<uint8_t*>(value)+at,&field,sizeof(field));}
    template<class T>static bool finite(T value){return __builtin_isfinite(value);}
    bool fail(const char* code){error_=code;return false;}
    double elapsed_time()const{return have_tick_&&!restore_rebased_?static_cast<double>(tick_)/static_cast<double>(hz_):0.;}
    bool settings_owned(void* manager)const{return load<float>(manager,Layout::capture_delta)==owned_capture_&&load<float>(manager,Layout::time_scale)==1.f&&load<float>(manager,Layout::fixed_delta)==saved_fixed_;}
    static void write_frame(void* manager,double game,double unscaled,double delta){
        const double previous=game-delta;
        for(size_t field:{Layout::game_time,Layout::render_time})store(manager,field,game);
        for(size_t field:{Layout::game_previous,Layout::render_previous})store(manager,field,previous);
        for(size_t field:{Layout::unscaled_time,Layout::render_unscaled})store(manager,field,unscaled);
        for(size_t field:{Layout::game_delta,Layout::unscaled_delta,Layout::smooth_delta,Layout::render_delta,Layout::render_unscaled_delta,Layout::render_smooth_delta})store(manager,field,static_cast<float>(delta));
        const float inverse=delta>0?static_cast<float>(1./delta):1.f;
        store(manager,Layout::inverse_delta,inverse);store(manager,Layout::render_inverse_delta,inverse);
    }
    Api api_{};void* owner_=nullptr;void* observed_manager_=nullptr;bool active_=false,have_tick_=false,restore_rebased_=false,loop_quiescent_=false;uint64_t tick_=0;uint32_t hz_=0;
    uint8_t snapshot_[snapshot_end-snapshot_begin]{};
    float saved_capture_=0,saved_scale_=0,saved_fixed_=0,owned_capture_=0;
    double saved_scaled_anchor_=0,saved_unscaled_anchor_=0,saved_level_=0,epoch_=0,unscaled_epoch_=0,start_wall_=0,last_wall_=0;
    const char* error_="none";
};
} // namespace idoly_mp4_engine_clock
