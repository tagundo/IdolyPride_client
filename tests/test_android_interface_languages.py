"""Every advertised Android interface language must own its complete resources.

Android silently falls back to the unqualified Korean resources for absent keys.
These checks catch that fallback before the actual public LocaleManager UI smoke
checks run; numeric spinner values and format arguments retain their meaning.
"""
from collections import Counter
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "android-server/app/src/main/res"
ANDROID = "{http://schemas.android.com/apk/res/android}"
LANGUAGE_FOLDERS = {"ko": "values-ko", "ja": "values-ja", "en": "values-en"}
FORMAT = re.compile(r"%(?:(?P<index>[1-9][0-9]*)\$)?(?P<flags>[-#+ 0,(<]*)(?:[0-9]+)?(?:\.[0-9]+)?(?P<date>[tT])?(?P<conversion>[a-zA-Z%])")
NUMBERS = re.compile(r"(?<![A-Za-z0-9_])[-+]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")
TECHNICAL_OPTIONS = re.compile(r"(?<![A-Za-z0-9_])(?:Android|iOS|PlayCover|FXAA|SMAA|fps|px|ID)(?![A-Za-z0-9_])|Downloads/IdolyPride", re.IGNORECASE)
KOREAN = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")


def resources(folder):
    tree = ET.parse(RESOURCES / folder / "strings.xml").getroot()
    assert tree.tag == "resources"
    entries = {}
    for entry in tree:
        name = entry.get("name")
        assert name, f"{folder}: every resource needs a name"
        assert name not in entries, f"{folder}: duplicate resource {name}"
        assert entry.tag in ("string", "string-array"), f"{folder}/{name}: unchecked resource type"
        entries[name] = entry
    return entries


def values(entry):
    if entry.tag == "string":
        return ["".join(entry.itertext())]
    assert all(child.tag == "item" for child in entry), f"{entry.get('name')}: array has a non-item child"
    return ["".join(child.itertext()) for child in entry]


def format_arguments(text):
    """Keep Java Formatter argument identity/type, allowing translated ordering."""
    result = Counter()
    next_argument, previous = 1, None
    for match in FORMAT.finditer(text):
        conversion = match["conversion"]
        if conversion in ("%", "n") and match["date"] is None:
            result[("literal", conversion)] += 1
            continue
        if match["index"]:
            argument = int(match["index"])
        elif "<" in match["flags"]:
            assert previous is not None, "format reuse has no previous argument"
            argument = previous
        else:
            argument, next_argument = next_argument, next_argument + 1
        previous = argument
        result[(argument, (match["date"] or "") + conversion)] += 1
    return result


@pytest.mark.parametrize("language", ("en", "ja"))
def test_advertised_interface_has_every_resource_without_korean_fallback(language):
    original = resources("values")
    translated = resources(LANGUAGE_FOLDERS[language])
    assert translated.keys() == original.keys(), (
        f"{language}: missing={sorted(original.keys() - translated.keys())}; "
        f"extra={sorted(translated.keys() - original.keys())}"
    )
    for name, source in original.items():
        target = translated[name]
        assert target.tag == source.tag, f"{language}/{name}: resource type differs"
        source_values, target_values = values(source), values(target)
        assert len(target_values) == len(source_values), f"{language}/{name}: array length/order differs"
        assert source_values and all(text.strip() for text in source_values), f"ko/{name}: empty resource"
        assert all(text.strip() for text in target_values), f"{language}/{name}: empty resource"
        for index, (before, after) in enumerate(zip(source_values, target_values)):
            location = f"{language}/{name}[{index}]"
            assert format_arguments(after) == format_arguments(before), f"{location}: format arguments differ"
            if source.tag == "string-array":
                # The selected array index maps directly to a fixed native enum.
                # Keep numeric values, ID/platform names and AA modes in their
                # original slots without prescribing the translated prose.
                assert NUMBERS.findall(after) == NUMBERS.findall(before), f"{location}: numeric option moved"
                technical_before = [token.casefold() for token in TECHNICAL_OPTIONS.findall(before)]
                technical_after = [token.casefold() for token in TECHNICAL_OPTIONS.findall(after)]
                assert technical_after == technical_before, f"{location}: technical option moved"
            # Units, enum names and format-only templates may stay identical.
            # Korean copied as prose would reproduce the mixed-language defect.
            # A language chooser may intentionally retain a language's autonym.
            if KOREAN.search(before) and name != "library_language_options":
                assert after != before, f"{location}: untranslated Korean resource"



def test_explicit_korean_keeps_system_english_fallback_from_overriding_selected_korean():
    original = RESOURCES / "values/strings.xml"
    explicit = RESOURCES / "values-ko/strings.xml"
    assert explicit.read_bytes() == original.read_bytes(), "explicit Korean must stay byte-identical to the default resources"
    baseline, korean = resources("values"), resources("values-ko")
    assert korean.keys() == baseline.keys()
    assert all(korean[key].tag == baseline[key].tag and values(korean[key]) == values(baseline[key])
               for key in baseline), "explicit/default Korean resources differ"


def test_android_system_language_settings_advertise_only_complete_interfaces():
    manifest = ET.parse(ROOT / "android-server/app/src/main/AndroidManifest.xml").getroot()
    application = manifest.find("application")
    assert application is not None
    assert application.get(ANDROID + "localeConfig") == "@xml/locales_config"
    config = ET.parse(RESOURCES / "xml/locales_config.xml").getroot()
    assert config.tag == "locale-config"
    assert all(child.tag == "locale" for child in config)
    supported = [child.get(ANDROID + "name") for child in config]
    assert len(supported) == len(set(supported)) == len(LANGUAGE_FOLDERS)
    assert set(supported) == LANGUAGE_FOLDERS.keys()
    for language in supported:
        assert resources(LANGUAGE_FOLDERS[language]), f"{language}: advertised language has no resources"
    assert KOREAN.search(values(resources("values")["app_name"])[0]), "unqualified interface should remain Korean"


def test_format_argument_check_allows_reordering_but_rejects_missing_or_retyped_values():
    original = "%1$s / %2$d · %1$s"
    assert format_arguments("%2$d · %1$s / %1$s") == format_arguments(original)
    assert format_arguments("%1$s / %2$d") != format_arguments(original)
    assert format_arguments("%1$s / %2$s · %1$s") != format_arguments(original)
    assert format_arguments("%s %d") == format_arguments("%1$s %2$d")
    assert format_arguments("%1$s %<s %%") == format_arguments("%1$s %1$s %%")
