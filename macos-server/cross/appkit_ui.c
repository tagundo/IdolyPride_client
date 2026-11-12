#include "darwin_objc.h"
#include "presentation_contract.h"
#include "playcover_launch.h"

/* The launcher owns Python embedding; this file owns only the Cocoa window and
   its existing local JSON-control child. No client download/install code. */

enum { C_CUSTOM = 1, C_QUALITY, C_FPS, C_SCALE, C_MAXIMUM, C_AA, C_SHADOW, C_EXPAND,
       C_MEDIA = 100, C_LIVE, C_DOWNLOAD, C_START = 200, C_STOP, C_OPEN, C_FOLDER };

static struct {
    IDObj app, delegate, window, timer, task, writer, defaults, dataURL, prefsURL, smokeURL;
    IDObj serverLabel, launchLabel, visualLabel, metricLabel, logView, start, stop, openGame;
    IDObj media, live, download, custom, expand, menus[6];
    IDPrefs prefs;
    int invalidPrefs, saveFailed, running, busy, canStop, mediaMode, liveMode, downloadMode;
    int outFD, errorFD, inputFD, inputClosed, engineEnded, quitting, terminated, termSent;
    int ackBridge, ackPresent, ackState, experimentalObserved;
    long long ackRevision;
    double screenW, screenH, renderW, renderH, baseFOV, fov, cameraAspect;
    double startedAt, quitAt, lastRequestAt;
    double scales[16]; int scaleCount, maxima[16], maximumCount;
    IDPolling polling;
    int smoke, smokeStarted, smokeStopping, smokeFinished;
    char output[131073], errors[32769], logs[60001];
    IDSize outputCount, errorCount, logCount;
} G;

static const int qualities[] = {0, 10, 20, 30, 40, 100};
static const int rates[] = {0, 30, 60, 90, 120};
static const int antiAlias[] = {-1, 0, 1, 2};
static const int shadows[] = {0, 512, 1024, 2048, 4096};
static const char *ackNames[] = {"waiting", "waiting", "applied", "disabled", "unsupported", "waiting_for_scene", "init_failed"};

static double uptime(void) { return id_number(id_get(id_class("NSProcessInfo"), "processInfo"), "systemUptime"); }
static IDObj childURL(IDObj base, const char *name) { return id_arg(base, "URLByAppendingPathComponent:", id_string(name)); }
static int truth(IDObj value) { return id_is(value, "NSNumber") && id_bool(value, "boolValue"); }
static IDObj color(const char *name) { return id_get(id_class("NSColor"), name); }

static void text(IDObj label, const char *value) { if (label) id_set(label, "setStringValue:", id_string(value)); }
static void status(const char *value) { text(G.serverLabel, value); }
static void log_line(const char *value) {
    if (!value || !*value) return;
    IDSize count = strlen(value);
    if (count > 50000) {
        value += count - 50000;
        while (((unsigned char)*value & 0xc0) == 0x80) ++value;
        count = strlen(value);
    }
    if (G.logCount + count + 1 >= sizeof G.logs) {
        IDSize keep = sizeof G.logs - count - 2;
        if (keep > 40000) keep = 40000;
        IDSize remove = G.logCount > keep ? G.logCount - keep : 0;
        while (remove < G.logCount && ((unsigned char)G.logs[remove] & 0xc0) == 0x80) ++remove;
        memmove(G.logs, G.logs + remove, G.logCount - remove);
        G.logCount -= remove;
    }
    memcpy(G.logs + G.logCount, value, count); G.logCount += count;
    if (G.logCount && G.logs[G.logCount - 1] != '\n') G.logs[G.logCount++] = '\n';
    G.logs[G.logCount] = 0;
    if (G.logView) {
        IDObj string = id_string(G.logs);
        id_set(G.logView, "setString:", string);
        IDRange end = {(IDSize)id_long(string, "length"), 0};
        ((void (*)(IDObj, IDSel, IDRange))IDRuntime.message)(G.logView, id_sel("scrollRangeToVisible:"), end);
    }
}

static int create_data_directory(void) {
    return ((IDBool (*)(IDObj, IDSel, IDObj, IDBool, IDObj, IDObj *))IDRuntime.message)(
        id_get(id_class("NSFileManager"), "defaultManager"), id_sel("createDirectoryAtURL:withIntermediateDirectories:attributes:error:"),
        G.dataURL, 1, 0, 0);
}

static int atomic_bytes(IDObj destination, const char *bytes, IDSize count) {
    return ((IDBool (*)(IDObj, IDSel, IDObj, unsigned long, IDObj *))IDRuntime.message)(
        id_data(bytes, count), id_sel("writeToURL:options:error:"), destination, 1, 0);
}

static void load_preferences(void) {
    G.prefs = id_prefs_defaults();
    IDObj manager = id_get(id_class("NSFileManager"), "defaultManager");
    IDObj path = id_get(G.prefsURL, "path");
    IDBool exists = ((IDBool (*)(IDObj, IDSel, IDObj))IDRuntime.message)(manager, id_sel("fileExistsAtPath:"), path);
    if (!exists) return;
    IDObj attributes = ((IDObj (*)(IDObj, IDSel, IDObj, IDObj *))IDRuntime.message)(manager,
        id_sel("attributesOfItemAtPath:error:"), path, 0);
    if (strcmp(id_utf8(id_item(attributes, "NSFileType")), "NSFileTypeRegular") != 0) { G.invalidPrefs = 1; return; }
    int fd = open(id_utf8(path), 0);
    if (fd < 0) { G.invalidPrefs = 1; return; }
    char bytes[8193]; IDSize length = 0;
    while (length < sizeof bytes) {
        long received = read(fd, bytes + length, sizeof bytes - length);
        if (received < 0) { G.invalidPrefs = 1; break; }
        if (!received) break;
        length += (IDSize)received;
    }
    close(fd);
    if (!G.invalidPrefs && !id_prefs_decode(bytes, length, &G.prefs)) G.invalidPrefs = 1;
}

