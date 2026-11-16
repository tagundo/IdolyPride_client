"""Synthetic host checks for actual Native event QA fail-closed observations."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import pytest

DIRECTORY = Path(__file__).parent
ACCOUNT_SPEC = importlib.util.spec_from_file_location("qa_account_management", DIRECTORY / "qa_account_management.py")
account = importlib.util.module_from_spec(ACCOUNT_SPEC)
ACCOUNT_SPEC.loader.exec_module(account)
sys.modules.setdefault("qa_account_management", account)
SPEC = importlib.util.spec_from_file_location("native_event_qa", DIRECTORY / "qa_event_settings.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def settings(revision=1):
    now = int(probe.time.time()*1000)
    return {"schema": 1, "saved": {"schema": 1, "revision": revision, "love_events": [
        {"event_id": "love-23-0514", "start_time_ms": now, "end_time_ms": now+30*probe.DAY}]}}


def home(entry):
    return SimpleNamespace(DESCRIPTOR=SimpleNamespace(fields_by_name={"eventInfo": object()}),
        eventInfo=SimpleNamespace(loveEventInfos=[SimpleNamespace(id=entry["event_id"],
            startTime=entry["start_time_ms"], endTime=entry["end_time_ms"])]))


@pytest.mark.parametrize("revision", [1, 1794835740000])
def test_saved_observation_requires_exact_cas_event_and_local_duration(revision):
    observed = settings(revision)
    entry = probe.assert_enabled(observed, "love-23-0514", 0)
    assert entry is observed["saved"]["love_events"][0]
    for damage in ("revision", "identity", "duration", "stale-period"):
        changed = copy.deepcopy(observed)
        if damage == "revision": changed["saved"]["revision"] = True
        elif damage == "identity": changed["saved"]["love_events"][0]["event_id"] = "unobserved"
        elif damage == "duration": changed["saved"]["love_events"][0]["end_time_ms"] += 1
        else:
            changed["saved"]["love_events"][0]["start_time_ms"] -= 3600000
            changed["saved"]["love_events"][0]["end_time_ms"] -= 3600000
        with pytest.raises(RuntimeError): probe.assert_enabled(changed, "love-23-0514", 0)


def test_actual_home_projection_requires_exact_id_and_period():
    entry = settings()["saved"]["love_events"][0]
    probe.assert_home_event(home(entry), entry)
    for field in ("id", "startTime", "endTime"):
        changed = home(entry)
        setattr(changed.eventInfo.loveEventInfos[0], field, "wrong" if field == "id" else 0)
        with pytest.raises(RuntimeError, match="encrypted Home"):
            probe.assert_home_event(changed, entry)


@pytest.mark.parametrize("save_revision,disable_revision", [(1, 2), (1794835740000, 1794835741000),
                                                           (1794835741000, 1794835741001)])
@pytest.mark.parametrize("damage", [None, "frozen", "progress", "home", "saved-file"])
def test_native_flow_gates_follow_observed_save_restart_rpc_and_progress(monkeypatch, damage, save_revision, disable_revision):
    base = {"schema": 1, "revision": 0, "love_events": []}
    model = {"saved": copy.deepcopy(base), "effective": None, "starts": 0, "calls": [], "selected": "sandbox"}
    owned = {table: () for table in account.TABLES}
    owned["profiles"] = (("@slot", "synthetic-server"),)
    owned["snapshots"] = (("@slot", b"unchanged snapshot"),)
    def snapshot(guest, copier, profile):
        value = copy.deepcopy(owned)
        if damage == "progress" and model["saved"]["revision"] == disable_revision:
            value["profile_love_progress"] = (("changed",),)
        return value
    def runtime(port):
        effective = copy.deepcopy(model["effective"])
        if damage == "frozen" and model["saved"]["revision"] == save_revision and model["starts"] == 1:
            effective = copy.deepcopy(model["saved"])
        return ({"running": True, "profile": probe.CREATE}, {"schema": 1,
            "saved": copy.deepcopy(model["saved"]), "effective": effective,
            "restart_required": effective != model["saved"], "catalog": {"available": True,
                "events": [{"id": "love-23-0514", "title": "Synthetic", "supported": True}], "ruleset_sha256": "a"*64}})
    class Guest:
        def adb(self, *arguments, **kwargs):
            model["calls"].append(("adb", arguments))
            if arguments[:4] == ("exec-out", "run-as", probe.PACKAGE, "cat"):
                value = model["saved"] if damage != "saved-file" else base
                return json.dumps(value).encode()
            return ""
        def tap(self, text, stage):
            model["calls"].append(("native", text, stage))
            if text == "서버 시작":
                model["starts"] += 1
                model["effective"] = copy.deepcopy(model["saved"])
        def capture(self, stage): model["calls"].append(("capture", stage))
    guest = Guest()
    def find(guest, predicate, stage, direction=None, **kwargs):
        model["calls"].append(("find", stage))
        return ET.fromstring('<node checked="false" content-desc="'+("idoly.events.disable-all" if stage == "87-event-disable" else "idoly.events.enabled")+'"/>')
    def enable(guest, node):
        if node.get("content-desc") == "idoly.events.disable-all":
            model["calls"].append(("native-description", "idoly.events.disable-all"))
            model["saved"] = dict(copy.deepcopy(base), revision=disable_revision)
        else:
            model["calls"].append(("native-checkbox",))
            model["saved"] = settings(save_revision)["saved"]
    def tap(guest, description, stage, direction=None):
        model["calls"].append(("native-description", description))
        if description == "idoly.events.disable-all":
            model["saved"] = dict(copy.deepcopy(base), revision=disable_revision)
    def select(guest, profile, *args):
        model["selected"] = profile
        model["calls"].append(("select", profile))
    def rpc(schema, port, method, token):
        model["calls"].append(("encrypted-rpc", method, token))
        entry = copy.deepcopy(model["effective"]["love_events"][0])
        if damage == "home": entry["end_time_ms"] += 1
        return home(entry)
    monkeypatch.setattr(probe, "projection", snapshot)
    monkeypatch.setattr(probe, "runtime_settings", runtime)
    monkeypatch.setattr(probe, "find", find)
    monkeypatch.setattr(probe, "tap_node", enable)
    monkeypatch.setattr(probe, "tap", tap)
    monkeypatch.setattr(probe, "select_profile", select)
    arguments = (guest, object(), 50051, 8080, 600)
    options = dict(wait_server=lambda *a, **k: None, bootstrap=lambda *a: (None, SimpleNamespace(gameAuthToken=b"synthetic-token")),
                   rpc=rpc, copy_database=object())
    if damage is not None:
        with pytest.raises(RuntimeError): probe.exercise_event_settings(*arguments, **options)
        return
    report = probe.exercise_event_settings(*arguments, **options)
    assert report["native_event_settings_autosave"] is True and report["native_event_settings_restart_preserved"] is True
    detail = report["native_event_settings"]
    assert detail["home_event_verified"] is True and detail["progress_preserved"] is True
    assert detail["gameplay_tested"] is False and detail["physical_device_tested"] is False
    assert model["starts"] == 2 and model["selected"] == "sandbox"
    assert model["saved"]["love_events"] == [] and model["saved"]["revision"] == disable_revision
    assert ("encrypted-rpc", "/api.Home/Enter", b"synthetic-token") in model["calls"]
    assert model["calls"].index(("native-checkbox",)) < model["calls"].index(("native", "서버 시작", "86-event-restart"))


class NavigationGuest:
    def __init__(self, trees):
        self.trees, self.actions, self.captures = list(trees), [], []
    def capture(self, stage):
        self.captures.append(stage)
        return ET.fromstring(self.trees.pop(0))
    def adb(self, *args):
        self.actions.append(args)
        return ""


def target_xml(description="idoly.events.catalog", *, enabled="true"):
    return '<hierarchy><node class="android.widget.ScrollView" scrollable="true" bounds="[44,707][1036,2126]"><node content-desc="'+description+'" enabled="'+enabled+'" bounds="[88,900][992,1032]"/></node></hierarchy>'


def viewport_xml(description="", text=""):
    return '<hierarchy><node class="android.widget.ScrollView" scrollable="true" bounds="[44,707][1036,2126]"><node content-desc="'+description+'" text="'+text+'" bounds="[88,900][992,1032]"/></node></hierarchy>'


def test_captured_actual_resource_viewport_navigates_up_toward_event_card(monkeypatch):
    monkeypatch.setattr(account.time, "sleep", lambda _: None)
    actual = (DIRECTORY / "fixtures/event-catalog-below-3bf.xml").read_text()
    guest = NavigationGuest([actual, target_xml()])
    node = probe.find_event_control(guest, "idoly.events.catalog", "lower")
    assert node.get("enabled") == "true"
    assert guest.actions == [("shell", "input", "swipe", "540", "1062", "540", "1771", "975")]
    assert guest.captures == ["lower-0", "lower-1"]


def test_above_account_section_navigates_down_and_visible_target_never_scrolls(monkeypatch):
    monkeypatch.setattr(account.time, "sleep", lambda _: None)
    guest = NavigationGuest([viewport_xml("idoly.accounts.create"), target_xml()])
    probe.find_event_control(guest, "idoly.events.catalog", "upper")
    assert guest.actions == [("shell", "input", "swipe", "540", "1771", "540", "1062", "975")]
    visible = NavigationGuest([target_xml()])
    probe.find_event_control(visible, "idoly.events.catalog", "visible")
    assert visible.actions == [] and visible.captures == ["visible-0"]


@pytest.mark.parametrize("visible,wanted,direction", [
    ("idoly.events.status", "idoly.events.catalog", "down"),
    ("idoly.events.end", "idoly.events.catalog", "up"),
    ("idoly.events.end", "idoly.events.disable-all", "down")])
def test_partial_event_card_uses_its_known_control_order(visible, wanted, direction):
    decide = probe.event_navigation(wanted)
    assert decide(ET.fromstring(viewport_xml(visible))) == direction


def test_anchored_direction_continues_through_intermediate_unlabelled_controls(monkeypatch):
    monkeypatch.setattr(account.time, "sleep", lambda _: None)
    actual = (DIRECTORY / "fixtures/event-catalog-below-3bf.xml").read_text()
    guest = NavigationGuest([actual, viewport_xml(text="4096"), target_xml()])
    probe.find_event_control(guest, "idoly.events.catalog", "intermediate")
    assert len(guest.actions) == 2 and all(int(action[4]) < int(action[6]) for action in guest.actions)


def test_repeated_lower_bottom_still_fails_with_the_original_16_observation_budget(monkeypatch):
    monkeypatch.setattr(account.time, "sleep", lambda _: None)
    actual = (DIRECTORY / "fixtures/event-catalog-below-3bf.xml").read_text()
    guest = NavigationGuest([actual]*16)
    with pytest.raises(RuntimeError, match="not observed enabled"):
        probe.find_event_control(guest, "idoly.events.catalog", "unchanged-bottom")
    assert len(guest.captures) == 16 and len(guest.actions) == 16
    assert all(action[:3] == ("shell", "input", "swipe") and int(action[4]) < int(action[6]) for action in guest.actions)


def test_disabled_catalog_is_never_enabled_skipped_or_scrolled_past(monkeypatch):
    monkeypatch.setattr(account.time, "sleep", lambda _: None)
    guest = NavigationGuest([target_xml(enabled="false")]*16)
    with pytest.raises(RuntimeError, match="not observed enabled"):
        probe.find_event_control(guest, "idoly.events.catalog", "disabled")
    assert len(guest.captures) == 16 and guest.actions == []


def test_unknown_viewport_fails_without_an_unobserved_navigation_input(monkeypatch):
    monkeypatch.setattr(account.time, "sleep", lambda _: None)
    guest = NavigationGuest([viewport_xml()])
    with pytest.raises(RuntimeError, match="cannot determine"):
        probe.find_event_control(guest, "idoly.events.catalog", "unrecognized")
    assert guest.actions == []


def test_overshoot_reverses_direction_from_each_fresh_section_anchor(monkeypatch):
    monkeypatch.setattr(account.time, "sleep", lambda _: None)
    actual = (DIRECTORY / "fixtures/event-catalog-below-3bf.xml").read_text()
    guest = NavigationGuest([actual, viewport_xml("idoly.accounts.create"), target_xml()])
    probe.find_event_control(guest, "idoly.events.catalog", "overshoot")
    assert len(guest.captures) == 3 and len(guest.actions) == 2
    assert int(guest.actions[0][4]) < int(guest.actions[0][6])
    assert int(guest.actions[1][4]) > int(guest.actions[1][6])


def test_offscreen_or_hidden_event_node_cannot_count_as_a_visible_target_or_anchor(monkeypatch):
    monkeypatch.setattr(account.time, "sleep", lambda _: None)
    actual = ET.fromstring((DIRECTORY / "fixtures/event-catalog-below-3bf.xml").read_text())
    area = next(node for node in actual.iter("node") if node.get("class") == "android.widget.ScrollView")
    ET.SubElement(area, "node", {"content-desc": "idoly.events.catalog", "enabled": "true", "bounds": "[88,2200][992,2332]"})
    ET.SubElement(area, "node", {"content-desc": "idoly.accounts.create", "enabled": "true", "bounds": "[44,116][1036,208]"})
    hidden = ET.SubElement(area, "node", {"content-desc": "idoly.events.status", "visible-to-user": "false", "bounds": "[88,900][992,1032]"})
    assert probe.event_visible(hidden, actual) is False
    guest = NavigationGuest([ET.tostring(actual, encoding="unicode"), target_xml()])
    node = probe.find_event_control(guest, "idoly.events.catalog", "offscreen")
    assert node.get("bounds") == "[88,900][992,1032]" and len(guest.actions) == 1
    assert int(guest.actions[0][4]) < int(guest.actions[0][6])


def test_missing_required_control_between_visible_event_positions_is_a_hard_failure(monkeypatch):
    monkeypatch.setattr(account.time, "sleep", lambda _: None)
    tree = ET.fromstring(viewport_xml("idoly.events.status"))
    area = next(node for node in tree.iter("node") if node.get("class") == "android.widget.ScrollView")
    ET.SubElement(area, "node", {"content-desc": "idoly.events.end", "bounds": "[88,1100][992,1232]"})
    guest = NavigationGuest([ET.tostring(tree, encoding="unicode")])
    with pytest.raises(RuntimeError, match="missing within"):
        probe.find_event_control(guest, "idoly.events.catalog", "missing-control")
    assert guest.actions == []


def test_partial_overlap_with_click_center_outside_is_not_a_visible_event_target(monkeypatch):
    monkeypatch.setattr(account.time, "sleep", lambda _: None)
    actual = ET.fromstring((DIRECTORY / "fixtures/event-catalog-below-3bf.xml").read_text())
    area = next(node for node in actual.iter("node") if node.get("class") == "android.widget.ScrollView")
    clipped = ET.SubElement(area, "node", {"content-desc": "idoly.events.catalog", "enabled": "true", "bounds": "[88,2100][992,2232]"})
    assert probe.event_visible(clipped, actual) is False
    guest = NavigationGuest([ET.tostring(actual, encoding="unicode"), target_xml()])
    found = probe.find_event_control(guest, "idoly.events.catalog", "clipped-center")
    assert found.get("bounds") == "[88,900][992,1032]"
    assert len(guest.actions) == 1 and guest.actions[0][:3] == ("shell", "input", "swipe")


def test_partially_clipped_control_remains_usable_when_observed_click_center_is_inside():
    tree = ET.fromstring(viewport_xml())
    area = next(node for node in tree.iter("node") if node.get("class") == "android.widget.ScrollView")
    node = ET.SubElement(area, "node", {"content-desc": "idoly.events.enabled", "bounds": "[88,2060][992,2150]"})
    assert probe.event_visible(node, tree) is True
    node.set("bounds", "[1000,900][1100,1000]")
    assert probe.event_visible(node, tree) is False
    node.set("bounds", "[1000,900][1060,1000]")
    assert probe.event_visible(node, tree) is True


@pytest.mark.parametrize("phase", [0, 1, 354, 708])
def test_half_viewport_event_navigation_covers_long_content_without_skipping_target(monkeypatch, phase):
    """A 10kpx synthetic path exceeds the observed failed run's 7014px travel.

    Use the actual 1419px viewport, a 132px control, and several target positions
    across one whole 709px step. This is host navigation coverage, not Native QA.
    """
    monkeypatch.setattr(account.time, "sleep", lambda _: None)
    class LongContentGuest:
        def __init__(self):
            self.offset, self.actions, self.captures = 10000+phase, [], []
        def capture(self, stage):
            self.captures.append(stage)
            center = 1416-self.offset
            if 66 <= center < 2300:
                return ET.fromstring(target_xml().replace("[88,900][992,1032]",
                    "[88,"+str(center-66)+"][992,"+str(center+66)+"]"))
            return ET.fromstring(viewport_xml(text="그래픽·촬영 화면 ▴"))
        def adb(self, *args):
            self.actions.append(args)
            self.offset -= int(args[6])-int(args[4])
            return ""
    guest = LongContentGuest()
    node = probe.find_event_control(guest, "idoly.events.catalog", "long-content")
    assert probe.event_visible(node, ET.fromstring(viewport_xml()))
    assert 1 < len(guest.captures) <= 16 and len(guest.actions) == len(guest.captures)-1
    assert all(action == ("shell", "input", "swipe", "540", "1062", "540", "1771", "975")
               for action in guest.actions)
    # Overlap is larger than a whole control and covers every intermediate center.
    assert 1419-709 == 710 and 710 > 132
    # 709px / 975ms preserves the previously observed 473px / 650ms speed.
    assert abs(709/975 - 473/650) < .001
    default_guest = LongContentGuest()
    with pytest.raises(RuntimeError, match="not observed enabled"):
        account.find(default_guest, lambda n: n.get("content-desc") == "idoly.events.catalog",
                     "long-default", probe.event_navigation("idoly.events.catalog"), node_filter=probe.event_visible)
    assert len(default_guest.captures) == 16 and len(default_guest.actions) == 16
    assert all(action == ("shell", "input", "swipe", "540", "1180", "540", "1653", "650")
               for action in default_guest.actions)


def test_unknown_scroll_profile_fails_before_any_capture_or_input():
    guest = NavigationGuest([])
    with pytest.raises(ValueError, match="scroll profile"):
        account.find(guest, lambda _: False, "unknown-profile", "up", scroll_profile="unobserved")
    assert guest.captures == [] and guest.actions == []


@pytest.mark.parametrize("previous,revision,expected", [
    (0, 1, True), (0, 1794835740000, True),
    (1794835740000, 1794835741000, True), (100, (1 << 53)-1, True),
    # A backward clock uses current+1, so the CAS token still advances safely.
    (1794835741000, 1794835741001, True),
    (100, 100, False), (100, 99, False), (100, -1, False),
    (0, True, False), (0, 1.0, False), (0, "101", False),
    (0, (1 << 53), False), (True, 101, False), (-1, 101, False)])
def test_cas_revision_observation_requires_typed_safe_strict_advance(previous, revision, expected):
    assert probe.revision_advanced({"revision": revision}, previous) is expected


def test_saved_event_with_unchanged_or_stale_revision_is_rejected():
    observed = settings(1794835740000)
    for previous in (1794835740000, 1794835740001):
        with pytest.raises(RuntimeError, match="CAS"):
            probe.assert_enabled(observed, "love-23-0514", previous)
