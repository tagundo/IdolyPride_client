"""Exercise native QA's private fixture round trip without an adb target."""
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from idoly_local.gameplay import (repair_starter_home_positions, repair_starter_inventory,
                                 repair_starter_roster, seed_starter_profile)
from idoly_local.schema import Schema
from idoly_local.state import State


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from test_gameplay import initial_inventory_rows
SPEC = spec_from_file_location("starter_native_qa", Path(__file__).with_name("qa_emulator.py"))
qa = module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


@pytest.fixture
def fixture(tmp_path):
    descriptor = ROOT / "data/protocol/idolypride-6.1.1.pb"
    if not descriptor.is_file():
        pytest.skip("Recovered client descriptor is unavailable")
    schema = Schema.from_descriptor_set(descriptor)
    master = tmp_path / "master"
    master.mkdir()
    rows = {"Setting": [{"id": 1, "tutorialPhotoShootingCharacterIds": list(qa.PHOTO_CHARACTERS)}],
        "Character": [], "Costume": [], "Hair": [],
        "CharacterActivityLevel": [{"level": 1, "maxStamina": 800}],
        "Area": [{"id": "area-1", "type": 1, "order": 1, "areaGroupId": "group-1", "questIds": ["quest-1"]},
                 {"id": "area-tutorial", "type": 101, "areaGroupId": "area-main-group-999", "questIds": ["qt-tutorial-full", "qt-tutorial-short"]},
                 {"id": "area-contest-001", "type": 2, "questIds": ["contest-" + str(i) for i in range(23)]}],
        "AreaGroup": [{"id": "group-1", "order": 1, "areaIds": ["area-1"]},
                      {"id": "area-main-group-999", "order": 999, "areaIds": ["area-tutorial"]}],
        "Quest": [{"id": "quest-1", "areaId": "area-1"},
                  {"id": "qt-tutorial-full", "areaId": "area-tutorial"}, {"id": "qt-tutorial-short", "areaId": "area-tutorial"},
                  *({"id": "contest-" + str(i), "areaId": "area-contest-001"} for i in range(23))],
        "HierarchyGrade": [{"id": "hie-007"}],
        "HierarchyDetailGrade": [{"id": "hie-007-003", "hierarchyGradeId": "hie-007",
                                  "requiredHierarchyPoint": "0", "requiredHierarchyRank": 0}]}
    rows["Setting"][0].update(cardDefaultMental=100, cardDefaultTechnique=100)
    rows.update(initial_inventory_rows(sorted(qa.STARTER_CHARACTERS)))
    for key in sorted(qa.STARTER_CHARACTERS):
        rows["Character"].append({"id": key, "type": 1, "defaultCostumeId": "cos-" + key,
                                  "defaultLiveCostumeId": "live-" + key})
        for prefix in ("cos-", "live-"):
            costume = prefix + key
            rows["Costume"].append({"id": costume, "characterId": key, "defaultHairId": "hair-" + costume})
            rows["Hair"].append({"id": "hair-" + costume, "characterId": key, "wearableCostumeIds": [costume]})
    for name, values in rows.items():
        (master / (name + ".json")).write_text(json.dumps(values))
    path = tmp_path / "original.db"
    state = State(path)
    seed_starter_profile(state, schema, "sandbox", master)
    def progress(payload):
        user = schema.response_type("/api.User/Get").FromString(payload)
        user.user.name = "Preserved manager"
        user.user.isReviewed = True
        user.user.lastLoginTime = 1794234000001
        user.totalCount.loginCount = 7
        user.tutorials[0].step = 10
        return user.SerializeToString()
    settings = schema.request_type("/api.Home/Login")().settingInfo
    settings.soundBgm = 37
    state.mutate_snapshot("sandbox", schema.fingerprint, progress, setting_info=settings.SerializeToString())
    token, _ = state.login("sandbox")
    # Copy a committed nonempty WAL, just as a force-stopped process can leave.
    hold = sqlite3.connect(path)
    settings.soundVoice = 61
    hold.execute("UPDATE profile_settings SET response=?", (settings.SerializeToString(),))
    hold.commit()
    files = {qa.PRIVATE_DATABASE: path.read_bytes(),
             qa.PRIVATE_DATABASE + "-wal": path.with_name(path.name + "-wal").read_bytes()}
    assert files[qa.PRIVATE_DATABASE + "-wal"]
    hold.close()
    user = schema.response_type("/api.User/Get").FromString(state.snapshot("sandbox")[0])
    return schema, master, token, files, user


class Device:
    command = ["fixture-adb", "-s", "emulator-5554"]

    def __init__(self, files):
        self.files = files

    def adb(self, *args, **kwargs):
        if args == ("shell", "getprop", "ro.kernel.qemu"):
            return "1\n"
        if args[:3] == ("shell", "pidof", "-s"):
            return ""
        if args[:4] == ("exec-out", "run-as", qa.PACKAGE, "cat"):
            return self.files.get(args[4], b"")
        if args[:5] == ("shell", "run-as", qa.PACKAGE, "rm", "-f"):
            for name in args[5:]:
                self.files.pop(name, None)
            return ""
        raise AssertionError("Unexpected fixture adb command")

    def run(self, command, **kwargs):
        if command[-3:-1] == ["test", "-s"]:
            return SimpleNamespace(returncode=0 if self.files.get(command[-1]) else 1)
        assert command[-2:] == ["dd", "of=" + qa.PRIVATE_DATABASE]
        assert kwargs["capture_output"] is True
        self.files[qa.PRIVATE_DATABASE] = kwargs["input"]
        return SimpleNamespace(returncode=0)


