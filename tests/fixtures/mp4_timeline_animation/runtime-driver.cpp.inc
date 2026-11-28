struct Fixture{void*asset_class=nullptr;bool infinite=false;Fixture(bool inf=false):infinite(inf){model=Model{};mp4_animation_runtime_dirty.store(false);mp4_animation_runtime_busy=false;mp4_animation_runtime_cursor=0;for(auto&r:mp4_animation_runtime_rows)r={};
 void*tree_class=alloc(32),*list_class=alloc(32);model.array_class=alloc(32);model.entry_class=alloc(32);model.runtime_class=alloc(32);asset_class=alloc(64);void*timeline_class=alloc(32),*track_class=alloc(32);
 model.tree=alloc(32,"UnityEngine.Timeline.IntervalTree`1",tree_class);model.list=alloc(32,"List",list_class);model.entry_array=alloc(32+8*24,"Entry[]",model.array_class);put(model.entry_array,24,size_t(8));put(model.tree,16,model.list);put(model.list,16,model.entry_array);field(tree_class,"m_Entries",16,list_class);field(list_class,"_items",16,model.array_class);field(list_class,"_size",24);field(list_class,"_version",28);field(model.entry_class,"intervalStart",16);field(model.entry_class,"intervalEnd",24);field(model.entry_class,"item",32,model.runtime_class);
 model.animation=alloc(32,"AnimationClip");model.asset=alloc(104,"AnimationPlayableAsset",asset_class);uintptr_t native=reinterpret_cast<uintptr_t>(alloc(32));put(reinterpret_cast<void*>(native),8,int32_t(77));put(model.asset,16,native);put(model.asset,24,model.animation);put(model.asset,65,uint8_t(1));put(model.asset,80,0.f);put(model.asset,92,1.f);mp4_animation_runtime_pins.instance.rva=uintptr_t(301);put(asset_class,32,uintptr_t(301));
 const char*names[]={"m_Clip","m_Position","m_EulerAngles","m_UseTrackMatchFields","m_MatchTargetFields","m_RemoveStartOffset","m_ApplyFootIK","m_Loop","<appliedOffsetMode>k__BackingField","m_Version","m_Rotation"};size_t ats[]={24,32,44,56,60,64,65,68,72,76,80};for(size_t i=0;i<11;++i)field(asset_class,names[i],ats[i]);
 model.timeline=alloc(64,"UnityEngine.Timeline.TimelineClip",timeline_class);put(model.timeline,40,model.asset);field(timeline_class,"m_Asset",40);void*track=alloc(272,"Track",track_class);put(track,256,model.animation);field(track_class,"m_InfiniteClip",256);
 model.parent.kind=infinite?mp4_animation_factory::Kind::infinite:mp4_animation_factory::Kind::clips;model.parent.track=reinterpret_cast<uintptr_t>(track);model.parent.tree=reinterpret_cast<uintptr_t>(model.tree);model.parent.graph={10,2,0};model.child.input.kind=mp4_animation_factory::Kind::clip;model.child.input.track=model.parent.track;model.child.input.clip=reinterpret_cast<uintptr_t>(model.animation);model.child.input.foot_ik=true;model.child.ticket={3,7,1,3};model.child.returned={30,2,0};
 model.element=alloc(64,infinite?"InfiniteRuntimeClip":"RuntimeClip");if(infinite)put(model.element,24,model.child.returned);else{put(model.element,24,model.timeline);put(model.element,32,model.child.returned);put(model.element,48,mp4actor::Handle{20,2,0});}
 mp4_cam_profile.class_element.rva=reinterpret_cast<uintptr_t>(class_element);mp4_cam_profile.class_value_size.rva=reinterpret_cast<uintptr_t>(class_size);mp4_cam_profile.field_offset.rva=reinterpret_cast<uintptr_t>(field_offset);mp4_animation_interval_add_original=append;
 }~Fixture(){model.thread=true;for(auto&r:mp4_animation_runtime_rows)if(r.active)mp4_animation_runtime_end(r.serial,false);assert(mp4_animation_runtime_retire());assert(model.roots.empty());}
 bool begin(uint64_t&s){return mp4_animation_runtime_begin(model.tree,model.element,model.method,infinite?200:100,&s);}bool complete(){uint64_t s=0;if(!begin(s))return false;append(model.tree,model.element,model.method);mp4_animation_runtime_end(s,true);model.active=false;model.settled=true;mp4_animation_factory::Receipt receipt{};return mp4_animation_runtime_observation(model.element,&receipt);}};
