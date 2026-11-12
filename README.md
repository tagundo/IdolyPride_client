# Android 360 LIVE 화면·UI 수정 v0.3.18

이 폴더의 APK는 Android 그래픽 진단 클라이언트 수정판입니다. 기존 아이프라 진단에 업데이트 설치합니다. 서버 v0.3.17을 그대로 사용하며 앱 삭제·데이터 초기화는 필요 없습니다. 게임을 완전히 종료한 뒤 업데이트하고 서버의 진단 게임 실행으로 여세요.

- Android 물리 카메라 변경·투영 실패 때 렌더 타깃을 반복 재생성할 수 있던 경로를 수정했습니다.
- 화면 확장 중 360 LIVE의 UI 표시·종료·카메라 버튼과 카메라 선택 팝업을 실제 촬영 화면 가장자리에 배치합니다.
- 같은 호출 안의 좌표 변환을 공유합니다. 일반 3부모 배치는 14회에서 11회로 줄고, 기존 표시 영역과 같으면 0회입니다. 원래 UI의 재배치·객체 수명 검사와 사용자 UI 켜기 선택은 유지합니다.
- 멀티스레드 시작 실험은 기존 서버 설정을 유지합니다. 사용자 제공 v0.3.17 기록에서 실제 MultiThreaded(2)·Vulkan(21)을 확인했지만 꺼짐과의 성능 비교는 없습니다.

원본 Android 6.1.1 함수 접두부 85개·훅 29개·JNI 6개, 기존 인증서와 원본 런타임 보존을 확인한 빌드입니다. 통합 호스트 검사 72개와 조건부 컴파일 수정 후 관련 검사 37개를 통과했습니다. 실제 기기의 깜빡임 소멸·버튼 표시·FPS 개선은 아직 확인하지 못했습니다.

소스: https://github.com/tagundo/IdolyPride_client/commit/07fb6283001b061cc46f6b261de3ae6535b46026

상세 안내: https://github.com/tagundo/IdolyPride_client/blob/main/docs/android-360-presentation-fix.md

서버 v0.3.17: https://github.com/tagundo/IdolyPride_client/tree/downloads/android-mt-v0.3.17

파일 페이지의 Download raw file로 받습니다. SHA256SUMS에서 파일 해시를 확인할 수 있습니다.
