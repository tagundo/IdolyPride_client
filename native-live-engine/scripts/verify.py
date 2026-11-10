#!/usr/bin/env python3
"""Exercise the actual C ABI and validate outputs against recovered 6.1.1."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse
import base64
import copy
import ctypes
import hashlib
import json
import sys


class Bridge:
    def __init__(self, library):
        self.library = ctypes.CDLL(str(library))
        self.library.IdolyLiveABIVersion.restype = ctypes.c_uint32
        self.library.IdolyLiveABIVersion.argtypes = []
        assert self.library.IdolyLiveABIVersion() == 1
        self.library.IdolyLiveFree.argtypes = [ctypes.c_void_p]
        self.library.IdolyLiveFree.restype = None
        self.library.IdolyLiveSimulate.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_size_t)]
        self.library.IdolyLiveSimulate.restype = ctypes.c_int

    def call(self, raw, *, declared_length=None):
        data = ctypes.create_string_buffer(raw) if raw is not None else None
        output, error = ctypes.c_void_p(), ctypes.c_void_p()
        length, error_length = ctypes.c_size_t(), ctypes.c_size_t()
        code = self.library.IdolyLiveSimulate(data, len(raw or b"") if declared_length is None else declared_length,
            ctypes.byref(output), ctypes.byref(length), ctypes.byref(error), ctypes.byref(error_length))
        try:
            body = ctypes.string_at(output, length.value) if output else b""
            detail = ctypes.string_at(error, error_length.value).decode("utf-8") if error else ""
            assert bool(output) == (code == 0)
            assert bool(error) == (code != 0)
            assert (code == 0 and body and not detail) or (code != 0 and not body and detail)
            return code, body, detail
        finally:
            self.library.IdolyLiveFree(output)
            self.library.IdolyLiveFree(error)

    def simulate(self, request):
        code, raw, detail = self.call(json.dumps(request, separators=(",", ":")).encode())
        assert code == 0, (code, detail)
        return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--stock-input", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-quest-start", type=Path,
                        help="Optional prior stock QuestStartResponse for exact trajectory comparison")
    args = parser.parse_args()
    sys.path.insert(0, str(args.project / "src"))
    from google.protobuf import message_factory
    from idoly_local.schema import Schema

    schema = Schema.from_descriptor_set(args.project / "data/protocol/idolypride-6.1.1.pb")
    result_type = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("api.LiveResult"))
    user_type = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("api.LiveUserInfo"))
    request = json.loads(args.stock_input.read_text())
    request.update(input_version=1, seed=123456, timeout_ms=10000)
    original_json = json.dumps(request, sort_keys=True)
    bridge = Bridge(args.library)
    raw = bridge.simulate(request)
    result = result_type.FromString(raw)
    clean = result_type(); clean.CopyFrom(result); clean.DiscardUnknownFields()
    assert result.SerializeToString(deterministic=True) == clean.SerializeToString(deterministic=True)
    assert result.userInfos[0].userResult.score == 4781 and result.cleared
    assert len(result.charts) == 183 and sum(len(row.beats) for row in result.charts) == 855
    assert not result.detailLogId and not result.isDisplayDetailAvailable
    assert all(len(row.cardStatuses) == 5 and len(row.userStatuses) == 1 for row in [result.preChart, *result.charts])
    trace = sum(beat.score for row in result.charts for beat in row.beats)
    trace += sum(row.activatedSkill.score for row in result.charts if row.HasField("activatedSkill"))
    trace += sum(skill.score for row in result.charts for skill in row.activatedPassiveSkills)
    trace += sum(skill.score for skill in result.activatedPassiveSkills)
    assert trace == result.userInfos[0].userResult.score
    assert trace == sum(row.totalScore for row in result.userInfos[0].userResult.cardResults)
    assert result.charts[-1].userStatuses[0].totalScore == trace
    expected_path = args.expected_quest_start
    if expected_path is not None:
        expected = schema.response_type("/api.Quest/Start").FromString(expected_path.read_bytes()).result
        assert expected == result
    assert bridge.simulate(request) == raw
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(body == raw for body in pool.map(bridge.simulate, [request] * 16))
    assert json.dumps(request, sort_keys=True) == original_json

    zero = copy.deepcopy(request)
    for index, encoded in enumerate(zero["proto"]["UserInfo"]):
        user = user_type.FromString(base64.b64decode(encoded))
        for card in user.userDeck.cards:
            card.vocal = card.dance = card.visual = 0
        zero["proto"]["UserInfo"][index] = base64.b64encode(user.SerializeToString()).decode()
    failed = result_type.FromString(bridge.simulate(zero))
    assert not failed.cleared and failed.userInfos[0].userResult.score == 0
    assert bridge.simulate(zero) == failed.SerializeToString(deterministic=True)

    errors = []
    for raw_bad, declared in ((None, None), (b"", None), (b"{", None), (b"{} {}", None),
                              (b"{}", None), (b"x", (16 << 20) + 1)):
        code, _raw, detail = bridge.call(raw_bad, declared_length=declared)
        assert code == 1 and detail
        errors.append("bounded-invalid-input")
    malformed = copy.deepcopy(request)
    malformed["proto"]["Quest"] = [base64.b64encode(b"\x80").decode()]
    code, _, detail = bridge.call(json.dumps(malformed).encode())
    assert code == 1 and "malformed Quest" in detail
    unknown = copy.deepcopy(request); unknown["unrecognized"] = True
    assert bridge.call(json.dumps(unknown).encode())[0] == 1
    unsupported = copy.deepcopy(request); unsupported["proto"]["SkillEfficacy"] = []
    code, _, detail = bridge.call(json.dumps(unsupported).encode())
    assert code == 2 and detail
    assert bridge.library.IdolyLiveSimulate(None, 0, None, None, None, None) == 1
    bridge.library.IdolyLiveFree(None)
    for _ in range(32):
        assert bridge.simulate(request) == raw
        assert bridge.call(b"{")[0] == 1
    assert bridge.simulate(request) == raw

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "stock-main-live-result.pb").write_bytes(raw)
    (args.output / "stock-input.json").write_text(json.dumps(request, separators=(",", ":")) + "\n")
    report = {"abi_version": 1, "ruleset": "live-v5", "local_rules_only": True,
        "official_score_equivalence_tested": False, "schema_sha256": schema.fingerprint,
        "library_sha256": hashlib.sha256(args.library.read_bytes()).hexdigest(),
        "result_sha256": hashlib.sha256(raw).hexdigest(), "result_bytes": len(raw),
        "stock_score": trace, "stock_clear": True, "zero_attribute_score": 0, "zero_attribute_clear": False,
        "chart_events": 183, "beat_entries": 855, "five_cards_one_user_per_snapshot": True,
        "same_seed_exact_bytes": True, "parallel_calls_exact_bytes": True,
        "source_stock_harness_exact_result": True if expected_path is not None else None, "input_immutable": True,
        "malformed_size_and_null_boundary_checks": True, "unsupported_explicit_error": True,
        "caller_freed_success_and_error_buffers": True, "repeated_success_and_error_calls": 32,
        "unknown_fields": False, "trace_score_conserved": True,
        "detail_analysis_disabled": True, "account_settlement_implemented": False,
        "android_execution_tested": False, "macos_build_tested": False}
    (args.output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
