// Engine/IL2CPP/GPU services below are explicit host models; implementation is extracted from shipping source.

#include <cassert>
#include <cstdint>
#include <cstdio>
using Method=void;bool main_thread=true;bool game_call(){return main_thread;}unsigned access_depth=0;
struct Mp4ProFlareAccess{explicit Mp4ProFlareAccess(bool original){assert(original);++access_depth;}~Mp4ProFlareAccess(){--access_depth;}};
namespace mp4pf{enum class Operation{enable,disable};enum class Result{unowned};}
bool scope_active=true,owned_result=true,throw_original=false;unsigned original_calls=0,owned_calls=0,handoffs=0,start_calls=0,lifecycle_calls=0,init_calls=0,late_calls=0,disable_calls=0;uintptr_t init_pc=0;
struct{bool active(){return scope_active;}}mp4_proflare_registry_scope;
bool mp4_owned_render_ticket_active=true;unsigned mp4_owned_render_depth=1,mp4_unowned_render_depth=0;
using Lifecycle=void(*)(void*,Method*);using Try=bool(*)(void*,void*,void**,Method*);using Initialize=void(*)(void*,int32_t,Method*);
void actual_lifecycle(void*,Method*){assert(access_depth);++original_calls;if(throw_original)throw 37;}
bool actual_try(void*,void*,void**,Method*){assert(access_depth);++original_calls;if(throw_original)throw 41;return true;}
void actual_init(void*,int32_t,Method*){assert(access_depth);++original_calls;}
Lifecycle mp4_proflare_start_trampoline=actual_lifecycle,mp4_proflare_enable_trampoline=actual_lifecycle,mp4_proflare_disable_trampoline=actual_lifecycle,mp4_proflare_batch_late_trampoline=actual_lifecycle,mp4_proflare_batch_disable_trampoline=actual_lifecycle;
Try mp4_proflare_try_trampoline=actual_try;Initialize mp4_proflare_initialize_trampoline=actual_init;
bool mp4_proflare_handoff(void*,mp4pf::Result){assert(access_depth);++handoffs;return false;}
bool mp4_proflare_try_invoke(void*self,void*camera,void**out,Method*m,Try original){assert(access_depth&&original==actual_try);++owned_calls;return owned_result?original(self,camera,out,m):false;}
bool mp4_proflare_start_invoke(void*self,Method*m,Lifecycle original){assert(access_depth);++start_calls;original(self,m);return true;}
void mp4_proflare_lifecycle_invoke(mp4pf::Operation,void*self,Method*m,Lifecycle original){assert(access_depth);++lifecycle_calls;original(self,m);}
void mp4_proflare_initialize_invoke(void*self,int32_t count,Method*m,uintptr_t pc,Initialize original){assert(access_depth);++init_calls;init_pc=pc;original(self,count,m);}
void mp4_proflare_batch_late_invoke(void*self,Method*m,Lifecycle original){Mp4ProFlareAccess access(true);++late_calls;original(self,m);}
void mp4_proflare_batch_disable_invoke(void*self,Method*m,Lifecycle original){Mp4ProFlareAccess access(true);++disable_calls;original(self,m);}

#include "frontends-host.inc"

void reset(){assert(!access_depth);main_thread=scope_active=owned_result=mp4_owned_render_ticket_active=true;throw_original=false;mp4_owned_render_depth=1;mp4_unowned_render_depth=0;original_calls=owned_calls=handoffs=start_calls=lifecycle_calls=init_calls=late_calls=disable_calls=0;}
int main(){unsigned cases=0;reset();void*out=nullptr;assert(mp4_proflare_try_hook(nullptr,nullptr,&out,nullptr)&&owned_calls==1&&original_calls==1&&!handoffs);++cases;
 reset();owned_result=false;assert(!mp4_proflare_try_hook(nullptr,nullptr,&out,nullptr)&&owned_calls==1&&!original_calls&&!handoffs);++cases;
 for(int bad=0;bad<4;++bad){reset();if(bad==0)main_thread=false;if(bad==1)mp4_owned_render_ticket_active=false;if(bad==2)mp4_owned_render_depth=0;if(bad==3)mp4_unowned_render_depth=1;assert(mp4_proflare_try_hook(nullptr,nullptr,&out,nullptr)&&original_calls==1&&!owned_calls&&handoffs==1);++cases;}
 reset();scope_active=false;main_thread=false;assert(mp4_proflare_try_hook(nullptr,nullptr,&out,nullptr)&&original_calls==1&&owned_calls==1&&!handoffs);++cases;
 reset();throw_original=true;mp4_owned_render_ticket_active=false;bool caught=false;try{(void)mp4_proflare_try_hook(nullptr,nullptr,&out,nullptr);}catch(int e){caught=e==41;}assert(caught&&original_calls==1&&handoffs==1&&!access_depth);++cases;
 reset();mp4_proflare_start_hook(nullptr,nullptr);mp4_proflare_enable_hook(nullptr,nullptr);mp4_proflare_disable_hook(nullptr,nullptr);assert(original_calls==3&&start_calls==1&&lifecycle_calls==2&&!access_depth);++cases;
 reset();mp4_proflare_initialize_hook(nullptr,17,nullptr);assert(init_calls==1&&init_pc&&original_calls==1&&!access_depth);++cases;
 reset();mp4_proflare_batch_late_hook(nullptr,nullptr);mp4_proflare_batch_disable_hook(nullptr,nullptr);assert(original_calls==2&&late_calls==1&&disable_calls==1&&!access_depth);++cases;
 reset();mp4_proflare_try_original=nullptr;assert(!mp4_proflare_try_hook(nullptr,nullptr,&out,nullptr)&&!original_calls&&!owned_calls&&!access_depth);mp4_proflare_try_original=actual_try;++cases;
 std::printf("%u actual PF whole frontend/original forwarding cases passed\n",cases);}
