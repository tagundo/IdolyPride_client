This disposable fixture tests ShadowHook 2.0.1 ARM64 instruction interception.
It includes no game binaries, credentials, server state or production client.

`checkpoint.S` creates known GPR and SIMD state, snapshots every x0–x30 and
q0–q31 plus SP/NZCV/FPCR/FPSR, and executes an intercepted `add x0,x0,#7`.
The interceptor leaves its CPU-context argument unchanged while deliberately
clobbering live caller-saved registers, SIMD registers and floating-point flags.
Android's reserved x18 is retained and compared, never assigned a sentinel.
The second snapshot checks the ADD executed and all other state survived.
The output-pointer x28 is deliberately advanced by exactly 800 bytes outside
the intercepted instruction; the comparison accounts for that adjustment.

The test also checks an uninstrumented baseline, rejected null-address install
followed by normal execution, three interceptor callbacks, and execution after
unintercept. The JSON contains only fixed booleans and version strings, without
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