static int save_preferences(IDPrefs changed) {
    double milliseconds = id_number(id_get(id_class("NSDate"), "date"), "timeIntervalSince1970") * 1000.0;
    if (!__builtin_isfinite(milliseconds) || milliseconds >= 9223372036854775807.0) return 0;
    IDPrefs next;
    if (!id_prefs_next(&changed, milliseconds > 0 ? (long long)milliseconds : 0, &next)) return 0;
    char bytes[2048]; int count = id_prefs_encode(&next, bytes, sizeof bytes);
    if (!count || !create_data_directory() || !atomic_bytes(G.prefsURL, bytes, (IDSize)count)) return 0;
    G.prefs = next; G.invalidPrefs = 0; G.saveFailed = 0;
    return 1;
}

static long selected_int(const int *values, int count, int desired) {
    for (int i = 0; i < count; ++i) if (values[i] == desired) return i;
    return 0;
}

static void sync_graphics_controls(void) {
    id_set_long(G.custom, "setState:", G.prefs.custom);
    id_set_long(G.expand, "setState:", G.prefs.expand);
    id_set_long(G.menus[0], "selectItemAtIndex:", selected_int(qualities, 6, G.prefs.quality));
    id_set_long(G.menus[1], "selectItemAtIndex:", selected_int(rates, 5, G.prefs.fps));
    for (int i = 0; i < G.scaleCount; ++i) if (G.scales[i] == G.prefs.scale) id_set_long(G.menus[2], "selectItemAtIndex:", i);
    id_set_long(G.menus[3], "selectItemAtIndex:", selected_int(G.maxima, G.maximumCount, G.prefs.maximum));
    id_set_long(G.menus[4], "selectItemAtIndex:", selected_int(antiAlias, 4, G.prefs.aa));
    id_set_long(G.menus[5], "selectItemAtIndex:", selected_int(shadows, 5, G.prefs.shadow));
    for (int i = 0; i < 6; ++i) id_set_bool(G.menus[i], "setEnabled:", (IDBool)G.prefs.custom);
}

static void update_controls(void) {
    id_set_bool(G.start, "setEnabled:", !G.quitting && !G.running && !G.busy && !G.canStop && !G.engineEnded);
    id_set_bool(G.stop, "setEnabled:", !G.quitting && G.canStop && !G.engineEnded);
    id_set_bool(G.openGame, "setEnabled:", !G.quitting && G.running);
    int modes = !G.running && !G.busy && !G.canStop && !G.quitting;
    id_set_bool(G.media, "setEnabled:", (IDBool)modes);
    id_set_bool(G.live, "setEnabled:", (IDBool)modes);
    id_set_bool(G.download, "setEnabled:", (IDBool)modes);
    int state = id_ack_feedback(G.running && !G.quitting, id_poll_fresh(&G.polling, uptime()), G.prefs.revision,
        G.ackBridge, G.ackRevision, G.ackPresent ? ackNames[G.ackState] : 0);
    const char *message;
    if (G.saveFailed) message = "화면 설정을 저장하지 못했습니다. 이전 설정을 유지합니다.";
    else if (G.invalidPrefs) message = "저장된 설정을 읽지 못해 기본값을 표시합니다. 설정을 바꾸면 새로 저장합니다.";
    else switch (state) {
        case 2: message = "게임에서 현재 설정의 적용을 확인했습니다."; break;
        case 3: message = "게임에서 원본 화면 설정 사용을 확인했습니다."; break;
        case 4: message = "현재 게임 또는 화면 배치에서는 이 설정을 적용할 수 없습니다."; break;
        case 5: message = "게임에서 설정 수신 · 촬영·360 화면 적용 확인 대기"; break;
        case 6: message = "게임의 화면 설정 초기화에 실패했습니다."; break;
        case 1: message = "설정 저장됨 · 게임의 적용 확인 대기"; break;
        default: message = "원본 설정 · 그래픽 지원 게임의 응답 대기";
    }
    text(G.visualLabel, message);
    id_set(G.visualLabel, "setTextColor:", color(G.saveFailed || G.invalidPrefs || state == 4 || state == 6
        ? "systemOrangeColor" : state == 2 || state == 3 ? "systemGreenColor" : "secondaryLabelColor"));
    if (G.ackPresent && id_poll_fresh(&G.polling, uptime()) && G.running && G.renderW > 0 && G.renderH > 0 && G.fov > 0) {
        char values[320];
        snprintf(values, sizeof values, "게임 측정 · 화면 %.0f×%.0f · 3D %.0f×%.0f · 시야각 %.2f° (원본 %.2f°) · 비율 %.3f",
            G.screenW, G.screenH, G.renderW, G.renderH, G.fov, G.baseFOV, G.cameraAspect);
        text(G.metricLabel, values);
    } else text(G.metricLabel, "게임의 3D 화면·시야각 측정값 수신 대기");
}

static int send_control(const char *action) {
    if (!G.task || !id_bool(G.task, "isRunning") || G.inputClosed) return 0;
    char command[320];
    int size;
    if (strcmp(action, "start") == 0) size = snprintf(command, sizeof command,
        "{\"action\":\"start\",\"experimental_main_live\":%s,\"media_mode\":%s,\"download_missing_resources\":%s}\n",
        G.liveMode ? "true" : "false", G.mediaMode ? "true" : "false", G.downloadMode ? "true" : "false");
    else size = snprintf(command, sizeof command, "{\"action\":\"%s\"}\n", action);
    return size > 0 && (IDSize)size < sizeof command && write(G.inputFD, command, (IDSize)size) == size;
}

