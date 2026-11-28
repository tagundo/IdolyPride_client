#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <cassert>
#include "history.hpp"
namespace mp4rh=mp4_root_history;
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace idoly_mp4_actor_placement{struct Address{void*value;};}void*operator new(size_t,idoly_mp4_actor_placement::Address a)noexcept{return a.value;}
struct Mp4TimelineContext{mp4actor::Handle root{2,2,0},nodes[8]{{2,2,0},{4,2,0},{6,2,0},{8,2,0}};size_t node_count=4;};
struct Model{int mode=0;bool current=true;unsigned calls=0;}model;
bool mp4_timeline_current(const Mp4TimelineContext&){return model.current;}
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;}
int mp4_timeline_node_index(const Mp4TimelineContext&c,mp4actor::Handle a){for(size_t i=0;i<c.node_count;++i)if(mp4_actor_same_handle(c.nodes[i],a))return int(i);return -1;}
int32_t count(mp4actor::Handle*h,void*){++model.calls;if(model.mode==5)return 257;if(model.mode==6)return -1;if(h->handle==2)return model.mode==3?2:1;if(h->handle==4)return model.mode==4?2:1;return model.mode==7&&h->handle==6?1:0;}
void input(mp4actor::Handle*h,int32_t i,mp4actor::Handle*out,void*){if(model.mode==8)model.current=false;if(model.mode==9){*out={0,2,0};return;}if(model.mode==10){*out={10,2,0};return;}if(model.mode==7&&h->handle==6){*out={2,2,0};return;}if(h->handle==2)*out={4,2,0};else if(h->handle==4)*out={i==1?8u:6u,2,0};else*out={};}
struct Api{decltype(&count)playable_input_count=count;decltype(&input)playable_input=input;};Api mp4_actor_state_api(){return {};}
