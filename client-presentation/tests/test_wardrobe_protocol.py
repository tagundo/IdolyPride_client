"""Native/Java lifecycle protocol checks; loopback only, no Android/JNI/device."""
from pathlib import Path
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import shutil
import subprocess
import importlib.util
import threading

import pytest

HERE=Path(__file__).resolve().parents[1]
JDK=Path("/workspace/.setup/jdk-system/usr/lib/jvm/java-21-openjdk-amd64/bin")
SPEC=importlib.util.spec_from_file_location("wardrobe_addon_protocol",HERE/"build_addon.py")
ADDON=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(ADDON)

def test_java_wardrobe_schema_transport_and_other_channel_retention(tmp_path):
    sources=[HERE/"java/game/qualiarts/idolypride/presentation/PresentationClient.java",HERE/"tests/WardrobeHarness.java"]
    env=dict(os.environ,MALLOC_ARENA_MAX="2")
    subprocess.run([str(JDK/"javac"),*["-J"+f for f in ADDON.JAVA_FLAGS],*ADDON.JAVAC_ARGUMENTS,
        "-d",str(tmp_path),*map(str,sources)],check=True,capture_output=True,timeout=30,env=env)
    result=subprocess.run([str(JDK/"java"),*ADDON.JAVA_FLAGS,"-cp",str(tmp_path),
        "game.qualiarts.idolypride.presentation.WardrobeHarness"],check=True,capture_output=True,text=True,timeout=30,env=env)
    assert result.stdout.startswith("PASS ") and int(result.stdout.split()[1])>=190


