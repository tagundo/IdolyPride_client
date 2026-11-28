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

// SHIPPING_VOLUME_ASSEMBLY_FIELDS
void *make_field(void *owner, const char *name, uint32_t offset,
                 void *valueclass, uint32_t kind) {
  void *f = object("Fixture.Field"), *type = object("Fixture.Type");
  fields[{object_class(owner), name}] = f;
  field_types[f] = type;
  type_classes[type] = valueclass;
  offsets[f] = offset;
  put(type, 8, kind << 16);
  return f;
}
int main(int argc, char **argv) {
  assert(argc == 2);
  std::string mode = argv[1];
  auto &h = mp4_volume_assembly;
  h.manager = object("UnityEngine.Rendering.VolumeManager");
  h.additional =
      object("UnityEngine.Rendering.Universal.UniversalAdditionalCameraData");
  h.manager_class = object_class(h.manager);
  h.additional_class = object_class(h.additional);
  h.manager_root = mp4_retain(h.manager);
  h.additional_root = mp4_retain(h.additional);
  h.source.generation = 17;
  mp4_cam_profile.field_offset.rva = reinterpret_cast<uintptr_t>(field_offset);
  mp4_cam_profile.field_flags.rva = reinterpret_cast<uintptr_t>(field_flags);
  mp4_cam_profile.class_value_type.rva = reinterpret_cast<uintptr_t>(is_value);
  mp4_cam_profile.class_value_size.rva =
      reinterpret_cast<uintptr_t>(value_size);
  mp4_cam_profile.write_barrier.rva = reinterpret_cast<uintptr_t>(barrier);
  void *stackclass = klass("Fixture.Stack"), *sortclass = klass("Fixture.Sort"),
       *dirtyclass = klass("Fixture.Dirty"),
       *listclass = klass("Fixture.Colliders");
  for (size_t n = 0; n < 8; ++n) {
    void *k = n == 0 || n == 7 ? stackclass
              : n == 2         ? sortclass
              : n == 4         ? dirtyclass
                               : listclass;
    make_field(h.manager, mp4_volume_assembly_manager_names[n],
               mp4_volume_assembly_manager_offsets[n], k, 18);
    assert(mp4_volume_assembly_field(
        h.manager, mp4_volume_assembly_manager_names[n],
        mp4_volume_assembly_manager_offsets[n], true, h.fields[n]));
  }
  make_field(h.additional, "m_VolumeStack", 120, stackclass, 18);
  assert(mp4_volume_assembly_field(h.additional, "m_VolumeStack", 120, true,
                                   h.fields[8]));
  void *enumclass =
      klass("UnityEngine.Rendering.Universal.VolumeFrameworkUpdateMode");
  value_classes[enumclass] = true;
  void *modefield = make_field(
      h.additional, "m_VolumeFrameworkUpdateModeOption", 72, enumclass, 17);
  put(h.additional, 72, int32_t(2));
  assert(mp4_volume_assembly_field(h.additional,
                                   "m_VolumeFrameworkUpdateModeOption", 72,
                                   false, h.fields[9]));
  h.fields_ready=true;
  mp4pv::Frame frame{object("Fixture.Stack"), object("Fixture.Sort"),
                     object("Fixture.Dirty"), object("Fixture.Colliders")};
  mp4_volume_factory_host.published = frame;
  if (mode == "static_field") {
    flags[modefield] = 16;
    Mp4VolumeAssemblyField out{};
    assert(!mp4_volume_assembly_field(
        h.additional, "m_VolumeFrameworkUpdateModeOption", 72, false, out));
    goto finish;
  }
  if (mode == "wrong_offset") {
    offsets[modefield] = 80;
    Mp4VolumeAssemblyField out{};
    assert(!mp4_volume_assembly_field(
        h.additional, "m_VolumeFrameworkUpdateModeOption", 72, false, out));
    goto finish;
  }
  if (mode == "wrong_enum") {
    objects[enumclass].name = "Unproven.Enum";
    Mp4VolumeAssemblyField out{};
    assert(!mp4_volume_assembly_field(
        h.additional, "m_VolumeFrameworkUpdateModeOption", 72, false, out));
    goto finish;
  }
  if (mode == "lost_root") {
    weak_free(h.manager_root);
    void *v = nullptr;
    assert(!mp4_volume_assembly_ref(h.manager, 16, &v));
    goto finish;
  }
  if (mode == "readonly_slot") {
    mp4_volume_assembly_ref_set(h.manager, 24, frame.stack);
    assert(!barrier_calls);
    goto finish;
  }
  if (mode == "wrong_reference_type") {
    mp4_volume_assembly_ref_set(h.manager, 16, object("Foreign.Value"));
    assert(!barrier_calls);
    goto finish;
  }
  if (mode == "reference_barrier") {
    mp4_volume_assembly_ref_set(h.manager, 16, frame.stack);
    void *v = nullptr;
    assert(barrier_calls == 1 && mp4_volume_assembly_ref(h.manager, 16, &v) &&
           v == frame.stack);
    goto finish;
  }
  if (mode == "mode_value") {
    mp4_volume_assembly_mode_set(h.additional, 1);
    int32_t v = 0;
    assert(!barrier_calls && mp4_volume_assembly_mode(h.additional, &v) &&
           v == 1);
    mp4_volume_assembly_mode_set(h.additional, 4);
    assert(mp4_volume_assembly_mode(h.additional, &v) && v == 1);
    goto finish;
  }
  if (mode == "manager_alias") {
    put(h.manager, 32, frame.sorted);
    assert(!mp4_volume_assembly_no_alias(frame));
    goto finish;
  }
  if (mode == "camera_alias") {
    put(h.additional, 120, frame.stack);
    assert(!mp4_volume_assembly_no_alias(frame));
    goto finish;
  }
  if(mode=="partial_readonly_capture") {
    h.fields_ready=false;mp4_volume_factory_host.published={};
    assert(mp4_volume_assembly_final_fenced(17) && !gpu_final_calls);
    goto finish;
  }
  if(mode=="partial_factory_not_unpublished") {
    h.fields_ready=false;h.factory_duty=true;mp4_volume_factory_host.published={};
    assert(!mp4_volume_assembly_final_fenced(17));
    goto finish;
  }
  assert(mp4_volume_assembly_no_alias(frame));
  if (mode == "unpublished") {
    assert(mp4_volume_assembly_draw_fenced(17, 1) &&
           mp4_volume_assembly_final_fenced(17) && !gpu_draw_calls &&
           !gpu_final_calls);
    goto finish;
  }
  h.receipt = {17, 77, 123, 1, true, true, true, false};
  if (mode == "wrong_source") {
    h.receipt.source = 18;
    assert(!mp4_volume_assembly_draw_fenced(17, 1) &&
           !mp4_volume_assembly_final_fenced(17) && !gpu_draw_calls &&
           !gpu_final_calls);
    goto finish;
  }
  if (mode == "unobserved_submit") {
    h.receipt.submitted = false;
    assert(!mp4_volume_assembly_draw_fenced(17, 1) &&
           !mp4_volume_assembly_final_fenced(17) && !gpu_draw_calls &&
           !gpu_final_calls);
    goto finish;
  }
  if (mode == "inflight") {
    h.receipt.ended = false;
    assert(!mp4_volume_assembly_draw_fenced(17, 1) &&
           !mp4_volume_assembly_final_fenced(17) && !gpu_draw_calls &&
           !gpu_final_calls);
    goto finish;
  }
  if (mode == "orphaned") {
    h.orphaned = true;
    assert(!mp4_volume_assembly_draw_fenced(17, 1) &&
           !mp4_volume_assembly_withdrawn(17, frame) && !gpu_draw_calls &&
           !gpu_final_calls);
    goto finish;
  }
  if (mode == "gpu_wait") {
    assert(!mp4_volume_assembly_draw_fenced(17, 1) && gpu_draw_calls == 1);
    gpu_ready = true;
    assert(mp4_volume_assembly_draw_fenced(17, 1) && gpu_draw_calls == 2);
    goto finish;
  }
  if (mode == "cached_actual_fence") {
    gpu_ready = true;
    assert(mp4_volume_assembly_draw_fenced(17, 1));
    gpu_ready = false;
    assert(mp4_volume_assembly_draw_fenced(17, 1) && gpu_draw_calls == 1);
    goto finish;
  }
  if (mode == "next_unpublished") {
    h.receipt.fenced = true;
    mp4_volume_factory_host.sequence = 2;
    assert(mp4_volume_assembly_draw_fenced(17, 2) && !gpu_draw_calls);
    goto finish;
  }
  if (mode == "withdraw_requires_no_alias") {
    gpu_ready = true;
    put(h.additional, 120, frame.stack);
    assert(!mp4_volume_assembly_withdrawn(17, frame));
    goto finish;
  }
  if (mode == "final_job_epoch") {
    gpu_ready = true;
    assert(mp4_volume_assembly_final_fenced(17) && gpu_final_calls == 1);
    goto finish;
  }
  assert(false);
finish:
  for (void *p : allocations)
    ::free(p);
  std::puts("ok");
}
