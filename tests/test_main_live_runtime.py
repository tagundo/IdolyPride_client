"""Opt-in native loading must preserve the embedded runtime's port lifecycle."""
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

import grpc
import pytest

from idoly_local import app_runtime, codec
from idoly_local.profiles import new_profile
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.state import State
from test_app_runtime import _Application, _write_bundle


@pytest.fixture
def runtime_bundle(tmp_path, monkeypatch):
    schema = _write_bundle(tmp_path)
    state = State(tmp_path / 'state.db')
    new_profile(state, schema, 'player', 'Preserved manager')
    state.mutate_snapshot('player', schema.fingerprint, lambda raw: raw, setting_info=b'preserved-settings')
    token, _ = state.login('player')
    created = []
    class Application(_Application):
        def __init__(self, *args, **kwargs):
            self.live_options = {key: kwargs.pop(key) for key in ('experimental_main_live', 'live_engine') if key in kwargs}
            super().__init__(*args, **kwargs)
            created.append(self)
    monkeypatch.setitem(sys.modules, 'idoly_local.application', SimpleNamespace(Application=Application))
    monkeypatch.setitem(sys.modules, 'idoly_local.gameplay', SimpleNamespace(
        seed_starter_profile=lambda *a: pytest.fail('existing profile was seeded again'),
        repair_starter_roster=lambda *a: False,
        repair_starter_home_positions=lambda *a: False,
        repair_starter_inventory=lambda *a: False,
        repair_starter_card_level_mission=lambda *a: False))
    return SimpleNamespace(root=tmp_path, schema=schema, state=state, created=created, token=token)


def dump(state):
    with state.connect() as db:
        return tuple(db.iterdump())


def port_pair():
    with socket.socket() as first, socket.socket() as second:
        first.bind(('127.0.0.1', 0))
        second.bind(('127.0.0.1', 0))
        return first.getsockname()[1], second.getsockname()[1]


def assert_ports_free(grpc_port, asset_port):
    for port in (grpc_port, asset_port):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', port))


def check_legacy_rpc(runtime, bundle):
    with grpc.insecure_channel(runtime.status()['grpc_address']) as channel:
        request = channel.unary_unary('/api.User/Get', request_serializer=codec.encode, response_deserializer=codec.decode)
        assert request(b'', timeout=3) == bundle.state.snapshot('player')[0]


def test_default_off_never_loads_native_library_and_preserves_legacy_application_options(runtime_bundle, monkeypatch):
    bundle = runtime_bundle
    def forbidden(*args):
        pytest.fail('default-off loaded native code')
    monkeypatch.setitem(sys.modules, 'idoly_local.live_engine', SimpleNamespace(NativeLiveEngine=forbidden))
    before = dump(bundle.state)
    runtime = app_runtime.start(bundle.root, profile='player', grpc_port=0, asset_port=0,
                                live_engine_library=bundle.root / 'missing.so')
    try:
        assert runtime.status()['running'] and 'experimental_main_live' not in runtime.status()
        assert bundle.created[-1].live_options == {}
        check_legacy_rpc(runtime, bundle)
        assert dump(bundle.state) == before and bundle.state.authenticated(bundle.token, 'player')
    finally:
        runtime.stop()
    assert not runtime.status()['running']


def test_enabled_mode_loads_one_explicit_library_and_restarts_without_snapshot_changes(runtime_bundle, monkeypatch):
    bundle = runtime_bundle
    loaded, engine = [], object()
    def load(path):
        loaded.append(path)
        return engine
    monkeypatch.setitem(sys.modules, 'idoly_local.live_engine', SimpleNamespace(NativeLiveEngine=load))
    path = bundle.root / 'native' / 'libidoly_live.so'
    before = dump(bundle.state)
    grpc_port, asset_port = port_pair()
    for _ in range(2):
        runtime = app_runtime.start(bundle.root, profile='player', grpc_port=grpc_port, asset_port=asset_port,
            experimental_main_live=True, live_engine_library=path)
        try:
            status = runtime.status()
            assert status['running'] and status['experimental_main_live'] is True and status['live_ruleset'] == 'live-v5'
            assert bundle.created[-1].live_options == {'experimental_main_live': True, 'live_engine': engine}
            check_legacy_rpc(runtime, bundle)
            assert dump(bundle.state) == before
        finally:
            runtime.stop()
            runtime.stop()
        assert_ports_free(grpc_port, asset_port)
    assert loaded == [path, path]


@pytest.mark.parametrize('value', [None, 0, 1, 'true', [], {}])
def test_runtime_rejects_non_boolean_opt_in_before_ports_files_or_native_loading(tmp_path, monkeypatch, value):
    loaded = []
    monkeypatch.setitem(sys.modules, 'idoly_local.live_engine', SimpleNamespace(NativeLiveEngine=lambda p: loaded.append(p)))
    root = tmp_path / 'not-created'
    grpc_port, asset_port = port_pair()
    with pytest.raises(ValueError, match='explicit boolean'):
        app_runtime.start(root, grpc_port=grpc_port, asset_port=asset_port, experimental_main_live=value)
    assert not root.exists() and not loaded
    assert_ports_free(grpc_port, asset_port)


def test_missing_real_native_library_fails_cleanly_and_releases_asset_socket(runtime_bundle):
    bundle = runtime_bundle
    grpc_port, asset_port = port_pair()
    before = dump(bundle.state)
    with pytest.raises(RpcFailure) as error:
        app_runtime.start(bundle.root, profile='player', grpc_port=grpc_port, asset_port=asset_port,
            experimental_main_live=True, live_engine_library=bundle.root / 'does-not-exist.so')
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(bundle.state) == before
    assert_ports_free(grpc_port, asset_port)
    # The failed opt-in must not prevent starting the original server mode.
    runtime = app_runtime.start(bundle.root, profile='player', grpc_port=grpc_port, asset_port=asset_port)
    try:
        check_legacy_rpc(runtime, bundle)
    finally:
        runtime.stop()
    assert_ports_free(grpc_port, asset_port)


def test_enabled_application_failure_after_library_load_releases_ports_and_preserves_account(runtime_bundle, monkeypatch):
    bundle = runtime_bundle
    loaded = []
    monkeypatch.setitem(sys.modules, 'idoly_local.live_engine', SimpleNamespace(NativeLiveEngine=lambda p: loaded.append(p) or object()))
    def rejected(*args, **kwargs):
        raise ValueError('application configuration rejected')
    monkeypatch.setitem(sys.modules, 'idoly_local.application', SimpleNamespace(Application=rejected))
    before = dump(bundle.state)
    grpc_port, asset_port = port_pair()
    with pytest.raises(ValueError, match='configuration rejected'):
        app_runtime.start(bundle.root, profile='player', grpc_port=grpc_port, asset_port=asset_port,
            experimental_main_live=True, live_engine_library=bundle.root / 'test.so')
    assert len(loaded) == 1 and dump(bundle.state) == before
    assert_ports_free(grpc_port, asset_port)
