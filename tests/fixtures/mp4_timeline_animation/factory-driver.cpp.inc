using namespace mp4_animation_factory;
struct Model {bool thread=true,pins=true,origin=true,inspect=true,nest=true,returned=true,settled=true,private_factory=false;unsigned mutate=0;size_t roots=0,releases=0;uint32_t seq=0;std::map<uint32_t,void*>refs;Journal*j=nullptr;bool reenter=false;};
Model model;
bool thread(void*p){return static_cast<Model*>(p)->thread;}bool pins(void*p){return static_cast<Model*>(p)->pins;}
bool origin(void*p,const Input&i,Origin*out){auto&m=*static_cast<Model*>(p);if(!m.origin)return false;*out={55,6,0x1000,i.game_object,0x3000,i.graph.version&~uint32_t(1),1,m.private_factory};return true;}
bool inspect(void*p,const Input&i,Image*out){auto&m=*static_cast<Model*>(p);if(!m.inspect)return false;*out={};out->owner_class=0x20;out->owner_native=i.self+8;out->owner_id=22;out->clip_native=i.clip?i.clip+8:0;out->clip_id=i.clip?33:0;out->bytes=4;std::memcpy(out->authored,&m.mutate,4);if(m.reenter){Input q=i;Ticket t;assert(!m.j->begin(q,&t));}return true;}
bool nested(void*p,const Input&,const Input&,const Input&){return static_cast<Model*>(p)->nest;}
bool returned(void*p,const Input&i,Handle h){return static_cast<Model*>(p)->returned&&h.handle&&i.graph.handle==0x2000;}
bool settled(void*p,const Origin&,Handle,Handle*out){*out={0xabcdef,2,0};return static_cast<Model*>(p)->settled;}
uint32_t retain(void*p){auto h=++model.seq;model.refs[h]=p;++model.roots;return h;}void*target(uint32_t h){auto at=model.refs.find(h);return at==model.refs.end()?nullptr:at->second;}void release(uint32_t h){assert(model.refs.erase(h)==1);++model.releases;}
Input base(){Input i{};i.graph={0x2000,2,0};i.self=i.track=0x4000;i.game_object=0x5000;i.tree=0x6000;i.method=0x7000;i.return_pc=0x8000;return i;}
int main(int argc,char**argv){assert(argc==2);std::string c=argv[1];Journal j;model.j=&j;Api a{&model,thread,pins,origin,inspect,nested,returned,settled,retain,target,release};
 if(c=="configure_missing"){a.origin=nullptr;assert(!j.configure(a));return 0;}
 assert(j.configure(a));Input root=base();Ticket tr{},tc{},tl{};Receipt out{};struct Finish{Journal&j;Ticket&r,&c,&l;~Finish(){if(l.serial)(void)j.end(l,{},false);if(c.serial)(void)j.end(c,{},false);if(r.serial)(void)j.end(r,{},false);(void)j.clear();}}finish{j,tr,tc,tl};
 if(c=="offthread"){model.thread=false;assert(!j.begin(root,&tr));model.thread=true;assert(j.begin(root,&tr));assert(j.end(tr,{9,2,0},true));assert(j.receipt(tr,&out));return 0;}
 if(c=="pins"){model.pins=false;assert(!j.begin(root,&tr));return 0;}
 if(c=="origin"){model.origin=false;assert(!j.begin(root,&tr));return 0;}
 if(c=="inspect"){model.inspect=false;assert(!j.begin(root,&tr));assert(model.roots==model.releases);return 0;}
 if(c=="missing_method")root.method=0;
 if(c=="missing_caller"){root.return_pc=0;assert(!j.begin(root,&tr));return 0;}
 if(c=="missing_tree"){root.tree=0;assert(!j.begin(root,&tr));return 0;}
 if(c=="wrong_root_track"){root.track++;assert(!j.begin(root,&tr));return 0;}
 if(c=="private_origin")model.private_factory=true;
 if(c=="provider_reentry")model.reenter=true;
 assert(j.begin(root,&tr));Input current{};assert(j.context(&current)&&current.self==root.self);
 if(c=="root_reentry"){Ticket t;assert(!j.begin(root,&t));assert(j.end(tr,{9,2,0},true));assert(j.receipt(tr,&out));return 0;}
 if(c=="active_receipt"){assert(!j.receipt(tr,&out));return 0;}
 Input clips=root;clips.kind=Kind::clips;clips.track=0x4100;clips.mode=1;
 if(c=="wrong_graph")clips.graph.handle++;
 if(c=="wrong_go")clips.game_object++;
 if(c=="wrong_tree")clips.tree++;
 if(c=="wrong_owner")clips.self++;
 if(c=="nested")model.nest=false;
 if(c=="wrong_graph"||c=="wrong_go"||c=="wrong_tree"||c=="wrong_owner"||c=="nested"){assert(!j.begin(clips,&tc));assert(j.end(tr,{9,2,0},true));return 0;}
 if(c=="infinite"){clips.kind=Kind::infinite;clips.self=clips.track;}
 assert(j.begin(clips,&tc));Input leaf=clips;leaf.kind=Kind::clip;leaf.self=0;leaf.clip=0x9000;leaf.position={0,0,0};leaf.euler={0,0,0};leaf.remove_start=true;leaf.foot_ik=true;
 if(c=="leaf_track")leaf.track++;
 if(c=="leaf_self")leaf.self=0x4400;
 if(c=="leaf_null")leaf.clip=0;
 if(c=="leaf_track"||c=="leaf_self"||c=="leaf_null"){assert(!j.begin(leaf,&tl));return 0;}
 assert(j.begin(leaf,&tl));
 if(c=="bad_end_order"){assert(!j.end(tc,{10,2,0},true));assert(!j.receipt(tr,&out));return 0;}
 if(c=="source_changed")model.mutate=1;
 if(c=="original_threw"){assert(!j.end(tl,{},false));assert(!j.end(tc,{10,2,0},true));assert(!j.end(tr,{9,2,0},true));assert(!j.receipt(tl,&out));assert(!j.receipt(tc,&out));return 0;}
 if(c=="invalid_return"){assert(!j.end(tl,{},true));return 0;}
 if(c=="source_changed"){assert(!j.end(tl,{11,2,0},true));return 0;}
 assert(j.end(tl,{11,2,0},true));
 if(c=="construction"||c=="construction_parent"||c=="construction_version"||c=="construction_stale"){
  Ticket active{};assert(j.active_ticket(&active)&&active.serial==tc.serial);if(c=="construction_stale")j.invalidate();
  const bool expected=c=="construction";assert(j.construction_child(c=="construction_parent"?tr:tc,{11,c=="construction_version"?4u:2u,0},&out)==expected);
  if(expected){assert(out.ticket.serial==tl.serial&&!out.source_root.handle);assert(!j.receipt(tl,&out));}return 0;}
 assert(j.end(tc,{10,2,0},true));assert(j.end(tr,{9,2,0},true));
 if(c=="unsettled")model.settled=false;
 if(c=="returned_changed")model.returned=false;
 if(c=="after_changed")model.mutate=2;
 if(c=="lost_root")model.refs.clear();
 if(c=="invalidated")j.invalidate();
 const bool good=c!="unsettled"&&c!="returned_changed"&&c!="after_changed"&&c!="lost_root"&&c!="invalidated";
 assert(j.receipt(tl,&out)==good);
 if(c=="lost_root"){model.refs.clear();return 0;}
 if(good){assert(out.input.clip==leaf.clip&&out.ticket.root==tr.serial);assert(out.origin.private_factory==model.private_factory);assert(j.count()==3);}
 if(c=="collect"||c=="collect_capacity"){Receipt rows[4]{};size_t number=0;const bool ok=j.collect(root.graph,root.track,rows,c=="collect"?4:2,&number);assert(ok==(c=="collect"));if(ok){assert(number==3&&rows[0].input.kind==Kind::root&&rows[1].input.kind==Kind::clips&&rows[2].input.kind==Kind::clip&&rows[0].source_root.handle==0xabcdef);}}
 if(c=="superseded"){Ticket t;assert(j.begin(root,&t));assert(j.end(t,{12,2,0},true));assert(!j.receipt(tl,&out));}
 return 0;
}
