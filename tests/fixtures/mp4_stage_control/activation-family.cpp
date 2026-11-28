#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
using Method = const void;
struct Binding {
  uintptr_t rva = 0;
};
struct Pin {};
struct {
  Pin transform;
} mp4_activation_target_pins;
struct NativeMethod {
  uintptr_t entry = 0;
};
struct Component {
  uint64_t header[2]{};
  uintptr_t native = 7;
  int kind = 2;
  bool alive = true;
  NativeMethod methods[5]{};
} component;
namespace mp4vs {
struct OwnerWitness {
  uint64_t receipt = 9;
};
} // namespace mp4vs
namespace mp4vm {
enum class Kind { mirror, height_fog, light };
struct Owner {
  void *component = nullptr;
  Kind kind = Kind::mirror;
  uint64_t receipt = 8;
};
} // namespace mp4vm
struct {
  bool captured = true;
} mp4_source_volume_host;
struct {
  bool captured = false;
  mp4vm::Owner owners[1]{};
  size_t count = 0;
} mp4_volume_mono_host;
struct {
  Binding volume_enable{10}, volume_disable{20};
} mp4_source_volume_pins;
struct {
  Binding fog_enable{30}, fog_disable{40};
} mp4_volume_mono_bindings;
uintptr_t image_base = 100;
bool owns = true, owner_ok = true, routes = true, additional_ok = false;
uint32_t additional_family = 4;
uint64_t additional_receipt = 10;
struct {
  bool owns_volume(void *p) { return owns && p == &component; }
} mp4_source_volume_scope;
bool mp4_source_volume_routes() { return routes; }
bool mp4_source_volume_owner(void *, void *, mp4vs::OwnerWitness *out) {
  out->receipt = 9;
  return owner_ok;
}
bool mp4_volume_mono_host_current() { return owner_ok; }
bool mp4_volume_mono_owner(void *, const mp4vm::Owner &) { return owner_ok; }
bool mp4_alive(void *p) { return p == &component && component.alive; }
bool mp4_type_is(void *p, const char *n) {
  return p == &component && component.kind == 2 &&
         !std::strcmp(n, "UnityEngine.Rendering.Volume");
}
bool mp4_timeline_exact(void *p, const Pin &) {
  return p == &component && component.kind == 1;
}
void *object_class(void *p) { return p; }
const void *font_method(void *, const char *name, int) {
  const char *names[] = {"Awake", "Start", "OnEnable", "OnDisable",
                         "OnDestroy"};
  for (size_t i = 0; i < 5; ++i)
    if (!std::strcmp(names[i], name))
      return component.methods[i].entry ? &component.methods[i] : nullptr;
  return nullptr;
}
template <class T> bool mp4_actor_field(void *p, size_t off, T &out) {
  if (sizeof(T) != 8)
    return false;
  if (p == &component && off == 16) {
    std::memcpy(&out, &component.native, 8);
    return true;
  }
  if (off == 0) {
    std::memcpy(&out, p, 8);
    return true;
  }
  return false;
}
bool additional(void *, uint32_t *f, uint64_t *r) {
  *f = additional_family;
  *r = additional_receipt;
  return additional_ok;
}
bool (*mp4_activation_additional_family)(void *, uint32_t *,
                                         uint64_t *) = additional;
#include "activation-family.cpp.inc"
int main(int argc, char **argv) {
  assert(argc == 2);
  std::string c = argv[1];
  component.methods[2].entry = 110;
  component.methods[3].entry = 120;
  if (c == "transform") {
    component.kind = 1;
    component.methods[2].entry = component.methods[3].entry = 0;
  }
  if (c == "dead")
    component.alive = false;
  if (c == "uncaptured")
    mp4_source_volume_host.captured = false;
  if (c == "unowned")
    owns = false;
  if (c == "owner_lost")
    owner_ok = false;
  if (c == "routes")
    routes = false;
  if (c == "awake")
    component.methods[0].entry = 199;
  if (c == "start")
    component.methods[1].entry = 199;
  if (c == "enable")
    component.methods[2].entry = 199;
  if (c == "disable")
    component.methods[3].entry = 199;
  if (c == "mono" || c == "fog" || c == "mono_start") {
    component.kind = 3;
    component.methods[2].entry = component.methods[3].entry = 0;
    mp4_volume_mono_host.captured = true;
    mp4_volume_mono_host.count = 1;
    mp4_volume_mono_host.owners[0] = {&component, mp4vm::Kind::mirror, 8};
    if (c == "fog") {
      mp4_volume_mono_host.owners[0].kind = mp4vm::Kind::height_fog;
      component.methods[2].entry = 130;
      component.methods[3].entry = 140;
    }
    if (c == "mono_start")
      component.methods[1].entry = 199;
  }
  if (c == "unknown" || c == "additional" || c == "additional_bad_family" ||
      c == "additional_no_receipt") {
    component.kind = 4;
    additional_ok = c != "unknown";
    if (c == "additional_bad_family")
      additional_family = 3;
    if (c == "additional_no_receipt")
      additional_receipt = 0;
  }
  uint32_t family = 0;
  uint64_t receipt = 0;
  uintptr_t callbacks[5]{};
  bool expected = c == "normal" || c == "transform" || c == "mono" ||
                  c == "fog" || c == "additional";
  assert(mp4_activation_component_family(&component, &family, &receipt,
                                         callbacks) == expected);
  if (expected)
    assert(family && receipt);
}
