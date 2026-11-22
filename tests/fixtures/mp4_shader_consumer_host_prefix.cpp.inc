#include "mp4_actor_state.hpp"
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cmath>
#include <array>
#include <vector>
#include <string>
#include <map>
#include <memory>
#include <initializer_list>
struct Class;
struct Blob {std::array<unsigned char,1024> memory{};Class*klass=nullptr;bool alive=true;std::vector<void*>items;};
struct Field {size_t offset=0;uint32_t flags=0;Class*declared=nullptr;void*value=nullptr;};
struct Class:Blob {std::string name;Class*parent=nullptr;std::map<std::string,Field>fields;};
std::vector<std::unique_ptr<Blob>> objects;
std::vector<std::unique_ptr<Class>> classes;
std::map<void*,Blob*> memory;
Class*cls(const char*n,Class*parent=nullptr){auto p=std::make_unique<Class>();p->name=n;p->parent=parent;auto*r=p.get();memory[r]=r;classes.push_back(std::move(p));return r;}
Blob*obj(Class*c){auto p=std::make_unique<Blob>();p->klass=c;auto*r=p.get();memory[r]=r;objects.push_back(std::move(p));return r;}
template<class T>void put(void*p,size_t at,T value){assert(memory.count(p)&&at+sizeof(T)<=1024);std::memcpy(memory[p]->memory.data()+at,&value,sizeof(T));}
bool live=true,thread=true,prefix=true,mutate_queue=false,mutate_static=false;
void*queue_for_mutation=nullptr,*method_for_mutation=nullptr;Field*static_for_mutation=nullptr;
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){auto i=memory.find(p);if(i==memory.end()||at+sizeof(T)>1024)return false;
 std::memcpy(&out,i->second->memory.data()+at,sizeof(T));
 if(mutate_queue&&p==method_for_mutation&&at==32){uint32_t v=0;std::memcpy(&v,memory[queue_for_mutation]->memory.data()+28,4);put(queue_for_mutation,28,v+1);mutate_queue=false;}
 return true;}
