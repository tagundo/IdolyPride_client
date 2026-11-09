# 아이프라 로컬 서버 for macOS

Apple Silicon과 macOS 13 이상용 서버 앱입니다. SwiftUI 창에서 **서버 시작**, **중지**, **아이프라 열기**를 사용할 수 있습니다. 사용자에게 Python·Homebrew·터미널 설치가 필요하지 않습니다.

서버는 이 Mac의 `127.0.0.1:50051`, 리소스는 `127.0.0.1:8080`에서 실행됩니다. 연결용 IPA를 PlayCover에 설치한 뒤 서버를 시작하고 게임을 열어 주세요. 앱을 종료하면 자신이 실행한 서버 엔진도 종료합니다.

첫 실행 시 앱에 포함된 공개 서버 데이터를 `~/Library/Application Support/IdolyPrideLocal`에 준비합니다. 기존 데이터베이스·프로필·파일을 덮어쓰지 않으므로 앱 업데이트와 이동 후에도 보존됩니다. 계정 수집·온라인 인증은 자동 실행하지 않습니다. 현재 게임 기능 지원 범위는 저장소 README를 따릅니다.

배포 빌드는 ad-hoc 서명이므로 Apple 공증은 포함되지 않습니다. 다운로드한 앱은 macOS의 개인정보 보호 및 보안에서 실행 허용이 필요할 수 있습니다.

## 빌드

GitHub 표준 `macos-15` 러너는 ARM64입니다. 빌드 시작 시 `uname -m`과 Python의 architecture가 `arm64`인지 확인합니다. Intel 또는 Linux에서는 앱 빌드를 거부합니다.

아래 명령은 개발/CI용입니다. 최종 사용자는 `.app.zip`을 풀어 앱만 실행합니다.

```bash
uv sync --locked --python 3.12
uv pip install --python .venv/bin/python -r macos-server/requirements-build.txt
.venv/bin/python -m pytest macos-server/tests -q
.venv/bin/python macos-server/build_app.py \
  --server-data data/clients/IdolyPride-ServerData-v0.2.7.zip \
  --output data/macos-built/IdolyPrideLocalServer.app \
  --archive data/clients/IdolyPride-Local-Server-macOS-arm64.app.zip \
  --evidence data/macos-evidence
```

PyInstaller가 서버용 Python과 패키지를 앱 내부에 넣고, Swift 컴파일러가 네이티브 창을 만듭니다. 빌드에는 이미 준비된 `ServerData.zip`만 사용하며 게임 계정이나 로컬 DB를 넣지 않습니다.

기본 빌드는 포함된 엔진으로 암호화 `System.Check`, 로그인 전의 비활성 `Refund.GetTerm` 기간, 약관·도움말과 리소스 Range 요청을 검사합니다. 로컬 로그인·홈 진입 응답의 등급 ID가 번들 `HierarchyDetailGrade`와 상위 `HierarchyGrade`에 연결되는지, 설정과 프로필이 서버 재시작 후에도 보존되는지도 확인합니다. 이어 공백·한글 경로로 옮긴 실제 앱을 열어 서버 시작/중지와 종료를 확인합니다. 이는 게임 클라이언트의 홈 화면 진입 검증을 뜻하지 않습니다. `--skip-smoke`는 개발용이며 배포 워크플로에서는 사용하지 않습니다.
