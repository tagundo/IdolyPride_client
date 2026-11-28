#!/usr/bin/env python3
"""Audit original capture cancellation and renderer queue retirement.

These are source receipts for cleanup custody. They do not authorize a frame,
provide a GPU completion fence, or prove a successfully rendered MP4.
"""
from pathlib import Path
import argparse
import hashlib
import json
import struct

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from audit_mp4_world import whole

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    "android": {"remove": (0x8DFE8BC, 280), "finish": (0x8E15AB0, 704),
                "predicate_type": 25139, "predicate": (0x8DFEC2C, 72),
                "equals": (0x8F9AE94, 48), "equals_leaf": (0x8F9AD6C, 296),
                "remove_where": 0x67B9648, "delegate_ctor": 0x6F513B4,
                "array_clear": 0x86600D4},
    "ios": {"remove": (0x767D200, 280), "finish": (0x7695FEC, 692),
            "predicate_type": 25188, "predicate": (0x767D748, 72),
            "equals": (0x7874DAC, 196), "equals_leaf": (0x7874DAC, 196),
            "remove_where": 0x4522948, "delegate_ctor": 0x4EDAF24,
            "array_clear": 0x6D60B84},
}


def audit(originals):
    dis = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    result = {}
    for platform, pins in PINS.items():
        original, engine, _ = whole(originals, platform)

        def body(key):
            address, length = pins[key]
            raw = original.b[original.offset(address):original.offset(address) + length]
            return {"rva": hex(address), "prefix": raw[:16].hex(), "body": raw.hex(),
                    "instructions": [{"rva": hex(row.address), "bytes": row.bytes.hex(),
                                      "op": row.mnemonic + " " + row.op_str}
                                     for row in dis.disasm(raw, address)]}

        rows = {name: body(name) for name in ("remove", "finish", "predicate", "equals", "equals_leaf")}
        ops = lambda key: [row["op"] for row in rows[key]["instructions"]]
        remove = original.method("VL.Rendering.VLSRPCapture", "Remove", 1,
                                 ("UnityEngine.Rendering.RenderTargetIdentifier",))
        finish = original.method("UnityEngine.Rendering.Universal.ScriptableRenderer", "InternalFinishRendering", 2)
        assert remove["rva"] == rows["remove"]["rva"] and remove["return"] == "System.Boolean"
        assert finish["rva"] == rows["finish"]["rva"]
        assert original.fields("VL.Rendering.VLSRPCameraController")["_capture"]["offset"] == 168
        assert original.fields("VL.Rendering.VLSRPCapture")["_captureRequests"]["offset"] == 32
        assert original.fields("UnityEngine.Rendering.Universal.ScriptableRenderer")["m_ActiveRenderPassQueue"]["offset"] == 48
        assert original.fields("VL.Rendering.VLCapturePass")["_target"]["offset"] == 136
        # The exact compiled Remove allocates a closure carrying only the RTID,
        # then invokes the original closed HashSet.RemoveWhere predicate route.
        assert "bl #" + hex(pins["delegate_ctor"]) in ops("remove")
        assert "bl #" + hex(pins["remove_where"]) in ops("remove")
        assert "ldr x19, [x19, #0x20]" in ops("remove")
        assert any(op.startswith("stp q") and "[x21, #0x10]" in op for op in ops("remove"))
        owner, definition = original.types[pins["predicate_type"]]
        assert owner == ".<>c__DisplayClass3_0"
        assert original.type_name(definition[3]) == "VL.Rendering.VLSRPCapture"
        methods = []
        for mid in range(definition[9], definition[9] + definition[16]):
            method = struct.unpack_from("<7I4H", original.m, original.h[12] + mid * 36)
            if original.string(method[0]) != "<Remove>b__0":
                continue
            assert method[10] == 1
            param = struct.unpack_from("<3I", original.m, original.h[22] + method[4] * 12)
            assert original.type_name(param[2]) == ".RequestData"
            module = next(module for module, first, last in original.images if first <= pins["predicate_type"] < last)
            _, table = original.module(module)
            address = original.qword(table + ((method[6] & 0xFFFFFF) - 1) * 8)
            methods.append(address)
        assert methods == [pins["predicate"][0]]
        assert "bl #" + rows["equals"]["rva"] in ops("predicate")
        if platform == "android":
            assert "bl #" + rows["equals_leaf"]["rva"] in ops("equals")
        # Both original finish bodies clear List count and advance its version,
        # then remove stale managed references from the previous queue payload.
        # Cleanup still needs the actual draw return and physical GPU fence.
        zero_register = "w9" if platform == "android" else "w8"
        pointer_register = "x8" if platform == "android" else "x0"
        assert "ldp w2, " + zero_register + ", [" + pointer_register + ", #0x18]" in ops("finish")
        assert "stp wzr, " + zero_register + ", [" + pointer_register + ", #0x18]" in ops("finish")
        assert "bl #" + hex(pins["array_clear"]) in ops("finish")
        result[platform] = {
            "aot_sha256": hashlib.sha256(original.b).hexdigest(),
            "engine_sha256": hashlib.sha256(engine).hexdigest(),
            "methods": rows, "predicate_type_definition_index": pins["predicate_type"],
            "remove_abi": "bool(Component*, const RenderTargetIdentifier40*, const MethodInfo*)",
            "required_cleanup_receipts": [
                "strongly retained original capture component and selected renderer from verified source",
                "actual private constructor/assignment custody independent of source mutation permission",
                "actual operation and draw unwound plus last-use GPU retirement",
                "actual field-detach or original source-owner retirement receipt; handoff alone is insufficient",
                "original active renderer queue empty with unchanged observed List version",
                "capture HashSet empty or exact single private target/event1010 before original Remove",
                "positive exact Add-producer custody with no intervening ordinary same-target Add",
                "post-Remove empty HashSet and still-empty renderer queue",
            ],
            "not_proven_here": ["runtime ownership", "GPU completion", "successful MP4 export"],
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(audit(args.originals), indent=2) + "\n")


if __name__ == "__main__":
    main()
