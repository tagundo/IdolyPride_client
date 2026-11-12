# Android 멀티스레드 렌더링 조사

2026-11-12, 일본판 6.1.1의 원본 Unity 2022.3.57f1 엔진과 같은 버전의 공식 Unity C# 소스를 대조했다. **원본 Android 엔진에 멀티스레드 렌더링 구현이 있으며, 기존 비활성화 설정보다 먼저 멀티스레드 모드를 선택하는 시작 옵션도 확인했다.** Unity 엔진을 새로 컴파일해야만 시도할 수 있는 상태는 아니다.

이 문서의 원본 조사는 배포 v0.3.16의 부팅 설정·클라이언트·서버 실행 옵션을 바꾸지 않고 수행했다. 후속 [Android MT 확인판 v0.3.17](android-mt-verification.md)은 기본 꺼짐의 시작 실험과 실제 모드 readback을 추가한다. 실제 휴대폰의 선택 모드·안정성·FPS를 측정한 결과는 아직 없다.

## 구현이 실제로 남아 있는가

원본 `libunity.so`의 장치 생성 함수는 모드 2·3·4에서 그래픽 worker 시작 함수로 진입한다. 이 함수가 `UnityGfxDeviceWorker`를 이름으로 지정하고, Thread 시작·pthread trampoline을 거쳐 실제 `pthread_create`와 렌더 작업 진입점으로 연결됨을 확인했다. 문자열 이름만 찾은 결과가 아니다.

따라서 `mobileMTRenderingBaked=false`만 보고 엔진에서 기능이 제거됐다고 판단할 수 없다. 원본의 `m_MTRendering`·`mobileMTRenderingBaked` 직렬화 필드는 확인했지만, 명시적 모드 선택 함수 밖의 모든 소비 경로를 추적한 것은 아니다. 이 값만으로 실행 중인 모드를 확정하지 않는다.

## 원본 엔진이 설정을 해석하는 방법

원본 모드 선택 함수 `0xc8cc90..0xc8cf5c`와 실제 모드 저장·장치 생성 경로를 추적했다. 아래는 Graphics Jobs 옵션과 별도 강제 jobs 인자를 사용하지 않는 조건이다.

| 입력 | 선택 함수의 결과 |
| --- | --- |
| 일반 실행, `gfx-disable-mt-rendering=1`, 강제 인자 없음 | `Direct(0)` |
| 일반 실행, 해당 키가 0이거나 없음 | Unity의 `processorCount > 1`이면 `MultiThreaded(2)`, 아니면 `Direct(0)` |
| `-force-gfx-mt`, 다른 force 인자 없음 | 비활성화 설정 검사보다 먼저 `MultiThreaded(2)` 반환 |
| `-force-gfx-direct`와 `-force-gfx-mt` 동시 지정 | `Direct(0)`; direct가 먼저 처리됨 |
| `-force-gfx-st`와 `-force-gfx-mt` 동시 지정 | `SingleThreaded(1)`; st가 먼저 처리됨 |

일반 실행은 `batchmode`·`automated`·테스트 실행 인자가 없는 경우를 뜻한다. 이 실행 상태를 검사하는 분기는 GPU 호환성 검사가 아니다. 기본 판정 함수도 원본 `SystemInfo.GetProcessorCount`와 같은 구현으로 연결됨을 확인했다. 강제 인자가 없고 배치·자동 테스트 실행에 해당하면 `SingleThreaded(1)`을 고르는 경로가 있다. 숫자 0은 실제 false로 해석된다. 반면 키에 빈 값만 주거나 값 없이 지정하면 true다. 따라서 `gfx-disable-mt-rendering=`는 비활성화를 해제하는 방법이 아니다.

`-force-gfx-mt`의 선택 결과가 2라는 것은 확인했지만, 실제 기기의 그래픽 장치 초기화·MV 재생이 성공한다는 실측은 아니다. 공식 공개 문서에 설명이 없는 내부 인자의 의미는 **해당 원본 바이너리에서 확인한 범위**로 한정한다. 다른 Unity 버전이나 다른 게임에 그대로 일반화하지 않는다.

원본 Android Activity의 DEX에서도 `unity` intent extra를 읽고 `updateUnityCommandLineArguments`를 거쳐 UnityPlayer를 만드는 순서를 확인했다. 이 메서드는 문자열을 그대로 반환하며, 실제 실행 Activity인 Firebase 하위 클래스도 이 경로를 사용한다. 클라이언트 엔진을 바꾸지 않고 시작 인자를 전달하는 실험 경로가 있다. 실행 중인 엔진의 모드를 바꾸는 API로 확인한 것은 아니므로, 적용 시험은 게임 프로세스를 완전히 종료한 뒤 새로 시작해야 한다.

## 무엇으로 활성화를 확인할 것인가

원본에 존재하는 `SystemInfo.renderingThreadingMode` getter를 확인했다. 이 함수는 장치 생성 함수와 같은 현재 모드 값을 읽으며 값은 다음과 같다.

