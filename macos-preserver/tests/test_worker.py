"""Bridge tests use synthetic values and injected functions; never any user HOME/auth."""
import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import worker as bridge
from synthetic_home import create


def inventory(groups=1):
    return {"status": "inspected", "matched_rows": groups, "valid_archives": groups,
        "rejected_archives": 0, "account_groups": groups, "groups": [
            {"group_number": n, "candidate_count": 1, "current_candidate_count": 0, "binding": "b" * 64}
            for n in range(1, groups + 1)]}


def cli(value, calls):
    def invoke(argv):
        calls.append(argv)
        print(json.dumps(value))
        return 0
    return invoke


def capture(path, group=None, **changes):
    return {"action": "capture", "output": str(path), "account_group": group,
            "allow_login": True, "allow_menu_visit": True, **changes}


def test_self_test_never_imports_or_calls_real_cli():
    assert bridge.self_test() == {"schema": 1, "synthetic_only": True, "ok": True,
        "offline_inspection_completed": True, "no_network_capture_called": True}


def test_inspection_redacts_unknown_fields():
    calls = []
    value = inventory()
    value["token"] = "SYNTHETIC_PRIVATE_TOKEN"
    value["groups"][0]["uid"] = "SYNTHETIC_PRIVATE_UID"
    result = bridge.Bridge(cli(value, calls)).handle({"action": "inspect"})
    assert "PRIVATE" not in json.dumps(result)
    assert len(calls) == 1 and calls[0][:2] == ["--inspect", "--inventory-nonce"]
    assert "binding" not in json.dumps(result)


@pytest.mark.parametrize("change", [
    {"matched_rows": True}, {"valid_archives": -1}, {"account_groups": 2},
    {"groups": [{"group_number": 1, "candidate_count": 1, "current_candidate_count": 2}]},
])
def test_malformed_inventory_is_fixed_error(change):
    with pytest.raises(bridge.BridgeError) as caught:
        bridge.Bridge(cli({**inventory(), **change}, [])).handle({"action": "inspect"})
    assert caught.value.code == "worker_reply_invalid"


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_capture_requires_literal_consent(tmp_path, value):
    calls = []
    worker = bridge.Bridge(cli(inventory(), calls))
    worker.handle({"action": "inspect"})
    with pytest.raises(bridge.BridgeError) as caught:
        worker.handle(capture(tmp_path / "new", allow_login=value))
    assert caught.value.code == "existing_login_opt_in_required"
    assert len(calls) == 1 and calls[0][0] == "--inspect"


def test_offline_only_rejects_capture_even_with_consent(tmp_path):
    calls = []
    worker = bridge.Bridge(cli(inventory(), calls), offline_only=True)
    worker.handle({"action": "inspect"})
    with pytest.raises(bridge.BridgeError) as caught:
        worker.handle(capture(tmp_path / "new"))
    assert caught.value.code == "offline_only"
    assert len(calls) == 1 and calls[0][0] == "--inspect"


def test_ambiguous_group_never_picks_newest(tmp_path):
    worker = bridge.Bridge(cli(inventory(2), []))
    worker.handle({"action": "inspect"})
    with pytest.raises(bridge.BridgeError) as caught:
        worker.handle(capture(tmp_path / "new"))
    assert caught.value.code == "account_selection_required_or_invalid"


