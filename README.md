# Android 의상룸 복귀 지연 점검 v0.3.20

서버와 연결용 클라이언트를 각각 업데이트합니다. 기존 앱·계정·리소스를 삭제하지 않습니다.

- [서버 APK](IdolyPride-Local-Server-Android.apk)
- [진단 게임 APK](IdolyPride-Local-Graphics-Diagnostic-Android-arm64.apk)
- [SHA256SUMS](SHA256SUMS) · [검증 범위](RELEASE-VERIFICATION.json)

37초 지연의 실제 원인은 아직 확정되지 않았습니다. 변경 없는 스냅샷의 디스크 쓰기를 제거하고, 종료 단계별 실제 동기 처리·경과 시간과 서버 RPC 처리·작업 대기 시간을 기록합니다. 측정값이 Java 전송부에서 버려지던 형식 호환성도 수정했습니다.

업데이트 후 서버의 **진단 게임 실행**으로 열고 의상룸 종료를 한 번 재현합니다. 캐릭터 선택창으로 돌아온 뒤 **진단 기록 내보내기**로 저장합니다. 기다리는 동안 게임을 전면에 둡니다.

[상세 측정 범위](https://github.com/tagundo/IdolyPride_client/blob/main/docs/wardrobe-exit-latency.md). 실제 폰에서 지연이 줄었는지는 미확인입니다. Mac 배포는 v0.3.19를 유지합니다. 비공개 저장소이므로 GitHub 로그인 후 파일 페이지의 **Download raw file**을 사용합니다. 첨부 업로드 인증과 Actions 사용 한도 때문에 앱은 이 다운로드 브랜치에서 제공합니다.
