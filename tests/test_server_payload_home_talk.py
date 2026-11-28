"""HomeTalk and the explicit gallery audience update preserve audited catalogs.

The expected bytes and row count come from the original 6.1.1 SQLCipher /
Protobuf projection, independently of the package builder's constants.
These tests inspect only small versioned inventories, never a game payload.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from tools import build_android_server_manual as tool


ROOT = Path(__file__).resolve().parents[1]
HOME_TALK = {"path": "data/master-json/HomeTalk.json", "bytes": 1068215,
             "sha256": "63f332a9cf291f32ff4d6b4f65dd0f2a72784f779fd94d250932597ef32dda38",
             "rows": 559}


# These literal pins describe the later v0.3.31 gallery-only audience change.
# They are independent of both the current inventory and builder constants.
AUDIENCE_SETTING_ROWS = [
    {"path": "data/original-master/assets/master/local-language-en-4808e008d3ac78f5ce62de20-Setting.db",
     "bytes": 12288, "sha256": "bf8fc9cc675f98c0d57ed23ab47224959580b9c66ecf31d10a9aed79a03d7470"},
    {"path": "data/original-master/assets/master/local-language-ko-e6f66206bc3851593d2ce459-Setting.db",
     "bytes": 12288, "sha256": "482b46f8ea96dcd35f05ed0cc1e4155127a8aac6e1067c3391ab0b15f6a2df6d"},
]
AUDIENCE_METADATA = {
    "data/original-master/languages/en/media-coverage.json":
        {"bytes": 53767, "sha256": "1f42defd409df2e2dd5559c8f75ef8d7ad81aa9b2f0d2228dc0e1b3d6abd0ab5"},
    "data/original-master/languages/en/media-master-sort.json":
        {"bytes": 3847, "sha256": "f82dfc984a20ce52b1c0d05b537821d0369aabfa1b6d4cdeba94f4ca0772f60c"},
    "data/original-master/languages/en/media-master-tag.json":
        {"bytes": 64896, "sha256": "c5869ba029424898a4868f7a3f04f9b46f8b8e7a677ebd788a0de267a75da38d"},
    "data/original-master/languages/ko/media-coverage.json":
        {"bytes": 53741, "sha256": "7ea7109832aaac0e3b85cda6525a6ff1a1b954a0e018baabf1f4f0033e17dd45"},
    "data/original-master/languages/ko/media-master-sort.json":
        {"bytes": 3847, "sha256": "7e8c6060e16953ea58c80d8d82b6d5bc9e16ac208b6016c44aa3202a9731d3b7"},
    "data/original-master/languages/ko/media-master-tag.json":
        {"bytes": 64896, "sha256": "cbd09c0314e8d3c6f2b1219ea2d92a071be4c9e0f8029c3426ea23fcba9cae50"},
    "data/original-master/media-master-sort.json":
        {"bytes": 3852, "sha256": "ff45cc1bd3b2df1daefec7eb93775112947b3a3d9fbfb5096f7a3fe724f04719"},
}
AUDIENCE_COMPONENT_COMMIT = "0462fc4672aacd8df42430fce910d0e072daa4b9"
AUDIENCE_SCOPE = (
    "Gallery-only audience minimum covers Mana/collaborator fan-derived fallback; "
    "original Setting and ordinary catalogs byte-identical"
)


def test_home_talk_inventory_preserves_the_audited_260_catalogs_and_two_ios_files():
    old_raw = (ROOT / "tools/server_payload_v0323.json").read_bytes()
    assert hashlib.sha256(old_raw).hexdigest() == "e775e49cfae0fe285d773145f7a5f871134ca3c28fd9a104811e76fa48170449"
    old = json.loads(old_raw)
    expected = deepcopy(old)
    expected["server_json_additions"] = [dict(HOME_TALK)]
    expected["component_commit"] = AUDIENCE_COMPONENT_COMMIT
    expected["component_sources"]["src/idoly_local/media_master_build.py"] = (
        "c5ccf938697ce5dadb135d7053c29495eaf03b57b0edc20db471158d49ffc794")
    expected["component_sources"]["src/idoly_local/media_profile.py"] = (
        "06914e9ddff360009a42f7261bee5559e60ba817a70cd80ce02134cd15a50a39")
    old_rows = {row["path"]: row for row in old["additions"]}
    assert len(old_rows) == len(old["additions"]) == 260
    assert len(old["component_sources"]) == 7
    assert set(AUDIENCE_METADATA) <= old_rows.keys()
    assert not {row["path"] for row in AUDIENCE_SETTING_ROWS} & old_rows.keys()
    for row in expected["additions"]:
        if row["path"] in AUDIENCE_METADATA:
            row.update(AUDIENCE_METADATA[row["path"]])
    expected["additions"].extend(deepcopy(AUDIENCE_SETTING_ROWS))
    expected["additions"].sort(key=lambda row: row["path"])
    proof = expected["prebuilt_catalogs"]
    proof["component_commit"] = AUDIENCE_COMPONENT_COMMIT
    proof["component_sources"] = deepcopy(expected["component_sources"])
    proof["catalog_inventory_sha256"] = "9949ac6008cf0708a7b56c50b892127c5d8cfdb4211a06800aff0e8f33196964"
    proof["added_members"] = 262
    proof["coverage"]["ko-media"]["version"] = (
        "local-language-ko-1a6ece8dd5ea96baa6eb52d8969082038310335430169780a3379e8d80b99c89")
    proof["coverage"]["en-media"]["version"] = (
        "local-language-en-4036548401a03ace4b6dc7dbf8e937331dda535cac93af2952871d60b2cc76f4")
    proof["scope"].append(AUDIENCE_SCOPE)
    # All coverage counts, ordinary catalogs, original DBs, iOS inputs and
    # unrelated provenance must survive the exact two documented transitions.
    current_raw = (ROOT / "tools/server_payload_v0331.json").read_bytes()
    assert hashlib.sha256(current_raw).hexdigest() == "1543b261fb3a3f4da401a1b0bfb9e7f7b3d1e52ef2e74187535edc3bc696632f"
    current = tool.load_payload_inventory()
    assert current == expected
    current_rows = {row["path"]: row for row in current["additions"]}
    assert current_rows.keys() - old_rows.keys() == {row["path"] for row in AUDIENCE_SETTING_ROWS}
    assert all(current_rows[path] == row for path, row in old_rows.items() if path not in AUDIENCE_METADATA)
    assert len(current["additions"]) == 262
    assert current["ios_public_files"] == old["ios_public_files"] and len(current["ios_public_files"]) == 2
    assert len(current["component_sources"]) == 8
    assert current["server_json_additions"] == [HOME_TALK]
    assert "HomeTalk" in tool.EXTRA_TABLES
    assert tool.ADDED_JSON_SHA256["HomeTalk"] == HOME_TALK["sha256"]


@pytest.mark.parametrize("change", ("absent", "extra", "rows", "bytes", "sha", "path",
                                    "float-rows", "float-bytes"))
def test_home_talk_inventory_rejects_a_missing_or_changed_original_projection(tmp_path, change):
    value = tool.load_payload_inventory()
    if change == "absent":
        value.pop("server_json_additions")
    elif change == "extra":
        value["server_json_additions"].append(dict(HOME_TALK))
    elif change == "rows":
        value["server_json_additions"][0]["rows"] = 558
    elif change == "bytes":
        value["server_json_additions"][0]["bytes"] += 1
    elif change == "sha":
        value["server_json_additions"][0]["sha256"] = "0" * 64
    elif change == "path":
        value["server_json_additions"][0]["path"] = "data/master-json/FakeTalk.json"
    elif change == "float-rows":
        value["server_json_additions"][0]["rows"] = 559.0
    elif change == "float-bytes":
        value["server_json_additions"][0]["bytes"] = 1068215.0
    source = tmp_path / "inventory.json"
    source.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        tool.load_payload_inventory(source)
