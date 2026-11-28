#include <cstdint>
#include <cstddef>
#include <cmath>
#include <cassert>
#include <stdexcept>
#include <cstdio>
#include "focus-extra-state-lease.inc"
using namespace idoly_mp4_focus_private;
struct Fixture{int ext=1,cam=2,target=3,old=4,priv=5,klass=6,ambient=7;void*field=&old;void*roots[64]{};uint32_t next=1;bool source=true,thread=true,held=true,detached=true,ctor_throw=false,wrong_class=false,retain_fail=false,set_false=false,set_throw=false;int gets=0,sets=0,ctors=0,drops=0,detaches=0;ExtraStateLease*lease=nullptr;};static Fixture*f;
bool current(void*,uint64_t e,const Owner&o){return f->source&&e==11&&o.extension==&f->ext&&o.camera==&f->cam&&o.native_extension==101&&o.offset==2;}
bool thread(){return f->thread;}bool held(void*){return f->held;}bool klass(void*,const Owner&,void**p){*p=&f->klass;return true;}void*get(void*){++f->gets;return f->field;}bool set(void*,void*expected,void*p){++f->sets;if(f->field!=expected||f->set_false)return false;f->field=p;if(f->set_throw)throw std::runtime_error("barrier");return true;}void*alloc(void*,void*){return &f->priv;}void ctor(void*,void*p){++f->ctors;assert(p==&f->priv);bool rooted=false;for(void*r:f->roots)if(r==p)rooted=true;assert(rooted);if(f->ctor_throw)throw std::runtime_error("ctor");}bool is(void*,void*p,void*k){return !f->wrong_class&&k==&f->klass&&(p==&f->old||p==&f->priv||p==&f->ambient);}uint32_t retain(void*p){if(f->retain_fail)return 0;uint32_t n=f->next++;assert(n<64);f->roots[n]=p;return n;}void*retained(uint32_t n){return f->roots[n];}void drop(uint32_t n){assert(f->roots[n]);f->roots[n]=nullptr;++f->drops;}bool detached(void*,const Owner&,void*p){++f->detaches;assert(p==&f->priv);return f->detached;}
ExtraApi api(){return {current,thread,held,klass,get,set,alloc,ctor,is,retain,retained,drop,detached};}
Owner owner(){return {&f->ext,&f->cam,&f->target,101,2};}
void capture(ExtraStateLease&l){assert(l.capture(api(),f,11,owner()));}void prepare(ExtraStateLease&l){capture(l);assert(l.prepare());assert(f->field==&f->priv&&l.current());}
void clean(ExtraStateLease&l){assert(l.restore_reference());assert(f->field==&f->old);assert(l.release());for(void*r:f->roots)assert(!r);}
int main(){int count=0;
#define CASE(name) {Fixture fixture;f=&fixture;ExtraStateLease l;f->lease=&l; ++count;
#define END }
 CASE(stable) prepare(l);clean(l); END
 CASE(nullbaseline) f->field=nullptr;prepare(l);assert(l.restore_reference()&&f->field==nullptr&&l.release()); END
 CASE(doubleprepare) prepare(l);assert(l.prepare()&&f->ctors==1);clean(l); END
 CASE(notheld) capture(l);f->held=false;assert(!l.prepare());assert(l.release()); END
 CASE(wrongthread) f->thread=false;assert(!l.capture(api(),f,11,owner())); END
 CASE(badclass) f->wrong_class=true;assert(!l.capture(api(),f,11,owner()));assert(l.release()); END
 CASE(retainfailure) f->retain_fail=true;assert(!l.capture(api(),f,11,owner()));assert(l.release()); END
 CASE(ctorfailure) capture(l);f->ctor_throw=true;try{l.prepare();assert(false);}catch(const std::runtime_error&){}assert(f->field==&f->old&&l.release()); END
 CASE(installfalse) capture(l);f->set_false=true;assert(!l.prepare());f->set_false=false;assert(l.restore_reference()&&l.release()); END
 CASE(installthrows) capture(l);f->set_throw=true;try{l.prepare();assert(false);}catch(const std::runtime_error&){}f->set_throw=false;assert(l.restore_reference()&&l.release()); END
 CASE(suspend) prepare(l);Suspension s;assert(l.suspend(s)&&f->field==&f->old&&!l.current());assert(l.resume(s)&&f->field==&f->priv);clean(l); END
 CASE(nested) prepare(l);Suspension a,b;assert(l.suspend(a)&&l.suspend(b));assert(l.resume(b)&&f->field==&f->old);assert(l.resume(a));clean(l); END
 CASE(adoptnewambient) prepare(l);Suspension s;assert(l.suspend(s));f->field=&f->ambient;assert(l.resume(s));assert(l.restore_reference()&&f->field==&f->ambient&&l.release()); END
 CASE(adoptnullambient) prepare(l);Suspension s;assert(l.suspend(s));f->field=nullptr;assert(l.resume(s));assert(l.restore_reference()&&f->field==nullptr&&l.release()); END
 CASE(outoforder) prepare(l);Suspension a,b;assert(l.suspend(a)&&l.suspend(b));int g=f->gets,s=f->sets;assert(!l.resume(a)&&l.abandoned());assert(f->gets==g&&f->sets==s&&l.release()); END
 CASE(handoffwhileheld) prepare(l);int g=f->gets,s=f->sets;f->source=false;l.abandon();assert(f->gets==g&&f->sets==s);assert(!l.restore_reference()&&l.release()); END
 CASE(handoffwhilesuspended) prepare(l);Suspension a;assert(l.suspend(a));f->field=&f->ambient;f->source=false;int g=f->gets,s=f->sets;l.abandon();assert(!l.resume(a));assert(f->gets==g&&f->sets==s&&f->field==&f->ambient&&l.release()); END
 CASE(publicationbusy) prepare(l);assert(l.restore_reference());f->detached=false;assert(!l.release());f->detached=true;assert(l.release()); END
 CASE(cannotreleaseinstalled) prepare(l);assert(!l.release());clean(l); END
 CASE(otherwriter) prepare(l);f->field=&f->ambient;assert(!l.restore_reference()&&!l.release());l.abandon();assert(l.release()); END
 CASE(staleowner) prepare(l);f->source=false;int s=f->sets;assert(!l.restore_reference()&&f->sets==s);l.abandon();assert(l.release()); END
 CASE(suspendthrows) prepare(l);Suspension s;f->set_throw=true;try{l.suspend(s);assert(false);}catch(const std::runtime_error&){}f->set_throw=false;l.abandon();assert(l.release()); END
 CASE(resumethrows) prepare(l);Suspension s;assert(l.suspend(s));f->set_throw=true;try{l.resume(s);assert(false);}catch(const std::runtime_error&){}f->set_throw=false;l.abandon();assert(l.release()); END
 CASE(nooprelease) assert(l.release()); END
 CASE(reuse) prepare(l);clean(l);capture(l);assert(l.prepare());clean(l); END
 CASE(sourcechangebeforeinstall) capture(l);f->source=false;int s=f->sets;assert(!l.prepare()&&f->sets==s);assert(l.release()); END
 CASE(changedbaseline) capture(l);f->field=&f->ambient;assert(!l.prepare());assert(l.release()); END
 CASE(ambientwrongclass) prepare(l);Suspension s;assert(l.suspend(s));f->wrong_class=true;assert(!l.resume(s)&&l.abandoned()&&l.release()); END
 CASE(retainambientfailure) prepare(l);Suspension s;assert(l.suspend(s));f->field=&f->ambient;f->retain_fail=true;assert(!l.resume(s)&&l.abandoned()&&l.release()); END
 CASE(suspendfalse) prepare(l);Suspension s;f->set_false=true;assert(!l.suspend(s));f->set_false=false;assert(l.restore_reference()&&l.release()); END
 CASE(restorefalse) prepare(l);f->set_false=true;assert(!l.restore_reference());f->set_false=false;assert(l.restore_reference()&&l.release()); END
 CASE(detachednotcalledpureabandon) prepare(l);int n=f->detaches;l.abandon();assert(f->detaches==n);assert(l.release()); END
 CASE(withdrawgrantedclock) prepare(l);f->held=false;assert(l.withdraw_before_source_change()&&f->field==&f->old&&l.abandoned());assert(l.release()); END
 CASE(withdrawempty) int g=f->gets,s=f->sets;assert(l.withdraw_before_source_change()&&f->gets==g&&f->sets==s&&l.release()); END
 CASE(withdrawunpublished) capture(l);int g=f->gets,s=f->sets;assert(l.withdraw_before_source_change()&&f->gets==g&&f->sets==s&&!l.prepare()&&l.release()); END
 CASE(withdrawsuspended) prepare(l);Suspension s;assert(l.suspend(s));f->field=&f->ambient;int n=f->sets;assert(l.withdraw_before_source_change()&&f->sets==n&&f->field==&f->ambient);assert(!l.resume(s)&&l.release()); END
 CASE(withdrawforeignwriter) prepare(l);f->field=&f->ambient;int n=f->sets;assert(!l.withdraw_before_source_change()&&f->sets==n);l.abandon();assert(l.release()); END
 CASE(withdrawstaleowner) prepare(l);f->source=false;int n=f->sets;assert(!l.withdraw_before_source_change()&&f->sets==n);l.abandon();assert(l.release()); END
 std::printf("%d Focus dictionary lease cases passed\n",count);
}
