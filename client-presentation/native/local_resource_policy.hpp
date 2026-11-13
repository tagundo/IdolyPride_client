#pragma once

#include <cstddef>
#include <cstdint>

namespace idoly::presentation::local_resources {

// This is the exact origin in the version-locked Android client's patched
// Octo literal. It is independent of OS Internet reachability. Accept only
// object routes the local gateway can look up; no URL normalization is used.
inline constexpr size_t max_url_units = 199;

inline bool literal(const uint16_t *url, size_t length, size_t &at,
                    const char *value, size_t count) {
    if (at > length || count > length - at) return false;
    for (size_t i = 0; i < count; ++i)
        if (url[at + i] != static_cast<unsigned char>(value[i])) return false;
    at += count;
    return true;
}

inline bool decimal(const uint16_t *url, size_t length, size_t &at,
                    uint64_t maximum, bool final) {
    if (at >= length || url[at] < '1' || url[at] > '9') return false;
    uint64_t value = 0;
    while (at < length && url[at] >= '0' && url[at] <= '9') {
        const unsigned digit = url[at++] - '0';
        if (value > (maximum - digit) / 10) return false;
        value = value * 10 + digit;
    }
    if (final) return at == length;
    if (at >= length || url[at] != '/') return false;
    ++at;
    return true;
}

inline bool object_url(const uint16_t *url, size_t length) {
    if (!url || !length || length > max_url_units) return false;
    size_t at = 0;
    constexpr char prefix[] = "http://127.0.0.1:8080/octo/";
    if (!literal(url, length, at, prefix, sizeof prefix - 1)
            || !decimal(url, length, at, INT32_MAX, false)) return false;
    if (!literal(url, length, at, "assetbundle/", 12)
            && !literal(url, length, at, "resources/", 10)) return false;
    const size_t name = at;
    while (at < length && url[at] != '/') {
        const uint16_t c = url[at++];
        if (at - name > 128 || !((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')
                || (c >= '0' && c <= '9') || c == '_' || c == '-')) return false;
    }
    if (at == name || at >= length) return false;
    ++at;
    return decimal(url, length, at, UINT64_MAX, true);
}

} // namespace idoly::presentation::local_resources
