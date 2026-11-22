using Kind=mp4_director_maintenance::Kind;using Call=mp4_director_maintenance::Call;
int main(int argc,char**argv){assert(argc==2);const int n=atoi(argv[1]);
 Call parent{Kind::rebuild,7,11,0x330,0x220,0x130,17};mp4_director_birth::SourceTuple owner{0x220,0x440,0x550,0x660,0x770,7,23};
 auto&x=mp4_child_execution_bank;x.count=1;x.records[0].ticket=99;x.records[0].source={owner,0x330};x.records[0].mutation={parent,true,true};x.records[0].finished=true;
 Call c{Kind::maintenance,7,12,0x330,0x220,0x814,18};mp4_raw_original_operation={7,12,18,0x330,0x220,0x814,6,1,false};mp4_child_pending_host.j.value=c;
 mp4_child_deferred_bank.count=2;mp4_child_deferred_bank.running=true;mp4_child_deferred_bank.duties[0].parent=parent;mp4_child_deferred_bank.duties[1].parent=parent;mp4_child_deferred_bank.duties[1].parent.serial=10;mp4_child_deferred_active={parent,owner,99,0,true};
 Mp4ChildPendingDeferredOrigin out{};
 if(n==1)assert(mp4_child_pending_deferred_origin(c,&out)&&!out.entered&&out.execution_ticket==99&&out.parent.serial==11);
 if(n==2){mp4_raw_original_operation.invoked=true;assert(mp4_child_pending_deferred_origin(c,&out)&&out.entered);}
 if(n==3){mp4_child_deferred_active.open=false;assert(!mp4_child_pending_deferred_origin(c,&out));}
 if(n==4){mp4_child_deferred_active.duty=1;assert(!mp4_child_pending_deferred_origin(c,&out));}
 if(n==5){mp4_child_deferred_bank.duties[0].complete=true;assert(!mp4_child_pending_deferred_origin(c,&out));}
 if(n==6){x.records[0].finished=false;assert(!mp4_child_pending_deferred_origin(c,&out));}
 if(n==7){c.method=0x999;mp4_raw_original_operation.method=c.method;mp4_child_pending_host.j.value=c;assert(!mp4_child_pending_deferred_origin(c,&out));}
 if(n==8){mp4_child_pending_host.j.value.serial=13;assert(!mp4_child_pending_deferred_origin(c,&out));}
 if(n==9){mp4_raw_original_operation.invoked=true;mp4_child_pending_host.j.current=false;assert(!mp4_child_pending_deferred_origin(c,&out));}
 if(n==10){x.records[1]=x.records[0];x.count=2;assert(!mp4_child_pending_deferred_origin(c,&out));}
 if(n==11){model.old_graph_available=false;assert(mp4_child_pending_deferred_origin(c,&out));}
 if(n==12){model.thread=false;assert(!mp4_child_pending_deferred_origin(c,&out));}
 puts("actual deferred origin composition passed");
}