def test_both_native_legacy_fixture_cycles_preserve_all_allowed_state(fixture, tmp_path, monkeypatch):
    schema, master, token, files, user = fixture
    device = Device(files)
    monkeypatch.setattr(qa, "subprocess", SimpleNamespace(run=device.run))
    home1 = next(row.SerializeToString() for row in user.homePositions if row.homePositionType == 1)
    first_preserved = None
    for legacy_version in (None, 2, 3):
        legacy_roster = legacy_version is None
        inventory_only = legacy_version == 3
        legacy, preserved = qa.stage_legacy_starter(device, schema, user, master_dir=master,
                                                   legacy_roster=legacy_roster, inventory_only=inventory_only)
        assert len(legacy.characters) == (5 if legacy_roster else 17)
        assert not legacy.cards and not legacy.items and not legacy.deckPositions
        if not inventory_only:
            assert {row.characterId for row in legacy.homePositions} == {"char-ktn"}
        else:
            qa.assert_starter_home_positions(legacy)
        assert next(row.SerializeToString() for row in legacy.homePositions if row.homePositionType == 1) == home1
        if first_preserved is None:
            first_preserved = preserved
        assert preserved == first_preserved
        assert preserved["profile_settings"]  # Nonempty settings are actually covered.
        db_path = tmp_path / ("legacy" + str(legacy_version) + ".db")
        db_path.write_bytes(device.files[qa.PRIVATE_DATABASE])
        state = State(db_path)
        assert state.starter_version("sandbox") == legacy_version
        assert repair_starter_roster(state, schema, "sandbox", master) is legacy_roster
        assert repair_starter_home_positions(state, schema, "sandbox", master) is not inventory_only
        assert repair_starter_inventory(state, schema, "sandbox", master) is True
        assert state.starter_version("sandbox") == 4
        assert state.authenticated(token, "sandbox")
        user = schema.response_type("/api.User/Get").FromString(state.snapshot("sandbox")[0])
        qa.assert_starter_home_positions(user)
        qa.assert_starter_roster(user)
        qa.assert_initial_inventory(user, master)
        projected = qa._without_initial_inventory(user)
        if legacy_roster:
            projected = qa._legacy_projection(projected)
        if not inventory_only:
            projected = qa._legacy_home_projection(projected)
        assert projected.SerializeToString(deterministic=True) == legacy.SerializeToString(deterministic=True)
        assert user.user.name == "Preserved manager" and user.user.isReviewed
        assert user.totalCount.loginCount == 7 and user.tutorials[0].step == 10
        assert qa.QA_UNKNOWN_PB in user.SerializeToString()
        device.files = {qa.PRIVATE_DATABASE: db_path.read_bytes()}
        qa.verify_upgrade_database(device, first_preserved)
        saved = state.snapshot("sandbox")
        assert not repair_starter_inventory(state, schema, "sandbox", master)
        assert state.snapshot("sandbox") == saved


def test_quest_qa_checks_catalog_and_does_not_accept_a_fabricated_clear(fixture):
    from idoly_local.quest import Quest
    schema, master, _token, files, user = fixture
    # Open the recovered source DB through State rather than manufacturing responses.
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "state.db"
        path.write_bytes(files[qa.PRIVATE_DATABASE])
        path.with_name("state.db-wal").write_bytes(files[qa.PRIVATE_DATABASE + "-wal"])
        handler = Quest(schema, State(path), "sandbox", master)
        top = schema.response_type("/api.Quest/Top").FromString(handler.handle("/api.Quest/Top", b""))
        main = schema.response_type("/api.Quest/ListMain").FromString(handler.handle("/api.Quest/ListMain", b""))
        assert qa.assert_quest_catalog(top, main, master, user) == "quest-1"
        top.mainAreaGroups[0].areas[0].quests[0].cleared = True
        main.areaGroups[0].areas[0].quests[0].cleared = True
        with pytest.raises(RuntimeError, match="uncleared playable quest"):
            qa.assert_quest_catalog(top, main, master, user)


def test_quest_qa_requires_contest_and_the_snapshot_tutorial_context(fixture):
    from idoly_local.quest import Quest
    import tempfile
    schema, master, _token, files, user = fixture
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "state.db"
        path.write_bytes(files[qa.PRIVATE_DATABASE])
        path.with_name("state.db-wal").write_bytes(files[qa.PRIVATE_DATABASE + "-wal"])
        state = State(path)
        handler = Quest(schema, state, "sandbox", master)
        def responses():
            return tuple(schema.response_type(method).FromString(handler.handle(method, b""))
                         for method in ("/api.Quest/Top", "/api.Quest/ListMain"))
        top, main = responses()
        top.ClearField("contestArea")
        with pytest.raises(RuntimeError, match="23 real contest quests"):
            qa.assert_quest_catalog(top, main, master, user)
        top, main = responses()
        top.contestArea.quests[0].campaignDropRewardIds.append("fabricated")
        with pytest.raises(RuntimeError, match="23 real contest quests"):
            qa.assert_quest_catalog(top, main, master, user)
        top, main = responses()
        del top.mainAreaGroups[-1]
        del main.areaGroups[-1]
        with pytest.raises(RuntimeError, match="actual bundled main-live catalog"):
            qa.assert_quest_catalog(top, main, master, user)
        def completed(payload):
            snapshot = schema.response_type("/api.User/Get").FromString(payload)
            snapshot.tutorials[0].step = 150
            return snapshot.SerializeToString()
        state.mutate_snapshot("sandbox", schema.fingerprint, completed)
        done = schema.response_type("/api.User/Get").FromString(state.snapshot("sandbox")[0])
        top, main = responses()
        assert qa.assert_quest_catalog(top, main, master, done) == "quest-1"
        assert len(top.mainAreaGroups) == 1 and not qa.tutorial_pending(done)
