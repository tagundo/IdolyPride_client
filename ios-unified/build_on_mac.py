#!/usr/bin/env python3
"""Local Xcode build fallback; owns only a fresh Downloads/IdolyPride/builds folder."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def capture(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL).strip()


def main():
    if sys.platform != "darwin" or sys.version_info[:2] != (3, 13):
        raise ValueError("Mac과 Python 3.13이 필요합니다. brew install python@3.13 으로 준비할 수 있습니다.")
    for tool in ("xcrun", "xcodebuild", "git", "gh"):
        if not shutil.which(tool):
            raise ValueError(tool + "가 필요합니다. 전체 Xcode와 GitHub CLI를 설치해 주세요.")
    capture("xcrun", "--sdk", "iphoneos", "--show-sdk-path")
    capture("xcrun", "--sdk", "iphonesimulator", "--show-sdk-path")
    translated = subprocess.run(["sysctl", "-n", "sysctl.proc_translated"], capture_output=True, text=True)
    if translated.returncode == 0 and translated.stdout.strip() == "1":
        raise ValueError("Rosetta 대신 Mac의 기본 아키텍처로 Python 3.13을 실행해 주세요.")
    for port in (50051, 8080):
        with socket.socket() as peer:
            peer.settimeout(0.2)
            if peer.connect_ex(("127.0.0.1", port)) == 0:
                raise ValueError("시뮬레이터 검증에 필요한 포트 " + str(port) + "가 사용 중입니다. 별도 아이프라 서버를 종료해 주세요.")
    runtimes = json.loads(capture("xcrun", "simctl", "list", "runtimes", "--json")).get("runtimes", [])
    if not any(r.get("isAvailable") is True and ".iOS-" in r.get("identifier", "") for r in runtimes):
        raise ValueError("Xcode의 iOS Simulator 런타임이 필요합니다. Xcode Settings > Components에서 설치해 주세요.")
    source = capture("git", "-C", str(HERE.parent), "rev-parse", "HEAD")
    if capture("git", "-C", str(HERE.parent), "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("소스에 수정사항이 있습니다. 깨끗한 체크아웃에서 빌드해 주세요.")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or capture("gh", "auth", "token")
    if not token:
        raise ValueError("비공개 입력 파일을 받으려면 gh auth login으로 GitHub에 로그인해 주세요.")
    base = Path.home() / "Downloads/IdolyPride/builds"
    base.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(base).free < 8 * 1024**3:
        raise ValueError("통합 IPA와 독립 시뮬레이터 검증을 위해 빌드 폴더에 8 GiB 이상이 필요합니다.")
    root = base / (datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + source[:12])
    root.mkdir()
    print("빌드 폴더: " + str(root), flush=True)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION": "python",
           "PYTHONPATH": str(HERE.parent / "src")}
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "GH_DEBUG", "GIT_CURL_VERBOSE"):
        env.pop(key, None)
    subprocess.run([sys.executable, "-m", "venv", str(root / "venv")], check=True, env=env)
    python = root / "venv/bin/python"
    subprocess.run([str(python), "-B", str(HERE / "fetch_inputs.py"), "--output", str(root / "inputs")],
                   check=True, env={**env, "GH_TOKEN": token})
    token = None
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir",
                    "pytest==8.4.2", "pycryptodome==3.23.0"], check=True, env=env)
    subprocess.run([str(python), "-m", "pip", "install", "--no-index", *map(str, sorted((root / "inputs/wheels").glob("*.whl")))],
                   check=True, env=env)
    tests = [HERE.parent / "tests/test_ios_host.py", HERE.parent / "tests/test_public_payload.py",
             *sorted((HERE.parent / "tests").glob("test_ios_unified_*.py")), HERE / "native/tests/test_build_native.py"]
    subprocess.run([str(python), "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(root / "test-tmp"), *map(str, tests)],
                   check=True, env=env, cwd=HERE.parent)
    subprocess.run([str(python), "-B", str(HERE / "ci_build.py"), "--inputs", str(root / "inputs"),
                    "--work", str(root / "work"), "--output", str(root / "output"), "--source-commit", source],
                   check=True, env=env, cwd=HERE.parent)
    print("통합 IPA 및 검사 결과: " + str(root / "output"), flush=True)
    subprocess.run(["open", str(root / "output")], check=False)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as error:
        print(str(error) if isinstance(error, ValueError) else "빌드 단계 실패: 위의 도구 오류를 확인해 주세요.", file=sys.stderr)
        raise SystemExit(1) from None
