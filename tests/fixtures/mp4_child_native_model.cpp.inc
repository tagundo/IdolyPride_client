// Exact shared typed wrappers against explicit modeled original services.
#define Host ModelHost
#define main journal_fixture_main
#include "mp4_child_journal_model.cpp.inc"
#undef main
#undef Host
#include "native-host.hpp"
static ModelHost*model=nullptr;static mp4_director_maintenance::Host*host=nullptr;
static unsigned enqueues=0,appends[2]{},collects=0,resets=0,deferred_calls[2]{},quarantines=0;static bool published=true;
static unsigned index(const world::AnimationGraph*h){return h->handle==ModelHost::ptr(model->slots[1])?1:0;}
static void enqueue_original(void*,uint32_t op,const world::AnimationGraph*h){++enqueues;model->push(index(h),op,h->version);}
static void append_a_original(void*,const world::AnimationGraph*h){++appends[0];model->append(index(h),0,false,h->version);}
static void append_b_original(void*,const world::AnimationGraph*h){++appends[1];model->append(index(h),1,false,h->version);}
static void collect_original(void*temporary,void*){++collects;uintptr_t at=ModelHost::get<uintptr_t>(model->queue,0);size_t n=0;while(at){auto*p=reinterpret_cast<void*>(at);ModelHost::put(model->data,n*24,ModelHost::get<uintptr_t>(p,8));ModelHost::put(model->data,n*24+8,ModelHost::get<uint32_t>(p,16));ModelHost::put(model->data,n*24+16,ModelHost::get<uint32_t>(p,24));at=ModelHost::get<uintptr_t>(p,0);++n;}ModelHost::put(temporary,0,ModelHost::ptr(model->data));ModelHost::put(temporary,16,uint64_t(n));ModelHost::put(temporary,24,uint64_t(64));ModelHost::put(model->queue,0,uintptr_t(0));}
static void reset_original(void*temporary){++resets;ModelHost::put(temporary,0,uintptr_t(0));ModelHost::put(temporary,16,uint64_t(0));}
static void deferred_a_original(void*){++deferred_calls[0];ModelHost::put(model->manager,0x398,uint64_t(0));}
static void deferred_b_original(void*){++deferred_calls[1];ModelHost::put(model->manager,0x3b8,uint64_t(0));}
static bool begin(Kind kind){Call c{kind,7,++model->serial,0xabc,0x55,0x66,kind==Kind::rebuild?1000+model->serial:0};return host->journal().begin(c)&&host->journal().invoked();}
static bool setup(ModelHost&m,mp4_director_maintenance::Host&h){model=&m;host=&h;auto api=m.api();api.hook_origin=[](void*,Hook hook,uintptr_t r,const Call&){return host->native_entry(hook,r);};Originals original{enqueue_original,{append_a_original,append_b_original},collect_original,reset_original,{deferred_a_original,deferred_b_original}};HostApi services{};services.bindings_current=[](void*,const Originals&o){return published&&o.enqueue==enqueue_original&&o.collect==collect_original&&o.reset==reset_original;};services.quarantine=[](void*,const char*){++quarantines;};return h.configure(api,original,services);}
int main(int argc,char**argv){assert(argc==2);int mode=std::atoi(argv[1]);ModelHost m;mp4_director_maintenance::Host h;assert(setup(m,h));auto handle=m.handle();m.spans.push_back({&handle,sizeof handle});
 if(mode==0){h.enqueue(m.manager,0,&handle);h.append(0,m.manager,&handle);h.append(1,m.manager,&handle);h.collect(m.temporary,m.queue);h.deferred(0,m.manager);h.deferred(1,m.manager);assert(enqueues==1&&appends[0]==1&&appends[1]==1&&collects==1&&deferred_calls[0]==1&&deferred_calls[1]==1&&!quarantines&&!resets);return 0;}
 if(mode==1){assert(begin(Kind::play));h.enqueue(m.manager,0,&handle);assert(enqueues==1&&h.journal().end());DirectorAuthorization out{};assert(h.journal().authorization(m.pending(),out));return 0;}
 if(mode==2){assert(begin(Kind::maintenance));m.push(1,0);auto original=ModelHost::get<uintptr_t>(m.queue,0);h.collect(m.temporary,m.queue);assert(!collects&&resets==1&&quarantines==1&&ModelHost::get<uintptr_t>(m.queue,0)==original);return 0;}
 if(mode==3){assert(begin(Kind::maintenance));m.append(1,0);h.deferred(0,m.manager);assert(!deferred_calls[0]&&quarantines==1&&ModelHost::get<uint64_t>(m.manager,0x398)==1);return 0;}
 if(mode==4){assert(begin(Kind::rebuild));h.append(0,m.manager,&handle);h.append(1,m.manager,&handle);assert(h.journal().end());assert(begin(Kind::maintenance));h.deferred(1,m.manager);h.deferred(0,m.manager);assert(deferred_calls[0]==1&&deferred_calls[1]==1&&!quarantines&&h.journal().end());return 0;}
 if(mode==5){assert(begin(Kind::play));published=false;h.enqueue(m.manager,0,&handle);assert(enqueues==1&&quarantines==1);return 0;}
 if(mode==6){assert(begin(Kind::play));h.enqueue(m.manager,0,&handle);assert(h.journal().end());assert(begin(Kind::maintenance));h.collect(m.temporary,m.queue);assert(collects==1&&!resets&&!quarantines&&h.journal().end());return 0;}
 if(mode==8){mp4_director_maintenance::Host empty;assert(!empty.routes_current()&&!enqueues&&!collects&&!resets);return 0;}
 if(mode==9){assert(h.routes_current()&&!enqueues&&!collects&&!resets&&!quarantines);return 0;}
 if(mode==10){published=false;assert(!h.routes_current()&&!enqueues&&!collects&&!resets);return 0;}
 if(mode==11){m.current=false;assert(h.routes_current()&&!enqueues&&!collects&&!resets);return 0;}
 return 2;
}
