# 로컬 게임 상태 구현 범위

`Gameplay`는 6.1.1 스키마와 같은 버전의 마스터를 사용합니다. 현재 구현은 부팅·홈 응답, 일부 사용자 설정·배치·튜토리얼·덱 상태의 보존입니다. 실제 게임 앱의 홈 진입·라이브 플레이를 검증한 상태는 아닙니다.

## 제목 화면의 환불 기간 조회

`Refund.GetTerm`은 `System.Check` 다음, `Auth.Login` 전에 호출되는 익명 조회입니다. v0.2.1은 로그인 없이 `startDatetime=endDatetime=4102444800000`(2100-01-01 UTC), `shopInvalidStartDatetime=0`을 반환합니다. 공식 환불 신청·잔액 조회는 실행하지 않습니다.

6.1.1의 `TitleView.StartAnimationAsync` 상태 머신(`0x5173d0c`)은 시작·종료 값 0을 무제한 기간으로 취급하므로 둘 다 0으로 두면 환불 버튼이 나타납니다. 미래 시작·종료를 사용해 환불 화면을 비활성화합니다. `CheckOpenStoneShop`(`0x528d338`)은 `IsBefore(shopInvalidStartDatetime)`을 사용하므로 0은 유료 상점 진입을 닫습니다. `GetPaidStone`과 사용자 데이터에는 기존 인증 검사를 유지합니다.

실제 Android에서 관측한 `System.Check → Refund.GetTerm`을 재현한 뒤 `Auth.Login`으로 이어지는 흐름을 HTTP/2·grpcio와 에뮬레이터 검사에 포함하며, 이 조회가 기존 프로필·세션을 바꾸지 않는지 검증합니다.

## 구현한 RPC

| RPC | 로컬 동작 | 저장되는 내용 |
| --- | --- | --- |
| `Home.Login` | 설정 수신·로그인 시각 갱신 | `SettingInfo`, `user.lastLoginTime`, JST 날짜별 `totalCount.loginCount` |
| `Home.Enter` | 마스터 기반 현재 메인 지역·현재 하이어라키 등급·홈 컨테이너 반환 | 읽기 전용; 보상·이벤트는 생성하지 않음 |
| `Home.SetReview` | 리뷰 확인 상태 기록 | `user.isReviewed=true` |
| `Home.SetCharacterPosition` | 소유 캐릭터·배치 유형을 검증하고 갱신 | `homePositions` |
| `Dokan.List` | 비어 있는 로컬 팝업 목록 | 없음 |
| `Notice.List` | 비어 있는 로컬 공지 목록 | 없음 |
| `Master.GetVersion` | 묶음의 `!version.txt` 반환 | 없음 |
| `Tutorial.Init` | 이름과 최초 GameStart 체크포인트 설정 | `user.name`, GameStart step 최소 10 |
| `Tutorial.Progress` | 알려진 유형·마스터 체크포인트의 진행을 단조 증가 | `tutorials`, GameStart 완료 시각 |
| `Tutorial.Skip` | GameStart 튜토리얼만 완료 처리 | GameStart step 최소 150·완료 시각 |
| `Deck.Save` | 기존 덱의 수동 편집, 카드·외형·사진·장비 소유 관계 검증 | `decks`, `deckPositions`, 제거된 슬롯의 `deletedData` |
| `Deck.Delete` | 지정한 기존 덱 삭제 | 덱·배치 제거 및 `deletedData` |

`Deck.Save`는 배치 1~5와 중복 참조·장비 수량·슬롯·캐릭터 제한을 검증합니다. 신규 덱 번호 할당, 자동 편성, 버디 대여, 캐릭터 그룹 제한 장비는 아직 `UNIMPLEMENTED`입니다. 일반 캐릭터 제한 장비는 동봉한 `Accessory` 마스터로 검증합니다.

