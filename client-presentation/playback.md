# MV 화면 회전 대기 설정

재생 설정은 기존 그래픽 설정과 별도입니다. `/client/presentation`의 열 개 필드는 바꾸지 않습니다. 새 클라이언트는 `/client/playback`을 독립적으로 읽으며, 휴대폰의 기본값은 회전 대기 사용, 확인된 Mac 실행의 기본값은 회전 대기 해제입니다. 유효한 설정을 받기 전에는 이 기본값을 유지합니다.

`GET http://127.0.0.1:8080/client/playback`은 다음 세 필드만 반환합니다.

```json
{"schema":1,"revision":0,"wait_for_orientation":true}
```

`schema`는 정수 `1`, `revision`은 `0`부터 `9223372036854775807`까지의 정수, `wait_for_orientation`은 불리언입니다. 추가 필드·중복 필드·잘못된 타입은 거부합니다. 메시지는 UTF-8 기준 8192바이트 이하입니다. 이전 리비전과 같은 리비전의 다른 값도 네이티브 브리지가 거부합니다. GET 실패·404·잘못된 응답은 기본값이나 마지막으로 받은 유효한 설정을 변경하지 않습니다.

클라이언트는 네이티브 설정 수신 결과만 `POST /client/playback/status`로 보냅니다. 응답 기록의 필드는 정확히 다음 여섯 개입니다.

```json
{"schema":1,"bridge_version":1,"revision":0,"wait_for_orientation":true,"supported":true,"applied":true}
```

`supported`는 검증된 회전 후크의 준비 여부이고, `applied`는 지원되는 브리지가 해당 설정을 수신했다는 뜻입니다. 실제 회전이나 MV 시작·종료가 완료됐다는 뜻이 아닙니다. 진행 중인 전환은 시작할 때 선택한 동작을 유지하며, 변경한 설정은 다음 MV 진입·종료 전환부터 사용합니다. POST 실패는 이미 수신한 설정을 되돌리지 않습니다.

Android JNI는 `NativePresentation.configurePlayback(int, long, boolean)`과 `playbackStatus()`를 사용합니다. iOS 폴러는 같은 검증·리비전 규칙으로 `accept_playback_configuration()`과 `playback_status_json()`을 호출합니다. 두 플랫폼 모두 게임의 Unity 스레드에서 원본 회전 기능을 처리하며, HTTP 폴러가 Unity 함수를 직접 호출하지 않습니다.
