"""Independent native-QA oracle for owned appearance acknowledgements/defaults."""
import json
from pathlib import Path

from google.protobuf import descriptor_pb2
import pytest

from idoly_local import appearance_qa as qa
from idoly_local.schema import Schema


UNKNOWN = b"\x80\x4b\x7b"


def _schema(path):
    file = descriptor_pb2.FileDescriptorProto(name="appearance-qa.proto", package="api", syntax="proto3")
    def message(name, definitions=()):
        target = file.message_type.add(name=name)
        for number, (name, kind, repeated) in enumerate(definitions, 1):
            field = target.field.add(name=name, number=number, label=3 if repeated else 1)
            if isinstance(kind, int):
                field.type = kind
            else:
                field.type, field.type_name = 11, ".api." + kind
    message("Empty")
    message("Manager", (("name", 9, False),))
    message("Balance", (("freeBalance", 5, False), ("paidBalance", 5, False)))
    message("CharacterRow", (("characterId", 9, False), ("favoriteCostumeId", 9, False),
        ("favoriteHairId", 9, False), ("liveCostumeId", 9, False), ("liveHairId", 9, False),
        ("activityExp", 3, False)))
    message("CostumeRow", (("costumeId", 9, False), ("checked", 8, False), ("obtainedTime", 3, False)))
    message("HairRow", (("hairId", 9, False), ("checked", 8, False)))
    message("ItemRow", (("itemId", 9, False), ("amount", 3, False)))
    message("DeckRow", (("number", 5, False), ("name", 9, False)))
    message("StoryRow", (("storyId", 9, False), ("statusType", 5, False)))
    message("UserGet", (("user", "Manager", False), ("characters", "CharacterRow", True),
        ("costumes", "CostumeRow", True), ("hairs", "HairRow", True), ("balance", "Balance", False),
        ("items", "ItemRow", True), ("decks", "DeckRow", True), ("stories", "StoryRow", True)))
    message("Common", (("updatedData", "UserGet", False), ("deletedData", "UserGet", False)))
    response = file.message_type.add(name="Action")
    response.field.add(name="commonResponse", number=9999, label=1, type=11, type_name=".api.Common")
    message("SetRequest", (("costumeId", 9, False), ("hairId", 9, False)))
    message("CostumeRequest", (("costumeId", 9, False),))
    message("HairRequest", (("hairId", 9, False),))
    message("BulkRequest", (("costumeIds", 9, True), ("hairIds", 9, True)))
    for service, method, request, output in (
            ("System", "Check", "Empty", "Empty"), ("User", "Get", "Empty", "UserGet"),
            ("Costume", "CheckCostume", "CostumeRequest", "Action"),
            ("Hair", "CheckHair", "HairRequest", "Action"),
            ("Costume", "CheckBulk", "BulkRequest", "Action"),
            ("Costume", "SetCostume", "SetRequest", "Action"),
            ("Costume", "SetLiveCostume", "SetRequest", "Action")):
        target = next((row for row in file.service if row.name == service), None)
        if target is None:
            target = file.service.add(name=service)
        target.method.add(name=method, input_type=".api." + request, output_type=".api." + output)
    descriptor = descriptor_pb2.FileDescriptorSet()
    descriptor.file.add().CopyFrom(file)
    path.write_bytes(descriptor.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(params=("small", "client-6.1.1"))
def game(request, tmp_path):
    if request.param == "small":
        schema = _schema(tmp_path / "schema.pb")
    else:
        path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
        if not path.is_file():
            pytest.skip("Optional recovered client descriptor is unavailable")
        schema = Schema.from_descriptor_set(path)
    master = tmp_path / "master"
    master.mkdir()
    tables = {name: [] for name in ("Character", "Costume", "Hair")}
    user = schema.response_type("/api.User/Get")()
    user.user.name = "Disposable QA profile"
    user.balance.freeBalance, user.balance.paidBalance = 30, 7
    user.items.add(itemId="existing-item", amount=5)
    user.decks.add(number=2, name="Existing unit")
    user.stories.add(storyId="existing-read", statusType=2)
    for suffix in ("a", "b"):
        owner, costume, hair = "char-" + suffix, "cos-" + suffix, "hair-" + suffix
        tables["Character"].append({"id": owner, "defaultCostumeId": costume, "defaultLiveCostumeId": costume})
        tables["Costume"].append({"id": costume, "characterId": owner, "defaultHairId": hair})
        tables["Hair"].append({"id": hair, "characterId": owner,
            "wearableCostumeIds": [costume], "notWearableCostumeIds": []})
        row = user.characters.add(characterId=owner, favoriteCostumeId=costume, favoriteHairId=hair,
            liveCostumeId=costume, liveHairId=hair, activityExp=17)
        row.MergeFromString(UNKNOWN)
        row = user.costumes.add(costumeId=costume, checked=True, obtainedTime=12345)
        row.MergeFromString(UNKNOWN)
        row = user.hairs.add(hairId=hair, checked=True)
        row.MergeFromString(UNKNOWN)
    # An unrelated owned row makes overbroad CheckBulk/Set acknowledgements observable.
    user.costumes.add(costumeId="cos-unrelated", checked=False, obtainedTime=98765)
    user.hairs.add(hairId="hair-unrelated", checked=False)
    user.MergeFromString(UNKNOWN)
    for name, rows in tables.items():
        (master / (name + ".json")).write_text(json.dumps(rows))
    calls = []
    class Transport:
        fault = None
        def invoke(self, path, request):
            calls.append((path, request))
            if path == "/api.User/Get":
                return type(user).FromString(user.SerializeToString())
            response = schema.response_type(path)()
            if path.endswith("CheckBulk") and not request.costumeIds and not request.hairIds:
                response.commonResponse.SetInParent()
                if self.fault == "empty-bulk":
                    response.commonResponse.updatedData.costumes.add().CopyFrom(user.costumes[0])
                if self.fault == "empty-bulk-delta":
                    response.commonResponse.updatedData.SetInParent()
                return response
            updated = response.commonResponse.updatedData
            updated.SetInParent()
            response.commonResponse.deletedData.SetInParent()
            if path.endswith(("SetCostume", "SetLiveCostume")):
                owner = next(row["characterId"] for row in tables["Costume"] if row["id"] == request.costumeId)
                row = next(row for row in user.characters if row.characterId == owner)
                prefix = "live" if path.endswith("SetLiveCostume") else "favorite"
                setattr(row, prefix + "CostumeId", request.costumeId)
                setattr(row, prefix + "HairId", request.hairId)
                updated.characters.add().CopyFrom(row)
            else:
                costume_ids = list(request.costumeIds) if path.endswith("CheckBulk") else ([request.costumeId] if path.endswith("CheckCostume") else [])
                hair_ids = list(request.hairIds) if path.endswith("CheckBulk") else ([request.hairId] if path.endswith("CheckHair") else [])
                for name, field, identities in (("costumes", "costumeId", costume_ids), ("hairs", "hairId", hair_ids)):
                    for identity in identities:
                        row = next(row for row in getattr(user, name) if getattr(row, field) == identity)
                        if self.fault != "ignored-check":
                            row.checked = True
                        getattr(updated, name).add().CopyFrom(row)
            if self.fault == "wallet": user.balance.paidBalance += 1
            if self.fault == "item": user.items[0].amount += 1
            if self.fault == "deck": user.decks[0].name = "Changed"
            if self.fault == "story": user.stories[0].statusType = 0
            if self.fault == "unknown": user.DiscardUnknownFields()
            if self.fault == "obtained": user.costumes[0].obtainedTime += 1
            if self.fault == "unrelated-checked": user.costumes[-1].checked = True
            if self.fault == "missing-deleted": response.commonResponse.ClearField("deletedData")
            if self.fault == "extra-common": updated.balance.CopyFrom(user.balance)
            if self.fault == "partial-character" and updated.characters:
                updated.characters[0].ClearField("activityExp")
            if self.fault == "empty-bulk" and path.endswith("CheckBulk") and not request.costumeIds and not request.hairIds:
                updated.costumes.add().CopyFrom(user.costumes[0])
            return response
    return schema, master, tables, user, calls, Transport()


def test_owned_defaults_report_actual_zero_changes_and_retry_with_new_receipt(game):
    schema, master, _tables, user, calls, transport = game
    before = user.SerializeToString(deterministic=True)
    receipt = qa.run_appearance_checks(schema, transport.invoke, master, label="unit")
    assert user.SerializeToString(deterministic=True) == before
    assert (receipt["rpc_count"], receipt["checked_costume_count"], receipt["checked_hair_count"], receipt["preference_field_count"]) == (5, 2, 2, 4)
    assert tuple(receipt[key] for key in ("costume_checked_changed_count", "hair_checked_changed_count",
        "favorite_changed_field_count", "live_changed_field_count", "preference_changed_field_count")) == (0, 0, 0, 0, 0)
    assert receipt["empty_bulk_no_change"] and receipt["exact_common"] and receipt["retries_no_change"]
    operations = [path for path, _request in calls if path != "/api.User/Get"]
    assert operations[:5] == ["/api.Costume/CheckCostume", "/api.Hair/CheckHair", "/api.Costume/CheckBulk",
                             "/api.Costume/SetCostume", "/api.Costume/SetLiveCostume"]
    qa.assert_appearance_snapshot(schema, memoryview(before), receipt)
    qa.assert_appearance_retries(schema, transport.invoke, master, receipt)
    assert user.SerializeToString(deterministic=True) == before and UNKNOWN in before


def test_unchecked_owned_acknowledgements_count_only_real_selected_changes(game):
    schema, master, _tables, user, _calls, transport = game
    for row in [*user.costumes[:2], *user.hairs[:2]]:
        row.checked = False
    receipt = qa.run_appearance_checks(schema, transport.invoke, master)
    assert receipt["costume_checked_changed_count"] == receipt["hair_checked_changed_count"] == 2
    assert not user.costumes[-1].checked and not user.hairs[-1].checked
    qa.assert_appearance_retries(schema, transport.invoke, master, receipt)


@pytest.mark.parametrize("fault", ("wallet", "item", "deck", "story", "unknown", "obtained",
    "unrelated-checked", "missing-deleted", "extra-common", "partial-character", "empty-bulk",
    "empty-bulk-delta"))
def test_qa_rejects_unrelated_state_or_inexact_common_responses(game, fault):
    schema, master, _tables, _user, _calls, transport = game
    transport.fault = fault
    with pytest.raises(RuntimeError):
        qa.run_appearance_checks(schema, transport.invoke, master)


def test_ignored_check_cannot_pass_when_selected_owned_row_is_unchecked(game):
    schema, master, _tables, user, _calls, transport = game
    user.costumes[0].checked = False
    transport.fault = "ignored-check"
    with pytest.raises(RuntimeError):
        qa.run_appearance_checks(schema, transport.invoke, master)


@pytest.mark.parametrize("fault", ("wrong-owner", "incompatible", "unowned", "duplicate"))
def test_qa_rejects_bad_master_or_ownership_before_sending_any_appearance_rpc(game, fault):
    schema, master, tables, user, calls, transport = game
    if fault == "wrong-owner":
        tables["Hair"][0]["characterId"] = "char-b"
    elif fault == "incompatible":
        tables["Hair"][0]["wearableCostumeIds"] = []
    elif fault == "unowned":
        del user.hairs[0]
    else:
        user.costumes.add().CopyFrom(user.costumes[0])
    (master / "Hair.json").write_text(json.dumps(tables["Hair"]))
    with pytest.raises(RuntimeError):
        qa.run_appearance_checks(schema, transport.invoke, master)
    assert [path for path, _request in calls] == ["/api.User/Get"]


def test_restart_must_match_new_snapshot_and_same_master_selection(game):
    schema, master, tables, user, _calls, transport = game
    receipt = qa.run_appearance_checks(schema, transport.invoke, master)
    user.stories[0].statusType = 1
    with pytest.raises(RuntimeError, match="snapshot"):
        qa.assert_appearance_retries(schema, transport.invoke, master, receipt)
    user.stories[0].statusType = 2
    receipt["selection_sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="selection"):
        qa.assert_appearance_retries(schema, transport.invoke, master, receipt)
