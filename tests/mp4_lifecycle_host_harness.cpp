#include <atomic>
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>
struct Method{};
#include "lifecycle_types.inc"
using VoidMethod=void(*)(void*,Method*);
std::vector<std::string> events;std::string fail_at;
unsigned original_calls=0,poisons=0;
void* self=reinterpret_cast<void*>(0x1111);void* parameter=reinterpret_cast<void*>(0x2222);
void* transition=reinterpret_cast<void*>(0x3333);void* capture=reinterpret_cast<void*>(0x4444);
void* descriptors=reinterpret_cast<void*>(0x5555);void* token_source=reinterpret_cast<void*>(0x6666);
Method metadata;Mp4UniTask expected{reinterpret_cast<void*>(0x7777),171,{1,2,3,4,5,6}};
void step(const char* name){assert(mp4_original_lifecycle_depth==(std::string(name)=="original"?1u:0u));
 events.emplace_back(name);if(fail_at==name)throw std::runtime_error(name);}
bool game_call(bool=false){return true;}std::atomic<bool> ready{true};
struct {uint64_t epoch=3;void* player=self;void* presenter=self;}mp4_actor_host;
void mp4_scene_restore_globals_before_source_change(void* context){assert(!context);step("globals");}
void mp4_scene_will_change(void* source){assert(source==self);step("scene");}
void mp4_actor_scene_will_change(void* source){assert(source==self);step("actor");}
bool mp4_prepare_runtime(){step("runtime");return true;}
bool mp4_type_is(void* source,const char* name){assert(source==self&&std::string(name)=="Solis.Photography.PhotographyLivePresenter");return true;}
namespace idoly_mp4_runtime {
void observe_source_handoff_failed(void* source)noexcept{assert(source==self);++poisons;}
void observe_source_will_change(void* source){assert(source==self);step("source_observe");}
void observe_player_initializing(void* source,void* param){assert(source==self&&param==parameter);step("player_observe");}
void observe_presenter_ended(void* source){assert(source==self);step("end_observe");}
void observe_photography_initializing(void* source,void* data,void* frozen){assert(source==self&&data==parameter&&frozen==descriptors);step("photo_observe");}
}
void* mp4_normalize_photography_descriptors(void* data){assert(data==parameter);step("descriptors");return descriptors;}
struct Presenter {void* object=self;void set(void* source){assert(source==self);step("presenter_set");object=source;}
 void* get(){step("presenter_get");return object;}void clear(){step("presenter_clear");object=nullptr;}}mp4_photography_presenter;
struct {uint64_t generation=11;bool failed=false;char error[96]{};}mp4_photography_navigation;
void original(){++original_calls;
 {Mp4LifecycleOriginalDepth nested;assert(mp4_original_lifecycle_depth==2);}
 step("original");}
Mp4UniTask player(void* source,void* param,bool setup,Mp4CancellationToken token,Method* method){
 assert(source==self&&param==parameter&&!setup&&token.source==token_source&&method==&metadata);original();return expected;}
Mp4UniTask end(void* source,Mp4CancellationToken token,Method* method){
 assert(source==self&&token.source==token_source&&method==&metadata);original();return expected;}
Mp4UniTask photo(void* source,void* trans,void* cap,Mp4CancellationToken token,Method* method){
 assert(source==self&&trans==transition&&cap==capture&&token.source==token_source&&method==&metadata);original();return expected;}
Mp4UniTask photo_player(void* source,void* data,Mp4CancellationToken token,Method* method){
 assert(source==self&&data==parameter&&token.source==token_source&&method==&metadata);original();return expected;}
void photo_end(void* source,Method* method){assert(source==self&&method==&metadata);original();}
using Mp4PlayerInitialize=Mp4UniTask(*)(void*,void*,bool,Mp4CancellationToken,Method*);
using Mp4PresenterEnd=Mp4UniTask(*)(void*,Mp4CancellationToken,Method*);
using Mp4PhotographyInitialize=Mp4UniTask(*)(void*,void*,void*,Mp4CancellationToken,Method*);
using Mp4PhotographyPlayerInitialize=Mp4UniTask(*)(void*,void*,Mp4CancellationToken,Method*);
Mp4PlayerInitialize mp4_player_initialize_original=player;
Mp4PresenterEnd mp4_presenter_end_original=end;
Mp4PhotographyInitialize mp4_photography_initialize_original=photo;
Mp4PhotographyPlayerInitialize mp4_photography_player_initialize_original=photo_player;
VoidMethod mp4_photography_end_original=photo_end;
#include "lifecycle_hooks.inc"
int main(int argc,char** argv){assert(argc==3);const std::string route=argv[1];fail_at=argv[2];
 Mp4UniTask result{};bool threw=false;try{
  if(route=="player")result=mp4_player_initialize_hook(self,parameter,false,{token_source},&metadata);
  else if(route=="end")result=mp4_presenter_end_hook(self,{token_source},&metadata);
  else if(route=="photo")result=mp4_photography_initialize_hook(self,transition,capture,{token_source},&metadata);
  else if(route=="photo_player")result=mp4_photography_player_initialize_hook(self,parameter,{token_source},&metadata);
  else if(route=="photo_end")mp4_photography_end_hook(self,&metadata);
  else assert(false);
 }catch(const std::runtime_error&){threw=true;}
 assert(original_calls==1&&events.back()=="original"&&mp4_original_lifecycle_depth==0);
 const bool original_throw=fail_at=="original";assert(threw==original_throw);
 const bool observed_exception=fail_at!="none"&&!original_throw;
 assert(poisons==(observed_exception?1u:0u));
 if(!threw&&route!="photo_end")assert(!std::memcmp(&result,&expected,sizeof result));
 if(observed_exception){unsigned calls=0;for(const auto& event:events)if(event==fail_at)++calls;assert(calls==1);}
 return 0;
}
