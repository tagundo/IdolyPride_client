namespace idoly_mp4_playback {enum class Phase{acquiring,held,starting,playing,restoring};}
#include <stdint.h>
#include <stddef.h>
namespace idoly_mp4_camera_profile {struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};struct Profile{Binding transform_children,object_active,object_set_active,field_flags,field_offset;};}
namespace idoly_mp4_actor {using Method=void;struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};struct ActorBinding{uintptr_t rva=0;uint8_t prefix[16]{};};}
// SHIPPING_SOURCE_VOLUME_TYPES

#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
namespace mp4camp = idoly_mp4_camera_profile;
namespace mp4game {
struct Binding {
  uintptr_t rva = 0;
  uint8_t prefix[16]{};
};
} // namespace mp4game
using Method = const void;
using Mp4CameraInvoke = void *(*)(const void *, void *, void **, void **);
uintptr_t image_base = 0;
mp4camp::Profile mp4_cam_profile{};
struct Object {
  std::string name;
  size_t size = 0;
  void *klass = nullptr;
  bool alive = true;
};
std::map<void *, Object> objects;
std::vector<void *> allocations;
std::map<std::string, void *> classes;
std::map<uintptr_t, void *> descriptors;
std::map<void *, void *> reflections;
void *make(const char *name, size_t bytes = 512) {
  void *p = ::calloc(1, bytes);
  allocations.push_back(p);
  objects[p] = {name, bytes, nullptr, true};
  return p;
}
void *klass(const char *name) {
  auto &i = classes[name];
  if (!i) {
    i = make("Fixture.Class");
    objects[i].name = name;
  }
  return i;
}
void *object(const char *name, size_t bytes = 512) {
  void *p = make(name, bytes);
  objects[p].klass = klass(name);
  if(std::string(name).find("UnityEngine.")==0||std::string(name)=="Solis.Common.LightVolume"){
   void*n=make("Fixture.Native");static int32_t next=1;const int32_t id=next++;
   ::memcpy(static_cast<uint8_t*>(n)+8,&id,4);::memcpy(static_cast<uint8_t*>(p)+16,&n,8);
  }
  return p;
}
void *object_class(void *p) {
  return objects.count(p) ? objects[p].klass : nullptr;
}
bool game_call() { return true; }
bool mp4_actor_mapped(const void *p, size_t n, bool) {
  uintptr_t a = reinterpret_cast<uintptr_t>(p);
  for (auto &o : objects) {
    uintptr_t b = reinterpret_cast<uintptr_t>(o.first);
    if (a >= b && a - b <= o.second.size && n <= o.second.size - (a - b))
      return true;
  }
  return false;
}
template <class T> bool mp4_actor_field(void *p, size_t at, T &v) {
  if (!p || !mp4_actor_mapped(static_cast<uint8_t *>(p) + at, sizeof(T), false))
    return false;
  ::memcpy(&v, static_cast<uint8_t *>(p) + at, sizeof(T));
  return true;
}
template <class T> void put(void *p, size_t at, T v) {
  assert(mp4_actor_mapped(static_cast<uint8_t *>(p) + at, sizeof(T), true));
  ::memcpy(static_cast<uint8_t *>(p) + at, &v, sizeof(T));
}
bool mp4_type_is(void *p, const char *name) {
  return objects.count(p) &&
         (objects[p].name == name ||
          (std::string(name)=="UnityEngine.Object"&&(objects[p].name.find("UnityEngine.")==0||objects[p].name=="Solis.Common.LightVolume")) ||
          (std::string(name) == "System.Array" &&
           objects[p].name.find("[]") != std::string::npos));
}
bool mp4_exact_type(void *p, const char *name) {
  return objects.count(p) && objects[p].name == name;
}
bool mp4_alive(void *p) { return objects.count(p) && objects[p].alive; }
void *array(size_t n) {
  void *p = object("System.Type[]", 32 + (n ? n : 1) * 8);
  put(p, 24, static_cast<uintptr_t>(n));
  return p;
}
void *mp4_array_data(void *p) { return static_cast<uint8_t *>(p) + 32; }
std::map<void *, std::vector<void *>> lists;
bool mp4_actor_list(void *p, void ***values, size_t *count, size_t limit) {
  if (!p || !lists.count(p) || lists[p].size() > limit)
    return false;
  *values = lists[p].data();
  *count = lists[p].size();
  return true;
}
std::map<uint32_t, void *> roots;
uint32_t root_next = 1;
bool root_fail = false;
uint32_t mp4_retain(void *p) {
  if (root_fail)
    return 0;
  uint32_t n = root_next++;
  roots[n] = p;
  return n;
}
void *weak_get(uint32_t n) { return roots.count(n) ? roots[n] : nullptr; }
void weak_free(uint32_t n) { roots.erase(n); }
bool mp4_prefix(const mp4game::Binding &) { return true; }
bool mp4_hook_was_statically_verified(const mp4game::Binding &) { return false; }
template <class T>
void *mp4_resolved_type_class(const T &b, const char *, const char *) {
  return descriptors[b.rva];
}
void *mp4_type_get_object(void *p) {
  return reflections[descriptors[reinterpret_cast<uintptr_t>(p)]];
}
bool mp4_actor_refresh_maps() { return true; }
bool mp4_camera_generic_class(void *p) {
  return objects.count(p) &&
         objects[p].name.find("System.Collections.Generic.") == 0;
}
template <class F> F mp4_cam_call(const mp4camp::Binding &b) {
  return reinterpret_cast<F>(b.rva);
}
std::map<std::pair<void *, std::string>, void *> fields;
std::map<void *, void *> field_types;
std::map<void *, void *> type_classes;
void *get_field(void *k, const char *n) { return fields[{k, n}]; }
const void *get_field_type(void *f) { return field_types[f]; }
void *get_class_type(const void *t) {
  return type_classes[const_cast<void *>(t)];
}
std::map<std::pair<void *, std::string>, const void *> methods;
const void *get_method(void *k, const char *n, int32_t) {
  return methods[{k, n}];
}
void *new_object(void *k) {
  void *p = object(objects[k].name.c_str());
  objects[p].klass = k;
  return p;
}
void *(*font_field)(void *, const char *) = get_field;
const void *(*font_field_type)(void *) = get_field_type;
void *(*font_class_type)(const void *) = get_class_type;
const void *(*font_method)(void *, const char *, int32_t) = get_method;
void *(*font_new)(void *) = new_object;

