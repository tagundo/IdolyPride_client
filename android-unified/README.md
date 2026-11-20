# Android unified prototype

The launcher and original Unity game share one application ID and UID. The
server menu is the only launcher. The original Firebase component name remains
an alias to the menu, so notifications and deep links follow the same preparation
path. Starting the game requires a running server and prepared language data.

The original client's `resources.arsc`, SDK DEX and Unity/SDK native libraries
are preserved. Server Java is rebuilt with a separate `0x7e` resource table,
attached through the public Android 11 resource-loader API. The optional
presentation addon is the only replaceable native member; it requires an ELF
and current-source build receipt. Compile-only Firebase/Core factory stubs never
enter the output DEX.

Unity mounts `getPackageCodePath()` directly. The language pack stores original
compressed spans and creates one selected, verified Data ZIP before Unity starts.
The activity overrides only that path; the actual installed APK and
`nativeLibraryDir` remain unchanged. Identical Unity/Firebase/WebView static
assets are included through a fixed allowlist. Downloaded Octo resources use a
separate canonical internal resource store; the Data carrier is not a second
downloaded resource cache.

A process-restored internal game activity passes through the component factory.
When server or Data preparation is absent, the factory constructs a plain
recovery activity instead of Unity. That activity calls the normal Android
activity superclass, forwards the launch payload to the menu, and finishes the
restored game record. It does not leave a menu instance attached to a game
activity record.

During the game, a stationary single-finger hold in the upper-right corner opens
the menu after two seconds. The region is at least 160 dp by 120 dp and at least a
quarter of each window dimension. Movement, another pointer, cancellation or
activity pause cancels the timer. Recognition sends a cancellation to Unity and
reorders the menu forward without clearing the game activity.

Both the application and game activity opt into Android multi-window resizing.
The game keeps every original Unity configuration handler, including screen size,
smallest size, screen layout, orientation and density for foldable cover/inner
display transitions. Original aspect-ratio caps are removed. Unity's original
SurfaceView and multi-window pause/resume logic remain responsible for rendering;
the wrapper forwards configuration/display changes and cancels stale corner holds.
While the OS reports multi-window mode, the existing two-frame orientation-ready
path is used so a portrait split window does not wait forever for a physical turn.
Leaving multi-window mode restores the user's saved playback preference.
The native server menu recreates for its new window bounds, restores its selected
category, event edits and scroll position, and leaves the service running.
The packager decodes the compiled manifest again and records its window policy.
Real split-screen, pop-up and foldable-device behavior still needs device testing.

`tools/package_android_unified.py` requires CPython 3.13, pinned public KO/JA/EN
clients and server APK, SDK34 tools, the pinned Chaquopy runtime JAR and APKEditor,
and the existing diagnostic development certificate. Output names include a
date and `prototype`; existing outputs are never overwritten. The provenance
records exact compiled source hashes, original member preservation, language
spans, signing identity, stored-native alignment and explicit runtime gates.

This is an internal prototype, not a release replacement for Android 9/10.
Device installation, native ABI coexistence, all language transitions and game
direct resource reads still require runtime verification. Signing and static
packaging checks do not establish those outcomes.

An Android9/10 follow-up may use a public `Resources` adapter for the server's
strings and twelve string-arrays, delegating Android/game IDs unchanged. The
server has no layout/style resource dependency, and its notification uses the
installed game's icon. This is feasibility evidence only: such an adapter is
not implemented or validated in this candidate. Existing separate Android9/10
packages remain the supported fallback.
