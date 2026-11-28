#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <atomic>
#include <cassert>
#include <map>
#include "mp4_engine_clock.hpp"
#include "pending-journal.hpp"
#include "birth-scope.hpp"
#include "source-origin.hpp"
#include "typed-host.hpp"
#include "passive-scope.hpp"
namespace s=mp4_source_factory;
struct Model{
 bool owner=true,ordinary=true,bindings=true,inspect=true,returned=true,changed=false,release_throw=false;unsigned calls=0,releases=0,retains=0,depth=0;int mode=0;uint32_t next=0;
 std::map<uint32_t,void*>roots; s::Ticket seen[40]{};s::Journal journal;
 s::Input input(uintptr_t graph=0x100){return {0x10,0x20,0x30,0x40,{graph,2,0}};}
 s::Api api(){s::Api a{};a.context=this;a.owner_thread=[](void*p){return ((Model*)p)->owner;};a.ordinary_stack=[](void*p){return ((Model*)p)->ordinary;};a.bindings=[](void*p,s::Factory){return ((Model*)p)->bindings;};
 a.inspect=[](void*p,const s::Input&i,s::Image*out){auto&m=*(Model*)p;bool asset_root=false,go_root=false;for(auto item:m.roots){asset_root|=item.second==(void*)i.asset;go_root|=item.second==(void*)i.game_object;}assert(asset_root&&go_root);if(m.mode==28)throw 28;if(!m.inspect||i.method!=0x30||i.return_pc!=0x40)return false;*out={{i.asset,0x50,i.asset+0x10000,m.changed?3u:1u},{i.game_object,0x60,i.game_object+0x20000,2},i.graph.handle+0x80000,2};if(m.mode==15)out->asset.klass=0;if(m.mode==16)out->asset.instance=0;return true;};
 a.returned=[](void*p,const s::Input&i,const s::Image&,s::Playable root){auto&m=*(Model*)p;if(m.mode==29)throw 29;return m.returned&&root.handle==i.graph.handle+0x90000&&root.version==12;};
 a.retain=[](void*p){auto&m=*active;++m.retains;if(m.mode==30&&m.retains==2)throw 30;const auto id=++m.next;m.roots[id]=m.mode==11?(void*)0xdead:p;return id;};
 a.target=[](uint32_t id){auto&m=*active;auto i=m.roots.find(id);return i==m.roots.end()?nullptr:i->second;};a.release=[](uint32_t id){auto&m=*active;if(m.release_throw){m.release_throw=false;throw 31;}assert(m.roots.erase(id)==1);++m.releases;};return a;}
 static Model*active;
};Model*Model::active=nullptr;
s::Playable original(void*asset,s::Graph graph,void*go,const void*method){auto&m=*Model::active;++m.calls;const unsigned d=m.depth++;s::Context c{};const bool observed=m.journal.context(graph,&c);
 if(observed){m.seen[d]=c.ticket;assert(c.input.asset==(uintptr_t)asset&&c.input.game_object==(uintptr_t)go&&c.input.method==(uintptr_t)method);assert(c.ticket.depth==d+1);if(d)assert(c.parent.serial==m.seen[d-1].serial);else assert(!c.parent.serial);}
 if(m.mode==19){auto wrong=graph;++wrong.version;assert(!m.journal.context(wrong,&c));}
 if(m.mode==23)assert(!m.journal.clear());
 if(m.mode==6||m.mode==25){--m.depth;throw 42;}
 if(m.mode==9||m.mode==24||m.mode==34){const auto released=m.releases;m.journal.invalidate();assert(m.releases==released&&!m.journal.context(graph,&c));}
 if((m.mode==20&&d==0)||(m.mode==27&&d<32)){auto next=m.input(graph.handle+1);(void)s::observe(m.journal,original,next);}
 if(m.mode==10)m.changed=true;
 --m.depth;return {m.mode==8?0:graph.handle+0x90000,12,0};
}
int main(int argc,char**argv){assert(argc==2);Model m;Model::active=&m;m.mode=atoi(argv[1]);auto api=m.api();if(m.mode!=1)assert(m.journal.configure(api,original));
 if(m.mode==2)m.owner=false;if(m.mode==3)m.ordinary=false;if(m.mode==4)m.bindings=false;if(m.mode==5)m.inspect=false;if(m.mode==7)m.returned=false;
 auto input=m.input();if(m.mode==12)++input.return_pc;if(m.mode==13)++input.method;if(m.mode==14)input.graph.version=4;
 if(m.mode==6||m.mode==25){bool caught=false;try{s::observe(m.journal,original,input);}catch(int x){caught=x==42;}assert(caught&&m.calls==1);m.mode=0;assert(m.journal.clear());assert(m.roots.empty());return 0;}
 const auto root=s::observe(m.journal,original,input);assert(m.calls==(m.mode==20?2u:m.mode==27?33u:1u));
 s::Receipt receipt{};const bool good=m.journal.find(input,root,&receipt);
 if(m.mode==1||m.mode==2||m.mode==3||m.mode==4||m.mode==5||m.mode==7||m.mode==8||m.mode==9||m.mode==10||m.mode==11||m.mode==12||m.mode==13||m.mode==14||m.mode==15||m.mode==16||m.mode==24||m.mode==28||m.mode==29||m.mode==30||m.mode==34)assert(!good);
 else{assert(good&&receipt.source.ticket.serial&&receipt.root.handle==root.handle);s::Receipt again{};assert(m.journal.receipt(receipt.source.ticket,&again));
  auto bad=receipt.source.ticket;bad.serial+=1000;assert(!m.journal.receipt(bad,&again));
  if(m.mode==17){m.changed=true;assert(!m.journal.find(input,root,&again));}
  if(m.mode==18){auto wrong=root;++wrong.version;assert(!m.journal.find(input,wrong,&again));}
  if(m.mode==26){for(size_t i=0;i<256;++i){auto next=m.input(0x200+i);(void)s::observe(m.journal,original,next);}assert(!m.journal.receipt(receipt.source.ticket,&again)&&m.roots.size()==512);}
  if(m.mode==32){const auto before=m.releases;m.journal.invalidate();assert(!m.journal.find(input,root,&again)&&m.releases==before);}
 }
 if(m.mode==33){m.owner=false;const auto before=m.releases;assert(!m.journal.clear()&&m.releases==before);}
 const int original_mode=m.mode;m.owner=true;m.ordinary=true;m.mode=0;if(original_mode==31)m.release_throw=true;
 if(original_mode==1){assert(!m.journal.clear()&&m.roots.empty());return 0;}if(m.release_throw)assert(!m.journal.clear());assert(m.journal.clear()&&m.roots.empty());
}
