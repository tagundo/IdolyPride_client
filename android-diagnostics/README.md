# 아이프라 진단 클라이언트

홈 화면 로딩 문제를 조사하기 위한 별도 Android ARM64 게임입니다. 패키지는 `game.qualiarts.idolypride.local.diagnostics`, 표시 이름은 **아이프라 진단**입니다. 기존 게임·로컬 게임의 데이터와 분리되며, 같은 기기에서 로컬 서버를 먼저 실행한 뒤 진단 게임을 엽니다.

게임 내부의 비공개 ContentProvider가 자기 PID의 `logcat`만 읽습니다. Unity 예외 종류와 인수를 제거한 정적 스택 메서드 이름, 정확히 확인된 셰이더 대기 문구만 전달합니다. 예외 메시지·로그 원문·파일 경로·URL·계정 값은 저장하거나 전송하지 않습니다. 다른 앱의 로그를 읽지 않으며 루트·ADB·`READ_LOGS` 권한을 요구하지 않습니다. Android AOSP는 자기 UID 로그 읽기를 허용하지만, 기기별 동작 확인은 필요합니다.

v0.2.0은 별도 ARM64 라이브러리에서 6.1.1의 검증된 명령어 위치 16개를 관측합니다. 원래 명령을 계속 실행하며 고정 단계 이름만 기록합니다. 관리 객체·인수·계정 데이터를 읽지 않습니다. 대상 코드의 build ID·16바이트와 실행 영역을 검증하고 일치하지 않으면 설치하지 않습니다. [네이티브 구현·범위](native/README.md)를 참고합니다. 원본 게임 파일은 유지하며 진단 라이브러리만 추가합니다.

같은 앱 UID의 실제 누적 수신·송신량도 5초 간격으로 기록합니다. 이는 SDK 등 앱 전체 통신을 포함하며 다운로드 완료율이 아닙니다. 상대 주소나 요청 내용은 수집하지 않습니다. 서버 v0.2.5 이상이 필요합니다.

진단 이벤트는 같은 기기의 고정 주소 `http://127.0.0.1:8080/diagnostics/client`로만 전송합니다. 프록시와 리다이렉트를 사용하지 않습니다. 메모리 대기열은 200개, 요청은 32개 이벤트·32KiB 이내이며, 요청 간격은 최소 2초이고 실패 시 최대 30초까지 늘어납니다. 수집은 게임 프로세스를 연 뒤 30분 동안만 진행합니다. 수집 실패는 게임 실행을 막지 않습니다. 무한 대기 과정에서 게임이 아무 로그도 쓰지 않으면 원인을 관측하지 못할 수 있습니다.

이 APK에는 원래 DEX를 바꾸지 않고 `classes5.dex`와 provider 선언을 추가합니다. API 주소와 기존 6개의 오프라인 부트스트랩 패치는 일반 로컬 클라이언트와 같습니다. 게임 실행 파일·프로토콜 데이터·계정 데이터는 이 소스 폴더에 포함하지 않습니다.

`local-diagnostics-development.keystore`는 **의도적으로 공개한 개발용 키**입니다. 비밀번호는 `android`, alias는 `idoly-diagnostics-public`입니다. 같은 진단 앱의 후속 설치에서 데이터를 유지하기 위해 사용합니다. 정식 인증이나 배포자 신뢰를 보증하는 키가 아닙니다.

개발용 빌드에는 JDK, Android SDK build-tools와 `android-34/android.jar`, APKEditor가 필요합니다.

```bash
.venv/bin/python tools/package_diagnostic_client.py original-6.1.1.xapk \
  --output data/clients/IdolyPride-Local-Diagnostic-Android-arm64.apk
.venv/bin/python -m pytest android-diagnostics/tests -q
```

입력은 원본 6.1.1 APK/XAPK이며 출력은 새 파일이어야 합니다. 빌드는 원본 DEX 4개·네이티브 코드·메타데이터 유지, 추가 DEX, 별도 패키지, 서명과 16KiB 정렬을 검사하고 옆에 `.evidence.json`을 만듭니다. 원본 입력이나 이미 설치한 앱을 수정하지 않습니다.
