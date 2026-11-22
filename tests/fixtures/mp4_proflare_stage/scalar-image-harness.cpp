#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <map>
#include <vector>
#include <memory>
#include <string>
struct Obj{uint8_t data[384]{};};std::vector<std::unique_ptr<Obj>>storage;std::map<void*,int>kinds;
Obj*make(int k){storage.emplace_back(new Obj);auto*p=storage.back().get();kinds[p]=k;return p;}
struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};struct Mp4TimelineTypePin{const char*name;Binding binding;};
struct{Mp4TimelineTypePin flare{"flare",{}},element{"element",{}};}mp4_proflare_pins;
#include "scalar-schema-pins.inc"
bool schema=true,access=true,mapped=true;unsigned allocs=0,frees=0;std::map<uint32_t,void*>roots;uint32_t sequence=0;
uint32_t mp4_retain(void*p){++allocs;roots[++sequence]=p;return sequence;}void*weak_get(uint32_t r){auto i=roots.find(r);return i==roots.end()?nullptr:i->second;}void weak_free(uint32_t r){++frees;roots.erase(r);}
bool mp4_proflare_access_current(){return access;}bool mp4_timeline_exact(void*p,const Mp4TimelineTypePin&t){return p&&kinds.count(p)&&kinds[p]==((&t==&mp4_proflare_pins.flare)?0:(&t==&mp4_proflare_pins.element)?1:2);}
const Mp4ProFlareScalarField*fields(void*object,size_t*n){int k=kinds[object];if(k==0){*n=sizeof(mp4_pf_flare_fields)/sizeof(*mp4_pf_flare_fields);return mp4_pf_flare_fields;}if(k==1){*n=sizeof(mp4_pf_element_fields)/sizeof(*mp4_pf_element_fields);return mp4_pf_element_fields;}*n=sizeof(mp4_pf_sub_fields)/sizeof(*mp4_pf_sub_fields);return mp4_pf_sub_fields;}
bool mp4_proflare_cache_field(void*object,const char*name,size_t at,uint32_t kind){size_t n=0;auto*f=fields(object,&n);for(size_t i=0;i<n;++i)if(f[i].offset==at&&!std::strcmp(name,f[i].name))return schema&&f[i].kind==kind;return false;}
bool mp4_root_track_field(void*object,const char*name,size_t at,void**out=nullptr){size_t n=0;auto*f=fields(object,&n);for(size_t i=0;i<n;++i)if(f[i].offset==at&&!std::strcmp(name,f[i].name)){if(out)*out=const_cast<Mp4ProFlareScalarField*>(&f[i]);return schema;}return false;}
const void*font_field_type(void*f){return f;}void*font_class_type(const void*f){return const_cast<void*>(f);}int32_t size(void*p,uint32_t*){return static_cast<Mp4ProFlareScalarField*>(p)->width;}
uintptr_t image_base=0;struct{Binding class_value_size{reinterpret_cast<uintptr_t>(&size),{}};}mp4_cam_profile;
template<class F>F mp4_cam_call(const Binding&b){return reinterpret_cast<F>(b.rva);}
bool mp4_actor_mapped(const void*,size_t,bool){return mapped;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(!p||at+sizeof(out)>384)return false;std::memcpy(&out,static_cast<uint8_t*>(p)+at,sizeof out);return mapped;}
template<class T>void put(void*p,size_t at,T value){std::memcpy(static_cast<uint8_t*>(p)+at,&value,sizeof value);}
#include "scalar-image-host.inc"
bool mp4_actor_list(void*l,void***items,size_t*n,size_t cap){void*a=nullptr;uint32_t count=0;if(!mp4_actor_field(l,16,a)||!mp4_actor_field(l,24,count)||count>cap)return false;*items=reinterpret_cast<void**>(static_cast<uint8_t*>(a)+32);*n=count;return true;}
bool mp4_proflare_cache_declared(void*,const char*,size_t,void*){return schema;}
#include "sub-element-image-host.inc"
int main(){auto*f=make(0),*e=make(1),*sub=make(2),*list=make(3),*array=make(4);unsigned cases=0;Mp4ProFlareScalarImage image;
 assert(mp4_proflare_scalar_capture(image,f,0)&&mp4_proflare_scalar_current(image));put(f,88,7.f);assert(mp4_proflare_scalar_current(image)&&!mp4_proflare_scalar_verified(image));assert(mp4_proflare_scalar_restore(image)&&mp4_proflare_scalar_verified(image));mp4_proflare_scalar_release(image);++cases;
 assert(mp4_proflare_scalar_capture(image,e,1));put(e,60,9.f);assert(mp4_proflare_scalar_restore(image)&&mp4_proflare_scalar_verified(image));mp4_proflare_scalar_release(image);++cases;
 assert(mp4_proflare_scalar_capture(image,sub,2));put(sub,96,11.f);assert(mp4_proflare_scalar_restore(image)&&mp4_proflare_scalar_verified(image));mp4_proflare_scalar_release(image);++cases;
 assert(mp4_proflare_scalar_capture(image,f,0));put(f,136,static_cast<void*>(sub));assert(!mp4_proflare_scalar_current(image)&&!mp4_proflare_scalar_restore(image));put(f,136,static_cast<void*>(nullptr));mp4_proflare_scalar_release(image);++cases;
 assert(mp4_proflare_scalar_capture(image,f,0));auto value=roots[image.object_root];roots[image.object_root]=nullptr;assert(!mp4_proflare_scalar_current(image));roots[image.object_root]=value;mp4_proflare_scalar_release(image);++cases;
 for(int k=0;k<3;++k){if(k==0)schema=false;if(k==1)access=false;if(k==2)mapped=false;assert(!mp4_proflare_scalar_capture(image,f,0));mp4_proflare_scalar_release(image);schema=access=mapped=true;++cases;}
 put(e,288,static_cast<void*>(list));put(list,16,static_cast<void*>(array));put(list,24,uint32_t(1));put(list,28,uint32_t(7));put(array,32,static_cast<void*>(sub));Mp4ProFlareSubImage children;size_t budget=8;assert(mp4_proflare_sub_capture(children,e,&budget)&&budget==7&&mp4_proflare_sub_current(children));put(sub,48,13.f);assert(mp4_proflare_sub_restore(children));++cases;
 put(list,28,uint32_t(8));assert(!mp4_proflare_sub_current(children)&&!mp4_proflare_sub_restore(children));put(list,28,uint32_t(7));mp4_proflare_sub_release(children);++cases;
 budget=0;assert(!mp4_proflare_sub_capture(children,e,&budget));mp4_proflare_sub_release(children);++cases;
 put(e,288,static_cast<void*>(nullptr));budget=1;assert(mp4_proflare_sub_capture(children,e,&budget)&&mp4_proflare_sub_current(children));mp4_proflare_sub_release(children);++cases;
 assert(roots.empty()&&allocs==frees);std::printf("%u actual PF scalar/SubElement image cases passed\n",cases);
}
