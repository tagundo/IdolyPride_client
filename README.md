# IDOLY PRIDE 로컬 서버와 통합 클라이언트

**[최신 릴리즈 v0.3.32](https://github.com/tagundo/IdolyPride_client/releases/tag/local-server-v0.3.32)** · [Android 서버 APK](https://github.com/tagundo/IdolyPride_client/raw/5eb868ca2860ecaa092d70977eb1b0d7c92b2759/IdolyPride-Local-Server-Android.apk) · [통합 IPA 156.9112](https://github.com/tagundo/IdolyPride_client/raw/5eb868ca2860ecaa092d70977eb1b0d7c92b2759/IdolyPride-6.1.1-Unified-iOS.ipa) · [Apple Silicon Mac 서버](https://github.com/tagundo/IdolyPride_client/raw/5eb868ca2860ecaa092d70977eb1b0d7c92b2759/IdolyPride-Local-Server-macOS-arm64.app.zip) · [수정·측정·검증 기록](docs/releases/optimization-v0.3.32.md)

서버 상태 조회에서 버려지던 전체 진단 기록 복사와 번역 자료 검증의 중복 메모리를 줄였습니다. 같은 소스로 세 플랫폼 파일을 제작하고 전체 검사·플랫폼 실행 검사·게시 파일 전체 SHA-256 검증을 통과했습니다. 실제 게임 FPS 개선량을 측정한 릴리즈는 아닙니다.

## 앱으로 실행하기

| 환경 | 받을 파일 | 실행 방법 |
| --- | --- | --- |
| Android ARM64, Android 9 이상 | [서버 APK v0.3.32](https://github.com/tagundo/IdolyPride_client/raw/5eb868ca2860ecaa092d70977eb1b0d7c92b2759/IdolyPride-Local-Server-Android.apk) + [한국어 게임 APK v0.3.31 재사용](https://github.com/tagundo/IdolyPride_client/raw/3b2c73b51931bb7be031c37c9d55297505fb88e1/IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk) | 서버 앱에서 **서버 시작 → 아이프라 실행** |
| iPhone·iPad | [서버·게임 통합 IPA 156.9112](https://github.com/tagundo/IdolyPride_client/raw/5eb868ca2860ecaa092d70977eb1b0d7c92b2759/IdolyPride-6.1.1-Unified-iOS.ipa) | 개인 서명 후 설치하고 서버 준비가 끝나면 **게임 시작** |
| Apple Silicon Mac / PlayCover | [통합 IPA 156.9112](https://github.com/tagundo/IdolyPride_client/raw/5eb868ca2860ecaa092d70977eb1b0d7c92b2759/IdolyPride-6.1.1-Unified-iOS.ipa) 하나, 또는 [Mac 서버 v0.3.32](https://github.com/tagundo/IdolyPride_client/raw/5eb868ca2860ecaa092d70977eb1b0d7c92b2759/IdolyPride-Local-Server-macOS-arm64.app.zip) + [별도 한국어 PlayCover IPA v0.3.31 재사용](https://github.com/tagundo/IdolyPride_client/raw/7fcc9f8661b5158cf66d93e9c307607db2c2ee43/IdolyPride-6.1.1-Local-PlayCover-ko.ipa) | 통합판은 **게임 시작**. 별도 서버는 **서버 시작 → PlayCover에서 열기** 후 PlayCover에서 **아이프라 로컬** 실행 |

별도 한국어 게임 APK와 PlayCover IPA는 검증된 기존 v0.3.31 파일이며 이번에 재제작하지 않았습니다. Mac 서버 ZIP은 풀어서 앱을 교체합니다. 같은 앱은 삭제·데이터 지우기 없이 업데이트하면 계정·설정·받은 리소스를 유지합니다. Android 서버는 같은 앱 식별자와 공개 개발 서명을 사용하고, 게임 APK는 기존 Diagnostics 앱 식별자를 유지하면서 **아이프라 로컬**로 표시합니다.

**통합 IPA와 별도 PlayCover IPA는 같은 게임 앱 식별자를 쓰는 대안입니다.** 통합판은 서버를 포함하므로 별도 Mac 서버를 완전히 종료하고 사용합니다. 별도 서버 구성에서는 게임을 사용하는 동안 서버를 켜 둡니다. 두 구성의 서버 저장 위치가 달라 자동 계정 이전을 보장하지 않습니다.

통합 IPA는 앱을 열면 서버 메뉴를 먼저 표시합니다. 게임 중에는 오른쪽 위 안전 영역을 **2초간 길게 눌러** 서버 메뉴를 엽니다. Mac에서는 **로컬 서버 설정… / ⌘⇧,**도 지원합니다. 메뉴를 닫아도 서버는 유지됩니다. 서버 화면 언어는 즉시 바뀌며, 게임에 들어간 뒤 바꾼 게임 언어는 앱을 완전히 종료·재실행하면 적용됩니다. 번역이 없는 문구·이미지는 원본으로 표시합니다. [통합 IPA 안내](ios-unified/README.md)

Mac 별도 서버의 계정·설정은 `~/Library/Application Support/IdolyPrideLocal`, 통합판은 앱 컨테이너의 `Library/Application Support/IdolyPrideLocal`에 보관합니다. 선택한 리소스 보관 위치도 업데이트할 때 유지합니다. 게임 API는 `127.0.0.1:50051`, 파일 서버는 `127.0.0.1:8080`이며 같은 기기에서 연결합니다.

검증은 전체 코드 검사, Android x86_64 에뮬레이터의 실제 서버 UI·암호화 RPC·업데이트 후 보존, 실제 Mac 앱의 시작·중지와 서명, Apple SDK 빌드와 iOS Simulator의 KO→EN→JA→EN→KO 재실행을 포함합니다. 이번 파일의 Android ARM64 실기기와 PlayCover·iPhone·iPad 실제 게임 재검증은 별도 대상입니다. [세부 검증과 해시](docs/releases/optimization-v0.3.32.md)

[촬영·의상·리소스 보관 안내](docs/local-library-v0.3.19.md) · [번역 출처](docs/translation-catalog.md) · [감상 모드](docs/media-mode.md) · [기존 클라이언트 설치 안내](docs/client-setup.md)

## 기능별 구현 기록

아래 버전 표시는 각 기능을 추가할 당시의 기록입니다. 현재 배포 파일과 검증 범위는 위 v0.3.32 안내를 따릅니다.

| 기능 | 상태 |
| --- | --- |
| 6.1.1 protobuf·암호화 gRPC | 스키마 로딩, SolisClient 양방향 호환, 실제 localhost HTTP/2 교환 검증 |
| `System.Check`, `System.GetMetadata`, `System.CheckApp`, `Auth.Login` | 로컬 응답·SQLite 프로필·세션 구현 |
| `Refund.GetTerm` | 제목 화면에서 로그인 없이 조회; 로컬 환불 기간 비활성·유료 상점 닫힘 |
| `User.Get` | 계정별 fixture 우선, 다음 SQLite snapshot 제공 |
| 홈·설정·튜토리얼 10개 RPC | `Home.Login/Enter/SetReview/SetCharacterPosition`, `Dokan.List`, `Notice.List`, `Master.GetVersion`, `Tutorial.Init/Progress/Skip` 구현 |
| `Deck.Save/Delete` — v0.3.1 | 새 번호 할당, 기존 덱 편집·삭제, 편집 모드 1~4의 클라이언트 선택 배치 저장과 보유 참조 검증 |
| `Quest.Top/ListMain/ListAsset` | 메인·튜토리얼 목록과 저장된 5인 덱의 캐릭터·의상·헤어 리소스 참조 조회; 잠긴 하이스코어 정보 제공, 전투·보상 생성 없음 |
| `Tutorial.StartQuest` | 검증된 공식 short/full 기록의 고정 시연 편성 재생; 로컬 사용자 표시·필요 리소스 연결, 계정 상태 변경 없음 |
| 첫 일반 라이브 — v0.3.0 베타 | 기본값 꺼짐인 실험 기능; 첫 메인 퀘스트만 현재 덱·능력치·스킬로 로컬 계산, 첫 성공 보상·경험치 1회와 결과 저장, 동일 요청 재시도 시 원래 응답 반환 |
| 첫 메인 라이브 SKIP — v0.3.2 | 같은 실제 계산·정산으로 하이라이트 시작 지원; Android 기존 클리어 계정 반복·업데이트·재시작 검사, 새 계정 첫 클리어·실패는 Linux 네이티브 검사 |
| 프로필 — v0.3.0 베타 | 저장된 계층 정보 조회, 이름·소개문·즐겨찾기 순서 저장·해제; 공식 금칙어·미션 보상 제외 |
| 포토 이름·프로필 레이아웃 — v0.3.4 후보 소스 | 보유 포토 이름과 기존 프로필의 레이아웃·정보·색상 선택 저장; 배포된 v0.3.2 앱에는 미포함 |
| 게임 리소스 — v0.3.4 후보 소스 | 일본 Android 6.1.1의 원본 목록·암호화 형식, 검증 후 보관하는 요청별 파일 제공·HEAD·Range; 원본 SDK 적용 후 실제 게임 검증은 진행 중 |
| 이미지 트레이닝·VENUS 읽기 모듈 — v0.3.4 후보 소스 | 모듈 포함; 실제 읽기는 개인 카탈로그와 추가 마스터를 준비한 별도 소스 환경 필요. 후보의 기존 데이터만으로 이벤트 메뉴를 복원하지 않으며 가져오기 UI·생성·대전·정산은 미지원, 배포된 v0.3.2 앱에는 미포함 |
| 카드 레벨 미션 — v0.3.0 베타 | 검증된 `ms-normal-card_level_achievement` 목록과 보유 카드의 최고 레벨 진행 저장; 다른 미션·보상 수령 제외 |
| 튜토리얼 후반 | 레슨 보상 1회 지급·초기 카드 강화·사쿠라 메시지 조회/선택 저장/완료; 명시적 `Progress150`으로 완료 |
| `Activity.ReceiveLessonReward` | 초기 메인 지역의 기본 레슨 보상을 10초 단위로 최대 12시간 누적·수령; 재시도·재시작 후 시간과 재화 보존 |
| 선물함·친구 목록 | 비어 있는 로컬 선물함·수령 이력·친구·신청·검색 목록 조회; 수령·관계 변경은 미구현 |
| `Story.ListEvent/ListExtra` | 고정 공개 기본 목록: 이벤트55개·272에피소드, 특별3개 분류·41개·154에피소드; 기존 읽음·계정별 잠금·빈 목록 유지 |
| `Story.Read/ReadEvent/ReadExtra` | 기본 목록 425개 Story의 완료·스킵 저장; 보상 있는 282개는 무료 스톤 30개를 한 번만 지급, 재시작·재시도 중복 지급 방지 |
| 의상·헤어 | 보유 외형과 라이브 기본 외형 선택, 개별·일괄 새 항목 확인; 캐릭터·착용 호환성 검증과 저장·재시작 유지 |
| 전체 해금 감상 모드 — v0.3.5 후보 | 별도 DB에 실제 캐릭터·의상·헤어·카드·스토리 및 촬영 목록 준비, 무료 스토리 읽기·선택 저장; API·빌드 검사 통과, 실제 재생 완료 검증은 별도 |
| 신규 앱 프로필 | 기본 캐릭터·초기 카드 17명분과 초기 아이템 2종, 서로 다른 홈 4곳·5인 기본 편성, 레벨 1; 알려진 구형 빈 계정만 보완 |
| 공개 약관·도움말 | `Master.Rule`·`Master.GetHelpCategory`의 요청별 공개 응답 10개 동봉 |
| `Master.Get`·파일 제공 | 현재 원본 마스터 202개·77,283,328바이트 보존·제공 |
| 기존 계정 보존 | `User.Get` snapshot 가져오기와 제한된 공식 세션 읽기 수집 구현; 실제 계정 수집은 미검증 |
| 나머지 일반 라이브·확장 육성·가챠·구매·전체 게임 진행 | 첫 메인 퀘스트 실험 범위 밖의 기능은 미구현 |
| 실제 게임 앱의 홈 진입·플레이 | 사용자 Android 기기의 홈·모델·편성·초기 튜토리얼 완료 확인; 공식 ARM64 Cuttlefish·QEMU TCG에서도 로그인·홈 API 교환 뒤 실제 홈·캐릭터 모델·공지 닫기 확인, 이 환경의 일반 라이브·감상 재생 완료는 미검증 |

`Deck.Save`는 `Manual(1)`, `Auto(2)`, `ManualAuto(3)`, `QuestAuto(4)`로 전달된 배치를 검사해 저장합니다. 서버 자체의 최적 편성 계산과 버디 대여는 미지원이며, `Unknown(0)`·알 수 없는 모드·대여 버디 요청은 상태를 변경하지 않고 거절합니다. 자세한 수정·검증 범위는 [자동 편성 저장 안내](docs/gameplay-status.md#자동-편성-저장-수정-v031)에 있습니다.

홈·튜토리얼 변경은 SQLite 트랜잭션으로 저장하며 활성 로컬 세션과 알 수 없는 protobuf 필드를 유지합니다. 신규 시작 데이터는 원본 `initial_user_reward`의 카드·아이템을 준비합니다. 튜토리얼 레슨 보상은 마스터의 수량만 한 번 더하며, 완료는 클라이언트의 명시적 진행 요청으로 기록합니다. 튜토리얼 시연은 원본 기록의 편성·스킬·차트·점수를 재생합니다. v0.3.0의 첫 메인 라이브 실험 기능은 첫 성공 보상과 경험치만 한 번 지급하며, 팬·음악 숙련도·미션 보상·전체 해금을 만들지 않습니다. 구현된 RPC의 세부 동작과 근거는 [게임 상태 구현 범위](docs/gameplay-status.md)에 정리했습니다. 구현이나 fixture가 없는 RPC는 `UNIMPLEMENTED`입니다.

`Auth.Login`은 Firebase 토큰을 검증하거나 저장하지 않고 로컬 세션을 발급합니다. 연결용 클라이언트는 공식 Seed·Firebase 인증 부팅을 버전별 네이티브 패치로 대체하고 로컬 `Auth.Login`을 유지합니다. Analytics·스토어 SDK는 남아 있습니다. 배포된 기존 연결판의 Octo 경로는 공식 서버를 사용하며, v0.3.4 후보의 새 연결판은 리소스 목록·파일을 로컬 서버로 요청합니다. 아직 보관하지 않은 파일을 받으려면 공식 CDN 연결이 필요하므로 모든 자료가 오프라인으로 준비됐다는 뜻은 아닙니다.

## 개발용 클라이언트 패키징

아래는 원본 6.1.1에서 연결용 게임 클라이언트를 다시 만드는 개발 명령입니다. 배포된 APK·IPA를 사용하는 경우 실행하지 않습니다.

```sh
# Android: JDK, Android SDK build-tools, APKEditor.jar 필요
uv run --all-extras python tools/package_android_client.py /path/to/client.xapk --output data/clients/local.apk

# PlayCover: 검증된 복호화 6.1.1 IPA 필요
uv run --all-extras python tools/patch_ios_client.py /path/to/client-decrypted.ipa --output data/clients/local.ipa
```

다른 API 주소는 `--endpoint http://192.168.0.10:50051`로 지정합니다. 기본 패치는 알려진 6.1.1 원본의 해시·진입 바이트를 확인하며 다른 바이너리는 거부합니다. 서버 앱 빌드는 [Android](android-server/README.md)·[macOS](macos-server/README.md) 문서를 참고합니다.

## 개발용 소스 실행

앱 설치 대신 서버 코드를 개발·시험하는 경우의 절차입니다. 일반 사용자는 위의 서버 앱을 사용합니다. Termux·소스 실행 helper는 [설치 안내의 개발용 절차](docs/client-setup.md#개발용-소스termux-실행)를 참고합니다.

Python 3.12 이상과 [uv](https://docs.astral.sh/uv/)가 필요합니다. 새 clone에는 게임 파일·추출 스키마가 포함되지 않으므로, 먼저 releases에서 받은 6.1.1 XAPK로 스키마를 준비합니다. 이 저장소 루트에서 실행합니다.

```sh
uv sync --extra extract
uv run --extra extract python tools/extract_client_schema.py /path/to/idolypride-6.1.1.xapk --output data/protocol/idolypride-6.1.1.pb
uv run idoly-local inspect
uv run idoly-local smoke
uv run idoly-local serve
```

기본 gRPC 주소는 `127.0.0.1:50051`, 상태 DB는 `data/state.db`, fixture 디렉터리는 `data/fixtures`입니다. `smoke`는 임시 DB와 실제 localhost gRPC 연결로 통신·로그인·fixture·세션 보존을 확인하며 공식 서버에 접속하지 않습니다.

스키마는 `data/protocol/idolypride-6.1.1.pb`가 있으면 우선 사용하고, 없으면 형제 디렉터리 `../SolisClient`의 생성된 protobuf 모듈을 읽습니다. 대체 경로를 지정할 수도 있습니다. **전역 옵션은 하위 명령 앞에 둡니다.**

```sh
uv run idoly-local --descriptor-set /path/to/client-schema.pb inspect
uv run idoly-local --solis-dir ../SolisClient smoke
uv run idoly-local --solis-dir ../SolisClient export-schema data/protocol/solis.pb
```

게임 파일 없이 전송 계층만 시험하려면 [SolisClient](https://github.com/vilebbit/SolisClient)의 분석 기준 커밋을 준비할 수 있습니다.

```sh
git clone https://github.com/vilebbit/SolisClient.git ../SolisClient
git -C ../SolisClient checkout a72ee470a4771858f7868a0963bece2e998a43f5
uv run idoly-local --solis-dir ../SolisClient smoke
```

이 구형 스키마와 6.1.1 스키마에는 필드 차이가 있으므로, 현재 클라이언트와 연결할 때는 해당 버전에서 추출한 descriptor를 사용합니다.

추출한 6.1.1 스키마는 359개 파일·68개 서비스·428개 RPC이며 descriptor pool 로딩과 smoke test를 통과했습니다. 전송 계층에 unary RPC 경로 427개를 등록하며, 실제 기능 구현은 위 표의 범위입니다. server-streaming `Health.Watch`는 아직 구현하지 않았습니다. 같은 버전 iOS의 359개 descriptor도 Android와 바이트 단위로 일치함을 확인했습니다.

복호화된 iOS IPA에서도 독립적으로 추출할 수 있습니다.

```sh
uv run --extra extract python tools/extract_ios_schema.py /path/to/idolypride-6.1.1-decrypted.ipa --output data/protocol/idolypride-6.1.1-ios.pb
uv run idoly-local --descriptor-set data/protocol/idolypride-6.1.1-ios.pb inspect
```

## 신규·기존 로컬 프로필

```sh
uv run idoly-local new-profile sandbox --manager-name '로컬 매니저'
uv run idoly-local serve --profile sandbox
```

위 CLI의 `new-profile`은 매니저 이름·레벨 1·로컬 식별자만 초기화하는 최소 프로필입니다. 배포 서버 앱은 검증한 기본 캐릭터 17명·외형과 원본 초기 카드·아이템, 5인 기본 편성을 준비합니다. 알려진 구형 초기 구성은 조건에 맞는 누락분만 보완하며 명시적으로 가져온 snapshot은 수정하지 않습니다. Android 홈·모델 표시·라이브 메뉴·5인 편성과 시작 버튼은 확인했습니다. 첫 일반 라이브의 네이티브 계산·결과 정산은 v0.3.0 소스에서 별도로 검사하며, 실제 게임의 일반 라이브 재생 화면 검증과 구분합니다.

기존 계정의 복호화된 `User.Get` 응답이 있으면 그대로 보존할 수 있습니다.

```sh
uv run idoly-local import-profile restored /path/to/USER.pb
uv run idoly-local serve --profile restored --fixtures data/restored/fixtures
```

암호화된 응답은 `import-profile`에 `--wire`를 붙입니다. snapshot은 사용한 스키마 지문과 함께 SQLite에 저장하며, 다른 스키마로 제공하려 하면 `FAILED_PRECONDITION`으로 거부합니다. 계정별 fixture 디렉터리도 분리해야 합니다. 기존 게임 계정의 모든 상태를 서버 로직으로 이식하는 기능과는 구분합니다.

## 로그인된 공식 세션에서 보존

현재 공식 요청의 metadata를 담은 로컬 JSON을 준비한 경우에만 사용합니다. 최소 `x-app-version`, `x-auth-token`, `x-master-version`이 필요하며 최상위 JSON 객체에 metadata 키·문자열 값을 둡니다. **이 명령은 Android·PlayCover에서 토큰을 추출하지 않습니다.** 기존 세션을 내보내는 기기별 절차는 아직 준비 중입니다. 인증 파일이나 토큰을 채팅에 보낼 필요는 없습니다.

```sh
uv run idoly-local collect-session private/session-metadata.json --output data/restored --profile restored
uv run idoly-local serve --profile restored --fixtures data/restored/fixtures
```

공식 `api.game-idolypride.jp:443`에 TLS로 접속해 `Master.Get`, `User.Get`, `Home.Enter`, `Dokan.List`, `Notice.List`를 각 한 번 읽습니다. `Home.Enter`는 `skipUpdate=true`를 사용합니다. 로그인·인증 갱신·계정 생성·일일 초기화·자동 재시도는 수행하지 않습니다. 인증 만료나 날짜 변경 오류가 나면 중단하며 원본 게임에서 먼저 정상 세션을 갱신해야 합니다.

성공한 응답은 `data/restored/fixtures`, MasterTag는 `data/restored/master-tag.json`에 저장합니다. `--profile restored`의 snapshot 가져오기는 5개 수집이 모두 성공한 뒤 수행합니다. 중간 오류가 나도 앞서 저장한 응답은 보존됩니다. 세션 metadata는 출력물에 기록하지 않습니다. 이 흐름은 테스트로 검증했으며 실제 사용자 세션 수집은 아직 실행하지 않았습니다.

### PlayCover 로컬 진단·Firebase archive

Mac의 PlayCover 설치 환경에서는 먼저 다음 명령으로 알려진 두 bundle의 기존 설정·DB 존재 여부와 스키마만 확인합니다. 인증값은 출력하지 않습니다.

```sh
uv run python tools/export_playcover_auth.py
```

이미 `playChain=true`인 앱만 Firebase 사용자 archive를 내보낼 수 있습니다. 실제 설치한 bundle ID와 해당 IPA를 지정합니다. 번역판의 bundle은 `.kr`일 수 있습니다.

```sh
uv run python tools/export_playcover_auth.py --bundle game.qualiarts.idolypride --ipa /path/to/installed-game.ipa --output private/firebase-user.archive
```

동일한 archive의 중복 행은 하나로 취급합니다. 서로 다른 기록이 여러 개면 `--diagnose`로 개수만 확인하거나, 다음 명령으로 전체 기록을 새 비공개 디렉터리에 보존할 수 있습니다.

```sh
python3 tools/export_playcover_auth.py --bundle game.qualiarts.idolypride --google-app-id 1:543065248020:ios:babf05d967621a37ab3201 --output-dir private/firebase-archives
```

전체 내보내기는 모든 archive 형식을 검증한 뒤 `001.archive` 등의 파일과 개수·파일명만 담은 manifest를 저장합니다. 디렉터리는 0700, 파일은 0600이며 기존 출력 경로는 덮어쓰지 않습니다. 현재 활성 계정을 자동 선택하거나 로그인하지 않습니다.

도구는 PlayChain DB를 read-only로 엽니다. `playChain`이나 디버그 설정을 바꾸지 않으며 native Keychain을 읽지 않습니다. PlayChain을 사용하지 않는 설치는 in-process 내보내기가 필요하다는 메시지와 함께 중단합니다. 이 archive는 현재 게임 세션 metadata가 아니므로 `collect-session`의 입력으로 바로 사용할 수 없습니다. archive·토큰은 Mac에 보관하고 채팅에 보내지 않습니다. 실제 PlayCover의 전체 내보내기는 아직 미검증입니다.

## 보존한 응답 가져오기

```sh
# 복호화된 protobuf 응답
uv run idoly-local import-response /api.User/Get /path/to/user.pb

# 암호화된 application envelope 응답
uv run idoly-local import-response /api.Home/Enter /path/to/home.bin --wire

# 특정 요청에만 적용: 요청 파일은 복호화된 protobuf
uv run idoly-local import-response /api.User/Get /path/to/user.pb --request /path/to/request.pb
```

`--wire` 입력에는 gRPC의 5바이트 프레임 헤더를 포함하지 않습니다. 요청별 fixture는 요청 바이트의 SHA-256으로 구분하며, 일치하는 fixture가 일반 fixture보다 우선합니다. 응답은 스키마로 파싱 가능한지 확인한 뒤 저장합니다. `Auth.*` 응답은 가져올 수 없습니다.

fixture는 고정 응답을 재생하며 일치하는 로컬 동작보다 우선합니다. 홈 설정·배치·튜토리얼의 일부 상태 변경은 별도 핸들러가 저장하지만, 기존 계정 전체의 게임 진행을 계산하는 기능은 아직 없습니다. 응답에는 개인 게임 데이터가 포함될 수 있으므로 `data/`와 원본 캡처는 로컬에 보관합니다. `data/`, `private/`, DB, APK·IPA, 인증서·키는 Git에서 제외합니다.

## 마스터 팩 제공

계정 없이 공식 MasterTag와 암호화 원본 팩을 보존할 수 있습니다. 익명 `System.Check`·`Master.Get`의 실제 응답을 검증했고, 현재 마스터의 202개 팩·77,283,328바이트를 모두 내려받았습니다. 파일 크기와 SHA-256으로 재개·손상 검증을 수행합니다.

```sh
uv run idoly-local archive-master --output data/original-master
```

보존한 `master-tag.json`과 `assets/master/`를 아래 서버 옵션에 연결합니다. 누락된 원본이 있을 때는 JSON 테이블을 SQLCipher 4 팩으로 재구성할 수도 있습니다.

```sh
uv sync --extra master
uv run --extra master python tools/build_master_packs.py --master-dir ../ipr-master-diff --schema data/protocol/idolypride-6.1.1.pb --output data/rebuilt-master
```

현재 JSON으로 202개 테이블·238,940개 행·78,475,264바이트를 생성했고 전체 테이블의 복호화·역직렬화 round trip을 검증했습니다. 재구성 팩은 원본과 다른 로컬 키·버전을 사용하며 실제 클라이언트 소비는 아직 검증하지 않았습니다. 원본과 재구성 결과는 각각 다른 디렉터리에 보관합니다.

서버에는 `MasterTag` 객체의 JSON과 일치하는 암호화 팩이 필요합니다. 일반 JSON 테이블을 파일 서버에 직접 올리는 것으로 대체할 수는 없습니다.

```text
data/original-master/
  master-tag.json
  assets/
    master/
      <MasterTag의 fileName과 동일한 원본 파일>
```

```sh
uv run idoly-local serve \
  --profile sandbox \
  --bind 0.0.0.0:50051 \
  --master-tag data/original-master/master-tag.json \
  --asset-root data/original-master/assets \
  --asset-host 0.0.0.0 \
  --asset-port 8080 \
  --asset-base-url http://192.168.0.10:8080
```

예시 IP는 서버 PC의 실제 LAN 주소로 바꿉니다. `--asset-base-url`은 게임 기기에서 접근 가능한 origin이어야 합니다. 서버는 파일명·크기·경로를 검증하고 다운로드 URL만 `/master/<fileName>`으로 바꿉니다. 버전, 암호화 키, 팩 바이트는 유지합니다. HTTP 서버는 `GET`·`HEAD`·단일 byte range를 지원하며 누락 파일을 자동 다운로드하지 않습니다.

gRPC TLS는 `--tls-cert`와 `--tls-key`를 함께 지정하면 사용할 수 있습니다. 배포 연결용 클라이언트는 같은 기기의 HTTP/2 cleartext 주소를 사용합니다. 별도 HTTPS 서버에는 해당 주소와 인증서 신뢰 설정이 필요합니다.

## 보존 우선순위

1. 사용 중인 Android·iOS 클라이언트와 해시, 버전별 protobuf descriptor를 보존합니다.
2. 원본 MasterTag 응답, 버전별 암호화 MasterDB 팩, Octo manifest와 실제 CDN 파일을 함께 보존합니다.
3. 서비스 이용이 가능한 동안 본인 계정의 부팅·홈·라이브·스토리 응답을 수집하고, 인증 토큰을 fixture에서 제외합니다.
4. 배포한 Android·PlayCover 연결용 클라이언트로 실제 로그인·홈 진입을 검증하고 누락된 요청을 확인합니다.
5. 홈·튜토리얼 상태 보존을 바탕으로 전투·보상 등 게임 로직을 구현합니다.

확인한 Octo revision 1087에는 AssetBundle 49,370개와 resource 5,072개가 있으며 원본 합계는 **39,322,868,160바이트**입니다. 현재 manifest 보존은 완료됐지만 실제 CDN 파일 전체 보존을 뜻하지 않습니다. 분석 환경의 남은 공간 약 30GB보다 크므로 전체 보존에는 추가 공간이 필요합니다.

## 참고 저장소

| 저장소 | 역할 |
| --- | --- |
| [IdolyPride_client](https://github.com/tagundo/IdolyPride_client/releases) | 분석 대상 Android·iOS 릴리스 |
| [SolisClient](https://github.com/vilebbit/SolisClient) | 공개 gRPC·protobuf·envelope 참고 구현 |
| [elichika](https://github.com/tagundo/elichika) | SIFAS 로컬 서버 구조 참고; 게임 프로토콜은 다름 |
| [HoshimiToolkit](https://github.com/tagundo/HoshimiToolkit) | Octo·MasterDB·리소스 보존 도구 |
| [Hoshimi-localify](https://github.com/tagundo/Hoshimi-localify), [iOS 구현](https://github.com/tagundo/hoshimi-localify-ios), [ipr-patcher](https://github.com/tagundo/ipr-patcher) | 플랫폼별 훅·번역·클라이언트 패키징 참고 |
| [ipr-master-diff](https://github.com/tagundo/ipr-master-diff), [ipr-adv-txts](https://github.com/tagundo/ipr-adv-txts) | 마스터 JSON 변경 이력·원문 스토리 |
| [hoshimi-station](https://github.com/tagundo/hoshimi-station), [번역 데이터](https://github.com/tagundo/ipr-translation-data-ko) | 번역 편집·출력 데이터 |
| [idoly-musics](https://github.com/tagundo/idoly-musics) | 음악 메타데이터 참고 |
| [mitmproxy](https://github.com/mitmproxy/mitmproxy), [jadx](https://github.com/skylot/jadx), [REA](https://github.com/morluto/rea) | 통신·APK·네이티브 분석 도구 |

elichika에서는 요청별 상태 처리, SQLite 영속성, 메모리 마스터 조회와 로컬 파일 제공 구조를 참고했습니다. SIFAS의 인증·암호화·게임 규칙을 그대로 사용하지 않고 아이돌리 프라이드 6.1.1의 protobuf·envelope·세션에 맞춰 별도로 구현했습니다. 기존 참고 저장소는 수정하지 않았습니다. 전송 형식과 확인 범위는 [프로토콜 메모](docs/protocol.md)에 정리했습니다.

## 검증·라이선스

```sh
uv run pytest
```

테스트는 암호화 호환성, 실제 localhost gRPC, 세션 영속성, fixture 검증, 로컬 파일 전송을 다룹니다. SolisClient 호환성 테스트는 해당 체크아웃이 있을 때 실행합니다. 테스트 통과는 게임 기기에서의 동작 확인과 구분합니다.

서버 코드는 [AGPL-3.0-or-later](LICENSE)입니다. 공개 프로토콜 참고 구현은 SolisClient에 출처를 두며, 게임 클라이언트·리소스는 저장소에 포함하지 않습니다.
