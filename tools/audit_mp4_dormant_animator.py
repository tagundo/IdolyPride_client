#!/usr/bin/env python3
"""Pin existing original readonly Animator getters used by a dormant family.

This is ABI/source evidence, not native activation or physical-device proof.
"""
import argparse
import json
from pathlib import Path

from audit_mp4_world import whole

ROOT = Path(__file__).resolve().parents[1]
GETTERS = {
    "root_motion": "get_applyRootMotion",
    "keep_state": "get_keepAnimatorStateOnDisable",
    "write_defaults": "get_writeDefaultValuesOnDisable",
}


def audit(originals):
    result = {}
    for platform in ("android", "ios"):
        original, _, _ = whole(originals, platform)
        rows = {key: original.method("UnityEngine.Animator", name, 0) for key, name in GETTERS.items()}
        for row in rows.values():
            assert row["return"] == "System.Boolean" and not row["static"] and not row["parameters"]
            assert int(row["rva"], 16) and len(row["prefix"]) == 32
        result[platform] = rows
    return result


def pins(result):
    rows = ["// BEGIN_MP4_DORMANT_ANIMATOR_PINS",
            "struct Mp4DormantAnimatorPins {mp4game::Binding root_motion,keep_state,write_defaults;};"]
    for platform, methods in result.items():
        rows.append("[[maybe_unused]] inline constexpr Mp4DormantAnimatorPins mp4_dormant_animator_" + platform + "={")
        for key, method in methods.items():
            prefix = method["prefix"]
            rows.append(" {" + method["rva"] + ",{" + ",".join("0x" + prefix[i:i+2] for i in range(0, 32, 2)) + "}}, // " + key)
        rows.append("};")
    rows += ["#ifdef IDOLY_DARWIN_BRIDGE", "constexpr const auto&mp4_dormant_animator_pins=mp4_dormant_animator_ios;",
             "#else", "constexpr const auto&mp4_dormant_animator_pins=mp4_dormant_animator_android;", "#endif",
             "// END_MP4_DORMANT_ANIMATOR_PINS"]
    return "\n".join(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--check-header", action="store_true")
    args = parser.parse_args()
    result = audit(args.originals)
    if args.check_header:
        bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
        start = bridge.index("// BEGIN_MP4_DORMANT_ANIMATOR_PINS")
        end = bridge.index("// END_MP4_DORMANT_ANIMATOR_PINS") + len("// END_MP4_DORMANT_ANIMATOR_PINS")
        assert bridge[start:end] == pins(result), "Dormant Animator readonly source pins differ"
    args.out.write_text(json.dumps({"schema": 1, "platforms": result}, indent=2) + "\n")
    print("Verified original readonly getters; actual zero graph/bindings/jobs and typed activation origin remain mandatory.")


if __name__ == "__main__":
    main()
