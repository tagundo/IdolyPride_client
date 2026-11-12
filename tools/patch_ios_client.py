#!/usr/bin/env python3
"""Package an isolated PlayCover IPA connected to a local Idoly Pride server."""
from __future__ import annotations

import argparse
from pathlib import Path
import plistlib
import struct
import sys
from zipfile import BadZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from idoly_local.ios_patch import DEFAULT_BUNDLE_ID, DEFAULT_ENDPOINT, package_ios_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client", type=Path, help="Verified original decrypted 6.1.1 IPA")
    parser.add_argument("--output", type=Path, required=True, help="New IPA filename (existing files are preserved)")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="Local HTTP(S) gRPC origin (Octo uses loopback port 8080)")
    parser.add_argument("--native-library", type=Path, help="Optional separately patched ARM64 UnityFramework")
    parser.add_argument("--presentation-library", type=Path, help="Optional ARM64 presentation dylib (requires --presentation-plan)")
    parser.add_argument("--presentation-plan", type=Path, help="Verified static presentation patch plan (requires --presentation-library)")
    parser.add_argument("--host-only", action="store_true", help="Diagnostic: omit native bootstrap hooks; incompatible with presentation")
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID, help="Isolated game.qualiarts.idolypride.local identity")
    args = parser.parse_args()
    try:
        report = package_ios_client(args.client, args.output, args.endpoint,
                                    native_library=args.native_library,
                                    presentation_library=args.presentation_library,
                                    presentation_plan=args.presentation_plan,
                                    bundle_id=args.bundle_id, bootstrap=not args.host_only)
    except (ValueError, OSError, KeyError, BadZipFile, struct.error, plistlib.InvalidFileException) as exc:
        parser.exit(1, f"iOS client packaging failed: {exc}\n")
    print(args.output)
    print(f"Bundle {report['bundle_id']} → {report['endpoint']}")
    print("Import in PlayCover for re-signing. Device connection/bootstrap remains unverified.")


if __name__ == "__main__":
    main()
