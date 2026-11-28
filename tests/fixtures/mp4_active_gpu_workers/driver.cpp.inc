void source_ready(){uint64_t r=99;assert(mp4_gpu_initial_source_advance(4,9,&r)==Mp4SceneResult::waiting&&r==0);assert(render_engine.executes==1&&mp4_gpu_fence_host.sequence==1&&mp4_render_hold_state.activity==1);render_engine.passed=true;assert(mp4_gpu_initial_source_advance(4,9,&r)==Mp4SceneResult::ok&&r);assert(render_engine.executes==1&&render_engine.disposes==0);assert(mp4_gpu_initial_source_fenced(4,9));}
void production_ready(){auto&h=mp4_frame_capture_host;h.production_ready=h.production.configured=h.queue.bound=true;h.queue.production=&h.production;mp4_capture_queue_published=&h.queue;mp4_capture_production_published=&h.production;mp4cq::Api api{game_call,queue_retained,queue_request,queue_update,queue_resource,mp4_capture_queue_observe};assert(h.queue.journal.bind(api,&h,h.queue.component,4,9,{1,2,3}));}
void frame_ready(){production_ready();auto&h=mp4_frame_capture_host;h.operation=h.production.operation_serial=17;h.production.publication_returned=true;h.production.publication_receipt={4,9,17,h.source.controller,nullptr,nullptr,0,true,true};auto&w=idoly_mp4_runtime::game.capture_workers_;w.sequence=w.request_returned=w.readback_issued=w.readback_returned=3;w.operation=17;}
void draw_issue(){auto&h=mp4_gpu_fence_host;assert(h.ledger.retire_sequence(9,1));h.retired=1;assert(h.ledger.begin_draw(9,2,{reinterpret_cast<void*>(0x777)}));h.sequence=2;h.draw=true;h.active_token=31;}
void draw_return(){auto&h=mp4_gpu_fence_host;assert(h.ledger.submit_returned(9,2,{reinterpret_cast<void*>(0x777)})==Result::waiting);assert(h.ledger.end_draw(9,2));h.draw=false;h.last_token=h.active_token;h.active_token=0;}
void aux_return(){auto&h=mp4_gpu_auxiliary_host;h.source=4;h.epoch=9;h.configured=h.ledger.configure(aux_engine.api,aux_engine.pins,9);assert(h.configured&&h.ledger.begin_auxiliary(9,1));assert(h.ledger.auxiliary_returned(9,1)==Result::waiting&&h.ledger.end_auxiliary(9,1));h.sequence=1;h.last_token=mp4_gpu_auxiliary_dispatched_ticket=52;}
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];uint64_t receipt=99;
 auto&hold=mp4_render_hold_state;hold.source=4;hold.job=9;hold.serial=hold.published=1;hold.active=hold.acquired=true;
 if(mode=="initial_no_cpu"){source_cpu_current=false;assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::stale&&!receipt&&!render_engine.executes);}
 else if(mode=="initial_no_images"){mp4_scene_host.captured=7;assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::stale&&!receipt&&!render_engine.executes);}
 else if(mode=="initial_too_late"){mp4_scene_host.prepared=1;assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::stale&&!receipt&&!render_engine.executes);}
 else if(mode=="initial_no_programme"){mp4_gpu_graphics_producers_closed=nullptr;assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::stale&&!receipt&&!render_engine.executes);}
 else if(mode=="initial_no_render_hold"){hold.acquired=false;assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::stale&&!receipt&&!render_engine.executes);}
 else if(mode=="initial_render_reader"){for(size_t i=0;i<3;++i){hold.readers[i]=1;assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::stale&&!receipt&&!render_engine.executes);hold.readers[i]=0;}}
 else if(mode=="initial_render_original"){Mp4RenderHoldOriginal::current=&hold;assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::stale&&!receipt&&!render_engine.executes);}
 else if(mode=="initial_render_frontends"){render_frontends=false;assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::stale&&!receipt&&!render_engine.executes);}
 else if(mode=="initial_render_handoff"){hold.handoff.store(hold.serial);assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::stale&&!receipt&&!render_engine.executes);}
 else if(mode=="initial_wait_once"){assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::waiting&&!receipt);assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::waiting&&!receipt&&render_engine.executes==1);render_engine.passed=true;assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::ok&&receipt&&render_engine.executes==1);}
 else if(mode=="initial_create_throw"){render_engine.create_throw=true;assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::stale&&!receipt&&render_engine.roots()==1);assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::stale&&!receipt&&render_engine.executes==0&&render_engine.roots()==1);}
 else if(mode=="initial_execute_throw"){render_engine.execute_throw=true;assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::stale&&!receipt&&render_engine.roots()==1);render_engine.execute_throw=false;render_engine.passed=true;assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::stale&&!receipt&&render_engine.executes==1);}
 else if(mode=="initial_source_lost_poll"){assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::waiting);render_engine.passed=true;gpu_query_action=[](){source_cpu_current=false;};assert(mp4_gpu_initial_source_advance(4,9,&receipt)==Mp4SceneResult::stale&&!receipt&&!mp4_initial_source_gpu_fence.completed&&render_engine.roots()==1);}
 else if(mode=="initial_no_work_is_not_fence"){assert(!mp4_gpu_active_workers_quiet(9)&&!render_engine.executes);}
 else if(mode=="initial_receipt_cannot_replace_ledger"){mp4_initial_source_gpu_fence={4,9,1,1,true,true,true};assert(!mp4_gpu_active_workers_quiet(9));}
 else {source_ready();
 if(mode=="baseline"){assert(mp4_gpu_active_workers_quiet(9));int e=render_engine.executes,d=render_engine.disposes;for(int i=0;i<5;++i)assert(mp4_gpu_active_workers_quiet(9));assert(render_engine.executes==e&&render_engine.disposes==d);draw_issue();draw_return();assert(mp4_gpu_active_workers_quiet(9));}
 else if(mode=="historical_no_old_roster"){source_cpu_current=source_key_current=false;assert(mp4_gpu_active_workers_quiet(9));}
 else if(mode=="production_empty"){production_ready();assert(mp4_gpu_active_workers_quiet(9)&&observe_calls>0);}
 else if(mode=="frame_complete"){frame_ready();assert(mp4_gpu_active_workers_quiet(9));}
 else if(mode=="readback_missing"){frame_ready();idoly_mp4_runtime::game.capture_workers_.readback_returned=0;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="readback_wrong_operation"){frame_ready();++idoly_mp4_runtime::game.capture_workers_.operation;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="adapter_active"){frame_ready();idoly_mp4_runtime::game.capture_request_running_=true;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="readback_active"){frame_ready();idoly_mp4_runtime::game.capture_workers_.readback_active=true;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="adapter_pending"){frame_ready();idoly_mp4_runtime::game.capture_pending_=true;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="publication_pending"){frame_ready();mp4_frame_capture_host.production.publication_request=17;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="publication_bad_return"){frame_ready();mp4_frame_capture_host.production.publication_returned=false;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="queue_nonempty"){production_ready();capture_set_count=1;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="queue_readers"){production_ready();mp4_capture_queue_readers=1;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="queue_untracked"){production_ready();mp4_capture_queue_untracked=1;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="queue_foreign"){production_ready();mp4_frame_capture_host.queue.journal.foreign();assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="queue_cancel"){production_ready();mp4cq::Gate::Cancel cancel;assert(cancel.try_enter(mp4_frame_capture_host.queue.gate)&&!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="queue_capture_tls"){production_ready();{mp4cq::Journal::Capture capture(mp4_frame_capture_host.queue.journal,nullptr,{},0,0);assert(!mp4_gpu_active_workers_quiet(9));}assert(mp4_gpu_active_workers_quiet(9));}
 else if(mode=="request_tls"){idoly_mp4_capture_publication::Request request;assert(!request.enter({},nullptr,nullptr,nullptr,0,0,0,0,0)&&!mp4_gpu_active_workers_quiet(9));request.finish();assert(mp4_gpu_active_workers_quiet(9));}
 else if(mode=="bank_tls"){mp4production::Bank bank;{auto scope=bank.update(nullptr,0,0);assert(!mp4_gpu_active_workers_quiet(9));}assert(mp4_gpu_active_workers_quiet(9));}
 else if(mode=="native_reader"){Mp4CaptureNativeReader reader;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="native_write_changed"){++mp4_capture_native_write_serial;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="native_untracked"){mp4_capture_native_untracked=1;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="render_depth"){mp4_owned_render_depth=1;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="unowned_render_depth"){mp4_unowned_render_depth=1;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="render_ticket"){mp4_owned_render_ticket_active=true;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="draw_pending"){draw_issue();render_engine.passed=false;draw_return();assert(!mp4_gpu_active_workers_quiet(9));render_engine.passed=true;assert(mp4_gpu_active_workers_quiet(9)&&render_engine.disposes==1);}
 else if(mode=="draw_active"){draw_issue();assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="draw_unknown"){mp4_gpu_fence_host.ledger.unknown_gpu_work(9);assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="draw_sealed"){mp4_gpu_fence_host.ledger.seal(9);mp4_gpu_fence_host.sealed=true;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="aux_pending"){aux_return();assert(!mp4_gpu_active_workers_quiet(9));aux_engine.passed=true;assert(mp4_gpu_active_workers_quiet(9)&&!aux_engine.disposes);}
 else if(mode=="aux_missing_dispatch"){aux_return();aux_engine.passed=true;mp4_gpu_auxiliary_dispatched_ticket=0;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="poll_reentry_native_write"){draw_issue();draw_return();gpu_query_action=[](){++mp4_capture_native_write_serial;};assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="poll_reentry_render_reader"){draw_issue();draw_return();gpu_query_action=[](){mp4_render_hold_state.readers[2]=1;};assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="render_hold_withdrawn"){hold.published=0;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="job_mismatch"){assert(!mp4_gpu_active_workers_quiet(10));}
 else if(mode=="foreign_production"){static Mp4CaptureProductionHost foreign;mp4_capture_production_published=&foreign;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="frame_sealed"){mp4_frame_capture_host.sealed=true;assert(!mp4_gpu_active_workers_quiet(9));}
 else if(mode=="offthread"){game_thread=false;assert(!mp4_gpu_active_workers_quiet(9));}
 else assert(false);
 }
 std::cout<<mode<<" PASS\n";
}
