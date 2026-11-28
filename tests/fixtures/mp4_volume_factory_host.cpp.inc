#include "mp4_camera_owner.hpp"
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
struct FakeCurve {
  void *parameter = nullptr;
  void *initial = nullptr;
  void *fresh = nullptr;
};
FakeCurve mp4_volume_curves[256]{};
size_t mp4_volume_curve_count = 0;
unsigned create_count = 0, reload_count = 0, destroy_count = 0,
         refresh_count = 0, clear_count = 0, ctor_count = 0,
         curve_release_count = 0;
bool source_current = true, callbacks = true, draw_fence = true,
     final_fence = true, throw_reload = false, throw_ctor = false,
     fail_clear = false, prepare_disposal = true, release_curves = true,
     disposed_defaults = false;
bool mp4_volume_curve_pin_initial(void *p) {
  for (size_t i = 0; i < mp4_volume_curve_count; ++i)
    if (mp4_volume_curves[i].parameter == p)
      return false;
  void *initial = nullptr;
  mp4_actor_field(p, 24, initial);
  assert(initial &&
         mp4_exact_type(initial, "UnityEngine.Rendering.TextureCurve"));
  mp4_volume_curves[mp4_volume_curve_count++] = {p, initial, nullptr};
  return true;
}
bool mp4_volume_curve_refresh(FakeCurve &c) {
  void *source = nullptr;
  mp4_actor_field(c.parameter, 24, source);
  assert(source && source != c.initial);
  if (!c.fresh)
    c.fresh = object("UnityEngine.Rendering.TextureCurve");
  put(c.parameter, 24, c.fresh);
  ++refresh_count;
  return true;
}
bool mp4_volume_curves_prepare_disposal() {
  if (!prepare_disposal)
    return false;
  for (size_t i = 0; i < mp4_volume_curve_count; ++i)
    put(mp4_volume_curves[i].parameter, 24, mp4_volume_curves[i].initial);
  disposed_defaults = true;
  return true;
}
bool mp4_volume_curves_release() {
  if (!release_curves)
    return false;
  assert(destroy_count == 1 || mp4_volume_curve_count == 0);
  ++curve_release_count;
  mp4_volume_curve_count = 0;
  return true;
}

