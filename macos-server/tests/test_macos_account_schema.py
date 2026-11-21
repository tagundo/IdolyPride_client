"""The app builder consumes the same strict eight-table proof as the publisher."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import build_app
from release_account_contract import CHECKS,TABLES


def report():
    return {"account_management_roundtrip":True,"account_management":{"schema":1,
        "snapshot_tables":list(TABLES),"archive_bytes":123,"archive_sha256":"a"*64,
        "checks":{key:True for key in CHECKS},"gameplay_tested":False}}


def test_builder_requires_exact_eighth_table_and_all_existing_checks():
    value=report();build_app.validate_account_roundtrip(value)
    assert TABLES[-1]=="profile_love_progress" and len(TABLES)==8
    for mutate in (lambda row:row["account_management"]["snapshot_tables"].pop(),
                   lambda row:row["account_management"]["checks"].update({CHECKS[0]:1}),
                   lambda row:row["account_management"].update(gameplay_tested=True)):
        broken=deepcopy(value);mutate(broken)
        with pytest.raises(ValueError):build_app.validate_account_roundtrip(broken)


def test_real_mac_smoke_seeds_love_json_and_checks_new_empty_profiles():
    source=(Path(__file__).resolve().parents[1]/"engine.py").read_text()
    scope=source.split('def _account_roundtrip_reference(',1)[1].split('\ndef smoke(',1)[0]
    assert '"profile_love_progress"' in scope and 'original_bundle["schema"] != 2' in scope
    assert 'indent=1).encode("utf-8") + b"\\n"' in scope
    assert 'state.mutate_love_snapshot("sandbox"' in scope
    assert 'love_fixture.replace(b\'"QA"\', b\'"Mac restore QA"\')' in scope
    assert scope.count('["tables"]["profile_love_progress"] == []')==2
    assert 'and state.snapshot(restored_name)[0].endswith(b"\\xf8\\x7f\\x01")' in scope
