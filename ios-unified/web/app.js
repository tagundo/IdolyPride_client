(function (root) {
  "use strict";

  const MAX_ID = 2147483647;
  const MAX_PENDING = 16;
  const ACTIVE_JOBS = new Set(["preparing", "running", "export_ready", "cancelling"]);
  const LANGUAGES = {ko: "한국어", ja: "日本語", en: "English"};
  const INTERFACE_LANGUAGES = ["system", "ko", "ja", "en"];
  const SCALE_PRESETS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];
  const BUFFER_PRESETS = [720, 1080, 1440, 1920, 2560, 3840, 4096];
  const UI_TRANSLATIONS = {
  "en": {
    "IDOLY PRIDE 로컬 설정": "IDOLY PRIDE Local Settings",
    "서버 설정": "Server settings",
    "새로고침": "Refresh",
    "서버 상태": "Server status",
    "확인 중": "Checking",
    "기기에 저장된 설정을 불러옵니다.": "Loading settings saved on this device.",
    "변경한 감상 모드·언어·자동 받기는 다음 앱 실행부터 적용됩니다.": "Changes to viewing mode, game language and automatic downloads apply next time you open the app.",
    "감상 모드·언어": "Viewing mode and language",
    "저장 후 앱을 완전히 종료하고 다시 실행하면 적용됩니다. 일반 모드의 저장 자료는 따로 유지됩니다.": "Save, fully close the app, then reopen it to apply changes. Normal-mode save data is kept separately.",
    "감상 모드 · 전체 해금": "Viewing mode · Unlock all",
    "없는 리소스 자동 받기": "Automatically download missing resources",
    "게임 언어": "Game language",
    "한국어": "Korean",
    "다음 실행 설정 저장": "Save for next launch",
    "현재 적용 값 확인 중": "Checking active settings",
    "그래픽·촬영 화면": "Graphics and photography",
    "대기": "Waiting",
    "사용자 그래픽 설정": "Use custom graphics settings",
    "그래픽 품질": "Graphics quality",
    "원본": "Original",
    "최저": "Lowest",
    "낮음": "Low",
    "보통": "Medium",
    "높음": "High",
    "목표 프레임 수": "Target frame rate",
    "3D 렌더 배율": "3D render scale",
    "렌더 버퍼 최대 크기": "Maximum render buffer size",
    "가장자리 다듬기": "Anti-aliasing",
    "없음": "None",
    "캐릭터 그림자": "Character shadows",
    "촬영·360 화면 확장": "Expand photography and 360 view",
    "화면 확장은 그래픽 설정과 독립적으로 적용됩니다. 목표 프레임 수는 실제 성능을 보장하지 않습니다.": "View expansion is independent of custom graphics settings. The target frame rate does not guarantee actual performance.",
    "그래픽 설정 저장": "Save graphics settings",
    "게임 적용 상태 확인 중": "Checking settings applied in the game",
    "MV 재생": "MV playback",
    "화면 회전 후 재생 시작": "Wait for rotation before playback",
    "기본값은 켜짐입니다. 화면이 가로 방향으로 바뀔 때까지 기다립니다.": "Enabled by default. Waits until the screen turns to landscape.",
    "재생 설정 저장": "Save playback settings",
    "MV·의상 목록": "MV and outfit lists",
    "영상 MV 숨기기": "Hide video MVs",
    "MV 정렬": "MV order",
    "최신순": "Newest first",
    "오래된 순": "Oldest first",
    "이름순": "Name",
    "ID순": "ID",
    "의상 정렬": "Outfit order",
    "목록 설정 저장": "Save list settings",
    "목록 설정은 다음 앱 실행부터 적용됩니다.": "List settings apply next time you open the app.",
    "iOS 리소스 보관": "iOS resource storage",
    "받은 파일은 크기·MD5를 검증해 기기에 보관합니다. 중단 후 다시 받으면 검증된 파일을 재사용합니다.": "Downloaded files are checked by size and MD5 before storage. Resuming reuses verified files.",
    "동시 다운로드": "Parallel downloads",
    "1개": "1",
    "2개": "2",
    "4개 · 기본": "4 · Default",
    "8개": "8",
    "목록·용량 확인": "Check list and size",
    "전체 리소스 받기": "Download all resources",
    "서버 상태를 확인하고 있습니다.": "Checking server status.",
    "ZIP 가져오기": "Import ZIP",
    "ZIP 내보내기": "Export ZIP",
    "작업 취소": "Cancel task",
    "파일 앱에서 ZIP을 선택하거나 저장합니다. 내보내기에는 현재 보관된 파일만 포함됩니다.": "Choose or save a ZIP using the Files app. Exports include only files already stored.",
    "진단": "Diagnostics",
    "게임 진단 대기 중": "Waiting for game diagnostics",
    "상태·최근 기록 보기": "View status and recent logs",
    "기록 없음": "No logs",
    "설정은 이 기기에 저장됩니다.": "Settings are saved on this device.",
    "요청을 처리하지 못했습니다.": "Could not process the request.",
    "허용되지 않은 설정 요청입니다.": "This settings request is not allowed.",
    "설정 화면이 닫혀 있습니다.": "The settings screen is closed.",
    "앱 안에서 설정 화면을 열어 주세요.": "Open settings from inside the app.",
    "진행 중인 요청을 마친 후 다시 시도해 주세요.": "Wait for the current request to finish, then try again.",
    "응답이 지연되었습니다. 새로고침 후 상태를 확인해 주세요.": "The response is taking longer than expected. Refresh to check the status.",
    "앱에 요청을 전달하지 못했습니다.": "Could not send the request to the app.",
    "설정 화면이 숨겨졌습니다.": "The settings screen was hidden.",
    "설정 화면이 닫혔습니다.": "The settings screen was closed.",
    "설정을 먼저 불러와 주세요.": "Load settings first.",
    "설정 값의 범위를 확인해 주세요.": "Check the allowed setting ranges.",
    "준비": "Preparing",
    "진행 중": "In progress",
    "내보내기 준비": "Preparing export",
    "취소 중": "Cancelling",
    "완료": "Complete",
    "일부 완료": "Partially complete",
    "실패": "Failed",
    "취소됨": "Cancelled",
    "ZIP 준비 중": "Preparing ZIP",
    "받기": "Download",
    "가져오기": "Import",
    "내보내기": "Export",
    "작업": "Task",
    " · 검증 ": " · Verified ",
    "개 · ": " files · ",
    "\n수신 ": "\nReceived ",
    " · 재사용 ": " · Reused ",
    "개 · 가져옴 ": " files · Imported ",
    "개\n실패 ": " files\nFailed ",
    "개 · 미보관 ": " files · Not stored ",
    "개": " files",
    "연결": "Connecting",
    "검증": "Verifying",
    "저장": "Saving",
    "복사": "Copying",
    "동시 ": "Parallel ",
    "평균 ": "Average ",
    "초\n": " sec\n",
    "\n오류: ": "\nError: ",
    "ZIP 작업을 준비하고 있습니다.": "Preparing the ZIP task.",
    "포함 목록 ": "Catalog ",
    "목록·용량 확인을 누르면 전체 예상 용량을 표시합니다.": "Choose Check list and size to see the estimated total size.",
    "서버가 준비되면 리소스를 관리할 수 있습니다.": "You can manage resources when the server is ready.",
    "\n\n최근 기록\n": "\n\nRecent logs\n",
    "준비 중": "Starting",
    "실행 중": "Running",
    "시작 실패": "Startup failed",
    "종료됨": "Stopped",
    "로컬 서버가 게임 연결을 기다리고 있습니다.": "The local server is waiting for the game to connect.",
    "서버와 데이터를 준비하고 있습니다.": "Preparing the server and data.",
    "로컬 서버가 실행 중이 아닙니다.": "The local server is not running.",
    "현재: ": "Active: ",
    "감상 모드": "Viewing mode",
    "일반 모드": "Normal mode",
    " · 자동 받기 ": " · Automatic downloads ",
    "켜짐": "On",
    "꺼짐": "Off",
    "현재 적용 값은 서버 준비 후 표시됩니다.": "Active settings appear when the server is ready.",
    "적용 대기": "Waiting to apply",
    "게임 적용 확인": "Applied in game",
    "원본 설정": "Original settings",
    "미지원": "Unsupported",
    "장면 대기": "Waiting for scene",
    "초기화 실패": "Initialization failed",
    "게임에서 현재 그래픽 설정을 확인했습니다. 화면 확장은 촬영 장면에서 확인해 주세요.": "The game confirmed the current graphics settings. Check view expansion in a photography scene.",
    "설정이 저장되었습니다. 촬영·360 장면에서 적용 상태를 확인합니다.": "Settings saved. Application is checked in photography and 360 scenes.",
    "저장 확인과 게임 적용 확인은 다릅니다. 해당 장면에 들어가 적용 상태를 확인해 주세요.": "Saving settings and confirming them in the game are separate. Open the relevant scene to check application.",
    "변경한 목록 설정은 다음 앱 실행부터 적용됩니다.": "Changed list settings apply next time you open the app.",
    "서버 상태 형식을 확인하지 못했습니다.": "Could not read the server status format.",
    "저장했습니다. 다음 앱 실행부터 적용됩니다.": "Saved. Changes apply next time you open the app.",
    "설정을 저장했습니다. 게임 적용 상태를 확인해 주세요.": "Settings saved. Check whether they are applied in the game.",
    "파일 선택을 취소했습니다.": "File selection cancelled.",
    "리소스 목록을 확인했습니다.": "Resource list checked.",
    "리소스 받기를 시작했습니다.": "Resource download started.",
    "작업 취소를 요청했습니다.": "Cancellation requested.",
    "ZIP 가져오기를 시작했습니다. 진행 상태를 확인해 주세요.": "ZIP import started. Check its progress.",
    "ZIP을 준비했습니다. 파일 앱에서 저장해 주세요.": "ZIP ready. Save it using the Files app.",
    "ZIP을 준비하고 있습니다. 완료되면 파일 앱에서 저장할 수 있습니다.": "Preparing ZIP. You can save it using the Files app when ready.",
    "ZIP 작업을 마치지 못했습니다. 확인된 파일과 기존 보관 자료는 유지됩니다.": "The ZIP task could not be completed. Verified files and existing stored data are kept.",
    "ZIP 가져오기를 마쳤습니다.": "ZIP import complete.",
    "원본 유지 (0)": "Keep original (0)",
    "서버 화면 언어": "Server interface language",
    "기기 언어": "Device language",
    "직접 입력": "Custom value",
    "배율": "Scale",
    "최대 크기": "Maximum size",
    "현재 그래픽 값": "Current graphics values",
    "서버 시작": "Start server",
    "다시 시도": "Retry",
    "게임 시작": "Start game",
    "게임으로 돌아가기": "Return to game",
    "서버 메뉴 닫기": "Close server menu",
    "언어 설정 저장": "Save language settings",
    "이 화면만 닫습니다. 서버는 계속 실행됩니다.": "Only this screen closes. The server keeps running.",
    "프리셋": "Preset",
    "서버 화면 언어는 게임 언어와 별개입니다.": "The server interface language is separate from the game language.",
    "낮음 (10)": "Low (10)",
    "중간 (20)": "Medium (20)",
    "높음 (30)": "High (30)",
    "최고 (40)": "Highest (40)",
    "촬영용 (100)": "Photography (100)",
    "1배 (기본)": "1× (Default)",
    "2배": "2×",
    "4096 px (기본)": "4096 px (Default)",
    "직접 입력 값": "Custom value",
    "서버 화면 언어는 아래 설정 저장으로 보관됩니다.": "Save the settings below to keep the server interface language.",
    "화면 언어만 바뀝니다. 게임 언어는 별도로 선택해 주세요.": "This changes the interface language only. Choose the game language separately.",
    "0.25배": "0.25×",
    "0.5배": "0.5×",
    "0.75배": "0.75×",
    "1.25배": "1.25×",
    "1.5배": "1.5×",
    "감상 모드·게임 언어": "Viewing mode and game language",
    "끔 (0)": "Off (0)",
    "원본 유지 (-1)": "Keep original (-1)",
    "앱을 열면 이 서버 메뉴가 먼저 표시됩니다. 서버가 준비되면 오른쪽 위의 ‘게임 시작’을 누르세요. 게임 중에는 화면 오른쪽 위 모서리를 한 손가락으로 2초간 누르면 이 메뉴를 다시 엽니다. Mac에서는 앱 메뉴의 ‘로컬 서버 설정…’ 또는 ⌘⇧,도 사용할 수 있습니다.": "This server menu opens first. When the server is ready, choose Start Game at the top right. During gameplay, hold the upper-right corner with one finger for 2 seconds to reopen this menu. On Mac, you can also use Local Server Settings… in the app menu or ⌘⇧,.",
    "화면 언어만 바뀝니다. 게임 언어는 별도로 선택해 주세요. 서버 화면 언어는 아래 설정 저장으로 보관됩니다.": "This changes the interface language only. Choose the game language separately. Save the settings below to keep the server interface language.",
    "3D 렌더 배율 선택": "Choose 3D render scale",
    "3D 렌더 배율 직접 입력 값": "Custom 3D render scale",
    "렌더 버퍼 최대 크기 선택": "Choose maximum render buffer size",
    "렌더 버퍼 최대 크기 직접 입력 값": "Custom maximum render buffer size",
    "리소스 검증 진행률": "Resource verification progress",
    "게임 시작 전의 변경은 ‘게임 시작’ 때 적용됩니다. 게임 시작 후의 감상 모드·언어 변경은 다음 앱 실행부터 적용됩니다.": "Changes saved before starting the game apply when you choose Start Game. Viewing mode and game language changed during gameplay apply next time you open the app.",
    "게임 시작 전에 저장하면 선택한 언어로 시작합니다. 게임을 시작한 뒤 변경한 언어는 앱을 다시 실행하면 적용됩니다. 번역이 없는 문구·이미지는 원본으로 표시합니다.": "Save before starting the game to use the selected language. Language changes made after the game starts apply when you reopen the app. Missing translations and untranslated images keep the original content.",
    "설정 저장": "Save settings",
    "저장했습니다. 게임 시작 전이면 ‘게임 시작’ 때 적용됩니다. 이미 게임을 시작했다면 다음 앱 실행부터 적용됩니다.": "Saved. Before gameplay, changes apply when you choose Start Game. If the game has already started, they apply next time you open the app."
  },
  "ja": {
    "IDOLY PRIDE 로컬 설정": "IDOLY PRIDE ローカル設定",
    "서버 설정": "サーバー設定",
    "새로고침": "更新",
    "서버 상태": "サーバー状態",
    "확인 중": "確認中",
    "기기에 저장된 설정을 불러옵니다.": "この端末に保存された設定を読み込みます。",
    "변경한 감상 모드·언어·자동 받기는 다음 앱 실행부터 적용됩니다.": "鑑賞モード・ゲーム言語・自動ダウンロードの変更は、次回のアプリ起動時に適用されます。",
    "감상 모드·언어": "鑑賞モード・言語",
    "저장 후 앱을 완전히 종료하고 다시 실행하면 적용됩니다. 일반 모드의 저장 자료는 따로 유지됩니다.": "保存後、アプリを完全に終了して再起動すると適用されます。通常モードのセーブデータは別に保持されます。",
    "감상 모드 · 전체 해금": "鑑賞モード・全解放",
    "없는 리소스 자동 받기": "未保存リソースを自動ダウンロード",
    "게임 언어": "ゲーム言語",
    "한국어": "韓国語",
    "다음 실행 설정 저장": "次回起動時の設定を保存",
    "현재 적용 값 확인 중": "現在の適用値を確認中",
    "그래픽·촬영 화면": "グラフィック・撮影画面",
    "대기": "待機",
    "사용자 그래픽 설정": "カスタムグラフィック設定を使用",
    "그래픽 품질": "グラフィック品質",
    "원본": "元の設定",
    "최저": "最低",
    "낮음": "低",
    "보통": "中",
    "높음": "高",
    "목표 프레임 수": "目標フレームレート",
    "3D 렌더 배율": "3D描画倍率",
    "렌더 버퍼 최대 크기": "描画バッファの最大サイズ",
    "가장자리 다듬기": "アンチエイリアス",
    "없음": "なし",
    "캐릭터 그림자": "キャラクターの影",
    "촬영·360 화면 확장": "撮影・360画面の表示領域を拡張",
    "화면 확장은 그래픽 설정과 독립적으로 적용됩니다. 목표 프레임 수는 실제 성능을 보장하지 않습니다.": "表示領域の拡張はグラフィック設定とは独立して適用されます。目標フレームレートは実際の動作性能を保証するものではありません。",
    "그래픽 설정 저장": "グラフィック設定を保存",
    "게임 적용 상태 확인 중": "ゲームへの適用状態を確認中",
    "MV 재생": "MV再生",
    "화면 회전 후 재생 시작": "画面の回転後に再生開始",
    "기본값은 켜짐입니다. 화면이 가로 방향으로 바뀔 때까지 기다립니다.": "初期設定はオンです。画面が横向きになるまで待機します。",
    "재생 설정 저장": "再生設定を保存",
    "MV·의상 목록": "MV・衣装一覧",
    "영상 MV 숨기기": "動画MVを非表示",
    "MV 정렬": "MVの並び順",
    "최신순": "新しい順",
    "오래된 순": "古い順",
    "이름순": "名前順",
    "ID순": "ID順",
    "의상 정렬": "衣装の並び順",
    "목록 설정 저장": "一覧設定を保存",
    "목록 설정은 다음 앱 실행부터 적용됩니다.": "一覧設定は、次回のアプリ起動時に適用されます。",
    "iOS 리소스 보관": "iOSリソースの保存",
    "받은 파일은 크기·MD5를 검증해 기기에 보관합니다. 중단 후 다시 받으면 검증된 파일을 재사용합니다.": "ダウンロードしたファイルはサイズ・MD5を検証して端末に保存します。中断後に再開すると、検証済みのファイルを再利用します。",
    "동시 다운로드": "同時ダウンロード数",
    "1개": "1個",
    "2개": "2個",
    "4개 · 기본": "4個・初期値",
    "8개": "8個",
    "목록·용량 확인": "一覧・容量を確認",
    "전체 리소스 받기": "全リソースをダウンロード",
    "서버 상태를 확인하고 있습니다.": "サーバー状態を確認しています。",
    "ZIP 가져오기": "ZIPを読み込む",
    "ZIP 내보내기": "ZIPを書き出す",
    "작업 취소": "処理を中止",
    "파일 앱에서 ZIP을 선택하거나 저장합니다. 내보내기에는 현재 보관된 파일만 포함됩니다.": "「ファイル」アプリでZIPを選択または保存します。書き出しには保存済みのファイルのみが含まれます。",
    "진단": "診断",
    "게임 진단 대기 중": "ゲームの診断待ち",
    "상태·최근 기록 보기": "状態・最近のログを表示",
    "기록 없음": "ログなし",
    "설정은 이 기기에 저장됩니다.": "設定はこの端末に保存されます。",
    "요청을 처리하지 못했습니다.": "リクエストを処理できませんでした。",
    "허용되지 않은 설정 요청입니다.": "許可されていない設定リクエストです。",
    "설정 화면이 닫혀 있습니다.": "設定画面が閉じています。",
    "앱 안에서 설정 화면을 열어 주세요.": "アプリ内から設定画面を開いてください。",
    "진행 중인 요청을 마친 후 다시 시도해 주세요.": "実行中のリクエストが完了してから、もう一度お試しください。",
    "응답이 지연되었습니다. 새로고침 후 상태를 확인해 주세요.": "応答に時間がかかっています。更新して状態をご確認ください。",
    "앱에 요청을 전달하지 못했습니다.": "アプリにリクエストを送信できませんでした。",
    "설정 화면이 숨겨졌습니다.": "設定画面が非表示になりました。",
    "설정 화면이 닫혔습니다.": "設定画面が閉じられました。",
    "설정을 먼저 불러와 주세요.": "先に設定を読み込んでください。",
    "설정 값의 범위를 확인해 주세요.": "設定値の範囲をご確認ください。",
    "준비": "準備",
    "진행 중": "処理中",
    "내보내기 준비": "書き出し準備",
    "취소 중": "中止中",
    "완료": "完了",
    "일부 완료": "一部完了",
    "실패": "失敗",
    "취소됨": "中止済み",
    "ZIP 준비 중": "ZIP準備中",
    "받기": "ダウンロード",
    "가져오기": "読み込み",
    "내보내기": "書き出し",
    "작업": "処理",
    " · 검증 ": "・検証済み ",
    "개 · ": "個・",
    "\n수신 ": "\n受信 ",
    " · 재사용 ": "・再利用 ",
    "개 · 가져옴 ": "個・読み込み ",
    "개\n실패 ": "個\n失敗 ",
    "개 · 미보관 ": "個・未保存 ",
    "개": "個",
    "연결": "接続",
    "검증": "検証",
    "저장": "保存",
    "복사": "コピー",
    "동시 ": "同時 ",
    "평균 ": "平均 ",
    "초\n": "秒\n",
    "\n오류: ": "\nエラー: ",
    "ZIP 작업을 준비하고 있습니다.": "ZIP処理を準備しています。",
    "포함 목록 ": "収録一覧 ",
    "목록·용량 확인을 누르면 전체 예상 용량을 표시합니다.": "「一覧・容量を確認」を押すと、合計の推定容量を表示します。",
    "서버가 준비되면 리소스를 관리할 수 있습니다.": "サーバーの準備が完了すると、リソースを管理できます。",
    "\n\n최근 기록\n": "\n\n最近のログ\n",
    "준비 중": "準備中",
    "실행 중": "実行中",
    "시작 실패": "起動失敗",
    "종료됨": "停止済み",
    "로컬 서버가 게임 연결을 기다리고 있습니다.": "ローカルサーバーはゲームの接続を待っています。",
    "서버와 데이터를 준비하고 있습니다.": "サーバーとデータを準備しています。",
    "로컬 서버가 실행 중이 아닙니다.": "ローカルサーバーは実行されていません。",
    "현재: ": "現在: ",
    "감상 모드": "鑑賞モード",
    "일반 모드": "通常モード",
    " · 자동 받기 ": "・自動ダウンロード ",
    "켜짐": "オン",
    "꺼짐": "オフ",
    "현재 적용 값은 서버 준비 후 표시됩니다.": "サーバーの準備が完了すると、現在の適用値を表示します。",
    "적용 대기": "適用待ち",
    "게임 적용 확인": "ゲームへの適用を確認",
    "원본 설정": "元の設定",
    "미지원": "未対応",
    "장면 대기": "シーン待ち",
    "초기화 실패": "初期化失敗",
    "게임에서 현재 그래픽 설정을 확인했습니다. 화면 확장은 촬영 장면에서 확인해 주세요.": "ゲームで現在のグラフィック設定を確認しました。表示領域の拡張は撮影シーンでご確認ください。",
    "설정이 저장되었습니다. 촬영·360 장면에서 적용 상태를 확인합니다.": "設定を保存しました。撮影・360シーンで適用状態を確認します。",
    "저장 확인과 게임 적용 확인은 다릅니다. 해당 장면에 들어가 적용 상태를 확인해 주세요.": "設定の保存とゲームへの適用確認は別です。対象のシーンで適用状態をご確認ください。",
    "변경한 목록 설정은 다음 앱 실행부터 적용됩니다.": "変更した一覧設定は、次回のアプリ起動時に適用されます。",
    "서버 상태 형식을 확인하지 못했습니다.": "サーバー状態の形式を確認できませんでした。",
    "저장했습니다. 다음 앱 실행부터 적용됩니다.": "保存しました。次回のアプリ起動時に適用されます。",
    "설정을 저장했습니다. 게임 적용 상태를 확인해 주세요.": "設定を保存しました。ゲームへの適用状態をご確認ください。",
    "파일 선택을 취소했습니다.": "ファイルの選択を中止しました。",
    "리소스 목록을 확인했습니다.": "リソース一覧を確認しました。",
    "리소스 받기를 시작했습니다.": "リソースのダウンロードを開始しました。",
    "작업 취소를 요청했습니다.": "処理の中止を要求しました。",
    "ZIP 가져오기를 시작했습니다. 진행 상태를 확인해 주세요.": "ZIPの読み込みを開始しました。進行状況をご確認ください。",
    "ZIP을 준비했습니다. 파일 앱에서 저장해 주세요.": "ZIPの準備ができました。「ファイル」アプリで保存してください。",
    "ZIP을 준비하고 있습니다. 완료되면 파일 앱에서 저장할 수 있습니다.": "ZIPを準備しています。完了後、「ファイル」アプリで保存できます。",
    "ZIP 작업을 마치지 못했습니다. 확인된 파일과 기존 보관 자료는 유지됩니다.": "ZIP処理を完了できませんでした。確認済みのファイルと既存の保存データは保持されます。",
    "ZIP 가져오기를 마쳤습니다.": "ZIPの読み込みが完了しました。",
    "원본 유지 (0)": "元の設定を維持 (0)",
    "서버 화면 언어": "サーバー画面の言語",
    "기기 언어": "端末の言語",
    "직접 입력": "直接入力",
    "배율": "倍率",
    "최대 크기": "最大サイズ",
    "현재 그래픽 값": "現在のグラフィック値",
    "서버 시작": "サーバー開始",
    "다시 시도": "再試行",
    "게임 시작": "ゲーム開始",
    "게임으로 돌아가기": "ゲームに戻る",
    "서버 메뉴 닫기": "サーバーメニューを閉じる",
    "언어 설정 저장": "言語設定を保存",
    "이 화면만 닫습니다. 서버는 계속 실행됩니다.": "この画面のみを閉じます。サーバーは動作を続けます。",
    "프리셋": "プリセット",
    "서버 화면 언어는 게임 언어와 별개입니다.": "サーバー画面の言語とゲームの言語は別の設定です。",
    "낮음 (10)": "低 (10)",
    "중간 (20)": "中 (20)",
    "높음 (30)": "高 (30)",
    "최고 (40)": "最高 (40)",
    "촬영용 (100)": "撮影用 (100)",
    "1배 (기본)": "1倍（初期値）",
    "2배": "2倍",
    "4096 px (기본)": "4096 px（初期値）",
    "직접 입력 값": "直接入力値",
    "서버 화면 언어는 아래 설정 저장으로 보관됩니다.": "下の設定を保存すると、サーバー画面の言語も保存されます。",
    "화면 언어만 바뀝니다. 게임 언어는 별도로 선택해 주세요.": "画面の言語のみを変更します。ゲームの言語は別に選択してください。",
    "0.25배": "0.25倍",
    "0.5배": "0.5倍",
    "0.75배": "0.75倍",
    "1.25배": "1.25倍",
    "1.5배": "1.5倍",
    "감상 모드·게임 언어": "鑑賞モード・ゲーム言語",
    "끔 (0)": "オフ (0)",
    "원본 유지 (-1)": "元の設定を維持 (-1)",
    "앱을 열면 이 서버 메뉴가 먼저 표시됩니다. 서버가 준비되면 오른쪽 위의 ‘게임 시작’을 누르세요. 게임 중에는 화면 오른쪽 위 모서리를 한 손가락으로 2초간 누르면 이 메뉴를 다시 엽니다. Mac에서는 앱 메뉴의 ‘로컬 서버 설정…’ 또는 ⌘⇧,도 사용할 수 있습니다.": "アプリを開くと、最初にこのサーバーメニューが表示されます。サーバーの準備が完了したら、右上の「ゲーム開始」を押してください。ゲーム中は画面右上を指1本で2秒間長押しすると、このメニューを開けます。Macではアプリメニューの「ローカルサーバー設定…」または ⌘⇧, も使用できます。",
    "화면 언어만 바뀝니다. 게임 언어는 별도로 선택해 주세요. 서버 화면 언어는 아래 설정 저장으로 보관됩니다.": "画面の言語のみを変更します。ゲームの言語は別に選択してください。 下の設定を保存すると、サーバー画面の言語も保存されます。",
    "3D 렌더 배율 선택": "3D描画倍率を選択",
    "3D 렌더 배율 직접 입력 값": "3D描画倍率の直接入力値",
    "렌더 버퍼 최대 크기 선택": "描画バッファの最大サイズを選択",
    "렌더 버퍼 최대 크기 직접 입력 값": "描画バッファの最大サイズの直接入力値",
    "리소스 검증 진행률": "リソース検証の進捗",
    "게임 시작 전의 변경은 ‘게임 시작’ 때 적용됩니다. 게임 시작 후의 감상 모드·언어 변경은 다음 앱 실행부터 적용됩니다.": "ゲーム開始前の変更は「ゲーム開始」時に適用されます。ゲーム開始後の鑑賞モード・言語の変更は次回のアプリ起動時に適用されます。",
    "게임 시작 전에 저장하면 선택한 언어로 시작합니다. 게임을 시작한 뒤 변경한 언어는 앱을 다시 실행하면 적용됩니다. 번역이 없는 문구·이미지는 원본으로 표시합니다.": "ゲーム開始前に保存すると、選択した言語で開始します。ゲーム開始後に変更した言語は、アプリの再起動後に適用されます。翻訳のない文章・画像は原文のまま表示されます。",
    "설정 저장": "設定を保存",
    "저장했습니다. 게임 시작 전이면 ‘게임 시작’ 때 적용됩니다. 이미 게임을 시작했다면 다음 앱 실행부터 적용됩니다.": "保存しました。ゲーム開始前なら「ゲーム開始」時に適用されます。すでにゲームを開始している場合は、次回のアプリ起動時に適用されます。"
  }
};
  function resolveInterfaceLanguage(value, navigator = {}) {
    if (["ko", "ja", "en"].includes(value)) return value;
    const languages = Array.isArray(navigator.languages) ? navigator.languages : [];
    const preferred = languages[0] || navigator.language || "ko";
    const code = String(preferred).toLowerCase().split(/[-_]/)[0];
    return ["ko", "ja", "en"].includes(code) ? code : "en";
  }
  function translateUI(value, language) {
    const dictionary = UI_TRANSLATIONS[language];
    return typeof value === "string" && dictionary && Object.prototype.hasOwnProperty.call(dictionary, value) ? dictionary[value] : value;
  }
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const integer = value => Number.isSafeInteger(value) && value >= 0;
  const choice = (value, values) => values.includes(value);
  const exact = (value, keys) => object(value) && Object.keys(value).length === keys.length && keys.every(key => Object.prototype.hasOwnProperty.call(value, key));
  const identity = value => object(value) && value.schema === 1 && integer(value.revision);
  const validOptions = value => object(value) && typeof value.media_mode === "boolean" && typeof value.download_missing_resources === "boolean" && choice(value.language, ["ko", "ja", "en"]) && (value.interface_language === undefined || choice(value.interface_language, INTERFACE_LANGUAGES));
  const validPresentation = value => exact(value, ["schema", "revision", "custom_graphics", "quality", "target_fps", "render_scale", "max_buffer_pixel", "anti_aliasing", "shadow_resolution", "expand_photography"]) && identity(value) && typeof value.custom_graphics === "boolean" && typeof value.expand_photography === "boolean" && choice(value.quality, [0, 10, 20, 30, 40, 100]) && choice(value.target_fps, [0, 30, 60, 90, 120]) && typeof value.render_scale === "number" && Number.isFinite(value.render_scale) && value.render_scale >= 0.25 && value.render_scale <= 2 && integer(value.max_buffer_pixel) && value.max_buffer_pixel >= 256 && value.max_buffer_pixel <= 4096 && value.max_buffer_pixel % 2 === 0 && choice(value.anti_aliasing, [-1, 0, 1, 2]) && choice(value.shadow_resolution, [0, 512, 1024, 2048, 4096]);
  const validPlayback = value => exact(value, ["schema", "revision", "wait_for_orientation"]) && identity(value) && typeof value.wait_for_orientation === "boolean";
  const validMedia = value => exact(value, ["schema", "revision", "hide_video_mv", "mv_sort", "outfit_sort"]) && identity(value) && typeof value.hide_video_mv === "boolean" && choice(value.mv_sort, ["recent", "old", "title", "id"]) && choice(value.outfit_sort, ["original", "recent", "old", "title", "id"]);
  const plain = (value, limit = 1000) => typeof value === "string" ? value.slice(0, limit) : "";
  const count = value => integer(value) ? value : 0;
  const boundedJSON = (value, limit) => {
    try { const encoded = JSON.stringify(value); return typeof encoded === "string" && encoded.length <= limit; }
    catch (_) { return false; }
  };

  function validRequest(action, payload) {
    if (action === "status") return exact(payload, []);
    if (action === "save_options") return exact(payload, ["media_mode", "download_missing_resources", "language", "interface_language"]) && validOptions(payload);
    if (action === "save_presentation") return exact(payload, ["settings"]) && validPresentation(payload.settings);
    if (action === "save_playback") return exact(payload, ["settings"]) && validPlayback(payload.settings);
    if (action === "save_media") return exact(payload, ["settings"]) && validMedia(payload.settings);
    if (action === "resources_cancel") return exact(payload, ["job_id"]) && typeof payload.job_id === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(payload.job_id);
    if (action === "resources_download") return exact(payload, ["parallelism"]) && choice(payload.parallelism, [1, 2, 4, 8]);
    if (["resources_preview", "resources_import", "resources_export"].includes(action)) return exact(payload, []);
    return false;
  }

  // The only transport is the native handler. IDs are never reused in a page,
  // so a reply arriving after hide, timeout or a later request cannot own it.
  function createBridge(scope, timers = scope) {
    const pending = new Map();
    const listeners = new Set();
    let nextID = 1;
    let active = true;
    let disposed = false;

    function rejectPending(message) {
      for (const item of pending.values()) {
        timers.clearTimeout(item.timer);
        item.reject(new Error(message));
      }
      pending.clear();
    }
    function reply(id, envelope) {
      if (!active || disposed || !Number.isInteger(id) || id < 1 || id > MAX_ID) return;
      const item = pending.get(id);
      if (!item || !object(envelope) || envelope.id !== id || typeof envelope.ok !== "boolean" || !boundedJSON(envelope, 524288)) return;
      if (envelope.ok && !object(envelope.result)) return;
      pending.delete(id);
      timers.clearTimeout(item.timer);
      if (envelope.ok) item.resolve(envelope.result);
      else item.reject(new Error(plain(envelope.error && envelope.error.message, 300) || "요청을 처리하지 못했습니다."));
    }
    function event(value) {
      if (!active || disposed || !object(value) || !boundedJSON(value, 524288)) return;
      for (const listener of listeners) listener(value);
    }
    scope.idolyServerReply = reply;
    scope.idolyServerEvent = event;
    return {
      request(action, payload = {}) {
        if (!validRequest(action, payload) || !boundedJSON(payload, 16384)) return Promise.reject(new Error("허용되지 않은 설정 요청입니다."));
        if (!active || disposed) return Promise.reject(new Error("설정 화면이 닫혀 있습니다."));
        const handler = scope.webkit && scope.webkit.messageHandlers && scope.webkit.messageHandlers.idolyServer;
        if (!handler || typeof handler.postMessage !== "function") return Promise.reject(new Error("앱 안에서 설정 화면을 열어 주세요."));
        if (pending.size >= MAX_PENDING || nextID > MAX_ID) return Promise.reject(new Error("진행 중인 요청을 마친 후 다시 시도해 주세요."));
        const id = nextID++;
        return new Promise((resolve, reject) => {
          const timeout = ["resources_import", "resources_export"].includes(action) ? 120000 : 20000;
          const timer = timers.setTimeout(() => {
            pending.delete(id);
            reject(new Error("응답이 지연되었습니다. 새로고침 후 상태를 확인해 주세요."));
          }, timeout);
          pending.set(id, {resolve, reject, timer});
          try { handler.postMessage({id, action, ...payload}); }
          catch (_) {
            pending.delete(id);
            timers.clearTimeout(timer);
            reject(new Error("앱에 요청을 전달하지 못했습니다."));
          }
        });
      },
      subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
      suspend() { active = false; rejectPending("설정 화면이 숨겨졌습니다."); },
      resume() { if (!disposed) active = true; },
      dispose() {
        if (disposed) return;
        disposed = true;
        active = false;
        rejectPending("설정 화면이 닫혔습니다.");
        listeners.clear();
        if (scope.idolyServerReply === reply) delete scope.idolyServerReply;
        if (scope.idolyServerEvent === event) delete scope.idolyServerEvent;
      }
    };
  }

  function formatBytes(value) {
    const bytes = typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
    if (bytes < 1024) return Math.floor(bytes) + " B";
    const exponent = Math.min(3, Math.floor(Math.log(bytes) / Math.log(1024)));
    return (bytes / Math.pow(1024, exponent)).toFixed(1) + " " + ["B", "KB", "MB", "GB"][exponent];
  }

  function createSettingsApp(scope, document, timers = scope) {
    const bridge = createBridge(scope, timers);
    const elements = new Map();
    const el = id => {
      if (!elements.has(id)) elements.set(id, document.getElementById(id));
      return elements.get(id);
    };
    let interfaceChoice = "system";
    let interfaceDirty = false;
    let language = resolveInterfaceLanguage(interfaceChoice, scope.navigator);
    const t = value => translateUI(value, language);
    const text = (id, value, localize = true) => { el(id).textContent = localize ? t(value) : value; };
    const staticText = [];
    const staticAttributes = [];
    if (typeof document.createTreeWalker === "function" && document.body) {
      const walker = document.createTreeWalker(document.body, 4);
      let node;
      while ((node = walker.nextNode())) {
        const source = node.nodeValue.trim();
        const owner = node.parentElement;
        if (!source || !owner || ["SCRIPT", "STYLE"].includes(owner.tagName)) continue;
        const select = owner.tagName === "OPTION" ? owner.parentElement : null;
        if (select && ["language", "interface_language"].includes(select.id) && ["한국어", "日本語", "English"].includes(source)) continue;
        staticText.push({node, source, before: node.nodeValue.slice(0, node.nodeValue.indexOf(source)), after: node.nodeValue.slice(node.nodeValue.indexOf(source) + source.length)});
      }
      for (const node of document.querySelectorAll("[aria-label]")) staticAttributes.push({node, source: node.getAttribute("aria-label")});
    }
    const title = document.title;
    function applyInterfaceLanguage(value) {
      interfaceChoice = choice(value, INTERFACE_LANGUAGES) ? value : "system";
      language = resolveInterfaceLanguage(interfaceChoice, scope.navigator);
      el("interface_language").value = interfaceChoice;
      if (document.documentElement) document.documentElement.lang = language;
      if (typeof title === "string") document.title = t(title);
      for (const entry of staticText) entry.node.nodeValue = entry.before + t(entry.source) + entry.after;
      for (const entry of staticAttributes) entry.node.setAttribute("aria-label", t(entry.source));
      if (messageSource) text("message", messageSource);
    }
    function syncPreset(key) {
      const presets = key === "render_scale" ? SCALE_PRESETS : BUFFER_PRESETS;
      const value = Number(el(key).value);
      el(key + "_preset").value = el(key).value.trim() && presets.includes(value) ? String(value) : "custom";
    }
    const forms = {
      options: {fields: ["media_mode", "download_missing_resources", "language", "interface_language"], valid: validOptions},
      presentation: {fields: ["custom_graphics", "quality", "target_fps", "render_scale", "max_buffer_pixel", "anti_aliasing", "shadow_resolution", "expand_photography"], valid: validPresentation},
      playback: {fields: ["wait_for_orientation"], valid: validPlayback},
      media: {fields: ["hide_video_mv", "mv_sort", "outfit_sort"], valid: validMedia}
    };
    let snapshot = null;
    let visible = document.visibilityState !== "hidden";
    let disposed = false;
    let pollTimer = null;
    let refreshing = false;
    let mutationVersion = 0;
    let visibilityVersion = 0;
    let resourcePending = false;
    let job = null;
    const logs = [];
    let messageSource = "";

    function message(value, error = false) {
      messageSource = plain(value, 500);
      text("message", messageSource);
      el("message").hidden = !value;
      el("message").dataset.error = String(error);
    }
    function updateForm(name, settings) {
      const form = forms[name];
      if (!form.valid(settings)) {
        el(name + "-fields").disabled = !form.value || Boolean(form.busy) || !snapshot.running || snapshot.state !== "ready";
        return;
      }
      settings = name === "options" ? {interface_language: "system", ...settings} : settings;
      form.value = {...settings};
      if (!form.dirty && !form.busy) {
        for (const key of form.fields) {
          const input = el(key);
          if (key === "interface_language" && interfaceDirty) continue;
          if (input.type === "checkbox") input.checked = settings[key];
          else input.value = String(settings[key]);
        }
      }
      if (name === "options") {
        if (interfaceDirty) form.dirty = true;
      }
      if (name === "presentation" && !form.dirty && !form.busy) for (const key of ["render_scale", "max_buffer_pixel"]) syncPreset(key);
      el(name + "-fields").disabled = Boolean(form.busy) || !snapshot.running || snapshot.state !== "ready";
    }
    function settingsFromForm(name) {
      const form = forms[name];
      if (!form.value) throw new Error("설정을 먼저 불러와 주세요.");
      const value = name === "options" ? {} : {...form.value};
      for (const key of form.fields) {
        const input = el(key);
        value[key] = input.type === "checkbox" ? input.checked : typeof form.value[key] === "number" ? (input.value.trim() === "" ? NaN : Number(input.value)) : input.value;
      }
      if (!form.valid(value)) throw new Error("설정 값의 범위를 확인해 주세요.");
      return value;
    }
    function stopPolling() {
      if (pollTimer !== null) timers.clearTimeout(pollTimer);
      pollTimer = null;
    }
    function schedulePoll() {
      stopPolling();
      if (!visible || disposed) return;
      pollTimer = timers.setTimeout(() => { pollTimer = null; refresh(); }, job && ACTIVE_JOBS.has(job.state) ? 1000 : 4000);
    }
    function renderResources(runtime) {
      const library = object(runtime.resource_library) ? runtime.resource_library : {};
      job = object(library.job) ? library.job : null;
      const archivePending = object(snapshot.resource_operation) && snapshot.resource_operation.accepted === true && snapshot.resource_operation.ready === false;
      const activeJob = Boolean(job && ACTIVE_JOBS.has(job.state));
      const busy = activeJob || archivePending;
      const ready = Boolean(snapshot && snapshot.running && snapshot.state === "ready");
      for (const action of ["preview", "download", "import", "export"]) el("resources-" + action).disabled = !ready || busy || resourcePending;
      el("parallelism").disabled = busy || resourcePending || !ready;
      el("resources-cancel").disabled = !ready || !activeJob || resourcePending || !/^[A-Za-z0-9_-]{1,64}$/.test(job.job_id || "");
      const states = {preparing: "준비", running: "진행 중", export_ready: "내보내기 준비", cancelling: "취소 중", completed: "완료", partial: "일부 완료", failed: "실패", cancelled: "취소됨"};
      text("resource-state", archivePending && !activeJob ? "ZIP 준비 중" : job ? states[job.state] || "확인 중" : "대기");
      el("resource-progress").hidden = !job;
      if (job) {
        const total = count(job.total_files);
        const checked = count(job.verified_files);
        el("resource-progress").max = Math.max(1, total);
        el("resource-progress").value = Math.min(checked, total);
        const action = {download: "받기", import: "가져오기", export: "내보내기"}[job.action] || "작업";
        text("resource-summary", t(action) + t(" · 검증 ") + checked + "/" + total + t("개 · ") + formatBytes(job.verified_bytes) + " / " + formatBytes(job.total_bytes) + t("\n수신 ") + formatBytes(job.received_bytes) + t(" · 재사용 ") + count(job.cache_hit_files) + t("개 · 가져옴 ") + count(job.imported_files) + t("개\n실패 ") + count(job.failed_files) + t("개 · 미보관 ") + count(job.missing_files) + t("개"));
        const phases = object(job.phase_active_files) ? job.phase_active_files : {};
        const phaseText = [["connecting", "연결"], ["receiving", "받기"], ["checking", "검증"], ["saving", "저장"], ["copying", "복사"]].map(([key, title]) => t(title) + " " + count(phases[key])).join(" · ");
        const parallel = choice(job.parallelism, [1, 2, 4, 8]) ? t("동시 ") + job.parallelism + t("개 · ") : "";
        const elapsed = typeof job.elapsed_seconds === "number" && Number.isFinite(job.elapsed_seconds) && job.elapsed_seconds >= 0 ? Math.floor(job.elapsed_seconds) : 0;
        text("resource-detail", parallel + t("평균 ") + formatBytes(job.average_bytes_per_second) + "/s · " + elapsed + t("초\n") + phaseText + (job.error_code ? t("\n오류: ") + plain(job.error_code, 80) : ""));
      } else {
        const catalog = object(library.catalogs) && object(library.catalogs.ios) ? library.catalogs.ios : null;
        text("resource-summary", archivePending ? "ZIP 작업을 준비하고 있습니다." : catalog ? t("포함 목록 ") + count(catalog.object_count) + t("개 · ") + formatBytes(catalog.total_bytes) : ready ? "목록·용량 확인을 누르면 전체 예상 용량을 표시합니다." : "서버가 준비되면 리소스를 관리할 수 있습니다.");
        text("resource-detail", "");
      }
    }
    function renderDiagnostics(runtime) {
      const diagnostic = object(runtime.client_diagnostics) ? runtime.client_diagnostics : {};
      text("diagnostic-summary", plain(diagnostic.summary, 500) || t("게임 진단 대기 중"), false);
      const details = {
        server: {state: snapshot.state, running: snapshot.running, restart_required: snapshot.restart_required},
        native: object(snapshot.native) ? Object.fromEntries([
          "schema", "phase", "captured", "forwarded", "attempts", "hook_installed",
          "python_initialized", "launch_requested", "launch_prepared", "launcher_visible",
          "keyboard_lifecycle", "keyboard_ready",
          "game_hook_error", "error", "game_error", "client_data"
        ].filter(key => Object.prototype.hasOwnProperty.call(snapshot.native, key)).map(key => [key, snapshot.native[key]])) : null,
        game: diagnostic,
        presentation: object(runtime.presentation) ? runtime.presentation.client || null : null,
        playback: object(runtime.playback) ? runtime.playback.client || null : null,
        resource_transfer: runtime.resource_transfer || null,
        asset_transfer: runtime.asset_transfer || null,
        resource_operation: object(snapshot.resource_operation) ? {
          accepted: snapshot.resource_operation.accepted,
          ready: snapshot.resource_operation.ready,
          error: snapshot.resource_operation.error || null
        } : null
      };
      // Never interpolate server strings as markup, URLs or executable code.
      let detail = JSON.stringify(details, null, 2).slice(0, 24000);
      const recent = (Array.isArray(runtime.logs) ? runtime.logs.filter(line => typeof line === "string").slice(-40).map(line => plain(line, 1000)) : []).concat(logs).slice(-50);
      if (recent.length) detail += "\n\n최근 기록\n" + recent.join("\n");
      text("diagnostics", detail, false);
    }
    function renderStatus(value) {
      if (!object(value) || !object(value.options)) return false;
      const runtime = object(value.runtime) ? value.runtime : {};
      snapshot = {...value, runtime};
      if (validOptions(value.options)) {
        const configuredInterface = choice(value.options.interface_language, INTERFACE_LANGUAGES) ? value.options.interface_language : "system";
        if (!interfaceDirty && !forms.options.dirty && interfaceChoice !== configuredInterface) applyInterfaceLanguage(configuredInterface);
      }
      const titles = {idle: "대기", starting: "준비 중", ready: "실행 중", failed: "시작 실패", closed: "종료됨"};
      text("server-state", titles[value.state] || "확인 중");
      text("server-summary", value.state === "ready" && value.running ? "로컬 서버가 게임 연결을 기다리고 있습니다." : value.last_error ? plain(object(value.last_error) ? value.last_error.message || value.last_error.code : value.last_error, 300) : value.state === "starting" ? "서버와 데이터를 준비하고 있습니다." : "로컬 서버가 실행 중이 아닙니다.");
      el("restart-notice").hidden = value.restart_required !== true;
      updateForm("options", value.options);
      updateForm("presentation", object(runtime.presentation) ? runtime.presentation.settings : null);
      updateForm("playback", object(runtime.playback) ? runtime.playback.settings : null);
      updateForm("media", object(runtime.media_options) ? runtime.media_options.settings : null);
      const effective = value.effective_options;
      text("effective-options", validOptions(effective) ? t("현재: ") + t(effective.media_mode ? "감상 모드" : "일반 모드") + " · " + LANGUAGES[effective.language] + t(" · 자동 받기 ") + t(effective.download_missing_resources ? "켜짐" : "꺼짐") : "현재 적용 값은 서버 준비 후 표시됩니다.");
      const graphics = object(runtime.presentation) && object(runtime.presentation.client) ? runtime.presentation.client : {};
      const graphicsLabels = {waiting: "적용 대기", applied: "게임 적용 확인", disabled: "원본 설정", unsupported: "미지원", waiting_for_scene: "장면 대기", init_failed: "초기화 실패"};
      text("graphics-state", graphicsLabels[graphics.status] || "대기");
      text("graphics-detail", graphics.status === "applied" ? "게임에서 현재 그래픽 설정을 확인했습니다. 화면 확장은 촬영 장면에서 확인해 주세요." : graphics.status === "waiting_for_scene" ? "설정이 저장되었습니다. 촬영·360 장면에서 적용 상태를 확인합니다." : "저장 확인과 게임 적용 확인은 다릅니다. 해당 장면에 들어가 적용 상태를 확인해 주세요.");
      const playback = object(runtime.playback) && object(runtime.playback.client) ? runtime.playback.client : {};
      text("playback-state", playback.applied === true ? "게임 적용 확인" : playback.supported === false ? "미지원" : "적용 대기");
      const media = object(runtime.media_options) ? runtime.media_options : {};
      const mediaChanged = validMedia(media.settings) && validMedia(media.effective_settings) && forms.media.fields.some(key => media.settings[key] !== media.effective_settings[key]);
      text("media-effective", mediaChanged ? "변경한 목록 설정은 다음 앱 실행부터 적용됩니다." : "목록 설정은 다음 앱 실행부터 적용됩니다.");
      renderResources(runtime);
      renderDiagnostics(runtime);
      return true;
    }
    async function refresh() {
      if (!visible || disposed || refreshing) return;
      refreshing = true;
      const version = mutationVersion;
      el("refresh").disabled = true;
      try {
        const result = await bridge.request("status");
        if (visible && !disposed && version === mutationVersion && !renderStatus(result)) message("서버 상태 형식을 확인하지 못했습니다.", true);
      } catch (error) {
        if (visible && !disposed && version === mutationVersion) message(error.message, true);
      } finally {
        refreshing = false;
        if (!disposed) el("refresh").disabled = false;
        schedulePoll();
      }
    }
    async function save(name) {
      const form = forms[name];
      if (!visible || disposed || form.busy || !snapshot || !snapshot.running || snapshot.state !== "ready") return;
      let value;
      try { value = settingsFromForm(name); }
      catch (error) { message(error.message, true); return; }
      form.busy = true;
      mutationVersion++;
      const visibility = visibilityVersion;
      el(name + "-fields").disabled = true;
      try {
        const result = await bridge.request("save_" + name, name === "options" ? value : {settings: value});
        if (!visible || disposed || visibility !== visibilityVersion) return;
        form.dirty = false;
        form.busy = false;
        if (name === "options") interfaceDirty = false;
        if (!renderStatus(result)) { await refresh(); return; }
        message(name === "options" ? "저장했습니다. 게임 시작 전이면 ‘게임 시작’ 때 적용됩니다. 이미 게임을 시작했다면 다음 앱 실행부터 적용됩니다." : name === "media" ? "저장했습니다. 다음 앱 실행부터 적용됩니다." : "설정을 저장했습니다. 게임 적용 상태를 확인해 주세요.");
      } catch (error) {
        if (visible && !disposed && visibility === visibilityVersion) message(error.message, true);
      } finally {
        form.busy = false;
        if (!disposed) el(name + "-fields").disabled = !form.value || !snapshot || !snapshot.running || snapshot.state !== "ready";
        schedulePoll();
      }
    }
    async function resource(action) {
      if (!visible || disposed || resourcePending || !snapshot || !snapshot.running || snapshot.state !== "ready") return;
      const payload = action === "cancel" ? {job_id: job && job.job_id} : action === "download" ? {parallelism: Number(el("parallelism").value)} : {};
      resourcePending = true;
      mutationVersion++;
      const visibility = visibilityVersion;
      if (snapshot) renderResources(snapshot.runtime);
      try {
        const result = await bridge.request("resources_" + action, payload);
        if (!visible || disposed || visibility !== visibilityVersion) return;
        message(result.cancelled === true ? "파일 선택을 취소했습니다." : {preview: "리소스 목록을 확인했습니다.", download: "리소스 받기를 시작했습니다.", cancel: "작업 취소를 요청했습니다.", import: "ZIP 가져오기를 시작했습니다. 진행 상태를 확인해 주세요.", export: result.ready === true ? "ZIP을 준비했습니다. 파일 앱에서 저장해 주세요." : "ZIP을 준비하고 있습니다. 완료되면 파일 앱에서 저장할 수 있습니다."}[action]);
      } catch (error) {
        if (visible && !disposed && visibility === visibilityVersion) message(error.message, true);
      } finally {
        resourcePending = false;
        if (!disposed && snapshot) renderResources(snapshot.runtime);
        if (visible && !disposed) refresh();
      }
    }
    function onVisibility() {
      visible = document.visibilityState !== "hidden";
      mutationVersion++;
      visibilityVersion++;
      stopPolling();
      if (visible) { bridge.resume(); Promise.resolve().then(refresh); }
      else bridge.suspend();
    }
    function dispose() {
      if (disposed) return;
      disposed = true;
      visible = false;
      stopPolling();
      bridge.dispose();
      document.removeEventListener("visibilitychange", onVisibility);
      scope.removeEventListener("pagehide", dispose);
    }
    for (const [name, form] of Object.entries(forms)) {
      form.dirty = false;
      form.busy = false;
      el(name + "-form").addEventListener("input", () => { form.dirty = true; });
      el(name + "-form").addEventListener("change", () => { form.dirty = true; });
      el(name + "-form").addEventListener("submit", event => { event.preventDefault(); save(name); });
    }
    el("interface_language").addEventListener("change", () => {
      interfaceDirty = true;
      if (forms.options.value) forms.options.dirty = true;
      applyInterfaceLanguage(el("interface_language").value);
      if (snapshot) renderStatus(snapshot);
    });
    for (const key of ["render_scale", "max_buffer_pixel"]) {
      el(key + "_preset").addEventListener("change", () => {
        const value = el(key + "_preset").value;
        if (value !== "custom") el(key).value = value;
        else if (typeof el(key).focus === "function") el(key).focus();
        forms.presentation.dirty = true;
      });
      el(key).addEventListener("input", () => { syncPreset(key); forms.presentation.dirty = true; });
    }
    applyInterfaceLanguage(interfaceChoice);
    el("refresh").addEventListener("click", () => { message(""); refresh(); });
    for (const action of ["preview", "download", "import", "export", "cancel"]) el("resources-" + action).addEventListener("click", () => resource(action));
    bridge.subscribe(event => {
      if (object(event.status) && ["ready", "status", "error", "closed"].includes(event.event)) renderStatus(event.status);
      if (event.event === "log" && typeof event.message === "string") {
        logs.push(plain(event.message, 1000));
        if (logs.length > 40) logs.shift();
        if (snapshot) renderDiagnostics(snapshot.runtime);
      }
      if (["resource_result", "resource_error"].includes(event.event)) {
        if (event.accepted === false || event.event === "resource_error") message("ZIP 작업을 마치지 못했습니다. 확인된 파일과 기존 보관 자료는 유지됩니다.", true);
        else if (event.ready === true) message(event.output_path ? "ZIP을 준비했습니다. 파일 앱에서 저장해 주세요." : "ZIP 가져오기를 마쳤습니다.");
        else if (event.message) message(event.message);
        refresh();
      }
      if (pollTimer === null) schedulePoll();
    });
    document.addEventListener("visibilitychange", onVisibility);
    scope.addEventListener("pagehide", dispose);
    if (visible) refresh();
    else bridge.suspend();
    return {dispose};
  }

  if (typeof module !== "undefined" && module.exports) module.exports = {createBridge, createSettingsApp, formatBytes, resolveInterfaceLanguage, translateUI};
  else if (root.document) createSettingsApp(root, root.document);
})(typeof window !== "undefined" ? window : globalThis);
