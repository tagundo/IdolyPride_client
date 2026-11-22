#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <pthread.h>
#include <set>
#include <string>
#include <vector>
namespace pin { struct Entry {const char*name;uintptr_t rva;};
// PIN_ENTRIES
}
// HOOK_DECLARATIONS
std::string mode,state_code,last_error;std::vector<std::string>notes,trace16;
std::map<uintptr_t,unsigned>ordinary_calls,backend_calls;std::set<uintptr_t>live_hooks;
std::map<void*,uintptr_t>stub_targets;
alignas(16) unsigned char engine[1024]{};
uintptr_t image_base=0,mp4_native_base=reinterpret_cast<uintptr_t>(engine);
void*held_library=nullptr,*mp4_native_time_stub=nullptr,*mp4_fixed_loop_condition_stub=nullptr;
void*mp4_native_time_original=nullptr,*mp4_fixed_loop_condition_original=nullptr;
void mp4_native_time_hook(){} void mp4_fixed_loop_condition_hook(){}
void*mp4_install_actor_burst(void*){return nullptr;}
struct {struct{uintptr_t rva=256;}update;}mp4_native_profile;
struct {struct{uintptr_t rva=512;}fixed_condition;}mp4_world_profile;
unsigned char mp4_fixed_patched_prefix[16]{};
bool mp4_source_verified=false,mp4_control_factory_hook_ready=false;
char mp4_binding_error[96]{};
std::atomic<bool>ready{false},mp4_managed_hook_receipts_ready{false},mp4_shader_bootstrap_receipts_open{false},mp4_actor_managed_installed{false},mp4_export_observer_install_complete{false};
std::atomic<unsigned>mp4_managed_hook_count{0};
std::atomic<const char*>mp4_native_clock_error{"none"},mp4_actor_route_error{"none"};
bool clock_installed=false;std::map<unsigned,bool>module_flags;
namespace idoly_mp4_runtime{
 void diagnostic_event(const char*stage,const char*code,uint64_t,uint64_t,bool failed){std::string event=std::string(stage)+":"+code;notes.push_back(event);trace16.push_back(event);if(trace16.size()>16)trace16.erase(trace16.begin());if(failed)last_error=code;}
 void diagnostic_module(unsigned id,bool value,const char*error){const bool changed=!module_flags.count(id)||module_flags[id]!=value;module_flags[id]=value;if(changed&&!value)diagnostic_event("bindings",error,0,0,true);}
 bool native_clock_available(){return clock_installed;}
}
constexpr size_t mp4_managed_hook_capacity=160;
struct Status{bool fps=false,quality=false,resolution=false,aa=false,shadow=false,expanded=false;}state;
pthread_mutex_t status_mutex=PTHREAD_MUTEX_INITIALIZER;
struct Image{uintptr_t base=0;bool unity=false;char name[64]{};};
int find_image(void*,size_t,void*){return 0;}
int model_iterate(int(*)(void*,size_t,void*),void*out){auto&i=*static_cast<Image*>(out);if(mode!="missing_image"){i.base=0x10000000;i.unity=true;std::strcpy(i.name,"/verified/libil2cpp.so");}return 0;}
void*model_open(const char*,int){return reinterpret_cast<void*>(0x1234);}
int model_close(void*){return 0;}
constexpr int RTLD_NOW=1,RTLD_NOLOAD=2,SHADOWHOOK_MODE_UNIQUE=1;
void pause_ms(unsigned){}
bool matches(const Image&){return mode!="primary_image";}
bool mp4_prepare_android_native_clock(){return mode!="native_source";}
bool mp4_prepare_fixed_root(){return mode!="fixed_source";}
bool mp4_prepare_animation_root(){return mode!="animation_source";}
void load_calls(){mp4_source_verified=mode!="subset_source";std::strcpy(mp4_binding_error,mp4_source_verified?"none":"original_mv_type_shape_test");}
void set_state(const char*s){state_code=s;}
// ACTUAL_FIRST_FAILURE
int shadowhook_get_errno(){return 73;}
// ACTUAL_BOOTSTRAP_FAILURE
int shadowhook_init(int,bool){return mode=="shadow_init"?1:0;}
void shadowhook_set_recordable(bool){}
bool mp4_android_managed_source_prepare(const Image&){return mode!="managed_prepare";}
bool mp4_child_native_install_android(){return mp4_source_verified&&mode.rfind("director_",0)!=0;}
bool mp4_capture_native_install_android(){return mp4_source_verified&&mode!="capture_native";}
bool mp4_audio_native_install_android(){return mp4_source_verified&&mode!="audio_native";}
namespace mp4_bootstrap {struct Pin{uintptr_t rva;};constexpr size_t managed_source_count=24;
const Pin*android_managed_source_pin(size_t i){static const Pin p[]={// SOURCE_ROWS
};return i<24?&p[i]:nullptr;}}
bool source_failure(size_t i,const char*stage){return mode==std::string("source_")+stage+"_"+std::to_string(i);}
void*publish(uintptr_t address,void**original){assert(original&&!*original);*original=reinterpret_cast<void*>(address+1);void*stub=reinterpret_cast<void*>(address+2);stub_targets[stub]=address;live_hooks.insert(address);return stub;}
struct Backend{
 void*stubs[24]{};
 bool install(size_t i,uintptr_t replacement,void**original){assert(replacement);++backend_calls[mp4_bootstrap::android_managed_source_pin(i)->rva];if(source_failure(i,"before"))return false;stubs[i]=publish(image_base+mp4_bootstrap::android_managed_source_pin(i)->rva,original);return !source_failure(i,"after");}
 void*installed_stub(size_t i){return stubs[i];}
}mp4_managed_source_backend;
void*shadowhook_hook_func_addr(void*target,void*replacement,void**original){assert(target&&replacement);const auto address=reinterpret_cast<uintptr_t>(target);++ordinary_calls[address];if((mode=="primary_hook"&&address==image_base+pin::q_set.rva)||(mode=="selection_hook"&&address==image_base+pin::mp4_photography_initialize.rva)||(mode=="optional_hook"&&address==image_base+pin::mp4_volume_update.rva)||(mode=="clock_hook"&&address==mp4_native_base+256)||(mode=="fixed_hook"&&address==mp4_native_base+512))return nullptr;return publish(address,original);}
int shadowhook_unhook(void*stub){if(stub)live_hooks.erase(stub_targets.at(stub));return 0;}
bool mp4_record_managed_hook(const pin::Entry*entry,void*stub,void**original,void*replacement){assert(entry&&stub&&original&&*original&&replacement);if((mode=="primary_receipt"&&entry==&pin::q_set)||(mode=="optional_receipt"&&entry==&pin::mp4_volume_update))return false;for(size_t i=0;i<24;++i)if(source_failure(i,"after")&&entry->rva==mp4_bootstrap::android_managed_source_pin(i)->rva)return false;++mp4_managed_hook_count;return true;}
bool mp4_scene_shader_frontends_current(){return mode!="scene_frontends";}
bool mp4_scene_shader_origin_install(){return mode!="scene_origin";}
bool mp4_capture_queue_frontends_bind(const pin::Entry&,const pin::Entry&){return mode!="queue_bind";}
namespace rotation{bool ready_for_publish(){return mode!="base_ready";}}
struct Ready{bool ready(){return true;}}preview_ui,korean_fallback,korean_list_factory,wardrobe_lifecycle,wardrobe_exit_tracker,sound_tracker;
bool mp4_install_native_clock_api(){clock_installed=mode!="clock_api";return clock_installed;}
bool mp4_install_fixed_root(){return mode!="fixed_api";}
int model_create(pthread_t*,const pthread_attr_t*,void*(*)(void*),void*){return 0;}
int model_detach(pthread_t){return 0;}
struct Hook{const pin::Entry*entry;void*replacement;void**original;void*stub=nullptr;const char*role=nullptr;};
// ACTUAL_OPTIONAL_POLICY
#define dl_iterate_phdr model_iterate
#define dlopen model_open
#define dlclose model_close
#define pthread_create model_create
#define pthread_detach model_detach
// ACTUAL_INSTALL
int main(int argc,char**argv){assert(argc==2);mode=argv[1];
 if(mode.rfind("first_failure_",0)==0){
  if(mode=="first_failure_none"){mp4_bootstrap_note("ordinary","not_failed");const auto count=notes.size();mp4_bootstrap_publish_first_failure();assert(notes.size()==count&&!mp4_bootstrap_first_failed.load());return 0;}
  const std::string initial=mode=="first_failure_bounded"?std::string(180,'x'):"native7_enqueue_errno_73";
  mp4_bootstrap_note("director_install",initial.c_str(),true);
  for(unsigned i=0;i<40;++i)mp4_bootstrap_note("later_binding","unbound",true);
  assert(trace16.size()==16&&last_error=="unbound");
  mp4_bootstrap_publish_first_failure();assert(last_error==initial.substr(0,95));assert(trace16.back()=="director_install:"+initial.substr(0,95));
  mp4_bootstrap_note("last_binding","second_unbound",true);mp4_bootstrap_publish_first_failure();assert(last_error==initial.substr(0,95));return 0;
 }
 install(nullptr);
 const bool refused=mode=="primary_image"||mode=="primary_hook"||mode=="primary_receipt"||mode=="selection_hook"||mode=="base_ready"||mode=="shadow_init"||mode=="missing_image";
 assert(ready.load()==!refused);
 if(refused){assert(!mp4_export_observer_install_complete.load());assert(!state.fps&&!state.quality&&!state.resolution&&!state.aa&&!state.shadow&&!state.expanded);
  if(mode=="primary_hook"||mode=="shadow_init"){bool exact=false;for(auto&s:notes)if(s==(mode=="primary_hook"?"primary_hook_failed:q_set_errno_73":"shadowhook_initialize:unique_mode_errno_73"))exact=true;assert(exact);}
  return 0;}
 assert(mp4_source_verified==(mode!="subset_source"));assert(std::strcmp(mp4_binding_error,mode=="subset_source"?"original_mv_type_shape_test":"none")==0);
 assert(state.fps&&state.quality&&state.resolution&&state.aa&&state.shadow&&state.expanded);
 assert(mp4_managed_hook_receipts_ready.load());assert(!mp4_shader_bootstrap_receipts_open.load());
 assert(mp4_export_observer_install_complete.load()==(mode=="normal"));
 assert(module_flags.at(13)==mp4_export_observer_install_complete.load());
 if(mode=="clock_api")assert(mp4_native_time_original&&live_hooks.count(mp4_native_base+256));
 if(mode=="fixed_api")assert(mp4_fixed_loop_condition_original&&live_hooks.count(mp4_native_base+512));
 for(auto*entry:{&pin::q_set,&pin::q_update,&pin::rt_update,&pin::rotation_wait,&pin::mp4_photography_initialize,&pin::mp4_photography_player_initialize,&pin::mp4_presenter_update,&pin::mp4_presenter_end}){
  assert(live_hooks.count(image_base+entry->rva));assert(ordinary_calls[image_base+entry->rva]==1);
 }
 assert(mp4_photography_initialize_original&&mp4_photography_player_initialize_original&&mp4_presenter_update_original&&mp4_presenter_end_original);
 for(size_t i=0;i<24;++i){const auto rva=mp4_bootstrap::android_managed_source_pin(i)->rva;
  if(source_failure(i,"after")){assert(ordinary_calls[image_base+rva]==0);assert(backend_calls[rva]==1);assert(live_hooks.count(image_base+rva));}
  if(source_failure(i,"before")){assert(ordinary_calls[image_base+rva]==1);assert(backend_calls[rva]==1);assert(live_hooks.count(image_base+rva));}
 }
 assert(!notes.empty());return 0;
}
