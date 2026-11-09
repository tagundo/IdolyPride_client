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
struct Snapshots { Snapshot before, after; uint64_t stored; };
static_assert(sizeof(Snapshot) == 800, "assembly snapshot size");
static_assert(offsetof(Snapshot, simd) == 288, "assembly SIMD offset");
extern "C" void idoly_machine_checkpoint_add(Snapshots*);
extern "C" void idoly_machine_instruction_add();
enum Kind { ADD = 0, MOV = 2, LDR, LDP, SUBSP, STRPRE, LDPPOST };
#define DECLARE_CASE(name) extern "C" void idoly_machine_checkpoint_##name(Snapshots*); \
    extern "C" void idoly_machine_instruction_##name();
DECLARE_CASE(mov) DECLARE_CASE(ldr) DECLARE_CASE(ldp)
DECLARE_CASE(subsp) DECLARE_CASE(strpre) DECLARE_CASE(ldppost)
struct CaseContext {
    Snapshots snapshots;
    unsigned hits;
    bool context_ok;
    Kind kind;
};
// Every callback context outlives even an uncertain removal.
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
    switch (context.kind) {
    case ADD: idoly_machine_checkpoint_add(&context.snapshots); break;
    case MOV: idoly_machine_checkpoint_mov(&context.snapshots); break;
    case LDR: idoly_machine_checkpoint_ldr(&context.snapshots); break;
    case LDP: idoly_machine_checkpoint_ldp(&context.snapshots); break;
    case SUBSP: idoly_machine_checkpoint_subsp(&context.snapshots); break;
    case STRPRE: idoly_machine_checkpoint_strpre(&context.snapshots); break;
    case LDPPOST: idoly_machine_checkpoint_ldppost(&context.snapshots); break;
    }
}