// SHIPPING_VOLUME_FACTORY_HOST
std::map<std::pair<void *, void *>, void *> stack_components;
void stack_ctor(void *, Method *) {
  ++create_count;
  if (throw_ctor)
    throw std::runtime_error("ctor fixture");
}
void stack_reload(void *stack, void *types, Method *) {
  ++reload_count;
  void *dict = object("Fixture.StackDictionary");
  put(stack, 16, dict);
  for (size_t i = 0; i < mp4_volume_component_count; ++i) {
    void *type = nullptr;
    ::memcpy(&type, static_cast<uint8_t *>(mp4_array_data(types)) + i * 8, 8);
    const auto &s = mp4_volume_component_schemas[i];
    void *c = object(s.name);
    void *ro = object("System.Collections.ObjectModel.ReadOnlyCollection`1");
    void *list = object("System.Collections.Generic.List`1");
    put(ro, 16, list);
    put(c, 40, ro);
    lists[list] = {};
    for (size_t j = 0; j < s.count; ++j) {
      const auto &f = s.fields[j];
      void *p = object(f.type);
      put(c, f.offset, p);
      lists[list].push_back(p);
      if (f.kind == Mp4VolumeValueKind::curve) {
        void *curve = object("UnityEngine.Rendering.TextureCurve");
        put(p, 24, curve);
      }
    }
    stack_components[{stack, type}] = c;
    put(dict, 32, static_cast<int32_t>(i + 1));
    if (throw_reload && i == 4)
      throw std::runtime_error("reload fixture");
  }
}
void *stack_component(void *stack, void *type, Method *) {
  return stack_components[{stack, type}];
}
void stack_destroy(void *, void *stack, Method *) {
  assert(disposed_defaults);
  for (size_t i = 0; i < mp4_volume_curve_count; ++i) {
    void *now = nullptr;
    mp4_actor_field(mp4_volume_curves[i].parameter, 24, now);
    assert(now == mp4_volume_curves[i].initial);
  }
  assert(stack);
  ++destroy_count;
}
void *runtime_invoke(const void *method, void *object, void **,
                     void **exception) {
  uintptr_t entry = 0;
  mp4_actor_field(const_cast<void *>(method), 0, entry);
  *exception = nullptr;
  for (size_t i = 0; i < 3; ++i) {
    const auto &p = mp4_volume_container_pins[i];
    if (entry == p.ctor.rva) {
      ++ctor_count;
      put(object, 24, int32_t{0});
      put(object, 32, int32_t{0});
      put(object, 40, int32_t{0});
      return nullptr;
    }
    if (entry == p.clear.rva) {
      ++clear_count;
      if (fail_clear) {
        *exception = object;
        return nullptr;
      }
      put(object, 24, int32_t{0});
      put(object, 32, int32_t{0});
      put(object, 40, int32_t{0});
      return nullptr;
    }
  }
  assert(false);
  return nullptr;
}
bool current(uint64_t e, void *) { return e == 17 && source_current; }
bool callback(uint64_t, void *, void *, const char *) { return callbacks; }
bool draw(uint64_t e, uint64_t) { return e == 17 && draw_fence; }
bool final(uint64_t e) { return e == 17 && final_fence; }
bool withdrawn(uint64_t, const idoly_mp4_private_volume::Frame &f) {
  void *actual = nullptr;
  constexpr uint32_t offsets[] = {16, 32, 48, 64, 72};
  for (uint32_t at : offsets) {
    mp4_actor_field(mp4_volume_factory_host.manager, at, actual);
    if (actual && (actual == f.stack || actual == f.sorted ||
                   actual == f.sort_needed || actual == f.colliders))
      return false;
  }
  return true;
}
void *method(void *k, const char *name, const mp4camp::Binding &pin) {
  void *p = object("Fixture.Method", 96);
  put(p, 0, pin.rva);
  put(p, 32, k);
  put(p, 82, uint8_t{0});
  methods[{k, name}] = p;
  return p;
}
void *setup() {
  for (size_t i = 0; i < mp4_volume_component_count; ++i) {
    const auto &s = mp4_volume_component_schemas[i];
    void *k = klass(s.name);
    descriptors[s.type.rva] = k;
    reflections[k] = object("System.RuntimeType");
  }
  descriptors[mp4_volume_stack_type.rva] =
      klass("UnityEngine.Rendering.VolumeStack");
  void *manager = object("UnityEngine.Rendering.VolumeManager");
  void *types = array(mp4_volume_component_count);
  put(manager, 24, types);
  for (size_t i = 0; i < mp4_volume_component_count; ++i) {
    void *t =
        reflections[descriptors[mp4_volume_component_schemas[i].type.rva]];
    ::memcpy(static_cast<uint8_t *>(mp4_array_data(types)) + i * 8, &t, 8);
  }
  constexpr const char *names[] = {"m_SortedVolumes", "m_SortNeeded",
                                   "m_TempColliders"};
  constexpr uint32_t offsets[] = {32, 48, 64};
  constexpr const char *cn[] = {
      "System.Collections.Generic.Dictionary`2<sorted>",
      "System.Collections.Generic.Dictionary`2<dirty>",
      "System.Collections.Generic.List`1<collider>"};
  for (size_t i = 0; i < 3; ++i) {
    void *k = klass(cn[i]);
    void *f = object("Fixture.Field");
    void *t = object("Fixture.Il2CppType");
    fields[{object_class(manager), names[i]}] = f;
    field_types[f] = t;
    type_classes[t] = k;
    void *c = object(cn[i]);
    put(manager, offsets[i], c);
    method(k, ".ctor", mp4_volume_container_pins[i].ctor);
    method(k, "Clear", mp4_volume_container_pins[i].clear);
  }
  mp4_cam_profile.runtime_invoke.rva =
      reinterpret_cast<uintptr_t>(runtime_invoke);
  mp4_cam_profile.volume_stack_ctor.rva =
      reinterpret_cast<uintptr_t>(stack_ctor);
  mp4_cam_profile.volume_stack_reload.rva =
      reinterpret_cast<uintptr_t>(stack_reload);
  mp4_cam_profile.volume_stack_component.rva =
      reinterpret_cast<uintptr_t>(stack_component);
  mp4_cam_profile.volume_destroy_stack.rva =
      reinterpret_cast<uintptr_t>(stack_destroy);
  mp4_volume_factory_hooks = {current, callback, draw, final, withdrawn};
  return manager;
}
void update() {
  assert(mp4_volume_curve_count == 8);
  for (size_t i = 0; i < mp4_volume_curve_count; ++i) {
    void *source = object("UnityEngine.Rendering.TextureCurve");
    put(mp4_volume_curves[i].parameter, 24, source);
  }
}
int main(int argc, char **argv) {
  assert(argc == 2);
  std::string mode = argv[1];
  void *manager = setup();
  if (mode == "unknown_type" || mode == "duplicate_type") {
    void *a = nullptr;
    mp4_actor_field(manager, 24, a);
    void *t = mode == "unknown_type"
                  ? object("Unknown.Type")
                  : reflections
                        [descriptors[mp4_volume_component_schemas[1].type.rva]];
    ::memcpy(mp4_array_data(a), &t, 8);
    assert(!mp4_volume_factory_configure(17, manager));
    assert(!create_count);
  } else if (mode == "unknown_callback") {
    callbacks = false;
    assert(!mp4_volume_factory_configure(17, manager));
    assert(!create_count);
  } else {
    assert(mp4_volume_factory_configure(17, manager));
    auto &h = mp4_volume_factory_host;
    idoly_mp4_private_volume::Frame f{};
    if (mode == "constructor_throw")
      throw_ctor = true;
    if (mode == "reload_throw")
      throw_reload = true;
    if (mode == "clear_exception")
      fail_clear = true;
    if (mode == "root_failure")
      root_fail = true;
    if (mode == "foreign_generic_method") {
      auto *k = h.containers[0].klass;
      (void)k;
      void *source = nullptr;
      mp4_actor_field(manager, 32, source);
      const void *m = methods[{object_class(source), ".ctor"}];
      put(const_cast<void *>(m), 0, uintptr_t{123});
    }
    bool ready = false, caught = false;
    try {
      ready = mp4_volume_factory_create(nullptr, manager, &f);
    } catch (const std::exception &) {
      caught = true;
    }
    root_fail = false;
    if (mode == "constructor_throw" || mode == "reload_throw" ||
        mode == "clear_exception" || mode == "foreign_generic_method" ||
        mode == "root_failure") {
      assert(!ready);
      if (mode == "constructor_throw" || mode == "reload_throw")
        assert(caught);
      assert(mp4_volume_factory_frame_fenced(nullptr, &f));
      assert(mp4_volume_factory_retire(nullptr, &f));
      assert(mp4_volume_factory_finalize());
      assert(destroy_count == (mode == "root_failure" ? 0u : 1u));
    } else {
      assert(ready && create_count == 1 && reload_count == 1 &&
             mp4_volume_curve_count == 8 && ctor_count == 3 &&
             clear_count == 3);
      assert(mp4_volume_factory_owned(nullptr, &f));
      update();
      assert(mp4_volume_factory_privatize(nullptr, f.stack) &&
             refresh_count == 8);
      if (mode == "foreign_frame") {
        auto x = f;
        x.stack = manager;
        assert(!mp4_volume_factory_owned(nullptr, &x));
        assert(!mp4_volume_factory_retire(nullptr, &x));
      }
      if (mode == "fence_wait") {
        draw_fence = false;
        assert(!mp4_volume_factory_retire(nullptr, &f));
        draw_fence = true;
      }
      assert(mp4_volume_factory_retire(nullptr, &f));
      assert(!destroy_count && !curve_release_count);
      if (mode == "reuse" || mode == "source_changed" ||
          mode == "list_changed") {
        if (mode == "source_changed")
          source_current = false;
        if (mode == "list_changed") {
          void *component = h.components[0];
          void *readonly = nullptr, *list = nullptr;
          mp4_actor_field(component, 40, readonly);
          mp4_actor_field(readonly, 16, list);
          lists[list].pop_back();
        }
        idoly_mp4_private_volume::Frame next{};
        bool ok = mp4_volume_factory_create(nullptr, manager, &next);
        assert(ok == (mode == "reuse"));
        assert(create_count == 1 && reload_count == 1);
        if (ok) {
          assert(next.stack == f.stack && next.sorted == f.sorted &&
                 mp4_volume_curve_count == 8 && ctor_count == 3 &&
                 clear_count == 6);
          update();
          assert(mp4_volume_factory_privatize(nullptr, next.stack));
        }
        assert(mp4_volume_factory_retire(nullptr, &next));
      }
      if (mode == "list_changed") {
        assert(!mp4_volume_factory_finalize() && !destroy_count);
        void *ro = nullptr, *list = nullptr;
        mp4_actor_field(h.components[0], 40, ro);
        mp4_actor_field(ro, 16, list);
        lists[list].push_back(
            h.parameters[mp4_volume_component_schemas[0].count - 1].parameter);
      }
      if (mode == "disposal_dictionary_replaced") {
        void *old = h.stack_dictionary;
        void *fresh = object("Fixture.StackDictionary");
        put(fresh, 32, static_cast<int32_t>(mp4_volume_component_count));
        put(h.stack, 16, fresh);
        assert(!mp4_volume_factory_finalize() && !destroy_count);
        put(h.stack, 16, old);
      }
      if (mode == "disposal_extra_component") {
        put(h.stack_dictionary, 32, static_cast<int32_t>(mp4_volume_component_count+1));
        assert(!mp4_volume_factory_finalize() && !destroy_count);
        put(h.stack_dictionary, 32, static_cast<int32_t>(mp4_volume_component_count));
      }
      if (mode == "disposal_parameter_replaced") {
        const auto &p = h.parameters[0];
        void *foreign = object(p.field->type);
        put(p.component, p.field->offset, foreign);
        assert(!mp4_volume_factory_finalize() && !destroy_count);
        put(p.component, p.field->offset, p.parameter);
      }
      if (mode == "orphaned_globals") {
        put(manager, 16, h.stack);
        assert(!mp4_volume_factory_finalize() && !destroy_count);
        put(manager, 16, static_cast<void *>(nullptr));
      }
      if (mode == "final_fence_wait") {
        final_fence = false;
        assert(!mp4_volume_factory_finalize() && !destroy_count);
        final_fence = true;
      }
      if (mode == "disposal_rebind_fail") {
        prepare_disposal = false;
        assert(!mp4_volume_factory_finalize() && !destroy_count);
        prepare_disposal = true;
      }
      assert(mp4_volume_factory_finalize());
      assert(destroy_count == 1 && curve_release_count == 1);
      assert(mp4_volume_factory_finalize());
      assert(destroy_count == 1);
    }
  }
  for (void *p : allocations)
    ::free(p);
  std::puts("ok");
}
