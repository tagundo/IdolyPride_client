// Unit fixture: bounded modeled managed heap and callback routes. No Unity/GPU claim.
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cmath>
// SHIPPING_SOURCE_VOLUME_SCOPE
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>
#include "mp4_actor_state.hpp"
namespace mp4vs=idoly_mp4_volume_source;
static bool bank_oom=false;static unsigned bank_allocations=0;
void*bank_allocate(size_t bytes){++bank_allocations;return bank_oom?nullptr : ::malloc(bytes);}
// SHIPPING_SOURCE_VOLUME_LAZY
static Mp4LazySourceVolumeScope lazy_bank;

using namespace idoly_mp4_volume_source;
struct Block {alignas(16) unsigned char b[8192]{};std::string type;bool alive=true,enabled=true,active=true;int layer=2;size_t length=0;};
struct Host;static Host*g;
struct Host{
 std::vector<std::unique_ptr<Block>> blocks;std::unordered_map<void*,Block*>meta;std::unordered_map<uint32_t,void*>roots;
 uint64_t epoch=17,receipt=99;uintptr_t asset=0x123;bool current=true,fenced=true,routes=true,delegated=false,denywrite=false,badfactory=false,refnoop=false;
 unsigned writes=0,refwrites=0,updates=0,bad_disabled_updates=0;uint32_t nextroot=1;size_t peakroots=0;
 void*manager=nullptr,*roster=nullptr,*v0=nullptr,*v1=nullptr,*v2=nullptr,*p0=nullptr,*p1=nullptr,*c0=nullptr,*c1=nullptr,*q0=nullptr,*q1=nullptr,*dynam=nullptr;
 void*cur=nullptr,*anim=nullptr,*keysource=nullptr;std::vector<void*> owned;std::unordered_map<void*,ProfileAccess>access;std::unordered_map<void*,ValueKind>kinds;
 std::unordered_map<void*,uint32_t> caps;std::unordered_map<void*,void*> gos;void*denied=nullptr;bool badrelease=false,badowner=false;
 Host(){g=this;manager=make("Manager");roster=list({});put(manager,40,roster);put(manager,32,make("Cache0"));put(manager,48,make("Cache1"));
  v0=volume(true);v1=volume(true);v2=volume(false);owned={v0,v2};caps[v0]=caps[v2]=restore_flat|restore_layer|restore_enabled;
  setlist(roster,{v0,v1});p0=profile(true,&c0,&q0);p1=profile(false,&c1,&q1);put(v0,48,p0);put(v1,48,p1);
 }
 void*make(const char*t){auto b=std::make_unique<Block>();b->type=t;void*p=b->b;meta[p]=b.get();blocks.push_back(std::move(b));return p;}
 template<class T>void put(void*p,size_t o,T v){memcpy(static_cast<unsigned char*>(p)+o,&v,sizeof v);}
 template<class T>T get(void*p,size_t o){T v{};memcpy(&v,static_cast<unsigned char*>(p)+o,sizeof v);return v;}
 void*array(std::vector<void*>items){void*p=make("Array");meta[p]->length=items.size();if(!items.empty())memcpy(static_cast<unsigned char*>(p)+32,items.data(),items.size()*8);return p;}
 void*list(std::vector<void*>items){void*p=make("List");setlist(p,items);return p;}
 void setlist(void*p,std::vector<void*>items){void*a=array(items);put(p,16,a);put<int32_t>(p,24,int32_t(items.size()));put<int32_t>(p,28,get<int32_t>(p,28)+1);}
 std::vector<void*>items(void*l){std::vector<void*>r;auto*a=static_cast<void**>(static_cast<void*>(static_cast<unsigned char*>(get<void*>(l,16))+32));for(int32_t i=0;i<get<int32_t>(l,24);++i)r.push_back(a[i]);return r;}
 void*volume(bool enabled){void*v=make("UnityEngine.Rendering.Volume"),*go=make("GameObject");gos[v]=go;meta[v]->enabled=enabled;
  put<uint8_t>(v,32,1);put<float>(v,36,2.f);put<float>(v,40,0.f);put<float>(v,44,1.f);put<int32_t>(v,56,2);put<float>(v,60,2.f);return v;}
 void*profile(bool writable,void**component,void**param){void*p=make("UnityEngine.Rendering.VolumeProfile"),*c=make(writable?"UnityEngine.Rendering.Universal.Bloom":"UnityEngine.Rendering.Universal.ColorAdjustments"),*q=make("FloatParameter");
  kinds[q]=ValueKind::flat;put<uint8_t>(q,16,1);put<float>(q,20,3.f);put<float>(q,24,0.f);put<float>(q,28,10.f);
  void*collection=make("ReadOnlyCollection");put(collection,16,list({q}));put(c,40,collection);put<uint8_t>(c,24,1);put(p,24,list({c}));access[p]=writable?ProfileAccess::mutable_owned:ProfileAccess::readonly_input;
  *component=c;*param=q;return p;}
 void register_volume(void*v){auto a=items(roster);if(std::find(a.begin(),a.end(),v)==a.end()){a.push_back(v);setlist(roster,a);}}
 void unregister_volume(void*v){auto a=items(roster);a.erase(std::remove(a.begin(),a.end(),v),a.end());setlist(roster,a);}
 void add_curve(){access[p0]=ProfileAccess::readonly_input;kinds[q0]=ValueKind::curve;cur=make("UnityEngine.Rendering.TextureCurve");anim=make("UnityEngine.AnimationCurve");put(cur,32,anim);put(cur,16,int32_t(1));put<float>(cur,24,0.f);put<float>(cur,28,1.f);put(q0,24,cur);keysource=make("Keys");meta[keysource]->length=1;put<float>(keysource,32,0.f);put<float>(keysource,36,1.f);}
 Api api();
};
static bool mapped(uintptr_t p,size_t n,bool write){if(write&&g->denywrite&&(!g->denied||(p>=uintptr_t(g->denied)&&p<uintptr_t(g->denied)+8192)))return false;for(auto&b:g->blocks){uintptr_t start=uintptr_t(b->b);if(p>=start&&n<=8192&&p-start<=8192-n)return true;}return false;}
static bool exact(void*p,const char*t){auto i=g->meta.find(p);return i!=g->meta.end()&&i->second->type==t;}
static bool alive(void*p){auto i=g->meta.find(p);return i!=g->meta.end()&&i->second->alive;}
static uint32_t retain(void*p){if(!p)return 0;uint32_t t=g->nextroot++;g->roots[t]=p;g->peakroots=std::max(g->peakroots,g->roots.size());return t;}
static void*retained(uint32_t t){auto i=g->roots.find(t);return i==g->roots.end()?nullptr:i->second;}
static void release(uint32_t t){g->roots.erase(t);}
static bool write_value(void*p,size_t o,const void*v,size_t n){++g->writes;if(!mapped(uintptr_t(p)+o,n,true))return false;memcpy(static_cast<unsigned char*>(p)+o,v,n);return true;}
static bool write_ref(void*p,size_t o,void*v){++g->refwrites;if(g->refnoop)return true;return write_value(p,o,&v,8);}
static bool owner(void*,void*v,OwnerWitness*w){if(std::find(g->owned.begin(),g->owned.end(),v)==g->owned.end())return false;*w={v,g->gos[v],0x456,g->asset,g->epoch,g->receipt+(g->badowner?1:0),g->caps[v]};return true;}
static bool shape(void*p,ParameterShape*s){auto i=g->kinds.find(p);if(i==g->kinds.end())return false;*s=ParameterShape{};s->klass=p;s->kind=i->second;s->release=g->badrelease?999:(i->second==ValueKind::curve?102:101);s->instance_bytes=40;s->value_offset=i->second==ValueKind::flat?20:24;s->value_bytes=i->second==ValueKind::flat?4:8;s->value_float_lanes=i->second==ValueKind::flat?1:0;
 if(i->second==ValueKind::flat){s->tail_count=2;s->tail[0]={24,4,1};s->tail[1]={28,4,1};}return true;}
