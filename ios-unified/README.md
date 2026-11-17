# iPhone·iPad·Mac/PlayCover 통합 IPA

로컬 서버와 일본어·한국어·영어 게임 데이터를 **IPA 하나**에 넣습니다. [현재 공개판 2026.11.17.2 다운로드](https://github.com/tagundo/IdolyPride_client/releases/download/v2026.11.17.2/IdolyPride-2026.11.17.2-Unified-iOS.ipa)를 iPhone·iPad에서는 개인 서명해 설치하고, Apple Silicon Mac에서는 PlayCover로 설치합니다. 별도 Mac 서버 앱은 필요하지 않습니다.

## 실행하기

1. 이전 별도 서버를 사용했다면 완전히 종료합니다.
2. 앱을 열고 서버 메뉴에서 사용할 게임 언어를 선택합니다.
3. 서버 준비가 끝나면 상단의 **게임 시작**을 누릅니다. 시작에 실패하면 표시된 오류와 **다시 시도**를 확인합니다.

게임 중에는 화면 **오른쪽 위를 한 손가락으로 2초간 길게 눌러** 서버 메뉴를 엽니다. 인식 영역은 안전 영역 안의 128×128포인트입니다. Mac에서는 **로컬 서버 설정… / ⌘⇧,**도 사용할 수 있습니다.

**게임으로 돌아가기**는 메뉴만 닫고 서버를 유지합니다. 앱을 완전히 종료하면 게임과 서버가 함께 종료됩니다.

## 언어와 설정

| 설정 | 적용 시점 |
| --- | --- |
| 서버 화면 언어 | 선택 즉시 상단·상태·버튼·Mac 메뉴에 적용 |
| 게임 언어 | 게임 시작 전 선택은 바로 적용, 게임 진입 후 변경은 앱을 완전히 종료·재실행 |
| 그래픽·촬영·MV·미디어 목록 | 변경하면 자동 저장, 저장 실패 시 해당 항목에서 재시도 |

**게임 시작**은 남은 설정 저장이 끝난 뒤 진행합니다. 번역 자료가 없는 문구·이미지는 원본을 유지합니다. 그래픽·촬영은 펼친 상태로 제공하며 렌더 배율은 최대 2배, 버퍼는 최대 4096px까지 지원합니다.

## ZIP 옮기기

| 파일 | 포함 내용 | 사용할 메뉴 |
| --- | --- | --- |
| iOS 리소스 ZIP | 받은 모델·이미지·음성 등 게임 파일 | iOS 리소스 보관의 ZIP 내보내기·가져오기 |
| 계정 ZIP | 로컬 계정의 진행·보유 항목·게임 설정 | 유저 관리의 계정 ZIP 백업·가져오기 |

다른 설치 환경으로 옮길 때는 원래 앱에서 내보낸 ZIP을 대상 앱에서 가져옵니다. 리소스 가져오기의 준비·복사·검증 상태를 확인하고 **완료 후 게임 시작**을 누릅니다. 직접 압축을 풀 필요는 없습니다. ZIP에 없던 파일은 자동 받기와 인터넷 연결이 필요합니다.

LiveContainer에서 ZIP을 선택할 수 없으면 아이프라 개별 앱 설정의 **Fix File Picker**를 켜고 다시 실행합니다. Sideloadly·LiveContainer·SideStore의 저장소는 서로 자동 공유되지 않습니다. 계정 가져오기는 검사 결과와 덮어쓸 대상을 확인한 뒤 진행합니다. 자세한 내용은 [계정 안내](../docs/server-user-management.md)를 참고하세요.

## 업데이트와 오류 기록

같은 앱 컨테이너를 유지하는 방식으로 업데이트합니다. 계정·설정은 `Library/Application Support/IdolyPrideLocal`, 게임 리소스는 `Documents/IdolyPride`에 보관합니다. 앱 삭제 전에는 필요한 계정 ZIP과 리소스 ZIP을 각각 내보냅니다. 이전 별도 Mac 서버의 자료는 자동 이전하지 않습니다.

오류가 나면 앱을 종료하기 전에 서버 메뉴의 **진단 전체 복사**를 사용합니다. UTF-8 32KiB를 넘는 내용은 생략 표시와 함께 복사됩니다. [설치·문제 확인 안내](../docs/client-setup.md)에서 자세한 절차를 확인할 수 있습니다.

## 이번 릴리즈

이번 날짜 릴리즈의 내부 빌드는 `156.9117`입니다. 콘솔·서버·계정·콘텐츠·그래픽 분류, 가로 화면 대응, 접힌 도움말, 모시코이 목록 번역·다중 선택, 시작 준비 최적화와 한국어 이미지 비율 수정을 포함합니다. [전체 플랫폼 검증](https://github.com/tagundo/IdolyPride_client/actions/runs/44015901340)을 확인할 수 있습니다. [게시 파일 검증](https://github.com/tagundo/IdolyPride_client/actions/runs/44022899574)에서는 같은 빌드 파일 5개의 전체 SHA를 재확인했습니다.

## 빌드와 검증

[전체 플랫폼 릴리즈 workflow](../.github/workflows/release-all-platforms.yml)는 같은 소스의 서버·클라이언트 산출물과 필수 검증을 확인한 뒤 게시합니다. 빌드 절차는 [PACKAGING.md](PACKAGING.md), 경계와 원본 보존 조건은 [CONTRACT.md](CONTRACT.md), 과거 수정·자동 검증 기록은 [VALIDATION.md](VALIDATION.md)와 [기능별 기록](../docs/releases/)에 있습니다.

자동 검증에는 실제 Apple SDK 빌드, macOS Foundation·AppKit 검사, 새 iOS Simulator의 서버·설정 UI·언어 재실행·ZIP·계정 보존 검사가 포함됩니다. Simulator의 검사용 Unity 진입점은 실제 게임 공연을 실행하는 검사가 아닙니다. iPhone·iPad·PlayCover의 전체 게임·MV 재생·성능과 LiveContainer·SideStore의 실제 Files 공급자·대용량 복원은 별도 기기 검증 범위입니다. 검사용 Unity 코드는 배포 IPA에 넣지 않습니다.

GitHub Actions 없이 빌드하려면 전체 Xcode·iOS Simulator 런타임·Python 3.13·GitHub CLI와 여유 공간 8GiB를 준비한 Mac에서 `build_on_mac.command`를 사용합니다. 결과는 새 `~/Downloads/IdolyPride/builds/날짜-커밋/`에 생성하며 기존 게임·계정 폴더는 유지합니다.
