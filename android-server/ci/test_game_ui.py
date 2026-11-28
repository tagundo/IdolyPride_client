"""UI inputs use observed hierarchy identities and geometry, never OCR points."""
from copy import deepcopy
import struct
from types import SimpleNamespace
import pytest

import qa_game_ui as ui
from qa_game_ui import choose_button, download_confirmation, mapped_point, title_block_reason


PACKAGE = "game.qualiarts.idolypride.local.diagnostics"
NORMAL_PACKAGE = "game.qualiarts.idolypride.local"
XML = ('<hierarchy><node package="' + PACKAGE + '" resource-id="' + PACKAGE
       + ':id/unitySurfaceView" bounds="[0,48][1080,2208]"/></hierarchy>')


@pytest.fixture
def snapshot():
    return {"ok": True, "generation": 2,
            "screen": {"width": 540, "height": 1080, "origin": "top-left", "units": "unity-screen-pixels"},
            "nodes": [
                {"kind": "button", "active": True, "interactable": True, "instance_id": -50,
                 "path": "Root/Home/LiveButton", "name": "LiveButton", "text": "", "bounds": [10, 900, 100, 980]},
                {"kind": "tmp_text", "active": True, "instance_id": 77,
                 "path": "Root/Home/LiveButton/Label", "text": "<color=#fff>ライブ</color>"}]}


def test_selects_actual_custom_button_from_its_descendant_label(snapshot):
    node = choose_button(snapshot, "ライブ")
    assert node["instance_id"] == -50 and node["label"] == "ライブ"
    assert mapped_point(snapshot, node, XML, PACKAGE, [1080, 2280]) == [110, 1928]


@pytest.mark.parametrize("package", (PACKAGE, NORMAL_PACKAGE))
def test_fixed_qa_packages_map_only_their_current_android_surface(snapshot, package):
    xml = XML.replace(PACKAGE, package)
    assert mapped_point(snapshot, snapshot["nodes"][0], xml, package, [1080, 2280]) == [110, 1928]
    for other in (PACKAGE, NORMAL_PACKAGE, "game.qualiarts.idolypride", "unknown.game"):
        if other != package:
            with pytest.raises(ValueError, match="unique current Unity"):
                mapped_point(snapshot, snapshot["nodes"][0], xml.replace(package, other), package, [1080, 2280])
    foreign = XML.replace(PACKAGE, "game.qualiarts.idolypride").replace("<hierarchy>", "").replace("</hierarchy>", "")
    with pytest.raises(ValueError, match="unique current Unity"):
        mapped_point(snapshot, snapshot["nodes"][0], xml.replace("</hierarchy>", foreign + "</hierarchy>"), package, [1080, 2280])


@pytest.mark.parametrize("package", ("game.qualiarts.idolypride", "unknown.game", NORMAL_PACKAGE + ".other", None, []))
def test_original_and_unknown_packages_are_rejected_before_forward_token_or_mapping(snapshot, package):
    qa = SimpleNamespace(game_package=package, forward=lambda port: pytest.fail("Rejected package must not forward"))
    with pytest.raises(ValueError, match="fixed emulator QA packages"):
        ui.UiExplorer(qa)
    with pytest.raises(ValueError, match="fixed emulator QA packages"):
        mapped_point(snapshot, snapshot["nodes"][0], XML, package, [1080, 2280])


@pytest.mark.parametrize("package", (PACKAGE, NORMAL_PACKAGE))
def test_snapshot_token_is_read_only_from_selected_private_qa_package(monkeypatch, package):
    commands, requests = [], []
    token = "a" * 64

    class Connection:
        def __init__(self, host, port, timeout):
            assert host == "127.0.0.1" and port == 12345

        def request(self, method, path, headers):
            requests.append((method, path))
            assert headers == {"Authorization": "Bearer " + token}

        def getresponse(self):
            return SimpleNamespace(status=200, read=lambda maximum: b'{"ok":true,"nodes":[]}')

        def close(self):
            pass

    def adb(*args, **kwargs):
        commands.append(args)
        assert kwargs == {"check": False}
        return token + "\n"

    monkeypatch.setattr(ui, "HTTPConnection", Connection)
    qa = SimpleNamespace(game_package=package, forward=lambda port: 12345, adb=adb)
    explorer = ui.UiExplorer(qa)
    assert explorer._snapshot()["ok"] is True
    assert commands == [("exec-out", "run-as", package, "cat", "files/idoly-qa-ui-token")]
    assert requests == [("GET", "/snapshot")]
    assert explorer.report()["game_package"] == package
    assert token not in str(explorer.report())


@pytest.mark.parametrize("package", (PACKAGE, NORMAL_PACKAGE))
@pytest.mark.parametrize("surface", ("matching", "other-qa", "original", "unknown"))
def test_normal_input_rechecks_selected_package_in_fresh_android_tree(snapshot, tmp_path, monkeypatch, package, surface):
    snapshot["startup_observation"] = {"content_blocking": False, "input_releasing": False}
    observed_package = {"matching": package, "other-qa": NORMAL_PACKAGE if package == PACKAGE else PACKAGE,
                        "original": "game.qualiarts.idolypride", "unknown": "unknown.game"}[surface]
    commands = []

    def adb(*args, **kwargs):
        if args == ("exec-out", "screencap", "-p"):
            return b"\x89PNG\r\n\x1a\n" + bytes(8) + struct.pack(">II", 1080, 2280)
        if args == ("shell", "wm", "size"):
            return "Physical size: 1080x2280\n"
        if args == ("exec-out", "uiautomator", "dump", "/dev/tty"):
            return XML.replace(PACKAGE, observed_package)
        commands.append(args)
        return ""

    qa = SimpleNamespace(game_package=package, artifacts=tmp_path, forward=lambda port: port,
                         touch_hold_ms=0, adb=adb)
    explorer = ui.UiExplorer(qa)
    monkeypatch.setattr(explorer, "_snapshot", lambda: snapshot)
    assert explorer._tap(snapshot, choose_button(snapshot, "ライブ"), "menu_live", 1) is (surface == "matching")
    assert commands == ([("shell", "input", "tap", "110", "1928")] if surface == "matching" else [])
    assert explorer.report()["native_click_used"] is False


@pytest.mark.parametrize("source,hold,expected", (
    ("mouse", 0, ("shell", "input", "mouse", "tap", "110", "1928")),
    ("mouse", 150, ("shell", "input", "mouse", "swipe", "110", "1928", "110", "1928", "150")),
    ("touchscreen", 0, ("shell", "input", "tap", "110", "1928")),
    ("touchscreen", 150, ("shell", "input", "touchscreen", "swipe", "110", "1928", "110", "1928", "150")),
))
def test_guarded_input_source_and_command_latency(snapshot, tmp_path, monkeypatch, source, hold, expected):
    snapshot["startup_observation"] = {"content_blocking": False, "input_releasing": False}
    clock, inputs = [0.0], []
    monkeypatch.setattr(ui, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    responses = {("exec-out", "screencap", "-p"): b"\x89PNG\r\n\x1a\n" + bytes(8) + struct.pack(">II", 1080, 2280),
                 ("shell", "wm", "size"): "Physical size: 1080x2280\n",
                 ("exec-out", "uiautomator", "dump", "/dev/tty"): XML}

    def adb(*args, **kwargs):
        if args[:2] == ("shell", "input"):
            inputs.append(args)
            clock[0] += .35
            return ""
        return responses[args]

    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, input_source=source,
                         touch_hold_ms=hold, forward=lambda port: port, adb=adb)
    explorer = ui.UiExplorer(qa)
    monkeypatch.setattr(explorer, "_snapshot", lambda: snapshot)
    assert explorer._tap(snapshot, choose_button(snapshot, "ライブ"), "menu_live", 1)
    assert inputs == [expected]
    assert explorer.actions[0]["input_source"] == source
    assert explorer.actions[0]["input_command_milliseconds"] == 350


@pytest.mark.parametrize("source", ("keyboard", "touchpad", "", None))
def test_unknown_input_source_fails_without_adb(snapshot, tmp_path, source):
    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, input_source=source,
                         forward=lambda port: port,
                         adb=lambda *args, **kwargs: pytest.fail("Invalid source must not access device"))
    explorer = ui.UiExplorer(qa)
    assert not explorer._tap(snapshot, choose_button(snapshot, "ライブ"), "menu_live", 1)
    assert explorer.input_errors == {"unsupported_input_source": 1}