namespace mp4actor = idoly_mp4_actor;
using Mp4CameraFlag = uint32_t (*)(const void *);
using Mp4CameraOffset = size_t (*)(const void *);
bool mp4_source_verified=true,mp4_actor_source_verified=true;
struct Mp4ActorTempRoot{uint32_t root=0;explicit Mp4ActorTempRoot(void*p):root(mp4_retain(p)){}~Mp4ActorTempRoot(){if(root)weak_free(root);}void*get()const{return weak_get(root);}};
struct Mp4SceneWitness {
  void *player = nullptr, *director = nullptr;
  uint64_t generation = 0;void*environment=nullptr;
};
enum class Mp4SceneResult { ok, waiting, stale, failed };
enum class Mp4TimelineProofPhase {
  admission,
  active,
  source_restore_plan,
  source_restored,source_bootstrap_plan
};
bool mp4_timeline_source_plan_phase(Mp4TimelineProofPhase p){return p==Mp4TimelineProofPhase::admission||p==Mp4TimelineProofPhase::source_bootstrap_plan;}
enum class Mp4TimelineVerdict { unrecognized, closed, unclosed };
struct Mp4TimelineRuntime {
  void *element = nullptr, *clip = nullptr, *track = nullptr;
  mp4actor::Handle playable{}, mixer{};
  uint8_t kind = 0;
};
struct Mp4TimelineContext {
  Mp4TimelineProofPhase phase = Mp4TimelineProofPhase::active;
  Mp4SceneWitness witness{};
  void *director = nullptr, *asset = nullptr;
  mp4actor::Handle nodes[8]{}, runtime_playables[8]{}, runtime_mixers[8]{};
  void *elements[8]{}, *clips[8]{}, *clip_tracks[8]{};
  size_t node_count = 0, element_count = 0, clip_count = 0,track_count=0;
  void*tracks[8]{};mp4actor::Handle compiled[8]{};
};
struct ClassPin {
  mp4camp::Binding clip;
} mp4_timeline_pins;
namespace mp4stage {
struct Layout {
  static constexpr size_t clip_asset = 40;
};
} // namespace mp4stage
namespace mp4game {
struct PropertyName4 {
  int32_t id = 0;
};
} // namespace mp4game
namespace idoly_mp4_runtime {
struct Job {uint64_t generation=91;}job;
struct Clock {
  bool is_held = true;
  bool held() const { return is_held; }
} clock;
const Clock &native_clock_scope() { return clock; }
struct Game {
  idoly_mp4_playback::Phase phase = idoly_mp4_playback::Phase::held;
  auto automatic_rebuild_phase() { return phase; }
} game;
} // namespace idoly_mp4_runtime
struct SceneHost {
  Mp4SceneWitness source{};
} mp4_scene_host;
struct AssemblyHost {
  bool prepare_started = false;
} mp4_volume_assembly;
bool context_current = true, source_current = true, fenced = true,
     rebuild_complete = true, saved_evaluated = true, prefixes = true;
