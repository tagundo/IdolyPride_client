#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cassert>
#include <stdexcept>
#include <string>
#include "shipping-gate.inc"
using namespace idoly_mp4_native_audio_output;
struct F {bool source=true,thread=true,pre=true,post=true;int calls=0,before=0,after=0;uintptr_t seen[8]{};size_t n=0;bool throw_call=false,handoff=false;Route routes[8]{};Gate gate;};static F*f;
bool current(void*,uint64_t e){return f->source&&e==11;}bool thread(){return f->thread;}bool mapped(const void*p,size_t){return p!=nullptr;}Route route(void*,uintptr_t p){return p<8?f->routes[p]:Route::reject;}
bool before(void*,const uintptr_t*p,size_t n){++f->before;assert(n&&p[0]==3);return f->pre;}bool after(void*,const uintptr_t*p,size_t n){++f->after;assert(n&&p[0]==3);return f->post;}
void original(void*p){++f->calls;if(p){auto*v=static_cast<VectorView*>(p);f->n=v->count;assert(v->opaque8==77&&v->opaque24==99);for(size_t i=0;i<v->count;++i)f->seen[i]=reinterpret_cast<uintptr_t*>(v->data)[i];}if(f->handoff){f->gate.abandon();f->source=false;}if(f->throw_call)throw std::runtime_error("original");}
int main(int argc,char**argv){assert(argc==2);const std::string c=argv[1];F fixture;f=&fixture;f->routes[1]=Route::unrelated;f->routes[2]=Route::private_silent;f->routes[3]=Route::source_restore;f->routes[4]=Route::reject;
 uintptr_t entries[]={1,2,3};VectorView v{reinterpret_cast<uintptr_t>(entries),77,3,99};Api api{current,thread,mapped,route,before,after};
 if(c=="ordinary"){assert(f->gate.invoke(original,nullptr)&&f->calls==1);return 0;}
 assert(f->gate.configure(api,f,11));
 if(c=="mixed"){assert(f->gate.invoke(original,&v));assert(f->calls==1&&f->n==2&&f->seen[0]==1&&f->seen[1]==3&&f->before==1&&f->after==1);}
 else if(c=="private"){v.data=reinterpret_cast<uintptr_t>(entries+1);v.count=1;assert(f->gate.invoke(original,&v)&&!f->calls);}
 else if(c=="unrelated"){v.count=1;assert(f->gate.invoke(original,&v)&&f->calls==1&&f->seen[0]==1&&!f->before);}
 else if(c=="restore"){v.data=reinterpret_cast<uintptr_t>(entries+2);v.count=1;assert(f->gate.invoke(original,&v)&&f->calls==1&&f->before==1&&f->after==1);}
 else if(c=="empty"){v.count=0;v.data=0;assert(f->gate.invoke(original,&v)&&f->calls==1&&!f->n);}
 else if(c=="bounds"){v.count=513;assert(!f->gate.invoke(original,&v)&&!f->calls);}
 else if(c=="null_data"){v.data=0;assert(!f->gate.invoke(original,&v)&&!f->calls);}
 else if(c=="null_vector"){assert(!f->gate.invoke(original,nullptr)&&!f->calls);}
 else if(c=="null_entry"){entries[1]=0;assert(!f->gate.invoke(original,&v)&&!f->calls);}
 else if(c=="duplicate"){entries[1]=1;assert(!f->gate.invoke(original,&v)&&!f->calls);}
 else if(c=="reject"){entries[1]=4;assert(!f->gate.invoke(original,&v)&&!f->calls);}
 else if(c=="bad_route"){f->routes[2]=static_cast<Route>(77);assert(!f->gate.invoke(original,&v)&&!f->calls);}
 else if(c=="pre"){f->pre=false;assert(!f->gate.invoke(original,&v)&&!f->calls&&!f->after);}
 else if(c=="post"){f->post=false;assert(!f->gate.invoke(original,&v)&&f->calls==1&&f->after==1);}
 else if(c=="source"){f->source=false;assert(!f->gate.invoke(original,&v)&&!f->calls);}
 else if(c=="thread"){f->thread=false;assert(!f->gate.invoke(original,&v)&&!f->calls);}
 else if(c=="abandon"){f->gate.abandon();assert(f->gate.invoke(original,&v)&&f->calls==1);}
 else if(c=="handoff"){f->handoff=true;assert(!f->gate.invoke(original,&v)&&f->calls==1&&!f->after);}
 else if(c=="exception"){f->throw_call=true;try{f->gate.invoke(original,&v);assert(false);}catch(const std::runtime_error&){}assert(f->calls==1&&!f->after&&!f->gate.current());assert(f->gate.release());}
 else if(c=="release"){assert(f->gate.release());assert(f->gate.invoke(original,&v)&&f->calls==1);}
 else if(c=="outcome_pre"){bool invoked=true;f->pre=false;assert(!f->gate.invoke(original,&v,&invoked)&&!invoked&&!f->calls);f->gate.abandon();assert(f->gate.invoke(original,&v,&invoked)&&invoked&&f->calls==1);}
 else if(c=="outcome_post"){bool invoked=false;f->post=false;assert(!f->gate.invoke(original,&v,&invoked)&&invoked&&f->calls==1);}
 else if(c=="outcome_private"){bool invoked=true;v.data=reinterpret_cast<uintptr_t>(entries+1);v.count=1;assert(f->gate.invoke(original,&v,&invoked)&&!invoked&&!f->calls);}
 else if(c=="outcome_throw"){bool invoked=false;f->throw_call=true;try{f->gate.invoke(original,&v,&invoked);assert(false);}catch(const std::runtime_error&){}assert(invoked&&f->calls==1);}
 else if(c=="original_missing"){assert(!f->gate.invoke(nullptr,&v));}
 else assert(false);
}
