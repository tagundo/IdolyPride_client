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


def test_document_tab_reobserves_focus_and_enters_only_exact_root():
    def tree(focused):
        return '<hierarchy><node package="com.google.android.documentsui" enabled="true" focusable="true" focused="'+str(focused == "toolbar").lower()+'" bounds="[0,0][100,50]" resource-id="provider:id/toolbar"/><node package="com.google.android.documentsui" resource-id="provider:id/item_root" enabled="true" focusable="true" focused="'+str(focused == "document").lower()+'" bounds="[60,600][540,1300]"><node package="com.google.android.documentsui" text="account.zip" enabled="true" bounds="[200,1180][490,1240]"/></node></hierarchy>'
    guest = Guest([tree("toolbar"), tree("document")])
    strategy = qa.keyboard_document(guest, "account.zip", ET.fromstring(tree("none")))
    assert strategy == "verified_document_keyboard_focus"
    assert guest.actions == [("shell", "input", "keyevent", "61"),
                             ("shell", "input", "keyevent", "61"),
                             ("shell", "input", "keyevent", "66")]
    assert guest.captures == ["75-account-provider-tab-0", "75-account-provider-tab-1"]


def test_document_tab_rejects_preview_child_focus_and_cycles():
    tree = '<hierarchy><node package="com.google.android.documentsui" resource-id="provider:id/item_root" enabled="true" focusable="true" focused="false" bounds="[60,600][540,1300]"><node package="com.google.android.documentsui" text="account.zip" enabled="true" bounds="[200,1180][490,1240]"/><node package="com.google.android.documentsui" resource-id="provider:id/preview_icon" enabled="true" focusable="true" focused="true" bounds="[400,700][530,830]"/></node></hierarchy>'
    guest = Guest([tree, tree])
    with pytest.raises(RuntimeError, match="focus cycled"):
        qa.keyboard_document(guest, "account.zip", ET.fromstring(tree))
    assert all(action[-1] == "61" for action in guest.actions)


def test_document_tab_never_activates_another_package():
    tree = '<hierarchy><node package="com.google.android.documentsui" resource-id="provider:id/item_root" enabled="true" focusable="true" bounds="[60,600][540,1300]"><node package="com.google.android.documentsui" text="account.zip" enabled="true" bounds="[200,1180][490,1240]"/></node><node package="unrelated.app" focused="true" bounds="[1,2][20,30]"/></hierarchy>'
    guest = Guest([tree])
    with pytest.raises(RuntimeError, match="focus left"):
        qa.keyboard_document(guest, "account.zip", ET.fromstring(tree))
    assert guest.actions == [("shell", "input", "keyevent", "61")]


def test_provider_evidence_refuses_non_synthetic_queries(tmp_path):
    guest = Guest([])
    with pytest.raises(RuntimeError, match="non-synthetic"):
        qa.provider_evidence(guest, "private-document.zip", "probe")
    assert guest.actions == []


def test_provider_evidence_queries_only_observed_synthetic_export(tmp_path):
    filename = "IdolyPride-Account-" + "a"*32 + ".zip"
    class MetadataGuest:
        artifacts = tmp_path
        actions = []
        def adb(self, *args, **kwargs):
            self.actions.append((args, kwargs))
            if "query" in args:
                return "Row: 0 _display_name="+filename+", mime_type=application/zip, _size=23900"
            return "  mCurrentFocus=Window{synthetic com.google.android.documentsui/.picker.PickActivity}"
    guest = MetadataGuest()
    qa.provider_evidence(guest, filename, "observed")
    import json
    saved = json.loads((tmp_path/"observed.json").read_text())
    assert saved["filename"] == filename and "mime_type=application/zip" in saved["media_query"]
    query, options = guest.actions[0]
    assert query[query.index("--uri")+1] == "content://media/external/file"
    assert filename in query[query.index("--where")+1] and "_display_name=" in query[-1]
    assert options == {"check": False}
    assert len(saved["window_focus"]) == 1


def test_raw_love_json_canary_preserves_whitespace_and_all_other_tables(tmp_path):
    from types import SimpleNamespace
    with sqlite3.connect(tmp_path / "state.db") as db:
        db.execute("CREATE TABLE profiles(name TEXT,server_id TEXT)")
        db.execute("INSERT INTO profiles VALUES('sandbox','synthetic-server')")
        db.execute("CREATE TABLE snapshots(profile TEXT,response BLOB,schema_sha256 TEXT)")
        db.execute("INSERT INTO snapshots VALUES(?,?,?)", ("sandbox", b"unchanged unknown protobuf", "b" * 64))
        for table in (*qa.TABLES[2:-1], "sessions"):
            db.execute("CREATE TABLE " + table + "(profile TEXT,value BLOB)")
            db.execute("INSERT INTO " + table + " VALUES(?,?)", ("sandbox", b"raw canary " + table.encode()))
        db.execute("CREATE TABLE profile_love_progress(profile TEXT,love_id TEXT,response BLOB,schema_sha256 TEXT,ruleset_sha256 TEXT)")
        before = {table: db.execute("SELECT * FROM " + table).fetchall() for table in (*qa.TABLES[:-1], "sessions")}
        raw = qa.seed_love_canary(db, SimpleNamespace(fingerprint="b" * 64))
        assert raw.startswith(b" \n{") and raw.endswith(b"\n ")
        row = db.execute("SELECT * FROM profile_love_progress").fetchone()
        assert row == ("sandbox", "love-23-0514", raw, "b" * 64, "a" * 64)
        assert b'"player_name": "QA raw JSON canary"' in raw
        assert {table: db.execute("SELECT * FROM " + table).fetchall() for table in before} == before
        with pytest.raises(RuntimeError, match="fresh stopped synthetic sandbox"):
            qa.seed_love_canary(db, SimpleNamespace(fingerprint="b" * 64))


