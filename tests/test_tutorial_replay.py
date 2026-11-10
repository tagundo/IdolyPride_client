"""Provider boundaries with independent templates; optional genuine-data audit.

The small fixture deliberately replaces only the validated-template loader.
It tests response copying, identity, resource prefetch and state boundaries.
The real pinned loader is exercised separately against available public data.
"""
import hashlib
import json
from pathlib import Path

from google.protobuf import descriptor_pb2
import pytest

from idoly_local import tutorial_replay as module
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_gameplay import synthetic_schema


PATH = "/api.Tutorial/StartQuest"


def small_schema(path):
    synthetic_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptors.file[0]
    manager = next(row for row in file.message_type if row.name == "Manager")
    manager.field.add(name="emblemId", number=1000, label=1, type=9)
    def message(name, fields):
        target = file.message_type.add(name=name)
        for number, (name, kind, repeated) in enumerate(fields, 1):
            field = target.field.add(name=name, number=number, label=3 if repeated else 1)
            if isinstance(kind, int):
                field.type = kind
            else:
                field.type, field.type_name = 11, ".api." + kind
    def fields(*values):
        return [(name, kind, False) for name, kind in values]
    message("ReplayCard", fields(("index", 5), ("cardId", 9), ("displayCharacterId", 9),
                                  ("displayCostumeId", 9), ("displayHairId", 9), ("level", 5), ("rarity", 5)))
    message("ReplayExtra", fields(("position", 5), ("characterId", 9), ("costumeId", 9), ("hairId", 9)))
    message("ReplayDeck", fields(("deckName", 9)) + [("cards", "ReplayCard", True), ("extraCharacterInfos", "ReplayExtra", True)])
    message("ReplayUserResult", fields(("score", 3)))
    message("ReplayUser", fields(("index", 5), ("userId", 9), ("name", 9), ("emblemId", 9),
                                  ("userDeck", "ReplayDeck"), ("userResult", "ReplayUserResult"), ("isNpc", 8)))
    message("ReplayChart", fields(("number", 5), ("chartType", 5)))
    message("ReplayResult", [("userInfos", "ReplayUser", True), ("charts", "ReplayChart", True)]
            + fields(("cleared", 8), ("detailLogId", 9), ("isDisplayDetailAvailable", 8)))
    message("ReplayRank", fields(("rankType", 5), ("plus", 5), ("thresholdScore", 3)))
    message("ReplayRequest", fields(("questId", 9)))
    message("ReplayResponse", fields(("result", "ReplayResult"), ("commonResponse", "CommonResponse"))
            + [("rankPatterns", "ReplayRank", True)])
    message("Asset", fields(("characterId", 9), ("costumeId", 9), ("hairId", 9)))
    message("AssetRequest", fields(("questId", 9), ("deckNumber", 5), ("buddyDeckName", 9))
            + [("userBuddyDeckPositions", "RequestedDeckPosition", True)])
    message("AssetResponse", fields(("commonResponse", "CommonResponse")) + [("characterAssets", "Asset", True)])
    next(row for row in file.service if row.name == "Tutorial").method.add(
        name="StartQuest", input_type=".api.ReplayRequest", output_type=".api.ReplayResponse")
    file.service.add(name="Quest").method.add(name="ListAsset", input_type=".api.AssetRequest", output_type=".api.AssetResponse")
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("replay-schema") / "schema.pb")
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def game(schema, tmp_path, monkeypatch):
    master, directory = tmp_path / "master", tmp_path / "public-tutorial"
    master.mkdir()
    directory.mkdir()
    names = ("ktn", "ngs", "mei", "suz", "ski", "skr", "chs", "rei", "szk")
    demo = ("skr", "ngs", "ktn", "chs", "rei")
    rows = {
        "Setting": [{"tutorialShortQuestId": "qt-tutorial-short", "tutorialFullQuestId": "qt-tutorial-full"}],
        "Quest": [{"id": "qt-main-001", "areaId": "area-main"},
                  {"id": "qt-tutorial-short", "areaId": "area-tutorial"},
                  {"id": "qt-tutorial-full", "areaId": "area-tutorial"}],
        "Area": [{"id": "area-main", "type": 1}, {"id": "area-tutorial", "type": 101}],
        "Card": [{"id": "card-" + key + "-03-schl-00", "characterId": "char-" + key} for key in names],
        "Character": [{"id": "char-" + key, "defaultLiveCostumeId": "cos-" + key + "-schl-00",
                       "defaultCostumeId": "cos-" + key + "-schl-00"} for key in names],
        "Costume": [{"id": "cos-" + key + "-schl-00", "characterId": "char-" + key,
                     "defaultHairId": "hair-" + key + "-schl-00"} for key in names],
        "Hair": [{"id": "hair-" + key + "-schl-00", "characterId": "char-" + key,
                  "wearableCostumeIds": ["cos-" + key + "-schl-00"]} for key in names],
        "Emblem": [{"id": "emblem-default"}, {"id": "emblem-local"}],
    }
    for table, values in rows.items():
        (master / (table + ".json")).write_text(json.dumps(values))
    (master / "!version.txt").write_text("unit-master")
    templates, entries = {}, []
    for kind, extra in (("short", "mei"), ("full", "szk")):
        response = schema.response_type(PATH)()
        response.commonResponse.SetInParent()
        result = response.result
        result.cleared = True
        user = result.userInfos.add(index=1, emblemId="emblem-default")
        user.userDeck.deckName = "Canonical demonstration"
        user.userResult.score = 100 if kind == "short" else 120
        assets = []
        for index, key in enumerate(demo, 1):
            user.userDeck.cards.add(index=index, cardId="card-" + key + "-03-schl-00", displayCharacterId="char-" + key,
                displayCostumeId="cos-" + key + "-schl-00", displayHairId="hair-" + key + "-schl-00", level=1, rarity=3)
            assets.append(("char-" + key, "cos-" + key + "-schl-00", "hair-" + key + "-schl-00"))
        user.userDeck.extraCharacterInfos.add(position=6, characterId="char-" + extra,
            costumeId="cos-" + extra + "-schl-00", hairId="hair-" + extra + "-schl-00")
        assets.append(("char-" + extra, "cos-" + extra + "-schl-00", "hair-" + extra + "-schl-00"))
        result.charts.add(number=1, chartType=1)
        result.charts.add(number=2, chartType=1)
        for rank, score in ((3, 120), (2, 100), (1, 0)):
            response.rankPatterns.add(rankType=rank, thresholdScore=score)
        payload = response.SerializeToString(deterministic=True)
        (directory / ("tutorial-" + kind + ".pb")).write_bytes(payload)
        quest_id = "qt-tutorial-" + kind
        templates[quest_id] = module._Replay(kind, quest_id, payload, tuple(assets), tuple(row.cardId for row in user.userDeck.cards))
        entries.append({"kind": kind, "quest_id": quest_id, "file": "tutorial-" + kind + ".pb",
                        "sha256": hashlib.sha256(payload).hexdigest()})
    (directory / "manifest.json").write_text(json.dumps({"replays": entries}))
    emblems = {row["id"]: row for row in rows["Emblem"]}
    # Isolate provider behavior from the genuine, separately tested validator.
    monkeypatch.setattr(module, "_load", lambda *_args: (templates, emblems, {"read_only": True}))
    state = State(tmp_path / "profiles.sqlite")
    identity = state.ensure_profile("player")
    snapshot = schema.response_type("/api.User/Get")()
    snapshot.user.name = "Local manager"
    snapshot.userPublic.serverUserId, snapshot.userPublic.publicUserId = identity["server_id"], identity["public_id"]
    snapshot.tutorials.add(tutorialType=1, step=10)
    snapshot.decks.add(number=1, name="Local deck")
    for key in names:
        snapshot.cards.add(cardId="card-" + key + "-03-schl-00", photoEquipableCount=2)
        snapshot.characters.add(characterId="char-" + key, liveCostumeId="cos-" + key + "-schl-00",
                                liveHairId="hair-" + key + "-schl-00")
        snapshot.costumes.add(costumeId="cos-" + key + "-schl-00")
        snapshot.hairs.add(hairId="hair-" + key + "-schl-00")
    for position, key in enumerate(names[:5], 1):
        snapshot.deckPositions.add(number=1, position=position, cardId="card-" + key + "-03-schl-00",
            costumeId="cos-" + key + "-schl-00", hairId="hair-" + key + "-schl-00")
    state.save_snapshot("player", snapshot.SerializeToString() + b"\xf8\x7f\x01", schema.fingerprint)
    token, _ = state.login("player")
    return module.TutorialReplays(schema, state, "player", master), state, master, rows, token, directory


