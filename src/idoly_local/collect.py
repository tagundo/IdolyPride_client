"""Preserve selected read responses using an existing official game session.

No login, token renewal, daily initialization, account creation or automatic retry
is performed. Session metadata stays in memory and is never included in exports.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import ssl
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import grpc
from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError

from . import codec
from .catalog import import_response

OFFICIAL_TARGET = "api.game-idolypride.jp:443"
COLLECT_METHODS = (
    "/api.Master/Get",
    "/api.User/Get",
    "/api.Home/Enter",
    "/api.Dokan/List",
    "/api.Notice/List",
)
_METADATA_KEY = re.compile(r"[0-9a-z_.-]+\Z")
_APPLICATION_CODE = re.compile(r"[0-9]{1,5}\Z")


class CollectorError(RuntimeError):
    """A credential-free, fixed-format error suitable for CLI output."""


def _load_metadata(path: Path) -> list[tuple[str, str]]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise CollectorError("Cannot read session metadata JSON") from None
    if not isinstance(value, dict) or not value:
        raise CollectorError("Session metadata must be a nonempty JSON object")
    for key, content in value.items():
        if not isinstance(key, str) or not isinstance(content, str):
            raise CollectorError("Session metadata keys and values must be strings")
        if not _METADATA_KEY.fullmatch(key) or key.endswith("-bin"):
            raise CollectorError("Session metadata has an invalid gRPC key")
        if any(ord(char) < 32 or ord(char) > 126 for char in content):
            raise CollectorError("Session metadata values must be printable ASCII without newlines")
    if any(not value.get(key, "").strip() for key in ("x-app-version", "x-auth-token", "x-master-version")):
        raise CollectorError("Session metadata requires app version, auth token and master version")
    return list(value.items())


def _application_codes(call) -> list[str]:
    codes = set()
    for key, value in [*(call.initial_metadata() or ()), *(call.trailing_metadata() or ())]:
        if key != "x-error-code":
            continue
        if not isinstance(value, str) or not _APPLICATION_CODE.fullmatch(value):
            codes.add("invalid")
        elif int(value) != 0:
            codes.add(str(int(value)))
    return sorted(codes)


def _failure(method: str, call) -> CollectorError:
    status = call.code()
    # Never include arbitrary remote details or metadata in diagnostics.
    name = status.name if isinstance(status, grpc.StatusCode) else "UNKNOWN"
    codes = _application_codes(call)
    return CollectorError(f"Collection stopped at {method}: status {name}, application codes "
                          + (",".join(codes) if codes else "none"))


def _tls_credentials(roots_file: Path | None):
    try:
        path = roots_file or ssl.get_default_verify_paths().cafile
        roots = Path(path).read_bytes() if path else None
        return grpc.ssl_channel_credentials(root_certificates=roots)
    except (OSError, ValueError):
        raise CollectorError("Cannot load collection TLS roots") from None


def _atomic_private(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".collect-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(contents)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _requests(schema):
    result = []
    for method in COLLECT_METHODS:
        try:
            descriptor = schema.method(method)
            request = schema.request_type(method)()
        except (KeyError, ValueError):
            raise CollectorError(f"Schema is missing preservation RPC {method}") from None
        if descriptor.client_streaming or descriptor.server_streaming:
            raise CollectorError(f"Preservation RPC must be unary: {method}")
        fields = descriptor.input_type.fields_by_name
        if method == "/api.Home/Enter":
            if set(fields) != {"skipUpdate"} or fields["skipUpdate"].type != fields["skipUpdate"].TYPE_BOOL:
                raise CollectorError("Home.Enter schema must expose only the skipUpdate boolean")
            request.skipUpdate = True
        elif fields:
            raise CollectorError(f"Preservation RPC must accept an empty request: {method}")
        result.append((method, codec.encode(request.SerializeToString())))
    return result


def collect_session(schema, metadata_file: Path, output: Path, *,
                    target: str = OFFICIAL_TARGET, roots_file: Path | None = None) -> dict:
    """Capture the fixed read allowlist once, preserving earlier successful files.

    Only the exact official TLS target accepts session credentials. Home.Enter
    uses skipUpdate=true. Cross-day/authentication failures stop collection;
    callers must refresh their session in the original game themselves.
    """
    if target != OFFICIAL_TARGET:
        raise CollectorError("Session collection only supports the official TLS target")
    metadata = _load_metadata(metadata_file)
    requests = _requests(schema)
    credentials = _tls_credentials(roots_file)
    output = Path(output)
    captured = []
    with grpc.secure_channel(target, credentials, options=(("grpc.enable_retries", 0),
                              ("grpc.max_receive_message_length", 17 * 1024 * 1024))) as channel:
        for method, request in requests:
            try:
                raw, call = channel.unary_unary(method).with_call(request, metadata=metadata, timeout=15)
            except grpc.RpcError as error:
                raise _failure(method, error) from None
            if call.code() != grpc.StatusCode.OK or _application_codes(call):
                raise _failure(method, call) from None
            try:
                payload = codec.decode(raw)
                response = schema.response_type(method).FromString(payload)
            except (ValueError, DecodeError):
                raise CollectorError(f"Collection stopped at {method}: malformed response") from None
            master = None
            if method == "/api.Master/Get":
                if not response.HasField("masterTag") or not response.masterTag.version:
                    raise CollectorError("Collection stopped at /api.Master/Get: missing master version")
                master = (json.dumps(MessageToDict(response.masterTag, preserving_proto_field_name=True),
                                     ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            try:
                output.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=output, prefix=".collect-response-", delete=False) as stream:
                    source = Path(stream.name)
                    stream.write(payload)
                try:
                    import_response(source, output / "fixtures", schema, method)
                finally:
                    source.unlink(missing_ok=True)
                if master is not None:
                    _atomic_private(output / "master-tag.json", master)
            except (OSError, ValueError):
                raise CollectorError(f"Collection stopped at {method}: cannot save validated response") from None
            captured.append(method)
    return {"captured": captured}


PUBLIC_MASTER_HOST = "climaster.game-idolypride.jp"


def _public_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname == PUBLIC_MASTER_HOST
                 and parsed.port in (None, 443) and parsed.username is None
                 and parsed.password is None and not parsed.fragment and not parsed.query
                 and parsed.path.startswith("/") and "\\" not in url
                 and all(32 < ord(char) < 127 for char in url))
    except ValueError:
        valid = False
    if not valid:
        raise CollectorError("Master download URL must use the official public HTTPS host")
    return url


class _PublicMasterRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        # Reject a destination before urllib sends a redirected request.
        _public_url(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _master_packs(tag):
    packs, names, types = [], set(), set()
    if not tag.version or not tag.masterTagPacks:
        raise CollectorError("Public Master.Get returned no version or master packs")
    for pack in tag.masterTagPacks:
        name = pack.fileName
        if (not name or name in (".", "..") or "/" in name or "\\" in name
                or any(ord(char) < 32 for char in name) or name in names
                or not pack.type or pack.type in types or pack.fileSize <= 0):
            raise CollectorError("Public Master.Get returned invalid or duplicate master packs")
        _public_url(pack.downloadUrl)
        names.add(name)
        types.add(pack.type)
        identity = [tag.version, pack.type, name, pack.fileSize, pack.cryptoKey, pack.downloadUrl]
        source_hash = hashlib.sha256(json.dumps(identity, ensure_ascii=False,
                                               separators=(",", ":")).encode("utf-8")).hexdigest()
        packs.append({"type": pack.type, "file_name": name, "size": pack.fileSize,
                      "source_sha256": source_hash, "url": pack.downloadUrl})
    return packs


def _download_master_pack(pack, root: Path, roots_file: Path | None) -> dict:
    context = ssl.create_default_context(cafile=str(roots_file) if roots_file is not None else None)
    opener = build_opener(_PublicMasterRedirect(), HTTPSHandler(context=context))
    target = root / pack["file_name"]
    temporary = None
    try:
        request = Request(pack["url"], headers={"User-Agent": "idolypride-local/0.1"})
        with opener.open(request, timeout=30) as response:
            _public_url(response.geturl())
            if response.status != 200:
                raise CollectorError("Public master download returned a non-success HTTP status")
            size, digest = 0, hashlib.sha256()
            with tempfile.NamedTemporaryFile(dir=root, prefix=".master-pack-", delete=False) as stream:
                temporary = Path(stream.name)
                while block := response.read(64 * 1024):
                    size += len(block)
                    if size > pack["size"]:
                        raise CollectorError("Public master download has an unexpected file size")
                    stream.write(block)
                    digest.update(block)
            if size != pack["size"]:
                raise CollectorError("Public master download has an unexpected file size")
        os.replace(temporary, target)
        return {key: pack[key] for key in ("file_name", "size", "source_sha256")} | {"sha256": digest.hexdigest()}
    except (OSError, ValueError, HTTPError, URLError, HTTPException):
        raise CollectorError("Public master download failed; completed files are retained") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def archive_public_master(schema, output: Path, app_version: str = "6.1.1", *,
                          roots_file: Path | None = None, workers: int = 6) -> dict:
    """Archive anonymous Master.Get and its encrypted raw packs, without accounts.

    Every completed file has an observed SHA-256 in archive-report.json. Resume
    checks its source identity, size and content hash; filenames are not hashes.
    HTTP requests inherit the proxy and CA configuration and carry no credentials.
    """
    if (not isinstance(app_version, str) or not app_version.strip()
            or any(ord(char) < 32 or ord(char) > 126 for char in app_version)):
        raise CollectorError("Public master collection requires a printable app version")
    if type(workers) is not int or not 1 <= workers <= 32:
        raise CollectorError("Public master workers must be between 1 and 32")
    method = "/api.Master/Get"
    try:
        descriptor = schema.method(method)
        if descriptor.input_type.fields:
            raise ValueError()
        request = codec.encode(schema.request_type(method)().SerializeToString())
    except (KeyError, ValueError):
        raise CollectorError("Schema must contain the unary empty-request Master.Get RPC") from None
    credentials = _tls_credentials(roots_file)
    with grpc.secure_channel(OFFICIAL_TARGET, credentials,
                            options=(("grpc.enable_retries", 0),
                                     ("grpc.max_receive_message_length", 17 * 1024 * 1024))) as channel:
        try:
            raw, call = channel.unary_unary(method).with_call(
                request, metadata=[("x-app-version", app_version)], timeout=15)
        except grpc.RpcError as error:
            raise _failure(method, error) from None
    if call.code() != grpc.StatusCode.OK or _application_codes(call):
        raise _failure(method, call) from None
    try:
        payload = codec.decode(raw)
        response = schema.response_type(method).FromString(payload)
        if not response.HasField("masterTag"):
            raise ValueError()
    except (ValueError, DecodeError):
        raise CollectorError("Public Master.Get returned a malformed response") from None
    packs = _master_packs(response.masterTag)
    output = Path(output).resolve()
    pack_root = output / "assets" / "master"
    pack_root.mkdir(parents=True, exist_ok=True)
    for pack in packs:
        if not (pack_root / pack["file_name"]).resolve().is_relative_to(pack_root.resolve()):
            raise CollectorError("A master pack destination is outside the archive")
    report_path = output / "archive-report.json"
    try:
        previous = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    if not isinstance(previous, dict) or previous.get("schema_version") != 1 or not isinstance(previous.get("packs"), dict):
        previous = {"packs": {}}
    report = {"schema_version": 1, "master_version": response.masterTag.version,
              "expected_packs": len(packs), "completed_packs": 0, "complete": False, "packs": {}}

    def save_report():
        report["completed_packs"] = len(report["packs"])
        report["complete"] = report["completed_packs"] == len(packs)
        _atomic_private(report_path, (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    _atomic_private(output / "response.pb", payload)
    _atomic_private(output / "master-tag.json", (json.dumps(
        MessageToDict(response.masterTag, preserving_proto_field_name=True),
        ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    pending, reused = [], 0
    for pack in packs:
        entry = previous["packs"].get(pack["type"])
        candidate = pack_root / pack["file_name"]
        identity = {key: pack[key] for key in ("file_name", "size", "source_sha256")}
        if (isinstance(entry, dict) and all(entry.get(key) == value for key, value in identity.items())
                and isinstance(entry.get("sha256"), str) and candidate.is_file()
                and candidate.stat().st_size == pack["size"] and _file_hash(candidate) == entry["sha256"]):
            report["packs"][pack["type"]] = identity | {"sha256": entry["sha256"]}
            candidate.chmod(0o600)
            reused += 1
        else:
            pending.append(pack)
    save_report()
    failed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_download_master_pack, pack, pack_root, roots_file): pack for pack in pending}
        for future in as_completed(futures):
            pack = futures[future]
            try:
                report["packs"][pack["type"]] = future.result()
            except (CollectorError, OSError, ValueError):
                failed += 1
            save_report()
    if failed:
        raise CollectorError(f"Public master archive incomplete ({len(report['packs'])}/{len(packs)} packs); "
                             "validated files are retained for resume")
    return {"master_version": response.masterTag.version, "packs": len(packs), "downloaded": len(pending),
            "reused": reused, "bytes": sum(pack["size"] for pack in packs), "complete": True}
