int main(int argc,char**argv){assert(argc==2);initialize();const std::string mode=argv[1];Mp4ShaderConsumerHost host;
 if(mode=="root_failure")root_fail_after=3;
 if(mode=="scene"||mode=="scene_changed"||mode=="scene_unknown"||mode=="scene_compute"){
  downloaded=false;scene_admitted=mode!="scene_unknown";put(material,32,static_cast<void*>(shader_b));
  if(mode=="scene_compute"){assert(!mp4_consumer_program(host,shader_b,true));return 0;}
 }
 if(mode=="downloaded")put(material,32,static_cast<void*>(shader_b));
 if(mode=="builtin")put(material,32,static_cast<void*>(shader_d));
 if(mode=="unknown"||mode=="disabled"||mode=="inactive"||mode=="unculled")put(material,32,static_cast<void*>(shader_c));
 if(mode=="disabled")enabled=false;if(mode=="inactive")hierarchy=false;if(mode=="unculled")mask=0;
 if(mode=="unknown_pass_shader")put(pass,48,static_cast<void*>(shader_c));
 if(mode=="null_material")shared_materials->items[0]=nullptr;
 if(mode=="skybox"){clear_flags=1;sky=material;}
 if(mode=="unknown_skybox"){clear_flags=1;sky=obj(static_cast<Class*>(object_class(material)));put(sky,16,uintptr_t(sky));put(sky,32,static_cast<void*>(shader_c));}
 if(mode=="config"){put(config_class_blob,224,uint32_t(1));static_cast<Class*>(config_class_blob)->fields["ms_Instance"].value=config;put(config,144,static_cast<void*>(shader_c));put(material,32,static_cast<void*>(shader_c));}
 if(mode=="queue"){auto*l=list(cls("System.Collections.Generic.List`1"),array(cls("System.Array"),{pass}));put(runtime_renderer,64,static_cast<void*>(l));}
 if(mode=="unknown_queue"){auto*l=list(cls("System.Collections.Generic.List`1"),array(cls("System.Array"),{obj(cls("ForeignPass"))}));put(runtime_renderer,64,static_cast<void*>(l));}
 if(mode=="vlb"||mode=="vlb_unknown"){
  mp4_vlb_state.started=true;mp4_vlb_state.batch_count=1;auto*draw=obj(cls("Draw"));put(draw,16,static_cast<void*>(material));mp4_vlb_state.batches[0].draw_images[0]={draw,material};
  if(mode=="vlb_unknown"){auto*m=obj(static_cast<Class*>(object_class(material)));put(m,16,uintptr_t(m));put(m,32,static_cast<void*>(shader_c));put(draw,16,static_cast<void*>(m));mp4_vlb_state.batches[0].draw_images[0].material=m;}
 }
 const bool accepted=mode!="root_failure"&&mode!="scene_unknown"&&mode!="unknown"&&mode!="unknown_pass_shader"&&mode!="null_material"&&mode!="unknown_skybox"&&mode!="unknown_queue"&&mode!="vlb_unknown";
 assert(mp4_shader_consumer_capture(host,&host,42,9,current,held)==accepted);
 if(!accepted){assert(roots.empty());return 0;}
 assert(mp4_shader_consumer_current(host));
 if(mode=="scene_changed"){scene_admitted=false;assert(!mp4_shader_consumer_current(host));}
 else if(mode=="role_changed"){put(feature,32,static_cast<void*>(shader_c));assert(!mp4_shader_consumer_current(host));}
 else if(mode=="shader_id_changed"){put(shader_a,8,int32_t(2));assert(!mp4_shader_consumer_current(host));}
 else if(mode=="shader_native_changed"){put(shader_a,16,uintptr_t(999));assert(!mp4_shader_consumer_current(host));}
 else if(mode=="material_shader_changed"){put(material,32,static_cast<void*>(shader_c));assert(!mp4_shader_consumer_current(host));}
 else if(mode=="source_changed"){current_scene.generation++;assert(!mp4_shader_consumer_current(host));}
 else if(mode=="unheld"){held_now=false;assert(!mp4_shader_consumer_current(host));}
 else if(mode=="owner_lost"){source_now=false;assert(!mp4_shader_consumer_current(host));}
 else if(mode=="unknown_node"){pass->klass=cls("UnknownPass");assert(!mp4_shader_consumer_current(host));}
 else if(mode=="builtin_changed"){put(builtin_material,32,static_cast<void*>(shader_c));assert(!mp4_shader_consumer_current(host));}
 else if(mode=="source_program_changed"){source_program=false;assert(!mp4_shader_consumer_current(host));}
 else assert(mode=="scene"||mode=="normal"||mode=="downloaded"||mode=="builtin"||mode=="disabled"||mode=="inactive"||mode=="unculled"||mode=="skybox"||mode=="config"||mode=="queue"||mode=="vlb");
 mp4_shader_consumer_clear(host);assert(roots.empty());
}
