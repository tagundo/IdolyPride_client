int main(int argc,char**argv){assert(argc==2);model.mode=atoi(argv[1]);
 model.list=model.list_image;model.controller=&model.list;model.player=&model.controller;
 model.witness={model.player,model.roots[0].director,model.roots[1].director,1};
 model.roster[0]=model.roots[1].director;model.roster[1]=model.roots[1].director;uint32_t version=1;std::memcpy(model.list_image+28,&version,4);
 mp4_actor_profile.get_game_object.rva=(uintptr_t)get_go-image_base;
 for(unsigned i=0;i<2;++i){auto&r=model.roots[i];r.root={0x30000+i*0x1000,2,0};r.leaf={r.root.handle+0x100,2,0};r.method=image_base+mp4_child_birth_pins.factory;
  uintptr_t klass=(uintptr_t)r.klass,method=(uintptr_t)&r.method,native=(uintptr_t)r.native,target=r.method;
  std::memcpy(r.asset,&klass,8);std::memcpy(r.klass+0x198,&target,8);std::memcpy(r.klass+0x1a0,&method,8);std::memcpy(r.director+16,&native,8);
  mp4actor::Handle graph{(uintptr_t)r.graph,2,0};std::memcpy(r.native+0x88,&graph,16);std::memcpy(r.native+0x98,&r.root,16);
  auto&v=r.receipt;v.source.ticket={i+1,1,1};v.source.input={(uintptr_t)r.asset,(uintptr_t)r.go,method,image_base+mp4_child_birth_pins.internal_return,{(uintptr_t)r.graph,2,0}};
  v.source.image.asset={(uintptr_t)r.asset,klass,0x10000+i,1};v.source.image.game_object={(uintptr_t)r.go,0x100,0x20000+i,2};v.source.image.graph_native=(uintptr_t)r.graph_native;v.source.image.graph_version=2;v.root={r.root.handle,2,0};
 }
 if(model.mode==1)model.owner=false;if(model.mode==2)mp4_scene_host.active=true;if(model.mode==3)model.phase=false;if(model.mode==4)model.hooks=false;if(model.mode==5)model.pins=false;if(model.mode==6)mp4_raw_original_operation.depth=1;
 if(model.mode==7)model.controller=nullptr;
 if(model.mode==22){uintptr_t zero=0;std::memcpy(model.roots[1].native+0x88,&zero,8);}if(model.mode==23){uintptr_t zero=0;std::memcpy(model.roots[1].native+0x98,&zero,8);}
 if(model.mode==24)++model.roots[1].receipt.source.image.asset.klass;if(model.mode==25)++model.roots[1].receipt.source.image.graph_native;if(model.mode==26)++model.roots[1].receipt.source.image.graph_version;
 if(model.mode==33){model.bootstrap=true;mp4_scene_host.active=true;}
 const bool good=mp4_source_director_plan_build(model.witness);
 const bool expected=model.mode==0||model.mode==10||model.mode>=27;assert(good==expected);
 if(good){if(model.mode==33)assert(mp4_source_director_plans.phase==Mp4TimelineProofPhase::source_bootstrap_plan);assert(mp4_source_director_plans.count==2&&mp4_source_director_plan_current());
  if(model.mode==27){const auto roots=model.gc.size();mp4_source_director_plan_withdraw();assert(model.gc.size()==roots&&!mp4_source_director_plan_current());}
  if(model.mode==28){++version;std::memcpy(model.list_image+28,&version,4);assert(!mp4_source_director_plan_current());}
  if(model.mode==29){model.lists=false;assert(!mp4_source_director_plan_current());}
  if(model.mode==30){const auto roots=model.gc.size();mp4_source_director_plans.readers=1;assert(!mp4_source_director_plan_drop()&&model.gc.size()==roots);mp4_source_director_plans.readers=0;}
  if(model.mode==34){const auto roots=model.gc.size();model.owner=false;assert(!mp4_source_director_plan_current()&&model.gc.size()==roots);model.owner=true;}
  if(model.mode==31){const auto roots=model.gc.size();model.owner=false;mp4_source_director_plan_withdraw();assert(model.gc.size()==roots&&!mp4_source_director_plan_drop());}
  if(model.mode==32){mp4_source_director_plans.readers=1;mp4_source_director_plan_withdraw();const auto roots=model.gc.size();assert(!mp4_source_director_plan_build(model.witness)&&model.gc.size()==roots);mp4_source_director_plans.readers=0;}
 }
 model.owner=true;mp4_raw_original_operation.depth=0;assert(mp4_source_director_plan_drop()&&model.gc.empty());
}
