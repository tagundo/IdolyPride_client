"""Version-locked, offline iOS presentation gateways. Never patches a process."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tempfile
from zipfile import ZipFile

PROFILE = Path(__file__).resolve().parents[2] / "client-presentation/ios/profile.json"
PROFILE_SHA256 = "dc69bd4d7129346f7e7ae8427a0e42120909db60adc407cf5ac2606436fef427"
PROFILE_ENTRY_COUNT = 244
PROFILE_HOOK_COUNT = 169
SOURCE_SHA256 = "b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf"
BOOTSTRAP_SHA256 = "2e61bc5754d9b934c1264e294ee2689c9ae9c016d0c197e374882db6f1c529ce"
IPA_SHA256 = "33197938a0990b267af2d67c09e9d1123694e28695fc39d9650ca4f6aa661848"
METADATA_SHA256 = "d11a50fd75d1e6744ae10f2a6e7081ea87bcca267a42ba0a72fe497057cd2bda"
UNITY = "Payload/IDOLY PRIDE.app/Frameworks/UnityFramework.framework/UnityFramework"
METADATA = "Payload/IDOLY PRIDE.app/Data/Managed/Metadata/global-metadata.dat"


def _object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate presentation JSON key")
        result[name] = value
    return result


def load_profile():
    raw = PROFILE.read_bytes()
    if len(raw) > 256 * 1024 or hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError("The original iOS presentation profile differs")
    return json.loads(raw, object_pairs_hook=_object)


def branch(source, target):
    if type(source) is not int or type(target) is not int:
        raise ValueError("ARM64 branch addresses must be integers")
    delta = target - source
    if delta % 4 or not -(1 << 27) <= delta < (1 << 27):
        raise ValueError("ARM64 presentation branch is out of range")
    return 0x14000000 | ((delta // 4) & 0x3FFFFFF)


def _displaced_allowed(word):
    # Audited first instructions: load/store pair, immediate stack arithmetic,
    # or an unsigned-offset field load/store. PC-relative instructions, literal
    # loads and pre-existing x16/x17 inputs are rejected, except compare-and-
    # branch, which uses two explicit original-address continuations.
    if (word & 0x7E000000) == 0x34000000:
        return (word & 31) not in (16, 17)
    base = (word >> 5) & 31
    if base in (16, 17):
        return False
    return ((word & 0x3B000000) in (0x29000000, 0x39000000)
            or (word & 0x1F000000) == 0x11000000)


def gateway(cave, slot, target, displaced, *, return_target=None):
    if cave % 4 or slot % 8 or len(displaced) != 4:
        raise ValueError("Presentation gateway alignment differs")
    word = int.from_bytes(displaced, "little")
    if not _displaced_allowed(word):
        raise ValueError("Unsupported displaced iOS instruction")
    page = (slot >> 12) - (cave >> 12)
    if not -(1 << 20) <= page < (1 << 20):
        raise ValueError("Presentation data pointer is outside ADRP range")
    words = [0x90000010 | ((page & 3) << 29) | (((page >> 2) & 0x7FFFF) << 5),
             0x91000210 | ((slot & 0xFFF) << 10), 0xC8DFFE10, 0xB4000050, 0xD61F0200]
    if (word & 0x7E000000) == 0x34000000:
        if return_target is not None:
            raise ValueError("Conditional gateway cannot use a return relay")
        immediate = (word >> 5) & 0x7FFFF
        if immediate & (1 << 18):
            immediate -= 1 << 19
        words += [(word & ~(0x7FFFF << 5)) | (2 << 5),
                  branch(cave + 24, target + 4),
                  branch(cave + 28, target + immediate * 4)]
    else:
        words += [word, branch(cave + 24, target + 4 if return_target is None else return_target)]
    return struct.pack("<" + str(len(words)) + "I", *words)


def render_header(plan, profile=None):
    profile = load_profile() if profile is None else profile
    uuid = profile["target"]["uuid"]
    lines = ["// Generated from pinned ORIGINAL iOS6.1.1 build156; do not use Android RVAs.",
             "#pragma once", "", "namespace idoly::presentation::profile {",
             "struct Entry { const char *name; uintptr_t rva; unsigned char bytes[16]; uintptr_t gateway; uintptr_t slot; uintptr_t relay_in=0, relay_out=0; };",
             "inline constexpr unsigned char uuid[16] = {"
             + ", ".join("0x" + uuid[i:i + 2] for i in range(0, 32, 2)) + "};", ""]
    for name, row in profile["aliases"].items():
        hook = plan["entries"].get(name, {})
        relay = (", " + hex(hook["relay_in"]) + "u, " + hex(hook["relay_out"]) + "u"
                 if "relay_in" in hook else "")
        lines.append("inline constexpr Entry " + name + "{" + json.dumps(row["name"])
                     + ", " + hex(row["rva"]) + "u, {"
                     + ", ".join("0x" + row["prefix16"][i:i + 2] for i in range(0, 32, 2))
                     + "}, " + hex(hook.get("gateway", 0)) + "u, "
                     + hex(hook.get("slot", 0)) + "u" + relay + "};")
    lines += ["", "inline constexpr Entry all[] = {",
              *("    " + name + "," for name in profile["aliases"]),
              "};", "} // namespace idoly::presentation::profile", ""]
    return "\n".join(lines).encode("utf-8")


def _profile_native_relays(profile):
    primary = profile.get("native_relay_region")
    extra = profile.get("native_extra_relay_regions", [])
    if primary is None:
        if extra:
            raise ValueError("Extra native relays require the original clock relay")
        return []
    approved_extra = ("mp4_fixed_loop_condition", "mp4_capture_native_publication",
                      "mp4_animation_output_target", "mp4_animation_output_create",
                      "mp4_audio_canonical_target", "mp4_audio_source_process_target",
                      "mp4_director_enqueue",
                      "mp4_director_append_a",
                      "mp4_director_append_b",
                      "mp4_director_collect",
                      "mp4_director_deferred_a",
                      "mp4_director_deferred_b",
                      "mp4_director_graph_create",
                      "mp4_animation_binding_build")
    if (type(primary) is not dict or primary.get("name") != "mp4_native_time"
            or type(extra) is not list or len(extra) > len(approved_extra)):
        raise ValueError("Native relay identities differ")
    result = [primary, *extra]
    if any(type(item) is not dict or item.get("name") != approved_extra[index]
           for index, item in enumerate(extra)):
        raise ValueError("Approved native relay identity differs")
    fields = {"name", "rva", "bytes", "original_zero", "gap_begin", "gap_end", "after_section", "before_section"}
    for item in result:
        if set(item) != fields or any(type(item.get(key)) is not int for key in ("rva", "bytes", "gap_begin", "gap_end")):
            raise ValueError("Native relay schema differs")
    for index, item in enumerate(result):
        if (item["rva"] != primary["rva"] + 8 * index
                or any(item[key] != primary[key] for key in ("gap_begin", "gap_end", "after_section", "before_section"))):
            raise ValueError("Native relay gap layout differs")
    spans = sorted((item["rva"], item["rva"] + item["bytes"]) for item in result)
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
        raise ValueError("Native relays overlap")
    return result


def make_plan():
    profile = load_profile()
    target = profile["target"]
    if (target["unity_sha256"] != SOURCE_SHA256
            or target["bootstrap_unity_sha256"] != BOOTSTRAP_SHA256
            or len(profile["aliases"]) != PROFILE_ENTRY_COUNT
            or len(profile["hook_names"]) != PROFILE_HOOK_COUNT):
        raise ValueError("Original iOS presentation target differs")
    text, data = profile["segments"]["__TEXT"], profile["segments"]["__DATA"]
    cave, slot = profile["gateway_region"]["rva"], profile["slot_region"]["rva"]
    if (profile["gateway_region"]["bytes"] != 32 * PROFILE_HOOK_COUNT
            or profile["slot_region"]["bytes"] != 8 * PROFILE_HOOK_COUNT
            or cave < text["section_end"] or cave + 32 * PROFILE_HOOK_COUNT > text["rva"] + text["filesize"]
            or slot < data["section_end"] or slot < data["rva"] + data["filesize"]
            or slot + 8 * PROFILE_HOOK_COUNT > data["rva"] + data["vmsize"]):
        raise ValueError("Gateway would overlap original code or data sections")
    relays = _profile_native_relays(profile)
    relay_by_name = {item["name"]: item for item in relays}
    for relay in relays:
        native = profile["aliases"][relay["name"]]
        if (relay["bytes"] != 8 or relay["original_zero"] is not True
                or native["relay_in"] != relay["rva"] or native["relay_out"] != relay["rva"] + 4
                or relay["rva"] % 4 or relay["rva"] < relay["gap_begin"]
                or relay["rva"] + 8 > relay["gap_end"]
                or relay["gap_end"] > text["rva"] + text["filesize"]
                or relay["rva"] + 8 > cave):
            raise ValueError("Native gateway relay extent differs")
    plan = {"schema": 1, "target": "ios-arm64-6.1.1-156", "source_unity_sha256": SOURCE_SHA256,
            "bootstrap_unity_sha256": BOOTSTRAP_SHA256, "metadata_sha256": METADATA_SHA256,
            "uuid": target["uuid"], "profile_sha256": PROFILE_SHA256,
            "hook_names": profile["hook_names"], "entries": {}}
    for i, name in enumerate(profile["hook_names"]):
        row = profile["aliases"][name]
        c, s = cave + 32 * i, slot + 8 * i
        displaced = bytes.fromhex(row["prefix16"][:8])
        relay_in, relay_out = row.get("relay_in"), row.get("relay_out")
        if (relay_in is None) != (relay_out is None) or ((relay_in is not None) != (name in relay_by_name)):
            raise ValueError("Native gateway relay identity differs")
        code = gateway(c, s, row["rva"], displaced, return_target=relay_out)
        plan["entries"][name] = {"rva": row["rva"], "original16": row["prefix16"],
                                  "gateway": c, "slot": s, "original_callable": c + 20,
                                  "patched_entry": struct.pack("<I", branch(row["rva"], c if relay_in is None else relay_in)).hex(),
                                  "gateway_hex": code.hex(),
                                  "registration_pointer_slot": row["registration_pointer_slot_rva"]}
        if relay_in is not None:
            plan["entries"][name].update(relay_in=relay_in, relay_out=relay_out,
                relay_in_hex=struct.pack("<I", branch(relay_in, c)).hex(),
                relay_out_hex=struct.pack("<I", branch(relay_out, row["rva"] + 4)).hex())
    plan["profile_header_sha256"] = hashlib.sha256(render_header(plan, profile)).hexdigest()
    return plan


def _validate_native_relay(native, profile):
    """Verify the relay is in original RX TEXT alignment slack, never a section."""
    relays = _profile_native_relays(profile)
    if not relays:
        return  # Small synthetic ownership fixtures have no Mach-O relay.
    if len(native) < 32 or struct.unpack_from("<II", native) != (0xFEEDFACF, 0x0100000C):
        raise ValueError("Original iOS Mach-O header differs")
    count, size = struct.unpack_from("<II", native, 16)
    if not 0 < count <= 128 or not 8 <= size <= 65536 or 32 + size > len(native):
        raise ValueError("Original iOS Mach-O commands differ")
    cursor, uuid, sections, text = 32, None, {}, None
    for _ in range(count):
        if cursor + 8 > 32 + size:
            raise ValueError("Original iOS Mach-O command bounds differ")
        command, length = struct.unpack_from("<II", native, cursor)
        if length < 8 or cursor + length > 32 + size:
            raise ValueError("Original iOS Mach-O command bounds differ")
        if command == 0x1B:
            if length != 24 or uuid is not None:
                raise ValueError("Original iOS Mach-O UUID differs")
            uuid = bytes(native[cursor + 8:cursor + 24]).hex()
        if command == 0x19 and length >= 72:
            name = bytes(native[cursor + 8:cursor + 24]).rstrip(b"\0")
            va, span, fileoff, filesize = struct.unpack_from("<4Q", native, cursor + 24)
            protection, nsects = struct.unpack_from("<II", native, cursor + 60)
            if nsects > 128 or 72 + nsects * 80 > length:
                raise ValueError("Original iOS Mach-O section bounds differ")
            if name == b"__TEXT":
                if text is not None or va != 0 or fileoff != 0 or protection & 5 != 5:
                    raise ValueError("Original iOS executable TEXT mapping differs")
                text = (span, filesize)
                for index in range(nsects):
                    at = cursor + 72 + 80 * index
                    section = bytes(native[at:at + 16]).rstrip(b"\0").decode("ascii")
                    start, extent = struct.unpack_from("<QQ", native, at + 32)
                    if section in sections or start > span or extent > span - start:
                        raise ValueError("Original iOS TEXT section extent differs")
                    sections[section] = (start, start + extent)
        cursor += length
    if cursor != 32 + size or uuid != profile["target"]["uuid"] or text is None:
        raise ValueError("Original iOS native relay image differs")
    for relay in relays:
        start, end = relay["rva"], relay["rva"] + relay["bytes"]
        if (end > min(text) or end > len(native)
                or sections.get(relay["after_section"], (None, None))[1] != relay["gap_begin"]
                or sections.get(relay["before_section"], (None, None))[0] != relay["gap_end"]
                or any(start < hi and lo < end for lo, hi in sections.values())
                or any(native[start:end])):
            raise ValueError("Original iOS native relay mapping or zero slack differs")



def validate_plan(plan):
    if not isinstance(plan, dict) or type(plan.get("schema")) is not int:
        raise ValueError("Presentation plan must be an explicit schema object")
    actual = dict(plan)
    library_hash = actual.pop("library_sha256", None)
    if library_hash is not None and (not isinstance(library_hash, str)
                                    or not re.fullmatch(r"[0-9a-f]{64}", library_hash)):
        raise ValueError("Presentation native fingerprint is malformed")
    if actual != make_plan():
        raise ValueError("Presentation plan differs from the pinned original iOS profile")


def patch_presentation(native, plan, *, bootstrap_report=None, in_place=False):
    """Patch only locked render entry points and verified zero executable slack.

    The loader command and exact compiled dylib embedding are the IPA packager's
    responsibility. Mutable pointers live after all declared DATA sections in
    the existing zero-fill tail; no existing BSS object or segment is extended.
    in_place=True requires an exclusively caller-owned bytearray and returns
    that same object. Every validation and small write payload is completed
    before mutation, so rejected inputs leave the supplied buffer unchanged.
    """
    if type(in_place) is not bool:
        raise ValueError("Presentation in_place must be a boolean")
    if in_place and type(native) is not bytearray:
        raise ValueError("In-place presentation requires an owned bytearray")
    validate_plan(plan)
    input_hash = hashlib.sha256(native).hexdigest()
    if input_hash not in (SOURCE_SHA256, BOOTSTRAP_SHA256):
        raise ValueError("Presentation requires the original or exact local-bootstrap UnityFramework")
    if bootstrap_report is not None and (
            input_hash != BOOTSTRAP_SHA256 or bootstrap_report.get("platform") != "ios"
            or bootstrap_report.get("input_sha256") != SOURCE_SHA256
            or bootstrap_report.get("output_sha256") != BOOTSTRAP_SHA256):
        raise ValueError("Presentation bootstrap composition differs")
    profile = load_profile()
    _validate_native_relay(native, profile)
    for row in profile["aliases"].values():
        if native[row["rva"]:row["rva"] + 16].hex() != row["prefix16"]:
            raise ValueError("Original iOS function prefix differs")
        pointer = row.get("registration_pointer_slot_rva")
        if pointer is not None and struct.unpack_from("<Q", native, pointer)[0] != row["rva"]:
            raise ValueError("Original iOS registration pointer differs")
    region = profile["gateway_region"]
    if any(native[region["rva"]:region["rva"] + region["bytes"]]):
        raise ValueError("Original executable slack is not zero")
    changes = []
    for row in plan["entries"].values():
        entry = bytes.fromhex(row["patched_entry"])
        code = bytes.fromhex(row["gateway_hex"])
        if (len(entry) != 4 or not 0 <= row["rva"] <= len(native) - len(entry)
                or not 0 <= row["gateway"] <= len(native) - len(code)):
            raise ValueError("Presentation write exceeds the validated native buffer")
        changes.extend(((row["rva"], entry), (row["gateway"], code)))
        if "relay_in" in row:
            for key in ("relay_in", "relay_out"):
                payload = bytes.fromhex(row[key + "_hex"])
                if len(payload) != 4 or not 0 <= row[key] <= len(native) - 4:
                    raise ValueError("Presentation relay exceeds the validated native buffer")
                changes.append((row[key], payload))
    output = native if in_place else bytearray(native)
    for offset, payload in changes:
        output[offset:offset + len(payload)] = payload
    result = output if in_place else bytes(output)
    return result, {"schema": 1, "platform": "ios", "input_sha256": input_hash,
                    "output_sha256": hashlib.sha256(result).hexdigest(),
                    "profile_sha256": PROFILE_SHA256,
                    "profile_header_sha256": plan["profile_header_sha256"],
                    "hook_count": PROFILE_HOOK_COUNT, "call_entry_count": PROFILE_ENTRY_COUNT,
                    "runtime_executable_memory_writes": False,
                    "existing_section_layout_or_bss_modified": False,
                    "runtime_verified": False}


def prepare_presentation(source, plan_output, header_output):
    """Reproduce the plan/header after bounded streaming reads of the original IPA."""
    source, plan_output, header_output = map(Path, (source, plan_output, header_output))
    if (os.path.lexists(plan_output) or os.path.lexists(header_output)
            or plan_output.resolve() == header_output.resolve()
            or header_output.name != "ios_profile.hpp"):
        raise ValueError("Choose unused plan and ios_profile.hpp paths")
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != IPA_SHA256:
            raise ValueError("Original decrypted IPA fingerprint differs")
    profile, plan = load_profile(), make_plan()
    regions = [(r["rva"], r["rva"] + 16, bytes.fromhex(r["prefix16"]))
               for r in profile["aliases"].values()]
    cave = profile["gateway_region"]
    regions.append((cave["rva"], cave["rva"] + cave["bytes"], b"\0" * cave["bytes"]))
    for relay in _profile_native_relays(profile):
        regions.append((relay["rva"], relay["rva"] + relay["bytes"], b"\0" * relay["bytes"]))
    seen = [bytearray(end - start) for start, end, _ in regions]
    with ZipFile(source) as archive:
        with archive.open(UNITY) as stream:
            digest, offset = hashlib.sha256(), 0
            while block := stream.read(262144):
                digest.update(block)
                for i, (start, end, _) in enumerate(regions):
                    lo, hi = max(offset, start), min(offset + len(block), end)
                    if hi > lo:
                        seen[i][lo - start:hi - start] = block[lo - offset:hi - offset]
                offset += len(block)
        if digest.hexdigest() != SOURCE_SHA256 or any(bytes(value) != row[2] for value, row in zip(seen, regions)):
            raise ValueError("Original iOS render prefixes/slack differ")
        with archive.open(METADATA) as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != METADATA_SHA256:
                raise ValueError("Original iOS metadata differs")
    plan_output.parent.mkdir(parents=True, exist_ok=True)
    header_output.parent.mkdir(parents=True, exist_ok=True)
    # Publish only small derived metadata, never the proprietary executable.
    # Hard links preserve any concurrently created destination, including links.
    with tempfile.TemporaryDirectory(prefix=".ios-plan-", dir=plan_output.parent) as work:
        staged_plan, staged_header = Path(work) / "plan.json", Path(work) / "header.hpp"
        staged_plan.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        staged_header.write_bytes(render_header(plan, profile))
        if plan_output.parent.stat().st_dev != header_output.parent.stat().st_dev:
            raise ValueError("Presentation plan and header must share a filesystem")
        identity = (staged_plan.stat().st_dev, staged_plan.stat().st_ino)
        os.link(staged_plan, plan_output)
        try:
            os.link(staged_header, header_output)
        except BaseException:
            if (plan_output.stat().st_dev, plan_output.stat().st_ino) == identity:
                plan_output.unlink()
            raise
    return plan
