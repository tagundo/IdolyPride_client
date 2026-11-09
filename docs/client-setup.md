# 같은 기기에서 로컬 클라이언트·서버 실행

Android는 게임과 Termux 서버를 같은 기기에서, PlayCover는 게임과 서버를 같은 MacBook에서 실행합니다. 제공하는 로컬 클라이언트의 기본 API 주소는 `http://127.0.0.1:50051`입니다. `127.0.0.1`은 게임을 실행하는 기기 자체를 가리킵니다.

현재 결과물은 연결·부팅 개발용입니다. 실제 Android·PlayCover의 로그인·홈 화면 진입은 아직 검증하지 않았으며, 홈·튜토리얼·라이브 게임 로직도 완성되지 않았습니다.

## MacBook + PlayCover

Python 3.12 이상을 먼저 설치합니다. 기본 `python3`가 구버전이면 설치한 인터프리터를 `IDOLY_PYTHON=python3.12 bash tools/setup_local_server.sh`처럼 지정할 수 있습니다. 설치 스크립트는 macOS에 Python을 자동 설치하지 않습니다.

저장소 ZIP을 이미 받았다면 `IdolyPride_client-main` 폴더에서 `bash tools/setup_local_server.sh`를 실행합니다. 비공개 저장소이므로 새로 받을 때는 로그인한 GitHub의 Download ZIP 또는 인증된 Git을 사용합니다. Git을 사용하는 경우:

```sh
git clone https://github.com/tagundo/IdolyPride_client.git
cd IdolyPride_client
bash tools/setup_local_server.sh
```