def test_capture_explicit_flags_and_only_bound_output(monkeypatch, tmp_path):
    calls = []
    def fake(argv):
        calls.append(argv)
        print(json.dumps(inventory() if argv[0] == "--inspect" else {
            "status": "preserved", "output": str(tmp_path / "new"),
            "credentials_exported": False, "captured_responses": 8,
            "complete": False, "limitation_count": 2, "consistent_final_snapshot": True,
            "PRIVATE": "SYNTHETIC_PRIVATE_VALUE"}))
        return 0
    monkeypatch.setattr(bridge, "_descriptor", lambda path: None)
    roots = tmp_path / "roots.pem"
    roots.write_text("synthetic-test-roots")
    import hashlib
    monkeypatch.setattr(bridge, "CA_SHA256", hashlib.sha256(roots.read_bytes()).hexdigest())
    worker = bridge.Bridge(fake, tmp_path / "descriptor.pb", roots_file=roots)
    worker.handle({"action": "inspect"})
    result = worker.handle(capture(tmp_path / "new", group=1))
    assert result == {"event": "complete", "output": str(tmp_path / "new"), "capture_count": 8,
        "complete": False, "limitation_count": 2, "consistent_final_snapshot": True}
    assert calls[1] == ["--login-existing-account", "--visit-current-menus", "--output", str(tmp_path / "new"),
        "--descriptor-set", str(tmp_path / "descriptor.pb"), "--roots-file", str(roots),
        "--account-group", "1", "--inventory-nonce", calls[0][2], "--expected-group-binding", "b" * 64]


@pytest.mark.parametrize("raw", ['{bad', json.dumps([1]), json.dumps({"action": "login"}),
    json.dumps({"action": "inspect", "token": "SYNTHETIC_PRIVATE_TOKEN"}),
    json.dumps({"action": "quit", "extra": True})])
def test_invalid_input_fixed_protocol_no_echo(raw):
    sink = io.StringIO()
    bridge.serve(bridge.Bridge(lambda argv: 0), io.StringIO(raw + '\n{"action":"quit"}\n'), sink)
    result = sink.getvalue()
    assert "PRIVATE" not in result and "Traceback" not in result
    assert json.loads(result.splitlines()[1])["event"] == "failure"


def test_cli_exception_and_unknown_failure_never_escape():
    def explode(argv):
        print("SYNTHETIC_PRIVATE_STDERR", file=sys.stderr)
        raise RuntimeError("SYNTHETIC_PRIVATE_EXCEPTION")
    for invoke in (explode, cli({"status": "failed", "code": "SYNTHETIC_PRIVATE_CODE"}, [])):
        sink = io.StringIO()
        bridge.serve(bridge.Bridge(invoke), io.StringIO('{"action":"inspect"}\n'), sink)
        assert "PRIVATE" not in sink.getvalue()


def test_oversized_input_and_output_are_bounded():
    sink = io.StringIO()
    assert bridge.serve(bridge.Bridge(lambda argv: 0), io.StringIO("x" * (bridge.MAX_LINE + 1)), sink) == 1
    def huge(argv):
        print("x" * (bridge.MAX_REPLY + 1))
        return 0
    with pytest.raises(bridge.BridgeError) as caught:
        bridge.Bridge(huge).handle({"action": "inspect"})
    assert caught.value.code == "worker_reply_invalid"


def test_actual_offline_inspect_reads_only_synthetic_home(monkeypatch, tmp_path):
    home = create(tmp_path / "synthetic")
    monkeypatch.setenv("HOME", str(home))
    sys.path.insert(0, str(HERE.parent / "tools"))
    from preserve_playcover_events import main
    from idoly_local import official_session
    def forbidden(*args, **kwargs):
        raise AssertionError("network/auth must not initialize during offline inspection")
    monkeypatch.setattr(official_session, "OfficialHttp", forbidden)
    monkeypatch.setattr(official_session.grpc, "secure_channel", forbidden)
    result = bridge.Bridge(main, offline_only=True).handle({"action": "inspect"})
    assert result["valid_archives"] == result["account_groups"] == result["matched_rows"] == 1
    assert result["groups"][0]["current_candidate_count"] == 1


def test_descriptor_requires_exact_bytes(tmp_path):
    path = tmp_path / "descriptor.pb"
    path.write_bytes(b"synthetic-wrong-bytes")
    with pytest.raises(bridge.BridgeError) as caught:
        bridge._descriptor(path)
    assert caught.value.code == "descriptor_invalid"
