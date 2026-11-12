// Separate, bounded playback schema; the presentation schema stays unchanged.
#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <cstdint>
#include <cstring>
#endif

namespace idoly::presentation {
struct PlaybackConfigMessage {
    std::int64_t revision = 0;
    bool wait_for_orientation = true;
};

inline void playback_space(const char *&cursor) {
    while (*cursor == ' ' || *cursor == '\t' || *cursor == '\r' || *cursor == '\n') ++cursor;
}

inline bool decode_playback_settings(const char *input, PlaybackConfigMessage *output) {
    if (!input || !output) return false;
    size_t bytes = 0;
    while (bytes <= 8192 && input[bytes]) ++bytes;
    if (!bytes || bytes > 8192) return false;
    const char *keys[] = {"schema", "revision", "wait_for_orientation"};
    const char *cursor = input;
    PlaybackConfigMessage value; unsigned seen = 0; std::int64_t schema = 0;
    playback_space(cursor); if (*cursor++ != '{') return false;
    for (unsigned count = 0; count < 3; ++count) {
        playback_space(cursor); if (*cursor++ != '"') return false;
        char key[32]; unsigned size = 0;
        while (*cursor && *cursor != '"' && size + 1 < sizeof key) {
            if (*cursor == '\\' || static_cast<unsigned char>(*cursor) < 32
                    || static_cast<unsigned char>(*cursor) > 126) return false;
            key[size++] = *cursor++;
        }
        key[size] = 0; if (*cursor++ != '"') return false;
        int field = -1;
        for (int index = 0; index < 3; ++index) if (!std::strcmp(key, keys[index])) field = index;
        if (field < 0 || (seen & (1u << field))) return false;
        seen |= 1u << field;
        playback_space(cursor); if (*cursor++ != ':') return false; playback_space(cursor);
        if (field == 2) {
            if (!std::strncmp(cursor, "true", 4)) { value.wait_for_orientation = true; cursor += 4; }
            else if (!std::strncmp(cursor, "false", 5)) { value.wait_for_orientation = false; cursor += 5; }
            else return false;
        } else {
            if (*cursor < '0' || *cursor > '9') return false;
            const bool zero = *cursor == '0'; std::int64_t integer = 0; unsigned digits = 0;
            while (*cursor >= '0' && *cursor <= '9') {
                const unsigned digit = static_cast<unsigned>(*cursor++ - '0');
                if ((zero && digits) || integer > 922337203685477580ll
                        || (integer == 922337203685477580ll && digit > 7)) return false;
                integer = integer * 10 + digit; ++digits;
            }
            if (field == 0) schema = integer; else value.revision = integer;
        }
        playback_space(cursor);
        if (count == 2) { if (*cursor++ != '}') return false; }
        else if (*cursor++ != ',') return false;
    }
    playback_space(cursor);
    if (*cursor || schema != 1 || seen != 7) return false;
    *output = value; return true;
}
}
