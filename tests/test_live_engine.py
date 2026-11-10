"""Native live ABI ownership tests; real Linux fixtures are optional."""
import base64
from concurrent.futures import ThreadPoolExecutor
import copy
import ctypes
import json
from pathlib import Path
import platform

import pytest

from idoly_local import live_engine
from idoly_local.live_engine import NativeLiveEngine
from idoly_local.rpc import RpcCode, RpcFailure


class Function:
    """A fake exported C function with configurable ctypes declarations."""

    def __init__(self, call):
        self.call = call
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.call(*args)


class FakeNative:
    def __init__(self, *, status=0, result=b"\x08\x01\x12\x03a\x00b", error=None, version=1):
        self.status, self.result, self.error = status, result, error
        self.buffers = {}
        self.freed = []
        self.inputs = []
        self.output_slots = []
        self.after_reply = None
        self.on_free = None
        self.IdolyLiveABIVersion = Function(lambda: version)
        self.IdolyLiveFree = Function(self.free)
        self.IdolyLiveSimulate = Function(self.simulate)

    def allocate(self, raw):
        buffer = ctypes.create_string_buffer(raw)
        address = ctypes.addressof(buffer)
        self.buffers[address] = buffer
        return address

    def write(self, pointer, length, raw):
        if raw is not None:
            pointer._obj.value = self.allocate(raw)
            length._obj.value = len(raw)

    def simulate(self, data, size, output, output_length, failure, failure_length):
        self.inputs.append(bytes(data)[:size])
        slots = [output, output_length, failure, failure_length]
        self.output_slots.append([ctypes.addressof(slot._obj) for slot in slots])
        self.write(output, output_length, self.result)
        self.write(failure, failure_length, self.error)
        if self.after_reply is not None:
            self.after_reply(*slots)
        return self.status

    def free(self, pointer):
        address = pointer.value
        assert address not in self.freed, "A native allocation was freed twice"
        self.freed.append(address)
        buffer = self.buffers.pop(address)
        # Copies returned to Python must survive native allocation release.
        ctypes.memset(address, 0xDD, ctypes.sizeof(buffer))
        if self.on_free is not None:
            self.on_free(address)


@pytest.fixture
def fake_loader(monkeypatch, tmp_path):
    path = tmp_path / "libidoly_live.so"
    path.write_bytes(b"fake native library")
    loads = []
    handles = []
    monkeypatch.setattr(live_engine, "_LIBRARIES", {})

    def install(native=None):
        native = native or FakeNative()
        handles.append(native)

        def load(name):
            loads.append(name)
            return native

        monkeypatch.setattr(live_engine.ctypes, "CDLL", load)
        return native, path, loads

    return install


def failure(call, code):
    with pytest.raises(RpcFailure) as caught:
        call()
    assert caught.value.code == code
    return caught.value


def test_success_copies_exact_bytes_and_frees_once_without_mutating_input(fake_loader):
    native, path, loads = fake_loader()
    expected = native.result
    prepared = {"input_version": 1, "cards": [{"name": "로컬", "value": 3}]}
    before = copy.deepcopy(prepared)
    engine = NativeLiveEngine(path)
    assert engine.simulate(prepared) == expected
    assert json.loads(native.inputs[0]) == prepared == before
    assert len(native.freed) == 1 and not native.buffers
    assert len(set(native.output_slots[0])) == 4
    assert loads == [str(path.resolve())]
    assert native.IdolyLiveABIVersion.argtypes == []
    assert native.IdolyLiveABIVersion.restype is ctypes.c_uint32
    assert native.IdolyLiveFree.argtypes == [ctypes.c_void_p]
    assert native.IdolyLiveFree.restype is None
    assert native.IdolyLiveSimulate.argtypes == [
        ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_size_t),
    ]
    assert native.IdolyLiveSimulate.restype is ctypes.c_int


@pytest.mark.parametrize("status,code", [(1, RpcCode.INVALID_ARGUMENT), (2, RpcCode.UNIMPLEMENTED),
                                        (3, RpcCode.DEADLINE_EXCEEDED), (4, RpcCode.INTERNAL)])
def test_native_statuses_map_with_exact_utf8_error_and_release(fake_loader, status, code):
    detail = "로컬 오류\x00with exact length"
    native, path, _ = fake_loader(FakeNative(status=status, result=None, error=detail.encode()))
    error = failure(lambda: NativeLiveEngine(path).simulate({}), code)
    assert error.details == "Native live engine: " + detail
    assert len(native.freed) == 1 and not native.buffers


@pytest.mark.parametrize("prepared", [None, [], "{}", {"x": b"bytes"}, {"x": {1, 2}},
                                      {"x": float("nan")}, {"x": float("inf")}])
