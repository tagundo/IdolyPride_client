#include <cmath>
#include <initializer_list>
#include "mp4_camera_owner.hpp"
#include <string>
#include <cassert>
#include <map>
using namespace idoly_mp4_camera_state;
struct Payload {int32_t value=0;int32_t pad=0;void* reference=nullptr;};
struct Sound {void* clip=nullptr;int32_t samples=20;float volume=.6f,pitch=1;bool playing=false,paused=true,loop=false,mute=false;};
struct Host {Scope scope;Payload brain{8},frame{7},status{40};Sound sound;int clip=1,transform=2,object=3;int32_t frame_count=50,mixer=7;bool own=true,held=true,no_barrier=false,corrupt=false;int writes=0,restores=0;uint32_t next=1;std::map<uint32_t,void*> roots;LensImage lens{};};
Host* host;bool logical_ok=true,timeline_output=true;int logical_calls=0,play_calls=0,stop_calls=0,seek_calls=0;
bool logical(void*,void*,bool,bool){++logical_calls;return logical_ok;}
uint32_t retain(void* p){auto id=host->next++;host->roots[id]=p;return id;}void* target(uint32_t h){auto i=host->roots.find(h);return i==host->roots.end()?nullptr:i->second;}void release(uint32_t h){host->roots.erase(h);}
bool current(void*,const Owner&){return host->own;}bool held(void*){return host->held;}bool mapped(const void*p,size_t n,bool){return p&&n;}bool alive(void*p){return p;}bool admit(void*,const Owner&){return true;}
bool roots(void*,void** out,size_t cap,size_t* n){if(cap<3)return false;out[0]=&host->brain;out[1]=&host->frame;out[2]=&host->status;*n=3;return true;}
bool describe(void*,void* p,Description& d){d={};d.klass=host;d.data=(uint8_t*)p;d.bytes=sizeof(Payload);d.references=1;d.reference_offsets[0]=8;
 if(p==&host->brain){d.role=Role::brain;d.next_id_offset=0;d.unity_component=true;}else if(p==&host->frame){d.role=Role::brain_frame;d.identity_offset=0;}else if(p==&host->status){d.role=Role::core_status;d.last_frame_offset=0;}else return false;return true;}