Api Host::api(){Api a{};a.thread=[](){return true;};a.routes_ready=[](){return g->routes;};a.current=[](void*){return g->current;};a.epoch=[](void*){return g->epoch;};a.asset=[](void*){return g->asset;};a.manager=[](void*){return g->manager;};a.mapped=mapped;a.exact_type=exact;a.class_of=[](void*p){return p;};a.alive=alive;a.retain=retain;a.retained=retained;a.release_root=release;
 a.array_length=[](void*p){return g->meta[p]->length;};a.array_data=[](void*p)->void*{return static_cast<unsigned char*>(p)+32;};
 a.owned_volumes=[](void*,void**out,size_t cap,size_t*n){*n=g->owned.size();if(*n>cap)return false;std::copy(g->owned.begin(),g->owned.end(),out);return true;};a.owner=owner;
 a.profile_witness=[](void*,void*p,ProfileWitness*w){auto i=g->access.find(p);if(i==g->access.end())return false;*w={p,g->asset,g->epoch,77,i->second};return true;};
 a.dynamic_volume=[](void*,void*v,DynamicVolumeWitness*w){if(v!=g->dynam)return false;void*internal=g->get<void*>(v,64),*shared=g->get<void*>(v,48);*w={v,g->gos[v],internal?internal:shared,0x900,g->asset,g->epoch,999,true};return true;};a.cine_apply_postfx=0x900;
 a.delegated_restored=[](void*,void*,const OwnerWitness&){return g->delegated;};a.component_parameters=[](void*,void**,size_t){return true;};a.parameter_shape=shape;a.base_release=101;a.curve_release=102;
 a.immutable_asset=[](void*,void*p,ValueKind kind,void*,void*){return alive(p)&&((kind==ValueKind::texture2d&&exact(p,"Texture2D"))||(kind==ValueKind::cubemap&&exact(p,"Cubemap"))||(kind==ValueKind::mesh&&exact(p,"Mesh")));};
 a.curve_keys=[](void*){void*p=g->make("Keys");g->meta[p]->length=g->meta[g->keysource]->length;memcpy(static_cast<unsigned char*>(p)+32,static_cast<unsigned char*>(g->keysource)+32,g->meta[p]->length*28);return p;};
 a.game_object=[](void*p){return g->gos[p];};a.enabled=[](void*p){return g->meta[p]->enabled;};a.layer=[](void*p){return g->meta[p]->layer;};a.active_hierarchy=[](void*p){return g->meta[p]->active;};a.write_value=write_value;a.write_reference=write_ref;
 a.set_enabled=[](void*p,bool enabled){++g->writes;g->meta[p]->enabled=enabled;if(enabled&&g->meta[g->gos[p]]->active)g->register_volume(p);else g->unregister_volume(p);return true;};
 a.set_layer=[](void*p,int32_t layer){++g->writes;g->meta[p]->layer=layer;return true;};
 a.original_volume_update=[](void*p){++g->updates;if(!g->meta[p]->enabled||!g->meta[g->gos[p]]->active)++g->bad_disabled_updates;g->put(p,56,g->meta[g->gos[p]]->layer);g->put(p,60,g->get<float>(p,36));g->register_volume(p);return true;};
 a.list_remove_at=[](void*p,size_t idx){++g->writes;auto a=g->items(p);if(idx>=a.size())return false;a.erase(a.begin()+idx);g->setlist(p,a);return true;};a.list_insert=[](void*p,size_t idx,void*v){++g->writes;auto a=g->items(p);if(idx>a.size())return false;a.insert(a.begin()+idx,v);g->setlist(p,a);return true;};
 a.empty_cache=[](void*,unsigned which){if(g->badfactory)return g->get<void*>(g->manager,which?48:32);return g->make(which?"Cache1":"Cache0");};a.empty_cache_verified=[](void*,void*p,unsigned which){return exact(p,which?"Cache1":"Cache0");};a.fenced=[](void*){return g->fenced;};return a;}
