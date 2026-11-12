#ifndef IDOLY_PLAYBACK_CONTRACT_H
#define IDOLY_PLAYBACK_CONTRACT_H

#include "presentation_contract.h"

/* Independent playback preferences: never add these members to presentation. */
typedef struct { long long revision; int waitForOrientation; } IDPlaybackPrefs;

static inline IDPlaybackPrefs id_playback_defaults(void) {
    IDPlaybackPrefs value = {0, 1}; return value;
}

static inline int id_playback_valid(const IDPlaybackPrefs *value) {
    return value->revision >= 0 && (value->waitForOrientation == 0 || value->waitForOrientation == 1);
}

static inline int id_playback_decode(const char *bytes, IDPSize length, IDPlaybackPrefs *output) {
    static const char *keys[] = {"schema", "revision", "wait_for_orientation"};
    if (!bytes || !length || length > 8192) return 0;
    IDPlaybackPrefs value = id_playback_defaults();
    IDPSize offset = 0;
    unsigned int seen = 0;
    id_skip_space(bytes, length, &offset);
    if (offset >= length || bytes[offset++] != '{') return 0;
    for (;;) {
        char key[64];
        id_skip_space(bytes, length, &offset);
        if (!id_key(bytes, length, &offset, key)) return 0;
        int field = -1;
        for (int i = 0; i < 3; ++i) if (strcmp(key, keys[i]) == 0) field = i;
        if (field < 0 || (seen & (1U << field))) return 0;
        seen |= 1U << field;
        id_skip_space(bytes, length, &offset);
        if (offset >= length || bytes[offset++] != ':') return 0;
        id_skip_space(bytes, length, &offset);
        if (field == 2) {
            if (!id_boolean(bytes, length, &offset, &value.waitForOrientation)) return 0;
        } else {
            long long number;
            if (!id_integer(bytes, length, &offset, &number)) return 0;
            if (field == 0) { if (number != 1) return 0; }
            else value.revision = number;
        }
        id_skip_space(bytes, length, &offset);
        if (offset >= length) return 0;
        if (bytes[offset] == '}') { ++offset; break; }
        if (bytes[offset++] != ',') return 0;
    }
    id_skip_space(bytes, length, &offset);
    if (offset != length || seen != 7 || !id_playback_valid(&value)) return 0;
    *output = value;
    return 1;
}

static inline int id_playback_encode(const IDPlaybackPrefs *value, char *bytes, IDPSize capacity) {
    if (!id_playback_valid(value)) return 0;
    int length = snprintf(bytes, capacity, "{\"schema\":1,\"revision\":%lld,\"wait_for_orientation\":%s}",
        value->revision, value->waitForOrientation ? "true" : "false");
    return length > 0 && (IDPSize)length < capacity ? length : 0;
}

static inline int id_playback_next(const IDPlaybackPrefs *current, long long now, IDPlaybackPrefs *next) {
    if (!id_playback_valid(current) || current->revision == 9223372036854775807LL) return 0;
    *next = *current;
    next->revision = current->revision + 1;
    if (now > next->revision) next->revision = now;
    return 1;
}

#endif
