# 보유 의상·헤어 선택

`Appearance(schema, state, profile, master_dir)`는 다음 6.1.1 RPC만 처리합니다. 새 의상·헤어·캐릭터를 지급하거나 해금하지 않습니다.

| RPC | 요청 | snapshot 변경 |
| --- | --- | --- |
| `Costume.SetCostume` | `costumeId`, `hairId` | 해당 `UserCharacter.favoriteCostumeId`, `favoriteHairId` |
| `Costume.SetLiveCostume` | `costumeId`, `hairId` | 해당 `UserCharacter.liveCostumeId`, `liveHairId` |
| `Costume.CheckCostume` | `costumeId` | 보유 `UserCostume.checked=true` |
| `Hair.CheckHair` | `hairId` | 보유 `UserHair.checked=true` |
| `Costume.CheckBulk` | `costumeIds[]`, `hairIds[]` | 요청한 보유 행의 `checked=true` |

의상과 헤어는 같은 캐릭터의 실제 마스터 행이어야 하며, 선택 시 캐릭터·의상·헤어를 모두 소유해야 합니다. `Character`, `Costume`, `Hair`는 기존 묶음에 포함되어 있습니다. 호환성은 원본 `Hair.IsWearableCostume`의 규칙을 사용합니다. 두 목록이 모두 비면 허용하며, 그렇지 않으면 허용 목록에 있거나 비어 있지 않은 제외 목록에 없는 경우 허용합니다. 두 목록이 함께 있을 때도 이 OR 규칙을 유지합니다.

빈 ID·없는 마스터 ID·다른 캐릭터의 조합·착용 불가능한 조합은 `INVALID_ARGUMENT`, 알려진 장비나 캐릭터를 소유하지 않았으면 `PERMISSION_DENIED`입니다. 중복되거나 손상된 보유 행·잘못된 마스터 참조·다른 스키마의 snapshot은 `FAILED_PRECONDITION`으로 거부합니다. 일괄 요청의 중복 ID는 처음 나온 순서로 한 번만 처리하고, 하나라도 유효하지 않으면 전체를 저장하지 않습니다. 두 배열이 모두 빈 일괄 확인은 빈 `CommonResponse`를 반환하며 snapshot을 읽거나 저장하지 않습니다.

응답은 `CommonResponse`만 포함합니다. 선택은 해당 캐릭터 행, 확인은 요청한 의상·헤어 행만 `updatedData`로 반환하며 `deletedData`는 비어 있습니다. 재요청은 현재 행을 반환하고 추가 상태 변경은 하지 않습니다. 선택 동작은 기존 `checked` 값을 바꾸지 않습니다.

모든 변경은 기존 `State.mutate_snapshot`의 단일 SQLite 트랜잭션을 사용합니다. 골드·스톤·보상·인벤토리 수량·획득 시각·덱 배치·홈 배치·튜토리얼은 변경하지 않습니다. 프로필 식별자·세션·설정·레슨 시간·다른 프로필과 알 수 없는 protobuf 필드도 유지합니다. 라이브 기본 외형을 바꿔도 명시적으로 저장된 덱 외형은 덮어쓰지 않습니다.

신규 기본 계정은 현재 17명의 기본 의상·헤어만 소유합니다. 이 API는 대체 외형을 새로 만들지 않습니다. 가져온 계정의 보유 외형이나 이후 정상적으로 획득한 외형도 같은 소유·호환성 검사를 거칩니다.

## 원본 근거

원본 Android 6.1.1의 `libil2cpp.so` SHA256은 `68d4706d14b33d07647b9752124632a44b6a5901c82723beb569d9123df676b3`, metadata SHA256은 `f03b65e71c07648215ae18d6bb787462f2b049c45212f379eaa9ea05f8ba874e`입니다.

- `CharacterCostumeScreenPresenter.SetCostumeRequestAsync`의 상태 머신 `0x537b468`은 모드 0에서 `SetCostumeAsync`를 `0x537b7dc`, 모드 1에서 `SetLiveCostumeAsync`를 `0x537b6cc`에 호출합니다. 선택한 보유 의상·헤어의 ID를 전달합니다.
- 모델의 `GetTargetCostume`(`0x5371544`)과 `GetTargetHair`(`0x5371634`)는 보유 컬렉션에서 선택을 찾으며, 후자는 `Hair.IsWearableCostume`(`0x4e47994`)를 사용합니다. 같은 규칙은 기존 `live_assets._wearable`에서 재사용합니다.
- 개별 확인 호출부 `0x5373a70`·`0x53735b8`은 확인 상태를 true로 기록합니다. 실제 `UserCostume.set_Checked`(`0x47a4d6c`)와 `UserHair.set_Checked`(`0x47a761c`)는 Boolean 필드만 씁니다.
- 일괄 확인 상태 머신 `0x53752b4`는 캐릭터에 해당하는 보유 의상·헤어 ID를 모아 `0x5375638`에서 `CheckBulkAsync`를 호출하며, 빈 배열을 제외하는 분기는 확인되지 않았습니다.
- 실제 descriptor의 요청·응답과 `UserCharacter`·`UserCostume`·`UserHair` 필드를 대조했습니다. 공개 공식 자료에서 이 다섯 응답의 캡처는 찾지 못했으며, 캡처의 계정 상태를 복사하지 않았습니다.

최소 독립 스키마와 실제 6.1.1 descriptor에서 대체 보유 의상·헤어 선택, 재시도·재시작·동시 선택, 소유·중복·호환성 오류, 일괄 실패의 롤백, unknown 필드와 계정 보존을 검사합니다. 암호화 HTTP/2 테스트는 실제 Application의 인증·fixture 우선순위와 상태 변경을 검증합니다. 이 자동 검사는 실제 기기의 화면에서 옷을 바꿨다는 의미는 아닙니다.
