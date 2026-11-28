Object *roster,*roster_array,*director_controller;Object *actor,*player,*swing,*track,*track_script,*timeline_script,*param_script,*asset[2],*motion[2],*actor_clip_script[2],*native_clip[2],*native_animation[2];
mp4actor::Handle master{},actor_timeline{},actor_mixer{},master_clips[2]{},actor_clips[2]{},layers[2]{},clips[2]{},base_param{};Mp4TimelineContext context{};Mp4TimelineRuntime requested{};
Object*array(size_t length,size_t stride){auto*p=object("System.Array");p->length=length;p->array.resize(length*stride);return p;}
mp4actor::Handle node(unsigned kind,void*script,mp4actor::Handle graph){auto*p=object("NativeNodeSlot");mp4actor::Handle h{uintptr_t(p),1,0};nodes[h.handle]={graph,script,kind,{ },true};return h;}
void set_method(void*p,const char*n,uintptr_t code){auto*m=object("Method");put(m,0,image_base+code);method_map[{object_class(p),n}]=m;const size_t slot=!std::strcmp(n,"Setup")?0x178:!std::strcmp(n,"SetTimelineWeight")?0x1c8:0x408;vtables[object_class(p)][slot]=image_base+code;}
void initialize(){
 actor=object("SolisActor");player=object("VL.VLAnimationClipPlayer");selected_player=source_binding=player;swing=object("VL.VLActorActorSwing");put(actor,56,static_cast<void*>(player));put(actor,376,static_cast<void*>(swing));actor_components=array(1,8);std::memcpy(static_cast<void*>(actor_components->array.data()),&actor,8);
 selected_owner.actor=actor;selected_owner.extension=swing;selected_owner.animator=object("UnityEngine.Animator");selected_owner.graph={456,1,0};context.graph={123,1,0};context.witness.player=object("Player");context.witness.director=context.director=object("UnityEngine.Playables.PlayableDirector");context.asset=object("TimelineAsset");
 director_controller=object("Controller");roster=object("List");roster_array=array(0,8);put(roster,16,static_cast<void*>(roster_array));put(roster,24,int32_t(0));put(roster,28,uint32_t(1));put(director_controller,0x28,static_cast<void*>(roster));put(context.witness.player,0x38,static_cast<void*>(director_controller));director_assets[context.director]=context.asset;director_graphs[context.director]=context.graph;
 set_method(player,"Setup",mp4_timeline_actor_pins.setup.rva);set_method(player,"SetTimelineWeight",mp4_timeline_actor_pins.weight.rva);set_method(actor,"ResetModel",mp4_timeline_actor_pins.reset_solis.rva);
 mp4_actor_profile.get_game_object.rva=reinterpret_cast<uintptr_t>(component_object)-image_base;mp4_actor_profile.get_components_internal.rva=reinterpret_cast<uintptr_t>(components)-image_base;mp4_actor_profile.playable_graph_get.rva=reinterpret_cast<uintptr_t>(graph_get)-image_base;
 track=object(mp4_timeline_actor_pins.track.name);track_script=object(mp4_timeline_actor_pins.track_playable.name);timeline_script=object(mp4_timeline_actor_pins.mixer.name);param_script=object("VL.Playables.VLAnimationClipParamMixerPlayable");
 master=node(99,track_script,context.graph);actor_timeline=node(5,timeline_script,selected_owner.graph);actor_mixer=node(0,nullptr,selected_owner.graph);base_param=node(4,param_script,selected_owner.graph);nodes[actor_timeline.handle].inputs={actor_mixer};put(player,80,base_param);put(player,152,static_cast<void*>(array(8,16)));put(player,192,actor_timeline);put(param_script,40,static_cast<void*>(array(4,48)));
 put(track_script,16,static_cast<void*>(player));put(track_script,24,actor_timeline);put(timeline_script,32,actor_mixer);put(timeline_script,24,int32_t(2));put(timeline_script,48,int32_t(2));
 context.track_count=1;context.tracks[0]=track;context.compiled[0]=master;context.clip_count=context.element_count=2;
 for(size_t i=0;i<2;++i){asset[i]=object(mp4_timeline_actor_pins.asset.name);motion[i]=object("VL.MotionDefine");auto*source_clip=object("UnityEngine.AnimationClip");put(source_clip,16,uintptr_t(source_clip));motions[motion[i]]={source_clip};put(asset[i],24,static_cast<void*>(motion[i]));put(asset[i],48,uint8_t(1));
  auto*authored=object("TimelineClip");put(authored,mp4stage::Layout::clip_asset,static_cast<void*>(asset[i]));context.clips[i]=authored;context.clip_tracks[i]=track;
  master_clips[i]=node(99,nullptr,context.graph);actor_clip_script[i]=object(mp4_timeline_actor_pins.clip.name);actor_clips[i]=node(6,actor_clip_script[i],selected_owner.graph);layers[i]=node(1,nullptr,selected_owner.graph);clips[i]=node(2,nullptr,selected_owner.graph);native_clip[i]=object("NativeClip");native_animation[i]=source_clip;put(reinterpret_cast<void*>(clips[i].handle),40,uintptr_t(native_clip[i]));put(native_clip[i],0x1d0,uintptr_t(source_clip));
  put(actor_clip_script[i],16,static_cast<void*>(motion[i]));put(actor_clip_script[i],24,uint8_t(1));put(actor_clip_script[i],32,layers[i]);auto*value_array=array(1,16);std::memcpy(value_array->array.data(),&clips[i],16);put(actor_clip_script[i],48,static_cast<void*>(value_array));nodes[actor_clips[i].handle].inputs={layers[i]};nodes[layers[i].handle].inputs={clips[i]};
  auto*element=object(mp4_timeline_pins.clip.name);put(element,24,static_cast<void*>(authored));put(element,32,master_clips[i]);put(element,48,master);context.elements[i]=element;
 }
 nodes[master.handle].inputs={master_clips[0],master_clips[1]};nodes[actor_mixer.handle].inputs={actor_clips[0],actor_clips[1]};
 actor_roots={actor_timeline,base_param};factory_roles.insert(actor_timeline.handle);factory_roles.insert(base_param.handle);for(size_t i=0;i<2;++i){factory_roles.insert(actor_clips[i].handle);factory_roles.insert(layers[i].handle);factory_roles.insert(clips[i].handle);}
 requested={context.elements[0],context.clips[0],track,master_clips[0],master,0};
}
bool closed(){return mp4_timeline_actor_node(context,master,track_script)==Mp4TimelineVerdict::closed&&mp4_timeline_actor_runtime(context,requested)==Mp4TimelineVerdict::closed;}
int main(int argc,char**argv){assert(argc==2);initialize();std::string test=argv[1];
 if(test=="source_admission"){assert(closed()&&source_collections&&catalog_calls);}
 else if(test=="active_source"){context.phase=Mp4TimelineProofPhase::active;assert(closed());}
 else if(test=="restore_plan"){context.phase=Mp4TimelineProofPhase::source_restore_plan;assert(closed());}
 else if(test=="restored"){context.phase=Mp4TimelineProofPhase::source_restored;assert(closed());}
 else if(test=="source_changed"){source_current=false;assert(!closed());}
 else if(test=="pins"){source_pins=false;assert(!closed());}
 else if(test=="inventory"){inventory_ready=false;assert(!closed());}
 else if(test=="presentation"){presentation_ready=false;assert(!closed());}
 else if(test=="temporal_plan"){temporal_catalog_ready=false;assert(!closed());}
 else if(test=="binding"){source_binding=actor;assert(!closed());}
 else if(test=="foreign_player"){put(actor,56,static_cast<void*>(object("VL.VLAnimationClipPlayer")));assert(!closed());}
 else if(test=="owned_actor_child"){auto*child=object("UnityEngine.Playables.PlayableDirector");roster_array->length=1;roster_array->array.resize(8);std::memcpy(roster_array->array.data(),&child,8);put(roster,24,int32_t(1));director_assets[child]=context.asset;director_graphs[child]=context.graph;context.director=child;assert(closed());}
 else if(test=="foreign_child"){auto*child=object("UnityEngine.Playables.PlayableDirector");director_assets[child]=context.asset;director_graphs[child]=context.graph;context.director=child;assert(!closed());}
 else if(test=="director_asset_changed"){director_assets[context.director]=object("OtherTimelineAsset");assert(!closed());}
 else if(test=="director_graph_changed"){director_graphs[context.director]=selected_owner.graph;assert(!closed());}
 else if(test=="director_roster_changed"){mutate_roster=true;roster_for_mutation=roster;assert(!closed());}
 else if(test=="wrong_director"){context.director=object("Director");assert(!closed());}
 else if(test=="duplicate_actor_component"){actor_components->length=2;actor_components->array.resize(16);assert(!closed());}
 else if(test=="wrong_actor_component"){void*other=object("SolisActor");std::memcpy(actor_components->array.data(),&other,8);assert(!closed());}
 else if(test=="virtual_reset_changed"){vtables[object_class(actor)][0x408]=image_base+999;assert(!closed());}
 else if(test=="virtual_setup_changed"){vtables[object_class(player)][0x178]=image_base+999;assert(!closed());}
 else if(test=="unknown_reset"){set_method(actor,"ResetModel",999);assert(!closed());}
 else if(test=="wrong_swing"){put(actor,376,static_cast<void*>(object("VL.VLActorActorSwing")));assert(!closed());}
 else if(test=="base_reset"){set_method(actor,"ResetModel",mp4_timeline_actor_pins.reset_base.rva);assert(closed());}
 else if(test=="unknown_setup"){set_method(player,"Setup",999);assert(!closed());}
 else if(test=="unknown_weight"){set_method(player,"SetTimelineWeight",999);assert(!closed());}
 else if(test=="metadata"){metadata_fields=false;assert(!closed());}
 else if(test=="dirty_param_rows"){void*a=nullptr;assert(mp4_actor_field(param_script,40,a));memory[a]->array[0]=1;assert(!closed());}
 else if(test=="param_queue"){put(param_script,48,int32_t(1));assert(!closed());}
 else if(test=="param_motion"){put(param_script,72,static_cast<void*>(motion[0]));assert(!closed());}
 else if(test=="unknown_outer_callback"){put(player,176,static_cast<void*>(object("Delegate")));assert(!closed());}
 else if(test=="unknown_callback"){put(param_script,112,static_cast<void*>(object("Delegate")));assert(!closed());}
 else if(test=="unknown_outer_play"){put(player,184,static_cast<void*>(object("Delegate")));assert(!closed());}
 else if(test=="duplicate_track_player"){context.track_count=2;context.tracks[1]=object(mp4_timeline_actor_pins.track.name);context.compiled[1]=master;assert(!closed());}
 else if(test=="owned_actor_swing_job"){auto extra=node(3,nullptr,selected_owner.graph);selected_owner.playable=extra;actor_roots.push_back(extra);assert(closed());}
 else if(test=="owned_fixed_job"){auto extra=node(3,nullptr,selected_owner.graph);actor_roots.push_back(extra);mp4actor::FixedJobOwner f{};f.job=reinterpret_cast<void*>(extra.handle);f.playable=extra;f.graph=selected_owner.graph;f.animator=selected_owner.animator;fixed_jobs.push_back(f);assert(closed());}
 else if(test=="wrong_fixed_job_owner"){auto extra=node(3,nullptr,selected_owner.graph);actor_roots.push_back(extra);mp4actor::FixedJobOwner f{};f.job=reinterpret_cast<void*>(extra.handle);f.playable=extra;f.graph=context.graph;f.animator=selected_owner.animator;fixed_jobs.push_back(f);assert(!closed());}
 else if(test=="unknown_actor_job"){auto extra=node(3,nullptr,selected_owner.graph);actor_roots.push_back(extra);assert(!closed());}
 else if(test=="unknown_actor_clip"){auto extra=node(2,nullptr,selected_owner.graph);actor_roots.push_back(extra);assert(!closed());}
 else if(test=="unknown_actor_script"){auto extra=node(99,object("UnknownScript"),selected_owner.graph);actor_roots.push_back(extra);assert(!closed());}
 else if(test=="unregistered_actor_child"){auto extra=node(99,nullptr,selected_owner.graph);nodes[actor_mixer.handle].inputs.push_back(extra);assert(!closed());}
 else if(test=="pure_actor_mixer"){auto extra=node(0,nullptr,selected_owner.graph);actor_roots.push_back(extra);assert(closed());}
 else if(test=="foreign_actor_root"){auto extra=node(0,nullptr,context.graph);actor_roots.push_back(extra);assert(!closed());}
 else if(test=="different_actor_mixer"){put(track_script,24,base_param);assert(!closed());}
 else if(test=="different_actor_graph"){nodes[actor_timeline.handle].graph=context.graph;assert(!closed());}
 else if(test=="different_master_graph"){nodes[master.handle].graph=selected_owner.graph;assert(!closed());}
 else if(test=="missing_actor_input"){nodes[actor_mixer.handle].inputs.pop_back();assert(!closed());}
 else if(test=="missing_authored_clip"){context.clip_count=1;assert(!closed());}
 else if(test=="duplicate_runtime"){context.element_count=3;context.elements[2]=context.elements[0];assert(!closed());}
 else if(test=="runtime_wrong_parent"){put(context.elements[0],48,actor_mixer);assert(!closed());}
 else if(test=="runtime_wrong_asset"){put(context.clips[0],24,static_cast<void*>(object("OtherAsset")));assert(!closed());}
 else if(test=="motion_swapped"){put(actor_clip_script[0],16,static_cast<void*>(motion[1]));assert(!closed());}
 else if(test=="motion_reference"){reference_valid=true;reference_value=motion[0];put(asset[0],24,static_cast<void*>(motion[1]));put(asset[1],32,mp4game::PropertyName4{1});assert(mp4_timeline_actor_clip(context,asset[0],actor_clips[0],selected_owner.graph));}
 else if(test=="exposed_default"){put(asset[0],24,static_cast<void*>(motion[1]));put(asset[0],40,static_cast<void*>(motion[0]));assert(closed());}
 else if(test=="foot_changed"){put(actor_clip_script[0],24,uint8_t(0));assert(!closed());}
 else if(test=="wrong_native_clip_asset"){put(native_clip[0],0x1d0,uintptr_t(native_animation[1]));assert(!closed());}
 else if(test=="wrong_layer_kind"){nodes[layers[0].handle].kind=0;assert(!closed());}
 else if(test=="wrong_layer_graph"){nodes[layers[0].handle].graph=context.graph;assert(!closed());}
 else if(test=="wrong_clip_graph"){nodes[clips[0].handle].graph=context.graph;assert(!closed());}
 else if(test=="stale_handle"){nodes[actor_clips[0].handle].valid=false;assert(!closed());}
 else if(test=="scheduled"){requested.kind=1;assert(mp4_timeline_actor_runtime(context,requested)==Mp4TimelineVerdict::unclosed);}
 else if(test=="foreign_runtime"){requested.element=object("RuntimeClip");assert(mp4_timeline_actor_runtime(context,requested)==Mp4TimelineVerdict::unclosed);}
 else if(test=="ignored_userdata"){assert(mp4_timeline_actor_userdata(context,master,track_script,object("ForeignData")));}
 else if(test=="unrecognized"){assert(mp4_timeline_actor_node(context,master,object("OtherScript"))==Mp4TimelineVerdict::unrecognized);requested.track=object("OtherTrack");put(context.clips[0],24,static_cast<void*>(object("OtherAsset")));assert(mp4_timeline_actor_runtime(context,requested)==Mp4TimelineVerdict::unrecognized);}
 else if(test=="foreign_actor_script"){assert(mp4_timeline_actor_node(context,actor_clips[0],actor_clip_script[0])==Mp4TimelineVerdict::unclosed);}
 else assert(false);
 assert(roots.empty());return 0;
}
