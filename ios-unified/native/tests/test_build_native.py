"""Platform admission fixtures for the actual Mach-O build inspector."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "build_native.py"
spec = importlib.util.spec_from_file_location("ios_embedded_build", MODULE)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class MachOAdmission(unittest.TestCase):
    def fixture(self, platform=2, cpu=0x100000c, *, width=24):
        command = struct.pack('<6I', 0x32, width, platform, 0xd0000, 0x1a0000, 0)
        return struct.pack('<8I', 0xfeedfacf, cpu, 0, 6, 1, len(command), 0, 0) + command

    def inspect(self, raw, platform=2, arch='arm64'):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.dylib'; path.write_bytes(raw)
            return build.macho(path, platform, arch)

    def test_device_and_explicit_simulator_architectures(self):
        self.assertEqual(self.inspect(self.fixture())['platform'], 2)
        self.assertEqual(self.inspect(self.fixture(7), 7)['platform'], 7)
        self.assertEqual(self.inspect(self.fixture(7, 0x1000007), 7, 'x86_64')['platform'], 7)

    def test_macos_or_simulator_cannot_be_admitted_as_device(self):
        for platform in (1, 6, 7):
            with self.subTest(platform=platform), self.assertRaises(ValueError):
                self.inspect(self.fixture(platform))

    def test_wrong_cpu_or_corrupt_command_rejected(self):
        with self.assertRaises(ValueError): self.inspect(self.fixture(cpu=0x1000007))
        with self.assertRaises(ValueError): self.inspect(self.fixture(width=65536))
        with self.assertRaises(ValueError): self.inspect(self.fixture()[:31])


if __name__ == '__main__': unittest.main()
