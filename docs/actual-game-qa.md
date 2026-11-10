# 실제 Android 게임 자동 점검

개발용 [Debug actual Android game boot](https://github.com/tagundo/IdolyPride_client/actions/workflows/debug-game-android.yml)는 일회용 에뮬레이터에서 현재 서버 앱과 실제 6.1.1 게임을 함께 실행합니다. 화면·UI 트리·일반 터치 입력·서버 요청을 남겨 다음 미구현 기능을 찾는 작업입니다.

## 실행과 입력

API35 `google_apis;x86_64`의 ARM64 변환 환경에서 고정 해시를 확인한 공개 진단 게임의 별도 복사본을 실행합니다. Lavapipe·소프트웨어 AES·스토어 없는 초기화·GLES3와 QA UI 브리지를 사용하며 일반 배포 게임은 바꾸지 않습니다. 결제 초기화 등에서 실제 기기와 동작 차이가 남을 수 있습니다.

수동 실행의 `display_size`는 기본 `1080x2280` 또는 부하 비교용 `540x1140`을 선택합니다. 각각 density 440/220으로 같은 dp 비율을 유지하고 실제 크기를 자료에 기록합니다. 렌더링 부하를 줄이는 실험이며, 성능이나 입력 개선은 실제 Unity 화면 크기·프레임 관측과 대조해야 합니다.

튜토리얼 완료 프로필은 알려진 로컬 RPC로 준비하고 `profile-fixture.json`에 별도 기록합니다. 이 준비 과정은 게임으로 튜토리얼을 플레이한 증거에 포함하지 않습니다.

드라이버는 새 Unity UI 트리의 버튼 ID·경로·좌표를 다시 확인하고 현재 Android 게임 뷰·화면 크기와 맞춘 뒤 일반 ADB 터치를 보냅니다. 브리지는 버튼 delegate를 직접 실행하지 않습니다. 메뉴 탐색 중 gameplay RPC도 주입하지 않습니다.

현재 대상은 레슨·라이브·아이돌·업무·스토리·선물 메뉴입니다. 알려진 타이틀 콜백 미등록·입력 해제 중·콘텐츠 차단 상태에서는 입력을 기다립니다. 관측할 수 없는 값은 `null`과 `unavailable`에 남기며, interceptor 존재 자체는 차단으로 단정하지 않습니다. 시작 상태를 관측하기 위해 게임·SDK 생성자나 싱글턴 생성을 추가하지 않습니다.

Android 전체화면 안내는 정확한 시스템 UI 식별자·버튼 상태·현재 화면 범위를 확인하고, 입력 직전 다시 조회한 트리가 일치할 때만 닫습니다. 시스템 안내 입력은 게임 입력과 별도로 기록하며 같은 프레임에 게임을 누르지 않습니다. 활성 `GlobalDialog`나 매니저 레벨업 안내가 있으면 그 뒤의 메뉴 입력·메뉴 결과 판정·앱 재시작을 막습니다. 알려진 공지 X도 전체 창의 문맥을 다시 확인합니다. 확인한 매니저2→3 안내의 X를 먼저 누르고, 다음 새 UI에서 안내가 사라지고 레슨 보상 창의 닫기가 활성화됐을 때만 그 창을 닫습니다. 촉진 버튼은 선택하지 않으며, 해결되지 않는 창이 반복되면 조기에 관측을 끝냅니다.

## 결과 파일

| 파일 | 내용 |
| --- | --- |
| `result.json` | 실제 게임 실행·촬영·입력 횟수와 프로필 준비 기록 |
| `ui-exploration.json` | 입력·메뉴별 관측 결과·조회 오류·타이틀 대기 원인 |
| `unity-ui-*.json` | 시각별 버튼·렌더링된 텍스트·시작 상태 |
| `ui-action-*.unity.json/.xml/.png` | 입력 직전 Unity·Android 트리와 화면 |
| `game-*.png/.xml` | 입력 사이의 게임 화면·Android 트리 |
| `system-dialog-*.json/.xml/.png` | 알려진 Android 안내 입력 전 재검증·입력 후 화면과 별도 처리 기록 |
| `environment-preflight/` | 같은 AVD의 CPU·GLES 합성 검사, 실제 루트 지원과 변환기 해시 |
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


## 루트 지원과 개선한 검사 환경

루트 권한은 내부 저장 데이터·시스템 로그·통신 분석에 유용하지만, ARM 변환기와 그래픽 한도의 오류를 없애 주지는 않습니다. MuMu의 [Mac 개발자 문서](https://www.mumuplayer.com/help/mac/developer-support-function.html)는 루트 설정 `vmRootEnable`을, [Windows MuMu12 개발자 문서](https://mumu.163.com/help/20240807/40912_1170006.html)는 `root_permission`을 안내합니다. 현재 Windows6.x/Android15의 내장 루트는 이 조사에서 직접 확인하지 않았습니다. 공식 Android15의 Magisk 미지원 안내를 내장 루트 미지원으로 해석하지 않습니다.

현재 Linux 실행기에 MuMu를 설치해 실행했다는 주장은 하지 않습니다. [별도 환경 검사](https://github.com/tagundo/IdolyPride_client/actions/runs/42785150482)의 API35·Lavapipe 구성은 실제 `adb root`와 `whoami=root`, 원본 실패 명령 `FCVTZS S1,S1`의 양·음수 절삭, vertex/fragment 각300개 vec4 uniform의 실제 컴파일·링크·활성 배열 크기 검사를 통과했습니다. 게임·계정 정보가 없는 ARM64 전용 합성 APK로 확인했습니다. 기본 `-gpu host` 구성의 결과와 구분합니다.

성공 구성은 emulator37.2.13(build16740729), Android35 image12960925, native bridge SHA256 `9b5808354a85d722a290ae879400b909aa961955e80ea1a7e807aea9416d92f9`, `-gpu lavapipe`입니다. 렌더러는 ANGLE의 Mesa Vulkan llvmpipe, GLES3.1이며 두 uniform 한도는 각각4096입니다. Xvfb와 Mesa·`libpulse0`, `LIBGL_ALWAYS_SOFTWARE=1`, `GALLIUM_DRIVER=llvmpipe`를 사용합니다. 게임 검사도 시작 전에 같은 합성 검사를 다시 통과해야 진행하며, 성공한 합성 검사 자체를 홈·메뉴 플레이 검증으로 취급하지 않습니다.

## API35 실제 게임에서 확인한 범위

[실행42785951638](https://github.com/tagundo/IdolyPride_client/actions/runs/42785951638)은 게임 PID가 1800초 동안 유지됐지만 Android의 `Viewing full screen / Got it` 안내가 남았습니다. 게임 입력은 0회였고 실제 요청은 `System.Check/Refund.GetTerm`뿐입니다. 이 실행은 홈·메뉴 검증 자료가 아닙니다.

[실행42793871383](https://github.com/tagundo/IdolyPride_client/actions/runs/42793871383)은 시스템 안내를 닫고 실제 타이틀 입력·1.07GB 다운로드 확인·다운로드 화면을 거쳐 `Auth.Login/Master.Get/User.Get/Home.Login/Home.Enter/Notice.List → OK`까지 진행했습니다. 그러나 `INFORMATION` 공지 창이 홈을 덮었습니다. 그 뒤의 레슨·라이브·아이돌·업무 버튼 입력과 트리 변화 기록은 메뉴 검증으로 사용할 수 없습니다. 스토리·선물은 시도하지 않았으며, 해당 메뉴의 요청도 관측하지 못했습니다.

[실행42801877846](https://github.com/tagundo/IdolyPride_client/actions/runs/42801877846), 소스 `6c856f8`은 공지 창의 정확한 X 버튼을 새 Unity·Android 트리로 확인하고 일반 입력을 두 번 보냈습니다. 창이 남아 `global_dialog_not_dismissed`로 조기에 끝냈으며, 메뉴 입력·결과는 0개입니다. 게임 입력 7회는 타이틀 4회·다운로드 확인 1회·공지 X 2회이고, Android 안내 처리 1회는 별도입니다. 명령이 전송됐다는 기록은 Unity 클릭 콜백 실행을 보장하지 않습니다.

이 실행은 동일한 API35 사전검사를 통과했고 게임 PID4433도 종료되지 않았습니다. 관측한 게임 로그에 새 관리 예외·`SIGILL`·GLSL 링크 오류는 없었습니다. 실제 게임에서 `Home.Login/Enter/Notice.List`가 성공했지만, 공지 창에 가리지 않은 홈 3D 모델과 메뉴 화면은 아직 검증하지 못했습니다. `UNIMPLEMENTED`가 없었던 것도 메뉴 기능이 모두 구현됐다는 뜻은 아닙니다. 초기 준비용 RPC 31회와 서버 준비 확인은 실제 게임 요청에서 분리합니다.

[실행42808761261](https://github.com/tagundo/IdolyPride_client/actions/runs/42808761261)은 축소 화면 설정용 여러 줄 셸 명령의 구문 오류로 게임 실행 전에 종료됐습니다. 사전검사 통과와 새 관측기 런타임 검증을 혼동하지 않습니다. 각 줄을 독립 실행하는 도구에 맞춰 설정 명령을 수정한 뒤 다음 실행을 진행했습니다.

[실행42810660579](https://github.com/tagundo/IdolyPride_client/actions/runs/42810660579), 소스 `4c2315a`는 같은 API35·Lavapipe 사전검사를 통과하고 `540x1140`, density220, 일반 입력 유지150ms로 실행했습니다. Android 전체화면 안내 처리 1회와 게임 입력 7회(타이틀3·다운로드 확인1·공지 X2·레슨1)를 구분해 기록했습니다. 프레임29의 공지가 사라진 화면과 새 UI 트리에서 **홈의 배경·중앙 3D 캐릭터·정상 홈 버튼**을 함께 확인했습니다. 축소 화면이 개선의 원인이라고 단정하지 않으며, 프레임27→29의 평균 처리 속도도 약1.7~1.8FPS였습니다.

그 뒤 실제 레슨 버튼 입력으로 `Activity.ReceiveLessonReward → OK`, `Home.Enter → OK`가 발생했고, 수령 창의 골드60·매니저 경험치96·레슨 피스36 및 매니저2→3 안내를 확인했습니다. 레슨 보상 창의 닫기는 이 안내 아래에서 비활성 상태였습니다. 탐색기는 이를 알 수 없는 겹친 창으로 처리해 프레임32에서 조기에 종료했으며, 기록한 메뉴 결과는 0개입니다. 레벨업 안내와 보상 창을 닫는 새 순서의 실제 실행, 나머지 다섯 메뉴, 일반 라이브 재생·결과 화면은 아직 검증하지 않았습니다.

이 관측 구간의 게임 PID4518은 유지됐고, 크래시 버퍼와 관리 예외·`SIGILL`·GLSL 링크 오류는 없었습니다. 초기 준비용 RPC 31회는 실제 게임 요청에서 제외했으며, 이 실행에서 새 `UNIMPLEMENTED`는 관측하지 못했습니다. 아직 누르지 않은 메뉴의 구현 여부를 이 결과로 판단하지 않습니다.

현재 메뉴 탐색기는 메뉴 입력 뒤 트리 변화를 기록하는 범위이며, 일반 퀘스트 선택·시작·재생·결과 화면까지 진행하지 않습니다. [첫 메인 라이브 실험 기능](first-live-support.md)의 엔진·API 검사는 이 실제 게임 기록과 별개이며, 일반 라이브의 실제 화면 재생을 증명하지 않습니다.
