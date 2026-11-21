#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cassert>
#include <cstdio>
#include <map>
#include <vector>
#include <memory>
#include "mp4-private-renderer-data-lease.hpp.inc"
using namespace idoly_mp4_private_renderer_data;
struct Object{alignas(8)uint8_t data[1200]{};const char* type;bool live=true;std::vector<void*>items;};
struct Fixture{
 std::vector<std::unique_ptr<Object>> heap;std::map<uint32_t,void*> roots;uint32_t next=1;uintptr_t next_native=0x100000;
 void *additional=nullptr,*renderer=nullptr,*asset=nullptr,*renders=nullptr,*dataarray=nullptr,*data=nullptr,*post=nullptr,*compute=nullptr,*features=nullptr,*featuremap=nullptr;
 uint64_t epoch=7;bool current=true,thread=true,routes=true,fenced=true,phase=true,warmed=true;int fail_clone=-1,alias_clone=-1,memberwise=-1,clones=0,destroyed=0,writes=0;Lease lease;static Fixture* active;
 Fixture(){active=this;additional=make("UnityEngine.Rendering.Universal.UniversalAdditionalCameraData");renderer=make("VL.Rendering.VLSRPRenderer");asset=make("UnityEngine.Rendering.Universal.UniversalRenderPipelineAsset");renders=make("System.Array");dataarray=make("System.Array");data=make("VL.Rendering.VLSRPRendererData");post=make("VL.Rendering.VLPostProcessData");compute=make("UnityEngine.ComputeShader");features=make("System.Collections.Generic.List`1");featuremap=make("System.Collections.Generic.List`1");
  put(additional,56,int32_t{-1});put(asset,32,renders);put(asset,64,dataarray);put(asset,72,int32_t{0});obj(renders)->items={renderer};obj(dataarray)->items={data};put(data,32,features);put(data,40,featuremap);put(data,48,post);put(post,96,compute);put(post,88,uint8_t{1});}
 Object* obj(void* p){for(auto& o:heap)if(o->data==p)return o.get();return nullptr;}
 void* make(const char*type){heap.emplace_back(new Object{});auto*o=heap.back().get();o->type=type;put(o->data,16,next_native);next_native+=0x100;return o->data;}
 template<class T>static void put(void*p,size_t at,T value){std::memcpy(static_cast<uint8_t*>(p)+at,&value,sizeof value);}
 template<class T>static T get(void*p,size_t at){T value{};std::memcpy(&value,static_cast<uint8_t*>(p)+at,sizeof value);return value;}
 static bool owner(){return active->thread;}static bool curr(void* p,uint64_t e){auto&f=*static_cast<Fixture*>(p);return f.current&&f.epoch==e;}
 static bool verified(void*p){return static_cast<Fixture*>(p)->routes;}static bool refresh(){return true;}
 static bool mapped(const void*p,size_t n,bool){auto&f=*active;auto a=reinterpret_cast<uintptr_t>(p);for(auto&o:f.heap){auto b=reinterpret_cast<uintptr_t>(o->data);if(a>=b&&a-b<=1200&&n<=1200-(a-b))return true;if(!o->items.empty()){b=reinterpret_cast<uintptr_t>(o->items.data());if(a>=b&&a-b<=o->items.size()*8&&n<=o->items.size()*8-(a-b))return true;}}return false;}
 static bool type(void*p,const char*t){auto*o=active->obj(p);return o&&std::strcmp(o->type,t)==0;}static void* klass(void*p){auto*o=active->obj(p);return o?const_cast<char*>(o->type):nullptr;}
 static bool alive(void*p){auto*o=active->obj(p);return o&&o->live&&get<uintptr_t>(p,16);}
 static uint32_t retain(void*p){auto&f=*active;f.roots[f.next]=p;return f.next++;}static void* target(uint32_t n){auto&i=active->roots;auto f=i.find(n);return f==i.end()?nullptr:f->second;}static void release(uint32_t n){active->roots.erase(n);}
 static size_t length(void*p){return active->obj(p)->items.size();}static void* array(void*p){return active->obj(p)->items.data();}static void* get_asset(){return active->asset;}
 static void* instantiate(void*p){auto&f=*active;int i=f.clones++;if(f.fail_clone==i)return nullptr;if(f.alias_clone==i)return p;void* v=f.make(f.obj(p)->type);auto native=get<uintptr_t>(v,16);std::memcpy(v,p,1200);if(f.memberwise!=i)put(v,16,native);return v;}
 static void destroy(void*p){auto&f=*active;assert(p!=f.asset&&p!=f.data&&p!=f.post&&p!=f.compute&&p!=f.additional);f.obj(p)->live=false;put(p,16,uintptr_t{});++f.destroyed;}
 static void write(void*owner,void**slot,void*value){auto&f=*active;assert(owner!=f.asset&&owner!=f.data&&owner!=f.post&&owner!=f.compute&&owner!=f.additional);++f.writes;std::memcpy(slot,&value,sizeof value);}
 static bool fence(void*p){return static_cast<Fixture*>(p)->fenced;}static bool held(void*p){return static_cast<Fixture*>(p)->phase;}static bool variant_warmed(void*){return active->warmed;}
 Api api(){return{this,owner,curr,verified,refresh,mapped,type,type,klass,alive,retain,target,release,length,array,get_asset,instantiate,destroy,write,fence,held,variant_warmed};}
 void source_untouched(){assert(get<void*>(data,48)==post&&get<void*>(post,96)==compute&&get<void*>(asset,32)==renders&&get<void*>(asset,64)==dataarray&&obj(data)->live&&obj(post)->live&&obj(compute)->live);}
};Fixture*Fixture::active=nullptr;
int main(){unsigned cases=0;
 {Fixture f;assert(f.lease.capture(f.api(),{},7,f.additional,f.renderer));assert(f.lease.prepare());assert(f.clones==3&&f.writes==3);void*d=f.lease.renderer_data(),*p=f.lease.post_data(),*c=f.lease.compute_shader();assert(d&&p&&c&&d!=f.data&&p!=f.post&&c!=f.compute);assert(Fixture::get<void*>(d,48)==p&&Fixture::get<void*>(p,96)==c);f.source_untouched();assert(f.lease.publish());f.fenced=false;assert(!f.lease.release()&&!f.destroyed);f.fenced=true;assert(f.lease.release()&&f.destroyed==3&&f.roots.empty());f.source_untouched();++cases;}
 for(int stage=0;stage<3;++stage){Fixture f;f.fail_clone=stage;assert(f.lease.capture(f.api(),{},7,f.additional,f.renderer));assert(!f.lease.prepare());assert(f.lease.release());assert(f.destroyed==stage&&f.roots.empty());f.source_untouched();++cases;}
 for(int stage=0;stage<3;++stage){Fixture f;f.alias_clone=stage;assert(f.lease.capture(f.api(),{},7,f.additional,f.renderer));assert(!f.lease.prepare());assert(f.lease.release());assert(f.destroyed==stage&&f.roots.empty());f.source_untouched();++cases;}
 for(int stage=0;stage<3;++stage){Fixture f;f.memberwise=stage;assert(f.lease.capture(f.api(),{},7,f.additional,f.renderer));assert(!f.lease.prepare());assert(f.lease.release());assert(f.destroyed==stage&&f.roots.empty());f.source_untouched();++cases;}
 for(int fail=0;fail<10;++fail){Fixture f;switch(fail){case 0:Fixture::put(f.features,24,int32_t{1});break;case 1:Fixture::put(f.featuremap,24,int32_t{1});break;case 2:Fixture::put(f.additional,56,int32_t{-2});break;case 3:Fixture::put(f.asset,72,int32_t{2});break;case 4:f.obj(f.data)->type="Unknown";break;case 5:f.obj(f.post)->type="Unknown";break;case 6:Fixture::put(f.post,96,static_cast<void*>(nullptr));break;case 7:Fixture::put(f.post,88,uint8_t{2});break;case 8:Fixture::put(f.data,92,int32_t{1});break;case 9:Fixture::put(f.renderer,936,int32_t{1});break;}
  assert(!f.lease.capture(f.api(),{},7,f.additional,f.renderer)&&!f.clones&&!f.writes);assert(f.lease.release());++cases;}
 for(int fail=0;fail<4;++fail){Fixture f;assert(f.lease.capture(f.api(),{},7,f.additional,f.renderer));switch(fail){case 0:f.current=false;break;case 1:Fixture::put(f.additional,56,int32_t{1});break;case 2:Fixture::put(f.features,24,int32_t{1});break;case 3:f.phase=false;break;}
  assert(!f.lease.prepare()&&!f.clones&&!f.writes);assert(f.lease.release());f.source_untouched();++cases;}
 {Fixture f;Fixture::put(f.post,96,static_cast<void*>(nullptr));Fixture::put(f.post,88,uint8_t{0});assert(f.lease.capture(f.api(),{},7,f.additional,f.renderer));assert(f.lease.prepare()&&f.clones==2);assert(!f.lease.compute_shader());assert(f.lease.release()&&f.destroyed==2);++cases;}
 {Fixture f;void* v=f.make("UnityEngine.ShaderVariantCollection");Fixture::put(f.post,80,v);assert(f.lease.capture(f.api(),{},7,f.additional,f.renderer));assert(f.lease.prepare());assert(f.lease.release()&&f.destroyed==3);++cases;}
 {Fixture f;void* v=f.make("UnityEngine.ShaderVariantCollection");Fixture::put(f.post,80,v);f.warmed=false;assert(!f.lease.capture(f.api(),{},7,f.additional,f.renderer));assert(f.lease.release()&&!f.destroyed);++cases;}
 {Fixture f;void* v=f.make("UnityEngine.ShaderVariantCollection");Fixture::put(f.post,80,v);f.obj(v)->live=false;assert(f.lease.capture(f.api(),{},7,f.additional,f.renderer));assert(f.lease.prepare());assert(f.lease.release()&&f.destroyed==3);++cases;}
 {Fixture f;void*xr=f.make("UnityEngine.Rendering.Universal.XRSystemData");Fixture::put(f.data,56,xr);assert(f.lease.capture(f.api(),{},7,f.additional,f.renderer));assert(f.lease.prepare());assert(Fixture::get<void*>(f.lease.renderer_data(),56)==nullptr&&Fixture::get<void*>(f.data,56)==xr);assert(f.lease.release()&&f.obj(xr)->live);++cases;}
 {Fixture f;assert(f.lease.capture(f.api(),{},7,f.additional,f.renderer));assert(f.lease.prepare());assert(Fixture::get<void*>(f.lease.renderer_data(),56)==nullptr);f.source_untouched();assert(f.lease.release());++cases;}
 {Fixture f;void*xr=f.make("UnityEngine.Rendering.Universal.XRSystemData");Fixture::put(f.data,56,xr);assert(f.lease.capture(f.api(),{},7,f.additional,f.renderer));Fixture::put(f.data,56,static_cast<void*>(nullptr));assert(!f.lease.current()&&!f.lease.prepare());assert(f.lease.release()&&!f.destroyed);++cases;}
 std::printf("%u private renderer data provenance/clone cases passed; no GPU/whole constructor claim\n",cases);
}
