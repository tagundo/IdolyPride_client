import AppKit
import Foundation
import SwiftUI
import Darwin

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
        guard !running && !busy && !canStop else { return }
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
    @State private var expanded = false

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
                Button("서버 시작") { model.start() }.disabled(model.running || model.busy || model.canStop)
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
