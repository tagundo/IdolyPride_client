"""Native readbacks remain distinct from requests and from receipt freshness."""
from http.client import HTTPConnection
import json
import threading
from types import SimpleNamespace
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from idoly_local.assets import create_asset_server
from idoly_local.render_probe import RenderProbeState, validate_report


def report(**changes):
    return {"schema": 1, "state": "observed", "actual_mode": 2, "graphics_api": 21,
            "callback_tid": 123, "observations": 1, "sample_age_ms": 0,
            "cpu_frame_ms": None, "gpu_frame_ms": None, "timing_age_ms": None, **changes}


def encode(value):
    return json.dumps(value, separators=(",", ":")).encode()


@pytest.mark.parametrize("mode", range(6))
def test_all_original_enum_modes_are_observations_without_an_applied_claim(mode):
    value = report(actual_mode=mode)
    assert validate_report(value) == value
    assert len(value) == 10 and "applied" not in value and "bridge_version" not in value


@pytest.mark.parametrize("field,value", [
    ("schema", True), ("schema", 2), ("state", "requested"), ("state", []),
    ("actual_mode", True), ("actual_mode", -1), ("actual_mode", 6), ("actual_mode", 2.0),
    ("graphics_api", True), ("graphics_api", -1), ("graphics_api", 256),
    ("callback_tid", True), ("callback_tid", 0), ("callback_tid", 2**31),
    ("observations", True), ("observations", 0), ("observations", 2**63),
    ("sample_age_ms", True), ("sample_age_ms", -1), ("sample_age_ms", 2**63),
    ("timing_age_ms", True), ("timing_age_ms", -1), ("timing_age_ms", 2**63),
    ("cpu_frame_ms", True), ("cpu_frame_ms", 0), ("cpu_frame_ms", -0.1),
    ("cpu_frame_ms", 60000.1), ("cpu_frame_ms", float("nan")),
    ("gpu_frame_ms", float("inf")), ("gpu_frame_ms", "12"),
    ("bridge_version", 1), ("profile", "account"),
])
def test_invalid_reports_are_rejected_without_replacing_last_observation(field, value):
    state = RenderProbeState(clock=lambda: 0)
    state.receive(encode(report()))
    before = state.status()
    with pytest.raises(ValueError):
        state.receive(encode(report(**{field: value})))
    assert state.status() == before


@pytest.mark.parametrize("state_name", ["waiting", "init_failed"])
def test_unobserved_states_require_zero_count_and_null_values(state_name):
    value = {key: None for key in report()}
    value.update(schema=1, state=state_name, observations=0)
    assert validate_report(value) == value
    for field in ("actual_mode", "graphics_api", "callback_tid", "sample_age_ms",
                  "cpu_frame_ms", "gpu_frame_ms", "timing_age_ms", "observations"):
        with pytest.raises(ValueError):
            validate_report({**value, field: 1})


def test_observed_requires_actual_fields_and_unsupported_never_claims_a_known_mode():
    for field in ("actual_mode", "graphics_api", "callback_tid", "sample_age_ms"):
        with pytest.raises(ValueError):
            validate_report(report(**{field: None}))
    value = report(state="unsupported", actual_mode=None, graphics_api=None,
                   callback_tid=None, sample_age_ms=None)
    assert validate_report(value) == value
    assert validate_report({**value, "graphics_api": 255, "callback_tid": 2**31-1,
                            "observations": 2**63-1, "sample_age_ms": 2**63-1})
    with pytest.raises(ValueError):
        validate_report({**value, "actual_mode": 0})
    with pytest.raises(ValueError):
        validate_report({**value, "observations": 0})


@pytest.mark.parametrize("cpu,gpu", [(1, None), (None, 60000), (1.5, 2.5)])
def test_timings_have_their_own_age_and_do_not_decide_mode_freshness(cpu, gpu):
    state = RenderProbeState(clock=lambda: 10)
    value = report(cpu_frame_ms=cpu, gpu_frame_ms=gpu, timing_age_ms=90000)
    state.receive(encode(value))
    assert state.status()["stale"] is False  # Old frame timing is not an old mode sample.
    assert state.status()["client"] == value
    with pytest.raises(ValueError):
        validate_report({**value, "timing_age_ms": None})
    with pytest.raises(ValueError):
        validate_report(report(timing_age_ms=0))
    state.receive(encode({**value, "sample_age_ms": 10000, "timing_age_ms": 0}))
    assert state.status()["stale"] is True  # A fresh timing does not freshen mode.


def test_native_sample_age_and_monotonic_receipt_age_are_added_and_report_is_not_erased():
    now = [100.0]
    state = RenderProbeState(clock=lambda: now[0])
    assert state.status() == {"client": None, "age_seconds": None, "stale": True}
    value = report(sample_age_ms=9000)
    state.receive(encode(value))
    now[0] += .999
    assert state.status()["stale"] is False
    now[0] = 101.0
    assert state.status() == {"client": value, "age_seconds": 1, "stale": True}
    # Polling the JNI cached sample reports its accumulated age, not a new sample.
    state.receive(encode({**value, "sample_age_ms": 10000}))
    assert state.status()["age_seconds"] == 0 and state.status()["stale"] is True
    state.receive(encode(report(observations=2)))
    snapshot = state.status()
    assert snapshot["stale"] is False
    snapshot["client"]["actual_mode"] = 5
    assert state.status()["client"]["actual_mode"] == 2


