int main(int argc,char**argv){assert(argc==2);model.mode=atoi(argv[1]);const auto mode=model.mode;
 model.before={{1,2,3,4,5,7,9},{0x1000,0x2000,2},{0x3000,2,0},1};model.actual=model.before;model.call={mp4_director_maintenance::Kind::rebuild,7,11,2,1,13,17};
 mp4_root_history::Image images[3];for(size_t i=0;i<3;++i){auto&r=mp4_root_history_lineage_pool.records[i];r.id=i+1;r.owner=model.before.owner;r.context=&model.contexts[i];r.context->identity=model.before.graph;r.context->root=model.before.root;r.image=&images[i];mp4_root_history::View data{};data.director=(void*)1;data.asset=(void*)2;data.epoch=7;data.graph=0x2000;data.root=0x3000;data.graph_version=data.root_version=2;assert(images[i].capture(data));}
 if(mode==1)model.thread=false;if(mode==2)model.before.source_capture=0;if(mode==3)model.call.serial=0;if(mode==4)model.call.original_receipt=0;if(mode==5)++model.call.epoch;
 if(mode==6)model.retired=false;if(mode==7)model.proof=false;if(mode==8)model.actual_capture=0;if(mode==9)model.actual_capture=4;
 if(mode==10)++model.actual.owner.director;if(mode==11)++model.actual.source_capture;if(mode==12)++model.contexts[1].identity.slot;if(mode==13)++model.contexts[1].root.version;
 if(mode==14)images[1].release();if(mode==15)++mp4_root_history_lineage_pool.records[1].owner.method;
 if(mode==16){mp4_root_history_lineage_pool.records[1].retired=true;mp4_root_history_lineage_pool.records[1].retired_call=model.call;}
 if(mode==17){mp4_root_history_lineage_pool.records[1].retired=true;mp4_root_history_lineage_pool.records[1].retired_call=model.call;++mp4_root_history_lineage_pool.records[1].retired_call.serial;}
 if(mode==18){mp4_root_history_lineage_pool.records[0].retired=true;mp4_root_history_lineage_pool.records[0].retired_call=model.call;++mp4_root_history_lineage_pool.records[0].retired_call.serial;}
 const bool good=mode==0||mode==16||mode==19;const bool retired=mp4_root_history_retired(model.before,model.call);assert(retired==good);assert(!model.old_capi);
 if(good){if(mode!=16)for(auto&r:mp4_root_history_lineage_pool.records)assert(r.retired&&mp4_child_call_same(r.retired_call,model.call));if(mode==19)assert(mp4_root_history_retired(model.before,model.call));}
 if(mode==1)assert(model.retirement_queries==0);
}
