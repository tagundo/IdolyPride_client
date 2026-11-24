"""The MV QA fixture inputs come only from the pinned payload inside the app under test."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("actual_mv_fixture_inputs", ROOT / "tools/actual_mv_fixture_inputs.py")
inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inputs)

MEMBERS = {
    "data/protocol/idolypride-6.1.1.pb": b"descriptor-set",
    "data/master-json/!version.txt": b"0" * 64,
    "data/master-json/Setting.json": b'[{"tutorialMessageId": "m"}]',
    "data/master-json/CardLevel.json": b'[{"level": 2, "requiredExp": "10"}]',
    "data/master-json/Message.json": b'[{"id": "m"}]',
    "data/master-json/Mission.json": b"[]",
    "data/master-json/Other.json": b"[1]",
    "data/original-master/master-tag.json": b"{}",
}


def row(path, raw):
    return {"path": path, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def build(tmp_path, members=MEMBERS, *, payload_name="assets/ServerData.zip", extra_payload=None, symlink=None):
    payload = tmp_path / "ServerData.zip"
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("data/master-json/", b"")  # A directory entry is never extracted.
        for name, raw in members.items():
            info = zipfile.ZipInfo(name)
            if name == symlink:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, raw)
        archive.writestr("data/payload-manifest.json", b"{}")
    raw = payload.read_bytes()
    pin = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
           "members": [row(name, value) for name, value in MEMBERS.items()]}
    apk = tmp_path / "current-unified-observer.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("classes.dex", b"dex")
        archive.writestr(zipfile.ZipInfo(payload_name), raw, compress_type=zipfile.ZIP_STORED)
        if extra_payload is not None:
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr(zipfile.ZipInfo(payload_name), extra_payload)
    return apk, pin


def test_extracts_the_descriptor_set_and_every_pinned_master_file(tmp_path):
    apk, pin = build(tmp_path)
    output = tmp_path / "fixture"
    receipt = inputs.extract(apk, output, pin=pin)
    assert (output / "protocol/idolypride-6.1.1.pb").read_bytes() == b"descriptor-set"
    assert sorted(path.name for path in (output / "master-json").iterdir()) == [
        "!version.txt", "CardLevel.json", "Message.json", "Mission.json", "Other.json", "Setting.json"]
    assert sorted(path.name for path in output.iterdir()) == ["master-json", "protocol"]
    assert receipt["server_data"] == {"member": "assets/ServerData.zip", "bytes": pin["bytes"], "sha256": pin["sha256"],
                                      "pin": "data/korean-master-data-pin.json output"}
    assert receipt["source_apk"]["sha256"] == hashlib.sha256(apk.read_bytes()).hexdigest()
    assert receipt["descriptor_set"] == "protocol/idolypride-6.1.1.pb" and receipt["master_dir"] == "master-json"
    assert receipt["master_files"] == 6 and receipt["gameplay_evidence"] is False and receipt["qa_only"] is True
    for entry in receipt["files"]:
        assert hashlib.sha256((output / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
    # No scratch copy of the payload is left beside the inputs.
    assert sorted(path.name for path in tmp_path.iterdir()) == ["ServerData.zip", "current-unified-observer.apk", "fixture"]


@pytest.mark.parametrize("defect,code", [
    ("payload_hash", "server_data_differs_from_pin"),
    ("payload_size", "server_data_differs_from_pin"),
    ("member_hash", "fixture_input_differs_from_pin"),
    ("unpinned_member", "fixture_input_inventory_differs"),
    ("missing_table", "fixture_inputs_not_pinned"),
    ("unsafe_path", "fixture_input_path_unsafe"),
    ("nested_path", "fixture_input_path_unsafe"),
    ("duplicate_payload", "server_data_member_unavailable"),
    ("no_payload", "server_data_member_unavailable"),
    ("symlink_member", "fixture_input_member_invalid"),
    ("nonempty_output", "fixture_output_not_empty"),
])
def test_any_difference_from_the_pin_is_rejected_and_nothing_is_left(tmp_path, defect, code):
    members = dict(MEMBERS)
    options = {}
    if defect == "unpinned_member":
        members["data/master-json/Extra.json"] = b"[]"
    if defect == "duplicate_payload":
        options["extra_payload"] = b"other"
    if defect == "no_payload":
        options["payload_name"] = "assets/OtherData.zip"
    if defect == "symlink_member":
        options["symlink"] = "data/master-json/Other.json"
    apk, pin = build(tmp_path, members, **options)
    # For unpinned_member the payload hash covers Extra.json, but no member row pins it.
    rows = {entry["path"]: entry for entry in pin["members"]}
    if defect == "payload_hash":
        pin["sha256"] = "0" * 64
    if defect == "payload_size":
        pin["bytes"] += 1
    if defect == "member_hash":
        rows["data/master-json/Mission.json"]["sha256"] = "1" * 64
    if defect == "missing_table":
        pin["members"] = [entry for entry in pin["members"] if entry["path"] != "data/master-json/Mission.json"]
    if defect == "unsafe_path":
        pin["members"].append(row("data/master-json/../escape.json", b"[]"))
    if defect == "nested_path":
        pin["members"].append(row("data/master-json/sub/inner.json", b"[]"))
    output = tmp_path / "fixture"
    if defect == "nonempty_output":
        output.mkdir()
        (output / "stale.json").write_text("{}")
    with pytest.raises(inputs.FixtureInputError, match="^" + code + "$"):
        inputs.extract(apk, output, pin=pin)
    if defect == "nonempty_output":
        assert sorted(path.name for path in output.iterdir()) == ["stale.json"]
    else:
        assert not output.exists()
    assert not list(tmp_path.glob(".server-data-*"))


def test_cli_writes_the_receipt_and_rejects_with_a_code(tmp_path, monkeypatch, capsys):
    apk, pin = build(tmp_path)
    monkeypatch.setattr(inputs, "load_output_pin", lambda: pin)
    receipt = tmp_path / "evidence" / "profile-fixture-inputs.json"
    receipt.parent.mkdir()
    assert inputs.main(["--apk", str(apk), "--output", str(tmp_path / "fixture"), "--receipt", str(receipt)]) == 0
    assert json.loads(receipt.read_text())["master_files"] == 6
    assert json.loads(capsys.readouterr().out)["descriptor_set"] == "protocol/idolypride-6.1.1.pb"
    assert inputs.main(["--apk", str(apk), "--output", str(tmp_path / "fixture"), "--receipt", str(receipt)]) == 1
    assert "fixture_output_not_empty" in capsys.readouterr().err


def test_tracked_pin_covers_every_fixture_input_offline():
    pin = inputs.load_output_pin()
    rows, wanted = inputs.pinned_rows(pin)
    # Shape only: the pin file is the authority, so a Korean pin refresh needs no test edit.
    assert re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
    assert inputs.PROTOCOL in wanted and rows[inputs.PROTOCOL]["bytes"] > 0
    tables = {path.rsplit("/", 1)[1] for path in wanted if path.startswith(inputs.MASTER_PREFIX)}
    assert set(inputs.REQUIRED_TABLES) <= tables
