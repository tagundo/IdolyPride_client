#define main prior_incremental_main
#include "node-incremental-model.inc"
#undef main
void begin_batch(H&h,n::Scope&s,n::Round round,unsigned affected){
 h.batch=true;h.affected=affected;h.pending=nullptr;h.pending_round=round;
 assert(s.expect_remap(round)==n::Result::ok);
 for(unsigned d=0;d<2;++d)if(affected&(1u<<d)){h.expected_old[d]=h.generation[d];++h.generation[d];}
 assert(s.current());
}
void map(H&h,n::Scope&s,unsigned d,n::Round r){assert(s.remap_director(r,h.nodes[d][0][0].key.director)==n::Result::ok);assert(s.current());}
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];H h;n::Scope s;auto api=h.api();assert(s.capture(api,&h,99)==n::Result::ok);
 unsigned affected=mode=="unaffected"||mode=="unaffected_changed"?1:3;
 if(mode=="expect_stale"){h.generation[0]=1;h.batch=true;h.pending_round=n::Round::exporting;assert(s.expect_remap(h.pending_round)==n::Result::stale);}
 else {
 begin_batch(h,s,n::Round::exporting,affected);
 n::Node lookup{};assert(s.lookup_receiver(h.nodes[0][0][0].script,true,&lookup));
 assert(s.finish_remap(n::Round::exporting)==n::Result::waiting&&h.oldqueries==0);
 if(mode=="call_lost"){h.owned=false;assert(!s.current()&&s.finish_remap(n::Round::exporting)==n::Result::stale);}
 else if(mode=="wrong_target"){h.affected=1;assert(s.remap_director(n::Round::exporting,h.nodes[1][0][0].key.director)==n::Result::stale);}
 else if(mode=="wrong_round"){assert(s.remap_director(n::Round::restoring,h.nodes[0][0][0].key.director)==n::Result::stale);}
 else if(mode=="read_failure"){h.readfail=true;assert(s.remap_director(n::Round::exporting,h.nodes[0][0][0].key.director)!=n::Result::ok);assert(s.lookup_receiver(h.nodes[0][0][0].script,false,&lookup));}
 else if(mode=="unaffected_changed"){h.generation[1]=1;assert(!s.current()&&s.remap_director(n::Round::exporting,h.nodes[0][0][0].key.director)==n::Result::stale);}
 else {
 if(mode=="wait_retry"){h.halfwait=true;assert(s.remap_director(n::Round::exporting,h.nodes[0][0][0].key.director)==n::Result::waiting&&h.writes==0);h.halfwait=false;}
 map(h,s,0,n::Round::exporting);
 if(mode=="partial_finish"){assert(s.finish_remap(n::Round::exporting)==n::Result::waiting&&h.oldqueries==0);}
 else {
 if(affected&2)map(h,s,1,n::Round::exporting);
 if(mode=="finish_after_call"){h.owned=false;assert(s.finish_remap(n::Round::exporting)==n::Result::stale);}
 else {
 assert(s.finish_remap(n::Round::exporting)==n::Result::ok&&s.current());assert(s.restore()==n::Result::waiting&&h.writes==0);
 if(mode=="repeat_same_round"||mode=="retiring_latest"){
 begin_batch(h,s,n::Round::exporting,affected);const auto old_queries=h.oldqueries;
 assert(s.lookup_receiver(h.nodes[0][1][0].script,true,&lookup)&&lookup.graph.handle==101&&h.oldqueries==old_queries);
 map(h,s,0,n::Round::exporting);if(affected&2)map(h,s,1,n::Round::exporting);assert(s.finish_remap(n::Round::exporting)==n::Result::ok);
 }
 begin_batch(h,s,n::Round::restoring,affected);map(h,s,0,n::Round::restoring);if(affected&2)map(h,s,1,n::Round::restoring);assert(s.finish_remap(n::Round::restoring)==n::Result::ok);
 assert(s.restore()==n::Result::ok&&s.current()&&h.writes==4);
 for(unsigned d=0;d<2;++d)for(unsigned i=0;i<2;++i)assert(H::state_equal(h.states[h.nodes[d][h.generation[d]][i].script],H::scalar(int(d*2+i))));
 }
 }
 }
 }
 assert(s.release(false)==n::Result::ok&&h.roots.empty());
}
