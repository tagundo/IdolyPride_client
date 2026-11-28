import AppKit
import Foundation
import SwiftUI
import Darwin


struct ManagedAccount: Identifiable, Equatable {
    let mode: String
    let profile: String
    let revision: String
    let summary: String
    var id: String { mode + ":" + profile }
    init?(_ row: [String: Any]) {
        guard let mode = row["mode"] as? String, ["normal", "media"].contains(mode),
              let profile = row["profile"] as? String, !profile.isEmpty, profile.utf8.count <= 64,
              let revision = row["revision"] as? String, revision.count == 64 else { return nil }
        self.mode = mode; self.profile = profile; self.revision = revision
        let counts = row["counts"] as? [String: Any] ?? [:]
        let labels = ["cards": "카드", "characters": "아이돌", "costumes": "의상", "photos": "포토"]
        self.summary = labels.keys.sorted().compactMap { key in
            guard let count = counts[key] as? Int, count >= 0 else { return nil }
            return "\(labels[key]!) \(count)"
        }.joined(separator: " · ")
    }
}

struct LocalLoveEvent: Identifiable, Equatable {
    let id: String
    let title: String
    let supported: Bool
    init?(_ row: [String: Any]) {
        guard let id = row["id"] as? String, !id.isEmpty, id.utf8.count <= 96,
              let title = row["title"] as? String, !title.isEmpty, title.utf8.count <= 1024 else { return nil }
        self.id = id; self.title = title; self.supported = row["supported"] as? Bool == true
    }
}

struct AccountRestorePoint: Identifiable, Equatable {
    let id: String
    let mode: String
    let profile: String
    let created: String
    init?(_ row: [String: Any]) {
        guard let id = row["id"] as? String, !id.isEmpty,
              let mode = row["mode"] as? String, let profile = row["profile"] as? String else { return nil }
        self.id = id; self.mode = mode; self.profile = profile
        self.created = row["created_at"].map { String(describing: $0) } ?? id
    }
}

@MainActor
final class ServerModel: ObservableObject {
    @Published var running = false
    @Published var busy = true
    @Published var canStop = false
    @Published var experimentalMainLive = UserDefaults.standard.bool(forKey: "experimentalMainLive") {
        didSet { UserDefaults.standard.set(experimentalMainLive, forKey: "experimentalMainLive") }
    }
    @Published var mediaMode = UserDefaults.standard.bool(forKey: "mediaMode") {
        didSet { UserDefaults.standard.set(mediaMode, forKey: "mediaMode") }
    }
    @Published var downloadMissingResources = (UserDefaults.standard.object(forKey: "downloadMissingResources") as? Bool) ?? true {
        didSet { UserDefaults.standard.set(downloadMissingResources, forKey: "downloadMissingResources") }
    }
    @Published var resourcesInDownloads = (UserDefaults.standard.object(forKey: "resourcesInDownloads") as? Bool) ?? true {
        didSet { UserDefaults.standard.set(resourcesInDownloads, forKey: "resourcesInDownloads") }
    }
    @Published private(set) var resourceDirectoryPath = (UserDefaults.standard.object(forKey: "resourceDirectoryPath") as? String) ?? ""
    @Published private(set) var resourceLocationMessage = "서버를 중지한 뒤 보관 폴더를 바꿀 수 있습니다. 기존 파일은 옮기거나 삭제하지 않습니다."
    @Published private(set) var presentation = ClientPresentationSettings.defaults
    @Published private(set) var playback = ClientPlaybackSettings.defaults
    @Published private(set) var library = ClientLibrarySettings()
    @Published private(set) var libraryMessage = "목록·언어 변경은 서버 재시작 후 게임 타이틀에서 다시 로그인하면 적용됩니다."
    @Published var resourcePlatform = "ios"
    @Published var resourceParallelism = ServerModel.savedResourceParallelism() {
        didSet {
            if [1, 2, 4, 8].contains(resourceParallelism) {
                UserDefaults.standard.set(resourceParallelism, forKey: "resourceDownloadParallelism")
            }
        }
    }
    @Published private(set) var resourceMessage = "서버를 시작하면 보관 목록과 진행 상태를 확인할 수 있습니다."
    @Published private(set) var resourceTransferMessage = "리소스 전송 상태 수신 대기"
    @Published private(set) var resourceJobID: String?
    @Published private(set) var resourceJobActive = false
    @Published private(set) var resourcePending = false
    @Published private(set) var playbackMessage = "Mac의 기본값은 꺼짐입니다. 켜면 원본 회전 대기 동작을 사용합니다."
    @Published private(set) var presentationFeedback = ClientPresentationFeedback.waiting

    @Published private(set) var accounts: [ManagedAccount] = []
    @Published private(set) var accountMode = "normal"
    @Published var selectedAccountProfile = ""
    @Published var newAccountProfile = ""
    @Published var newAccountManagerName = ""
    @Published var selectedRestorePoint = ""
    @Published private(set) var accountMessage = "새로고침으로 일반·감상 계정과 복구 지점을 확인합니다."
    @Published private(set) var accountPending = false
    @Published private(set) var accountPreviewMessage = ""
    @Published private(set) var accountSelectionMessage = ""
    @Published private(set) var currentAccountMessage = ""
    @Published private(set) var accountPageMessage = ""
    @Published private(set) var restorePoints: [AccountRestorePoint] = []
    @Published private(set) var nextAccountOffset: Int?
    @Published private(set) var nextRestoreOffset: Int?
    @Published private(set) var startupChecksMessage = "서버 준비 검사 대기"
    @Published private(set) var durableHistoryMessage = "저장된 오류 기록을 확인하고 있습니다."
    private var accountSelectionRevision: String?
    private var accountPreviewToken: String?
    private var accountRequestSerial = 0
    private var pendingAccountID: Int?
    private var pendingAccountAction: String?
    private var accountsInitiallyRequested = false
    private var accountOffset = 0
    private var restoreOffset = 0
    private var diagnosticStatus: [String: Any] = [:]

    // Transfer credentials live only in OfficialImportControls' local State.
    @Published var officialUILanguage = UserDefaults.standard.string(forKey: "officialInterfaceLanguage")
        ?? (Locale.preferredLanguages.first?.hasPrefix("ja") == true ? "ja" : Locale.preferredLanguages.first?.hasPrefix("ko") == true ? "ko" : "en") {
        didSet { if ["ko", "ja", "en"].contains(officialUILanguage) { UserDefaults.standard.set(officialUILanguage, forKey: "officialInterfaceLanguage") } }
    }
    @Published var officialPlatform = "ios"
    @Published var officialTargetProfile = "official-import"
    @Published var officialReplace = false
    @Published var officialReplaceProfile = ""
    @Published private(set) var officialState = "idle"
    @Published private(set) var officialProgress = "preparing"
    @Published private(set) var officialBusy = false
    @Published private(set) var officialPending = false
    @Published private(set) var officialExpiry = 0
    @Published private(set) var officialErrorCode: String?
    @Published private(set) var officialPreview: [String: Any] = [:]
    @Published private(set) var officialImportedAccount: ManagedAccount?
    @Published private(set) var officialNotice = ""
    @Published private(set) var officialWarningCodes: [String] = []
    @Published private(set) var officialAccountListRefreshRequired = false
    private var officialJobID: String?
    private var officialRequestSerial = 0
    private var pendingOfficialID: Int?
    private var pendingOfficialAction: String?
    private var officialActivationProfile: String?

    @Published private(set) var eventRows: [LocalLoveEvent] = []
    @Published private(set) var eventPending = false
    @Published private(set) var eventCatalogAvailable = false
    @Published private(set) var eventInvalidFile = false
    @Published private(set) var eventRestartRequired = false
    @Published private(set) var eventDraftDirty = false
    @Published private(set) var eventErrorCode: String?
    @Published private(set) var eventDraft: [[String: Any]] = []
    private var eventEffective: [[String: Any]] = []
    private var eventHasEffective = false
    private var eventRevision = 0
    private var eventRequestSerial = 0
    private var pendingEventID: Int?
    private var pendingEventAction: String?
    private var eventSnapshotData: Data?

    private var invalidResourceLocation = false
    private var experimentalLiveObserved = false
    @Published var status = "앱을 준비하고 있습니다."
    @Published var logs = ""
    @Published var alertMessage: String?
    @Published var clientLaunchMessage = "PlayCover에서 ‘아이프라 로컬’을 두 번 클릭해 실행해 주세요."
    @Published var clientLaunchFailed = false
    let dataDirectory: URL
    private let smoke: Bool
    private let smokeReport: URL?
    private var child: Process?
    private var input: Pipe?
    private var output: Pipe?
    private var errors: Pipe?
    private var pending = Data()
    private var launched = false
    private var shutdownRequested = false
    private var shutdownFinished = false
    private var shutdownCompletions: [() -> Void] = []
    private var smokeStarted = false
    private var smokeStopping = false
    private var smokeFinished = false
    private var visibleWindowObserved = false
    private var phases: [String] = []
    private var statusTimer: Timer?
    private var statusPolling = ClientPresentationPolling()
    private var presentationClient: [String: Any]?
    private var presentationInvalid = false
    private var presentationSaveFailed = false

    init() {
        if let saved = UserDefaults.standard.object(forKey: "resourceDirectoryPath"), !(saved is String) {
            invalidResourceLocation = true
        }
        let arguments = ProcessInfo.processInfo.arguments
        func value(_ flag: String) -> String? {
            guard let index = arguments.firstIndex(of: flag), index + 1 < arguments.count else { return nil }
            return arguments[index + 1]
        }
        smoke = arguments.contains("--app-smoke")
        smokeReport = value("--smoke-report").map { URL(fileURLWithPath: $0) }
        if arguments.contains("--experimental-main-live") { experimentalMainLive = true }
        if let custom = value("--data-dir") {
            dataDirectory = URL(fileURLWithPath: custom, isDirectory: true)
        } else {
            let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            dataDirectory = support.appendingPathComponent("IdolyPrideLocal", isDirectory: true)
        }
        let loaded = ClientPresentationSettings.load(from: presentationFile)
        presentation = loaded.settings
        presentationInvalid = loaded.invalid
        let loadedPlayback = ClientPlaybackSettings.load(from: playbackFile)
        playback = loadedPlayback.settings
        let loadedLibrary = ClientLibrarySettings.load(from: dataDirectory)
        library = loadedLibrary.settings
        if loadedLibrary.invalid { libraryMessage = "목록·언어 설정을 읽지 못했습니다. 선택을 바꾸면 새로 저장합니다." }
        if loadedPlayback.invalid {
            playbackMessage = "회전 대기 설정을 읽지 못해 기본값을 표시합니다. 옵션을 바꾸면 새로 저장합니다."
        }
        updatePresentationFeedback()
        checkpoint("model_initialized")
    }

    private var presentationFile: URL {
        dataDirectory.appendingPathComponent(ClientPresentationSettings.filename)
    }

    private var playbackFile: URL {
        dataDirectory.appendingPathComponent(ClientPlaybackSettings.filename)
    }

    var orientationWaitBinding: Binding<Bool> {
        Binding(get: { self.playback.waitForOrientation }, set: { enabled in
            guard !self.shutdownRequested, self.playback.waitForOrientation != enabled else { return }
            var changed = self.playback
            changed.waitForOrientation = enabled
            do {
                self.playback = try changed.saving(to: self.playbackFile)
                self.playbackMessage = "MV 회전 대기 설정이 저장되었습니다."
            } catch {
                self.playbackMessage = "회전 대기 설정을 저장하지 못했습니다. 이전 설정을 유지합니다."
                self.alertMessage = self.playbackMessage
            }
        })
    }

    func libraryBinding<Value: Equatable>(_ key: WritableKeyPath<ClientLibrarySettings, Value>) -> Binding<Value> {
        Binding(get: { self.library[keyPath: key] }, set: { value in
            guard !self.shutdownRequested, self.library[keyPath: key] != value else { return }
            var changed = self.library
            changed[keyPath: key] = value
            do {
                self.library = try changed.savingMedia(to: self.dataDirectory.appendingPathComponent(ClientLibrarySettings.mediaFilename))
                self.libraryMessage = "저장되었습니다. 서버를 재시작하고 게임 타이틀에서 다시 로그인해 주세요."
            } catch { self.alertMessage = "목록 설정을 저장하지 못했습니다. 이전 설정을 유지합니다." }
        })
    }

    var languageBinding: Binding<String> {
        Binding(get: { self.library.language }, set: { value in
            guard !self.shutdownRequested, self.library.language != value else { return }
            var changed = self.library
            changed.language = value
            do {
                try changed.savingLanguage(to: self.dataDirectory.appendingPathComponent(ClientLibrarySettings.languageFilename))
                self.library = changed
                self.libraryMessage = "언어가 저장되었습니다. 서버를 재시작하고 게임 타이틀에서 다시 로그인해 주세요."
            } catch { self.alertMessage = "언어 설정을 저장하지 못했습니다. 이전 설정을 유지합니다." }
        })
    }

    private func updateResourceStatus(_ state: [String: Any]) {
        resourcePending = false
        resourceTransferMessage = Self.resourceTransferDescription(state["resource_transfer"] as? [String: Any])
        guard let resources = state["resource_library"] as? [String: Any] else {
            if !running { resourceJobActive = false; resourceJobID = nil }
            return
        }
        let job = resources["job"] as? [String: Any]
        let phase = job?["state"] as? String ?? "idle"
        resourceJobID = job?["job_id"] as? String
        resourceJobActive = ["preparing", "running", "export_ready", "cancelling"].contains(phase)
        if let job = job {
            let files = (job["verified_files"] as? NSNumber)?.intValue ?? 0
            let total = (job["total_files"] as? NSNumber)?.intValue ?? 0
            let bytes = (job["received_bytes"] as? NSNumber)?.int64Value ?? 0
            let missing = (job["missing_files"] as? NSNumber)?.intValue ?? 0
            let imported = (job["imported_files"] as? NSNumber)?.intValue ?? 0
            let failed = (job["failed_files"] as? NSNumber)?.intValue ?? 0
            let parallelism = (job["parallelism"] as? NSNumber)?.intValue ?? 0
            let transfers = job["action"] as? String == "download" && [1, 2, 4, 8].contains(parallelism)
                ? " · 동시 \(parallelism)개" : ""
            resourceMessage = "상태 \(phase)\(transfers) · 확인 \(files)/\(total)개 · 수신 \(ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)) · 가져옴 \(imported)개 · 실패 \(failed)개 · 미보관 \(missing)개"
            if job["action"] as? String == "download", job["elapsed_seconds"] != nil {
                let rawRate = (job["average_bytes_per_second"] as? NSNumber)?.doubleValue ?? 0
                let rate = rawRate.isFinite && rawRate >= 0 && rawRate < Double(Int64.max) ? Int64(rawRate) : 0
                let rawElapsed = (job["elapsed_seconds"] as? NSNumber)?.doubleValue ?? 0
                let elapsed = rawElapsed.isFinite && rawElapsed >= 0 && rawElapsed < Double(Int64.max) ? Int64(rawElapsed) : 0
                resourceMessage += "\n평균 수신 \(ByteCountFormatter.string(fromByteCount: rate, countStyle: .file))/s · \(elapsed)초 · 기존 파일 재사용 \((job["cache_hit_files"] as? NSNumber)?.intValue ?? 0)개"
                let checkedBytes = max(0, (job["verified_bytes"] as? NSNumber)?.int64Value ?? 0)
                let totalBytes = max(0, (job["total_bytes"] as? NSNumber)?.int64Value ?? 0)
                resourceMessage += "\n용량 검증 완료 \(ByteCountFormatter.string(fromByteCount: checkedBytes, countStyle: .file)) / \(ByteCountFormatter.string(fromByteCount: totalBytes, countStyle: .file))"
                if let phases = job["phase_active_files"] as? [String: Any] {
                    let entries = [("connecting", "연결"), ("receiving", "받기"), ("checking", "검증"), ("saving", "저장"), ("copying", "복사")]
                    resourceMessage += "\n" + entries.map { key, title in "\(title) \(max(0, (phases[key] as? NSNumber)?.intValue ?? 0))" }.joined(separator: " · ") + "개"
                }
            }
        } else if let catalogs = resources["catalogs"] as? [String: Any], let catalog = catalogs[resourcePlatform] as? [String: Any] {
            if let files = catalog["object_count"] as? NSNumber, let bytes = catalog["total_bytes"] as? NSNumber {
                resourceMessage = "포함 목록 \(files.intValue)개 · \(ByteCountFormatter.string(fromByteCount: bytes.int64Value, countStyle: .file)). 받은 파일은 크기와 MD5를 검사해 보관합니다."
            } else { resourceMessage = "선택한 플랫폼의 목록 확인을 누르면 예상 용량을 표시합니다." }
        }
    }

