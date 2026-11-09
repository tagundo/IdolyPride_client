#include <jni.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "shadowhook.h"

// Load ShadowHook only as this library's DT_NEEDED dependency. Its Java
// wrapper is deliberately absent; our own entry point prevents JNI_OnLoad
// lookup from falling through to the dependency's Java-wrapper entry point.
extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM*, void*) {
    return JNI_VERSION_1_6;
}

struct alignas(16) Snapshot {
    uint64_t regs[31];
    uint64_t sp, nzcv, fpcr, fpsr, padding;
    uint8_t simd[32][16];
};
struct Snapshots { Snapshot before, after; };
static_assert(sizeof(Snapshot) == 800, "assembly snapshot size");
static_assert(offsetof(Snapshot, simd) == 288, "assembly SIMD offset");
extern "C" void idoly_selftest_checkpoint(Snapshots* output);
extern "C" void idoly_selftest_instruction();

static unsigned callback_hits;
static bool callback_context_ok;

static void intercept(shadowhook_cpu_context_t* cpu, void* opaque) {
    const Snapshot& before = static_cast<Snapshots*>(opaque)->before;
    bool same = cpu->sp == before.sp && (cpu->pstate & 0xf0000000) == before.nzcv
            && cpu->fpcr == before.fpcr && cpu->fpsr == before.fpsr;
    for (unsigned i = 0; i < 31; ++i) same = same && cpu->regs[i] == before.regs[i];
    for (unsigned i = 0; i < 32; ++i) same = same && memcmp(cpu->vregs[i].b, before.simd[i], 16) == 0;
    callback_context_ok = callback_context_ok && same;
    ++callback_hits;
    // Leave the supplied CPU context untouched. Deliberately trash permitted
    // live caller registers and flags to exercise ShadowHook's restoration.
    // Compiler-generated AAPCS64 saves preserve d8..d15 for its own caller;
    // the upper halves of q8..q15 still require full FPSIMD restoration.
    asm volatile(
        "mov x0, #0xee\nmov x1, #0xee\nmov x2, #0xee\nmov x3, #0xee\n"
        "mov x4, #0xee\nmov x5, #0xee\nmov x6, #0xee\nmov x7, #0xee\n"
        "mov x8, #0xee\nmov x9, #0xee\nmov x10, #0xee\nmov x11, #0xee\n"
        "mov x12, #0xee\nmov x13, #0xee\nmov x14, #0xee\nmov x15, #0xee\n"
        "mov x16, #0xee\nmov x17, #0xee\n"
        ".irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31\n"
        "movi v\\n\\().16b, #0xee\n.endr\n"
        "mov x16, #0x800000\nmsr fpcr, x16\n"
        "msr fpsr, xzr\nmsr nzcv, xzr\n"
        : : : "x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9",
        "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17",
        "v0", "v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10", "v11",
        "v12", "v13", "v14", "v15", "v16", "v17", "v18", "v19", "v20", "v21", "v22", "v23",
        "v24", "v25", "v26", "v27", "v28", "v29", "v30", "v31", "cc", "memory");
}

struct Checks {
    bool original = true, gpr = true, simd = true, sp = true;
    bool nzcv = true, fpcr = true, fpsr = true;
    bool ok() const { return original && gpr && simd && sp && nzcv && fpcr && fpsr; }
};

static Checks check(const Snapshots& output) {
    Checks result;
    const Snapshot& before = output.before;
    const Snapshot& after = output.after;
    result.original = before.regs[0] == 0x101 && after.regs[0] == before.regs[0] + 7;
    for (unsigned i = 0; i < 31; ++i) {
        uint64_t expected = before.regs[i] + (i == 0 ? 7 : i == 28 ? 800 : 0);
        result.gpr = result.gpr && after.regs[i] == expected;
        if (i != 18 && i != 28) result.gpr = result.gpr && before.regs[i] == 0x101 + i;
    }
    for (unsigned i = 0; i < 32; ++i)
        for (unsigned j = 0; j < 16; ++j)
            result.simd = result.simd && before.simd[i][j] == i + 1 && after.simd[i][j] == i + 1;
    result.sp = before.sp != 0 && (before.sp & 15) == 0 && before.sp == after.sp;
    result.nzcv = before.nzcv == 0xa0000000 && before.nzcv == after.nzcv;
    result.fpcr = before.fpcr == 0x400000 && before.fpcr == after.fpcr;
    result.fpsr = before.fpsr == 0x8000000 && before.fpsr == after.fpsr;
    return result;
}

