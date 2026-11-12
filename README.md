# v0.3.19 앱 다운로드

서버와 해당 게임 클라이언트를 **각각** 업데이트합니다. 기존 앱과 데이터를 삭제하지 않습니다. 비공개 저장소이므로 GitHub에 로그인한 뒤 파일 페이지의 **Download raw file**로 받습니다.

| 기기 | 서버 | 클라이언트 |
| --- | --- | --- |
| Android | [서버 APK](IdolyPride-Local-Server-Android.apk) | [연결용 APK](IdolyPride-Local-Graphics-Diagnostic-Android-arm64.apk) |
| Mac | [서버 앱 ZIP](IdolyPride-Local-Server-macOS-arm64.app.zip) | [PlayCover IPA](IdolyPride-6.1.1-Local-PlayCover.ipa) |

[초기 서버 데이터 ZIP](IdolyPride-ServerData-v0.3.19.zip)은 앱에도 동봉되어 있으며 수동 설치·개발용입니다. 전체 CDN 리소스는 별도입니다.

[SHA256SUMS](SHA256SUMS) · [서명·원본 보존·다운로드 검증 기록](RELEASE-VERIFICATION.json) · [기능·Downloads 보관·번역 범위](https://github.com/tagundo/IdolyPride_client/blob/main/docs/local-library-v0.3.19.md)

기본 리소스 위치는 `Downloads/IdolyPride/` 아래 `octo-cache/`(Android), `octo-cache-ios/`(iOS), `exports/`(선택적 ZIP)입니다. 게임의 요청과 전체 받기가 같은 캐시를 사용합니다. Android11 이상에서 직접 보관하려면 파일 관리 권한을 허용합니다. 계정·설정은 앱 데이터 폴더에 유지합니다.

다섯 파일 모두 전체 원격 다운로드의 SHA-256을 확인했습니다. GitHub 첨부파일 업로드는 인증 오류, GitHub-hosted Actions는 계정 결제/사용 한도로 차단되어 파일을 이 다운로드 브랜치에서 제공합니다. 릴리즈 첨부파일을 업로드했다고 주장하지 않습니다. 실제 휴대폰·Mac 동작과 성능의 최종 재검증은 별도입니다.
