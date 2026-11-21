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
import selectors
import stat
import subprocess
import threading
import time
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
RELEASE_ASSET_ID = 725761399
RELEASE_ASSET_NAME = "game.qualiarts.idolypride-6.1.1-Decrypted.ipa"
RELEASE_TIMEOUT = 180
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


def copy_pinned(source, destination, row, *, on_create=None):
    digest = hashlib.sha256()
    total = 0
    with destination.open("xb") as output:
        if on_create is not None:
            on_create(os.fstat(output.fileno()))
        while block := source.read(CHUNK):
            total += len(block)
            need(total <= row["bytes"], "Donor member exceeds pinned size")
            digest.update(block)
            output.write(block)
    need(total == row["bytes"] and digest.hexdigest() == row["sha256"], "Donor member digest differs")


def _pinned_row(row, *, maximum):
    need(isinstance(row, dict) and type(row.get("bytes")) is int and 0 < row["bytes"] <= maximum
         and isinstance(row.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]),
         "Pinned input metadata invalid")


def _fresh(path):
    need(not path.exists() and not path.is_symlink(), "Fresh build input path required")


def _identity(info):
    return info.st_dev, info.st_ino


def _retire_partial(path, identity):
    try:
        current = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISREG(current.st_mode) and _identity(current) == identity:
        path.unlink()


def _publish_partial(partial, destination, identity):
    info = partial.lstat()
    need(stat.S_ISREG(info.st_mode) and _identity(info) == identity, "Owned input partial changed")
    # A hard link publishes the verified file without replacing a destination
    # created while the download was running. Both paths share one directory.
    try:
        os.link(partial, destination, follow_symlinks=False)
    except FileExistsError:
        raise ValueError("Fresh build input path required") from None
    partial.unlink()


