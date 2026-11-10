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
