#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#define idoly_mp4_stage actual_stage_scope
#include "mp4_stage_state.hpp"
#undef idoly_mp4_stage
#include "particle-native-coordinator-cache-model.inc"
namespace actual_scope_admission {

using namespace actual_stage_scope;
struct List {std::vector<unsigned char> data;size_t stride=4;};
std::vector<List*> allocated;
List* list(size_t stride,int n=0){auto*p=new List;p->stride=stride;p->data.resize(stride*n,42);allocated.push_back(p);return p;}
struct PS {PlaybackState state{};std::vector<Particle> particles;bool paused=true,stopped=false,emitting=false,playing=false,automatic=true;uint32_t seed=17;} ps,other;
struct Ctx {bool current=true,held=true,controlled=true,reset=true,granted=false,inventory=true;uint64_t tick=0;} context;
struct Box{uint8_t header[16]{};Trails value{};};std::vector<Box*>boxes;
int camera,controller,pass,block,foreigncamera,producer;void* passController=&controller;void* passBlock=&block;
float sourceTime=-1,speed=2,property=47;int writes=0,fences=0,sets=0,getfloats=0;bool failroot=false,badlist=false;
uint32_t producer_kind=1;float last_time=30,system_time=20;
std::map<uint32_t,void*> roots;uint32_t rootserial=0;
int ownerchecks=0;
bool current(void*){++ownerchecks;return context.current&&mp4_particle_native_early_current();}bool held(void*){return context.held;}bool granted(void*,uint64_t n){return context.granted&&context.tick==n;}
bool inventory(void*,const Owner*,size_t){return context.inventory;}
Result controlled(void*,void*){return context.controlled?Result::ok:Result::unsupported;}Result reset_ready(void*,void*){return context.reset?Result::ok:Result::waiting;}
bool type(void*p,const char*n){if(!p)return false;std::string name=n;if(name=="UnityEngine.Timeline.ParticleControlPlayable")return p==&producer&&producer_kind==1;if(name=="Solis.Live.Equipment.Environment.LiveParticleEffect")return p==&producer&&producer_kind==2;if(name=="UnityEngine.ParticleSystem")return p==&ps||p==&other;if(name=="UnityEngine.Camera")return p==&camera||p==&foreigncamera;if(name=="Solis.Live.Psyllium.PsylliumController")return p==&controller;if(name=="Solis.Live.Psyllium.RenderPsyllium")return p==&pass;if(name=="UnityEngine.MaterialPropertyBlock")return p==&block;return false;}
bool alive(void*){return true;}uint32_t retain(void*p){if(failroot)return 0;roots[++rootserial]=p;return rootserial;}void* retained(uint32_t n){auto i=roots.find(n);return i==roots.end()?nullptr:i->second;}void release(uint32_t n){assert(roots.erase(n)==1);}
bool createbox(RootedTrails*out){auto*b=new Box;boxes.push_back(b);out->object=b;out->value=&b->value;out->root=retain(b);return out->root!=0;}
bool view(void*p,size_t stride,ListView*out){auto*l=static_cast<List*>(p);if(badlist||l->stride!=stride)return false;out->array=p;out->data=l->data.data();out->count=l->data.size()/stride;out->capacity=l->data.capacity()/stride;return true;}
void getplay(void*p,PlaybackState*out,Method*){assert(context.held);++fences;*out=static_cast<PS*>(p)->state;}
void setplay(void*p,PlaybackState*in,Method*){++writes;static_cast<PS*>(p)->state=*in;}
int count(void*p,Method*){return static_cast<int>(static_cast<PS*>(p)->particles.size());}
int getdata(void*p,void*out,int capacity,int n,int offset,Method*){assert(out&&capacity==n&&offset==0);auto&v=static_cast<PS*>(p)->particles;assert(static_cast<int>(v.size())==n);if(n)memcpy(out,v.data(),n*sizeof(Particle));return n;}
void setdata(void*p,void*in,int capacity,int n,int offset,Method*){assert(in&&capacity==n&&offset==0);++writes;auto&v=static_cast<PS*>(p)->particles;v.resize(n);if(n)memcpy(v.data(),in,n*sizeof(Particle));}
bool paused(void*p,Method*){return static_cast<PS*>(p)->paused;}bool playing(void*p,Method*){return static_cast<PS*>(p)->playing;}bool stopped(void*p,Method*){return static_cast<PS*>(p)->stopped;}bool emitting(void*p,Method*){return static_cast<PS*>(p)->emitting;}
uint32_t seed(void*p,Method*){return static_cast<PS*>(p)->seed;}void setseed(void*p,uint32_t s,Method*){++writes;static_cast<PS*>(p)->seed=s;static_cast<PS*>(p)->automatic=false;}
bool automatic(void*p,Method*){return static_cast<PS*>(p)->automatic;}void setauto(void*p,bool a,Method*){++writes;static_cast<PS*>(p)->automatic=a;}
void allocate(Trails*t,Method*){bool rooted=false;for(auto*b:boxes)if(&b->value==t)for(const auto&r:roots)if(r.second==b)rooted=true;assert(rooted);for(int i=0;i<5;++i)if(!t->lists[i])t->lists[i]=list(i?4:16);}
int gettrails(void*,Trails*t,Method*){allocate(t,nullptr);for(int i=0;i<5;++i)static_cast<List*>(t->lists[i])->data.resize((i?4:16)*2,12);t->maximum_trails=3;t->maximum_positions=8;return 2;}
void settrails(void*,Trails*t,Method*){++writes;assert(t->maximum_trails==3);}
int customget(void*,void*l,int stream,Method*){assert(stream==0||stream==1);static_cast<List*>(l)->data.resize(32,static_cast<unsigned char>(stream+9));return 2;}
void customset(void*,void*l,int stream,Method*){++writes;assert(static_cast<List*>(l)->data[0]==stream+9);}
void pause(void*p,bool children,Method*){assert(!children);++writes;auto*s=static_cast<PS*>(p);s->paused=true;s->playing=false;s->stopped=false;}
void stop(void*p,bool children,int behavior,Method*){assert(!children&&behavior==1);++writes;auto*s=static_cast<PS*>(p);s->paused=false;s->playing=false;s->stopped=true;}
bool control_current(void*,const Owner&){return context.controlled;}
Result readcontrol(void*,const Owner&o,ControlState*out){assert(o.producer==&producer);out->first=last_time;out->second=system_time;out->random_seed=producer_kind==1?44:0;out->kind=producer_kind;return Result::ok;}
Result resetcontrol(void*,const Owner&o){assert(o.producer==&producer);if(producer_kind==2){last_time=Layout::live_unset_time;++writes;}return Result::ok;}
Result restorecontrol(void*,const Owner&o,const ControlState*in){assert(o.producer==&producer&&in->first==30&&in->second==20&&in->kind==producer_kind&&(producer_kind==2||in->random_seed==44));last_time=in->first;system_time=in->second;++writes;return Result::ok;}
Api api(){return {current,held,granted,inventory,controlled,reset_ready,type,alive,retain,retained,release,view,createbox,getplay,setplay,getdata,setdata,count,paused,playing,stopped,emitting,seed,setseed,automatic,setauto,allocate,gettrails,settrails,customget,customset,pause,stop,control_current,readcontrol,resetcontrol,restorecontrol};}
bool source(void*,void*c,void*p,void*cam){return c==&controller&&(p==nullptr||p==&pass)&&cam==&camera;}
void* pass_controller(void*){return passController;}void* props(void*){return passBlock;}
float time(void*){return sourceTime;}float sp(void*){return speed;}float getfloat(void*,int id,Method*){assert(id==99);++getfloats;return property;}
void setfloat(void*,int id,float f,Method*){assert(id==99);++sets;property=f;}
float savedTime=0,savedSpeed=0;int statecaptures=0,staterestores=0,statereleases=0;
Result capstate(void*,void*c){assert(c==&controller&&context.held);savedTime=sourceTime;savedSpeed=speed;++statecaptures;return Result::ok;}
Result reststate(void*,void*c){assert(c==&controller&&context.held&&context.current);sourceTime=savedTime;speed=savedSpeed;++staterestores;return Result::ok;}
void freestate(void*){++statereleases;}
PsylliumApi psyapi(){return {current,held,granted,source,type,alive,retain,retained,release,pass_controller,props,time,sp,getfloat,setfloat,capstate,reststate,freestate};}
void commit(ParticleScope&s,uint64_t tick){context.held=true;assert(s.prepare_step(tick,tick/60.)==Result::ok);context.tick=tick;context.granted=true;context.held=false;assert(s.commit_step(tick)==Result::ok);context.held=true;}
}

