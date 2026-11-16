#!/usr/bin/env python3
"""Calendar release labels and public filenames, separate from app build versions."""
from __future__ import annotations

import argparse
from datetime import date
import json
import re

# Raw names are immutable build/input identities; only publication names change.
ASSET_TEMPLATES = {
    "IdolyPride-Local-Server-Android.apk": "IdolyPride-{version}-Server-Android.apk",
    "IdolyPride-Local-Server-macOS-arm64.app.zip": "IdolyPride-{version}-Server-macOS-arm64.app.zip",
    "IdolyPride-6.1.1-Unified-iOS.ipa": "IdolyPride-{version}-Unified-iOS.ipa",
    "IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk": "IdolyPride-{version}-Client-Android-arm64-ko.apk",
    "IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ja.apk": "IdolyPride-{version}-Client-Android-arm64-ja.apk",
    "IdolyPride-Local-Graphics-Diagnostic-Android-arm64-en.apk": "IdolyPride-{version}-Client-Android-arm64-en.apk",
    "IdolyPride-6.1.1-Local-PlayCover-ko.ipa": "IdolyPride-{version}-Client-PlayCover-ko.ipa",
}


def resolve_release_version(value):
    """Require YYYY.MM.DD.N: a real date and an unpadded sequence from 1 to 99."""
    match = re.fullmatch(r"([0-9]{4})\.([0-9]{2})\.([0-9]{2})\.([1-9][0-9]?)", value) if type(value) is str else None
    if match is None:
        raise ValueError("release_version_invalid")
    try:
        date(*(int(part) for part in match.groups()[:3]))
    except ValueError:
        raise ValueError("release_version_invalid") from None
    return value


def release_tag(version):
    return "v" + resolve_release_version(version)


def asset_name(source_name, version):
    version = resolve_release_version(version)
    if type(source_name) is not str or source_name not in ASSET_TEMPLATES:
        raise ValueError("release_asset_source_unknown")
    return ASSET_TEMPLATES[source_name].format(version=version)


def asset_names(version):
    return frozenset(asset_name(name, version) for name in ASSET_TEMPLATES)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Release date in Asia/Seoul, YYYY.MM.DD.N")
    args = parser.parse_args(argv)
    try:
        version = resolve_release_version(args.version)
    except ValueError:
        parser.error("expected a valid YYYY.MM.DD.N release version (sequence 1..99)")
    print(json.dumps({"release_version": version, "tag": release_tag(version),
        "date_timezone": "Asia/Seoul",
        "filenames": {name: asset_name(name, version) for name in ASSET_TEMPLATES}}, indent=2))


if __name__ == "__main__":
    main()
