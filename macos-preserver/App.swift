import AppKit
import CoreFoundation
import Foundation
import SwiftUI
import Darwin

private struct AccountGroup: Identifiable {
    let id: Int
    let candidates: Int
    let currentCandidates: Int
}

@MainActor
private final class PreserverModel: ObservableObject {
    @Published private(set) var busy = true
    @Published private(set) var ready = false
    @Published private(set) var inspected = false
    @Published private(set) var status = "보존 도구를 준비하고 있습니다."
    @Published private(set) var matchedRows = 0
    @Published private(set) var validArchives = 0
    @Published private(set) var rejectedArchives = 0
    @Published private(set) var groups: [AccountGroup] = []
    @Published var selectedGroup: Int?
    @Published var allowVisit = false
    @Published private(set) var outputDirectory: URL?
    @Published private(set) var captureFinished = false
    @Published var alertMessage: String?

    private let maxLineBytes = 1024 * 1024
    private let smoke: Bool
    private let smokeReport: URL?
    private let smokeHome: URL?
    private var child: Process?
    private var input: Pipe?
    private var output: Pipe?
    private var errors: Pipe?
    private var pending = Data()
    private var launched = false
    private var shutdownRequested = false
    private var smokeFinished = false
    private var visibleWindowObserved = false
    private var offlineInspectionCompleted = false
    private var networkCaptureCalled = false
    private var inspectionPending = false
    private var captureInFlight = false

    init() {
        let arguments = ProcessInfo.processInfo.arguments
        func value(_ flag: String) -> String? {
            guard let index = arguments.firstIndex(of: flag), index + 1 < arguments.count else { return nil }
            return arguments[index + 1]
        }
        smoke = arguments.contains("--app-smoke")
        smokeReport = value("--smoke-report").map { URL(fileURLWithPath: $0) }
        smokeHome = value("--smoke-home").map { URL(fileURLWithPath: $0, isDirectory: true) }
    }

    var canCapture: Bool {
        ready && !busy && !smoke && inspected && validArchives > 0 && rejectedArchives == 0 && allowVisit && !captureFinished
            && outputDirectory != nil
            && (groups.count == 1 || selectedGroup.map { selected in groups.contains { $0.id == selected } } == true)
    }

