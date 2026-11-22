#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include "activation-target-scope.hpp.inc"
using namespace idoly_mp4_activation_targets;
int objects[20]{};
void *target = &objects[0];
Component components[3]{};
State states[3]{{1, 0}, {0, 1}, {1, 1}};
bool owner = true, held = true, component_ok = true, execution = true,
     inventory_ok = true, duplicate = false, extra = false, write_ok = true;
uint32_t seq = 0;
std::map<uint32_t, void *> roots;
size_t active_writes = 0, dirty_writes = 0;
Scope scope;
bool test_callbacks = false;
std::string scenario;
bool current(void *, uint64_t e) { return owner && e == 11; }
bool clock(void *) { return held; }
bool comp_current(void *, const Component &c) {
  return component_ok && c.object && c.owner;
}
bool inventory(void *, void *p, Emit emit, void *ctx) {
  assert(p == target);
  if (!inventory_ok)
    return false;
  for (size_t i = 0; i < (extra ? 3u : 2u); ++i) {
    auto c = components[duplicate && i ? 0 : i];
    if (!emit(ctx, c))
      return false;
  }
  return true;
}
size_t index(void *go) {
  for (size_t i = 0; i < 3; ++i)
    if (components[i].game_object == go)
      return i;
  assert(false);
  return 0;
}
bool read(void *, void *go, void *t, State *out) {
  auto i = index(go);
  assert(components[i].transform == t);
  *out = states[i];
  return true;
}
bool active(void *, void *go, bool b) {
  ++active_writes;
  if (!write_ok)
    return false;
  auto i = index(go);
  if (test_callbacks) {
    assert(scope.lifecycle_current(components[i].object));
    if (i == 0)
      assert(scope.lifecycle_current(components[1].object));
    assert(!scope.lifecycle_current(components[2].object));
  }
  states[i].active = b;
  states[i].dirty = 1;
  return true;
}
bool dirty(void *, void *t, bool b) {
  ++dirty_writes;
  for (size_t i = 0; i < 3; ++i)
    if (components[i].transform == t) {
      states[i].dirty = b;
      return true;
    }
  assert(false);
  return false;
}
bool original(void *, void *) { return execution; }
uint32_t keep(void *p) {
  assert(p != &objects[6]); // Il2CppClass is native metadata, not a GC object.
  roots[++seq] = p;
  return seq;
}
void *get(uint32_t h) {
  auto i = roots.find(h);
  return i == roots.end() ? nullptr : i->second;
}
void drop(uint32_t h) { assert(roots.erase(h) == 1); }
Api api() {
  return {current, clock,    inventory, comp_current, read, active,
          dirty,   original, keep,      get,          drop};
}
int main(int argc, char **argv) {
  assert(argc == 2);
  scenario = argv[1];
  for (size_t i = 0; i < 3; ++i) {
    auto &c = components[i];
    c.object = &objects[i + 3];
    c.klass = &objects[6];
    c.game_object = &objects[i];
    c.transform = &objects[7 + i];
    c.parent = i == 1 ? components[0].transform : nullptr;
    c.native = 100 + i;
    c.owner = 1000 + i;
    c.family = 1;
  }
  if (scenario == "capture_owner")
    owner = false;
  if (scenario == "capture_clock")
    held = false;
  if (scenario == "capture_inventory")
    inventory_ok = false;
  if (scenario == "capture_component")
    component_ok = false;
  if (scenario == "capture_duplicate")
    duplicate = true;
  if (scenario == "capture_state")
    states[0].active = 2;
  auto r = scope.capture(api(), nullptr, 11, &target, 1);
  if (scenario.rfind("capture_", 0) == 0) {
    assert(r != Result::ok);
    scope.release(false);
    assert(roots.empty());
    return 0;
  }
  assert(r == Result::ok && scope.current() && scope.owns(target) &&
         scope.target_current(target));
  assert(scope.lifecycle_current(components[0].object));
  execution = false;
  assert(!scope.lifecycle_current(components[0].object));
  execution = true;
  if (scenario == "changed_inventory")
    extra = true;
  if (scenario == "changed_parent")
    components[1].parent = nullptr;
  if (scenario == "changed_native")
    ++components[0].native;
  if (scenario == "changed_callback")
    components[0].callbacks[2] = 5;
  if (scenario == "changed_owner")
    ++components[0].owner;
  if (scenario.rfind("changed_", 0) == 0) {
    assert(!scope.current());
    assert(scope.restore() != Result::ok && !active_writes && !dirty_writes);
    scope.release(false);
    assert(roots.empty());
    return 0;
  }
  states[0] = {0, 1};
  states[1] = {1, 0};
  if (scenario == "restore_clock")
    held = false;
  if (scenario == "restore_owner")
    owner = false;
  if (scenario == "restore_component")
    component_ok = false;
  if (scenario == "restore_writer")
    write_ok = false;
  test_callbacks = scenario == "restore_callbacks";
  r = scope.restore();
  if (scenario.rfind("restore_", 0) == 0 && scenario != "restore_callbacks") {
    assert(r != Result::ok);
    scope.release(false);
    assert(roots.empty());
    return 0;
  }
  assert(r == Result::ok && states[0].active == 1 && states[0].dirty == 0 &&
         states[1].active == 0 && states[1].dirty == 1 && active_writes == 2 &&
         dirty_writes == 2);
  if (scenario == "restored_changed") {
    states[0].active = 0;
    assert(scope.restore() != Result::ok);
  } else
    assert(scope.restore() == Result::ok && active_writes == 2);
  scope.release(false);
  assert(roots.empty());
}
