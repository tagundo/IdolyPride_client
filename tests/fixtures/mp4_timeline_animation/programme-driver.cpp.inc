using namespace mp4_animation_programme;
struct Model{std::map<uintptr_t,Node>nodes;bool current=true,track=true,clip=true;int reads=0;};
bool current(void*p,const Receipt&){return static_cast<Model*>(p)->current;}bool track(void*p,uintptr_t r,uintptr_t t){return static_cast<Model*>(p)->track&&r==100&&t==100;}bool clip(void*p,const Receipt&,const Receipt&,const Receipt&c){return static_cast<Model*>(p)->clip&&c.input.clip==200;}
bool read(void*p,Handle h,Node*out){auto&m=*static_cast<Model*>(p);++m.reads;auto i=m.nodes.find(h.handle);if(i==m.nodes.end()||i->second.handle.version!=h.version)return false;*out=i->second;return true;}
struct Fixture{Model model;Receipt rows[3]{};Api api{};Plan plan{};Fixture(bool offset=false){
 using K=mp4_animation_factory::Kind;auto origin=mp4_animation_factory::Origin{5,7,500,600,700,2,1,false};
 for(size_t i=0;i<3;++i){auto&r=rows[i];r.origin=origin;r.source_root={99,2,0};r.ticket={i+1,7,1,uint8_t(i+1)};r.input.graph={10,2,0};r.input.game_object=600;r.input.tree=800;r.input.track=100;}
 rows[0].input.kind=K::root;rows[0].input.self=100;rows[0].returned={offset?45u:40u,2,0};
 rows[1].input.kind=K::clips;rows[1].input.self=100;rows[1].returned={offset?25u:20u,2,0};rows[1].input.mode=offset?1:0;
 rows[2].input.kind=K::clip;rows[2].input.clip=200;rows[2].input.mode=offset?1:0;rows[2].input.foot_ik=true;rows[2].image.clip_native=2000;rows[2].returned={offset?35u:30u,2,0};
 Node c{};c.handle={30,2,0};c.kind=NativeKind::clip;c.native=3000;c.asset_native=2000;c.clip_flags[1]=1;model.nodes[30]=c;
 Node mix{};mix.handle={20,2,0};mix.kind=NativeKind::mixer;mix.native=2000;mix.count=1;mix.inputs[0]=rows[2].returned;model.nodes[20]=mix;
 Node layer{};layer.handle={40,2,0};layer.kind=NativeKind::layer;layer.native=4000;layer.count=1;layer.inputs[0]=rows[1].returned;model.nodes[40]=layer;
 if(offset){for(uintptr_t n:{uintptr_t(25),uintptr_t(35)}){Node o{};o.handle={n,2,0};o.kind=NativeKind::offset;o.native=n*100;o.count=1;o.inputs[0]={n==25?20u:30u,2,0};o.rotation[3]=1;model.nodes[n]=o;}Node motion{};motion.handle={45,2,0};motion.kind=NativeKind::motion;motion.native=4500;motion.count=1;motion.inputs[0]=layer.handle;motion.absolute=1;model.nodes[45]=motion;}
 api={&model,current,track,clip,read};}bool build(){return mp4_animation_programme::build(api,rows,3,&plan);}};
int main(){int tests=0;
 {Fixture f;assert(f.build());assert(f.plan.node_count==3&&f.plan.clip_count==1&&f.plan.group_count==1);assert(runtime(f.plan,100,200,{30,2,0},{20,2,0},false));assert(!runtime(f.plan,100,201,{30,2,0},{20,2,0},false));assert(!runtime(f.plan,100,200,{30,2,0},{40,2,0},false));assert(contains(f.plan,{30,2,0})&&!contains(f.plan,{30,4,0}));++tests;}
 {Fixture f(true);assert(f.build());assert(f.plan.node_count==6);assert(runtime(f.plan,100,200,{35,2,0},{20,2,0},false));assert(!runtime(f.plan,100,200,{30,2,0},{20,2,0},false));++tests;}
 {Fixture f;f.rows[1].input.kind=mp4_animation_factory::Kind::infinite;assert(f.build());assert(runtime(f.plan,0,0,{30,2,0},{},true));++tests;}
 {Fixture f;f.api.current=nullptr;assert(!f.build());++tests;}
 {Fixture f;f.model.current=false;assert(!f.build());assert(!f.model.reads);++tests;}
 {Fixture f;f.model.track=false;assert(!f.build());++tests;}
 {Fixture f;f.model.clip=false;assert(!f.build());++tests;}
 {Fixture f;f.rows[1].origin.private_factory=true;assert(!f.build());++tests;}
 {Fixture f;f.rows[1].input.graph.version=4;assert(!f.build());++tests;}
 {Fixture f;f.rows[1].source_root.version=4;assert(!f.build());++tests;}
 {Fixture f;f.rows[1].ticket.serial=1;assert(!f.build());++tests;}
 {Fixture f;f.rows[2].ticket.root=9;assert(!f.build());++tests;}
 {Fixture f;f.rows[2].ticket.depth=2;assert(!f.build());++tests;}
 {Fixture f;f.rows[1].input.mode=3;assert(!f.build());++tests;}
 {Fixture f;f.rows[2].input.mode=1;assert(!f.build());++tests;}
 {Fixture f;f.rows[2].input.loop=1;assert(!f.build());++tests;}
 {Fixture f;f.rows[2].input.foot_ik=false;assert(!f.build());++tests;}
 {Fixture f;f.rows[2].input.position.x=1;assert(!f.build());++tests;}
 {Fixture f;f.rows[2].input.euler.y=1;assert(!f.build());++tests;}
 {Fixture f;f.model.nodes[30].asset_native=2001;assert(!f.build());++tests;}
 for(size_t i=0;i<5;++i){Fixture f;f.model.nodes[30].clip_flags[i]^=1;assert(!f.build());++tests;}
 {Fixture f;f.model.nodes[20].inputs[0]={40,2,0};assert(!f.build());++tests;}
 {Fixture f;f.model.nodes[40].inputs[0]={30,2,0};assert(!f.build());++tests;}
 {Fixture f;f.model.nodes[20].count=2;assert(!f.build());++tests;}
 {Fixture f;f.model.nodes[40].count=0;assert(!f.build());++tests;}
 {Fixture f;f.model.nodes[30].count=1;assert(!f.build());++tests;}
 {Fixture f(true);f.model.nodes[25].rotation[3]=0;assert(!f.build());++tests;}
 {Fixture f(true);f.model.nodes[35].position[2]=.01f;assert(!f.build());++tests;}
 {Fixture f(true);f.model.nodes[45].absolute=0;assert(!f.build());++tests;}
 {Fixture f(true);f.model.nodes[45].count=2;assert(!f.build());++tests;}
 {Fixture f(true);f.rows[1].input.mode=0;f.rows[2].input.mode=0;assert(!f.build());++tests;}
 {Fixture f;f.rows[2].returned.version=4;assert(!f.build());++tests;}
 {Fixture f;assert(!mp4_animation_programme::build(f.api,f.rows,0,&f.plan));++tests;}
 {Fixture f;assert(!mp4_animation_programme::build(f.api,f.rows,2,&f.plan));++tests;}
 assert(tests==38);
}
