#include <cstdint>
#include <cstdio>
#include <cassert>
bool thread=true,hooks=true,before=true,operation=true,current=true,journal_result=true,post=true,detached=true;unsigned before_calls=0,pending_calls=0;
bool game_call(){return thread;}bool mp4_audio_native_hooks_current(){return hooks;}
bool mp4_audio_native_hook_ready=false,mp4_audio_process_hook_ready=false;
void*mp4_audio_source_clip(void*){return nullptr;}void*wrong_clip(void*){return nullptr;}
void*(*mp4_audio_managed_clip)(void*)=mp4_audio_source_clip;struct{bool verified=true;}mp4_camera_host;
bool mp4_post_restore_detached(uint64_t){return detached;}bool wrong_detached(uint64_t){return false;}
bool(*mp4_audio_natural_restore_detached)(uint64_t)=mp4_post_restore_detached;
bool(*mp4_audio_natural_restore_route_ready)()=nullptr;
bool(*mp4_audio_pending_destroy_receipt)(uint64_t,uintptr_t,uintptr_t,uint32_t,uint64_t,uintptr_t)=nullptr;
bool mp4_post_restore_routes_ready(){return post;}
namespace mp4_director_maintenance{struct Call{uint64_t epoch=0,serial=0;};}
uint64_t actual_epoch=7;
bool mp4_director_actual_operation(mp4_director_maintenance::Call*out){if(!operation)return false;*out={actual_epoch,45};return true;}
struct Journal{bool current_call(const mp4_director_maintenance::Call&call){return current&&call.epoch==7&&call.serial==45;}
 bool pending_destroy_receipt(uint64_t e,uintptr_t n,uintptr_t s,uint32_t v,uint64_t r,uintptr_t o){++pending_calls;assert(e==7&&n==11&&s==13&&v==2&&r==17&&o==19);return journal_result;}}journal;
struct{Journal&journal(){return ::journal;}}mp4_child_pending_host;
bool mp4_audio_retired_before_closed(uint64_t e,uintptr_t n,uintptr_t s,uint32_t v,uint64_t r,uintptr_t o){++before_calls;assert(e==7&&n==11&&s==13&&v==2&&r==17&&o==19);return before;}
// RETIREMENT_BIND
void reset(){thread=hooks=before=operation=current=journal_result=post=detached=true;actual_epoch=7;before_calls=pending_calls=0;mp4_audio_native_hook_ready=mp4_audio_process_hook_ready=false;mp4_audio_managed_clip=mp4_audio_source_clip;mp4_camera_host.verified=true;mp4_audio_natural_restore_detached=mp4_post_restore_detached;mp4_audio_natural_restore_route_ready=nullptr;mp4_audio_pending_destroy_receipt=nullptr;}
int main(){unsigned cases=0;
 {reset();assert(mp4_bind_audio_native_frontends()&&mp4_audio_natural_restore_route_ready==mp4_audio_native_routes_current&&mp4_audio_native_routes_current());++cases;}
 {reset();hooks=false;assert(!mp4_bind_audio_native_frontends()&&!mp4_audio_native_hook_ready&&!mp4_audio_pending_destroy_receipt);++cases;}
 {reset();mp4_camera_host.verified=false;assert(!mp4_bind_audio_native_frontends());++cases;}
 {reset();mp4_audio_managed_clip=wrong_clip;assert(!mp4_bind_audio_native_frontends());++cases;}
 {reset();post=false;assert(!mp4_bind_audio_native_frontends());++cases;}
 {reset();assert(mp4_bind_audio_native_frontends());hooks=false;assert(!mp4_audio_native_routes_current());++cases;}
 {reset();assert(mp4_bind_audio_native_frontends());mp4_audio_pending_destroy_receipt=nullptr;assert(!mp4_audio_native_routes_current());++cases;}
 {reset();assert(mp4_bind_audio_native_frontends());mp4_audio_natural_restore_detached=wrong_detached;assert(!mp4_audio_native_routes_current());++cases;}
 {reset();assert(mp4_audio_native_pending_destroy(7,11,13,2,17,19)&&pending_calls==1&&!before_calls);++cases;}
 {reset();thread=false;assert(!mp4_audio_native_pending_destroy(7,11,13,2,17,19)&&!pending_calls);++cases;}
 {reset();operation=false;assert(!mp4_audio_native_pending_destroy(7,11,13,2,17,19)&&!pending_calls);++cases;}
 {reset();actual_epoch=8;assert(!mp4_audio_native_pending_destroy(7,11,13,2,17,19)&&!pending_calls);++cases;}
 {reset();current=false;assert(!mp4_audio_native_pending_destroy(7,11,13,2,17,19)&&!pending_calls);++cases;}
 {reset();journal_result=false;assert(!mp4_audio_native_pending_destroy(7,11,13,2,17,19)&&pending_calls==1);++cases;}
 {reset();assert(mp4_audio_native_retired_output(nullptr,7,11,13,2,17,19)&&before_calls==1&&!pending_calls);++cases;}
 {reset();before=false;assert(!mp4_audio_native_retired_output(nullptr,7,11,13,2,17,19)&&before_calls==1&&!pending_calls);++cases;}
 {reset();thread=false;assert(!mp4_audio_native_retired_output(nullptr,7,11,13,2,17,19)&&!before_calls);++cases;}
 printf("%u actual Audio retirement binding cases; Journal/physical leaf calls modeled\n",cases);
}
