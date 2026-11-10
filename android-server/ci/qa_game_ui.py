"""Explore a disposable game's real UI using its authenticated Unity tree.

The bridge only observes UI. Every input goes through Android's normal touch
dispatch using current Unity bounds and the current accessibility game view.
This driver never calls gameplay handlers, purchase APIs or native clicks.
"""
from __future__ import annotations

from http.client import HTTPConnection, HTTPException
import hashlib
import json
import math
import re
import struct
import time
import xml.etree.ElementTree as ET


_PACKAGE = "game.qualiarts.idolypride.local.diagnostics"
_MAX_BODY = 72 * 1024
_FORBIDDEN = re.compile(r"購入|課金|ガチャを引|データ削除|アカウント削除|buy|purchase|deleteaccount", re.I)
_ERROR = re.compile(r"Unimplemented|Unauthenticated|NullReferenceException|サーバーとの通信に失敗", re.I)
_GOALS = (
    ("lesson", r"レッスン", r"lesson.*button|button.*lesson"),
    ("live", r"ライブ", r"live.*button|button.*live"),
    ("idols", r"アイドル", r"idol.*button|button.*idol"),
    ("work", r"お仕事", r"work.*button|button.*work"),
    ("stories", r"ストーリー", r"story.*button|button.*story"),
    ("gifts", r"プレゼント", r"gift|present"),
)


def text(value):
    return " ".join(re.sub(r"<[^>]*>", "", str(value)).split())


def buttons(snapshot):
    result = []
    nodes = snapshot.get("nodes", [])
    if not isinstance(nodes, list) or len(nodes) > 512:
        raise ValueError("Invalid Unity UI node count")
    labels = [node for node in nodes if isinstance(node, dict) and node.get("kind") in ("text", "tmp_text") and node.get("active") is True]
    for node in nodes:
        if (not isinstance(node, dict) or node.get("kind") != "button"
                or node.get("active") is not True or node.get("interactable") is not True):
            continue
        path = node.get("path", "")
        if not isinstance(path, str) or not path:
            continue
        label = text(" ".join([str(node.get("text", "")), *(str(row.get("text", "")) for row in labels
                            if row.get("path") == path or str(row.get("path", "")).startswith(path + "/"))]))
        if _FORBIDDEN.search(label + " " + str(node.get("name", ""))):
            continue
        result.append(dict(node, label=label))
    return result


def choose_button(snapshot, label_pattern, name_pattern=None):
    candidates = buttons(snapshot)
    exact = [node for node in candidates if re.fullmatch(label_pattern, node["label"], re.I)]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None
    matched = [node for node in candidates if re.search(label_pattern, node["label"], re.I)]
    if len(matched) == 1:
        return matched[0]
    if name_pattern:
        named = [node for node in candidates if re.search(name_pattern, str(node.get("name", "")), re.I)]
        if len(named) == 1:
            return named[0]
    return None


def title_block_reason(snapshot, node):
    """Only known blocking observations suppress ordinary touch attempts."""
    if node.get("callback_registered") is False:
        return "title_callback_not_registered"
    startup = snapshot.get("startup_observation")
    if not isinstance(startup, dict):
        return None
    for field in ("input_releasing", "content_blocking"):
        if startup.get(field) is True:
            return field
    return None


def mapped_point(snapshot, node, xml, package, image_size):
    screen = snapshot.get("screen", {})
    width, height = screen.get("width"), screen.get("height")
    if (screen.get("origin") != "top-left" or screen.get("units") != "unity-screen-pixels"
            or type(width) is not int or type(height) is not int or not 64 <= width <= 8192 or not 64 <= height <= 8192):
        raise ValueError("Invalid Unity UI screen geometry")
    bounds = node.get("bounds")
    if (not isinstance(bounds, list) or len(bounds) != 4
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in bounds)):
        raise ValueError("The selected Unity button has no usable bounds")
    left, top, right, bottom = bounds
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError("Unity button bounds are outside its screen")
    views = []
    for item in ET.fromstring(xml).iter("node"):
        if item.get("package") == package and item.get("resource-id", "").endswith(":id/unitySurfaceView"):
            match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", item.get("bounds", ""))
            if match:
                views.append(tuple(map(int, match.groups())))
    if len(views) != 1:
        raise ValueError("A unique current Unity accessibility surface is required")
    x0, y0, x1, y1 = views[0]
    if not (0 <= x0 < x1 <= image_size[0] and 0 <= y0 < y1 <= image_size[1]):
        raise ValueError("Android game surface is outside the current display")
    if abs(((x1 - x0) / (y1 - y0)) / (width / height) - 1) > 0.04:
        # API30 Unity can render at 0.6x the full immersive display while its
        # accessibility SurfaceView still excludes the navigation inset.
        # Accept that specific, measured geometry; never stretch arbitrary
        # mismatched viewports. Positions still come only from the Unity tree.
        display_width, display_height = image_size
        if (x0 == y0 == 0 and x1 == display_width
                and 0 <= display_height - y1 <= display_height * 0.12
                and abs((display_width / display_height) / (width / height) - 1) <= 0.01):
            x1, y1 = display_width, display_height
        else:
            raise ValueError("Unity and Android screen aspect ratios disagree")
    return [round(x0 + (left + right) / 2 * (x1 - x0) / width),
            round(y0 + (top + bottom) / 2 * (y1 - y0) / height)]


