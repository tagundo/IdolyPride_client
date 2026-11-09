"""Check fail-closed native profiles and execute the ARM64 stubs with Unicorn."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from idoly_local import native_bootstrap as bootstrap

try:
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm64_const import (
        UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X8,
        UC_ARM64_REG_X19, UC_ARM64_REG_X30, UC_ARM64_REG_PC, UC_ARM64_REG_SP,
    )
except ImportError:
    Uc = None


def fixture_profile():
    raw = bytearray(b"\xaa" * 512)
    host = bytes(range(16))
    entry = bytes(range(32, 64))
    raw[32:48] = host
    raw[128:160] = entry
    profile = bootstrap._Profile(
        hashlib.sha256(raw).hexdigest(), 0x4000, 32, host.hex(),
        (bootstrap._Site("AccountManager.GetFirebaseIdTokenAsync", 0x2000, 128,
                         entry.hex(), "completed_token"),),
    )
    return bytes(raw), profile


class NativeProfileTests(unittest.TestCase):
    def test_unknown_platform_binary_and_non_bytes_are_rejected(self):
        for raw, platform in ((b"", "unknown"), (b"not the game", "android"), (bytearray(), "ios")):
            with self.subTest(platform=platform), self.assertRaises(ValueError):
                bootstrap.patch_native(raw, platform)

    def test_profile_applies_only_its_verified_range_and_has_json_report(self):
        raw, profile = fixture_profile()
        with patch.dict(bootstrap._PROFILES, android=profile):
            result, report = bootstrap.patch_native(raw, "android")
        self.assertEqual(len(result), len(raw))
        self.assertEqual(result[:128], raw[:128])
        self.assertEqual(result[160:], raw[160:])
        self.assertNotEqual(result[128:160], raw[128:160])
        self.assertEqual(report["input_sha256"], profile.sha256)
        self.assertEqual(report["output_sha256"], hashlib.sha256(result).hexdigest())
        self.assertFalse(report["device_verified"])
        json.dumps(report)

    def test_entry_checks_remain_required_after_hash_validation(self):
        raw, profile = fixture_profile()
        wrong_host = replace(profile, host_expected="00" * 16)
        wrong_entry = replace(profile, sites=(replace(profile.sites[0], expected="00" * 32),))
        for invalid, message in ((wrong_host, "GetHost entry"), (wrong_entry, "entry does not match")):
            with self.subTest(message=message), patch.dict(bootstrap._PROFILES, android=invalid):
                with self.assertRaisesRegex(ValueError, message):
                    bootstrap.patch_native(raw, "android")

    def test_truncated_entry_and_patch_larger_than_verified_prefix_are_rejected(self):
        raw, profile = fixture_profile()
        shortened = replace(profile, sites=(replace(profile.sites[0], expected=profile.sites[0].expected[:32]),))
        outside = replace(profile, sites=(replace(profile.sites[0], offset=len(raw) - 1),))
        for invalid in (shortened, outside):
            with self.subTest(profile=invalid), patch.dict(bootstrap._PROFILES, android=invalid):
                with self.assertRaises(ValueError):
                    bootstrap.patch_native(raw, "android")

    def test_arm64_branch_alignment_and_range_are_enforced(self):
        for source, target in ((0, 1), (0, 1 << 27), (0, -(1 << 27) - 4)):
            with self.subTest(target=target), self.assertRaises(ValueError):
                bootstrap._branch(source, target)
        self.assertEqual(bootstrap._branch(4, 0), 0x17FFFFFF)
        self.assertEqual(bootstrap._branch(0, 4, link=True), 0x94000001)

    def test_all_profiles_verify_every_overwritten_byte(self):
        for platform, profile in bootstrap._PROFILES.items():
            for site in profile.sites:
                with self.subTest(platform=platform, method=site.name):
                    self.assertLessEqual(len(bootstrap._replacement(site, profile.host_rva)), len(bytes.fromhex(site.expected)))


@unittest.skipUnless(Uc is not None, "Optional Unicorn emulator is unavailable")
class Arm64ExecutionTests(unittest.TestCase):
    def test_all_stubs_return_completed_results_and_preserve_aapcs64(self):
        for platform, profile in bootstrap._PROFILES.items():
            for site in profile.sites:
                with self.subTest(platform=platform, method=site.name):
                    emulator = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
                    for address in {site.rva & ~0xFFF, profile.host_rva & ~0xFFF, 0x77700000}:
                        emulator.mem_map(address, 0x1000)
                    emulator.mem_map(0x50000000, 0x2000)
                    emulator.mem_map(0x60000000, 0x1000)
                    emulator.mem_write(site.rva, bootstrap._replacement(site, profile.host_rva))
                    emulator.mem_write(profile.host_rva, struct.pack("<I", 0xD65F03C0))
                    emulator.mem_write(0x60000000, b"\xa5" * 32)
                    emulator.reg_write(UC_ARM64_REG_X0, 0x9999)
                    emulator.reg_write(UC_ARM64_REG_X1, 0xBBBB)
                    emulator.reg_write(UC_ARM64_REG_X8, 0x60000000)
                    emulator.reg_write(UC_ARM64_REG_X19, 0x1111222233334444)
                    emulator.reg_write(UC_ARM64_REG_X30, 0x77700000)
                    emulator.reg_write(UC_ARM64_REG_SP, 0x50001000)
                    calls = []

                    def get_host(machine, address, size, userdata):
                        if address != profile.host_rva:
                            return
                        calls.append(address)
                        self.assertEqual(machine.reg_read(UC_ARM64_REG_SP) % 16, 0)
                        if site.action == "completed_token":
                            self.assertEqual(machine.reg_read(UC_ARM64_REG_X0), 0)
                        # Simulate a managed string return and clobber caller-
                        # saved x8 to prove the original sret pointer is retained.
                        machine.reg_write(UC_ARM64_REG_X0, 0x70000000)
                        machine.reg_write(UC_ARM64_REG_X8, 0xDEADBEEF)
                        machine.reg_write(UC_ARM64_REG_PC, machine.reg_read(UC_ARM64_REG_X30))

                    emulator.hook_add(UC_HOOK_CODE, get_host)
                    emulator.emu_start(site.rva, 0x77700000, count=100)
                    self.assertEqual(emulator.reg_read(UC_ARM64_REG_PC), 0x77700000)
                    self.assertEqual(emulator.reg_read(UC_ARM64_REG_SP), 0x50001000)
                    self.assertEqual(emulator.reg_read(UC_ARM64_REG_X19), 0x1111222233334444)
                    self.assertEqual(emulator.reg_read(UC_ARM64_REG_X30), 0x77700000)
                    if site.action == "true":
                        self.assertEqual(emulator.reg_read(UC_ARM64_REG_X0), 1)
                    elif site.action == "completed_void":
                        self.assertEqual(emulator.reg_read(UC_ARM64_REG_X0), 0)
                        self.assertEqual(emulator.reg_read(UC_ARM64_REG_X1), 0)
                    elif site.action in ("completed_error", "completed_token"):
                        expected = (0, 0x70000000 if site.action == "completed_token" else 0, 0)
                        self.assertEqual(bytes(emulator.mem_read(0x60000000, 24)), struct.pack("<3Q", *expected))
                        self.assertEqual(bytes(emulator.mem_read(0x60000018, 8)), b"\xa5" * 8)
                    elif site.action == "host":
                        self.assertEqual(emulator.reg_read(UC_ARM64_REG_X0), 0x70000000)
                    self.assertEqual(len(calls), int(site.action in ("host", "completed_token")))


class ActualClientProfileTests(unittest.TestCase):
    def test_verified_local_client_images_when_available(self):
        paths = {
            "android": Path("/workspace/shared/artifacts/client-6.1.1/config.arm64_v8a/lib/arm64-v8a/libil2cpp.so"),
            "ios": Path("/workspace/shared/artifacts/ios-client-6.1.1/Payload/IDOLY PRIDE.app/Frameworks/UnityFramework.framework/UnityFramework"),
        }
        available = [(platform, path) for platform, path in paths.items() if path.is_file()]
        if not available:
            self.skipTest("Optional original client artifacts are unavailable")
        for platform, path in available:
            with self.subTest(platform=platform):
                raw = path.read_bytes()
                result, report = bootstrap.patch_native(raw, platform)
                self.assertEqual(len(result), len(raw))
                self.assertEqual(len(report["patches"]), 6)
                cursor = 0
                for entry in sorted(report["patches"], key=lambda item: int(item["file_offset"], 16)):
                    offset = int(entry["file_offset"], 16)
                    self.assertEqual(result[cursor:offset], raw[cursor:offset])
                    replacement = bytes.fromhex(entry["patched_hex"])
                    self.assertEqual(result[offset:offset + len(replacement)], replacement)
                    cursor = offset + len(replacement)
                self.assertEqual(result[cursor:], raw[cursor:])


if __name__ == "__main__":
    unittest.main()
