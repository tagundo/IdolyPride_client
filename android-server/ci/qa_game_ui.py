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


_DIAGNOSTIC_PACKAGE = "game.qualiarts.idolypride.local.diagnostics"
_NORMAL_PACKAGE = "game.qualiarts.idolypride.local"
_QA_PACKAGES = frozenset((_DIAGNOSTIC_PACKAGE, _NORMAL_PACKAGE))
_MAX_BODY = 72 * 1024
# Japanese and Korean clients (the unified app ships both); never tap these.
_FORBIDDEN = re.compile(r"購入|課金|ガチャを引|データ削除|アカウント削除|구매|과금|가챠|뽑기|데이터\s*삭제|계정\s*삭제|buy|purchase|deleteaccount", re.I)
_ERROR = re.compile(r"Unimplemented|Unauthenticated|NullReferenceException|サーバーとの通信に失敗|서버와의\s*통신에\s*실패", re.I)
_GOALS = (
    ("lesson", r"レッスン", r"lesson.*button|button.*lesson"),
    ("live", r"ライブ", r"live.*button|button.*live"),
    ("idols", r"アイドル", r"idol.*button|button.*idol"),
    ("work", r"お仕事", r"work.*button|button.*work"),
    ("stories", r"ストーリー", r"story.*button|button.*story"),
    ("gifts", r"プレゼント", r"gift|present"),
)
_HOME_ROOT = "WindowSystem/WindowRoot/HomeWindow(Clone)/HomeTopScreen(Clone)/ScreenCanvas/ScreenRoot/"
_GLOBAL_DIALOG_ROOT = "Singleton/GlobalDialog/DialogManager/"
_NOTICE_ROOT = _GLOBAL_DIALOG_ROOT + "NoticeDialog(Clone)/"
_LESSON_REWARD_ROOT = _GLOBAL_DIALOG_ROOT + "ActivityLessonReceiveDIalog(Clone)/"
_MANAGER_LEVEL_ROOT = "WindowSystem/WindowRoot/HomeWindow(Clone)/HomeTopScreen(Clone)/ManagerLvUpOverlay(Clone)/"
_HOME_ROLES = {
    "lesson": ("HomePage/SlideRoot/ActivityLesson/ActivityLessonButton", "ActivityLessonButton"),
    "live": ("HomePage/SlideRoot/Live", "Live"),
    "idols": ("ScreenPager/HomeFooter/FooterRoot/HomeGlobalMenu/Character", "Character"),
    "work": ("ScreenPager/HomeFooter/FooterRoot/HomeGlobalMenu/Activity", "Activity"),
    "stories": ("CharacterPage/SlideRoot/Character/HomeRenewalRoot/RenewalStory", "RenewalStory"),
    "gifts": ("HomePage/SlideRoot/DelayMove3/Container/GiftRoot/Gift", "Gift"),
    "home": ("ScreenPager/HomeFooter/FooterRoot/HomeGlobalMenu/Home", "Home"),
}


def text(value):
    return " ".join(re.sub(r"<[^>]*>", "", str(value)).split())


# Touch reasons whose control the bridge does not type as a button: the game's
# own checkbox (e.g. the Photography Live "match the stage song" TouchArea)
# exposes only its label. The label is touched at its observed bounds.
LABEL_TOUCH_REASONS = frozenset(("qa_mv_original_member",))


def label_nodes(snapshot):
    """Active, non-empty, on-screen text labels that are not forbidden actions."""
    nodes = snapshot.get("nodes", [])
    if not isinstance(nodes, list) or len(nodes) > 512:
        raise ValueError("Invalid Unity UI node count")
    result = []
    for node in nodes:
        if (not isinstance(node, dict) or node.get("kind") not in ("text", "tmp_text")
                or node.get("active") is not True or not usable_bounds(snapshot, node)):
            continue
        label = text(node.get("text", ""))
        path = node.get("path", "")
        if not label or not isinstance(path, str) or not path or _FORBIDDEN.search(label + " " + path):
            continue
        result.append(dict(node, label=label))
    return result


