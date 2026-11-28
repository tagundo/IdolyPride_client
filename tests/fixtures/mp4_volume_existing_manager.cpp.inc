#include "mp4_actor_state.hpp"
namespace mp4actor = idoly_mp4_actor;
struct Mp4SceneWitness {
  void *player = nullptr, *camera = nullptr;
  uint64_t generation = 17;
};
struct Mp4RenderContext {
  void *pointer = nullptr;
};
struct Mp4RenderSubmission {
  Mp4RenderContext context{};
  uint64_t source_generation = 0, job_generation = 0, tick = 0, draw_token = 0;
  bool prewarm = false;
};
using Mp4CameraOffset = size_t (*)(const void *);
using Mp4CameraFlag = uint32_t (*)(const void *);
using Mp4CameraBool = bool (*)(void *);
using Mp4CameraValueSize = int32_t (*)(void *, uint32_t *);
std::map<void *, uint32_t> offsets, flags;
std::map<void *, bool> value_classes;
std::map<void *, void *> parents;
const char *class_name(void *k) {
  const auto &s = objects[k].name;
  size_t dot = s.rfind('.');
  return s.c_str() + (dot == std::string::npos ? 0 : dot + 1);
}
const char *class_namespace(void *k) {
  static std::map<void *, std::string> names;
  const auto &s = objects[k].name;
  size_t dot = s.rfind('.');
  return (names[k] = dot == std::string::npos ? "" : s.substr(0, dot)).c_str();
}
void *class_parent(void *k) { return parents[k]; }
size_t field_offset(const void *f) { return offsets[const_cast<void *>(f)]; }
uint32_t field_flags(const void *f) { return flags[const_cast<void *>(f)]; }
bool is_value(void *k) { return value_classes[k]; }
int32_t value_size(void *, uint32_t *align) {
  *align = 4;
  return 4;
}
unsigned barrier_calls = 0;
void barrier(void *owner, void **slot, void *value) {
  ++barrier_calls;
  assert(mp4_actor_mapped(slot, 8, true));
  size_t at =
      reinterpret_cast<uintptr_t>(slot) - reinterpret_cast<uintptr_t>(owner);
  put(owner, at, value);
}
struct FactoryHost {
  uint64_t sequence = 1;
  idoly_mp4_private_volume::Frame published{};
} mp4_volume_factory_host;
bool gpu_ready = false;
unsigned gpu_draw_calls = 0, gpu_final_calls = 0;
bool mp4_gpu_draw_fenced(uint64_t job, uint64_t token) {
  assert(job == 77 && token == 123);
  ++gpu_draw_calls;
  return gpu_ready;
}
bool mp4_gpu_final_fenced(uint64_t job) {
  assert(job == 77);
  ++gpu_final_calls;
  return gpu_ready;
}
namespace mp4pv = idoly_mp4_private_volume;

// SHIPPING_VOLUME_ASSEMBLY_PINS
void *mp4_volume_factory_class(const mp4camp::Binding &p, const char *) {
  return descriptors[p.rva];
}
struct Mp4ActorTempRoot {
  uint32_t root = 0;
  explicit Mp4ActorTempRoot(void *p) : root(mp4_retain(p)) {}
  ~Mp4ActorTempRoot() {
    if (root)
      weak_free(root);
  }
  void *get() { return weak_get(root); }
};

// SHIPPING_VOLUME_EXISTING_MANAGER
int main(int argc, char **argv) {
  assert(argc == 2);
  std::string mode = argv[1];
  mp4_cam_profile.field_flags.rva = reinterpret_cast<uintptr_t>(field_flags);
  mp4_cam_profile.field_offset.rva = reinterpret_cast<uintptr_t>(field_offset);
  void *managerclass = klass("UnityEngine.Rendering.VolumeManager"),
       *lazyclass = klass("System.Lazy`1"),
       *helperclass = klass("System.LazyHelper"),
       *factoryclass = klass("System.Func`1");
  descriptors[mp4_volume_assembly_pins.manager.rva] = managerclass;
  put(managerclass, 0xe0, uint32_t(1));
  void *statics = object("Fixture.Statics"), *lazy = object("System.Lazy`1"),
       *manager = object("UnityEngine.Rendering.VolumeManager");
  put(managerclass, 0xb8, statics);
  put(statics, 0, lazy);
  put(lazy, 32, manager);
  auto field = [&](void *k, const char *name, size_t at, void *t,
                   uint32_t f = 0) {
    void *fi = object("Fixture.Field"), *type = object("Fixture.Type");
    fields[{k, name}] = fi;
    offsets[fi] = at;
    flags[fi] = f;
    field_types[fi] = type;
    type_classes[type] = t;
    return fi;
  };
  void *instance = field(managerclass, "s_Instance", 0, lazyclass, 48);
  void *state = field(lazyclass, "_state", 16, helperclass);
  void *factory = field(lazyclass, "_factory", 24, factoryclass);
  void *value = field(lazyclass, "_value", 32, managerclass);
  if (mode == "baseline") {
    assert(mp4_volume_existing_manager() == manager);
    assert(roots.empty());
  } else if (mode == "state_pending") {
    put(lazy, 16, object("System.LazyHelper"));
    assert(!mp4_volume_existing_manager());
  } else if (mode == "state_faulted") {
    put(lazy, 16, object("System.LazyHelper.Faulted"));
    assert(!mp4_volume_existing_manager());
  } else if (mode == "manager_uninitialized") {
    put(managerclass, 0xe0, uint32_t(0));
    assert(!mp4_volume_existing_manager());
  } else if (mode == "no_existing_value") {
    put(lazy, 32, static_cast<void *>(nullptr));
    assert(!mp4_volume_existing_manager());
  } else if (mode == "wrong_closed_value_type") {
    type_classes[field_types[value]] = klass("Foreign.Manager");
    assert(!mp4_volume_existing_manager());
  } else if (mode == "open_generic_zero_offset") {
    offsets[state] = 0;
    assert(!mp4_volume_existing_manager());
  } else if (mode == "foreign_lazy") {
    put(statics, 0, object("Foreign.Lazy`1"));
    assert(!mp4_volume_existing_manager());
  } else if (mode == "not_static_readonly") {
    flags[instance] = 16;
    assert(!mp4_volume_existing_manager());
  } else if (mode == "wrong_factory") {
    type_classes[field_types[factory]] = klass("Foreign.Func`1");
    assert(!mp4_volume_existing_manager());
  } else if (mode == "root_failure") {
    root_fail = true;
    assert(!mp4_volume_existing_manager());
  } else
    assert(false);
  assert(roots.empty());
  for (void *a : allocations)
    ::free(a);
  std::printf("%s passed\n", mode.c_str());
}
