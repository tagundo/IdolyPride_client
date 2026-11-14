#!/usr/bin/env python3
"""Fetch and verify public build inputs; never bundle the donor Mac executable."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
REPO = "tagundo/IdolyPride_client"
DONOR = {"bytes": 330787485, "sha256": "f40a393ad766ac36035332ba741236eea00da9ba9310d401613f10566037043d"}
DONOR_ROOT = "IdolyPrideLocalServer.app/Contents/Resources/"
CHUNK = 128 * 1024
MAX_JSON = 128 * 1024
HOSTS = {"github.com", "lfs.github.com", "github-cloud.githubusercontent.com", "media.githubusercontent.com", "objects.githubusercontent.com", "github-cloud.s3.amazonaws.com", "release-assets.githubusercontent.com", "files.pythonhosted.org"}


def need(value, message):
    if not value:
        raise ValueError(message)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def approved(url):
    parsed = urlsplit(url)
    need(parsed.scheme == "https" and parsed.hostname in HOSTS and not parsed.username
         and not parsed.password and parsed.port in (None, 443), "Unapproved build input origin")
    return url


def download(url, row, path, *, headers=None):
    need(not path.exists(), "Fresh build input path required")
    opener = build_opener(NoRedirect())
    request_headers = {"Accept-Encoding": "identity", **(headers or {})}
    response = None
    for _ in range(5):
        try:
            response = opener.open(Request(approved(url), headers=request_headers), timeout=90)
            break
        except HTTPError as error:
            need(error.code in (301, 302, 303, 307, 308), "Build input download HTTP failure")
            url = approved(error.headers.get("Location", ""))
            request_headers = {"Accept-Encoding": "identity"}
    need(response is not None, "Build input redirect bound exceeded")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    total = 0
    digest = hashlib.sha256()
    with response, partial.open("xb") as destination:
        while block := response.read(CHUNK):
            total += len(block)
            need(total <= row["bytes"], "Build input exceeds pinned size")
            digest.update(block)
            destination.write(block)
    need(total == row["bytes"] and digest.hexdigest() == row["sha256"], "Build input digest differs")
    partial.rename(path)


def lfs_download(row, path):
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    need(token, "Repository read token required for pinned LFS inputs")
    basic = base64.b64encode(("x-access-token:" + token).encode()).decode()
    raw = json.dumps({"operation": "download", "transfers": ["basic"], "objects": [{"oid": row["sha256"], "size": row["bytes"]}]}).encode()
    request = Request("https://github.com/" + REPO + ".git/info/lfs/objects/batch", data=raw,
                      headers={"Authorization": "Basic " + basic, "Content-Type": "application/vnd.git-lfs+json", "Accept": "application/vnd.git-lfs+json"})
    with build_opener(NoRedirect()).open(request, timeout=60) as response:
        body = response.read(MAX_JSON + 1)
    need(len(body) <= MAX_JSON, "LFS response exceeds bound")
    objects = json.loads(body).get("objects", [])
    need(len(objects) == 1, "LFS object inventory differs")
    obj = objects[0]
    need(obj.get("oid") == row["sha256"] and obj.get("size") == row["bytes"] and not obj.get("error"), "LFS object differs")
    action = obj.get("actions", {}).get("download", {})
    href = approved(action.get("href", ""))
    need(token not in href, "Repository credential in download URL")
    headers = action.get("header", {})
    need(isinstance(headers, dict) and len(headers) <= 16, "Invalid LFS headers")
    for key, value in headers.items():
        need(isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9-]{1,64}", key)
             and key.lower() not in {"host", "cookie", "proxy-authorization"}
             and isinstance(value, str) and len(value) <= 4096 and token not in value
             and all(32 <= ord(c) < 127 for c in value), "Invalid LFS download header")
    download(href, row, path, headers=headers)


def copy_pinned(source, destination, row):
    digest = hashlib.sha256()
    total = 0
    with destination.open("xb") as output:
        while block := source.read(CHUNK):
            total += len(block)
            need(total <= row["bytes"], "Donor member exceeds pinned size")
            digest.update(block)
            output.write(block)
    need(total == row["bytes"] and digest.hexdigest() == row["sha256"], "Donor member digest differs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.absolute()
    need(not output.exists(), "Fresh input directory required")
    output.mkdir(parents=True)
    manifest = json.loads((HERE / "runtime_inputs.json").read_text())
    support = output / manifest["support"]["filename"]
    download(manifest["support"]["url"], manifest["support"], support)
    for row in manifest["pure_wheels"]:
        download(row["url"], row, output / "wheels" / row["filename"])
    base = manifest["inputs"]["base_ipa"]
    lfs_download(base, output / "base.ipa")
    donor = output / "donor-macos.zip"
    lfs_download(DONOR, donor)
    with ZipFile(donor) as archive:
        need(len(set(archive.namelist())) == len(archive.infolist()), "Duplicate donor member")
        for name, key in (("ServerData.zip", "server_data"), ("bundledTranslations.zip", "translations")):
            row = manifest["inputs"][key]
            info = archive.getinfo(DONOR_ROOT + name)
            need(info.file_size == row["bytes"] and not info.flag_bits & 1, "Pinned donor member differs")
            with archive.open(info) as source:
                copy_pinned(source, output / name, row)
    donor.unlink()  # Only this newly downloaded exact donor; no host/private state.
    with ZipFile(output / "base.ipa") as archive:
        name = "Payload/IDOLY PRIDE.app/Frameworks/IdolyPresentation.dylib"
        with archive.open(name) as source:
            copy_pinned(source, output / "IdolyPresentation.dylib", {"bytes": 157520, "sha256": "85a445f71ac59473522aa15e15919efbc351cbbc9d2d5829062a9a22416c9cb5"})
    (output / "fetch-report.json").write_text(json.dumps({"schema": 1, "verified": True, "base_sha256": base["sha256"], "support_sha256": manifest["support"]["sha256"], "donor_sha256": DONOR["sha256"], "Mac_executable_bundled": False}, indent=2) + "\n")
    print("PASS_VERIFIED_IOS_UNIFIED_INPUTS")


if __name__ == "__main__":
    # Remote URLs may carry signed credentials. Do not expose exception reprs.
    try:
        main()
    except Exception as error:
        print("Input preparation failed: " + (str(error) if isinstance(error, ValueError) else type(error).__name__))
        raise SystemExit(1) from None
