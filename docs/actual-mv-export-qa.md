# Actual MV export QA

`verify-actual-mv-export.yml` never creates a release. Its own definition push
registers and tests the workflow; subsequent runs are dispatched manually
at the exact source commit and pass the same 40-character commit in
`expected_source`. The runner builds the normal unified APK, verifies its
complete producer/native-source receipts, then appends the emulator-only QA
observer. Original SDK, AES, Unity and existing game members remain unchanged.

The official Google API35 x86_64 image supplies its own ARM translation library.
The GPU is Lavapipe with its reported limits preserved. A separate ARM/GLES
probe checks the environment first; its success cannot pass the game test.
The original SDK/AES path must actually launch. Failure to reach usable Home or
the normal Photography 3D MV is retained as a failed or blocked run, with no
automatic adapted-game fallback.

Every action uses a fresh observed Android or Unity UI control and ordinary
touch/keyboard input. The read-only `/mp4-status` endpoint returns cached native
observations; it does not call Unity getters, evaluate a timeline or start an
export. The native status also contains cached per-part admission diagnostics
(Actor, Camera, Stage and World), collected on the Unity thread at most four
times per second while idle. Collecting these codes cannot enable an unfinished
render pipeline or count as a rendering pass. Its bearer token is read from the fresh app's private files into memory
and is excluded from artifacts.

The driver opens **Idols → Photography / Viewing → Live → Bittersweet Echo →
View** and observes a real normal 3D source with an advancing PlayerLoop and
timeline. IDOLY PRIDE has no user-facing Pause button during this MV; the driver
does not search for or require one. The exporter itself saves the actual source
state and acquires its internal held clock before stepping frames. During export
the driver uses the actual native export overlay's
Pause and Resume controls while the Unity surface remains foreground. A paused
acknowledgement must hold the simulation tick, accepted-frame count and timeline
time while native PlayerLoop entries advance. Resume must advance the owned
simulation clock.

Completion separately requires verified scene admission, capture acknowledgements
for every scheduled frame, exact render and encoded dimensions, rational PTS,
decoded frame count, stereo AAC duration, non-silent decoded audio and changing
decoded visual samples. Source identity, pause position, clock settings,
camera/audio and dependent state must all be verified restored. Cleanup alone
cannot satisfy restoration. The actual DocumentsUI cancel/return flow must retain
the completed movie and Save button, and a subsequent actual Save must produce
the same public-file SHA-256 as the private completed movie.

The actual job render dimensions remain in the native observation after the
live camera target is restored; idle readiness dimensions are not substituted
for that evidence. A native source-state checkpoint is recorded before normal
playback continues. An originally paused source must still hold that position;
an originally playing source may advance after the verified checkpoint.

Both direct and queued exports use the native job's actual acquired source
identity/time/play-state snapshot as the restoration baseline. A normally
playing MV may advance while the user opens the server menu and changes output
settings, so its earlier UI observation is not the acquisition timestamp. A
direct export must retain that same source identity. A queued replay may
construct a new player and must use its new actual acquisition snapshot.

The landscape 30fps case then adds and exports one queued MV. Add must persist
the queue entry without hiding the server menu. The square 60fps case
independently verifies direct export at another
aspect ratio. A shared deadline bounds all exports in each case.

Both cases set a custom 0.5 Mbps video bitrate through the actual autosaving UI
to keep full-song evidence small. Packet probing collects only timing fields;
full decoding and audio checks still process the entire actual movie.

Small proof artifacts include source receipts, phase snapshots, UI trees,
screenshots, decoded samples, scoped logs and `runtime-report.json`. Bounded real
movies are retained separately. Runner transport APKs are private short-lived
artifacts and are not downloaded into the agent workspace. A successful evidence
upload is not a functional pass: the driver exits nonzero unless every required
runtime gate passes.

These results cover the actual game inside the specified translated software
guest. They do not establish physical-device speed, display color accuracy,
long-term thermal behavior, background execution, or iOS device rendering.

## Latest observed boundary, 2026-11-22

Run `44981305568` uses exact source
`0f7c0a5bd6b9847fec2f33011cab81edf718fad7`. The normal producer and packaging
job passed. Its square-case runtime proof shows that the app Main Activity was
created and resumed, but every observed Android UI tree was obscured by the
system dialog **Pixel Launcher isn't responding**. The foreground Activity
under that overlay was the Android notification permission controller. The
driver did not close this unrelated ANR, infer a launcher button behind it, or
count the permission Activity as the game launcher. It timed out before a
usable Home or MV could be observed.

The same proof separately retains Shadowhook initialization errno 12
(`INIT_LINKER`) in the translated ARM guest. This is not evidence that a game
MV ran, that memory was exhausted, or that export works on a physical device.
No actual MP4, restoration or saved-file verification passed in this case.
The small proof artifact is `14738371088`; successful artifact collection and
strict native links remain separate from a functional runtime pass.

## Native ARM64 redroid guest (separate scope)

`verify-actual-mv-export-redroid.yml` builds the same current input on x86 and
runs the game on a GitHub `ubuntu-24.04-arm` runner inside a disposable
[redroid](https://github.com/remote-android/redroid-doc) container
(`redroid/redroid:15.0.0_64only-250627`, pinned by digest; `14.0.0_64only-240527`
is a dispatch fallback). The game's arm64 code runs natively, so no ARM
translation library is present. The runner has no KVM or render node, so the
guest uses redroid's software GPU (ANGLE on SwiftShader). The container gets a
fresh `/data`, adb is published only on `127.0.0.1:15555`, and the job loads
`binder_linux` before starting it. The job records the host gate, the image
digest, `getprop`, the ABI list, the GLES/Vulkan renderer, display size, codec
libraries, audio HAL and preinstalled packages.

The driver and probe take an explicit `--guest redroid`. The default
`translated-emulator` contract is unchanged. Under redroid the driver:

- accepts only a loopback adb serial;
- requires the exact native ARM64 redroid identity (no native bridge,
  `uname -m` aarch64) instead of the translator hash;
- pre-grants only `POST_NOTIFICATIONS` through adb before launch;
- answers an Android system "isn't responding" dialog with **Wait**, recording
  each answer;
- reports a missing DocumentsUI as `EXPORT_VERIFIED_SAVE_BLOCKED` /
  `save_blocked_documentsui_unavailable`, which is never a pass.

Every export, decode, audio and restore gate is identical. A pass is reported
as `PASS_ACTUAL_MV_EXPORT_REDROID_ARM64_ONLY` with scope
`actual_game_in_redroid_native_arm64_container`. This is neither emulator nor
phone evidence. The environment probe result is recorded, but it does not stop
the game step.

On both outcomes the driver keeps the app's own export trace. The emulator-only
observer's read-only `/mp4-diagnostics` endpoint returns the native status with
scene diagnostics, the native export-trace document (current stage, last error,
recent events and unbound modules) and the app's diagnostics-export document.
Each value is re-bounded to scalar codes. The driver writes
`latest-mp4-diagnostics.json` and one `mp4-diagnostics-NNN-<reason>.json` per
distinct trace. It also writes `persisted-mp4-diagnostics.json`, the app's
persisted last and last-failed trace, which can still be read after the process
dies. `runtime-report.json` summarizes them under `mp4_diagnostics`.

`/mp4-status` now also carries the render target, draw count and restoration
checkpoint fields. The completion gates already required these fields, but the
observer had not forwarded them.