static void begin_start(void) {
    if (G.running || G.busy || G.canStop || G.quitting) return;
    G.busy = 1; status("서버를 시작하고 있습니다."); update_controls();
    if (!send_control("start")) { G.busy = 0; status("서버 엔진에 요청을 전달하지 못했습니다. 앱을 다시 열어 주세요."); update_controls(); }
}

static void begin_stop(void) {
    if (!G.canStop || G.quitting) return;
    G.busy = 1; status("서버를 중지하고 있습니다."); update_controls();
    if (!send_control("stop")) { G.busy = 0; status("서버 엔진에 요청을 전달하지 못했습니다."); update_controls(); }
}

static void launch_message(const char *message, int failed) {
    text(G.launchLabel, message);
    id_set(G.launchLabel, "setTextColor:", color(failed ? "systemOrangeColor" : "secondaryLabelColor"));
}

static IDObj running_application(const char *bundle) {
    IDObj applications = id_arg(id_class("NSRunningApplication"), "runningApplicationsWithBundleIdentifier:", id_string(bundle));
    long count = id_long(applications, "count");
    if (count > 32) count = 32;
    for (long i = 0; i < count; ++i) {
        IDObj application = id_index(applications, "objectAtIndex:", i);
        if (!id_bool(application, "isTerminated")) return application;
    }
    return 0;
}

static IDBool activate_application(IDObj application) {
    /* NSApplicationActivateIgnoringOtherApps, from NSRunningApplication.h. */
    return application && ((IDBool (*)(IDObj, IDSel, unsigned long))IDRuntime.message)(
        application, id_sel("activateWithOptions:"), 2);
}

static IDObj valid_playcover_url(IDObj candidate) {
    if (!candidate) return 0;
    IDObj manager = id_get(id_class("NSFileManager"), "defaultManager");
    IDObj path = id_get(candidate, "path");
    IDBool directory = 0;
    int exists = ((IDBool (*)(IDObj, IDSel, IDObj, IDBool *))IDRuntime.message)(
        manager, id_sel("fileExistsAtPath:isDirectory:"), path, &directory);
    IDObj bundle = id_arg(id_class("NSBundle"), "bundleWithURL:", candidate);
    IDObj executable = id_get(bundle, "executableURL");
    int executableExists = executable && id_bool_arg(manager, "fileExistsAtPath:", id_get(executable, "path"));
    return id_playcover_candidate_valid(exists, directory, executableExists,
        id_utf8(id_get(bundle, "bundleIdentifier"))) ? candidate : 0;
}

static void open_game(void) {
    IDObj game = running_application(IDOLY_GAME_BUNDLE);
    IDObj playcover = running_application(IDOLY_PLAYCOVER_BUNDLE);
    enum IDLaunchRoute route = id_launch_route(G.running, game != 0, playcover != 0);
    if (route == ID_LAUNCH_SERVER_STOPPED) { launch_message("먼저 서버를 시작해 주세요.", 1); return; }
    if (route == ID_LAUNCH_FOCUS_GAME) {
        launch_message(activate_application(game) ? "실행 중인 아이프라로 전환했습니다."
            : "아이프라가 이미 실행 중입니다. Dock에서 게임 창을 선택해 주세요.", 0);
        return;
    }
    if (route == ID_LAUNCH_FOCUS_PLAYCOVER && activate_application(playcover)) {
        launch_message(IDOLY_PLAYCOVER_INSTRUCTION, 0); return;
    }
    IDObj workspace = id_get(id_class("NSWorkspace"), "sharedWorkspace");
    IDObj home = id_get(id_get(id_class("NSFileManager"), "defaultManager"), "homeDirectoryForCurrentUser");
    IDObj candidates[] = {playcover ? id_get(playcover, "bundleURL") : 0,
        id_arg(workspace, "URLForApplicationWithBundleIdentifier:", id_string(IDOLY_PLAYCOVER_BUNDLE)),
        id_arg(id_class("NSURL"), "fileURLWithPath:", id_string("/Applications/PlayCover.app")),
        childURL(home, "Applications/PlayCover.app")};
    IDObj error = 0, tried[4]; int attempted = 0;
    for (int i = 0; i < 4; ++i) {
        IDObj application = valid_playcover_url(candidates[i]);
        if (!application) continue;
        int duplicate = 0;
        for (int j = 0; j < attempted; ++j)
            if (id_bool_arg(application, "isEqual:", tried[j])) duplicate = 1;
        if (duplicate) continue;
        tried[attempted++] = application;
        error = 0;
        /* NSWorkspaceLaunchDefault == NSWorkspaceLaunchAsync (0x10000).
           Error presentation is not requested. Never launch the game alias. */
        IDObj opened = ((IDObj (*)(IDObj, IDSel, IDObj, unsigned long, IDObj, IDObj *))IDRuntime.message)(workspace,
            id_sel("launchApplicationAtURL:options:configuration:error:"), application, 0x10000,
            id_get(id_class("NSDictionary"), "dictionary"), &error);
        if (opened) { launch_message(IDOLY_PLAYCOVER_INSTRUCTION, 0); return; }
    }
    if (!attempted) {
        launch_message("PlayCover를 찾지 못했습니다. 설치한 위치에서 먼저 연 뒤 다시 눌러 주세요.", 1);
        return;
    }
    char message[320];
    if (error) snprintf(message, sizeof message, "PlayCover를 열지 못했습니다 (OS %ld). PlayCover 아이콘으로 열어 게임을 실행해 주세요.",
        id_long(error, "code"));
    else snprintf(message, sizeof message, "%s", "PlayCover를 열지 못했습니다. PlayCover 아이콘으로 열어 게임을 실행해 주세요.");
    launch_message(message, 1);
}

