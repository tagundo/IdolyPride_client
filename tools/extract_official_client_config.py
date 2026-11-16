#!/usr/bin/env python3
"""Recover public Firebase app settings from SHA-pinned original JP clients.

Run on an isolated CI runner. This reads original app archives and Android SDK
metadata only: no accounts, passwords, tokens, official services or app launch.
Config API keys identify a public client project; they are never written to logs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import plistlib
import re
import stat
import subprocess
import tempfile
from zipfile import ZipFile

BUNDLE_ID = "game.qualiarts.idolypride"
PROJECT_ID = "solis-firebase"
PROJECT_NUMBER = "543065248020"
APP_VERSION = "6.1.1"
PINS = {
    "ios": {"asset_id":725761399, "bytes":146438450,
            "sha256":"33197938a0990b267af2d67c09e9d1123694e28695fc39d9650ca4f6aa661848"},
    "android": {"asset_id":725772331, "bytes":167699540,
                "sha256":"ab3bd9186ccc2659f91fcf2a48e25b591e94b4209c505f2ca401be8b22e5de36"},
}
APK_SHAS = frozenset(("3d54e05f897bfb54716a0ad645562955ceb0081cead696cb29595941ac08faa9",
                     "b91a53316f230b48e290145f9625ca5caf5d40180c3de6ab1dce5171912aba67"))
CERT_SHA256 = "06cede031cd36c1986928fb5a9339c859253c07e06aff6137503d8385d3291b5"
MAX_MEMBERS = 8192
MAX_EXPANDED = 1024 * 1024 * 1024
MAX_METADATA = 1024 * 1024
MAX_TOOL_OUTPUT = 32 * 1024 * 1024
_REQUIRED_ANDROID = frozenset(("google_api_key", "google_app_id", "project_id", "gcm_defaultSenderId"))


class ConfigExtractionError(ValueError):
    """Fixed codes only: no source contents, credentials, or subprocess output."""
    def __init__(self, code):
        self.code = code
        super().__init__("Public client configuration extraction stopped: " + code)


def need(value, code):
    if not value:
        raise ConfigExtractionError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def verify_source(path, platform):
    path = Path(path)
    before = path.lstat()
    need(stat.S_ISREG(before.st_mode), "source_not_regular")
    pin = PINS[platform]
    need(before.st_size == pin["bytes"], "source_size_mismatch")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.lstat()
    need((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)
         == (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns), "source_changed")
    need(digest == pin["sha256"], "source_sha_mismatch")
    return dict(pin)


def archive_inventory(archive):
    infos = archive.infolist()
    need(0 < len(infos) <= MAX_MEMBERS, "archive_inventory_invalid")
    seen = set()
    total = 0
    for info in infos:
        path = PurePosixPath(info.filename)
        need(info.filename not in seen and not path.is_absolute() and ".." not in path.parts
             and "\\" not in info.filename and not info.flag_bits & 1, "archive_member_invalid")
        seen.add(info.filename)
        mode = info.external_attr >> 16
        need(not stat.S_ISLNK(mode), "archive_member_invalid")
        total += info.file_size
        need(total <= MAX_EXPANDED, "archive_expanded_limit")
    return infos


def read_metadata(archive, name):
    info = archive.getinfo(name)
    need(0 < info.file_size <= MAX_METADATA, "metadata_size_invalid")
    raw = archive.read(info)
    need(len(raw) == info.file_size, "metadata_size_invalid")
    return raw, {"member":name, "bytes":len(raw), "sha256":sha(raw)}


def validate_config(value, platform):
    need(type(value) is dict and platform in ("ios", "android"), "config_invalid")
    required = {"api_key", "project_id", "project_number", "google_app_id", "bundle_id", "app_version"}
    need(set(value) == required | ({"certificate_sha1"} if platform == "android" else set()), "config_fields_invalid")
    need(all(type(v) is str and 0 < len(v) <= 256 for v in value.values()), "config_values_invalid")
    need(value["bundle_id"] == BUNDLE_ID and value["project_id"] == PROJECT_ID
         and value["project_number"] == PROJECT_NUMBER and value["app_version"] == APP_VERSION,
         "config_scope_mismatch")
    need(re.fullmatch(r"AIza[A-Za-z0-9_-]{20,80}", value["api_key"]) is not None, "api_key_invalid")
    need(re.fullmatch(r"1:" + PROJECT_NUMBER + ":" + platform + r":[a-f0-9]{16,64}",
                      value["google_app_id"]) is not None, "google_app_id_invalid")
    if platform == "android":
        need(re.fullmatch(r"[A-F0-9]{40}", value["certificate_sha1"]) is not None, "certificate_invalid")
    return dict(value)


def parse_ios_config(google_raw, info_raw):
    try:
        google, info = plistlib.loads(google_raw), plistlib.loads(info_raw)
    except Exception:
        raise ConfigExtractionError("plist_invalid") from None
    need(type(google) is dict and type(info) is dict, "plist_invalid")
    need(info.get("CFBundleIdentifier") == BUNDLE_ID, "config_scope_mismatch")
    fields = {"api_key":google.get("API_KEY"), "project_id":google.get("PROJECT_ID"),
        "project_number":google.get("GCM_SENDER_ID"), "google_app_id":google.get("GOOGLE_APP_ID"),
        "bundle_id":google.get("BUNDLE_ID"), "app_version":info.get("CFBundleShortVersionString")}
    return validate_config(fields, "ios")


def extract_ios(path):
    source = verify_source(path, "ios")
    with ZipFile(path) as archive:
        infos = archive_inventory(archive)
        candidates = [i.filename for i in infos if re.fullmatch(r"Payload/[^/]+\.app/GoogleService-Info\.plist", i.filename)]
        need(len(candidates) == 1, "ios_google_config_ambiguous")
        google_name = candidates[0]
        info_name = google_name.rsplit("/",1)[0] + "/Info.plist"
        need(info_name in {i.filename for i in infos}, "ios_info_missing")
        google, google_proof = read_metadata(archive, google_name)
        info, info_proof = read_metadata(archive, info_name)
        config = parse_ios_config(google, info)
    need(verify_source(path, "ios") == source, "source_changed")
    return config, {"source":source, "members":[google_proof,info_proof],
                    "identity_scope_verified":True, "app_executed":False}


def parse_android_badging(raw):
    need(type(raw) is str and len(raw) <= MAX_TOOL_OUTPUT, "badging_invalid")
    lines = raw.splitlines()
    need(lines and lines[0].startswith("package: "), "badging_invalid")
    fields = re.findall(r"([A-Za-z][A-Za-z0-9_-]*)='([^']*)'", lines[0][9:])
    need(len(dict(fields)) == len(fields), "badging_invalid")
    value = dict(fields)
    need(value.get("name") == BUNDLE_ID and value.get("versionName") == APP_VERSION
         and value.get("versionCode") == "414", "config_scope_mismatch")
    return value


def parse_android_certificate(raw):
    need(type(raw) is str and len(raw) <= MAX_METADATA, "certificate_invalid")
    sha1 = re.findall(r"^Signer #([0-9]+) certificate SHA-1 digest: ([A-Fa-f0-9]{40})$", raw, re.M)
    sha256 = re.findall(r"^Signer #([0-9]+) certificate SHA-256 digest: ([A-Fa-f0-9]{64})$", raw, re.M)
    need(len(sha1) == len(sha256) == 1 and sha1[0][0] == sha256[0][0] == "1"
         and sha256[0][1].lower() == CERT_SHA256, "certificate_invalid")
    return sha1[0][1].upper()


def parse_android_resources(raw):
    need(type(raw) is str and len(raw) <= MAX_TOOL_OUTPUT, "resources_invalid")
    values = {}
    current = None
    for line in raw.splitlines():
        resource = re.match(r"\s*resource\s+0x[0-9a-fA-F]+\s+(?:[^\s:]+:)?string/([^\s:]+)(?:\s|:|$)", line)
        if resource:
            current = resource.group(1) if resource.group(1) in _REQUIRED_ANDROID else None
            continue
        if re.match(r"\s*(?:resource|type|Package)\s", line):
            current = None
        if current:
            entry = re.match(r'\s*\(([^)]*)\)\s+("(?:[^"\\]|\\.)*")\s*$', line)
            if entry:
                # Firebase IDs must not differ across locale/device configs.
                try:
                    value = json.loads(entry.group(2))
                except Exception:
                    raise ConfigExtractionError("resources_invalid") from None
                need(type(value) is str and (current not in values or values[current] == value),
                     "resources_ambiguous")
                values[current] = value
    need(set(values) == _REQUIRED_ANDROID, "resources_missing")
    return values


def run_tool(args, maximum=MAX_TOOL_OUTPUT):
    # Captured bytes are never printed, including on a tool error. The source
    # and executable names are fixed by this caller, not supplied app metadata.
    try:
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            result = subprocess.run([str(a) for a in args], stdout=out, stderr=err, timeout=120, check=False)
            need(result.returncode == 0, "android_tool_failed")
            need(out.tell() <= maximum and err.tell() <= maximum, "android_tool_output_limit")
            out.seek(0)
            return out.read(maximum + 1).decode("utf-8", errors="strict")
    except ConfigExtractionError:
        raise
    except Exception:
        raise ConfigExtractionError("android_tool_failed") from None


def extract_android(path, build_tools):
    source = verify_source(path, "android")
    build_tools = Path(build_tools)
    need(build_tools.name == "34.0.0" and all((build_tools/name).is_file() for name in ("aapt2","apksigner")),
         "android_sdk_invalid")
    records = []
    found = []
    with tempfile.TemporaryDirectory(prefix="idoly-public-config-") as temporary, ZipFile(path) as archive:
        infos = archive_inventory(archive)
        members = [i for i in infos if i.filename.endswith(".apk")]
        need(len(members) == 2 and len({PurePosixPath(i.filename).name for i in members}) == 2,
             "android_apk_inventory_invalid")
        hashes = set()
        for index, info in enumerate(members):
            need(0 < info.file_size <= 200 * 1024 * 1024, "android_apk_size_invalid")
            target = Path(temporary)/(str(index) + ".apk")
            digest = hashlib.sha256()
            copied = 0
            with archive.open(info) as incoming, target.open("xb") as outgoing:
                while block := incoming.read(256*1024):
                    copied += len(block)
                    need(copied <= info.file_size, "android_apk_size_invalid")
                    digest.update(block)
                    outgoing.write(block)
            need(copied == info.file_size and digest.hexdigest() in APK_SHAS, "android_apk_sha_mismatch")
            hashes.add(digest.hexdigest())
            signature = run_tool([build_tools/"apksigner","verify","--verbose","--print-certs",target], MAX_METADATA)
            certificate = parse_android_certificate(signature)
            badging_raw = run_tool([build_tools/"aapt2","dump","badging",target])
            badging = parse_android_badging(badging_raw)
            record = {"member":info.filename,"bytes":copied,"sha256":digest.hexdigest(),
                      "certificate_sha256":CERT_SHA256,"certificate_sha1":certificate,
                      "badging_sha256":sha(badging_raw.encode()),"signature_output_sha256":sha(signature.encode())}
            if "split" not in badging:
                resources_raw = run_tool([build_tools/"aapt2","dump","resources",target])
                resources = parse_android_resources(resources_raw)
                config = validate_config({"api_key":resources["google_api_key"],
                    "google_app_id":resources["google_app_id"],"project_id":resources["project_id"],
                    "project_number":resources["gcm_defaultSenderId"],"bundle_id":badging["name"],
                    "app_version":badging["versionName"],"certificate_sha1":certificate}, "android")
                record["resources_dump_sha256"] = sha(resources_raw.encode())
                found.append(config)
            records.append(record)
        need(hashes == APK_SHAS and len(found) == 1, "android_base_ambiguous")
    need(verify_source(path, "android") == source, "source_changed")
    return found[0], {"source":source,"members":records,"android_build_tools":"34.0.0",
                      "identity_scope_verified":True,"app_executed":False}


def extract(ipa, xapk, build_tools, output):
    output = Path(output)
    need(not output.exists() and not output.is_symlink(), "output_exists")
    ios, ios_proof = extract_ios(ipa)
    android, android_proof = extract_android(xapk, build_tools)
    result = {"schema":1,"scope":"public-original-jp-client-configuration",
              "platforms":{"ios":ios,"android":android},
              "provenance":{"ios":ios_proof,"android":android_proof},
              "official_authentication_attempted":False,"private_account_data_read":False}
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("x",encoding="utf-8") as stream:
        stream.write(json.dumps(result,ensure_ascii=True,indent=2,sort_keys=True)+"\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ipa",type=Path,required=True)
    parser.add_argument("--xapk",type=Path,required=True)
    parser.add_argument("--build-tools",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args(argv)
    try:
        extract(args.ipa,args.xapk,args.build_tools,args.output)
    except ConfigExtractionError as error:
        parser.exit(1,str(error)+"\n")
    except Exception:
        parser.exit(1,"Public client configuration extraction stopped: extraction_failed\n")
    print("Verified original iOS/Android public client configuration; no official authentication attempted.")


if __name__ == "__main__":
    main()
