"""Mandatory release smoke for the actual pinned latest media startup chain.

Ordinary unit runs do not fetch data. The release workflow supplies the already
registered whole ZIP and separately requires both cases with no skips. These
checks run the real installer, preparation functions, Application and listeners;
no fixture authority or prepare_* replacement can mask a stale master gate.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from idoly_local import app_runtime, codec
from idoly_local.gameplay import seed_starter_profile
from idoly_local.public_payload import install_payload, install_bundled_translations
from idoly_local.schema import Schema
from idoly_local.state import State
from tools import latest_server_data_pin


_UNKNOWN = b"\x80\x4b\x7b"
_SCHEMA = "0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3"
_LATEST = "6b77e0d8a64b26d5bebd09a7c19a47f2dfad2af914c5160418aa2e7292e13a11"


@pytest.fixture(scope="module")
def latest_payload():
    source = os.environ.get("IDOLY_LATEST_MEDIA_PAYLOAD")
    if source is None:
        pytest.skip("The mandatory release job supplies the actual pinned latest payload")
    path = Path(source)
    assert path.is_absolute() and path.is_file() and not path.is_symlink()
    pin = latest_server_data_pin.output_pin()
    # A BASE payload or an arbitrary candidate must not satisfy this smoke.
    assert pin == {'bytes': 198675046, 'sha256': '3ea45bd9fba07d35cf366d50e8bc7604aeb67ea0aa1cd55f751474a75724dbce'}
    verified = latest_server_data_pin.verify_payload(path)
    assert {key: verified[key] for key in ("bytes", "sha256")} == pin
    return path, pin


def account_bytes(state, profile):
    captured = state.account_snapshot(profile)
    assert captured is not None
    return State.account_bytes(captured[0])


def ready_start(root, platform):
    def no_download(*args, **kwargs):
        raise AssertionError("The latest media startup smoke must not fetch game assets")

    runtime = app_runtime.start(root, profile="sandbox", media_mode=True,
        resource_platform=platform, grpc_port=0, asset_port=0,
        download_missing_resources=False, resource_fetcher=no_download)
    try:
        status = runtime.status()
        assert status["running"] is True and status["media_mode"] is True
        assert status["profile"] == "sandbox" and status["last_error"] is None
        assert status["language"]["effective_language"] == "ko"
        checks = status["startup_checks"]
        assert checks["state"] == "ready"
        assert {row["id"] for row in checks["checks"] if row["state"] == "ready"} >= {
            "account", "catalog", "protocol", "master", "storage", "http", "grpc"}
        # Exercise the real encrypted loopback H2 listener, not only its flag.
        import grpc
        schema = Schema.from_descriptor_set(root / "protocol/idolypride-6.1.1.pb")
        with grpc.insecure_channel(status["grpc_address"]) as channel:
            raw = channel.unary_unary("/api.System/Check")(b"", timeout=5)
        response = schema.response_type("/api.System/Check").FromString(codec.decode(raw))
        assert response.keepAliveTimeMilliseconds > 0
    finally:
        runtime.stop()
    assert runtime.status()["running"] is False


@pytest.mark.parametrize("platform", ("android", "ios"))
def test_actual_latest_media_preparation_and_restart_preserve_accounts(
        latest_payload, platform, tmp_path, record_property):
    payload, pin = latest_payload
    root = tmp_path / "runtime"
    install_payload(payload, root, expected_bytes=pin["bytes"], expected_sha256=pin["sha256"])
    # This smoke intentionally has no separately distributed ADV/image bundle.
    # Host ordering is retained; absence is a supported optional-package result.
    assert install_bundled_translations(payload, root / "resources", data_dir=root) == {"state": "absent"}
    (root / "client-language.json").write_text('{"schema":1,"language":"ko"}')
    schema = Schema.from_descriptor_set(root / "protocol/idolypride-6.1.1.pb")
    assert schema.fingerprint == _SCHEMA
    assert (root / "master-json/!version.txt").read_text().strip() == _LATEST
    record_property("payload_sha256", pin["sha256"])
    record_property("master_version", _LATEST)
    record_property("resource_platform", platform)

    normal = State(root / "state.db")
    seed_starter_profile(normal, schema, "normal-preserved", root / "master-json",
                         manager_name="Preserved normal manager")
    def normal_canary(raw):
        value = schema.response_type("/api.User/Get").FromString(raw)
        value.balance.freeBalance, value.balance.paidBalance = 71, 3
        value.user.MergeFromString(_UNKNOWN)
        value.MergeFromString(_UNKNOWN)
        return value.SerializeToString()
    normal.mutate_snapshot("normal-preserved", schema.fingerprint, normal_canary)
    normal_before = account_bytes(normal, "normal-preserved")
    normal_snapshot = normal.snapshot("normal-preserved")
    normal_identity = normal.profile("normal-preserved")
    token, _ = normal.login("normal-preserved")

    # New media account: includes every real preflight dependency, in the same
    # order as app startup (including Excursion and Company validation).
    ready_start(root, platform)
    media = State(root / "media-state.db")
    assert media.snapshot("sandbox") is not None
    def media_canary(raw):
        value = schema.response_type("/api.User/Get").FromString(raw)
        assert value.cards and value.characters and value.costumes and value.hairs
        value.user.name = "Preserved media manager"
        value.balance.freeBalance, value.balance.paidBalance = 19, 2
        value.cards[0].MergeFromString(_UNKNOWN)
        value.characters[0].MergeFromString(_UNKNOWN)
        value.user.MergeFromString(_UNKNOWN)
        value.MergeFromString(_UNKNOWN)
        return value.SerializeToString()
    media.mutate_snapshot("sandbox", schema.fingerprint, media_canary)
    before = account_bytes(media, "sandbox")
    media_snapshot, media_schema = media.snapshot("sandbox")
    media_identity = media.profile("sandbox")
    assert _UNKNOWN in media_snapshot and media_schema == schema.fingerprint

    # Existing media account: preparation may not reset identity, selections,
    # balances, progression, opaque fields, or any other account table.
    ready_start(root, platform)
    assert media.snapshot("sandbox") == (media_snapshot, media_schema)
    assert account_bytes(media, "sandbox") == before
    assert media.profile("sandbox") == media_identity
    assert normal.snapshot("normal-preserved") == normal_snapshot
    assert account_bytes(normal, "normal-preserved") == normal_before
    assert normal.profile("normal-preserved") == normal_identity
    assert normal.authenticated(token, "normal-preserved")
