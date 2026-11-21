# 계정·프로필·설정 관련 게임 API 조사

2026-11-16 기준 **새 소스 조사 기록이며 배포 기록이 아닙니다.** 현재 원본 6.1.1 descriptor의 서비스·메서드 목록과 [RPC 범위 표](rpc-coverage-6.1.1.csv)를 대조했습니다. [실제 메서드·분류 JSON](account-game-api-investigation.json)에 전부 기록합니다. 계정 관리 화면의 버튼 수나 RPC 수를 복구된 완성 게임 기능 수로 세지 않습니다.

## 기존 범위와 이번 변화

| 서비스 | 원본 RPC 수 | 기존 로컬 처리 | 이번 새 소스 처리 | 남은 미지원 |
| --- | ---: | ---: | ---: | ---: |
| Auth | 4 | 1 | 0 | 3 |
| Profile | 12 | 9 | 2 | 1 |
| User | 2 | 1 | 0 | 1 |
| System | 3 | 3 | 0 | 0 |
| Home | 5 | 5 | 0 | 0 |

여기의 기존 처리도 명시된 **로컬 범위**입니다. 예를 들어 Auth.Login은 공식 Firebase 검증이 아닌 로컬 프로필 세션이며, System.CheckApp/GetMetadata는 의도적인 빈 로컬 응답입니다. Profile.Top은 실제 저장 등급을 조회하지만 전역 순위·원격 친구를 만들지 않습니다. 이미 있던 19개 경로를 이번에 새로 복구한 것으로 표시하지 않습니다.

이번에 새로 추가한 게임 RPC는 정확히 두 개입니다.

1. **Profile.FindUser** — 선택한 로컬 계정의 실제 서버/공개 ID 조회, 저장된 프로필·보유 카드/사진과 실제 마스터의 등급을 반환합니다. 다른 로컬 계정과 원격 사용자는 NOT_FOUND입니다.
2. **Profile.UpdateBirthday** — 미등록 0/0 날짜의 초기 등록, 같은 날짜의 재요청과 전체 프로필 ACK를 지원합니다. 기존 다른 날짜 덮어쓰기·생일 캠페인·ADV·알림·보상은 포함하지 않습니다.

이전의 이름·소개·좋아하는 아이돌·칭호·버디·장식·배경·레이아웃 편집과 새 두 경로를 연결한 로컬 프로필 사용 흐름을 검사합니다. [세부 저장·조회 계약](profile-directory-support.md). 이것은 광범위한 미실장 게임 콘텐츠 복구를 끝냈다는 뜻이 아닙니다.

## 설정과 등록 관련 실제 계약

원본 descriptor에는 독립 `Setting`/`Settings` 서비스가 없습니다. 게임의 `Home.LoginRequest.settingInfo`에 음량 세 가지, 그래픽 종류·프레임률, 활동/메시지/미접속 알림, 야간 모드, 용량 제한의 10개 필드가 있습니다. 기존 Home.Login은 전달된 SettingInfo 원본 바이트를 스냅샷 변경과 함께 저장합니다. 이 저장을 새로운 설정 RPC 복구라고 세지 않습니다. 서버 UI의 언어·렌더링·계정 선택 등 native 관리 명령은 게임의 protobuf RPC와 별개의 기능입니다.

새 로컬 계정 생성 역시 원본 초기 보상 마스터를 사용하는 별도 로컬 준비 기능입니다. Auth.Create의 공식 Firebase 등록 요청을 복구한 것으로 표시하지 않습니다.

## 남겨 둔 미지원과 필요한 근거

| 경로/묶음 | 확인된 계약 | 지금 처리하지 않는 이유와 다음 근거 |
| --- | --- | --- |
| Auth.Create | firebaseUID → firebaseCustomToken | 실제 Firebase 토큰 발급·클라이언트 등록 흐름 근거가 없습니다. 가짜 문자열을 반환하면 뒤의 SDK 등록을 복구한 것이 아닙니다. |
| Auth.Recreate | firebaseIDToken → firebaseCustomToken | 재인증·기존 데이터 연결·복구 조건이 필요합니다. 이미 지원하는 로컬 로그인과 다른 계약입니다. |
| Auth.Delete | Empty → 빈 응답형 | 응답이 비어 있어도 전체 계정 삭제·SDK 로그아웃·재가입은 상태 전이입니다. 검증된 삭제 후 재시작/재등록 흐름 없이 빈 성공을 반환하지 않습니다. |
| Profile.ClearTwitterMission | Empty → commonResponse | SNS 미션의 자격 확인·대상 미션·진행도 갱신 근거가 없습니다. 저장된 twitterInfo가 있다는 이유만으로 보상이나 완료를 생성하지 않습니다. |
| User.ProvideExternalReward | externalRewardId → commonResponse | 외부 지급 자격, 해당 ID의 보상 매핑, 이미 지급된 상태의 판정·중복 방지 근거가 필요합니다. 임의 재화 지급을 로컬 조회 복구에 섞지 않습니다. |
| Birthday의 다섯 RPC | Top, SetWatched, SetWatchedRemindInfo, OutputWatchedLog, ReceiveReward | 생일 이벤트 목록·ADV 에셋·대상 기간·읽음과 수령 상태·보상 정의가 필요합니다. 저장 프로필의 월/일만으로 이 자료를 복원할 수 없습니다. 빈 Top 성공으로 감추지 않습니다. |
| Shop.RegisterBirthday | year, month → 등록 결과 | Shop에 별도로 있는 연도·월 등록 계약입니다. 연도 없는 프로필 월/일에서 이 입력을 추정할 수 없으며, 상품·구매 규칙과 실제 저장·등록 단계의 근거가 더 필요합니다. |
| Friend 관계 변경 여섯 RPC | Apply/Approve/Cancel/CancelAll/Delete/Reject | 현재 로컬 소셜 그래프는 비어 있으며 List/ListApplied/ListApplying/Search 네 조회만 제공합니다. 서로 다른 실제 프로필·관계 상태·상대의 동의/요청·원자적 관계 저장 규칙을 먼저 설계·검증해야 합니다. 자기 프로필 조회를 원격 친구 복구로 확대하지 않습니다. |

추가 복구를 위해 우선 확보할 자료는 해당 6.1.1 요청 전후의 공식 응답·실제 클라이언트 소비 함수, 관련 마스터와 저장 상태입니다. 프로필 분야에서 근거 없이 더 많은 빈 성공을 추가하기보다, 별도 기능 묶음의 실제 사용 흐름과 자료를 조사하는 것이 타당합니다. 현재 결과만으로 새 게임 기능을 충분히 많이 복구했다고 주장하거나 새 공개 릴리즈를 정당화하지 않습니다.

## 조사 근거와 검증 경계

원본 descriptor는 508,520바이트이며 SHA-256은 `c82cee62abdca7144d11e710a6f773211464a89d2ddede207999a0a5e7aec8ad`입니다. 프로젝트나 protobuf 패키지를 로컬에 import하지 않고 표준 라이브러리의 제한된 protobuf wire parser로 서비스·메서드 목록을 읽어 CSV와 대조했습니다. 관련 실제 필드는 기존 `native-live-engine/internal/proto/papi/papi.pb.go`와 `ptransaction/ptransaction.pb.go`에서도 확인했습니다. 이 조사 자체는 새로운 서버의 실행 검사나 기기 UI 확인을 대신하지 않습니다.