void*object_class(void*p){auto i=memory.find(p);return i==memory.end()?nullptr:i->second->klass;}
bool mp4_type_is(void*p,const char*n){auto*c=static_cast<Class*>(object_class(p));for(;c;c=c->parent)if(c->name==n)return true;return false;}
bool mp4_exact_type(void*p,const char*n){auto*c=static_cast<Class*>(object_class(p));return c&&c->name==n;}
bool mp4_alive(void*p){return memory.count(p)&&memory[p]->alive;}
bool mp4_actor_mapped(const void*p,size_t,bool){return p!=nullptr;}
size_t mp4_array_length(void*p){assert(memory.count(p));return memory[p]->items.size();}
void*mp4_array_data(void*p){assert(memory.count(p));return memory[p]->items.data();}
bool mp4_actor_list(void*p,void***out,size_t*n,size_t maximum){void*a=nullptr;int32_t count=0;if(!mp4_actor_field(p,16,a)||!a||!mp4_actor_field(p,24,count)||count<0||size_t(count)>maximum||!mp4_type_is(a,"System.Array")||size_t(count)>mp4_array_length(a))return false;*out=static_cast<void**>(mp4_array_data(a));*n=size_t(count);return true;}
uint32_t next_root=0;std::map<uint32_t,void*>roots;int root_fail_after=-1;
bool retained(void*p){for(const auto&entry:roots)if(entry.second==p)return true;return false;}
uint32_t mp4_retain(void*p){if(root_fail_after==0)return 0;if(root_fail_after>0)--root_fail_after;roots[++next_root]=p;return next_root;}
void*weak_get(uint32_t t){auto i=roots.find(t);return i==roots.end()?nullptr:i->second;}
void weak_free(uint32_t t){assert(roots.erase(t)==1);}
struct Mp4ActorTempRoot {uint32_t h=0;explicit Mp4ActorTempRoot(void*p):h(p?mp4_retain(p):0){}~Mp4ActorTempRoot(){if(h)weak_free(h);}void*get()const{return h?weak_get(h):nullptr;}};
Field*find_field(Class*c,const char*n){for(;c;c=c->parent){auto i=c->fields.find(n);if(i!=c->fields.end())return &i->second;}return nullptr;}
void*field(void*k,const char*n){return find_field(static_cast<Class*>(k),n);}
void*field_type(void*p){return static_cast<Field*>(p)->declared;}void*class_type(void*p){return p;}
void*(*font_field)(void*,const char*)=field;void*(*font_field_type)(void*)=field_type;void*(*font_class_type)(void*)=class_type;
uint32_t field_flags(void*p){return static_cast<Field*>(p)->flags;}size_t field_offset(void*p){return static_cast<Field*>(p)->offset;}
void field_get(void*p,void*out){std::memcpy(out,&static_cast<Field*>(p)->value,sizeof(void*));}
namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};struct Layout{uint32_t player_binder=88,binder_actors=64;};}
struct Mp4SrpPins{mp4game::Binding manager,pipeline,controller,outline,actor,foot,frame,outline_begin,outline_update,aabb,foot_apply;}mp4_srp_pins;
struct{mp4game::Binding field_flags,field_offset,field_static_get;}mp4_cam_profile;
struct{struct{uint32_t actor_extensions=64;}fields;mp4game::Binding material_shader;}mp4_actor_profile;
uintptr_t image_base=0;
bool mp4_source_verified=true,mp4_actor_source_verified=true;
bool game_call(){return thread;}bool mp4_prefix(const mp4game::Binding&){return prefix;}bool mp4_hook_was_statically_verified(const mp4game::Binding&){return false;}
std::map<uintptr_t,Class*> resolved;
void*mp4_resolved_type_class(const mp4game::Binding&p,const char*,const char*){if(mutate_static&&p.rva==mp4_srp_pins.outline.rva){static_for_mutation->value=nullptr;mutate_static=false;}auto i=resolved.find(p.rva);return i==resolved.end()?nullptr:i->second;}
struct Mp4SceneWitness{void*player=nullptr,*controller=nullptr,*camera=nullptr;uint64_t generation=7;};
struct Mp4OriginalRendererSource{Mp4SceneWitness scene{};void*asset=nullptr,*camera=nullptr,*data=nullptr,*post=nullptr,*renderer=nullptr,*features=nullptr;};
Mp4SceneWitness current_scene{};
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.player==b.player&&a.controller==b.controller&&a.camera==b.camera&&a.generation==b.generation;}
namespace idoly_mp4_runtime{struct Game{bool selected_scene_witness(Mp4SceneWitness&w){w=current_scene;return live;}}game;}

bool mp4_actor_refresh_maps(){return thread;}
namespace mp4shader=idoly_mp4_shader_lineage;
using Method=const void;
struct Mp4ConsumerField{const char*name;uint16_t offset;uint8_t kind;};
struct Mp4ConsumerSchema{mp4game::Binding type;const char*space;const char*name;const Mp4ConsumerField*fields;uint16_t count;};
const Mp4ConsumerField renderer_fields[]={{"pass",16,5},{"queue",64,7}};
const Mp4ConsumerField feature_fields[]={{"shader",32,3},{"pass",40,5}};
const Mp4ConsumerField pass_fields[]={{"material",16,1},{"shader",48,3}};
const Mp4ConsumerSchema mp4_consumer_schemas[]={{{201,{}} ,"","Renderer",renderer_fields,2},{{202,{}} ,"","Feature",feature_fields,2},{{203,{}} ,"","Pass",pass_fields,2}};
struct{mp4game::Binding renderer_type,config_type,shared_materials,renderer_enabled,component_object,active_hierarchy,layer,culling,clear_flags,skybox,builtin,default_material,default_particle,default_line;}mp4_consumer_calls;
struct{mp4game::Binding instance_id;}mp4_shader_lineage_pins;
struct{mp4game::Binding find_all;}mp4_renderer_message_pins;
namespace mp4camp{struct RenderLayout{
 static constexpr uint32_t renderer_data_shaders=32,post_shaders=32,renderer_data_blend_shader=40,post_compute_shader=40;
 inline static constexpr uint32_t renderer_ctor_shaders[]={16},post_standard_shaders[]={16},post_vl_shaders[]={48};};}
