#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
using Method = const void;
struct Binding {
  uintptr_t rva = 0;
};
struct Pin {
  Binding binding;
};
struct {
  Pin component;
} mp4_activation_target_pins;
struct {
  Binding components_internal;
} mp4_stage_profile;
struct {
  Binding game_object_transform;
} mp4_cam_profile;
namespace mp4at {
struct Component {
  void *object = nullptr, *klass = nullptr, *game_object = nullptr,
       *transform = nullptr, *parent = nullptr;
  uintptr_t native = 0;
  uint64_t owner = 0;
  uint32_t family = 0;
  uintptr_t callbacks[5]{};
};
using Emit = bool (*)(void *, const Component &);
} // namespace mp4at
int objects[20]{};
void *target = &objects[0], *root_transform = &objects[1], *type = &objects[2];
uintptr_t image_base = 0;
uint32_t mp4_activation_component_type = 0, sequence = 0;
std::map<uint32_t, void *> roots;
bool pins = true, alive = true, retain_ok = true, array_ok = true,
     description_ok = true, emit_ok = true, source = true;
size_t emitted = 0;
bool queried = false;
mp4at::Component components[3]{};
struct Array {
  void *values[4]{};
  size_t count = 3;
} array;
uint32_t mp4_retain(void *p) {
  if (!retain_ok)
    return 0;
  roots[++sequence] = p;
  return sequence;
}
void *weak_get(uint32_t h) {
  auto i = roots.find(h);
  return i == roots.end() ? nullptr : i->second;
}
void weak_free(uint32_t h) { assert(roots.erase(h) == 1); }
struct Mp4ActorTempRoot {
  uint32_t h = 0;
  explicit Mp4ActorTempRoot(void *p) : h(p ? mp4_retain(p) : 0) {}
  ~Mp4ActorTempRoot() {
    if (h)
      weak_free(h);
  }
  void *get() const { return weak_get(h); }
};
bool mp4_activation_target_pins_ready() { return pins; }
bool mp4_type_is(void *p, const char *n) {
  return p == target && !std::strcmp(n, "UnityEngine.GameObject");
}
bool mp4_alive(void *p) { return p && alive; }
void *mp4_type_get_object(void *) { return type; }
template <class T> T mp4_equipment_call(const Binding &b) {
  return reinterpret_cast<T>(b.rva);
}
template <class T> T mp4_cam_call(const Binding &b) {
  return reinterpret_cast<T>(b.rva);
}
void *get_components(void *go, void *t, bool exact, bool recursive,
                     bool inactive, bool reverse, void *list, Method *) {
  assert(go == target && t == type && exact && recursive && inactive &&
         !reverse && !list);
  queried = true;
  return &array;
}
void *get_transform(void *go, Method *) {
  assert(go == target);
  return root_transform;
}
bool mp4_stage_array(void *p, void ***values, size_t *count, size_t maximum) {
  assert(p == &array && maximum == 8192);
  if (!array_ok || array.count > maximum)
    return false;
  *values = array.values;
  *count = array.count;
  return true;
}
struct Mp4ActivationComponentRoots {};
bool mp4_activation_component_description(void *p, mp4at::Component *out, Mp4ActivationComponentRoots*) {
  if (!description_ok)
    return false;
  for (auto &c : components)
    if (c.object == p) {
      *out = c;
      return true;
    }
  return false;
}
void *parent(void *p, Method *) {
  for (auto &c : components)
    if (c.transform == p)
      return c.parent;
  return nullptr;
}
struct Api {
  decltype(&parent) transform_parent = parent;
};
Api mp4_actor_state_api() { return {}; }
bool mp4_stage_owner(void *) { return source; }
bool emit(void *, const mp4at::Component &c) {
  assert(c.object && roots.size() >= 4);
  ++emitted;
  return emit_ok;
}
#include "activation-subtree.cpp.inc"
int main(int argc, char **argv) {
  assert(argc == 2);
  std::string c = argv[1];
  mp4_stage_profile.components_internal.rva =
      reinterpret_cast<uintptr_t>(&get_components);
  mp4_cam_profile.game_object_transform.rva =
      reinterpret_cast<uintptr_t>(&get_transform);
  for (size_t i = 0; i < 3; ++i) {
    components[i].object = &objects[3 + i];
    components[i].transform = i ? &objects[6 + i] : root_transform;
    components[i].game_object = i ? &objects[10 + i] : target;
    components[i].parent = i ? root_transform : nullptr;
    components[i].native = i + 10;
    components[i].owner = i + 20;
    components[i].family = 1;
    array.values[i] = components[i].object;
  }
  if (c == "pins")
    pins = false;
  if (c == "dead")
    alive = false;
  if (c == "retain")
    retain_ok = false;
  if (c == "array")
    array_ok = false;
  if (c == "empty")
    array.count = 0;
  if (c == "null")
    array.values[1] = nullptr;
  if (c == "duplicate")
    array.values[1] = array.values[0];
  if (c == "description")
    description_ok = false;
  if (c == "outside")
    components[1].parent = nullptr;
  if (c == "root_missing") {
    array.values[0] = components[1].object;
    array.values[1] = components[2].object;
    array.count = 2;
  }
  if (c == "emit")
    emit_ok = false;
  if (c == "source")
    source = false;
  assert(mp4_activation_subtree_inventory(nullptr, target, emit, nullptr) ==
         (c == "normal"));
  if (c == "normal")
    assert(queried && emitted == 3);
  assert(roots.size() == (mp4_activation_component_type ? 1u : 0u));
}
