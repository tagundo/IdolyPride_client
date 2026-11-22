#include "mp4_actor_state.hpp"
#include <cassert>
#include <cstdio>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
// SHIPPING_VOLUME_MONO_SCOPE
namespace vm = idoly_mp4_volume_mono;
struct Object {
  std::string type;
  size_t size;
  bool alive = true;
};
std::map<void *, Object> objects;
std::vector<void *> allocated;
void *obj(const char *t) {
  void *p = ::calloc(1, 512);
  allocated.push_back(p);
  objects[p] = {t, 512, true};
  return p;
}
bool mapped(const void *p, size_t n, bool) {
  uintptr_t a = reinterpret_cast<uintptr_t>(p);
  for (auto &o : objects) {
    uintptr_t b = reinterpret_cast<uintptr_t>(o.first);
    if (a >= b && a - b < o.second.size && n <= o.second.size - (a - b))
      return true;
  }
  return false;
}
template <class T> void put(void *p, size_t off, T x) {
  assert(mapped(static_cast<uint8_t *>(p) + off, sizeof x, true));
  ::memcpy(static_cast<uint8_t *>(p) + off, &x, sizeof x);
}
template <class T> T get(void *p, size_t off) {
  T x{};
  assert(mapped(static_cast<uint8_t *>(p) + off, sizeof x, false));
  ::memcpy(&x, static_cast<uint8_t *>(p) + off, sizeof x);
  return x;
}
bool exact(void *p, const char *t) {
  return objects.count(p) && objects[p].type == t;
}
bool alive(void *p) { return objects.count(p) && objects[p].alive; }
std::map<uint32_t, void *> roots;
uint32_t serial = 1;
uint32_t retain(void *p) {
  uint32_t n = serial++;
  roots[n] = p;
  return n;
}
void *target(uint32_t n) { return roots.count(n) ? roots[n] : nullptr; }
void release(uint32_t n) { roots.erase(n); }
bool live = true, fenced = true, readonly_mesh = true, closed_profile = true,
     throw_clone = false, throw_late = false, frame_fenced = true,
     enabled = true, changed = true, lifecycle_allowed = true,
     detach_allowed = true, zero_inventory = false, invoke_nested = false,
     invoke_reentrant = false, lose_capture_fence = false;