    // BEGIN_RESOURCE_TRANSFER_DISPLAY
    private static func transferInteger(_ value: Any?) -> Int64? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              !["f", "d"].contains(String(cString: number.objCType)), number.int64Value >= 0 else { return nil }
        return number.int64Value
    }

    private static func transferPlain(_ value: Any?, limit: Int) -> String? {
        guard let text = value as? String, !text.isEmpty, text.utf8.count <= limit,
              text.utf8.allSatisfy({ (65...90).contains($0) || (97...122).contains($0)
                  || (48...57).contains($0) || $0 == 95 || $0 == 45 || $0 == 46 }) else { return nil }
        return text
    }

    private static func transferBytes(_ value: Any?) -> String {
        guard let bytes = transferInteger(value) else { return "확인 불가" }
        if bytes < 1024 { return "\(bytes) B" }
        let divisor: Double = bytes < 1048576 ? 1024 : bytes < 1073741824 ? 1048576 : 1073741824
        let unit = bytes < 1048576 ? "KiB" : bytes < 1073741824 ? "MiB" : "GiB"
        return String(format: "%.1f %@", locale: Locale(identifier: "en_US_POSIX"), Double(bytes) / divisor, unit)
    }

    private static func transferEntry(_ entry: [String: Any], active: Bool) -> String {
        let phase = ["received": "접수", "resolving": "목록 조회", "waiting_cache": "캐시 대기",
                     "sending": "전송 중", "completed": "완료", "failed": "실패"]
        let cache = ["pending": "캐시 확인 중", "cache_hit": "캐시 파일", "upstream": "CDN 받기", "cache_miss": "미보관"]
        let key = entry["cache_key"] as? String
        let validKey = key.flatMap { value in value.utf8.count == 64
            && value.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) ? value : nil }
        let name = entry["kind"] as? String == "manifest" ? "목록"
            : transferPlain(entry["object_name"], limit: 160) ?? validKey ?? "리소스 확인 불가"
        let code = transferInteger(entry["http_status"])
        let http = code == 0 ? "응답 대기" : code.map { (100...599).contains($0) ? "HTTP \($0)" : "HTTP 확인 불가" } ?? "HTTP 확인 불가"
        let state = transferPlain(entry["phase"], limit: 24).flatMap { phase[$0] } ?? "상태 확인 불가"
        let result = transferPlain(entry["cache_result"], limit: 24).flatMap { cache[$0] } ?? "캐시 확인 불가"
        var text = "\(name) · \(http) · \(state) · \(result)"
        if let rawError = entry["error_code"] as? String, !rawError.isEmpty {
            text += " · " + (transferPlain(rawError, limit: 64) ?? "오류 코드 확인 불가")
        }
        if let cause = entry["cause_code"] as? String, !cause.isEmpty {
            text += " · " + (transferPlain(cause, limit: 64) ?? "원인 코드 확인 불가")
        }
        if active, let elapsed = transferInteger(entry["elapsed_ms"]) {
            text += String(format: " · 경과 %.1f초", locale: Locale(identifier: "en_US_POSIX"), Double(elapsed) / 1000)
        }
        return text
    }

    private static func resourceTransferDescription(_ value: [String: Any]?) -> String {
        let value = value ?? [:]
        func count(_ key: String) -> String { transferInteger(value[key]).map(String.init) ?? "확인 불가" }
        let rawActive = value["active_http_requests"] as? [[String: Any]]
        let active = rawActive.flatMap { $0.count <= 64 ? $0 : nil }
        let hasActive = active?.isEmpty == false
        let current = active?.first ?? value["last_request"] as? [String: Any]
        let currentEmpty = value["last_request"] is NSNull ? "없음" : "세부 상태 수신 대기"
        let failedEmpty = value["last_failed_request"] is NSNull ? "없음" : "세부 상태 수신 대기"
        let currentText = current.map { transferEntry($0, active: hasActive) } ?? currentEmpty
        let failedText = (value["last_failed_request"] as? [String: Any]).map { transferEntry($0, active: false) } ?? failedEmpty
        return "로컬→게임 \(transferBytes(value["session_served_bytes"])) · CDN→서버 \(transferBytes(value["session_received_bytes"]))\n"
            + "게임 HTTP 요청 \(count("session_http_requests")) · 실패 \(count("session_http_failures")) · 캐시 적중 \(count("session_cache_hits")) · 미보관 \(count("session_cache_misses"))\n"
            + "\(hasActive ? "현재 요청" : "최근 요청"): \(currentText)\n최근 실패: \(failedText)"
    }
    // END_RESOURCE_TRANSFER_DISPLAY

    private static func savedResourceParallelism() -> Int {
        guard let number = UserDefaults.standard.object(forKey: "resourceDownloadParallelism") as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID(),
              !["f", "d"].contains(String(cString: number.objCType)),
              [1, 2, 4, 8].contains(number.intValue) else { return 4 }
        return number.intValue
    }


    var visibleAccounts: [ManagedAccount] { accounts.filter { $0.mode == accountMode } }
    var visibleRestorePoints: [AccountRestorePoint] {
        restorePoints.filter { $0.mode == accountMode && $0.profile == selectedAccountProfile }
    }
    var selectedManagedAccount: ManagedAccount? {
        visibleAccounts.first { $0.profile == selectedAccountProfile }
    }
    var hasAccountPreview: Bool { accountPreviewToken != nil }
    var accountModeBinding: Binding<String> {
        Binding(get: { self.accountMode }, set: { value in
            guard ["normal", "media"].contains(value), !self.accountPending else { return }
            self.accountMode = value
            self.selectedAccountProfile = self.visibleAccounts.first?.profile ?? ""
            self.selectedRestorePoint = ""
        })
    }

    private func updateAccounts(_ value: [String: Any]) {
        let rows = (value["accounts"] as? [[String: Any]] ?? []).compactMap(ManagedAccount.init)
        if accounts != rows { accounts = rows }
        let points = (value["restore_points"] as? [[String: Any]] ?? []).compactMap(AccountRestorePoint.init)
        if restorePoints != points { restorePoints = points }
        accountSelectionRevision = value["selection_revision"] as? String
        accountOffset = value["offset"] as? Int ?? 0
        restoreOffset = value["restore_offset"] as? Int ?? 0
        nextAccountOffset = value["next_offset"] as? Int
        nextRestoreOffset = value["next_restore_offset"] as? Int
        let selected = value["selected"] as? [String: String] ?? [:]
        accountSelectionMessage = "다음 시작 · 일반: \(selected["normal"] ?? "sandbox") · 감상: \(selected["media"] ?? "sandbox")"
        accountPageMessage = "계정 \(rows.count) / \(value["accounts_total"] as? Int ?? rows.count)개 · 복구 지점 \(points.count) / \(value["restore_points_total"] as? Int ?? points.count)개"
        if !visibleAccounts.contains(where: { $0.profile == selectedAccountProfile }) {
            selectedAccountProfile = visibleAccounts.first(where: { $0.profile == selected[accountMode] })?.profile
                ?? visibleAccounts.first?.profile ?? ""
        }
        if !visibleRestorePoints.contains(where: { $0.id == selectedRestorePoint }) { selectedRestorePoint = "" }
    }


    private static func settingsCodeDescription(_ code: String) -> String {
        let labels = [
            "selection_ready": "다음 시작 계정 확인", "selection_invalid": "예약 계정을 확인해 주세요.",
            "catalog_present": "기본 목록 확인", "descriptor_loaded": "통신 규격 확인",
            "tag_and_pack_sizes_checked": "마스터 목록·파일 크기 확인", "storage_writable": "저장 위치 쓰기 가능",
            "low_free_space": "남은 저장 공간이 부족합니다.", "http_json_ready": "파일 서버 응답 확인",
            "listener_started": "게임 서버 연결 대기", "listener_stopped": "서버 중지",
            "resource_catalog_missing": "리소스 목록이 없습니다.", "on_demand_enabled": "필요한 파일 자동 받기 사용",
            "offline_cache_unverified": "오프라인 파일 전체 검증 전", "permission_denied": "저장 위치의 접근 권한을 확인해 주세요.",
            "address_in_use": "다른 서버가 같은 포트를 사용하고 있습니다.", "missing_input": "필수 파일이 없습니다.",
            "invalid_input": "필수 파일을 읽지 못했습니다.", "insufficient_space": "저장 공간이 부족합니다.",
            "internal_error": "준비 검사에 실패했습니다.", "startup_requested": "서버 시작 요청",
            "server_ready": "로컬 서버 준비 완료", "server_stopped": "로컬 서버 중지",
            "grpc_stopped": "게임 연결 중지", "profile_created": "일반 계정 준비",
            "profile_loaded": "기존 계정 준비", "media_profile_prepared": "감상 계정 준비",
            "media_master_prepared": "감상용 마스터 준비", "selected_resource_storage": "선택한 리소스 보관 위치 사용",
            "cleanup_failed": "중지 정리를 완료하지 못했습니다.", "history_cleared": "보관 기록 지움",
            "history_recovered": "손상된 기록 대신 새 기록 시작"
        ]
        return labels[code] ?? code
    }

    private static func historyDescription(_ row: [String: Any]) -> String {
        let kind = row["kind"] as? String ?? ""
        let labels = ["rpc": "게임 요청", "http_failure": "파일 요청 실패",
            "startup_failure": "서버 시작 실패", "lifecycle": "실행 상태"]
        var parts = [row["timestamp"] as? String ?? "", labels[kind] ?? kind]
        if let code = row["code"] as? String, !code.isEmpty { parts.append(settingsCodeDescription(code)) }
        if let path = row["path"] as? String, !path.isEmpty { parts.append(path) }
        if let outcome = row["outcome"] as? String, !outcome.isEmpty {
            let outcomes = ["OK": "정상", "UNIMPLEMENTED": "미구현", "INVALID_ARGUMENT": "잘못된 입력",
                "INTERNAL": "내부 오류", "UNAUTHENTICATED": "다시 로그인 필요"]
            parts.append(outcomes[outcome] ?? outcome)
        }
        if let status = row["http_status"] as? Int, status > 0 { parts.append("HTTP \(status)") }
        if let stage = row["stage"] as? String, !stage.isEmpty { parts.append(stage) }
        if let type = row["error_type"] as? String, !type.isEmpty { parts.append(type) }
        return parts.filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private func updateServerChecks(_ state: [String: Any]) {
        diagnosticStatus = state.filter { $0.key != "accounts" }
        currentAccountMessage = (state["running"] as? Bool == true)
            ? "현재 실행 · \(state["media_mode"] as? Bool == true ? "감상" : "일반"): \(state["profile"] as? String ?? "확인 중")"
            : "현재 실행 중인 계정 없음"
        if let checks = state["startup_checks"] as? [String: Any] {
            let labels = ["protocol": "게임 통신 규격", "catalog": "기본 목록", "master": "마스터 파일",
                "storage": "저장 공간", "http": "파일 서버", "grpc": "게임 서버",
                "resources": "게임 리소스", "account": "계정"]
            let names = ["ready": "준비됨", "blocked": "실패", "missing": "누락",
                "attention": "확인 필요", "not_checked": "미검사", "stopped": "중지"]
            let scope = checks["scope"] as? String ?? "not_run"
            let prefix = scope == "previous_run" ? "이전 실행의 검사" : (scope == "current_run" ? "현재 실행의 검사" : "아직 실행하지 않았습니다")
            let lines = (checks["checks"] as? [[String: Any]] ?? []).compactMap { row -> String? in
                guard let id = row["id"] as? String, let phase = row["state"] as? String else { return nil }
                let code = row["code"] as? String ?? ""
                return "\(labels[id] ?? id): \(names[phase] ?? phase)\(code.isEmpty ? "" : " · " + Self.settingsCodeDescription(code))"
            }
            startupChecksMessage = ([prefix] + lines + ["서버 준비 상태이며 실제 게임 재생 검증은 아닙니다."]).joined(separator: "\n")
        }
        if let history = state["durable_history"] as? [String: Any] {
            let available = history["available"] as? Bool ?? false
            let load = history["load_state"] as? String ?? ""
            let lines = (history["records"] as? [[String: Any]] ?? []).suffix(20).map(Self.historyDescription)
            let prefix = !available ? "오류 기록 보관에 접근하지 못했습니다."
                : (load == "recovered_invalid" ? "이전 기록 파일을 읽지 못해 새 기록을 시작했습니다." : "재실행 후에도 보관되는 최근 기록")
            durableHistoryMessage = ([prefix] + (lines.isEmpty ? ["보관된 기록 없음"] : lines)).joined(separator: "\n")
        }
    }

    func refreshAccounts(offset: Int = 0, restoreOffset: Int = 0) {
        sendAccount("accounts_status", payload: ["offset": max(0, offset), "restore_offset": max(0, restoreOffset)])
    }
    func previousAccounts() { refreshAccounts(offset: max(0, accountOffset - 24), restoreOffset: restoreOffset) }
    func moreAccounts() { if let offset = nextAccountOffset { refreshAccounts(offset: offset, restoreOffset: restoreOffset) } }
    func previousRestorePoints() { refreshAccounts(offset: accountOffset, restoreOffset: max(0, restoreOffset - 16)) }
    func moreRestorePoints() { if let offset = nextRestoreOffset { refreshAccounts(offset: accountOffset, restoreOffset: offset) } }

    private func targetProfile() -> String? {
        let name = newAccountProfile.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, name.utf8.count <= 64, !name.contains("/"), !name.contains("\\"),
              name.unicodeScalars.allSatisfy({ !CharacterSet.controlCharacters.contains($0) }) else {
            alertMessage = "새 계정 이름을 1~64 UTF-8바이트로 입력해 주세요. 경로 문자와 제어 문자는 사용할 수 없습니다."
            return nil
        }
        return name
    }
    func createAccount() {
        guard let profile = targetProfile() else { return }
        let name = newAccountManagerName.trimmingCharacters(in: .whitespacesAndNewlines)
        sendAccount("accounts_create", payload: ["mode": accountMode, "profile": profile,
            "manager_name": name.isEmpty ? profile : name])
    }
    func cloneAccount() {
        guard let source = selectedManagedAccount, let profile = targetProfile() else { return }
        sendAccount("accounts_clone", payload: ["mode": source.mode, "source_profile": source.profile,
            "profile": profile, "expected_revision": source.revision])
    }
    func selectAccount() {
        guard let row = selectedManagedAccount else { return }
        var payload: [String: Any] = ["mode": row.mode, "profile": row.profile, "expected_revision": row.revision]
        if let revision = accountSelectionRevision { payload["selection_revision"] = revision }
        sendAccount("accounts_select", payload: payload)
    }
    func exportAccount() {
        guard let row = selectedManagedAccount, !accountPending else { return }
        let panel = NSSavePanel()
        panel.allowedFileTypes = ["zip"]
        panel.nameFieldStringValue = "IdolyPride-Account-backup.zip"
        panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        guard panel.runModal() == .OK, let url = panel.url else { return }
        sendAccount("accounts_export", payload: ["mode": row.mode, "profile": row.profile,
            "expected_revision": row.revision], destination: url.path)
    }
    func previewAccountImport() {
        guard !accountPending else { return }
        let panel = NSOpenPanel()
        panel.allowedFileTypes = ["zip"]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        guard panel.runModal() == .OK, let url = panel.url else { return }
        accountPreviewToken = nil; accountPreviewMessage = ""
        sendAccount("accounts_preview", payload: ["path": url.path])
    }
    func importAccount(replacing: Bool) {
        guard let token = accountPreviewToken, !accountPending else { return }
        var payload: [String: Any] = ["token": token, "mode": accountMode, "replace": replacing]
        if replacing {
            guard !running, !busy, !canStop, let target = selectedManagedAccount else {
                alertMessage = "게임을 종료하고 서버를 중지한 뒤 계정을 교체해 주세요."; return
            }
            let warning = NSAlert()
            warning.messageText = "선택한 계정을 백업 내용으로 교체할까요?"
            warning.informativeText = "\(target.profile)의 현재 상태를 복구 지점으로 보관한 뒤 교체합니다."
            warning.addButton(withTitle: "교체"); warning.addButton(withTitle: "취소")
            guard warning.runModal() == .alertFirstButtonReturn else { return }
            payload["profile"] = target.profile
            payload["expected_revision"] = target.revision
        } else {
            guard let profile = targetProfile() else { return }
            payload["profile"] = profile; payload["expected_revision"] = NSNull()
        }
        sendAccount("accounts_import", payload: payload)
    }
    func restoreAccount() {
        guard !running, !busy, !canStop, let target = selectedManagedAccount,
              !selectedRestorePoint.isEmpty, !accountPending else { return }
        let warning = NSAlert()
        warning.messageText = "선택한 복구 지점으로 되돌릴까요?"
        warning.informativeText = "대상 계정: \(target.profile). 현재 상태도 복구 지점으로 보관합니다."
        warning.addButton(withTitle: "복구"); warning.addButton(withTitle: "취소")
        guard warning.runModal() == .alertFirstButtonReturn else { return }
        sendAccount("accounts_restore", payload: ["id": selectedRestorePoint, "mode": target.mode,
            "profile": target.profile, "expected_revision": target.revision])
    }
    func clearServerHistory() {
        let warning = NSAlert()
        warning.messageText = "보관된 서버 기록을 지울까요?"
        warning.informativeText = "게임 계정과 리소스는 변경하지 않습니다."
        warning.addButton(withTitle: "기록 지우기"); warning.addButton(withTitle: "취소")
        guard warning.runModal() == .alertFirstButtonReturn else { return }
        sendAccount("settings_clear_history", payload: [:])
    }
    func exportDiagnostics() {
        let panel = NSSavePanel()
        panel.allowedFileTypes = ["json"]
        panel.nameFieldStringValue = "IdolyPride-diagnostics.json"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let snapshot: [String: Any] = ["schema": 1, "runtime": diagnosticStatus, "server_logs": logs]
        guard let bytes = try? JSONSerialization.data(withJSONObject: snapshot, options: [.prettyPrinted, .sortedKeys]) else {
            alertMessage = "진단 기록을 만들지 못했습니다."; return
        }
        DispatchQueue.global(qos: .utility).async { [weak self] in
            do {
                try bytes.write(to: url, options: .atomic)
                DispatchQueue.main.async { self?.accountMessage = "진단·서버 기록을 JSON 하나로 저장했습니다." }
            } catch {
                DispatchQueue.main.async { self?.alertMessage = "진단 기록을 저장하지 못했습니다." }
            }
        }
    }

    func officialText(_ ko: String, _ en: String, _ ja: String) -> String {
        officialUILanguage == "ja" ? ja : officialUILanguage == "ko" ? ko : en
    }
    var officialNormalAccounts: [ManagedAccount] { accounts.filter { $0.mode == "normal" } }
    var officialCanFetch: Bool {
        officialState == "verified" && officialJobID != nil && !officialPreview.isEmpty && !officialPending && !officialBusy
    }
    var officialCanApply: Bool {
        officialState == "ready" && officialJobID != nil && !officialPending && !officialBusy
            && !running && !busy && !canStop && !accountPending
    }
    var officialStatusText: String {
        switch officialNotice {
        case "invalid_id": return officialText("인계 ID는 영문·숫자·_·- 1~64자로 입력해 주세요.", "Use 1–64 letters, digits, _ or - for the transfer ID.", "引き継ぎIDは英数字・_・-の1～64文字で入力してください。")
        case "invalid_password": return officialText("비밀번호는 앞뒤 공백 없이 ASCII 1~128자로 입력해 주세요.", "Use 1–128 ASCII characters without leading or trailing spaces.", "パスワードは前後に空白を付けずASCII 1～128文字で入力してください。")
        case "stopped_required": return officialText("게임을 종료하고 이 서버를 완전히 중지한 뒤 적용해 주세요.", "Quit the game and fully stop this server before applying.", "ゲームを終了し、このサーバーを完全に停止してから適用してください。")
        case "invalid_profile": return officialText("저장 슬롯 이름은 슬래시·제어문자 없이 UTF-8 64바이트 이내로 입력해 주세요.", "Use a slot name of up to 64 UTF-8 bytes without slashes or control characters.", "保存スロット名はスラッシュ・制御文字なし、UTF-8で64バイト以内にしてください。")
        case "select_target": return officialText("교체할 일반 계정을 선택해 주세요.", "Select a normal account to replace.", "置き換える通常アカウントを選択してください。")
        case "send_failed": return officialText("요청을 전달하지 못했습니다. 입력은 지웠으며 자동 재시도하지 않습니다.", "The request was not sent. Input was cleared; it will not retry automatically.", "要求を送信できませんでした。入力は消去され、自動再試行は行いません。")
        case "session_closed": return officialText("임시 인계 확인 세션을 종료했습니다. 이미 저장한 로컬 계정은 유저 관리에 남습니다.", "The temporary transfer session ended. Any local account already saved remains in user management.", "一時引き継ぎ確認セッションを終了しました。保存済みのローカルアカウントはユーザー管理に残ります。")
        case "selected": return officialText("다음 일반 계정 선택과 감상 모드 끄기를 저장했습니다. 서버를 시작해 주세요.", "Saved the next normal account and turned off viewing mode. Start the server when ready.", "次回の通常アカウントを保存し、鑑賞モードをオフにしました。サーバーを起動してください。")
        default: break
        }
        if officialBusy && officialProgress == "applying" {
            return officialText("검증된 계정을 로컬에 저장하고 있습니다.", "Saving the verified account locally.", "検証済みアカウントをローカルに保存しています。")
        }
        if let code = officialErrorCode {
            switch code {
            case "transfer_rejected", "transfer_id_invalid", "transfer_password_invalid":
                return officialText("인계 ID 또는 비밀번호를 확인하고 새 확인을 시작해 주세요.", "Check the transfer ID and password, then start a new verification.", "引き継ぎIDとパスワードを確認し、新しい確認を開始してください。")
            case "verification_expired", "official_session_expired", "verification_consumed", "official_job_missing", "official_job_mismatch":
                return officialText("확인 자료가 만료되었거나 더 이상 사용할 수 없습니다. 인계 정보를 다시 확인해 주세요.", "Verification data expired or is no longer usable. Verify the transfer credentials again.", "確認データが期限切れ、または使用できなくなりました。引き継ぎ情報を再確認してください。")
            case "official_maintenance":
                return officialText("공식 서비스가 점검 중입니다. 나중에 직접 다시 시도해 주세요.", "The official service is under maintenance. Try again manually later.", "公式サービスはメンテナンス中です。後で手動で再試行してください。")
            case "official_reauthentication_required":
                return officialText("공식 인증을 다시 확인해야 합니다. 새 인계 확인을 시작해 주세요.", "Official authentication must be checked again. Start a new transfer verification.", "公式認証の再確認が必要です。新しい引き継ぎ確認を開始してください。")
            case "official_master_mismatch", "official_catalog_changed", "official_protocol_changed", "account_protocol_schema_differs":
                return officialText("공식 자료와 로컬 자료가 일치하지 않아 저장을 중단했습니다. 자료를 확인한 뒤 다시 시도해 주세요.", "Official and local data do not match, so saving was stopped. Check the data before trying again.", "公式データとローカルデータが一致しないため保存を停止しました。データを確認してから再試行してください。")
            case "account_revision_conflict", "account_target_exists", "account_target_missing":
                return officialText("저장 대상이 바뀌었습니다. 계정 목록을 새로 불러오거나 새 슬롯 이름을 선택해 주세요.", "The save target changed. Refresh the account list or choose a new slot name.", "保存先が変更されました。一覧を更新するか、新しいスロット名を選んでください。")
            case "official_server_running", "official_server_starting":
                return officialText("게임을 종료하고 서버가 완전히 중지된 뒤 적용해 주세요.", "Quit the game and fully stop the server before applying.", "ゲームを終了し、サーバーを完全に停止してから適用してください。")
            default:
                return officialText("공식 계정 작업을 완료하지 못했습니다. 상태를 확인한 뒤 직접 다시 시도해 주세요.", "The official account task did not complete. Check its status before trying again manually.", "公式アカウント処理を完了できませんでした。状態を確認し、必要なら手動で再試行してください。")
            }
        }
        switch officialState {
        case "checking": return officialText("공식 인계 정보를 확인하고 있습니다.", "Checking official transfer credentials.", "公式の引き継ぎ情報を確認しています。")
        case "verified": return officialText("확인된 계정입니다. 아래 요약을 확인한 뒤 공식 로그인·내려받기를 요청해 주세요.", "Review the verified account below, then request official transfer login and download.", "確認されたアカウントです。要約を確認してから公式引き継ぎログイン・取得を要求してください。")
        case "fetching": return officialStageText
        case "ready": return officialText("검증된 공식 계정 자료를 준비했습니다. 로컬 저장 대상과 교체 여부를 확인해 주세요.", "Verified official account data is ready. Review the local destination and replacement choice.", "検証済みの公式アカウントデータを準備しました。保存先と置き換えの選択を確認してください。")
        case "completed": return officialText("일반 계정으로 저장했습니다. 자동으로 계정이나 감상 모드를 바꾸지 않았습니다.", "Saved as a normal account. Account selection and viewing mode were not changed automatically.", "通常アカウントとして保存しました。アカウント選択と鑑賞モードは自動変更していません。")
        case "cancelled": return officialText("작업을 취소하고 임시 인증 자료를 지웠습니다.", "Cancelled the task and cleared temporary authentication data.", "処理を取り消し、一時認証データを消去しました。")
        case "failed": return officialText("공식 계정 작업을 완료하지 못했습니다. 자동 재시도하지 않습니다.", "The official account task did not complete. It will not retry automatically.", "公式アカウント処理を完了できませんでした。自動再試行は行いません。")
        default: return officialText("인계 ID·비밀번호로 공식 JP 계정을 확인하고 이 Mac의 일반 계정으로 가져옵니다.", "Inspect an official JP account with its transfer ID and password, then import it into a normal local slot.", "引き継ぎIDとパスワードで公式JPアカウントを確認し、このMacの通常スロットに取り込みます。")
        }
    }
    var officialCompletionNotice: String {
        guard officialState == "completed", officialImportedAccount != nil else { return "" }
        var lines: [String] = []
        if officialWarningCodes.contains("account_temporary_cleanup_pending") {
            lines.append(officialText("계정 저장은 완료했습니다. 임시 가져오기 파일 일부를 아직 정리하지 못했습니다. 계정을 다시 가져올 필요는 없습니다.", "The account was saved. Some temporary import files still need cleanup. Do not import the account again.", "アカウントの保存は完了しました。一部の一時取り込みファイルは未整理です。再取り込みは不要です。"))
        }
        if officialAccountListRefreshRequired {
            lines.append(officialText("계정 저장은 완료했지만 목록을 갱신하지 못했습니다. 계정 목록을 새로고침해 주세요. 다시 가져올 필요는 없습니다.", "The account was saved, but the account list could not be refreshed. Refresh the list; do not import it again.", "アカウントの保存は完了しましたが、一覧を更新できませんでした。一覧を更新してください。再取り込みは不要です。"))
        }
        return lines.joined(separator: "\n")
    }
    var officialStageText: String {
        switch officialProgress {
        case "transferring", "firebase", "login": return officialText("공식 인계 로그인 중", "Official transfer login in progress", "公式引き継ぎログイン中")
        case "master", "catalog_check": return officialText("공식 마스터 자료 확인 중", "Checking official master data", "公式マスターデータを確認中")
        case "account", "collected", "staging": return officialText("계정 자료 내려받기·검증 중", "Downloading and validating account data", "アカウントデータを取得・検証中")
        default: return officialText("공식 계정 작업 처리 중", "Processing official account task", "公式アカウント処理中")
        }
    }
    var officialPreviewText: String {
        var lines: [String] = []
        if let name = officialPreview["manager_name"] as? String {
            lines.append(officialText("매니저", "Manager", "マネージャー") + ": " + name)
        }
        if let identifier = officialPreview["public_id"] as? String {
            lines.append(officialText("공개 게임 ID", "Public game ID", "公開ゲームID") + ": " + identifier)
        }
        if let level = officialPreview["manager_level"] as? Int { lines.append(officialText("레벨", "Level", "レベル") + ": \(level)") }
        let inventory = officialPreview["inventory"] as? [String: Any] ?? [:]
        for (key, ko, en, ja) in [("cards", "카드", "Cards", "カード"), ("items", "아이템 종류", "Item types", "アイテム種類"), ("photos", "포토", "Photos", "フォト")] {
            if let count = inventory[key] as? Int { lines.append(officialText(ko, en, ja) + ": \(count)") }
        }
        return lines.joined(separator: "\n")
    }
    private func updateOfficialJob(_ job: [String: Any], privateSummary: Bool) {
        let states = ["idle", "checking", "verified", "fetching", "ready", "completed", "failed", "cancelled"]
        guard let state = job["state"] as? String, states.contains(state) else { return }
        officialState = state
        officialProgress = job["progress"] as? String ?? "preparing"
        officialBusy = job["busy"] as? Bool ?? false
        officialJobID = job["job_id"] as? String
        officialExpiry = max(0, min(600, job["expires_in_seconds"] as? Int ?? 0))
        officialErrorCode = job["error_code"] as? String
        if privateSummary { officialPreview = job["preview"] as? [String: Any] ?? [:] }
        if ["idle", "failed", "cancelled"].contains(state) { officialPreview = [:] }
    }
    func inspectOfficial(userID: String, password: String) {
        guard !officialPending, !officialBusy, !busy else { return }
        guard !userID.isEmpty, userID.utf8.count <= 64, userID.unicodeScalars.allSatisfy({
            (65...90).contains($0.value) || (97...122).contains($0.value) || (48...57).contains($0.value) || $0.value == 95 || $0.value == 45
        }) else { officialNotice = "invalid_id"; return }
        guard (1...128).contains(password.utf8.count), password.trimmingCharacters(in: .whitespacesAndNewlines) == password,
              password.unicodeScalars.allSatisfy({ $0.value >= 32 && $0.value < 127 }) else { officialNotice = "invalid_password"; return }
        officialPreview = [:]; officialImportedAccount = nil; officialNotice = ""; officialErrorCode = nil
        officialWarningCodes = []; officialAccountListRefreshRequired = false
        sendOfficial("official_inspect", payload: ["user_id": userID, "password": password, "platform": officialPlatform])
    }
    func fetchOfficial() {
        guard officialCanFetch, let job = officialJobID else { return }
        officialNotice = ""; sendOfficial("official_fetch", payload: ["job_id": job])
    }
    func cancelOfficial() {
        guard !officialPending, let job = officialJobID else { return }
        officialPreview = [:]; sendOfficial("official_cancel", payload: ["job_id": job])
    }
    func refreshOfficial() { if !officialPending { sendOfficial("official_status", payload: [:]) } }
    func applyOfficial() {
        guard officialCanApply, let job = officialJobID else { officialNotice = "stopped_required"; return }
        var payload: [String: Any] = ["job_id": job, "replace": officialReplace]
        if officialReplace {
            guard let target = officialNormalAccounts.first(where: { $0.profile == officialReplaceProfile }) else { officialNotice = "select_target"; return }
            let alert = NSAlert(); alert.messageText = officialText("일반 계정을 교체하시겠습니까?", "Replace this normal account?", "この通常アカウントを置き換えますか？")
            alert.informativeText = officialText("게임을 종료했는지 확인해 주세요. 선택한 슬롯의 진행·보유 항목을 교체하며 직전 상태의 복구점을 자동으로 남깁니다.", "Ensure the game is closed. This replaces the selected slot's progress and inventory and creates an automatic restore point first.", "ゲームが終了していることを確認してください。選択した進行・所持項目を置き換え、直前の復元ポイントを自動作成します。")
            alert.addButton(withTitle: officialText("교체", "Replace", "置き換え")); alert.addButton(withTitle: officialText("취소", "Cancel", "キャンセル"))
            guard alert.runModal() == .alertFirstButtonReturn else { return }
            payload["profile"] = target.profile; payload["expected_revision"] = target.revision
        } else {
            let name = officialTargetProfile.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !name.isEmpty, name.utf8.count <= 64, !name.contains("/"), !name.contains("\\"),
                  name.unicodeScalars.allSatisfy({ !CharacterSet.controlCharacters.contains($0) }) else { officialNotice = "invalid_profile"; return }
            payload["profile"] = name; payload["expected_revision"] = NSNull()
        }
        officialNotice = ""; sendOfficial("official_apply", payload: payload)
    }
    func useOfficialImportForNextStart() {
        guard let row = officialImportedAccount, !running, !busy, !canStop, !accountPending, !officialPending, !officialBusy else { officialNotice = "stopped_required"; return }
        var payload: [String: Any] = ["mode": "normal", "profile": row.profile, "expected_revision": row.revision]
        if let revision = accountSelectionRevision { payload["selection_revision"] = revision }
        sendAccount("accounts_select", payload: payload)
        if accountPending { officialActivationProfile = row.profile }
    }
    private func sendOfficial(_ action: String, payload: [String: Any]) {
        guard !shutdownRequested, !officialPending, let writer = input?.fileHandleForWriting, child?.isRunning == true else { officialNotice = "send_failed"; return }
        officialRequestSerial = officialRequestSerial >= Int(Int32.max) ? 1 : officialRequestSerial + 1
        var command = payload; command["action"] = action; command["request_id"] = officialRequestSerial
        var bytes = Data()
        defer { bytes.resetBytes(in: 0..<bytes.count); command.removeAll(keepingCapacity: false) }
        do {
            bytes = try JSONSerialization.data(withJSONObject: command); bytes.append(10)
            guard Self.nonblockingWrite(bytes, fileDescriptor: writer.fileDescriptor) else { officialNotice = "send_failed"; return }
            officialPending = true; pendingOfficialID = officialRequestSerial; pendingOfficialAction = action
        } catch { officialNotice = "send_failed" }
    }
    private func consumeOfficial(_ event: [String: Any], kind: String) {
        guard let identifier = event["request_id"] as? Int, identifier == pendingOfficialID,
              event["action"] as? String == pendingOfficialAction else { return }
        let action = pendingOfficialAction
        pendingOfficialID = nil; pendingOfficialAction = nil; officialPending = false
        if kind == "official_error" {
            officialErrorCode = event["code"] as? String ?? "official_operation_failed"
            officialPreview = [:]; return
        }
        guard let result = event["result"] as? [String: Any], result["action"] as? String == action,
              let job = result["job"] as? [String: Any] else { officialErrorCode = "official_response_invalid"; officialPreview = [:]; return }
        officialNotice = ""; updateOfficialJob(job, privateSummary: true)
        if action == "official_apply", officialState == "completed" {
            if let state = result["status"] as? [String: Any] { updateAccounts(state) }
            if let row = result["account"] as? [String: Any] { officialImportedAccount = ManagedAccount(row) }
            officialWarningCodes = (result["warning_codes"] as? [String] ?? []).filter {
                ["account_temporary_cleanup_pending", "account_status_refresh_required"].contains($0)
            }
            officialAccountListRefreshRequired = result["status_refresh_required"] as? Bool == true
                || officialWarningCodes.contains("account_status_refresh_required")
        }
    }

    var eventFeedbackText: String {
        if eventPending { return officialText("로컬 이벤트 설정을 저장·확인하고 있습니다.", "Saving or checking local event settings.", "ローカルイベント設定を保存・確認しています。") }
        if eventInvalidFile { return officialText("저장 파일을 읽지 못했습니다. 기존 파일을 자동으로 덮어쓰지 않습니다.", "The saved file is invalid. It will not be overwritten automatically.", "保存ファイルを読み取れません。自動で上書きしません。") }
        if eventErrorCode != nil {
            if eventErrorCode == "event_settings_revision_conflict" {
                return officialText("다른 곳에서 설정이 바뀌었습니다. 저장값을 다시 불러온 뒤 변경해 주세요. 미저장 입력은 현재 화면에 남아 있습니다.", "Settings changed elsewhere. Reload saved values before editing again. Unsaved input remains on this screen.", "別の場所で設定が変更されました。保存値を再読み込みしてから変更してください。未保存の入力はこの画面に残ります。")
            }
            return officialText("설정을 저장하지 못했습니다. 입력과 기존 적용값을 유지합니다.", "Settings could not be saved. Input and the effective settings are preserved.", "設定を保存できませんでした。入力と適用中の値を保持します。")
        }
        if eventDraftDirty { return officialText("미저장 변경이 남아 있습니다.", "Unsaved changes remain.", "未保存の変更があります。") }
        if eventRestartRequired { return officialText("저장했습니다. 게임을 종료하고 서버를 다시 시작하면 적용됩니다.", "Saved. Quit the game and restart the server to apply.", "保存しました。ゲームを終了し、サーバーを再起動すると適用されます。") }
        if !eventCatalogAvailable { return officialText("지원 이벤트 자료를 준비하지 못했습니다. 서버 준비 후 다시 불러와 주세요.", "Supported event data is unavailable. Reload after the server data is prepared.", "対応イベントのデータを準備できません。サーバーデータの準備後に再読み込みしてください。") }
        return officialText("선택과 기간은 자동 저장됩니다. 이벤트 진행은 초기화하지 않습니다.", "Selections and periods save automatically. Event progress is preserved.", "選択と期間は自動保存されます。イベントの進行は初期化しません。")
    }
    func eventEnabled(_ id: String) -> Bool { eventDraft.contains { $0["event_id"] as? String == id } }
    func eventEnabledBinding(_ id: String) -> Binding<Bool> {
        Binding(get: { self.eventEnabled(id) }, set: { enabled in
            guard !self.eventPending, !self.eventInvalidFile else { return }
            var rows = self.eventDraft.filter { $0["event_id"] as? String != id }
            if enabled {
                guard self.eventCatalogAvailable, self.eventRows.contains(where: { $0.id == id && $0.supported }) else { return }
                let start = Int(Date().timeIntervalSince1970 * 1000)
                rows.append(["event_id": id, "start_time_ms": start, "end_time_ms": start + 30 * 86400000])
            }
            self.eventDraft = rows.sorted { ($0["event_id"] as? String ?? "") < ($1["event_id"] as? String ?? "") }
            self.eventDraftDirty = true; self.saveEventDraft()
        })
    }
    func eventDateBinding(_ id: String, start: Bool) -> Binding<Date> {
        let key = start ? "start_time_ms" : "end_time_ms"
        return Binding(get: {
            let value = self.eventDraft.first { $0["event_id"] as? String == id }?[key] as? Int
            return value.map { Date(timeIntervalSince1970: Double($0) / 1000) } ?? Date()
        }, set: { date in
            guard !self.eventPending, !self.eventInvalidFile,
                  let index = self.eventDraft.firstIndex(where: { $0["event_id"] as? String == id }) else { return }
            let milliseconds = date.timeIntervalSince1970 * 1000
            guard milliseconds.isFinite, milliseconds >= 0, milliseconds <= 9007199254740991 else { return }
            var rows = self.eventDraft; rows[index][key] = Int(milliseconds)
            self.eventDraft = rows; self.eventDraftDirty = true; self.saveEventDraft()
        })
    }
    func eventEffectiveText(_ id: String) -> String {
        if !eventHasEffective { return officialText("현재 적용: 서버 중지", "Effective now: server stopped", "現在の適用: サーバー停止中") }
        guard let row = eventEffective.first(where: { $0["event_id"] as? String == id }),
              let start = row["start_time_ms"] as? Int, let end = row["end_time_ms"] as? Int else {
            return officialText("현재 적용: 꺼짐", "Effective now: off", "現在の適用: オフ")
        }
        let formatter = DateFormatter(); formatter.dateStyle = .medium; formatter.timeStyle = .short
        formatter.locale = Locale(identifier: officialUILanguage)
        return officialText("현재 적용: ", "Effective now: ", "現在の適用: ")
            + formatter.string(from: Date(timeIntervalSince1970: Double(start) / 1000)) + " – "
            + formatter.string(from: Date(timeIntervalSince1970: Double(end) / 1000))
    }
    func clearEventSelection() {
        guard !eventPending, !eventInvalidFile else { return }
        eventDraft = []; eventDraftDirty = true; saveEventDraft()
    }
    func refreshEvents() { if !eventPending { sendEvent("events_status", payload: [:]) } }
    func saveEventDraft() {
        guard !eventPending, !eventInvalidFile, eventErrorCode != "event_settings_revision_conflict" else { return }
        sendEvent("events_save", payload: ["settings": ["schema": 1, "revision": eventRevision,
            "love_events": eventDraft], "expected_revision": eventRevision])
    }
    private func updateEventSettings(_ value: [String: Any], replaceDraft: Bool = false) {
        if !replaceDraft && (eventPending || eventDraftDirty) { return }
        guard let saved = value["saved"] as? [String: Any], let revision = saved["revision"] as? Int,
              let rows = saved["love_events"] as? [[String: Any]],
              let catalog = value["catalog"] as? [String: Any] else { return }
        let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        if !replaceDraft && data == eventSnapshotData { return }
        eventSnapshotData = data
        eventRows = (catalog["events"] as? [[String: Any]] ?? []).compactMap(LocalLoveEvent.init)
        eventCatalogAvailable = catalog["available"] as? Bool == true
        eventInvalidFile = value["invalid_settings_file"] as? Bool == true
        eventRestartRequired = value["restart_required"] as? Bool == true
        eventHasEffective = value["effective"] is [String: Any]
        eventEffective = (value["effective"] as? [String: Any])?["love_events"] as? [[String: Any]] ?? []
        eventRevision = revision; eventDraft = rows; eventDraftDirty = false; eventErrorCode = nil
    }
    private func sendEvent(_ action: String, payload: [String: Any]) {
        guard !shutdownRequested, !eventPending, let writer = input?.fileHandleForWriting, child?.isRunning == true else { return }
        eventRequestSerial = eventRequestSerial >= Int(Int32.max) ? 1 : eventRequestSerial + 1
        var command = payload; command["action"] = action; command["request_id"] = eventRequestSerial
        if action == "events_save" {
            // Only this private Mac wire is compact. The engine expands each
            // triple before the common settings validator/CAS operation.
            guard var settings = payload["settings"] as? [String: Any],
                  let rows = settings["love_events"] as? [[String: Any]] else { eventErrorCode = "event_settings_invalid"; return }
            var compact: [[Any]] = []
            for row in rows {
                guard let id = row["event_id"] as? String, let start = row["start_time_ms"] as? Int,
                      let end = row["end_time_ms"] as? Int else { eventErrorCode = "event_settings_invalid"; return }
                compact.append([id, start, end])
            }
            settings["love_events"] = compact; command["settings"] = settings
        }
        do {
            var bytes = try JSONSerialization.data(withJSONObject: command); bytes.append(10)
            guard bytes.count <= 512 else { eventErrorCode = "event_settings_command_invalid"; return }
            guard Self.nonblockingWrite(bytes, fileDescriptor: writer.fileDescriptor) else { eventErrorCode = "event_settings_io"; return }
            eventPending = true; pendingEventID = eventRequestSerial; pendingEventAction = action
        } catch { eventErrorCode = "event_settings_invalid" }
    }
    private func consumeEvents(_ event: [String: Any], kind: String) {
        guard let id = event["request_id"] as? Int, id == pendingEventID,
              event["action"] as? String == pendingEventAction else { return }
        pendingEventID = nil; pendingEventAction = nil; eventPending = false
        if kind == "events_error" { eventErrorCode = event["code"] as? String ?? "event_settings_io"; return }
        guard let value = event["result"] as? [String: Any] else { eventErrorCode = "event_settings_invalid"; return }
        updateEventSettings(value, replaceDraft: true)
    }

    private func sendAccount(_ action: String, payload: [String: Any], destination: String? = nil) {
        guard !shutdownRequested, !accountPending, let writer = input?.fileHandleForWriting,
              child?.isRunning == true else { return }
        accountRequestSerial = accountRequestSerial >= Int(Int32.max) ? 1 : accountRequestSerial + 1
        var command = payload
        command["action"] = action; command["request_id"] = accountRequestSerial
        if let destination = destination { command["destination"] = destination }
        do {
            var bytes = try JSONSerialization.data(withJSONObject: command); bytes.append(10)
            guard Self.nonblockingWrite(bytes, fileDescriptor: writer.fileDescriptor) else {
                alertMessage = "계정 요청을 전달하지 못했습니다. 이름과 파일 경로가 길면 짧은 이름의 ZIP을 Downloads에 두고 다시 선택해 주세요."
                return
            }
            pendingAccountID = accountRequestSerial; pendingAccountAction = action
            accountPending = true; accountMessage = "계정 작업을 준비하고 있습니다."
        } catch { alertMessage = "계정 요청을 만들지 못했습니다." }
    }
    private func consumeAccount(_ event: [String: Any], kind: String) {
        guard let identifier = event["request_id"] as? Int, identifier == pendingAccountID,
              event["action"] as? String == pendingAccountAction else { return }
        if kind == "account_progress" {
            if let received = event["received_bytes"] as? Int, let total = event["total_bytes"] as? Int, total > 0 {
                accountMessage = "계정 ZIP 저장 중 · \(received) / \(total)바이트"
            } else { accountMessage = "계정 자료를 준비·검증하고 있습니다." }
            return
        }
        let action = pendingAccountAction
        let activationProfile = officialActivationProfile; officialActivationProfile = nil
        pendingAccountID = nil; pendingAccountAction = nil; accountPending = false
        if kind == "account_error" {
            let code = event["code"] as? String ?? "account_operation_failed"
            let messages = ["account_server_running": "게임을 종료하고 서버를 중지한 뒤 교체·복구해 주세요.",
                "account_operation_busy": "이전 계정 작업이 끝난 뒤 다시 시도해 주세요.",
                "account_server_starting": "서버 시작이 끝난 뒤 다시 시도해 주세요."]
            accountMessage = messages[code] ?? "계정 작업을 완료하지 못했습니다. 새로고침 후 다시 확인해 주세요."
            alertMessage = accountMessage + "\n" + code
            return
        }
        guard let result = event["result"] as? [String: Any], result["ok"] as? Bool == true else {
            accountMessage = "계정 응답을 확인하지 못했습니다."; return
        }
        if let state = result["status"] as? [String: Any] {
            updateAccounts(state)
            if action == "accounts_status", state["stale"] as? Bool != true {
                officialAccountListRefreshRequired = false
                officialWarningCodes.removeAll { $0 == "account_status_refresh_required" }
            }
            if action == "accounts_select", let profile = activationProfile,
                  (state["selected"] as? [String: String])?["normal"] == profile {
                mediaMode = false; accountMode = "normal"; selectedAccountProfile = profile
                officialNotice = "selected"
            }
        }
        if action == "accounts_preview", let token = result["token"] as? String,
              let archive = result["archive"] as? [String: Any] {
            accountPreviewToken = token
            if let mode = archive["mode"] as? String, ["normal", "media"].contains(mode) { accountMode = mode }
            accountPreviewMessage = "선택한 계정 ZIP · \(archive["mode"] as? String ?? "") · \(archive["profile"] as? String ?? "") · \(archive["bytes"] as? Int ?? 0)바이트"
            accountMessage = "미리보기를 확인한 뒤 새 계정으로 가져오거나 선택 계정을 교체해 주세요."
        } else {
            let messages = ["accounts_status": "계정과 복구 지점 목록을 갱신했습니다.",
                "accounts_create": "새 계정을 만들었습니다.", "accounts_clone": "계정을 복제했습니다.",
                "accounts_select": "다음 서버 시작 계정을 저장했습니다. 게임을 종료하고 서버를 재시작해 주세요.",
                "accounts_export": "계정 ZIP을 저장했습니다. 게임 리소스는 별도 ZIP으로 옮깁니다.",
                "accounts_import": "계정을 가져왔습니다. 선택 후 서버를 다시 시작해 주세요.",
                "accounts_restore": "계정을 복구했습니다. 서버를 다시 시작해 주세요.",
                "settings_clear_history": "보관된 서버 기록을 지웠습니다."]
            accountMessage = messages[action ?? ""] ?? "계정 작업을 완료했습니다."
            if action == "accounts_import" { accountPreviewToken = nil; accountPreviewMessage = "" }
        }
    }

    func resources(_ action: String) {
        guard running, !shutdownRequested else { alertMessage = "먼저 서버를 시작해 주세요."; return }
        guard !resourceJobActive, !resourcePending else { return }
        var extra: [String: Any] = ["platform": resourcePlatform]
        if action == "resources_download" {
            guard [1, 2, 4, 8].contains(resourceParallelism) else { return }
            extra["parallelism"] = resourceParallelism
        }
        sendResource(action, extra: extra)
    }

    func cancelResources() {
        guard !resourcePending, let identifier = resourceJobID else { return }
        sendResource("resources_cancel", extra: ["job_id": identifier])
    }

    func exportResources() {
        guard running, !resourceJobActive, !resourcePending else { return }
        let panel = NSSavePanel()
        panel.allowedFileTypes = ["zip"]
        guard let exports = resourceExportsDirectory() else { return }
        panel.directoryURL = exports
        panel.nameFieldStringValue = "IdolyPride-resources-\(resourcePlatform).zip"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        sendResource("resources_export", extra: ["platform": resourcePlatform, "path": url.path])
    }

    private func downloadsResourceDirectory() -> URL? {
        FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first?
            .appendingPathComponent("IdolyPride", isDirectory: true)
    }

    var canChangeResourceLocation: Bool {
        !running && !busy && !canStop && !resourceJobActive && !resourcePending && !shutdownRequested
    }

    var resourceLocationBinding: Binding<Bool> {
        Binding(get: { self.resourcesInDownloads }, set: { enabled in
            guard self.canChangeResourceLocation else { return }
            self.resourcesInDownloads = enabled
        })
    }

    private func externalResourceDirectory() -> URL? {
        guard !invalidResourceLocation else { return nil }
        guard !resourceDirectoryPath.isEmpty else { return downloadsResourceDirectory() }
        guard resourceDirectoryPath.hasPrefix("/"), !resourceDirectoryPath.contains("\0") else { return nil }
        return URL(fileURLWithPath: resourceDirectoryPath, isDirectory: true)
    }

    private var selectedResourceDirectory: URL? {
        resourcesInDownloads ? externalResourceDirectory() : dataDirectory
    }

    var resourceLocationDescription: String {
        guard let root = selectedResourceDirectory else { return "저장된 보관 경로를 확인해 주세요. 폴더 선택 또는 기본 위치 복원으로 다시 지정할 수 있습니다." }
        return (resourcesInDownloads ? "직접 보관 위치: " : "앱 전용 보관 위치: ") + root.path
    }

    private static func validatedResourceDirectory(_ candidate: URL, create: Bool) -> URL? {
        guard candidate.isFileURL else { return nil }
        let root = candidate.standardizedFileURL.resolvingSymlinksInPath()
        guard root.path.hasPrefix("/"), !root.path.contains("\0"), root.path.utf8.count <= 4096 else { return nil }
        do {
            if create { try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true) }
            let values = try root.resourceValues(forKeys: [.isDirectoryKey])
            guard values.isDirectory == true, FileManager.default.isWritableFile(atPath: root.path) else { return nil }
            // Use the longest Boolean spellings when reserving one atomic IPC line.
            let command: [String: Any] = ["action": "start", "experimental_main_live": false,
                "media_mode": false, "download_missing_resources": false, "resource_cache_dir": root.path]
            guard try JSONSerialization.data(withJSONObject: command).count + 1 <= 512 else { return nil }
            return root
        } catch { return nil }
    }

    private func saveResourceDirectory(_ candidate: URL, restoreDefault: Bool = false) {
        guard canChangeResourceLocation else { return }
        guard let root = Self.validatedResourceDirectory(candidate, create: true) else {
            alertMessage = "쓰기 가능한 리소스 폴더를 선택해 주세요. 폴더 접근 권한과 경로 길이를 확인해 주세요. 이전 보관 위치는 유지됩니다."
            return
        }
        if restoreDefault {
            UserDefaults.standard.removeObject(forKey: "resourceDirectoryPath")
            resourceDirectoryPath = ""
        } else {
            UserDefaults.standard.set(root.path, forKey: "resourceDirectoryPath")
            resourceDirectoryPath = root.path
        }
        invalidResourceLocation = false
        resourcesInDownloads = true
        resourceLocationMessage = "보관 위치가 저장되었습니다. 다음 서버 시작부터 적용됩니다. 기존 파일은 이전 폴더에 유지되며 자동으로 옮기거나 삭제하지 않습니다."
    }

    func chooseResourceDirectory() {
        guard canChangeResourceLocation else { return }
        let panel = NSOpenPanel()
        panel.title = "리소스 보관 폴더 선택"
        panel.prompt = "이 폴더 사용"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.directoryURL = externalResourceDirectory()
        guard panel.runModal() == .OK, let selected = panel.url else { return }
        saveResourceDirectory(selected)
    }

    func restoreDefaultResourceDirectory() {
        guard canChangeResourceLocation, let root = downloadsResourceDirectory() else { return }
        saveResourceDirectory(root, restoreDefault: true)
    }

    private func resourceExportsDirectory() -> URL? {
        guard let root = downloadsResourceDirectory() else {
            alertMessage = "Downloads 보관 폴더를 찾지 못했습니다."; return nil
        }
        let exports = root.appendingPathComponent("exports", isDirectory: true)
        do { try FileManager.default.createDirectory(at: exports, withIntermediateDirectories: true) }
        catch { alertMessage = "Downloads 보관 폴더에 접근하지 못했습니다. 폴더 접근 권한을 확인해 주세요."; return nil }
        return exports
    }

    func revealResources() {
        guard let folder = selectedResourceDirectory else { return }
        do { try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true) }
        catch { alertMessage = "리소스 보관 폴더에 접근하지 못했습니다."; return }
        NSWorkspace.shared.open(folder)
    }

    func importResources() {
        guard running, !resourceJobActive, !resourcePending else { return }
        let panel = NSOpenPanel()
        panel.allowedFileTypes = ["zip"]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        guard panel.runModal() == .OK, let url = panel.url else { return }
        sendResource("resources_import", extra: ["platform": resourcePlatform, "path": url.path])
    }

    private func sendResource(_ action: String, extra: [String: Any]) {
        guard running, !shutdownRequested, !resourcePending, let writer = input?.fileHandleForWriting else { return }
        var command = extra
        command["action"] = action
        do {
            var data = try JSONSerialization.data(withJSONObject: command)
            data.append(10)
            guard Self.nonblockingWrite(data, fileDescriptor: writer.fileDescriptor) else {
                alertMessage = "리소스 요청을 전달하지 못했습니다. 경로가 길면 Downloads 아래의 짧은 이름을 선택해 주세요."
                return
            }
            resourcePending = true
            resourceMessage = "리소스 작업을 준비하고 있습니다."
        } catch { alertMessage = "리소스 요청을 만들지 못했습니다." }
    }

    func presentationBinding<Value: Equatable>(_ key: WritableKeyPath<ClientPresentationSettings, Value>) -> Binding<Value> {
        Binding(get: { self.presentation[keyPath: key] }, set: { value in
            guard self.presentation[keyPath: key] != value else { return }
            var changed = self.presentation
            changed[keyPath: key] = value
            do {
                self.presentation = try changed.saving(to: self.presentationFile)
                self.presentationInvalid = false
                self.presentationSaveFailed = false
            } catch {
                self.presentationSaveFailed = true
                self.alertMessage = ClientPresentationFeedback.saveFailed.message
            }
            self.updatePresentationFeedback()
        })
    }

    private func updatePresentationFeedback() {
        let fresh = statusPolling.fresh(at: ProcessInfo.processInfo.systemUptime)
        presentationFeedback = .observed(running: running && fresh && !shutdownRequested,
            settings: presentation, client: presentationClient, invalidFile: presentationInvalid,
            saveFailed: presentationSaveFailed)
    }

    private func pollStatus() {
        guard !shutdownRequested, child?.isRunning == true else { return }
        updatePresentationFeedback()
        if officialJobID != nil && !officialPending && !["completed", "cancelled", "failed"].contains(officialState) { refreshOfficial() }
        if statusPolling.lastStatusUptime != nil && !statusPolling.fresh(at: ProcessInfo.processInfo.systemUptime) {
            presentationClient = nil
            status = "서버 응답을 기다리고 있습니다."
        }
        // One outstanding command keeps a stalled engine from filling its stdin
        // pipe. A later status event resumes polling without a request backlog.
        guard statusPolling.beginRequest() else { return }
        send("status", reportFailure: false)
    }

    private func checkpoint(_ phase: String) {
        guard smoke, let report = smokeReport else { return }
        phases.append(phase)
        let destination = report.deletingPathExtension().appendingPathExtension("checkpoint.json")
        let value: [String: Any] = ["phase": phase, "phases": Array(phases.suffix(40)),
            "window_count": NSApp?.windows.count ?? 0, "engine_running": child?.isRunning ?? false]
        do {
            try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
            let data = try JSONSerialization.data(withJSONObject: value, options: .prettyPrinted)
            try data.write(to: destination, options: .atomic)
        } catch { fputs("Cannot write native app checkpoint.\n", stderr) }
    }

    func applicationReady() {
        checkpoint("application_did_finish_launching")
        launch()
    }

    func launch() {
        guard !launched else { return }
        launched = true
        checkpoint("engine_launch_requested")
        guard let resources = Bundle.main.resourceURL else {
            fail("앱 리소스를 찾지 못했습니다.")
            return
        }
        let engine = resources.appendingPathComponent("runtime/IdolyServerEngine")
        let serverData = resources.appendingPathComponent("ServerData.zip")
        let process = Process()
        let writer = Pipe(), reader = Pipe(), errorReader = Pipe()
        // Fixed JSON commands fit in Darwin's minimum PIPE_BUF (512 bytes).
        // A full engine pipe must never stall the main AppKit thread.
        let inputFD = writer.fileHandleForWriting.fileDescriptor
        let inputFlags = fcntl(inputFD, F_GETFL)
        guard inputFlags >= 0, fcntl(inputFD, F_SETFL, inputFlags | O_NONBLOCK) == 0 else {
            fail("서버 엔진 연결을 준비하지 못했습니다.")
            return
        }
        signal(SIGPIPE, SIG_IGN)
        process.executableURL = engine
        process.arguments = ["--json-control", "--data-dir", dataDirectory.path,
                             "--server-data", serverData.path]
        process.standardInput = writer
        process.standardOutput = reader
        process.standardError = errorReader
        var environment = ProcessInfo.processInfo.environment
        for key in ["PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"] {
            environment.removeValue(forKey: key)
        }
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = environment
        reader.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { self?.consume(data) }
        }
        errorReader.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            let text = String(decoding: data, as: UTF8.self)
            DispatchQueue.main.async { self?.appendLog(text) }
        }
        process.terminationHandler = { [weak self] finished in
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.running = false
                self.busy = false
                self.canStop = false
                self.resourcePending = false
                self.accountPending = false
                self.pendingAccountID = nil; self.pendingAccountAction = nil
                self.officialPending = false; self.officialBusy = false
                self.eventPending = false; self.pendingEventID = nil; self.pendingEventAction = nil
                self.pendingOfficialID = nil; self.pendingOfficialAction = nil; self.officialJobID = nil
                self.officialPreview = [:]; self.officialImportedAccount = nil
                self.officialWarningCodes = []; self.officialAccountListRefreshRequired = false
                self.officialState = "idle"; self.officialErrorCode = nil; self.officialNotice = "session_closed"
                self.statusTimer?.invalidate()
                self.statusTimer = nil
                self.statusPolling.reset()
                self.presentationClient = nil
                self.updatePresentationFeedback()
                if !self.shutdownRequested {
                    self.status = "서버 엔진이 종료되었습니다."
                    if finished.terminationStatus != 0 {
                        self.fail("서버 엔진을 실행하지 못했습니다. 앱을 다시 열어 주세요.")
                    }
                }
            }
        }
        child = process; input = writer; output = reader; errors = errorReader
        do {
            try process.run()
            statusTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
                DispatchQueue.main.async { self?.pollStatus() }
            }
            checkpoint("engine_process_started")
        } catch {
            fail("서버 엔진을 실행하지 못했습니다. 앱 파일을 다시 확인해 주세요.")
        }
        if smoke {
            DispatchQueue.main.asyncAfter(deadline: .now() + 45) { [weak self] in
                guard let self = self, !self.shutdownRequested, !self.smokeFinished else { return }
                self.checkpoint("smoke_deadline")
                self.finishSmoke(success: false)
            }
        }
    }

    private func consume(_ data: Data) {
        guard !shutdownRequested else { return }
        pending.append(data)
        while let end = pending.firstIndex(of: 10) {
            let line = pending.prefix(upTo: end)
            pending.removeSubrange(...end)
            guard let event = try? JSONSerialization.jsonObject(with: Data(line)) as? [String: Any],
                  let kind = event["event"] as? String else {
                appendLog(String(decoding: line, as: UTF8.self)); continue
            }
            switch kind {
            case "log": appendLog(event["message"] as? String ?? "")
            case "error": fail(event["message"] as? String ?? "서버 작업에 실패했습니다.")
            case "resource_error":
                resourcePending = false
                alertMessage = event["message"] as? String ?? "리소스 작업을 완료하지 못했습니다."
            case "resource_result":
                resourcePending = false
                resourceMessage = event["message"] as? String ?? "리소스 작업 상태가 갱신되었습니다."
            case "account_result", "account_error", "account_progress":
                consumeAccount(event, kind: kind)
            case "official_result", "official_error":
                consumeOfficial(event, kind: kind)
            case "events_result", "events_error":
                consumeEvents(event, kind: kind)
            case "status":
                guard let state = event["status"] as? [String: Any] else { continue }
                statusPolling.received(at: ProcessInfo.processInfo.systemUptime)
                running = state["running"] as? Bool ?? false
                if running && (state["experimental_main_live"] as? Bool == true) { experimentalLiveObserved = true }
                busy = state["starting"] as? Bool ?? false
                canStop = state["can_stop"] as? Bool ?? (running || busy)
                status = running ? "로컬 서버가 실행 중입니다." : (busy ? "서버를 시작하고 있습니다." : "서버가 중지되어 있습니다.")
                presentationClient = (state["presentation"] as? [String: Any])?["client"] as? [String: Any]
                updateResourceStatus(state)
                updateServerChecks(state)
                if let accountStatus = state["accounts"] as? [String: Any] { updateAccounts(accountStatus) }
                if let officialStatus = state["official_import"] as? [String: Any] { updateOfficialJob(officialStatus, privateSummary: false) }
                if let eventStatus = state["event_settings"] as? [String: Any] { updateEventSettings(eventStatus) }
                if !accountsInitiallyRequested && !busy && !smoke {
                    accountsInitiallyRequested = true
                    refreshAccounts()
                }
                updatePresentationFeedback()
                checkpoint(running ? "server_running" : (busy ? "server_starting" : "server_stopped"))
                if smoke { advanceSmoke() }
            default: break
            }
        }
    }

    private func advanceSmoke() {
        guard smoke, !smokeFinished, !shutdownRequested else { return }
        let visible = NSApp.windows.contains { $0.isVisible }
        if visible && !visibleWindowObserved {
            visibleWindowObserved = true
            checkpoint("visible_window_observed")
        }
        if !visible {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in self?.advanceSmoke() }
            return
        }
        guard !busy else { return }
        if running && !smokeStopping {
            smokeStarted = true; smokeStopping = true; stop()
        } else if !running && smokeStopping {
            finishSmoke(success: smokeStarted && !canStop)
        } else if !running && !smokeStarted {
            start()
        }
    }

    private func send(_ action: String, experimental: Bool? = nil, mediaMode: Bool? = nil,
                      downloadMissingResources: Bool? = nil, resourceCacheDirectory: String? = nil,
                      reportFailure: Bool = true) {
        guard !shutdownRequested else { return }
        guard let writer = input?.fileHandleForWriting, child?.isRunning == true else {
            if reportFailure { fail("서버 엔진에 연결하지 못했습니다. 앱을 다시 열어 주세요.") }
            return
        }
        do {
            var command: [String: Any] = ["action": action]
            if let enabled = experimental { command["experimental_main_live"] = enabled }
            if let enabled = mediaMode { command["media_mode"] = enabled }
            if let enabled = downloadMissingResources { command["download_missing_resources"] = enabled }
            if let directory = resourceCacheDirectory { command["resource_cache_dir"] = directory }
            var data = try JSONSerialization.data(withJSONObject: command)
            data.append(10)
            guard Self.nonblockingWrite(data, fileDescriptor: writer.fileDescriptor) else {
                if reportFailure { fail("서버 엔진에 요청을 전달하지 못했습니다.") }
                return
            }
        } catch {
            if reportFailure { fail("서버 엔진에 요청을 전달하지 못했습니다.") }
        }
    }

    private static func nonblockingWrite(_ data: Data, fileDescriptor: Int32) -> Bool {
        guard !data.isEmpty, data.count <= 512 else { return false }
        let flags = fcntl(fileDescriptor, F_GETFL)
        guard flags >= 0, flags & O_NONBLOCK != 0 else { return false }
        return data.withUnsafeBytes { bytes in
            // <= PIPE_BUF is atomic: EAGAIN writes nothing. Retry only a
            // bounded number of signal interruptions, never wait for capacity.
            for _ in 0..<3 {
                let count = write(fileDescriptor, bytes.baseAddress, bytes.count)
                if count == bytes.count { return true }
                if count >= 0 || errno != EINTR { return false }
            }
            return false
        }
    }

    func start() {
        guard !running && !busy && !canStop && !accountPending && !officialPending && !officialBusy && !eventPending else { return }
        var cache: String?
        if resourcesInDownloads {
            guard let selected = externalResourceDirectory(),
                  let folder = Self.validatedResourceDirectory(selected, create: true) else {
                alertMessage = "리소스 보관 폴더에 접근하지 못했습니다. 쓰기 권한과 경로 길이를 확인하거나 다른 보관 폴더를 선택해 주세요."
                return
            }
            cache = folder.path
        }
        busy = true; status = "서버를 시작하고 있습니다."
        send("start", experimental: experimentalMainLive, mediaMode: mediaMode,
             downloadMissingResources: downloadMissingResources, resourceCacheDirectory: cache)
    }
    func stop() {
        busy = true; status = "서버를 중지하고 있습니다."; send("stop")
    }
    func openGame() {
        guard running else { alertMessage = "먼저 서버를 시작해 주세요."; return }
        clientLaunchFailed = false
        // PlayCover 3.1.0 has no app-launch URL/CLI. Its own launch() prepares
        // settings, entitlements, signing and aliases before opening the game.
        if let game = NSRunningApplication.runningApplications(withBundleIdentifier: "game.qualiarts.idolypride.local")
                .first(where: { !$0.isTerminated }) {
            clientLaunchMessage = game.activate(options: .activateIgnoringOtherApps)
                ? "실행 중인 아이프라로 전환했습니다."
                : "아이프라가 이미 실행 중입니다. Dock에서 게임 창을 선택해 주세요."
            return
        }
        let runningPlayCover = NSRunningApplication.runningApplications(withBundleIdentifier: "io.playcover.PlayCover")
            .first(where: { !$0.isTerminated })
        if let playcover = runningPlayCover, playcover.activate(options: .activateIgnoringOtherApps) {
            clientLaunchMessage = "PlayCover에서 ‘아이프라 로컬’을 두 번 클릭해 실행해 주세요."
            return
        }
        let workspace = NSWorkspace.shared
        let candidates: [URL?] = [runningPlayCover?.bundleURL, workspace.urlForApplication(withBundleIdentifier: "io.playcover.PlayCover"),
            URL(fileURLWithPath: "/Applications/PlayCover.app", isDirectory: true),
            FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications/PlayCover.app", isDirectory: true)]
        var applications: [URL] = []
        for candidate in candidates.compactMap({ validPlayCover($0) }) {
            let normalized = candidate.standardizedFileURL.resolvingSymlinksInPath()
            if !applications.contains(normalized) { applications.append(normalized) }
        }
        guard !applications.isEmpty else {
            clientLaunchFailed = true
            clientLaunchMessage = "PlayCover를 찾지 못했습니다. PlayCover를 설치한 위치에서 먼저 연 뒤 다시 눌러 주세요."
            alertMessage = clientLaunchMessage
            return
        }
        clientLaunchMessage = "PlayCover에서 ‘아이프라 로컬’을 두 번 클릭해 실행해 주세요."
        openPlayCover(applications, index: 0)
    }

    private func openPlayCover(_ candidates: [URL], index: Int) {
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.promptsUserIfNeeded = false
        NSWorkspace.shared.openApplication(at: candidates[index], configuration: configuration) { [weak self] _, error in
            guard let error = error as NSError? else { return }
            DispatchQueue.main.async {
                guard let self = self else { return }
                if index + 1 < candidates.count {
                    self.openPlayCover(candidates, index: index + 1)
                    return
                }
                self.clientLaunchFailed = true
                self.clientLaunchMessage = "PlayCover를 열지 못했습니다 (OS \(error.code)). PlayCover 아이콘으로 열어 게임을 실행해 주세요."
                self.alertMessage = self.clientLaunchMessage
            }
        }
    }

    private func validPlayCover(_ candidate: URL?) -> URL? {
        guard let candidate = candidate else { return nil }
        var directory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: candidate.path, isDirectory: &directory), directory.boolValue,
              let bundle = Bundle(url: candidate), bundle.bundleIdentifier == "io.playcover.PlayCover",
              let executable = bundle.executableURL, FileManager.default.fileExists(atPath: executable.path) else { return nil }
        return candidate
    }
    func revealData() {
        try? FileManager.default.createDirectory(at: dataDirectory, withIntermediateDirectories: true)
        NSWorkspace.shared.open(dataDirectory)
    }
    private func appendLog(_ text: String) {
        logs += text.hasSuffix("\n") ? text : text + "\n"
        if logs.count > 60_000 { logs = String(logs.suffix(50_000)) }
    }
    private func fail(_ message: String) {
        resourcePending = false
        busy = false; status = message; appendLog(message)
        if !smoke { alertMessage = message }
    }
    private func finishSmoke(success: Bool) {
        guard !smokeFinished else { return }
        smokeFinished = true
        checkpoint(success ? "smoke_complete" : "smoke_failed")
        if let destination = smokeReport {
            let report: [String: Any] = ["gui_started": visibleWindowObserved,
                "window_visible": NSApp.windows.contains { $0.isVisible }, "server_started": smokeStarted,
                "server_stopped": success && !running && !canStop, "game_client_tested": false,
                "experimental_main_live_requested": experimentalMainLive,
                "experimental_main_live_observed": experimentalLiveObserved]
            do {
                try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
                let data = try JSONSerialization.data(withJSONObject: report, options: .prettyPrinted)
                try data.write(to: destination, options: .atomic)
            } catch { fputs("Cannot write native app smoke report.\n", stderr) }
        }
        NSApp.terminate(nil)
    }
    func shutdown(_ completion: @escaping () -> Void) {
        if shutdownFinished { completion(); return }
        shutdownCompletions.append(completion)
        guard !shutdownRequested else { return }
        shutdownRequested = true
        officialPreview = [:]; officialJobID = nil
        busy = true
        canStop = false
        status = "서버를 종료하고 있습니다."
        statusTimer?.invalidate()
        statusTimer = nil
        presentationClient = nil
        updatePresentationFeedback()
        checkpoint("shutdown_requested")
        let process = child
        let writer = input?.fileHandleForWriting
        let reader = output?.fileHandleForReading
        let errorReader = errors?.fileHandleForReading
        let quit = Data("{\"action\":\"quit\"}\n".utf8)
        // A full stdin pipe must not block AppKit or prevent escalation from
        // starting. The write/close operation has its own worker.
        DispatchQueue.global(qos: .userInitiated).async {
            if process?.isRunning == true { try? writer?.write(contentsOf: quit) }
            try? writer?.close()
        }
        DispatchQueue.global(qos: .userInitiated).async {
            if let process = process {
                let deadline = ProcessInfo.processInfo.systemUptime + 8
                while process.isRunning && ProcessInfo.processInfo.systemUptime < deadline {
                    Thread.sleep(forTimeInterval: 0.05)
                }
                if process.isRunning {
                    process.terminate()
                    let finalDeadline = ProcessInfo.processInfo.systemUptime + 2
                    while process.isRunning && ProcessInfo.processInfo.systemUptime < finalDeadline {
                        Thread.sleep(forTimeInterval: 0.05)
                    }
                    if process.isRunning { kill(process.processIdentifier, SIGKILL) }
                }
            }
            // Request application exit before optional FileHandle cleanup:
            // removing a handler can wait for an in-flight Foundation read.
            DispatchQueue.main.async { self.finishShutdown() }
            reader?.readabilityHandler = nil
            errorReader?.readabilityHandler = nil
        }
    }

    private func finishShutdown() {
        guard !shutdownFinished else { return }
        shutdownFinished = true
        checkpoint("shutdown_cleanup_complete")
        let completions = shutdownCompletions
        shutdownCompletions.removeAll()
        for completion in completions { completion() }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let model = ServerModel()
    private var window: NSWindow?
    private var quitPending = false
    private var readyToTerminate = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let controller = NSHostingController(rootView: ServerView(model: model))
        let visibleWindow = NSWindow(contentViewController: controller)
        visibleWindow.title = "아이프라 로컬 서버"
        visibleWindow.styleMask = [.titled, .closable, .miniaturizable, .resizable]
        visibleWindow.isReleasedWhenClosed = false
        visibleWindow.setContentSize(NSSize(width: 760, height: 520))
        visibleWindow.minSize = NSSize(width: 650, height: 450)
        visibleWindow.center()
        window = visibleWindow
        visibleWindow.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        model.applicationReady()
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if readyToTerminate { return .terminateNow }
        if !quitPending {
            quitPending = true
            model.shutdown {
                self.readyToTerminate = true
                sender.terminate(nil)
            }
        }
        // Keep the ordinary main run loop alive while owned-process cleanup
        // completes, then reissue Quit once it is safe to terminate.
        return .terminateCancel
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@MainActor
struct PresentationControls: View {
    @ObservedObject var model: ServerModel
    @State private var expanded = true

    private func picker<Value: Hashable>(_ title: String, selection: Binding<Value>,
            values: [Value], label: @escaping (Value) -> String) -> some View {
        HStack {
            Text(title).frame(width: 170, alignment: .leading)
            Picker(title, selection: selection) {
                ForEach(values, id: \.self) { value in Text(label(value)).tag(value) }
            }.labelsHidden().frame(width: 230)
            Spacer()
        }
    }

    var body: some View {
        DisclosureGroup("그래픽·촬영 화면", isExpanded: $expanded) {
            VStack(alignment: .leading, spacing: 10) {
                Text("그래픽 지원 IPA를 PlayCover에 별도로 설치해 주세요. 서버 실행 중에도 설정을 바꿀 수 있으며 게임의 적용 확인을 기다립니다.")
                    .font(.caption).foregroundStyle(.secondary)
                Toggle("사용자 그래픽 설정 사용", isOn: model.presentationBinding(\.customGraphics))
                VStack(alignment: .leading, spacing: 8) {
                    picker("그래픽 품질", selection: model.presentationBinding(\.quality),
                           values: ClientPresentationSettings.qualities) { value in
                        switch value {
                        case 10: return "낮음 (10)"
                        case 20: return "중간 (20)"
                        case 30: return "높음 (30)"
                        case 40: return "최고 (40)"
                        case 100: return "촬영용 (100)"
                        default: return "원본 유지 (0)"
                        }
                    }
                    picker("목표 프레임 수", selection: model.presentationBinding(\.targetFPS),
                           values: ClientPresentationSettings.frameRates) { $0 == 0 ? "원본 유지 (0)" : "\($0) fps" }
                    picker("3D 렌더 배율", selection: model.presentationBinding(\.renderScale),
                           values: Array(Set(ClientPresentationSettings.renderScales + [model.presentation.renderScale])).sorted()) {
                        $0 == 1 ? "1배 (기본)" : String(format: "%g배", $0)
                    }
                    picker("렌더 버퍼 최대 크기", selection: model.presentationBinding(\.maxBufferPixel),
                           values: Array(Set(ClientPresentationSettings.bufferSizes + [model.presentation.maxBufferPixel])).sorted()) {
                        $0 == 4096 ? "4096 px (기본)" : "\($0) px"
                    }
                    picker("가장자리 다듬기", selection: model.presentationBinding(\.antiAliasing),
                           values: ClientPresentationSettings.antiAliasingModes) { value in
                        switch value {
                        case 0: return "끔 (0)"
                        case 1: return "FXAA (1)"
                        case 2: return "SMAA (2)"
                        default: return "원본 유지 (-1)"
                        }
                    }
                    picker("캐릭터 그림자 해상도", selection: model.presentationBinding(\.shadowResolution),
                           values: ClientPresentationSettings.shadowSizes) { $0 == 0 ? "원본 유지 (0)" : "\($0)" }
                }.disabled(!model.presentation.customGraphics)
                Toggle("촬영·360 화면의 3D 표시 영역 확장", isOn: model.presentationBinding(\.expandPhotography))
                Text("기본 16:9 바깥에도 3D 장면을 렌더링합니다. 확대·잘라내기·늘이기 방식이 아닙니다. 그래픽 설정 사용 여부와 별도로 저장됩니다.")
                    .font(.caption).foregroundStyle(.secondary)
            }.padding(.top, 8)
        }.accessibilityIdentifier("presentation-controls")
        Text(model.presentationFeedback.message).font(.caption).textSelection(.enabled)
            .foregroundColor(model.presentationFeedback.confirmed ? .green : model.presentationFeedback.failed ? .orange : .secondary)
            .accessibilityIdentifier("presentation-status")
    }
}

@MainActor

struct AccountControls: View {
    @ObservedObject var model: ServerModel
    var body: some View {
        GroupBox("유저 관리 · 계정 백업") {
            VStack(alignment: .leading, spacing: 8) {
                Text(model.currentAccountMessage).font(.caption).textSelection(.enabled)
                Text(model.accountSelectionMessage).font(.caption).textSelection(.enabled)
                Picker("계정 종류", selection: model.accountModeBinding) {
                    Text("일반 진행").tag("normal")
                    Text("전체 해금 감상").tag("media")
                }.disabled(model.accountPending)
                Picker("관리할 계정", selection: $model.selectedAccountProfile) {
                    Text("계정 선택").tag("")
                    ForEach(model.visibleAccounts) { row in Text(row.profile).tag(row.profile) }
                }.disabled(model.accountPending)
                if let row = model.selectedManagedAccount, !row.summary.isEmpty {
                    Text(row.summary).font(.caption).foregroundStyle(.secondary)
                }
                HStack {
                    Button("새로고침") { model.refreshAccounts() }
                    Button("이전 계정") { model.previousAccounts() }
                    Button("다음 계정") { model.moreAccounts() }.disabled(model.nextAccountOffset == nil)
                }.disabled(model.accountPending)
                Text(model.accountPageMessage).font(.caption).foregroundStyle(.secondary)
                HStack {
                    TextField("새 저장 슬롯 이름", text: $model.newAccountProfile)
                    TextField("게임 내 매니저 이름 (새 계정)", text: $model.newAccountManagerName)
                }.disabled(model.accountPending)
                HStack {
                    Button("새 계정 만들기") { model.createAccount() }
                    Button("선택 계정 복제") { model.cloneAccount() }.disabled(model.selectedManagedAccount == nil)
                    Button("다음 시작 계정으로 선택") { model.selectAccount() }.disabled(model.selectedManagedAccount == nil)
                }.disabled(model.accountPending)
                HStack {
                    Button("계정 ZIP 내보내기…") { model.exportAccount() }.disabled(model.selectedManagedAccount == nil)
                    Button("계정 ZIP 가져오기 미리보기…") { model.previewAccountImport() }
                }.disabled(model.accountPending)
                if model.hasAccountPreview {
                    Text(model.accountPreviewMessage).font(.caption).textSelection(.enabled)
                    HStack {
                        Button("새 계정으로 가져오기") { model.importAccount(replacing: false) }
                        Button("선택 계정 교체") { model.importAccount(replacing: true) }
                            .disabled(model.running || model.busy || model.canStop || model.selectedManagedAccount == nil)
                    }.disabled(model.accountPending)
                }
                Picker("선택 계정의 복구 지점", selection: $model.selectedRestorePoint) {
                    Text("복구 지점 선택").tag("")
                    ForEach(model.visibleRestorePoints) { point in Text(point.created).tag(point.id) }
                }.disabled(model.accountPending)
                HStack {
                    Button("이전 복구 지점") { model.previousRestorePoints() }
                    Button("다음 복구 지점") { model.moreRestorePoints() }.disabled(model.nextRestoreOffset == nil)
                    Button("선택 지점으로 복구") { model.restoreAccount() }
                        .disabled(model.running || model.busy || model.canStop || model.selectedRestorePoint.isEmpty)
                }.disabled(model.accountPending)
                if model.accountPending { ProgressView().controlSize(.small) }
                Text(model.accountMessage).font(.caption).textSelection(.enabled)
                Text("계정 ZIP에는 계정·진행·게임 설정을 보관하며 다운로드 리소스는 포함하지 않습니다. 리소스 ZIP에는 계정이 없습니다. 선택은 해당 일반/감상 모드의 다음 계정에 적용됩니다. 사용할 감상 모드도 별도로 확인해 주세요. 복제는 게임 내 이름과 ID를 보존한 저장 분기입니다. 교체·복구는 게임 종료 후 서버를 중지한 상태에서 진행합니다.")
                    .font(.caption).foregroundStyle(.secondary)
            }.padding(.top, 6)
        }
    }
}


@MainActor
struct LocalLoveEventControls: View {
    @ObservedObject var model: ServerModel
    private func text(_ ko: String, _ en: String, _ ja: String) -> String { model.officialText(ko, en, ja) }
    var body: some View {
        GroupBox(text("이벤트 · 모시코이", "Events · Moshikoi", "イベント・もし恋")) {
            VStack(alignment: .leading, spacing: 10) {
                Picker(text("이 안내의 언어", "Language for this panel", "この案内の言語"), selection: $model.officialUILanguage) {
                    Text("한국어").tag("ko"); Text("English").tag("en"); Text("日本語").tag("ja")
                }
                Text(text("저장값은 다음 서버 시작부터 일반·감상 모드에 적용하며 진행은 모드별로 보관합니다.", "Saved values apply at the next server start in normal and viewing modes; progress is stored separately.", "保存値は次回のサーバー起動から通常・鑑賞モードに適用され、進行はモード別に保存します。"))
                    .font(.caption).fixedSize(horizontal: false, vertical: true)
                Text(text("기간은 이 기기에서 정하는 로컬 운영 기간입니다. 공식 종료 시각·기간은 확인되지 않았습니다. 켜면 지금부터 30일로 제안하며 최대 366일까지 편집할 수 있습니다.", "These are local server periods, not verified official dates. Enabling proposes 30 days from now; each period may be edited up to 366 days.", "この端末で指定するローカル運営期間です。公式の終了時刻・期間は未確認です。有効化時は現在から30日を提案し、最大366日まで編集できます。"))
                    .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                ForEach(model.eventRows) { row in
                    LocalLoveEventRow(model: model, row: row)
                }
                Text(model.eventFeedbackText).font(.caption).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                HStack {
                    Button(text("저장값 다시 불러오기", "Reload saved values", "保存値を再読み込み")) { model.refreshEvents() }.disabled(model.eventPending)
                    Button(text("다시 저장", "Retry saving", "保存を再試行")) { model.saveEventDraft() }
                        .disabled(model.eventPending || !model.eventDraftDirty || model.eventInvalidFile || model.eventErrorCode == "event_settings_revision_conflict")
                    Button(text("모두 끄기 · 진행 유지", "Turn all off · keep progress", "すべてオフ・進行を保持")) { model.clearEventSelection() }
                        .disabled(model.eventPending || model.eventInvalidFile || model.eventDraft.isEmpty)
                }
                if let code = model.eventErrorCode { Text(code).font(.caption).textSelection(.enabled) }
            }.padding(.top, 6).frame(maxWidth: .infinity, alignment: .leading)
        }.accessibilityIdentifier("local-love-event-controls")
    }
}

struct LocalLoveEventRow: View {
    @ObservedObject var model: ServerModel
    let row: LocalLoveEvent
    private func text(_ ko: String, _ en: String, _ ja: String) -> String { model.officialText(ko, en, ja) }
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Toggle(row.title, isOn: model.eventEnabledBinding(row.id))
                .fixedSize(horizontal: false, vertical: true)
                .disabled(model.eventPending || model.eventInvalidFile || (!model.eventEnabled(row.id) && (!model.eventCatalogAvailable || !row.supported)))
            if model.eventEnabled(row.id) {
                DatePicker(text("로컬 시작", "Local start", "ローカル開始"), selection: model.eventDateBinding(row.id, start: true), displayedComponents: [.date, .hourAndMinute])
                DatePicker(text("로컬 종료", "Local end", "ローカル終了"), selection: model.eventDateBinding(row.id, start: false), displayedComponents: [.date, .hourAndMinute])
            }
            Text(model.eventEffectiveText(row.id)).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            if !row.supported { Text(text("아직 지원 자료를 검증하지 못했습니다.", "Required data has not been validated.", "必要なデータをまだ検証できていません。" )).font(.caption) }
            Divider()
        }.disabled(model.eventPending || model.eventInvalidFile)
    }
}

