int main(int argc,char**argv){assert(argc==2);setup();std::string kind=argv[1];Mp4DormantAnimatorImage image{};
 if(kind=="off_thread")thread_ok=false;
 if(kind=="source_changed")source_ok=false;
 if(kind=="bad_pin")pins_ok=false;
 if(kind=="controller")controller=true;
 if(kind=="avatar")avatar=true;
 if(kind=="bound")bound=true;
 if(kind=="root_motion")root_motion=true;
 if(kind=="keep_state")keep_state=true;
 if(kind=="write_defaults")write_defaults=true;
 if(kind=="graph")graph_present=true;
 if(kind=="mode")mode=2;
 if(kind=="culling")culling=2;
 if(kind=="native_swap")swap_native=true;
 if(kind=="bindings")put(native,mp4world::AnimatorBindingLayout::count,uint64_t(1));
 if(kind=="capacity")put(native,mp4world::AnimatorBindingLayout::capacity,uint64_t(16386));
 if(kind=="invalid_storage")put(native,mp4world::AnimatorBindingLayout::capacity,uint64_t(2));
 if(kind=="job_group")put(native,0x238,uint64_t(17));
 if(kind=="job_version")put(native,0x240,int32_t(7));
 if(kind!="normal"&&kind!="active_transition"){
  assert(!mp4_dormant_animator_read(&source_ok,current,ref(animator),ref(go),&image)&&!image.component);
  if(kind=="off_thread"||kind=="source_changed"||kind=="bad_pin")assert(queries==0);
  return 0;
 }
 assert(mp4_dormant_animator_read(&source_ok,current,ref(animator),ref(go),&image));
 Mp4DormantAnimatorImage next{};active=true;
 // This models the separate original SetActive native receipt. The helper
 // itself performs no lifecycle/Animator setters and cannot grant one.
 assert(mp4_dormant_animator_read(&source_ok,current,ref(animator),ref(go),&next));
 assert(mp4_dormant_animator_same(image,next,true)&&!mp4_dormant_animator_same(image,next,false));
 active=false;assert(mp4_dormant_animator_read(&source_ok,current,ref(animator),ref(go),&next)&&mp4_dormant_animator_same(image,next,false));
}
