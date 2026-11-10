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

## Separate packaging inputs

`tools/package_qa_ui_client.py` keeps the existing `diagnostic-aes` profile as
its default. That profile still requires the audited software-AES/no-store
intermediate and its matching `--qa-aes-report`; it is not an original-client
baseline. It retains `game.qualiarts.idolypride.local.diagnostics`.

The explicitly selected `normal-local` profile instead requires the published
normal local APK (release asset `726978000`, SHA-256
`28ecc6a617867d0842a5e88eac3d5736199809a49d4d433ce47816d6a40ba77b`).
It rejects diagnostic reports and prior QA markers, verifies the published
certificate and exact original FastAES/Unity bytes, normal IL2CPP/metadata and
four existing top-level DEX files. This input already has the local endpoint
and six authentication bootstrap patches; it is not the untouched game. The
UI packager adds no further bootstrap, AES, store, graphics or game-code changes.

For example, after building this library and providing SDK/JDK/APKEditor:

```sh
uv run --locked python tools/package_qa_ui_client.py data/clients/Game-r2-pinned.apk \
  --input-profile normal-local \
  --expected-source-sha256 28ecc6a617867d0842a5e88eac3d5736199809a49d4d433ce47816d6a40ba77b \
  --native-library scratch/ui-native/lib/arm64-v8a/libidoly_qa_ui_bridge.so \
  --apkeditor /path/to/APKEditor.jar --build-tools "$ANDROID_HOME/build-tools/34.0.0" \
  --android-jar "$ANDROID_HOME/platforms/android-34/android.jar" \
  --emulator-only --output scratch/normal-local-ui-qa.apk
```

The new QA copy keeps `game.qualiarts.idolypride.local`, uses the fixed
nonexported authority `game.qualiarts.idolypride.local.qa.ui`, becomes debuggable,
and receives an ephemeral QA signature. All input ZIP members other than the
manifest/signatures are checked unchanged. The source APK is never overwritten.
The appended marker/report identify the selected input profile and preserved
member hashes. Runtime activation requires the matching package/profile marker,
the pinned normal input hash, and both existing emulator guards; the original
production package is never allowed. This preparation is not device validation.

A later emulator run can use the current host Python server with a fresh
synthetic `sandbox` profile and the prepared payload directory, then reverse
both services with `adb reverse tcp:50051 tcp:50051` and
`adb reverse tcp:8080 tcp:8080`. This avoids depending on Android server-app
packaging for testing the current backend. The UI listener remains loopback-only
on port 50052 with its existing temporary private token and expiry. Read that
token only in memory through the disposable app's `run-as`; do not put it into
logs, build reports or artifacts. No workflow is enabled by this packaging step.

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

TMP node text uses virtual `TMP_Text.GetParsedText()`, which copies the current
`m_textInfo.characterInfo` render characters into a new string without writing
TMP instance fields. The client's `TMP_Text.text` getter is unsuitable for a
repeated observer: its first read consumes the backing-string dirty flag but
leaves `m_text` at the serialized value, so later reads can return stale text.
For example, the first actual snapshot read `version.6.1.1` and later reads of
the same component returned its serialized `version.0.2.0` while the screen
still displayed 6.1.1. Parsed text omits formatting markup and reflects the
last parsed render text; it can be empty before the first text layout. Standard
`UnityEngine.UI.Text` continues to use its text getter.

Each Qua button additionally reports `callback_registered: true|false|null`.
It reads only whether the existing `onClickedCallback` delegate reference is
non-null. It does not invoke or identify delegate targets, and `true` alone
does not prove which listener is registered or whether Android input reached it.

Snapshots include this bounded, nonsecret startup state:

```json
{"startup_observation":{"title_presenters":[{"instance_id":42,"is_initialized":false,"title_button_id":-123}],"solis_initialization_succeeded":false,"click_interceptor_present":true,"input_releasing":false,"content_blocking":false,"unavailable":[]}}
```

Title presenter fields use typed metadata field APIs, including a checked
one-byte Boolean and checked reference fields, with no hardcoded object offsets.
The active presenter list is capped at eight. Unavailable values are `null` and
their fixed field keys appear in `unavailable`; an enumeration failure produces
`title_presenters:null`, rather than an empty list implying absence.

