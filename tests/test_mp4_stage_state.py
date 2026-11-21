"""Shipping stage-state protocol with typed synthetic engine callbacks.

These tests execute the C++ helper; they do not execute a game/GPU. Original
cohort regeneration and native fence instruction checks are tested separately.
"""
import json,os,shutil,subprocess,sys
import struct
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'client-presentation/native'
HARNESS=r'''
#include "mp4_stage_state.hpp"
#include <cassert>
#include <vector>
#include <map>
#include <string>
#include <cstring>
using namespace idoly_mp4_stage;
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
bool current(void*){++ownerchecks;return context.current;}bool held(void*){return context.held;}bool granted(void*,uint64_t n){return context.granted&&context.tick==n;}
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
int main(int argc,char**argv){struct Cleanup{~Cleanup(){for(auto*l:allocated)delete l;for(auto*b:boxes)delete b;}}cleanup;assert(argc==2);std::string mode=argv[1];
 if(mode.rfind("psy_",0)==0){PsylliumScope s;assert(s.configure(psyapi(),&context,&controller,&camera,99,4)==Result::ok);
  assert(s.capture()==Result::ok&&s.capture()==Result::ok&&statecaptures==1);
  assert(s.prepare_step(0,0.5)==Result::ok);
  if(mode=="psy_rejected_clock"){assert(s.commit_step(0)==Result::stale);PsylliumTicket t;assert(s.begin_psyllium(&pass,&camera,t)==Result::ok&&!t.changed&&sets==0);assert(s.hold()==Result::ok);assert(s.prepare_step(0,0.5)==Result::ok);}
  context.granted=true;context.tick=0;context.held=false;assert(s.commit_step(0)==Result::ok);
  if(mode=="psy_revoke_invalid_owner"){
   context.held=true;assert(s.prepare_step(1,1.5)==Result::ok);context.current=false;
   const int checked=ownerchecks;const auto rooted=roots.size();s.revoke_grants();
   assert(ownerchecks==checked&&roots.size()==rooted&&sets==0);context.current=true;
   assert(s.prepare_step(1,2.5)==Result::ok);s.revoke_grants();
  }
  if(mode=="psy_authored")sourceTime=2.f/3;
  if(mode=="psy_foreign_camera"){PsylliumTicket t;assert(s.begin_psyllium(&pass,&foreigncamera,t)==Result::ok&&!t.changed&&sets==0);}
  else if(mode=="psy_foreign_controller"){passController=nullptr;PsylliumTicket t;assert(s.begin_psyllium(&pass,&camera,t)==Result::stale&&sets==0);}
  else {PsylliumTicket t;assert(s.begin_psyllium(&pass,&camera,t)==Result::ok);
   if(mode=="psy_authored"){assert(!t.changed&&sets==0&&getfloats==0&&property==47);}
   else {assert(t.changed&&property==1&&sets==1);float captured=property;(void)captured;
    if(mode=="psy_busy_ticket")assert(s.begin_psyllium(&pass,&camera,t)==Result::invalid&&t.changed);
    if(mode=="psy_scene_loss")context.current=false;
    if(mode=="psy_block_replaced")passBlock=nullptr;
    auto r=s.end_psyllium(t);if(mode=="psy_scene_loss"||mode=="psy_block_replaced")assert(r==Result::stale&&sets==1);else assert(r==Result::ok&&property==47&&sets==2);
   }}
  context.held=true;
  if(context.current)assert(s.restore()==Result::ok&&s.restore()==Result::ok&&staterestores==1&&sourceTime==-1&&speed==2);
  else assert(s.restore()==Result::stale&&staterestores==0);
  s.release();assert(roots.empty()&&statereleases==1);return 0;
 }
 ParticleScope s;if(mode=="live_producer")producer_kind=2;Owner owners[]={{&ps,&producer,producer_kind}};ps.particles.resize(2);memset(static_cast<void*>(ps.particles.data()),43,2*sizeof(Particle));ps.state.bytes[0]=29;
 if(mode=="read_only_admit"){context.held=false;assert(admit_particles(api(),owners,1,&context)==Result::ok&&fences==0&&writes==0);return 0;}
 if(mode=="reject_uncontrolled"){context.controlled=false;assert(admit_particles(api(),owners,1,&context)==Result::unsupported&&fences==0);return 0;}
 if(mode=="empty_particles")ps.particles.clear();
 assert(s.configure(api(),owners,1,&context,7)==Result::ok);
 if(mode=="reject_playing"){ps.playing=true;ps.paused=false;assert(s.capture()==Result::unsupported&&writes==0);assert(s.release(false)==Result::ok&&roots.empty());return 0;}
 if(mode=="partial_capture"){badlist=true;assert(s.capture()==Result::unsupported);badlist=false;assert(s.capture()==Result::invalid);assert(s.release(false)==Result::ok&&roots.empty());return 0;}
 assert(s.capture()==Result::ok);assert(s.prepare()==Result::ok);assert(!s.allow_simulate(&ps)&&s.allow_simulate(&other));assert(!s.allow_simulate(&ps,0.1f,false,false,false));assert(s.allow_simulate(&other,0.1f,false,false,false));
 assert(s.begin_control_initialization(&ps)==Result::invalid);assert(s.begin_zero_evaluation()==Result::ok);assert(s.begin_zero_evaluation()==Result::invalid);assert(s.allow_simulate(&ps));
 if(mode=="control_initialization"||mode=="revoke_initialization_invalid_owner"){
  assert(s.begin_control_initialization(&other)==Result::unsupported);assert(s.begin_control_initialization(&ps)==Result::ok);assert(s.begin_control_initialization(&ps)==Result::invalid);
  assert(s.allow_simulate(&ps,2.f,false,true,false)&&s.allow_simulate(&ps,.1f,false,false,false));
  assert(!s.allow_simulate(&ps,2.f,true,true,false)&&!s.allow_simulate(&ps,2.f,false,true,true));
  assert(!s.allow_simulate(&ps,-1.f,false,true,false)&&!s.allow_simulate(&ps,901.f,false,true,false));
  if(mode=="revoke_initialization_invalid_owner"){
   context.current=false;const int checked=ownerchecks,beforefence=fences,beforewrites=writes;const auto rooted=roots.size();s.revoke_grants();
   assert(ownerchecks==checked&&fences==beforefence&&writes==beforewrites&&roots.size()==rooted);context.current=true;
   assert(!s.allow_simulate(&ps,0.f,false,true,false)&&!s.allow_simulate(&ps,2.f,false,true,false));assert(s.begin_control_initialization(&ps)==Result::invalid);
  }
  s.end_control_initialization(&ps);assert(!s.allow_simulate(&ps,2.f,false,true,false));
 }
 if(producer_kind==2){assert(last_time==-1&&system_time==20);assert(s.allow_producer(&producer,&ps,0));assert(!s.allow_producer(&producer,&ps,.1f));assert(!s.allow_producer(&producer,&other,0));assert(s.allow_producer(&controller,&other,.1f));last_time=system_time=0;assert(s.prepare()==Result::ok&&last_time==0);}
 s.end_zero_evaluation();assert(!s.allow_simulate(&ps));if(producer_kind==2)assert(!s.allow_producer(&producer,&ps,0));
 context.reset=false;assert(s.reset()==Result::waiting);context.reset=true;assert(s.reset()==Result::ok);assert(!s.allow_simulate(&ps));
 if(mode=="rejected_clock"){assert(s.prepare_step(0,0)==Result::ok);assert(s.commit_step(0)==Result::stale&&!s.allow_simulate(&ps));assert(s.quiesce()==Result::ok);}
 commit(s,0);assert(s.allow_simulate(&ps));assert(s.commit_step(0)==Result::stale);
 if(mode=="revoke_invalid_owner"){
  context.current=false;const int checked=ownerchecks,beforefence=fences,beforewrites=writes;const auto rooted=roots.size();s.revoke_grants();
  assert(ownerchecks==checked&&fences==beforefence&&writes==beforewrites&&roots.size()==rooted);context.current=true;assert(!s.allow_simulate(&ps));
 }
 assert(s.quiesce()==Result::ok&&!s.allow_simulate(&ps));commit(s,1);assert(s.quiesce()==Result::ok);
 if(producer_kind==2)assert(!s.allow_producer(&producer,&ps,0));
 if(mode=="stale_inventory")context.inventory=false;
 if(mode=="stale_producer")context.controlled=false;
 if(mode=="saved_list_tamper")allocated[0]->data[0]^=1;
 const int before=writes;
 if(mode=="stale_inventory"||mode=="stale_producer"||mode=="saved_list_tamper"){assert(s.restore()==Result::stale&&writes==before);assert(s.release(false)==Result::ok);}
 else {ps.state.bytes[0]=88;if(!ps.particles.empty())ps.particles[0].bytes[0]=99;ps.seed=100;assert(s.restore()==Result::ok);assert(ps.state.bytes[0]==29&&(mode=="empty_particles"?ps.particles.empty():ps.particles[0].bytes[0]==43)&&ps.seed==17&&ps.automatic);assert(s.release(true)==Result::ok);}
 assert(s.release(false)==Result::ok&&roots.empty());return 0;
}
'''
@pytest.fixture(scope='module')
def binary(tmp_path_factory):
 compiler=os.environ.get('CXX')or shutil.which('g++')or shutil.which('clang++')
 if not compiler:pytest.skip('C++ compiler required')
 d=tmp_path_factory.mktemp('stage');src=d/'stage.cpp';out=d/'stage';src.write_text(HARNESS)
 r=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(NATIVE),str(src),'-o',str(out)],capture_output=True,text=True,timeout=40)
 assert r.returncode==0,r.stdout+r.stderr
 return out
