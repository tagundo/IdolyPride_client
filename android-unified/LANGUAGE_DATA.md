# Internal Android language carrier

This implementation needs an actual Android launch check before it is described
as a working language-switching feature. Host verification checks archive bytes,
not Unity's behavior on a device.

`tools/build_android_language_data.py` admits three pinned game APKs, requires
identical member sets and identical content outside `assets/bin/Data/`, and
requires identical `boot.config` but distinct `unity_app_guid` values. It puts
only deduplicated original compressed Data spans and an index into an archive
without APK executable code. A fixed allowlist of 46 byte-identical original
static assets also preserves StreamingAssets JSON and web-view files. The
audience-network DEX and dexopt profiles are excluded. The unified APK builder preserves the base game's compressed Data
spans and embeds the extra spans. The index describes complete Data inventories
for Korean, Japanese and English.

Before Unity starts, `UnifiedGameAssets.prepare(context, language)` runs on a
worker. It assembles and verifies one selected Data ZIP. Original compressed
bytes, compression methods, CRCs and an expected whole-ZIP SHA-256 are checked.
An identical valid cache is reused. Publication uses a staged file and rename;
a failed replacement retains the previous valid file. Preparation has its own
worker lock; UI snapshots and session freezing never wait for file hashing or
assembly. A brief state lock covers only the final rename and publication. If
another language is frozen while a worker prepares, publication is rejected.
Other selected carriers
are removed only before a Unity session is frozen. A live session cannot switch
languages or replace its carrier. The cache adds about 77 MB for the current
input set (about 79 MB including the retained static assets), while all three bundled languages add about 30 MB of extra encoded
spans. These figures concern built-in Data, separately from downloaded game
resources and their shared store.

`UnifiedGameActivity` calls `freeze(context, language)` before its Firebase/Unity
superclass and overrides only `getPackageCodePath()`. Its application information,
native library directory and Java AssetManager continue to refer to the actual
installed APK. The server launcher must complete preparation and match the
running server language before starting this activity. Language changes after
game launch require a cold restart.

## Native route verified for the donor

The inspected `libunity.so` SHA-256 is
`c36ea39e5040fbcd0577f7c49d08e149e2e7dc62449d90aadce761118a816c85`.
These are static ARM64 virtual addresses, not installed hooks:

- The `initJni` registration at `0x1465488` points to `0x7e4a20`, which passes
  the supplied Java Context through `0x7cb254` to the retained-context setter
  `0x7b0e34` at `0x7cb38c`.
- Native startup obtains that same context at `0x7c8dbc` and invokes its
  `getPackageCodePath()` through `0x104aab4` at `0x7c8dc4`.
- The returned path flows through `0x7cc724`, `0x7cc7d0` and `0x7c7df0` into
  the ZIP central-directory reader. Nearby diagnostics include `[VFS] Mount`,
  `ApkAddCentralDirectory` and `Unable to open/read zip file!`.
- The sole `getAssets()` JNI call at `0x7b1104` supplies `bin/Data/boot.config`.
  That file is identical across the admitted languages.

A public ResourcesLoader assets overlay alone would therefore not select all
native Unity Data. This implementation does not patch Unity's native code.

## Remaining platform validation

Test all three languages on a real Android target, including a cold language
change, metadata extraction/GUID invalidation, a cached relaunch, process exit
and server recovery. `Application.streamingAssetsPath` will reference the
selected Data/static-assets ZIP; Java AssetManager retains the installed APK.
The fixed static-asset allowlist is tested against both Python and Java, and
must remain identical across all three admitted clients. Service configuration
and inquiry-web-view use still need real device coverage. The API 30 requirement of
the current server resource loader is a separate prototype limitation; this
carrier does not establish Android 9/10 unified-app support.
