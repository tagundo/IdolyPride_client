#include <cassert>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include "../sound_persistence.hpp"
namespace sp=idoly::presentation::sound_persistence;
struct Object { unsigned char raw[256]{}; } presenter,model,settings,other;
void *handles[32]{};int live_handles=0,clock_reads=0,saves=0;bool active=true,alive=true,save_ok=true;int64_t now=1000;
template<class T> void put(Object &o,size_t offset,T value){std::memcpy(o.raw+offset,&value,sizeof value);}
uint32_t weak_new(void *p,bool flag){assert(!flag);for(unsigned i=1;i<32;++i)if(!handles[i]){handles[i]=p;++live_handles;return i;}return 0;}
void *weak_get(uint32_t h){return h<32?handles[h]:nullptr;}
void weak_free(uint32_t h){assert(h&&h<32);if(handles[h])--live_handles;handles[h]=nullptr;}
bool matches(void *p,const char *ns,const char *name){return (p==&presenter&&((!std::strcmp(ns,"Solis.OutGame")&&!std::strcmp(name,"GameSettingTopScreenPresenter"))||(!std::strcmp(ns,"UnityEngine")&&!std::strcmp(name,"Behaviour"))))||(p==&model&&!std::strcmp(name,"GameSettingTopScreenModel"))||((p==&settings||p==&other)&&!std::strcmp(name,"GameSetting"));}
bool is_alive(void*p,sp::Method*){assert(p==&presenter);return alive;}
bool is_active(void*p,sp::Method*){assert(p==&presenter);return active;}
int64_t clock_ms(){++clock_reads;return now;}
bool save(void *p){assert(p==&settings||p==&other);++saves;return save_ok;}
sp::Calls calls{weak_new,weak_get,weak_free,matches,is_alive,is_active,clock_ms,save};
sp::Tracker tracker;
int binds=0;bool inside_bind_change=false,throw_bind=false,nested_bind=false;
void edit(sp::Field field,float value,bool enabled=true){auto before=tracker.before(&model,field,enabled);put(settings,field==sp::Field::BgmVolume?0x18:field==sp::Field::SeVolume?0x20:0x28,value);tracker.after(&model,before,enabled);}
void bind_original(void *self,sp::Method *m){assert(self==&presenter&&m==(void*)0x1234);++binds;if(inside_bind_change)edit(sp::Field::BgmVolume,.33f);if(nested_bind){nested_bind=false;tracker.bind(self,m,bind_original,true);}if(throw_bind)throw std::runtime_error("original");}
void arm(){tracker.bind(&presenter,(void*)0x1234,bind_original,true);}
void reset(){tracker.configure(calls);std::memset(handles,0,sizeof handles);live_handles=0;put(presenter,0xe0,(void*)&model);put(model,0x18,(void*)&settings);put(settings,0x18,.5f);put(settings,0x20,.5f);put(settings,0x28,.7f);put(settings,0x1c,uint8_t(1));put(settings,0x24,uint8_t(1));put(settings,0x2c,uint8_t(1));now=1000;clock_reads=saves=0;active=alive=save_ok=true;inside_bind_change=throw_bind=nested_bind=false;}
int main(){
 reset();for(int i=0;i<10000;++i)tracker.tick(true);assert(clock_reads==0&&saves==0);
 edit(sp::Field::BgmVolume,.2f);assert(!tracker.pending()); // constructor/unbound
 inside_bind_change=true;arm();inside_bind_change=false;assert(!tracker.pending()&&saves==0&&clock_reads==0);
 edit(sp::Field::BgmVolume,.33f);assert(!tracker.pending()&&clock_reads==0); // no change
 edit(sp::Field::BgmVolume,.2f);assert(tracker.pending()&&clock_reads==1);now+=399;tracker.tick(true);assert(!saves);++now;tracker.tick(true);assert(saves==1&&!tracker.pending());
 const int reads=clock_reads;for(int i=0;i<10000;++i)tracker.tick(true);assert(clock_reads==reads); // idle no clock
 for(auto field:{sp::Field::BgmVolume,sp::Field::SeVolume,sp::Field::VoiceVolume}){edit(field,.4f);now+=400;tracker.tick(true);}assert(saves==4);
 for(auto field:{sp::Field::BgmSoundable,sp::Field::SeSoundable,sp::Field::VoiceSoundable}){auto b=tracker.before(&model,field,true);put(settings,field==sp::Field::BgmSoundable?0x1c:field==sp::Field::SeSoundable?0x24:0x2c,uint8_t(0));tracker.after(&model,b,true);now+=400;tracker.tick(true);}assert(saves==7);
 edit(sp::Field::BgmVolume,.1f);now+=300;edit(sp::Field::BgmVolume,.2f);now+=399;tracker.tick(true);assert(saves==7);++now;tracker.tick(true);assert(saves==8); // gesture coalescing
 edit(sp::Field::BgmVolume,.1f,false);assert(!tracker.pending()); // original changed, off-thread no tracking
 active=false;edit(sp::Field::BgmVolume,.2f);assert(!tracker.pending());active=true;
 edit(sp::Field::BgmVolume,.27f);assert(tracker.pending());nested_bind=true;inside_bind_change=true;arm();inside_bind_change=false;assert(!tracker.pending()); // rebinding clears an old gesture; nested emissions suppressed
 throw_bind=true;try{arm();assert(false);}catch(const std::runtime_error&){}throw_bind=false;edit(sp::Field::BgmVolume,.25f);assert(!tracker.pending());arm();
 edit(sp::Field::BgmVolume,.3f);tracker.observed_save(&other,true);assert(tracker.pending());tracker.observed_save(&settings,true);assert(!tracker.pending()); // original close-save
 now=-1;edit(sp::Field::BgmVolume,.35f);tracker.tick(true);assert(tracker.pending());now=5000;tracker.tick(true);assert(tracker.pending());now+=400;tracker.tick(true);assert(!tracker.pending()); // invalid clock recovers
 edit(sp::Field::BgmVolume,.4f);now-=100;tracker.tick(true);assert(tracker.pending());now+=400;tracker.tick(true);assert(!tracker.pending()); // rollback
 edit(sp::Field::BgmVolume,.45f);save_ok=false;now+=400;const int base=saves;tracker.tick(true);assert(saves==base+1&&tracker.pending());for(int i=0;i<100;++i)tracker.tick(true);assert(saves==base+1);now+=1999;tracker.tick(true);assert(saves==base+1);++now;save_ok=true;tracker.tick(true);assert(saves==base+2&&!tracker.pending()); // failure retry, no per-frame I/O
 edit(sp::Field::BgmVolume,.5f);for(unsigned i=1;i<32;++i)if(handles[i]==&settings)handles[i]=nullptr;now+=400;const int old=saves;tracker.tick(true);assert(!tracker.pending()&&saves==old); // freed weak
 reset();arm();edit(sp::Field::BgmVolume,.4f);put(model,0x18,(void*)&other);arm();assert(!tracker.pending()); // replaced identity
 reset();arm();edit(sp::Field::BgmVolume,.4f);put(model,0x18,(void*)&other);now+=400;tracker.tick(true);assert(!tracker.pending()&&!saves); // replacement without rebinding
 reset();arm();edit(sp::Field::BgmVolume,.4f);put(presenter,0xe0,(void*)nullptr);now+=400;tracker.tick(true);assert(!tracker.pending()&&!saves); // detached model
 reset();arm();edit(sp::Field::BgmVolume,.4f);for(unsigned i=1;i<32;++i)if(handles[i]==&model)handles[i]=nullptr;now+=400;tracker.tick(true);assert(!tracker.pending()&&!saves); // destroyed managed model
 reset();arm();edit(sp::Field::BgmVolume,.4f);alive=false;now+=400;tracker.tick(true);assert(!tracker.pending()&&!saves); // destroyed presenter
 reset();arm();edit(sp::Field::BgmVolume,.4f);active=false;now+=400;tracker.tick(true);assert(!tracker.pending()&&!saves); // hidden presenter
 reset();arm();auto b=tracker.before(&model,sp::Field::BgmVolume,true);put(settings,0x18,2.f);tracker.after(&model,b,true);assert(!tracker.pending());
 tracker.configure({});assert(!tracker.ready());
}
