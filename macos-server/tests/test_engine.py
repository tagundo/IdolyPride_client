from pathlib import Path
import json
import sys
import threading
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine


def test_home_hierarchy_reference_requires_both_master_rows(tmp_path):
    master = tmp_path / "master-json"
    master.mkdir()
    (master / "HierarchyDetailGrade.json").write_text(json.dumps([
        {"id": "hie-007-003", "hierarchyGradeId": "hie-007"}]))
    (master / "HierarchyGrade.json").write_text(json.dumps([{"id": "hie-007"}]))
    home = SimpleNamespace(hierarchyNotiInfo=SimpleNamespace(currentDetailGradeId="hie-007-003"))
    assert engine._home_hierarchy_reference(home, tmp_path) is True
    home.hierarchyNotiInfo.currentDetailGradeId = ""
    assert engine._home_hierarchy_reference(home, tmp_path) is False
    home.hierarchyNotiInfo.currentDetailGradeId = "missing"
    assert engine._home_hierarchy_reference(home, tmp_path) is False
    home.hierarchyNotiInfo.currentDetailGradeId = "hie-007-003"
    (master / "HierarchyGrade.json").write_text("[]")
    assert engine._home_hierarchy_reference(home, tmp_path) is False


def _client_schema():
    from idoly_local.schema import Schema
    descriptor = Path(__file__).resolve().parents[2] / "data/protocol/idolypride-6.1.1.pb"
    if not descriptor.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(descriptor)


def test_home_positions_require_four_distinct_owned_characters_and_original_home1():
    user = _client_schema().response_type("/api.User/Get")()
    for kind, character in enumerate(("char-ktn", "char-ngs", "char-mei", "char-suz"), 1):
        user.characters.add(characterId=character)
        user.homePositions.add(homePositionType=kind, characterId=character)
    assert engine._home_positions_distinct(user) is True
    user.homePositions[3].characterId = "char-ktn"
    assert engine._home_positions_distinct(user) is False
    user.homePositions[3].characterId = "unowned"
    assert engine._home_positions_distinct(user) is False
    user.homePositions[3].characterId = "char-suz"
    user.homePositions[0].characterId, user.homePositions[1].characterId = "char-ngs", "char-ktn"
    assert engine._home_positions_distinct(user) is False
    user.homePositions[0].characterId, user.homePositions[1].characterId = "char-ktn", "char-ngs"
    user.homePositions[3].homePositionType = 3
    assert engine._home_positions_distinct(user) is False
    user.homePositions[3].homePositionType = 4
    user.homePositions[3].isCharacterRandom = True
    assert engine._home_positions_distinct(user) is False


@pytest.fixture
def quest_catalog(tmp_path):
    schema = _client_schema()
    master = tmp_path / "master-json"
    master.mkdir()
    rows = {
        "AreaGroup": [{"id": "later", "order": 20, "areaIds": ["a3"]},
                      {"id": "first", "order": 10, "areaIds": ["a2", "a1"]},
                      {"id": "tutorial", "order": 999, "areaIds": ["tutorial"]}],
        "Area": [{"id": key, "type": 1, "areaGroupId": "later" if key == "a3" else "first",
                  "questIds": [key + "-q2", key + "-q1"]} for key in ("a1", "a2", "a3")]
                + [{"id": "tutorial", "type": 101, "questIds": ["tutorial-q"]}],
        "Quest": [{"id": key + suffix, "areaId": key} for key in ("a1", "a2", "a3")
                  for suffix in ("-q1", "-q2")] + [{"id": "tutorial-q", "areaId": "tutorial"}],
        "HierarchyDetailGrade": [{"id": "detail", "hierarchyGradeId": "grade"}],
        "HierarchyGrade": [{"id": "grade"}],
    }
    for name, values in rows.items():
        (master / (name + ".json")).write_text(json.dumps(values))
    top = schema.response_type("/api.Quest/Top")()
    top.pvpInfo.SetInParent()
    top.hierarchyNotiInfo.currentDetailGradeId = "detail"
    for group_id, area_ids in (("first", ("a2", "a1")), ("later", ("a3",))):
        group = top.mainAreaGroups.add(areaGroupId=group_id)
        for area_id in area_ids:
            area = group.areas.add(areaId=area_id)
            for suffix in ("-q2", "-q1"):
                area.quests.add(questId=area_id + suffix)
    top.mainAreaGroups[0].areas[0].unlocked = True
    top.mainAreaGroups[0].areas[0].quests[0].isPlayable = True
    return schema, top, rows, tmp_path


def _matching_main(schema, top):
    main = schema.response_type("/api.Quest/ListMain")()
    main.areaGroups.extend(top.mainAreaGroups)
    return main


def test_quest_catalog_uses_real_group_order_and_explicit_child_references(quest_catalog):
    schema, top, _rows, directory = quest_catalog
    assert engine._quest_catalog_reference(top, _matching_main(schema, top), directory) == "a2-q2"


@pytest.mark.parametrize("changed", ("different-list", "group-order", "area-order", "quest-order",
                                    "missing-pvp", "missing-hierarchy", "locked-first", "cleared-first",
                                    "wrong-area-parent", "wrong-quest-parent", "missing-main-area"))
