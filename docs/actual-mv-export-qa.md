# Actual paused-MV export QA

`verify-actual-mv-export.yml` is manual only and never creates a release. Dispatch
it at the exact source commit and pass the same 40-character commit in
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
View**, observes a real normal 3D source, and pauses it through the game UI. It
requires an advancing PlayerLoop with a fixed paused timeline position before
starting a direct export. During export it uses the actual native overlay's
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

The landscape 30fps case then adds and exports one queued MV. Add must persist
the queue entry without hiding the server menu. A replay may construct a new
player, so its restoration baseline comes from the native job's actual acquired
source identity/time/pause snapshot, rather than the previous player's init
sequence. The square 60fps case independently verifies direct export at another
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
