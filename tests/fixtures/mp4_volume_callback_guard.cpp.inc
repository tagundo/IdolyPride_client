#include "mp4_actor_state.hpp"
namespace mp4actor = idoly_mp4_actor;
using Mp4CameraOffset = size_t (*)(const void *);
using Mp4CameraFlag = uint32_t (*)(const void *);
using Mp4CameraFields = void *(*)(void *, void **);
using Mp4CameraValueSize = int32_t (*)(void *, uint32_t *);
bool mp4_source_verified = true, mp4_actor_source_verified = true,
     ctor_context = true;
bool mp4_volume_assembly_ctor_context(uint64_t e, void *m) {
  return ctor_context && e == 17 && m;
}
std::map<void *, uint32_t> offsets, flags;
std::map<void *, void *> parents;
std::map<void *, std::vector<void *>> declared_fields;
const char *class_name(void *k) {
  auto &s = objects[k].name;
  auto dot = s.rfind('.');
  return s.c_str() + (dot == std::string::npos ? 0 : dot + 1);
}
const char *class_namespace(void *k) {
  static std::map<void *, std::string> ns;
  auto &s = objects[k].name;
  auto dot = s.rfind('.');
  return (ns[k] = dot == std::string::npos ? "" : s.substr(0, dot)).c_str();
}
void *class_parent(void *k) { return parents[k]; }
size_t field_offset(const void *f) { return offsets[const_cast<void *>(f)]; }
uint32_t field_flags(const void *f) { return flags[const_cast<void *>(f)]; }
void *class_fields(void *k, void **it) {
  size_t n = reinterpret_cast<uintptr_t>(*it);
  if (n >= declared_fields[k].size())
    return nullptr;
  *it = reinterpret_cast<void *>(n + 1);
  return declared_fields[k][n];
}
int32_t value_size(void *, uint32_t *a) {
  *a = 4;
  return 16;
}
bool mp4_mapped(uintptr_t p, size_t n, bool w) {
  return mp4_actor_mapped(reinterpret_cast<void *>(p), n, w);
}
bool mp4_volume_factory_prefix(const mp4camp::Binding &) {
  return true;
} // typed original query boundary fixture
void *mp4_volume_factory_class(const mp4camp::Binding &p, const char *) {
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
std::map<uintptr_t, std::vector<uint8_t>> hook_receipts;
bool mp4_hook_was_statically_verified(const mp4game::Binding &p) {
  auto i = hook_receipts.find(p.rva);
  return i != hook_receipts.end() &&
         !std::memcmp(i->second.data(), p.prefix, 16);
}

// SHIPPING_VOLUME_CALLBACK_GUARD
void *method(void *k, const char *name, uint8_t argc,
             const mp4actor::ActorBinding &p, void *owner = nullptr) {
  void *m = object("Fixture.Method");
  put(m, 0, image_base + p.rva);
  put(m, 32, owner ? owner : k);
  put(m, 82, argc);
  methods[{k, name}] = m;
  return m;
}
void add_param_method(void *k, void *base, const char *name, uint8_t argc,
                      unsigned slot, const mp4actor::ActorBinding &p,
                      void *owner = nullptr) {
  void *m = method(k, name, argc, p, owner ? owner : base);
  put(k, 0x138 + slot * 16, image_base + p.rva);
  put(k, 0x140 + slot * 16, m);
}
void *pinclass(const mp4actor::ActorBinding &p, const char *name) {
  void *k = klass(name);
  descriptors[p.rva] = k;
  reflections[k] = object("System.RuntimeType");
  return k;
}
int main(int argc, char **argv) {
  assert(argc == 2);
  std::string mode = argv[1];
  size_t bytes = 0;
  for (const auto &s : mp4_volume_ctor_segments)
    bytes = std::max(bytes, size_t(s.rva + s.count));
  void *image = make("Fixture.OriginalAOTCode", bytes + 32);
  image_base = reinterpret_cast<uintptr_t>(image);
  for (const auto &s : mp4_volume_ctor_segments)
    std::memcpy(static_cast<uint8_t *>(image) + s.rva, s.bytes, s.count);
  mp4_cam_profile.field_flags.rva = reinterpret_cast<uintptr_t>(field_flags);
  mp4_cam_profile.field_offset.rva = reinterpret_cast<uintptr_t>(field_offset);
  mp4_cam_profile.class_fields.rva = reinterpret_cast<uintptr_t>(class_fields);
  mp4_cam_profile.class_value_size.rva =
      reinterpret_cast<uintptr_t>(value_size);
  auto &b = mp4_volume_base_callbacks;
  void *base =
      pinclass(b.component_type, "UnityEngine.Rendering.VolumeComponent");
  void *param =
      pinclass(b.parameter_type, "UnityEngine.Rendering.VolumeParameter");
  for (const auto &p : mp4_volume_param_callback_pins) {
    void *k = pinclass(p.type, p.name);
    parents[k] = param;
    add_param_method(k, param, "get_overrideState", 0, 4,
                     b.parameter_get_override);
    add_param_method(k, param, "set_overrideState", 1, 5, p.set_override);
    add_param_method(k, param, "OnEnable", 0, 8, p.on_enable);
    add_param_method(k, param, "OnDisable", 0, 9, p.on_disable);
    add_param_method(k, param, "Release", 0, 10, p.release,
                     p.curve ? k : param);
  }
  for (const auto &p : mp4_volume_ctor_pins) {
    void *k = pinclass(p.type, p.name);
    parents[k] = base;
    method(k, ".ctor", 0, p.ctor);
    method(k, "OnEnable", 0, b.component_enable, base);
    method(k, "OnDisable", 0, b.component_disable, base);
    method(k, "OnDestroy", 0, b.component_destroy, base);
    method(k, "Release", 0, b.component_release, base);
    for (const auto &s : mp4_volume_component_schemas)
      if (!std::strcmp(s.name, p.name))
        for (size_t n = 0; n < s.count; ++n) {
          auto &f = s.fields[n];
          void *fi = object("Fixture.Field"), *t = object("Fixture.Type");
          offsets[fi] = f.offset;
          declared_fields[k].push_back(fi);
          field_types[fi] = t;
          type_classes[t] = klass(f.type);
        }
    if (k == descriptors[b.mirror_type.rva]) {
      method(k, ".cctor", 0, b.mirror_cctor);
      void *f = object("Fixture.Field"), *t = object("Fixture.Type"),
           *a = klass("UnityEngine.Plane[]");
      fields[{k, "Planes"}] = f;
      flags[f] = 16;
      field_types[f] = t;
      type_classes[t] = a;
    }
  }
  // Native reflection calls are explicit fixture boundaries; no constructor or
  // callback body is executed by this metadata/whole-byte verifier harness.
  using Rank = int32_t (*)(void *);
  using Elem = void *(*)(void *);
  const Rank rank = +[](void *) -> int32_t { return 1; };
  const Elem elem =
      +[](void *) -> void * { return klass("UnityEngine.Plane"); };
  mp4_cam_profile.class_rank.rva = reinterpret_cast<uintptr_t>(rank);
  mp4_cam_profile.class_element.rva = reinterpret_cast<uintptr_t>(elem);
  const auto &p = mp4_volume_ctor_pins[0];
  void *k = descriptors[p.type.rva], *type = reflections[k],
       *manager = object("UnityEngine.Rendering.VolumeManager");
  if (mode == "bytes_tampered") {
    static_cast<uint8_t *>(image)[mp4_volume_ctor_segments[0].rva] ^= 1;
    assert(!mp4_volume_ctor_code_closed());
  } else if (mode == "foreign_hook") {
    auto r = mp4_volume_ctor_segments[0].rva;
    static_cast<uint8_t *>(image)[r] ^= 1;
    assert(!mp4_volume_ctor_code_closed());
  } else if (mode == "own_hook") {
    auto r = mp4_volume_ctor_segments[0].rva;
    hook_receipts[r] =
        std::vector<uint8_t>(static_cast<uint8_t *>(image) + r,
                             static_cast<uint8_t *>(image) + r + 16);
    static_cast<uint8_t *>(image)[r] ^= 1;
    assert(mp4_volume_ctor_code_closed());
  } else if (mode == "lost_source") {
    mp4_source_verified = false;
    assert(!mp4_volume_ctor_code_closed());
  } else if (mode == "context_lost") {
    ctor_context = false;
    assert(!mp4_volume_component_callbacks_closed(17, manager, type, p.name));
  } else if (mode == "wrong_ctor") {
    put(const_cast<void *>(methods[{k, ".ctor"}]), 0, uintptr_t(123));
    assert(!mp4_volume_component_callbacks_closed(17, manager, type, p.name));
  } else if (mode == "derived_enable") {
    put(const_cast<void *>(methods[{k, "OnEnable"}]), 32, k);
    assert(!mp4_volume_component_callbacks_closed(17, manager, type, p.name));
  } else if (mode == "unknown_cctor") {
    method(k, ".cctor", 0, p.ctor);
    assert(!mp4_volume_component_callbacks_closed(17, manager, type, p.name));
  } else if (mode == "wrong_reflection") {
    assert(
        !mp4_volume_component_callbacks_closed(17, manager, manager, p.name));
  } else if (mode == "bad_slot") {
    void *q = descriptors[mp4_volume_param_callback_pins[0].type.rva];
    put(q, 0x138 + 5 * 16, uintptr_t(123));
    assert(!mp4_volume_parameter_callbacks_closed(
        q, mp4_volume_param_callback_pins[0], param));
  } else if (mode == "slot_method_owner") {
    void *q = descriptors[mp4_volume_param_callback_pins[0].type.rva];
    put(const_cast<void *>(methods[{q, "OnEnable"}]), 32, q);
    assert(!mp4_volume_parameter_callbacks_closed(
        q, mp4_volume_param_callback_pins[0], param));
  } else if (mode == "wrong_param_type") {
    void *f = declared_fields[k][0];
    type_classes[field_types[f]] = klass("Foreign.Param");
    assert(!mp4_volume_component_callbacks_closed(17, manager, type, p.name));
  } else if (mode == "static_param_field") {
    flags[declared_fields[k][0]] = 16;
    assert(!mp4_volume_component_callbacks_closed(17, manager, type, p.name));
  } else if (mode == "all32") {
    for (const auto &q : mp4_volume_ctor_pins) {
      void *c = descriptors[q.type.rva];
      assert(mp4_volume_component_callbacks_closed(17, manager, reflections[c],
                                                   q.name));
    }
  } else
    assert(false);
  for (void *a : allocations)
    ::free(a);
  std::printf("%s passed\n", mode.c_str());
}
