int main(int argc,char**argv){assert(argc==2);initialize();origin_mode=std::atoi(argv[1]);mp4_scene_shader_origin_install();
 gobo_renderer->game_object=gobo;particle_renderer->game_object=particle;smoke_renderer->game_object=smoke;
 assert(mp4_scene_shader_bundle_add(bundle,1,1));auto t=mp4_scene_shader_load_begin(api,loaded_name,-1,{1,0},false);assert(t.slot);mp4_scene_shader_load_return(t,operation,true);
 mp4_scene_shader_importing=true;
 void*material=memory[gobo_renderer->materials]->items[0];
 if(origin_mode==8)root_fail=0;
 if(origin_mode==9)scene_roots->items={particle};
 if(origin_mode==10)gobo_renderer->game_object=particle;
 if(origin_mode==11)memory[material]->shader=shader_b;
 uint64_t receipt=44;bool ok=mp4_scene_shader_origin_receipt(11,1,bundle,role_rows[0],gobo,gobo_renderer,material,shader_a,&receipt);
 assert(ok==(origin_mode==0));assert((receipt!=0)==ok);assert(!origin_queries||origin_mode!=7);
 if(origin_mode==0){Mp4SceneShaderRole copy=role_rows[0];receipt=44;assert(!mp4_scene_shader_origin_receipt(11,1,bundle,copy,gobo,gobo_renderer,material,shader_a,&receipt)&&!receipt);}
 mp4_scene_shader_importing=false;root_fail=-1;cleanup();std::puts("PASS actual origin-role adapter (modeled native query)");
}
