#pragma once

#include <cstddef>
#include <cstring>

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
}
