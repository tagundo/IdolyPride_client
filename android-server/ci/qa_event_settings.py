"""Actual native event autosave/restart on a verified disposable emulator.

Uses a fresh synthetic account without the portability canary; no Love gameplay,
reward, reset, production credentials or physical game client is exercised.
"""
from __future__ import annotations
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import time
from urllib.request import urlopen
from qa_account_management import (ACTIVITY, PACKAGE, CREATE, find, tap, tap_node,
                                    select_profile, projection, bounds)

DAY = 24 * 60 * 60 * 1000
SCOPE = "Android emulator native event settings and encrypted Home RPC"


_EVENT_ORDER = {"idoly.events."+name: index for index, name in enumerate(
    ("status", "catalog", "enabled", "start", "end", "applied", "reload", "disable-all"))}
_BELOW_KEYS = {"library_settings_title", "experiment_section_title", "presentation_title_expanded",
               "presentation_render_scale", "presentation_max_buffer_pixel", "playback_section_title",
               "resources_section_title", "library_resources_title", "diagnostics_section_title",
               "library_resource_platform", "library_download_all", "library_import", "library_export", "export_diagnostics"}


def event_viewport(tree):
    regions = [bounds(node) for node in tree.iter("node")
               if "ScrollView" in node.get("class", "") and bounds(node)]
    if not regions:
        raise RuntimeError("Event QA requires the observed settings viewport")
    return max(regions, key=lambda area: (area[2]-area[0])*(area[3]-area[1]))


def event_visible(node, tree):
    area = bounds(node)
    if area is None or node.get("visible-to-user") == "false":
        return False
    viewport = event_viewport(tree)
    center_x, center_y = (area[0]+area[2])//2, (area[1]+area[3])//2
    return (max(area[0], viewport[0]) < min(area[2], viewport[2])
            and max(area[1], viewport[1]) < min(area[3], viewport[3])
            and viewport[0] <= center_x < viewport[2] and viewport[1] <= center_y < viewport[3])


def event_navigation(description):
    """Navigate toward the event card from fresh anchors, within find's same budget."""
    if description not in _EVENT_ORDER:
        raise RuntimeError("Event QA control has no known section order")
    root = Path(__file__).resolve().parents[1] / "app/src/main/res"
    below = set()
    for locale in ("values", "values-en", "values-ja"):
        for row in ET.parse(root / locale / "strings.xml").getroot():
            if row.attrib.get("name") in _BELOW_KEYS and row.text:
                below.add(row.text)
    previous = None
    def observed(tree):
        nonlocal previous
        nodes = [node for node in tree.iter("node") if event_visible(node, tree)]
        positions = [_EVENT_ORDER[node.get("content-desc")] for node in nodes if node.get("content-desc") in _EVENT_ORDER]
        wanted = _EVENT_ORDER[description]
        if positions:
            if all(value < wanted for value in positions): previous = "down"
            elif all(value > wanted for value in positions): previous = "up"
            else: raise RuntimeError("Event QA control is missing within its observed section")
        else:
            lower = any(node.get("text") in below for node in nodes)
            upper = any(node.get("content-desc", "").startswith(("idoly.accounts.", "idoly.official.")) for node in nodes)
            if lower and upper: raise RuntimeError("Event QA section anchors disagree")
            if lower: previous = "up"
            elif upper: previous = "down"
        if previous is None:
            raise RuntimeError("Event QA cannot determine the current settings section")
        return previous
    return observed


def find_event_control(qa, description, stage):
    return find(qa, lambda node: node.get("content-desc") == description,
                stage, event_navigation(description), node_filter=event_visible)


def runtime_settings(asset_port):
    with urlopen("http://127.0.0.1:" + str(asset_port) + "/diagnostics/runtime", timeout=10) as response:
        raw = response.read(2*1024*1024+1)
    if len(raw) > 2*1024*1024:
        raise RuntimeError("Native event QA runtime observation exceeded its bound")
    runtime = json.loads(raw)["runtime"]
    settings = runtime.get("event_settings")
    if runtime.get("running") is not True or type(settings) is not dict:
        raise RuntimeError("Native event QA expected current running event settings")
    return runtime, settings


def await_saved(asset_port, predicate):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        runtime, settings = runtime_settings(asset_port)
        if predicate(settings):
            return runtime, settings
        time.sleep(.25)
    raise RuntimeError("Native event QA autosave did not reach the required saved/effective state")


def assert_enabled(settings, event_id, previous_revision):
    saved = settings.get("saved", {})
    entries = saved.get("love_events", [])
    if (saved.get("schema") != 1 or type(saved.get("revision")) is not int
            or saved["revision"] != previous_revision+1 or len(entries) != 1
            or entries[0].get("event_id") != event_id):
        raise RuntimeError("Native event checkbox did not save exactly the supported chosen event with CAS")
    entry = entries[0]
    if (type(entry.get("start_time_ms")) is not int or type(entry.get("end_time_ms")) is not int
            or entry["end_time_ms"]-entry["start_time_ms"] != 30*DAY
            or abs(entry["start_time_ms"]-int(time.time()*1000)) > 120000):
        raise RuntimeError("Native event checkbox did not use the explicit local thirty-day period")
    return entry


def assert_home_event(home, entry):
    if "eventInfo" not in home.DESCRIPTOR.fields_by_name:
        raise RuntimeError("Actual encrypted Home response has no eventInfo field")
    rows = list(home.eventInfo.loveEventInfos)
    if (len(rows) != 1 or rows[0].id != entry["event_id"]
            or rows[0].startTime != entry["start_time_ms"] or rows[0].endTime != entry["end_time_ms"]):
        raise RuntimeError("Actual encrypted Home response did not expose the selected local Love period")


