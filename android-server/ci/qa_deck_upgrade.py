"""Verify the automatic-deck fix across an actual owned ARM64 APK update.

Inputs use normal Android UI and encrypted RPCs. Tokens and private DB rows
remain in memory or protected, automatically deleted temporary directories.
This driver never clears app data, calls a game callback, or computes a team.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tempfile
from zipfile import ZipFile

import grpc

import qa_emulator as q
from qa_profile_upgrade import clone, digest, require
from qa_target import verify_disposable_target


SAVE = "/api.Deck/Save"
USER = "/api.User/Get"
PAYLOAD_SHA256 = "3139ea69af1305a231ca09a3caab88a4496f1663c7a3af30892c588ed2cbc436"
MODE_LABEL = "첫 메인 라이브 실험 기능 사용"


def installed_hash(qa):
    paths = qa.adb("shell", "pm", "path", q.PACKAGE).splitlines()
    require(len(paths) == 1 and paths[0].startswith("package:"), "Installed server APK path is ambiguous")
    path = paths[0][len("package:"):]
    require(re.fullmatch(r"/data/app/[A-Za-z0-9_./=+~\-]+/base\.apk", path) is not None,
            "Installed server APK path is outside the fixed package location")
    values = qa.adb("shell", "sha256sum", path).split()
    require(values and re.fullmatch(r"[0-9a-f]{64}", values[0]) is not None,
            "Installed server APK hash is unavailable")
    return values[0]


def guard_idle_owned_guest(qa):
    """A forwarded host core must never masquerade as the installed APK."""
    target = verify_disposable_target(qa.adb, qa.command[-1])
    require(target["kind"] == "cuttlefish_arm64_only", "This proof requires the known ARM64-only Cuttlefish guest")
    for package in (q.PACKAGE, "game.qualiarts.idolypride.local",
                    "game.qualiarts.idolypride.local.diagnostics", "game.qualiarts.idolypride"):
        require(not qa.adb("shell", "pidof", "-s", package, check=False).strip(),
                "Native deck QA requires the server and game processes to be stopped")
    reverse = qa.adb("reverse", "--list")
    require(not re.search(r"\btcp:(?:50051|8080)\b", reverse),
            "Remove only the owned guest game/asset reverses before native APK QA")
    return target


def verify_payload(apk, expected_hash, data_root):
    require(hashlib.sha256(apk.read_bytes()).hexdigest() == expected_hash, "Updated APK hash mismatch")
    with ZipFile(apk) as archive:
        names = [name for name in archive.namelist() if name.endswith("ServerData.zip")]
        require(len(names) == 1, "Updated APK payload identity is ambiguous")
        with archive.open(names[0]) as stream:
            require(hashlib.file_digest(stream, "sha256").hexdigest() == PAYLOAD_SHA256,
                    "Deck patch must retain the verified unchanged public payload")
        with archive.open(names[0]) as stream, ZipFile(stream) as payload:
            for name in payload.namelist():
                if name.startswith(("data/protocol/", "data/master-json/")) and not name.endswith("/"):
                    path = PurePosixPath(name)
                    require(not path.is_absolute() and ".." not in path.parts, "Unsafe public QA input path")
                    local = data_root.joinpath(*path.parts[1:])
                    require(local.is_file() and payload.read(name) == local.read_bytes(),
                            "Updated protocol/master differs from the QA inputs")


def protected_database(qa):
    """Read every non-snapshot table without exporting rows or credentials."""
    with tempfile.TemporaryDirectory(prefix="idoly-deck-private-") as directory:
        path = q._copy_private_database(qa, directory)
        with sqlite3.connect(path) as db:
            q._checkpoint(db)
            tables = db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            require({"profiles", "sessions", "snapshots", "profile_settings", "starter_profiles",
                     "profile_lesson_progress", "main_live_attempts"}.issubset(name for name, _ in tables),
                    "Native state is missing required preservation tables")
            require(db.execute("SELECT name FROM profiles").fetchall() == [("sandbox",)],
                    "Deck QA accepts only its existing synthetic sandbox profile")
            rows = {}
            for name, definition in tables:
                require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is not None,
                        "Unexpected private table identity")
                if name == "snapshots":
                    continue
                cursor = db.execute('SELECT * FROM "' + name + '" LIMIT 0')
                order = ",".join(str(index + 1) for index in range(len(cursor.description)))
                values = db.execute('SELECT * FROM "' + name + '" ORDER BY ' + order).fetchall()
                rows[name] = (definition, values)
            metadata = db.execute("SELECT profile,schema_sha256 FROM snapshots ORDER BY profile").fetchall()
            require(len(metadata) == 1 and metadata[0][0] == "sandbox",
                    "Deck QA requires one existing synthetic snapshot")
            return {"definitions": tables, "rows": rows, "snapshot_metadata": metadata}


def mode_setting(qa, stage):
    tree = qa.capture(stage)
    boxes = [node for node in tree.iter("node")
             if node.get("text") == MODE_LABEL and node.get("class") == "android.widget.CheckBox"]
    require(len(boxes) == 1 and boxes[0].get("checked") in ("true", "false"),
            "Native experimental setting is ambiguous")
    return boxes[0].get("checked") == "true"


def row_bytes(rows):
    return [row.SerializeToString(deterministic=True) for row in rows]


def non_deck_snapshot(snapshot, sequence):
    value = clone(snapshot)
    value.ClearField("decks")
    value.ClearField("deckPositions")
    value.user.deckSequence = sequence
    return value.SerializeToString(deterministic=True)


def assert_saved(before, after, response, request):
    """Check client selection, exact deltas and independent unrelated state."""
    creating = request.number == 0
    number = max([before.user.deckSequence, *(row.number for row in before.decks)]) + 1 if creating else request.number
    require(non_deck_snapshot(after, before.user.deckSequence) == non_deck_snapshot(before, before.user.deckSequence),
            "Deck save changed unrelated snapshot state")
    require(after.user.deckSequence == (number if creating else before.user.deckSequence),
            "Deck save changed the sequence incorrectly")
    require(row_bytes(row for row in before.decks if row.number != number)
            == row_bytes(row for row in after.decks if row.number != number),
            "Deck save changed other decks or their order")
    require(row_bytes(row for row in before.deckPositions if row.number != number)
            == row_bytes(row for row in after.deckPositions if row.number != number),
            "Deck save changed other deck positions")
    decks = [row for row in after.decks if row.number == number]
    require(len(decks) == 1, "Saved deck identity is ambiguous")
    old_deck = next((row for row in before.decks if row.number == number), None)
    expected_deck = clone(old_deck) if old_deck is not None else type(decks[0])()
    expected_deck.number, expected_deck.name = number, request.name
    require(decks[0] == expected_deck, "Saved deck changed fields beyond its selected name")
    old_rows = [row for row in before.deckPositions if row.number == number]
    old_by_slot = {row.position: row for row in old_rows}
    saved = [row for row in after.deckPositions if row.number == number]
    require(len(saved) == len(request.userDeckPositions), "Server invented or dropped selected cards")
    for actual, selected in zip(saved, request.userDeckPositions):
        expected = clone(old_by_slot[selected.position]) if selected.position in old_by_slot else type(actual)()
        expected.number, expected.position = number, selected.position
        for field in ("cardId", "part1AccessoryId", "part2AccessoryId", "costumeId", "hairId"):
            setattr(expected, field, getattr(selected, field))
        del expected.photoIds[:]
        expected.photoIds.extend(selected.photoIds)
        require(actual == expected, "Saved layout differs from the explicit client selection")
    updated = response.commonResponse.updatedData
    expected_fields = {"decks", "deckPositions"} | ({"user"} if creating else set())
    require({field.name for field, _ in updated.ListFields()} == expected_fields,
            "Deck response contains an unexpected update field")
    require(row_bytes(updated.decks) == row_bytes(after.decks)
            and row_bytes(updated.deckPositions) == row_bytes(after.deckPositions),
            "Deck response delta differs from persisted deck data")
    if creating:
        require(updated.user == after.user, "New deck response omitted its assigned sequence")
    requested_slots = {row.position for row in request.userDeckPositions}
    removed = [row for row in old_rows if row.position not in requested_slots]
    deleted = response.commonResponse.deletedData
    require(row_bytes(deleted.deckPositions) == row_bytes(removed)
            and {field.name for field, _ in deleted.ListFields()} <= {"deckPositions"},
            "Removed-slot response differs from the original saved rows")
    return number


def exercise_decks(schema, invoke, initial, master_dir):
    """Submit selected owned cards; no optimizer or direct DB mutation."""
    before = clone(initial)
    settings = json.loads((master_dir / "Setting.json").read_text())
    require(len(settings) == 1 and len(before.decks) + 2 <= settings[0]["deckCountMax"],
            "Synthetic profile has insufficient room for two QA decks")
    master_cards = {row["id"] for row in json.loads((master_dir / "Card.json").read_text())}
    cards = [row.cardId for row in before.cards if row.cardId in master_cards]
    require(len(cards) >= 5 and len(cards) == len(set(cards)), "Needs five distinct owned master cards")
    target = min(row.number for row in before.decks)
    require(target > 0, "Needs an existing positive synthetic deck")
    full = [(slot, card) for slot, card in zip(range(1, 6), reversed(cards[:5]))]
    partial = [(1, cards[1]), (3, cards[0])]
    flags = {}

    def request(mode, number, positions, name):
        value = schema.request_type(SAVE)(number=number, name=name, deckEditType=mode,
                                          questId="qt-main-1-001-01")
        for slot, card in positions:
            value.userDeckPositions.add(position=slot, cardId=card)
        return value

    def save(value):
        nonlocal before
        response = invoke(SAVE, value)
        after = invoke(USER, schema.request_type(USER)())
        number = assert_saved(before, after, response, value)
        before = after
        return number

    save(request(4, target, full, "QA QuestAuto"))
    flags["quest_auto_existing_saved"] = True
    save(request(3, target, partial, "QA ManualAuto"))
    flags["manual_auto_partial_and_deleted_slots_saved"] = True
    created = [save(request(3, 0, full, "QA ManualAuto new")),
               save(request(4, 0, partial, "QA QuestAuto new"))]
    require(len(set(created)) == 2, "New deck identities are not distinct")
    flags["both_auto_modes_allocate_new_decks"] = True
    # Use an assigned identity for retry; Number=0 intentionally creates a new
    # deck and has no idempotency contract.
    value = request(4, created[-1], partial, "QA QuestAuto new")
    save(value)
    stable = digest(before)
    save(value)
    require(digest(before) == stable, "Retrying the assigned identity changed state")
    flags["assigned_deck_retry_preserved"] = True
    for status, value in (
        (grpc.StatusCode.INVALID_ARGUMENT, request(4, target, [(1, "qa-not-owned-card")], "QA invalid")),
        (grpc.StatusCode.INVALID_ARGUMENT, request(3, target, [(1, cards[0]), (1, cards[1])], "QA duplicate")),
        (grpc.StatusCode.UNIMPLEMENTED, request(0, target, full, "QA unknown mode")),
    ):
        try:
            invoke(SAVE, value)
        except grpc.RpcError as error:
            require(error.code() == status, "Deck rejection returned the wrong RPC status")
        else:
            raise RuntimeError("Invalid deck selection was accepted")
        require(digest(invoke(USER, schema.request_type(USER)())) == digest(before),
                "Rejected deck selection changed state")
    borrowed = request(4, target, [(1, cards[0])], "QA no buddy")
    borrowed.userDeckPositions[0].buddyUserId = "qa-unavailable-buddy"
    try:
        invoke(SAVE, borrowed)
    except grpc.RpcError as error:
        require(error.code() == grpc.StatusCode.UNIMPLEMENTED, "Unsupported buddy returned the wrong status")
    else:
        raise RuntimeError("Unsupported borrowed buddy was accepted")
    require(digest(invoke(USER, schema.request_type(USER)())) == digest(before), "Rejected buddy changed state")
    flags["invalid_and_buddy_rejections_preserved"] = True
    # Leave a complete ordinary unit, while also checking both prior modes.
    save(request(1, target, full, "QA manual retained"))
    save(request(2, target, full, "QA auto retained"))
    flags["manual_and_auto_modes_retained"] = True
    require(non_deck_snapshot(before, initial.user.deckSequence)
            == non_deck_snapshot(initial, initial.user.deckSequence), "Deck scenarios changed unrelated state")
    flags["all_non_deck_snapshot_fields_preserved"] = True
    return before, flags


def main():
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
    args = parser.parse_args()
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
              "private_state_exported": False, "game_client_gameplay_tested": False,
              "diagnostics_collector_tested": False, "final_server_stopped": False}
    verified, startup_requested, ready_observed = False, False, False
    try:
        print("Native deck QA: verifying the idle owned ARM64 target and both APKs", flush=True)
        result["target_evidence"] = guard_idle_owned_guest(qa)
        verified = True
        result["baseline_installed_apk_sha256"] = installed_hash(qa)
        require(result["baseline_installed_apk_sha256"] == args.baseline_apk_sha256,
                "Installed baseline APK hash mismatch")
        verify_payload(args.new_apk, args.new_apk_sha256, args.data_root)
        schema = q.Schema.from_descriptor_set(args.data_root / "protocol/idolypride-6.1.1.pb")
        master = args.data_root / "master-json"
        port = qa.forward(50051)

        def start(stage, expected_mode=None):
            nonlocal startup_requested, ready_observed
            print("Native deck QA stage: " + stage, flush=True)
            qa.adb("shell", "am", "start", "-n", q.ACTIVITY)
            mode = mode_setting(qa, stage + "-mode")
            if expected_mode is not None:
                require(mode == expected_mode, "APK update/restart changed the experimental setting")
            qa.tap("서버 시작", stage)
            startup_requested, ready_observed = True, False
            q.wait_server(schema, port, timeout=args.startup_timeout)
            ready_observed = True
            return mode

        def stop(stage):
            nonlocal startup_requested, ready_observed
            print("Native deck QA stage: " + stage, flush=True)
            qa.tap("서버 중지", stage)
            q.wait_server(schema, port, expected=False, timeout=30)
            qa.adb("shell", "am", "force-stop", q.PACKAGE)
            require(not qa.adb("shell", "pidof", "-s", q.PACKAGE, check=False).strip(), "Native server did not stop")
            startup_requested, ready_observed = False, False

        mode = start("01-baseline-start")
        _, login = q.bootstrap(schema, port)
        token = login.gameAuthToken
        require(bool(token), "Baseline APK did not issue a local session")

        def invoke(path, request=None):
            return q.rpc(schema, port, path, token, request)

        before = invoke(USER)
        require(before.user.name == "NativeQA", "Deck update proof requires its existing synthetic QA profile")
        require(before.decks and len(before.cards) >= 5, "Synthetic baseline has no usable existing deck")
        selected = list(before.cards)[:5]
        for edit_mode in (3, 4):
            request = schema.request_type(SAVE)(number=before.decks[0].number, name="QA baseline rejected",
                                                deckEditType=edit_mode, questId="qt-main-1-001-01")
            for index, card in enumerate(selected, 1):
                request.userDeckPositions.add(position=index, cardId=card.cardId)
            try:
                invoke(SAVE, request)
            except grpc.RpcError as error:
                require(error.code() == grpc.StatusCode.UNIMPLEMENTED, "Baseline automatic save returned an unexpected status")
            else:
                raise RuntimeError("Baseline APK no longer reproduces the automatic-save bug")
            require(digest(invoke(USER)) == digest(before), "Rejected baseline automatic save changed state")
        result["baseline_modes3_and4_unimplemented_reproduced"] = True
        stop("02-baseline-stop")
        protected = protected_database(qa)
        print("Native deck QA: install-r updated APK without clearing data", flush=True)
        qa.adb("install", "-r", "-g", str(args.new_apk.resolve()))
        result["installed_apk_sha256"] = installed_hash(qa)
        require(result["installed_apk_sha256"] == args.new_apk_sha256, "Installed updated APK hash mismatch")
        package = qa.adb("shell", "dumpsys", "package", q.PACKAGE)
        require(re.search(r"\bprimaryCpuAbi=arm64-v8a\b", package) is not None
                and re.search(r"\bversionCode=20\b", package) is not None
                and re.search(r"\bversionName=0\.3\.1\b", package) is not None,
                "Updated APK is not the expected ARM64 version20/0.3.1")
        start("03-updated-start", mode)
        require(digest(invoke(USER)) == digest(before), "Install-r lost the original snapshot or session")
        result["install_r_snapshot_session_preserved"] = True
        # Verify unauthenticated access fails before any local deck mutation.
        request = schema.request_type(SAVE)(number=before.decks[0].number, deckEditType=4)
        try:
            q.rpc(schema, port, SAVE, request=request)
        except grpc.RpcError as error:
            require(error.code() == grpc.StatusCode.UNAUTHENTICATED, "Deck.Save did not enforce local authentication")
        else:
            raise RuntimeError("Unauthenticated deck save was accepted")
        require(digest(invoke(USER)) == digest(before), "Unauthenticated deck save changed snapshot")
        result["authentication_rejection_preserved"] = True
        final, flags = exercise_decks(schema, invoke, before, master)
        result.update(flags)
        stop("04-updated-state-stop")
        require(protected_database(qa) == protected, "Deck update changed non-snapshot private state")
        start("05-updated-state-restart", mode)
        require(digest(invoke(USER)) == digest(final), "Native restart lost deck state or the original session")
        result["native_restart_snapshot_session_preserved"] = True
        stop("06-final-stop")
        require(protected_database(qa) == protected, "Native restart changed protected private state")
        result.update(protected_database_tables_preserved=True, experimental_setting_preserved=True,
                      ok=True, final_server_stopped=True)
    except BaseException as error:
        result["error_type"] = type(error).__name__
        result["error"] = str(error) if isinstance(error, RuntimeError) else "Native deck QA operation failed"
        raise
    finally:
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        result["startup_requested_when_finishing"] = startup_requested
        result["server_ready_observed_when_finishing"] = ready_observed
        if verified:
            for port in qa.forwarded:
                qa.adb("forward", "--remove", "tcp:" + str(port), check=False)
        # Intentionally do not call QA.close: it writes raw logcat.
        (args.artifacts / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
