#include "mp4_actor_state.hpp"
#include <array>
#include <cassert>
#include <cstdlib>
#include <cstdio>
#include <cstring>
using namespace idoly_mp4_native_temporal;
struct Fixture {
    alignas(8) std::array<uint8_t,0x80> slot[4]{};
    alignas(8) std::array<uint8_t,0x220> nodes[4]{};
    alignas(8) uintptr_t table[40]{};
    alignas(8) std::array<uint8_t,0x100> root_old{},root_new{};
    static Fixture*active;
    unsigned cleanups=0,prepares=0;int events=0;bool bad_fresh=false,clip_binding_ok=true;
    alignas(8) std::array<uint8_t,0x80> graph_slot{};
    alignas(8) std::array<uint8_t,0xd0> graph_node{};
    alignas(8) uintptr_t type[2]{};
    uint64_t epoch=7,ticket=9;bool fence=true,source=true,inventory=true,profile=true,typed=true,live=true,wronggraph=false,manager=true;
    uintptr_t deny_write=0;bool remap_ok=true,duplicate_remap=false,token_change=false;unsigned leases=0;
    Handle graph{};Layout layouts[5]{};
    Fixture(){
        active=this;
        graph={reinterpret_cast<uintptr_t>(graph_slot.data()),20,0};
        uint32_t gv=20;uintptr_t gn=reinterpret_cast<uintptr_t>(graph_node.data());
        std::memcpy(graph_slot.data()+0x20,&gv,4);std::memcpy(graph_slot.data()+0x28,&gn,8);
        table[0]=reinterpret_cast<uintptr_t>(type);type[1]=reinterpret_cast<uintptr_t>("test_pinned_native_type");
        for(unsigned i=0;i<4;++i){
            const uintptr_t node=reinterpret_cast<uintptr_t>(nodes[i].data());
            const uint32_t version=10+i*2;std::memcpy(slot[i].data()+0x20,&version,4);
            std::memcpy(slot[i].data()+0x28,&node,8);
            for(size_t j=0;j<nodes[i].size();++j)nodes[i][j]=uint8_t((j*17+i*13)&255);
            auto vt=reinterpret_cast<uintptr_t>(table+1);std::memcpy(nodes[i].data(),&vt,8);
            std::memcpy(nodes[i].data()+0x20,&gn,8);
        }
        for(unsigned i=0;i<5;++i)layouts[i]={static_cast<Kind>(i),reinterpret_cast<uintptr_t>(table+1),
            reinterpret_cast<uintptr_t>(type),"test_pinned_native_type",0x220,
            i==3?clip_spans:base_spans,uint8_t(i==3?17:13),0x12345678,true};
    }
    Handle h(unsigned i){return{reinterpret_cast<uintptr_t>(slot[i].data()),10+i*2,0};}
    Input input(unsigned i,Kind k=Kind::mixer){return{h(i),{},k,Lifetime::persistent_exact};}
    static Fixture&f(void*p){return*static_cast<Fixture*>(p);}
    static bool begin(void*p,uint64_t e,Lease&l){auto&a=f(p);if(!a.fence)return false;l={e,a.ticket};++a.leases;return true;}
    static bool held(void*p,const Lease&l){auto&a=f(p);return a.fence&&l.epoch==a.epoch&&l.ticket==a.ticket;}
    static void end(void*p,const Lease&){auto&a=f(p);assert(a.leases);--a.leases;}
    static bool current(void*p,uint64_t e){auto&a=f(p);return a.source&&a.epoch==e;}
    static bool inv(void*p,Handle g,const Input*,size_t){auto&a=f(p);return a.inventory&&same(g,a.graph);}
    bool contains(uintptr_t a,size_t n,const void*base,size_t len){auto b=reinterpret_cast<uintptr_t>(base);return a>=b&&a-b<=len&&n<=len-(a-b);}
    static bool mapped(void*p,uintptr_t a,size_t n,bool write){auto&f=Fixture::f(p);if(write&&a==f.deny_write)return false;
        if(f.contains(a,n,f.root_old.data(),f.root_old.size())||f.contains(a,n,f.root_new.data(),f.root_new.size()))return true;
        if(f.contains(a,n,f.graph_slot.data(),f.graph_slot.size())||f.contains(a,n,f.graph_node.data(),f.graph_node.size()))return true;
        if(f.contains(a,n,f.table,sizeof f.table)||f.contains(a,n,f.type,sizeof f.type)
            ||f.contains(a,n,"test_pinned_native_type",24))return !write;
        for(unsigned i=0;i<4;++i)if(f.contains(a,n,f.slot[i].data(),f.slot[i].size())
            ||f.contains(a,n,f.nodes[i].data(),f.nodes[i].size()))return true;
        return false;
    }
    static bool prof(void*p,const Layout&l){auto&a=f(p);return a.profile&&l.proof_id==0x12345678;}
    static bool validh(void*p,const Handle&h){auto&a=f(p);if(!a.live)return false;for(unsigned i=0;i<4;++i)if(same(a.h(i),h))return true;return false;}
    static bool getgraph(void*p,const Handle&,Handle&g){auto&a=f(p);g=a.graph;if(a.wronggraph)++g.version;return true;}
    static bool graphvalid(void*p,const Handle&g){return same(f(p).graph,g);}
    static bool kind(void*p,const Input&){return f(p).typed;}
    static bool remap(void*p,uint64_t,const Input&old,Input&target){auto&a=f(p);if(!a.remap_ok)return false;target=old;
        target.handle=a.h(a.duplicate_remap?2:(same(old.handle,a.h(0))?2:3));
        if(a.token_change)++target.logical.layer;
        return true;}
    static void cleanup(void*node){auto&a=*active;++a.cleanups;uintptr_t zero=0;
        std::memcpy(static_cast<uint8_t*>(node)+0x138,&zero,8);static_cast<uint8_t*>(node)[0x104]=0;}
    static void prepare(void*node,void*context){auto&a=*active;++a.prepares;
        assert(reinterpret_cast<uintptr_t>(context)==0x200000b0);
        auto n=static_cast<uint8_t*>(node);uintptr_t ptr=reinterpret_cast<uintptr_t>(a.root_new.data());
        std::memcpy(n+0x138,&ptr,8);n[0x104]=a.bad_fresh?0:1;n[0x102]=0;n[0x174]=0;
        std::memset(a.root_new.data(),0xcc,a.root_new.size());}
    static bool binding(void*p,const Input&,uintptr_t,ClipBinding&b){auto&a=f(p);if(!a.clip_binding_ok)return false;
        b={0x20000000,0x98760000,0x200000b0,0x5678,a.events};return true;}
    void enable_clip(unsigned node){auto&l=layouts[3];l.span_count=17;l.clip_cleanup=reinterpret_cast<uintptr_t>(&cleanup);
        l.clip_prepare=reinterpret_cast<uintptr_t>(&prepare);l.normalization_proof=0xabcd;
        table[1+0xd0/8]=l.clip_cleanup;table[1+0xc8/8]=l.clip_prepare;
        uintptr_t asset=0x98760000,root=reinterpret_cast<uintptr_t>(root_old.data());
        std::memcpy(nodes[node].data()+0x1d0,&asset,8);std::memcpy(nodes[node].data()+0x138,&root,8);
        for(size_t i=0;i<root_old.size();++i)root_old[i]=uint8_t(i*7+9);
        for(auto offset:clip_authored_offsets)nodes[node][offset]=0;
        nodes[node][0x174]=1; // Common source after an ordinary full sample.
    }
    static bool quiescent(void*p,const Lease&){return f(p).manager;}
    Api api(){return{this,begin,held,end,current,inv,mapped,prof,validh,getgraph,graphvalid,kind,remap,binding,quiescent};}
    uint64_t scalar(unsigned i,unsigned off){uint64_t v=0;std::memcpy(&v,nodes[i].data()+off,8);return v;}
    void write(unsigned i,unsigned off,uint64_t v){std::memcpy(nodes[i].data()+off,&v,8);}
};
Fixture*Fixture::active=nullptr;
static Logical token(unsigned i){return{0x123400+i,0x456700+i,3,i,0,1};}
namespace actor=idoly_mp4_actor;
static int edges_mode=0,weight_sets=0;static float edge_weights[2]={.25f,0};
static int32_t input_count(actor::Handle* h,void*){auto& f=*Fixture::active;return h->handle==f.h(0).slot||h->handle==f.h(2).slot?(edges_mode==1?1:2):0;}
static void input_get(actor::Handle* h,int32_t index,actor::Handle* out,void*){auto& f=*Fixture::active;*out={};if(index==0){auto target=f.h(h->handle==f.h(0).slot?1:3);*out={target.slot,target.version,0};if(edges_mode==2)out->version+=2;}if(edges_mode==3&&index==1)*out={f.h(3).slot,f.h(3).version,0};}
static float weight_get(actor::Handle*,int32_t i,void*){return edge_weights[i];}
static void weight_set(actor::Handle*,int32_t i,float v,void*){++weight_sets;edge_weights[i]=v;}
static actor::TemporalBinding binding(Fixture& f,bool remap=false){actor::TemporalBinding b{};b.api=f.api();b.layouts=f.layouts;b.layout_count=5;b.node_count=2;b.nodes[0]=f.input(0);b.nodes[1]=f.input(1);b.input_count=input_count;b.input=input_get;b.weight_get=weight_get;b.weight_set=weight_set;
    if(remap)for(unsigned i=0;i<2;++i){b.nodes[i].lifetime=Lifetime::rebuilt_logical;b.nodes[i].logical=token(i);}
    edges_mode=0;weight_sets=0;edge_weights[0]=.25f;edge_weights[1]=0;return b;}
