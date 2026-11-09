import AppKit
import Foundation
import SwiftUI
import Darwin

@MainActor
final class ServerModel: ObservableObject {
    static weak var active: ServerModel?
    @Published var running = false
    @Published var busy = true
    @Published var canStop = false
    @Published var status = "앱을 준비하고 있습니다."
    @Published var logs = ""
    @Published var alertMessage: String?
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
    private var smokeStarted = false
    private var smokeStopping = false

    init() {
        let arguments = ProcessInfo.processInfo.arguments
        func value(_ flag: String) -> String? {
            guard let index = arguments.firstIndex(of: flag), index + 1 < arguments.count else { return nil }
            return arguments[index + 1]
        }
        smoke = arguments.contains("--app-smoke")
        smokeReport = value("--smoke-report").map { URL(fileURLWithPath: $0) }
        if let custom = value("--data-dir") {
            dataDirectory = URL(fileURLWithPath: custom, isDirectory: true)
        } else {
            let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            dataDirectory = support.appendingPathComponent("IdolyPrideLocal", isDirectory: true)
        }
        ServerModel.active = self
    }

    func launch() {
        guard !launched else { return }
        launched = true
        guard let resources = Bundle.main.resourceURL else {
            fail("앱 리소스를 찾지 못했습니다.")
            return
        }
        let engine = resources.appendingPathComponent("runtime/IdolyServerEngine")
        let serverData = resources.appendingPathComponent("ServerData.zip")
        let process = Process()
        let writer = Pipe(), reader = Pipe(), errorReader = Pipe()
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
        } catch {
            fail("서버 엔진을 실행하지 못했습니다. 앱 파일을 다시 확인해 주세요.")
        }
        if smoke {
            DispatchQueue.main.asyncAfter(deadline: .now() + 45) { [weak self] in
                guard let self = self, !self.shutdownRequested else { return }
                self.finishSmoke(success: false)
            }
        }
    }

    private func consume(_ data: Data) {
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
            case "status":
                guard let state = event["status"] as? [String: Any] else { continue }
                running = state["running"] as? Bool ?? false
                busy = state["starting"] as? Bool ?? false
                canStop = state["can_stop"] as? Bool ?? (running || busy)
                status = running ? "로컬 서버가 실행 중입니다." : (busy ? "서버를 시작하고 있습니다." : "서버가 중지되어 있습니다.")
                if smoke && !busy {
                    if running && !smokeStopping {
                        smokeStarted = true; smokeStopping = true; stop()
                    } else if !running && smokeStopping {
                        finishSmoke(success: smokeStarted && !canStop)
                    } else if !running && !smokeStarted {
                        start()
                    }
                }
            default: break
            }
        }
    }

    private func send(_ action: String) {
        guard let writer = input?.fileHandleForWriting, child?.isRunning == true else {
            fail("서버 엔진에 연결하지 못했습니다. 앱을 다시 열어 주세요.")
            return
        }
        do {
            var data = try JSONSerialization.data(withJSONObject: ["action": action])
            data.append(10)
            try writer.write(contentsOf: data)
        } catch { fail("서버 엔진에 요청을 전달하지 못했습니다.") }
    }

    func start() {
        guard !running && !busy && !canStop else { return }
        busy = true; status = "서버를 시작하고 있습니다."; send("start")
    }
    func stop() {
        busy = true; status = "서버를 중지하고 있습니다."; send("stop")
    }
    func openGame() {
        guard running else { alertMessage = "먼저 서버를 시작해 주세요."; return }
        let configuration = NSWorkspace.OpenConfiguration()
        guard let application = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "game.qualiarts.idolypride.local") else {
            alertMessage = "연결용 아이프라 IPA를 PlayCover에 먼저 설치해 주세요."
            return
        }
        NSWorkspace.shared.openApplication(at: application, configuration: configuration) { [weak self] _, error in
            if error != nil {
                DispatchQueue.main.async { self?.alertMessage = "PlayCover에서 연결용 아이프라를 열어 주세요." }
            }
        }
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
        busy = false; status = message; appendLog(message)
        if !smoke { alertMessage = message }
    }
    private func finishSmoke(success: Bool) {
        if let destination = smokeReport {
            let report: [String: Any] = ["gui_started": true, "server_started": smokeStarted,
                "server_stopped": success && !running, "game_client_tested": false]
            if let data = try? JSONSerialization.data(withJSONObject: report, options: .prettyPrinted) {
                try? FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
                try? data.write(to: destination, options: .atomic)
            }
        }
        NSApp.terminate(nil)
    }
    func shutdown(_ completion: @escaping () -> Void) {
        guard !shutdownRequested else { completion(); return }
        shutdownRequested = true
        let process = child
        if process?.isRunning == true { send("quit") }
        try? input?.fileHandleForWriting.close()
        output?.fileHandleForReading.readabilityHandler = nil
        errors?.fileHandleForReading.readabilityHandler = nil
        DispatchQueue.global(qos: .userInitiated).async {
            if let process = process {
                let deadline = Date().addingTimeInterval(8)
                while process.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.05) }
                if process.isRunning {
                    process.terminate()
                    let finalDeadline = Date().addingTimeInterval(2)
                    while process.isRunning && Date() < finalDeadline { Thread.sleep(forTimeInterval: 0.05) }
                    if process.isRunning { kill(process.processIdentifier, SIGKILL) }
                }
            }
            DispatchQueue.main.async { completion() }
        }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let model = ServerModel.active else { return .terminateNow }
        model.shutdown { sender.reply(toApplicationShouldTerminate: true) }
        return .terminateLater
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
@MainActor
struct IdolyLocalServerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model = ServerModel()
    var body: some Scene {
        WindowGroup("아이프라 로컬 서버") {
            VStack(alignment: .leading, spacing: 18) {
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
                    Button("아이프라 열기") { model.openGame() }.disabled(!model.running)
                    Spacer()
                    Button("데이터 폴더") { model.revealData() }
                }
                Text("서버 127.0.0.1:50051 · 리소스 127.0.0.1:8080").font(.caption).foregroundStyle(.secondary)
                Divider()
                Text("실행 기록").font(.subheadline.bold())
                ScrollView {
                    Text(model.logs.isEmpty ? "서버를 시작하면 여기에 실행 상태가 표시됩니다." : model.logs)
                        .font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading).padding(10)
                }.background(Color(nsColor: .textBackgroundColor)).clipShape(RoundedRectangle(cornerRadius: 8))
                Text("앱을 종료하면 서버도 중지됩니다. 업데이트해도 데이터는 별도 폴더에 보관됩니다.")
                    .font(.caption).foregroundStyle(.secondary)
            }.padding(24).frame(minWidth: 650, minHeight: 450).task { model.launch() }
                .alert("아이프라 로컬 서버", isPresented: Binding(
                    get: { model.alertMessage != nil }, set: { if !$0 { model.alertMessage = nil } })) {
                    Button("확인") { model.alertMessage = nil }
                } message: { Text(model.alertMessage ?? "") }
        }.windowResizability(.contentMinSize)
    }
}
