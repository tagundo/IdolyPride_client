int add_calls=0,invoke_calls=0,frame_calls=0;bool source_ok=true,allow_root_add=false,original_throws=false,nested_frame=false,source_handoff=false,clear_during_callback=false;uint64_t mono_caller=0;Mp4SrpDispatchHost*active_host=nullptr;Blob*current_action=nullptr,*camera_array=nullptr;
bool source_current(void*,uint64_t epoch,uint64_t job){return live&&source_ok&&epoch==7&&job==9;}
bool dispatch_held(void*){return held_now;}
bool root_add(void*,void*self,void*action,uintptr_t,uint64_t*receipt){*receipt=allow_root_add&&self==controller&&action==current_action?88:0;return *receipt;}
mp4actor::RandomState random_state{};
bool mono_current(void*){return source_ok;}bool mono_thread(){return thread;}
void rng_get(mp4actor::RandomState*out,mp4actor::Method*){*out=random_state;}void rng_set(const mp4actor::RandomState*value,mp4actor::Method*){random_state=*value;}
void original_add(void*self,void*action,Method*){
 assert(self==controller);++add_calls;if(original_throws)throw std::runtime_error("actual add");
 void*backing=nullptr;int32_t count=0;uint32_t version=0;assert(mp4_actor_field(queue,16,backing)&&mp4_actor_field(queue,24,count)&&mp4_actor_field(queue,28,version));
 if(size_t(count)==memory[backing]->items.size()){auto*replacement=array(static_cast<Class*>(object_class(backing)),{});replacement->items.resize(count?size_t(count)*2:4);for(int32_t i=0;i<count;++i)replacement->items[size_t(i)]=memory[backing]->items[size_t(i)];backing=replacement;put(queue,16,backing);}
 memory[backing]->items[size_t(count)]=action;put(queue,24,count+1);put(queue,28,version+1);
}
void original_invoke(void*self,Method*method){
 assert(self==controller&&method==reinterpret_cast<Method*>(0xdeadbeef));++invoke_calls;if(original_throws)throw std::runtime_error("actual invoke");
 void*backing=nullptr;uint32_t version=0;assert(mp4_actor_field(queue,16,backing)&&mp4_actor_field(queue,28,version));
 for(auto&item:memory[backing]->items)item=nullptr;put(queue,24,int32_t(0));put(queue,28,version+1);
}
void original_frame(void*self,Mp4RenderContext context,void*cameras,Method*method){
 assert(self==controller);++frame_calls;if(original_throws)throw std::runtime_error("actual frame");
 if(clear_during_callback)assert(active_host&&!mp4_srp_dispatch_clear(*active_host));
 if(source_handoff){assert(active_host);mp4_srp_dispatch_withdraw(*active_host);source_ok=false;}
 if(nested_frame){nested_frame=false;mp4_srp_dispatch_frame(original_frame,self,context,cameras,method,777);}
 if(mp4_array_length(cameras)){put(controller,148,uint8_t(0));mp4_srp_dispatch_invoke(original_invoke,self,reinterpret_cast<Method*>(0xdeadbeef),666);}
}
void actor_late(void*,mp4actor::Method*){mp4_srp_dispatch_add(original_add,controller,current_action,nullptr,mono_caller);}
void other_late(void*,mp4actor::Method*){actor_late(nullptr,nullptr);}
void run_mono(void*receiver,bool wrong=false){mp4actor::MonoReceiver route{receiver,mp4actor::MonoPhase::actor_late};assert(mp4_actor_mono_gate.publish({mono_current,mono_thread,rng_get,rng_set},&route,7,&route,1)&&mp4_actor_mono_gate.hold(7)&&mp4_actor_mono_gate.grant(7,1));mp4_actor_mono_gate.invoke(route.phase,wrong?other_late:mp4_actor_late_original,receiver,nullptr);mp4_actor_mono_gate.revoke(7);}
int main(int argc,char**argv){assert(argc==2);const std::string mode=argv[1];initialize_source();mp4_actor_late_original=actor_late;
 Mp4SrpControllerHost state;Mp4SrpDispatchHost host;active_host=&host;auto*ctx=&host;auto render_context=Mp4RenderContext{reinterpret_cast<void*>(0x1234)};
 camera_array=array(cls("UnityEngine.Camera[]",array_class),{camera});current_action=callback(action_class,foot,105,method_foot);mono_caller=image_base+mp4_srp_foot_add_return;
 if(mode=="unheld_capture"){held_now=false;assert(!mp4_srp_dispatch_capture(host,state,current_scene,ctx,7,9,source_current,dispatch_held,root_add));assert(roots.empty());return 0;}
 assert(mp4_srp_dispatch_capture(host,state,current_scene,ctx,7,9,source_current,dispatch_held,root_add));assert(mp4_srp_dispatch_current(host));
 if(mode=="mono_add"||mode=="wrong_caller"||mode=="wrong_mono"||mode=="wrong_extension"||mode=="mono_aabb"){
  if(mode=="wrong_caller")++mono_caller;
  if(mode=="mono_aabb")current_action=callback(action_class,actor,104,method_aabb);
  void*receiver=actor;
  if(mode=="wrong_extension"){auto*other=obj(actor_class);auto*l=list(queue_class,array(array_class,{}));put(other,64,static_cast<void*>(l));actor_array->items.push_back(other);put(actor_list,24,int32_t(2));receiver=other;}
  run_mono(receiver,mode=="wrong_mono");assert(add_calls==1);assert(state.lease.poisoned()==(mode!="mono_add"));
 }else if(mode=="root_add"||mode=="unknown_add"||mode=="add_exception"){
  allow_root_add=mode=="root_add";original_throws=mode=="add_exception";bool threw=false;
  try{mp4_srp_dispatch_add(original_add,controller,current_action,nullptr,333);}catch(const std::runtime_error&){threw=true;}
  assert(add_calls==1&&threw==(mode=="add_exception"));assert(state.lease.poisoned()==(mode!="root_add"));
 }else if(mode=="add_frontend"){
  mp4_srp_add_precull_original=original_add;mp4_srp_add_precull_hook(controller,current_action,nullptr);assert(add_calls==1&&state.lease.poisoned());
 }else if(mode=="invoke_frontend"){
  mp4_srp_invoke_precull_original=original_invoke;mp4_srp_invoke_precull_hook(controller,reinterpret_cast<Method*>(0xdeadbeef));assert(invoke_calls==1&&state.lease.poisoned());
 }else if(mode=="unowned_invoke"){
  mp4_srp_dispatch_invoke(original_invoke,controller,reinterpret_cast<Method*>(0xdeadbeef),333);assert(invoke_calls==1&&state.lease.poisoned());
 }else if(mode=="held_retry"){
  idoly_mp4_runtime::render_allowed=false;mp4_srp_dispatch_frame(original_frame,controller,render_context,camera_array,nullptr,333);assert(!frame_calls&&!invoke_calls&&!state.lease.poisoned());
 }else if(mode=="offthread"){
  thread=false;mp4_srp_dispatch_add(original_add,controller,current_action,nullptr,333);thread=true;assert(add_calls==1&&mp4_srp_dispatch_foreign_dirty.load()&&!mp4_srp_dispatch_current(host));
 }else if(mode=="withdraw"){
  const size_t retained=roots.size();mp4_srp_dispatch_withdraw(host);assert(roots.size()==retained);mp4_srp_dispatch_add(original_add,controller,current_action,nullptr,333);assert(add_calls==1&&!state.lease.poisoned());
 }else{
  if(mode=="prewarm"){idoly_mp4_runtime::job.auto_started=false;idoly_mp4_runtime::job.prewarm_requested=true;}
  if(mode=="no_selected")camera_array->items.clear();
  if(mode=="duplicate_selected")camera_array->items.push_back(camera);
  if(mode=="frame_exception")original_throws=true;
  if(mode=="nested_frame")nested_frame=true;
  if(mode=="handoff")source_handoff=true;
  if(mode=="callback_clear")clear_during_callback=true;
  bool threw=false;try{if(mode=="frame_frontend"){mp4_srp_begin_frame_original=original_frame;mp4_srp_begin_frame_hook(controller,render_context,camera_array,nullptr);}else mp4_srp_dispatch_frame(original_frame,controller,render_context,camera_array,nullptr,333);}catch(const std::runtime_error&){threw=true;}
  assert(threw==(mode=="frame_exception"));
  if(mode=="no_selected"){assert(!frame_calls&&!invoke_calls&&!state.lease.poisoned());}
  else if(mode=="duplicate_selected"||mode=="frame_exception"||mode=="nested_frame"||mode=="handoff"){assert(state.lease.poisoned());}
  else{
   assert(frame_calls==1&&invoke_calls==1&&!state.lease.poisoned()&&host.have_frame&&host.frame_receipt==1);
   mp4_srp_dispatch_frame(original_frame,controller,render_context,camera_array,nullptr,333);assert(frame_calls==1&&invoke_calls==1);
   uint64_t receipt=0;const bool prewarm=mode=="prewarm";
   assert(!mp4_srp_dispatch_draw_receipt(host,9,0,prewarm,render_context,camera,0,&receipt)&&!receipt);
   assert(mp4_srp_dispatch_draw_receipt(host,9,0,prewarm,render_context,camera,22,&receipt)&&receipt==1);
   assert(mp4_srp_dispatch_draw_receipt(host,9,0,prewarm,render_context,camera,22,&receipt)&&receipt==1);
   assert(!mp4_srp_dispatch_draw_receipt(host,9,0,prewarm,render_context,camera,23,&receipt)&&!receipt);
   assert(!mp4_srp_dispatch_draw_receipt(host,10,0,prewarm,render_context,camera,22,&receipt)&&!receipt);
   if(mode=="stale_draw"){idoly_mp4_runtime::native_engine_clock.value=1;assert(!mp4_srp_dispatch_draw_receipt(host,9,0,prewarm,render_context,camera,22,&receipt)&&!receipt);}
   if(mode=="next_tick"){idoly_mp4_runtime::native_engine_clock.value=1;mp4_srp_dispatch_frame(original_frame,controller,render_context,camera_array,nullptr,333);assert(frame_calls==2&&invoke_calls==2&&host.frame_receipt==2);}
  }
 }
 if(!state.lease.poisoned()&&mode!="offthread"&&mode!="withdraw")assert(state.lease.restore());
 assert(mp4_srp_dispatch_clear(host)&&roots.empty()&&!mp4_srp_entered&&!mp4_srp_dispatch_published.load());
}
