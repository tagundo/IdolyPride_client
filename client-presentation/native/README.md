# Client presentation bridge

This independently implemented ARM64 addon consumes the server's presentation
preferences inside the original 6.1.1 game process. It contains no game assets,
account information, HTTP client or Java launcher. The separate Java provider
owns loading this library and forwarding validated loopback preferences.

`libidoly_presentation.so` exports these static JNI methods on
`game.qualiarts.idolypride.presentation.NativePresentation`:

```java
void start();
boolean configure(int schema, long revision, boolean customGraphics,
    int quality, int fps, float scale, int maxBufferPixel,
    int aaMode, int shadow, boolean expandPhotography);
String status();
```

`configure` validates schema 1 and publishes one mutex-protected immutable
snapshot. It performs no Unity/IL2CPP operation. A true return means accepted,
not applied. Older revisions and conflicting reuse of a revision are rejected.
`start` installs function-entry hooks on a worker after matching the mapped GNU
build ID and every pinned 16-byte function prefix; it never hashes the whole
game library during startup. ShadowHook 2.0.1 UNIQUE mode matches diagnostics.
The library stays pinned while hooks exist. A partial install is rolled back.

All game access occurs from the QualityManager or scene/render callbacks on
the established game thread. Managed references retained between calls use
weak IL2CPP handles. Cameras/controllers/images also require Unity liveness.
The tiny FPS setter and OnDestroy tail branches are not inline-hooked. Actual
FPS uses Unity Application.targetFrameRate, preserving the latest game value
for disabling the override. No preference changes a user snapshot or inventory.

The bridge supports quality 0/10/20/30/40/100, FPS 0/30/60/90/120, finite scale
0.25–2, even maximum dimension 256–4096, AA -1/0/1/2 and actor shadow
0/512/1024/2048/4096. Quality 100 is the original Recording mode. AA affects
only the main base camera; FXAA/SMAA require existing postprocessing. Shadow
requests cannot exceed the device's maximum texture dimension. Additional
camera data is restored immediately after the original initializer returns.
The custom-graphics master switch also gates FPS; a stored 120 remains saved
when disabled but the latest original game cap is restored. Photography
expansion has its own independent switch.

Expanded photography is separate from custom graphics. Main and 360 scene
entry/reset hooks delimit its lifetime. An active target image must point to
the main render target and have full UV coordinates. Original level4/5 images
serialize `applyAspectRatio=false`; the active horizontal image starts at a
fixed 1920x1080, while its direct Main parent stretches with the actual view.
The bridge adjusts only this image's sizeDelta and localPosition to fill that
verified parent. It preserves anchors, pivot, scale, rotation and UVs, without
enabling or creating a fitter. Four weak layout slots retain exact original
values across horizontal/vertical image switches and restore on off, exit,
owner/controller replacement or failure. Later original layout writes take
precedence over the saved override baseline.
Its *unfitted parent RectTransform* supplies the viewport ratio, rather than
the whole Screen or the already fitted 16:9 child. The original renderer
rebuilds its target and its existing resize/LateUpdate path updates the image.
Camera position, rectangle and automatic/manual aspect policy are unchanged.
Only cameras whose aspect automatically follows the actual render target and
whose rectangle is already full are supported. Wider viewports retain the original vertical
FOV; narrower viewports increase vertical coverage to preserve the original
horizontal coverage. The bridge measures the original projection matrix's
four edge rays and the new target's fitted projection, including physical
camera film-gate behavior. It computes the minimum lens expansion that keeps
all four original edges, then verifies those edges in the actual matrix.
Checking only raw `Camera.fieldOfView` is insufficient for a physical lens.
Cinemachine's original physical-camera path writes `Camera.focalLength`
instead of fieldOfView in LateUpdate; both original lens setters are observed
and expansion is reapplied immediately after either write. Both getters expose
the original game lens values to prevent feedback. Exit/off restores the exact
saved physical focal length or nonphysical FOV and controller ratio. Incoming
original lens changes update the baseline. Gate, sensor, lens-shift or camera
projection-model changes cause a fresh measurement at the original ratio.
The bridge never changes Camera.aspect, Camera.rect or Camera.projectionMatrix.

The bridge acknowledges expanded view only after checking actual texture
dimensions, the complete displayed parent rectangle including position,
identity local rotation/unit scale, full UVs, current controller-camera
identity, actual projection-edge containment and projection/target aspect.
Unknown layouts remain `waiting_for_scene`; a fixed 16:9 parent on
a differently shaped window is reported `unsupported`, with expansion
capability false, until its true viewport can be established. It does not infer a
larger viewport from screen orientation, alter HUD layout, move a camera,
stretch a texture, crop UVs, create missing geometry or expand fixed MV video.
Actual Fold/rotation rendering still requires device validation; static
profiles and CPU tests do not establish it.

`status` has only the agreed fixed schema: `schema`, `bridge_version`, actual
applied `revision`, `status`, six capability booleans and seven finite numeric
metrics. Status values are `waiting`, `applied`, `disabled`, `unsupported`,
`waiting_for_scene`, `init_failed`. An acknowledgement revision changes after
game-thread application; publishing preferences never manufactures one.

The source references HoshimiLocalify's documented option contracts and the
original metadata/native interfaces. Its GPLv3 implementation was not copied.
Profile provenance and ABI details are in `profile.json`. This repository's
existing ShadowHook license/third-party notices apply to that dependency.

Run the CPU and bounded-profile checks with:

```sh
python -m pytest -q client-presentation/native/tests
```

Native compilation uses cached NDK 26.3.11579264, C++17, `-fexceptions`,
`-fno-rtti`, `-nostdlib++`, and 16 KiB ELF segment alignment. Statically link
the NDK libc++abi archive with hidden archive symbols so RAII restores
temporary fields/TLS if an original IL2CPP call unwinds; no libc++ shared
library is required. Dynamic dependencies are ShadowHook, dl, m and libc. The parent
addon builder owns signing and APK packaging. No runtime/device verification
or installer is included in these native tests.
