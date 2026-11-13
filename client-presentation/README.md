# Presentation bridge and standalone client

This component builds a graphics preference bridge for the Android 6.1.1 ARM64
client. Feature splits are intermediate build inputs to the separately distributed
standalone client APK. Since v0.3.16 the server never embeds, modifies or installs
client APKs. It inherits this repository's
[AGPL-3.0 license](../LICENSE). The native implementation and its original
interface/profile evidence are described in [native/README.md](native/README.md).
Host checks and signature checks do not establish device rendering support.

## Offline inputs

The build uses cached Android build-tools 34.0.0 (`aapt2`, `d8.jar`, `zipalign`,
`apksigner.jar`), Android platform 34 `android.jar`, OpenJDK 21, and NDK
26.3.11579264 `llvm-readelf`. Native compilation uses that NDK, C++17,
`-fexceptions -fno-rtti -nostdlib++`, static `libc++abi.a`, hidden archive
symbols, and 16 KiB load alignment. It needs no Gradle, Go, network access, or
full game APK rebuild. Use the native producer's stripped SO and provenance.

Pinned dependency SHA-256 values are:

| Input | SHA-256 |
| --- | --- |
| Android 34 android.jar | `6cea1df3efb77103ac3e2beb9bf4718964b0e0869ab16d39d29d5cbae1c147ad` |
| build-tools 34 d8.jar | `d43c8a94c9b1f1da1a7cc49c32b81e8cee1708b37ee8b530a81a0688222b42c0` |
| build-tools 34 apksigner.jar | `eefdd6aed9db9fb849e4c98a50d8741e19d1b674ba6547220bcb9c3ed152123a` |
| ShadowHook 2.0.1 AAR | `2cad01ff4d59542958775e19f281981a7e84b39670b5fae75905b8511e10c7cd` |

The matching base version code is **414** for both profiles. `diagnostics`
targets `game.qualiarts.idolypride.local.diagnostics`, certificate SHA-256
`aa4e9346ff9e542b263b70254df3e25b79211df16161208a3b509c4f113facfc`,
and requires the audited ShadowHook 2.0.1 libraries already in the base.
`resources` targets `game.qualiarts.idolypride.local.resources`, certificate
`3c56abcfd37697c4a1436849391a2002793df18082d2843130a7e99292a5bd6c`,
and bundles those two libraries. Both require the exact bootstrap native
member hash recorded by `required_base_members()` in `build_addon.py`.
Other packages, certificates and older incompatible diagnostic bases are
rejected; profiles do not fall back to another client.

## Build and verify

Run each profile sequentially with an unused output path. Provide the existing
matching keystore and a mode-0600 password file through explicit arguments;
never put credentials in source, command text or a report. The builder does
not generate a new key. A typical invocation, using environment variables
which name paths only, is:

```sh
MALLOC_ARENA_MAX=2 python client-presentation/build_addon.py \
  --profile diagnostics --base-apk "$DIAGNOSTIC_BASE_APK" \
  --source-commit "$FROZEN_SOURCE_COMMIT" \
  --native-library "$PRESENTATION_SO" --output "$ADDON_OUTPUT/diagnostics.apk" \
  --jdk-bin "$JDK_BIN" --build-tools "$ANDROID_BUILD_TOOLS" \
  --android-jar "$ANDROID_JAR" --shadowhook-aar "$SHADOWHOOK_AAR" \
  --readelf "$NDK_READELF" --keystore "$EXISTING_DIAGNOSTIC_KEYSTORE" \
  --password-file "$PRIVATE_PASSWORD_FILE"
```

Repeat with `--profile resources`, its matching base/key, and `resources.apk`.
The exact frozen Git commit must contain every Java source, native CPP/HPP,
profile, manifest and dependency notice used by the build. The native input's
adjacent `build-receipt.json` must identify that same commit, its SHA-256/size,
unchanged-source check, all native source hashes, and prefix/hook counts derived
from the frozen profile and hook declarations. All five JNI methods and
`JNI_OnLoad` must be exact defined, externally visible native functions.
Java runs use heap/metaspace 128 MiB, code cache 32 MiB, Serial GC and one
processor; tools run at nice 19 with bounded output and time limits. The
Java compilation uses `--release 8 -parameters`: named synthetic constructor
parameters avoid the cached D8 8.2.2 reader's null-name bug with JDK 21.
The
builder verifies the existing base's v2/v3 signature and certificate, version/native prerequisites, JNI exports,
ELF alignment/dependencies, the exact output member hashes, Android feature
metadata, v2 signature/certificate and 16 KiB ZIP alignment. Each split must
remain at most 1 MiB. Existing base/native inputs are checked unchanged.

`build_addon.bundle_manifest()` can record the two `.provenance.json` reports
for build inspection. The server manual builder no longer accepts
`--presentation-addons` and rejects embedded client APKs. Use the verified
diagnostics feature as an input to the standalone client builder below.

