static std::thread background;
static bool callback_reentry_test(){auto*h=static_cast<Mp4CaptureAliasHost*>(alias_context);return !mp4_capture_alias_unreferenced(h,&wrapper,&texture,401)&&!mp4_capture_alias_release(*h)&&release_count==0;}
static void target_callout(){if(ctor_withdraw)produced=false;}
static bool remove_original(void*p,const Mp4CaptureTarget40*t,const Method*){
 assert(producer.gate.cancel_on_thread()&&p==&component&&set.count==1);uint32_t value=0;memcpy(&value,t->bytes,4);assert(value==401);
 ++remove_calls;
 if(reenter){assert(!mp4_capture_alias_unreferenced(alias_context,&wrapper,&texture,401));++reentry_denied;assert(!mp4_capture_alias_release(*static_cast<Mp4CaptureAliasHost*>(alias_context))&&release_count==0);}
 if(do_throw)throw std::runtime_error("typed-original-failed");
 clear_set();
 if(inject_after)actual_add(false);
 if(foreign_during_remove){background=std::thread([](){on_thread=false;Mp4CaptureQueueAdd lease;assert(mp4_capture_queue_add_enter(lease,&component));add_original();});
  while(!producer.journal.withdrawn())std::this_thread::yield();assert(set.count==0);}
 return true;
}
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];Mp4CaptureAliasHost host;int ctx=1;controller.field168=&component;
 assert(mp4_capture_queue_bind(producer,production,&ctx,query_produced,true));assert(retains==1);
 if(mode=="bind_source")source_available=false;
 if(mode=="bind_pending")add_original();
 if(mode=="bind_queue")queue_empty=false;
 if(mode=="bind_queue_changed")queue_stable=false;
 if(mode=="bind_root1")fail_root=retains+1;
 if(mode=="bind_root2")fail_root=retains+2;
 if(mode=="bind_root3")fail_root=retains+3;
 bool bound=mp4_capture_alias_bind(host,{9,&controller},17,&ctx,query_unwound,query_retired,query_produced,producer,query_detached,query_consumers);
 if(mode.rfind("bind_",0)==0){assert(!bound&&!host.bound);assert(mp4_capture_queue_finish(producer));assert(release_count==retains-(fail_root?1:0));return 0;}
 assert(bound&&retains==4);alias_context=&host;const int source_reads_before=controller_reads;
 const bool needs_pending=mode=="pending"||mode=="reentry"||mode=="throws"||mode=="foreign"||mode=="prefix"||mode=="post_foreign"||mode=="ctor_withdraw"||mode=="foreign_same_target"||mode=="foreign_during_remove";
 if(needs_pending)actual_add(true);
 if(mode=="partial_empty"||mode=="partial_pending")complete_birth=false;
 if(mode=="partial_pending")add_original();
 if(mode=="foreign_same_target")actual_add(false);
 if(mode=="withdrawn_empty"){actual_add(true);actual_add(false);clear_set();}
 if(mode=="queue")queue_empty=false;
 if(mode=="queue_changed")queue_stable=false;
 if(mode=="unwound")unwound=false;
 if(mode=="owner_still_aliases")detached_receipt=false;
 if(mode=="foreign_already_consumed")consumer_receipt=false;
 if(mode=="handoff_still_aliases"){source_available=false;source_current=false;detached_receipt=false;}
 if(mode=="gpu")retired=false;
 if(mode=="producer")produced=false;
 if(mode=="native_changed")component.native=999;
 if(mode=="texture_changed")texture.native=999;
 if(mode=="handoff"){source_available=false;source_current=false;}
 if(mode=="foreign")single_owned=false;
 if(mode=="prefix")prefix_current=false;
 if(mode=="post_foreign")inject_after=true;
 if(mode=="ctor_withdraw")ctor_withdraw=true;
 if(mode=="reentry")reenter=true;
 if(mode=="throws")do_throw=true;
 if(mode=="callout_reentry")callback_reentry=true;
 if(mode=="consumers_callout_add")consumer_add=true;
 if(mode=="foreign_during_remove")foreign_during_remove=true;
 if(mode=="thread")on_thread=false;
 if(mode=="lost_root")roots[host.roots[1]]=nullptr;
 if(mode=="producer_epoch")++producer.epoch;
 if(mode=="producer_job")++producer.job;
 if(mode=="producer_unpublished")assert(mp4_capture_queue_finish(producer));
 Mp4CaptureQueueReader reader;
 if(mode=="reader_before_load")assert(reader.begin());
 if(mode=="reader_old_pointer"){assert(reader.begin()&&reader.published()==&producer);assert(!mp4_capture_queue_finish(producer));}
 idoly_mp4_capture_queue::Gate::Add held;
 if(mode=="gate_busy")held.enter(producer.gate);
 bool okay=mp4_capture_alias_unreferenced(&host,&wrapper,&texture,401);
 if(background.joinable())background.join();
 const bool expected=mode=="empty"||mode=="callout_reentry"||mode=="partial_empty"||mode=="pending"||mode=="reentry"||mode=="handoff";
 assert(okay==expected);assert(controller_reads==source_reads_before&&forbidden_controller_reads==0);
 if(mode=="pending"||mode=="reentry"||mode=="throws"||mode=="post_foreign"||mode=="foreign_during_remove")assert(remove_calls==1);else assert(remove_calls==0);
 if(mode=="reentry")assert(reentry_denied==1);
 if(mode=="throws")assert(host.invalid&&!host.busy);
 if(mode=="lost_root")roots[host.roots[1]]=&renderer;
 if(mode=="producer_epoch")--producer.epoch;
 if(mode=="producer_job")--producer.job;
 on_thread=true;held.leave();reader.leave();
 assert(mp4_capture_alias_release(host));if(producer.bound)assert(mp4_capture_queue_finish(producer));assert(release_count==4&&!host.bound&&roots.empty());return 0;
}
