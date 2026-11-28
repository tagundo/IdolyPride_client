// Actual shipping Raw/Journal/native-phase/Driver join. Queue, descriptor and
// original callback leaves are explicit service models, not engine emulation.
alignas(16) uint8_t native_manager[0x500]{},native_queue[16]{};
unsigned phase_calls[8]{};bool phase_body=true;
bool source_plan(const dm::Call&c){const auto&r=mp4_raw_original_operation;
 return owner&&source_current&&r.depth&&r.epoch==c.epoch&&r.serial==c.serial&&r.root_asset==c.source_asset&&r.director==c.receiver&&r.method==c.method&&r.receipt==c.original_receipt&&r.kind==static_cast<uint8_t>(c.kind)
  &&mp4_native_phase_origin(c.epoch,reinterpret_cast<void*>(c.receiver),c.method);
}
bool read_native(void*,uintptr_t at,void*out,size_t count){const auto m=reinterpret_cast<uintptr_t>(native_manager),q=reinterpret_cast<uintptr_t>(native_queue);
 if(!((at>=m&&count<=sizeof native_manager&&at-m<=sizeof native_manager-count)||(at>=q&&count<=sizeof native_queue&&at-q<=sizeof native_queue-count)))return false;
 memcpy(out,reinterpret_cast<void*>(at),count);return true;
}
void phase_original(unsigned index){++phase_calls[index];if(index==0&&phase_body){auto n=model->live();expected_entry=mp4_child_driving_hooks.methods[3].rva;mp4_child_driving_process_hook(n.script,n.node,{},nullptr,reinterpret_cast<Method*>(0xdeadc0de));}}
void p0(){phase_original(0);}void p1(){phase_original(1);}void p2(){phase_original(2);}void p3(){phase_original(3);}void p4(){phase_original(4);}void p5(){phase_original(5);}void p6(){phase_original(6);}void p7(){phase_original(7);}
void w0(){mp4_animation_journal_original(0);}void w1(){mp4_animation_journal_original(1);}void w2(){mp4_animation_journal_original(2);}void w3(){mp4_animation_journal_original(3);}void w4(){mp4_animation_journal_original(4);}void w5(){mp4_animation_journal_original(5);}void w6(){mp4_animation_journal_original(6);}void w7(){mp4_animation_journal_original(7);}
bool native_thread(){return owner;}
int main(int argc,char**argv){assert(argc==2);const int scenario=atoi(argv[1]);Model m;model=&m;
 Phase originals[]={p0,p1,p2,p3,p4,p5,p6,p7};for(unsigned i=0;i<8;++i){mp4_animation_original[i]=originals[i];mp4_animation_profile.phases[i].callback.rva=reinterpret_cast<uintptr_t>(originals[i]);}
 idoly_mp4_world::AnimationApi gate{{w0,w1,w2,w3,w4,w5,w6,w7},native_thread};assert(mp4_animation_gate.install(gate));
 uintptr_t queue=reinterpret_cast<uintptr_t>(native_queue);memcpy(native_manager+0x478,&queue,sizeof queue);
 dm::Api pending{};pending.manager=reinterpret_cast<uintptr_t>(native_manager);pending.read=read_native;pending.current=[](void*,const dm::Call&c){return source_plan(c);};pending.call_origin=pending.current;
 pending.retired_output=[](void*,uint64_t,uintptr_t,uintptr_t,uint32_t,uint64_t,uintptr_t){return false;};pending.hook_origin=[](void*,dm::Hook,uintptr_t,const dm::Call&){return false;};pending.basis=[](void*,const dm::Call&,idoly_mp4_world::AnimationGraph,uint32_t,dm::Basis*){return false;};pending.future_producers_closed=[](void*,const dm::Call&){return closure;};pending.frame_deferred_current=mp4_native_phase_deferred_current;
 assert(mp4_child_pending_host.journal().configure(pending));
 mp4_child_driving_process_original=process;
 auto a=m.api();a.current=[](void*p,uint64_t e,uintptr_t asset){return static_cast<Model*>(p)->source&&!mp4_child_driving_rejected.load()&&e==17&&asset==33;};a.origin=mp4_child_driving_origin;
 a.frame_closed=[](void*,uint64_t e,uint64_t t){return mp4_animation_gate.completed_frame(e,t);};a.frame_issued_current=[](void*,uint64_t e,uint64_t t){return mp4_animation_gate.issued_frame(e,t);};a.frame_revoked_unconsumed=[](void*,uint64_t e,uint64_t t){return mp4_animation_gate.revoked_unconsumed_frame(e,t);};
 assert(mp4_child_driving_scope.configure(a)&&mp4_child_driving_scope.capture(17,33)==R::ok&&mp4_child_driving_scope.begin_frame(0)==R::ok);mp4_child_driving_active.store(true);
 assert(mp4_animation_gate.acquire(17)&&mp4_animation_gate.prepare(17,0)&&mp4_animation_gate.grant(17,0));
 if(scenario!=2)assert(mp4_child_driving_scope.mark_frame_issued(0)==R::ok);
 if(scenario==1){auto n=m.live();expected_entry=mp4_child_driving_hooks.methods[3].rva;mp4_child_driving_process_hook(n.script,n.node,{},nullptr,reinterpret_cast<Method*>(0xdeadc0de));assert(mp4_child_driving_rejected.load()&&quarantines==1&&original_calls==1);assert(!mp4_animation_gate.completed_frame(17,0));mp4_animation_gate.revoke_grants(17);assert(mp4_child_driving_scope.release()==R::ok);return 0;}
 if(scenario==3)phase_body=false;
 m.held=false;bool ran=true;for(unsigned i=0;i<8;++i)ran=mp4_animation_gate.invoke(i)&&ran;m.held=true;
 if(scenario==2){assert(ran&&mp4_child_driving_rejected.load()&&quarantines==1&&original_calls==1);assert(mp4_child_driving_scope.finish_frame(0)==R::stale);}
 else if(scenario==3){assert(ran&&mp4_child_driving_scope.finish_frame(0)==R::unsupported&&!original_calls);}
 else {assert(ran&&!mp4_child_driving_rejected.load()&&!quarantines&&original_calls==1&&mp4_child_driving_scope.finish_frame(0)==R::ok);for(auto calls:phase_calls)assert(calls==1);}
 assert(mp4_child_driving_scope.release()==R::ok&&mp4_animation_gate.release(17));
}
