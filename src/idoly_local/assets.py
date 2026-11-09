"""Serve archived game files locally without fetching missing content."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import time
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


def create_asset_server(host: str, port: int, root: Path, *, diagnostics=None,
                        transfer_callback=None) -> ThreadingHTTPServer:
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
            if self.path == "/diagnostics/status" and diagnostics is not None:
                if not self._loopback():
                    self._json(403, {"error": "loopback_required"})
                    return
                self._json(200, diagnostics.status())
                return
            self._serve(True)

        def do_HEAD(self):
            self._serve(False)

        def _loopback(self):
            try:
                return ipaddress.ip_address(self.client_address[0]).is_loopback
            except ValueError:
                return False

        def _json(self, status, value):
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _transfer(self, path, phase, sent, total, status):
            if transfer_callback is not None:
                try:
                    transfer_callback({"transfer_id": id(self), "path": path,
                                       "phase": phase, "sent_bytes": sent,
                                       "total_bytes": total, "http_status": status})
                except Exception:
                    pass  # A status observer cannot interrupt file serving.

        def do_POST(self):
            if self.path != "/diagnostics/client" or diagnostics is None:
                self._json(404, {"error": "not_found"})
                return
            if not self._loopback():
                self._json(403, {"error": "loopback_required"})
                return
            if self.headers.get("Transfer-Encoding") is not None:
                self._json(400, {"error": "content_length_required"})
                return
            size = self.headers.get("Content-Length", "")
            if not re.fullmatch(r"[0-9]{1,8}", size):
                self._json(411, {"error": "content_length_required"})
                return
            size = int(size)
            if not 0 < size <= 32768:
                self._json(413, {"error": "diagnostics_size_limit"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self._json(415, {"error": "json_required"})
                return
            previous_timeout = self.connection.gettimeout()
            try:
                self.connection.settimeout(3)
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError("Incomplete request")
                result = diagnostics.receive(raw)
            except (ValueError, TimeoutError, OSError):
                self._json(400, {"error": "invalid_client_diagnostics"})
                return
            finally:
                self.connection.settimeout(previous_timeout)
            self._json(200, result)

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
                    sent, last_update = 0, time.monotonic()
                    self._transfer(path, "started", 0, length, status)
                    try:
                        while remaining:
                            block = stream.read(min(64 * 1024, remaining))
                            if not block:
                                raise OSError("File ended before advertised length")
                            self.wfile.write(block)
                            sent += len(block)
                            remaining -= len(block)
                            if time.monotonic() - last_update >= 0.5:
                                self._transfer(path, "progress", sent, length, status)
                                last_update = time.monotonic()
                    except OSError:
                        self._transfer(path, "failed", sent, length, status)
                        return
                    self._transfer(path, "completed", sent, length, status)

    return ThreadingHTTPServer((host, port), Handler)