def test_nonobserved_reports_are_stale_and_new_instances_have_no_client_cache():
    state = RenderProbeState(clock=lambda: 0)
    state.receive(encode(report(state="unsupported", actual_mode=None)))
    assert state.status()["stale"] is True
    assert state.status()["client"]["state"] == "unsupported"
    assert RenderProbeState().status()["client"] is None


def test_duplicate_observation_cannot_refresh_but_counter_or_thread_changes_can_restart():
    now = [0.0]
    state = RenderProbeState(clock=lambda: now[0])
    original = report(observations=5)
    state.receive(encode(original))
    now[0] = 11
    state.receive(encode(original))
    assert state.status()["age_seconds"] == 0
    assert state.status()["stale"] is True
    state.receive(encode(report(observations=6)))
    assert state.status()["stale"] is False
    now[0] = 22
    # A restarted native process may reuse the same TID and reset its counter.
    state.receive(encode(report(observations=1)))
    assert state.status()["stale"] is False
    now[0] = 33
    state.receive(encode(report(observations=1, callback_tid=124)))
    assert state.status()["stale"] is False


@pytest.mark.parametrize("raw", [b"", b" "*8192, b"[]", b"null", b"{}", b"\xff",
    encode(report()).decode().encode("utf-16"), b'{"schema":1,"schema":1}',
    encode(report()).replace(b'"schema":1', b'"schema":1,"schema":1'),
    b"["*1500+b"]"*1500])
def test_malformed_duplicate_nonutf8_and_bounded_messages_fail_closed(raw):
    state = RenderProbeState()
    with pytest.raises(ValueError):
        state.receive(raw)
    assert state.status()["client"] is None


def test_strict_size_boundary_and_rejected_report_leave_existing_observation_intact():
    state = RenderProbeState(clock=lambda: 0)
    raw = encode(report())
    state.receive(raw + b" " * (8191 - len(raw)))
    before = state.status()
    with pytest.raises(ValueError):
        state.receive(raw + b" " * (8192 - len(raw)))
    assert state.status() == before


def test_http_loopback_route_is_canonical_bounded_and_cannot_read_or_write_account_files(tmp_path):
    public = tmp_path / "public"
    (public / "client").mkdir(parents=True)
    (public / "client" / "render-probe").write_bytes(b"must never fall back to a file")
    private = tmp_path / "state.db"
    private.write_bytes(b"unchanged private state")
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    state = RenderProbeState(clock=lambda: 0)
    server = create_asset_server("127.0.0.1", 0, public, render_probe=state)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = "http://127.0.0.1:" + str(server.server_address[1])
    try:
        with urlopen(base + "/client/render-probe", timeout=3) as response:
            assert response.headers["Cache-Control"] == "no-store"
            assert json.load(response) == state.status()
        with urlopen(Request(base + "/client/render-probe", data=encode(report()),
                     headers={"Content-Type": "application/json"}), timeout=3) as response:
            assert json.load(response) == {"accepted": True}
        assert state.status()["client"] == report()
        for route, method, body, headers, code in [
            ("/client/render-probe?file=state.db", "GET", None, {}, 404),
            ("/client/%72ender-probe", "GET", None, {}, 404),
            ("/client//render-probe", "GET", None, {}, 404),
            ("/client//render-probe", "HEAD", None, {}, 404),
            ("/client/render-probe/status", "GET", None, {}, 404),
            ("/client/render-probe", "HEAD", None, {}, 404),
            ("/client/render-probe/status", "POST", b"{}", {}, 404),
            ("/client/%72ender-probe", "POST", b"{}", {}, 404),
            ("/client/render-probe", "POST", b"{}", {}, 400),
            ("/client/render-probe", "POST", b" "*8192, {}, 413),
            ("/client/render-probe", "POST", encode(report()), {"Content-Type": "text/plain"}, 415),
        ]:
            with pytest.raises(HTTPError) as failure:
                urlopen(Request(base + route, method=method, data=body,
                                headers={"Content-Type": "application/json", **headers}), timeout=3)
            assert failure.value.code == code
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        try:
            # Send only headers: this deliberately rejected framing must not
            # depend on a client finishing a body after the server closes it.
            connection.putrequest("POST", "/client/render-probe")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Transfer-Encoding", "chunked")
            connection.endheaders()
            assert connection.getresponse().status == 400
        finally:
            connection.close()
        with mock.patch("idoly_local.assets.ipaddress.ip_address", return_value=SimpleNamespace(is_loopback=False)):
            for body in (None, encode(report())):
                with pytest.raises(HTTPError) as failure:
                    urlopen(Request(base + "/client/render-probe", data=body,
                                    headers={"Content-Type": "application/json"}), timeout=3)
                assert failure.value.code == 403
        assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def test_absent_probe_still_reserves_its_route_without_static_file_fallback(tmp_path):
    (tmp_path / "client").mkdir()
    (tmp_path / "client" / "render-probe").write_bytes(b"not a diagnostic response")
    server = create_asset_server("127.0.0.1", 0, tmp_path)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with pytest.raises(HTTPError) as failure:
            urlopen("http://127.0.0.1:" + str(server.server_address[1]) + "/client/render-probe", timeout=3)
        assert failure.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