static void control_action(IDObj self, IDSel command, IDObj sender) {
    (void)self; (void)command;
    void *pool = IDRuntime.poolPush();
    long tag = id_long(sender, "tag");
    if (tag == C_START) begin_start();
    else if (tag == C_STOP) begin_stop();
    else if (tag == C_OPEN) open_game();
    else if (tag == C_FOLDER) {
        create_data_directory();
        id_bool_arg(id_get(id_class("NSWorkspace"), "sharedWorkspace"), "openURL:", G.dataURL);
    } else if (tag >= C_MEDIA && tag <= C_DOWNLOAD) {
        int value = id_long(sender, "state") == 1;
        const char *key;
        if (tag == C_MEDIA) { G.mediaMode = value; key = "mediaMode"; }
        else if (tag == C_LIVE) { G.liveMode = value; key = "experimentalMainLive"; }
        else { G.downloadMode = value; key = "downloadMissingResources"; }
        ((void (*)(IDObj, IDSel, IDBool, IDObj))IDRuntime.message)(G.defaults, id_sel("setBool:forKey:"), (IDBool)value, id_string(key));
    } else if (tag >= C_CUSTOM && tag <= C_EXPAND) {
        IDPrefs changed = G.prefs;
        long index = tag >= C_QUALITY && tag <= C_SHADOW ? id_long(sender, "indexOfSelectedItem") : -1;
        if (tag == C_CUSTOM) changed.custom = id_long(sender, "state") == 1;
        if (tag == C_EXPAND) changed.expand = id_long(sender, "state") == 1;
        if (tag == C_QUALITY && index >= 0 && index < 6) changed.quality = qualities[index];
        if (tag == C_FPS && index >= 0 && index < 5) changed.fps = rates[index];
        if (tag == C_SCALE && index >= 0 && index < G.scaleCount) changed.scale = G.scales[index];
        if (tag == C_MAXIMUM && index >= 0 && index < G.maximumCount) changed.maximum = G.maxima[index];
        if (tag == C_AA && index >= 0 && index < 4) changed.aa = antiAlias[index];
        if (tag == C_SHADOW && index >= 0 && index < 5) changed.shadow = shadows[index];
        if (!save_preferences(changed)) G.saveFailed = 1;
        sync_graphics_controls(); update_controls();
    }
    IDRuntime.poolPop(pool);
}

static IDObj add_label(IDObj parent, const char *value, double y, double height, double size, int secondary) {
    IDObj label = id_arg(id_class("NSTextField"), "labelWithString:", id_string(value));
    id_frame(label, id_rect(12, y, 680, height));
    id_set(label, "setFont:", id_double(id_class("NSFont"), "systemFontOfSize:", size));
    IDObj cell = id_get(label, "cell");
    id_set_bool(cell, "setUsesSingleLineMode:", 0);
    id_set_bool(cell, "setWraps:", 1);
    id_set_bool(cell, "setScrollable:", 0);
    id_set_long(cell, "setLineBreakMode:", 0);
    id_set_bool(label, "setSelectable:", 1);
    if (secondary) id_set(label, "setTextColor:", color("secondaryLabelColor"));
    id_set_long(label, "setAutoresizingMask:", 2);
    id_set(parent, "addSubview:", label);
    return label;
}

static void action_target(IDObj object, long tag) {
    id_set_long(object, "setTag:", tag);
    id_set(object, "setTarget:", G.delegate);
    id_set_selector(object, "setAction:", id_sel("controlAction:"));
}

static IDObj add_button(IDObj parent, const char *title, double x, double y, double width, long tag, int checkbox) {
    IDObj button = id_init_frame(id_get(id_class("NSButton"), "alloc"), id_rect(x, y, width, 28));
    id_set(button, "setTitle:", id_string(title));
    if (checkbox) id_set_long(button, "setButtonType:", 3);
    else id_set_long(button, "setBezelStyle:", 1);
    action_target(button, tag);
    id_set(parent, "addSubview:", button);
    return button;
}

static IDObj add_menu(IDObj parent, const char *title, double y, long tag) {
    IDObj label = add_label(parent, title, y + 4, 24, 13, 0);
    id_frame(label, id_rect(12, y + 4, 180, 24));
    IDObj menu = ((IDObj (*)(IDObj, IDSel, IDRect, IDBool))IDRuntime.message)(id_get(id_class("NSPopUpButton"), "alloc"),
        id_sel("initWithFrame:pullsDown:"), id_rect(204, y, 240, 28), 0);
    action_target(menu, tag);
    id_set(parent, "addSubview:", menu);
    return menu;
}

static void menu_item(IDObj menu, const char *title) { id_set(menu, "addItemWithTitle:", id_string(title)); }
static void add_int_items(IDObj menu, const int *values, int count, int mode) {
    for (int i = 0; i < count; ++i) {
        char value[96];
        if (mode == 0) {
            const char *names[] = {"원본 유지 (0)", "낮음 (10)", "중간 (20)", "높음 (30)", "최고 (40)", "촬영용 (100)"};
            menu_item(menu, names[i]); continue;
        }
        if (mode == 1 && values[i] == 0) { menu_item(menu, "원본 유지 (0)"); continue; }
        if (mode == 3) {
            const char *names[] = {"원본 유지 (-1)", "끔 (0)", "FXAA (1)", "SMAA (2)"};
            menu_item(menu, names[i]); continue;
        }
        if (mode == 4 && values[i] == 0) { menu_item(menu, "원본 유지 (0)"); continue; }
        snprintf(value, sizeof value, mode == 1 ? "%d fps" : mode == 2 ? "%d px" : "%d", values[i]);
        menu_item(menu, value);
    }
}

