#!/usr/bin/env python3
"""Build a separately installed, signed Idoly Pride local Android client."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from idoly_local.android_package import AndroidPackagingError, LOCAL_PACKAGE, package_android


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Original standalone APK or ARM64 XAPK")
    parser.add_argument("--output", type=Path, required=True, help="A new signed APK; existing files are preserved")
    parser.add_argument("--endpoint", default="http://127.0.0.1:50051")
    parser.add_argument("--package", default=LOCAL_PACKAGE)
    parser.add_argument("--label", default="아이프라 로컬")
    parser.add_argument("--apkeditor", type=Path, help="APKEditor.jar (defaults to sibling ipr-patcher)")
    parser.add_argument("--build-tools", type=Path, help="Android SDK build-tools directory")
    parser.add_argument("--java", help="JDK java executable")
    parser.add_argument("--native-library", type=Path, help="Optional same-layout prepatched ARM64 libil2cpp.so")
    parser.add_argument("--keystore", type=Path, help="Existing signing key; otherwise create a persistent local development key")
    parser.add_argument("--alias", default="idoly-local")
    parser.add_argument("--storepass-env", default="IDOLY_CLIENT_KEYSTORE_PASSWORD")
    parser.add_argument("--keypass-env")
    parser.add_argument("--signing-dir", type=Path, help="Private storage for the generated key/password pair")
    args = parser.parse_args()
    try:
        report = package_android(args.source, args.output, endpoint=args.endpoint, package=args.package,
            label=args.label, apkeditor=args.apkeditor, build_tools=args.build_tools, java=args.java,
            native_library=args.native_library, keystore=args.keystore, alias=args.alias,
            storepass_env=args.storepass_env, keypass_env=args.keypass_env, signing_dir=args.signing_dir)
    except (AndroidPackagingError, OSError, ValueError) as error:
        raise SystemExit(f"Error: {error}") from None
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
