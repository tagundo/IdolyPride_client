#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cstddef>
#include <cassert>
#include <string>
#include "mp4_actor_state.hpp"
using namespace idoly_mp4_actor;
struct List{uintptr_t data;int32_t length=2,capacity=2;};
struct Fixture{
 alignas(8) uint8_t job[96]{};
 List header[2]{};
 alignas(8) uint8_t blends[48]{},talks[40]{},other[48]{};
 bool current=true,fenced=true;unsigned owners=0;unsigned lose_at=0;
};
Fixture* f;
bool mapped(const void* p,size_t n,bool){const auto a=reinterpret_cast<uintptr_t>(p),b=reinterpret_cast<uintptr_t>(f);return a>=b&&a-b<=sizeof(*f)&&n<=sizeof(*f)-(a-b);}
bool current(void* p,const void* job){assert(p==f&&job==f->job);++f->owners;return f->current&&(!f->lose_at||f->owners!=f->lose_at);}
bool fence(void* p,const void* job){assert(p==f&&job==f->job);return f->fenced;}
template<class T>void set(void* p,size_t at,T v){::memcpy(static_cast<uint8_t*>(p)+at,&v,sizeof v);}
template<class T>T get(void* p,size_t at){T v{};::memcpy(&v,static_cast<uint8_t*>(p)+at,sizeof v);return v;}
int main(int argc,char**argv){
 assert(argc==2);const std::string s=argv[1];Fixture fx;f=&fx;TalkJobSnapshot snap;
 fx.header[0].data=reinterpret_cast<uintptr_t>(fx.blends);fx.header[1].data=reinterpret_cast<uintptr_t>(fx.talks);
 for(size_t k=0;k<2;++k){set(fx.job,k*16,reinterpret_cast<uintptr_t>(&fx.header[k]));
  set(fx.blends,k*24+4,int32_t(8+k));set(fx.blends,k*24+12,int32_t(6));set(fx.blends,k*24+16,.3f);set(fx.blends,k*24+20,.7f);
  set(fx.talks,k*20,2.f);set(fx.talks,k*20+4,int32_t(3+k));set(fx.talks,k*20+8,.4f);set(fx.talks,k*20+12,int32_t(1));set(fx.talks,k*20+16,int32_t(4));}
 set(fx.job,80,.6f);set(fx.job,84,int32_t(5));set(fx.job,88,uint8_t(1));set(fx.job,92,3.f);
 if(s=="zero"){for(auto& h:fx.header){h.data=0;h.length=h.capacity=0;}}
 if(s=="unfenced_capture"){fx.fenced=false;assert(snap.capture({mapped,current,fence},f,fx.job)==Result::waiting);return 0;}
 if(s=="missing_api"){assert(snap.capture({mapped,current,nullptr},f,fx.job)==Result::invalid);return 0;}
 if(s=="invalid_scalar"){set(fx.job,88,uint8_t(2));assert(snap.capture({mapped,current,fence},f,fx.job)==Result::invalid);return 0;}
 if(s=="capacity_bound"){fx.header[0].capacity=9000;assert(snap.capture({mapped,current,fence},f,fx.job)==Result::stale);return 0;}
 assert(snap.capture({mapped,current,fence},f,fx.job)==Result::ok);
 set(fx.job,80,.9f);set(fx.job,84,int32_t(8));set(fx.job,88,uint8_t(0));set(fx.job,92,10.f);
 for(size_t k=0;k<2;++k){set(fx.blends,k*24,int32_t(99));set(fx.blends,k*24+8,int32_t(42));set(fx.blends,k*24+16,8.f);set(fx.blends,k*24+20,9.f);set(fx.talks,k*20,7.f);set(fx.talks,k*20+8,6.f);}
 if(s=="fence_wait"){fx.fenced=false;assert(snap.restore()==Result::waiting&&get<float>(fx.job,92)==10.f);fx.fenced=true;}
 if(s=="owner_lost")fx.current=false;
 if(s=="owner_handoff")fx.lose_at=fx.owners+3;
 if(s=="list_changed")fx.header[0].data=reinterpret_cast<uintptr_t>(fx.other);
 if(s=="length_changed")fx.header[0].length=1;
 if(s=="capacity_changed")fx.header[0].capacity=3;
 if(s=="handle_changed")set(fx.blends,4,int32_t(100));
 if(s=="bind_type_changed")set(fx.blends,12,int32_t(100));
 if(s=="voice_changed")set(fx.talks,4,int32_t(100));
 if(s=="curve_changed")set(fx.talks,12,int32_t(100));
 if(s=="prefix_changed")set(fx.job,72,uintptr_t(100));
 const bool rejected=s=="owner_lost"||s=="owner_handoff"||s=="list_changed"||s=="length_changed"||s=="capacity_changed"||s=="handle_changed"||s=="bind_type_changed"||s=="voice_changed"||s=="curve_changed"||s=="prefix_changed";
 if(rejected){assert(snap.restore()==Result::stale&&!snap.restored()&&get<float>(fx.job,92)==10.f);return 0;}
 assert(snap.restore()==Result::ok&&snap.restored());assert(get<float>(fx.job,80)==.6f&&get<float>(fx.job,92)==3.f&&get<uint8_t>(fx.job,88)==1&&get<int32_t>(fx.job,84)==5);
 if(s!="zero")for(size_t k=0;k<2;++k){assert(get<int32_t>(fx.blends,k*24)==99&&get<int32_t>(fx.blends,k*24+8)==42);assert(get<float>(fx.blends,k*24+16)==.3f&&get<float>(fx.blends,k*24+20)==.7f);assert(get<float>(fx.talks,k*20)==2.f&&get<float>(fx.talks,k*20+8)==.4f);}
 assert(snap.restore()==Result::ok);snap.clear();assert(!snap.captured());
}
