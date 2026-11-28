// Explicit unit model of actual shared Scope, no Unity/device/GPU claim.
#include "mp4_engine_clock.hpp"
#include "pending-journal.hpp"
#include "birth-scope.hpp"
#include "source-origin.hpp"
#include "child-scope.hpp"
#include "original-call-host.hpp"
#include <cassert>
#include <vector>
#include <cstdlib>
#include <cmath>
using namespace mp4_child_source;
struct Host {
 Scope scope;birth::SourceTuple owners[3]{};Graph graphs[3]{};bool valid[256]{},known[256]{};
 double speeds[256]{},source_speeds[3]{0.75,-2,0};unsigned speed_sets[256]{};int root_wait=0,parent_state_wait=0;bool bad_root=false,wait_after_speed_set=false;
 double times[3]{10,3,4};int32_t modes[3]{1,0,2},states[3]{1,0,1};bool tuple_good[3]{true,true,true};
 bool current=true,held=true,dependencies=true,timing=true,cycle=false,source_loss_after_set=false,bad_receipt=false,bad_fresh=false,issued_wait=false;dm::Kind wait_kind=dm::Kind::rebuild;
 int pre_wait=0,confirm_wait=0,physical_wait=0;Result dependency_status=Result::ok;unsigned raw_rebuild[3]{},raw_eval[3]{},sets[3]{},mode_sets[3]{},state_sets[3]{};
 unsigned get_queries=0;uintptr_t next=10;uint64_t serial=0;std::vector<unsigned>evaluate_order,rebuild_order;
 static Host*active;
 Host(){active=this;for(size_t i=0;i<3;++i){owners[i]={100+i,200+i,300+i,400+i,500+i,7,20};graphs[i]={i+1,20,0};valid[i+1]=known[i+1]=true;speeds[i+1]=source_speeds[i];}assert(scope.configure(api()));}
 static size_t ix(void*d){assert(reinterpret_cast<uintptr_t>(d)>=100&&reinterpret_cast<uintptr_t>(d)<103);return reinterpret_cast<uintptr_t>(d)-100;}
 Api api(){Api a{};a.context=this;
  a.current=[](void*p,uint64_t e,uintptr_t r){return static_cast<Host*>(p)->current&&e==7&&r==0xabc;};a.held=[](void*p){return static_cast<Host*>(p)->held;};
  a.catalogue=[](void*p,birth::SourceTuple*out,size_t cap,size_t*n,uintptr_t*m){if(cap<3)return false;auto&h=*static_cast<Host*>(p);for(size_t i=0;i<3;++i)out[i]=h.owners[i];*n=3;*m=100;return true;};
  a.dependencies=[](void*p,const birth::SourceTuple*,size_t,Edge*out,size_t,size_t*n,uint64_t*r){auto&h=*static_cast<Host*>(p);out[0]={0,1,40};out[1]={1,2,41};out[2]={uint16_t(h.cycle?2:1),uint16_t(h.cycle?1:2),42};*n=3;*r=43;return h.dependencies;};
  a.dependencies_current=[](void*p,const Edge*,size_t,uint64_t){return static_cast<Host*>(p)->dependency_status;};
  a.export_timing=[](void*p,const State&,bool,uint64_t){return static_cast<Host*>(p)->timing?Result::ok:Result::unsupported;}; // Explicit unit source-role service.
  a.tuple_current=[](void*p,const birth::SourceTuple&t){auto&h=*static_cast<Host*>(p);return h.current&&t.director>=100&&t.director<103&&h.tuple_good[t.director-100];};
  a.graph=[](void*d,Graph*out,const void*){++active->get_queries;*out=active->graphs[ix(d)];};a.graph_valid=[](const Graph*g,const void*){return g->handle<256&&active->valid[g->handle];};
  a.root_map=[](void*p,const State&,Graph g,birth::Playable*out){auto&h=*static_cast<Host*>(p);if(h.root_wait){--h.root_wait;return Result::waiting;}if(g.handle>=256||!h.valid[g.handle]||!h.known[g.handle])return Result::stale;*out={g.handle+(h.bad_root?1024:512),g.version,0};return Result::ok;};
  a.root_speed=[](const birth::Playable*r,const void*){assert(r->handle>=512&&r->handle<768);auto g=r->handle-512;assert(active->valid[g]);return active->speeds[g];};
  a.set_root_speed=[](const birth::Playable*r,double v,const void*){assert(r->handle>=512&&r->handle<768);auto g=r->handle-512;assert(active->valid[g]);++active->speed_sets[g];active->speeds[g]=v;if(active->wait_after_speed_set){active->wait_after_speed_set=false;active->root_wait=1;}};
  a.time=[](void*d,const void*){++active->get_queries;return active->times[ix(d)];};a.mode=[](void*d,const void*){++active->get_queries;return active->modes[ix(d)];};a.state=[](void*d,const void*){++active->get_queries;return active->states[ix(d)];};
  a.set_time=[](void*d,double v,const void*){auto i=ix(d);++active->sets[i];active->times[i]=v;if(active->source_loss_after_set)active->current=false;};
  a.set_mode=[](void*d,int32_t v,const void*){auto i=ix(d);++active->mode_sets[i];active->modes[i]=v;};
  a.pause=[](void*d,const void*){auto i=ix(d);++active->state_sets[i];active->states[i]=0;};a.resume=[](void*d,const void*){auto i=ix(d);++active->state_sets[i];active->states[i]=1;};
  a.bindings_current=[](void*){return true;}; // Unit service fixture only.
  a.preflight=[](void*p,Round,dm::Kind,const State&,Graph){auto&h=*static_cast<Host*>(p);if(h.pre_wait){--h.pre_wait;return Result::waiting;}return Result::ok;};
  a.lineage=[](void*p,const State&,Graph g){auto&h=*static_cast<Host*>(p);return g.handle<256&&h.known[g.handle]?Result::ok:Result::stale;};
  a.invoke=[](void*p,dm::Kind k,const State&s,Mutation*out){auto&h=*static_cast<Host*>(p);auto i=s.owner.director-100;*out={{k,7,++h.serial,0xabc,s.owner.director,0x777,h.serial+100},true,true};if(h.bad_receipt)out->call.receiver=999;
   if(k==dm::Kind::rebuild){assert(h.modes[i]==3&&h.states[i]==0);++h.raw_rebuild[i];h.rebuild_order.push_back(unsigned(i));if(!h.bad_fresh){h.valid[h.graphs[i].handle]=false;h.graphs[i]={++h.next,20,0};h.valid[h.next]=h.known[h.next]=true;h.speeds[h.next]=1;}}
   else if(k==dm::Kind::saved_evaluate||k==dm::Kind::zero_evaluate){++h.raw_eval[i];h.evaluate_order.push_back(unsigned(i));if(i==1){h.times[2]=999;h.speeds[h.graphs[2].handle]=42;}}
   else if(k==dm::Kind::play||k==dm::Kind::stop){++h.state_sets[i];h.states[i]=k==dm::Kind::play?1:0;}
   if(h.issued_wait&&k==h.wait_kind){h.issued_wait=false;return Result::waiting;}return Result::ok;};
  a.confirm=[](void*p,dm::Kind,const State&,const Mutation&,Graph,Graph){auto&h=*static_cast<Host*>(p);if(h.confirm_wait){--h.confirm_wait;return Result::waiting;}return Result::ok;};
  a.parent_ready=[](void*,Round){return Result::ok;};a.parent_saved_checkpoint=[](void*){return Result::ok;};
  a.parent_state_checkpoint=[](void*p){auto&h=*static_cast<Host*>(p);if(h.parent_state_wait){--h.parent_state_wait;return Result::waiting;}return Result::ok;};
  a.physical_checkpoint=[](void*p){auto&h=*static_cast<Host*>(p);if(h.physical_wait){--h.physical_wait;return Result::waiting;}return Result::ok;};return a;
 }
 bool capture(){return scope.capture(7,0xabc)==Result::ok;}
 bool rebuild(Round r){return scope.rebuild_children(r)==Result::ok;}
 bool restore(){return scope.restore_children()==Result::ok&&scope.restore_root_speeds()==Result::ok;}
};Host*Host::active=nullptr;
int main(int argc,char**argv){assert(argc==2);int mode=std::atoi(argv[1]);Host h;
 if(mode==0){assert(h.capture());assert(h.scope.source(0)->state==1&&h.scope.source(1)->time==3);h.states[0]=0;assert(h.rebuild(Round::exporting)&&h.rebuild(Round::restoring)&&h.restore()&&h.scope.checkpoint());assert((h.rebuild_order==std::vector<unsigned>{2,1,2,1})&&(h.evaluate_order==std::vector<unsigned>{1,2}));assert(h.times[1]==3&&h.times[2]==4&&!h.raw_rebuild[0]&&!h.raw_eval[0]&&h.states[0]==0);return 0;}
 if(mode==1){h.dependencies=false;assert(!h.capture()&&!h.raw_rebuild[1]);return 0;}
 if(mode==2){h.cycle=true;assert(!h.capture()&&!h.raw_rebuild[1]);return 0;}
 if(mode==3){h.held=false;assert(h.scope.capture(7,0xabc)==Result::waiting);return 0;}
 if(mode==4){h.modes[1]=4;assert(!h.capture());return 0;}
 if(mode==5){h.times[1]=NAN;assert(!h.capture());return 0;}
 if(mode==6){h.valid[2]=false;assert(!h.capture());return 0;}
 if(mode==7){assert(h.capture());h.pre_wait=1;assert(h.scope.rebuild_children(Round::exporting)==Result::waiting&&!h.raw_rebuild[2]);assert(h.rebuild(Round::exporting)&&h.raw_rebuild[2]==1);return 0;}
 if(mode==8){assert(h.capture());h.issued_wait=true;assert(h.scope.rebuild_children(Round::exporting)==Result::waiting&&h.raw_rebuild[2]==1);assert(h.rebuild(Round::exporting)&&h.raw_rebuild[2]==1);return 0;}
 if(mode==9){assert(h.capture());h.confirm_wait=2;assert(!h.rebuild(Round::exporting)&&!h.rebuild(Round::exporting)&&h.rebuild(Round::exporting)&&h.raw_rebuild[2]==1);return 0;}
 if(mode==10){assert(h.capture());h.bad_receipt=true;assert(!h.rebuild(Round::exporting)&&!h.scope.checkpoint());return 0;}
 if(mode==11){assert(h.capture());h.bad_fresh=true;assert(!h.rebuild(Round::exporting)&&!h.scope.checkpoint());return 0;}
 if(mode==12){assert(h.capture());h.known[3]=false;assert(!h.rebuild(Round::exporting)&&!h.raw_rebuild[2]);return 0;}
 if(mode==13){assert(h.capture()&&h.rebuild(Round::restoring));h.physical_wait=2;assert(!h.restore()&&!h.restore()&&h.restore());for(unsigned i=1;i<3;++i)assert(h.raw_eval[i]==1&&h.sets[i]==1&&h.mode_sets[i]==2&&h.state_sets[i]==3);return 0;}
 if(mode==14){assert(h.capture()&&h.rebuild(Round::restoring));h.source_loss_after_set=true;assert(!h.restore()&&!h.raw_eval[1]);return 0;}
 if(mode==15){assert(h.capture());assert(h.scope.restore_children()==Result::invalid);return 0;}
 if(mode==16){assert(h.capture()&&h.rebuild(Round::restoring));h.tuple_good[1]=false;assert(!h.restore()&&!h.raw_eval[1]);return 0;}
 if(mode==17){assert(h.capture()&&h.rebuild(Round::exporting));h.tuple_good[1]=false;assert(!h.rebuild(Round::exporting));return 0;}
 if(mode==19){assert(h.capture()&&h.rebuild(Round::restoring)&&h.restore());Checkpoint c{};assert(h.scope.director_checkpoint(101,c)&&c.epoch==7&&c.root_asset==0xabc&&c.time==3&&c.saved_evaluate.receiver==101);assert(!h.scope.director_checkpoint(100,c));h.times[1]=99;assert(!h.scope.director_checkpoint(101,c));return 0;}
 if(mode==20){assert(h.capture()&&h.rebuild(Round::restoring)&&h.restore());Checkpoint c{};h.valid[h.graphs[1].handle]=false;assert(!h.scope.director_checkpoint(101,c));return 0;}
 if(mode==21){h.timing=false;assert(!h.capture()&&!h.raw_rebuild[1]);return 0;}
 if(mode==22){assert(h.capture()&&h.rebuild(Round::restoring)&&h.restore());h.times[1]=88;assert(h.scope.verify_checkpoint()==Result::failed&&h.scope.restore_children()==Result::failed);return 0;}
 if(mode==23){assert(h.capture());assert(h.scope.rebuild_children(static_cast<Round>(255))==Result::invalid&&!h.raw_rebuild[1]);return 0;}
 if(mode==24){assert(h.capture());h.dependency_status=Result::stale;assert(h.scope.rebuild_children(Round::exporting)==Result::stale&&!h.raw_rebuild[1]);return 0;}
 if(mode==25){assert(h.capture());h.dependency_status=Result::waiting;assert(h.scope.rebuild_children(Round::exporting)==Result::waiting&&!h.raw_rebuild[1]);return 0;}
 if(mode==26){h.speeds[2]=NAN;assert(!h.capture()&&!h.raw_rebuild[1]);return 0;}
 if(mode==27){assert(h.capture()&&h.rebuild(Round::restoring));assert(h.scope.restore_children()==Result::ok&&h.scope.child_fields_restored()&&!h.scope.checkpoint());Checkpoint c{};assert(h.scope.director_fields_checkpoint(101,c)&&!c.speed_restored&&!h.scope.director_checkpoint(101,c));h.speeds[h.graphs[0].handle]=14;assert(h.scope.restore_root_speeds()==Result::ok&&h.scope.checkpoint());for(size_t i=0;i<3;++i)assert(h.speeds[h.graphs[i].handle]==h.source_speeds[i]);assert(h.scope.director_checkpoint(101,c)&&c.speed_restored&&c.root_speed==-2);return 0;}
 if(mode==28){assert(h.capture()&&h.rebuild(Round::restoring)&&h.scope.restore_children()==Result::ok);h.parent_state_wait=1;assert(h.scope.restore_root_speeds()==Result::waiting);for(size_t i=0;i<256;++i)assert(h.speed_sets[i]==0);assert(h.scope.restore_root_speeds()==Result::ok);return 0;}
 if(mode==29){assert(h.capture()&&h.rebuild(Round::restoring)&&h.restore());h.speeds[h.graphs[2].handle]=1;assert(h.scope.verify_checkpoint()==Result::failed&&h.scope.restore_root_speeds()==Result::stale);return 0;}
 if(mode==30){assert(h.capture()&&h.rebuild(Round::restoring)&&h.scope.restore_children()==Result::ok);h.root_wait=1;assert(h.scope.restore_root_speeds()==Result::waiting&&h.speed_sets[h.graphs[0].handle]==0);assert(h.scope.restore_root_speeds()==Result::ok);for(size_t i=0;i<3;++i)assert(h.speed_sets[h.graphs[i].handle]==1);return 0;}
 if(mode==31){assert(h.capture()&&h.rebuild(Round::restoring)&&h.restore());for(size_t i=0;i<3;++i)assert(h.speed_sets[h.graphs[i].handle]==1);assert(h.scope.restore_root_speeds()==Result::ok);for(size_t i=0;i<3;++i)assert(h.speed_sets[h.graphs[i].handle]==1);return 0;}
 if(mode==32){assert(h.capture()&&h.rebuild(Round::restoring));assert(h.scope.restore_root_speeds()==Result::invalid);return 0;}
 if(mode==33){assert(h.capture()&&h.rebuild(Round::restoring)&&h.restore());Checkpoint c{};assert(h.scope.director_checkpoint(101,c));h.graphs[1]={++h.next,20,0};h.valid[h.next]=h.known[h.next]=true;assert(!h.scope.director_checkpoint(101,c)&&h.scope.verify_checkpoint()==Result::failed);return 0;}
 if(mode==34){assert(h.capture()&&h.rebuild(Round::restoring)&&h.scope.restore_children()==Result::ok);h.wait_after_speed_set=true;assert(h.scope.restore_root_speeds()==Result::waiting&&h.speed_sets[h.graphs[0].handle]==1);assert(h.scope.restore_root_speeds()==Result::ok);for(size_t i=0;i<3;++i)assert(h.speed_sets[h.graphs[i].handle]==1);return 0;}
 if(mode==35){assert(h.capture());h.issued_wait=true;h.wait_kind=dm::Kind::stop;assert(h.scope.rebuild_children(Round::exporting)==Result::waiting&&h.state_sets[2]==1&&!h.raw_rebuild[2]&&!h.mode_sets[2]);assert(h.rebuild(Round::exporting)&&h.state_sets[2]==1&&h.raw_rebuild[2]==1&&h.mode_sets[2]==1);return 0;}
 if(mode==36){assert(h.capture());h.confirm_wait=1;assert(h.scope.rebuild_children(Round::exporting)==Result::waiting&&h.state_sets[2]==1&&!h.mode_sets[2]);assert(h.rebuild(Round::exporting)&&h.state_sets[2]==1&&h.mode_sets[2]==1);return 0;}
 if(mode==37){assert(h.capture()&&h.rebuild(Round::exporting));assert(h.modes[1]==3&&h.modes[2]==3&&h.states[1]==0&&h.states[2]==0);assert(h.rebuild(Round::exporting));assert(h.mode_sets[1]==1&&h.mode_sets[2]==1&&h.state_sets[1]==1&&h.state_sets[2]==1);return 0;}
 if(mode==38){assert(h.capture()&&h.rebuild(Round::exporting)&&h.rebuild(Round::restoring)&&h.restore());assert(h.modes[1]==0&&h.modes[2]==2&&h.states[1]==0&&h.states[2]==1);assert(h.mode_sets[1]==3&&h.mode_sets[2]==3);return 0;}
 if(mode==18){assert(h.capture());auto n=h.get_queries;h.current=false;h.scope.release();assert(!h.scope.captured()&&h.get_queries==n);return 0;}
 return 2;
}
