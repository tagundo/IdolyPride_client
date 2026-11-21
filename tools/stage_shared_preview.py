#!/usr/bin/env python3
"""Build-input fetch and draft-only delivery for one frozen shared-cache preview.

Uses Actions' GH_TOKEN through gh; credentials never enter argv or reports.
No command publishes, changes visibility, replaces assets, or deletes releases.
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
import time
from urllib.request import urlopen
from zipfile import ZipFile

REPO = "tagundo/IdolyPride_client"
SOURCE = "1d583f4e1af17b92048cf01f5cc1781fe1905729"
RELEASE, MAC_RUN = 452520617, 44721537092
TAG = "shared-resources-preview-2026.11.20-" + SOURCE[:7]
ARTIFACT = "ios-unified-prototype-" + SOURCE
APK = "IdolyPride-Unified-2026.11.20-prototype.apk"
IPA = "IdolyPride-Unified-2026.11.20-prototype-" + SOURCE[:12] + "-iOS.ipa"
SUMS = "SHA256SUMS-shared-preview-" + SOURCE[:7] + ".txt"
MAC_WAIT_SECONDS = 2100
MIB = 1024 * 1024
INPUTS = {
    "client-ko.apk": (757750249, 165128829, "f2b4555f2b56f5f388104a2e13a8cf0d50e3ffef3fca05d85281658d5a7366ae"),
    "client-ja.apk": (757750501, 164276861, "3cffdcdf99b48eb5819b8639b3a31bfa43f4ae5cc1c092bb5dbd984a6c080543"),
    "client-en.apk": (757750856, 164260477, "2bd373fbee1435c45000088fbf7996cbea8d577bf6015085e8c1101d82130baf"),
    "server.apk": (757749041, 350605707, "fc75a864d0b9306883439916c4a8df272ec7e8ff8d53dfa09e5ce594888b75b2"),
    "chaquopy.jar": ("https://repo.maven.apache.org/maven2/com/chaquo/python/runtime/chaquopy_java/17.0.0/chaquopy_java-17.0.0.jar", 33648, "04eed6260e65634ac1c2031d2ca8fdf90d58da226b2f070132a66c6e3af9e39b"),
    "APKEditor.jar": ("https://github.com/REAndroid/APKEditor/releases/download/V1.4.1/APKEditor-1.4.1.jar", 7126009, "4a98ae6a755264357603f1906b92e62e757d59229014e33395f4e03ff019fda8"),
}


def need(value, code):
    if not value:
        raise ValueError(code)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", f"repos/{REPO}/{path}"], timeout=60))


def download_api(path, target):
    with Path(target).open("xb") as stream:
        accept = "application/octet-stream" if path.startswith("releases/assets/") else "application/vnd.github+json"
        subprocess.run(["gh", "api", f"repos/{REPO}/{path}", "--header", "Accept: " + accept],
                       stdout=stream, check=True, timeout=600)


def fetch_inputs(folder):
    folder.mkdir(parents=True, exist_ok=False)
    for name, (origin, size, digest) in INPUTS.items():
        target = folder / name
        if type(origin) is int:
            download_api(f"releases/assets/{origin}", target)
        else:
            with urlopen(origin, timeout=60) as source, target.open("xb") as output:
                used = 0
                while block := source.read(256 * 1024):
                    used += len(block)
                    need(used <= size, "public_input_size_exceeded")
                    output.write(block)
        need(target.stat().st_size == size and sha(target) == digest, "public_input_pin_differs")
    if __package__:
        from . import refresh_korean_translation_bundle as korean
    else:
        import refresh_korean_translation_bundle as korean
    korean.fetch_source(folder / "korean-translations-source.zip")


def release_gate(value):
    need(value.get("id") == RELEASE and value.get("draft") is True
         and value.get("prerelease") is True and value.get("tag_name") == TAG
         and value.get("target_commitish") == SOURCE, "preview_release_is_not_exact_draft")
    return value


def mac_gate(run, artifacts):
    need(run.get("id") == MAC_RUN and run.get("status") == "completed" and run.get("conclusion") == "success"
         and run.get("head_sha") == SOURCE and run.get("event") == "workflow_dispatch"
         and run.get("path") == ".github/workflows/build-server-apps.yml"
         and run.get("head_repository", {}).get("full_name") == REPO, "mac_producer_not_successful_exact_source")
    selected = [row for row in artifacts if row.get("name") == ARTIFACT]
    need(len(selected) == 1 and selected[0].get("expired") is False
         and type(selected[0].get("id")) is int and selected[0]["id"] > 0
         and 0 < selected[0].get("size_in_bytes", 0) <= 768 * MIB
         and re.fullmatch(r"sha256:[0-9a-f]{64}", selected[0].get("digest", "")), "mac_artifact_identity_invalid")
    return selected[0]


def wait_mac():
    deadline = time.monotonic() + MAC_WAIT_SECONDS
    while True:
        run = api(f"actions/runs/{MAC_RUN}")
        # Validate the producer even while waiting; never follow a different run/source.
        need(run.get("id") == MAC_RUN and run.get("head_sha") == SOURCE
             and run.get("event") == "workflow_dispatch"
             and run.get("path") == ".github/workflows/build-server-apps.yml"
             and run.get("head_repository", {}).get("full_name") == REPO, "mac_producer_identity_differs")
        if run.get("status") == "completed": return run
        need(os.environ.get("GITHUB_ACTIONS") == "true"
             and run.get("status") in ("queued", "in_progress", "waiting")
             and time.monotonic() < deadline, "mac_producer_still_pending")
        print(f"Waiting up to {MAC_WAIT_SECONDS // 60} minutes for exact Mac producer {MAC_RUN}", flush=True)
        time.sleep(30)


def bounded_json(path):
    need(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= 8 * MIB, "report_file_invalid")
    return json.loads(path.read_bytes())


def apk_files(folder):
    apk, report = folder / APK, folder / APK.replace(".apk", ".provenance.json")
    value = bounded_json(report)
    need(value.get("source_commit") == SOURCE and value.get("working_tree_snapshot") is False
         and value.get("prototype") is True and value.get("release_eligible") is False
         and value.get("compiled_source_unchanged_during_build") is True
         and value.get("public_apk_inputs_unchanged") is True, "apk_source_proof_differs")
    marker, preservation, native = (value.get(key, {}) for key in ("marker", "preservation", "native_addon_build"))
    need(type(marker) is dict and sorted(marker.get("languages", [])) == ["en", "ja", "ko"]
         and marker.get("process_mode") == "same" and marker.get("min_sdk") == 30
         and type(preservation) is dict and preservation.get("original_dex_and_sdk_native_unchanged") is True
         and preservation.get("resources_arsc_unchanged") is True
         and preservation.get("owned_presentation_addon_replaced") is True
         and type(native) is dict and native.get("source_commit") == SOURCE
         and native.get("shared_cache_hooks") == 5 and native.get("runtime_symbols_hidden") is True
         and native.get("source_unchanged_during_build") is True, "apk_shared_feature_proof_differs")
    need(apk.is_file() and not apk.is_symlink() and 0 < apk.stat().st_size <= 768 * MIB
         and value.get("apk_bytes") == apk.stat().st_size and value.get("apk_sha256") == sha(apk), "apk_bytes_differ")
    return [apk, report]


def checksum_file(paths, target):
    need(len({path.name for path in paths}) == len(paths), "duplicate_delivery_name")
    target.write_text("".join(f"{sha(path)}  {path.name}\n" for path in sorted(paths)))


def fetch_ipa(work):
    run = wait_mac()
    artifact = mac_gate(run, api(f"actions/runs/{MAC_RUN}/artifacts?per_page=100")["artifacts"])
    archive = work / "mac-artifact.zip"
    download_api(f"actions/artifacts/{artifact['id']}/zip", archive)
    need(archive.stat().st_size == artifact["size_in_bytes"]
         and "sha256:" + sha(archive) == artifact["digest"], "mac_artifact_archive_differs")
    paths = [work / IPA, work / IPA.replace(".ipa", ".report.json")]
    with ZipFile(archive) as source:
        infos = source.infolist()
        need(len(infos) <= 128 and len({row.filename for row in infos}) == len(infos), "mac_artifact_inventory_invalid")
        sums = source.getinfo("SHA256SUMS")
        need(sums.file_size <= 4096, "mac_checksum_bound")
        match = re.fullmatch(r"([0-9a-f]{64})  " + re.escape(IPA) + r"\n?", source.read(sums).decode("ascii"))
        need(match is not None, "mac_checksum_names_differ")
        for target in paths:
            info = source.getinfo(target.name)
            need(not info.flag_bits & 1 and not stat.S_ISLNK(info.external_attr >> 16)
                 and 0 < info.file_size <= (600 * MIB if target.suffix == ".ipa" else 8 * MIB), "mac_selected_member_invalid")
            with source.open(info) as incoming, target.open("xb") as outgoing:
                while block := incoming.read(256 * 1024): outgoing.write(block)
    value = bounded_json(paths[1])
    need(value.get("source_commit") == SOURCE and value.get("output_sha256") == sha(paths[0]) == match[1]
         and value.get("output_bytes") == paths[0].stat().st_size
         and value.get("fresh_presentation_source_build", {}).get("fresh_source_build") is True,
         "ipa_source_or_checksum_differs")
    return paths, {"run_id": MAC_RUN, "source_commit": SOURCE, "artifact_id": artifact["id"], "artifact_digest": artifact["digest"]}


def verify_remote(asset, path):
    expected = sha(path)
    need(asset.get("size") == path.stat().st_size and asset.get("state") == "uploaded"
         and asset.get("digest") in (None, "sha256:" + expected), "existing_asset_metadata_differs")
    with tempfile.TemporaryDirectory(prefix=".preview-readback-") as folder:
        copy = Path(folder) / "asset"
        download_api(f"releases/assets/{asset['id']}", copy)
        need(copy.stat().st_size == path.stat().st_size and sha(copy) == expected, "release_asset_readback_differs")


def stage(apk_folder, work):
    release_gate(api(f"releases/{RELEASE}"))
    paths = apk_files(apk_folder)
    work.mkdir(parents=True, exist_ok=False)
    ipa_paths, mac_proof = fetch_ipa(work)  # No release write before the producer gates pass.
    paths += ipa_paths
    checksum_file(paths, work / SUMS)
    paths.append(work / SUMS)
    names, verified = {path.name for path in paths}, []
    for path in paths:
        release = release_gate(api(f"releases/{RELEASE}"))
        need({row["name"] for row in release["assets"]} <= names, "draft_contains_unreviewed_assets")
        selected = [row for row in release["assets"] if row["name"] == path.name]
        if not selected:
            subprocess.run(["gh", "release", "upload", TAG, str(path), "--repo", REPO], check=True, timeout=600)
            release = release_gate(api(f"releases/{RELEASE}"))
            selected = [row for row in release["assets"] if row["name"] == path.name]
        need(len(selected) == 1, "release_asset_missing_or_duplicated")
        verify_remote(selected[0], path)
        verified.append({"name": path.name, "bytes": path.stat().st_size, "sha256": sha(path), "asset_id": selected[0]["id"]})
    release_gate(api(f"releases/{RELEASE}"))
    proof = {"schema": 1, "draft": True, "published": False, "release_id": RELEASE,
             "source_commit": SOURCE, "mac_producer": mac_proof, "verified_assets": verified,
             "android_producer": {"run_id": os.environ.get("GITHUB_RUN_ID"),
                "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                "delivery_workflow_commit": os.environ.get("GITHUB_SHA"),
                "event": os.environ.get("GITHUB_EVENT_NAME")}}
    (work / "draft-staging-proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fetch", "checksums", "stage"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()
    if args.action == "fetch": fetch_inputs(args.directory)
    elif args.action == "checksums": checksum_file(apk_files(args.directory), args.directory / "SHA256SUMS")
    else:
        need(args.work is not None, "fresh_staging_directory_required")
        stage(args.directory, args.work)


if __name__ == "__main__":
    main()
