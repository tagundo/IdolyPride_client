#include <jni.h>
#include <stdio.h>
#include "shadowhook.h"
#include "machine_state_check.h"

extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM*, void*) { return JNI_VERSION_1_6; }
static const char* boolean(bool value) { return value ? "true" : "false"; }

static void case_json(char* output, size_t capacity, const idoly_machine_case_report_t& value) {
    snprintf(output, capacity,
        "{\"baseline\":%s,\"installed\":%s,\"original_instruction\":%s,\"gpr\":%s,"
        "\"simd\":%s,\"sp\":%s,\"nzcv\":%s,\"fpcr\":%s,\"fpsr\":%s,"
        "\"link_register\":%s,\"callback_context\":%s,\"callback_hits\":%s,"
        "\"unintercept\":%s,\"install_errno\":%d,\"unintercept_result\":%d}",
        boolean(value.baseline), boolean(value.installed), boolean(value.original_instruction),
        boolean(value.gpr), boolean(value.simd), boolean(value.sp), boolean(value.nzcv),
        boolean(value.fpcr), boolean(value.fpsr), boolean(value.link_register),
        boolean(value.callback_context), boolean(value.callback_hits), boolean(value.unintercept),
        value.install_errno, value.unintercept_result);
}

extern "C" JNIEXPORT jstring JNICALL
Java_game_qualiarts_idolypride_phase_1selftest_SelfTestActivity_runNative(JNIEnv* env, jclass) {
    bool baseline = idoly_phase_machine_baseline();
    int init_result = shadowhook_init(SHADOWHOOK_MODE_UNIQUE, false);
    int init_errno = shadowhook_get_errno();
    shadowhook_set_recordable(false);
    bool ok = init_result == 0 && idoly_phase_machine_check();
    const idoly_machine_report_t& report = *idoly_phase_machine_report();
    char add[1024], bl[1024], output[3072];
    case_json(add, sizeof(add), report.add);
    case_json(bl, sizeof(bl), report.bl);
    snprintf(output, sizeof(output),
        "{\"schema\":2,\"synthetic_only\":true,\"abi\":\"arm64-v8a\","
        "\"shadowhook_version\":\"2.0.1\",\"baseline\":%s,\"init_result\":%d,\"init_errno\":%d,"
        "\"attempted\":%s,\"ok\":%s,\"hook_failure_fail_open\":%s,\"add\":%s,\"bl\":%s}",
        boolean(baseline), init_result, init_errno, boolean(report.attempted), boolean(ok),
        boolean(report.hook_failure_fail_open), add, bl);
    return env->NewStringUTF(output);
}
