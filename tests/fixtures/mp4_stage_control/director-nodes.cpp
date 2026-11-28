#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <limits>
#include <map>
#include <string>
#include "director-node-scope.hpp.inc"
using namespace idoly_mp4_director_nodes;
int objects[30]{};
bool owner = true, held = true, pending = true, source_live = true,
     fresh_ok = true, private_live = true, restore_live = true,
     wait_visit = false, missing = false, duplicate = false, bad_key = false,
     bad_state = false, throw_visit = false, partial = false, write_ok = true;
size_t writes = 0, source_node_queries = 0;
uint32_t nextroot = 0;
std::map<uint32_t, void *> roots;
std::map<void *, State> states;
Node source_nodes[2]{}, export_nodes[2]{}, restore_nodes[2]{};
bool current(void *, uint64_t e) { return owner && e == 11; }
bool clock_held(void *) { return held; }
bool owner_current(void *, const Key &) { return owner; }
bool pending_current(void *, Round) { return pending; }
bool node_current(void *, const Node &n) {
  if (n.graph.handle == 1) {
    ++source_node_queries;
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
  if (partial) {
    states[n.script].sync = s.sync;
    partial = false;
    return false;
  }
  if (!write_ok)
    return false;
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
  if (wait_visit)
    return Result::waiting;
  const auto *nodes = r == Round::source      ? source_nodes
                      : r == Round::exporting ? export_nodes
                                              : restore_nodes;
  for (size_t i = 0; i < (missing ? 1u : 2u); ++i) {
    auto n = nodes[i];
    if (duplicate && i)
      n.script = nodes[0].script;
    if (bad_key && i)
      n.key.path[0] = 9;
    if (!emit(ctx, n))
      return Result::unsupported;
    if (throw_visit)
      throw 7;
  }
  *receipt = 9;
  return Result::ok;
}
uint32_t keep(void *p) {
  roots[++nextroot] = p;
  return nextroot;
}
void *get(uint32_t h) {
  auto i = roots.find(h);
  return i == roots.end() ? nullptr : i->second;
}
void drop(uint32_t h) { assert(roots.erase(h) == 1); }
Api api() {
  return {current, clock_held,   owner_current, pending_current,
          visit,   node_current, fresh,         read,
          write,   keep,         get,           drop};
}
void setup() {
  for (size_t i = 0; i < 2; ++i) {
    Key key{&objects[0],     &objects[1],     &objects[2], &objects[3 + i],
            &objects[5 + i], &objects[7 + i], {},          1};
    key.path[0] = static_cast<uint16_t>(i);
    Node n{key, &objects[10 + i], {1, 2, 0}, {11 + i, 2, 0}, {21 + i, 2, 0}, 1,
           0};
    source_nodes[i] = n;
    states[n.script] = {static_cast<uint8_t>(i), double(50 + i)};
    n.script = &objects[14 + i];
    n.graph.handle = 2;
    n.runtime.handle += 100;
    n.node.handle += 100;
    n.factory = 2;
    n.birth = 100;
    export_nodes[i] = n;
    states[n.script] = {0, std::numeric_limits<double>::max()};
    n.script = &objects[18 + i];
    n.graph.handle = 3;
    n.runtime.handle += 100;
    n.node.handle += 100;
    n.factory = 3;
    restore_nodes[i] = n;
    states[n.script] = {1, 999};
  }
}
int main(int argc, char **argv) {
  assert(argc == 2);
  std::string c = argv[1];
  setup();
  Scope scope;
  if (c == "capture_duplicate")
    duplicate = true;
  else if (c == "capture_state")
    states[source_nodes[0].script].duration = __builtin_nan("");
  else if (c == "capture_throw")
    throw_visit = true;
  if(c=="capture_wait_retry"){
   wait_visit=true;assert(scope.capture(api(),&scope,11)==Result::waiting&&roots.empty());
   wait_visit=false;assert(scope.capture(api(),&scope,11)==Result::ok);assert(scope.release(false)==Result::ok&&roots.empty());return 0;
  }
  if (c == "capture_throw") {
    try {
      (void)scope.capture(api(), &scope, 11);
      assert(false);
    } catch (int v) {
      assert(v == 7);
    }
    assert(scope.release(false) == Result::ok && roots.empty());
    return 0;
  }
  const bool captured = c != "capture_duplicate" && c != "capture_state";
  assert((scope.capture(api(), &scope, 11) == Result::ok) == captured);
  if (!captured) {
    assert(scope.release(false) == Result::ok && roots.empty());
    return 0;
  }
  if (c == "no_rebuild") {
    assert(scope.restore() == Result::ok);
    assert(scope.release(false) == Result::ok && roots.empty());
    return 0;
  }
  if (c == "pending_reject") {
    pending = false;
    assert(scope.expect_remap(Round::exporting) == Result::stale);
    assert(scope.release(false) == Result::ok && roots.empty());
    return 0;
  }
  assert(scope.expect_remap(Round::exporting) == Result::ok);
  source_live = false;
  const auto reads_before = source_node_queries;
  assert(scope.current() && source_node_queries == reads_before);
  if (c == "pending_lost") {
    pending = false;
    assert(!scope.current() && source_node_queries == reads_before);
    assert(scope.release(false) == Result::ok && roots.empty());
    return 0;
  }
  if (c == "pending_wait") {
    wait_visit = true;
    assert(scope.remap(Round::exporting) == Result::waiting && writes == 0 &&
           scope.current());
    wait_visit = false;
  }
  if (c == "map_missing")
    missing = true;
  else if (c == "map_duplicate")
    duplicate = true;
  else if (c == "map_key")
    bad_key = true;
  else if (c == "map_birth")
    fresh_ok = false;
  else if (c == "map_state")
    states[export_nodes[1].script].sync = 2;
  const bool mapped = c.rfind("map_", 0) != 0;
  assert((scope.remap(Round::exporting) == Result::ok) == mapped);
  if (!mapped) {
    assert(!writes);
    assert(scope.release(false) == Result::ok && roots.empty());
    return 0;
  }
  assert(scope.current());
  assert(states[export_nodes[0].script].duration ==
         std::numeric_limits<double>::max());
  assert(scope.restore() == Result::waiting);
  if (c == "source_lost") {
    owner = false;
    assert(!scope.current() && scope.release(false) == Result::ok &&
           roots.empty());
    return 0;
  }
  if (c == "cleanup_false") {
    assert(scope.release(false) == Result::ok && writes == 0 && roots.empty());
    return 0;
  }
  assert(scope.expect_remap(Round::restoring) == Result::ok);
  private_live = false;
  assert(scope.current());
  assert(scope.remap(Round::restoring) == Result::ok);
  if (c == "restore_unheld") {
    held = false;
    assert(scope.restore() == Result::waiting && writes == 0);
    held = true;
  }
  if (c == "restore_write_failure") {
    write_ok = false;
    assert(scope.restore() == Result::stale && writes == 1);
    assert(scope.release(false) == Result::ok && roots.empty());
    return 0;
  }
  if (c == "restore_partial") {
    partial = true;
    assert(scope.restore() == Result::stale && writes == 1);
  }
  assert(scope.restore() == Result::ok && scope.current());
  const auto written = writes;
  assert(scope.restore() == Result::ok && writes == written);
  for (size_t i = 0; i < 2; ++i) {
    assert(states[restore_nodes[i].script].sync == i);
    assert(states[restore_nodes[i].script].duration == 50 + i);
    assert(scope.retired_receiver(source_nodes[i].script, source_nodes[i].key));
    assert(scope.retired_receiver(export_nodes[i].script, source_nodes[i].key));
  }
  if (c == "restored_superseded") {
    states[restore_nodes[0].script].duration = 12;
    assert(!scope.current() && scope.restore() == Result::stale);
  }
  assert(scope.release(false) == Result::ok && roots.empty());
  if (c == "reuse") {
    source_live = true;
    assert(scope.capture(api(), &scope, 11) == Result::ok);
    assert(scope.release(false) == Result::ok && roots.empty());
  }
}
