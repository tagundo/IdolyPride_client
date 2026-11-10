# 원본 Android 기준 분석과 실행 검증

2026-11-11 점검. 원본 동작 → 로컬 연결판 비교 → 필요한 구간의 진단 순서로 검증합니다. 현재 자료에는 **우리 환경에서 원본 Android APK가 공식 서버에 정상 로그인한 뒤 메뉴를 사용하는 통신 캡처가 없습니다.** 진단판의 홈 진입을 그 증거로 대체하지 않습니다.

## 확인한 원본 파일

| 항목 | 값 |
| --- | --- |
| 릴리스 자산 | `725772331`, 원본 6.1.1 XAPK |
| 크기·SHA-256 | 167,699,540바이트 · `ab3bd9186ccc2659f91fcf2a48e25b591e94b4209c505f2ca401be8b22e5de36` |
| 패키지·버전 | `game.qualiarts.idolypride` · 6.1.1 / versionCode 414 |
| CPU·Unity | `arm64-v8a` split · Unity 2022.3.57f1 |
| 원본 서명 인증서 SHA-256 | `06cede031cd36c1986928fb5a9339c859253c07e06aff6137503d8385d3291b5` |

base APK와 ARM64 split의 원본 서명이 일치합니다. 기준 실행에서는 이 두 파일을 `adb install-multiple`로 설치하며 합치기·재서명·패키지명 변경을 하지 않습니다. AES 교체, 스토어 초기화 생략, 강제 사용자 생성 여부 변경, UI observer가 들어간 복사본은 원본 기준 실행에 포함하지 않습니다.

## 통신에서 아는 것과 아직 모르는 것

| 항목 | 확인 수준 |
| --- | --- |
| 공식 API `https://api.game-idolypride.jp`, HTTPS·HTTP/2 gRPC 스택 | 원본 바이너리 정적 분석 |
| 359개 descriptor 파일·68서비스·428 RPC, 요청/응답 타입 | 원본 추출·descriptor pool 검증 |
| protobuf와 AES-CBC·선택적 gzip application envelope | 원본 분석·공개 구현 대조·codec 테스트 |
| 공식 `System.Check`·`Master.Get` 등 익명 조회 | 우리 도구의 실제 공식 서버 호출; 원본 APK 실행 캡처와 구분 |
| 공개 튜토리얼·스토리·레슨 참조 응답 | 외부 공개 공식 캡처를 고정 커밋에서 보존 |
| 원본 APK의 현재 공식 로그인·메뉴별 요청 순서·정상 상태 변경 | **직접 관측 자료 없음** |
| 로컬 연결판·진단판의 홈·레슨·라이브 메뉴 | 별도 로컬 실행 자료; 공식 동작 검증과 구분 |

원본의 전송 계층은 다음과 같습니다. 상세 바이트 형식은 [프로토콜 문서](protocol.md)에 있습니다.

```mermaid
flowchart LR
    P[protobuf] --> Z[gzip 옵션]
    Z --> E[AES-CBC application envelope]
    E --> G[gRPC 프레임]
    G --> T[HTTP/2 · TLS]
```

`Auth.Login`에 보내는 Firebase ID token과 응답의 `gameAuthToken`은 다릅니다. 후속 게임 세션 metadata는 `x-auth-token`을 사용합니다. 정적 초기화 호출 순서를 실제 원본의 요청 순서로 확정하지 않습니다. 로컬 HTTP/h2c는 별도 URI 분기와 연결판의 동작이며 원본 공식 HTTPS 통신과 구분합니다.

TLS 패킷을 수집해도 RPC 경로와 본문은 그대로 보이지 않습니다. TLS를 해석한 경우에도 gRPC 프레임을 처리한 뒤 application envelope를 해독해야 protobuf를 읽을 수 있습니다. 원본은 `debuggable=false`이며 manifest의 기본 신뢰는 system CA입니다. 사용자 CA 설치만으로 복호화가 가능하다고 가정하지 않습니다. 네이티브 HTTP handler의 proxy·인증서 처리도 별도 확인 대상입니다.

## 현재 서버 구현 범위

기준 소스 `165a920`, 정규화 스키마 지문 `0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3`를 대조했습니다. 이후 검사 도구·문서 변경은 이 서버 경로 목록을 바꾸지 않았습니다.

| 분류 | 경로 수 | 의미 |
| --- | ---: | --- |
| 원본 스키마 전체 | 428 | unary 427개 + streaming 1개 |
| 기본 명시 처리 경로 | 49 | 제한된 로컬 동작·고정 기록·빈 목록·공개 fixture 전용 2개 포함 |
| 기본 자체 처리 경로 없음 | 378 unary | 가져온 사용자 fixture가 없는 조건; 공식 기능 구현으로 계산하지 않음 |
| 미지원 streaming | 1 | `Health.Watch` |
| 기본 OFF 실험 | 1 | 첫 메인 퀘스트에 한정된 `Quest.Start`; 일반 라이브 전체 구현 아님 |

