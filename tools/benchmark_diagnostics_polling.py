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
    result = {"schema": 1, "source_root": str(root), "iterations": args.iterations,
              "synthetic_events": EVENT_COUNT, "frames_per_event": FRAME_COUNT,
              "poll_contains_events": False, "received_events": summary["received_events"],
              "stored_events": summary["stored_events"], "default_full_events": len(default_full["events"]),
              "exported_events": len(exported["client_diagnostics"]["events"]),
              "summary_sha256": canonical_hash(summary), "poll_sha256": canonical_hash(poll),
              "export_sha256": canonical_hash(exported), "history_deepcopy_calls": copy_counts,
              "wall_seconds": wall_seconds, "process_cpu_seconds": cpu_seconds,
              "wall_microseconds_per_poll": wall_seconds * 1e6 / args.iterations,
              "cpu_microseconds_per_poll": cpu_seconds * 1e6 / args.iterations,
              "tracemalloc_peak_bytes": peak_bytes}
    print(json.dumps(result, sort_keys=True, allow_nan=False))


def run_worker(script, root, cwd, iterations, trace):
    command = [sys.executable, "-I", "-B", str(script), "--_worker", "--root", str(root),
               "--iterations", str(iterations)]
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
        require(isinstance(result, dict) and result.get("schema") == 1, "Malformed benchmark worker result")
        require(result.get("source_root") == str(root) and result.get("iterations") == iterations,
                "Benchmark worker provenance differs")
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
    for repeat in range(args.repeats):
        # Alternate order to reduce simple first/second-run ordering effects.
        order = ("baseline", "candidate") if repeat % 2 == 0 else ("candidate", "baseline")
        for name in order:
            child_cwd = work / f"{name}-{repeat + 1}"
            child_cwd.mkdir(mode=0o700)
            rows[name].append(run_worker(script, roots[name], child_cwd, args.iterations, args.tracemalloc))
    require(source_sha256 == {name: source_hashes(root) for name, root in roots.items()},
            "Benchmark source modules changed during measurement")
    hashes = {}
    for key in ("summary_sha256", "poll_sha256", "export_sha256"):
        values = {row[key] for group in rows.values() for row in group}
        require(len(values) == 1, "Baseline/candidate output mismatch: " + key)
        hashes[key] = next(iter(values))
    expected = {"baseline": {"poll": 1, "explicit_export": 2}, "candidate": {"poll": 0, "explicit_export": 1}}
    for name, group in rows.items():
        require(all(row["history_deepcopy_calls"] == expected[name] for row in group),
                "Unexpected full-history copy path: " + name)
    medians = {name: {key: statistics.median(row[key] for row in group)
                      for key in ("wall_microseconds_per_poll", "cpu_microseconds_per_poll")}
               for name, group in rows.items()}
    report = {"schema": 1, "benchmark": "Runtime.status synthetic diagnostics polling", "python": sys.version,
              "iterations": args.iterations, "repeats": args.repeats,
              "source_sha256": source_sha256,
              "tracemalloc_separate_pass": args.tracemalloc, "identical_outputs": hashes,
              "expected_history_deepcopy_calls": expected, "median": medians, "runs": rows,
              "median_speedup": {key: medians["baseline"][key] / medians["candidate"][key]
                                 for key in medians["baseline"]}}
    encoded = json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
    require(len(encoded.encode("utf-8")) <= 131072, "Benchmark report exceeded its output limit")
    with output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
    print(json.dumps({"report": str(output), "identical_outputs": hashes, "median": medians,
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
