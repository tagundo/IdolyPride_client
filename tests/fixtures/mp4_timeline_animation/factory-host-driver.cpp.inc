struct Object{alignas(16)uint8_t bytes[320]{};alignas(16)uint8_t native[32]{};Object(uintptr_t klass,int32_t id){model.ranges.push_back({reinterpret_cast<uintptr_t>(bytes),sizeof bytes});model.ranges.push_back({reinterpret_cast<uintptr_t>(native),sizeof native});model.classes[bytes]=klass;auto p=reinterpret_cast<uintptr_t>(native);std::memcpy(bytes+16,&p,8);std::memcpy(native+8,&id,4);}void*get(){return bytes;}};
int main(int argc,char**argv){assert(argc==2);std::string c=argv[1];
 image_base=0;mp4_animation_factory_source.events.rva=reinterpret_cast<uintptr_t>(get_events);mp4_animation_factory_source.legacy.rva=reinterpret_cast<uintptr_t>(get_legacy);mp4_animation_factory_source.human.rva=reinterpret_cast<uintptr_t>(get_human);
 Object root(mp4_animation_factory_source.track.binding.rva,1),child(mp4_animation_factory_source.track.binding.rva,2),clip(mp4_animation_factory_source.clip.binding.rva,3),go(6,4);model.classes[events_object]=7;
 void*r=root.get();std::memcpy(child.bytes+64,&r,8);
 using namespace mp4_animation_factory;
 if(c=="static_callback"||c=="static_missing"){model.static_callback=c=="static_callback";model.static_missing=c=="static_missing";assert(!mp4_animation_factory_bindings(nullptr));return 0;}Input i{};i.graph={0x2000,2,0};i.self=i.track=reinterpret_cast<uintptr_t>(root.get());i.game_object=reinterpret_cast<uintptr_t>(go.get());i.tree=0x6000;i.return_pc=0x7000;
 model.source.ticket={11,12,1};model.source.input={0x1100,i.game_object,0x1200,0x1300,{0x2000,2,0}};model.source.image={0x3000,2};
 model.child.input={0x1100,i.game_object,{0x2000,2,0}};model.child.birth={21,22,{0x3000,2}};
 Origin o{};Image image{};Handle top{};
 if(c=="origin_ordinary"){assert(mp4_animation_factory_origin(nullptr,i,&o)&&!o.private_factory&&o.serial==11);assert(mp4_animation_factory_settled(nullptr,o,i.graph,&top)&&top.handle==0xa000);return 0;}
 if(c=="origin_private"){model.ordinary=false;model.private_context=true;assert(mp4_animation_factory_origin(nullptr,i,&o)&&o.private_factory&&o.serial==21);assert(mp4_animation_factory_settled(nullptr,o,i.graph,&top)&&top.handle==0xb000);return 0;}
 if(c=="origin_none"){model.ordinary=false;assert(!mp4_animation_factory_origin(nullptr,i,&o));return 0;}
 if(c=="origin_foreign_go"){i.game_object++;assert(!mp4_animation_factory_origin(nullptr,i,&o));return 0;}
 if(c=="unsettled"){assert(mp4_animation_factory_origin(nullptr,i,&o));model.settled=false;assert(!mp4_animation_factory_settled(nullptr,o,i.graph,&top));return 0;}
 if(c=="wrong_settle_identity"){assert(mp4_animation_factory_origin(nullptr,i,&o));o.graph_native++;assert(!mp4_animation_factory_settled(nullptr,o,i.graph,&top));return 0;}
 if(c=="inspect_track"){assert(mp4_animation_factory_inspect(nullptr,i,&image)&&image.bytes==128);return 0;}
 if(c=="inspect_child"){i.track=reinterpret_cast<uintptr_t>(child.get());assert(mp4_animation_factory_inspect(nullptr,i,&image)&&image.bytes==256);return 0;}
 if(c=="inspect_wrong_type"){i.self=reinterpret_cast<uintptr_t>(go.get());assert(!mp4_animation_factory_inspect(nullptr,i,&image));return 0;}
 if(c=="inspect_offset"){model.broken_offset=256;assert(!mp4_animation_factory_inspect(nullptr,i,&image));return 0;}
 if(c=="inspect_dead"){model.stale=true;assert(!mp4_animation_factory_inspect(nullptr,i,&image));return 0;}
 if(c=="inspect_clip"||c=="events"||c=="legacy"||c=="human"||c=="nonfinite"||c=="mode"||c=="loop"){
 i.kind=Kind::clip;i.self=0;i.clip=reinterpret_cast<uintptr_t>(clip.get());
 if(c=="events")model.events=1;if(c=="legacy")model.legacy=true;if(c=="human")model.human=true;if(c=="nonfinite")i.euler.x=INFINITY;if(c=="mode")i.mode=7;if(c=="loop")i.loop=3;
 assert(mp4_animation_factory_inspect(nullptr,i,&image)==(c=="inspect_clip"));assert(model.roots.empty());return 0;}
 Input nested=i;nested.kind=Kind::clips;nested.track=reinterpret_cast<uintptr_t>(child.get());nested.return_pc=mp4_animation_factory_source.clips_call;
 if(c=="nested_child"){assert(mp4_animation_factory_nested(nullptr,i,i,nested));return 0;}
 if(c=="nested_wrong_caller"){nested.return_pc++;assert(!mp4_animation_factory_nested(nullptr,i,i,nested));return 0;}
 if(c=="nested_cycle"){void*p=child.get();std::memcpy(child.bytes+64,&p,8);assert(!mp4_animation_factory_nested(nullptr,i,i,nested));return 0;}
 if(c=="clip_nested"||c=="clip_wrong_caller"||c=="clip_wrong_mode"){
 Input leaf=nested;leaf.kind=Kind::clip;leaf.self=0;leaf.clip=reinterpret_cast<uintptr_t>(clip.get());leaf.return_pc=mp4_animation_factory_source.clip_from_clips;
 if(c=="clip_wrong_caller")leaf.return_pc++;if(c=="clip_wrong_mode")leaf.mode=1;
 assert(mp4_animation_factory_nested(nullptr,i,nested,leaf)==(c=="clip_nested"));return 0;}
 if(c=="returned"){assert(mp4_animation_factory_returned(nullptr,i,{8,2,0}));return 0;}
 if(c=="returned_foreign"){i.graph.handle++;assert(!mp4_animation_factory_returned(nullptr,i,{8,2,0}));return 0;}
 if(c=="configured"){assert(mp4_animation_factory_configure());assert(mp4_animation_factories.clear());return 0;}
 assert(false);
}