vm::Scope *active_scope = nullptr;
int32_t hide_flags = 12;
uint64_t native_tick = 0;
bool consumed(void *, uint64_t epoch, uint64_t tick) {
  return epoch == 17 && tick == native_tick;
}
bool grant(vm::Scope &scope, uint64_t epoch, uint64_t serial) {
  if (!scope.prepare_grant(epoch, serial))
    return false;
  native_tick = serial - 1;
  return scope.grant(epoch, serial);
}
unsigned invokes = 0, destroys = 0, clear_calls = 0;
std::map<void *, std::vector<int>> blocks, renderer_blocks;
std::map<void *, void *> profile_component,profile_component2;
std::map<void *, int> profile_value;
std::map<void *, vm::Kind> volume_kind;
vm::Owner owner;
bool thread() { return true; }
bool held(void *, uint64_t e) { return fenced && e == 17; }
bool routes(void *) { return true; }
bool current(void *, const vm::Owner &o) {
  return live && o.component == owner.component &&
         o.environment == owner.environment && o.asset == 0x123 &&
         o.epoch == 17 && o.receipt == 99;
}
bool inventory(void *, const vm::Owner *o, size_t n) {
  if (zero_inventory)
    return n == 0;
  return n == 1 && current(nullptr, o[0]);
}
void reference(void *p, uint32_t off, void *x) { put(p, off, x); }
void *block_new() {
  void *p = obj("UnityEngine.MaterialPropertyBlock");
  blocks[p] = {};
  return p;
}
bool block_valid(void *p) { return alive(p) && blocks.count(p); }
bool block_empty(void *p, void *) { return blocks[p].empty(); }
void block_get(void *r, void *b, int32_t, void *) {
  blocks[b] = renderer_blocks[r];
  if (lose_capture_fence)
    fenced = false;
}
void block_set(void *r, void *b, int32_t, void *) {
  renderer_blocks[r] = b ? blocks[b] : std::vector<int>{};
}
void block_dispose(void *b, void *) { objects[b].alive = false; }
void *new_profile(vm::Kind k, int value) {
  void *p = obj("UnityEngine.Rendering.VolumeProfile");
  void *c = obj(k == vm::Kind::mirror
                    ? "VL.Rendering.PostProcess.VLMirrorVolumeComponent"
                    : k==vm::Kind::light ? "VL.Rendering.PostProcess.VLActorParameter":"Solis.Rendering.VolumetricHeightFog");
  profile_component[p] = c;
  if(k==vm::Kind::light)profile_component2[p]=obj("VL.Rendering.PostProcess.VLLightmapVolume");
  profile_value[p] = value;
  return p;
}
void *profile_get(void *v, void *) {
  void *p = get<void *>(v, 64);
  if (alive(p))
    return p;
  void *s = get<void *>(v, 48);
  p = new_profile(volume_kind[v], profile_value[s]);
  if(!profile_component[s])profile_component[p]=nullptr;
  if(!profile_component2[s])profile_component2[p]=nullptr;
  put(v, 64, p);
  if (throw_clone)
    throw std::runtime_error("original profile clone fixture");
  return p;
}
bool profile_closed(void *, void *p, const vm::Owner &) {
  return closed_profile && profile_component.count(p);
}
bool contains(void *, void *p, void *c, vm::Kind) {
  return c && (profile_component[p] == c||profile_component2[p]==c);
}
bool profile_cache(void*,void*p,vm::Kind k,size_t at,void**out){if(!out||at>=(k==vm::Kind::light?2u:1u))return false;*out=at?profile_component2[p]:profile_component[p];return true;}
bool mesh(void *, const vm::Owner &, void *m) {
  return readonly_mesh && m == owner.mask_mesh;
}
bool active(void *) { return enabled; }
bool lifecycle_authorized(void *, const vm::Owner &, vm::Phase) {
  return lifecycle_allowed;
}
bool get_hide_flags(void *, int32_t *out) {
  *out = hide_flags;
  return true;
}
bool set_hide_flags(void *, int32_t value) {
  hide_flags = value;
  return true;
}
bool get_changed(void *, bool *x) {
  *x = changed;
  return true;
}
bool set_changed(void *, bool x) {
  changed = x;
  return true;
}
bool get_enabled(void *, bool *x) {
  *x = enabled;
  return true;
}
bool set_enabled(void *, bool x) {
  enabled = x;
  return true;
}
void invoke(void *, vm::Kind k, vm::Phase phase, void *self) {
  ++invokes;
  if (invoke_nested)
    assert(active_scope->route(k, vm::Phase::parameters, self));
  if (invoke_reentrant) {
    assert(!active_scope->route(k, vm::Phase::enable, self));
    return;
  }
  if (k == vm::Kind::height_fog && phase == vm::Phase::enable) {
    hide_flags = 8;
    put(self, 96, block_new());
    return;
  }
  void *v = owner.volume;
  if (phase == vm::Phase::disable) {
    renderer_blocks[owner.renderer].clear();
    ++clear_calls;
    void *p = profile_get(v, nullptr);
    objects[profile_component[p]].alive = false;
    objects[p].alive = false;
    ++destroys;
    return;
  }
  if (phase == vm::Phase::late) {
    if (throw_late)
      throw std::runtime_error("original Late fixture");
    void *p = profile_get(v, nullptr);
    // Model the actual original Add<T> duplicate guard, not a permissive
    // fixture replacement of an already existing component.
    const uint32_t cache=vm::cache_offset(k);
    if(!alive(get<void*>(self,cache))){
      assert(!profile_component[p]);
      profile_component[p]=obj(k==vm::Kind::light?"VL.Rendering.PostProcess.VLActorParameter":k==vm::Kind::mirror?"VL.Rendering.PostProcess.VLMirrorVolumeComponent":"Solis.Rendering.VolumetricHeightFog");
      put(self,cache,profile_component[p]);
    }else assert(get<void*>(self,cache)==profile_component[p]);
    if(k==vm::Kind::light){
      if(!alive(get<void*>(self,128))){assert(!profile_component2[p]);profile_component2[p]=obj("VL.Rendering.PostProcess.VLLightmapVolume");put(self,128,profile_component2[p]);}
      else assert(get<void*>(self,128)==profile_component2[p]);
    }
    profile_value[p] = 42;
    if (k == vm::Kind::height_fog) {
      void *b = get<void *>(self, 96);
      blocks[b] = {1, 2, 3};
      renderer_blocks[owner.renderer] = blocks[b];
      enabled = false;
    } else if(k==vm::Kind::mirror) {
      changed = false;
      float v = 12;
      put(self, 96, v);
    }
  }
}
bool lifecycle(void *, const vm::Owner &o, const vm::SourceRefs &s) {
  if (!detach_allowed)
    return false;
  reference(o.volume, 48, s.shared);
  reference(o.volume, 64, s.internal);
  reference(o.component, vm::cache_offset(o.kind), s.cached);
  if(o.kind==vm::Kind::light)reference(o.component,128,s.cached2);
  if (o.kind == vm::Kind::height_fog) {
    reference(o.component, 96, s.block);
    reference(o.component, 80, s.renderer);
    reference(o.component, 88, s.volume);
  }
  live = false;
  return true;
}
bool gpu(void *, uint64_t) { return frame_fenced; }
bool destroy(void *, void *p) {
  assert(p != get<void *>(owner.volume, 64));
  objects[p].alive = false;
  ++destroys;
  return true;
}
vm::Api api() {
  vm::Api a{};
  a.thread = thread;
  a.held_fenced = held;
  a.consumed_tick = consumed;
  a.routes_verified = routes;
  a.owner_current = current;
  a.inventory_exact = inventory;
  a.mapped = mapped;
  a.exact_type = exact;
  a.alive = alive;
  a.retain = retain;
  a.target = target;
  a.release = release;
  a.reference_set = reference;
  a.profile_get = profile_get;
  a.profile_clone_closed = profile_closed;
  a.profile_contains = contains;
  a.profile_cache = profile_cache;
  a.mesh_readonly = mesh;
  a.active_enabled = active;
  a.lifecycle_authorized = lifecycle_authorized;
  a.transform_changed = get_changed;
  a.set_transform_changed = set_changed;
  a.renderer_enabled = get_enabled;
  a.set_renderer_enabled = set_enabled;
  a.hide_flags = get_hide_flags;
  a.set_hide_flags = set_hide_flags;
  a.images.block_new = block_new;
  a.images.block_valid = block_valid;
  a.images.block_empty = block_empty;
  a.images.block_get = block_get;
  a.images.block_set = block_set;
  a.images.block_dispose = block_dispose;
  a.invoke = invoke;
  a.before_lifecycle = lifecycle;
  a.private_unpublished_or_fenced = gpu;
  a.destroy_profile = destroy;
  return a;
}
int main(int argc, char **argv) {
  assert(argc == 2);
  std::string mode = argv[1];
  vm::Scope scope;
  active_scope = &scope;
  if (mode == "zero_inventory" || mode == "unconfigured_inventory") {
    size_t count = 100;
    assert(!scope.enumerate_volumes(nullptr, 0, &count));
    if (mode == "zero_inventory") {
      zero_inventory = true;
      assert(scope.capture(api(), 17, nullptr, 0) == vm::Result::ok);
      assert(scope.enumerate_volumes(nullptr, 0, &count) && count == 0);
      assert(scope.prepare() == vm::Result::ok);
      assert(grant(scope, 17, 1) && scope.complete_grant(17, 1));
      assert(scope.restore() == vm::Result::ok);
      assert(scope.release() == vm::Result::ok);
    }
    std::puts("ok");
    return 0;
  }
  auto k = mode.find("light") == 0 ? vm::Kind::light : mode.find("mirror") == 0 ? vm::Kind::mirror : vm::Kind::height_fog;
  owner.kind = k;
  owner.component =
      obj(vm::component_name(k));
  owner.environment = obj("SolisLiveEnvironment");
  owner.volume = k != vm::Kind::height_fog ? owner.component
                                       : obj("UnityEngine.Rendering.Volume");
  owner.game_object = obj("UnityEngine.GameObject");
  owner.transform = obj("UnityEngine.Transform");
  owner.renderer = obj("UnityEngine.MeshRenderer");
  owner.mask_mesh = obj("UnityEngine.Mesh");
  if (mode == "mirror_null")
    owner.mask_mesh = nullptr;
  if (k == vm::Kind::mirror)
    put(owner.component, 88, owner.mask_mesh);
  owner.asset = 0x123;
  owner.epoch = 17;
  owner.receipt = 99;
  volume_kind[owner.volume] = k;
  void *source = new_profile(k, 33), *shared = new_profile(k, 7);
  profile_component[shared]=nullptr;profile_component2[shared]=nullptr;
  put(owner.volume, 48, shared);
  put(owner.volume, 64, source);
  put(owner.component, vm::cache_offset(k),
      profile_component[source]);
  if(k==vm::Kind::light)put(owner.component,128,profile_component2[source]);
  void *sourceblock = block_new();
  blocks[sourceblock] = {9};
  if (k == vm::Kind::height_fog) {
    put(owner.component, 80, owner.renderer);
    put(owner.component, 88, owner.volume);
    put(owner.component, 96, sourceblock);
    renderer_blocks[owner.renderer] = {10, 11};
  }
  const bool dormant = mode == "fog_dormant" || mode == "mirror_dormant" || mode=="light_dormant";
  if (dormant) {
    profile_component[shared]=nullptr;profile_component2[shared]=nullptr;
    put<void *>(owner.volume, 64, nullptr);
    put<void *>(owner.component, vm::cache_offset(k), nullptr);
    if(k==vm::Kind::light)put<void*>(owner.component,128,nullptr);
    if (k == vm::Kind::height_fog) {
      put<void *>(owner.component, 80, nullptr);
      put<void *>(owner.component, 88, nullptr);
      put<void *>(owner.component, 96, nullptr);
    }
  }
  if(mode=="light_nonfinite")put(owner.component,72,std::nanf(""));
  if(mode=="light_second_foreign")put(owner.component,128,obj("VL.Rendering.PostProcess.VLLightmapVolume"));
  if (mode == "mirror_unproved_mesh")
    readonly_mesh = false;
  if (mode == "unclosed_profile")
    closed_profile = false;
  if (mode == "capture_fence_lost")
    lose_capture_fence = true;
  auto result = scope.capture(api(), 17, &owner, 1);
  if (mode == "mirror_unproved_mesh" || mode == "unclosed_profile" ||mode=="light_nonfinite"||mode=="light_second_foreign") {
    assert(result == vm::Result::unsupported);
    assert(scope.discard_unpublished_capture() == vm::Result::ok);
    assert(roots.empty());
    goto done;
  }
  if (mode == "capture_fence_lost") {
    assert(result == vm::Result::stale);
    frame_fenced = false;
    assert(scope.discard_unpublished_capture() == vm::Result::waiting);
    frame_fenced = true;
    assert(scope.discard_unpublished_capture() == vm::Result::ok);
    assert(roots.empty());
    goto done;
  }
  assert(result == vm::Result::ok);
  {
    vm::Owner found{};
    assert(scope.owned_volume(owner.volume, found));
    if (k == vm::Kind::mirror && owner.mask_mesh)
      assert(scope.mesh_protected(owner.mask_mesh, 17, 0x123));
    void *volumes[64]{};
    size_t n = 0;
    assert(scope.enumerate_volumes(volumes, 64, &n) && n == 1 &&
           volumes[0] == owner.volume);
  }
  if (mode == "clone_throw")
    throw_clone = true;
  try {
    result = scope.prepare();
  } catch (const std::exception &) {
    assert(mode == "clone_throw");
    assert(get<void *>(owner.volume, 48) == shared);
    throw_clone = false;
    assert(scope.restore() == vm::Result::ok);
    assert(scope.source_restored(owner.volume));
    assert(scope.release() == vm::Result::ok);
    goto done;
  }
  assert(result == vm::Result::ok);
  assert(get<void *>(owner.volume, 48) == shared &&
         get<void *>(owner.volume, 64) != source);
  if (mode == "abandon_forward") {
    scope.abandon();
    assert(scope.route(k, vm::Phase::late, owner.component));
    assert(scope.release() == vm::Result::waiting);
    goto done;
  }
  if (mode == "raw_handoff_cleanup" || mode == "raw_handoff_cleanup_alias") {
    void *private_profile = get<void *>(owner.volume, 64);
    assert(scope.raw_source_handoff());
    live = false;
    void *replacement = new_profile(k, 88);
    put(owner.volume, 64, replacement);
    put(owner.component, 104, profile_component[replacement]);
    void *new_block = block_new();
    put(owner.component, 96, new_block);
    renderer_blocks[owner.renderer] = {55};
    frame_fenced = false;
    assert(scope.release(false) == vm::Result::waiting);
    frame_fenced = true;
    if (mode == "raw_handoff_cleanup_alias") {
      put(owner.volume, 64, private_profile);
      assert(scope.release(false) == vm::Result::waiting);
      put(owner.volume, 64, replacement);
    }
    assert(scope.release(false) == vm::Result::ok);
    assert(get<void *>(owner.volume, 64) == replacement &&
           get<void *>(owner.component, 96) == new_block &&
           renderer_blocks[owner.renderer] == std::vector<int>{55});
    goto done;
  }
  if (mode == "raw_handoff" || mode == "raw_handoff_superseded") {
    live = false;
    if (mode == "raw_handoff_superseded") {
      put(owner.volume, 64, obj("Foreign"));
      assert(!scope.raw_source_handoff());
    } else {
      assert(scope.raw_source_handoff());
      assert(get<void *>(owner.volume, 64) == source);
      assert(get<void *>(owner.component, 104) == profile_component[source]);
      assert(get<void *>(owner.component, 96) == sourceblock);
      assert(scope.route(k, vm::Phase::disable, owner.component));
    }
    assert(!scope.source_restored(owner.volume));
    assert(scope.release() == vm::Result::waiting);
    goto done;
  }
  if (mode == "unauthorized_lifecycle" || mode == "failed_lifecycle_detach") {
    lifecycle_allowed = false;
    detach_allowed = mode != "failed_lifecycle_detach";
    assert(scope.route(k, vm::Phase::disable, owner.component) ==
           detach_allowed);
    assert(!invokes && scope.closed(17));
    assert(scope.release() == vm::Result::waiting);
    goto done;
  }
  if (mode == "owner_changed" || mode == "mirror_mask_retarget") {
    if (mode == "owner_changed")
      live = false;
    else
      put(owner.component, 88, obj("UnityEngine.Mesh"));
    void *out[64]{};
    size_t count = 0;
    assert(!scope.enumerate_volumes(out, 64, &count));
    assert(!scope.route(k, vm::Phase::late, owner.component));
    assert(!invokes && scope.restore() == vm::Result::stale);
    goto done;
  }
  if (mode == "foreign_profile" || mode == "foreign_cache" ||
      mode == "foreign_block") {
    void *object = mode == "foreign_profile" ? owner.volume : owner.component;
    const size_t offset = mode == "foreign_profile" ? 64
                          : mode == "foreign_cache" ? 104
                                                    : 96;
    void *old = get<void *>(object, offset);
    put(object, offset, obj("Foreign"));
    assert(grant(scope, 17, 1));
    assert(!scope.route(k, vm::Phase::late, owner.component) && !invokes);
    assert(scope.restore() == vm::Result::stale);
    put(object, offset, old);
    assert(scope.restore() == vm::Result::ok);
    assert(scope.release() == vm::Result::ok);
    goto done;
  }
  if (mode == "unowned_forward") {
    assert(scope.route(k, vm::Phase::late, obj("Foreign")));
  }
  if (mode == "held_late") {
    assert(!scope.route(k, vm::Phase::late, owner.component));
    assert(!invokes);
  }
  if (mode == "pending_revoke" || mode == "stale_consumed_tick") {
    assert(scope.prepare_grant(17, 1) && !scope.closed(17));
    if (mode == "stale_consumed_tick") {
      native_tick = 9;
      assert(!scope.grant(17, 1));
    }
    scope.revoke_grants(18);
    assert(!scope.closed(17));
    scope.revoke_grants(17);
    assert(scope.closed(17));
  }
  if (mode == "grant_requires_prepare")
    assert(!scope.grant(17, 1));
  if (mode == "consumed_nonheld") {
    assert(scope.prepare_grant(17, 1));
    fenced = false;
    native_tick = 0;
    assert(scope.grant(17, 1));
  } else
    assert(grant(scope, 17, 1));
  invoke_nested = mode == "mirror_nested_parameters";
  invoke_reentrant = mode == "reentrant";
  if (mode == "late_throw")
    throw_late = true;
  try {
    assert(!scope.route(k, vm::Phase::late, owner.component));
  } catch (const std::exception &) {
    assert(mode == "late_throw");
    throw_late = false;
    assert(scope.closed(17));
    assert(scope.restore() == vm::Result::ok);
    assert(scope.release() == vm::Result::ok);
    goto done;
  }
  if (mode == "reentrant") {
    assert(scope.closed(17) && !scope.complete_grant(17, 1));
    assert(scope.restore() == vm::Result::ok);
    assert(scope.release() == vm::Result::ok);
    goto done;
  }
  assert(!scope.route(k, vm::Phase::late, owner.component));
  assert(invokes == 1);
  assert(scope.complete_grant(17, 1));
  assert(profile_value[source] == 33 && alive(source) &&
         alive(profile_component[source]));
  if (mode == "fog_lifecycle") {
    assert(!scope.route(k, vm::Phase::disable, owner.component));
    assert(clear_calls == 1 && renderer_blocks[owner.renderer].empty());
    assert(alive(source) && alive(profile_component[source]));
    assert(!scope.route(k, vm::Phase::enable, owner.component));
    assert(grant(scope, 17, 2));
    assert(!scope.route(k, vm::Phase::late, owner.component));
    assert(scope.complete_grant(17, 2));
    assert(get<void *>(owner.volume, 64) != source);
  }
  if (mode == "revoke") {
    assert(grant(scope, 17, 2));
    scope.revoke_grants(17);
    assert(scope.closed(17));
    assert(!scope.route(k, vm::Phase::late, owner.component));
  }
  fenced = true;
  assert(scope.restore() == vm::Result::ok);
  assert(get<void *>(owner.volume, 64) == (dormant ? nullptr : source) &&
         get<void *>(owner.component, vm::cache_offset(k)) ==
             (dormant ? nullptr : profile_component[source]));
  assert(scope.source_restored(owner.volume));
  if(k==vm::Kind::light)assert(get<void*>(owner.component,128)==(dormant?nullptr:profile_component2[source]));
  assert(hide_flags == 12);
  assert(!grant(scope, 17, 4));
  if (mode == "postrestore_forward")
    assert(!scope.route(k, vm::Phase::late, owner.component));
  if (k == vm::Kind::height_fog) {
    assert(get<void *>(owner.component, 96) ==
               (dormant ? nullptr : sourceblock) &&
           blocks[sourceblock] == std::vector<int>{9} &&
           renderer_blocks[owner.renderer] == std::vector<int>({10, 11}));
    assert(get<void *>(owner.component, 80) ==
           (dormant ? nullptr : owner.renderer));
    assert(get<void *>(owner.component, 88) ==
           (dormant ? nullptr : owner.volume));
    assert(enabled);
  } else
    assert(changed);
  if (mode == "gpu_wait") {
    frame_fenced = false;
    assert(scope.release() == vm::Result::waiting);
    frame_fenced = true;
  }
  assert(scope.release() == vm::Result::ok);
  assert(scope.route(k, vm::Phase::late, owner.component));
done:
  for (void *p : allocated)
    ::free(p);
  std::puts("ok");
}
