# iPhone·iPad 통합 IPA

기존 한국어 게임 IPA에 iOS용 로컬 서버를 넣습니다. 앱을 열면 서버 화면이 먼저 표시되고, 앱 내부의 별도 스레드에서 서버와 리소스 서버를 준비합니다. 준비가 끝난 뒤 사용자가 **게임 시작**을 눌러야 Unity가 시작됩니다. macOS용 Python이나 별도 서버 프로세스를 실행하지 않습니다.

[검증된 통합 IPA 시험판](https://github.com/tagundo/IdolyPride_client/tree/downloads/ios-unified-prototype-source-7afaeda34a7c762c9a7fe2ffe4ea3fc9b6c4d2a6)과 정확한 [검증 범위](VALIDATION.md)를 확인할 수 있습니다.

빌드 `156.9102`에서는 **게임 중 화면 오른쪽 위를 한 손가락으로 3초간 길게 누르면** 서버 메뉴를 다시 엽니다. 모서리의 작은 영역에만 적용되며 짧은 터치와 드래그는 일반 게임 입력으로 전달됩니다. Mac에서는 앱 메뉴의 **로컬 서버 설정…** 또는 **⌘⇧,**도 사용할 수 있습니다. 세 손가락 제스처는 사용하지 않습니다. 언어·해금 모드·그래픽·화면 확장·촬영 옵션과 리소스 다운로드·ZIP 가져오기/내보내기를 사용할 수 있습니다. 언어와 해금 모드 변경은 다음 앱 실행부터 적용합니다. 다운로드 리소스는 앱의 `Documents/IdolyPride`에 보관하고 iOS ‘파일’ 앱으로 접근합니다. 계정과 설정은 `Library/Application Support/IdolyPrideLocal`에 별도로 보관합니다.

iPhone·iPad를 우선합니다. 기기용 IPA는 개인 서명 후 설치해야 합니다. 같은 IPA의 PlayCover 호환성은 별도 확인 대상입니다. 실제 기기에서의 MV 재생·성능 검증과 시뮬레이터의 서버 코어 검증은 구분합니다. 시뮬레이터용 가짜 Unity 진입점과 검사 우회 코드는 기기용 프레임워크에 포함하지 않습니다. 선택적인 실험용 Go 라이브 시뮬레이터는 이 iOS 이식 범위에 포함하지 않습니다.

## 빌드와 검증

`.github/workflows/build-server-apps.yml`의 `ios_unified=true`를 선택합니다. 기존 Android·Mac 릴리즈 작업을 실행하거나 기존 배포 파일을 바꾸지 않고 Actions 후보 파일을 만듭니다.

1. `fetch_inputs.py`가 SHA-256으로 고정한 기존 게임·서버 데이터·번역 데이터, BeeWare iOS Python과 순수 Python 의존성을 받습니다.
2. `prepare_runtime.py`가 실제 iOS 플랫폼을 확인하고 Python 확장 모듈을 서명 가능한 프레임워크로 변환합니다. `.fwork`/`.origin`으로 로드하며 느슨한 `.so`를 넣지 않습니다.
3. `native/build_native.py`가 실제 Apple SDK로 기기용 서버 프레임워크를 빌드합니다. Unity의 UUID·진입점 ABI가 일치할 때만 시작을 대기시킵니다.
4. `patch_load.py`와 `package_unified.py`가 기존 Unity 헤더의 빈 공간에 의존성 하나를 추가합니다. 기존 게임 코드·SDK·리소스 바이트는 유지하고, 앱 정보와 추가 서버 파일만 바꿉니다.
5. 별도 시뮬레이터용 프레임워크·검사용 앱을 만들고 새 시뮬레이터에서 서버 준비, CommonCrypto AES, 암호화된 실제 RPC와 상태 저장을 검사합니다. 기존 시뮬레이터나 사용자 데이터를 사용하지 않습니다.

빌드 산출물에는 IPA, SHA-256, 프레임워크·원본 보존 검사와 시뮬레이터 결과를 함께 보관합니다. 자세한 내부 경계는 [CONTRACT.md](CONTRACT.md)에 정리했습니다.

GitHub Actions를 사용할 수 없는 경우 Mac에서 전체 Xcode·iOS Simulator 런타임·기본 아키텍처의 Python 3.13·GitHub CLI와 여유 공간 8 GiB를 준비합니다. 별도 아이프라 서버를 종료하고 `gh auth login` 후 `ios-unified/build_on_mac.command`를 실행합니다. 새 `~/Downloads/IdolyPride/builds/날짜-커밋/` 안에서 같은 빌드와 검사를 진행합니다. 기존 게임·서버·리소스·계정 폴더를 변경하지 않습니다.
