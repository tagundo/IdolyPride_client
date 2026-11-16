#!/usr/bin/env python3
"""Compare anonymous public master candidates without updating runtime data.

Run remotely after the existing account-free archive-master command. Only a
bounded ID/name/hash proof is written. Raw packs remain in the remote job;
no authentication, account, catalog replacement, or release is performed here.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
BASE_BYTES = 191343014
BASE_SHA256 = "37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"
BASE_VERSION = "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"
DESCRIPTOR_SHA256 = "c82cee62abdca7144d11e710a6f773211464a89d2ddede207999a0a5e7aec8ad"
TABLES = ("Card", "Costume", "Character", "Hair")
MAX_PROOF, MAX_METADATA, MAX_TABLE = 512 * 1024, 4 * 1024 * 1024, 32 * 1024 * 1024
MAX_PACKS, MAX_PACK, MAX_PACK_TOTAL = 512, 64 * 1024 * 1024, 512 * 1024 * 1024
DETAIL_BUDGET, DETAIL_LIMIT = 256 * 1024, 128
ERROR_CODES = frozenset(("anonymous_public_master_unavailable", "baseline_pin_differs", "descriptor_pin_differs",
    "candidate_archive_invalid", "candidate_pack_invalid", "candidate_schema_unsupported", "row_contract_invalid",
    "proof_bound", "comparison_failed"))


class AuditError(ValueError):
    def __init__(self, code):
        self.code = code if code in ERROR_CODES else "comparison_failed"
        super().__init__(self.code)


def need(value, code):
    if not value:
        raise AuditError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(65536):
            value.update(block)
    return value.hexdigest()


def object_pairs(pairs):
    value = {}
    for key, item in pairs:
        need(key not in value, "candidate_archive_invalid")
        value[key] = item
    return value


def decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=object_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(AuditError("candidate_archive_invalid")))
    except (UnicodeError, ValueError, RecursionError):
        raise AuditError("candidate_archive_invalid") from None


def read(path, maximum):
    path = Path(path)
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and not path.is_symlink() and 0 < info.st_size <= maximum,
         "candidate_archive_invalid")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    need(len(raw) == info.st_size, "candidate_archive_invalid")
    return raw


def member(archive, name, maximum):
    matches = [info for info in archive.infolist() if info.filename == name]
    need(len(matches) == 1 and 0 < matches[0].file_size <= maximum and not matches[0].flag_bits & 1
         and not stat.S_ISLNK(matches[0].external_attr >> 16), "baseline_pin_differs")
    return archive.read(matches[0])


def row_index(rows):
    need(type(rows) is list and len(rows) <= 200000, "row_contract_invalid")
    result = {}
    for row in rows:
        need(type(row) is dict, "row_contract_invalid")
        identity = row.get("id")
        need(type(identity) is str and 0 < len(identity.encode()) <= 256
             and not any(ord(char) < 32 for char in identity) and identity not in result,
             "row_contract_invalid")
        name = row.get("name", "")
        need(type(name) is str and len(name.encode()) <= 8192, "row_contract_invalid")
        result[identity] = {"id": identity, "name": name, "row_sha256": hashlib.sha256(canonical(row)).hexdigest()}
    return result


def display_name(value):
    # The exact full row is represented by its hash. Only the small display
    # label is projected; no dialogue or other row fields are exported.
    return " ".join(value.split()).encode()[:1024].decode("utf-8", errors="ignore")


def compare_rows(before, after, budget):
    old, new = row_index(before), row_index(after)
    added, removed = sorted(new.keys() - old.keys()), sorted(old.keys() - new.keys())
    changed = sorted(key for key in old.keys() & new.keys() if old[key]["row_sha256"] != new[key]["row_sha256"])
    result = {"baseline_count": len(old), "candidate_count": len(new), "added_count": len(added),
        "removed_count": len(removed), "changed_count": len(changed), "unchanged_count": len(old.keys() & new.keys()) - len(changed),
        "baseline_rows_sha256": hashlib.sha256(canonical({key: old[key]["row_sha256"] for key in sorted(old)})).hexdigest(),
        "candidate_rows_sha256": hashlib.sha256(canonical({key: new[key]["row_sha256"] for key in sorted(new)})).hexdigest(),
        "known_schema_fields_only": True, "added": [], "removed": [], "changed": [], "details_truncated": False}
    for kind, identities in (("added", added), ("removed", removed), ("changed", changed)):
        for key in identities:
            if kind == "changed":
                row = {"id": key, "baseline_name": display_name(old[key]["name"]), "candidate_name": display_name(new[key]["name"]),
                       "baseline_row_sha256": old[key]["row_sha256"], "candidate_row_sha256": new[key]["row_sha256"]}
            else:
                record = new[key] if kind == "added" else old[key]
                row = {"id": key, "name": display_name(record["name"]), "row_sha256": record["row_sha256"]}
            size = len(canonical(row))
            if len(result[kind]) >= DETAIL_LIMIT or budget[0] < size:
                result["details_truncated"] = True
                continue
            result[kind].append(row)
            budget[0] -= size
    return result


def compare_packs(before, after):
    fields = ("file_name", "size", "sha256")
    old, new = before["packs"], after["packs"]
    added, removed = sorted(new.keys() - old.keys()), sorted(old.keys() - new.keys())
    changed = sorted(key for key in old.keys() & new.keys() if any(old[key].get(f) != new[key].get(f) for f in fields))
    return {"baseline_count": len(old), "candidate_count": len(new), "added_types": added, "removed_types": removed,
        "unchanged_count": len(old.keys() & new.keys()) - len(changed), "changed_count": len(changed),
        "changed": [{"type": key, "baseline_bytes": old[key]["size"], "candidate_bytes": new[key]["size"],
                     "baseline_sha256": old[key]["sha256"], "candidate_sha256": new[key]["sha256"]} for key in changed]}


def validate_candidate(schema, candidate):
    from google.protobuf.json_format import ParseDict
    tag = schema.response_type("/api.Master/Get")().masterTag
    report = decode(read(candidate / "archive-report.json", MAX_METADATA))
    ParseDict(decode(read(candidate / "master-tag.json", MAX_METADATA)), tag)
    need(type(report) is dict and report.get("complete") is True and report.get("master_version") == tag.version
         and bool(tag.version) and 0 < len(tag.masterTagPacks) <= MAX_PACKS
         and report.get("expected_packs") == report.get("completed_packs") == len(tag.masterTagPacks)
         and type(report.get("packs")) is dict and len(report["packs"]) == len(tag.masterTagPacks), "candidate_archive_invalid")
    root = candidate / "assets/master"
    seen, total, packs = set(), 0, {}
    for pack in tag.masterTagPacks:
        name = pack.fileName
        need(name and "/" not in name and "\\" not in name and name not in (".", "..")
             and pack.type not in seen and pack.type in report["packs"]
             and 0 < pack.fileSize <= MAX_PACK, "candidate_pack_invalid")
        seen.add(pack.type); total += pack.fileSize
        need(total <= MAX_PACK_TOTAL, "candidate_pack_invalid")
        path = root / name; record = report["packs"][pack.type]
        need(type(record) is dict and record.get("file_name") == name and record.get("size") == pack.fileSize
             and path.is_file() and not path.is_symlink() and path.stat().st_size == pack.fileSize
             and sha(path) == record.get("sha256"), "candidate_pack_invalid")
        packs[pack.type] = pack
    need(set(TABLES) <= set(packs), "candidate_schema_unsupported")
    return tag, report, packs


def audit(base, candidate, descriptor):
    need(base.is_file() and not base.is_symlink() and base.stat().st_size == BASE_BYTES and sha(base) == BASE_SHA256,
         "baseline_pin_differs")
    need(descriptor.is_file() and sha(descriptor) == DESCRIPTOR_SHA256, "descriptor_pin_differs")
    sys.path.insert(0, str(ROOT / "src"))
    from idoly_local.schema import Schema
    from sqlcipher3 import dbapi2
    spec = importlib.util.spec_from_file_location("public_master_decode_only", ROOT / "tools/build_server_payload.py")
    builder = importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    schema = Schema.from_descriptor_set(descriptor)
    tag, report, packs = validate_candidate(schema, candidate)
    budget = [DETAIL_BUDGET]
    with ZipFile(base) as archive:
        baseline = decode(member(archive, "data/original-master/archive-report.json", MAX_METADATA))
        need(baseline.get("complete") is True and baseline.get("master_version") == BASE_VERSION,
             "baseline_pin_differs")
        tables = {}
        for table in TABLES:
            before = decode(member(archive, "data/master-json/" + table + ".json", MAX_TABLE))
            after = builder.decode_master_table(schema, dbapi2, candidate / "assets/master", packs[table], table)
            tables[table] = compare_rows(before, after, budget)
    return {"baseline": {"server_data": {"bytes": BASE_BYTES, "sha256": BASE_SHA256},
                "master_version": BASE_VERSION, "pack_count": len(baseline["packs"])},
            "candidate": {"master_version": tag.version, "pack_count": len(report["packs"]),
                "archive_complete": True, "original_master_tag_sha256": sha(candidate / "master-tag.json")},
            "version_changed": tag.version != BASE_VERSION, "packs": compare_packs(baseline, report), "tables": tables}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-zip", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--collection-failed", action="store_true")
    args = parser.parse_args()
    need(re.fullmatch(r"[0-9a-f]{40}", args.source_commit) is not None, "comparison_failed")
    need(not args.output.exists() and not args.output.is_symlink(), "comparison_failed")
    result = {"schema": 1, "status": "FAIL", "scope": "anonymous-official-master-comparison",
        "checked_at": datetime.now(timezone.utc).isoformat(), "source_commit": args.source_commit,
        "app_version": "6.1.1", "tables_requested": list(TABLES), "production_data_changed": False,
        "account_authentication_performed": False, "raw_packs_uploaded": False,
        "comparison_policy": {"protobuf_schema": "original-6.1.1-known-fields", "row_hash": "canonical-json-sha256",
            "display_names": "whitespace-normalized-and-utf8-bounded", "name_max_bytes": 1024,
            "detail_limit_per_change_kind": DETAIL_LIMIT, "total_detail_budget_bytes": DETAIL_BUDGET},
        "source_files": {name: sha(ROOT / name) for name in
            ("tools/audit_public_master_freshness.py", ".github/workflows/audit-public-master-freshness.yml", "src/idoly_local/collect.py")}}
    try:
        if args.collection_failed:
            raise AuditError("anonymous_public_master_unavailable")
        result.update(audit(args.base_zip, args.candidate_root, args.descriptor), status="PASS")
    except Exception as error:
        result["error_code"] = error.code if isinstance(error, AuditError) else "comparison_failed"
    raw = canonical(result) + b"\n"
    if len(raw) > MAX_PROOF:
        result = {key: result[key] for key in ("schema", "scope", "checked_at", "source_commit", "app_version",
            "tables_requested", "production_data_changed", "account_authentication_performed", "raw_packs_uploaded", "source_files")}
        result.update(status="FAIL", error_code="proof_bound")
        raw = canonical(result) + b"\n"
    need(len(raw) <= MAX_PROOF, "proof_bound")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"status": result["status"], "error_code": result.get("error_code"),
        "version_changed": result.get("version_changed"), "proof_bytes": len(raw),
        "proof_sha256": hashlib.sha256(raw).hexdigest()}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
