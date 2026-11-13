"""The native upgrade gate must detect state/delta loss, not just RPC success."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

import qa_deck_upgrade as probe
from idoly_local.state import State


ROOT = Path(__file__).resolve().parents[2]
SPEC = spec_from_file_location("native_deck_test_contract", ROOT / "tests/test_gameplay.py")
contract = module_from_spec(SPEC)
SPEC.loader.exec_module(contract)
UNKNOWN = b"\xc8\xa3\x09\x7b"


@pytest.fixture
def case(tmp_path):
    schema = contract.synthetic_schema(tmp_path / "schema.pb")
    master = contract.master_dir.__wrapped__(tmp_path)
    game = contract.game.__wrapped__(tmp_path, schema, master)

    def unknowns(raw):
        value = schema.response_type(probe.USER).FromString(raw)
        value.MergeFromString(UNKNOWN)
        value.user.MergeFromString(UNKNOWN)
        for row in (*value.decks, *value.deckPositions):
            row.MergeFromString(UNKNOWN)
        return value.SerializeToString()

    game.state.mutate_snapshot(game.profile, schema.fingerprint, unknowns)
    before = contract.snapshot(game)
    request = schema.request_type(probe.SAVE)(number=1, name="Selected", deckEditType=4,
                                             questId="quest-1")
    request.userDeckPositions.add(position=1, cardId=before.cards[1].cardId)
    request.userDeckPositions.add(position=3, cardId=before.cards[0].cardId)
    response = schema.response_type(probe.SAVE).FromString(game.handle(probe.SAVE, request.SerializeToString()))
    return game, before, contract.snapshot(game), response, request


def test_actual_selected_save_delta_and_unknown_fields_are_accepted(case):
    _game, before, after, response, request = case
    assert probe.assert_saved(before, after, response, request) == 1
    assert UNKNOWN in after.SerializeToString()
    assert len(response.commonResponse.deletedData.deckPositions) == 3


@pytest.mark.parametrize("damage", ("manager", "unknown", "card", "sequence"))
def test_successful_rpc_cannot_hide_unrelated_snapshot_or_sequence_damage(case, damage):
    _game, before, after, response, request = case
    if damage == "manager":
        after.user.managerLevel += 1
    elif damage == "unknown":
        after.DiscardUnknownFields()
    elif damage == "card":
        after.cards[0].level += 1
    else:
        after.user.deckSequence += 1
    with pytest.raises(RuntimeError, match="unrelated|sequence"):
        probe.assert_saved(before, after, response, request)


@pytest.mark.parametrize("damage", ("selection", "missing_deleted", "other_delta", "deck_unknown"))
def test_layout_and_common_delta_failures_are_detected(case, damage):
    _game, before, after, response, request = case
    if damage == "selection":
        after.deckPositions[0].cardId = before.cards[-1].cardId
    elif damage == "missing_deleted":
        del response.commonResponse.deletedData.deckPositions[:]
    elif damage == "other_delta":
        response.commonResponse.updatedData.items.add(itemId="unexpected", amount=1)
    else:
        after.decks[0].DiscardUnknownFields()
    with pytest.raises(RuntimeError, match="layout|Removed-slot|unexpected update|selected name"):
        probe.assert_saved(before, after, response, request)


def test_created_deck_sequence_is_verified_from_actual_existing_numbers(case):
    game, _before, _after, _response, _request = case
    before = contract.snapshot(game)
    request = game.schema.request_type(probe.SAVE)(number=0, name="New", deckEditType=3,
                                                  questId="quest-1")
    request.userDeckPositions.add(position=5, cardId=before.cards[0].cardId)
    response = game.schema.response_type(probe.SAVE).FromString(game.handle(probe.SAVE, request.SerializeToString()))
    after = contract.snapshot(game)
    assert probe.assert_saved(before, after, response, request) == 2
    assert [row.number for row in response.commonResponse.updatedData.decks] == [2]
    assert [(row.number, row.position) for row in response.commonResponse.updatedData.deckPositions] == [(2, 5)]
    assert response.commonResponse.updatedData.user == after.user
    response.commonResponse.updatedData.ClearField("user")
    with pytest.raises(RuntimeError, match="unexpected update field"):
        probe.assert_saved(before, after, response, request)


@pytest.mark.parametrize("field", ("decks", "deckPositions"))
def test_created_deck_ack_rejects_resending_unrelated_existing_rows(case, field):
    game, _before, _after, _response, _request = case
    before = contract.snapshot(game)
    request = game.schema.request_type(probe.SAVE)(number=0, name="Only new deck", deckEditType=3,
                                                  questId="quest-1")
    request.userDeckPositions.add(position=5, cardId=before.cards[0].cardId)
    response = game.schema.response_type(probe.SAVE).FromString(game.handle(probe.SAVE, request.SerializeToString()))
    after = contract.snapshot(game)
    assert probe.assert_saved(before, after, response, request) == 2
    getattr(response.commonResponse.updatedData, field).extend(getattr(before, field))
    with pytest.raises(RuntimeError, match="affected persisted deck"):
        probe.assert_saved(before, after, response, request)


def test_affected_deck_ack_must_retain_current_row_unknown_fields(case):
    _game, before, after, response, request = case
    response.commonResponse.updatedData.decks[0].DiscardUnknownFields()
    with pytest.raises(RuntimeError, match="affected persisted deck"):
        probe.assert_saved(before, after, response, request)


def test_empty_new_deck_ack_does_not_require_unrelated_occupied_positions(case):
    game, _before, _after, _response, _request = case
    before = contract.snapshot(game)
    request = game.schema.request_type(probe.SAVE)(number=0, name="Empty new deck", deckEditType=3,
                                                  questId="quest-1")
    response = game.schema.response_type(probe.SAVE).FromString(game.handle(probe.SAVE, request.SerializeToString()))
    after = contract.snapshot(game)
    assert probe.assert_saved(before, after, response, request) == 2
    assert [row.number for row in response.commonResponse.updatedData.decks] == [2]
    assert not response.commonResponse.updatedData.deckPositions
    assert response.commonResponse.updatedData.user == after.user


@pytest.mark.parametrize("condition", ("running_game", "running_server", "host_reverse", "other_target"))
def test_target_guard_rejects_conflicts_before_any_mutation(monkeypatch, condition):
    calls = []
    target = {"kind": "android_emulator" if condition == "other_target" else "cuttlefish_arm64_only"}
    monkeypatch.setattr(probe, "verify_disposable_target", lambda *_: target)

    def adb(*args, **kwargs):
        calls.append(args)
        if args[:3] == ("shell", "pidof", "-s"):
            if ((condition == "running_server" and args[-1] == probe.q.PACKAGE)
                    or (condition == "running_game" and args[-1] == "game.qualiarts.idolypride.local")):
                return "123\n"
            return ""
        if args == ("reverse", "--list"):
            return "UsbFfs tcp:50051 tcp:50051\n" if condition == "host_reverse" else ""
        raise AssertionError("Guard attempted an unexpected operation")

    qa = SimpleNamespace(command=["unused-adb", "-s", "127.0.0.1:6520"], adb=adb)
    with pytest.raises(RuntimeError):
        probe.guard_idle_owned_guest(qa)
    assert all(call[:3] == ("shell", "pidof", "-s") or call == ("reverse", "--list") for call in calls)


def test_future_non_snapshot_tables_and_receipts_are_not_ignored(tmp_path, monkeypatch):
    state = State(tmp_path / "original.db")
    state.save_snapshot("sandbox", b"before", "schema")
    state.login("sandbox")
    with state.connect() as db:
        db.execute("CREATE TABLE future_ledger (identity TEXT PRIMARY KEY, receipt BLOB)")
        db.execute("INSERT INTO future_ledger VALUES (?,?)", ("receipt", b"unchanged"))

    def backup(_qa, directory):
        destination = Path(directory) / "state.db"
        with state.connect() as source, sqlite3.connect(destination) as target:
            source.backup(target)
        destination.chmod(0o600)
        return destination

    monkeypatch.setattr(probe.q, "_copy_private_database", backup)
    before = probe.protected_database(object())
    assert "future_ledger" in before["rows"] and "snapshots" not in before["rows"]
    state.mutate_snapshot("sandbox", "schema", lambda raw: b"updated")
    assert probe.protected_database(object()) == before
    with state.connect() as db:
        db.execute("UPDATE future_ledger SET receipt=?", (b"lost",))
    assert probe.protected_database(object()) != before


def test_snapshot_identity_and_schema_cannot_change_behind_an_rpc_result(tmp_path, monkeypatch):
    state = State(tmp_path / "original.db")
    state.save_snapshot("sandbox", b"snapshot", "schema")

    def backup(_qa, directory):
        destination = Path(directory) / "state.db"
        with state.connect() as source, sqlite3.connect(destination) as target:
            source.backup(target)
        destination.chmod(0o600)
        return destination

    monkeypatch.setattr(probe.q, "_copy_private_database", backup)
    before = probe.protected_database(object())
    with state.connect() as db:
        db.execute("UPDATE snapshots SET schema_sha256=?", ("other-schema",))
    assert probe.protected_database(object()) != before

