"""Lock finite Actor source pins; static proofs do not imply game execution."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_mp4_timeline_actor import derive, verify_bridge
PROOF = json.loads((ROOT / "tests/fixtures/mp4_timeline_actor_source.json").read_text())


def test_finite_original_callback_pins_match_shipping():
    verify_bridge(PROOF, (ROOT / "client-presentation/native/bridge.cpp").read_text())
    for row in PROOF["platforms"].values():
        assert len(row["callbacks"]) == 40
        assert row["seek_receiver"]["arguments"] == ["VL.Core.VLActorController"]
        assert row["virtual_offsets"] == {"Setup": 0x178, "SetTimelineWeight": 0x1c8, "ResetModel": 0x408}


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_reproduce_actor_pins_and_closed_generic_from_originals(platform):
    originals = Path(os.environ.get("IDOLY_ORIGINAL_CLIENTS", "/workspace/shared/idoly-sdk-cache-analysis"))
    required = ("android-metadata.dat", "android-native.so", "ios-metadata.dat", "ios-native.bin", "mp4-android-analysis/libunity.so")
    if not all((originals / name).is_file() for name in required):
        pytest.skip("unchanged original client corpus is not installed")
    if importlib.util.find_spec("capstone") is None:
        pytest.skip("Capstone is required for original source disassembly")
    result = derive(originals, platform)
    for callback in result["callbacks"]:
        callback.pop("instructions", None)
    assert result == PROOF["platforms"][platform]
