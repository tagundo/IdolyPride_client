# 릴리즈 버전과 파일명

다음 릴리즈부터 Elichika와 같은 날짜 버전 `YYYY.MM.DD.N`을 사용합니다.
날짜는 **Asia/Seoul** 기준이며 당일 첫 배포는 `.1`, 추가 배포는 `.2`처럼 올립니다.
회차는 1~99이고 월·일은 두 자리입니다. 존재하지 않는 날짜나 이미 사용한 태그는 거절합니다.

예시는 규칙 설명용이며 이 버전이 배포됐다는 뜻은 아닙니다.

| 대상 | 공개 파일명 예시 |
| --- | --- |
| Android 서버 | `IdolyPride-2026.11.16.1-Server-Android.apk` |
| Mac 서버 | `IdolyPride-2026.11.16.1-Server-macOS-arm64.app.zip` |
| 통합 IPA | `IdolyPride-2026.11.16.1-Unified-iOS.ipa` |
| Android 한국어 게임 | `IdolyPride-2026.11.16.1-Client-Android-arm64-ko.apk` |
| Android 일본어·영어 게임 | 위 이름에서 `ko` 대신 `ja`·`en` |
| 별도 PlayCover 게임 | `IdolyPride-2026.11.16.1-Client-PlayCover-ko.ipa` |

태그는 `v2026.11.16.1`, 릴리즈 이름은 `아이프라 로컬 2026.11.16.1` 형식입니다.
같은 릴리즈의 7개 공개 파일과 LFS 대체 주소에는 같은 날짜 버전을 사용합니다.
게임 원본 버전 6.1.1, 플랫폼의 업데이트 빌드 번호, 서버 엔진 버전은 별도 정보입니다.
기존 클라이언트를 재사용하면 공개 파일명만 해당 릴리즈 버전으로 바꾸며, 원래 버전·소스·전체 SHA-256을 보존하고 재제작으로 표시하지 않습니다.

## 배포 절차

1. 한국 날짜와 그날의 기존 공개 릴리즈를 확인해 버전 회차를 정합니다.
2. `python tools/release_identity.py --version 2026.11.16.1`로 태그와 7개 파일명을 미리 확인합니다. 이 명령은 게시하지 않습니다.
3. `release-all-platforms.yml`을 수동 실행하면서 `release_version`을 입력합니다. 검증만 할 때는 `publish=false`를 유지합니다.
4. 실제 배포는 `publish=true`로 실행하며 기존 여섯 QA 작업이 모두 통과해야 합니다.
5. 검증된 파일을 버전 파일명으로 게시 준비하고 다시 해시를 확인합니다. 원래 빌드 보고서의 파일명과 새 공개 이름을 증거에 함께 남깁니다.
6. 모든 공개 파일의 전체 다운로드 SHA-256, 파일 목록·태그·URL을 검증하고 다운로드 안내를 갱신합니다.

워크플로 파일을 수정하거나 push하는 것만으로 빌드·릴리즈를 게시하지 않습니다.
현재 v0.3.35 및 이전 릴리즈의 이름·태그·파일·다운로드 링크는 그대로 유지합니다.
이번 규칙 변경은 새 APK·IPA·Mac 앱의 배포가 아닙니다.

## 참고한 Elichika

- [실제 날짜 릴리즈 v2026.11.14.1](https://github.com/tagundo/elichika/releases/tag/v2026.11.14.1): `elichika-2026.11.14.1.apk`, `Elichika-2026.11.14.1-AppleSilicon.app.zip`
- [고정 소스의 날짜·회차 검증](https://github.com/tagundo/elichika/blob/02f659d707997e03218be231e8a675fb0358a6c8/android/ci/app_version.py)

Elichika의 날짜 형식을 참고하며 원본 게임의 앱 ID·서명·업데이트 번호를 그대로 가져오지는 않습니다.
