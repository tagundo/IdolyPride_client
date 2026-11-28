namespace idoly_mp4_actor_placement{struct Address{void*value;};}
void*operator new(size_t,idoly_mp4_actor_placement::Address at)noexcept{return at.value;}
struct NativeOutput{alignas(8)uint8_t bytes[0x110]{},slot[48]{};uint8_t family=2;};
NativeOutput native_outputs[2][2];uintptr_t tables[3][8]{};uint32_t mp4_output_types[3]{};int output_count=1,close_mode=0;bool audio_mode=false,module_closed=true,callbacks_closed=true,restoration_closed=true,nodes_closed=true;unsigned callback_queries=0,output_queries=0;alignas(8)uint8_t audio_element[64]{};Mp4AudioProgramImage audio_program{};
uintptr_t mp4_native_base=0x1000;
struct{mp4game::Binding graph_output_count,graph_output,output_type;}mp4_world_profile;
mp4world::DirectorRegistryProfile mp4_director_profile{};
int32_t output_count_call(mp4actor::Handle*g,Method*){assert(by_graph(g->handle));return output_count;}
NativeOutput*find_output(uintptr_t handle){for(auto&row:native_outputs)for(auto&o:row)if((uintptr_t)o.slot==handle)return &o;return nullptr;}
void output_get(mp4actor::Handle*g,int32_t index,mp4world::AnimationOutput*out,Method*){auto*r=by_graph(g->handle);assert(r&&index>=0&&index<2);*out={(uintptr_t)native_outputs[r==&model.roots[0]?0:1][index].slot,2,0};}
void*output_type(mp4world::AnimationOutput*out,Method*){auto*o=find_output(out->handle);assert(o);return weak_get(mp4_output_types[o->family]);}
bool mp4_director_output_source(mp4world::AnimationOutput out,mp4actor::Handle*source){for(size_t row=0;row<2;++row)for(auto&o:native_outputs[row])if((uintptr_t)o.slot==out.handle){*source=model.roots[row].root;if(close_mode==10)++source->handle;return true;}return false;}
bool mp4_director_output_userdata(const mp4world::DirectorGraphIdentity&i,uintptr_t native,void**out){assert(by_graph(i.slot));for(auto&row:native_outputs)for(auto&o:row)if((uintptr_t)o.bytes==native){*out=close_mode==11?(void*)0x12345:nullptr;return true;}return false;}
bool mp4_native_mapped(uintptr_t p,size_t,int){return p!=0;}
mp4world::DirectorRegistryApi mp4_director_api(){return {};}
void producer(){}void callback(){}
bool mp4_persistent_or_rebuilt_animation_output_closed(const mp4world::DirectorGraphIdentity&i,uintptr_t native){++output_queries;return by_graph(i.slot)&&native&&module_closed;}
bool mp4_audio_outer_output_closed(const Mp4SceneWitness&w,const mp4world::DirectorGraphIdentity&i,uintptr_t native,bool admission){++output_queries;return w.generation==1&&admission&&by_graph(i.slot)&&native&&module_closed&&close_mode!=11;}
bool mp4_audio_program_collect(size_t index,const mp4world::DirectorGraphIdentity&i,uintptr_t native,bool fresh,Mp4AudioProgramImage&out){if(index||fresh||i.slot!=(uintptr_t)model.roots[1].graph||native!=(uintptr_t)native_outputs[1][0].bytes||close_mode==12)return false;out=audio_program;return true;}
struct Game{size_t selected_audio_track_count(){return 1;}bool selected_audio_track(size_t index,void*&d,void*&a,void*&t,void*&s){if(index)return false;d=audio_program.director;a=audio_program.asset;t=audio_program.track;s=audio_program.source;return true;}};namespace idoly_mp4_runtime{Game game;}
bool mp4_timeline_tracks(Mp4TimelineContext&c){if(audio_mode&&c.director==model.roots[1].director){c.clips[0]=audio_program.clips[0].timeline;c.clip_tracks[0]=audio_program.track;c.clip_count=1;c.tracks[0]=audio_program.track;c.track_count=1;}return true;}
bool mp4_timeline_runtime_elements(Mp4TimelineContext&c,bool verify){assert(!verify);if(audio_mode&&c.director==model.roots[1].director){c.elements[0]=audio_element;c.element_count=1;c.runtime_playables[0]=audio_program.clips[0].playable;c.runtime_mixers[0]=audio_program.mixer;}return true;}
bool mp4_timeline_runtime_source(Mp4TimelineContext&,const Mp4TimelineRuntime&){return false;}
bool mp4_timeline_callbacks(Mp4TimelineContext&){++callback_queries;return callbacks_closed;}
bool mp4_timeline_userdata(Mp4TimelineContext&,mp4world::AnimationOutput,uintptr_t){return module_closed&&close_mode!=11;}
struct{bool(*restoration_closed)(const Mp4TimelineContext&)=[](const Mp4TimelineContext&c){return ::restoration_closed&&mp4_timeline_source_plan_phase(c.phase);};}mp4_timeline_hooks;
bool mp4_source_director_plan(const Mp4TimelineContext&,void*,void*);
struct Mp4SourceDirectorPlanBank; // Real concrete bank definition follows.
bool plan_nodes_impl(const Mp4TimelineContext&c);
template<class Entry>bool plan_nodes(Entry&e){return plan_nodes_impl(*e.context);}
