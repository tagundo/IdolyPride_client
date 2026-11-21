#!/usr/bin/env python3
"""Compare the shared translation-startup slice using pinned public inputs.

Run remotely on a machine with room for the public payload. This does not start
Unity, network listeners, or an application profile. Every measured run uses a
fresh pure-Python-protobuf subprocess and a new revision-state directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import statistics
import subprocess
import sys
import time

PINS = {
    "server_data": {"bytes": 191343014,
        "sha256": "37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"},
    "translations": {"bytes": 125717042,
        "sha256": "987fab065fbf791b37b9afe71c53979dc2186e711cde338c89ebe8e0ff905b72"},
}
BASELINE_REVISION = "50e349f4db6db0d3122bdc09c3b06307145f814f"
SOURCE_FILES = ("public_payload.py", "bundled_translations.py", "resource_translation.py",
                "resource_translation_runtime.py", "octo_manifest.py", "octo_runtime.py")
SEQUENCE = ("ja", "ko", "en", "ko")
MARKER = ".idoly-public-translation-benchmark.json"


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            result.update(block)
    return result.hexdigest()


def peak_rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def sources(root):
    directory = root / "src/idoly_local"
    return {name: digest(directory / name) for name in SOURCE_FILES}


def alias_digest(layer):
    result = hashlib.sha256()
    aliases = layer.object_aliases if layer is not None else {}
    for key, record in sorted(aliases.items()):
        row = (key, record.identity, record.size, record.md5, record.name)
        result.update(json.dumps(row, separators=(",", ":"), ensure_ascii=True).encode("ascii"))
        result.update(b"\n")
    return {"count": len(aliases), "sha256": result.hexdigest()}


def child(args):
    # -I keeps inherited PYTHONPATH out; the source root is selected explicitly.
    os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    source_root = args._source_root.resolve(strict=True)
    sys.path.insert(0, str(source_root / "src"))
    from google.protobuf.internal import api_implementation
    require(api_implementation.Type() == "python", "pure_python_protobuf_required")
    import google.protobuf
    from idoly_local.public_payload import install_payload
    from idoly_local.bundled_translations import install_translation_bundle
    from idoly_local.resource_translation_runtime import (
        select_resource_translation, validate_prepared_translations)
    from idoly_local.octo_runtime import load_octo_archive
    import idoly_local.resource_translation_runtime as runtime_module
    require(Path(runtime_module.__file__).resolve().is_relative_to(source_root / "src"),
            "wrong_project_source_imported")
    work = args.work.resolve(strict=True)
    require(json.loads((work / MARKER).read_text()) == {
        "schema": 1, "scope": "owned-public-payload-only"}, "work_marker_invalid")
    data, cache = work / "public-data", work / "public-resources"
    coverage = {}

    def validate(directory):
        result = validate_prepared_translations(directory, data, platform="ios")
        coverage.update(result)
        return result

    def install():
        return install_translation_bundle(args.translations, cache,
            expected_sha256=PINS["translations"]["sha256"],
            expected_bytes=PINS["translations"]["bytes"], platform="ios",
            validate_prepared=validate)

    started = time.perf_counter()
    if args._child == "setup":
        data.mkdir(mode=0o700)
        cache.mkdir(mode=0o700)
        installed = install_payload(args.server_data, data)
        translated = install()
        return {"schema": 1, "status": "PASS", "role": "setup",
                "installed": installed, "translations": translated, "coverage": coverage,
                "elapsed_seconds": time.perf_counter() - started,
                "peak_rss_bytes": peak_rss_bytes(), "protobuf": api_implementation.Type(),
                "protobuf_version": google.protobuf.__version__}

    state = args._run_dir / "revision-state"
    state.mkdir(mode=0o700, parents=True)
    installed = install()
    require(installed["state"] == "unchanged", "warm_prepared_package_reuse_required")
    validation_seconds = time.perf_counter() - started
    validation_peak = peak_rss_bytes()
    archive = load_octo_archive(data / "public-octo-ios", platform="ios")
    require(archive is not None, "pinned_original_catalog_missing")
    settings, original = archive
    del archive
    outputs = []
    for language in SEQUENCE:
        layer = None
        try:
            raw, layer, compatible = select_resource_translation(
                original, state, cache, language=language, platform="ios")
            path = state / "client-resource-revision-ios.json"
            revision_state = json.loads(path.read_text()) if path.exists() else None
            outputs.append({"language": language, "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                "manifest_bytes": len(raw), "compatible_previous_revisions": compatible,
                "coverage": dict(layer.report["coverage"]) if layer is not None else None,
                "aliases": alias_digest(layer), "revision_state": revision_state,
                "revision_state_sha256": digest(path) if path.exists() else None})
        finally:
            if layer is not None:
                layer.close()
                del layer
    return {"schema": 1, "status": "PASS", "role": "measure",
            "protobuf": api_implementation.Type(), "protobuf_version": google.protobuf.__version__,
            "elapsed_seconds": time.perf_counter() - started,
            "validation_seconds": validation_seconds,
            "validation_peak_rss_bytes": validation_peak, "peak_rss_bytes": peak_rss_bytes(),
            "semantics": {"coverage": coverage, "original_manifest_sha256": hashlib.sha256(original).hexdigest(),
                          "original_revision": settings["revision"], "sequence": outputs}}


def run_child(args, role, source_root, run_dir):
    command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
        "--baseline-root", str(args.baseline_root), "--candidate-root", str(args.candidate_root),
        "--server-data", str(args.server_data), "--translations", str(args.translations),
        "--work", str(args.work), "--output", str(args.output),
        "--_child", role, "--_source-root", str(source_root), "--_run-dir", str(run_dir)]
    env = dict(os.environ, PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION="python", PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(command, capture_output=True, timeout=args.timeout_seconds, env=env)
    require(len(result.stdout) <= 256 * 1024 and len(result.stderr) <= 65536, "child_output_exceeds_bound")
    if result.returncode:
        raise RuntimeError("benchmark_child_failed: " + result.stderr.decode("utf-8", errors="replace")[-8192:])
    value = json.loads(result.stdout)
    require(value.get("status") == "PASS" and value.get("protobuf") == "python", "invalid_child_result")
    return value


def benchmark(args):
    for name in ("baseline_root", "candidate_root", "server_data", "translations", "work", "output"):
        path = getattr(args, name)
        require(path.is_absolute(), "absolute_paths_required: " + name)
        require(not path.is_symlink(), "symlink_not_allowed: " + name)
    args.baseline_root = args.baseline_root.resolve(strict=True)
    args.candidate_root = args.candidate_root.resolve(strict=True)
    args.work = args.work.resolve(strict=False)
    args.output = args.output.resolve(strict=False)
    require(args.baseline_root != args.candidate_root, "distinct_source_roots_required")
    require(args.work != args.output, "distinct_work_and_output_required")
    require(not args.work.exists() and not args.output.exists(), "fresh_work_and_output_required")
    for root in (args.baseline_root, args.candidate_root):
        require((root / "src/idoly_local/resource_translation_runtime.py").is_file(), "source_snapshot_missing")
        require(not args.work.is_relative_to(root) and not args.output.is_relative_to(root),
                "benchmark_outputs_must_be_outside_source_roots")
    require(1 <= args.runs <= 5 and 30 <= args.timeout_seconds <= 900, "benchmark_bounds_invalid")
    inputs = {"server_data": args.server_data, "translations": args.translations}
    input_rows = {}
    for name, path in inputs.items():
        require(path.is_file() and path.stat().st_size == PINS[name]["bytes"], "input_size_mismatch: " + name)
        require(digest(path) == PINS[name]["sha256"], "input_hash_mismatch: " + name)
        input_rows[name] = dict(PINS[name])
    require(shutil.disk_usage(args.work.parent).free >= 2 * 1024**3, "two_GiB_public_workspace_required")
    before = {"baseline": sources(args.baseline_root), "candidate": sources(args.candidate_root)}
    args.work.mkdir(mode=0o700)
    (args.work / MARKER).write_text(json.dumps({"schema": 1, "scope": "owned-public-payload-only"}))
    setup = run_child(args, "setup", args.baseline_root, args.work / "setup")
    runs = {"baseline": [], "candidate": []}
    for index in range(args.runs):
        order = ("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline")
        for name in order:
            root = args.baseline_root if name == "baseline" else args.candidate_root
            row = run_child(args, "measure", root, args.work / (name + "-" + str(index + 1)))
            runs[name].append(row)
    expected = runs["baseline"][0]["semantics"]
    require(all(row["semantics"] == expected for rows in runs.values() for row in rows),
            "baseline_candidate_semantics_differ")
    require(before == {"baseline": sources(args.baseline_root), "candidate": sources(args.candidate_root)},
            "source_changed_during_benchmark")
    summaries = {}
    for name, rows in runs.items():
        summaries[name] = {key: statistics.median(row[key] for row in rows) for key in (
            "elapsed_seconds", "validation_seconds", "peak_rss_bytes", "validation_peak_rss_bytes")}
    return {"schema": 1, "status": "PASS", "platform": "ios", "protobuf": "python",
        "scope": "shared_translation_validation_and_revision_selection",
        "baseline_revision_expected": BASELINE_REVISION,
        "measurement": "fresh-process wall time and peak RSS; no current-footprint claim",
        "max_parallel_children": 1, "child_timeout_seconds": args.timeout_seconds,
        "inputs": input_rows, "source_sha256": before, "setup": setup,
        "same_semantics": True, "sequence": list(SEQUENCE), "runs_per_source": args.runs,
        "medians": summaries, "runs": runs,
        "median_peak_rss_saving_bytes": summaries["baseline"]["peak_rss_bytes"] - summaries["candidate"]["peak_rss_bytes"],
        "median_seconds_saved": summaries["baseline"]["elapsed_seconds"] - summaries["candidate"]["elapsed_seconds"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline-root", "candidate-root", "server-data", "translations", "work", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--_child", choices=("setup", "measure"), help=argparse.SUPPRESS)
    parser.add_argument("--_source-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--_run-dir", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args._child:
        result = child(args)
        print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
        return 0
    require(args.output.is_absolute() and not args.output.exists() and not args.output.is_symlink(),
            "fresh_absolute_output_required")
    for root in (args.baseline_root, args.candidate_root):
        require(not args.output.resolve().is_relative_to(root.resolve()),
                "benchmark_output_must_be_outside_source_roots")
    try:
        result = benchmark(args)
    except Exception as error:
        result = {"schema": 1, "status": "FAIL", "error": str(error)[:8192],
                  "error_type": type(error).__name__}
    require(args.output.is_absolute() and not args.output.exists() and not args.output.is_symlink(),
            "fresh_absolute_output_required")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
