"""Validated, local response fixtures keyed by RPC and optional request digest."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from google.protobuf.message import DecodeError


_METHOD = re.compile(r"/[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*/[A-Za-z_][A-Za-z_0-9]*\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _method_descriptor(schema, method: str):
    if not isinstance(method, str) or not _METHOD.fullmatch(method):
        raise ValueError("Fixture method must be a complete /package.Service/Method path")
    if method.split("/")[1].split(".")[-1] == "Auth":
        raise ValueError("Auth responses cannot be stored as fixtures")
    try:
        descriptor = schema.method(method)
    except (KeyError, ValueError) as error:
        raise ValueError(f"Unknown fixture method: {method}") from error
    if descriptor is None:
        raise ValueError(f"Unknown fixture method: {method}")
    if descriptor.client_streaming or descriptor.server_streaming:
        raise ValueError("Fixtures support unary RPC methods only")
    return descriptor


def _validate_response(schema, method: str, data: bytes) -> None:
    _method_descriptor(schema, method)
    try:
        schema.response_type(method).FromString(data)
    except DecodeError as error:
        raise ValueError(f"Malformed protobuf fixture for {method}") from error


def _contained_path(directory: Path, filename: str) -> Path:
    if not isinstance(filename, str) or not filename or "\\" in filename or "\0" in filename:
        raise ValueError("Fixture file must be a relative path")
    relative = Path(filename)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Fixture file must stay inside its fixture directory")
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory):
        raise ValueError("Fixture file must stay inside its fixture directory")
    return path


def _read_manifest(directory: Path) -> dict:
    path = _contained_path(directory, "manifest.json")
    if not path.exists():
        return {"schema_version": 1, "responses": []}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("Invalid fixture manifest JSON") from error
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ValueError("Fixture manifest requires schema_version 1")
    if not isinstance(manifest.get("responses"), list):
        raise ValueError("Fixture manifest responses must be a list")
    return manifest


def _request_key(entry: dict) -> str | None:
    if "request_sha256" not in entry:
        return None
    digest = entry["request_sha256"]
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise ValueError("request_sha256 must be a lowercase SHA-256 digest")
    return digest


class FixtureStore:
    """Load and validate fixtures before serving any of their contents."""

    def __init__(self, directory: Path, schema):
        self.directory = Path(directory).resolve()
        self.schema = schema
        self._responses: dict[tuple[str, str | None], bytes] = {}
        self.manifest = _read_manifest(self.directory)
        for entry in self.manifest["responses"]:
            if not isinstance(entry, dict):
                raise ValueError("Fixture response entries must be objects")
            method = entry.get("method")
            _method_descriptor(schema, method)
            key = (method, _request_key(entry))
            if key in self._responses:
                raise ValueError(f"Duplicate fixture route: {method}")
            path = _contained_path(self.directory, entry.get("file"))
            data = path.read_bytes()
            _validate_response(schema, method, data)
            self._responses[key] = data

    def get(self, method: str, request_bytes: bytes) -> bytes | None:
        digest = hashlib.sha256(request_bytes).hexdigest()
        key = (method, digest)
        if key in self._responses:
            return self._responses[key]
        return self._responses.get((method, None))

    def variants(self, method: str) -> tuple[bytes, ...]:
        """Return every validated response for a method without choosing a request.

        Request digests alone cannot establish which capture is current. Callers
        interpreting shared account permissions must reconcile all variants.
        The tuple and its byte values expose no mutable store state.
        """
        return tuple(data for (path, _request), data in self._responses.items() if path == method)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".fixture-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def import_response(source: Path, output: Path, schema, method: str,
                    request: Path | None = None, wire: bool = False) -> Path:
    """Import a response; request contents are represented only by their digest.

    ``wire`` accepts the encrypted application message inside a gRPC frame,
    without the five-byte gRPC framing header. Requests, when supplied, are
    decrypted protobuf bytes regardless of the response's input format.
    """
    _method_descriptor(schema, method)
    data = Path(source).read_bytes()
    if wire:
        from .codec import decode

        data = decode(data)
    _validate_response(schema, method, data)
    directory = Path(output).resolve()
    store = FixtureStore(directory, schema)
    request_digest = hashlib.sha256(Path(request).read_bytes()).hexdigest() if request is not None else None
    service, rpc = method[1:].split("/")
    filename = f"responses/{service}-{rpc}-{hashlib.sha256(data).hexdigest()}.pb"
    target = _contained_path(directory, filename)
    entries = [entry for entry in store.manifest["responses"]
               if (entry["method"], _request_key(entry)) != (method, request_digest)]
    entry = {"method": method, "file": filename}
    if request_digest is not None:
        entry["request_sha256"] = request_digest
    entries.append(entry)
    manifest = {"schema_version": 1, "responses": entries}
    # Content-addressed files keep the previous manifest valid until the final
    # atomic replace, even if writing a new manifest fails or is interrupted.
    _atomic_write(target, data)
    _atomic_write(_contained_path(directory, "manifest.json"),
                  (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return target