static IDBool flipped(IDObj self, IDSel selector) { (void)self; (void)selector; return 1; }

static void make_window(void) {
    IDObj viewClass = IDRuntime.allocateClass(id_class("NSView"), "IdolyFlippedView", 0);
    IDRuntime.addMethod(viewClass, id_sel("isFlipped"), (void *)flipped, "B@:");
    IDRuntime.registerClass(viewClass);
    IDObj root = id_init_frame(id_get(viewClass, "alloc"), id_rect(0, 0, 760, 620));
    G.window = ((IDObj (*)(IDObj, IDSel, IDRect, unsigned long, unsigned long, IDBool))IDRuntime.message)(
        id_get(id_class("NSWindow"), "alloc"), id_sel("initWithContentRect:styleMask:backing:defer:"),
        id_rect(0, 0, 760, 620), 15, 2, 0);
    id_set(G.window, "setContentView:", root);
    id_set(G.window, "setTitle:", id_string("아이프라 로컬 서버"));
    id_set_bool(G.window, "setReleasedWhenClosed:", 0);
    IDDimensions minimum = {700, 520};
    ((void (*)(IDObj, IDSel, IDDimensions))IDRuntime.message)(G.window, id_sel("setMinSize:"), minimum);
    add_label(root, "아이프라 로컬 서버 · 이 Mac의 별도 PlayCover 게임에 연결", 14, 30, 20, 0);
    G.serverLabel = add_label(root, "앱을 준비하고 있습니다.", 50, 30, 14, 0);
    G.start = add_button(root, "서버 시작", 12, 88, 110, C_START, 0);
    G.stop = add_button(root, "중지", 128, 88, 85, C_STOP, 0);
    G.openGame = add_button(root, "PlayCover에서 열기", 220, 88, 165, C_OPEN, 0);
    add_button(root, "데이터 폴더", 576, 88, 140, C_FOLDER, 0);
    G.launchLabel = add_label(root, IDOLY_PLAYCOVER_INSTRUCTION, 124, 34, 11, 1);
    add_label(root, "서버 127.0.0.1:50051 · 리소스 127.0.0.1:8080", 164, 22, 11, 1);

    IDObj scroll = id_init_frame(id_get(id_class("NSScrollView"), "alloc"), id_rect(12, 192, 724, 412));
    id_set_bool(scroll, "setHasVerticalScroller:", 1);
    id_set_bool(scroll, "setHasHorizontalScroller:", 0);
    id_set_long(scroll, "setAutoresizingMask:", 2 | 16);
    IDObj document = id_init_frame(id_get(viewClass, "alloc"), id_rect(0, 0, 700, 1060));
    id_set_long(document, "setAutoresizingMask:", 2);
    id_set(scroll, "setDocumentView:", document); id_set(root, "addSubview:", scroll);
    add_label(document, "연결용 IPA는 별도 파일입니다. 위 버튼으로 PlayCover를 연 뒤 게임을 선택해 실행합니다.", 0, 36, 12, 1);
    G.media = add_button(document, "감상용 전체 해금", 8, 40, 430, C_MEDIA, 1);
    id_set_long(G.media, "setState:", G.mediaMode);
    add_label(document, "감상용 저장은 일반 진행과 별도로 보관됩니다. 변경 후 서버를 다시 시작하고 게임 타이틀에서 다시 로그인해 주세요.", 72, 38, 11, 1);
    G.live = add_button(document, "첫 메인 라이브 실험 기능 사용", 8, 114, 470, C_LIVE, 1);
    id_set_long(G.live, "setState:", G.liveMode);
    add_label(document, "첫 퀘스트만 지원하며 로컬 점수 규칙을 사용합니다. 기본값은 꺼짐입니다.", 146, 28, 11, 1);
    G.download = add_button(document, "없는 게임 리소스 내려받기", 8, 180, 470, C_DOWNLOAD, 1);
    id_set_long(G.download, "setState:", G.downloadMode);
    add_label(document, "게임이 요청한 리소스만 보관합니다. 끄면 이미 보관한 파일만 제공합니다. IPA 설치 파일은 내려받지 않습니다.", 212, 36, 11, 1);
    add_label(document, "그래픽·촬영 화면", 256, 30, 17, 0);
    add_label(document, "그래픽 지원 IPA가 필요합니다. 서버 실행 중에도 바꿀 수 있으며 저장 후 실제 게임의 적용 확인을 기다립니다.", 290, 38, 11, 1);
    G.custom = add_button(document, "사용자 그래픽 설정 사용", 8, 332, 450, C_CUSTOM, 1);
    const char *labels[] = {"그래픽 품질", "목표 프레임 수", "3D 렌더 배율", "렌더 버퍼 최대 크기", "가장자리 다듬기", "캐릭터 그림자 해상도"};
    long tags[] = {C_QUALITY, C_FPS, C_SCALE, C_MAXIMUM, C_AA, C_SHADOW};
    for (int i = 0; i < 6; ++i) G.menus[i] = add_menu(document, labels[i], 368 + i * 34, tags[i]);
    add_int_items(G.menus[0], qualities, 6, 0); add_int_items(G.menus[1], rates, 5, 1);
    double initialScales[] = {0.25, 0.5, 0.75, 1, 1.25, 1.5, 2};
    G.scaleCount = 7; for (int i = 0; i < 7; ++i) G.scales[i] = initialScales[i];
    int found = 0; for (int i = 0; i < 7; ++i) if (G.scales[i] == G.prefs.scale) found = 1;
    if (!found) G.scales[G.scaleCount++] = G.prefs.scale;
    for (int i = 0; i < G.scaleCount; ++i) { char value[64]; snprintf(value, sizeof value, "%g배", G.scales[i]); menu_item(G.menus[2], value); }
    int initialMaxima[] = {720, 1080, 1440, 1920, 2560, 3840, 4096};
    G.maximumCount = 7; for (int i = 0; i < 7; ++i) G.maxima[i] = initialMaxima[i];
    found = 0; for (int i = 0; i < 7; ++i) if (G.maxima[i] == G.prefs.maximum) found = 1;
    if (!found) G.maxima[G.maximumCount++] = G.prefs.maximum;
    add_int_items(G.menus[3], G.maxima, G.maximumCount, 2);
    add_int_items(G.menus[4], antiAlias, 4, 3); add_int_items(G.menus[5], shadows, 5, 4);
    G.expand = add_button(document, "촬영·360 화면의 3D 표시 영역 확장", 8, 578, 600, C_EXPAND, 1);
    add_label(document, "기본 16:9 바깥에도 3D 장면을 렌더링합니다. 확대·잘라내기·늘이기 방식이 아닙니다.", 610, 32, 11, 1);
    G.visualLabel = add_label(document, "게임의 응답 대기", 648, 42, 12, 1);
    G.metricLabel = add_label(document, "게임의 3D 화면·시야각 측정값 수신 대기", 692, 42, 11, 1);
    add_label(document, "실행 기록", 746, 26, 14, 0);
    IDObj logScroll = id_init_frame(id_get(id_class("NSScrollView"), "alloc"), id_rect(12, 776, 676, 200));
    id_set_bool(logScroll, "setHasVerticalScroller:", 1); id_set_bool(logScroll, "setHasHorizontalScroller:", 0);
    G.logView = id_init_frame(id_get(id_class("NSTextView"), "alloc"), id_rect(0, 0, 650, 200));
    id_set_bool(G.logView, "setEditable:", 0); id_set_bool(G.logView, "setSelectable:", 1);
    id_set_bool(G.logView, "setVerticallyResizable:", 1); id_set_bool(G.logView, "setHorizontallyResizable:", 0);
    id_set(G.logView, "setFont:", id_double(id_class("NSFont"), "userFixedPitchFontOfSize:", 11));
    id_set(logScroll, "setDocumentView:", G.logView); id_set(document, "addSubview:", logScroll);
    add_label(document, "튜토리얼 라이브는 원본 기록을 재생합니다. 앱을 종료하면 소유한 서버 엔진도 중지됩니다.", 988, 42, 11, 1);
    sync_graphics_controls(); update_controls();
    id_void(G.window, "center"); id_set(G.window, "makeKeyAndOrderFront:", 0);
    id_set_bool(G.app, "activateIgnoringOtherApps:", 1);
}

