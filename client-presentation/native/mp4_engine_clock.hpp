// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <cmath>
#include <initializer_list>
#endif

// BEGIN_ORIGINAL_ENGINE_CLOCK_PROFILE
namespace idoly_mp4_engine_clock {
struct Binding { uintptr_t rva;uint8_t prefix[16]; };
struct Profile {
    const char* native_sha256;uintptr_t registry_slot,manager_vtable;
    Binding get_manager,update,fixed_work,fixed_tick,fixed_cache_refresh,level_reset,realtime,monotonic_timestamp,application_fps_get,application_fps_set,quality_manager,vsync_set;
};
inline constexpr Profile android_profile={
    "c36ea39e5040fbcd0577f7c49d08e149e2e7dc62449d90aadce761118a816c85",0x1497840,0x14139c8,
    {0x6225e8,{0xe0,0x0,0x80,0x52,0xe0,0xd3,0xfc,0x17,0xe0,0x0,0x80,0x52,0xe2,0xd3,0xfc,0x17}}, // get_manager
    {0x622000,{0x8,0x64,0x40,0xf9,0x9,0xd0,0x40,0xb9,0xa,0xe0,0x43,0x39,0x8,0x5,0x0,0x91}}, // update
    {0x6221c8,{0x0,0x48,0x40,0xbd,0x1,0x18,0x40,0xfd,0x2,0x30,0x40,0xfd,0x0,0xc0,0x22,0x1e}}, // fixed_work
    {0x6221fc,{0x2,0x48,0x40,0xbd,0x1,0x18,0x40,0xfd,0x0,0x30,0x40,0xfd,0x9,0x8,0x43,0x39}}, // fixed_tick
    {0x6222b4,{0x0,0x48,0x40,0xbd,0x1,0x10,0x2e,0x1e,0x21,0x18,0x20,0x1e,0x1,0x58,0x0,0xbd}}, // fixed_cache_refresh
    {0x62232c,{0x0,0x30,0x40,0xfd,0x28,0x20,0x80,0x52,0x8,0x80,0x1,0x79,0x0,0x40,0x61,0x1e}}, // level_reset
    {0x622464,{0xfe,0x4f,0xbf,0xa9,0xf3,0x3,0x0,0xaa,0x54,0x0,0x1,0x94,0x61,0x76,0x40,0xfd}}, // realtime
    {0x6625bc,{0xfe,0x4f,0xbf,0xa9,0xe8,0x73,0x0,0x90,0x13,0x1,0x45,0xf9,0x33,0x1,0x0,0xb5}}, // monotonic_timestamp
    {0x440f88,{0xa7,0x82,0x7,0x14,0xa9,0x82,0x7,0x14,0x1f,0x1c,0x0,0x72,0xe0,0x7,0x9f,0x1a}}, // application_fps_get
    {0x440f8c,{0xa9,0x82,0x7,0x14,0x1f,0x1c,0x0,0x72,0xe0,0x7,0x9f,0x1a,0xde,0x4b,0xb,0x14}}, // application_fps_set
    {0xe5c548,{0x60,0x1,0x80,0x52,0x8,0xec,0xdb,0x17,0x60,0x1,0x80,0x52,0xa,0xec,0xdb,0x17}}, // quality_manager
    {0x453820,{0xfe,0x4f,0xbf,0xa9,0xf3,0x3,0x0,0x2a,0x48,0x23,0x28,0x94,0xe1,0x3,0x13,0x2a}}, // vsync_set
};
inline constexpr Profile ios_profile={
    "b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf",0xa85a408,0x97ebb78,
    {0xcad690,{0xe0,0x0,0x80,0x52,0x71,0xd9,0xfc,0x17,0xff,0x43,0x1,0xd1,0xf8,0x5f,0x1,0xa9}}, // get_manager
    {0xcad01c,{0x8,0x64,0x40,0xf9,0x8,0x5,0x0,0x91,0x8,0x64,0x0,0xf9,0x8,0xd0,0x40,0xb9}}, // update
    {0xcad1dc,{0x0,0x18,0x40,0xfd,0x1,0x48,0x40,0xbd,0x21,0xc0,0x22,0x1e,0x0,0x28,0x61,0x1e}}, // fixed_work
    {0xcad210,{0x0,0x18,0x40,0xfd,0x1,0x48,0x40,0xbd,0x21,0xc0,0x22,0x1e,0x2,0x28,0x61,0x1e}}, // fixed_tick
    {0xcad2c8,{0x0,0x48,0x40,0xbd,0x1,0x10,0x2e,0x1e,0x21,0x18,0x20,0x1e,0x1,0x58,0x0,0xbd}}, // fixed_cache_refresh
    {0xcad340,{0x0,0x30,0x40,0xfd,0x0,0x40,0x61,0x1e,0x0,0x78,0x0,0xfd,0x28,0x20,0x80,0x52}}, // level_reset
    {0xcad4ec,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0xf3,0x3,0x0,0xaa}}, // realtime
    {0xced8c8,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0xa8,0xdd,0x4,0xb0}}, // monotonic_timestamp
    {0xaef7f4,{0x17,0xf5,0x6,0x14,0x19,0xf5,0x6,0x14,0x1f,0x0,0x0,0x71,0xe0,0x7,0x9f,0x1a}}, // application_fps_get
    {0xaef7f8,{0x19,0xf5,0x6,0x14,0x1f,0x0,0x0,0x71,0xe0,0x7,0x9f,0x1a,0xb3,0xf1,0xa,0x14}}, // application_fps_set
    {0x137ba44,{0x60,0x1,0x80,0x52,0x84,0xa0,0xe1,0x17,0xfc,0x6f,0xbc,0xa9,0xf6,0x57,0x1,0xa9}}, // quality_manager
    {0xafdd14,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0xf3,0x3,0x0,0xaa}}, // vsync_set
};
} // namespace idoly_mp4_engine_clock
// END_ORIGINAL_ENGINE_CLOCK_PROFILE

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

