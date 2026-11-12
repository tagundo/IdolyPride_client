"""Exercise the native parser against server-generated valid/invalid messages."""
from pathlib import Path
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from idoly_local.presentation import DEFAULTS, validate_settings


def test_native_decoder_bounds_and_exact_schema(tmp_path):
    source=tmp_path/'settings.cpp'
    source.write_text('''#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <iostream>
#include <string>
#include "client-presentation/native/presentation_math.hpp"
#include "client-presentation/ios/settings_json.hpp"
int main() {
  std::string line;
  while (std::getline(std::cin,line)) {
    idoly::presentation::Config value;
    bool ok=idoly::presentation::decode_settings(line.c_str(),&value);
    std::cout << (ok ? "yes" : "no") << '\\n';
  }
}
''')
    executable=tmp_path/'settings'
    subprocess.run(['g++','-std=c++17','-O1','-Wall','-Wextra','-Werror',
        '-Wno-misleading-indentation','-I',str(ROOT),str(source),'-o',str(executable)],check=True)
    valid=[dict(DEFAULTS),{**DEFAULTS,'revision':2**63-1,'custom_graphics':True,
        'quality':100,'target_fps':120,'render_scale':.25,'max_buffer_pixel':256,
        'anti_aliasing':2,'shadow_resolution':4096,'expand_photography':True}]
    for value in valid: validate_settings(value)
    messages=[json.dumps(value,separators=(',',':')) for value in valid]
    messages.append(json.dumps(dict(reversed(list(valid[1].items())))))
    expected=['yes']*len(messages)
    original=messages[0]
    invalid=[original.replace('"schema":1','"schema":1,"schema":1'),
        original.replace('"revision":0','"revision":9223372036854775808'),
        original.replace('"revision":0','"revision":1.0'),
        original.replace('"custom_graphics":false','"custom_graphics":0'),
        original.replace('"quality":0','"quality":true'),
        original.replace('"render_scale":1.0','"render_scale":NaN'),
        original.replace('"render_scale":1.0','"render_scale":1e999'),
        original.replace('"quality":0','"quality":00'),
        original.replace('"max_buffer_pixel":4096','"max_buffer_pixel":257'),
        original.replace('"target_fps":0','"target_fps":-2147483648'),
        original.replace('"schema":1','"unknown":1'),original+'{}','[]','null','']
    invalid.extend(original[:i] for i in range(1,len(original)))
    messages.extend(invalid); expected.extend(['no']*len(invalid))
    result=subprocess.run([str(executable)],input='\n'.join(messages)+'\n',text=True,capture_output=True,check=True)
    assert result.stdout.splitlines()==expected