def _gh_api_stream(accept, consume, maximum, *, timeout=RELEASE_TIMEOUT):
    need(type(timeout) in (int, float) and 0 < timeout <= RELEASE_TIMEOUT,
         "Release asset timeout invalid")
    need(os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"), "Repository read token required")
    endpoint = "repos/" + REPO + "/releases/assets/" + str(RELEASE_ASSET_ID)
    command = ["gh", "api", "--hostname", "github.com", endpoint, "-H", "Accept: " + accept]
    # Credentials stay in gh's inherited environment. Neither command arguments
    # nor diagnostics contain a token or a signed redirect URL.
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
    expired = threading.Event()
    def stop_own_process():
        expired.set()
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
    timer = threading.Timer(timeout, stop_own_process)
    timer.daemon = True
    deadline = time.monotonic() + timeout
    timer.start()
    total = 0
    try:
        os.set_blocking(process.stdout.fileno(), False)
        with selectors.DefaultSelector() as incoming:
            incoming.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                need(not expired.is_set() and remaining > 0, "Release asset request timed out")
                if not incoming.select(min(1, remaining)):
                    continue
                try:
                    block = os.read(process.stdout.fileno(), CHUNK)
                except BlockingIOError:
                    continue
                if not block:
                    break
                total += len(block)
                need(total <= maximum, "Release asset response exceeds bound")
                consume(block)
        try:
            code = process.wait(timeout=max(0.01, min(5, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            raise ValueError("Release asset request timed out") from None
        need(not expired.is_set(), "Release asset request timed out")
        need(code == 0, "Release asset request failed")
    finally:
        timer.cancel()
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=5)
        finally:
            process.stdout.close()


def release_asset_download(row, destination):
    _pinned_row(row, maximum=256 * 1024 * 1024)
    need(type(row.get("asset_id")) is int and row["asset_id"] == RELEASE_ASSET_ID
         and row.get("filename") == RELEASE_ASSET_NAME, "Pinned release asset differs")
    destination = Path(destination)
    partial = destination.with_name(destination.name + ".partial")
    _fresh(destination); _fresh(partial)
    metadata = bytearray()
    _gh_api_stream("application/vnd.github+json", metadata.extend, MAX_JSON)
    try:
        value = json.loads(metadata)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("Release asset metadata invalid") from None
    need(isinstance(value, dict) and type(value.get("id")) is int and value["id"] == row["asset_id"]
         and value.get("name") == row["filename"] and type(value.get("size")) is int
         and value["size"] == row["bytes"] and value.get("state") == "uploaded",
         "Release asset metadata differs")
    destination.parent.mkdir(parents=True, exist_ok=True)
    identity = None
    try:
        with partial.open("xb") as output:
            identity = _identity(os.fstat(output.fileno()))
            digest = hashlib.sha256()
            total = 0
            def receive(block):
                nonlocal total
                total += len(block)
                digest.update(block)
                output.write(block)
            _gh_api_stream("application/octet-stream", receive, row["bytes"])
        need(total == row["bytes"] and digest.hexdigest() == row["sha256"], "Release asset digest differs")
        _publish_partial(partial, destination, identity)
    finally:
        if identity is not None:
            _retire_partial(partial, identity)


def copy_local_pinned(filename, destination, row):
    _pinned_row(row, maximum=8 * 1024 * 1024)
    need(filename in ("en.csv", "en-report.json") and row.get("filename") == filename,
         "Pinned English input filename differs")
    folder = HERE / "client-language-inputs"
    folder_info = folder.lstat()
    source = folder / filename
    before = source.lstat()
    need(stat.S_ISDIR(folder_info.st_mode) and not stat.S_ISLNK(folder_info.st_mode)
         and stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode)
         and before.st_size == row["bytes"], "Pinned English input must be a regular file")
    destination = Path(destination)
    partial = destination.with_name(destination.name + ".partial")
    _fresh(destination); _fresh(partial)
    destination.parent.mkdir(parents=True, exist_ok=True)
    identity = None
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as incoming:
        opened = os.fstat(incoming.fileno())
        need(stat.S_ISREG(opened.st_mode) and (_identity(before), before.st_size, before.st_mtime_ns)
             == (_identity(opened), opened.st_size, opened.st_mtime_ns), "Pinned English input changed")
        try:
            # copy_pinned keeps the same streaming size/hash admission as donor
            # members, but this local wrapper publishes only a verified partial.
            def created(info):
                nonlocal identity
                identity = _identity(info)
            copy_pinned(incoming, partial, row, on_create=created)
            after = os.fstat(incoming.fileno())
            need((_identity(opened), opened.st_size, opened.st_mtime_ns)
                 == (_identity(after), after.st_size, after.st_mtime_ns), "Pinned English input changed")
            _publish_partial(partial, destination, identity)
        finally:
            if identity is not None:
                _retire_partial(partial, identity)


def fetch_korean_source(destination):
    import importlib.util
    spec = importlib.util.spec_from_file_location("ios_translation_source", HERE.parent / "tools/refresh_korean_translation_bundle.py")
    korean = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(korean)
    return korean.fetch_source(destination)


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
    stock = manifest["inputs"]["stock_ipa"]
    release_asset_download(stock, output / "stock.ipa")
    for key, filename in (("english_ui", "en.csv"), ("english_ui_proof", "en-report.json")):
        copy_local_pinned(filename, output / filename, manifest["inputs"][key])
    donor = output / "donor-macos.zip"
    lfs_download(DONOR, donor)
    with ZipFile(donor) as archive:
        need(len(set(archive.namelist())) == len(archive.infolist()), "Duplicate donor member")
        for name, key in (("ServerData.zip", "server_data"), ("bundledTranslations.zip", "translations_base")):
            row = manifest["inputs"][key]
            info = archive.getinfo(DONOR_ROOT + name)
            need(info.file_size == row["bytes"] and not info.flag_bits & 1, "Pinned donor member differs")
            with archive.open(info) as source:
                copy_pinned(source, output / ("bundledTranslations.base.zip" if key == "translations_base" else name), row)
    donor.unlink()  # Only this newly downloaded exact donor; no host/private state.
    korean_source = fetch_korean_source(output / "korean-translations-source.zip")
    with ZipFile(output / "base.ipa") as archive:
        name = "Payload/IDOLY PRIDE.app/Frameworks/IdolyPresentation.dylib"
        with archive.open(name) as source:
            copy_pinned(source, output / "IdolyPresentation.dylib", {"bytes": 157520, "sha256": "85a445f71ac59473522aa15e15919efbc351cbbc9d2d5829062a9a22416c9cb5"})
    (output / "fetch-report.json").write_text(json.dumps({"schema": 1, "verified": True, "base_sha256": base["sha256"], "stock_ipa_sha256": stock["sha256"], "english_ui_sha256": manifest["inputs"]["english_ui"]["sha256"], "english_ui_proof_sha256": manifest["inputs"]["english_ui_proof"]["sha256"], "support_sha256": manifest["support"]["sha256"], "donor_sha256": DONOR["sha256"], "korean_translation_source": korean_source, "Mac_executable_bundled": False}, indent=2) + "\n")
    print("PASS_VERIFIED_IOS_UNIFIED_INPUTS")


if __name__ == "__main__":
    # Remote URLs may carry signed credentials. Do not expose exception reprs.
    try:
        main()
    except Exception as error:
        print("Input preparation failed: " + (str(error) if isinstance(error, ValueError) else type(error).__name__))
        raise SystemExit(1) from None
