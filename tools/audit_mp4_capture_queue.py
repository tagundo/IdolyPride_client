#!/usr/bin/env python3
"""Pin original Add producer/caller ABI and scalar RTID equality.

These source checks do not install hooks, own a frame, or provide a GPU fence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from audit_mp4_world import whole

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    "android": (0x923D4C8, 0x923D684, 0x923D570, 248),
    "ios": (0x7BCB7E8, 0x7BCB9DC, 0x7BCB8A0, 220),
}


def audit(originals):
    dis = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    result = {}
    for platform, (update_add, capture_add, request_capture, size) in PINS.items():
        original, _, _ = whole(originals, platform)
        signature = ("UnityEngine.Rendering.RenderTargetIdentifier",
                     "UnityEngine.Rendering.Universal.RenderPassEvent")
        add = original.method("VL.Rendering.VLSRPCapture", "Add", 2, signature)
        capture = original.method("VL.Rendering.VLSRPCameraController", "CaptureRequest", 2, signature)
        update = original.method("VL.Rendering.VLSRPCameraController", "UpdateCapturedTexture", 0)
        request = original.method("VL.Rendering.VLSRPCameraController", "CaptureRequest", 0)

        def code(address, count):
            raw = original.b[original.offset(address):original.offset(address) + count]
            return [{"rva": hex(row.address), "op": row.mnemonic + " " + row.op_str}
                    for row in dis.disasm(raw, address)]

        def call(return_pc, target):
            rows = code(return_pc - 4, 4)
            assert rows == [{"rva": hex(return_pc - 4), "op": "bl #" + target["rva"]}]
            return rows[0]

        calls = [call(update_add, add), call(capture_add, add), call(request_capture, capture)]
        # These late BLs are beyond every supported4/20/24-byte entry relay.
        assert update_add > int(update["rva"], 0) + 24
        assert capture_add > int(capture["rva"], 0) + 24
        assert request_capture > int(request["rva"], 0) + 24
        fields = original.fields("UnityEngine.Rendering.RenderTargetIdentifier")
        semantic = {name: fields[name] for name in (
            "m_Type", "m_NameID", "m_InstanceID", "m_BufferPointer",
            "m_MipLevel", "m_CubeFace", "m_DepthSlice")}
        assert [value["offset"] - 16 for value in semantic.values()] == [0, 4, 8, 16, 24, 28, 32]
        instructions = code(int(add["rva"], 0), size)
        ops = [row["op"] for row in instructions]
        assert "mov x21, x1" in ops or "mov x20, x1" in ops
        assert any(op.startswith("ldp q") and ("[x21]" in op or "[x20]" in op) for op in ops)
        assert any("stp w19, wzr" in op for op in ops)
        assert "ldr x20, [x22, #0x20]" in ops or "ldr x0, [x21, #0x20]" in ops
        assert "bl #0x67b8b18" in ops or "bl #0x4521db0" in ops
        intptr = original.method("System.IntPtr", "op_Equality", 2,
                                 ("System.IntPtr", "System.IntPtr"))
        address = int(intptr["rva"], 0)
        assert code(address, 12) == [
            {"rva": hex(address), "op": "cmp x0, x1"},
            {"rva": hex(address + 4), "op": "cset w0, eq"},
            {"rva": hex(address + 8), "op": "ret "}]
        equals = original.method("UnityEngine.Rendering.RenderTargetIdentifier", "Equals", 1,
                                 ("UnityEngine.Rendering.RenderTargetIdentifier",))
        eq_rows = code(int(equals["rva"], 0), 152 if platform == "android" else 200)
        assert [row["op"] for row in eq_rows if row["op"].startswith(("bl ", "blr ", "br "))] == ["bl #" + intptr["rva"]]
        assert fields["m_BufferPointer"]["type"] == "System.IntPtr"
        result[platform] = {
            "aot_sha256": hashlib.sha256(original.b).hexdigest(),
            "add": add, "capture": capture, "update": update, "request": request,
            "returns": [hex(value) for value in (update_add, capture_add, request_capture)],
            "calls": calls, "semantic_target_fields": semantic, "add_body": instructions,
            "scalar_equals": {"target": equals, "body": eq_rows, "intptr": intptr},
            "abi": "void(self, const RTID40* X1, int32 event W2, MethodInfo* X3)",
            "scope": "Actual issued typed Request and exact masked source path required; ordinary Add forwards once and withdraws cancellation, including dedup. No frame/GPU permission.",
        }
    return result


def render(proof):
    lines = ["struct Mp4CaptureQueuePins{mp4game::Binding add,capture,intptr_equal;uintptr_t update_add,capture_add,request_capture;};"]

    def binding(row):
        return "{" + row["rva"] + ",{" + ",".join(hex(value) for value in bytes.fromhex(row["prefix"])) + "}}"

    for platform, row in proof.items():
        lines.append("inline constexpr Mp4CaptureQueuePins mp4_capture_queue_" + platform + "={"
                     + ",".join(binding(value) for value in (row["add"], row["capture"], row["scalar_equals"]["intptr"]))
                     + "," + ",".join(row["returns"]) + "};")
    lines += ["#ifdef IDOLY_DARWIN_BRIDGE", "constexpr const auto&mp4_capture_queue_pins=mp4_capture_queue_ios;",
              "#else", "constexpr const auto&mp4_capture_queue_pins=mp4_capture_queue_android;", "#endif"]
    return "\n".join(lines)


def check_shipping(proof):
    source = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    actual = source.split("// BEGIN_MP4_CAPTURE_QUEUE_PINS", 1)[1].split("// END_MP4_CAPTURE_QUEUE_PINS", 1)[0]

    def normalize(value):
        return re.sub(r"\s+", "", value.replace("[[maybe_unused]]", ""))

    assert normalize(actual) == normalize(render(proof)), "capture_queue_source_pins_differ"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--check-shipping", action="store_true")
    args = parser.parse_args()
    proof = audit(args.originals)
    if args.check_shipping:
        check_shipping(proof)
    args.out.write_text(json.dumps(proof, indent=2) + "\n")
    print("Pinned both original capture Add paths and scalar equality; no runtime admission granted.")


if __name__ == "__main__":
    main()
