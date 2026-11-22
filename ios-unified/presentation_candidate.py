"""Rebuild an integrated Unity image from the pinned stock executable.

The translated base IPA supplies its existing UI, SDKs and static resources.
Its old presentation executable and bridge are never reused by this path.
Every executable change is reproduced from the current, version-locked
bootstrap and presentation plans before a candidate is packaged.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from zipfile import ZipFile

from packaging_common import CHUNK, audit_macho, regular, require, sha_file, stamp
from patch_load import MAX_HEADER, patched_header

ROOT = Path(__file__).resolve().parents[1]
UNITY = "Payload/IDOLY PRIDE.app/Frameworks/UnityFramework.framework/UnityFramework"
MAX_UNITY = 256 * 1024**2
MAX_LIBRARY = 8 * 1024**2
MAX_RECEIPT = 256 * 1024
SHARED_HOOKS = frozenset(("shared_setup", "shared_is_cached", "shared_file_path",
                         "shared_pre_download", "shared_downloader_update"))
MP4_HOOKS = frozenset(("mp4_presenter_update", "mp4_capture_pass", "mp4_end_camera",
                      "mp4_graph_mode", "mp4_brain_delta", "mp4_core_camera", "mp4_player_initialize",
                      "mp4_photography_initialize", "mp4_photography_player_initialize", "mp4_photography_end"))
NEW_BASE_HOOKS = SHARED_HOOKS | MP4_HOOKS


def _json(path, maximum):
    before = regular(path)
    require(0 < before.st_size <= maximum, "Presentation metadata exceeds bound")
    raw = Path(path).read_bytes()
    require(stamp(before) == stamp(regular(path)), "Presentation metadata changed")
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "Duplicate presentation metadata key")
            value[key] = item
        return value
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite presentation metadata")))
    require(type(value) is dict, "Presentation metadata must be an object")
    return value


def load_plan(path):
    from idoly_local.ios_presentation import validate_plan
    plan = _json(path, MAX_RECEIPT)
    validate_plan(plan)
    return plan


def validate_library(library, plan, *, source_root=ROOT):
    """Require this build's bridge, matching plan and checked source receipt."""
    library = Path(library)
    require(0 < regular(library).st_size <= MAX_LIBRARY, "Presentation library exceeds bound")
    receipt = _json(library.with_suffix(".build.json"), MAX_RECEIPT)
    digest = sha_file(library, MAX_LIBRARY)
    require(type(receipt.get("schema")) is int and receipt["schema"] == 1
            and receipt.get("target") == "arm64-apple-ios13.0"
            and type(receipt.get("bytes")) is int and receipt["bytes"] == regular(library).st_size
            and receipt.get("sha256") == digest
            and receipt.get("profile_header_sha256") == plan["profile_header_sha256"],
            "Fresh presentation library receipt differs")
    sources = receipt.get("source_sha256")
    mandatory = {"client-presentation/native/bridge.cpp",
                 "client-presentation/native/shared_cache_core.hpp",
                 "client-presentation/native/shared_cache_hooks.hpp",
                 "client-presentation/ios/static_install.hpp",
                 "client-presentation/ios/build_native.py"}
    require(type(sources) is dict and mandatory <= sources.keys() and len(sources) <= 128,
            "Fresh presentation source closure is incomplete")
    source_root = Path(source_root).resolve()
    for name, wanted in sources.items():
        require(type(name) is str and name.startswith("client-presentation/")
                and "\\" not in name and "\0" not in name
                and not name.startswith("/") and ".." not in Path(name).parts
                and type(wanted) is str and re.fullmatch("[0-9a-f]{64}", wanted),
                "Presentation source receipt path differs")
        path = source_root / name
        # The generated bridge translation unit contains the finite native
        # adapters; every other checked source retains its existing limit.
        maximum = (4 * 1024**2 if name == "client-presentation/native/bridge.cpp"
                   else 2 * 1024**2)
        require(path.resolve().is_relative_to(source_root)
                and sha_file(path, maximum) == wanted,
                "Presentation sources changed after native compilation")
    image = audit_macho(library, "device", require_signature=True, maximum=MAX_LIBRARY)
    require(len(image["slices"]) == 1
            and image["slices"][0]["install_name"] == "@rpath/IdolyPresentation.dylib",
            "Presentation library identity differs")
    return {"bytes": regular(library).st_size, "sha256": digest,
            "build_receipt_sha256": sha_file(library.with_suffix(".build.json"), MAX_RECEIPT),
            "profile_header_sha256": plan["profile_header_sha256"],
            "source_sha256": dict(sources), "fresh_source_build": True}