해당 변경 응답은 `commonResponse.updatedData`에 반영됩니다. 일반 게임 동작은 활성 로컬 세션을 유지하며, snapshot과 설정을 SQLite의 단일 트랜잭션에서 갱신합니다. 동시 요청의 변경 유실, 잘못된 요청의 부분 저장, 스키마가 다른 snapshot 수정은 거부합니다. protobuf의 알 수 없는 필드도 정상 수정 뒤 유지합니다.

`Home.Enter`는 `HierarchyDetailGrade`·`HierarchyGrade`의 실제 참조를 검증합니다. 현재 점수에서 전역 순위가 필요 없는 등급을 선택하며 순위·보상을 생성하지 않습니다. 신규 프로필의 0점 기본 등급은 현재 마스터의 `hie-007-003`입니다. 기존 snapshot의 빈 하이어라키에는 응답에서만 기본 등급을 적용하며 저장된 계정 상태는 변경하지 않습니다. 잘못된 마스터 참조는 명시적으로 거부합니다. Android 6.1.1 `HomeTop.SetHomeEnterData`(`0x566c15c`)는 현재 등급을 무조건 읽고, 조회 실패 시 `0x566c1c8`에서 null 참조로 중단합니다.

`Home.Enter`의 이벤트·활동·배너 컨테이너는 로컬 콘텐츠가 없다는 구조를 반환합니다. 급여·자동 보상·진행 중인 활동 결과를 만들어내지는 않습니다. 메인 지역 선택에는 `Area` 마스터가 필요하며 다른 지역 유형을 임의로 메인 지역으로 취급하지 않습니다.

진행 중인 특별 홈 이벤트가 없으면 `homeFishHeavenInfo` 메시지는 보내지 않습니다. Android 6.1.1의 `HomeTop.ShouldHideLoading`(`0x566c9b0`)과 홈 전환(`0x5675ff4`~`0x5676008`)은 이 메시지가 null인지 검사합니다. 빈 메시지도 존재하면 일반 로딩 화면을 숨기지 않으므로, v0.2.6은 이 선택 필드를 응답에서 제외합니다. v0.2.5와 진단판 v0.2.1의 실제 기기 기록에서 배경·캐릭터·홈 표시 전환은 통과하고 `loading_hide`만 누락된 것을 확인했습니다. 이 변경은 응답만 수정하며 저장된 계정·튜토리얼·세션을 변경하지 않습니다.

## 신규 프로필의 시작 데이터

`seed_starter_profile(state, schema, profile, master_dir)`는 snapshot이 없는 프로필에서만 사용합니다. 기존 공식 계정 snapshot이나 이미 생성한 로컬 프로필에는 자동 적용하지 않습니다.

시작 캐릭터는 `Character.type=1`이며 `viewConditionId`·`unlockConditionId`가 모두 빈 일반 캐릭터 17명입니다. Android 6.1.1의 `GetSubCharacterCandidate`는 보유 목록을 검사하지 않고 이 마스터 풀에서 홈 배경 인물을 선택합니다. 이어 `CreateActorDescriptor`는 `UserCharacter.FindById` 결과를 무조건 읽으므로 5명만 준비하면 나머지 12명 선택 시 null 참조가 발생할 수 있습니다. 조건이 있는 `char-kan/kor/mhk` 등은 제외합니다. 이 17명은 실제 `initial_user_reward`의 캐릭터 목록과도 일치합니다.

`Setting.tutorialPhotoShootingCharacterIds`의 5명은 기본 즐겨찾기·홈 배치에 사용합니다. 각 캐릭터의 기본·라이브 의상과 헤어 소유 관계·착용 가능성을 실제 마스터로 검증합니다. 활동 레벨 1 체력은 `CharacterActivityLevel`에서 가져오며 최초 메인 지역의 퀘스트 참조도 검증합니다.

최소 데이터에는 레벨 1 매니저, 위 캐릭터·외형, 홈 배치, 빈 덱 하나와 GameStart step 0이 포함됩니다. 카드·통화·보상·라이브 클리어·기능 전체 해금은 지급하지 않습니다. 마스터 참조 검증이 실패하면 부분 snapshot을 남기지 않습니다.

