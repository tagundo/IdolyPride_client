#include "machine_state_check.h"
#include "shadowhook.h"
#include <stddef.h>
#include <stdint.h>
#include <string.h>

struct alignas(16) Snapshot {
    uint64_t regs[31];
    uint64_t sp, nzcv, fpcr, fpsr, padding;
    uint8_t simd[32][16];
};
struct Snapshots { Snapshot before, after; };
static_assert(sizeof(Snapshot) == 800, "assembly snapshot size");
static_assert(offsetof(Snapshot, simd) == 288, "assembly SIMD offset");
extern "C" void idoly_machine_checkpoint_add(Snapshots*);
extern "C" void idoly_machine_checkpoint_bl(Snapshots*);
extern "C" void idoly_machine_instruction_add();
extern "C" void idoly_machine_instruction_bl();
struct CaseContext {
    Snapshots snapshots;
    unsigned hits;
    bool context_ok, is_bl;
};
// Every callback context and snapshot outlives even a failed unintercept.
static CaseContext add_context, bl_context;
static idoly_machine_report_t report;
static unsigned baseline_state, check_state; // 0=new, 1=running, 2=finished.

static void intercept(shadowhook_cpu_context_t* cpu, void* opaque) {
    CaseContext& context = *static_cast<CaseContext*>(opaque);
    const Snapshot& before = context.snapshots.before;
    bool same = cpu->sp == before.sp && (cpu->pstate & 0xf0000000) == before.nzcv
            && cpu->fpcr == before.fpcr && cpu->fpsr == before.fpsr;
    for (unsigned i = 0; i < 31; ++i) same = same && cpu->regs[i] == before.regs[i];
    for (unsigned i = 0; i < 32; ++i) same = same && memcmp(cpu->vregs[i].b, before.simd[i], 16) == 0;
    context.context_ok = context.context_ok && same;
    ++context.hits;
    // Context remains read-only. Deliberately clobber live caller registers,
    // SIMD upper halves and flags. Android x18 is never modified; compiler
    // AAPCS64 saves retain d8..d15 for ShadowHook's own internal caller.
    asm volatile(
        "mov x0, #0xee\nmov x1, #0xee\nmov x2, #0xee\nmov x3, #0xee\n"
        "mov x4, #0xee\nmov x5, #0xee\nmov x6, #0xee\nmov x7, #0xee\n"
        "mov x8, #0xee\nmov x9, #0xee\nmov x10, #0xee\nmov x11, #0xee\n"
        "mov x12, #0xee\nmov x13, #0xee\nmov x14, #0xee\nmov x15, #0xee\n"
        "mov x16, #0xee\nmov x17, #0xee\n"
        ".irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31\n"
        "movi v\\n\\().16b, #0xee\n.endr\n"
        "mov x16, #0x800000\nmsr fpcr, x16\nmsr fpsr, xzr\nmsr nzcv, xzr\n"
        : : : "x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11",
        "x12", "x13", "x14", "x15", "x16", "x17", "v0", "v1", "v2", "v3", "v4", "v5",
        "v6", "v7", "v8", "v9", "v10", "v11", "v12", "v13", "v14", "v15", "v16", "v17",
        "v18", "v19", "v20", "v21", "v22", "v23", "v24", "v25", "v26", "v27", "v28", "v29",
        "v30", "v31", "cc", "memory");
}

static void execute(CaseContext& context) {
    if (context.is_bl) idoly_machine_checkpoint_bl(&context.snapshots);
    else idoly_machine_checkpoint_add(&context.snapshots);
}

