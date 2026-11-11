"""Preserving native APK upgrade proof for the first-main live SKIP option.

The owned synthetic profile already cleared the first main quest. This proof
checks real repeated calculation with no further rewards, rather than resetting
that profile to manufacture another first grant. No private state is exported.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile

import grpc

import qa_emulator as q
import qa_deck_upgrade as deck_qa
import qa_profile_upgrade as profile_qa
import qa_target as target_qa
from qa_deck_upgrade import guard_idle_owned_guest, installed_hash, mode_setting, verify_payload, PAYLOAD_SHA256
from qa_profile_upgrade import digest, require
from idoly_local import main_live_qa as live


START = "/api.Quest/Start"
USER = "/api.User/Get"
IDS = ("9000000000000000401", "9000000000000000402")


def protected_database(qa):
    """Read stopped state in a protected auto-deleted directory, never export it."""
    with tempfile.TemporaryDirectory(prefix="idoly-skip-private-") as directory:
        path = q._copy_private_database(qa, directory)
        with sqlite3.connect(path) as db:
            q._checkpoint(db)
            definitions = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            require({"profiles", "sessions", "snapshots", "profile_settings", "starter_profiles",
                     "profile_lesson_progress", "main_live_attempts"}.issubset(name for name, in tables),
                    "Native state is missing preservation tables")
            require(db.execute("SELECT name FROM profiles").fetchall() == [("sandbox",)],
                    "Skip QA accepts only its existing synthetic sandbox profile")
            rows, columns = {}, {}
            for name, in tables:
                require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is not None,
                        "Unexpected private table identity")
                cursor = db.execute('SELECT * FROM "' + name + '" LIMIT 0')
                columns[name] = tuple(col[0] for col in cursor.description)
                if name == "snapshots":
                    continue
                order = ",".join(str(index + 1) for index in range(len(cursor.description)))
                rows[name] = db.execute('SELECT * FROM "' + name + '" ORDER BY ' + order).fetchall()
            require({"profile", "response", "schema_sha256"}.issubset(columns["snapshots"]),
                    "Snapshot columns are not compatible with preservation")
            selected = tuple(name for name in columns["snapshots"] if name != "response")
            require(all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in selected),
                    "Unexpected private snapshot column identity")
            projection = ",".join('"' + name + '"' for name in selected)
            metadata = db.execute("SELECT " + projection + " FROM snapshots ORDER BY profile").fetchall()
            require(len(metadata) == 1 and metadata[0][selected.index("profile")] == "sandbox",
                    "Needs one existing synthetic snapshot")
            metadata = {"columns": selected, "rows": metadata}
            return {"definitions": definitions, "columns": columns, "rows": rows, "snapshot_metadata": metadata}


def assert_database_preserved(schema, before, after, receipt):
    require(before["definitions"] == after["definitions"] and before["columns"] == after["columns"]
            and before["snapshot_metadata"] == after["snapshot_metadata"],
            "Skip update changed private schema or snapshot metadata")
    for table, rows in before["rows"].items():
        if table != "main_live_attempts":
            require(rows == after["rows"].get(table), "Skip update changed protected table " + table)
    def attempts(database):
        names = database["columns"]["main_live_attempts"]
        result = {}
        for values in database["rows"]["main_live_attempts"]:
            row = dict(zip(names, values))
            require(row.get("request_id") not in result, "Stored attempt identities are ambiguous")
            result[row.get("request_id")] = row
        return result
    original, updated = attempts(before), attempts(after)
    require(set(receipt["request_ids"]).isdisjoint(original), "Skip test IDs already exist in the baseline")
    require(set(updated) == set(original) | set(receipt["request_ids"]), "Skip update lost or added unrelated attempts")
    require(all(updated[key] == value for key, value in original.items()), "Skip update changed a preexisting attempt")
    live.assert_main_live_attempt_rows(schema, [updated[key] for key in receipt["request_ids"]], receipt)


def choose_request(schema, snapshot, master_dir):
    """Use an existing complete ordinary deck; never repair or reset one."""
    tables = live._oracle(master_dir)
    numbers = sorted({row.number for row in snapshot.decks if row.number > 0})
    for number in numbers:
        try:
            return live._request(schema, snapshot, tables, is_skip=True, deck_number=number)
        except RuntimeError:
            continue
    raise RuntimeError("No existing complete five-card owned unequipped deck is eligible; no state was repaired")


def exercise_skip(schema, invoke, master_dir):
    """Calculate two real repeat clears and verify exact, reward-free deltas."""
    tables = live._oracle(master_dir)
    before = invoke(USER, schema.request_type(USER)(), None)
    require(any(row.questId == live._QUEST and row.lastClearedTime > 0 for row in before.quests),
            "Preserving skip proof requires the already-cleared owned synthetic first quest")
    request, positions = choose_request(schema, before, master_dir)
    response_hashes, times, scores = [], [], []
    current = before
    for identity in IDS:
        response = invoke(START, request, identity)
        expected, now, score, gains = live._clear_projection(schema, current, response, positions,
            tables, master_dir, first=False)
        require(not gains and digest(invoke(USER, schema.request_type(USER)(), None)) == digest(expected),
                "Repeated skip granted rewards/EXP or changed unrelated snapshot fields")
        response_hashes.append(digest(response))
        times.append(now)
        scores.append(score)
        live._cached(schema, invoke, request, expected, [identity], [response_hashes[-1]])
        current = expected
    receipt = {"platform": "Android native repeated first-main SKIP", "quest_id": live._QUEST,
        "deck_number": request.deckNumber, "is_skip": True, "request_ids": list(IDS), "request_sha256": digest(request),
        "first_response_sha256": response_hashes[0], "replay_response_sha256": response_hashes[1],
        "started_times": times, "master_version": (Path(master_dir) / "!version.txt").read_text().strip(),
        "schema_sha256": schema.fingerprint, "ruleset": "live-v5", "snapshot_sha256": digest(current),
        "first_score": scores[0], "replay_score": scores[1], "chart_count": 183, "beat_count": 855,
        "first_clear_already_complete": True, "new_skip_ids_grant_no_rewards_or_exp": True,
        "exact_snapshot_projection": True, "score_trace_conserved": True}
    live.assert_main_live_retries(schema, invoke, master_dir, receipt)
    live.assert_main_live_mode_conflicts(schema, invoke, master_dir, receipt)
    return current, receipt


def stop_owned_after_failure(qa, schema, port):
    """Bounded cleanup of only the verified owned server; never clear data."""
    qa.adb("shell", "am", "force-stop", q.PACKAGE, check=False)
    if qa.adb("shell", "pidof", "-s", q.PACKAGE, check=False).strip():
        return False
    q.wait_server(schema, port, expected=False, timeout=20)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", default="127.0.0.1:6520")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--baseline-source", required=True)
    parser.add_argument("--baseline-apk-sha256", required=True)
    parser.add_argument("--new-source", required=True)
    parser.add_argument("--new-apk", type=Path, required=True)
    parser.add_argument("--new-apk-sha256", required=True)
    parser.add_argument("--startup-timeout", type=float, default=600)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args(argv)
    for value in (args.baseline_source, args.new_source):
        if re.fullmatch(r"[0-9a-f]{40}", value) is None:
            parser.error("Source commits require full lowercase SHA-1 values")
    for value in (args.baseline_apk_sha256, args.new_apk_sha256):
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            parser.error("APK digests require full lowercase SHA-256 values")
    if args.startup_timeout <= 0:
        parser.error("--startup-timeout must be positive")
    qa = q.QA(args.adb, args.serial, args.artifacts)
    result = {"schema": 1, "ok": False, "compiled_source_commit": args.new_source,
        "apk_sha256": args.new_apk_sha256, "payload_sha256": PAYLOAD_SHA256,
        "previous_source_commit": args.baseline_source, "previous_apk_sha256": args.baseline_apk_sha256,
        "qa_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "qa_oracle_sha256": hashlib.sha256(Path(live.__file__).read_bytes()).hexdigest(),
        "qa_dependency_sha256": {Path(module.__file__).name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                                 for module in (q, deck_qa, profile_qa, target_qa)},
        "private_state_exported": False, "game_client_gameplay_tested": False,
        "first_clear_reward_tested_on_device": False, "diagnostics_collector_tested": False,
        "failure_cleanup_attempted": False, "failure_cleanup_status": "not_needed",
        "final_server_stopped": False}
    verified, requested, ready, cleanup_needed = False, False, False, False
    try:
        print("Native SKIP QA: verifying the idle owned ARM64 target and both APKs", flush=True)
        result["target_evidence"] = guard_idle_owned_guest(qa)
        verified = True
        result["baseline_installed_apk_sha256"] = installed_hash(qa)
        require(result["baseline_installed_apk_sha256"] == args.baseline_apk_sha256, "Installed baseline APK hash mismatch")
        verify_payload(args.new_apk, args.new_apk_sha256, args.data_root)
        schema = q.Schema.from_descriptor_set(args.data_root / "protocol/idolypride-6.1.1.pb")
        master = args.data_root / "master-json"
        port = qa.forward(50051)
        def start(stage):
            nonlocal requested, ready, cleanup_needed
            print("Native SKIP QA stage: " + stage, flush=True)
            cleanup_needed = True
            qa.adb("shell", "am", "start", "-n", q.ACTIVITY)
            require(mode_setting(qa, stage + "-mode") is True, "Existing experimental opt-in must stay enabled")
            qa.tap("서버 시작", stage)
            requested, ready = True, False
            q.wait_server(schema, port, timeout=args.startup_timeout)
            ready = True
        def stop(stage):
            nonlocal requested, ready, cleanup_needed
            print("Native SKIP QA stage: " + stage, flush=True)
            qa.tap("서버 중지", stage)
            q.wait_server(schema, port, expected=False, timeout=30)
            qa.adb("shell", "am", "force-stop", q.PACKAGE)
            require(not qa.adb("shell", "pidof", "-s", q.PACKAGE, check=False).strip(), "Native server did not stop")
            requested, ready, cleanup_needed = False, False, False
        start("01-baseline-start")
        _, login = q.bootstrap(schema, port)
        token = login.gameAuthToken
        require(bool(token), "Baseline APK did not issue a local session")
        def invoke(path, request=None, identity=None):
            return q.rpc(schema, port, path, token, request, request_id=identity)
        before = invoke(USER)
        require(before.user.name == "NativeQA", "Skip upgrade proof requires its existing synthetic QA profile")
        request, _ = choose_request(schema, before, master)
        require(any(row.questId == live._QUEST and row.lastClearedTime > 0 for row in before.quests),
                "Preserving skip proof requires the existing first-main clear before the APK update")
        try:
            invoke(START, request, IDS[0])
        except grpc.RpcError as error:
            require(error.code() == grpc.StatusCode.UNIMPLEMENTED, "Baseline skip returned an unexpected status")
        else:
            raise RuntimeError("Baseline APK no longer reproduces the SKIP bug")
        require(digest(invoke(USER)) == digest(before), "Rejected baseline skip changed state")
        result["baseline_skip_unimplemented_reproduced"] = True
        stop("02-baseline-stop")
        protected = protected_database(qa)
        attempt_columns = protected["columns"]["main_live_attempts"]
        require(all(dict(zip(attempt_columns, row)).get("request_id") not in IDS
                    for row in protected["rows"]["main_live_attempts"]), "Reserved skip test IDs already exist")
        print("Native SKIP QA: install-r updated APK without clearing data", flush=True)
        qa.adb("install", "-r", "-g", str(args.new_apk.resolve()))
        result["installed_apk_sha256"] = installed_hash(qa)
        require(result["installed_apk_sha256"] == args.new_apk_sha256, "Installed updated APK hash mismatch")
        package = qa.adb("shell", "dumpsys", "package", q.PACKAGE)
        require(re.search(r"\bprimaryCpuAbi=arm64-v8a\b", package) is not None
                and re.search(r"\bversionCode=21\b", package) is not None
                and re.search(r"\bversionName=0\.3\.2\b", package) is not None,
                "Updated APK is not the expected ARM64 version21/0.3.2")
        start("03-updated-start")
        require(digest(invoke(USER)) == digest(before), "Install-r lost the original snapshot or session")
        result["install_r_snapshot_session_preserved"] = True
        try:
            q.rpc(schema, port, START, request=request, request_id=IDS[0])
        except grpc.RpcError as error:
            require(error.code() == grpc.StatusCode.UNAUTHENTICATED, "Quest.Start did not enforce authentication")
        else:
            raise RuntimeError("Unauthenticated skip was accepted")
        require(digest(invoke(USER)) == digest(before), "Unauthenticated skip changed state")
        result["authentication_rejection_preserved"] = True
        final, receipt = exercise_skip(schema, invoke, master)
        result.update(main_live=receipt, native_skip_repeat_computed=True, repeat_grants_no_rewards_or_exp=True,
            full_score_timeline_conserved=True, opposite_mode_identity_rejection_preserved=True,
            all_unrelated_snapshot_fields_preserved=True)
        stop("04-computed-state-stop")
        settled_database = protected_database(qa)
        assert_database_preserved(schema, protected, settled_database, receipt)
        result.update(protected_database_tables_preserved=True, preexisting_attempts_preserved=True,
                      two_new_skip_attempts_persisted=True)
        start("05-cached-state-restart")
        require(digest(invoke(USER)) == digest(final), "Native restart lost settled state or the original session")
        live.assert_main_live_retries(schema, invoke, master, receipt)
        live.assert_main_live_mode_conflicts(schema, invoke, master, receipt)
        result["native_restart_cached_skip_preserved"] = True
        stop("06-final-stop")
        require(protected_database(qa) == settled_database, "Cached/rejected requests after restart changed private state")
        result.update(experimental_setting_preserved=True, ok=True, final_server_stopped=True)
    except BaseException as error:
        result["error_type"] = type(error).__name__
        result["error"] = "native_skip_qa_failed"
        raise
    finally:
        if verified and cleanup_needed:
            result["failure_cleanup_attempted"] = True
            try:
                confirmed = stop_owned_after_failure(qa, schema, port)
            except BaseException:
                confirmed = False
            result["failure_cleanup_status"] = "stopped" if confirmed else "unconfirmed"
            if confirmed:
                result["final_server_stopped"] = True
                requested, ready = False, False
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        result["startup_requested_when_finishing"] = requested
        result["server_ready_observed_when_finishing"] = ready
        if verified:
            for port in qa.forwarded:
                qa.adb("forward", "--remove", "tcp:" + str(port), check=False)
        # QA.close writes raw logcat; this credential-free proof must not call it.
        (args.artifacts / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