@pytest.mark.parametrize("package", (PACKAGE, NORMAL_PACKAGE))
def test_restart_uses_same_qa_identity_and_normal_profile_has_no_graphics_override(package):
    commands = []
    qa = SimpleNamespace(game_package=package, forward=lambda port: port,
                         adb=lambda *args: commands.append(args))
    explorer = ui.UiExplorer(qa)
    explorer._restart()
    assert commands[0] == ("shell", "am", "force-stop", package)
    expected = ("shell", "am", "start", "-W", "-n", package + "/com.google.firebase.MessagingUnityPlayerActivity")
    assert commands[1] == expected + (("--es", "unity", "-force-gles30") if package == PACKAGE else ())


def test_ambiguous_button_text_causes_no_selection(snapshot):
    duplicate = deepcopy(snapshot["nodes"][0])
    duplicate["instance_id"] = 49
    snapshot["nodes"].append(duplicate)
    assert choose_button(snapshot, "ライブ") is None


def test_original_title_button_is_selected_when_tap_label_is_a_sibling(snapshot):
    snapshot["nodes"][0].update(path="Canvas/TitleButton", name="TitleButton")
    snapshot["nodes"][1].update(path="Canvas/UIContentArea/TAP TO START", text="TAP TO START")
    target = choose_button(snapshot, r"TAP\s*TO\s*START", r"tap.*start|start.*tap|^TitleButton$")
    assert target["instance_id"] == -50 and not target["label"]


@pytest.mark.parametrize("active,label,expected", ((True, "LOADING", "title_loading_visible"),
                                                  (True, "<b>loading</b>", "title_loading_visible"),
                                                  (False, "LOADING", None),
                                                  (True, "Download complete", None)))
def test_active_loading_text_blocks_title_even_after_callback_binding(snapshot, active, label, expected):
    snapshot["nodes"].append({"kind": "tmp_text", "active": active, "text": label})
    snapshot["nodes"][0]["callback_registered"] = True
    assert title_block_reason(snapshot, snapshot["nodes"][0]) == expected


@pytest.mark.parametrize("change,error", ((None, None), ("duplicate", "title_prompt_ambiguous"),
                                         ("label", "title_prompt_invalid"),
                                         ("outside", "title_prompt_outside_button")))
def test_title_prompt_anchor_is_unique_visible_and_inside_the_selected_button(snapshot, change, error):
    button = dict(snapshot["nodes"][0], path="Canvas/TitleButton", bounds=[0, 0, 540, 1080])
    prompt = {"path": "Canvas/UIContentArea/TAP TO START", "kind": "tmp_text", "active": True,
              "text": "TAP TO START", "bounds": [100, 900, 400, 940]}
    snapshot["nodes"].append(prompt)
    if change == "duplicate":
        snapshot["nodes"].append(dict(prompt))
    elif change == "label":
        prompt["text"] = "Purchase"
    elif change == "outside":
        button["bounds"] = [0, 0, 540, 800]
    if error:
        with pytest.raises(ValueError, match=error):
            ui.title_touch_anchor(snapshot, button)
    else:
        assert ui.title_touch_anchor(snapshot, button) is prompt
        prompt["active"] = False
        assert ui.title_touch_anchor(snapshot, button) is button


def test_title_tap_uses_final_tree_prompt_and_records_button_identity(snapshot, tmp_path, monkeypatch):
    selected = dict(snapshot["nodes"][0], path="Canvas/TitleButton", name="TitleButton", bounds=[0, 0, 540, 1080])
    snapshot["nodes"] = [selected, {"path": "Canvas/UIContentArea/TAP TO START", "kind": "tmp_text",
                                  "active": True, "text": "TAP TO START", "bounds": [100, 900, 400, 940]}]
    inputs = []
    responses = {("exec-out", "screencap", "-p"): b"\x89PNG\r\n\x1a\n" + bytes(8) + struct.pack(">II", 1080, 2280),
                 ("shell", "wm", "size"): "Physical size: 1080x2280\n",
                 ("exec-out", "uiautomator", "dump", "/dev/tty"): XML}

    def adb(*args, **kwargs):
        if args[:3] == ("shell", "input", "tap"):
            inputs.append(args)
            return ""
        return responses[args]

    explorer = ui.UiExplorer(SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, touch_hold_ms=0,
                                             forward=lambda port: 12345, adb=adb))
    monkeypatch.setattr(explorer, "_snapshot", lambda: snapshot)
    assert explorer._tap(snapshot, selected, "observed_title", 1)
    assert inputs == [("shell", "input", "tap", "500", "1888")]
    action = explorer.actions[0]
    assert action["path"] == "Canvas/TitleButton" and action["instance_id"] == selected["instance_id"]
    assert action["coordinate_anchor_path"] == "Canvas/UIContentArea/TAP TO START"


def test_known_startup_blocking_defers_title_input_but_success_flag_is_not_a_prerequisite(snapshot):
    node = snapshot["nodes"][0]
    snapshot["startup_observation"] = {"solis_initialization_succeeded": False,
                                      "input_releasing": None, "content_blocking": None}
    assert title_block_reason(snapshot, node) is None
    node["callback_registered"] = False
    assert title_block_reason(snapshot, node) == "title_callback_not_registered"
    node["callback_registered"] = True
    for field in ("input_releasing", "content_blocking"):
        snapshot["startup_observation"][field] = True
        assert title_block_reason(snapshot, node) == field
        snapshot["startup_observation"][field] = False


@pytest.mark.parametrize("field", ["active", "interactable"])
def test_inactive_or_disabled_button_is_not_selected(snapshot, field):
    snapshot["nodes"][0][field] = False
    assert choose_button(snapshot, "ライブ") is None


@pytest.mark.parametrize("label", ["購入", "ガチャを引く", "アカウント削除", "Purchase"])
def test_purchase_and_account_removal_controls_are_excluded(snapshot, label):
    snapshot["nodes"][1]["text"] = label
    assert choose_button(snapshot, ".*") is None


@pytest.mark.parametrize("bounds", [None, [0, 1, 0, 2], [0, 0, 900, 100], [float("nan"), 0, 100, 100], [-1, 0, 10, 20]])
def test_invalid_or_unavailable_unity_bounds_prevent_input(snapshot, bounds):
    node = snapshot["nodes"][0]
    node["bounds"] = bounds
    with pytest.raises(ValueError):
        mapped_point(snapshot, node, XML, PACKAGE, [1080, 2280])


def test_wrong_foreground_surface_and_mismatched_aspect_prevent_input(snapshot):
    node = snapshot["nodes"][0]
    with pytest.raises(ValueError, match="unique current Unity"):
        mapped_point(snapshot, node, XML.replace(PACKAGE, "other"), PACKAGE, [1080, 2280])
    snapshot["screen"]["height"] = 2000
    with pytest.raises(ValueError, match="aspect ratios"):
        mapped_point(snapshot, node, XML, PACKAGE, [1080, 2280])


def test_actual_api30_immersive_render_scale_uses_matching_display_metrics(snapshot):
    # Actual runtime42752337928: Unity renders at0.6x1080x2280, while Android
    # still reports its accessibility view with a132px navigation inset.
    snapshot["screen"].update(width=648, height=1368)
    node = snapshot["nodes"][0]
    node["bounds"] = [0, 0, 648, 1368]
    xml = XML.replace("[0,48][1080,2208]", "[0,0][1080,2148]")
    assert mapped_point(snapshot, node, xml, PACKAGE, [1080, 2280]) == [540, 1140]
    node["bounds"] = [307.8, 1287.6, 451.8, 1354.8]
    assert mapped_point(snapshot, node, xml, PACKAGE, [1080, 2280]) == [633, 2202]


