#include "mp4_actor_state.hpp"
#include <cassert>
#include <string>
#include <vector>
using namespace idoly_mp4_actor;
struct Header{uintptr_t data=0;int32_t length=1,capacity=1;};
struct Fixture{
 alignas(16) uint8_t component[2048]{},job[4096]{};Header headers[16]{};
 std::vector<uint8_t> buffers[16];FixedJobOwner owner{};bool current=true,fenced=true;
};
Fixture* f=nullptr;
bool mapped(const void* p,size_t n,bool){const uintptr_t a=reinterpret_cast<uintptr_t>(p);
 for(auto pair:{std::pair<const void*,size_t>{f->component,sizeof f->component},{f->job,sizeof f->job},{f->headers,sizeof f->headers}}){const uintptr_t b=reinterpret_cast<uintptr_t>(pair.first);if(a>=b&&a-b<=pair.second&&n<=pair.second-(a-b))return true;}
 for(auto& b:f->buffers){const uintptr_t at=reinterpret_cast<uintptr_t>(b.data());if(a>=at&&a-at<=b.size()&&n<=b.size()-(a-at))return true;}return false;}
bool current(void* p,const FixedJobOwner& o){return p==f&&f->current&&o.component==f->owner.component&&o.job==f->owner.job&&o.schema==f->owner.schema&&o.playable.handle==f->owner.playable.handle&&o.playable.version==f->owner.playable.version&&o.graph.handle==f->owner.graph.handle&&o.graph.version==f->owner.graph.version&&o.animator==f->owner.animator;}
bool fenced(void* p,const FixedJobOwner& o){assert(p==f&&o.job==f->job);return f->fenced;}
void setup(const ActorFixedJobSchema& s){f->owner={f->component,f->job,&s,{1,2,0},{3,4,0},f->component};
 for(size_t i=0;i<s.container_count;++i){const auto& c=s.containers[i];f->buffers[i].assign(c.stride,0x31);void* data=f->buffers[i].data();
  if(c.list){f->headers[i].data=reinterpret_cast<uintptr_t>(data);void* h=&f->headers[i];std::memcpy(f->job+c.offset,&h,8);}
  else{std::memcpy(f->job+c.offset,&data,8);int32_t length=1;std::memcpy(f->job+c.offset+8,&length,4);}
  std::memcpy(f->component+c.component_offset,f->job+c.offset,16);
 }
 for(size_t i=0;i<s.history_count;++i){const float value=float(1+i);std::memcpy(f->job+s.history[i].offset,&value,4);}
 for(size_t i=0;i<s.scratch_count;++i){const auto& r=s.scratch[i];for(size_t at=0;at<r.bytes;at+=4){const float value=2.5f;std::memcpy(f->job+r.offset+at,&value,4);}}
}
int main(int argc,char**argv){assert(argc==4);const bool ios=std::string(argv[1])=="ios";const size_t index=std::stoul(argv[2]);assert(index<5);const auto& schema=(ios?ios_fixed_job_schemas:android_fixed_job_schemas)[index];const std::string scenario=argv[3];Fixture fixture;f=&fixture;setup(schema);FixedJobSnapshot snapshot;
 if(scenario=="no_fence"){f->fenced=false;assert(snapshot.capture({mapped,current,fenced},f,f->owner)==Result::waiting);return 0;}
 if(scenario=="budget"){assert(snapshot.capture({mapped,current,fenced},f,f->owner,1)==Result::failed);return 0;}
 assert(snapshot.capture({mapped,current,fenced},f,f->owner)==Result::ok);
 for(size_t i=0;i<schema.cache_count;++i)std::memset(f->job+schema.caches[i].offset,0x77,schema.caches[i].bytes);
 for(size_t c=0;c<schema.container_count;++c)for(size_t i=0;i<schema.containers[c].cache_count;++i)std::memset(f->buffers[c].data()+schema.containers[c].caches[i].offset,0x78,schema.containers[c].caches[i].bytes);
 assert(snapshot.validate()==Result::ok);
 if(scenario=="owner_lost"){f->current=false;assert(snapshot.restore()==Result::stale);return 0;}
 if(scenario=="graph_generation"){++f->owner.graph.version;assert(snapshot.restore()==Result::stale);return 0;}
 if(scenario=="job_generation"){++f->owner.playable.version;assert(snapshot.restore()==Result::stale);return 0;}
 if(scenario=="job_configuration"){size_t at=0;for(;at<schema.bytes;++at){bool excluded=false;for(size_t j=0;j<schema.cache_count;++j)excluded|=at>=schema.caches[j].offset&&at<schema.caches[j].offset+schema.caches[j].bytes;for(size_t j=0;j<schema.scratch_count;++j)excluded|=at>=schema.scratch[j].offset&&at<schema.scratch[j].offset+schema.scratch[j].bytes;for(size_t j=0;j<schema.history_count;++j)excluded|=at>=schema.history[j].offset&&at<schema.history[j].offset+schema.history[j].bytes;if(!excluded)break;}assert(at<schema.bytes);f->job[at]^=1;assert(snapshot.restore()==Result::stale);return 0;}
 if(scenario=="row_binding"&&schema.container_count){const auto& c=schema.containers[0];size_t at=0;for(;at<c.stride;++at){bool excluded=false;for(size_t j=0;j<c.cache_count;++j)excluded|=at>=c.caches[j].offset&&at<c.caches[j].offset+c.caches[j].bytes;if(!excluded)break;}f->buffers[0][at]^=1;assert(snapshot.restore()==Result::stale);return 0;}
 if(scenario=="mirror_changed"&&schema.container_count){f->component[schema.containers[0].component_offset]^=1;assert(snapshot.restore()==Result::stale);return 0;}
 if(scenario=="history"){assert(snapshot.reset_history()==Result::ok);for(size_t i=0;i<schema.history_count;++i){float value=1;std::memcpy(&value,f->job+schema.history[i].offset,4);assert(value==0);value=9;std::memcpy(f->job+schema.history[i].offset,&value,4);}for(size_t i=0;i<schema.scratch_count;++i)std::memset(f->job+schema.scratch[i].offset,0x79,schema.scratch[i].bytes);}
 assert(snapshot.restore()==Result::ok);for(size_t i=0;i<schema.history_count;++i){float value=0;std::memcpy(&value,f->job+schema.history[i].offset,4);assert(value==float(i+1));}
 for(size_t i=0;i<schema.scratch_count;++i){float value=0;std::memcpy(&value,f->job+schema.scratch[i].offset,4);assert(value==2.5f);}
 for(size_t i=0;i<schema.cache_count;++i)for(size_t j=0;j<schema.caches[i].bytes;++j)assert(f->job[schema.caches[i].offset+j]==0x77);
 for(size_t c=0;c<schema.container_count;++c)for(size_t i=0;i<schema.containers[c].cache_count;++i)for(size_t j=0;j<schema.containers[c].caches[i].bytes;++j)assert(f->buffers[c][schema.containers[c].caches[i].offset+j]==0x78);
 snapshot.clear();assert(!snapshot.captured());return 0;}
