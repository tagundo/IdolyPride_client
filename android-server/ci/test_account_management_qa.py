"""Host checks for the native account QA observation and preservation helpers."""
import importlib.util
from pathlib import Path
import sqlite3
import xml.etree.ElementTree as ET

import pytest

PATH = Path(__file__).with_name("qa_account_management.py")
SPEC = importlib.util.spec_from_file_location("native_account_qa", PATH)
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


class Guest:
    def __init__(self, trees):
        self.trees, self.actions, self.captures = iter(trees), [], []
    def capture(self, name):
        self.captures.append(name)
        return ET.fromstring(next(self.trees))
    def adb(self, *args):
        self.actions.append(args)
        return ""


def test_native_locator_uses_fresh_enabled_node_and_exact_observed_bounds():
    guest = Guest(['<hierarchy><node content-desc="target" enabled="true" bounds="[12,34][112,94]"/></hierarchy>'])
    node = qa.find(guest, lambda value: value.get("content-desc") == "target", "native")
    assert guest.actions == []
    qa.tap_node(guest, node)
    assert guest.actions == [("shell", "input", "tap", "62", "64")]
    assert guest.captures == ["native-0"]


def test_native_locator_scrolls_only_observed_settings_scrollview(monkeypatch):
    monkeypatch.setattr(qa.time, "sleep", lambda _: None)
    guest = Guest([
        '<hierarchy><node class="android.widget.ScrollView" scrollable="true" bounds="[20,100][620,900]"/></hierarchy>',
        '<hierarchy><node content-desc="target" enabled="true" bounds="[30,200][300,250]"/></hierarchy>',
    ])
    node = qa.find(guest, lambda value: value.get("content-desc") == "target", "scroll", "down")
    assert node.get("content-desc") == "target"
    assert len(guest.actions) == 1
    action = guest.actions[0]
    assert action[:3] == ("shell", "input", "swipe")
    x1, y1, x2, y2, duration = map(int, action[3:])
    assert x1 == x2 == 320 and 100 < y2 < y1 < 900
    assert y1-y2 <= (900-100)//2 and duration >= 600


def test_missing_control_without_scrollview_cannot_send_a_blind_input():
    guest = Guest(['<hierarchy><node bounds="[0,0][0,0]"/></hierarchy>'])
    with pytest.raises(RuntimeError, match="visible settings scroll view"):
        qa.find(guest, lambda _: False, "missing", "up")
    assert guest.actions == []


def test_disabled_control_is_reobserved_without_tapping_or_scrolling(monkeypatch):
    monkeypatch.setattr(qa.time, "sleep", lambda _: None)
    guest = Guest([
        '<hierarchy><node content-desc="target" enabled="false" bounds="[10,20][90,70]"/></hierarchy>',
        '<hierarchy><node content-desc="target" enabled="true" bounds="[15,25][95,75]"/></hierarchy>',
    ])
    found = qa.find(guest, lambda value: value.get("content-desc") == "target", "busy", "down")
    assert found.get("bounds") == "[15,25][95,75]" and guest.actions == []


def test_profile_projection_preserves_all_owned_bytes_and_excludes_sessions_by_default(tmp_path):
    def copy_database(guest, directory):
        path = Path(directory)/"state.db"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE profiles(name TEXT,server_id TEXT,public_id TEXT)")
            db.execute("CREATE TABLE sessions(token_hash TEXT,profile TEXT,expires_at INTEGER)")
            for table in qa.TABLES[1:]:
                db.execute("CREATE TABLE "+table+"(profile TEXT,value BLOB)")
            for slot in ("source", "copy"):
                db.execute("INSERT INTO profiles VALUES(?,?,?)", (slot, "server-fixed", "public-fixed"))
                for table in qa.TABLES[1:]:
                    db.execute("INSERT INTO "+table+" VALUES(?,?)", (slot, b"unknown\x80\x4b\x7b"+table.encode()))
                db.execute("INSERT INTO sessions VALUES(?,?,?)", ("token-hash-"+slot, slot, 1000))
        return path
    source = qa.projection(None, copy_database, "source")
    cloned = qa.projection(None, copy_database, "copy")
    assert source == cloned and set(source) == set(qa.TABLES) and "sessions" not in source
    explicit = qa.projection(None, copy_database, "source", sessions=True)
    assert explicit["sessions"] == (("token-hash-source", "source", 1000),)
    assert source["snapshots"][0][1] == b"unknown\x80\x4b\x7bsnapshots"


def test_account_probe_runs_after_existing_engine_and_preservation_checks():
    source = PATH.with_name("qa_emulator.py").read_text()
    main = source[source.index("def main():"):]
    assert main.index("result.update(exercise_main_live_checks") < main.index("from qa_account_management import")
    assert main.index("result.update(exercise_account_management") < main.index("result.update(ok=True, final_stop=True)")


def test_document_target_is_enabled_named_item_not_inert_grid_caption():
    tree = ET.fromstring('<hierarchy><node package="com.google.android.documentsui" resource-id="com.google.android.documentsui:id/item_root" enabled="true" focusable="true" bounds="[60,600][540,1300]"><node package="com.google.android.documentsui" text="account.zip" clickable="false" enabled="true" bounds="[200,1180][490,1240]"/></node></hierarchy>')
    item = qa.document_item(tree, "account.zip")
    assert item.get("resource-id").endswith("/item_root")
    assert qa.bounds(item) == (60, 600, 540, 1300)
    guest = Guest(['<hierarchy/>'])
    qa.activate_document(guest, "account.zip", item)
    assert guest.actions == [("shell", "input", "tap", "300", "950")]


def test_document_keyboard_activation_requires_fresh_focus_on_same_named_item():
    def hierarchy(name, focused):
        return '<hierarchy><node package="com.google.android.documentsui" resource-id="com.google.android.documentsui:id/item_root" enabled="true" focused="'+focused+'" bounds="[60,600][540,1300]"><node package="com.google.android.documentsui" text="'+name+'" enabled="true" bounds="[200,1180][490,1240]"/></node></hierarchy>'
    item = qa.document_item(ET.fromstring(hierarchy("account.zip", "false")), "account.zip")
    guest = Guest([hierarchy("account.zip", "true")])
    qa.activate_document(guest, "account.zip", item)
    assert guest.actions[-1] == ("shell", "input", "keyevent", "66")
    other = Guest([hierarchy("different.zip", "true")])
    qa.activate_document(other, "account.zip", item)
    assert len(other.actions) == 1


def test_disabled_provider_document_cannot_be_activated():
    tree = ET.fromstring('<hierarchy><node package="com.android.documentsui" resource-id="com.android.documentsui:id/item_root" enabled="false" bounds="[1,2][100,200]"><node package="com.android.documentsui" text="account.zip" enabled="true" bounds="[2,3][99,190]"/></node></hierarchy>')
    assert qa.document_item(tree, "account.zip") is None


def test_named_item_in_another_package_is_not_a_documentsui_target():
    tree = ET.fromstring('<hierarchy><node package="unrelated.app" resource-id="com.google.android.documentsui:id/item_root" enabled="true" focused="true" bounds="[1,2][100,200]"><node package="unrelated.app" text="account.zip" enabled="true" bounds="[2,3][99,190]"/></node></hierarchy>')
    assert qa.document_item(tree, "account.zip") is None
