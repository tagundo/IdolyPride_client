import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from idoly_local.assets import create_asset_server
from idoly_local.playback import PlaybackState, validate_settings, validate_report


def report(revision=0, wait=True, **changes):
    return {"schema": 1, "bridge_version": 1, "revision": revision,
            "wait_for_orientation": wait, "supported": True, "applied": True, **changes}


@pytest.mark.parametrize("default_wait", [False, True])
def test_platform_defaults_and_invalid_file_preserve_last_valid_setting(tmp_path, default_wait):
    path = tmp_path / "client-playback.json"
    state = PlaybackState(path, default_wait=default_wait)
    assert state.settings() == {"schema": 1, "revision": 0, "wait_for_orientation": default_wait}
    setting = {"schema": 1, "revision": 3, "wait_for_orientation": not default_wait}
    path.write_text(json.dumps(setting))
    assert state.settings() == setting
    for raw in ('{"schema":1,"schema":1,"revision":4,"wait_for_orientation":true}',
                '[]', '{"schema":1,"revision":true,"wait_for_orientation":false}', ' '*8193):
        path.write_text(raw)
        assert state.status()["settings"] == setting
        assert state.status()["invalid_settings_file"] is True


@pytest.mark.parametrize("changes", [{"schema": True}, {"revision": -1}, {"revision": 2**63},
    {"wait_for_orientation": 0}, {"wait_for_orientation": "false"}, {"quality": 0}])
def test_strict_settings_identity(changes):
    with pytest.raises(ValueError):
        validate_settings({"schema": 1, "revision": 0, "wait_for_orientation": True, **changes})


def test_receipt_is_current_configuration_only_and_expires(tmp_path):
    clock = [10.0]
    path = tmp_path / "client-playback.json"
    state = PlaybackState(path, default_wait=False, clock=lambda: clock[0])
    assert state.status()["client"]["applied"] is False
    state.receive(json.dumps(report(wait=False)).encode())
    assert state.status()["client"]["applied"] is True
    path.write_text('{"schema":1,"revision":1,"wait_for_orientation":true}')
    assert state.status()["client"]["applied"] is False
    state.receive(json.dumps(report(revision=1, wait=False)).encode())
    assert state.status()["client"]["applied"] is False
    state.receive(json.dumps(report(revision=1, wait=True)).encode())
    assert state.status()["client"]["applied"] is True
    clock[0] = 21
    assert state.status()["client"]["applied"] is False
    for changes in ({"supported": 1}, {"supported": False}, {"bridge_version": True}, {"profile": "account"}):
        with pytest.raises(ValueError):
            validate_report(report(**changes))


def test_loopback_http_contract_preserves_graphics_schema_and_account_files(tmp_path):
    public = tmp_path / "public"
    public.mkdir()
    private = tmp_path / "state.db"
    private.write_bytes(b"existing account bytes")
    state = PlaybackState(tmp_path / "client-playback.json", default_wait=False)
    server = create_asset_server("127.0.0.1", 0, public, playback=state)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = "http://127.0.0.1:" + str(server.server_address[1])
    try:
        with urlopen(base+"/client/playback", timeout=3) as response:
            assert response.headers["Cache-Control"] == "no-store"
            assert json.load(response) == {"schema": 1, "revision": 0, "wait_for_orientation": False}
        request = Request(base+"/client/playback/status", data=json.dumps(report(wait=False)).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=3) as response:
            assert json.load(response) == {"accepted": True}
        assert state.status()["client"]["applied"] is True
        for route, method, body, code in [
            ("/client/playback?file=state.db", "GET", None, 404),
            ("/client/playback/status", "GET", None, 404),
            ("/client/playback", "HEAD", None, 404),
            ("/client/playback", "POST", b"{}", 404),
            ("/client/playback/status", "POST", b'{"profile":"account"}', 400),
        ]:
            with pytest.raises(HTTPError) as failure:
                urlopen(Request(base+route, data=body, method=method,
                        headers={"Content-Type": "application/json"}), timeout=3)
            assert failure.value.code == code
        assert private.read_bytes() == b"existing account bytes"
        assert not state.path.exists()  # The HTTP interface never edits preferences.
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