Follow follow(void*,void*,void*){return Follow::leaf;}void barrier(void*,void** p,void*v){++host->writes;if(!host->no_barrier)*p=v;}
bool comp_capture(void*,void*,ComponentImage& x){x={};x.transform=&host->transform;x.game_object=&host->object;return true;}bool comp_restore(void*,void*,const ComponentImage&){++host->restores;return !host->corrupt;}bool comp_verify(void*,void*,const ComponentImage&){return true;}
bool global_capture(void*,GlobalImage& x){x={};return true;}bool global_restore(void*,const GlobalImage&){return true;}bool global_verify(void*,const GlobalImage&){return true;}
bool lens_capture(void*,void*,LensImage& x){x=host->lens;return true;}bool lens_restore(void*,void*,const LensImage& x){host->lens=x;return true;}bool lens_verify(void*,void*,const LensImage&){return true;}
bool mixers(void*,Mixer* m,size_t cap,size_t* n){if(!cap)return false;m[0]={};m[0].director=&host->clip;m[0].brain=&host->brain;m[0].id=host->mixer;*n=1;return true;}int32_t count(){return host->frame_count;}bool reset(void*,const Owner&){return true;}
void* clip(void*p,Method*){return ((Sound*)p)->clip;}void setclip(void*p,void*q,Method*){((Sound*)p)->clip=q;}int32_t samples(void*p,Method*){return ((Sound*)p)->samples;}void setsamples(void*p,int32_t v,Method*){++seek_calls;((Sound*)p)->samples=v;}bool playing(void*p,Method*){return ((Sound*)p)->playing;}
float vol(void*p,Method*){return ((Sound*)p)->volume;}void setvol(void*p,float v,Method*){((Sound*)p)->volume=v;}float pitch(void*p,Method*){return ((Sound*)p)->pitch;}void setpitch(void*p,float v,Method*){((Sound*)p)->pitch=v;}bool loop(void*p,Method*){return ((Sound*)p)->loop;}void setloop(void*p,bool v,Method*){((Sound*)p)->loop=v;}bool mute(void*p,Method*){return ((Sound*)p)->mute;}void setmute(void*p,bool v,Method*){((Sound*)p)->mute=v;}
void play(void*p,Method*){++play_calls;((Sound*)p)->playing=true;((Sound*)p)->paused=false;}void stop(void*p,Method*){++stop_calls;((Sound*)p)->playing=false;((Sound*)p)->paused=false;}void pause(void*p,Method*){((Sound*)p)->paused=true;((Sound*)p)->playing=false;}void unpause(void*p,Method*){((Sound*)p)->paused=false;}bool paused(void*p,bool*v){*v=((Sound*)p)->paused;return true;}bool timeline(void*,void*){return timeline_output;}int32_t clipsamples(void*,Method*){return 100;}bool supported(void*,void*p,bool has_clip,bool is_playing,bool is_paused){auto& x=*static_cast<Sound*>(p);return bool(x.clip)==has_clip&&x.playing==is_playing&&x.paused==is_paused;}
Api api(){Api a{};a.current=current;a.held=held;a.mapped=mapped;a.alive=alive;a.retain=retain;a.target=target;a.release=release;a.admit=admit;a.roots=roots;a.describe=describe;a.follow=follow;a.write_reference=barrier;a.component_capture=comp_capture;a.component_restore=comp_restore;a.component_verify=comp_verify;a.lens_capture=lens_capture;a.lens_restore=lens_restore;a.lens_verify=lens_verify;a.global_capture=global_capture;a.global_restore=global_restore;a.global_verify=global_verify;a.mixers=mixers;a.frame_count=count;a.reset_history=reset;
a.audio={clip,setclip,samples,setsamples,playing,vol,setvol,pitch,setpitch,loop,setloop,mute,setmute,play,stop,pause,unpause,paused,timeline,clipsamples,supported};a.audio.timeline_logical_restored=logical;return a;}
void configure(Host& h,bool direct=true){host=&h;if(direct)h.sound.clip=&h.clip;h.brain.reference=&h.frame;Owner o{};o.player=&h;o.director=&h.clip;o.camera=&h.object;o.controller=&h.transform;o.brain=&h.brain;o.bgm=&h.sound;o.generation=2;assert(h.scope.configure(api(),&h,o)==Result::ok);assert(h.scope.capture()==Result::ok);}

int main(int argc,char**argv){assert(argc==2);std::string c=argv[1];Host h;
 if(c=="missing_api"||c=="unowned_active"){
  host=&h;h.brain.reference=&h.frame;h.sound.playing=true;h.sound.paused=false;Owner o{};o.player=&h;o.director=&h.clip;o.camera=&h.object;o.controller=&h.transform;o.brain=&h.brain;o.bgm=&h.sound;o.generation=2;
  auto a=api();if(c=="missing_api")a.audio.timeline_logical_restored=nullptr;else timeline_output=false;
  assert(h.scope.configure(a,&h,o)==Result::ok);assert(h.scope.capture()==Result::unsupported);assert(h.scope.release(false)==Result::ok);assert(h.roots.empty());return 0;
 }
 const bool direct=c=="direct_unchanged";
 if(c=="active"||c=="logical_reject"){h.sound.playing=true;h.sound.paused=false;}
 if(c=="paused_fast"){h.sound.playing=true;h.sound.paused=true;}
 configure(h,direct);assert(h.scope.prepare()==Result::ok);assert(h.scope.restore()==Result::ok);
 if(c=="active"||c=="paused_fast"||c=="logical_reject")h.sound.playing=false;
 if(c=="logical_reject")logical_ok=false;
 if(c=="direct_unchanged")h.sound.playing=true;
 if(c=="property_reject")h.sound.pitch=2;
 const auto r=h.scope.verify_source_restored();
 if(c=="logical_reject"||c=="property_reject"||c=="direct_unchanged")assert(r==Result::failed);
 else assert(r==Result::ok);
 if(direct)assert(!logical_calls);else {assert(!play_calls&&!stop_calls&&!seek_calls);if(c!="property_reject")assert(logical_calls==1);}
 assert(h.scope.release(false)==Result::ok);assert(h.roots.empty());
}