static double metric(IDObj values, const char *key) {
    IDObj number = id_item(values, key);
    if (!id_is(number, "NSNumber")) return 0;
    double value = id_number(number, "doubleValue");
    return __builtin_isfinite(value) && value >= 0 && value <= 32768 ? value : 0;
}

static void received_event(const char *bytes, IDSize length) {
    IDObj event = id_json(id_data(bytes, length));
    if (!id_is(event, "NSDictionary")) return;
    const char *kind = id_utf8(id_item(event, "event"));
    if (strcmp(kind, "log") == 0) { log_line(id_utf8(id_item(event, "message"))); return; }
    if (strcmp(kind, "error") == 0) {
        G.busy = 0; status(id_utf8(id_item(event, "message"))); log_line(id_utf8(id_item(event, "message"))); update_controls(); return;
    }
    if (strcmp(kind, "status") != 0) return;
    IDObj state = id_item(event, "status");
    if (!id_is(state, "NSDictionary")) return;
    id_poll_received(&G.polling, uptime());
    G.running = truth(id_item(state, "running")); G.busy = truth(id_item(state, "starting"));
    G.canStop = truth(id_item(state, "can_stop"));
    if (G.running && truth(id_item(state, "experimental_main_live"))) G.experimentalObserved = 1;
    if (!G.quitting) status(G.running ? "로컬 서버가 실행 중입니다." : G.busy ? "서버를 시작하고 있습니다." : "서버가 중지되어 있습니다.");
    IDObj client = id_item(id_item(state, "presentation"), "client");
    G.ackPresent = id_is(client, "NSDictionary"); G.ackState = 0;
    G.ackBridge = id_json_integer(id_item(client, "bridge_version"), -1) == 1;
    G.ackRevision = id_json_integer(id_item(client, "revision"), -1);
    const char *visual = id_utf8(id_item(client, "status"));
    for (int i = 2; i <= 6; ++i) if (strcmp(visual, ackNames[i]) == 0) G.ackState = i;
    IDObj values = id_item(client, "metrics");
    G.screenW = metric(values, "screen_width"); G.screenH = metric(values, "screen_height");
    G.renderW = metric(values, "render_width"); G.renderH = metric(values, "render_height");
    G.baseFOV = metric(values, "base_vertical_fov"); G.fov = metric(values, "vertical_fov");
    G.cameraAspect = metric(values, "camera_aspect");
    update_controls();
}

