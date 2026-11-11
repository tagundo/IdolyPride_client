#!/usr/bin/env python3
"""Private, bounded JSON bridge. No credentials or exception text cross this boundary."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import ssl
import sys

DESCRIPTOR_SHA256 = "c82cee62abdca7144d11e710a6f773211464a89d2ddede207999a0a5e7aec8ad"
CA_SHA256 = "2089fc5a25836401faee99f722460b01b393999746a0fb817943666d6ecc0458"
MAX_LINE = 64 * 1024
MAX_REPLY = 256 * 1024
FAILURE_CODES = frozenset((
    "archive_scopes_differ", "archive_rows_invalid", "archive_candidates_invalid",
    "account_selection_required_or_invalid", "existing_login_opt_in_required",
    "firebase_scope_invalid", "firebase_token_time_invalid", "firebase_refresh_scope_mismatch",
    "firebase_response_invalid", "http_target_not_allowed", "http_redirect_rejected",
    "http_request_rejected", "http_response_too_large", "http_transport_failed",
    "tls_roots_invalid", "seed_response_invalid", "rpc_method_not_allowed", "rpc_failed",
    "application_error", "rpc_response_invalid", "master_version_invalid",
    "existing_account_login_rejected", "existing_login_failed", "time_invalid",
    "inspect_and_login_conflict", "menu_visit_requires_existing_login",
    "new_private_output_required", "capture_options_invalid", "local_preservation_failed",
    "cannot_create_private_output", "cannot_save_private_archive", "capture_failed",
    "account_binding_invalid", "account_inventory_changed",
))


class BridgeError(Exception):
    def __init__(self, code):
        self.code = code


class BoundedText(io.StringIO):
    def write(self, text):
        if self.tell() + len(text) > MAX_REPLY:
            raise BridgeError("worker_reply_invalid")
        return super().write(text)


def _integer(value, minimum=0, maximum=4096):
    return type(value) is int and minimum <= value <= maximum


def _descriptor(path):
    if path is None or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise BridgeError("descriptor_invalid")
    if hashlib.sha256(path.read_bytes()).hexdigest() != DESCRIPTOR_SHA256:
        raise BridgeError("descriptor_invalid")


def _invoke(cli, argv):
    output, discarded = BoundedText(), BoundedText()
    with redirect_stdout(output), redirect_stderr(discarded):
        result = cli(argv)
    if type(result) is not int or result not in (0, 1):
        raise BridgeError("worker_reply_invalid")
    try:
        value = json.loads(output.getvalue())
    except (ValueError, TypeError):
        raise BridgeError("worker_reply_invalid") from None
    if type(value) is not dict:
        raise BridgeError("worker_reply_invalid")
    if value.get("status") == "failed":
        code = value.get("code")
        raise BridgeError(code if type(code) is str and code in FAILURE_CODES else "capture_failed")
    if result != 0:
        raise BridgeError("worker_reply_invalid")
    return value


def _inspection(value):
    keys = ("matched_rows", "valid_archives", "rejected_archives", "account_groups")
    if value.get("status") != "inspected" or not all(_integer(value.get(k)) for k in keys):
        raise BridgeError("worker_reply_invalid")
    groups = value.get("groups")
    if type(groups) is not list or len(groups) != value["account_groups"]:
        raise BridgeError("worker_reply_invalid")
    safe = []
    for index, group in enumerate(groups, 1):
        if (type(group) is not dict or not _integer(group.get("group_number"), 1)
                or group.get("group_number") != index
                or not _integer(group.get("candidate_count"), 1)
                or not _integer(group.get("current_candidate_count"))
                or group["current_candidate_count"] > group["candidate_count"]):
            raise BridgeError("worker_reply_invalid")
        safe.append({k: group[k] for k in ("group_number", "candidate_count", "current_candidate_count")})
    if sum(g["candidate_count"] for g in safe) != value["valid_archives"]:
        raise BridgeError("worker_reply_invalid")
    if value["valid_archives"] + value["rejected_archives"] > value["matched_rows"]:
        raise BridgeError("worker_reply_invalid")
    return {"event": "inspection", "status": "inspected", **{k: value[k] for k in keys}, "groups": safe}


class Bridge:
    def __init__(self, cli, descriptor=None, *, roots_file=None, offline_only=False):
        self.cli, self.descriptor, self.offline_only = cli, descriptor, offline_only
        self.roots_file = roots_file
        self.inventory = None
        self.nonce, self.bindings = None, {}

    def handle(self, command):
        if type(command) is not dict:
            raise BridgeError("command_invalid")
        action = command.get("action")
        if action == "inspect" and set(command) == {"action"}:
            self.inventory = None
            self.nonce, self.bindings = secrets.token_hex(32), {}
            value = _invoke(self.cli, ["--inspect", "--inventory-nonce", self.nonce])
            safe = _inspection(value)
            for group in value["groups"]:
                binding = group.get("binding")
                if type(binding) is not str or re.fullmatch("[0-9a-f]{64}", binding) is None:
                    raise BridgeError("worker_reply_invalid")
                self.bindings[group["group_number"]] = binding
            self.inventory = safe
            return safe
        if action != "capture" or set(command) != {"action", "output", "account_group", "allow_login", "allow_menu_visit"}:
            raise BridgeError("command_invalid")
        if self.offline_only:
            raise BridgeError("offline_only")
        if command["allow_login"] is not True or command["allow_menu_visit"] is not True:
            raise BridgeError("existing_login_opt_in_required")
        if self.inventory is None or not self.inventory["valid_archives"] or self.inventory["rejected_archives"]:
            raise BridgeError("inspection_required")
        group = command["account_group"]
        if group is None:
            if self.inventory["account_groups"] != 1:
                raise BridgeError("account_selection_required_or_invalid")
        elif not _integer(group, 1, self.inventory["account_groups"]):
            raise BridgeError("account_selection_required_or_invalid")
        output = command["output"]
        if (type(output) is not str or not 0 < len(output.encode("utf-8")) <= 4096
                or any(ord(c) < 32 for c in output) or not Path(output).is_absolute()):
            raise BridgeError("new_private_output_required")
        target = Path(output)
        if target.exists() or target.is_symlink() or not target.parent.is_dir():
            raise BridgeError("new_private_output_required")
        _descriptor(self.descriptor)
        if (self.roots_file is None or not self.roots_file.is_file()
                or not 0 < self.roots_file.stat().st_size <= 1024 * 1024
                or hashlib.sha256(self.roots_file.read_bytes()).hexdigest() != CA_SHA256):
            raise BridgeError("tls_roots_invalid")
        group = group or 1
        args = ["--login-existing-account", "--visit-current-menus", "--output", str(target),
                "--descriptor-set", str(self.descriptor), "--roots-file", str(self.roots_file),
                "--account-group", str(group), "--inventory-nonce", self.nonce,
                "--expected-group-binding", self.bindings[group]]
        value = _invoke(self.cli, args)
        if (value.get("status") != "preserved" or value.get("credentials_exported") is not False
                or value.get("output") != str(target.resolve())
                or not _integer(value.get("captured_responses"), 0, 4096)
                or not _integer(value.get("limitation_count"), 0, 4096)
                or type(value.get("complete")) is not bool
                or type(value.get("consistent_final_snapshot")) is not bool
                or (value["complete"] and (value["limitation_count"] or not value["consistent_final_snapshot"]))):
            raise BridgeError("worker_reply_invalid")
        return {"event": "complete", "output": str(target.resolve()),
                "capture_count": value["captured_responses"], "complete": value["complete"],
                "limitation_count": value["limitation_count"],
                "consistent_final_snapshot": value["consistent_final_snapshot"]}


def _emit(value, output):
    output.write(json.dumps({"schema": 1, **value}, ensure_ascii=False, separators=(",", ":")) + "\n")
    output.flush()


def serve(bridge, source, output):
    _emit({"event": "ready", "offline": True}, output)
    while True:
        line = source.readline(MAX_LINE + 1)
        if not line:
            return 0
        if len(line) > MAX_LINE:
            _emit({"event": "failure", "code": "command_invalid"}, output)
            return 1
        try:
            command = json.loads(line)
            if command == {"action": "quit"}:
                return 0
            _emit(bridge.handle(command), output)
        except BridgeError as error:
            _emit({"event": "failure", "code": error.code}, output)
        except BaseException:
            _emit({"event": "failure", "code": "local_preservation_failed"}, output)


def self_test(descriptor=None):
    calls = []
    def fake(argv):
        calls.append(argv)
        print(json.dumps({"status": "inspected", "matched_rows": 1, "valid_archives": 1,
            "rejected_archives": 0, "account_groups": 1, "groups": [
                {"group_number": 1, "candidate_count": 1, "current_candidate_count": 0, "binding": "b" * 64}]}))
        return 0
    if descriptor is not None:
        _descriptor(descriptor)
    bridge = Bridge(fake, descriptor, offline_only=True)
    capture = {"action": "capture", "output": "/synthetic-unused", "account_group": 1,
               "allow_login": True, "allow_menu_visit": True}
    sink = io.StringIO()
    serve(bridge, io.StringIO('\n'.join(map(json.dumps, [{"action": "inspect"}, capture, {"action": "quit"}]))), sink)
    replies = list(map(json.loads, sink.getvalue().splitlines()))
    inspected_only = len(calls) == 1 and calls[0][:2] == ["--inspect", "--inventory-nonce"]
    ok = inspected_only and replies[-1] == {"schema": 1, "event": "failure", "code": "offline_only"}
    return {"schema": 1, "synthetic_only": True, "ok": ok, "offline_inspection_completed": ok,
            "no_network_capture_called": inspected_only}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--offline-only", action="store_true", help="Reject all login/capture commands")
    parser.add_argument("--self-test", action="store_true", help="Synthetic bridge only; never reads user files or contacts a server")
    parser.add_argument("--descriptor-set", type=Path)
    parser.add_argument("--roots-file", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            result = self_test(args.descriptor_set)
            if args.roots_file is not None:
                if hashlib.sha256(args.roots_file.read_bytes()).hexdigest() != CA_SHA256:
                    raise BridgeError("tls_roots_invalid")
                context = ssl.create_default_context(cafile=str(args.roots_file))
                if context.cert_store_stats().get("x509_ca", 0) < 1:
                    raise BridgeError("tls_roots_invalid")
                result["packaged_tls_roots_loaded"] = True
            if args.report:
                args.report.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result))
            return 0 if result["ok"] else 1
        if not args.worker or args.report:
            parser.error("choose --worker or --self-test")
        # Import lazily: --help and synthetic self-test cannot read PlayCover or initialize auth.
        from preserve_playcover_events import main as cli
        return serve(Bridge(cli, args.descriptor_set, roots_file=args.roots_file,
                            offline_only=args.offline_only), sys.stdin, sys.stdout)
    except BaseException:
        _emit({"event": "failure", "code": "local_preservation_failed"}, sys.stdout)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
