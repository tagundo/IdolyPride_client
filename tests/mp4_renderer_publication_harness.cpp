#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <unordered_map>
#include "client-presentation/native/mp4_camera_owner.hpp"
using namespace idoly_mp4_camera_state;
struct Host {
    RendererPublication publication;bool source=true,ready=true,fence=true,throw_getter=false;
    unsigned source_calls=0,ready_calls=0,getter_calls=0,release_calls=0,retain_calls=0,fail_root=0;
    int additional=0,original=0,replacement=0,foreign=0;void* getter_result=&original;
    std::unordered_map<uint32_t,void*> roots;uint32_t next=1;
};
Host* handles=nullptr;
uint32_t retain(void* object){auto& h=*handles;if(++h.retain_calls==h.fail_root)return 0;const auto id=h.next++;h.roots[id]=object;return id;}
void* target(uint32_t id){auto& h=*handles;auto at=h.roots.find(id);return at==h.roots.end()?nullptr:at->second;}
void drop(uint32_t id){auto& h=*handles;assert(h.roots.erase(id)==1);++h.release_calls;}
RendererPublicationApi api(){RendererPublicationApi a{};
 a.source_current=[](void* p){auto& h=*static_cast<Host*>(p);++h.source_calls;return h.source;};
 a.private_ready=[](void* p){auto& h=*static_cast<Host*>(p);++h.ready_calls;return h.ready;};
 a.original_renderer=[](void* p,void* additional)->void*{auto& h=*static_cast<Host*>(p);assert(additional==&h.additional);++h.getter_calls;if(h.throw_getter)throw std::runtime_error("original getter");return h.getter_result;};
 a.cleanup_ready=[](void* p){return static_cast<Host*>(p)->fence;};a.retain=retain;a.target=target;a.release=drop;return a;}
void configure(Host& h,uint64_t generation=1){handles=&h;assert(h.publication.configure(api(),&h,&h.additional,&h.original,&h.replacement,generation)==Result::ok);assert(h.roots.size()==3);}
int main(){
 {Host h;configure(h);assert(h.publication.publish()==Result::ok);assert(h.getter_calls==1);auto r=h.publication.resolve(&h.additional);assert(r.kind==RendererResolve::owned&&r.renderer==&h.replacement&&r.original_called);assert(h.getter_calls==2);const auto calls=h.source_calls;assert(h.publication.resolve(&h.foreign).kind==RendererResolve::forward);assert(h.source_calls==calls&&h.getter_calls==2);assert(h.publication.release(true)==Result::ok&&h.roots.empty());}
 {Host h;configure(h);assert(h.publication.publish()==Result::ok);h.getter_result=&h.foreign;auto r=h.publication.resolve(&h.additional);assert(r.kind==RendererResolve::error&&r.renderer==&h.foreign&&r.original_called);assert(h.getter_calls==2&&!h.publication.published());assert(h.publication.release(false)==Result::ok);}
 {Host h;configure(h);assert(h.publication.publish()==Result::ok);h.getter_result=nullptr;auto r=h.publication.resolve(&h.additional);assert(r.kind==RendererResolve::error&&!r.renderer&&r.original_called);assert(h.getter_calls==2);assert(h.publication.release(false)==Result::ok);}
 {Host h;configure(h);assert(h.publication.publish()==Result::ok);h.source=false;auto r=h.publication.resolve(&h.additional);assert(r.kind==RendererResolve::error&&!r.original_called&&h.getter_calls==1);const auto calls=h.source_calls;assert(h.publication.release(false)==Result::ok&&h.roots.empty());assert(h.source_calls==calls);}
 {Host h;configure(h);assert(h.publication.publish()==Result::ok);const auto token=h.publication.begin_draw(&h.replacement);assert(token&&h.publication.readers()==1);h.publication.before_source_change();h.source=false;const auto calls=h.source_calls;const auto ready=h.ready_calls;assert(h.publication.resolve(&h.additional).kind==RendererResolve::forward);assert(h.publication.release(false)==Result::waiting&&h.roots.size()==3);assert(h.publication.end_draw(token));assert(!h.publication.end_draw(token));assert(h.publication.release(false)==Result::ok&&h.roots.empty());assert(h.source_calls==calls&&h.ready_calls==ready);}
 {Host h;configure(h);assert(h.publication.publish()==Result::ok);h.fence=false;assert(h.publication.release(false)==Result::waiting&&h.roots.size()==3&&!h.publication.published());h.source=false;const auto calls=h.source_calls;h.fence=true;assert(h.publication.release(false)==Result::ok&&h.roots.empty()&&h.source_calls==calls);}
 {Host h;configure(h);assert(h.publication.publish()==Result::ok);h.throw_getter=true;bool threw=false;try{(void)h.publication.resolve(&h.additional);}catch(const std::runtime_error&){threw=true;}assert(threw&&h.getter_calls==2&&!h.publication.published());assert(h.publication.release(false)==Result::ok);}
 {Host h;handles=&h;h.fail_root=2;assert(h.publication.configure(api(),&h,&h.additional,&h.original,&h.replacement,1)==Result::failed);assert(h.roots.size()==1);h.source=false;assert(h.publication.release(false)==Result::ok&&h.roots.empty()&&h.release_calls==1);}
 {Host h;configure(h);assert(h.publication.publish()==Result::ok);uint64_t tokens[16]{};for(auto& token:tokens){token=h.publication.begin_draw(&h.replacement);assert(token);}assert(!h.publication.begin_draw(&h.replacement));assert(h.publication.release(false)==Result::waiting);for(auto token:tokens)assert(h.publication.end_draw(token));assert(h.publication.release(false)==Result::ok);}
 {Host h;configure(h);assert(h.publication.publish()==Result::ok);const auto old=h.publication.begin_draw(&h.replacement);assert(old&&h.publication.end_draw(old));assert(h.publication.release(false)==Result::ok);configure(h,2);assert(h.publication.generation()==2&&h.publication.publish()==Result::ok);const auto fresh=h.publication.begin_draw(&h.replacement);assert(fresh&&fresh!=old&&!h.publication.end_draw(old));assert(h.publication.end_draw(fresh)&&h.publication.release(false)==Result::ok);}
 {Host h;configure(h);h.ready=false;assert(h.publication.publish()==Result::stale&&!h.publication.published());assert(h.publication.release(false)==Result::ok);}
}
