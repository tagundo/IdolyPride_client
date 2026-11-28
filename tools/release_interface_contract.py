"""Strict public-OS locale and orientation proof for the current Android lane."""
from copy import deepcopy
import math

FIELD = "actual_os_api_resource_configuration"
AUTHORITY = "Android public LocaleManager and WindowManager shell APIs"
SDK = 34
VERSION = "0.3.37"
LANGUAGES = ("en", "ja", "ko")
READBACKS = {
    "en": ("IDOLY PRIDE Server", "Start server", "Stop server"),
    "ja": ("アイプラサーバー", "サーバー開始", "サーバー停止"),
    "ko": ("아이프라 서버", "서버 시작", "서버 중지"),
}
STATUS_READBACKS = {"en": ("Stopped", "Running"), "ja": ("停止中", "実行中"), "ko": ("중지됨", "실행 중")}
_DETAIL = {"authority", "sdk", "languages", "running_languages", "wide", "restored_portrait"}
_LANGUAGE = {"language", "title", "start", "stop", "status", "actual_ui_observed"}
_WIDE_PANEL = {"width_px", "height_px", "density_dpi", "body_height_px", "body_fraction", "visible_categories",
               "minimum_navigation_target_dp", "help_closed", "default_panel", "default_panel_expanded"}
_GRAPHICS_CONTROL = {"class", "width_px", "height_px", "minimum_target_dp", "fully_visible", "enabled", "clickable", "checkable", "checked"}
_GRAPHICS_INTERACTION = {"actual_tap", "changed", "restored", "checked_before", "checked_changed", "checked_restored", "other_visible_controls_unchanged"}
_PORTRAIT = {"actual_rotation", "width_px", "height_px", "interface_language", "console_selected"}


def _need(condition):
    if not condition:
        raise ValueError("android_public_os_interface_scope_differs")


def _fields(value, names):
    _need(type(value) is dict and set(value) == names)


def _extent(value):
    return type(value) is int and 1 <= value <= 16384


def _panel(value, *, graphics):
    _fields(value, _WIDE_PANEL | ({"first_graphics_control"} if graphics else set()))
    width, height, dpi = value["width_px"], value["height_px"], value["density_dpi"]
    target, body, fraction = value["minimum_navigation_target_dp"], value["body_height_px"], value["body_fraction"]
    _need(_extent(width) and _extent(height) and width > height
          and type(dpi) is int and 120 <= dpi <= 1000
          and _extent(body) and body <= height and type(fraction) is float and math.isfinite(fraction)
          and .5 <= fraction <= 1 and math.isclose(fraction, round(body / height, 6), rel_tol=0, abs_tol=0.000001)
          and type(value["visible_categories"]) is int and value["visible_categories"] == 5
          and type(target) is float and math.isfinite(target)
          and 44.0 <= target <= min(width, height) * 160.0 / dpi
          and value["help_closed"] is True
          and value["default_panel"] == ("graphics" if graphics else "checks")
          and value["default_panel_expanded"] is graphics)
    if graphics:
        first = value["first_graphics_control"]
        _fields(first, _GRAPHICS_CONTROL)
        control_width, control_height, minimum = first["width_px"], first["height_px"], first["minimum_target_dp"]
        _need(first["class"] == "android.widget.CheckBox" and _extent(control_width) and control_width <= width
              and _extent(control_height) and control_height <= body
              and type(minimum) is float and math.isfinite(minimum) and minimum >= 44
              and math.isclose(minimum, round(min(control_width, control_height) * 160.0 / dpi, 2), rel_tol=0, abs_tol=.000001)
              and all(first[key] is True for key in ("fully_visible", "enabled", "clickable", "checkable"))
              and type(first["checked"]) is bool)
    return width, height, dpi


def validate_android(report):
    """Validate observations only; existing preservation/attempt gates stay separate."""
    if type(report) is not dict or FIELD not in report:
        raise ValueError("android_public_os_interface_not_passed")
    detail = report[FIELD]
    _fields(detail, _DETAIL)
    _need(detail["authority"] == AUTHORITY and type(detail["sdk"]) is int and detail["sdk"] == SDK)
    for field, running in (("languages", False), ("running_languages", True)):
        values = detail[field]
        _need(type(values) is list and len(values) == len(LANGUAGES))
        for value, language in zip(values, LANGUAGES):
            _fields(value, _LANGUAGE)
            title, start, stop = READBACKS[language]
            _need(value["language"] == language and value["title"] == title + "  " + VERSION
                  and value["start"] == start and value["stop"] == stop
                  and value["status"] == STATUS_READBACKS[language][int(running)]
                  and value["actual_ui_observed"] is True)
    wide = detail["wide"]
    _fields(wide, {"console", "graphics", "graphics_interaction", "actual_rotation"})
    _need(type(wide["actual_rotation"]) is int and wide["actual_rotation"] == 1)
    _need(_panel(wide["console"], graphics=False) == _panel(wide["graphics"], graphics=True))
    interaction = wide["graphics_interaction"]
    _fields(interaction, _GRAPHICS_INTERACTION)
    before = interaction["checked_before"]
    _need(all(interaction[key] is True for key in ("actual_tap", "changed", "restored", "other_visible_controls_unchanged"))
          and type(before) is bool and interaction["checked_changed"] is not before
          and type(interaction["checked_changed"]) is bool and interaction["checked_restored"] is before
          and wide["graphics"]["first_graphics_control"]["checked"] is before)
    portrait = detail["restored_portrait"]
    _fields(portrait, _PORTRAIT)
    _need(type(portrait["actual_rotation"]) is int and portrait["actual_rotation"] == 0
          and _extent(portrait["width_px"]) and _extent(portrait["height_px"])
          and portrait["height_px"] > portrait["width_px"]
          and portrait["interface_language"] == "ko" and portrait["console_selected"] is True)
    return deepcopy(detail)