static bool check(bool ok,const char*what,Mp4LazySourceVolumeScope&s){if(!ok){std::fprintf(stderr,"%s: %s\n",what,s.error());return false;}return true;}
int main(int argc,char**argv){if(argc!=2)return 2;const int mode=std::atoi(argv[1]);Host h;auto*scope=&lazy_bank;Mp4LazySourceVolumeScope&s=*scope;Api api=h.api();Result expected=Result::ok;
 if(mode==29||mode==30) {
  const size_t total=mode==29?617:source_max_volumes+1;
  while(h.owned.size()<total) {
   void*v=h.volume(true);h.meta[h.gos[v]]->active=false;h.owned.push_back(v);h.caps[v]=restore_flat|restore_layer|restore_enabled;
   if(mode==29) {void*c=nullptr,*q=nullptr;void*p=h.profile(false,&c,&q);h.put(v,48,p);
    std::vector<void*> comps{c};
    for(unsigned i=0;i<3;++i){void*cc=nullptr,*qq=nullptr;h.profile(false,&cc,&qq);comps.push_back(cc);}
    h.setlist(h.get<void*>(p,24),comps);
   }
  }
  if(mode==30)expected=Result::unsupported;
 }
 if(mode==7){h.badrelease=true;expected=Result::unsupported;}
 if(mode==8){h.put(h.v1,48,h.p0);expected=Result::unsupported;}
 if(mode==12||mode==13)h.add_curve();
 if(mode==14){h.put<int32_t>(h.v2,56,11);h.put<float>(h.v2,60,9.f);}
 if(mode==15||mode==16)h.caps[h.v0]|=external_restore;
 if(mode==21){h.dynam=h.volume(true);h.register_volume(h.dynam);expected=Result::invalid;}
 if(mode==24){h.kinds[h.q0]=ValueKind::texture2d;h.put(h.q0,24,h.make("Texture2D"));}
 if(mode==26){h.meta[h.c0]->type="VL.PostProcessing.VLDOF";}
 if(mode==32){bank_oom=true;expected=Result::unsupported;}
 Result result=s.capture(api,&h);if(!check(result==expected,"capture",s))return 1;
 if(mode==32&&(!check(!s.allocated(),"OOM allocated a bank",s)||!check(bank_allocations==1,"OOM attempt count",s)))return 1;
 if(expected!=Result::ok){if(!check(h.roots.empty(),"failed capture leaked roots",s))return 1;return 0;}
 unsigned before=h.writes;Result restore_expect=Result::ok;bool assert_no_write=false;
 switch(mode){
 case 0:case 26:case 29:break;
 case 1:h.put<float>(h.v0,44,.2f);h.put<float>(h.v0,36,9.f);h.put<int32_t>(h.v0,56,9);h.put<float>(h.q0,20,7.f);h.put<float>(h.q0,24,-2.f);h.put<uint8_t>(h.c0,24,0);h.put<uint8_t>(h.p0,32,1);break;
 case 2:h.setlist(h.roster,{h.v0,h.v1,h.volume(true)});restore_expect=Result::stale;assert_no_write=true;break;
 case 3:h.setlist(h.roster,{h.v0});restore_expect=Result::stale;assert_no_write=true;break;
 case 4:h.put<float>(h.q1,20,6.f);restore_expect=Result::stale;assert_no_write=true;break;
 case 5:++h.epoch;restore_expect=Result::stale;assert_no_write=true;break;
 case 6:h.badowner=true;restore_expect=Result::stale;assert_no_write=true;break;
 case 9:{void*l=h.get<void*>(h.p0,24),*a=h.get<void*>(l,16);h.put(a,32,h.c1);restore_expect=Result::stale;assert_no_write=true;break;}
 case 10:{void*l=h.get<void*>(h.get<void*>(h.c0,40),16),*a=h.get<void*>(l,16);h.put(a,32,h.q1);restore_expect=Result::stale;assert_no_write=true;break;}
 case 11:h.current=false;restore_expect=Result::stale;assert_no_write=true;break;
 case 12:h.put<float>(h.keysource,36,2.f);restore_expect=Result::stale;assert_no_write=true;break;
 case 13:{const size_t baseline=h.roots.size();for(int i=0;i<80;++i)if(!check(s.validate()==Result::ok,"curve validate",s)||!check(h.roots.size()==baseline,"curve temporary root leak",s))return 1;break;}
 case 14:api.set_enabled(h.v2,true);break;
 case 15:h.put<float>(h.v0,44,.25f);h.put(h.v0,48,h.p1);if(!check(s.validate()==Result::ok,"delegated export validate",s))return 1;restore_expect=Result::waiting;assert_no_write=true;break;
 case 16:h.delegated=true;break;
 case 17:h.dynam=h.volume(true);h.register_volume(h.dynam);if(!check(s.validate()==Result::ok,"dynamic validate",s)||!check(s.owns_volume(h.dynam),"dynamic ownership",s))return 1;restore_expect=Result::waiting;assert_no_write=true;break;
 case 18:h.dynam=h.volume(true);h.register_volume(h.dynam);if(!check(s.validate()==Result::ok,"dynamic validate",s))return 1;h.unregister_volume(h.dynam);h.meta[h.dynam]->alive=false;break;
 case 19:h.denywrite=true;h.denied=h.q0;restore_expect=Result::unsupported;assert_no_write=true;break;
 case 20:h.badfactory=true;restore_expect=Result::unsupported;assert_no_write=true;break;
 case 22:h.fenced=false;restore_expect=Result::stale;assert_no_write=true;break;
 case 23:h.refnoop=true;restore_expect=Result::failed;break;
 case 24:h.put(h.q0,24,h.make("Texture2D"));break;
 case 25:h.setlist(h.roster,{h.v1,h.v0});break;
 case 28:h.fenced=false;if(!check(s.validate_inputs()==Result::ok,"draw inputs read guard",s))return 1;restore_expect=Result::stale;assert_no_write=true;break;
 case 27:h.caps[h.v0]=0;restore_expect=Result::stale;assert_no_write=true;break;
 default:break;
 }
 before=h.writes;result=s.restore();if(!check(result==restore_expect,"restore",s))return 1;
 if(assert_no_write&&!check(h.writes==before,"preflight wrote source",s))return 1;
 if(result==Result::ok){if(!check(s.verify()==Result::ok,"verify",s)||!check(!h.bad_disabled_updates,"called Update on disabled source",s))return 1;
  if(mode==24&&!check(h.refwrites>=3,"asset reference was not barrier-written",s))return 1;
 }
 s.clear();if(!check(h.roots.empty(),"clear leaked roots",s))return 1;
 if(mode==31){if(!check(s.allocated()&&bank_allocations==1,"bank not stable",s)||!check(s.capture(api,&h)==Result::ok,"bank reuse capture",s))return 1;s.clear();if(!check(bank_allocations==1&&h.roots.empty(),"reuse allocated/leaked",s))return 1;}
 return 0;}
