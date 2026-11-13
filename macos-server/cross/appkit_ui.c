#include "darwin_objc.h"
#include "presentation_contract.h"
#include "playcover_launch.h"
#include "shutdown_policy.h"
#include "playback_contract.h"
#include "library_contract.h"

extern int fcntl(int, int, ...);

/* The launcher owns Python embedding; this file owns only the Cocoa window and
   its existing local JSON-control child. No client download/install code. */

enum { C_CUSTOM = 1, C_QUALITY, C_FPS, C_SCALE, C_MAXIMUM, C_AA, C_SHADOW, C_EXPAND,
       C_MEDIA = 100, C_LIVE, C_DOWNLOAD, C_WAIT_ROTATION,
       C_HIDE_VIDEO = 110, C_MV_SORT, C_OUTFIT_SORT, C_LANGUAGE,
       C_START = 200, C_STOP, C_OPEN, C_FOLDER,
       C_RESOURCE_PLATFORM = 300, C_RESOURCE_PREVIEW, C_RESOURCE_DOWNLOAD,
       C_RESOURCE_CANCEL, C_RESOURCE_EXPORT, C_RESOURCE_IMPORT,
       C_RESOURCE_LOCATION, C_RESOURCE_REVEAL, C_RESOURCE_PARALLELISM, C_RESOURCE_CHOOSE, C_RESOURCE_DEFAULT };

/* Official Foundation SearchPathDirectory values (swift-foundation6.0.3):
   cachesDirectory13, applicationSupportDirectory14, downloadsDirectory15. */
enum { ID_SEARCH_DOWNLOADS = 15, ID_USER_DOMAIN = 1 };

static struct {
    IDObj app, delegate, window, timer, task, writer, defaults, dataURL, prefsURL, playbackURL, smokeURL;
    IDObj mediaURL, languageURL, libraryLabel, hideVideo, mvSort, outfitSort, language;
    IDObj resourcePlatform, resourceParallelism, resourceLabel, resourcePreview, resourceDownload, resourceCancel, resourceExport, resourceImport;
    IDObj resourceSnapshot;
    IDObj downloadsResourcesURL, customResourcesURL, resourcesInDownloads, resourceLocationLabel, revealResources;
    IDObj chooseResources, defaultResources, resourceLocationHelp;
    IDObj serverLabel, launchLabel, visualLabel, metricLabel, logView, start, stop, openGame;
    IDObj media, live, download, waitOrientation, playbackLabel, custom, expand, menus[6];
    IDPrefs prefs;
    IDPlaybackPrefs playback;
    IDLibraryPrefs library;
    int invalidPrefs, saveFailed, running, busy, canStop, mediaMode, liveMode, downloadMode;
    int invalidPlayback, playbackSaveFailed;
    int invalidLibrary, librarySaveFailed, libraryChanged;
    int resourcePlatformIndex, resourceParallelismValue, resourceJobActive, resourcePending;
    int resourcesDownloads, invalidResourceLocation, resourceLocationChanged;
    char resourceJobID[65];
    int outFD, errorFD, inputFD, inputClosed, engineEnded, quitting;
    int ackBridge, ackPresent, ackState, experimentalObserved;
    long long ackRevision;
    double screenW, screenH, renderW, renderH, baseFOV, fov, cameraAspect;
    double startedAt, lastRequestAt;
    double scales[16]; int scaleCount, maxima[16], maximumCount;
    IDPolling polling;
    IDShutdown shutdown;
    int smoke, smokeStarted, smokeStopping, smokeFinished;
    char output[131073], errors[32769], logs[60001];
    IDSize outputCount, errorCount, logCount;
} G;

static const int qualities[] = {0, 10, 20, 30, 40, 100};
static const int rates[] = {0, 30, 60, 90, 120};
static const int antiAlias[] = {-1, 0, 1, 2};
static const int shadows[] = {0, 512, 1024, 2048, 4096};
static const int resourceParallelisms[] = {1, 2, 4, 8};
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

static IDObj external_resource_root(void) {
    return G.invalidResourceLocation ? 0 : G.customResourcesURL ? G.customResourcesURL : G.downloadsResourcesURL;
}
static IDObj selected_resource_root(void) { return G.resourcesDownloads ? external_resource_root() : G.dataURL; }
static int resource_location_can_change(void) {
    return id_resource_location_change_allowed(G.running,G.busy,G.canStop,G.resourceJobActive,G.resourcePending,G.quitting);
}

static int create_resource_directory(IDObj url) {
    return url && ((IDBool (*)(IDObj,IDSel,IDObj,IDBool,IDObj,IDObj *))IDRuntime.message)(
        id_get(id_class("NSFileManager"),"defaultManager"),id_sel("createDirectoryAtURL:withIntermediateDirectories:attributes:error:"),
        url,1,0,0);
}

static int valid_resource_path(IDObj path) {
    if (!id_is(path,"NSString")) return 0;
    IDSize bytes=((IDSize (*)(IDObj,IDSel,unsigned long))IDRuntime.message)(path,id_sel("lengthOfBytesUsingEncoding:"),4);
    return id_resource_location_path_valid(id_utf8(path),bytes);
}

