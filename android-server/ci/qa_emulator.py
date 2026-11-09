#!/usr/bin/env python3
"""Exercise the native Android server UI and real encrypted loopback RPCs.

Only an emulator target is accepted. UI taps use fresh uiautomator node bounds;
screenshots, UI XML, logcat and a credential-free result report are retained.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import grpc

from idoly_local import codec
from idoly_local.schema import Schema


PACKAGE = "game.qualiarts.idolypride.localserver"
ACTIVITY = PACKAGE + "/.MainActivity"


class QA:
    def __init__(self, adb, serial, artifacts):
        self.command = [adb, "-s", serial]
        self.artifacts = artifacts
        artifacts.mkdir(parents=True, exist_ok=True)
        self.forwarded = []

    def adb(self, *args, binary=False, check=True):
        result = subprocess.run([*self.command, *args], capture_output=True, text=not binary, timeout=90)
        if check and result.returncode:
            raise RuntimeError("adb command failed: " + " ".join(args[:3]))
        return result.stdout

    def capture(self, stage):
        raw = self.adb("exec-out", "uiautomator", "dump", "/dev/tty")
        begin, end = raw.find("<hierarchy"), raw.rfind("</hierarchy>")
        if begin < 0 or end < 0:
            raise RuntimeError("uiautomator did not return a UI hierarchy")
        xml = raw[begin:end + len("</hierarchy>")]
        (self.artifacts / (stage + ".xml")).write_text(xml, encoding="utf-8")
        (self.artifacts / (stage + ".png")).write_bytes(self.adb("exec-out", "screencap", "-p", binary=True))
        return ET.fromstring(xml)

    def tap(self, label, stage):
        for attempt in range(5):
            hierarchy = self.capture(stage + "-" + str(attempt))
            for node in hierarchy.iter("node"):
                if node.get("text") != label or node.get("enabled") != "true":
                    continue
                bounds = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
                if bounds:
                    left, top, right, bottom = map(int, bounds.groups())
                    self.adb("shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2))
                    return
            time.sleep(0.5)
        raise RuntimeError("Enabled UI button not found: " + label)

    def forward(self, device_port):
        value = self.adb("forward", "tcp:0", "tcp:" + str(device_port)).strip()
        port = int(value)
        self.forwarded.append(port)
        return port

    def close(self):
        (self.artifacts / "logcat.txt").write_text(self.adb("logcat", "-d", check=False), encoding="utf-8")
        (self.artifacts / "crash-logcat.txt").write_text(self.adb("logcat", "-b", "crash", "-d", check=False), encoding="utf-8")
        for port in self.forwarded:
            self.adb("forward", "--remove", "tcp:" + str(port), check=False)


def rpc(schema, port, method, token=None):
    request = schema.request_type(method)()
    metadata = (("x-auth-token", token),) if token else ()
    with grpc.insecure_channel("127.0.0.1:" + str(port)) as channel:
        raw = channel.unary_unary(method)(codec.encode(request.SerializeToString()), metadata=metadata, timeout=2)
    return schema.response_type(method).FromString(codec.decode(raw))


def wait_server(schema, port, expected=True, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            rpc(schema, port, "/api.System/Check")
            ready = True
        except grpc.RpcError:
            ready = False
        if ready == expected:
            return
        time.sleep(0.5)
    raise RuntimeError("Server did not " + ("start" if expected else "stop") + " before the timeout")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--descriptor-set", type=Path, default=Path("data/protocol/idolypride-6.1.1.pb"))
    parser.add_argument("--artifacts", type=Path, default=Path("data/android-server-qa"))
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", default="emulator-5554")
    args = parser.parse_args()
    qa = QA(args.adb, args.serial, args.artifacts)
    result = {"ok": False, "target": "Android emulator", "device_game_client_tested": False}
    try:
        if qa.adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
            raise RuntimeError("This QA driver accepts an emulator only")
        qa.adb("install", "-r", "-g", str(args.apk.resolve()))
        qa.adb("logcat", "-c")
        qa.adb("shell", "am", "force-stop", PACKAGE)
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        grpc_port, asset_port = qa.forward(50051), qa.forward(8080)
        schema = Schema.from_descriptor_set(args.descriptor_set)
        qa.tap("서버 시작", "01-start")
        wait_server(schema, grpc_port)
        qa.capture("02-running")
        check = rpc(schema, grpc_port, "/api.System/Check")
        login = rpc(schema, grpc_port, "/api.Auth/Login")
        if not login.gameAuthToken:
            raise RuntimeError("Local login did not return a session")
        user = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
        if not user.HasField("user") or not user.user.name:
            raise RuntimeError("Local User.Get snapshot is absent")
        rpc(schema, grpc_port, "/api.Home/Login", login.gameAuthToken)
        home = rpc(schema, grpc_port, "/api.Home/Enter", login.gameAuthToken)
        if not home.currentMainAreaId:
            raise RuntimeError("Local Home.Enter did not resolve the bundled starting area")
        rpc(schema, grpc_port, "/api.Home/SetReview", login.gameAuthToken)
        changed = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
        if not changed.user.isReviewed or changed.user.lastLoginTime <= 0:
            raise RuntimeError("Local gameplay changes were not saved")
        master = rpc(schema, grpc_port, "/api.Master/Get", login.gameAuthToken)
        if not master.masterTag.masterTagPacks:
            raise RuntimeError("Local master archive is absent")
        filename = master.masterTag.masterTagPacks[0].fileName
        from urllib.parse import quote

        request = Request("http://127.0.0.1:" + str(asset_port) + "/master/" + quote(filename, safe=""), headers={"Range": "bytes=0-31"})
        with urlopen(request, timeout=5) as response:
            if response.status != 206 or len(response.read()) != 32:
                raise RuntimeError("Local master HTTP byte range failed")
        result.update(system_check=check.keepAliveTimeMilliseconds > 0, local_auth=True, home_rpcs=True,
                      user_snapshot=True, master_packs=len(master.masterTag.masterTagPacks), asset_range=True)
        qa.tap("서버 중지", "03-stop")
        wait_server(schema, grpc_port, expected=False, timeout=30)
        qa.capture("04-stopped")
        # Stop the whole process, preserving its private DB, then exercise a
        # fresh service instance and the previously issued local session.
        qa.adb("shell", "am", "force-stop", PACKAGE)
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        qa.tap("서버 시작", "05-restart")
        wait_server(schema, grpc_port)
        restored = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
        if restored.user.name != user.user.name or not restored.user.isReviewed:
            raise RuntimeError("Restart did not preserve the local profile")
        result.update(restart_session_preserved=True, gameplay_change_preserved=True, port_rebound=True)
        qa.capture("06-restarted")
        qa.tap("서버 중지", "07-final-stop")
        wait_server(schema, grpc_port, expected=False, timeout=30)
        result.update(ok=True, final_stop=True)
    except BaseException as error:
        result["error_type"] = type(error).__name__
        result["error"] = str(error)
        raise
    finally:
        try:
            qa.capture("08-final")
        except Exception:
            pass
        qa.close()
        (args.artifacts / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