def usable_bounds(snapshot, node):
    screen = snapshot.get("screen", {})
    width, height = screen.get("width"), screen.get("height")
    bounds = node.get("bounds")
    if (screen.get("origin") != "top-left" or screen.get("units") != "unity-screen-pixels"
            or type(width) is not int or type(height) is not int or not 64 <= width <= 8192 or not 64 <= height <= 8192
            or not isinstance(bounds, list) or len(bounds) != 4
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in bounds)):
        return False
    left, top, right, bottom = bounds
    return 0 <= left < right <= width and 0 <= top < bottom <= height


def buttons(snapshot):
    result = []
    nodes = snapshot.get("nodes", [])
    if not isinstance(nodes, list) or len(nodes) > 512:
        raise ValueError("Invalid Unity UI node count")
    labels = [node for node in nodes if isinstance(node, dict) and node.get("kind") in ("text", "tmp_text") and node.get("active") is True]
    # List cells are clones with one shared path; each keeps only the labels
    # drawn inside its own bounds (the song list's titles, run 9).
    shared = {}
    for node in nodes:
        if isinstance(node, dict) and node.get("kind") == "button":
            shared[node.get("path")] = shared.get(node.get("path"), 0) + 1

    def inside(row, node):
        if shared.get(node.get("path"), 0) < 2:
            return True
        if not usable_bounds(snapshot, row):
            return False
        x, y = (row["bounds"][0] + row["bounds"][2]) / 2, (row["bounds"][1] + row["bounds"][3]) / 2
        left, top, right, bottom = node["bounds"]
        return left <= x <= right and top <= y <= bottom
    for node in nodes:
        if (not isinstance(node, dict) or node.get("kind") != "button"
                or node.get("active") is not True or node.get("interactable") is not True
                or not usable_bounds(snapshot, node)):
            continue
        path = node.get("path", "")
        if not isinstance(path, str) or not path:
            continue
        parts, seen = [], set()
        for row in [node, *labels]:
            row_path, label_text = str(row.get("path", "")), text(row.get("text", ""))
            if (row_path == path or row_path.startswith(path + "/")) and label_text and (row is node or inside(row, node)):
                identity = (row_path, label_text)
                if identity not in seen:
                    seen.add(identity)
                    parts.append(label_text)
        label = " ".join(parts)
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


def _home_role(snapshot, role):
    if role not in _HOME_ROLES:
        return None
    suffix, name = _HOME_ROLES[role]
    matches = [node for node in buttons(snapshot)
               if node.get("path") == _HOME_ROOT + suffix and node.get("name") == name]
    return matches[0] if len(matches) == 1 else None


def goal_button(snapshot, goal):
    """Select only a bounded role observed in the actual Home hierarchy."""
    return _home_role(snapshot, goal) if goal in {row[0] for row in _GOALS} else None


def route_button(snapshot, goal):
    """Expose a hidden page first; an existing unbounded leaf is not absent."""
    if goal_button(snapshot, goal) is not None:
        return None
    if goal == "stories":
        return _home_role(snapshot, "idols")
    if goal in ("lesson", "live", "gifts"):
        return _home_role(snapshot, "home")
    return None


def title_block_reason(snapshot, node):
    """Only known blocking observations suppress ordinary touch attempts."""
    if node.get("callback_registered") is False:
        return "title_callback_not_registered"
    if any(row.get("active") is True and row.get("kind") in ("text", "tmp_text")
           and text(row.get("text", "")).upper() == "LOADING"
           for row in snapshot.get("nodes", []) if isinstance(row, dict)):
        return "title_loading_visible"
    startup = snapshot.get("startup_observation")
    if not isinstance(startup, dict):
        return None
    for field in ("input_releasing", "content_blocking"):
        if startup.get(field) is True:
            return field
    return None


