# Android queue storage proof

This small signed development APK loads only its JNI probe and the current
production `client-presentation/native/mp4_queue.hpp`. It does not load the game.
The JNI calls execute inside the Activity's ordinary app UID and `untrusted_app`
SELinux domain, using fresh app-private directories with mode 0700. `adb run-as`
only collects the final bounded JSON report.

Build with SDK platforms/build-tools 34 and NDK **26.3.11579264** installed:

```sh
python -B tools/build_android_queue_qa.py --output-directory /tmp/queue-proof --android-sdk "$ANDROID_HOME"
python -B tools/build_android_queue_qa.py --run-device --serial emulator-5554 \
  --output-directory /tmp/queue-proof --android-sdk "$ANDROID_HOME"
```

A physical Android device serial can be used in place of `emulator-5554`. Running
clears only this probe package's data. CI adds `--require-committed` to both commands.

The seven required cases prove a legacy `linkat` call fails with the actual
EPERM/EACCES errno, the production no-replace install preserves an existing
target and installs a new single-link file, the production Queue survives first
and replacement enqueue/reopen, an unexpected journal is preserved, journal and
lock symlinks are rejected, and tampering is rejected both during an open session
and after reopen. Unsupported or missing cases fail the run.

The runner requires enforcing SELinux before and after the run, native and Java
UID/PID agreement with the package UID, the compiled source hashes, a fresh
challenge, and every detailed case result. It never roots the device or changes
SELinux policy. If the app cannot read `selinuxfs/enforce`, it reports the exact
EPERM/EACCES errno and a null native enforcing value. The host must still attest
`getenforce=Enforcing` both before and after the cases; an unavailable native read
never becomes a claim that the app observed enforcing. Other read failures fail.
`build-report.json` alone is explicitly **not** a runtime pass.
`runtime-report.json` records the terminal gate result. These checks do not prove
game rendering, UI queue admission, or MP4 encoding. The runner also attempts
optional UI-tree/screenshot capture while the probe is visible and retains only
the probe's own PID-filtered logcat. Missing optional captures do not change the
storage gate result.