@pytest.fixture
def download_sheet():
    # Public UI structure observed in run42759541286 frame26; no account data
    # or dependency on the ignored runtime capture directory is retained.
    root = "Title/SimpleActionSheet(Clone)/Canvas/Root/UIContentArea/"
    execute = root + "ActionBarContainer/AnchorAdjust/Actions/Execute/TextButtonNormal"
    cancel = root + "ActionBarContainer/AnchorAdjust/Actions/Cancel/TextButtonNormal"
    return {"ok": True, "generation": 28,
            "screen": {"width": 648, "height": 1368, "origin": "top-left", "units": "unity-screen-pixels"},
            "nodes": [
                {"kind": "button", "active": True, "interactable": True, "instance_id": -2544,
                 "name": "TextButtonNormal", "path": execute, "bounds": [325.2, 1276.8, 648.0, 1368.0]},
                {"kind": "button", "active": True, "interactable": True, "instance_id": -2504,
                 "name": "TextButtonNormal", "path": cancel, "bounds": [0.0, 1276.8, 322.8, 1368.0]},
                {"kind": "tmp_text", "active": True, "path": execute + "/Text", "text": "ダウンロード"},
                {"kind": "tmp_text", "active": True, "path": cancel + "/Text", "text": "キャンセル"},
                {"kind": "tmp_text", "active": True, "name": "Description",
                 "path": root + "SheetContainer/Header/Description", "text": "必要なデータをダウンロードします(1.07 GB)"},
                {"kind": "tmp_text", "active": True, "name": "Title",
                 "path": root + "SheetContainer/Header/Title", "text": "ダウンロード確認"}]}


def test_observed_resource_action_sheet_selects_execute_button_not_cancel_or_other_download(download_sheet):
    download_sheet["nodes"].extend([
        {"kind": "button", "active": True, "interactable": True, "instance_id": 99,
         "name": "DownloadButton", "path": "Title/OtherPanel/DownloadButton", "bounds": [0, 0, 20, 20]},
        {"kind": "tmp_text", "active": True, "path": "Title/OtherPanel/DownloadButton/Label", "text": "ダウンロード"}])
    target = download_confirmation(download_sheet)
    assert target["instance_id"] == -2544
    assert target["path"].endswith("/Actions/Execute/TextButtonNormal")
    assert target["label"] == "ダウンロード"
    assert target["bounds"] == [325.2, 1276.8, 648.0, 1368.0]


@pytest.mark.parametrize("title", ("購入確認", "確認", "ダウンロード"))
def test_unrelated_modal_title_does_not_authorize_a_download(download_sheet, title):
    download_sheet["nodes"][-1]["text"] = title
    assert download_confirmation(download_sheet) is None


@pytest.mark.parametrize("change", ("outside_sheet", "inactive", "unrelated_text"))
def test_resource_description_must_be_active_and_inside_the_same_action_sheet(download_sheet, change):
    description = download_sheet["nodes"][-2]
    if change == "outside_sheet":
        description["path"] = "Title/OtherPanel/Description"
    elif change == "inactive":
        description["active"] = False
    else:
        description["text"] = "この商品を購入します(1.07 GB)"
    assert download_confirmation(download_sheet) is None


@pytest.mark.parametrize("purchase", ("購入", "課金", "Purchase"))
def test_purchase_content_in_the_confirmation_is_never_selected(download_sheet, purchase):
    download_sheet["nodes"].append({"kind": "tmp_text", "active": True,
        "path": download_sheet["nodes"][-1]["path"] + "/PurchaseWarning", "text": purchase})
    assert download_confirmation(download_sheet) is None


def test_two_active_download_modals_are_ambiguous(download_sheet):
    second = deepcopy(download_sheet["nodes"])
    for node in second:
        node["path"] = node["path"].replace("Title/", "OtherCanvas/", 1)
    download_sheet["nodes"].extend(second)
    assert download_confirmation(download_sheet) is None


def test_another_active_action_sheet_header_also_makes_the_target_ambiguous(download_sheet):
    other = deepcopy(download_sheet["nodes"][-1])
    other.update(path=other["path"].replace("Title/", "OtherCanvas/", 1), text="確認")
    download_sheet["nodes"].append(other)
    assert download_confirmation(download_sheet) is None


def test_two_execute_targets_in_the_resource_sheet_are_ambiguous(download_sheet):
    duplicate = deepcopy(download_sheet["nodes"][0])
    duplicate.update(instance_id=101, path=duplicate["path"] + "Duplicate")
    download_sheet["nodes"].extend([duplicate, {"kind": "tmp_text", "active": True,
        "path": duplicate["path"] + "/Text", "text": "ダウンロード"}])
    assert download_confirmation(download_sheet) is None


@pytest.mark.parametrize("label", ("ダウンロードしない", "追加ダウンロード"))
def test_resource_confirmation_requires_the_exact_observed_execute_label(download_sheet, label):
    download_sheet["nodes"][2]["text"] = label
    assert download_confirmation(download_sheet) is None


def test_download_modal_context_is_rechecked_after_refresh_before_input(download_sheet, tmp_path, monkeypatch):
    selected = download_confirmation(download_sheet)
    fresh = deepcopy(download_sheet)
    fresh["generation"] += 1
    # The shared action-sheet button keeps its object identity and label while
    # another confirmation replaces the header. That must not authorize input.
    fresh["nodes"][-1]["text"] = "購入確認"
    fresh["nodes"][-2]["text"] = "この商品を購入します"
    inputs = []
    responses = {
        ("exec-out", "screencap", "-p"): b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 1080, 2280),
        ("shell", "wm", "size"): "Physical size: 1080x2280\n",
        ("exec-out", "uiautomator", "dump", "/dev/tty"): XML.replace("[0,48][1080,2208]", "[0,0][1080,2148]")}

    def adb(*args, **kwargs):
        if args[:3] == ("shell", "input", "tap"):
            inputs.append(args)
            return ""
        return responses[args]

    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, touch_hold_ms=0,
                         forward=lambda port: 12345, adb=adb)
    explorer = ui.UiExplorer(qa)
    monkeypatch.setattr(explorer, "_snapshot", lambda: fresh)
    assert explorer._tap(download_sheet, selected, "observed_resource_download_confirmation", 26) is False
    assert inputs == [] and explorer.actions == []


@pytest.mark.parametrize("collection_seconds,allowed", ((0.5, True), (10.01, False)))
def test_slow_unity_queries_cannot_refresh_an_already_stale_android_surface(
        snapshot, tmp_path, monkeypatch, collection_seconds, allowed):
    snapshot["startup_observation"] = {"content_blocking": False, "input_releasing": False}
    clock = [0.0]
    monkeypatch.setattr(ui, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    class FakeQa:
        game_package = PACKAGE
        artifacts = tmp_path
        touch_hold_ms = 0

        def __init__(self):
            self.inputs = []

        def forward(self, port):
            assert port == 50052
            return 12345

        def adb(self, *args, **kwargs):
            if args == ("exec-out", "screencap", "-p"):
                assert kwargs == {"binary": True}
                # Only the screenshot signature and IHDR dimensions are read.
                return b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 1080, 2280)
            if args == ("shell", "wm", "size"):
                return "Physical size: 1080x2280\n"
            if args == ("exec-out", "uiautomator", "dump", "/dev/tty"):
                clock[0] += collection_seconds
                return XML
            if args[:3] == ("shell", "input", "tap"):
                self.inputs.append(args)
                return ""
            raise AssertionError("Unexpected fake adb command")

    qa = FakeQa()
    explorer = ui.UiExplorer(qa)
    fresh = deepcopy(snapshot)
    fresh["generation"] = 3

    def slow_query():
        clock[0] += 20  # Waiting for Unity precedes creation of the returned tree.
        return fresh

    monkeypatch.setattr(explorer, "_snapshot", slow_query)
    selected = choose_button(snapshot, "ライブ")
    assert explorer._tap(snapshot, selected, "menu_live", 26) is allowed
    if allowed:
        assert qa.inputs == [("shell", "input", "tap", "110", "1928")]
        assert explorer.actions[0]["generation"] == 3
        assert explorer.actions[0]["ui_query_milliseconds"] == 20000
        assert explorer.actions[0]["observation_to_input_milliseconds"] == 500
        assert explorer.input_errors == {}
    else:
        assert qa.inputs == [] and explorer.actions == []
        assert explorer.input_errors == {"ui_observation_became_stale": 1}
        assert not list(tmp_path.glob("ui-action-*"))


