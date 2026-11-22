#!/usr/bin/env python3
"""Verify the readonly PM origin ABI and exact serialized Scene role recipe.

Uses immutable original images/assets, never calls native functions, changes a
profile, or grants a Scene/Shader/render permission. No binary inputs are added.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from audit_mp4_world import whole
from extract_client_schema import ClientImage

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("pm_get", "lock", "unlock", "map_lookup", "path_get", "string_destroy",
         "map_hash_find", "lock_leaf", "unlock_leaf", "lock_dispatch",
         "unlock_dispatch", "pm_constructor", "object_path", "original_object_path_caller")
ENTRIES = {
    "android": ((0x79473C, 12), (0x797F8C, 60), (0x79690C, 60), (0x7947A8, 204),
                (0x793F18, 168), (0x5521E4, 40), (0x7A6174, 216), (0xE91180, 8),
                (0xE91188, 8), (0xE911F8, 4), (0xE911FC, 4), (0x793FC0, 108),
                (0x795BC4, 148), (0x91A894, 204)),
    "ios": ((0xE26308, 12), (0xE2A274, 64), (0xE289F4, 64), (0xE26398, 216),
            (0xE25ABC, 188), (0xB40850, 68), (0xE38BCC, 216), (0x13AFF30, 8),
            (0x13AFF38, 8), (0xD89854, 4), (0xD89858, 4), (0xE25B78, 116),
            (0xE27AC4, 196), (0xF7277C, 216)),
}
LAYOUTS = {"android": (0x1419FA8, 0x1E8), "ios": (0x97F2CC8, 0x218)}
SCENE_HASHES = {
    "android": "4ccaf2e271e253711fd49a5e0e63aee459a8f2572971023fbaa0a05d0dc9d3cd",
    "ios": "d3205473aa31cd25a0c213501be2210c14f4d1c08dccb266560b1c7000a63fa1",
}
ROLES = ((691, 691, 1487, 72, 4232), (657, 2, 1835, 75, 4231), (657, 13, 1840, 77, 4233))


def audit_native(originals):
    dis = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    proof = {}
    for platform, entries in ENTRIES.items():
        original, raw, offset = whole(originals, platform)
        image = ClientImage(original.m, raw) if platform == "android" else original
        functions = {}
        for name, (address, size) in zip(NAMES, entries):
            body = raw[offset(address):offset(address) + size]
            instructions = list(dis.disasm(body, address))
            assert len(instructions) * 4 == size, "native_body_not_instructions"
            functions[name] = {
                "rva": hex(address), "bytes": size, "prefix": body[:16].hex(),
                "body": body.hex(), "sha256": hashlib.sha256(body).hexdigest(),
                "instructions": [i.mnemonic + " " + i.op_str for i in instructions],
            }
        ops = lambda name: functions[name]["instructions"]
        assert "ldr x0, [x19, #0x58]" in ops("object_path")
        assert "ldr x9, [x8, #0x30]" in ops("object_path")
        assert "mov x20, x8" in ops("object_path"), "path_result_must_be_sret_X8"
        assert "mov w2, #1" in ops("object_path")
        assert any(s.startswith("ldr w1, [") and "#8]" in s
                   for s in ops("original_object_path_caller")), "native_Object_ID_offset_changed"
        assert "str q0, [x19]" in ops("map_lookup")
        assert "str xzr, [x19, #8]" in ops("map_lookup")
        assert not any(s.split(" ", 1)[0] in ("str", "stp", "stur", "stlr", "stxr", "stlxr")
                       for s in ops("map_hash_find")), "map_hash_lookup_must_be_readonly"
        assert any("#0x20]" in s for s in ops("string_destroy"))
        assert any("#0x24]" in s for s in ops("string_destroy"))
        table, count = LAYOUTS[platform]
        pointer = image.read_pointer(table + 0x30) if platform == "android" else image.qword(table + 0x30)
        assert pointer == entries[4][0], "exact_PM_path_virtual_producer_changed"
        proof[platform] = {
            "native_sha256": hashlib.sha256(raw).hexdigest(), "native_bytes": len(raw),
            "vtable": hex(table), "path_count": hex(count), "functions": functions,
            "ABI": "String40 path(PM* X0, int32 file W1, bool alreadyLocked W2); result sret X8",
        }
    return proof


def render_native(proof):
    lines = ["namespace idoly_mp4_origin {", "struct Pin{uintptr_t rva;uint16_t bytes;unsigned char body[256];};",
             "struct Profile{uintptr_t pm_vtable;size_t path_count;Pin pins[14];};"]
    for platform, row in proof.items():
        lines.append("inline constexpr Profile " + platform + "_profile={" + row["vtable"] + "," + row["path_count"] + ",{")
        for name in NAMES:
            fn = row["functions"][name]
            lines.append("{" + fn["rva"] + "," + str(fn["bytes"]) + ",{" +
                         ",".join("0x%02x" % b for b in bytes.fromhex(fn["body"])) + "}},")
        lines.append("}};")
    lines.append("}")
    return "\n".join(lines)


def normalize(source):
    return re.sub(r"\s+", "", re.sub(r"//[^\n]*", "", source).replace("[[maybe_unused]]", ""))


def check_shipping(proof, source):
    marker = source.split("// BEGIN_MP4_PERSISTENT_ORIGIN_PINS", 1)[1].split("// END_MP4_PERSISTENT_ORIGIN_PINS", 1)[0]
    assert normalize(marker) == normalize(render_native(proof)), "persistent_origin_shipping_pins_differ"


def audit_scene(path, platform):
    import UnityPy
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SCENE_HASHES[platform], "original_scene_hash_differs"
    UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.57f1"
    env = UnityPy.load(raw)
    objects = list(env.objects)
    index = {(o.assets_file.name, o.path_id): o for o in objects}
    cache = {}

    def tree(obj):
        key = (obj.assets_file.name, obj.path_id)
        if key not in cache:
            cache[key] = obj.read_typetree()
        return cache[key]

    def resolve(obj, ref):
        name = obj.assets_file.name if not ref.get("m_FileID") else obj.assets_file.externals[ref["m_FileID"] - 1].name
        return index.get((name, ref.get("m_PathID", 0)))

    bundles = [o for o in objects if o.type.name == "AssetBundle"]
    assert len(bundles) == 1
    bundle = bundles[0]
    shared = bundle.assets_file.name
    assert bundle.path_id == 2 and shared.endswith(".sharedAssets")
    main = shared.removesuffix(".sharedAssets")
    assert tree(bundle)["m_IsStreamedSceneAssetBundle"] is True
    assert tree(bundle)["m_SceneHashes"] == [("tln_live_thrx-006", main)]
    roles = []
    for root_id, go_id, renderer_id, material_id, shader_id in ROLES:
        renderer = index[(main, renderer_id)]
        assert renderer.type.name in ("MeshRenderer", "ParticleSystemRenderer")
        go = resolve(renderer, tree(renderer)["m_GameObject"])
        assert go.path_id == go_id and go.assets_file.name == main
        material = resolve(renderer, tree(renderer)["m_Materials"][0])
        assert material.type.name == "Material" and material.path_id == material_id and material.assets_file.name == shared
        shader = resolve(material, tree(material)["m_Shader"])
        assert shader.type.name == "Shader" and shader.path_id == shader_id and shader.assets_file.name == shared
        parents = []
        current = go
        while current:
            parents.append(current.path_id)
            components = [resolve(current, row["component"]) for row in tree(current)["m_Component"]]
            transforms = [o for o in components if o and o.type.name == "Transform"]
            assert len(transforms) == 1
            parent = resolve(transforms[0], tree(transforms[0])["m_Father"])
            current = resolve(parent, tree(parent)["m_GameObject"]) if parent else None
        assert parents[-1] == root_id and len(parents) <= 16
        roles.append([root_id, go_id, renderer_id, material_id, shader_id])
    return {"sha256": SCENE_HASHES[platform], "bundle_local": bundle.path_id,
            "bundle_file": shared, "main_file": main, "roles": roles}


def check_shipping_roles(recipe, source):
    expected = "inline constexpr Role common_roles[]={" + ",".join(
        "{" + ",".join(str(n) for n in role) + "}" for role in recipe["roles"]) + "};"
    assert normalize(expected) in normalize(source), "persistent_origin_shipping_role_recipe_differs"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--android-scene", type=Path)
    parser.add_argument("--ios-scene", type=Path)
    parser.add_argument("--check-shipping", action="store_true")
    args = parser.parse_args()
    proof = {"native": audit_native(args.originals), "scenes": {}}
    source = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    if args.check_shipping:
        check_shipping(proof["native"], source)
    for platform in ("android", "ios"):
        path = getattr(args, platform + "_scene")
        if path:
            proof["scenes"][platform] = audit_scene(path, platform)
            if args.check_shipping:
                check_shipping_roles(proof["scenes"][platform], source)
    args.out.write_text(json.dumps(proof, indent=2) + "\n")
    print("Verified readonly PM native source" + (" and original serialized Scene roles" if proof["scenes"] else "") + "; no runtime admission granted.")


if __name__ == "__main__":
    main()
