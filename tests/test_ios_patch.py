"""Verify IPA packaging without distributing or downloading game files."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
from unittest import mock
from zipfile import ZipFile

from idoly_local.client_patch import OFFICIAL_API, literal_rows
from idoly_local.ios_patch import IOSProfile, DEFAULT_BUNDLE_ID, macho_info, package_ios_client


APP = "Payload/Test Game.app/"
UNITY = APP + "Frameworks/UnityFramework.framework/UnityFramework"
METADATA = APP + "Data/Managed/Metadata/global-metadata.dat"


def metadata_fixture():
    header = [0] * 64
    header[:6] = [0xFAB11BAF, 31, 256, 8, 264, len(OFFICIAL_API)]
    return struct.pack("<64I", *header) + struct.pack("<II", len(OFFICIAL_API), 0) + OFFICIAL_API


def macho_fixture(cryptid=0, cpu=0x0100000C, marker=b""):
    header = struct.pack("<8I", 0xFEEDFACF, cpu, 0, 6, 1, 24, 0, 0)
    return header + struct.pack("<6I", 0x2C, 24, 0, 0, cryptid, 0) + marker


class IOSPackagingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "original.ipa"
        self.output = self.root / "local.ipa"
        self.metadata = metadata_fixture()
        self.unity = macho_fixture()
        self.main = macho_fixture(marker=b"launcher")
        self.info = {"CFBundleIdentifier": "game.qualiarts.idolypride", "CFBundleShortVersionString": "6.1.1",
                     "CFBundleVersion": "156", "CFBundleExecutable": "Test Game",
                     "CFBundleURLTypes": [{"CFBundleURLSchemes": ["idolypride.ios.app", "game.qualiarts.idolypride",
                                                                 "com.googleusercontent.apps.original"]}]}
        self.write_source()

    def write_source(self):
        self.members = {APP + "Info.plist": plistlib.dumps(self.info), UNITY: self.unity,
                        METADATA: self.metadata, APP + "Test Game": self.main,
                        APP + "Data/keep.bin": b"preserved game data", APP + "_CodeSignature/CodeResources": b"stale",
                        APP + "Frameworks/Child.framework/_CodeSignature/CodeResources": b"stale nested signature",
                        APP + "embedded.mobileprovision": b"stale profile"}
        with ZipFile(self.source, "w") as archive:
            for name, data in self.members.items():
                archive.writestr(name, data)
        sha = lambda data: hashlib.sha256(data).hexdigest()
        self.profile = IOSProfile(sha(self.source.read_bytes()), sha(self.unity), sha(self.metadata))

    def test_packages_isolated_client_and_preserves_unmodified_members(self):
        original_sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        endpoint = "http://a-long-local-server-name.example:50051"
        report = package_ios_client(self.source, self.output, endpoint, bootstrap=False, profile=self.profile)
        with ZipFile(self.output) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read(UNITY), self.unity)
            self.assertEqual(archive.read(APP + "Data/keep.bin"), b"preserved game data")
            self.assertFalse(any("/_CodeSignature/" in name or name.endswith("embedded.mobileprovision")
                                 for name in archive.namelist()))
            _, literals = literal_rows(archive.read(METADATA))
            self.assertEqual(literals[0][3], endpoint.encode())
            info = plistlib.loads(archive.read(APP + "Info.plist"))
            self.assertEqual(info["CFBundleIdentifier"], DEFAULT_BUNDLE_ID)
            self.assertEqual(info["CFBundleDisplayName"], "아이프라 로컬")
            self.assertEqual(info["CFBundleVersion"], "156.9001")
            self.assertEqual([scheme for item in info["CFBundleURLTypes"] for scheme in item["CFBundleURLSchemes"]],
                             [DEFAULT_BUNDLE_ID])
            self.assertTrue(info["NSAppTransportSecurity"]["NSAllowsArbitraryLoads"])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original_sha)
        self.assertEqual(report["output_sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertFalse(report["device_verified"])
        self.assertEqual(json.loads(self.output.with_suffix(".report.json").read_text())["bundle_id"], DEFAULT_BUNDLE_ID)

    def test_optional_native_patch_is_packaged_and_verified(self):
        native = self.root / "UnityFramework-patched"
        patched = macho_fixture(marker=b"explicit replacement")
        native.write_bytes(patched)
        report = package_ios_client(self.source, self.output, native_library=native, bootstrap=False, profile=self.profile)
        with ZipFile(self.output) as archive:
            self.assertEqual(archive.read(UNITY), patched)
        self.assertTrue(report["native_replacement"])
        self.assertEqual(report["output_unity"]["sha256"], hashlib.sha256(patched).hexdigest())

    def test_default_pipeline_applies_shared_native_bootstrap(self):
        patched = macho_fixture(marker=b"shared bootstrap patch")
        with mock.patch("idoly_local.native_bootstrap.patch_native", return_value=(patched, {"platform": "ios"})) as patch:
            report = package_ios_client(self.source, self.output, profile=self.profile)
        patch.assert_called_once_with(self.unity, "ios")
        self.assertEqual(report["bootstrap_patch"], {"platform": "ios"})
        with ZipFile(self.output) as archive:
            self.assertEqual(archive.read(UNITY), patched)

    def test_mismatched_source_or_payload_hash_fails_without_output(self):
        for profile in [replace(self.profile, ipa_sha256="0" * 64),
                        replace(self.profile, metadata_sha256="0" * 64),
                        replace(self.profile, unity_sha256="0" * 64)]:
            with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, "SHA-256"):
                package_ios_client(self.source, self.output, profile=profile)
            self.assertFalse(self.output.exists())

    def test_encrypted_native_or_main_executable_fails(self):
        for target in ["unity", "main"]:
            with self.subTest(target=target):
                self.unity = macho_fixture(cryptid=1) if target == "unity" else macho_fixture()
                self.main = macho_fixture(cryptid=1) if target == "main" else macho_fixture()
                self.write_source()
                with self.assertRaisesRegex(ValueError, "encrypted"):
                    package_ios_client(self.source, self.output, bootstrap=False, profile=self.profile)
                self.assertFalse(self.output.exists())

    def test_rejects_existing_output_and_installed_app_identities(self):
        for bundle in ["game.qualiarts.idolypride", "game.qualiarts.idolypride.kr", "other.bundle"]:
            with self.subTest(bundle=bundle), self.assertRaisesRegex(ValueError, "isolated"):
                package_ios_client(self.source, self.output, bundle_id=bundle, bootstrap=False, profile=self.profile)
        self.output.write_bytes(b"existing IPA")
        with self.assertRaisesRegex(ValueError, "already exists"):
            package_ios_client(self.source, self.output, bootstrap=False, profile=self.profile)
        self.assertEqual(self.output.read_bytes(), b"existing IPA")

    def test_identity_and_endpoint_validation_leave_no_output(self):
        with self.assertRaises(ValueError):
            package_ios_client(self.source, self.output, "http://user:pass@localhost", bootstrap=False, profile=self.profile)
        self.assertFalse(self.output.exists())
        self.info["CFBundleVersion"] = "157"
        self.write_source()
        with self.assertRaisesRegex(ValueError, "identity/version"):
            package_ios_client(self.source, self.output, bootstrap=False, profile=self.profile)
        self.assertFalse(self.output.exists())

    def test_rejects_non_arm64_and_malformed_macho(self):
        for data in [b"bad", macho_fixture(cpu=7), macho_fixture()[:40]]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                macho_info(data)


if __name__ == "__main__":
    unittest.main()