static idoly_machine_case_report_t inspect(const CaseContext& context) {
    idoly_machine_case_report_t result{};
    const Snapshot& before = context.snapshots.before;
    const Snapshot& after = context.snapshots.after;
    uint64_t expected_lr = context.is_bl ? reinterpret_cast<uintptr_t>(idoly_machine_instruction_bl) + 4
                                         : before.regs[30];
    result.original_instruction = before.regs[0] == 0x101 && after.regs[0] == before.regs[0] + 7;
    result.gpr = result.simd = true;
    for (unsigned i = 0; i < 31; ++i) {
        uint64_t expected = i == 30 ? expected_lr : before.regs[i] + (i == 0 ? 7 : i == 28 ? 800 : 0);
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
    result.link_register = after.regs[30] == expected_lr;
    return result;
}

static bool state_ok(const idoly_machine_case_report_t& value) {
    return value.original_instruction && value.gpr && value.simd && value.sp && value.nzcv
            && value.fpcr && value.fpsr && value.link_register;
}

extern "C" bool idoly_phase_machine_baseline(void) {
    unsigned expected = 0;
    if (!__atomic_compare_exchange_n(&baseline_state, &expected, 1, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
        return expected == 2 && report.add.baseline && report.bl.baseline;
    report.add.install_errno = report.bl.install_errno = -1;
    report.add.unintercept_result = report.bl.unintercept_result = -1;
    bl_context.is_bl = true;
    execute(add_context);
    report.add.baseline = state_ok(inspect(add_context));
    execute(bl_context);
    report.bl.baseline = state_ok(inspect(bl_context));
    __atomic_store_n(&baseline_state, 2, __ATOMIC_RELEASE);
    return report.add.baseline && report.bl.baseline;
}

// False means an installed hook could not be proven removed. All callback
// data stays static; after such a failure no further fixture is installed.
static bool run_case(CaseContext& context, idoly_machine_case_report_t& value, void* instruction) {
    context.hits = 0;
    context.context_ok = true;
    void* stub = shadowhook_intercept_instr_addr(instruction, intercept, &context,
            SHADOWHOOK_INTERCEPT_WITH_FPSIMD_READ_WRITE);
    value.install_errno = shadowhook_get_errno();
    value.installed = stub != nullptr;
    if (stub == nullptr) return true; // No hook remains; its report still fails.
    value.original_instruction = value.gpr = value.simd = value.sp = true;
    value.nzcv = value.fpcr = value.fpsr = value.link_register = true;
    for (unsigned iteration = 0; iteration < 3; ++iteration) {
        execute(context);
        idoly_machine_case_report_t one = inspect(context);
        value.original_instruction &= one.original_instruction; value.gpr &= one.gpr;
        value.simd &= one.simd; value.sp &= one.sp; value.nzcv &= one.nzcv;
        value.fpcr &= one.fpcr; value.fpsr &= one.fpsr; value.link_register &= one.link_register;
    }
    value.callback_context = context.context_ok;
    value.callback_hits = context.hits == 3;
    value.unintercept_result = shadowhook_unintercept(stub);
    if (value.unintercept_result != 0) return false;
    unsigned previous_hits = context.hits;
    execute(context);
    value.unintercept = state_ok(inspect(context)) && context.hits == previous_hits;
    return value.unintercept;
}

static bool case_ok(const idoly_machine_case_report_t& value) {
    return value.baseline && value.installed && state_ok(value) && value.callback_context
            && value.callback_hits && value.unintercept && value.install_errno == 0 && value.unintercept_result == 0;
}

extern "C" bool idoly_phase_machine_check(void) {
    unsigned expected = 0;
    if (!__atomic_compare_exchange_n(&check_state, &expected, 1, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
        return expected == 2 && report.ok;
    report.attempted = true;
    if (idoly_phase_machine_baseline()) {
        void* rejected = shadowhook_intercept_instr_addr(nullptr, intercept, &add_context,
                SHADOWHOOK_INTERCEPT_WITH_FPSIMD_READ_WRITE);
        int rejected_errno = shadowhook_get_errno();
        bool rejected_removed = rejected == nullptr || shadowhook_unintercept(rejected) == 0;
        execute(add_context);
        report.hook_failure_fail_open = rejected == nullptr && rejected_errno != 0
                && state_ok(inspect(add_context)) && add_context.hits == 0;
        if (rejected_removed) {
            bool add_removed = run_case(add_context, report.add, reinterpret_cast<void*>(idoly_machine_instruction_add));
            if (add_removed) run_case(bl_context, report.bl, reinterpret_cast<void*>(idoly_machine_instruction_bl));
        }
        report.ok = report.hook_failure_fail_open && case_ok(report.add) && case_ok(report.bl);
    }
    __atomic_store_n(&check_state, 2, __ATOMIC_RELEASE);
    return report.ok;
}

extern "C" const idoly_machine_report_t* idoly_phase_machine_report(void) { return &report; }