int main(){int tests=0;
 {Fixture f;assert(f.complete());assert(model.original_calls==1);++tests;}
 {Fixture f(true);assert(f.complete());++tests;}
 {Fixture f;uint64_t s=0;assert(f.begin(s));mp4_animation_factory::Receipt receipt{};assert(!mp4_animation_runtime_observation(model.element,&receipt));append(model.tree,model.element,model.method);mp4_animation_runtime_end(s,true);assert(!mp4_animation_runtime_observation(model.element,&receipt));model.active=false;model.settled=true;assert(mp4_animation_runtime_observation(model.element,&receipt));++tests;}
 {Fixture f;uint64_t s=0;assert(!mp4_animation_runtime_begin(model.tree,model.element,model.method,101,&s));assert(model.roots.empty());++tests;}
 {Fixture f;uint64_t s=0;assert(!mp4_animation_runtime_begin(model.tree,model.element,nullptr,100,&s));++tests;}
 {Fixture f;model.active=false;uint64_t s=0;assert(!f.begin(s));++tests;}
 {Fixture f;model.parent.tree=1;uint64_t s=0;assert(!f.begin(s));++tests;}
 {Fixture f;model.construction=false;uint64_t s=0;assert(!f.begin(s));++tests;}
 {Fixture f;model.child.source_root={1,2,0};uint64_t s=0;assert(!f.begin(s));++tests;}
 {Fixture f;model.graph=false;uint64_t s=0;assert(!f.begin(s));++tests;}
 {Fixture f;put(model.asset,65,uint8_t(0));uint64_t s=0;assert(!f.begin(s));++tests;}
 {Fixture f;put(model.asset,24,alloc(32,"AnimationClip"));uint64_t s=0;assert(!f.begin(s));++tests;}
 {Fixture f;put(f.asset_class,32,uintptr_t(0));uint64_t s=0;assert(!f.begin(s));++tests;}
 {Fixture f;model.size=32;uint64_t s=0;assert(!f.begin(s));++tests;}
 {Fixture f;uint64_t s=0;assert(f.begin(s));mp4_animation_runtime_end(s,false);assert(mp4_animation_runtime_dirty.load());++tests;}
 {Fixture f;uint64_t s=0;assert(f.begin(s));append(model.tree,model.element,model.method);put(model.list,28,uint32_t(2));mp4_animation_runtime_end(s,true);assert(mp4_animation_runtime_dirty.load());++tests;}
 {Fixture f;uint64_t s=0;assert(f.begin(s));append(model.tree,model.element,model.method);put(model.element,48,mp4actor::Handle{21,2,0});mp4_animation_runtime_end(s,true);assert(mp4_animation_runtime_dirty.load());++tests;}
 {Fixture f;assert(f.complete());put(model.asset,64,uint8_t(1));mp4_animation_factory::Receipt out{};assert(!mp4_animation_runtime_observation(model.element,&out));++tests;}
 {Fixture f(true);uint64_t s=0;model.parent.kind=mp4_animation_factory::Kind::clips;assert(!f.begin(s));++tests;}
 {Fixture f;model.thread=false;uint64_t s=0;assert(!f.begin(s));assert(mp4_animation_runtime_dirty.load());++tests;}
 {Fixture f;mp4_animation_interval_add_hook(model.tree,model.element,model.method);assert(model.original_calls==1);++tests;}
 {Fixture f;model.throw_original=true;try{mp4_animation_interval_add_hook(model.tree,model.element,model.method);assert(false);}catch(int x){assert(x==17);}assert(model.original_calls==1);++tests;}
 {Fixture f;uint64_t s=0;assert(f.begin(s));assert(!mp4_animation_runtime_retire());append(model.tree,model.element,model.method);mp4_animation_runtime_end(s,true);assert(mp4_animation_runtime_retire());++tests;}
 {Fixture f;void*old=alloc(32,"OldForeign");int64_t begin=2,end=6;auto*data=static_cast<uint8_t*>(mp4_array_data(model.entry_array));std::memcpy(data,&begin,8);std::memcpy(data+8,&end,8);std::memcpy(data+16,&old,8);put(model.list,24,int32_t(1));put(model.list,28,uint32_t(9));assert(f.complete());assert(!::memcmp(data,&begin,8));++tests;}
 {Fixture f;put(model.list,24,int32_t(1));std::memcpy(static_cast<uint8_t*>(mp4_array_data(model.entry_array))+16,&model.element,8);uint64_t serial=0;assert(!f.begin(serial));++tests;}
 {Fixture f;put(model.list,24,int32_t(1));uint64_t serial=0;assert(f.begin(serial));void*old=model.entry_array;model.entry_array=alloc(32+16*24,"Entry[]",model.array_class);put(model.entry_array,24,size_t(16));std::memcpy(mp4_array_data(model.entry_array),mp4_array_data(old),24);put(model.list,16,model.entry_array);append(model.tree,model.element,model.method);mp4_animation_runtime_end(serial,true);model.active=false;model.settled=true;mp4_animation_factory::Receipt receipt{};assert(mp4_animation_runtime_observation(model.element,&receipt));++tests;}
 assert(tests==26);
}
