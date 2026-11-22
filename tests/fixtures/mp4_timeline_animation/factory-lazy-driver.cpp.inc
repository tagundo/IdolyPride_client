using H=Mp4AnimationFactoryHandle;
int originals=0,configurations=0,gc_calls=0;bool allow=true,config_throw=false,reenter=false,original_throw=false,expect_observed=false;
mp4_animation_factory::Ticket observed{};
bool thread(void*){assert(game_call());return true;}
H original(void*,H,void*,void*,Method*){++originals;mp4_animation_factory::Ticket actual{};const bool active=mp4_animation_factory_publication.load(std::memory_order_acquire)==2&&mp4_animation_factories.active_ticket(&actual);assert(active==expect_observed);if(active)observed=actual;if(original_throw)throw 37;return {0x5566,2,0};}
H invoke(){return mp4_animation_root_factory_hook(reinterpret_cast<void*>(0x1000),{0x1234,2,0},reinterpret_cast<void*>(0x2000),reinterpret_cast<void*>(0x3000),reinterpret_cast<Method*>(0xdead));}
bool bindings(void*){assert(game_call());if(config_throw)throw 41;if(reenter){reenter=false;assert(mp4_animation_factory_publication.load(std::memory_order_acquire)==1);const bool saved=expect_observed;expect_observed=false;invoke();expect_observed=saved;}return allow;}
bool origin(void*,const mp4_animation_factory::Input&i,mp4_animation_factory::Origin*out){*out={1,2,0x9000,i.game_object,0x8000,i.graph.version&~uint32_t(1),0,false};return true;}
bool inspect(void*,const mp4_animation_factory::Input&,mp4_animation_factory::Image*out){*out={};return true;}
bool nested(void*,const mp4_animation_factory::Input&,const mp4_animation_factory::Input&,const mp4_animation_factory::Input&){return true;}
bool returned(void*,const mp4_animation_factory::Input&,H){return true;}
bool settled(void*,const mp4_animation_factory::Origin&,H,H*out){*out={99,2,0};return true;}
uint32_t retain(void*p){assert(game_call());++gc_calls;return static_cast<uint32_t>(reinterpret_cast<uintptr_t>(p));}void*target(uint32_t h){assert(game_call());return reinterpret_cast<void*>(uintptr_t(h));}void drop(uint32_t){assert(game_call());}
bool mp4_animation_factory_configure(){assert(game_call());++configurations;return mp4_animation_factory_publish({nullptr,thread,bindings,origin,inspect,nested,returned,settled,retain,target,drop});}
int main(int argc,char**argv){assert(argc==2);const std::string name=argv[1];mp4_animation_root_factory_original=original;
 if(name=="foreign_first"){std::thread foreign([]{invoke();});foreign.join();assert(originals==1&&!configurations&&!gc_calls&&!observed.serial);}
 if(name=="refused"||name=="configure_throw"){allow=name!="refused";config_throw=name=="configure_throw";invoke();assert(originals==1&&configurations==1&&!gc_calls&&!observed.serial&&mp4_animation_factory_publication.load()==0);allow=true;config_throw=false;}
 reenter=name=="reentrant_configure";original_throw=name=="original_throw";expect_observed=true;bool threw=false;try{invoke();}catch(int v){assert(v==37);threw=true;}assert(threw==original_throw);assert(observed.serial&&configurations==(name=="refused"||name=="configure_throw"?2:1));assert(mp4_animation_factory_publication.load()==2);
 if(!original_throw){mp4_animation_factory::Receipt receipt{};assert(mp4_animation_factories.receipt(observed,&receipt)&&receipt.ticket.serial==observed.serial);}
 const auto count=configurations;original_throw=false;invoke();assert(configurations==count);assert(mp4_animation_factories.clear());return 0;}