def category_frame(selected, panel=None, target=False):
    body = '<node content-desc="idoly.nav.users" selected="' + str(selected).lower() + '" enabled="true" bounds="[10,10][110,60]"/>'
    if panel is not None:
        body += '<node content-desc="idoly.panel.accounts" selected="' + str(panel).lower() + '" enabled="true" bounds="[20,100][500,160]"/>'
    if target:
        body += '<node content-desc="idoly.accounts.create" enabled="true" bounds="[30,200][300,250]"/>'
    return '<hierarchy>' + body + '</hierarchy>'


def test_category_and_collapsed_panel_are_opened_through_fresh_observed_taps(monkeypatch):
    monkeypatch.setattr(qa.time, "sleep", lambda _: None)
    guest = Guest([category_frame(False), category_frame(True, False), category_frame(True, True, True)])
    found = qa.find(guest, lambda n: n.get("content-desc") == "idoly.accounts.create", "route", "down",
                    attempts=3, destination=("users", "accounts"))
    assert found.get("content-desc") == "idoly.accounts.create"
    assert guest.actions == [("shell", "input", "tap", "60", "35"),
                             ("shell", "input", "tap", "260", "130")]
    assert len(guest.captures) == 3


def test_navigation_uses_existing_observation_budget_and_never_taps_missing_target(monkeypatch):
    monkeypatch.setattr(qa.time, "sleep", lambda _: None)
    guest = Guest([category_frame(False), category_frame(True, False)])
    with pytest.raises(RuntimeError, match="native control was not observed"):
        qa.find(guest, lambda n: n.get("content-desc") == "idoly.accounts.create", "route", "down",
                attempts=2, destination=("users", "accounts"))
    assert len(guest.captures) == len(guest.actions) == 2


def test_hidden_control_and_clipped_scroll_child_are_not_tap_targets():
    tree = ET.fromstring('<hierarchy><node class="android.widget.ScrollView" bounds="[0,100][500,400]">'
        '<node content-desc="offscreen" bounds="[10,450][100,500]"/>'
        '<node content-desc="hidden" visible-to-user="false" bounds="[10,200][100,250]"/>'
        '<node content-desc="visible" bounds="[10,220][100,270]"/></node></hierarchy>')
    nodes = {n.get("content-desc"): n for n in tree.iter("node") if n.get("content-desc")}
    assert not qa.visible_node(nodes["offscreen"], tree)
    assert not qa.visible_node(nodes["hidden"], tree)
    assert qa.visible_node(nodes["visible"], tree)


def test_current_category_repositions_once_before_existing_scroll_logic(monkeypatch):
    monkeypatch.setattr(qa.time, "sleep", lambda _: None)
    state = {}; guest = Guest([]); tree = ET.fromstring(category_frame(True))
    assert qa.navigation_step(guest, tree, ("users", "accounts"), state)
    assert not qa.navigation_step(guest, tree, ("users", "accounts"), state)
    assert guest.actions == [("shell", "input", "tap", "60", "35")]


def test_actual_restart_console_routes_to_users_before_observing_queued_selection(monkeypatch):
    monkeypatch.setattr(qa.time, "sleep", lambda _: None)
    actual = (Path(__file__).parent / "fixtures/account-restart-console-2c35.xml").read_text()
    initial = ET.fromstring(actual)
    nav = next(n for n in initial.iter("node") if n.get("content-desc") == "idoly.nav.users")
    assert any(n.get("scrollable") == "false" and "ScrollView" in n.get("class", "") for n in initial.iter("node"))
    final = category_frame(True, True).replace('</hierarchy>', '<node text="다음 시작 · 일반 sandbox" enabled="false" bounds="[30,260][500,320]"/></hierarchy>')
    guest = Guest([actual, category_frame(True, False), final])
    result = qa.find_queued_account(guest, "sandbox", "restart")
    assert "다음 시작 · 일반 sandbox" in result.get("text")
    left, top, right, bottom = qa.bounds(nav)
    assert guest.actions == [("shell", "input", "tap", str((left+right)//2), str((top+bottom)//2)),
                             ("shell", "input", "tap", "260", "130")]
    assert guest.captures == ["restart-0", "restart-1", "restart-2"]
