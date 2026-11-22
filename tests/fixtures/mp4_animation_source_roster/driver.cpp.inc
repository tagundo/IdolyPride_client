struct Setup{
 void*player=make("Player"),*controller=make("Controller"),*list=make("List"),*bundle=make("UnityEngine.AssetBundle",2);
 void*d0=make("UnityEngine.Playables.PlayableDirector"),*d1=make("UnityEngine.Playables.PlayableDirector");
 void*a0=make("UnityEngine.Timeline.TimelineAsset",100),*a1=make("UnityEngine.Timeline.TimelineAsset",200);
 void*t0=make("UnityEngine.Timeline.AnimationTrack",101),*t1=make("UnityEngine.Timeline.AnimationTrack",201);
 void*v0=make("UnityEngine.Animator",501),*v1=make("UnityEngine.Animator",502),*go0=make("UnityEngine.GameObject",601),*go1=make("UnityEngine.GameObject",602);
 Setup(){
  animation_type=make("AnimationType");
  other_type=make("OtherType");
  obj(player).fields[16]=uintptr_t(controller);
  obj(controller).fields[24]=uintptr_t(list);
  obj(list).fields[28]=9;
  obj(list).list={d1,d0};
  assets[d0]=a0;
  assets[d1]=a1;
  void*l0=make("List"),*l1=make("List");
  obj(l0).list={t0};
  obj(l1).list={t1};
  obj(a0).fields[40]=uintptr_t(l0);
  obj(a1).fields[40]=uintptr_t(l1);
  obj(t0).fields[32]=0;
  obj(t1).fields[32]=0;
  bindings[{d0,t0}]=v0;
  bindings[{d1,t1}]=v1;
  programmes[v0]={v0,go0,bundle,obj(v0).native,obj(v0).id,1,&roles[0],11};
  programmes[v1]={v1,go1,bundle,obj(v1).native,obj(v1).id,1,&roles[1],12};
  director_graphs[d0]={1000,2,0};
  director_graphs[d1]={2000,2,0};
  graphs[1000]={{1000,2,0},{1010,2,0},true,{{1100,2,0},{1101,2,0}}};
  graphs[2000]={{2000,2,0},{2010,2,0},true,{{2100,2,0}}};
  outputs[1100]={true,v0};
  outputs[1101]={false,nullptr};
  outputs[2100]={true,v1};
  idoly_mp4_runtime::game.selected={player,d0,nullptr,17};
  mp4_world_profile.graph_output_count.rva=reinterpret_cast<uintptr_t>(output_count);
  mp4_world_profile.graph_output.rva=reinterpret_cast<uintptr_t>(get_output);
  mp4_world_profile.output_type.rva=reinterpret_cast<uintptr_t>(output_type);
 }
};
int main(int argc,char**argv){assert(argc==2);
const std::string mode=argv[1];
Setup h;
Mp4AnimationSourceRoster roster{};
auto w=idoly_mp4_runtime::game.selected;

 if(mode=="all_retain_failures"||mode=="all_query_throws"){
  retains=query_calls=0;
  assert(mp4_animation_source_animators(w,roster));
  const unsigned total=mode=="all_retain_failures"?retains:query_calls;
  assert(mp4_animation_source_release(roster)&&roots.empty());
  for(unsigned failure=1;failure<=total;++failure){retains=query_calls=0;
  fail_retain_at=mode=="all_retain_failures"?int(failure):0;
  throw_query_at=mode=="all_query_throws"?int(failure):0;
   assert(!mp4_animation_source_animators(w,roster)&&!roster.covered);
   assert(mp4_animation_source_release(roster)&&roots.empty());
  }
  fail_retain_at=throw_query_at=0;
  retains=query_calls=0;
  assert(mp4_animation_source_animators(w,roster)&&mp4_animation_source_release(roster)&&roots.empty());
  std::printf("swept %u failure positions\n",total);
  return 0;
 }
 if(mode=="cross_director")outputs[1100].target=h.v1;
 if(mode=="null_target")outputs[1100].target=nullptr;
 if(mode=="null_graph"||mode=="null_graph_becomes_live")director_graphs[h.d1]={};
 if(mode=="uncovered_target")outputs[1100].target=make("UnityEngine.Animator",999);
 if(mode=="bad_role")obj(h.t0).local=999;
 if(mode=="foreign_target_provider")target_provider=false;
 if(mode=="bad_target_native")programmes[h.v0].native+=8;
 if(mode=="unknown_track")obj(h.t0).known=false;
 if(mode=="duplicate_track")obj(reinterpret_cast<void*>(obj(h.a0).fields[40])).list.push_back(h.t0);
 if(mode=="track_cycle"){void*children=make("List");
 obj(children).list={h.t0};
 obj(h.t0).fields[32]=uintptr_t(children);
 }
 if(mode=="graph_invalid")graphs[1000].valid=false;
 if(mode=="root_missing")graphs[1000].root={};
 if(mode=="throw_collect")throw_query_at=8;
 if(mode=="retain_failure")fail_retain_at=9;
 if(mode=="graph_only_partial_retry"){
  obj(reinterpret_cast<void*>(obj(h.a0).fields[40])).list.clear();
  obj(h.d1).alive=false;
  assert(!mp4_animation_source_animators(w,roster)&&roster.graph_count>0&&roster.count==0&&!roster.covered);
  const size_t held=roots.size();
  const unsigned count=retains;
  obj(h.d1).alive=true;
  assert(!mp4_animation_source_animators(w,roster)&&roots.size()==held&&retains==count);
  assert(mp4_animation_source_release(roster)&&roots.empty());
  obj(reinterpret_cast<void*>(obj(h.a0).fields[40])).list={h.t0};
  assert(mp4_animation_source_animators(w,roster));
  assert(mp4_animation_source_release(roster)&&roots.empty());
  return 0;
 }
 bool captured=mp4_animation_source_animators(w,roster);
 const bool negative=mode=="uncovered_target"||mode=="bad_role"||mode=="foreign_target_provider"||mode=="bad_target_native"||mode=="unknown_track"||mode=="duplicate_track"||mode=="track_cycle"||mode=="graph_invalid"||mode=="root_missing"||mode=="throw_collect"||mode=="retain_failure";
 if(negative){assert(!captured);
 assert(!mp4_animation_source_current(roster));
 assert(mp4_animation_source_release(roster)&&roots.empty());
 return 0;
 }
 assert(captured&&roster.covered&&roster.count==2&&roster.graph_count==2);
 assert(mp4_animation_source_current(roster));
 const size_t live=roots.size();
 mp4_animation_defaults::Object value{};
 assert(mp4_animation_source_object(roster,0,&value)&&value.managed==h.v0&&value.strong_root==roster.values[0].roots[0]&&weak_get(value.strong_root)==h.v0&&roots.size()==live);
 if(mode=="baseline"||mode=="cross_director"||mode=="null_target"||mode=="null_graph"){assert(mp4_animation_source_release(roster)&&roots.empty());
 assert(mp4_animation_source_release(roster));
 return 0;
 }
 target_reads=output_reads=0;
 query_calls=0;
 if(mode=="changed_graph"){director_graphs[h.d0]={3000,4,0};
 assert(!mp4_animation_source_current(roster)&&!target_reads&&!output_reads);
 }
 else if(mode=="changed_graph_version"){++director_graphs[h.d0].version;
 assert(!mp4_animation_source_current(roster)&&!target_reads&&!output_reads);
 }
 else if(mode=="changed_root"){graphs[1000].root.handle=9999;
 assert(!mp4_animation_source_current(roster)&&!output_reads);
 }
 else if(mode=="output_count"){graphs[1000].outputs.pop_back();
 assert(!mp4_animation_source_current(roster)&&!output_reads);
 }
 else if(mode=="output_order"){std::swap(graphs[1000].outputs[0],graphs[1000].outputs[1]);
 assert(!mp4_animation_source_current(roster)&&!target_reads);
 }
 else if(mode=="output_version"){++graphs[1000].outputs[0].version;
 assert(!mp4_animation_source_current(roster)&&!target_reads);
 }
 else if(mode=="output_target"){outputs[1100].target=h.v1;
 assert(!mp4_animation_source_current(roster));
 }
 else if(mode=="nonanimation_replaced"){graphs[1000].outputs[1]={9998,4,0};
 outputs[9998]={true,make("UnityEngine.Animator",999)};
 assert(!mp4_animation_source_current(roster));
 }
 else if(mode=="output_type"){outputs[1101].animation=true;
 outputs[1101].target=h.v1;
 assert(!mp4_animation_source_current(roster));
 }
 else if(mode=="new_director"){obj(h.list).list.push_back(make("UnityEngine.Playables.PlayableDirector"));
 ++obj(h.list).fields[28];
 assert(!mp4_animation_source_current(roster)&&!output_reads);
 }
 else if(mode=="director_order"){std::swap(obj(h.list).list[0],obj(h.list).list[1]);
 assert(!mp4_animation_source_current(roster)&&!output_reads);
 }
 else if(mode=="director_version"){++obj(h.list).fields[28];
 assert(!mp4_animation_source_current(roster)&&!output_reads);
 }
 else if(mode=="director_list_identity"){void*l=make("List");
 obj(l).fields[28]=9;
 obj(l).list=obj(h.list).list;
 obj(h.controller).fields[24]=uintptr_t(l);
 assert(!mp4_animation_source_current(roster));
 }
 else if(mode=="director_asset"){assets[h.d1]=h.a0;
 assert(!mp4_animation_source_current(roster));
 }
 else if(mode=="null_graph_becomes_live"){director_graphs[h.d1]={2000,2,0};
 assert(!mp4_animation_source_current(roster));
 }
 else if(mode=="root_lost"){weak_free(roster.values[0].roots[0]);
 roster.values[0].roots[0]=0;
 assert(!mp4_animation_source_current(roster));
 }
 else if(mode=="graph_root_lost"){weak_free(roster.graphs[0].root);
 roster.graphs[0].root=0;
 assert(!mp4_animation_source_current(roster));
 }
 else if(mode=="native_identity"){++obj(h.v0).id;
 assert(!mp4_animation_source_current(roster));
 }
 else if(mode=="binding_changed"){bindings[{h.d0,h.t0}]=h.v1;
 assert(!mp4_animation_source_current(roster));
 }
 else if(mode=="foreign_generation"){++mp4_scene_shader_foreign;
 assert(!mp4_animation_source_current(roster));
 }
 else if(mode=="selected_source"){++idoly_mp4_runtime::game.selected.generation;
 assert(!mp4_animation_source_current(roster));
 }
 else if(mode=="prefix_changed"){prefixes=false;
 assert(!mp4_animation_source_current(roster));
 }
 else if(mode=="origin_changed"){origin=false;
 assert(!mp4_animation_source_current(roster));
 }
 else if(mode=="borrowed_failure_clears"){++obj(h.v0).id;
 assert(!mp4_animation_source_object(roster,0,&value)&&!value.managed&&!value.strong_root);
 }
 else if(mode=="release_offthread"){owner=false;
 assert(!mp4_animation_source_release(roster)&&roots.size()==live);
 owner=true;
 }
 else if(mode=="throw_current"){throw_query_at=1;
 bool thrown=false;
 try{(void)mp4_animation_source_current(roster);
 }catch(const std::runtime_error&){thrown=true;
 }assert(thrown&&roots.size()==live);
 throw_query_at=0;
 }
 else if(mode=="retry_after_partial"){assert(!mp4_animation_source_animators(w,roster)&&roots.size()==live);
 }
 else return 3;
 owner=true;
 assert(mp4_animation_source_release(roster)&&roots.empty());
 return 0;
}
