"""Known public incompatibility blocks credentials and irreversible transfer early."""
import json
import threading

import pytest

from idoly_local.official_account import OfficialAccountError
from test_official_import import env, schema, inspect, finish, populate, MASTER, PASSWORD


def begin(env, phase, platform="ios"):
    if phase == "inspect": return None
    job_id = inspect(env, platform);finish(env, "verified")
    return job_id


def perform(env, phase, job_id):
    if phase == "inspect": return inspect(env)
    env.manager.command("official_fetch", {"job_id":job_id})
    return job_id


@pytest.mark.parametrize("platform", ["ios", "android"])
@pytest.mark.parametrize("phase", ["inspect", "fetch"])
@pytest.mark.parametrize("failure,code", [("mismatch","official_master_mismatch"),
    ("unavailable","official_rpc_failed"), ("timeout","deadline_exceeded")])
def test_public_preflight_failures_stop_before_inspect_or_ticket_consumption(env, platform, phase, failure, code):
    job_id = begin(env, phase, platform)
    ticket = env.clients[0].verification if env.clients else None
    if failure == "mismatch": env.preflight_version = "newer-public-master"
    else: env.preflight_error = OfficialAccountError(code)
    if phase == "inspect": job_id = inspect(env, platform)
    else: perform(env, phase, job_id)
    result = finish(env, "failed")
    assert result["error_code"] == code and "preview" not in result
    assert env.calls == ([] if phase == "inspect" else ["inspect"])
    assert env.preflight_calls == [MASTER] * (1 if phase == "inspect" else 2)
    assert ticket is None or not ticket.consumed
    assert not (env.root / "state.db").exists() and not list(env.accounts.base.rglob("*.zip"))
    assert PASSWORD not in json.dumps(env.manager.status())


@pytest.mark.parametrize("relative", ["original-master/master-tag.json", "master-json/!version.txt"])
def test_same_version_local_file_byte_change_blocks_fetch_before_second_network_call(env, relative):
    job_id = begin(env, "fetch")
    ticket = env.clients[0].verification
    path = env.root / relative
    path.write_bytes(path.read_bytes() + b"\n")
    perform(env, "fetch", job_id)
    result = finish(env, "failed")
    assert result["error_code"] == "official_catalog_changed"
    assert env.preflight_calls == [MASTER] and env.calls == ["inspect"] and not ticket.consumed


@pytest.mark.parametrize("phase", ["inspect", "fetch"])
def test_local_change_during_anonymous_request_is_detected_before_credentials_or_execute(env, phase):
    job_id = begin(env, phase)
    ticket = env.clients[0].verification if env.clients else None
    path = env.root / "original-master/master-tag.json"
    env.preflight_action = lambda:path.write_bytes(path.read_bytes() + b" ")
    perform(env, phase, job_id)
    result = finish(env, "failed")
    assert result["error_code"] == "official_catalog_changed"
    assert env.calls == ([] if phase == "inspect" else ["inspect"])
    assert ticket is None or not ticket.consumed


@pytest.mark.parametrize("phase", ["inspect", "fetch"])
@pytest.mark.parametrize("end", ["cancel", "expire"])
def test_cancellation_or_expiry_during_preflight_preserves_final_state_without_transfer(env, phase, end):
    job_id = begin(env, phase)
    ticket = env.clients[0].verification if env.clients else None
    env.preflight_started, env.preflight_gate = threading.Event(), threading.Event()
    try:
        job_id = perform(env, phase, job_id)
        assert env.preflight_started.wait(3)
        if end == "cancel":
            env.manager.command("official_cancel", {"job_id":job_id})
        else:
            env.manager._job.timer.fire()
    finally:
        env.preflight_gate.set()
    result = finish(env, "cancelled" if end == "cancel" else "failed")
    if end == "expire": assert result["error_code"] == "official_session_expired"
    assert env.calls == ([] if phase == "inspect" else ["inspect"])
    assert ticket is None or not ticket.consumed
    assert not (env.root / "state.db").exists()


@pytest.mark.parametrize("bad", ["absent", "malformed", "mismatched-local-version"])
def test_local_catalog_must_be_available_and_consistent_before_any_client_network(env, bad):
    path = env.root / "original-master/master-tag.json"
    if bad == "absent": path.unlink()
    elif bad == "malformed": path.write_bytes(b"{not json")
    else: path.write_text(json.dumps({"version":"different-local-version"}))
    inspect(env)
    result = finish(env, "failed")
    assert result["error_code"] == ("official_master_mismatch" if bad == "mismatched-local-version" else "official_catalog_unavailable")
    assert not env.clients and not env.calls


def test_incompatible_public_master_preserves_every_existing_normal_and_media_account_table(env):
    normal = populate(env, "main")
    media = populate(env, "gallery", "media")
    before = normal.account_snapshot("main"), media.account_snapshot("gallery")
    env.preflight_version = "newer-public-master"
    inspect(env);result = finish(env, "failed")
    assert result["error_code"] == "official_master_mismatch" and not env.calls
    assert (normal.account_snapshot("main"), media.account_snapshot("gallery")) == before
