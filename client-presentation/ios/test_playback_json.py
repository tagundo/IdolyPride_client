"""The independent playback schema never changes a snapshot on invalid input."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_playback_native_decoder_exact_schema_and_failure_retention(tmp_path):
    root = Path(__file__).resolve().parents[2]
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("A host C++17 compiler is unavailable")
    source = tmp_path / "playback.cpp"
    source.write_text('''#include <iostream>
#include <cstdint>
#include <string>
#include "client-presentation/native/playback_config.hpp"
#include "client-presentation/ios/playback_json.hpp"
int main() {
    std::string line;
    while (std::getline(std::cin,line)) {
        idoly::presentation::PlaybackConfigMessage value{41,false};
        bool valid=idoly::presentation::decode_playback_settings(line.c_str(),&value);
        if (!valid && (value.revision!=41 || value.wait_for_orientation)) return 2;
        std::cout << (valid ? "yes" : "no") << '\\n';
    }
}
''')
    executable = tmp_path / "playback"
    subprocess.run([compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(root),
                    str(source), "-o", str(executable)], check=True, timeout=30)
    good = [json.dumps({"schema": 1, "revision": 0, "wait_for_orientation": True}),
            '{"wait_for_orientation":false,"revision":9223372036854775807,"schema":1}']
    original = good[0]
    bad = [original.replace('"schema": 1', '"schema": true'), original.replace('"schema": 1', '"schema": 1.0'),
           original.replace('"schema": 1', '"schema": 2'), original.replace('"revision": 0', '"revision": -1'),
           original.replace('"revision": 0', '"revision": 0.0'), original.replace('"revision": 0', '"revision": 1e0'),
           original.replace('"revision": 0', '"revision": 9223372036854775808'), original.replace('true', '1'),
           original.replace('true', '"true"'), original.replace('true', 'null'), original + '{}',
           original.replace('"schema": 1', '"schema": 1,"schema":1'),
           original[:-1] + ',"custom_graphics":false}', original.replace('"wait_for_orientation"', '"unknown"'),
           '[]', 'null', '', ' ' * 8193, original + ' ' * 8192]
    bad += [original[:size] for size in range(1, len(original))]
    messages = good + bad
    result = subprocess.run([str(executable)], input="\n".join(messages) + "\n", capture_output=True,
                            text=True, check=True, timeout=5)
    assert result.stdout.splitlines() == ["yes"] * len(good) + ["no"] * len(bad)