unsigned active_writes = 0, changed_writes = 0;
std::map<void *, void *> component_go, go_components;
std::map<void *, int32_t> child_count;
std::map<void *, bool> active, changed;
std::map<int32_t, void *> references;
std::map<void *, uint32_t> offsets, flags;
void *get_object(void *v, Method *) { return component_go[v]; }
void *resolve_reference(void *, mp4game::PropertyName4 n, bool *valid,
                        Method *) {
  auto i = references.find(n.id);
  *valid = i != references.end();
  return *valid ? i->second : nullptr;
}
void *root_asset = nullptr;
void *get_asset(void *, Method *) { return root_asset; }
struct GameApi {
  void *(*component_game_object)(void *, Method *) = get_object;
  void *(*director_get_reference)(void *, mp4game::PropertyName4, bool *,
                                  Method *) = resolve_reference;
  void *(*director_get_asset)(void *, Method *) = get_asset;
} mp4_api;
bool mp4_scene_same_source(const Mp4SceneWitness &a, const Mp4SceneWitness &b) {
  return a.generation && a.generation == b.generation && a.player == b.player &&
         a.director == b.director;
}
bool mp4_scene_source_current() { return source_current; }
bool mp4_director_boundary_closed(void *) { return fenced; }
bool mp4_world_volume_routes();
bool mp4_volume_mono_routes(void *) { return prefixes; }
bool mp4_volume_factory_prefix(const mp4camp::Binding &) { return prefixes; }
void *mp4_volume_factory_class(const mp4camp::Binding &p, const char *) {
  return descriptors[p.rva];
}
void *mp4_volume_callback_class(const mp4actor::ActorBinding &p, const char *) {
  return descriptors[p.rva];
}
bool mp4_volume_factory_array(void *p, void ***data, size_t *n, size_t limit) {
  uintptr_t count = 0;
  if (!mp4_actor_field(p, 24, count) || count > limit)
    return false;
  *n = count;
  *data = reinterpret_cast<void **>(static_cast<uint8_t *>(p) + 32);
  return !count || mp4_actor_mapped(*data, count * 8, false);
}
bool mp4_volume_mono_changed(void *t, bool *out) {
  *out = changed[t];
  return true;
}
bool mp4_volume_mono_changed_set(void *t, bool v) {
  ++changed_writes;
  changed[t] = v;
  return true;
}
size_t field_offset(const void *f) { return offsets[const_cast<void *>(f)]; }
uint32_t field_flags(const void *f) { return flags[const_cast<void *>(f)]; }
void *get_components(void *go, void *, bool, bool, bool, bool, void *,
                     Method *) {
  return go_components[go];
}
int32_t children(void *t, Method *) { return child_count[t]; }
bool get_active(void *go, Method *) { return active[go]; }
void set_active(void *go, bool v, Method *) {
  ++active_writes;
  active[go] = v;
}
struct ActorProfile {
  mp4camp::Binding get_components_internal;
  mp4actor::ActorBinding transform_type;
} mp4_actor_profile;
struct CamTypes {
  mp4camp::Binding component;
} mp4_cam_types;
struct Node {
  mp4actor::Handle handle;
  void *script;
  std::vector<mp4actor::Handle> inputs;
};
std::vector<Node> nodes;
Node *node(mp4actor::Handle h) {
  for (auto &n : nodes)
    if (n.handle.handle == h.handle && n.handle.version == h.version)
      return &n;
  return nullptr;
}
bool mp4_actor_same_handle(mp4actor::Handle a, mp4actor::Handle b) {
  return a.handle == b.handle && a.version == b.version;
}
void *mp4_timeline_script(mp4actor::Handle h) {
  auto *n = node(h);
  return n ? n->script : nullptr;
}
int32_t mp4_timeline_node_index(const Mp4TimelineContext &c,
                                mp4actor::Handle h) {
  for (size_t i = 0; i < c.node_count; ++i)
    if (mp4_actor_same_handle(c.nodes[i], h))
      return static_cast<int32_t>(i);
  return -1;
}
int32_t input_count(mp4actor::Handle *h, mp4actor::Method *) {
  auto *n = node(*h);
  return n ? static_cast<int32_t>(n->inputs.size()) : -1;
}
void input(mp4actor::Handle *h, int32_t i, mp4actor::Handle *out,
           mp4actor::Method *) {
  auto *n = node(*h);
  *out = n && i >= 0 && size_t(i) < n->inputs.size() ? n->inputs[size_t(i)]
                                                     : mp4actor::Handle{};
}
struct StateApi {
  decltype(&input_count) playable_input_count = input_count;
  decltype(&input) playable_input = input;
};
StateApi mp4_actor_state_api() { return {}; }
bool mp4_timeline_current(const Mp4TimelineContext &c) {
  return context_current &&
         mp4_scene_same_source(c.witness, mp4_scene_host.source);
}
bool mp4_timeline_exact(void *p, const mp4camp::Binding &pin) {
  return p && object_class(p) == descriptors[pin.rva];
}
bool mp4_timeline_original_rebuild_complete(const Mp4TimelineContext &,
                                            bool saved) {
  return rebuild_complete && (!saved || saved_evaluated);
}
Mp4TimelineContext context;
bool mp4_timeline_visit_owned_contexts(
    Mp4TimelineProofPhase phase,
    bool (*visitor)(const Mp4TimelineContext &, void *), void *opaque) {
  context.phase = phase;
  return fenced && idoly_mp4_runtime::clock.held() &&
         visitor(context, opaque) && mp4_timeline_current(context);
}

