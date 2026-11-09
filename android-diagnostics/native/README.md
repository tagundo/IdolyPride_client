# Native phase observations

This optional ARM64 library records sixteen fixed instruction checkpoints in the
pinned Android 6.1.1 client. It never reads managed objects, arguments, strings,
authentication metadata, or a state machine after its original method returns.
It never changes an interceptor register context or replaces a game task/result.
Each checkpoint is emitted once per process as `Unity: IDOLY_PHASE:<fixed code>`.

`NativePhaseProbe.start()` is a safe, idempotent Java entry point. A background
worker waits for the Unity and IL2CPP ELF mappings, then delays another
500 ms before initializing ShadowHook. It validates the ELF build ID, executable
mapping ranges, and **all sixteen 16-byte windows before installing any hook**.
A timeout or missing library produces `probe_unavailable`; profile,
initialization, preflight and installation failures have distinct fixed codes. Before reading ELF headers or instruction
windows, the worker pins the exact loaded path with `RTLD_NOLOAD`, then
refreshes its mappings. The reference remains held while hooks are active.
Partial installation attempts are rolled back and every removal result is
checked. If removal fails, the ELF remains pinned and some fixed observational
callbacks may remain active after `probe_install_failed`.
An unavailable probe must not block game startup.

After ShadowHook initialization, the version 2 ordinary-instruction guard runs
seven synthetic cases before any game checkpoint is intercepted: ADD, MOV,
scalar LDR, pair LDP, SUB of SP, pre-index STR of LR, and post-index LDP of LR.
It requires all GPR/SIMD state, SP, NZCV, FPCR and FPSR, permitting exactly each
instruction's specified register, stack and memory effects. Every fixture must
pass its baseline, three callbacks, untouched-context check and removal check.
The same guard is compiled into the standalone test APK; it uses no C++ shared
runtime. A failure prevents every game hook. Callback storage remains static
if removal fails. `probe_ready` requires all seven checks and sixteen installs.

Version 2 allows only the exact reviewed ordinary instruction words. Ten
checkpoints moved four bytes before their old BL sites; the original BL remains
untouched. The pinned ShadowHook 2.0.1 ARM64 binary uses a four-byte branch island
without a wider fallback. Each actual install additionally verifies that only
the first word became a direct B and the neighboring twelve bytes stayed intact;
a mismatch triggers rollback, with all sixteen original bytes checked afterward.
BL, other control flow and PC-relative instructions are forbidden. The earlier
BL fixture exposed a trampoline link-register difference on the phone; its
strict historical comparison is retained in the separate immutable c814 phone
checker. No assertion about ordinary CPU preservation has been weakened.

ShadowHook's instruction intercept API executes the original instruction after
the callback. The `SHADOWHOOK_INTERCEPT_WITH_FPSIMD_READ_WRITE` flag requests preservation of the
ARM64 general register context, SP, PC, PSTATE, q0–q31, FPSR and FPCR. Our callback
does not access that context and calls only the Android public log API with a
fixed string. The game ELF on disk, metadata, original DEX files, and FastAES are
preserved; the APK adds three ARM64 libraries and one additional DEX.

These signals mean **an instruction was reached**, not that an operation
succeeded or that the home screen is visible. In particular:

- `shader_completion_flag` observes the cleanup callback after setting its flag;
  cleanup can also happen on an error.
- `background_load_returned` precedes subsequent environment callbacks.
- `front_loading_finished` observes return from `FinishLoading`; the later
  `ShowInAsync` await has its own `home_show_in_returned` checkpoint.
- `actor_motion_wait` observes acquiring a joined task's awaiter, not suspension.

The exact windows and meanings are in `phase-profile.json`. Do not reuse these
addresses with another client build. The packager also requires the exact known
6.1.1 offline-bootstrap native SHA-256 before adding this library.

ShadowHook 2.0.1 is downloaded from Maven Central with a fixed SHA-256. The build
uses NDK 26.3.11579264, API 28, ARM64 only, with 16 KiB ELF and APK alignment.
The old ADD case passed on a physical ARM64 phone. All seven new uninstrumented
fixtures passed ARM64 Unicorn execution; the new complete device guard runs on
each phone before game instrumentation. These results do not claim that all
seven new interceptors or the game startup have passed on hardware. Upstream documents a
native crash-handler ordering risk when ShadowHook initializes before other
crash SDKs; the deferred worker reduces early startup interference but is not a
guarantee. The prior Java-only diagnostic APK remains a separate fallback.

```bash
.venv/bin/python android-diagnostics/native/build_native.py \
  --output data/diagnostic-native --ndk /path/to/26.3.11579264
```

The synthetic `selftest/` uses no game or account data. It verifies preservation
of machine state and execution of an intercepted instruction on a real ARM64 or
supported translated ARM64 emulator. Host compilation alone is not that proof.

ShadowHook is MIT licensed; see `SHADOWHOOK-LICENSE` and upstream's third-party
notices at https://github.com/bytedance/android-inline-hook/tree/v2.0.1 .
