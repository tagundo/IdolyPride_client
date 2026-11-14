"""Verify IPA packaging without distributing or downloading game files."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock
from zipfile import ZipFile

from idoly_local.client_patch import OFFICIAL_API, literal_rows
from idoly_local.ios_patch import (IOSProfile, DEFAULT_BUNDLE_ID, _add_presentation_load,
                                   _patch_octo_origin, _patch_unity_http, macho_info, package_ios_client)


APP = "Payload/Test Game.app/"
UNITY = APP + "Frameworks/UnityFramework.framework/UnityFramework"
METADATA = APP + "Data/Managed/Metadata/global-metadata.dat"
SETTINGS = APP + "Data/globalgamemanagers"
OCTO = b"https://api.octo-cloud.com/"


def metadata_fixture():
    header = [0] * 64
    literals = OFFICIAL_API + OCTO
    header[:6] = [0xFAB11BAF, 31, 256, 16, 272, len(literals)]
    return (struct.pack("<64I", *header) + struct.pack("<4I", len(OFFICIAL_API), 0, len(OCTO), len(OFFICIAL_API))
            + literals)


def settings_fixture():
    data = bytearray(2124)
    struct.pack_into(">I", data, 8, 22)
    struct.pack_into(">Q", data, 32, 1264)
    return bytes(data)


def macho_fixture(cryptid=0, cpu=0x0100000C, marker=b""):
    header = struct.pack("<8I", 0xFEEDFACF, cpu, 0, 6, 1, 24, 0, 0)
    return header + struct.pack("<6I", 0x2C, 24, 0, 0, cryptid, 0) + marker


def padded_macho_fixture(section_offset=512):
    data = bytearray(1024)
    encryption = struct.pack("<6I", 0x2C, 24, 0, 0, 0, 0)
    segment = struct.pack("<II16s4QiiII", 0x19, 152, b"__TEXT", 0, len(data),
                          0, len(data), 5, 5, 1, 0)
    section = struct.pack("<16s16sQQ8I", b"__text", b"__TEXT", section_offset, 16,
                          section_offset, 2, 0, 0, 0x80000400, 0, 0, 0)
    commands = encryption + segment + section
    data[:32] = struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 6, 2, len(commands), 0, 0)
    data[32:32 + len(commands)] = commands
    data[section_offset:section_offset + 16] = b"original code!!!"
    return bytes(data)


class IOSPackagingTests(unittest.TestCase):
    def setUp(self):
        # The small synthetic metadata has two literals, not the real 6.1.1
        # toast index. Its version-locked writer has separate real-layout tests.
        display = mock.patch('idoly_local.ui_display_literals.patch_bytes',
            side_effect=lambda raw, *args, **kwargs: (raw,
                {'output_sha256': hashlib.sha256(raw).hexdigest(), 'changed_indexes': []}))
        display.start()
        self.addCleanup(display.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "original.ipa"
        self.output = self.root / "local.ipa"
        self.metadata = metadata_fixture()
        self.settings = settings_fixture()
        self.unity = macho_fixture()
        self.main = macho_fixture(marker=b"launcher")
        self.info = {"CFBundleIdentifier": "game.qualiarts.idolypride", "CFBundleShortVersionString": "6.1.1",
                     "CFBundleVersion": "156", "CFBundleExecutable": "Test Game",
                     "CFBundleURLTypes": [{"CFBundleURLSchemes": ["idolypride.ios.app", "game.qualiarts.idolypride",
                                                                 "com.googleusercontent.apps.original"]}]}
        self.write_source()

    def write_source(self):
        self.members = {APP + "Info.plist": plistlib.dumps(self.info), UNITY: self.unity,
                        METADATA: self.metadata, SETTINGS: self.settings, APP + "Test Game": self.main,
                        APP + "Data/keep.bin": b"preserved game data", APP + "_CodeSignature/CodeResources": b"stale",
                        APP + "Frameworks/Child.framework/_CodeSignature/CodeResources": b"stale nested signature",
                        APP + "embedded.mobileprovision": b"stale profile"}
        with ZipFile(self.source, "w") as archive:
            for name, data in self.members.items():
                archive.writestr(name, data)
        sha = lambda data: hashlib.sha256(data).hexdigest()
        patched_settings = bytearray(self.settings)
        struct.pack_into("<i", patched_settings, 2120, 2)
        self.profile = IOSProfile(sha(self.source.read_bytes()), sha(self.unity), sha(self.metadata),
                                  octo_literal_index=1, unity_settings_sha256=sha(self.settings),
                                  unity_settings_patched_sha256=sha(patched_settings),
                                  unity_settings_size=len(self.settings))

    def test_fixed_ui_resource_is_streamed_and_verified_without_reading_whole_asset(self):
        from unittest.mock import patch
        from dataclasses import replace
        ui_name = APP + "Data/resources.assets"
        source_ui, localized_ui = b"original UI resource", b"translated English UI resource"
        with ZipFile(self.source, "a") as archive:
            archive.writestr(ui_name, source_ui)
        profile = replace(self.profile, ipa_sha256=hashlib.sha256(self.source.read_bytes()).hexdigest())
        actual_read = ZipFile.read
        def bounded_read(archive, name, *args, **kwargs):
            if name == ui_name:
                raise AssertionError("The complete UI member must use forward ZIP streams")
            return actual_read(archive, name, *args, **kwargs)
        def ui_stream(source, destination, **kwargs):
            self.assertEqual((kwargs["ui_csv"], kwargs["language"]), (b"compiled CSV", "en"))
            self.assertEqual(source.read(), source_ui)
            self.assertEqual(destination.write(localized_ui), len(localized_ui))
            return {"language": "en", "output_asset_bytes": len(localized_ui),
                    "output_asset_sha256": hashlib.sha256(localized_ui).hexdigest(),
                    "ui_translation": {"language": "en"}, "changed_static_texts": 3}
        with patch("idoly_local.ui_assets.load_package_inputs", return_value=(b"compiled CSV", {})), \
                patch("idoly_local.static_ui_assets.patch_ios_stream", side_effect=ui_stream), \
                patch.object(ZipFile, "read", bounded_read):
            report = package_ios_client(self.source, self.output, bootstrap=False, profile=profile,
                                        ui_language="en", ui_csv_file=self.root/"compiled.csv",
                                        ui_proof_file=self.root/"proof.json")
        with ZipFile(self.output) as archive:
            self.assertEqual(archive.read(ui_name), localized_ui)
            self.assertEqual(archive.read(APP + "Data/keep.bin"), b"preserved game data")
        self.assertEqual(report["ui_language"], "en")
        self.assertEqual(report["ui_translation"]["output_asset_sha256"], hashlib.sha256(localized_ui).hexdigest())
        self.assertEqual(report["static_ui_translation"]["changed_static_texts"], 3)

    def test_missing_fixed_ui_inputs_are_rejected_before_source_is_opened(self):
        with self.assertRaisesRegex(ValueError, "requires CSV"):
            package_ios_client(self.root/"missing.ipa", self.output, ui_language="ko")

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
            self.assertEqual(literals[1][3], b"http://127.0.0.1:8080/")
            self.assertEqual(struct.unpack_from("<i", archive.read(SETTINGS), 2120)[0], 2)
            info = plistlib.loads(archive.read(APP + "Info.plist"))
            self.assertEqual(info["CFBundleIdentifier"], DEFAULT_BUNDLE_ID)
            self.assertEqual(info["CFBundleDisplayName"], "아이프라 로컬")
            self.assertEqual(info["CFBundleVersion"], "156.9004")
            self.assertEqual([scheme for item in info["CFBundleURLTypes"] for scheme in item["CFBundleURLSchemes"]],
                             [DEFAULT_BUNDLE_ID])
            self.assertTrue(info["NSAppTransportSecurity"]["NSAllowsArbitraryLoads"])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original_sha)
        self.assertEqual(report["output_sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertFalse(report["device_verified"])
        self.assertEqual(json.loads(self.output.with_suffix(".report.json").read_text())["bundle_id"], DEFAULT_BUNDLE_ID)

    def test_https_api_still_allows_the_http_loopback_resource_origin(self):
        package_ios_client(self.source, self.output, "https://local.example:50051",
                           bootstrap=False, profile=self.profile)
        with ZipFile(self.output) as archive:
            info = plistlib.loads(archive.read(APP + "Info.plist"))
            self.assertTrue(info["NSAppTransportSecurity"]["NSAllowsArbitraryLoads"])
            _, literals = literal_rows(archive.read(METADATA))
            self.assertEqual(literals[0][3], b"https://local.example:50051")
            self.assertEqual(literals[1][3], b"http://127.0.0.1:8080/")

    def test_octo_patch_preserves_layout_and_rejects_wrong_or_overlapping_literals(self):
        patched, report = _patch_octo_origin(self.metadata, 1)
        self.assertEqual(len(patched), len(self.metadata))
        self.assertEqual(patched[:256], self.metadata[:256])
        self.assertEqual(struct.unpack_from("<I", patched, 268)[0], len(OFFICIAL_API))
        self.assertEqual(literal_rows(patched)[1][1][3], b"http://127.0.0.1:8080/")
        self.assertTrue(report["metadata_layout_preserved"])
        with self.assertRaisesRegex(ValueError, "profile"):
            _patch_octo_origin(self.metadata, 0)
        with self.assertRaisesRegex(ValueError, "profile"):
            _patch_octo_origin(patched, 1)
        header = [0] * 64
        literals = OFFICIAL_API + OCTO
        header[:6] = [0xFAB11BAF, 31, 256, 24, 280, len(literals)]
        overlap = (struct.pack("<64I", *header)
                   + struct.pack("<6I", len(OFFICIAL_API), 0, len(OCTO), len(OFFICIAL_API), 5, len(OFFICIAL_API))
                   + literals)
        with self.assertRaisesRegex(ValueError, "overlaps"):
            _patch_octo_origin(overlap, 1)

    def test_unity_http_patch_is_fingerprint_locked_and_changes_only_transport(self):
        patched, report = _patch_unity_http(self.settings, self.profile)
        self.assertEqual(patched[:2120], self.settings[:2120])
        self.assertEqual(patched[2124:], self.settings[2124:])
        self.assertEqual(struct.unpack_from("<i", patched, 2120)[0], 2)
        self.assertEqual(report["field"], "insecureHttpOption")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            _patch_unity_http(patched, self.profile)
        with self.assertRaisesRegex(ValueError, "output SHA-256"):
            _patch_unity_http(self.settings, replace(self.profile, unity_settings_patched_sha256="0" * 64))

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

    def presentation_inputs(self):
        self.unity = padded_macho_fixture()
        self.write_source()
        library = self.root / "presentation.dylib"
        library.write_bytes(macho_fixture(marker=b"presentation library"))
        plan = self.root / "presentation-plan.json"
        plan.write_text(json.dumps({"schema": 1, "fixture": True, "profile_header_sha256": "a" * 64}))
        library.with_suffix(".build.json").write_text(json.dumps({
            "schema": 1, "target": "arm64-apple-ios13.0", "profile_header_sha256": "a" * 64,
            "sha256": hashlib.sha256(library.read_bytes()).hexdigest(), "bytes": library.stat().st_size}))
        return library, plan

    def test_presentation_composes_bootstrap_and_embeds_matching_loaded_library(self):
        library, plan = self.presentation_inputs()
        original_sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        bootstrap_native = self.unity[:-1] + b"B"
        graphics_native = bootstrap_native[:-2] + b"G" + bootstrap_native[-1:]
        bootstrap_report = {"platform": "ios", "fixture": "bootstrap"}
        presentation = types.ModuleType("idoly_local.ios_presentation")
        presentation.patch_presentation = mock.Mock(return_value=(graphics_native, {"fixture": "graphics"}))
        with mock.patch("idoly_local.native_bootstrap.patch_native",
                        return_value=(bootstrap_native, bootstrap_report)) as bootstrap, \
                mock.patch.dict(sys.modules, {presentation.__name__: presentation}):
            report = package_ios_client(self.source, self.output, presentation_library=library,
                                        presentation_plan=plan, profile=self.profile)
        bootstrap.assert_called_once_with(self.unity, "ios")
        presentation.patch_presentation.assert_called_once_with(
            bootstrap_native, {"schema": 1, "fixture": True, "profile_header_sha256": "a" * 64},
            bootstrap_report=bootstrap_report)
        with ZipFile(self.output) as archive:
            embedded = APP + "Frameworks/IdolyPresentation.dylib"
            self.assertEqual(archive.read(embedded), library.read_bytes())
            self.assertEqual((archive.getinfo(embedded).external_attr >> 16) & 0o777, 0o755)
            final_native = archive.read(UNITY)
            self.assertIn(b"@loader_path/../IdolyPresentation.dylib\0", final_native)
            self.assertEqual(final_native[512:], graphics_native[512:])
            self.assertEqual(plistlib.loads(archive.read(APP + "Info.plist"))["CFBundleIdentifier"],
                             DEFAULT_BUNDLE_ID)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original_sha)
        self.assertTrue(report["presentation_patch"]["bootstrap_composed"])
        self.assertEqual(report["presentation_patch"]["plan_sha256"], hashlib.sha256(plan.read_bytes()).hexdigest())
        self.assertEqual(report["presentation_patch"]["library"]["sha256"], hashlib.sha256(library.read_bytes()).hexdigest())
        self.assertEqual(report["presentation_patch"]["build_receipt"]["name"], "presentation.build.json")
        self.assertFalse(report["presentation_patch"]["device_verified"])

    def test_presentation_rejects_partial_pairs_and_ambiguous_native_modes(self):
        library, plan = self.presentation_inputs()
        cases = [{"presentation_library": library}, {"presentation_plan": plan},
                 {"presentation_library": library, "presentation_plan": plan, "native_library": library},
                 {"presentation_library": library, "presentation_plan": plan, "bootstrap": False}]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                package_ios_client(self.source, self.output, profile=self.profile, **kwargs)
            self.assertFalse(self.output.exists())

    def test_font_asset_and_native_hook_must_be_supplied_together_before_source_read(self):
        library, plan = self.presentation_inputs()
        valid_plan = json.loads(plan.read_text())
        for font_hooks, supplied_font in [(True, False), (False, True)]:
            plan.write_text(json.dumps({**valid_plan, 'hook_names': ['font_awake'] if font_hooks else []}))
            kwargs = {'font_file': self.root/'explicit.otf'} if supplied_font else {}
            with self.subTest(font_hooks=font_hooks, supplied_font=supplied_font), \
                    mock.patch('idoly_local.ios_patch._file_sha256', side_effect=AssertionError('source read')), \
                    self.assertRaisesRegex(ValueError, 'supplied together'):
                package_ios_client(self.source, self.output, presentation_library=library,
                                   presentation_plan=plan, profile=self.profile, **kwargs)
            self.assertFalse(self.output.exists())
        with self.assertRaisesRegex(ValueError, 'license requires'):
            package_ios_client(self.source, self.output, font_license_file=self.root/'OFL.txt')
        with self.assertRaisesRegex(ValueError, 'native presentation fallback'):
            package_ios_client(self.source, self.output, font_file=self.root/'explicit.otf')

    def test_font_package_replaces_declared_asset_and_embeds_exact_notices(self):
        library, plan = self.presentation_inputs()
        document = json.loads(plan.read_text())
        plan.write_text(json.dumps({**document, 'hook_names': ['font_awake']}))
        asset = APP+'Data/sharedassets0.assets'
        with ZipFile(self.source, 'a') as archive:
            archive.writestr(asset, b'original font asset')
        profile = replace(self.profile, ipa_sha256=hashlib.sha256(self.source.read_bytes()).hexdigest())
        presentation = types.ModuleType('idoly_local.ios_presentation')
        presentation.patch_presentation = mock.Mock(return_value=(self.unity, {}))
        notices = {'IdolyFontSupport.json': b'font proof', 'OFL-Pretendard.txt': b'exact license'}
        with mock.patch('idoly_local.native_bootstrap.patch_native', return_value=(self.unity, {'platform':'ios'})), \
                mock.patch.dict(sys.modules, {presentation.__name__: presentation}), \
                mock.patch('idoly_local.font_assets.read_font', return_value=(b'font bytes', {})), \
                mock.patch('idoly_local.font_assets.read_license', return_value=b'exact license'), \
                mock.patch('idoly_local.font_assets.patch_bytes', return_value=(b'patched font asset', {'policy':'hangul-font-v2-original-dashes'})) as patch, \
                mock.patch('idoly_local.font_assets.package_notices', return_value=notices):
            report = package_ios_client(self.source, self.output, presentation_library=library,
                                        presentation_plan=plan, font_file=self.root/'font.otf', profile=profile)
        patch.assert_called_once_with(b'original font asset', b'font bytes', 'ios')
        with ZipFile(self.output) as archive:
            self.assertEqual(archive.read(asset), b'patched font asset')
            self.assertEqual(archive.read(APP+'Data/keep.bin'), b'preserved game data')
            self.assertEqual(plistlib.loads(archive.read(APP+'Info.plist'))['CFBundleVersion'], '156.9006')
            for name, raw in notices.items():
                member = APP+'IdolyFonts/'+name
                self.assertEqual(archive.read(member), raw)
                self.assertEqual(report['font_support']['notice_members'][member],
                                 {'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()})
        self.assertEqual(report['font_support']['output_members'][asset]['sha256'],
                         hashlib.sha256(b'patched font asset').hexdigest())

    def test_presentation_rejects_bad_library_or_plan_before_output(self):
        library, plan = self.presentation_inputs()
        valid_library, valid_plan = library.read_bytes(), plan.read_bytes()
        invalid_library = bytearray(valid_library)
        struct.pack_into("<I", invalid_library, 12, 2)
        cases = [(macho_fixture(cryptid=1), valid_plan),
                 (macho_fixture(cpu=7), valid_plan), (bytes(invalid_library), valid_plan),
                 (valid_library, b"[]"), (valid_library, b'{"schema":1,"schema":2}')]
        for native, raw_plan in cases:
            library.write_bytes(native)
            plan.write_bytes(raw_plan)
            with self.subTest(native=native[:4], plan=raw_plan), self.assertRaises(ValueError):
                package_ios_client(self.source, self.output, presentation_library=library,
                                   presentation_plan=plan, profile=self.profile)
            self.assertFalse(self.output.exists())
        library.write_bytes(valid_library)
        plan.write_bytes(valid_plan)
        for constant, limit in [("_MAX_PRESENTATION_LIBRARY_BYTES", len(valid_library) - 1),
                                ("_MAX_PRESENTATION_PLAN_BYTES", len(valid_plan) - 1),
                                ("_MAX_PRESENTATION_BUILD_BYTES", 1)]:
            with mock.patch("idoly_local.ios_patch." + constant, limit), self.assertRaises(ValueError):
                package_ios_client(self.source, self.output, presentation_library=library,
                                   presentation_plan=plan, profile=self.profile)
            self.assertFalse(self.output.exists())

    def test_presentation_requires_matching_ios_build_receipt(self):
        library, plan = self.presentation_inputs()
        build_path = library.with_suffix(".build.json")
        valid = json.loads(build_path.read_text())
        for change in [{"target": "aarch64-linux-android"}, {"schema": True},
                       {"profile_header_sha256": "b" * 64}, {"sha256": "0" * 64},
                       {"bytes": valid["bytes"] + 1}]:
            build_path.write_text(json.dumps({**valid, **change}))
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "build receipt"):
                package_ios_client(self.source, self.output, presentation_library=library,
                                   presentation_plan=plan, profile=self.profile)
            self.assertFalse(self.output.exists())
        build_path.write_text(json.dumps(valid))
        plan.write_text(json.dumps({"profile_header_sha256": "a" * 64, "library_sha256": "0" * 64}))
        with self.assertRaisesRegex(ValueError, "library SHA-256"):
            package_ios_client(self.source, self.output, presentation_library=library,
                               presentation_plan=plan, profile=self.profile)
        build_path.unlink()
        with self.assertRaises(OSError):
            package_ios_client(self.source, self.output, presentation_library=library,
                               presentation_plan=plan, profile=self.profile)

    def test_presentation_load_refuses_unsafe_padding_or_duplicate_commands(self):
        source = padded_macho_fixture()
        final, report = _add_presentation_load(source)
        self.assertEqual(len(final), len(source))
        self.assertEqual(final[512:], source[512:])
        self.assertFalse(report["code_moved"])
        dirty = bytearray(source)
        dirty[32 + struct.unpack_from("<I", source, 20)[0]] = 1
        for bad in [macho_fixture(), padded_macho_fixture(224), bytes(dirty), final]:
            with self.subTest(prefix=bad[:4]), self.assertRaises(ValueError):
                _add_presentation_load(bad)

    def test_rejected_presentation_patch_leaves_no_ipa_or_report(self):
        library, plan = self.presentation_inputs()
        presentation = types.ModuleType("idoly_local.ios_presentation")
        presentation.patch_presentation = mock.Mock(side_effect=ValueError("Plan/native mismatch"))
        with mock.patch("idoly_local.native_bootstrap.patch_native", return_value=(self.unity, {"platform": "ios"})), \
                mock.patch.dict(sys.modules, {presentation.__name__: presentation}), \
                self.assertRaisesRegex(ValueError, "Plan/native mismatch"):
            package_ios_client(self.source, self.output, presentation_library=library,
                               presentation_plan=plan, profile=self.profile)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix(".report.json").exists())

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
