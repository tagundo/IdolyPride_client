# 검증 상태

2026-11-14 서버 메뉴를 먼저 표시하는 통합 IPA 시험판을 생성하고, 실제 Apple SDK 빌드와 새 iOS Simulator 검사를 통과했습니다.

- 빌드 소스: `063f23ab8104f8ae9afa499378141a4ce4e324b7`
- 빌드 버전: `156.9102`
- [성공한 Actions 실행](https://github.com/tagundo/IdolyPride_client/actions/runs/43594213861)
- [검증된 IPA 다운로드 브랜치](https://github.com/tagundo/IdolyPride_client/tree/downloads/ios-unified-prototype-source-063f23ab8104f8ae9afa499378141a4ce4e324b7)
- 파일: `IdolyPride-6.1.1-Unified-iOS-ko.ipa` / 477,732,774 bytes
- SHA-256: `307f737bd973723e0d79249c6b224b4b71e09c51d4af9d9c42e9e904c3a3ab9c`

## 통과한 검사

기본 검사 234개와 하위 검사 3개, 휴대용 모서리 영역·시작 대기·HTTP 정책 검사를 통과했습니다. Xcode 16.4 / iOS SDK 18.5로 기기용 arm64 프레임워크와 시뮬레이터용 프레임워크를 빌드했습니다. Python과 표준 확장 모듈의 실제 Mach-O 플랫폼·의존성·서명, 기존 게임 코드·SDK·리소스 보존, 완성 IPA 전체 멤버의 SHA/CRC를 확인했습니다.

새 iPhone 16 Pro / iOS 18.5 Simulator와 새 로컬 저장소에서 다음을 확인했습니다.

- 준비 전 게임 시작 요청을 무시하고, 서버가 준비된 후에도 1초 이상 서버 메뉴에 머무르며 Unity를 시작하지 않음.
- 실제 보이는 ‘게임 시작’ 버튼의 활성화와 UIKit 액션 전달. 사용자가 누른 뒤에만 검사용 AppDelegate의 Unity 시작 진입점을 메인 스레드에서 정확히 한 번 호출하고, 중복 요청을 무시하며 서버 메뉴를 숨김.
- 실제 게임 창에 이름으로 구분한 제스처가 하나 등록됨. 한 손가락·3초·12pt 허용 이동·델리게이트 연결·짧은 터치 지연 없음·인식 후 취소 설정을 확인. 안전 영역의 오른쪽 위 64pt 계산은 휴대용 검사 17개로 확인.
- 네이티브 CommonCrypto의 NIST 128/256 비트 벡터. Python 작업 스레드 경계에서는 128 비트 암호화·복호화와 잘못된 IV 거부.
- 실제 암호화 H2 요청·응답으로 `System.Check`, 새 `Auth.Login`, `Home.Enter` 성공.
- 리소스 서버의 호스트 루프백 연결과 검사 후 생성한 Simulator 종료·삭제. 최종 실행의 앱 실행 명령은 시간 초과 없이 완료.

실제 macOS AppKit에서도 서버 설정 메뉴의 대상·액션, 합성 키 이벤트를 통한 ⌘⇧, 전달, 제거한 메뉴 복원과 메뉴 교체 시 중복 방지를 확인했습니다. 기기용 프레임워크에는 AppKit 의존성을 추가하지 않습니다.

Actions ZIP 전체를 API가 제공한 SHA-256으로 검증한 다음 IPA를 스트리밍 추출했습니다. IPA 전체 SHA, 빌드 소스 파일 해시, 입력 데이터 핀, 원본 SDK 보존 보고서를 대조했습니다. 배포된 LFS 객체도 전체 재다운로드 SHA 검증을 통과했습니다.

## 남은 검증

iPhone·iPad 실기기의 실제 게임·MV 재생·성능과 PlayCover 실행은 아직 검증하지 않았습니다. 모서리 길게 누르기는 등록 설정과 영역 계산을 검증했으며 실제 손가락·마우스로 메뉴를 여는 동작은 미검증입니다. Simulator의 가짜 Unity 진입점 결과는 서버 코어와 시작 흐름 검사이며 실제 Unity 공연 실행 검사가 아닙니다. 기기 설치에는 개인 서명이 필요합니다. 선택적인 실험용 Go 라이브 시뮬레이터는 이 iOS 이식에 포함하지 않았습니다.
