#!/usr/bin/env python3
"""Prepare a small pinned public Love reference; no game/authentication calls.

PyYAML is a remote preparation-only dependency. Runtime loaders use JSON only.
Original master tables, ADV scripts, media and account data are not downloaded.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import ssl
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

COMMIT = "9b67c06939403d7035e1795745f791340a775868"
REPOSITORY = "vertesan/solis-server"
BASE = "https://raw.githubusercontent.com/" + REPOSITORY + "/" + COMMIT + "/"
LICENSE_SHA256 = "20b067f86de375aae6db0f283ab2e65de24d537733b89bd58432c101259d84cf"
IDS = ("love-23-0514", "love-23-1114", "love-24-0517", "love-24-1114", "love-26-0313", "love-extra-25-0426")
# Exact raw UTF-8 bytes at the public reference commit, not mutable branch URLs.
PINS = {
    "catalogdata/love-23-0514.yaml": (764, "00df4d9d1e992b39f8214c41f2b5e0ac99ad19518a94dfb8a00adc3dffe6764f"),
    "catalogdata/love-23-1114.yaml": (1081, "63fb9d2f866cfed8c19383387c5bebb3faf3f6aa1c914800bce1195406281b50"),
    "catalogdata/love-24-0517.yaml": (1152, "c770f8e3e5b0822c0eb598df2ff14575205513f61ef1c70cd926cb68b9fc9931"),
    "catalogdata/love-24-1114.yaml": (1073, "aa2c8387a49eb4b316468c433b8783156f91a08e6f32de867ac61c99cc09afa6"),
    "catalogdata/love-26-0313.yaml": (1076, "3cf2f60e67305a27297607f42939c479552d77aa632efa792d49b73c0ab6c657"),
    "catalogdata/love-extra-25-0426.yaml": (1551, "de9f2be024db7de2c9ee51e479e25477b07e10f4bdb73339d26708562e5fe762"),
    "routedata/love-23-0514.yaml": (5400, "a69d3a658e16cc29bf4f37e2a11bb0cae849d1ca63cb2f49b4fad5229352ad92"),
    "routedata/love-23-1114.yaml": (5002, "d0f22a83ea41ebe5a3eed46a3ce2ceec9017b7d7042c9922695e65a2b8bf99e5"),
    "routedata/love-24-0517.yaml": (5308, "a743c994e43886a7c4edeba48c3ac314a0ef82a3aacc2790b487732f2db8f0be"),
    "routedata/love-24-1114.yaml": (6726, "ee0aa3b6e2b8cd01f2dd07f85638699b47443bc031d0d8a32e5bad3c45e770e9"),
    "routedata/love-26-0313.yaml": (5132, "18fc8398c828af4dd189c553688ded74ba650a4051fde3ab0bc290e5ab2937a3"),
    "routedata/love-extra-25-0426.yaml": (11027, "ce828add5105c83925ecfb782d92c9635655c36d4a10d7854824f04b9f5881e5"),
}
PREFIX = "internal/makino/moshikoi/"
MAX_INPUT = 16384
MAX_OUTPUT = 128 * 1024


def need(value, code):
    if not value:
        raise ValueError(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise ValueError("love_reference_redirect_rejected")


def download(relative, maximum):
    need(relative in {PREFIX + key for key in PINS} | {"LICENSE"}, "love_reference_source_rejected")
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    try:
        with opener.open(Request(BASE + relative, headers={"Accept": "text/plain"}), timeout=25) as response:
            need(response.status == 200 and response.geturl() == BASE + relative, "love_reference_http_rejected")
            raw = response.read(maximum + 1)
        need(len(raw) <= maximum, "love_reference_input_too_large")
        return raw
    except ValueError:
        raise
    except Exception:
        raise ValueError("love_reference_download_failed") from None


def canonical_tree(value, active=None, count=None, depth=0):
    """Expand aliases, reject cycles/non-JSON YAML types and key collisions."""
    active = set() if active is None else active
    count = [0] if count is None else count
    count[0] += 1
    need(count[0] <= 20000 and depth <= 32, "love_reference_structure_bound")
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        need(abs(value) <= 2**53 - 1, "love_reference_integer_bound")
        return value
    if type(value) is str:
        need(len(value.encode("utf-8")) <= 4096 and "\x00" not in value, "love_reference_string_bound")
        return value
    need(type(value) in (list, dict), "love_reference_non_json_type")
    need(id(value) not in active and len(value) <= 512, "love_reference_cycle_or_collection_bound")
    active.add(id(value))
    try:
        if type(value) is list:
            return [canonical_tree(row, active, count, depth + 1) for row in value]
        result = {}
        for key, child in value.items():
            need(type(key) in (str, int), "love_reference_key_type")
            if type(key) is int:
                need(0 <= key <= 10000, "love_reference_key_bound")
            key = str(key)
            need(0 < len(key) <= 256 and key not in result, "love_reference_key_collision")
            result[key] = canonical_tree(child, active, count, depth + 1)
        return result
    finally:
        active.remove(id(value))


def prepare(fetch=download):
    import yaml
    need(yaml.__version__ == "6.0.3", "love_reference_yaml_version")
    license_raw = fetch("LICENSE", 65536)
    need(hashlib.sha256(license_raw).hexdigest() == LICENSE_SHA256, "love_reference_license_changed")
    sources, events, total = {}, {}, 0
    for relative, (size, digest) in sorted(PINS.items()):
        raw = fetch(PREFIX + relative, MAX_INPUT)
        need(type(raw) is bytes and len(raw) == size and hashlib.sha256(raw).hexdigest() == digest,
             "love_reference_source_changed")
        total += len(raw)
        need(total <= 64 * 1024, "love_reference_total_bound")
        try:
            text = raw.decode("utf-8")
            decoded = canonical_tree(yaml.safe_load(text))
        except ValueError:
            raise
        except Exception:
            raise ValueError("love_reference_yaml_invalid") from None
        event_id = Path(relative).stem
        need(event_id in IDS and type(decoded) is dict and decoded.get("loveId") == event_id,
             "love_reference_identity_changed")
        comments = []
        for line in text.splitlines():
            if not line.startswith("#"):
                break
            comments.append(line[1:].strip())
        need(len(comments) <= 16 and sum(len(row) for row in comments) <= 4096, "love_reference_notice_bound")
        sources[relative] = {"bytes": size, "sha256": digest, "header_comments": comments}
        section = "catalog" if relative.startswith("catalogdata/") else "route"
        events.setdefault(event_id, {})[section] = decoded
    need(set(events) == set(IDS) and len(sources) == 12, "love_reference_event_set_changed")
    for event_id, event in events.items():
        need(set(event) == {"catalog", "route"}, "love_reference_sections_missing")
        catalog, route = event["catalog"], event["route"]
        need(type(catalog.get("name")) is str and bool(catalog["name"])
             and type(catalog.get("description")) is str and type(catalog.get("startTime")) is int
             and "endTime" not in catalog, "love_reference_catalog_invalid")
        need(set(route) == {"loveId", "endingConditions", "endings", "episodes"}
             and type(route["episodes"]) is dict and 1 <= len(route["episodes"]) <= 32
             and type(route["endings"]) is list and 1 <= len(route["endings"]) <= 32,
             "love_reference_routes_invalid")
    result = {"schema": 1, "reference": {"repository": REPOSITORY, "commit": COMMIT,
        "license_name": "GNU Affero General Public License version 3", "license_sha256": LICENSE_SHA256,
        "license_url": BASE + "LICENSE", "sources": sources},
        "policy": {"dynamic_settings": "reference_capture_claim", "routes": "inferred_reference_not_official_capture",
            "score_bonus_grants": False, "official_end_times": "unknown",
            "game_data_notice": "Original game text/assets remain owned by their respective right holders. Reference licensing does not relicense original game assets. No ADV/media/account data is included."},
        "events": events}
    raw = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    need(len(raw) <= MAX_OUTPUT, "love_reference_output_bound")
    report = {"schema": 1, "status": "PASS", "reference_commit": COMMIT, "source_count": len(sources),
        "total_source_bytes": total, "output_bytes": len(raw), "output_sha256": hashlib.sha256(raw).hexdigest(),
        "event_ids": sorted(events), "license_sha256": LICENSE_SHA256,
        "preparation_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "yaml_version": yaml.__version__, "official_authentication_performed": False}
    return raw, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    need(args.output != args.report and not args.output.exists() and not args.report.exists(), "love_reference_fresh_output_required")
    raw, report = prepare()
    with args.output.open("xb") as stream:
        stream.write(raw)
    with args.report.open("xb") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    print(json.dumps({"status": "PASS", "bytes": len(raw), "sha256": report["output_sha256"], "sources": 12}))


if __name__ == "__main__":
    main()
