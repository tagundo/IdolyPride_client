#!/usr/bin/env python3
"""Preserve private Dream/VENUS data locally; never send credentials to chat."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from idoly_local.event_capture import (EventCaptureError, MAX_ARCHIVE, MAX_REQUEST, MAX_WIRE,
    ObservedResponse, collect_events, import_observed)
from idoly_local.schema import Schema


def _private_input(root, value, limit, *, remaining=None):
    if not isinstance(value, str):
        raise EventCaptureError("import_plan_invalid")
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > limit:
        raise EventCaptureError("import_file_invalid")
    remaining = MAX_ARCHIVE if remaining is None else remaining
    if path.stat().st_size > remaining:
        raise EventCaptureError("archive_size_limit_reached")
    # Bound the read itself as well as stat(), in case the file grows meanwhile.
    with path.open("rb") as stream:
        raw = stream.read(min(limit, remaining) + 1)
    if len(raw) > limit:
        raise EventCaptureError("import_file_invalid")
    if len(raw) > remaining:
        raise EventCaptureError("archive_size_limit_reached")
    return raw


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor-set", type=Path,
        default=Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb")
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("collect", help="Use current existing session metadata, without login or refresh")
    capture.add_argument("--metadata-file", type=Path, required=True, help="Private local JSON; never upload it")
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--roots-file", type=Path)
    capture.add_argument("--visit-menus", action="store_true",
        help="Visit Dream/VENUS menus; official monthly/season reconciliation or login rewards can occur")
    capture.add_argument("--photo-limit", type=int, default=16)
    capture.add_argument("--opponent-limit", type=int, default=6)
    capture.add_argument("--deadline-seconds", type=float, default=300)
    observed = commands.add_parser("import", help="Import previously observed responses; no network calls")
    observed.add_argument("--plan", type=Path, required=True,
        help="JSON array: method,response,request(optional for empty methods),response_is_wire,request_is_wire")
    observed.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        schema = Schema.from_descriptor_set(args.descriptor_set)
        if args.command == "collect":
            result = collect_events(schema, args.metadata_file, args.output, visit_menus=args.visit_menus,
                roots_file=args.roots_file, photo_limit=args.photo_limit, opponent_limit=args.opponent_limit,
                deadline_seconds=args.deadline_seconds)
        else:
            if args.plan.stat().st_size > 1024 * 1024:
                raise EventCaptureError("import_plan_invalid")
            with args.plan.open("rb") as stream:
                raw_plan = stream.read(1024 * 1024 + 1)
            if len(raw_plan) > 1024 * 1024:
                raise EventCaptureError("import_plan_invalid")
            plan = json.loads(raw_plan)
            if not isinstance(plan, list) or not 0 < len(plan) <= 128:
                raise EventCaptureError("import_plan_invalid")
            root = args.plan.resolve().parent
            records, remaining = [], MAX_ARCHIVE
            for row in plan:
                if not isinstance(row, dict) or set(row) - {"method", "response", "request", "response_is_wire", "request_is_wire"}:
                    raise EventCaptureError("import_plan_invalid")
                response = _private_input(root, row.get("response"), MAX_WIRE, remaining=remaining)
                remaining -= len(response)
                request = _private_input(root, row["request"], MAX_REQUEST, remaining=remaining) if "request" in row else None
                remaining -= len(request) if request is not None else 0
                records.append(ObservedResponse(method=row.get("method"), response=response, request=request,
                    response_is_wire=row.get("response_is_wire", False), request_is_wire=row.get("request_is_wire", False)))
            result = import_observed(schema, records, args.output)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except EventCaptureError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("Event preservation stopped: local_input_invalid", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