bool source_program=true,held_now=true,source_now=true,downloaded=true,enabled=true,hierarchy=true,stage_now=true,root_dead=false;
int32_t mask=-1,clear_flags=2;void*sky=nullptr;
Blob *player,*camera,*controller,*pass_material,*shader_a,*shader_b,*shader_c,*shader_d,*material,*builtin_material,*mesh_renderer,*game_object,*renderers,*shared_materials,*reflection_type,*runtime_renderer,*feature,*pass,*config,*config_class_blob;
Mp4OriginalRendererSource consumer_source{};
struct{bool started=false;size_t batch_count=0;struct{struct{void*object=nullptr,*material=nullptr;}draw_images[432];}batches[1];}mp4_vlb_state;
bool mp4_stage_vlb_current(){return stage_now;}
bool mp4_renderer_source_program_closed(){return source_program;}
bool mp4_original_renderer_source_detail(Mp4OriginalRendererSource&value){value=consumer_source;return live;}
bool mp4_renderer_srp_code(const mp4game::Binding&){return prefix;}
bool mp4_renderer_srp_field(void*k,const char*n,size_t offset,bool statik,void*&out){auto*f=find_field(static_cast<Class*>(k),n);out=f;return f&&f->offset==offset&&((f->flags&16u)!=0)==statik;}
bool mp4_renderer_srp_list(void*list,void**&items,size_t&count,void*&array,uint32_t&version,size_t maximum){return mp4_actor_field(list,16,array)&&mp4_actor_field(list,28,version)&&mp4_actor_list(list,&items,&count,maximum);}
bool mp4_renderer_srp_list_same(void*list,void*array,uint32_t version,void*const*items,size_t count,size_t maximum){void**now=nullptr,*a=nullptr;size_t n=0;uint32_t v=0;if(!mp4_renderer_srp_list(list,now,n,a,v,maximum)||a!=array||v!=version||n!=count)return false;for(size_t i=0;i<n;++i)if(now[i]!=items[i])return false;return true;}
bool mp4_shader_downloaded_program(void*p){return downloaded&&p==shader_b;}
int32_t instance_id(void*p,Method*){assert(retained(p));int32_t id=0;assert(mp4_actor_field(p,8,id));return id;}
void*material_shader(void*p,Method*){if(p==builtin_material)assert(retained(p));void*shader=nullptr;assert(mp4_actor_field(p,32,shader));return shader;}
void*builtin(Method*){return builtin_material;}
void*find_all(void*p,Method*){assert(p==reflection_type);return renderers;}
void*reflection(const void*p){assert(p==reinterpret_cast<void*>(401));return reflection_type;}
void*(*mp4_type_get_object)(const void*)=reflection;
void*shared(void*p,Method*){assert(p==mesh_renderer);return shared_materials;}
bool render_enabled(void*,Method*){return enabled;}
void*component_object(void*,Method*){return game_object;}
bool active_hierarchy(void*,Method*){return hierarchy;}
int32_t get_layer(void*,Method*){return 2;}int32_t culling(void*,Method*){return mask;}int32_t flags(void*,Method*){return clear_flags;}
void*skybox(Method*){return sky;}
bool current(void*,uint64_t epoch,uint64_t job){return source_now&&epoch==42&&job==9;}
bool held(void*,uint64_t epoch,uint64_t job){return held_now&&epoch==42&&job==9;}
Blob*array(Class*c,std::initializer_list<void*>items){auto*a=obj(c);a->items=items;return a;}
Blob*list(Class*c,Blob*a){auto*l=obj(c);put(l,16,static_cast<void*>(a));put(l,24,int32_t(a->items.size()));put(l,28,uint32_t(1));return l;}
void initialize(){
 auto*shader=cls("UnityEngine.Shader"),*mat=cls("UnityEngine.Material"),*renderer=cls("Renderer"),*feat=cls("Feature"),*passc=cls("Pass");
 resolved[201]=renderer;resolved[202]=feat;resolved[203]=passc;
 renderer->fields["pass"]={16,0,nullptr,nullptr};renderer->fields["queue"]={64,0,nullptr,nullptr};
 feat->fields["shader"]={32,0,nullptr,nullptr};feat->fields["pass"]={40,0,nullptr,nullptr};passc->fields["material"]={16,0,nullptr,nullptr};passc->fields["shader"]={48,0,nullptr,nullptr};
 auto*cfg=cls("VLB.Config");resolved[402]=cfg;cfg->fields["ms_Instance"]={0,16,nullptr,nullptr};cfg->fields["_BeamShader"]={144,0,nullptr,nullptr};config=obj(cfg);config_class_blob=cfg;
 shader_a=obj(shader);shader_b=obj(shader);shader_c=obj(shader);shader_d=obj(shader);
 for(auto*s:{shader_a,shader_b,shader_c,shader_d}){put(s,16,uintptr_t(s));put(s,8,int32_t(1));}
 material=obj(mat);builtin_material=obj(mat);put(material,16,uintptr_t(material));put(builtin_material,16,uintptr_t(builtin_material));put(material,32,static_cast<void*>(shader_a));put(builtin_material,32,static_cast<void*>(shader_d));
 runtime_renderer=obj(renderer);feature=obj(feat);pass=obj(passc);put(runtime_renderer,16,static_cast<void*>(pass));put(feature,32,static_cast<void*>(shader_a));put(feature,40,static_cast<void*>(pass));pass_material=obj(mat);put(pass_material,16,uintptr_t(pass_material));put(pass_material,32,static_cast<void*>(shader_a));put(pass,16,static_cast<void*>(pass_material));
 auto*arr=cls("System.Array");auto*listc=cls("System.Collections.Generic.List`1");auto*features=list(listc,array(arr,{feature}));
 auto*data=obj(cls("Data")),*post=obj(cls("Post")),*resources=obj(cls("ShaderResources")),*postres=obj(cls("PostShaders"));
 put(data,32,static_cast<void*>(resources));put(data,40,static_cast<void*>(shader_a));put(post,32,static_cast<void*>(postres));put(postres,16,static_cast<void*>(shader_a));put(post,48,static_cast<void*>(shader_a));put(resources,16,static_cast<void*>(shader_a));
 camera=obj(cls("UnityEngine.Camera"));put(camera,16,uintptr_t(camera));player=obj(cls("Player"));controller=obj(cls("Controller"));current_scene={player,controller,camera,7};consumer_source.scene=current_scene;consumer_source.camera=camera;consumer_source.data=data;consumer_source.post=post;consumer_source.features=features;consumer_source.renderer=runtime_renderer;
 reflection_type=obj(cls("System.Type"));game_object=obj(cls("UnityEngine.GameObject"));mesh_renderer=obj(cls("UnityEngine.Renderer"));put(game_object,16,uintptr_t(game_object));put(mesh_renderer,16,uintptr_t(mesh_renderer));renderers=array(arr,{mesh_renderer});shared_materials=array(cls("UnityEngine.Material[]",arr),{material});
 mp4_consumer_calls.renderer_type.rva=401;mp4_consumer_calls.config_type.rva=402;
 mp4_consumer_calls.shared_materials.rva=reinterpret_cast<uintptr_t>(shared);mp4_consumer_calls.renderer_enabled.rva=reinterpret_cast<uintptr_t>(render_enabled);mp4_consumer_calls.component_object.rva=reinterpret_cast<uintptr_t>(component_object);mp4_consumer_calls.active_hierarchy.rva=reinterpret_cast<uintptr_t>(active_hierarchy);mp4_consumer_calls.layer.rva=reinterpret_cast<uintptr_t>(get_layer);mp4_consumer_calls.culling.rva=reinterpret_cast<uintptr_t>(culling);mp4_consumer_calls.clear_flags.rva=reinterpret_cast<uintptr_t>(flags);mp4_consumer_calls.skybox.rva=reinterpret_cast<uintptr_t>(skybox);mp4_consumer_calls.default_material.rva=mp4_consumer_calls.default_particle.rva=mp4_consumer_calls.default_line.rva=reinterpret_cast<uintptr_t>(builtin);
 mp4_renderer_message_pins.find_all.rva=reinterpret_cast<uintptr_t>(find_all);mp4_shader_lineage_pins.instance_id.rva=reinterpret_cast<uintptr_t>(instance_id);mp4_actor_profile.material_shader.rva=reinterpret_cast<uintptr_t>(material_shader);mp4_cam_profile.field_static_get.rva=reinterpret_cast<uintptr_t>(field_get);
}
