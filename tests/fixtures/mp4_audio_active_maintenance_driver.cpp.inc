Call call;int mode=0;unsigned phase_calls=0;bool expected=true;
void phase(){++phase_calls;assert(mp4_animation_gate.maintenance_inflight(7)&&!mp4_animation_gate.closed(7));
 if(mode==2)deferred_origin=false;
 if(mode==3){call.kind=Kind::rebuild;call.method=0x130;mp4_raw_original_operation.kind=3;mp4_raw_original_operation.method=call.method;mp4_child_pending_host.j.value=call;}
 if(mode==4)audio_model.change_phase=true;
 if(mode==5)mp4_audio_native_readers=1;
 assert(mp4_audio_active_call_source_quiet(call)==expected);
}
void idle(){}bool thread(){return model.thread;}
bool before(void*,uint64_t e){assert(e==7&&mp4_animation_gate.closed(e));return true;}
bool after(void*,uint64_t e){assert(e==7&&mp4_animation_gate.closed(e)&&!mp4_animation_gate.maintenance_inflight(e));return true;}
int main(int argc,char**argv){assert(argc==2);mode=atoi(argv[1]);expected=mode==1;
 call=init();call.kind=Kind::maintenance;call.method=0x814;mp4_raw_original_operation.kind=6;mp4_raw_original_operation.method=call.method;mp4_child_pending_host.j.value=call;
 idoly_mp4_world::AnimationApi api{{idle,idle,idle,idle,idle,phase,idle,idle},thread};assert(mp4_animation_gate.install(api)&&mp4_animation_gate.acquire(7));
 assert(mp4_audio_active_call_source_quiet(call)); // exact prepared Before while closed
 assert(mp4_animation_gate.maintenance(7,{nullptr,before,after})&&phase_calls==1);
 if(mode==1)assert(mp4_audio_active_call_source_quiet(call)); // exact post-consumption while closed
 assert(!mp4_animation_gate.maintenance_inflight(7)&&mp4_animation_gate.closed(7)&&mp4_animation_gate.release(7));
 assert(!mp4_audio_active_call_source_quiet(call)); // released gate grants nothing
 puts("actual Audio +real AnimationGate maintenance composition passed");
}