static idoly_machine_case_report_t inspect(const CaseContext& context) {
    idoly_machine_case_report_t result{};
    const Snapshot& before = context.snapshots.before;
    const Snapshot& after = context.snapshots.after;
    uint64_t expected_lr = context.kind == LDPPOST ? 0x9001 : before.regs[30];
    result.original_instruction = true;
    result.gpr = result.simd = true;
    for (unsigned i = 0; i < 31; ++i) {
        uint64_t expected = before.regs[i] + (i == 28 ? 800 : 0);
        if (i == 30) expected = expected_lr;
        if (i == 0 && context.kind == ADD) expected += 7;
        if (i == 0 && context.kind == MOV) expected = before.regs[1];
        if (i == 1 && context.kind == LDR) expected = 0x9001;
        if (i == 1 && context.kind == LDP) expected = 0x9002;
        if (i == 2 && context.kind == LDP) expected = 0x9001;
        if (i == 19 && context.kind == LDPPOST) expected = 0x9002;
        result.gpr = result.gpr && after.regs[i] == expected;
        bool scratch_base = i == 19 && (context.kind == LDR || context.kind == LDP);
        if (i != 18 && i != 28 && !scratch_base)
            result.gpr = result.gpr && before.regs[i] == 0x101 + i;
    }
    switch (context.kind) {
    case ADD: result.original_instruction = after.regs[0] == 0x108; break;
    case MOV: result.original_instruction = after.regs[0] == 0x102; break;
    case LDR: result.original_instruction = after.regs[1] == 0x9001; break;
    case LDP: result.original_instruction = after.regs[2] == 0x9001 && after.regs[1] == 0x9002; break;
    case SUBSP: result.original_instruction = after.sp == before.sp - 0x90; break;
    case STRPRE: result.original_instruction = after.sp == before.sp - 16
            && context.snapshots.stored == before.regs[30]; break;
    case LDPPOST: result.original_instruction = after.regs[30] == 0x9001 && after.regs[19] == 0x9002
            && after.sp == before.sp + 16; break;
    }
    for (unsigned i = 0; i < 32; ++i)
        for (unsigned j = 0; j < 16; ++j)
            result.simd = result.simd && before.simd[i][j] == i + 1 && after.simd[i][j] == i + 1;
    result.sp = before.sp != 0 && (before.sp & 15) == 0 && after.sp == before.sp + (context.kind == LDPPOST ? 16 : 0)
            - (context.kind == SUBSP ? 0x90 : context.kind == STRPRE ? 16 : 0);
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

// False means an installed hook could not be proven removed. All callback
// data stays static; after such a failure no further fixture is installed.
static bool run_case(CaseContext& context, idoly_machine_case_report_t& value, void* instruction) {
    unsigned char original[16];
    memcpy(original, instruction, sizeof(original));
    context.hits = 0;
    context.context_ok = true;
    void* stub = shadowhook_intercept_instr_addr(instruction, intercept, &context,
            SHADOWHOOK_INTERCEPT_WITH_FPSIMD_READ_WRITE);
    value.install_errno = shadowhook_get_errno();
    value.installed = stub != nullptr;
    if (stub == nullptr) return memcmp(instruction, original, sizeof(original)) == 0;
    uint32_t first;
    memcpy(&first, instruction, sizeof(first));
    value.neighbors = (first & 0xfc000000u) == 0x14000000u
            && memcmp(static_cast<unsigned char*>(instruction) + 4, original + 4, 12) == 0;
    if (!value.neighbors) {
        value.unintercept_result = shadowhook_unintercept(stub);
        return value.unintercept_result == 0 && memcmp(instruction, original, sizeof(original)) == 0;
    }
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
    if (value.unintercept_result != 0 || memcmp(instruction, original, sizeof(original)) != 0) return false;
    unsigned previous_hits = context.hits;
    execute(context);
    value.unintercept = state_ok(inspect(context)) && context.hits == previous_hits
            && memcmp(instruction, original, sizeof(original)) == 0;
    return value.unintercept;
}

static bool case_ok(const idoly_machine_case_report_t& value) {
    return value.baseline && value.installed && state_ok(value) && value.callback_context
            && value.callback_hits && value.unintercept && value.neighbors && value.install_errno == 0 && value.unintercept_result == 0;
}

// Ordinary-only API. The historical full BL guard is immutable in the c814 phone checker.
static idoly_machine_ordinary_report_t ordinary_report;
static CaseContext ordinary_contexts[IDOLY_ORDINARY_CASE_COUNT];
static unsigned ordinary_state, ordinary_baseline_state;
extern "C" bool idoly_phase_machine_baseline_ordinary(void) {
    unsigned expected = 0;
    if (!__atomic_compare_exchange_n(&ordinary_baseline_state, &expected, 1, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        if (expected != 2) return false;  // Do not read a baseline report still being written.
        bool ok = true;
        for (const auto& value : ordinary_report.cases) ok &= value.baseline;
        return ok;
    }
    const Kind kinds[] = {ADD, MOV, LDR, LDP, SUBSP, STRPRE, LDPPOST};
    bool baselines = true;
    for (unsigned i = 0; i < IDOLY_ORDINARY_CASE_COUNT; ++i) {
        ordinary_contexts[i].kind = kinds[i];
        auto& value = ordinary_report.cases[i];
        value.install_errno = value.unintercept_result = -1;
        execute(ordinary_contexts[i]);
        value.baseline = state_ok(inspect(ordinary_contexts[i]));
        baselines &= value.baseline;
    }
    __atomic_store_n(&ordinary_baseline_state, 2, __ATOMIC_RELEASE);
    return baselines;
}
extern "C" bool idoly_phase_machine_check_ordinary(void) {
    unsigned expected = 0;
    if (!__atomic_compare_exchange_n(&ordinary_state, &expected, 1, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
        return expected == 2 && ordinary_report.ok;
    ordinary_report.attempted = true;
    void* instructions[] = {reinterpret_cast<void*>(idoly_machine_instruction_add),
        reinterpret_cast<void*>(idoly_machine_instruction_mov), reinterpret_cast<void*>(idoly_machine_instruction_ldr),
        reinterpret_cast<void*>(idoly_machine_instruction_ldp), reinterpret_cast<void*>(idoly_machine_instruction_subsp),
        reinterpret_cast<void*>(idoly_machine_instruction_strpre), reinterpret_cast<void*>(idoly_machine_instruction_ldppost)};
    if (idoly_phase_machine_baseline_ordinary()) {
        void* rejected = shadowhook_intercept_instr_addr(nullptr, intercept, &ordinary_contexts[0],
                SHADOWHOOK_INTERCEPT_WITH_FPSIMD_READ_WRITE);
        int rejected_errno = shadowhook_get_errno();
        bool removed = rejected == nullptr || shadowhook_unintercept(rejected) == 0;
        execute(ordinary_contexts[0]);
        ordinary_report.hook_failure_fail_open = rejected == nullptr && rejected_errno != 0
                && state_ok(inspect(ordinary_contexts[0])) && ordinary_contexts[0].hits == 0;
        ordinary_report.ok = ordinary_report.hook_failure_fail_open;
        if (removed) {
            for (unsigned i = 0; i < IDOLY_ORDINARY_CASE_COUNT; ++i) {
                bool removed_one = run_case(ordinary_contexts[i], ordinary_report.cases[i], instructions[i]);
                ordinary_report.ok &= case_ok(ordinary_report.cases[i]);
                if (!removed_one) { ordinary_report.ok = false; break; }
            }
        } else ordinary_report.ok = false;
    }
    __atomic_store_n(&ordinary_state, 2, __ATOMIC_RELEASE);
    return ordinary_report.ok;
}
extern "C" const idoly_machine_ordinary_report_t* idoly_phase_machine_ordinary_report(void) { return &ordinary_report; }