def test_invalid_prepared_input_never_calls_native(fake_loader, prepared):
    native, path, _ = fake_loader()
    failure(lambda: NativeLiveEngine(path).simulate(prepared), RpcCode.INVALID_ARGUMENT)
    assert native.inputs == [] and native.freed == []


def test_circular_input_and_oversized_json_rejected_before_native(fake_loader, monkeypatch):
    native, path, _ = fake_loader()
    engine = NativeLiveEngine(path)
    circular = {}
    circular["self"] = circular
    failure(lambda: engine.simulate(circular), RpcCode.INVALID_ARGUMENT)
    monkeypatch.setattr(live_engine, "_MAX_BYTES", 32)
    # The limit is the encoded JSON byte length, including punctuation.
    assert engine.simulate({"x": "a" * 24}) == native.result
    failure(lambda: engine.simulate({"x": "a" * 25}), RpcCode.INVALID_ARGUMENT)
    assert len(native.inputs) == 1 and len(native.inputs[0]) == 32


def test_real_limit_is_16_mib():
    assert live_engine._MAX_BYTES == 16 * 1024 * 1024


@pytest.mark.parametrize("status,result,error", [
    (0, None, None), (0, b"", None), (0, b"result", b"unexpected error"),
    (1, None, None), (1, None, b""), (1, b"unexpected result", b"error"),
    (1, None, b"\xff"), (5, None, b"unknown status"), (-1, None, b"unknown status"),
])
def test_malformed_response_shapes_and_utf8_are_internal_and_always_freed(fake_loader, status, result, error):
    native, path, _ = fake_loader(FakeNative(status=status, result=result, error=error))
    failure(lambda: NativeLiveEngine(path).simulate({}), RpcCode.INTERNAL)
    assert not native.buffers
    assert len(native.freed) == int(result is not None) + int(error is not None)


@pytest.mark.parametrize("slot", [0, 1, 2, 3])
def test_inconsistent_or_oversized_lengths_are_rejected_before_read(fake_loader, monkeypatch, slot):
    status = 0 if slot < 2 else 1
    native, path, _ = fake_loader(FakeNative(status=status, result=b"result" if status == 0 else None,
                                            error=b"error" if status else None))

    def break_reply(output, output_length, error, error_length):
        if slot == 0:
            output._obj.value = None
        elif slot == 1:
            output_length._obj.value = live_engine._MAX_BYTES + 1
        elif slot == 2:
            error._obj.value = None
        else:
            error_length._obj.value = live_engine._MAX_BYTES + 1

    native.after_reply = break_reply
    engine = NativeLiveEngine(path)

    def forbidden_read(*args):
        pytest.fail("Invalid pointer/length must not be dereferenced")

    monkeypatch.setattr(live_engine.ctypes, "string_at", forbidden_read)
    failure(lambda: engine.simulate({}), RpcCode.INTERNAL)
    if slot in (1, 3):
        assert len(native.freed) == 1 and not native.buffers
    else:
        # A library that hides its allocation address cannot be freed by a caller.
        assert native.freed == []


@pytest.mark.parametrize("status", [0, 1])
def test_wrong_unused_length_rejected_before_read(fake_loader, monkeypatch, status):
    native, path, _ = fake_loader(FakeNative(status=status, result=b"result" if status == 0 else None,
                                            error=b"error" if status else None))

    def break_reply(output, output_length, error, error_length):
        (error_length if status == 0 else output_length)._obj.value = 1

    native.after_reply = break_reply
    engine = NativeLiveEngine(path)
    monkeypatch.setattr(live_engine.ctypes, "string_at", lambda *args: pytest.fail("Unexpected read"))
    failure(lambda: engine.simulate({}), RpcCode.INTERNAL)
    assert len(native.freed) == 1 and not native.buffers


def test_aliased_native_pointers_are_rejected_and_freed_only_once(fake_loader):
    native, path, _ = fake_loader(FakeNative(result=b"result"))

    def alias(output, output_length, error, error_length):
        error._obj.value = output._obj.value
        error_length._obj.value = output_length._obj.value

    native.after_reply = alias
    failure(lambda: NativeLiveEngine(path).simulate({}), RpcCode.INTERNAL)
    assert len(native.freed) == 1 and not native.buffers


@pytest.mark.parametrize("failure_stage", ["call", "read"])
def test_python_boundary_failure_still_releases_native_allocation(fake_loader, monkeypatch, failure_stage):
    native, path, _ = fake_loader()
    engine = NativeLiveEngine(path)

    def fail(*args):
        raise OSError("Simulated native boundary failure")

    if failure_stage == "call":
        native.after_reply = fail
    else:
        monkeypatch.setattr(live_engine.ctypes, "string_at", fail)
    failure(lambda: engine.simulate({}), RpcCode.INTERNAL)
    assert len(native.freed) == 1 and not native.buffers


