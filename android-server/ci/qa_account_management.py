"""Native account-management round trip on the already verified disposable guest.

No command runs on import. The caller owns emulator verification and all ports.
Raw synthetic account rows stay in memory/private temporary files, never reports.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import sqlite3
import tempfile
import time
from urllib.request import urlopen

PACKAGE = "game.qualiarts.idolypride.localserver"
ACTIVITY = PACKAGE + "/.MainActivity"
CREATE, CLONE, IMPORTED = "zz-qa-created", "zz-qa-clone", "zz-qa-imported"
DOCUMENT_UI_PACKAGES = frozenset(("com.android.documentsui", "com.google.android.documentsui"))
TABLES = ("profiles", "snapshots", "profile_settings", "starter_profiles",
          "profile_lesson_progress", "preference_receipts", "main_live_attempts")


def bounds(node):
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
    if match:
        left, top, right, bottom = map(int, match.groups())
        if right > left and bottom > top:
            return left, top, right, bottom
    return None


def find(qa, predicate, stage, direction=None, *, enabled=True, attempts=16):
    for attempt in range(attempts):
        tree = qa.capture(stage + "-" + str(attempt))
        matching = [node for node in tree.iter("node") if predicate(node) and bounds(node)]
        usable = [node for node in matching if not enabled or node.get("enabled") == "true"]
        if usable:
            return usable[0]
        if matching or direction is None:
            time.sleep(.5)
            continue
        scrolling = [node for node in tree.iter("node")
                     if node.get("scrollable") == "true" and "ScrollView" in node.get("class", "") and bounds(node)]
        if not scrolling:
            raise RuntimeError("Account QA expected a visible settings scroll view: " + stage)
        area = max(scrolling, key=lambda node: (bounds(node)[2]-bounds(node)[0])*(bounds(node)[3]-bounds(node)[1]))
        left, top, right, bottom = bounds(area)
        # A fast full-height swipe flings past entire button groups on API 30.
        # Move through the central third slowly so successive observations overlap.
        travel = max(24, (bottom-top)//3)
        x = (left+right)//2
        y1 = (top+bottom)//2 - travel//2
        y2 = y1 + travel
        if direction == "up":
            qa.adb("shell", "input", "swipe", str(x), str(y1), str(x), str(y2), "650")
        else:
            qa.adb("shell", "input", "swipe", str(x), str(y2), str(x), str(y1), "650")
        time.sleep(.25)
    raise RuntimeError("Account QA native control was not observed enabled: " + stage)


def tap_node(qa, node):
    left, top, right, bottom = bounds(node)
    qa.adb("shell", "input", "tap", str((left+right)//2), str((top+bottom)//2))


def tap(qa, description, stage, direction=None):
    tap_node(qa, find(qa, lambda node: node.get("content-desc") == description, stage, direction))


def positive(qa, stage):
    tap_node(qa, find(qa, lambda node: node.get("resource-id") == "android:id/button1", stage))


def input_profile(qa, name, stage):
    tap(qa, "idoly.accounts.profile-input", stage)
    qa.adb("shell", "input", "text", name)
    positive(qa, stage + "-confirm")


def select_profile(qa, profile, stage, direction="up"):
    tap(qa, "idoly.accounts.list", stage + "-open", direction)
    tap_node(qa, find(qa, lambda node: node.get("text") == "일반 · " + profile, stage + "-row"))


def projection(qa, copy_database, profile, *, sessions=False):
    with tempfile.TemporaryDirectory(prefix="idoly-account-native-") as temporary:
        path = copy_database(qa, temporary)
        with sqlite3.connect(path) as db:
            result = {}
            for table in (*TABLES, "sessions") if sessions else TABLES:
                field = "name" if table == "profiles" else "profile"
                rows = db.execute("SELECT * FROM " + table + " WHERE " + field + "=? ORDER BY rowid", (profile,)).fetchall()
                if table == "sessions":
                    result[table] = tuple(sorted(rows))
                else:
                    result[table] = tuple(sorted((("@slot", *row[1:]) for row in rows), key=repr))
            if not result["profiles"] or not result["snapshots"]:
                raise RuntimeError("Account QA expected a complete stored profile")
            return result


def document_name(qa):
    for attempt in range(15):
        tree = qa.capture("72-account-export-picker-" + str(attempt))
        for node in tree.iter("node"):
            value = node.get("text", "")
            if re.fullmatch(r"IdolyPride-Account-[0-9a-f]{32}\.zip", value):
                return value
        time.sleep(.5)
    raise RuntimeError("Account QA document picker did not show the native export filename")


def save_document(qa):
    node = find(qa, lambda item: item.get("resource-id", "").endswith("/action_menu_select")
                or item.get("text") in ("SAVE", "Save", "저장"), "73-account-document-save")
    tap_node(qa, node)



def document_item(tree, filename):
    """Resolve the actual provider row/tile containing this exact filename."""
    parents = {child: parent for parent in tree.iter() for child in parent}
    for title in tree.iter("node"):
        if title.get("text") != filename or title.get("package") not in DOCUMENT_UI_PACKAGES:
            continue
        current = title
        while current is not None:
            if (current.get("resource-id", "").endswith("/item_root")
                    and current.get("package") == title.get("package")
                    and current.get("enabled") == "true" and bounds(current)):
                return current
            current = parents.get(current)
    return None


def find_document(qa, filename, stage, *, attempts=8):
    for attempt in range(attempts):
        tree = qa.capture(stage + "-" + str(attempt))
        item = document_item(tree, filename)
        if item is not None:
            return item
        time.sleep(.5)
    raise RuntimeError("Account QA enabled document item was not observed: " + stage)


def keyboard_document(qa, filename, tree):
    """Tab only within the observed provider; Enter requires this exact row's focus."""
    current = document_item(tree, filename)
    if current is None or current.get("focusable") != "true":
        raise RuntimeError("Account QA document is not an observed keyboard focus target")
    provider = current.get("package")
    focusable = [node for node in tree.iter("node")
                 if node.get("package") == provider and node.get("enabled") == "true"
                 and node.get("focusable") == "true" and bounds(node)]
    # API 30 shell input tap creates TOOL_TYPE_UNKNOWN. DocumentsUI's
    # SelectionTracker handles finger/stylus, so the tile can ignore that tap.
    # Its normal keyboard path remains available; never activate a preview child.
    seen = set()
    for attempt in range(min(20, len(focusable) + 1)):
        qa.adb("shell", "input", "keyevent", "61")
        tree = qa.capture("75-account-provider-tab-" + str(attempt))
        current = document_item(tree, filename)
        if current is None:
            raise RuntimeError("Account QA document changed during provider keyboard navigation")
        if current.get("focused") == "true":
            qa.adb("shell", "input", "keyevent", "66")
            return "verified_document_keyboard_focus"
        focused = [node for node in tree.iter("node") if node.get("focused") == "true"]
        if any(node.get("package") != provider for node in focused):
            raise RuntimeError("Account QA keyboard focus left the observed document provider")
        signature = tuple((node.get("resource-id"), node.get("bounds")) for node in focused)
        if signature and signature in seen:
            raise RuntimeError("Account QA document provider focus cycled before the named row")
        if signature:
            seen.add(signature)
    raise RuntimeError("Account QA named document did not receive keyboard focus")


