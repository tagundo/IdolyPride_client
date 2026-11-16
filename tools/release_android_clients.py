#!/usr/bin/env python3
"""Build fixed Korean/Japanese/English game APKs on an owned remote Actions runner.

The pinned diagnostic base is an immutable donor, not a fresh-source claim.
Current presentation native/Java and the complete audited full-client writer
are rebuilt. All three languages keep the existing update identity and certificate.
No device, account, private key outside this checkout or installed app is read.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("ko", "ja", "en")
PACKAGE = "game.qualiarts.idolypride.local.diagnostics"
VERSION_CODE = 414
CERTIFICATE = "aa4e9346ff9e542b263b70254df3e25b79211df16161208a3b509c4f113facfc"
REPORT_NAME = "android-clients-report.json"
FONT_PUBLIC_COMMIT = "5c41199ea0024a9e0b2cb31735265056e5472d76"
FONT_GIT_BLOB = "ab20ba021ecb09802976a8dcee3eaa4219bf55f7"
CLIENT_NAMES = {lang: "IdolyPride-Local-Graphics-Diagnostic-Android-arm64-" + lang + ".apk"
                for lang in LANGUAGES}
INPUTS = {
    "korean_donor": {"bytes": 165128829, "sha256": "44f233290128a97f78940e3167c9486dbe39550090efcb90f7dc403430e94b9e"},
    "diagnostic_base": {"bytes": 159549324, "sha256": "f5be0c0e19c2a17ea28ffa0c3205a49f5ab004f013e2e67e319aa192ca1995df"},
    "apkeditor": {"bytes": 7126009, "sha256": "4a98ae6a755264357603f1906b92e62e757d59229014e33395f4e03ff019fda8"},
    "font": {"bytes": 3781740, "sha256": "7cd2b757bd8b8db79b4b87c3b402aa62aca666b55ff50ae0799e14ece1942314"},
    "english_ui": {"bytes": 227781, "sha256": "b30f48cdcbc0ddfc267a0a7d265ec717a7057342bdc55c9f0d16fe3ea06fc702"},
    "english_ui_proof": {"bytes": 348, "sha256": "298138bcadd69249a4b064b1b96ada4c15e6da2c42327d1d97e27a2b6c69cb62"},
    "shadowhook": {"bytes": 461264, "sha256": "2cad01ff4d59542958775e19f281981a7e84b39670b5fae75905b8511e10c7cd"},
}
URLS = {
    "korean_donor": "https://github.com/tagundo/IdolyPride_client/releases/download/v2026.11.17.1/IdolyPride-2026.11.17.1-Client-Android-arm64-ko.apk",
    "diagnostic_base": "https://github.com/tagundo/IdolyPride_client/releases/download/local-diagnostics-v0.2.1/IdolyPride-Local-Diagnostic-Android-arm64.apk",
    "apkeditor": "https://github.com/REAndroid/APKEditor/releases/download/V1.4.1/APKEditor-1.4.1.jar",
    "font": "https://github.com/orioncactus/pretendard/raw/5c41199ea0024a9e0b2cb31735265056e5472d76/packages/pretendard-jp/dist/public/static/PretendardJP-SemiBold.otf",
    "shadowhook": "https://repo.maven.apache.org/maven2/com/bytedance/android/shadowhook/2.0.1/shadowhook-2.0.1.aar",
}
HOSTS = frozenset(("github.com", "raw.githubusercontent.com", "media.githubusercontent.com",
    "objects.githubusercontent.com", "release-assets.githubusercontent.com", "github-cloud.githubusercontent.com",
    "github-cloud.s3.amazonaws.com", "repo.maven.apache.org"))
CHUNK = 128 * 1024
UI_MEMBER = "assets/bin/Data/dc5a3280fad6542929a0daf3a3736d29"
JAPANESE_UI_SHA256 = "6c522891fb2ed310c9a6669871c76550e4d144e9aa538b5074b064ef7ecb020e"
VALIDATION_FLAGS = ("pinned_inputs_verified", "source_bound_native_and_feature_verified",
    "signature_v2_v3_verified", "zipalign_16384_verified", "same_update_identity_verified",
    "declared_member_inventory_verified", "local_resource_output_fields_verified",
    "built_in_ui_language_verified", "font_assets_verified", "original_inputs_unchanged")
REQUIRED_SOURCES = (
    "tools/release_android_clients.py", "tools/fetch_korean_ui_images.py",
    "client-presentation/images/korean-static-sprites-v1.json", "client-presentation/images/korean-static-sprites-v2.json",
    "client-presentation/images/korean-static-textures-v1.json", "client-presentation/build_addon.py",
    "client-presentation/build_full_client.py", "client-presentation/native/bridge.cpp",
    "client-presentation/native/profile.json", "src/idoly_local/ui_assets.py",
    "src/idoly_local/font_assets.py", "src/idoly_local/static_ui_assets.py",
    "src/idoly_local/ui_display_literals.py", "src/idoly_local/story_loading_prefab.py",
    "ios-unified/client-language-inputs/en.csv", "ios-unified/client-language-inputs/en-report.json")


PHASES = frozenset(("startup", "checkout", "directories", "input_diagnostic_base", "input_korean_donor", "input_apkeditor",
    "input_font", "input_shadowhook", "input_english_ui", "input_english_ui_proof", "sdk", "resources",
    "native", "native_ndk", "native_shadowhook", "native_sources", "native_resource",
    "native_compile", "native_strip", "native_readelf", "native_receipt",
    "feature", "language_ko", "language_ja", "language_en", "verification", "final"))
_PHASE = "startup"


def phase(name):
    global _PHASE
    need(name in PHASES, "unknown_build_phase")
    _PHASE = name


def failure_report(error):
    message = str(error)
    role = "none"
    if isinstance(error, FileNotFoundError):
        names = {"/sys/fs/cgroup/memory.max": "cgroup_memory_max",
                 "/sys/fs/cgroup/memory.current": "cgroup_memory_current",
                 "/sys/fs/cgroup/memory.events": "cgroup_memory_events",
                 "/proc/meminfo": "proc_meminfo"}
        role = names.get(error.filename, "unknown")
        if role == "unknown" and isinstance(error.filename, str) and Path(error.filename).name == "source.properties":
            role = "ndk_properties"
    return {"schema": 1, "status": "FAIL", "phase": _PHASE,
            "error_type": type(error).__name__, "file_role": role,
            "error_code": message if re.fullmatch(r"[a-z0-9_]{1,96}", message) else "unclassified"}


def need(value, code):
    if not value:
        raise ValueError(code)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), "regular_report_required")
    return {"bytes": path.stat().st_size, "sha256": sha(path)}


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


class HostedResourceGuard:
    """Explicit runner policy; the shared finite-cgroup local guard is unchanged.

    Only GitHub-hosted execution may use host MemAvailable when the root cgroup
    has no finite limit. Missing finite-budget files and malformed values fail.
    No process, cache, memory limit or system configuration is changed.
    """
    MIB = 1024**2

    def __init__(self, budget_reader, *, cgroup=Path("/sys/fs/cgroup"),
                 proc=Path("/proc"), disk_usage=None):
        need(os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted", "hosted_runner_required")
        self.budget_reader, self.cgroup, self.proc = budget_reader, Path(cgroup), Path(proc)
        self.disk_usage = shutil.disk_usage if disk_usage is None else disk_usage
        self.samples, self.minimum_headroom, self.minimum_disk = 0, None, None
        self.mode, self.oom_supported, self.oom_baseline = None, None, None
        self.entry = self.check(ROOT, entry=True)

    @staticmethod
    def _read(path):
        with path.open("r", encoding="ascii") as stream:
            raw = stream.read(65537)
        need(len(raw) <= 65536, "hosted_resource_metadata_bound")
        return raw

    def _budget(self):
        maximum = self.cgroup / "memory.max"
        if maximum.exists():
            raw = self._read(maximum).strip()
            need(raw == "max" or re.fullmatch(r"[0-9]+", raw) and int(raw) > 0,
                 "hosted_cgroup_max_malformed")
            mode = "memory_max_unlimited" if raw == "max" else "finite_cgroup"
        else:
            mode = "memory_max_absent"
        need(self.mode in (None, mode), "hosted_memory_policy_changed")
        self.mode = mode
        if mode == "finite_cgroup":
            budget = self.budget_reader()
            need(budget["memory_direct_headroom"] >= 768 * self.MIB
                 and budget["memory_effective_headroom"] >= 1024 * self.MIB,
                 "hosted_finite_cgroup_headroom_floor")
            return budget
        values = re.findall(r"^MemAvailable:[ \t]+([0-9]+)[ \t]+kB[ \t]*$",
                            self._read(self.proc / "meminfo"), re.M)
        need(len(values) == 1 and int(values[0]) <= (2**63 - 1) // 1024,
             "hosted_memavailable_malformed")
        available = int(values[0]) * 1024
        return {"memory_current": None, "memory_max": None,
                "memory_direct_headroom": available, "memory_clean_inactive_credit": 0,
                "memory_effective_headroom": available}

    def _oom(self):
        path = self.cgroup / "memory.events"
        supported = path.exists()
        need(self.oom_supported in (None, supported), "hosted_oom_counter_support_changed")
        self.oom_supported = supported
        if not supported:
            return None
        values = {}
        for line in self._read(path).splitlines():
            fields = line.split()
            need(len(fields) == 2 and fields[0] not in values
                 and re.fullmatch(r"[0-9]+", fields[1]), "hosted_oom_metadata_malformed")
            values[fields[0]] = int(fields[1])
        need("oom_kill" in values, "hosted_oom_counter_missing")
        value = values["oom_kill"]
        if self.oom_baseline is None:
            self.oom_baseline = value
        need(value == self.oom_baseline, "hosted_oom_baseline_changed")
        return value

    def check(self, root, *, entry=False):
        need(os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted", "hosted_runner_required")
        budget = self._budget()
        if self.mode != "finite_cgroup":
            need(budget["memory_direct_headroom"] >= (1024 if entry else 512) * self.MIB,
                 "hosted_memory_entry_floor" if entry else "hosted_memory_stage_floor")
        # Keep the shared guard's separate-build Java exclusion. Each callback
        # runs before a child is started or after that child has exited.
        for process in self.proc.iterdir():
            if not process.name.isdecimal():
                continue
            try:
                name = (process / "comm").read_text().strip()
                status = (process / "status").read_text()
            except OSError:
                continue
            need(name not in ("java", "javac") or re.search(r"^State:\s+Z\b", status, re.M),
                 "hosted_other_java_process_active")
        free = self.disk_usage(root).free
        need(free >= 150 * self.MIB, "hosted_disk_reserve_floor")
        oom = self._oom()
        snapshot = {**budget, "oom_kill": oom, "oom_counter_supported": self.oom_supported,
                    "memory_policy": self.mode, "entry": entry, "disk_free_bytes": free}
        self.samples += 1
        direct = budget["memory_direct_headroom"]
        self.minimum_headroom = direct if self.minimum_headroom is None else min(direct, self.minimum_headroom)
        self.minimum_disk = free if self.minimum_disk is None else min(free, self.minimum_disk)
        self.latest = snapshot
        return snapshot

    def __call__(self, root):
        return self.check(root)

    def report(self):
        return {"policy": "github_hosted_explicit", "entry": self.entry, "latest": self.latest,
                "samples": self.samples, "minimum_direct_headroom": self.minimum_headroom,
                "minimum_disk": self.minimum_disk, "oom_counter_supported": self.oom_supported,
                "oom_baseline": self.oom_baseline}


def runner_resource_guard(limits):
    return (HostedResourceGuard(limits._memory_budget)
            if os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted" else None)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def approved(url):
    parsed = urlsplit(url)
    need(parsed.scheme == "https" and parsed.hostname in HOSTS and parsed.port in (None, 443)
         and not parsed.username and not parsed.password, "unapproved_public_input_origin")
    return url


def download(url, pin, destination, guard):
    """Stream only one fixed public input, never forward repository credentials."""
    destination = Path(destination)
    need(not destination.exists() and not destination.is_symlink(), "fresh_input_required")
    opener, response = build_opener(NoRedirect()), None
    for _ in range(6):
        try:
            response = opener.open(Request(approved(url), headers={"Accept-Encoding": "identity"}), timeout=90)
            break
        except HTTPError as error:
            need(error.code in (301, 302, 303, 307, 308), "public_input_http_failure")
            url = approved(error.headers.get("Location", ""))
    need(response is not None, "public_input_redirect_bound")
    partial = destination.with_name(destination.name + ".partial")
    size, digest = 0, hashlib.sha256()
    with response, partial.open("xb") as output:
        while block := response.read(CHUNK):
            guard.check()
            size += len(block)
            need(size <= pin["bytes"], "public_input_size_bound")
            digest.update(block)
            output.write(block)
    need(size == pin["bytes"] and digest.hexdigest() == pin["sha256"], "public_input_digest_differs")
    partial.rename(destination)


def verify_input(path, pin):
    need(record(path) == pin, "pinned_input_differs")


def native_command(compiler, toolchain, shadow, output):
    return [compiler, "-std=c++17", "-O2", "-fPIC", "-fvisibility=hidden",
        "-fexceptions", "-fno-rtti", "-nostdlib++", "-ffunction-sections", "-fdata-sections",
        "-Wall", "-Wextra", "-Werror", "-shared", "-Wl,--gc-sections",
        "-Wl,--exclude-libs,ALL", "-Wl,--no-undefined", "-Wl,--threads=1",
        "-Wl,-z,max-page-size=16384", "-Wl,-z,common-page-size=16384",
        "-Wl,-soname,libidoly_presentation.so", "-I" + str(shadow / "include"),
        "-I" + str(ROOT / "client-presentation/native"), ROOT / "client-presentation/native/bridge.cpp",
        toolchain / "sysroot/usr/lib/aarch64-linux-android/libc++abi.a",
        "-L" + str(shadow / "lib"), "-lshadowhook", "-ldl", "-lm", "-o", output]


def prepare_native(args, addon, limits, guard, work, inputs, *, resource_guard=None):
    phase("native_ndk")
    ndk = Path(args.ndk).resolve(strict=True)
    properties = dict(line.split("=", 1) for line in (ndk / "source.properties").read_text().splitlines() if "=" in line)
    need(next((value.strip() for key, value in properties.items() if key.strip() == "Pkg.Revision"), None)
         == "26.3.11579264", "ndk_revision_differs")
    toolchain = ndk / "toolchains/llvm/prebuilt/linux-x86_64"
    tools = toolchain / "bin"
    phase("native_shadowhook")
    shadow = work / "shadowhook"
    shadow.mkdir()
    selected = {"prefab/modules/shadowhook/include/shadowhook.h": "include/shadowhook.h",
                "jni/arm64-v8a/libshadowhook.so": "lib/libshadowhook.so",
                "jni/arm64-v8a/libshadowhook_nothing.so": "lib/libshadowhook_nothing.so"}
    with ZipFile(inputs["shadowhook"]) as archive:
        need(len(archive.namelist()) == len(set(archive.namelist())), "duplicate_shadowhook_member")
        for name, relative in selected.items():
            info = archive.getinfo(name)
            need(not info.is_dir() and 0 < info.file_size <= 2 * 1024**2, "shadowhook_member_bound")
            path = shadow / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as incoming, path.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, CHUNK)
    for member, expected in addon.SHADOW_HASHES.items():
        need(sha(shadow / "lib" / Path(member).name) == expected, "shadowhook_native_digest_differs")
    out = work / "native"
    out.mkdir()
    library = out / "libidoly_presentation.so"
    phase("native_sources")
    sources = addon.frozen_sources(args.source_commit)
    phase("native_resource")
    check_resources = limits._resource_guard if resource_guard is None else resource_guard
    original = check_resources(ROOT)
    stages = []
    env = {key: value for key, value in os.environ.items()
           if key not in ("GH_TOKEN", "GITHUB_TOKEN", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH")}
    env["MALLOC_ARENA_MAX"] = "2"
    def run(name, command):
        phase("native_" + name)
        guard.check()
        before = check_resources(ROOT)
        result = limits._run(command, root=ROOT, env=env, timeout=120, guard=check_resources)
        after = check_resources(ROOT)
        need(before["oom_kill"] == after["oom_kill"] == original["oom_kill"], "native_oom_baseline_changed")
        stages.append({"name": name, "before": before, "after": after})
        return result.decode("utf-8")
    command = native_command(tools / "aarch64-linux-android28-clang++", toolchain, shadow, library)
    run("compile", command)
    run("strip", [tools / "llvm-strip", "--strip-unneeded", library])
    dynamic = run("readelf", [tools / "llvm-readelf", "-d", library])
    needed = re.findall(r"Shared library: \[([^\]]+)\]", dynamic)
    need(set(needed) == {"libshadowhook.so", "libdl.so", "libm.so", "libc.so"}, "native_dependencies_differ")
    phase("native_receipt")
    alignment, jni = addon.check_elf(library), addon.check_jni(library)
    need(addon.frozen_sources(args.source_commit) == sources, "native_source_changed")
    prefixes, hooks = addon.native_profile_counts()
    receipt = {"schema": 1, "source_commit": args.source_commit, **record(library),
        "source_sha256": {name: sources[name] for name in addon.native_source_paths()},
        "source_unchanged_during_build": True, "profile_prefix_count": prefixes,
        "profile_hook_count": hooks, "abi": "arm64-v8a", "minimum_api": 28,
        "segment_alignment": 16384, "dt_needed": needed, "load_segments": alignment,
        "exports": jni, "command": list(map(str, command)), "stages": stages,
        "runtime_device_tested": False}
    write_json(out / "build-receipt.json", receipt)
    addon.verified_native(library, args.source_commit, sources)
    return library, tools / "llvm-readelf"


def extract_korean_ui(donor, work):
    """Reuse only the exact shipped Korean text, then rebuild from stock data."""
    verify_input(donor, INPUTS["korean_donor"])
    import UnityPy
    from idoly_local.ui_assets import ORIGINAL_CSV_SHA256, MAX_CSV_BYTES, validate_csv
    with ZipFile(donor) as archive:
        need(len(archive.namelist()) == len(set(archive.namelist())), "duplicate_korean_donor_member")
        item = archive.getinfo(UI_MEMBER)
        need(0 < item.file_size <= MAX_CSV_BYTES, "korean_donor_ui_bound")
        prepared = archive.read(item)
    objects = list(UnityPy.load(prepared).objects)
    need(len(objects) == 1 and objects[0].type.name == "TextAsset" and objects[0].path_id == 1,
         "korean_donor_ui_object_differs")
    asset = objects[0].read()
    need(asset.m_Name == "af07872d088f944f", "korean_donor_ui_name_differs")
    value = asset.m_Script.encode("utf-8") if isinstance(asset.m_Script, str) else asset.m_Script
    need(type(value) is bytes, "korean_donor_ui_script_invalid")
    checked = validate_csv(value)
    csv_path, proof_path = Path(work)/"ko.csv", Path(work)/"ko-report.json"
    with csv_path.open("xb") as stream:
        need(stream.write(value) == len(value), "korean_ui_write_incomplete")
    write_json(proof_path, {"language":"ko", "input_sha256":ORIGINAL_CSV_SHA256,
        "output_sha256":checked["sha256"], "bytes":len(value), "source_ui_keys":checked["ui_keys"],
        "prepared_korean_donor":dict(INPUTS["korean_donor"])})
    return csv_path, proof_path


def _korean_sprite_pixels(raw, canvas):
    from idoly_local import static_ui_images as images
    UnityPy,_=images._imports()
    env=UnityPy.load(raw)
    need(len(env.files)==1,"korean_sprite_asset_graph_differs")
    asset=next(iter(env.files.values()))
    need(int(asset.target_platform)==13 and sorted((obj.path_id,obj.class_id) for obj in env.objects)==[(1,213),(2,28)],
         "korean_sprite_asset_graph_differs")
    sprite=asset.objects[1].read();texture=asset.objects[2].read()
    actual=sprite.image.convert("RGBA");decoded=texture.image.convert("RGBA")
    need((sprite.m_Rect.width,sprite.m_Rect.height)==canvas.size and actual.size==decoded.size==canvas.size
         and actual.tobytes()==decoded.tobytes()==canvas.tobytes(),"packaged_korean_sprite_pixels_differ")


def _korean_prefab_transforms(raw):
    from idoly_local import static_ui_images as images
    UnityPy,_=images._imports()
    env=UnityPy.load(raw)
    need(len(env.files)==1,"korean_logo_prefab_graph_differs")
    asset=next(iter(env.files.values()));result={}
    for name,target in images.LOGO_TRANSFORMS.items():
        obj=asset.objects.get(target["android"]["path_id"])
        need(obj is not None and obj.class_id==224,"packaged_korean_logo_transform_missing")
        result[name]=obj.get_raw_data()
    return result


def _verify_korean_layout(archive, proof, image_dir):
    from idoly_local import static_ui_images as images
    import struct
    need(image_dir is not None,"korean_image_inputs_required_for_readback")
    captions=images.FIXED_LOVE_TEXT;names=set(captions)|set(images.LOGO_TRANSFORMS)
    report=proof.get("static_ui_images",{})
    need(report.get("fixed_text_layout_policy")==images.TEXT_LAYOUT_POLICY
         and report.get("fixed_text_sprites")==len(captions),"korean_fixed_text_layout_proof_missing")
    entries=report.get("sprites",[])
    need(type(entries) is list and all(type(row) is dict for row in entries),"korean_sprite_proof_invalid")
    rows={row.get("name"):row for row in entries if row.get("name") in names}
    need(set(rows)==names and sum(row.get("name") in names for row in entries)==len(names),
         "korean_sprite_proof_inventory_differs")
    for profile in (row for row in images.PROFILES if row["name"] in names):
        target=profile["android"];row=rows[profile["name"]];member=target["member"]
        need(row.get("input_member")==member and row.get("input_sha256")==target["asset_sha256"]
             and row.get("png_sha256")==profile["png_sha256"] and row.get("sprite_path_id")==1
             and row.get("private_texture_path_id")==2 and row.get("readback_pixel_exact") is True
             and row.get("layout_policy")==profile["layout_policy"]
             and row.get("layout_size")==list(profile["sprite_size"])
             and row.get("original_layout_size")==target["source_layout"]["sprite_size"]
             and row.get("content_size")==list(profile.get("content_size",profile["png_size"]))
             and row.get("transparent_padding_offset")==list(profile["padding_offset"]),
             "korean_sprite_layout_provenance_differs")
        info=archive.getinfo(member)
        need(0<info.file_size<=256*1024 and info.file_size==row.get("output_bytes"),"packaged_korean_sprite_size_differs")
        raw=archive.read(info)
        need(hashlib.sha256(raw).hexdigest()==row.get("output_sha256"),"packaged_korean_sprite_hash_differs")
        canvas=images._canvas(images._png(image_dir,profile),profile)
        _korean_sprite_pixels(raw,canvas)
    logo=report.get("logo_layout",{});members=logo.get("members",[]);transforms=logo.get("transforms",[])
    need(logo.get("policy")==images.LOGO_LAYOUT_POLICY and logo.get("platform")=="android"
         and logo.get("uniform_scale")==0.75 and logo.get("content_size")==[94.5,24.0]
         and logo.get("original_frame")==[96.0,32.0] and logo.get("full_translated_glyphs_preserved") is True
         and logo.get("all_other_object_bytes_identical") is True and len(members)==1
         and type(members[0]) is dict and members[0].get("member")==images.LOGO_ANDROID_MEMBER
         and members[0].get("original_sha256")==images.LOGO_ANDROID_SHA256
         and members[0].get("only_three_position_size_spans_changed") is True,
         "korean_whole_logo_proof_missing")
    text=proof.get("static_ui_translation",{})
    stages=[row for row in text.get("assets",[]) if row.get("member")==images.LOGO_ANDROID_MEMBER]
    need(text.get("language")=="ko" and text.get("runtime_translation_hooks_added") is False
         and len(stages)==1 and stages[0].get("input_asset_sha256")==images.LOGO_ANDROID_SHA256
         and stages[0].get("input_asset_bytes")==images.LOGO_ANDROID_BYTES
         and stages[0].get("output_asset_sha256")==members[0].get("input_sha256")
         and stages[0].get("output_asset_bytes")==members[0].get("output_bytes")
         and stages[0].get("all_other_object_payloads_unchanged") is True,
         "korean_logo_text_layout_chain_differs")
    info=archive.getinfo(images.LOGO_ANDROID_MEMBER)
    need(0<info.file_size<=2*1024*1024 and info.file_size==members[0].get("output_bytes"),"packaged_korean_logo_size_differs")
    raw=archive.read(info);prefab_hash=hashlib.sha256(raw).hexdigest()
    need(prefab_hash==members[0].get("output_sha256"),"packaged_korean_logo_hash_differs")
    actual=_korean_prefab_transforms(raw)
    need(type(transforms) is list and len(transforms)==3 and all(type(row) is dict for row in transforms)
         and {row.get("name") for row in transforms}==set(images.LOGO_TRANSFORMS),"korean_logo_transform_inventory_differs")
    for row in transforms:
        name=row["name"];target=images.LOGO_TRANSFORMS[name];source=target["android"];payload=actual[name]
        need(len(payload)==108,"packaged_korean_logo_transform_size_differs")
        original=payload[:84]+struct.pack("<4f",target["old_x"],0.0,32.0,32.0)+payload[100:]
        expected,canonical=images._logo_rect(original,name,"android")
        need(payload==expected and all(row.get(key)==value for key,value in canonical.items()),
             "packaged_korean_logo_transform_differs")
    return {"fixed_text_layout_policy":images.TEXT_LAYOUT_POLICY,"fixed_text_sprites":len(captions),
        "packaged_sprite_pixel_readbacks":len(names),"logo_policy":images.LOGO_LAYOUT_POLICY,
        "logo_prefab_sha256":prefab_hash,"logo_transform_readbacks":3,"text_to_layout_chain_verified":True}


def verify_language(apk, proof, language, commit, full, *, prepared_ui_sha256=None, korean_image_dir=None):
    need(proof.get("source_commit") == commit and proof.get("source_apk_sha256") == INPUTS["diagnostic_base"]["sha256"]
         and proof.get("source_apk_bytes") == INPUTS["diagnostic_base"]["bytes"]
         and proof.get("ui_language") == language and proof.get("certificate_sha256") == CERTIFICATE
         and proof.get("signature_v2_v3_verified") is True
         and proof.get("local_resource_output_fields_verified") is True
         and proof.get("all_original_members_preserved_except_declared_manifest_font_UI_transport_and_story_loading") is True
         and proof.get("native_input", {}).get("source_commit") == commit
         and proof.get("device_tested") is False, "full_client_provenance_differs")
    need(record(apk) == {"bytes": proof.get("output_bytes"), "sha256": proof.get("output_apk_sha256")},
         "full_client_output_digest_differs")
    font = proof.get("font_support", {})
    need(font.get("original_long_dash_font_retained") is True
         and font.get("legacy_Japanese_font_data_unchanged") is True
         and font.get("all_other_objects_byte_identical") is True
         and font.get("output_members"), "font_support_differs")
    with ZipFile(apk) as archive:
        need(len(archive.namelist()) == len(set(archive.namelist())), "duplicate_output_member")
        def digest_member(name):
            with archive.open(name) as incoming:
                return hashlib.file_digest(incoming, "sha256").hexdigest()
        for name, item in font["output_members"].items():
            need(archive.getinfo(name).file_size == item["bytes"] and digest_member(name) == item["sha256"],
                 "packaged_font_member_differs")
        ui_hash = digest_member(UI_MEMBER)
        if language == "ja":
            need(archive.getinfo(UI_MEMBER).file_size == 244584 and ui_hash == JAPANESE_UI_SHA256
                 and proof.get("ui_translation") is None, "japanese_ui_not_original")
        else:
            ui = proof.get("ui_translation", {})
            expected_csv = INPUTS["english_ui"]["sha256"] if language == "en" else prepared_ui_sha256
            need(language in ("ko", "en") and isinstance(expected_csv, str)
                 and re.fullmatch(r"[0-9a-f]{64}", expected_csv) is not None
                 and ui.get("language") == language and ui.get("output_asset_sha256") == ui_hash
                 and ui.get("compiled_csv_sha256") == expected_csv
                 and ui.get("runtime_translation_hooks_added") is False
                 and ui.get("all_other_objects_byte_identical") is True, "translated_ui_not_packaged")
        layout=_verify_korean_layout(archive,proof,korean_image_dir) if language=="ko" else None
        full.verify_local_resource_output(archive, proof["local_resource_transport"])
        guid_hash = digest_member(full.unity_cache.MEMBER)
        native_hash = digest_member(full.addon.LIBRARY)
        need(native_hash == proof["native_library_sha256"], "packaged_presentation_native_differs")
    result={"ui_asset_sha256":ui_hash,"unity_cache_sha256":guid_hash,"presentation_native_sha256":native_hash}
    if layout is not None: result["korean_image_layout"]=layout
    return result


def korean_image_fetcher():
    # Direct script execution exposes tools/ rather than its parent namespace.
    return importlib.import_module("fetch_korean_ui_images").fetch_images


def build(args):
    phase("checkout")
    need(re.fullmatch(r"[0-9a-f]{40}", args.source_commit), "exact_source_commit_required")
    run_id = int(args.run_id or os.environ.get("GITHUB_RUN_ID", "0"))
    need(run_id > 0 and str(run_id) == os.environ.get("GITHUB_RUN_ID", str(run_id)), "exact_run_id_required")
    phase("directories")
    work_arg, output_arg = Path(args.work).absolute(), Path(args.output).absolute()
    need(not work_arg.is_symlink() and not output_arg.is_symlink(), "non_symlink_remote_paths_required")
    work, output = work_arg.resolve(strict=False), output_arg.resolve(strict=False)
    need(work != output and not work.exists() and not output.exists()
         and not work.is_symlink() and not output.is_symlink(), "fresh_remote_directories_required")
    need(not work.is_relative_to(ROOT) and not output.is_relative_to(ROOT)
         and not work.is_relative_to(output) and not output.is_relative_to(work), "external_separate_work_and_output_required")
    need(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
         == args.source_commit, "checkout_source_differs")
    # All inputs are public and source checks are local Git reads. Native/Java
    # child tools do not need repository tokens or inherited tracing options.
    for name in tuple(os.environ):
        if name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_DEBUG", "GIT_CURL_VERBOSE") or name.startswith("GIT_TRACE"):
            os.environ.pop(name, None)
    sys.path[:0] = [str(ROOT / "client-presentation"), str(ROOT / "tools"), str(ROOT / "src")]
    shared = importlib.import_module("release_platform_builds")
    addon = importlib.import_module("build_addon")
    full = importlib.import_module("build_full_client")
    limits = importlib.import_module("build_android_server_manual")
    guard = shared.Guard()
    phase("resources")
    resource_guard = runner_resource_guard(limits)
    hosted_disk_staging = resource_guard is not None
    work.mkdir(mode=0o700); output.mkdir(mode=0o700)
    inputs = {}
    for name, url in URLS.items():
        phase("input_" + name)
        inputs[name] = work / (name + (".apk" if name == "diagnostic_base" else ".bin"))
        download(url, INPUTS[name], inputs[name], guard)
    for name, filename in (("english_ui", "en.csv"), ("english_ui_proof", "en-report.json")):
        phase("input_" + name)
        inputs[name] = ROOT / "ios-unified/client-language-inputs" / filename
        verify_input(inputs[name], INPUTS[name])
    phase("sdk")
    android_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    need(android_home is not None, "android_sdk_root_required")
    sdk_root = Path(android_home)
    jdk = Path(args.jdk_bin or (Path(os.environ["JAVA_HOME"]) / "bin")).resolve(strict=True)
    sdk = Path(args.build_tools or (sdk_root / "build-tools/34.0.0")).resolve(strict=True)
    android = Path(args.android_jar or (sdk_root / "platforms/android-34/android.jar")).resolve(strict=True)
    args.ndk = args.ndk or (sdk_root / "ndk/26.3.11579264")
    for filename, expected in ((android, limits.PUBLIC_INPUT_HASHES["android-jar"]),
        (sdk / "lib/d8.jar", limits.PUBLIC_INPUT_HASHES["d8-jar"]),
        (sdk / "lib/apksigner.jar", limits.PUBLIC_INPUT_HASHES["signer-jar"])):
        need(sha(filename) == expected, "android_build_tool_input_differs")
    phase("native")
    library, readelf = prepare_native(args, addon, limits, guard, work, inputs, resource_guard=resource_guard)
    password = work / "public-diagnostic-password"
    password.write_bytes(b"android"); password.chmod(0o600)
    key = ROOT / "android-diagnostics/local-diagnostics-development.keystore"
    common = dict(source_commit=args.source_commit, jdk_bin=jdk, build_tools=sdk,
                  keystore=key, password_file=password)
    feature = work / "diagnostics-feature.apk"
    phase("feature")
    addon.build(SimpleNamespace(profile="diagnostics", base_apk=inputs["diagnostic_base"],
        native_library=library, output=feature, android_jar=android, shadowhook_aar=inputs["shadowhook"],
        readelf=readelf, **common), resource_guard=resource_guard)
    extra = (*full.TRANSPORT_SOURCES, *full.STATIC_UI_SOURCES,
        "client-presentation/build_full_client.py", "tools/build_android_server_manual.py",
        "tools/repack_android_server_python.py", "tools/package_android_resource_client.py",
        "src/idoly_local/font_assets.py", "client-presentation/fonts/pretendard-jp-v1.json",
        "client-presentation/licenses/Pretendard-OFL.txt", "src/idoly_local/ui_assets.py",
        "src/idoly_local/ui_translation_build.py", *REQUIRED_SOURCES)
    source_hashes = addon.frozen_sources(args.source_commit, extra=extra)
    fetch_images = korean_image_fetcher()
    image_dir = work / "ko-images"
    image_inputs = fetch_images(image_dir)
    korean_csv, korean_proof = extract_korean_ui(inputs["korean_donor"], work)
    from idoly_local.ui_assets import load_package_inputs
    korean_prepared, _ = load_package_inputs("ko", korean_csv, korean_proof)
    korean_csv_sha256 = hashlib.sha256(korean_prepared).hexdigest()
    binaries, packaging_evidence = [], {}
    for language in LANGUAGES:
        phase("language_" + language)
        guard.check()
        apk = output / CLIENT_NAMES[language]
        proof = full.build(SimpleNamespace(source=inputs["diagnostic_base"], feature_apk=feature,
            output=apk, ram_directory=output if hosted_disk_staging else Path("/dev/shm"), all_tmpfs=False,
            hosted_disk_staging=hosted_disk_staging,
            apkeditor=inputs["apkeditor"], font_file=inputs["font"], font_license_file=None,
            ui_language=language, ui_csv_file=inputs["english_ui"] if language == "en" else korean_csv if language == "ko" else None,
            ui_proof_file=inputs["english_ui_proof"] if language == "en" else korean_proof if language == "ko" else None,
            image_dir=image_dir, native_library=None, **common), resource_guard=resource_guard)
        packaged = verify_language(apk, proof, language, args.source_commit, full,
                                   prepared_ui_sha256=korean_csv_sha256 if language == "ko" else None,
                                   korean_image_dir=image_dir if language=="ko" else None)
        signer = [jdk / "java", *addon.JAVA_FLAGS, "-jar", sdk / "lib/apksigner.jar"]
        checked = limits._run(full.output_verify_command(signer, apk), root=ROOT,
                              env=shared.clean_env(), timeout=60, guard=resource_guard).decode("utf-8")
        need(re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([a-f0-9]{64})$", checked, re.M)
             == [CERTIFICATE] and all("Verified using v" + str(n) +
                " scheme (APK Signature Scheme v" + str(n) + "): true" in checked for n in (2, 3)),
             "final_signature_differs")
        limits._run([sdk / "zipalign", "-c", "16384", apk], root=ROOT, env=shared.clean_env(), timeout=60, guard=resource_guard)
        badging = limits._run([sdk / "aapt2", "dump", "badging", apk], root=ROOT,
                             env=shared.clean_env(), timeout=60, guard=resource_guard).decode("utf-8")
        need("package: name='" + PACKAGE + "'" in badging and "versionCode='414'" in badging
             and "versionName='6.1.1'" in badging and "native-code: 'arm64-v8a'" in badging,
             "final_update_identity_differs")
        binaries.append({"language": language, "name": apk.name, **record(apk),
            "application_id": PACKAGE, "version_code": VERSION_CODE,
            "certificate_sha256": CERTIFICATE})
        packaging_evidence[language] = packaged
    phase("verification")
    need(len({row["unity_cache_sha256"] for row in packaging_evidence.values()}) == len(LANGUAGES), "locale_cache_guids_not_distinct")
    need(len({row["presentation_native_sha256"] for row in packaging_evidence.values()}) == 1, "locale_native_features_differ")
    for name, path in inputs.items():
        verify_input(path, INPUTS[name])
    need(addon.frozen_sources(args.source_commit, extra=extra) == source_hashes, "build_sources_changed")
    guard.check()
    (output / "native").mkdir()
    shutil.copyfile(work / "native/build-receipt.json", output / "native/build-receipt.json")
    shutil.copyfile(feature.with_suffix(".provenance.json"), output / "diagnostics-feature.provenance.json")
    reports = ("native/build-receipt.json", "diagnostics-feature.provenance.json",
               *(Path(CLIENT_NAMES[lang]).with_suffix(".provenance.json").name for lang in LANGUAGES))
    value = {"schema": 1, "status": "PASS", "source_commit": args.source_commit, "run_id": run_id,
        "languages": list(LANGUAGES), "binaries": binaries, "inputs": INPUTS,
        "source_sha256": source_hashes,
        "validation": {**{name: True for name in VALIDATION_FLAGS}, "runtime_device_tested": False},
        "packaging_evidence": packaging_evidence, "korean_image_inputs": image_inputs,
        "report_files": {name: record(output / name) for name in reports},
        "input_provenance": {"diagnostic_base_release_asset": 728205797,
            "diagnostic_base_reused_immutable": True, "fresh_native_feature_for_current_source": True,
            "font_public_commit": FONT_PUBLIC_COMMIT, "font_git_blob": FONT_GIT_BLOB,
            "package_variants_are_alternative_updates": True, "ko_client_reused_unchanged": False, "ko_client_rebuilt_from_current_source": True},
        "resources": {**guard.report(), "hosted_policy": resource_guard.report() if resource_guard is not None else None}}
    phase("final")
    write_json(output / REPORT_NAME, value)
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("work", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("jdk-bin", "build-tools", "android-jar", "ndk"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    try:
        result = build(args)
    except Exception as error:
        failure = failure_report(error)
        if (_PHASE not in ("startup", "checkout", "directories")
                and args.output.is_dir() and not args.output.is_symlink()):
            try:
                write_json(args.output / "android-client-failure.json", failure)
            except OSError:
                pass
        print(json.dumps(failure))
        return 1
    print(json.dumps({"status": result["status"], "source_commit": result["source_commit"],
                      "binaries": result["binaries"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
