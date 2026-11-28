#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <memory>
#include "proflare-registry-scope.hpp.inc"
#include "proflare-storage-promotion.hpp.inc"
namespace p = idoly_mp4_proflare_registry;
struct F {
  int32_t id;
};
struct H {
  F a{1}, b{257}, other{9};
  void *rows[8]{}, *data[2]{};
  int32_t queue[8]{}, buckets[8]{};
  p::Entry entries[8]{};
  p::Image image{};
  p::Flare flares[2]{};
  std::map<uint32_t, void *> roots;
  uint32_t seq = 1;
  uint64_t token = 33;
  bool valid = true, held = true, birth = true, write = true, data_authority = true, data_completed = true;
  int writes = 0;
  H() {
    image.batch = this;
    image.native = 17;
    image.atlas = &other;
    image.list = {&image.list, rows, nullptr, rows, 2, 7, 8};
    rows[0] = &a;
    image.data = {&image.data, data, nullptr, data, 1, 2, 2};
    data[0] = &image;
    image.queue = {&image.queue, queue, nullptr, queue, 0, 1, 1, 1, 8};
    queue[0] = 1;
    image.dictionary = {&image.dictionary,
                        buckets,
                        entries,
                        nullptr,
                        nullptr,
                        nullptr,
                        nullptr,
                        buckets,
                        entries,
                        1,
                        3,
                        0,
                        -1,
                        8,
                        8};
    entries[0] = {1, -1, 1, 0};
    buckets[1] = 1;
    flares[0] = {&a, &other, 11, 1, 100};
    flares[1] = {&b, &other, 12, 257, 101};
  }
  static bool current(void *c, uint64_t e) {
    return static_cast<H *>(c)->valid && e == 7;
  }
  static bool hold(void *c) { return static_cast<H *>(c)->held; }
  static bool read(void *c, p::Image *o) {
    *o = static_cast<H *>(c)->image;
    return true;
  }
  static bool flare(void *c, const p::Flare &f) {
    auto &h = *static_cast<H *>(c);
    return h.birth && f.initialized &&
           ((f.object == &h.a && f.instance == 1 && f.native == 11) ||
            (f.object == &h.b && f.instance == 257 && f.native == 12));
  }
  static int32_t instance(void *, void *o) { return static_cast<F *>(o)->id; }
  static uint64_t origin(void *c, void *, p::Operation) {
    return static_cast<H *>(c)->token;
  }
  static bool put(void *c, const p::Image &i, void *const *l, const int32_t *q,
                  const int32_t *b, const p::Entry *e,void*const*data_rows) {
    auto &h = *static_cast<H *>(c);
    if (!h.write)
      return false;
    ++h.writes;
    for (size_t n = 0; n < i.list.capacity; ++n)
      i.list.rows[n] = l[n];
    for (size_t n = 0; n < i.queue.capacity; ++n)
      i.queue.rows[n] = q[n];
    for (size_t n = 0; n < i.dictionary.bucket_capacity; ++n)
      i.dictionary.bucket_rows[n] = b[n];
    for (size_t n = 0; n < i.dictionary.capacity; ++n)
      i.dictionary.rows[n] = e[n];
    for(size_t n=0;n<i.data.capacity;++n)i.data.rows[n]=data_rows[n];
    h.image = i;
    return true;
  }
  static H *root_host;
  static uint32_t retain(void *p) {
    auto &h = *root_host;
    auto n = h.seq++;
    h.roots[n] = p;
    return n;
  }
  static void *target(uint32_t n) { return root_host->roots[n]; }
  static void release(uint32_t n) { root_host->roots.erase(n); }
  static uint64_t data_origin(void*c,p::DataOperation,void*,void*) {
    auto&h=*static_cast<H*>(c);return h.data_authority?h.token:0;
  }
  static bool data_complete(void*c,p::DataOperation,void*,void*,uint64_t token) {
    auto&h=*static_cast<H*>(c);return h.data_authority&&h.data_completed&&token==h.token;
  }
  p::Api api() {
    root_host = this;
    p::Api a{current, hold, read, flare, instance, origin, put, retain, target, release};
    a.data_origin=data_origin;a.data_complete=data_complete;return a;
  }
  void add(F *f) {
    auto &d = image.dictionary;
    auto &q = image.queue;
    auto &l = image.list;
    int32_t slot=0;
    if(q.count){slot=queue[q.head];q.head=(q.head+1)%q.capacity;--q.count;++q.version;}
    else slot=static_cast<int32_t>(l.count++);
    rows[slot] = f;
    ++l.version;
    int at = d.free_count ? d.free_list : static_cast<int>(d.count++);
    if (d.free_count) {
      d.free_list = entries[at].next;
      --d.free_count;
    }
    int bucket = (f->id & 0x7fffffff) % d.bucket_capacity;
    entries[at] = {f->id & 0x7fffffff, buckets[bucket] - 1, f->id, slot};
    buckets[bucket] = at + 1;
    ++d.version;
    image.atlas = &other;
  }
  void remove(F *f) {
    auto &d = image.dictionary;
    auto &q = image.queue;
    auto &l = image.list;
    int bucket = (f->id & 0x7fffffff) % d.bucket_capacity;
    int prev = -1, at = buckets[bucket] - 1;
    while (at >= 0 && entries[at].key != f->id) {
      prev = at;
      at = entries[at].next;
    }
    if (at < 0)
      return;
    auto e = entries[at];
    if (prev < 0)
      buckets[bucket] = e.next + 1;
    else
      entries[prev].next = e.next;
    rows[e.value] = nullptr;
    ++l.version;
    queue[q.tail] = e.value;
    q.tail = (q.tail + 1) % q.capacity;
    ++q.count;
    ++q.version;
    entries[at] = {-1, d.free_list, 0, 0};
    d.free_list = at;
    ++d.free_count;
    ++d.version;
    if (d.count == d.free_count)
      image.atlas = nullptr;
  }
};
H *H::root_host = nullptr;
int cases = 0;
bool expect(bool b, int line) {
  ++cases;
  if (!b)
    std::printf("FAILED %d\n", line);
  return b;
}
#define CHECK(x)                                                               \
  do {                                                                         \
    if (!expect((x), __LINE__))                                                \
      return 1;                                                                \
  } while (0)
