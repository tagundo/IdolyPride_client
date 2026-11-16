"""Contract tests for the real public-OS Android locale and rotation QA.

Synthetic UI trees exercise fail-closed observation, not the application itself.
The owned emulator job still runs every real UI stage and all 32 legacy gates.
"""
import importlib.util
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / "android-server/ci"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if "qa_account_management" not in sys.modules:
    sys.modules["qa_account_management"] = load_module("qa_account_management", CI / "qa_account_management.py")
probe = load_module("android_interface_configuration_qa", CI / "qa_interface.py")
PACKAGE = "game.qualiarts.idolypride.localserver"
CATEGORIES = ("console", "server", "users", "content", "graphics")


def resource_labels(language):
    path = ROOT / "android-server/app/src/main/res" / ("values-" + language) / "strings.xml"
    return {node.get("name"): "".join(node.itertext()) for node in ET.parse(path).getroot()
            if node.tag == "string"}


TEXT = {language: resource_labels(language) for language in ("en", "ja", "ko")}


def ui_frame(language, *, landscape=False, selected="console", damage=None, running=False):
    # Independent observed-tree fixture: every app child is inside the app root
    # except the explicitly damaged category used by the clipped-target test.
    width, height = (1200, 600) if landscape else (600, 1000)
    tree = ET.Element("hierarchy")
    app = ET.SubElement(tree, "node", {"package": PACKAGE, "class": "android.widget.LinearLayout",
                                      "bounds": f"[0,0][{width},{height}]", "enabled": "true"})
    text = TEXT[language]
    def node(value, box, *, kind="android.widget.TextView", description=None, selected=False):
        attributes = {"package": PACKAGE, "class": kind, "text": value, "bounds": box,
                      "enabled": "true", "selected": str(selected).lower()}
        if description:
            attributes["content-desc"] = description
        return ET.SubElement(app, "node", attributes)
    node(text["app_name"] + "  0.3.37", "[20,10][580,50]")
    status_key = "status_running" if running else "status_stopped"
    status = TEXT["ko"][status_key] if damage == "wrong-status-" + language else text[status_key]
    node(status, "[180,55][1180,75]" if landscape else "[20,55][580,75]")
    if damage == "wrong-status-" + language:
        # Another translated state label must not mask the Korean global
        # server status in its actual top-of-screen position.
        node(text[status_key], "[180,180][580,198]" if landscape else "[20,285][580,310]")
    start = node(text["start_server"], "[180,80][650,130]" if landscape else "[20,80][280,130]", kind="android.widget.Button")
    start.set("enabled", str(not running).lower())
    if damage != "missing-controls":
        stop = node(text["stop_server"], "[670,80][1180,130]" if landscape else "[300,80][560,130]", kind="android.widget.Button")
        stop.set("enabled", str(running).lower())
    for index, category in enumerate(CATEGORIES):
        if landscape:
            left, top, right, bottom = 10, 80 + index * 60, 150, 130 + index * 60
        else:
            left, top, right, bottom = 10 + index * 115, 140, 110 + index * 115, 190
        if landscape and category == "content":
            if damage == "clipped-nav":
                left, right = width - 20, width + 60
            elif damage == "small-nav":
                bottom = top + 43
        nav = node(text["nav_" + category], f"[{left},{top}][{right},{bottom}]",
                   kind="android.widget.Button", description="idoly.nav." + category,
                   selected=category == selected)
        if landscape and category == "content" and damage == "hidden-nav":
            nav.set("visible-to-user", "false")
    key = "graphics" if selected == "graphics" else "checks"
    panel = node("Panel", "[180,400][580,450]" if landscape else "[20,230][580,280]",
                 kind="android.widget.Button", description="idoly.panel." + key,
                 selected=key == "graphics" and damage != "closed-graphics")
    if damage == "open-checks" and key == "checks":
        panel.set("selected", "true")
    if landscape and damage == "help-dialog":
        ET.SubElement(tree, "node", {"package": "android", "resource-id": "android:id/alertTitle",
                                    "text": "Help", "bounds": "[300,200][900,300]"})
    return tree