static IDObj validated_resource_directory(IDObj candidate, int create) {
    if (!candidate || !id_bool(candidate,"isFileURL")) return 0;
    IDObj root=id_get(id_get(candidate,"URLByStandardizingPath"),"URLByResolvingSymlinksInPath");
    IDObj path=id_get(root,"path");
    const char *bytes=id_utf8(path);
    if (!valid_resource_path(path)) return 0;
    if (create && !create_resource_directory(root)) return 0;
    IDObj manager=id_get(id_class("NSFileManager"),"defaultManager");
    IDBool directory=0;
    if (!((IDBool (*)(IDObj,IDSel,IDObj,IDBool *))IDRuntime.message)(manager,
            id_sel("fileExistsAtPath:isDirectory:"),path,&directory) || !directory
            || !id_bool_arg(manager,"isWritableFileAtPath:",path)) return 0;
    char command[513];
    return id_server_start_command(0,0,0,bytes,command,sizeof command) ? root : 0;
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

static int write_playback_preferences(const IDPlaybackPrefs *value) {
    char bytes[256]; int length = id_playback_encode(value, bytes, sizeof bytes);
    return length > 0 && create_data_directory() && atomic_bytes(G.playbackURL, bytes, (IDSize)length);
}

static void load_playback_preferences(void) {
    G.playback = id_playback_defaults();
    IDObj manager = id_get(id_class("NSFileManager"), "defaultManager");
    IDObj path = id_get(G.playbackURL, "path");
    if (!id_bool_arg(manager, "fileExistsAtPath:", path)) {
        G.playbackSaveFailed = !write_playback_preferences(&G.playback);
        return;
    }
    IDObj attributes = ((IDObj (*)(IDObj, IDSel, IDObj, IDObj *))IDRuntime.message)(manager,
        id_sel("attributesOfItemAtPath:error:"), path, 0);
    if (strcmp(id_utf8(id_item(attributes, "NSFileType")), "NSFileTypeRegular") != 0) { G.invalidPlayback = 1; return; }
    int fd = open(id_utf8(path), 0);
    if (fd < 0) { G.invalidPlayback = 1; return; }
    char bytes[8193]; IDSize length = 0;
    while (length < sizeof bytes) {
        long count = read(fd, bytes + length, sizeof bytes - length);
        if (count < 0) { G.invalidPlayback = 1; break; }
        if (!count) break;
        length += (IDSize)count;
    }
    close(fd);
    if (!G.invalidPlayback && !id_playback_decode(bytes, length, &G.playback)) G.invalidPlayback = 1;
}

static int save_playback_preferences(int waitForOrientation) {
    double milliseconds = id_number(id_get(id_class("NSDate"), "date"), "timeIntervalSince1970") * 1000.0;
    if (!__builtin_isfinite(milliseconds) || milliseconds >= 9223372036854775807.0) return 0;
    IDPlaybackPrefs changed = G.playback, next;
    changed.waitForOrientation = waitForOrientation;
    if (!id_playback_next(&changed, milliseconds > 0 ? (long long)milliseconds : 0, &next)
        || !write_playback_preferences(&next)) return 0;
    G.playback = next; G.invalidPlayback = G.playbackSaveFailed = 0;
    return 1;
}

/* Read only these two public preference files. No directory scan or account
   database access is performed by the UI. */
static void load_library_file(IDObj url, int languageOnly) {
    IDObj manager = id_get(id_class("NSFileManager"), "defaultManager");
    IDObj path = id_get(url, "path");
    IDObj attributes = ((IDObj (*)(IDObj, IDSel, IDObj, IDObj *))IDRuntime.message)(manager,
        id_sel("attributesOfItemAtPath:error:"), path, 0);
    if (!attributes) return;
    int invalid = languageOnly ? 2 : 1;
    if (strcmp(id_utf8(id_item(attributes,"NSFileType")),"NSFileTypeRegular")) { G.invalidLibrary |= invalid; return; }
    int fd = open(id_utf8(path), 0x104); /* Darwin O_NOFOLLOW | O_NONBLOCK. */
    if (fd < 0) { G.invalidLibrary |= invalid; return; }
    char bytes[8193]; IDSize length=0; int failed=0;
    while (length < sizeof bytes) {
        long count=read(fd,bytes+length,sizeof bytes-length);
        if (count < 0) { failed=1; break; }
        if (!count) break;
        length+=(IDSize)count;
    }
    close(fd);
    IDLibraryPrefs decoded;
    if (failed || !id_library_decode(bytes,length,&decoded,languageOnly)) { G.invalidLibrary |= invalid; return; }
    if (languageOnly) G.library.language=decoded.language;
    else { int language=G.library.language; G.library=decoded; G.library.language=language; }
}

static int save_library_preferences(IDLibraryPrefs changed, int languageOnly) {
    IDLibraryPrefs next=changed;
    if (!languageOnly) {
        double now=id_number(id_get(id_class("NSDate"),"date"),"timeIntervalSince1970")*1000.0;
        if (!__builtin_isfinite(now) || now < 0 || now >= 9223372036854775807.0
            || !id_library_next(&changed,(long long)now,&next)) return 0;
    }
    IDObj url=languageOnly ? G.languageURL : G.mediaURL;
    IDObj attributes=((IDObj (*)(IDObj,IDSel,IDObj,IDObj *))IDRuntime.message)(
        id_get(id_class("NSFileManager"),"defaultManager"),id_sel("attributesOfItemAtPath:error:"),id_get(url,"path"),0);
    if (!strcmp(id_utf8(id_item(attributes,"NSFileType")),"NSFileTypeSymbolicLink")) return 0;
    char bytes[512]; int length=id_library_encode(&next,bytes,sizeof bytes,languageOnly);
    if (!length || !create_data_directory() || !atomic_bytes(url,bytes,(IDSize)length)) return 0;
    G.library=next; G.invalidLibrary &= ~(languageOnly ? 2 : 1);
    G.librarySaveFailed=0; G.libraryChanged=1; return 1;
}

static void sync_library_controls(void) {
    id_set_long(G.hideVideo,"setState:",G.library.hideVideo);
    id_set_long(G.mvSort,"selectItemAtIndex:",G.library.mvSort);
    id_set_long(G.outfitSort,"selectItemAtIndex:",G.library.outfitSort);
    id_set_long(G.language,"selectItemAtIndex:",G.library.language);
}

static void resource_status(IDObj resources);

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
    id_set_bool(G.resourcesInDownloads,"setEnabled:",(IDBool)resource_location_can_change());
    id_set_bool(G.chooseResources,"setEnabled:",(IDBool)resource_location_can_change());
    id_set_bool(G.defaultResources,"setEnabled:",(IDBool)resource_location_can_change());
    id_set_long(G.resourcesInDownloads,"setState:",G.resourcesDownloads);
    id_set_bool(G.revealResources,"setEnabled:",!G.quitting);
    IDObj resourceRoot=selected_resource_root();
    if (resourceRoot) id_set(G.resourceLocationLabel,"setStringValue:",id_arg(
        id_string(G.resourcesDownloads ? "직접 보관 위치: " : "앱 전용 보관 위치: "),"stringByAppendingString:",id_get(resourceRoot,"path")));
    else text(G.resourceLocationLabel,"저장된 보관 경로를 확인해 주세요. 폴더 선택 또는 기본 위치 복원으로 다시 지정할 수 있습니다.");
    text(G.resourceLocationHelp,G.resourceLocationChanged
        ? "보관 위치가 저장되었습니다. 다음 서버 시작부터 적용됩니다. 기존 파일은 이전 폴더에 유지되며 자동으로 옮기거나 삭제하지 않습니다."
        : "서버 중지 후 폴더를 변경할 수 있습니다. 폴더 선택·기본 위치 복원은 직접 보관을 켜며 체크 해제 시 앱 전용 보관을 사용합니다.");
    id_set_bool(G.waitOrientation, "setEnabled:", !G.quitting);
    id_set_long(G.waitOrientation, "setState:", G.playback.waitForOrientation);
    text(G.playbackLabel, G.playbackSaveFailed ? "회전 대기 설정을 저장하지 못했습니다. 이전 값을 유지합니다."
        : G.invalidPlayback ? "회전 대기 설정을 읽지 못해 기본값 켜짐을 표시합니다. 바꾸면 새로 저장합니다."
        : G.playback.revision > 0 ? "MV 회전 대기 설정이 저장되었습니다."
        : "기본값 켜짐 · 그래픽 설정과 별도로 저장됩니다.");
    id_set(G.playbackLabel, "setTextColor:", color(G.invalidPlayback || G.playbackSaveFailed ? "systemOrangeColor" : "secondaryLabelColor"));
    id_set_bool(G.hideVideo,"setEnabled:",!G.quitting);
    id_set_bool(G.mvSort,"setEnabled:",!G.quitting);
    id_set_bool(G.outfitSort,"setEnabled:",!G.quitting);
    id_set_bool(G.language,"setEnabled:",!G.quitting);
    text(G.libraryLabel,G.librarySaveFailed ? "목록·언어 설정을 저장하지 못했습니다. 이전 값을 유지합니다."
        : G.invalidLibrary ? "목록·언어 설정 일부를 읽지 못해 기본값을 표시합니다. 변경하면 해당 파일을 새로 저장합니다."
        : G.libraryChanged ? "저장되었습니다. 서버를 재시작하고 게임 타이틀에서 다시 로그인해 주세요."
        : "서버 시작 시 적용합니다. 변경 후 서버를 재시작하고 게임 타이틀에서 다시 로그인해 주세요.");
    id_set(G.libraryLabel,"setTextColor:",color(G.librarySaveFailed || G.invalidLibrary ? "systemOrangeColor" : "secondaryLabelColor"));
    int resources=G.running && !G.quitting && !G.engineEnded && !G.inputClosed && !G.resourcePending;
    id_set_bool(G.resourcePlatform,"setEnabled:",!G.quitting && !G.resourceJobActive && !G.resourcePending);
    id_set_bool(G.resourceParallelism,"setEnabled:",!G.quitting && !G.resourceJobActive && !G.resourcePending);
    id_set_bool(G.resourcePreview,"setEnabled:",resources && !G.resourceJobActive);
    id_set_bool(G.resourceDownload,"setEnabled:",resources && !G.resourceJobActive);
    id_set_bool(G.resourceExport,"setEnabled:",resources && !G.resourceJobActive);
    id_set_bool(G.resourceImport,"setEnabled:",resources && !G.resourceJobActive);
    id_set_bool(G.resourceCancel,"setEnabled:",resources && G.resourceJobActive && id_resource_job_valid(G.resourceJobID));
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

static void close_input(void) {
    if (!G.inputClosed && G.writer) {
        G.inputClosed = 1;
        id_void(G.writer, "closeFile");
    }
}

static int send_control(const char *action) {
    if (!G.task || !id_bool(G.task, "isRunning") || G.inputClosed) return 0;
    char command[513];
    int size;
    if (strcmp(action, "start") == 0) {
        IDObj root=external_resource_root();
        if (G.resourcesDownloads && !root) return 0;
        size=id_server_start_command(G.liveMode,G.mediaMode,G.downloadMode,
            G.resourcesDownloads ? id_utf8(id_get(root,"path")) : 0,command,sizeof command);
    }
    else size = snprintf(command, sizeof command, "{\"action\":\"%s\"}\n", action);
    if (size <= 0 || (IDSize)size >= sizeof command) return 0;
    int sent = id_control_send(G.inputFD, command, (IDSize)size, write);
    if (sent < 0) close_input(); /* Never append a second JSON command to a partial line. */
    return sent == 1;
}

static void begin_start(void) {
    if (G.running || G.busy || G.canStop || G.quitting) return;
    if (G.resourcesDownloads) {
        IDObj root=validated_resource_directory(external_resource_root(),1);
        if (!root) { status("리소스 보관 폴더에 접근하지 못했습니다. 쓰기 권한과 경로 길이를 확인하거나 다른 폴더를 선택해 주세요."); return; }
        if (G.customResourcesURL) {
            IDObj saved=G.customResourcesURL; G.customResourcesURL=id_keep(root); id_void(saved,"release");
        } else {
            IDObj saved=G.downloadsResourcesURL; G.downloadsResourcesURL=id_keep(root); if (saved) id_void(saved,"release");
        }
    }
    G.busy = 1; status("서버를 시작하고 있습니다."); update_controls();
    if (!send_control("start")) { G.busy = 0; status("서버 시작 요청을 전달하지 못했습니다. 보관 위치와 앱 상태를 확인해 주세요."); update_controls(); }
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

static void resource_message(const char *message, int failed) {
    text(G.resourceLabel,message);
    id_set(G.resourceLabel,"setTextColor:",color(failed ? "systemOrangeColor" : "secondaryLabelColor"));
}

static void resource_request(const char *action, const char *argument) {
    if (!G.running || G.quitting || G.engineEnded || G.inputClosed || G.resourcePending
        || !G.task || !id_bool(G.task,"isRunning")) return;
    char bytes[513]; const char *platform=G.resourcePlatformIndex ? "android" : "ios";
    int count=!strcmp(action,"resources_download")
        ? id_resource_download_command(platform,G.resourceParallelismValue,bytes,sizeof bytes)
        : id_resource_command(action,platform,argument,bytes,sizeof bytes);
    if (!count) { resource_message("요청 경로가 너무 길거나 ZIP 형식이 아닙니다. Downloads 아래의 짧은 이름을 선택해 주세요.",1); return; }
    int sent=id_control_send(G.inputFD,bytes,(IDSize)count,write);
    if (sent < 0) close_input();
    if (sent != 1) { resource_message("리소스 요청을 전달하지 못했습니다. 잠시 뒤 다시 시도해 주세요.",1); return; }
    G.resourcePending=1; resource_message("리소스 작업을 준비하고 있습니다.",0); update_controls();
}

static void resource_archive_panel(int importing) {
    if (!G.running || G.resourceJobActive || G.resourcePending || G.quitting) return;
    IDObj panel=id_get(id_class(importing ? "NSOpenPanel" : "NSSavePanel"),importing ? "openPanel" : "savePanel");
    IDObj zip=id_string("zip"); id_set(panel,"setAllowedFileTypes:",id_array(&zip,1));
    id_set_bool(panel,"setAllowsOtherFileTypes:",0);
    if (importing) {
        IDObj directories=((IDObj (*)(IDObj,IDSel,unsigned long,unsigned long))IDRuntime.message)(
            id_get(id_class("NSFileManager"),"defaultManager"),id_sel("URLsForDirectory:inDomains:"),ID_SEARCH_DOWNLOADS,ID_USER_DOMAIN);
        if (id_long(directories,"count") > 0) id_set(panel,"setDirectoryURL:",id_index(directories,"objectAtIndex:",0));
    } else {
        IDObj exports=G.downloadsResourcesURL ? childURL(G.downloadsResourcesURL,"exports") : 0;
        if (!create_resource_directory(exports)) {
            resource_message("Downloads/IdolyPride/exports 폴더를 준비하지 못했습니다. macOS의 폴더 접근 권한을 확인해 주세요.",1); return;
        }
        id_set(panel,"setDirectoryURL:",exports);
    }
    if (importing) {
        id_set_bool(panel,"setAllowsMultipleSelection:",0); id_set_bool(panel,"setCanChooseDirectories:",0);
        id_set_bool(panel,"setCanChooseFiles:",1);
    } else {
        id_set_bool(panel,"setCanCreateDirectories:",1);
        id_set(panel,"setNameFieldStringValue:",id_string(G.resourcePlatformIndex
            ? "IdolyPride-resources-android.zip" : "IdolyPride-resources-ios.zip"));
    }
    if (id_long(panel,"runModal") != 1) return; /* NSModalResponseOK. */
    IDObj selected=id_get(panel,"URL");
    if (!selected || !id_bool(selected,"isFileURL")) return;
    resource_request(importing ? "resources_import" : "resources_export",id_utf8(id_get(selected,"path")));
}

static void select_resource_directory(int restoreDefault) {
    if (!resource_location_can_change()) return;
    IDObj chosen=G.downloadsResourcesURL;
    if (!restoreDefault) {
        IDObj panel=id_get(id_class("NSOpenPanel"),"openPanel");
        id_set(panel,"setTitle:",id_string("리소스 보관 폴더 선택"));
        id_set(panel,"setPrompt:",id_string("이 폴더 사용"));
        id_set_bool(panel,"setCanChooseDirectories:",1); id_set_bool(panel,"setCanChooseFiles:",0);
        id_set_bool(panel,"setCanCreateDirectories:",1); id_set_bool(panel,"setAllowsMultipleSelection:",0);
        if (external_resource_root()) id_set(panel,"setDirectoryURL:",external_resource_root());
        if (id_long(panel,"runModal")!=1) return;
        chosen=id_get(panel,"URL");
    }
    // A nested panel run loop may have received a new engine/job state.
    if (!resource_location_can_change()) return;
    IDObj root=validated_resource_directory(chosen,1);
    if (!root) { resource_message("쓰기 가능한 리소스 폴더를 선택해 주세요. 접근 권한과 경로 길이를 확인해 주세요. 이전 위치는 유지됩니다.",1); return; }
    IDObj previous=G.customResourcesURL;
    if (restoreDefault) {
        id_set(G.defaults,"removeObjectForKey:",id_string("resourceDirectoryPath"));
        G.customResourcesURL=0;
    } else {
        ((void (*)(IDObj,IDSel,IDObj,IDObj))IDRuntime.message)(G.defaults,id_sel("setObject:forKey:"),
            id_get(root,"path"),id_string("resourceDirectoryPath"));
        G.customResourcesURL=id_keep(root);
    }
    if (previous) id_void(previous,"release");
    G.resourcesDownloads=1; G.invalidResourceLocation=0; G.resourceLocationChanged=1;
    ((void (*)(IDObj,IDSel,IDBool,IDObj))IDRuntime.message)(G.defaults,id_sel("setBool:forKey:"),1,id_string("resourcesInDownloads"));
    update_controls();
}

static void control_action(IDObj self, IDSel command, IDObj sender) {
    (void)self; (void)command;
    void *pool = IDRuntime.poolPush();
    long tag = id_long(sender, "tag");
    if (tag == C_START) begin_start();
    else if (tag == C_STOP) begin_stop();
    else if (tag == C_OPEN) open_game();
    else if (tag == C_RESOURCE_LOCATION) {
        if (resource_location_can_change()) {
            G.resourcesDownloads=id_long(sender,"state") == 1;
            ((void (*)(IDObj,IDSel,IDBool,IDObj))IDRuntime.message)(G.defaults,id_sel("setBool:forKey:"),
                (IDBool)G.resourcesDownloads,id_string("resourcesInDownloads"));
        }
        update_controls();
    } else if (tag == C_RESOURCE_CHOOSE || tag == C_RESOURCE_DEFAULT) {
        select_resource_directory(tag == C_RESOURCE_DEFAULT);
    } else if (tag == C_RESOURCE_REVEAL) {
        IDObj root=selected_resource_root();
        if (!create_resource_directory(root)) resource_message("리소스 폴더를 열지 못했습니다. macOS의 폴더 접근 권한을 확인해 주세요.",1);
        else if (!id_bool_arg(id_get(id_class("NSWorkspace"),"sharedWorkspace"),"openURL:",root))
            resource_message("Finder에서 리소스 폴더를 열지 못했습니다.",1);
    }
    else if (tag == C_RESOURCE_PARALLELISM) {
        long index=id_long(sender,"indexOfSelectedItem");
        if (!G.quitting && !G.resourceJobActive && !G.resourcePending && index >= 0 && index < 4) {
            G.resourceParallelismValue=resourceParallelisms[index];
            ((void (*)(IDObj,IDSel,long,IDObj))IDRuntime.message)(G.defaults,id_sel("setInteger:forKey:"),
                (long)G.resourceParallelismValue,id_string("resourceDownloadParallelism"));
        }
        id_set_long(G.resourceParallelism,"selectItemAtIndex:",selected_int(resourceParallelisms,4,G.resourceParallelismValue));
        update_controls();
    }
    else if (tag >= C_RESOURCE_PLATFORM && tag <= C_RESOURCE_IMPORT) {
        if (tag == C_RESOURCE_PLATFORM) {
            long index=id_long(sender,"indexOfSelectedItem");
            if (!G.resourceJobActive && !G.resourcePending && index >= 0 && index < 2) G.resourcePlatformIndex=(int)index;
            resource_status(G.resourceSnapshot); update_controls();
        } else if (tag == C_RESOURCE_CANCEL) resource_request("resources_cancel",G.resourceJobID);
        else if (!G.resourceJobActive && tag == C_RESOURCE_PREVIEW) resource_request("resources_preview",0);
        else if (!G.resourceJobActive && tag == C_RESOURCE_DOWNLOAD) resource_request("resources_download",0);
        else if (tag == C_RESOURCE_EXPORT || tag == C_RESOURCE_IMPORT) resource_archive_panel(tag == C_RESOURCE_IMPORT);
    }
    else if (tag == C_FOLDER) {
        create_data_directory();
        id_bool_arg(id_get(id_class("NSWorkspace"), "sharedWorkspace"), "openURL:", G.dataURL);
    } else if (tag == C_WAIT_ROTATION) {
        if (!G.quitting && !save_playback_preferences(id_long(sender, "state") == 1)) G.playbackSaveFailed = 1;
        update_controls();
    } else if (tag >= C_HIDE_VIDEO && tag <= C_LANGUAGE) {
        if (!G.quitting) {
            IDLibraryPrefs changed=G.library;
            long index=tag == C_HIDE_VIDEO ? -1 : id_long(sender,"indexOfSelectedItem");
            if (tag == C_HIDE_VIDEO) changed.hideVideo=id_long(sender,"state") == 1;
            if (tag == C_MV_SORT && index >= 0 && index < 4) changed.mvSort=(int)index;
            if (tag == C_OUTFIT_SORT && index >= 0 && index < 5) changed.outfitSort=(int)index;
            if (tag == C_LANGUAGE && index >= 0 && index < 3) changed.language=(int)index;
            if (!save_library_preferences(changed,tag == C_LANGUAGE)) G.librarySaveFailed=1;
        }
        sync_library_controls(); update_controls();
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
    IDObj document = id_init_frame(id_get(viewClass, "alloc"), id_rect(0, 0, 700, 2066));
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
    G.waitOrientation = add_button(document, "MV 진입·종료 시 화면 회전 대기", 8, 256, 620, C_WAIT_ROTATION, 1);
    add_label(document, "켜면 화면 회전이 끝날 때까지 MV 진입·종료를 기다립니다. 끄면 회전을 기다리지 않습니다.", 288, 36, 11, 1);
    G.playbackLabel = add_label(document, "회전 대기 설정을 준비하고 있습니다.", 328, 36, 11, 1);
    add_label(document, "MV·의상 목록·게임 데이터 언어", 384, 30, 17, 0);
    G.hideVideo=add_button(document,"3D 촬영이 없는 영상 MV 숨기기",8,420,620,C_HIDE_VIDEO,1);
    G.mvSort=add_menu(document,"라이브 촬영 MV 정렬",458,C_MV_SORT);
    const char *mvNames[]={"최신순 (기본)","오래된 순","이름순","ID순"};
    for (int i=0;i<4;++i) menu_item(G.mvSort,mvNames[i]);
    G.outfitSort=add_menu(document,"의상 정렬",492,C_OUTFIT_SORT);
    const char *outfitNames[]={"원본 획득순 (기본)","출시 최신순","출시 오래된 순","이름순","ID순"};
    for (int i=0;i<5;++i) menu_item(G.outfitSort,outfitNames[i]);
    G.language=add_menu(document,"게임 데이터 언어",526,C_LANGUAGE);
    const char *languageNames[]={"日本語 (원본)","한국어","English"};
    for (int i=0;i<3;++i) menu_item(G.language,languageNames[i]);
    add_label(document,"스토리·게임 데이터에 준비된 번역을 적용합니다. UI 언어를 바꾸려면 같은 언어의 클라이언트로 업데이트해 주세요. 없는 번역은 원문을 유지합니다.",562,38,11,1);
    G.libraryLabel=add_label(document,"목록·언어 설정을 준비하고 있습니다.",606,50,11,1);
    add_label(document, "그래픽·촬영 화면", 684, 30, 17, 0);
    add_label(document, "그래픽 지원 IPA가 필요합니다. 서버 실행 중에도 바꿀 수 있으며 저장 후 실제 게임의 적용 확인을 기다립니다.", 718, 38, 11, 1);
    G.custom = add_button(document, "사용자 그래픽 설정 사용", 8, 760, 450, C_CUSTOM, 1);
    const char *labels[] = {"그래픽 품질", "목표 프레임 수", "3D 렌더 배율", "렌더 버퍼 최대 크기", "가장자리 다듬기", "캐릭터 그림자 해상도"};
    long tags[] = {C_QUALITY, C_FPS, C_SCALE, C_MAXIMUM, C_AA, C_SHADOW};
    for (int i = 0; i < 6; ++i) G.menus[i] = add_menu(document, labels[i], 796 + i * 34, tags[i]);
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
    G.expand = add_button(document, "촬영·360 화면의 3D 표시 영역 확장", 8, 1006, 600, C_EXPAND, 1);
    add_label(document, "기본 16:9 바깥에도 3D 장면을 렌더링합니다. 확대·잘라내기·늘이기 방식이 아닙니다.", 1038, 32, 11, 1);
    G.visualLabel = add_label(document, "게임의 응답 대기", 1076, 42, 12, 1);
    G.metricLabel = add_label(document, "게임의 3D 화면·시야각 측정값 수신 대기", 1120, 42, 11, 1);
    add_label(document,"게임 리소스 보관",1174,28,17,0);
    G.resourcesInDownloads=add_button(document,"선택한 폴더에 리소스 직접 보관",8,1208,500,C_RESOURCE_LOCATION,1);
    G.revealResources=add_button(document,"리소스 폴더 열기",516,1208,170,C_RESOURCE_REVEAL,0);
    G.resourceLocationLabel=add_label(document,"보관 위치를 확인하고 있습니다.",1240,44,11,1);
    G.chooseResources=add_button(document,"보관 폴더 변경…",12,1290,220,C_RESOURCE_CHOOSE,0);
    G.defaultResources=add_button(document,"Downloads 기본 위치 복원",242,1290,300,C_RESOURCE_DEFAULT,0);
    G.resourceLocationHelp=add_label(document,"보관 위치 설정을 준비하고 있습니다.",1324,54,11,1);
    G.resourcePlatform=add_menu(document,"보관할 리소스",1388,C_RESOURCE_PLATFORM);
    menu_item(G.resourcePlatform,"iOS · Mac PlayCover (기본)"); menu_item(G.resourcePlatform,"Android");
    G.resourceParallelism=add_menu(document,"동시 다운로드 수",1422,C_RESOURCE_PARALLELISM);
    const char *parallelismNames[]={"1개","2개","4개 (기본)","8개"};
    for (int i=0;i<4;++i) menu_item(G.resourceParallelism,parallelismNames[i]);
    id_set_long(G.resourceParallelism,"selectItemAtIndex:",selected_int(resourceParallelisms,4,G.resourceParallelismValue));
    G.resourcePreview=add_button(document,"목록·예상 용량 확인",12,1460,180,C_RESOURCE_PREVIEW,0);
    G.resourceDownload=add_button(document,"전체 리소스 받기",202,1460,180,C_RESOURCE_DOWNLOAD,0);
    G.resourceCancel=add_button(document,"작업 취소",392,1460,120,C_RESOURCE_CANCEL,0);
    G.resourceExport=add_button(document,"보관 ZIP 내보내기",12,1498,180,C_RESOURCE_EXPORT,0);
    G.resourceImport=add_button(document,"보관 ZIP 가져오기",202,1498,180,C_RESOURCE_IMPORT,0);
    G.resourceLabel=add_label(document,"서버를 시작하면 보관 목록과 진행 상태를 확인할 수 있습니다.",1538,128,11,1);
    add_label(document,"선택한 보관 폴더 아래에 octo-cache(Android), octo-cache-ios(iOS)를 만듭니다. ZIP은 Downloads/IdolyPride/exports에 선택적으로 백업합니다. 계정·설정은 앱 전용 폴더에 유지됩니다.",1670,54,11,1);
    add_label(document, "실행 기록", 1752, 26, 14, 0);
    IDObj logScroll = id_init_frame(id_get(id_class("NSScrollView"), "alloc"), id_rect(12, 1782, 676, 200));
    id_set_bool(logScroll, "setHasVerticalScroller:", 1); id_set_bool(logScroll, "setHasHorizontalScroller:", 0);
    G.logView = id_init_frame(id_get(id_class("NSTextView"), "alloc"), id_rect(0, 0, 650, 200));
    id_set_bool(G.logView, "setEditable:", 0); id_set_bool(G.logView, "setSelectable:", 1);
    id_set_bool(G.logView, "setVerticallyResizable:", 1); id_set_bool(G.logView, "setHorizontallyResizable:", 0);
    id_set(G.logView, "setFont:", id_double(id_class("NSFont"), "userFixedPitchFontOfSize:", 11));
    id_set(logScroll, "setDocumentView:", G.logView); id_set(document, "addSubview:", logScroll);
    add_label(document, "튜토리얼 라이브는 원본 기록을 재생합니다. 앱을 종료하면 소유한 서버 엔진도 중지됩니다.", 1994, 42, 11, 1);
    sync_graphics_controls(); sync_library_controls(); update_controls();
    id_void(G.window, "center"); id_set(G.window, "makeKeyAndOrderFront:", 0);
    id_set_bool(G.app, "activateIgnoringOtherApps:", 1);
}

static double metric(IDObj values, const char *key) {
    IDObj number = id_item(values, key);
    if (!id_is(number, "NSNumber")) return 0;
    double value = id_number(number, "doubleValue");
    return __builtin_isfinite(value) && value >= 0 && value <= 32768 ? value : 0;
}

static double resource_number(IDObj values, const char *key) {
    IDObj number=id_item(values,key);
    if (!id_is(number,"NSNumber")) return 0;
    double value=id_number(number,"doubleValue");
    return __builtin_isfinite(value) && value >= 0 && value < 9223372036854775807.0 ? value : 0;
}

static long long resource_phase_count(IDObj phases, const char *key) {
    long long value=id_json_integer(id_item(phases,key),0);
    return value >= 0 && value <= 8 ? value : 0;
}

/* Status is a cached, bounded dictionary from the owned engine. Reading it
   never scans the resource cache or calculates object digests on the UI thread. */
static void resource_status(IDObj resources) {
    if (!id_is(resources,"NSDictionary")) {
        if (!G.running) {
            G.resourceJobActive=0; G.resourceJobID[0]=0;
            resource_message("서버를 시작하면 보관 목록과 진행 상태를 확인할 수 있습니다.",0);
        }
        return;
    }
    IDObj job=id_item(resources,"job");
    const char *phase=id_utf8(id_item(job,"state"));
    const char *identifier=id_utf8(id_item(job,"job_id"));
    G.resourceJobActive=id_resource_active(phase); G.resourceJobID[0]=0;
    if (id_resource_job_valid(identifier)) {
        IDSize length=strlen(identifier); memcpy(G.resourceJobID,identifier,length+1);
    }
    const char *platform=G.resourcePlatformIndex ? "android" : "ios";
    char message[512];
    if (id_is(job,"NSDictionary") && (G.resourceJobActive || !strcmp(platform,id_utf8(id_item(job,"platform"))))) {
        long long files=id_json_integer(id_item(job,"verified_files"),-1);
        long long total=id_json_integer(id_item(job,"total_files"),-1);
        long long bytes=id_json_integer(id_item(job,"received_bytes"),-1);
        long long missing=id_json_integer(id_item(job,"missing_files"),-1);
        long long parallelism=id_json_integer(id_item(job,"parallelism"),-1);
        if (files < 0 || total < 0 || bytes < 0 || missing < 0) { resource_message("리소스 작업 상태를 확인하고 있습니다.",0); return; }
        const char *phases[]={"preparing","running","export_ready","cancelling","completed","partial","failed","cancelled"};
        const char *names[]={"준비","진행","내보내기 준비","취소 중","완료","일부 완료","실패","취소됨"};
        const char *name="상태 확인 중";
        for (int i=0;i<8;++i) if (!strcmp(phase,phases[i])) name=names[i];
        if (!strcmp(id_utf8(id_item(job,"action")),"download") && id_resource_parallelism_valid(parallelism))
            snprintf(message,sizeof message,"%s · %s · 동시 %lld개 · 확인 %lld/%lld개 · 수신 %.1f MiB · 미보관 %lld개",
                !strcmp(id_utf8(id_item(job,"platform")),"android") ? "Android" : "iOS",name,parallelism,files,total,(double)bytes/1048576.0,missing);
        else snprintf(message,sizeof message,"%s · %s · 확인 %lld/%lld개 · 수신 %.1f MiB · 미보관 %lld개",
                !strcmp(id_utf8(id_item(job,"platform")),"android") ? "Android" : "iOS",name,files,total,(double)bytes/1048576.0,missing);
        if (!strcmp(id_utf8(id_item(job,"action")),"download") && id_item(job,"elapsed_seconds")) {
            IDSize used=strlen(message);
            snprintf(message+used,sizeof message-used,"\n평균 수신 %.2f MiB/s · %.0f초 · 기존 파일 재사용 %lld개",
                resource_number(job,"average_bytes_per_second")/1048576.0,resource_number(job,"elapsed_seconds"),
                id_json_integer(id_item(job,"cache_hit_files"),0));
            used=strlen(message);
            snprintf(message+used,sizeof message-used,"\n용량 검증 완료 %.1f / %.1f GiB",
                resource_number(job,"verified_bytes")/1073741824.0,resource_number(job,"total_bytes")/1073741824.0);
            IDObj phases=id_item(job,"phase_active_files");
            if (id_is(phases,"NSDictionary")) {
                used=strlen(message);
                snprintf(message+used,sizeof message-used,"\n연결 %lld · 받기 %lld · 검증 %lld · 저장 %lld · 복사 %lld개",
                    resource_phase_count(phases,"connecting"),resource_phase_count(phases,"receiving"),
                    resource_phase_count(phases,"checking"),resource_phase_count(phases,"saving"),resource_phase_count(phases,"copying"));
            }
        }
        resource_message(message,!strcmp(phase,"failed") || !strcmp(phase,"partial"));
    } else {
        IDObj catalog=id_item(id_item(resources,"catalogs"),platform);
        long long files=id_json_integer(id_item(catalog,"object_count"),-1);
        long long bytes=id_json_integer(id_item(catalog,"total_bytes"),-1);
        if (files >= 0 && bytes >= 0) {
            snprintf(message,sizeof message,"%s 목록 %lld개 · %.1f GiB · 받은 파일은 크기·MD5를 확인해 보관합니다.",
                G.resourcePlatformIndex ? "Android" : "iOS",files,(double)bytes/1073741824.0);
            resource_message(message,0);
        } else resource_message(G.running ? "목록·예상 용량 확인을 누르면 선택한 플랫폼의 보관 용량을 표시합니다."
            : "서버를 시작하면 보관 목록과 진행 상태를 확인할 수 있습니다.",0);
    }
}

static void received_event(const char *bytes, IDSize length) {
    IDObj event = id_json(id_data(bytes, length));
    if (!id_is(event, "NSDictionary")) return;
    const char *kind = id_utf8(id_item(event, "event"));
    if (strcmp(kind, "log") == 0) { log_line(id_utf8(id_item(event, "message"))); return; }
    if (!strcmp(kind,"resource_error") || !strcmp(kind,"resource_result")) {
        const char *message=id_utf8(id_item(event,"message"));
        G.resourcePending=0; resource_message(*message ? message : "리소스 작업 상태가 갱신되었습니다.",!strcmp(kind,"resource_error"));
        log_line(message); update_controls(); return;
    }
    if (strcmp(kind, "error") == 0) {
        G.busy = 0; status(id_utf8(id_item(event, "message"))); log_line(id_utf8(id_item(event, "message"))); update_controls(); return;
    }
    if (strcmp(kind, "status") != 0) return;
    IDObj state = id_item(event, "status");
    if (!id_is(state, "NSDictionary")) return;
    id_poll_received(&G.polling, uptime());
    G.running = truth(id_item(state, "running")); G.busy = truth(id_item(state, "starting"));
    G.canStop = truth(id_item(state, "can_stop"));
    G.resourcePending=0;
    IDObj resources=id_item(state,"resource_library");
    IDObj previous=G.resourceSnapshot; G.resourceSnapshot=id_keep(resources);
    if (previous) id_void(previous,"release");
    resource_status(resources);
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
        enum IDShutdownAction action = id_shutdown_step(&G.shutdown, now, alive,
            G.task ? id_int(G.task, "processIdentifier") : 0);
        if (action == ID_SHUTDOWN_TERM) kill(G.shutdown.ownedPID, 15);
        else if (action == ID_SHUTDOWN_KILL) kill(G.shutdown.ownedPID, 9);
        else if (action == ID_SHUTDOWN_FINISH) {
            /* NSTask owns reaping. Read the result only after it reports exit;
               waitUntilExit on the main thread would block the window again. */
            if (G.shutdown.observedExit && G.task) (void)id_int(G.task, "terminationStatus");
            if (G.shutdown.timedOut) log_line("서버 엔진에 강제 종료를 요청한 뒤 앱을 종료합니다.");
            if (G.shutdown.ownershipLost) log_line("서버 엔진의 소유 정보를 확인할 수 없어 추가 신호 없이 앱을 종료합니다.");
            id_void(G.timer, "invalidate");
            id_set(G.app, "terminate:", G.delegate);
        }
    } else if (alive) {
        if (G.polling.received && !id_poll_fresh(&G.polling, now)) {
            G.ackPresent = 0; status("서버 응답을 기다리고 있습니다."); update_controls();
        }
        if (now - G.lastRequestAt >= 1 && id_poll_begin(&G.polling)) {
            G.lastRequestAt = now;
            if (!send_control("status")) G.polling.outstanding = 0;
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
    /* Darwin F_GETFL=3, F_SETFL=4, O_NONBLOCK=4. Never let a full engine pipe
       block a button, the timer, or applicationShouldTerminate on the main thread. */
    int writable = id_control_nonblocking(G.inputFD, 3, 4, 4, fcntl);
    if (!writable) close_input();
    G.outFD = id_int(id_get(output, "fileHandleForReading"), "fileDescriptor");
    G.errorFD = id_int(id_get(errors, "fileHandleForReading"), "fileDescriptor");
    IDBool launched = ((IDBool (*)(IDObj, IDSel, IDObj *))IDRuntime.message)(G.task, id_sel("launchAndReturnError:"), 0);
    if (!launched) { G.engineEnded = 1; G.busy = 0; status("서버 엔진을 실행하지 못했습니다. 앱 파일을 확인해 주세요."); }
    else if (!writable) { G.busy = 0; status("서버 엔진 제어 통로를 준비하지 못했습니다. 앱을 다시 열어 주세요."); }
    update_controls();
}

static void did_launch(IDObj self, IDSel command, IDObj notification) {
    (void)self; (void)command; (void)notification;
    if (G.window) return;
    make_window(); start_engine(); G.startedAt = uptime();
    G.timer = id_keep(((IDObj (*)(IDObj, IDSel, double, IDObj, IDSel, IDObj, IDBool))IDRuntime.message)(
        id_class("NSTimer"), id_sel("timerWithTimeInterval:target:selector:userInfo:repeats:"),
        0.2, G.delegate, id_sel("timerTick:"), 0, 1));
    /* Common modes include ordinary events and menu tracking. Quit itself is
       cancelled during cleanup, so no termination-modal run loop is entered. */
    ((void (*)(IDObj, IDSel, IDObj, IDObj))IDRuntime.message)(id_get(id_class("NSRunLoop"), "mainRunLoop"),
        id_sel("addTimer:forMode:"), G.timer, id_string("kCFRunLoopCommonModes"));
}

static unsigned long should_terminate(IDObj self, IDSel command, IDObj app) {
    (void)self; (void)command; (void)app;
    int alive = G.task && id_bool(G.task, "isRunning");
    enum IDTerminateReply reply = id_shutdown_request(&G.shutdown, uptime(),
        G.task ? id_int(G.task, "processIdentifier") : 0, alive);
    if (reply == ID_TERMINATE_NOW) return ID_TERMINATE_NOW;
    if (!G.quitting) {
        G.quitting = 1; G.ackPresent = 0;
        status("서버 엔진을 종료하고 있습니다."); update_controls();
        send_control("quit");
        close_input(); /* EOF also requests cleanup if the quit command could not fit. */
    }
    /* Keep the normal run loop/timer alive. tick reissues terminate only when
       the owned child has exited, or bounded escalation has finished. */
    return ID_TERMINATE_CANCEL;
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
    G.resourceParallelismValue=id_resource_parallelism(id_json_integer(
        id_arg(G.defaults,"objectForKey:",id_string("resourceDownloadParallelism")),-1));
    IDObj resourcesChoice=id_arg(G.defaults,"objectForKey:",id_string("resourcesInDownloads"));
    G.resourcesDownloads=id_resources_in_downloads(id_is(resourcesChoice,"NSNumber")
        && IDRuntime.typeID(resourcesChoice)==IDRuntime.booleanTypeID(),truth(resourcesChoice));
    IDObj downloadDirectories=((IDObj (*)(IDObj,IDSel,unsigned long,unsigned long))IDRuntime.message)(
        id_get(id_class("NSFileManager"),"defaultManager"),id_sel("URLsForDirectory:inDomains:"),ID_SEARCH_DOWNLOADS,ID_USER_DOMAIN);
    if (id_long(downloadDirectories,"count") > 0)
        G.downloadsResourcesURL=id_keep(childURL(id_index(downloadDirectories,"objectAtIndex:",0),"IdolyPride"));
    IDObj savedRoot=id_arg(G.defaults,"objectForKey:",id_string("resourceDirectoryPath"));
    if (savedRoot && !(id_is(savedRoot,"NSString") && id_long(savedRoot,"length")==0)) {
        if (!valid_resource_path(savedRoot)) G.invalidResourceLocation=1;
        else G.customResourcesURL=id_keep(id_get(id_get(id_arg(id_class("NSURL"),"fileURLWithPath:",savedRoot),
            "URLByStandardizingPath"),"URLByResolvingSymlinksInPath"));
    }
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
    G.playbackURL = id_keep(childURL(G.dataURL, "client-playback.json")); load_playback_preferences();
    G.library=id_library_defaults();
    G.mediaURL=id_keep(childURL(G.dataURL,"client-media.json")); load_library_file(G.mediaURL,0);
    G.languageURL=id_keep(childURL(G.dataURL,"client-language.json")); load_library_file(G.languageURL,1);
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
