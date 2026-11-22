#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
namespace mp4game {
struct Binding {
    uintptr_t rva;
    uint8_t prefix[16];
};
} // namespace mp4game
namespace mp4actor {
struct Handle {
    uintptr_t handle = 1;
    uint32_t version = 1, padding = 0;
};
} // namespace mp4actor
struct Mp4AudioProgramImage {
    mp4actor::Handle graph{};
    uintptr_t target_native = 0;
    uint64_t recipe = 42;
};
struct Mp4AudioProgramClip {
    mp4actor::Handle playable{};
    uintptr_t native = 0, voice_shared = 0;
};
struct Managed {
    uint8_t bytes[24]{};
} managed;
struct Native {
    alignas(8) uint8_t bytes[0x410]{};
} native;
struct Box {
    alignas(8) uint8_t bytes[24]{};
} box;
struct Clip {
    alignas(8) uint8_t bytes[0x130]{};
} clip;
uintptr_t entries[4]{};
uintptr_t mp4_native_base = 0;
bool node_current = true;
int copies = 0, releases = 0;
template <class T> void set(void *p, size_t offset, T value) {
    std::memcpy(static_cast<uint8_t *>(p) + offset, &value, sizeof value);
}
template <class T> bool mp4_actor_field(void *p, size_t offset, T &v) {
    if (!p)
        return false;
    std::memcpy(&v, static_cast<uint8_t *>(p) + offset, sizeof v);
    return true;
}
bool game_call() { return true; }
bool mp4_exact_type(void *p, const char *) { return p == &managed; }
bool mp4_alive(void *p) { return p != nullptr; }
bool mp4_actor_mapped(void *, size_t, bool) { return true; }
bool mp4_native_mapped(uintptr_t, size_t, int) { return true; }
bool mp4_audio_program_pins_ready() { return true; }
bool mp4_audio_program_native_node(mp4actor::Handle, mp4actor::Handle, bool, uintptr_t &out) {
    out = reinterpret_cast<uintptr_t>(&clip);
    return node_current;
}
void copy_slot(void *dst, const void *src) {
    ++copies;
    uintptr_t p = 0;
    std::memcpy(&p, src, 8);
    std::memcpy(dst, &p, 8);
    uint32_t n = 0;
    mp4_actor_field(reinterpret_cast<void *>(p), 12, n);
    set(reinterpret_cast<void *>(p), 12, n + 1);
}
void release_slot(void *slot) {
    ++releases;
    uintptr_t p = 0;
    std::memcpy(&p, slot, 8);
    uint32_t n = 0;
    mp4_actor_field(reinterpret_cast<void *>(p), 12, n);
    set(reinterpret_cast<void *>(p), 12, n - 1);
    set(slot, 0, uintptr_t(0));
}
bool playing(void *) { return true; }
#define mp4_audio_channel_pins generated_audio_channel_pins
#include "shipping-channel-pins.inc"
#undef mp4_audio_channel_pins
Mp4AudioChannelPins mp4_audio_channel_pins = generated_audio_channel_pins;
#include "shipping-channel.inc"
void setup() {
    set(&managed, 16, reinterpret_cast<uintptr_t>(&native));
    set(&native, 0x39, uint8_t(1));
    set(&native, 0x318, reinterpret_cast<uintptr_t>(&native) + 0x318);
    set(&native, 0x320, reinterpret_cast<uintptr_t>(&native) + 0x318);
    set(&native, 0x2f8, reinterpret_cast<uintptr_t>(entries));
    set(&native, 0x310, uintptr_t(8));
    set(&box, 12, uint32_t(3));
    set(&clip, 0xc0, reinterpret_cast<uintptr_t>(&native));
    set(&clip, 0x110, reinterpret_cast<uintptr_t>(&box));
    mp4_audio_channel_pins.shared_copy.rva = reinterpret_cast<uintptr_t>(copy_slot);
    std::memcpy(mp4_audio_channel_pins.shared_copy.prefix, reinterpret_cast<void *>(copy_slot), 16);
    mp4_audio_channel_pins.shared_release.rva = reinterpret_cast<uintptr_t>(release_slot);
    std::memcpy(mp4_audio_channel_pins.shared_release.prefix, reinterpret_cast<void *>(release_slot), 16);
    mp4_audio_channel_pins.playing.rva = reinterpret_cast<uintptr_t>(playing);
    std::memcpy(mp4_audio_channel_pins.playing.prefix, reinterpret_cast<void *>(playing), 16);
}
int main() {
    int n = 0;
    setup();
    Mp4AudioSharedPin pin{};
    Mp4AudioProgramImage program{};
    program.target_native = reinterpret_cast<uintptr_t>(&native);
    Mp4AudioProgramClip c{};
    c.native = reinterpret_cast<uintptr_t>(&clip);
    c.voice_shared = reinterpret_cast<uintptr_t>(&box);
    assert(mp4_audio_shared_pin(program, c, 0, pin) && copies == 1);
    uint32_t refs = 0;
    mp4_actor_field(&box, 12, refs);
    assert(refs == 4);
    ++n;
    assert(!mp4_audio_shared_pin(program, c, 0, pin) && copies == 1);
    ++n;
    Mp4AudioChannelImage image{};
    assert(mp4_audio_channel_image(&managed, &pin, 1, image));
    ++n;
    entries[0] = pin.box;
    set(&native, 0x308, uint64_t(1));
    assert(mp4_audio_channel_image(&managed, &pin, 1, image));
    ++n;
    pin.retirement = 7;
    assert(mp4_audio_channel_image(&managed, &pin, 1, image));
    ++n;
    set(&native, 0x395, uint8_t(1));
    set(&native, 0x3ac, uint8_t(1));
    assert(mp4_audio_channel_image(&managed, &pin, 1, image));
    ++n;
    assert(!mp4_audio_channel_image(&managed, nullptr, 0, image));
    ++n;
    auto wrong = pin;
    wrong.source += 8;
    assert(!mp4_audio_channel_image(&managed, &wrong, 1, image));
    ++n;
    set(&native, 0x395, uint8_t(0));
    set(&native, 0x3ac, uint8_t(0));
    entries[0] = pin.box + 8;
    assert(!mp4_audio_channel_image(&managed, &pin, 1, image));
    entries[0] = pin.box;
    ++n;
    for (size_t at : {size_t(0x318), size_t(0x320), size_t(0x358), size_t(0x400)}) {
        uintptr_t old = 0;
        mp4_actor_field(&native, at, old);
        set(&native, at, uintptr_t(1));
        assert(!mp4_audio_channel_image(&managed, &pin, 1, image));
        set(&native, at, old);
        ++n;
    }
    set(&native, 0x310, uintptr_t(0));
    assert(!mp4_audio_channel_image(&managed, &pin, 1, image));
    set(&native, 0x310, uintptr_t(8));
    ++n;
    set(&native, 0x308, uint64_t(4097));
    assert(!mp4_audio_channel_image(&managed, &pin, 1, image));
    set(&native, 0x308, uint64_t(1));
    ++n;
    set(&native, 0x2f8, uintptr_t(0));
    assert(!mp4_audio_channel_image(&managed, &pin, 1, image));
    set(&native, 0x2f8, reinterpret_cast<uintptr_t>(entries));
    ++n;
    for (size_t at : {size_t(0x39), size_t(0x395), size_t(0x3ac)}) {
        set(&native, at, uint8_t(2));
        assert(!mp4_audio_channel_image(&managed, &pin, 1, image));
        set(&native, at, uint8_t(at == 0x39 ? 1 : 0));
        ++n;
    }
    set(&native, 0x308, uint64_t(0));
    mp4_audio_shared_release(pin);
    mp4_actor_field(&box, 12, refs);
    assert(!pin.box && refs == 3 && releases == 1);
    ++n;
    Mp4AudioSharedPin invalid{};
    set(&clip, 0xc0, uintptr_t(44));
    assert(!mp4_audio_shared_pin(program, c, 0, invalid) && copies == 1);
    ++n;
    set(&clip, 0xc0, program.target_native);
    node_current = false;
    assert(!mp4_audio_shared_pin(program, c, 0, invalid) && copies == 1);
    ++n;
    std::printf("Concrete native AudioSource channel host: %d cases passed\n", n);
}
