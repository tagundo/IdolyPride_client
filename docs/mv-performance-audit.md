# 라이브 촬영·360 LIVE 성능 조사

2026-11-12, 일본판 원본 6.1.1 Android APK·iOS IPA와 로컬 클라이언트 소스 `d67baadc491c386711650ac9cee2056b1ea6d3bc` 기준이다. 대상은 실시간 3D 공연이다. 사용자는 원본 Android에서도 전반적으로 iPhone 14 Pro보다 끊긴다고 보고했다.

**원본 Android에만 렌더링 멀티스레드를 비활성화하는 부팅 설정이 있다.** 우선 조사할 플랫폼 차이지만, 실제 기기의 렌더 스레드 상태·프레임 시간은 아직 측정하지 않았다. 따라서 이를 확정 원인이나 보장된 개선 방법으로 제시하지 않는다. 현재 ADB에 연결된 실기기는 없으며, 클라우드의 CPU 에뮬레이션·소프트웨어 GPU 결과로 휴대폰 성능을 대신하지 않았다.

## 원본에서 확인한 차이와 공통점

| 항목 | Android | iOS | 판단 범위 |
| --- | --- | --- | --- |
| Unity | 2022.3.57f1 | 2022.3.57f1 | 같은 엔진 버전 |
| `boot.config` | `gfx-disable-mt-rendering=1` | 해당 키 없음 | Android의 스레딩 정책 차이 후보 |
| `m_MTRendering` / `mobileMTRenderingBaked` | true / false | true / true | 실제 실행 스레드·설정 우선순위는 미측정 |
| 선언된 그래픽 API | Vulkan 우선, GLES3 대체 | Metal | Android에서 실제 선택된 API는 미확인 |
| 저장된 FPS 옵션 | 30 또는 60 | 30 또는 60 | Android에만 고정 30 제한이 있다는 증거 없음 |
| `gpuSkinning` | false | false | 공통 후보이며 실제 스키닝 경로는 미확인 |
| 품질별 최대 버퍼 크기 | 1024 / 1440 / 2160 / 4096 | 동일 | 현재 선택 품질과 실제 RT는 별도 확인 필요 |

GPU가 더 빠르더라도 CPU의 그리기 명령 준비·제출이나 프레임 간격 제어가 제한되면 화면이 덜 부드러울 수 있다. 다만 CPU 계산, GPU 처리, 대기, 발열에 따른 제한 중 무엇이 지배적인지 판별할 실측 자료는 없다. 멀티스레드 설정만 강제로 바꾸면 커스텀 렌더러·그래픽 백엔드와의 호환성 문제가 생길 수 있어 기본 클라이언트에는 적용하지 않았다.

품질 4단계의 비교 가능한 값은 같다. URP 설정 자산 4개도 검증한 객체 참조 7곳을 정규화하면 동일하고, 참조 대상 이름도 일치한다. 내장 `Live.unity`의 3D·UI 카메라는 각각 184바이트 전체가 같다. 이 결과는 내려받은 모든 무대, RendererData 본문, 컴파일된 셰이더까지 같다는 뜻은 아니다. 카메라의 HDR·MSAA 허용값만으로 실제 RT 포맷·샘플 수를 판단하지 않는다.

원본의 일반·360 촬영 기본 비율은 양쪽 모두 16:9다. 충분히 큰 가로 Unity 화면·High·배율 1·명시적 크기 덮어쓰기 없음 조건에서 원본 해상도 함수는 짝수 보정을 거쳐 **2160×1216**을 계산한다. 따라서 Fold의 물리 화면 픽셀이 많다는 사실만으로 원본 3D 렌더 부하가 더 크다고 단정할 수 없다.

iOS의 해상도 배율 0.5 특례는 `iPadAir4Gen`·`iPad10Gen`에 적용된다. 원본 enum의 `iPhone14Pro=74`는 조건 61·78에 해당하지 않는다. 이 특례로 비교 대상 iPhone의 부드러움을 설명할 수 없다.

## iOS·공통 최적화 후보

아래는 코드에서 확인한 작업이며 소요 시간이나 개선율은 아직 측정하지 않았다. 원본 Android에서 이미 있던 문제와 로컬 패치의 추가 비용을 구분한다.

