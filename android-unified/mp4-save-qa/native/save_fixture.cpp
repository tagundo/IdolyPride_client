// SPDX-License-Identifier: AGPL-3.0-or-later
// Synthetic native producer only. Actual production Java owns Save and lifecycle.
#include <jni.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#ifndef IDOLY_SAVE_SOURCE_SHA256
#error Verified source snapshot required
#endif
#ifndef IDOLY_SAVE_CONTROLLER_SHA256
#error Verified unchanged production controller required
#endif
static jclass fixture(JNIEnv* env) { return env->FindClass("game/qualiarts/idolypride/localserver/SaveProbeActivity"); }
extern "C" {
JNIEXPORT jstring JNICALL Java_game_qualiarts_idolypride_localserver_SaveProbeActivity_nativeReceipt(JNIEnv* env, jclass) {
    char context[512]{}; int fd = open("/proc/self/attr/current", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    ssize_t n = fd >= 0 ? read(fd, context, sizeof(context) - 1) : -1; if (fd >= 0) close(fd);
    if (n <= 0) return env->NewStringUTF("{\"error\":\"selinux_context_unavailable\"}");
    while (n > 0 && (context[n - 1] == '\n' || context[n - 1] == 0)) context[--n] = 0;
    for (ssize_t i = 0; i < n; ++i) if (context[i] < 32 || context[i] == '"' || context[i] == '\\') return env->NewStringUTF("{\"error\":\"selinux_context_invalid\"}");
    char report[1024]{};
    snprintf(report, sizeof(report), "{\"uid\":%u,\"euid\":%u,\"pid\":%u,\"selinux_context\":\"%s\",\"source_snapshot_sha256\":\"%s\",\"production_controller_sha256\":\"%s\",\"synthetic_native_fixture\":true}",
             getuid(), geteuid(), getpid(), context, IDOLY_SAVE_SOURCE_SHA256, IDOLY_SAVE_CONTROLLER_SHA256);
    return env->NewStringUTF(report);
}
JNIEXPORT jboolean JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeInitializeEncoder(JNIEnv*, jclass, jclass) { return true; }
JNIEXPORT jint JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeConfigure(JNIEnv* env, jclass, jstring broker, jlong epoch, jstring, jstring output, jint platform) {
    const char* root = env->GetStringUTFChars(broker, nullptr); if (!root) return -1;
    const char* destination = env->GetStringUTFChars(output, nullptr); if (!destination) { env->ReleaseStringUTFChars(broker, root); return -1; }
    const size_t length = strlen(root);
    const bool valid = epoch > 0 && platform == 1 && strlen(destination) == length + 8
        && memcmp(destination, root, length) == 0 && strcmp(destination + length, "/exports") == 0;
    env->ReleaseStringUTFChars(broker, root); env->ReleaseStringUTFChars(output, destination); return valid ? 0 : -1;
}
JNIEXPORT jint JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeQueueConfigure(JNIEnv*, jclass, jstring, jstring) { return 0; }
JNIEXPORT jstring JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeStatus(JNIEnv* env, jclass) {
    jclass type = fixture(env); return static_cast<jstring>(env->GetStaticObjectField(type, env->GetStaticFieldID(type, "nativeSession", "Ljava/lang/String;")));
}
JNIEXPORT jstring JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeQueueStatus(JNIEnv* env, jclass) { return env->NewStringUTF("{\"available\":true,\"running\":false,\"paused\":false,\"jobs\":[]}"); }
JNIEXPORT void JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeCancel(JNIEnv* env, jclass) {
    jclass type = fixture(env); env->CallStaticVoidMethod(type, env->GetStaticMethodID(type, "fixtureCancel", "()V"));
}
JNIEXPORT void JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeInvalidateQueueSelection(JNIEnv*, jclass) { }
JNIEXPORT void JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeSuspend(JNIEnv*, jclass, jint) { }
JNIEXPORT void JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeResume(JNIEnv*, jclass) { }
JNIEXPORT jboolean JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeReady(JNIEnv*, jclass) { return false; }
JNIEXPORT jint JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeQueuePause(JNIEnv*, jclass) { return 0; }
JNIEXPORT jint JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeQueueCommand(JNIEnv*, jclass, jint, jstring, jint) { return -1; }
}
