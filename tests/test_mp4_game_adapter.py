"""Exercise original-game adapter ownership with a synthetic managed heap.

This tests the contract at the native boundary: timeline provenance, real frame
submission ordering, bounded PCM offsets, cancellation and state restoration.
It does not claim Unity/GPU/device validation.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]

SOURCE=r'''
#include "mp4_game_adapter.hpp"
#include "mp4_game_bindings.hpp"
#include <array>
#include <cassert>
#include <map>
#include <memory>
#include <string>
#include <vector>
using namespace idoly_mp4_game;
struct Obj { alignas(16) std::array<uint8_t,512> mem{}; std::string type,name; std::vector<void*> pointers; std::vector<float> floats; std::vector<uint8_t> bytes; int array_kind=0; };
std::vector<std::unique_ptr<Obj>> heap;
std::map<void*,Obj*> objects;
std::map<uint32_t,void*> handles;uint32_t serial=1;
Obj* make(const char* type,const char* name=""){auto item=std::make_unique<Obj>();item->type=type;item->name=name;Obj* p=item.get();objects[p->mem.data()]=p;heap.push_back(std::move(item));return p;}
void* ptr(Obj* o){return o?o->mem.data():nullptr;}
template<class T>void write(Obj* o,size_t at,T value){std::memcpy(o->mem.data()+at,&value,sizeof(value));}
Obj *presenter,*player,*controller,*director,*timeline,*camera_controller,*camera,*wrapper,*rt,*bgm,*voice,*source_clip,*private_clip,*bundle,*request,*track,*clip,*camera_track,*brain,*actor_controller,*animation_player;
int mode=0,evals=0,unloads=0,destroys=0,graph_steps=0,graph_variant=0,actor_mode=1,actor_steps=0,actor_resets=0,audio_state=2,audio_load_calls=0;bool actor_mode_known=true;GameAdapter* clock_game=nullptr;int camera_steps=0,camera_resets=0;bool camera_clock_healthy=true;double time_value=13.25;bool custom=false,done=false,load_ok=true;float shader=4,bgm_volume=.6f,voice_volume=.4f;void* active=nullptr;
bool rebuild_actor_on_reset=false,transition_during_evaluate=false,transition_during_resize_restore=false;unsigned geometry_cleanup_calls=0;
void take_over_scene(){timeline=make("UnityEngine.Timeline.TimelineAsset");time_value=9;mode=2;bgm_volume=.3f;voice_volume=.7f;actor_mode=2;custom=true;shader=77;}
bool istype(void* p,const char* type){auto it=objects.find(p);return it!=objects.end()&&it->second->type==type;}
bool alive(void* p){return p&&objects.count(p);}
uint32_t retain(void* p){if(!p)return 0;handles[serial]=p;return serial++;}
void* target(uint32_t h){auto it=handles.find(h);return it==handles.end()?nullptr:it->second;}
void release(uint32_t h){assert(handles.erase(h)==1);}
size_t length(void* p){auto* o=objects.at(p);return o->array_kind==1?o->pointers.size():o->array_kind==2?o->floats.size():o->bytes.size();}
void* data(void* p){auto* o=objects.at(p);return o->array_kind==1?static_cast<void*>(o->pointers.data()):o->array_kind==2?static_cast<void*>(o->floats.data()):static_cast<void*>(o->bytes.data());}
void* string_new(const char* value){return ptr(make("System.String",value));}
size_t utf8(void* p,char* out,size_t cap){if(!p)return 0;const auto& s=objects.at(p)->name;if(s.size()<cap)std::memcpy(out,s.c_str(),s.size()+1);return s.size();}
void* name(void* p,Method*){return string_new(objects.at(p)->name.c_str());}
void* asset(void*,Method*){return ptr(timeline);}
void* audio_binding_override=nullptr;
void* binding(void*,void* key,Method*){if(istype(key,"UnityEngine.Timeline.AudioTrack"))return audio_binding_override?audio_binding_override:ptr(bgm);return ptr(brain);}
void* output_camera(void*,Method*){return ptr(camera);}
std::map<void*,void*> director_game_objects;
void* game_object(void* value,Method*){auto found=director_game_objects.find(value);if(found!=director_game_objects.end())return found->second;return director_game_objects[value]=ptr(make("UnityEngine.GameObject"));}
void* reference(void*,PropertyName4,bool* valid,Method*){*valid=false;return nullptr;}
bool track_muted(void* value,Method*){return objects.at(value)->mem[0x29]!=0;}
bool active_enabled(void*,Method*){return true;}
void brain_manual(void* p,Method*){assert(p==ptr(brain));assert(*reinterpret_cast<int32_t*>(brain->mem.data()+0x30)==3);assert(*reinterpret_cast<int32_t*>(brain->mem.data()+0x34)==1);if(clock_game){float delta=999;assert(clock_game->camera_delta_override(p,&delta));if(delta<0)++camera_resets;else ++camera_steps;}}
bool camera_clock_ok(){return camera_clock_healthy;}
double get_time(void*,Method*){return time_value;}
double duration(void*,Method*){return 122;}
int32_t get_mode(void*,Method*){return mode;}
void set_mode(void*,int32_t n,Method*){mode=n;}
void set_time(void*,double n,Method*){time_value=n;}
void evaluate(void*,Method*){++evals;if(transition_during_evaluate)take_over_scene();}
void get_graph(void*,PlayableGraph* out,Method*){out->handle=reinterpret_cast<void*>(0x1234);out->version=7;}
void graph_step(PlayableGraph* graph,float dt,Method*){if(graph->handle==reinterpret_cast<void*>(0x2222)){assert(actor_mode==3);if(dt>0)++actor_steps;return;}++graph_steps;if(graph_variant==0)time_value+=dt;else if(graph_variant==2)time_value+=dt*2;}
void graph_mode(PlayableGraph* graph,int32_t mode,Method*){assert(graph->handle==reinterpret_cast<void*>(0x2222));actor_mode=mode;}
bool graph_valid(PlayableGraph* graph,Method*){return graph->handle!=nullptr;}
bool recorded_mode(const PlayableGraph* graph,int32_t* out){if(!actor_mode_known||graph->handle!=reinterpret_cast<void*>(0x2222))return false;*out=1;return true;}
void reset_player(void*,float t,Method*){time_value=t;++evals;++actor_resets;if(rebuild_actor_on_reset){write(animation_player,0x28,PlayableGraph{reinterpret_cast<void*>(0x3333),10,0});actor_mode=2;}}
void* tracks(void*,Method*){auto* a=make("UnityEngine.Timeline.TrackAsset[]");a->array_kind=1;a->pointers={ptr(track),ptr(camera_track)};return ptr(a);}
void* clips(void*,Method*){auto* a=make("UnityEngine.Timeline.TimelineClip[]");a->array_kind=1;a->pointers={ptr(clip)};return ptr(a);}
int32_t samples(void*,Method*){return 8;}int32_t channels(void*,Method*){return 2;}int32_t frequency(void*,Method*){return 48000;}
float volume_get(void* p,Method*){return p==ptr(bgm)?bgm_volume:voice_volume;}
void volume_set(void* p,float n,Method*){(p==ptr(bgm)?bgm_volume:voice_volume)=n;}
int32_t loadstate(void*,Method*){return load_ok?audio_state:3;}int32_t loadtype(void*,Method*){return 0;}
bool load(void*,Method*){++audio_load_calls;if(!load_ok||audio_state!=0)return false;audio_state=1;return true;}
void* new_float(size_t n){auto* a=make("float[]");a->array_kind=2;a->floats.resize(n);return ptr(a);}
bool get_data(void*,void* a,int32_t offset,Method*){auto& f=objects.at(a)->floats;for(size_t i=0;i<f.size();++i)f[i]=float(offset*2+int(i))/16.f;return true;}
void* load_bundle(void*,Method*){return ptr(request);}bool isdone(void*,Method*){return done;}
void* bundle_result(void*,Method*){return ptr(bundle);}
void* load_asset(void*,void*,void*,Method*){return ptr(private_clip);}
void unload(void*,bool all,Method*){assert(all);++unloads;}
bool op_wait=false,op_wait_ticket=false,op_zero=false,op_end_good=true,op_throw=false,op_handoff=false,op_reuse=false;
int raw_captures=0,op_ends=0,op_failed_ends=0;uint64_t op_serial=0;
bool op_observe_inflight=false,op_try_reenter=false;
void capture(void*p,Method*){++raw_captures;
 if(op_observe_inflight){assert(clock_game&&clock_game->owned_capture_request(p,op_serial));
  assert(clock_game->capture_request_origin_serial(p)==op_serial&&!clock_game->capture_operation_starting(p));
  assert(clock_game->owned_capture_request_serial(p)==op_serial&&clock_game->owned_capture_request_serial(ptr(bgm))==0);
  assert(!clock_game->owned_capture_request(ptr(bgm),op_serial)&&!clock_game->owned_capture_request(p,op_serial+1));
  if(op_try_reenter){const int before=raw_captures;assert(clock_game->request_capture()==Result::invalid&&raw_captures==before);}}
 if(op_throw)throw 37;
}
Result capture_begin(void*p,uint64_t*out){assert(p==ptr(camera_controller)&&!clock_game->owned_capture_request(p,op_serial)&&clock_game->owned_capture_request_serial(p)==0&&clock_game->capture_operation_starting(p)&&clock_game->capture_request_origin_serial(p)==0);*out=0;if(op_wait){if(op_wait_ticket)*out=1;return Result::waiting;}*out=op_zero?0:op_reuse?1:++op_serial;return Result::ok;}
bool capture_end(void*p,uint64_t serial,bool returned){assert(p==ptr(camera_controller)&&serial&&clock_game->capture_request_origin_serial(p)==serial&&!clock_game->capture_operation_starting(p));if(op_observe_inflight)assert(clock_game->owned_capture_request(p,serial)&&clock_game->owned_capture_request_serial(p)==serial);++op_ends;if(!returned)++op_failed_ends;if(op_handoff){take_over_scene();assert(clock_game->owned_capture_request_serial(p)==0&&clock_game->capture_request_origin_serial(p)==serial);}return op_end_good;}

int32_t capture_width=16,capture_height=16,source_width=4096,source_height=2458;
std::vector<std::array<int32_t,2>> geometry_calls;bool geometry_resize_good=true;
bool resize_output(void* value,int32_t w,int32_t h){if(!value){assert(!w&&!h);++geometry_cleanup_calls;return true;}assert(value==ptr(camera_controller));geometry_calls.push_back({w,h});if(!w&&!h&&transition_during_resize_restore)take_over_scene();return geometry_resize_good||(!w&&!h);}
bool project_output(void* value,bool){assert(value==ptr(camera_controller));return true;}
int32_t width(void*,Method*){return capture_width;}int32_t height(void*,Method*){return capture_height;}
int32_t format_value=4;int32_t format(void*,Method*){return format_value;}bool srgb(void*,Method*){return true;}
bool throw_bind=false,throw_pixels=false,supersede_active=false;void* replacement_active=nullptr;
void* active_get(Method*){return active;}void active_set(void* p,Method*){active=p;if(throw_bind&&p==ptr(rt)){throw_bind=false;throw 17;}}
void* new_texture(){return ptr(make("UnityEngine.Texture2D"));}
void ctor(void*,int32_t w,int32_t h,int32_t f,bool m,bool linear,Method*){assert(w==16&&h==16&&f==4&&!m&&!linear);}
void readpixels(void*,const Rect* rect,int32_t x,int32_t y,bool m,Method*){assert(active==ptr(rt)&&rect->width==16&&x==0&&y==0&&!m);if(throw_pixels)throw 23;if(supersede_active)active=replacement_active;}
void* raw_data(void*,Method*){auto* a=make("byte[]");a->array_kind=3;a->bytes.resize(16*16*4);for(int y=0;y<16;++y)for(int x=0;x<16;++x){a->bytes[(y*16+x)*4]=uint8_t(y);a->bytes[(y*16+x)*4+3]=255;}return ptr(a);}
void destroy(void*,Method*){++destroys;}
bool shader_custom(Method*){return custom;}float shader_time(Method*){return shader;}
void shader_set(float n,Method*){shader=n;custom=true;}void shader_reset(Method*){custom=false;}
int32_t logical_width(void*,Method*){return 3600;}int32_t logical_height(void*,Method*){return 2160;}
bool actual_source_geometry(void* value,int32_t* w,int32_t* h){assert(value==ptr(camera_controller));*w=source_width;*h=source_height;return true;}
Api api(){Api a{};a.is_type=istype;a.alive=alive;a.retain=retain;a.retained=target;a.release=release;a.new_string=string_new;a.string_utf8=utf8;a.array_length=length;a.array_data=data;a.new_float_array=new_float;a.new_texture2d=new_texture;a.audio_clip_type=reinterpret_cast<void*>(1);a.object_get_name=name;a.director_get_asset=asset;a.director_get_binding=binding;a.director_get_reference=reference;a.component_game_object=game_object;a.track_muted_hierarchy=track_muted;a.active_enabled=active_enabled;a.brain_output_camera=output_camera;a.brain_manual_update=brain_manual;a.camera_clock_ok=camera_clock_ok;a.director_get_time=get_time;a.director_get_duration=duration;a.director_get_mode=get_mode;a.director_set_mode=set_mode;a.director_set_time=set_time;a.director_evaluate=evaluate;a.director_graph_injected=get_graph;a.graph_evaluate_injected=graph_step;a.graph_set_mode_injected=graph_mode;a.graph_valid=graph_valid;a.recorded_graph_mode=recorded_mode;a.player_set_time=reset_player;a.timeline_get_tracks=tracks;a.track_get_clips=clips;a.audio_source_get_volume=volume_get;a.audio_source_set_volume=volume_set;a.audio_clip_samples=samples;a.audio_clip_channels=channels;a.audio_clip_frequency=frequency;a.audio_clip_load_state=loadstate;a.audio_clip_load_type=loadtype;a.audio_clip_load_data=load;a.audio_clip_get_data=get_data;a.bundle_load_file_async=load_bundle;a.async_done=isdone;a.bundle_request_get_bundle=bundle_result;a.bundle_load_asset=load_asset;a.bundle_unload=unload;a.camera_capture_request=capture;a.texture_width=width;a.texture_height=height;a.texture_graphics_format=format;a.texture_srgb=srgb;a.rt_active_get=active_get;a.rt_active_set=active_set;a.texture2d_ctor_rgba=ctor;a.texture2d_read_pixels_injected=readpixels;a.texture2d_raw_data=raw_data;a.object_destroy=destroy;a.shader_use_custom=shader_custom;a.shader_current_time=shader_time;a.shader_set_custom=shader_set;a.shader_reset_custom=shader_reset;return a;}
void setup(){presenter=make("Solis.OutGame.LivePlayerScreenPresenter");player=make("Solis.Common.SolisLivePlayer");controller=make("Solis.Common.Live.SolisLiveTimelineController");director=make("UnityEngine.Playables.PlayableDirector");timeline=make("UnityEngine.Timeline.TimelineAsset");camera_controller=make("VL.Rendering.VLSRPCameraController");camera=make("UnityEngine.Camera");wrapper=make("VL.VLRenderTexture");rt=make("UnityEngine.RenderTexture");bgm=make("UnityEngine.AudioSource");voice=make("UnityEngine.AudioSource");source_clip=make("UnityEngine.AudioClip","sud_music_short_tri-004");private_clip=make("UnityEngine.AudioClip",source_clip->name.c_str());bundle=make("UnityEngine.AssetBundle");request=make("UnityEngine.AssetBundleCreateRequest");track=make("UnityEngine.Timeline.AudioTrack","BGM");clip=make("UnityEngine.Timeline.TimelineClip");
    auto* binder=make("Solis.Common.Live.SolisLiveBinder");auto* actor_list=make("System.Collections.Generic.List`1");auto* actor_array=make("array");actor_array->array_kind=1;actor_controller=make("VL.Core.VLActorController");animation_player=make("VL.VLAnimationClipPlayer");actor_array->pointers={ptr(actor_controller)};write(player,0x58,ptr(binder));write(binder,0x40,ptr(actor_list));write(actor_list,0x10,ptr(actor_array));write(actor_list,0x18,int32_t(1));write(actor_controller,0x20,ptr(animation_player));write(animation_player,0x28,PlayableGraph{reinterpret_cast<void*>(0x2222),9,0});
    auto* initial_directors=make("System.Collections.Generic.List`1");auto* initial_items=make("UnityEngine.Playables.PlayableDirector[]");initial_items->array_kind=1;initial_items->pointers={ptr(director)};
    write(initial_directors,0x10,ptr(initial_items));write(initial_directors,0x18,int32_t(1));write(controller,0x28,ptr(initial_directors));
}
int main(){
    // This smoke guard also compiles both generated architecture maps.
    assert(android_game_profile.presenter_update.rva&&ios_game_profile.presenter_update.rva);
    setup();camera_track=make(".CinemachineTrack");brain=make("Cinemachine.CinemachineBrain");write(brain,0x30,int32_t(2));write(brain,0x34,int32_t(0));
    write(presenter,0xe0,ptr(player));write(player,0x38,ptr(controller));write(controller,0x20,ptr(director));write(player,0x28,ptr(bgm));write(player,0x30,ptr(voice));write(camera_controller,0x50,ptr(camera));write(camera_controller,0xa0,ptr(wrapper));write(wrapper,0x10,ptr(rt));
    auto* owned_directors=make("System.Collections.Generic.List`1");auto* owned_items=make("UnityEngine.Playables.PlayableDirector[]");owned_items->array_kind=1;owned_items->pointers={ptr(director)};
    write(owned_directors,0x10,ptr(owned_items));write(owned_directors,0x18,int32_t(1));write(controller,0x28,ptr(owned_directors));
    auto* ap=make("UnityEngine.Timeline.AudioPlayableAsset");auto* props=make("UnityEngine.Timeline.AudioMixerProperties");auto* cp=make("UnityEngine.Timeline.AudioClipProperties");write(props,0x10,1.f);write(cp,0x10,1.f);write(track,0xa0,ptr(props));write(clip,0x28,ptr(ap));write(ap,0x18,ptr(source_clip));write(ap,0x28,ptr(cp));write(clip,0x18,2.0);write(clip,0x20,0.0);write(clip,0x30,116.0);write(clip,0x38,1.0);write(clip,0x58,-1.0);write(clip,0x60,-1.0);
    Api selected_api=api();selected_api.camera_pixel_width=logical_width;selected_api.camera_pixel_height=logical_height;selected_api.source_geometry=actual_source_geometry;selected_api.output_geometry=resize_output;selected_api.output_projection=project_output;
    GameAdapter a(selected_api);clock_game=&a;a.observe_presenter(ptr(presenter));a.observe_camera_controller(ptr(camera_controller));Snapshot s{};assert(a.snapshot(s)==Result::ok);assert(s.audio.count==1&&s.audio.clips[0].start_seconds==2&&s.duration_seconds==122&&s.audio.clips[0].source_gain==.6f&&!s.procedural_physics_determinism_proven);
    void* audio_director=nullptr,*audio_asset=nullptr,*audio_track=nullptr,*audio_source=nullptr;
    assert(a.selected_audio_track_count()==1&&a.selected_audio_track(0,audio_director,audio_asset,audio_track,audio_source));
    assert(audio_director==ptr(director)&&audio_asset==ptr(timeline)&&audio_track==ptr(track)&&audio_source==ptr(bgm));
    audio_binding_override=ptr(voice);SceneWitness changed_audio{};assert(!a.selected_scene_witness(changed_audio));
    assert(a.selected_audio_track(0,audio_director,audio_asset,audio_track,audio_source)&&audio_source==ptr(bgm));
    audio_binding_override=nullptr;
    assert(!a.selected_audio_track(1,audio_director,audio_asset,audio_track,audio_source)&&!audio_director&&!audio_asset&&!audio_track&&!audio_source);
    int32_t actual_width=0,actual_height=0;assert(a.source_geometry(actual_width,actual_height)==Result::ok&&actual_width==4096&&actual_height==2458);
    source_width=4095;source_height=2457;assert(a.source_geometry(actual_width,actual_height)==Result::ok&&actual_width==4095&&actual_height==2457);
    source_width=7680;source_height=4320;assert(a.source_geometry(actual_width,actual_height)==Result::ok&&actual_width==7680&&actual_height==4320);
    source_width=8193;assert(a.source_geometry(actual_width,actual_height)==Result::unsupported);source_width=4096;source_height=2458;
    assert(a.set_output_geometry(1920,1080)==Result::stale&&geometry_calls.empty());
    write(clip,0x38,2.0);assert(a.snapshot(s)==Result::unsupported);write(clip,0x38,1.0);assert(a.snapshot(s)==Result::ok);
    assert(s.actor_graph_count==1);assert(a.begin_manual()==Result::ok&&mode==3&&bgm_volume==0&&voice_volume==0&&actor_mode==3&&actor_resets==1);assert(a.evaluate(2)==Result::ok&&time_value==2&&shader==2&&graph_steps==1);assert(a.evaluate(2)==Result::ok&&graph_steps==1&&actor_steps==1&&camera_steps==1);graph_variant=1;assert(a.evaluate(3)==Result::ok&&time_value==3&&graph_steps==2);graph_variant=0;assert(a.evaluate(123)==Result::invalid);
    assert(!a.owned_capture_wrapper(ptr(wrapper)));
    assert(a.request_capture()==Result::ok&&a.owned_capture_wrapper(ptr(wrapper)));
    auto* substituted_wrapper=make("VL.VLRenderTexture");write(substituted_wrapper,0x10,ptr(rt));
    assert(!a.owned_capture_wrapper(ptr(substituted_wrapper)));
    int32_t w=0,h=0;assert(a.capture_geometry(w,h)==Result::ok&&w==16&&h==16);std::vector<uint8_t> pixels(1024);size_t bytes=0;assert(a.readback_rgba(pixels.data(),pixels.size(),bytes,w,h)==Result::waiting);
    auto* pass=make("VL.Rendering.VLCapturePass");auto* rd=make("RenderingData");write(rd,0x90,ptr(camera));write(rd,0x158,uint8_t(1));a.observe_capture_pass(ptr(pass),ptr(rd));assert(a.readback_rgba(pixels.data(),pixels.size(),bytes,w,h)==Result::waiting);assert(!a.after_camera(ptr(bgm)));assert(a.after_camera(ptr(camera)));format_value=97;assert(a.readback_rgba(pixels.data(),pixels.size(),bytes,w,h)==Result::unsupported);format_value=4;assert(a.readback_rgba(pixels.data(),pixels.size(),bytes,w,h)==Result::ok&&bytes==1024&&pixels[0]==15&&pixels[15*64]==0&&active==nullptr);
    auto* previous_rt=make("UnityEngine.RenderTexture");auto* external_rt=make("UnityEngine.RenderTexture");
    assert(a.request_capture()==Result::ok);a.observe_capture_pass(ptr(pass),ptr(rd));assert(a.after_camera(ptr(camera)));
    const auto roots_before_readback=handles.size();active=ptr(previous_rt);throw_bind=true;
    try{a.readback_rgba(pixels.data(),pixels.size(),bytes,w,h);assert(false);}catch(int code){assert(code==17);}
    assert(active==ptr(previous_rt)&&handles.size()==roots_before_readback);
    throw_pixels=true;
    try{a.readback_rgba(pixels.data(),pixels.size(),bytes,w,h);assert(false);}catch(int code){assert(code==23);}
    assert(active==ptr(previous_rt)&&handles.size()==roots_before_readback);throw_pixels=false;
    supersede_active=true;replacement_active=ptr(external_rt);
    assert(a.readback_rgba(pixels.data(),pixels.size(),bytes,w,h)==Result::failed);
    assert(active==ptr(external_rt)&&handles.size()==roots_before_readback);supersede_active=false;active=nullptr;
    auto expected=s.audio.clips[0];assert(a.begin_private_audio("/private/derived.bundle",expected)==Result::waiting);assert(a.poll_private_audio()==Result::waiting);done=true;assert(a.poll_private_audio()==Result::ok&&audio_load_calls==0);float pcm[4]{};assert(a.read_audio_chunk(2,2,pcm,4)==Result::ok&&pcm[0]==.25f&&pcm[3]==.4375f);assert(a.read_audio_chunk(7,2,pcm,4)==Result::invalid);a.close_private_audio();assert(unloads==1);
    private_clip->name="wrong-clip";assert(a.begin_private_audio("/private/bad.bundle",expected)==Result::waiting);assert(a.poll_private_audio()==Result::failed);assert(a.poll_private_audio()==Result::failed);a.close_private_audio();private_clip->name=source_clip->name;assert(unloads==2);
    done=false;assert(a.begin_private_audio("/private/second.bundle",expected)==Result::waiting);const size_t held=handles.size();a.close_private_audio();assert(handles.size()==held&&unloads==2);done=true;a.maintenance();assert(unloads==3);
    audio_state=0;assert(a.begin_private_audio("/private/unloaded.bundle",expected)==Result::waiting);assert(a.poll_private_audio()==Result::waiting&&audio_load_calls==1&&audio_state==1);assert(a.poll_private_audio()==Result::waiting&&audio_load_calls==1);audio_state=2;assert(a.poll_private_audio()==Result::ok);a.close_private_audio();assert(unloads==4);
    a.restore();assert(mode==0&&time_value==13.25&&bgm_volume==.6f&&voice_volume==.4f&&!custom&&destroys==1&&actor_mode==1&&camera_resets==2&&*reinterpret_cast<int32_t*>(brain->mem.data()+0x30)==2&&*reinterpret_cast<int32_t*>(brain->mem.data()+0x34)==0);a.reset_observations();assert(handles.empty());
    a.observe_presenter(ptr(presenter));a.observe_camera_controller(ptr(camera_controller));assert(a.snapshot(s)==Result::ok&&a.begin_manual()==Result::ok);graph_variant=2;const int steps_before=graph_steps;assert(a.evaluate(1)==Result::unsupported&&graph_steps==steps_before+1);assert(a.evaluate(1)==Result::failed&&graph_steps==steps_before+1);a.reset_observations();assert(handles.empty()&&mode==0&&time_value==13.25);
    // Source readback accepts odd phone/aspect dimensions. Only the separately
    // selected encoded output is constrained to even dimensions.
    graph_variant=0;capture_width=17;capture_height=19;
    a.observe_presenter(ptr(presenter));a.observe_camera_controller(ptr(camera_controller));
    assert(a.snapshot(s)==Result::ok&&a.begin_manual()==Result::ok);
    assert(a.request_capture()==Result::ok&&a.capture_geometry(w,h)==Result::ok&&w==17&&h==19);
    assert(a.set_output_geometry(1921,1080)==Result::invalid&&geometry_calls.empty());
    assert(a.set_output_geometry(1920,1080)==Result::ok);
    assert((geometry_calls==std::vector<std::array<int32_t,2>>{{1920,1080}}));
    a.reset_observations();assert((geometry_calls==std::vector<std::array<int32_t,2>>{{1920,1080},{0,0}})&&handles.empty());
    // Even a callback failure can follow original texture destruction, so it
    // must retain its restoration obligation during terminal cleanup.
    geometry_resize_good=false;
    a.observe_presenter(ptr(presenter));a.observe_camera_controller(ptr(camera_controller));
    assert(a.snapshot(s)==Result::ok&&a.begin_manual()==Result::ok);
    assert(a.set_output_geometry(3840,2160)==Result::failed);
    a.reset_observations();assert(geometry_calls.size()==4&&geometry_calls.back()[0]==0&&geometry_calls.back()[1]==0&&handles.empty());
    a.reset_observations();assert(geometry_calls.size()==4);
    const auto normal_scene=[&](){mode=0;time_value=13.25;bgm_volume=.6f;voice_volume=.4f;actor_mode=1;custom=false;shader=4;
        write(animation_player,0x28,PlayableGraph{reinterpret_cast<void*>(0x2222),9,0});geometry_resize_good=true;};
    const auto observe=[&](){a.observe_presenter(ptr(presenter));a.observe_camera_controller(ptr(camera_controller));assert(a.snapshot(s)==Result::ok);};
    // Rebuilding only an actor graph must still roll back this same director,
    // camera and audio state, while never writing the actor's replacement graph.
    normal_scene();observe();rebuild_actor_on_reset=true;
    assert(a.begin_manual()==Result::unsupported&&!std::strcmp(a.last_error(),"actor_graph_rebuilt_during_reset"));
    assert(mode==0&&time_value==13.25&&bgm_volume==.6f&&voice_volume==.4f&&actor_mode==2&&!custom);
    rebuild_actor_on_reset=false;a.reset_observations();assert(handles.empty());
    normal_scene();observe();assert(a.begin_manual()==Result::ok);
    write(animation_player,0x28,PlayableGraph{reinterpret_cast<void*>(0x3333),10,0});actor_mode=2;
    assert(a.restore()==Result::ok&&mode==0&&bgm_volume==.6f&&voice_volume==.4f&&actor_mode==2);
    a.reset_observations();assert(handles.empty());
    // A reused primary scene (even the same controller/camera addresses) must
    // receive no saved RT/lens/time/audio writes from the former owner.
    normal_scene();observe();assert(a.begin_manual()==Result::ok&&a.set_output_geometry(1920,1080)==Result::ok);
    const auto before_calls=geometry_calls.size();take_over_scene();
    assert(a.restore()==Result::ok&&geometry_calls.size()==before_calls&&geometry_cleanup_calls==1);
    assert(mode==2&&time_value==9&&bgm_volume==.3f&&voice_volume==.7f&&actor_mode==2&&custom&&shader==77);
    a.reset_observations();assert(handles.empty());
    // Original director evaluation and RT target callbacks may themselves
    // transition a pooled scene. Recheck ownership after each callback.
    normal_scene();observe();assert(a.begin_manual()==Result::ok);transition_during_evaluate=true;
    assert(a.restore()==Result::ok&&mode==2&&time_value==9&&bgm_volume==.3f&&voice_volume==.7f&&actor_mode==2&&custom&&shader==77);
    transition_during_evaluate=false;a.reset_observations();assert(handles.empty());
    normal_scene();observe();assert(a.begin_manual()==Result::ok&&a.set_output_geometry(1920,1080)==Result::ok);
    transition_during_resize_restore=true;
    assert(a.restore()==Result::ok&&mode==2&&time_value==9&&bgm_volume==.3f&&voice_volume==.7f&&actor_mode==2&&custom&&shader==77);
    transition_during_resize_restore=false;a.reset_observations();assert(handles.empty());
    // Only an actual returned operation may authorize the native request. CPU
    // discard does not consume the original renderer's still-queued request.
    normal_scene();observe();assert(a.install_capture_operations(capture_begin,capture_end));
    assert(a.begin_manual()==Result::ok&&!a.install_capture_operations(capture_begin,capture_end));
    int before_capture_calls=raw_captures;op_observe_inflight=true;op_try_reenter=true;op_wait=true;
    assert(a.request_capture()==Result::waiting&&raw_captures==before_capture_calls&&!a.owned_pending_capture(ptr(wrapper)));
    op_wait_ticket=true;assert(a.request_capture()==Result::failed&&raw_captures==before_capture_calls);op_wait_ticket=false;op_wait=false;
    op_zero=true;assert(a.request_capture()==Result::failed&&raw_captures==before_capture_calls);op_zero=false;
    op_end_good=false;assert(a.request_capture()==Result::failed&&raw_captures==before_capture_calls+1&&!a.owned_pending_capture(ptr(wrapper)));op_end_good=true;assert(!a.owned_capture_request(ptr(camera_controller),op_serial));
    op_throw=true;try{a.request_capture();assert(false);}catch(int code){assert(code==37);}op_throw=false;assert(op_failed_ends==1&&!a.owned_pending_capture(ptr(wrapper))&&!a.owned_capture_request(ptr(camera_controller),op_serial));
    assert(a.request_capture()==Result::ok&&a.owned_pending_capture(ptr(wrapper))
        &&a.owned_pending_capture(ptr(camera),ptr(camera_controller),ptr(wrapper))
        &&!a.owned_pending_capture(ptr(bgm),ptr(camera_controller),ptr(wrapper)));
    assert(!a.owned_capture_request(ptr(camera_controller),op_serial)&&a.owned_capture_request_serial(ptr(camera_controller))==0
        &&a.capture_request_origin_serial(ptr(camera_controller))==0&&!a.capture_operation_starting(ptr(camera_controller)));
    a.discard_capture();assert(a.owned_pending_capture(ptr(wrapper)));
    before_capture_calls=raw_captures;op_reuse=true;assert(a.request_capture()==Result::failed&&raw_captures==before_capture_calls);op_reuse=false;
    a.reset_observations();assert(handles.empty()&&!a.owned_pending_capture(ptr(wrapper)));
    normal_scene();observe();assert(a.begin_manual()==Result::ok);op_handoff=true;
    assert(a.request_capture()==Result::stale&&!a.owned_pending_capture(ptr(wrapper)));
    op_handoff=false;a.reset_observations();assert(handles.empty()&&mode==2&&time_value==9);
}
'''


def test_original_game_adapter_timeline_render_and_cleanup(tmp_path):
    compiler=shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    source=tmp_path/'adapter.cpp';source.write_text(SOURCE)
    executable=tmp_path/'adapter'
    subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(ROOT/'client-presentation/native'),str(source),'-o',str(executable)],check=True,capture_output=True,text=True)
    subprocess.run([str(executable)],check=True,capture_output=True,text=True)