def test_second_allocation_is_released_even_if_first_free_raises(fake_loader):
    native, path, _ = fake_loader(FakeNative(result=b"result", error=b"unexpected error"))

    def fail_first(address):
        if len(native.freed) == 1:
            raise OSError("Release failed")

    native.on_free = fail_first
    failure(lambda: NativeLiveEngine(path).simulate({}), RpcCode.INTERNAL)
    assert len(native.freed) == 2 and not native.buffers


def test_canonical_library_cache_is_shared_by_aliases_and_concurrent_constructors(fake_loader, tmp_path):
    native, path, loads = fake_loader()
    alias = tmp_path / "alias.so"
    alias.symlink_to(path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        engines = list(pool.map(NativeLiveEngine, [path, alias] * 8))
    assert all(engine._library is native for engine in engines)
    assert loads == [str(path.resolve())]
    assert native in live_engine._LOADED_LIBRARIES


@pytest.mark.parametrize("reason", ["version", "symbol"])
def test_rejected_library_retained_but_never_enters_ready_cache(fake_loader, reason):
    native = FakeNative(version=2 if reason == "version" else 1)
    if reason == "symbol":
        del native.IdolyLiveSimulate
    native, path, loads = fake_loader(native)
    for _ in range(2):
        failure(lambda: NativeLiveEngine(path), RpcCode.FAILED_PRECONDITION)
    assert len(loads) == 2 and path.resolve() not in live_engine._LIBRARIES
    assert native in live_engine._LOADED_LIBRARIES


def test_missing_directory_or_unloadable_library_is_failed_precondition(monkeypatch, tmp_path):
    failure(lambda: NativeLiveEngine(tmp_path / "absent.so"), RpcCode.FAILED_PRECONDITION)
    failure(lambda: NativeLiveEngine(tmp_path), RpcCode.FAILED_PRECONDITION)
    path = tmp_path / "bad.so"
    path.write_bytes(b"not a shared library")

    def fail(*args):
        raise OSError("Wrong architecture")

    monkeypatch.setattr(live_engine.ctypes, "CDLL", fail)
    failure(lambda: NativeLiveEngine(path), RpcCode.FAILED_PRECONDITION)


@pytest.fixture(scope="module")
def real_library():
    path = Path("/workspace/shared/artifacts/live-native-bridge/linux/libidoly_live.so")
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64") or not path.is_file():
        pytest.skip("Optional Linux x86_64 native proof library is unavailable")
    return path


def test_actual_linux_library_rejects_invalid_prepared_input(real_library):
    engine = NativeLiveEngine(real_library)
    error = failure(lambda: engine.simulate({}), RpcCode.INVALID_ARGUMENT)
    assert "input_version" in error.details
    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(lambda _: failure(lambda: engine.simulate({}), RpcCode.INVALID_ARGUMENT).code,
                              range(16)))
    assert codes == [RpcCode.INVALID_ARGUMENT] * 16


def test_actual_linux_stock_and_zero_attributes_are_computed(real_library):
    fixture = real_library.parent.parent / "verification/stock-input.json"
    descriptor = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not fixture.is_file() or not descriptor.is_file():
        pytest.skip("Optional stock prepared input or recovered client descriptor is unavailable")
    # Schema/protobuf are deliberately test-only; the adapter has no such dependency.
    from google.protobuf import message_factory
    from idoly_local.schema import Schema

    schema = Schema.from_descriptor_set(descriptor)
    result_type = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("api.LiveResult"))
    user_type = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("api.LiveUserInfo"))
    prepared = json.loads(fixture.read_text())
    before = copy.deepcopy(prepared)
    engine = NativeLiveEngine(real_library)
    raw = engine.simulate(prepared)
    result = result_type.FromString(raw)
    assert result.cleared and result.userInfos[0].userResult.score == 4781
    assert raw == fixture.with_name("stock-main-live-result.pb").read_bytes()
    assert prepared == before
    zero = copy.deepcopy(prepared)
    for index, encoded in enumerate(zero["proto"]["UserInfo"]):
        user = user_type.FromString(base64.b64decode(encoded))
        for card in user.userDeck.cards:
            card.vocal = card.dance = card.visual = 0
        zero["proto"]["UserInfo"][index] = base64.b64encode(user.SerializeToString()).decode()
    failed = result_type.FromString(engine.simulate(zero))
    assert not failed.cleared and failed.userInfos[0].userResult.score == 0
