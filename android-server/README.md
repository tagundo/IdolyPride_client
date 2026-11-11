# 아이프라 서버 Android 앱

서버와 공개 게임 데이터를 APK 안에 넣습니다. 설치 후 **서버 시작**을 누르고 **게임 열기**로 같은 기기의 로컬 클라이언트를 실행합니다. 서버는 `127.0.0.1:50051`, 마스터 파일은 `127.0.0.1:8080`에서 제공합니다. Termux가 필요하지 않습니다.

최초 실행은 포함된 `ServerData.zip`의 공개 데이터만 앱 전용 저장소에 설치합니다. 프로필과 진행 상태 DB는 앱 업데이트 후에도 유지됩니다. 앱 삭제나 Android 설정의 데이터 지우기는 해당 데이터를 제거합니다.

[GitHub에 배포된 Android 서버 APK는 v0.3.2](https://github.com/tagundo/IdolyPride_client/releases/download/local-server-v0.3.2/IdolyPride-Local-Server-Android.apk)입니다. 현재 v0.3.4 후보 소스에는 게임 리소스 경로와 포토 이름·프로필 레이아웃 저장을 추가했습니다. 후보는 아직 GitHub에 게시하지 않았습니다. Mac 배포 앱은 v0.3.2를 유지합니다.

후보의 **없는 게임 리소스 내려받기**는 기본값이 켜짐입니다. 서버를 중지한 상태에서 선택한 뒤 시작합니다. 게임이 요청한 파일만 공식 CDN에서 받아 크기·MD5 확인 후 이 앱의 전용 저장소에 보관합니다. 끄면 보관한 파일만 제공합니다. **게임 리소스**에는 이번 실행의 수신량·새로 보관한 파일 수와 게임으로 보낸 양을 따로 표시하며, 게임 전체 다운로드 완료율은 표시하지 않습니다. 상세 범위·검증 상태는 [게임 리소스 안내](../docs/resource-support.md)에 있습니다.

리소스 후보 연결판 `game.qualiarts.idolypride.local.resources`는 기존 공식·로컬 게임 앱과 나란히 설치합니다. 기존 앱은 유지합니다. 새 연결판은 기존 연결판과 패키지·서명이 다르고 전용 캐시도 별도입니다. 서버 앱은 기존 서명의 업데이트 경로를 유지하며, **아이프라 로컬 실행**은 새 연결판이 설치돼 있으면 이를 우선 엽니다. 없으면 기존 연결판을 엽니다.

실제 게임에서 내장 서버의 `Auth.Login → Master.Get → User.Get` 교환 뒤 원본 SDK의 리소스 시간 초과 `E209`를 확인했습니다. 새 목록 경로의 로컬 HTTP 검사는 통과했으며, 실제 SDK 적용 후의 오류 해결·다운로드 UI·홈·일반 라이브는 검증 중입니다. 앞선 v0.3.3 후보에서 검사한 DB 보존 업데이트·서버 시작·암호화 RPC 결과와 구분합니다. GitHub 파일 업로드의 `401 Bad credentials` 오류로 후보는 미게시 상태입니다.

이미지 트레이닝·VENUS 읽기 모듈도 소스에 포함됩니다. 실제 읽기에는 보존한 개인 자료와 추가 마스터를 준비한 소스 환경이 필요하며, 후보의 기존 40개 디코딩 JSON 마스터만으로 이벤트 메뉴를 복원하지는 않습니다. 개인 자료 가져오기 UI·포토 촬영·지역 생성·이벤트 라이브·VENUS 대전·보상 정산은 아직 지원하지 않습니다.

Java 17 이상, Android SDK 34, Python 3.13을 준비한 뒤 저장소 루트에서 빌드합니다.

아래는 미게시 v0.3.4 후보 소스의 빌드 예시입니다. 현재 배포 링크는 [저장소 README](../README.md#앱으로-실행하기)의 v0.3.2 파일입니다. 스키마·원본 마스터 202개·서버용 JSON 40개를 준비한 뒤, 공개 Octo 설정과 목록 두 파일을 명시적으로 넣어 데이터 묶음을 만듭니다. `public-octo`에는 원본 클라이언트의 공개 SDK 설정만 넣으며 계정·Firebase 인증 자료는 넣지 않습니다.

```sh
uv run python tools/build_server_payload.py \
  --data-dir data \
  --output /tmp/IdolyPride-ServerData-v0.3.4.zip \
  --octo-data /path/to/public-octo

cd android-server
./gradlew :app:assembleDebug \
  -PbuildPython=/path/to/python3.13 \
  -PserverData=/tmp/IdolyPride-ServerData-v0.3.4.zip
```

현재 후보 데이터 묶음은 84,041,457바이트이며 원본 마스터 202개와 기존 JSON 40개를 유지합니다. 추가한 리소스 목록의 54,442개 참조는 메타데이터이며 전체 약 39.3GB의 리소스 파일은 동봉하지 않습니다. 목록은 일본 Android 6.1.1용이며 iOS·한국판 목록은 포함하지 않습니다.

기본 ABI는 `arm64-v8a`입니다. CI 에뮬레이터용 빌드는 `-PserverAbi=x86_64`를 추가합니다. 결과는 `app/build/outputs/apk/debug/app-debug.apk`입니다. v0.3.4 후보의 Android 버전 코드는 23이며 기존 서버 개발 서명을 재사용합니다. Chaquopy 17과 Python 3.13을 사용하며 protobuf·HTTP/2는 순수 Python, AES와 HTTPS는 Android의 플랫폼 구현을 사용합니다.

## 첫 메인 라이브 실험 기능

앱의 **첫 메인 라이브 실험 기능 사용**은 기본값이 꺼져 있습니다. 서버를 중지한 상태에서 선택한 뒤 시작하면 첫 퀘스트 `qt-main-1-001-01`만 현재 소유 카드 다섯 장으로 계산합니다. 설정은 다음 실행에도 유지됩니다. 점수는 `live-v5` 로컬 규칙을 사용하며 공식 서버와 다를 수 있습니다. 첫 성공 때만 보상·경험치를 지급하고, 같은 요청을 재시도하면 저장된 결과를 돌려줍니다. 자세한 제한은 [첫 일반 라이브 안내](../docs/first-live-support.md)에 있습니다.

이 기능을 포함한 APK는 [네이티브 엔진](../native-live-engine/README.md)을 먼저 빌드합니다. Go 1.27.3과 NDK 26.3.11579264가 있는 Linux x86_64 호스트에서, 저장소 루트 기준으로 실행합니다.

```sh
python3 native-live-engine/scripts/build.py --target android \
  --go /path/to/go1.27.3/bin/go \
  --ndk /path/to/android-ndk/26.3.11579264 \
  --output /tmp/idoly-live/jni/arm64-v8a --cache /tmp/idoly-live/cache

cd android-server
./gradlew :app:assembleDebug \
  -PbuildPython=/path/to/python3.13 \
  -PserverData=/tmp/IdolyPride-ServerData-v0.3.4.zip \
  -PliveEngineDir=/tmp/idoly-live/jni
```

`liveEngineDir` 바로 아래에 선택한 ABI의 `libidoly_live.so`가 있어야 합니다. x86_64 검사용은 `--target android-x86_64 --output /tmp/idoly-live/jni/x86_64`로 만든 뒤 Gradle에 `-PserverAbi=x86_64`를 추가합니다. Gradle은 해당 ABI 라이브러리와 원본 라이선스·고지만 APK에 넣습니다. `liveEngineDir`를 생략한 빌드는 일반 라이브 엔진을 포함하지 않으며, 이 상태에서 실험 기능을 켜면 서버 시작 시 명확한 오류로 중단합니다.

`local-server-development.keystore`는 이 프로젝트의 **공개 개발용 키**입니다. 별칭은 `idoly-local-server`, 저장소·키 비밀번호는 모두 `android`입니다. 실험용 서버 APK를 동일한 서명으로 업데이트하여 로컬 DB를 보존하려고 저장소에 포함했습니다. 운영용 비밀 키로 사용하지 않습니다. 향후 별도의 릴리스 서명이 필요하면 `IDOLY_SERVER_KEYSTORE`, `IDOLY_SERVER_STORE_PASSWORD`, `IDOLY_SERVER_KEY_ALIAS`, `IDOLY_SERVER_KEY_PASSWORD`를 설정할 수 있습니다.

표준 Gradle wrapper만 참고 저장소에서 재사용했으며 앱 구현은 독립적으로 작성했습니다. 실제 게임 플레이 지원 범위는 서버의 구현된 기능에 따라 달라집니다.
