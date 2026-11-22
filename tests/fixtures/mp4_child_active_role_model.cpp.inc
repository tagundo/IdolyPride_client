#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cassert>
#include <cstdlib>
#include <unordered_map>
#include <vector>
#include "mp4_engine_clock.hpp"
#include "pending-journal.hpp"
#include "birth-scope.hpp"
#include "source-origin.hpp"
#include "child-scope.hpp"
#include "director-node-scope.hpp"
namespace mp4dn=idoly_mp4_director_nodes;
struct Object{uint8_t memory[128]{};bool clip=false;};
struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};
struct Mp4TimelineList{void*owner=nullptr;size_t owner_offset=0,stride=8;int32_t count=0;uint8_t*data=nullptr;};
struct Mp4TimelineContext{void*root_script=nullptr;void*elements[3]{};size_t element_count=1;Handle runtime_playables[3]{};Mp4TimelineList lists[3]{};size_t list_count=2;};
bool current=true,lists_current=true;unsigned list_calls=0;int mode=0;
bool mp4_timeline_current(Mp4TimelineContext&){return current;}
bool mp4_timeline_lists_current(Mp4TimelineContext&){++list_calls;return lists_current&&!(mode==13&&list_calls==2);}
struct{int clip=1;}mp4_timeline_pins;
bool mp4_timeline_exact(void*p,int){return p&&static_cast<Object*>(p)->clip;}
template<class T>bool mp4_actor_field(void*p,size_t off,T&out){if(!p||off+sizeof(T)>128)return false;::memcpy(&out,static_cast<Object*>(p)->memory+off,sizeof(T));return true;}
template<class T>void set(Object&o,size_t off,T value){assert(off+sizeof(T)<=128);::memcpy(o.memory+off,&value,sizeof value);}
// ACTUAL_RUNTIME_ACTIVE
int main(int argc,char**argv){assert(argc==2);mode=atoi(argv[1]);Object root,element,tree;void*clip=(void*)0x101;set(root,16,static_cast<void*>(&tree));set(root,40,uint32_t(1));set(element,16,uint32_t(1));set(element,24,clip);element.clip=true;
 void*active[3]{&element,nullptr,nullptr};void*scratch[3]{&element,nullptr,nullptr};
 Mp4TimelineContext c{};c.root_script=&root;c.elements[0]=&element;c.runtime_playables[0]={0x201,2,0};c.lists[0]={&root,24,8,1,reinterpret_cast<uint8_t*>(active)};c.lists[1]={&root,32,8,1,reinterpret_cast<uint8_t*>(scratch)};
 mp4dn::Node node{};node.key.clip=clip;node.runtime={0x201,2,0};bool value=true;
 if(mode==1)set(root,16,static_cast<void*>(nullptr));
 if(mode==2)scratch[0]=&tree;
 if(mode==3)c.lists[1].stride=16;
 if(mode==4){c.lists[0].count=c.lists[1].count=2;active[1]=scratch[1]=&element;}
 if(mode==5)c.element_count=0;
 if(mode==6)++node.runtime.version;
 if(mode==7)set(root,40,uint32_t(2));
 if(mode==8)set(element,16,uint32_t(2));
 if(mode==9)node.key.clip=(void*)0x111;
 if(mode==10)current=false;
 if(mode==11)c.list_count=1;
 if(mode==12)c.lists[1].count=0;
 if(mode==14){c.lists[0].count=c.lists[1].count=0;}
 if(mode==15)set(element,16,uint32_t(0));
 if(mode==16){c.element_count=2;c.elements[1]=&element;c.runtime_playables[1]=c.runtime_playables[0];}
 if(mode==17)lists_current=false;
 if(mode==18)c.lists[0].count=c.lists[1].count=4097;
 if(mode==19){c.list_count=3;c.lists[2]=c.lists[0];}
 const bool ok=mp4_child_driving_runtime_active(c,node,&value);
 if(mode==0){assert(ok&&value);}else if(mode==14||mode==15){assert(ok&&!value);}else assert(!ok&&!value);
 assert(!mp4_child_driving_runtime_active(c,node,nullptr));
}
