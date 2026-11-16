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
    assert pin["preparation"]["source_commit"] == "e917b61364a08cddbee9e5e0fc969ccae3459ccc"
    assert pin["preparation"]["run_id"] == 43902573251
    assert pin["preparation"]["report_sha256"] == "cecd65d35a87f7d8a10d2e62f2f63a019c262bc27c9f9d192a02067feae2e729"
    assert pin["output"]["bytes"] == 198675046
    assert pin["output"]["sha256"] == "7da4d61f9aa42fbddab8480060fce62f76cc48223cb511b44089a408f917c1ce"
    assert pin["output"]["entries"] == 573 and pin["output"]["master_json_tables"] == 64
    assert pin["upgrade_proof"]["original_master"]["pack_count"] == 202
    assert len(pin["component_sources"]) == len(subject.SOURCE_COMPONENTS) == 37
    assert subject.verify_source_pointer() == subject.overlay_pin() == subject.output_pin()
    assert (subject.ROOT/subject.OVERLAY_PATH).stat().st_size < 256
    assert pin["source_blob"] == {"path": subject.OVERLAY_PATH, **subject.output_pin()}
