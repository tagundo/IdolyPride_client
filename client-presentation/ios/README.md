# PlayCover 그래픽 클라이언트

원본 일본판 iOS 6.1.1 빌드156을 대상으로 합니다. Android와 같은 그래픽 설정·촬영 및360 LIVE 표시 영역 확장 코어를 사용하지만, 함수 주소와 필드 배치는 iOS 원본에서 따로 검증했습니다. 프로필은 함수88개, 정적 게이트웨이31개를 고정합니다. Android 주소나 번들을 iOS에서 사용하지 않습니다.

서버 앱의 **MV 진입·종료 시 화면 회전 대기** 옵션은 Mac과 Android 모두 기본 켜짐이며, 이미 저장한 선택은 유지합니다. 켜면 원래 회전 안내와 완료 조건을 사용합니다. 끄면 휴대전화의 세로→회전 안내→가로 절차를 원래 방향 전환 작업으로 연결하며, 원본 작업의 취소 관리와 전후 콜백을 유지합니다. 이미 취소된 호출은 원본 경로를 사용합니다. 대기를 끈 전환은 원래 Unity 프레임이 두 번 진행되고 실제 화면 크기가 유효할 때 완료를 허용합니다. 전환 시작 때 옵션을 고정하므로 설정 변경이 진행 중인 작업을 중간에 바꾸지 않습니다. 화면·센서 전역 getter와 게임 시간은 변경하지 않습니다. 실제 PlayCover 실행 검증은 별도로 필요합니다.

일반·표정·라이브 촬영의 감상 세션, MV, 360 LIVE는 UI를 처음에 숨깁니다. 원래 UI 켜기 동작은 유지하며, 같은 세션에서 사용자가 켠 UI를 다시 강제로 숨기지 않습니다. 유료 촬영과 선택 메뉴에는 이 감상 UI 초기값을 적용하지 않습니다.

일반 MV와 360 LIVE는 시청에 들어갈 때 원본 UI 숨김 동작을 한 번 적용합니다. 이후 화면 탭이나 UI 표시 조작으로 다시 켤 수 있습니다. 360 LIVE의 표시 영역 확장을 켜면 UI 표시 버튼은 왼쪽 위, 종료는 왼쪽 아래, 카메라 버튼과 전체 메뉴는 오른쪽 아래로 옮깁니다. 기존 여백과 원본 클릭 동작을 유지하고, 확장을 끄거나 장면을 나가면 원래 위치로 복원합니다.

서버 앱과 클라이언트 IPA는 별도 파일로 배포합니다. IPA를 PlayCover에 가져오면 PlayCover가 앱과 내장 dylib를 변환·다시 서명합니다. 별도 번들ID `game.qualiarts.idolypride.local`을 사용합니다. 원본 앱과 기존 계정 데이터를 삭제할 필요가 없습니다.

클라이언트는 `127.0.0.1:8080/client/presentation`에서 공개 표시 설정만 받습니다. 실제 적용은 Unity의 게임 스레드에서 하고, 적용 리비전·지원 여부·화면과 렌더 타깃 크기·실제 투영 시야를 보고합니다. 설정 저장만으로 적용 완료를 표시하지 않습니다. 계정 데이터나 인증 백업은 읽지 않습니다.

회전 대기는 별도 `GET /client/playback`의 세 필드 설정을 사용합니다. `POST /client/playback/status`는 클라이언트가 설정을 수신했는지만 보고하며 MV 재생이나 회전 완료를 뜻하지 않습니다. 기존 열 필드 그래픽 설정 형식은 유지합니다. 서버가 이 API를 지원하지 않거나 응답이 잘못됐으면 마지막 유효 설정과 플랫폼 기본값을 유지합니다.

4:3에서는 원래16:9의 좌우 범위를 유지하면서 위아래를 더 표시합니다. 물리 카메라의 초점거리 갱신도 처리하고 실제 투영 행렬의 네 가장자리 포함 여부를 확인합니다. 카메라 위치·화면UV·투영 행렬 자체는 변경하지 않습니다. 장면을 나가거나 기능을 끄면 원래 렌즈·표시 영역을 복원합니다. 고정 영상인 MV 자체의 바깥 장면을 새로 만들지는 않습니다.

Mac에서 카메라의 센서·게이트·렌즈 시프트가 바뀔 때 원래 비율의 투영을 같은 콜백 안에서 측정하고 즉시 ResetAspect로 자동 비율을 복원합니다. 이 측정 때문에 렌더 타깃을 16:9로 되돌렸다가 다시 만드는 반복을 없앴습니다. 투영 검증에 실패하면 설정이나 화면 크기가 바뀌기 전까지 반복 재생성을 중단합니다.

빌드는 Clang과 Darwin LLD가 있는 Linux에서도 가능합니다. Apple SDK를 포함하지 않으며 필요한 공개 Darwin C ABI만 선언합니다. 실행 중 코드 페이지를 수정하지 않고, IPA 패키징 시 검증된 빈 영역에 게이트웨이를 만듭니다. 런타임은 UUID·원본 함수 바이트·게이트웨이와 포인터 공간을 확인한 뒤 활성화합니다.

```sh
python3 tools/prepare_ios_presentation.py --help
python3 client-presentation/ios/build_native.py \
  --llvm-bin /path/to/llvm/bin \
  --profile-header client-presentation/ios/ios_profile.hpp \
  --output /path/to/IdolyPresentation.dylib
python3 tools/patch_ios_client.py /path/to/original.ipa \
  --output /path/to/IdolyPride-6.1.1-Local-PlayCover.ipa \
  --presentation-library /path/to/IdolyPresentation.dylib \
  --presentation-plan client-presentation/ios/hook-plan.json
```

옆의 `.build.json`은 실제 dylib 해시와 프로필 헤더 해시를 묶습니다. 패키저는 로컬 로그인 패치, Octo의 로컬 리소스 경로, iOS 원본 Unity HTTP 정책, 그래픽 라이브러리를 함께 검증합니다. 원본 IPA와 생성 바이너리는 소스 저장소에 커밋하지 않습니다.

CPU 투영 회귀 검사, 원본 함수·필드·게이트웨이·Mach-O 서명 검사는 실제 Mac에서의 앱 실행이나 게임 화면 검증을 대신하지 않습니다.
