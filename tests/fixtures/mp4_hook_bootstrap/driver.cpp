#include <cassert>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#include <vector>
extern "C" {
#include "sh_a64.h"
void sh_island_alloc(sh_island_t *, size_t, uintptr_t, uintptr_t, uintptr_t,
                     sh_addr_info_t *, void *) {
  assert(false);
}
}
#include "shipping-bootstrap.hpp" // namespace mp4_bootstrap
using namespace mp4_bootstrap;
static void assert_case(bool value, int line) {
  if (!value) {
    fprintf(stderr, "failed line %d\n", line);
    abort();
  }
}
#define CHECK(x) assert_case(!!(x), __LINE__)
static std::string hex(uintptr_t n) {
  char s[32];
  snprintf(s, sizeof s, "%lx", (unsigned long)n);
  return s;
}
static std::string hex(const uint8_t *p, size_t n) {
  std::string s;
  const char *d = "0123456789abcdef";
  for (size_t i = 0; i < n; ++i) {
    s += d[p[i] >> 4];
    s += d[p[i] & 15];
  }
  return s;
}
struct Region {
  uintptr_t address;
  std::vector<uint8_t> bytes;
};
struct Model {
  std::vector<Region> memory;
  Source engine{0x100000000, 3, 17}, game{0x200000000, 4, 18};
  bool installer = true, pub = true, recordable = false;
  std::string records;
  Install active{};
  BootstrapPin pin{};
  size_t span = 20;
  bool nonproc = false;
  unsigned calls = 0;
  unsigned allocator_gaps = 0;
  void **original_slot = nullptr;
  void put(uintptr_t at, const void *p, size_t n) {
    for (auto &r : memory)
      if (r.address == at) {
        r.bytes.assign((const uint8_t *)p, (const uint8_t *)p + n);
        return;
      }
    memory.push_back(
        {at, std::vector<uint8_t>((const uint8_t *)p, (const uint8_t *)p + n)});
  }
  bool read(uintptr_t at, void *p, size_t n) {
    for (auto &r : memory)
      if (at >= r.address && at - r.address <= r.bytes.size() &&
          n <= r.bytes.size() - (at - r.address)) {
        memcpy(p, r.bytes.data() + at - r.address, n);
        return true;
      }
    return false;
  }
  static bool thread(void *p) { return ((Model *)p)->installer; }
  static bool source(void *p, BootstrapImage i, Source *out) {
    *out =
        i == BootstrapImage::engine ? ((Model *)p)->engine : ((Model *)p)->game;
    return true;
  }
  static bool read(void *p, uintptr_t at, void *b, size_t n) {
    return ((Model *)p)->read(at, b, n);
  }
  static bool installed(void *p, BootstrapRole, uintptr_t t, uintptr_t n,
                        uintptr_t e, uintptr_t s, Install *out) {
    auto &m = *(Model *)p;
    return shadow_record(m.records.c_str(), m.records.size(), t, n, e, s, out);
  }
  static bool gateway(void *, const BootstrapPin &p, const Install &i) {
    return shadow_gateway(p, i);
  }
  static bool publication(void *p, BootstrapRole, const Install &i) {
    auto &m = *(Model *)p;
    return m.pub && m.active.stub == i.stub && m.active.gateway == i.gateway &&
           m.active.serial == i.serial;
  }
  Api api() {
    return {this, thread, source, read, installed, gateway, publication};
  }
  void original(const BootstrapPin &p) {
    pin = p;
    put((p.image == BootstrapImage::engine ? engine : game).base + p.rva,
        p.original, 24);
  }
  Install make(const BootstrapPin &p, size_t copied, bool np) {
    Install i{};
    i.target = (p.image == BootstrapImage::engine ? engine : game).base + p.rva;
    i.replacement = 0x400001000;
    i.gateway = 0x300001000;
    i.stub = 0x500001000;
    i.serial = 1;
    i.span = copied;
    memcpy(i.original, p.original, copied);
    i.enter.address = i.gateway;
    uint32_t buf[48]{};
    sh_a64_rewrite_info_t info{};
    info.start_addr = i.target;
    info.end_addr = i.target + copied;
    info.buf = buf;
    info.inst_lens_cnt = copied / 4;
    for (size_t x = 0; x < copied; x += 4)
      info.inst_lens[x / 4] =
          sh_a64_get_rewrite_inst_len(word(p.original + x), false);
    if (np)
      info.buf_offset = info.inst_prolog_len = sh_a64_restore_ip(buf);
    for (size_t x = 0; x < copied; x += 4) {
      size_t n = sh_a64_rewrite((uint32_t *)((uint8_t *)buf + info.buf_offset),
                                word(p.original + x), i.target + x, &info);
      CHECK(n);
      info.buf_offset += n;
    }
    i.resume = np && copied == 24 ? i.target + 20 : i.target + copied;
    uintptr_t return_address = i.resume;
    if (copied == 4) {
      i.island_exit.address = i.target + 0x10000;
      i.island_exit.count =
          np ? sh_a64_absolute_jump_with_br_rx((uint32_t *)i.island_exit.data,
                                               i.replacement)
             : sh_a64_absolute_jump_with_br_ip((uint32_t *)i.island_exit.data,
                                               i.replacement);
      sh_a64_relative_jump((uint32_t *)i.patch, i.island_exit.address,
                           i.target);
      if (np) {
        i.island_enter.address = i.target + 0x20000;
        i.island_enter.count = 8;
        sh_a64_restore_rx((uint32_t *)i.island_enter.data);
        sh_a64_relative_jump((uint32_t *)(i.island_enter.data + 4), i.resume,
                             i.island_enter.address + 4);
        return_address = i.island_enter.address;
      }
    } else if (np) {
      CHECK(copied == 24);
      sh_a64_absolute_jump_with_br_rx((uint32_t *)i.patch, i.replacement);
      sh_a64_restore_rx((uint32_t *)(i.patch + 20));
    } else {
      CHECK(copied == 20);
      sh_a64_nop((uint32_t *)i.patch);
      sh_a64_absolute_jump_with_br_ip((uint32_t *)(i.patch + 4), i.replacement);
    }
    info.buf_offset +=
        np ? sh_a64_absolute_jump_with_ret_rx(
                 (uint32_t *)((uint8_t *)buf + info.buf_offset), return_address)
           : sh_a64_absolute_jump_with_ret_ip(
                 (uint32_t *)((uint8_t *)buf + info.buf_offset),
                 return_address);
    i.enter.count = info.buf_offset;
    memcpy(i.enter.data, buf, i.enter.count);
    return i;
  }
  std::string record(const Install &i) {
    // Exact official sh_elf.c: S|load_bias|start-end|...; carries variable
    // allocator diagnostics, never mandatory hook/code authority.
    std::string allocator;
    if (allocator_gaps) {
      allocator = "S|" + hex(engine.base);
      for (unsigned gap = 0; gap < allocator_gaps; ++gap)
        allocator += "|" + hex(0x1000u + gap * 0x2000u) + "-" +
                     hex(0x1100u + gap * 0x2000u);
      allocator += ";";
    }
    return "hook_func_addr," + hex(i.target) + "," + hex(i.replacement) + "," +
           std::to_string(i.span) + ",0," + hex(i.stub) +
           ",10," + allocator + "B|arm64|hook;T|" + hex(i.target) + "|" +
           hex(i.original, i.span) + "|" + hex(i.patch, i.span) + ";" +
           (i.island_exit.address
                ? "X|" + hex(i.island_exit.address) + "|1|" +
                      hex(i.island_exit.data, i.island_exit.count) + ";"
                : "") +
           "N|" + hex(i.replacement) + ";E|" + hex(i.gateway) + "|" +
           hex(i.enter.data, i.enter.count) + ";" +
           (i.island_enter.address
                ? "e|" + hex(i.island_enter.address) + "|1|" +
                      hex(i.island_enter.data, i.island_enter.count) + ";"
                : "") +
           "R|" + hex(i.resume) + ";\n";
  }
  void publish(Install i) {
    active = i;
    records = record(i);
    uint8_t head[24];
    memcpy(head, pin.original, 24);
    memcpy(head, i.patch, i.span);
    put(i.target, head, 24);
    put(i.gateway, i.enter.data, i.enter.count);
    if (i.island_exit.address)
      put(i.island_exit.address, i.island_exit.data, i.island_exit.count);
    if (i.island_enter.address)
      put(i.island_enter.address, i.island_enter.data, i.island_enter.count);
  }
};
static Model *global = nullptr;
static bool get_recordable() { return global->recordable; }
static void set_recordable(bool b) { global->recordable = b; }
static char *get_records(uint32_t items) {
  CHECK(items == shadow_record_items);
  return strdup(global->records.c_str());
}
static void *hook(void *t, void *n, void **original, uint32_t flags, ...) {
  auto &m = *global;
  CHECK(flags == 10u);
  CHECK((uintptr_t)t ==
        (m.pin.image == BootstrapImage::engine ? m.engine : m.game).base +
            m.pin.rva);
  CHECK((uintptr_t)n == 0x400001000);
  ++m.calls;
  m.original_slot = original;
  m.publish(m.make(m.pin, m.span, m.nonproc));
  *original = (void *)m.active.gateway;
  return (void *)m.active.stub;
}
int main() {
  unsigned cases = 0;
  CHECK(managed_source_count==24);++cases;
  CHECK(android_managed_source_pin(12)==&android_scene_managed_pins[3]);++cases;
  CHECK(android_managed_source_pin(13)==&android_capture_queue_pins[0]);++cases;
  CHECK(android_managed_source_pin(14)==&android_capture_queue_pins[1]);++cases;
  CHECK(android_managed_source_pin(24)==nullptr);++cases;
  for(size_t i=0;i<managed_source_count;++i){
    CHECK(android_managed_source_pin(i));
    for(size_t j=0;j<i;++j)CHECK(android_managed_source_pin(i)->rva!=android_managed_source_pin(j)->rva);
  }

  struct PinRange { const BootstrapPin* pins; size_t count; };
  for (const auto range : {PinRange{android_bootstrap_pins,8},PinRange{ios_bootstrap_pins,8},
                          PinRange{android_managed_extra_pins,8},PinRange{ios_managed_extra_pins,8},
                          PinRange{android_scene_managed_pins,4},PinRange{ios_scene_managed_pins,4},PinRange{android_capture_queue_pins,2},PinRange{ios_capture_queue_pins,2},PinRange{android_fresh_video_event_pins,9}})
    for (size_t p = 0; p < range.count; ++p)
      for (unsigned mode = 0; mode < 4; ++mode) {
        const auto*pins=range.pins;
        Model m;
        const size_t spans[] = {4, 4, 20, 24};
        const bool np[] = {false, true, false, true};
        m.original(pins[p]);
        auto i = m.make(pins[p], spans[mode], np[mode]);
        CHECK(shadow_gateway(pins[p], i));
        m.publish(i);
        Install out{};
        CHECK(shadow_record(m.records.c_str(), m.records.size(), i.target,
                            i.replacement, i.gateway, i.stub, &out));
        CHECK(shadow_gateway(pins[p], out));
        for (size_t offset = 0; offset < 24; offset += 4)
          if ((word(pins[p].original + offset) & 0xfc000000u) == 0x94000000u) {
            uintptr_t mapped = 0;
            CHECK(
                shadow_return_pc(pins[p], out, i.target + offset + 4, &mapped));
            if (offset >= i.span)
              CHECK(mapped == i.target + offset + 4);
            else {
              CHECK(mapped >= i.gateway + 20 &&
                    mapped <= i.gateway + i.enter.count);
              CHECK(word(i.enter.data + (mapped - i.gateway) - 4) ==
                    0xd63f0220u);
              CHECK(pointer(i.enter.data + (mapped - i.gateway) - 12) ==
                    relative(i.target + offset,
                             sign(uint64_t(word(pins[p].original + offset) &
                                           0x3ffffffu)
                                      << 2,
                                  28)));
            }
            CHECK(!shadow_return_pc(pins[p], out, i.target + offset + 3,
                                    &mapped));
          }

        ++cases;
        auto bad = out;
        bad.enter.data[bad.enter.count - 1] ^= 1;
        CHECK(!shadow_gateway(pins[p], bad));
        bad = out;
        bad.patch[0] ^= 1;
        CHECK(!shadow_gateway(pins[p], bad));
        bad = out;
        bad.original[0] ^= 1;
        CHECK(!shadow_gateway(pins[p], bad));
        bad = out;
        bad.resume += 4;
        CHECK(!shadow_gateway(pins[p], bad));
      }
  for (unsigned mode = 0; mode < 4; ++mode) {
    Model m;
    m.allocator_gaps = 4 + mode;
    m.original(android_bootstrap_pins[0]);
    auto installed = m.make(m.pin, 20, false);
    if (mode == 2) installed.enter.data[0] ^= 1;
    std::string records = m.record(installed);
    if (mode == 1) {
      const auto base = records.find("B|arm64|hook;");
      CHECK(base != std::string::npos);
      records.erase(base, strlen("B|arm64|hook;"));
    }
    Install parsed{};
    const bool accepted = shadow_record(records.c_str(), records.size(),
                                       installed.target, installed.replacement,
                                       installed.gateway, installed.stub, &parsed);
    CHECK(accepted == (mode != 1));
    if (accepted) CHECK(shadow_gateway(m.pin, parsed) == (mode != 2));
    if (mode == 3) {
      // The whole real installer/parser retains mandatory live-code checks
      // when the official allocator emits more than the former five fields.
      global = &m;
      ShadowSourceSpec spec{};
      spec.image = m.pin.image;
      spec.rva = m.pin.rva;
      memcpy(spec.original, m.pin.original, 24);
      spec.library = "libunity.so";
      spec.symbol = "official-allocator-S";
      ShadowService<1> service;
      CHECK(service.configure({get_recordable,set_recordable,hook,get_records,free},
                              {&m,Model::thread,Model::source,Model::read},&spec,1));
      void *original = nullptr;
      CHECK(service.install(0,0x400001000,&original));
      CHECK(service.current(0));
      m.memory[1].bytes[0] ^= 1;
      CHECK(!service.current(0));
    }
    ++cases;
  }
  for (unsigned badcase = 0; badcase < 10; ++badcase) {
    Model m;
    m.original(android_bootstrap_pins[0]);
    auto i = m.make(m.pin, 20, false);
    std::string s = m.record(i);
    const auto flags = s.find(",10,B|");
    CHECK(flags != std::string::npos);
    if (badcase == 0)
      s += s;
    else if (badcase == 1)
      s.replace(flags + 1, 2, "2");
    else if (badcase == 2)
      s.replace(flags + 1, 2, "11");
    else if (badcase == 3)
      s.replace(s.find("|hook;"), 6, "|rehook;");
    else if (badcase == 4)
      s.replace(s.find(";N|"), 3, ";W|");
    else if (badcase == 5)
      s.erase(s.find(";E|"));
    else if (badcase == 6)
      s[s.find("T|") + 2] = 'g';
    else if (badcase == 7)
      s.replace(s.find(",0,"), 3, ",7,");
    else if (badcase == 8)
      i.gateway += 4;
    else
      i.stub += 4;
    Install out{};
    CHECK(!shadow_record(s.c_str(), s.size(), i.target, i.replacement,
                         i.gateway, i.stub, &out));
    ++cases;
  }
  for (unsigned mode = 0; mode < 14; ++mode) {
    Model m;
    Bank b;
    uintptr_t replacements[8];
    for (size_t x = 0; x < 8; ++x)
      replacements[x] = 0x400001000;
    CHECK(b.configure(m.api(), android_bootstrap_pins, replacements));
    m.original(android_bootstrap_pins[0]);
    Ticket ticket{};
    CHECK(b.begin(BootstrapRole::enqueue, &ticket));
    CHECK(!b.begin(BootstrapRole::enqueue, &ticket));
    CHECK(b.begin(BootstrapRole::append_a, &ticket) == false);
    CHECK(b.begin(BootstrapRole::factory, &ticket) == false);
    ticket = {0, 1};
    auto i = m.make(m.pin, 20, false);
    m.publish(i);
    if (mode == 1)
      m.records += m.records;
    if (mode == 2)
      m.memory.back().bytes[0] ^= 1;
    if (mode == 3)
      m.pub = false;
    if (mode == 4)
      ++m.engine.load;
    if (mode == 5)
      ticket.serial = 2;
    const bool okay = b.publish(ticket, i.gateway, i.stub);
    CHECK(okay == (mode == 0 || mode >= 6));
    if (okay) {
      CHECK(b.current(BootstrapRole::enqueue, i.gateway));
      CHECK(b.native_code(m.pin.rva, m.pin.original));
      CHECK(!b.native_code(android_bootstrap_pins[7].rva,
                           android_bootstrap_pins[7].original));
      CHECK(!b.current(BootstrapRole::enqueue, i.gateway + 4));
      if (mode == 6)
        m.pub = false;
      if (mode == 7)
        ++m.engine.cohort;
      if (mode == 8)
        m.memory[0].bytes[0] ^= 1;
      if (mode == 9)
        m.memory[1].bytes[0] ^= 1;
      if (mode == 10)
        b.revoke(BootstrapRole::enqueue);
      if (mode >= 6 && mode <= 10)
        CHECK(!b.current(BootstrapRole::enqueue));
      if (mode == 11) {
        m.memory[0].bytes[23] ^= 1;
        CHECK(!b.current(BootstrapRole::enqueue));
      }
      if (mode == 12) {
        uint8_t prefix[16];
        memcpy(prefix, m.pin.original, 16);
        prefix[0] ^= 1;
        CHECK(!b.native_code(m.pin.rva, prefix));
      }
      if (mode == 13) {
        CHECK(!b.publish(ticket, i.gateway, i.stub));
      }
    }
    ++cases;
  }
  for (unsigned mode = 0; mode < 7; ++mode) {
    Model m;
    global = &m;
    m.original(mode == 6 ? android_managed_extra_pins[0]
                         : android_bootstrap_pins[mode]);
    m.span = mode < 2 ? 4 : mode < 4 ? 20 : 24;
    m.nonproc = (mode % 2) == 1 || m.span == 24;
    if (m.span == 20)
      m.nonproc = false;
    ShadowSourceSpec spec{};
    spec.image = m.pin.image;
    spec.rva = m.pin.rva;
    memcpy(spec.original, m.pin.original, 24);
    spec.library = "libunity.so";
    spec.symbol = "bounded-test";
    ShadowService<1> service;
    CHECK(service.configure(
        {get_recordable, set_recordable, hook, get_records, free},
        {&m, Model::thread, Model::source, Model::read}, &spec, 1));
    void *original = nullptr;
    CHECK(service.install(0, 0x400001000, &original));
    CHECK(m.calls == 1);
    CHECK(service.installed_stub(0) == (void *)m.active.stub);
    m.installer = false;
    CHECK(!service.installed_stub(0));
    m.installer = true;
    CHECK(!m.recordable);
    CHECK(!service.install(0, 0x400001000, &original));
    CHECK(service.current(0));
    if (mode == 6) {
      uintptr_t pc = 0;
      CHECK(service.exact_source_return(0, m.active.target + 16, &pc));
      CHECK(pc == m.active.gateway + 36);
      CHECK(!service.exact_source_return(0, m.active.target + 12, &pc));
    }
    Install out{};
    CHECK(service.receipt(0, m.active.target, m.active.replacement,
                          m.active.gateway, m.active.stub, &out));
    CHECK(service.publication(0, out));
    original = (void *)(m.active.gateway + 4);
    CHECK(!service.current(0));
    ++cases;
  }
  printf("bootstrap cases %u passed\n", cases);
}
