"""Optional startup media channel, no Android/JNI execution."""
from pathlib import Path
import os
import subprocess
import importlib.util

HERE=Path(__file__).resolve().parents[1]
JDK=Path("/workspace/.setup/jdk-system/usr/lib/jvm/java-21-openjdk-amd64/bin")
SPEC=importlib.util.spec_from_file_location("media_addon_protocol",HERE/"build_addon.py")
ADDON=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(ADDON)

def test_java_media_schema_polling_and_last_valid_native_retention(tmp_path):
    sources=[HERE/"java/game/qualiarts/idolypride/presentation/PresentationClient.java",HERE/"tests/MediaHarness.java"]
    env=dict(os.environ,MALLOC_ARENA_MAX="2")
    subprocess.run([str(JDK/"javac"),*["-J"+f for f in ADDON.JAVA_FLAGS],*ADDON.JAVAC_ARGUMENTS,
        "-d",str(tmp_path),*map(str,sources)],check=True,capture_output=True,timeout=30,env=env)
    result=subprocess.run([str(JDK/"java"),*ADDON.JAVA_FLAGS,"-cp",str(tmp_path),
        "game.qualiarts.idolypride.presentation.MediaHarness"],check=True,capture_output=True,text=True,timeout=30,env=env)
    assert result.stdout.startswith("PASS ") and int(result.stdout.split()[1])>=140
