namespace mp4shader=idoly_mp4_shader_lineage;
const mp4shader::KnownBundle mp4_shader_known[2]={{3,2,{{0xba,0x78,0x16,0xbf,0x8f,0x01,0xcf,0xea,0x41,0x41,0x40,0xde,0x5d,0xae,0x22,0x23,0xb0,0x03,0x61,0xa3,0x96,0x17,0x7a,0x9c,0xb4,0x10,0xff,0x61,0xf2,0x00,0x15,0xad}}},{4,2,{}}};
int main(int argc,char**argv){assert(argc==2);const std::string mode=argv[1];
 shader_a.klass=shader_b.klass=&shader_class;bundle.klass=&bundle_class;request.klass=&request_class;input.klass=&bytes_class;path.klass=empty.klass=&string_class;type.klass=&type_class;array.klass=&array_class;array.items={&shader_a,&shader_b};input.bytes={'a','b','c'};
 put_native(shader_a,11);put_native(shader_b,12);put_native(bundle,13);put_native(request,14);
 mp4_shader_lineage_pins.instance_id.rva=reinterpret_cast<uintptr_t>(get_id)-image_base;mp4_shader_lineage_pins.all_shaders.rva=reinterpret_cast<uintptr_t>(all_shaders)-image_base;
 mp4_shader_memory_sync_original=memory_original;mp4_shader_memory_async_original=async_original;mp4_shader_file_async_original=file_original;mp4_shader_bundle_result_original=request_original;
 mp4_shader_lineage_pins.main_thread.rva=reinterpret_cast<uintptr_t>(actual_main_thread)-image_base;
 Method*m=reinterpret_cast<Method*>(456);
 if(mode=="bootstrap_main"){owner=false;oracle_main=true;assert(mp4_shader_memory_sync_hook(&input,123,m)==&bundle&&owner&&oracle_calls==1&&original_calls==1&&all_calls==1&&mp4_shader_downloaded_program(&shader_a));mp4_shader_lineage_registry.clear();assert(roots.empty());return 0;}
 if(mode=="bootstrap_bad_prefix"){owner=false;source_prefix=false;assert(mp4_shader_memory_sync_hook(&input,123,m)==&bundle&&!owner&&!oracle_calls&&original_calls==1&&!all_calls&&roots.empty());return 0;}
 if(mode=="offthread"){owner=false;private_active=true;assert(mp4_shader_memory_sync_hook(&input,123,m)==&bundle&&original_calls==1&&!all_calls&&roots.empty()&&mp4_shader_lineage_foreign_dirty.load());return 0;}
 if(mode=="source_prefix"){source_prefix=false;assert(mp4_shader_memory_sync_hook(&input,123,m)==&bundle&&original_calls==1&&!all_calls&&roots.empty());return 0;}
 if(mode=="unknown_bytes")input.bytes[0]='z';
 if(mode=="changed_memory"||mode=="changed_file")mutate=true;
 if(mode=="observer_throw")all_throw=true;
 if(mode=="original_throw")original_throw=true;
 const bool file_mode=mode=="file"||mode=="changed_file"||mode=="file_changed_before_result";
 if(file_mode){char name[]="/tmp/mp4-shader-lineage-XXXXXX";int fd=mkstemp(name);assert(fd>=0&&write(fd,"abc",3)==3);close(fd);path.text=name;
  assert(mp4_shader_file_async_hook(&path,123,0,m)==&request&&original_calls==1&&!all_calls);
  if(mode=="file_changed_before_result"){fd=open(name,O_WRONLY);assert(fd>=0&&write(fd,"xyz",3)==3);close(fd);}
  assert(mp4_shader_bundle_result_hook(&request,m)==&bundle&&original_calls==2);
  assert(mp4_shader_downloaded_program(&shader_a)==(mode=="file"));unlink(name);
 }else if(mode=="async"){
  assert(mp4_shader_memory_async_hook(&input,123,m)==&request&&original_calls==1&&!all_calls);
  complete=false;assert(!mp4_shader_bundle_result_hook(&request,m)&&original_calls==2&&!all_calls);
  complete=true;assert(mp4_shader_bundle_result_hook(&request,m)==&bundle&&original_calls==3&&all_calls==1&&mp4_shader_downloaded_program(&shader_a));
 }else{
  bool threw=false;try{assert(mp4_shader_memory_sync_hook(&input,123,m)==&bundle);}catch(const std::runtime_error&){threw=true;}
  assert(threw==(mode=="original_throw")&&original_calls==1);
  assert(mp4_shader_downloaded_program(&shader_a)==(mode=="sync"));
 }
 mp4_shader_lineage_registry.clear();assert(roots.empty());
}
