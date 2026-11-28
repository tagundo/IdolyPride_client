# v0.3.34 프로필·포토 편집과 목록 복구

2026-11-15 · [릴리즈](https://github.com/tagundo/IdolyPride_client/releases/tag/local-server-v0.3.34) · [Actions](https://github.com/tagundo/IdolyPride_client/actions/runs/43722420006)

- 빌드 소스: `4bf0325d90ac36c9f3a5a9f10c55ef7d0e456118`
- 게시 커밋: `48ddc99687c608a1f7a0b2e586619a3f7927f57b`
- Android·Mac 서버: 0.3.34 / build 51; 통합 IPA: 156.9114

## 실제 설정 변경

| 동작 | 복구 범위 |
| --- | --- |
| 버디 카드 선택 | 보유 카드 지정, 전체 사용자 갱신 응답 |
| 프로필 장식 | 실제 마스터·보유 항목 적용, 전체 프로필 갱신 |
| 프로필 배경 | 기본/보유 포토/보유 카드 일러스트와 자동 표시 선택을 원자적으로 저장 |
| 카드 상세 일러스트 | 실제 카드·표시 유형 조합과 현재 희귀도/진화 조건을 확인해 저장 |
| 포토 잠금/해제 | 보유 포토 한 장 또는 여러 장을 한 번에 전환하고 전체 행 응답 |

전체 해금 감상 모드에는 실제 장식 **361종**의 누락 보유 행만 추가합니다. 기존 감상 계정에도 다음 준비 시 적용하며 선택한 장식·기존 행·알 수 없는 필드는 보존합니다. 일반 계정에는 새 보유 항목을 지급하지 않습니다. [사용 흐름과 제한](../preference-support.md).

포토 잠금 원본 API는 최종 상태가 아닌 전환 요청입니다. 원본 SDK의 DateTime.Now.Ticks 요청 ID·입력·스키마에 연결한 응답을 상태 변경과 함께 저장해 재시도·재시작·동시 요청이 잠금을 두 번 바꾸지 않게 했습니다. 같은 ID의 다른 입력은 거절하며 명시적 계정 가져오기는 해당 계정의 이전 응답 기록만 초기화합니다. 기본 배경의 참조 초기화는 지원하지만 버디·장식의 빈 ID 해제나 생일 등록은 근거가 부족해 포함하지 않았습니다. 새 포토 생성도 별도 미구현입니다.

## 원본 자료와 목록

원본 ServerData의 SHA-256·실제 스키마·202개 팩 목록/응답을 대조한 뒤 암호화된 CardImage·Decoration 두 팩만 SQLCipher 읽기 전용으로 해독했습니다. CardImage **611개 카드/표시 유형 조합**과 Decoration **361종**을 데이터 전용 소스 모듈에 보관합니다. 기존 JSON이 없고 카탈로그 버전이 정확히 일치할 때만 보완합니다. 기존 ServerData ZIP·게임 원본 마스터·리소스 지문·언어 캐시 형식은 유지합니다. [입력·추출 지문](../preference-master-data.json).

Mission.List는 실제로 저장된 일반 Daily·Weekly·Normal 행을 정확한 임계값·표시 보상과 함께 반환합니다. 전용 Photo·이벤트·교류 미션은 일반 탭에 섞지 않고 원본 저장소에 보존합니다. 신규 계정에 새 미션을 생성하거나 수령·기간 리셋을 구현한 것은 아닙니다.

Quest.Top과 새 ListDaily·ListContest·ListTower·TowerTop은 실제 마스터 목록과 저장된 점수·등급·클리어·조회용 타워 위치를 제공합니다. 조건부 일일·서브타워는 실제 결과가 있을 때 과거 기록으로 표시하며 새 입장권·전투·보상을 만들지 않습니다. [목록 복구 범위와 Company 보류 이유](../menu-recovery-v0.3.34.md).

구현표 33행의 기존 기능·조건부 감상/자료 읽기 범위도 코드와 맞췄습니다. 이를 새로 복구한 기능 33개로 계산하지 않습니다. [RPC 구현표](../rpc-coverage-6.1.1.csv).

## 검증과 게시

- 최종 소스의 전체 검사 **7,271개·하위 375개 통과**, 환경별 165개 건너뜀. compileall과 네이티브 정책 검사 통과.
- 원본 자료 필수 검사 **3개, 생략 0개**: 보완 모듈 전체 지문·611/361행 확인, 실제 보유 선택 저장, 기존 감상 계정 장식 보완/보존/재적용.
- 전체 배치 검증·원자성·미보유 거절·실제 6.1.1 필드·암호화 HTTP/2 인증·중복 헤더·정확한 재시도·동시성·저장 실패 롤백·재시작·계정 분리·알 수 없는 필드 보존을 검사했습니다.
- Android: 서명·정렬된 ARM64 배포 APK 및 x86_64 검사 APK. 실제 서버 UI·암호화 통신·업데이트/재시작 보존·네이티브 엔진의 기존 필수 판정 통과.
- Mac: 실제 ARM64 SwiftUI 앱을 다른 위치로 옮겨 시작·중지·엔진 통신·엄격한 서명을 검사했습니다.
- IPA: 기기/Simulator Apple SDK 빌드, 실제 Mac Foundation/AppKit, 같은 저장소의 **KO→EN→JA→EN→KO 다섯 재실행**, 실제 파일 전체 해시/재사용, 시작 전 EPIPE 생존과 기존 서버 메뉴·키보드·언어 즉시 전환·SDK/마스터/Octo/번역 이미지 검사를 유지했습니다.
- 게시기는 원본 Actions ZIP 전체 API SHA-256과 동일 소스·실행의 다섯 성공을 검증하고 세 게시 파일 전체를 원격 재다운로드해 SHA-256을 대조했습니다. 작은 게시 증거 ZIP의 API SHA-256, 내부 보고서 **36개**와 필수 JUnit 3개를 다시 확인했습니다. 세 고정 주소의 인증 없는 64바이트 HTTP 206·전체 크기·ZIP 접두도 확인했습니다.

첫 회귀 검사가 원본 enum의 ResourceType_ 접두어 처리 오류를 발견했습니다. 정확한 접두어만 제거하도록 고치고 원본 enum 검사가 잘못 생략되지 않게 했으며, 최종 소스로 전체 검사와 다섯 검증·게시를 다시 통과했습니다.

Android 실행 검사는 x86_64입니다. Simulator는 실제 서버와 검사용 Unity 진입점을 사용합니다. 실제 Android ARM64 기기 및 이 파일의 PlayCover·iPhone·iPad 게임 편집 화면·터치·공연 재확인은 별도 대상입니다. 게임 FPS나 시작 속도 향상을 측정한 릴리즈가 아닙니다. 이전 공통 최적화의 동일 입력 비교는 유지했습니다.

보고된 Enumerable.Where 예외의 원인은 아직 확인되지 않았고 NPC MV 출연은 별도 조사 단계입니다. 일반 Company의 보상 수령 이력·급여를 추측해 기능을 개방하지 않습니다.

## 다운로드와 SHA-256

| 파일 | 크기 (bytes) | SHA-256 |
| --- | ---: | --- |
| [IdolyPride-Local-Server-Android.apk](https://github.com/tagundo/IdolyPride_client/raw/48ddc99687c608a1f7a0b2e586619a3f7927f57b/IdolyPride-Local-Server-Android.apk) | 332,301,503 | `7340387f3285d7b9a255b7bdb5c12e96b7c8e0606922aa2653b109e8ff6838e0` |
| [IdolyPride-Local-Server-macOS-arm64.app.zip](https://github.com/tagundo/IdolyPride_client/raw/48ddc99687c608a1f7a0b2e586619a3f7927f57b/IdolyPride-Local-Server-macOS-arm64.app.zip) | 331,122,144 | `ed4c8caee7e1ea30da435098dec7e29ff1332289879e43cca1dd052e423bd3c4` |
| [IdolyPride-6.1.1-Unified-iOS.ipa](https://github.com/tagundo/IdolyPride_client/raw/48ddc99687c608a1f7a0b2e586619a3f7927f57b/IdolyPride-6.1.1-Unified-iOS.ipa) | 525,727,103 | `01fbec7c54e7d67417a3afc4baf7afe23bc074a16e8346c08e44520dea178c38` |

Android는 기존 v0.3.31 한국어 게임 APK와 새 서버 APK를 사용합니다. 별도 Mac 서버용 PlayCover IPA도 기존 파일을 재사용합니다. 통합 IPA는 서버가 포함되므로 별도 Mac 서버를 종료한 뒤 사용합니다. 삭제·데이터 지우기 없이 기존 앱 위에 업데이트하며 서로 다른 구성 사이의 자동 계정 이전을 뜻하지 않습니다.

[게시·원본 자료 검사·해시 요약](recovery-v0.3.34-evidence.json)
