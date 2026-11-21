#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cassert>
#include <cstdio>
#include <vector>
#include <memory>
#include <set>
#include "mp4-private-renderer-root-check.hpp.inc"
using namespace idoly_mp4_private_renderer_root;
struct Object {alignas(8)uint8_t data[1200]{};int role=-1;bool shader=false,material=false,live=true;};
struct Fixture {
 std::vector<std::unique_ptr<Object>> heap;std::set<void*> owned_materials,owned_libraries;void* shaders[21]{};
 void *source_data=nullptr,*source_post=nullptr,*private_data=nullptr,*private_post=nullptr,*source_renderer=nullptr,*private_renderer=nullptr,*compute=nullptr;Check check;static Fixture* active;
 Fixture(){active=this;for(auto& s:shaders){s=make();obj(s)->shader=true;}source_data=make();source_post=make();private_data=make();private_post=make();compute=make();bind_shaders(source_data,source_post);bind_shaders(private_data,private_post);source_renderer=renderer(false,source_post);private_renderer=renderer(true,private_post);}
 Object* obj(void* p){for(auto&o:heap)if(o->data==p)return o.get();return nullptr;}
 void* make(int role=-1){heap.emplace_back(new Object{});heap.back()->role=role;return heap.back()->data;}
 template<class T>static void put(void*p,size_t at,T value){std::memcpy(static_cast<uint8_t*>(p)+at,&value,sizeof value);}
 template<class T>static T get(void*p,size_t at){T value{};std::memcpy(&value,static_cast<uint8_t*>(p)+at,sizeof value);return value;}
 void* material(bool own){void* m=make();obj(m)->material=true;if(own)owned_materials.insert(m);return m;}
 void bind_shaders(void* data,void* post){void*r=make(),*p=make();put(data,64,r);put(post,24,p);size_t slot=0;constexpr size_t used[]={16,24,40,32,64};for(size_t at:used)put(r,at,shaders[slot++]);put(data,104,shaders[slot++]);for(size_t at=16;at<=96;at+=8)put(p,at,shaders[slot++]);for(size_t at=48;at<=72;at+=8)put(post,at,shaders[slot++]);assert(slot==21);}
 void* renderer(bool own,void* post){void* r=make(int(Role::renderer));for(size_t at=952;at<=1008;at+=8)if(at!=984&&at!=992)put(r,at,material(own));void*lut=make(int(Role::lut_pass));put(r,152,lut);put(lut,128,material(own));put(lut,136,material(own));void*c=make(int(Role::compute_pass));put(r,160,c);put(c,128,compute);
  for(size_t at:{size_t(328),size_t(336)}){void*p=make(int(Role::post_pass));void*l=make(int(Role::material_library));put(r,at,p);put(p,376,l);put(p,384,post);put(p,536,get<void*>(r,952));if(own)owned_libraries.insert(l);for(size_t i=16;i<=112;i+=8)put(l,i,material(own));}return r;}
 void** slot(void* r,size_t index){if(index<8)return reinterpret_cast<void**>(static_cast<uint8_t*>(r)+952+index*8);index-=8;if(index<2){void*lut=get<void*>(r,152);return reinterpret_cast<void**>(static_cast<uint8_t*>(lut)+128+index*8);}index-=2;void*pass=get<void*>(r,index<13?328:336);void*lib=get<void*>(pass,376);return reinterpret_cast<void**>(static_cast<uint8_t*>(lib)+16+(index%13)*8);}
 static bool mapped(const void*p,size_t n,bool){auto a=reinterpret_cast<uintptr_t>(p);for(auto&o:active->heap){auto b=reinterpret_cast<uintptr_t>(o->data);if(a>=b&&a-b<=1200&&n<=1200-(a-b))return true;}return false;}
 static bool role(void*p,Role role){auto*o=active->obj(p);return o&&o->role==int(role);}
 static bool shader(void*p){auto*o=active->obj(p);return o&&o->shader&&o->live;}
 static bool mat(void*p){auto*o=active->obj(p);return o&&o->material&&o->live;}
 static bool owns_mat(void*,void*p){return active->owned_materials.count(p)&&mat(p);}
 static bool owns_lib(void*,void*p){return active->owned_libraries.count(p);}
 Api api(){return{this,mapped,role,shader,mat,owns_mat,owns_lib};}
 bool capture(){return check.capture(api(),source_renderer,source_data,source_post);}
 bool complete(){return check.private_complete(private_renderer,private_data,private_post,compute);}
};Fixture*Fixture::active=nullptr;
int main(){unsigned cases=0;
 {Fixture f;assert(f.capture()&&f.check.expected_materials()==34&&f.complete());for(auto shader:f.shaders)assert(f.check.shader_admitted(shader));assert(!f.check.shader_admitted(f.make()));++cases;}
 for(size_t index=10;index<36;++index){Fixture f;*f.slot(f.source_renderer,index)=nullptr;*f.slot(f.private_renderer,index)=nullptr;assert(f.capture()&&f.check.expected_materials()==33&&f.complete());++cases;}
 for(size_t index=0;index<36;++index){if(index==4||index==5)continue;Fixture f;assert(f.capture());void* value=*f.slot(f.private_renderer,index);f.owned_materials.erase(value);assert(!f.complete());++cases;}
 for(size_t index=0;index<21;++index){Fixture f;f.obj(f.shaders[index])->live=false;assert(!f.capture());++cases;}
 for(unsigned failure=0;failure<8;++failure){Fixture f;assert(f.capture());switch(failure){
  case 0:Fixture::put(f.private_renderer,328,Fixture::get<void*>(f.source_renderer,328));break;
  case 1:Fixture::put(Fixture::get<void*>(f.private_renderer,328),384,f.source_post);break;
  case 2:Fixture::put(Fixture::get<void*>(f.private_renderer,336),536,Fixture::get<void*>(f.source_renderer,952));break;
  case 3:Fixture::put(Fixture::get<void*>(f.private_renderer,160),128,f.make());break;
  case 4:f.obj(Fixture::get<void*>(f.private_renderer,152))->role=-1;break;
  case 5:*f.slot(f.private_renderer,12)=nullptr;break;
  case 6:Fixture::put(f.private_data,104,f.make());break;
  case 7:f.private_renderer=f.source_renderer;break;
 }assert(!f.complete());++cases;}
 std::printf("%u private renderer source-role ownership cases passed; no GPU/original ctor execution claim\n",cases);
}
