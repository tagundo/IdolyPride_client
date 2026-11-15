# NPC의 3D 라이브 출연 가능성 조사

2026-11-15 기준으로 사토미와 `lmn`·`lim` 후보의 3D 모델 메타데이터를 확인했다. NPC 출연 기능은 활성화하지 않았으며 실제 댄스·표정·물리 동작의 호환성은 아직 검증하지 않았다.

## 검증 범위와 재현 정보

- [감사 도구](../tools/audit_npc_models.py), UnityPy `1.25.4`; Android 공개 Octo 카탈로그 revision `1087`.
- [Actions 실행 43716544403](https://github.com/tagundo/IdolyPride_client/actions/runs/43716544403), 소스 `05bae887d306d26b88a95e27349140941b322c85`.
- 도구 SHA-256: `85393300b5d6e3894daeeb2c107ab08ac8fee65caac0750b8fbed0f9d296ec13`.
- ServerData: `191,343,014`바이트, SHA-256 `37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223`.
- 결과 아티팩트 `14162508657`: ZIP `22,548`바이트, SHA-256 `7cac0dfb9490a9b408e9beb74c50fbe7bcf14d21d6da67154e9b36b63740df47`.
- 원본 12개, 합계 `59,949,526`바이트의 길이·MD5·SHA-256을 검증했다. 읽지 못한 대상 type tree는 0개였다. 모델·텍스처 원본은 이 문서에 포함하지 않는다.

GameObject, Transform, Animator, Avatar, SkinnedMeshRenderer, MonoBehaviour, MonoScript 메타데이터를 제한적으로 읽었다. Mesh 정점·bind matrix·blendshape 내용, 텍스처 픽셀, 실제 모션은 읽거나 실행하지 않았다. Android 모델 결과를 iOS 모델의 검증으로 확대할 수 없다. 주요 수치는 [요약 JSON](npc-mv-feasibility-evidence.json)에 기록했다.

## 대상과 관찰 결과

`data/master-json/Character.json`의 `char-stm`은 `assetId: stm`, 이름 `橋本さとみ`, 영문명 `SATOMI HASHIMOTO`이다. 사토미의 동일 인물 바인딩에는 마스터 근거가 있다. `lmn`→[大須賀れもん](https://idolypride.jp/gallery/tag/lemon/), `lim`→[小南来夢](https://idolypride.jp/gallery/tag/lime/)은 이름·리소스 접두어에 따른 강한 후보 매핑이다. 공개 이름 자료만으로 내부 ID 대응까지 입증되지는 않으며, 해당 후보의 시각 자료나 ADV 참조를 통한 확정이 필요하다.

| 대상 | body 리소스 | 고유 skin bone 이름 수 | 사쿠라와 공통 |
| --- | --- | ---: | ---: |
| 기준: 사쿠라 | `mdl_chr_skr-schl-00_body` | 78 | 78 |
| 사토미 | `mdl_chr_stm-idol-02_body` | 94 | 78 |
| 레몬 후보 | `mdl_chr_lmn-idol-00_body` | 70 | 62 |
| 라임 후보 | `mdl_chr_lim-idol-00_body` | 74 | 62 |

각 대상은 별도의 `mdl_chr_<ID>-base-00_face`와 `mdl_chr_<ID>-base-00_hair`도 검사했다. 기준 사쿠라의 의상·머리는 실제 `char-skr`의 `cos-skr-schl-00`·`hair-skr-schl-00` 참조에서 선택했다.

사토미에는 기준의 78개 bone 이름이 모두 있고 옷·리본 계열 16개가 추가된다. 레몬·라임 후보에서 빠진 기준 이름 16개는 모두 `Skirt*_S` 계열이며, 각각 셔츠 8개와 셔츠·체인 12개가 추가된다. 공통 62개에는 hips, spine, head, 팔·다리·손·손가락 이름이 포함된다. 따라서 총 bone 수 차이만으로 기본 인체 모션의 비호환성을 판정할 수 없다. 이름 일치는 부모 계층·rest transform·skin bind·Avatar 매핑 일치를 뜻하지 않는다.

네 body 모두 아래 9개 스크립트 클래스가 해석되었다.

```text
ActorSwing.ActorSwingBreastBone
ActorSwing.ActorSwingChain
ActorSwing.ActorSwingDynamicBone
ActorSwing.ActorSwingStaticBone
VL.IK.IKBodyEffector
VL.IK.IKGoalEffector
VL.IK.IKHintEffector
VL.IK.LookAtEffector
VL.VLActorExpressionBone
```

네 face 모두 SkinnedMeshRenderer 6개, skin bone 슬롯 18개·고유 이름 3개이며 `Solis.Common.SolisActorTalkModel`, `VL.VLActorEyeHighlight`, `VL.VLActorFaceTargetCorrection`을 공유한다. 라임 후보의 face에는 나머지 세 대상에서 보이는 `ActorSwingStaticBone`이 없다. 이 차이의 실제 영향은 확인하지 않았다.

## 증거의 한계

- 12개 번들 모두 Animator·Avatar가 없다. 동작하는 기준 사쿠라도 같으므로 NPC에만 필수 리그가 빠졌다고 결론 내릴 수 없다. 공용 actor root와 실행 시 제공되는 controller·Avatar 의존성을 별도로 확인해야 한다.
- Renderer의 blendshape weight 배열은 기준을 포함해 모두 비어 있다. Mesh의 blendshape 데이터를 읽지 않았으므로 표정 기능이나 blendshape가 없다는 증거가 아니다.
- 검사한 skin bone·스크립트 참조의 미해결 수와 외부 참조 수는 0이다. 재질·텍스처·공용 controller 등 모든 의존성을 추적한 결과는 아니다.
- 보고서의 `rig_name_markers`는 `Right`의 `rig` 부분도 일치시킨다. 리그 근거에는 이 검색 결과 수 대신 해석된 MonoScript 클래스를 사용한다.
- 현재 서버의 출연자 목록은 실제 카드 소유 캐릭터에서 만들어진다. 모델이 존재한다는 사실만으로 NPC가 선택되거나 정상 출연하는 것은 아니다.

## 다음 구현의 경계

첫 실험은 근거가 가장 많은 사토미로 한정한다. 기존 아이돌 슬롯을 유지한 채 감상용 3D 라이브·촬영의 외형 descriptor만 명시적으로 교체하는 방식이 적절하다. 일반 카드·소유권·성장 데이터에 NPC를 추가하기 전에 아래 조건을 확인한다.

1. 실제 descriptor 생성 함수의 ABI와 body·face·hair 순서, actor 초기화 완료 경로 및 공용 controller·Avatar 의존성을 확인한다.
2. 기준과 후보의 Transform 부모 계층·rest pose·skin bind matrix를 비교하고 의상별 ActorSwing·IK 초기화를 보존한다. 이름 변경이나 옷 bone 삭제로 차이를 감추지 않는다.
3. 알려진 모션 하나를 실제 적용해 전신·손·시선·입·의상·머리 물리, 장면 종료와 반복 로딩을 확인한다. 원격 메타데이터 감사는 이 실행 검증을 대신하지 않는다.
4. 외형·플랫폼·카탈로그 revision·원본 digest를 구별하는 캐시 식별과 해제 수명을 확인하고, 검증 실패 시 기존 외형으로 복귀하도록 한다. 언어·외형 전환 후 잘못된 모델이 재사용되지 않아야 한다.
5. 레몬·라임은 인물 ID 매핑을 먼저 확정하고 같은 검증을 각각 수행한다. iOS는 해당 플랫폼 번들로 따로 검증한다.

사전 렌더링 영상인 video MV의 출연자는 이 모델 교체 경로로 바꿀 수 없다. 이번 제안의 대상은 런타임 3D 라이브·촬영이다.
