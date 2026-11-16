"""Latest cohort packaging and native sidecar contract; no native tools/network."""
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_app
import engine
from test_build_app import app_build

VERSION = "6b77e0d8a64b26d5bebd09a7c19a47f2dfad2af914c5160418aa2e7292e13a11"


def pin_for(payload):
    return {"schema": 1, "policy": "latest-cohort-overlay-v1", "bytes": payload.stat().st_size,
            "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
            "manifest_sha256": "b" * 64, "master_version": VERSION}


def verifier_for(monkeypatch, payload, proof):
    calls = []
    pin = pin_for(payload)

    def verify_proof(value):
        calls.append("proof")
        if value != proof:
            raise ValueError("latest_data_proof_differs")
        return dict(value)

    def verify_payload(path):
        calls.append("payload")
        assert Path(path) == payload
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == pin["sha256"]
        return dict(pin)

    monkeypatch.setitem(sys.modules, "latest_server_data_pin", SimpleNamespace(
        verify_upgrade_proof=verify_proof, verify_payload=verify_payload, payload_pin=lambda: dict(pin)))
    return pin, calls


def test_actual_builder_copies_verified_cohort_and_records_small_runtime_pin(app_build, monkeypatch, tmp_path):
    payload, output, archive, evidence, commands = app_build
    proof = {"schema": 1, "policy": "latest-cohort-overlay-v1", "source_blob": {"sha256": "a" * 64}}
    proof_path = tmp_path / "server-data-preparation.json"
    proof_path.write_text(json.dumps(proof))
    pin, calls = verifier_for(monkeypatch, payload, proof)
    result = build_app.build(payload, output, archive, evidence, "0.3.36", smoke=False,
                             server_data_upgrade_proof=proof_path)
    resources = output / "Contents/Resources"
    sidecar = resources / "payload-pin.json"
    assert calls == ["proof", "payload"]
    assert sidecar.stat().st_size <= 4096 and json.loads(sidecar.read_text()) == pin
    assert (resources / "ServerData.zip").read_bytes() == payload.read_bytes()
    assert result["server_data_provenance"] == proof and result["payload_pin"] == pin
    assert result["server_data_bytes"] == pin["bytes"]
    assert result["payload_pin_sha256"] == hashlib.sha256(sidecar.read_bytes()).hexdigest()
    bundled = json.loads((resources / "bundle-provenance.json").read_text())
    assert bundled["payload_pin"] == pin and bundled["server_data_provenance"] == proof
    command = next(row for row in commands if "PyInstaller" in row)
    for module in ("idoly_local.public_payload_transaction", "idoly_local.love_compatibility_pins",
                   "idoly_local.public_cohort_support", "idoly_local.latest_cohort_pins"):
        assert command[command.index(module) - 1] == "--hidden-import"


def test_builder_rejects_substituted_proof_before_any_native_command(app_build, monkeypatch, tmp_path):
    payload, output, archive, evidence, commands = app_build
    verifier_for(monkeypatch, payload, {"approved": True})
    proof = tmp_path / "proof.json"
    proof.write_text('{"approved":false}')
    with pytest.raises(ValueError, match="latest_data_proof_differs"):
        build_app.build(payload, output, archive, evidence, "0.3.36", smoke=False,
                        server_data_upgrade_proof=proof)
    assert commands == [] and not output.exists()


def test_builder_rejects_changed_copy_before_signing(app_build, monkeypatch, tmp_path):
    payload, output, archive, evidence, commands = app_build
    proof = tmp_path / "proof.json"
    proof.write_text("{}")
    verifier_for(monkeypatch, payload, {})
    original = build_app.shutil.copy2

    def copy(source, destination, **kwargs):
        result = original(source, destination, **kwargs)
        if Path(destination).name == "ServerData.zip":
            Path(destination).write_bytes(b"substituted")
        return result

    monkeypatch.setattr(build_app.shutil, "copy2", copy)
    with pytest.raises(ValueError, match="Copied server data"):
        build_app.build(payload, output, archive, evidence, "0.3.36", smoke=False,
                        server_data_upgrade_proof=proof)
    assert not any(row[0] == "/usr/bin/codesign" for row in commands)


