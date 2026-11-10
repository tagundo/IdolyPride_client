# Synthetic Android environment probe

This is a standalone, ARM64-only Android APK. It contains no game code, SDK, account data or INTERNET permission. It does not modify the game. It is intentionally debuggable so the QA driver can retrieve its private JSON via `run-as`.

## Checks

1. Create a 16x16 EGL pbuffer with an OpenGL ES 3 context; record vendor, renderer, version and vertex/fragment uniform-vector limits.
2. Compile/link two programs that each use every element of `uniform vec4 u[300]`, once in the vertex shader and once in the fragment shader. Query the linked active vec4 array size; a driver success requires **300**, not merely compiler success.
3. Persist `graphics_complete`, then `conversion_begin`, to private `files/report.json` using fsync + rename. This preserves the graphics report if the next instruction kills the process.
4. Execute the exact original-game ARM64 opcode `0x5ea1b821` (`FCVTZS S1,S1`), then `SCVTF S1,S1`, with 3.75 and -3.75. Expected results are 3 and -3. There is no instruction emulation, fallback, patch or SIGILL handler. Unsupported translation should crash and remain visible in the process/crash logs.
5. Persist `complete` and write the same bounded JSON line to fixed `IdolyEnvironmentProbe` log tag. On-screen JSON is scrollable/selectable. Shader info logs are bounded to 127 bytes each; GL strings/JSON escaping are bounded.

Package: `org.idolypride.environmentprobe`; activity: `.ProbeActivity`.

```sh
python -m unittest discover -s tools/emulator_environment_probe -p test_driver.py -v
python tools/emulator_environment_probe/build.py \
  --sdk "$ANDROID_HOME" --ndk "$ANDROID_HOME/ndk/26.3.11579264" \
  --java "$JAVA_HOME/bin" --output /new/output/probe.apk
python tools/emulator_environment_probe/run_probe.py \
  --apk /new/output/probe.apk --output /new/output/runtime --serial emulator-5554
```

`build.py` accepts explicit `--sdk`, `--ndk`, `--java` directories and refuses to overwrite the APK. Android SDK/JDK environment variables are supported; no workspace path is assumed. The Linux builder uses SDK/build-tools 34, NDK 26.3, Java 21 targeting Java8, D8, aapt2, 16KiB ELF/ZIP alignment and a fresh disposable signing key inside the temporary build directory. The key is deleted after building, so reinstalling a later build over an existing differently signed probe may require uninstalling this synthetic probe first. No APK, native library or signing key belongs in source control.

The builder verifies the exact instruction bytes, ARM64-only native inventory, no permissions, signatures, source hashes and packaged provenance. The APK's `.evidence.json` records all hashes and explicitly marks `runtime_verified=false`; only a separate Android execution report can establish runtime compatibility. `run_probe.py` passes only when the complete report includes successful conversion and **both** linked 300-element uniform arrays. Context creation or a claimed GL limit alone cannot pass. `--record-root` separately records `adb root` and `whoami`; root access is not a graphics/CPU pass requirement and does not repair unsupported instructions or shaders. This checks ADB daemon root, not every emulator's separate `su` mechanism.

## API35 environment comparison

The manual [probe-game-emulator workflow](../../.github/workflows/probe-game-emulator.yml) compares the current API35 `google_apis` x86_64 image with two officially documented Android Emulator GPU modes: `host` backed by Mesa llvmpipe under Xvfb, and `lavapipe`. It records the actual host GL renderer, emulator version, Android image revision and native-bridge library hash. It does not download or launch the game/server. A candidate passing this small probe still needs actual game Home/menu validation; other CPU instructions, URP features and performance remain untested.

Android documents [`host` and `lavapipe`](https://developer.android.com/studio/run/emulator-acceleration); Mesa documents [`LIBGL_ALWAYS_SOFTWARE` and `GALLIUM_DRIVER=llvmpipe`](https://docs.mesa3d.org/envvars.html). No `MESA_GL_VERSION_OVERRIDE`, shader modification, Burst patch, instruction fallback or fake graphics capability is used.

## Local validation performed

Actual NDK compile with `-Wall -Wextra -Werror`, javac/D8, aapt2 inventory, apksigner verification and ZIP/ELF 16KiB alignment all passed. A separate Unicorn check of the exact compiled five-instruction ARM64 function passed positive, negative and zero inputs; this verifies fixture arithmetic only and **is not** an Android emulator translation/device test. This workspace has no connected ADB target, so no Android graphics or instruction compatibility success is claimed here.
