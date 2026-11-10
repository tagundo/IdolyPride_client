"""Target selection must not turn a cross-build into an Apple runtime claim."""
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("live_engine_build", Path(__file__).resolve().parents[1] / "scripts/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class BuildTargetTests(unittest.TestCase):
    def test_android_targets_use_pinned_ndk_api26_and_distinct_architectures(self):
        with tempfile.TemporaryDirectory() as temporary:
            ndk = Path(temporary)
            (ndk / "source.properties").write_text("Pkg.Revision = 26.3.11579264\n")
            for target, arch, triple in (("android", "arm64", "aarch64"),
                                         ("android-x86_64", "amd64", "x86_64")):
                with self.subTest(target=target):
                    environment, filename = build.target_settings(target, ndk)
                    self.assertEqual(filename, "libidoly_live.so")
                    self.assertEqual(environment["GOOS"], "android")
                    self.assertEqual(environment["GOARCH"], arch)
                    prefix = ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin"
                    self.assertEqual(environment["CC"], str(prefix / (triple + "-linux-android26-clang")))
                    self.assertEqual(environment["CXX"], str(prefix / (triple + "-linux-android26-clang++")))
            (ndk / "source.properties").write_text("Pkg.Revision = 27.0.0\n")
            with self.assertRaisesRegex(ValueError, "pinned"):
                build.target_settings("android-x86_64", ndk)
        with self.assertRaisesRegex(ValueError, "--ndk"):
            build.target_settings("android-x86_64")

    def test_android_output_must_match_architecture_and_all_16k_load_segments(self):
        def elf(machine, alignment=16384):
            raw = bytearray(120)
            raw[:6] = b"\x7fELF\x02\x01"
            struct.pack_into("<HH", raw, 16, 3, machine)
            struct.pack_into("<Q", raw, 32, 64)
            struct.pack_into("<HH", raw, 54, 56, 1)
            struct.pack_into("<IIQQQQQQ", raw, 64, 1, 5, 0, 0, 0, 120, 120, alignment)
            return bytes(raw)
        for target, machine in (("android", 183), ("android-x86_64", 62)):
            with self.subTest(target=target):
                self.assertEqual(build.check_android_library(elf(machine), target), [16384])
                with self.assertRaisesRegex(ValueError, "selected"):
                    build.check_android_library(elf(62 if machine == 183 else 183), target)
                with self.assertRaisesRegex(ValueError, "16-KiB"):
                    build.check_android_library(elf(machine, 4096), target)
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    build.check_android_library(elf(machine)[:80], target)

    def test_macos_requires_native_apple_silicon_host(self):
        for system, machine in (("Linux", "arm64"), ("Linux", "x86_64"), ("Darwin", "x86_64")):
            with self.subTest(system=system, machine=machine), self.assertRaisesRegex(ValueError, "Apple Silicon"):
                build.target_settings("macos", system=system, machine=machine)

    def test_macos_compiler_and_minimum_os_are_explicit(self):
        environment, filename = build.target_settings("macos", system="Darwin", machine="arm64")
        self.assertEqual(filename, "libidoly_live.dylib")
        self.assertEqual(environment, {"GOOS": "darwin", "GOARCH": "arm64", "CC": "clang", "CXX": "clang++",
                                       "MACOSX_DEPLOYMENT_TARGET": "13.0"})
        self.assertEqual(build.target_settings("linux")[1], "libidoly_live.so")

    def test_macos_report_requires_an_arm64_dynamic_library(self):
        header = struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 6, 0, 0, 0, 0)
        build.check_macos_library(header)
        for wrong in (b"\x7fELF" + bytes(28), header[:20],
                      struct.pack("<8I", 0xFEEDFACF, 0x01000007, 0, 6, 0, 0, 0, 0),
                      struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 2, 0, 0, 0, 0)):
            with self.assertRaisesRegex(ValueError, "Mach-O"):
                build.check_macos_library(wrong)


