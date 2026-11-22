#include <cstdint>
#include <cstddef>
#include <atomic>
#include <cassert>
#include <cstdlib>
#include <thread>
enum class Mp4SceneResult:uint8_t{ok,waiting,stale,failed,unsupported};
struct Mp4ScenePart{void*context=nullptr;Mp4SceneResult(*capture)(void*)=nullptr;bool(*owner_current)(void*)=nullptr;};
struct{bool active=true;unsigned configured=15,all=15,captured=0;struct{uint64_t generation=7;}source;Mp4ScenePart parts[4]{};}mp4_scene_host;
struct{unsigned depth=0;}mp4_raw_original_operation;
struct Model{bool thread=true,current=true,held=true,owner[4]{true,true,true,true};int mode=0;unsigned calls[4]{},saved[4]{};Mp4SceneResult result=Mp4SceneResult::ok;}model;
bool game_call(){return model.thread;}bool mp4_scene_source_current(){return model.current;}bool mp4_actor_clock_held(void*){return model.held;}
void mp4_root_capture_withdraw()noexcept;Mp4SceneResult mp4_root_capture_part(size_t,const Mp4ScenePart&);
bool owner(void*p){const auto index=(uintptr_t)p-1;return index<4&&model.owner[index];}
Mp4SceneResult callback(void*p){const auto i=(uintptr_t)p-1;assert(i<4);++model.calls[i];++model.saved[i];if(model.mode==2)throw 42;if(model.mode==12)++mp4_scene_host.source.generation;if(model.mode==13)model.owner[i]=false;if(model.mode==14)mp4_root_capture_withdraw();if(model.mode==24)assert(mp4_root_capture_part(1,mp4_scene_host.parts[1])==Mp4SceneResult::unsupported);return model.result;}
Mp4SceneResult wrong(void*){assert(false);return Mp4SceneResult::failed;}
Mp4ScenePart part(size_t index){return {(void*)(index+1),callback,owner};}
Mp4ScenePart mp4_scene_actor_part(){return part(0);}Mp4ScenePart mp4_scene_camera_part(){return part(1);}Mp4ScenePart mp4_stage_part(){return part(2);}Mp4ScenePart mp4_scene_world_part(){return part(3);}