[클라이언트 릴리스](https://github.com/tagundo/IdolyPride_client/releases)에서 받은 원본 복호화 6.1.1 IPA가 다운로드 폴더에 있다면 처음 한 번 다음 명령을 실행합니다. 실제 파일 위치가 다르면 `--client` 경로를 바꿉니다.

```sh
.venv/bin/python tools/run_local_server.py \
  --client "$HOME/Downloads/game.qualiarts.idolypride-6.1.1-Decrypted.ipa" \
  --download-master
```

이 명령은 누락된 스키마를 원본 파일에서 추출하고, 공개 원본 마스터 팩을 내려받고, `sandbox` 프로필이 없으면 최소 신규 snapshot을 만듭니다. 기존 snapshot·식별자·세션·fixture는 보존합니다. 첫 준비가 끝난 뒤에는 아래 명령으로 다시 실행합니다.

```sh
.venv/bin/python tools/run_local_server.py
```

터미널에 `gRPC ready: 127.0.0.1:50051`과 `HTTP files ready: 127.0.0.1:8080`이 표시되면 터미널을 열린 채 둡니다. 종료는 `Ctrl+C`입니다.

PlayCover에서 **`IdolyPride-6.1.1-Local-PlayCover.ipa`**를 가져와 설치·재서명하고 **아이프라 로컬**을 실행합니다. bundle ID와 딥링크는 `game.qualiarts.idolypride.local`로 분리했습니다. 로컬 앱의 신규 프로필은 원래 공식 계정의 자동 복원본이 아닙니다.

## Android + Termux

현재 유지되는 [Termux 배포판](https://github.com/termux/termux-app#installation)을 준비합니다. Termux에서 저장소를 받고 설치 스크립트를 실행합니다.

```sh
pkg install git
git clone https://github.com/tagundo/IdolyPride_client.git
cd IdolyPride_client
bash tools/setup_local_server.sh
```

설치 스크립트는 `python`, `python-grpcio`, `capstone`, `clang`, `make`를 설치합니다. `.venv`는 `--system-site-packages`로 만들어 Termux의 `python-grpcio`를 사용하며, 이후 프로젝트의 `[extract]` 의존성을 로컬 venv에 설치합니다. Capstone Python binding이나 PyCryptodome은 빌드가 필요할 수 있습니다. 실제 Termux에서 설치를 끝까지 실행한 검증은 아직 없습니다.

다운로드 폴더의 원본 6.1.1 XAPK를 읽으려면 처음 한 번 저장소 접근을 허용합니다.

```sh
termux-setup-storage
```

원본 XAPK를 `idolypride-6.1.1.xapk`라는 이름으로 다운로드 폴더에 준비한 경우:

```sh
.venv/bin/python tools/run_local_server.py \
  --client "$HOME/storage/downloads/idolypride-6.1.1.xapk" \
  --download-master
```

첫 준비 이후에는 `.venv/bin/python tools/run_local_server.py`로 다시 실행합니다. 서버를 켠 상태에서 **`IdolyPride-6.1.1-Local-Android.apk`**를 Android의 파일 앱에서 설치하고 **아이프라 로컬**을 실행합니다. 패키지는 `game.qualiarts.idolypride.local`입니다. 백그라운드에서 Termux가 종료되지 않도록 기기의 배터리 설정도 확인합니다.

## 저장 위치·다른 프로필

기본 저장 위치는 다음과 같습니다. `data/`는 Git에 포함되지 않으므로 기기를 옮길 때 별도로 보존해야 합니다.

| 위치 | 내용 |
| --- | --- |
| `data/protocol/idolypride-6.1.1.pb` | 원본 클라이언트에서 추출한 스키마 |
| `data/original-master/master-tag.json` | 공개 원본 MasterTag |
| `data/original-master/assets/master/` | 원본 암호화 마스터 팩 |
| `data/state.db` | 로컬 프로필·snapshot·세션 |
| `data/<프로필>/fixtures/` | 해당 프로필의 보존 응답 |

기존 데이터를 다른 디렉터리에 보관하거나 다른 프로필을 실행할 수 있습니다.

```sh
.venv/bin/python tools/run_local_server.py --data-dir /path/to/idoly-data --profile restored
```

`--manager-name '로컬 매니저'`는 snapshot이 없는 프로필을 처음 만들 때만 적용합니다. 새 프로필은 이름·레벨 1·로컬 식별자만 초기화하며 카드·튜토리얼·콘텐츠 해금은 수행하지 않습니다. 기존 `User.Get`을 가져오는 절차는 [README](../README.md#신규기존-로컬-프로필)를 참고합니다.

`--client`는 스키마가 없을 때만 읽습니다. Android의 base APK와 ARM64 split APK가 나뉘어 있다면 `--client base.apk --native config.arm64_v8a.apk`를 사용할 수 있습니다. 신규 데이터 경로에는 원본 클라이언트 파일을 지정해야 합니다.

일반 재실행은 외부 다운로드를 하지 않습니다. 원본 마스터를 새로 받거나 이어 받으려는 경우에만 `--download-master`를 붙입니다. 이 옵션은 계정이나 Firebase 인증 없이 공개 마스터 API·CDN에 접속합니다.

기본 포트를 바꾸려면 `--grpc-port`·`--asset-port`를 지정할 수 있습니다. 게임 클라이언트에는 API 주소가 패키징 시 저장되므로 gRPC 포트를 바꾸면 해당 주소로 다시 패키징해야 합니다. 다른 기기에서 접속하는 구성은 서버의 `--grpc-host`·`--asset-host`·`--asset-base-url`도 그 기기에서 접근 가능한 주소로 맞춰야 합니다. 같은 기기에서는 기본값을 사용합니다.

## 패키징·검증 범위

로컬 클라이언트는 원본 API 문자열을 로컬 주소로 바꾸고, 검증된 6.1.1 원본 native 바이너리의 6개 진입점을 패치합니다. Seed 초기화·갱신과 Firebase ID token 취득을 완료된 UniTask로 대체하고 기존 사용자 검사를 통과시킵니다. 임시 문자열은 로컬 서버가 무시하는 식별자이며 실제 인증정보를 읽지 않습니다. `Auth.Login` RPC는 유지해 로컬 서버에서 새 세션을 받습니다.

ARM64 스텁은 두 플랫폼의 실제 원본 해시·진입 바이트를 확인했고 Unicorn에서 반환 구조와 레지스터·스택 보존을 실행 검증했습니다. Android APK는 서명·16KiB 정렬을 확인했고 iOS IPA는 PlayCover 가져오기·재서명을 위한 별도 bundle로 구성했습니다. 버전이 다른 native 입력은 기본 패치가 거부합니다.

네이티브 코드 분석에서 `http` 주소가 `YetAnotherHttpHandler.Http2Only`를 설정하는 h2c 경로와 `https`에서만 실행되는 인증서 분기를 확인했습니다. 로컬 서버의 실제 HTTP/2 gRPC·암호화 protobuf 교환도 테스트했습니다. 게임 앱의 실제 연결·화면 부팅은 별도 기기 검증이 필요합니다.

Firebase Analytics·푸시 알림·구매 SDK 호출과 Octo 리소스 경로는 아직 남아 있습니다. 현재 패치는 인증 부팅의 온라인 의존성을 줄이며 완전한 네트워크 격리나 전체 게임 플레이를 보장하지 않습니다. 원본 마스터 202개 보존은 모델·음성·영상 등 전체 Octo 리소스 보존과도 구분합니다.

Android를 다시 빌드할 때는 `data/client-signing/local-client.p12`와 `local-client.password`를 함께 보존합니다. 같은 로컬 앱의 업데이트에는 같은 서명 키가 필요합니다. 이 파일이나 공식 계정 인증 archive·세션 metadata는 공유하지 않습니다. PlayCover용 IPA는 PlayCover가 로컬에서 재서명합니다.

설치·실행 helper는 셸 문법, 플랫폼 명령 선택을 모의한 테스트, 실제 SQLite 프로필·세션 보존, 추출·다운로드·서버 경계 테스트를 통과했습니다. 실제 macOS·Termux 설치 성공과 앱 화면 동작은 아직 확인하지 않았습니다.
