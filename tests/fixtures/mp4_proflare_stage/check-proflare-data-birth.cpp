#define main prior_registry_main
#include "check-proflare-registry.cpp"
#undef main
#include <cassert>
#include <initializer_list>
#include <string>
using Method=void;
namespace mp4pf=idoly_mp4_proflare_registry;
#if defined(IDOLY_DARWIN_BRIDGE)
constexpr uintptr_t source_init_site=0x6eaf304;
#else
constexpr uintptr_t source_init_site=0x877aa08;
#endif
struct Data {uint8_t header[16]{};void*batch=nullptr,*camera=nullptr;uint8_t resources[136]{};}data_object;
struct Camera{int v=1;}camera,other_camera;
H *host=nullptr;
struct {struct{uint64_t generation=7;void*camera=nullptr;}source;bool invalidated=false;const char*error="none";}mp4_stage_host;
namespace idoly_mp4_runtime{enum class Stage{active,retiring};struct{uint64_t generation=19;Stage stage=Stage::active;}job;bool permit=true,failed=false;bool native_render_job_current(){return permit&&job.stage==Stage::active;}void terminal(const char*,bool){failed=true;job.stage=Stage::retiring;}}
namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}
struct{mp4game::Binding try_update{101},data_initialize{102};}mp4_proflare_pins;
uintptr_t image_base=0;
bool mp4_source_verified=true,game=true,verified=true,gpu_current=true,original_exception=false,init_exception=false,source_baseline=false,empty_output=false,withdrawal_ready=true,root_failure=false,wrong_site=false,bad_fresh=false,nested_try=false,cancel_inside=false,after_init_throw=false,forged_abort=false,unwind_live=true,after_append_throw=false;
int original_calls=0,initialize_calls=0,buffer=0,index_buffer=0,continuations=0;size_t upload_receipts=0;
p::Scope mp4_proflare_registry_scope;
struct{void*batch=nullptr;uint64_t epoch=7;}mp4_proflare_registry_host;
struct Mp4ProFlareGpuOwner{uint64_t source=0,job=0,draw_sequence=0,draw_token=0;};
bool game_call(){return game;}
bool mp4_prefix(const mp4game::Binding&b,bool=true){return unwind_live&&b.rva>102;}
bool mp4_proflare_data_pins(){return true;}
bool mp4_hook_was_statically_verified(const mp4game::Binding&){return verified;}
uint32_t mp4_retain(void*p){return root_failure?0:H::retain(p);}
void*weak_get(uint32_t h){return H::target(h);}
void weak_free(uint32_t h){H::release(h);}
bool mp4_actor_mapped(const void*p,size_t,bool){return p!=nullptr;}
template<class T>bool mp4_actor_field(void*p,size_t offset,T&out){
 if(!p)return false;
 if(p==host&&offset==72){if constexpr(sizeof(T)==4){int32_t maximum=4;std::memcpy(&out,&maximum,sizeof(T));return true;}else return false;}
 std::memcpy(&out,static_cast<uint8_t*>(p)+offset,sizeof(T));return true;
}
bool mp4_proflare_data_schema(void*p){return p==&data_object;}
bool mp4_proflare_registry_current(void*,uint64_t e){return host&&host->valid&&e==7;}
bool mp4_proflare_registry_read(void*,p::Image*out){*out=host->image;return host->valid;}
bool mp4_proflare_gpu_current(const Mp4ProFlareGpuOwner&o){return gpu_current&&o.source==7&&o.job==19&&o.draw_sequence==23&&o.draw_token==29;}
bool mp4_proflare_gpu_origin(uint64_t source,uint64_t job,void*cam,Mp4ProFlareGpuOwner*out){*out={source,job,23,29};return cam==&camera&&mp4_proflare_gpu_current(*out);}
bool mp4_proflare_gpu_quiet(const Mp4ProFlareGpuOwner&){return !gpu_current;}
#include "proflare-data-birth-host.cpp"
bool original_try(void*,void*,void**,Method*);
void initialize(void*self,int32_t maximum,Method*){
 ++initialize_calls;assert(self==&data_object&&maximum==4);void*p=&buffer;std::memcpy(static_cast<uint8_t*>(self)+120,&p,8);
 uint64_t receipt=0;assert(mp4_proflare_birth_upload_owner(p,7,19,&receipt)&&receipt);++upload_receipts;
 if(init_exception)throw 31;
 if(cancel_inside)idoly_mp4_runtime::permit=false;
 if(nested_try){void*out=nullptr;(void)mp4_proflare_try_invoke(host,&camera,&out,nullptr,original_try);assert(false);}
}
bool original_try(void*batch,void*cam,void**out,Method*){
 ++original_calls;*out=nullptr;
 if(empty_output)return false;
 if(original_exception)throw 17;
 if(forged_abort)throw Mp4ProFlareWithdraw{nullptr,0,0,0,"forged"};
 if(!host->image.data.count){
 data_object.batch=batch;data_object.camera=cam;*out=&data_object;if(bad_fresh)data_object.resources[0]=1;
 mp4_proflare_initialize_invoke(&data_object,4,nullptr,image_base+(wrong_site?source_init_site+4:source_init_site),initialize);
 ++continuations;assert(!mp4_stage_host.invalidated);
 if(after_init_throw)throw 51;
 host->image.data.rows[host->image.data.count++]=&data_object;++host->image.data.version;if(after_append_throw)throw 53;
 }else{
 *out=&data_object;uint64_t receipt=0;assert(mp4_proflare_birth_upload_owner(&buffer,7,19,&receipt)&&receipt);++upload_receipts;
 }
 return true;
}
bool source_lease(void*data,void*cam,uint64_t*out){*out=0;if(!source_baseline||data!=&data_object||cam!=&camera)return false;*out=71;return true;}
#ifndef MP4_PROFLARE_BIRTH_NO_MAIN
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];H h;host=&h;h.data[0]=nullptr;h.image.data.count=0;
 mp4_stage_host.source.camera=&camera;mp4_proflare_registry_host.batch=&h;
 auto api=h.api();api.data_origin=mp4_proflare_data_registry_origin;api.data_complete=mp4_proflare_data_registry_complete;
 mp4_proflare_try_trampoline=original_try;mp4_proflare_initialize_trampoline=initialize;
 mp4_proflare_existing_data_lease=source_lease;mp4_proflare_try_withdrawal_ready=[](void*,void*){return withdrawal_ready;};
 if(mode=="existing_source"){source_baseline=true;data_object.batch=&h;data_object.camera=&camera;void*p=&buffer;std::memcpy(reinterpret_cast<uint8_t*>(&data_object)+120,&p,8);h.data[0]=&data_object;h.image.data.count=1;}
 assert(mp4_proflare_registry_scope.capture(api,&h,7,h.flares,2)==p::Result::ok);void*out=nullptr;
 if(mode=="withdrawal_source"){
 assert(mp4_proflare_try_withdrawal_source(&h,&camera));unwind_live=false;assert(!mp4_proflare_try_withdrawal_source(&h,&camera));
 }
 else if(mode=="cancel_before"){
 idoly_mp4_runtime::permit=false;assert(!mp4_proflare_try_invoke(&h,&camera,&out,nullptr,original_try)&&!original_calls);
 }
 else if(mode=="wrong_site"||mode=="bad_fresh"||mode=="nested_try"||mode=="cancel_inside"){
 wrong_site=mode=="wrong_site";bad_fresh=mode=="bad_fresh";nested_try=mode=="nested_try";cancel_inside=mode=="cancel_inside";
 assert(!mp4_proflare_try_invoke(&h,&camera,&out,nullptr,original_try));
 assert(idoly_mp4_runtime::failed&&!mp4_stage_host.invalidated&&mp4_proflare_data_birth_count==1&&mp4_proflare_data_births[0].withdrawn&&continuations==0&&h.image.data.count==0&&mp4_proflare_data_original_try==nullptr);
 assert(!mp4_proflare_registry_scope.current());
 if(mode=="bad_fresh")assert(mp4_proflare_data_births[0].object==&data_object&&!mp4_proflare_data_births[0].birth_proven);
 if(mode=="nested_try"||mode=="cancel_inside")assert(initialize_calls==1&&mp4_proflare_data_births[0].birth_proven&&upload_receipts==1);
 }
 else if(mode=="forged_abort"){
 forged_abort=true;try{(void)mp4_proflare_try_invoke(&h,&camera,&out,nullptr,original_try);assert(false);}catch(const Mp4ProFlareWithdraw&value){assert(value.owner==nullptr&&value.recipe==0);}
 assert(idoly_mp4_runtime::failed&&!mp4_stage_host.invalidated&&mp4_proflare_data_original_try==nullptr);
 }
 else if(mode=="no_boundary"){mp4_proflare_try_withdrawal_ready=nullptr;assert(!mp4_proflare_try_invoke(&h,&camera,&out,nullptr,original_try)&&!original_calls);}
 else if(mode=="boundary_reject"){withdrawal_ready=false;assert(!mp4_proflare_try_invoke(&h,&camera,&out,nullptr,original_try)&&!original_calls);}
 else if(mode=="foreign"){game=false;assert(!mp4_proflare_try_invoke(&h,&camera,&out,nullptr,original_try)&&!original_calls);}
 else if(mode=="unverified"){verified=false;assert(!mp4_proflare_try_invoke(&h,&camera,&out,nullptr,original_try)&&!original_calls);}
 else if(mode=="wrong_camera"){assert(!mp4_proflare_try_invoke(&h,&other_camera,&out,nullptr,original_try)&&!original_calls);}
 else if(mode=="root_failure"){root_failure=true;assert(!mp4_proflare_try_invoke(&h,&camera,&out,nullptr,original_try)&&!original_calls);root_failure=false,wrong_site=false,bad_fresh=false,nested_try=false,cancel_inside=false,after_init_throw=false,forged_abort=false,unwind_live=true,after_append_throw=false;assert(mp4_proflare_data_birth_count==1);}
 else if(mode=="gpu_unowned"){gpu_current=false;assert(!mp4_proflare_try_invoke(&h,&camera,&out,nullptr,original_try)&&!original_calls);}
 else if(mode=="original_exception"||mode=="init_exception"||mode=="after_init_throw"){
 original_exception=mode=="original_exception";init_exception=mode=="init_exception";after_init_throw=mode=="after_init_throw";
 try{(void)mp4_proflare_try_invoke(&h,&camera,&out,nullptr,original_try);assert(false);}catch(int value){assert(value==(original_exception?17:init_exception?31:51));}
 assert(mp4_proflare_data_birth_count==1&&mp4_proflare_data_births[0].threw&&!mp4_proflare_registry_scope.current());
 assert(mp4_proflare_data_original_try==nullptr&&idoly_mp4_runtime::failed&&!mp4_stage_host.invalidated);
 if(init_exception)assert(mp4_proflare_data_births[0].object==&data_object&&mp4_proflare_data_births[0].root_count==3&&upload_receipts==1);
 }
 else {
 empty_output=mode=="empty";bool result=mp4_proflare_try_invoke(&h,&camera,&out,nullptr,original_try);assert(result!=empty_output&&!mp4_stage_host.invalidated&&mp4_proflare_registry_scope.current());
 if(mode=="empty"||mode=="existing_source")assert(mp4_proflare_data_birth_count==0);
 else {
 assert(mp4_proflare_data_birth_count==1&&mp4_proflare_data_births[0].initialized&&mp4_proflare_data_births[0].registered&&initialize_calls==1);
 uint64_t receipt=0;assert(mp4_proflare_registry_scope.data_birth(&data_object,&camera,&receipt)&&receipt==mp4_proflare_data_births[0].recipe);
 if(mode=="repeat")for(size_t i=0;i<128;++i){assert(mp4_proflare_try_invoke(&h,&camera,&out,nullptr,original_try));assert(mp4_proflare_data_birth_count==1&&!mp4_stage_host.invalidated&&initialize_calls==1);}
 if(mode=="unowned_upload"){assert(!mp4_proflare_birth_upload_owner(&buffer,7,19,&receipt));}
 }
 }
 // Fixture teardown is not a production failure-cleanup or GPU proof. Actual
 // born Data retirement must be joined before this source packet may ship.
 mp4_proflare_registry_scope.release();
 for(size_t i=0;i<mp4_proflare_data_birth_count;++i)mp4_proflare_birth_drop(mp4_proflare_data_births[i]);
 assert(h.roots.empty());return 0;
}

#endif
