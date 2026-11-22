#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include "proflare-registry-scope.hpp.inc"
using Method = void;
struct Binding {
  uintptr_t rva = 0;
};
namespace mp4game{using Binding=::Binding;}
bool mp4_source_verified=true;uintptr_t image_base=0;
bool mp4_prefix(const Binding&){return true;}bool mp4_hook_was_statically_verified(const Binding&){return false;}
bool mp4_proflare_start_callable(void(*)(void*,Method*)){return true;}
struct Pin {
  void *klass = nullptr;
};
using Mp4TimelineTypePin = Pin;
struct Class {
  const char *name;
  const char *space;
  bool value = false;
  int rank = 0, width = 8;
  Class *element = nullptr;
};
Class c_batch{"ProFlareBatchForSRP", ""}, c_flare{"ProFlare", ""},
    c_data{"ProFlareBatchForSRPData", ""}, c_int{"Int32", "System", true, 0, 4},
    c_entry{"Entry`2", "System.Collections.Generic", true, 0, 16};
Class c_list{"List`1", "System.Collections.Generic"},
    c_ld{"List`1", "System.Collections.Generic"},
    c_queue{"Queue`1", "System.Collections.Generic"},
    c_dict{"Dictionary`2", "System.Collections.Generic"};
Class c_af{"ProFlare[]", "", false, 1, 8, &c_flare},
    c_ad{"Data[]", "", false, 1, 8, &c_data},
    c_ai{"Int32[]", "System", false, 1, 4, &c_int},
    c_ae{"Entry[]", "", false, 1, 16, &c_entry};
struct Obj {
  alignas(16) uint8_t b[512]{};
};
Obj batch, atlas, list, larray, queue, qarray, dict, buckets, entries, data,
    darray, flare_a, flare_b, native, native_a, native_b;
