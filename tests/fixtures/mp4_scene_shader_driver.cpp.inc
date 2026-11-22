Class *array_class,*string_class,*bundle_class,*request_class,*operation_class,*api_class,*go_class,*transform_class,*mesh_class,*particle_class,*material_class,*shader_class;
Obj *bundle,*request,*operation,*api,*bytes,*loaded_name,*all_bundles,*scene_roots,*gobo,*particle,*smoke,*gobo_renderer,*particle_renderer,*smoke_renderer,*shader_a,*shader_b,*shader_c;
int original_calls=0,original_event_calls=0;Method*expected_method=reinterpret_cast<Method*>(uintptr_t(0xbad));
Obj*named(Class*c,const char*name){auto*p=obj(c);p->text=name;put(p,16,uintptr_t(p));put(p,8,int32_t(objects.size()));return p;}
Obj*array(std::initializer_list<void*>items,Class*c=nullptr){auto*p=obj(c?c:array_class);p->items=items;return p;}
int32_t instance(void*p,Method*){assert(retained(p));int32_t id=0;assert(mp4_actor_field(p,8,id));return id;}
void*reflect(const void*p){auto i=resolved.find(uintptr_t(p)-image_base);assert(i!=resolved.end());return named(cls("System.Type"),i->second->name.c_str());}
void*find_all(void*,Method*){return all_bundles;}
bool bundle_scene(void*p,Method*){return memory[p]->scene;}
void*object_name(void*p,Method*){return named(string_class,memory[p]->text.c_str());}
void*object_transform(void*p,Method*){return p;}
int32_t child_count(void*p,Method*){return int32_t(memory[p]->children.size());}
void*child_get(void*p,int32_t i,Method*){return memory[p]->children.at(size_t(i));}
void*component_object(void*p,Method*){return memory[p]->game_object?memory[p]->game_object:p;}
Mp4Scene4 object_scene(void*p,Method*){return {memory[p]->scene_handle};}
bool scene_valid(int32_t h,Method*){return h==11;}
bool scene_ready(int32_t h,Method*){return h==11;}
void*scene_get_roots(Mp4Scene4*p,Method*){assert(p->handle==11);return scene_roots;}
void*scene_name(int32_t h,Method*){assert(h==11);return loaded_name;}
void*components(void*p,void*type,bool,bool,bool,bool,void*,Method*){assert(retained(type));const auto&name=memory[type]->text;std::vector<void*>found;
 for(void*c:memory[p]->components)if(static_cast<Class*>(object_class(c))->name==name)found.push_back(c);
 auto*a=obj(array_class);a->items=found;return a;}
void*shared(void*p,Method*){return memory[p]->materials;}
void*material_shader(void*p,Method*){assert(retained(p));return memory[p]->shader;}
bool shader_supported(void*,Method*){if(reenter){reenter=false;mp4_scene_shader_loaded_event({11},1);}return true;}
void*load_original(void*self,void*name,int32_t index,Mp4LoadScene8 params,bool complete,Method*method){++original_calls;assert(root_fail==0||(retained(self)&&retained(name)));assert(self==api&&name==loaded_name&&index==-1&&params.mode==1&&!complete&&method==expected_method);
 if(original_early_event)mp4_scene_shader_loaded_event({11},1);if(original_throw)throw 77;return operation;}