struct OfficialImportControls: View {
    @ObservedObject var model: ServerModel
    @State private var transferID = ""
    @State private var transferPassword = ""
    private func text(_ ko: String, _ en: String, _ ja: String) -> String { model.officialText(ko, en, ja) }
    private var credentials: some View {
        VStack(alignment: .leading, spacing: 8) {
            Picker(text("공식 계정 플랫폼", "Official account platform", "公式アカウントのプラットフォーム"), selection: $model.officialPlatform) {
                Text("iOS").tag("ios"); Text("Android").tag("android")
            }
            TextField(text("공식 JP 인계 ID", "Official JP transfer ID", "公式JPの引き継ぎID"), text: $transferID)
                .textFieldStyle(.roundedBorder).accessibilityIdentifier("official-transfer-id")
            SecureField(text("인계 비밀번호", "Transfer password", "引き継ぎパスワード"), text: $transferPassword)
                .textFieldStyle(.roundedBorder).accessibilityIdentifier("official-transfer-password")
            Button(text("1. 공식 인계 정보 확인", "1. Check official transfer credentials", "1. 公式引き継ぎ情報を確認")) {
                model.inspectOfficial(userID: transferID, password: transferPassword)
                transferID = ""; transferPassword = ""
            }.fixedSize(horizontal: false, vertical: true)
                .disabled(model.officialPending || model.officialBusy || model.busy || model.accountPending)
            Text(text("확인은 공식 인계 인증 요청입니다. 다음 로그인·내려받기는 공식 계정의 로그인 상태에 영향을 줄 수 있습니다. ID·비밀번호는 저장하거나 기록하지 않으며 제출 후 입력칸을 지웁니다.",
                "Checking sends an official transfer authentication request. Transfer login and download can affect the official account's login state. ID and password are not saved or logged; input clears after submission.",
                "確認は公式の引き継ぎ認証要求です。ログイン・取得は公式アカウントのログイン状態に影響する場合があります。ID・パスワードは保存・記録せず、送信後に入力を消去します。"))
                .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }.disabled(model.officialPending || model.officialBusy)
    }
    private var destination: some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle(text("기존 일반 계정 교체", "Replace an existing normal account", "既存の通常アカウントを置き換える"), isOn: $model.officialReplace)
            if model.officialReplace {
                Picker(text("교체할 일반 계정", "Normal account to replace", "置き換える通常アカウント"), selection: $model.officialReplaceProfile) {
                    Text(text("계정 선택", "Select an account", "アカウントを選択")).tag("")
                    ForEach(model.officialNormalAccounts) { row in Text(row.profile).tag(row.profile) }
                }
                Text(text("직전 상태의 복구점을 자동 생성합니다. 대상과 버전이 바뀌면 교체를 거절합니다.", "An automatic restore point preserves the previous state. Replacement is rejected if the target revision changed.", "直前の復元ポイントを自動作成します。対象の版が変わると置き換えを拒否します。"))
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                TextField(text("새 일반 계정 저장 슬롯", "New normal account slot", "新しい通常アカウントの保存スロット"), text: $model.officialTargetProfile)
                    .textFieldStyle(.roundedBorder)
            }
            Text(text("게임을 종료하고 서버를 중지한 뒤 저장합니다. 공식 보유·진행 자료를 사용하며 새 시작 계정으로 대신 만들지 않습니다. 다운로드 리소스는 별도로 보관합니다.",
                "Quit the game and stop the server before saving. Official inventory and progress are used; no starter account replaces them. Downloaded resources are stored separately.",
                "ゲームを終了しサーバーを停止してから保存します。公式の所持・進行データを使い、初期アカウントに置き換えません。リソースは別途保管します。"))
                .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            Button(text("3. 검증된 자료를 일반 계정에 저장", "3. Save verified data as a normal account", "3. 検証済みデータを通常アカウントに保存")) { model.applyOfficial() }
                .fixedSize(horizontal: false, vertical: true).disabled(!model.officialCanApply)
        }.disabled(model.officialPending || model.officialBusy)
    }
    var body: some View {
        GroupBox(text("공식 JP 계정 가져오기", "Import an official JP account", "公式JPアカウントの取り込み")) {
            VStack(alignment: .leading, spacing: 10) {
                Picker(text("이 안내의 언어", "Language for this panel", "この案内の言語"), selection: $model.officialUILanguage) {
                    Text("한국어").tag("ko"); Text("English").tag("en"); Text("日本語").tag("ja")
                }
                credentials
                if !model.officialPreviewText.isEmpty {
                    Text(model.officialPreviewText).font(.caption).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                }
                if ["verified", "ready"].contains(model.officialState) {
                    Text(text("임시 확인 자료 만료까지", "Temporary data expires in", "一時確認データの有効期間") + " \(model.officialExpiry)s")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Button(text("2. 공식 인계 로그인·내려받기", "2. Official transfer login and download", "2. 公式引き継ぎログイン・取得")) { model.fetchOfficial() }
                    .fixedSize(horizontal: false, vertical: true).disabled(!model.officialCanFetch)
                if model.officialState == "ready" { destination }
                if model.officialState == "completed", let imported = model.officialImportedAccount {
                    Text(text("저장된 일반 계정", "Saved normal account", "保存した通常アカウント") + ": " + imported.profile)
                        .font(.caption).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                    if !model.officialCompletionNotice.isEmpty {
                        Text(model.officialCompletionNotice).font(.caption).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                    }
                    if model.officialAccountListRefreshRequired {
                        Button(text("계정 목록 새로고침", "Refresh account list", "アカウント一覧を更新")) { model.refreshAccounts() }
                            .disabled(model.accountPending || model.officialPending || model.officialBusy)
                    }
                    Button(text("다음 실행에서 이 일반 계정 사용 · 감상 모드 끄기", "Use this normal account next time and turn off viewing mode", "次回この通常アカウントを使用・鑑賞モードをオフ")) { model.useOfficialImportForNextStart() }
                        .disabled(model.running || model.busy || model.canStop || model.accountPending || model.officialPending)
                }
                HStack {
                    Button(text("상태 확인", "Refresh status", "状態を確認")) { model.refreshOfficial() }.disabled(model.officialPending)
                    Button(text("작업 취소", "Cancel task", "処理を取り消す")) {
                        transferID = ""; transferPassword = ""; model.cancelOfficial()
                    }.disabled(model.officialPending || ["idle", "completed", "cancelled", "failed"].contains(model.officialState))
                    Button(text("입력 지우기", "Clear input", "入力を消去")) { transferID = ""; transferPassword = "" }
                }
                VStack(alignment: .leading, spacing: 6) {
                    if model.officialPending || model.officialBusy { ProgressView().controlSize(.small) }
                    Text(model.officialStatusText).font(.caption).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                    if let code = model.officialErrorCode {
                        DisclosureGroup(text("오류 코드", "Error code", "エラーコード")) { Text(code).font(.caption).textSelection(.enabled) }
                    }
                }
            }.padding(.top, 6).frame(maxWidth: .infinity, alignment: .leading)
        }.accessibilityIdentifier("official-import-controls")
            .onDisappear { transferID = ""; transferPassword = "" }
    }
}

