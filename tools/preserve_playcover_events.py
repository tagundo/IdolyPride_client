#!/usr/bin/env python3
"""Inspect local PlayCover records, or explicitly preserve existing-account events.

Default inspection is offline. Login and normal event-menu visits require
separate switches. Never upload Firebase archives, credentials or private output.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from export_playcover_auth import _export_rows
from idoly_local.event_capture import EventCaptureError, collect_in_memory
from idoly_local.official_session import (BUNDLE, GOOGLE_APP_ID, PROJECT_ID,
    OfficialSessionError, inspect_archives, login_existing_account)
from idoly_local.schema import Schema


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true", help="Offline counts only (the default)")
    parser.add_argument("--bundle", default=BUNDLE, choices=(BUNDLE,))
    parser.add_argument("--google-app-id", default=GOOGLE_APP_ID, choices=(GOOGLE_APP_ID,))
    parser.add_argument("--project-id", default=PROJECT_ID, choices=(PROJECT_ID,))
    parser.add_argument("--account-group", "--group-number", type=int, dest="account_group")
    parser.add_argument("--inventory-nonce", help=argparse.SUPPRESS)
    parser.add_argument("--expected-group-binding", help=argparse.SUPPRESS)
    parser.add_argument("--login-existing-account", action="store_true",
        help="Use the existing account on this Mac, refreshing only if expired; never create an account")
    parser.add_argument("--visit-current-menus", "--visit-menus", action="store_true", dest="visit_menus",
        help="Visit Dream/VENUS menus; ordinary monthly/season reconciliation or login rewards may occur")
    parser.add_argument("--output", type=Path, help="New private archive directory, kept on this Mac")
    parser.add_argument("--descriptor-set", type=Path, default=_ROOT / "data/protocol/idolypride-6.1.1.pb")
    parser.add_argument("--roots-file", type=Path)
    parser.add_argument("--photo-limit", type=int, default=16)
    parser.add_argument("--opponent-limit", type=int, default=6)
    parser.add_argument("--deadline-seconds", type=float, default=300)
    args = parser.parse_args(argv)
    try:
        if args.inspect and args.login_existing_account:
            raise OfficialSessionError("inspect_and_login_conflict")
        if args.visit_menus and not args.login_existing_account:
            raise OfficialSessionError("menu_visit_requires_existing_login")
        if (args.expected_group_binding is not None
                and (not args.login_existing_account or args.inventory_nonce is None)
                or args.login_existing_account and args.inventory_nonce is not None
                and args.expected_group_binding is None):
            raise OfficialSessionError("account_binding_invalid")
        if args.login_existing_account:
            if args.output is None or os.path.lexists(args.output):
                raise OfficialSessionError("new_private_output_required")
            if not 0 <= args.photo_limit <= 32 or not 0 <= args.opponent_limit <= 20 \
                    or not 0 < args.deadline_seconds <= 900:
                raise OfficialSessionError("capture_options_invalid")
        rows = _export_rows(args.bundle, Path.home(), args.google_app_id)
        inventory = inspect_archives([row[2] for row in rows])
        now = int(time.time())
        result = inventory.summary(now=now, binding_nonce=args.inventory_nonce)
        if args.login_existing_account:
            credentials = inventory.select(now=now, group_number=args.account_group,
                binding_nonce=args.inventory_nonce, expected_group_binding=args.expected_group_binding)
            schema = Schema.from_descriptor_set(args.descriptor_set)
            with login_existing_account(schema, credentials, login_existing_account=True,
                                        roots_file=args.roots_file, now=now) as session:
                capture = collect_in_memory(schema, session.metadata, args.output,
                    visit_menus=args.visit_menus, roots_file=args.roots_file,
                    photo_limit=args.photo_limit, opponent_limit=args.opponent_limit,
                    deadline_seconds=args.deadline_seconds)
            result = {"status": "preserved", "output": str(args.output.resolve()), **capture}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OfficialSessionError, EventCaptureError) as error:
        print(json.dumps({"status": "failed", "code": error.code}))
        return 1
    except Exception:
        # Export/SQLite/plist/network exceptions can contain paths or credentials.
        print(json.dumps({"status": "failed", "code": "local_preservation_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
