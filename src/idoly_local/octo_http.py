"""HTTP boundary for archived Octo manifests and verified resource bytes.

The manifest owns the complete route whitelist. The cache owns retrieval and
verification before an object is served. GET, HEAD and ranges expose those
original bytes; neither a successful response nor a transfer callback asserts
that the game has loaded an asset or completed a download category.
"""
from __future__ import annotations

import json
import hashlib
import os
import threading
import time
from urllib.parse import unquote, urlsplit

from .assets import _range
from .octo_cache import OctoCacheError, OctoCacheMiss
from .octo_manifest import OctoManifestError, OctoRequestError


class OctoGateway:
    """Optional GET/HEAD gateway supplied to ``create_asset_server``.

    ``transfer_callback`` observes only bytes in local HTTP response bodies.
    Upstream cache download progress belongs to ``OctoCache(on_event=...)`` and
    must be labelled separately. A HEAD may fetch a missing object when the
    cache explicitly allows downloads, but it sends no object response bytes.
    """

    def __init__(self, manifest, cache, *, transfer_callback=None, translation_layer=None,
                 request_callback=None):
        if transfer_callback is not None and not callable(transfer_callback):
            raise ValueError("Octo transfer observer must be callable")
        if request_callback is not None and not callable(request_callback):
            raise ValueError("Octo request observer must be callable")
        self.manifest, self.cache = manifest, cache
        self.transfer_callback = transfer_callback
        self.translation_layer = translation_layer
        self.request_callback = request_callback
        self._request_lock = threading.Lock()
        self._request_sequence = 0
        self._closed = threading.Event()

    def close(self):
        """Reject new work and cancel cache retrievals before listener shutdown."""
        self._closed.set()
        self.cache.close()
        if self.translation_layer is not None:
            self.translation_layer.close()

    @staticmethod
    def handles(target):
        # Reserve encoded variants too, so malformed Octo paths cannot fall
        # through to the generic static-file handler. Validators receive the
        # original target and accept only canonical request paths.
        try:
            path = unquote(urlsplit(target).path)
        except (ValueError, TypeError):
            return False
        return path in ("/octo", "/v2") or path.startswith(("/octo/", "/v2/"))

    def _notify(self, handler, path, kind, phase, sent, total, status, *, object_size=None):
        if self.transfer_callback is None:
            return
        event = {"source": "octo", "kind": kind, "transfer_id": id(handler),
                 "path": path, "phase": phase, "sent_bytes": sent,
                 "total_bytes": total, "http_status": status}
        if object_size is not None:
            event["object_bytes"] = object_size
        try:
            self.transfer_callback(event)
        except Exception:
            pass  # An observer cannot change asset serving or verification.

    def _request(self, state, phase, *, status=0, error=None, cause=None):
        """Observe request boundaries separately from response-body byte events.

        No request headers, raw target, query string or client key is exposed.
        Object names are added only after the manifest resolves a known row.
        """
        state.update(phase=phase, http_status=status, error_code=error, cause_code=cause)
        if self.request_callback is not None:
            try:
                self.request_callback(dict(state))
            except Exception:
                pass  # A diagnostic observer never owns an HTTP operation.

    @staticmethod
    def _error(handler, status, code, send_body):
        body = json.dumps({"error": code}, separators=(",", ":")).encode("ascii")
        try:
            handler.send_response(status)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(body)))
            handler.send_header("Cache-Control", "no-store")
            handler.end_headers()
            if send_body:
                handler.wfile.write(body)
        except OSError:
            pass  # The requesting client may already have disconnected.

    def serve(self, handler, *, send_body):
        """Serve one already-dispatched request from BaseHTTPRequestHandler."""
        target = handler.path
        try:
            path = urlsplit(target).path
        except (TypeError, ValueError):
            path = ""
        with self._request_lock:
            self._request_sequence = min(self._request_sequence + 1, 2**63 - 1)
            identity = self._request_sequence
        state = {"source": "octo_request", "request_id": identity, "method": "GET" if send_body else "HEAD",
                 "kind": "manifest" if path == "/v2" or path.startswith("/v2/") else "object",
                 "route_fingerprint": hashlib.sha256(path.encode("utf-8", "replace")).hexdigest()[:16],
                 "object_name": None, "cache_key": None}
        self._request(state, "received")
        try:
            self._serve(handler, send_body=send_body, state=state)
        finally:
            if state["phase"] not in ("completed", "failed"):
                self._request(state, "failed", status=state["http_status"], error="request_aborted")

    def _serve(self, handler, *, send_body, state):
        if self._closed.is_set():
            self._request(state, "failed", status=503, error="octo_gateway_closed")
            self._error(handler, 503, "octo_gateway_closed", send_body)
            return
        target = handler.path
        try:
            self._request(state, "resolving")
            if urlsplit(target).path.startswith("/v2/") or urlsplit(target).path == "/v2":
                body = self.manifest.manifest_response(target, handler.headers)
                self._request(state, "sending", status=200)
                success = self._manifest(handler, body, send_body)
                self._request(state, "completed" if success else "failed", status=200,
                              error=None if success else "client_disconnected")
                return
            record = self.manifest.lookup_object(target)
        except OctoRequestError as error:
            status = error.status if error.status in (400, 403, 404, 409) else 400
            code = {400: "octo_invalid_request", 403: "octo_forbidden",
                    404: "octo_not_found", 409: "octo_revision_unavailable"}[status]
            self._request(state, "failed", status=status, error=code)
            self._error(handler, status, code, send_body)
            return
        except OctoManifestError:
            self._request(state, "failed", status=502, error="octo_manifest_unavailable")
            self._error(handler, 502, "octo_manifest_unavailable", send_body)
            return

        # The friendly name comes from the trusted manifest, never the URL.
        state.update(object_name="".join(c for c in record.name[:160] if c.isprintable()) or None,
                     cache_key=record.cache_key)
        self._request(state, "waiting_cache")
        start, end, status = 0, record.size - 1, 200
        ranges = handler.headers.get_all("Range", [])
        if ranges:
            try:
                if len(ranges) != 1:
                    raise ValueError("Multiple resource range headers are unsupported")
                start, end = _range(ranges[0], record.size)
            except ValueError:
                # Manifest sizes are authoritative; reject an impossible
                # range before any cache miss can trigger upstream work.
                self._request(state, "failed", status=416, error="octo_invalid_range")
                handler.send_response(416)
                handler.send_header("Content-Range", f"bytes */{record.size}")
                handler.send_header("Content-Length", "0")
                handler.end_headers()
                return
            status = 206
        response_started = False
        try:
            with self.cache.open_verified(record) as stream:
                info = os.fstat(stream.fileno())
                if info.st_size != record.size:
                    self._notify(handler, target, "object", "failed", 0, record.size, 502,
                                 object_size=record.size)
                    response_started = True
                    self._request(state, "failed", status=502, error="octo_cache_invalid")
                    self._error(handler, 502, "octo_cache_invalid", send_body)
                    return
                response_started = True
                self._request(state, "sending", status=status)
                success = self._object(handler, stream, record, start, end, status, send_body)
                self._request(state, "completed" if success else "failed", status=status,
                              error=None if success else "client_disconnected")
        except OctoCacheMiss:
            if response_started:
                return  # A read-only stream close cannot change a committed response.
            self._notify(handler, target, "object", "failed", 0, record.size, 503,
                         object_size=record.size)
            self._request(state, "failed", status=503, error="octo_cache_miss")
            self._error(handler, 503, "octo_cache_miss", send_body)
        except (OctoCacheError, OSError, ValueError) as error:
            if response_started:
                return
            unavailable = 503 if getattr(error, "code", None) == "cache_closed" else 502
            self._notify(handler, target, "object", "failed", 0, record.size, unavailable,
                         object_size=record.size)
            self._request(state, "failed", status=unavailable, error="octo_resource_unavailable",
                          cause=error.code if isinstance(error, OctoCacheError) else None)
            self._error(handler, unavailable, "octo_resource_unavailable", send_body)

    def _manifest(self, handler, body, send_body):
        handler.send_response(200)
        handler.send_header("Content-Type", "application/x-protobuf")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Vary", "Accept, X-OCTO-KEY")
        sent = 0
        try:
            handler.end_headers()
            if not send_body:
                return True
            self._notify(handler, handler.path, "manifest", "started", 0, len(body), 200)
            for offset in range(0, len(body), 64 * 1024):
                block = body[offset:offset + 64 * 1024]
                handler.wfile.write(block)
                sent += len(block)
        except OSError:
            if send_body:
                self._notify(handler, handler.path, "manifest", "failed", sent, len(body), 200)
            return False
        self._notify(handler, handler.path, "manifest", "completed", sent, len(body), 200)
        return True

    def _object(self, handler, stream, record, start, end, status, send_body):
        length = max(0, end - start + 1)
        handler.send_response(status)
        handler.send_header("Content-Type", "application/octet-stream")
        handler.send_header("Content-Length", str(length))
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("ETag", '"' + record.md5 + '"')
        handler.send_header("Cache-Control", "public, max-age=31536000, immutable")
        if status == 206:
            handler.send_header("Content-Range", f"bytes {start}-{end}/{record.size}")
        remaining, sent, last_update = length, 0, time.monotonic()
        try:
            handler.end_headers()
            if not send_body:
                return True
            stream.seek(start)
            self._notify(handler, handler.path, "object", "started", 0, length, status,
                         object_size=record.size)
            while remaining:
                block = stream.read(min(64 * 1024, remaining))
                if not block:
                    raise OSError("Verified resource ended before its response length")
                handler.wfile.write(block)
                sent += len(block)
                remaining -= len(block)
                if time.monotonic() - last_update >= 0.5:
                    self._notify(handler, handler.path, "object", "progress", sent, length, status,
                                 object_size=record.size)
                    last_update = time.monotonic()
        except OSError:
            if send_body:
                self._notify(handler, handler.path, "object", "failed", sent, length, status,
                             object_size=record.size)
            return False
        self._notify(handler, handler.path, "object", "completed", sent, length, status,
                     object_size=record.size)
        return True
