#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdio>
#include <map>
#include <vector>
#include <stdexcept>
// TARGET_SCOPE
namespace t=idoly_mp4_target_image;
struct F{int director=0,asset=0,track=0,track2=0,image=0,rect=0,oldtex=0,newtex=0,other=0,oldmixer=0,newmixer=0;bool current=true,held=true,admitted=true,remap=true,failenabled=false,mismatch=false,callback_loss=false;unsigned reads=0,queries=0,writes=0;std::map<uint32_t,void*>roots;uint32_t next=1;t::Image value{};t::Program program{};t::Scope scope;};F*f;
bool thread(){return true;}bool current(void*,uint64_t e,uint64_t j){++f->queries;return f->current&&e==7&&j==9;}bool held(void*){++f->queries;return f->held;}
bool empty_inventory=false;
bool inventory(void*,t::Owner*out,t::Program*p,size_t,size_t*n){if(empty_inventory){*n=0;return true;}out[0]={&f->director,&f->asset,&f->track,&f->image,7,9};p[0]={&f->oldmixer,&f->image,false};*n=1;return true;}
bool owner(void*,const t::Owner&o){++f->queries;return f->current&&o.director==&f->director&&o.asset==&f->asset&&o.track==&f->track&&o.image==&f->image;}
bool image(void*,void*object,t::Image*out){assert(f->current);++f->reads;if(object!=&f->image)return false;*out=f->value;return true;}
bool admitted(void*,const t::Owner&,const t::Image&){++f->queries;return f->admitted;}
bool restored_program(void*,const t::Owner&,t::Program*out){assert(f->current);++f->reads;*out=f->program;return true;}
bool cache(void*,const t::Owner&,const t::Program&actual,const t::Program&saved){assert(f->current&&actual.mixer==&f->newmixer);++f->writes;f->program.cached_image=saved.cached_image;f->program.initial_enabled=saved.initial_enabled;return true;}
bool texture(void*,const t::Owner&,const t::Image&saved,void**out){assert(f->current);++f->reads;if(!f->remap)return false;*out=saved.role==t::TextureRole::source_controller_rt?&f->newtex:saved.texture;return true;}
bool set_texture(void*,void*,void*value){assert(f->current);++f->writes;f->value.texture=value;if(f->callback_loss)f->current=false;return true;}
bool uv(void*,void*,t::Rect value){assert(f->current);++f->writes;if(!f->mismatch)f->value.uv=value;return true;}
bool color(void*,void*,t::Color value){assert(f->current);++f->writes;f->value.color=value;return true;}
bool enabled(void*,void*,bool value){assert(f->current);++f->writes;f->value.enabled=value;if(f->failenabled)throw std::runtime_error("enabled callback");return true;}
uint32_t retain(void*p){uint32_t id=f->next++;f->roots[id]=p;return id;}void*get(uint32_t id){auto i=f->roots.find(id);return i==f->roots.end()?nullptr:i->second;}void drop(uint32_t id){assert(f->roots.erase(id)==1);}
t::Api api(){return {thread,current,held,inventory,owner,image,admitted,restored_program,cache,texture,set_texture,uv,enabled,color,retain,get,drop};}

