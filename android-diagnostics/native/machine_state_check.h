#ifndef IDOLY_MACHINE_STATE_CHECK_H
#define IDOLY_MACHINE_STATE_CHECK_H
#include <stdbool.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
    bool baseline, installed, original_instruction, gpr, simd, sp, nzcv, fpcr, fpsr;
    bool link_register, callback_context, callback_hits, unintercept;
    int install_errno;       /* -1 when installation was not attempted. */
    int unintercept_result; /* -1 when removal was not attempted. */
} idoly_machine_case_report_t;
typedef struct {
    bool attempted, ok, hook_failure_fail_open;
    idoly_machine_case_report_t add, bl;
} idoly_machine_report_t;
/* Synthetic-only baselines; no ShadowHook initialization or interception. */
bool idoly_phase_machine_baseline(void);
/* Call after successful shadowhook_init. One-shot, fail-closed, no game data. */
bool idoly_phase_machine_check(void);
/* Read on the calling thread after baseline/check returns. Static lifetime. */
const idoly_machine_report_t* idoly_phase_machine_report(void);
#ifdef __cplusplus
}
#endif
#endif
