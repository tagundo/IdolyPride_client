#!/usr/bin/env python3
"""Source-bound APK-only draft delivery for the Android fold/window preview.

This never publishes, replaces assets, deletes releases, uploads an IPA, or
changes repository visibility. Actions owns the write token; local checks do not.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

REPO = "tagundo/IdolyPride_client"
WORKFLOW = ".github/workflows/build-android-windowing-preview.yml"
BRANCH = "refs/heads/feat/ios-unified-server"
VERSION = "2026.11.20.1"
APK = "IdolyPride-Unified-" + VERSION + "-prototype.apk"
REPORT = APK.removesuffix(".apk") + ".provenance.json"
SUMS = "SHA256SUMS"
MIB = 1024 * 1024
CERTIFICATE = "aa4e9346ff9e542b263b70254df3e25b79211df16161208a3b509c4f113facfc"
REQUIRED_CHANGES = {"orientation", "screenLayout", "screenSize", "smallestScreenSize", "density", "colorMode"}
REQUIRED_SOURCES = {
    "android-server/app/src/main/AndroidManifest.xml",
    "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/MainActivity.java",
    "android-unified/src/main/java/game/qualiarts/idolypride/localserver/UnifiedGameActivity.java",
    "android-unified/src/main/java/game/qualiarts/idolypride/localserver/UnifiedWindowing.java",
    "tools/package_android_unified.py",
}
CLIENTS = {
    "ko": {"bytes": 165128829, "sha256": "f2b4555f2b56f5f388104a2e13a8cf0d50e3ffef3fca05d85281658d5a7366ae"},
    "ja": {"bytes": 164276861, "sha256": "3cffdcdf99b48eb5819b8639b3a31bfa43f4ae5cc1c092bb5dbd984a6c080543"},
    "en": {"bytes": 164260477, "sha256": "2bd373fbee1435c45000088fbf7996cbea8d577bf6015085e8c1101d82130baf"},
}
SERVER_SHA = "fc75a864d0b9306883439916c4a8df272ec7e8ff8d53dfa09e5ce594888b75b2"
CHAQUOPY_SHA = "04eed6260e65634ac1c2031d2ca8fdf90d58da226b2f070132a66c6e3af9e39b"
EDITOR_SHA = "4a98ae6a755264357603f1906b92e62e757d59229014e33395f4e03ff019fda8"


def need(value, code):
    if not value:
        raise ValueError(code)


def source_sha(value):
    need(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value), "exact_source_sha_required")
    return value


def tag(source):
    return "android-windowing-preview-" + VERSION + "-" + source_sha(source)[:7]


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def regular(path, maximum):
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= maximum, "regular_bounded_file_required")
    return info


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def json_value(raw):
    def reject(_):
        raise ValueError("invalid_json_constant")
    return json.loads(raw, object_pairs_hook=object_pairs, parse_constant=reject)


def apk_files(folder, source):
    source_sha(source)
    need(folder.is_dir() and not folder.is_symlink(), "real_output_directory_required")
    apk, report = folder / APK, folder / REPORT
    regular(report, 8 * MIB)
    value = json_value(report.read_bytes())
    need(type(value) is dict and value.get("schema") == 1 and value.get("source_commit") == source
         and value.get("working_tree_snapshot") is False and value.get("prototype") is True
         and value.get("release_eligible") is False and value.get("compiled_source_unchanged_during_build") is True
         and value.get("public_apk_inputs_unchanged") is True, "apk_source_proof_differs")
    marker, preservation, native = (value.get(key, {}) for key in ("marker", "preservation", "native_addon_build"))
    need(type(marker) is dict and marker.get("languages") == ["ko", "ja", "en"]
         and marker.get("process_mode") == "same" and marker.get("min_sdk") == 30
         and type(preservation) is dict and preservation.get("original_dex_and_sdk_native_unchanged") is True
         and preservation.get("resources_arsc_unchanged") is True
         and preservation.get("owned_presentation_addon_replaced") is True
         and set(preservation.get("changed_original_members", [])) == {"AndroidManifest.xml", "lib/arm64-v8a/libidoly_presentation.so"}
         and type(native) is dict and native.get("source_commit") == source
         and native.get("shared_cache_hooks") == 5 and native.get("abi") == "arm64-v8a"
         and native.get("runtime_symbols_hidden") is True and native.get("source_unchanged_during_build") is True
         and re.fullmatch(r"[0-9a-f]{64}", native.get("sha256", ""))
         and type(native.get("bytes")) is int and 0 < native["bytes"] <= 16 * MIB,
         "apk_native_or_preservation_proof_differs")
    window = value.get("windowing", {})
    changes = window.get("game_config_changes", []) if type(window) is dict else []
    need(type(window) is dict and all(window.get(key) is True for key in
              ("application_resizable", "game_resizable", "menu_resizable"))
         and type(changes) is list and all(type(change) is str for change in changes)
         and len(changes) == len(set(changes)) and REQUIRED_CHANGES <= set(changes)
         and window.get("game_orientation") == "fullUser"
         and window.get("menu_configuration_handling") == "recreate_with_saved_state"
         and window.get("aspect_ratio_restricted") is False, "apk_windowing_readback_differs")
    inputs = value.get("inputs", {})
    need(type(inputs) is dict and inputs.get("client_sha256") == CLIENTS["ko"]["sha256"]
         and inputs.get("language_clients") == CLIENTS and inputs.get("server_sha256") == SERVER_SHA
         and inputs.get("chaquopy_jar_sha256") == CHAQUOPY_SHA
         and value.get("tools", {}).get("editor") == EDITOR_SHA
         and value.get("signed_certificate_sha256") == CERTIFICATE, "apk_input_or_signature_proof_differs")
    rows = value.get("source_files", [])
    need(type(rows) is list and all(type(row) is dict and type(row.get("path")) is str
         and type(row.get("bytes")) is int and row["bytes"] > 0
         and re.fullmatch(r"[0-9a-f]{64}", row.get("sha256", "")) for row in rows), "apk_source_inventory_invalid")
    names = [row["path"] for row in rows]
    need(len(names) == len(set(names)) and REQUIRED_SOURCES <= set(names), "apk_windowing_sources_missing")
    info = regular(apk, 768 * MIB)
    need(type(value.get("apk_bytes")) is int and value["apk_bytes"] == info.st_size
         and value.get("apk_sha256") == sha(apk), "apk_bytes_differ")
    return [apk, report]


def checksums(folder, source):
    paths = apk_files(folder, source)
    result = "".join(f"{sha(path)}  {path.name}\n" for path in sorted(paths))
    target = folder / SUMS
    if target.exists() or target.is_symlink():
        regular(target, 4096)
        need(target.read_text() == result, "existing_checksums_differ")
    else:
        with target.open("x") as stream:
            stream.write(result)
    return [*paths, target]


def actions_context(source):
    need(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_REPOSITORY") == REPO
         and os.environ.get("GITHUB_SHA") == source_sha(source) and os.environ.get("GITHUB_REF") == BRANCH
         and os.environ.get("GITHUB_WORKFLOW_REF") == REPO + "/" + WORKFLOW + "@" + BRANCH
         and os.environ.get("GITHUB_EVENT_NAME") in ("push", "workflow_dispatch")
         and re.fullmatch(r"[1-9][0-9]*", os.environ.get("GITHUB_RUN_ID", ""))
         and re.fullmatch(r"[1-9][0-9]*", os.environ.get("GITHUB_RUN_ATTEMPT", "")), "scoped_actions_context_required")
    artifact = os.environ.get("BUILD_ARTIFACT_URL", "")
    run_id = os.environ["GITHUB_RUN_ID"]
    need(re.fullmatch(r"https://github\.com/" + re.escape(REPO) + r"/actions/runs/" + run_id + r"/artifacts/[1-9][0-9]*", artifact),
         "exact_build_artifact_url_required")
    return {"run_id": run_id, "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "event": os.environ["GITHUB_EVENT_NAME"], "workflow_commit": source,
            "workflow_run_url": "https://github.com/" + REPO + "/actions/runs/" + run_id,
            "build_artifact_url": artifact}


def api(path, *, body=None, absent=False):
    command = ["gh", "api", "repos/" + REPO + "/" + path]
    raw = None
    if body is not None:
        command += ["--method", "POST", "--input", "-"]
        raw = json.dumps(body).encode()
    result = subprocess.run(command, input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    need(len(result.stdout) <= 2 * MIB, "github_response_bound")
    if result.returncode:
        if absent and b"(HTTP 404)" in result.stderr:
            return None
        raise ValueError("github_api_failed")
    return json_value(result.stdout)


def release_gate(value, source, release_id=None, names=()):
    need(type(value) is dict and type(value.get("id")) is int and value["id"] > 0
         and (release_id is None or value["id"] == release_id)
         and value.get("draft") is True and value.get("prerelease") is True
         and value.get("tag_name") == tag(source) and value.get("target_commitish") == source,
         "preview_release_is_not_exact_draft")
    assets = value.get("assets")
    need(type(assets) is list and all(type(row) is dict and type(row.get("name")) is str
         and type(row.get("id")) is int and row["id"] > 0 for row in assets), "draft_asset_inventory_invalid")
    asset_names = [row["name"] for row in assets]
    need(len(asset_names) == len(set(asset_names)) and len({row["id"] for row in assets}) == len(assets)
         and set(asset_names) <= set(names), "draft_contains_unreviewed_or_duplicate_assets")
    return value


def existing_tag_gate(source):
    value = api("git/ref/tags/" + tag(source), absent=True)
    if value is None:
        return
    obj = value.get("object", {})
    for _ in range(3):
        if obj.get("type") == "commit":
            break
        need(obj.get("type") == "tag" and re.fullmatch(r"[0-9a-f]{40}", obj.get("sha", "")), "existing_tag_identity_differs")
        obj = api("git/tags/" + obj["sha"]).get("object", {})
    need(obj.get("type") == "commit" and obj.get("sha") == source, "existing_tag_source_differs")


def download_api(path, target):
    with target.open("xb") as stream:
        subprocess.run(["gh", "api", "repos/" + REPO + "/" + path, "--header", "Accept: application/octet-stream"],
                       stdout=stream, stderr=subprocess.DEVNULL, check=True, timeout=600)


def verify_remote(asset, path, work):
    digest = sha(path)
    need(type(asset.get("id")) is int and asset["id"] > 0 and type(asset.get("size")) is int
         and asset["size"] == path.stat().st_size and asset.get("state") == "uploaded"
         and asset.get("digest") in (None, "sha256:" + digest), "existing_asset_metadata_differs")
    with tempfile.TemporaryDirectory(prefix="readback-", dir=work) as folder:
        downloaded = Path(folder) / "asset"
        download_api("releases/assets/" + str(asset["id"]), downloaded)
        regular(downloaded, 768 * MIB)
        need(downloaded.stat().st_size == path.stat().st_size and sha(downloaded) == digest, "release_asset_readback_differs")
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": digest,
            "asset_id": asset["id"], "complete_download_verified": True}


def stage(folder, work, source):
    producer = actions_context(source)
    paths = checksums(folder, source)
    names = {path.name for path in paths}
    need(not work.exists() and not work.is_symlink(), "fresh_staging_directory_required")
    work.mkdir(parents=True)
    proof = {"schema": 1, "source_commit": source, "tag": tag(source), "draft": True,
             "published": False, "stage": "preflight", "android_producer": producer, "verified_assets": []}
    receipt = work / "draft-staging-proof.json"
    def save():
        receipt.write_text(json.dumps(proof, indent=2) + "\n")
    save()
    try:
        existing_tag_gate(source)
        release = api("releases/tags/" + tag(source), absent=True)
        if release is None:
            release = api("releases", body={"tag_name": tag(source), "target_commitish": source,
                "name": "Android fold/window preview " + VERSION + " (" + source[:7] + ")",
                "draft": True, "prerelease": True, "make_latest": "false",
                "body": "APK-only prototype built from " + source + ". Compiled manifest readback enables app/game/menu resizing and fold configuration handling without aspect caps. Original game DEX/SDK and resources.arsc preservation and three-language/current-native bridge proofs accompany this APK. Actual device split-screen and fold transitions remain unverified. This draft does not replace or publish any prior Android/iOS preview."})
        release = release_gate(release, source, names=names)
        release_id = release["id"]
        proof.update(release_id=release_id, release_url=release.get("html_url"), stage="upload_and_readback")
        save()
        # Reject conflicting existing bytes before uploading any other asset.
        local = {path.name: path for path in paths}
        for asset in release["assets"]:
            verify_remote(asset, local[asset["name"]], work)
        for path in paths:
            release = release_gate(api("releases/" + str(release_id)), source, release_id, names)
            selected = [row for row in release["assets"] if row["name"] == path.name]
            if not selected:
                subprocess.run(["gh", "release", "upload", tag(source), str(path), "--repo", REPO],
                               check=True, timeout=600)  # Deliberately no --clobber.
                release = release_gate(api("releases/" + str(release_id)), source, release_id, names)
                selected = [row for row in release["assets"] if row["name"] == path.name]
            need(len(selected) == 1, "release_asset_missing_or_duplicated")
            proof["verified_assets"].append(verify_remote(selected[0], path, work))
            save()
        final = release_gate(api("releases/" + str(release_id)), source, release_id, names)
        need({row["name"] for row in final["assets"]} == names, "draft_asset_inventory_incomplete")
        proof["stage"] = "verified_exact_draft"
        save()
        print(json.dumps(proof, indent=2))
        return proof
    except Exception as error:
        proof.update(stage="stopped", error_type=type(error).__name__)
        save()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("checksums", "stage"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()
    if args.action == "checksums":
        checksums(args.directory, args.source)
    else:
        need(args.work is not None, "fresh_staging_directory_required")
        stage(args.directory, args.work, args.source)


if __name__ == "__main__":
    main()