std::map<void *, Class *> classes;
std::map<uint32_t, void *> roots;
uint32_t seq = 1;
bool physical = true, source = true, held = true, operation = true;
int barriers = 0;
struct Field {
  uint8_t type[16]{};
  size_t offset = 0;
  Class *declared = nullptr;
};
std::map<std::pair<Class *, std::string>, Field> fields;
template <class T> void put(void *p, size_t at, T v) {
  std::memcpy(static_cast<uint8_t *>(p) + at, &v, sizeof v);
}
template <class T> bool mp4_actor_field(void *p, size_t at, T &v) {
  if (!p)
    return false;
  std::memcpy(&v, static_cast<uint8_t *>(p) + at, sizeof v);
  return true;
}
void *class_of(void *p) { return classes[p]; }
auto object_class = class_of;
const char *class_name(void *k) { return static_cast<Class *>(k)->name; }
const char *class_namespace(void *k) { return static_cast<Class *>(k)->space; }
void *find_field(void *k, const char *n) {
  auto i = fields.find({static_cast<Class *>(k), n});
  return i == fields.end() ? nullptr : &i->second;
}
auto font_field = find_field;
const void *type_of(void *f) { return f; }
auto font_field_type = type_of;
void *font_class_type(const void *f) {
  return static_cast<const Field *>(f)->declared;
}
size_t offset_of(void *f) { return static_cast<Field *>(f)->offset; }
int32_t rank_of(void *k) { return static_cast<Class *>(k)->rank; }
void *element_of(void *k) { return static_cast<Class *>(k)->element; }
bool value_of(void *k) { return static_cast<Class *>(k)->value; }
int32_t width_of(void *k, uint32_t *a) {
  *a = 4;
  return static_cast<Class *>(k)->width;
}
bool mp4_root_track_field(void *o, const char *n, size_t at,
                          void **out = nullptr) {
  void *f = font_field(object_class(o), n);
  if (!f || offset_of(f) != at)
    return false;
  if (out)
    *out = f;
  return true;
}
void add(Class *c, const char *n, size_t at, Class *type = nullptr,
         int kind = 8) {
  Field f{};
  f.offset = at;
  f.declared = type;
  put(f.type, 8, uint32_t(kind << 16));
  fields[{c, n}] = f;
}
bool mp4_type_is(void *p, const char *n) {
  auto *k = classes[p];
  return k && ((!std::strcmp(n, "System.Array") && k->rank == 1) ||
               (!std::strcmp(n, "UnityEngine.Object") &&
                (k == &c_batch || k == &c_flare)));
}
bool mp4_alive(void *p) { return p && classes.count(p); }
void *mp4_timeline_class(const Pin &p) { return p.klass; }
bool mp4_timeline_exact(void *p, const Pin &pin) {
  return p && object_class(p) == pin.klass;
}
struct {
  Pin batch{&c_batch}, flare{&c_flare}, data{&c_data};
 Binding enable{11},disable{12};
} mp4_proflare_pins;
struct {
  Binding class_rank{reinterpret_cast<uintptr_t>(rank_of)},
      class_element{reinterpret_cast<uintptr_t>(element_of)},
      class_value_type{reinterpret_cast<uintptr_t>(value_of)},
      class_value_size{reinterpret_cast<uintptr_t>(width_of)},
      field_offset{reinterpret_cast<uintptr_t>(offset_of)};
} mp4_cam_profile;
template <class T> T mp4_cam_call(const Binding &b) {
  return reinterpret_cast<T>(b.rva);
}
size_t mp4_array_length(void *a) {
  size_t n = 0;
  mp4_actor_field(a, 24, n);
  return n;
}
void *mp4_array_data(void *a) { return static_cast<uint8_t *>(a) + 32; }
bool mp4_actor_mapped(void *p, size_t, bool) { return p != nullptr; }
uint32_t mp4_retain(void *p) {
  auto h = seq++;
  roots[h] = p;
  return h;
}
void *target(uint32_t h) { return roots[h]; }
auto weak_get = target;
void drop(uint32_t h) { roots.erase(h); }
auto weak_free = drop;
bool game_call() { return true; }
bool mp4_proflare_data_pins() { return true; }
bool mp4_control_source_current(void *, uint64_t e) { return source && e == 7; }
bool mp4_stage_clock_held(void *) { return held; }
struct Mp4ProFlareCacheImage {
  uintptr_t native = 0;
  int32_t instance = 0;
  void *atlas = nullptr, *batch = nullptr;
};
bool mp4_proflare_cache_image(void *f, Mp4ProFlareCacheImage *out, bool) {
  out->native = f == flare_a.b ? reinterpret_cast<uintptr_t>(native_a.b)
                               : reinterpret_cast<uintptr_t>(native_b.b);
  out->instance = f == flare_a.b ? 1 : 257;
  out->atlas = atlas.b;
  out->batch = batch.b;
  return f == flare_a.b || f == flare_b.b;
}
bool mp4_proflare_cache_current(void *f, uint64_t *out) {
  *out = f == flare_a.b ? 11 : 12;
  return f == flare_a.b || f == flare_b.b;
}
uint64_t (*mp4_proflare_cache_preparation)(void *) = nullptr;
std::atomic<bool> mp4_proflare_cache_foreign{false};
struct {
  bool lifecycle_current(void *) const { return true; }
  uint64_t restoring_receipt(void *) const { return 99; }
} mp4_activation_targets;
bool mp4_activation_callback_execution(void *) { return false; }
struct Origin {
  uint64_t receipt = 0;
} origin;
Origin *mp4_activation_origin = &origin;
void mp4_camera_barrier(void *, void **slot, void *v) {
  ++barriers;
  *slot = v;
}
template <class T> bool mp4_stage_store(void *p, size_t at, T v) {
  put(p, at, v);
  return true;
}
struct {
  bool invalidated = false;
  const char *error = nullptr;
} mp4_stage_host;
uint64_t mp4_proflare_start_invoke(void *f, Method *m,
                                   void (*original)(void *, Method *)) {
  original(f, m);
  return 11;
}
#include "proflare-registry-host.cpp"
bool physical_owner(void *b, uint64_t *r) {
  *r = 123;
  return physical && b == batch.b;
}
uint64_t op(void *) { return operation ? 77 : 0; }
bool handoff(void *, mp4pf::Result) { return false; }
void setup() {
  for (auto p : {std::pair{&batch, &c_batch},
                 {&list, &c_list},
                 {&larray, &c_af},
                 {&queue, &c_queue},
                 {&qarray, &c_ai},
                 {&dict, &c_dict},
                 {&buckets, &c_ai},
                 {&entries, &c_ae},
                 {&data, &c_ld},
                 {&darray, &c_ad},
                 {&flare_a, &c_flare},
                 {&flare_b, &c_flare}})
    classes[p.first->b] = p.second;
  add(&c_batch, "_atlas", 40, nullptr, 18);
  add(&c_batch, "FlaresList", 48, &c_list, 21);
  add(&c_batch, "_flareEmptyQueue", 56, &c_queue, 21);
  add(&c_batch, "_flareInstanceIDTable", 64, &c_dict, 21);
  add(&c_batch, "_batchDatas", 80, &c_ld, 21);
  for (auto *c : {&c_list, &c_ld}) {
    add(c, "_items", 16, c == &c_list ? &c_af : &c_ad, 29);
    add(c, "_size", 24);
    add(c, "_version", 28);
    add(c, "_syncRoot", 32, nullptr, 28);
  }
  const char *qn[] = {"_array", "_head",    "_tail",
                      "_size",  "_version", "_syncRoot"};
  size_t qo[] = {16, 24, 28, 32, 36, 40};
  for (int i = 0; i < 6; ++i)
    add(&c_queue, qn[i], qo[i], i ? nullptr : &c_ai, i ? 8 : 29);
  const char *dn[] = {"_buckets",  "_entries",   "_count",    "_version",
                      "_freeList", "_freeCount", "_comparer", "_keys",
                      "_values",   "_syncRoot"};
  size_t d[] = {16, 24, 32, 36, 40, 44, 48, 56, 64, 72};
  for (int i = 0; i < 10; ++i)
    add(&c_dict, dn[i], d[i],
        i == 0   ? &c_ai
        : i == 1 ? &c_ae
                 : nullptr,
        i < 2 ? 29 : 8);
  const char *en[] = {"hashCode", "next", "key", "value"};
  for (int i = 0; i < 4; ++i)
    add(&c_entry, en[i], 16 + i * 4);
  put(batch.b, 16, reinterpret_cast<uintptr_t>(native.b));
  put(batch.b, 40, static_cast<void *>(atlas.b));
  put(batch.b, 48, static_cast<void *>(list.b));
  put(batch.b, 56, static_cast<void *>(queue.b));
  put(batch.b, 64, static_cast<void *>(dict.b));
  put(batch.b, 80, static_cast<void *>(data.b));
  put(list.b, 16, static_cast<void *>(larray.b));
  put(list.b, 24, uint32_t(2));
  put(list.b, 28, uint32_t(4));
  put(larray.b, 24, size_t(8));
  put(larray.b, 32, static_cast<void *>(flare_a.b));
  put(data.b, 16, static_cast<void *>(darray.b));
  put(darray.b, 24, size_t(8));
  put(queue.b, 16, static_cast<void *>(qarray.b));
  put(queue.b, 28, uint32_t(1));
  put(queue.b, 32, uint32_t(1));
  put(qarray.b, 24, size_t(8));
  put(qarray.b, 32, int32_t(1));
  put(dict.b, 16, static_cast<void *>(buckets.b));
  put(dict.b, 24, static_cast<void *>(entries.b));
  put(dict.b, 32, uint32_t(1));
  put(dict.b, 40, int32_t(-1));
  put(buckets.b, 24, size_t(8));
  put(buckets.b, 36, int32_t(1));
  put(entries.b, 24, size_t(8));
  put(entries.b, 32, mp4pf::Entry{1, -1, 1, 0});
  put(flare_a.b, 16, reinterpret_cast<uintptr_t>(native_a.b));
  put(native_a.b, 8, int32_t(1));
  put(flare_b.b, 16, reinterpret_cast<uintptr_t>(native_b.b));
  put(native_b.b, 8, int32_t(257));
  mp4_proflare_registry_physical = physical_owner;
  mp4_proflare_registry_operation = op;
  mp4_proflare_registry_handoff = handoff;
}
int main(int argc, char **argv) {
  assert(argc == 2);
  setup();
  std::string c = argv[1];
  void *flares[] = {flare_a.b, flare_b.b};
  if (c == "wrong_field")
    fields[{&c_dict, "_version"}].offset = 99;
  if (c == "wrong_entry")
    fields[{&c_entry, "value"}].offset = 99;
  if (c == "wrong_element")
    c_ai.element = &c_flare;
  if (c == "wrong_array")
    classes[qarray.b] = &c_ae;
  if (c == "wrong_owner")
    physical = false;
  auto result = mp4_proflare_registry_capture(batch.b, flares, 2, 7);
  bool should = c == "normal" || c == "restore" || c == "no_operation" ||
                c == "no_restore" || c == "source_lost";
  assert((result == mp4pf::Result::ok) == should);
  if (should) {
    mp4pf::Image im{};
    assert(mp4_proflare_registry_read(&mp4_proflare_registry_host, &im));
    assert(im.list.count == 2 && im.queue.rows[0] == 1 &&
           im.dictionary.rows[0].value == 0);
    if (c == "normal")
      assert(mp4_proflare_registry_scope.current());
    if (c == "restore") {
      assert(mp4_proflare_registry_restore() == mp4pf::Result::ok);
      assert(barriers == 18);
    }
    if (c == "no_operation") {
      operation = false;
      assert(mp4_proflare_registry_restore() == mp4pf::Result::failed);
      assert(!barriers);
    }
    if (c == "source_lost") {
      source = false;
      assert(mp4_proflare_registry_scope.current());
    }
    if (c == "no_restore") {
      void *rows[8]{};
      int32_t q[8]{}, b[8]{};
      mp4pf::Entry e[8]{};
      assert(!mp4_proflare_registry_write(&mp4_proflare_registry_host, im, rows,
                                          q, b, e,rows));
      assert(!barriers);
    }
  }
  mp4_proflare_registry_release();
  assert(roots.empty());
  std::puts("passed");
}
