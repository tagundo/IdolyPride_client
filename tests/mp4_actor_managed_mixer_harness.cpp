#include "mp4_actor_state.hpp"
#include <cassert>
#include <map>
#include <cstring>
#include <cstdio>
using namespace idoly_mp4_actor;
struct Object {alignas(8) uint8_t data[512]{};const char* type;};
struct Fixture {
    Object param{{},"VL.Playables.VLAnimationClipParamMixerPlayable"},timeline{{},"VL.Timeline.VLAnimationClipPlayerTimelineMixerPlayable"},
        fresh{{},"VL.Timeline.VLAnimationClipPlayerTimelineMixerPlayable"},layers{{},"System.Array"},player{{},"VL.VLAnimationClipPlayer"},other{{},"Unknown"};
    std::map<uint32_t,void*> roots;uint32_t next=1;bool source=true,fenced=true,callbacks=true,rebuilt=false,allow=true,wronggraph=false,denied=false;
    MixerOwner owner{};static Fixture* active;
    Fixture(){active=this;owner={other.data,player.data,param.data,{0x1000,2,0},{0x2000,4,0},MixerKind::parameter,0};
        Handle layer{0x3000,6,0};put(param.data,24,layer);void* p=layers.data;put(param.data,40,p);float delay=1.25f;put(param.data,16,delay);param.data[20]=1;
        int32_t index=-1;put(param.data,96,index);int32_t steps=7;put(param.data,64,steps);float time=3.5f;put(param.data,100,time);
        double td=2.5;put(timeline.data,16,td);int32_t inputs=3;put(timeline.data,24,inputs);put(timeline.data,48,inputs);
        Handle native{0x4000,8,0};put(timeline.data,32,native);std::memcpy(fresh.data,timeline.data,sizeof timeline.data);native={0x5000,10,0};put(fresh.data,32,native);}
    template<class T> static void put(void* p,size_t at,T x){std::memcpy(static_cast<uint8_t*>(p)+at,&x,sizeof x);}
    template<class T> static T get(void* p,size_t at){T x{};std::memcpy(&x,static_cast<uint8_t*>(p)+at,sizeof x);return x;}
    Object* object(void* p){for(Object* o:{&param,&timeline,&fresh,&layers,&player,&other})if(o->data==p)return o;return nullptr;}
    static bool mapped(const void* p,size_t n,bool){auto& f=*active;if(f.denied)return false;for(Object* o:{&f.param,&f.timeline,&f.fresh,&f.layers,&f.player,&f.other}){uintptr_t a=reinterpret_cast<uintptr_t>(p),b=reinterpret_cast<uintptr_t>(o->data);if(a>=b&&a-b<=512&&n<=512-(a-b))return true;}return false;}
    static bool type(void* p,const char* t){auto*o=active->object(p);return o&&std::strcmp(o->type,t)==0;}
    static uint32_t retain(void* p){auto& f=*active;f.roots[f.next]=p;return f.next++;}
    static void* target(uint32_t root){auto& f=*active;auto i=f.roots.find(root);return i==f.roots.end()?nullptr:i->second;}
    static void release(uint32_t root){active->roots.erase(root);}
    static size_t length(void* p){assert(p==active->layers.data);return 4;}
    static void* data(void* p){assert(p==active->layers.data);return active->layers.data+32;}
    static bool held(void* context,const MixerOwner&){auto&f=*static_cast<Fixture*>(context);return f.source&&f.fenced;}
    static bool resolve(void* context,const MixerOwner& source,MixerOwner& out){auto&f=*static_cast<Fixture*>(context);if(!f.source)return false;out=source;if(f.rebuilt){out.instance=f.fresh.data;out.playable={0x6000,12,0};}if(f.wronggraph)++out.graph.version;return true;}
    static bool allowed(void* context,const MixerOwner&,const MixerOwner&){return static_cast<Fixture*>(context)->allow;}
    static bool safe(void* context,const MixerOwner&){return static_cast<Fixture*>(context)->callbacks;}
    ManagedMixerApi api(){return{mapped,type,retain,target,release,length,data,held,resolve,allowed,safe};}
    MixerOwner timeline_owner(){auto result=owner;result.instance=timeline.data;result.kind=MixerKind::timeline;result.index=0xfffe;return result;}
};
Fixture* Fixture::active=nullptr;
int main(){unsigned scenarios=0;
    {Fixture f;ManagedMixerSnapshot s;assert(s.capture(f.api(),&f,f.owner)==Result::ok);const Handle layer=Fixture::get<Handle>(f.param.data,24);assert(s.reset()==Result::ok);
        assert(Fixture::get<float>(f.param.data,16)==0&&Fixture::get<int32_t>(f.param.data,64)==0&&Fixture::get<float>(f.param.data,100)==0&&f.param.data[20]==1);
        assert(s.restore()==Result::ok);assert(Fixture::get<float>(f.param.data,16)==1.25f&&Fixture::get<int32_t>(f.param.data,64)==7&&Fixture::get<float>(f.param.data,100)==3.5f);
        assert(Fixture::get<Handle>(f.param.data,24).handle==layer.handle);s.clear();assert(f.roots.empty());++scenarios;}
    for(unsigned failure=0;failure<7;++failure){Fixture f;ManagedMixerSnapshot s;
        switch(failure){case 0:Fixture::put(f.param.data,72,static_cast<void*>(f.other.data));break;case 1:Fixture::put(f.param.data,56,static_cast<void*>(f.other.data));break;
        case 2:f.layers.data[32]=1;break;case 3:f.callbacks=false;break;case 4:f.fenced=false;break;case 5:f.param.type="Unknown";break;case 6:f.denied=true;break;}
        uint8_t before[512];std::memcpy(before,f.param.data,512);assert(s.capture(f.api(),&f,f.owner)!=Result::ok);assert(!s.captured()&&std::memcmp(before,f.param.data,512)==0);s.clear();assert(f.roots.empty());++scenarios;}
    for(unsigned failure=0;failure<7;++failure){Fixture f;ManagedMixerSnapshot s;assert(s.capture(f.api(),&f,f.owner)==Result::ok);assert(s.reset()==Result::ok);
        switch(failure){case 0:f.source=false;break;case 1:f.fenced=false;break;case 2:f.wronggraph=true;break;case 3:f.layers.data[32]=1;break;case 4:f.callbacks=false;break;
        case 5:f.roots[1]=f.other.data;break;case 6:Fixture::put(f.param.data,112,static_cast<void*>(f.other.data));break;}
        uint8_t before[512];std::memcpy(before,f.param.data,512);assert(s.restore()!=Result::ok&&std::memcmp(before,f.param.data,512)==0);++scenarios;}
    {Fixture f;ManagedMixerSnapshot s;auto owner=f.timeline_owner();assert(s.capture(f.api(),&f,owner)==Result::ok);assert(s.reset()==Result::ok&&Fixture::get<double>(f.timeline.data,16)==0);
        f.rebuilt=true;double new_delay=0;Fixture::put(f.fresh.data,16,new_delay);auto fresh_handle=Fixture::get<Handle>(f.fresh.data,32);
        assert(s.restore()==Result::ok&&Fixture::get<double>(f.fresh.data,16)==2.5);assert(Fixture::get<Handle>(f.fresh.data,32).handle==fresh_handle.handle);++scenarios;}
    for(unsigned failure=0;failure<4;++failure){Fixture f;ManagedMixerSnapshot s;auto owner=f.timeline_owner();assert(s.capture(f.api(),&f,owner)==Result::ok);f.rebuilt=true;
        switch(failure){case 0:f.allow=false;break;case 1:Fixture::put(f.fresh.data,24,int32_t{4});break;case 2:Fixture::put(f.fresh.data,48,int32_t{2});break;case 3:f.wronggraph=true;break;}
        uint8_t before[512];std::memcpy(before,f.fresh.data,512);assert(s.restore()!=Result::ok&&std::memcmp(before,f.fresh.data,512)==0);++scenarios;}
    std::printf("%u managed mixer source-history scenarios passed\n",scenarios);
}
