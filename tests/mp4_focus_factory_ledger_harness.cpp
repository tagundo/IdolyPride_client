#include <cstdint>
#include <cstddef>
#include <cassert>
#include <cstdio>
#include <stdexcept>
#include "focus-factory-ledger.inc"
using namespace idoly_mp4_focus_private;
struct F{int objects[4]{};void*roots[32]{};uint32_t next=1;bool alive[4]{true,true,true,true};bool source=true,thread=true,entry=true,receiver=true,detached=true,retain_fail=false,destroy_false=false,destroy_throw=false,deferred=false;int reads=0,destroys=0;};static F*f;
bool current(void*,uint64_t e){++f->reads;return f->source&&e==11;}bool thread(){++f->reads;return f->thread;}bool entry(void*,uint64_t,uint64_t,Role){++f->reads;return f->entry;}bool receiver(void*,uint64_t,Role,void*p,uintptr_t n){++f->reads;for(int i=0;i<4;++i)if(p==&f->objects[i]&&n==100u+i)return f->receiver;return false;}uint32_t retain(void*p){if(f->retain_fail)return 0;auto n=f->next++;f->roots[n]=p;return n;}void*retained(uint32_t n){return f->roots[n];}void drop(uint32_t n){assert(f->roots[n]);f->roots[n]=nullptr;}bool detached(void*,uint64_t){++f->reads;return f->detached;}bool alive(void*,void*p,uintptr_t n){for(int i=0;i<4;++i)if(p==&f->objects[i]&&n==100u+i)return f->alive[i];assert(false);return false;}bool destroy(void*,void*p,uintptr_t n){++f->destroys;if(f->destroy_throw)throw std::runtime_error("destroy");if(f->destroy_false)return false;if(!f->deferred)for(int i=0;i<4;++i)if(p==&f->objects[i]&&n==100u+i)f->alive[i]=false;return true;}
FactoryApi api(){return {current,thread,entry,receiver,retain,retained,drop,detached,alive,destroy};}void configure(FactoryLedger&l){assert(l.configure(api(),f,11));}void object(FactoryLedger&l,int i,uint64_t s,Role r){assert(l.begin(s,r));assert(l.before_base(s,r,&f->objects[i],100+i)==Observe::owned);assert(l.result(s,r,&f->objects[i],100+i)==Observe::owned);assert(l.end(s));}
int main(){int count=0;
#define CASE(name) {F fixture;f=&fixture;FactoryLedger l;++count;
#define END }
 CASE(twoobjects) configure(l);object(l,0,1,Role::profile);object(l,1,2,Role::dof);assert(l.count()==2&&l.release()&&f->destroys==2); END
 CASE(resultfallback) configure(l);assert(l.begin(1,Role::profile));assert(l.result(1,Role::profile,&f->objects[0],100)==Observe::owned);assert(l.end(1)&&l.release()); END
 CASE(newsourceforward) configure(l);assert(l.begin(1,Role::profile));assert(l.before_base(0,Role::profile,&f->objects[1],101)==Observe::forward);assert(!l.end(1)&&!l.release()); END
 CASE(wrongroleforward) configure(l);assert(l.begin(1,Role::profile));assert(l.before_base(1,Role::dof,&f->objects[1],101)==Observe::forward);assert(!l.end(1)&&!l.release()); END
 CASE(provenancefailure) configure(l);assert(l.begin(1,Role::profile));f->receiver=false;assert(l.before_base(1,Role::profile,&f->objects[0],100)==Observe::reject);assert(!l.end(1));assert(!l.release()); END
 CASE(zero_native) configure(l);assert(l.begin(1,Role::profile));assert(l.before_base(1,Role::profile,&f->objects[0],0)==Observe::reject);assert(!l.end(1)&&!l.release()); END
 CASE(nestedentry) configure(l);assert(l.begin(1,Role::profile));assert(!l.begin(2,Role::dof));assert(!l.end(1)&&!l.release()); END
 CASE(reusedserial) configure(l);object(l,0,1,Role::profile);assert(!l.begin(1,Role::dof));assert(l.release()); END
 CASE(staleowner) configure(l);f->source=false;assert(!l.begin(1,Role::profile)&&l.release()); END
 CASE(wrongthread) f->thread=false;assert(!l.configure(api(),f,11)); END
 CASE(entryreject) configure(l);f->entry=false;assert(!l.begin(1,Role::profile)&&l.release()); END
 CASE(pureabandon) configure(l);object(l,0,1,Role::profile);int n=f->reads;l.abandon();assert(f->reads==n&&!l.begin(2,Role::dof));assert(l.release()); END
 CASE(lateresult) configure(l);assert(l.begin(1,Role::profile));int n=f->reads;l.abandon();assert(f->reads==n);f->source=false;assert(l.result(1,Role::profile,&f->objects[0],100)==Observe::owned);assert(!l.end(1)&&l.release()); END
 CASE(activecannotrelease) configure(l);assert(l.begin(1,Role::profile));assert(!l.release());assert(!l.end(1)&&!l.release()); END
 CASE(detachedrequired) configure(l);object(l,0,1,Role::profile);f->detached=false;assert(!l.release()&&f->destroys==0);f->detached=true;assert(l.release()); END
 CASE(partialdestroyfalse) configure(l);object(l,0,1,Role::profile);f->destroy_false=true;assert(!l.release()&&f->destroys==1);f->destroy_false=false;assert(!l.release()&&f->destroys==1); END
 CASE(partialdestroythrows) configure(l);object(l,0,1,Role::profile);f->destroy_throw=true;try{l.release();assert(false);}catch(const std::runtime_error&){}f->destroy_throw=false;assert(!l.release()&&f->destroys==1); END
 CASE(deferred_destroy) configure(l);object(l,0,1,Role::profile);f->deferred=true;assert(!l.release()&&f->destroys==1);f->alive[0]=false;assert(l.release()&&f->destroys==1); END
 CASE(rootfailurefallback) configure(l);assert(l.begin(1,Role::profile));f->retain_fail=true;assert(l.before_base(1,Role::profile,&f->objects[0],100)==Observe::reject);f->retain_fail=false;assert(l.result(1,Role::profile,&f->objects[0],100)==Observe::owned);assert(!l.end(1)&&l.release()); END
 CASE(unobservablefailure) configure(l);assert(l.begin(1,Role::profile));assert(!l.end(1,true)&&!l.release()); END
 CASE(nativealias) configure(l);object(l,0,1,Role::profile);assert(l.begin(2,Role::dof));assert(l.before_base(2,Role::dof,&f->objects[0],100)==Observe::reject);assert(!l.end(2)&&!l.release()); END
 CASE(alreadydead) configure(l);object(l,0,1,Role::profile);f->alive[0]=false;assert(l.release()&&f->destroys==0); END
 CASE(doublecleanup) configure(l);object(l,0,1,Role::profile);assert(l.cleanup()&&l.release()&&f->destroys==1); END
 CASE(reuse) configure(l);object(l,0,1,Role::profile);assert(l.release());f->alive[0]=true;configure(l);object(l,0,1,Role::profile);assert(l.release()); END
 CASE(zeroepoch) assert(!l.configure(api(),f,0)); END
 CASE(resultafterendforward) configure(l);assert(l.begin(1,Role::profile)&&!l.end(1));assert(l.result(1,Role::profile,&f->objects[0],100)==Observe::forward);assert(!l.release()); END
 CASE(handoffresult_detachbusy) configure(l);assert(l.begin(1,Role::profile));l.abandon();assert(l.result(1,Role::profile,&f->objects[0],100)==Observe::owned);assert(!l.end(1));f->detached=false;assert(!l.release());f->detached=true;assert(l.release()); END
 CASE(accessors) configure(l);object(l,0,1,Role::profile);object(l,1,2,Role::dof);assert(l.owns_object_raw(&f->objects[0])&&l.owns_object_raw(&f->objects[1])&&!l.owns_object_raw(&f->objects[2])&&!l.owns_object_raw(nullptr));assert(l.object_at(0)==&f->objects[0]&&l.role_at(0)==Role::profile&&l.native_at(0)==100);assert(l.object_at(1)==&f->objects[1]&&l.role_at(1)==Role::dof&&l.native_at(1)==101);assert(l.release()); END
 CASE(invalidaccessor) configure(l);assert(!l.object_at(0)&&l.native_at(0)==0&&static_cast<uint32_t>(l.role_at(0))==0);assert(l.release()); END
 CASE(abandonedaccessor) configure(l);object(l,0,1,Role::profile);l.abandon();f->source=false;int n=f->reads;assert(l.owns_object_raw(&f->objects[0])&&f->reads==n);assert(l.object_at(0)==&f->objects[0]&&l.role_at(0)==Role::profile);assert(l.release());assert(!l.owns_object_raw(&f->objects[0])); END
 CASE(lostrootaccessor) configure(l);object(l,0,1,Role::profile);f->roots[1]=nullptr;assert(l.owns_object_raw(&f->objects[0])&&!l.object_at(0));assert(!l.release()); END
 CASE(releasedaccessor) configure(l);object(l,0,1,Role::profile);assert(l.release());assert(l.count()==0&&!l.object_at(0)&&!l.owns_object_raw(&f->objects[0])&&static_cast<uint32_t>(l.role_at(0))==0); END
 std::printf("%d Focus native factory ledger cases passed\n",count);
}
