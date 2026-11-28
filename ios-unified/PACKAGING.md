# Runtime and package layout

`runtime_inputs.json` pins the public CPython3.13 b18 support archive, five universal Python wheels, exact Korean v0.3.31 client, Data31 and iOS translation inputs. Dependency wheel hashes/URLs were compared with PyPI version metadata; the four locally cached wheels matched their pins. No desktop Python runtime, grpcio, upb or PyCryptodome native library is selected.

On an Xcode host, first fetch the pinned inputs with the separate CI fetch helper, then prepare one target into a fresh directory:

```sh
python ios-unified/prepare_runtime.py --support INPUTS/Python-3.13-iOS-support.b18.tar.gz --wheel-dir INPUTS/wheels --project-root . --target device --architecture arm64 --output RUNTIME
```

For the Simulator smoke app use `--target simulator --architecture x86_64` or `arm64` to match the host. Target selection uses the XCFramework plist plus the actual Mach-O architecture and LC_BUILD_VERSION platform. There is no fallback to a Mac or wrong-platform binary. The prepared Python framework retains `Headers/Python.h` for the native framework compiler.

Each native stdlib extension is copied into its own framework, its install ID is changed to that framework path, and its `.so` name becomes a `.fwork` mapping. Its framework binary also has the matching `.origin` file. Both mappings are relative to the app executable directory, as required by CPython's AppleFrameworkLoader. Every prepared Python framework is ad-hoc signed and checked with `codesign --verify --strict`. The final audit re-reads all native binary platforms, IDs and dependencies. New loose `.so` or `.dylib` modules are rejected.

The Python source allowlist is the exact71-module transitive import closure of `idoly_local.ios_host`. A changed closure requires updating the manifest. The Dream archive reader is needed by the normal profile and imports no grpcio; no private capture files, DBs or catalogs are copied. Standard-library tests/editors, protobuf compiler helpers and gRPC generated helpers are omitted. Project and dependency licenses remain bundled. The native host must set pure-Python protobuf before importing the server.

The prepared tree is app-relative:

```text
Frameworks/Python.framework/{Python,Info.plist,Headers,...}
Frameworks/<module>.framework/{<module>,<module>.origin,Info.plist,...}
python-stdlib/lib-dynload/<original-extension-name>.fwork
LocalServer/python/{idoly_local,h2,hpack,hyperframe,google,...}
LocalServer/licenses/AGPL-3.0.txt
runtime-report.json
```

Build `IdolyEmbeddedServer.framework` against `RUNTIME/Frameworks/Python.framework`. The native builder and Unity load patch are separate tools. For the actual device package, sign the native framework before composition:

```sh
codesign --force --sign - --timestamp=none NATIVE/IdolyEmbeddedServer.framework
codesign --verify --strict NATIVE/IdolyEmbeddedServer.framework
python ios-unified/patch_load.py --source-ipa INPUTS/base.ipa --output PATCHED-UNITY
python ios-unified/package_unified.py --base-ipa INPUTS/base.ipa --patched-unity PATCHED-UNITY --runtime-root RUNTIME --native-framework NATIVE/IdolyEmbeddedServer.framework --server-data INPUTS/ServerData.zip --translations INPUTS/bundledTranslations.zip --source-commit EXACT_COMMIT --output Unified.ipa
```

The package adds `LocalServer/ServerData.zip`, `bundledTranslations.zip`, verified selection metadata and local settings files. It preserves the client's identifier and protocol version; the display name is 아이프라 로컬 and CFBundleVersion is156.9103. File Sharing and opening Documents in place are enabled. The original small executable and SDK members remain byte-identical. The Unity comparison streams the entire input and patched file, permitting only the two load-command counters and the exact new command in previously zero header padding. No code or presentation gateways move.

The explicit unified package capacity is600MiB compressed and1GiB expanded. Large files are streamed in64KiB chunks. All output members are read back through CRC/SHA verification before the owned partial is promoted. Existing output paths are preserved.

For the independent Simulator probe, omit all original game inputs:

```sh
python ios-unified/package_unified.py --stage-only --target simulator --runtime-root SIM_RUNTIME --native-framework SIM_NATIVE/IdolyEmbeddedServer.framework --server-data INPUTS/ServerData.zip --translations INPUTS/bundledTranslations.zip --output Prepared.app
python ios-unified/build_probe.py --prepared-app Prepared.app --output Probe.app --arch HOST_ARCH
```

Stage-only mode supplies no executable or app Info.plist. It permits the explicitly unsigned native smoke framework; the probe builder must sign every copied framework and its own app before launch. Device IPA composition continues to require a signed embedded framework. Simulator host tests do not establish phone gameplay, FPS or PlayCover compatibility. The combined IPA still requires user sideload/PlayCover signing; no signing certificate or private account data is included.


The multilingual package additionally includes LocalServer/client-languages.zip and its SHA-256 descriptor. The ZIP stores only the language-dependent serialized assets and native metadata, with a manifest binding every common/variant member to the pinned original and Korean-base IPA inputs. Build verification reconstructs and reuses all three complete Data bundles. The Simulator app receives the original base Data as non-executable files to exercise this preparation path; it never runs original device game code.