int main(){unsigned scenarios=0;
    {Fixture f;SourceTemporalSnapshot<4>s(f.api(),f.layouts,4);Input x[]={f.input(0),f.input(1)};
        uint64_t graph_counter=123;std::memcpy(f.graph_node.data()+0x20,&graph_counter,8);
        auto a=f.scalar(0,0x60),b=f.scalar(1,0x68);assert(s.capture(7,f.graph,x,2));assert(!s.source_restorable());
        f.write(0,0x60,777);f.write(1,0x68,888);uint64_t advanced=999;std::memcpy(f.graph_node.data()+0x20,&advanced,8);
        assert(s.restore_scalar_component());uint64_t restored=0;std::memcpy(&restored,f.graph_node.data()+0x20,8);assert(restored==123);
        assert(f.scalar(0,0x60)==a&&f.scalar(1,0x68)==b);assert(s.result()==Result::scalar_component_restored);
        auto before=f.nodes;assert(!s.restore_source());assert(s.result()==Result::incomplete_native_sampling_state&&before==f.nodes);assert(f.leases==0);++scenarios;}
    // Every preflight failure leaves all native node bytes unchanged, even when
    // the last node fails after the first node's temporal data was readmitted.
    for(unsigned failure=0;failure<18;++failure){Fixture f;SourceTemporalSnapshot<4>s(f.api(),f.layouts,4);Input x[]={f.input(0),f.input(1)};
        assert(s.capture(7,f.graph,x,2));f.write(0,0x60,123);f.write(1,0x60,456);
        switch(failure){
        case 0:f.fence=false;break;case 1:f.source=false;break;case 2:f.inventory=false;break;case 3:f.profile=false;break;
        case 4:f.typed=false;break;case 5:f.live=false;break;case 6:f.wronggraph=true;break;
        case 7:{uint32_t v=222;std::memcpy(f.slot[1].data()+0x20,&v,4);break;}
        case 8:{auto n=reinterpret_cast<uintptr_t>(f.nodes[2].data());std::memcpy(f.slot[1].data()+0x28,&n,8);break;}
        case 9:{uintptr_t v=1;std::memcpy(f.nodes[1].data(),&v,8);break;}
        case 10:f.table[0]=0;break;
        case 11:f.deny_write=reinterpret_cast<uintptr_t>(f.nodes[1].data()+0xaa);break;
        case 12:++f.epoch;break;
        case 13:{uintptr_t v=0x1234;std::memcpy(f.nodes[1].data()+0x20,&v,8);break;}
        case 14:{uint32_t v=222;std::memcpy(f.graph_slot.data()+0x20,&v,4);break;}
        case 15:{uintptr_t v=reinterpret_cast<uintptr_t>(f.nodes[2].data());std::memcpy(f.graph_slot.data()+0x28,&v,8);break;}
        case 16:f.manager=false;break;
        case 17:f.graph_node[0xc8]=1;break;
        }
        auto before=f.nodes;assert(!s.restore_scalar_component());assert(before==f.nodes&&f.leases==0);++scenarios;
    }
    {Fixture f;SourceTemporalSnapshot<4>s(f.api(),f.layouts,4);Input x[]={f.input(0),f.input(1)};
        for(unsigned i=0;i<2;++i){x[i].lifetime=Lifetime::rebuilt_timeline;x[i].logical=token(i);}
        auto t0=f.scalar(0,0x60),t1=f.scalar(1,0x68);assert(s.capture(7,f.graph,x,2));
        const auto slots=f.slot;const auto originals=f.nodes;
        assert(s.restore_scalar_component());assert(f.scalar(2,0x60)==t0&&f.scalar(3,0x68)==t1);
        assert(f.nodes[0]==originals[0]&&f.nodes[1]==originals[1]&&f.slot==slots&&f.leases==0);++scenarios;
    }
    for(unsigned failure=0;failure<3;++failure){Fixture f;SourceTemporalSnapshot<4>s(f.api(),f.layouts,4);Input x[]={f.input(0),f.input(1)};
        for(unsigned i=0;i<2;++i){x[i].lifetime=Lifetime::rebuilt_timeline;x[i].logical=token(i);}
        assert(s.capture(7,f.graph,x,2));if(failure==0)f.remap_ok=false;if(failure==1)f.token_change=true;if(failure==2)f.duplicate_remap=true;
        auto before=f.nodes;assert(!s.restore_scalar_component());assert(f.nodes==before&&f.leases==0);++scenarios;}
    {Fixture f;SourceTemporalSnapshot<4>s(f.api(),f.layouts,4);Input x[]={f.input(0),f.input(1,Kind::clip)};
        auto before=f.nodes;assert(!s.capture(7,f.graph,x,2));
        assert(s.result()==Result::incomplete_native_sampling_state&&before==f.nodes);++scenarios;}
    {Fixture f;Span fields[]={{0x38,4,0x104},{0x60,8,UINT64_MAX}};f.layouts[1].spans=fields;f.layouts[1].span_count=2;
        SourceTemporalSnapshot<4>s(f.api(),f.layouts,4);Input x[]={f.input(0)};uint32_t expected=0;std::memcpy(&expected,f.nodes[0].data()+0x38,4);
        assert(s.capture(7,f.graph,x,1));uint32_t changed=0xffffffffu;std::memcpy(f.nodes[0].data()+0x38,&changed,4);
        assert(s.restore_scalar_component());uint32_t actual=0;std::memcpy(&actual,f.nodes[0].data()+0x38,4);
        assert(actual==((changed&~0x104u)|(expected&0x104u)));++scenarios;}
    {Fixture f;f.enable_clip(1);SourceTemporalSnapshot<4>s(f.api(),f.layouts,4);Input x[]={f.input(0),f.input(1,Kind::clip)};
        const auto root=f.root_old;const auto temporal=f.scalar(1,0x178);assert(s.capture(7,f.graph,x,2));
        f.write(1,0x178,999);f.nodes[1][0x174]=1;
        assert(s.restore_scalar_component());assert(f.cleanups==1&&f.prepares==1&&f.nodes[1][0x174]==0);
        assert(f.scalar(1,0x178)==temporal);
        // Derived RootMath is not copied. Original prepare's fresh buffer is
        // left for the original full sampler, never marked as old valid data.
        assert(f.root_new[0]==0xcc&&f.root_new[0xf2]==0xcc);assert(f.root_old==root);assert(!s.source_restorable());++scenarios;}
    for(unsigned failure=0;failure<4;++failure){Fixture f;f.enable_clip(1);SourceTemporalSnapshot<4>s(f.api(),f.layouts,4);Input x[]={f.input(0),f.input(1,Kind::clip)};
        assert(s.capture(7,f.graph,x,2));if(failure==0)f.events=1;if(failure==1)f.clip_binding_ok=false;
        if(failure==2){uintptr_t asset=44;std::memcpy(f.nodes[1].data()+0x1d0,&asset,8);}
        if(failure==3)f.nodes[1][0x1f6]=1;
        auto before=f.nodes;assert(!s.restore_scalar_component());assert(f.cleanups==0&&before==f.nodes);++scenarios;}
    {Fixture f;actor::GraphTemporalScope s;auto b=binding(f);const auto saved=f.scalar(0,0x60);assert(s.capture(b,7,{f.graph.slot,f.graph.version,0},64*1024*1024)==actor::Result::ok);f.write(0,0x60,5678);edge_weights[0]=.875f;assert(s.restore()==actor::Result::ok);assert(f.scalar(0,0x60)==saved&&edge_weights[0]==.25f&&weight_sets==2&&f.leases==0);assert(s.component_closed());assert(s.restore()==actor::Result::ok&&weight_sets==2);++scenarios;}
    for(unsigned failure=0;failure<8;++failure){Fixture f;actor::GraphTemporalScope s;auto b=binding(f);assert(s.capture(b,7,{f.graph.slot,f.graph.version,0},64*1024*1024)==actor::Result::ok);f.write(0,0x60,5678);edge_weights[0]=.875f;
        switch(failure){case 0:edges_mode=1;break;case 1:edges_mode=2;break;case 2:edges_mode=3;break;case 3:f.source=false;break;case 4:f.manager=false;break;case 5:f.fence=false;break;case 6:f.inventory=false;break;case 7:f.deny_write=reinterpret_cast<uintptr_t>(f.nodes[1].data()+0xaa);break;}
        auto before=f.nodes;assert(s.restore()!=actor::Result::ok);assert(before==f.nodes&&weight_sets==0&&edge_weights[0]==.875f&&f.leases==0);++scenarios;}
    {Fixture f;actor::GraphTemporalScope s;auto b=binding(f,true);auto saved=f.scalar(0,0x60);const auto original=f.nodes[0];assert(s.capture(b,7,{f.graph.slot,f.graph.version,0},64*1024*1024)==actor::Result::ok);assert(s.restore()==actor::Result::ok);assert(f.scalar(2,0x60)==saved&&f.nodes[0]==original&&weight_sets==2);++scenarios;}
    {Fixture f;actor::GraphTemporalScope s;auto b=binding(f);assert(s.capture(b,7,{f.graph.slot,f.graph.version,0},64)==actor::Result::unsupported);assert(weight_sets==0&&!s.captured());++scenarios;}
    {Fixture f;actor::GraphTemporalScope s;auto b=binding(f);edges_mode=3;assert(s.capture(b,7,{f.graph.slot,f.graph.version,0},64*1024*1024)==actor::Result::unsupported);assert(weight_sets==0&&!s.captured());++scenarios;}
    std::printf("%u temporal checkpoint scenarios passed; full source restore remains unclaimed\n",scenarios);
}