def exercise_event_settings(qa, schema, grpc_port, asset_port, startup_timeout, *,
                            wait_server, bootstrap, rpc, copy_database):
    qa.adb("shell", "am", "force-stop", PACKAGE)
    before = projection(qa, copy_database, CREATE)
    if before["profile_love_progress"]:
        raise RuntimeError("Native event QA requires the fresh no-progress synthetic slot")
    qa.adb("shell", "am", "start", "-n", ACTIVITY)
    select_profile(qa, CREATE, "81-event-test-account", "down")
    tap(qa, "idoly.accounts.select", "81-event-queue-account", "down")
    find(qa, lambda n: n.get("content-desc") == "idoly.accounts.select", "81-event-account-queued")
    qa.tap("서버 시작", "82-event-baseline-start")
    wait_server(schema, grpc_port, timeout=startup_timeout)
    baseline_runtime, baseline = runtime_settings(asset_port)
    if (baseline_runtime.get("profile") != CREATE or baseline.get("saved", {}).get("love_events") != []
            or baseline.get("effective", {}).get("love_events") != []):
        raise RuntimeError("Native event QA requires a fresh disabled event selection")
    catalog = baseline["catalog"]
    supported = [row for row in catalog.get("events", []) if row.get("supported") is True]
    if catalog.get("available") is not True or not supported:
        raise RuntimeError("Native event QA did not receive the data-backed supported catalog")
    chosen = supported[0]
    # The supported-only native spinner starts with its first observed entry.
    find_event_control(qa, "idoly.events.catalog", "83-event-catalog")
    control = find_event_control(qa, "idoly.events.enabled", "83-event-enable")
    if control.get("checked") != "false":
        raise RuntimeError("Native event checkbox was unexpectedly already enabled")
    revision = baseline["saved"]["revision"]
    tap_node(qa, control)
    active, observed = await_saved(asset_port, lambda s: s.get("saved", {}).get("revision") == revision+1)
    entry = assert_enabled(observed, chosen["id"], revision)
    if (active.get("profile") != CREATE or observed.get("effective") != baseline["effective"]
            or observed.get("restart_required") is not True):
        raise RuntimeError("Native event autosave restarted the current server or changed frozen effective settings")
    raw = qa.adb("exec-out", "run-as", PACKAGE, "cat", "files/data/server-events.json", binary=True)
    if len(raw) > 32768 or json.loads(raw) != observed["saved"]:
        raise RuntimeError("Native event saved file did not match the CAS observation")
    qa.capture("84-event-autosaved-restart-required")
    qa.tap("서버 중지", "85-event-stop-before-restart")
    wait_server(schema, grpc_port, expected=False, timeout=30)
    qa.adb("shell", "am", "force-stop", PACKAGE)
    if projection(qa, copy_database, CREATE) != before:
        raise RuntimeError("Native event settings autosave changed account progress")
    qa.adb("shell", "am", "start", "-n", ACTIVITY)
    qa.tap("서버 시작", "86-event-restart")
    wait_server(schema, grpc_port, timeout=startup_timeout)
    restarted, effective = runtime_settings(asset_port)
    if (restarted.get("profile") != CREATE or effective.get("saved") != observed["saved"]
            or effective.get("effective") != observed["saved"] or effective.get("restart_required") is not False):
        raise RuntimeError("Native event settings or queued account did not persist across the actual restart")
    _, login = bootstrap(schema, grpc_port)
    assert_home_event(rpc(schema, grpc_port, "/api.Home/Enter", login.gameAuthToken), entry)
    # Turning the setting off removes the schedule, preserving stored progress.
    tap_node(qa, find_event_control(qa, "idoly.events.disable-all", "87-event-disable"))
    _, disabled = await_saved(asset_port, lambda s: s.get("saved", {}).get("love_events") == [])
    if (disabled.get("effective") != effective["effective"] or disabled.get("restart_required") is not True
            or disabled.get("saved", {}).get("revision") != observed["saved"]["revision"]+1):
        raise RuntimeError("Native event disable changed the running frozen event selection")
    qa.tap("서버 중지", "88-event-stop")
    wait_server(schema, grpc_port, expected=False, timeout=30)
    qa.adb("shell", "am", "force-stop", PACKAGE)
    if projection(qa, copy_database, CREATE) != before:
        raise RuntimeError("Native event enable, Home read or disable changed stored account progress")
    qa.adb("shell", "am", "start", "-n", ACTIVITY)
    select_profile(qa, "sandbox", "89-event-restore-original", "down")
    tap(qa, "idoly.accounts.select", "89-event-queue-original", "down")
    find(qa, lambda n: "다음 시작 · 일반 sandbox" in n.get("text", ""),
         "89-event-original-queued", "down", enabled=False)
    qa.capture("89-native-event-settings-complete")
    return {"native_event_settings_autosave": True, "native_event_settings_restart_preserved": True,
            "native_event_settings": {"scope": SCOPE, "event_id": entry["event_id"],
                "settings_revision": observed["saved"]["revision"],
                "start_time_ms": entry["start_time_ms"], "end_time_ms": entry["end_time_ms"],
                "ruleset_sha256": catalog["ruleset_sha256"], "saved_file_verified": True,
                "effective_match": True, "home_event_verified": True, "progress_preserved": True,
                "selection_restored": True, "physical_device_tested": False, "gameplay_tested": False}}
