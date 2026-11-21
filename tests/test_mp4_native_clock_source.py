"""Run the production startup-only libunity source fingerprint reader."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import warnings
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED

import pytest

ROOT = Path(__file__).resolve().parents[1]
MEMBER = 'lib/arm64-v8a/libunity.so'


@pytest.fixture(scope='module')
def source_reader(tmp_path_factory):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('A host C++ compiler is required')
    source = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    source = source.split('// BEGIN_MP4_NATIVE_CLOCK_SOURCE_HASH\n', 1)[1].split('// END_MP4_NATIVE_CLOCK_SOURCE_HASH', 1)[0]
    folder = tmp_path_factory.mktemp('native-clock-source-reader')
    cpp, binary = folder / 'reader.cpp', folder / 'reader'
    cpp.write_text('''#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <climits>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
struct Profile {const char* native_sha256;};Profile mp4_native_profile{};
''' + source + '''
int main(int argc,char** argv){
    if(argc!=4)return 2;
    mp4_native_profile.native_sha256=argv[3];
    bool matches=false;
    if(!std::strcmp(argv[1],"source"))matches=mp4_native_source_matches(argv[2]);
    else if(!std::strcmp(argv[1],"hash")){
        Mp4SourceSha256 hash;
        for(size_t i=0;argv[2][i];++i)hash.append(reinterpret_cast<const uint8_t*>(argv[2]+i),1);
        matches=hash.matches(argv[3]);
    }else return 3;
    std::printf("%d\\n",matches);
}
''')
    result = subprocess.run([compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(binary)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return binary


def invoke(reader, mode, value, digest):
    result = subprocess.run([str(reader), mode, str(value), digest], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return result.stdout == '1\n'


@pytest.mark.parametrize('text', ['', 'abc', 'a' * 55, 'a' * 56, 'a' * 63, 'a' * 64, 'a' * 65, 'x' * 10000])
def test_production_sha256_padding_and_chunk_boundaries(source_reader, text):
    expected = hashlib.sha256(text.encode()).hexdigest()
    assert invoke(source_reader, 'hash', text, expected)
    assert not invoke(source_reader, 'hash', text, '0' * 64)


@pytest.fixture(scope='module')
def source_inputs(tmp_path_factory):
    folder = tmp_path_factory.mktemp('native-clock-source-fixtures')
    library = folder / 'libunity.so'
    with library.open('wb') as output:
        output.write(b'\x7fELF\x02\x01' + b'\0' * (21427000 - 7) + b'!')
    digest = hashlib.sha256(library.read_bytes()).hexdigest()
    return folder, library, digest


def test_direct_source_requires_exact_length_and_whole_fingerprint(source_reader, source_inputs):
    folder, library, digest = source_inputs
    assert invoke(source_reader, 'source', library, digest)
    assert not invoke(source_reader, 'source', library, '0' * 64)
    small = folder / 'small.so'
    small.write_bytes(b'\x7fELF\x02\x01')
    assert not invoke(source_reader, 'source', small, hashlib.sha256(small.read_bytes()).hexdigest())
    linked = folder / 'linked.so'
    linked.symlink_to(library)
    assert not invoke(source_reader, 'source', linked, digest)


@pytest.mark.parametrize('variant', ['stored', 'compressed', 'duplicate', 'wrong_member', 'local_name_changed'])
def test_apk_source_member_is_bounded_exact_stored_unique_and_local_name_agrees(source_reader, source_inputs, variant):
    folder, library, digest = source_inputs
    archive = folder / (variant + '.apk')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with ZipFile(archive, 'w', compression=ZIP_DEFLATED if variant == 'compressed' else ZIP_STORED) as output:
            output.write(library, MEMBER if variant != 'wrong_member' else 'lib/other/libunity.so')
            output.comment = b'bounded APK comment'
            if variant == 'duplicate':
                output.write(library, MEMBER)
    if variant == 'local_name_changed':
        with archive.open('r+b') as stream:
            stream.seek(30)
            stream.write(b'x')
    assert invoke(source_reader, 'source', str(archive) + '!/' + MEMBER, digest) is (variant == 'stored')
    assert not invoke(source_reader, 'source', str(archive) + '!/lib/other/libunity.so', digest)


def test_actual_original_libunity_whole_hash_when_public_analysis_input_available(source_reader):
    original = Path('/workspace/shared/idoly-sdk-cache-analysis/mp4-android-analysis/libunity.so')
    if not original.is_file():
        pytest.skip('Pinned original analysis input is not present')
    expected = 'c36ea39e5040fbcd0577f7c49d08e149e2e7dc62449d90aadce761118a816c85'
    assert original.stat().st_size == 21427000
    assert hashlib.sha256(original.read_bytes()).hexdigest() == expected
    assert invoke(source_reader, 'source', original, expected)
