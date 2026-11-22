int main(int argc,char**argv){assert(argc==2);model.mode=atoi(argv[1]);const int mode=model.mode;
 for(size_t i=0;i<2;++i){auto&e=mp4_source_director_plans.roots[i];e.context=(Mp4TimelineContext*)malloc(sizeof(Mp4TimelineContext));new(e.context)Mp4TimelineContext{};auto&c=*e.context;c.director=&model.objects[i];c.asset=(void*)(uintptr_t)(0x100+i);c.root_script=&model.objects[i];c.phase=Mp4TimelineProofPhase::source_bootstrap_plan;c.witness.generation=7;c.identity={0x1000+i,0x2000+i*2,2};c.graph={0x2000+i*2,2,0};c.root={0x3000+i*2,2,0};assert(c.keep(c.root_script));e.construction.source.ticket.serial=i+1;e.construction.source.image.graph_native=c.identity.native;e.construction.source.image.graph_version=2;e.construction.root=c.root;}
 if(mode==1)model.plan=false;if(mode==2)model.logical=false;if(mode==3)model.window=false;
 uint8_t frozen=0;uint64_t provisional=0;const auto prepared=mp4_root_history_provisional_capture(&provisional);const bool early=mode==0||mode>=4;assert((prepared==mp4child::Result::ok)==early);
 if(!early){assert(!provisional);model.plan=model.logical=model.window=true;assert(mp4_root_history_provisional_release());goto cleanup;}
 assert(provisional&&mp4_root_history_provisional_current());assert(model.gc.size()==4);frozen=mp4_root_history_provisional.entries[0].image->view().lists[0].data[0];
 if(mode==4)model.bytes[0][0]=9;if(mode==5)model.source=false;if(mode==6)model.plan=false;if(mode==7)mp4_root_history_provisional_withdraw_source();
 if(mode>=4&&mode<=7){assert(!mp4_root_history_provisional_current());model.source=model.plan=true;assert(mp4_root_history_provisional_release());goto cleanup;}
 model.physical=true;mp4_scene_host.captured=15;
 if(mode==8)model.physical=false;if(mode==9)mp4_scene_host.captured=7;if(mode==10)model.target=false;if(mode==11)model.activation=false;if(mode==12)model.bytes[0][0]=10;
 {uint64_t captured=0;const auto result=mp4_root_history_initial_capture(&captured);const bool full=mode==0||mode>=13;assert((result==mp4child::Result::ok)==full);
  if(!full){assert(!captured&&!mp4_root_history_initial_cohort.ready);model.source=true;assert(mp4_root_history_initial_release());assert(mp4_root_history_provisional_release());goto cleanup;}
  assert(captured&&mp4_root_history_initial_current()&&model.gc.size()==6);assert(mp4_root_history_provisional.entries[0].image->view().lists[0].data[0]==frozen);
  if(mode==13)++model.module_image;if(mode==14)model.bytes[0][0]=11;if(mode==15)++idoly_mp4_runtime::job.generation;if(mode==16)mp4_root_capture_withdraw_sequence++;
  if(mode>=13&&mode<=16){assert(!mp4_root_history_initial_current());assert(mp4_root_history_initial_release());assert(mp4_root_history_provisional_release());goto cleanup;}
  model.full=true;mp4_child_readonly_source.finalized=true;
  if(mode==17)model.full=false;if(mode==18)mp4_child_readonly_source.finalized=false;if(mode==19)model.active_ok=false;
  const auto committed=mp4_root_history_initial_commit();const bool commit=mode==0||mode>=20;assert((committed==mp4child::Result::ok)==commit);
  if(!commit){assert(!mp4_root_history_initial_sealed(7)&&!mp4_root_history_provisional.finalized);assert(mp4_root_history_initial_cohort.entries[0].context->phase==Mp4TimelineProofPhase::source_bootstrap_plan);}
  else{assert(mp4_root_history_initial_sealed(7)&&mp4_root_history_provisional_current());if(mode==21){model.plan=false;assert(mp4_root_history_provisional_current());}assert(!mp4_root_history_initial_release());mp4_scene_host.released=15;}
  if(mode==22){model.borrowed=true;assert(!mp4_root_history_initial_release());model.borrowed=false;}
  if(mode==20){const auto reads=model.reads;model.thread=false;assert(!mp4_root_history_provisional_current()&&!mp4_root_history_initial_current()&&model.reads==reads);model.thread=true;}
  assert(mp4_root_history_initial_release());assert(mp4_root_history_provisional_release());}
 cleanup:for(size_t i=0;i<2;++i){auto*c=mp4_source_director_plans.roots[i].context;c->~Mp4TimelineContext();free(c);}assert(model.gc.empty());
}
