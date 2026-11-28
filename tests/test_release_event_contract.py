"""Credential-free Native event QA release evidence validation."""
import ast
from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_event_contract", ROOT / "tools/release_event_contract.py")
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)


def passed():
    return {**{key: True for key in contract.CHECKS}, "native_event_settings": {
        "scope": contract.SCOPE, "event_id": "love-23-0514", "settings_revision": 1,
        "start_time_ms": 1000, "end_time_ms": 1000+30*24*60*60*1000, "ruleset_sha256": "a"*64,
        **{key: True for key in contract.TRUE_FIELDS}, "physical_device_tested": False, "gameplay_tested": False}}


def test_complete_real_native_flow_evidence_is_copied_and_accepted():
    value = passed()
    result = contract.validate_android(value)
    assert result == value["native_event_settings"]
    result["event_id"] = "changed"
    assert value["native_event_settings"]["event_id"] == "love-23-0514"


@pytest.mark.parametrize("key", contract.CHECKS)
@pytest.mark.parametrize("value", [None, False, 1])
def test_each_actual_native_gate_is_strictly_required(key, value):
    report = passed(); report[key] = value
    with pytest.raises(ValueError, match="not_passed"):
        contract.validate_android(report)


@pytest.mark.parametrize("field,value", [("scope", "synthetic UI"), ("event_id", "arbitrary-event"),
    ("settings_revision", True), ("settings_revision", 0), ("settings_revision", 2**53),
    ("start_time_ms", -1), ("start_time_ms", True), ("end_time_ms", 1000), ("end_time_ms", 2**53),
    ("ruleset_sha256", "secret/path"), ("physical_device_tested", True), ("physical_device_tested", 0),
    ("gameplay_tested", True), ("gameplay_tested", 0),
    *[(key, 1) for key in contract.TRUE_FIELDS], *[(key, False) for key in contract.TRUE_FIELDS]])
def test_scope_types_period_and_complete_observations_are_required(field, value):
    report = passed(); report["native_event_settings"][field] = value
    with pytest.raises(ValueError, match="scope_differs"):
        contract.validate_android(report)


def test_missing_or_extra_detail_is_rejected():
    for change in ("remove", "append"):
        report = passed()
        if change == "remove": del report["native_event_settings"]["selection_restored"]
        else: report["native_event_settings"]["unverified_claim"] = True
        with pytest.raises(ValueError): contract.validate_android(report)


def test_release_supported_ids_match_the_source_bound_game_catalog():
    tree = ast.parse((ROOT / "src/idoly_local/love_catalog.py").read_text())
    ids = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == "EVENT_IDS" for target in node.targets))
    assert tuple(ids) == contract.EVENT_IDS
