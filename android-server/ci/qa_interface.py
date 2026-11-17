"""Observed native resource/locales and landscape proof on a disposable guest.

Configuration uses Android's public LocaleManager and WindowManager shell APIs.
No application-private preferences/database are changed, no hidden view is
forced visible, and the existing five-observation UI budget is unchanged.
"""
from __future__ import annotations

from pathlib import Path
import re
import time
import xml.etree.ElementTree as ET

from qa_account_management import bounds, visible_node, tap_node

PACKAGE = "game.qualiarts.idolypride.localserver"
ACTIVITY = PACKAGE + "/.MainActivity"
ROOT = Path(__file__).resolve().parents[2]
LANGUAGES = ("en", "ja", "ko")
CATEGORIES = ("console", "server", "users", "content", "graphics")
OBSERVATIONS = 5


def labels(language):
    if language not in LANGUAGES:
        raise ValueError("Unsupported interface QA language")
    path = ROOT / "android-server/app/src/main/res" / ("values-" + language) / "strings.xml"
    rows = {node.get("name"): "".join(node.itertext()) for node in ET.parse(path).getroot()
            if node.tag == "string"}
    keys = ("app_name", "start_server", "stop_server", "status_stopped", "status_running",
            "presentation_custom_graphics", *("nav_" + key for key in CATEGORIES))
    if any(not rows.get(key, "").strip() for key in keys):
        raise RuntimeError("Interface QA requires explicit translated title, controls and categories")
    return {key: rows[key] for key in keys}


def app_bounds(tree):
    areas = [bounds(node) for node in tree.iter("node")
             if node.get("package") == PACKAGE and visible_node(node, tree)]
    areas = [area for area in areas if area is not None]
    if not areas:
        raise RuntimeError("Native application viewport was not observed")
    return max(areas, key=lambda area: (area[2] - area[0]) * (area[3] - area[1]))


def nav_node(tree, category):
    matches = [node for node in tree.iter("node")
               if node.get("package") == PACKAGE
               and node.get("content-desc") == "idoly.nav." + category and visible_node(node, tree)]
    if len(matches) != 1 or matches[0].get("enabled") != "true":
        raise RuntimeError("Native interface category was not uniquely visible")
    return matches[0]


def language_proof(tree, expected, *, status_key="status_stopped"):
    nodes = [node for node in tree.iter("node") if node.get("package") == PACKAGE and visible_node(node, tree)]
    titles = [node for node in nodes if node.get("class") == "android.widget.TextView"
              and node.get("text", "").startswith(expected["app_name"] + "  ")]
    if len(titles) != 1:
        raise RuntimeError("Native interface title did not use the selected language")
    controls = []
    for key in ("start_server", "stop_server"):
        matches = [node for node in nodes if node.get("class") == "android.widget.Button"
                   and node.get("text") == expected[key]]
        if len(matches) != 1:
            raise RuntimeError("Native interface server controls did not use the selected language")
        controls.append(matches[0])
    # Observe the existing top status region, even when its text is wrong.
    # Searching for expected text could accept a matching label elsewhere;
    # no machine-only spoken description or production selector is added.
    text_views = [node for node in nodes if node.get("class") == "android.widget.TextView"]
    if len(text_views) < 2 or text_views[0] is not titles[0]:
        raise RuntimeError("Native interface title and top status region were not observed")
    status = text_views[1]
    title_area, status_area = bounds(titles[0]), bounds(status)
    below_title = status_area[1] >= title_area[3]
    beside_title = (status_area[0] >= title_area[2]
                    and min(status_area[3], title_area[3]) > max(status_area[1], title_area[1]))
    if (not (below_title or beside_title)
            or status_area[3] > min(bounds(node)[1] for node in controls)):
        raise RuntimeError("Native interface top status is outside its observed region")
    if status.get("text") != expected[status_key]:
        raise RuntimeError("Native interface server status did not use the selected language")
    for category in CATEGORIES:
        if nav_node(tree, category).get("text") != expected["nav_" + category]:
            raise RuntimeError("Native interface category did not use the selected language")
    return {"title": titles[0].get("text"), "start": expected["start_server"],
            "stop": expected["stop_server"], "status": status.get("text"), "actual_ui_observed": True}


def observe(qa, stage, checker):
    last = None
    for attempt in range(OBSERVATIONS):
        tree = qa.capture(stage + "-" + str(attempt))
        try:
            proof = checker(tree)
        except RuntimeError as error:
            last = error
            if attempt + 1 < OBSERVATIONS:
                time.sleep(.5)
        else:
            return tree, proof
    raise RuntimeError("Native interface observation failed: " + stage + "; " + str(last))


def configure_locale(qa, language):
    # AOSP android-14.0.0_r1 LocaleManagerShellCommand requires --locales;
    # the trailing positional language would silently leave an empty list.
    qa.adb("shell", "cmd", "locale", "set-app-locales", PACKAGE, "--user", "0", "--locales", language)
    reply = qa.adb("shell", "cmd", "locale", "get-app-locales", PACKAGE, "--user", "0").strip()
    match = re.search(r"\[([^\]]*)\]\s*$", reply)
    if match is None or match.group(1) != language:
        raise RuntimeError("Android public app-locale configuration did not match")
    qa.adb("shell", "am", "start", "-n", ACTIVITY)


