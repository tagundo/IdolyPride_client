#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
using Method = const void;
namespace mp4actor {
struct Handle {
  uintptr_t handle = 0;
  uint32_t version = 0, padding = 0;
};
} // namespace mp4actor
namespace mp4an {
struct Key {
  void *target = nullptr;
};
struct Node {
  Key key{};
  void *script = nullptr;
  mp4actor::Handle node{};
};
} // namespace mp4an
struct Binding {
  uintptr_t rva = 0;
};
struct {
  Binding calls[7]{};
} mp4_activation_pins;
struct Script {
  uint64_t bytes[2]{};
  void *target = nullptr;
} script;
struct NativeMethod {
  uintptr_t entry = 0;
} method;
bool thread = true, schema = true, lookup = true, retired = false,
     target_current = true, component_current = true, have_origin = true;
uint64_t origin_token = 7;
void *allowed_component = &schema;
uintptr_t image_base = 100;
struct {
  bool active = true;
  bool captured() const { return active; }
  bool target_current(void *p) {
    return ::target_current && p == script.target;
  }
  bool affected(void *p, void *go) {
    return component_current && p == allowed_component && go == script.target;
  }
} mp4_activation_targets;
struct {
  bool active = true;
  bool captured() const { return active; }
  bool lookup_receiver(void *p, bool old, mp4an::Node *out) {
    if (!lookup || p != &script || old != retired)
      return false;
    out->key.target = script.target;
    out->script = &script;
    out->node = {42, 3, 0};
    return true;
  }
} mp4_activation_nodes;
bool game_call() { return thread; }
bool mp4_activation_node_schema(void *) { return schema; }
void *object_class(void *p) { return p; }
const void *method_lookup(void *, const char *, int) { return &method; }
auto font_method = method_lookup;
template <class T> bool mp4_actor_field(void *p, size_t off, T &out) {
  if (off == 0 && p == &method && sizeof(T) == 8) {
    std::memcpy(&out, &method.entry, 8);
    return true;
  }
  if (off == 16 && p == &script && sizeof(T) == 8) {
    std::memcpy(&out, &script.target, 8);
    return true;
  }
  return false;
}
#include "activation-callback-origin.cpp"
uint64_t receipt(Mp4ActivationOperation, const mp4an::Node &) {
  return have_origin ? origin_token : 0;
}
int main(int argc, char **argv) {
  assert(argc == 2);
  std::string c = argv[1];
  script.target = &lookup;
  for (size_t i = 1; i < 6; ++i)
    mp4_activation_pins.calls[i].rva = 10 + i;
  method.entry = image_base + 11;
  mp4_activation_callback_origin = receipt;
  Mp4ActivationOperation op = Mp4ActivationOperation::play;
  mp4actor::Handle playable{42, 3, 0};
  if (c == "ordinary")
    mp4_activation_targets.active = false;
  if (c == "thread")
    thread = false;
  if (c == "nodes_uncaptured")
    mp4_activation_nodes.active = false;
  if (c == "missing_origin")
    mp4_activation_callback_origin = nullptr;
  if (c == "schema")
    schema = false;
  if (c == "method")
    ++method.entry;
  if (c == "lookup")
    lookup = false;
  if (c == "retired_play")
    retired = true;
  if (c == "retired_destroy") {
    retired = true;
    op = Mp4ActivationOperation::destroy;
    method.entry = image_base + 15;
  }
  if (c == "playable")
    ++playable.handle;
  if (c == "version")
    ++playable.version;
  if (c == "no_receipt")
    have_origin = false;
  if (c == "target")
    target_current = false;
  Mp4ActivationOrigin scope;
  const bool expected = c == "normal" || c == "ordinary" ||
                        c == "retired_destroy" || c == "component" ||
                        c == "end_receipt" || c == "end_thread" ||
                        c == "nested" || c == "depth_limit" ||
                        c == "exception" || c == "out_of_order";
  assert(mp4_activation_origin_begin(scope, &script, playable, &method, op) ==
         expected);
  if (!expected) {
    assert(!mp4_activation_origin && !scope.receipt && !scope.published);
    return 0;
  }
  if (c == "ordinary") {
    assert(!scope.published && !mp4_activation_origin &&
           !mp4_activation_callback_execution(allowed_component));
    assert(mp4_activation_origin_end(scope));
    return 0;
  }
  assert(scope.published && scope.receipt == 7 &&
         mp4_activation_callback_execution(allowed_component));
  assert(!mp4_activation_callback_execution(&method));
  if (c == "component") {
    component_current = false;
    assert(!mp4_activation_callback_execution(allowed_component));
    component_current = true;
  }
  if (c == "nested") {
    Mp4ActivationOrigin inner;
    assert(mp4_activation_origin_begin(inner, &script, playable, &method, op) &&
           inner.depth == 2 && inner.previous == &scope);
    assert(mp4_activation_origin_end(inner) && mp4_activation_origin == &scope);
  }
  if (c == "depth_limit") {
    scope.depth = 16;
    Mp4ActivationOrigin inner;
    assert(
        !mp4_activation_origin_begin(inner, &script, playable, &method, op) &&
        mp4_activation_origin == &scope);
    scope.depth = 1;
  }
  if (c == "exception") {
    try {
      Mp4ActivationOriginGuard guard(scope);
      throw 17;
    } catch (int code) {
      assert(code == 17);
    }
    assert(!mp4_activation_origin && !scope.receipt && !scope.published);
    return 0;
  }
  if (c == "out_of_order") {
    Mp4ActivationOrigin inner;
    assert(mp4_activation_origin_begin(inner, &script, playable, &method, op));
    assert(!mp4_activation_origin_end(scope) && !mp4_activation_origin);
    mp4_activation_origin_abandon(inner);
    assert(!mp4_activation_origin);
    return 0;
  }
  if (c == "end_receipt")
    ++origin_token;
  if (c == "end_thread")
    thread = false;
  assert(mp4_activation_origin_end(scope) ==
         (c != "end_receipt" && c != "end_thread"));
  assert(!mp4_activation_origin && !scope.published && !scope.receipt);
}
