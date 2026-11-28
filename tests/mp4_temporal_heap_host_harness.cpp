#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <new>
struct Mp4TemporalHost {uint64_t epoch=0;unsigned depth=0;int layout=7;int cached_index=-1;float weights[3]{1,1,1};const char*error="temporal_not_bound";};
namespace idoly_mp4_actor_placement{struct Address{void*value;};}
void*operator new(size_t,idoly_mp4_actor_placement::Address a)noexcept{return a.value;}
bool on_thread=true,oom=false;int allocations=0;
bool game_call(){return on_thread;}
void*test_malloc(size_t bytes){assert(bytes==sizeof(Mp4TemporalHost));++allocations;return oom?nullptr:std::malloc(bytes);}
#define malloc test_malloc
// SHIPPING_TEMPORAL_HEAP_HOST
#undef malloc
int main(int argc,char**argv){assert(argc==2);int c=std::atoi(argv[1]);
    for(auto*p:mp4_temporal_hosts)assert(!p);assert(allocations==0);
    if(c==0){auto*p=mp4_temporal_host_slot(0);assert(p&&p->epoch==0&&p->layout==7&&p->cached_index==-1&&p->weights[2]==1);assert(mp4_temporal_host_slot(0)==p&&allocations==1);}
    else if(c==1){assert(!mp4_temporal_host_slot(32)&&!mp4_temporal_host_slot(~size_t(0))&&allocations==0);}
    else if(c==2){on_thread=false;assert(!mp4_temporal_host_slot(0)&&allocations==0);}
    else if(c==3){oom=true;assert(!mp4_temporal_host_slot(0)&&!mp4_temporal_hosts[0]);oom=false;assert(mp4_temporal_host_slot(0)&&allocations==2);}
    else if(c==4){auto*a=mp4_temporal_host_slot(0);auto*b=mp4_temporal_host_slot(31);assert(a!=b&&a&&b&&allocations==2);a->epoch=91;assert(b->epoch==0);}
    else if(c==5){auto*p=mp4_temporal_host_slot(0);p->epoch=17;p->layout=99;*p={};assert(mp4_temporal_host_slot(0)==p&&p->epoch==0&&p->layout==7&&p->weights[2]==1&&allocations==1);}
    else if(c==6){auto*p=mp4_temporal_host_slot(0);on_thread=false;assert(!mp4_temporal_host_slot(0)&&mp4_temporal_hosts[0]==p&&allocations==1);}
    else return 2;
}
