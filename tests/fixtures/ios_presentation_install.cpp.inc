#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <map>
#include <pthread.h>
#include <string>
#include <vector>
namespace pin{struct Entry{const char*name;uintptr_t gateway,slot;};
// PIN_ENTRIES
}
void model_forward(void**);
// HOOK_DECLARATIONS
std::string mode,state_code;std::vector<std::string>notes;
alignas(uintptr_t) unsigned char image[8192]{};
uintptr_t image_base=0;
std::atomic<bool>ready{false},mp4_export_observer_install_complete{false},mp4_actor_managed_installed{false},mp4_actor_burst_installed{false},shared_hooks_ready{false};
std::atomic<const char*>mp4_native_clock_error{"modeled_native_source_unavailable"};
bool mp4_source_verified=false,mp4_control_factory_hook_ready=false;
const char*mp4_binding_error="modeled_game_api_source_unavailable";
struct{bool fps=false,quality=false,resolution=false,aa=false,shadow=false,expanded=false;}state;
pthread_mutex_t status_mutex=PTHREAD_MUTEX_INITIALIZER;
std::map<unsigned,bool>module_flags;
namespace idoly_mp4_runtime{void diagnostic_module(unsigned id,bool value,const char*){module_flags[id]=value;}}
pin::Entry*entries[]={
// ENTRY_POINTERS
};
void**originals[]={
// ORIGINAL_POINTERS
};
constexpr size_t hook_count=sizeof(entries)/sizeof(*entries);
unsigned publications=0,original_calls=0,verify_calls=0,load_calls_count=0,finished=0;
bool all_originals(){for(auto*original:originals)if(!*original)return false;return true;}
void ordinary_original(){++original_calls;}
void model_forward(void**original){assert(original&&*original);reinterpret_cast<void(*)()>(*original)();}
void model_publish(uintptr_t*slot,uintptr_t replacement,int order){
 assert(order==__ATOMIC_RELEASE&&all_originals()&&!ready.load());
 bool known=false;for(auto*entry:entries)if(slot==reinterpret_cast<uintptr_t*>(image_base+entry->slot))known=true;
 assert(known&&!*slot&&replacement);*slot=replacement;++publications;
 // A real callback may race publication before primary-ready becomes true.
 // The ordinary forwarding branch is modeled; its saved original is genuine
 // fixture code, and all slots must already be assigned before this call.
 const auto before=original_calls;reinterpret_cast<void(*)()>(replacement)();assert(original_calls==before+1);
}
const void*mapped_unity_header(){return mode=="missing_image"?nullptr:image;}
void pause_ms(unsigned){}
bool verify_static_image(const void*header){++verify_calls;assert(header==image);return mode!="primary_image";}
void set_state(const char*value){state_code=value;}
void mp4_bootstrap_note(const char*stage,const char*code,bool failed=false){notes.push_back(std::string(stage)+":"+code+(failed?":failed":""));}
void mp4_bootstrap_publish_first_failure(){++finished;}
bool mp4_prepare_native_clock(uintptr_t value){assert(value==reinterpret_cast<uintptr_t>(image));return mode!="native_source";}
bool mp4_prepare_fixed_root(){return mode!="fixed_source";}
bool mp4_prepare_animation_root(){return mode!="animation_source";}
void load_calls(){++load_calls_count;mp4_source_verified=mode!="api_source";}
void shared_cache_load_calls(){}
bool mp4_install_native_clock_api(){assert(all_originals());return mode!="clock_install";}
bool mp4_install_fixed_root(){assert(all_originals());return mode!="fixed_install";}
bool mp4_scene_shader_frontends_current(){assert(all_originals()&&publications);return mode!="scene_frontends";}
bool mp4_scene_shader_origin_install(){assert(all_originals()&&publications);return mode!="scene_origin";}
bool mp4_child_native_install_static(const pin::Entry**actual,size_t count){assert(count==7&&actual[0]==&pin::mp4_director_enqueue&&publications==hook_count);return mp4_source_verified&&mode!="native7";}
bool mp4_capture_native_install_static(const pin::Entry&entry){assert(&entry==&pin::mp4_capture_native_publication&&publications==hook_count);return mp4_source_verified&&mode!="capture";}
bool mp4_audio_native_install_static(const pin::Entry&a,const pin::Entry&b){assert(&a==&pin::mp4_audio_canonical_target&&&b==&pin::mp4_audio_source_process_target&&publications==hook_count);return mp4_source_verified&&mode!="audio";}
bool mp4_capture_queue_frontends_bind(const pin::Entry&a,const pin::Entry&b){assert(&a==&pin::mp4_capture_add_target&&&b==&pin::mp4_capture_request_target&&publications==hook_count);return mp4_source_verified&&mode!="queue";}
namespace rotation{bool ready_for_publish(){assert(all_originals());return mode!="helper_rotation";}}
struct Helper{const char*failure;bool ready(){assert(all_originals());return mode!=failure;}};
Helper preview_ui{"helper_preview"},korean_fallback{"helper_fallback"},korean_list_factory{"helper_list"},sound_tracker{"helper_sound"};
struct Hook{const pin::Entry*entry;void*replacement;void**original;};
#define __atomic_store_n model_publish
// ACTUAL_INSTALL
#undef __atomic_store_n
int main(int argc,char**argv){assert(argc==2);mode=argv[1];
 for(size_t i=0;i<hook_count;++i){entries[i]->gateway=reinterpret_cast<uintptr_t>(&ordinary_original)-reinterpret_cast<uintptr_t>(image)-20;entries[i]->slot=(i+1)*sizeof(uintptr_t);}
 if(mode.rfind("gateway_",0)==0||mode.rfind("slot_",0)==0){
  const size_t index=mode.find("first")!=std::string::npos?0:mode.find("middle")!=std::string::npos?hook_count/2:hook_count-1;
  if(mode.rfind("gateway_",0)==0)entries[index]->gateway=0;else entries[index]->slot=0;
 }
 install(nullptr);
 const bool refused=mode=="missing_image"||mode=="primary_image"||mode.rfind("helper_",0)==0||mode.rfind("gateway_",0)==0||mode.rfind("slot_",0)==0;
 assert(ready.load()==!refused);
 if(refused){assert(!publications&&!original_calls&&!finished&&!mp4_export_observer_install_complete.load());
  assert(!state.fps&&!state.quality&&!state.resolution&&!state.aa&&!state.shadow&&!state.expanded);
  assert(!mp4_actor_managed_installed.load()&&!shared_hooks_ready.load());
  if(mode=="missing_image"||mode=="primary_image"){assert(!load_calls_count);assert(state_code=="unsupported");}else assert(state_code=="init_failed");return 0;}
 assert(verify_calls==1&&load_calls_count==1&&all_originals()&&publications==hook_count&&original_calls==hook_count&&finished==1);
 assert(mp4_source_verified==(mode!="api_source"));assert(mp4_export_observer_install_complete.load()==(mode=="normal"));
 assert(module_flags.at(13)==(mode=="normal"));assert(state.fps&&state.quality&&state.resolution&&state.aa&&state.shadow&&state.expanded);
 assert(mp4_actor_managed_installed.load()&&mp4_actor_burst_installed.load()&&shared_hooks_ready.load());
 for(auto*entry:entries){uintptr_t replacement=0;std::memcpy(&replacement,image+entry->slot,sizeof replacement);const auto before=original_calls;reinterpret_cast<void(*)()>(replacement)();assert(original_calls==before+1);}
 assert(original_calls==hook_count*2&&!notes.empty());
}
