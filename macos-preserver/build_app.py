#!/usr/bin/env python3
"""Build and test an Apple Silicon app; no real account/network operation runs here."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from extract_descriptor import DESCRIPTOR_SHA256, PAYLOAD_SHA256
from synthetic_home import create as create_synthetic_home

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
APP_NAME = "IdolyPrideEventPreserver"
WORKER_NAME = "IdolyEventPreserverWorker"
CERTIFI_VERSION = "2025.10.5"
CA_SHA256 = "2089fc5a25836401faee99f722460b01b393999746a0fb817943666d6ecc0458"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def runtime_environment(home):
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "DYLD_", "GRPC_"))
                   and k not in ("VIRTUAL_ENV", "CONDA_PREFIX")}
    environment.update(HOME=str(home), PATH="/usr/bin:/bin:/usr/sbin:/sbin", PYTHONNOUSERSITE="1")
    return environment


def run(command, **kwargs):
    subprocess.run(list(map(str, command)), check=True, **kwargs)


def smoke_worker(worker, descriptor, roots, home, evidence):
    environment = runtime_environment(home)
    run([worker, "--self-test", "--descriptor-set", descriptor, "--roots-file", roots,
         "--report", evidence / "worker-self-test.json"], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = subprocess.run([str(worker), "--worker", "--offline-only", "--descriptor-set", str(descriptor),
        "--roots-file", str(roots)],
        input='{"action":"inspect"}\n{"action":"quit"}\n', text=True,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment, timeout=45, check=True)
    if len(result.stdout) > 65536:
        raise RuntimeError("synthetic_worker_reply_invalid")
    values = [json.loads(line) for line in result.stdout.splitlines()]
    if len(values) != 2 or values[0] != {"schema": 1, "event": "ready", "offline": True}:
        raise RuntimeError("synthetic_worker_reply_invalid")
    value = values[1]
    expected = {"schema": 1, "event": "inspection", "status": "inspected", "matched_rows": 1,
        "valid_archives": 1, "rejected_archives": 0, "account_groups": 1,
        "groups": [{"group_number": 1, "candidate_count": 1, "current_candidate_count": 1}]}
    if value != expected:
        raise RuntimeError("synthetic_worker_inspection_failed")
    write_json(evidence / "frozen-offline-inspection.json", {"synthetic_only": True,
        "offline_inspection_completed": True, "no_network_capture_called": True, "safe_summary": value})


def verify_public_tls(roots, evidence):
    """TLS handshake only against a fixed public hostname; send no HTTP/auth request."""
    context = ssl.create_default_context(cafile=str(roots))
    with socket.create_connection(("id.qseed.jp", 443), timeout=20) as connection:
        with context.wrap_socket(connection, server_hostname="id.qseed.jp") as secured:
            version = secured.version()
            verified = bool(secured.getpeercert())
    if not verified or version not in ("TLSv1.2", "TLSv1.3"):
        raise RuntimeError("public_tls_handshake_failed")
    write_json(evidence / "public-tls-handshake.json", {"schema": 1,
        "host": "id.qseed.jp", "port": 443, "certificate_verified": True,
        "hostname_verified": True, "tls_version": version, "application_bytes_sent": 0,
        "authentication_requested": False, "user_files_read": False, "ca_sha256": digest(roots)})


def smoke_app(app, home, report):
    command = [app / "Contents/MacOS" / APP_NAME, "--app-smoke", "--smoke-home", home, "--smoke-report", report]
    process = subprocess.Popen(list(map(str, command)), env=runtime_environment(Path.home()),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        code = process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
        raise RuntimeError("synthetic_app_smoke_timed_out") from None
    if code != 0 or not report.is_file():
        raise RuntimeError("synthetic_app_smoke_failed")
    value = json.loads(report.read_text())
    if not all(value.get(k) is True for k in ("ok", "gui_started", "window_visible",
            "offline_inspection_completed", "no_network_capture_called")) or value.get("real_account_tested") is not False:
        raise RuntimeError("synthetic_app_smoke_failed")


def build(descriptor, output, archive, evidence, test_report):
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise RuntimeError("Apple Silicon macOS builder required")
    if digest(descriptor) != DESCRIPTOR_SHA256:
        raise RuntimeError("pinned_descriptor_mismatch")
    import certifi
    if importlib.metadata.version("certifi") != CERTIFI_VERSION:
        raise RuntimeError("pinned_ca_dependency_required")
    if digest(certifi.where()) != CA_SHA256:
        raise RuntimeError("pinned_ca_bundle_mismatch")
    if any(path.exists() for path in (output, archive, evidence)):
        raise RuntimeError("new_build_output_required")
    evidence.mkdir(parents=True)
    totals = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    for suite in ET.parse(test_report).getroot().iter("testsuite"):
        for key in totals:
            totals[key] += int(suite.get(key, "0"))
    if totals["tests"] < 100 or any(totals[k] for k in ("failures", "errors", "skipped")):
        raise RuntimeError("synthetic_test_summary_invalid")
    write_json(evidence / "synthetic-test-summary.json", {"schema": 1, "synthetic_only": True, **totals})
    output.parent.mkdir(parents=True, exist_ok=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="idoly-event-preserver-build-") as temp:
        temporary = Path(temp)
        run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
             "--name", WORKER_NAME, "--target-arch", "arm64", "--codesign-identity", "-",
             "--distpath", temporary / "dist", "--workpath", temporary / "work", "--specpath", temporary,
             "--paths", ROOT / "src", "--paths", ROOT / "tools", "--paths", HERE,
             "--hidden-import", "preserve_playcover_events", "--hidden-import", "export_playcover_auth",
             "--hidden-import", "google.protobuf.descriptor_pb2", "--hidden-import", "google.rpc.status_pb2",
             HERE / "worker.py"], cwd=ROOT)
        contents = output / "Contents"
        macos, resources = contents / "MacOS", contents / "Resources"
        macos.mkdir(parents=True)
        resources.mkdir()
        shutil.copytree(temporary / "dist" / WORKER_NAME, resources / "runtime", symlinks=True)
        shutil.copy2(descriptor, resources / "idolypride-6.1.1.pb")
        shutil.copy2(certifi.where(), resources / "cacert.pem")
        ca_license = importlib.metadata.distribution("certifi").locate_file(
            "certifi-" + CERTIFI_VERSION + ".dist-info/licenses/LICENSE")
        shutil.copy2(ca_license, resources / "certifi-LICENSE")
        shutil.copy2(ROOT / "LICENSE", resources / "LICENSE")
        run(["xcrun", "swiftc", "-O", "-parse-as-library", "-target", "arm64-apple-macos13.0",
             "-framework", "SwiftUI", "-framework", "AppKit", HERE / "App.swift", "-o", macos / APP_NAME])
        (contents / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleExecutable": APP_NAME, "CFBundleIdentifier": "game.idolypride.eventpreserver",
            "CFBundleName": "아이프라 이벤트 보존", "CFBundleDisplayName": "아이프라 이벤트 보존",
            "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "0.1.0", "CFBundleVersion": "1",
            "LSMinimumSystemVersion": "13.0", "NSHighResolutionCapable": True,
            "NSPrincipalClass": "NSApplication"}))
        dependencies = ["src/idoly_local/firebase_archive.py", "src/idoly_local/official_session.py",
            "src/idoly_local/event_capture.py", "src/idoly_local/codec.py", "src/idoly_local/schema.py",
            "src/idoly_local/collect.py", "tools/export_playcover_auth.py", "tools/preserve_playcover_events.py"]
        own = ["macos-preserver/" + name for name in ("worker.py", "App.swift", "build_app.py",
            "extract_descriptor.py", "synthetic_home.py", "requirements-build.txt")]
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        provenance = {"schema": 1, "source_commit": commit,
            "source_sha256": {p: digest(ROOT / p) for p in dependencies + own},
            "descriptor_sha256": DESCRIPTOR_SHA256, "source_payload_sha256": PAYLOAD_SHA256,
            "source_payload_github_asset": 732944285, "architecture": "arm64", "minimum_macos": "13.0",
            "python_version": platform.python_version(), "pyinstaller_version": importlib.metadata.version("pyinstaller"),
            "user_python_required": False, "synthetic_tests_only": True,
            "official_account_login_tested": False, "game_client_tested": False,
            "bundled_game_data": ["idolypride-6.1.1.pb"], "bundled_user_credentials": False}
        provenance["tls_roots"] = {"dependency": "certifi", "version": CERTIFI_VERSION,
            "sha256": digest(resources / "cacert.pem"),
            "wheel_sha256": "0f212c2744a9bb6de0c56639a6f68afe01ecd92d91f14ae897c4fe7bbeeef0de"}
        write_json(evidence / "source-provenance.json", provenance)
        write_json(resources / "source-provenance.json", provenance)
        run(["codesign", "--force", "--deep", "--sign", "-", output])
        run(["codesign", "--verify", "--deep", "--strict", output])
        home = create_synthetic_home(temporary / "synthetic-home")
        verify_public_tls(resources / "cacert.pem", evidence)
        smoke_worker(resources / "runtime" / WORKER_NAME, resources / "idolypride-6.1.1.pb",
                     resources / "cacert.pem", home, evidence)
        smoke_app(output, home, evidence / "app-smoke.json")
        relocated = temporary / "이동 검증 with spaces" / output.name
        relocated.parent.mkdir()
        shutil.copytree(output, relocated, symlinks=True)
        smoke_app(relocated, home, evidence / "relocated-app-smoke.json")
        run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", output, archive])
    write_json(evidence / "build-summary.json", {"schema": 1, "artifact": archive.name,
        "sha256": digest(archive), "synthetic_only": True, "release_published": False,
        "signature": "ad-hoc", "apple_notarized": False})
    # Only the known, credential-free reports enter the QA archive. Never zip a HOME or raw logs.
    qa = archive.with_name(archive.stem + "-QA.zip")
    names = ("source-provenance.json", "worker-self-test.json", "frozen-offline-inspection.json",
             "app-smoke.json", "relocated-app-smoke.json", "build-summary.json", "public-tls-handshake.json",
             "synthetic-test-summary.json")
    with ZipFile(qa, "x", compression=ZIP_DEFLATED) as bundle:
        for name in names:
            bundle.write(evidence / name, name)
    return provenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor-set", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--test-report", required=True, type=Path)
    args = parser.parse_args()
    build(*(p.resolve() for p in (args.descriptor_set, args.output, args.archive, args.evidence, args.test_report)))