`is_initialized` means that presenter's initialization await succeeded; it is
separate from click listener registration. `solis_initialization_succeeded`
reads the existing public `SolisInitializer.IsSuccess` getter. The installed
Solis click interceptor is normally present even when input is allowed, so its
presence must not be interpreted as blocking. `input_releasing` reads the
existing active EventSystem's `m_CurrentInputModule` and, when it is a
SolisInputModule, its Boolean `IsReleasing` backing field. Zero or multiple
active EventSystems produce unavailable, not an assumed value. No delegate,
`EventSystem.current`, or static `SolisInputModule` method is invoked: the
latter's managed static constructor performs reflection and writes a static
field, which an observer must not trigger. `content_blocking` uses the verified pure
`SolisBlockingManager.IsActive(BlockingOrder.ContentBlocking)` query (enum155),
which checks the existing counter without creating a manager or blocker.
These observations do not create purchase managers, call initialization,
invoke click callbacks, release blockers, or write game fields. A driver can
defer input on an absent callback or a known active input/content gate; an
unsuccessful initializer alone is not a reason to suppress the first title tap.

Additional nullable startup bits narrow home-loading waits:

- `shader_warmup_ended` reads the existing `IsEndShaderWarmUp` static backing
  Boolean. True means its cleanup gate was released, including cancellation or
  error cleanup; it does not prove successful shader compilation.
- `home_scene_loading` is the logical OR of `IsLoadingScene` across active,
  enabled `HomePlaceEnvironmentPresenterBase` instances. No active instance,
  an oversized enumeration, or any read failure is unavailable. False describes
  those observed flags and does not prove the entire home scene is ready.
- `home_enter_called` reads `CalledHomeEnter` through the one active
  HomeTopScreenPresenter's existing model. Zero or multiple active presenters,
  a missing model or an invalid field is unavailable. True marks entry into
  Home.Enter response handling, before later UI binding and actor setup.
- `purchase_initialized` reads `UnityPurchaseManager.IsInitializeSucceeded`
  only through the already existing closed generic manager's static `_instance`
  and instance `_unityPurchaseManager` fields. Missing objects or unresolved
  generic field types are unavailable. The generic parent does have a managed
  static constructor; the verified static-field copy API does not invoke it.
  No `get_Instance`, lazy `get_UnityPurchaseManager`, store/controller creation,
  receipt handling, or purchase action is called. False is an observation, not a
  request to set the flag or a proof that it caused the home wait.

Their same fixed names appear in `unavailable` whenever the value is null.
These bits never change loading flags, complete tasks, skip tutorials, alter
SDK state, or dismiss the loading screen. `GetParsedText()` is the last parsed
render text, so placeholder labels under a hidden/loading canvas do not by
themselves establish that binding or initialization did not run.

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

## Title, notice input and frame observations

`frame_observation` reports `sample_monotonic_ms`, nullable `frame_count`,
`unscaled_delta_time` and `time_scale`, with missing field names in
`unavailable`. Values come from uniquely resolved, typed Unity `Time` getters
on UnityMain. Delta time describes Unity's most recent frame; it is not a
direct FPS measurement. Frame-count differences divided by monotonic sample
time can help compare successive observations. Sampling itself also takes time.

Only the exact observed `Canvas/TitleButton` and
`Singleton/GlobalDialog/DialogManager/NoticeDialog(Clone)/TabDialogBase/DialogCanvas/Dialog/Footer/CloseButton`
nodes receive `input_observation`. Child and similarly named paths are excluded. It contains nullable
`long_tap_time_seconds`, `suppress_long_tap_click`, `is_pressed`, `is_dragged`,
`canvas_effective_alpha`, `canvas_interactable`, `canvas_blocks_raycasts`,
`canvas_group_count`, and `unavailable` keys. The gesture is read from the
already existing `SolisButtonBase._longTapGesture` reference using checked
metadata field types. No lazy gesture getter, event handler or setter is called.
An absent gesture is unknown, not an invented default configuration.

`canvas_effective_alpha` is specifically the existing target CanvasRenderer's
`GetInheritedAlpha()` value; if the target has no renderer it remains null.
It does not claim to include every material/color/fader/culling effect.
CanvasGroup flags are read on the target transform and its ancestors, stopping
at `ignoreParentGroups`, with a 32-ancestor ceiling. No groups means known true
flags and count zero. Multiple groups on one transform have order-sensitive
ignore rules, so effective flags/count remain unavailable in that case rather
than guessing. These values do not prove the final EventSystem raycast winner,
window animation completion or Android pointer delivery. No `ready=true` value
is synthesized and the normal-input driver does not bypass a handler or gate.

New getters are checked for unique name, parameter/return kinds and static
flags before invocation. Both additional IL2CPP signature-query exports are
covered by the same ELF build-ID/address/16-byte guards, now 34 exports. The
audited getter classes have no managed static constructors. Unity engine getters
may resolve their native iCall cache on first use; this is not a claim that no
engine memory is ever written. The observer writes no managed game fields,
creates no game singleton and invokes no purchase, click or gameplay handler.
These new observations require actual emulator validation before any claim
about why the Notice close input failed.