@pytest.mark.parametrize('mode',['read_only_admit','reject_uncontrolled','reject_playing','partial_capture','rejected_clock','normal','empty_particles','live_producer','control_initialization','revoke_initialization_invalid_owner','revoke_invalid_owner','stale_inventory','stale_producer','saved_list_tamper','psy_normal','psy_rejected_clock','psy_revoke_invalid_owner','psy_authored','psy_foreign_camera','psy_foreign_controller','psy_busy_ticket','psy_scene_loss','psy_block_replaced'])
def test_shipping_stage_scope(binary,mode):
 r=subprocess.run([str(binary),mode],capture_output=True,text=True,timeout=5)
 assert r.returncode==0,r.stdout+r.stderr

def test_profile_regeneration_from_both_originals(tmp_path):
 directory=os.environ.get('IDOLY_MP4_ORIGINALS_DIR')
 if not directory:pytest.skip('Pinned original cohorts required')
 h=tmp_path/'stage.hpp';h.write_bytes((NATIVE/'mp4_stage_state.hpp').read_bytes())
 r=subprocess.run([sys.executable,str(ROOT/'tools/audit_mp4_stage_state.py'),'--originals',directory,'--header',str(h),'--report',str(tmp_path/'proof.json')],capture_output=True,text=True,timeout=90)
 assert r.returncode==0,r.stdout+r.stderr
 assert h.read_bytes()==(NATIVE/'mp4_stage_state.hpp').read_bytes()
 proof=json.loads((tmp_path/'proof.json').read_text())
 for p in proof['platforms'].values():
  assert p['layouts']['playback']['bytes']==352 and p['layouts']['particle']['bytes']==132 and p['layouts']['context']['bytes']==8
  assert p['particle_fence']['requires_held_render_delta']==[0xa8,0xac]
  assert all(v['contains_pointers_or_managed_references']is False for v in p['pointer_free_values'].values())
  assert len(p['pointer_free_values']['UnityEngine.ParticleSystem/PlaybackState']['definitions'])>5
  assert set(p['draw_property_copy']['methods'])=={'draw','capture','clone','array0','array1','array2'}
  assert p['methods']['live_particle_simulate']['parameters'][1]['type']=='System.Single'
  assert p['producer_control']['live_unset_time']['value']==-1
  assert p['producer_control']['control_source_resolve']['name_offset']==0
  assert p['producer_control']['control_source_resolve']['default_offset']==8
  assert p['equipment_layouts']['vlb_property']['bytes']==256
  assert p['vlb_initialization']['clear_memory_enum']==1 and p['vlb_initialization']['structured_buffer_enum']==16
  assert p['vlb_config']['class_static_fields_offset']==184 and p['vlb_config']['static_instance_offset']==0
  assert p['fields']['vlb_config_scale']['offset']==64 and p['fields']['vlb_config_velocity']['offset']==68
  assert p['runtime_types']['VLB.VLBProperty']['metadata_type_definition_index']==p['pointer_free_values']['VLB.VLBProperty']['root_definition']
  assert p['methods']['vlb_compute_readback']['parameters'][0]['type']=='System.Array'
  assert [x['type']for x in p['methods']['vlb_compute_readback']['parameters'][1:]]==['System.Int32']*4
  assert p['fields']['vlb_render_camera']['offset']==144
  assert {x['name']for x in p['beam_spans']if x['identity']} >= {'_batchSRP','m_BeamGeom','m_CoPlaytimeUpdate','_CachedLight'}