def build_unity(stock_ipa, plan):
    """Return one owned image after exact stock/bootstrap/gateway validation."""
    from idoly_local.ios_patch import _add_presentation_load
    from idoly_local.ios_presentation import IPA_SHA256, SOURCE_SHA256, patch_presentation
    from idoly_local.native_bootstrap import patch_native
    stock_ipa = Path(stock_ipa)
    require(sha_file(stock_ipa, 256 * 1024**2) == IPA_SHA256, "Stock iOS IPA fingerprint differs")
    before = regular(stock_ipa)
    with ZipFile(stock_ipa) as archive:
        require(archive.namelist().count(UNITY) == 1, "Stock Unity member is missing or duplicated")
        info = archive.getinfo(UNITY)
        require(0 < info.file_size <= MAX_UNITY and not info.flag_bits & 1, "Stock Unity member exceeds bound")
        with archive.open(info) as incoming:
            original = incoming.read(MAX_UNITY + 1)
        require(len(original) == info.file_size and hashlib.sha256(original).hexdigest() == SOURCE_SHA256,
                "Stock Unity bytes differ")
    require(stamp(before) == stamp(regular(stock_ipa)), "Stock iOS input changed")
    native, bootstrap = patch_native(original, "ios", mutable_output=True)
    del original
    native, presentation = patch_presentation(native, plan, bootstrap_report=bootstrap, in_place=True)
    native, presentation_load = _add_presentation_load(native, in_place=True)
    header, server_load = patched_header(bytes(native[:MAX_HEADER]), len(native))
    native[:len(header)] = header
    proof = {"schema": 1, "stock_ipa_sha256": IPA_SHA256,
             "stock_unity_sha256": SOURCE_SHA256,
             "output_unity_sha256": hashlib.sha256(native).hexdigest(),
             "output_bytes": len(native), "bootstrap": bootstrap,
             "presentation": presentation, "presentation_load": presentation_load,
             "server_load": server_load, "original_file_layout_preserved": True,
             "actual_device_or_PlayCover_execution": False}
    return native, proof


def compose(stock_ipa, plan_path, output):
    output = Path(output)
    proof_path = output.with_suffix(".json")
    require(not os.path.lexists(output) and not os.path.lexists(proof_path), "Fresh Unity output required")
    plan = load_plan(plan_path)
    native, proof = build_unity(stock_ipa, plan)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fresh-unity-", dir=output.parent) as folder:
        staged = Path(folder) / "UnityFramework"
        with staged.open("xb") as outgoing:
            for at in range(0, len(native), CHUNK):
                block = memoryview(native)[at:at + CHUNK]
                require(outgoing.write(block) == len(block), "Short fresh Unity write")
        require(sha_file(staged, MAX_UNITY) == proof["output_unity_sha256"], "Fresh Unity readback differs")
        # Refuse a concurrently published destination without deleting it.
        os.link(staged, output)
    with proof_path.open("x") as receipt:
        receipt.write(json.dumps(proof, indent=2) + "\n")
    return proof


