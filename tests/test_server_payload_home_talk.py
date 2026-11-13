"""The first HomeTalk addition preserves the already audited public catalogs.

The expected bytes and row count come from the original 6.1.1 SQLCipher /
Protobuf projection, independently of the package builder's constants.
These tests inspect only small versioned inventories, never a game payload.
"""
import hashlib
import json
from pathlib import Path

import pytest

from tools import build_android_server_manual as tool


ROOT = Path(__file__).resolve().parents[1]
HOME_TALK = {"path": "data/master-json/HomeTalk.json", "bytes": 1068215,
             "sha256": "63f332a9cf291f32ff4d6b4f65dd0f2a72784f779fd94d250932597ef32dda38",
             "rows": 559}


def test_home_talk_inventory_preserves_the_audited_260_catalogs_and_two_ios_files():
    old_raw = (ROOT / "tools/server_payload_v0323.json").read_bytes()
    assert hashlib.sha256(old_raw).hexdigest() == "e775e49cfae0fe285d773145f7a5f871134ca3c28fd9a104811e76fa48170449"
    old = json.loads(old_raw)
    current = tool.load_payload_inventory()
    # This also covers every original component hash, coverage/sort proof,
    # catalog filename and content digest; adding HomeTalk cannot rewrite them.
    assert {key: value for key, value in current.items() if key != "server_json_additions"} == old
    assert len(current["additions"]) == 260
    assert len(current["ios_public_files"]) == 2
    assert len(current["component_sources"]) == 7
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
