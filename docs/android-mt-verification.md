# Android MT 확인판 v0.3.17

이 확인판은 **멀티스레드를 요청한 설정과 게임이 실제로 선택한 모드를 구분**하기 위한 Android 서버·진단 클라이언트다. 연결된 실기기가 없어 여기서 활성화·안정성·속도 향상을 관측한 버전은 아니다. Mac 배포판은 v0.3.16을 유지한다.

## 비교 방법

1. 게임과 서버를 종료하고 확인판 서버 APK와 진단 클라이언트 APK를 각각 업데이트한다. 기존 앱·데이터를 삭제하지 않는다.
2. 서버의 **다중 스레드 렌더링 시작 실험**을 끈 상태로 먼저 실행한다. 기본값은 꺼짐이다.
3. Android 앱 정보에서 **아이프라 진단을 강제 종료**한 뒤 서버를 시작하고 **진단 게임 실행** 또는 **그래픽 지원 게임 실행**으로 연다. 일반 로컬 실행 버튼은 이전 리소스판을 열 수 있다.
4. 같은 라이브 촬영·360 LIVE 장면을 재생한 뒤 서버로 돌아와 **실제 측정**의 모드를 확인하고 **진단 기록 내보내기**로 보관한다.
5. 게임을 다시 강제 종료하고 실험 옵션을 켠 뒤 같은 버튼으로 새로 실행한다. 같은 장면·품질·해상도·FPS 설정으로 재현한다.
6. 실제 값이 **MultiThreaded (2 · 다중 스레드)**로 바뀌는지 확인한다. Direct(0)·SingleThreaded(1)이면 적용된 것으로 판단하지 않는다. 3·4·5는 Graphics Jobs를 포함한 다른 모드이므로 별도로 구분한다.

실행 중인 게임으로 다시 돌아가는 것만으로는 엔진이 재시작되지 않는다. 옵션을 켰는데 0·1이 관측되면 게임을 완전히 종료했는지 확인하고, 계속 같으면 요청이 적용되지 않은 결과로 보관한다. 원복은 옵션을 끄고 게임을 강제 종료한 뒤 새로 실행한다. 이 확인판은 `boot.config`를 수정하지 않으므로 원복에 별도 클라이언트 재설치는 필요 없다.

## 표시와 진단 기록

서버 화면의 **요청**은 다음 실행에 전달할 옵션이다. **실제 측정**은 게임의 원본 `SystemInfo.renderingThreadingMode`를 읽은 값이다. 요청 체크박스가 켜졌다는 이유로 적용 완료를 표시하지 않는다. 일치하지 않는 기존 렌더링 강제 인수가 있으면 덮어쓰지 않고 실행 전에 안내한다.

게임은 검증된 Unity 콜백 뒤에서 약 2초마다 실제 모드·그래픽 API·그 콜백의 Linux TID를 읽는다. TID는 그래픽 worker의 ID를 의미하지 않는다. Java 네트워크 스레드는 Unity 함수를 호출하지 않고 저장된 관측만 보낸다. 모드 관측이 오래되거나 게임을 멈춘 경우 최신 적용 상태로 표시하지 않는다.

진단 JSON의 `runtime.render_probe.client.actual_mode`와 같은 객체의 `graphics_api`, `observations`, `sample_age_ms`에서 값을 확인할 수 있다. 게임을 멈추거나 서버 앱으로 전환하면 관측이 오래될 수 있으므로, 화면이 대기로 바뀌어도 직전 관측은 진단 기록에 남는다. `runtime.render_probe.stale`과 수신 후 경과 시간은 그 관측의 최신 여부를 별도로 설명한다.

**CPU·GPU 프레임 시간은 이 판에서 측정하지 않는다.** 원본 FrameTiming은 지연된 결과를 내며, 현재 배열의 유효 개수·새 타임스탬프·시계 관계를 실행 중에 확인하지 못했다. `cpu_frame_ms`·`gpu_frame_ms`·`timing_age_ms`는 null로 유지한다. 0ms·0 FPS로 바꾸거나 체크박스 상태로 속도 향상을 추정하지 않는다. 실제 표시 간격을 측정할 ADB 기기가 있으면 [기존 실기기 측정 도구](mv-performance-audit.md#android-실기기-표시-간격-수집)를 사용할 수 있다.

## 개발 계약

`POST /client/render-probe`는 UTF-8 8192바이트 미만의 정확한 10개 필드를 받는다. 기존 그래픽·회전 설정 API는 바꾸지 않는다.

| 필드 | 범위 |
| --- | --- |
| schema | 정수 1 |
| state | waiting / observed / unsupported / init_failed |
| actual_mode | null 또는 정수 0~5 |
| graphics_api | null 또는 원본 API 정수 0~255; Android Vulkan은 21, GLES3는 11 |
| callback_tid | null 또는 양수 signed 32-bit Linux TID |
| observations | 0~INT64_MAX; 포화 후 더 늘리지 않음 |
| sample_age_ms | null 또는 마지막 모드 관측 후 monotonic 경과 ms |
| cpu_frame_ms / gpu_frame_ms | null 또는 유한한 양수 60000 이하; 현재 producer는 항상 null |
| timing_age_ms | null 또는 timing 관측 후 경과 ms; 현재 producer는 항상 null |

waiting·init_failed는 관측 수 0과 나머지 nullable 필드 null을 사용한다. observed는 양수 관측 수와 유효한 모드·API·TID·관측 age를 요구한다. unsupported는 양수 관측 수를 가질 수 있지만 모드는 null이다.

`GET /client/render-probe`와 Runtime 진단은 `{client, age_seconds, stale}`를 반환한다. 서버는 자기 monotonic 수신 시간과 클라이언트 관측 age를 합해 10초 이상 지난 관측을 오래된 것으로 취급한다. 같은 관측 번호·모드·API·TID의 재전송이 관측 시간을 새로 만들지 않는다. 프로세스 재시작으로 관측 번호가 낮아지는 경우는 허용한다. 이 상태는 메모리에만 보관하며 계정 DB·파일에 쓰지 않는다.

기존 APK 설치 권한과 내장 APK는 복구하지 않았다. 시작 옵션은 알려진 로컬 게임에 고정된 `-force-gfx-mt`만 전달하며 임의의 쉘 명령을 실행하지 않는다. 기존 엔진의 모드 값을 쓰거나 getter 결과를 강제로 2로 바꾸는 코드는 없다.

원본 근거는 [멀티스레드 렌더링 조사](android-multithreading.md)를 참고한다. 호스트·서명·파일 보존 검사는 실기기에서 mode 2가 관측됐다는 결과와 구분한다.
