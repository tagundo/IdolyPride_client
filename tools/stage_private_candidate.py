#!/usr/bin/env python3
"""Stage two verified, date-named private Actions downloads without publishing.

Only the same-run artifact metadata and binary archives are fetched. Existing
platform and iOS verification functions run before owned copies are created.
This tool has no release, tag, branch, LFS or publication operation.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CHUNK = 128 * 1024
PRIMARY_ROLES = ("android", "ios-unified")
REQUIRED_JOBS = ("portable", "performance", "android", "android-clients", "ios-unified")


class PrivateCandidateError(ValueError):
    pass


def need(condition, code):
    if not condition:
        raise PrivateCandidateError(code)


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def identity(path):
    value = Path(path).lstat()
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def stage_copies(rows, output, version, publisher, names, guard):
    """Keep all verified raw input files and proof paths unchanged."""
    version = names.resolve_release_version(version)
    need(type(rows) is list and len(rows) == 2 and all(type(row) is dict for row in rows)
         and {row.get("name") for row in rows} == {publisher.APK, publisher.IPA},
         "private_primary_inventory_differs")
    checked = []
    for row in rows:
        plain = {key: row[key] for key in ("name", "bytes", "sha256")}
        source = Path(row["path"])
        need(source.name == row["name"], "private_source_name_differs")
        publisher.verified_file(source.parent, plain)
        checked.append((source, identity(source), plain))
    output = Path(output)
    need(not output.exists() and not output.is_symlink(), "private_fresh_output_required")
    output.mkdir(mode=0o700)
    result = []
    roles = {publisher.APK: "android", publisher.IPA: "ios-unified"}
    for source, before, plain in checked:
        guard.check()
        role = roles[plain["name"]]
        directory = output / role
        directory.mkdir(mode=0o700)
        target = directory / names.asset_name(plain["name"], version)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(source, flags)
        with os.fdopen(descriptor, "rb") as incoming:
            opened = os.fstat(incoming.fileno())
            need(stat.S_ISREG(opened.st_mode)
                 and (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_size,
                      opened.st_mtime_ns, opened.st_ctime_ns) == before,
                 "private_source_changed")
            value, count = hashlib.sha256(), 0
            with target.open("xb") as outgoing:
                while block := incoming.read(CHUNK):
                    guard.check()
                    count += len(block)
                    need(count <= plain["bytes"], "private_binary_extent_differs")
                    value.update(block)
                    need(outgoing.write(block) == len(block), "private_binary_short_write")
                outgoing.flush()
                os.fsync(outgoing.fileno())
            need(count == plain["bytes"] and value.hexdigest() == plain["sha256"]
                 and identity(source) == before, "private_source_changed")
        final = {"name": target.name, "bytes": plain["bytes"], "sha256": plain["sha256"]}
        publisher.verified_file(directory, final)
        result.append({**final, "source_name": plain["name"], "artifact_directory": role})
    return result


def stage_candidate(source, run, version, work, output, token):
    publisher = module("private_candidate_verification", "tools/publish_optimized_release.py")
    delivery = module("private_candidate_ios_verification", "ios-unified/delivery.py")
    names = module("private_candidate_names", "tools/release_identity.py")
    version = names.resolve_release_version(version)
    need(type(source) is str and re.fullmatch(r"[0-9a-f]{40}", source)
         and type(run) is int and run > 0, "private_run_identity_invalid")
    work, output = Path(work), Path(output)
    need(not work.exists() and not work.is_symlink() and not output.exists()
         and not output.is_symlink() and work != output, "private_fresh_directories_required")
    guard = delivery.Guard()
    work.mkdir(mode=0o700)
    github = publisher.GitHub(token, delivery.OPENER)
    # These are the only GitHub API calls. The existing validator requires all
    # five required verification jobs and immutable same-source artifact digests.
    build = github.api("/actions/runs/" + str(run))
    jobs = github.api("/actions/runs/" + str(run) + "/jobs?filter=latest&per_page=100")
    artifacts = github.api("/actions/runs/" + str(run) + "/artifacts?per_page=100")
    need(build.get("event") == "workflow_dispatch", "private_manual_run_required")
    bindings = publisher.validate_run(build, jobs, artifacts, source, run)
    need(type(publisher.JOBS) in (tuple, list) and tuple(publisher.JOBS) == REQUIRED_JOBS
         and type(bindings) is dict and set(bindings) == set(REQUIRED_JOBS),
         "private_required_artifacts_differs")
    directories = {}
    for role in PRIMARY_ROLES:
        guard.check()
        archive = work / (role + ".zip")
        delivery.fetch_archive(bindings[role], token, archive, guard)
        directory = work / role
        if role == "ios-unified":
            directory.mkdir(mode=0o700)
            delivery.extract_archive(archive, directory, bindings[role], guard)
        else:
            publisher.extract_generic(archive, directory, role, guard)
        archive.unlink()  # Only this tool's downloaded transport copy.
        directories[role] = directory
    rows, proof_files = [], {}
    for role in ("android",):
        path = directories[role] / "platform-report.json"
        report = publisher.validate_platform(publisher.read_json(path), role, source)
        rows.append(publisher.validate_platform_files(directories[role], report, guard))
        proof_files[role] = {"name": path.name, "sha256": publisher.digest(path)}
    ios_proof = work / "ios-verified"
    ios_proof.mkdir(mode=0o700)
    ios_manifest, _identity = delivery.verify_members(directories["ios-unified"], ios_proof,
        source, run, bindings["ios-unified"]["artifact_id"], guard)
    rows.extend(ios_manifest["artifacts"])
    path = directories["ios-unified"] / publisher.IPA.replace(".ipa", ".report.json")
    proof_files["ios-unified"] = {"name": path.name, "sha256": publisher.digest(path)}
    staged = stage_copies(rows, output, version, publisher, names, guard)
    manifest = {"schema": 1, "status": "PASS_PRIVATE_CANDIDATE", "candidate_version": version,
        "source_commit": source, "run_id": run, "official_release_published": False,
        "source_artifacts_preserved": True, "all_required_verification_jobs_passed": True,
        "required_verification_jobs": list(publisher.JOBS),
        "whole_API_archive_sha256_verified": True, "input_artifacts": bindings,
        "input_proofs": proof_files, "server_data": publisher.DATA_PIN,
        "server_data_preparation": publisher.LOVE_SERVER_DATA.load_pin()["upgrade_proof"],
        "internal_server_version": publisher.VERSION, "internal_ipa_version": publisher.IPA_VERSION,
        "artifacts": staged}
    publisher.write_json(output / "PRIVATE-CANDIDATE.json", manifest)
    for row in staged:
        directory = output / row["artifact_directory"]
        publisher.write_json(directory / "PRIVATE-CANDIDATE.json",
                             {**manifest, "artifact_role": row["artifact_directory"], "artifacts": [row]})
        (directory / "SHA256SUMS").write_text(row["sha256"] + "  " + row["name"] + "\n", encoding="utf-8")
        (directory / "README.txt").write_text("IdolyPride private candidate " + version + "\nSource: " + source
            + "\nActions: https://github.com/" + publisher.REPO + "/actions/runs/" + str(run)
            + "\n\nVerified changed executable: " + row["name"]
            + "\nOriginal build proofs remain in the same Actions run.\n"
            + "Android emulator and iOS Simulator checks passed. Mac uses the unified IPA.\n"
            + "Physical phone and PlayCover gameplay are not tested here.\n",
            encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    need(sys.platform.startswith("linux") and __debug__
         and args.source_commit == os.environ.get("GITHUB_SHA")
         and str(args.run_id) == os.environ.get("GITHUB_RUN_ID"), "private_remote_run_required")
    need(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
         == args.source_commit and subprocess.run(["git", "diff", "--quiet"], cwd=ROOT).returncode == 0,
         "private_checkout_source_differs")
    runner = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    for path in (args.work, args.output):
        need(path.is_absolute() and path.parent.resolve(strict=True) == runner,
             "private_owned_runner_directory_required")
    need(shutil.disk_usage(runner).free >= 6 * 1024**3, "private_entry_disk_floor")
    os.umask(0o077)
    result = stage_candidate(args.source_commit, args.run_id, args.candidate_version,
                             args.work, args.output, os.environ["GH_TOKEN"])
    print(json.dumps({key: result[key] for key in ("status", "candidate_version", "source_commit", "artifacts")}))


if __name__ == "__main__":
    main()
