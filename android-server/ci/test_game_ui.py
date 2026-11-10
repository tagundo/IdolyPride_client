"""UI inputs use observed hierarchy identities and geometry, never OCR points."""
from copy import deepcopy
import struct
from types import SimpleNamespace
import pytest

import qa_game_ui as ui
from qa_game_ui import choose_button, download_confirmation, mapped_point, title_block_reason


PACKAGE = "game.qualiarts.idolypride.local.diagnostics"
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
def test_slow_unity_query_does_not_age_the_response_but_late_android_collection_does(
        snapshot, tmp_path, monkeypatch, collection_seconds, allowed):
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