def database(state):
    with state.connect() as db:
        return list(db.iterdump())


def invoke(game, kind="short"):
    provider = game[0]
    query = provider.schema.request_type(PATH)(questId="qt-tutorial-" + kind)
    return provider.schema.response_type(PATH).FromString(provider.handle(PATH, query.SerializeToString()))


def change(game, callback):
    provider, state = game[:2]
    def update(raw):
        snapshot = provider.schema.response_type("/api.User/Get").FromString(raw)
        callback(snapshot)
        return snapshot.SerializeToString()
    state.mutate_snapshot("player", provider.schema.fingerprint, update)


@pytest.mark.parametrize("kind", ("short", "full"))
def test_identity_only_changes_and_repeat_calls_preserve_entire_database(game, kind):
    before = database(game[1])
    canonical = game[0].schema.response_type(PATH).FromString((game[5] / ("tutorial-" + kind + ".pb")).read_bytes())
    observed = invoke(game, kind)
    identity = game[1].profile("player")
    assert observed.result.userInfos[0].userId == identity["public_id"] != identity["server_id"]
    assert observed.result.userInfos[0].name == "Local manager"
    observed.result.userInfos[0].userId = observed.result.userInfos[0].name = ""
    assert observed.SerializeToString(deterministic=True) == canonical.SerializeToString(deterministic=True)
    assert invoke(game, kind).result.charts == canonical.result.charts
    assert database(game[1]) == before


