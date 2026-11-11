"""Command-line entry points for offline development and replay."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import tempfile
from threading import Thread

import grpc
from google.protobuf.message import DecodeError

from . import codec
from .catalog import FixtureStore, import_response
from .collect import CollectorError
from .schema import Schema
from .server import Application, ServerConfig, create_server
from .state import State


PROJECT = Path(__file__).resolve().parents[2]


def load_schema(args):
    if args.descriptor_set:
        return Schema.from_descriptor_set(args.descriptor_set)
    if args.solis_dir:
        return Schema.from_solis(args.solis_dir)
    exact = PROJECT / "data" / "protocol" / "idolypride-6.1.1.pb"
    if exact.exists():
        return Schema.from_descriptor_set(exact)
    return Schema.from_solis(PROJECT.parent / "SolisClient")


def rpc(channel, schema, method, request, metadata=()):
    call = channel.unary_unary(method,
        request_serializer=lambda message: codec.encode(message.SerializeToString()),
        response_deserializer=lambda raw: schema.response_type(method).FromString(codec.decode(raw)))
    return call(request, metadata=metadata, timeout=5)


def smoke(schema):
    """Use a disposable DB and a real TCP gRPC channel; never contact official services."""
    with tempfile.TemporaryDirectory(prefix="idoly-smoke-") as directory:
        root = Path(directory)
        fixture = schema.response_type("/api.User/Get")()
        fixture.user.name = "Local smoke test"
        source = root / "user.pb"
        source.write_bytes(fixture.SerializeToString())
        import_response(source, root / "fixtures", schema, "/api.User/Get")
        state = State(root / "state.db")
        app = Application(schema, state, FixtureStore(root / "fixtures", schema))
        server, port = create_server(schema, app, ServerConfig(bind="127.0.0.1:0"))
        server.start()
        try:
            with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
                check = rpc(channel, schema, "/api.System/Check", schema.request_type("/api.System/Check")())
                assert check.keepAliveTimeMilliseconds == 60000
                login = rpc(channel, schema, "/api.Auth/Login", schema.request_type("/api.Auth/Login")())
                metadata = [("x-auth-token", login.gameAuthToken)]
                user = rpc(channel, schema, "/api.User/Get", schema.request_type("/api.User/Get")(), metadata)
                assert user.user.name == "Local smoke test"
                try:
                    rpc(channel, schema, "/api.Master/Get", schema.request_type("/api.Master/Get")(), metadata)
                except grpc.RpcError as error:
                    assert error.code() == grpc.StatusCode.UNIMPLEMENTED
                else:
                    raise AssertionError("Missing master unexpectedly succeeded")
                assert State(root / "state.db").authenticated(login.gameAuthToken, "local")
        finally:
            server.stop(0).wait()
    print(json.dumps({"ok": True, "transport": "encrypted protobuf over gRPC",
        "verified": ["System.Check", "Auth.Login", "User.Get fixture", "missing master error", "SQLite persistence"],
        "game_client_tested": False}, ensure_ascii=False, indent=2))


def serve(args, schema):
    from .assets import create_asset_server, prepare_master_tag

    asset_server = None
    if args.master_tag and (not args.asset_root or not args.asset_base_url):
        raise ValueError("--master-tag requires --asset-root and --asset-base-url")
    master_response = None
    if args.master_tag:
        master_response = prepare_master_tag(schema, args.master_tag, args.asset_root / "master", args.asset_base_url)
    media_mode = getattr(args, "media_mode", False)
    state_path = args.state.with_name("media-" + args.state.name) if media_mode else args.state
    fixture_path = args.fixtures.with_name("media-" + args.fixtures.name) if media_mode else args.fixtures
    fixtures = FixtureStore(fixture_path, schema)
    state = State(state_path)
    media_scenes = None
    if media_mode:
        if args.master_dir is None:
            raise ValueError("--media-mode requires --master-dir")
        from .media_runtime import prepare_media_profile
        media_scenes = prepare_media_profile(state, schema, args.profile, args.master_dir)
    app = Application(schema, state, fixtures, args.profile, master_response,
                      master_dir=args.master_dir, dream_catalog_path=args.dream_catalog,
                      pvp_catalog_path=args.pvp_catalog, media_mode=media_mode,
                      photo_scene_access=media_scenes)
    config = ServerConfig(args.bind, state_path, args.profile, args.tls_cert, args.tls_key)
    server, port = create_server(schema, app, config)
    try:
        if args.asset_root:
            asset_server = create_asset_server(args.asset_host, args.asset_port, args.asset_root)
            Thread(target=asset_server.serve_forever, daemon=True).start()
        server.start()
        print(f"gRPC ready: {args.bind} (port {port}), profile={args.profile}", flush=True)
        if asset_server:
            print(f"HTTP files ready: {args.asset_host}:{asset_server.server_address[1]}", flush=True)
        print("Unimplemented RPCs return UNIMPLEMENTED; this server does not contact official services.", flush=True)
        server.wait_for_termination()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop(1).wait()
        if asset_server:
            asset_server.shutdown()
            asset_server.server_close()


def parser():
    result = argparse.ArgumentParser(description="Idoly Pride offline gRPC development server")
    source = result.add_mutually_exclusive_group()
    source.add_argument("--solis-dir", type=Path, help="SolisClient checkout containing generated protobuf modules")
    source.add_argument("--descriptor-set", type=Path, help="FileDescriptorSet, with all imported dependencies")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("inspect", help="Print schema fingerprint and RPC coverage")
    export = commands.add_parser("export-schema", help="Export the loaded schema plus dependencies")
    export.add_argument("output", type=Path)
    commands.add_parser("smoke", help="Run a disposable offline TCP gRPC smoke test")
    archive = commands.add_parser("archive-master", help="Archive public MasterTag and original encrypted packs without an account")
    archive.add_argument("--output", type=Path, default=Path("data/original-master"))
    archive.add_argument("--app-version", default="6.1.1")
    archive.add_argument("--roots-file", type=Path)
    archive.add_argument("--workers", type=int, default=6)
    new = commands.add_parser("new-profile", help="Create an initial local User.Get snapshot")
    new.add_argument("profile")
    new.add_argument("--manager-name", default="Local Manager")
    new.add_argument("--state", type=Path, default=Path("data/state.db"))
    imp_profile = commands.add_parser("import-profile", help="Preserve an existing User.Get response as a local profile")
    imp_profile.add_argument("profile")
    imp_profile.add_argument("source", type=Path)
    imp_profile.add_argument("--state", type=Path, default=Path("data/state.db"))
    imp_profile.add_argument("--wire", action="store_true", help="Encrypted application envelope without gRPC frame header")
    collect = commands.add_parser("collect-session", help="Preserve allowed official reads using existing local session metadata")
    collect.add_argument("metadata_file", type=Path, help="Local JSON containing current request metadata; never submit this file to chat")
    collect.add_argument("--output", type=Path, default=Path("data/archive"))
    collect.add_argument("--roots-file", type=Path, help="Optional trusted CA PEM for the official gRPC endpoint")
    collect.add_argument("--profile", help="Also import the captured User.Get snapshot under this local profile")
    collect.add_argument("--state", type=Path, default=Path("data/state.db"))
    run = commands.add_parser("serve", help="Start the local server")
    run.add_argument("--bind", default="127.0.0.1:50051")
    run.add_argument("--state", type=Path, default=Path("data/state.db"))
    run.add_argument("--profile", default="local", help="Single local profile to serve; Firebase tokens are ignored")
    run.add_argument("--media-mode", action="store_true",
        help="Unlock local media in a separate media- state DB; ordinary saves are preserved")
    run.add_argument("--fixtures", type=Path, default=Path("data/fixtures"))
    run.add_argument("--master-dir", type=Path, help="Matching decoded local master JSON directory")
    run.add_argument("--dream-catalog", type=Path, help="Private Dream catalog belonging to this profile")
    run.add_argument("--pvp-catalog", type=Path, help="Private VENUS catalog belonging to this profile")
    run.add_argument("--tls-cert", type=Path)
    run.add_argument("--tls-key", type=Path)
    run.add_argument("--master-tag", type=Path, help="Original MasterTag JSON, with matching local raw packs")
    run.add_argument("--asset-root", type=Path, help="Static file root, with encrypted MasterDBs in master/")
    run.add_argument("--asset-host", default="127.0.0.1")
    run.add_argument("--asset-port", type=int, default=8080)
    run.add_argument("--asset-base-url", help="Device-reachable HTTP(S) base URL for master downloads")
    imp = commands.add_parser("import-response", help="Validate and import a decrypted or encrypted response")
    imp.add_argument("method", help="e.g. /api.User/Get")
    imp.add_argument("source", type=Path)
    imp.add_argument("--output", type=Path, default=Path("data/fixtures"))
    imp.add_argument("--request", type=Path, help="Decrypted protobuf request to match by SHA-256")
    imp.add_argument("--wire", action="store_true", help="Source is an encrypted application envelope, without gRPC frame header")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        schema = load_schema(args)
        if args.command == "inspect":
            print(json.dumps({"schema_sha256": schema.fingerprint, "files": len(schema.files),
                "services": len({path.rsplit("/", 1)[0] for path in schema.methods}), "rpc_count": len(schema.methods),
                "unary_rpcs": sum(not method.client_streaming and not method.server_streaming for method in schema.methods.values()),
                "builtin_rpcs": ["/api.System/Check", "/api.System/GetMetadata", "/api.System/CheckApp", "/api.Auth/Login"],
                "others": "Imported fixtures or UNIMPLEMENTED"}, ensure_ascii=False, indent=2))
        elif args.command == "export-schema":
            schema.export(args.output)
            print(args.output.resolve())
        elif args.command == "smoke":
            smoke(schema)
        elif args.command == "archive-master":
            from .collect import archive_public_master

            print(json.dumps(archive_public_master(schema, args.output, args.app_version,
                roots_file=args.roots_file, workers=args.workers), ensure_ascii=False, indent=2))
        elif args.command in ("new-profile", "import-profile"):
            from .profiles import new_profile, import_profile

            state = State(args.state)
            if args.command == "new-profile":
                new_profile(state, schema, args.profile, args.manager_name)
            else:
                import_profile(state, schema, args.profile, args.source, args.wire)
            print(json.dumps({"profile": args.profile, "state": str(args.state.resolve()),
                "snapshot_saved": True}, ensure_ascii=False))
        elif args.command == "collect-session":
            from .collect import collect_session

            summary = collect_session(schema, args.metadata_file, args.output, roots_file=args.roots_file)
            if args.profile:
                from .profiles import import_profile

                payload = FixtureStore(args.output / "fixtures", schema).get("/api.User/Get", b"")
                if payload is None:
                    raise ValueError("Archive has no User.Get snapshot")
                with tempfile.TemporaryDirectory(prefix="idoly-profile-import-") as directory:
                    source = Path(directory) / "user.pb"
                    source.write_bytes(payload)
                    import_profile(State(args.state), schema, args.profile, source)
                summary["profile"] = args.profile
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        elif args.command == "import-response":
            print(import_response(args.source, args.output, schema, args.method, args.request, args.wire))
        elif args.command == "serve":
            serve(args, schema)
    except (ValueError, OSError, DecodeError, CollectorError) as error:
        # Exception text from protobuf JSON parsing may include raw input values.
        # Individual importers sanitize parse failures before they reach here.
        raise SystemExit(f"Error: {error}") from None


if __name__ == "__main__":
    main()