static void drain_pipe(int fd, char *pending, IDSize *length, IDSize capacity, int events) {
    if (fd < 0) return;
    for (int batch = 0; batch < 8; ++batch) {
        struct IDPollFD ready = {fd, 1, 0};
        if (poll(&ready, 1, 0) <= 0 || !(ready.revents & (1 | 16))) break;
        char data[8192]; long count = read(fd, data, sizeof data);
        if (count <= 0) break;
        for (long i = 0; i < count; ++i) {
            if (data[i] == '\n') {
                pending[*length] = 0;
                if (events) received_event(pending, *length); else log_line(pending);
                *length = 0;
            } else if (*length + 1 < capacity) pending[(*length)++] = data[i];
            else { *length = 0; log_line("긴 엔진 기록 한 줄을 생략했습니다."); }
        }
    }
}

static void smoke_report(int success) {
    if (!G.smoke || G.smokeFinished) return;
    G.smokeFinished = 1;
    char report[640]; int count = snprintf(report, sizeof report,
        "{\"gui_started\":true,\"window_visible\":%s,\"server_started\":%s,\"server_stopped\":%s,"
        "\"game_client_tested\":false,\"experimental_main_live_requested\":%s,\"experimental_main_live_observed\":%s}\n",
        id_bool(G.window, "isVisible") ? "true" : "false", G.smokeStarted ? "true" : "false", success ? "true" : "false",
        G.liveMode ? "true" : "false", G.experimentalObserved ? "true" : "false");
    if (G.smokeURL && count > 0) atomic_bytes(G.smokeURL, report, (IDSize)count);
    id_set(G.app, "terminate:", G.delegate);
}

static void tick(IDObj self, IDSel command, IDObj timer) {
    (void)self; (void)command; (void)timer;
    void *pool = IDRuntime.poolPush();
    drain_pipe(G.outFD, G.output, &G.outputCount, sizeof G.output, 1);
    drain_pipe(G.errorFD, G.errors, &G.errorCount, sizeof G.errors, 0);
    int alive = G.task && id_bool(G.task, "isRunning");
    double now = uptime();
    if (!alive && !G.engineEnded) {
        G.engineEnded = 1; G.running = G.busy = G.canStop = 0; G.ackPresent = 0;
        if (!G.quitting) status("서버 엔진이 종료되었습니다. 앱을 다시 열어 주세요.");
        update_controls();
    }
    if (G.quitting) {
        if (!alive) { G.terminated = 1; id_set_bool(G.app, "replyToApplicationShouldTerminate:", 1); }
        else if (now - G.quitAt > 10) kill(id_int(G.task, "processIdentifier"), 9);
        else if (now - G.quitAt > 8 && !G.termSent) { G.termSent = 1; id_void(G.task, "terminate"); }
    } else if (alive) {
        if (G.polling.received && !id_poll_fresh(&G.polling, now)) {
            G.ackPresent = 0; status("서버 응답을 기다리고 있습니다."); update_controls();
        }
        if (now - G.lastRequestAt >= 1 && id_poll_begin(&G.polling)) {
            G.lastRequestAt = now; send_control("status");
        }
    }
    if (G.smoke && !G.smokeFinished && !G.quitting) {
        if (G.running && !G.smokeStopping) { G.smokeStarted = G.smokeStopping = 1; begin_stop(); }
        else if (!G.running && !G.busy && !G.canStop && G.smokeStopping) smoke_report(G.smokeStarted);
        else if (!G.running && !G.busy && !G.smokeStarted && alive) begin_start();
        if (now - G.startedAt > 45) smoke_report(0);
    }
    IDRuntime.poolPop(pool);
}