@pytest.mark.parametrize('kind,byref',[(18,False),(15,False),(24,False),(12,True),(17,False)])
def test_pointer_free_proof_rejects_reference_pointer_byref_or_cycle(kind,byref):
 # Small malformed metadata fixture executes the same recursive verifier used
 # after the whole-original SHA checks. Size equality alone cannot admit it.
 sys.path.insert(0,str(ROOT/'tools'))
 try:
  from audit_mp4_stage_state import pointer_free_value
 finally:
  sys.path.pop(0)
 class Image:
  def __init__(self):
   self.m=struct.pack('<III',0,0,0);self.b=bytearray(0x280);self.h={24:0}
   row=[0]*24;row[8]=0;row[18]=1;self.types={0:('Fixture',row)}
   self.size_table=0x100;self.field_table=0x110;self.type_table=0x120
   for at,value in [(0x100,0x200),(0x110,0x220),(0x120,0x230)]:struct.pack_into('<Q',self.b,at,value)
   struct.pack_into('<4I',self.b,0x200,20,4,0,0);struct.pack_into('<i',self.b,0x220,16)
   struct.pack_into('<QI',self.b,0x230,0,(kind<<16)|((1<<29)if byref else 0))
  def type_id(self,_):return 0
  def string(self,_):return 'field'
  def offset(self,address):return address
  def qword(self,address):return struct.unpack_from('<Q',self.b,address)[0]
 with pytest.raises(ValueError,match='stage_(value_contains_pointer_or_reference|recursive_value_type)'):
  pointer_free_value(Image(),'Fixture')