@pytest.mark.parametrize("kind", ["oversize", "duplicate", "nonfinite", "symlink", "hardlink", "fifo"])
def test_packaging_proof_is_bounded_regular_strict_json(tmp_path, monkeypatch, kind):
    payload = tmp_path / "payload"
    payload.write_bytes(b"test")
    verifier_for(monkeypatch, payload, {})
    proof = tmp_path / "proof.json"
    if kind == "oversize":
        proof.write_bytes(b" " * (512 * 1024 + 1))
    elif kind == "duplicate":
        proof.write_text('{"schema":1,"schema":1}')
    elif kind == "nonfinite":
        proof.write_text('{"number":NaN}')
    elif kind in ("symlink", "hardlink"):
        source = tmp_path / "source"
        source.write_text("{}")
        proof.symlink_to(source) if kind == "symlink" else os.link(source, proof)
    else:
        os.mkfifo(proof)
    with pytest.raises((ValueError, OSError)):
        build_app.latest_payload_metadata(payload, proof)


@pytest.mark.parametrize("damage", ["schema", "policy", "bytes-bool", "bytes-bound", "sha",
                                   "manifest", "version", "extra", "missing", "duplicate", "oversize", "symlink", "hardlink", "fifo"])
def test_engine_refuses_invalid_sidecar_without_calling_installer(tmp_path, monkeypatch, damage):
    payload = tmp_path / "ServerData.zip"
    payload.write_bytes(b"public payload")
    pin = pin_for(payload)
    if damage == "schema": pin["schema"] = True
    elif damage == "policy": pin["policy"] = "future"
    elif damage == "bytes-bool": pin["bytes"] = True
    elif damage == "bytes-bound": pin["bytes"] = 512 * 1024**2 + 1
    elif damage == "sha": pin["sha256"] = "A" * 64
    elif damage == "manifest": pin["manifest_sha256"] = None
    elif damage == "version": pin["master_version"] = "unknown"
    elif damage == "extra": pin["unexpected"] = "value"
    elif damage == "missing": del pin["sha256"]
    sidecar = tmp_path / "payload-pin.json"
    if damage == "duplicate":
        sidecar.write_text('{"schema":1,"schema":1}')
    elif damage == "oversize":
        sidecar.write_bytes(b" " * 4097)
    elif damage in ("symlink", "hardlink"):
        source = tmp_path / "source.json"
        source.write_text(json.dumps(pin))
        sidecar.symlink_to(source) if damage == "symlink" else os.link(source, sidecar)
    elif damage == "fifo":
        os.mkfifo(sidecar)
    else:
        sidecar.write_text(json.dumps(pin))
    calls = []
    monkeypatch.setattr(engine, "install_payload", lambda *a, **k: calls.append((a, k)))
    with pytest.raises((ValueError, OSError)):
        engine._install_payload(payload, tmp_path / "data")
    assert calls == []


def test_engine_passes_exact_pin_keywords_and_retains_legacy_fixture_signature(tmp_path, monkeypatch):
    payload = tmp_path / "ServerData.zip"
    payload.write_bytes(b"public payload")
    calls = []
    monkeypatch.setattr(engine, "install_payload", lambda *a, **k: calls.append((a, k)))
    engine._install_payload(payload, tmp_path / "legacy")
    assert calls[-1] == ((payload, tmp_path / "legacy"), {})
    pin = pin_for(payload)
    (tmp_path / "payload-pin.json").write_text(json.dumps(pin))
    engine._install_payload(payload, tmp_path / "managed", "log")
    assert calls[-1] == ((payload, tmp_path / "managed", "log"),
                        {"expected_sha256": pin["sha256"], "expected_bytes": pin["bytes"]})
