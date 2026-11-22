using Kind=mp4_director_maintenance::Kind;using Call=mp4_director_maintenance::Call;
Call init(){Call c{Kind::rebuild,7,11,0x330,0x220,0x130,17};auto&x=mp4_child_execution_bank;x.running=true;x.records[0].ticket=99;x.records[0].source={{0x220,0x440,0x550,0x660,0x770,7,23},0x330};x.records[0].before={0x900,4,0};auto&m=mp4_child_module_operations;m.count=1;m.before_count=1;auto&r=m.records[0];r.source=x.records[0].source;r.before={r.source.owner,{0xa00,0x900,4},{0xb00,4,0},29};r.kind=c.kind;r.ticket=99;r.original_receipt=17;r.before_count=1;m.before[0]={r.before,31,false};mp4_raw_original_operation={7,11,17,0x330,0x220,0x130,3,1,false};mp4_child_pending_host.j.value=c;auto&h=audio_bank;h.programs[0].captured=true;h.programs[0].before={(void*)0x500,0x700,41};h.sources[0]={(void*)0x500,0x700,true,false};h.pins[0]={0xd00,0x700,41,0};h.pin_proofs[0]={0xa00,0x900,0xc00,4,0};h.roots[0]=1;h.root_values[0]=(void*)0x500;return c;}
void private_phase(){auto&h=audio_bank;h.phase=Mp4AudioOuterPhase::private_silent;h.transaction=2;h.evaluated=true;h.programs[0].fresh=true;mp4_audio_published=true;}
void entered(Call c){auto&x=mp4_child_execution_bank;x.count=1;x.records[0].mutation={c,true,true};mp4_raw_original_operation.invoked=true;auto&r=mp4_child_module_operations.records[0];r.entered=true;r.call=c;r.returned=true;}
int main(int argc,char**argv){assert(argc==2);int n=atoi(argv[1]);Call c=init();bool want=false;
 if(n==1)want=true; // genuine pending-before: initial playing/unpaused Source is allowed
 if(n==2){entered(c);want=true;}
 if(n==3){private_phase();want=true;}
 if(n==4){audio_bank.phase=Mp4AudioOuterPhase::rebuilding;audio_bank.transaction=2;want=true;}
 if(n==5){audio_bank.phase=Mp4AudioOuterPhase::restore_rebuilding;audio_bank.transaction=2;audio_bank.restoring=true;want=true;}
 if(n==6){audio_bank.phase=Mp4AudioOuterPhase::restore_ready;audio_bank.transaction=2;audio_bank.restoring=audio_bank.evaluated=true;want=true;}
 if(n==7){model.thread=false;}
 if(n==8){mp4_child_execution_bank.records[0].ticket=0;}
 if(n==9){mp4_world_host.animation_owned=false;}
 if(n==10){mp4_world_host.invalidated=true;}
 if(n==11){mp4_animation_published=false;}
 if(n==12){audio_schedule_closed=false;}
 if(n==13){audio_model.root=0x331;}
 if(n==14){audio_bank.failed=true;}
 if(n==15){audio_bank.canonical_readers=1;}
 if(n==16){audio_bank.source_readers=1;}
 if(n==17){mp4_audio_native_readers=1;}
 if(n==18){audio_bank.pending_canonical=2;}
 if(n==19){audio_model.hooks=false;}
 if(n==20){audio_model.current=false;}
 if(n==21){audio_model.roots=false;}
 if(n==22){audio_bank.phase=Mp4AudioOuterPhase::source_wait;}
 if(n==23){audio_bank.phase=Mp4AudioOuterPhase::restored;}
 if(n==24){mp4_audio_published=true;}
 if(n==25){private_phase();audio_bank.programs[0].fresh=false;}
 if(n==26){private_phase();audio_bank.gate.valid=false;}
 if(n==27){audio_bank.phase=Mp4AudioOuterPhase::rebuilding;audio_bank.transaction=3;}
 if(n==28){audio_bank.sources[0].managed=(void*)0x999;}
 if(n==29){audio_bank.roots[0]=0;}
 if(n==30){audio_bank.pins[0].recipe=42;}
 if(n==31){audio_bank.pin_proofs[0].output=0;}
 if(n==32){audio_model.channel=false;}
 if(n==33){audio_model.throw_channel=true;}
 if(n==34){audio_model.change_call=true;}
 if(n==35){audio_model.begin_reader=true;}
 if(n==36){audio_model.change_phase=true;}
 if(n==37){audio_model.lose_root=true;}
 if(n==38){mp4_audio_foreign_dirty=true;audio_model.current=false;}
 if(n==39){audio_bank.count=65;}
 if(n==40){audio_bank.source_count=65;}
 if(n==41){audio_bank.pin_count=8193;}
 if(n==42){audio_bank.root_count=32769;}
 if(n==43){model.old_graph_available=false;audio_bank.pins[0].retirement=2;want=true;} // ref identity only, no old native CAPI
 if(n==44){c.kind=Kind::native_phase;c.method=0x818;mp4_raw_original_operation.kind=7;mp4_raw_original_operation.method=c.method;mp4_child_pending_host.j.value=c;model.phase_index=6;model.tick=0;audio_schedule_closed=false;private_phase();want=true;}
 if(n==45){c.kind=Kind::native_phase;c.method=0x818;mp4_raw_original_operation.kind=7;mp4_raw_original_operation.method=c.method;mp4_child_pending_host.j.value=c;model.phase_index=6;model.phase=false;private_phase();}
 if(n==46){c.kind=Kind::maintenance;c.method=0x814;mp4_raw_original_operation.kind=6;mp4_raw_original_operation.method=c.method;mp4_child_pending_host.j.value=c;want=true;}
 if(n==47){c.kind=Kind::maintenance;c.method=0x814;mp4_raw_original_operation.kind=6;mp4_raw_original_operation.method=c.method;mp4_child_pending_host.j.value=c;deferred_origin=false;}
 if(n==48){audio_bank.pin_count=0;want=true;} // empty actual transient accepted by channel probe
 if(n==49){audio_direct_clip=(void*)0x999;}
 if(n==50){mp4_audio_managed_clip=nullptr;}
 if(n==51){audio_clip_throws=true;}
 if(n>=52&&n<=54){c.kind=Kind::native_phase;c.method=0x818;mp4_raw_original_operation.kind=7;mp4_raw_original_operation.method=c.method;mp4_child_pending_host.j.value=c;model.phase_index=6;
  if(n>=53){audio_bank.phase=Mp4AudioOuterPhase::restore_ready;audio_bank.transaction=2;audio_bank.restoring=audio_bank.evaluated=true;audio_bank.programs[0].fresh=true;}
  if(n==54){mp4_audio_published=true;want=true;}
 }
 if(n>=55&&n<=59){audio_schedule_closed=false;audio_schedule_maintenance=n!=56;
  if(n!=57){c.kind=Kind::maintenance;c.method=0x814;mp4_raw_original_operation.kind=6;mp4_raw_original_operation.method=c.method;mp4_child_pending_host.j.value=c;}
  if(n==55)want=true;if(n==58)audio_model.lose_schedule=true;if(n==59)deferred_origin=false;
 }
 assert(mp4_audio_active_call_source_quiet(c)==want);puts("actual active Audio Call composition passed");
}
