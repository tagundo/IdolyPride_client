# 튜토리얼 재생 데이터

`Tutorial.StartQuest`는 원본 short/full 시연 두 개를 재생합니다. 선택한 덱으로 새 전투를 계산하거나 일반 라이브 보상을 정산하는 기능은 아닙니다.

출처는 [Project-Hoshimi/sumire-sr-data](https://github.com/Project-Hoshimi/sumire-sr-data)의 고정 커밋 `c40ea107b9cc8e53ae1705f82a5c39cc9fe3be02`입니다. 해당 저장소는 계정 식별자를 가상 값으로 대체한 응답 자료를 공개합니다. 이 서버에는 원본 사용자·로그 식별자를 다시 제거한 두 응답만 포함하며 다른 프로젝트의 서버 구현은 복사하지 않습니다.

| 기록 | 원본 파일 | 차트 수 | 점수 | 추가 출연자 |
| --- | --- | --- | --- | --- |
| short | `captures/2026-10-25_fresh_official/raw/00026.resp-plain.Tutorial:StartQuest.bin` | 158 | 8,813 | 메이 |
| full | `captures/2026-10-25_fresh_official/raw/00028.resp-plain.Tutorial:StartQuest.bin` | 156 | 10,717 | 시즈쿠 |

두 기록의 시연 카드는 사쿠라·나기사·코토노·치사·레이의 기본 학교 의상 카드이며 모두 레벨 1입니다. 보유 카드와 저장된 덱은 변경하지 않습니다. 리소스 준비 단계에서 선택 덱과 시연·추가 출연자의 외형을 중복 없이 합칩니다.

보관 도구는 다운로드 크기·SHA-256·Git blob 해시를 확인한 뒤 새 응답을 만듭니다. 카드·스킬·숫자 인덱스·타임라인·점수·랭크 기준은 유지하고, 사용자 ID·이름·상세 로그 ID를 제거합니다. `isDisplayDetailAvailable=false`와 빈 `CommonResponse`를 사용합니다. 실행할 때는 로컬 `publicUserId`와 매니저 이름을 별도 사본에 연결합니다.

| 기록 | 원본 SHA-256 | 식별자 제거 후 SHA-256 |
| --- | --- | --- |
| short | `532c199a7fe2daaeedf7ba9cb0c28a988d4dc0e549bcfd30dadcdf274d56f8ae` | `719068e48099082fad71760d65a88047182be8b858a3586f33f87b812103fba7` |
| full | `0cd36f73aff5f733633528434a19af179797241f01195b0c4a2888d8736acd3c` | `29ecb24412bd6a2034a8b31803fcb34a8cd6b6632c2f0a96fe0319c15236d562` |

매니페스트는 추출 스키마와 마스터 버전을 함께 기록합니다. 패키지 생성과 실제 요청에서 현재 마스터의 차트 순서·능력치·스킬·외형·점수 합계를 검증합니다. 예상 해시·스키마·마스터와 다르면 재생을 거부합니다.

개발용으로 재생 자료를 준비하려면 추출 스키마와 검증된 마스터 태그가 있는 저장소에서 실행합니다.

```sh
python3 tools/archive_tutorial_replays.py \
  --descriptor-set data/protocol/idolypride-6.1.1.pb \
  --master-tag data/original-master/master-tag.json \
  --output data/public-tutorial
```

생성되는 파일은 `manifest.json`, `tutorial-short.pb`, `tutorial-full.pb`뿐입니다. 원본 응답은 메모리에서만 다루며 보관하지 않습니다. 일반 사용자용 APK와 Mac 앱에는 이 준비를 마친 자료가 포함됩니다.