int main() {
  {
    H h;
    p::Scope s;
    CHECK(s.capture(h.api(), &h, 7, h.flares, 2) == p::Result::ok);
    CHECK(s.current());
    uint64_t token = 0;
    CHECK(s.begin(&h.b, p::Operation::enable, &token) == p::Result::ok);
    CHECK(!s.current());
    h.add(&h.b);
    CHECK(s.end(token, true) == p::Result::ok);
    CHECK(h.rows[1] == &h.b);
    CHECK(s.begin(&h.a, p::Operation::disable, &token) == p::Result::ok);
    h.remove(&h.a);
    CHECK(s.end(token, true) == p::Result::ok);
    CHECK(s.restore() == p::Result::ok);
    CHECK(h.rows[0] == &h.a && !h.rows[1] && h.image.dictionary.count == 1 &&
          h.image.dictionary.version == 3 && h.image.queue.version == 1 &&
          h.image.list.version == 7);
    s.release();
    CHECK(h.roots.empty());
  }
  {
    H h;
    p::Scope s;
    h.flares[1].initialized = 0;
    CHECK(s.capture(h.api(), &h, 7, h.flares, 2) == p::Result::unsupported);
    s.release();
    CHECK(h.roots.empty());
  }
  {
    H h;
    p::Scope s;
    h.image.queue.capacity = 1;
    CHECK(s.capture(h.api(), &h, 7, h.flares, 2) == p::Result::unsupported);
    s.release();
  }
  {
    H h;
    p::Scope s;
    h.queue[0] = 0;
    CHECK(s.capture(h.api(), &h, 7, h.flares, 2) == p::Result::unsupported);
    s.release();
  }
  {
    H h;
    p::Scope s;
    h.buckets[1] = 8;
    CHECK(s.capture(h.api(), &h, 7, h.flares, 2) == p::Result::unsupported);
    s.release();
  }
  {
    H h;
    p::Scope s;
    h.entries[0].next = 0;
    CHECK(s.capture(h.api(), &h, 7, h.flares, 2) == p::Result::unsupported);
    s.release();
  }
  {
    H h;
    p::Scope s;
    h.entries[0].hash = 2;
    CHECK(s.capture(h.api(), &h, 7, h.flares, 2) == p::Result::unsupported);
    s.release();
  }
  {
    H h;
    p::Scope s;
    CHECK(s.capture(h.api(), &h, 7, h.flares, 2) == p::Result::ok);
    h.rows[3] = &h.b;
    CHECK(!s.current());
    s.release();
  }
  {
    H h;
    p::Scope s;
    CHECK(s.capture(h.api(), &h, 7, h.flares, 2) == p::Result::ok);
    uint64_t t = 0;
    h.token = 0;
    CHECK(s.begin(&h.b, p::Operation::enable, &t) == p::Result::unsupported);
    s.release();
  }
  {
    H h;
    p::Scope s;
    CHECK(s.capture(h.api(), &h, 7, h.flares, 2) == p::Result::ok);
    uint64_t t = 0;
    CHECK(s.begin(&h.b, p::Operation::enable, &t) == p::Result::ok);
    h.add(&h.b);
    h.token++;
    CHECK(s.end(t, true) == p::Result::failed);
    CHECK(!s.current());
    s.release();
  }
  {
    H h;
    p::Scope s;
    CHECK(s.capture(h.api(), &h, 7, h.flares, 2) == p::Result::ok);
    uint64_t t = 0;
    CHECK(s.begin(&h.b, p::Operation::enable, &t) == p::Result::ok);
    h.add(&h.b);
    h.image.list.array = &h;
    CHECK(s.end(t, true) == p::Result::failed);
    s.release();
  }
  {
    H h;
    p::Scope s;
    CHECK(s.capture(h.api(), &h, 7, h.flares, 2) == p::Result::ok);
    uint64_t t = 0;
    CHECK(s.begin(&h.b, p::Operation::enable, &t) == p::Result::ok);
    h.add(&h.b);
    h.remove(&h.a);
    CHECK(s.end(t, true) == p::Result::failed);
    s.release();
  }
  {
    H h;
    p::Scope s;
    CHECK(s.capture(h.api(), &h, 7, h.flares, 2) == p::Result::ok);
    uint64_t t = 0;
    CHECK(s.begin(&h.other, p::Operation::enable, &t) == p::Result::unowned);
    s.release();
  }
  {
    H h;
    p::Scope s;
    CHECK(s.capture(h.api(), &h, 7, h.flares, 2) == p::Result::ok);
    h.held = false;
    CHECK(s.restore() == p::Result::stale);
    h.held = true;
    h.birth = false;
    CHECK(!s.current());
    s.release();
  }
  {
    H h;
    p::Scope s;
    CHECK(s.capture(h.api(), &h, 7, h.flares, 2) == p::Result::ok);
    h.write = false;
    CHECK(s.restore() == p::Result::failed);
    s.release();
  }
  {
    H h; p::Scope s;
    h.image.list.count=0;h.rows[0]=nullptr;h.image.queue.head=h.image.queue.tail=h.image.queue.count=0;
    h.image.dictionary.count=0;h.buckets[1]=0;
    CHECK(s.capture(h.api(),&h,7,h.flares,2)==p::Result::ok);
    uint64_t token=0;
    CHECK(s.begin(&h.b,p::Operation::start,&token)==p::Result::ok);
    h.add(&h.b);CHECK(s.end(token,true)==p::Result::ok);
    CHECK(h.image.list.count==1&&h.rows[0]==&h.b);
    CHECK(s.restore()==p::Result::ok);CHECK(h.image.list.count==0&&!h.rows[0]&&h.image.dictionary.count==0);
    s.release();CHECK(h.roots.empty());
  }
  {
    H h; p::LogicalImage saved;p::PromotedImage restored;
    h.image.list.capacity=2;h.image.queue.capacity=2;h.image.dictionary.capacity=3;h.image.dictionary.bucket_capacity=3;
    CHECK(saved.capture(h.image));auto after=h.image;
    void*new_list[8]{};int32_t new_queue[8]{},new_buckets[7]{};p::Entry new_entries[7]{};
    after.list.array=new_list;after.list.rows=new_list;after.list.capacity=8;
    after.queue.array=new_queue;after.queue.rows=new_queue;after.queue.capacity=8;
    after.dictionary.buckets=new_buckets;after.dictionary.bucket_rows=new_buckets;after.dictionary.bucket_capacity=7;
    after.dictionary.entries=new_entries;after.dictionary.rows=new_entries;after.dictionary.capacity=7;
    CHECK(saved.restore_image(after,&restored));CHECK(restored.image.list.count==2&&restored.list[0]==&h.a&&!restored.list[1]);
    CHECK(restored.image.list.array==new_list&&restored.image.dictionary.rows==new_entries);
    CHECK(restored.queue[0]==1&&restored.image.queue.count==1&&restored.image.queue.head==0&&restored.image.queue.tail==1);
    CHECK(restored.entries[0].key==1&&restored.entries[0].value==0&&restored.buckets[1]==1&&restored.image.dictionary.version==3);
    auto wrong=after;wrong.dictionary.object=&h;CHECK(!saved.restore_image(wrong,&restored));
    wrong=after;wrong.data.version++;CHECK(!saved.restore_image(wrong,&restored));
    wrong=after;wrong.list.capacity=1;CHECK(!saved.restore_image(wrong,&restored));
    wrong=after;wrong.dictionary.comparer=&h;CHECK(!saved.restore_image(wrong,&restored));
  }
  {
    H h;p::LogicalImage saved;p::PromotedImage restored;
    h.image.list.count=0;h.image.list.capacity=0;h.image.list.rows=nullptr;
    h.image.queue.count=0;h.image.queue.capacity=0;h.image.queue.rows=nullptr;
    h.image.dictionary.count=0;h.image.dictionary.capacity=h.image.dictionary.bucket_capacity=0;
    h.image.dictionary.rows=nullptr;h.image.dictionary.bucket_rows=nullptr;h.image.dictionary.free_list=0;
    CHECK(saved.capture(h.image));H initialized;auto after=initialized.image;
    after.batch=h.image.batch;after.native=h.image.native;after.list.object=h.image.list.object;after.queue.object=h.image.queue.object;
    after.dictionary.object=h.image.dictionary.object;after.data=h.image.data;
    CHECK(saved.restore_image(after,&restored));CHECK(restored.image.list.count==0&&restored.image.dictionary.count==0&&restored.image.dictionary.free_list==-1&&!restored.list[0]);
  }
  std::printf("%d cases passed\n", cases);
  return 0;
}
