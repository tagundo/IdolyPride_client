using Kind=mp4_director_maintenance::Kind;using Call=mp4_director_maintenance::Call;
Call init(Kind kind=Kind::rebuild){
 Call c{kind,7,11,0x330,0x220,kind==Kind::rebuild?0x130u:kind==Kind::play?0x110u:kind==Kind::stop?0x120u:0x150u,17};
 auto&x=mp4_child_execution_bank;x.running=true;x.records[0].ticket=99;x.records[0].source={{0x220,0x440,0x550,0x660,0x770,7,23},0x330};x.records[0].before={0x900,4,0};
 auto&m=mp4_child_module_operations;m.count=1;m.before_count=1;auto&r=m.records[0];r.source=x.records[0].source;r.before={r.source.owner,{0xa00,0x900,4},{0xb00,4,0},29};r.kind=kind;r.ticket=99;r.original_receipt=kind==Kind::rebuild?17:0;r.before_count=1;m.before[0]={r.before,31,false};
 mp4_raw_original_operation={c.epoch,c.serial,c.original_receipt,c.source_asset,c.receiver,c.method,uint8_t(c.kind),1,false};mp4_child_pending_host.j.value=c;return c;
}
void enter(Call c,bool returned=false){auto&x=mp4_child_execution_bank;x.count=1;x.records[0].mutation={c,true,returned};mp4_raw_original_operation.invoked=true;auto&r=mp4_child_module_operations.records[0];r.entered=true;r.call=c;r.original_receipt=c.original_receipt;r.returned=returned;}
int main(int argc,char**argv){assert(argc==2);const int n=atoi(argv[1]);Call c=init();Mp4ChildPendingOperationOrigin out{};uint64_t ticket=55;
 if(n==1){assert(mp4_child_pending_operation_read(c,&out)&&!out.entered&&out.module_ticket==99&&out.retained_before_capture==31&&out.before_count==1);assert(mp4_child_pending_operation_origin(c,&ticket)&&ticket==99);}
 if(n==2){enter(c);assert(mp4_child_pending_operation_read(c,&out)&&out.entered&&!out.original_returned);}
 if(n==3){enter(c,true);assert(mp4_child_pending_operation_read(c,&out)&&out.original_returned&&out.module_returned);}
 if(n==4){mp4_child_execution_bank.records[0].ticket=0;assert(!mp4_child_pending_operation_origin(c,&ticket)&&!ticket);}
 if(n==5){mp4_child_execution_bank.running=false;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==6){mp4_child_execution_bank.records[0].ticket=98;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==7){auto&m=mp4_child_module_operations;m.records[1]=m.records[0];m.count=2;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==8){mp4_child_module_operations.records[0].entered=true;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==9){mp4_raw_original_operation.invoked=true;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==10){enter(c);mp4_child_pending_host.j.current=false;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==11){enter(c);mp4_child_execution_bank.records[1]=mp4_child_execution_bank.records[0];mp4_child_execution_bank.count=2;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==12){mp4_child_module_operations.records[0].original_receipt=18;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==13){mp4_child_execution_bank.records[0].before.version=6;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==14){mp4_child_module_operations.records[0].source.owner.asset=0x999;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==15){mp4_child_module_operations.records[0].before_count=0;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==16){mp4_child_module_operations.records[0].before_begin=~size_t(0);assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==17){mp4_child_module_operations.before[0].actual_capture=0;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==18){auto&m=mp4_child_module_operations;m.before[1]=m.before[0];m.records[0].before_count=m.before_count=2;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==19){mp4_child_module_operations.before[0].source.owner.epoch=8;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==20){mp4_child_module_operations.before[0].source.root.version=6;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==21){mp4_child_module_operations.records[0].abandoned=true;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==22){enter(c);mp4_child_module_operations.records[0].finished=true;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==23){mp4_child_pending_host.j.bad=true;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==24){mp4_child_pending_host.j.value.serial=12;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==25){model.thread=false;assert(!mp4_child_pending_operation_origin(c,&ticket)&&ticket==0);}
 if(n==26){model.throw_planned=true;assert(!mp4_child_pending_operation_origin(c,&ticket)&&ticket==0);}
 if(n==27){model.old_graph_available=false;enter(c);assert(mp4_child_pending_operation_read(c,&out)&&out.before.graph.native==0xa00);}
 if(n>=28&&n<=32){mp4_child_execution_bank={};mp4_child_module_operations={};c=init(static_cast<Kind>(n-27));assert(mp4_child_pending_operation_read(c,&out));}
 if(n==33){c=init(Kind::play);c.method=0x140;mp4_raw_original_operation.method=c.method;mp4_child_pending_host.j.value=c;assert(mp4_child_pending_operation_read(c,&out));}
 if(n==34){c.method=0x999;mp4_raw_original_operation.method=c.method;mp4_child_pending_host.j.value=c;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n==35){c.kind=Kind::maintenance;assert(!mp4_child_pending_operation_read(c,&out));}
 if(n>=36){c.kind=Kind::native_phase;c.method=0x800;mp4_raw_original_operation.kind=7;mp4_raw_original_operation.method=c.method;mp4_child_pending_host.j.value=c;Mp4ChildPendingFrameOrigin frame{};
  if(n==36)assert(mp4_child_pending_frame_origin(c,&frame)&&frame.tick==0&&frame.phase==0&&!frame.entered);
  if(n==37){mp4_raw_original_operation.invoked=true;assert(mp4_child_pending_frame_origin(c,&frame)&&frame.entered);}
  if(n==38){model.phase_index=5;c.method=0x814;mp4_raw_original_operation.method=c.method;mp4_child_pending_host.j.value=c;model.tick=17;assert(mp4_child_pending_frame_origin(c,&frame)&&frame.tick==17&&frame.phase==5);}
  if(n==39){mp4_raw_original_operation.depth=2;assert(!mp4_child_pending_frame_origin(c,&frame));}
  if(n==40){model.phase=false;assert(!mp4_child_pending_frame_origin(c,&frame));}
  if(n==41){model.native=false;assert(!mp4_child_pending_frame_origin(c,&frame));}
  if(n==42){model.phase_index=8;assert(!mp4_child_pending_frame_origin(c,&frame));}
  if(n==43){mp4_raw_original_operation.invoked=true;mp4_child_pending_host.j.current=false;assert(!mp4_child_pending_frame_origin(c,&frame));}
  if(n==44){c.kind=Kind::maintenance;assert(!mp4_child_pending_frame_origin(c,&frame));}
 }
 puts("actual operation origin case passed");
}