class RuntimeOverlayTests(unittest.TestCase):
    def test_patch_is_exactly_one_android_midr_guard_and_keeps_go_license(self):
        manifest, original, modified = build.verify_runtime_patch()
        self.assertEqual(original.count(build.MIDR_ANCHOR), 1)
        self.assertEqual(modified, original.replace(build.MIDR_ANCHOR, build.MIDR_REPLACEMENT))
        self.assertIn(b'ARM64.HasCPUID = isSet(HWCap, hwcap_CPUID)', modified)
        self.assertEqual(list(build.RUNTIME_PATCH.rglob('*.go')), [])
        self.assertEqual(manifest['original_sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(manifest['license_sha256'], hashlib.sha256(
            (build.ROOT / 'third-party-licenses/Go-LICENSE').read_bytes()).hexdigest())

    def test_all_other_targets_never_inspect_an_installed_go_sdk(self):
        for target in ('linux', 'macos', 'android-x86_64'):
            with self.subTest(target=target), patch.object(build, 'run', side_effect=AssertionError('SDK read')):
                self.assertEqual(build.runtime_overlay(target, 'go', 'arbitrary version', {}, '/unused'),
                                 ([], {'applied': False}))

    def make_sdk(self, directory):
        _, original, _ = build.verify_runtime_patch()
        sdk = directory / 'sdk'
        source = sdk / 'src/internal/cpu/cpu_arm64_hwcap.go'
        source.parent.mkdir(parents=True)
        source.write_bytes(original)
        (sdk / 'LICENSE').write_bytes((build.ROOT / 'third-party-licenses/Go-LICENSE').read_bytes())
        return sdk, source, original

    def test_exact_sdk_is_read_only_and_overlay_is_outside_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            sdk, source, original = self.make_sdk(directory)
            with patch.object(build, 'run', return_value=str(sdk)) as run:
                flags, report = build.runtime_overlay('android', 'real-go', 'go version go1.27.3 linux/amd64',
                                                       {'GOOS': 'android'}, directory / 'cache')
            run.assert_called_once_with(['real-go', 'env', 'GOROOT'], {'GOOS': 'android'})
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(flags[0], '-overlay')
            replace = json.loads(Path(flags[1]).read_text())['Replace']
            self.assertEqual(list(replace), [str(source)])
            staged = Path(replace[str(source)])
            self.assertFalse(staged.is_relative_to(sdk))
            self.assertNotEqual(staged.suffix, '.go')
            self.assertEqual(hashlib.sha256(staged.read_bytes()).hexdigest(), report['patched_sha256'])
            self.assertFalse(report['hwcap_assignments_changed'])
            build.check_runtime_overlay(flags, report)
            self.assertTrue(report['sdk_and_overlay_source_reverified_after_build'])
            staged.write_bytes(b'changed after Go compile')
            with self.assertRaisesRegex(ValueError, 'changed during'):
                build.check_runtime_overlay(flags, report)

    def test_unexpected_version_sdk_hash_license_or_sdk_output_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            sdk, source, original = self.make_sdk(directory)
            with patch.object(build, 'run', return_value=str(sdk)):
                for version in ('go version go1.27.2 linux/amd64', 'go version go1.28 linux/amd64', 'go1.27.3'):
                    with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'exact Go 1.27.3'):
                        build.runtime_overlay('android', 'go', version, {}, directory / 'cache')
                source.write_bytes(original + b'\n')
                with self.assertRaisesRegex(ValueError, 'original SHA-256'):
                    build.runtime_overlay('android', 'go', 'go version go1.27.3 linux/amd64', {}, directory / 'cache')
                source.write_bytes(original)
                (sdk / 'LICENSE').write_bytes(b'changed license')
                with self.assertRaisesRegex(ValueError, 'license differs'):
                    build.runtime_overlay('android', 'go', 'go version go1.27.3 linux/amd64', {}, directory / 'cache')
                (sdk / 'LICENSE').write_bytes((build.ROOT / 'third-party-licenses/Go-LICENSE').read_bytes())
                with self.assertRaisesRegex(ValueError, 'outside the installed SDK'):
                    build.runtime_overlay('android', 'go', 'go version go1.27.3 linux/amd64', {}, sdk / 'cache')

    def test_missing_or_duplicate_anchor_and_unrelated_patch_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / 'patch'
            shutil.copytree(build.RUNTIME_PATCH, copied)
            original = (copied / 'original/cpu_arm64_hwcap.go.txt').read_bytes()
            for bad in (original.replace(build.MIDR_ANCHOR, b'\tif false {\n'), original + build.MIDR_ANCHOR):
                (copied / 'original/cpu_arm64_hwcap.go.txt').write_bytes(bad)
                with patch.object(build, 'RUNTIME_PATCH', copied), self.assertRaisesRegex(ValueError, 'exactly one'):
                    build.verify_runtime_patch()
            (copied / 'original/cpu_arm64_hwcap.go.txt').write_bytes(original)
            patched = copied / 'patched/cpu_arm64_hwcap.go.txt'
            patched.write_bytes(patched.read_bytes() + b'// unrelated change\n')
            with patch.object(build, 'RUNTIME_PATCH', copied), self.assertRaisesRegex(ValueError, 'only the MIDR guard'):
                build.verify_runtime_patch()


if __name__ == "__main__":
    unittest.main()
