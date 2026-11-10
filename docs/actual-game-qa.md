# 실제 Android 게임 자동 점검

개발용 [Debug actual Android game boot](https://github.com/tagundo/IdolyPride_client/actions/workflows/debug-game-android.yml)는 일회용 에뮬레이터에서 현재 서버 앱과 실제 6.1.1 게임을 함께 실행합니다. 화면·UI 트리·일반 터치 입력·서버 요청을 남겨 다음 미구현 기능을 찾는 작업입니다.

## 실행과 입력

API30 ARM64 변환 환경에서 고정 해시를 확인한 공개 진단 게임의 별도 복사본을 실행합니다. 변환 환경용 소프트웨어 AES·스토어 없는 초기화·GLES3와 QA UI 브리지를 사용하며 일반 배포 게임은 바꾸지 않습니다. 결제 초기화 등에서 실제 기기와 동작 차이가 남을 수 있습니다.

튜토리얼 완료 프로필은 알려진 로컬 RPC로 준비하고 `profile-fixture.json`에 별도 기록합니다. 이 준비 과정은 게임으로 튜토리얼을 플레이한 증거에 포함하지 않습니다.

드라이버는 새 Unity UI 트리의 버튼 ID·경로·좌표를 다시 확인하고 현재 Android 게임 뷰·화면 크기와 맞춘 뒤 일반 ADB 터치를 보냅니다. 브리지는 버튼 delegate를 직접 실행하지 않습니다. 메뉴 탐색 중 gameplay RPC도 주입하지 않습니다.

현재 대상은 레슨·라이브·아이돌·업무·스토리·선물 메뉴입니다. 알려진 타이틀 콜백 미등록·입력 해제 중·콘텐츠 차단 상태에서는 입력을 기다립니다. 관측할 수 없는 값은 `null`과 `unavailable`에 남기며, interceptor 존재 자체는 차단으로 단정하지 않습니다. 시작 상태를 관측하기 위해 게임·SDK 생성자나 싱글턴 생성을 추가하지 않습니다.

## 결과 파일

| 파일 | 내용 |
| --- | --- |
| `result.json` | 실제 게임 실행·촬영·입력 횟수와 프로필 준비 기록 |
| `ui-exploration.json` | 입력·메뉴별 관측 결과·조회 오류·타이틀 대기 원인 |
| `unity-ui-*.json` | 시각별 버튼·렌더링된 텍스트·시작 상태 |
| `ui-action-*.unity.json/.xml/.png` | 입력 직전 Unity·Android 트리와 화면 |
| `game-*.png/.xml` | 입력 사이의 게임 화면·Android 트리 |
| `server-rpc-sequence.json` | 서버 UI의 요청·상태 순서; 앞부분의 프로필 준비 호출은 별도 기록과 대조 |
| `qa-aes-report.json`, `qa-ui-report.json` | 원본·변환 복사본의 해시와 변경 범위 |

작업의 완료 상태는 자료 수집 완료를 나타냅니다. 홈 진입은 게임에서 발생한 `Home.Login/Enter`, 화면과 UI 트리를 함께 확인합니다. 메뉴별 `different_ui_tree_observed`도 기능 전체의 성공 판정은 아니며 후속 화면과 요청을 검토합니다.

Android 서버 APK·Mac 앱의 별도 빌드 검사는 암호화 RPC와 재시작 후 저장 상태를 검사합니다. 실제 게임 메뉴 탐색의 화면 검증은 이 검사와 구분해 기록합니다.

## 확인한 초기 흐름

[실행42759541286](https://github.com/tagundo/IdolyPride_client/actions/runs/42759541286)에서 게임 초기화 성공·타이틀 버튼 콜백 등록과 두 차례의 실제 로그인 요청을 확인했습니다. 이후 원본 게임의 `SimpleActionSheet`에 **1.07GB 리소스 다운로드 확인**이 나타났습니다. 이 실행은 확인 창까지 진행했으며 홈 진입 자료는 포함하지 않습니다.

다음 드라이버는 새 UI 응답의 정확한 다운로드 제목·설명·버튼·단일 창을 다시 확인하고 일반 Android 입력으로 진행합니다. 알 수 없는 action sheet가 있으면 뒤의 타이틀을 누르지 않습니다. Unity 응답을 기다리는 시간과 응답 이후 UI 수집 시간을 따로 기록해 실제로 새로 반환된 트리를 과거 트리로 오인하지 않도록 했습니다.
