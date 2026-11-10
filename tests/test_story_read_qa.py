"""Independent story-read QA detects wallet, progress and restart regressions."""
import hashlib
import json

from google.protobuf import descriptor_pb2
import pytest

from idoly_local import story_read_qa as qa
from idoly_local.schema import Schema
import test_story_qa


def _rich_schema(path):
    descriptor = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptor.file[0]
    def fields(message, definitions):
        target = next((row for row in file.message_type if row.name == message), None)
        if target is None:
            target = file.message_type.add(name=message)
        for name, number, kind, repeated in definitions:
            field = target.field.add(name=name, number=number, label=3 if repeated else 1)
            if isinstance(kind, int):
                field.type = kind
            else:
                field.type, field.type_name = 11, ".api." + kind
    fields("Balance", (("freeBalance", 1, 5, False), ("paidBalance", 2, 5, False)))
    fields("UserData", (("managerExp", 1, 3, False), ("managerLevel", 2, 5, False)))
    fields("Resource", (("id", 1, 9, False), ("amount", 2, 3, False)))
    fields("UserStory", (("isInvalid", 3, 8, False), ("isUseActivatePhotoShootingStoryTicket", 4, 8, False),
                         ("isPhotoShot", 5, 8, False)))
    fields("UserGet", (("balance", 2, "Balance", False), ("user", 3, "UserData", False),
                       ("points", 4, "Resource", True), ("items", 5, "Resource", True)))
    fields("Progress", tuple((name, index, kind, False) for index, (name, kind) in enumerate((
        ("stepRewardGold", 5), ("stepRewardManagerExp", 5), ("stepRewardCardEnhanceItem", 5),
        ("rewardGoldAmount", 5), ("rewardManagerExpAmount", 5), ("rewardCardEnhanceItemAmount", 5),
        ("lastReceiveTime", 3), ("maxRewardTime", 3), ("dailyPromoteCount", 5), ("currentAreaId", 9)), 1)))
    fields("LessonInfo", (("lessonProgress", 1, "Progress", False),))
    fields("HomeResponse", (("lessonProgress", 1, "Progress", False), ("lessonInfo", 2, "LessonInfo", False)))
    fields("Reward", (("resourceType", 1, 5, False), ("resourceId", 2, 9, False),
        ("beforeAmount", 4, 3, False), ("afterAmount", 5, 3, False), ("isGift", 8, 8, False),
        ("amountI64", 11, 3, False)))
    fields("ReadRequest", (("storyId", 1, 9, False), ("isLast", 2, 8, False)))
    fields("EventRequest", (("eventStoryId", 1, 9, False), ("episode", 2, 5, False), ("isLast", 3, 8, False)))
    fields("ExtraRequest", (("extraStoryId", 1, 9, False), ("episode", 2, 5, False), ("isLast", 3, 8, False)))
    fields("ReadResponse", (("rewards", 1, "Reward", True), ("commonResponse", 9999, "Common", False)))
    service = next(row for row in file.service if row.name == "Story")
    for method, request in (("Read", "ReadRequest"), ("ReadEvent", "EventRequest"), ("ReadExtra", "ExtraRequest")):
        service.method.add(name=method, input_type=".api." + request, output_type=".api.ReadResponse")
    # Reuse only the progress message constructor in the existing clock checker.
    activity = file.service.add(name="Activity")
    fields("ReceiveResponse", (("progress", 1, "Progress", False),))
    activity.method.add(name="ReceiveLessonReward", input_type=".api.Empty", output_type=".api.ReceiveResponse")
    path.write_bytes(descriptor.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture
def game(tmp_path, monkeypatch):
    base, master, public, tables, responses, _calls, _invoke = test_story_qa.catalog.__wrapped__(tmp_path, monkeypatch)
    schema = _rich_schema(tmp_path / "schema.pb")
    responses = {path: schema.response_type(path).FromString(value.SerializeToString())
                 for path, value in responses.items()}
    # Canonical catalogs contain 426 appearances but 425 unique Story IDs.
    old = tables["ExtraStory"][-1]["episodes"][-1]["storyId"]
    tables["ExtraStory"][-1]["episodes"][-1]["storyId"] = tables["ExtraStory"][-1]["episodes"][-2]["storyId"]
    tables["Story"] = [row for row in tables["Story"] if row["id"] != old]
    extras = [row for row in tables["Story"] if row["id"].startswith("extra-")]
    for row in tables["Story"]:
        row["rewardId"] = "" if row in extras[:143] else "rd_auto;stone;;30"
    pins = {}
    manifest = json.loads((public / "manifest.json").read_text())
    manifest["schema_sha256"] = schema.fingerprint
    for kind, path in (("event", "/api.Story/ListEvent"), ("extra", "/api.Story/ListExtra")):
        response = responses[path]
        for info in response.infos:
            if kind == "extra":
                info.unlocked = True
            for story in info.stories if kind == "extra" else (info,):
                if kind == "extra":
                    story.unlocked = True
                for episode in story.episodes:
                    episode.unlocked = True
        raw = response.SerializeToString(deterministic=True)
        pins[kind] = (len(raw), hashlib.sha256(raw).hexdigest())
        (public / ("story-list-" + kind + ".pb")).write_bytes(raw)
        entry = next(row for row in manifest["catalogs"] if row["kind"] == kind)
        entry.update(bytes=len(raw), sha256=pins[kind][1])
    monkeypatch.setattr(test_story_qa.qa, "_PINS", pins)
    (public / "manifest.json").write_text(json.dumps(manifest))
    tables["Setting"] = [{"id": 1, "freeStoneLimit": "9999999"}]
    for name, rows in tables.items():
        (master / (name + ".json")).write_text(json.dumps(rows))
    user = responses["/api.User/Get"]
    user.stories[0].storyId = "unrelated-read-story-1"
    user.stories[0].isUseActivatePhotoShootingStoryTicket = True
    user.stories[1].isPhotoShot = True
    user.balance.freeBalance, user.balance.paidBalance = 100, 7
    user.user.managerExp, user.user.managerLevel = 8, 1
    user.points.add(id="gold", amount=5)
    user.items.add(id="enhance", amount=3)
    home = responses["/api.Home/Enter"]
    home.ClearField("extraStoryPartInfos")
    home.extraStoryPartInfos.extend(responses["/api.Story/ListExtra"].infos)
    home.lessonProgress.stepRewardGold, home.lessonProgress.stepRewardManagerExp = 5, 8
    home.lessonProgress.stepRewardCardEnhanceItem = 3
    home.lessonProgress.lastReceiveTime = 100000
    home.lessonProgress.maxRewardTime = 100000 + 12 * 60 * 60 * 1000
    home.lessonProgress.currentAreaId = "area-main-001"
    home.lessonInfo.lessonProgress.CopyFrom(home.lessonProgress)
    calls = []
    class Game:
        first = True
        fault = None
        def invoke(self, path, request):
            calls.append((path, request))
            if path in responses:
                return type(responses[path]).FromString(responses[path].SerializeToString())
            kind = "EventStory" if path.endswith("ReadEvent") else "ExtraStory"
            if path.endswith("/Read"):
                identity = request.storyId
            else:
                key = request.eventStoryId if kind == "EventStory" else request.extraStoryId
                parent = next(row for row in tables[kind] if row["id"] == key)
                identity = next(row["storyId"] for row in parent["episodes"] if row["episode"] == request.episode)
            reward = next(row["rewardId"] for row in tables["Story"] if row["id"] == identity) != ""
            existing = next((row for row in user.stories if row.storyId == identity), None)
            first = existing is None
            if first:
                existing = user.stories.add(storyId=identity, statusType=2)
            previous = user.balance.freeBalance
            if reward and (first or self.fault == "reward-twice"):
                user.balance.freeBalance += 30
            result = schema.response_type(path)()
            result.commonResponse.updatedData.stories.add().CopyFrom(existing)
            result.commonResponse.deletedData.SetInParent()
            if reward:
                result.commonResponse.updatedData.balance.CopyFrom(user.balance)
                if first or self.fault == "reward-twice":
                    result.rewards.add(resourceType=15, beforeAmount=previous,
                        afterAmount=user.balance.freeBalance, amountI64=30)
            if self.first:
                self.first = False
                if self.fault == "paid": user.balance.paidBalance += 1
                if self.fault == "flags": user.stories[0].isUseActivatePhotoShootingStoryTicket = False
                if self.fault == "unknown": user.DiscardUnknownFields()
                if self.fault == "gold": user.points[0].amount += 1
                if self.fault == "item": user.items[0].amount += 1
                if self.fault == "clock":
                    home.lessonProgress.lastReceiveTime += 10000
                    home.lessonProgress.maxRewardTime += 10000
                    home.lessonInfo.lessonProgress.CopyFrom(home.lessonProgress)
            if self.fault == "extra-reward" and not reward:
                result.rewards.add(resourceType=15, amountI64=30)
            if self.fault == "missing-deleted": result.commonResponse.ClearField("deletedData")
            if self.fault == "stale-wallet" and reward: result.commonResponse.updatedData.balance.freeBalance = previous
            if self.fault == "gift" and result.rewards: result.rewards[0].isGift = True
            return result
    state = Game()
    return schema, master, user, home, calls, state, tables


def test_skip_reward_finish_no_reward_retries_and_restart_preserve_exact_state(game):
    schema, master, user, home, calls, state, _tables = game
    receipt = qa.run_story_read_checks(schema, state.invoke, master, label="unit")
    assert (receipt["audited_story_count"], receipt["no_reward_story_count"], receipt["free_stone_story_count"]) == (425, 143, 282)
    assert receipt["story_rows_added"] == 2 and receipt["free_stone_delta"] == 30
    assert user.balance.freeBalance == 130 and user.balance.paidBalance == 7
    assert len(user.stories) == 4 and b"\x80\x4b\x7b" in user.SerializeToString()
    reads = [(path, request.isLast) for path, request in calls if path.startswith("/api.Story/Read")]
    assert reads[:4] == [("/api.Story/ReadEvent", False), ("/api.Story/ReadEvent", True),
                        ("/api.Story/Read", False), ("/api.Story/ReadExtra", True)]
    qa.assert_story_read_snapshot(schema, user.SerializeToString(), receipt)
    qa.assert_story_read_progress(schema, home.lessonProgress.SerializeToString(), receipt)
    qa.assert_story_read_retries(schema, state.invoke, master, receipt)


@pytest.mark.parametrize("fault", ("reward-twice", "paid", "flags", "unknown", "gold", "item", "clock",
                                  "extra-reward", "missing-deleted", "stale-wallet", "gift"))
def test_read_qa_rejects_incorrect_reward_projection_or_unrelated_mutations(game, fault):
    schema, master, _user, _home, _calls, state, _tables = game
    state.fault = fault
    with pytest.raises(RuntimeError):
        qa.run_story_read_checks(schema, state.invoke, master)


def test_qa_never_clears_existing_selected_progress(game):
    schema, master, user, _home, calls, state, _tables = game
    user.stories.add(storyId="event-0-1", statusType=2, isPhotoShot=True)
    with pytest.raises(RuntimeError, match="existing progress must never be cleared"):
        qa.run_story_read_checks(schema, state.invoke, master)
    assert [path for path, _request in calls] == ["/api.User/Get"]


def test_restart_requires_new_receipt_and_preserves_clock_and_wallet(game):
    schema, master, user, home, _calls, state, _tables = game
    receipt = qa.run_story_read_checks(schema, state.invoke, master)
    user.balance.paidBalance += 1
    with pytest.raises(RuntimeError, match="snapshot"):
        qa.assert_story_read_retries(schema, state.invoke, master, receipt)
    home.lessonProgress.lastReceiveTime += 10000
    with pytest.raises(RuntimeError, match="clock"):
        qa.assert_story_read_progress(schema, home.lessonProgress.SerializeToString(), receipt)


def test_independent_oracle_rejects_unreviewed_master_reward_before_any_rpc(game):
    schema, master, _user, _home, calls, state, tables = game
    tables["Story"][0]["rewardId"] = "rd_auto;paid_stone;;300"
    (master / "Story.json").write_text(json.dumps(tables["Story"]))
    with pytest.raises(RuntimeError, match="scope"):
        qa.run_story_read_checks(schema, state.invoke, master)
    assert calls == []
