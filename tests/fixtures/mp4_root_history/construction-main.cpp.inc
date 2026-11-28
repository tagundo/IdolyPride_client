int main(int argc,char**argv){assert(argc==2);model.mode=atoi(argv[1]);int mode=model.mode;Mp4TimelineContext c;Mp4RootConstructionReceipt proof{};
 if(mode==1)model.thread=false;if(mode==2)model.current=false;if(mode==3)model.lineage=false;if(mode==4)model.owner=false;if(mode==5)model.record=false;if(mode==6)record.retired=true;if(mode==7)model.promise=false;if(mode==8)model.complete=false;
 if(mode==9)++model.actual.birth;if(mode==10)++model.actual.factory;if(mode==11)++model.actual.parent.serial;if(mode==12)model.actual.returned=false;if(mode==13)model.publication=false;if(mode==14)++model.actual.root.version;if(mode==15)mp4_child_lineage_bank.nodes[0].current.root.version++;
 if(mode==16){c.phase=Mp4TimelineProofPhase::admission;model.held=false;}if(mode==17){c.phase=Mp4TimelineProofPhase::source_bootstrap_plan;model.held=false;model.ordinary=false;}
 if(mode==18)mp4_child_lineage_bank.count=2;if(mode==19)mp4_child_lineage_bank.nodes[0].factory_returned=true;
 if(mode==20){mp4_child_lineage_bank.nodes[0].factory_returned=true;model.completed_graph=false;}
 if(mode>=21&&mode<=23){record.private_birth=false;if(mode==22)model.ordinary=false;if(mode==23)record.ordinary.source.input.game_object=4;}
 if(mode>=24){model.held=false;model.call.kind=mp4_director_maintenance::Kind::native_phase;if(mode==25)model.operation=false;if(mode==26)model.call.kind=mp4_director_maintenance::Kind::rebuild;if(mode==27)model.call.epoch=8;if(mode==28)model.call.source_asset=3;if(mode==29)model.phase_current=false;}
 const bool good=mode==0||mode==16||mode==19||mode==21||mode==24||mode==30;
 const bool ready=mp4_root_history_current_construction(c,&proof);assert(ready==good);
 if(good){if(mode==16||mode==21)assert(proof.ordinary==23&&proof.ordinary_generation==29&&!proof.birth);else assert(proof.birth==17&&proof.factory==19&&proof.operation==11&&proof.original==13);}
 else assert(!proof.birth&&!proof.ordinary);
 if(mode==1||mode==2)assert(!model.queries);
}
