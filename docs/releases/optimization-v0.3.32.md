# v0.3.32 서버 최적화와 세 플랫폼 릴리즈

2026-11-15 · [릴리즈](https://github.com/tagundo/IdolyPride_client/releases/tag/local-server-v0.3.32) · [Actions](https://github.com/tagundo/IdolyPride_client/actions/runs/43710465014)

- 빌드 소스: `7f4244f146a07c35cafcdacf1e5caef949cd1d1c`
- 게시 커밋: `5eb868ca2860ecaa092d70977eb1b0d7c92b2759`
- Android·Mac 서버: 0.3.32 / build 49; 통합 IPA: 156.9112

## 변경

상태 조회가 최대 200개 진단 기록과 프레임을 깊은 복사한 뒤 버리던 경로를 요약 전용으로 바꿨습니다. 전체 기록 조회의 기본 동작은 유지하고 명시적 내보내기는 한 번만 복사합니다. 다음 번역 언어를 검증하기 전에 이전 객체의 보유 참조를 해제하고, SHA-256 지문은 같은 바이트를 순서대로 갱신해 계산합니다. 번역 내용·파일·캐시 리비전과 계정 저장 형식은 유지합니다.

## 측정

Linux CI에서 고정된 이전 소스와 같은 입력·Python 환경으로 독립 프로세스를 각각 세 번 실행한 중앙값입니다. Android·Mac·통합 IPA가 공유하는 서버 코드의 측정이며 전체 앱이나 Unity 실행 측정이 아닙니다.

| 항목 | 이전 | 수정 |
| --- | --- | --- |
| 서버 상태 조회 CPU / 회 | 1.009245 ms | 0.015311 ms |
| 번역 검증 단계 최대 RSS | 192,593,920 bytes | 175,845,376 bytes |
| 측정한 번역 처리 전체 최대 RSS | 192,593,920 bytes | 187,723,776 bytes |
| 측정한 번역 처리 시간 | 20.624 s | 20.856 s |

상태 조회는 합성 기록 200개 × 프레임 16개, 1,000회 × 세 새 프로세스 조건입니다. 조회마다 기록 복사 1회→0회, 명시적 내보내기 2회→1회이며 전체 출력 해시가 같습니다. 번역 검증 단계의 피크는 약 15.97 MiB, 측정한 번역 처리 전체 피크는 약 4.64 MiB 낮아졌습니다. 순수 Python protobuf와 실제 SHA 고정 공개 iOS 자료로 JA→KO→EN→KO를 검사했으며 목록·alias·범위·저장된 리비전 바이트가 일치합니다. 시작 시간 차이는 작아 개선으로 단정하지 않으며 게임 FPS 향상을 주장하지 않습니다.

[측정 수치·입력·원본 보고서 해시](optimization-v0.3.32-benchmarks.json) · 재현 도구: `tools/benchmark_diagnostics_polling.py`, `tools/benchmark_translation_startup.py`.

## 검증과 배포

- 전체 검사 6,805개와 하위 검사 375개 통과; 환경별 123개 건너뜀. compileall과 네이티브 정책 검사 통과.
- Android: ARM64 배포 APK와 별도 x86_64 검사 APK 빌드·서명·정렬·패키지/버전/공개 개발 인증서 검사. 새 에뮬레이터에서 실제 서버 UI, 암호화 RPC, 재시작·업데이트 후 계정/세션/설정 보존과 네이티브 라이브 엔진 등 21개 필수 판정 통과.
- Mac: ARM64 SwiftUI 앱을 별도 위치로 옮겨 실제 시작·중지·엔진 통신과 엄격한 코드 서명 검사 통과.
- IPA: Apple 기기/Simulator SDK 빌드, 실제 Mac Foundation/AppKit 검사, 같은 새 Simulator 저장소에서 KO→EN→JA→EN→KO 완전 재실행 통과. 준비 전 대기, EPIPE 생존, 원래 신호 보존, 실제 언어 파일 전체 해시와 돌아온 언어의 파일 동일성, 즉시 UI 전환·키보드·SDK 330초·서버 유지·암호화 RPC·마스터/Octo/이미지 전송 검사를 유지.
- 동일 실행의 원본 Actions ZIP 전체 API SHA-256, 소스 핀과 보고서를 대조하고 게시한 세 파일 전체를 원격에서 다시 받아 SHA-256 검증. 별도로 인증 없는 64바이트 HTTP 206·전체 크기·ZIP 접두 확인.
- 초기 실행은 검사 도구의 호스트별 차이, 준비 자료 누락과 사용하지 않는 빈 응답 자료 선택 때문에 중단됐습니다. 준비 코드와 호스트 구분, 화면 밖 옵션 탐색 및 검사 대역의 화면 계층 반환을 고쳤으며 통과 조건은 유지했습니다. 다섯 재실행의 총 검사 예산은 느린 Simulator 부팅·설치를 포함하도록 600→900초로 조정했고 개별 동작의 제한은 유지했습니다. 최종 실행은 모든 필수 판정을 통과했습니다.

Android 실행 검사는 x86_64이며 ARM64 실기기 검사는 아닙니다. iOS Simulator는 실제 서버·리소스와 검사용 Unity 진입점을 사용합니다. 원본 Unity 게임을 Simulator에서 실행한 검사가 아니며 이번 파일의 실제 PlayCover·iPhone·iPad 재검증과 게임 FPS 측정은 별도 대상입니다.

## 다운로드와 SHA-256

| 파일 | 크기 (bytes) | SHA-256 |
| --- | ---: | --- |
| [IdolyPride-Local-Server-Android.apk](https://github.com/tagundo/IdolyPride_client/raw/5eb868ca2860ecaa092d70977eb1b0d7c92b2759/IdolyPride-Local-Server-Android.apk) | 332,253,919 | `d4f2c3f2d75c7650d7f3452689491e11f46ae5686ddc3563fa3e73cd328b521d` |
| [IdolyPride-6.1.1-Unified-iOS.ipa](https://github.com/tagundo/IdolyPride_client/raw/5eb868ca2860ecaa092d70977eb1b0d7c92b2759/IdolyPride-6.1.1-Unified-iOS.ipa) | 525,694,288 | `f0f30e6a2f92a0cc167dfac3e546f9f2859788128556d5bcc8e0f6712ee3c903` |
| [IdolyPride-Local-Server-macOS-arm64.app.zip](https://github.com/tagundo/IdolyPride_client/raw/5eb868ca2860ecaa092d70977eb1b0d7c92b2759/IdolyPride-Local-Server-macOS-arm64.app.zip) | 331,076,384 | `f393f2d5082a95205ed1a76abeb758fe3af70a6449b61a1aa14f2fd905fc85fa` |

한국어 게임 APK와 별도 PlayCover IPA는 기존 v0.3.31 파일을 재사용합니다. 통합 IPA와 별도 서버 구성은 대안이며 같은 게임 식별자와 서버 포트를 사용합니다. 같은 앱의 업데이트 설치는 기존 저장소를 유지하지만 구성 간 자동 이전을 뜻하지 않습니다. 삭제·데이터 지우기 없이 업데이트하세요.
