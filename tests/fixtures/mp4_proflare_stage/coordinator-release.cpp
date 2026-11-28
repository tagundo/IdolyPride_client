// Engine/IL2CPP/GPU services below are explicit host models; implementation is extracted from shipping source.

#include <cassert>
#include <atomic>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <vector>
using Method=void;enum class Mp4SceneResult{ok,waiting,stale,unsupported,failed};struct Mp4SceneWitness{};struct Mp4ProFlareSourcePlan{};
struct Mp4ProFlareScalarImage{bool captured=true;};struct Mp4ProFlareSubImage{};struct Mp4ProFlareDataImage{void*object=nullptr;bool captured=false,gpu_touched=false;};
struct Mp4ProFlareAccess{Mp4ProFlareAccess(){}};bool thread=true;bool game_call(){return thread;}
std::atomic<bool>mp4_proflare_access_withdrawn{false},mp4_proflare_access_published{false};bool mp4_proflare_data_original_try=false;size_t mp4_proflare_data_birth_count=0;
bool plans_ok=true,birth_release_ok=true,data_release_ok=true,pass_release_ok=true,pass_restore_ok=true,discard_quiet=true;int verify_mode=0,gpu_mode=0,birth_mode=0;std::vector<int>events;unsigned data_clears=0,plan_clears=0;
bool mp4_proflare_source_plans_retire(){events.push_back(8);if(plans_ok)++plan_clears;return plans_ok;}
bool mp4_proflare_pass_restore_references(){events.push_back(2);return pass_restore_ok;}
enum class Mp4ProFlareRetireResult{ok,waiting,failed};Mp4ProFlareRetireResult mp4_proflare_birth_retire(size_t i){assert(i<mp4_proflare_data_birth_count);events.push_back(3);return birth_mode==1?Mp4ProFlareRetireResult::waiting:birth_mode==2?Mp4ProFlareRetireResult::failed:Mp4ProFlareRetireResult::ok;}
bool mp4_proflare_birth_release(){events.push_back(4);if(!birth_release_ok)return false;mp4_proflare_data_birth_count=0;return true;}
bool mp4_proflare_discard_quiet(void*,const Mp4ProFlareDataImage&){return discard_quiet;}
bool mp4_proflare_data_release(Mp4ProFlareDataImage&i,bool(*quiet)(void*,const Mp4ProFlareDataImage&),void*c){events.push_back(5);if(!data_release_ok||(i.gpu_touched&&!quiet(c,i)))return false;if(i.captured)++data_clears;i={};return true;}
bool mp4_proflare_pass_release_references(bool owned){events.push_back(6);return pass_release_ok&&(owned||discard_quiet);}
void mp4_proflare_registry_release(){events.push_back(7);}
void mp4_proflare_sub_release(Mp4ProFlareSubImage&){}void mp4_proflare_scalar_release(Mp4ProFlareScalarImage&){}

bool mp4_stage_activation_physical_family(void*,uint32_t*,uint64_t*){return false;}
bool (*mp4_activation_additional_family)(void*,uint32_t*,uint64_t*)=mp4_stage_activation_physical_family;
bool mp4_proflare_empty_capture_release(){return true;}

#include "coordinator-types.inc"

Mp4SceneResult mp4_proflare_verify_source_restored(){events.push_back(0);if(verify_mode)return verify_mode==1?Mp4SceneResult::waiting:Mp4SceneResult::stale;mp4_proflare_coordinator->restored=true;return Mp4SceneResult::ok;}
Mp4SceneResult mp4_proflare_retire_gpu(){events.push_back(1);return gpu_mode==1?Mp4SceneResult::waiting:gpu_mode==2?Mp4SceneResult::stale:Mp4SceneResult::ok;}

#include "coordinator-release.inc"

