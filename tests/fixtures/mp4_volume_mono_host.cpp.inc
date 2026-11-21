#include "mp4_camera_owner.hpp"
#include "mp4_actor_state.hpp"
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

namespace mp4actor=idoly_mp4_actor; using VoidMethod=void(*)(void*,Method*);
bool callbacks=true;

// SHIPPING_VOLUME_MONO_SCOPE
// SHIPPING_VOLUME_FACTORY_SCHEMAS
// SHIPPING_VOLUME_SOURCE_PINS
// SHIPPING_VOLUME_MONO_PINS_EXPORTS
struct Mp4SceneWitness {
  void *environment = nullptr, *director = nullptr;
  uint64_t generation = 0;
};
struct StageHost {
  Mp4SceneWitness source;
} mp4_stage_host;
bool stage_current = true, boundary = true, texture_closed = true;
bool mp4_stage_owner(void *) { return stage_current; }
bool mp4_scene_same_source(const Mp4SceneWitness &a, const Mp4SceneWitness &b) {
  return a.environment == b.environment && a.director == b.director &&
         a.generation == b.generation;
}
std::map<void *, void *> gos, transforms;
void *source_asset = nullptr;
void *get_go(void *c, Method *) { return gos[c]; }
void *get_transform(void *c, Method *) { return transforms[c]; }
void *get_asset(void *, Method *) { return source_asset; }
struct RootApi {
  void *(*director_get_asset)(void *, Method *) = get_asset;
} mp4_api;
struct FakeActorProfile {
  mp4camp::Binding get_components_internal;
} mp4_actor_profile;
struct TempRoot {
  uint32_t token = 0;
  TempRoot(void *p) { token = mp4_retain(p); }
  ~TempRoot() { weak_free(token); }
  void *get() { return weak_get(token); }
};
using Mp4ActorTempRoot = TempRoot;
void *mp4_volume_factory_class(const mp4camp::Binding &pin, const char *full) {
  void *k = klass(full);
  descriptors[pin.rva] = k;
  if (!reflections[k])
    reflections[k] = object("System.RuntimeType");
  return k;
}
bool mp4_volume_factory_array(void *a, void ***values, size_t *count,
                              size_t cap) {
  uintptr_t n = 0;
  if (!mp4_type_is(a, "System.Array") || !mp4_actor_field(a, 24, n) || n > cap)
    return false;
  *values = static_cast<void **>(mp4_array_data(a));
  *count = n;
  return true;
}
struct FactoryHooks {
  bool (*callbacks_closed)(uint64_t, void *, void *, const char *) = nullptr;
} mp4_volume_factory_hooks;
struct FactoryHost {
  bool in_frame = false;
} mp4_volume_factory_host;
bool ctor_closed(uint64_t epoch, void *, void *type, const char *name) {
  return callbacks && epoch == 17 && type == reflections[klass(name)];
}
struct FakeMonoGate {
  template <class F> bool isolate(F &&f) {
    f();
    return true;
  }
} mp4_actor_mono_gate;
bool mp4_director_boundary_closed(void *) { return boundary; }
bool mp4_camera_volume_asset_readonly(void *o,
                                      idoly_mp4_volume_source::ValueKind k,
                                      void *, void *) {
  return texture_closed && mp4_alive(o) &&
         ((k == idoly_mp4_volume_source::ValueKind::texture2d &&
           mp4_exact_type(o, "UnityEngine.Texture2D")) ||
          (k == idoly_mp4_volume_source::ValueKind::texture3d &&
           mp4_exact_type(o, "UnityEngine.Texture3D")) ||
          (k == idoly_mp4_volume_source::ValueKind::cubemap &&
           mp4_exact_type(o, "UnityEngine.Cubemap")));
}
mp4actor::MonoCallback mp4_actor_foot_apply_original = nullptr;
mp4actor::PresentationApi mp4_actor_presentation_api(mp4actor::MonoCallback) {
  return {};
}
void original_mono(void *, Method *) {}
VoidMethod mp4_mirror_late_original = original_mono,
           mp4_mirror_parameters_original = original_mono,
           mp4_mirror_destroy_original = original_mono,
           mp4_fog_enable_original = original_mono,
           mp4_fog_disable_original = original_mono,
           mp4_fog_late_original = original_mono;