def density_dpi(qa):
    value = qa.adb("shell", "wm", "density")
    matches = re.findall(r"(Physical|Override) density:\s*(\d+)", value)
    readings = {kind: int(number) for kind, number in matches}
    density = readings.get("Override", readings.get("Physical"))
    if type(density) is not int or not 120 <= density <= 1000:
        raise RuntimeError("Android public display density was not available")
    return density


def content_and_body_bounds(tree):
    content = [node for node in tree.iter("node") if node.get("package") == PACKAGE
               and node.get("resource-id") == "android:id/content" and visible_node(node, tree)]
    body = [node for node in tree.iter("node") if node.get("package") == PACKAGE
            and node.get("class") == "android.widget.ScrollView" and visible_node(node, tree)]
    if len(content) != 1 or len(body) != 1:
        raise RuntimeError("Native settings viewport and scroll body were not uniquely observed")
    viewport, scroll = bounds(content[0]), bounds(body[0])
    if (viewport is None or scroll is None or scroll[0] < viewport[0] or scroll[1] < viewport[1]
            or scroll[2] > viewport[2] or scroll[3] > viewport[3]):
        raise RuntimeError("Native settings scroll body is clipped by the application viewport")
    fraction = (scroll[3] - scroll[1]) / (viewport[3] - viewport[1])
    if fraction < .5:
        raise RuntimeError("Landscape settings body occupies less than half the usable viewport")
    return viewport, scroll, body[0], fraction


def first_graphics_control(tree, body, area, density):
    matches = [node for node in body.iter("node") if node.get("package") == PACKAGE
               and node.get("class") == "android.widget.CheckBox"
               and node.get("text") == labels("ko")["presentation_custom_graphics"]
               and visible_node(node, tree)]
    if len(matches) != 1:
        raise RuntimeError("Landscape first Graphics control was not uniquely visible")
    node = matches[0]; target = bounds(node)
    if (target is None or target[0] < area[0] or target[1] < area[1]
            or target[2] > area[2] or target[3] > area[3]):
        raise RuntimeError("Landscape first Graphics control is clipped by the scroll body")
    minimum = min(target[2] - target[0], target[3] - target[1]) * 160.0 / density
    if minimum < 44.0:
        raise RuntimeError("Landscape first Graphics control is smaller than 44 dp")
    if (any(node.get(key) != "true" for key in ("enabled", "clickable", "checkable"))
            or node.get("checked") not in ("true", "false")):
        raise RuntimeError("Landscape first Graphics control is not an enabled editable checkbox")
    return node, {"class": "android.widget.CheckBox", "width_px": target[2]-target[0],
                  "height_px": target[3]-target[1], "minimum_target_dp": round(minimum, 2),
                  "fully_visible": True, "enabled": True, "clickable": True, "checkable": True,
                  "checked": node.get("checked") == "true"}


def other_visible_controls(body, first):
    # Compare only public UI properties. No private preferences or settings
    # override is used to toggle or restore this real control.
    return tuple((node.get("class"), node.get("content-desc", ""), node.get("text", ""),
                  node.get("checked", ""), node.get("selected", ""), node.get("enabled", ""),
                  tuple(child.get("text", "") for child in node.iter("node") if child is not node))
                 for node in body.iter("node") if node is not first
                 and node.get("class") in ("android.widget.CheckBox", "android.widget.Spinner"))


def wide_proof(tree, density, *, graphics):
    language_proof(tree, labels("ko"))
    viewport, scroll, body, fraction = content_and_body_bounds(tree)
    left, top, right, bottom = viewport
    if right - left <= bottom - top:
        raise RuntimeError("Actual native application viewport is not landscape")
    minimum = float("inf")
    for category in CATEGORIES:
        node = nav_node(tree, category)
        x0, y0, x1, y1 = bounds(node)
        if x0 < left or y0 < top or x1 > right or y1 > bottom:
            raise RuntimeError("Landscape category is clipped by the application viewport")
        target = min(x1 - x0, y1 - y0) * 160.0 / density
        if target < 44.0:
            raise RuntimeError("Landscape category target is smaller than 44 dp")
        minimum = min(minimum, target)
    if any(node.get("resource-id") == "android:id/alertTitle" for node in tree.iter("node")):
        raise RuntimeError("A help or system dialog obscures the landscape settings")
    key = "graphics" if graphics else "checks"
    panels = [node for node in tree.iter("node") if node.get("content-desc") == "idoly.panel." + key
              and node.get("package") == PACKAGE and visible_node(node, tree)]
    if len(panels) != 1 or panels[0].get("selected") != ("true" if graphics else "false"):
        raise RuntimeError("Landscape default panel state was not observed")
    if nav_node(tree, "graphics" if graphics else "console").get("selected") != "true":
        raise RuntimeError("Landscape category selection was not observed")
    result = {"width_px": right - left, "height_px": bottom - top, "density_dpi": density,
              "body_height_px": scroll[3]-scroll[1], "body_fraction": round(fraction, 6),
              "visible_categories": len(CATEGORIES), "minimum_navigation_target_dp": round(minimum, 2),
              "help_closed": True, "default_panel": key, "default_panel_expanded": graphics}
    if graphics:
        _, result["first_graphics_control"] = first_graphics_control(tree, body, scroll, density)
    return result


