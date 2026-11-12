// Independent startup media schema; the graphics/playback schemas stay intact.
#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <cstdint>
#include <cstring>
#endif
namespace idoly::presentation {
struct MediaConfigMessage {
    int64_t revision = 0;
    bool hide_video_mv = false;
    int mv_sort = 0; // recent, old, title, id
    int outfit_sort = 0; // original, recent, old, title, id
    bool same_values(const MediaConfigMessage &other) const {
        return hide_video_mv == other.hide_video_mv && mv_sort == other.mv_sort
            && outfit_sort == other.outfit_sort;
    }
};
inline void media_space(const char *&p) { while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') ++p; }
inline bool media_word(const char *&p, char *out, unsigned capacity) {
    if (*p++ != '"') return false;
    unsigned used = 0;
    while (*p && *p != '"' && used + 1 < capacity) {
        if (*p == '\\' || static_cast<unsigned char>(*p) < 32 || static_cast<unsigned char>(*p) > 126) return false;
        out[used++] = *p++;
    }
    out[used] = 0; return *p++ == '"';
}
inline bool decode_media_settings(const char *input, MediaConfigMessage *output) {
    if (!input || !output) return false;
    size_t bytes = 0; while (bytes <= 8192 && input[bytes]) ++bytes;
    if (!bytes || bytes > 8192) return false;
    const char *keys[] = {"schema", "revision", "hide_video_mv", "mv_sort", "outfit_sort"};
    const char *mv[] = {"recent", "old", "title", "id"};
    const char *outfit[] = {"original", "recent", "old", "title", "id"};
    const char *p = input; MediaConfigMessage value; unsigned seen = 0; int64_t schema = 0;
    media_space(p); if (*p++ != '{') return false;
    for (unsigned count = 0; count < 5; ++count) {
        media_space(p); char key[32]; if (!media_word(p, key, sizeof key)) return false;
        int field = -1;
        for (int i = 0; i < 5; ++i) if (!std::strcmp(key, keys[i])) field = i;
        if (field < 0 || (seen & (1u << field))) return false;
        seen |= 1u << field; media_space(p); if (*p++ != ':') return false; media_space(p);
        if (field <= 1) {
            if (*p < '0' || *p > '9') return false;
            const bool zero = *p == '0'; int64_t integer = 0; unsigned digits = 0;
            while (*p >= '0' && *p <= '9') {
                unsigned digit = static_cast<unsigned>(*p++ - '0');
                if ((zero && digits) || integer > 922337203685477580ll
                        || (integer == 922337203685477580ll && digit > 7)) return false;
                integer = integer * 10 + digit; ++digits;
            }
            if (field == 0) schema = integer; else value.revision = integer;
        } else if (field == 2) {
            if (!std::strncmp(p, "true", 4)) { value.hide_video_mv = true; p += 4; }
            else if (!std::strncmp(p, "false", 5)) { value.hide_video_mv = false; p += 5; }
            else return false;
        } else {
            char word[16]; if (!media_word(p, word, sizeof word)) return false;
            const char **choices = field == 3 ? mv : outfit;
            const int total = field == 3 ? 4 : 5; int selected = -1;
            for (int i = 0; i < total; ++i) if (!std::strcmp(word, choices[i])) selected = i;
            if (selected < 0) return false;
            if (field == 3) value.mv_sort = selected; else value.outfit_sort = selected;
        }
        media_space(p);
        if (count == 4) { if (*p++ != '}') return false; }
        else if (*p++ != ',') return false;
    }
    media_space(p); if (*p || schema != 1 || seen != 31) return false;
    *output = value; return true;
}
} // namespace idoly::presentation
