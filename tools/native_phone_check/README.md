# Small native phone checker

This synthetic-only Android app shows the full strict ADD/BL preservation report in Korean, with selectable text and a Copy button. It requests no permissions and contains no game or account code. The original c814 common guard is loaded from Git by exact revision and SHA-256, so future production probe changes cannot change this comparison fixture.

Build with `python tools/native_phone_check/build.py --help` and the pinned ShadowHook 2.0.1 AAR, NDK 26.3.11579264, SDK 34 and JDK 21. The builder verifies ARM64-only libraries, 16 KiB alignment, source provenance and the existing public diagnostic development certificate. Native runtime behavior must be checked on the phone; a successful build does not claim a successful intercept.

The manual **Build small native phone checker** workflow builds these three new files: `IdolyPride-Native-SelfTest-Android-arm64.apk`, its `.apk.evidence.json`, and `NativeSelfTest-SHA256SUMS`. Its optional `publish_fixture` input adds them to `local-diagnostics-v0.2.0` without replacing any existing assets.