class Guest:
    def __init__(self, *, damage=None, sdk="34", density="Physical density: 160\n", running=False):
        self.damage, self.sdk, self.density, self.running = damage, sdk, density, running
        self.language, self.rotation, self.selected = None, 0, "console"
        self.commands, self.captures = [], []

    def adb(self, *arguments, **kwargs):
        arguments = tuple(str(item) for item in arguments)
        self.commands.append((arguments, kwargs))
        if arguments == ("shell", "getprop", "ro.build.version.sdk"):
            return self.sdk
        if arguments == ("shell", "wm", "density"):
            return self.density
        if arguments[:4] == ("shell", "cmd", "locale", "set-app-locales"):
            assert arguments[4:-1] == (PACKAGE, "--user", "0", "--locales")
            assert arguments[-1] in ("en", "ja", "ko")
            self.language, self.selected = arguments[-1], "console"
            return ""
        if arguments[:4] == ("shell", "cmd", "locale", "get-app-locales"):
            assert arguments[4:] == (PACKAGE, "--user", "0")
            locale = "ja" if self.damage == "wrong-readback" else self.language
            return f"Locales for {PACKAGE} for user 0 are [{locale}]\n"
        if arguments == ("shell", "am", "start", "-n", PACKAGE + "/.MainActivity"):
            return "Starting app\n"
        if arguments[:4] == ("shell", "wm", "user-rotation", "lock"):
            assert arguments[4] in ("0", "1") and len(arguments) == 5
            requested = int(arguments[4])
            if self.damage != "failed-portrait-restore" or requested != 0:
                self.rotation = requested
            return ""
        if arguments[:3] == ("shell", "input", "tap"):
            assert len(arguments) == 5
            # Only the actual fixture's observed Graphics/Console centers are
            # accepted. No canned app-state mutation or coordinate fallback.
            point = tuple(map(int, arguments[3:]))
            if point == (80, 345) and self.rotation == 1:
                self.selected = "graphics"
            elif point == (60, 165) and self.rotation == 0:
                self.selected = "console"
            else:
                raise AssertionError("input did not target a fresh visible category")
            return ""
        raise AssertionError("Unexpected OS/private command: " + " ".join(arguments))

    def capture(self, stage):
        self.captures.append(stage)
        language = "ko" if self.damage == "wrong-ui-language" and self.language == "en" else self.language
        landscape = self.rotation == 1 and self.damage != "portrait-during-wide"
        damage = self.damage if landscape or self.damage == "missing-controls" or (self.damage or "").startswith("wrong-status-") else None
        return ui_frame(language, landscape=landscape, selected=self.selected, damage=damage, running=self.running)


@pytest.fixture(autouse=True)
def no_observation_wait(monkeypatch):
    monkeypatch.setattr(probe.time, "sleep", lambda _: None)


def commands(guest, prefix):
    return [(arguments, kwargs) for arguments, kwargs in guest.commands if arguments[:len(prefix)] == prefix]


def test_real_interface_qa_requires_three_resource_languages_and_actual_wide_then_portrait():
    guest = Guest()
    result = probe.exercise_interface_configuration(guest)["actual_os_api_resource_configuration"]
    assert [case["language"] for case in result["languages"]] == ["en", "ja", "ko"]
    for case in result["languages"]:
        language = case["language"]
        assert case["actual_ui_observed"] is True
        assert case["title"] == TEXT[language]["app_name"] + "  0.3.37"
        assert case["start"] == TEXT[language]["start_server"]
        assert case["stop"] == TEXT[language]["stop_server"]
        assert case["status"] == TEXT[language]["status_stopped"]
    assert result["wide"]["console"]["visible_categories"] == result["wide"]["graphics"]["visible_categories"] == 5
    assert result["wide"]["console"]["minimum_navigation_target_dp"] == 50
    assert result["wide"]["console"]["help_closed"] is True
    assert result["wide"]["console"]["default_panel"] == "checks"
    assert result["wide"]["console"]["default_panel_expanded"] is False
    assert result["wide"]["graphics"]["default_panel"] == "graphics"
    assert result["wide"]["graphics"]["default_panel_expanded"] is True
    assert result["restored_portrait"]["console_selected"] is True
    assert result["restored_portrait"]["interface_language"] == "ko"
    assert guest.captures == ["00-interface-en-0", "00-interface-ja-0", "00-interface-ko-0",
                              "00-interface-wide-0", "00-interface-wide-1",
                              "00-interface-portrait-0", "00-interface-portrait-1"]
    assert [arguments[-1] for arguments, _ in commands(guest, ("shell", "cmd", "locale", "set-app-locales"))] == ["en", "ja", "ko"]
    assert [arguments[-1] for arguments, _ in commands(guest, ("shell", "wm", "user-rotation", "lock"))] == ["1", "0"]
    assert [arguments[3:] for arguments, _ in commands(guest, ("shell", "input", "tap"))] == [("80", "345"), ("60", "165")]
    assert commands(guest, ("shell", "wm", "user-rotation", "lock"))[-1][1] == {"check": False}


