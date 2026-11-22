"""Run the production dependency aggregation over explicitly modeled parts.

These tests check phase transactions, roots and source generations; they are
not a simulation of Unity rendering, particles, native physics or codecs.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def aggregate(tmp_path_factory):
    compiler=shutil.which("c++")
    if not compiler:pytest.skip("Host C++ compiler required")
    bridge=(ROOT/"client-presentation/native/bridge.cpp").read_text()
    production=(ROOT/"client-presentation/native/bridge.cpp").read_text().split("// BEGIN_MP4_SCENE_AGGREGATE",1)[1].split("// END_MP4_SCENE_AGGREGATE",1)[0]
    def function(signature):
        start=bridge.index(signature);opening=bridge.index('{',start);depth=1;end=opening+1
        while depth:
            depth+=(bridge[end]=='{')-(bridge[end]=='}');end+=1
        return bridge[start:end]
    callgraph='\n'.join(function(sig)for sig in ('bool mp4_world_source_current(', '[[maybe_unused]] bool mp4_world_fixed_subtree_closed(', 'bool mp4_camera_source_current('))
    harness=r'''
#include "mp4_game_adapter.hpp"
#include <cassert>
#include <map>
#include <string>
#include <stdexcept>
#include <vector>
using R=idoly_mp4_playback::Result;
using W=idoly_mp4_game::SceneWitness;
W live{reinterpret_cast<void*>(1),reinterpret_cast<void*>(2),reinterpret_cast<void*>(3),
    reinterpret_cast<void*>(4),reinterpret_cast<void*>(5),reinterpret_cast<void*>(6),
    reinterpret_cast<void*>(7),reinterpret_cast<void*>(8),reinterpret_cast<void*>(9),reinterpret_cast<void*>(10),reinterpret_cast<void*>(11),reinterpret_cast<void*>(12),7};
bool on_thread=true,witness_available=true,automatic=true,held=true,mp4_api_installed=true;unsigned witness_calls=0;
bool game_call(){return on_thread;}
bool driving_permission=true;bool mp4_world_driving_permission(){return driving_permission;}
bool mp4_exact_type(void*p,const char*){return p==reinterpret_cast<void*>(13);}
bool mp4_alive(void*p){return p!=nullptr;}
struct GameApi{void* director_get_asset(void*,void*){return reinterpret_cast<void*>(13);}}mp4_api;
int actor_globals=0,camera_globals=0,actor_withdrawn=0,camera_withdrawn=0;
void mp4_actor_withdraw_interception()noexcept{++actor_withdrawn;}
void mp4_camera_withdraw_interception()noexcept{++camera_withdrawn;}
struct RngLease{void restore_rng_before_source_change(){++actor_globals;}void abandon_rng_before_source_change(){++actor_globals;}}mp4_actor_mono_gate;
void mp4_shader_lease_abandon(void*)noexcept{}
void mp4_audio_abandon_globals()noexcept{}
void mp4_stage_withdraw_interception()noexcept{}
unsigned admission_drops=0,admission_withdrawals=0;bool admission_receipt=true;int admission_throw=-1;
void mp4_source_director_plan_withdraw()noexcept{}
void mp4_root_capture_withdraw()noexcept{}
void mp4_srp_source_withdraw()noexcept{}
bool mp4_source_director_plan_drop(){return true;}
void mp4_stage_admission_drop()noexcept{++admission_drops;admission_receipt=false;}
void mp4_stage_admission_withdraw()noexcept{++admission_withdrawals;admission_receipt=false;}
void mp4_camera_abandon_globals_before_source_change()noexcept{++camera_globals;}
void mp4_camera_restore_globals_before_source_change(){++camera_globals;}
std::map<uint32_t,void*> roots;uint32_t nextroot=1;int allocation_fail_after=-1;
uint32_t mp4_retain(void* p){if(allocation_fail_after==0)return 0;if(allocation_fail_after>0)--allocation_fail_after;roots[nextroot]=p;return nextroot++;}
void* weak_get(uint32_t h){auto i=roots.find(h);return i==roots.end()?nullptr:i->second;}
void weak_free(uint32_t h){roots.erase(h);}
namespace idoly_mp4_runtime {
struct Job{uint64_t generation=17;}job;
struct Game{idoly_mp4_playback::Phase automatic_rebuild_phase(){return idoly_mp4_playback::Phase::held;}uint64_t owned_scene_generation(){return live.generation;}bool selected_scene_witness(W& w){++witness_calls;if(!witness_available)return false;w=live;return true;}bool automatic(){return ::automatic;}}game;
struct Clock{bool held(){return ::held;}}clock;
Clock& native_clock_scope(){return clock;}
}
bool mp4_root_history_initial_sealed(uint64_t){return false;}
idoly_mp4_playback::Result mp4_scene_source_bootstrap_quiesce(){return idoly_mp4_playback::Result::unsupported;}
idoly_mp4_playback::Result mp4_scene_source_bootstrap_release(){return idoly_mp4_playback::Result::ok;}
unsigned final_handoff=0;bool final_handoff_wait=false;
idoly_mp4_playback::Result mp4_scene_source_bootstrap_before_part_release(bool own){
    if(own){++final_handoff;if(final_handoff_wait){assert(!actor_withdrawn&&!camera_withdrawn);return R::waiting;}}
    return R::ok;
}
R mp4_gpu_initial_source_advance(uint64_t,uint64_t,uint64_t*out){*out=1;return R::ok;}
bool mp4_gpu_initial_source_fenced(uint64_t,uint64_t){return true;}
// PRODUCTION
Mp4SceneResult mp4_root_capture_part(size_t,const Mp4ScenePart&part){return part.capture(part.context);}
struct ScopeWitness{bool active(){return true;}bool frame_granted(){return true;}};
struct WorldHost{W source{};uint64_t epoch=7;bool invalidated=false;ScopeWitness scope;}mp4_world_host;
namespace mp4actor{struct Handle{uintptr_t slot=0;uint32_t version=0;};}
struct CameraHost{W source{};bool verified=true,invalidated=false,smart=true,rebuilding=false;mp4actor::Handle camera_graph{};ScopeWitness scope;}mp4_camera_host;
bool mp4_camera_graph(mp4actor::Handle& out){out={};return true;}
bool mp4_camera_same_graph(mp4actor::Handle a,mp4actor::Handle b){return a.slot==b.slot&&a.version==b.version;}
struct FixedWitness{bool healthy(uint64_t e){return e==live.generation;}}mp4_fixed_gate;
bool mp4_fixed_routes_ready(){return true;}
bool mp4_camera_core_domain_current(){return true;}
// SMART_CALLGRAPH
struct Part {
    int index=0,configure=0,quiesce=0,capture=0,prepare=0,reset=0,restore=0,release=0,step=0,grant=0,invalidate=0;
    bool available=true,current=true,restorable=true,restoration=true;int admitted=0,finalized=0,revoked=0,rendered=0,detached=0;
    std::vector<bool> owned;
}parts[4];
std::string wait_operation;int wait_part=-1;bool waited=false,change_during=false;
R operation(Part& p,const char* name,int& count){
    ++count;
    if(change_during&&wait_operation==name&&p.index==wait_part){++live.generation;change_during=false;}
    if(!waited&&wait_operation==name&&p.index==wait_part){waited=true;return R::waiting;}
    return R::ok;
}
bool available(void* c){return static_cast<Part*>(c)->available;}
R configure(void* c,const W& w){assert(w.generation==live.generation);auto& p=*static_cast<Part*>(c);return operation(p,"configure",p.configure);}
bool current(void* c){return static_cast<Part*>(c)->current;}
R quiesce(void* c){auto& p=*static_cast<Part*>(c);return operation(p,"quiesce",p.quiesce);}
R capture(void* c){auto& p=*static_cast<Part*>(c);return operation(p,"capture",p.capture);}
R prepare(void* c){auto& p=*static_cast<Part*>(c);return operation(p,"prepare",p.prepare);}
R reset(void* c){auto& p=*static_cast<Part*>(c);return operation(p,"reset",p.reset);}
R restore(void* c){auto& p=*static_cast<Part*>(c);return operation(p,"restore",p.restore);}
R release(void* c,bool own){auto& p=*static_cast<Part*>(c);p.owned.push_back(own);return operation(p,"release",p.release);}
const char* error(void*){return "modeled_part_waiting";}
R step(void* c,uint64_t t,double s){assert(t==0&&s==0);++static_cast<Part*>(c)->step;return R::ok;}
R grant(void* c,uint64_t t){assert(t==0);++static_cast<Part*>(c)->grant;return R::ok;}
bool restorable(void* c){return static_cast<Part*>(c)->restorable;}
void invalidate(void* c,void*){++static_cast<Part*>(c)->invalidate;}
void revoke(void* c){++static_cast<Part*>(c)->revoked;}
R prepare_render(void* c,uint64_t tick){assert(tick==0);++static_cast<Part*>(c)->rendered;return R::ok;}
R detach(void* c){auto& p=*static_cast<Part*>(c);return operation(p,"detach",p.detached);}
R finalized(void* c){auto& p=*static_cast<Part*>(c);return operation(p,"finalize",p.finalized);}
bool verified(void* c){return static_cast<Part*>(c)->restoration&&static_cast<Part*>(c)->restore>0;}
R admit(void* c,const W& w){assert(w.generation==live.generation);auto& p=*static_cast<Part*>(c);++p.admitted;if(p.index==admission_throw)throw std::runtime_error("admission");if(p.restorable&&p.index==2)admission_receipt=true;return p.restorable?R::ok:R::unsupported;}
int post_begins=0,post_detaches=0,post_verifies=0,post_releases=0;bool post_checkpoint=false,post_begin_throws=false,post_begin_fails=false;
R post_begin(bool checkpoint){++post_begins;post_checkpoint=checkpoint;if(post_begin_throws)throw std::runtime_error("observer");return post_begin_fails?R::failed:R::ok;}
R post_detach(bool checkpoint){++post_detaches;assert(checkpoint==post_checkpoint);return R::ok;}
R post_verify(){++post_verifies;return R::ok;}
R post_release(){++post_releases;return R::ok;}
void install(bool missing=false){
    mp4_scene_post_restore={post_begin,post_detach,post_verify,post_release};
    Mp4ScenePart table[4]{};
    for(unsigned i=0;i<4;++i){parts[i].index=i;table[i]={&parts[i],available,configure,current,quiesce,capture,prepare,reset,restore,release,error,nullptr,nullptr,nullptr,invalidate,admit,verified};}
    for(auto& part:table){part.prepare_step=step;part.grant=grant;part.revoke_grants=revoke;}table[3].clock_restorable=restorable;table[1].verify_source_restored=finalized;table[1].prepare_render=prepare_render;table[3].detach_global_loops=detach;
    if(missing)table[0].prepare_step=nullptr;
    assert(mp4_scene_register_parts(table,4));
}
void begin(){assert(mp4_scene_quiesce(nullptr)==R::ok);assert(mp4_scene_capture(nullptr)==R::ok);assert(mp4_scene_prepare(nullptr)==R::ok);assert(mp4_scene_reset(nullptr)==R::ok);}
int main(int argc,char** argv){
    assert(argc==2);std::string mode=argv[1];
    if(mode=="missing_part"){install(true);assert(!mp4_scene_parts_available());assert(!mp4_scene_owner_current(nullptr));return 0;}
    install();assert(mp4_scene_parts_available());
    if(mode=="smart_callgraph"||mode=="smart_callgraph_rejected"){
        mp4_world_host.source=live;mp4_camera_host.source=live;
        mp4_scene_host.parts[1].owner_current=mp4_camera_source_current;
        mp4_scene_host.parts[3].owner_current=mp4_world_source_current;
        assert(mp4_scene_quiesce(nullptr)==R::ok);
        const unsigned before=witness_calls;
        assert(mp4_scene_normal_animation_closed()&&mp4_scene_owner_current(nullptr)&&mp4_world_fixed_subtree_closed());
        assert(witness_calls>before&&witness_calls-before<32);
        if(mode=="smart_callgraph_rejected"){driving_permission=false;assert(!mp4_scene_owner_current(nullptr)&&!mp4_world_fixed_subtree_closed()&&mp4_scene_grant(nullptr,0)==R::stale);for(auto&p:parts)assert(!p.grant);return 0;}
        ++live.generation;assert(!mp4_world_fixed_subtree_closed()&&!mp4_scene_owner_current(nullptr));return 0;
    }
    if(mode=="global_handoff"){mp4_scene_restore_globals_before_source_change(nullptr);assert(actor_globals==1&&camera_globals==1);on_thread=false;mp4_scene_restore_globals_before_source_change(nullptr);assert(actor_globals==1&&camera_globals==1);return 0;}
    if(mode=="abandon_loops_before_resource_wait"){
        begin();wait_operation="release";wait_part=0;
        assert(mp4_scene_release(nullptr,false)==R::waiting);
        assert(parts[3].detached==1&&!parts[3].release&&parts[0].release==1&&!parts[1].release);
        assert(!roots.empty()&&mp4_scene_host.active);
        assert(mp4_scene_release(nullptr,false)==R::ok&&parts[3].detached==2&&roots.empty());return 0;
    }
    if(mode=="pending_end_blocks_detach"){
        begin();wait_operation="detach";wait_part=3;
        assert(mp4_scene_release(nullptr,false)==R::waiting);
        for(auto& p:parts)assert(!p.release);
        assert(parts[3].detached==1&&!roots.empty());
        assert(mp4_scene_release(nullptr,false)==R::ok&&parts[3].detached==2&&roots.empty());return 0;
    }
    if(mode=="abandon_globals"){
        on_thread=false;mp4_scene_abandon_globals(nullptr);
        assert(actor_globals==1&&camera_globals==1&&actor_withdrawn==1&&camera_withdrawn==1);return 0;
    }
    if(mode=="final_handoff_before_detach"){
        begin();assert(mp4_scene_restore(nullptr)==R::ok);assert(mp4_scene_verify_source_restored(nullptr)==R::ok);
        final_handoff_wait=true;assert(mp4_scene_detach_after_restore(nullptr)==R::waiting);
        assert(final_handoff==1&&!actor_withdrawn&&!camera_withdrawn&&!parts[3].detached&&!post_begins);
        final_handoff_wait=false;assert(mp4_scene_detach_after_restore(nullptr)==R::ok);
        assert(final_handoff==2&&actor_withdrawn==1&&camera_withdrawn==1&&parts[3].detached==1);
        assert(mp4_scene_detach_after_restore(nullptr)==R::ok&&final_handoff==2);return 0;
    }
    if(mode=="post_begin_failure"||mode=="post_begin_exception"){
        begin();post_begin_throws=mode=="post_begin_exception";post_begin_fails=!post_begin_throws;
        assert(mp4_scene_detach_after_restore(nullptr)==R::ok&&mp4_scene_host.detached);
        assert(parts[3].detached==1&&actor_withdrawn==1&&camera_withdrawn==1);
        assert(mp4_scene_verify_post_restore(nullptr)==R::failed&&!post_verifies);
        assert(mp4_scene_release(nullptr,false)==R::ok);
        assert(mp4_scene_release_post_restore(nullptr)==R::ok&&post_releases==1);return 0;
    }
    if(mode=="detach_partial"||mode=="detach_pending_end"||mode=="detach_checkpoint"||mode=="detach_missing_provider"){
        begin();
        if(mode=="detach_checkpoint"){
            assert(mp4_scene_restore(nullptr)==R::ok&&mp4_scene_verify_source_restored(nullptr)==R::ok);
            bool ca=false,deps=false;mp4_scene_attest(nullptr,&ca,&deps);assert(ca&&deps&&!roots.empty());
        }
        if(mode=="detach_pending_end"){wait_operation="detach";wait_part=3;}
        if(mode=="detach_missing_provider")mp4_scene_post_restore={};
        const auto first=mp4_scene_detach_after_restore(nullptr);
        assert(actor_withdrawn==1&&camera_withdrawn==1&&!roots.empty());
        assert(!parts[0].release&&parts[3].detached==1);
        if(mode=="detach_missing_provider"){assert(first==R::unsupported&&!mp4_scene_host.detached);return 0;}
        if(mode=="detach_pending_end"){assert(first==R::waiting);assert(mp4_scene_detach_after_restore(nullptr)==R::ok);}
        else assert(first==R::ok);
        assert(post_begins==1&&post_checkpoint==(mode=="detach_checkpoint"));
        const int withdrawals=actor_withdrawn;assert(mp4_scene_detach_after_restore(nullptr)==R::ok&&actor_withdrawn==withdrawals);
        wait_operation="release";wait_part=1;waited=false;
        assert(mp4_scene_release(nullptr,false)==R::waiting);
        assert(mp4_scene_verify_post_restore(nullptr)==R::ok);
        ++live.generation;
        assert(mp4_scene_release(nullptr,false)==R::ok&&roots.empty());
        assert(mp4_scene_verify_post_restore(nullptr)==R::ok&&mp4_scene_release_post_restore(nullptr)==R::ok);
        assert(post_verifies==2&&post_releases==1);
        bool ca=false,deps=false;mp4_scene_attest(nullptr,&ca,&deps);
        assert(ca==(mode=="detach_checkpoint")&&deps==ca);return 0;
    }
    if(mode=="missing_render_arm"){mp4_scene_host.parts[1].prepare_render=nullptr;assert(!mp4_scene_parts_available());return 0;}
    if(mode=="render_only"){
        begin();assert(mp4_scene_prepare_step(nullptr,0,0)==R::ok);assert(mp4_scene_grant(nullptr,0)==R::ok);
        assert(mp4_scene_hold(nullptr)==R::ok);assert(mp4_scene_prepare_render(nullptr,0)==R::ok);
        for(unsigned i=0;i<4;++i){assert(parts[i].grant==1&&parts[i].step==1);assert(parts[i].rendered==(i==1?1:0));}
        assert(mp4_scene_release(nullptr,false)==R::ok);return 0;
    }
    if(mode=="missing_camera_grant"||mode=="missing_stage_grant"||mode=="missing_world_grant"){
        mp4_scene_host.parts[mode=="missing_camera_grant"?1:mode=="missing_stage_grant"?2:3].grant=nullptr;
        assert(!mp4_scene_parts_available());return 0;
    }
    if(mode=="admit_ledger"){
        assert(!mp4_scene_normal_animation_closed());assert(mp4_scene_admit(nullptr)==R::ok);
        assert(mp4_scene_normal_animation_closed());++live.generation;assert(!mp4_scene_normal_animation_closed());
        --live.generation;mp4_scene_will_change(live.player);assert(!mp4_scene_normal_animation_closed());return 0;
    }
    if(mode=="admit"){assert(mp4_scene_admit(nullptr)==R::ok&&roots.empty()&&!mp4_scene_host.active&&admission_receipt&&admission_drops==1);for(auto& p:parts)assert(p.admitted==1&&!p.configure);return 0;}
    if(mode=="admit_after_stage_reject"){parts[3].restorable=false;assert(mp4_scene_admit(nullptr)==R::unsupported&&!admission_receipt&&admission_drops==2);assert(parts[2].admitted==1&&parts[3].admitted==1);return 0;}
    if(mode=="admit_exception"){admission_throw=3;try{mp4_scene_admit(nullptr);assert(false);}catch(const std::runtime_error&){}assert(!admission_receipt&&admission_drops==2);return 0;}
    if(mode=="admit_reject"){parts[2].restorable=false;assert(mp4_scene_admit(nullptr)==R::unsupported&&roots.empty()&&!mp4_scene_host.active&&!admission_receipt&&admission_drops==2);assert(parts[0].admitted==1&&parts[1].admitted==1&&parts[2].admitted==1&&!parts[3].admitted);return 0;}
    if(mode=="unavailable"){parts[2].available=false;assert(!mp4_scene_owner_current(nullptr));return 0;}
    if(mode=="not_owned_clock"){held=false;assert(!mp4_scene_owner_current(nullptr));assert(roots.empty());return 0;}
    if(mode=="not_automatic"){automatic=false;assert(!mp4_scene_owner_current(nullptr));return 0;}
    if(mode=="cancel_before_reset"||mode=="prepare_failed_restored"){
        assert(mp4_scene_quiesce(nullptr)==R::ok);assert(mp4_scene_capture(nullptr)==R::ok);
        if(mode=="prepare_failed_restored"){
            wait_operation="prepare";wait_part=2;assert(mp4_scene_prepare(nullptr)==R::waiting);
        }
        assert(!mp4_scene_host.reset);assert(mp4_scene_restore(nullptr)==R::ok);
        assert(mp4_scene_verify_source_restored(nullptr)==R::ok);assert(mp4_scene_release(nullptr,true)==R::ok);
        bool ca=false,deps=false;mp4_scene_attest(nullptr,&ca,&deps);assert(ca&&deps&&roots.empty());return 0;
    }
    if(mode=="allocation_failure"){
        allocation_fail_after=2;assert(mp4_scene_quiesce(nullptr)==R::failed);assert(roots.size()==2);
        assert(mp4_scene_release(nullptr,true)==R::ok&&roots.empty());for(auto& p:parts)assert(!p.configure&&!p.release);return 0;
    }
    if(mode=="configure_partial"){
        wait_operation="configure";wait_part=2;assert(mp4_scene_quiesce(nullptr)==R::waiting);
        assert(parts[0].configure==1&&parts[1].configure==1&&parts[2].configure==1&&parts[3].configure==0);
        assert(mp4_scene_release(nullptr,true)==R::ok&&roots.empty());
        for(unsigned i=0;i<4;++i)assert(parts[i].release==(i<3));return 0;
    }
    assert(mp4_scene_quiesce(nullptr)==R::ok);assert(roots.size()==13);
    if(mode=="root_lost"){
        roots.erase(roots.begin());assert(!mp4_scene_owner_current(nullptr));assert(mp4_scene_release(nullptr,true)==R::ok);
        for(auto& p:parts)assert(p.owned==std::vector<bool>{false});return 0;
    }
    if(mode=="stale_callback"){
        wait_operation="capture";wait_part=1;waited=true;change_during=true;
        assert(mp4_scene_capture(nullptr)==R::stale);assert(parts[0].capture==1&&parts[1].capture==1&&parts[2].capture==0);
        assert(mp4_scene_release(nullptr,true)==R::ok);for(auto& p:parts)assert(p.owned==std::vector<bool>{false});return 0;
    }
    if(mode=="capture_wait"){
        wait_operation="capture";wait_part=1;
        assert(mp4_scene_capture(nullptr)==R::waiting&&mp4_scene_capture(nullptr)==R::ok);
        assert(parts[0].capture==1&&parts[1].capture==2&&parts[2].capture==1&&parts[3].capture==1);
    }else assert(mp4_scene_capture(nullptr)==R::ok);
    if(mode=="prepare_wait"){
        wait_operation="prepare";wait_part=2;
        assert(mp4_scene_prepare(nullptr)==R::waiting&&mp4_scene_prepare(nullptr)==R::ok);
        assert(parts[0].prepare==1&&parts[1].prepare==1&&parts[2].prepare==2&&parts[3].prepare==1);
    }else assert(mp4_scene_prepare(nullptr)==R::ok);
    if(mode=="reset_wait"){
        wait_operation="reset";wait_part=0;
        assert(mp4_scene_reset(nullptr)==R::waiting&&mp4_scene_reset(nullptr)==R::ok);
        assert(parts[0].reset==2&&parts[1].reset==1&&parts[2].reset==1&&parts[3].reset==1);
    }else assert(mp4_scene_reset(nullptr)==R::ok);
    assert(mp4_scene_prepare_step(nullptr,0,0)==R::ok&&mp4_scene_grant(nullptr,0)==R::ok);
    for(const auto& p:parts)assert(p.step==1&&p.grant==1);
    if(mode=="world_not_restorable")parts[3].restorable=false;
    assert(mp4_scene_clock_restorable(nullptr)==(mode!="world_not_restorable"));
    if(mode=="stale_epoch"){
        ++live.generation;assert(!mp4_scene_owner_current(nullptr));assert(mp4_scene_hold(nullptr)==R::stale);
        assert(mp4_scene_release(nullptr,true)==R::ok);for(auto& p:parts)assert(p.owned==std::vector<bool>{false});return 0;
    }
    if(mode=="invalidate"){
        mp4_scene_will_change(reinterpret_cast<void*>(999));assert(mp4_scene_owner_current(nullptr));
        mp4_scene_will_change(live.player);assert(!mp4_scene_owner_current(nullptr));
        for(auto& p:parts)assert(p.invalidate==1);assert(mp4_scene_release(nullptr,true)==R::ok);for(auto& p:parts)assert(p.owned==std::vector<bool>{false});return 0;
    }
    if(mode=="restore_wait"){
        wait_operation="restore";wait_part=2;
        assert(mp4_scene_restore(nullptr)==R::waiting&&mp4_scene_restore(nullptr)==R::ok);
        assert(parts[0].restore==1&&parts[1].restore==1&&parts[2].restore==2&&parts[3].restore==1);
    }else assert(mp4_scene_restore(nullptr)==R::ok);
    if(mode=="camera_attest_failed")parts[1].restoration=false;
    if(mode=="stage_attest_failed")parts[2].restoration=false;
    if(mode=="finalize_wait"){
        wait_operation="finalize";wait_part=1;
        assert(mp4_scene_verify_source_restored(nullptr)==R::waiting);assert(!mp4_scene_host.finalized);
        assert(mp4_scene_verify_source_restored(nullptr)==R::ok&&parts[1].finalized==2);
    }else assert(mp4_scene_verify_source_restored(nullptr)==R::ok);
    if(mode=="revoke_stale"){
        for(auto& p:parts)p.current=false;
        const int before=parts[0].revoked;mp4_scene_revoke_grants(nullptr);
        for(const auto& p:parts)assert(p.revoked==before+1);
        assert(mp4_scene_hold(nullptr)==R::stale);
        for(const auto& p:parts)assert(p.revoked==before+2);
        assert(mp4_scene_release(nullptr,false)==R::ok);return 0;
    }
    if(mode=="release_wait"){
        wait_operation="release";wait_part=1;
        assert(mp4_scene_release(nullptr,true)==R::waiting);assert(!parts[3].release);++live.generation;
        assert(mp4_scene_release(nullptr,true)==R::ok);
        assert(parts[0].owned==std::vector<bool>{true});assert((parts[1].owned==std::vector<bool>{true,false}));
        assert(parts[2].owned==std::vector<bool>{false});assert(parts[3].owned==std::vector<bool>{false});
    }else assert(mp4_scene_release(nullptr,true)==R::ok);
    assert(roots.empty()&&!mp4_scene_host.active);
    bool ca=false,deps=false;mp4_scene_attest(nullptr,&ca,&deps);assert(ca==(mode!="release_wait"&&mode!="camera_attest_failed")&&deps==(mode!="release_wait"&&mode!="stage_attest_failed"));
    assert(mp4_scene_release(nullptr,true)==R::ok);
}
'''
    folder=tmp_path_factory.mktemp("scene-aggregate");source=folder/"test.cpp";binary=folder/"test"
    source.write_text(harness.replace("// PRODUCTION",production).replace("// SMART_CALLGRAPH",callgraph))
    result=subprocess.run([compiler,"-std=c++17","-O2","-Wall","-Wextra","-Werror","-Wno-misleading-indentation","-I",str(ROOT/"client-presentation/native"),str(source),"-o",str(binary)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return binary


@pytest.mark.parametrize("mode",["normal","final_handoff_before_detach","post_begin_failure","post_begin_exception","detach_partial","detach_pending_end","detach_checkpoint","detach_missing_provider","abandon_globals","abandon_loops_before_resource_wait","pending_end_blocks_detach","global_handoff","render_only","missing_render_arm","smart_callgraph","smart_callgraph_rejected","revoke_stale","cancel_before_reset","prepare_failed_restored","finalize_wait","admit","admit_reject","admit_after_stage_reject","admit_exception","admit_ledger","missing_camera_grant","missing_stage_grant","missing_world_grant","camera_attest_failed","stage_attest_failed","missing_part","unavailable","not_owned_clock","not_automatic","allocation_failure","configure_partial","root_lost","stale_callback","capture_wait","prepare_wait","reset_wait","world_not_restorable","stale_epoch","invalidate","restore_wait","release_wait"])
def test_production_aggregate_preserves_order_roots_and_partial_phase_ownership(aggregate,mode):
    result=subprocess.run([str(aggregate),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
