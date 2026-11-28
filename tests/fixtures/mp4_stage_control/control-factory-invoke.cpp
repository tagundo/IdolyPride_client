#include <cassert>
#include <cstdint>
#include <string>
using Method=const void;
namespace mp4ctl{
struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};
struct Ticket{bool owned=false;};enum class Dispatch{forward,owned,reject};enum class Result{ok,failed};
}
int asset,owner,method;
std::string scenario;
bool main_thread=true;
size_t original_calls=0,passive_befores=0,passive_afters=0,passive_failed=0,foreigns=0,scope_befores=0,scope_afters=0;
mp4ctl::Dispatch route=mp4ctl::Dispatch::owned;
struct{bool invalidated=false;const char*error="none";}mp4_stage_host;
bool game_call(){return main_thread;}
struct Mp4ControlPassiveTicket{bool active=false;void clear(){active=false;}};
void mp4_control_passive_foreign(){++foreigns;}
bool mp4_control_passive_before(void*a,mp4ctl::Handle g,void*o,Method*m,Mp4ControlPassiveTicket&t){assert(a==&asset&&g.handle==42&&o==&owner&&m==&method);++passive_befores;t.active=true;if(scenario=="passive_before_throw")throw 9;return true;}
bool mp4_control_passive_after(Mp4ControlPassiveTicket&t,mp4ctl::Handle r,bool completed){if(!t.active)return false;t.active=false;if(!completed){++passive_failed;return false;}assert(r.handle==101&&original_calls==1);++passive_afters;if(scenario=="passive_after_throw")throw 8;return true;}
struct{
 mp4ctl::Dispatch before(void*,mp4ctl::Handle,void*,mp4ctl::Ticket&t){++scope_befores;t.owned=route==mp4ctl::Dispatch::owned;return route;}
 mp4ctl::Result after(mp4ctl::Ticket&t,mp4ctl::Handle r,bool completed){assert(t.owned);t.owned=false;++scope_afters;if(!completed){assert(passive_failed==1);if(scenario=="secondary_after_throw")throw 44;return mp4ctl::Result::failed;}assert(r.handle==101&&original_calls==1&&(passive_afters==1||scenario=="passive_before_throw"));if(scenario=="private_after_throw")throw 45;return scenario=="private_after_failed"?mp4ctl::Result::failed:mp4ctl::Result::ok;}
 const char*error()const{return "scope_failed";}
}mp4_control_assets;
#include "control-factory-invoke.cpp.inc"
mp4ctl::Handle original(void*a,mp4ctl::Handle g,void*o,Method*m){assert(a==&asset&&g.handle==42&&o==&owner&&m==&method);++original_calls;if(scenario=="original_throw"||scenario=="secondary_after_throw")throw 17;return {101,2,0};}
int main(int argc,char**argv){assert(argc==2);scenario=argv[1];
 if(scenario=="forward")route=mp4ctl::Dispatch::forward;
 if(scenario=="reject")route=mp4ctl::Dispatch::reject;
 if(scenario=="foreign"){main_thread=false;route=mp4ctl::Dispatch::reject;}
 if(scenario=="null_original"){assert(!mp4_control_factory_invoke(nullptr,&asset,{42,2,0},&owner,&method).handle&&!original_calls&&!passive_befores);return 0;}
 mp4ctl::Handle result{};
 try{result=mp4_control_factory_invoke(original,&asset,{42,2,0},&owner,&method);}
 catch(int code){
  if(scenario=="private_after_throw"){assert(code==45&&mp4_stage_host.invalidated&&scope_afters==1);return 0;}
  assert((scenario=="original_throw"||scenario=="secondary_after_throw")&&code==17&&original_calls==1&&passive_failed==1&&scope_afters==1&&mp4_stage_host.invalidated);return 0;
 }
 if(scenario=="reject"){assert(!result.handle&&!original_calls&&passive_befores==1&&!passive_afters&&!scope_afters&&mp4_stage_host.invalidated);return 0;}
 assert(result.handle==101&&original_calls==1);
 if(scenario=="foreign"){assert(foreigns==1&&!passive_befores&&!scope_befores&&!passive_afters);return 0;}
 assert(passive_befores==1&&scope_befores==1&&scope_afters==(route==mp4ctl::Dispatch::owned?1u:0u));
 assert(passive_afters==(scenario=="passive_before_throw"?0u:1u));
 assert(mp4_stage_host.invalidated==(scenario=="private_after_failed"));
}