| 우선순위 | 후보 | 확인할 사항 |
| --- | --- | --- |
| 1, 공통 | 사용자 그래픽 설정을 켰을 때 실제 렌더 해상도 증가 | `limited_hook`은 원본 제한을 우회한 뒤 사용자 제한을 적용한다. FPS만 바꾸려 설정을 켜도 원본과 같은 RT라고 보장할 수 없다. 동일한 실제 RT·품질·FPS로 비교한다. |
| 2, 공통 | 중복 카메라·화면 기하 검사 | 품질 Update, TargetImage LateUpdate와 렌즈 setter에서 같은 대상의 타입·Weak·투영·화면 검사가 반복될 수 있다. 안정된 타입·기하 계산을 재사용하고 상태 표시용 측정과 필수 검증을 분리할 여지가 있다. |
| 3, Mac/PlayCover | 360 LIVE 버튼의 중복 배치 계산 | 품질 Update·TargetImage LateUpdate·카메라 갱신에서 같은 UI 배치에 진입할 수 있다. 안정된 배치 1회에도 5개 대상의 position 읽기 15회와 좌표 변환 20회가 남는다. 실제 변경 시 갱신하거나 한 계산 안에서 공통 변환을 재사용할 후보가 있다. |
| 4, Android | 확장 투영 실패 뒤 RT 재생성 반복 가능성 | 일부 실패 복구는 Android에서 동일 revision·viewport 재시도 억제를 사용하지 않는다. 실제 반복 증거는 없으므로 실패·복구·RT 생성 횟수부터 센다. |
| 5, 원본 공통 | 동적 해상도 정책·셰이더 준비·스키닝 | 양쪽 동적 해상도 루프는 CPU 프레임 시간을 사용한다. GPU 시간·실제 배율과 대조한다. 첫 진입 셰이더 준비와 지속 재생을 나누고, 스키닝이 실제 상위 비용일 때 호환 리소스를 포함한 GPU 경로를 검토한다. |

버튼 가장자리 배치의 추가 계산은 desktop 실행을 확인한 경로에만 적용되므로 iPhone의 비용으로 일반화하지 않는다. 브리지의 네트워크 폴링은 별도 스레드에서 정상 상태 기준 약 2초 주기로 실행된다. 렌더 콜백이 매 프레임 HTTP 응답을 기다리는 구조는 아니다. 설정·상태 잠금 비용은 측정 대상이지만 네트워크 지연을 그대로 렌더 정지로 설명하면 안 된다.

캐시는 객체·장면·부모·렌즈 변경 때 무효화해야 한다. Unity 객체 생존 검사, 원본 LateUpdate 뒤 보정, UI 다시 켜기 버튼, 사용자 UI 선택과 종료 시 원복을 유지해야 한다. 위 표는 조사 시점의 후보이며, 아래의 작은 호출 중복 제거를 v0.3.16에 반영했다.

## v0.3.16에 반영한 호출 중복 제거

공통 RectTransform 확인은 한 번의 원본 콜백 이후 처리 안에서 같은 IL2CPP class의 성공한 상속 검사를 최대 4개까지 스택에 기억한다. 콜백 종료·중첩·예외 때 원래 범위로 돌아가며 프레임을 넘겨 보관하지 않는다. 객체 생존과 현재 class 조회는 매번 유지한다. 같은 class를 4회 검사하는 호스트 예제에서 상속 순회는 4회에서 1회로 줄지만, alive·class 조회는 각각 4회다. 실패·용량 초과는 원래 검사를 사용한다.

Mac/PlayCover의 360 UI 배치는 한 번의 갱신 안에서 공통 viewport 좌표만 재사용한다. 정상 경로의 Unity 좌표 변환은 20회에서 14회로 줄어든다. 각 대상의 부모 역변환·현재 위치 조회는 유지하며, 이전 배치 복원으로 viewport가 달라질 가능성이 있으면 즉시 다시 계산한다. 사용자 UI 선택과 마지막 작성자 기준의 원복도 유지한다.

이 변경은 반복되는 CPU 호출을 줄인다. Android 원본의 멀티스레드 플래그·GPU 스키닝·FPS·해상도 정책은 바꾸지 않았으며, **실기기의 FPS 개선량이나 원본 Android의 병목 해결을 검증한 결과는 아니다.**

## Android 실기기 표시 간격 수집

기존 ADB와 연결된 휴대폰에서 게임을 직접 실행하고 공연 장면을 유지한 뒤 사용한다. SDK 설치·root·앱 실행·강제 종료·설정 변경·로그 업로드를 하지 않는다. 현재 저장소에서 이 도구를 실기기에 실행한 결과는 없다.

```sh
python3 tools/capture_android_mv_performance.py --serial DEVICE_SERIAL --package GAME_PACKAGE --list-layers
python3 tools/capture_android_mv_performance.py --serial DEVICE_SERIAL --package GAME_PACKAGE --duration 25 --output private/mv-android-01.json
```

