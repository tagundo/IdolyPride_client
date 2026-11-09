"""Unary gRPC transport, local boot handlers, and explicitly imported responses."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import logging
from pathlib import Path

import grpc

from . import codec
from .application import Application
from .rpc import RpcCode


LOG = logging.getLogger(__name__)
MAX_MESSAGE = 16 * 1024 * 1024


@dataclass
class ServerConfig:
    bind: str = "127.0.0.1:50051"
    state: Path = Path("data/state.db")
    profile: str = "local"
    tls_cert: Path | None = None
    tls_key: Path | None = None




class _Context:
    def __init__(self, context):
        self.context = context

    def invocation_metadata(self):
        return self.context.invocation_metadata()

    def abort(self, code: RpcCode, details: str):
        self.context.abort(grpc.StatusCode[code.name], details)


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
            lambda raw, context, path=path: application.handle(path, raw, _Context(context)),
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