def provider_evidence(qa, filename, stage):
    """Retain only this synthetic export's MIME/size and bounded focus metadata."""
    if not re.fullmatch(r"IdolyPride-Account-[0-9a-f]{32}\.zip", filename):
        raise RuntimeError("Account QA refuses to query a non-synthetic document")
    report = {"schema": 1, "filename": filename, "stage": stage}
    raw = qa.adb("shell", "content", "query", "--uri", "content://media/external/file",
                 "--projection", "_display_name:mime_type:_size", "--where",
                 shlex.quote("_display_name='" + filename + "'"), check=False)
    rows = [line for line in raw.splitlines() if line.startswith("Row:") and filename in line]
    report["media_query"] = rows[0][:512] if len(rows) == 1 else "metadata_unavailable"
    raw = qa.adb("shell", "dumpsys", "window", "windows", check=False)
    report["window_focus"] = [line.strip()[:384] for line in raw.splitlines()
                              if "mCurrentFocus=" in line or "mFocusedApp=" in line][:4]
    (qa.artifacts / (stage + ".json")).write_text(json.dumps(report), encoding="utf-8")


def activate_document(qa, filename, item):
    # A grid caption is not an actionable node in DocumentsUI. Its observed
    # item_root owns the tile; keyboard activation is allowed only if the next
    # fresh hierarchy confirms that this exact named item received focus.
    tap_node(qa, item)
    tree = qa.capture("75-account-document-activated")
    current = document_item(tree, filename)
    if current is None:
        return "provider_result_pending"
    opening = [node for node in tree.iter("node")
               if node.get("enabled") == "true" and bounds(node)
               and node.get("package") == current.get("package")
               and (node.get("resource-id", "").endswith("/action_menu_select")
                    or node.get("text") in ("OPEN", "Open", "열기"))]
    if opening:
        tap_node(qa, opening[0])
        return "observed_provider_open_action"
    if current.get("focused") == "true":
        qa.adb("shell", "input", "keyevent", "66")
        return "verified_document_keyboard_focus"
    return keyboard_document(qa, filename, tree)