// BEGIN_ORIGINAL_WORLD_PROFILE
namespace idoly_mp4_world {
struct CodeBinding {uintptr_t rva;uint8_t prefix[16];};
struct TypeBinding {uintptr_t rva;uint8_t prefix[16];uint32_t kind,definition;};
struct WorldProfile {uintptr_t registry_slot;CodeBinding find_objects,current_loop,cloth_enabled,actor_registry,game_object,active_hierarchy,active_enabled,animator_graph,animator_controller,animator_bound,animator_mode,legacy_state_count,graph_valid,graph_output_count,graph_output,output_valid,output_type,output_target,lookup,lookup_impl,lookup_iterator,lookup_hash,registrar,fixed_condition,fixed_executor,animator_register,animator_unregister,animator_record_ctor,animator_append;TypeBinding rigidbody_type,rigidbody2d_type,cloth_type,character_controller_type,fixed_update_type,animator_type,animation_type,animation_output_type;};
inline constexpr WorldProfile android_world_profile={0x1497250,
    {0x8f84ae0,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x1,0xa9,0xb5,0x87,0x0,0xb0,0xa2,0x6a,0x41,0xf9}}, // find_objects
    {0x8f97444,{0xfe,0x4f,0xbf,0xa9,0x13,0x87,0x0,0xd0,0x60,0xfe,0x46,0xf9,0xa0,0x0,0x0,0xb5}}, // current_loop
    {0x8f3437c,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0x14,0x8a,0x0,0xd0,0x81,0x6e,0x43,0xf9}}, // cloth_enabled
    {0x924507c,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0xd3,0x71,0x0,0xb0,0x14,0x3e,0x0,0xf0}}, // actor_registry
    {0x8f7c5c8,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0xf4,0x87,0x0,0x90,0x81,0xe6,0x47,0xf9}}, // game_object
    {0x8f7fdd8,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0xd4,0x87,0x0,0xd0,0x81,0x72,0x40,0xf9}}, // active_hierarchy
    {0x8f7bb50,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0xf4,0x87,0x0,0xb0,0x81,0xd6,0x47,0xf9}}, // active_enabled
    {0x8f21850,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x1,0xa9,0xb5,0x8a,0x0,0x90,0xa2,0x2e,0x44,0xf9}}, // animator_graph
    {0x8f21630,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0xb4,0x8a,0x0,0x90,0x81,0xa,0x44,0xf9}}, // animator_controller
    {0x8f216b0,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0xb4,0x8a,0x0,0x90,0x81,0x12,0x44,0xf9}}, // animator_bound
    {0x8f1df64,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0xd4,0x8a,0x0,0x90,0x81,0x12,0x43,0xf9}}, // animator_mode
    {0x8f1bfd8,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0xd4,0x8a,0x0,0xd0,0x81,0x72,0x42,0xf9}}, // legacy_state_count
    {0x8fabb44,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0x74,0x86,0x0,0xf0,0x81,0x5a,0x41,0xf9}}, // graph_valid
    {0x8fabff4,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0x74,0x86,0x0,0xf0,0x81,0x82,0x41,0xf9}}, // graph_output_count
    {0x8fac30c,{0xfe,0xf,0x1d,0xf8,0xf6,0x57,0x1,0xa9,0xf4,0x4f,0x2,0xa9,0x76,0x86,0x0,0xd0}}, // graph_output
    {0x8fae8bc,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0x74,0x86,0x0,0x90,0x81,0x52,0x42,0xf9}}, // output_valid
    {0x8fae8f8,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0x74,0x86,0x0,0x90,0x81,0x56,0x42,0xf9}}, // output_type
    {0x8f2679c,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0x74,0x8a,0x0,0xf0,0x81,0x52,0x46,0xf9}}, // output_target
    {0x54a674,{0x68,0x7a,0x0,0xb0,0x8,0x29,0x41,0xf9,0xe1,0x3,0x0,0x2a,0xe0,0x3,0x8,0xaa}}, // lookup
    {0x54a688,{0xff,0xc3,0x0,0xd1,0xfe,0x4f,0x2,0xa9,0xf3,0x3,0x0,0xaa,0xe1,0x1f,0x0,0xb9}}, // lookup_impl
    {0x54ad4c,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0x2,0x50,0x0,0x91,0xf4,0x3,0x0,0xaa}}, // lookup_iterator
    {0x54bc88,{0x28,0x0,0x40,0xb9,0xc9,0xa2,0x8b,0x52,0xa9,0xda,0xaf,0x72,0x8a,0x47,0x98,0x52}}, // lookup_hash
    {0x54b388,{0xff,0x3,0x1,0xd1,0xfe,0xb,0x0,0xf9,0xf6,0x57,0x2,0xa9,0xf4,0x4f,0x3,0xa9}}, // registrar
    {0x6420e4,{0xfe,0xf,0x1f,0xf8,0x40,0x81,0xff,0x97,0xfe,0x7,0x41,0xf8,0x43,0x80,0xff,0x17}}, // fixed_condition
    {0x63ffd8,{0x68,0x32,0x40,0xf9,0x68,0x0,0x0,0xb4,0x0,0x1,0x3f,0xd6,0x60,0x7,0x0,0x36}}, // fixed_executor
    {0x8bbb80,{0xff,0x43,0x3,0xd1,0xfe,0x5f,0xa,0xa9,0xf6,0x57,0xb,0xa9,0xf4,0x4f,0xc,0xa9}}, // animator_register
    {0x8bb9e8,{0xff,0x43,0x3,0xd1,0xfe,0x53,0x0,0xf9,0xf6,0x57,0xb,0xa9,0xf4,0x4f,0xc,0xa9}}, // animator_unregister
    {0x8affb8,{0xff,0xc3,0x0,0xd1,0xfe,0x57,0x1,0xa9,0xf4,0x4f,0x2,0xa9,0xf3,0x3,0x0,0xaa}}, // animator_record_ctor
    {0x8bf09c,{0xfe,0xf,0x1d,0xf8,0xf6,0x57,0x1,0xa9,0xf4,0x4f,0x2,0xa9,0x15,0x20,0x41,0xa9}}, // animator_append
    {0x9de8480,{0x85,0x7e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x12,0x0,0x0,0x0,0x0,0x0},18,32389}, // rigidbody_type
    {0x9de84b0,{0x8f,0x81,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x12,0x0,0x0,0x0,0x0,0x0},18,33167}, // rigidbody2d_type
    {0x9da10d0,{0x82,0x82,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x12,0x0,0x0,0x0,0x0,0x0},18,33410}, // cloth_type
    {0x9d9f4b0,{0x87,0x7e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x12,0x0,0x0,0x0,0x0,0x0},18,32391}, // character_controller_type
    {0x9db51f0,{0x85,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24197}, // fixed_update_type
    {0x9d85f00,{0x16,0x78,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x12,0x0,0x0,0x0,0x0,0x0},18,30742}, // animator_type
    {0x9d94d60,{0x6,0x78,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x12,0x0,0x0,0x0,0x0,0x0},18,30726}, // animation_type
    {0x9d95100,{0x3f,0x78,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,30783}, // animation_output_type
};
inline constexpr WorldProfile ios_world_profile={0xa938f90,
    {0x7854ed8,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}}, // find_objects
    {0x787002c,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0x73,0x85,0x1,0xb0}}, // current_loop
    {0x77e6374,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0x93,0x89,0x1,0xf0}}, // cloth_enabled
    {0x7bd4f70,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0x73,0x6a,0x1,0xb0}}, // actor_registry
    {0x7849a74,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0x93,0x86,0x1,0xf0}}, // game_object
    {0x784e5ec,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0x73,0x86,0x1,0xd0}}, // active_hierarchy
    {0x7848b70,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0xb3,0x86,0x1,0x90}}, // active_enabled
    {0x77c7ef8,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}}, // animator_graph
    {0x77c7c28,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0x93,0x8a,0x1,0xd0}}, // animator_controller
    {0x77c7cdc,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0x93,0x8a,0x1,0xd0}}, // animator_bound
    {0x77c2f00,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0xb3,0x8a,0x1,0xd0}}, // animator_mode
    {0x77c0208,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0xd3,0x8a,0x1,0x90}}, // legacy_state_count
    {0x78900f8,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0x73,0x84,0x1,0xb0}}, // graph_valid
    {0x7890aa4,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0x73,0x84,0x1,0xb0}}, // graph_output_count
    {0x7891148,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}}, // graph_output
    {0x78961fc,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0x33,0x84,0x1,0xf0}}, // output_valid
    {0x78962f8,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0x33,0x84,0x1,0xf0}}, // output_type
    {0x77d07b4,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0x53,0x8a,0x1,0xb0}}, // output_target
    {0xbd69b4,{0xe1,0x3,0x0,0xaa,0x8,0xeb,0x4,0xd0,0x0,0xc9,0x47,0xf9,0x1,0x0,0x0,0x14}}, // lookup
    {0xbd69c4,{0xff,0x3,0x1,0xd1,0xf4,0x4f,0x2,0xa9,0xfd,0x7b,0x3,0xa9,0xfd,0xc3,0x0,0x91}}, // lookup_impl
    {0xb410e0,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0xf4,0x3,0x0,0xaa}}, // lookup_iterator
    {0xb41140,{0x28,0x0,0x40,0xb9,0x9,0x31,0x8,0xb,0xca,0xa2,0x8b,0x52,0xaa,0xda,0xaf,0x72}}, // lookup_hash
    {0xbd781c,{0xff,0x3,0x1,0xd1,0xf6,0x57,0x1,0xa9,0xf4,0x4f,0x2,0xa9,0xfd,0x7b,0x3,0xa9}}, // registrar
    {0xccc210,{0xfd,0x7b,0xbf,0xa9,0xfd,0x3,0x0,0x91,0x1e,0x85,0xff,0x97,0xfd,0x7b,0xc1,0xa8}}, // fixed_condition
    {0xccac30,{0x68,0x32,0x40,0xf9,0x68,0x0,0x0,0xb4,0x0,0x1,0x3f,0xd6,0x60,0x7,0x0,0x34}}, // fixed_executor
    {0xf13468,{0xff,0x43,0x3,0xd1,0xf6,0x57,0xa,0xa9,0xf4,0x4f,0xb,0xa9,0xfd,0x7b,0xc,0xa9}}, // animator_register
    {0xf13290,{0xff,0x43,0x3,0xd1,0xf6,0x57,0xa,0xa9,0xf4,0x4f,0xb,0xa9,0xfd,0x7b,0xc,0xa9}}, // animator_unregister
    {0xf072ec,{0xff,0xc3,0x0,0xd1,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}}, // animator_record_ctor
    {0xf1681c,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}}, // animator_append
    {0xa551fd0,{0x3c,0x7f,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x12,0x0,0x0,0x0,0x0,0x0},18,32572}, // rigidbody_type
    {0xa552000,{0xfe,0x81,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x12,0x0,0x0,0x0,0x0,0x0},18,33278}, // rigidbody2d_type
    {0xa50aae0,{0xf2,0x82,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x12,0x0,0x0,0x0,0x0,0x0},18,33522}, // cloth_type
    {0xa508ec0,{0x3e,0x7f,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x12,0x0,0x0,0x0,0x0,0x0},18,32574}, // character_controller_type
    {0xa51ebf0,{0xb4,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24244}, // fixed_update_type
    {0xa4efae0,{0x4e,0x78,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x12,0x0,0x0,0x0,0x0,0x0},18,30798}, // animator_type
    {0xa4fe720,{0x3e,0x78,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x12,0x0,0x0,0x0,0x0,0x0},18,30782}, // animation_type
    {0xa4feac0,{0x77,0x78,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,30839}, // animation_output_type
};
struct DirectorOutputRoute {uintptr_t vtable;CodeBinding producer;CodeBinding callbacks[2];uint32_t categories[2];uint8_t count;bool animation;};
struct DirectorRegistryProfile {uintptr_t manager_slot;bool tagged_queue;CodeBinding registry_getter,sample_category,rebuild,append,category,callbacks_rebuild,callbacks_dispatch,output_callbacks,drain,collect,enqueue,deferred_a,deferred_b,deferred_append_a,deferred_append_b,graph_create,graph_destroy,atomic_push,atomic_pop;DirectorOutputRoute outputs[3];};
inline constexpr DirectorRegistryProfile android_director_registry_profile={0x14e64c0,true,
    {0x731404,{0xa8,0x6d,0x0,0xb0,0x0,0x61,0x42,0xf9,0xc0,0x3,0x5f,0xd6,0xfe,0xf,0x1f,0xf8}}, // registry_getter
    {0x72f8c0,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0xf4,0x3,0x1,0x2a,0xf3,0x3,0x0,0xaa}}, // sample_category
    {0x72f96c,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x1,0xa9,0x8,0x74,0x50,0x39,0xa8,0x2,0x0,0x34}}, // rebuild
    {0x73093c,{0xfe,0x5f,0xbd,0xa9,0xf6,0x57,0x1,0xa9,0xf4,0x4f,0x2,0xa9,0x29,0xb0,0x42,0x39}}, // append
    {0x73061c,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0x28,0x0,0x80,0x52,0xf3,0x3,0x1,0x2a}}, // category
    {0x730364,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x1,0xa9,0x8,0x78,0x50,0x39,0x48,0x2,0x0,0x34}}, // callbacks_rebuild
    {0x7302f0,{0xfe,0xf,0x1d,0xf8,0xf6,0x57,0x1,0xa9,0xf4,0x4f,0x2,0xa9,0xf3,0x3,0x1,0x2a}}, // callbacks_dispatch
    {0x730a48,{0xff,0x3,0x3,0xd1,0xfd,0x7b,0x6,0xa9,0xfc,0x6f,0x7,0xa9,0xfa,0x67,0x8,0xa9}}, // output_callbacks
    {0x72fb78,{0xff,0x3,0x2,0xd1,0xfd,0x7b,0x2,0xa9,0xfc,0x6f,0x3,0xa9,0xfa,0x67,0x4,0xa9}}, // drain
    {0x72fe94,{0xfe,0xf,0x1a,0xf8,0xfc,0x6f,0x1,0xa9,0xfa,0x67,0x2,0xa9,0xf8,0x5f,0x3,0xa9}}, // collect
    {0x730464,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x1,0xa9,0xc3,0xd1,0xff,0xf0,0xf3,0x3,0x2,0xaa}}, // enqueue
    {0x7305ac,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0x8,0xcc,0x41,0xf9,0xf3,0x3,0x0,0xaa}}, // deferred_a
    {0x73052c,{0xfe,0xf,0x1e,0xf8,0xf4,0x4f,0x1,0xa9,0x8,0xdc,0x41,0xf9,0xf3,0x3,0x0,0xaa}}, // deferred_b
    {0x7306c0,{0xfe,0xf,0x1d,0xf8,0xf6,0x57,0x1,0xa9,0xf4,0x4f,0x2,0xa9,0x28,0x0,0x40,0xf9}}, // deferred_append_a
    {0x7304bc,{0xfe,0xf,0x1d,0xf8,0xf6,0x57,0x1,0xa9,0xf4,0x4f,0x2,0xa9,0x28,0x0,0x40,0xf9}}, // deferred_append_b
    {0x730834,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x1,0xa9,0xc3,0xd1,0xff,0xf0,0xf4,0x3,0x1,0xaa}}, // graph_create
    {0x73075c,{0xff,0xc3,0x0,0xd1,0xfe,0x57,0x1,0xa9,0xf4,0x4f,0x2,0xa9,0x28,0x0,0x40,0xf9}}, // graph_destroy
    {0x6f10cc,{0x8,0x24,0x7f,0xc8,0x8,0x24,0x2a,0xc8,0xca,0xff,0xff,0x35,0x28,0x0,0x0,0xf9}}, // atomic_push
    {0x6f115c,{0xa,0x24,0x7f,0xc8,0xa,0x24,0x28,0xc8,0xc8,0xff,0xff,0x35,0xe8,0x3,0xa,0xaa}}, // atomic_pop
    {
        {0x1423b70,{0x8e39b0,{0xfe,0x5f,0xbd,0xa9,0xf6,0x57,0x1,0xa9,0xf4,0x4f,0x2,0xa9,0x8,0x68,0x40,0xf9}},{{0x8b34d8,{0x21,0x0,0x80,0x52,0xe2,0x3,0x1f,0x2a,0xe3,0x3,0x1f,0x2a,0x1,0x0,0x0,0x14}},{0x8b3e70,{0x22,0x0,0x80,0x52,0xe1,0x3,0x1f,0x2a,0xe3,0x3,0x1f,0x2a,0x9b,0xfd,0xff,0x17}}},{3,4},2,true},
        {0x1426600,{0x94e438,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x1,0xa9,0x34,0x20,0x41,0xa9,0xf3,0x3,0x1,0xaa}},{{0x94dfc0,{0xff,0x83,0x5,0xd1,0xe8,0x7b,0x0,0xfd,0xfd,0x7b,0x10,0xa9,0xfc,0x6f,0x11,0xa9}},{0,{}}},{5,0},1,false},
        {0x1419648,{0x72df8c,{0xfe,0x57,0xbe,0xa9,0xf4,0x4f,0x1,0xa9,0x34,0x20,0x41,0xa9,0xf3,0x3,0x1,0xaa}},{{0x72dfe0,{0xff,0x83,0x4,0xd1,0xe8,0x5b,0x0,0xfd,0xfd,0x7b,0xc,0xa9,0xfc,0x6f,0xd,0xa9}},{0,{}}},{2,0},1,false},
    }
};
inline constexpr DirectorRegistryProfile ios_director_registry_profile={0xa8a8e00,false,
    {0xdc73a0,{0x8,0xd7,0x4,0xb0,0x0,0x1,0x47,0xf9,0xc0,0x3,0x5f,0xd6,0xfd,0x7b,0xbf,0xa9}}, // registry_getter
    {0xdc5838,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0xf4,0x3,0x1,0xaa}}, // sample_category
    {0xdc58e8,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}}, // rebuild
    {0xdc696c,{0xf8,0x5f,0xbc,0xa9,0xf6,0x57,0x1,0xa9,0xf4,0x4f,0x2,0xa9,0xfd,0x7b,0x3,0xa9}}, // append
    {0xdc6618,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0xf3,0x3,0x1,0xaa}}, // category
    {0xdc632c,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}}, // callbacks_rebuild
    {0xdc62b4,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}}, // callbacks_dispatch
    {0xdc6a6c,{0xff,0x43,0x3,0xd1,0xfc,0x6f,0x7,0xa9,0xfa,0x67,0x8,0xa9,0xf8,0x5f,0x9,0xa9}}, // output_callbacks
    {0xdc5b18,{0xff,0x3,0x2,0xd1,0xfc,0x6f,0x2,0xa9,0xfa,0x67,0x3,0xa9,0xf8,0x5f,0x4,0xa9}}, // drain
    {0xdc5e4c,{0xfc,0x6f,0xba,0xa9,0xfa,0x67,0x1,0xa9,0xf8,0x5f,0x2,0xa9,0xf6,0x57,0x3,0xa9}}, // collect
    {0xdc6448,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}}, // enqueue
    {0xdc65a4,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0xf3,0x3,0x0,0xaa}}, // deferred_a
    {0xdc6520,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0xf3,0x3,0x0,0xaa}}, // deferred_b
    {0xdc66c0,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}}, // deferred_append_a
    {0xdc64ac,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}}, // deferred_append_b
    {0xdc6870,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}}, // graph_create
    {0xdc6760,{0xff,0x43,0x1,0xd1,0xf6,0x57,0x2,0xa9,0xf4,0x4f,0x3,0xa9,0xfd,0x7b,0x4,0xa9}}, // graph_destroy
    {0xd87a1c,{0x8,0xfc,0x5f,0xc8,0x28,0x0,0x0,0xf9,0x1,0xfc,0x8,0xc8,0xa8,0xff,0xff,0x35}}, // atomic_push
    {0xd87a44,{0xe8,0x3,0x0,0xaa,0x0,0xfd,0x5f,0xc8,0xa0,0x0,0x0,0xb4,0x9,0x0,0x40,0xf9}}, // atomic_pop
    {
        {0x97f7688,{0xf3fa68,{0xf8,0x5f,0xbc,0xa9,0xf6,0x57,0x1,0xa9,0xf4,0x4f,0x2,0xa9,0xfd,0x7b,0x3,0xa9}},{{0xf0aa08,{0x21,0x0,0x80,0x52,0x2,0x0,0x80,0x52,0x3,0x0,0x80,0x52,0x1,0x0,0x0,0x14}},{0xf0b490,{0x1,0x0,0x80,0x52,0x22,0x0,0x80,0x52,0x3,0x0,0x80,0x52,0x5f,0xfd,0xff,0x17}}},{3,4},2,true},
        {0x97fa218,{0xfa37f8,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}},{{0xfa3394,{0xff,0x83,0x5,0xd1,0xe9,0x23,0xf,0x6d,0xfc,0x6f,0x10,0xa9,0xfa,0x67,0x11,0xa9}},{0,{}}},{5,0},1,false},
        {0x97f2140,{0xdc443c,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}},{{0xdc449c,{0xff,0x83,0x4,0xd1,0xe9,0x23,0xb,0x6d,0xfc,0x6f,0xc,0xa9,0xfa,0x67,0xd,0xa9}},{0,{}}},{2,0},1,false},
    }
};
} // namespace idoly_mp4_world
// END_ORIGINAL_WORLD_PROFILE

