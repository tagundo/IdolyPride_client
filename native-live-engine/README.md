# 일반 라이브 계산 라이브러리 기반

`live-v5` 계산 엔진과 C ABI 어댑터의 최소 소스입니다. **명시적인 로컬 규칙이며 공식 서버와 점수가 같다는 검증은 없습니다.** 현재 서버·Android 앱·macOS 앱에서 이 모듈을 불러오지 않습니다. 일반 `Quest.Start`, 재화 정산, 퀘스트 진행 저장도 연결하지 않았습니다.

원본은 [vertesan/solis-server](https://github.com/vertesan/solis-server/tree/9b67c06939403d7035e1795745f791340a775868) 커밋 `9b67c06939403d7035e1795745f791340a775868`입니다. Go 엔진 12개·embed YAML 3개·생성 protobuf 4개를 수정 없이 보존했습니다. [source-manifest.json](source-manifest.json)은 이 19개 파일과 원본 LICENSE의 해시, 별도 작성한 어댑터 해시를 기록합니다. `papi_grpc.pb.go`, DB·HTTP·gRPC 서버·인증 코드는 포함하지 않습니다.

원본 AGPLv3 [LICENSE](LICENSE)·[NOTICE](NOTICE)와 [외부 의존성 고지](third-party-licenses/)를 유지합니다. 어댑터는 AGPL-3.0-or-later입니다. 외부 Go 모듈은 `google.golang.org/protobuf v1.36.12`, `go.yaml.in/yaml/v3 v3.0.5`뿐입니다.

## 확인한 범위

- Linux amd64 공유 라이브러리를 `ctypes`와 C 프로그램에서 실제 호출했습니다.
- 공개 마스터로 준비한 첫 퀘스트 입력은 4,781점·성공, 능력치를 0으로 바꾸면 0점·실패였습니다. 차트 183개·beat 855개와 누적 점수 보존을 확인했습니다.
- 동일 seed·입력의 결과가 반복·병렬 호출에서 일치했습니다. 잘못된 입력, 미지원 정의, 오류·결과 버퍼 해제도 검사했습니다.
- NDK 26.3.11579264/API 26으로 Android arm64 교차 빌드와 16KB ELF LOAD 정렬을 확인했습니다. Android 기기·Chaquopy 로딩과 macOS 빌드는 아직 검증하지 않았습니다.
- 기존 원본 순수 테스트는 최상위 23개·하위 90개를 통과했습니다. 이는 로컬 규칙 검증이며 공식 점수·계정 정산 검증이 아닙니다.

소스 동일성과 기존 실행 증거의 요약은 [docs/proof.json](docs/proof.json)에 있습니다. 바이너리·SDK·입력 마스터·계정 자료는 이 폴더에 커밋하지 않습니다.

## 빌드

Python 표준 라이브러리만으로 소스 해시를 확인할 수 있습니다.

```sh
python3 native-live-engine/scripts/build.py --verify-only
```

실제 Go 1.27.3 컴파일러와 C 컴파일러가 필요합니다. `--go` 또는 `IDOLY_GO_BINARY`로 위치를 선택합니다. 일부 환경의 `/usr/bin/go`는 바둑 프로그램이므로 `go version`을 확인해야 합니다. 이 스크립트는 다른 프로그램을 선택하면 오류로 종료합니다. Go 의존성은 첫 빌드 시 내려받을 수 있으며 SDK나 Go 자체를 설치하지 않습니다.

```sh
python3 native-live-engine/scripts/build.py --target linux \
  --go /path/to/go1.27.3/bin/go \
  --output /tmp/idoly-live/linux --cache /tmp/idoly-live/cache

python3 native-live-engine/scripts/build.py --target android \
  --go /path/to/go1.27.3/bin/go \
  --ndk /path/to/android-ndk/26.3.11579264 \
  --output /tmp/idoly-live/android-arm64 --cache /tmp/idoly-live/cache
```

Android 교차 빌드는 Linux x86_64 호스트와 해당 NDK를 대상으로 합니다. `libidoly_live.so`, 생성 헤더, `build-report.json`을 출력합니다. 기본 출력은 이 폴더의 무시되는 `build/` 아래이며, 예시는 저장소 밖에 출력합니다. `-mod=readonly`, `-buildvcs=false`, `-trimpath`를 사용하고 서버·DB 의존성이 생기면 거부합니다. Android에는 `-Wl,-z,max-page-size=16384`를 적용합니다.

## C ABI와 검증

공개 인터페이스는 [include/idoly_live.h](include/idoly_live.h), 구현은 [cmd/livebridge/bridge.go](cmd/livebridge/bridge.go)입니다.

```c
uint32_t IdolyLiveABIVersion(void);
int IdolyLiveSimulate(const void *json, size_t json_len,
                     void **result, size_t *result_len,
                     void **error, size_t *error_len);
void IdolyLiveFree(void *buffer);
```

ABI 버전은 1입니다. 성공은 압축·봉투 없는 `api.LiveResult` protobuf, 실패는 길이가 지정된 UTF-8 오류를 반환합니다. 상태 코드는 성공 0·잘못된 입력 1·미지원 정의 2·계산 시간 초과 3·내부 오류 4입니다. 입력은 복사하며 호출자가 소유합니다. 네 출력 인수는 유효하고 서로 다른 슬롯이어야 합니다. 반환 버퍼에는 NUL 종료를 가정하지 말고 각각 `IdolyLiveFree`로 한 번 해제합니다. Go 포인터는 외부로 반환하지 않습니다. 라이브러리는 프로세스 수명 동안 유지하고 서버를 멈출 때 `dlclose`하지 않습니다.

입력 JSON은 `input_version=1`, `seed`, `music_id`, 준비된 `cards`와 `proto` 배열을 받습니다. `proto` 값은 JSON 마스터가 아니라 **직렬화한 protobuf의 base64 배열**입니다. 필요한 키는 Quest·Setting·Chart·ReferenceChart·UserInfo·QuestPressure·QuestAudienceAdvantage·ComboAdvantage·QuestStaminaConsumption·Skill·SkillEfficacy·SkillTrigger·SkillTarget입니다. Chart는 `master.MusicChartPattern`, UserInfo는 준비된 `api.LiveUserInfo`입니다. 입력·출력은 최대 16MiB이며, 계산 루프의 제한 시간은 기본 10초입니다. 소유권·진행 조건·스키마 및 마스터 버전 검사는 최종 서버 어댑터가 담당해야 합니다.

[scripts/verify.py](scripts/verify.py)는 기존 공개 마스터 기반 스타터 입력을 받아 실제 C ABI를 검사합니다. 이 저장소에는 생성 입력 fixture를 포함하지 않으므로 해당 JSON과 6.1.1 descriptor를 별도로 준비해야 합니다. 일반 임의 덱 검증 도구가 아닌, 위에 기록한 고정 스타터 smoke입니다.

```sh
.venv/bin/python native-live-engine/scripts/verify.py \
  --library /tmp/idoly-live/linux/libidoly_live.so \
  --stock-input /path/to/prepared-stock-main-input.json \
  --project . --output /tmp/idoly-live/verification
```

`--expected-quest-start /path/to/prior-stock-quest-start.pb`가 있으면 기존 전체 타임라인과도 비교합니다. 없을 때 해당 비교를 했다고 기록하지 않습니다. C 헤더 검사 예제는 [tests/c_api_smoke.c](tests/c_api_smoke.c)입니다. 실행 산출물은 커밋하지 않습니다.

## 후속 서버 연결

현재 소유 덱·능력치·스킬·외형으로 입력을 준비하고, 결과와 실제 보상·진행 갱신을 한 트랜잭션에 저장해야 합니다. `Quest.Start`가 재생 결과와 정산을 모두 반환하며 `Quest.Finish`는 없습니다. SolisClient는 `x-app-request-id`에 tick 문자열을 보내므로, 후속 어댑터는 이 헤더와 동일 payload를 검증하고 attempt seed·시각·응답 cache·snapshot을 원자적으로 보존해야 재시도와 새 도전을 구별할 수 있습니다. 이 저장소 기반에는 해당 런타임 처리가 없습니다.
