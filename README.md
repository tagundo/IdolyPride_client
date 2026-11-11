# Android 서버 v0.3.6

[APK 직접 다운로드](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/local-server-v0.3.6/IdolyPride-Local-Server-Android.apk)

접근 권한이 있는 GitHub 계정으로 로그인해서 받으세요. 이 브랜치는 다운로드용이며 소스 main으로 병합하지 않습니다. 릴리즈 asset 업로드의 인증 오류 때문에 같은 비공개 저장소의 정상 Git 다운로드 경로로 제공합니다.

기존 서버 APK를 업데이트 설치하고 감상용 전체 해금을 유지한 채 서버를 시작한 뒤 게임 타이틀에서 다시 로그인하세요. 앱 삭제·데이터 지우기는 필요 없습니다. 기본 계정 DB와 감상 계정의 의상 선택·스토리 읽음 기록을 보존합니다.

촬영·360 LIVE 메뉴 조건을 감상 계정에서 준비하며, 360 LIVE 전용 목록 14곡과 곡별 3~6명 편성 확인을 지원합니다. 초기 희귀도 5 카드에 잘못 지정된 표시 형식 1을 필요한 경우 2로 보완해 Card.GetDisplayData 예외를 수정합니다. 카드 성장과 유효한 표시 선택은 유지합니다.

실제 마스터를 사용한 임시 서버에서 메뉴 조건, 14곡 목록·유효 편성 확인, 기존 계정 파일·선택·읽음 기록·잔액 보존과 재시작을 검사했습니다. 실제 360 장면 재생 완료 및 의상룸 Back 프리징 해결 여부는 아직 검증 범위와 구분합니다. 사진 생성/업로드와 새 Mac 바이너리는 포함하지 않습니다. 매핑 미확인인 music-hsm-017은 360 목록에서 제외합니다.

14곡 데이터의 출처 및 원본 조건은 main의 docs/panorama-support.md에 있습니다. SHA256SUMS와 RELEASE-VERIFICATION.json으로 파일과 검증 범위를 확인할 수 있습니다.