def verify(stock_ipa, patched_unity, plan_path, library):
    """Reproduce every executable byte instead of trusting a supplied proof."""
    plan = load_plan(plan_path)
    bridge = validate_library(library, plan)
    expected, proof = build_unity(stock_ipa, plan)
    require(regular(patched_unity).st_size == len(expected), "Fresh Unity size differs")
    before = regular(patched_unity)
    with Path(patched_unity).open("rb") as incoming:
        for at in range(0, len(expected), CHUNK):
            require(incoming.read(min(CHUNK, len(expected) - at)) == expected[at:at + CHUNK],
                    "Fresh Unity differs from reproduced stock patch")
        require(incoming.read(1) == b"", "Fresh Unity has trailing bytes")
    require(stamp(before) == stamp(regular(patched_unity)), "Fresh Unity changed during verification")
    return {"original_sha256": proof["stock_unity_sha256"],
            "patched_sha256": proof["output_unity_sha256"], "bytes": proof["output_bytes"],
            "load_path": "@rpath/IdolyEmbeddedServer.framework/IdolyEmbeddedServer",
            "code_moved": False, "all_other_Unity_bytes_equal": True,
            "verification": "reproduced_stock_bootstrap_and_current_presentation",
            "stock_patch": proof, "presentation_library": bridge}


def verify_base_delta(incoming, patched_unity, original_sha256, plan_path):
    """Keep every previous base patch, permitting fifteen named new hook sites.

    This is independent of the stock reconstruction: old presentation hooks,
    bootstrap instructions and all other executable bytes must still equal the
    translated 41-hook base image. Five shared-resource and ten MV-export
    entries must have their original prefixes; their gateways must occupy old
    zero padding. Existing entry points and gateways receive no exception.
    """
    plan = load_plan(plan_path)
    require(NEW_BASE_HOOKS <= plan["entries"].keys(), "Declared additional hook plan is incomplete")
    size = regular(patched_unity).st_size
    old_header = incoming.read(min(MAX_HEADER, size))
    header, load = patched_header(old_header, size)
    writes = [(0, header)]
    checks = []
    for name in sorted(NEW_BASE_HOOKS):
        row = plan["entries"][name]
        entry, gateway = bytes.fromhex(row["patched_entry"]), bytes.fromhex(row["gateway_hex"])
        original = bytes.fromhex(row["original16"])
        require(len(entry) == 4 and len(gateway) in (28,32) and len(original) == 16,
                "Declared static gateway extent differs")
        writes.extend(((row["rva"],entry),(row["gateway"],gateway)))
        checks.extend(((row["rva"],original),
                       (row["gateway"],bytes(len(gateway)))))
    writes.sort()
    require(all(0 <= offset <= size-len(raw) for offset,raw in writes)
            and all(a+len(raw) <= b for (a,raw),(b,_) in zip(writes,writes[1:])),
            "Shared static changes overlap or exceed the original image")
    old_hash, new_hash = hashlib.sha256(), hashlib.sha256()
    offset = 0
    with Path(patched_unity).open("rb") as replacement:
        def compare(block):
            nonlocal offset
            old_hash.update(block)
            expected = bytearray(block)
            for at,raw in checks:
                lo,hi = max(at,offset),min(at+len(raw),offset+len(block))
                if hi > lo:
                    require(block[lo-offset:hi-offset] == raw[lo-at:hi-at],
                            "Existing base shared-cache prefix or zero gateway differs")
            for at,raw in writes:
                lo,hi=max(at,offset),min(at+len(raw),offset+len(block))
                if hi > lo:expected[lo-offset:hi-offset]=raw[lo-at:hi-at]
            require(replacement.read(len(expected)) == expected,
                    "Fresh Unity changed a prior bootstrap, presentation or SDK byte")
            new_hash.update(expected)
            offset += len(block)
        compare(old_header)
        while block := incoming.read(CHUNK):compare(block)
        require(offset == size and replacement.read(1) == b"" and old_hash.hexdigest() == original_sha256,
                "Pinned previous base Unity SHA or size differs")
    return {"schema":1,"base_unity_sha256":old_hash.hexdigest(),
            "output_unity_sha256":new_hash.hexdigest(),"new_shared_hooks":sorted(SHARED_HOOKS),
            "new_mp4_hooks":sorted(MP4_HOOKS),"new_hook_count":len(NEW_BASE_HOOKS),"server_load":load,
            "previous_bootstrap_and_presentation_bytes_preserved":True}
