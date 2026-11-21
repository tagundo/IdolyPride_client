# Real Android MP4 Save UI fixture

This separate development APK compiles the unchanged production Java save
controller, completed-output registry and document history. A tiny JNI fixture
supplies session status; it never loads the game, native capture, EGL transport
or an encoder. The bundled 1,559-byte MP4 is a complete synthetic one-frame H.264
file (32 × 32 pixels, one second), independently checked with FFprobe at build.

The device driver uses fresh Android UI-tree bounds for every tap. It verifies
that completion launches no document picker, an explicit production Save tap
opens actual Android DocumentsUI, Back cancels without consuming the private
source, Activity recreation keeps Save reachable, and a new process after
`am force-stop` restores the same source and completed inventory. It repeats the
actual Save/cancel interaction after recreation and cold restart, and checks the
production bounded document history and actual resolved launch component.
During the second real DocumentsUI visit the QA Activity schedules its own real
`recreate()`. The gate requires the framework Bundle to contain the pending target,
the recreated production controller to retain that target while DocumentsUI stays
open, and cancellation to return to a saveable completed file without reopening.

```sh
python -B tools/build_android_mp4_save_qa.py --output-directory /tmp/save-ui-proof --android-sdk "$ANDROID_HOME"
python -B tools/build_android_mp4_save_qa.py --run-device --serial emulator-5554 \
  --output-directory /tmp/save-ui-proof --android-sdk "$ANDROID_HOME"
```

SDK/build-tools 34, NDK 26.3.11579264, JDK 21 and FFprobe are required. CI adds
`--require-committed`. The runner clears only the standalone QA package on initial
launch. Its later force-stop retains all QA files and preferences, and it requires
a new PID, matching source receipts, ordinary app UID, an `untrusted_app` SELinux
domain and independent `getenforce=Enforcing` before and after. Missing or failed
required steps fail the run; no permission bypass or unsupported pass exists.
Each actual process configures a different broker/exports directory. The cold
phase must recover the original source from the old directory, so re-registering
the new native output directory cannot stand in for durable registry recovery.

A successful build alone is not runtime proof. A UI pass is explicitly scoped to
the synthetic fixture's Save lifecycle; it does not prove actual game MV output,
video capture or encoding. Local development may compile this APK without an
available Android target; only a completed device report can claim the UI pass.
