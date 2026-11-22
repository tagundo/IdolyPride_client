#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cassert>
#include <atomic>
namespace mp4_director_maintenance{enum class Kind{saved_evaluate=5,rebuild=3,play=1,stop=2};struct Call{Kind kind=Kind::saved_evaluate;uint64_t epoch=7,serial=11;uintptr_t source_asset=2,receiver=1,method=3;uint64_t original_receipt=13;};}
namespace mp4child{enum class Result{ok,waiting};struct Owner{uintptr_t director=1,asset=2;uint64_t epoch=7;};struct State{Owner owner{};uintptr_t root_asset=2;double time=1.5;int mode=1,state=0;};struct Handle{uintptr_t handle=100;uint32_t version=4;};struct Checkpoint{uint64_t epoch=7;uintptr_t root_asset=2,director=1;Handle graph{},root{200,4};double time=1.5;int mode=1,state=0;mp4_director_maintenance::Call saved_evaluate{};};}
enum class Mp4TimelineProofPhase{admission,active,source_restore_plan,source_restored};struct Mp4TimelineContext{Mp4TimelineProofPhase phase=Mp4TimelineProofPhase::source_restore_plan;void*director=(void*)1,*asset=(void*)2;struct{uint64_t generation=7;}witness;mp4child::Handle graph{},root{200,4};};
struct{bool ready=true,inside=false;uint64_t epoch=7,job=9,withdraw=0;}mp4_root_history_initial_cohort;namespace idoly_mp4_runtime{struct{uint64_t generation=9;}job;}
std::atomic<uint64_t>mp4_root_capture_withdraw_sequence{0};struct{unsigned depth=0;}mp4_raw_original_operation;struct{struct{void*director=(void*)1;}source;void*root_asset=(void*)2;}mp4_scene_host;
namespace mp4play{enum class OperationStep{restore_evaluate,restore_state};}struct Request{bool complete=true;struct{bool issued=true,returned=true;mp4_director_maintenance::Call call{};}mutation;mp4child::State source{};};struct{Request requests[2]{};}mp4_main_control_bank;
struct Model{bool thread=true,current=true,held=true,fields=true,sealed=true,parent=true,checkpoint=true,bindings=true,time=true,mode=true,state=true;size_t count=1;mp4child::State source{},duplicate{};mp4child::Checkpoint saved{};unsigned calls=0;}model;
bool game_call(){return model.thread;}bool mp4_timeline_current(const Mp4TimelineContext&){++model.calls;return model.current;}bool mp4_actor_clock_held(void*){return model.held;}bool mp4_root_history_initial_sealed(uint64_t){return model.sealed;}
struct{bool child_fields_restored(){return model.fields;}size_t count(){return model.count;}const mp4child::State*source(size_t i){return i?&model.duplicate:&model.source;}bool director_fields_checkpoint(uintptr_t,mp4child::Checkpoint&out){out=model.saved;return model.checkpoint;}}mp4_child_source_scope;
mp4child::Result mp4_child_parent_state_checkpoint(){assert(false&&"read-only saved query called mutating parent checkpoint");return mp4child::Result::waiting;}bool mp4_child_tuple_same(const mp4child::Owner&a,const mp4child::Owner&b){return a.director==b.director&&a.asset==b.asset&&a.epoch==b.epoch;}

bool mp4_child_readonly_bindings(){return model.bindings;}
double get_time(void*,void*){return model.source.time+(model.time?0:1);}
int get_mode(void*,void*){return model.source.mode+(model.mode?0:1);}
int get_state(void*,void*){return model.source.state+(model.state?0:1);}
struct{void*director_evaluate=(void*)3;decltype(&get_time)director_get_time=get_time;decltype(&get_mode)director_get_mode=get_mode;struct{void*director_resume=(void*)7,*director_pause=(void*)5;decltype(&get_state)director_state=get_state;}automatic_playback;}mp4_api;
namespace idoly_mp4_runtime{struct{bool automatic_source_playback_state_restored(uint64_t){return model.parent;}}game;}

bool mp4_root_history_saved_context_current(const Mp4TimelineContext&c){return mp4_timeline_current(c);}
