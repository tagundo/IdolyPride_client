This disposable fixture tests ShadowHook 2.0.1 ARM64 instruction interception.
It includes no game binaries, credentials, server state or production client.

The version 2 fixture calls the same ordinary-only guard as production. It
covers seven instructions: ADD, MOV, scalar LDR, pair LDP, SUB SP, STR LR with
pre-index stack allocation and LDP LR/register with post-index stack release.
Every case snapshots all x0–x30, q0–q31, SP, NZCV, FPCR and FPSR. The comparison
allows only the specific instruction's documented register, SP and memory
effects. Android's reserved x18 remains unchanged. The output-pointer x28 is
advanced exactly 800 bytes outside the intercepted instruction.

The wrapper runs all seven baselines before ShadowHook initialization. It then
captures numeric initialization result/errno immediately and, if init succeeds,
runs rejected-address fail-open and three callbacks per case, each with an
unchanged CPU context and deliberately clobbered live caller/SIMD/flag state.
Every install must overwrite only one word with B and preserve the neighboring
twelve bytes. Every removal must restore all sixteen bytes and normal execution.
The production preflight is one-shot; any failure prevents every game hook.
Callbacks and snapshots have static storage even if removal fails.

Schema 2 reports `scope: ordinary-v2`, initialization/attempted/fail-open status,
and seven named `cases`, each with every CPU, instruction-effect, callback,
neighbor, cleanup flag and numeric status. The driver requires every flag true
and all numeric statuses zero. A native bridge that declines initialization
still exposes the seven baseline results, but does not prove interception.

The older strict ADD/BL comparison remains available in the immutable c814
phone checker under `tools/native_phone_check/`. BL replay was shown to change
LR through the pinned library's trampoline; production version 2 forbids all
BL/control/PC-relative sites rather than allowing that register difference.

Build with installed SDK/NDK/JDK tools (NDK 26.3.11579264 is required):

```sh
python android-diagnostics/native/selftest/build_apk.py \
  --output data/clients/arm64-interceptor-selftest.apk \
  --shadowhook-aar /path/to/shadowhook-2.0.1.aar \
  --ndk "$ANDROID_NDK_HOME" \
  --build-tools "$ANDROID_HOME/build-tools/34.0.0" \
  --android-jar "$ANDROID_HOME/platforms/android-34/android.jar"
```

The AAR must match SHA-256
`2cad01ff4d59542958775e19f281981a7e84b39670b5fae75905b8511e10c7cd`.
The fixture links the same ShadowHook library as production; it is third-party
code distributed under MIT; see [the pinned license](../SHADOWHOOK-LICENSE).
The builder neither downloads dependencies
nor runs a game. Its evidence explicitly says runtime verification has not run.

Execute only on a disposable ARM64-capable emulator:

```sh
python android-diagnostics/native/selftest/run_emulator.py \
  --apk data/clients/arm64-interceptor-selftest.apk \
  --serial emulator-5554 --artifacts data/qa/arm64-interceptor
```

The driver rejects physical devices and non-ARM64 emulator images. It replaces
only its own `game.qualiarts.idolypride.phase_selftest` installation, launches
the visible Activity, reads the fixture's private JSON using `run-as`, checks
every boolean, and stops its process. An x86 emulator may run it only when its
ABI list advertises ARM64 through a native bridge; record that distinction when
reporting results. This permits testing an advertised ABI, not a compatibility
claim: upstream documents unsupported architectures including Houdini in
errors 34/35, so translated execution can fail. A built APK alone does not
verify runtime preservation.

On failure the driver retains only fixture-scoped logcat and package exit data.
If the UID/time-filtered log is empty, it retries all tags and buffers with both
the fixture PID and UID, without the timestamp filter. A readable `/proc/PID/status`
is checked to reject a PID reused by another UID. Environment evidence normalizes
the public native-bridge property to `libndk_translation.so`, `libhoudini.so`,
`none` or `other`; it never preserves arbitrary property text.
