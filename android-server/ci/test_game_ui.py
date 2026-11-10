"""UI inputs use observed hierarchy identities and geometry, never OCR points."""
from copy import deepcopy
import pytest

from qa_game_ui import choose_button, mapped_point


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
