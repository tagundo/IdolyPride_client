"""Existing prepared translations affect display only, in both local modes."""
import copy
import hashlib
import json
import os

import pytest

from idoly_local.love import Love, load_display_text
from test_love import game, schema, settings, invoke, register, finish_first, progress, database, EV


def pack(tmp_path, *, language="ko", generic=None, raw=None):
    root = tmp_path / "translations" / language
    root.mkdir(parents=True)
    data = {"schema":1, "language":language, "ui":{}, "generic":generic or {"原文":"번역"},
            "split":{}, "phone":{}}
    raw = raw if raw is not None else json.dumps(data, ensure_ascii=False).encode()
    (root / "text.json").write_bytes(raw)
    report = {"schema":1, "language":language, "pack":{"name":"text.json", "bytes":len(raw),
              "sha256":hashlib.sha256(raw).hexdigest()}}
    (root / "text-manifest.json").write_text(json.dumps(report))
    return root


@pytest.mark.parametrize("platform", ["android", "ios"])
@pytest.mark.parametrize("language", ["ko", "en"])
def test_existing_prepared_generic_pack_is_selected_exactly_once(tmp_path, platform, language):
    root = pack(tmp_path, language=language, generic={"原文":"Available translation", "空":""})
    before = {p.name:p.read_bytes() for p in root.iterdir()}
    result = load_display_text(tmp_path, language=language, platform=platform)
    assert result == {"原文":"Available translation"}
    assert before == {p.name:p.read_bytes() for p in root.iterdir()}


def test_japanese_and_absent_optional_text_group_retain_original(tmp_path):
    assert load_display_text(tmp_path / "absent", language="ja", platform="ios") == {}
    assert load_display_text(tmp_path, language="ko", platform="android") == {}


@pytest.mark.parametrize("damage", ["digest", "size", "language", "schema", "duplicate", "map",
                                     "symlink", "fifo", "partial", "oversize"])
def test_corrupt_or_unsafe_text_group_is_rejected_with_fixed_code(tmp_path, damage):
    if damage == "duplicate":
        root = pack(tmp_path, raw=b'{"schema":1,"schema":1}')
    elif damage == "map":
        root = pack(tmp_path, generic={"source":None})
    else:
        root = pack(tmp_path)
    manifest = root / "text-manifest.json"
    if damage in ("digest", "size", "language", "schema"):
        data = json.loads(manifest.read_bytes())
        if damage == "digest":data["pack"]["sha256"] = "0" * 64
        elif damage == "size":data["pack"]["bytes"] += 1
        elif damage == "language":data["language"] = "en"
        else:data["schema"] = True
        manifest.write_text(json.dumps(data))
    if damage == "symlink":
        target = tmp_path / "outside.json"
        target.write_bytes((root / "text.json").read_bytes())
        (root / "text.json").unlink()
        (root / "text.json").symlink_to(target)
    elif damage == "fifo":
        (root / "text.json").unlink();os.mkfifo(root / "text.json")
    elif damage == "partial":
        manifest.unlink()
    elif damage == "oversize":
        with (root / "text.json").open("r+b") as stream:stream.truncate(4 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="^love_display_text_invalid$"):
        load_display_text(tmp_path, language="ko", platform="android")


@pytest.mark.parametrize("media", [False, True])
def test_only_output_labels_translate_without_rewriting_rules_progress_or_user_names(game, media):
    original = copy.deepcopy(game.plan)
    event = game.plan["events"][EV]
    table = {event["name"]:"Translated event", event["description"]:"Translated description",
             event["simpleName"]:"Translated short name", "Bad test end":"Translated ending",
             "Manager":"Must not replace a user name", EV:"Must not replace an ID"}
    game.love = Love(game.schema, game.state, "player", game.master, event_settings=settings(),
                     media_mode=media, clock=lambda:game.clock[0], display_text=table)
    game.love._prepared = game.plan
    table[event["name"]] = "Caller mutation must not change selected text"
    title = invoke(game, "Title").loveInfos[0]
    assert title.loveId == EV and title.description == "Translated description"
    assert title.assetId == event.get("assetId", EV)
    assert game.love.home_info()[1][0].name == "Translated event"
    register(game)
    end = finish_first(game, bad=True)
    assert end.storyEndName == "Translated ending"
    before_progress = game.state.love_progress("player", EV)
    before_db = database(game.state)
    top = invoke(game, "Top", loveId=EV)
    assert top.loveName == "Translated event" and top.loveSimpleName == "Translated short name"
    assert top.playerName == "Manager"
    assert top.storyEndInfos[0].name == "Translated ending"
    assert game.plan == original and game.state.love_progress("player", EV) == before_progress
    assert database(game.state) == before_db and progress(game)["player_name"] == "Manager"
    game.love = Love(game.schema, game.state, "player", game.master, event_settings=settings(),
                     media_mode=media, clock=lambda:game.clock[0])
    game.love._prepared = game.plan
    fallback = invoke(game, "Top", loveId=EV)
    assert fallback.loveName == event["name"] and fallback.storyEndInfos[0].name == "Bad test end"
    assert game.state.love_progress("player", EV) == before_progress


def test_authenticated_application_passes_selected_display_map_to_home_and_title(game, tmp_path):
    from idoly_local.application import Application
    from idoly_local.catalog import FixtureStore
    from test_love_application import request
    event = game.plan["events"][EV]
    app = Application(game.schema, game.state, FixtureStore(tmp_path / "fixtures", game.schema),
        profile="player", master_dir=game.master, event_settings=settings(),
        love_display_text={event["name"]:"Selected event", event["description"]:"Selected description"})
    app.love._prepared = game.plan
    app.love.clock = lambda:game.clock[0]
    app.gameplay.handle = lambda path, raw: b"" if path == "/api.Home/Enter" else None
    before = database(game.state)
    home = request(game, app, "/api.Home/Enter")
    title = request(game, app, "/api.Love/Title")
    assert home.eventInfo.loveEventInfos[0].name == "Selected event"
    assert title.loveInfos[0].description == "Selected description"
    assert game.plan["events"][EV] == event and database(game.state) == before
