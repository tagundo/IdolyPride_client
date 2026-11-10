#ifndef IDOLY_QA_UI_JSON_H
#define IDOLY_QA_UI_JSON_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* ASCII-only JSON avoids JNI modified-UTF8 ambiguity. UTF16 is escaped exactly. */
struct ui_json { char *data; size_t capacity, length; bool failed; };
static inline void ui_raw(struct ui_json *j, const char *s) {
    size_t n = strlen(s);
    if (j->failed || n >= j->capacity || j->length >= j->capacity - n) { j->failed = true; return; }
    memcpy(j->data + j->length, s, n + 1); j->length += n;
}
static inline void ui_number(struct ui_json *j, int64_t n) {
    char value[32]; snprintf(value, sizeof(value), "%lld", (long long)n); ui_raw(j, value);
}
static inline void ui_utf16(struct ui_json *j, const uint16_t *s, size_t length, size_t limit) {
    ui_raw(j, "\"");
    if (length > limit) length = limit;
    /* Do not truncate a surrogate pair between its two halves. */
    if (length && s[length - 1] >= 0xd800 && s[length - 1] <= 0xdbff) --length;
    for (size_t i = 0; i < length && !j->failed; ++i) {
        unsigned v = s[i]; char part[8];
        if (v == '"') ui_raw(j, "\\\"");
        else if (v == '\\') ui_raw(j, "\\\\");
        else if (v >= 32 && v < 127) { part[0] = (char)v; part[1] = 0; ui_raw(j, part); }
        else { snprintf(part, sizeof(part), "\\u%04x", v); ui_raw(j, part); }
    }
    ui_raw(j, "\"");
}
#endif
