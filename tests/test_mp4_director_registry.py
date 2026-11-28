"""Execute the shipping global DirectorManager classifier on bounded heaps.

The fixture supplies pure source-ledger and callback/state-owner queries. It
never equates known graph/type identity with whole scene or GPU restoration.
Exact original native dispatch/producer code is exercised by separate ARM tests.
"""
from pathlib import Path
import shutil,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include "mp4_engine_clock.hpp"
#include <cassert>
#include <cstdio>
#include <string>
#include <vector>
using namespace idoly_mp4_world;
alignas(16) unsigned char image[0x10000]{},manager[0x500]{},graphs[3][0xf8]{},slots[3][0x40]{},outputs[3][0xe0]{},animator[0x200]{},queue[16]{},nodes[3][32]{},dispatch[7][2][240]{},callback[7][120]{},values[7][24]{},deferred[2][48]{};
std::string mode;bool source=true,closed=true,owners[3]={true,false,false},changed=false;unsigned owner_calls=0,retired_calls=0;uint64_t epoch=17;DirectorRegistryProfile profile{};
struct Span{const void*p;size_t size;};std::vector<Span>spans;
template<class T>void put(void*p,size_t at,T value){memcpy(static_cast<unsigned char*>(p)+at,&value,sizeof value);}
uintptr_t addr(const void*p){return reinterpret_cast<uintptr_t>(p);}bool current(void*){return source;}uint64_t source_epoch(void*){return epoch;}
bool thread(){return mode!="wrong_thread";}bool ready(){return mode!="routes_missing";}
bool mapped(uintptr_t at,size_t count){if(mode=="unmapped")return false;for(const auto&s:spans){const uintptr_t b=addr(s.p);if(at>=b&&count<=s.size&&at-b<=s.size-count)return true;}return false;}
void link(bool active,std::initializer_list<unsigned>items){const uintptr_t sentinel=addr(manager)+(active?0x368:0x378);uintptr_t prior=sentinel;for(unsigned i:items){put(graphs[i],0,prior);put(reinterpret_cast<void*>(prior),8,addr(graphs[i]));prior=addr(graphs[i]);}put(reinterpret_cast<void*>(prior),8,sentinel);put(manager,active?0x368:0x378,prior);if(!items.size())put(manager,active?0x370:0x380,sentinel);}
void vector(void*p,size_t at,void*data,uint64_t count,uint64_t capacity){put(p,at,addr(data));put(p,at+16,count);put(p,at+24,capacity*2);}
DirectorGraphIdentity identity(unsigned i){uint32_t v=0;memcpy(&v,slots[i]+0x20,4);return {addr(graphs[i]),addr(slots[i]),v,1,2,4};}
void output(unsigned graph,unsigned out,unsigned family){const uintptr_t sentinel=addr(graphs[graph])+0x78,node=addr(outputs[out])+8;put(graphs[graph],0x78,node);put(graphs[graph],0x80,node);put(outputs[out],8,sentinel);put(outputs[out],16,sentinel);put(outputs[out],0,addr(image)+profile.outputs[family].vtable);}
void enqueue(unsigned n,unsigned graph,unsigned op,uint32_t version=20){put(nodes[n],8,addr(slots[graph]));put(nodes[n],16,version);put(nodes[n],24,op);uintptr_t old=0;memcpy(&old,queue,8);put(nodes[n],0,old);put(queue,0,addr(nodes[n]));}
void clean_dispatch(){put(manager,0x41d,uint8_t(0));put(manager,0x41e,uint8_t(0));vector(manager,0x90+2*32,dispatch[2][0],1,3);put(dispatch[2][0],72,addr(graphs[0]));vector(manager,0x250+2*32,callback[2],1,3);put(callback[2],0,addr(image)+profile.outputs[2].callbacks[0].rva);vector(callback[2],8,values[2],1,3);put(values[2],0,addr(outputs[0]));}
bool owner(void*,const DirectorGraphIdentity&id){++owner_calls;bool owned=false;for(unsigned i=0;i<3;++i)if(id.native==addr(graphs[i])&&id.slot==addr(slots[i])&&id.version==(i==0&&mode.rfind("retired",0)==0?22u:20u))owned=owners[i];
 if(!changed){changed=true;
  if(mode=="source_changed")source=false;
  if(mode=="epoch_changed")++epoch;
  if(mode=="queue_tag_changed")put(queue,8,uint64_t(9));
  if(mode=="queue_head_changed")enqueue(1,0,0);
  if(mode=="list_changed")put(manager,0x370,addr(graphs[1]));
  if(mode=="version_changed")put(slots[0],0x20,uint32_t(22));
  if(mode=="callback_changed")put(values[2],0,addr(outputs[1]));
 }
 return owned;
}
bool output_closed(void*,const DirectorGraphIdentity&,uintptr_t,uint32_t family){return mode!="payload_unowned"&&family==2;}
bool retired(void*,const DirectorGraphIdentity&id,DirectorRetiredGraph*out){++retired_calls;if(mode.rfind("retired",0)!=0)return false;*out={id.native,id.slot,0x123,20,17,99};if(mode=="retired_bad_receipt")out->receipt=0;if(mode=="retired_wrong_asset")out->source_asset=0;if(mode=="retired_wrong_epoch")out->epoch=18;if(mode=="retired_wrong_slot")out->slot=addr(slots[1]);if(mode=="retired_bad_version")out->version=18;return true;}
bool maintenance(void*){return closed;}
bool authorize(void*,const DirectorPending&p,DirectorAuthorization*out){if(mode=="maintenance_no_receipt")return false;*out={p.graph.native,p.graph.slot,0x123,p.graph.version,p.operation,17,88};if(mode=="maintenance_wrong_operation")++out->operation;if(mode=="maintenance_wrong_epoch")++out->epoch;if(mode=="maintenance_changes_queue")enqueue(1,0,1);return true;}
DirectorRegistryApi api(){DirectorRegistryApi a{};a.owner_thread=thread;a.source_current=current;a.source_epoch=source_epoch;a.routes_ready=ready;a.mapped=mapped;a.current_graph=owner;a.output_closed=output_closed;a.retired_graph=retired;a.maintenance_closed=maintenance;a.pending_authorized=authorize;return a;}
void setup(){spans={{image,sizeof image},{manager,sizeof manager},{graphs,sizeof graphs},{slots,sizeof slots},{outputs,sizeof outputs},{animator,sizeof animator},{queue,sizeof queue},{nodes,sizeof nodes},{dispatch,sizeof dispatch},{callback,sizeof callback},{values,sizeof values},{deferred,sizeof deferred}};
 profile.manager_slot=0x300;profile.tagged_queue=true;put(image,profile.manager_slot,addr(manager));
 CodeBinding binding{};binding.rva=0x100;for(unsigned i=0;i<16;++i)binding.prefix[i]=0xa5;memcpy(image+0x100,binding.prefix,16);
 CodeBinding*calls[]={&profile.registry_getter,&profile.sample_category,&profile.rebuild,&profile.append,&profile.category,&profile.callbacks_rebuild,&profile.callbacks_dispatch,&profile.output_callbacks,&profile.drain,&profile.collect,&profile.enqueue,&profile.deferred_a,&profile.deferred_b,&profile.deferred_append_a,&profile.deferred_append_b,&profile.graph_create,&profile.graph_destroy,&profile.atomic_push,&profile.atomic_pop};for(auto*c:calls)*c=binding;
 for(unsigned i=0;i<3;++i){auto&r=profile.outputs[i];r.vtable=0x1000+i*0x100;r.producer=binding;r.count=i==0?2:1;r.animation=i==0;put(image,r.vtable+0x20,addr(image)+binding.rva);for(unsigned j=0;j<r.count;++j){r.callbacks[j]=binding;r.callbacks[j].rva=0x2000+i*0x100+j*0x20;memcpy(image+r.callbacks[j].rva,binding.prefix,16);r.categories[j]=i==0?3+j:i==1?5:2;}}
 for(unsigned i=0;i<3;++i){put(graphs[i],16,addr(slots[i]));put(graphs[i],24,uint32_t(1));put(graphs[i],48,uint32_t(2));put(graphs[i],0xac,uint16_t(4));put(slots[i],0x20,uint32_t(20));put(slots[i],0x28,addr(graphs[i]));put(graphs[i],0x78,addr(graphs[i])+0x78);put(graphs[i],0x80,addr(graphs[i])+0x78);}
 link(true,{0});link(false,{1});output(0,0,2);put(manager,0x478,addr(queue));put(manager,0x41d,uint8_t(1));put(manager,0x41e,uint8_t(1));
}
int main(int argc,char**argv){assert(argc==2);mode=argv[1];setup();Result expected=Result::unsupported;auto a=api();int context=1;
 if(mode=="dirty_valid"||mode=="clean_valid"||mode=="stopped_unowned"||mode=="other_pending_quiescent"||mode=="pending_current"||mode=="pending_stale"||mode=="dirty_stale_vectors"||mode=="retired_valid"||mode=="stopped_no_public_slot")expected=Result::ok;
 if(mode=="clean_valid"||mode=="callback_unknown"||mode=="callback_payload_unowned"||mode=="callback_changed"||mode=="dispatch_missing"||mode=="dispatch_wrong_category"||mode=="dispatch_duplicate"||mode=="callback_duplicate"||mode=="callback_empty")clean_dispatch();
 if(mode=="active_unowned")owners[0]=false;
 if(mode=="pending_current"||mode=="target_pending"||mode=="other_pending_quiescent"){owners[1]=true;enqueue(0,1,0);}
 if(mode=="pending_unowned")enqueue(0,1,0);
 if(mode=="pending_stale")enqueue(0,1,0,18);
 if(mode=="pending_unknown_operation")enqueue(0,0,99);
 if(mode=="queue_cycle"){enqueue(0,0,0);put(nodes[0],0,addr(nodes[0]));}
 if(mode=="target_pending")expected=Result::waiting;
 if(mode=="active_phase"){put(manager,0x41b,uint8_t(1));expected=Result::waiting;}
 if(mode=="active_graph_eval"){put(graphs[0],0xc8,uint8_t(1));expected=Result::waiting;}
 if(mode=="slot_resolved_mismatch")put(slots[0],0x28,addr(graphs[1]));
 if(mode=="bad_list_links")put(graphs[0],0,addr(graphs[1]));
 if(mode=="source_changed"||mode=="epoch_changed"||mode=="queue_tag_changed"||mode=="queue_head_changed"||mode=="list_changed"||mode=="version_changed"||mode=="slot_resolved_mismatch"||mode=="bad_list_links")expected=Result::stale;
 if(mode=="dirty_stale_vectors"){put(manager,0x90+2*32,uintptr_t(1));put(manager,0x250+2*32,uintptr_t(1));}
 if(mode=="dispatch_missing")put(manager,0xa0+2*32,uint64_t(0));
 if(mode=="dispatch_wrong_category")put(graphs[0],48,uint32_t(3));
 if(mode=="dispatch_duplicate"){put(manager,0xa0+2*32,uint64_t(2));put(dispatch[2][0],152,addr(graphs[0]));}
 if(mode=="callback_unknown")put(callback[2],0,addr(image)+0x5000);
 if(mode=="callback_payload_unowned")put(values[2],0,addr(outputs[1]));
 if(mode=="callback_empty")put(callback[2],24,uint64_t(0));
 if(mode=="callback_duplicate"){put(callback[2],24,uint64_t(2));put(values[2],8,addr(outputs[0]));}
 if(mode=="output_unknown")put(outputs[0],0,addr(image)+0x1500);
 if(mode=="output_producer_changed")put(image,profile.outputs[2].vtable+0x20,addr(image)+0x8000);
 if(mode=="source_code_changed")image[0x100]=0;
 if(mode=="stopped_no_public_slot")put(graphs[1],16,uintptr_t(0));
 if(mode.rfind("retired",0)==0){owners[0]=false;put(slots[0],0x20,uint32_t(22));if(mode!="retired_without_destroy")enqueue(0,0,2,22);if(mode=="retired_extra_play")enqueue(1,0,0,22);}
 if(mode=="deferred_unowned"||mode=="deferred_current"||mode=="deferred_stale"){vector(manager,0x388,deferred[0],1,3);AnimationGraph h{addr(slots[1]),mode=="deferred_stale"?18u:20u,0};put(deferred[0],0,h);if(mode=="deferred_current"){owners[1]=true;expected=Result::ok;}if(mode=="deferred_stale")expected=Result::ok;}
 if(mode.rfind("maintenance",0)==0){enqueue(0,0,0);if(mode=="maintenance_valid")expected=Result::ok;if(mode=="maintenance_not_captured")closed=false;if(mode=="maintenance_changes_queue")expected=Result::stale;}
 if(mode=="missing_api")a.output_closed=nullptr;
 DirectorRegistryAdmission parser;Result result;
 if(mode.rfind("maintenance",0)==0)result=parser.maintenance_ready(a,&context,profile,addr(image));
 else if(mode=="target_pending"||mode=="other_pending_quiescent"){const unsigned target=mode=="target_pending"?1:0;result=parser.graph_quiescent(a,&context,profile,addr(image),{addr(slots[target]),20,0});}
 else result=parser.admit(a,&context,profile,addr(image));
 if(result!=expected){fprintf(stderr,"%s result %d expected %d: %s\n",mode.c_str(),int(result),int(expected),parser.error());return 1;}
 if(result==Result::ok){assert(parser.summary().active==1);if(mode=="retired_valid")assert(parser.summary().retiring==1);}
 if(mode=="retired_without_destroy")assert(retired_calls==0);
 return 0;
}
'''
@pytest.fixture(scope='module')
def binary(tmp_path_factory):
 compiler=shutil.which('c++')
 if not compiler:pytest.skip('Host C++ compiler required')
 d=tmp_path_factory.mktemp('mp4-director-registry');s=d/'test.cpp';b=d/'test';s.write_text(HARNESS)
 r=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(ROOT/'client-presentation/native'),str(s),'-o',str(b)],capture_output=True,text=True)
 assert r.returncode==0,r.stderr
 return b
MODES=['dirty_valid','clean_valid','stopped_unowned','active_unowned','pending_current','pending_unowned','pending_stale','pending_unknown_operation','queue_cycle','target_pending','other_pending_quiescent','active_phase','active_graph_eval','source_changed','epoch_changed','queue_tag_changed','queue_head_changed','list_changed','version_changed','slot_resolved_mismatch','bad_list_links','dirty_stale_vectors','dispatch_missing','dispatch_wrong_category','dispatch_duplicate','callback_unknown','callback_payload_unowned','callback_changed','callback_empty','callback_duplicate','payload_unowned','output_unknown','output_producer_changed','source_code_changed','stopped_no_public_slot','retired_valid','retired_without_destroy','retired_bad_receipt','retired_wrong_asset','retired_wrong_epoch','retired_wrong_slot','retired_bad_version','retired_extra_play','deferred_unowned','deferred_current','deferred_stale','maintenance_valid','maintenance_no_receipt','maintenance_wrong_operation','maintenance_wrong_epoch','maintenance_not_captured','maintenance_changes_queue','missing_api','wrong_thread','routes_missing','unmapped']
@pytest.mark.parametrize('mode',MODES)
def test_production_director_registry_and_authorized_pending_transitions(binary,mode):
 r=subprocess.run([str(binary),mode],capture_output=True,text=True)
 assert r.returncode==0,r.stderr
