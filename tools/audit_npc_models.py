#!/usr/bin/env python3
"""Audit fixed public NPC model metadata on an owned Actions runner.

This does not load a game, execute model code, change cards, or enable an NPC.
Each Unity bundle is read in a fresh bounded worker; no mesh/texture payloads
are exported and unresolvable references remain explicitly unknown.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import time
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024
SERVER_BYTES = 191343014
SERVER_SHA256 = "37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"
MAX_OBJECT_BYTES = 64 * MIB
MAX_TOTAL_BYTES = 256 * MIB
MAX_READERS = 4096
MAX_TREE_BYTES = 4 * MIB
MAX_NAMES = 512
MAX_NAME = 128
MAX_OUTPUT = 2 * MIB
MAX_UNREADABLE = 64
TREE_CLASSES = frozenset((1, 4, 90, 95, 114, 115, 137))
# Sakura's actual Character.defaultLiveCostumeId -> Costume.defaultHairId
# is cos-skr-schl-00 -> hair-skr-schl-00 in the pinned 6.1.1 master.
MODELS = {
    "baseline_sakura": ("mdl_chr_skr-schl-00_body", "mdl_chr_skr-base-00_face", "mdl_chr_skr-base-00_hair"),
    "satomi": ("mdl_chr_stm-idol-02_body", "mdl_chr_stm-base-00_face", "mdl_chr_stm-base-00_hair"),
    "lemon_candidate": ("mdl_chr_lmn-idol-00_body", "mdl_chr_lmn-base-00_face", "mdl_chr_lmn-base-00_hair"),
    "lime_candidate": ("mdl_chr_lim-idol-00_body", "mdl_chr_lim-base-00_face", "mdl_chr_lim-base-00_hair"),
}
SELECTED_NAMES = tuple(name for names in MODELS.values() for name in names)
PUBLIC_MEMBERS = {"data/public-octo/settings.json": 64 * 1024,
                  "data/public-octo/manifest.pb": 16 * MIB}
LOGICAL_NAME = re.compile(r"(?:mdl|img)_[A-Za-z0-9_-]{1,160}\Z")
SAFE_NAME = re.compile(r"[A-Za-z0-9_ .:+()#@-]{1,128}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")


class AuditError(ValueError):
    """A fixed, credential-free failure code."""


def need(value, code):
    if not value:
        raise AuditError(code)


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    need(0 < len(raw) <= MAX_OUTPUT, "report_size_bound")
    with Path(path).open("xb") as stream:
        stream.write(raw)


def mask(name):
    need(type(name) is str and LOGICAL_NAME.fullmatch(name) is not None, "logical_name_invalid")
    source = name.encode("ascii")
    values = bytearray(len(source) * 2)
    for index, value in enumerate(source):
        values[index * 2] = value
        values[len(values) - 1 - index * 2] = value ^ 255
    checksum = 0x9B
    for value in values:
        checksum = ((checksum & 1) << 7 | checksum >> 1) ^ value
    return bytes(value ^ checksum for value in values)


def crypt_header(raw, name):
    need(type(raw) is bytes and 0 < len(raw) <= MAX_OBJECT_BYTES, "bundle_extent_invalid")
    key = mask(name)
    return bytes(value ^ key[index % len(key)] for index, value in enumerate(raw[:256])) + raw[256:]


def verify_bundle(raw, *, name, size, md5, sha256):
    need(name in SELECTED_NAMES and type(size) is int and 0 < size <= MAX_OBJECT_BYTES,
         "bundle_identity_invalid")
    need(type(raw) is bytes and len(raw) == size
         and type(md5) is str and re.fullmatch(r"[0-9a-f]{32}", md5) is not None
         and hashlib.md5(raw, usedforsecurity=False).hexdigest() == md5,
         "bundle_length_or_md5_differs")
    need(type(sha256) is str and SHA.fullmatch(sha256) is not None
         and hashlib.sha256(raw).hexdigest() == sha256, "bundle_sha256_differs")
    decoded = raw if raw.startswith(b"UnityFS\0") else crypt_header(raw, name)
    need(decoded.startswith(b"UnityFS\0"), "unityfs_header_differs")
    return decoded


def select_records(records):
    wanted = set(SELECTED_NAMES)
    need(len(wanted) == len(SELECTED_NAMES) == 12, "fixed_selection_differs")
    found = {}
    for record in records:
        if record.name not in wanted:
            continue
        need(record.name not in found and record.kind == "assetbundle",
             "selected_record_duplicate_or_kind")
        need(type(record.size) is int and 0 < record.size <= MAX_OBJECT_BYTES,
             "selected_object_size_bound")
        found[record.name] = record
    need(found.keys() == wanted, "selected_public_model_missing")
    need(sum(record.size for record in found.values()) <= MAX_TOTAL_BYTES, "selected_total_bound")
    return tuple(found[name] for name in SELECTED_NAMES)


def extract_public_archive(payload, destination, guard):
    payload, destination = Path(payload), Path(destination)
    info = payload.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_size == SERVER_BYTES
         and file_sha(payload) == SERVER_SHA256, "server_data_pin_differs")
    destination.mkdir(mode=0o700)
    with ZipFile(payload) as archive:
        selected = {}
        for item in archive.infolist():
            if item.filename not in PUBLIC_MEMBERS:
                continue
            need(item.filename not in selected, "public_member_duplicate")
            path = PurePosixPath(item.filename)
            need(not path.is_absolute() and ".." not in path.parts and "\\" not in item.filename
                 and not stat.S_ISLNK(item.external_attr >> 16) and not item.flag_bits & 1
                 and 0 < item.file_size <= PUBLIC_MEMBERS[item.filename], "public_member_bound")
            selected[item.filename] = item
        need(selected.keys() == PUBLIC_MEMBERS.keys(), "public_archive_incomplete")
        for name, item in selected.items():
            target = destination / PurePosixPath(name).name
            count = 0
            with archive.open(item) as incoming, target.open("xb") as outgoing:
                while block := incoming.read(64 * 1024):
                    guard.check()
                    count += len(block)
                    need(count <= item.file_size, "public_member_extent")
                    outgoing.write(block)
            need(count == item.file_size, "public_member_truncated")


def bounded_name(value):
    return value if type(value) is str and SAFE_NAME.fullmatch(value) is not None else None


def pointer(value):
    if not isinstance(value, dict):
        return None
    file_id, path_id = value.get("m_FileID"), value.get("m_PathID")
    if type(file_id) is not int or not 0 <= file_id <= 65535:
        return None
    if type(path_id) is not int or not -(1 << 63) <= path_id < (1 << 63):
        return None
    return file_id, path_id


def small_list(value, maximum=2048):
    need(type(value) is list and len(value) <= maximum, "metadata_list_bound")
    return value


def summary(readers, *, name, check=lambda: None):
    """Consume metadata readers only; Texture2D/Mesh readers are never read."""
    need(name in SELECTED_NAMES, "summary_name_not_selected")
    rows = []
    for obj in readers:
        check()
        need(len(rows) < MAX_READERS, "unity_object_count_bound")
        rows.append(obj)
    need(rows, "unity_object_count_bound")
    counts = Counter()
    objects, readable, skipped, skipped_total = {}, Counter(), [], 0
    for obj in rows:
        check()
        class_id = int(obj.class_id)
        need(0 <= class_id <= 65535, "unity_class_id_invalid")
        counts[class_id] += 1
        if class_id not in TREE_CLASSES:
            continue
        path_id = int(obj.path_id)
        need(-(1 << 63) <= path_id < (1 << 63), "unity_path_id_invalid")
        size = getattr(obj, "byte_size", None)
        try:
            need(type(size) is int and 0 < size <= MAX_TREE_BYTES, "metadata_object_extent")
            tree = obj.read_typetree()
            need(type(tree) is dict and len(tree) <= 512, "metadata_root_bound")
        except Exception as error:
            skipped_total += 1
            if len(skipped) < MAX_UNREADABLE:
                skipped.append({"class_id": class_id, "path_id": path_id,
                                "reason": "type_tree_unreadable",
                                "error_type": type(error).__name__[:64]})
            continue
        identity = (obj.assets_file.name, path_id)
        need(identity not in objects, "metadata_identity_duplicate")
        objects[identity] = (class_id, tree)
        readable[class_id] += 1

    def resolve(owner, value, expected):
        target = pointer(value)
        if target is None or target[0] != 0 or target[1] == 0:
            return None
        candidate = objects.get((owner, target[1]))
        return candidate[1] if candidate is not None and candidate[0] == expected else None

    def game_name(owner, tree):
        game = resolve(owner, tree.get("m_GameObject"), 1)
        return bounded_name(game.get("m_Name")) if game else None

    game_names, bone_names, scripts, rig_markers, face_markers = set(), set(), set(), set(), set()
    external_refs, unbound_bones, script_unresolved = 0, 0, 0
    animators, avatars, renderers = [], [], []
    total_bones, blend_weights = 0, 0
    human_avatars = 0
    for (owner, _path_id), (class_id, tree) in objects.items():
        check()
        if class_id == 1:
            value = bounded_name(tree.get("m_Name"))
            if value:
                game_names.add(value)
        elif class_id == 90:
            fields = tree.get("m_Avatar")
            fields = fields if type(fields) is dict else {}
            human = fields.get("m_Human")
            human = human if type(human) is dict else {}
            human_avatars += bool(human)
            need(len(avatars) < 64, "avatar_count_bound")
            avatars.append({"name": bounded_name(tree.get("m_Name")),
                            "avatar_fields": sorted(key for key in fields if bounded_name(key))[:64],
                            "human_fields": sorted(key for key in human if bounded_name(key))[:64],
                            "human_structure_present": bool(human)})
        elif class_id == 95:
            need(len(animators) < 64, "animator_count_bound")
            avatar = pointer(tree.get("m_Avatar"))
            external_refs += bool(avatar and avatar[0] != 0 and avatar[1] != 0)
            animators.append({"game_object": game_name(owner, tree),
                              "avatar_reference": list(avatar) if avatar else None,
                              "avatar_resolved_in_bundle": resolve(owner, tree.get("m_Avatar"), 90) is not None})
        elif class_id == 137:
            bones = small_list(tree.get("m_Bones", []))
            weights = small_list(tree.get("m_BlendShapeWeights", []))
            total_bones += len(bones)
            blend_weights += len(weights)
            need(len(renderers) < 64, "renderer_count_bound")
            renderers.append({"game_object": game_name(owner, tree), "bone_slots": len(bones),
                              "blend_shape_weight_slots": len(weights),
                              "root_bone_reference": list(pointer(tree.get("m_RootBone")) or ())})
            for item in bones:
                reference = pointer(item)
                if reference and reference[0] != 0 and reference[1] != 0:
                    external_refs += 1
                bone = resolve(owner, item, 4)
                value = game_name(owner, bone) if bone else None
                if value:
                    bone_names.add(value)
                else:
                    unbound_bones += 1
        elif class_id == 114:
            reference = pointer(tree.get("m_Script"))
            if reference and reference[0] != 0 and reference[1] != 0:
                external_refs += 1
            script = resolve(owner, tree.get("m_Script"), 115)
            if script:
                parts = [bounded_name(script.get(key)) for key in ("m_Namespace", "m_ClassName")]
                value = ".".join(part for part in parts if part)
                if value and len(value) <= MAX_NAME:
                    scripts.add(value)
            else:
                script_unresolved += 1
            direct = bounded_name(tree.get("m_EditorClassIdentifier"))
            if direct:
                scripts.add(direct)
    need(all(len(values) <= MAX_NAMES for values in (game_names, bone_names, scripts)), "metadata_name_count_bound")
    for value in sorted(game_names | scripts):
        if re.search(r"(?:rig|quartz|swing|spring|constraint|fullbody|inversekinematic|\bik\b)", value, re.I):
            rig_markers.add(value)
        if re.search(r"(?:facial|blendshape|lipsync|face)", value, re.I):
            face_markers.add(value)
    bones = sorted(bone_names)
    constraints = []
    if skipped_total:
        constraints.append("Some selected object type trees could not be read.")
    if external_refs:
        constraints.append("External references were not followed or downloaded.")
    if unbound_bones:
        constraints.append("Some skin bone names could not be resolved inside this bundle.")
    if script_unresolved:
        constraints.append("Some component script classes could not be resolved inside this bundle.")
    if not avatars:
        constraints.append("No readable Avatar object is embedded in this bundle.")
    return {
        "name": name, "object_count": len(rows),
        "class_counts": {str(key): value for key, value in sorted(counts.items())},
        "readable_metadata_class_counts": {str(key): value for key, value in sorted(readable.items())},
        "unreadable_type_trees": skipped, "unreadable_type_tree_count": skipped_total,
        "game_object_names": sorted(game_names), "resolved_skin_bone_names": bones,
        "resolved_skin_bone_names_sha256": hashlib.sha256("\n".join(bones).encode()).hexdigest(),
        "total_skin_bone_slots": total_bones, "unresolved_skin_bone_slots": unbound_bones,
        "skinned_renderers": renderers, "blend_shape_weight_slots": blend_weights,
        "animators": animators, "avatars": avatars, "human_avatar_structures": human_avatars,
        "component_script_classes": sorted(scripts), "unresolved_script_components": script_unresolved,
        "external_reference_count": external_refs,
        "facial_name_markers": sorted(face_markers), "rig_name_markers": sorted(rig_markers),
        "metadata_constraints": constraints,
        "runtime_motion_tested": False, "runtime_mv_compatibility": "NOT_TESTED", "npc_enabled": False,
    }


class Guard:
    def __init__(self):
        self.oom = None
        self.minimum_memory = None
        self.minimum_disk = None
        self.samples = 0
        self.check(entry=True)

    def check(self, *, entry=False):
        floor = (1024 if entry else 512) * MIB
        root = Path("/sys/fs/cgroup")
        if (root / "memory.max").is_file() and (root / "memory.max").read_text().strip() != "max":
            available = int((root / "memory.max").read_text()) - int((root / "memory.current").read_text())
        else:
            memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
            available = int(memory["MemAvailable"].split()[0]) * 1024
        if (root / "memory.events").is_file():
            events = dict(line.split() for line in (root / "memory.events").read_text().splitlines())
            now = int(events["oom_kill"])
            if self.oom is None:
                self.oom = now
            need(self.oom == now, "runner_oom_changed")
        free = shutil.disk_usage("/").free
        need(available >= floor, "runner_memory_floor")
        need(free >= 150 * MIB, "runner_root_disk_floor")
        self.minimum_memory = available if self.minimum_memory is None else min(self.minimum_memory, available)
        self.minimum_disk = free if self.minimum_disk is None else min(self.minimum_disk, free)
        self.samples += 1

    def report(self):
        return {"oom_baseline": self.oom, "minimum_memory_bytes": self.minimum_memory,
                "minimum_root_free_bytes": self.minimum_disk, "samples": self.samples}


def owned_main(args):
    need(sys.platform.startswith("linux") and os.environ.get("GITHUB_ACTIONS") == "true"
         and os.environ.get("GITHUB_REPOSITORY") == "tagundo/IdolyPride_client"
         and args.source_commit == os.environ.get("GITHUB_SHA")
         and os.environ.get("GITHUB_RUN_ID", "").isdigit(), "remote_actions_required")
    # Keep SHA-1 source identities distinct from content SHA-256.
    need(type(args.source_commit) is str and re.fullmatch(r"[0-9a-f]{40}", args.source_commit) is not None,
         "source_commit_invalid")
    need(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() == args.source_commit,
         "source_checkout_differs")
    need(subprocess.run(["git", "diff", "--quiet", "--", "tools/audit_npc_models.py",
                         "tests/test_npc_model_audit.py"], cwd=ROOT).returncode == 0,
         "audit_source_dirty")
    runner = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    need(args.work.is_absolute() and args.work.parent.resolve(strict=True) == runner
         and not args.work.exists() and not args.work.is_symlink(), "fresh_runner_work_required")
    need(args.output.is_absolute() and not args.output.exists() and not args.output.is_symlink()
         and (args.output.parent == args.work or args.output.parent.resolve(strict=True) == runner),
         "fresh_owned_report_required")
    source = args.server_data.resolve(strict=True)
    need(args.server_data.is_absolute() and source.is_relative_to(runner)
         and not args.server_data.is_symlink(), "owned_server_data_required")
    return runner


def worker(args):
    need(sys.platform.startswith("linux") and os.environ.get("GITHUB_ACTIONS") == "true"
         and os.environ.get("GITHUB_REPOSITORY") == "tagundo/IdolyPride_client"
         and args.source_commit == os.environ.get("GITHUB_SHA")
         and args.worker_name in SELECTED_NAMES, "remote_worker_required")
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    guard = Guard()
    root = args.work.resolve(strict=True)
    runner = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    need(root.parent == runner and root.is_dir() and not args.work.is_symlink(), "worker_owned_root_required")
    path = args.worker_input
    need(path.is_absolute() and path.parent.resolve(strict=True) == root / "bundles"
         and not path.is_symlink() and stat.S_ISREG(path.lstat().st_mode), "worker_input_path_invalid")
    need(args.output.parent.resolve(strict=True) == root / "metadata"
         and not args.output.exists() and not args.output.is_symlink(), "worker_output_path_invalid")
    need(path.stat().st_size == args.worker_size <= MAX_OBJECT_BYTES, "worker_input_extent")
    phase = "bundle_validation"
    try:
        need(importlib.metadata.version("UnityPy") == "1.25.4", "audited_unitypy_version_required")
        with path.open("rb") as stream:
            raw = stream.read(MAX_OBJECT_BYTES + 1)
        decoded = verify_bundle(raw, name=args.worker_name, size=args.worker_size,
                                md5=args.worker_md5, sha256=args.worker_sha256)
        phase = "unity_import"
        import UnityPy
        import UnityPy.config
        UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.57f1"
        phase = "unity_load"
        environment = UnityPy.load(decoded)
        phase = "metadata_summary"
        result = summary(environment.objects, name=args.worker_name, check=guard.check)
        result["resources"] = guard.report()
        write_json(args.output, result)
    except Exception as error:
        if not args.output.exists():
            write_json(args.output, {"schema": 1, "status": "FAIL", "name": args.worker_name,
                "error_type": type(error).__name__[:128], "phase": phase,
                "error_code": str(error) if isinstance(error, AuditError) else "metadata_worker_failed",
                "runtime_motion_tested": False, "npc_enabled": False})
        raise SystemExit(1) from None


def comparisons(results):
    by_name = {row["name"]: row for row in results}
    baseline = set(by_name[MODELS["baseline_sakura"][0]]["resolved_skin_bone_names"])
    values = {}
    for role, names in MODELS.items():
        current = set(by_name[names[0]]["resolved_skin_bone_names"])
        values[role] = {"baseline_body": MODELS["baseline_sakura"][0], "candidate_body": names[0],
                        "baseline_resolved_bones": len(baseline), "candidate_resolved_bones": len(current),
                        "shared_bone_names": sorted(current & baseline),
                        "missing_baseline_bone_names": sorted(baseline - current),
                        "extra_candidate_bone_names": sorted(current - baseline),
                        "complete_bone_name_match": bool(baseline) and current == baseline,
                        "runtime_mv_compatibility": "NOT_TESTED", "npc_enabled": False}
    return values


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-data", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker-name", help=argparse.SUPPRESS)
    parser.add_argument("--worker-input", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-size", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--worker-md5", help=argparse.SUPPRESS)
    parser.add_argument("--worker-sha256", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    os.umask(0o077)
    if args.worker_name is not None:
        worker(args)
        return 0
    need(args.server_data is not None, "server_data_required")
    owned_main(args)
    guard = Guard()
    args.work.mkdir(mode=0o700)
    for directory in ("bundles", "metadata"):
        (args.work / directory).mkdir(mode=0o700)
    try:
        # Project/native dependencies are deliberately imported only after the
        # remote identity, clean owned paths and resource entry guards pass.
        sys.path.insert(0, str(ROOT / "src"))
        from idoly_local.octo_runtime import load_octo_archive, _desktop_aes_backend
        from idoly_local.octo_manifest import OctoManifest
        from idoly_local.octo_cache import OctoCache
        archive = args.work / "public-octo"
        extract_public_archive(args.server_data, archive, guard)
        settings, plain = load_octo_archive(archive, platform="android")
        manifest = OctoManifest(plain, aes_key=bytes.fromhex(settings["aes_key_hex"]),
            client_key=settings["client_key"], base_url="http://127.0.0.1:8080",
            aes_cbc=_desktop_aes_backend(), application_version=settings["application_version"])
        selected = select_records(manifest.objects.values())
        report = {"schema": 1, "status": "RUNNING", "source_commit": args.source_commit,
                  "platform": "android", "revision": manifest.revision,
                  "server_data": {"bytes": SERVER_BYTES, "sha256": SERVER_SHA256},
                  "manifest_sha256": settings["manifest_sha256"],
                  "tool_sha256": file_sha(Path(__file__)), "unitypy_version": "1.25.4",
                  "selection_count": len(selected), "selection_bytes": sum(row.size for row in selected),
                  "baseline_selection": {"character_id": "char-skr", "costume_id": "cos-skr-schl-00",
                                         "hair_id": "hair-skr-schl-00"},
                  "name_mapping": {"satomi": "Character char-stm has assetId stm",
                                   "lemon_candidate": "lmn is a candidate; visual/ADV name binding is not verified",
                                   "lime_candidate": "lim is a candidate; visual/ADV name binding is not verified"},
                  "objects": [], "runtime_motion_tested": False,
                  "runtime_mv_compatibility": "NOT_TESTED", "npc_enabled": False}
        cache = OctoCache(args.work / "cache", max_object_bytes=MAX_OBJECT_BYTES,
            max_parallel=1, timeout=30, total_timeout=180, max_download_bytes=MAX_TOTAL_BYTES,
            write_guard=lambda *_args: guard.check())
        try:
            for record in selected:
                guard.check()
                target = args.work / "bundles" / (record.name + ".bundle")
                count, checksum, md5 = 0, hashlib.sha256(), hashlib.md5(usedforsecurity=False)
                with cache.open_verified(record) as incoming, target.open("xb") as outgoing:
                    while block := incoming.read(64 * 1024):
                        guard.check()
                        count += len(block)
                        need(count <= record.size <= MAX_OBJECT_BYTES, "verified_bundle_extent")
                        checksum.update(block); md5.update(block); outgoing.write(block)
                need(count == record.size and md5.hexdigest() == record.md5, "verified_bundle_digest_differs")
                metadata = args.work / "metadata" / (record.name + ".json")
                command = [sys.executable, "-B", str(Path(__file__).resolve()),
                    "--source-commit", args.source_commit, "--work", str(args.work), "--output", str(metadata),
                    "--worker-name", record.name, "--worker-input", str(target), "--worker-size", str(record.size),
                    "--worker-md5", record.md5, "--worker-sha256", checksum.hexdigest()]
                worker_env = {key: value for key, value in os.environ.items()
                              if key not in ("GH_TOKEN", "GITHUB_TOKEN", "GH_DEBUG", "GIT_CURL_VERBOSE")
                              and not key.startswith("GIT_TRACE")}
                worker_env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
                                  MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, env=worker_env)
                deadline = time.monotonic() + 180
                try:
                    while child.poll() is None:
                        guard.check()
                        need(time.monotonic() < deadline, "metadata_worker_timeout")
                        time.sleep(.2)
                    need(child.returncode == 0, "metadata_worker_failed")
                finally:
                    if child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait(timeout=10)
                need(0 < metadata.stat().st_size <= MAX_OUTPUT, "worker_report_bound")
                result = json.loads(metadata.read_text())
                need(result["name"] == record.name and result["runtime_motion_tested"] is False
                     and result["npc_enabled"] is False, "worker_report_identity_differs")
                result["verified_source"] = {"bytes": count, "md5": md5.hexdigest(),
                    "sha256": checksum.hexdigest(), "upload_version": record.upload_version,
                    "object_name": record.object_name, "generation": record.generation}
                report["objects"].append(result)
        finally:
            cache.close()
        report.update(status="METADATA_AUDIT_COMPLETE", comparisons=comparisons(report["objects"]),
                      resources=guard.report(),
                      interpretation="Metadata similarity is not animation/Avatar/runtime compatibility proof.")
        write_json(args.output, report)
        print(json.dumps({"status": report["status"], "objects": len(report["objects"]),
                          "runtime_motion_tested": False, "npc_enabled": False}))
        return 0
    except Exception as error:
        if not args.output.exists():
            write_json(args.output, {"schema": 1, "status": "FAIL", "source_commit": args.source_commit,
                "error_type": type(error).__name__, "error_code": str(error) if isinstance(error, AuditError)
                else "metadata_audit_failed", "runtime_motion_tested": False, "npc_enabled": False,
                "resources": guard.report()})
        raise SystemExit("Public NPC metadata audit stopped; bounded report saved") from None


if __name__ == "__main__":
    raise SystemExit(main())
