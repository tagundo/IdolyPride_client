#include <stdio.h>
#include <string.h>
#include "../playback_contract.h"

static int checks;
#define CHECK(value) do { ++checks; if (!(value)) { fprintf(stderr, "playback contract failed at %d\n", __LINE__); return 1; } } while (0)

int main(int argc, char **argv) {
    IDPlaybackPrefs value = id_playback_defaults(), decoded;
    char bytes[512];
    CHECK(value.revision == 0 && value.waitForOrientation);
    int length = id_playback_encode(&value, bytes, sizeof bytes);
    CHECK(length > 0 && id_playback_decode(bytes, (IDPSize)length, &decoded));
    CHECK(decoded.revision == 0 && decoded.waitForOrientation);
    value.waitForOrientation = 1;
    IDPlaybackPrefs first, second, third;
    CHECK(id_playback_next(&value, 100, &first) && first.revision == 100);
    CHECK(id_playback_next(&first, 100, &second) && second.revision == 101);
    CHECK(id_playback_next(&second, 1, &third) && third.revision == 102);
    CHECK(id_playback_encode(&third, bytes, sizeof bytes));
    CHECK(id_playback_decode(bytes, strlen(bytes), &decoded));
    CHECK(decoded.revision == 102 && decoded.waitForOrientation);
    if (argc == 2 && strcmp(argv[1], "--json") == 0) { puts(bytes); return 0; }

    const char *invalid[] = {
        "{}", "[]", "null", "{\"schema\":1,\"revision\":0}",
        "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":0}",
        "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":\"false\"}",
        "{\"schema\":1,\"revision\":true,\"wait_for_orientation\":false}",
        "{\"schema\":1,\"revision\":0.0,\"wait_for_orientation\":false}",
        "{\"schema\":true,\"revision\":0,\"wait_for_orientation\":false}",
        "{\"schema\":2,\"revision\":0,\"wait_for_orientation\":false}",
        "{\"schema\":1,\"revision\":-1,\"wait_for_orientation\":false}",
        "{\"schema\":1,\"revision\":9223372036854775808,\"wait_for_orientation\":false}",
        "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":false,\"quality\":40}",
        "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":false,\"schema\":1}",
        "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":false,\"\\u0073chema\":1}",
        "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":false,}",
        "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":false} trailing",
    };
    for (unsigned long i = 0; i < sizeof invalid / sizeof invalid[0]; ++i) {
        decoded = third;
        CHECK(!id_playback_decode(invalid[i], strlen(invalid[i]), &decoded));
        CHECK(decoded.revision == third.revision && decoded.waitForOrientation);
    }
    const char reordered[] = " { \"wait_for_orientation\" : false, \"revision\" : 13, \"schema\" : 1 }\n";
    CHECK(id_playback_decode(reordered, sizeof reordered - 1, &decoded));
    CHECK(decoded.revision == 13 && !decoded.waitForOrientation);
    /* A new default must never replace an explicitly saved false value. */
    CHECK(id_playback_encode(&decoded, bytes, sizeof bytes));
    IDPlaybackPrefs reopened = id_playback_defaults();
    CHECK(id_playback_decode(bytes, strlen(bytes), &reopened));
    CHECK(reopened.revision == 13 && !reopened.waitForOrientation);
    const char escaped[] = "{\"\\u0073chema\":1,\"revision\":0,\"wait_for_orientation\":false}";
    CHECK(id_playback_decode(escaped, sizeof escaped - 1, &decoded));
    CHECK(decoded.revision == 0 && !decoded.waitForOrientation);
    value.revision = 9223372036854775807LL;
    CHECK(id_playback_encode(&value, bytes, sizeof bytes));
    CHECK(id_playback_decode(bytes, strlen(bytes), &decoded));
    CHECK(!id_playback_next(&value, 100, &decoded));
    char tiny[] = {'x', 'x', 'x', 'x', 'S'};
    CHECK(!id_playback_encode(&value, tiny, 4) && tiny[4] == 'S');
    value.waitForOrientation = 2;
    CHECK(!id_playback_encode(&value, bytes, sizeof bytes));
    CHECK(!id_playback_next(&value, 100, &decoded));
    char huge[8193]; memset(huge, ' ', sizeof huge);
    CHECK(!id_playback_decode(huge, sizeof huge, &decoded));
    CHECK(!id_playback_decode(0, 0, &decoded));
    /* Playback preferences and edits cannot alter the ten-field graphics format. */
    IDPrefs graphics = id_prefs_defaults(), roundTrip;
    CHECK(id_prefs_encode(&graphics, bytes, sizeof bytes));
    CHECK(id_prefs_decode(bytes, strlen(bytes), &roundTrip));
    CHECK(strstr(bytes, "wait_for_orientation") == 0 && roundTrip.revision == 0 && roundTrip.maximum == 4096);
    printf("PASS: %d independent playback preference checks\n", checks);
    return 0;
}
