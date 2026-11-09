#!/usr/bin/env python3
"""Archive anonymous title-screen terms and public help responses for offline use.

Only Rule(1..7) and Help/Faq/Tips(1..3) are requested. Account recovery, login,
Firebase, session metadata and token refresh are outside this tool's scope.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import grpc
from google.protobuf.message import DecodeError

from idoly_local import codec
from idoly_local.catalog import import_response
from idoly_local.collect import (CollectorError, OFFICIAL_TARGET, _application_codes,
                                _failure, _tls_credentials)
from idoly_local.schema import Schema

RULE = "/api.Master/Rule"
HELP = "/api.Master/GetHelpCategory"
PUBLIC_REQUESTS = ((RULE, "ruleType", tuple(range(1, 8))), (HELP, "helpType", (1, 2, 3)))


def archive_public_text(schema, output: Path, app_version: str = "6.1.1") -> dict:
    if (not isinstance(app_version, str) or not app_version.strip()
            or any(ord(char) < 32 or ord(char) > 126 for char in app_version)):
        raise CollectorError("Public text collection requires a printable app version")
    requests = []
    for method, field, values in PUBLIC_REQUESTS:
        try:
            descriptor = schema.method(method)
            fields = descriptor.input_type.fields_by_name
            if set(fields) != {field} or fields[field].enum_type is None:
                raise ValueError()
            if not set(values).issubset(fields[field].enum_type.values_by_number):
                raise ValueError()
            request_class = schema.request_type(method)
            for value in values:
                request = request_class(**{field: value}).SerializeToString()
                requests.append((method, value, request))
        except (ValueError, KeyError, TypeError):
            raise CollectorError("Schema does not match the public terms/help request contract") from None
    output = Path(output)
    metadata = [("x-app-version", app_version)]
    captured = []
    with grpc.secure_channel(OFFICIAL_TARGET, _tls_credentials(None),
            options=(("grpc.enable_retries", 0), ("grpc.max_receive_message_length", 17 * 1024 * 1024))) as channel:
        for method, value, request in requests:
            try:
                raw, call = channel.unary_unary(method).with_call(
                    codec.encode(request), metadata=metadata, timeout=15)
            except grpc.RpcError as error:
                raise _failure(method, error) from None
            if call.code() != grpc.StatusCode.OK or _application_codes(call):
                raise _failure(method, call) from None
            try:
                payload = codec.decode(raw)
                schema.response_type(method).FromString(payload)
            except (ValueError, DecodeError):
                raise CollectorError("Public terms/help RPC returned a malformed response") from None
            try:
                output.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(dir=output.parent, prefix=".public-text-") as temporary:
                    source, request_path = Path(temporary) / "response.pb", Path(temporary) / "request.pb"
                    source.write_bytes(payload)
                    request_path.write_bytes(request)
                    source.chmod(0o600)
                    request_path.chmod(0o600)
                    import_response(source, output, schema, method, request=request_path)
            except (OSError, ValueError):
                raise CollectorError("Cannot save validated public terms/help fixtures") from None
            captured.append({"method": method, "type": value})
    return {"anonymous": True, "captured_responses": len(captured), "rules": 7, "help_types": [1, 2, 3]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor-set", type=Path, default=Path("data/protocol/idolypride-6.1.1.pb"))
    parser.add_argument("--output", type=Path, default=Path("data/public-fixtures"))
    parser.add_argument("--app-version", default="6.1.1")
    args = parser.parse_args(argv)
    try:
        schema = Schema.from_descriptor_set(args.descriptor_set)
        summary = archive_public_text(schema, args.output, args.app_version)
    except (CollectorError, OSError, ValueError, DecodeError) as error:
        if isinstance(error, CollectorError):
            parser.exit(1, f"Public text archive failed: {error}\n")
        parser.exit(1, "Public text archive failed: cannot load the supplied schema or local output\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
