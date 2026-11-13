"""Separate server queue/handler time without changing appearance RPC results."""
from types import SimpleNamespace

import pytest

from idoly_local import codec
from idoly_local import h2_server as h2
from idoly_local.rpc import RpcCode, RpcFailure


def connection(handler, log):
    peer = object.__new__(h2._Connection)
    peer.server = SimpleNamespace(application=SimpleNamespace(handle=handler), _log=log)
    return peer


@pytest.mark.parametrize("path", sorted(h2._APPEARANCE_TIMED))
def test_queue_and_handler_times_do_not_change_encrypted_reply(monkeypatch, path):
    values = iter((12_000_000_000, 12_041_000_000))
    monkeypatch.setattr(h2.time, "monotonic_ns", lambda: next(values))
    context = h2.Context()
    context._appearance_queued_ns = 11_900_000_000
    logs = []
    raw = b"private-account-input"
    peer = connection(lambda route, payload, ctx: b"original-result", logs.append)
    result = peer._invoke(path, raw, context)
    assert codec.decode(result) == b"original-result"
    assert not logs  # A blocked UI callback must not run on the RPC worker.
    assert context._appearance_timing == (41, 100)
    suffix = h2._appearance_timing_suffix(context)
    assert suffix == " [의상룸 API 처리 41ms · 작업 대기 100ms]"
    assert "private" not in suffix


def test_original_failure_survives_failed_timing_observer(monkeypatch):
    monkeypatch.setattr(h2.time, "monotonic_ns", lambda: 100)
    failure = RpcFailure(RpcCode.PERMISSION_DENIED, "original detail")

    def reject(*args):
        raise failure

    def broken_log(*args):
        raise RuntimeError("observation failed")

    peer = connection(reject, broken_log)
    with pytest.raises(RpcFailure) as observed:
        peer._invoke("/api.Costume/CheckBulk", b"", h2.Context())
    assert observed.value is failure


def test_clock_failure_preserves_reply_and_other_routes_are_not_sampled(monkeypatch):
    def broken_clock():
        raise RuntimeError("clock unavailable")

    monkeypatch.setattr(h2.time, "monotonic_ns", broken_clock)
    logs = []
    peer = connection(lambda *args: b"reply", logs.append)
    assert codec.decode(peer._invoke("/api.Costume/CheckBulk", b"", h2.Context())) == b"reply"
    assert codec.decode(peer._invoke("/api.User/Get", b"", h2.Context())) == b"reply"
    assert not logs
