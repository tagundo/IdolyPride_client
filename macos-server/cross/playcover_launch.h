#ifndef IDOLY_PLAYCOVER_LAUNCH_H
#define IDOLY_PLAYCOVER_LAUNCH_H

/* PlayCover 3.1.0 a103786: only its game-list double click calls PlayApp.launch.
   Its URL handler has source management, and it has no game-launch CLI/URL API.
   Activate existing games; otherwise hand off to PlayCover's own preparation. */
#define IDOLY_GAME_BUNDLE "game.qualiarts.idolypride.local"
#define IDOLY_PLAYCOVER_BUNDLE "io.playcover.PlayCover"
#define IDOLY_PLAYCOVER_INSTRUCTION "PlayCover에서 ‘아이프라 로컬’을 두 번 클릭해 실행해 주세요."

extern int strcmp(const char *, const char *);

enum IDLaunchRoute { ID_LAUNCH_SERVER_STOPPED, ID_LAUNCH_FOCUS_GAME, ID_LAUNCH_FOCUS_PLAYCOVER, ID_LAUNCH_FIND_PLAYCOVER };

static enum IDLaunchRoute id_launch_route(int server_running, int game_running, int playcover_running) {
    if (!server_running) return ID_LAUNCH_SERVER_STOPPED;
    if (game_running) return ID_LAUNCH_FOCUS_GAME;
    return playcover_running ? ID_LAUNCH_FOCUS_PLAYCOVER : ID_LAUNCH_FIND_PLAYCOVER;
}

static int id_playcover_candidate_valid(int exists, int directory, int executable_exists, const char *bundle) {
    return exists && directory && executable_exists && bundle && strcmp(bundle, IDOLY_PLAYCOVER_BUNDLE) == 0;
}

#endif
