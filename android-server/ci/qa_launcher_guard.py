"""One bounded recovery for a verified disposable AVD's exact Pixel Launcher ANR.

Never dismisses the server's own ANR, an unknown dialog, or a non-system home.
No command executes on import; every input uses a fresh observed XML target.
"""
from __future__ import annotations
import json
import re

SERVER = "game.qualiarts.idolypride.localserver"
ACTIVITY = SERVER + "/.MainActivity"
LAUNCHER = "com.google.android.apps.nexuslauncher"
TITLE = "Pixel Launcher isn't responding"
CHECKPOINT = "before_initial_server_start"


def _bounds(node):
    value = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
    if value is not None:
        left, top, right, bottom = map(int, value.groups())
        if right > left and bottom > top:
            return left, top, right, bottom
    return None


def launcher_dialog(tree):
    nodes = list(tree.iter("node"))
    anr = [node for node in nodes if node.get("resource-id") in ("android:id/aerr_close", "android:id/aerr_wait")]
    if not anr:
        if any(node.get("resource-id") == "android:id/alertTitle" for node in nodes):
            raise RuntimeError("An unapproved dialog blocks native server QA")
        return None
    titles = [node for node in nodes if node.get("resource-id") == "android:id/alertTitle"]
    if (len(titles) != 1 or titles[0].get("text") != TITLE or titles[0].get("package") != "android"
            or len(anr) != 2 or {node.get("resource-id") for node in anr} != {"android:id/aerr_close", "android:id/aerr_wait"}
            or any(node.get("package") != "android" or node.get("enabled") != "true"
                   or node.get("clickable") != "true" or _bounds(node) is None for node in anr)):
        raise RuntimeError("An unapproved ANR blocks native server QA")
    return next(node for node in anr if node.get("resource-id") == "android:id/aerr_close")


def _verified_system_launcher(qa):
    resolved = qa.adb("shell", "cmd", "package", "resolve-activity", "--brief", "--user", "0",
                      "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME").splitlines()
    components = [line.strip() for line in resolved if re.fullmatch(re.escape(LAUNCHER)+r"/[A-Za-z0-9_.$]+", line.strip())]
    if len(components) != 1:
        raise RuntimeError("Pixel Launcher ANR target could not be verified")
    paths = qa.adb("shell", "pm", "path", "--user", "0", LAUNCHER).splitlines()
    if (len(paths) != 1 or re.fullmatch(r"package:/(?:system|system_ext|product)/priv-app/[A-Za-z0-9_./-]+\.apk", paths[0].strip()) is None):
        raise RuntimeError("Pixel Launcher ANR is not a verified system target")


def recover_initial_launcher(qa, target_evidence):
    if (type(target_evidence) is not dict or target_evidence.get("kind") != "android_emulator"
            or target_evidence.get("ro.kernel.qemu") != "1"):
        raise RuntimeError("Launcher recovery requires the verified disposable GitHub AVD")
    initial = qa.capture("00-launcher-before")
    close = launcher_dialog(initial)
    if close is None:
        return
    incidents = getattr(qa, "launcher_environment_incidents", [])
    qa.launcher_environment_incidents = incidents
    if incidents:
        incidents[0]["incident_count"] = 2
        (qa.artifacts / "00-launcher-incident.json").write_text(json.dumps(incidents[0], sort_keys=True), encoding="utf-8")
        raise RuntimeError("Pixel Launcher ANR recovery is limited to one attempt")
    incident = {"schema": 1, "incident_count": 1, "checkpoint": CHECKPOINT, "component": LAUNCHER,
                "dialog": "pixel_launcher_anr", "action": "close_launcher", "performed": False,
                "resolved": False, "before_xml": "00-launcher-before.xml",
                "confirm_xml": "00-launcher-confirm.xml", "after_xml": "00-launcher-after.xml"}
    incidents.append(incident)
    def persist():
        (qa.artifacts / "00-launcher-incident.json").write_text(json.dumps(incident, sort_keys=True), encoding="utf-8")
    try:
        persist()
        _verified_system_launcher(qa)
        confirmed = qa.capture("00-launcher-confirm")
        current = launcher_dialog(confirmed)
        if current is None or _bounds(current) != _bounds(close):
            raise RuntimeError("Pixel Launcher dialog changed before the observed input")
        left, top, right, bottom = _bounds(current)
        qa.adb("shell", "input", "tap", str((left+right)//2), str((top+bottom)//2))
        incident["performed"] = True
        qa.adb("shell", "am", "start", "-W", "-n", ACTIVITY)
        after = qa.capture("00-launcher-after")
        if launcher_dialog(after) is not None:
            raise RuntimeError("Pixel Launcher ANR remained after its one recovery attempt")
        if not any(node.get("package") == SERVER for node in after.iter("node")):
            raise RuntimeError("Actual native server UI was not observed after launcher recovery")
        incident["resolved"] = True
    finally:
        persist()