427개 unary를 등록했다는 것은 427개 기능이 구현됐다는 뜻이 아닙니다. 49개 경로도 공식 기능 49개를 완전히 재현했다는 뜻이 아닙니다. 전체 요청·응답 타입과 제한은 [RPC 분류 CSV](rpc-coverage-6.1.1.csv)에 기록했습니다. 미지원 경로도 인증 상황에 따라 먼저 `UNAUTHENTICATED` 등으로 중단될 수 있으므로 오류 이름만으로 기능 존재를 판단하지 않습니다.

우선 대조할 미구현 범위는 다음과 같습니다. 이것은 코드·스키마 기반 목록이며 원본에서 실제 호출되는 순서라는 뜻은 아닙니다.

| 범위 | 대표 경로 | 현재 공백 |
| --- | --- | --- |
| 신규 계정 초기화 | `Auth.Create` | 현재 로컬 인증은 `Login`만 처리. bootstrap의 사용자 생성 여부 우회가 원본 흐름의 공백을 숨길 수 있음 |
| 일반 라이브 | `Quest.Start` | 첫 퀘스트 실험 외 전투·정산과 실제 재생 검증 |
| 미션 | `Mission.List` | 목록과 진행·보상 계약 |
| 활동 | `Activity.StartPromotion` | 일반 레슨 이외 활동의 상태 전이 |
| 촬영 | `Photo.CreateShootings` | 생성·소비·결과 계약 |
| 육성 | `Card.LimitBreak`, `Accessory.Enhance` | 초기 카드 강화 이외의 재료 소비·능력치·반환 상태 |
| 선물 | `Gift.Receive` | 현재 빈 목록 조회와 실제 수령 처리의 차이 |
| 가챠·로그인 보너스 | `Gacha.List`, `LoginBonus.List` | 목록·일정·수령과 일일 상태 계약 |

이 목록을 빈 성공 응답으로 채우지 않습니다. 원본의 요청·응답과 전후 상태, 마스터 참조·오류 조건을 확인한 뒤 저장·재시도·보상 중복 방지를 구현합니다. 기존 지원 범위는 [게임 상태 문서](gameplay-status.md)를 따릅니다.

## 에뮬레이터 선정과 현재 차단점

선정 기준은 **Google 공식 Android Emulator·공식 시스템 이미지·실제 가속 확인·원본 게임 구동**입니다. ARM64 호스트에서는 ARM64 이미지를 사용합니다. x86_64 호스트에서는 공식 x86_64 이미지의 Google 제공 ARM64 앱 번역 지원을 확인해야 하며, ARM64 시스템 이미지를 x86에서 가속할 수 있다고 가정하지 않습니다. 임의 native bridge나 AES·Go 런타임 패치를 추가해 기준 실행으로 취급하지 않습니다.

- [Google: CPU·GPU 가속과 지원 아키텍처](https://developer.android.com/studio/run/emulator-acceleration)
- [Google: ARM 앱 번역 지원](https://android-developers.googleblog.com/2020/03/run-arm-apps-on-android-emulator.html)
- [Google: AVD·Google Play 이미지와 root 제한](https://developer.android.com/studio/run/managing-avds)

현재 선택된 클라우드는 x86_64 Linux이며 CPU 가상화 플래그·KVM 장치·GPU 장치가 없습니다. rootless Docker도 같은 호스트이며 이를 추가해 주지 않습니다. GitHub Mac은 Android용 중첩 가상화를 지원하지 않고, 이전 GitHub Linux 소프트웨어 GPU 환경의 실제 게임은 약 1.7FPS였습니다. **정상 구동용 에뮬레이터 설치·검증을 완료한 상태가 아닙니다.** 현재 도구에는 GPU/KVM 호스트를 새로 할당하거나 이 인스턴스의 하드웨어를 변경하는 기능도 없습니다. 사용자는 현재 클라우드만 사용 가능하다고 명시했습니다.

원본 기준 검증은 가속 가능한 실행 호스트 확보 → 원본 해시·서명 보존 설치 → 정상 화면·원본 PID 로그·실제 네트워크 관측 → 메뉴별 요청/응답과 상태 변화 정리 → 최소 연결 변경판 대조 → 필요한 경우 진단 순서로 진행합니다. 루팅·시스템 CA·관측 도구를 추가한 조건은 별도로 기록합니다. Google Play 이미지와 root 가능한 이미지의 차이도 구분합니다. 계정·세션 원문은 비공개 로컬 자료로 유지하며 채팅·공개 저장소에 넣지 않습니다.

기존 소프트웨어 GPU·변형 APK 게임 workflow는 기본 비활성화했습니다. 자료와 합성 네이티브 검사는 보존하지만 원본 게임의 정상 동작이나 새 호스트의 적합성 근거로 사용하지 않습니다.
