from pathlib import Path
import json
import resource
import shutil
import subprocess
import pytest

from idoly_local.media_settings import decode_settings
from idoly_local.language_settings import validate_settings as validate_language

ROOT=Path(__file__).resolve().parents[1]

def bounded():
    resource.setrlimit(resource.RLIMIT_AS,(128*1024*1024,)*2)

@pytest.fixture(scope="module")
def library_contract(tmp_path_factory):
    compiler=shutil.which("cc")
    if compiler is None: pytest.skip("A host C compiler is required")
    output=tmp_path_factory.mktemp("cross-library")/"contract"
    subprocess.run([compiler,"-std=c11","-O1","-Wall","-Wextra","-Werror","-Wno-unused-function",
        str(ROOT/"cross/tests/library_contract_test.c"),"-o",str(output)],check=True,timeout=20,preexec_fn=bounded)
    return output

def run(binary,*args):
    return subprocess.run([str(binary),*args],check=True,capture_output=True,text=True,timeout=3,preexec_fn=bounded).stdout

def test_public_library_files_strict_types_and_original_defaults(library_contract):
    assert "independent library preference/IPC checks" in run(library_contract)
    media,language=run(library_contract,"--json").splitlines()
    assert decode_settings(media.encode())=={"schema":1,"revision":102,"hide_video_mv":True,"mv_sort":"title","outfit_sort":"title"}
    assert validate_language(json.loads(language))=={"schema":1,"language":"ko"}

def test_resource_commands_are_exact_json_and_atomic_pipe_sized(library_contract):
    raw=run(library_contract,"--commands").splitlines()
    assert len(raw)==5
    commands=list(map(json.loads,raw))
    assert commands[0]=={"action":"resources_preview","platform":"ios"}
    assert commands[1]=={"action":"resources_download","platform":"ios"}
    for command,action in zip(commands[2:4],("resources_export","resources_import")):
        assert command=={"action":action,"platform":"ios","path":"/tmp/앨범\"\\\n.zip"}
    assert commands[4]=={"action":"resources_cancel","job_id":"0ab123"}
    assert all(len(line.encode())+1<=512 for line in raw)

def test_start_command_selects_primary_downloads_cache_without_changing_profile_path(library_contract):
    raw=run(library_contract,"--start-commands").splitlines()
    assert len(raw)==2
    shared,private=map(json.loads,raw)
    assert shared=={"action":"start","experimental_main_live":False,"media_mode":True,
        "download_missing_resources":True,"resource_cache_dir":"/Users/테스트\"\\\n/Downloads/IdolyPride"}
    assert private=={"action":"start","experimental_main_live":True,"media_mode":False,
        "download_missing_resources":False,"resource_cache_dir":None}
    assert all(len(line.encode())+1<=512 for line in raw)
    assert not any(key in shared for key in ("data_dir","profile","database","settings_dir"))

def test_actual_cocoa_source_compiles_without_apple_sdk():
    compiler=shutil.which("cc")
    if compiler is None: pytest.skip("A host C compiler is required")
    subprocess.run([compiler,"-std=c11","-Wall","-Wextra","-Werror","-Wno-unused-function","-fsyntax-only",
        str(ROOT/"cross/appkit_ui.c")],check=True,timeout=20,preexec_fn=bounded)
