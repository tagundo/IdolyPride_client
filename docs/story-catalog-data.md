# 공개 스토리 기본 목록

`Story.ListEvent`와 `Story.ListExtra`는 공식 새 계정에서 관측한 공개 기본 목록을 제공합니다. 기본 목록 버전은 `fresh-official-2026-10-25`, 형식 버전은 `1`입니다. 목록은 이벤트 55개·에피소드 272개와 특별 스토리 분류 3개·스토리 41개·에피소드 154개로 고정됩니다.

출처는 [Project-Hoshimi/sumire-sr-data](https://github.com/Project-Hoshimi/sumire-sr-data)의 고정 커밋 [`c40ea107b9cc8e53ae1705f82a5c39cc9fe3be02`](https://github.com/Project-Hoshimi/sumire-sr-data/tree/c40ea107b9cc8e53ae1705f82a5c39cc9fe3be02/captures/2026-10-25_fresh_official/raw)입니다. 이벤트 목록은 `00016.resp-plain.Story:ListEvent.bin`의 `infos`, 특별 목록은 `00033.resp-plain.Home:Enter.bin`의 `extraStoryPartInfos`에서 ID·에피소드 번호·해금 여부만 추출합니다. 전체 홈 응답은 저장하지 않습니다.

| 실행 파일 | 크기 | SHA-256 |
| --- | ---: | --- |
| `public-story/story-list-event.pb` | 2,898 | `830ce025b2866706bb5b26f7ab54d5b63c8d87b6c33623e8b4c465c32c4e9252` |
| `public-story/story-list-extra.pb` | 2,803 | `53972ca1710d59ca2d379e172ecda4d717edb0ab8627a08bd070793945ef925f` |

`public-story/manifest.json`은 기본 목록·스키마·마스터 버전과 원본 및 정제본의 해시를 기록합니다. 서버는 `EventStory`, `ExtraStoryPart`, `ExtraStory`, `Story` 마스터를 통해 부모 관계와 425개 Story 참조를 검증합니다. 새 마스터의 모든 항목을 자동 해금하지 않으며 일반 조건 평가 기능은 제공하지 않습니다.

두 RPC의 `CommonResponse.updatedData`와 `deletedData`는 명시적으로 존재하는 빈 메시지입니다. 읽음 상태는 별도의 `User.Get.stories`에서 유지됩니다. 목록 조회는 `UserStory`를 생성하거나 변경하지 않습니다. 현재 프로필의 응답 fixture가 우선하며, 홈에 기존 특별 스토리 목록이 있으면 그대로 유지합니다. 이 기능은 목록 조회 범위이며 스토리 읽기·보상 수령은 별도 구현이 필요합니다.

개발 빌드에서 공개 자료를 준비하려면 다음을 실행합니다. 일반 앱 사용자는 앱에 포함된 자료를 사용합니다.

```sh
uv run python tools/archive_story_catalog.py \
  --descriptor-set data/protocol/idolypride-6.1.1.pb \
  --output data/public-story
```

`--master-tag data/original-master/master-tag.json`으로 대상 마스터 버전을 명시할 수 있습니다. 생략하면 현재 검증된 마스터 `961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60`을 사용합니다. 도구는 기존 출력 디렉터리를 덮어쓰지 않습니다. 원본 다운로드는 이 명령을 명시적으로 실행할 때만 발생하며, 런타임 서버는 로컬 자료를 읽습니다.
