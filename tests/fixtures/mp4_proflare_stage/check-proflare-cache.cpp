#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <stdexcept>
struct Method {};
struct Binding {
  uintptr_t rva = 0;
  uint8_t prefix[16]{};
};
namespace mp4game {
using Binding = ::Binding;
}
struct Pin {
  int kind = 0;
};
struct {
  Pin flare{1}, element{2}, batch{3};
  Binding start{20}, init{21}, enable{22}, disable{23}, add{24}, remove{25};
} mp4_proflare_pins;
const struct {
  Binding awake{19}, destroy{26};
} mp4_proflare_cache_pins;
uintptr_t image_base = 0;
bool game = true, pins = true, observer_throw = false;
bool mp4_source_verified = true;
struct Obj {
  alignas(16) unsigned char b[320]{};
  int kind = 0;
  bool alive = true;
} flare, atlas, elements, array, transform, go, batch, element, native,
    tr_native, go_native, batch_native, wrong;
std::map<void *, Obj *> objects;
std::map<uint32_t, void *> roots;
uint32_t rootseq = 1;
int calls = 0;
bool original_throw = false;
uint64_t prep = 77;
uint32_t weak_make(void *p, bool) {
  if (observer_throw)
    throw std::runtime_error("observer");
  auto h = rootseq++;
  roots[h] = p;
  return h;
}
void *weak_target(uint32_t h) { return roots[h]; }
void weak_drop(uint32_t h) { roots.erase(h); }
auto weak_new = weak_make;
auto weak_get = weak_target;
auto weak_free = weak_drop;
uint32_t mp4_retain(void *p) { return weak_new(p, false); }
struct Mp4ActorTempRoot {
  uint32_t h = 0;
  explicit Mp4ActorTempRoot(void *p) : h(p ? mp4_retain(p) : 0) {}
  ~Mp4ActorTempRoot() {
    if (h)
      weak_free(h);
  }
  void *get() const { return h ? weak_get(h) : nullptr; }
};
bool font_strong = true;
void *class_of(void *p) {
  auto i = objects.find(p);
  return i == objects.end() ? nullptr
                            : reinterpret_cast<void *>(
                                  static_cast<uintptr_t>(i->second->kind));
}
auto object_class = class_of;
bool game_call() { return game; }
void *mp4_timeline_class(const Pin &p) {
  return reinterpret_cast<void *>(static_cast<uintptr_t>(p.kind));
}
bool mp4_prefix(const Binding &) { return pins; }
bool mp4_hook_was_statically_verified(const Binding &b) { return b.rva == 20; }
bool mp4_timeline_exact(void *p, const Pin &pin) {
  return p && class_of(p) == mp4_timeline_class(pin);
}
bool mp4_alive(void *p) {
  auto i = objects.find(p);
  return i != objects.end() && i->second->alive;
}
bool mp4_type_is(void *p, const char *n) {
  return (std::strcmp(n, "UnityEngine.Transform") == 0 && p == transform.b) ||
         (std::strcmp(n, "UnityEngine.GameObject") == 0 && p == go.b);
}
uintptr_t methods[5] = {19, 20, 22, 23, 26};
const void *method_find(void *, const char *n, int) {
  const char *names[] = {"Awake", "Start", "OnEnable", "OnDisable",
                         "OnDestroy"};
  for (int i = 0; i < 5; ++i)
    if (!std::strcmp(n, names[i]))
      return &methods[i];
  return nullptr;
}
auto font_method = method_find;
bool font_field = true;
struct Field {
  uint32_t bits[4]{};
  void *declared = nullptr;
};
Field field;
const void *field_type(void *f) { return f; }
void *class_type_impl(const void *f) {
  return static_cast<const Field *>(f)->declared;
}
auto font_class_type=class_type_impl;
auto font_field_type = field_type;
bool mp4_root_track_field(void *, const char *n, size_t off, void **out) {
  struct F {
    const char *n;
    size_t off;
    uint32_t k;
  };
  const F fs[] = {{"_items", 16, 29},
                  {"_Atlas", 32, 18},
                  {"Elements", 48, 21},
                  {"thisTransform", 56, 18},
                  {"thisGameObject", 64, 18},
                  {"sunMode", 229, 2},
                  {"sunModeTransformA", 232, 18},
                  {"sunModeTransformB", 240, 18},
                  {"flareBatchForSrp", 248, 18},
                  {"Initialised", 256, 2},
                  {"DisabledPlayMode", 257, 2},
                  {"flare", 32, 18},
                  {"flareAtlas", 40, 18}};
  for (auto &f : fs)
    if (!std::strcmp(n, f.n) && off == f.off) {
      field.bits[2] = f.k << 16;
      field.declared = reinterpret_cast<void *>(static_cast<uintptr_t>(
          !std::strcmp(n, "_Atlas") || !std::strcmp(n, "flareAtlas") ? 4
          : !std::strcmp(n, "Elements")                              ? 5
          : !std::strcmp(n, "thisTransform")                         ? 7
          : !std::strcmp(n, "thisGameObject")                        ? 8
          : !std::strcmp(n, "flareBatchForSrp")                      ? 3
          : !std::strcmp(n, "_items")                                ? 6
                                                                     : 1));
      *out = &field;
      return true;
    }
  return false;
}
template <class T> void set(void *p, size_t off, T v) {
  std::memcpy(static_cast<unsigned char *>(p) + off, &v, sizeof v);
}
template <class T> bool mp4_actor_field(void *p, size_t off, T &out) {
  if (!p)
    return false;
  std::memcpy(&out, static_cast<unsigned char *>(p) + off, sizeof out);
  return true;
}
void *get_go(void *, Method *) { return go.b; }
struct {
  Binding component_gameobject;
} mp4_stage_profile;
template <class T> T mp4_equipment_call(const Binding &b) {
  return reinterpret_cast<T>(b.rva);
}
bool mp4_actor_list(void *list, void ***out, size_t *count, size_t cap) {
  void *a = nullptr;
  uint32_t n = 0;
  if (!mp4_actor_field(list, 16, a) || !mp4_actor_field(list, 24, n) || n > cap)
    return false;
  *out = reinterpret_cast<void **>(static_cast<unsigned char *>(a) + 32);
  *count = n;
  return true;
}
struct{Binding field_offset{27};}mp4_actor_profile;
struct{Binding field_flags{28};}mp4_cam_profile;
#include "proflare-cache-host.cpp"
uint64_t preparation(void *) { return prep; }
void original(void *p, Method *) {
  ++calls;
  if (original_throw)
    throw std::runtime_error("source");
  set(p, 248, static_cast<void *>(batch.b));
  set(p, 256, uint8_t(1));
  set(element.b, 32, p);
  set(element.b, 40, static_cast<void *>(atlas.b));
}
void reset() {
  for (auto *o :
       {&flare, &atlas, &elements, &array, &transform, &go, &batch, &element,
        &native, &tr_native, &go_native, &batch_native, &wrong}) {
    std::memset(o->b, 0, sizeof o->b);
    o->alive = true;
    objects[o->b] = o;
  }
  flare.kind = 1;
  element.kind = 2;
  batch.kind = 3;
  atlas.kind = 4;
  elements.kind = 5;
  array.kind = 6;
  transform.kind = 7;
  go.kind = 8;
  native.kind = 9;
  tr_native.kind = 10;
  go_native.kind = 11;
  batch_native.kind = 12;
  set(flare.b, 16, reinterpret_cast<uintptr_t>(native.b));
  set(native.b, 8, int32_t(123));
  set(flare.b, 32, static_cast<void *>(atlas.b));
  set(flare.b, 48, static_cast<void *>(elements.b));
  set(flare.b, 56, static_cast<void *>(transform.b));
  set(flare.b, 64, static_cast<void *>(go.b));
  set(transform.b, 16, reinterpret_cast<uintptr_t>(tr_native.b));
  set(go.b, 16, reinterpret_cast<uintptr_t>(go_native.b));
  set(batch.b, 16, reinterpret_cast<uintptr_t>(batch_native.b));
  set(elements.b, 16, static_cast<void *>(array.b));
  set(elements.b, 24, uint32_t(1));
  set(elements.b, 28, uint32_t(3));
  set(array.b, 24, size_t(1));
  set(array.b, 32, static_cast<void *>(element.b));
  mp4_stage_profile.component_gameobject.rva =
      reinterpret_cast<uintptr_t>(get_go);
  mp4_proflare_cache_preparation = preparation;
  mp4_proflare_start_trampoline = original;
  game = pins = true;
  observer_throw = original_throw = false;
  prep = 77;
  calls = 0;
  mp4_proflare_cache_foreign.store(false);
  methods[1] = 20;
}
int main(int argc, char **argv) {
  assert(argc == 2);
  reset();
  const char *c = argv[1];
  uint64_t receipt = 0;
  if (!std::strcmp(c, "normal")) {
    assert(mp4_proflare_cache_prepare(flare.b, nullptr, original, &receipt));
    assert(receipt && calls == 1);
    assert(mp4_proflare_cache_current(flare.b, &receipt));
  } else if (!std::strcmp(c, "ordinary")) {
    assert(mp4_proflare_start_invoke(flare.b, nullptr, original));
    assert(calls == 1);
  } else if (!std::strcmp(c, "unreceipted")) {
    original(flare.b, nullptr);
    assert(!mp4_proflare_cache_observe_completed(flare.b));
  } else if (!std::strcmp(c, "source_exception")) {
    original_throw = true;
    bool threw = false;
    try {
      mp4_proflare_start_invoke(flare.b, nullptr, original);
    } catch (const std::runtime_error &e) {
      threw = std::strcmp(e.what(), "source") == 0;
    }
    assert(threw && calls == 1 && !mp4_proflare_start_completion);
  } else if (!std::strcmp(c, "observer_exception")) {
    observer_throw = true;
    assert(!mp4_proflare_start_invoke(flare.b, nullptr, original));
    assert(calls == 1 && !mp4_proflare_start_completion);
    observer_throw = false;
  } else if (!std::strcmp(c, "unverified_original")) {
    mp4_proflare_start_trampoline = nullptr;
    assert(!mp4_proflare_cache_prepare(flare.b, nullptr, original, &receipt));
    assert(!calls);
    assert(!mp4_proflare_start_invoke(flare.b, nullptr, original));
    assert(calls == 1);
  } else if (!std::strcmp(c, "foreign")) {
    game = false;
    assert(!mp4_proflare_start_invoke(flare.b, nullptr, original));
    assert(calls == 1 && mp4_proflare_cache_foreign.load());
    game = true;
  } else if (!std::strcmp(c, "no_token")) {
    prep = 0;
    assert(!mp4_proflare_cache_prepare(flare.b, nullptr, original, &receipt));
    assert(!calls);
  } else if (!std::strcmp(c, "sun")) {
    set(flare.b, 229, uint8_t(1));
    assert(!mp4_proflare_cache_prepare(flare.b, nullptr, original, &receipt));
    assert(!calls);
  } else if (!std::strcmp(c, "helper")) {
    set(flare.b, 232, static_cast<void *>(go.b));
    assert(!mp4_proflare_cache_prepare(flare.b, nullptr, original, &receipt));
    assert(!calls);
  } else if (!std::strcmp(c, "other_owner")) {
    set(element.b, 32, static_cast<void *>(wrong.b));
    assert(!mp4_proflare_cache_prepare(flare.b, nullptr, original, &receipt));
    assert(!calls);
  } else if (!std::strcmp(c, "other_atlas")) {
    set(element.b, 40, static_cast<void *>(wrong.b));
    assert(!mp4_proflare_cache_prepare(flare.b, nullptr, original, &receipt));
    assert(!calls);
  } else if (!std::strcmp(c, "wrong_callback")) {
    methods[1] = 9;
    assert(!mp4_proflare_cache_prepare(flare.b, nullptr, original, &receipt));
    assert(!calls);
  } else if (!std::strcmp(c, "dead")) {
    flare.alive = false;
    assert(!mp4_proflare_cache_prepare(flare.b, nullptr, original, &receipt));
    assert(!calls);
  } else {
    assert(mp4_proflare_cache_prepare(flare.b, nullptr, original, &receipt));
    if (!std::strcmp(c, "native_changed"))
      set(flare.b, 16, reinterpret_cast<uintptr_t>(wrong.b));
    else if (!std::strcmp(c, "element_changed"))
      set(array.b, 32, static_cast<void *>(wrong.b));
    else if (!std::strcmp(c, "owner_changed"))
      set(element.b, 32, static_cast<void *>(wrong.b));
    else if (!std::strcmp(c, "atlas_changed"))
      set(flare.b, 32, static_cast<void *>(wrong.b));
    else if (!std::strcmp(c, "batch_changed"))
      set(flare.b, 248, static_cast<void *>(wrong.b));
    else if (!std::strcmp(c, "version_changed"))
      set(elements.b, 28, uint32_t(99));
    else if (!std::strcmp(c, "weak_expired"))
      roots[mp4_proflare_cache_births[0].weak[2]] = nullptr;
    else if (!std::strcmp(c, "weak_wrong"))
      roots[mp4_proflare_cache_births[0].weak[2]] = wrong.b;
    else if (!std::strcmp(c, "pins_lost"))
      pins = false;
    else
      assert(false);
    assert(!mp4_proflare_cache_current(flare.b, &receipt));
  }
  if (mp4_proflare_cache_births) {
    for (size_t i = 0; i < 128; ++i)
      mp4_proflare_cache_drop(mp4_proflare_cache_births[i]);
    std::free(mp4_proflare_cache_births);
    mp4_proflare_cache_births = nullptr;
  }
  assert(roots.empty());
  std::puts("passed");
}
