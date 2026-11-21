#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
#include <functional>
#include "client-presentation/native/mp4_camera_owner.hpp"
using Method=void;namespace mp4cam=idoly_mp4_camera_state;namespace mp4camp=idoly_mp4_camera_profile;namespace mp4game{using Binding=mp4camp::Binding;}
const auto& mp4_cam_profile=mp4camp::android_profile;const auto& mp4_cam_types=mp4camp::android_types;
struct Pin{uintptr_t rva;unsigned char bytes[16];};namespace pin{Pin mp4_material_ctor_shader{0xaa,{}},mp4_render_library_ctor{0xbb,{}};}
struct Klass{std::string name;bool value=false;std::string space;};struct Object{Klass*klass;uintptr_t monitor=0;uint8_t body[4096]{};explicit Object(Klass*k):klass(k){}};
struct StaticField{uint32_t at;void* value=nullptr;};StaticField bloomFields[2]={{144,nullptr},{152,nullptr}};
std::vector<std::unique_ptr<Object>> heap;std::unordered_map<std::string,std::unique_ptr<Klass>> classes;std::unordered_map<uint32_t,void*> roots;std::unordered_map<uintptr_t,uintptr_t> calls;uint32_t nextroot=1;uintptr_t nextnative=0x1000;
bool current=true,phase=true,program=true,fence=true,drawfence=true,fail_ctor=false,fail_root=false,lose_after_ctor=false;int fail_clone=-1,clone_count=0,destroy_count=0,dispose_count=0,reset_count=0;void*asset=nullptr,*sourceRenderer=nullptr;void*sourceData=nullptr,*sourcePost=nullptr,*additional=nullptr;void* shaderInputs[21]{};int ctor_fail_material=-1,material_seq=0;
Klass* klass(const std::string&n){auto&i=classes[n];if(!i)i=std::make_unique<Klass>(Klass{n,n=="System.Int32",n.find_last_of('.')==std::string::npos?"":n.substr(0,n.find_last_of('.'))});return i.get();}
void* make(const std::string&n,bool live=true){auto v=std::make_unique<Object>(klass(n));auto*p=v.get();heap.push_back(std::move(v));uintptr_t ptr=live?nextnative++:0;std::memcpy(p->body,&ptr,8);return p;}
template<class T>void put(void*p,size_t at,T v){std::memcpy(static_cast<uint8_t*>(p)+at,&v,sizeof v);}
template<class T>T get(void*p,size_t at){T v{};std::memcpy(&v,static_cast<uint8_t*>(p)+at,sizeof v);return v;}
bool mp4_actor_mapped(const void*p,size_t n,bool){uintptr_t a=reinterpret_cast<uintptr_t>(p);for(auto&o:heap){uintptr_t b=reinterpret_cast<uintptr_t>(o.get());if(a>=b&&a-b<=sizeof(Object)&&n<=sizeof(Object)-(a-b))return true;}return false;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&v){if(!p||!mp4_actor_mapped(static_cast<uint8_t*>(p)+at,sizeof v,false))return false;v=get<T>(p,at);return true;}
const char*class_name(void*k){auto&n=static_cast<Klass*>(k)->name;auto at=n.find_last_of('.');return n.c_str()+(at==std::string::npos?0:at+1);}
const char*class_namespace(void*k){return static_cast<Klass*>(k)->space.c_str();}
void*field_type(void*){return klass("System.Int32[]");}void*class_type(const void*p){return const_cast<void*>(p);}
void*(*font_field_type)(void*)=field_type;void*(*font_class_type)(const void*)=class_type;
void*object_class(void*p){return p?static_cast<Object*>(p)->klass:nullptr;}
bool mp4_type_is(void*p,const char*n){return p&&(static_cast<Object*>(p)->klass->name==n||(std::string(n)=="System.Array"&&static_cast<Object*>(p)->klass->name=="System.Int32[]"));}
bool mp4_exact_type(void*p,const char*n){return mp4_type_is(p,n);}
bool mp4_alive(void*p){return p&&get<uintptr_t>(p,16)!=0;}
uint32_t mp4_retain(void*p){if(!p)return 0;roots[nextroot]=p;return nextroot++;}void*weak_get(uint32_t r){auto i=roots.find(r);return i==roots.end()?nullptr:i->second;}void weak_free(uint32_t r){assert(roots.erase(r)==1);}
bool mp4_actor_refresh_maps(){return true;}bool game_call(){return true;}bool mp4_actor_clock_held(void*){return phase;}
size_t mp4_array_length(void*p){return get<uintptr_t>(p,24);}void*mp4_array_data(void*p){return static_cast<uint8_t*>(p)+32;}
void* arr(const std::vector<void*>&v){void*p=make("System.Array");put(p,16,static_cast<void*>(nullptr));put<uintptr_t>(p,24,v.size());if(!v.empty())std::memcpy(mp4_array_data(p),v.data(),v.size()*8);return p;}
void* ints(){void*p=make("System.Int32[]");put(p,16,static_cast<void*>(nullptr));put<uintptr_t>(p,24,7);for(int i=0;i<7;++i)put<int32_t>(p,32+i*4,100+i);return p;}
void mp4_camera_barrier(void*p,void**slot,void*v){assert(mp4_actor_mapped(slot,8,true));assert(p);std::memcpy(slot,&v,8);}
bool mp4_prefix(const mp4game::Binding&){return true;}bool mp4_hook_was_statically_verified(const mp4game::Binding&){return true;}
void* mp4_resolved_type_class(const mp4camp::Binding&,const char*space,const char*name){return klass(std::string(space)+(*space?".":"")+name);}
using Mp4CameraStatic=void(*)(void*,void*);using Mp4CameraFlag=uint32_t(*)(void*);using Mp4CameraOffset=size_t(*)(void*);
void* field_lookup(void*,const char*n){return &bloomFields[std::strcmp(n,"_BloomMipUp")==0?0:1];}void*method_lookup(void*,const char*,int){return reinterpret_cast<void*>(1);}void* allocate(void*c){return make(static_cast<Klass*>(c)->name,false);}
void*(*font_field)(void*,const char*)=field_lookup;void*(*font_method)(void*,const char*,int)=method_lookup;void*(*font_new)(void*)=allocate;
template<class F>F mp4_cam_call(const mp4camp::Binding& b){auto it=calls.find(b.rva);assert(it!=calls.end());return reinterpret_cast<F>(it->second);}
struct Mp4SceneWitness{uint64_t generation=7;void*controller=nullptr;};Mp4SceneWitness witness;
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation==b.generation&&a.controller==b.controller;}
namespace idoly_mp4_runtime{struct Game{bool selected_scene_witness(Mp4SceneWitness&v){v=witness;return current;}}game;struct Job{uint64_t generation=11;}job;}
struct CameraHost{bool verified=true;Mp4SceneWitness source;}mp4_camera_host;
struct Mono{template<class F>bool isolate(F f){f();return true;}}mp4_actor_mono_gate;
bool(*mp4_camera_renderer_inputs_witness)()=nullptr;
void* source_get(void*,Method*){return sourceRenderer;}void*(*mp4_selected_renderer_original)(void*,Method*)=source_get;mp4cam::RendererPublication mp4_renderer_publication;
bool(*mp4_private_constructor_scope)()noexcept=nullptr;bool(*mp4_private_material_before)(void*,void*)=nullptr;bool(*mp4_private_library_before)(void*,void*)=nullptr;
void material_ctor(void*p,void*,Method*){put(p,16,nextnative++);}void library_ctor(void*,void*,Method*){}
void(*mp4_material_ctor_shader_original)(void*,void*,Method*)=material_ctor;void(*mp4_render_library_ctor_original)(void*,void*,Method*)=library_ctor;
#include "private_renderer_host.inc"
void* get_asset(Method*){return asset;}void* clone_object(void*p,Method*){int at=clone_count++;if(at==fail_clone)return nullptr;void*v=make(static_cast<Object*>(p)->klass->name);uintptr_t n=get<uintptr_t>(v,16);std::memcpy(v,p,sizeof(Object));put(v,16,n);return v;}
void destroy_object(void*p,bool,Method*){assert(p!=sourceData&&p!=sourcePost&&p!=sourceRenderer&&p!=additional);if(mp4_alive(p)){put<uintptr_t>(p,16,0);++destroy_count;}}
bool warmed(void*,Method*){return true;}bool structured(Method*){return false;}int rank(void*){return 1;}void*element(void*){return klass("System.Int32");}int value_size(void*,uint32_t*a){*a=4;return 4;}
void static_get(void*p,void*out){std::memcpy(out,&static_cast<StaticField*>(p)->value,8);}void static_set(void*p,void*v){static_cast<StaticField*>(p)->value=v;}uint32_t field_flags(void*){return 16;}size_t field_offset(void*p){return static_cast<StaticField*>(p)->at;}
void dispose(void*,bool,Method*){++dispose_count;}void reset(void*p,Method*){put(p,mp4camp::RenderLayout::post_reset,true);++reset_count;}
std::string typename_of(const mp4camp::TypeName&n){return std::string(n.space)+(*n.space?".":"")+n.leaf;}
void* mat(bool own,void*shader){void*m=make("UnityEngine.Material",!own);if(own){assert(mp4_private_constructor_scope&&mp4_private_constructor_scope());assert(mp4_private_material_before(m,shader));if(material_seq++==ctor_fail_material)throw std::runtime_error("material native throw");material_ctor(m,shader,nullptr);}return m;}
void build_root(void*r,void*data,bool own){void*post=get<void*>(data,48);void*compute=get<void*>(post,96);size_t s=0;
 for(size_t at:{size_t(952),size_t(960),size_t(968),size_t(976),size_t(1000),size_t(1008)})put(r,at,mat(own,shaderInputs[s++%21]));
 void*lut=make(typename_of(mp4camp::type_names.lut_pass));put(r,152,lut);put(lut,128,mat(own,shaderInputs[s++%21]));put(lut,136,mat(own,shaderInputs[s++%21]));void*c=make(typename_of(mp4camp::type_names.compute_pass));put(r,160,c);put(c,128,compute);
 for(size_t at:{size_t(328),size_t(336)}){void*p=make(typename_of(mp4camp::type_names.post_process));void*l=make(typename_of(mp4camp::type_names.post_library));if(own){assert(mp4_private_library_before(l,post));library_ctor(l,post,nullptr);}put(r,at,p);put(p,376,l);put(p,384,post);put(p,536,get<void*>(r,952));for(size_t j=16;j<=112;j+=8)put(l,j,mat(own,shaderInputs[s++%21]));}
 void*l=make(typename_of(mp4camp::type_names.forward_lights));put(r,mp4camp::RenderLayout::renderer_forward_lights,l);for(uint32_t at:mp4camp::RenderLayout::forward_light_arrays)put(l,at,arr({}));
}
void root_ctor(void*r,void*data,Method*){if(fail_root)throw std::runtime_error("root early throw");bloomFields[0].value=ints();if(fail_ctor)throw std::runtime_error("middle static throw");bloomFields[1].value=ints();build_root(r,data,true);if(lose_after_ctor)current=false;}
template<class F>void bind(const mp4camp::Binding&b,F f){calls[b.rva]=reinterpret_cast<uintptr_t>(f);}
void setup(){assert(roots.empty());heap.clear();calls.clear();current=phase=program=fence=drawfence=true;fail_ctor=fail_root=lose_after_ctor=false;fail_clone=-1;clone_count=destroy_count=dispose_count=reset_count=material_seq=0;ctor_fail_material=-1;
 for(auto*&s:shaderInputs){s=make("UnityEngine.Shader");}
 sourceData=make("VL.Rendering.VLSRPRendererData");sourcePost=make("VL.Rendering.VLPostProcessData");void*rs=make("ForwardResources"),*ps=make("PostResources");put(sourceData,64,rs);put(sourcePost,24,ps);size_t n=0;for(uint32_t at:mp4camp::RenderLayout::renderer_ctor_shaders)put(rs,at,shaderInputs[n++]);put(sourceData,104,shaderInputs[n++]);for(uint32_t at:mp4camp::RenderLayout::post_standard_shaders)put(ps,at,shaderInputs[n++]);for(uint32_t at:mp4camp::RenderLayout::post_vl_shaders)put(sourcePost,at,shaderInputs[n++]);assert(n==21);
 put(sourceData,32,make("System.Collections.Generic.List`1"));put(sourceData,40,make("System.Collections.Generic.List`1"));put(sourceData,48,sourcePost);put(sourcePost,96,make("UnityEngine.ComputeShader"));put<uint8_t>(sourcePost,88,1);
 sourceRenderer=make(typename_of(mp4camp::type_names.renderer));build_root(sourceRenderer,sourceData,false);additional=make("UnityEngine.Rendering.Universal.UniversalAdditionalCameraData");put<int32_t>(additional,56,-1);asset=make("UnityEngine.Rendering.Universal.UniversalRenderPipelineAsset");put(asset,32,arr({sourceRenderer}));put(asset,64,arr({sourceData}));put<int32_t>(asset,72,0);witness={7,make("Controller")};put(witness.controller,mp4camp::RenderLayout::controller_additional,additional);mp4_camera_host.source=witness;mp4_camera_host.verified=true;idoly_mp4_runtime::job.generation=11;
 bloomFields[0].value=ints();bloomFields[1].value=ints();
 bind(mp4_cam_profile.render_asset,get_asset);bind(mp4_cam_profile.instantiate,clone_object);bind(mp4_cam_profile.object_destroy_immediate,destroy_object);bind(mp4_cam_profile.shader_variant_warmed,warmed);bind(mp4_cam_profile.use_structured_buffer,structured);bind(mp4_cam_profile.class_rank,rank);bind(mp4_cam_profile.class_element,element);bind(mp4_cam_profile.class_value_size,value_size);bind(mp4_cam_profile.field_static_get,static_get);bind(mp4_cam_profile.field_static_set,static_set);bind(mp4_cam_profile.field_flags,field_flags);bind(mp4_cam_profile.field_offset,field_offset);bind(mp4_cam_profile.renderer_ctor,root_ctor);bind(mp4_cam_profile.renderer_dispose,dispose);bind(mp4_cam_profile.post_process_reset,reset);
 mp4_renderer_source_program_verified=[](){return program;};mp4_renderer_draw_fence_ready=[](uint64_t e,uint64_t j){return e==7&&j==11&&drawfence;};mp4_renderer_final_fence_ready=[](uint64_t e,uint64_t j){return e==7&&j==11&&fence;};
}
void cleanup(){fence=true;assert(mp4_renderer_release(false)==mp4cam::Result::ok);assert(roots.empty());assert(mp4_alive(sourceData)&&mp4_alive(sourcePost)&&mp4_alive(sourceRenderer)&&mp4_alive(additional));}
int main(){unsigned cases=0;
 {setup();void*old[]={bloomFields[0].value,bloomFields[1].value};assert(mp4_renderer_capture());assert(mp4_renderer_prepare()==mp4cam::Result::ok);assert(mp4_private_renderer.construction.material_count()==34&&mp4_private_renderer.construction.library_count()==2);assert(bloomFields[0].value==old[0]&&bloomFields[1].value==old[1]);assert(mp4_renderer_publication.resolve(additional).renderer==mp4_private_renderer.construction.root());drawfence=false;assert(mp4_renderer_reset_after_prewarm()==mp4cam::Result::waiting&&!reset_count);drawfence=true;assert(mp4_renderer_reset_after_prewarm()==mp4cam::Result::ok&&reset_count==2);assert(mp4_renderer_restore()==mp4cam::Result::ok&&mp4_renderer_verify_restored());fence=false;assert(mp4_renderer_release(true)==mp4cam::Result::waiting&&!dispose_count);cleanup();assert(dispose_count==1&&destroy_count==37);++cases;}
 for(int i=0;i<3;++i){setup();assert(mp4_renderer_capture());fail_clone=i;assert(mp4_renderer_prepare()==mp4cam::Result::failed);cleanup();assert(!dispose_count&&destroy_count==i);++cases;}
 for(int i=0;i<3;++i){setup();assert(mp4_renderer_capture());if(i==0)fail_root=true;else if(i==1)fail_ctor=true;else ctor_fail_material=15;assert(mp4_renderer_prepare()==mp4cam::Result::failed);cleanup();assert(!dispose_count);++cases;}
 {setup();program=false;assert(!mp4_renderer_capture());cleanup();++cases;}
 {setup();put<int32_t>(additional,56,-2);assert(!mp4_renderer_capture());cleanup();++cases;}
 {setup();assert(mp4_renderer_capture());assert(mp4_renderer_prepare()==mp4cam::Result::ok);auto token=mp4_renderer_begin_draw();assert(token&&mp4_renderer_before_source_change());current=false;assert(mp4_renderer_release(false)==mp4cam::Result::waiting&&!dispose_count);assert(mp4_renderer_end_draw(token));cleanup();assert(dispose_count==1);++cases;}
 {setup();assert(mp4_renderer_capture());assert(mp4_renderer_prepare()==mp4cam::Result::ok);mp4_renderer_abandon_globals();current=false;fence=false;assert(mp4_renderer_release(false)==mp4cam::Result::waiting);cleanup();++cases;}
 {setup();assert(mp4_renderer_capture());put(sourceData,104,make("UnityEngine.Shader"));assert(mp4_renderer_prepare()==mp4cam::Result::stale);cleanup();++cases;}
 {setup();assert(mp4_renderer_capture());lose_after_ctor=true;assert(mp4_renderer_prepare()==mp4cam::Result::failed);cleanup();assert(dispose_count==1);++cases;}
 {setup();assert(mp4_renderer_capture());void* data=nullptr;void* valid=bloomFields[0].value;assert(mp4_renderer_int_array7(valid,&data));void* bad=arr({});assert(!mp4_renderer_int_array7(bad,&data));put<uintptr_t>(valid,24,6);assert(!mp4_renderer_int_array7(valid,&data));put<uintptr_t>(valid,24,7);cleanup();++cases;}
 std::printf("%u concrete Renderer host ownership/lifecycle scenarios passed; modeled ctor/CAPI, no device/GPU claim\n",cases);
}