std::map<std::pair<void *, void *>, std::vector<void *>> component_query;
void *components(void *go, void *type, bool typed, bool recursive,
                 bool inactive, bool reverse, void *list, Method *) {
  assert(typed && inactive && !reverse && !list);
  (void)recursive;
  auto &v = component_query[{go, type}];
  void *a = array(v.size());
  if (v.size())
    std::memcpy(mp4_array_data(a), v.data(), v.size() * 8);
  return a;
}

namespace idoly_mp4_runtime {
struct FixtureClock {
  bool active() const {return true;}
  bool restoring() const {return false;}
  bool have_tick() const {return true;}
  uint64_t tick() const {return 0;}
};
const FixtureClock&native_clock_scope(){static FixtureClock c;return c;}
}

// SHIPPING_VOLUME_MONO_ADAPTER
void *new_list(const std::vector<void *> &v) {
  void *l = object("System.Collections.Generic.List`1");
  lists[l] = v;
  return l;
}
void *make_component(const Mp4VolumeComponentSchema &s) {
  void *c = object(s.name);
  void *ro = object("System.Collections.ObjectModel.ReadOnlyCollection`1");
  void *l = new_list({});
  put(c, 40, ro);
  put(ro, 16, l);
  for (size_t k = 0; k < s.count; ++k) {
    auto &f = s.fields[k];
    void *p = object(f.type);
    put(c, f.offset, p);
    lists[l].push_back(p);
    void *method = object("Fixture.MethodInfo");
    put(method, 0, image_base + mp4_source_volume_pins.release.rva);
    put(method, 82, uint8_t(0));
    methods[{object_class(p), "Release"}] = method;
    put(object_class(p), 0x1d8,
        image_base + mp4_source_volume_pins.release.rva);
    put(object_class(p), 0x1e0, static_cast<const void *>(method));
  }
  return c;
}
void *make_profile(void *c) {
  void *p = object("UnityEngine.Rendering.VolumeProfile");
  put(p, 16, new_list({c}));
  return p;
}
int main(int argc, char **argv) {
  assert(argc == 2);
  std::string mode = argv[1];
  void *root = object("Solis.Common.Live.SolisLiveEnvironment"),
       *root_go = object("UnityEngine.GameObject"),
       *director = object("PlayableDirector");
  source_asset = object("UnityEngine.Timeline.TimelineAsset");
  mp4_stage_host.source = {root, director, 17};
  gos[root] = root_go;
  const auto &t = mp4_volume_mono_types;
  const mp4camp::Binding *pins[] = {&t.mirror, &t.height_fog, &t.volume,
                                    &t.renderer};
  const char *names[] = {
      "VL.Rendering.MirrorVolume", "Solis.Rendering.VolumetricHeightFogVolume",
      "UnityEngine.Rendering.Volume", "UnityEngine.MeshRenderer"};
  void *types[4]{};
  for (size_t i = 0; i < 4; ++i) {
    void *k = mp4_volume_factory_class(*pins[i], names[i]);
    types[i] = reflections[k];
  }
  mp4_source_volume_pins.get_object.rva = reinterpret_cast<uintptr_t>(get_go);
  mp4_cam_profile.component_transform.rva =
      reinterpret_cast<uintptr_t>(get_transform);
  mp4_actor_profile.get_components_internal.rva =
      reinterpret_cast<uintptr_t>(components);
  mp4_volume_factory_hooks.callbacks_closed = ctor_closed;
  void *producer = nullptr, *volume = nullptr, *renderer = nullptr,
       *mesh = nullptr, *profile = nullptr, *component = nullptr;
  bool mirror = mode.find("mirror") == 0, zero = mode == "zero";
  if (!zero) {
    producer = object(mirror ? names[0] : names[1]);
    void *go = object("UnityEngine.GameObject"),
         *tr = object("UnityEngine.Transform");
    gos[producer] = go;
    transforms[producer] = tr;
    component_query[{root_go, types[mirror ? 0 : 1]}] = {producer};
    if (mirror) {
      volume = producer;
      mesh = object("UnityEngine.Mesh");
      put(producer, 88, mesh);
    } else {
      volume = object(names[2]);
      renderer = object(names[3]);
      gos[volume] = go;
      gos[renderer] = go;
      component_query[{go, types[2]}] = {volume};
      component_query[{go, types[3]}] = {renderer};
      if (mode != "dormant") {
        put(producer, 80, renderer);
        put(producer, 88, volume);
      }
    }
    const size_t schema = mirror ? 13 : 0;
    component = make_component(mp4_volume_component_schemas[schema]);
    profile = make_profile(component);
    put(volume, 48, profile);
    if (mode != "dormant") {
      put(volume, 64, profile);
      put(producer, mirror ? 136 : 104, component);
    }
  }
  if (mode == "duplicate_producer")
    component_query[{root_go, types[1]}].push_back(producer);
  if (mode == "unknown_producer")
    objects[producer].klass = klass("Unproven.Subclass");
  if (mode == "unknown_profile_component")
    objects[component].klass = klass("Unproven.VolumeComponent");
  if (mode == "unknown_lifecycle")
    callbacks = false;
  mp4_volume_mono_hooks.mesh_protected = [](const mp4vm::Owner &o, void *m) {
    return o.mask_mesh == m;
  };
  if (mode == "mirror_unprotected")
    mp4_volume_mono_hooks.mesh_protected = nullptr;
  void *manager = object("UnityEngine.Rendering.VolumeManager");
  bool admitted = mp4_volume_mono_host_admit(manager);
  bool negative = mode == "duplicate_producer" || mode == "unknown_producer" ||
                  mode == "unknown_profile_component" ||
                  mode == "unknown_lifecycle" || mode == "mirror_unprotected";
  if (negative) {
    assert(!admitted);
    goto finish;
  }
  assert(admitted && mp4_volume_mono_host.count == (zero ? 0 : 1));
  {
    auto &h = mp4_volume_mono_host;
    assert(mp4_volume_mono_inventory(nullptr, h.owners, h.count));
    if (mode == "stage_changed") {
      stage_current = false;
      assert(!mp4_volume_mono_inventory(nullptr, h.owners, h.count));
    }
    if (mode == "asset_changed") {
      source_asset = object("UnityEngine.Timeline.TimelineAsset");
      assert(!mp4_volume_mono_inventory(nullptr, h.owners, h.count));
    }
    if (mode == "membership_changed") {
      component_query[{root_go, types[1]}].clear();
      assert(!mp4_volume_mono_inventory(nullptr, h.owners, h.count));
    }
    if (mode == "target_changed") {
      put(producer, 88, object(names[2]));
      assert(!mp4_volume_mono_inventory(nullptr, h.owners, h.count));
    }
    if (mode == "private_component_alias") {
      void *p = make_profile(component);
      assert(!mp4_volume_mono_profile(nullptr, p, h.owners[0]));
    }
    if (mode == "private_param_alias") {
      void *c = make_component(mp4_volume_component_schemas[0]);
      void *ro = nullptr, *l = nullptr, *source_param = nullptr;
      mp4_actor_field(c, 40, ro);
      mp4_actor_field(ro, 16, l);
      mp4_actor_field(component, 56, source_param);
      put(c, 56, source_param);
      lists[l][0] = source_param;
      void *p = make_profile(c);
      assert(!mp4_volume_mono_profile(nullptr, p, h.owners[0]));
    }
    if (mode == "private_flat_clone") {
      void *c = make_component(mp4_volume_component_schemas[0]);
      void *p = make_profile(c);
      assert(mp4_volume_mono_profile(nullptr, p, h.owners[0]));
    }
    if (mode == "curve_profile") {
      void *c = make_component(mp4_volume_component_schemas[18]);
      void *p = make_profile(c);
      assert(!mp4_volume_mono_profile(nullptr, p, h.owners[0]));
    }
  }
finish:
  for (void *p : allocations)
    ::free(p);
  std::puts("ok");
}