def title_touch_anchor(snapshot, button):
    """Use the observed title prompt inside its full-screen button, if present."""
    if button.get("path") != "Canvas/TitleButton":
        return button
    prompts = [row for row in snapshot.get("nodes", []) if isinstance(row, dict)
               and row.get("path") == "Canvas/UIContentArea/TAP TO START"
               and row.get("active") is True]
    if not prompts:
        return button  # Preserve the existing layout's ordinary button center.
    if len(prompts) != 1:
        raise ValueError("title_prompt_ambiguous")
    prompt = prompts[0]
    if (prompt.get("kind") not in ("text", "tmp_text")
            or not re.fullmatch(r"TAP\s+TO\s+START", text(prompt.get("text", "")), re.I)
            or not usable_bounds(snapshot, prompt) or not usable_bounds(snapshot, button)):
        raise ValueError("title_prompt_invalid")
    left, top, right, bottom = button["bounds"]
    x0, y0, x1, y1 = prompt["bounds"]
    if not (left <= x0 < x1 <= right and top <= y0 < y1 <= bottom):
        raise ValueError("title_prompt_outside_button")
    return prompt


def download_confirmation(snapshot):
    """Recognize the real client's observed resource download action sheet."""
    nodes = snapshot.get("nodes", [])
    roots = {str(row.get("path", "")).split("/SimpleActionSheet(Clone)/", 1)[0] + "/SimpleActionSheet(Clone)/"
             for row in nodes if row.get("active") is True and "/SimpleActionSheet(Clone)/" in str(row.get("path", ""))}
    if len(roots) != 1:
        return None
    titles = [row for row in nodes if row.get("active") is True and row.get("kind") in ("text", "tmp_text")
              and text(row.get("text", "")) in ("ダウンロード確認", "다운로드 확인")
              and "/SimpleActionSheet(Clone)/" in str(row.get("path", ""))]
    if len(titles) != 1:
        return None
    root = roots.pop()
    local = [row for row in nodes if str(row.get("path", "")).startswith(root)]
    descriptions = [text(row.get("text", "")) for row in local if row.get("active") is True]
    if (not any(re.fullmatch(r"必要なデータをダウンロードします\s*\([^)]*\)|필요한 데이터를 다운로드\s*합니다\s*\([^)]*\)", label)
                for label in descriptions)
            or _FORBIDDEN.search(" ".join(descriptions))):
        return None
    return choose_button(dict(snapshot, nodes=local), r"^(ダウンロード|다운로드)$")


def visible_action_sheet(snapshot):
    return any(row.get("active") is True and "/SimpleActionSheet(Clone)/" in str(row.get("path", ""))
               for row in snapshot.get("nodes", []))


def visible_global_dialogs(snapshot):
    """Modal detection must include forbidden purchase/delete controls too."""
    roots = set()
    for node in snapshot.get("nodes", []):
        if (not isinstance(node, dict) or node.get("kind") != "button"
                or node.get("active") is not True or node.get("interactable") is not True
                or not usable_bounds(snapshot, node)):
            continue
        path = node.get("path", "")
        if not isinstance(path, str) or not path.startswith(_GLOBAL_DIALOG_ROOT):
            continue
        clone, separator, _ = path[len(_GLOBAL_DIALOG_ROOT):].partition("/")
        if separator and clone.endswith("(Clone)"):
            roots.add(_GLOBAL_DIALOG_ROOT + clone + "/")
    return roots