@pytest.mark.parametrize("emblem,expected", [("", "emblem-default"), ("missing", "emblem-default"), ("emblem-local", "emblem-local")])
def test_safe_emblem_is_display_metadata_without_ownership_mutation(game, emblem, expected):
    change(game, lambda user: setattr(user.user, "emblemId", emblem))
    before = database(game[1])
    assert invoke(game).result.userInfos[0].emblemId == expected
    assert database(game[1]) == before


def test_missing_owned_demo_card_is_rejected_without_granting_it(game):
    def remove(user):
        kept = [card for card in user.cards if card.cardId != "card-skr-03-schl-00"]
        del user.cards[:]
        user.cards.extend(kept)
    change(game, remove)
    before = database(game[1])
    with pytest.raises(RpcFailure) as failure:
        invoke(game)
    assert failure.value.code == RpcCode.FAILED_PRECONDITION
    assert database(game[1]) == before


def test_schema_mismatch_and_malformed_requests_fail_explicitly(game):
    with pytest.raises(RpcFailure) as failure:
        game[0].handle(PATH, b"\xff")
    assert failure.value.code == RpcCode.INVALID_ARGUMENT
    raw = game[1].snapshot("player")[0]
    game[1].save_snapshot("player", raw, "wrong-schema")
    with pytest.raises(RpcFailure) as failure:
        invoke(game)
    assert failure.value.code == RpcCode.FAILED_PRECONDITION


def test_disabled_provider_is_lazy_and_does_not_touch_schema_or_state(tmp_path):
    provider = module.TutorialReplays(object(), object(), "player", None)
    assert provider.handle(PATH, b"invalid") is None
    provider.append_assets(object(), object(), "anything")
    absent = module.TutorialReplays(object(), object(), "player", tmp_path / "master")
    assert absent.handle(PATH, b"") is None


def test_real_public_bundle_passes_validation_and_corruption_is_rejected(tmp_path):
    master = Path("/workspace/scratch/server0211-master-json")
    root = Path(__file__).resolve().parents[1]
    descriptor, bundle = root / "data/protocol/idolypride-6.1.1.pb", root / "data/public-tutorial"
    if not master.is_dir() or not descriptor.is_file() or not (bundle / "manifest.json").is_file():
        pytest.skip("Optional public master export/canonical bundle is unavailable")
    import shutil
    target = tmp_path / "public-tutorial"
    shutil.copytree(bundle, target)
    actual = Schema.from_descriptor_set(descriptor)
    report = module.validate_replays(actual, master, target)
    assert {row["kind"]: (row["charts"], row["score"]) for row in report["replays"]} == {
        "short": (158, 8813), "full": (156, 10717)}
    file = target / "tutorial-short.pb"
    file.write_bytes(file.read_bytes() + b"\x00")
    with pytest.raises(ValueError, match="digest"):
        module.validate_replays(actual, master, target)


def test_builder_validator_rejects_missing_bundle(tmp_path):
    with pytest.raises(ValueError):
        module.validate_replays(object(), tmp_path, tmp_path / "missing")


def test_builder_validator_rejects_non_object_manifest(tmp_path):
    (tmp_path / "manifest.json").write_text("[]")
    with pytest.raises(ValueError, match="manifest object"):
        module.validate_replays(object(), tmp_path, tmp_path)
