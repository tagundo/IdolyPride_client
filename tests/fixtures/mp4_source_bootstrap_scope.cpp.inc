#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <vector>
// SOURCE_BOOTSTRAP_SCOPE
namespace boot=idoly_mp4_source_bootstrap;using R=boot::Result;
struct F{
 boot::Scope scope;boot::Key key{7,9,0x100,0x200};bool thread=true,window=true,aggregate=true,lose_on_query=false;
 bool owned[boot::phases]{},withdrawn[boot::phases]{};uint64_t proof[boot::phases]{},serial=100;
 int calls[boot::phases]{},releases[boot::phases]{},wait[boot::phases]{},release_wait[boot::phases]{};
 int fail=-1,zero=-1,bad=-1,wait_proof=-1,throw_advance=-1,throw_current=-1,throw_release=-1,throw_withdraw=-1,release_fail=-1,reenter=-1,lose_on_advance=-1;
 unsigned changed=0;std::vector<unsigned>released;
 template<size_t I>static R advance(void*c,const boot::Key&k,uint64_t*out){auto&f=*static_cast<F*>(c);assert(boot::same(k,f.key));++f.calls[I];f.owned[I]=true;
  if(f.reenter==int(I))assert(f.scope.run()==R::invalid);
  if(f.throw_advance==int(I))throw std::runtime_error("advance");
  if(f.lose_on_advance==int(I))f.window=false;
  if(f.wait[I]){--f.wait[I];if(f.wait_proof==int(I))*out=44;return R::waiting;}
  if(f.fail==int(I))return R::unsupported;
  f.proof[I]=++f.serial;*out=f.zero==int(I)?0:f.proof[I];return R::ok;}
 template<size_t I>static bool current(void*c,const boot::Key&k,uint64_t proof){auto&f=*static_cast<F*>(c);
  if(f.throw_current==int(I))throw std::runtime_error("current");
  return boot::same(k,f.key)&&f.owned[I]&&proof==f.proof[I]&&proof&&f.bad!=int(I)&&!(f.changed&(1u<<I));}
 template<size_t I>static void withdraw(void*c,const boot::Key&k){auto&f=*static_cast<F*>(c);assert(boot::same(k,f.key));if(f.throw_withdraw==int(I)){f.throw_withdraw=-1;throw std::runtime_error("withdraw");}f.withdrawn[I]=true;}
 template<size_t I>static R release(void*c,const boot::Key&k){auto&f=*static_cast<F*>(c);assert(boot::same(k,f.key));++f.releases[I];
  for(size_t j=I;j<boot::phases;++j)if(f.owned[j])assert(f.withdrawn[j]);
  for(size_t j=I+1;j<boot::phases;++j)assert(!f.owned[j]);
  if(f.throw_release==int(I)){f.throw_release=-1;throw std::runtime_error("release");}
  if(f.release_fail==int(I)){f.release_fail=-1;return R::failed;}
  if(f.release_wait[I]){--f.release_wait[I];return R::waiting;}
  f.owned[I]=false;f.proof[I]=0;f.released.push_back(I);return R::ok;}
 template<size_t I>void phase(boot::Api&a){a.provider[I]={advance<I>,current<I>,withdraw<I>,release<I>};}
 boot::Api api(){boot::Api a{};a.context=this;a.thread=[](void*c){return static_cast<F*>(c)->thread;};a.source_window=[](void*c,const boot::Key&k){auto&f=*static_cast<F*>(c);return f.window&&boot::same(f.key,k);};
  phase<0>(a);phase<1>(a);phase<2>(a);phase<3>(a);phase<4>(a);phase<5>(a);phase<6>(a);phase<7>(a);
  a.aggregate_owns=[](void*c,const boot::Key&k,const uint64_t*receipts,size_t count){auto&f=*static_cast<F*>(c);if(f.lose_on_query)f.window=false;
   if(!f.aggregate||!boot::same(k,f.key)||count!=boot::phases)return false;
   for(size_t i=0;i<count;++i)if(!f.owned[i]||receipts[i]!=f.proof[i])return false;
   return true;};return a;}
 void start(){assert(scope.begin(api(),key)==R::ok);}bool empty()const{for(bool own:owned)if(own)return false;return true;}
};
int main(){unsigned cases=0;
 {F f;f.start();assert(f.scope.run()==R::ok&&f.scope.ready());for(int c:f.calls)assert(c==1);assert(f.scope.run()==R::ok);for(int c:f.calls)assert(c==1);assert(f.scope.seal()==R::ok&&f.scope.sealed()&&f.scope.cancel()==R::invalid);assert(!f.empty());++cases;}
 for(unsigned i=0;i<boot::phases;++i){F f;f.wait[i]=2;f.start();assert(f.scope.run()==R::waiting&&f.scope.next()==i);for(unsigned j=0;j<i;++j)assert(f.calls[j]==1);assert(f.scope.run()==R::waiting&&f.scope.run()==R::ok);for(unsigned j=0;j<boot::phases;++j)assert(f.calls[j]==(j==i?3:1));++cases;}
 for(unsigned i=0;i<boot::phases;++i){F f;f.fail=int(i);f.start();assert(f.scope.run()==R::unsupported&&f.scope.clean()&&f.empty());assert(f.released.size()==i+1);for(size_t j=0;j<f.released.size();++j)assert(f.released[j]==i-j);++cases;}
 for(unsigned i=0;i<boot::phases;++i){F f;f.fail=int(i);f.release_wait[i]=2;f.start();assert(f.scope.run()==R::waiting&&!f.scope.clean());for(unsigned j=0;j<i;++j)assert(f.owned[j]&&!f.releases[j]);assert(f.scope.run()==R::waiting&&f.scope.run()==R::unsupported&&f.empty());assert(f.calls[i]==1);++cases;}
 {F f;f.fail=3;f.release_fail=3;f.start();assert(f.scope.run()==R::waiting&&!f.scope.clean()&&f.owned[1]);assert(f.scope.run()==R::unsupported&&f.empty());++cases;}
 {F f;f.fail=4;f.throw_release=4;f.start();assert(f.scope.run()==R::waiting&&f.owned[1]);assert(f.scope.run()==R::unsupported&&f.empty());++cases;}
 {F f;f.fail=4;f.throw_withdraw=4;f.start();assert(f.scope.run()==R::waiting&&f.released.empty());assert(f.scope.run()==R::unsupported&&f.empty());++cases;}
 {F f;f.wait[4]=1;f.start();assert(f.scope.run()==R::waiting);f.window=false;assert(f.scope.run()==R::stale&&f.empty());++cases;}
 {F f;f.wait[4]=1;f.start();assert(f.scope.run()==R::waiting);f.changed=1u<<1;assert(f.scope.run()==R::stale&&f.empty());++cases;}
 {F f;f.zero=5;f.start();assert(f.scope.run()==R::stale&&f.empty());++cases;}
 {F f;f.bad=5;f.start();assert(f.scope.run()==R::stale&&f.empty());++cases;}
 {F f;f.throw_advance=4;f.start();assert(f.scope.run()==R::failed&&f.empty());++cases;}
 {F f;f.throw_current=4;f.start();assert(f.scope.run()==R::failed&&f.empty());++cases;}
 {F f;f.wait[4]=1;f.wait_proof=4;f.start();assert(f.scope.run()==R::failed&&f.empty());++cases;}
 {F f;f.reenter=2;f.start();assert(f.scope.run()==R::ok&&f.scope.cancel()==R::invalid&&f.empty());++cases;}
 {F f;f.lose_on_advance=6;f.start();assert(f.scope.run()==R::stale&&f.empty());++cases;}
 {F f;f.wait[3]=1;f.start();assert(f.scope.run()==R::waiting);f.thread=false;assert(f.scope.cancel()==R::invalid&&f.released.empty());f.thread=true;assert(f.scope.cancel()==R::invalid&&f.empty());++cases;}
 {F f;f.start();assert(f.scope.seal()==R::invalid);assert(f.scope.cancel()==R::invalid&&f.empty());++cases;}
 {F f;f.start();assert(f.scope.run()==R::ok);f.aggregate=false;assert(f.scope.seal()==R::unsupported&&f.empty()&&!f.scope.transferred());++cases;}
 {F f;f.start();assert(f.scope.run()==R::ok);f.lose_on_query=true;assert(f.scope.seal()==R::stale&&f.empty());++cases;}
 {F f;f.start();assert(f.scope.run()==R::ok);f.changed=1u<<7;assert(f.scope.seal()==R::stale&&f.empty());++cases;}
 {F f;auto a=f.api();a.provider[4].advance=nullptr;assert(f.scope.begin(a,f.key)==R::invalid&&f.empty());++cases;}
 {F f;auto a=f.api();a.aggregate_owns=nullptr;assert(f.scope.begin(a,f.key)==R::invalid&&f.empty());++cases;}
 {F f;f.window=false;assert(f.scope.begin(f.api(),f.key)==R::stale&&f.empty());++cases;}
 {F f;f.fail=3;f.start();assert(f.scope.run()==R::unsupported&&f.empty());f.fail=-1;f.withdrawn[0]=f.withdrawn[1]=f.withdrawn[2]=f.withdrawn[3]=false;assert(f.scope.begin(f.api(),f.key)==R::ok&&f.scope.run()==R::ok);++cases;}
 {F f;f.wait[2]=1;f.start();assert(f.scope.run()==R::waiting&&f.scope.begin(f.api(),f.key)==R::invalid);assert(f.scope.cancel()==R::invalid&&f.empty());++cases;}
 std::printf("%u source bootstrap latching/cleanup cases passed; actual native providers are modeled\n",cases);
}