`private` 폴더는 먼저 만든다. `GAME_PACKAGE`는 설치한 클라이언트의 실제 패키지명으로 지정한다. 대상 패키지의 SurfaceView가 하나일 때만 자동 선택하며, 여러 개라면 출력된 이름 전체를 셸에서 인용해 `--layer '정확한 SurfaceView 이름'`으로 지정한다. 기존 출력 파일은 덮어쓰지 않는다.

도구는 SurfaceFlinger의 두 번째 열인 `actualPresentTime`에서 새 버퍼 표시 간격을 읽는다. 최초 조회의 과거 이력, 0·pending 값·중복을 제외하고 주사 주기 변경·타임스탬프 초기화·이력 겹침 소실을 별도 구간으로 나눈다. 대상 SurfaceView 집합이 달라지면 수집을 중단한다. 같은 레이어를 유지한 장면 변경은 판별할 수 없으므로 공연 도중 메뉴를 열지 않는다.

JSON의 p50·p95·p99·최대 간격과 50ms 초과 횟수는 **선택한 SurfaceView의 표시 간격 관측값**이다. 마지막 새 표시 기록을 받은 뒤 2초 이상 새 기록 없이 끝나면 `partial`과 `stale_tail_seconds`를 남긴다. 이는 수집 범위 경고 기준이며 0 FPS·끊김 원인을 판정하는 기준은 아니다. 요청 FPS, Unity CPU/GPU 시간, 실제 RT 해상도는 이 도구로 알 수 없어 null로 남긴다. 권한 거부·오래된 이력만 수신·지원하지 않는 명령은 0 FPS로 취급하지 않는다. SF가 보고한 주기를 기기의 게임별 실제 주사율로 확정하지 않으며, 읽기 전용 dumpsys 폴링 자체의 부하도 비교 시 통제한다.

## 병목 판별에 추가로 필요한 자료

같은 곡·카메라·인원·의상, 같은 실제 RT·품질·요청 FPS, 같은 접힘 상태에서 장면을 예열하고 25초 구간을 3회 비교한다. 첫 다운로드·셰이더 준비는 따로 기록하고 화면 녹화와 열 상태도 맞춘다. 원본/라우팅만 변경한 기준, 현재 패치의 custom·확장 OFF, 해상도를 맞춘 custom ON, 확장 ON을 구분한다. iOS도 같은 조건을 별도로 맞춘다.

Android에서 Perfetto의 CPU 스케줄링·주파수, Unity main/render/job 스레드, BufferQueue·present/fence 대기와 사용 가능한 GPU 이벤트를 수집한다. **FrameTimeline의 SurfaceView 지원 한계가 있으므로 앱 FrameTimeline이나 `gfxinfo`만으로 Unity 3D FPS를 계산하지 않는다.** GPU 이벤트가 없으면 GPU 시간을 추정값으로 채우지 않는다. iOS는 실행 가능한 실기기에서 Instruments의 Time Profiler·Metal System Trace로 같은 구간을 확인해야 한다. PlayCover 가상 Mac 결과를 iPhone 성능으로 대체하지 않는다.

브리지 비용을 분리할 때는 호출·실패·RT 재생성 횟수와 훅 내부/원본 시간을 합산하는 진단 카운터가 우선이다. 매 프레임 로그는 추가하지 않는다. CPU 제출 비용이 확인된 뒤에만 Android 스레딩 A/B를, GPU 비용이 확인된 뒤에만 해상도·효과 A/B를 검토한다.

참고: [Perfetto FrameTimeline](https://perfetto.dev/docs/data-sources/frametimeline), [Android SurfaceView](https://source.android.com/docs/core/graphics/arch-sv-glsv), [Android Frame Pacing](https://developer.android.com/games/sdk/frame-pacing), [Apple Metal System Trace](https://developer.apple.com/documentation/xcode/analyzing-the-performance-of-your-metal-app).

## 증거 고정

원본 파일 해시, 비교 필드, 주요 원본 함수 주소와 조사 한계는 [mv-performance-evidence.json](mv-performance-evidence.json)에 고정했다. 현재 런타임 검토 대상은 [bridge.cpp](../client-presentation/native/bridge.cpp)와 [panorama_ui_edges.hpp](../client-presentation/native/panorama_ui_edges.hpp)다. 전체 역어셈블리나 계정·기기 로그는 저장소에 추가하지 않는다.
