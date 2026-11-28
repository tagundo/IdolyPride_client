int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];setup();Mp4PausedImageHost h{};
 if(mode=="missing_provider"){assert(mp4_paused_image_capture(h,mp4_scene_host.source,9,&held_gpu,held_fence,production_provider,nullptr,preservation_provider)==mp4frame::Result::invalid&&!h.configured);return 0;}
 if(mode=="capture_root_failure")fail_root=true;
 if(mode=="empty_capture")put(controller,160,static_cast<void*>(nullptr));
 if(mode=="not_held")held_gpu=false;
 if(mode=="queue_busy")idle=false;
 if(mode=="not_configured")mp4_scene_host.configured=7;
 if(mode=="foreign_epoch")mp4_scene_host.source.generation=8;
 const auto source=Mp4SceneWitness{7,ref(controller),ref(camera),reinterpret_cast<void*>(1)};
 auto result=mp4_paused_image_capture(h,source,9,&held_gpu,held_fence,production_provider,alias_provider,preservation_provider);
 if(mode=="capture_root_failure"||mode=="not_held"||mode=="queue_busy"||mode=="not_configured"||mode=="foreign_epoch"){
  assert(result==(mode=="capture_root_failure"?mp4frame::Result::failed:mp4frame::Result::unsupported)&&field_writes==0&&allocations==0);
  assert(h.scope.release()==mp4frame::Result::ok&&mp4_paused_image_finish(h,true)&&roots.empty());return 0;
 }
 assert(result==mp4frame::Result::ok&&h.original_capture==(mode=="empty_capture"?nullptr:ref(original)));
 assert(!mp4_paused_image_finish(h,true)); // No fake cleanup from an active scope.
 if(mode=="foreign_slot"){put(controller,160,ref(foreign));assert(!mp4_paused_image_capture_slot(&h,ref(original),nullptr)&&!field_writes);return 0;}
 if(mode=="foreign_replacement"){assert(!mp4_paused_image_capture_slot(&h,ref(original),ref(foreign))&&!field_writes);return 0;}
 if(mode=="handoff_slot"){current_ok=false;assert(!mp4_paused_image_capture_slot(&h,ref(original),nullptr)&&!field_writes);return 0;}
 assert(h.scope.prepare()==mp4frame::Result::waiting&&copies==1&&field_writes==0);
 assert(h.scope.prepare()==mp4frame::Result::waiting&&copies==1&&field_writes==0);
 copy_ready=true;assert(h.scope.prepare()==mp4frame::Result::ok&&field_writes==1&&global_writes==0);
 if(mode=="observed_private_handoff"){
  put(controller,160,ref(private_wrapper));assert(h.scope.observe_export_capture(ref(private_wrapper))==mp4frame::Result::ok);
  current_ok=false;h.scope.abandon();aliases_clear=false;
  assert(h.scope.release()==mp4frame::Result::ok&&preserves==2&&!destroys&&field_writes==1);
  assert(mp4_paused_image_finish(h,true)&&roots.empty());return 0;
 }
 if(mode=="preserve_handoff"){
  current_ok=false;h.scope.abandon();preserve_good=false;
  assert(h.scope.release()==mp4frame::Result::waiting&&preserves==1&&!destroys);
  preserve_good=true;assert(h.scope.release()==mp4frame::Result::ok&&preserves==2);
  assert(mp4_paused_image_finish(h,true)&&roots.empty());return 0;
 }
 put(controller,160,ref(private_wrapper));
 if(mode=="unowned")production_good=false;
 if(mode=="partial_production")owned_good=false;
 if(mode=="capture_adoption_root_failure"){
  const auto count=roots.size();fail_root=true;
  assert(h.scope.restore()==mp4frame::Result::stale&&field_writes==1&&!h.capture_root&&!h.texture_root&&roots.size()==count);
  fail_root=false;
 }
 if(mode=="unowned"){assert(h.scope.restore()==mp4frame::Result::stale&&field_writes==1&&!destroys);return 0;}
 assert(h.scope.restore()==mp4frame::Result::waiting&&copies==2&&field_writes==2&&global_writes==0);
 assert(h.scope.restore()==mp4frame::Result::ok&&h.scope.verify_held()==mp4frame::Result::ok);
 if(mode=="alias_wait")aliases_clear=false;
 if(mode=="alias_wait"){assert(h.scope.release()==mp4frame::Result::waiting&&!destroys);aliases_clear=true;}
 if(mode=="native_swap"){put(private_rt,16,uintptr_t(999));assert(h.scope.release()==mp4frame::Result::waiting&&!destroys);put(private_rt,16,uintptr_t(202));}
 if(mode=="deferred_destroy")defer_destroy=true;
 if(mode=="throw_destroy")throw_destroy=true;
 if(mode=="deferred_destroy"||mode=="throw_destroy"){
  if(throw_destroy){try{h.scope.release();assert(false);}catch(int code){assert(code==41);}}
  else assert(h.scope.release()==mp4frame::Result::waiting);
  assert(destroys==1&&h.scope.release()==mp4frame::Result::waiting&&destroys==1);
  put(private_rt,16,uintptr_t(0));
 }
 assert(h.scope.release()==mp4frame::Result::ok&&destroys==1&&global_writes==0);
 assert(mp4_paused_image_finish(h,true)&&roots.empty());
 if(mode=="normal"){
  assert(mp4_paused_image_capture(h,source,9,&held_gpu,held_fence,production_provider,alias_provider,preservation_provider)==mp4frame::Result::ok);
  assert(h.scope.restore()==mp4frame::Result::ok&&h.scope.release()==mp4frame::Result::ok);
  assert(mp4_paused_image_finish(h,true)&&roots.empty()&&copies==2&&destroys==1);
 }
}