static const char* boolean(bool value) { return value ? "true" : "false"; }

extern "C" JNIEXPORT jstring JNICALL
Java_game_qualiarts_idolypride_phase_1selftest_SelfTestActivity_runNative(JNIEnv* env, jclass) {
    Snapshots output{};
    idoly_selftest_checkpoint(&output);
    bool baseline = check(output).ok();
    int initialized = shadowhook_init(SHADOWHOOK_MODE_UNIQUE, false);
    shadowhook_set_recordable(false);
    callback_hits = 0;
    callback_context_ok = true;
    void* rejected = shadowhook_intercept_instr_addr(nullptr, intercept, &output,
            SHADOWHOOK_INTERCEPT_WITH_FPSIMD_READ_WRITE);
    bool failure_rejected = rejected == nullptr && shadowhook_get_errno() != 0;
    if (rejected != nullptr) shadowhook_unintercept(rejected);
    idoly_selftest_checkpoint(&output);
    bool fail_open = failure_rejected && check(output).ok() && callback_hits == 0;
    void* stub = initialized == 0 ? shadowhook_intercept_instr_addr(
            reinterpret_cast<void*>(idoly_selftest_instruction), intercept, &output,
            SHADOWHOOK_INTERCEPT_WITH_FPSIMD_READ_WRITE) : nullptr;
    Checks checks;
    if (stub == nullptr) {
        checks.original = checks.gpr = checks.simd = checks.sp = false;
        checks.nzcv = checks.fpcr = checks.fpsr = false;
    }
    if (stub != nullptr) {
        for (unsigned iteration = 0; iteration < 3; ++iteration) {
            idoly_selftest_checkpoint(&output);
            Checks one = check(output);
            checks.original &= one.original; checks.gpr &= one.gpr; checks.simd &= one.simd;
            checks.sp &= one.sp; checks.nzcv &= one.nzcv; checks.fpcr &= one.fpcr; checks.fpsr &= one.fpsr;
        }
    }
    bool hits = stub != nullptr && callback_hits == 3;
    bool restored = stub != nullptr && shadowhook_unintercept(stub) == 0;
    unsigned previous_hits = callback_hits;
    idoly_selftest_checkpoint(&output);
    restored = restored && check(output).ok() && callback_hits == previous_hits;
    bool ok = baseline && initialized == 0 && hits && checks.ok() && callback_context_ok && fail_open && restored;
    char report[1024];
    snprintf(report, sizeof(report),
        "{\"schema\":1,\"ok\":%s,\"abi\":\"arm64-v8a\",\"synthetic_only\":true,"
        "\"shadowhook_version\":\"2.0.1\",\"baseline\":%s,\"initialized\":%s,\"installed\":%s,"
        "\"original_instruction\":%s,\"gpr\":%s,\"simd\":%s,\"sp\":%s,\"nzcv\":%s,"
        "\"fpcr\":%s,\"fpsr\":%s,\"callback_context\":%s,\"callback_hits\":%s,"
        "\"hook_failure_fail_open\":%s,\"unintercept\":%s}",
        boolean(ok), boolean(baseline), boolean(initialized == 0), boolean(stub != nullptr),
        boolean(checks.original), boolean(checks.gpr), boolean(checks.simd), boolean(checks.sp),
        boolean(checks.nzcv), boolean(checks.fpcr), boolean(checks.fpsr), boolean(callback_context_ok),
        boolean(hits), boolean(fail_open), boolean(restored));
    return env->NewStringUTF(report);
}
