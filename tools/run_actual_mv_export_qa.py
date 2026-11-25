#!/usr/bin/env python3
"""Export a normal playing 3D MV and validate its real output and restoration.

This never creates synthetic video or invokes gameplay/button delegates. Every
functional verdict is separate from successful evidence collection. The only
HTTP calls are authenticated read-only observations in an emulator-only addon.
Only the explicit QA-only --prepare-completed-opening option adds local server
RPCs: qa_game_boot's setup-only completed-opening profile, before Launch.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
from http.client import HTTPConnection, HTTPException
import importlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "game.qualiarts.idolypride.local.diagnostics"
MAIN = PACKAGE + "/game.qualiarts.idolypride.localserver.MainActivity"
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
HEX32 = re.compile(r"[0-9a-f]{32}")
MAX_JSON = 72 * 1024
MAX_MOVIE = 24 * 1024 * 1024
ENVIRONMENT_PROBE = "org.idolypride.environmentprobe"
PERMISSION_CONTROLLERS = frozenset(("com.android.permissioncontroller", "com.google.android.permissioncontroller"))
PERMISSION_ACTIVITY = "com.android.permissioncontroller.permission.ui.GrantPermissionsActivity"
NOTIFICATION_PERMISSION = "android.permission.POST_NOTIFICATIONS"
DOCUMENTSUI_PACKAGES = ("com.google.android.documentsui", "com.android.documentsui")
MAX_DIAGNOSTICS = 64 * 1024
TRANSLATED_GUEST, REDROID_GUEST = "translated-emulator", "redroid"
# The default guest keeps the official translated emulator contract unchanged.
# redroid is a separate, explicitly selected native ARM64 container whose
# results are never presented as emulator or physical-phone evidence.
GUESTS = {
    TRANSLATED_GUEST: {"serial": r"emulator-[0-9]+", "serial_code": "disposable_emulator_serial_required",
                       "scope": "actual_game_in_official_translated_guest",
                       "status": "PASS_ACTUAL_MV_EXPORT_TRANSLATED_GUEST_ONLY", "install_timeout": 180},
    # adb TCP transport bound to the runner's own loopback only; never a LAN device.
    REDROID_GUEST: {"serial": r"(?:127\.0\.0\.1|localhost):[0-9]{2,5}",
                    "serial_code": "disposable_redroid_loopback_serial_required",
                    "scope": "actual_game_in_redroid_native_arm64_container",
                    "status": "PASS_ACTUAL_MV_EXPORT_REDROID_ARM64_ONLY", "install_timeout": 600},
}
REDROID_DEVICES = frozenset(("redroid_arm64", "redroid_arm64_only"))
REDROID_PROPERTIES = ("ro.hardware", "ro.boot.hardware", "ro.product.device", "ro.product.cpu.abi",
    "ro.product.cpu.abilist", "ro.dalvik.vm.native.bridge", "ro.kernel.qemu", "ro.boot.qemu",
    "ro.build.version.sdk", "ro.build.version.incremental", "ro.build.fingerprint", "ro.build.type",
    "ro.hardware.egl", "ro.hardware.vulkan", "ro.hardware.gralloc", "ro.boot.redroid_gpu_mode",
    "ro.opengles.version", "debug.stagefright.ccodec", "sys.use_memfd")
SAVE_BLOCKED_DOCUMENTSUI = "save_blocked_documentsui_unavailable"
MAX_ANR_WAITS = 32


class Rejected(ValueError):
    pass


def need(value, code):
    if not value:
        raise Rejected(code)


def normalized_component(value):
    parts = value.split("/")
    if len(parts) != 2 or not all(parts):
        return None
    package, name = parts
    return package, package + name if name.startswith(".") else name


def verified_activity_start(raw, component=MAIN, *, notification_interruption=False):
    """am can print an error while adb itself exits successfully."""
    need(isinstance(raw, str) and len(raw) <= 16384, "activity_start_result_invalid")
    need(re.findall(r"^Status:\s*(\S+)\s*$", raw, re.MULTILINE) == ["ok"], "unified_launcher_activity_start_rejected")
    activities = re.findall(r"^Activity:\s*(\S+)\s*$", raw, re.MULTILINE)
    need(len(activities) == 1, "unified_launcher_activity_identity_mismatch")
    reported = normalized_component(activities[0])
    if reported == normalized_component(component):
        return False
    # Android 13+ can report the notification permission Activity as the result
    # of a successful explicit MAIN launch. This is an interruption, never proof
    # that the requested launcher is ready. Its real UI/target and then MAIN's
    # foreground lifecycle are independently required below.
    if notification_interruption and reported and reported[0] in PERMISSION_CONTROLLERS and reported[1] == PERMISSION_ACTIVITY:
        intents = re.findall(r"^Starting:\s*Intent\s*\{([^\n}]*)\}\s*$", raw, re.MULTILINE)
        requested = re.findall(r"(?:^|\s)cmp=(\S+)", intents[0]) if len(intents) == 1 else []
        need(len(intents) == 1 and len(requested) == 1
             and normalized_component(requested[0]) == normalized_component(component)
             and re.search(r"(?:^|\s)act=android\.intent\.action\.MAIN(?:\s|$)", intents[0])
             and re.search(r"(?:^|\s)cat=\[android\.intent\.category\.LAUNCHER\](?:\s|$)", intents[0]),
             "unified_launcher_requested_main_unverified")
        return True
    raise Rejected("unified_launcher_activity_identity_mismatch")


def foreground_activity(raw):
    need(isinstance(raw, str) and len(raw) <= 2 * 1024 * 1024, "foreground_activity_context_invalid")
    pattern = r"^\s*%s\s*[:=]\s*ActivityRecord\{(\S+)\s+u\d+\s+(\S+)"
    rows = re.findall(pattern % "topResumedActivity", raw, re.MULTILINE)
    if not rows:
        rows = re.findall(pattern % "mResumedActivity", raw, re.MULTILINE)
    identities = {(token, normalized_component(component)) for token, component in rows}
    need(len(identities) <= 1, "foreground_activity_ambiguous")
    return next(iter(identities)) if identities else (None, None)


def notification_permission_control(tree, activities):
    """Accept only the actual target app's observed notification request UI."""
    token, component = foreground_activity(activities)
    if not component or component[0] not in PERMISSION_CONTROLLERS or component[1] != PERMISSION_ACTIVITY:
        return None
    nodes = [node for node in tree.iter("node") if node.get("package") == component[0]]
    if not nodes:
        return None  # A different system overlay can obscure this Activity.
    # The foreground system Activity's own record binds the dialog to the
    # requested package. A similar app label in a different request is not enough.
    records = list(re.finditer(r"^[ \t]*\*[ \t]+Hist[ \t]+#\d+:[ \t]*ActivityRecord\{(\S+)\s+u\d+\s+(\S+)[^\n]*", activities, re.MULTILINE))
    matches = [(index, row) for index, row in enumerate(records)
               if row[1] == token and normalized_component(row[2]) == component]
    need(len(matches) == 1, "notification_permission_target_unverified")
    index, row = matches[0]
    block = activities[row.end():records[index + 1].start() if index + 1 < len(records) else len(activities)]
    callers = re.findall(r"\blaunchedFromPackage=([^\s,]+)", block)
    need(callers == [PACKAGE]
         and re.search(r"\bact=android\.content\.pm\.action\.REQUEST_PERMISSIONS(?:\s|[}])", block),
         "notification_permission_target_unverified")
    def text(value):
        return " ".join(re.sub(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", value).split())
    # The official QA guest uses English system UI. Match this permission kind,
    # not generic Allow text. Its app label is not a package identity (and the
    # unified app's label differs from the server's app_name resource); the
    # actual Activity record above supplies that identity independently.
    message_ids = {package + ":id/permission_message" for package in PERMISSION_CONTROLLERS}
    allow_ids = {package + ":id/permission_allow_button" for package in PERMISSION_CONTROLLERS}
    messages = [node for node in nodes if node.get("resource-id") in message_ids]
    need(len(messages) == 1 and re.fullmatch(r"Allow [^?\r\n]{1,256} to send you notifications\?",
                                           text(messages[0].get("text", ""))),
         "notification_permission_kind_unverified")
    controls = [node for node in nodes if node.get("resource-id") in allow_ids
                and node.get("enabled") == "true" and node.get("clickable") == "true"
                and node.get("class") == "android.widget.Button"]
    need(len(controls) == 1, "notification_permission_control_ambiguous")
    return controls[0]


def launcher_main_control(tree, activities, lifecycle):
    """A system permission window can never stand in for the real Main UI."""
    if foreground_activity(activities)[1] != normalized_component(MAIN):
        return None
    need(isinstance(lifecycle, str) and len(lifecycle) <= 16384, "unified_launcher_lifecycle_invalid")
    rows = re.findall(r"^\d+ server (precreated|created|started|resumed|paused|stopped|destroyed) finishing=(true|false) destroyed=(true|false)\s*$",
                      lifecycle, re.MULTILINE)
    # Configuration changes can recreate MAIN; require the current incarnation,
    # not an old resumed line followed by a later pause/destruction.
    starts = [index for index, row in enumerate(rows) if row[0] == "precreated"]
    current = rows[starts[-1]:] if starts else rows
    states = [row[0] for row in current]
    if not ("created" in states and "started" in states and current
            and current[-1] == ("resumed", "false", "false")
            and states.index("created") < states.index("started") < len(states) - 1):
        return None
    names = labels("launch_diagnostic_client")
    controls = [node for node in tree.iter("node") if node.get("package") == PACKAGE
                and node.get("class") == "android.widget.Button" and node.get("enabled") == "true"
                and node.get("clickable") == "true"
                and (node.get("text") in names or node.get("content-desc") in names)]
    need(len(controls) <= 1, "unified_launch_control_ambiguous")
    return controls[0] if controls else None


def redroid_guest_verified(properties):
    """Exact native ARM64 redroid identity; no ARM translation can be present."""
    return (isinstance(properties, dict)
            and properties.get("ro.hardware") == "redroid" and properties.get("ro.boot.hardware") == "redroid"
            and properties.get("ro.product.device") in REDROID_DEVICES
            and properties.get("ro.product.cpu.abi") == "arm64-v8a"
            and "arm64-v8a" in str(properties.get("ro.product.cpu.abilist", "")).split(",")
            and set(str(properties.get("ro.product.cpu.abilist", "")).split(",")) <= {"arm64-v8a", "armeabi-v7a", "armeabi"}
            and properties.get("ro.dalvik.vm.native.bridge") in ("", "0")
            and properties.get("uname_machine") == "aarch64")


ANR_WINDOW = re.compile(r"Window\{[0-9a-f]+\s+u\d+\s+Application Not Responding:\s*([A-Za-z0-9_.]{1,256})\}")


def system_anr_windows(raw):
    """Package names of Android's own ANR dialog windows in `dumpsys window windows`."""
    if not isinstance(raw, str) or len(raw) > 8 * 1024 * 1024:
        return []
    return sorted(set(ANR_WINDOW.findall(raw)))


def system_anr_wait_control(tree):
    """The single enabled Wait button of an English system "isn't responding" dialog.

    Returns (title, node) or None. Close/report are never selected; an ambiguous
    dialog is left on screen so the surrounding wait reports its own timeout.
    """
    def text(value):
        return " ".join(re.sub(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", value or "").split())
    nodes = [node for node in tree.iter("node") if node.get("package") == "android"]
    titles = [text(node.get("text")) for node in nodes
              if re.fullmatch(r".{1,256} (?:isn't|isn\u2019t|is not) responding", text(node.get("text")))]
    waits = [node for node in nodes if node.get("resource-id") == "android:id/aerr_wait"
             and node.get("enabled") == "true" and node.get("clickable") == "true"]
    if len(titles) != 1 or len(waits) != 1:
        return None
    return titles[0], waits[0]


def notification_permission_granted(raw):
    return isinstance(raw, str) and re.search(
        r"^\s*" + re.escape(NOTIFICATION_PERMISSION) + r": granted=true\b", raw, re.MULTILINE) is not None


def export_trace_summary(payload):
    """Where the native export currently is or stopped; evidence only, never a verdict."""
    if type(payload) is not dict:
        return {}
    summary = {}
    status = payload.get("native_status")
    if type(status) is dict:
        for key in ("phase", "error_code", "readiness_error", "selection_error", "restoration_error",
                    "pipeline_mode", "export_id", "frames", "total_frames", "audio_frames", "total_audio_frames"):
            if key in status:
                summary[key] = status[key]
        if type(status.get("scene_diagnostics")) is dict:
            summary["scene_diagnostics"] = status["scene_diagnostics"]
    application = payload.get("app_diagnostics")
    if type(application) is dict:
        for key in ("job_stage", "cleanup_stage", "last_cancel", "last_java_crash", "last_save_failure_stage"):
            if key in application:
                summary[key] = application[key]
        if type(application.get("last_failed_export_trace")) is dict:
            summary["last_failed_export_trace"] = application["last_failed_export_trace"]
    native = payload.get("native_diagnostics")
    trace = native.get("export_trace") if type(native) is dict else None
    if type(trace) is not dict and type(application) is dict:
        trace = application.get("export_trace")
    if type(trace) is dict:
        events = [event for event in trace.get("events", []) if type(event) is dict][-16:] \
            if type(trace.get("events")) is list else []
        modules = trace.get("modules") if type(trace.get("modules")) is dict else {}
        summary["export_trace"] = {"current_stage": trace.get("current_stage"), "last_error": trace.get("last_error"),
            "events": events, "unbound_modules": sorted(k for k, v in modules.items() if v is False)}
        if type(native) is dict and type(native.get("session_progress")) is dict:
            summary["session_progress"] = native["session_progress"]
    return summary


PERSISTED_DIAGNOSTIC_KEYS = ("last_native_trace", "last_failed_native_trace", "last_cancel",
                             "last_java_crash", "last_save_failure_stage")


def persisted_mp4_diagnostics(raw):
    """The app's own persisted export trace (SharedPreferences), readable after a crash."""
    need(isinstance(raw, str) and len(raw) <= 1024 * 1024, "persisted_mp4_diagnostics_invalid")
    start, end = raw.find("<map"), raw.rfind("</map>")
    if start < 0 or end < start:
        return {"available": False}
    root = ET.fromstring(raw[start:end + len("</map>")])
    result = {"available": True}
    for node in root:
        name = node.get("name")
        if name not in PERSISTED_DIAGNOSTIC_KEYS or node.tag != "string":
            continue
        value = node.text or ""
        try:
            result[name] = json.loads(value) if value[:1] in "{[" else value[:256]
        except ValueError:
            result[name] = "unparseable"
    return result


def verified_observer_manifest(evidence):
    need(isinstance(evidence,dict)
         and evidence.get("compiled_manifest_structure_preserved") is True
         and evidence.get("manifest_factory_and_activities_preserved") is True,
         "qa_manifest_component_preservation_unverified")


LAUNCH_ROW = re.compile(r"^(\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\s+(\d+)\s+(\d+)\s+([VDIWEF])\s+([^:]+):\s?(.*)$")
LAUNCH_SENSITIVE = re.compile(r"authorization|password|passcode|(?:auth|access|refresh|id)[_-]?token|"
    r"(?:transfer|handoff|account|player|user|seed|device|android|advertising)[_ -]?id\s*[:=]|\bID:\s*\d", re.I)


def launch_log_evidence(raw, package=PACKAGE):
    """Retain bounded launch context and ALL target process incarnations.

    A final surviving provider PID is not necessarily the failed Activity PID.
    Package-only line filtering also drops transaction/exception continuations.
    """
    need(isinstance(raw, str) and len(raw) <= 4 * 1024 * 1024, "launch_log_evidence_oversized")
    lines=raw.splitlines()[-4096:]
    rows=[LAUNCH_ROW.match(line) for line in lines]
    target=re.compile(re.escape(package)+r"(?![A-Za-z0-9_.])")
    pids=set();history=[];anchors=[]
    for index,(line,row) in enumerate(zip(lines,rows)):
        if not target.search(line):
            continue
        anchors.append(index)
        if not row:
            continue
        stamp,pid,_,_,tag,message=row.groups();tag=tag.strip()
        event=None;observed=None
        start=re.search(r"\bStart proc (\d+):"+re.escape(package)+r"(?:/|\b)",message)
        event_start=re.search(r"\[\s*\d+,\s*(\d+),\s*\d+,\s*"+re.escape(package)+r"\s*,",message)
        event_pid=re.search(r"\[\s*\d+,\s*(\d+),\s*"+re.escape(package)+r"\s*[,\]]",message)
        died=re.search(re.escape(package)+r"\s*\(pid (\d+)\).*\bhas died\b",message)
        if start:
            event,observed="process_start",int(start[1])
        elif tag=="am_proc_start"and event_start:
            event,observed="process_start",int(event_start[1])
        elif tag in("am_crash","am_proc_died","am_kill")and event_pid:
            event,observed={"am_crash":"crash","am_proc_died":"process_died","am_kill":"process_killed"}[tag],int(event_pid[1])
        elif died:
            event,observed="process_died",int(died[1])
        elif tag=="ActivityTaskManager"and"Force finishing activity"in message:
            event="activity_force_finished"
        elif tag=="ActivityTaskManager"and re.search(r"\bSTART u\d+\b",message):
            event="activity_start_requested"
        if event:
            entry={"timestamp":stamp,"kind":event,"tag":tag,"record":index}
            if observed:
                pids.add(observed);entry["pid"]=observed
            if event=="activity_start_requested":
                caller=re.search(r"\bfrom uid (\d+)\b",message)
                if caller:entry["caller_uid"]=int(caller[1])
            history.append(entry)
    # Crash/transaction stack lines retain their target PID even without a
    # package name. Include surrounding system-server records, not just anchors.
    chosen=set()
    for index in anchors:
        chosen.update(range(max(0,index-32),min(len(lines),index+33)))
    for index,row in enumerate(rows):
        if row and int(row[2])in pids:
            chosen.add(index)
            tag,message=row[5].strip(),row[6]
            kind=("fatal_exception"if tag=="AndroidRuntime"and"FATAL EXCEPTION"in message else
                  "factory_load_failed"if"Unable to instantiate appComponentFactory"in message else
                  "launch_transaction_failed"if"Failed to execute the transaction"in message else None)
            if kind:history.append({"timestamp":row[1],"kind":kind,"tag":tag,"pid":int(row[2]),"record":index})
    history.sort(key=lambda row:row["record"])
    for event in history:event.pop("record")
    # Budget priority must not follow log chronology: PackageManager anchors
    # can pull a large Settings-indexing flood in before the failed Activity.
    # Keep the actual failure/transaction stack and process events first, then
    # fill with target-PID logs and surrounding system context. Emit the chosen
    # records chronologically only after applying this semantic priority.
    failure_tags={"AndroidRuntime","TransactionExecutor","ActivityThread","IdolyLauncher"}
    system_tags={"ActivityTaskManager","ActivityManager"}
    critical=[i for i in chosen if rows[i]and(
        int(rows[i][2])in pids and rows[i][5].strip()in failure_tags
        or rows[i][5].strip()in system_tags and re.search(r"Exception|Error|\bat (?:android|com)\.",rows[i][6]))]
    own=[i for i in chosen if rows[i]and int(rows[i][2])in pids]
    priority=list(dict.fromkeys(sorted(critical)+anchors+sorted(own)+sorted(chosen,reverse=True)))
    selected={};bytes_kept=0;redacted=0
    for index in priority:
        line=lines[index];row=rows[index]
        sensitive=bool(LAUNCH_SENSITIVE.search(line))
        if sensitive:
            types=re.findall(r"(?:[A-Za-z_$][A-Za-z0-9_$]*\.)+[A-Za-z_$][A-Za-z0-9_$]*(?:Exception|Error)\b",line)
            line=(line[:row.start(6)]if row else"")+(", ".join(types[:3])+": "if types else"")+"[sensitive launch log content omitted]"
        line=line[:4096]+(" [truncated]"if len(line)>4096 else"")
        encoded=len(line.encode("utf-8"))+1
        if bytes_kept+encoded>128*1024:
            continue
        selected[index]=line;bytes_kept+=encoded;redacted+=int(sensitive)
    ordered=[selected[i]for i in sorted(selected)]
    return {"schema":1,"package":package,"observed_process_ids":sorted(pids),
        "events":history[:256],"redacted_records":redacted,"input_records":len(lines),
        "retained_records":len(ordered),"omitted_context_records":len(chosen)-len(ordered),
        "context":"\n".join(ordered)+("\n"if ordered else"")}


def integer(value, minimum=0, maximum=9007199254740991):
    return type(value) is int and minimum <= value <= maximum


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reported_digest(raw, code):
    fields = raw.split()
    need(bool(fields) and HEX64.fullmatch(fields[0]), code)
    return fields[0]


def native_payload(payload):
    need(type(payload) is dict and payload.get("ok") is True and payload.get("qa_only") is True
         and payload.get("read_only") is True, "native_observation_unavailable")
    state = payload.get("native")
    need(type(state) is dict and type(state.get("schema")) is int and state.get("schema") == 1, "native_status_invalid")
    observed = state.get("observation")
    need(type(observed) is dict and type(observed.get("schema")) is int and observed.get("schema") == 1
         and observed.get("pipeline") == "owned_native_clock", "owned_native_pipeline_unavailable")
    need(observed.get("source_valid") is True and observed.get("source_kind") == "photography_3d"
         and type(observed.get("source_identity")) is str
         and observed.get("source_identity") != "0000000000000000"
         and re.fullmatch(r"[A-Za-z0-9_:.\-]{1,96}", observed["source_identity"]), "normal_3d_source_unavailable")
    need(integer(observed.get("playerloop_frame")) and finite(observed.get("source_time"))
         and 0 <= observed["source_time"] <= 900 and type(observed.get("source_paused")) is bool,
         "source_observation_invalid")
    return state, observed


def validate_paused_source(first, second):
    a, x = native_payload(first)
    b, y = native_payload(second)
    need(a.get("ready") is True and b.get("ready") is True, "paused_source_not_ready")
    need(x["source_identity"] == y["source_identity"] and x["source_paused"] and y["source_paused"],
         "source_not_paused")
    need(y["playerloop_frame"] > x["playerloop_frame"], "playerloop_suspended_is_not_mv_pause")
    need(abs(y["source_time"] - x["source_time"]) <= .0001, "paused_timeline_advanced")
    need(x.get("coordinator_active") is False and y.get("coordinator_active") is False
         and x.get("native_clock_owned") is False and y.get("native_clock_owned") is False,
         "baseline_already_owned")
    return y


def validate_playing_source(first, second):
    """Observe normal playback; IDOLY PRIDE has no in-MV Pause button."""
    _, x = native_payload(first)
    _, y = native_payload(second)
    need(x["source_identity"] == y["source_identity"]
         and x["source_paused"] is False and y["source_paused"] is False,
         "source_not_playing")
    need(y["playerloop_frame"] > x["playerloop_frame"], "playing_source_playerloop_not_advancing")
    need(y["source_time"] > x["source_time"] + .0001, "playing_source_timeline_not_advancing")
    need(x.get("coordinator_active") is False and y.get("coordinator_active") is False
         and x.get("native_clock_owned") is False and y.get("native_clock_owned") is False,
         "baseline_already_owned")
    # Native export readiness is a separate gate. A visible, advancing real MV
    # can be observed even when a required export provider is still unavailable.
    return y


def validate_running(payload, previous_tick=None):
    state, observed = native_payload(payload)
    need(observed.get("coordinator_active") is True and observed.get("native_clock_owned") is True
         and observed.get("world_admission") == "verified", "render_admission_not_verified")
    tick = observed.get("simulation_tick")
    need(tick is None or integer(tick), "simulation_tick_invalid")
    if previous_tick is not None and tick is not None:
        need(tick >= previous_tick, "simulation_clock_rewound_during_job")
    need(integer(observed.get("accepted_frames")), "accepted_frame_observation_invalid")
    need(integer(observed.get("rendered_simulation_ticks")), "draw_count_observation_invalid")
    return tick


def validate_clock_hold(first, second):
    """A live PlayerLoop must not turn a held offline frame into realtime play."""
    validate_running(first)
    validate_running(second)
    _, a = native_payload(first)
    _, b = native_payload(second)
    need(a.get("native_clock_held") is True and b.get("native_clock_held") is True,
         "native_clock_hold_not_observed")
    need(integer(a.get("simulation_tick")) and a["simulation_tick"] == b.get("simulation_tick")
         and a["accepted_frames"] > 0 and a["accepted_frames"] == b["accepted_frames"]
         and a["rendered_simulation_ticks"] == b["rendered_simulation_ticks"],
         "held_frame_scope_changed")
    need(b["playerloop_frame"] > a["playerloop_frame"], "held_clock_playerloop_not_advancing")
    need(abs(b["source_time"] - a["source_time"]) <= .0001, "held_clock_source_timeline_advanced")


def validate_export_pause(first, second):
    for payload in (first, second):
        state, _ = native_payload(payload)
        need(state.get("phase") == "paused" and state.get("paused") is True
             and state.get("pause_requested") is True, "export_pause_not_acknowledged")
    validate_clock_hold(first, second)


def export_acquisition_baseline(before, current, *, replay=False):
    """Use the actual internal acquisition, after menu/configuration time."""
    old, previous = native_payload(before)
    state, observation = native_payload(current)
    need(state.get("export_id") != old.get("export_id") and state.get("phase") == "rendering",
         "new_export_scope_not_observed")
    identity, seconds, paused = (observation.get("acquired_source_identity"),
                                observation.get("acquired_source_time"), observation.get("acquired_source_paused"))
    need(observation.get("acquired_source_valid") is True
         and type(identity) is str and re.fullmatch(r"[0-9a-f]{16}", identity) and identity != "0000000000000000"
         and finite(seconds) and 0 <= seconds <= 900 and type(paused) is bool,
         "native_export_acquisition_baseline_unavailable")
    need(replay or identity == previous["source_identity"], "direct_export_source_identity_changed")
    baseline = json.loads(json.dumps(before))
    baseline["native"]["observation"].update(source_identity=identity, source_time=seconds, source_paused=paused)
    return baseline


def validate_restored(baseline, final):
    _, old = native_payload(baseline)
    _, restored = native_payload(final)
    need(restored["source_identity"] == old["source_identity"]
         and restored["source_paused"] is old["source_paused"]
         and (abs(restored["source_time"] - old["source_time"]) <= .0001 if old["source_paused"]
              else restored["source_time"] + .0001 >= old["source_time"]), "source_pause_position_not_restored")
    need(restored.get("restored_source_valid") is True
         and restored.get("restored_source_identity") == old["source_identity"]
         and restored.get("restored_source_paused") is old["source_paused"]
         and finite(restored.get("restored_source_time"))
         and abs(restored["restored_source_time"] - old["source_time"]) <= .0001,
         "native_source_restoration_checkpoint_differs")
    need(restored.get("coordinator_active") is False and restored.get("native_clock_owned") is False,
         "native_scope_not_released")
    for name in ("source_restored", "clock_settings_restored", "camera_audio_restored", "dependent_state_restored"):
        need(restored.get(name) is True, name + "_not_verified")


def validate_completed(baseline, final, width, height, fps):
    need(integer(width, 16, 4096) and integer(height, 16, 4096) and fps in (30, 60)
         and type(fps) is int, "requested_render_geometry_or_rate_invalid")
    before, _ = native_payload(baseline)
    state, observed = native_payload(final)
    need(state.get("phase") == "completed" and state.get("error_code") == "none", "native_export_not_completed")
    need(type(state.get("export_id")) is str and HEX32.fullmatch(state["export_id"]), "export_identity_invalid")
    total = state.get("total_frames")
    need(integer(total, 2) and integer(state.get("frames")) and integer(observed.get("accepted_frames"))
         and state.get("frames") == total and observed.get("accepted_frames") == total,
         "native_frame_count_differs")
    need(integer(state.get("capture_acks")) and integer(before.get("capture_acks"))
         and state["capture_acks"] - before["capture_acks"] == total, "real_capture_ack_count_differs")
    # Public source_width/height describe the current idle MV for UI/queue
    # readiness and can change immediately after source-target restoration.
    # The native observation retains the job's actual readback/render target.
    need(all(integer(state.get(k)) for k in ("width", "height", "fps_num", "fps_den"))
         and state.get("width") == width and state.get("height") == height
         and integer(observed.get("render_width")) and integer(observed.get("render_height"))
         and observed.get("render_width") == width and observed.get("render_height") == height
         and state.get("fps_num") == fps and state.get("fps_den") == 1, "actual_render_geometry_or_rate_differs")
    need(integer(state.get("total_audio_frames"), 1)
         and state.get("audio_frames") == state["total_audio_frames"], "native_audio_not_complete")
    need(integer(observed.get("simulation_tick")) and observed.get("simulation_tick") == (total - 1) * (60 // fps),
         "simulation_schedule_differs")
    need(integer(observed.get("rendered_simulation_ticks"))
         and observed["rendered_simulation_ticks"] == observed["simulation_tick"] + 1,
         "actual_simulation_draw_count_differs")
    validate_restored(baseline, final)
    return state


def validate_probe(probe, state):
    need(type(probe) is dict and type(probe.get("streams")) is list, "probe_streams_invalid")
    video = [s for s in probe["streams"] if s.get("codec_type") == "video"]
    audio = [s for s in probe["streams"] if s.get("codec_type") == "audio"]
    need(len(video) == len(audio) == 1, "expected_one_video_and_audio_stream")
    video, audio = video[0], audio[0]
    need(video.get("codec_name") == "h264" and video.get("width") == state["width"]
         and video.get("height") == state["height"], "encoded_geometry_or_codec_differs")
    try:
        rate = Fraction(video["avg_frame_rate"])
        count = int(video["nb_read_frames"])
        sample_rate = int(audio["sample_rate"])
        duration = float(audio["duration"])
    except (ValueError, TypeError, KeyError, ZeroDivisionError):
        raise Rejected("probe_timing_invalid") from None
    need(rate == Fraction(state["fps_num"], state["fps_den"]) and count == state["total_frames"],
         "decoded_rate_or_count_differs")
    need(audio.get("codec_name") == "aac" and audio.get("channels") == 2 and sample_rate in (44100, 48000),
         "encoded_audio_format_differs")
    need(abs(duration - state["total_audio_frames"] / sample_rate) <= 2048 / sample_rate + .005,
         "encoded_audio_duration_differs")
    packets = [p for p in probe.get("packets", []) if p.get("codec_type") == "video"]
    need(len(packets) == count, "video_packet_count_differs")
    try:
        pts = sorted(Fraction(p["pts"]) * Fraction(video["time_base"]) for p in packets)
    except (ValueError, TypeError, KeyError, ZeroDivisionError):
        raise Rejected("video_packet_pts_invalid") from None
    need(all(abs(t - Fraction(index, 1) / rate) <= Fraction(1, 1000000) for index, t in enumerate(pts)),
         "video_packet_pts_not_rational_frame_steps")
    return {"frames": count, "fps": str(rate), "width": video["width"], "height": video["height"],
            "audio_sample_rate": sample_rate, "audio_duration": duration}


def load_ui():
    spec = importlib.util.spec_from_file_location("actual_mv_observed_ui", ROOT / "android-server/ci/qa_game_ui.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# QA ONLY, explicit option: the unified app's embedded server listens on this
# guest-loopback gRPC port (reached through an adb forward on the selected serial).
FIXTURE_SERVER_PORT = 50051
FIXTURE_SERVER_TIMEOUT, FIXTURE_RPC_TIMEOUT = 300, 60
# Master tables the tutorial continuation reads (Mission.json is required for
# its card-level mission delta check).
FIXTURE_TABLES = ("Setting.json", "CardLevel.json", "Message.json", "Mission.json")
FIXTURE_CHECK_PREFIX = "Tutorial continuation QA: "


def load_fixture_boot():
    """qa_game_boot, reused as is for its completed-opening fixture.

    grpc (and protobuf/pycryptodome through idoly_local) is imported only here,
    so the default driver path and its tests never need them.
    """
    for path in (ROOT / "src", ROOT / "android-server/ci"):
        if str(path) not in sys.path:
            sys.path.append(str(path))
    return importlib.import_module("qa_game_boot")


def fixture_failure_code(stage, error, boot=None):
    """A fixed code: never exception text, which for an RPC can carry details."""
    rpc_error = getattr(getattr(boot, "grpc", None), "RpcError", ())
    if isinstance(error, Rejected):
        reason = str(error)
    elif isinstance(error, rpc_error):
        try:
            reason = "rpc_" + error.code().name.lower()
        except Exception:  # A non-call RpcError has no status code.
            reason = "rpc_error"
    else:
        reason = type(error).__name__
    return "profile_fixture_failed_" + stage + "_" + re.sub(r"[^A-Za-z0-9_]", "_", reason)[:64]


def fixture_failed_check(error):
    """The continuation's own literal check name; nothing else is kept."""
    text = str(error) if type(error) is RuntimeError else ""
    found = re.fullmatch(re.escape(FIXTURE_CHECK_PREFIX) + r"([A-Za-z][A-Za-z0-9 ./=-]{0,159})", text)
    return re.sub(r"[^a-z0-9]+", "_", found[1].lower()).strip("_") if found else None


def completed_opening_document(fixture):
    """qa_game_boot's fixture result, accepted only as credential-free setup."""
    need(type(fixture) is dict and fixture.get("enabled") is True and fixture.get("qa_only") is True
         and fixture.get("status") == "ready" and fixture.get("completed_tutorial_step") == 150
         and fixture.get("tutorial_cleared") is True and fixture.get("actual_game_tutorial_played") is False,
         "profile_fixture_result_invalid")
    calls = fixture.get("rpc_calls")
    need(type(calls) is list and len(calls) >= 3 and all(
        type(row) is dict and set(row) == {"method", "status", "origin"} and row["status"] == "OK"
        and row["origin"] == "profile_fixture" and type(row["method"]) is str
        and re.fullmatch(r"/api\.[A-Za-z0-9_]+/[A-Za-z0-9_]+", row["method"]) for row in calls)
         and [row["method"] for row in calls[:2]] == ["/api.Auth/Login", "/api.Tutorial/Init"],
         "profile_fixture_calls_invalid")
    document = dict(fixture, server="embedded_unified_server", prepared_before_game_launch=True,
                    gameplay_evidence=False)
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    # Defense in depth: a local session token ("local-" + urlsafe) is never written.
    need(not re.search(r"local-[A-Za-z0-9_-]{16,}", text), "profile_fixture_secret_shaped_value")
    return document, text


# The title ignores input while it fades in; re-tap a still-visible title.
TITLE_RETAP_SECONDS, TITLE_TAP_LIMIT = 20, 15


TERMS_SHEET = "/TermsOfServiceSheet(Clone)/"
TERMS_AGREE_SUFFIX = "/Actions/Execute/TextButtonNormal"


def terms_agree_target(snapshot):
    """The single active, wired Agree button of the game's Terms of Service sheet."""
    nodes = snapshot.get("nodes") if isinstance(snapshot, dict) else None
    if not isinstance(nodes, list):
        return None
    found = [node for node in nodes if isinstance(node, dict) and node.get("kind") == "button"
             and node.get("active") is True and node.get("interactable") is True
             and node.get("callback_registered") is True
             and TERMS_SHEET in str(node.get("path", "")) and str(node.get("path", "")).endswith(TERMS_AGREE_SUFFIX)]
    return found[0] if len(found) == 1 else None


def home_input_blocked(snapshot):
    """True while the game's own startup observation says input is held.

    A missing observation is not treated as blocked; the explorer's own
    per-touch checks still refuse a control that is not current.
    """
    startup = snapshot.get("startup_observation") if isinstance(snapshot, dict) else None
    return isinstance(startup, dict) and (startup.get("content_blocking") is True or startup.get("input_releasing") is True)


# Photography Live route (Korean 6.1.1 hierarchy observed in redroid run 9;
# the screens after the Live page are from the game's own type names:
# PhotographyTopPage decide -> LivePhotographyScreen music/stage lists and
# decide -> PhotographyConfirmSheet preview).
ORIGINAL_MEMBER_SUFFIX = "/PhotographyLivePage/Lower/Checkbox/TouchArea/Label"
DECIDE_LABEL = r"^(決定|결정|次へ|다음|Decide|Next|OK)(する|하기)?$"
DECIDE_NAME = r"Decide"
VIEW_LABEL = r"^(鑑賞|감상|プレビュー|미리\s*보기|Preview|View|Watch)(する|하기)?$"
VIEW_NAME = r"^(Viewing|View|Watch|Preview)(Button)?$"
OVERLAY_PATH = re.compile(r"Sheet|Dialog")
MUSIC_CELL_PATH = re.compile(r"Music[A-Za-z]*(List|Cell)")
STAGE_CELL_PATH = re.compile(r"Stage[A-Za-z]*(List|Cell)")
SONG_SWIPE_LIMIT = 40


def original_member_label(ui, snapshot):
    """The Live page's "match the stage song" checkbox label (its TouchArea is no button)."""
    found = [node for node in ui.label_nodes(snapshot) if str(node.get("path", "")).endswith(ORIGINAL_MEMBER_SUFFIX)]
    return found[0] if len(found) == 1 else None


def choose_route_button(ui, snapshot, label, name=None, exclude=(), prefer=None):
    """A unique button by label (exact, then contained), then by object name.

    With several matches, a single one on a sheet or dialog (``prefer``) is
    the control on top.
    """
    candidates = [b for b in ui.buttons(snapshot) if not any(part in b["path"] for part in exclude)]
    def unique(rows):
        if len(rows) > 1 and prefer is not None:
            top = [row for row in rows if prefer.search(row["path"])]
            rows = top if len(top) == 1 else rows
        return rows[0] if len(rows) == 1 else None
    exact = [b for b in candidates if re.fullmatch(label, b["label"], re.I)]
    if exact:
        return unique(exact)
    matched = [b for b in candidates if re.search(label, b["label"], re.I)]
    if matched:
        return unique(matched)
    if name:
        # A text button's touch target can be a generic child (the Terms
        # sheet's .../Execute/TextButtonNormal): its parent names the action.
        return unique([b for b in candidates if re.search(name, str(b.get("name", "")), re.I)
                       or re.search(name, b["path"].rsplit("/", 2)[-2] if b["path"].count("/") else "", re.I)])
    return None


def labels(name):
    found = set()
    for path in (ROOT / "android-server/app/src/main/res").glob("values*/strings*.xml"):
        for node in ET.parse(path).getroot().findall("string"):
            if node.get("name") == name and node.text:
                found.add(node.text)
    need(found, "source_ui_resource_missing_" + name)
    return found


class Device:
    def __init__(self, adb, serial, output, guest=TRANSLATED_GUEST):
        need(guest in GUESTS, "qa_guest_kind_invalid")
        need(re.fullmatch(GUESTS[guest]["serial"], serial), GUESTS[guest]["serial_code"])
        self.guest = guest
        self.base, self.output = [str(adb), "-s", serial], output
        self.game_package, self.artifacts = PACKAGE, output
        self.input_source, self.touch_hold_ms = "touchscreen", 150
        self.capture_number = 0

    def adb(self, *args, binary=False, check=True, timeout=30, merge_error=False):
        result = subprocess.run(self.base + list(args), capture_output=True, timeout=timeout)
        if check:
            need(result.returncode == 0, "adb_operation_failed_" + re.sub(r"[^a-zA-Z_]", "_", args[0]))
        raw = result.stdout + (b"\nSTDERR\n" + result.stderr if merge_error and result.stderr else b"")
        return raw if binary else raw.decode("utf-8", errors="replace")

    def forward(self, port):
        value = self.adb("forward", "tcp:0", "tcp:" + str(port)).strip()
        need(value.isdigit() and 1 <= int(value) <= 65535, "loopback_forward_failed")
        return int(value)

    def identity(self):
        if getattr(self, "guest", TRANSLATED_GUEST) == REDROID_GUEST:
            # No translator exists to hash; record the native GPU/codec stack instead.
            properties = {name: self.adb("shell", "getprop", name).strip() for name in REDROID_PROPERTIES}
            properties["uname_machine"] = self.adb("shell", "uname", "-m").strip()
            need(redroid_guest_verified(properties), "redroid_native_arm64_guest_unavailable")
            properties["guest"] = REDROID_GUEST
            return properties
        properties = {name: self.adb("shell", "getprop", name).strip() for name in (
            "ro.kernel.qemu", "ro.product.cpu.abilist", "ro.dalvik.vm.native.bridge",
            "ro.build.version.sdk", "ro.build.version.incremental", "ro.hardware.egl")}
        need(properties["ro.kernel.qemu"] == "1" and "arm64-v8a" in properties["ro.product.cpu.abilist"].split(",")
             and properties["ro.dalvik.vm.native.bridge"] not in ("", "0"), "official_translated_guest_unavailable")
        properties["native_bridge_sha256"] = reported_digest(
            self.adb("shell", "sha256sum", "/system/lib64/libndk_translation.so"), "bundled_native_bridge_unverified")
        return properties

    def android(self):
        self.capture_number += 1
        raw = self.adb("exec-out", "uiautomator", "dump", "/dev/tty", check=False)
        prefix = self.output / ("android-%04d" % self.capture_number)
        prefix.with_suffix(".raw.txt").write_text(raw)
        start, end = raw.find("<hierarchy"), raw.rfind("</hierarchy>")
        need(start >= 0 and end >= start, "android_ui_tree_unavailable")
        xml = raw[start:end + len("</hierarchy>")]
        prefix.with_suffix(".xml").write_text(xml)
        return ET.fromstring(xml)

    def screenshot(self, name):
        raw = self.adb("exec-out", "screencap", "-p", binary=True)
        need(raw.startswith(b"\x89PNG\r\n\x1a\n"), "display_capture_unavailable")
        (self.output / (name + ".png")).write_bytes(raw)
        return struct.unpack_from(">II", raw, 16)

    @staticmethod
    def point(node):
        found = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
        need(found, "android_bounds_invalid")
        left, top, right, bottom = map(int, found.groups())
        need(left < right and top < bottom, "android_bounds_invalid")
        return (left + right) // 2, (top + bottom) // 2

    def touch(self, node):
        x, y = self.point(node)
        self.adb("shell", "input", "touchscreen", "swipe", str(x), str(y), str(x), str(y), "150")

    def android_control(self, values, *, cls=None, scroll=True, packages=(PACKAGE,)):
        for attempt in range(12 if scroll else 1):
            tree = self.android()
            nodes = [n for n in tree.iter("node") if n.get("package") in packages
                     and n.get("enabled") == "true" and (cls is None or n.get("class") == cls)
                     and (n.get("text") in values or n.get("content-desc") in values)]
            need(len(nodes) <= 1, "android_control_ambiguous")
            if nodes:
                return nodes[0]
            if not scroll:
                return None
            scrollable = [n for n in tree.iter("node") if n.get("package") == PACKAGE and n.get("scrollable") == "true"]
            if len(scrollable) != 1:
                break
            x, y = self.point(scrollable[0])
            box = list(map(int, re.findall(r"\d+", scrollable[0].get("bounds"))))
            self.adb("shell", "input", "swipe", str(x), str(box[3] - 40), str(x), str(box[1] + 40), "300")
        raise Rejected("android_control_missing")

    def press_resource(self, name):
        self.touch(self.android_control(labels(name), cls="android.widget.Button"))

    def spinner(self, name, value):
        expected = labels(name)
        found = None
        for _ in range(12):
            tree = self.android()
            candidates = []
            for parent in tree.iter("node"):
                children = list(parent)
                for index, node in enumerate(children[:-1]):
                    following = children[index + 1]
                    if node.get("text") in expected and following.get("class") == "android.widget.Spinner":
                        candidates.append(following)
            need(len(candidates) <= 1, "spinner_label_ambiguous")
            if candidates:
                found = candidates[0]
                break
            self.android_control(expected)
        need(found is not None, "spinner_label_unavailable")
        self.touch(found)
        choice = self.android_control({value} if isinstance(value, str) else value,
            cls="android.widget.CheckedTextView", scroll=False, packages=(PACKAGE, "android"))
        need(choice is not None, "spinner_choice_unavailable")
        self.touch(choice)

    def number(self, name, value):
        node = self.android_control(labels(name), cls="android.widget.EditText")
        self.touch(node)
        # Ordinary keyboard select-all also covers a field that the IME already
        # focused while the previous setting was edited.
        self.adb("shell", "input", "keycombination", "KEYCODE_CTRL_LEFT", "KEYCODE_A")
        self.adb("shell", "input", "text", str(value))
        self.adb("shell", "input", "keyevent", "KEYCODE_BACK")
        fresh = self.android_control(labels(name), cls="android.widget.EditText")
        need(fresh.get("text") == str(value), "numeric_ui_setting_not_applied")


class ActualRun:
    def __init__(self, args):
        self.args = args
        self.proof = args.output_directory
        self.proof.mkdir(parents=True, exist_ok=False)
        self.device = Device(args.adb, args.serial, self.proof, args.guest)
        self.ui, self.explorer, self.journal = load_ui(), None, []
        self.report = {"schema": 1, "scope": GUESTS[args.guest]["scope"], "guest": args.guest,
                       "source_commit": args.source_commit,
                       "game_sdk_aes_store_adaptations": False, "actual_mv_verified": False,
                       "export_file_verified": False, "restoration_verified": False, "physical_device_verified": False}

    def guest(self):
        return getattr(getattr(self, "args", None), "guest", TRANSLATED_GUEST)

    def record(self, phase, payload=None):
        need(len(self.journal) < 2048, "phase_journal_limit")
        event = {"phase": phase, "monotonic_seconds": round(time.monotonic(), 3)}
        if payload is not None:
            event["observation"] = payload
        self.journal.append(event)
        (self.proof / "phase-journal.json").write_text(json.dumps(self.journal, ensure_ascii=False, indent=2) + "\n")

    def capture_launch_evidence(self, stage):
        need(stage in("initial","final"),"launch_evidence_stage_invalid")
        raw=self.device.adb("logcat","-b","main","-b","system","-b","crash","-b","events",
                            "-d","-t","4096","-v","threadtime",check=False)
        evidence=launch_log_evidence(raw)
        context=evidence.pop("context")
        pids=self.device.adb("shell","pidof",PACKAGE,check=False).split()
        evidence["current_process_ids"]=[int(pid)for pid in pids if pid.isdigit()][:8]
        evidence["pre_launch_process_ids"]=getattr(self,"pre_launch_pids",[])
        (self.proof/(stage+"-launch-system-context.txt")).write_text(context)
        (self.proof/(stage+"-launch-process-history.json")).write_text(json.dumps(evidence,indent=2)+"\n")
        self.report.setdefault("launch_evidence",{})[stage]={"observed_process_ids":evidence["observed_process_ids"],
            "current_process_ids":evidence["current_process_ids"],"events":len(evidence["events"]),
            "retained_records":evidence["retained_records"]}
        return context

    def observer_get(self, path, limit, code):
        token = self.device.adb("exec-out", "run-as", PACKAGE, "cat", "files/idoly-qa-ui-token", check=False).strip()
        need(HEX64.fullmatch(token), "qa_observer_token_unavailable")
        connection = HTTPConnection("127.0.0.1", self.explorer.port, timeout=15)
        try:
            connection.request("GET", path, headers={"Authorization": "Bearer " + token})
            response = connection.getresponse()
            raw = response.read(limit + 1)
            need(response.status == 200 and len(raw) <= limit, code)
            return json.loads(raw)
        finally:
            connection.close()

    def capture_mp4_diagnostics(self, reason, force=False):
        """Keep the app's own native export trace on success and failure alike.

        This is evidence collection only: it never raises, never feeds a verdict
        gate, and does not change the status/timing of any functional check.
        """
        try:
            now = time.monotonic()
            if not force and now - getattr(self, "diagnostics_at", -1e9) < 15:
                return None
            self.diagnostics_at = now
            summary = self.report.setdefault("mp4_diagnostics", {"snapshots": 0, "errors": {}})
            try:
                need(getattr(self, "explorer", None) is not None, "qa_observer_not_started")
                payload = self.observer_get("/mp4-diagnostics", MAX_DIAGNOSTICS, "mp4_diagnostics_rejected")
                need(type(payload) is dict, "mp4_diagnostics_unavailable")
                observer_error = payload.get("error")
                need(payload.get("ok") is True, "observer_" + re.sub(r"[^a-z0-9_]", "_", str(observer_error))[:64]
                     if observer_error else "mp4_diagnostics_unavailable")
            except (Rejected, OSError, ValueError, HTTPException, subprocess.SubprocessError) as error:
                code = str(error)[:96] if isinstance(error, Rejected) else type(error).__name__
                summary["errors"][code] = summary["errors"].get(code, 0) + 1
                summary["last_error_reason"] = reason
                return None
            trace = export_trace_summary(payload)
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            (self.proof / "latest-mp4-diagnostics.json").write_text(text)
            key = json.dumps(trace, sort_keys=True)
            if key != getattr(self, "diagnostics_key", None) and summary["snapshots"] < 256:
                summary["snapshots"] += 1
                (self.proof / ("mp4-diagnostics-%03d-%s.json" % (summary["snapshots"], reason))).write_text(text)
                self.diagnostics_key = key
            summary.update(last_reason=reason, trace=trace)
            return payload
        except Exception as error:  # Diagnostics must never alter a verdict.
            report = getattr(self, "report", None)
            if isinstance(report, dict):
                report.setdefault("mp4_diagnostics_collection_errors", []).append(type(error).__name__)
            return None

    def capture_persisted_mp4_diagnostics(self):
        try:
            raw = self.device.adb("exec-out", "run-as", PACKAGE, "cat", "shared_prefs/mp4_export.xml", check=False)
            document = persisted_mp4_diagnostics(raw)
            (self.proof / "persisted-mp4-diagnostics.json").write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n")
            self.report["persisted_mp4_diagnostics"] = {key: document.get(key) for key in
                ("available", "last_failed_native_trace", "last_cancel", "last_save_failure_stage") if key in document}
        except Exception as error:  # Evidence only.
            self.report["persisted_mp4_diagnostics_unavailable"] = type(error).__name__

    def relieve_system_anr(self, force=False):
        """redroid only: answer Android's own "isn't responding" dialog with Wait.

        The official translated guest keeps refusing every system dialog.
        """
        if self.guest() != REDROID_GUEST:
            return False
        try:
            now = time.monotonic()
            if not force and now - getattr(self, "anr_checked_at", -1e9) < 10:
                return False
            self.anr_checked_at = now
            waited = self.report.setdefault("system_anr_wait_selected", [])
            if len(waited) >= MAX_ANR_WAITS:
                return False
            windows = system_anr_windows(self.device.adb("shell", "dumpsys", "window", "windows", check=False))
            if not windows:
                return False
            tree = self.device.android()
            found = system_anr_wait_control(tree)
            if found is None:
                self.report.setdefault("system_anr_unanswered", []).append({"windows": windows})
                return False
            title, control = found
            self.device.screenshot("system-anr-%02d" % (len(waited) + 1))
            self.device.touch(control)
            entry = {"title": title[:256], "windows": windows, "choice": "wait",
                     "monotonic_seconds": round(time.monotonic(), 3)}
            waited.append(entry)
            self.record("redroid_system_anr_wait_selected", entry)
            return True
        except (Rejected, OSError, ValueError, ET.ParseError, subprocess.SubprocessError) as error:
            self.report.setdefault("system_anr_check_errors", []).append(
                str(error)[:96] if isinstance(error, Rejected) else type(error).__name__)
            return False

    def mp4(self):
        payload = self.observer_get("/mp4-status", MAX_JSON, "mp4_observation_rejected")
        need(type(payload) is dict, "mp4_observation_shape_invalid")
        # Keep the last complete read-only status even if admission never
        # becomes ready. Otherwise a failed early game run would discard
        # the concrete Actor/Camera/Stage/World code we need to investigate.
        # The bearer token is only an HTTP header and is never in payload.
        (self.proof / "latest-native-status.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        native = payload.get("native", {})
        observation = native.get("observation", {}) if type(native) is dict else {}
        if type(observation) is dict and observation.get("source_valid") is True and observation.get("source_kind") == "photography_3d":
            (self.proof / "last-photography-native-status.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return payload

    def wait(self, action, timeout, code):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # redroid only, throttled: a system ANR dialog over the game is
            # answered with Wait. The awaited condition itself is unchanged.
            self.relieve_system_anr()
            result = action()
            if result is not None and result is not False:
                return result
            time.sleep(1)
        raise Rejected(code)

    def unity_touch(self, snapshot, node, role):
        need(self.explorer._tap(snapshot, node, role, len(self.journal)), "observed_unity_input_rejected")
        self.record(role)

    def route(self, pattern, name=None, optional=False):
        def attempt():
            snap = self.explorer._snapshot()
            if snap.get("ok") is not True:
                return None
            if self.handle_dialog(snap):
                return None
            if home_input_blocked(snap):
                return None
            node = self.ui.choose_button(snap, pattern, name)
            if node:
                # A control that moved or closed between the snapshot and the
                # touch is re-observed within this route's wait, not a failure.
                if self.explorer._tap(snap, node, "qa_mv_route", len(self.journal)):
                    self.record("qa_mv_route")
                    return True
                return None
            return None
        if optional:
            return attempt()
        return self.wait(attempt, 120, "observed_route_control_unavailable")

    def route_snapshot(self):
        """A current Unity tree with no dialog to answer and input released."""
        snap = self.explorer._snapshot()
        if snap.get("ok") is not True or self.handle_dialog(snap) or home_input_blocked(snap):
            return None
        return snap

    def route_touch(self, snap, node, role, detail=None):
        """Touch through the explorer; a control gone before the touch is re-observed."""
        if not self.explorer._tap(snap, node, role, len(self.journal)):
            return False
        self.record(role, detail)
        return True

    def live_members_decide(self):
        """Photography Live page: "match the stage song", then its Decide.

        The checkbox makes the song's original members the selection, so the
        song list is not filtered by a hand-picked member count. It toggles,
        so it is touched at most twice, 15 s apart, and only while no Decide
        is visible.
        """
        touches = []
        def attempt():
            snap = self.route_snapshot()
            if snap is None:
                return None
            if touches:
                decide = choose_route_button(self.ui, snap, DECIDE_LABEL, DECIDE_NAME)
                if decide is not None:
                    return True if self.route_touch(snap, decide, "qa_mv_live_members_decided",
                                                    {"label": decide["label"], "original_member_touches": len(touches)}) else None
                if len(touches) >= 2 or time.monotonic() - touches[-1] < 15:
                    return None
            label = original_member_label(self.ui, snap)
            if label is not None and self.explorer._tap(snap, label, "qa_mv_original_member", len(self.journal)):
                touches.append(time.monotonic())
                self.record("qa_mv_original_member", {"touch": len(touches), "label": label["label"]})
            return None
        self.wait(attempt, 120, "photography_live_decide_unavailable")

    def select_song(self):
        """Touch the requested song in the Live photography song list.

        The list is scrolled along its observed axis; at an unchanged end it
        reverses once. Every song label seen is reported.
        """
        pattern = re.escape(self.args.song_label)
        seen = self.report.setdefault("photography_song_labels_seen", [])
        state = {"swipes": 0, "direction": 1, "reversals": 0, "last": None, "list_seen_at": None}
        def attempt():
            snap = self.route_snapshot()
            if snap is None:
                return None
            candidates = [b for b in self.ui.buttons(snap) if "PhotographyTopScreen" not in b["path"]]
            found = [b for b in candidates if re.search(pattern, b["label"], re.I)]
            if len(found) == 1:
                return True if self.route_touch(snap, found[0], "qa_mv_song",
                                                {"label": found[0]["label"], "swipes": state["swipes"]}) else None
            cells = [b for b in candidates if MUSIC_CELL_PATH.search(b["path"]) and b["label"]]
            for cell in cells:
                if cell["label"] not in seen and len(seen) < 200:
                    seen.append(cell["label"][:128])
            if not cells:
                return None
            now = time.monotonic()
            if state["list_seen_at"] is None:
                state["list_seen_at"] = now
            if now - state["list_seen_at"] < 3:
                return None  # let the list finish its open animation first
            signature = tuple(sorted((c["label"], tuple(c["bounds"])) for c in cells))
            if signature == state["last"]:
                if state["reversals"] >= 1:
                    raise Rejected("requested_song_not_in_photography_list")
                state["reversals"] += 1
                state["direction"] = -state["direction"]
            state["last"] = signature
            if state["swipes"] >= SONG_SWIPE_LIMIT:
                raise Rejected("requested_song_not_in_photography_list")
            self.unity_list_swipe(snap, cells, state["direction"])
            state["swipes"] += 1
            return None
        self.wait(attempt, 300, "photography_song_list_unavailable")

    def live_song_decide_and_view(self):
        """Song list Decide, then the confirmation sheet's watch control.

        If Decide did not open the sheet within 15 s, one stage is chosen
        (when a stage list is shown) and Decide is touched again.
        """
        state = {"decides": 0, "at": 0.0, "stages": 0}
        def attempt():
            snap = self.route_snapshot()
            if snap is None:
                return None
            now = time.monotonic()
            if state["decides"]:
                view = choose_route_button(self.ui, snap, VIEW_LABEL, VIEW_NAME, prefer=OVERLAY_PATH)
                if view is not None:
                    return True if self.route_touch(snap, view, "qa_mv_view", {"label": view["label"]}) else None
                if now - state["at"] < 15:
                    return None
                if state["stages"] < 1:
                    stages = [b for b in self.ui.buttons(snap) if "PhotographyTopScreen" not in b["path"]
                              and STAGE_CELL_PATH.search(b["path"])]
                    if stages:
                        stage = min(stages, key=lambda b: (b["bounds"][1], b["bounds"][0]))
                        if self.route_touch(snap, stage, "qa_mv_stage", {"label": stage["label"]}):
                            state["stages"] += 1
                            state["at"] = now - 12  # Decide again shortly after
                        return None
                if state["decides"] >= 3:
                    return None
            decide = choose_route_button(self.ui, snap, DECIDE_LABEL, DECIDE_NAME,
                                         exclude=("PhotographyTopScreen",), prefer=OVERLAY_PATH)
            if decide is not None and self.route_touch(snap, decide, "qa_mv_song_decided", {"label": decide["label"]}):
                state["decides"] += 1
                state["at"] = now
            return None
        self.wait(attempt, 180, "photography_confirm_view_unavailable")

    def unity_list_swipe(self, snap, cells, direction):
        """Swipe inside the observed list cells, along their spread axis."""
        left = min(c["bounds"][0] for c in cells)
        top = min(c["bounds"][1] for c in cells)
        right = max(c["bounds"][2] for c in cells)
        bottom = max(c["bounds"][3] for c in cells)
        xs = [(c["bounds"][0] + c["bounds"][2]) / 2 for c in cells]
        ys = [(c["bounds"][1] + c["bounds"][3]) / 2 for c in cells]
        horizontal = max(xs) - min(xs) > max(ys) - min(ys)
        cx, cy = (left + right) / 2, (top + bottom) / 2
        if horizontal:
            a, b = (left + (right - left) * 0.8, cy), (left + (right - left) * 0.2, cy)
        else:
            a, b = (cx, top + (bottom - top) * 0.8), (cx, top + (bottom - top) * 0.2)
        if direction < 0:
            a, b = b, a
        raw = self.device.adb("exec-out", "screencap", "-p", binary=True)
        need(raw[:8] == b"\x89PNG\r\n\x1a\n", "display_capture_unavailable")
        size = struct.unpack_from(">II", raw, 16)
        xml = self.device.adb("exec-out", "uiautomator", "dump", "/dev/tty")
        begin, end = xml.find("<hierarchy"), xml.rfind("</hierarchy>")
        need(begin >= 0 and end >= begin, "android_ui_tree_unavailable")
        xml = xml[begin:end + len("</hierarchy>")]
        try:
            points = [self.ui.mapped_point(snap, {"bounds": [x - 1, y - 1, x + 1, y + 1]}, xml, PACKAGE, size)
                      for x, y in (a, b)]
        except ValueError:
            raise Rejected("photography_list_swipe_unmapped") from None
        self.device.adb("shell", "input", "touchscreen", "swipe", str(points[0][0]), str(points[0][1]),
                        str(points[1][0]), str(points[1][1]), "600")
        self.record("qa_mv_song_list_swipe", {"horizontal": horizontal, "direction": direction})

    def handle_dialog(self, snap):
        # The game's own first-start Terms of Service sheet: its agree checkbox is
        # pre-checked in the observed UI and its Agree action stays interactable.
        terms = terms_agree_target(snap)
        if terms is not None:
            self.dialog_touch(snap, terms, "observed_terms_agree")
            return True
        for function, role in ((self.ui.notice_close_target, "observed_notice_close"),
                               (self.ui.manager_level_close_target, "observed_manager_level_close"),
                               (self.ui.lesson_reward_close_target, "observed_lesson_reward_close"),
                               (self.ui.download_confirmation, "observed_resource_download_confirmation")):
            node = function(snap)
            if node:
                self.dialog_touch(snap, node, role)
                return True
        return False

    def dialog_touch(self, snap, node, role):
        """Touch a recognised dialog control; a closed dialog is not a failure.

        The explorer re-reads Unity before touching and refuses a control that
        is no longer current, e.g. a sheet the previous touch already accepted
        (run 6: the download sheet closed into the loading screen). The wait
        loop then re-observes instead of ending the run on a stale snapshot.
        """
        if self.explorer._tap(snap, node, role, len(self.journal)):
            self.record(role)
        else:
            self.record(role + "_input_skipped")

    def launch(self):
        self.report["target"] = self.device.identity()
        need(not self.device.adb("shell", "pm", "path", PACKAGE, check=False).strip(), "fresh_disposable_install_required")
        self.device.adb("install", str(self.args.apk), timeout=GUESTS[self.guest()]["install_timeout"])
        if self.guest() == REDROID_GUEST:
            self.grant_redroid_notification_permission()
        # The preceding environment probe is our own disposable QA app. End
        # its Activity so a stale probe window cannot be mistaken for a game UI.
        self.device.adb("shell", "am", "force-stop", ENVIRONMENT_PROBE)
        self.record("unified_launcher_start_requested")
        before=self.device.adb("shell","pidof",PACKAGE,check=False).split()
        self.pre_launch_pids=[int(pid)for pid in before if pid.isdigit()][:8]
        started = self.device.adb("shell", "am", "start", "-W", "-a", "android.intent.action.MAIN",
                                  "-c", "android.intent.category.LAUNCHER", "-n", MAIN,
                                  timeout=120, merge_error=True)
        (self.proof / "launcher-start.txt").write_text(started[:16384])
        try:
            launch_context=self.capture_launch_evidence("initial")
        except (Rejected,OSError,subprocess.SubprocessError):
            self.report["initial_launch_context_collection_unavailable"]=True
            launch_context=""
        interrupted = verified_activity_start(started, notification_interruption=True)
        self.record("unified_launcher_notification_interruption_reported" if interrupted
                    else "unified_launcher_start_reported")
        factory="\n".join(line for line in launch_context.splitlines()if"IdolyLauncher"in line)
        (self.proof / "launcher-constructor.txt").write_text(factory[-16384:])
        starts = self.device.adb("logcat", "-b", "system", "-d", "-t", "5000", "-v", "brief", "-s", "ActivityTaskManager", check=False)
        (self.proof / "initial-own-activity-launch-log.txt").write_text("\n".join(line for line in starts.splitlines() if PACKAGE in line)[-65536:])
        # The exact launcher control is source-localized; no startup RPC is
        # injected into the game (the optional fixture below precedes Launch).
        def launcher_control():
            tree = self.device.android()
            activities = self.device.adb("shell", "dumpsys", "activity", "activities", check=False)
            need(len(activities) <= 2 * 1024 * 1024, "foreground_activity_context_invalid")
            (self.proof / "launcher-activity-context.txt").write_text(activities[:65536])
            permission = notification_permission_control(tree, activities)
            if permission is not None:
                # Use only observed UI bounds. Never pm-grant/appops a permission
                # or accept another runtime group merely because it has Allow.
                (self.proof / "notification-permission-activity.txt").write_text(activities[:65536])
                (self.proof / "notification-permission-ui.xml").write_text(ET.tostring(tree, encoding="unicode"))
                self.device.touch(permission)
                self.record("fresh_qa_notification_permission_allowed", {
                    "permission": "android.permission.POST_NOTIFICATIONS", "target_package": PACKAGE,
                    "foreground_activity": "/".join(foreground_activity(activities)[1])})
                return None
            lifecycle = self.device.adb("shell", "run-as", PACKAGE, "cat", "files/idoly-qa-lifecycle.txt", check=False)
            need(len(lifecycle) <= 16384, "unified_launcher_lifecycle_invalid")
            (self.proof / "launcher-main-lifecycle.txt").write_text(lifecycle)
            return launcher_main_control(tree, activities, lifecycle)
        launch = self.wait(launcher_control, 120, "unified_launch_control_unavailable")
        # The unified app launches the game only while its resource server runs
        # (MainActivity.prepareUnifiedClient); otherwise Launch only shows the
        # "Start the server first" toast. Start it through the real UI control.
        # QA ONLY, explicit option: the server's own "Viewing mode · Unlock all"
        # switch must be set before the server starts (it selects the profile
        # store). A fresh post-tutorial profile has Photography locked (run 8).
        if getattr(self.args, "viewing_mode", False) is True:
            self.enable_viewing_mode()
        started = self.start_embedded_server()
        # QA ONLY, explicit option: the fixture needs the running server and must
        # exist before the game's own first login, so it runs before Launch,
        # also when the server was already running.
        prepared = getattr(self.args, "prepare_completed_opening", False) is True
        if prepared:
            self.prepare_completed_opening_fixture()
        if started or prepared:
            launch = self.wait(launcher_control, 120, "unified_launch_control_unavailable")
        self.report["launcher_main_verified"] = True
        self.record("unified_launcher_start_accepted", {"requested_component": MAIN,
                    "foreground_main_and_observed_control": True, "main_lifecycle_resumed": True})
        self.device.touch(launch)
        self.explorer = self.ui.UiExplorer(self.device)
        title_taps = []
        def title_or_home():
            snapshot = self.explorer._snapshot()
            if snapshot.get("ok") is not True:
                return None
            if self.handle_dialog(snapshot):
                return None
            if self.ui._home_role(snapshot, "idols"):
                # Home's controls exist while LoadingManager still blocks input
                # (run 7); Home counts only once the game releases it.
                return True if not home_input_blocked(snapshot) else None
            title = [n for n in self.ui.buttons(snapshot) if n.get("path") == "Canvas/TitleButton"]
            if len(title) == 1 and self.ui.title_block_reason(snapshot, title[0]) is None:
                # A tap during the title fade-in is ignored by the game; while
                # the same title stays up, tap it again at a bounded interval.
                now = time.monotonic()
                if not title_taps or (now - title_taps[-1] >= TITLE_RETAP_SECONDS and len(title_taps) < TITLE_TAP_LIMIT):
                    self.unity_touch(snapshot, title[0], "observed_title" if not title_taps else "observed_title_retap")
                    title_taps.append(now)
            return None
        self.wait(title_or_home, self.args.startup_timeout, "usable_home_not_observed")
        self.report["game_boot_verified"] = True

    def enable_viewing_mode(self):
        """Check the Main UI's own Viewing mode checkbox (Server tab) before Start."""
        tab = self.device.android_control({"idoly.nav.server"}, scroll=False)
        need(tab is not None, "viewing_mode_server_tab_unavailable")
        self.device.touch(tab)

        def checkbox():
            nodes = [node for node in self.device.android().iter("node") if node.get("package") == PACKAGE
                     and node.get("content-desc") == "idoly.options.media-mode" and node.get("enabled") == "true"]
            need(len(nodes) <= 1, "viewing_mode_control_ambiguous")
            return nodes[0] if nodes else None
        # ElementTree nodes without children are falsy: compare with None.
        box = checkbox()
        if box is None:
            box = self.device.android_control({"idoly.options.media-mode"})
        if box.get("checked") != "true":
            self.device.touch(box)

        def enabled():
            current = checkbox()
            return True if current is not None and current.get("checked") == "true" else None
        self.wait(enabled, 30, "viewing_mode_not_enabled")
        self.device.screenshot("viewing-mode-enabled")
        self.record("viewing_mode_enabled", {"control": "idoly.options.media-mode", "qa_only": True})

    def start_embedded_server(self):
        """Start the unified app's resource server with its own Start control.

        Returns True when a start was requested (the caller re-reads the Main
        UI), False when it was already running. Only observed UI controls are
        used; a storage-choice dialog is answered with app-private storage.
        """
        running, failed = labels("status_running"), labels("status_failed")
        start_names, private = labels("start_server"), labels("resource_storage_use_private")
        def texts(tree):
            return [node.get("text") or "" for node in tree.iter("node") if node.get("package") == PACKAGE]
        def is_running(values):
            return any(value == name or value.startswith(name + " ") for value in values for name in running)
        tree = self.device.android()
        if is_running(texts(tree)):
            self.record("embedded_server_already_running")
            return False
        controls = [node for node in tree.iter("node") if node.get("package") == PACKAGE
                    and node.get("class") == "android.widget.Button" and node.get("enabled") == "true"
                    and node.get("clickable") == "true" and node.get("text") in start_names]
        need(len(controls) == 1, "embedded_server_start_control_unavailable")
        self.device.touch(controls[0])
        self.record("embedded_server_start_requested")
        def server_running():
            current = self.device.android()
            values = texts(current)
            need(not any(value in failed for value in values), "embedded_server_start_failed")
            choice = [node for node in current.iter("node") if node.get("text") in private
                      and node.get("clickable") == "true" and node.get("enabled") == "true"]
            if choice:
                self.device.touch(choice[0])
                self.record("embedded_server_private_storage_selected")
                return None
            return True if is_running(values) else None
        self.wait(server_running, 600, "embedded_server_not_running")
        self.device.screenshot("embedded-server-running")
        self.record("embedded_server_running")
        return True

    def prepare_completed_opening_fixture(self):
        """QA ONLY: qa_game_boot's completed-opening profile, after Running, before Launch.

        The embedded server keeps one local profile. qa_game_boot's verified
        Auth.Login, Tutorial.Init(QAManager) and tutorial continuation prepare
        it, so the game's own first login lands after the opening tutorial.
        This is setup, never evidence that the game played the tutorial. Only
        method/status rows are written; the local session token never leaves
        the fixture call. Nothing is retried: the continuation refuses a
        partially progressed profile, so any failure stops the run.
        """
        self.record("profile_fixture_requested", {"kind": "completed_opening", "qa_only": True,
                                                  "server_port": FIXTURE_SERVER_PORT})
        stage, boot, port = "load", None, None
        try:
            boot = load_fixture_boot()
            stage = "descriptor_set"
            schema = boot.Schema.from_descriptor_set(Path(self.args.descriptor_set))
            stage = "forward"
            port = self.device.forward(FIXTURE_SERVER_PORT)
            stage = "server_wait"
            boot.wait_server(schema, port, timeout=FIXTURE_SERVER_TIMEOUT)
            stage = "prepare"
            fixture = boot.prepare_completed_opening(schema, port, Path(self.args.master_dir),
                                                     timeout=FIXTURE_RPC_TIMEOUT)
            stage = "record"
            document, text = completed_opening_document(fixture)
            (self.proof / "profile-fixture.json").write_text(text)
        except Exception as error:  # Every cause, also RpcError/RuntimeError, is a named stop.
            code = fixture_failure_code(stage, error, boot)
            failure = {"enabled": True, "qa_only": True, "status": "failed", "failure_code": code,
                       "actual_game_tutorial_played": False}
            check = fixture_failed_check(error)
            if check:
                failure["failed_check"] = check
            self.report["profile_fixture"] = failure
            self.record(code)
            raise Rejected(code) from None
        finally:
            if port is not None:
                try:
                    self.device.adb("forward", "--remove", "tcp:" + str(port), check=False)
                except (OSError, subprocess.SubprocessError):
                    self.report["profile_fixture_forward_removal_unavailable"] = True
        self.report["profile_fixture"] = document
        self.record("profile_fixture_ready", {
            "rpc_methods": [row["method"] for row in document["rpc_calls"]],
            "completed_tutorial_step": 150, "tutorial_cleared": True,
            "actual_game_tutorial_played": False, "gameplay_evidence": False})
        return document

    def grant_redroid_notification_permission(self):
        """redroid only: pre-grant the app's own runtime notification permission.

        The observed-dialog path below stays available if the grant does not
        take effect; the translated guest never uses pm grant.
        """
        result = self.device.adb("shell", "pm", "grant", PACKAGE, NOTIFICATION_PERMISSION,
                                 check=False, merge_error=True)
        granted = notification_permission_granted(self.device.adb("shell", "dumpsys", "package", PACKAGE, check=False))
        self.report["notification_permission_pregranted_via_adb"] = granted
        self.record("redroid_notification_permission_pregranted" if granted
                    else "redroid_notification_permission_pregrant_unverified",
                    {"permission": NOTIFICATION_PERMISSION, "target_package": PACKAGE,
                     "pm_grant_output": result.strip()[:512]})
        return granted

    def open_mv(self):
        def idols():
            snap = self.explorer._snapshot()
            if snap.get("ok") is not True or self.handle_dialog(snap) or home_input_blocked(snap):
                return None
            node = self.ui._home_role(snap, "idols")
            if node is None:
                return None
            if self.explorer._tap(snap, node, "route_idols", len(self.journal)):
                self.record("route_idols")
                return True
            return None
        self.wait(idols, 600, "home_character_page_control_unavailable")
        self.route(r"撮影\s*[・·･]\s*鑑賞|촬영\s*[・·･]\s*감상|Shooting.*Viewing|Photography", r"^(Photography|PhotoButton)$")
        self.route(r"ライブ|라이브|Live", r"^Live(Tab|Button)?$")
        # Live page -> "match the stage song" -> Decide -> song list -> Decide
        # -> confirmation sheet -> watch (run 9: the Live tab opens idol
        # selection, not a song list).
        self.live_members_decide()
        self.select_song()
        self.live_song_decide_and_view()
        self.route(r"画面回転|화면\s*회전|Rotate\s*(screen)?", r"^Rotate(Button)?$", optional=True)
        def scene_ready():
            try:
                payload = self.mp4()
                state, obs = native_payload(payload)
                return payload if obs["source_kind"] == "photography_3d" else None
            except (Rejected, ValueError, OSError):
                return None
        first = self.wait(scene_ready, 600, "actual_normal_3d_mv_not_observed")
        self.device.screenshot("real-mv-playing")
        def playing_again():
            second = self.mp4()
            try:
                validate_playing_source(first, second)
                return second
            except Rejected:
                return None
        baseline = self.wait(playing_again, 30, "real_mv_playback_not_verified")
        self.record("real_mv_playing", baseline)
        self.report["actual_mv_verified"] = True
        return baseline

    def server_menu(self):
        tree = self.device.android()
        surfaces = [n for n in tree.iter("node") if n.get("package") == PACKAGE
                    and n.get("resource-id", "").endswith(":id/unitySurfaceView")]
        need(len(surfaces) == 1, "current_unity_surface_unavailable_for_menu")
        left, top, right, bottom = map(int, re.findall(r"\d+", surfaces[0].get("bounds", "")))
        x, y = right - 8, top + 8
        need(left <= x < right and top <= y < bottom, "menu_hold_bounds_invalid")
        self.device.adb("shell", "input", "touchscreen", "swipe", str(x), str(y), str(x), str(y), "2300")
        self.record("normal_hot_corner_menu_hold")
        # Source tab labels are translated independently of game language.
        tab = self.device.android_control({"그래픽", "グラフィック", "Graphics"}, cls="android.widget.Button")
        self.device.touch(tab)

    def configure_options(self):
        self.device.spinner("mp4_fps", str(self.args.fps))
        self.device.spinner("mp4_codec", "H.264")
        # Keep a full normal song within the small evidence transport bound;
        # set this through the actual autosaving UI rather than depending on a
        # changing default/recommendation or altering the encoder out of band.
        self.device.spinner("mp4_bitrate", labels("mp4_custom"))
        self.device.number("mp4_bitrate_mbps", 0.5)
        self.device.spinner("mp4_output_resolution", labels("mp4_custom"))
        self.device.number("mp4_width_pixels", self.args.width)
        self.device.number("mp4_height_pixels", self.args.height)

    def configure_and_start(self):
        self.configure_options()
        self.device.press_resource("mp4_queue_immediate")
        self.record("normal_direct_export_button_pressed")

    def enqueue_and_start(self):
        self.configure_options()
        self.device.press_resource("mp4_queue_add")
        def enqueued():
            payload = self.mp4()
            queue = payload.get("queue", {})
            need(queue.get("error_code") in ("none", "queue_not_configured"), "queue_enqueue_failed")
            if queue.get("command_pending") is False and queue.get("job_count") == 1:
                need(queue.get("available") is True and queue.get("running") is False,
                     "queue_snapshot_invalid")
                return payload
            return None
        queued = self.wait(enqueued, 120, "queue_entry_not_observed")
        # Adding is deliberately checked before any export-side handoff. The
        # server control must remain on screen; an Activity switch is a failure.
        need(self.device.android_control(labels("mp4_queue_run"), cls="android.widget.Button", scroll=False)
             is not None, "server_menu_lost_after_enqueue")
        self.record("current_mv_queued_without_hiding_menu", queued)
        self.report["queue_entry_verified_without_menu_handoff"] = True
        self.device.press_resource("mp4_queue_run")
        self.record("normal_queue_export_button_pressed")

    def foreground_export_control(self, name):
        tree = self.device.android()
        surfaces = [n for n in tree.iter("node") if n.get("package") == PACKAGE
                    and n.get("resource-id", "").endswith(":id/unitySurfaceView")]
        need(len(surfaces) == 1, "unity_surface_not_foreground_for_export_pause")
        names = labels(name)
        controls = [n for n in tree.iter("node") if n.get("package") == PACKAGE
                    and n.get("class") == "android.widget.Button" and n.get("enabled") == "true"
                    and (n.get("text") in names or n.get("content-desc") in names)]
        need(len(controls) == 1, "native_export_overlay_control_unavailable")
        self.device.touch(controls[0])

    def exercise_export_pause(self):
        # Exercise the shipping native overlay, keeping Unity's Activity and
        # PlayerLoop alive. Opening the server Activity would test a different
        # lifecycle pause and cannot qualify this gate.
        self.foreground_export_control("mp4_pause")
        self.record("actual_export_overlay_pause_pressed")
        def acknowledged():
            payload = self.mp4()
            state, _ = native_payload(payload)
            need(state.get("phase") not in ("failed", "cancelled", "completed"), "export_ended_before_pause_gate")
            return payload if state.get("phase") == "paused" and state.get("paused") is True else None
        first = self.wait(acknowledged, 60, "actual_export_pause_not_acknowledged")
        def loop_advanced_while_held():
            payload = self.mp4()
            try:
                validate_export_pause(first, payload)
                return payload
            except Rejected:
                return None
        second = self.wait(loop_advanced_while_held, 60, "export_pause_did_not_hold_native_clock_with_live_loop")
        self.device.screenshot("actual-export-pause-live-unity")
        self.record("export_clock_held_while_playerloop_advances", {"first": first, "second": second})
        self.foreground_export_control("mp4_resume")
        _, paused = native_payload(second)
        def resumed():
            payload = self.mp4()
            state, observed = native_payload(payload)
            need(state.get("phase") not in ("failed", "cancelled"), "export_resume_failed")
            if state.get("phase") in ("rendering", "finishing"):
                validate_running(payload)
                if observed.get("simulation_tick") is not None and observed["simulation_tick"] > paused["simulation_tick"]:
                    return payload
            return None
        resumed_payload = self.wait(resumed, 120, "actual_export_resume_did_not_advance_owned_clock")
        self.record("actual_export_overlay_resumed", resumed_payload)
        self.report["native_clock_hold_with_advancing_playerloop_verified"] = True
        self.report["native_overlay_pause_resume_verified"] = True

    def await_export(self, baseline, replay=False):
        deadline, previous_tick, observed_running, last_record = self.export_deadline, None, False, 0
        acquired = False
        self.report["native_overlay_pause_resume_verified"] = False
        self.report["native_clock_hold_with_advancing_playerloop_verified"] = False
        while time.monotonic() < deadline:
            payload = self.mp4()
            state, obs = native_payload(payload)
            phase = state.get("phase")
            if phase == "completed":
                self.capture_mp4_diagnostics("completed", force=True)
                need(observed_running, "no_actual_native_render_progress_observed")
                need(acquired, "native_export_acquisition_baseline_unavailable")
                need(self.report.get("native_clock_hold_with_advancing_playerloop_verified") is True,
                     "independent_clock_hold_not_verified")
                validate_completed(baseline, payload, self.args.width, self.args.height, self.args.fps)
                self.record("native_export_completed_and_restored", payload)
                return payload, baseline
            need(phase not in ("failed", "cancelled"), "native_export_failed_" + str(state.get("error_code", "unknown")))
            if phase in ("rendering", "finishing"):
                previous_tick = validate_running(payload, previous_tick)
                observed_running = True
                if not acquired and phase == "rendering":
                    baseline = export_acquisition_baseline(baseline, payload, replay=replay)
                    self.record("native_queue_replay_acquisition_baseline" if replay
                                else "native_direct_acquisition_baseline", payload)
                    acquired = True
                if phase == "rendering" and obs["accepted_frames"] >= 2 and not self.report.get("native_overlay_pause_resume_verified"):
                    self.exercise_export_pause()
            if time.monotonic() - last_record >= 20:
                self.record("export_progress", payload)
                last_record = time.monotonic()
                self.capture_mp4_diagnostics("export_progress", force=True)
            need(bool(self.device.adb("shell", "pidof", PACKAGE, check=False).strip()), "game_process_exited")
            self.relieve_system_anr()
            time.sleep(.25)
        raise Rejected("actual_full_export_timeout")

    def retrieve_and_decode(self, payload, label):
        state, _ = native_payload(payload)
        identifier = state["export_id"]
        raw = self.device.adb("exec-out", "run-as", PACKAGE, "find", "files", "-type", "f", "-name", identifier + ".mp4")
        paths = raw.splitlines()
        need(len(paths) == 1, "completed_private_source_not_unique")
        path = PurePosixPath(paths[0])
        need(path.parts[0] == "files" and all(p not in (".", "..") for p in path.parts)
             and path.name == identifier + ".mp4" and path.parent.name == "exports"
             and re.fullmatch(r"\.idoly-mp4-(?:library|audio-[0-9a-f]{32})", path.parent.parent.name),
             "completed_private_source_path_invalid")
        size = self.device.adb("exec-out", "run-as", PACKAGE, "stat", "-c", "%s", str(path)).strip()
        need(size.isdigit() and 1 <= int(size) <= MAX_MOVIE, "bounded_movie_evidence_size_required")
        folder = self.proof.parent / "video"
        folder.mkdir(exist_ok=True)
        movie = folder / (label + "-actual-game.mp4")
        with movie.open("xb") as output:
            result = subprocess.run(self.device.base + ["exec-out", "run-as", PACKAGE, "cat", str(path)], stdout=output,
                                    stderr=subprocess.PIPE, timeout=120)
        need(result.returncode == 0 and movie.stat().st_size == int(size), "completed_movie_transfer_failed")
        expected = reported_digest(self.device.adb("exec-out", "run-as", PACKAGE, "sha256sum", str(path)),
                                   "completed_movie_digest_unavailable")
        need(sha(movie) == expected, "completed_movie_hash_differs")
        probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_packets",
                                "-show_entries", "stream=index,codec_type,codec_name,width,height,avg_frame_rate,nb_read_frames,sample_rate,channels,duration,time_base:packet=codec_type,pts",
                                "-of", "json", str(movie)], capture_output=True, timeout=180)
        need(probe.returncode == 0 and len(probe.stdout) <= 16 * 1024 * 1024, "movie_probe_failed")
        summary = validate_probe(json.loads(probe.stdout), state)
        decoded = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(movie),
                                  "-f", "null", "-"], capture_output=True, timeout=180)
        need(decoded.returncode == 0 and not decoded.stderr.strip(), "full_movie_decode_failed")
        # Audio evidence is actual decoded PCM; never a generated reference signal.
        sound = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(movie), "-vn", "-ac", "2",
                                "-ar", "48000", "-f", "f32le", "-"], capture_output=True, timeout=180)
        need(sound.returncode == 0 and 8 <= len(sound.stdout) <= 512 * 1024 * 1024, "decoded_audio_unavailable")
        energy = sum(v[0] * v[0] for v in struct.iter_unpack("<f", sound.stdout)) / (len(sound.stdout) // 4)
        need(math.isfinite(energy) and energy > 1e-12, "decoded_audio_silent_or_nonfinite")
        samples = []
        for index, fraction in enumerate((0, .25, .5, .75, .98)):
            position = (state["total_frames"] - 1) / self.args.fps * fraction
            image = self.proof / (label + "-actual-frame-%d.png" % index)
            sample = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(position), "-i", str(movie),
                                     "-frames:v", "1", str(image)], capture_output=True, timeout=60)
            need(sample.returncode == 0 and image.is_file(), "decoded_visual_sample_failed")
            samples.append(sha(image))
        need(len(set(samples)) >= 2, "movie_frames_are_frozen")
        self.report.setdefault("videos", {})[label] = {**summary, "bytes": movie.stat().st_size, "sha256": expected,
                                                       "decoded_audio_mean_square": energy, "sample_sha256": samples}
        self.report["export_file_verified"] = True
        self.report["restoration_verified"] = True
        return str(path), expected

    def save_cancel(self, path, expected):
        self.device.press_resource("mp4_save")
        def documents():
            tree = self.device.android()
            return tree if any(n.get("package") in ("com.google.android.documentsui", "com.android.documentsui")
                               for n in tree.iter("node")) else None
        self.wait(documents, 40, "actual_documentsui_not_observed")
        self.device.screenshot("actual-save-picker-before-cancel")
        self.device.adb("shell", "input", "keyevent", "KEYCODE_BACK")
        self.wait(lambda: self.device.android_control(labels("mp4_save"), cls="android.widget.Button", scroll=False),
                  40, "save_button_lost_after_picker_cancel")
        actual = reported_digest(self.device.adb("exec-out", "run-as", PACKAGE, "sha256sum", path),
                                 "completed_movie_digest_unavailable")
        need(actual == expected, "completed_movie_lost_after_picker_cancel")
        self.report["save_cancel_preserved_source_and_button"] = True

    def save_completed(self, path, expected, identifier):
        self.device.press_resource("mp4_save")
        def save_control():
            tree = self.device.android()
            nodes = [n for n in tree.iter("node") if n.get("package") in
                     ("com.google.android.documentsui", "com.android.documentsui")
                     and n.get("enabled") == "true"
                     and (n.get("resource-id", "").endswith(":id/action_menu_save")
                          or n.get("class") == "android.widget.Button"
                          and n.get("text") in ("SAVE", "Save", "저장", "保存"))]
            need(len(nodes) <= 1, "documentsui_save_control_ambiguous")
            return nodes[0] if nodes else None
        button = self.wait(save_control, 40, "actual_documentsui_save_control_unavailable")
        self.device.screenshot("actual-save-picker-confirm")
        self.device.touch(button)
        filename = "IdolyPride-MV-" + identifier + ".mp4"
        # The picker chooses the default public Downloads location on this
        # fresh emulator. The exact completed ID bounds the file readback.
        def saved():
            output = self.device.adb("shell", "find", "/sdcard/Download", "-maxdepth", "1", "-type", "f",
                "-name", filename, check=False).splitlines()
            if not output:
                return None
            need(output == ["/sdcard/Download/" + filename], "public_saved_movie_path_differs")
            actual = reported_digest(self.device.adb("shell", "sha256sum", output[0]), "saved_movie_digest_unavailable")
            need(actual == expected, "public_saved_movie_hash_differs")
            return output[0]
        self.wait(saved, 120, "public_saved_movie_not_verified")
        actual = reported_digest(self.device.adb("exec-out", "run-as", PACKAGE, "sha256sum", path),
                                 "completed_movie_digest_unavailable")
        need(actual == expected, "private_completed_movie_lost_after_save")
        self.report["actual_documentsui_save_verified"] = {"filename": filename, "sha256": expected,
                                                            "location": "public_Download"}
        self.record("actual_save_completed_and_hash_verified")

    def save_steps(self, path, expected, identifier):
        """The unchanged cancel/save gates, or a distinct redroid-only blocked verdict.

        A guest image without any DocumentsUI cannot show the system picker. That
        is recorded separately from the already completed export/decode verdict
        and never counts as a pass.
        """
        if self.guest() == REDROID_GUEST:
            installed = [name for name in DOCUMENTSUI_PACKAGES
                         if self.device.adb("shell", "pm", "path", name, check=False).strip()]
            if not installed:
                self.report["save_verdict"] = {"status": "BLOCKED", "code": SAVE_BLOCKED_DOCUMENTSUI,
                                               "documentsui_packages": []}
                self.record(SAVE_BLOCKED_DOCUMENTSUI)
                return False
        self.save_cancel(path, expected)
        self.save_completed(path, expected, identifier)
        self.report["save_verdict"] = {"status": "VERIFIED"}
        return True

    def run(self):
        try:
            need(HEX40.fullmatch(self.args.source_commit), "exact_source_commit_required")
            need(subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
                 == self.args.source_commit, "runtime_source_checkout_differs")
            evidence = json.loads(self.args.qa_evidence.read_bytes())
            verified_observer_manifest(evidence)
            marker = evidence.get("qa_ui", {})
            need(evidence.get("input_profile") == "unified-current" and evidence.get("qa_only") is True
                 and evidence.get("software_aes_and_no_store_input") is False
                 and evidence.get("all_existing_members_preserved_except_manifest_and_signatures") is True
                 and marker.get("source_commit") == self.args.source_commit
                 and evidence.get("output_apk_sha256") == sha(self.args.apk), "qa_current_source_identity_differs")
            self.launch()
            baseline = self.open_mv()
            self.server_menu()
            self.export_deadline = time.monotonic() + self.args.export_timeout
            self.configure_and_start()
            final, baseline = self.await_export(baseline)
            path, digest = self.retrieve_and_decode(final, "direct")
            saved = self.save_steps(path, digest, final["native"]["export_id"])
            self.report["direct_playing_source_export_and_restore_verified"] = True
            if self.args.queue_replay:
                before_queue = self.mp4()
                validate_restored(baseline, before_queue)
                self.server_menu()
                self.enqueue_and_start()
                queued_final, _ = self.await_export(before_queue, replay=True)
                self.retrieve_and_decode(queued_final, "queue")
                self.report["queue_replay_export_and_acquired_source_restore_verified"] = True
            if saved:
                self.report["status"] = GUESTS[self.guest()]["status"]
            else:
                # Export/decode passed independently; the Save gate could not run.
                self.report["status"] = "EXPORT_VERIFIED_SAVE_BLOCKED"
                self.report["failure_stage"] = "save"
                self.report["failure_code"] = SAVE_BLOCKED_DOCUMENTSUI
        except (Rejected, OSError, ValueError, HTTPException, subprocess.SubprocessError) as error:
            self.report["status"] = "FAILED_OR_ENVIRONMENT_BLOCKED"
            self.report["failure_stage"] = self.journal[-1]["phase"] if self.journal else "input_or_target"
            self.report["failure_code"] = str(error)[:192] if isinstance(error, Rejected) else type(error).__name__
            self.capture_mp4_diagnostics("failure", force=True)
            try:
                self.device.android()
                self.device.screenshot("failure-display")
                if self.explorer:
                    (self.proof / "failure-unity.json").write_text(json.dumps(self.explorer._snapshot(), ensure_ascii=False))
            except (Rejected, OSError, ValueError, subprocess.SubprocessError):
                pass
        finally:
            # The app's own export trace, live and persisted, on every outcome.
            self.capture_mp4_diagnostics("final", force=True)
            self.capture_persisted_mp4_diagnostics()
            try:
                self.capture_launch_evidence("final")
            except (Rejected,OSError,subprocess.SubprocessError):
                self.report["launch_context_collection_unavailable"]=True
            try:
                activities = self.device.adb("shell", "dumpsys", "activity", "activities", check=False)
                resumed = [line.strip() for line in activities.splitlines()
                           if "mResumedActivity" in line or "topResumedActivity" in line]
                (self.proof / "foreground-activity.txt").write_text("\n".join(resumed)[:4096])
                lifecycle = self.device.adb("shell", "run-as", PACKAGE, "cat", "files/idoly-qa-lifecycle.txt", check=False)
                (self.proof / "own-activity-lifecycle.txt").write_text(lifecycle[:16384])
                starts = self.device.adb("logcat", "-b", "system", "-d", "-t", "5000", "-v", "brief", "-s", "ActivityTaskManager", check=False)
                own = [line for line in starts.splitlines() if PACKAGE in line]
                (self.proof / "own-activity-launch-log.txt").write_text("\n".join(own)[-65536:])
            except (Rejected, OSError, subprocess.SubprocessError):
                self.report["activity_collection_unavailable"] = True
            try:
                pids = self.device.adb("shell", "pidof", PACKAGE, check=False).split()
                if len(pids) == 1 and pids[0].isdigit():
                    logs = self.device.adb("logcat", "-d", "--pid=" + pids[0], check=False)
                    safe = [line for line in logs.splitlines() if not re.search(r"authorization|x-auth-token|password|id.?token", line, re.I)]
                    (self.proof / "own-pid-logcat.txt").write_text("\n".join(safe)[-2 * 1024 * 1024:])
            except (Rejected, OSError, subprocess.SubprocessError):
                self.report["log_collection_unavailable"] = True
            self.report["driver_sha256"] = sha(Path(__file__))
            self.report["collection_succeeded"] = True
            (self.proof / "runtime-report.json").write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + "\n")
        return self.report["status"].startswith("PASS_")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--qa-evidence", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--adb", type=Path, default=Path("adb"))
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--guest", choices=tuple(GUESTS), default=TRANSLATED_GUEST,
                        help="translated-emulator (default, official API35 ARM-translation emulator) or redroid "
                             "(native ARM64 container on a loopback adb serial; separate evidence scope)")
    parser.add_argument("--song-label", default="Bittersweet Echo")
    parser.add_argument("--fps", type=int, choices=(30, 60), default=30)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=144)
    parser.add_argument("--queue-replay", action="store_true", help="Also export the queued MV and gate its native acquired-source restoration")
    parser.add_argument("--startup-timeout", type=int, default=1800)
    parser.add_argument("--export-timeout", type=int, default=14400)
    parser.add_argument("--prepare-completed-opening", action="store_true",
                        help="QA ONLY: once the embedded server runs and before Launch, prepare qa_game_boot's "
                             "completed-opening profile through local RPCs (setup, never tutorial evidence)")
    parser.add_argument("--viewing-mode", action="store_true",
                        help="QA ONLY: check the server's own 'Viewing mode · Unlock all' before Start; it selects "
                             "the unlocked viewing profile store (tutorial cleared), so no fixture is needed")
    parser.add_argument("--descriptor-set", type=Path, help="server protocol descriptor set for the fixture")
    parser.add_argument("--master-dir", type=Path, help="server master-json directory for the fixture")
    args = parser.parse_args()
    need(16 <= args.width <= 4096 and 16 <= args.height <= 4096 and not args.width % 2 and not args.height % 2,
         "requested_render_geometry_invalid")
    need(1 <= len(args.song_label) <= 128 and not any(ord(c) < 32 for c in args.song_label), "song_label_invalid")
    need(1 <= args.startup_timeout <= 3600 and 1 <= args.export_timeout <= 18000, "driver_deadline_invalid")
    need(not (args.viewing_mode and args.prepare_completed_opening), "viewing_mode_and_fixture_are_exclusive")
    if args.prepare_completed_opening:
        need(args.descriptor_set is not None and args.descriptor_set.is_file() and args.master_dir is not None
             and all((args.master_dir / name).is_file() for name in FIXTURE_TABLES), "profile_fixture_inputs_required")
    else:
        need(args.descriptor_set is None and args.master_dir is None, "profile_fixture_inputs_without_option")
    raise SystemExit(0 if ActualRun(args).run() else 1)


if __name__ == "__main__":
    main()
