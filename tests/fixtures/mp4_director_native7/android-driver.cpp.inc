void setup(){
 auto*area=mmap(nullptr,0x1000000,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_NORESERVE,-1,0);assert(area!=MAP_FAILED);image_base=mp4_native_base=reinterpret_cast<uintptr_t>(area);model.engine.base=image_base;
 const auto address=image_base+mp4_child_native_reset_pin.rva;const auto page=address&~uintptr_t(4095);assert(!mprotect(reinterpret_cast<void*>(page),4096,PROT_READ|PROT_WRITE));regions.push_back({page,4096});std::memcpy(reinterpret_cast<void*>(address),mp4_child_native_reset_pin.prefix,16);
 for(size_t i=0;i<7;++i)model.original(mp4_bootstrap::android_bootstrap_pins[i]);
}
mp4_director_maintenance::Originals originals(){return {mp4_director_enqueue_original,{mp4_director_append_a_original,mp4_director_append_b_original},mp4_director_collect_original,reinterpret_cast<mp4_director_maintenance::ResetFn>(mp4_native_base+mp4_child_native_reset_pin.rva),{mp4_director_deferred_a_original,mp4_director_deferred_b_original}};}
int main(int argc,char**argv){assert(argc==2);failure_mode=static_cast<unsigned>(atoi(argv[1]));setup();
 if(failure_mode>=1&&failure_mode<=7){auto&i=model.memory[failure_mode-1];i.bytes[0]^=1;assert(!mp4_child_native_install_android()&&!mp4_child_native_hooks_current());return 0;}
 if(failure_mode==8)mp4_source_verified=false;
 if(failure_mode==9)mp4_native_clock_source_ready=false;
 if(failure_mode==10)model.installer=false;
 if(failure_mode>=8&&failure_mode<=10){assert(!mp4_child_native_install_android()&&!model.calls);return 0;}
 assert(mp4_child_native_install_android()&&model.calls==7&&!model.recordable&&mp4_child_native_hooks_current()&&mp4_child_pending_bindings_current(originals()));assert(!mp4_child_native_install_android()&&model.calls==7);
 if(failure_mode>=11&&failure_mode<=17){const auto index=failure_mode-11;const auto&p=mp4_child_native_source_pins[index];for(auto&r:model.memory)if(r.address==image_base+p.rva)r.bytes[0]^=1;assert(!mp4_child_native_certificate(index)&&!mp4_child_native_hooks_current());}
 if(failure_mode>=18&&failure_mode<=24){const auto index=failure_mode-18;auto address=mp4_child_native_original(index);for(auto&r:model.memory)if(r.address==address)r.bytes[0]^=1;assert(!mp4_child_native_certificate(index)&&!mp4_child_native_hooks_current());}
 if(failure_mode>=25&&failure_mode<=31){const auto index=failure_mode-25;auto address=mp4_child_native_original(index);for(auto&r:model.memory)if(r.address==address)r.bytes.back()^=1;assert(!mp4_child_native_certificate(index)&&!mp4_child_native_hooks_current());}
 if(failure_mode==32){model.engine.load++;assert(!mp4_child_native_hooks_current());}
 if(failure_mode==33){model.engine.cohort++;assert(!mp4_child_native_hooks_current());}
 if(failure_mode==34){auto o=originals();o.collect=nullptr;assert(!mp4_child_pending_bindings_current(o));}
 if(failure_mode==35){*reinterpret_cast<uint8_t*>(mp4_native_base+mp4_child_native_reset_pin.rva)^=1;assert(!mp4_child_pending_bindings_current(originals()));}
 if(failure_mode==36){factory_current=false;assert(!mp4_child_native_birth_bindings(mp4_child_graph_create_original,factory));}
 if(failure_mode==37){mp4_native_clock_source_ready=false;assert(!mp4_child_native_hooks_current());}
 if(failure_mode==38){mp4_source_verified=false;assert(!mp4_child_native_hooks_current());}
 assert(!munmap(reinterpret_cast<void*>(image_base),0x1000000));
}