// A normal-MV export never needs the engine's FixedUpdate subtree: owned actor
// graphs use Normal Animator/GameTime evaluation, and its procedural jobs have
// their own explicit grants. The exact native loop-condition hook below holds
// the WHOLE subtree, including physics and inserted managed fixed delegates.
// Admission still requires a measured empty native-dynamics world; missing
// managed types are not treated as measured absence.
namespace idoly_mp4_world {
using Method=void;
enum class Result:int {ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};
struct FixedApi { bool(*original)()=nullptr;bool(*owner_thread)()=nullptr; };
class FixedGate {
    FixedApi api_{};
    alignas(8) uint64_t epoch_=0;
    alignas(4) uint32_t dirty_=0;
public:
    bool install(FixedApi api){
        if(installed()||__atomic_load_n(&epoch_,__ATOMIC_ACQUIRE)||!api.original||!api.owner_thread)return false;
        api_=api;return true;
    }
    bool installed()const{return api_.original&&api_.owner_thread;}
    bool acquire(uint64_t epoch){
        if(!epoch||!installed()||!api_.owner_thread()||__atomic_load_n(&dirty_,__ATOMIC_ACQUIRE))return false;
        uint64_t empty=0;
        if(!__atomic_compare_exchange_n(&epoch_,&empty,epoch,false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return false;
        return true;
    }
    bool healthy(uint64_t epoch)const{return epoch&&__atomic_load_n(&epoch_,__ATOMIC_ACQUIRE)==epoch
        &&!__atomic_load_n(&dirty_,__ATOMIC_ACQUIRE);}
    void release(uint64_t epoch){
        uint64_t owned=epoch;
        if(epoch)__atomic_compare_exchange_n(&epoch_,&owned,uint64_t(0),false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);
    }
    bool native_condition(){
        if(!api_.original)return false;
        if(__atomic_load_n(&epoch_,__ATOMIC_ACQUIRE)){
            if(api_.owner_thread())return false;
            // Unexpected entry must retain ordinary engine behavior, while
            // invalidating permission to rewind a now-unclosed physics world.
            __atomic_store_n(&dirty_,1u,__ATOMIC_RELEASE);
        }
        return api_.original();
    }
};
struct Api {
    bool(*source_current)(void*)=nullptr;
    bool(*clock_held)(void*)=nullptr;
    bool(*actor_jobs_closed)(void*)=nullptr;
    bool(*normal_animation_closed)(void*)=nullptr;
    bool(*routes_ready)()=nullptr;
    bool(*mapped)(uintptr_t,size_t)=nullptr;
    bool(*is_type)(void*,const char*)=nullptr;
    bool(*alive)(void*)=nullptr;
    uint32_t(*retain)(void*)=nullptr;
    void*(*retained)(uint32_t)=nullptr;
    void(*release_root)(uint32_t)=nullptr;
    size_t(*array_length)(void*)=nullptr;
    void*(*array_data)(void*)=nullptr;
    void*(*find_objects)(void*,bool,Method*)=nullptr;
    void*(*current_loop)(Method*)=nullptr;
    bool(*cloth_enabled)(void*,Method*)=nullptr;
    void*(*native_registry)()=nullptr;
    const void*(*native_type)(int32_t)=nullptr;
    void* rigidbody_type=nullptr;
    void* rigidbody2d_type=nullptr;
    void* cloth_type=nullptr;
    void* character_controller_type=nullptr;
    void* fixed_update_type=nullptr;
};
// Exact PlayerLoopSystemInternal value layout, excluding the managed box's
// 16-byte object header. Source getters return a NEW flat preorder array.
struct LoopEntry {void*type;void*delegate;uintptr_t update,condition;int32_t children,padding;};
static_assert(sizeof(LoopEntry)==40,"Original ARM64 PlayerLoop entry layout");
struct Registry {uintptr_t manager=0,buckets=0;uint32_t mask=0,count=0,empty=0;};
class Scope {
    Api api_{};FixedGate* gate_=nullptr;void* context_=nullptr;
    uint64_t epoch_=0;uintptr_t condition_=0;Registry saved_{};bool acquired_=false;
    const char*error_="none";
    Result fail(Result r,const char*e){error_=e;return r;}
    template<class T>bool read(uintptr_t at,T&v)const{
        if(!at||!api_.mapped(at,sizeof(T)))return false;
        ::memcpy(&v,reinterpret_cast<const void*>(at),sizeof(T));return true;
    }
    bool text(uintptr_t at,const char*name)const{
        for(size_t i=0;i<64;++i){char c=0;if(!read(at+i,c)||c!=name[i])return false;if(!c)return true;}return false;
    }
    bool rtti(uintptr_t at,uint32_t key,const char*name=nullptr)const{
        uint32_t id=0;uintptr_t str=0;
        return read(at+0x28,id)&&id==key&&read(at+0x10,str)&&str&&(!name||text(str,name));
    }
    static bool same(const Registry&a,const Registry&b){return a.manager==b.manager&&a.buckets==b.buckets
        &&a.mask==b.mask&&a.count==b.count&&a.empty==b.empty;}
    bool valid_api()const{return api_.source_current&&api_.clock_held&&api_.actor_jobs_closed&&api_.normal_animation_closed
        &&api_.routes_ready&&api_.mapped&&api_.is_type&&api_.alive&&api_.retain&&api_.retained&&api_.release_root
        &&api_.array_length&&api_.array_data&&api_.find_objects&&api_.current_loop&&api_.cloth_enabled
        &&api_.native_registry&&api_.native_type&&api_.rigidbody_type&&api_.rigidbody2d_type&&api_.cloth_type
        &&api_.character_controller_type&&api_.fixed_update_type;}
    struct Root {
        Api*api;uint32_t value=0;void*object=nullptr;
        Root(Api&a,void*v):api(&a),object(v){if(v)value=a.retain(v);}
        ~Root(){if(value)api->release_root(value);}
        bool valid()const{return value&&api->retained(value)==object;}
    };
    Result registry(Registry&out){
        out.manager=reinterpret_cast<uintptr_t>(api_.native_registry());
        if(!out.manager||!read(out.manager+0x40,out.buckets)||!read(out.manager+0x48,out.mask)
            ||!read(out.manager+0x4c,out.count)||!read(out.manager+0x50,out.empty))
            return fail(Result::unsupported,"world_native_registry_unavailable");
        const uint64_t extent=uint64_t(out.mask)+8,capacity=extent/8;
        if((out.mask&7)||!extent||(extent&(extent-1))||capacity>8192||!out.buckets
            ||out.count>capacity||out.empty>capacity||!api_.mapped(out.buckets,size_t(extent*3)))
            return fail(Result::unsupported,"world_native_registry_shape_differs");
        const uint32_t anchors[4]={54,50,183,143};const char*names[4]={"Rigidbody","Rigidbody2D","Cloth","CharacterController"};
        uintptr_t seen[4]{};uint32_t occupied=0;
        for(size_t i=0;i<capacity;++i){
            const uintptr_t at=out.buckets+i*24;uint32_t status=0,key=0;uintptr_t value=0;
            if(!read(at,status))return fail(Result::unsupported,"world_native_registry_unreadable");
            if(status>=0xfffffffeu)continue;
            if(status&3u)return fail(Result::unsupported,"world_native_registry_status_differs");
            if(!read(at+8,key)||!read(at+16,value)||!rtti(value,key))
                return fail(Result::unsupported,"world_native_registry_entry_differs");
            ++occupied;
            uintptr_t name=0;if(!read(value+0x10,name))return fail(Result::unsupported,"world_native_registry_entry_differs");
            // Check BOTH canonical serialized ID and actual registered name.
            // An unavailable managed Articulation type never supplies zero.
            if(key==171741748u||text(name,"ArticulationBody"))return fail(Result::unsupported,"world_articulation_registered");
            for(size_t j=0;j<4;++j)if(key==anchors[j]){
                if(seen[j]||!rtti(value,key,names[j]))return fail(Result::unsupported,"world_native_registry_anchor_differs");
                seen[j]=value;
            }
        }
        if(occupied!=out.count)return fail(Result::unsupported,"world_native_registry_count_differs");
        for(size_t j=0;j<4;++j)if(!seen[j]||reinterpret_cast<uintptr_t>(api_.native_type(int32_t(anchors[j])))!=seen[j])
            return fail(Result::unsupported,"world_native_registry_lookup_differs");
        if(api_.native_type(171741748))return fail(Result::unsupported,"world_articulation_registered");
        return Result::ok;
    }
    Result empty_dynamics(void*type,const char*name,bool cloth=false){
        void*array=api_.find_objects(type,false,nullptr);
        if(!array||!api_.is_type(array,"System.Array"))return fail(Result::unsupported,"world_dynamic_query_unavailable");
        Root root(api_,array);if(!root.valid())return fail(Result::failed,"world_query_root_failed");
        const size_t count=api_.array_length(array);
        if(count>8192)return fail(Result::unsupported,"world_dynamic_query_too_large");
        if(!cloth&&count)return fail(Result::unsupported,"world_active_native_dynamics");
        if(cloth&&count){
            auto*items=static_cast<uint8_t*>(api_.array_data(array));
            if(!items||!api_.mapped(reinterpret_cast<uintptr_t>(items),count*sizeof(void*)))
                return fail(Result::unsupported,"world_dynamic_query_invalid");
            for(size_t i=0;i<count;++i){void*object=nullptr;::memcpy(&object,items+i*sizeof(void*),sizeof(void*));
                if(!object||!api_.is_type(object,name)||!api_.alive(object))return fail(Result::stale,"world_dynamic_query_changed");
                if(api_.cloth_enabled(object,nullptr))return fail(Result::unsupported,"world_active_native_dynamics");
                if(!root.valid()||!api_.source_current(context_))return fail(Result::stale,"world_source_changed");
            }
        }
        return Result::ok;
    }
    Result loop(){
        void*array=api_.current_loop(nullptr);
        if(!array||!api_.is_type(array,"System.Array"))return fail(Result::unsupported,"world_playerloop_query_unavailable");
        Root root(api_,array);if(!root.valid())return fail(Result::failed,"world_query_root_failed");
        const size_t count=api_.array_length(array);auto*data=static_cast<uint8_t*>(api_.array_data(array));
        if(!count||count>2048||!data||!api_.mapped(reinterpret_cast<uintptr_t>(data),count*sizeof(LoopEntry)))
            return fail(Result::unsupported,"world_playerloop_shape_differs");
        int32_t remaining[64]{};size_t depth=0,fixed=0;
        for(size_t i=0;i<count;++i){
            while(depth&&remaining[depth-1]==0)--depth;
            if(i&&(!depth||--remaining[depth-1]<0))return fail(Result::unsupported,"world_playerloop_tree_differs");
            LoopEntry entry{};::memcpy(&entry,data+i*sizeof(LoopEntry),sizeof(entry));
            if(entry.children<0||size_t(entry.children)>count-i-1)return fail(Result::unsupported,"world_playerloop_tree_differs");
            if(entry.type==api_.fixed_update_type){
                ++fixed;
                if(entry.delegate||entry.update||entry.condition!=condition_||!entry.children)
                    return fail(Result::unsupported,"world_fixed_loop_condition_changed");
            }
            if(entry.children){if(depth==64)return fail(Result::unsupported,"world_playerloop_tree_too_deep");remaining[depth++]=entry.children;}
        }
        while(depth&&remaining[depth-1]==0)--depth;
        if(depth||fixed!=1)return fail(Result::unsupported,"world_fixed_loop_missing_or_duplicated");
        return root.valid()?Result::ok:fail(Result::stale,"world_playerloop_query_changed");
    }
    Result measure(Registry&state){
        if(!valid_api()||!context_||!condition_||!api_.routes_ready())return fail(Result::unsupported,"world_admission_api_unverified");
        if(!api_.source_current(context_))return fail(Result::stale,"world_source_changed");
        Result r=registry(state);if(r!=Result::ok)return r;
        for(size_t i=0;i<4;++i){void*type=i==0?api_.rigidbody_type:i==1?api_.rigidbody2d_type:i==2?api_.cloth_type:api_.character_controller_type;
            r=empty_dynamics(type,i==2?"UnityEngine.Cloth":"",i==2);if(r!=Result::ok)return r;
        }
        r=loop();if(r!=Result::ok)return r;
        if(!api_.actor_jobs_closed(context_))return fail(Result::unsupported,"world_unowned_actor_jobs");
        if(!api_.normal_animation_closed(context_))return fail(Result::unsupported,"world_fixed_animation_dependency");
        if(!api_.source_current(context_))return fail(Result::stale,"world_source_changed");
        Registry after{};r=registry(after);
        if(r!=Result::ok)return r;
        if(!same(state,after))return fail(Result::stale,"world_native_registry_changed");
        error_="none";return Result::ok;
    }
public:
    const char*error()const{return error_;}
    bool active()const{return acquired_;}
    Result admit(Api api,void*context,uintptr_t expected_condition){
        if(acquired_)return fail(Result::invalid,"world_already_owned");
        api_=api;context_=context;condition_=expected_condition;Registry state{};return measure(state);
    }
    bool configure(Api api,FixedGate*gate,void*context,uint64_t epoch,uintptr_t expected_condition){
        if(acquired_||!gate||!gate->installed()||!context||!epoch||!expected_condition)return false;
        api_=api;gate_=gate;context_=context;epoch_=epoch;condition_=expected_condition;return valid_api();
    }
    Result capture(){
        if(!gate_||!epoch_||!valid_api())return fail(Result::invalid,"world_not_configured");
        if(!api_.clock_held(context_))return fail(Result::waiting,"world_clock_not_held");
        Registry state{};const Result r=measure(state);if(r!=Result::ok)return r;
        if(!acquired_){if(!gate_->acquire(epoch_))return fail(Result::unsupported,"world_fixed_gate_busy");saved_=state;acquired_=true;}
        if(!same(saved_,state)||!gate_->healthy(epoch_))return fail(Result::stale,"world_fixed_gate_lost");
        return Result::ok;
    }
    Result quiesce(){
        // The empty-world measurement proves there is no native dynamics state
        // to read or fence. Close our fixed-subtree gate before scene setup.
        return capture();
    }
    Result validate(){
        if(!acquired_||!gate_||!gate_->healthy(epoch_))return fail(Result::stale,"world_fixed_gate_lost");
        Registry state{};const Result r=measure(state);if(r!=Result::ok)return r;
        return same(saved_,state)?Result::ok:fail(Result::stale,"world_native_registry_changed");
    }
    Result prepare(){return validate();}
    Result reset(){return validate();}
    Result restore(){
        if(!api_.clock_held||!api_.clock_held(context_))return fail(Result::waiting,"world_clock_not_held");
        return validate();
    }
    bool restorable(){return acquired_&&validate()==Result::ok;}
    Result release(bool){
        // Only our global gate lease is released. No old physics object or
        // scene pointer is touched, including source replacement cleanup.
        if(gate_&&acquired_)gate_->release(epoch_);
        acquired_=false;epoch_=0;gate_=nullptr;context_=nullptr;
        return Result::ok;
    }
};
} // namespace idoly_mp4_world


// BEGIN_ORIGINAL_ANIMATION_LOOP_PROFILE
namespace idoly_mp4_world {
struct AnimationPhaseBinding {const char* name;uintptr_t slot;CodeBinding callback;TypeBinding type;};
struct AnimationProfile {uintptr_t registry;bool indirect;CodeBinding executor;AnimationPhaseBinding phases[8];};
inline constexpr AnimationProfile android_animation_profile={0x14591a0,true,
    {0x640004,{0x8,0x63,0x40,0xf9,0x14,0xa3,0x1,0x91,0xa8,0x0,0x0,0xb4,0x8,0x1,0x40,0xf9}}, {
    {"DirectorSampleTime",0x3f8,{0x72f6e0,{0xa8,0x6d,0x0,0xf0,0x0,0x61,0x42,0xf9,0xbc,0x0,0x0,0x14,0xa8,0x6d,0x0,0xf0}},{0x9e27f40,{0x4f,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24143}},
    {"DirectorUpdate",0x5f0,{0x72f718,{0xa8,0x6d,0x0,0xf0,0x0,0x61,0x42,0xf9,0x41,0x0,0x80,0x52,0xbe,0x3,0x0,0x14}},{0x9e4ffc0,{0x92,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24210}},
    {"DirectorUpdateAnimationBegin",0x600,{0x72f790,{0xa8,0x6d,0x0,0xf0,0x0,0x61,0x42,0xf9,0x61,0x0,0x80,0x52,0xa0,0x3,0x0,0x14}},{0x9e3b0f0,{0x99,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24217}},
    {"LegacyAnimationUpdate",0x608,{0x8a5208,{0xfe,0xf,0x1f,0xf8,0x16,0x68,0xf6,0x97,0xa0,0x0,0x0,0x36,0xc8,0x62,0x0,0xb0}},{0x9e3b120,{0x9a,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24218}},
    {"DirectorUpdateAnimationEnd",0x610,{0x72f7a0,{0xa8,0x6d,0x0,0xf0,0x0,0x61,0x42,0xf9,0x81,0x0,0x80,0x52,0x9c,0x3,0x0,0x14}},{0x9e3b100,{0x9b,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24219}},
    {"DirectorDeferredEvaluate",0x618,{0x72f728,{0xfe,0x4f,0xbf,0xa9,0xb3,0x6d,0x0,0xf0,0x60,0x62,0x42,0xf9,0x7e,0x3,0x0,0x94}},{0x9e3b0e0,{0x9c,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24220}},
    {"DirectorLateUpdate",0x660,{0x72f744,{0xa8,0x6d,0x0,0xf0,0x0,0x61,0x42,0xf9,0xa1,0x0,0x80,0x52,0xb3,0x3,0x0,0x14}},{0x9e3ad60,{0xab,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24235}},
    {"DirectorRenderImage",0x6f8,{0x72f754,{0xfe,0xf,0x1f,0xf8,0xd4,0x3e,0xfc,0x97,0x60,0x1,0x0,0x36,0xfb,0x61,0x15,0x94}},{0x9e3ad70,{0xba,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24250}},
}};
inline constexpr AnimationProfile ios_animation_profile={0xa939448,false,
    {0xccac60,{0x8,0x63,0x40,0xf9,0xa8,0x0,0x0,0xb4,0x8,0x1,0x40,0xf9,0xc8,0x4,0x0,0xb4}}, {
    {"DirectorSampleTime",0x3f8,{0xdc5618,{0x8,0xd7,0x4,0xf0,0x0,0x1,0x47,0xf9,0xd0,0x0,0x0,0x14,0x8,0xd7,0x4,0xf0}},{0xa591e60,{0x7e,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24190}},
    {"DirectorUpdate",0x5f0,{0xdc5650,{0x8,0xd7,0x4,0xf0,0x0,0x1,0x47,0xf9,0x41,0x0,0x80,0x52,0xef,0x3,0x0,0x14}},{0xa5ba4a0,{0xc1,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24257}},
    {"DirectorUpdateAnimationBegin",0x600,{0xdc56d8,{0x8,0xd7,0x4,0xf0,0x0,0x1,0x47,0xf9,0x61,0x0,0x80,0x52,0xcd,0x3,0x0,0x14}},{0xa5a5420,{0xc8,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24264}},
    {"LegacyAnimationUpdate",0x608,{0xefcc40,{0xfd,0x7b,0xbf,0xa9,0xfd,0x3,0x0,0x91,0x83,0x35,0xf7,0x97,0xa0,0x0,0x0,0x34}},{0xa5a5450,{0xc9,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24265}},
    {"DirectorUpdateAnimationEnd",0x610,{0xdc56e8,{0x8,0xd7,0x4,0xf0,0x0,0x1,0x47,0xf9,0x81,0x0,0x80,0x52,0xc9,0x3,0x0,0x14}},{0xa5a5430,{0xca,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24266}},
    {"DirectorDeferredEvaluate",0x618,{0xdc5660,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x1,0xa9,0xfd,0x43,0x0,0x91,0x13,0xd7,0x4,0xf0}},{0xa5a5410,{0xcb,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24267}},
    {"DirectorLateUpdate",0x660,{0xdc5688,{0x8,0xd7,0x4,0xf0,0x0,0x1,0x47,0xf9,0xa1,0x0,0x80,0x52,0xe1,0x3,0x0,0x14}},{0xa5a5090,{0xda,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24282}},
    {"DirectorRenderImage",0x6f8,{0xdc5698,{0xfd,0x7b,0xbf,0xa9,0xfd,0x3,0x0,0x91,0xfc,0x12,0xfc,0x97,0x60,0x1,0x0,0x34}},{0xa5a50a0,{0xe9,0x5e,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x11,0x80,0x0,0x0,0x0,0x0},17,24297}},
}};
} // namespace idoly_mp4_world
// END_ORIGINAL_ANIMATION_LOOP_PROFILE

namespace idoly_mp4_world {
// Actual native loop callbacks have void(void) ABI. A grant is independent of
// deltaTime: frame/tick zero must run once, while every held retry runs none.
struct AnimationApi {void(*original[8])(){};bool(*owner_thread)()=nullptr;};
// Mandatory source/transaction checks around an actual Deferred-only original
// invocation. This is independent from an accepted simulation frame grant.
struct AnimationMaintenanceApi {
    void* context=nullptr;
    bool(*before)(void*,uint64_t)=nullptr;
    bool(*after)(void*,uint64_t)=nullptr;
};
class AnimationGate {
    AnimationApi api_{};
    alignas(8) uint64_t epoch_=0;
    alignas(4) uint32_t dirty_=0;
    uint64_t tick_=0;
    uint8_t next_=0,seen_=0;
    alignas(8) uint64_t permission_=0;
    bool have_tick_=false,pair_=false,inside_=false,maintenance_=false;
    bool open(uint64_t epoch)const{return epoch&&__atomic_load_n(&permission_,__ATOMIC_ACQUIRE)==epoch;}
    void close(){__atomic_store_n(&permission_,uint64_t(0),__ATOMIC_RELEASE);}
    void poison(){__atomic_store_n(&dirty_,1u,__ATOMIC_RELEASE);close();}
    bool original(unsigned phase){
        struct Boundary {
            AnimationGate& gate;bool complete=false;
            ~Boundary(){gate.inside_=false;if(!complete)gate.poison();}
        } boundary{*this};
        inside_=true;api_.original[phase]();boundary.complete=true;return true;
    }
public:
    bool installed()const{
        if(!api_.owner_thread)return false;
        for(unsigned i=0;i<8;++i)if(!api_.original[i])return false;
        return true;
    }
    bool install(AnimationApi api){
        if(installed()||__atomic_load_n(&epoch_,__ATOMIC_ACQUIRE)||!api.owner_thread)return false;
        for(unsigned i=0;i<8;++i)if(!api.original[i])return false;
        api_=api;return true;
    }
    bool acquire(uint64_t epoch){
        if(!epoch||!installed()||!api_.owner_thread()||__atomic_load_n(&dirty_,__ATOMIC_ACQUIRE))return false;
        uint64_t empty=0;
        if(!__atomic_compare_exchange_n(&epoch_,&empty,epoch,false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return false;
        have_tick_=pair_=inside_=maintenance_=false;close();tick_=0;next_=seen_=0;return true;
    }
    bool healthy(uint64_t epoch)const{return epoch&&__atomic_load_n(&epoch_,__ATOMIC_ACQUIRE)==epoch
        &&!__atomic_load_n(&dirty_,__ATOMIC_ACQUIRE);}
    bool closed(uint64_t epoch)const{return healthy(epoch)&&!open(epoch)&&!pair_&&!inside_;}
    // Read-only receipt for lifecycle caused by an actually executing accepted
    // native phase. Cleanup End after scalar revoke deliberately returns false.
    bool granted_inflight(uint64_t epoch)const{return healthy(epoch)&&inside_&&!maintenance_&&open(epoch);}
    // Successful grant, including the interval before its first original
    // callback. A merely prepared or revoked frame never satisfies this.
    bool issued_frame(uint64_t epoch,uint64_t tick)const{
        return healthy(epoch)&&have_tick_&&tick_==tick&&!maintenance_&&open(epoch);
    }
    // Revocation before even the first accepted original leaves no native
    // Begin/End or callback duty. A partial/dirty cycle never gets this proof.
    bool revoked_unconsumed_frame(uint64_t epoch,uint64_t tick)const{
        return healthy(epoch)&&have_tick_&&tick_==tick&&!inside_&&!maintenance_
            &&!pair_&&!open(epoch)&&!next_&&!seen_;
    }
    // Scalar-only observation of that SAME original's accepted position. This
    // cannot grant a frame or adopt a callback entered outside invoke(). The
    // owner-thread caller keeps the native original stack alive while reading.
    bool granted_phase(uint64_t epoch,uint64_t*tick,uint8_t*phase)const{
        if(tick){*tick=0;}
        if(phase){*phase=0;}
        if(!tick||!phase||!granted_inflight(epoch)||!have_tick_||!next_||next_>8
            ||seen_!=static_cast<uint8_t>((uint16_t(1)<<next_)-1))return false;
        *tick=tick_;*phase=static_cast<uint8_t>(next_-1);return true;
    }
    // Unlike closed(), a completed frame requires all eight actual originals
    // to have returned under the same healthy grant. Revoked/partial/Deferred-
    // only cycles cannot produce this receipt.
    bool completed_frame(uint64_t epoch,uint64_t tick)const{
        return healthy(epoch)&&have_tick_&&tick_==tick&&!inside_&&!maintenance_
            &&!pair_&&!open(epoch)&&next_==8&&seen_==255;
    }
    // A failed receipt during an actual accepted original invalidates this
    // frame even if its native cleanup still has to return normally.
    bool reject_inflight(uint64_t epoch)noexcept{
        if(!epoch||__atomic_load_n(&epoch_,__ATOMIC_ACQUIRE)!=epoch||!inside_||maintenance_)return false;
        poison();return true;
    }
    bool maintenance_inflight(uint64_t epoch)const{return healthy(epoch)&&inside_&&maintenance_&&!open(epoch)&&!pair_;}
    // Runs exactly the original DeferredEvaluate (phase5). Does not grant Time,
    // sample a frame, touch tick/seen/next, or create an animation Begin/End pair.
    // Caller keeps RNG isolated, all workers/Mono/render grants closed, and
    // supplies finite current+retired pending/producer receipts in both checks.
    bool maintenance(uint64_t epoch,AnimationMaintenanceApi checks){
        if(!checks.before||!checks.after||!api_.owner_thread||!api_.owner_thread()
            ||!closed(epoch)||maintenance_||!checks.before(checks.context,epoch)
            ||!closed(epoch))return false;
        struct Exit {
            AnimationGate&gate;bool complete=false;
            ~Exit(){gate.maintenance_=false;if(!complete)gate.poison();}
        } exit{*this};
        maintenance_=true;
        (void)original(5);
        if(!healthy(epoch)||!closed(epoch)||!checks.after(checks.context,epoch)||!closed(epoch)){
            poison();return false;
        }
        exit.complete=true;return true;
    }
    bool prepare(uint64_t epoch,uint64_t tick)const{
        return api_.owner_thread&&api_.owner_thread()&&closed(epoch)
            &&(!have_tick_?tick==0:tick_!=~uint64_t(0)&&tick==tick_+1);
    }
    bool grant(uint64_t epoch,uint64_t tick){
        if(!prepare(epoch,tick))return false;
        tick_=tick;have_tick_=true;next_=seen_=0;
        __atomic_store_n(&permission_,epoch,__ATOMIC_RELEASE);return true;
    }
    void revoke_grants(uint64_t epoch)noexcept{
        // Called on the loop-owning thread before any scene/receiver check.
        // This closes only permission. Keep a real native Begin/End pair and
        // its in-flight completion responsibility until original End arrives.
        uint64_t expected=epoch;
        if(epoch)(void)__atomic_compare_exchange_n(&permission_,&expected,uint64_t(0),false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);
    }
    bool invoke(unsigned phase){
        if(phase>=8||!installed())return false;
        const uint64_t epoch=__atomic_load_n(&epoch_,__ATOMIC_ACQUIRE);
        if(!epoch){api_.original[phase]();return true;}
        if(!api_.owner_thread()){
            // Preserve ordinary engine behavior on an unexpected thread and
            // permanently remove permission to rewind this global schedule.
            __atomic_store_n(&dirty_,1u,__ATOMIC_RELEASE);api_.original[phase]();return true;
        }
        if(inside_){poison();return false;}
        // If a broken/incomplete cycle already entered animation Begin, its
        // actual original End must still close the native pair. Cleanup never
        // invents a second End or calls it against a stale selected object.
        if(phase==4&&pair_&&(!open(epoch)||!healthy(epoch))){
            const bool called=original(phase);pair_=false;return called;
        }
        if(!open(epoch)||!healthy(epoch))return false;
        const uint8_t bit=static_cast<uint8_t>(1u<<phase);
        if(seen_&bit)return false;
        if(phase!=next_){poison();return false;}
        seen_|=bit;++next_;
        if(phase==2)pair_=true;
        const bool called=original(phase);
        if(phase==4)pair_=false;
        if(phase==7)close();
        return called;
    }
    bool release(uint64_t epoch){
        if(!epoch||!installed()||!api_.owner_thread()||pair_||inside_)return false;
        uint64_t owned=epoch;
        if(!__atomic_compare_exchange_n(&epoch_,&owned,uint64_t(0),false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return false;
        close();have_tick_=false;next_=seen_=0;return true;
    }
};

// Require the current original loop's typed leaf entries and native slot
// addresses. Custom delegates, duplicate/retargeted slots, child injection and
// reordered Begin/End pairs do not satisfy this closed scheduling contract.
inline bool animation_loop_matches(const Api& api,const AnimationProfile& profile,
        uintptr_t native_base,void*const* types,const uintptr_t* dispatch=nullptr){
    if(!api.current_loop||!api.is_type||!api.retain||!api.retained||!api.release_root
        ||!api.array_length||!api.array_data||!api.mapped||!types)return false;
    uintptr_t registry=native_base+profile.registry;
    if(registry<native_base)return false;
    if(profile.indirect){
        if(!api.mapped(registry,sizeof(uintptr_t)))return false;
        ::memcpy(&registry,reinterpret_cast<void*>(registry),sizeof(registry));
    }
    if(!registry)return false;
    for(unsigned phase=0;phase<8;++phase){
        if(!types[phase])return false;
        for(unsigned other=0;other<phase;++other)if(types[phase]==types[other])return false;
    }
    void* array=api.current_loop(nullptr);
    if(!array||!api.is_type(array,"System.Array"))return false;
    const uint32_t root=api.retain(array);if(!root)return false;
    struct Root {const Api&api;uint32_t root;~Root(){api.release_root(root);}} retained{api,root};
    if(api.retained(root)!=array)return false;
    const size_t count=api.array_length(array);auto*data=static_cast<uint8_t*>(api.array_data(array));
    if(!count||count>2048||!data||!api.mapped(reinterpret_cast<uintptr_t>(data),count*sizeof(LoopEntry)))return false;
    uint8_t seen=0;unsigned next=0;
    for(size_t index=0;index<count;++index){
        LoopEntry entry{};::memcpy(&entry,data+index*sizeof(entry),sizeof(entry));
        for(unsigned phase=0;phase<8;++phase){
            const auto& binding=profile.phases[phase];
            const uintptr_t expected_slot=registry+binding.slot,original_callback=native_base+binding.callback.rva;
            const uintptr_t expected_callback=dispatch?dispatch[phase]:original_callback;
            if(expected_slot<registry||original_callback<native_base||!expected_callback)return false;
            if(entry.type==types[phase]){
                const uint8_t bit=static_cast<uint8_t>(1u<<phase);
                if((seen&bit)||phase!=next||entry.delegate||entry.condition||entry.children
                    ||entry.update!=expected_slot||!api.mapped(expected_slot,sizeof(uintptr_t)))return false;
                uintptr_t actual=0;::memcpy(&actual,reinterpret_cast<void*>(expected_slot),sizeof(actual));
                if(actual!=expected_callback)return false;
                seen|=bit;++next;
            }else if(entry.update){
                if(entry.update==expected_slot)return false;
                if(api.mapped(entry.update,sizeof(uintptr_t))){
                    uintptr_t actual=0;::memcpy(&actual,reinterpret_cast<void*>(entry.update),sizeof(actual));
                    if(actual==expected_callback||actual==original_callback)return false;
                }
            }
        }
    }
    return seen==255u&&next==8&&api.retained(root)==array;
}
} // namespace idoly_mp4_world

namespace idoly_mp4_world {
struct AnimationRouteApi {bool(*mapped)(uintptr_t,size_t,bool writable)=nullptr;};
// The original native loop dereferences these writable callback-table cells on
// every phase. Owning the exact cells avoids patching tiny native tail thunks.
// Publication/restoration use compare-and-swap; another writer is never erased.
class AnimationRoutes {
    AnimationRouteApi api_{};uintptr_t slots_[8]{},originals_[8]{},dispatch_[8]{};
    uint8_t owned_=0;
    bool current(unsigned phase)const{
        return slots_[phase]&&api_.mapped&&api_.mapped(slots_[phase],sizeof(uintptr_t),false)
            &&__atomic_load_n(reinterpret_cast<const uintptr_t*>(slots_[phase]),__ATOMIC_ACQUIRE)==dispatch_[phase];
    }
public:
    uintptr_t original(unsigned phase)const{return phase<8?originals_[phase]:0;}
    const uintptr_t* dispatch()const{return dispatch_;}
    bool ready()const{
        if(owned_!=255u)return false;
        for(unsigned phase=0;phase<8;++phase)if(!current(phase))return false;
        return true;
    }
    bool install(AnimationRouteApi api,const AnimationProfile& profile,uintptr_t base,const uintptr_t* hooks){
        if(owned_||!api.mapped||!hooks)return false;
        uintptr_t registry=base+profile.registry;if(registry<base)return false;
        if(profile.indirect){
            if(!api.mapped(registry,sizeof(uintptr_t),false))return false;
            ::memcpy(&registry,reinterpret_cast<void*>(registry),sizeof(registry));
        }
        if(!registry)return false;
        // Verify ALL cells before publishing any hook. No class cache, node
        // offset or executable instruction is inferred or overwritten here.
        for(unsigned phase=0;phase<8;++phase){
            const uintptr_t slot=registry+profile.phases[phase].slot,original=base+profile.phases[phase].callback.rva;
            if(slot<registry||original<base||!hooks[phase]||(slot&(sizeof(uintptr_t)-1))
                ||!api.mapped(slot,sizeof(uintptr_t),true)
                ||__atomic_load_n(reinterpret_cast<const uintptr_t*>(slot),__ATOMIC_ACQUIRE)!=original)return false;
            for(unsigned previous=0;previous<phase;++previous)if(slot==slots_[previous]||hooks[phase]==hooks[previous])return false;
            slots_[phase]=slot;originals_[phase]=original;dispatch_[phase]=hooks[phase];
        }
        api_=api;
        for(unsigned phase=0;phase<8;++phase){
            uintptr_t expected=originals_[phase];
            if(!__atomic_compare_exchange_n(reinterpret_cast<uintptr_t*>(slots_[phase]),&expected,dispatch_[phase],false,
                    __ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)){(void)release();return false;}
            owned_|=static_cast<uint8_t>(1u<<phase);
        }
        if(ready())return true;
        (void)release();return false;
    }
    bool release(){
        for(unsigned phase=0;phase<8;++phase){
            const uint8_t bit=static_cast<uint8_t>(1u<<phase);if(!(owned_&bit))continue;
            if(!api_.mapped(slots_[phase],sizeof(uintptr_t),true))return false;
            uintptr_t expected=dispatch_[phase];
            (void)__atomic_compare_exchange_n(reinterpret_cast<uintptr_t*>(slots_[phase]),&expected,originals_[phase],false,
                __ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);
            owned_&=static_cast<uint8_t>(~bit);
        }
        return true;
    }
};
} // namespace idoly_mp4_world

namespace idoly_mp4_world {
struct AnimationGraph {uintptr_t handle=0;uint32_t version=0,padding=0;};
static_assert(sizeof(AnimationGraph)==16,"original_animation_graph_abi");
struct GlobalAnimationApi {
    Api world{};
    bool(*active_enabled)(void*,Method*)=nullptr;
    void(*animator_graph)(void*,AnimationGraph*,Method*)=nullptr;
    void*(*animator_controller)(void*,Method*)=nullptr;
    bool(*animator_bound)(void*,Method*)=nullptr;
    int32_t(*animator_mode)(void*,Method*)=nullptr;
    bool(*graph_valid)(AnimationGraph*,Method*)=nullptr;
    int32_t(*legacy_state_count)(void*,Method*)=nullptr;
    // Actual current source Actor/Director graph identity, independently
    // collected from selected live fields; no same-scene/name inference.
    bool(*graph_owned)(void*,void*,const AnimationGraph&)=nullptr;
    // Must close EVERY native AnimationPlayableOutput bound to this Animator
    // against actual outputs of the selected Actor/Director graphs. Its own
    // GetCurrentGraph is a separate field and is not that enumeration.
    bool(*bindings_owned)(void*,void*)=nullptr;
    void* animator_type=nullptr;
    void* animation_type=nullptr;
};
struct GlobalAnimationSummary {
    size_t animators=0,owned_animators=0,disabled_animators=0,dormant_animators=0,
        legacy=0,empty_legacy=0,disabled_legacy=0;
};
class GlobalAnimationAdmission {
    GlobalAnimationApi api_{};void*context_=nullptr;const char*error_="none";
    GlobalAnimationSummary summary_{};
    struct Root {
        const Api& api;void* value;uint32_t root;
        Root(const Api&a,void*v):api(a),value(v),root(a.retain(v)){}
        ~Root(){if(root)api.release_root(root);}
        bool current()const{return root&&api.retained(root)==value;}
    };
    Result fail(Result result,const char* error){error_=error;return result;}
    bool current()const{return context_&&api_.world.source_current(context_);}
    bool complete()const{
        const auto&w=api_.world;
        return w.source_current&&w.find_objects&&w.is_type&&w.alive&&w.retain&&w.retained
            &&w.release_root&&w.array_length&&w.array_data&&w.mapped&&api_.active_enabled
            &&api_.animator_graph&&api_.animator_controller&&api_.animator_bound&&api_.animator_mode
            &&api_.graph_valid&&api_.legacy_state_count&&api_.graph_owned&&api_.bindings_owned
            &&api_.animator_type&&api_.animation_type;
    }
    static bool same(const AnimationGraph&a,const AnimationGraph&b){return a.handle==b.handle&&a.version==b.version;}
    Result inspect_animator(void* animator){
        const bool active=api_.active_enabled(animator,nullptr);
        if(!active){++summary_.disabled_animators;return Result::ok;}
        AnimationGraph graph{};api_.animator_graph(animator,&graph,nullptr);
        const bool valid=api_.graph_valid(&graph,nullptr);
        void*controller=api_.animator_controller(animator,nullptr);
        const bool bound=api_.animator_bound(animator,nullptr);
        const int32_t mode=api_.animator_mode(animator,nullptr);
        if(!current())return fail(Result::stale,"world_animation_source_changed");
        if(controller&&(!api_.world.is_type(controller,"UnityEngine.RuntimeAnimatorController")||!api_.world.alive(controller)))
            return fail(Result::stale,"world_animator_controller_changed");
        // A standalone state machine has history beyond a Timeline's time.
        // Being in a loaded scene or under a selected Transform does not prove
        // its state can be restored by the source's graph reconstruction.
        if(controller)return fail(Result::unsupported,"world_stateful_animator_controller_unowned");
        if(!api_.bindings_owned(context_,animator))
            return fail(Result::unsupported,"world_active_animator_bindings_unowned");
        if(!bound){
            if(valid||graph.handle||graph.version)return fail(Result::unsupported,"world_animator_graph_unverified");
            // Native current-graph absence plus no controller/bound playables
            // is measured again below. No animation history can be granted.
            ++summary_.dormant_animators;
        }else{
            if(mode!=0)return fail(Result::unsupported,"world_animator_clock_mode_unowned");
            if((valid&&!api_.graph_owned(context_,animator,graph))||(!valid&&(graph.handle||graph.version)))
                return fail(Result::unsupported,"world_active_animator_graph_unowned");
            ++summary_.owned_animators;
        }
        AnimationGraph after{};api_.animator_graph(animator,&after,nullptr);
        if(!same(graph,after)||api_.graph_valid(&after,nullptr)!=valid
            ||api_.animator_controller(animator,nullptr)!=controller||api_.animator_bound(animator,nullptr)!=bound
            ||api_.animator_mode(animator,nullptr)!=mode||!api_.bindings_owned(context_,animator)
            ||!api_.active_enabled(animator,nullptr)||!current())
            return fail(Result::stale,"world_animator_state_changed_during_admission");
        return Result::ok;
    }
    Result inspect_legacy(void* animation){
        if(!api_.active_enabled(animation,nullptr)){++summary_.disabled_legacy;return Result::ok;}
        const int32_t count=api_.legacy_state_count(animation,nullptr);
        if(count<0||count>8192)return fail(Result::unsupported,"world_legacy_state_query_invalid");
        if(count)return fail(Result::unsupported,"world_active_legacy_animation_unowned");
        if(api_.legacy_state_count(animation,nullptr)!=count||!api_.active_enabled(animation,nullptr)||!current())
            return fail(Result::stale,"world_legacy_state_changed_during_admission");
        ++summary_.empty_legacy;return Result::ok;
    }
    Result family(bool legacy){
        auto&w=api_.world;void*array=w.find_objects(legacy?api_.animation_type:api_.animator_type,false,nullptr);
        if(!array||!w.is_type(array,"System.Array"))return fail(Result::unsupported,"world_animation_inventory_unavailable");
        Root root(w,array);if(!root.current())return fail(Result::failed,"world_animation_inventory_root_failed");
        const size_t count=w.array_length(array);auto*items=static_cast<uint8_t*>(w.array_data(array));
        if(count>8192||(count&&(!items||!w.mapped(reinterpret_cast<uintptr_t>(items),count*sizeof(void*)))))
            return fail(Result::unsupported,"world_animation_inventory_invalid");
        if(legacy)summary_.legacy=count;else summary_.animators=count;
        for(size_t index=0;index<count;++index){
            void*object=nullptr;::memcpy(&object,items+index*sizeof(void*),sizeof(object));
            if(!object||!w.is_type(object,legacy?"UnityEngine.Animation":"UnityEngine.Animator")||!w.alive(object))
                return fail(Result::stale,"world_animation_inventory_changed");
            const Result result=legacy?inspect_legacy(object):inspect_animator(object);
            if(result!=Result::ok)return result;
            if(!root.current()||!current())return fail(Result::stale,"world_animation_source_changed");
        }
        return Result::ok;
    }
public:
    const char*error()const{return error_;}
    const GlobalAnimationSummary&summary()const{return summary_;}
    Result admit(GlobalAnimationApi api,void*context){
        api_=api;context_=context;summary_=GlobalAnimationSummary{};error_="none";
        if(!complete())return fail(Result::unsupported,"world_animation_admission_api_unavailable");
        if(!current())return fail(Result::stale,"world_animation_source_changed");
        Result result=family(false);if(result==Result::ok)result=family(true);
        return result;
    }
};
} // namespace idoly_mp4_world

namespace idoly_mp4_world {
struct AnimationOutput {uintptr_t handle=0;uint32_t version=0,padding=0;};
struct AnimatorBindingLayout {
    // Both originals' typed registration/record constructor/append/get-target
    // bodies prove this exact list, widths and versioned handle identities.
    static constexpr size_t cached_ptr=0x10,data=0x168,count=0x178,capacity=0x180,registration_flags=0x194,
        record_bytes=0x28,output=0,graph=0x10;
};
struct AnimationBindingsApi {
    Api world{};
    bool(*output_valid)(AnimationOutput*,Method*)=nullptr;
    void*(*output_type)(AnimationOutput*,Method*)=nullptr;
    void*(*output_target)(AnimationOutput*,Method*)=nullptr;
    bool(*graph_valid)(AnimationGraph*,Method*)=nullptr;
    bool(*graph_owned)(void*,void*,const AnimationGraph&)=nullptr;
    void* animation_output_type=nullptr;
};
class AnimationBindingsAdmission {
    AnimationBindingsApi api_{};void*context_=nullptr;const char*error_="none";
    struct List {uintptr_t native=0,data=0;uint64_t count=0,capacity=0;uint8_t flags=0;};
    template<class T>bool read(uintptr_t address,T& value)const{
        if(!address||!api_.world.mapped(address,sizeof(T)))return false;
        ::memcpy(&value,reinterpret_cast<void*>(address),sizeof(value));return true;
    }
    bool same(const List&a,const List&b)const{return a.native==b.native&&a.data==b.data&&a.count==b.count&&a.capacity==b.capacity&&a.flags==b.flags;}
    bool list(void*animator,List& result)const{
        const uintptr_t object=reinterpret_cast<uintptr_t>(animator);
        if(object+AnimatorBindingLayout::cached_ptr<object||!read(object+AnimatorBindingLayout::cached_ptr,result.native)
            ||!result.native||result.native+AnimatorBindingLayout::registration_flags<result.native)return false;
        return read(result.native+AnimatorBindingLayout::data,result.data)
            &&read(result.native+AnimatorBindingLayout::count,result.count)
            &&read(result.native+AnimatorBindingLayout::capacity,result.capacity)
            &&read(result.native+AnimatorBindingLayout::registration_flags,result.flags);
    }
    Result fail(Result result,const char* error){error_=error;return result;}
public:
    const char*error()const{return error_;}
    Result admit(AnimationBindingsApi api,void*context,void*animator){
        api_=api;context_=context;error_="none";const auto&w=api_.world;
        if(!w.source_current||!w.mapped||!w.is_type||!w.alive||!w.retain||!w.retained||!w.release_root
            ||!api_.output_valid||!api_.output_type||!api_.output_target||!api_.graph_valid
            ||!api_.graph_owned||!api_.animation_output_type)return fail(Result::unsupported,"world_binding_api_unavailable");
        if(!context_||!w.source_current(context_)||!w.is_type(animator,"UnityEngine.Animator")||!w.alive(animator))
            return fail(Result::stale,"world_binding_animator_changed");
        const uint32_t token=w.retain(animator);if(!token)return fail(Result::failed,"world_binding_root_failed");
        struct Root {const Api&api;uint32_t token;~Root(){api.release_root(token);}} root{w,token};
        List snapshot{};
        if(w.retained(token)!=animator||!list(animator,snapshot)||snapshot.count>8192
            ||snapshot.count>(snapshot.capacity>>1)||(snapshot.count&&(!snapshot.data
                ||!w.mapped(snapshot.data,static_cast<size_t>(snapshot.count)*AnimatorBindingLayout::record_bytes))))
            return fail(Result::unsupported,"world_binding_vector_unverified");
        if(snapshot.flags&16u)return fail(Result::unsupported,"world_animator_binding_registration_suspended");
        for(size_t index=0;index<snapshot.count;++index){
            const uintptr_t address=snapshot.data+index*AnimatorBindingLayout::record_bytes;
            if(address<snapshot.data)return fail(Result::unsupported,"world_binding_vector_unverified");
            AnimationOutput output{};AnimationGraph graph{};
            if(!read(address+AnimatorBindingLayout::output,output)||!read(address+AnimatorBindingLayout::graph,graph)
                ||!output.handle||!graph.handle||!api_.output_valid(&output,nullptr)||!api_.graph_valid(&graph,nullptr))
                return fail(Result::stale,"world_binding_handle_changed");
            for(size_t previous=0;previous<index;++previous){
                AnimationOutput prior{};
                if(!read(snapshot.data+previous*AnimatorBindingLayout::record_bytes,prior))
                    return fail(Result::stale,"world_binding_vector_changed");
                if(prior.handle==output.handle&&prior.version==output.version)
                    return fail(Result::unsupported,"world_binding_duplicate_output");
            }
            if(api_.output_type(&output,nullptr)!=api_.animation_output_type
                ||api_.output_target(&output,nullptr)!=animator||!api_.graph_owned(context_,animator,graph))
                return fail(Result::unsupported,"world_binding_output_graph_unowned");
            List after{};AnimationOutput current_output{};AnimationGraph current_graph{};
            if(w.retained(token)!=animator||!w.alive(animator)||!w.source_current(context_)||!list(animator,after)||!same(snapshot,after)
                ||!read(address+AnimatorBindingLayout::output,current_output)||!read(address+AnimatorBindingLayout::graph,current_graph)
                ||current_output.handle!=output.handle||current_output.version!=output.version
                ||current_graph.handle!=graph.handle||current_graph.version!=graph.version)
                return fail(Result::stale,"world_binding_vector_changed");
        }
        List after{};
        if(w.retained(token)!=animator||!w.alive(animator)||!w.source_current(context_)||!list(animator,after)||!same(snapshot,after))
            return fail(Result::stale,"world_binding_vector_changed");
        return Result::ok;
    }
};
} // namespace idoly_mp4_world


// The global DirectorManager advances Script/Timeline/audio-only graphs too.
// This parser only observes bounded native collections. It never drains a queue
// or evaluates a graph, and its pure host queries must not call World.validate
// or Actor capture recursively.
namespace idoly_mp4_world {
struct DirectorGraphIdentity {
    uintptr_t native=0,slot=0;
    uint32_t version=0,mode=0,category=0;
    uint16_t status=0;
};
struct DirectorRetiredGraph {
    uintptr_t native=0,slot=0,source_asset=0;
    uint32_t version=0;
    uint64_t epoch=0,receipt=0;
};
struct DirectorPending {
    DirectorGraphIdentity graph{};
    uintptr_t record=0;
    // Native queue operations 0..6; 7=deferred completion vector388,
    // 8=deferred-evaluation vector3A8. These latter values are host tags.
    uint32_t operation=0;
};
struct DirectorAuthorization {
    uintptr_t native=0,slot=0,source_asset=0;
    uint32_t version=0,operation=0;
    uint64_t epoch=0,receipt=0;
};
struct DirectorRegistryApi {
    bool(*owner_thread)()=nullptr;
    bool(*source_current)(void*)=nullptr;
    uint64_t(*source_epoch)(void*)=nullptr;
    bool(*routes_ready)()=nullptr;
    bool(*mapped)(uintptr_t,size_t)=nullptr;
    // Exact current source fields/typed graph queries, not selected-scene or
    // Animator ancestry inference. These queries must be read-only/nonrecursive.
    bool(*current_graph)(void*,const DirectorGraphIdentity&)=nullptr;
    // Separate complete typed target/audio-state/script-userData+managed node
    // callback ownership. A recognized native output vtable alone is not this.
    bool(*output_closed)(void*,const DirectorGraphIdentity&,uintptr_t,uint32_t)=nullptr;
    // Return the BEFORE identity from an actual authorized original-operation
    // receipt. The parser independently requires version+2 AND a live pending
    // Destroy of the same native graph/slot before accepting this retirement.
    bool(*retired_graph)(void*,const DirectorGraphIdentity&,DirectorRetiredGraph*)=nullptr;
    // Used only by maintenance_ready, never to authorize ordinary admission.
    // Must prove captured callbacks and all simulation/Mono/render gates closed.
    bool(*maintenance_closed)(void*)=nullptr;
    bool(*pending_authorized)(void*,const DirectorPending&,DirectorAuthorization*)=nullptr;
    // Fallback only for an exact source-pinned entry whose bytes were replaced
    // by this process's verified typed hook. Must validate actual target,
    // original gateway and current installed patch/publication; never broad true.
    bool(*native_code_verified)(const CodeBinding&)=nullptr;
};
inline bool director_registry_profile_matches(const DirectorRegistryProfile& profile,uintptr_t base,
        bool(*mapped)(uintptr_t,size_t),bool(*native_code_verified)(const CodeBinding&)=nullptr){
    if(!mapped)return false;
    const CodeBinding* calls[]={&profile.registry_getter,&profile.sample_category,&profile.rebuild,&profile.append,
        &profile.category,&profile.callbacks_rebuild,&profile.callbacks_dispatch,&profile.output_callbacks,
        &profile.drain,&profile.collect,&profile.enqueue,&profile.deferred_a,&profile.deferred_b,
        &profile.deferred_append_a,&profile.deferred_append_b,&profile.graph_create,&profile.graph_destroy,
        &profile.atomic_push,&profile.atomic_pop};
    auto code=[&](const CodeBinding& call){const uintptr_t at=base+call.rva;
        if(!call.rva||at<base||!mapped(at,16))return false;
        return !::memcmp(reinterpret_cast<const void*>(at),call.prefix,16)
            ||(native_code_verified&&native_code_verified(call));};
    for(const auto* call:calls)if(!code(*call))return false;
    for(size_t i=0;i<3;++i){const auto& output=profile.outputs[i];
        if(output.count!=(output.animation?2u:1u)||!output.vtable||base+output.vtable<base
            ||!mapped(base+output.vtable+0x20,8)||!code(output.producer))return false;
        uintptr_t producer=0;::memcpy(&producer,reinterpret_cast<const void*>(base+output.vtable+0x20),8);
        if(producer!=base+output.producer.rva)return false;
        for(size_t j=0;j<output.count;++j)if(!code(output.callbacks[j])||output.categories[j]>6)return false;
    }
    return true;
}
struct DirectorRegistrySummary {
    size_t active=0,stopped=0,current=0,retiring=0,outputs=0,
        pending_valid=0,pending_stale=0,deferred_valid=0,callbacks=0;
    bool graphs_dirty=false,callbacks_dirty=false;
};
class DirectorRegistryAdmission {
    static constexpr size_t max_graphs=256,max_outputs=2048,max_pending=512,
        max_deferred=512,max_derived=1024,max_callbacks=256,max_callback_values=4096;
    struct Vector {uintptr_t data=0;uint64_t count=0,capacity=0;uint32_t allocator=0;};
    struct Graph {
        DirectorGraphIdentity id{};
        uintptr_t previous=0,next=0,output_previous=0,output_next=0;
        uint64_t counter=0,clock=0,delta=0;uint32_t scale=0;
        uint8_t busy=0,active=0,owner=0;
    };
    struct Output {uintptr_t native=0,previous=0,next=0,vtable=0,target=0;uint32_t graph=0,family=0,mode=0;};
    struct Pending {DirectorPending value{};uintptr_t next=0,slot=0;uint32_t version=0;uint8_t valid=0;};
    struct Deferred {DirectorPending value{};AnimationGraph handle{};uint8_t valid=0;};
    struct Derived {uintptr_t address=0,graph=0;uint8_t bytes[80]{};};
    struct Callback {uintptr_t address=0,function=0;Vector values{};uint32_t category=0;};
    struct CallbackValue {uintptr_t native=0;uint32_t callback=0,output=0;};
    struct Snapshot {
        uintptr_t manager=0,active_previous=0,active_next=0,stopped_previous=0,stopped_next=0,
            queue=0,queue_head=0;uint64_t queue_tag=0,epoch=0;
        uint8_t processing=0,inphase=0,graphs_dirty=0,callbacks_dirty=0;
        Vector a[7]{},b[7]{},callback[7]{},deferred[2]{};
        size_t graphs=0,outputs=0,pending=0,deferred_count=0,derived=0,callbacks=0,callback_values=0;
        Graph graph[max_graphs]{};Output output[max_outputs]{};Pending command[max_pending]{};
        Deferred deferred_value[max_deferred]{};Derived derived_value[max_derived]{};
        Callback callback_value[max_callbacks]{};CallbackValue callback_item[max_callback_values]{};
    } first_{},second_{};
    DirectorRegistryApi api_{};void* context_=nullptr;const DirectorRegistryProfile* profile_=nullptr;
    uintptr_t base_=0;uint64_t epoch_=0;bool measuring_=false;
    const char*error_="none";DirectorRegistrySummary summary_{};
    Result fail(Result r,const char* e){error_=e;return r;}
    bool current()const{return context_&&api_.owner_thread()&&api_.source_current(context_)
        &&api_.source_epoch(context_)==epoch_;}
    template<class T>bool read(uintptr_t at,T& value)const{
        if(!at||at+sizeof(T)<at||!api_.mapped(at,sizeof(T)))return false;
        ::memcpy(&value,reinterpret_cast<const void*>(at),sizeof(T));return true;
    }
    bool span(uintptr_t at,size_t count,size_t stride)const{
        return count<=(~size_t(0))/stride&&(!count||(at&&at+count*stride>=at&&api_.mapped(at,count*stride)));
    }
    bool vector(uintptr_t at,Vector& value,size_t limit,size_t stride)const{
        return read(at,value.data)&&read(at+8,value.allocator)&&read(at+16,value.count)
            &&read(at+24,value.capacity)&&value.count<=limit&&value.count<=(value.capacity>>1)
            &&span(value.data,static_cast<size_t>(value.count),stride);
    }
    static bool identity(const DirectorGraphIdentity&a,const DirectorGraphIdentity&b){
        return a.native==b.native&&a.slot==b.slot&&a.version==b.version;
    }
    int graph_index(const Snapshot&s,uintptr_t native)const{
        for(size_t i=0;i<s.graphs;++i)if(s.graph[i].id.native==native)return static_cast<int>(i);
        return -1;
    }
    int output_index(const Snapshot&s,uintptr_t native)const{
        for(size_t i=0;i<s.outputs;++i)if(s.output[i].native==native)return static_cast<int>(i);
        return -1;
    }
    bool graph_shape(uintptr_t native,Graph& graph)const{
        graph.id.native=native;
        if((native&7)||!span(native,1,0xf8)||!read(native,graph.previous)||!read(native+8,graph.next)
            ||!read(native+16,graph.id.slot)||!read(native+24,graph.id.mode)||graph.id.mode>3
            ||!read(native+32,graph.counter)||!read(native+40,graph.clock)
            ||!read(native+48,graph.id.category)||graph.id.category>6||!read(native+56,graph.delta)
            ||!read(native+64,graph.scale)||!read(native+0x78,graph.output_previous)
            ||!read(native+0x80,graph.output_next)||!read(native+0xac,graph.id.status)
            ||!read(native+0xc8,graph.busy))return false;
        if(!graph.id.slot)return true; // An unexposed stopped native graph can have no managed slot yet.
        uintptr_t resolved=0;
        return !(graph.id.slot&7)&&read(graph.id.slot+0x20,graph.id.version)&&!(graph.id.version&1)
            &&read(graph.id.slot+0x28,resolved)&&resolved==native;
    }
    Result list(Snapshot&s,bool active){
        const uintptr_t sentinel=s.manager+(active?0x368:0x378);uintptr_t previous=0,next=0;
        if(!read(sentinel,previous)||!read(sentinel+8,next)||!previous||!next)
            return fail(Result::unsupported,"world_director_list_unreadable");
        if(active){s.active_previous=previous;s.active_next=next;}else{s.stopped_previous=previous;s.stopped_next=next;}
        uintptr_t prior=sentinel;
        while(next!=sentinel){
            if(s.graphs==max_graphs||graph_index(s,next)>=0)return fail(Result::unsupported,"world_director_list_cycle_or_overflow");
            Graph& graph=s.graph[s.graphs];
            if(!graph_shape(next,graph)||graph.previous!=prior||!graph.next)
                return fail(Result::stale,"world_director_graph_identity_changed");
            if(graph.busy)return fail(Result::waiting,"world_director_graph_evaluating");
            graph.active=active?1:0;++s.graphs;prior=next;next=graph.next;
        }
        if(previous!=prior)return fail(Result::stale,"world_director_list_links_changed");
        return Result::ok;
    }
    // Resolves ONLY after the live slot version agrees. A stale public handle
    // is never dereferenced through its old resolved native object.
    Result resolve(const Snapshot&s,const AnimationGraph& handle,DirectorGraphIdentity& graph,bool& valid){
        valid=false;graph=DirectorGraphIdentity{};if(!handle.handle)return Result::ok;
        uint32_t version=0;
        if((handle.handle&7)||!read(handle.handle+0x20,version))return fail(Result::stale,"world_director_pending_slot_unreadable");
        if(version!=(handle.version&~uint32_t(1)))return Result::ok;
        uintptr_t native=0;if(!read(handle.handle+0x28,native))return fail(Result::stale,"world_director_pending_slot_unreadable");
        if(!native)return Result::ok;
        const int index=graph_index(s,native);
        if(index<0)return fail(Result::unsupported,"world_director_pending_graph_outside_registry");
        graph=s.graph[static_cast<size_t>(index)].id;
        if(graph.slot!=handle.handle||graph.version!=version)return fail(Result::stale,"world_director_pending_identity_changed");
        valid=true;return Result::ok;
    }
    Result pending(Snapshot&s){
        if(!read(s.manager+0x478,s.queue)||!s.queue||(s.queue&7)
            ||!read(s.queue,s.queue_head)||(profile_->tagged_queue&&!read(s.queue+8,s.queue_tag)))
            return fail(Result::unsupported,"world_director_queue_unavailable");
        uintptr_t next=s.queue_head;
        while(next){
            if(s.pending==max_pending)return fail(Result::unsupported,"world_director_queue_too_large");
            for(size_t i=0;i<s.pending;++i)if(s.command[i].value.record==next)
                return fail(Result::unsupported,"world_director_queue_cycle");
            Pending& item=s.command[s.pending++];item.value.record=next;
            if((next&7)||!span(next,1,32)||!read(next,item.next)||!read(next+8,item.slot)
                ||!read(next+16,item.version)||!read(next+24,item.value.operation))
                return fail(Result::stale,"world_director_queue_record_changed");
            AnimationGraph handle{item.slot,item.version,0};bool valid=false;
            Result result=resolve(s,handle,item.value.graph,valid);if(result!=Result::ok)return result;
            item.valid=valid?1:0;
            if(valid&&item.value.operation>6)return fail(Result::unsupported,"world_director_pending_operation_unverified");
            next=item.next;
        }
        for(size_t k=0;k<2;++k){
            if(!vector(s.manager+(k?0x3a8:0x388),s.deferred[k],max_deferred,16))
                return fail(Result::unsupported,"world_director_deferred_vector_unverified");
            for(size_t i=0;i<s.deferred[k].count;++i){
                if(s.deferred_count==max_deferred)return fail(Result::unsupported,"world_director_deferred_too_large");
                Deferred& item=s.deferred_value[s.deferred_count++];item.value.record=s.deferred[k].data+i*16;
                item.value.operation=k?8:7;
                if(!read(item.value.record,item.handle))return fail(Result::stale,"world_director_deferred_changed");
                bool valid=false;Result result=resolve(s,item.handle,item.value.graph,valid);if(result!=Result::ok)return result;
                item.valid=valid?1:0;
            }
        }
        return Result::ok;
    }
    bool destroy_pending(const Snapshot&s,const DirectorGraphIdentity& graph)const{
        for(size_t i=0;i<s.pending;++i)if(s.command[i].valid&&s.command[i].value.operation==2
            &&identity(s.command[i].value.graph,graph))return true;
        return false;
    }
    bool retirement(const Snapshot&s,const DirectorGraphIdentity& graph)const{
        if(!api_.retired_graph||!destroy_pending(s,graph))return false;
        DirectorRetiredGraph old{};
        return api_.retired_graph(context_,graph,&old)&&old.epoch==epoch_&&old.receipt&&old.source_asset
            &&old.native==graph.native&&old.slot==graph.slot&&!(old.version&1)
            &&old.version<=(~uint32_t(0))-2&&old.version+2==graph.version;
    }
    Result ownership(Snapshot&s){
        for(size_t i=0;i<s.graphs;++i){Graph& graph=s.graph[i];
            if(graph.id.slot&&api_.current_graph(context_,graph.id))graph.owner=1;
            else if(graph.id.slot&&retirement(s,graph.id))graph.owner=2;
            if(!current())return fail(Result::stale,"world_director_source_changed");
            if(graph.active&&!graph.owner)return fail(Result::unsupported,"world_active_director_graph_unowned");
        }
        for(size_t i=0;i<s.pending;++i)if(s.command[i].valid){const int index=graph_index(s,s.command[i].value.graph.native);
            if(index<0||!s.graph[static_cast<size_t>(index)].owner)return fail(Result::unsupported,"world_director_pending_graph_unowned");
            if(s.graph[static_cast<size_t>(index)].owner==2&&s.command[i].value.operation!=2)
                return fail(Result::unsupported,"world_director_retired_operation_unverified");}
        for(size_t i=0;i<s.deferred_count;++i)if(s.deferred_value[i].valid){const int index=graph_index(s,s.deferred_value[i].value.graph.native);
            if(index<0||!s.graph[static_cast<size_t>(index)].owner)return fail(Result::unsupported,"world_director_deferred_graph_unowned");
            if(s.graph[static_cast<size_t>(index)].owner==2)return fail(Result::unsupported,"world_director_retired_operation_unverified");}
        return Result::ok;
    }
    Result outputs(Snapshot&s){
        for(size_t g=0;g<s.graphs;++g){const Graph& graph=s.graph[g];
            if(!graph.owner)continue;
            const uintptr_t sentinel=graph.id.native+0x78;uintptr_t next=graph.output_next,prior=sentinel;
            if(!next||!graph.output_previous)return fail(Result::unsupported,"world_director_output_list_unavailable");
            while(next!=sentinel){
                if(s.outputs==max_outputs||next<8||output_index(s,next-8)>=0)
                    return fail(Result::unsupported,"world_director_output_cycle_or_overflow");
                Output& item=s.output[s.outputs++];item.native=next-8;item.graph=static_cast<uint32_t>(g);
                if((next&7)||!read(next,item.previous)||!read(next+8,item.next)||item.previous!=prior||!item.next
                    ||!read(item.native,item.vtable))return fail(Result::stale,"world_director_output_list_changed");
                bool known=false;
                for(size_t k=0;k<3;++k)if(item.vtable==base_+profile_->outputs[k].vtable){
                    const auto& route=profile_->outputs[k];uintptr_t producer=0;
                    if(!read(item.vtable+0x20,producer)||producer!=base_+route.producer.rva)
                        return fail(Result::unsupported,"world_director_output_producer_changed");
                    item.family=static_cast<uint32_t>(k);known=true;
                    if(route.animation){
                        if(!read(item.native+0xd0,item.target))return fail(Result::stale,"world_director_animation_output_target_changed");
                        if(item.target&&(!read(item.target+0x190,item.mode)||item.mode>2))
                            return fail(Result::unsupported,"world_director_animation_output_mode_unverified");
                    }
                    break;
                }
                if(!known)return fail(Result::unsupported,"world_director_output_type_unverified");
                if(!api_.output_closed(context_,graph.id,item.native,item.family))
                    return fail(Result::unsupported,"world_director_output_state_unowned");
                if(!current())return fail(Result::stale,"world_director_source_changed");
                prior=next;next=item.next;
            }
            if(prior!=graph.output_previous)return fail(Result::stale,"world_director_output_list_changed");
        }
        return Result::ok;
    }
    bool callback_route(const Output& output,uintptr_t function,uint32_t category)const{
        const auto& route=profile_->outputs[output.family];
        for(size_t k=0;k<route.count;++k){const uint32_t actual=route.animation&&output.target&&output.mode==1
                ?static_cast<uint32_t>(k):route.categories[k];
            if(function==base_+route.callbacks[k].rva&&category==actual)return true;}
        return false;
    }
    Result derived(Snapshot&s){
        for(size_t k=0;k<7;++k){
            if(!s.graphs_dirty){
                for(unsigned b=0;b<2;++b){Vector& v=b?s.b[k]:s.a[k];
                    if(!vector(s.manager+(b?0x170:0x90)+k*32,v,max_derived,80))
                        return fail(Result::unsupported,"world_director_dispatch_vector_unverified");
                    for(size_t i=0;i<v.count;++i){
                        if(s.derived==max_derived)return fail(Result::unsupported,"world_director_dispatch_too_large");
                        Derived& item=s.derived_value[s.derived++];item.address=v.data+i*80;
                        if(!api_.mapped(item.address,80))return fail(Result::stale,"world_director_dispatch_changed");
                        ::memcpy(item.bytes,reinterpret_cast<const void*>(item.address),80);::memcpy(&item.graph,item.bytes+72,8);
                        const int index=graph_index(s,item.graph);
                        if(index<0)return fail(Result::unsupported,"world_director_dispatch_graph_outside_registry");
                        const Graph& graph=s.graph[static_cast<size_t>(index)];
                        if(!graph.active||!graph.owner||graph.id.category!=k||bool(graph.id.status&4)==bool(b))
                            return fail(Result::unsupported,"world_director_dispatch_graph_unowned");
                        for(size_t j=0;j+1<s.derived;++j)if(s.derived_value[j].graph==item.graph)
                            return fail(Result::unsupported,"world_director_duplicate_dispatch_graph");
                    }
                }
            }
            if(!s.callbacks_dirty){
                if(!vector(s.manager+0x250+k*32,s.callback[k],max_callbacks,40))
                    return fail(Result::unsupported,"world_director_callback_vector_unverified");
                for(size_t i=0;i<s.callback[k].count;++i){
                    if(s.callbacks==max_callbacks)return fail(Result::unsupported,"world_director_callbacks_too_large");
                    Callback& item=s.callback_value[s.callbacks];item.address=s.callback[k].data+i*40;item.category=static_cast<uint32_t>(k);
                    if(!read(item.address,item.function)||!item.function||!vector(item.address+8,item.values,max_callback_values,8))
                        return fail(Result::unsupported,"world_director_callback_payload_unverified");
                    if(!item.values.count)return fail(Result::unsupported,"world_director_empty_callback_group");
                    for(size_t q=0;q<s.callbacks;++q)if(s.callback_value[q].function==item.function&&s.callback_value[q].category==k)
                        return fail(Result::unsupported,"world_director_duplicate_callback_group");
                    for(size_t j=0;j<item.values.count;++j){
                        if(s.callback_values==max_callback_values)return fail(Result::unsupported,"world_director_callback_payload_too_large");
                        CallbackValue& value=s.callback_item[s.callback_values++];value.callback=static_cast<uint32_t>(s.callbacks);
                        if(!read(item.values.data+j*8,value.native))return fail(Result::stale,"world_director_callback_payload_changed");
                        const int index=output_index(s,value.native);
                        if(index<0)return fail(Result::unsupported,"world_director_callback_output_unowned");
                        value.output=static_cast<uint32_t>(index);const Output& output=s.output[static_cast<size_t>(index)];
                        if(!s.graph[output.graph].active||!callback_route(output,item.function,static_cast<uint32_t>(k)))
                            return fail(Result::unsupported,"world_director_callback_route_unverified");
                        for(size_t q=0;q+1<s.callback_values;++q){const auto& old=s.callback_item[q];const auto& old_callback=s.callback_value[old.callback];
                            if(old.native==value.native&&old_callback.function==item.function&&old_callback.category==k)
                                return fail(Result::unsupported,"world_director_duplicate_callback_output");}
                    }
                    ++s.callbacks;
                }
            }
        }
        if(!s.graphs_dirty){size_t active=0;for(size_t i=0;i<s.graphs;++i)if(s.graph[i].active)++active;
            if(s.derived!=active)return fail(Result::unsupported,"world_director_dispatch_incomplete");}
        return Result::ok;
    }
    Result observe(Snapshot&s){
        ::memset(static_cast<void*>(&s),0,sizeof(s));s.epoch=epoch_;
        if(!current())return fail(Result::stale,"world_director_source_changed");
        if(base_+profile_->manager_slot<base_||!read(base_+profile_->manager_slot,s.manager)
            ||!s.manager||(s.manager&7)||!span(s.manager,1,0x490)
            ||!read(s.manager+0x41a,s.processing)||!read(s.manager+0x41b,s.inphase)
            ||!read(s.manager+0x41d,s.graphs_dirty)||!read(s.manager+0x41e,s.callbacks_dirty))
            return fail(Result::unsupported,"world_director_registry_unavailable");
        if(s.processing||s.inphase)return fail(Result::waiting,"world_director_phase_in_progress");
        if(s.graphs_dirty>1||s.callbacks_dirty>1)return fail(Result::unsupported,"world_director_dirty_flags_unverified");
        Result result=list(s,true);if(result==Result::ok)result=list(s,false);
        if(result==Result::ok)result=pending(s);
        if(result==Result::ok)result=ownership(s);
        if(result==Result::ok)result=outputs(s);
        if(result==Result::ok)result=derived(s);
        return result;
    }
    bool api_ready()const{return api_.owner_thread&&api_.source_current&&api_.source_epoch&&api_.routes_ready
        &&api_.mapped&&api_.current_graph&&api_.output_closed;}
    Result measure(DirectorRegistryApi api,void*context,const DirectorRegistryProfile&profile,uintptr_t base){
        if(measuring_)return fail(Result::invalid,"world_director_recursive_query");
        api_=api;context_=context;profile_=&profile;base_=base;summary_=DirectorRegistrySummary{};
        if(!api_ready()||!context_||!api_.routes_ready()||!api_.owner_thread()
            ||!director_registry_profile_matches(profile,base,api_.mapped,api_.native_code_verified))
            return fail(Result::unsupported,"world_director_registry_api_unverified");
        epoch_=api_.source_epoch(context_);if(!epoch_)return fail(Result::stale,"world_director_source_changed");
        measuring_=true;struct Exit{bool& flag;~Exit(){flag=false;}} exit{measuring_};
        Result result=observe(first_);if(result!=Result::ok)return result;
        result=observe(second_);if(result!=Result::ok)return fail(Result::stale,"world_director_registry_changed");
        if(!current()||::memcmp(&first_,&second_,sizeof(first_)))return fail(Result::stale,"world_director_registry_changed");
        for(size_t i=0;i<first_.graphs;++i){const auto& graph=first_.graph[i];
            if(graph.active)++summary_.active;else ++summary_.stopped;
            if(graph.owner==1)++summary_.current;else if(graph.owner==2)++summary_.retiring;
        }
        for(size_t i=0;i<first_.pending;++i)if(first_.command[i].valid)++summary_.pending_valid;else ++summary_.pending_stale;
        for(size_t i=0;i<first_.deferred_count;++i)if(first_.deferred_value[i].valid)++summary_.deferred_valid;
        summary_.outputs=first_.outputs;summary_.callbacks=first_.callbacks;
        summary_.graphs_dirty=first_.graphs_dirty;summary_.callbacks_dirty=first_.callbacks_dirty;error_="none";return Result::ok;
    }
    bool authorized(const DirectorPending& value)const{
        if(!api_.pending_authorized)return false;
        DirectorAuthorization receipt{};
        return api_.pending_authorized(context_,value,&receipt)&&receipt.epoch==epoch_&&receipt.receipt
            &&receipt.source_asset&&receipt.native==value.graph.native&&receipt.slot==value.graph.slot
            &&receipt.version==value.graph.version&&receipt.operation==value.operation;
    }
public:
    const char*error()const{return error_;}
    const DirectorRegistrySummary&summary()const{return summary_;}
    Result admit(DirectorRegistryApi api,void*context,const DirectorRegistryProfile&profile,uintptr_t base){return measure(api,context,profile,base);}
    Result graph_quiescent(DirectorRegistryApi api,void*context,const DirectorRegistryProfile&profile,uintptr_t base,AnimationGraph target){
        Result result=measure(api,context,profile,base);if(result!=Result::ok)return result;
        DirectorGraphIdentity graph{};bool valid=false;result=resolve(first_,target,graph,valid);
        if(result!=Result::ok)return result;
        if(!valid)return fail(Result::stale,"world_director_target_graph_changed");
        const int index=graph_index(first_,graph.native);
        if(index<0||!first_.graph[static_cast<size_t>(index)].owner)return fail(Result::unsupported,"world_director_target_graph_unowned");
        for(size_t i=0;i<first_.pending;++i)if(first_.command[i].valid&&identity(first_.command[i].value.graph,graph))
            return fail(Result::waiting,"world_director_target_operation_pending");
        for(size_t i=0;i<first_.deferred_count;++i)if(first_.deferred_value[i].valid&&identity(first_.deferred_value[i].value.graph,graph))
            return fail(Result::waiting,"world_director_target_operation_pending");
        return Result::ok;
    }
    // This is ONLY a permission query. The owner may call the already-installed
    // original DeferredEvaluate entry once after its captured/gated/RNG checks.
    // Admission alone, or a same-target match, never grants maintenance.
    Result maintenance_ready(DirectorRegistryApi api,void*context,const DirectorRegistryProfile&profile,uintptr_t base){
        Result result=measure(api,context,profile,base);if(result!=Result::ok)return result;
        if(!api_.maintenance_closed||!api_.pending_authorized||!api_.maintenance_closed(context_))
            return fail(Result::unsupported,"world_director_maintenance_not_captured");
        bool work=false;
        for(size_t i=0;i<first_.pending;++i)if(first_.command[i].valid){work=true;
            if(!authorized(first_.command[i].value))return fail(Result::unsupported,"world_director_pending_receipt_missing");}
        for(size_t i=0;i<first_.deferred_count;++i)if(first_.deferred_value[i].valid){work=true;
            if(!authorized(first_.deferred_value[i].value))return fail(Result::unsupported,"world_director_pending_receipt_missing");}
        if(!current()||!api_.maintenance_closed(context_))return fail(Result::stale,"world_director_source_changed");
        result=observe(second_);if(result!=Result::ok)return result;
        if(::memcmp(&first_,&second_,sizeof(first_)))return fail(Result::stale,"world_director_registry_changed");
        return work?Result::ok:fail(Result::invalid,"world_director_no_pending_maintenance");
    }
};
} // namespace idoly_mp4_world