static void start_engine(void) {
    IDObj bundle = id_get(id_class("NSBundle"), "mainBundle");
    IDObj executable = id_get(bundle, "executableURL");
    IDObj resources = id_get(bundle, "resourceURL");
    IDObj arguments[] = {id_string("--engine"), id_string("--json-control"), id_string("--data-dir"), id_get(G.dataURL, "path"),
        id_string("--server-data"), id_get(childURL(resources, "ServerData.zip"), "path")};
    G.task = id_get(id_get(id_class("NSTask"), "alloc"), "init");
    id_set(G.task, "setExecutableURL:", executable);
    id_set(G.task, "setArguments:", id_array(arguments, 6));
    IDObj environment = id_get(id_get(id_get(id_class("NSProcessInfo"), "processInfo"), "environment"), "mutableCopy");
    const char *removed[] = {"PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"};
    for (int i = 0; i < 6; ++i) id_set(environment, "removeObjectForKey:", id_string(removed[i]));
    const char *flags[] = {"PYTHONNOUSERSITE", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE"};
    for (int i = 0; i < 3; ++i) ((void (*)(IDObj, IDSel, IDObj, IDObj))IDRuntime.message)(environment,
        id_sel("setObject:forKey:"), id_string("1"), id_string(flags[i]));
    id_set(G.task, "setEnvironment:", environment); id_void(environment, "release");
    IDObj input = id_get(id_class("NSPipe"), "pipe"), output = id_get(id_class("NSPipe"), "pipe"), errors = id_get(id_class("NSPipe"), "pipe");
    id_set(G.task, "setStandardInput:", input); id_set(G.task, "setStandardOutput:", output); id_set(G.task, "setStandardError:", errors);
    G.writer = id_keep(id_get(input, "fileHandleForWriting")); G.inputFD = id_int(G.writer, "fileDescriptor");
    G.outFD = id_int(id_get(output, "fileHandleForReading"), "fileDescriptor");
    G.errorFD = id_int(id_get(errors, "fileHandleForReading"), "fileDescriptor");
    IDBool launched = ((IDBool (*)(IDObj, IDSel, IDObj *))IDRuntime.message)(G.task, id_sel("launchAndReturnError:"), 0);
    if (!launched) { G.engineEnded = 1; G.busy = 0; status("서버 엔진을 실행하지 못했습니다. 앱 파일을 확인해 주세요."); }
    update_controls();
}

static void did_launch(IDObj self, IDSel command, IDObj notification) {
    (void)self; (void)command; (void)notification;
    if (G.window) return;
    make_window(); start_engine(); G.startedAt = uptime();
    G.timer = id_keep(((IDObj (*)(IDObj, IDSel, double, IDObj, IDSel, IDObj, IDBool))IDRuntime.message)(
        id_class("NSTimer"), id_sel("scheduledTimerWithTimeInterval:target:selector:userInfo:repeats:"),
        0.2, G.delegate, id_sel("timerTick:"), 0, 1));
}

static unsigned long should_terminate(IDObj self, IDSel command, IDObj app) {
    (void)self; (void)command; (void)app;
    if (G.terminated || !G.task || !id_bool(G.task, "isRunning")) return 1;
    if (!G.quitting) {
        G.quitting = 1; G.quitAt = uptime(); G.ackPresent = 0;
        status("서버 엔진을 종료하고 있습니다."); update_controls();
        send_control("quit");
        if (!G.inputClosed) { G.inputClosed = 1; id_void(G.writer, "closeFile"); }
    }
    return 2;
}

static IDBool close_quits(IDObj self, IDSel command, IDObj app) { (void)self; (void)command; (void)app; return 1; }

int idoly_app_main(int argc, char **argv) {
    if (!id_runtime_load()) { const char *error = "Cannot load the macOS user interface.\n"; write(2, error, strlen(error)); return 1; }
    signal(13, (void (*)(int))1); /* Ignore SIGPIPE only in this UI process. */
    setlocale(4, "C"); /* Darwin LC_NUMERIC: protocol numbers always use a dot. */
    void *pool = IDRuntime.poolPush();
    G.outFD = G.errorFD = G.inputFD = -1; G.busy = 1;
    G.defaults = id_get(id_class("NSUserDefaults"), "standardUserDefaults");
    G.mediaMode = truth(id_arg(G.defaults, "objectForKey:", id_string("mediaMode")));
    G.liveMode = truth(id_arg(G.defaults, "objectForKey:", id_string("experimentalMainLive")));
    IDObj downloads = id_arg(G.defaults, "objectForKey:", id_string("downloadMissingResources"));
    G.downloadMode = downloads ? truth(downloads) : 1;
    IDObj directories = ((IDObj (*)(IDObj, IDSel, unsigned long, unsigned long))IDRuntime.message)(
        id_get(id_class("NSFileManager"), "defaultManager"), id_sel("URLsForDirectory:inDomains:"), 14, 1);
    if (id_long(directories, "count") < 1) { IDRuntime.poolPop(pool); return 1; }
    G.dataURL = id_keep(childURL(id_index(directories, "objectAtIndex:", 0), "IdolyPrideLocal"));
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--app-smoke") == 0) G.smoke = 1;
        else if (strcmp(argv[i], "--experimental-main-live") == 0) G.liveMode = 1;
        else if ((strcmp(argv[i], "--data-dir") == 0 || strcmp(argv[i], "--smoke-report") == 0) && i + 1 < argc) {
            int data = strcmp(argv[i], "--data-dir") == 0;
            IDObj url = id_arg(id_class("NSURL"), "fileURLWithPath:", id_string(argv[++i]));
            if (data) G.dataURL = id_keep(url); else G.smokeURL = id_keep(url);
        }
    }
    G.prefsURL = id_keep(childURL(G.dataURL, "client-presentation.json")); load_preferences();
    G.app = id_get(id_class("NSApplication"), "sharedApplication"); id_set_long(G.app, "setActivationPolicy:", 0);
    IDObj delegateClass = IDRuntime.allocateClass(id_class("NSObject"), "IdolyServerDelegate", 0);
    IDRuntime.addMethod(delegateClass, id_sel("applicationDidFinishLaunching:"), (void *)did_launch, "v@:@");
    IDRuntime.addMethod(delegateClass, id_sel("applicationShouldTerminate:"), (void *)should_terminate, "Q@:@");
    IDRuntime.addMethod(delegateClass, id_sel("applicationShouldTerminateAfterLastWindowClosed:"), (void *)close_quits, "B@:@");
    IDRuntime.addMethod(delegateClass, id_sel("controlAction:"), (void *)control_action, "v@:@");
    IDRuntime.addMethod(delegateClass, id_sel("timerTick:"), (void *)tick, "v@:@");
    IDRuntime.registerClass(delegateClass);
    G.delegate = id_get(id_get(delegateClass, "alloc"), "init"); id_set(G.app, "setDelegate:", G.delegate);
    IDObj menu = id_get(id_get(id_class("NSMenu"), "alloc"), "init");
    IDObj item = id_get(id_get(id_class("NSMenuItem"), "alloc"), "init");
    IDObj appMenu = id_get(id_get(id_class("NSMenu"), "alloc"), "init");
    ((IDObj (*)(IDObj, IDSel, IDObj, IDSel, IDObj))IDRuntime.message)(appMenu, id_sel("addItemWithTitle:action:keyEquivalent:"),
        id_string("아이프라 로컬 서버 종료"), id_sel("terminate:"), id_string("q"));
    id_set(item, "setSubmenu:", appMenu); id_set(menu, "addItem:", item); id_set(G.app, "setMainMenu:", menu);
    id_void(G.app, "finishLaunching"); id_void(G.app, "run");
    if (G.timer) id_void(G.timer, "invalidate");
    IDRuntime.poolPop(pool);
    return 0;
}
