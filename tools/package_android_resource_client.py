#!/usr/bin/env python3
"""Build a separate normal local client with a local Octo resource origin.

The existing game stays installed. This package has its own cache and settings,
and connects to the same local server profile. Existing local-login bootstrap
bytes are reused from the verified normal-client baseline; no QA observer,
software AES, store bypass, SDK flags or additional native hooks are introduced.
Unity's one PlayerSettings HTTP transport policy is enabled; Android NSC still
limits cleartext connections to127.0.0.1 and TLS validation is unchanged.
The Unity extraction-cache build GUID is derived from the changed code/config
hashes so ordinary engine startup refreshes IL2CPP resources after an update.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from idoly_local.android_package import configure_android
from idoly_local.client_patch import patch_metadata
from idoly_local.unity_http import MEMBER as UNITY_SETTINGS, patch_player_http
from idoly_local.unity_cache import MEMBER as UNITY_GUID, derive_cache_guid

if __package__:
    from . import patch_android_octo_origin as octo
else:
    import patch_android_octo_origin as octo


PACKAGE = "game.qualiarts.idolypride.local.resources"
LABEL = "아이프라 로컬 리소스"
API_ORIGIN = "http://127.0.0.1:50051"
SIGNER = "3c56abcfd37697c4a1436849391a2002793df18082d2843130a7e99292a5bd6c"
SOURCE_SHA256 = "f34f443744e5417a1a80015d4f7a1aab700fd1a74f7e97604827074d82706371"
NORMAL_NATIVE_SOURCE_SHA256 = "2be12648e8fb416de07ea882278f38f9c4a4fb3798d210d7dc8d4423cef1127a"
ORIGINAL_METADATA = "f03b65e71c07648215ae18d6bb787462f2b049c45212f379eaa9ea05f8ba874e"
ORIGINAL_NATIVE = "68d4706d14b33d07647b9752124632a44b6a5901c82723beb569d9123df676b3"
NORMAL_NATIVE = "4517381b0dbeae559d79832797f0c57c78ba6f37cf7d3544a58d0f31f2b8def3"
NATIVE = "lib/arm64-v8a/libil2cpp.so"
MARKER = "assets/idoly-local.json"
RESOURCE_REPLACEMENTS = {"AndroidManifest.xml", "resources.arsc", "res/xml/network_security_config.xml"}
FORBIDDEN = {"classes5.dex", "assets/idoly-qa-ui.json", "lib/arm64-v8a/libidoly_qa_ui_bridge.so"}


def private_regular_file(path: Path) -> Path:
    path = Path(path).resolve(strict=True)
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("Signing material must be an existing private regular file")
    return path


def verify_key(keytool: Path, key: Path, password: Path, alias: str, env: dict) -> None:
    # Only keytool reads the password file. No secret value enters Python or a report.
    cmd = [keytool, "-J-Xmx128m", "-keystore", key, "-alias", alias, "-storepass:file", password]
    cert = subprocess.run([str(x) for x in [*cmd[:1], "-exportcert", *cmd[1:]]],
                          capture_output=True, env=env)
    if cert.returncode or hashlib.sha256(cert.stdout).hexdigest() != SIGNER:
        raise ValueError("Configured side-by-side client signing certificate differs")
    listing = octo._run([*cmd[:1], "-list", "-v", *cmd[1:]], "Signing key validation", env)
    if "PrivateKeyEntry" not in listing.stdout:
        raise ValueError("Configured side-by-side signing alias has no private key")


def stage_resources(decoded: Path, stage: Path) -> dict:
    """Reuse the small original XML decode; never copy or decode game executables."""
    stage.mkdir()
    shutil.copyfile(decoded / "AndroidManifest.xml", stage / "AndroidManifest.xml")
    shutil.copytree(decoded / "resources", stage / "resources")
    (stage / "root").mkdir()
    raw = decoded / "root/res"
    if raw.exists():
        shutil.copytree(raw, stage / "root/res")
    for name in ("archive-info.json", "uncompressed-files.json", "path-map.json"):
        shutil.copyfile(decoded / name, stage / name)
    return configure_android(stage, API_ORIGIN, PACKAGE, LABEL)


def write_resource_input(source: Path, target: Path) -> None:
    """Bind the XML decode directly to resource members of the pinned APK."""
    with ZipFile(source) as incoming, ZipFile(target, "x") as outgoing:
        for info in incoming.infolist():
            if info.filename not in ("AndroidManifest.xml", "resources.arsc") and not info.filename.startswith("res/"):
                continue
            with incoming.open(info) as src, outgoing.open(copy.copy(info), "w") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)


def resource_ids(text: str) -> list:
    return re.findall(r"^\s+resource (0x[0-9a-f]+) ([^\s]+)", text, re.MULTILINE)


def signing_command(signer: list, key: Path, password: Path, alias: str, apk: Path) -> list:
    # apksigner consumes successive lines if the SAME password file is named
    # twice. PKCS12 uses the store password for the key when --key-pass is absent.
    return [*signer, "sign", "--ks", key, "--ks-key-alias", alias,
            "--ks-pass", "file:" + str(password), "--v4-signing-enabled", "false", apk]


def validate_identity(badging: str, manifest: str, resource_dump: str) -> None:
    if (f"package: name='{PACKAGE}'" not in badging or "versionName='6.1.1'" not in badging
            or "versionCode='414'" not in badging or "native-code: 'arm64-v8a'" not in badging
            or f"application-label:'{LABEL}'" not in badging
            or f"Package name={PACKAGE} id=7f" not in resource_dump):
        raise ValueError("Resource client's package, label, version, ABI or resource package differs")
    # Reject stale original/local authorities and permissions, while preserving
    # original qualified Java component names (which still live in original DEX).
    for line in manifest.splitlines():
        if any(name in line for name in (":authorities(", ":permission(", ":readPermission(", ":writePermission(")):
            for value in re.findall(r'="([^"]+)"', line):
                for part in value.split(";"):
                    if part.startswith("game.qualiarts.idolypride") and not (
                            part == PACKAGE or part.startswith(PACKAGE + ".")):
                        raise ValueError("Resource client retained a conflicting local/original authority or permission")
    debug_lines = [line for line in manifest.splitlines() if ":debuggable(" in line]
    if ("game.qualiarts.idolypride.qa.ui.QaUiProvider" in manifest
            or any(not re.search(r":debuggable\([^)]*\)=false(?:\s|$)", line) for line in debug_lines)):
        raise ValueError("Normal resource client must not contain the QA provider or debug flag")


def stream_apk(source: Path, normal_source: Path, target: Path, replacements: dict) -> None:
    with ZipFile(source) as incoming, ZipFile(normal_source) as normal, ZipFile(target, "x") as outgoing:
        for info in incoming.infolist():
            if octo.signature_member(info.filename):
                continue
            if info.filename in replacements:
                outgoing.writestr(copy.copy(info), replacements[info.filename])
            else:
                reader = normal if info.filename == NATIVE else incoming
                with reader.open(info.filename) as src, outgoing.open(copy.copy(info), "w") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
        marker = ZipInfo(MARKER)
        marker.compress_type = ZIP_DEFLATED
        marker.external_attr = 0o100644 << 16
        outgoing.writestr(marker, replacements[MARKER])


def package(source: Path, normal_native_source: Path, output: Path, *,
            keystore: Path, password_file: Path, alias="idoly-local", apkeditor: Path,
            build_tools: Path, java: Path, report_path: Path | None = None) -> dict:
    source, normal_native_source = Path(source).resolve(strict=True), Path(normal_native_source).resolve(strict=True)
    output = Path(output).resolve()
    report_path = Path(report_path).resolve() if report_path else output.with_suffix(".evidence.json")
    if (output.suffix != ".apk" or output.exists() or report_path.exists()
            or output in (source, normal_native_source) or report_path in (source, normal_native_source, output)):
        raise ValueError("Choose new APK and evidence paths; all existing clients are preserved")
    if octo.file_hash(source) != SOURCE_SHA256 or octo.file_hash(normal_native_source) != NORMAL_NATIVE_SOURCE_SHA256:
        raise ValueError("Expected the pinned original merged APK and normal-native provenance source")
    key, password = private_regular_file(keystore), private_regular_file(password_file)
    java, sdk, editor = Path(java).resolve(strict=True), Path(build_tools).resolve(strict=True), Path(apkeditor).resolve(strict=True)
    env = dict(os.environ)
    signer = [java, "-Xmx128m", "-jar", sdk / "lib/apksigner.jar"]
    verify_key(java.with_name("keytool"), key, password, alias, env)
    octo.verify_signer(signer, normal_native_source,
                       octo.PROFILES[NORMAL_NATIVE_SOURCE_SHA256]["signer"], env)
    with ZipFile(source) as incoming, ZipFile(normal_native_source) as normal:
        before, normal_hashes = octo.member_hashes(incoming), octo.member_hashes(normal)
        if before.get(NATIVE) != ORIGINAL_NATIVE or normal_hashes.get(NATIVE) != NORMAL_NATIVE:
            raise ValueError("Native source differs from original/normal baseline")
        code = {k: v for k, v in before.items() if k.startswith("lib/") or re.fullmatch(r"classes\d*\.dex", k)}
        if any(normal_hashes.get(k) != v for k, v in code.items() if k != NATIVE):
            raise ValueError("Original SDK/native/Java differs from the normal baseline")
        if FORBIDDEN & before.keys() or MARKER in before:
            raise ValueError("Original source contains local or QA additions")
        metadata = incoming.read(octo.METADATA)
        settings = incoming.read(UNITY_SETTINGS)
        original_guid = incoming.read(UNITY_GUID)
    if hashlib.sha256(metadata).hexdigest() != ORIGINAL_METADATA:
        raise ValueError("Original metadata differs")
    api_metadata, api_proof = patch_metadata(metadata, API_ORIGIN)
    del metadata
    if hashlib.sha256(api_metadata).hexdigest() != octo.METADATA_SHA256:
        raise ValueError("Local API patch differs from published normal metadata")
    metadata, octo_proof = octo.patch_octo_metadata(api_metadata)
    del api_metadata
    settings, unity_proof = patch_player_http(settings)
    guid, guid_proof = derive_cache_guid(original_guid, octo_proof["output_sha256"], unity_proof["output_sha256"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".resource-client-", dir=output.parent) as temporary:
        work = Path(temporary)
        decoded, resource_input = work / "source-xml", work / "source-resources.apk"
        stage, resource_apk = work / "resource-stage", work / "resource-only.apk"
        write_resource_input(source, resource_input)
        octo._run([java, "-Xmx128m", "-jar", editor, "d", "-dex", "-t", "xml",
                  "-i", resource_input, "-o", decoded], "Pinned source resource-only decode", env)
        configuration = stage_resources(decoded, stage)
        shutil.rmtree(decoded)
        resource_input.unlink()
        octo._run([java, "-Xmx128m", "-jar", editor, "b", "-i", stage, "-o", resource_apk],
                  "Resource-only rebuild", env)
        original_resources = octo._run([sdk / "aapt2", "dump", "resources", source], "Original resource table", env).stdout
        rebuilt_resources = octo._run([sdk / "aapt2", "dump", "resources", resource_apk], "Rebuilt resource table", env).stdout
        if not resource_ids(original_resources) or resource_ids(original_resources) != resource_ids(rebuilt_resources):
            raise ValueError("Resource rebuild changed original resource identifiers/names")
        del original_resources, rebuilt_resources
        with ZipFile(resource_apk) as resources:
            replacements = {name: resources.read(name) for name in RESOURCE_REPLACEMENTS}
        shutil.rmtree(stage)
        resource_apk.unlink()
        marker = {"schema_version": 2, "package": PACKAGE, "label": LABEL,
                  "endpoint": API_ORIGIN, "octo_origin": octo.DEFAULT_ORIGIN,
                  "side_by_side": True, "existing_client_replaced": False,
                  "cache_and_settings_are_separate": True, "profile_is_selected_by_local_server": True,
                  "input_original_merged_sha256": SOURCE_SHA256,
                  "native_sha256_matches_published_normal": NORMAL_NATIVE,
                  "normal_baseline_reuses_six_existing_local_login_bootstrap_patches": True,
                  "unity_http_connection_policy": unity_proof,
                  "unity_cache_build_guid": guid_proof,
                  "qa_observer_or_new_sdk_native_patches_added": False}
        replacements.update({octo.METADATA: metadata, UNITY_SETTINGS: settings, UNITY_GUID: guid,
                             MARKER: (json.dumps(marker, ensure_ascii=False, indent=2) + "\n").encode()})
        del metadata, settings
        unsigned, aligned = work / "unsigned.apk", work / "aligned.apk"
        stream_apk(source, normal_native_source, unsigned, replacements)
        replacement_hashes = {k: hashlib.sha256(v).hexdigest() for k, v in replacements.items()}
        del replacements
        octo._run([sdk / "zipalign", "-f", "16384", unsigned, aligned], "APK alignment", env)
        unsigned.unlink()
        octo._run(signing_command(signer, key, password, alias, aligned), "Resource client signing", env)
        octo.verify_signer(signer, aligned, SIGNER, env)
        octo._run([sdk / "zipalign", "-c", "16384", aligned], "Resource client alignment", env)
        with ZipFile(aligned) as archive:
            after = octo.member_hashes(archive)
        expected = {**before, **replacement_hashes, NATIVE: NORMAL_NATIVE}
        if after != expected or FORBIDDEN & after.keys():
            raise ValueError("Unexpected game, SDK, resource or QA APK member change")
        badging = octo._run([sdk / "aapt2", "dump", "badging", aligned], "Resource client identity", env).stdout
        manifest = octo._run([sdk / "aapt2", "dump", "xmltree", "--file", "AndroidManifest.xml", aligned], "Resource client manifest", env).stdout
        resources = octo._run([sdk / "aapt2", "dump", "resources", aligned], "Resource client resources", env).stdout
        validate_identity(badging, manifest, resources)
        if octo.file_hash(source) != SOURCE_SHA256 or octo.file_hash(normal_native_source) != NORMAL_NATIVE_SOURCE_SHA256:
            raise ValueError("Build source changed")
        report = {**marker, "source_kind": "independent build from original merged APK plus verified normal native baseline",
                  "qa_only": False, "configuration": configuration, "metadata_api_patch": api_proof,
                  "metadata_octo_patch": octo_proof, "output_apk_sha256": octo.file_hash(aligned),
                  "output_bytes": aligned.stat().st_size, "signer_sha256": SIGNER,
                  "signing_password_handled_only_by_keytool_apksigner_file_option": True,
                  "signature_and_16384_alignment_verified": True, "original_resource_ids_preserved": True,
                  "resource_xml_decoded_directly_from_pinned_source_apk": True,
                  "changed_members_from_original": sorted(k for k in before if before[k] != after[k]),
                  "added_members": sorted(after.keys() - before.keys()),
                  "all_other_member_bytes_preserved": True,
                  "normal_baseline_sdk_native_dex_sha256": {**code, NATIVE: NORMAL_NATIVE},
                  "old_public_client_update_compatible": False,
                  "existing_game_install_or_saved_data_modified": False,
                  "sdk_callbacks_flags_clocks_modified": False, "vm_install_performed": False,
                  "published": False}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        os.link(aligned, output)
        try:
            with report_path.open("x", encoding="utf8") as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        except BaseException:
            output.unlink()
            raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--normal-native-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--keystore", type=Path, required=True)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--alias", default="idoly-local")
    parser.add_argument("--apkeditor", type=Path, required=True)
    parser.add_argument("--build-tools", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        report = package(args.source, args.normal_native_source, args.output,
                         keystore=args.keystore, password_file=args.password_file, alias=args.alias,
                         apkeditor=args.apkeditor, build_tools=args.build_tools, java=args.java,
                         report_path=args.report)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Resource client build failed: {error}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
