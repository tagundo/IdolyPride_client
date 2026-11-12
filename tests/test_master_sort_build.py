import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from idoly_local.master_sort_build import build_sort_master_overlays, compose_sort_tag, sort_rows
from idoly_local.media_settings import DEFAULTS


@pytest.fixture
def catalog():
    return {"Music": [{"id": "c", "releaseTime": "300"}, {"id": "a", "releaseTime": "100"},
                      {"id": "b", "releaseTime": "300"}],
            "PhotoQuestMusic": [{"id": "c", "name": "zulu", "order": 5, "description": "keep"},
                                {"id": "a", "name": "beta", "order": 1, "description": "keep"},
                                {"id": "b", "name": "Alpha", "order": 3, "description": "keep"}],
            "Costume": [{"id": "c", "name": "가", "order": 5, "releaseDate": "100", "characterId": "owner"},
                        {"id": "a", "name": "다", "order": 1, "releaseDate": "300", "characterId": "owner"},
                        {"id": "b", "name": "나", "order": 3, "releaseDate": "200", "characterId": "owner"}]}


def ordered(rows):
    return [row["id"] for row in sorted(rows, key=lambda row: row["order"])]


def test_actual_release_dates_drive_rank_and_all_original_fields_are_preserved(catalog):
    before = copy.deepcopy(catalog)
    music = catalog["Music"]
    assert ordered(sort_rows("PhotoQuestMusic", catalog["PhotoQuestMusic"], "recent", music_rows=music)) == ["b", "c", "a"]
    assert ordered(sort_rows("PhotoQuestMusic", catalog["PhotoQuestMusic"], "old", music_rows=music)) == ["a", "b", "c"]
    assert ordered(sort_rows("PhotoQuestMusic", catalog["PhotoQuestMusic"], "title")) == ["b", "a", "c"]
    assert ordered(sort_rows("PhotoQuestMusic", catalog["PhotoQuestMusic"], "id")) == ["a", "b", "c"]
    assert ordered(sort_rows("Costume", catalog["Costume"], "recent")) == ["a", "b", "c"]
    assert ordered(sort_rows("Costume", catalog["Costume"], "old")) == ["c", "b", "a"]
    assert ordered(sort_rows("Costume", catalog["Costume"], "title")) == ["c", "b", "a"]
    assert sort_rows("Costume", catalog["Costume"], "original") == catalog["Costume"]
    changed = sort_rows("Costume", catalog["Costume"], "recent")
    for old, new in zip(catalog["Costume"], changed, strict=True):
        assert {k: v for k, v in old.items() if k != "order"} == {k: v for k, v in new.items() if k != "order"}
    assert catalog == before


@pytest.mark.parametrize("broken", [None, True, -1, "unknown", 1.5, str(2**63)])
def test_invalid_original_dates_are_not_invented_for_sorting(catalog, broken):
    catalog["Music"][0]["releaseTime"] = broken
    with pytest.raises(ValueError):
        sort_rows("PhotoQuestMusic", catalog["PhotoQuestMusic"], "recent", music_rows=catalog["Music"])
    catalog["Costume"][0]["releaseDate"] = broken
    with pytest.raises(ValueError):
        sort_rows("Costume", catalog["Costume"], "recent")


def base_tag():
    return {"version": "translated-base", "masterTagPacks": [
        {"type": table, "fileName": "base-" + table + ".db", "fileSize": 10,
         "cryptoKey": "a" * 64, "downloadUrl": "http://127.0.0.1:8080/master/base-" + table + ".db"}
        for table in ("Costume", "PhotoQuestMusic", "PreservedOther")]}


def test_offline_producer_builds_nine_packs_and_composes_only_two_entries(catalog, tmp_path, monkeypatch):
    calls = []

    def fake_builder(schema, source, output, *, tables):
        assert len(tables) == 1
        table = tables[0]
        raw = (source / (table + ".json")).read_bytes()
        calls.append(table)
        packs = output / "assets/master"
        packs.mkdir(parents=True)
        (packs / (table + ".db")).write_bytes(raw)
        tag = {"version": "fake-builder", "masterTagPacks": [{"type": table, "fileName": table + ".db",
            "fileSize": len(raw), "cryptoKey": "a" * 64, "downloadUrl": "http://127.0.0.1:8080/master/" + table + ".db"}]}
        (output / "master-tag.json").write_text(json.dumps(tag))

    monkeypatch.setattr("idoly_local.master_build.build_master_packs", fake_builder)
    original, before = base_tag(), copy.deepcopy(catalog)
    output = tmp_path / "sorts"
    manifest = build_sort_master_overlays(SimpleNamespace(), original, catalog, output, language="ko", source="media")
    assert len(calls) == 9 and len(list((output / "assets/master").iterdir())) == 9
    assert json.loads((output / "sort-manifest.json").read_text()) == manifest
    selected = compose_sort_tag(original, manifest, DEFAULTS | {"mv_sort": "title", "outfit_sort": "recent"})
    assert len(selected["masterTagPacks"]) == len(original["masterTagPacks"])
    assert selected["masterTagPacks"][2] == original["masterTagPacks"][2]
    assert selected["version"] != original["version"] and original == base_tag() and catalog == before
    for entry in selected["masterTagPacks"][:2]:
        expected = ["a", "b", "c"] if entry["type"] == "Costume" else ["b", "a", "c"]
        assert ordered(json.loads((output / "assets/master" / entry["fileName"]).read_bytes())) == expected
    # A hide/filter or revision edit must not redownload otherwise identical packs.
    again = compose_sort_tag(original, manifest, DEFAULTS | {"mv_sort": "title", "outfit_sort": "recent", "hide_video_mv": True, "revision": 100})
    assert again == selected
    with pytest.raises(ValueError):
        build_sort_master_overlays(SimpleNamespace(), original, catalog, output, language="ko", source="media")
    bad = copy.deepcopy(manifest)
    bad["base_version"] = "another-base"
    with pytest.raises(ValueError):
        compose_sort_tag(original, bad, DEFAULTS)
    bad = copy.deepcopy(manifest)
    bad["variants"]["Costume"]["original"]["pack"]["fileName"] = "../account.db"
    with pytest.raises(ValueError):
        compose_sort_tag(original, bad, DEFAULTS)
