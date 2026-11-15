#!/usr/bin/env python3
"""Build fixed Japanese/English game APKs on an owned remote Actions runner.

The pinned diagnostic base is an immutable donor, not a fresh-source claim.
Current presentation native/Java and the complete audited full-client writer
are rebuilt. Both languages keep the existing update identity and certificate.
No device, account, private key outside this checkout or installed app is read.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("ja", "en")
PACKAGE = "game.qualiarts.idolypride.local.diagnostics"
VERSION_CODE = 414
CERTIFICATE = "aa4e9346ff9e542b263b70254df3e25b79211df16161208a3b509c4f113facfc"
REPORT_NAME = "android-clients-report.json"
FONT_PUBLIC_COMMIT = "5c41199ea0024a9e0b2cb31735265056e5472d76"
FONT_GIT_BLOB = "ab20ba021ecb09802976a8dcee3eaa4219bf55f7"
CLIENT_NAMES = {lang: "IdolyPride-Local-Graphics-Diagnostic-Android-arm64-" + lang + ".apk"
                for lang in LANGUAGES}
INPUTS = {
    "diagnostic_base": {"bytes": 159549324, "sha256": "f5be0c0e19c2a17ea28ffa0c3205a49f5ab004f013e2e67e319aa192ca1995df"},
    "apkeditor": {"bytes": 7126009, "sha256": "4a98ae6a755264357603f1906b92e62e757d59229014e33395f4e03ff019fda8"},
    "font": {"bytes": 3781740, "sha256": "7cd2b757bd8b8db79b4b87c3b402aa62aca666b55ff50ae0799e14ece1942314"},
    "english_ui": {"bytes": 227781, "sha256": "b30f48cdcbc0ddfc267a0a7d265ec717a7057342bdc55c9f0d16fe3ea06fc702"},
    "english_ui_proof": {"bytes": 348, "sha256": "298138bcadd69249a4b064b1b96ada4c15e6da2c42327d1d97e27a2b6c69cb62"},
    "shadowhook": {"bytes": 461264, "sha256": "2cad01ff4d59542958775e19f281981a7e84b39670b5fae75905b8511e10c7cd"},
}
URLS = {
    "diagnostic_base": "https://github.com/tagundo/IdolyPride_client/releases/download/local-diagnostics-v0.2.1/IdolyPride-Local-Diagnostic-Android-arm64.apk",
    "apkeditor": "https://github.com/REAndroid/APKEditor/releases/download/V1.4.1/APKEditor-1.4.1.jar",
    "font": "https://github.com/orioncactus/pretendard/raw/5c41199ea0024a9e0b2cb31735265056e5472d76/packages/pretendard-jp/dist/public/static/PretendardJP-SemiBold.otf",
    "shadowhook": "https://repo.maven.apache.org/maven2/com/bytedance/android/shadowhook/2.0.1/shadowhook-2.0.1.aar",
}
HOSTS = frozenset(("github.com", "raw.githubusercontent.com", "media.githubusercontent.com",
    "objects.githubusercontent.com", "release-assets.githubusercontent.com", "github-cloud.githubusercontent.com",
    "github-cloud.s3.amazonaws.com", "repo.maven.apache.org"))
CHUNK = 128 * 1024
UI_MEMBER = "assets/bin/Data/dc5a3280fad6542929a0daf3a3736d29"
JAPANESE_UI_SHA256 = "6c522891fb2ed310c9a6669871c76550e4d144e9aa538b5074b064ef7ecb020e"
VALIDATION_FLAGS = ("pinned_inputs_verified", "source_bound_native_and_feature_verified",
    "signature_v2_v3_verified", "zipalign_16384_verified", "same_update_identity_verified",
    "declared_member_inventory_verified", "local_resource_output_fields_verified",
    "built_in_ui_language_verified", "font_assets_verified", "original_inputs_unchanged")
REQUIRED_SOURCES = (
    "tools/release_android_clients.py", "client-presentation/build_addon.py",
    "client-presentation/build_full_client.py", "client-presentation/native/bridge.cpp",
    "client-presentation/native/profile.json", "src/idoly_local/ui_assets.py",
    "src/idoly_local/font_assets.py", "src/idoly_local/static_ui_assets.py",
    "src/idoly_local/ui_display_literals.py", "src/idoly_local/story_loading_prefab.py",
    "ios-unified/client-language-inputs/en.csv", "ios-unified/client-language-inputs/en-report.json")


PHASES = frozenset(("startup", "checkout", "directories", "input_diagnostic_base", "input_apkeditor",
    "input_font", "input_shadowhook", "input_english_ui", "input_english_ui_proof", "sdk",
    "native", "feature", "language_ja", "language_en", "verification", "final"))
_PHASE = "startup"


def phase(name):
    global _PHASE
    need(name in PHASES, "unknown_build_phase")
    _PHASE = name


def failure_report(error):
    message = str(error)
    return {"schema": 1, "status": "FAIL", "phase": _PHASE,
            "error_type": type(error).__name__,
            "error_code": message if re.fullmatch(r"[a-z0-9_]{1,96}", message) else "unclassified"}


def need(value, code):
    if not value:
        raise ValueError(code)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), "regular_report_required")
    return {"bytes": path.stat().st_size, "sha256": sha(path)}


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def approved(url):
    parsed = urlsplit(url)
    need(parsed.scheme == "https" and parsed.hostname in HOSTS and parsed.port in (None, 443)
         and not parsed.username and not parsed.password, "unapproved_public_input_origin")
    return url


def download(url, pin, destination, guard):
    """Stream only one fixed public input, never forward repository credentials."""
    destination = Path(destination)
    need(not destination.exists() and not destination.is_symlink(), "fresh_input_required")
    opener, response = build_opener(NoRedirect()), None
    for _ in range(6):
        try:
            response = opener.open(Request(approved(url), headers={"Accept-Encoding": "identity"}), timeout=90)
            break
        except HTTPError as error:
            need(error.code in (301, 302, 303, 307, 308), "public_input_http_failure")
            url = approved(error.headers.get("Location", ""))
    need(response is not None, "public_input_redirect_bound")
    partial = destination.with_name(destination.name + ".partial")
    size, digest = 0, hashlib.sha256()
    with response, partial.open("xb") as output:
        while block := response.read(CHUNK):
            guard.check()
            size += len(block)
            need(size <= pin["bytes"], "public_input_size_bound")
            digest.update(block)
            output.write(block)
    need(size == pin["bytes"] and digest.hexdigest() == pin["sha256"], "public_input_digest_differs")
    partial.rename(destination)


def verify_input(path, pin):
    need(record(path) == pin, "pinned_input_differs")


def native_command(compiler, toolchain, shadow, output):
    return [compiler, "-std=c++17", "-O2", "-fPIC", "-fvisibility=hidden",
        "-fexceptions", "-fno-rtti", "-nostdlib++", "-ffunction-sections", "-fdata-sections",
        "-Wall", "-Wextra", "-Werror", "-shared", "-Wl,--gc-sections",
        "-Wl,--exclude-libs,ALL", "-Wl,--no-undefined", "-Wl,--threads=1",
        "-Wl,-z,max-page-size=16384", "-Wl,-z,common-page-size=16384",
        "-Wl,-soname,libidoly_presentation.so", "-I" + str(shadow / "include"),
        "-I" + str(ROOT / "client-presentation/native"), ROOT / "client-presentation/native/bridge.cpp",
        toolchain / "sysroot/usr/lib/aarch64-linux-android/libc++abi.a",
        "-L" + str(shadow / "lib"), "-lshadowhook", "-ldl", "-lm", "-o", output]


def prepare_native(args, addon, limits, guard, work, inputs):
    ndk = Path(args.ndk).resolve(strict=True)
    properties = dict(line.split("=", 1) for line in (ndk / "source.properties").read_text().splitlines() if "=" in line)
    need(next((value.strip() for key, value in properties.items() if key.strip() == "Pkg.Revision"), None)
         == "26.3.11579264", "ndk_revision_differs")
    toolchain = ndk / "toolchains/llvm/prebuilt/linux-x86_64"
    tools = toolchain / "bin"
    shadow = work / "shadowhook"
    shadow.mkdir()
    selected = {"prefab/modules/shadowhook/include/shadowhook.h": "include/shadowhook.h",
                "jni/arm64-v8a/libshadowhook.so": "lib/libshadowhook.so",
                "jni/arm64-v8a/libshadowhook_nothing.so": "lib/libshadowhook_nothing.so"}
    with ZipFile(inputs["shadowhook"]) as archive:
        need(len(archive.namelist()) == len(set(archive.namelist())), "duplicate_shadowhook_member")
        for name, relative in selected.items():
            info = archive.getinfo(name)
            need(not info.is_dir() and 0 < info.file_size <= 2 * 1024**2, "shadowhook_member_bound")
            path = shadow / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as incoming, path.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, CHUNK)
    for member, expected in addon.SHADOW_HASHES.items():
        need(sha(shadow / "lib" / Path(member).name) == expected, "shadowhook_native_digest_differs")
    out = work / "native"
    out.mkdir()
    library = out / "libidoly_presentation.so"
    sources = addon.frozen_sources(args.source_commit)
    original = limits._resource_guard(ROOT)
    stages = []
    env = {key: value for key, value in os.environ.items()
           if key not in ("GH_TOKEN", "GITHUB_TOKEN", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH")}
    env["MALLOC_ARENA_MAX"] = "2"
    def run(name, command):
        guard.check()
        before = limits._resource_guard(ROOT)
        result = limits._run(command, root=ROOT, env=env, timeout=120)
        after = limits._resource_guard(ROOT)
        need(before["oom_kill"] == after["oom_kill"] == original["oom_kill"], "native_oom_baseline_changed")
        stages.append({"name": name, "before": before, "after": after})
        return result.decode("utf-8")
    command = native_command(tools / "aarch64-linux-android28-clang++", toolchain, shadow, library)
    run("compile", command)
    run("strip", [tools / "llvm-strip", "--strip-unneeded", library])
    dynamic = run("readelf", [tools / "llvm-readelf", "-d", library])
    needed = re.findall(r"Shared library: \[([^\]]+)\]", dynamic)
    need(set(needed) == {"libshadowhook.so", "libdl.so", "libm.so", "libc.so"}, "native_dependencies_differ")
    alignment, jni = addon.check_elf(library), addon.check_jni(library)
    need(addon.frozen_sources(args.source_commit) == sources, "native_source_changed")
    prefixes, hooks = addon.native_profile_counts()
    receipt = {"schema": 1, "source_commit": args.source_commit, **record(library),
        "source_sha256": {name: sources[name] for name in addon.native_source_paths()},
        "source_unchanged_during_build": True, "profile_prefix_count": prefixes,
        "profile_hook_count": hooks, "abi": "arm64-v8a", "minimum_api": 28,
        "segment_alignment": 16384, "dt_needed": needed, "load_segments": alignment,
        "exports": jni, "command": list(map(str, command)), "stages": stages,
        "runtime_device_tested": False}
    write_json(out / "build-receipt.json", receipt)
    addon.verified_native(library, args.source_commit, sources)
    return library, tools / "llvm-readelf"


def verify_language(apk, proof, language, commit, full):
    need(proof.get("source_commit") == commit and proof.get("source_apk_sha256") == INPUTS["diagnostic_base"]["sha256"]
         and proof.get("source_apk_bytes") == INPUTS["diagnostic_base"]["bytes"]
         and proof.get("ui_language") == language and proof.get("certificate_sha256") == CERTIFICATE
         and proof.get("signature_v2_v3_verified") is True
         and proof.get("local_resource_output_fields_verified") is True
         and proof.get("all_original_members_preserved_except_declared_manifest_font_UI_transport_and_story_loading") is True
         and proof.get("native_input", {}).get("source_commit") == commit
         and proof.get("device_tested") is False, "full_client_provenance_differs")
    need(record(apk) == {"bytes": proof.get("output_bytes"), "sha256": proof.get("output_apk_sha256")},
         "full_client_output_digest_differs")
    font = proof.get("font_support", {})
    need(font.get("original_long_dash_font_retained") is True
         and font.get("legacy_Japanese_font_data_unchanged") is True
         and font.get("all_other_objects_byte_identical") is True
         and font.get("output_members"), "font_support_differs")
    with ZipFile(apk) as archive:
        need(len(archive.namelist()) == len(set(archive.namelist())), "duplicate_output_member")
        def digest_member(name):
            with archive.open(name) as incoming:
                return hashlib.file_digest(incoming, "sha256").hexdigest()
        for name, item in font["output_members"].items():
            need(archive.getinfo(name).file_size == item["bytes"] and digest_member(name) == item["sha256"],
                 "packaged_font_member_differs")
        ui_hash = digest_member(UI_MEMBER)
        if language == "ja":
            need(archive.getinfo(UI_MEMBER).file_size == 244584 and ui_hash == JAPANESE_UI_SHA256
                 and proof.get("ui_translation") is None, "japanese_ui_not_original")
        else:
            ui = proof.get("ui_translation", {})
            need(ui.get("language") == "en" and ui.get("output_asset_sha256") == ui_hash
                 and ui.get("compiled_csv_sha256") == INPUTS["english_ui"]["sha256"]
                 and ui.get("runtime_translation_hooks_added") is False
                 and ui.get("all_other_objects_byte_identical") is True, "english_ui_not_packaged")
        full.verify_local_resource_output(archive, proof["local_resource_transport"])
        guid_hash = digest_member(full.unity_cache.MEMBER)
        native_hash = digest_member(full.addon.LIBRARY)
        need(native_hash == proof["native_library_sha256"], "packaged_presentation_native_differs")
    return {"ui_asset_sha256": ui_hash, "unity_cache_sha256": guid_hash,
            "presentation_native_sha256": native_hash}


def build(args):
    phase("checkout")
    need(re.fullmatch(r"[0-9a-f]{40}", args.source_commit), "exact_source_commit_required")
    run_id = int(args.run_id or os.environ.get("GITHUB_RUN_ID", "0"))
    need(run_id > 0 and str(run_id) == os.environ.get("GITHUB_RUN_ID", str(run_id)), "exact_run_id_required")
    phase("directories")
    work_arg, output_arg = Path(args.work).absolute(), Path(args.output).absolute()
    need(not work_arg.is_symlink() and not output_arg.is_symlink(), "non_symlink_remote_paths_required")
    work, output = work_arg.resolve(strict=False), output_arg.resolve(strict=False)
    need(work != output and not work.exists() and not output.exists()
         and not work.is_symlink() and not output.is_symlink(), "fresh_remote_directories_required")
    need(not work.is_relative_to(ROOT) and not output.is_relative_to(ROOT)
         and not work.is_relative_to(output) and not output.is_relative_to(work), "external_separate_work_and_output_required")
    need(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
         == args.source_commit, "checkout_source_differs")
    # All inputs are public and source checks are local Git reads. Native/Java
    # child tools do not need repository tokens or inherited tracing options.
    for name in tuple(os.environ):
        if name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_DEBUG", "GIT_CURL_VERBOSE") or name.startswith("GIT_TRACE"):
            os.environ.pop(name, None)
    sys.path[:0] = [str(ROOT / "client-presentation"), str(ROOT / "tools"), str(ROOT / "src")]
    shared = importlib.import_module("release_platform_builds")
    addon = importlib.import_module("build_addon")
    full = importlib.import_module("build_full_client")
    limits = importlib.import_module("build_android_server_manual")
    guard = shared.Guard()
    work.mkdir(mode=0o700); output.mkdir(mode=0o700)
    inputs = {}
    for name, url in URLS.items():
        phase("input_" + name)
        inputs[name] = work / (name + (".apk" if name == "diagnostic_base" else ".bin"))
        download(url, INPUTS[name], inputs[name], guard)
    for name, filename in (("english_ui", "en.csv"), ("english_ui_proof", "en-report.json")):
        phase("input_" + name)
        inputs[name] = ROOT / "ios-unified/client-language-inputs" / filename
        verify_input(inputs[name], INPUTS[name])
    phase("sdk")
    android_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    need(android_home is not None, "android_sdk_root_required")
    sdk_root = Path(android_home)
    jdk = Path(args.jdk_bin or (Path(os.environ["JAVA_HOME"]) / "bin")).resolve(strict=True)
    sdk = Path(args.build_tools or (sdk_root / "build-tools/34.0.0")).resolve(strict=True)
    android = Path(args.android_jar or (sdk_root / "platforms/android-34/android.jar")).resolve(strict=True)
    args.ndk = args.ndk or (sdk_root / "ndk/26.3.11579264")
    for filename, expected in ((android, limits.PUBLIC_INPUT_HASHES["android-jar"]),
        (sdk / "lib/d8.jar", limits.PUBLIC_INPUT_HASHES["d8-jar"]),
        (sdk / "lib/apksigner.jar", limits.PUBLIC_INPUT_HASHES["signer-jar"])):
        need(sha(filename) == expected, "android_build_tool_input_differs")
    phase("native")
    library, readelf = prepare_native(args, addon, limits, guard, work, inputs)
    password = work / "public-diagnostic-password"
    password.write_bytes(b"android"); password.chmod(0o600)
    key = ROOT / "android-diagnostics/local-diagnostics-development.keystore"
    common = dict(source_commit=args.source_commit, jdk_bin=jdk, build_tools=sdk,
                  keystore=key, password_file=password)
    feature = work / "diagnostics-feature.apk"
    phase("feature")
    addon.build(SimpleNamespace(profile="diagnostics", base_apk=inputs["diagnostic_base"],
        native_library=library, output=feature, android_jar=android, shadowhook_aar=inputs["shadowhook"],
        readelf=readelf, **common))
    extra = (*full.TRANSPORT_SOURCES, *full.STATIC_UI_SOURCES,
        "client-presentation/build_full_client.py", "tools/build_android_server_manual.py",
        "tools/repack_android_server_python.py", "tools/package_android_resource_client.py",
        "src/idoly_local/font_assets.py", "client-presentation/fonts/pretendard-jp-v1.json",
        "client-presentation/licenses/Pretendard-OFL.txt", "src/idoly_local/ui_assets.py",
        "src/idoly_local/ui_translation_build.py", *REQUIRED_SOURCES)
    source_hashes = addon.frozen_sources(args.source_commit, extra=extra)
    binaries, packaging_evidence = [], {}
    for language in LANGUAGES:
        phase("language_" + language)
        guard.check()
        apk = output / CLIENT_NAMES[language]
        proof = full.build(SimpleNamespace(source=inputs["diagnostic_base"], feature_apk=feature,
            output=apk, ram_directory=Path("/dev/shm"), all_tmpfs=False,
            apkeditor=inputs["apkeditor"], font_file=inputs["font"], font_license_file=None,
            ui_language=language, ui_csv_file=inputs["english_ui"] if language == "en" else None,
            ui_proof_file=inputs["english_ui_proof"] if language == "en" else None,
            image_dir=None, native_library=None, **common))
        packaged = verify_language(apk, proof, language, args.source_commit, full)
        signer = [jdk / "java", *addon.JAVA_FLAGS, "-jar", sdk / "lib/apksigner.jar"]
        checked = limits._run(full.output_verify_command(signer, apk), root=ROOT,
                              env=shared.clean_env(), timeout=60).decode("utf-8")
        need(re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([a-f0-9]{64})$", checked, re.M)
             == [CERTIFICATE] and all("Verified using v" + str(n) +
                " scheme (APK Signature Scheme v" + str(n) + "): true" in checked for n in (2, 3)),
             "final_signature_differs")
        limits._run([sdk / "zipalign", "-c", "16384", apk], root=ROOT, env=shared.clean_env(), timeout=60)
        badging = limits._run([sdk / "aapt2", "dump", "badging", apk], root=ROOT,
                             env=shared.clean_env(), timeout=60).decode("utf-8")
        need("package: name='" + PACKAGE + "'" in badging and "versionCode='414'" in badging
             and "versionName='6.1.1'" in badging and "native-code: 'arm64-v8a'" in badging,
             "final_update_identity_differs")
        binaries.append({"language": language, "name": apk.name, **record(apk),
            "application_id": PACKAGE, "version_code": VERSION_CODE,
            "certificate_sha256": CERTIFICATE})
        packaging_evidence[language] = packaged
    phase("verification")
    need(len({row["unity_cache_sha256"] for row in packaging_evidence.values()}) == 2, "locale_cache_guids_not_distinct")
    need(len({row["presentation_native_sha256"] for row in packaging_evidence.values()}) == 1, "locale_native_features_differ")
    for name, path in inputs.items():
        verify_input(path, INPUTS[name])
    need(addon.frozen_sources(args.source_commit, extra=extra) == source_hashes, "build_sources_changed")
    guard.check()
    (output / "native").mkdir()
    shutil.copyfile(work / "native/build-receipt.json", output / "native/build-receipt.json")
    shutil.copyfile(feature.with_suffix(".provenance.json"), output / "diagnostics-feature.provenance.json")
    reports = ("native/build-receipt.json", "diagnostics-feature.provenance.json",
               *(Path(CLIENT_NAMES[lang]).with_suffix(".provenance.json").name for lang in LANGUAGES))
    value = {"schema": 1, "status": "PASS", "source_commit": args.source_commit, "run_id": run_id,
        "languages": list(LANGUAGES), "binaries": binaries, "inputs": INPUTS,
        "source_sha256": source_hashes,
        "validation": {**{name: True for name in VALIDATION_FLAGS}, "runtime_device_tested": False},
        "packaging_evidence": packaging_evidence,
        "report_files": {name: record(output / name) for name in reports},
        "input_provenance": {"diagnostic_base_release_asset": 728205797,
            "diagnostic_base_reused_immutable": True, "fresh_native_feature_for_current_source": True,
            "font_public_commit": FONT_PUBLIC_COMMIT, "font_git_blob": FONT_GIT_BLOB,
            "package_variants_are_alternative_updates": True, "ko_client_reused_unchanged": True},
        "resources": guard.report()}
    phase("final")
    write_json(output / REPORT_NAME, value)
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("work", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("jdk-bin", "build-tools", "android-jar", "ndk"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    try:
        result = build(args)
    except Exception as error:
        failure = failure_report(error)
        if (_PHASE not in ("startup", "checkout", "directories")
                and args.output.is_dir() and not args.output.is_symlink()):
            try:
                write_json(args.output / "android-client-failure.json", failure)
            except OSError:
                pass
        print(json.dumps(failure))
        return 1
    print(json.dumps({"status": result["status"], "source_commit": result["source_commit"],
                      "binaries": result["binaries"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