| 값 | 이름 | 의미 |
| --- | --- | --- |
| 0 | Direct | 주 스레드에서 직접 그래픽 API 호출 |
| 1 | SingleThreaded | 단일 스레드로 MT 구조를 모사하는 내부 모드 |
| 2 | MultiThreaded | 별도 렌더 스레드가 low-level 그래픽 API 호출 |
| 3 | LegacyJobified | 여러 worker의 중간 명령을 렌더 스레드가 처리 |
| 4 | NativeGraphicsJobs | 렌더 스레드가 그래픽 jobs도 분배 |
| 5 | NativeGraphicsJobsWithoutRenderThread | 별도 렌더 스레드 없이 여러 worker에서 처리 |

**MT Rendering과 Graphics Jobs는 별개 설정이다.** 단순 MT 시험의 목표 값은 2다. 0이 아닌 값, worker 스레드의 존재, 설정 체크박스만으로 MT가 적용됐다고 표시하면 안 된다. 원래부터 존재하는 Java `UnityMain`도 그래픽 worker의 증거가 아니다.

원본 엔진에는 `GfxDevice: creating device client; threaded=%i; jobified=%i` 로그도 있다. 해당 경로에서 모드 2는 threaded=true/jobified=false다. 다만 로그가 안 보인다는 이유만으로 모드를 판단하지 않는다. 현재 모드 API와 같은 프로세스의 실제 worker 실행을 함께 확인한다.

## 게임·현재 패치와의 관계

원본에서 확인한 직접 getter 호출은 Unity 2D Animation의 `BufferManager.OnEnable`이다. 결과가 Direct가 아니면 double buffering을 사용하는 호환 분기이며, 멀티스레딩을 강제로 끄는 코드가 아니다. 직접 B/BL 조사만으로 모든 가상 호출·정적 링크 플러그인·렌더 경로를 확인한 것은 아니다. 제작사가 MT를 꺼 둔 이유를 설명하는 자료도 없다.

현재 브리지는 별도 그래픽 worker나 GLES/Vulkan submit 함수를 교체하지 않고 게임의 IL2CPP/URP 콜백을 감싼다. 첫 허용 콜백의 pthread를 기준으로 이후 작업을 제한하며, 다른 스레드에서는 추가 처리를 건너뛰는 경로가 있다. MT를 켠 상태에서도 해당 콜백·AA·그림자·사진 경로의 실제 thread가 어떻게 배치되는지 확인해야 한다. 스레드 검사를 삭제하는 것을 해결책으로 삼지 않는다.

## 다음 시험의 범위

1. 원본 실행과 MT 요청 실행을 분리한다. 한 방법은 `gfx-disable-mt-rendering`만 0으로 바꾼 클라이언트 시험판으로 원본의 배치·CPU 수 자동 판정을 유지하는 것이다. 다른 방법은 기존 APK에 `-force-gfx-mt` 시작 인자만 전달하는 것이다. 후자는 배치·CPU 수 자동 판정보다 먼저 모드 2를 강제하므로 두 방법을 구분한다. Graphics Jobs·해상도·품질·FPS·그래픽 API는 같이 바꾸지 않으며 충돌하는 direct/st 인자도 제거한다.
2. 각 실행에서 실제 모드·선택된 API·실제 RT 크기·콜백 thread를 읽는다. 화면에 ‘MT 요청’과 ‘실제 MultiThreaded(2) 확인’을 구분해 표시해야 한다.
3. 같은 MV를 예열한 뒤 같은 구간을 반복해 표시 간격과 CPU·GPU 작업/대기를 비교한다. [기존 측정 범위와 도구](mv-performance-audit.md)를 따른다. 소프트웨어 GPU 에뮬레이터의 FPS를 휴대폰 결과로 사용하지 않는다.
4. 시작·종료·회전·설정 전환·라이브 촬영·360 LIVE의 화면과 복원을 확인한다. 시작 인자 시험은 인자를 제거하고 새 프로세스로 실행해 원복한다. boot.config를 바꾼 시험판은 인자 제거만으로 돌아오지 않으므로, 기존 `gfx-disable-mt-rendering=1` 클라이언트로 같은 서명 업데이트한 뒤 새로 실행해야 한다. 앱 데이터 삭제는 원복 절차에 포함하지 않는다.

MT는 그래픽 API 처리의 스레드를 나누는 기능이며 게임 전체 로직을 자동 병렬화하지 않는다. 실제 병목이 그 작업에 있을 때 도움이 될 수 있다. 이번 조사만으로 속도 향상·충돌 없음·모든 플러그인의 호환성을 보장할 수는 없다.

## 증거

원본 `libunity.so`는 21,427,000바이트, SHA-256 `c36ea39e5040fbcd0577f7c49d08e149e2e7dc62449d90aadce761118a816c85`다. v0.3.16의 보존 검사에서도 같은 엔진·boot.config·PlayerSettings 자산 해시를 확인했다. 주요 함수·설정 우선순위·검증 한계는 [고정 증거 JSON](android-multithreading-evidence.json)에 기록한다.

공식 참고: [MT·Graphics Jobs 설정](https://docs.unity3d.com/2022.3/Documentation/Manual/class-PlayerSettingsAndroid.html), [실제 렌더 모드 API](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/SystemInfo-renderingThreadingMode.html), [모드 enum](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/Rendering.RenderingThreadingMode.html), [동일 엔진 버전 C# 소스](https://github.com/Unity-Technologies/UnityCsReference/tree/2343a015342bdb351e30a92c104ebc77ead0b94a).
