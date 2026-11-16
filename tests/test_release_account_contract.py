"""No packaged-account preservation claim without every real smoke observation."""
import importlib.util
from pathlib import Path
from copy import deepcopy
import pytest

SPEC = importlib.util.spec_from_file_location("account_release_contract",
    Path(__file__).resolve().parents[1]/"tools/release_account_contract.py")
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)


def valid():
    return {"account_management_roundtrip": True, "account_management": {
        "schema": 1, "snapshot_tables": list(contract.TABLES), "archive_bytes": 32000,
        "archive_sha256": "a"*64, "checks": {key: True for key in contract.CHECKS},
        "gameplay_tested": False}}


def test_complete_actual_account_observations_are_retained_independently():
    smoke = valid()
    result = contract.validate(smoke)
    assert result == smoke["account_management"]
    result["checks"]["mode_isolation"] = False
    assert smoke["account_management"]["checks"]["mode_isolation"] is True


@pytest.mark.parametrize("key", contract.CHECKS)
@pytest.mark.parametrize("value", [False, 1, None])
def test_each_account_preservation_check_is_mandatory_and_boolean(key, value):
    smoke = valid()
    if value is None:
        del smoke["account_management"]["checks"][key]
    else:
        smoke["account_management"]["checks"][key] = value
    with pytest.raises(ValueError):
        contract.validate(smoke)


@pytest.mark.parametrize("case", ["summary", "summary_number", "schema_bool", "missing_table",
    "table_order", "empty_bytes", "bytes_bool", "oversize", "digest", "gameplay_claim", "extra"])
def test_report_identity_and_scope_cannot_be_weakened(case):
    smoke = valid()
    detail = smoke["account_management"]
    if case == "summary": smoke["account_management_roundtrip"] = False
    elif case == "summary_number": smoke["account_management_roundtrip"] = 1
    elif case == "schema_bool": detail["schema"] = True
    elif case == "missing_table": detail["snapshot_tables"].pop()
    elif case == "table_order": detail["snapshot_tables"].reverse()
    elif case == "empty_bytes": detail["archive_bytes"] = 0
    elif case == "bytes_bool": detail["archive_bytes"] = True
    elif case == "oversize": detail["archive_bytes"] = 128*1024*1024+1
    elif case == "digest": detail["archive_sha256"] = "b"*63
    elif case == "gameplay_claim": detail["gameplay_tested"] = True
    else: detail["checks"]["unverified_claim"] = True
    with pytest.raises(ValueError):
        contract.validate(smoke)
