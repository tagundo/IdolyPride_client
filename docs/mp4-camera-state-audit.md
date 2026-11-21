# Selected camera and audio restoration audit

This work is source and native-boundary implementation evidence. It is not a successful device MP4 receipt and does not authorize a product build or release.

`tools/audit_mp4_camera_state.py` derives both platforms' method bindings, exported IL2CPP APIs, enum values, reference layouts and native property witnesses from the pinned unchanged clients. The profile is embedded in the existing `mp4_camera_owner.hpp`; generated evidence stays outside the native input directory.

## Camera state

The bounded scope retains the selected player, directors, output camera, brain and audio sources. It admits authored `CinemachineShotPlayable` cameras through actual retained director graph paths. It snapshots native component transforms and activation, lens/projection properties, and the finite managed camera/cache island. Managed references are restored with the original IL2CPP write barrier. Restoration reads actual native properties and normalized managed bytes again after the source director/player state has been restored.

A root graph rebuild creates new mixer override IDs. Restoration resolves the corresponding new mixer on the same authorized director/graph path and maps captured logical frame IDs to the new ID. It never writes an old positive override ID into a fresh mixer. The live next-ID counter remains monotonic. Native frame counts remain monotonic too; camera history frame indexes retain their captured relative age.

`CinemachineCore.mLastUpdateTime` and `FixedFrameCount` are static fields. `UpdateTracker` also owns static mutable status and deletion containers. They are not instance offsets. Export installs fresh containers through the original closed generic constructors and restores the captured source references and values afterward. A source status cloned with `PreferredUpdate=Fixed` can remain Fixed forever when its matrix does not move, so copying the source tracker into export would starve a Smart camera.

Smart support requires the actual world scope to suppress the entire Fixed subtree and to close normal animation ownership. Fresh tracker statuses start with the original Late preference; unchanged ARM execution shows that 90 Late-only updates of static or moving targets retain Late preference. The original Brain Smart/Late branch and Core cache/filter decisions remain in use. The source update method is not rewritten to Late. This branch evidence does not establish that a particular running MV has passed the domain checks.

The output lens witness includes the original native automatic-aspect authority flag, not just its numerical aspect ratio. Original `ResetAspect` sets that flag and `set_aspect` clears it on both engines. Only verified implicit and physical projection modes are admitted; a custom explicit matrix is not restored by blindly assigning a getter matrix or calling `ResetProjectionMatrix`.

Camera extensions and unknown mutable reference families remain unsupported until their state and time consumers are closed. No-Impulse admission checks instantiated listeners/sources, including inactive components, plus existing active manager events. It does not mistake an empty current event list for complete listener ownership.

## Audio state

The scope captures each selected source's clip, samples, original `isPlaying`, precise native paused bit, volume, pitch, mute and loop state. The native Pause and UnPause leaves on both engines write the same proven receiver byte. The managed API has no pause getter; `isPlaying=false` is not used to infer that a source was paused.

A nonnull direct clip can be reconciled with the original Play/Stop/Pause/UnPause and sample setters. Samples are verified while the source is paused. Once a playing source resumes, the audio backend may advance samples, so an equality check against the old sample number is not a valid continued-playback test.

A clipless selected Timeline output is never Play/Stop/seeked as if it had a direct clip. A clipless source with `isPlaying=true` is rejected before source mutation with `camera_timeline_audio_active_channel_unclosed`: synchronous reconstruction of that native channel is not yet proved. A clipless source with `isPlaying=false` can be supported. Whether normal device MVs expose this value must be recorded from the running game; audible Timeline playback alone is not that evidence.

Dependent property/history restoration happens before the source director resumes. The mandatory `verify_source_restored` phase runs afterward, while the source roots are still retained. Director/player restoration is latched once, so retrying verification cannot repeatedly resume, rebuild or evaluate the source. A final native playback mismatch is a permanent restoration error, not an indefinite wait for a native animation phase that has been closed.

Private RNG isolation is shared with the owned actor callback scope. Camera callbacks must not rewind the ambient RNG at the end of export; doing so would erase unrelated consumers' progress.

## Rendering state still under audit

Holding the native clock does not suppress URP rendering. The actual selected `SetupDithering` updates its pass index on each render, and `SetupGrain` can consume Unity RNG on each render, even when the frame number has not changed. Capture-pass or end-camera hooks run too late to prevent this work. The selected draw route therefore needs one render for each accepted 60 Hz simulation tick, including the ticks omitted from a 30 fps output file. Held readback retries reuse the rendered target. The camera scope has separate scalar render permission, so arming a delayed first draw does not reopen Brain/Core or advance actor simulation.

Both pinned originals expose static `RenderCameraStack` and `RenderSingleCamera` entries with an eight-byte `ScriptableRenderContext` and a `Camera` reference. The inner overload receives a caller-local 336-byte `CameraData` through the actual native indirect argument. Its camera member is at unboxed offset 128, not at the boxed metadata offset 144. Original caller scans find two inner calls from the stack entry and one from the external camera entry on each platform. A conservative outer-route admission requires the selected camera to be Base with an empty overlay stack; actual running-camera evidence remains necessary.

The selected UACD owns `MotionVectorsPersistentData`: two view matrices, two previous matrices, two frame indexes and two previous aspect values. A concrete host helper retains the original instance and arrays unchanged, creates private state with the original constructor, and redirects the UACD reference only during an owned draw. The reference is compare-restored immediately afterward, including before a reentrant source initialization. Prewarm history is reset on the private instance before frame zero. Its C++ fixture exercises null source history, private mutation, reset, reference supersession, a barrier that writes then throws, partial capture cleanup and pre-initialization closure. This is managed-state protocol evidence, not GPU rendering evidence.

The shared postprocess passes and volume interpolation are not closed merely by this MotionData isolation. Passes own mutable reset/dither/bokeh state and materials; constructing a fresh pass also changes shared shader-ID arrays. URP volume processing can replace the manager's stack, use or dispose a camera-cached stack, and mutate sort/collider caches. World admission does not own those values. Private pass construction/redirection and a scoped volume-stack/cache lease must be implemented and verified before this render domain can attest restoration. The current state must not be described as a completed normal-MV export implementation.

## Other lifecycle boundaries

Grant revocation is scalar-only and works after source/clock ownership is lost. It does not perform Unity reads or substitute for a job fence. Ordinary and photography presenter-end observations retire stale readiness. Global shader lease cleanup precedes observed source replacement.

Readback uses a temporary active-RT guard armed before the original setter. It compare-restores its previous target and releases its temporary GC root on setter or ReadPixels exceptions. A superseding external target is preserved.

The C++ protocol tests cover these ownership, cancellation, remapping, native property, reference-barrier and exception paths. Complete-original audits reconstruct the embedded profile. Device validation must still demonstrate actual supported MV readiness, render/frame progression, restoration, and a decodable MP4 before the work is described as complete.