    func applicationReady() {
        guard !launched else { return }
        launched = true
        if smoke {
            var directory: ObjCBool = false
            guard smokeReport != nil, let home = smokeHome,
                  FileManager.default.fileExists(atPath: home.path, isDirectory: &directory),
                  directory.boolValue,
                  home.standardizedFileURL != FileManager.default.homeDirectoryForCurrentUser.standardizedFileURL else {
                fail("점검용 임시 폴더를 확인하지 못했습니다.")
                return
            }
        }
        guard let resources = Bundle.main.resourceURL else {
            fail("앱 리소스를 찾지 못했습니다.")
            return
        }
        let process = Process()
        let writer = Pipe(), reader = Pipe(), errorReader = Pipe()
        process.executableURL = resources.appendingPathComponent("runtime/IdolyEventPreserverWorker")
        process.arguments = ["--worker", "--descriptor-set",
                             resources.appendingPathComponent("idolypride-6.1.1.pb").path,
                             "--roots-file", resources.appendingPathComponent("cacert.pem").path]
        if smoke { process.arguments?.append("--offline-only") }
        process.standardInput = writer
        process.standardOutput = reader
        process.standardError = errorReader
        var environment = ProcessInfo.processInfo.environment
        for key in Array(environment.keys) where key.hasPrefix("PYTHON") || key.hasPrefix("DYLD_") || key.hasPrefix("GRPC_") || key == "VIRTUAL_ENV" || key == "CONDA_PREFIX" {
            environment.removeValue(forKey: key)
        }
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        // Normal launches retain the user's environment. Only the explicit
        // offline CI smoke substitutes HOME with an existing temporary folder.
        if smoke, let home = smokeHome { environment["HOME"] = home.path }
        process.environment = environment
        reader.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { self?.consume(data) }
        }
        errorReader.fileHandleForReading.readabilityHandler = { handle in
            // Stderr can contain private third-party output. Drain and discard
            // every byte; it is never converted to text, displayed or saved.
            if handle.availableData.isEmpty { handle.readabilityHandler = nil }
        }
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.ready = false
                self.busy = false
                if !self.shutdownRequested && !self.smokeFinished {
                    self.fail("보존 도구가 종료되었습니다. 앱을 다시 열어 주세요.")
                }
            }
        }
        child = process
        input = writer
        output = reader
        errors = errorReader
        do {
            try process.run()
        } catch {
            fail("보존 도구를 실행하지 못했습니다. 앱 파일을 다시 확인해 주세요.")
        }
        if smoke {
            DispatchQueue.main.asyncAfter(deadline: .now() + 45) { [weak self] in
                guard let self = self, !self.smokeFinished else { return }
                self.finishSmoke(success: false)
            }
        }
    }

    private func count(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite,
              number.doubleValue >= 0, number.doubleValue <= 1_000_000,
              number.doubleValue.rounded(.towardZero) == number.doubleValue else { return nil }
        return number.intValue
    }

    private func flag(_ value: Any?) -> Bool? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) == CFBooleanGetTypeID() else { return nil }
        return number.boolValue
    }

    private func consume(_ data: Data) {
        guard !shutdownRequested else { return }
        guard data.count <= maxLineBytes else { protocolFailure(); return }
        pending.append(data)
        while let end = pending.firstIndex(of: 10) {
            let line = pending.prefix(upTo: end)
            pending.removeSubrange(...end)
            guard line.count <= maxLineBytes,
                  let event = try? JSONSerialization.jsonObject(with: Data(line)) as? [String: Any],
                  count(event["schema"]) == 1,
                  let kind = event["event"] as? String else {
                protocolFailure()
                return
            }
            switch kind {
            case "ready":
                guard !ready else { protocolFailure(); return }
                ready = true
                busy = false
                inspect()
            case "inspection": receiveInspection(event)
            case "progress":
                guard busy else { continue }
                status = progressLabel(event["code"] as? String)
            case "failure":
                fail(failureLabel(event["code"] as? String))
            case "complete":
                guard captureInFlight, networkCaptureCalled, !smoke, busy,
                      let directory = outputDirectory,
                      event["output"] as? String == directory.path,
                      let captured = count(event["capture_count"]),
                      let complete = flag(event["complete"]),
                      let limitations = count(event["limitation_count"]),
                      let consistent = flag(event["consistent_final_snapshot"]) else {
                    protocolFailure()
                    return
                }
                busy = false
                captureInFlight = false
                captureFinished = true
                allowVisit = false
                if complete && limitations == 0 && consistent {
                    status = "보존을 완료했습니다. 응답 \(captured)개를 선택한 폴더에 보관했습니다."
                } else {
                    status = "일부 응답 보존 · 누락 \(limitations)개 · 응답 \(captured)개"
                    if limitations == 0 { status += " · 최종 상태 확인 필요" }
                }
            default:
                protocolFailure()
                return
            }
        }
        if pending.count > maxLineBytes { protocolFailure() }
    }

    private func receiveInspection(_ event: [String: Any]) {
        guard ready, busy, inspectionPending, !captureInFlight,
              event["status"] as? String == "inspected",
              let matched = count(event["matched_rows"]),
              let valid = count(event["valid_archives"]),
              let rejected = count(event["rejected_archives"]),
              let groupCount = count(event["account_groups"]),
              let values = event["groups"] as? [[String: Any]],
              groupCount == values.count, groupCount <= 4096,
              valid + rejected <= matched,
              (valid == 0) == values.isEmpty else {
            protocolFailure()
            return
        }
        var parsed: [AccountGroup] = []
        var seen = Set<Int>()
        for value in values {
            guard let number = count(value["group_number"]), number > 0,
                  let candidates = count(value["candidate_count"]), candidates > 0,
                  let current = count(value["current_candidate_count"]), current <= candidates,
                  seen.insert(number).inserted else {
                protocolFailure()
                return
            }
            parsed.append(AccountGroup(id: number, candidates: candidates, currentCandidates: current))
        }
        guard parsed.reduce(0, { $0 + $1.candidates }) == valid else {
            protocolFailure()
            return
        }
        matchedRows = matched
        validArchives = valid
        rejectedArchives = rejected
        groups = parsed
        selectedGroup = parsed.count == 1 ? parsed[0].id : nil
        inspected = true
        busy = false
        inspectionPending = false
        offlineInspectionCompleted = true
        if rejected > 0 {
            status = "일부 인증 자료를 확인하지 못했습니다. 이 Mac에서 자료를 점검한 뒤 다시 확인해 주세요."
        } else {
            status = valid > 0 ? "로컬 인증 자료를 확인했습니다. 계정 그룹과 보존 위치를 선택해 주세요." :
                "이 Mac에서 보존에 사용할 기존 인증 자료를 찾지 못했습니다."
        }
        if smoke { advanceSmoke() }
    }

    func inspect() {
        guard ready, !busy, !captureInFlight else { return }
        inspected = false
        captureFinished = false
        selectedGroup = nil
        groups = []
        allowVisit = false
        busy = true
        inspectionPending = true
        status = "이 Mac의 기존 인증 자료를 오프라인으로 확인하고 있습니다."
        send(["action": "inspect"])
    }

    func chooseOutput() {
        guard !busy, !smoke else { return }
        let panel = NSOpenPanel()
        panel.title = "보존 폴더를 둘 위치 선택"
        panel.prompt = "선택"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let chosenParent = panel.url else { return }
        let parent = chosenParent.resolvingSymlinksInPath().standardizedFileURL
        let date = DateFormatter()
        date.locale = Locale(identifier: "en_US_POSIX")
        date.dateFormat = "yyyyMMdd-HHmmss"
        let name = "IdolyPride-Events-" + date.string(from: Date()) + "-" + String(UUID().uuidString.prefix(8))
        // Only the worker creates this new child folder, after validation.
        outputDirectory = parent.appendingPathComponent(name, isDirectory: true)
        captureFinished = false
    }

    func capture() {
        guard canCapture, let directory = outputDirectory else { return }
        networkCaptureCalled = true
        captureInFlight = true
        busy = true
        captureFinished = false
        status = "선택한 기존 계정으로 보존을 시작하고 있습니다."
        var command: [String: Any] = ["action": "capture", "output": directory.path,
                                     "allow_login": true, "allow_menu_visit": true]
        command["account_group"] = selectedGroup.map { $0 as Any } ?? NSNull()
        send(command)
    }

    func revealOutput() {
        guard captureFinished, let directory = outputDirectory else { return }
        NSWorkspace.shared.open(directory)
    }

    private func send(_ command: [String: Any]) {
        guard let writer = input?.fileHandleForWriting, child?.isRunning == true else {
            fail("보존 도구에 연결하지 못했습니다. 앱을 다시 열어 주세요.")
            return
        }
        do {
            var data = try JSONSerialization.data(withJSONObject: command)
            data.append(10)
            try writer.write(contentsOf: data)
        } catch {
            fail("보존 도구에 요청을 전달하지 못했습니다.")
        }
    }

    private func progressLabel(_ code: String?) -> String {
        switch code {
        case "logging_in", "authenticating": return "기존 계정으로 로그인하고 있습니다."
        case "collecting", "capturing": return "이미지 트레이닝·VENUS 응답을 보존하고 있습니다."
        case "saving", "writing": return "보존 파일을 저장하고 있습니다."
        default: return "보존 작업을 진행하고 있습니다."
        }
    }

    private func failureLabel(_ code: String?) -> String {
        switch code {
        case "multiple_accounts_require_selection", "invalid_group_number", "account_selection_required_or_invalid":
            return "계정 그룹을 선택한 뒤 다시 확인해 주세요."
        case "archive_candidates_invalid", "archive_scopes_differ", "archive_rows_invalid":
            return "일부 인증 자료를 확인하지 못했습니다. 이 Mac에서 자료를 점검한 뒤 다시 확인해 주세요."
        case "no_current_candidate", "no_eligible_candidate", "no_archives", "playchain_missing":
            return "사용할 기존 인증 자료가 없습니다. 공식 앱의 로그인 상태를 확인해 주세요."
        case "output_exists", "invalid_output", "new_private_output_required", "cannot_create_private_output":
            return "새 보존 폴더를 선택해 주세요. 기존 폴더에는 덮어쓰지 않습니다."
        case "authentication_failed", "login_failed", "refresh_failed", "existing_account_login_rejected", "existing_login_failed":
            return "기존 계정 로그인에 실패했습니다. 공식 앱의 로그인 상태를 확인해 주세요."
        default:
            return "보존 작업을 완료하지 못했습니다. 인증 파일이나 오류 원문은 공유하지 마세요."
        }
    }

    private func protocolFailure() {
        pending.removeAll(keepingCapacity: false)
        ready = false
        fail("보존 도구의 응답을 확인하지 못했습니다. 앱을 다시 열어 주세요.")
    }

    private func fail(_ message: String) {
        busy = false
        inspectionPending = false
        captureInFlight = false
        allowVisit = false
        status = message
        if smoke { finishSmoke(success: false) } else { alertMessage = message }
    }

    private func advanceSmoke() {
        guard smoke, !smokeFinished else { return }
        if NSApp.windows.contains(where: { $0.isVisible }) { visibleWindowObserved = true }
        guard visibleWindowObserved else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in self?.advanceSmoke() }
            return
        }
        guard offlineInspectionCompleted else { return }
        finishSmoke(success: offlineInspectionCompleted && !networkCaptureCalled)
    }

    private func finishSmoke(success: Bool) {
        guard smoke, !smokeFinished else { return }
        smokeFinished = true
        if NSApp.windows.contains(where: { $0.isVisible }) { visibleWindowObserved = true }
        if let destination = smokeReport {
            let report: [String: Any] = ["schema": 1, "ok": success,
                "gui_started": visibleWindowObserved,
                "window_visible": NSApp.windows.contains { $0.isVisible },
                "offline_inspection_completed": offlineInspectionCompleted,
                "no_network_capture_called": !networkCaptureCalled,
                "real_account_tested": false]
            do {
                try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(),
                                                        withIntermediateDirectories: true)
                try JSONSerialization.data(withJSONObject: report, options: .prettyPrinted)
                    .write(to: destination, options: .atomic)
            } catch { fputs("Cannot write offline app smoke report.\n", stderr) }
        }
        NSApp.terminate(nil)
    }

    func shutdown(_ completion: @escaping () -> Void) {
        guard !shutdownRequested else { completion(); return }
        shutdownRequested = true
        allowVisit = false
        ready = false
        busy = true
        let process = child
        if process?.isRunning == true { send(["action": "quit"]) }
        let writer = input?.fileHandleForWriting
        let reader = output?.fileHandleForReading
        let errorReader = errors?.fileHandleForReading
        pending.removeAll(keepingCapacity: false)
        DispatchQueue.global(qos: .userInitiated).async {
            try? writer?.close()
            if let process = process {
                let deadline = Date().addingTimeInterval(8)
                while process.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.05) }
                if process.isRunning {
                    process.terminate()
                    let last = Date().addingTimeInterval(2)
                    while process.isRunning && Date() < last { Thread.sleep(forTimeInterval: 0.05) }
                    if process.isRunning { kill(process.processIdentifier, SIGKILL) }
                }
            }
            reader?.readabilityHandler = nil
            errorReader?.readabilityHandler = nil
            DispatchQueue.main.async { completion() }
        }
    }
}

