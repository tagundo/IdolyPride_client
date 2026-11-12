#!/usr/bin/env python3
"""Read-only Android physical-device MV measurement preparation.

The game must already be playing. This samples one exact SurfaceView's legacy
SurfaceFlinger actualPresent timestamps, not Unity CPU/GPU times or gfxinfo FPS.
No SDK install, app launch, setting change, trace capture or upload is performed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import selectors
import shlex
import subprocess
import sys
import time


PENDING = 2**63 - 1
MAX_OUTPUT = 65536
MAX_SAMPLES = 20000
STALE_TAIL_SECONDS = 2.0
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+")
SERIAL = re.compile(r"[A-Za-z0-9_:.%\[\]-]{1,128}")


@dataclass
class Reply:
    text: str = ""
    error: str | None = None


def bounded_command(argv: list[str], timeout: float) -> Reply:
    """Bound both local adb output and wall time; kill only this owned client."""
    try:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError:
        return Reply(error="adb_unavailable")
    output = bytearray()
    failure = None
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    failure = "command_timeout"
                    break
                for key, _ in selector.select(remaining):
                    block = os.read(key.fd, min(4096, MAX_OUTPUT + 1 - len(output)))
                    if not block:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(block)
                        if len(output) > MAX_OUTPUT:
                            failure = "output_limit"
                            break
                if failure:
                    break
        if failure is None:
            try:
                process.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                failure = "command_timeout"
        text = output.decode("utf-8", "replace")
        if failure is None and process.returncode:
            failure = "command_failed"
        if re.search(r"permission denial|permission denied|not permitted", text, re.I):
            failure = "permission_denied"
        elif re.search(r"unknown command|unknown option|not found", text, re.I):
            failure = failure or "unsupported_command"
        return Reply(text if failure is None else "", failure)
    finally:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass  # Do not turn a bounded sampler into an indefinite host wait.
        process.stdout.close()


class Adb:
    def __init__(self, serial: str, executable: str = "adb", runner=bounded_command):
        if not SERIAL.fullmatch(serial):
            raise ValueError("Invalid explicit adb serial")
        self.serial, self.executable, self.runner = serial, executable, runner

    def shell(self, *parts: str, timeout: float = 2.0) -> Reply:
        # adb shell rejoins arguments into a REMOTE shell command. Quote the
        # entire command, including layer names containing spaces/$/parentheses.
        return self.runner([self.executable, "-s", self.serial, "shell", shlex.join(parts)], timeout)


def candidates(raw: str, package: str) -> list[str]:
    match_package = re.compile(r"(?<![A-Za-z0-9_.])" + re.escape(package) + r"(?![A-Za-z0-9_.])")
    return sorted({line.strip() for line in raw.splitlines()
                   if "SurfaceView" in line and not line.strip().startswith("Background for ")
                   and match_package.search(line)})


def choose_layer(layers: list[str], explicit: str | None) -> str | None:
    if explicit is not None:
        if len(explicit) > 2048 or any(c in explicit for c in "\n\r\0"):
            return None
        return explicit if explicit in layers else None
    return layers[0] if len(layers) == 1 else None


def parse_latency(raw: str) -> dict:
    """AOSP columns: desiredPresentTime, actualPresentTime, frameReadyTime."""
    period = None
    timestamps = []
    invalid = backward = duplicate = malformed = 0
    for line in raw.splitlines():
        parts = line.split()
        if not parts:
            continue
        if len(parts) == 1 and period is None and re.fullmatch(r"\d+", parts[0]):
            value = int(parts[0])
            period = value if 0 < value < 1_000_000_000 else None
            continue
        if len(parts) != 3 or not all(re.fullmatch(r"-?\d+", part) for part in parts):
            malformed += 1
            continue
        actual = int(parts[1])
        if not 0 < actual < PENDING:
            invalid += 1
        elif timestamps and actual == timestamps[-1]:
            duplicate += 1
        elif timestamps and actual < timestamps[-1]:
            backward += 1
        else:
            timestamps.append(actual)
    return {"period_ns": period, "timestamps": timestamps, "invalid_or_pending": invalid,
            "backward_rows": backward, "duplicate_rows": duplicate, "malformed_rows": malformed}


def percentile(values: list[int], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    at = (len(ordered) - 1) * fraction
    low = math.floor(at)
    return round((ordered[low] + (ordered[math.ceil(at)] - ordered[low]) * (at - low)) / 1e6, 3)


def summarize(segment: dict) -> dict:
    frames = segment["actual_present_ns"]
    intervals = [b - a for a, b in zip(frames, frames[1:])]
    return {**segment, "new_present_count": len(frames), "interval_count": len(intervals),
            "sampled_span_seconds": round((frames[-1] - frames[0]) / 1e9, 6) if len(frames) > 1 else None,
            "interval_ms": {"p50": percentile(intervals, .5), "p95": percentile(intervals, .95),
                            "p99": percentile(intervals, .99), "max": round(max(intervals) / 1e6, 3) if intervals else None},
            "intervals_over_50ms": sum(value > 50_000_000 for value in intervals),
            "sf_reported_refresh_hz": round(1e9 / segment["period_ns"], 3) if segment["period_ns"] else None}


def capture(adb: Adb, package: str, layer: str, initial_layers: list[str], duration: float,
            clock=time.monotonic, sleep=time.sleep) -> dict:
    started = clock()
    deadline = started + duration
    segments = []
    active = None
    previous = set()
    high = None
    repeated = 0
    first_new_poll = last_new_poll = None
    errors = []
    polls = []
    status = "completed"
    current_layers = initial_layers

    def start_segment(reason, parsed):
        nonlocal active, previous, high
        active = {"reason": reason, "period_ns": parsed["period_ns"], "actual_present_ns": [],
                  "baseline_discarded": len(parsed["timestamps"])}
        segments.append(active)
        previous = set(parsed["timestamps"])
        high = max(previous) if previous else None

    while clock() < deadline:
        timeout = min(2.0, max(.01, deadline - clock()))
        listed = adb.shell("dumpsys", "SurfaceFlinger", "--list", timeout=timeout)
        if listed.error:
            errors.append(listed.error)
            status = "unknown"
            break
        current_layers = candidates(listed.text, package)
        if current_layers != initial_layers:
            status = "layer_changed"
            errors.append("surface_set_changed; no frames across this transition are combined")
            if active is not None:
                active["end_reason"] = "layer_changed"
            break
        if clock() >= deadline:
            break
        reply = adb.shell("dumpsys", "SurfaceFlinger", "--latency", layer,
                          timeout=min(2.0, max(.01, deadline - clock())))
        if reply.error:
            errors.append(reply.error)
            status = "unknown"
            break
        parsed = parse_latency(reply.text)
        timestamps = parsed.pop("timestamps")
        polls.append({"elapsed_seconds": round(clock() - started, 3), **parsed,
                      "valid_rows": len(timestamps)})
        parsed["timestamps"] = timestamps
        if not timestamps:
            errors.append("no_valid_present_timestamps")
        elif active is None:
            start_segment("initial_history_discarded", parsed)
        elif parsed["period_ns"] != active["period_ns"]:
            reason = "reported_refresh_changed" if parsed["period_ns"] and active["period_ns"] else "refresh_metadata_changed"
            active["end_reason"] = reason
            start_segment(reason, parsed)
        elif high is not None and timestamps[-1] < high:
            active["end_reason"] = "timestamp_reset"
            start_segment("timestamp_reset", parsed)
            errors.append("timestamp_reset; intervals exclude discontinuity")
        elif high is not None and timestamps[-1] > high and not previous.intersection(timestamps):
            active["end_reason"] = "history_overlap_lost"
            start_segment("history_overlap_lost", parsed)
            errors.append("history_overlap_lost; intervals exclude missing coverage")
        else:
            new = [value for value in timestamps if high is None or value > high]
            if not new:
                repeated += 1
            remaining = MAX_SAMPLES - sum(len(segment["actual_present_ns"]) for segment in segments)
            accepted = new[:remaining]
            active["actual_present_ns"].extend(accepted)
            if accepted:
                last_new_poll = clock() - started
                if first_new_poll is None:
                    first_new_poll = last_new_poll
            previous = set(timestamps)
            high = timestamps[-1]
        if sum(len(segment["actual_present_ns"]) for segment in segments) >= MAX_SAMPLES:
            status = "sample_limit"
            break
        sleep(min(.5, max(0, deadline - clock())))
    summaries = [summarize(segment) for segment in segments]
    elapsed = clock() - started
    stale_tail = round(max(0, elapsed - (last_new_poll if last_new_poll is not None else 0)), 3)
    if not any(segment["interval_count"] for segment in summaries) and status == "completed":
        status = "unknown"
        errors.append("insufficient_new_present_samples; not zero FPS")
    elif status == "completed" and stale_tail >= STALE_TAIL_SECONDS:
        status = "partial"
        errors.append("stale_tail_at_least_2s; timestamp coverage is partial, not proof of zero FPS or jank")
    return {"status": status, "elapsed_seconds": round(elapsed, 3), "segments": summaries,
            "polls": polls, "repeated_history_polls": repeated, "warnings": sorted(set(errors)),
            "first_new_present_poll_elapsed": round(first_new_poll, 3) if first_new_poll is not None else None,
            "last_new_present_poll_elapsed": round(last_new_poll, 3) if last_new_poll is not None else None,
            "stale_tail_seconds": stale_tail, "stale_tail_partial_threshold_seconds": STALE_TAIL_SECONDS,
            "last_target_surfaceview_candidates": current_layers,
            "requested_unity_fps": None, "unity_render_resolution": None, "unity_cpu_gpu_times": None,
            "interpretation": "Selected SurfaceView actualPresent intervals only; >50ms is an observation, not universal jank or a CPU/GPU diagnosis. A stale tail of at least2s is partial coverage, not zero FPS. Completed means sample progression was observed, not that every game frame was captured. Same-layer scene changes cannot be detected; keep the MV scene stable."}


def context(adb: Adb, package: str, identity: bool = False) -> dict:
    result = {}
    if identity:
        for key, prop in (("model", "ro.product.model"), ("android_api", "ro.build.version.sdk")):
            reply = adb.shell("getprop", prop)
            value = reply.text.strip()
            result[key] = {"value": value[:128] if value and not any(ord(c) < 32 for c in value) else None,
                           "error": reply.error}
    reply = adb.shell("dumpsys", "display")
    modes = sorted({int(v) for v in re.findall(r"\bmActiveModeId\s*=\s*(\d+)", reply.text)})
    result["display"] = {"reported_active_mode_ids": modes, "game_display_mapping": None,
                         "active_game_refresh_hz": None, "error": reply.error}
    reply = adb.shell("dumpsys", "thermalservice")
    thermal = re.search(r"\bThermal Status:\s*([0-6])\b", reply.text)
    result["thermal"] = {"status": int(thermal[1]) if thermal else None, "error": reply.error}
    reply = adb.shell("cmd", "game", "list-modes", package)
    mode = re.search(r"\bcurrent mode:\s*(\d+)", reply.text)
    result["game_mode"] = {"reported_current_mode": int(mode[1]) if mode else None, "error": reply.error}
    reply = adb.shell("cmd", "game", "list-configs", package)
    result["game_configs"] = {"reported_fps_values": sorted({int(v) for v in re.findall(r"\bfps\s*[:=]\s*(\d+)", reply.text, re.I)}),
                              "active_intervention": None, "error": reply.error}
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--layer")
    parser.add_argument("--list-layers", action="store_true")
    parser.add_argument("--duration", type=float, default=25, help="capture seconds, 20–30 (default25)")
    parser.add_argument("--adb", default="adb", help="existing adb executable; never installs an SDK")
    parser.add_argument("--output", type=Path, help="new local JSON file; default stdout; existing files are not overwritten")
    args = parser.parse_args(argv)
    if not PACKAGE.fullmatch(args.package) or len(args.package) > 192 or not SERIAL.fullmatch(args.serial):
        parser.error("explicit serial/package contain invalid characters")
    if not math.isfinite(args.duration) or not 20 <= args.duration <= 30:
        parser.error("--duration must be20–30seconds")
    if args.output and args.output.exists():
        parser.error("--output must name a new file")
    adb = Adb(args.serial, args.adb)
    reply = adb.shell("dumpsys", "SurfaceFlinger", "--list")
    layers = candidates(reply.text, args.package)
    layer = choose_layer(layers, args.layer)
    document = {"schema": 1, "purpose": "Android physical-device MV measurement preparation; not iOS/common performance proof",
                "package": args.package, "target_surfaceview_candidates": layers,
                "device_mutations": False, "perfetto": "not_captured; see docs/mv-performance-audit.md"}
    if reply.error:
        document.update(status="unknown", error=reply.error)
    elif args.list_layers:
        document.update(status="layers_listed")
    elif layer is None:
        document.update(status="ambiguous_or_missing_layer", error="Choose one exact target-package SurfaceView with --layer; no layer was sampled.")
    else:
        document["layer"] = layer
        document["context_before"] = context(adb, args.package, identity=True)
        document["capture"] = capture(adb, args.package, layer, layers, args.duration)
        document["context_after"] = context(adb, args.package)
        document["status"] = document["capture"]["status"]
    encoded = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        try:
            with args.output.open("x", encoding="utf-8") as output:
                output.write(encoded)
        except OSError as error:
            parser.exit(2, f"Cannot create new output JSON: {type(error).__name__}\n")
    else:
        print(encoded, end="")
    return 0 if document["status"] in {"completed", "layers_listed"} else 2


if __name__ == "__main__":
    sys.exit(main())
