#include <jni.h>
#include <stdio.h>
#include "shadowhook.h"
#include "machine_state_check.h"

// Avoid dependency JNI_OnLoad lookup; ShadowHook is initialized via C API.
extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM*, void*) { return JNI_VERSION_1_6; }
static const char* boolean(bool value) { return value ? "true" : "false"; }

extern "C" JNIEXPORT jstring JNICALL
Java_game_qualiarts_idolypride_phase_1selftest_SelfTestActivity_runNative(JNIEnv* env, jclass) {
    bool baseline = idoly_phase_machine_baseline();
    int initialized = shadowhook_init(SHADOWHOOK_MODE_UNIQUE, false);
    // The pinned AAR does not export its header's get_init_errno declaration.
    int init_errno = shadowhook_get_errno();
    shadowhook_set_recordable(false);
    bool ok = initialized == 0 && idoly_phase_machine_check();
    const idoly_machine_report_t& report = *idoly_phase_machine_report();
    const idoly_machine_case_report_t& add = report.add;
    const idoly_machine_case_report_t& bl = report.bl;
    char output[2048];
    snprintf(output, sizeof(output),
        "{\"schema\":1,\"ok\":%s,\"abi\":\"arm64-v8a\",\"synthetic_only\":true,"
        "\"shadowhook_version\":\"2.0.1\",\"baseline\":%s,\"initialized\":%s,\"installed\":%s,"
        "\"init_result\":%d,\"init_errno\":%d,\"install_errno\":%d,\"bl_install_errno\":%d,"
        "\"original_instruction\":%s,\"gpr\":%s,\"simd\":%s,\"sp\":%s,\"nzcv\":%s,"
        "\"fpcr\":%s,\"fpsr\":%s,\"callback_context\":%s,\"callback_hits\":%s,"
        "\"hook_failure_fail_open\":%s,\"unintercept\":%s,\"bl_baseline\":%s,"
        "\"bl_installed\":%s,\"bl_original_instruction\":%s,\"bl_original_lr\":%s,"
        "\"bl_callback_context\":%s,\"bl_callback_hits\":%s,\"bl_unintercept\":%s,"
        "\"add_unintercept_result\":%d,\"bl_unintercept_result\":%d}",
        boolean(ok), boolean(baseline), boolean(initialized == 0), boolean(add.installed && bl.installed),
        initialized, init_errno, add.install_errno, bl.install_errno,
        boolean(add.original_instruction && bl.original_instruction), boolean(add.gpr && bl.gpr),
        boolean(add.simd && bl.simd), boolean(add.sp && bl.sp), boolean(add.nzcv && bl.nzcv),
        boolean(add.fpcr && bl.fpcr), boolean(add.fpsr && bl.fpsr),
        boolean(add.callback_context && bl.callback_context), boolean(add.callback_hits && bl.callback_hits),
        boolean(report.hook_failure_fail_open), boolean(add.unintercept && bl.unintercept), boolean(bl.baseline),
        boolean(bl.installed), boolean(bl.original_instruction), boolean(bl.link_register),
        boolean(bl.callback_context), boolean(bl.callback_hits), boolean(bl.unintercept),
        add.unintercept_result, bl.unintercept_result);
    return env->NewStringUTF(output);
}