namespace mp4vs=idoly_mp4_volume_source;
namespace mp4vm {enum class Kind{mirror,height_fog,light};struct Owner{Kind kind=Kind::mirror;void*component=nullptr,*volume=nullptr,*game_object=nullptr,*transform=nullptr,*environment=nullptr;uintptr_t asset=0;uint64_t epoch=0,receipt=0;};}
struct MonoHost {Mp4SceneWitness source{};void*asset=nullptr;void*classes[5]{};uint64_t receipt=31;}mp4_volume_mono_host;
bool mp4_volume_mono_host_current(){return source_current;}
bool mp4_source_volume_routes(){return prefixes;}
bool mp4_world_volume_private_preparation_started(){return mp4_volume_assembly.prepare_started;}
bool mp4_volume_source_snapshot_fenced(){return fenced&&source_current&&idoly_mp4_runtime::clock.held();}
bool mp4_world_volume_rebuilt_current(const Mp4TimelineContext&,bool saved){return rebuild_complete&&(!saved||saved_evaluated);}
struct SourceHost {Mp4SceneWitness source{};bool captured=true;uint64_t capture_invocation=55;}mp4_source_volume_host;
struct SourceScopeModel {uint64_t capture=77;bool valid=true;uint64_t capture_receipt_raw(){return capture;}bool captured_image(void*,mp4vs::CapturedVolumeImage*); }mp4_source_volume_scope;
bool mp4_source_volume_current(void*){return source_current;}
struct Mp4TimelineProducer {Mp4TimelineVerdict(*node)(const Mp4TimelineContext&,mp4actor::Handle,void*);bool(*userdata)(const Mp4TimelineContext&,mp4actor::Handle,void*,void*);Mp4TimelineVerdict(*runtime)(const Mp4TimelineContext&,const Mp4TimelineRuntime&);};
Mp4TimelineVerdict target_verdict=Mp4TimelineVerdict::unrecognized;
Mp4TimelineVerdict mp4_target_image_node(const Mp4TimelineContext&,mp4actor::Handle,void*){return target_verdict;}
bool mp4_target_image_userdata(const Mp4TimelineContext&,mp4actor::Handle,void*,void*){return target_verdict==Mp4TimelineVerdict::closed;}
Mp4TimelineVerdict mp4_target_image_runtime(const Mp4TimelineContext&,const Mp4TimelineRuntime&){return target_verdict;}