def notice_close_target(snapshot):
    """Select the observed textless Notice X, only with its full known context."""
    if visible_manager_level_overlay(snapshot) or visible_global_dialogs(snapshot) != {_NOTICE_ROOT}:
        return None
    base = _NOTICE_ROOT + "TabDialogBase/DialogCanvas/Dialog/"
    nodes = snapshot.get("nodes", [])

    def label_at(path, expected):
        matches = [node for node in nodes if isinstance(node, dict)
                   and node.get("path") == path and node.get("kind") in ("text", "tmp_text")
                   and node.get("active") is True]
        return len(matches) == 1 and text(matches[0].get("text", "")) == expected

    if not label_at(base + "Header/Title", "INFORMATION"):
        return None
    candidates = buttons(snapshot)
    # Tab labels are localized. Accept the observed Japanese set, or a fully
    # localized set (all three non-empty, none Japanese, none forbidden, e.g.
    # the Korean client whose labels are not yet observed); a mixed set is not
    # this dialog. The INFORMATION title, three wired tabs and CloseButton stay required.
    japanese = ("お知らせ", "不具合", "PR")
    labels = []
    for number in (1, 2, 3):
        path = base + f"Footer/TabButtons/Button{number}"
        tabs = [node for node in candidates if node.get("path") == path
                and node.get("name") == f"Button{number}"
                and node.get("callback_registered") is True]
        if len(tabs) != 1:
            return None
        labels.append(_label_text(nodes, path + "/Text"))
    localized = (all(labels) and not any(label in japanese[:2] for label in labels)
                 and not _FORBIDDEN.search(" ".join(labels)))
    if tuple(labels) != japanese and not localized:
        return None
    close = [node for node in candidates if node.get("path") == base + "Footer/CloseButton"
             and node.get("name") == "CloseButton" and node.get("callback_registered") is True]
    return close[0] if len(close) == 1 else None


def _label_text(nodes, path):
    matches = [node for node in nodes if isinstance(node, dict)
               and node.get("path") == path and node.get("kind") in ("text", "tmp_text")
               and node.get("active") is True]
    return text(matches[0].get("text", "")).strip() if len(matches) == 1 else ""


def visible_manager_level_overlay(snapshot):
    return any(isinstance(node, dict) and node.get("active") is True
               and str(node.get("path", "")).startswith(_MANAGER_LEVEL_ROOT)
               and usable_bounds(snapshot, node) for node in snapshot.get("nodes", []))


def _unique_label(snapshot, path, expected):
    matches = [node for node in snapshot.get("nodes", []) if isinstance(node, dict)
               and node.get("path") == path and node.get("active") is True
               and node.get("kind") in ("text", "tmp_text")]
    return len(matches) == 1 and re.fullmatch(expected, text(matches[0].get("text", ""))) is not None


def _exact_close(snapshot, path):
    matches = [node for node in buttons(snapshot) if node.get("path") == path
               and node.get("name") == "CloseButton" and node.get("callback_registered") is True]
    return matches[0] if len(matches) == 1 else None


def manager_level_close_target(snapshot):
    """Only the observed 2->3 acknowledgement above the first lesson reward."""
    if (not visible_manager_level_overlay(snapshot)
            or visible_global_dialogs(snapshot) != {_LESSON_REWARD_ROOT}):
        return None
    base = _MANAGER_LEVEL_ROOT + "OverlayCanvas/SlideRoot/ContentArea/ContentRoot/"
    if (not _unique_label(snapshot, base + "Content/PrevLevelAnchor/prevLevel", "2")
            or not _unique_label(snapshot, base + "Content/CurrentLevelAnchor/currentLevel", "3")):
        return None
    return _exact_close(snapshot, base + "CloseButton")


def lesson_reward_close_target(snapshot):
    """Close a received reward view; never select its two-hour promotion action."""
    if (visible_manager_level_overlay(snapshot)
            or visible_global_dialogs(snapshot) != {_LESSON_REWARD_ROOT}):
        return None
    base = _LESSON_REWARD_ROOT + "BasicDialogBase/DialogCanvas/Dialog/"
    if (not _unique_label(snapshot, base + "Header/Title", r"\d{2}:[0-5]\d:[0-5]\d の自主トレ")
            or not _unique_label(snapshot, base + "Body/MainContentsRoot/MainLive", "メインライブ")
            or not _unique_label(snapshot, base + "Body/MainContentsRoot/LiveName", r"\#01 Rapture渋谷")
            or not _unique_label(snapshot, base + "Body/Rewards/RewardRoot/RewardTitle", "成果")):
        return None
    return _exact_close(snapshot, base + "Footer/CloseButton")


