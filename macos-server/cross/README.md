# SDK-free Mac cross-build

The normal `macos-server/build_app.py` uses SwiftUI and a Mac runner. This
fallback builds a native ARM64 AppKit launcher with Clang/LLD on Linux. It
reuses the byte-identical, previously packaged CPython 3.12.10 Darwin runtime;
exports its dependency PYZ bytecode without recompilation; excludes the old
application modules; and includes the current backend Python sources. No user
Python installation or terminal command is required.

`main.c` dispatches `--engine` to the embedded Python interpreter. The GUI
launches that same executable and exchanges the existing bounded JSON-control
protocol. Server data, profiles, media state, and presentation preferences use
the same application-support location as the SwiftUI app. Mac resources use
the separately preserved iOS Octo catalog.

Run with CPython 3.12, pinned public inputs, cached NDK 26.3.11579264 Clang/LLD,
and official apple-codesign 0.29.0 Linux `rcodesign`:

```sh
python macos-server/cross/build_app.py \
  --source-commit COMMITTED_SOURCE_SHA \
  --runtime RETAINED_030_APP_ZIP --payload MAC_SERVER_DATA_ZIP \
  --llvm CACHED_NDK_LLVM_BIN --rcodesign VERIFIED_RCODESIGN \
  --app TMPFS/IdolyPrideLocalServer.app \
  --archive OUTPUT/IdolyPride-Local-Server-macOS-arm64.app.zip \
  --evidence OUTPUT/evidence
```

Inputs and source bytes are checked before export. The app/payload staging
paths must share a filesystem for a hard link. Compiler/linker/signing calls
run sequentially at nice 19, one CPU, a 512 MiB address-space cap, and bounded
timeouts. Ad-hoc outer signing preserves all reused runtime and payload bytes.
The output contains a resource seal and an artifact/provenance report. No
private signing key, Apple account, Go rebuild, or SDK download is used.

Cross-linking and signature verification do **not** establish successful
execution on macOS. Reports explicitly record `actual_mac_execution: false`;
launch/start/stop and rendering still require a real Apple Silicon Mac.
