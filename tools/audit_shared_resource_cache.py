#!/usr/bin/env python3
"""Extract exact, version-locked shared-resource hook contracts from originals.

Inputs are read only. This tool makes no network requests and does not launch a
game. Optional hermetic proofs run original leaf instructions in synthetic
Unicorn memory; they do not establish physical-device compatibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

from audit_game_resource_cache import PINS, inspect_metadata, module_table

REGISTRATIONS = {
    "android": {"types": 0x97B7528, "field_offsets": 0x9A13C30},
    "ios": {"types": 0x9CF7808, "field_offsets": 0xA17D708},
}
METHODS = frozenset((
    "Octo.OctoManager.Setup", "Octo.OctoManager._Setup",
    "Octo.OctoFullSettings.get_CachingType", "Octo.OctoFullSettings.set_CachingType",
    "Octo.Loader.Downloader.Update", "Octo.Loader.OctoBaseLoader.PreDownload",
    "Octo.Caching.OctoCaching.IsCached", "Octo.Caching.OctoCaching.GetFilePath",
    "Octo.Loader.OctoAssetBundleLoader.GetItemByName",
    "Octo.Loader.OctoResourceLoader.GetItemByName",
))
PRIMITIVES = {1: "System.Void", 2: "System.Boolean", 3: "System.Char",
    4: "System.SByte", 5: "System.Byte", 6: "System.Int16", 7: "System.UInt16",
    8: "System.Int32", 9: "System.UInt32", 10: "System.Int64", 11: "System.UInt64",
    12: "System.Single", 13: "System.Double", 14: "System.String", 28: "System.Object"}


def need(value, message):
    if not value:
        raise ValueError(message)


def check_original(platform, metadata, native):
    need(platform in PINS, "Unknown platform")
    need(type(metadata) is bytes and type(native) is bytes, "Inputs must be bytes")
    need(hashlib.sha256(metadata).hexdigest() == PINS[platform]["metadata"],
         "Original metadata SHA256 differs")
    need(hashlib.sha256(native).hexdigest() == PINS[platform]["native"],
         "Original native SHA256 differs")


def decode_type(image, pointer, type_names, *, depth=0):
    need(depth < 8, "Generic type recursion exceeds bound")
    data = image.read_pointer(pointer)
    bits = struct.unpack_from("<I", image.native, image.file_offset(pointer) + 8)[0]
    kind = bits >> 16 & 255
    if kind in (17, 18):
        need(data in type_names, "Type definition is outside metadata")
        return type_names[data]
    if kind == 21:
        definition = image.read_pointer(data)
        instance = image.read_pointer(data + 8)
        count = struct.unpack_from("<I", image.native, image.file_offset(instance))[0]
        need(count <= 16, "Generic argument count exceeds bound")
        arguments = image.read_pointer(instance + 8)
        names = [decode_type(image, image.read_pointer(arguments + index * 8),
                            type_names, depth=depth + 1) for index in range(count)]
        return decode_type(image, definition, type_names, depth=depth + 1) + "<" + ",".join(names) + ">"
    if kind == 29:
        return decode_type(image, data, type_names, depth=depth + 1) + "[]"
    need(kind in PRIMITIVES, "Unexpected native type kind")
    return PRIMITIVES[kind]


def native_parameters(full_name, static, parameters):
    result = [] if static else ["this"]
    result.extend(row["name"] + ":" + row["type"] for row in parameters)
    result.append("MethodInfo*")
    return result


def extract_contracts(platform, metadata, native):
    check_original(platform, metadata, native)
    inspect_metadata(metadata)  # Bounds/ownership/token checks before pointer use.
    if platform == "android":
        from extract_client_schema import ClientImage
        image = ClientImage(metadata, native)
    else:
        from extract_ios_schema import MachOClientImage
        image = MachOClientImage(metadata, native)
    header = image.header
    types, definitions = {}, {}
    for index in range(header[41] // 88):
        row = struct.unpack_from("<16I8H2I", metadata, header[40] + index * 88)
        namespace, name = image.string(row[1]), image.string(row[0])
        full_name = namespace + "." + name if namespace else name
        types[index], definitions[index] = full_name, row
    octo = []
    for index, name in types.items():
        if not name.startswith("Octo."):
            continue
        definition = definitions[index]
        for method in range(definition[9], definition[9] + definition[16]):
            row = struct.unpack_from("<7I4H", metadata, header[12] + method * 36)
            full_name = name + "." + image.string(row[0])
            if full_name in METHODS:
                octo.append((full_name, row))
    need(len(octo) == len(METHODS) and {name for name, _ in octo} == METHODS,
         "Pinned method set differs")
    count, table = module_table(image, platform, max(row[6] & 0xFFFFFF for _, row in octo))
    addresses = sorted({image.read_pointer(table + index * 8) for index in range(count)} - {0})
    registrations = REGISTRATIONS[platform]

    def type_name(index):
        return decode_type(image, image.read_pointer(registrations["types"] + index * 8), types)

    methods = []
    for name, row in octo:
        address = image.read_pointer(table + ((row[6] & 0xFFFFFF) - 1) * 8)
        following = next((value for value in addresses if value > address), None)
        need(following is not None and following > address, "Method boundary is unavailable")
        distance = following - address
        prefix_count = min(32, distance)
        parameters = []
        for index in range(row[4], row[4] + row[10]):
            parameter = struct.unpack_from("<3I", metadata, header[22] + index * 12)
            parameters.append({"name": image.string(parameter[0]), "type": type_name(parameter[2])})
        static = bool(row[7] & 0x10)
        methods.append({"name": name, "address": address, "address_hex": hex(address),
            "return_type": type_name(row[2]), "static": static, "parameters": parameters,
            "native_parameters": native_parameters(name, static, parameters),
            "next_mapped_function_distance": distance, "prefix_bytes": prefix_count,
            "prefix_hex": native[image.file_offset(address):image.file_offset(address) + prefix_count].hex(),
            "call_only": distance < 16})
    item_index = next(index for index, name in types.items() if name == "Octo.Data.Item")
    definition = definitions[item_index]
    offsets = image.read_pointer(registrations["field_offsets"] + item_index * 8)
    fields = []
    for relative, index in enumerate(range(definition[8], definition[8] + definition[18])):
        row = struct.unpack_from("<3I", metadata, header[24] + index * 12)
        offset = struct.unpack_from("<i", native, image.file_offset(offsets + relative * 4))[0]
        native_type = image.read_pointer(registrations["types"] + row[1] * 8)
        attributes = struct.unpack_from("<I", native, image.file_offset(native_type) + 8)[0] & 0xFFFF
        fields.append({"name": image.string(row[0]), "offset": offset,
                       "type": type_name(row[1]), "static": bool(attributes & 0x10)})
    setup = next(row for row in methods if row["name"] == "Octo.OctoManager.Setup")
    need(setup["static"] and setup["parameters"][0]["type"] == "Octo.OctoFullSettings",
         "Setup no longer accepts static full settings")
    return {"schema": 1, "platform": platform, "status": "PASS_PINNED_NATIVE_CONTRACTS",
        "native_sha256": PINS[platform]["native"], "metadata_sha256": PINS[platform]["metadata"],
        "methods": methods, "item_fields": fields, "actual_gameplay_executed": False,
        "physical_device_verified": False,
        "caching_type": {"UnityDefault": 0, "OctoAutoDelete": 1, "OctoFullCache": 2},
        "cache_state": {"None": 0, "Old": 1, "OldLocked": 2, "Latest": 3}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=tuple(PINS), required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hermetic-proof", action="store_true")
    args = parser.parse_args()
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3,) * 2)
    need(256 <= args.metadata.stat().st_size <= 64 * 1024**2, "Metadata size exceeds bounds")
    need(1 <= args.native.stat().st_size <= 256 * 1024**2, "Native size exceeds bounds")
    metadata, native = args.metadata.read_bytes(), args.native.read_bytes()
    report = extract_contracts(args.platform, metadata, native)
    if args.hermetic_proof:
        if args.platform == "android":
            from prove_android_resource_cache import prove_original_code
        else:
            from prove_ios_resource_cache import prove_original_code
        report["hermetic_proof"] = prove_original_code(native)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "platform": args.platform,
                      "methods": len(report["methods"])}))


if __name__ == "__main__":
    main()
