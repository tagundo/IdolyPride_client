"""Bounded loopback commands and streaming exports for the resource library."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

PREFIX = "/client/resources"


def _object(pairs):
    row = {}
    for key, value in pairs:
        if key in row:
            raise ValueError("Duplicate resource command key")
        row[key] = value
    return row


def _selection(row, *, required=True):
    if set(row) - {"platform", "kind"} or (required and "platform" not in row):
        raise ValueError("Resource selection fields")
    platform, kind = row.get("platform"), row.get("kind", "all")
    if platform not in ("android", "ios") or kind not in ("all", "assetbundle", "resources"):
        raise ValueError("Resource selection")
    return platform, kind


def _failure(handler, error):
    # Report fixed codes only; never exception text, CDN URLs or local paths.
    code = getattr(error, "code", "invalid_resource_command")
    allowed = {"busy", "unavailable", "catalog_unavailable", "invalid_catalog", "closed", "not_prepared",
               "cancelled", "unknown_job", "invalid_selection", "cache_io", "insufficient_space",
               "export_failed", "import_failed"}
    code = code if code in allowed else "invalid_resource_command"
    status = (507 if code == "insufficient_space" else 500 if code in ("cache_io", "export_failed", "import_failed")
              else 409 if code in ("busy", "closed", "not_prepared")
              else 404 if code in ("unavailable", "catalog_unavailable", "unknown_job") else 400)
    handler._json(status, {"error": code})


def handles(path):
    return unquote(urlsplit(path).path).startswith(PREFIX)


def get(handler, library):
    if not handles(handler.path):
        return False
    parts = urlsplit(handler.path)
    if library is None or parts.path not in (PREFIX, PREFIX + "/export") or parts.fragment:
        handler._json(404, {"error": "not_found"})
        return True
    if not handler._loopback():
        handler._json(403, {"error": "loopback_required"})
        return True
    try:
        values = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True,
                          max_num_fields=2)
        if any(len(value) != 1 for value in values.values()):
            raise ValueError("Duplicate resource selection")
        row = {key: value[0] for key, value in values.items()}
        if parts.path == PREFIX:
            if set(row) - {"platform"}:
                raise ValueError("Resource status fields")
            if row:
                platform, _ = _selection(row)
                library.catalog_summary(platform)
            handler._json(200, library.status())
            return True
        platform, kind = _selection(row)
        job = library.prepare_export(platform, kind=kind)
        filename = job["filename"]
        if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", filename):
            library.cancel(job["job_id"])
            raise ValueError("Resource export filename")
    except (ValueError, RuntimeError, OSError) as error:
        _failure(handler, error)
        return True
    previous, restore_timeout = None, False
    try:
        previous = handler.connection.gettimeout()
        restore_timeout = True
        handler.connection.settimeout(30)
        handler.send_response(200)
        handler.send_header("Content-Type", "application/zip")
        handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        handler.send_header("X-Idoly-Resource-Job", job["job_id"])
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.close_connection = True
        library.write_export(job["job_id"], handler.wfile)
    except (ValueError, RuntimeError, OSError):
        # Headers are already sent; a failed stream must remain incomplete.
        library.cancel(job["job_id"])
    finally:
        if restore_timeout:
            try:
                handler.connection.settimeout(previous)
            except OSError:
                pass
    return True


def post(handler, library):
    if not handles(handler.path):
        return False
    if library is None or handler.path not in (PREFIX + "/download", PREFIX + "/cancel"):
        handler._json(404, {"error": "not_found"})
        return True
    if not handler._loopback():
        handler._json(403, {"error": "loopback_required"})
        return True
    if handler.headers.get("Transfer-Encoding") is not None:
        handler._json(400, {"error": "content_length_required"})
        return True
    length = handler.headers.get("Content-Length", "")
    if not re.fullmatch(r"[0-9]{1,5}", length):
        handler._json(411, {"error": "content_length_required"})
        return True
    if not 0 < int(length) <= 4096:
        handler._json(413, {"error": "resource_command_size_limit"})
        return True
    if handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
        handler._json(415, {"error": "json_required"})
        return True
    previous = handler.connection.gettimeout()
    try:
        handler.connection.settimeout(3)
        raw = handler.rfile.read(int(length))
        if len(raw) != int(length):
            raise ValueError("Incomplete resource command")
        row = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_object,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
        if not isinstance(row, dict):
            raise ValueError("Resource command object required")
        if handler.path.endswith("/download"):
            platform, kind = _selection(row)
            result = library.start_download(platform, kind=kind)
        else:
            if set(row) != {"job_id"} or not isinstance(row["job_id"], str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]{1,64}", row["job_id"]):
                raise ValueError("Resource cancellation fields")
            result = library.cancel(row["job_id"])
    except (ValueError, RuntimeError, OSError) as error:
        _failure(handler, error)
    else:
        handler._json(202, result)
    finally:
        handler.connection.settimeout(previous)
    return True