@MainActor
private struct PreserverView: View {
    @ObservedObject var model: PreserverModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: "archivebox").font(.largeTitle).foregroundStyle(.purple)
                VStack(alignment: .leading, spacing: 5) {
                    Text("아이프라 이벤트 보존").font(.title2.bold())
                    Text("이 Mac의 기존 PlayCover 로그인 자료로 게임 데이터를 보관합니다.")
                        .foregroundStyle(.secondary)
                }
            }
            Text(model.status).font(.headline).accessibilityIdentifier("preserver-status")
            HStack {
                Button("인증 자료 다시 확인") { model.inspect() }.disabled(model.busy || !model.ready)
                Spacer()
                if model.inspected {
                    Text("확인 \(model.matchedRows)개 · 사용 가능 \(model.validArchives)개 · 점검 필요 \(model.rejectedArchives)개")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            if model.inspected && !model.groups.isEmpty {
                if model.groups.count > 1 {
                    Picker("계정 그룹", selection: $model.selectedGroup) {
                        Text("그룹을 선택해 주세요").tag(Optional<Int>.none)
                        ForEach(model.groups) { group in
                            Text("그룹 \(group.id) · 인증 자료 \(group.candidates)개")
                                .tag(Optional(group.id))
                        }
                    }.disabled(model.busy)
                } else {
                    Text("계정 그룹 1 · 인증 자료 \(model.groups[0].candidates)개")
                        .font(.subheadline)
                }
                Text("여러 그룹이 있으면 현재 사용할 그룹을 직접 선택해야 합니다. 계정 식별자와 인증값은 화면에 표시하지 않습니다.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Divider()
            HStack {
                Button("보존 위치 선택") { model.chooseOutput() }.disabled(model.busy)
                Button("보존 폴더 열기") { model.revealOutput() }.disabled(!model.captureFinished)
            }
            Text(model.outputDirectory?.path ?? "보존 위치를 선택하면 새 폴더에 저장합니다.")
                .font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                .lineLimit(3).truncationMode(.middle)
            Toggle("기존 계정으로 로그인하고 이미지 트레이닝·VENUS 메뉴 조회", isOn: $model.allowVisit)
                .disabled(model.busy || !model.inspected || model.validArchives == 0 || model.rejectedArchives > 0)
            Text("공식 서버에 정상 로그인하고 메뉴를 조회하므로 로그인·월간 보상 상태가 바뀔 수 있습니다. 생성·대전 시작·재료 소비는 자동으로 실행하지 않습니다.")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                Button("보존 시작") { model.capture() }.disabled(!model.canCapture)
                    .keyboardShortcut(.defaultAction)
                Spacer()
                if model.busy { ProgressView().controlSize(.small) }
            }
            Text("인증 파일과 보존한 원본 데이터는 보내지 말고 이 Mac에 보관해 주세요. 앱을 종료하면 진행 중인 보존 작업도 중지됩니다.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(24)
        .frame(minWidth: 660, minHeight: 480)
        .alert("아이프라 이벤트 보존", isPresented: Binding(
            get: { model.alertMessage != nil }, set: { if !$0 { model.alertMessage = nil } })) {
                Button("확인") { model.alertMessage = nil }
            } message: { Text(model.alertMessage ?? "") }
    }
}

@MainActor
private final class PreserverAppDelegate: NSObject, NSApplicationDelegate {
    private let model = PreserverModel()
    private var window: NSWindow?
    private var quitPending = false
    private var readyToTerminate = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let visible = NSWindow(contentViewController: NSHostingController(rootView: PreserverView(model: model)))
        visible.title = "아이프라 이벤트 보존"
        visible.styleMask = [.titled, .closable, .miniaturizable, .resizable]
        visible.isReleasedWhenClosed = false
        visible.setContentSize(NSSize(width: 740, height: 570))
        visible.minSize = NSSize(width: 660, height: 480)
        visible.center()
        window = visible
        visible.makeKeyAndOrderFront(nil)
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
        return .terminateCancel
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct IdolyEventPreserverApp {
    @MainActor static func main() {
        let application = NSApplication.shared
        application.setActivationPolicy(.regular)
        let mainMenu = NSMenu()
        let item = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "아이프라 이벤트 보존 종료", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = appMenu
        mainMenu.addItem(item)
        application.mainMenu = mainMenu
        let delegate = PreserverAppDelegate()
        application.delegate = delegate
        withExtendedLifetime(delegate) { application.run() }
    }
}