struct ServerView: View {
    @ObservedObject var model: ServerModel
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Image(systemName: "server.rack").font(.largeTitle).foregroundStyle(.purple)
                VStack(alignment: .leading, spacing: 5) {
                    Text("아이프라 로컬 서버").font(.title2.bold())
                    Text("이 Mac에서 실행하는 아이프라에 연결합니다.").foregroundStyle(.secondary)
                }
                Spacer()
                Circle().fill(model.running ? Color.green : Color.gray).frame(width: 12, height: 12)
            }
            Text(model.status).font(.headline).accessibilityIdentifier("server-status")
            HStack {
                Button("서버 시작") { model.start() }.disabled(model.running || model.busy || model.canStop || model.accountPending || model.officialPending || model.officialBusy || model.eventPending)
                Button("중지") { model.stop() }.disabled(!model.canStop)
                Button("PlayCover에서 열기") { model.openGame() }.disabled(!model.running)
                Spacer()
                Button("데이터 폴더") { model.revealData() }
            }
            Text(model.clientLaunchMessage).font(.caption).textSelection(.enabled)
                .foregroundColor(model.clientLaunchFailed ? .orange : .secondary)
            Text("서버 127.0.0.1:50051 · 리소스 127.0.0.1:8080").font(.caption).foregroundStyle(.secondary)
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text("연결용 IPA는 별도 파일입니다. 위 버튼으로 PlayCover를 연 뒤 게임을 선택해 실행합니다.")
                        .font(.caption).foregroundStyle(.secondary)
                    AccountControls(model: model)
                    LocalLoveEventControls(model: model)
                    OfficialImportControls(model: model)
                    DisclosureGroup("서버 준비 검사 · 이전 오류 기록") {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(model.startupChecksMessage).font(.caption).textSelection(.enabled)
                            Text(model.durableHistoryMessage).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                            HStack {
                                Button("진단·서버 기록 내보내기…") { model.exportDiagnostics() }
                                Button("보관 기록 지우기") { model.clearServerHistory() }.disabled(model.accountPending)
                            }
                        }.padding(.top, 6)
                    }
                    Toggle("감상용 전체 해금", isOn: $model.mediaMode)
                        .disabled(model.running || model.busy || model.canStop)
                    Text("감상용 저장은 일반 진행과 별도로 보관합니다. 모드를 바꾼 뒤에는 서버를 다시 시작하고 게임 타이틀에서 다시 로그인해 주세요. 기본값은 꺼짐입니다.")
                        .font(.caption).foregroundStyle(.secondary)
                    Toggle("첫 메인 라이브 실험 기능 사용", isOn: $model.experimentalMainLive)
                        .disabled(model.running || model.busy || model.canStop)
                    Text("첫 퀘스트만 지원하며 점수는 로컬 계산 규칙을 사용합니다. 공식 서버와 다를 수 있습니다. 기본값은 꺼짐입니다.")
                        .font(.caption).foregroundStyle(.secondary)
                    Toggle("없는 게임 리소스 내려받기", isOn: $model.downloadMissingResources)
                        .disabled(model.running || model.busy || model.canStop)
                    Text("게임에서 요청한 리소스 파일만 내려받아 이 기기에 보관합니다. 끄면 이미 보관한 파일만 제공합니다.")
                        .font(.caption).foregroundStyle(.secondary)
                    Text("튜토리얼 라이브는 원본 기록을 재생합니다.").font(.caption).foregroundStyle(.secondary)
                    DisclosureGroup("촬영 목록·의상·언어") {
                        VStack(alignment: .leading, spacing: 8) {
                            Toggle("라이브 촬영에서 영상 MV 숨기기", isOn: model.libraryBinding(\.hideVideoMV))
                            Text("3D 공연 목록을 유지하고 영상으로 재생하는 MV만 숨깁니다.")
                                .font(.caption).foregroundStyle(.secondary)
                            Picker("MV 정렬", selection: model.libraryBinding(\.mvSort)) {
                                Text("최근 공개순").tag("recent")
                                Text("오래된 공개순").tag("old")
                                Text("제목순").tag("title")
                                Text("ID순").tag("id")
                            }
                            Picker("의상 정렬", selection: model.libraryBinding(\.outfitSort)) {
                                Text("원본 획득순").tag("original")
                                Text("최근 공개순").tag("recent")
                                Text("오래된 공개순").tag("old")
                                Text("이름순").tag("title")
                                Text("ID순").tag("id")
                            }
                            Picker("게임 데이터 언어", selection: model.languageBinding) {
                                Text("日本語").tag("ja")
                                Text("한국어").tag("ko")
                                Text("English").tag("en")
                            }
                            Text("스토리·게임 데이터에 준비된 번역을 적용합니다. UI 언어를 바꾸려면 같은 언어의 클라이언트로 업데이트해 주세요. 번역이 없는 문구는 원문을 유지합니다.")
                                .font(.caption).foregroundStyle(.secondary)
                            Text(model.libraryMessage).font(.caption).foregroundStyle(.secondary)
                        }.padding(.top, 6)
                    }
                    DisclosureGroup("게임 리소스 보관·Downloads 내보내기") {
                        VStack(alignment: .leading, spacing: 8) {
                            Toggle("선택한 폴더에 리소스 직접 보관", isOn: model.resourceLocationBinding)
                                .disabled(!model.canChangeResourceLocation)
                            Text(model.resourceLocationDescription).font(.caption).textSelection(.enabled)
                            HStack {
                                Button("보관 폴더 변경…") { model.chooseResourceDirectory() }
                                Button("Downloads 기본 위치 복원") { model.restoreDefaultResourceDirectory() }
                            }.disabled(!model.canChangeResourceLocation)
                            Text(model.resourceLocationMessage).font(.caption).foregroundStyle(.secondary)
                            Text("기본 위치는 Downloads/IdolyPride입니다. 폴더를 선택하거나 기본 위치를 복원하면 직접 보관이 켜집니다. 체크를 해제하면 앱 전용 보관을 사용하며 계정·설정은 기존 앱 폴더에 유지합니다.")
                                .font(.caption).foregroundStyle(.secondary)
                            Button("리소스 보관 폴더 열기") { model.revealResources() }
                            Picker("보관할 리소스", selection: $model.resourcePlatform) {
                                Text("Mac·iOS").tag("ios")
                                Text("Android").tag("android")
                            }.disabled(model.resourceJobActive || model.resourcePending)
                            Picker("동시 다운로드 수", selection: $model.resourceParallelism) {
                                ForEach([1, 2, 4, 8], id: \.self) { count in
                                    Text(count == 4 ? "4개 (기본)" : "\(count)개").tag(count)
                                }
                            }.disabled(model.resourceJobActive || model.resourcePending)
                            HStack {
                                Button("목록·예상 용량 확인") { model.resources("resources_preview") }
                                    .disabled(model.resourceJobActive || model.resourcePending)
                                Button("전체 리소스 받기") { model.resources("resources_download") }
                                    .disabled(model.resourceJobActive || model.resourcePending)
                                Button("작업 취소") { model.cancelResources() }
                                    .disabled(!model.resourceJobActive || model.resourcePending)
                            }.disabled(!model.running)
                            HStack {
                                Button("Downloads에 내보내기") { model.exportResources() }
                                Button("보관 ZIP 가져오기") { model.importResources() }
                            }.disabled(!model.running || model.resourceJobActive || model.resourcePending)
                            Text(model.resourceMessage).font(.caption).textSelection(.enabled)
                            Text("게임 리소스 요청 · 서버 시작 후 누적").font(.caption.bold())
                            Text(model.resourceTransferMessage).font(.caption).textSelection(.enabled)
                            Text("포함된 목록의 원본 파일을 서버에 보관합니다. 전체 자료는 수십 GB가 될 수 있습니다. 다시 받으면 검증된 완료 파일부터 재사용하며, 전송 중인 파일의 바이트 단위 재개는 지원하지 않습니다. 내보낸 ZIP은 다른 서버로 가져올 수 있습니다.")
                                .font(.caption).foregroundStyle(.secondary)
                        }.padding(.top, 6)
                    }
                    Toggle("MV 진입·종료 시 화면 회전 대기", isOn: model.orientationWaitBinding)
                    Text(model.playbackMessage).font(.caption).foregroundStyle(.secondary)
                    Divider()
                    PresentationControls(model: model)
                    Divider()
                    Text("실행 기록").font(.subheadline.bold())
                    ScrollView {
                        Text(model.logs.isEmpty ? "서버를 시작하면 여기에 실행 상태가 표시됩니다." : model.logs)
                            .font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading).padding(10)
                    }.frame(height: 180).background(Color(nsColor: .textBackgroundColor))
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                    Text("앱을 종료하면 서버도 중지됩니다. 업데이트해도 데이터는 별도 폴더에 보관됩니다.")
                        .font(.caption).foregroundStyle(.secondary)
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
        }.padding(24).frame(minWidth: 650, minHeight: 450)
            .alert("아이프라 로컬 서버", isPresented: Binding(
                get: { model.alertMessage != nil }, set: { if !$0 { model.alertMessage = nil } })) {
                Button("확인") { model.alertMessage = nil }
            } message: { Text(model.alertMessage ?? "") }
    }
}

@main
struct IdolyLocalServerApp {
    @MainActor static func main() {
        let application = NSApplication.shared
        application.setActivationPolicy(.regular)
        let mainMenu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "아이프라 로컬 서버 종료", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        mainMenu.addItem(appItem)
        application.mainMenu = mainMenu
        let delegate = AppDelegate()
        application.delegate = delegate
        withExtendedLifetime(delegate) { application.run() }
    }
}
