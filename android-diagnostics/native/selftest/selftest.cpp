#include <jni.h>
#include <stdio.h>
#include "shadowhook.h"
#include "machine_state_check.h"

// Avoid dependency JNI_OnLoad lookup; ShadowHook is initialized via C API.
extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM*, void*) { return JNI_VERSION_1_6; }
static const char* boolean(bool value) { return value ? "true" : "false"; }

extern "C" JNIEXPORT jstring JNICALL
Java_game_qualiarts_idolypride_phase_1selftest_SelfTestActivity_runNative(JNIEnv* env, jclass) {
    bool baseline = idoly_phase_machine_baseline_ordinary();
    int initialized = shadowhook_init(SHADOWHOOK_MODE_UNIQUE, false);
    int init_errno = shadowhook_get_errno();  // Capture before any later API call.
    shadowhook_set_recordable(false);
    bool ok = initialized == 0 && idoly_phase_machine_check_ordinary();
    const idoly_machine_ordinary_report_t& report = *idoly_phase_machine_ordinary_report();
    const char* names[] = {"add", "mov", "ldr", "ldp", "subsp", "strpre", "ldppost"};
    char cases[6144] = {0};
    size_t offset = 0;
    for (unsigned i = 0; i < IDOLY_ORDINARY_CASE_COUNT; ++i) {
        const auto& value = report.cases[i];
        int length = snprintf(cases + offset, sizeof(cases) - offset,
            "%s\"%s\":{\"baseline\":%s,\"installed\":%s,\"original_instruction\":%s,"
            "\"gpr\":%s,\"simd\":%s,\"sp\":%s,\"nzcv\":%s,\"fpcr\":%s,\"fpsr\":%s,"
            "\"link_register\":%s,\"callback_context\":%s,\"callback_hits\":%s,"
            "\"neighbors\":%s,\"unintercept\":%s,\"install_errno\":%d,\"unintercept_result\":%d}",
            i == 0 ? "" : ",", names[i], boolean(value.baseline), boolean(value.installed),
            boolean(value.original_instruction), boolean(value.gpr), boolean(value.simd), boolean(value.sp),
            boolean(value.nzcv), boolean(value.fpcr), boolean(value.fpsr), boolean(value.link_register),
            boolean(value.callback_context), boolean(value.callback_hits), boolean(value.neighbors),
            boolean(value.unintercept), value.install_errno, value.unintercept_result);
        if (length < 0 || static_cast<size_t>(length) >= sizeof(cases) - offset)
            return env->NewStringUTF("{\"schema\":2,\"ok\":false,\"synthetic_only\":true}");
        offset += static_cast<size_t>(length);
    }
    char output[8192];
    snprintf(output, sizeof(output),
        "{\"schema\":2,\"scope\":\"ordinary-v2\",\"ok\":%s,\"abi\":\"arm64-v8a\","
        "\"synthetic_only\":true,\"shadowhook_version\":\"2.0.1\",\"baseline\":%s,"
        "\"initialized\":%s,\"init_result\":%d,\"init_errno\":%d,\"attempted\":%s,"
        "\"hook_failure_fail_open\":%s,\"cases\":{%s}}", boolean(ok), boolean(baseline),
        boolean(initialized == 0), initialized, init_errno, boolean(report.attempted),
        boolean(report.hook_failure_fail_open), cases);
    return env->NewStringUTF(output);
}
