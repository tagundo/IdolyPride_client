 close_mode=test;audio_mode=(test>=20&&test<=25)||test==12;
 output_count=(test==2||test==3||test==4||test==5)?2:(test==1?0:1);
 mp4_world_profile.graph_output_count.rva=(uintptr_t)output_count_call-image_base;mp4_world_profile.graph_output.rva=(uintptr_t)output_get-image_base;mp4_world_profile.output_type.rva=(uintptr_t)output_type-image_base;
 for(size_t family=0;family<3;++family){mp4_output_types[family]=mp4_retain((void*)(0x50000+family));auto&route=mp4_director_profile.outputs[family];route.vtable=(uintptr_t)tables[family]-mp4_native_base;route.producer.rva=(uintptr_t)producer-mp4_native_base;std::memcpy(route.producer.prefix,(void*)producer,16);tables[family][4]=(uintptr_t)producer;route.count=family==0?2:1;for(size_t k=0;k<route.count;++k){route.callbacks[k].rva=(uintptr_t)callback-mp4_native_base;std::memcpy(route.callbacks[k].prefix,(void*)callback,16);}}
 for(size_t row=0;row<2;++row){auto&r=model.roots[row];const uintptr_t sentinel=(uintptr_t)r.graph_native+0x78;const uintptr_t first=output_count?(uintptr_t)native_outputs[row][0].bytes+8:sentinel,last=output_count?(uintptr_t)native_outputs[row][output_count-1].bytes+8:sentinel;
  std::memcpy(r.graph_native+0x78,&last,8);std::memcpy(r.graph_native+0x80,&first,8);
  for(int32_t i=0;i<output_count;++i){auto&o=native_outputs[row][i];o.family=audio_mode?1:2;uintptr_t native=(uintptr_t)o.bytes,table=(uintptr_t)tables[o.family],prev=i?(uintptr_t)native_outputs[row][i-1].bytes+8:sentinel,next=i+1<output_count?(uintptr_t)native_outputs[row][i+1].bytes+8:sentinel;float weight=1;int32_t port=0;
   std::memcpy(o.slot+0x28,&native,8);std::memcpy(o.bytes,&table,8);std::memcpy(o.bytes+8,&prev,8);std::memcpy(o.bytes+16,&next,8);std::memcpy(o.bytes+0x40,&weight,4);std::memcpy(o.bytes+0x44,&port,4);}
 }
 if(audio_mode){auto&r=model.roots[1];audio_program.director=r.director;audio_program.asset=r.asset;audio_program.track=(void*)0x60000;audio_program.source=(void*)0x61000;audio_program.track_properties=(void*)0x62000;audio_program.graph={(uintptr_t)r.graph,2,0};audio_program.root=r.root;audio_program.mixer=r.leaf;audio_program.count=1;audio_program.clips[0]={(void*)0x63000,(void*)0x64000,(void*)0x65000,(void*)0x66000,{r.leaf.handle+0x100,2,0},0,0,0};void*clip=audio_program.clips[0].timeline;std::memcpy(audio_element+24,&clip,8);}
 if(test==3){uintptr_t self=(uintptr_t)native_outputs[1][0].bytes+8;std::memcpy(native_outputs[1][0].bytes+16,&self,8);}
 if(test==4){uintptr_t bad=1;std::memcpy(native_outputs[1][1].bytes+8,&bad,8);}
 if(test==5){uintptr_t same=(uintptr_t)native_outputs[1][0].bytes;std::memcpy(native_outputs[1][1].slot+0x28,&same,8);}
 if(test==6){uintptr_t bad=1;std::memcpy(native_outputs[1][0].bytes,&bad,8);}
 if(test==7){float value=__builtin_nanf("");std::memcpy(native_outputs[1][0].bytes+0x40,&value,4);}
 if(test==8){int32_t port=256;std::memcpy(native_outputs[1][0].bytes+0x44,&port,4);}
 if(test==9)mp4_director_profile.outputs[2].callbacks[0].prefix[0]^=1;
 if(test==13)module_closed=false;if(test==14)callbacks_closed=false;if(test==15)restoration_closed=false;if(test==16)nodes_closed=false;
 if(test==26){model.bootstrap=true;mp4_scene_host.active=true;}
 assert(mp4_source_director_plan_build(model.witness));
 if(test==21)++audio_program.clips[0].playable.handle;
 if(test==22)audio_program.clips[0].timeline=(void*)0x123;
 if(test==23)++audio_program.mixer.handle;
 if(test==24)audio_program.track=(void*)0x124;
 auto&parent=*mp4_source_director_plans.roots[0].context;
 const bool closed=mp4_source_director_plan(parent,model.roots[1].director,model.roots[1].asset);
 const bool expected=test==0||test==1||test==2||test==20||test==25||test==26;assert(closed==expected);
 if(closed&&test!=1)assert(callback_queries&&(!audio_mode||output_queries));
 assert(mp4_source_director_plan_drop());for(auto&root:mp4_output_types){weak_free(root);root=0;}assert(model.gc.empty());
}
bool plan_nodes_impl(const Mp4TimelineContext&c){
 if(close_mode==17)return mp4_source_director_plan(c,model.roots[c.director==model.roots[1].director?0:1].director,model.roots[c.director==model.roots[1].director?0:1].asset);
 if(close_mode==18){const auto size=model.gc.size();assert(!mp4_source_director_plan_drop()&&model.gc.size()==size);mp4_source_director_plan_withdraw();return false;}
 if(close_mode==19){model.phase=false;return false;}
 return nodes_closed;
}