@pytest.mark.parametrize("second_query_seconds,change,allowed,error", (
    (0.5, None, True, None),
    (10.01, None, False, "ui_observation_became_stale"),
    (0.5, "identity", False, "selected_node_no_longer_present"),
    (0.5, "blocking", False, "content_blocking"),
))
def test_slow_android_dump_is_followed_by_a_fresh_guarded_unity_query(
        snapshot, tmp_path, monkeypatch, second_query_seconds, change, allowed, error):
    snapshot["nodes"][0].update(path="Canvas/TitleButton", name="TitleButton", callback_registered=True)
    snapshot["startup_observation"] = {"content_blocking": False, "input_releasing": False}
    clock, queries, inputs = [0.0], [], []
    monkeypatch.setattr(ui, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def adb(*args, **kwargs):
        if args == ("exec-out", "screencap", "-p"):
            clock[0] += 4
            return b"\x89PNG\r\n\x1a\n" + bytes(8) + struct.pack(">II", 1080, 2280)
        if args == ("shell", "wm", "size"):
            clock[0] += 1
            return "Physical size: 1080x2280\n"
        if args == ("exec-out", "uiautomator", "dump", "/dev/tty"):
            clock[0] += 9
            return XML
        if args[:3] == ("shell", "input", "tap"):
            inputs.append(args)
            return ""
        raise AssertionError(args)

    def query():
        queries.append(clock[0])
        current = deepcopy(snapshot)
        if len(queries) == 2:
            clock[0] += second_query_seconds
            current["generation"] += 1
            current["nodes"][0]["bounds"] = [20, 900, 120, 980]
            if change == "identity":
                current["nodes"][0]["instance_id"] -= 1
            elif change == "blocking":
                current["startup_observation"]["content_blocking"] = True
        return current

    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, touch_hold_ms=0,
                         forward=lambda port: 12345, adb=adb)
    explorer = ui.UiExplorer(qa)
    monkeypatch.setattr(explorer, "_snapshot", query)
    assert explorer._tap(snapshot, ui.buttons(snapshot)[0], "observed_title", 1) is allowed
    assert queries == [0, 14]
    if allowed:
        # Bounds are from the final Unity tree, not the obsolete selection.
        assert inputs == [("shell", "input", "tap", "140", "1928")]
        action = explorer.actions[0]
        assert action["generation"] == 3
        assert action["observation_to_input_milliseconds"] == 0
        assert action["android_geometry_to_input_milliseconds"] == 500
    else:
        assert inputs == [] and explorer.actions == []
        assert explorer.input_errors == {error: 1}


HOME_ROOT = "WindowSystem/WindowRoot/HomeWindow(Clone)/HomeTopScreen(Clone)/ScreenCanvas/ScreenRoot/"
HOME_FOOTER = HOME_ROOT + "ScreenPager/HomeFooter/FooterRoot/HomeGlobalMenu/"
STORY_PATH = HOME_ROOT + "CharacterPage/SlideRoot/Character/HomeRenewalRoot/RenewalStory"


@pytest.fixture
def home_snapshot():
    # Minimal public hierarchy observed in run42764587884 frames43/53. Active
    # page objects can have null bounds while their pages are offscreen.
    nodes = []

    def add_button(identity, path, name, bounds, *labels):
        nodes.append({"kind": "button", "active": True, "interactable": True,
                      "callback_registered": True, "instance_id": identity,
                      "path": path, "name": name, "text": "", "bounds": bounds})
        for label in labels:
            nodes.append({"kind": "tmp_text", "active": True,
                          "path": path + "/Label", "text": label})

    add_button(-3146, HOME_FOOTER + "Character", "Character", [6.0, 1193.4, 133.2, 1307.4], "アイドル", "アイドル")
    add_button(-3210, HOME_FOOTER + "Home", "Home", [260.4, 1193.4, 387.6, 1307.4], "ホーム", "ホーム")
    add_button(-3242, HOME_FOOTER + "Activity", "Activity", [387.6, 1193.4, 514.8, 1307.4], "お仕事", "お仕事")
    add_button(-5710, HOME_ROOT + "HomePage/SlideRoot/Live", "Live", [379.8, 948.6, 607.8, 1176.6])
    add_button(-5934, HOME_ROOT + "HomePage/SlideRoot/ActivityLesson/ActivityLessonButton",
               "ActivityLessonButton", [249.6, 982.8, 350.4, 1069.2], "TAP", "自主トレ")
    add_button(-6108, HOME_ROOT + "HomePage/SlideRoot/DelayMove3/Container/GiftRoot/Gift",
               "Gift", [567.63, 696.0, 639.63, 768.0])
    add_button(-4526, STORY_PATH, "RenewalStory", None, "ストーリー")
    add_button(-4972, HOME_ROOT + "CardPage/SlideRoot/Card/Enhance", "Enhance", None, "アイドル強化")
    add_button(858280, "WindowSystem/WindowRoot/FooterCanvas/ContentArea/FooterContent/Background/Frame/ButtonGroups/HomeButton",
               "HomeButton", None, "ホーム")
    return {"ok": True, "generation": 47,
            "screen": {"width": 648, "height": 1368, "origin": "top-left", "units": "unity-screen-pixels"},
            "startup_observation": {"content_blocking": False, "input_releasing": False}, "nodes": nodes}


@pytest.mark.parametrize("bounds", [None, [], [0, 0, 0, 1], [0, 0, 1, 1081], [0, 0, 541, 1],
                                    [float("nan"), 0, 1, 1], [0, float("inf"), 1, 1],
                                    [-1, 0, 1, 1], [True, 0, 1, 1], "[0,0,1,1]"])
def test_button_candidates_exclude_null_invalid_and_outside_geometry(snapshot, bounds):
    snapshot["nodes"][0]["bounds"] = bounds
    assert ui.buttons(snapshot) == []
    assert choose_button(snapshot, "ライブ") is None


def test_duplicate_same_path_labels_describe_one_footer_button_once(home_snapshot):
    target = choose_button(home_snapshot, r"^アイドル$")
    assert target["instance_id"] == -3146
    assert target["label"] == "アイドル"


def test_label_dedup_preserves_different_text_or_different_descendant_path(home_snapshot):
    path = HOME_FOOTER + "Character"
    home_snapshot["nodes"].extend([
        {"kind": "tmp_text", "active": True, "path": path + "/Label", "text": "NEW"},
        {"kind": "tmp_text", "active": True, "path": path + "/Badge", "text": "アイドル"}])
    target = next(node for node in ui.buttons(home_snapshot) if node["instance_id"] == -3146)
    assert target["label"] == "アイドル NEW アイドル"


@pytest.mark.parametrize("goal,identity", [("lesson", -5934), ("live", -5710), ("idols", -3146),
                                          ("work", -3242), ("gifts", -6108)])
def test_home_goals_select_the_observed_role_even_when_labels_are_empty_or_different(home_snapshot, goal, identity):
    target = ui.goal_button(home_snapshot, goal)
    assert target["instance_id"] == identity
    assert ui.route_button(home_snapshot, goal) is None


def test_home_role_selection_ignores_matching_labels_and_names_outside_home_root(home_snapshot):
    live = next(node for node in home_snapshot["nodes"] if node.get("instance_id") == -5710)
    live["bounds"] = None
    impostor = deepcopy(live)
    impostor.update(instance_id=123, path="OtherWindow/HomePage/SlideRoot/Live", bounds=[0, 0, 100, 100], text="ライブ")
    home_snapshot["nodes"].append(impostor)
    assert ui.goal_button(home_snapshot, "live") is None
    assert ui.route_button(home_snapshot, "live")["instance_id"] == -3210


def test_stories_route_through_character_then_require_fresh_bounded_story(home_snapshot):
    assert ui.goal_button(home_snapshot, "stories") is None
    assert ui.route_button(home_snapshot, "stories")["instance_id"] == -3146
    fresh = deepcopy(home_snapshot)
    fresh["generation"] += 1
    story = next(node for node in fresh["nodes"] if node.get("path") == STORY_PATH and node.get("kind") == "button")
    story["bounds"] = [100, 500, 300, 650]
    assert ui.goal_button(fresh, "stories")["instance_id"] == -4526
    assert ui.route_button(fresh, "stories") is None


@pytest.mark.parametrize("goal,identity", [("lesson", -5934), ("live", -5710), ("gifts", -6108)])
def test_offscreen_home_leaf_routes_only_through_actual_home_footer(home_snapshot, goal, identity):
    next(node for node in home_snapshot["nodes"] if node.get("instance_id") == identity)["bounds"] = None
    assert ui.goal_button(home_snapshot, goal) is None
    assert ui.route_button(home_snapshot, goal)["instance_id"] == -3210


@pytest.mark.parametrize("goal,identity", [("idols", -3146), ("work", -3242), ("unknown", None)])
def test_absent_other_goals_have_no_fallback_route(home_snapshot, goal, identity):
    if identity is not None:
        next(node for node in home_snapshot["nodes"] if node.get("instance_id") == identity)["bounds"] = None
    assert ui.goal_button(home_snapshot, goal) is None
    assert ui.route_button(home_snapshot, goal) is None


