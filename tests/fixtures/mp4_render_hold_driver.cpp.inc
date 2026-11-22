int main(int argc,char**argv){assert(argc==2);setup();std::string mode=argv[1];
 if(mode=="ordinary"){auto_call();mp4_render_camera_hook({srp.native_context},mp4_scene_host.source.camera,nullptr);mp4_camera_manual_render_hook(mp4_scene_host.source.camera,nullptr);assert(automatic_originals==2&&manual_originals==1&&mp4_render_hold_readers_idle());}
 else if(mode=="missing_manual"){mp4_camera_manual_render_original=nullptr;assert(mp4_render_hold_acquire(4,9)==Mp4SceneResult::stale&&!mp4_render_hold_state.active);}
 else if(mode=="frontend_wrong_stub"){
#ifndef IDOLY_DARWIN_BRIDGE
 mp4_managed_hook_receipts[2].stub=reinterpret_cast<void*>(automatic_original);
#else
 frontends_ok=false;
#endif
 assert(mp4_render_hold_acquire(4,9)==Mp4SceneResult::stale&&!mp4_render_hold_state.active);}
 else if(mode=="existing_original_wait"){std::atomic<bool>entered{false},leave{false};automatic_action=[&](){entered=true;while(!leave.load())std::this_thread::yield();};std::thread worker([&](){owner_thread=false;auto_call();});while(!entered.load())std::this_thread::yield();assert(mp4_render_hold_acquire(4,9)==Mp4SceneResult::waiting&&mp4_render_hold_state.active&&!mp4_render_hold_state.acquired);leave=true;worker.join();automatic_action={};acquire();assert(automatic_originals==1);cleanup();}
 else {acquire();
 if(mode=="ordinary_blocked"){render_intent=false;auto_call();mp4_render_camera_hook({srp.native_context},reinterpret_cast<void*>(0x222),nullptr);mp4_camera_manual_render_hook(mp4_scene_host.source.camera,nullptr);assert(!automatic_originals&&!manual_originals&&!owned_attempts&&!suspensions&&!particle_observations);cleanup();auto_call();assert(automatic_originals==1);}
 else if(mode=="private_main"){bool sampled=false;automatic_action=[&](){sampled=private_time&&private_rng&&Mp4RenderHoldOriginal::current&&Mp4RenderHoldOriginal::current->draw==17&&Mp4RenderHoldOriginal::current->frame==13;};auto_call();assert(automatic_originals==1&&sampled&&!suspensions&&mp4_render_hold_readers_idle());automatic_action={};cleanup();}
 else if(mode=="private_no_ticket"){gpu_ticket=false;auto_call();assert(!automatic_originals&&mp4_camera_host.invalidated&&mp4_render_hold_readers_idle());cleanup();}
 else if(mode=="private_no_srp_receipt"){srp_draw_receipt=false;auto_call();assert(!automatic_originals&&mp4_camera_host.invalidated);cleanup();}
 else if(mode=="private_wrong_context"){mp4_render_stack_hook({reinterpret_cast<void*>(0x999)},mp4_scene_host.source.camera,nullptr);assert(!automatic_originals&&!owned_attempts);cleanup();}
 else if(mode=="private_no_programme"){graphics_closed=false;auto_call();assert(!automatic_originals&&mp4_camera_host.invalidated);cleanup();}
 else if(mode=="unexpected_nested"){nested_auto=true;auto_call();assert(automatic_originals==1&&mp4_camera_host.invalidated&&!suspensions&&mp4_render_hold_readers_idle());cleanup();}
 else if(mode=="automatic_throw"){original_throw=true;try{auto_call();assert(false);}catch(int x){assert(x==7);}assert(mp4_render_hold_readers_idle()&&!Mp4RenderHoldOriginal::current&&!Mp4RenderHoldReader::current&&!private_time&&!private_rng);original_throw=false;cleanup();}
 else if(mode=="offthread_held"){std::thread worker([&](){owner_thread=false;auto_call();mp4_camera_manual_render_hook(mp4_scene_host.source.camera,nullptr);});worker.join();assert(!automatic_originals&&!manual_originals&&mp4_render_hold_readers_idle());cleanup();}
 else if(mode=="manual_no_origin"){mp4_camera_manual_render_hook(reinterpret_cast<void*>(0x222),nullptr);assert(!manual_originals);cleanup();}
 else if(mode=="manual_no_aux"){mp4_monitor_camera_render_origin=monitor_origin;monitor_allowed=true;mp4_camera_manual_render_hook(reinterpret_cast<void*>(0x222),nullptr);assert(!manual_originals);cleanup();}
 else if(mode=="manual_private"||mode=="manual_nested"||mode=="manual_throw"){mp4_monitor_camera_render_origin=monitor_origin;monitor_allowed=true;mp4_gpu_auxiliary_host.configured=mp4_gpu_auxiliary_host.draw=true;mp4_gpu_auxiliary_host.source=4;mp4_gpu_auxiliary_host.epoch=9;mp4_gpu_auxiliary_host.active_token=63;mp4_gpu_auxiliary_host.sequence=1;mp4_gpu_auxiliary_host.auxiliary_recipe=(uint64_t(0x4d4f)<<48)|1;private_time=private_rng=true;manual_nested=mode=="manual_nested";original_throw=mode=="manual_throw";
  try{mp4_camera_manual_render_hook(reinterpret_cast<void*>(0x222),nullptr);assert(!original_throw);}catch(int x){assert(x==8&&original_throw);}assert(manual_originals==1&&mp4_render_hold_readers_idle()&&!Mp4RenderHoldOriginal::current&&!suspensions&&private_time&&private_rng);assert(automatic_originals==(manual_nested?1:0));original_throw=false;private_time=private_rng=false;mp4_gpu_auxiliary_host={};cleanup();}
 else if(mode.rfind("direct_",0)==0||mode.rfind("frame_",0)==0){
  direct_monitor=true;aux_setup();submit_context=mode!="direct_no_submit";original_throw=mode=="direct_throw";
  bad_frame=mode=="direct_bad_frame";bad_context=mode=="direct_bad_context";
  if(mode=="direct_without_frame"){mp4_render_camera_hook({srp.native_context},reinterpret_cast<void*>(0x222),nullptr);assert(!automatic_originals);}
  else{
   Mp4RenderHoldReader main_entry(Mp4RenderHoldKind::stack,mp4_scene_host.source.camera,srp.native_context,reinterpret_cast<uintptr_t>(automatic_original));main_entry.candidate=true;
   Mp4RenderHoldFrame frame;
   if(mode=="frame_bad_physical")srp.physical_valid=false;
   if(mode=="frame_wrong_context")srp.physical_context=reinterpret_cast<void*>(0x999);
   const bool entered=frame_enter(frame);
   if(mode=="frame_bad_physical"||mode=="frame_wrong_context"){assert(!entered);}
   else{
    assert(entered);Mp4RenderHoldFrameOrigin actual{};assert(mp4_render_hold_frame_current(&actual)&&actual.serial&&actual.physical_frame==14);
    if(mode=="frame_no_reentry"){Mp4RenderHoldFrame second;assert(!frame_enter(second));}
    else if(mode=="frame_stale_physical"){++srp.physical_receipt;assert(!mp4_render_hold_frame_current(&actual));}
    else{
     Mp4MonitorCameraOrigin origin{};assert(monitor_origin(reinterpret_cast<void*>(0x222),&origin));
     if(mode=="direct_held_current")automatic_action=[&](){assert(mp4_render_hold_current(4,9)&&!mp4_render_hold_job_quiet(4,9)&&private_time&&private_rng);};
     private_time=private_rng=true;
     try{mp4_render_camera_hook({srp.native_context},reinterpret_cast<void*>(0x222),nullptr);assert(!original_throw);}catch(int x){assert(original_throw&&x==7);}
     Mp4MonitorCameraReceipt receipt{};const bool completed=mp4_render_hold_monitor_completed(origin,&receipt);
     const bool rejected=bad_frame||bad_context;
     assert(automatic_originals==(rejected?0:1)&&!manual_originals&&!suspensions);
     assert(completed==(!rejected&&!original_throw&&submit_context));
     if(completed)assert(receipt.context_entries==1&&receipt.submits==1&&receipt.returned&&receipt.origin.route==Mp4MonitorCameraRoute::urp_direct);
     if(mode=="direct_duplicate"){mp4_render_camera_hook({srp.native_context},reinterpret_cast<void*>(0x222),nullptr);assert(automatic_originals==1&&!mp4_render_hold_monitor_completed(origin,&receipt));}
     if(mode=="direct_wrong_receipt"){++origin.frame_serial;assert(!mp4_render_hold_monitor_completed(origin,&receipt));}
     private_time=private_rng=false;original_throw=false;automatic_action={};
    }
   }
  }
  assert(!Mp4RenderHoldFrame::current&&!Mp4RenderHoldOriginal::current);mp4_gpu_auxiliary_host={};cleanup();
 }
 else if(mode.rfind("consumers_",0)==0){
  mp4_scene_host.releasing=mode!="consumers_not_final";
  if(mode=="consumers_slots"){actor_slots_idle=false;assert(!mp4_graphics_program_consumers_retired(4,9));actor_slots_idle=true;mp4_equipment_targets.material_count=1;mp4_equipment_targets.materials[0].slot_displaced=true;assert(!mp4_graphics_program_consumers_retired(4,9));mp4_equipment_targets.materials[0].slot_displaced=false;}
  if(mode=="consumers_callback"){callback_idle=false;assert(!mp4_graphics_program_consumers_retired(4,9));callback_idle=true;mono_idle=false;assert(!mp4_graphics_program_consumers_retired(4,9));mono_idle=true;}
  if(mode=="consumers_request"){request_idle=false;assert(!mp4_graphics_program_consumers_retired(4,9));request_idle=true;}
  if(mode=="consumers_readback"){idoly_mp4_runtime::game.work.readback_active=true;assert(!mp4_graphics_program_consumers_retired(4,9));idoly_mp4_runtime::game.work.readback_active=false;}
  if(mode=="consumers_bank"){bank_idle=false;assert(!mp4_graphics_program_consumers_retired(4,9));bank_idle=true;}
  if(mode=="consumers_old_activity"){mp4_render_hold_gpu_activity();assert(!mp4_graphics_program_consumers_retired(4,9));mp4_frame_capture_host.active=true;}
  if(mode=="consumers_gpu_wait"||mode=="consumers_after_frame_finish"){mp4_frame_capture_host.active=true;mp4_render_hold_gpu_activity();frame_gpu_retired=false;assert(!mp4_graphics_program_consumers_retired(4,9));frame_gpu_retired=true;}
  if(mode=="consumers_same_job")assert(!mp4_graphics_program_consumers_retired(4,10)&&!mp4_graphics_program_consumers_retired(5,9));
  assert(mp4_graphics_program_consumers_retired(4,9)==mp4_scene_host.releasing);
  if(mode=="consumers_after_frame_finish"){mp4_frame_capture_host.active=false;assert(mp4_graphics_program_consumers_retired(4,9));}
  cleanup();
 }
 else if(mode=="gpu_checkpoint_wait"){mp4_frame_capture_host.active=true;frame_gpu_retired=false;mp4_render_hold_gpu_activity();assert(!mp4_render_hold_gpu_checkpoint(9)&&mp4_render_hold_state.retiring);render_intent=true;auto_call();assert(!automatic_originals);frame_gpu_retired=true;assert(mp4_render_hold_gpu_checkpoint(9));mp4_frame_capture_host.active=false;cleanup();}
 else if(mode=="activity_invalidates"){mp4_frame_capture_host.active=true;mp4_render_hold_gpu_activity();assert(mp4_render_hold_gpu_checkpoint(9));auto old=mp4_render_hold_state.gpu_receipt;mp4_render_hold_gpu_activity();assert(!mp4_render_hold_state.gpu_receipt);assert(mp4_render_hold_gpu_checkpoint(9)&&mp4_render_hold_state.gpu_receipt!=old);mp4_frame_capture_host.active=false;cleanup();}
 else if(mode=="scope_not_retired"){assert(!mp4_render_hold_scope_checkpoint(4,9)&&!mp4_render_hold_state.cleanup_receipt);cleanup();}
 else if(mode=="logical_not_restored"){auto&b=mp4_scene_source_bootstrap;b.scope.transferred_value=b.pre_released=true;b.retired=b.withdrawn=254;mp4_scene_host.released=15;idoly_mp4_runtime::game.primary_started=true;assert(!mp4_render_hold_scope_checkpoint(4,9));mp4_scene_host.logical_checkpoint=true;assert(mp4_render_hold_scope_checkpoint(4,9)&&mp4_render_hold_retire(9)==Mp4SceneResult::ok);}
 else if(mode=="full_capture_abort_before_primary"){auto&b=mp4_scene_source_bootstrap;b.scope.transferred_value=b.pre_released=true;b.retired=b.withdrawn=254;mp4_scene_host.released=15;assert(mp4_render_hold_scope_checkpoint(4,9)&&mp4_render_hold_retire(9)==Mp4SceneResult::ok);}
 else if(mode=="no_work_requires_cleanup"){assert(!mp4_render_hold_gpu_checkpoint(9));cleanup();}
 else if(mode=="readback_wait"){idoly_mp4_runtime::game.work.readback_active=true;mp4_scene_host.released=15;mp4_scene_source_bootstrap.scope.clean_value=true;assert(!mp4_render_hold_scope_checkpoint(4,9));idoly_mp4_runtime::game.work.readback_active=false;cleanup();}
 else if(mode=="handoff"){auto old=mp4_render_hold_state.serial;mp4_render_hold_handoff(mp4_scene_host.source.player);assert(!__atomic_load_n(&mp4_render_hold_state.published,__ATOMIC_SEQ_CST)&&mp4_render_hold_state.active&&mp4_render_hold_state.handoff.load()==old);auto_call();assert(automatic_originals==1);cleanup();acquire();assert(mp4_render_hold_state.serial>old);auto expected=old;(void)__atomic_compare_exchange_n(&mp4_render_hold_state.published,&expected,uint64_t(0),false,__ATOMIC_SEQ_CST,__ATOMIC_SEQ_CST);assert(mp4_render_hold_job_quiet(4,9));cleanup();}
 else if(mode=="abandon"){mp4_render_hold_abandon_job(9);assert(mp4_render_hold_state.active&&!__atomic_load_n(&mp4_render_hold_state.published,__ATOMIC_SEQ_CST));auto_call();assert(automatic_originals==1);cleanup();}
 else if(mode=="handoff_wrong_receiver"){mp4_render_hold_handoff(reinterpret_cast<void*>(0x999));assert(mp4_render_hold_job_quiet(4,9));cleanup();}
 else if(mode=="old_stack_cannot_forward"){Mp4RenderHoldReader reader(Mp4RenderHoldKind::stack,mp4_scene_host.source.camera,srp.native_context,reinterpret_cast<uintptr_t>(automatic_original));mp4_render_hold_handoff(mp4_scene_host.source.player);Mp4RenderHoldOriginal original;assert(!original.enter(automatic_original,{srp.native_context},mp4_scene_host.source.camera));assert(mp4_render_hold_retire(9)==Mp4SceneResult::waiting);}
 else if(mode=="wrong_job"){assert(mp4_render_hold_acquire(4,10)==Mp4SceneResult::stale&&!mp4_render_hold_gpu_checkpoint(10)&&mp4_render_hold_retire(10)==Mp4SceneResult::waiting);cleanup();}
 else if(mode=="frontend_withdraw"){frontends_ok=false;auto_call();assert(!automatic_originals&&!mp4_render_hold_job_quiet(4,9));frontends_ok=true;cleanup();}
 else if(mode=="reader_overflow"){mp4_render_hold_state.readers[0]=~uint64_t(0);{Mp4RenderHoldReader reader(Mp4RenderHoldKind::stack,nullptr,nullptr,0);assert(mp4_render_hold_state.untracked.load());}mp4_render_hold_state.readers[0]=0;assert(!mp4_render_hold_readers_idle()&&mp4_render_hold_retire(9)==Mp4SceneResult::waiting);mp4_render_hold_handoff(mp4_scene_host.source.player);assert(!__atomic_load_n(&mp4_render_hold_state.published,__ATOMIC_SEQ_CST));}
 else assert(false);
 }
 std::cout<<mode<<" PASS\n";
}