struct Mp4SceneWitness{uint64_t generation=0,identity=0;};
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation&&a.generation==b.generation&&a.identity==b.identity;}
F state;
namespace mp4target=t;
struct Host{t::Scope&scope;Mp4SceneWitness source{};uint64_t job=0;}mp4_target_image_host{state.scope};
struct{Mp4SceneWitness source{7,11};}mp4_scene_host;
namespace idoly_mp4_runtime{struct{uint64_t generation=9;}job;}
bool owner_thread=true,host_current=true,throw_capture=false,force_fail=false;unsigned actual_calls=0;
bool game_call(){return owner_thread;}
bool mp4_target_image_current(void*,uint64_t epoch,uint64_t job){return host_current&&state.current&&epoch==mp4_target_image_host.source.generation&&job==mp4_target_image_host.job;}
bool mp4_target_image_held(void*){return state.held;}
t::Result mp4_target_image_capture(uint64_t job){++actual_calls;auto&h=mp4_target_image_host;h.source=mp4_scene_host.source;h.job=job;if(throw_capture)throw std::runtime_error("capture");if(force_fail)return t::Result::unsupported;return h.scope.capture(api(),&h,h.source.generation,job);}
t::Result mp4_target_image_release(){auto&h=mp4_target_image_host;auto result=h.scope.release();if(result==t::Result::ok){h.source={};h.job=0;}return result;}
// CAPTURE_HOST
void setup(){f=&state;assert(state.scope.release()==t::Result::ok);state=F{};f=&state;state.value={&state.image,&state.oldtex,&state.rect,0x123,{.1f,.2f,.7f,.8f},true,t::TextureRole::source_controller_rt};state.program={&state.newmixer,&state.image,true};owner_thread=host_current=true;throw_capture=force_fail=empty_inventory=false;actual_calls=0;mp4_target_image_host.source={};mp4_target_image_host.job=0;mp4_scene_host.source={7,11};idoly_mp4_runtime::job.generation=9;mp4_target_image_capture_receipt={};}
t::Owner expected(){return {&state.director,&state.asset,&state.track,&state.image,7,9};}
bool snapshot(Mp4TargetImageSnapshot*out){return mp4_target_image_captured_snapshot(mp4_scene_host.source,9,expected(),out);}
int main(){unsigned cases=0;
 {setup();Mp4TargetImageSnapshot out{};assert(!snapshot(&out)&&!actual_calls);++cases;}
 {setup();assert(mp4_target_image_capture_recorded(9)==t::Result::ok&&actual_calls==1);Mp4TargetImageSnapshot out{};assert(snapshot(&out)&&out.scope==&state.scope&&out.saved.program.mixer==&state.oldmixer&&out.saved.image.native==0x123&&out.capture&&out.invocation);assert(mp4_target_image_capture_recorded(9)==t::Result::ok&&actual_calls==1);++cases;}
 {setup();assert(mp4_target_image_capture(9)==t::Result::ok&&state.scope.captured());Mp4TargetImageSnapshot out{};assert(!snapshot(&out)&&mp4_target_image_capture_recorded(9)==t::Result::unsupported);++cases;}
 {setup();force_fail=true;assert(mp4_target_image_capture_recorded(9)==t::Result::unsupported&&actual_calls==1);force_fail=false;assert(mp4_target_image_capture_recorded(9)==t::Result::stale&&actual_calls==1);assert(mp4_target_image_release_recorded()==t::Result::ok&&mp4_target_image_capture_recorded(9)==t::Result::ok&&actual_calls==2);++cases;}
 {setup();throw_capture=true;try{(void)mp4_target_image_capture_recorded(9);assert(false);}catch(const std::runtime_error&){}throw_capture=false;assert(mp4_target_image_capture_receipt.entered&&!mp4_target_image_capture_receipt.completed&&mp4_target_image_capture_recorded(9)==t::Result::stale);++cases;}
 {setup();assert(mp4_target_image_capture_recorded(9)==t::Result::ok);auto old=mp4_target_image_capture_receipt.invocation;assert(mp4_target_image_release_recorded()==t::Result::ok&&mp4_target_image_capture_recorded(9)==t::Result::ok&&mp4_target_image_capture_receipt.invocation>old);++cases;}
 {setup();assert(mp4_target_image_capture_recorded(9)==t::Result::ok);Mp4TargetImageSnapshot out{};state.current=false;auto reads=state.reads;assert(!snapshot(&out)&&!out.capture&&state.reads==reads);state.current=true;++cases;}
 {setup();assert(mp4_target_image_capture_recorded(9)==t::Result::ok);Mp4TargetImageSnapshot out{};state.held=false;assert(!snapshot(&out));++cases;}
 {setup();assert(mp4_target_image_capture_recorded(9)==t::Result::ok);Mp4TargetImageSnapshot out{};state.value.native=0x124;assert(!snapshot(&out));++cases;}
 {setup();assert(mp4_target_image_capture_recorded(9)==t::Result::ok);Mp4TargetImageSnapshot out{};state.value.rect_transform=&state.other;assert(!snapshot(&out));++cases;}
 {setup();assert(mp4_target_image_capture_recorded(9)==t::Result::ok);Mp4TargetImageSnapshot out{};state.admitted=false;assert(!snapshot(&out));++cases;}
 {setup();assert(mp4_target_image_capture_recorded(9)==t::Result::ok);Mp4TargetImageSnapshot out{};auto owner=expected();owner.track=&state.track2;assert(!mp4_target_image_captured_snapshot(mp4_scene_host.source,9,owner,&out));++cases;}
 {setup();assert(mp4_target_image_capture_recorded(9)==t::Result::ok);Mp4TargetImageSnapshot out{};idoly_mp4_runtime::job.generation=10;assert(!snapshot(&out));++cases;}
 {setup();assert(mp4_target_image_capture_recorded(9)==t::Result::ok);Mp4TargetImageSnapshot out{};mp4_scene_host.source.identity=12;assert(!snapshot(&out));++cases;}
 {setup();assert(mp4_target_image_capture_recorded(9)==t::Result::ok);Mp4TargetImageSnapshot out{};auto root=state.roots.begin()->first;void*object=state.roots[root];state.roots.erase(root);assert(!snapshot(&out));state.roots[root]=object;++cases;}
 {setup();assert(mp4_target_image_capture_recorded(9)==t::Result::ok);Mp4TargetImageSnapshot out{};state.value.uv={3,4,5,6};state.value.enabled=false;state.value.color={0,0,0,0};assert(snapshot(&out)&&out.saved.image.uv.x==.1f&&out.saved.image.enabled&&out.saved.image.color.a==1);++cases;}
 {setup();assert(mp4_target_image_capture_recorded(9)==t::Result::ok);owner_thread=false;assert(mp4_target_image_release_recorded()==t::Result::waiting&&state.scope.captured());owner_thread=true;++cases;}
 {setup();empty_inventory=true;assert(mp4_target_image_capture_recorded(9)==t::Result::ok&&mp4_target_image_capture_receipt_current(9)&&state.roots.empty());Mp4TargetImageSnapshot out{};assert(!snapshot(&out));++cases;}
 {setup();empty_inventory=true;assert(mp4_target_image_capture_recorded(9)==t::Result::ok);state.current=false;auto reads=state.reads;assert(!mp4_target_image_capture_receipt_current(9)&&state.reads==reads);state.current=true;++cases;}
 {setup();t::completed_capture_sequence=~uint64_t(0);assert(mp4_target_image_capture_recorded(9)==t::Result::unsupported&&state.scope.captured()&&!state.scope.capture_receipt_raw()&&!mp4_target_image_capture_receipt_current(9));++cases;}
 assert(mp4_target_image_release_recorded()==t::Result::ok&&state.roots.empty());printf("%u exact TargetImage capture/image receipt cases; engine image calls modeled\n",cases);
}