@pytest.mark.parametrize("startup", [None, {}, {"input_releasing": False},
                                     {"content_blocking": None, "input_releasing": False},
                                     {"content_blocking": 0, "input_releasing": False},
                                     {"content_blocking": True, "input_releasing": False},
                                     {"content_blocking": False, "input_releasing": True}])
def test_navigation_requires_known_clear_content_and_rejects_observed_input_blocking(home_snapshot, startup):
    home_snapshot["startup_observation"] = startup
    assert ui.navigation_block_reason(home_snapshot) is not None


@pytest.mark.parametrize("startup", [{"content_blocking": False},
                                     {"content_blocking": False, "input_releasing": False},
                                     {"content_blocking": False, "input_releasing": None},
                                     {"content_blocking": False, "input_releasing": 0}])
def test_navigation_accepts_known_clear_content_without_claiming_unknown_input_is_blocking(home_snapshot, startup):
    home_snapshot["startup_observation"] = startup
    assert ui.navigation_block_reason(home_snapshot) is None


@pytest.mark.parametrize("reason,goal", [("menu_live", "live"), ("route_stories", "stories")])
@pytest.mark.parametrize("field,value", [("content_blocking", True), ("input_releasing", True),
                                        ("content_blocking", None)])
def test_navigation_refresh_rechecks_blockers_for_leaf_and_route_inputs(
        home_snapshot, tmp_path, monkeypatch, reason, goal, field, value):
    selected = ui.goal_button(home_snapshot, goal) if reason.startswith("menu_") else ui.route_button(home_snapshot, goal)
    fresh = deepcopy(home_snapshot)
    fresh["generation"] += 1
    fresh["startup_observation"][field] = value

    def unexpected_adb(*args, **kwargs):
        raise AssertionError("Blocked navigation must not collect or inject Android input")

    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, forward=lambda port: 12345,
                         adb=unexpected_adb)
    explorer = ui.UiExplorer(qa)
    monkeypatch.setattr(explorer, "_snapshot", lambda: fresh)
    assert explorer._tap(home_snapshot, selected, reason, 43) is False
    assert explorer.actions == [] and len(explorer.input_errors) == 1
    assert not list(tmp_path.glob("ui-action-*"))


def test_ui_change_signature_tracks_bounds_but_ignores_timer_text_and_snapshot_generation(home_snapshot):
    home_snapshot["nodes"].append({"kind": "tmp_text", "active": True, "instance_id": 22,
                                    "path": HOME_ROOT + "Timer", "text": "00:10", "bounds": [0, 0, 20, 20]})
    initial = ui.UiExplorer._signature(home_snapshot)
    fresh = deepcopy(home_snapshot)
    fresh["generation"] += 1
    fresh["nodes"][-1]["text"] = "00:09"
    assert ui.UiExplorer._signature(fresh) == initial
    next(node for node in fresh["nodes"] if node.get("instance_id") == -5710)["bounds"] = [100, 200, 300, 400]
    assert ui.UiExplorer._signature(fresh) != initial


def test_pending_goal_under_loading_has_no_outcome_or_restart(home_snapshot, tmp_path, monkeypatch):
    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, forward=lambda port: 12345)
    explorer = ui.UiExplorer(qa)
    explorer.goal_index = next(i for i, goal in enumerate(ui._GOALS) if goal[0] == "live")
    explorer.pending = ("live", 1, explorer._signature(home_snapshot))
    pending = explorer.pending
    blocked = deepcopy(home_snapshot)
    blocked["startup_observation"]["content_blocking"] = True
    next(node for node in blocked["nodes"] if node.get("instance_id") == -5710)["bounds"] = None
    restarts, taps = [], []
    monkeypatch.setattr(explorer, "_snapshot", lambda: blocked)
    monkeypatch.setattr(explorer, "_restart", lambda: restarts.append(True))
    monkeypatch.setattr(explorer, "_tap", lambda *args: taps.append(args))
    monkeypatch.setattr(ui, "time", SimpleNamespace(monotonic=lambda: 100))
    for frame in (43, 53, 70):
        explorer.step(frame)
    assert explorer.pending == pending
    assert explorer.goal_index == 1 and explorer.outcomes == []
    assert restarts == [] and taps == []


def test_absent_goal_is_not_completed_merely_because_other_home_buttons_exist(home_snapshot, tmp_path, monkeypatch):
    for node in home_snapshot["nodes"]:
        if node.get("instance_id") in (-5934, -3210):
            node["bounds"] = None
    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, forward=lambda port: 12345)
    explorer = ui.UiExplorer(qa)
    restarts, taps = [], []
    monkeypatch.setattr(explorer, "_snapshot", lambda: home_snapshot)
    monkeypatch.setattr(explorer, "_restart", lambda: restarts.append(True))
    monkeypatch.setattr(explorer, "_tap", lambda *args: taps.append(args))
    monkeypatch.setattr(ui, "time", SimpleNamespace(monotonic=lambda: 100))
    for frame in (43, 53, 70):
        explorer.step(frame)
    assert explorer.goal_index == 0 and explorer.pending is None
    assert explorer.outcomes == [] and restarts == [] and taps == []


def test_story_page_route_waits_without_repeating_then_uses_fresh_bounded_destination(home_snapshot, tmp_path, monkeypatch):
    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, forward=lambda port: 12345)
    explorer = ui.UiExplorer(qa)
    goal_index = next(i for i, goal in enumerate(ui._GOALS) if goal[0] == "stories")
    explorer.goal_index = goal_index
    current = [home_snapshot]
    taps = []

    def tap(snapshot, node, reason, frame):
        taps.append((reason, node["instance_id"], snapshot["generation"]))
        return True

    monkeypatch.setattr(explorer, "_snapshot", lambda: current[0])
    monkeypatch.setattr(explorer, "_tap", tap)
    monkeypatch.setattr(ui, "time", SimpleNamespace(monotonic=lambda: 100))
    for frame in (43, 44, 53):
        explorer.step(frame)
    assert taps == [("route_stories", -3146, 47)]
    assert explorer.pending is None and explorer.goal_index == goal_index
    assert explorer.route_pending == {"goal": "stories", "frame": 43, "path": HOME_FOOTER + "Character"}
    assert explorer.outcomes == []

    fresh = deepcopy(home_snapshot)
    fresh["generation"] += 1
    next(node for node in fresh["nodes"] if node.get("instance_id") == -4526)["bounds"] = [100, 500, 300, 650]
    current[0] = fresh
    explorer.step(54)
    assert taps[-1] == ("menu_stories", -4526, 48)
    assert explorer.pending == ("stories", 54, explorer._signature(fresh))
    assert explorer.route_pending is None and explorer.outcomes == []


def test_transient_dialog_evidence_waits_for_clear_navigation_before_pending_outcome(home_snapshot, tmp_path, monkeypatch):
    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, forward=lambda port: 12345)
    explorer = ui.UiExplorer(qa)
    explorer.goal_index = next(i for i, goal in enumerate(ui._GOALS) if goal[0] == "live")
    explorer.pending = ("live", 1, explorer._signature(home_snapshot))
    dialog = deepcopy(home_snapshot)
    dialog["startup_observation"]["content_blocking"] = True
    dialog["nodes"].append({"kind": "button", "active": True, "interactable": True,
                            "instance_id": 300, "name": "Close", "path": "Window/Dialog/Close",
                            "text": "OK", "bounds": [100, 500, 300, 650]})
    current, restarts, taps = [dialog], [], []
    monkeypatch.setattr(explorer, "_snapshot", lambda: current[0])
    monkeypatch.setattr(explorer, "_restart", lambda: restarts.append(True))
    monkeypatch.setattr(explorer, "_tap", lambda snapshot, node, reason, frame: taps.append(reason) or True)
    monkeypatch.setattr(ui, "time", SimpleNamespace(monotonic=lambda: 100))
    explorer.step(43)
    assert taps == ["observed_dialog"]
    assert explorer.pending_dialog_frame == 43 and explorer.outcomes == [] and restarts == []
    current[0] = deepcopy(home_snapshot)
    current[0]["startup_observation"]["content_blocking"] = True
    explorer.step(53)
    assert explorer.pending is not None and explorer.outcomes == [] and restarts == []
    current[0]["startup_observation"]["content_blocking"] = False
    explorer.step(54)
    assert len(explorer.outcomes) == 1
    assert explorer.outcomes[0]["status"] == "different_ui_tree_observed"
    assert explorer.outcomes[0]["transient_dialog_frame"] == 43
    assert explorer.pending is None and restarts == [True]


