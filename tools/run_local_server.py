#!/usr/bin/env python3
"""Prepare missing local data and run the server on this Android device or Mac.

Dependencies must already be installed by setup_local_server.sh. Game files and
existing profile snapshots are preserved. Only --download-master enables this
launcher's network collection; normal serving stays local.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys


PROJECT = Path(__file__).resolve().parents[1]


class LauncherError(ValueError):
    """A setup failure with a user-facing recovery step."""


def _port(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535") from None
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535")
    return number


def _profile(value: str) -> str:
    if (not value.strip() or not value.isprintable() or value in (".", "..")
            or "/" in value or "\\" in value):
        raise argparse.ArgumentTypeError("profile must be a nonempty plain directory name")
    return value


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--client", type=Path, help="Original 6.1.1 APK/XAPK or decrypted IPA; used only if schema is absent")
    result.add_argument("--native", type=Path, help="ARM64 split APK or libil2cpp.so for an Android base APK")
    result.add_argument("--download-master", action="store_true", help="Explicitly download/resume public original master packs")
    result.add_argument("--data-dir", type=Path, default=PROJECT / "data")
    result.add_argument("--profile", type=_profile, default="sandbox")
    result.add_argument("--manager-name", default="로컬 매니저", help="Used only when the profile has no snapshot")
    result.add_argument("--grpc-host", default="127.0.0.1")
    result.add_argument("--grpc-port", type=_port, default=50051)
    result.add_argument("--asset-host", default="127.0.0.1")
    result.add_argument("--asset-port", type=_port, default=8080)
    result.add_argument("--asset-base-url", help="Download origin visible to the client; default uses asset host and port")
    return result


def ensure_environment(project: Path, argv: list[str]) -> None:
    interpreter = project / ".venv/bin/python"
    if not interpreter.is_file():
        raise LauncherError("Missing .venv. Run bash tools/setup_local_server.sh first.")
    if Path(sys.prefix).resolve() != (project / ".venv").resolve():
        os.execv(str(interpreter), [str(interpreter), str(project / "tools/run_local_server.py"), *argv])


def extract_schema(client: Path | None, output: Path, project: Path, native: Path | None = None) -> None:
    if client is None or not client.is_file():
        raise LauncherError("No local schema exists. Supply --client with an existing original 6.1.1 XAPK/APK or decrypted IPA.")
    suffix = client.suffix.lower()
    if suffix not in (".apk", ".xapk", ".ipa"):
        raise LauncherError("--client must be an original APK/XAPK or decrypted IPA")
    script = "extract_ios_schema.py" if suffix == ".ipa" else "extract_client_schema.py"
    command = [sys.executable, str(project / "tools" / script), str(client), "--output", str(output)]
    if native is not None:
        if suffix == ".ipa":
            raise LauncherError("--native is only used with an Android APK/XAPK")
        if not native.is_file():
            raise LauncherError("The --native split APK or library file does not exist")
        command += ["--native", str(native)]
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError:
        raise LauncherError("Client schema extraction failed. Check the original client version and extraction dependencies.") from None


def _authority(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host and not host.startswith("[") else f"{host}:{port}"


def run(args, project: Path = PROJECT) -> None:
    try:
        from idoly_local.cli import serve
        from idoly_local.profiles import new_profile
        from idoly_local.schema import Schema
        from idoly_local.state import State
    except ImportError:
        raise LauncherError("Server dependencies are missing. Run bash tools/setup_local_server.sh first.") from None

    data = args.data_dir.expanduser().resolve()
    descriptor = data / "protocol/idolypride-6.1.1.pb"
    if not descriptor.is_file():
        extract_schema(args.client.expanduser() if args.client else None, descriptor, project,
                       args.native.expanduser() if args.native else None)
    schema = Schema.from_descriptor_set(descriptor)
    archive = data / "original-master"
    if args.download_master:
        from idoly_local.collect import archive_public_master

        archive_public_master(schema, archive)
    master_tag = archive / "master-tag.json"
    asset_root = archive / "assets"
    if not master_tag.is_file() or not (asset_root / "master").is_dir():
        raise LauncherError("Original master archive is missing. Run again with --download-master, or restore it under the selected data directory.")

    state_path = data / "state.db"
    state = State(state_path)
    if state.snapshot(args.profile) is None:
        new_profile(state, schema, args.profile, args.manager_name)
    base_url = args.asset_base_url or "http://" + _authority(args.asset_host, args.asset_port)
    options = SimpleNamespace(bind=_authority(args.grpc_host, args.grpc_port), state=state_path,
                              profile=args.profile, fixtures=data / args.profile / "fixtures",
                              tls_cert=None, tls_key=None, master_tag=master_tag, asset_root=asset_root,
                              asset_host=args.asset_host, asset_port=args.asset_port, asset_base_url=base_url)
    print(f"Starting local profile {args.profile} at {options.bind}; stop with Ctrl+C.", flush=True)
    serve(options, schema)


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(arguments)
    try:
        ensure_environment(PROJECT, arguments)
        run(args)
    except (ValueError, OSError, RuntimeError) as error:
        print(f"Cannot start local server: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