@pytest.mark.parametrize("sdk", ("30", "32", "unknown"))
def test_unsupported_os_cannot_claim_public_locale_coverage_or_change_the_guest(sdk):
    guest = Guest(sdk=sdk)
    with pytest.raises(RuntimeError, match="API 33 or newer"):
        probe.exercise_interface_configuration(guest)
    assert guest.commands == [(("shell", "getprop", "ro.build.version.sdk"), {})]
    assert guest.captures == []


@pytest.mark.parametrize("damage,stage,error", (
    ("wrong-ui-language", "00-interface-en", "selected language"),
    ("missing-controls", "00-interface-en", "server controls"),
))
def test_wrong_or_incomplete_actual_ui_fails_within_the_original_five_observations(damage, stage, error):
    guest = Guest(damage=damage)
    with pytest.raises(RuntimeError, match=error):
        probe.exercise_interface_configuration(guest)
    assert guest.captures == [stage + "-" + str(index) for index in range(5)]
    assert guest.language == "ko"
    cleanup = commands(guest, ("shell", "cmd", "locale", "set-app-locales"))[-1]
    assert cleanup[0][-1] == "ko" and cleanup[1] == {"check": False}
    assert not commands(guest, ("shell", "wm", "user-rotation", "lock"))

@pytest.mark.parametrize("language", ("en", "ja"))
def test_translated_title_and_buttons_cannot_hide_a_korean_server_status(language):
    frame = ui_frame(language, damage="wrong-status-" + language)
    assert any(node.get("text") == TEXT[language]["app_name"] + "  0.3.37" for node in frame.iter("node"))
    assert any(node.get("text") == TEXT[language]["start_server"] for node in frame.iter("node"))
    assert any(node.get("text") == TEXT["ko"]["status_stopped"] for node in frame.iter("node"))
    guest = Guest(damage="wrong-status-" + language)
    with pytest.raises(RuntimeError, match="status"):
        probe.exercise_interface_configuration(guest)
    preceding = ["00-interface-en-0"] if language == "ja" else []
    assert guest.captures == preceding + ["00-interface-" + language + "-" + str(index) for index in range(5)]
    assert guest.language == "ko"
    cleanup = commands(guest, ("shell", "cmd", "locale", "set-app-locales"))[-1]
    assert cleanup[0][-1] == "ko" and cleanup[1] == {"check": False}
    assert not commands(guest, ("shell", "wm", "user-rotation", "lock"))


def test_os_readback_is_required_before_ui_language_can_be_claimed():
    guest = Guest(damage="wrong-readback")
    with pytest.raises(RuntimeError, match="app-locale configuration did not match"):
        probe.exercise_interface_configuration(guest)
    assert guest.captures == [] and guest.language == "ko"
    assert not commands(guest, ("shell", "am", "start"))
    assert commands(guest, ("shell", "cmd", "locale", "set-app-locales"))[-1][1] == {"check": False}


@pytest.mark.parametrize("damage,error", (
    ("clipped-nav", "clipped"),
    ("small-nav", "smaller than 44 dp"),
    ("hidden-nav", "uniquely visible"),
    ("closed-graphics", "default panel state"),
    ("open-checks", "default panel state"),
    ("help-dialog", "dialog obscures"),
    ("portrait-during-wide", "not landscape"),
))
def test_unusable_wide_layout_is_rejected_and_public_rotation_is_always_restored(damage, error):
    guest = Guest(damage=damage)
    with pytest.raises(RuntimeError, match=error):
        probe.exercise_interface_configuration(guest)
    assert [stage for stage in guest.captures if stage.startswith("00-interface-wide-")] == [
        "00-interface-wide-" + str(index) for index in range(5)]
    assert guest.rotation == 0 and guest.language == "ko"
    assert commands(guest, ("shell", "wm", "user-rotation", "lock"))[-1] == (
        ("shell", "wm", "user-rotation", "lock", "0"), {"check": False})
    assert not any(stage.startswith("00-interface-portrait-") for stage in guest.captures)


def test_portrait_restore_requires_actual_portrait_ui_and_not_only_a_successful_os_command():
    guest = Guest(damage="failed-portrait-restore")
    with pytest.raises(RuntimeError, match="portrait UI was not restored"):
        probe.exercise_interface_configuration(guest)
    assert [stage for stage in guest.captures if stage.startswith("00-interface-portrait-")] == [
        "00-interface-portrait-" + str(index) for index in range(5)]
    assert commands(guest, ("shell", "wm", "user-rotation", "lock"))[-1][0][-1] == "0"
    assert guest.language == "ko"


