#pragma once

#ifndef IDOLY_DARWIN_BRIDGE
#include <cstddef>
#include <cstring>
#endif

namespace idoly::presentation {

template<class T> class ScopedValue {
    T &slot;
    T previous;
public:
    ScopedValue(T &slot, T value) : slot(slot), previous(slot) { slot = value; }
    ~ScopedValue() { slot = previous; }
    ScopedValue(const ScopedValue &) = delete;
    ScopedValue &operator=(const ScopedValue &) = delete;
};

template<class T> class ScopedMemory {
    void *address;
    T previous{};
    bool active;
public:
    ScopedMemory(void *object, size_t offset, bool active) :
        address(static_cast<char *>(object) + offset), active(active) {
        if (active) std::memcpy(&previous, address, sizeof previous);
    }
    void set(T value) { if (active) std::memcpy(address, &value, sizeof value); }
    ~ScopedMemory() { if (active) std::memcpy(address, &previous, sizeof previous); }
    ScopedMemory(const ScopedMemory &) = delete;
    ScopedMemory &operator=(const ScopedMemory &) = delete;
};

// Register native state restoration before applying a temporary setter. This
// also restores the state when a later original IL2CPP call unwinds.
class ScopedCleanup {
    void (*callback)(void *);
    void *context;
public:
    ScopedCleanup(void (*callback)(void *), void *context) : callback(callback), context(context) {}
    ~ScopedCleanup() { callback(context); }
    ScopedCleanup(const ScopedCleanup &) = delete;
    ScopedCleanup &operator=(const ScopedCleanup &) = delete;
};
}
