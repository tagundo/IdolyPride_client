#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <cassert>
#include <vector>
#include "mp4_engine_clock.hpp"
#include "pending-journal.hpp"
#include "birth-scope.hpp"
#include "source-origin.hpp"
#include "child-scope.hpp"
#include "director-node-scope.hpp"
#include "driving-scope.hpp"
namespace drive=mp4_child_driving;namespace dn=idoly_mp4_director_nodes;namespace child=mp4_child_source;namespace dm=mp4_director_maintenance;using R=drive::Result;using E=drive::Event;using D=drive::Dispatch;
struct Model {
 bool source=true,held=true,bindings=true,node_current=true,origin=false,closed=true,live_active=true,issued=true,revoked_unconsumed=false;unsigned count=1;uint64_t complete=1;int mode=0;
 drive::Role role{};drive::Stamp stamp{};
 Model(){auto&n=role.node;n.key.director=(void*)0x10;n.key.asset=(void*)0x20;n.key.track=(void*)0x30;n.key.clip=(void*)0x40;n.key.control_asset=(void*)0x50;n.key.target=(void*)0x60;n.key.length=1;n.key.path[0]=1;n.script=(void*)0x70;n.graph={0x80,2,0};n.runtime={0x90,2,0};n.node={0xa0,2,0};n.factory=5;role.source_capture=7;role.active=true;
 stamp.call={dm::Kind::native_phase,9,11,0x99,0x10,0x110,12};stamp.frame=true;}
 dn::Node live(){auto n=role.node;n.script=(void*)0x170;n.graph={0x180,4,0};n.runtime={0x190,4,0};n.node={0x1a0,4,0};n.factory=6;n.birth=7;return n;}
 drive::Api api(){drive::Api a{};a.context=this;a.current=[](void*p,uint64_t e,uintptr_t r){return ((Model*)p)->source&&e==9&&r==0x99;};a.held=[](void*p){return ((Model*)p)->held;};a.bindings=[](void*p){return ((Model*)p)->bindings;};a.node_current=[](void*p,const dn::Node&){return ((Model*)p)->node_current;};
 a.source_roles=[](void*p,drive::Emit emit,void*c,uint64_t*r){auto&m=*(Model*)p;*r=m.complete;for(unsigned i=0;i<m.count;++i)if(!emit(c,m.role))return R::unsupported;return R::ok;};
 a.live_roles=[](void*p,drive::Emit emit,void*c,uint64_t*r){auto&m=*(Model*)p;*r=m.complete;if(m.mode==46)return R::ok;drive::Role live{m.live(),8,m.live_active};if(m.mode==29)live.node.key.clip=(void*)0x444;if(m.mode==30)return R::ok;return emit(c,live)?R::ok:R::unsupported;};
 a.edge=[](void*,const drive::Role&,const child::State&,uint64_t r){return r==10;};a.origin=[](void*p,drive::Stamp*out){auto&m=*(Model*)p;if(!m.origin)return false;*out=m.stamp;return true;};a.frame_closed=[](void*p,uint64_t e,uint64_t t){auto&m=*(Model*)p;return m.closed&&e==9&&t==m.stamp.tick;};a.frame_issued_current=[](void*p,uint64_t e,uint64_t t){auto&m=*(Model*)p;return m.issued&&e==9&&t==m.stamp.tick;};a.frame_revoked_unconsumed=[](void*p,uint64_t e,uint64_t t){auto&m=*(Model*)p;return m.revoked_unconsumed&&e==9&&t==m.stamp.tick;};a.nested_origin=[](void*,E parent,E nested,uintptr_t caller,uintptr_t saved){return parent==E::prepare&&nested==E::sync_start?saved&&caller==saved:parent==E::process&&nested==E::update_time?caller==0x501:parent==E::process&&nested==E::sync_stop?caller==0x502:false;};a.target_time=[](void*,void*){return 1.25;};return a;}
};
int main(int argc,char**argv){assert(argc==2);const int mode=atoi(argv[1]);Model m;m.mode=mode;drive::Scope s;struct Cleanup{drive::Scope&s;~Cleanup(){assert(s.release()==R::ok);}}cleanup{s};assert(s.configure(m.api()));
 if(mode==1)m.role.node.factory=0;if(mode==2)m.role.node.birth=1;if(mode==3)m.count=2;if(mode==4)m.role.source_capture=0;if(mode==5)m.complete=0;if(mode==6)m.node_current=false;if(mode==7)m.bindings=false;
 if(mode==46)m.count=0;
 const auto captured=s.capture(9,0x99);if(mode>=1&&mode<=7){assert(captured!=R::ok);assert(s.release()==R::ok);return 0;}assert(captured==R::ok);
 if(mode>=50&&mode<=53){assert(s.begin_frame(0)==R::ok);assert(s.mark_frame_issued(0)==R::ok);assert(s.discard_issued_unconsumed(0)==R::invalid);m.revoked_unconsumed=true;
  if(mode==51){m.held=false;assert(s.discard_issued_unconsumed(0)==R::invalid);m.held=true;}
  if(mode==52){m.origin=true;m.held=false;drive::Ticket t{};assert(s.enter(E::process,m.live(),&t)==D::owned&&s.invoked(t)&&s.returned(t));m.origin=false;m.held=true;assert(s.discard_issued_unconsumed(0)==R::invalid);return 0;}
  if(mode==53)assert(s.discard_issued_unconsumed(1)==R::invalid);
  assert(s.discard_issued_unconsumed(0)==R::ok);assert(s.begin_frame(0)==R::ok);assert(s.mark_frame_issued(0)==R::ok);return 0;}
 if(mode==48||mode==49){assert(s.begin_frame(0)==R::ok);m.origin=true;m.stamp.frame=false;m.stamp.call.kind=dm::Kind::saved_evaluate;drive::Ticket t{};assert(s.enter(E::process,m.live(),&t)==D::owned&&s.invoked(t)&&s.returned(t));m.stamp.frame=true;m.stamp.call.kind=dm::Kind::native_phase;assert(s.enter(E::process,m.live(),&t)==D::reject);assert(s.finish_frame(0)==R::waiting);m.issued=false;assert(s.mark_frame_issued(0)==R::invalid);assert(s.discard_prepared_frame(0)==R::ok);assert(s.begin_frame(0)==R::ok);m.issued=true;assert(s.mark_frame_issued(0)==R::ok);assert(s.discard_prepared_frame(0)==R::invalid);assert(s.enter(E::process,m.live(),&t)==D::owned&&s.invoked(t)&&s.returned(t));m.origin=false;m.held=true;assert(s.finish_frame(0)==R::ok);return 0;}
 if(mode==46){assert(s.begin_frame(0)==R::ok);assert(s.mark_frame_issued(0)==R::ok);assert(s.finish_frame(0)==R::ok);return 0;}
 if(mode==47){assert(s.begin_frame(0)==R::ok);assert(s.mark_frame_issued(0)==R::ok);assert(s.finish_frame(0)==R::unsupported&&s.failed());return 0;}
 child::State state{};state.owner.director=0x60;state.owner.epoch=9;state.root_asset=0x99;state.mode=1;state.time=1.0;assert(s.timing(state,true,10)==R::ok);state.mode=3;assert(s.timing(state,true,10)==R::ok);assert(s.timing(state,false,10)==R::stale);
 if(mode==8){assert(s.release()==R::ok);m.role.active=false;assert(s.capture(9,0x99)==R::ok);state.mode=1;assert(s.timing(state,true,10)==R::unsupported);state.mode=3;assert(s.timing(state,true,10)==R::ok);return 0;}
 if(mode==35||mode==36){m.stamp.frame=false;m.stamp.call.kind=mode==35?dm::Kind::saved_evaluate:dm::Kind::maintenance;m.origin=true;drive::Ticket t{};assert(s.enter(E::process,m.live(),&t)==D::owned);assert(s.invoked(t)&&s.returned(t));assert(s.release()==R::ok);return 0;}
 assert(s.begin_frame(0)==R::ok);assert(s.mark_frame_issued(0)==R::ok);if(mode==9){assert(s.begin_frame(0)==R::invalid);return 0;}
 m.held=false;m.origin=true;if(mode==10)m.origin=false;if(mode==11)m.stamp.call.kind=dm::Kind::play;if(mode==12)++m.stamp.tick;if(mode==13)m.stamp.phase=8;
 auto node=m.live();
 if(mode==44){drive::Ticket prep{},sync{};assert(s.enter(E::prepare,node,&prep)==D::owned&&s.invoked(prep));assert(!s.record_original_return((void*)0xdead,0x601));assert(s.record_original_return(node.script,0x601));assert(!s.record_original_return(node.script,0x601));assert(s.enter_nested(E::sync_start,node.script,node.graph,true,0,0x602,&sync)==D::reject);assert(s.enter_nested(E::sync_start,node.script,node.graph,true,0,0x601,&sync)==D::owned&&s.invoked(sync)&&s.returned(sync));assert(s.returned(prep));}
 if(mode==14)node.key.target=(void*)0x666;drive::Ticket t{};const auto dispatch=s.enter(E::process,node,&t);
 if(mode>=10&&mode<=14){assert(dispatch==D::reject);s.abandon(t);assert(s.failed());assert(s.release()==R::ok);return 0;}assert(dispatch==D::owned);
 if(mode==15){assert(!s.returned(t));s.abandon(t);assert(s.release()==R::ok);return 0;}
 if(mode==16){auto wrong=t;++wrong.serial;assert(!s.invoked(wrong));assert(s.release()==R::waiting);s.abandon(t);assert(s.release()==R::ok);return 0;}
 assert(s.invoked(t));assert(!s.invoked(t));drive::Ticket nested{};
 if(mode==43){assert(s.enter_nested(E::sync_stop,node.script,node.graph,true,1.0,0x502,&nested)==D::owned&&s.invoked(nested)&&s.returned(nested));}
 if(mode==45){assert(s.enter_nested(E::update_time,node.script,node.node,false,0,0x500,&nested)==D::reject);s.abandon(t);assert(s.release()==R::ok);return 0;}
 if(mode>=17&&mode<=20){auto arg=node.node;void*script=node.script;bool graph=false;double time=0;
  if(mode==17)script=(void*)0x777;if(mode==18)++arg.handle;if(mode==19){graph=true;arg=node.graph;++arg.version;}if(mode==20){graph=true;arg=node.graph;time=__builtin_nan("");}
  assert(s.enter_nested(graph?E::sync_start:E::update_time,script,arg,graph,time,0x501,&nested)==D::reject);s.abandon(t);assert(s.release()==R::ok);return 0;}
 assert(s.enter_nested(E::update_time,node.script,node.node,false,0,0x501,&nested)==D::owned);assert(s.invoked(nested));
 if(mode==21){++m.stamp.call.serial;assert(!s.returned(nested));s.abandon(nested);s.abandon(t);assert(s.release()==R::ok);return 0;}
 assert(s.returned(nested));assert(!s.returned(nested));
 if(mode==22){m.node_current=false;assert(!s.returned(t));s.abandon(t);assert(s.release()==R::ok);return 0;}
 if(mode==23){m.source=false;assert(!s.returned(t));s.abandon(t);assert(s.release()==R::ok);return 0;}
 assert(s.returned(t));m.origin=false;m.held=true;
 if(mode==24){m.closed=false;assert(s.finish_frame(0)==R::waiting);m.closed=true;assert(s.finish_frame(0)==R::ok);return 0;}
 if(mode==25){assert(s.finish_frame(1)==R::waiting);assert(s.finish_frame(0)==R::ok);return 0;}
 if(mode==26)m.complete=0;
 const auto done=s.finish_frame(0);if(mode==26||mode==29||mode==30){assert(done!=R::ok&&s.failed());assert(s.release()==R::ok);return 0;}assert(done==R::ok);
 assert(s.begin_frame(1)==R::ok);m.stamp.tick=1;assert(s.mark_frame_issued(1)==R::ok);m.stamp.call.serial++;m.origin=true;m.held=false;m.live_active=false;
 if(mode!=27){assert(s.enter(E::pause,m.live(),&t)==D::owned);assert(s.invoked(t));if(mode==31){s.abandon(t);assert(s.finish_frame(1)==R::failed);assert(s.release()==R::ok);return 0;}assert(s.returned(t));}
 m.origin=false;m.held=true;const auto second=s.finish_frame(1);if(mode==27){assert(second==R::unsupported&&s.failed());return 0;}assert(second==R::ok);
 if(mode==28){assert(s.begin_frame(3)==R::invalid);assert(s.release()==R::ok);return 0;}
 if(mode==32){drive::Ticket no_parent{};assert(s.enter_nested(E::update_time,node.script,node.node,false,0,0x501,&no_parent)==D::reject);}
 if(mode==33){state.owner.director=0x777;state.mode=1;assert(s.timing(state,false,10)==R::unsupported);}
 if(mode==34){assert(s.begin_frame(2)==R::ok);m.stamp.tick=2;assert(s.mark_frame_issued(2)==R::ok);m.origin=true;m.held=false;assert(s.enter(E::process,m.live(),&t)==D::owned);assert(s.invoked(t)&&s.returned(t));m.origin=false;m.held=true;m.live_active=true;assert(s.finish_frame(2)==R::ok);}
 assert(s.release()==R::ok);
}
