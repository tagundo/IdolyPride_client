#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <unordered_map>
#include <stdexcept>
#include "cine-volume-producer.inc"
using namespace idoly_mp4_cine_volume_producer;
struct O {int type=0,layer=3;bool alive=true,registered=false,abandoned=false,detached=false;O* go=nullptr;void* shared=nullptr;void* internal=nullptr;float priority=1,weight=.4f;};
struct H {Scope scope;O brain{},asset{},go{1},volume{2},created_go{1},created_volume{2},foreign_go{1},foreign_volume{2};bool current=true,fail_restore=false,gpu=true;int touches=0,transfers=0,destroys=0,owner_queries=0;std::unordered_map<uint32_t,void*> roots;uint32_t next=1;H(){volume.go=&go;volume.registered=true;created_go.alive=false;created_volume.go=&created_go;foreign_volume.go=&foreign_go;}};
H* host=nullptr;
VolumeImage image(O& v){return {&v,v.go,v.shared,v.internal,v.priority,0,v.weight,1,3,true};}
Api api(H& h){Api a{};a.context=&h;a.source_asset=&h.asset;a.producer_method=0x1234;
 a.owner_thread=[](){return true;};a.current=[](void* p,uint64_t){auto& h=*static_cast<H*>(p);++h.owner_queries;return h.current;};a.routes_verified=[](void*){return true;};a.membership_current=[](void*){return true;};
 a.retain=[](void* p){auto id=host->next++;host->roots[id]=p;return id;};a.target=[](uint32_t id)->void*{auto at=host->roots.find(id);return at==host->roots.end()?nullptr:at->second;};a.release=[](uint32_t id){assert(host->roots.erase(id)==1);};
 a.inventory=[](void* p,void*,GameObjectImage* gos,size_t,size_t* ng,VolumeImage* vs,size_t,size_t* nv){auto& h=*static_cast<H*>(p);gos[0]={&h.go,h.go.layer};vs[0]=image(h.volume);*ng=*nv=1;return true;};
 a.volume_current=[](void*,const VolumeImage& v){return static_cast<O*>(v.object)->alive;};a.game_object_current=[](void*,const GameObjectImage& g){return static_cast<O*>(g.object)->alive;};
 a.restore_game_object=[](void* p,const GameObjectImage& g){auto& h=*static_cast<H*>(p);++h.touches;static_cast<O*>(g.object)->layer=g.layer;return true;};a.verify_game_object=[](void*,const GameObjectImage& g){return static_cast<O*>(g.object)->layer==g.layer;};
 a.restore_volume=[](void* p,const VolumeImage& v){auto& h=*static_cast<H*>(p);++h.touches;if(h.fail_restore)return false;auto& x=*static_cast<O*>(v.object);x.shared=v.shared_profile;x.internal=v.internal_profile;x.priority=v.priority;x.weight=v.weight;return true;};
 a.verify_volume=[](void*,const VolumeImage& v){auto& x=*static_cast<O*>(v.object);return x.shared==v.shared_profile&&x.internal==v.internal_profile&&x.priority==v.priority&&x.weight==v.weight;};
 a.fresh_game_object=[](void*,void* p,void* name){return static_cast<O*>(p)->type==1&&!static_cast<O*>(p)->alive&&name==reinterpret_cast<void*>(1);};
 a.volume_subject=[](void*,void* p,void** go){auto* x=static_cast<O*>(p);if(x->type!=2)return false;*go=x->go;return true;};
 a.created_current=[](void*,void* p,Kind,void*){return static_cast<O*>(p)->alive;};
 a.destroy_created_immediate=[](void* p,void* v,Kind){auto& h=*static_cast<H*>(p);++h.destroys;auto& x=*static_cast<O*>(v);x.alive=false;x.registered=false;return true;};
 a.created_unregistered=[](void*,void* p,Kind){auto& x=*static_cast<O*>(p);return !x.alive&&!x.registered;};
 a.withdraw_created=[](void*,void* p,Kind,void*){auto& x=*static_cast<O*>(p);x.detached=true;x.registered=false;x.shared=x.internal=nullptr;return true;};
 a.created_withdrawn=[](void*,void* p,Kind,void*){return static_cast<O*>(p)->detached;};
 a.cleanup_fenced=[](void* p){return static_cast<H*>(p)->gpu;};
 a.destroy_detached=[](void* p,void* v,Kind,void*){auto& h=*static_cast<H*>(p);++h.destroys;auto& x=*static_cast<O*>(v);x.alive=false;x.registered=false;return true;};a.detached_destroyed=a.created_unregistered;
 a.abandon_created=[](void* p,void* v,Kind)noexcept{auto& h=*static_cast<H*>(p);++h.transfers;static_cast<O*>(v)->abandoned=true;};
 a.current_profile=[](void*,void* p,void** profile){auto& v=*static_cast<O*>(p);*profile=v.internal?v.internal:v.shared;return true;};return a;}