def test_observed_game_error_defers_restart_until_loading_clears(home_snapshot, tmp_path, monkeypatch):
    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, forward=lambda port: 12345)
    explorer = ui.UiExplorer(qa)
    explorer.goal_index = next(i for i, goal in enumerate(ui._GOALS) if goal[0] == "live")
    explorer.pending = ("live", 1, explorer._signature(home_snapshot))
    blocked = deepcopy(home_snapshot)
    blocked["startup_observation"]["content_blocking"] = True
    blocked["nodes"].append({"kind": "tmp_text", "active": True,
                             "path": "Window/Dialog/Error", "text": "NullReferenceException"})
    current, restarts = [blocked], []
    monkeypatch.setattr(explorer, "_snapshot", lambda: current[0])
    monkeypatch.setattr(explorer, "_restart", lambda: restarts.append(True))
    monkeypatch.setattr(ui, "time", SimpleNamespace(monotonic=lambda: 100))
    for frame in (43, 53):
        explorer.step(frame)
    assert len(explorer.outcomes) == 1 and explorer.outcomes[0]["status"] == "game_error_observed"
    assert explorer.restart_pending is True and restarts == []
    current[0] = home_snapshot
    explorer.step(54)
    assert len(explorer.outcomes) == 1 and explorer.restart_pending is False
    assert restarts == [True]


def test_repeated_missing_android_surface_stops_without_fabricating_menu_results():
    qa = SimpleNamespace(game_package=PACKAGE, forward=lambda port: port)
    explorer = ui.UiExplorer(qa)
    for count in range(1, 4):
        assert explorer._input_error("A unique current Unity accessibility surface is required") is False
        assert explorer.stopped is (count == 3)
    assert explorer.stop_reason == "android_surface_unavailable"
    assert explorer.report()["repeated_android_surface_failures"] == 3
    assert explorer.actions == [] and explorer.outcomes == []


def test_other_input_guard_failure_resets_the_repeated_surface_failure_window():
    qa = SimpleNamespace(game_package=PACKAGE, forward=lambda port: port)
    explorer = ui.UiExplorer(qa)
    explorer._input_error("A unique current Unity accessibility surface is required")
    explorer._input_error("A unique current Unity accessibility surface is required")
    explorer._input_error("ui_observation_became_stale")
    explorer._input_error("A unique current Unity accessibility surface is required")
    assert explorer.surface_input_failures == 1 and not explorer.stopped


NOTICE_ROOT = "Singleton/GlobalDialog/DialogManager/NoticeDialog(Clone)/"
NOTICE_BASE = NOTICE_ROOT + "TabDialogBase/DialogCanvas/Dialog/"


@pytest.fixture
def notice_snapshot(home_snapshot):
    # Minimal public dialog nodes from run42793871383 unity-ui-043.json.
    result = deepcopy(home_snapshot)
    result["nodes"].append({"kind": "tmp_text", "active": True, "text": "INFORMATION",
                            "path": NOTICE_BASE + "Header/Title", "instance_id": -15698})
    for number, label, bounds in ((1, "お知らせ", [67.2, 1140, 230.4, 1212]),
                                  (2, "不具合", [242.4, 1140, 405.6, 1212]),
                                  (3, "PR", [417.6, 1140, 580.8, 1212])):
        path = NOTICE_BASE + f"Footer/TabButtons/Button{number}"
        result["nodes"].extend([
            {"kind": "button", "active": True, "interactable": True, "callback_registered": True,
             "instance_id": -16000 - number, "name": f"Button{number}", "path": path,
             "text": "", "bounds": bounds},
            {"kind": "tmp_text", "active": True, "text": label, "path": path + "/Text"}])
    result["nodes"].append({"kind": "button", "active": True, "interactable": True,
                            "callback_registered": True, "instance_id": -16020, "name": "CloseButton",
                            "path": NOTICE_BASE + "Footer/CloseButton", "text": "",
                            "bounds": [288, 1236, 360, 1308]})
    return result


def test_observed_notice_textless_x_is_selected_without_using_background_labels(notice_snapshot):
    node = ui.notice_close_target(notice_snapshot)
    assert node["instance_id"] == -16020 and node["label"] == ""
    assert node["path"] == NOTICE_BASE + "Footer/CloseButton"
    assert ui.visible_global_dialogs(notice_snapshot) == {NOTICE_ROOT}


@pytest.mark.parametrize("change", ["header", "tab", "missing_close", "ambiguous_close",
                                   "callback", "inactive", "geometry", "name"])
def test_notice_context_or_close_ambiguity_prevents_selection(notice_snapshot, change):
    close = next(n for n in notice_snapshot["nodes"] if n.get("name") == "CloseButton")
    if change == "header":
        next(n for n in notice_snapshot["nodes"] if n.get("path") == NOTICE_BASE + "Header/Title")["text"] = "Purchase"
    elif change == "tab":
        next(n for n in notice_snapshot["nodes"] if n.get("path", "").endswith("Button2/Text"))["text"] = "Other"
    elif change == "missing_close":
        notice_snapshot["nodes"].remove(close)
    elif change == "ambiguous_close":
        notice_snapshot["nodes"].append(dict(close, instance_id=-42))
    elif change == "callback":
        close["callback_registered"] = False
    elif change == "inactive":
        close["active"] = False
    elif change == "geometry":
        close["bounds"] = [288, 1236, 360, 2000]
    else:
        close["name"] = "OtherButton"
    assert ui.notice_close_target(notice_snapshot) is None


def competing_modal(snapshot):
    snapshot["nodes"].append({"kind": "button", "active": True, "interactable": True,
                              "instance_id": -999, "name": "Buy", "text": "購入",
                              "path": "Singleton/GlobalDialog/DialogManager/PurchaseDialog(Clone)/Buy",
                              "bounds": [1, 1, 100, 100]})


def test_competing_purchase_modal_still_blocks_although_its_button_is_forbidden(notice_snapshot):
    competing_modal(notice_snapshot)
    assert len(ui.visible_global_dialogs(notice_snapshot)) == 2
    assert ui.notice_close_target(notice_snapshot) is None
    assert not any(n["name"] == "Buy" for n in ui.buttons(notice_snapshot))


@pytest.mark.parametrize("change", ["header", "callback", "competing"])
def test_notice_context_is_revalidated_before_any_android_input(notice_snapshot, tmp_path, monkeypatch, change):
    selected = ui.notice_close_target(notice_snapshot)
    fresh = deepcopy(notice_snapshot)
    if change == "header":
        next(n for n in fresh["nodes"] if n.get("path") == NOTICE_BASE + "Header/Title")["text"] = "Other"
    elif change == "callback":
        next(n for n in fresh["nodes"] if n.get("name") == "CloseButton")["callback_registered"] = False
    else:
        competing_modal(fresh)
    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, forward=lambda port: port,
                         adb=lambda *args, **kwargs: pytest.fail("Stale notice must never call adb"))
    explorer = ui.UiExplorer(qa)
    monkeypatch.setattr(explorer, "_snapshot", lambda: fresh)
    assert not explorer._tap(notice_snapshot, selected, "observed_notice_close", 43)
    assert explorer.actions == [] and explorer.input_errors == {"notice_dialog_changed": 1}


def test_fresh_valid_notice_uses_normal_android_tap_at_its_tree_bounds(notice_snapshot, tmp_path, monkeypatch):
    inputs = []
    responses = {("exec-out", "screencap", "-p"): b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 1080, 2280),
                 ("shell", "wm", "size"): "Physical size: 1080x2280\n",
                 ("exec-out", "uiautomator", "dump", "/dev/tty"): XML.replace("[0,48][1080,2208]", "[0,0][1080,2148]")}

    def adb(*args, **kwargs):
        if args[:3] == ("shell", "input", "tap"):
            inputs.append(args)
            return ""
        return responses[args]

    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, forward=lambda port: port,
                         touch_hold_ms=0, adb=adb)
    explorer = ui.UiExplorer(qa)
    monkeypatch.setattr(explorer, "_snapshot", lambda: notice_snapshot)
    assert explorer._tap(notice_snapshot, ui.notice_close_target(notice_snapshot), "observed_notice_close", 43)
    assert inputs == [("shell", "input", "tap", "540", "2120")]
    assert explorer.actions[0]["reason"] == "observed_notice_close"


