"""The checked-in production pin is separate from bootstrap producer fixtures."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("checked_in_love_payload_pin", ROOT / "tools/love_server_data_pin.py")
pinmod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pinmod)


def test_checked_in_prepared_pin_and_overlay_are_current_and_not_the_base():
    # The source-frozen public data are verified independently of any native
    # build. This test needs no SQLCipher or project/runtime import.
    pin = pinmod.load_pin()
    assert pinmod.output_pin() != pinmod.base_pin()
    assert pinmod.verify_upgrade_proof(pin["upgrade_proof"]) == pin["upgrade_proof"]
    assert pinmod.verify_overlay(ROOT / pin["prepared_overlay"]["path"]) == pin["upgrade_proof"]["prepared_overlay"]
    assert len(pin["prepared_overlay"]["members"]) == 11