EQUIPMENT_HARNESS=r'''
#include "mp4_stage_state.hpp"
#include <cassert>
#include <cstring>
#include <map>
#include <string>
using namespace idoly_mp4_stage;
struct Controller {unsigned char stream[232],initial[128],animation[192],timeline[8];} a,b,replacement;
struct Ctx {bool current=true,held=true,granted=false,mapped=true,capture_ok=true;uint64_t tick=0;} ctx;
bool replace_array=false;int owner_checks=0,fences=0,captures=0,restores=0,releases=0,target=42,saved_target=0;
std::map<uint32_t,void*> roots;uint32_t next_root=0;
bool owner(void*){++owner_checks;return ctx.current;}
bool held(void*){return ctx.held;}bool granted(void*,uint64_t n){return ctx.granted&&ctx.tick==n;}
bool controller_current(void*,void* p){return p==&a||p==&b;}
bool array_view(void*,void* p,EquipmentArray kind,EquipmentArrayView*out){
 auto*c=static_cast<Controller*>(p);if(replace_array&&p==&a)c=&replacement;
 void* rows[]={c->stream,c->initial,c->animation,c->timeline};*out={rows[static_cast<unsigned>(kind)],2,4};return true;
}
bool mapped(const void*,size_t,bool){return ctx.mapped;}
uint32_t retain(void*p){roots[++next_root]=p;return next_root;}void*retained(uint32_t h){auto it=roots.find(h);return it==roots.end()?nullptr:it->second;}void release(uint32_t h){assert(roots.erase(h)==1);}
Result admit(void*){return Result::ok;}Result fence(void*){assert(ctx.held);++fences;return Result::ok;}
Result capture(void*){++captures;saved_target=target;return ctx.capture_ok?Result::ok:Result::failed;}
bool targets_current(void*){return true;}
Result restore(void*){assert(ctx.held&&ctx.current);assert(a.stream[0]==42&&a.animation[0]==42&&a.timeline[0]==42);++restores;target=saved_target;return Result::ok;}
void free_targets(void*){++releases;}
EquipmentApi api(){return {owner,held,granted,controller_current,array_view,mapped,retain,retained,release,admit,fence,capture,targets_current,restore,free_targets};}
void commit(EquipmentScope&s,uint64_t tick){ctx.held=true;assert(s.prepare_step(tick,tick/60.)==Result::ok);ctx.tick=tick;ctx.granted=true;ctx.held=false;assert(s.commit_step(tick)==Result::ok);}
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];memset(&a,42,sizeof a);memset(&b,42,sizeof b);void* controllers[]={&a,&b};EquipmentScope s;
 if(mode=="unmapped")ctx.mapped=false;
 const auto configured=s.configure(api(),controllers,2,&ctx);
 if(mode=="unmapped"){assert(configured==Result::unsupported&&roots.empty());return 0;}
 assert(configured==Result::ok&&s.owns(&a)&&s.owns(&b)&&!s.owns(&replacement));
 assert(s.admit()==Result::ok&&fences==0&&captures==0&&target==42);
 if(mode=="partial_capture")ctx.capture_ok=false;
 const auto captured=s.capture();
 if(mode=="partial_capture"){assert(captured==Result::failed);assert(s.release(false)==Result::ok&&roots.empty()&&releases==1&&restores==0);return 0;}
 assert(captured==Result::ok&&s.capture()==Result::ok&&captures==1&&fences==1);
 assert(s.prepare()==Result::ok&&s.reset()==Result::ok&&s.begin_controller(&a)==Result::waiting);
 if(mode=="rejected_clock"){
  assert(s.prepare_step(0,0)==Result::ok&&s.commit_step(0)==Result::stale);
  assert(s.begin_controller(&a)==Result::waiting);s.revoke_grants();
 }
 commit(s,0);if(mode=="tick_zero_held")ctx.held=true;assert(s.begin_controller(&a)==Result::ok);assert(s.begin_controller(&b)==Result::invalid);
 if(mode=="original_exception"){
  assert(s.end_controller(&a,false)==Result::failed);ctx.held=true;
  assert(s.restore()==Result::stale&&restores==0);assert(s.release(false)==Result::ok&&roots.empty());return 0;
 }
 a.stream[0]=a.animation[0]=a.timeline[0]=99;target=99;assert(s.end_controller(&a,true)==Result::ok);
 assert(s.begin_controller(&a)==Result::waiting&&s.begin_controller(&b)==Result::ok&&s.end_controller(&b,true)==Result::ok);
 if(mode=="revoke_invalid_owner"){
  ctx.current=false;const int checked=owner_checks,before=fences;const auto rooted=roots.size();s.revoke_grants();
  assert(owner_checks==checked&&fences==before&&roots.size()==rooted);ctx.current=true;assert(s.begin_controller(&a)==Result::waiting);
 }
 ctx.held=true;assert(s.quiesce()==Result::ok);commit(s,1);assert(s.begin_controller(&a)==Result::ok&&s.end_controller(&a,true)==Result::ok);ctx.held=true;
 if(mode=="initial_changed")++a.initial[0];
 if(mode=="array_replaced")replace_array=true;
 if(mode=="owner_lost")ctx.current=false;
 if(mode=="initial_changed"||mode=="array_replaced"||mode=="owner_lost"){
  assert(s.restore()==Result::stale&&restores==0&&a.stream[0]==99&&target==99);assert(s.release(false)==Result::ok);
 }else{
  assert(s.restore()==Result::ok&&s.restore()==Result::ok&&restores==1&&target==42);
  assert(s.release(true)==Result::ok);
 }
 assert(s.release(false)==Result::ok&&roots.empty()&&releases==1);return 0;
}
'''

@pytest.fixture(scope='module')
def equipment_binary(tmp_path_factory):
 compiler=os.environ.get('CXX')or shutil.which('g++')or shutil.which('clang++')
 if not compiler:pytest.skip('C++ compiler required')
 d=tmp_path_factory.mktemp('equipment');src=d/'equipment.cpp';out=d/'equipment';src.write_text(EQUIPMENT_HARNESS)
 r=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(NATIVE),str(src),'-o',str(out)],capture_output=True,text=True,timeout=40)
 assert r.returncode==0,r.stdout+r.stderr
 return out

@pytest.mark.parametrize('mode',['normal','tick_zero_held','unmapped','partial_capture','rejected_clock','original_exception','revoke_invalid_owner','initial_changed','array_replaced','owner_lost'])
def test_shipping_equipment_scope(equipment_binary,mode):
 r=subprocess.run([str(equipment_binary),mode],capture_output=True,text=True,timeout=5)
 assert r.returncode==0,r.stdout+r.stderr
