# 검증 상태

2026-11-14 기준 통합 IPA **소스 구현**을 완료했습니다. 설치 가능한 IPA와 실제 기기 호환성은 아직 검증하지 못했습니다.

- Linux에서 호스트 수명·암호화 H2 통신·패키징·시작 대기·설정 경계의 집중 검사 122개와 하위 검사 3개가 통과했습니다.
- 기존 서버 데이터 전체를 사용한 별도 Linux 검사에서 기본 한국어/해금 모드, 암호화된 System.Check·Auth.Login·User.Get, 설정 HTTP 경로와 종료를 확인했습니다. 이는 iOS 실행 검사가 아닙니다.
- 실제 Apple SDK 빌드와 새 iOS Simulator 검사를 요청한 [Actions 실행](https://github.com/tagundo/IdolyPride_client/actions/runs/43577808882)은 실행 단계가 시작되기 전에 중단됐습니다. GitHub의 오류는 다음과 같습니다.

> The job was not started because recent account payments have failed or your spending limit needs to be increased. Please check the 'Billing & plans' section in your settings

이 환경은 Linux이며 별도의 Mac/Xcode 실행 연결이 없습니다. 따라서 Apple SDK 컴파일, 시뮬레이터 실행, iPhone·iPad MV 재생과 PlayCover 실행이 통과했다고 주장하지 않습니다. Actions 계정 문제가 해결되면 `ios_unified=true`로 재실행하거나, Mac에서 `build_on_mac.command`로 동일한 빌드와 검사를 실행할 수 있습니다. 기존 v0.3.31 배포 파일은 변경하지 않았습니다.
