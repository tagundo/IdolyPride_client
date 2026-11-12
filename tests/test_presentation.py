"""Visual settings are bounded, private-file driven and acknowledged by the game."""
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from idoly_local.assets import create_asset_server
from idoly_local.presentation import (CAPABILITIES, DEFAULTS, METRICS, PresentationState,
                                      validate_report, validate_settings)


def report(revision=0, status="applied"):
    return {"schema": 1, "bridge_version": 1, "revision": revision, "status": status,
        "capabilities": {key: True for key in CAPABILITIES}, "metrics": {key: 0 for key in METRICS}}


def test_settings_do_not_create_files_and_never_import_account_values(tmp_path):
    account = tmp_path / "state.db"
    account.write_bytes(b"account file must stay untouched")
    path = tmp_path / "client-presentation.json"
    state = PresentationState(path)
    assert state.settings() == DEFAULTS
    assert not path.exists()
    settings = {**DEFAULTS, "revision": 123, "custom_graphics": True, "quality": 40,
        "target_fps": 60, "render_scale": 1.5, "expand_photography": True}
    path.write_text(json.dumps(settings))
    assert state.settings() == settings
    assert PresentationState(path).settings() == settings
    assert account.read_bytes() == b"account file must stay untouched"
    assert not list(tmp_path.glob("media-*"))


@pytest.mark.parametrize("field,value", [("quality", True), ("quality", 41),
    ("target_fps", 1000), ("render_scale", float("nan")), ("render_scale", 3),
    ("max_buffer_pixel", 1023), ("anti_aliasing", 3), ("shadow_resolution", 3000),
    ("expand_photography", 1), ("revision", -1), ("schema", True), ("extra", "private")])
def test_invalid_settings_are_rejected_without_replacing_the_last_valid_values(tmp_path, field, value):
    path = tmp_path / "client-presentation.json"
    path.write_text(json.dumps(DEFAULTS))
    state = PresentationState(path)
    assert state.settings() == DEFAULTS
    invalid = {**DEFAULTS, field: value}
    with pytest.raises(ValueError):
        validate_settings(invalid)
    path.write_text(json.dumps(invalid))
    assert state.settings() == DEFAULTS
    assert state.status()["invalid_settings_file"]


def test_duplicate_and_oversized_files_do_not_escape_into_settings(tmp_path):
    path = tmp_path / "client-presentation.json"
    state = PresentationState(path)
    path.write_text('{"schema":1,"schema":2}')
    assert state.settings() == DEFAULTS and state.status()["invalid_settings_file"]
    path.write_bytes(b" " * 8193)
    assert state.settings() == DEFAULTS and state.status()["invalid_settings_file"]


def test_saved_is_not_applied_and_old_or_expired_ack_is_not_reported_as_applied(tmp_path):
    now = [1.0]
    path = tmp_path / "client-presentation.json"
    path.write_text(json.dumps({**DEFAULTS, "revision": 3}))
    state = PresentationState(path, clock=lambda: now[0])
    assert state.status()["client"]["status"] == "waiting"
    state.receive(json.dumps(report(2)).encode())
    assert state.status()["client"]["status"] == "waiting"
    state.receive(json.dumps(report(3)).encode())
    assert state.status()["client"]["status"] == "applied"
    now[0] += 11
    assert state.status()["client"]["status"] == "waiting"


@pytest.mark.parametrize("status", ["unsupported", "init_failed", "waiting_for_scene"])
def test_fresh_non_success_reports_keep_their_reason_without_claiming_the_requested_revision(tmp_path, status):
    path = tmp_path / "client-presentation.json"
    path.write_text(json.dumps({**DEFAULTS, "revision": 5}))
    state = PresentationState(path)
    state.receive(json.dumps(report(2, status)).encode())
    assert state.status()["client"]["status"] == status
    assert state.status()["client"]["revision"] == 2


@pytest.mark.parametrize("mutate", [lambda x: x.update(password="no"),
    lambda x: x.update(status="arbitrary raw exception"), lambda x: x.update(revision=True),
    lambda x: x["capabilities"].update(quality=1),
    lambda x: x["metrics"].update(vertical_fov=float("inf")),
    lambda x: x["metrics"].update(camera_aspect="private"),
    lambda x: x["metrics"].update(profile="not permitted")])
def test_status_accepts_only_fixed_public_observations(mutate):
    value = report()
    mutate(value)
    with pytest.raises(ValueError):
        validate_report(value)


def test_real_http_route_reads_current_preferences_and_accepts_only_status_posts(tmp_path):
    public = tmp_path / "public"
    public.mkdir()
    path = tmp_path / "client-presentation.json"
    state = PresentationState(path)
    server = create_asset_server("127.0.0.1", 0, public, presentation=state)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/client/presentation", timeout=3) as response:
            assert json.load(response) == DEFAULTS
            assert response.headers["Cache-Control"] == "no-store"
        chosen = {**DEFAULTS, "revision": 5, "expand_photography": True}
        path.write_text(json.dumps(chosen))
        with urlopen(base + "/client/presentation", timeout=3) as response:
            assert json.load(response) == chosen
        request = Request(base + "/client/presentation/status", data=json.dumps(report(5)).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=3) as response:
            assert json.load(response) == {"accepted": True}
        assert state.status()["client"]["status"] == "applied"
        assert json.loads(path.read_text()) == chosen
        for route, method, body in [("/client/presentation?file=state.db", "GET", None),
                ("/client/presentation", "POST", b"{}"),
                ("/client/presentation/status", "POST", b'{"profile":"secret"}')]:
            with pytest.raises(HTTPError) as failed:
                urlopen(Request(base + route, data=body, method=method,
                    headers={"Content-Type": "application/json"}), timeout=3)
            assert failed.value.code in (400, 404)
    finally:
        server.shutdown()
        worker.join(timeout=3)
        server.server_close()
