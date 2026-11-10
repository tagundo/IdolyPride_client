"""Only the captured Android immersive education dialog may receive an OS tap."""
from collections import deque
import json
import struct
import xml.etree.ElementTree as ET

import pytest

from qa_game_boot import GameQA, immersive_cling_target


# Minimized public OS nodes from run42785951638 game-50-1000s.xml.
CLING = '''<hierarchy rotation="0"><node package="android" class="android.widget.FrameLayout" bounds="[0,0][1080,2280]" enabled="true" clickable="false">
<node package="android" class="android.widget.RelativeLayout" bounds="[0,0][1080,653]" enabled="true" clickable="false">
<node package="android" class="android.widget.TextView" resource-id="android:id/immersive_cling_title" text="Viewing full screen" bounds="[66,209][1014,297]" enabled="true" clickable="false"/>
<node package="android" class="android.widget.TextView" resource-id="android:id/immersive_cling_description" text="To exit, swipe down from the top of your screen" bounds="[66,297][1014,389]" enabled="true" clickable="false"/>
<node package="android" class="android.widget.Button" resource-id="android:id/ok" text="Got it" bounds="[819,455][1014,587]" enabled="true" clickable="true"/>
</node></node></hierarchy>'''
PACKAGE = "game.qualiarts.idolypride.local.diagnostics"
GAME = ('<hierarchy><node package="' + PACKAGE + '" resource-id="' + PACKAGE +
        ':id/unitySurfaceView" bounds="[0,0][1080,2280]" enabled="true"/></hierarchy>')
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 1080, 2280)


def changed(**attributes):
    root = ET.fromstring(CLING)
    button = next(n for n in root.iter("node") if n.get("resource-id") == "android:id/ok")
    button.attrib.update(attributes)
    return ET.tostring(root, encoding="unicode")


def test_actual_captured_dialog_selects_only_its_enabled_os_button():
    target = immersive_cling_target(CLING, [1080, 2280])
    assert target["point"] == [916, 521]
    assert target["bounds"] == [819, 455, 1014, 587]
    assert target["package"] == "android"
    assert immersive_cling_target(GAME, [1080, 2280]) is None


@pytest.mark.parametrize("xml", [
    CLING.replace("immersive_cling_title", "other_title"),
    CLING.replace("immersive_cling_description", "other_description"),
    CLING.replace('package="android"', 'package="other.app"'),
    CLING.replace("Viewing full screen", "Permission request"),
    changed(**{"class": "android.widget.TextView"}),
    changed(enabled="false"), changed(clickable="false"),
    changed(bounds="[819,455][1081,587]"), changed(bounds="[819,455][819,587]"),
    changed(bounds="[-1,455][1014,587]"), "not xml",
])
def test_other_or_unsafe_dialog_never_selects_a_button(xml):
    assert immersive_cling_target(xml, [1080, 2280]) is None


def test_ambiguous_ok_buttons_are_rejected_even_if_one_is_disabled():
    root = ET.fromstring(CLING)
    duplicate = ET.SubElement(root, "node", package="android", **{
        "resource-id": "android:id/ok", "class": "android.widget.Button", "text": "Got it",
        "enabled": "false", "clickable": "false", "bounds": "[1,1][20,20]"})
    assert duplicate is not None
    assert immersive_cling_target(ET.tostring(root), [1080, 2280]) is None


@pytest.mark.parametrize("size", [[0, 2280], [1080, 500], [True, 2280], [1080], None])
def test_invalid_or_changed_screenshot_dimensions_fail_closed(size):
    assert immersive_cling_target(CLING, size) is None


class FakeGame(GameQA):
    def __init__(self, directory, fresh=()):
        super().__init__("unused-adb", "emulator-5554", directory)
        self.game_package = PACKAGE
        self.fresh = deque(fresh)
        self.inputs = []

    def write_capture(self, stage, xml):
        (self.artifacts / (stage + ".xml")).write_text(xml)
        (self.artifacts / (stage + ".png")).write_bytes(PNG)

    def capture(self, stage):
        xml = self.fresh.popleft()
        self.write_capture(stage, xml)
        return ET.fromstring(xml)

    def adb(self, *args, **kwargs):
        self.inputs.append(args)
        return ""


def test_late_dialog_is_rechecked_then_dismissed_with_separate_evidence(tmp_path):
    qa = FakeGame(tmp_path, [CLING, GAME])
    qa.write_capture("game-0", GAME)
    assert qa.dismiss_immersive_cling("game-0") is True
    qa.write_capture("game-1", CLING)
    assert qa.dismiss_immersive_cling("game-1") is False  # Never game-click this same frame.
    assert qa.inputs == [("shell", "input", "tap", "916", "521")]
    action = qa.system_dialog_actions[0]
    assert action["performed"] and action["dismissed"]
    assert action["input_tree"] == "system-dialog-001-before.xml"
    assert action["after_capture"] == "system-dialog-001-after"
    assert json.loads((tmp_path / "system-dialog-001.json").read_text()) == action
    assert not getattr(qa, "title_actions", [])
    qa.write_capture("game-2", GAME)
    assert qa.dismiss_immersive_cling("game-2") is True


@pytest.mark.parametrize("fresh", [GAME, changed(bounds="[820,455][1014,587]"),
                                  CLING.replace("Viewing full screen", "Another dialog")])
def test_replaced_or_moved_window_between_capture_and_input_is_not_tapped(tmp_path, fresh):
    qa = FakeGame(tmp_path, [fresh])
    qa.write_capture("game-0", CLING)
    assert qa.dismiss_immersive_cling("game-0") is False
    assert not qa.inputs
    assert qa.system_dialog_actions[0]["reason"] == "system_dialog_changed_before_input"


def test_post_tap_overlay_is_not_reported_as_dismissed(tmp_path):
    qa = FakeGame(tmp_path, [CLING, CLING])
    qa.write_capture("game-0", CLING)
    assert qa.dismiss_immersive_cling("game-0") is False
    assert qa.system_dialog_actions[0]["performed"] is True
    assert qa.system_dialog_actions[0]["dismissed"] is False


def test_unknown_os_window_never_taps_through_and_stops_after_three_frames(tmp_path):
    qa = FakeGame(tmp_path)
    unknown = CLING.replace("Viewing full screen", "Another system dialog")
    for n in range(3):
        qa.write_capture("game-" + str(n), unknown)
        if n < 2:
            assert qa.dismiss_immersive_cling("game-" + str(n)) is False
        else:
            with pytest.raises(RuntimeError, match="three consecutive captures"):
                qa.dismiss_immersive_cling("game-" + str(n))
    assert not qa.inputs
    assert len(qa.system_dialog_actions) == 3


def test_missing_capture_is_left_to_existing_surface_watchdog(tmp_path):
    qa = FakeGame(tmp_path)
    assert qa.dismiss_immersive_cling("missing") is True
    assert not qa.inputs
