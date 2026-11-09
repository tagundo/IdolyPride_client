"""Serve archived game files locally without fetching missing content."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit

from google.protobuf.json_format import ParseDict, ParseError


_LOG = logging.getLogger(__name__)
_RANGE = re.compile(r"bytes=(\d*)-(\d*)\Z")


def prepare_master_tag(schema, tag_path: Path, pack_dir: Path, base_url: str) -> bytes:
    """Validate a MasterTag JSON archive and point its packs at local HTTP files.

    Pack bytes and SQLCipher keys are preserved. ``pack_dir`` must correspond to
    the ``/master/`` directory of the HTTP server. This function never downloads
    content or writes the supplied archive.
    """
    target = urlsplit(base_url)
    if (target.scheme not in ("http", "https") or not target.hostname
            or target.username is not None or target.password is not None
            or target.query or target.fragment or target.path not in ("", "/")):
        raise ValueError("Asset base URL must be an HTTP(S) origin without credentials")
    response = schema.response_type("/api.Master/Get")()
    try:
        value = json.loads(Path(tag_path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError()
        ParseDict(value, response.masterTag)
    except (ValueError, TypeError, AttributeError, ParseError):
        raise ValueError("Invalid MasterTag JSON for supplied schema") from None
    if not response.masterTag.version or not response.masterTag.masterTagPacks:
        raise ValueError("MasterTag must contain a version and at least one pack")
    root = Path(pack_dir).resolve()
    names = set()
    for pack in response.masterTag.masterTagPacks:
        name = pack.fileName
        if (not name or name in (".", "..") or "/" in name or "\\" in name
                or "\x00" in name or name in names):
            raise ValueError("Master pack names must be unique plain filenames")
        names.add(name)
        candidate = (root / name).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise ValueError("A required local master pack is missing or outside its directory")
        if candidate.stat().st_size != pack.fileSize:
            raise ValueError("A local master pack has a different size from its MasterTag")
        pack.downloadUrl = base_url.rstrip("/") + "/master/" + quote(name, safe="")
    return response.SerializeToString()


def _range(value: str, size: int) -> tuple[int, int]:
    match = _RANGE.fullmatch(value)
    if not match or not any(match.groups()) or size == 0:
        raise ValueError("Unsupported byte range")
    left, right = match.groups()
    if not left:
        suffix = int(right)
        if suffix <= 0:
            raise ValueError("Unsatisfiable byte range")
        return max(0, size - suffix), size - 1
    start = int(left)
    end = min(int(right), size - 1) if right else size - 1
    if start >= size or start > end:
        raise ValueError("Unsatisfiable byte range")
    return start, end


def create_asset_server(host: str, port: int, root: Path) -> ThreadingHTTPServer:
    """Create a bound server; caller owns serve_forever/shutdown/server_close.

    Files live under the explicit root. Directory listings and paths resolving
    outside that root, including symlink escapes, are unavailable.
    """
    directory = Path(root).resolve()
    if not directory.is_dir():
        raise ValueError("Asset root must be an existing directory")

    class Handler(BaseHTTPRequestHandler):
        server_version = "IdolyLocalAssets/0.1"

        def log_message(self, _format, *args):
            _LOG.info("%s %r", self.command, urlsplit(self.path).path)

        def do_GET(self):
            self._serve(True)

        def do_HEAD(self):
            self._serve(False)

        def _serve(self, send_body: bool):
            path = unquote(urlsplit(self.path).path)
            parts = path.split("/")
            if any(part in (".", "..") or "\\" in part or "\x00" in part for part in parts):
                self.send_error(404)
                return
            try:
                source = directory.joinpath(*filter(None, parts)).resolve()
                if not source.is_relative_to(directory) or not source.is_file():
                    self.send_error(404)
                    return
                stream = source.open("rb")
            except (OSError, ValueError, RuntimeError):
                self.send_error(404)
                return
            with stream:
                # Use the opened file's identity/size for headers and transfer.
                info = os.fstat(stream.fileno())
                start, end = 0, info.st_size - 1
                status = 200
                if self.headers.get("Range") is not None:
                    try:
                        start, end = _range(self.headers["Range"], info.st_size)
                    except ValueError:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{info.st_size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    status = 206
                length = max(0, end - start + 1)
                self.send_response(status)
                self.send_header("Content-Type", mimetypes.guess_type(source.name)[0]
                                 or "application/octet-stream")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Last-Modified", self.date_time_string(info.st_mtime))
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{info.st_size}")
                self.end_headers()
                if send_body:
                    stream.seek(start)
                    remaining = length
                    while remaining:
                        block = stream.read(min(64 * 1024, remaining))
                        if not block:
                            break
                        self.wfile.write(block)
                        remaining -= len(block)

    return ThreadingHTTPServer((host, port), Handler)
