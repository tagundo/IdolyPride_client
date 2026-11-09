This disposable fixture tests ShadowHook 2.0.1 ARM64 instruction interception.
It includes no game binaries, credentials, server state or production client.

The shared `../checkpoint.S` and `../machine_state_check.cpp` are compiled
unchanged into both production and this fixture. They create known GPR and
SIMD state, snapshot every x0–x30 and q0–q31 plus SP/NZCV/FPCR/FPSR, and test
both an intercepted `add x0,x0,#7` and a direct `bl` to a local ADD7/RET callee.
The interceptor leaves its CPU-context argument unchanged while deliberately
clobbering live caller-saved registers, SIMD registers and floating-point flags.
Android's reserved x18 is retained and compared, never assigned a sentinel.
The second snapshot checks ADD7 executed and all other state survived. The BL
case additionally requires x30 to equal the original BL instruction address
plus four after return, rather than a trampoline return address.
The output-pointer x28 is deliberately advanced by exactly 800 bytes outside
the intercepted instruction; the comparison accounts for that adjustment.

The test checks both uninstrumented baselines, rejected null-address install
followed by normal execution, three callbacks per instruction, and execution
after both successful unintercepts. Shared callback contexts and snapshots have
static lifetime even if cleanup fails. The production preflight is one-shot and
returns true only after every check and both removals pass; subsequent calls
use the cached result. It never initializes ShadowHook or calls game methods.
The standalone wrapper runs shared baselines before initialization so an init
failure remains distinguishable from a baseline failure. It captures numeric initialization result and TLS errno immediately
after initialization, before the deliberately invalid install overwrites errno.
`install_errno` is `-1` when initialization prevented installation. The JSON
contains only fixed booleans, numeric API statuses and version strings, without
register values, memory addresses, stack contents or application data.

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
