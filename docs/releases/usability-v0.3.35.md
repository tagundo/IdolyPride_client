# v0.3.35 설정 화면·ZIP 가져오기와 다국어 클라이언트

2026-11-15 · [릴리즈](https://github.com/tagundo/IdolyPride_client/releases/tag/local-server-v0.3.35) · [Actions](https://github.com/tagundo/IdolyPride_client/actions/runs/43753600993)

- 빌드 소스: `ce5b3551a059544a8b7ac3a985b577cc1f338c2e`
- 게시 커밋: `6f1531033b3085ed5b0357261b6e09cf51c3293a`
- Android·Mac 서버: 0.3.35 / build 52; 통합 IPA: 156.9115

## 변경 내용

- Android 서버의 게임 실행 버튼을 상단 하나로 정리하고 진단·서버 로그를 JSON 하나로 내보냅니다. 밝은 카드와 16sp 글자를 사용하며 그래픽·촬영 설정은 처음부터 펼쳐집니다.
- 통합 IPA의 게임 옵션·그래픽/촬영·재생·미디어 설정은 자동 저장합니다. 숫자 입력은 600ms 대기 또는 입력 완료 뒤 저장하며, 실패 시 재시도합니다. 게임 시작은 최신 설정 저장이 완료된 뒤 진행합니다.
- iOS ZIP 가져오기는 사본 모드로 선택한 파일을 복사하고 준비·복사 용량/진행률·검증/보관 단계를 표시합니다. 검증된 같은 보관 폴더의 경로 별칭을 처리하며 파일·폴더 링크와 소유 검사는 유지합니다.
- 설정 창들은 메모리 전용 WebKit 저장소를 재사용하고, 각 창과 JavaScript 문서는 새로 생성합니다. 디스크 영구 저장으로 전환하지 않습니다.
- 세 명 편성에서 1인 포즈를 선택할 때 회색 대기 두 명을 촬영 정원에서 제외합니다. 전체 명단의 보유·의상/헤어 호환 검사는 유지합니다.

기존 v0.3.34의 프로필·카드·포토 편집과 목록 읽기 복구도 포함합니다. [이전 복구 범위](recovery-v0.3.34.md). 개별 Enumerable.Where 예외의 원인이나 NPC의 MV 출연을 이번 변경으로 해결했다고 주장하지 않습니다.

## 설치와 리소스 ZIP

Android는 서버 APK와 한국어·일본어·영어 게임 APK 중 하나를 사용합니다. 게임 세 언어판은 같은 앱 ID와 versionCode 414의 교체 업데이트이며 서버의 게임 언어와 맞춥니다. 한국어 게임 APK와 별도 PlayCover IPA는 검증된 v0.3.31 파일을 그대로 재사용합니다.

iPhone·iPad는 개인 서명한 통합 IPA 하나에서 언어를 선택합니다. 게임 시작 뒤 바꾼 게임 언어는 완전히 종료·재실행하면 적용됩니다. 번역 자료가 없는 문구·이미지는 원본을 유지합니다. Mac은 통합 IPA 또는 별도 Mac 서버와 한국어 PlayCover IPA 구성을 선택하며 같은 포트의 다른 서버는 종료합니다.

같은 앱 위에 업데이트하면 기존 계정·설정·보관 파일을 유지합니다. 다른 설치 도구나 컨테이너 사이의 자동 계정 이전은 뜻하지 않습니다. 설치된 앱의 서버 메뉴에서 리소스 ZIP을 내보내며, ZIP에는 기기에 보관한 리소스만 포함되고 계정 저장은 포함되지 않습니다. 대상 앱에서 ZIP 가져오기 완료 후 게임을 시작합니다. ZIP에 없던 파일은 자동 받기와 인터넷 연결이 필요합니다. LiveContainer에서 ZIP 선택이 막히면 개별 앱의 Fix File Picker를 켭니다.

## 검증 범위

- 최종 소스의 회귀 7,654개·하위 375개 통과, 환경별 165개 생략. 실제 원본 마스터 필수 검사 3개는 생략 없이 통과했습니다.
- Android ARM64 배포 APK의 서명·정렬, x86_64 에뮬레이터의 실제 서버 UI·암호화 RPC·업데이트/재시작 보존을 검사했습니다. JA/EN 게임 APK는 서명·16KiB 정렬·내장 UI·폰트·멤버 목록·같은 업데이트 식별자를 검사했습니다.
- 실제 ARM64 Mac 앱을 다른 위치로 옮겨 시작·중지·엔진 통신과 엄격한 서명을 검사했습니다.
- Apple SDK 빌드와 같은 Simulator 컨테이너의 KO→EN→JA→EN→KO 다섯 재실행이 통과했습니다. 실제 저장 요청/응답 ID·폼 완료 상태·독립 서버 저장값과 실행 언어, 캐시 재사용·새 문서·비영구 WebKit 저장소·게임 시작 대기를 검사했습니다.
- Simulator ZIP 원본과 사본은 각각 5,842,291바이트이며 전체 SHA-256이 일치했습니다. 가져오기 완료·버튼 복구·실패 파일 0개를 확인했습니다. 카탈로그만 포함한 ZIP이며 실제 리소스 오브젝트는 0개입니다. 실제 Files 행 탭 대신 공개 picker delegate callback을 사용했습니다.
- 원본 Actions ZIP 전체 API SHA, 게시 세 파일의 LFS 전체 재다운로드 SHA, 7개 Release Assets 각각의 전체 API 다운로드 SHA·파일 목록을 검사했습니다. 별도로 작은 증거 ZIP의 전체 SHA와 내부 보고서 41개, 인증 없는 7개 다운로드의 HTTP 206·64바이트·전체 크기·ZIP 접두를 다시 확인했습니다.

Simulator는 검사용 Unity 진입점과 실제 서버를 사용합니다. 실제 Android ARM64 게임, PlayCover·iPhone·iPad 게임 및 LiveContainer·SideStore의 파일 선택·대용량 리소스 복원은 이번 자동 검증 범위에 포함되지 않습니다. 기존 공통 최적화의 동일 입력 비교는 유지했으며 게임 FPS 향상을 측정한 릴리즈는 아닙니다.

## 다운로드와 SHA-256

| 파일 | 크기 (bytes) | SHA-256 |
| --- | ---: | --- |
| [IdolyPride-Local-Server-Android.apk](https://github.com/tagundo/IdolyPride_client/releases/download/local-server-v0.3.35/IdolyPride-Local-Server-Android.apk) | 332,303,435 | `0e46e8fa9c3b8217ca255354d8910441a981c476b760e8eda04436efcfc0ba5f` |
| [IdolyPride-Local-Server-macOS-arm64.app.zip](https://github.com/tagundo/IdolyPride_client/releases/download/local-server-v0.3.35/IdolyPride-Local-Server-macOS-arm64.app.zip) | 331,119,630 | `cffbdf5d4c54dd7ffa9962e7ab6ef027e90ae3dcb8a9cea91afdaaddcf006be7` |
| [IdolyPride-6.1.1-Unified-iOS.ipa](https://github.com/tagundo/IdolyPride_client/releases/download/local-server-v0.3.35/IdolyPride-6.1.1-Unified-iOS.ipa) | 525,737,381 | `e9b40fdf699c5084cc1d429f6dec67c87ece5fba22a87cb867045f6294897893` |
| [IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ja.apk](https://github.com/tagundo/IdolyPride_client/releases/download/local-server-v0.3.35/IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ja.apk) | 164,276,861 | `3cffdcdf99b48eb5819b8639b3a31bfa43f4ae5cc1c092bb5dbd984a6c080543` |
| [IdolyPride-Local-Graphics-Diagnostic-Android-arm64-en.apk](https://github.com/tagundo/IdolyPride_client/releases/download/local-server-v0.3.35/IdolyPride-Local-Graphics-Diagnostic-Android-arm64-en.apk) | 164,260,477 | `2bd373fbee1435c45000088fbf7996cbea8d577bf6015085e8c1101d82130baf` |
| [IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk](https://github.com/tagundo/IdolyPride_client/releases/download/local-server-v0.3.35/IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk) | 165,128,829 | `44f233290128a97f78940e3167c9486dbe39550090efcb90f7dc403430e94b9e` |
| [IdolyPride-6.1.1-Local-PlayCover-ko.ipa](https://github.com/tagundo/IdolyPride_client/releases/download/local-server-v0.3.35/IdolyPride-6.1.1-Local-PlayCover-ko.ipa) | 150,132,823 | `d872903da8d79bf4a255888f9d5a952198ff47268cfcf7c35e8ac437b56e72a1` |

[게시·실제 저장값·검증 근거](usability-v0.3.35-evidence.json)
