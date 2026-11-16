"""Historical Love artifacts retain their original compiler provenance.

Latest production entry points use latest_server_data_pin. The old loader still
rejects changed compiler sources rather than silently claiming a fresh build.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("checked_in_love_payload_pin", ROOT / "tools/love_server_data_pin.py")
pinmod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pinmod)


def test_historical_prepared_pin_keeps_original_source_and_overlay(tmp_path, monkeypatch):
    stored = json.loads((ROOT / "data/love-server-data-pin.json").read_text())
    assert stored["preparation"]["source_commit"] == "2db9be606526d0356af0a3ade3fb344276c99f37"
    with pytest.raises(pinmod.LoveServerDataPinError, match="source_differs"):
        pinmod.load_pin()
    historical = tmp_path / "historical-source"
    for name, expected in stored["component_sources"].items():
        source = ROOT / ("data/legacy-sources/love_catalog.py" if name == "src/idoly_local/love_catalog.py" else name)
        raw = source.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected
        target = historical / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    monkeypatch.setattr(pinmod, "ROOT", historical)
    pin = pinmod.load_pin()
    assert pinmod.output_pin() != pinmod.base_pin()
    assert pinmod.verify_upgrade_proof(pin["upgrade_proof"]) == pin["upgrade_proof"]
    assert pinmod.verify_overlay(ROOT / pin["prepared_overlay"]["path"]) == pin["upgrade_proof"]["prepared_overlay"]
    assert len(pin["prepared_overlay"]["members"]) == 11
