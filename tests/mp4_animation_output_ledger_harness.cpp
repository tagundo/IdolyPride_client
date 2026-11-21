#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cmath>
#include <cassert>
#include <string>
#include "mp4-animation-output-witness.hpp.inc"
#include "mp4-animation-output-ledger.hpp.inc"
using namespace idoly_mp4_animation_output;
struct F{Record rows[4]{};size_t count=3;uint64_t epoch=11;bool source=true,thread=true,held=true;int collects=0,guards=0;};static F*f;
bool source(void*,uint64_t e){++f->guards;return f->source&&e==f->epoch;}bool thread(){return f->thread;}bool held(void*){return f->held;}bool collect(void*,Record*out,size_t cap,size_t*n,uint64_t*e){++f->collects;*n=f->count;*e=f->epoch;for(size_t i=0;i<f->count&&i<cap;++i)out[i]=f->rows[i];return true;}
int main(int argc,char**argv){assert(argc==2);F fixture;f=&fixture;for(size_t i=0;i<3;++i){auto&r=f->rows[i];r.owner={reinterpret_cast<void*>(i==2?2:1),reinterpret_cast<void*>(i==2?4:3),{uintptr_t(5+(i==2)),2,0},{10+i,2,0}};r.view.graph=r.owner.graph;r.view.output=r.owner.output;r.view.source={20+i,2,0};r.view.native_graph=30+(i==2);r.view.native_output=40+i;r.view.native_target=50+(i==2);r.view.native_source=60+i;r.view.weight=1;r.view.stream=1;}
 Ledger ledger;assert(ledger.bind({source,thread,held,collect},f));std::string c=argv[1];
 if(c=="idle"){assert(ledger.inspect(30,41)&&!ledger.captured()&&!ledger.current());return 0;}
 if(c=="idle_unknown"){assert(!ledger.inspect(30,99)&&!ledger.captured());return 0;}
 if(c=="notheld"){f->held=false;assert(!ledger.capture());return 0;}
 assert(ledger.capture()&&ledger.captured()&&ledger.current());bool expected=false;
 if(c=="stable")expected=true;
 else if(c=="second_output")f->rows[1].view.weight=0.5f;
 else if(c=="third_actor")f->rows[2].view.sorting=2;
 else if(c=="add")f->count=4;
 else if(c=="remove")f->count=2;
 else if(c=="reorder"){auto r=f->rows[0];f->rows[0]=f->rows[1];f->rows[1]=r;}
 else if(c=="duplicate")f->rows[1]=f->rows[0];
 else if(c=="source")f->source=false;
 else if(c=="epoch")f->epoch=12;
 else if(c=="thread")f->thread=false;
 else if(c=="release"){const int n=f->collects,g=f->guards;f->source=false;ledger.release();assert(!ledger.captured()&&f->collects==n&&f->guards==g);return 0;}
 else if(c=="recapture"){assert(ledger.capture());expected=true;}
 else if(c=="target")f->rows[1].view.native_target=999;
 else if(c=="unknown")assert(!ledger.inspect(30,999));
 else assert(false);
 assert(ledger.current()==expected);
}