// SHIPPING_WORLD_VOLUME_PINS// SHIPPING_WORLD_VOLUME_HOST// SHIPPING_WORLD_VOLUME_ENDPOINTS
bool SourceScopeModel::captured_image(void*v,mp4vs::CapturedVolumeImage*out){
 if(out)*out={};
 if(!out||!valid||!fenced||!capture)return false;
 for(size_t i=0;i<mp4_world_volume_host.go_count;++i){const auto&g=mp4_world_volume_host.gos[i];if(g.volume!=v)continue;
  out->owner={v,g.go,1,2,mp4_scene_host.source.generation,mp4_world_volume_host.receipt,mp4vs::activation_restore};out->capture=capture;return true;
 }return false;
}
void field(void *k, const char *name, size_t at, uint32_t kind,
           void *valueclass) {
  void *f = object("Fixture.Field"), *t = object("Fixture.Type");
  fields[{k, name}] = f;
  field_types[f] = t;
  type_classes[t] = valueclass;
  offsets[f] = at;
  put(t, 8, kind << 16);
}
int main(int argc, char **argv) {
  assert(argc == 2);
  std::string mode = argv[1];
  auto &p = mp4_world_volume_pins;
  const mp4camp::Binding *typepins[] = {&p.volume,       &p.light, &p.asset,
                                        &p.track,        &p.clip,  &p.mixer,
                                        &p.initial_state};
  const char *names[] = {"UnityEngine.Rendering.Volume",
                         "Solis.Common.LightVolume",
                         "Solis.Timeline.SolisVolumeTimelineAsset",
                         "Solis.Timeline.SolisVolumeTimelineTrack",
                         "Solis.Timeline.SolisVolumeTimelineBehaviour",
                         "Solis.Timeline.SolisVolumeTimelineMixerBehaviour",
                         "InitialState"};
  for (size_t i = 0; i < 7; ++i)
    descriptors[typepins[i]->rva] = klass(names[i]);
  mp4_actor_profile.transform_type.rva = 91;
  descriptors[91] = klass("UnityEngine.Transform");
  mp4_cam_types.component.rva = 92;
  descriptors[92] = klass("UnityEngine.Component");
  reflections[descriptors[92]] = object("System.RuntimeType");
  mp4_actor_profile.get_components_internal.rva =
      reinterpret_cast<uintptr_t>(get_components);
  mp4_cam_profile.transform_children.rva =
      reinterpret_cast<uintptr_t>(children);
  mp4_cam_profile.object_active.rva = reinterpret_cast<uintptr_t>(get_active);
  mp4_cam_profile.object_set_active.rva =
      reinterpret_cast<uintptr_t>(set_active);
  mp4_cam_profile.field_offset.rva = reinterpret_cast<uintptr_t>(field_offset);
  mp4_cam_profile.field_flags.rva = reinterpret_cast<uintptr_t>(field_flags);
  field(descriptors[p.clip.rva], "m_InitialState", 28, 17,
        descriptors[p.initial_state.rva]);
  field(descriptors[p.clip.rva], "initialVolumePriority", 40, 12,
        klass("System.Single"));
  void *player = object("Fixture.Player"),
       *director = object("UnityEngine.Playables.PlayableDirector");
  root_asset = object("UnityEngine.Timeline.TimelineAsset");
  mp4_scene_host.source = {player, director, 17};
  context.witness = mp4_scene_host.source;
  context.director = director;
  context.asset = root_asset;
  void *volume = object((mode=="light_volume"||mode=="light_owners")?names[1]:names[0]), *go = object("UnityEngine.GameObject"),
       *transform = object("UnityEngine.Transform");
  component_go[volume] = go;
  void *a = array(2);
  put(a, 32, volume);
  put(a, 40, transform);
  go_components[go] = a;
  active[go] = true;
  changed[transform] = true;
  void *asset = object(names[2]), *track = object(names[3]),
       *clip = object("UnityEngine.Timeline.TimelineClip"),
       *element = object("UnityEngine.Timeline.RuntimeClip");
  put(asset, 24, int32_t(123));
  references[123] = volume;
  put(clip, 40, asset);
  void *script = object(names[4]), *mixer_script = object(names[5]);
  put(script, 16, go);
  put(script, 24, int32_t(1));
  put(script, 28, int32_t(2));
  put(script, 32, volume);
  put(script, 40, 7.5f);
  mp4actor::Handle leaf{123, 2, 0}, mixer{456, 2, 0};
  nodes.push_back({leaf, script, {}});
  nodes.push_back({mixer, mixer_script, {leaf}});
  context.nodes[0] = leaf;
  context.nodes[1] = mixer;
  context.node_count = 2;
  context.runtime_playables[0] = leaf;
  context.runtime_mixers[0] = mixer;
  context.elements[0] = element;
  context.element_count = 1;
  context.clips[0] = clip;
  context.clip_tracks[0] = track;
  context.clip_count = 1;
  put(element, 24, clip);put(element,32,leaf);put(element,48,mixer);
  context.track_count=1;context.tracks[0]=track;context.compiled[0]=mixer;
  mp4_source_volume_host.source=mp4_scene_host.source;mp4_volume_mono_host.source=mp4_scene_host.source;mp4_volume_mono_host.asset=root_asset;
  mp4_volume_mono_host.classes[4]=descriptors[p.light.rva];
  mp4_timeline_pins.clip.rva = 93;
  descriptors[93] = object_class(element);
  Mp4TimelineRuntime r{element, clip, track, leaf, mixer, 0};
  context.phase = Mp4TimelineProofPhase::admission;
  if (mode == "foreign_component") {
    void *extra = object("Foreign.Callback");
    a = array(3);
    put(a, 32, volume);
    put(a, 40, transform);
    put(a, 48, extra);
    go_components[go] = a;
    assert(mp4_world_volume_runtime(context, r) ==
           Mp4TimelineVerdict::unclosed);
    goto done;
  }
  if (mode == "nonleaf") {
    child_count[transform] = 1;
    assert(mp4_world_volume_runtime(context, r) ==
           Mp4TimelineVerdict::unclosed);
    goto done;
  }
  if (mode == "light_volume_unclosed") {
    objects[volume].klass = klass("Unknown.VolumeSubclass");
    assert(mp4_world_volume_runtime(context, r) ==
           Mp4TimelineVerdict::unclosed);
    goto done;
  }
  if (mode == "wrong_exposed_target") {
    references[123] = object(names[0]);
    assert(mp4_world_volume_runtime(context, r) ==
           Mp4TimelineVerdict::unclosed);
    goto done;
  }
  if (mode == "wrong_parent") {
    nodes[1].inputs.clear();
    assert(mp4_world_volume_runtime(context, r) ==
           Mp4TimelineVerdict::unclosed);
    goto done;
  }
  if (mode == "wrong_post") {
    put(script, 24, int32_t(2));
    assert(mp4_world_volume_runtime(context, r) ==
           Mp4TimelineVerdict::unclosed);
    goto done;
  }

  if(mode=="wrong_compiled"){context.compiled[0]={999,2,0};assert(mp4_world_volume_runtime(context,r)==Mp4TimelineVerdict::unclosed);goto done;}
  if(mode=="wrong_runtime_element"){put(element,32,mixer);assert(mp4_world_volume_runtime(context,r)==Mp4TimelineVerdict::unclosed);goto done;}
  if(mode=="duplicate_parent_edge"){nodes[1].inputs.push_back(leaf);assert(mp4_world_volume_runtime(context,r)==Mp4TimelineVerdict::unclosed);goto done;}
  if(mode=="bootstrap_plan"){context.phase=Mp4TimelineProofPhase::source_bootstrap_plan;assert(mp4_world_volume_runtime(context,r)==Mp4TimelineVerdict::closed&&!mp4_world_volume_host.captured);goto done;}
  assert(mp4_world_volume_runtime(context, r) == Mp4TimelineVerdict::closed);
  if (mode == "admission_userdata") {
    assert(mp4_world_volume_userdata(context, leaf, script,
                                     object("Foreign.UserData")));
    goto done;
  }
  if (mode == "playing_without_capture") {
    context.phase = Mp4TimelineProofPhase::active;
    idoly_mp4_runtime::game.phase = idoly_mp4_playback::Phase::playing;
    assert(mp4_world_volume_runtime(context, r) ==
           Mp4TimelineVerdict::unclosed);
    goto done;
  }
  assert(mp4_world_volume_capture());
  assert(mp4_world_volume_host.go_count == 1 &&
         mp4_world_volume_host.clip_count == 1);
  {
    void *out[1]{};
    size_t n = 0;
    assert(mp4_world_volume_source_volumes(out, 1, &n) && n == 1 &&
           out[0] == volume);
  }


  if(mode=="native_identity_changed") {uintptr_t native=0;int32_t id=0;assert(mp4_actor_field(volume,16,native)&&mp4_actor_field(reinterpret_cast<void*>(native),8,id));put(reinterpret_cast<void*>(native),8,id+1);assert(!mp4_world_volume_roots());goto done;}
  if(mode=="source_image_missing") {mp4_source_volume_scope.valid=false;assert(!mp4_world_volume_complete_source_capture());goto done;}
  assert(mp4_world_volume_complete_source_capture());
  if(mode=="clip_snapshot"||mode=="mixer_snapshot") {Mp4WorldVolumeSnapshot image{};context.phase=Mp4TimelineProofPhase::source_bootstrap_plan;
   const bool is_mixer=mode=="mixer_snapshot";assert(mp4_world_volume_captured_snapshot(context,is_mixer?mixer:leaf,is_mixer?mixer_script:script,track,is_mixer?nullptr:clip,&image));
   assert(image.image&&image.source_capture==77&&image.source_invocation==55&&image.logical_capture&&image.target==(is_mixer?track:volume));goto done;}
  if(mode=="source_capture_changed"){++mp4_source_volume_scope.capture;assert(!mp4_world_volume_image_current());goto done;}
  if(mode=="source_invocation_changed"){++mp4_source_volume_host.capture_invocation;assert(!mp4_world_volume_image_current());goto done;}
  if(mode=="dispatcher_target_unclosed"){target_verdict=Mp4TimelineVerdict::unclosed;assert(mp4_world_timeline_runtime(context,r)==Mp4TimelineVerdict::unclosed);goto done;}
  if(mode=="light_owners"){mp4vm::Owner owners[64]{};size_t count=0;assert(mp4_world_volume_light_owners(owners,64,&count));assert(count==1&&owners[0].volume==volume);goto done;}
  if (mode == "capture_root_lost") {
    weak_free(mp4_world_volume_host.roots[0].root);
    assert(mp4_world_volume_restore() == Mp4SceneResult::stale &&
           !active_writes);
    goto done;
  }
  active[go] = false;
  changed[transform] = false;
  if (mode == "fence_wait") {
    fenced = false;
    assert(mp4_world_volume_restore() == Mp4SceneResult::waiting &&
           !active_writes);
    fenced = true;
    goto done;
  }
  if (mode == "source_lost") {
    ++mp4_scene_host.source.generation;
    assert(mp4_world_volume_restore() == Mp4SceneResult::stale &&
           !active_writes);
    goto done;
  }
  if (mode == "authored_target_retarget") {
    put(asset, 24, int32_t(124));
    references[124] = volume;
    assert(mp4_world_volume_restore() == Mp4SceneResult::stale &&
           !active_writes);
    goto done;
  }
  {
    void *new_script = object(names[4]);
    put(new_script, 16, go);
    put(new_script, 24, int32_t(1));
    put(new_script, 28, int32_t(1));
    put(new_script, 32, volume);
    put(new_script, 40, 99.f);
    mp4actor::Handle replacement{124, 4, 0};
    nodes[0] = {replacement, new_script, {}};
    nodes[1].inputs = {replacement};
    context.nodes[0] = replacement;
    context.runtime_playables[0] = replacement;put(element,32,replacement);
    if(mode=="restore_plan_before_saved_eval"||mode=="final_without_saved_eval"){
      saved_evaluated=false;
      r.playable=replacement;context.phase=mode=="restore_plan_before_saved_eval"?Mp4TimelineProofPhase::source_restore_plan:Mp4TimelineProofPhase::source_restored;
      assert(mp4_world_volume_runtime(context,r)==(mode=="restore_plan_before_saved_eval"?Mp4TimelineVerdict::closed:Mp4TimelineVerdict::unclosed));
      assert(mp4_world_volume_restore()==Mp4SceneResult::stale&&!active_writes);
      goto done;
    }
    if (mode == "untrusted_rebuild") {
      rebuild_complete = false;
      assert(mp4_world_volume_restore() == Mp4SceneResult::stale &&
             !active_writes);
      goto done;
    }
    if (mode == "saved_eval_missing") {
      saved_evaluated = false;
      assert(mp4_world_volume_restore() == Mp4SceneResult::stale &&
             !active_writes);
      goto done;
    }
    if (mode == "field_type_changed") {
      void *f = fields[{object_class(new_script), "m_InitialState"}];
      type_classes[field_types[f]] = klass("Foreign.State");
      assert(mp4_world_volume_restore() == Mp4SceneResult::stale &&
             !active_writes);
      goto done;
    }
    assert(mp4_world_volume_restore() == Mp4SceneResult::ok);
    int32_t state = 0;
    float priority = 0;
    mp4_actor_field(new_script, 28, state);
    mp4_actor_field(new_script, 40, priority);
    assert(state == 2 && priority == 7.5f && active[go] && changed[transform] &&
           active_writes == 1);
    assert(
        mp4_world_volume_userdata(context, replacement, new_script, nullptr));
    if(mode=="postrestore_go_changed"){active[go]=false;assert(!mp4_world_volume_target_restored(volume));}
    else if(mode=="postrestore_history_changed"){put(new_script,28,int32_t(1));assert(!mp4_world_volume_target_restored(volume));}
    else assert(mp4_world_volume_target_restored(volume));

  }
done:
  assert(mp4_world_volume_release(false));
  assert(roots.empty());
  for (void *x : allocations)
    ::free(x);
  std::puts("ok");
}
