#!/usr/bin/env python3
"""Compare Runtime.status polling using public, synthetic diagnostic events only.

Run on a build runner with two trusted source checkouts. Every root/repeat gets
an isolated child interpreter; no server, database, game files or network is used.
The fresh --work directory and exclusive --output file are the only writes.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
from pathlib import Path
import selectors
import statistics
import subprocess
import sys
import time

EVENT_COUNT = 200
FRAME_COUNT = 16
STDOUT_LIMIT = 32768
STDERR_LIMIT = 16384
WORKER_TIMEOUT = 180.0


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_hash(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


MANAGEMENT_KEYS = ("durable_history", "startup_checks", "account_selection")
ROLES = ("baseline", "candidate")


def strict_equal(actual, expected):
    """JSON comparison must not accept Python's True == 1 equivalence."""
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(strict_equal(actual[key], value) for key, value in expected.items())
    if type(expected) is list:
        return len(actual) == len(expected) and all(strict_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def management_defaults():
    return {
        "durable_history": {"schema": 1, "available": False, "load_state": "unavailable",
            "persistence": "unavailable", "last_write_error": None, "current_run": None,
            "retained_records": 0, "total_records": 0, "records": [],
            "last_failure": None, "last_startup": None},
        "startup_checks": {"schema": 1, "scope": "not_run", "run_id": None, "started_at": None,
            "updated_at": None, "state": "not_run", "gameplay_verified": False, "checks": []},
        "account_selection": {"active_profile": "sandbox", "selected_for_next_start": "sandbox",
            "selection_revision": None, "invalid_registry": False, "restart_required": False},
    }


def comparison_scope():
    return {"schema": 1, "name": "legacy-runtime-status-v1",
            "excluded_runtime_fields_after_validation": list(MANAGEMENT_KEYS),
            "canonical_comparison": "untimed",
            "timed_operation": "full Runtime.status()",
            "tracemalloc_operation": "full Runtime.status()"}


def management_contract():
    return {"schema": 1, "name": "unbound-runtime-management-v1",
            "baseline": "all_three_fields_absent", "candidate": "all_three_exact_defaults",
            "candidate_defaults": management_defaults()}


def expected_management_evidence(role):
    require(role in ROLES and type(role) is str, "Benchmark worker role is invalid")
    return {"schema": 1, "role": role,
            "poll": management_defaults() if role == "candidate" else {},
            "export_runtime": management_defaults() if role == "candidate" else {}}


def project_outputs(poll, exported, role):
    """Validate exactly three additions, then retain every other key/value."""
    require(type(poll) is dict and type(exported) is dict and type(exported.get("runtime")) is dict,
            "Benchmark output objects are invalid")
    runtime = exported["runtime"]
    require(type(poll.get("profile")) is str and poll["profile"] == "sandbox"
            and type(runtime.get("profile")) is str and runtime["profile"] == "sandbox"
            and poll.get("running") is False and runtime.get("running") is False,
            "Benchmark requires a fresh unbound sandbox Runtime")
    evidence = {"schema": 1, "role": role,
                "poll": {key: poll[key] for key in MANAGEMENT_KEYS if key in poll},
                "export_runtime": {key: runtime[key] for key in MANAGEMENT_KEYS if key in runtime}}
    require(strict_equal(evidence, expected_management_evidence(role)),
            "Runtime management contract differs for " + str(role))
    legacy_poll = {key: value for key, value in poll.items() if key not in MANAGEMENT_KEYS}
    legacy_export = dict(exported)
    legacy_export["runtime"] = {key: value for key, value in runtime.items() if key not in MANAGEMENT_KEYS}
    return legacy_poll, legacy_export, evidence


def validate_worker_comparison(row, role):
    require(type(row) is dict and type(row.get("role")) is str and row["role"] == role,
            "Benchmark worker role differs")
    require(strict_equal(row.get("comparison_scope"), comparison_scope())
            and strict_equal(row.get("management_contract"), expected_management_evidence(role)),
            "Benchmark worker comparison contract differs")
    for key in ("summary_sha256", "poll_sha256", "export_sha256", "full_poll_sha256", "full_export_sha256", "benchmark_sha256"):
        require(type(row.get(key)) is str and re.fullmatch(r"[0-9a-f]{64}", row[key]) is not None,
                "Benchmark worker output hash is invalid")
    same = role == "baseline"
    require((row["full_poll_sha256"] == row["poll_sha256"]) is same
            and (row["full_export_sha256"] == row["export_sha256"]) is same,
            "Benchmark full/projected output relation differs")


def compare_outputs(rows):
    require(type(rows) is dict and set(rows) == set(ROLES), "Benchmark role set differs")
    for role, group in rows.items():
        require(type(group) is list and group, "Benchmark role has no runs")
        for row in group:
            validate_worker_comparison(row, role)
    hashes = {}
    for key in ("summary_sha256", "poll_sha256", "export_sha256"):
        values = {row[key] for group in rows.values() for row in group}
        require(len(values) == 1, "Baseline/candidate legacy output mismatch: " + key)
        hashes[key] = next(iter(values))
    full_outputs = {}
    for role, group in rows.items():
        full_outputs[role] = {}
        for key in ("poll_sha256", "export_sha256"):
            values = {row["full_" + key] for row in group}
            require(len(values) == 1, "Full output changed between runs: " + role)
            full_outputs[role][key] = next(iter(values))
    return hashes, full_outputs


def source_root(value):
    root = Path(value).resolve(strict=True)
    require(root.is_dir(), "Source root must be a directory")
    for name in ("app_runtime.py", "diagnostics.py"):
        path = root / "src" / "idoly_local" / name
        require(path.is_file() and path.resolve().is_relative_to(root), "Trusted source module is missing or escapes its root")
    return root


def source_hashes(root):
    result = {}
    for name in ("diagnostics.py", "app_runtime.py"):
        path = root / "src" / "idoly_local" / name
        require(0 < path.stat().st_size <= 2 * 1024**2, "Source module exceeds the benchmark identity limit")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def bounded_integer(value):
    number = int(value)
    if not 1 <= number <= 10000:
        raise argparse.ArgumentTypeError("Expected an integer from 1 to 10000")
    return number


def worker(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", required=True)
    parser.add_argument("--role", choices=ROLES, required=True)
    parser.add_argument("--iterations", required=True, type=bounded_integer)
    parser.add_argument("--tracemalloc", action="store_true")
    args = parser.parse_args(argv)
    require(sys.flags.isolated and sys.dont_write_bytecode, "Worker requires isolated mode and disabled bytecode writes")
    root = source_root(args.root)
    src = root / "src"
    sys.path.insert(0, str(src))
    runtime_module = importlib.import_module("idoly_local.app_runtime")
    diagnostics_module = importlib.import_module("idoly_local.diagnostics")
    for module in (runtime_module, diagnostics_module):
        require(Path(module.__file__).resolve().is_relative_to(src), "Import came from a different source checkout")
    runtime = runtime_module.Runtime("sandbox")
    events = [{"kind": "exception", "type": "Bench.SyntheticException",
               "frames": [f"Bench.Event{index:03d}.Frame{frame:02d}" for frame in range(FRAME_COUNT)]}
              for index in range(EVENT_COUNT)]
    for start in range(0, EVENT_COUNT, 32):
        batch = events[start:start + 32]
        raw = json.dumps({"schema": 1, "source": "android-game", "events": batch}).encode("utf-8")
        require(runtime._diagnostics.receive(raw)["accepted"] == len(batch), "Synthetic intake did not accept the batch")
    poll = runtime.status()
    summary = poll["client_diagnostics"]
    require("events" not in summary, "Routine polling leaked the full history")
    require(summary["received_events"] == EVENT_COUNT and summary["stored_events"] == EVENT_COUNT,
            "Routine polling lost event counts")
    default_full = runtime._diagnostics.status()
    require(default_full["events"] == events, "Default diagnostics API did not preserve the full bounded history")
    exported = runtime.diagnostics_snapshot()
    require(exported["client_diagnostics"]["events"] == events, "Explicit export lost diagnostic events or frames")
    require("events" not in exported["runtime"]["client_diagnostics"], "Export's runtime summary contains history")

    # Comparison/projection is untimed; polling and allocation loops below
    # continue to call the full, unmodified Runtime.status().
    legacy_poll, legacy_export, evidence = project_outputs(poll, exported, args.role)

    # Instrument only outside timing. The baseline copies the whole history
    # during a routine poll; the candidate must avoid that discarded work.
    original = diagnostics_module.deepcopy
    def counted_history_copies(function):
        copies = 0
        def tracked(value):
            nonlocal copies
            if isinstance(value, dict) and isinstance(value.get("events"), list) and len(value["events"]) == EVENT_COUNT:
                copies += 1
            return original(value)
        diagnostics_module.deepcopy = tracked
        try:
            function()
        finally:
            diagnostics_module.deepcopy = original
        return copies
    copy_counts = {"poll": counted_history_copies(runtime.status),
                   "explicit_export": counted_history_copies(runtime.diagnostics_snapshot)}
    for _ in range(10):
        runtime.status()
    wall_start, cpu_start = time.perf_counter(), time.process_time()
    for _ in range(args.iterations):
        runtime.status()
    cpu_seconds = time.process_time() - cpu_start
    wall_seconds = time.perf_counter() - wall_start
    peak_bytes = None
    if args.tracemalloc:
        import tracemalloc
        tracemalloc.start()
        try:
            for _ in range(args.iterations):
                runtime.status()
            peak_bytes = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
    result = {"schema": 1, "role": args.role, "source_root": str(root), "iterations": args.iterations,
              "synthetic_events": EVENT_COUNT, "frames_per_event": FRAME_COUNT,
              "poll_contains_events": False, "received_events": summary["received_events"],
              "stored_events": summary["stored_events"], "default_full_events": len(default_full["events"]),
              "exported_events": len(exported["client_diagnostics"]["events"]),
              "summary_sha256": canonical_hash(summary), "poll_sha256": canonical_hash(legacy_poll),
              "export_sha256": canonical_hash(legacy_export), "full_poll_sha256": canonical_hash(poll),
              "full_export_sha256": canonical_hash(exported), "comparison_scope": comparison_scope(),
              "management_contract": evidence,
              "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "history_deepcopy_calls": copy_counts,
              "wall_seconds": wall_seconds, "process_cpu_seconds": cpu_seconds,
              "wall_microseconds_per_poll": wall_seconds * 1e6 / args.iterations,
              "cpu_microseconds_per_poll": cpu_seconds * 1e6 / args.iterations,
              "tracemalloc_peak_bytes": peak_bytes}
    print(json.dumps(result, sort_keys=True, allow_nan=False))


def run_worker(script, root, cwd, iterations, trace, role):
    command = [sys.executable, "-I", "-B", str(script), "--_worker", "--root", str(root),
               "--iterations", str(iterations), "--role", role]
    if trace:
        command.append("--tracemalloc")
    process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + WORKER_TIMEOUT
    selector = selectors.DefaultSelector()
    try:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            remaining = deadline - time.monotonic()
            require(remaining > 0, "Benchmark worker exceeded its time limit")
            for key, _ in selector.select(min(remaining, 0.25)):
                block = os.read(key.fd, 4096)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                target = buffers[key.data]
                limit = STDOUT_LIMIT if key.data == "stdout" else STDERR_LIMIT
                require(len(target) + len(block) <= limit, "Benchmark worker exceeded its output limit")
                target.extend(block)
        remaining = max(0.01, deadline - time.monotonic())
        code = process.wait(timeout=remaining)
        require(code == 0, "Benchmark worker failed: " + bytes(buffers["stderr"]).decode("utf-8", errors="replace")[:2000])
        require(not buffers["stderr"], "Benchmark worker emitted unexpected stderr")
        result = json.loads(bytes(buffers["stdout"]).decode("utf-8"))
        require(type(result) is dict and type(result.get("schema")) is int and result["schema"] == 1,
                "Malformed benchmark worker result")
        validate_worker_comparison(result, role)
        require(result["benchmark_sha256"] == hashlib.sha256(Path(script).read_bytes()).hexdigest(),
                "Benchmark worker script provenance differs")
        require(result.get("source_root") == str(root) and type(result.get("iterations")) is int
                and result["iterations"] == iterations, "Benchmark worker provenance differs")
        require((type(result.get("tracemalloc_peak_bytes")) is int and result["tracemalloc_peak_bytes"] > 0)
                if trace else result.get("tracemalloc_peak_bytes") is None,
                "Benchmark allocation observation differs")
        return result
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()


def coordinator(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", required=True)
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--iterations", type=bounded_integer, default=1000)
    parser.add_argument("--repeats", type=bounded_integer, default=3)
    parser.add_argument("--tracemalloc", action="store_true", help="Measure peak allocations in a separate, untimed pass")
    args = parser.parse_args(argv)
    require(args.repeats <= 10, "At most ten repeats are supported")
    roots = {"baseline": source_root(args.baseline_root), "candidate": source_root(args.candidate_root)}
    baseline, candidate = roots["baseline"], roots["candidate"]
    source_sha256 = {name: source_hashes(root) for name, root in roots.items()}
    require(not baseline.is_relative_to(candidate) and not candidate.is_relative_to(baseline),
            "Source roots must be distinct and non-overlapping")
    work = Path(args.work).resolve()
    output = Path(args.output).resolve()
    require(not work.exists() and not output.exists(), "Work directory and report must be fresh")
    for path in (work, output):
        require(not any(path.is_relative_to(root) for root in roots.values()), "Writes cannot be inside either source checkout")
    require(work.parent.is_dir(), "Work parent directory must already exist")
    require(output.parent == work or output.parent.is_dir(), "Report parent must exist or be the fresh work directory")
    work.mkdir(mode=0o700)
    rows = {name: [] for name in roots}
    script = Path(__file__).resolve(strict=True)
    benchmark_sha256 = hashlib.sha256(script.read_bytes()).hexdigest()
    for repeat in range(args.repeats):
        # Alternate order to reduce simple first/second-run ordering effects.
        order = ("baseline", "candidate") if repeat % 2 == 0 else ("candidate", "baseline")
        for name in order:
            child_cwd = work / f"{name}-{repeat + 1}"
            child_cwd.mkdir(mode=0o700)
            rows[name].append(run_worker(script, roots[name], child_cwd, args.iterations, args.tracemalloc, name))
    require(source_sha256 == {name: source_hashes(root) for name, root in roots.items()},
            "Benchmark source modules changed during measurement")
    require(benchmark_sha256 == hashlib.sha256(script.read_bytes()).hexdigest(),
            "Benchmark script changed during measurement")
    hashes, full_outputs = compare_outputs(rows)
    expected = {"baseline": {"poll": 1, "explicit_export": 2}, "candidate": {"poll": 0, "explicit_export": 1}}
    for name, group in rows.items():
        require(all(strict_equal(row["history_deepcopy_calls"], expected[name]) for row in group),
                "Unexpected full-history copy path: " + name)
    medians = {name: {key: statistics.median(row[key] for row in group)
                      for key in ("wall_microseconds_per_poll", "cpu_microseconds_per_poll")}
               for name, group in rows.items()}
    report = {"schema": 1, "benchmark": "Runtime.status synthetic diagnostics polling", "python": sys.version,
              "iterations": args.iterations, "repeats": args.repeats,
              "source_sha256": source_sha256,
              "tracemalloc_separate_pass": args.tracemalloc, "identical_legacy_outputs": hashes,
              "comparison_scope": comparison_scope(), "management_contract": management_contract(),
              "full_outputs": full_outputs, "benchmark_sha256": benchmark_sha256,
              "expected_history_deepcopy_calls": expected, "median": medians, "runs": rows,
              "median_speedup": {key: medians["baseline"][key] / medians["candidate"][key]
                                 for key in medians["baseline"]}}
    encoded = json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
    require(len(encoded.encode("utf-8")) <= 131072, "Benchmark report exceeded its output limit")
    with output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
    print(json.dumps({"report": str(output), "identical_legacy_outputs": hashes,
                      "comparison_scope": comparison_scope(), "full_outputs": full_outputs, "median": medians,
                      "median_speedup": report["median_speedup"]}, sort_keys=True))


def main():
    try:
        if sys.argv[1:2] == ["--_worker"]:
            worker(sys.argv[2:])
        else:
            coordinator(sys.argv[1:])
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error)[:2200], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