void reset(){mp4_activation_additional_family=mp4_stage_activation_physical_family;if(mp4_proflare_coordinator){auto*h=mp4_proflare_coordinator;std::free(h->flares[0].elements);std::free(h);}auto*h=static_cast<Mp4ProFlareCoordinator*>(std::malloc(sizeof(Mp4ProFlareCoordinator)));new(h)Mp4ProFlareCoordinator{};mp4_proflare_coordinator=h;h->started=h->prepared=h->captured=true;h->serial=13;h->count=1;h->flares[0].count=1;h->flares[0].elements=static_cast<Mp4ProFlareOwnedElement*>(std::malloc(sizeof(Mp4ProFlareOwnedElement)));new(h->flares[0].elements)Mp4ProFlareOwnedElement{};h->existing={h,true,false};thread=plans_ok=birth_release_ok=data_release_ok=pass_release_ok=pass_restore_ok=discard_quiet=true;verify_mode=gpu_mode=birth_mode=0;mp4_proflare_access_withdrawn=false;mp4_proflare_access_published=true;mp4_proflare_data_original_try=false;mp4_proflare_data_birth_count=0;data_clears=plan_clears=0;events.clear();}
int main(){unsigned cases=0;reset();assert(mp4_proflare_release(true)==Mp4SceneResult::ok&&!mp4_proflare_coordinator&&!mp4_proflare_access_published&&data_clears==1&&plan_clears==1);assert(events==std::vector<int>({0,4,5,6,7,8})&&!mp4_activation_additional_family);++cases;
 for(int bad=1;bad<=2;++bad){reset();verify_mode=bad;assert(mp4_proflare_release(true)!=(Mp4SceneResult::ok)&&mp4_proflare_coordinator&&events==std::vector<int>({0})&&mp4_proflare_access_published&&mp4_activation_additional_family==mp4_stage_activation_physical_family);++cases;}
 reset();thread=false;assert(mp4_proflare_release(false)==Mp4SceneResult::waiting&&mp4_proflare_coordinator&&events.empty());thread=true;++cases;
 reset();mp4_proflare_data_original_try=true;assert(mp4_proflare_release(false)==Mp4SceneResult::waiting&&events.empty());mp4_proflare_data_original_try=false;++cases;
 reset();mp4_proflare_data_birth_count=1;mp4_proflare_access_withdrawn=true;assert(mp4_proflare_release(false)==Mp4SceneResult::stale&&events.empty()&&mp4_proflare_coordinator&&mp4_proflare_data_birth_count==1);++cases;
 for(int bad=1;bad<=2;++bad){reset();gpu_mode=bad;assert(mp4_proflare_release(false)!=(Mp4SceneResult::ok)&&events==std::vector<int>({1})&&!data_clears&&mp4_proflare_access_published&&mp4_activation_additional_family==mp4_stage_activation_physical_family);++cases;}
 reset();mp4_proflare_data_birth_count=2;assert(mp4_proflare_release(false)==Mp4SceneResult::ok&&!mp4_proflare_coordinator);assert(events==std::vector<int>({1,2,3,3,4,5,6,7,8}));++cases;
 reset();mp4_proflare_data_birth_count=1;pass_restore_ok=false;assert(mp4_proflare_release(false)==Mp4SceneResult::stale&&events==std::vector<int>({1,2}));++cases;
 for(int bad=1;bad<=2;++bad){reset();mp4_proflare_data_birth_count=1;birth_mode=bad;assert(mp4_proflare_release(false)!=(Mp4SceneResult::ok)&&events==std::vector<int>({1,2,3})&&!data_clears&&mp4_proflare_data_birth_count==1);++cases;}
 reset();birth_release_ok=false;assert(mp4_proflare_release(false)==Mp4SceneResult::waiting&&!data_clears&&mp4_proflare_coordinator);++cases;
 reset();data_release_ok=false;assert(mp4_proflare_release(false)==Mp4SceneResult::waiting&&!data_clears&&mp4_proflare_coordinator);++cases;
 reset();pass_release_ok=false;assert(mp4_proflare_release(false)==Mp4SceneResult::waiting&&data_clears==1&&mp4_proflare_coordinator);pass_release_ok=true;assert(mp4_proflare_release(false)==Mp4SceneResult::ok&&data_clears==1);++cases;
 reset();mp4_proflare_coordinator->existing.gpu_touched=true;discard_quiet=false;assert(mp4_proflare_release(false)==Mp4SceneResult::waiting&&!data_clears&&mp4_proflare_coordinator);discard_quiet=true;assert(mp4_proflare_release(false)==Mp4SceneResult::ok&&data_clears==1);++cases;
 reset();plans_ok=false;assert(mp4_proflare_release(false)==Mp4SceneResult::waiting&&!mp4_proflare_coordinator&&!mp4_proflare_access_published&&!plan_clears);plans_ok=true;assert(mp4_proflare_release(false)==Mp4SceneResult::ok&&plan_clears==1);++cases;
 assert(mp4_proflare_release(false)==Mp4SceneResult::ok);++cases;
 std::printf("%u actual PF retirement/release/custody orchestration cases passed\n",cases);}
