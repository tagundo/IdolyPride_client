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

[실행42764587884](https://github.com/tagundo/IdolyPride_client/actions/runs/42764587884)은 실제 다운로드 확인·다운로드 UI와 게임에서 발생한 `Home.Login/Enter → OK`까지 진행했습니다. 이후 촬영은 계속 전체 로딩 화면이었고 `content_blocking=true`였습니다. 이 실행의 메뉴 결과는 로딩 아래의 UI를 선택한 탐색기 오류 때문에 메뉴 완료 검증에 사용할 수 없습니다. 앱 재시작 사이의 홈 연속 관측은 각각 약40·120·80초였으므로 장시간 정지로 단정하지 않습니다. 다음 탐색기는 차단 상태에서 메뉴 입력·결과 판정·재시작을 모두 기다리도록 수정합니다.

## 연속 관측 중 확인한 에뮬레이터 제약

[실행42772231854](https://github.com/tagundo/IdolyPride_client/actions/runs/42772231854)은 로딩 중 메뉴 입력·재시작 없이 연속 관측했습니다. `Home.Login/Enter → OK` 이후 `home_scene_loading=false`, `home_enter_called=true`였지만 `content_blocking=true`와 전체 로딩 화면이 유지됐습니다. 자료 수집 워크플로 성공은 **홈 화면·메뉴 검증 성공을 뜻하지 않습니다**. `shader_warmup_ended=true`도 정리 단계의 플래그이며 셰이더 링크 성공을 보장하지 않습니다.

게임 PID5060의 로그에는 07:23:05~07:27:47 UTC에 `Environment/Default` GLSL 링크 오류가 550회 기록됐습니다. SwiftShader의 vertex uniform 한도256 초과251회, fragment uniform 한도261 초과299회입니다. 이어 07:27:48에 ARM 변환기가 원본 `lib_burst_generated.so+0x2fff0`의 `FCVTZS S1,S1`을 지원하지 못해 UnityMain이 `SIGILL`로 종료됐습니다. 원본 라이브러리의 해당 명령 바이트와 크래시 로그를 대조했습니다. 셰이더 오류와 명령 변환 실패는 별도 환경 제약으로 기록하며, 셰이더 오류가 종료를 일으켰다고 단정하지 않습니다.

프레임59부터 게임 PID와 UI 브리지 리스너가 함께 사라지고 서버 앱이 전면에 나타났습니다. 이후의 `bridge_snapshot_unavailable`는 정상 30분 세션 만료가 아니며, 이 실행은 홈·메뉴 검증 미완료로 남깁니다. 종료 지점에 미구현 RPC나 OOM 증거는 없고, `purchase_initialized=false`만으로 원인을 판단하지 않습니다. 드라이버는 수집 오류 없이 **3회 연속 게임 PID가 없으면** `game_process_exited`를 기록하고 관측을 중단하도록 보강했습니다. 이 조사로 일반 배포 게임이나 서버 동작을 우회하는 패치는 추가하지 않았습니다.
