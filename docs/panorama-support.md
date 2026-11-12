# 360 LIVE 감상 모드

v0.3.6의 별도 감상 계정에서 `PhotoPanorama.List`와 `PhotoPanorama.CheckShooting`을 지원하며, v0.3.8에는 MELODIES를 더한 15곡을 제공합니다. 원본의 360 LIVE 메뉴는 `MenuIconButtonType.Panorama(51) → FeatureLockType.Panorama(32) → FunctionLockType.PhotoPanoramaShooting(49)` 경로입니다. 일반 촬영·영상 MV의 `Photo.ListShooting` 목록과 구분합니다.

메뉴 조건 `cd-photo_panorama_music-start`의 첫 설정은 두 번째 메인 지역 클리어와 2025-06-23 15:00 UTC 이후를 요구합니다. 설정 목록은 OR이고 각 설정 안은 AND입니다. 현재 시각에서는 감상 계정의 `area-main-002.clearQuestCount=3`으로 촬영·360 LIVE 메뉴 조건을 모두 만족하며 티켓을 추가하지 않습니다. 개별 라이브 결과·점수·보상·기본 계정 데이터는 생성하거나 변경하지 않습니다.

목록은 실제 `Music`·`Stage`와 대조한 15곡을 순서대로 해금 상태로 제공합니다. 곡·자산·스테이지·카메라는 실제 마스터를 사용합니다. v0.3.8은 `music-hsm-017`의 단일 지정 스테이지 `stage-live-dome-03-00`, 공개 시각·5인 편성·카메라를 원본 마스터에서 직접 확인했습니다. 실제 SDK에도 `hsm-017-360` timeline·layout·5인 모션이 있습니다. 감상 목록의 표시·해금 조건 ID는 비웁니다. `Music.displayCharacterAmount`에 따른 3~6명 편성, 캐릭터·의상·헤어 보유와 착용 호환성을 확인합니다. 곡 ID는 원본 확인 요청의 `photoMusicId`에 전달합니다.

목록·확인은 DB·필름·포토·예약 ID·보상을 변경하지 않습니다. `PhotoPanorama.CreateShootings`, 이미지 업로드와 실제 포토 생성은 별도 미지원 범위입니다. 기존 45개 JSON 데이터 묶음으로 동작하며 일반 계정의 획득 조건을 해석하는 기능은 추가하지 않습니다.

기존 14개 곡·스테이지·순서·조건의 사실 자료는 [solis-server의 고정 공개 카탈로그](https://github.com/vertesan/solis-server/blob/9b67c06939403d7035e1795745f791340a775868/internal/server/rpc/servers/photo_panorama/catalogdata/photo_panorama.yaml)에서 확인했습니다. 파일 SHA-256은 `3cbd0d5d2b332aaae31370425b995e4c4ef165e32811ae7060a924e690cb68a1`입니다. 이는 공식 API 캡처가 아닌 공개 참고 자료입니다. 추가 MELODIES의 근거는 이 보조 카탈로그가 아닌 원본 `Music.selectableStageIds`입니다. 해당 프로젝트는 AGPL-3.0이며 처리 코드는 복사하지 않고 원본 클라이언트·복구한 protobuf와 마스터를 근거로 독립 구현했습니다.

원본 `PanoramaCharacterSelectSheetModel.SetMusicAndCameraData`의 RVA `0x591b550`과 확인 요청 생성 `0x5925618`에서 인원수·곡 ID 계약을 확인했습니다. 실제 마스터를 사용하는 임시 서버 검사에서 목록 14곡과 각 곡의 유효 편성을 확인하고 기본 DB·선택·읽음 기록·잔액 보존 및 재시작을 검사했습니다. 이 API 검사는 게임의 실제 360 장면 재생 완료 검증과 구분합니다.