void begin(H& h){host=&h;assert(h.scope.capture(api(h),7,&h.brain));}
void created(H& h){assert(h.scope.game_object_before(&h.created_go,reinterpret_cast<void*>(1))==Observe::owned);h.created_go.alive=true;assert(h.scope.volume_before_enable(&h.created_volume)==Observe::owned);h.created_volume.registered=true;}
int main(){
 {H h;begin(h);auto token=h.scope.begin_apply(&h.brain);created(h);
  auto clear=[](void*p){auto&v=*static_cast<O*>(p);return !v.shared&&!v.internal;};
  assert(!h.scope.created_volume_publications_withdrawn(clear));assert(h.scope.end_apply(token));
  assert(!h.scope.created_volume_publications_withdrawn(clear));assert(h.scope.before_source_change()==Result::ok);
  h.current=false;const auto queries=h.owner_queries;assert(h.scope.created_volume_publications_withdrawn(clear)&&h.owner_queries==queries);
  h.created_volume.shared=&h.asset;assert(!h.scope.created_volume_publications_withdrawn(clear));h.created_volume.shared=nullptr;
  uint32_t lost=0;for(const auto&v:h.roots)if(v.second==&h.created_volume)lost=v.first;assert(lost);auto value=h.roots[lost];h.roots.erase(lost);
  assert(!h.scope.created_volume_publications_withdrawn(clear));h.roots[lost]=value;
  assert(h.scope.release(false)==Result::ok&&h.roots.empty());}

 {H h;begin(h);auto token=h.scope.begin_apply(&h.brain);assert(token);created(h);Receipt r{};assert(h.scope.receipt(&h.created_volume,r)&&r.newly_created&&r.owner==&h.brain&&r.asset==&h.asset&&r.producer==0x1234&&r.epoch==7);h.go.layer=8;h.volume.priority=99;h.volume.shared=&h.asset;assert(h.scope.end_apply(token));assert(h.scope.restore()==Result::ok&&h.scope.delegated_restored(&h.volume)&&h.destroys==2);assert(h.scope.release(true)==Result::ok&&h.roots.empty());}
 {H h;begin(h);VolumeImage v{};Receipt r{};assert(h.scope.source_receipt(0,v,r)&&!r.newly_created&&r.object==&h.volume);assert(!h.scope.source_receipt(1,v,r));assert(h.scope.release(true)==Result::ok);}
 {H h;begin(h);auto token=h.scope.begin_apply(&h.brain);created(h);h.current=false;auto touches=h.touches;assert(h.scope.restore()==Result::stale);h.scope.abandon_before_source_change();assert(h.scope.release(false)==Result::waiting);assert(!h.scope.end_apply(token));assert(h.scope.release(false)==Result::ok&&h.roots.empty()&&h.touches==touches&&h.transfers==2&&h.created_go.alive&&h.created_volume.alive);}
 {H h;begin(h);auto token=h.scope.begin_apply(&h.brain);assert(h.scope.volume_before_enable(&h.volume)==Observe::owned);assert(h.scope.volume_before_enable(&h.foreign_volume)==Observe::reject);assert(!h.scope.end_apply(token));assert(h.scope.restore()==Result::ok);assert(h.scope.release(true)==Result::ok);}
 {H h;begin(h);auto token=h.scope.begin_apply(&h.brain);h.go.layer=9;assert(h.scope.end_apply(token));assert(h.scope.before_source_change()==Result::ok&&h.go.layer==3);assert(!h.scope.begin_apply(&h.brain));assert(h.scope.release(false)==Result::ok&&h.roots.empty());}
 {H h;begin(h);auto token=h.scope.begin_apply(&h.brain);h.volume.priority=77;assert(h.scope.end_apply(token));h.fail_restore=true;assert(h.scope.restore()==Result::failed);h.fail_restore=false;assert(h.scope.restore()==Result::ok);assert(h.scope.release(true)==Result::ok);}
 {H h;begin(h);auto token=h.scope.begin_apply(&h.brain);assert(token);h.scope.abandon_before_source_change();const auto touches=h.touches;assert(!h.scope.end_apply(token));assert(h.scope.restore()==Result::stale&&h.touches==touches);assert(h.scope.release(false)==Result::ok);}
 {H h;begin(h);uint64_t tokens[16]{};for(auto& t:tokens){t=h.scope.begin_apply(&h.brain);assert(t);}assert(!h.scope.begin_apply(&h.brain));assert(h.scope.release(false)==Result::waiting);for(auto t:tokens)assert(h.scope.end_apply(t));assert(h.scope.release(true)==Result::ok);}
 {H h;begin(h);auto token=h.scope.begin_apply(&h.brain);created(h);assert(h.scope.end_apply(token));h.gpu=false;assert(h.scope.before_source_change()==Result::ok&&h.destroys==0&&h.created_volume.alive&&h.created_go.alive&&h.scope.owns_created_volume_raw(&h.created_volume));h.current=false;assert(h.scope.release(false)==Result::waiting&&h.destroys==0&&!h.roots.empty());h.gpu=true;assert(h.scope.release(false)==Result::ok&&h.destroys==2&&h.roots.empty());}
 {H h;begin(h);auto token=h.scope.begin_apply(&h.brain);created(h);assert(h.scope.end_apply(token));h.gpu=false;const auto touches=h.touches;assert(h.scope.restore()==Result::waiting&&h.touches==touches&&h.destroys==0);h.gpu=true;assert(h.scope.release(true)==Result::ok);}

}
