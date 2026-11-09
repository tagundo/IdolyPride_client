# 로컬 게임 상태 구현 범위

`Gameplay`는 6.1.1 스키마와 같은 버전의 마스터를 사용합니다. 현재 구현은 부팅·홈 응답, 일부 사용자 설정·배치·튜토리얼·덱 상태의 보존입니다. 실제 게임 앱의 홈 진입·라이브 플레이를 검증한 상태는 아닙니다.

## 구현한 RPC

| RPC | 로컬 동작 | 저장되는 내용 |
| --- | --- | --- |
| `Home.Login` | 설정 수신·로그인 시각 갱신 | `SettingInfo`, `user.lastLoginTime`, JST 날짜별 `totalCount.loginCount` |
| `Home.Enter` | 마스터 기반 현재 메인 지역·홈 컨테이너 반환 | 읽기 전용; 보상·이벤트는 생성하지 않음 |
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

`Home.Enter`의 이벤트·활동·배너 컨테이너는 로컬 콘텐츠가 없다는 구조를 반환합니다. 급여·자동 보상·진행 중인 활동 결과를 만들어내지는 않습니다. 메인 지역 선택에는 `Area` 마스터가 필요하며 다른 지역 유형을 임의로 메인 지역으로 취급하지 않습니다.

## 신규 프로필의 시작 데이터

`seed_starter_profile(state, schema, profile, master_dir)`는 snapshot이 없는 프로필에서만 사용합니다. 기존 공식 계정 snapshot이나 이미 생성한 로컬 프로필에는 자동 적용하지 않습니다.

시작 캐릭터는 `Setting.tutorialPhotoShootingCharacterIds`에서 가져옵니다. 현재 마스터에서는 5명입니다. 이 목록은 촬영 튜토리얼의 대상이며, 여기서는 신규 로컬 프로필의 기본 편성으로 사용합니다. 공식 신규 계정의 전체 보유 목록을 재현한 것은 아닙니다. 각 캐릭터의 기본·라이브 의상과 기본 헤어를 실제 `Character`·`Costume`·`Hair` 소유 관계로 검증합니다. 캐릭터 활동 레벨 1의 최대 체력은 `CharacterActivityLevel`에서 가져옵니다. 최초 메인 지역의 퀘스트 참조도 검증합니다.

최소 데이터에는 레벨 1 매니저, 위 캐릭터·외형, 홈 배치, 빈 덱 하나와 GameStart step 0이 포함됩니다. 카드·통화·보상·라이브 클리어·기능 전체 해금은 지급하지 않습니다. 마스터 참조 검증이 실패하면 부분 snapshot을 남기지 않습니다.

사용하는 마스터 파일은 `Setting.json`, `Character.json`, `Costume.json`, `Hair.json`, `CharacterActivityLevel.json`, `Area.json`, `Quest.json`, `Tutorial.json`, `Card.json`, `Accessory.json`, `!version.txt`입니다. 번들의 정규 JSON은 protobuf 필드 이름과 숫자 enum을 사용합니다.

## 근거·검증

- 실제 6.1.1의 `api/home.proto`, `api/tutorial.proto`, `api/common_response.proto`, `transaction/user.proto`, `transaction/user_tutorial.proto` descriptor로 요청·응답 필드와 변경 목록을 확인했습니다.
- iOS native `UserTutorialCollection.IsFinished`의 `0x1e0d274`에서 GameStart 완료 조건 `step > 149`를 확인했습니다. 마스터에도 마지막 체크포인트 150이 있습니다. 다른 튜토리얼을 함께 완료시키지 않습니다.
- `TimeManager.GetDeviceNowUnixTime`의 `0x1d29230`은 UTC epoch 차이에 `TimeSpan.TotalMilliseconds`를 적용합니다. 따라서 저장 시각은 Unix 밀리초입니다.
- 독립 최소 스키마와 실제 6.1.1 스키마 양쪽에서 상태 보존·설정·JST 날짜 경계·병렬 변경·오류 롤백·알 수 없는 필드 유지·실제 마스터 참조를 테스트했습니다. 외부 스키마·마스터가 없는 fresh clone에서도 최소 스키마 테스트는 실행됩니다.

`Tutorial.StartQuest`, 활동 보상, 카드 육성, 가챠·구매 등 나머지 게임 로직은 이 모듈이 처리하지 않습니다. 준비된 fixture도 없으면 `UNIMPLEMENTED`를 반환합니다. 현재 튜토리얼 완료 표시는 전투·보상 계산의 구현을 뜻하지 않습니다.

## 다음 구현 근거

- 같은 버전의 `Reward.initial_user_reward`에는 캐릭터 17명과 실제 3성 카드 17장 등이 있습니다. 공식 지급 시점은 아직 확인하지 못했으므로 기존 snapshot에 자동 적용하지 않습니다. 향후 신규 로컬 프로필 정책으로 명시하거나 정상 응답에서 지급 시점을 확인해야 합니다.
- 덱의 신규 번호 발급·자동 편성·버디 대여와 캐릭터 그룹 장비 제한은 추가 계약·마스터 검증이 필요합니다.
- Android `LiveTutorialPresenter.RequestFullTutorialLiveAsync`의 `0x42f8664`에서 `Tutorial.StartQuestAsync` 호출을 확인했습니다. 응답에는 라이브 차트·스킬·사용자 정보가 필요합니다. `Setting`의 `qt-tutorial-short/full` 퀘스트만으로 빈 성공 응답을 만들 수는 없습니다.
- 부팅의 `OctoSetupAsync`와 홈의 3D 환경 로딩이 남아 있습니다. 원본 마스터 제공과 별개로 모델·음성 등 Octo 리소스의 보존·주소 연결을 구현하고 게임 기기에서 확인해야 합니다.
