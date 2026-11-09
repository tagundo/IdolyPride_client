"""Unary gRPC transport, local boot handlers, and explicitly imported responses."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import logging
from pathlib import Path

import grpc
from google.protobuf.message import DecodeError

from . import codec
from .state import State


LOG = logging.getLogger(__name__)
MAX_MESSAGE = 16 * 1024 * 1024


@dataclass
class ServerConfig:
    bind: str = "127.0.0.1:50051"
    state: Path = Path("data/state.db")
    profile: str = "local"
    tls_cert: Path | None = None
    tls_key: Path | None = None


class Application:
    def __init__(self, schema, state: State, fixtures, profile="local", master_response: bytes | None = None):
        self.schema = schema
        self.state = state
        self.fixtures = fixtures
        self.profile = profile
        self.master_response = master_response

    def handle(self, path, raw, context):
        # Deserialize here so malformed traffic maps to INVALID_ARGUMENT instead
        # of gRPC's generic INTERNAL serializer failure. Never log request bodies.
        try:
            plain = codec.decode(raw)
            self.schema.request_type(path).FromString(plain)
        except (ValueError, DecodeError):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Malformed encrypted protobuf request")
        response_type = self.schema.response_type(path)
        LOG.info("RPC %s", path)
        # Auth.Login deliberately ignores firebaseIDToken: this is a single local
        # profile, with no online token validation, refresh, or credential storage.
        if path == "/api.Auth/Login":
            token, profile = self.state.login(self.profile)
            result = response_type(gameAuthToken=token)
            result.userPublic.serverUserId = profile["server_id"]
            result.userPublic.publicUserId = profile["public_id"]
            return result.SerializeToString()
        if path == "/api.System/Check":
            result = response_type(keepAliveTimeMilliseconds=60000, keepAliveTimeoutMilliseconds=20000)
            result.maintenanceInfo.inMaintenance = False
            result.reviewInfo.inReview = False
            return result.SerializeToString()
        if path in ("/api.System/GetMetadata", "/api.System/CheckApp"):
            return response_type().SerializeToString()
        # These title-screen text APIs are anonymous in the Toolkit's observed
        # official flow, and may be needed before a local login is possible.
        if path in ("/api.Master/Rule", "/api.Master/GetHelpCategory"):
            response = self.fixtures.get(path, plain)
            if response is not None:
                return response
            context.abort(grpc.StatusCode.UNIMPLEMENTED, "No local text fixture for " + path)
        metadata = dict(context.invocation_metadata())
        if not self.state.authenticated(metadata.get("x-auth-token", ""), self.profile):
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "Local Auth.Login is required")
        if path == "/api.Master/Get" and self.master_response is not None:
            return self.master_response
        response = self.fixtures.get(path, plain)
        if response is not None:
            return response
        if path == "/api.User/Get":
            snapshot = self.state.snapshot(self.profile)
            if snapshot is not None:
                payload, schema_sha256 = snapshot
                if schema_sha256 != self.schema.fingerprint:
                    context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Profile snapshot uses a different schema; import it with the current schema")
                return payload
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "No local handler or response fixture for " + path)


def create_server(schema, application: Application, config: ServerConfig):
    if (config.tls_cert is None) != (config.tls_key is None):
        raise ValueError("Both TLS certificate and key are required")
    server = grpc.server(ThreadPoolExecutor(max_workers=8), options=[
        ("grpc.max_receive_message_length", MAX_MESSAGE),
        ("grpc.max_send_message_length", MAX_MESSAGE),
    ])
    services = {}
    for path, method in schema.methods.items():
        # Health.Watch is a server stream in 6.1.1. Leaving unsupported stream
        # handlers unregistered lets gRPC return UNIMPLEMENTED for that method.
        if method.client_streaming or method.server_streaming:
            continue
        service_name, method_name = path[1:].split("/")
        services.setdefault(service_name, {})[method_name] = grpc.unary_unary_rpc_method_handler(
            lambda raw, context, path=path: application.handle(path, raw, context),
            request_deserializer=lambda raw: raw,
            response_serializer=codec.encode,
        )
    server.add_generic_rpc_handlers([
        grpc.method_handlers_generic_handler(name, methods)
        for name, methods in services.items()
    ])
    if config.tls_cert:
        credentials = grpc.ssl_server_credentials([(
            config.tls_key.read_bytes(), config.tls_cert.read_bytes(),
        )])
        port = server.add_secure_port(config.bind, credentials)
    else:
        port = server.add_insecure_port(config.bind)
    if not port:
        raise ValueError("Could not bind gRPC address")
    return server, port
