# 로컬 서버와 한국어 클라이언트 v0.3.31

Android와 Apple Silicon Mac용 로컬 서버를 새로 제작했습니다. 한국어 Android 클라이언트 APK와 Mac PlayCover IPA는 서버와 별도 파일입니다.

이 시험판은 한국어 UI와 이미지, 서버의 로컬 자료 처리를 수정합니다. Android 파일 이름의 Graphics-Diagnostic 표기는 기존 배포 이름을 유지한 것입니다. 설치 화면의 앱 이름은 별도로 정리했습니다.

네 파일은 모두 소스 `cba4b5a272d4e7033ec5a18223f737c37a749d8f`에서 새로 제작하고 실제 배포 파일의 독립 패키지 검사를 통과한 뒤 원격 저장소의 LFS 파일과 전체 SHA256을 대조합니다. 한국어 클라이언트 두 파일은 인증 헤더 없는 전체 다운로드도 검증합니다.

실제 Android 및 PlayCover 화면의 재생은 아직 검증하지 않았습니다. 모든 번역이 완료되었다는 뜻은 아닙니다. 이전 버전의 사용자 플레이 결과를 이 수정판의 검증으로 사용하지 않았습니다.

| 파일 | 용도 |
| --- | --- |
| `IdolyPride-Local-Server-Android.apk` | Android 로컬 서버 |
| `IdolyPride-Local-Server-macOS-arm64.app.zip` | Apple Silicon Mac 로컬 서버 |
| `IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk` | Android ARM64 한국어 클라이언트 |
| `IdolyPride-6.1.1-Local-PlayCover-ko.ipa` | Mac PlayCover 한국어 클라이언트 |

[다운로드 목록](https://github.com/tagundo/IdolyPride_client/tree/downloads/local-v0.3.31) · [SHA256SUMS](https://github.com/tagundo/IdolyPride_client/tree/downloads/local-v0.3.31/SHA256SUMS) · [배포 검증](https://github.com/tagundo/IdolyPride_client/tree/downloads/local-v0.3.31/RELEASE-VERIFICATION.json). 채팅에서 제공하는 임시 다운로드 링크는 별도이며 이 배포 기록에 저장하지 않습니다.

기존 계정·설정·다운로드 자료를 삭제할 필요는 없습니다. Mac IPA는 PlayCover에서 다시 서명해야 합니다.
