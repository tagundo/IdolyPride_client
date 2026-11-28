bool late_current(void*,uint64_t epoch,uint64_t job){++late_calls;return late_ok&&epoch==7&&job==9;}
bool late_fenced(void*){++late_calls;return late_ok;}
bool root_add(void*,void*,void*,uintptr_t caller,uint64_t*out){++root_calls;*out=late_ok&&caller==123?19:0;return *out;}
bool retired=false;bool retired_receipt(void*,uint64_t epoch,uint64_t job,void*controller,void*camera){return retired&&epoch==7&&job==9&&controller==reinterpret_cast<void*>(11)&&camera==reinterpret_cast<void*>(12);}
int main(int argc,char**argv){
 assert(argc==2);const std::string name=argv[1];auto&h=mp4_srp_source_bootstrap;
 state_image.controller=mp4_scene_host.source.controller;state_image.camera=mp4_scene_host.source.camera;state_image.queue=reinterpret_cast<void*>(41);state_image.array=reinterpret_cast<void*>(42);state_image.count=1;state_image.capacity=4;state_image.version=2;state_image.items[0]=reinterpret_cast<void*>(43);
 if(name=="no_worker")worker_current=false;if(name=="no_producer")mp4_scene_source_bootstrap.producer_receipt=0;
 if(name=="no_early")mp4_scene_source_bootstrap.receipt[1]=0;if(name=="wrong_key")mp4_scene_source_bootstrap.key.job=10;
 if(name=="raw")mp4_raw_original_operation.depth=1;if(name=="rebuilding")mp4_rebuild_ledger.active=true;
 if(name=="no_gate")early_current=false;if(name=="unheld")clock_held=false;
 if(name=="camera_unheld")camera_active=false;if(name=="no_intercept")intercepted=false;
 if(name=="capture_refused")capture_ok=false;if(name=="read_refused")read_ok=false;if(name=="throw")capture_throws=true;
 bool captured=false,threw=false;try{captured=mp4_srp_source_capture();}catch(const std::runtime_error&){threw=true;}
 assert(threw==(name=="throw"));
 const bool negative=name=="no_worker"||name=="no_producer"||name=="no_early"||name=="wrong_key"||name=="raw"||name=="rebuilding"||name=="no_gate"||name=="unheld"||name=="camera_unheld"||name=="no_intercept"||name=="capture_refused"||name=="read_refused"||name=="throw";
 assert(captured==!negative&&!h.capturing);assert(!late_calls);
 if(negative){assert(h.failed&&!mp4_srp_source_capture());assert(mp4_srp_source_release());return 0;}
 assert(mp4_srp_source_initial_current()&&mp4_srp_source_capture());
 // A completed initial snapshot supplies neither later Raw nor frame authority.
 assert(!mp4_srp_source_dispatch_current(&h,7,9)&&!mp4_srp_source_dispatch_fenced(&h));
 uint64_t receipt=99;assert(!mp4_srp_source_root_add(&h,h.source.controller,reinterpret_cast<void*>(43),123,&receipt)&&!receipt);
 mp4_srp_source_mutations={reinterpret_cast<void*>(1),late_current,late_fenced,root_add,retired_receipt};
 if(name=="changed_worker")worker_current=false;if(name=="queue_changed")++state_image.version;
 if(name=="first_changed")state_image.first=false;if(name=="subscriber_changed")state_image.subscribers[3]=reinterpret_cast<void*>(15);
 if(name=="foreign")mp4_srp_dispatch_foreign_dirty.store(true,std::memory_order_release);
 if(name=="lease_open")h.controller.lease.opened=true;if(name=="lease_poison")h.controller.lease.poison=true;
 if(name=="changed_source")mp4_scene_host.source.camera=reinterpret_cast<void*>(16);
 const bool changed=name=="changed_worker"||name=="queue_changed"||name=="first_changed"||name=="subscriber_changed"||name=="foreign"||name=="lease_open"||name=="lease_poison"||name=="changed_source";
 assert(mp4_srp_source_initial_current()==!changed);
 if(name=="program"||name=="program_open"||name=="program_owned"||name=="program_rejected"){
  assert(mp4_srp_source_program_current(7,9));worker_current=false;assert(mp4_srp_source_program_current(7,9));
  assert(!mp4_srp_source_program_current(8,9)&&!mp4_srp_source_program_current(7,10));
  h.controller.lease.opened=true;assert(!mp4_srp_source_program_current(7,9));
  Mp4SrpEntered entry{&h.dispatch,h.source.controller,name=="program_owned",true,nullptr};mp4_srp_entered=&entry;
  assert(mp4_srp_source_program_current(7,9)==(name=="program_owned"));mp4_srp_entered=nullptr;h.controller.lease.opened=false;
 }
 if(name=="late_real"){
  late_ok=true;worker_current=false; // old source graph receipt is intentionally not reused
  assert(mp4_srp_source_dispatch_current(&h,7,9)&&mp4_srp_source_dispatch_fenced(&h));
  assert(mp4_srp_source_root_add(&h,h.source.controller,reinterpret_cast<void*>(43),123,&receipt)&&receipt==19);
  assert(!mp4_srp_source_dispatch_current(&h,7,10));
 }
 if(name=="foreign"){assert(!mp4_srp_source_release()&&h.captured);retired=true;}
 if(name=="withdraw"){const unsigned old=read_calls;mp4_srp_source_withdraw();assert(read_calls==old&&!mp4_srp_dispatch_published.load(std::memory_order_acquire));}
 if(name=="restore_before_parts"){
  h.dispatch.mutated=true;late_ok=true;assert(mp4_srp_source_restore()&&h.restored&&restore_calls==1);
  late_ok=false;worker_current=false;assert(mp4_srp_source_restore()&&restore_calls==1);
 }
 if(name=="new_unknown_after_restore"){
  h.dispatch.mutated=true;late_ok=true;assert(mp4_srp_source_restore()&&restore_calls==1);
  h.dispatch.unknown_mutation=true;late_ok=false;assert(!mp4_srp_source_release()&&h.captured);retired=true;
 }
 if(name=="busy_release"){clear_ok=false;assert(!mp4_srp_source_release()&&h.captured);clear_ok=true;}
 if(name=="mutated_wait"||name=="mutated_restore"||name=="retired_mutation"||name=="unknown_mutation"){
  h.dispatch.mutated=true;assert(!mp4_srp_source_release()&&h.captured&&!restore_calls);
  if(name=="unknown_mutation")h.dispatch.unknown_mutation=true;
  if(name=="retired_mutation")mp4_scene_host.source.camera=reinterpret_cast<void*>(99);
  late_ok=true;
  if(name=="unknown_mutation"||name=="retired_mutation"){
   assert(!mp4_srp_source_release()&&h.captured&&!restore_calls);retired=true;
  }
  if(name=="mutated_restore"){restore_ok=false;assert(!mp4_srp_source_release()&&h.captured&&restore_calls==1);restore_ok=true;assert(!mp4_srp_source_release()&&h.captured);retired=true;}
 }
 readers_idle=false;assert(!mp4_srp_source_release()&&h.captured);readers_idle=true;
 assert(mp4_srp_source_release()&&!h.started&&!h.captured);return 0;
}