class UiExplorer:
    def __init__(self, qa):
        if qa.game_package != _PACKAGE:
            raise ValueError("UI exploration accepts only the emulator diagnostic package")
        self.qa = qa
        self.port = qa.forward(50052)
        self.actions, self.outcomes = [], []
        self.goal_index, self.pending = 0, None
        self.last_action = -1000.0
        self.wait_frames, self.session_titles, self.stopped = 0, 0, False
        self.snapshot_successes, self.snapshot_errors = 0, {}
        self.input_errors = {}
        self.title_deferrals = {}
        self.title_instance = None

    def _input_error(self, code):
        self.input_errors[code] = self.input_errors.get(code, 0) + 1
        print("Unity UI input skipped: " + code, flush=True)
        return False

    def _snapshot(self):
        token = self.qa.adb("exec-out", "run-as", _PACKAGE, "cat", "files/idoly-qa-ui-token", check=False).strip()
        if re.fullmatch(r"[0-9a-f]{64}", token) is None:
            return {"ok": False, "error": "bridge_token_unavailable"}
        connection = HTTPConnection("127.0.0.1", self.port, timeout=14)
        try:
            connection.request("GET", "/snapshot", headers={"Authorization": "Bearer " + token})
            response = connection.getresponse()
            raw = response.read(_MAX_BODY + 1)
            if response.status != 200 or len(raw) > _MAX_BODY:
                return {"ok": False, "error": "bridge_response_rejected"}
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("UI response is not an object")
            return result
        except (OSError, ValueError, HTTPException):
            return {"ok": False, "error": "bridge_snapshot_unavailable"}
        finally:
            connection.close()

    def _tap(self, snapshot, node, reason, frame):
        # Refresh object identity/bounds after selection, then obtain a current
        # Android tree. Coordinates never come from screenshot/OCR detection.
        began = time.monotonic()
        fresh = self._snapshot()
        current = next((item for item in buttons(fresh) if item.get("instance_id") == node.get("instance_id")
                        and item.get("path") == node.get("path") and item.get("name") == node.get("name")), None)
        if fresh.get("ok") is not True or current is None:
            return self._input_error("selected_node_no_longer_present")
        if reason == "observed_title" and (blocked := title_block_reason(fresh, current)):
            return self._input_error(blocked)
        raw = self.qa.adb("exec-out", "screencap", "-p", binary=True)
        if raw[:8] != b"\x89PNG\r\n\x1a\n":
            return self._input_error("display_capture_unavailable")
        size = struct.unpack_from(">II", raw, 16)
        metrics = self.qa.adb("shell", "wm", "size")
        measured = re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", metrics)
        if not measured or tuple(map(int, measured[-1])) != size:
            return self._input_error("display_metrics_disagree")
        xml = self.qa.adb("exec-out", "uiautomator", "dump", "/dev/tty")
        begin, end = xml.find("<hierarchy"), xml.rfind("</hierarchy>")
        if begin < 0 or end < 0:
            return self._input_error("android_ui_tree_unavailable")
        xml = xml[begin:end + len("</hierarchy>")]
        try:
            point = mapped_point(fresh, current, xml, _PACKAGE, size)
        except ValueError as error:
            return self._input_error(str(error))
        if time.monotonic() - began > 10:
            return self._input_error("ui_observation_became_stale")
        prefix = self.qa.artifacts / f"ui-action-{len(self.actions) + 1:02d}"
        prefix.with_suffix(".png").write_bytes(raw)
        prefix.with_suffix(".xml").write_text(xml, encoding="utf-8")
        prefix.with_suffix(".unity.json").write_text(json.dumps(fresh, ensure_ascii=False, indent=2) + "\n")
        action = {"reason": reason, "frame": frame, "instance_id": current.get("instance_id"),
                  "generation": fresh.get("generation"), "path": current["path"], "label": current["label"],
                  "point": point, "coordinate_source": "fresh_unity_tree_and_android_surface", "performed": False}
        hold = getattr(self.qa, "touch_hold_ms", 0)
        action["touch_hold_milliseconds"] = hold
        if hold == 150:
            # Normal Android DOWN/MOVE/UP at the same point. The original
            # title's long-tap threshold is 500ms and its drag threshold is30.
            self.qa.adb("shell", "input", "touchscreen", "swipe", str(point[0]), str(point[1]),
                        str(point[0]), str(point[1]), "150")
        elif hold == 0:
            self.qa.adb("shell", "input", "tap", str(point[0]), str(point[1]))
        else:
            return self._input_error("unsupported_touch_duration")
        action["performed"] = True
        self.actions.append(action)
        self.last_action = time.monotonic()
        return True

    def _restart(self):
        if self.goal_index >= len(_GOALS):
            return
        self.qa.adb("shell", "am", "force-stop", _PACKAGE)
        self.qa.adb("shell", "am", "start", "-W", "-n", _PACKAGE + "/com.google.firebase.MessagingUnityPlayerActivity",
                    "--es", "unity", "-force-gles30")
        self.last_action = time.monotonic()
        self.session_titles, self.wait_frames = 0, 0

    @staticmethod
    def _signature(snapshot):
        nodes = [(n.get("kind"), n.get("path"), n.get("instance_id")) for n in snapshot.get("nodes", []) if isinstance(n, dict)]
        return hashlib.sha256(json.dumps(nodes, sort_keys=True).encode()).hexdigest()

    def step(self, frame):
        snapshot = self._snapshot()
        (self.qa.artifacts / f"unity-ui-{frame:03d}.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
        if snapshot.get("ok") is True:
            self.snapshot_successes += 1
        else:
            code = str(snapshot.get("error", "unknown"))
            self.snapshot_errors[code] = self.snapshot_errors.get(code, 0) + 1
        if self.stopped or snapshot.get("ok") is not True or len(self.actions) >= 30 or time.monotonic() - self.last_action < 12:
            return
        visible = " ".join(text(row.get("text", "")) for row in snapshot.get("nodes", []) if isinstance(row, dict))
        if _ERROR.search(visible):
            self.outcomes.append({"goal": self.pending[0] if self.pending else "startup", "status": "game_error_observed", "frame": frame})
            if self.pending is None:
                self.stopped = True
                return
            self.goal_index += 1
            self.pending = None
            self._restart()
            return
        close = choose_button(snapshot, r"OK|閉じる|確認|次へ|あとで")
        if close is not None and re.search(r"dialog|modal|popup", str(close.get("path", "")), re.I):
            self._tap(snapshot, close, "observed_dialog", frame)
            return
        # In the original Title scene, the full-canvas TitleButton and
        # UIContentArea/TAP TO START label are siblings, not parent/child.
        # Master initialization can replace this scene with a new Title scene.
        title = choose_button(snapshot, r"TAP\s*TO\s*START", r"tap.*start|start.*tap|^TitleButton$")
        if title is not None:
            identity = title.get("instance_id")
            if identity != self.title_instance:
                self.title_instance, self.session_titles = identity, 0
            blocked = title_block_reason(snapshot, title)
            if blocked:
                self.title_deferrals[blocked] = self.title_deferrals.get(blocked, 0) + 1
                return
            if self.session_titles < self.qa.max_title_taps and self._tap(snapshot, title, "observed_title", frame):
                self.session_titles += 1
            return
        if self.pending:
            goal, started, previous = self.pending
            if frame - started >= 2:
                self.outcomes.append({"goal": goal, "status": ("different_ui_tree_observed" if self._signature(snapshot) != previous
                                                               else "no_ui_change_observed"), "frame": frame,
                                      "note": "View and RPC evidence require separate review"})
                self.goal_index += 1
                self.pending = None
                self._restart()
            return
        if self.goal_index < len(_GOALS):
            goal, label, name = _GOALS[self.goal_index]
            target = choose_button(snapshot, label, name)
            if target is not None and self._tap(snapshot, target, "menu_" + goal, frame):
                self.pending = (goal, frame, self._signature(snapshot))
                self.wait_frames = 0
            elif any(choose_button(snapshot, other[1], other[2]) is not None for other in _GOALS[1:]):
                self.wait_frames += 1
                if self.wait_frames >= 2:
                    self.outcomes.append({"goal": goal, "status": "target_not_present_in_observed_tree", "frame": frame})
                    self.goal_index += 1
                    self.wait_frames = 0

    def report(self):
        return {"qa_only": True, "actions": self.actions, "outcomes": self.outcomes,
                "goals": [goal[0] for goal in _GOALS], "native_click_used": False,
                "successful_ui_snapshots": self.snapshot_successes, "snapshot_errors": self.snapshot_errors,
                "input_errors": self.input_errors,
                "title_deferrals": self.title_deferrals,
                "gameplay_rpc_injected_during_exploration": False, "menu_success_requires_evidence_review": True}
