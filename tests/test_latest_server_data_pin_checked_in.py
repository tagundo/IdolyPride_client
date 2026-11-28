"""Actual checked-in cohort authority, separate from preparation bootstrap units."""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("latest_pin_checked_in_tests", ROOT/"tools/latest_server_data_pin.py")
subject = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = subject
SPEC.loader.exec_module(subject)


def test_checked_in_latest_pin_has_positive_preparation_and_exact_source_pointer():
    pin = subject.load_pin()
    assert pin["preparation"]["source_commit"] == "8726a7cfaac5b303263005cbef8b1bc226b17dec"
    assert pin["preparation"]["run_id"] == 43908928713
    assert pin["preparation"]["report_sha256"] == "b29b489921f3563ecca0d91c9429b1330d8a58d49bfbf2a1a82813753209197a"
    assert pin["output"]["bytes"] == 198675046
    assert pin["output"]["sha256"] == "3ea45bd9fba07d35cf366d50e8bc7604aeb67ea0aa1cd55f751474a75724dbce"
    assert pin["output"]["entries"] == 573 and pin["output"]["master_json_tables"] == 64
    assert pin["upgrade_proof"]["original_master"]["pack_count"] == 202
    assert len(pin["component_sources"]) == len(subject.SOURCE_COMPONENTS) == 37
    assert subject.verify_source_pointer() == subject.overlay_pin() == subject.output_pin()
    assert (subject.ROOT/subject.OVERLAY_PATH).stat().st_size < 256
    assert pin["source_blob"] == {"path": subject.OVERLAY_PATH, **subject.output_pin()}
