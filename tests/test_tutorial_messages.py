"""The finite opening conversation uses local state, no captured account rows."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from google.protobuf import descriptor_pb2
import pytest

from idoly_local import tutorial_messages as module
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_gameplay import synthetic_schema


PREFIX = "/api.Message/"
NOW = 1_800_000_000_123


def small_schema(path):
    synthetic_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptors.file[0]

    def message(name, fields):
        target = file.message_type.add(name=name)
        for number, (name, kind, repeated) in enumerate(fields, 1):
            field = target.field.add(name=name, number=number, label=3 if repeated else 1)
            field.type = kind if isinstance(kind, int) else 11
            if isinstance(kind, str):
                field.type_name = ".api." + kind

    def fields(*values):
        return [(name, kind, False) for name, kind in values]

    message("UserMessage", fields(("messageId", 9), ("messageStatusType", 5))
            + [("selectMessageDetailIds", 9, True)] + fields(("arrivedTime", 3)))
    message("MessageSchedule", fields(("messageId", 9), ("scheduledTime", 3)))
    for name in ("UserGetResponse", "UpdatedData"):
        target = next(row for row in file.message_type if row.name == name)
        target.field.add(name="messages", number=1001, label=3, type=11, type_name=".api.UserMessage")
        target.field.add(name="messageSchedules", number=1002, label=3, type=11, type_name=".api.MessageSchedule")
    next(row for row in file.message_type if row.name == "DeletedData").field.add(
        name="messageSchedules", number=1002, label=3, type=11, type_name=".api.MessageSchedule")
    message("Timeline", fields(("messageGroupId", 9), ("timelineId", 3), ("messageId", 9), ("arrivedTime", 3))
            + [("selectMessageDetailIds", 9, True)]
            + fields(("lastMessageDetailId", 9), ("lastMessageDetailTime", 3), ("finished", 8)))
    message("MessageGroup", fields(("messageGroupId", 9), ("latestTimelineInfo", "Timeline")))
    message("MessageGroups", [("infos", "MessageGroup", True)] + fields(("commonResponse", "CommonResponse")))
    message("TimelineRequest", fields(("messageGroupId", 9), ("timelineId", 3)))
    message("TimelineResponse", [("infos", "Timeline", True)] + fields(("hasNext", 8), ("commonResponse", "CommonResponse")))
    message("MessageSaveRequest", fields(("messageGroupId", 9), ("timelineId", 3), ("messageDetailId", 9))
            + [("selectMessageDetailIds", 9, True)])
    message("MessageFinishRequest", fields(("messageGroupId", 9), ("timelineId", 3))
            + [("selectMessageDetailIds", 9, True)])
    message("MessageFinishResponse", fields(("isReliabilityUp", 8), ("commonResponse", "CommonResponse")))
    message("MessageReceiveRequest", [("messageIds", 9, True)])
    service = file.service.add(name="Message")
    for name, request, response in (("ListGroup", "Empty", "MessageGroups"),
                                    ("Timeline", "TimelineRequest", "TimelineResponse"),
                                    ("Save", "MessageSaveRequest", "ActionResponse"),
                                    ("Finish", "MessageFinishRequest", "MessageFinishResponse"),
                                    ("Receive", "MessageReceiveRequest", "ActionResponse")):
        service.method.add(name=name, input_type=".api." + request, output_type=".api." + response)
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("messages-schema") / "schema.pb")
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def game(schema, tmp_path, monkeypatch):
    master = tmp_path / "master"
    master.mkdir()
    rows = {
        "Setting": [{"tutorialMessageId": "message-opening"}],
        "Character": [{"id": "char-guide"}],
        "MessageGroup": [{"id": "group-guide", "characterIds": ["char-guide"]}],
        "Message": [{"id": "message-opening", "messageGroupId": "group-guide", "type": 1,
            "characterId": "char-guide", "details": [
                {"messageDetailId": "incoming", "characterId": "char-guide", "text": "A local greeting",
                 "choiceText": "", "nextMessageDetailIds": ["reply"]},
                {"messageDetailId": "reply", "characterId": "", "text": "My reply", "choiceText": "My reply",
                 "nextMessageDetailIds": []}]}],
    }
    for table, values in rows.items():
        (master / (table + ".json")).write_text(json.dumps(values))
    state = State(tmp_path / "profiles.sqlite")
    snapshot = schema.response_type("/api.User/Get")()
    snapshot.user.name = "Existing manager"
    snapshot.user.managerLevel = 3
    snapshot.characters.add(characterId="char-guide", activityLevel=7)
    snapshot.cards.add(cardId="existing-card", level=8)
    snapshot.items.add(itemId="existing-item", amount=123)
    snapshot.tutorials.add(tutorialType=1, step=130)
    snapshot.messages.add(messageId="unrelated-message", messageStatusType=3,
                          arrivedTime=100, selectMessageDetailIds=["unrelated-choice"])
    snapshot.messageSchedules.add(messageId="unrelated-schedule", scheduledTime=200)
    state.save_snapshot("player", snapshot.SerializeToString() + b"\xf8\x7f\x01", schema.fingerprint)
    token, _ = state.login("player")
    other = schema.response_type("/api.User/Get")(user={"name": "Other manager"})
    state.save_snapshot("other", other.SerializeToString(), schema.fingerprint)
    state.mutate_snapshot("player", schema.fingerprint, lambda raw: raw, setting_info=b"local-settings")
    monkeypatch.setattr(module, "_now_ms", lambda: NOW)
    return module.TutorialMessages(schema, state, "player", master), state, master, rows, token


def call(game, name, **fields):
    service = game[0]
    path = PREFIX + name
    request = service.schema.request_type(path)(**fields)
    return service.schema.response_type(path).FromString(service.handle(path, request.SerializeToString()))


def snapshot(game):
    return game[0].schema.response_type("/api.User/Get").FromString(game[1].snapshot("player")[0])


def change(game, callback):
    def update(raw):
        user = game[0].schema.response_type("/api.User/Get").FromString(raw)
        callback(user)
        return user.SerializeToString()
    game[1].mutate_snapshot("player", game[0].schema.fingerprint, update)


def database(game):
    with game[1].connect() as db:
        return tuple(db.iterdump())


def latest(game):
    return call(game, "ListGroup").infos[0].latestTimelineInfo


def save_fields(info, *, incoming=False):
    return {"messageGroupId": info.messageGroupId, "timelineId": info.timelineId,
            "messageDetailId": "incoming" if incoming else "reply",
            "selectMessageDetailIds": [] if incoming else ["reply"]}


def finish_fields(info):
    return {"messageGroupId": info.messageGroupId, "timelineId": info.timelineId,
            "selectMessageDetailIds": ["reply"]}


@pytest.mark.parametrize("step", (0, 120))
def test_before_stage130_has_no_placeholder_or_snapshot_mutation(game, step):
    change(game, lambda user: setattr(user.tutorials[0], "step", step))
    before = database(game)
    result = call(game, "ListGroup")
    assert result.HasField("commonResponse") and not result.infos
    assert not call(game, "Timeline", messageGroupId="group-guide").infos
    with pytest.raises(RpcFailure) as failure:
        call(game, "Finish", messageGroupId="group-guide", timelineId=1, selectMessageDetailIds=["reply"])
    assert failure.value.code == RpcCode.FAILED_PRECONDITION
    assert database(game) == before


def test_first_read_creates_only_local_received_message_and_matching_schedule(game):
    before, other = snapshot(game), game[1].snapshot("other")
    result = call(game, "ListGroup")
    assert len(result.infos) == 1 and result.infos[0].HasField("latestTimelineInfo")
    info = result.infos[0].latestTimelineInfo
    assert result.infos[0].messageGroupId == info.messageGroupId == "group-guide"
    assert info.messageId == "message-opening" and info.arrivedTime == NOW
    assert 0 < info.timelineId < (1 << 63) and not info.finished
    assert not info.selectMessageDetailIds and not info.lastMessageDetailTime
    after = snapshot(game)
    message = next(row for row in after.messages if row.messageId == info.messageId)
    schedule = next(row for row in after.messageSchedules if row.messageId == info.messageId)
    assert message.messageStatusType == 3 and message.arrivedTime == schedule.scheduledTime == NOW
    assert [row.messageId for row in result.commonResponse.updatedData.messages] == [info.messageId]
    assert [row.messageId for row in result.commonResponse.updatedData.messageSchedules] == [info.messageId]
    kept_messages = [row for row in after.messages if row.messageId != info.messageId]
    kept_schedules = [row for row in after.messageSchedules if row.messageId != info.messageId]
    del after.messages[:]
    after.messages.extend(kept_messages)
    del after.messageSchedules[:]
    after.messageSchedules.extend(kept_schedules)
    assert after.SerializeToString() == before.SerializeToString()
    assert game[1].snapshot("other") == other and game[1].authenticated(game[4], "player")


def test_repeated_reads_and_restart_keep_identity_and_do_not_rewrite_state(game, monkeypatch):
    initial = latest(game)
    before = database(game)
    monkeypatch.setattr(module, "_now_ms", lambda: NOW + 9_000_000)
    assert not call(game, "ListGroup").commonResponse.SerializeToString()
    assert call(game, "Timeline", messageGroupId="group-guide").infos[0] == initial
    restarted = module.TutorialMessages(game[0].schema, State(game[1].path), "player", game[2])
    request = game[0].schema.request_type(PREFIX + "ListGroup")()
    response = game[0].schema.response_type(PREFIX + "ListGroup").FromString(
        restarted.handle(PREFIX + "ListGroup", request.SerializeToString()))
    assert response.infos[0].latestTimelineInfo == initial
    assert database(game) == before


def test_timeline_cursor_is_an_exclusive_upper_bound(game):
    info = latest(game)
    assert len(call(game, "Timeline", messageGroupId="group-guide").infos) == 1
    assert not call(game, "Timeline", messageGroupId="group-guide", timelineId=info.timelineId).infos
    assert not call(game, "Timeline", messageGroupId="group-guide", timelineId=info.timelineId - 1).infos
    if info.timelineId < (1 << 63) - 1:
        assert len(call(game, "Timeline", messageGroupId="group-guide", timelineId=info.timelineId + 1).infos) == 1


def test_save_persists_the_master_choice_without_finishing_or_rewarding(game):
    info = latest(game)
    before = database(game)
    assert not call(game, "Save", **save_fields(info, incoming=True)).commonResponse.SerializeToString()
    assert database(game) == before
    result = call(game, "Save", **save_fields(info))
    assert [field.name for field, _ in result.commonResponse.updatedData.ListFields()] == ["messages"]
    message = next(row for row in snapshot(game).messages if row.messageId == info.messageId)
    assert list(message.selectMessageDetailIds) == ["reply"] and message.messageStatusType == 3
    assert len(snapshot(game).messageSchedules) == 2
    saved = call(game, "Timeline", messageGroupId="group-guide").infos[0]
    assert list(saved.selectMessageDetailIds) == ["reply"] and saved.lastMessageDetailId == "reply"
    assert not saved.lastMessageDetailTime and not saved.finished
    before = database(game)
    assert not call(game, "Save", **save_fields(info)).commonResponse.SerializeToString()
    with pytest.raises(RpcFailure) as failure:
        call(game, "Save", **save_fields(info, incoming=True))
    assert failure.value.code == RpcCode.FAILED_PRECONDITION
    assert database(game) == before


def test_finish_is_atomic_reward_free_and_retry_safe_after_restart(game):
    info = latest(game)
    call(game, "Save", **save_fields(info))
    change(game, lambda user: setattr(user.tutorials[0], "step", 140))
    before = snapshot(game)
    result = call(game, "Finish", **finish_fields(info))
    assert not result.isReliabilityUp
    assert [field.name for field, _ in result.commonResponse.updatedData.ListFields()] == ["messages"]
    assert [row.messageId for row in result.commonResponse.deletedData.messageSchedules] == [info.messageId]
    after = snapshot(game)
    message = next(row for row in after.messages if row.messageId == info.messageId)
    assert message.messageStatusType == 4 and message.arrivedTime == NOW
    assert [row.messageId for row in after.messageSchedules] == ["unrelated-schedule"]
    assert after.user == before.user and after.cards == before.cards and after.items == before.items
    assert after.characters == before.characters and after.tutorials == before.tutorials
    assert after.messages[0] == before.messages[0]
    assert latest(game).finished
    whole = database(game)
    service = module.TutorialMessages(game[0].schema, State(game[1].path), "player", game[2])
    request = service.schema.request_type(PREFIX + "Finish")(**finish_fields(info))
    response = service.schema.response_type(PREFIX + "Finish").FromString(service.handle(PREFIX + "Finish", request.SerializeToString()))
    assert not response.commonResponse.SerializeToString() and not response.isReliabilityUp
    assert database(game) == whole and game[1].authenticated(game[4], "player")


def test_concurrent_initialization_and_finish_have_one_local_transition(game):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: call(game, "ListGroup"), range(8)))
    identities = {result.infos[0].latestTimelineInfo.timelineId for result in results}
    assert len(identities) == 1
    assert sum(len(result.commonResponse.updatedData.messages) for result in results) == 1
    assert sum(row.messageId == "message-opening" for row in snapshot(game).messages) == 1
    assert sum(row.messageId == "message-opening" for row in snapshot(game).messageSchedules) == 1
    info = results[0].infos[0].latestTimelineInfo
    with ThreadPoolExecutor(max_workers=8) as pool:
        replies = list(pool.map(lambda _: call(game, "Finish", **finish_fields(info)), range(8)))
    assert sum(len(reply.commonResponse.updatedData.messages) for reply in replies) == 1
    assert sum(len(reply.commonResponse.deletedData.messageSchedules) for reply in replies) == 1
    assert all(not reply.isReliabilityUp for reply in replies)


@pytest.mark.parametrize("fields", [
    {"messageGroupId": "wrong", "timelineId": 1, "messageDetailId": "reply", "selectMessageDetailIds": ["reply"]},
    {"messageGroupId": "group-guide", "timelineId": 0, "messageDetailId": "reply", "selectMessageDetailIds": ["reply"]},
    {"messageGroupId": "group-guide", "timelineId": -1, "messageDetailId": "reply", "selectMessageDetailIds": ["reply"]},
    {"messageGroupId": "group-guide", "timelineId": 1, "messageDetailId": "unknown", "selectMessageDetailIds": ["reply"]},
    {"messageGroupId": "group-guide", "timelineId": 1, "messageDetailId": "reply", "selectMessageDetailIds": []},
    {"messageGroupId": "group-guide", "timelineId": 1, "messageDetailId": "reply", "selectMessageDetailIds": ["reply", "reply"]},
    # Valid choices with an unrelated positive ID reach the transaction after
    # initialization; failure must roll the newly initialized rows back too.
    {"messageGroupId": "group-guide", "timelineId": 1, "messageDetailId": "reply", "selectMessageDetailIds": ["reply"]},
])
def test_invalid_save_never_creates_a_message_or_changes_any_table(game, fields):
    before = database(game)
    with pytest.raises(RpcFailure):
        call(game, "Save", **fields)
    assert database(game) == before


@pytest.mark.parametrize("problem", ("duplicate-message", "duplicate-schedule", "missing-owner", "invalid-status", "invalid-choices"))
def test_inconsistent_local_state_is_not_replaced_or_granted_over(game, problem):
    def corrupt(user):
        if problem == "missing-owner":
            del user.characters[:]
            return
        message = user.messages.add(messageId="message-opening", messageStatusType=3, arrivedTime=NOW)
        if problem == "duplicate-message":
            user.messages.add().CopyFrom(message)
        elif problem == "duplicate-schedule":
            for _ in range(2):
                user.messageSchedules.add(messageId="message-opening", scheduledTime=NOW)
        elif problem == "invalid-status":
            message.messageStatusType = 0
        else:
            message.selectMessageDetailIds.append("not-a-master-choice")
    change(game, corrupt)
    before = database(game)
    with pytest.raises(RpcFailure) as failure:
        call(game, "ListGroup")
    assert failure.value.code == RpcCode.FAILED_PRECONDITION
    assert database(game) == before


def test_receive_promotes_only_a_due_existing_tutorial_schedule(game):
    def scheduled(user):
        user.messages.add(messageId="message-opening", messageStatusType=2)
        user.messageSchedules.add(messageId="message-opening", scheduledTime=NOW - 1)
    change(game, scheduled)
    result = call(game, "Receive", messageIds=["message-opening"])
    assert result.commonResponse.updatedData.messages[0].messageStatusType == 3
    message = next(row for row in snapshot(game).messages if row.messageId == "message-opening")
    assert message.arrivedTime == NOW
    assert sum(row.messageId == message.messageId for row in snapshot(game).messageSchedules) == 1
    before = database(game)
    assert not call(game, "Receive", messageIds=["message-opening"]).commonResponse.SerializeToString()
    with pytest.raises(RpcFailure):
        call(game, "Receive", messageIds=["unrelated-message"])
    assert database(game) == before


def test_future_schedule_and_missing_profile_schema_are_rejected_without_replacement(game):
    def future(user):
        user.messages.add(messageId="message-opening", messageStatusType=2)
        user.messageSchedules.add(messageId="message-opening", scheduledTime=NOW + 1)
    change(game, future)
    before = database(game)
    with pytest.raises(RpcFailure):
        call(game, "Receive", messageIds=["message-opening"])
    assert database(game) == before
    game[1].save_snapshot("player", game[1].snapshot("player")[0], "other-schema")
    before = database(game)
    with pytest.raises(RpcFailure) as failure:
        call(game, "ListGroup")
    assert failure.value.code == RpcCode.FAILED_PRECONDITION
    assert database(game) == before


@pytest.mark.parametrize("problem", ("missing-group", "wrong-path", "reward", "telephone"))
def test_master_incompatibility_cannot_synthesize_another_conversation_or_reward(game, problem):
    rows = game[3]
    if problem == "missing-group":
        rows["MessageGroup"] = []
        table = "MessageGroup"
    else:
        table = "Message"
        detail = rows[table][0]["details"][0]
        if problem == "wrong-path":
            detail["nextMessageDetailIds"] = ["missing"]
        elif problem == "reward":
            detail["reliability"] = 1
        else:
            detail["telephoneId"] = "unsupported-phone"
    (game[2] / (table + ".json")).write_text(json.dumps(rows[table]))
    before = database(game)
    with pytest.raises(RpcFailure) as failure:
        call(game, "ListGroup")
    assert failure.value.code == RpcCode.FAILED_PRECONDITION
    assert database(game) == before


def test_malformed_request_and_disabled_provider_do_not_read_or_mutate_state(game):
    before = database(game)
    with pytest.raises(RpcFailure) as failure:
        game[0].handle(PREFIX + "Save", b"\x80")
    assert failure.value.code == RpcCode.INVALID_ARGUMENT
    assert database(game) == before
    disabled = module.TutorialMessages(object(), object(), "player")
    assert disabled.handle(PREFIX + "Save", b"invalid") is None
    assert game[0].handle("/api.Quest/Start", b"invalid") is None
