#!/usr/bin/env python3
"""Prepare locked iOS render gateways before compiling the matching dylib."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from idoly_local.ios_presentation import prepare_presentation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ipa", type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--header", required=True, type=Path)
    args = parser.parse_args()
    plan = prepare_presentation(args.ipa, args.plan, args.header)
    print("Prepared", len(plan["entries"]), "original iOS gateways; runtime remains unverified")


if __name__ == "__main__":
    main()
