int main(int argc,char**argv){assert(argc==2);model.mode=atoi(argv[1]);
 bind(strong,pin::font_strong);bind(target,pin::weak_get);bind(release,pin::weak_free);bind(alive,pin::object_alive);bind(klass,pin::object_class);bind(name,pin::class_name);bind(space,pin::class_namespace);
 bind(main_thread,mp4_shader_lineage_pins.main_thread);bind(instance_id,mp4_shader_lineage_pins.instance_id);bind(graph_valid,mp4_profile.graph_valid);bind(playable_valid,mp4_actor_profile.playable_valid);bind(playable_graph,mp4_actor_profile.playable_graph_get);
 model.asset={&model.klass,0,(uintptr_t)&model.assetNative,1,"UnityEngine.Timeline.TimelineAsset"};model.go={&model.goClass,0,(uintptr_t)&model.goNative,2,"UnityEngine.GameObject"};
 model.graph.native=(uintptr_t)&model.graphNative;model.graphNative.back=(uintptr_t)&model.graph;model.node.native=(uintptr_t)&model.nodeNative;
 mp4_child_birth_pins.factory=0x1000;model.method=(uintptr_t)&model.method_storage;const uintptr_t entry=image_base+mp4_child_birth_pins.factory;std::memcpy(&model.method_storage,&entry,8);std::memcpy(model.klass.b+0x198,&entry,8);const uintptr_t mi=model.method;std::memcpy(model.klass.b+0x1a0,&mi,8);
 alignas(8)uint8_t internal[8]={1,2,3,4,5,6,7,8};mp4_child_birth_pins.internal_return=(uintptr_t)internal+8-image_base;std::memcpy(mp4_child_birth_pins.internal_call,internal,8);
 uintptr_t caller=(uintptr_t)internal+8;void*method=(void*)mi;Graph graph{(uintptr_t)&model.graph,2,0};
 if(model.mode==1)model.main=false;if(model.mode==2)model.gateway=false;if(model.mode==3)mp4_native_clock_source_ready=false;if(model.mode==4)model.refresh=false;if(model.mode==5)mp4_raw_original_operation.depth=1;
 if(model.mode==6)++caller;if(model.mode==7)method=(uint8_t*)method+1;if(model.mode==8)model.asset.type="Wrong";if(model.mode==9)model.go.type="Wrong";if(model.mode==10)model.alive=false;
 if(model.mode==11)model.asset.id=0;if(model.mode==12)model.graph.version=4;if(model.mode==13)model.graphNative.back=0;if(model.mode==14)model.graph.native=0;
 if(model.mode==15)mp4_shader_lineage_pins.instance_id.prefix[0]^=1;if(model.mode==16)pin::font_strong.bytes[0]^=1;
 if(model.mode==17){uintptr_t wrong=entry+4;std::memcpy(model.klass.b+0x198,&wrong,8);}if(model.mode==18)model.asset.native=0;if(model.mode==19)model.method_storage=entry+4;
 if(model.mode==20)model.wrongGraph=true;if(model.mode==21)model.node.version=4;if(model.mode==22)model.throw_original=true;
 bool caught=false;Playable root{};try{root=mp4_source_factory_observe(&model.asset,graph,&model.go,method,caller);}catch(int x){caught=x==42;}
 if(model.mode==24)foreign_observe();assert(model.calls==(model.mode>=23?2u:1u)&&caught==(model.mode==22));if(model.mode==1)assert(!model.established&&model.establishes==0);
 if(model.mode>=23)assert(model.foreign_calls==1);model.mode=0;if(caught){assert(mp4_source_factory_clear());return 0;}
 mp4_director_birth::SourceTuple tuple{0x777,(uintptr_t)&model.asset,(uintptr_t)&model.go,(uintptr_t)&model.klass,mi,1,1};mp4_source_factory::Receipt sealed{};
 if(atoi(argv[1])==0||atoi(argv[1])==23){assert(mp4_source_factory_seal(tuple,graph,root,&sealed));auto bad=tuple;++bad.method;assert(!mp4_source_factory_seal(bad,graph,root,&sealed));mp4_source_factory_invalidate();assert(!mp4_source_factory_seal(tuple,graph,root,&sealed));}
 else assert(!mp4_source_factory_seal(tuple,graph,root,&sealed));
 model.main=true;model.refresh=true;mp4_raw_original_operation.depth=0;mp4_source_factory_invalidate();if(mp4_source_factory_configured)assert(mp4_source_factory_clear());assert(model.roots.empty());
}
