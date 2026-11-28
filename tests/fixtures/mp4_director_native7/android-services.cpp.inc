qa::Model model;unsigned failure_mode=0;
bool shadowhook_get_recordable(){return model.recordable;}
void shadowhook_set_recordable(bool b){model.recordable=b;}
char*shadowhook_get_records(uint32_t n){assert(n==mp4_bootstrap::shadow_record_items);return strdup(model.records.c_str());}
void*shadowhook_hook_func_addr_2(void*target,void*replacement,void**original,uint32_t flags,...){
 assert(flags==10&&model.recordable);const mp4_bootstrap::BootstrapPin*pin=nullptr;
 for(size_t i=0;i<7;++i){const auto&p=mp4_bootstrap::android_bootstrap_pins[i];if(model.engine.base+p.rva==reinterpret_cast<uintptr_t>(target))pin=&p;}
 assert(pin);model.pin=*pin;model.requested=reinterpret_cast<uintptr_t>(replacement);++model.calls;
 auto install=model.make(*pin,20,false);model.publish(install);*original=reinterpret_cast<void*>(install.gateway);return reinterpret_cast<void*>(install.stub);
}
void*mp4_capture_native_android_source_context(){return &model;}
bool mp4_android_hook_installer(void*p){return qa::Model::thread(p);}
bool mp4_android_hook_source(void*p,mp4_bootstrap::BootstrapImage image,mp4_bootstrap::Source*out){return qa::Model::source(p,image,out);}
bool mp4_android_hook_code(void*p,uintptr_t at,void*out,size_t n){return qa::Model::read(p,at,out,n);}
