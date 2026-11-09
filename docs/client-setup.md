# 같은 기기에서 로컬 게임·서버 앱 실행

[릴리스](https://github.com/tagundo/IdolyPride_client/releases)의 서버 앱과 로컬 게임 클라이언트를 함께 설치합니다. **터미널·Python·Termux 없이 서버 앱의 버튼으로 실행합니다.** Android는 같은 Android 기기에서, PlayCover는 같은 Mac에서 서버와 게임을 실행합니다.

현재는 개발 중인 프로토타입입니다. 서버의 암호화 HTTP/2 통신과 저장 동작을 검증했지만 실제 게임 클라이언트의 로그인·홈 화면 진입·라이브 플레이는 아직 확인하지 않았습니다.

## Android

ARM64 기기와 Android 8 이상이 필요합니다. 릴리스에서 다음 두 파일을 받습니다.

| 파일 | 용도 |
| --- | --- |
| `IdolyPride-Local-Server-Android.apk` | 서버 v0.2.0 앱, 표시 이름 **아이프라 서버** |
| `IdolyPride-6.1.1-Local-Android.apk` | 게임 클라이언트, 표시 이름 **아이프라 로컬** |

1. 파일 앱에서 두 APK를 설치합니다. 필요한 경우 해당 파일 앱의 APK 설치 권한을 허용합니다.
2. **아이프라 서버**를 열고 **서버 시작**을 누릅니다. 첫 실행에는 앱에 포함된 서버 데이터를 준비합니다.
3. **실행 중**으로 바뀌면 **아이프라 로컬 실행**을 누릅니다. 서버 실행 알림을 유지한 채 게임을 사용합니다.
4. 끝나면 서버 앱에서 **서버 중지**를 누릅니다. Android가 백그라운드 앱을 종료했다면 서버 앱을 다시 열어 시작합니다.

서버 패키지는 `game.qualiarts.idolypride.localserver`, 게임 패키지는 `game.qualiarts.idolypride.local`입니다. 기존 공식 게임과 별도로 설치하며 공식 계정이 자동으로 옮겨지지는 않습니다.

서버 v0.2.0 개발 APK는 고정된 **공개 개발 서명**을 사용합니다. 같은 서명의 후속 APK를 업데이트 설치하면 앱 전용 저장소의 DB가 유지됩니다. **업데이트하려고 기존 서버 앱을 먼저 삭제하지 마세요. 앱 삭제나 설정의 데이터 지우기는 프로필·진행 DB를 삭제합니다.**

## Mac + PlayCover

Apple Silicon Mac과 macOS 13 이상이 필요합니다. Python·Homebrew 설치는 필요하지 않습니다. 릴리스에서 다음 두 파일을 받습니다.

| 파일 | 용도 |
| --- | --- |
| `IdolyPride-Local-Server-macOS-arm64.app.zip` | 서버 v0.2.0 앱 |
| `IdolyPride-6.1.1-Local-PlayCover.ipa` | PlayCover용 로컬 게임 클라이언트 |

1. ZIP을 풀어 `IdolyPrideLocalServer.app`을 **응용 프로그램** 폴더로 옮깁니다.
2. PlayCover에서 로컬 IPA를 가져와 설치·재서명합니다. 원본 공식 앱 대신 별도의 **아이프라 로컬**이 설치됩니다.
3. 서버 앱을 열어 **서버 시작**을 누릅니다. 앱은 ad-hoc 서명이며 Apple 공증은 포함되지 않습니다. macOS가 실행을 차단하면 **시스템 설정 → 개인정보 보호 및 보안**에서 해당 앱의 실행을 허용합니다.
4. **로컬 서버가 실행 중입니다**가 표시되면 **아이프라 열기**를 누르거나 PlayCover에서 **아이프라 로컬**을 엽니다.
5. 게임을 사용하는 동안 서버 앱을 켜 둡니다. **중지**를 누르거나 앱을 종료하면 서버도 종료됩니다.

데이터는 `~/Library/Application Support/IdolyPrideLocal`에 저장합니다. 서버 앱의 **데이터 폴더** 버튼으로 열 수 있습니다. 서버 앱 교체·업데이트와 별개로 보존하며, 백업하려면 서버를 중지한 뒤 이 폴더를 복사합니다. 로컬 게임의 bundle ID는 `game.qualiarts.idolypride.local`입니다.

## 포함된 데이터와 저장 상태

두 서버 앱은 게임 API `127.0.0.1:50051`, 마스터 파일 `127.0.0.1:8080`을 사용합니다. `127.0.0.1`은 게임을 실행하는 기기 자체입니다. 같은 포트의 소스 서버나 Termux 서버를 함께 실행하지 않습니다.

v0.2.0에는 6.1.1 스키마, 원본 암호화 마스터 202개, 시작 데이터용 JSON, 공개 약관·도움말 응답 10개가 포함됩니다. 첫 실행은 이 공개 데이터를 준비하며 공식 로그인이나 계정 수집을 실행하지 않습니다. 모델·음성·영상 등의 전체 Octo 리소스가 포함된 것은 아닙니다.

새 `sandbox` 프로필은 실제 마스터에서 선택한 시작 캐릭터 5명과 검증한 기본·라이브 의상·헤어, 레벨 1 매니저, 빈 덱을 준비합니다. 카드·통화·전투 보상·전체 해금은 지급하지 않습니다. 기존 snapshot은 자동 초기화하거나 시작 데이터로 바꾸지 않습니다.

홈 로그인·진입·리뷰·캐릭터 배치, 빈 로컬 공지·팝업 목록, 마스터 버전, 튜토리얼 초기화·진행·스킵의 **10개 RPC**와 기존 덱 수동 편집·삭제(`Deck.Save/Delete`)를 구현했습니다. 신규 덱 번호 발급·자동 편성·대여 편성은 아직 지원하지 않습니다. 설정과 일부 게임 상태는 SQLite 트랜잭션으로 저장합니다. 전투·카드 육성·가챠·구매·보상 계산은 미구현이며 구현이나 fixture가 없는 요청은 `UNIMPLEMENTED`입니다. 자세한 범위는 [게임 상태 구현 문서](gameplay-status.md)를 참고합니다.

| 데이터 | Android 서버 앱 | Mac 서버 앱 |
| --- | --- | --- |
| 상태 DB | 앱 전용 `files/data/state.db` | `~/Library/Application Support/IdolyPrideLocal/state.db` |
| 공개 스키마·마스터·JSON | 앱 전용 `files/data/` 아래 | 위 데이터 폴더 아래 |
| 앱 업데이트 | 같은 서명으로 설치하면 DB 유지 | 데이터 폴더 유지 |
| 앱 삭제 | 앱 데이터도 삭제 | 데이터 폴더는 별도 보관 |

서버 앱에는 공식 계정 인증정보가 없습니다. 기존 계정의 snapshot·응답·PlayCover Firebase archive를 보존하는 개발 도구는 [README의 계정 보존 절차](../README.md#로그인된-공식-세션에서-보존)를 참고합니다. Firebase archive는 현재 게임 세션 metadata와 다르며 새 로컬 앱이 공식 계정을 자동 복원하지 않습니다. archive·토큰·세션 파일을 채팅이나 공개 저장소에 올리지 않습니다.

## 패치·검증 범위

연결용 게임 클라이언트는 원본 API 문자열을 로컬 주소로 바꾸고, 검증된 6.1.1 native 바이너리의 6개 진입점을 패치합니다. Seed 초기화·갱신과 Firebase ID token 취득을 완료된 UniTask로 대체하고 기존 사용자 검사를 통과시킵니다. 대체 문자열은 서버가 무시하는 로컬 식별자이며 실제 인증정보를 읽지 않습니다. `Auth.Login` RPC는 유지해 로컬 서버에서 새 세션을 받습니다.

ARM64 스텁은 원본 해시·진입 바이트를 검사하며 Unicorn에서 반환 구조·레지스터·스택 보존을 실행 검증했습니다. Android 게임 APK의 서명·16KiB 정렬도 확인했습니다. native 코드 분석에서 `http` 주소가 `YetAnotherHttpHandler.Http2Only`를 설정하는 h2c 경로와 `https` 전용 인증서 분기를 확인했습니다. 이는 **정적 분석 근거**이며 게임 앱의 네트워크 실행 검증은 아직 아닙니다. 서버 측 실제 HTTP/2·암호화 protobuf 교환 테스트와 구분합니다.

Firebase Analytics·푸시 알림·구매 SDK 호출과 Octo 리소스 경로는 남아 있습니다. 현재 패치는 인증 부팅의 온라인 의존성을 줄이며 완전한 네트워크 격리나 전체 게임 플레이를 보장하지 않습니다.

Android 서버의 공개 개발 키와 게임 클라이언트의 서명 키는 별개입니다. 게임 APK를 직접 다시 빌드한다면 `data/client-signing/local-client.p12`와 `local-client.password`를 보존해야 같은 서명으로 업데이트할 수 있습니다. 기존 게임 클라이언트의 초기 CI 빌드는 임시 개발 키를 사용하므로 임의 재빌드 APK와 업데이트 호환을 가정하지 않습니다. PlayCover용 IPA는 PlayCover가 재서명합니다.

## 개발용 소스·Termux 실행

아래는 서버 코드를 개발하거나 별도 데이터 경로를 사용하는 경우의 선택 절차입니다. 배포 서버 앱과 동시에 실행하지 않습니다. 소스 실행의 기본 DB는 저장소의 `data/state.db`이며 서버 앱의 DB와 자동 공유하지 않습니다.

Mac에서는 Python 3.12 이상을 먼저 설치하고 저장소 루트에서 실행합니다. 스크립트는 macOS에 Python을 자동 설치하지 않습니다.

```sh
bash tools/setup_local_server.sh
.venv/bin/python tools/run_local_server.py \
  --client "$HOME/Downloads/game.qualiarts.idolypride-6.1.1-Decrypted.ipa" \
  --download-master
```

Termux에서는 저장소를 준비한 뒤 다음을 실행합니다.

```sh
bash tools/setup_local_server.sh
termux-setup-storage
.venv/bin/python tools/run_local_server.py \
  --client "$HOME/storage/downloads/idolypride-6.1.1.xapk" \
  --download-master
```

Termux 설치 스크립트는 `python`, `python-grpcio`, `capstone`, `clang`, `make`를 설치하고 `--system-site-packages` venv로 Termux의 grpcio를 사용합니다. Capstone binding·PyCryptodome 빌드가 필요할 수 있으며 실제 Termux 설치 완료는 미검증입니다.

`--client`는 스키마가 없을 때만 읽고, 외부 마스터 다운로드는 명시한 `--download-master`에서만 실행합니다. 새 데이터 경로에는 원본 클라이언트 파일 또는 준비된 ServerData가 필요합니다. 첫 준비 이후에는 `.venv/bin/python tools/run_local_server.py`로 실행합니다. 종료는 `Ctrl+C`입니다.

소스 helper는 기존 snapshot·세션·fixture를 보존하고 최소 신규 프로필을 만듭니다. 앱의 마스터 기반 시작 캐릭터 초기화와는 별도 경로입니다. `--data-dir /path/to/data --profile restored`로 데이터를 선택할 수 있고 `--manager-name`은 신규 프로필에만 적용됩니다. 전체 CLI·스키마 추출·fixture·마스터 준비는 [README 개발 절차](../README.md#개발용-소스-실행)를 참고합니다.
