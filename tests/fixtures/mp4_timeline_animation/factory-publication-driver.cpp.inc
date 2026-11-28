bool mp4_animation_factory_configure(){return false;} // explicit refused lazy source/CAPI leaf in this fixture
// Real publication/core/frontend bodies; only Unity identity/query leaves below
// are modeled. The actual configuring callback is held while a foreign thread
// invokes every installed factory frontend.
using H=Mp4AnimationFactoryHandle;using V=Mp4AnimationFactoryVec3;
static std::atomic<unsigned>originals{0},bindings_entered{0},foreign_done{0};
static std::atomic<bool>pause_configuration{false};
static bool throw_original=false,fail_bindings=false;
static bool host_thread(void*){assert(game_call());return true;}
static bool bindings(void*){
 assert(game_call());
 if(pause_configuration.load(std::memory_order_acquire)){
  bindings_entered.store(1,std::memory_order_release);
  while(!foreign_done.load(std::memory_order_acquire))std::this_thread::yield();
 }
 return !fail_bindings;
}
static bool origin(void*,const mp4_animation_factory::Input&i,mp4_animation_factory::Origin*out){assert(game_call());*out={1,2,0x9000,i.game_object,0x8000,i.graph.version&~uint32_t(1),0,false};return true;}
static bool inspect(void*,const mp4_animation_factory::Input&,mp4_animation_factory::Image*out){assert(game_call());*out={};return true;}
static bool nested(void*,const mp4_animation_factory::Input&,const mp4_animation_factory::Input&,const mp4_animation_factory::Input&){assert(game_call());return true;}
static bool returned(void*,const mp4_animation_factory::Input&,H){assert(game_call());return true;}
static bool settled(void*,const mp4_animation_factory::Origin&,H,H*out){assert(game_call());*out={99,2,0};return true;}
static uint32_t retain(void*p){assert(game_call());return static_cast<uint32_t>(reinterpret_cast<uintptr_t>(p));}
static void*target(uint32_t h){assert(game_call());return reinterpret_cast<void*>(uintptr_t(h));}
static void release(uint32_t){assert(game_call());}
static H called(){originals.fetch_add(1,std::memory_order_relaxed);if(throw_original)throw 37;return {0x5566,2,0};}
static H root_original(void*,H,void*,void*,Method*){return called();}
static H clips_original(void*,H,void*,void*,void*,int32_t,Method*){return called();}
static H infinite_original(void*,H,void*,void*,int32_t,Method*){return called();}
static H clip_original(H,void*,V,V,bool,int32_t,bool,int32_t,Method*){return called();}
static void all_originals(){
 H g{0x1234,2,0};auto*p=reinterpret_cast<void*>(uintptr_t(0x1000));
 auto*q=reinterpret_cast<void*>(uintptr_t(0x2000));auto*t=reinterpret_cast<void*>(uintptr_t(0x3000));
 Method*m=reinterpret_cast<Method*>(uintptr_t(0xdead));
 for(unsigned k=0;k<4;++k){bool threw=false;try{
  H result{};if(k==0)result=mp4_animation_root_factory_hook(p,g,q,t,m);
  if(k==1)result=mp4_animation_clips_factory_hook(p,g,p,q,t,1,m);
  if(k==2)result=mp4_animation_infinite_factory_hook(p,g,q,t,1,m);
  if(k==3)result=mp4_animation_clip_factory_hook(g,p,{1,2,3},{4,5,6},false,1,false,0,m);
  assert(result.handle==0x5566&&result.version==2);
 }catch(int value){assert(value==37);threw=true;}assert(threw==throw_original);}
}
int main(int argc,char**argv){
 assert(argc==2);const std::string name=argv[1];throw_original=name=="throw";fail_bindings=name=="failed_configure";
 mp4_animation_root_factory_original=root_original;mp4_animation_clips_factory_original=clips_original;
 mp4_animation_infinite_factory_original=infinite_original;mp4_animation_clip_factory_original=clip_original;
 all_originals();assert(originals==4); // Unpublished main calls are forwarded.
 mp4_animation_factory::Api api{nullptr,host_thread,bindings,origin,inspect,nested,returned,settled,retain,target,release};
 pause_configuration.store(true,std::memory_order_release);
 std::thread foreign([&]{while(!bindings_entered.load(std::memory_order_acquire))std::this_thread::yield();
  assert(!mp4_animation_factory_observation_entry());all_originals();foreign_done.store(1,std::memory_order_release);
 });
 const bool published=mp4_animation_factory_publish(api);foreign.join();
 assert(originals==8&&published==!fail_bindings);assert(mp4_animation_factory_publication.load(std::memory_order_acquire)==(published?2:0));
 pause_configuration.store(false,std::memory_order_release);
 if(fail_bindings){assert(!mp4_animation_factory_observation_entry());fail_bindings=false;assert(mp4_animation_factory_publish(api));}
 assert(mp4_animation_factory_observation_entry());assert(!mp4_animation_factory_publish(api));
 all_originals();assert(originals==12);
 // Publication is stable even after foreign calls: those calls only invalidate
 // the atomic Journal generation, never read/write Api/rows or retain objects.
 std::thread after([&]{all_originals();});after.join();assert(originals==16);
 assert(mp4_animation_factory_observation_entry());assert(mp4_animation_factories.clear());
 return 0;
}