@pytest.mark.parametrize("reason", ["menu_live", "route_stories", "observed_title", "observed_dialog"])
def test_modal_appearing_during_refresh_blocks_every_background_input(home_snapshot, notice_snapshot, tmp_path, monkeypatch, reason):
    target = ui.goal_button(home_snapshot, "live")
    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, forward=lambda port: port,
                         adb=lambda *args, **kwargs: pytest.fail("Background input must not reach adb"))
    explorer = ui.UiExplorer(qa)
    monkeypatch.setattr(explorer, "_snapshot", lambda: notice_snapshot)
    assert not explorer._tap(home_snapshot, target, reason, 43)
    assert explorer.input_errors == {"visible_global_dialog_blocks_input": 1}
    assert explorer.actions == []


@pytest.mark.parametrize("goal", ["lesson", "live", "idols", "work"])
def test_notice_prevents_the_four_observed_background_menu_outcomes(notice_snapshot, tmp_path, monkeypatch, goal):
    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, forward=lambda port: port)
    explorer = ui.UiExplorer(qa)
    explorer.goal_index = next(i for i, row in enumerate(ui._GOALS) if row[0] == goal)
    explorer.pending = (goal, 1, explorer._signature(notice_snapshot))
    before = explorer.pending
    taps, restarts = [], []
    monkeypatch.setattr(explorer, "_snapshot", lambda: notice_snapshot)
    monkeypatch.setattr(explorer, "_tap", lambda snap, node, reason, frame: taps.append(reason) or True)
    monkeypatch.setattr(explorer, "_restart", lambda: restarts.append(True))
    monkeypatch.setattr(ui, "time", SimpleNamespace(monotonic=lambda: 100))
    for frame in (43, 44, 45):
        explorer.step(frame)
    assert taps == ["observed_notice_close", "observed_notice_close"]
    assert explorer.pending == before and explorer.outcomes == [] and restarts == []
    assert explorer.stopped and explorer.stop_reason == "global_dialog_not_dismissed"


def test_unknown_global_dialog_stops_after_three_observations_without_generic_close(notice_snapshot, tmp_path, monkeypatch):
    competing_modal(notice_snapshot)
    notice_snapshot["nodes"].append({"kind": "button", "active": True, "interactable": True,
                                    "instance_id": 999, "path": "Window/Dialog/Close", "name": "Close",
                                    "text": "OK", "bounds": [1, 1, 100, 100]})
    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, forward=lambda port: port)
    explorer = ui.UiExplorer(qa)
    monkeypatch.setattr(explorer, "_snapshot", lambda: notice_snapshot)
    monkeypatch.setattr(explorer, "_tap", lambda *args: pytest.fail("Unknown modal must not authorize generic close"))
    monkeypatch.setattr(explorer, "_restart", lambda: pytest.fail("No restart behind a modal"))
    monkeypatch.setattr(ui, "time", SimpleNamespace(monotonic=lambda: 100))
    for frame in (43, 44, 45):
        explorer.step(frame)
    assert explorer.stopped and explorer.stop_reason == "unrecognized_global_dialog"
    assert explorer.actions == explorer.outcomes == []


LESSON_ROOT = "Singleton/GlobalDialog/DialogManager/ActivityLessonReceiveDIalog(Clone)/"
LESSON_BASE = LESSON_ROOT + "BasicDialogBase/DialogCanvas/Dialog/"
LEVEL_ROOT = "WindowSystem/WindowRoot/HomeWindow(Clone)/HomeTopScreen(Clone)/ManagerLvUpOverlay(Clone)/"
LEVEL_BASE = LEVEL_ROOT + "OverlayCanvas/SlideRoot/ContentArea/ContentRoot/"


@pytest.fixture
def layered_lesson(home_snapshot):
    # Minimal real frame31/32 nodes from run42810660579 at 540x1140.
    result = deepcopy(home_snapshot)
    result["screen"].update(width=540, height=1140)
    for node in result["nodes"]:
        if isinstance(node.get("bounds"), list):
            node["bounds"] = [v * 5 / 6 for v in node["bounds"]]

    def label(path, value, bounds=None):
        result["nodes"].append({"kind": "tmp_text", "path": path, "text": value,
                                "active": True, "bounds": bounds})

    def button(path, ident, bounds, enabled=True, callback=True):
        result["nodes"].append({"kind": "button", "name": path.rsplit("/", 1)[-1],
                                "path": path, "instance_id": ident, "bounds": bounds,
                                "active": True, "interactable": enabled, "callback_registered": callback,
                                "text": ""})

    label(LEVEL_BASE + "Content/PrevLevelAnchor/prevLevel", "2", [174, 340, 366, 500])
    label(LEVEL_BASE + "Content/CurrentLevelAnchor/currentLevel", "3", [150, 320, 390, 520])
    button(LEVEL_BASE + "CloseButton", -26340, [240, 1050, 300, 1110])
    button(LEVEL_BASE + "ActionButton", -26358, [210.5, 918, 329.5, 1037], callback=False)
    label(LESSON_BASE + "Header/Title", "00:02:00 の自主トレ")
    label(LESSON_BASE + "Body/MainContentsRoot/MainLive", "メインライブ")
    label(LESSON_BASE + "Body/MainContentsRoot/LiveName", "#01 Rapture渋谷")
    label(LESSON_BASE + "Body/Rewards/RewardRoot/RewardTitle", "成果")
    button(LESSON_BASE + "Footer/CloseButton", -20874, [240, 812.5, 300, 872.5], enabled=False)
    button(LESSON_ROOT + "BasicDialogBase/DialogCanvas/Background", -20476, [0, 0, 540, 1140])
    button(LESSON_BASE + "FloatButtonRoot/PromoteButton", -20900, [347.5, 725, 512.5, 890], callback=False)
    return result


def without_level_overlay(snapshot):
    result = deepcopy(snapshot)
    result["nodes"] = [n for n in result["nodes"] if not n.get("path", "").startswith(LEVEL_ROOT)]
    next(n for n in result["nodes"] if n.get("path") == LESSON_BASE + "Footer/CloseButton")["interactable"] = True
    return result


def test_actual_layered_level_up_must_close_before_disabled_reward_footer(layered_lesson):
    assert ui.visible_manager_level_overlay(layered_lesson)
    assert ui.manager_level_close_target(layered_lesson)["instance_id"] == -26340
    assert ui.lesson_reward_close_target(layered_lesson) is None
    reward = without_level_overlay(layered_lesson)
    assert not ui.visible_manager_level_overlay(reward)
    assert ui.manager_level_close_target(reward) is None
    assert ui.lesson_reward_close_target(reward)["instance_id"] == -20874
    assert "PromoteButton" not in ui.lesson_reward_close_target(reward)["path"]


@pytest.mark.parametrize("change", ["missing_previous", "wrong_current", "no_callback", "bounds", "competing"])
def test_level_up_missing_context_or_competing_modal_is_not_acknowledged(layered_lesson, change):
    if change == "missing_previous":
        layered_lesson["nodes"] = [n for n in layered_lesson["nodes"] if not n.get("path", "").endswith("/prevLevel")]
    elif change == "wrong_current":
        next(n for n in layered_lesson["nodes"] if n.get("path", "").endswith("/currentLevel"))["text"] = "4"
    elif change == "no_callback":
        next(n for n in layered_lesson["nodes"] if n.get("path") == LEVEL_BASE + "CloseButton")["callback_registered"] = False
    elif change == "bounds":
        next(n for n in layered_lesson["nodes"] if n.get("path") == LEVEL_BASE + "CloseButton")["bounds"] = [0, 0, 600, 1200]
    else:
        competing_modal(layered_lesson)
    assert ui.manager_level_close_target(layered_lesson) is None
    assert ui.lesson_reward_close_target(layered_lesson) is None


