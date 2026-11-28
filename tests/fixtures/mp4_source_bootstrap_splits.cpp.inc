#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
enum class Mp4SceneResult{ok,waiting,unsupported,invalid,stale};
struct Mp4SceneWitness{uint64_t generation=0,token=0;};bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation&&a.generation==b.generation&&a.token==b.token;}
bool thread=true,stage=true,held=true,configure_ok=true,assembly_current=true,mono_current=true,world_image_current=true,source_validate=true,manager_exists=true,partial_failure=false,logical_ready=false;
unsigned configured_calls=0,full_calls=0,baseline_calls=0,cleanup_calls=0;bool cleanup_wait=false;
bool game_call(){return thread;}bool mp4_stage_owner(void*){return stage;}bool mp4_actor_clock_held(void*){return held;}
struct FixedGate{}mp4_fixed_gate;uintptr_t mp4_native_base=0x100;struct{struct{uintptr_t rva=0x200;}fixed_condition;}mp4_world_profile;
int mp4_world_api(){return 4;}
struct WorldScope{bool acquired=false;bool active()const{return acquired;}bool configure(int api,FixedGate*g,void*ctx,uint64_t epoch,uintptr_t condition){++configured_calls;assert(api==4&&g==&mp4_fixed_gate&&ctx&&epoch==7&&condition==0x300);return configure_ok;}};
struct World{WorldScope scope{};Mp4SceneWitness source{};uint64_t epoch=0;bool invalidated=true,restoration_verified=true;}mp4_world_host;
Mp4SceneResult mp4_world_full_quiesce_adopting_source_gates(){++full_calls;if(!logical_ready)return Mp4SceneResult::unsupported;mp4_world_host.scope.acquired=true;return Mp4SceneResult::ok;}
struct VolumeAssembly{Mp4SceneWitness source{};uint64_t job=0;bool prepared=false,prepare_started=false,captured=false,configured=false;uint32_t manager_root=0,additional_root=0;}mp4_volume_assembly;
struct{Mp4SceneWitness source{};}mp4_camera_host;namespace idoly_mp4_runtime{struct{uint64_t generation=9;}job;}
struct{bool captured=false;}mp4_source_volume_host,mp4_volume_mono_host;
namespace idoly_mp4_volume_source{enum class Result{ok,failed};}
struct{auto validate(){return source_validate?idoly_mp4_volume_source::Result::ok:idoly_mp4_volume_source::Result::failed;}}mp4_source_volume_scope;
bool mp4_volume_mono_host_current(){return mono_current;}bool mp4_world_volume_image_current(){return world_image_current;}bool mp4_volume_assembly_current(void*,uint64_t epoch){return assembly_current&&epoch==7;}
void*mp4_volume_existing_manager(){return manager_exists?reinterpret_cast<void*>(0x44):nullptr;}
bool mp4_volume_assembly_capture(void*manager){assert(manager==reinterpret_cast<void*>(0x44));++baseline_calls;auto&h=mp4_volume_assembly;h.configured=true;h.manager_root=1;if(partial_failure)return false;h.additional_root=2;h.source=mp4_camera_host.source;h.job=idoly_mp4_runtime::job.generation;h.captured=true;mp4_source_volume_host.captured=mp4_volume_mono_host.captured=true;return true;}
Mp4SceneResult mp4_volume_assembly_cleanup(bool owned){assert(!owned);++cleanup_calls;if(cleanup_wait)return Mp4SceneResult::waiting;mp4_volume_assembly={};mp4_source_volume_host={};mp4_volume_mono_host={};return Mp4SceneResult::ok;}
// SOURCE_BOOTSTRAP_SPLITS_HOST
void reset(){thread=stage=held=configure_ok=assembly_current=mono_current=world_image_current=source_validate=manager_exists=true;partial_failure=logical_ready=cleanup_wait=false;configured_calls=full_calls=baseline_calls=cleanup_calls=0;mp4_world_host={};mp4_volume_assembly={};mp4_source_volume_host={};mp4_volume_mono_host={};mp4_camera_host.source={7,11};idoly_mp4_runtime::job.generation=9;}
int main(){unsigned cases=0;
 {reset();assert(mp4_world_source_configure_only(nullptr,{7,11})==Mp4SceneResult::ok&&configured_calls==1&&!full_calls&&!mp4_world_host.scope.active());++cases;}
 {reset();mp4_world_host.scope.acquired=true;assert(mp4_world_source_configure_only(nullptr,{7,11})==Mp4SceneResult::invalid&&!configured_calls);++cases;}
 {reset();configure_ok=false;assert(mp4_world_source_configure_only(nullptr,{7,11})==Mp4SceneResult::unsupported&&!full_calls);++cases;}
 {reset();assert(mp4_world_full_capture_after_source_images()==Mp4SceneResult::unsupported&&full_calls==1&&!mp4_world_host.scope.active());logical_ready=true;assert(mp4_world_full_capture_after_source_images()==Mp4SceneResult::ok&&mp4_world_host.scope.active());++cases;}
 {reset();assert(mp4_camera_source_baselines_capture_or_verify()&&baseline_calls==1);assert(mp4_camera_source_baselines_capture_or_verify()&&baseline_calls==1&&!full_calls);++cases;}
 {reset();manager_exists=false;assert(!mp4_camera_source_baselines_capture_or_verify()&&!baseline_calls);++cases;}
 {reset();partial_failure=true;assert(!mp4_camera_source_baselines_capture_or_verify()&&baseline_calls==1);partial_failure=false;assert(!mp4_camera_source_baselines_capture_or_verify()&&baseline_calls==1);assert(mp4_camera_source_baselines_release()==Mp4SceneResult::ok);assert(mp4_camera_source_baselines_capture_or_verify()&&baseline_calls==2);++cases;}
 {reset();assert(mp4_camera_source_baselines_capture_or_verify());mp4_volume_assembly.prepared=true;assert(!mp4_camera_source_baselines_capture_or_verify()&&baseline_calls==1);++cases;}
 {reset();assert(mp4_camera_source_baselines_capture_or_verify());mp4_volume_assembly.prepare_started=true;assert(!mp4_camera_source_baselines_capture_or_verify()&&baseline_calls==1);++cases;}
 {reset();assert(mp4_camera_source_baselines_capture_or_verify());mp4_volume_assembly.source.token=12;assert(!mp4_camera_source_baselines_capture_or_verify()&&baseline_calls==1);++cases;}
 {reset();assert(mp4_camera_source_baselines_capture_or_verify());idoly_mp4_runtime::job.generation=10;assert(!mp4_camera_source_baselines_capture_or_verify()&&baseline_calls==1);++cases;}
 {reset();assert(mp4_camera_source_baselines_capture_or_verify());mp4_source_volume_host.captured=false;assert(!mp4_camera_source_baselines_capture_or_verify());++cases;}
 {reset();assert(mp4_camera_source_baselines_capture_or_verify());mp4_volume_mono_host.captured=false;assert(!mp4_camera_source_baselines_capture_or_verify());++cases;}
 {reset();assert(mp4_camera_source_baselines_capture_or_verify());source_validate=false;assert(!mp4_camera_source_baselines_capture_or_verify());++cases;}
 {reset();assert(mp4_camera_source_baselines_capture_or_verify());mono_current=false;assert(!mp4_camera_source_baselines_capture_or_verify());++cases;}
 {reset();assert(mp4_camera_source_baselines_capture_or_verify());world_image_current=false;assert(!mp4_camera_source_baselines_capture_or_verify()&&baseline_calls==1);++cases;}
 {reset();assert(mp4_camera_source_baselines_capture_or_verify());assembly_current=false;assert(!mp4_camera_source_baselines_capture_or_verify());++cases;}
 {reset();thread=false;assert(!mp4_camera_source_baselines_capture_or_verify()&&!baseline_calls);++cases;}
 {reset();held=false;assert(!mp4_camera_source_baselines_capture_or_verify()&&!baseline_calls);++cases;}
 {reset();stage=false;assert(!mp4_camera_source_baselines_capture_or_verify()&&!baseline_calls);++cases;}
 {reset();assert(mp4_camera_source_baselines_capture_or_verify());cleanup_wait=true;assert(mp4_camera_source_baselines_release()==Mp4SceneResult::waiting&&mp4_volume_assembly.captured);cleanup_wait=false;assert(mp4_camera_source_baselines_release()==Mp4SceneResult::ok&&!mp4_volume_assembly.captured);++cases;}
 std::printf("%u source bootstrap literal split cases passed; original scopes/providers modeled\n",cases);
}
