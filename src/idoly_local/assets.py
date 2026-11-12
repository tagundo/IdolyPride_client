"""Serve archived game files and an optional verified Octo resource gateway."""
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
_RUNTIME_DIAGNOSTICS_PATH = "/diagnostics/runtime"
_MAX_RUNTIME_DIAGNOSTICS_BYTES = 1024 * 1024


def _render_probe_route(path):
    # Static-file serving collapses empty path components. Reserve those aliases
    # too, while the handler below still accepts only the literal canonical URL.
    decoded = unquote(urlsplit(path).path)
    return "/".join(filter(None, decoded.split("/"))).startswith("client/render-probe")


def select_master_tag(tag_path: Path, *, media_mode=False) -> Path:
    """Select the separate client-facing outfit catalog before opening a profile.

    The ordinary archive and backend JSON catalog retain their original version.
    Media packs are prepared by the public-data builder, not rebuilt on a phone.
    """
    if type(media_mode) is not bool:
        raise ValueError("Media mode must be an explicit boolean")
    selected = Path(tag_path)
    if media_mode:
        selected = selected.with_name("media-master-tag.json")
        if not selected.is_file():
            raise ValueError("Media outfit master is missing; update the bundled server data")
    return selected


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
                        transfer_callback=None, octo=None,
                        runtime_status_callback=None, presentation=None, playback=None,
                        render_probe=None) -> ThreadingHTTPServer:
    """Create a bound server; caller owns serve_forever/shutdown/server_close.

    Files live under the explicit root. Directory listings and paths resolving
    outside that root, including symlink escapes, are unavailable. An explicit
    ``octo`` gateway owns its reserved API/resource routes and transfer observer;
    its downloads never enter the master-file transfer callback. A caller may
    bind port zero, set ``server.octo_gateway`` using the bound port, and then
    start serving. Replacing the gateway after serving starts is not supported.
    ``runtime_status_callback`` optionally exposes a safe snapshot over the
    loopback-only GET endpoint ``/diagnostics/runtime``. It receives no input;
    its JSON response is limited to 1 MiB and never cached.
    """
    if runtime_status_callback is not None and not callable(runtime_status_callback):
        raise ValueError("Runtime status callback must be callable")
    directory = Path(root).resolve()
    if not directory.is_dir():
        raise ValueError("Asset root must be an existing directory")

    class Handler(BaseHTTPRequestHandler):
        server_version = "IdolyLocalAssets/0.1"

        def log_message(self, _format, *args):
            _LOG.info("%s %r", self.command, urlsplit(self.path).path)

        def do_GET(self):
            if _render_probe_route(self.path):
                if self.path != "/client/render-probe" or render_probe is None:
                    self._json(404, {"error": "not_found"})
                elif not self._loopback():
                    self._json(403, {"error": "loopback_required"})
                else:
                    self._json(200, render_probe.status())
                return
            if unquote(urlsplit(self.path).path).startswith("/client/playback"):
                if self.path != "/client/playback" or playback is None:
                    self._json(404, {"error": "not_found"})
                elif not self._loopback():
                    self._json(403, {"error": "loopback_required"})
                else:
                    self._json(200, playback.settings())
                return
            if unquote(urlsplit(self.path).path).startswith("/client/presentation"):
                if self.path != "/client/presentation" or presentation is None:
                    self._json(404, {"error": "not_found"})
                elif not self._loopback():
                    self._json(403, {"error": "loopback_required"})
                else:
                    self._json(200, presentation.settings())
                return
            if unquote(urlsplit(self.path).path) == _RUNTIME_DIAGNOSTICS_PATH:
                if self.path != _RUNTIME_DIAGNOSTICS_PATH or runtime_status_callback is None:
                    self._json(404, {"error": "not_found"})
                    return
                if not self._loopback():
                    self._json(403, {"error": "loopback_required"})
                    return
                self._runtime_status()
                return
            if self.path == "/diagnostics/status" and diagnostics is not None:
                if not self._loopback():
                    self._json(403, {"error": "loopback_required"})
                    return
                self._json(200, diagnostics.status())
                return
            gateway = self.server.octo_gateway
            if gateway is not None and gateway.handles(self.path):
                gateway.serve(self, send_body=True)
                return
            self._serve(True)

        def do_HEAD(self):
            if _render_probe_route(self.path):
                self._json(404, {"error": "not_found"})
                return
            if unquote(urlsplit(self.path).path).startswith("/client/playback"):
                self._json(404, {"error": "not_found"})
                return
            if unquote(urlsplit(self.path).path).startswith("/client/presentation"):
                self._json(404, {"error": "not_found"})
                return
            if unquote(urlsplit(self.path).path) == _RUNTIME_DIAGNOSTICS_PATH:
                self._json(404, {"error": "not_found"})
                return
            gateway = self.server.octo_gateway
            if gateway is not None and gateway.handles(self.path):
                gateway.serve(self, send_body=False)
                return
            self._serve(False)

        def _loopback(self):
            try:
                return ipaddress.ip_address(self.client_address[0]).is_loopback
            except ValueError:
                return False

        def _json(self, status, value):
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._json_body(status, body)

        def _json_body(self, status, body):
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _runtime_status(self):
            # Only a trusted, zero-argument observer is called. Encode before
            # sending headers so failures cannot leak exception text or produce
            # a successful but truncated response. No request fields select
            # profiles, files, authentication metadata or executable actions.
            try:
                value = runtime_status_callback()
                if not isinstance(value, dict):
                    raise ValueError("Runtime snapshot must be an object")
                body = bytearray()
                encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                for chunk in encoder.iterencode(value):
                    encoded = chunk.encode("utf-8")
                    if len(body) + len(encoded) > _MAX_RUNTIME_DIAGNOSTICS_BYTES:
                        raise ValueError("Runtime snapshot exceeds response limit")
                    body.extend(encoded)
            except Exception:
                self._json(503, {"error": "runtime_diagnostics_unavailable"})
                return
            self._json_body(200, body)

        def _transfer(self, path, phase, sent, total, status):
            if transfer_callback is not None:
                try:
                    transfer_callback({"transfer_id": id(self), "path": path,
                                       "phase": phase, "sent_bytes": sent,
                                       "total_bytes": total, "http_status": status})
                except Exception:
                    pass  # A status observer cannot interrupt file serving.

        def do_POST(self):
            visual = self.path == "/client/presentation/status" and presentation is not None
            playback_report = self.path == "/client/playback/status" and playback is not None
            probe_report = self.path == "/client/render-probe" and render_probe is not None
            if not visual and not playback_report and not probe_report and (self.path != "/diagnostics/client" or diagnostics is None):
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
            if not 0 < size <= (8191 if probe_report else 8192 if visual or playback_report else 32768):
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
                receiver = render_probe if probe_report else playback if playback_report else presentation if visual else diagnostics
                result = receiver.receive(raw)
            except (ValueError, TimeoutError, OSError):
                self._json(400, {"error": "invalid_render_probe" if probe_report else
                                       "invalid_playback_status" if playback_report else
                                       "invalid_presentation_status" if visual else "invalid_client_diagnostics"})
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

    server = ThreadingHTTPServer((host, port), Handler)
    server.octo_gateway = octo
    return server
