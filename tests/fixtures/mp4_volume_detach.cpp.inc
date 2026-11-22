#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <string>
struct Mp4SceneWitness {
  void *player = nullptr;
  uint64_t generation = 0;
};
enum class Mp4SceneResult { ok, waiting, stale, failed };
struct FakeRootScope {
  bool globals = true, raw_ok = true;
  unsigned raw_calls = 0, abandon_calls = 0;
  bool globals_withdrawn() const noexcept { return globals; }
  bool before_source_change() {
    ++raw_calls;
    if (raw_ok)
      globals = true;
    return raw_ok;
  }
  void abandon_globals() noexcept { ++abandon_calls; }
};
namespace mp4pv {
using Scope = FakeRootScope;
}
struct FakeMonoScope {
  bool raw_ok = true, unpublished_ok = true;
  unsigned raw_calls = 0, abandon_calls = 0, unpublished_calls = 0;
  bool raw_source_handoff() {
    ++raw_calls;
    return raw_ok;
  }
  bool detach_unpublished() noexcept {
    ++unpublished_calls;
    return unpublished_ok;
  }
  void abandon() noexcept { ++abandon_calls; }
} mp4_volume_mono_scope;
struct FakeMonoHost {
  bool captured = false;
} mp4_volume_mono_host;
bool game_call() { return true; }
bool mp4_scene_same_source(const Mp4SceneWitness &a, const Mp4SceneWitness &b) {
  return a.generation && a.generation == b.generation && a.player == b.player;
}
namespace idoly_mp4_runtime {
struct Game {
  Mp4SceneWitness current{};
  bool available = true;
  bool selected_scene_witness(Mp4SceneWitness &o) {
    o = current;
    return available;
  }
} game;
} // namespace idoly_mp4_runtime
unsigned holds = 0, pubs = 0, renderer_calls = 0, cine_calls = 0,
         renderer_abandons = 0, cine_abandons = 0;
bool renderer_ok = true, cine_ok = true, renderer_throw = false,
     publication = true;
void mp4_volume_assembly_hold() noexcept { ++holds; }
void mp4_source_volume_publish_interception(bool value) noexcept {
  ++pubs;
  publication = value;
}
bool mp4_renderer_before_source_change() {
  ++renderer_calls;
  if (renderer_throw)
    throw std::runtime_error("raw receiver fixture");
  return renderer_ok;
}
bool mp4_cine_before_source_change() {
  ++cine_calls;
  return cine_ok;
}
void mp4_renderer_abandon_globals() noexcept { ++renderer_abandons; }
void mp4_cine_abandon_globals() noexcept { ++cine_abandons; }

// SHIPPING_VOLUME_ASSEMBLY_DETACH
int main(int argc, char **argv) {
  assert(argc == 2);
  std::string mode = argv[1];
  auto &h = mp4_volume_assembly;
  h.source = {reinterpret_cast<void *>(0x123), 17};
  idoly_mp4_runtime::game.current = h.source;
  if (mode == "empty") {
    assert(mp4_volume_assembly_detach(false) == Mp4SceneResult::ok &&
           h.withdrawn && h.detached && !h.orphaned);
    assert(!renderer_calls && !cine_calls && !mp4_volume_mono_scope.raw_calls);
  } else if (mode == "capture_only") {
    h.configured = true;
    mp4_volume_mono_host.captured = true;
    assert(mp4_volume_assembly_detach(false) == Mp4SceneResult::ok);
    assert(mp4_volume_mono_scope.unpublished_calls == 1 &&
           !mp4_volume_mono_scope.raw_calls && !h.orphaned);
  } else if (mode == "unpublished_refused") {
    mp4_volume_mono_host.captured = true;
    mp4_volume_mono_scope.unpublished_ok = false;
    assert(mp4_volume_assembly_detach(false) == Mp4SceneResult::stale &&
           h.orphaned && h.detached);
  } else if (mode == "checkpoint") {
    h.source_verified = true;
    mp4_volume_mono_host.captured = true;
    assert(mp4_volume_assembly_detach(true) == Mp4SceneResult::ok &&
           h.withdrawn && h.detached && !h.orphaned);
    assert(!renderer_calls && !cine_calls && !mp4_volume_mono_scope.raw_calls);
  } else if (mode == "bad_checkpoint") {
    mp4_volume_mono_host.captured = true;
    assert(mp4_volume_assembly_detach(true) == Mp4SceneResult::stale &&
           h.orphaned && h.detached && mp4_volume_mono_scope.abandon_calls);
  } else if (mode == "checkpoint_globals_pending") {
    h.source_verified = true;
    h.scope.globals = false;
    assert(mp4_volume_assembly_detach(true) == Mp4SceneResult::stale &&
           h.orphaned && h.scope.abandon_calls);
  } else if (mode == "first_current_raw") {
    h.prepare_started = h.scope_duty = h.renderer_duty = h.cine_duty = true;
    mp4_volume_mono_host.captured = true;
    assert(mp4_volume_assembly_detach(false) == Mp4SceneResult::ok);
    assert(h.scope.raw_calls == 1 && renderer_calls == 1 && cine_calls == 1 &&
           mp4_volume_mono_scope.raw_calls == 1);
  } else if (mode == "same_pointer_new_init") {
    h.prepare_started = h.scope_duty = h.renderer_duty = h.cine_duty = true;
    mp4_volume_mono_host.captured = true;
    assert(mp4_volume_assembly_before_source_change());
    idoly_mp4_runtime::game.current.generation = 18;
    assert(mp4_volume_assembly_detach(false) == Mp4SceneResult::ok);
    assert(mp4_volume_assembly_before_source_change());
    assert(h.scope.raw_calls == 1 && renderer_calls == 1 && cine_calls == 1 &&
           mp4_volume_mono_scope.raw_calls == 1);
  } else if (mode == "lost_source_without_receipt") {
    h.prepare_started = h.scope_duty = h.renderer_duty = h.cine_duty = true;
    mp4_volume_mono_host.captured = true;
    idoly_mp4_runtime::game.current.generation = 18;
    assert(mp4_volume_assembly_detach(false) == Mp4SceneResult::stale &&
           h.orphaned && h.detached);
    assert(!h.scope.raw_calls && !renderer_calls && !cine_calls &&
           !mp4_volume_mono_scope.raw_calls);
  } else if (mode == "partial_raw_throw") {
    h.prepare_started = h.scope_duty = h.renderer_duty = h.cine_duty = true;
    mp4_volume_mono_host.captured = true;
    renderer_throw = true;
    assert(!mp4_volume_assembly_before_source_change());
    assert(h.scope.raw_calls == 1 && renderer_calls == 1 && cine_calls == 1 &&
           mp4_volume_mono_scope.raw_calls == 1);
    assert(mp4_volume_assembly_detach(false) == Mp4SceneResult::stale &&
           h.orphaned);
    assert(renderer_calls == 1 && cine_calls == 1);
  } else if (mode == "already_detached") {
    h.detached = h.withdrawn = true;
    assert(mp4_volume_assembly_detach(false) == Mp4SceneResult::ok &&
           !renderer_calls && !cine_calls);
  } else if (mode == "uncertain_globals") {
    h.scope.globals = false;
    idoly_mp4_runtime::game.available = false;
    assert(mp4_volume_assembly_detach(false) == Mp4SceneResult::stale &&
           h.orphaned);
  } else
    assert(false);
  assert(!publication && holds);
  std::puts("ok");
}
