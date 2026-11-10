# 아이프라 서버 Android 앱

서버와 공개 게임 데이터를 APK 안에 넣습니다. 설치 후 **서버 시작**을 누르고 **게임 열기**로 같은 기기의 로컬 클라이언트를 실행합니다. 서버는 `127.0.0.1:50051`, 마스터 파일은 `127.0.0.1:8080`에서 제공합니다. Termux가 필요하지 않습니다.

최초 실행은 포함된 `ServerData.zip`의 공개 데이터만 앱 전용 저장소에 설치합니다. 프로필과 진행 상태 DB는 앱 업데이트 후에도 유지됩니다. 앱 삭제나 Android 설정의 데이터 지우기는 해당 데이터를 제거합니다.

Java 17 이상, Android SDK 34, Python 3.13을 준비한 뒤 저장소 루트에서 빌드합니다.

아래는 개발 중인 v0.3.0 소스의 빌드 예시입니다. 현재 배포 링크와 설치 방법은 [저장소 README](../README.md#앱으로-실행하기)를 따릅니다. 새 서버 데이터에는 기존 35개 JSON 테이블과 첫 일반 라이브 계산용 네 개를 합쳐 39개 테이블이 필요합니다.

```sh
cd android-server
./gradlew :app:assembleDebug \
  -PbuildPython=/path/to/python3.13 \
  -PserverData=/path/to/IdolyPride-ServerData-v0.3.0.zip
```

기본 ABI는 `arm64-v8a`입니다. CI 에뮬레이터용 빌드는 `-PserverAbi=x86_64`를 추가합니다. 결과는 `app/build/outputs/apk/debug/app-debug.apk`입니다. v0.3.0의 Android 버전 코드는 19이며 같은 개발 서명을 사용하므로 설치된 서버 앱 위에 업데이트합니다. Chaquopy 17과 Python 3.13을 사용하며 protobuf·HTTP/2는 순수 Python, AES는 Android의 `javax.crypto`를 사용합니다.

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
  -PserverData=/path/to/IdolyPride-ServerData-v0.3.0.zip \
  -PliveEngineDir=/tmp/idoly-live/jni
```

`liveEngineDir` 바로 아래에 선택한 ABI의 `libidoly_live.so`가 있어야 합니다. x86_64 검사용은 `--target android-x86_64 --output /tmp/idoly-live/jni/x86_64`로 만든 뒤 Gradle에 `-PserverAbi=x86_64`를 추가합니다. Gradle은 해당 ABI 라이브러리와 원본 라이선스·고지만 APK에 넣습니다. `liveEngineDir`를 생략한 빌드는 일반 라이브 엔진을 포함하지 않으며, 이 상태에서 실험 기능을 켜면 서버 시작 시 명확한 오류로 중단합니다.

`local-server-development.keystore`는 이 프로젝트의 **공개 개발용 키**입니다. 별칭은 `idoly-local-server`, 저장소·키 비밀번호는 모두 `android`입니다. 실험용 서버 APK를 동일한 서명으로 업데이트하여 로컬 DB를 보존하려고 저장소에 포함했습니다. 운영용 비밀 키로 사용하지 않습니다. 향후 별도의 릴리스 서명이 필요하면 `IDOLY_SERVER_KEYSTORE`, `IDOLY_SERVER_STORE_PASSWORD`, `IDOLY_SERVER_KEY_ALIAS`, `IDOLY_SERVER_KEY_PASSWORD`를 설정할 수 있습니다.

표준 Gradle wrapper만 참고 저장소에서 재사용했으며 앱 구현은 독립적으로 작성했습니다. 실제 게임 플레이 지원 범위는 서버의 구현된 기능에 따라 달라집니다.
