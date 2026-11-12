#!/usr/bin/env python3
"""Compile actual server sources and run installer policy tests without Android.

Run: python android-server/tests/run_presentation_installer_host_tests.py
Tool paths default to the workspace's existing cached SDK, JDK and Chaquopy JAR.
Override them with --jdk-bin, --android-jar and --chaquopy-jar as needed.
This does not build an APK, run Gradle, install anything, or download dependencies.
"""

import argparse
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT.parent
PACKAGE = Path("game/qualiarts/idolypride/localserver")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jdk-bin", type=Path, default=WORKSPACE / ".setup/jdk-system/usr/lib/jvm/java-21-openjdk-amd64/bin")
    parser.add_argument("--android-jar", type=Path, default=WORKSPACE / ".setup/android-sdk/platforms/android-34/android.jar")
    parser.add_argument("--chaquopy-jar", type=Path, default=WORKSPACE / "shared/chaquopy_java-17.0.0.jar")
    args = parser.parse_args()
    sources = sorted((ROOT / "android-server/app/src/main/java" / PACKAGE).glob("*.java"))
    test = ROOT / "android-server/tests/java" / PACKAGE / "PresentationFailurePolicyHostTest.java"
    for path in (args.jdk_bin / "javac", args.jdk_bin / "java", args.android_jar, args.chaquopy_jar, test):
        if not path.is_file():
            parser.error(f"Required cached tool or source is missing: {path}")
    with tempfile.TemporaryDirectory(prefix="presentation-installer-host-") as directory:
        work = Path(directory)
        generated = work / "generated" / PACKAGE
        generated.mkdir(parents=True)
        resources = ET.parse(ROOT / "android-server/app/src/main/res/values/strings.xml").getroot()
        lines = ["package game.qualiarts.idolypride.localserver;", "public final class R {"]
        for kind, tag in (("string", "string"), ("array", "string-array")):
            lines.append(f" public static final class {kind} {{")
            for number, item in enumerate(resources, 1):
                if item.tag == tag:
                    lines.append(f"  public static final int {item.attrib['name']} = {number};")
            lines.append(" }")
        lines.append(" public static final class drawable { public static final int ic_server=1000; } }")
        resource_source = generated / "R.java"
        resource_source.write_text("\n".join(lines), encoding="utf-8")
        config_source = generated / "BuildConfig.java"
        config_source.write_text(
            'package game.qualiarts.idolypride.localserver; public final class BuildConfig {'
            'public static final String VERSION_NAME="host-test", SERVER_DATA_SHA256="host-test";'
            'public static final int VERSION_CODE=0;}', encoding="utf-8")
        classes = work / "classes"
        subprocess.run([
            str(args.jdk_bin / "javac"), "-J-Xmx128m", "-J-XX:MaxMetaspaceSize=128m",
            "-J-XX:ReservedCodeCacheSize=32m", "-J-XX:+UseSerialGC", "-J-XX:ActiveProcessorCount=1",
            "--release", "17", "-encoding", "UTF-8", "-classpath",
            str(args.android_jar) + ":" + str(args.chaquopy_jar), "-d", str(classes),
            str(resource_source), str(config_source), *(str(path) for path in sources), str(test),
        ], check=True)
        # Deliberately omit android.jar here: these tested policies use only Java.
        subprocess.run([
            str(args.jdk_bin / "java"), "-Xmx64m", "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=1",
            "-cp", str(classes), "game.qualiarts.idolypride.localserver.PresentationFailurePolicyHostTest",
        ], check=True)
        print(f"Compiled {len(sources)} actual server Java sources; no APK build or Android runtime.")


if __name__ == "__main__":
    main()
