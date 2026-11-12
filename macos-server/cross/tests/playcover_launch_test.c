#include <stdio.h>
#include <string.h>
#include "../playcover_launch.h"

static int checks;
#define CHECK(value) do { ++checks; if (!(value)) { fprintf(stderr, "launch policy failed at %d\n", __LINE__); return 1; } } while (0)

int main(void) {
    for (int game = 0; game < 2; ++game) for (int playcover = 0; playcover < 2; ++playcover)
        CHECK(id_launch_route(0, game, playcover) == ID_LAUNCH_SERVER_STOPPED);
    CHECK(id_launch_route(1, 1, 0) == ID_LAUNCH_FOCUS_GAME);
    CHECK(id_launch_route(1, 1, 1) == ID_LAUNCH_FOCUS_GAME);
    CHECK(id_launch_route(1, 0, 1) == ID_LAUNCH_FOCUS_PLAYCOVER);
    CHECK(id_launch_route(1, 0, 0) == ID_LAUNCH_FIND_PLAYCOVER);
    CHECK(id_playcover_candidate_valid(1, 1, 1, IDOLY_PLAYCOVER_BUNDLE));
    CHECK(!id_playcover_candidate_valid(0, 1, 1, IDOLY_PLAYCOVER_BUNDLE)); /* stale LS path */
    CHECK(!id_playcover_candidate_valid(1, 0, 1, IDOLY_PLAYCOVER_BUNDLE));
    CHECK(!id_playcover_candidate_valid(1, 1, 0, IDOLY_PLAYCOVER_BUNDLE));
    CHECK(!id_playcover_candidate_valid(1, 1, 1, IDOLY_GAME_BUNDLE)); /* never launch the cached game alias */
    CHECK(!id_playcover_candidate_valid(1, 1, 1, "other.application"));
    CHECK(!id_playcover_candidate_valid(1, 1, 1, 0));
    CHECK(strstr(IDOLY_PLAYCOVER_INSTRUCTION, "PlayCover") != 0);
    printf("PASS: %d PlayCover launch routing checks\n", checks);
    return 0;
}
