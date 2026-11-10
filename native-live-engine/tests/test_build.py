"""Target selection must not turn a cross-build into an Apple runtime claim."""
import importlib.util
from pathlib import Path
import struct
import unittest


SPEC = importlib.util.spec_from_file_location("live_engine_build", Path(__file__).resolve().parents[1] / "scripts/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class BuildTargetTests(unittest.TestCase):
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
