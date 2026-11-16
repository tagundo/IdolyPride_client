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
_DETAIL = {"authority", "sdk", "languages", "wide", "restored_portrait"}
_LANGUAGE = {"language", "title", "start", "stop", "actual_ui_observed"}
_WIDE_PANEL = {"width_px", "height_px", "density_dpi", "visible_categories",
               "minimum_navigation_target_dp", "help_closed", "default_panel", "default_panel_expanded"}
_PORTRAIT = {"actual_rotation", "width_px", "height_px", "interface_language", "console_selected"}


def _need(condition):
    if not condition:
        raise ValueError("android_public_os_interface_scope_differs")


def _fields(value, names):
    _need(type(value) is dict and set(value) == names)


def _extent(value):
    return type(value) is int and 1 <= value <= 16384


def _panel(value, *, graphics):
    _fields(value, _WIDE_PANEL)
    width, height, dpi = value["width_px"], value["height_px"], value["density_dpi"]
    target = value["minimum_navigation_target_dp"]
    _need(_extent(width) and _extent(height) and width > height
          and type(dpi) is int and 120 <= dpi <= 1000
          and type(value["visible_categories"]) is int and value["visible_categories"] == 5
          and type(target) is float and math.isfinite(target)
          and 44.0 <= target <= min(width, height) * 160.0 / dpi
          and value["help_closed"] is True
          and value["default_panel"] == ("graphics" if graphics else "checks")
          and value["default_panel_expanded"] is graphics)
    return width, height, dpi


def validate_android(report):
    """Validate observations only; existing preservation/attempt gates stay separate."""
    if type(report) is not dict or FIELD not in report:
        raise ValueError("android_public_os_interface_not_passed")
    detail = report[FIELD]
    _fields(detail, _DETAIL)
    _need(detail["authority"] == AUTHORITY and type(detail["sdk"]) is int and detail["sdk"] == SDK
          and type(detail["languages"]) is list and len(detail["languages"]) == len(LANGUAGES))
    for value, language in zip(detail["languages"], LANGUAGES):
        _fields(value, _LANGUAGE)
        title, start, stop = READBACKS[language]
        _need(value["language"] == language and value["title"] == title + "  " + VERSION
              and value["start"] == start and value["stop"] == stop
              and value["actual_ui_observed"] is True)
    wide = detail["wide"]
    _fields(wide, {"console", "graphics", "actual_rotation"})
    _need(type(wide["actual_rotation"]) is int and wide["actual_rotation"] == 1)
    _need(_panel(wide["console"], graphics=False) == _panel(wide["graphics"], graphics=True))
    portrait = detail["restored_portrait"]
    _fields(portrait, _PORTRAIT)
    _need(type(portrait["actual_rotation"]) is int and portrait["actual_rotation"] == 0
          and _extent(portrait["width_px"]) and _extent(portrait["height_px"])
          and portrait["height_px"] > portrait["width_px"]
          and portrait["interface_language"] == "ko" and portrait["console_selected"] is True)
    return deepcopy(detail)
