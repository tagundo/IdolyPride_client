#include <cstdint>
#include <cstddef>
#include <cstring>
#include <map>
#include <string>
#include <vector>
#include <cassert>
#include <cstdio>
#include <cstdlib>
struct Method{};namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}
struct Class{const char*name;};Class pfclasses[5]={{"DrawProFlare"},{"ProFlareComputePass"},{"ProFlareRenderPass"},{"ProFlareBatchForSRP"},{"ProFlareBatchForSRPData"}};Class camera_c{"UnityEngine.Camera"},additional_c{"UnityEngine.Rendering.Universal.UniversalAdditionalCameraData"},asset_c{"UnityEngine.Rendering.Universal.UniversalRenderPipelineAsset"},renderer_c{"VL.Rendering.VLSRPRenderer"},data_c{"VL.Rendering.VLSRPRendererData"},post_c{"VL.Rendering.VLPostProcessData"},compute_c{"UnityEngine.ComputeShader"},array_c{"System.Array"},other_c{"other"};
struct Obj{Class*klass;bool alive=true;};Obj camera{&camera_c},controller{&other_c},additional{&additional_c},asset{&asset_c},renderer{&renderer_c},data{&data_c},post{&post_c},compute{&compute_c},features{&other_c},feature_map{&other_c};
Obj pf{&pfclasses[0]},pc{&pfclasses[1]},pr{&pfclasses[2]},pb{&pfclasses[3]},pd{&pfclasses[4]};std::vector<void*>feature_items;
struct Array{Obj object{&array_c};uintptr_t n=1;void*values[2]{};}renderers,data_array;
struct Mp4SceneWitness{void*camera=nullptr,*controller=nullptr;uint64_t generation=0;};Mp4SceneWitness scene{&camera,&controller,7};int source_queries=0,asset_queries=0;bool source_ok=true,source_changed=false,main_thread=true,mp4_source_verified=true,mp4_actor_source_verified=true,prefix_ok=true,mapping=true;
namespace idoly_mp4_runtime{struct Game{bool selected_scene_witness(Mp4SceneWitness&out){++source_queries;out=scene;if(source_changed&&source_queries>1)++out.generation;return source_ok;}}game;}
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.camera==b.camera&&a.controller==b.controller&&a.generation==b.generation;}
std::map<std::pair<void*,size_t>,std::vector<uint8_t>>fields;
template<class T>void put(void*p,size_t at,T v){fields[{p,at}]=std::vector<uint8_t>(sizeof v);std::memcpy(fields[{p,at}].data(),&v,sizeof v);}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){auto it=fields.find({p,at});if(!mapping||it==fields.end()||it->second.size()!=sizeof out)return false;std::memcpy(&out,it->second.data(),sizeof out);return true;}
bool game_call(){return main_thread;}bool mp4_actor_refresh_maps(){return mapping;}bool mp4_actor_mapped(void*,size_t n,bool){return mapping&&n>0;}bool mp4_prefix(const mp4game::Binding&){return prefix_ok;}
bool mp4_alive(void*p){return p&&static_cast<Obj*>(p)->alive;}void*object_class(void*p){return static_cast<Obj*>(p)->klass;}
bool mp4_exact_type(void*p,const char*n){return p&&!std::strcmp(static_cast<Obj*>(p)->klass->name,n);}bool mp4_type_is(void*p,const char*n){return mp4_exact_type(p,n);}
size_t mp4_array_length(void*p){return static_cast<Array*>(p)->n;}void*mp4_array_data(void*p){return static_cast<Array*>(p)->values;}
uintptr_t image_base=0;
void*get_asset(const Method*){++asset_queries;return &asset;}
namespace mp4camp{struct RenderLayout{static constexpr uint32_t controller_additional=96,additional_renderer_index=56,pipeline_renderers=32,pipeline_renderer_data=64,pipeline_default_renderer=72,renderer_data_features=32,renderer_data_feature_map=40,renderer_data_post=48,post_compute_shader=96,renderer_data_mode=92,renderer_mode=936;};}
struct{mp4game::Binding render_asset;}mp4_cam_profile;
struct{mp4game::Binding renderer{1,{}},renderer_data{2,{}},post_data{3,{}},compute_shader{4,{}};}mp4_cam_types;
void*mp4_resolved_type_class(const mp4game::Binding&b,const char*,const char*){if(b.rva>=11&&b.rva<=15)return &pfclasses[b.rva-11];return b.rva==1?&renderer_c:b.rva==2?&data_c:b.rva==3?&post_c:b.rva==4?&compute_c:nullptr;}
mp4game::Binding mp4_renderer_proflare_pins[5]={{11,{}},{12,{}},{13,{}},{14,{}},{15,{}}};
bool mp4_actor_list(void*p,void***items,size_t*count,size_t bound){if(p!=&features||feature_items.size()>bound)return false;*items=feature_items.data();*count=feature_items.size();return true;}
// ACTUAL_ORIGINAL_RENDERER_SOURCE
// ACTUAL_PROFLARE_SOURCE
void setup(){mp4_cam_profile.render_asset.rva=reinterpret_cast<uintptr_t>(&get_asset);put(&controller,96,static_cast<void*>(&additional));put(&additional,56,int32_t(-1));put(&asset,32,static_cast<void*>(&renderers));put(&asset,64,static_cast<void*>(&data_array));put(&asset,72,int32_t(0));put(&data,32,static_cast<void*>(&features));put(&data,40,static_cast<void*>(&feature_map));put(&data,48,static_cast<void*>(&post));put(&post,96,static_cast<void*>(&compute));put(&data,92,int32_t(0));put(&renderer,936,int32_t(0));renderers.values[0]=&renderer;data_array.values[0]=&data;}
int main(int argc,char**argv){assert(argc==2);setup();int c=std::atoi(argv[1]);feature_items={&pf};put(&pf,24,true);put(&pf,48,static_cast<void*>(&pc));put(&pf,56,static_cast<void*>(&pr));put(&pf,80,static_cast<void*>(&pb));put(&pc,136,static_cast<void*>(&pb));put(&pr,136,static_cast<void*>(&pb));put(&pc,144,static_cast<void*>(&pd));put(&pr,144,static_cast<void*>(&pd));put(&pd,24,static_cast<void*>(&camera));bool expected=false,inactive=false,absent=false,nullable=false;
 if(c==0)expected=true;
 else if(c==1){feature_items.clear();expected=absent=true;}
 else if(c==2){put(&pf,24,false);put(&pf,48,static_cast<void*>(nullptr));put(&pf,56,static_cast<void*>(nullptr));expected=inactive=true;}
 else if(c==3)feature_items.push_back(&pf);
 else if(c==4)put(&pf,48,static_cast<void*>(nullptr));
 else if(c==5)put(&pf,56,static_cast<void*>(nullptr));
 else if(c==6)put(&pf,80,static_cast<void*>(nullptr));
 else if(c==7)pb.alive=false;
 else if(c==8)pc.klass=&other_c;
 else if(c==9)pr.klass=&other_c;
 else if(c==10)pb.klass=&other_c;
 else if(c==11)pd.klass=&other_c;
 else if(c==12)put(&pc,136,static_cast<void*>(nullptr));
 else if(c==13)put(&pr,144,static_cast<void*>(nullptr));
 else if(c==14)put(&pd,24,static_cast<void*>(&other_c));
 else if(c==15)source_changed=true;
 else if(c==16)pf.alive=false;
 else if(c==17)feature_items={nullptr};
 else if(c==18)main_thread=false;
 else if(c==19)feature_items.resize(65,&pf);
 else if(c==20){put(&pc,144,static_cast<void*>(nullptr));put(&pr,144,static_cast<void*>(nullptr));expected=nullable=true;}
 else if(c==21){put(&pf,48,static_cast<void*>(nullptr));put(&pf,56,static_cast<void*>(nullptr));}
 else if(c==22){put(&pf,48,static_cast<void*>(nullptr));put(&pf,56,static_cast<void*>(nullptr));fields.erase({&pf,24});}
 else assert(false);
 const auto before=fields;void*f=reinterpret_cast<void*>(1),*a=f,*b=f,*d=f,*e=f;
 bool result=mp4_renderer_proflare_source(&camera,&f,&a,&b,&d,&e);
 assert(result==expected&&fields==before);
 if(!expected||absent)assert(!f&&!a&&!b&&!d&&!e);
 else if(inactive)assert(f==&pf&&!a&&!b&&!d&&!e);
 else assert(f==&pf&&a==&pc&&b==&pr&&d==&pb&&e==(nullable?nullptr:&pd));
 std::printf("case %d passed\n",c);
}
