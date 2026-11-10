# 아이프라 서버 Android 앱

서버와 공개 게임 데이터를 APK 안에 넣습니다. 설치 후 **서버 시작**을 누르고 **게임 열기**로 같은 기기의 로컬 클라이언트를 실행합니다. 서버는 `127.0.0.1:50051`, 마스터 파일은 `127.0.0.1:8080`에서 제공합니다. Termux가 필요하지 않습니다.

최초 실행은 포함된 `ServerData.zip`의 공개 데이터만 앱 전용 저장소에 설치합니다. 프로필과 진행 상태 DB는 앱 업데이트 후에도 유지됩니다. 앱 삭제나 Android 설정의 데이터 지우기는 해당 데이터를 제거합니다.

Java 17 이상, Android SDK 34, Python 3.13을 준비한 뒤 저장소 루트에서 빌드합니다.

```sh
cd android-server
./gradlew :app:assembleDebug \
  -PbuildPython=/path/to/python3.13 \
  -PserverData=/path/to/IdolyPride-ServerData-v0.2.11.zip
```

기본 ABI는 `arm64-v8a`입니다. CI 에뮬레이터용 빌드는 `-PserverAbi=x86_64`를 추가합니다. 결과는 `app/build/outputs/apk/debug/app-debug.apk`입니다. v0.2.11의 Android 버전 코드는 13이며 같은 개발 서명을 사용하므로 설치된 서버 앱 위에 업데이트합니다. Chaquopy 17과 Python 3.13을 사용하며 protobuf·HTTP/2는 순수 Python, AES는 Android의 `javax.crypto`를 사용합니다.

`local-server-development.keystore`는 이 프로젝트의 **공개 개발용 키**입니다. 별칭은 `idoly-local-server`, 저장소·키 비밀번호는 모두 `android`입니다. 실험용 서버 APK를 동일한 서명으로 업데이트하여 로컬 DB를 보존하려고 저장소에 포함했습니다. 운영용 비밀 키로 사용하지 않습니다. 향후 별도의 릴리스 서명이 필요하면 `IDOLY_SERVER_KEYSTORE`, `IDOLY_SERVER_STORE_PASSWORD`, `IDOLY_SERVER_KEY_ALIAS`, `IDOLY_SERVER_KEY_PASSWORD`를 설정할 수 있습니다.

표준 Gradle wrapper만 참고 저장소에서 재사용했으며 앱 구현은 독립적으로 작성했습니다. 실제 게임 플레이 지원 범위는 서버의 구현된 기능에 따라 달라집니다.
