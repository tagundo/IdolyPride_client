#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdio>
#include <map>
#include <vector>
#include <stdexcept>
#include "target_image_scope.inc"
namespace t=idoly_mp4_target_image;
struct F{int director=0,asset=0,track=0,track2=0,image=0,rect=0,oldtex=0,newtex=0,other=0,oldmixer=0,newmixer=0;bool current=true,held=true,admitted=true,remap=true,failenabled=false,mismatch=false,callback_loss=false;unsigned reads=0,queries=0,writes=0;std::map<uint32_t,void*>roots;uint32_t next=1;t::Image value{};t::Program program{};t::Scope scope;};F*f;
bool thread(){return true;}bool current(void*,uint64_t e,uint64_t j){++f->queries;return f->current&&e==7&&j==9;}bool held(void*){++f->queries;return f->held;}
bool inventory(void*,t::Owner*out,t::Program*p,size_t,size_t*n){out[0]={&f->director,&f->asset,&f->track,&f->image,7,9};p[0]={&f->oldmixer,&f->image,false};*n=1;return true;}
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
void begin(F&fixture){f=&fixture;f->value={&f->image,&f->oldtex,&f->rect,0x123,{.1f,.2f,.7f,.8f},true,t::TextureRole::source_controller_rt};f->program={&f->newmixer,&f->image,true};assert(f->scope.capture(api(),f,7,9)==t::Result::ok);f->value.texture=&f->other;f->value.uv={0,0,1,1};f->value.enabled=false;f->value.color={0,0,0,0};}
int main(){int cases=0;
 {F x;begin(x);assert(x.scope.restore()==t::Result::ok&&x.scope.restored());assert(x.value.texture==&x.newtex&&x.value.enabled&&x.value.uv.x==.1f&&x.value.color.a==1&&!x.program.initial_enabled);unsigned r=x.reads,q=x.queries,w=x.writes;x.current=false;x.value.uv={3,4,5,6};assert(x.scope.restore()==t::Result::ok&&x.scope.release()==t::Result::ok&&x.roots.empty());assert(x.reads==r&&x.queries==q&&x.writes==w);++cases;}
 {F x;begin(x);x.held=false;assert(x.scope.restore()==t::Result::waiting&&!x.writes);x.held=true;assert(x.scope.restore()==t::Result::ok);assert(x.scope.release()==t::Result::ok);++cases;}
 {F x;begin(x);x.current=false;unsigned r=x.reads,w=x.writes;assert(x.scope.restore()==t::Result::stale&&x.reads==r&&x.writes==w);unsigned q=x.queries;assert(x.scope.release()==t::Result::ok&&x.queries==q&&x.reads==r);++cases;}
 {F x;begin(x);x.value.native=0x456;assert(x.scope.restore()==t::Result::stale&&!x.writes);assert(x.scope.release()==t::Result::ok);++cases;}
 {F x;begin(x);x.remap=false;assert(x.scope.restore()==t::Result::stale&&!x.writes);assert(x.scope.release()==t::Result::ok);++cases;}
 {F x;begin(x);x.program.cached_image=&x.other;assert(x.scope.restore()==t::Result::stale&&!x.writes);assert(x.scope.release()==t::Result::ok);++cases;}
 {F x;begin(x);x.callback_loss=true;assert(x.scope.restore()==t::Result::stale&&x.writes==1);assert(x.scope.release()==t::Result::ok);++cases;}
 {F x;begin(x);x.failenabled=true;try{x.scope.restore();assert(false);}catch(const std::runtime_error&){}assert(!x.scope.restored());x.failenabled=false;assert(x.scope.restore()==t::Result::ok&&x.scope.release()==t::Result::ok);++cases;}
 {F x;begin(x);x.mismatch=true;assert(x.scope.restore()==t::Result::failed&&!x.scope.restored());x.mismatch=false;assert(x.scope.restore()==t::Result::ok&&x.scope.release()==t::Result::ok);++cases;}
 {F x;begin(x);uint32_t id=x.roots.begin()->first;void*object=x.roots[id];x.roots.erase(id);assert(x.scope.restore()==t::Result::stale&&!x.writes);x.roots[id]=object;assert(x.scope.release()==t::Result::ok);++cases;}
 std::printf("%d TargetImage sourceRT/cache/logical-restore scenarios passed; modeled native UI, no visual/GPU claim\n",cases);
}
