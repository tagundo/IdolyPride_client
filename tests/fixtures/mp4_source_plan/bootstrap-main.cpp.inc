 mp4_scene_host.source=model.witness;mp4_profile.director_get_asset.rva=(uintptr_t)get_asset-image_base;mp4_profile.director_graph_injected.rva=(uintptr_t)get_graph-image_base;
 for(auto&r:model.roots){uint32_t v=2;uintptr_t native=(uintptr_t)r.graph_native,slot=(uintptr_t)r.graph;std::memcpy(r.graph+0x20,&v,4);std::memcpy(r.graph+0x28,&native,8);std::memcpy(r.graph_native+16,&slot,8);}
 if(model.mode==1)model.owner=false;if(model.mode==2)mp4_scene_host.active=false;if(model.mode==3)mp4_scene_host.invalidated=true;if(model.mode==4)mp4_scene_host.releasing=true;if(model.mode==5)mp4_scene_host.configured=3;
 if(model.mode==6)mp4_raw_original_operation.depth=1;if(model.mode==7)mp4_rebuild_ledger.active=true;if(model.mode==8)model.roster[0]=model.roots[0].director;
 if(model.mode==9)model.controller=nullptr;if(model.mode==10)held=false;if(model.mode==11)acquiring=false;if(model.mode==12)model.phase=false;
 if(model.mode==13)mp4_root_history_initial_seal={1,2};if(model.mode==14)mp4_source_factory_configured=false;if(model.mode==15)model.pins=false;if(model.mode==16)++mp4_profile.director_get_asset.rva;
 if(model.mode==17)mp4_scene_host.source.generation=2;if(model.mode==18)mp4_root_history_initial_seal={2,2};
 if(model.mode==19){uintptr_t z=0;std::memcpy(model.roots[1].native+0x88,&z,8);}if(model.mode==20){uintptr_t z=0;std::memcpy(model.roots[1].native+0x98,&z,8);}
 if(model.mode==22)++model.roots[1].receipt.source.image.asset.klass;if(model.mode==23)++model.roots[1].receipt.source.image.graph_native;if(model.mode==24)++model.roots[1].receipt.source.image.graph_version;
 if(model.mode==25){uintptr_t z=0;std::memcpy(model.roots[1].graph_native+16,&z,8);}if(model.mode==26){uint32_t v=4;std::memcpy(model.roots[1].graph+0x20,&v,4);}
 const bool current=mp4_source_bootstrap_roots_current(model.witness);const bool expected=model.mode==0||model.mode==18;assert(current==expected);
 assert(model.gc.empty());
}
