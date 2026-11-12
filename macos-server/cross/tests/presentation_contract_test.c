#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "../presentation_contract.h"

static int checks;
#define CHECK(value) do { ++checks; if (!(value)) { fprintf(stderr, "check failed at line %d\n", __LINE__); return 1; } } while (0)

static int replace_field(const char *source, const char *field, const char *replacement, char *output, size_t capacity) {
    char key[96]; snprintf(key, sizeof key, "\"%s\":", field);
    const char *start = strstr(source, key);
    if (!start) return 0;
    start += strlen(key);
    const char *end = start;
    while (*end && *end != ',' && *end != '}') ++end;
    int count = snprintf(output, capacity, "%.*s%s%s", (int)(start - source), source, replacement, end);
    return count > 0 && (size_t)count < capacity;
}

int main(int argc, char **argv) {
    IDPrefs prefs = id_prefs_defaults(), decoded;
    char json[2048], changed[4096];
    int bytes = id_prefs_encode(&prefs, json, sizeof json);
    CHECK(bytes > 0 && id_prefs_decode(json, (size_t)bytes, &decoded));
    CHECK(decoded.revision == 0 && decoded.custom == 0 && decoded.scale == 1 && decoded.maximum == 4096 && decoded.aa == -1);
    prefs.custom = 1; prefs.quality = 40; prefs.fps = 60; prefs.scale = 0.625;
    prefs.maximum = 2000; prefs.aa = 2; prefs.shadow = 4096; prefs.expand = 1;
    IDPrefs first, second, third;
    CHECK(id_prefs_next(&prefs, 100, &first) && first.revision == 100);
    CHECK(id_prefs_next(&first, 100, &second) && second.revision == 101);
    CHECK(id_prefs_next(&second, 10, &third) && third.revision == 102);
    if (argc == 2 && strcmp(argv[1], "--json") == 0) {
        IDPrefs samples[] = {first, second, third};
        for (int i = 0; i < 3; ++i) { CHECK(id_prefs_encode(&samples[i], json, sizeof json)); puts(json); }
        return 0;
    }
    CHECK(id_prefs_encode(&third, json, sizeof json) && id_prefs_decode(json, strlen(json), &decoded));
    CHECK(decoded.revision == 102 && decoded.scale == 0.625 && decoded.maximum == 2000 && decoded.expand == 1);
    const char *integerFields[] = {"schema", "revision", "quality", "target_fps", "max_buffer_pixel", "anti_aliasing", "shadow_resolution"};
    for (int i = 0; i < 7; ++i) {
        CHECK(replace_field(json, integerFields[i], "1.0", changed, sizeof changed));
        CHECK(!id_prefs_decode(changed, strlen(changed), &decoded));
        CHECK(replace_field(json, integerFields[i], "true", changed, sizeof changed));
        CHECK(!id_prefs_decode(changed, strlen(changed), &decoded));
    }
    const char *fields[] = {"custom_graphics", "expand_photography", "revision", "quality", "target_fps",
        "anti_aliasing", "shadow_resolution", "render_scale", "render_scale", "render_scale", "max_buffer_pixel", "max_buffer_pixel"};
    const char *invalid[] = {"1", "\"false\"", "-1", "50", "45", "3", "999", "true", "0.24", "2.01", "257", "4098"};
    for (int i = 0; i < 12; ++i) {
        CHECK(replace_field(json, fields[i], invalid[i], changed, sizeof changed));
        CHECK(!id_prefs_decode(changed, strlen(changed), &decoded));
    }
    snprintf(changed, sizeof changed, "{\"schema\":1,%s", json + 1);
    CHECK(!id_prefs_decode(changed, strlen(changed), &decoded));
    snprintf(changed, sizeof changed, "{\"\\u0073chema\":1,%s", json + 1);
    CHECK(!id_prefs_decode(changed, strlen(changed), &decoded));
    snprintf(changed, sizeof changed, "{\"audience\":true,%s", json + 1);
    CHECK(!id_prefs_decode(changed, strlen(changed), &decoded));
    CHECK(replace_field(json, "revision", "9223372036854775807", changed, sizeof changed));
    CHECK(id_prefs_decode(changed, strlen(changed), &decoded) && decoded.revision == 9223372036854775807LL);
    CHECK(!id_prefs_next(&decoded, 100, &prefs));
    CHECK(replace_field(json, "revision", "9223372036854775808", changed, sizeof changed));
    CHECK(!id_prefs_decode(changed, strlen(changed), &decoded));
    CHECK(replace_field(json, "render_scale", "2.5e-1", changed, sizeof changed));
    CHECK(id_prefs_decode(changed, strlen(changed), &decoded) && decoded.scale == 0.25);
    CHECK(replace_field(json, "render_scale", "NaN", changed, sizeof changed));
    CHECK(!id_prefs_decode(changed, strlen(changed), &decoded));
    CHECK(replace_field(json, "render_scale", "01", changed, sizeof changed));
    CHECK(!id_prefs_decode(changed, strlen(changed), &decoded));
    CHECK(replace_field(json, "render_scale", "1e10000", changed, sizeof changed));
    CHECK(!id_prefs_decode(changed, strlen(changed), &decoded));
    CHECK(!id_prefs_decode("[]", 2, &decoded));
    CHECK(!id_prefs_decode("", 0, &decoded));
    char tooLarge[8193]; memset(tooLarge, ' ', sizeof tooLarge);
    CHECK(!id_prefs_decode(tooLarge, sizeof tooLarge, &decoded));
    decoded = third;
    CHECK(!id_prefs_decode("{}", 2, &decoded) && decoded.revision == third.revision && decoded.scale == third.scale);
    char tiny[] = {'X', 'X', 'X', 'X', 'S'};
    CHECK(!id_prefs_encode(&third, tiny, 4) && tiny[4] == 'S');

    IDPolling polling = {0};
    CHECK(!id_poll_fresh(&polling, 10));
    CHECK(id_poll_begin(&polling));
    for (int i = 0; i < 100; ++i) CHECK(!id_poll_begin(&polling));
    id_poll_received(&polling, 10);
    CHECK(id_poll_fresh(&polling, 15)); CHECK(!id_poll_fresh(&polling, 15.01)); CHECK(!id_poll_fresh(&polling, 9));
    CHECK(id_poll_begin(&polling)); id_poll_received(&polling, 20); CHECK(id_poll_fresh(&polling, 21));
    CHECK(id_ack_feedback(1, 1, 100, 1, 100, "applied") == 2);
    CHECK(id_ack_feedback(1, 1, 100, 1, 100, "disabled") == 3);
    CHECK(id_ack_feedback(1, 1, 100, 1, 99, "applied") == 1);
    CHECK(id_ack_feedback(1, 1, 100, 1, 101, "disabled") == 1);
    CHECK(id_ack_feedback(0, 1, 100, 1, 100, "applied") == 1);
    CHECK(id_ack_feedback(1, 0, 100, 1, 100, "applied") == 1);
    CHECK(id_ack_feedback(1, 1, 100, 0, 100, "applied") == 1);
    CHECK(id_ack_feedback(1, 1, 100, 1, 0, "unsupported") == 4);
    CHECK(id_ack_feedback(1, 1, 100, 1, 0, "waiting_for_scene") == 5);
    CHECK(id_ack_feedback(1, 1, 100, 1, 0, "init_failed") == 6);
    CHECK(id_ack_feedback(1, 1, 0, 1, 0, "unknown") == 0);
    printf("PASS: %d SDK-free presentation/ACK/poll checks\n", checks);
    return 0;
}
