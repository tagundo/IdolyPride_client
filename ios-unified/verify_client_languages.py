#!/usr/bin/env python3
"""Reconstruct all prebuilt client Data variants on an owned Mac build host.

This validates real resources with the same worker used by the embedded server.
It does not execute Unity or claim physical iPhone/PlayCover compatibility.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import plistlib
import sys
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from idoly_local.ios_client_data import BUNDLE_ID, MAX_MANIFEST, prepare_client_data, validate_manifest


def need(value, message):
    if not value:
        raise ValueError(message)


def source_pins():
    inputs = json.loads((HERE / "runtime_inputs.json").read_text())["inputs"]
    return {field: inputs[key]["sha256"] for field, key in (
        ("stock_ipa_sha256", "stock_ipa"), ("base_ipa_sha256", "base_ipa"),
        ("english_ui_sha256", "english_ui"))}


def verify(prepared_app, workspace, *, expected_sources=None):
    prepared_app, workspace = Path(prepared_app), Path(workspace)
    need(prepared_app.is_absolute() and prepared_app.is_dir() and not prepared_app.is_symlink(),
         "Absolute prepared app directory required")
    need(workspace.is_absolute() and not workspace.exists() and not workspace.is_symlink(),
         "Fresh absolute language verification workspace required")
    app, work = prepared_app.resolve(strict=True), workspace.resolve(strict=False)
    need(not app.is_relative_to(work) and not work.is_relative_to(app),
         "Language verification must not modify the prepared app")
    package = app / "LocalServer/client-languages.zip"
    need(package.is_file() and not package.is_symlink(), "Prepared client-language package required")
    with ZipFile(package) as archive:
        info = archive.getinfo("manifest.json")
        need(0 < info.file_size <= MAX_MANIFEST, "Client-language manifest exceeds bound")
        manifest = validate_manifest(json.loads(archive.read(info)))
    need(manifest["source"] == (source_pins() if expected_sources is None else expected_sources),
         "Prepared language source pins differ")
    workspace.mkdir(mode=0o700, parents=True)
    rows = []
    for language in ("ja", "ko", "en"):
        first = prepare_client_data(app, workspace, language)
        second = prepare_client_data(app, workspace, language)
        expected_files = len(manifest["common"]) + len(manifest["languages"][language])
        need(first.get("reused") is False and second.get("reused") is True,
             "Language preparation or verified cache reuse failed")
        for result in (first, second):
            need(result.get("language") == language and result.get("bundle_id") == BUNDLE_ID
                 and type(result.get("files")) is int and result["files"] == expected_files and expected_files > 0,
                 "Prepared language identity or file count differs")
        bundle = Path(second["bundle_path"]).resolve(strict=True)
        need(bundle.is_relative_to(workspace.resolve(strict=True)) and bundle.name == language + ".bundle",
             "Prepared language bundle escaped its verification workspace")
        info_path = bundle / "Info.plist"
        need(info_path.is_file() and not info_path.is_symlink() and info_path.stat().st_size <= 16384,
             "Prepared language bundle metadata invalid")
        metadata = plistlib.loads(info_path.read_bytes())
        need(metadata.get("CFBundleIdentifier") == BUNDLE_ID and metadata.get("CFBundlePackageType") == "BNDL"
             and "CFBundleExecutable" not in metadata, "Prepared language bundle must be resource-only")
        data_files = [path for path in (bundle / "Data").rglob("*") if path.is_file()]
        need(len(data_files) == expected_files and all(not path.is_symlink() and not path.stat().st_mode & 0o111 for path in data_files),
             "Prepared language Data must be complete and nonexecutable")
        rows.append({"language": language, "bundle_id": BUNDLE_ID, "files": expected_files,
                     "first_reused": False, "second_reused": True, "resource_only_bundle": True})
    return {"schema": 1, "status": "PASS", "execution": "offline_client_data_reconstruction",
            "source": manifest["source"], "common_files": len(manifest["common"]), "languages": rows,
            "all_source_and_output_hashes_verified_by_runtime": True,
            "signed_app_modified": False, "Unity_executed": False, "physical_PlayCover_execution": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-app", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    need(args.report.is_absolute() and not args.report.exists() and not args.report.is_symlink(),
         "Fresh absolute language verification report required")
    need(not args.report.resolve(strict=False).is_relative_to(args.prepared_app.resolve(strict=False)),
         "Language verification report must not modify the prepared app")
    report = {"schema": 1, "status": "FAIL", "execution": "offline_client_data_reconstruction",
              "Unity_executed": False, "physical_PlayCover_execution": False}
    try:
        need(sys.platform == "darwin", "Actual Mac build host required for the complete resource check")
        report = verify(args.prepared_app, args.work)
    except Exception as error:
        report["error_type"] = type(error).__name__
        if isinstance(error, ValueError): report["error"] = str(error)[:500]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x") as stream:
        json.dump(report, stream, indent=2); stream.write("\n")
    print(json.dumps({"status": report["status"], "report": str(args.report),
                      "Unity_executed": False}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