@pytest.mark.parametrize("change", ["disabled", "missing_header", "ambiguous", "competing", "level_reappeared"])
def test_reward_close_requires_fresh_unobscured_enabled_unique_footer(layered_lesson, change):
    reward = without_level_overlay(layered_lesson)
    close = next(n for n in reward["nodes"] if n.get("path") == LESSON_BASE + "Footer/CloseButton")
    if change == "disabled":
        close["interactable"] = False
    elif change == "missing_header":
        reward["nodes"] = [n for n in reward["nodes"] if n.get("path") != LESSON_BASE + "Header/Title"]
    elif change == "ambiguous":
        reward["nodes"].append(dict(close, instance_id=-77))
    elif change == "competing":
        competing_modal(reward)
    else:
        reward["nodes"].extend(n for n in layered_lesson["nodes"] if n.get("path", "").startswith(LEVEL_ROOT))
    assert ui.lesson_reward_close_target(reward) is None


@pytest.mark.parametrize("reason", ["observed_manager_level_close", "observed_lesson_reward_close"])
@pytest.mark.parametrize("change", ["competing", "closed"])
def test_layered_modal_target_is_revalidated_and_no_stale_close_is_dispatched(layered_lesson, tmp_path, monkeypatch, reason, change):
    original = layered_lesson if reason == "observed_manager_level_close" else without_level_overlay(layered_lesson)
    target = (ui.manager_level_close_target(original) if reason == "observed_manager_level_close"
              else ui.lesson_reward_close_target(original))
    fresh = deepcopy(original)
    if change == "competing":
        competing_modal(fresh)
    else:
        root = LEVEL_ROOT if reason == "observed_manager_level_close" else LESSON_ROOT
        fresh["nodes"] = [n for n in fresh["nodes"] if not n.get("path", "").startswith(root)]
    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, forward=lambda port: port,
                         adb=lambda *args, **kwargs: pytest.fail("Stale acknowledgement must not reach adb"))
    explorer = ui.UiExplorer(qa)
    monkeypatch.setattr(explorer, "_snapshot", lambda: fresh)
    assert not explorer._tap(original, target, reason, 31)
    error = "selected_modal_changed" if change == "competing" else "selected_node_no_longer_present"
    assert explorer.actions == [] and explorer.input_errors == {error: 1}


def test_level_then_reward_then_home_are_separate_observations_without_background_outcome(layered_lesson, tmp_path, monkeypatch):
    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, forward=lambda port: port)
    explorer = ui.UiExplorer(qa)
    current = [layered_lesson]
    explorer.pending = ("lesson", 29, explorer._signature(layered_lesson))
    taps, restarts = [], []
    monkeypatch.setattr(explorer, "_snapshot", lambda: current[0])
    monkeypatch.setattr(explorer, "_tap", lambda snapshot, node, reason, frame: taps.append((reason, node["instance_id"])) or True)
    monkeypatch.setattr(explorer, "_restart", lambda: restarts.append(True))
    monkeypatch.setattr(ui, "time", SimpleNamespace(monotonic=lambda: 100))
    explorer.step(31)
    explorer.step(32)
    assert taps == [("observed_manager_level_close", -26340)] * 2
    assert explorer.pending and explorer.outcomes == [] and restarts == []
    current[0] = without_level_overlay(layered_lesson)
    explorer.step(33)  # A different acknowledged layer resets the repeat guard.
    assert taps[-1] == ("observed_lesson_reward_close", -20874)
    assert explorer.pending_dialog_frame == 33 and explorer.outcomes == [] and not explorer.stopped
    current[0]["nodes"] = [n for n in current[0]["nodes"] if not n.get("path", "").startswith(LESSON_ROOT)]
    home = deepcopy(current[0])
    next(n for n in current[0]["nodes"] if n.get("name") == "Home")["bounds"] = None
    explorer.step(34)
    assert explorer.pending and explorer.outcomes == [] and restarts == []
    current[0] = home
    explorer.step(35)
    assert len(explorer.outcomes) == 1 and explorer.outcomes[0]["transient_dialog_frame"] == 33
    assert restarts == [True]
    assert all("PromoteButton" not in str(row) for row in taps)


def test_level_overlay_without_global_dialog_still_blocks_background_menu_and_outcome(layered_lesson, tmp_path, monkeypatch):
    layered_lesson["nodes"] = [n for n in layered_lesson["nodes"] if not n.get("path", "").startswith(LESSON_ROOT)]
    qa = SimpleNamespace(game_package=PACKAGE, artifacts=tmp_path, forward=lambda port: port)
    explorer = ui.UiExplorer(qa)
    explorer.pending = ("lesson", 1, explorer._signature(layered_lesson))
    monkeypatch.setattr(explorer, "_snapshot", lambda: layered_lesson)
    monkeypatch.setattr(explorer, "_tap", lambda *args: pytest.fail("Unknown overlay context cannot authorize input"))
    monkeypatch.setattr(explorer, "_restart", lambda: pytest.fail("No restart behind level overlay"))
    monkeypatch.setattr(ui, "time", SimpleNamespace(monotonic=lambda: 100))
    for n in (31, 32, 33):
        explorer.step(n)
    assert explorer.stopped and explorer.outcomes == []


def test_korean_client_resource_sheet_selects_its_execute_button(download_sheet):
    # Korean labels observed in the redroid run of the unified Korean client.
    texts = {"/Execute/TextButtonNormal/Text": "다운로드", "/Cancel/TextButtonNormal/Text": "취소",
             "/Header/Description": "필요한 데이터를 다운로드 합니다 (1.07 GB)", "/Header/Title": "다운로드 확인"}
    for node in download_sheet["nodes"]:
        for suffix, label in texts.items():
            if node["path"].endswith(suffix):
                node["text"] = label
    target = download_confirmation(download_sheet)
    assert target["instance_id"] == -2544 and target["label"] == "다운로드"
    # A Korean purchase/deletion description never authorizes the action.
    download_sheet["nodes"][-2]["text"] = "이 상품을 구매합니다 (1.07 GB)"
    assert download_confirmation(download_sheet) is None


def test_korean_forbidden_and_error_labels_are_recognized():
    for label in ("구매", "과금", "가챠", "데이터 삭제", "계정 삭제"):
        assert ui._FORBIDDEN.search(label)
    assert ui._ERROR.search("서버와의 통신에 실패했습니다")


def test_fully_localized_notice_tabs_are_accepted_but_mixed_or_forbidden_are_not(notice_snapshot):
    tabs = [n for n in notice_snapshot["nodes"] if n.get("path", "").endswith(("Button1/Text", "Button2/Text", "Button3/Text"))]
    for node, label in zip(sorted(tabs, key=lambda n: n["path"]), ("공지사항", "오류", "PR")):
        node["text"] = label
    assert ui.notice_close_target(notice_snapshot) is not None
    sorted(tabs, key=lambda n: n["path"])[1]["text"] = "구매"
    assert ui.notice_close_target(notice_snapshot) is None


def test_touch_hold_spans_frames_on_a_slow_guest():
    # redroid run 15: ~0.9 s frames; 501 notice-close touches of 150 ms all missed.
    hold = ui.touch_hold_for_frame
    assert hold({"frame_observation": {"unscaled_delta_time": 0.033}}, "observed_notice_close") == 150
    assert hold({}, "qa_mv_route") == 150
    assert hold({"frame_observation": {"unscaled_delta_time": 0.15}}, "observed_notice_close") == 390
    # Run 17: a hold of 0.5 s or more is a long tap whose click is suppressed.
    assert hold({"frame_observation": {"unscaled_delta_time": 0.9}}, "observed_notice_close") == 450
    assert hold({"frame_observation": {"unscaled_delta_time": 5.0}}, "qa_mv_route") == 450


def test_asset_retry_is_only_the_e209_dialogs_own_retry_button():
    root = "Singleton/GlobalDialog/ErrorDialogManager/SystemDialog(Clone)/SystemDialogCommonRoot/DialogCanvas/Dialog/"
    button = {"instance_id": 1, "kind": "button", "name": "OkButton", "path": root + "Buttons/Root/OkButton",
              "active": True, "interactable": True, "bounds": [431.0, 652.0, 514.0, 712.0], "text": ""}
    def snapshot(description):
        return {"ok": True, "screen": {"width": 540, "height": 1140, "origin": "top-left", "units": "unity-screen-pixels"}, "nodes": [button, {"instance_id": 2, "kind": "tmp_text", "name": "Description",
                "path": root + "Description", "active": True, "text": description, "bounds": [0, 0, 1, 1]}]}
    found = ui.asset_retry_target(snapshot("에셋 획득 실패\n네트워크 환경을 확인한 후 재시도해 주세요\n(E209)"))
    assert found is not None and found["instance_id"] == 1
    assert ui.asset_retry_target(snapshot("다른 오류 (E100)")) is None