def navigation_block_reason(snapshot):
    startup = snapshot.get("startup_observation")
    if not isinstance(startup, dict) or type(startup.get("content_blocking")) is not bool:
        return "content_blocking_state_unavailable"
    if startup["content_blocking"]:
        return "content_blocking"
    return "input_releasing" if startup.get("input_releasing") is True else None


def qa_package(package):
    if not isinstance(package, str) or package not in _QA_PACKAGES:
        raise ValueError("UI exploration accepts only the two fixed emulator QA packages")
    return package


def mapped_point(snapshot, node, xml, package, image_size):
    package = qa_package(package)
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
        if item.get("resource-id", "").endswith(":id/unitySurfaceView"):
            if item.get("package") != package:
                raise ValueError("A unique current Unity accessibility surface is required")
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
        self.game_package = qa_package(qa.game_package)
        self.qa = qa
        self.port = qa.forward(50052)
        self.actions, self.outcomes = [], []
        self.goal_index, self.pending = 0, None
        self.last_action = -1000.0
        self.wait_frames, self.session_titles, self.stopped = 0, 0, False
        self.snapshot_successes, self.snapshot_errors = 0, {}
        self.input_errors = {}
        self.surface_input_failures = 0
        self.title_deferrals = {}
        self.title_instance = None
        self.stop_reason = None
        self.navigation_deferrals = {}
        self.route_pending = None
        self.pending_dialog_frame = None
        self.restart_pending = False
        self.global_dialog_observations = 0
        self.blocking_modal_identity = None

    def _input_error(self, code):
        self.input_errors[code] = self.input_errors.get(code, 0) + 1
        if code == "A unique current Unity accessibility surface is required":
            self.surface_input_failures += 1
            if self.surface_input_failures >= 3:
                self.stopped, self.stop_reason = True, "android_surface_unavailable"
        else:
            self.surface_input_failures = 0
        print("Unity UI input skipped: " + code, flush=True)
        return False

    def _snapshot(self):
        token = self.qa.adb("exec-out", "run-as", self.game_package, "cat", "files/idoly-qa-ui-token", check=False).strip()
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

    def _input_target(self, fresh, node, reason):
        """Recheck identity and blockers before collecting geometry or touching."""
        def reject(code):
            self._input_error(code)
            return None

        candidates = label_nodes(fresh) if reason in LABEL_TOUCH_REASONS else buttons(fresh)
        current = next((item for item in candidates if item.get("instance_id") == node.get("instance_id")
                        and item.get("path") == node.get("path") and item.get("name") == node.get("name")
                        and (reason not in LABEL_TOUCH_REASONS or item.get("label") == node.get("label"))), None)
        if fresh.get("ok") is not True or current is None:
            return reject("selected_node_no_longer_present")
        selectors = {"observed_notice_close": notice_close_target,
                     "observed_manager_level_close": manager_level_close_target,
                     "observed_lesson_reward_close": lesson_reward_close_target}
        if reason in selectors:
            close = selectors[reason](fresh)
            if (close is None or close.get("instance_id") != current.get("instance_id")
                    or close.get("path") != current.get("path")):
                return reject("notice_dialog_changed" if reason == "observed_notice_close"
                                         else "selected_modal_changed")
        elif visible_global_dialogs(fresh) or visible_manager_level_overlay(fresh):
            return reject("visible_global_dialog_blocks_input")
        if reason == "observed_title" and (blocked := title_block_reason(fresh, current)):
            return reject(blocked)
        if reason == "observed_title" and visible_action_sheet(fresh):
            return reject("title_obscured_by_action_sheet")
        if reason == "observed_resource_download_confirmation":
            confirmation = download_confirmation(fresh)
            if (confirmation is None or confirmation.get("instance_id") != current.get("instance_id")
                    or confirmation.get("path") != current.get("path")):
                return reject("download_confirmation_changed")
        if reason.startswith(("menu_", "route_")) and (blocked := navigation_block_reason(fresh)):
            return reject(blocked)
        return current

    def _tap(self, snapshot, node, reason, frame):
        # Source choice is a normal Android input differential, never a native
        # gameplay callback. Unsupported sources cannot fall back to touching.
        source = getattr(self.qa, "input_source", "touchscreen")
        if source not in ("touchscreen", "mouse"):
            return self._input_error("unsupported_input_source")
        # Reject an obsolete selection before the relatively slow Android dump.
        query_began = time.monotonic()
        fresh = self._snapshot()
        observed_at = time.monotonic()
        current = self._input_target(fresh, node, reason)
        if current is None:
            return False
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
        geometry_observed_at = time.monotonic()
        if geometry_observed_at - observed_at > 10:
            # A software-rendered guest can take >10s to return uiautomator's
            # current surface. Refresh Unity *after* that work instead of
            # touching from the older tree or increasing the freshness limit.
            query_began = time.monotonic()
            fresh = self._snapshot()
            observed_at = time.monotonic()
            current = self._input_target(fresh, node, reason)
            if current is None:
                return False
        try:
            anchor = title_touch_anchor(fresh, current) if reason == "observed_title" else current
            point = mapped_point(fresh, anchor, xml, self.game_package, size)
        except ValueError as error:
            return self._input_error(str(error))
        now = time.monotonic()
        if now - observed_at > 10 or now - geometry_observed_at > 10:
            return self._input_error("ui_observation_became_stale")
        prefix = self.qa.artifacts / f"ui-action-{len(self.actions) + 1:02d}"
        prefix.with_suffix(".png").write_bytes(raw)
        prefix.with_suffix(".xml").write_text(xml, encoding="utf-8")
        prefix.with_suffix(".unity.json").write_text(json.dumps(fresh, ensure_ascii=False, indent=2) + "\n")
        action = {"reason": reason, "frame": frame, "instance_id": current.get("instance_id"),
                  "generation": fresh.get("generation"), "path": current["path"], "label": current["label"],
                  "point": point, "coordinate_source": "fresh_unity_tree_and_android_surface", "performed": False}
        action["coordinate_anchor_path"] = anchor["path"]
        action["ui_query_milliseconds"] = round((observed_at - query_began) * 1000)
        action["observation_to_input_milliseconds"] = round((time.monotonic() - observed_at) * 1000)
        action["android_geometry_to_input_milliseconds"] = round((time.monotonic() - geometry_observed_at) * 1000)
        hold = getattr(self.qa, "touch_hold_ms", 0)
        action["touch_hold_milliseconds"] = hold
        action["input_source"] = source
        input_began = time.monotonic()
        if hold == 150:
            # Normal Android DOWN/MOVE/UP at the same point. The original
            # title's long-tap threshold is 500ms and its drag threshold is30.
            self.qa.adb("shell", "input", source, "swipe", str(point[0]), str(point[1]),
                        str(point[0]), str(point[1]), "150")
        elif hold == 0:
            prefix_args = ("shell", "input") if source == "touchscreen" else ("shell", "input", source)
            self.qa.adb(*prefix_args, "tap", str(point[0]), str(point[1]))
        else:
            return self._input_error("unsupported_touch_duration")
        # This includes adb/process/injection latency, not a claim about the
        # event's actual DOWN/UP interval or final Android/Unity delivery.
        action["input_command_milliseconds"] = round((time.monotonic() - input_began) * 1000)
        action["performed"] = True
        self.actions.append(action)
        self.surface_input_failures = 0
        self.last_action = time.monotonic()
        return True

    def _restart(self):
        self.route_pending = None
        self.pending_dialog_frame = None
        if self.goal_index >= len(_GOALS):
            self.stopped, self.stop_reason = True, "all_goal_outcomes_collected"
            return
        self.qa.adb("shell", "am", "force-stop", self.game_package)
        arguments = ["shell", "am", "start", "-W", "-n", self.game_package + "/com.google.firebase.MessagingUnityPlayerActivity"]
        if self.game_package == _DIAGNOSTIC_PACKAGE:
            # Retain the legacy diagnostic launch. The normal-local profile
            # uses the client's default graphics selection without overrides.
            arguments.extend(("--es", "unity", "-force-gles30"))
        self.qa.adb(*arguments)
        self.last_action = time.monotonic()
        self.session_titles, self.wait_frames = 0, 0

    @staticmethod
    def _signature(snapshot):
        # All pager pages exist while offscreen. Button geometry distinguishes
        # a page becoming actionable without treating timer text as navigation.
        nodes = [(n.get("kind"), n.get("path"), n.get("instance_id"),
                  n.get("bounds") if n.get("kind") == "button" and usable_bounds(snapshot, n) else None)
                 for n in snapshot.get("nodes", []) if isinstance(n, dict)]
        nodes.sort(key=lambda row: tuple(str(value) for value in row[:3]))
        return hashlib.sha256(json.dumps(nodes, sort_keys=True).encode()).hexdigest()

    def step(self, frame):
        snapshot = self._snapshot()
        (self.qa.artifacts / f"unity-ui-{frame:03d}.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
        if snapshot.get("ok") is True:
            self.snapshot_successes += 1
        else:
            code = str(snapshot.get("error", "unknown"))
            self.snapshot_errors[code] = self.snapshot_errors.get(code, 0) + 1
        if len(self.actions) >= 30:
            self.stopped, self.stop_reason = True, "action_limit_reached"
        if self.stopped or snapshot.get("ok") is not True or time.monotonic() - self.last_action < 12:
            return
        dialogs = visible_global_dialogs(snapshot)
        manager_overlay = visible_manager_level_overlay(snapshot)
        identity = ("manager_level",) if manager_overlay else tuple(sorted(dialogs)) if dialogs else None
        if identity != self.blocking_modal_identity:
            self.global_dialog_observations = 0
            self.blocking_modal_identity = identity
        download = download_confirmation(snapshot)
        if download is not None and not dialogs and not manager_overlay:
            if self.pending and self._signature(snapshot) != self.pending[2] and self.pending_dialog_frame is None:
                self.pending_dialog_frame = frame
            self._tap(snapshot, download, "observed_resource_download_confirmation", frame)
            return
        if dialogs or manager_overlay:
            self.global_dialog_observations += 1
            close = manager_level_close_target(snapshot) if manager_overlay else notice_close_target(snapshot)
            reason = "observed_manager_level_close" if manager_overlay else "observed_notice_close"
            if close is None and not manager_overlay:
                close = lesson_reward_close_target(snapshot)
                reason = "observed_lesson_reward_close"
            if self.global_dialog_observations >= 3:
                self.stopped = True
                self.stop_reason = ("global_dialog_not_dismissed" if close is not None
                                    else "unrecognized_global_dialog")
                return
            if close is not None:
                if (reason == "observed_lesson_reward_close" and self.pending
                        and self.pending[0] == "lesson" and self.pending_dialog_frame is None):
                    self.pending_dialog_frame = frame
                self._tap(snapshot, close, reason, frame)
            else:
                key = "unrecognized_global_dialog"
                self.navigation_deferrals[key] = self.navigation_deferrals.get(key, 0) + 1
            return
        visible = " ".join(text(row.get("text", "")) for row in snapshot.get("nodes", []) if isinstance(row, dict))
        if _ERROR.search(visible) and not self.restart_pending:
            self.outcomes.append({"goal": self.pending[0] if self.pending else "startup", "status": "game_error_observed", "frame": frame})
            if self.pending is None:
                self.stopped, self.stop_reason = True, "observed_startup_error"
                return
            self.goal_index += 1
            self.pending = None
            self.route_pending = None
            self.pending_dialog_frame = None
            self.restart_pending = True
            if navigation_block_reason(snapshot) is None:
                self.restart_pending = False
                self._restart()
            return
        close = choose_button(snapshot, r"OK|閉じる|確認|次へ|あとで|확인|닫기|다음|나중에")
        if close is not None and re.search(r"dialog|modal|popup|sheet", str(close.get("path", "")), re.I):
            if self.pending and self._signature(snapshot) != self.pending[2] and self.pending_dialog_frame is None:
                self.pending_dialog_frame = frame
            self._tap(snapshot, close, "observed_dialog", frame)
            return
        if visible_action_sheet(snapshot):
            self.title_deferrals["unhandled_action_sheet"] = self.title_deferrals.get("unhandled_action_sheet", 0) + 1
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
        blocked = navigation_block_reason(snapshot)
        if blocked:
            self.navigation_deferrals[blocked] = self.navigation_deferrals.get(blocked, 0) + 1
            return
        if self.restart_pending:
            self.restart_pending = False
            self._restart()
            return
        if self.pending:
            goal, started, previous = self.pending
            if goal == "lesson" and (_home_role(snapshot, "home") is None or goal_button(snapshot, "lesson") is None):
                key = "lesson_home_not_ready"
                self.navigation_deferrals[key] = self.navigation_deferrals.get(key, 0) + 1
                return
            if frame - started >= 2:
                self.outcomes.append({"goal": goal, "status": ("different_ui_tree_observed" if self._signature(snapshot) != previous
                                                               or self.pending_dialog_frame is not None
                                                               else "no_ui_change_observed"), "frame": frame,
                                      "transient_dialog_frame": self.pending_dialog_frame,
                                      "note": "View and RPC evidence require separate review; this is not menu success"})
                self.goal_index += 1
                self.pending = None
                self.pending_dialog_frame = None
                self._restart()
            return
        if self.goal_index < len(_GOALS):
            goal = _GOALS[self.goal_index][0]
            target = goal_button(snapshot, goal)
            if target is not None and self._tap(snapshot, target, "menu_" + goal, frame):
                self.pending = (goal, frame, self._signature(snapshot))
                self.pending_dialog_frame = None
                self.route_pending = None
                self.wait_frames = 0
            elif target is None:
                route = route_button(snapshot, goal) if self.route_pending is None else None
                if route is not None and self._tap(snapshot, route, "route_" + goal, frame):
                    self.route_pending = {"goal": goal, "frame": frame, "path": route["path"]}
                    self.wait_frames = 0
                    return
                self.wait_frames += 1
                key = "route_destination_not_ready" if self.route_pending else "goal_target_not_actionable"
                self.navigation_deferrals[key] = self.navigation_deferrals.get(key, 0) + 1

    def report(self):
        return {"qa_only": True, "game_package": self.game_package, "actions": self.actions, "outcomes": self.outcomes,
                "goals": [goal[0] for goal in _GOALS], "native_click_used": False,
                "successful_ui_snapshots": self.snapshot_successes, "snapshot_errors": self.snapshot_errors,
                "input_errors": self.input_errors,
                "repeated_android_surface_failures": self.surface_input_failures,
                "repeated_visible_global_dialogs": self.global_dialog_observations,
                "title_deferrals": self.title_deferrals,
                "stop_reason": self.stop_reason,
                "navigation_deferrals": self.navigation_deferrals,
                "pending_route": self.route_pending,
                "gameplay_rpc_injected_during_exploration": False, "menu_success_requires_evidence_review": True}