int main(){full_setup();auto*old=particle;particle=&actual_scope_admission::ps;regions.push_back({reinterpret_cast<uintptr_t>(particle),sizeof(actual_scope_admission::ps)});full_reset();assert(mp4_particle_native_capture()==Mp4SceneResult::ok);assert(mp4_particle_native_early_current());
 namespace s=actual_scope_admission;actual_stage_scope::ParticleScope scope;s::ps.particles.resize(2);actual_stage_scope::Owner owners[]={{particle,&s::producer,1}};assert(scope.configure(s::api(),owners,1,&s::context,7)==actual_stage_scope::Result::ok);assert(scope.capture()==actual_stage_scope::Result::ok);assert(scope.prepare()==actual_stage_scope::Result::ok);assert(scope.begin_zero_evaluation()==actual_stage_scope::Result::ok);unsigned cases=0;
 {Mp4ParticleOperationWriter writer(Mp4ParticleOperationWriterRole::particle_simulate);assert(scope.allow_simulate(particle,0.f,false,true,false));++cases;assert(writer.original_begin());uint64_t watch=0;assert(!mp4_particle_operation_read_begin(&watch));++cases;assert(writer.original_returned());assert(scope.allow_simulate(particle,0.f,false,true,false));++cases;}
 {Mp4ParticleOperationWriter live(Mp4ParticleOperationWriterRole::live_particle_simulate);assert(live.original_begin());{Mp4ParticleOperationWriter child(Mp4ParticleOperationWriterRole::particle_simulate);assert(scope.allow_simulate(particle,0.f,false,true,false));++cases;assert(child.original_begin()&&child.original_returned());}assert(live.original_returned());}
 {Mp4ParticleOperationWriter ambient;assert(!scope.allow_simulate(particle,0.f,false,true,false));++cases;}
 {Mp4ParticleOperationRead read;assert(read);{Mp4ParticleOperationWriter reentry(Mp4ParticleOperationWriterRole::particle_simulate);assert(!read&&!scope.allow_simulate(particle,0.f,false,true,false)&&!reentry.original_begin());++cases;}}
 assert(scope.release(false)==actual_stage_scope::Result::ok);for(auto*l:s::allocated)delete l;for(auto*b:s::boxes)delete b;assert(s::roots.empty());assert(mp4_particle_native_release(false)==Mp4SceneResult::ok);if(mp4_particle_source_renderer_type)weak_free(mp4_particle_source_renderer_type);::free(mp4_particle_source_policies);::free(mp4_particle_source_programs);delete static_cast<Material*>(source_material);particle=old;assert(roots.empty()&&private_materials.empty()&&private_blocks.empty());std::printf("%u composed actual ParticleScope/native coordinator/typed writer admission cases passed\n",cases);}