The static LLVM runtime notice in both splits reproduces the compiler-rt,
libc++abi and libunwind blocks from the pinned NDK's
`toolchains/llvm/prebuilt/linux-x86_64/NOTICE`; its source hash and component
boundaries are retained in [licenses/NDK-RUNTIME-NOTICES.txt](licenses/NDK-RUNTIME-NOTICES.txt).
The resources split also carries the existing ShadowHook license/notices.
All notice hashes appear in the APK member provenance and are checked again
by the server builder.

## Install and runtime contract

Download the server APK and complete client APK separately. Install the client
using Android's ordinary installer, preserving its package and signer for an
update. The server only launches known installed clients through normal launch
intents; it has no package-install permission, APK patcher or install callback.
The intermediate split is not a standalone app and is not an end-user download.
Its compatibility marker still describes its build contract; those fields do
not expose an installation feature in the server.

An unexported provider starts only in the supported main process. The daemon
polls `http://127.0.0.1:8080/client/presentation` every two seconds using a
strict schema, an 8192-byte limit, a one-second request deadline, no proxy and
no redirects. Native configuration publishes preferences; actual Unity-thread
acknowledgements alone determine reported application revisions. A native load
failure reports fixed `init_failed`/revision zero without exception text.
Unavailable server/bridge support leaves the game running with original
defaults. The provider performs no Unity calls or account/system-ID reads.

Host-only checks:

```sh
python -m pytest -q client-presentation/tests tests/test_build_android_server_manual.py
python -m pytest -q client-presentation/native/tests
```

## Standalone diagnostic update

`build_full_client.py` provides a normal full-APK fallback for the exact pinned
published diagnostic base. It reuses the audited feature's own DEX and native
library, appends `classes6.dex` and a private provider, and preserves original
SDK/DEX/native and Unity members except the declared manifest and font assets.
The compiled manifest comparison permits only that provider addition. The output retains
the AA4e certificate, package and version414 and verifies both v2/v3 signatures.
`assets/idoly-presentation-standalone.json` contains only the five public
compatibility fields used by the server to recognize the bridge in the base.

Use `--source`, `--feature-apk`, `--source-commit`, `--output`, `--apkeditor`,
`--jdk-bin`, `--build-tools`, `--keystore` and `--password-file` with the existing
matching private signing file. `--ram-directory /dev/shm` uses the approved
mixed staging route: unsigned on the output filesystem, aligned in RAM, then
signed on the output filesystem. At most one full APK occupies each location;
the normal memory and disk-reserve guards still apply. Only small original
manifest/resource members are decoded, and no whole game/native/DEX is rebuilt.
Alternatively, `--all-tmpfs --ram-directory /dev/shm` requires an output beneath
`/dev/shm` and keeps at most two full APKs there, including the final artifact.
This changes placement only: the Root reserve remains 150 MiB and every tool
still requires 1 GiB effective/768 MiB direct memory headroom. A small external
symlink can point to the final artifact for subsequent verified delivery.

The feature APK must have its adjacent `.provenance.json` with the same frozen
source commit, complete source/member hashes, verified signature/alignment and
native receipt. The full builder independently verifies its AA4e signature and
copies only the own DEX, native library and notices. The diagnostic base remains
fixed by its original SHA-256 and length. Optional `--native-library` requires
the same native receipt contract while retaining the feature's own DEX; the
standalone marker records its actual hash. Distribute this complete client APK
separately from the server APK.

## Korean font assets

The font-aware native profile requires `--font-file` on `build_full_client.py`
and on `tools/patch_ios_client.py` together with its presentation library/plan.
Supply the unmodified Pretendard JP SemiBold input pinned by
`fonts/pretendard-jp-v1.json`. The offline asset writer requires
`UnityPy==1.25.4`; the game and server do not import that build dependency.
`--font-license-file` can explicitly supply the pinned OFL text, which otherwise
comes from `licenses/Pretendard-OFL.txt`. Both builders reject an unpaired font
asset/native hook, a changed font or license, and an unexpected original asset.

The patch replaces the embedded SourceSansPro `Font` data and adds one legacy
fallback reference from the original Japanese `Font`. It preserves the Japanese
font bytes, all nineteen other serialized objects, and their external references.
The original SourceSansPro TMP asset remains in Dynamic mode and still references
that embedded `Font`. The native Awake hook checks the mode and source, retains
the fallback once and generates only requested glyphs. It does not scan text
every frame or pre-generate all 11,172 Korean syllables.

Android re-splits the shared asset into its declared 24 one-MiB-or-smaller parts;
iOS replaces the single shared asset. The client includes `IdolyFontSupport.json`
and `OFL-Pretendard.txt` under Android `assets/idoly-fonts/` or iOS `IdolyFonts/`.
The adjacent provenance/report records input/output hashes, actual Unicode
coverage, the unchanged Japanese data and object proofs. These checks establish
asset integrity and coverage; they do not claim a physical-device rendering test.
