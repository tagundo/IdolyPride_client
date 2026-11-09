#!/usr/bin/env python3
"""Capture an actual ARM64 game launch on a disposable translated emulator.

The optional title action taps a freshly OCR-observed TAP TO START phrase.
An opt-in second action requires observed post-tap loading followed by two
fresh stable, nonloading returned-title frames.
No other game input is performed. Captures do not establish home success.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time

import grpc

from qa_emulator import ACTIVITY, PACKAGE, QA, wait_server
from qa_diagnostics import _tap_initial_start
from idoly_local import codec
from idoly_local.schema import Schema


GAME = "game.qualiarts.idolypride.local"
GAME_PACKAGES = (GAME, GAME + ".diagnostics")
GAME_ACTIVITY = GAME + "/com.google.firebase.MessagingUnityPlayerActivity"


def observed_title(tsv, width, height):
    """Return one confident contiguous phrase; coordinates come only from OCR."""
    lines = {}
    # Tesseract text can contain literal quotes; TSV does not CSV-escape them.
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row.get("level") != "5" or not row.get("text", "").strip():
            continue
        try:
            word = {"text": row["text"].strip().upper(), "confidence": float(row["conf"]),
                    "word": int(row["word_num"]), "left": int(row["left"]), "top": int(row["top"]),
                    "width": int(row["width"]), "height": int(row["height"])}
            line = tuple(int(row[key]) for key in ("page_num", "block_num", "par_num", "line_num"))
        except (KeyError, ValueError):
            continue
        lines.setdefault(line, []).append(word)
    matches = []
    for words in lines.values():
        words.sort(key=lambda word: word["word"])
        for start in range(len(words)):
            for count in (1, 2, 3):
                selected = words[start:start + count]
                # Tesseract can merge TO START into TOSTART. Require exact
                # recognized letters, with whitespace merging only; no fuzzy
                # spelling or coordinates inferred from a previous frame.
                if len(selected) != count or "".join(word["text"] for word in selected) != "TAPTOSTART":
                    continue
                if any(not word["confidence"] >= 85 or not 10 <= word["height"] <= height * 0.08
                       or word["width"] <= 0 or word["left"] < 0 or word["top"] < 0
                       or word["left"] + word["width"] > width or word["top"] + word["height"] > height
                       for word in selected):
                    continue
                if any(right["word"] != left["word"] + 1 or right["left"] <= left["left"]
                       or right["left"] - left["left"] - left["width"] > height * 0.08
                       or min(left["top"] + left["height"], right["top"] + right["height"])
                          - max(left["top"], right["top"]) < min(left["height"], right["height"]) * 0.5
                       for left, right in zip(selected, selected[1:])):
                    continue
                left, top = min(word["left"] for word in selected), min(word["top"] for word in selected)
                right = max(word["left"] + word["width"] for word in selected)
                bottom = max(word["top"] + word["height"] for word in selected)
                if not width * 0.1 <= right - left <= width * 0.9 or bottom - top > height * 0.08:
                    continue
                matches.append({"phrase": "TAP TO START", "ocr_words": selected,
                                "bounds": [left, top, right, bottom],
                                "point": [(left + right) // 2, (top + bottom) // 2]})
    return matches[0] if len(matches) == 1 else None


def raw_loading_state(tsv):
    """Treat any recognized LOADING as a veto, irrespective of confidence."""
    lines = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row.get("level") != "5" or not row.get("text", "").strip():
            continue
        line = tuple(row.get(key, "") for key in ("page_num", "block_num", "par_num", "line_num"))
        letters = re.sub("[^A-Z]", "", row["text"].upper())
        if letters:
            lines.setdefault(line, []).append(letters)
    # Also handle an animated word split into several OCR tokens on one line.
    return {"raw_ocr_has_words": bool(lines),
            "raw_loading_detected": any("LOADING" in "".join(words) for words in lines.values())}


def stable_title_pair(previous, current):
    """Require two separate, foreground, nonloading observations >=3s apart."""
    for frame in (previous, current):
        if (frame is None or frame.get("phrase") != "TAP TO START" or not frame.get("foreground_game")
                or not frame.get("raw_ocr_has_words") or frame.get("raw_loading_detected") is not False):
            return False
    if (current["captured_at"] - previous["captured_at"] < 3
            or current["source_image"] == previous["source_image"]
            or current["image_size"] != previous["image_size"]):
        return False
    a, b = previous["bounds"], current["bounds"]
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap
    return union > 0 and overlap / union >= 0.9


def game_launch_args(force_gles30=False, game_package=GAME):
    if game_package not in GAME_PACKAGES:
        raise ValueError("Only the two dedicated local QA game packages are accepted")
    command = ["shell", "am", "start", "-W", "-n",
               game_package + "/com.google.firebase.MessagingUnityPlayerActivity"]
    if force_gles30:
        # Audited classes3.dex: Firebase onCreate calls UnityPlayerActivity,
        # whose onCreate forwards this string through the unchanged
        # updateUnityCommandLineArguments before constructing UnityPlayer.
        command.extend(["--es", "unity", "-force-gles30"])
    return command


def prepare_restarted_tutorial(schema, port, *, caller=None):
    """Name a fresh local QA profile, without skipping or granting anything.

    Stored completed step10 is the client input for its next current step100.
    That client-derived value is not a protobuf field or a visual observation.
    """
    if caller is None:
        def caller(method, values, token):
            request = schema.request_type(method)(**values)
            metadata = (("x-auth-token", token),) if token else ()
            with grpc.insecure_channel("127.0.0.1:" + str(port)) as channel:
                raw = channel.unary_unary(method)(codec.encode(request.SerializeToString()),
                                                  metadata=metadata, timeout=15)
            return schema.response_type(method).FromString(codec.decode(raw))

    calls = []

    def invoke(method, values, token=None):
        response = caller(method, values, token)
        # Deliberately retain method/status only, never authentication values.
        calls.append({"method": method, "status": "OK", "origin": "profile_fixture"})
        return response

    auth = invoke("/api.Auth/Login", {"firebaseIDToken": "local"})
    if not auth.gameAuthToken:
        raise RuntimeError("Local QA fixture login did not return a session")
    invoke("/api.Tutorial/Init", {"name": "QAManager"}, auth.gameAuthToken)
    snapshot = invoke("/api.User/Get", {}, auth.gameAuthToken)
    tutorials = [row.step for row in snapshot.tutorials if row.tutorialType == 1]
    if (tutorials != [10] or snapshot.user.name != "QAManager"
            or snapshot.user.tutorialClearedTime != 0):
        raise RuntimeError("Restarted tutorial fixture requires an unprogressed disposable profile; no skip performed")
    return {"enabled": True, "qa_only": True, "status": "ready", "rpc_calls": calls, "manager_name": "QAManager",
            "completed_tutorial_step": 10, "expected_client_next_tutorial_step": 100,
            "client_next_step_visually_verified": False, "tutorial_cleared": False,
            "tutorial_progress_or_skip_called": False, "purchase_or_grant_called": False}


class GameQA(QA):
    def capture_server(self, stage):
        """Allow Unity's observed pause delay without dropping capture checks."""
        for attempt in range(3):
            capture_stage = stage if attempt == 0 else f"{stage}-retry-{attempt}"
            try:
                hierarchy = self.capture(capture_stage)
                if not any(node.get("package") == PACKAGE for node in hierarchy.iter("node")):
                    raise RuntimeError("Server activity has not reached foreground")
                return hierarchy
            except RuntimeError as error:
                # The actual no-store probe finished all game observations but
                # Unity paused slowly; uiautomator returned no hierarchy once.
                # Retry only these transition states, always with fresh input.
                if str(error) not in ("uiautomator did not return a UI hierarchy",
                                      "Server activity has not reached foreground"):
                    raise
                (self.artifacts / (capture_stage + ".error.txt")).write_text(str(error) + "\n")
                try:
                    (self.artifacts / (capture_stage + ".png")).write_bytes(
                        self.adb("exec-out", "screencap", "-p", binary=True))
                except (OSError, RuntimeError, subprocess.TimeoutExpired):
                    pass
                if attempt == 2:
                    raise
                time.sleep(1)

    def _observe_title_frame(self, prefix, *, inspect_loading=False):
        image_tool = shutil.which("magick") or shutil.which("convert")
        if image_tool is None or shutil.which("tesseract") is None:
            raise RuntimeError("Observed title QA requires ImageMagick and Tesseract")
        prefix = self.artifacts / prefix
        source = prefix.with_suffix(".png")
        mask = prefix.with_name(prefix.name + "-ocr-mask").with_suffix(".png")
        captured_at = time.monotonic()
        raw = self.adb("exec-out", "screencap", "-p", binary=True)
        if raw[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("Fresh title screenshot is not PNG")
        source.write_bytes(raw)
        width, height = struct.unpack_from(">II", raw, 16)
        # Mask the entire fresh frame; no historical coordinate/crop is used.
        subprocess.run([image_tool, str(source), "-alpha", "off", "-colorspace", "gray",
                        "-threshold", "99%", "-negate", str(mask)], check=True, capture_output=True, timeout=15)
        ocr = subprocess.run(["tesseract", str(mask), "stdout", "--psm", "11", "-l", "eng", "tsv"],
                             check=True, capture_output=True, text=True, timeout=15)
        prefix.with_suffix(".tsv").write_text(ocr.stdout, encoding="utf-8")
        phrase = observed_title(ocr.stdout, width, height)
        # A non-title frame is still an observation. In particular, raw LOADING
        # without TAP TO START is positive departure evidence, not OCR absence.
        observation = {"phrase": None, "source_image": source.name, "ocr_mask": mask.name,
                       "ocr_tsv": prefix.with_suffix(".tsv").name, "captured_at": captured_at,
                       "image_size": [width, height], "elapsed_seconds": round(captured_at - self.started, 2)}
        if phrase is not None:
            observation.update(phrase)
        activity = self.adb("shell", "dumpsys", "activity", "activities")
        prefix.with_suffix(".activity.txt").write_text(activity, encoding="utf-8")
        observation["foreground_game"] = bool(re.search(r"(?:mResumedActivity|topResumedActivity)[^\n]*\b"
                                    + re.escape(getattr(self, "game_package", GAME)) + r"/", activity))
        if inspect_loading:
            # Check the unmasked frame even when the title phrase is absent:
            # a white-only mask can omit a colored/dimmed LOADING indicator.
            raw_ocr = subprocess.run(["tesseract", str(source), "stdout", "--psm", "11", "-l", "eng", "tsv"],
                                     check=True, capture_output=True, text=True, timeout=15)
            raw_tsv = prefix.with_name(prefix.name + "-raw").with_suffix(".tsv")
            raw_tsv.write_text(raw_ocr.stdout, encoding="utf-8")
            observation.update(raw_ocr_tsv=raw_tsv.name, **raw_loading_state(raw_ocr.stdout))
        prefix.with_suffix(".observation.json").write_text(json.dumps(observation, indent=2) + "\n")
        return observation

    def _perform_title_action(self, phrase):
        actions = getattr(self, "title_actions", [])
        maximum = getattr(self, "max_title_taps", 1)
        if len(actions) >= maximum or len(actions) >= 2:
            raise RuntimeError("The configured observed title action limit was reached")
        if phrase.get("phrase") != "TAP TO START":
            raise RuntimeError("A game tap requires a confident fresh title phrase")
        if not phrase.get("foreground_game"):
            raise RuntimeError("OCR title phrase is not in the foreground game activity")
        action = dict(phrase, action_number=len(actions) + 1, performed=False)
        actions.append(action)
        self.title_actions = actions
        record = self.artifacts / f"observed-title-action-{len(actions)}.json"

        def save():
            record.write_text(json.dumps(action, indent=2) + "\n")
            # Preserve the first action's original filename for earlier probes.
            if len(actions) == 1:
                (self.artifacts / "observed-title-action.json").write_text(json.dumps(action, indent=2) + "\n")
            (self.artifacts / "observed-title-actions.json").write_text(json.dumps(actions, indent=2) + "\n")

        save()
        x, y = action["point"]
        self.adb("shell", "input", "tap", str(x), str(y))
        self.last_title_tap_at = time.monotonic()
        action.update(performed=True, performed_seconds=round(self.last_title_tap_at - self.started, 2))
        save()
        print(f"Tapped fresh OCR-observed TAP TO START action {len(actions)}", flush=True)
        return action

    def tap_observed_title(self, timeout=180):
        if getattr(self, "title_actions", []):
            raise RuntimeError("The first observed title action may be attempted only once")
        if not 0 < timeout <= 180:
            raise ValueError("Title observation must be bounded to at most 180 seconds")
        deadline = time.monotonic() + timeout
        attempt = 0
        while time.monotonic() < deadline:
            began = time.monotonic()
            phrase = self._observe_title_frame(f"title-wait-{attempt:02d}", inspect_loading=True)
            if (phrase is not None and phrase.get("phrase") == "TAP TO START"
                    and phrase.get("foreground_game") and phrase.get("raw_ocr_has_words")
                    and phrase.get("raw_loading_detected") is False and time.monotonic() < deadline):
                return self._perform_title_action(phrase)
            attempt += 1
            time.sleep(max(0, min(5 - (time.monotonic() - began), deadline - time.monotonic())))
        raise RuntimeError(f"No confident fresh nonloading TAP TO START phrase appeared within {timeout:g} seconds; no game tap performed")

    def tap_observed_title_reentry(self, timeout=180):
        # The full first master download and title reload took >90s in actual
        # probe 42647043103. Keep a bounded 180s window with the same input guards.
        if (getattr(self, "max_title_taps", 1) != 2 or len(getattr(self, "title_actions", [])) != 1
                or not self.title_actions[0].get("performed")):
            raise RuntimeError("Second title observation requires one completed action and opt-in max-title-taps=2")
        if not 0 < timeout <= 180:
            raise ValueError("Title reentry observation must be bounded to at most 180 seconds")
        began = time.monotonic()
        deadline = began + timeout
        earliest = self.last_title_tap_at + 20
        first = self.title_actions[0]
        busy = None
        candidate = None
        attempt = 0
        while time.monotonic() < deadline:
            frame_start = time.monotonic()
            current = self._observe_title_frame(f"title-reentry-{attempt:02d}", inspect_loading=True)
            fresh = (current is not None and current["captured_at"] > self.last_title_tap_at
                     and current.get("source_image") != first["source_image"])
            if (fresh and current.get("foreground_game") is True and current.get("raw_ocr_has_words")
                    and current.get("raw_loading_detected") is True):
                busy = current
                candidate = None
            eligible = (fresh and busy is not None and current.get("phrase") == "TAP TO START"
                        and current["captured_at"] >= earliest and current["captured_at"] > busy["captured_at"]
                        and current.get("source_image") != busy["source_image"]
                        and current.get("foreground_game") and current.get("raw_ocr_has_words")
                        and current.get("raw_loading_detected") is False)
            if eligible and stable_title_pair(candidate, current) and time.monotonic() < deadline:
                current.update(stable_previous_observation=candidate, returned_after_loading_observation=busy,
                               minimum_seconds_after_first_tap=20,
                               stable_frames_minimum_gap_seconds=3)
                action = self._perform_title_action(current)
                (self.artifacts / "title-reentry-result.json").write_text(json.dumps(
                    {"performed": True, "timeout_seconds": timeout,
                     "waited_seconds": round(time.monotonic() - began, 2),
                     "action_number": action["action_number"], "busy_phase_observed": True,
                     "busy_observation": busy}, indent=2) + "\n")
                return action
            candidate = current if eligible else None
            attempt += 1
            time.sleep(max(0, min(3 - (time.monotonic() - frame_start), deadline - time.monotonic())))
        # A game that proceeds elsewhere needs no second title input. Preserve
        # observations and continue capturing without treating absence as error.
        (self.artifacts / "title-reentry-result.json").write_text(json.dumps(
            {"performed": False, "timeout_seconds": timeout,
             "reason": ("No stable returned title after observed loading" if busy is not None
                        else "No positive foreground loading phase observed after the first tap"),
             "busy_phase_observed": busy is not None, "busy_observation": busy,
             "waited_seconds": round(time.monotonic() - began, 2)}, indent=2) + "\n")
        return None

    def capture_game(self, stage):
        """Keep screenshots even if Unity's accessibility tree is unavailable."""
        report = {"stage": stage, "elapsed_seconds": round(time.monotonic() - self.started, 2)}
        for suffix, args, binary in (
            ("png", ("exec-out", "screencap", "-p"), True),
            ("xml", ("exec-out", "uiautomator", "dump", "/dev/tty"), False),
            ("activity.txt", ("shell", "dumpsys", "activity", "activities"), False),
            ("sockets.txt", ("shell", "netstat", "-an"), False),
        ):
            try:
                process = subprocess.run([*self.command, *args], capture_output=True,
                                         text=not binary, timeout=30)
                output = process.stdout
                if suffix == "xml":
                    begin, end = output.find("<hierarchy"), output.rfind("</hierarchy>")
                    if begin >= 0 and end >= 0:
                        output = output[begin:end + len("</hierarchy>")]
                target = self.artifacts / (stage + "." + suffix)
                target.write_bytes(output) if binary else target.write_text(output, encoding="utf-8")
                if process.returncode:
                    report[suffix + "_error"] = str(process.stderr)[:1000]
            except (OSError, subprocess.TimeoutExpired) as error:
                report[suffix + "_error"] = type(error).__name__
        report["game_pid"] = self.adb("shell", "pidof", getattr(self, "game_package", GAME), check=False).strip()
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-apk", type=Path, required=True)
    parser.add_argument("--game-apk", type=Path, required=True)
    parser.add_argument("--game-package", choices=GAME_PACKAGES, default=GAME)
    parser.add_argument("--descriptor-set", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, default=Path("data/android-game-debug"))
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--duration", type=int, default=180)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--startup-timeout", type=float, default=600)
    parser.add_argument("--force-gles30", action="store_true",
                        help="QA-only Unity launch override to avoid emulator Vulkan translation; changes no APK bytes")
    parser.add_argument("--tap-observed-title", action="store_true",
                        help="Tap a freshly OCR-observed TAP TO START phrase, then observe 180 seconds")
    parser.add_argument("--max-title-taps", type=int, choices=(1, 2), default=1,
                        help="QA-only opt-in: at most two title taps; the second requires observed loading then a fresh stable returned title")
    parser.add_argument("--prepare-restarted-tutorial", action="store_true",
                        help="QA ONLY: local Auth/Login + Tutorial/Init(QAManager) before launch; no tutorial skip/grants")
    args = parser.parse_args()
    if not 90 <= args.duration <= 180 or args.interval < 5 or args.startup_timeout <= 0:
        parser.error("duration must be 90..180, interval >=5, and startup-timeout positive")
    if args.max_title_taps == 2 and not args.tap_observed_title:
        parser.error("max-title-taps=2 requires tap-observed-title")
    qa = GameQA(args.adb, args.serial, args.artifacts)
    qa.game_package = args.game_package
    qa.max_title_taps = args.max_title_taps
    qa.started = time.monotonic()
    result = {"capture_completed": False, "actual_game_client_launched": False,
              "game_observation_completed": False,
              "home_screen_verified": False, "game_input_performed": False, "game_input_count": 0,
              "target": "disposable Android emulator", "captures": [],
              "game_package": args.game_package,
              "max_title_taps": args.max_title_taps, "observed_title_actions": [],
              "profile_fixture": {"enabled": False, "rpc_calls": []},
              "qa_launch_override": {"force_gles30_requested": args.force_gles30,
                  "intent_string_extras": {"unity": "-force-gles30"} if args.force_gles30 else {},
                  "apk_bytes_changed_for_graphics": False}}
    logger = None
    logger_file = None
    server_started = False
    try:
        if not args.serial.startswith("emulator-") or qa.adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
            raise RuntimeError("This driver accepts only a disposable emulator target")
        props = {key: qa.adb("shell", "getprop", key).strip() for key in (
            "ro.build.version.sdk", "ro.build.fingerprint", "ro.product.cpu.abilist",
            "ro.product.cpu.abilist64", "ro.dalvik.vm.native.bridge", "ro.dalvik.vm.isa.arm64")}
        (args.artifacts / "native-bridge.json").write_text(json.dumps(props, indent=2) + "\n")
        result["native_bridge"] = props
        if "arm64-v8a" not in props["ro.product.cpu.abilist"].split(","):
            raise RuntimeError("System image does not advertise arm64-v8a support")
        if props["ro.dalvik.vm.native.bridge"] in ("", "0"):
            raise RuntimeError("No native bridge is enabled in this x86_64 system image")
        print("Verified ARM64 translation; installing both apps on emulator only", flush=True)
        qa.adb("install", "-r", "-g", str(args.server_apk.resolve()))
        qa.adb("install", "-r", "-g", "--abi", "arm64-v8a", str(args.game_apk.resolve()))
        qa.adb("logcat", "-c")
        logger_file = (args.artifacts / "live-logcat.txt").open("w", encoding="utf-8")
        logger = subprocess.Popen([*qa.command, "logcat", "-v", "threadtime"], stdout=logger_file,
                                  stderr=subprocess.STDOUT, text=True)
        qa.adb("shell", "am", "force-stop", PACKAGE)
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        port = qa.forward(50051)
        schema = Schema.from_descriptor_set(args.descriptor_set)
        result["startup_system_dialog_actions"] = _tap_initial_start(qa)
        server_started = True
        wait_server(schema, port, timeout=args.startup_timeout)
        qa.capture_server("server-running")
        # Readiness and the explicitly selected profile fixture are separate
        # from subsequent game-originated RPCs; neither proves game UI success.
        if args.prepare_restarted_tutorial:
            result["profile_fixture"] = {"enabled": True, "qa_only": True, "status": "preparing",
                                         "rpc_calls": [], "home_screen_verified": False}
            result["profile_fixture"] = prepare_restarted_tutorial(schema, port)
            (args.artifacts / "profile-fixture.json").write_text(
                json.dumps(result["profile_fixture"], indent=2) + "\n")
        qa.adb("shell", "am", "force-stop", args.game_package)
        command = game_launch_args(args.force_gles30, args.game_package)
        (args.artifacts / "game-launch-command.json").write_text(json.dumps(
            {"qa_only": True, "adb_arguments": command}, indent=2) + "\n")
        launch = qa.adb(*command)
        (args.artifacts / "game-launch.txt").write_text(launch, encoding="utf-8")
        if "Error:" in launch or "Exception" in launch:
            raise RuntimeError("Game activity did not launch; inspect game-launch.txt")
        result["actual_game_client_launched"] = True
        result["game_input_performed"] = False
        if args.tap_observed_title:
            result["observed_title_action"] = qa.tap_observed_title()
            result["game_input_performed"] = True
            result["game_input_count"] = 1
            if args.max_title_taps == 2:
                # Start departure OCR immediately. A slow Unity accessibility
                # capture here could miss the complete loading/reload phase.
                result["title_reentry_action"] = qa.tap_observed_title_reentry()
                result["captures"].append(qa.capture_game("after-title-reentry-observation"))
            result["observed_title_actions"] = qa.title_actions
            result["game_input_count"] = sum(action["performed"] for action in qa.title_actions)
        duration = 180 if args.tap_observed_title else args.duration
        result["post_title_observation_seconds"] = duration if args.tap_observed_title else None
        begin = time.monotonic()
        for index, scheduled in enumerate(range(0, duration + args.interval, args.interval)):
            time.sleep(max(0, begin + min(scheduled, duration) - time.monotonic()))
            elapsed = time.monotonic() - begin
            result["captures"].append(qa.capture_game(f"game-{index:02d}-{int(elapsed):03d}s"))
            print("Captured actual game at " + str(int(elapsed)) + "s; no further game input", flush=True)
            if scheduled >= duration:
                break
        result["game_observation_completed"] = True
        if args.tap_observed_title:
            result["elapsed_seconds_after_last_title_tap"] = round(time.monotonic() - qa.last_title_tap_at, 2)
        # Return to the server only after capturing the game's uninterrupted run.
        qa.adb("shell", "am", "start", "-W", "-n", ACTIVITY)
        hierarchy = qa.capture_server("server-after-game")
        texts = [node.get("text", "") for node in hierarchy.iter("node") if node.get("text")]
        (args.artifacts / "server-ui-log.txt").write_text("\n".join(texts) + "\n", encoding="utf-8")
        sequence = [{"method": match.group(1), "status": match.group(2)}
                    for match in re.finditer(r"RPC (/api\.[A-Za-z0-9_.]+/[A-Za-z0-9_]+) -> ([A-Z_]+)",
                                             "\n".join(texts))]
        (args.artifacts / "server-rpc-sequence.json").write_text(json.dumps(sequence, indent=2) + "\n")
        result["capture_completed"] = True
    except BaseException as error:
        result.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        result["observed_title_actions"] = getattr(qa, "title_actions", [])
        result["game_input_count"] = sum(action["performed"] for action in result["observed_title_actions"])
        result["game_input_performed"] = result["game_input_count"] > 0
        try:
            result["captures"].append(qa.capture_game("final"))
            if server_started:
                qa.adb("shell", "am", "start", "-W", "-n", ACTIVITY)
                qa.capture_server("server-final")
                qa.tap("서버 중지", "server-stop")
        except Exception as error:
            result["cleanup_error"] = type(error).__name__
        if logger is not None:
            if logger.poll() is None:
                logger.terminate()
            try:
                logger.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.kill()
                logger.wait(timeout=10)
        if logger_file is not None:
            logger_file.close()
        try:
            qa.close()
        finally:
            (args.artifacts / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
