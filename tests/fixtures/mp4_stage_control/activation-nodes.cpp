#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <map>
#include <string>
#include "activation-node-scope.hpp.inc"
using namespace idoly_mp4_activation_nodes;
int objects[40]{};
bool owner = true, held = true, pending = true, source_live = true,
     private_live = true, restore_live = true, fresh_ok = true, wait = false,
     missing = false, duplicate = false, bad_key = false, write_ok = true,
     partial = false;
size_t writes = 0, old_queries = 0;
uint32_t sequence = 0;
std::map<uint32_t, void *> roots;
std::map<void *, State> states;
Node sources[2]{}, exports[2]{}, restores[2]{};
bool current(void *, uint64_t e) { return owner && e == 11; }
bool clock(void *) { return held; }
bool owned(void *, const Key &) { return owner; }
bool pending_current(void *, Round) { return pending; }
bool node_current(void *, const Node &n) {
  if (n.graph.handle == 1) {
    ++old_queries;
    return source_live;
  }
  return n.graph.handle == 2 ? private_live : restore_live;
}
bool read(void *, const Node &n, State *out) {
  *out = states[n.script];
  return true;
}
bool write(void *, const Node &n, const State &s) {
  ++writes;
  if (!write_ok)
    return false;
  if (partial) {
    states[n.script].initial = s.initial;
    partial = false;
    return false;
  }
  states[n.script] = s;
  return true;
}
bool fresh(void *, Round r, const Node &old, const Node &now) {
  return fresh_ok && old.graph.handle == (r == Round::exporting ? 1u : 2u) &&
         now.graph.handle == (r == Round::exporting ? 2u : 3u) &&
         now.birth == 100;
}
Result visit(void *, Round r, Emit emit, void *ctx, uint64_t *receipt) {
  *receipt = 0;
  if (wait)
    return Result::waiting;
  auto *ns = r == Round::source      ? sources
             : r == Round::exporting ? exports
                                     : restores;
  for (size_t i = 0; i < (missing ? 1u : 2u); ++i) {
    auto n = ns[i];
    if (duplicate && i)
      n.script = ns[0].script;
    if (bad_key && i)
      n.key.path[0] = 9;
    if (!emit(ctx, n))
      return Result::unsupported;
  }
  *receipt = 9;
  return Result::ok;
}
uint32_t keep(void *p) {
  roots[++sequence] = p;
  return sequence;
}
void *get(uint32_t h) {
  auto i = roots.find(h);
  return i == roots.end() ? nullptr : i->second;
}
void drop(uint32_t h) { assert(roots.erase(h) == 1); }
Api api() {
  return {current, clock,        owned, pending_current,
          visit,   node_current, fresh, read,
          write,   keep,         get,   drop};
}
void setup() {
  for (size_t i = 0; i < 2; ++i) {
    Node n;
    n.key = {&objects[0],     &objects[1],     &objects[2], &objects[3 + i],
             &objects[5 + i], &objects[7 + i], {},          1};
    n.key.path[0] = uint16_t(i);
    n.script = &objects[10 + i];
    n.graph = {1, 2, 0};
    n.runtime = {11 + i, 2, 0};
    n.node = {21 + i, 2, 0};
    n.factory = 1;
    sources[i] = n;
    states[n.script] = {2, int32_t(i + 1)};
    n.script = &objects[14 + i];
    n.graph.handle = 2;
    n.runtime.handle += 100;
    n.node.handle += 100;
    n.factory = 2;
    n.birth = 100;
    exports[i] = n;
    states[n.script] = {2, 0};
    n.script = &objects[18 + i];
    n.graph.handle = 3;
    n.runtime.handle += 100;
    n.node.handle += 100;
    n.factory = 3;
    restores[i] = n;
    states[n.script] = {2, 2};
  }
}
int main(int argc, char **argv) {
  assert(argc == 2);
  std::string c = argv[1];
  setup();
  Scope scope;
  if (c == "capture_bad_enum")
    states[sources[0].script].initial = 3;
  if (c == "capture_duplicate")
    duplicate = true;
  if (c == "capture_unheld")
    held = false;
  if (c == "capture_wait")
    wait = true;
  const auto first = scope.capture(api(), &objects[0], 11);
  if (c.rfind("capture_", 0) == 0) {
    assert(first != Result::ok);
    scope.release(false);
    assert(roots.empty());
    return 0;
  }
  assert(first == Result::ok && scope.current());
  Node found{};
  assert(scope.lookup_receiver(sources[0].script, false, &found) &&
         found.key.target == sources[0].key.target);
  assert(!scope.lookup_receiver(&objects[39], false, &found));
  if (c == "pending_lost")
    pending = false;
  assert((scope.expect_remap(Round::exporting) == Result::ok) == pending);
  if (!pending) {
    scope.release(false);
    assert(roots.empty());
    return 0;
  }
  source_live = false;
  size_t queries = old_queries;
  assert(scope.current() && old_queries == queries);
  if (c == "remap_wait")
    wait = true;
  if (c == "remap_missing")
    missing = true;
  if (c == "remap_duplicate")
    duplicate = true;
  if (c == "remap_key")
    bad_key = true;
  if (c == "remap_birth")
    fresh_ok = false;
  if (c == "remap_post")
    states[exports[0].script].post = 1;
  if (c == "remap_initial")
    states[exports[0].script].initial = 3;
  auto mapped = scope.remap(Round::exporting);
  if (c.rfind("remap_", 0) == 0) {
    assert(mapped != Result::ok && !writes);
    scope.release(false);
    assert(roots.empty());
    return 0;
  }
  assert(mapped == Result::ok && old_queries == queries && scope.current());
  assert(scope.lookup_receiver(sources[0].script, true, &found));
  assert(!scope.lookup_receiver(sources[0].script, false, &found));
  assert(scope.restore() == Result::waiting && !writes);
  assert(scope.expect_remap(Round::restoring) == Result::ok);
  private_live = false;
  assert(scope.remap(Round::restoring) == Result::ok && scope.current());
  if (c == "restore_unheld")
    held = false;
  if (c == "restore_owner")
    owner = false;
  if (c == "restore_node")
    restore_live = false;
  if (c == "restore_post")
    states[restores[0].script].post = 1;
  if (c == "restore_initial")
    states[restores[0].script].initial = 3;
  if (c == "restore_write")
    write_ok = false;
  if (c == "restore_partial")
    partial = true;
  auto restored = scope.restore();
  if (c.rfind("restore_", 0) == 0) {
    assert(restored != Result::ok);
    if (c == "restore_partial") {
      assert(writes == 1);
      assert(scope.restore() == Result::ok);
    }
    scope.release(false);
    assert(roots.empty());
    return 0;
  }
  assert(restored == Result::ok && writes == 2 &&
         scope.round() == Round::restored);
  for (size_t i = 0; i < 2; ++i)
    assert(states[restores[i].script].post == 2 &&
           states[restores[i].script].initial == int32_t(i + 1));
  if (c == "restored_changed") {
    states[restores[0].script].initial = 0;
    assert(scope.restore() != Result::ok);
  } else {
    assert(scope.restore() == Result::ok && writes == 2);
    assert(scope.release(true) == Result::ok);
  }
  scope.release(false);
  assert(roots.empty());
}
