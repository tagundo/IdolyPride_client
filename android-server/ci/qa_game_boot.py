#!/usr/bin/env python3
"""Capture an actual ARM64 game launch on a disposable translated emulator.

This driver never taps inside the game. A completed capture is diagnostic
evidence, not proof that the game reached home or that gameplay works.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import time

from qa_emulator import ACTIVITY, PACKAGE, QA, wait_server
from idoly_local.schema import Schema


GAME = "game.qualiarts.idolypride.local"
GAME_ACTIVITY = GAME + "/com.google.firebase.MessagingUnityPlayerActivity"


class GameQA(QA):
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
        report["game_pid"] = self.adb("shell", "pidof", GAME, check=False).strip()
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-apk", type=Path, required=True)
    parser.add_argument("--game-apk", type=Path, required=True)
    parser.add_argument("--descriptor-set", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, default=Path("data/android-game-debug"))
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--duration", type=int, default=180)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--startup-timeout", type=float, default=600)
    args = parser.parse_args()
    if not 90 <= args.duration <= 180 or args.interval < 5 or args.startup_timeout <= 0:
        parser.error("duration must be 90..180, interval >=5, and startup-timeout positive")
    qa = GameQA(args.adb, args.serial, args.artifacts)
    qa.started = time.monotonic()
    result = {"capture_completed": False, "actual_game_client_launched": False,
              "home_screen_verified": False, "game_input_performed": False,
              "target": "disposable Android emulator", "captures": []}
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
        qa.tap("서버 시작", "server-start")
        server_started = True
        wait_server(schema, port, timeout=args.startup_timeout)
        qa.capture("server-running")
        # These readiness System.Check probes do not create a session. All game
        # Auth/Login, User, Home and asset requests below originate in the APK.
        qa.adb("shell", "am", "force-stop", GAME)
        launch = qa.adb("shell", "am", "start", "-W", "-n", GAME_ACTIVITY)
        (args.artifacts / "game-launch.txt").write_text(launch, encoding="utf-8")
        if "Error:" in launch or "Exception" in launch:
            raise RuntimeError("Game activity did not launch; inspect game-launch.txt")
        result["actual_game_client_launched"] = True
        result["game_input_performed"] = False
        begin = time.monotonic()
        for index, scheduled in enumerate(range(0, args.duration + args.interval, args.interval)):
            time.sleep(max(0, begin + min(scheduled, args.duration) - time.monotonic()))
            elapsed = time.monotonic() - begin
            result["captures"].append(qa.capture_game(f"game-{index:02d}-{int(elapsed):03d}s"))
            print("Captured actual game at " + str(int(elapsed)) + "s; no game taps", flush=True)
            if scheduled >= args.duration:
                break
        # Return to the server only after capturing the game's uninterrupted run.
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        hierarchy = qa.capture("server-after-game")
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
        try:
            result["captures"].append(qa.capture_game("final"))
            if server_started:
                qa.adb("shell", "am", "start", "-n", ACTIVITY)
                qa.capture("server-final")
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