def open_document(qa, filename):
    try:
        node = find_document(qa, filename, "75-account-recent-file", attempts=8)
    except RuntimeError:
        node = find(qa, lambda item: item.get("content-desc") in ("Show roots", "루트 표시", "탐색 창 열기"),
                    "75-account-document-roots", attempts=4)
        tap_node(qa, node)
        tap_node(qa, find(qa, lambda item: item.get("text") in ("Downloads", "다운로드"),
                          "75-account-downloads", attempts=5))
        node = find_document(qa, filename, "75-account-download-file", attempts=10)
    tree = qa.capture("75-account-provider-before")
    node = document_item(tree, filename)
    if node is None:
        raise RuntimeError("Account QA named document disappeared before activation")
    provider_evidence(qa, filename, "75-account-provider-metadata-before")
    try:
        strategy = activate_document(qa, filename, node)
        (qa.artifacts / "75-account-provider-activation.json").write_text(
            json.dumps({"schema": 1, "filename": filename, "strategy": strategy}), encoding="utf-8")
        return strategy
    finally:
        qa.capture("75-account-provider-after")
        provider_evidence(qa, filename, "75-account-provider-metadata-after")


def exercise_account_management(qa, schema, grpc_port, asset_port, startup_timeout, *,
                                wait_server, bootstrap, rpc, copy_database):
    original = projection(qa, copy_database, "sandbox", sessions=True)
    qa.adb("shell", "am", "start", "-n", ACTIVITY)
    tap(qa, "idoly.accounts.create", "60-account-create", "down")
    input_profile(qa, CREATE, "61-account-create-name")
    find(qa, lambda node: node.get("content-desc") == "idoly.accounts.create", "62-account-created", "up")
    # The active/default sandbox selection is retained after creating a different slot.
    tap(qa, "idoly.accounts.clone", "63-account-clone", "down")
    input_profile(qa, CLONE, "64-account-clone-name")
    find(qa, lambda node: node.get("content-desc") == "idoly.accounts.clone", "65-account-cloned", "up")
    select_profile(qa, CLONE, "66-account-select-clone")
    tap(qa, "idoly.accounts.select", "66-account-queue-clone", "down")
    find(qa, lambda node: node.get("content-desc") == "idoly.accounts.select", "66-account-queued")
    qa.adb("shell", "am", "force-stop", PACKAGE)
    if projection(qa, copy_database, "sandbox", sessions=True) != original:
        raise RuntimeError("Native create/clone/select changed the original whole account or sessions")
    cloned = projection(qa, copy_database, CLONE)
    if cloned != {key: value for key, value in original.items() if key != "sessions"}:
        raise RuntimeError("Native clone changed account identity, clock, receipts or protobuf bytes")
    created = projection(qa, copy_database, CREATE)
    if created["profiles"][0][1:] == original["profiles"][0][1:]:
        raise RuntimeError("A new native account reused the original synthetic identity")

    qa.adb("shell", "am", "start", "-n", ACTIVITY)
    qa.tap("서버 시작", "67-account-selected-start")
    wait_server(schema, grpc_port, timeout=startup_timeout)
    with urlopen("http://127.0.0.1:" + str(asset_port) + "/diagnostics/runtime", timeout=10) as response:
        raw = response.read(2*1024*1024+1)
    if len(raw) > 2*1024*1024 or json.loads(raw)["runtime"].get("profile") != CLONE:
        raise RuntimeError("Native queued account did not become the runtime's selected profile")
    _, login = bootstrap(schema, grpc_port)
    restored = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
    expected = schema.response_type("/api.User/Get").FromString(cloned["snapshots"][0][1])
    if restored.SerializeToString(deterministic=True) != expected.SerializeToString(deterministic=True):
        raise RuntimeError("Selected-account encrypted User.Get changed the whole saved snapshot")
    qa.capture("68-account-selected-running")
    qa.tap("서버 중지", "69-account-selected-stop")
    wait_server(schema, grpc_port, expected=False, timeout=30)
    qa.adb("shell", "am", "force-stop", PACKAGE)
    if projection(qa, copy_database, "sandbox", sessions=True) != original:
        raise RuntimeError("Starting the cloned account modified the original profile or sessions")

    qa.adb("shell", "am", "start", "-n", ACTIVITY)
    tap(qa, "idoly.accounts.export", "71-account-export", "down")
    filename = document_name(qa)
    save_document(qa)
    find(qa, lambda node: node.get("content-desc") == "idoly.accounts.export", "74-account-export-saved", "up")
    tap(qa, "idoly.accounts.import", "75-account-import", "down")
    open_document(qa, filename)
    try:
        tap(qa, "idoly.accounts.import-new", "76-account-native-preview")
    except RuntimeError:
        qa.capture("76-account-preview-timeout")
        raise
    input_profile(qa, IMPORTED, "77-account-import-name")
    find(qa, lambda node: node.get("content-desc") == "idoly.accounts.import", "78-account-import-complete", "up")
    select_profile(qa, "sandbox", "79-account-select-original")
    tap(qa, "idoly.accounts.select", "79-account-queue-original", "down")
    find(qa, lambda node: node.get("content-desc") == "idoly.accounts.select", "79-account-original-queued")
    qa.adb("shell", "am", "force-stop", PACKAGE)
    imported = projection(qa, copy_database, IMPORTED, sessions=True)
    current_clone = projection(qa, copy_database, CLONE)
    if {key: value for key, value in imported.items() if key != "sessions"} != current_clone or imported["sessions"]:
        raise RuntimeError("Native account ZIP round trip changed owned bytes or imported an authentication session")
    if projection(qa, copy_database, "sandbox", sessions=True) != original:
        raise RuntimeError("Native account ZIP round trip changed unrelated original state")
    qa.adb("shell", "am", "start", "-n", ACTIVITY)
    selected = find(qa, lambda node: "다음 시작 · 일반 sandbox" in node.get("text", ""),
                    "80-account-original-selection", "down", enabled=False)
    qa.capture("80-account-management-complete")
    return {"account_native_create": True, "account_native_clone": True,
            "account_queued_selection_persisted": True, "account_selected_encrypted_rpc": True,
            "account_document_export_import": True, "account_zip_whole_state_preserved": True,
            "account_original_whole_state_preserved": True, "account_import_sessions_excluded": True,
            "account_selection_restored": True,
            "account_management": {"scope": "Android emulator native UI and real document provider",
                "archive_filename_observed": filename, "owned_tables": list(TABLES),
                "imported_sessions": 0, "physical_device_tested": False}}