def observe_wide(qa, density):
    # Console, Graphics and the two real checkbox observations share the same
    # five captures. A tap must change the checked state and a second tap must
    # restore it before any legacy account/game checks can continue.
    phase, last, console, graphics = "console", None, None, None
    initial_checked, initial_other = None, None
    for attempt in range(OBSERVATIONS):
        tree = qa.capture("00-interface-wide-" + str(attempt))
        try:
            proof = wide_proof(tree, density, graphics=phase != "console")
            if phase == "console":
                console = proof
                tap_node(qa, nav_node(tree, "graphics"))
                phase = "graphics"
                continue
            _, scroll, body, _ = content_and_body_bounds(tree)
            control, first = first_graphics_control(tree, body, scroll, density)
            if phase == "graphics":
                graphics = proof
                initial_checked = first["checked"]
                initial_other = other_visible_controls(body, control)
                tap_node(qa, control)
                phase = "changed"
                continue
            if phase == "changed":
                if first["checked"] is initial_checked:
                    raise RuntimeError("Landscape first Graphics control did not respond to the actual tap")
                tap_node(qa, control)
                phase = "restored"
                continue
            if first["checked"] is not initial_checked:
                raise RuntimeError("Landscape first Graphics control was not restored after the second tap")
            if other_visible_controls(body, control) != initial_other:
                raise RuntimeError("Landscape other visible Graphics controls changed during checkbox restoration")
            return {"console": console, "graphics": graphics, "actual_rotation": 1,
                    "graphics_interaction": {"actual_tap": True, "changed": True, "restored": True,
                        "checked_before": initial_checked, "checked_changed": not initial_checked,
                        "checked_restored": first["checked"], "other_visible_controls_unchanged": True}}
        except RuntimeError as error:
            last = error
            if attempt + 1 < OBSERVATIONS:
                time.sleep(.5)
    raise RuntimeError("Native landscape UI was not observed within five attempts; " + str(last))


def observe_portrait(qa):
    last = None
    for attempt in range(OBSERVATIONS):
        tree = qa.capture("00-interface-portrait-" + str(attempt))
        try:
            language_proof(tree, labels("ko"))
            left, top, right, bottom = app_bounds(tree)
            if bottom - top <= right - left:
                raise RuntimeError("Actual native application viewport did not return to portrait")
            console = nav_node(tree, "console")
        except RuntimeError as error:
            last = error
            if attempt + 1 < OBSERVATIONS:
                time.sleep(.5)
            continue
        if console.get("selected") == "true":
            return {"actual_rotation": 0, "width_px": right-left, "height_px": bottom-top,
                    "interface_language": "ko", "console_selected": True}
        tap_node(qa, console)
    raise RuntimeError("Native portrait UI was not restored within five attempts; " + str(last))


def exercise_interface_configuration(qa):
    sdk = qa.adb("shell", "getprop", "ro.build.version.sdk").strip()
    if not sdk.isdigit() or int(sdk) < 33:
        raise RuntimeError("Official per-app language QA requires Android API 33 or newer")
    density = density_dpi(qa)
    cases, selected, rotated = [], None, False
    try:
        for language in LANGUAGES:
            configure_locale(qa, language)
            selected = language
            _, proof = observe(qa, "00-interface-" + language,
                               lambda tree, expected=labels(language): language_proof(tree, expected))
            cases.append({"language": language, **proof})
        rotated = True
        qa.adb("shell", "wm", "user-rotation", "lock", "1")
        wide = observe_wide(qa, density)
    finally:
        if rotated:
            qa.adb("shell", "wm", "user-rotation", "lock", "0", check=False)
        if selected != "ko":
            # Cleanup uses the same public user preference API; a failed case
            # never claims success or continues into the 32 legacy checks.
            qa.adb("shell", "cmd", "locale", "set-app-locales", PACKAGE,
                   "--user", "0", "--locales", "ko", check=False)
    restored = observe_portrait(qa)
    return {"actual_os_api_resource_configuration": {
        "authority": "Android public LocaleManager and WindowManager shell APIs",
        "sdk": int(sdk), "languages": cases, "wide": wide, "restored_portrait": restored}}


def exercise_running_interface_languages(qa):
    """Observe live status through locale changes without a server restart."""
    cases, selected = [], None
    try:
        for language in LANGUAGES:
            configure_locale(qa, language)
            selected = language
            _, proof = observe(qa, "02-interface-running-" + language,
                               lambda tree, expected=labels(language): language_proof(
                                   tree, expected, status_key="status_running"))
            cases.append({"language": language, **proof})
    finally:
        if selected != "ko":
            qa.adb("shell", "cmd", "locale", "set-app-locales", PACKAGE,
                   "--user", "0", "--locales", "ko", check=False)
    return cases
