#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <map>
#include <string>
#ifdef TEST_ACTIVATION
#include "activation-node-scope.hpp.inc"
namespace n=idoly_mp4_activation_nodes;
#else
#include "director-node-scope.hpp.inc"
namespace n=idoly_mp4_director_nodes;
#endif
struct H {
 int objects[120]{}; n::Node nodes[2][4][2]{};
 std::map<void*,n::State> states;std::map<uint32_t,void*> roots;
 unsigned generation[2]{0,0}, expected_old[2]{0,0};uint32_t root_sequence=0;
 void*pending=nullptr;n::Round pending_round=n::Round::source;
 bool batch=false;unsigned affected=3;
 bool source=true,owned=true,waiting=false,incomplete=false,duplicate=false,badkey=false,readfail=false,freshgood=true,wrongemit=false,siblingmutate=false,halfwait=false,siblingalias=false;
 size_t writes=0,freshcalls=0,oldqueries=0;
 static n::State scalar(int i){n::State s{};
#ifdef TEST_ACTIVATION
 s.post=i%3;s.initial=i%2;
#else
 s.sync=i%2;s.duration=40+i;
#endif
 return s;}
 static bool state_equal(const n::State&a,const n::State&b){
#ifdef TEST_ACTIVATION
 return a.post==b.post&&a.initial==b.initial;
#else
 return a.sync==b.sync&&a.duration==b.duration;
#endif
 }
 H(){for(unsigned d=0;d<2;++d)for(unsigned g=0;g<4;++g)for(unsigned i=0;i<2;++i){
 auto &x=nodes[d][g][i];x.key={&objects[d],&objects[2+d],&objects[4+d],&objects[6+d*2+i],&objects[10+d*2+i],&objects[14+d*2+i],{},1};x.key.path[0]=uint16_t(i);
 x.script=&objects[20+d*8+g*2+i];x.graph={100+d*10+g,1,0};x.runtime={200+d*100+g*10+i,1,0};x.node={500+d*100+g*10+i,1,0};x.factory=1+g;x.birth=g?100+g:0;states[x.script]=scalar(g?10+int(i):int(d*2+i));
#ifdef TEST_ACTIVATION
 states[x.script].post=int(d*2+i)%3;
#endif
 }}
 int director(void*p)const{return p==nodes[0][0][0].key.director?0:p==nodes[1][0][0].key.director?1:-1;}
 static H&self(void*p){return *static_cast<H*>(p);}
 static bool current(void*p,uint64_t e){return self(p).source&&e==99;}
 static bool held(void*){return true;}
 static bool owner(void*p,const n::Key&k){return self(p).source&&self(p).director(k.director)>=0;}
 static bool whole_pending(void*p,n::Round r){auto&h=self(p);return h.batch&&h.owned&&h.pending_round==r;}
 static bool pending_for(void*p,n::Round r,void*d){auto&h=self(p);return h.owned&&h.pending_round==r&&(h.batch?(h.director(d)>=0&&(h.affected&(1u<<h.director(d)))):h.pending==d);}
 static bool live(void*p,const n::Node&x){auto&h=self(p);int d=h.director(x.key.director);if(d<0)return false;bool result=x.graph.handle==h.nodes[d][h.generation[d]][0].graph.handle;if(!result)++h.oldqueries;return result;}
 static bool fresh(void*p,n::Round,const n::Node&old,const n::Node&now){auto&h=self(p);++h.freshcalls;int d=h.director(now.key.director);return d>=0&&h.freshgood&&old.graph.handle==h.nodes[d][h.expected_old[d]][0].graph.handle&&now.graph.handle==h.nodes[d][h.generation[d]][0].graph.handle&&old.graph.handle!=now.graph.handle&&now.birth;}
 static bool read(void*p,const n::Node&x,n::State*out){auto&h=self(p);if(h.readfail&&x.key.path[0]==1)return false;*out=h.states[x.script];return true;}
 static bool write(void*p,const n::Node&x,const n::State&s){auto&h=self(p);++h.writes;h.states[x.script]=s;return true;}
 static n::Result source_visit(void*p,n::Round r,n::Emit emit,void*ctx,uint64_t*receipt){auto&h=self(p);if(r!=n::Round::source)return n::Result::unsupported;for(unsigned d=0;d<2;++d)for(auto&x:h.nodes[d][0])if(!emit(ctx,x))return n::Result::unsupported;*receipt=7;return n::Result::ok;}
 static n::Result visit_for(void*p,n::Round r,void*director,n::Emit emit,void*ctx,uint64_t*receipt){auto&h=self(p);*receipt=0;if(!pending_for(p,r,director))return n::Result::stale;if(h.waiting)return n::Result::waiting;int d=h.director(director);if(d<0)return n::Result::unsupported;if(h.wrongemit)d=1-d;for(unsigned i=0;i<(h.incomplete?1u:2u);++i){auto x=h.nodes[d][h.generation[d]][i];if(h.duplicate&&i)x=h.nodes[d][h.generation[d]][0];if(h.badkey&&i)x.key.path[0]=9;if(h.siblingalias&&i==1){x.script=h.nodes[1-d][h.generation[1-d]][0].script;x.node=h.nodes[1-d][h.generation[1-d]][0].node;}if(!emit(ctx,x))return n::Result::unsupported;if(h.halfwait)return n::Result::waiting;}if(h.siblingmutate){int sibling=1-d;h.states[h.nodes[sibling][h.generation[sibling]][0].script]=scalar(12);}*receipt=8;return n::Result::ok;}
 static H* rooting;
 static uint32_t keep(void*p){auto&h=*rooting;h.roots[++h.root_sequence]=p;return h.root_sequence;}
 static void*get(uint32_t k){auto&h=*rooting;auto i=h.roots.find(k);return i==h.roots.end()?nullptr:i->second;}
 static void drop(uint32_t k){assert(rooting->roots.erase(k)==1);}
 n::Api api(){rooting=this;n::Api a{current,held,owner,whole_pending,source_visit,live,fresh,read,write,keep,get,drop};a.pending_director_current=pending_for;a.visit_director=visit_for;return a;}
 void begin(n::Scope&s,unsigned d,n::Round r){pending=nodes[d][0][0].key.director;pending_round=r;assert(s.expect_remap(r,pending)==n::Result::ok);expected_old[d]=generation[d];++generation[d];}
 n::Result finish(n::Scope&s){return s.remap_director(pending_round,pending);}
 void transition(n::Scope&s,unsigned d,n::Round r){begin(s,d,r);assert(finish(s)==n::Result::ok);assert(s.current());}
};H* H::rooting=nullptr;
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];H h;n::Scope s;auto api=h.api();assert(s.capture(api,&h,99)==n::Result::ok);
 if(mode=="missing_callbacks"){assert(s.release(false)==n::Result::ok);api.pending_director_current=nullptr;assert(s.capture(api,&h,99)==n::Result::ok);h.pending=h.nodes[0][0][0].key.director;h.pending_round=n::Round::exporting;assert(s.expect_remap(h.pending_round,h.pending)==n::Result::stale);}
 else if(mode=="wrong_director"){h.pending=h.nodes[0][0][0].key.director;h.pending_round=n::Round::exporting;assert(s.expect_remap(h.pending_round,h.nodes[1][0][0].key.director)==n::Result::stale);}
 else {
 h.begin(s,0,n::Round::exporting);assert(s.current()&&h.oldqueries==0);n::Node lookup{};assert(s.lookup_receiver(h.nodes[0][0][0].script,true,&lookup)&&lookup.graph.handle==100);
 if(mode=="lost_call"){h.owned=false;assert(!s.current()&&h.finish(s)==n::Result::stale);}
 else if(mode=="sibling_changed"){h.generation[1]=1;assert(!s.current()&&h.finish(s)==n::Result::stale);}
 else if(mode=="wrong_round"){assert(s.remap_director(n::Round::restoring,h.pending)==n::Result::stale);}
 else if(mode=="wrong_remap_director"){assert(s.remap_director(h.pending_round,h.nodes[1][0][0].key.director)==n::Result::stale);}
 else if(mode=="global_during_target"){assert(s.remap(h.pending_round)==n::Result::invalid);}
 else if(mode=="incomplete"||mode=="duplicate"||mode=="bad_key"||mode=="bad_birth"||mode=="read_failure"||mode=="wrong_emit"||mode=="sibling_alias"){
 h.incomplete=mode=="incomplete";h.duplicate=mode=="duplicate";h.badkey=mode=="bad_key";h.freshgood=mode!="bad_birth";h.readfail=mode=="read_failure";h.wrongemit=mode=="wrong_emit";h.siblingalias=mode=="sibling_alias";assert(h.finish(s)!=n::Result::ok&&h.writes==0);assert(s.lookup_receiver(h.nodes[0][0][0].script,false,&lookup)&&lookup.graph.handle==100);assert(!s.lookup_receiver(h.nodes[0][1][0].script,false,&lookup));}
 else {
 if(mode=="wait_retry"||mode=="partial_wait"){h.waiting=mode=="wait_retry";h.halfwait=mode=="partial_wait";assert(h.finish(s)==n::Result::waiting&&h.writes==0&&s.current());assert(s.lookup_receiver(h.nodes[0][0][0].script,false,&lookup));h.waiting=h.halfwait=false;}
 assert(h.finish(s)==n::Result::ok&&s.current());assert(s.round()==n::Round::source);assert(s.restore()==n::Result::waiting&&h.writes==0);
 if(mode=="repeat_same_round"||mode=="retiring_generation"){
 h.begin(s,0,n::Round::exporting);const auto queries=h.oldqueries;assert(s.lookup_receiver(h.nodes[0][1][0].script,true,&lookup)&&lookup.graph.handle==101&&h.oldqueries==queries);assert(h.finish(s)==n::Result::ok&&s.current());assert(s.round()==n::Round::source);}
 h.transition(s,1,n::Round::exporting);assert(s.round()==n::Round::exporting);
 h.transition(s,0,n::Round::restoring);assert(s.round()==n::Round::exporting);assert(s.restore()==n::Result::waiting&&h.writes==0);
 h.transition(s,1,n::Round::restoring);assert(s.round()==n::Round::restoring);assert(s.restore()==n::Result::ok&&s.current());assert(h.writes==4);
 for(unsigned d=0;d<2;++d)for(unsigned i=0;i<2;++i)assert(H::state_equal(h.states[h.nodes[d][h.generation[d]][i].script],H::scalar(int(d*2+i))));
 if(mode=="restored_sibling_changed"){
 h.begin(s,0,n::Round::restoring);h.siblingmutate=true;assert(h.finish(s)==n::Result::stale);}
 else {assert(s.restore()==n::Result::ok&&h.writes==4);}
 }
 }
 assert(s.release(false)==n::Result::ok&&h.roots.empty());return 0;
}
