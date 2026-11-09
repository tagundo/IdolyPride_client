#ifndef IDOLY_MACHINE_STATE_CHECK_H
#define IDOLY_MACHINE_STATE_CHECK_H
#include <stdbool.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
    bool baseline, installed, original_instruction, gpr, simd, sp, nzcv, fpcr, fpsr;
    bool link_register, callback_context, callback_hits, unintercept, neighbors;
    int install_errno;       /* -1 when installation was not attempted. */
    int unintercept_result; /* -1 when removal was not attempted. */
} idoly_machine_case_report_t;
#define IDOLY_ORDINARY_CASE_COUNT 7
typedef struct {
    bool attempted, ok, hook_failure_fail_open;
    idoly_machine_case_report_t cases[IDOLY_ORDINARY_CASE_COUNT];
} idoly_machine_ordinary_report_t;
/* Version 2 admits only ordinary instructions, never BL/control/PC-relative.
 * Checks ADD, MOV, scalar LDR, pair LDP, SUB SP, pre-index STR, post-index LDP.
 * All CPU-state assertions remain required, allowing only each instruction's
 * documented register/SP/memory effects. Baseline may run before initialization;
 * the complete check requires successful ShadowHook init. Cached, one-shot. */
bool idoly_phase_machine_baseline_ordinary(void);
bool idoly_phase_machine_check_ordinary(void);
const idoly_machine_ordinary_report_t* idoly_phase_machine_ordinary_report(void);
/* Read report on the calling thread after baseline/check returns. Static lifetime. */
#ifdef __cplusplus
}
#endif
#endif
