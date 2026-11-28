#define MP4_PROFLARE_BIRTH_NO_MAIN 1
#include "check-proflare-data-birth.cpp"
#if defined(IDOLY_DARWIN_BRIDGE)
constexpr uintptr_t dispose_rva=0x6eb69f4,remove_rva=0x493205c;
#else
constexpr uintptr_t dispose_rva=0x8781a5c,remove_rva=0x6adbbfc;
#endif
#undef MP4_PROFLARE_BIRTH_NO_MAIN
namespace mp4stage{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}
struct{mp4stage::Binding equipment_job_complete{909,{}};}mp4_stage_profile;
struct Meta{uintptr_t entry=0;}dispose_meta,remove_meta;
bool quiet=true,passes_released=true,held=true,operation_live=true,job_ready=true,dispose_throws=false,remove_foreign=false,method_ok=true;
int completes=0,disposes=0,removes=0;
bool mp4_stage_clock_held(void*){return held;}
void* object_class(void*object){return object;}
const void*font_method(void*object,const char*name,int count){
 if(!method_ok)return nullptr;
 if(object==&data_object&&!std::strcmp(name,"Dispose")&&count==0){dispose_meta.entry=image_base+dispose_rva;return &dispose_meta;}
 if(object==host->image.data.object&&!std::strcmp(name,"RemoveAt")&&count==1){remove_meta.entry=image_base+remove_rva;return &remove_meta;}
 return nullptr;
}
bool mp4_proflare_pass_retained_without(void*batch,void*data){return passes_released&&batch==host&&data==&data_object;}
void complete(void*job,Method*){++completes;if(job_ready){uint64_t zero=0;std::memcpy(job,&zero,8);}}
void dispose(void*object,Method*method){assert(object==&data_object&&method==&dispose_meta&&quiet&&!gpu_current&&passes_released);++disposes;if(dispose_throws)throw 67;std::memset(data_object.resources,0,sizeof(data_object.resources));}
void remove_at(void*list,int32_t at,Method*method){assert(list==host->image.data.object&&method==&remove_meta&&at>=0&&uint32_t(at)+1==host->image.data.count);++removes;host->image.data.rows[--host->image.data.count]=nullptr;++host->image.data.version;if(remove_foreign)++host->image.list.version;}
template<class Fn>Fn mp4_equipment_call(const mp4stage::Binding&b){
 if(b.rva==dispose_rva)return reinterpret_cast<Fn>(reinterpret_cast<uintptr_t>(&dispose));
 if(b.rva==remove_rva)return reinterpret_cast<Fn>(reinterpret_cast<uintptr_t>(&remove_at));
 if(b.rva==909)return reinterpret_cast<Fn>(reinterpret_cast<uintptr_t>(&complete));
 assert(false);return nullptr;
}
#include "proflare-data-retirement-host.cpp"
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];H h;host=&h;h.data[0]=nullptr;h.image.data.count=0;
 mp4_stage_host.source.camera=&camera;mp4_proflare_registry_host.batch=&h;
 auto api=h.api();api.data_origin=mp4_proflare_data_registry_origin;api.data_complete=mp4_proflare_data_registry_complete;
 mp4_proflare_try_trampoline=original_try;mp4_proflare_initialize_trampoline=initialize;
 mp4_proflare_existing_data_lease=source_lease;mp4_proflare_try_withdrawal_ready=[](void*,void*){return true;};
 mp4_proflare_data_restore_operation=[](void*)->uint64_t{return operation_live?811:0;};
 assert(mp4_proflare_registry_scope.capture(api,&h,7,h.flares,2)==p::Result::ok);void*out=nullptr;
 if(mode=="original_exception")original_exception=true;
 if(mode=="partial_init")init_exception=true;
 if(mode=="after_init")after_init_throw=true;
 if(mode=="after_append")after_append_throw=true;
 if(mode=="cancel")cancel_inside=true;
 if(mode=="bad_fresh")bad_fresh=true;
 bool failed=mode=="original_exception"||mode=="partial_init"||mode=="after_init"||mode=="after_append";
 if(failed){try{(void)mp4_proflare_try_invoke(&h,&camera,&out,nullptr,original_try);assert(false);}catch(int value){assert(value==(original_exception?17:init_exception?31:after_init_throw?51:53));}}
 else assert(mp4_proflare_try_invoke(&h,&camera,&out,nullptr,original_try)==(mode!="cancel"&&mode!="bad_fresh"));
 assert(mp4_proflare_data_birth_count==1&&!mp4_proflare_birth_release());
 gpu_current=false;
 using R=Mp4ProFlareRetireResult;
 if(mode=="gpu_wait"){gpu_current=true;assert(mp4_proflare_birth_retire(0)==R::waiting&&!completes&&!disposes&&!removes);gpu_current=false;}
 if(mode=="passes_wait"){passes_released=false;assert(mp4_proflare_birth_retire(0)==R::waiting&&!completes&&!disposes&&!removes);passes_released=true;}
 if(mode=="no_operation"){operation_live=false;assert(mp4_proflare_birth_retire(0)==R::invalid&&!disposes&&!removes);operation_live=true;}
 if(mode=="no_method"){method_ok=false;assert(mp4_proflare_birth_retire(0)==R::invalid&&!disposes&&!removes);method_ok=true;}
 if(mode=="not_held"){held=false;assert(mp4_proflare_birth_retire(0)==R::invalid&&!disposes&&!removes);held=true;}
 if(mode=="job_wait"){uint64_t group=79;std::memcpy(reinterpret_cast<uint8_t*>(&data_object)+104,&group,8);job_ready=false;assert(mp4_proflare_birth_retire(0)==R::waiting&&!disposes&&!removes);job_ready=true;}
 if(mode=="bad_fresh"){assert(mp4_proflare_birth_retire(0)==R::invalid&&!disposes&&!removes);}
 else if(mode=="dispose_throw"){
 dispose_throws=true;try{(void)mp4_proflare_birth_retire(0);assert(false);}catch(int v){assert(v==67);}
 assert(disposes==1&&removes==0&&!mp4_proflare_birth_release());
 }
 else if(mode=="foreign_list"){
 remove_foreign=true;assert(mp4_proflare_birth_retire(0)==R::failed&&disposes==1&&removes==1&&!mp4_proflare_birth_release());
 }
 else {
 assert(mp4_proflare_birth_retire(0)==R::ok);const int done=disposes;
 assert(mp4_proflare_birth_retire(0)==R::ok&&disposes==done);
 assert(mp4_proflare_data_births[0].retired&&h.image.data.count==0&&mp4_proflare_registry_scope.current());
 assert(disposes==(mode=="original_exception"?0:1));
 assert(removes==((mode=="partial_init"||mode=="after_init"||mode=="cancel"||mode=="original_exception")?0:1));
 assert(mp4_proflare_registry_scope.restore()==p::Result::ok&&h.image.data.version==2);
 assert(mp4_proflare_birth_release()&&mp4_proflare_data_birth_count==0);
 }
 // A deliberately rejected or throwing cleanup retains its custody in real
 // code; this harness only drops model GC roots after checking that refusal.
 mp4_proflare_registry_scope.release();
 for(size_t i=0;i<mp4_proflare_data_birth_count;++i)mp4_proflare_birth_drop(mp4_proflare_data_births[i]);
 assert(h.roots.empty());return 0;
}