def test_quest_catalog_rejects_mismatched_references_or_unusable_first_quest(quest_catalog, changed):
    schema, top, rows, directory = quest_catalog
    if changed == "group-order":
        copy = type(top)()
        copy.CopyFrom(top)
        del top.mainAreaGroups[:]
        top.mainAreaGroups.extend(reversed(copy.mainAreaGroups))
    elif changed in ("area-order", "quest-order"):
        container = top.mainAreaGroups[0].areas if changed == "area-order" else top.mainAreaGroups[0].areas[0].quests
        copies = [type(row)().FromString(row.SerializeToString()) for row in container]
        del container[:]
        container.extend(reversed(copies))
    elif changed == "missing-pvp":
        top.ClearField("pvpInfo")
    elif changed == "missing-hierarchy":
        top.hierarchyNotiInfo.currentDetailGradeId = "missing"
    elif changed == "locked-first":
        top.mainAreaGroups[0].areas[0].quests[0].isPlayable = False
    elif changed == "cleared-first":
        top.mainAreaGroups[0].areas[0].quests[0].cleared = True
    elif changed == "wrong-area-parent":
        rows["Area"][1]["areaGroupId"] = "later"
        (directory / "master-json/Area.json").write_text(json.dumps(rows["Area"]))
    elif changed == "wrong-quest-parent":
        rows["Quest"][3]["areaId"] = "a1"
        (directory / "master-json/Quest.json").write_text(json.dumps(rows["Quest"]))
    elif changed == "missing-main-area":
        rows["Area"].append({"id": "unlisted-main", "type": 1, "areaGroupId": "first", "questIds": ["hidden-q"]})
        (directory / "master-json/Area.json").write_text(json.dumps(rows["Area"]))
    main = _matching_main(schema, top)
    if changed == "different-list":
        main.areaGroups[0].areas[0].quests[0].highestScore = 10
    with pytest.raises(RuntimeError):
        engine._quest_catalog_reference(top, main, directory)


class Runtime:
    def __init__(self):
        self.running = True
        self.stops = 0

    def status(self):
        return {"running": self.running, "profile": "sandbox", "grpc_address": "127.0.0.1:50051",
                "asset_url": "http://127.0.0.1:8080", "logs": ["not repeated in status"]}

    def stop(self):
        self.running = False
        self.stops += 1


def wait_until(check):
    deadline = time.monotonic() + 3
    while not check() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert check()


def test_native_control_start_stop_does_not_duplicate_runtime_or_logs(tmp_path, monkeypatch):
    events, runtimes = [], []
    monkeypatch.setattr(engine, "install_payload", lambda *args: None)

    def start(*args, **kwargs):
        runtime = Runtime()
        runtimes.append(runtime)
        kwargs["log_callback"]("server ready")
        return runtime

    monkeypatch.setitem(sys.modules, "idoly_local.app_runtime", SimpleNamespace(start=start))
    import idoly_local
    monkeypatch.setattr(idoly_local, "app_runtime", sys.modules["idoly_local.app_runtime"], raising=False)
    controller = engine.Controller(tmp_path, tmp_path / "ServerData.zip", emit_event=lambda event, **data: events.append((event, data)))
    controller.start()
    wait_until(lambda: controller.runtime is not None)
    controller.start()
    assert len(runtimes) == 1
    assert controller.status()["running"] is True
    assert "logs" not in controller.status()
    controller.stop()
    assert runtimes[0].stops == 1
    assert controller.status()["running"] is False
    controller.close()
    assert runtimes[0].stops == 1
    assert any(event == "log" and data["message"] == "server ready" for event, data in events)


def test_quit_during_startup_cancels_owned_runtime_without_late_start(tmp_path, monkeypatch):
    entered, finish = threading.Event(), threading.Event()
    runtime = Runtime()
    monkeypatch.setattr(engine, "install_payload", lambda *args: None)

    def start(*args, **kwargs):
        entered.set()
        assert finish.wait(timeout=3)
        return runtime

    monkeypatch.setitem(sys.modules, "idoly_local.app_runtime", SimpleNamespace(start=start))
    import idoly_local
    monkeypatch.setattr(idoly_local, "app_runtime", sys.modules["idoly_local.app_runtime"], raising=False)
    controller = engine.Controller(tmp_path, tmp_path / "ServerData.zip", emit_event=lambda *args, **kwargs: None)
    controller.start()
    assert entered.wait(timeout=3)
    controller.stop()
    finish.set()
    wait_until(lambda: controller.worker is None)
    assert runtime.stops == 1
    assert controller.runtime is None
    assert controller.status()["running"] is False
    controller.close()


def test_stop_failure_retains_owned_runtime_for_retry(tmp_path):
    class RetryRuntime(Runtime):
        def stop(self):
            self.stops += 1
            self.running = False
            if self.stops == 1:
                raise RuntimeError("retry cleanup")

    runtime = RetryRuntime()
    controller = engine.Controller(tmp_path, tmp_path / "ServerData.zip", emit_event=lambda *args, **kwargs: None)
    controller.runtime = runtime
    assert controller.stop()["can_stop"] is True
    assert controller.runtime is runtime
    assert controller.stop()["can_stop"] is False
    assert controller.runtime is None
    assert runtime.stops == 2