def test_native_schema2_snapshots_reach_java_and_actual_loopback_post(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("Host C++ compiler unavailable")
    native = HERE / "native"
    helper = tmp_path / "timing"
    subprocess.run([compiler, "-std=c++17", "-pthread", "-O2", "-Wall", "-Wextra", "-Werror",
                    str(native / "tests/wardrobe_timing_test.cpp"), "-o", str(helper)],
                   check=True, capture_output=True, timeout=20)
    nested = subprocess.run([str(helper)], check=True, capture_output=True, text=True, timeout=5).stdout.splitlines()
    assert len(nested) == 5
    prefix = ('{"schema":2,"phase":"idle","show_failures":0,"released_waits":0,'
              '"sequence":0,"sample_age_ms":null,"exit":')
    valid = [prefix + row + "}" for row in nested]

    # Exercise the actual bridge's outer schema2 serializer too, including
    # outer legacy idle counters with a completed, non-idle exit observation.
    spec = importlib.util.spec_from_file_location("wardrobe_bridge_wire_fixture",
            native / "tests/test_native_wardrobe_bridge.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    module.test_original_hook_arguments_results_and_background_snapshot(bridge_dir)
    outer = subprocess.run([str(bridge_dir / "exit")], check=True, capture_output=True,
                           text=True, timeout=5).stdout.splitlines()
    assert len(outer) == 2
    valid.extend(outer)
    assert all(json.loads(row)["schema"] == 2 for row in valid)
    assert json.loads(valid[-1])["phase"] == "idle" and json.loads(valid[-1])["exit"]["phase"] == "completed"

    # Expiry or a failed observation clock is not operation completion.
    expired = json.loads(valid[1])
    expired["exit"].update(active=False, in_original=True, elapsed_ms=None)
    valid.append(json.dumps(expired, separators=(",", ":")))
    maximum = json.loads(valid[2])
    for field in ("elapsed_ms", "last_sync_ms", "max_sync_ms", "sequence"):
        maximum["exit"][field] = 2**63 - 1
    stages = ["back", "preclose", "hide", "disable", "selection_show", "selection_open", "gc", "unload"]
    maximum["exit"]["spans"] = [{"stage": name, "duration_ms": 2**63 - 1} for name in stages]
    valid.append(json.dumps(maximum, separators=(",", ":")))
    valid.extend(('{"schema":1,"phase":"idle","show_failures":0,"released_waits":0,"sequence":0,"sample_age_ms":null}',
                  '{"schema":1,"phase":"show_begin","show_failures":0,"released_waits":0,"sequence":1,"sample_age_ms":0}'))

    bad = []
    sample = json.loads(valid[1])

    def exit_value(key, value):
        row = deepcopy(sample)
        row["exit"][key] = value
        bad.append(json.dumps(row, separators=(",", ":")))

    for key in sample["exit"]:
        row = deepcopy(sample)
        del row["exit"][key]
        bad.append(json.dumps(row, separators=(",", ":")))
    for key in ("last_sync_ms", "max_sync_ms", "sequence", "elapsed_ms"):
        for value in (-1, 1.0, "1", True, 2**63):
            exit_value(key, value)
    for key in ("last_sync_ms", "max_sync_ms", "sequence"):
        exit_value(key, None)
    for key in ("active", "in_original"):
        for value in (0, 1, None, "true", [], {}):
            exit_value(key, value)
    for key, values in (("schema", (0, 2, True, None, "1", 1.0)),
                        ("room", (None, "unknown", 1, [], {})),
                        ("phase", (None, "unknown", "none", [], {})),
                        ("max_sync_stage", (None, "completed", "idle", 1, [], {})),
                        ("spans", (None, {}, 1, "[]", [None], [[]],
                                   [{"stage": "completed", "duration_ms": 1}],
                                   [{"stage": "back", "duration_ms": -1}],
                                   [{"stage": "back", "duration_ms": True}],
                                   [{"stage": "back", "duration_ms": 2**63}],
                                   [{"stage": "back", "duration_ms": 1, "extra": 0}],
                                   [{"stage": "back"}], [{"duration_ms": 1}],
                                   [{"stage": "back", "duration_ms": 1}] * 9))):
        for value in values:
            exit_value(key, value)
    idle = json.loads(valid[0])
    for key, value in (("room", "character_costume"), ("active", True), ("in_original", True),
                       ("elapsed_ms", 0), ("last_sync_ms", 1), ("max_sync_ms", 1),
                       ("max_sync_stage", "back"), ("sequence", 1),
                       ("spans", [{"stage": "back", "duration_ms": 0}])):
        row = deepcopy(idle)
        row["exit"][key] = value
        bad.append(json.dumps(row, separators=(",", ":")))
    for key in ("exit", "schema"):
        row = deepcopy(sample)
        del row[key]
        bad.append(json.dumps(row, separators=(",", ":")))
    row = deepcopy(sample)
    row["extra"] = 1
    bad.append(json.dumps(row, separators=(",", ":")))
    row = deepcopy(sample)
    row["exit"]["extra"] = 1
    bad.append(json.dumps(row, separators=(",", ":")))
    bad.extend((valid[1].replace('"schema":2', '"schema":2,"schema":2', 1),
                valid[1].replace('"room":"character_costume"', '"room":"character_costume","room":"none"', 1),
                valid[1] + "x", valid[1] + " " * 2048,
                valid[1].replace('"spans":[', '"spans":[[[[[', 1)))
    assert bad and len(bad) == len(set(bad))
    accepted_path, rejected_path = tmp_path / "accepted.jsonl", tmp_path / "rejected.jsonl"
    accepted_path.write_text("\n".join(valid) + "\n")
    rejected_path.write_text("\n".join(bad) + "\n")
    assert all(len(row.encode()) <= 2048 for row in valid)

    harness = tmp_path / "WardrobeV2NativeHarness.java"
    harness.write_text(r'''
package game.qualiarts.idolypride.presentation;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.Proxy;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
public final class WardrobeV2NativeHarness {
    public static void main(String[] args) throws Exception {
        final int port = Integer.parseInt(args[2]);
        final int[] opens = {0};
        PresentationClient client = new PresentationClient(new PresentationClient.Connections() {
            @Override public HttpURLConnection open(URL url) throws IOException {
                if (!url.toString().equals("http://127.0.0.1:8080/client/wardrobe")) throw new AssertionError();
                ++opens[0];
                return (HttpURLConnection) new URL("http://127.0.0.1:" + port + "/client/wardrobe").openConnection(Proxy.NO_PROXY);
            }
        });
        int accepted=0, rejected=0;
        for (String raw : Files.readAllLines(Paths.get(args[0]), StandardCharsets.UTF_8)) {
            client.postWardrobe(raw); ++accepted;
        }
        if (opens[0] != accepted) throw new AssertionError();
        for (String raw : Files.readAllLines(Paths.get(args[1]), StandardCharsets.UTF_8)) {
            try { client.postWardrobe(raw); throw new AssertionError("Invalid V2 accepted"); }
            catch (IOException expected) { ++rejected; }
            if (opens[0] != accepted) throw new AssertionError("Invalid input reached HTTP");
        }
        // Other protocol channels keep their original non-array parser mode.
        try { PresentationClient.parsePlayback("{\"schema\":1,\"revision\":0,\"wait_for_orientation\":[]}");
            throw new AssertionError(); } catch (IOException expected) {}
        System.out.println("PASS " + accepted + " " + rejected);
    }
}
''')
    env = dict(os.environ, MALLOC_ARENA_MAX="2")
    subprocess.run([str(JDK / "javac"), *["-J" + flag for flag in ADDON.JAVA_FLAGS],
                    *ADDON.JAVAC_ARGUMENTS, "-d", str(tmp_path),
                    str(HERE / "java/game/qualiarts/idolypride/presentation/PresentationClient.java"), str(harness)],
                   check=True, capture_output=True, timeout=30, env=env)
    received = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            if self.path != "/client/wardrobe" or not 0 < length <= 2048:
                self.send_error(400)
                return
            received.append((self.rfile.read(length), self.headers.get("Content-Type")))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        result = subprocess.run([str(JDK / "java"), *ADDON.JAVA_FLAGS, "-cp", str(tmp_path),
            "game.qualiarts.idolypride.presentation.WardrobeV2NativeHarness", str(accepted_path),
            str(rejected_path), str(server.server_port)], check=True, capture_output=True,
            text=True, timeout=30, env=env)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert result.stdout.strip() == f"PASS {len(valid)} {len(bad)}"
    assert [body for body, _ in received] == [row.encode() for row in valid]
    assert all(content == "application/json; charset=utf-8" for _, content in received)
