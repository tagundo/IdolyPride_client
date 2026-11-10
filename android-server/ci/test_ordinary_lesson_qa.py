"""Ensure native QA rejects lost clock/resource rows rather than reporting success."""
from importlib.util import module_from_spec, spec_from_file_location
import hashlib
from pathlib import Path
import sqlite3

import pytest

from idoly_local.schema import Schema
from idoly_local.state import State


SPEC = spec_from_file_location("android_ordinary_lesson_qa", Path(__file__).with_name("qa_emulator.py"))
qa = module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


@pytest.mark.parametrize("changed", (None, "clock", "schema", "resources"))
def test_stopped_native_database_must_preserve_claimed_clock_and_resource_snapshot(tmp_path, monkeypatch, changed):
    descriptor = Path(__file__).resolve().parents[2] / "data/protocol/idolypride-6.1.1.pb"
    if not descriptor.is_file():
        pytest.skip("Recovered client descriptor is unavailable")
    schema = Schema.from_descriptor_set(descriptor)
    snapshot = schema.response_type("/api.User/Get")()
    snapshot.user.managerExp, snapshot.user.managerLevel = 118, 3
    snapshot.user.tutorialClearedTime = 1790000000000
    snapshot.totalCount.pointGoldAmount = 10
    snapshot.points.add(pointType=1, amount=12)
    snapshot.items.add(itemId="item-card_enhance", amount=103)
    snapshot.tutorials.add(tutorialType=1, step=150)
    progress = schema.response_type("/api.Activity/ReceiveLessonReward")().progress
    progress.currentAreaId = "area-main-001"
    progress.lastReceiveTime = 1790000010000
    progress.maxRewardTime = progress.lastReceiveTime + 12 * 60 * 60 * 1000
    progress.stepRewardGold, progress.stepRewardManagerExp, progress.stepRewardCardEnhanceItem = 5, 8, 3
    receipt = {"snapshot_sha256": hashlib.sha256(snapshot.SerializeToString(deterministic=True)).hexdigest(),
        "clock_sha256": hashlib.sha256(progress.SerializeToString(deterministic=True)).hexdigest(),
        "resource_totals": {"gold": 12, "manager_exp": 118, "manager_level": 3,
                            "enhance_items": 103, "lifetime_gold": 10}}
    state = State(tmp_path / "state.db")
    state.save_snapshot("sandbox", snapshot.SerializeToString(), schema.fingerprint, starter_version=4)
    state.mutate_lesson_snapshot("sandbox", schema.fingerprint,
        lambda raw, _clock: (raw, progress.SerializeToString()))
    if changed == "clock":
        progress.lastReceiveTime += 10000
        progress.maxRewardTime += 10000
        with sqlite3.connect(state.path) as connection:
            connection.execute("UPDATE profile_lesson_progress SET response=?", (progress.SerializeToString(),))
    elif changed == "schema":
        with sqlite3.connect(state.path) as connection:
            connection.execute("UPDATE profile_lesson_progress SET schema_sha256='other'")
    elif changed == "resources":
        snapshot.items[0].amount = 100
        state.mutate_snapshot("sandbox", schema.fingerprint, lambda _raw: snapshot.SerializeToString())
    monkeypatch.setattr(qa, "_copy_private_database", lambda device, directory: state.path)
    if changed:
        with pytest.raises(RuntimeError):
            qa.verify_ordinary_lesson_database(object(), schema, receipt)
    else:
        qa.verify_ordinary_lesson_database(object(), schema, receipt)
