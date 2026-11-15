# v0.3.33 서버 기록·프로필 복구와 통합 메뉴 영역 확대

2026-11-15 · [릴리즈](https://github.com/tagundo/IdolyPride_client/releases/tag/local-server-v0.3.33) · [Actions](https://github.com/tagundo/IdolyPride_client/actions/runs/43716026678)

- 빌드 소스: `b9c3e3d7ed954e0c1c9d87e1f726fb8c29a8e479`
- 게시 커밋: `c5f299259b3009c6a5807f28b6707167c645c57d`
- Android·Mac 서버: 0.3.33 / build 50; 통합 IPA: 156.9113

## 변경

Android 서버의 **서버 기록** 아래 **서버 기록 내보내기**를 추가했습니다. 누른 시점의 표시 기록을 UTF-8 텍스트로 보관하며 시스템 저장 창에서 위치를 선택합니다. 기본 이름은 `IdolyPride-server-records.txt`입니다. 백그라운드 저장과 중복 실행 방지를 적용하고 취소·출력 스트림 오류·회전 중에도 기록을 보존합니다. 기존 표시 한도인 400줄·줄당 2,000자를 유지하고 기존 진단 JSON 내보내기도 유지합니다.

예외의 첫 프레임이 LINQ 등 프레임워크 함수이면 뒤의 첫 게임 호출 위치를 함께 표시합니다. 원래 예외 종류와 최대 16개 원본 프레임은 유지합니다. 보고된 **ArgumentNullException @ System.Linq.Enumerable.Where**의 발생 메뉴·실제 호출 위치는 아직 확인되지 않았습니다. 이번 변경을 그 오류의 원인 수정으로 표시하지 않습니다.

**Profile.UpdateEmblem**을 복구했습니다. 원본 Emblem 마스터에 존재하고 현재 계정이 보유한 칭호만 적용합니다. 트랜잭션 안에서 User.emblemId만 바꾸고 전체 user 갱신 응답을 반환하며 재시도·재시작·동시 요청과 알 수 없는 기존 데이터를 보존합니다. 보상이나 보유 칭호를 만들지 않습니다. 빈 값으로 해제하는 동작은 원본 UI 근거가 없어 허용하지 않습니다.

통합 IPA의 오른쪽 위 메뉴 진입 영역을 **64×64 → 128×128 포인트**로 넓혔습니다. 작은 안전 영역은 화면 안으로 제한하고 회전·크기 변경 후의 현재 좌표를 사용합니다. **2초·한 손가락·12포인트 이동 제한과 일반 터치 전달**을 유지합니다. Android는 별도 서버 앱 구성을 유지합니다.

## 미구현 기능 조사 범위

| 항목 | 결과 |
| --- | --- |
| 보유 프로필 칭호 적용 | 이번 버전에서 복구 |
| Mission.List 확장 | 저장된 실제 미션 투영을 검토; 임의 미션·보상 생성은 미포함 |
| 일일·타워 퀘스트 목록 | 마스터 기반 읽기 후보; 기존 퀘스트 분류와 저장 상태 검증이 더 필요 |
| 일반 모드 Company 화면 | 저장 상태의 검증이 필요; 감상 모드와 혼동해 해금하지 않음 |
| 카드 표시 형태 변경 | 실제 CardImage별 사용 가능 형태 확인이 필요해 보류 |
| NPC의 3D MV 출연 | 12개 실제 모델의 검증·골격/스크립트 비교 완료. [별도 조사](../npc-mv-feasibility.md). 실제 춤 재생·선택 기능은 미포함 |

[RPC별 구현 표](../rpc-coverage-6.1.1.csv)의 범위를 유지합니다. 근거 없는 빈 성공 응답으로 UNIMPLEMENTED를 숨기지 않습니다. 최신 [Elichika v2026.11.14.1](https://github.com/tagundo/elichika/releases/tag/v2026.11.14.1), 소스 `02f659d707997e03218be231e8a675fb0358a6c8`의 빈 목록·상태 갱신·일괄 보상 검증 방식도 대조했습니다. 다른 게임의 JSON 응답을 이 게임의 protobuf에 그대로 적용하지 않았습니다.

## 검증

- 같은 빌드 소스의 전체 검사 **6,860개·하위 375개 통과**, 환경별 123개 건너뜀. compileall 및 네이티브 정책 검사 통과.
- 새 기록 내보내기·예외 호출 위치·칭호의 보유/마스터 검증·실제 6.1.1 스키마·암호화 HTTP/2·재시도·재시작·동시성 검사를 포함합니다. 모서리 C 정책 검사는 43개입니다.
- Android: 서명·정렬된 ARM64 배포 APK와 x86_64 검사 APK 제작. 새 에뮬레이터의 실제 서버 UI·암호화 RPC·업데이트/재시작 보존·네이티브 엔진 등 기존 21개 필수 판정 통과.
- Mac: 별도 위치로 옮긴 실제 ARM64 SwiftUI 앱의 시작·중지·엔진 통신·엄격한 코드 서명 검사 통과.
- IPA: 기기/Simulator용 Apple SDK 빌드, 실제 Mac Foundation/AppKit, 같은 새 저장소의 **KO→EN→JA→EN→KO 다섯 완전 재실행**, 실제 파일 전체 해시·재사용, 시작 전 EPIPE 생존과 기존 키보드·서버 UI 즉시 전환·SDK 330초·암호화 RPC·마스터/Octo/번역 이미지 전송 검사 통과.
- 원본 Actions ZIP 전체 API SHA-256·동일 소스/실행 핀 검증, 게시 세 파일의 전체 원격 재다운로드 SHA-256 통과. 작은 게시 증거 ZIP을 API SHA-256과 대조하고 내부 보고서 **33개**를 다시 해시 검증했습니다. 인증 없는 각 파일의 64바이트 HTTP 206·전체 크기·ZIP 접두도 확인했습니다.
- 첫 후보는 iOS의 명시적 모듈 목록에 새 칭호 처리 모듈이 빠진 것을 검사가 발견했습니다. 목록을 보완한 최종 소스로 다섯 필수 검증과 게시가 모두 통과했습니다.

Android 실행 검사는 x86_64이며 ARM64 실기기 검사가 아닙니다. Simulator는 실제 서버와 검사용 Unity 진입점을 사용하며 원본 게임 공연을 실행한 검사가 아닙니다. 이 파일의 PlayCover·iPhone·iPad 실제 게임·터치 재확인과 게임 FPS 측정은 별도 대상입니다.

## 최적화 유지 확인

이전 v0.3.32의 공통 최적화를 유지하고 동일 입력의 세 독립 프로세스로 다시 비교했습니다. 합성 기록 200개×프레임 16개 상태 조회 CPU 중앙값은 이전 기준 0.816619 → 이번 0.013125 ms/회였습니다. 번역 검증 단계 피크 RSS는 192,557,056 → 175,775,744 bytes, 측정 전체 피크는 192,557,056 → 187,711,488 bytes였습니다. 처리 시간은 17.4268 → 17.4298초로 시작 속도 개선을 주장하지 않습니다. 실제 게임 FPS 측정값이 아닙니다. [이전 최적화 설명](optimization-v0.3.32.md).

## 다운로드와 SHA-256

| 파일 | 크기 (bytes) | SHA-256 |
| --- | ---: | --- |
| [IdolyPride-Local-Server-Android.apk](https://github.com/tagundo/IdolyPride_client/raw/c5f299259b3009c6a5807f28b6707167c645c57d/IdolyPride-Local-Server-Android.apk) | 332,258,691 | `4da22d3ce26b10e40af3ce2fa37642dafac89c9fb9d1c012312ebb88c0feebb8` |
| [IdolyPride-Local-Server-macOS-arm64.app.zip](https://github.com/tagundo/IdolyPride_client/raw/c5f299259b3009c6a5807f28b6707167c645c57d/IdolyPride-Local-Server-macOS-arm64.app.zip) | 331,079,069 | `e80823e6f2ace49aacef32a39496a5ee6d7c51b10b364b41cbfede1ecdf009ab` |
| [IdolyPride-6.1.1-Unified-iOS.ipa](https://github.com/tagundo/IdolyPride_client/raw/c5f299259b3009c6a5807f28b6707167c645c57d/IdolyPride-6.1.1-Unified-iOS.ipa) | 525,695,863 | `b4c8b1b5eb8a6ee43c567912ae92f33106ab5403c5916c7b340896368bde654e` |

별도 한국어 Android 게임 APK·PlayCover IPA는 검증된 v0.3.31 파일을 그대로 사용합니다. 통합 IPA는 서버를 포함하므로 별도 Mac 서버를 종료하고 사용합니다. 같은 앱을 삭제·데이터 지우기 없이 업데이트하면 기존 저장소를 유지하며 서로 다른 서버 구성 사이의 자동 계정 이전을 뜻하지 않습니다.

[작은 검증 요약](recovery-v0.3.33-evidence.json)
