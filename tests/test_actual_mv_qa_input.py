"""Current-source QA packaging cannot reuse an old or adapted game producer."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location("actual_mv_qa_input", ROOT / "tools/actual_mv_qa_input.py")
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)
COMMIT, APK = "a" * 40, "b" * 64
BLOBS = {"one": b"x", "two": b"two"}


def receipt():
    return {"schema": 1, "prototype": True, "release_eligible": False, "source_commit": COMMIT,
        "working_tree_snapshot": False, "compiled_source_unchanged_during_build": True,
        "public_apk_inputs_unchanged": True, "apk_sha256": APK, "apk_bytes": 100,
        "inputs": {"client_sha256": qa.unified.CLIENT_SHA256, "server_sha256": qa.unified.SERVER_SHA256},
        "signed_certificate_sha256": qa.unified.CERTIFICATE,
        "source_files": [{"path": k, "bytes": len(v), "sha256": hashlib.sha256(v).hexdigest()} for k, v in BLOBS.items()],
        "preservation": {"original_dex_and_sdk_native_unchanged": True, "resources_arsc_unchanged": True,
                         "owned_presentation_addon_replaced": True},
        "native_addon_build": {"source_commit": COMMIT, "abi": "arm64-v8a", "source_unchanged_during_build": True,
                               "source_sha256": {"first": "d" * 64, "second": "e" * 64}}}


def test_exact_current_complete_producer_report_passes_pure_gate_only():
    assert qa.report_metadata(receipt(), COMMIT, APK, 100, BLOBS)["abi"] == "arm64-v8a"


@pytest.mark.parametrize("field,value", [
    ("schema", True), ("source_commit", "c" * 40), ("working_tree_snapshot", True),
    ("compiled_source_unchanged_during_build", False), ("public_apk_inputs_unchanged", False),
    ("apk_sha256", "d" * 64), ("apk_bytes", True), ("release_eligible", True),
])
def test_rejects_old_dirty_unbound_or_release_eligible_input(field, value):
    data = receipt()
    data[field] = value
    with pytest.raises(ValueError, match="producer_identity"):
        qa.report_metadata(data, COMMIT, APK, 100, BLOBS)


def test_source_receipt_must_include_exact_complete_current_source_bytes():
    for mutation in (lambda r: r["source_files"].pop(),
                     lambda r: r["source_files"][0].update(bytes=True),
                     lambda r: r["source_files"][0].update(sha256="0" * 64),
                     lambda r: r["source_files"].append(r["source_files"][0])):
        data = receipt()
        mutation(data)
        with pytest.raises(ValueError, match="source_closure"):
            qa.report_metadata(data, COMMIT, APK, 100, BLOBS)


@pytest.mark.parametrize("path,value,error", [
    (("inputs", "client_sha256"), "0" * 64, "producer_inputs"),
    (("preservation", "original_dex_and_sdk_native_unchanged"), False, "not_preserved"),
    (("native_addon_build", "source_commit"), "0" * 40, "native_receipt"),
    (("native_addon_build", "source_unchanged_during_build"), False, "native_receipt"),
])
def test_original_sdk_aes_and_current_addon_provenance_are_separate_required_gates(path, value, error):
    data = receipt()
    data[path[0]][path[1]] = value
    with pytest.raises(ValueError, match=error):
        qa.report_metadata(data, COMMIT, APK, 100, BLOBS)


@pytest.fixture
def bound_apk(tmp_path, monkeypatch):
    native = {"client-presentation/native/bridge.cpp": b"bridge source",
              "client-presentation/native/profile.json": b"profile source",
              "android-diagnostics/native/build_native.py": b"dependency builder"}
    for name, raw in native.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    aes, unity, addon = b"original aes", b"original unity", b"current owned addon"
    monkeypatch.setattr(qa, "ORIGINAL_AES", hashlib.sha256(aes).hexdigest())
    monkeypatch.setattr(qa, "ORIGINAL_UNITY", hashlib.sha256(unity).hexdigest())
    monkeypatch.setattr(qa.unified, "source_snapshot", lambda root, commit, dirty: (BLOBS, {}, False))
    def git_show(command, timeout):
        assert command[:4] == ["git", "-C", str(tmp_path), "show"]
        commit, name = command[4].split(":", 1)
        assert commit == COMMIT
        return native[name]
    monkeypatch.setattr(qa.subprocess, "check_output", git_show)
    marker = {"package": qa.unified.PACKAGE, "process_mode": "same", "prototype": True}
    path = tmp_path / "current.apk"
    with ZipFile(path, "w") as archive:
        for name, raw in ((qa.AES, aes), (qa.UNITY, unity), (qa.unified.OWN_BRIDGE, addon),
                          (qa.unified.MARKER, json.dumps(marker).encode())):
            archive.writestr(name, raw)
    data = receipt()
    data.update(apk_sha256=qa.sha(path), apk_bytes=path.stat().st_size, marker=marker)
    data["native_addon_build"].update(source_sha256={k: hashlib.sha256(v).hexdigest() for k, v in native.items()},
                                     bytes=len(addon), sha256=hashlib.sha256(addon).hexdigest())
    report = tmp_path / "current.provenance.json"
    report.write_text(json.dumps(data))
    return path, report, tmp_path, data


def test_current_unified_zip_and_exact_native_source_closure_are_independently_checked(bound_apk):
    apk, report, root, _ = bound_apk
    checked = qa.validate_current(apk, report, COMMIT, qa.sha(apk), root)
    assert checked["sdk_aes_store_adaptations"] is False
    assert checked["native_sources_verified"] == 3


def test_native_receipt_subset_cannot_omit_a_current_header(bound_apk):
    apk, report, root, _ = bound_apk
    (root / "client-presentation/native/new_clock.hpp").write_bytes(b"new clock source")
    with pytest.raises(ValueError, match="native_source_closure_differs"):
        qa.validate_current(apk, report, COMMIT, qa.sha(apk), root)


def test_native_working_bytes_must_match_the_git_blob_and_compiled_receipt(bound_apk):
    apk, report, root, _ = bound_apk
    (root / "client-presentation/native/bridge.cpp").write_bytes(b"edited after compile")
    with pytest.raises(ValueError, match="native_source_bytes_differ"):
        qa.validate_current(apk, report, COMMIT, qa.sha(apk), root)


def test_dirty_current_source_never_qualifies_for_the_actual_game_runner(bound_apk, monkeypatch):
    apk, report, root, _ = bound_apk
    monkeypatch.setattr(qa.unified, "source_snapshot", lambda root, commit, dirty: (BLOBS, {}, True))
    with pytest.raises(ValueError, match="dirty_source"):
        qa.validate_current(apk, report, COMMIT, qa.sha(apk), root)
