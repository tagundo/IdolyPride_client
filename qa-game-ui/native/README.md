# QA Unity UI snapshot

This library is added only to the synthetic-profile emulator QA APK. It leaves
the original DEX and game native libraries unchanged and uses no ShadowHook.
Java schedules its JNI call through the original
`UnityPlayer.queueGLThreadEvent(Runnable)`. The original queue is consumed by
`UnityMain` before `nativeRender`. A paused or unready player can delay or drop
the queue request, so Java must use a bounded asynchronous timeout.

Build with Linux NDK 26.3.11579264:

```sh
python qa-game-ui/native/build_native.py --output scratch/ui-native
JAVA_HOME=/path/to/jdk .venv/bin/python -m pytest qa-game-ui/native/tests/test_native.py
```

The output is `lib/arm64-v8a/libidoly_qa_ui_bridge.so` plus
`native-provenance.json`. The builder checks ARM64 and 16 KiB ELF alignment.
At runtime the library pins the already loaded IL2CPP image and verifies the
6.1.1 ELF build ID, exact exported API addresses and their 16-byte windows.
The original and bootstrap file hashes are provenance; the runtime guard does
not claim to hash the entire loaded image. The QA APK packager separately pins
the source APK and records all permitted QA adaptations.

`NativeUiBridge.nativeSnapshot()` returns ASCII JSON. Success contains:

```json
{"ok":true,"generation":1,"screen":{"width":1080,"height":1920,"origin":"top-left","units":"unity-screen-pixels"},"nodes":[{"instance_id":-123,"parent_instance_id":-100,"transform_instance_id":-101,"game_object_id":-102,"kind":"button","name":"Start","path":"Canvas/Start","text":"","active":true,"interactable":true,"bounds":[100,200,300,260],"button_type":"qua"}],"truncated":false}
```

`instance_id` is the actual component's signed Unity instance ID. Zero is
invalid; negative IDs are valid. Nodes cover active `Qua.UI.ButtonBase`,
`UnityEngine.UI.Button`, `UnityEngine.UI.Text`, and `TMPro.TMP_Text`, including
their subclasses. `parent_instance_id` identifies the actual parent Transform;
intermediate transforms may have no emitted node. `path` can join child text to
buttons using a `/` boundary. `interactable` means the Qua button's `IsEnabled`
or standard Selectable's `IsInteractable`; it does not imply absence of an
overlaid modal.

Bounds come from the actual RectTransform, root Canvas camera and
WorldToScreenPoint. They use Unity Screen pixels with a top-left origin, clipped
to the reported Screen dimensions. They are null if geometry cannot be resolved.
The driver must compare and transform these dimensions against a fresh Android
Unity SurfaceView UI-tree rectangle before issuing normal Android input. No
screenshot or OCR location is used. Normal input retains the game's modal,
interceptor, raycast, nested-handler, drag and animation behavior.

`nativeClick(instanceId, generation)` validates freshness, Unity liveness and
the enabled state, then deliberately returns
`{"ok":false,"error":"native_click_disabled_use_adb"}`. It never calls game
click handlers. Direct `Qua.UI.ButtonBase.OnClickedHandler` bypasses the game's
Solis interceptor and drag checks; even direct standard Button dispatch can
select the wrong handler for a nested target. This MVP therefore performs all
clicks through normal Android input derived from the real UI tree.

All failures return `{"ok":false,"error":"fixed_code"}` without managed
exception text. Snapshot generations replace the previous set of strong GC
handles, bounded to 512 nodes and less than 64 KiB JSON. Enumeration has an
8192-object-per-kind scan ceiling and a 500 ms cooperative budget checked
between managed calls. The native library must run on `UnityMain` with a current
IL2CPP thread. It makes no game API calls, writes no game fields, and reads no
account storage. The host tests check JSON escaping/overflow, exported API
coverage, virtual dispatch and fail-closed exception, thread, generation and
enabled-state paths. Actual Unity execution is a separate emulator CI check.
