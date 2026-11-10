"""Read-only admission checks for the explicitly supported disposable QA guests.

These are accidental-target guards, not attestation: Android properties can be
spoofed. Never change properties to make a device pass. The Cuttlefish branch
matches the observed official ARM64-only userdebug guest without native bridge;
it does not admit arbitrary network ADB devices or physical phones.
"""
from __future__ import annotations

import re


_CUTTLEFISH_SERIAL = "127.0.0.1:6520"
_CUTTLEFISH_PROPERTIES = (
    ("ro.hardware", "cutf_cvm"),
    ("ro.boot.hardware", "cutf_cvm"),
    ("ro.product.device", "vsoc_arm64_only"),
    ("ro.product.cpu.abi", "arm64-v8a"),
    ("ro.product.cpu.abilist", "arm64-v8a"),
    ("ro.dalvik.vm.native.bridge", "0"),
    ("ro.build.type", "userdebug"),
    # Unlike the stock Android Emulator, this Cuttlefish guest leaves it unset.
    ("ro.kernel.qemu", ""),
)
_ERROR = "Native QA accepts a supported disposable emulator only"


def verify_disposable_target(adb, serial):
    """Read fixed properties before installs, UI input or private data access."""
    if isinstance(serial, str) and re.fullmatch(r"emulator-[0-9]+", serial):
        if adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
            raise RuntimeError(_ERROR)
        # Preserve the legacy Google Emulator branch, including translated ARM
        # runs. It must never be reported as the Cuttlefish native ARM proof.
        return {"kind": "android_emulator", "ro.kernel.qemu": "1"}
    if serial != _CUTTLEFISH_SERIAL:
        raise RuntimeError(_ERROR)
    observed = {}
    for name, expected in _CUTTLEFISH_PROPERTIES:
        value = adb("shell", "getprop", name).strip()
        if value != expected:
            raise RuntimeError(_ERROR)
        observed[name] = value
    return {"kind": "cuttlefish_arm64_only", **observed}
