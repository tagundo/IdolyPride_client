"""Target selection must not turn a cross-build into an Apple runtime claim."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("live_engine_build", Path(__file__).resolve().parents[1] / "scripts/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class BuildTargetTests(unittest.TestCase):
    def test_android_targets_use_pinned_ndk_api26_and_distinct_architectures(self):
        with tempfile.TemporaryDirectory() as temporary:
            # macOS exposes temporary directories through the /var symlink.
            ndk = Path(temporary).resolve()
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


if __name__ == "__main__":
    unittest.main()