void loaded_original(Mp4Scene4 scene,int32_t mode,Method*method){++original_event_calls;assert(scene.handle==11&&mode==1&&method==expected_method);}
void unloaded_original(Mp4Scene4,Method*){++original_event_calls;}
void unload_original(void*self,bool,Method*){++original_event_calls;assert(retained(self));}
template<class F>void bind(mp4game::Binding&pin,F fn){pin.rva=reinterpret_cast<uintptr_t>(fn)-image_base;}
bool role_receipt(int32_t handle,uint16_t known,void*source,const Mp4SceneShaderRole&role,void*go,void*renderer,void*material,void*shader,uint64_t*out){
 assert(handle==11&&known==1&&source==bundle&&retained(shader)&&retained(material)&&retained(go));assert(role.material_path_id&&role.shader_path_id);assert(renderer&&material&&shader);*out=source_verified?99:0;return source_verified;
}
void initialize(){
 mp4_scene_shader_role_receipt=role_receipt;
 array_class=cls("System.Array");string_class=cls("System.String");bundle_class=cls("UnityEngine.AssetBundle");request_class=cls("UnityEngine.AssetBundleCreateRequest");operation_class=cls("UnityEngine.AsyncOperation");api_class=cls("UnityEngine.SceneManagement.SceneManagerAPI");go_class=cls("UnityEngine.GameObject");transform_class=cls("UnityEngine.Transform");mesh_class=cls("UnityEngine.MeshRenderer");particle_class=cls("UnityEngine.ParticleSystemRenderer");material_class=cls("UnityEngine.Material");shader_class=cls("UnityEngine.Shader");
 bundle=named(bundle_class,"source");bundle->scene=true;request=named(request_class,"request");operation=named(operation_class,"operation");api=named(api_class,"api");bytes=array({nullptr,nullptr,nullptr,nullptr},cls("System.Byte[]",array_class));std::memcpy(bytes->items.data(),"game",4);loaded_name=named(string_class,"tln_live_thrx-006");all_bundles=array({bundle});
 gobo=named(go_class,"Gobo");particle=named(go_class,"ParticleSystem");smoke=named(go_class,"Smoke");particle->children={smoke};scene_roots=array({gobo,particle});
 gobo_renderer=named(mesh_class,"renderer");particle_renderer=named(particle_class,"renderer");smoke_renderer=named(particle_class,"renderer");gobo->components={gobo_renderer};particle->components={particle_renderer};smoke->components={smoke_renderer};
 shader_a=named(shader_class,"shader");shader_b=named(shader_class,"shader");shader_c=named(shader_class,"shader");int i=0;
 for(auto*r:{gobo_renderer,smoke_renderer,particle_renderer}){auto*m=named(material_class,"material");m->shader=i==0?shader_a:i==1?shader_b:shader_c;++i;r->materials=array({m},cls("UnityEngine.Material[]",array_class));}
 mp4_scene_shader_pins.api_type.rva=201;mp4_scene_shader_pins.mesh_type.rva=202;mp4_scene_shader_pins.particle_type.rva=203;mp4_scene_shader_pins.bundle_type.rva=204;resolved[201]=api_class;resolved[202]=mesh_class;resolved[203]=particle_class;resolved[204]=bundle_class;
 bind(mp4_scene_shader_pins.api_load,load_original);bind(mp4_scene_shader_pins.bundle_scene,bundle_scene);bind(mp4_scene_shader_pins.object_name,object_name);bind(mp4_scene_shader_pins.object_transform,object_transform);bind(mp4_scene_shader_pins.component_children,child_count);bind(mp4_scene_shader_pins.component_child,child_get);bind(mp4_scene_shader_pins.component_object,component_object);bind(mp4_scene_shader_pins.object_scene,object_scene);bind(mp4_scene_shader_pins.scene_valid,scene_valid);bind(mp4_scene_shader_pins.scene_ready,scene_ready);bind(mp4_scene_shader_pins.scene_roots,scene_get_roots);bind(mp4_scene_shader_pins.scene_name,scene_name);bind(mp4_scene_shader_pins.shared_materials,shared);bind(mp4_scene_shader_pins.shader_supported,shader_supported);bind(mp4_actor_profile.get_components_internal,components);bind(mp4_actor_profile.material_shader,material_shader);bind(mp4_shader_lineage_pins.instance_id,instance);bind(mp4_renderer_message_pins.find_all,find_all);
 mp4_scene_shader_load_original=load_original;mp4_scene_shader_loaded_original=loaded_original;mp4_scene_shader_unloaded_original=unloaded_original;mp4_scene_shader_bundle_unload_original=unload_original;
 mp4shader::Sha256 hash;assert(hash.append("game",4));mp4_known_scene_bundles[0].digest=hash.finish();
}
void cleanup(){for(auto&r:mp4_scene_shader_loaded)mp4_scene_shader_loaded_clear(r);for(auto&r:mp4_scene_shader_pending){mp4_scene_shader_drop(r.operation);r={};}for(auto&r:mp4_scene_shader_bundles){mp4_scene_shader_drop(r.object);r={};}for(auto&r:mp4_scene_shader_requests)mp4_scene_shader_request_clear(r);assert(roots.empty());}
bool enter(){if(!mp4_scene_shader_bundle_add(bundle,1,1))return false;auto ticket=mp4_scene_shader_load_begin(api,loaded_name,-1,{1,0},false);if(!ticket.slot)return false;mp4_scene_shader_load_return(ticket,operation,true);mp4_scene_shader_loaded_event({11},1);return mp4_scene_shader_program(shader_a)&&mp4_scene_shader_program(shader_b)&&mp4_scene_shader_program(shader_c);}
int main(int argc,char**argv){assert(argc==2);initialize();const std::string test=argv[1];
 if(test=="normal"){assert(enter());}
 else if(test=="missing_producer_receipt"){mp4_scene_shader_role_receipt=nullptr;assert(!enter());}
 else if(test=="invalid_producer_receipt"){source_verified=false;assert(!enter());}
 else if(test=="memory"){assert(mp4_scene_shader_memory(bytes)==1);std::memcpy(bytes->items.data(),"evil",4);assert(!mp4_scene_shader_memory(bytes));}
 else if(test=="wrong_size"){bytes->items.resize(5);assert(!mp4_scene_shader_memory(bytes));}
 else if(test=="unknown_bundle"){assert(!mp4_scene_shader_bundle_add(bundle,0,0));void*selected=nullptr;assert(!mp4_scene_shader_inventory(1,&selected));}
 else if(test=="input_changed"){assert(!mp4_scene_shader_bundle_add(bundle,1,0));assert(!mp4_scene_shader_foreign_thread.load());}
 else if(test=="duplicate_bundle"){assert(mp4_scene_shader_bundle_add(bundle,1,1));auto*other=named(bundle_class,"other");other->scene=true;all_bundles->items.push_back(other);assert(mp4_scene_shader_bundle_add(other,1,1));assert(!mp4_scene_shader_load_begin(api,loaded_name,-1,{1,0},false).slot);}
 else if(test=="custom_api"){api->klass=cls("CustomAPI",api_class);assert(!mp4_scene_shader_load_begin(api,loaded_name,-1,{1,0},false).slot);}
 else if(test=="bad_parameters"){assert(!mp4_scene_shader_load_begin(api,loaded_name,0,{1,0},false).slot);assert(!mp4_scene_shader_load_begin(api,loaded_name,-1,{0,0},false).slot);assert(!mp4_scene_shader_load_begin(api,loaded_name,-1,{1,1},false).slot);assert(!mp4_scene_shader_load_begin(api,loaded_name,-1,{1,0},true).slot);}
 else if(test=="prefix"){prefix=false;assert(!enter());}
 else if(test=="wrong_path"){smoke->text="other";assert(!enter());}
 else if(test=="wrong_scene"){smoke->scene_handle=12;assert(!enter());}
 else if(test=="duplicate_component"){gobo->components.push_back(named(mesh_class,"other"));assert(!enter());}
 else if(test=="wrong_shader_type"){shader_a->klass=material_class;assert(!enter());}
 else if(test=="root_failure"){root_fail=0;assert(!mp4_scene_shader_bundle_add(bundle,1,1));}
 else if(test=="shader_native_changed"){assert(enter());put(shader_a,16,uintptr_t(123));assert(!mp4_scene_shader_program(shader_a));}
 else if(test=="shader_id_changed"){assert(enter());put(shader_a,8,int32_t(123));assert(!mp4_scene_shader_program(shader_a));}
 else if(test=="foreign_after_load"){assert(mp4_scene_shader_bundle_add(bundle,1,1));auto t=mp4_scene_shader_load_begin(api,loaded_name,-1,{1,0},false);assert(t.slot);mp4_scene_shader_load_return(t,operation,true);auto*foreign=named(bundle_class,"foreign");foreign->scene=true;assert(!mp4_scene_shader_bundle_add(foreign,0,0));mp4_scene_shader_unload_bundle(foreign,false);mp4_scene_shader_loaded_event({11},1);assert(!mp4_scene_shader_program(shader_a));}
 else if(test=="offthread"){assert(enter());mp4_scene_shader_offthread();assert(!mp4_scene_shader_program(shader_a));}
 else if(test=="unloaded"){assert(enter());mp4_scene_shader_unloaded_event({11});assert(!mp4_scene_shader_program(shader_a));}
 else if(test=="bundle_unload_false"){assert(enter());mp4_scene_shader_unload_bundle(bundle,false);assert(mp4_scene_shader_program(shader_a));}
 else if(test=="bundle_unload_true"){assert(enter());mp4_scene_shader_unload_bundle(bundle,true);assert(!mp4_scene_shader_program(shader_a));}
 else if(test=="duplicate_pending"){assert(mp4_scene_shader_bundle_add(bundle,1,1));auto first=mp4_scene_shader_load_begin(api,loaded_name,-1,{1,0},false);assert(first.slot);auto second=mp4_scene_shader_load_begin(api,loaded_name,-1,{1,0},false);assert(!second.slot);mp4_scene_shader_load_return(first,operation,true);mp4_scene_shader_loaded_event({11},1);assert(!mp4_scene_shader_program(shader_a));}
 else if(test=="hook_input_root_failure"){assert(mp4_scene_shader_bundle_add(bundle,1,1));root_fail=0;assert(mp4_scene_shader_load_hook(api,loaded_name,-1,{1,0},false,expected_method)==operation&&original_calls==1&&!mp4_scene_shader_pending_any.load());root_fail=-1;}
 else if(test=="hook"){assert(mp4_scene_shader_bundle_add(bundle,1,1));assert(mp4_scene_shader_load_hook(api,loaded_name,-1,{1,0},false,expected_method)==operation);assert(original_calls==1);mp4_scene_shader_loaded_hook({11},1,expected_method);assert(original_event_calls==1&&mp4_scene_shader_program(shader_a));}
 else if(test=="original_throw"){assert(mp4_scene_shader_bundle_add(bundle,1,1));original_throw=true;try{mp4_scene_shader_load_hook(api,loaded_name,-1,{1,0},false,expected_method);assert(false);}catch(int x){assert(x==77);}assert(original_calls==1&&!mp4_scene_shader_pending_any.load());}
 else if(test=="event_before_return"){assert(mp4_scene_shader_bundle_add(bundle,1,1));original_early_event=true;(void)mp4_scene_shader_load_hook(api,loaded_name,-1,{1,0},false,expected_method);assert(!mp4_scene_shader_program(shader_a)&&!mp4_scene_shader_pending_any.load());}
 else if(test=="stale_ticket"){assert(mp4_scene_shader_bundle_add(bundle,1,1));auto first=mp4_scene_shader_load_begin(api,loaded_name,-1,{1,0},false);assert(first.slot);mp4_scene_shader_load_return(first,nullptr,false);auto second=mp4_scene_shader_load_begin(api,loaded_name,-1,{1,0},false);assert(second.slot==first.slot&&second.serial!=first.serial);mp4_scene_shader_load_return(first,operation,true);assert(second.slot->returning&&!second.slot->operation.root);mp4_scene_shader_load_return(second,operation,true);mp4_scene_shader_loaded_event({11},1);assert(mp4_scene_shader_program(shader_a));}
 else if(test=="reentry"){reenter=true;assert(!enter());assert(mp4_scene_shader_foreign_thread.load());}
 else if(test=="async_memory"){mp4_scene_shader_async_result(request,bytes,1,1,nullptr);assert(retained(request)&&retained(bytes));mp4_scene_shader_bundle_result(request,bundle);assert(!retained(request)&&!retained(bytes));void*out=nullptr;assert(mp4_scene_shader_inventory(1,&out)&&out==bundle);}
 else if(test=="async_memory_changed"){mp4_scene_shader_async_result(request,bytes,1,1,nullptr);std::memcpy(bytes->items.data(),"evil",4);mp4_scene_shader_bundle_result(request,bundle);assert(!mp4_scene_shader_bundles[0].object.root);}
 else if(test=="async_request_changed"){mp4_scene_shader_async_result(request,bytes,1,1,nullptr);put(request,16,uintptr_t(999));mp4_scene_shader_bundle_result(request,bundle);assert(!mp4_scene_shader_bundles[0].object.root);}
 else if(test=="file"){char path[]="/tmp/idoly-scene-shader-XXXXXX";int fd=mkstemp(path);assert(fd>=0&&write(fd,"game",4)==4);close(fd);assert(mp4_scene_shader_file(path,0)==1);fd=open(path,O_WRONLY);assert(fd>=0&&write(fd,"evil",4)==4);close(fd);assert(!mp4_scene_shader_file(path,0));unlink(path);}
 else assert(false);
 cleanup();return 0;
}