`repair_starter_roster`는 출처 표시가 있는 구형 로컬 프로필 또는 이전 서버의 5명·기본 외형·빈 `Local deck`·고정 홈 배치·식별자가 일치하는 구성을 보완합니다. 출처 없는 데이터에 다른 인벤토리·잔액이 있으면 보정하지 않습니다. 가져오기는 출처 0으로 표시하여 제외하며, 신규 기본 데이터는 버전 2입니다. 누락 캐릭터 추가와 버전 갱신은 한 SQLite 트랜잭션으로 수행합니다. 기존 캐릭터·외형·진행·이름·설정·세션·알 수 없는 protobuf 필드는 유지합니다.

사용하는 마스터 파일은 `Setting.json`, `Character.json`, `Costume.json`, `Hair.json`, `CharacterActivityLevel.json`, `Area.json`, `Quest.json`, `Tutorial.json`, `Card.json`, `Accessory.json`, `HierarchyDetailGrade.json`, `HierarchyGrade.json`, `!version.txt`입니다. 번들의 정규 JSON은 protobuf 필드 이름과 숫자 enum을 사용합니다.

## 근거·검증

- 실제 6.1.1의 `api/home.proto`, `api/tutorial.proto`, `api/common_response.proto`, `transaction/user.proto`, `transaction/user_tutorial.proto` descriptor로 요청·응답 필드와 변경 목록을 확인했습니다.
- iOS native `UserTutorialCollection.IsFinished`의 `0x1e0d274`에서 GameStart 완료 조건 `step > 149`를 확인했습니다. 마스터에도 마지막 체크포인트 150이 있습니다. 다른 튜토리얼을 함께 완료시키지 않습니다.
- `TimeManager.GetDeviceNowUnixTime`의 `0x1d29230`은 UTC epoch 차이에 `TimeSpan.TotalMilliseconds`를 적용합니다. 따라서 저장 시각은 Unix 밀리초입니다.
- 독립 최소 스키마와 실제 6.1.1 스키마 양쪽에서 상태 보존·설정·JST 날짜 경계·병렬 변경·오류 롤백·알 수 없는 필드 유지·실제 마스터 참조를 테스트했습니다. 외부 스키마·마스터가 없는 fresh clone에서도 최소 스키마 테스트는 실행됩니다.

`Tutorial.StartQuest`, 활동 보상, 카드 육성, 가챠·구매 등 나머지 게임 로직은 이 모듈이 처리하지 않습니다. 준비된 fixture도 없으면 `UNIMPLEMENTED`를 반환합니다. 현재 튜토리얼 완료 표시는 전투·보상 계산의 구현을 뜻하지 않습니다.

## 다음 구현 근거

- 같은 버전의 `Reward.initial_user_reward`에는 기본 캐릭터 17명과 실제 3성 카드 17장 등이 있습니다. 위 홈 표시용 캐릭터 구성 이외의 카드·보상 지급 시점은 아직 확인하지 못했으므로 전체 보상은 자동 적용하지 않습니다.
- 덱의 신규 번호 발급·자동 편성·버디 대여와 캐릭터 그룹 장비 제한은 추가 계약·마스터 검증이 필요합니다.
- Android `LiveTutorialPresenter.RequestFullTutorialLiveAsync`의 `0x42f8664`에서 `Tutorial.StartQuestAsync` 호출을 확인했습니다. 응답에는 라이브 차트·스킬·사용자 정보가 필요합니다. `Setting`의 `qt-tutorial-short/full` 퀘스트만으로 빈 성공 응답을 만들 수는 없습니다.
- 부팅의 `OctoSetupAsync`와 홈의 3D 환경 로딩이 남아 있습니다. 원본 마스터 제공과 별개로 모델·음성 등 Octo 리소스의 보존·주소 연결을 구현하고 게임 기기에서 확인해야 합니다.