def test_navigation_target_size_uses_the_actual_public_density_override():
    guest = Guest(density="Physical density: 320\nOverride density: 160\n")
    assert probe.density_dpi(guest) == 160
    proof = probe.wide_proof(ui_frame("ko", landscape=True), 160, graphics=False)
    assert proof["minimum_navigation_target_dp"] == 50
    with pytest.raises(RuntimeError, match="smaller than 44 dp"):
        probe.wide_proof(ui_frame("ko", landscape=True), 320, graphics=False)


def test_exact_44_dp_targets_pass_but_fractionally_smaller_targets_do_not():
    exact = ui_frame("ko", landscape=True)
    for nav in exact.iter("node"):
        if nav.get("content-desc", "").startswith("idoly.nav."):
            left, top, right, _ = probe.bounds(nav)
            nav.set("bounds", f"[{left},{top}][{right},{top + 44}]")
    assert probe.wide_proof(exact, 160, graphics=False)["minimum_navigation_target_dp"] == 44
    # Fifty pixels at 183 dpi is 43.72 dp. Rounding or a relaxed 43.5 dp
    # threshold must not classify it as an actual 44 dp touch target.
    with pytest.raises(RuntimeError, match="smaller than 44 dp"):
        probe.wide_proof(ui_frame("ko", landscape=True), 183, graphics=False)



@pytest.mark.parametrize("area", ("[20,40][580,60]", "[20,135][580,155]"))
def test_global_status_must_occupy_the_actual_region_between_title_and_controls(area):
    frame = ui_frame("en")
    textviews = [node for node in frame.iter("node") if node.get("package") == PACKAGE
                 and node.get("class") == "android.widget.TextView"]
    textviews[1].set("bounds", area)
    with pytest.raises(RuntimeError, match="top status"):
        probe.language_proof(frame, probe.labels("en"))


def test_already_running_server_changes_all_three_interface_languages_without_service_lifecycle_commands():
    guest = Guest(running=True)
    result = probe.exercise_running_interface_languages(guest)
    assert [case["language"] for case in result] == ["en", "ja", "ko"]
    for case in result:
        language = case["language"]
        assert set(case) == {"language", "title", "start", "stop", "status", "actual_ui_observed"}
        assert case["actual_ui_observed"] is True
        assert case["title"] == TEXT[language]["app_name"] + "  0.3.37"
        assert case["start"] == TEXT[language]["start_server"]
        assert case["stop"] == TEXT[language]["stop_server"]
        assert case["status"] == TEXT[language]["status_running"]
    assert guest.captures == ["02-interface-running-en-0", "02-interface-running-ja-0", "02-interface-running-ko-0"]
    assert guest.running is True and guest.language == "ko"
    assert [arguments[-1] for arguments, _ in commands(guest, ("shell", "cmd", "locale", "set-app-locales"))] == ["en", "ja", "ko"]
    assert len(commands(guest, ("shell", "cmd", "locale", "get-app-locales"))) == 3
    assert len(commands(guest, ("shell", "am", "start", "-n", PACKAGE + "/.MainActivity"))) == 3
    # The existing running service must survive locale configuration. Only the
    # official locale preference and foreground-Activity commands are allowed.
    assert all(arguments[:3] in (("shell", "cmd", "locale"), ("shell", "am", "start"))
               for arguments, _ in guest.commands)


@pytest.mark.parametrize("language", ("en", "ja"))
def test_already_running_korean_status_cannot_hide_under_translated_controls(language):
    frame = ui_frame(language, running=True, damage="wrong-status-" + language)
    textviews = [node for node in frame.iter("node") if node.get("package") == PACKAGE
                 and node.get("class") == "android.widget.TextView"]
    assert textviews[1].get("text") == TEXT["ko"]["status_running"]
    assert any(node.get("text") == TEXT[language]["status_running"] for node in textviews[2:])
    guest = Guest(running=True, damage="wrong-status-" + language)
    with pytest.raises(RuntimeError, match="status"):
        probe.exercise_running_interface_languages(guest)
    preceding = ["02-interface-running-en-0"] if language == "ja" else []
    assert guest.captures == preceding + ["02-interface-running-" + language + "-" + str(index) for index in range(5)]
    assert guest.running is True and guest.language == "ko"
    cleanup = commands(guest, ("shell", "cmd", "locale", "set-app-locales"))[-1]
    assert cleanup[0][-1] == "ko" and cleanup[1] == {"check": False}
    assert all(arguments[:3] in (("shell", "cmd", "locale"), ("shell", "am", "start"))
               for arguments, _ in guest.commands)
