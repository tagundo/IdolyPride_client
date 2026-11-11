#!/usr/bin/env python3
"""Fixed v0.3.2 draft staging entry point. Never publishes or selects a release.

Source/run/draft are trusted constants for one candidate. Incomplete or
unapproved asset/proof pins intentionally fail closed before API access. Root
approves those bytes only after actual receipts and independent review.
"""
from pathlib import Path
from reviewed_draft_adapter import bind

IDENTITY = ('tagundo/IdolyPride_client', 441084603, 'local-server-v0.3.2', '276b5552e77f4264b80ea40e00e95cc6576cdab9', 42930420770)
PIN_PATH = Path(__file__).with_name('reviewed-drafts') / 'local-server-v0.3.2.json'
ARTIFACT_NAMES = {
    'android': 'android-server-build-and-available-evidence-v0.3.2',
    'macos': 'macos-server-candidate-and-native-evidence-v0.3.2',
}


def configured_engine():
    return bind(identity=IDENTITY, pin_path=PIN_PATH,
                payload_name='IdolyPride-ServerData-v0.3.2.zip', artifact_names=ARTIFACT_NAMES)


def main():
    configured_engine().main()


if __name__ == '__main__': main()
