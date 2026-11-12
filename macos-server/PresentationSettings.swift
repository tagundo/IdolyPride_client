import Foundation
import CoreFoundation

/// Public graphics preferences only; stored beside the existing server data.
struct ClientPresentationSettings: Equatable {
    static let filename = "client-presentation.json"
    static let maximumBytes = 8192
    static let qualities = [0, 10, 20, 30, 40, 100]
    static let frameRates = [0, 30, 60, 90, 120]
    static let renderScales = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
    static let bufferSizes = [720, 1080, 1440, 1920, 2560, 3840, 4096]
    static let antiAliasingModes = [-1, 0, 1, 2]
    static let shadowSizes = [0, 512, 1024, 2048, 4096]
    static let defaults = ClientPresentationSettings()
    private static let fields: Set<String> = ["schema", "revision", "custom_graphics", "quality",
        "target_fps", "render_scale", "max_buffer_pixel", "anti_aliasing", "shadow_resolution", "expand_photography"]

    var revision: Int64 = 0
    var customGraphics = false
    var quality = 0
    var targetFPS = 0
    var renderScale = 1.0
    var maxBufferPixel = 4096
    var antiAliasing = -1
    var shadowResolution = 0
    var expandPhotography = false

    enum Invalid: Error { case settings, revisionExhausted }

    struct Loaded {
        let settings: ClientPresentationSettings
        let invalid: Bool
    }

    fileprivate static func integer(_ value: Any?) -> Int64? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              !["f", "d"].contains(String(cString: number.objCType)) else { return nil }
        return Int64(number.stringValue)
    }

    private static func boolean(_ value: Any?) -> Bool? {
        guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else { return nil }
        return number.boolValue
    }

    static func decode(_ data: Data) throws -> ClientPresentationSettings {
        guard !data.isEmpty, data.count <= maximumBytes,
              let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(object.keys) == fields, integer(object["schema"]) == 1,
              let revision = integer(object["revision"]), revision >= 0,
              let custom = boolean(object["custom_graphics"]), let expand = boolean(object["expand_photography"]),
              let qualityValue = integer(object["quality"]), let fps = integer(object["target_fps"]),
              let maximum = integer(object["max_buffer_pixel"]), let aa = integer(object["anti_aliasing"]),
              let shadow = integer(object["shadow_resolution"]), let scale = object["render_scale"] as? NSNumber,
              CFGetTypeID(scale) != CFBooleanGetTypeID() else { throw Invalid.settings }
        // Every accepted value is a scalar. Counting all JSON member tokens also
        // rejects duplicate keys, including differently escaped spellings.
        guard let source = String(data: data, encoding: .utf8) else { throw Invalid.settings }
        let members = try NSRegularExpression(pattern: #"(?:^|[,{])\s*"(?:\\.|[^"\\])*"\s*:"#)
        guard members.numberOfMatches(in: source, range: NSRange(source.startIndex..., in: source)) == fields.count,
              let quality = Int(exactly: qualityValue), let targetFPS = Int(exactly: fps),
              let maxBufferPixel = Int(exactly: maximum), let antiAliasing = Int(exactly: aa),
              let shadowResolution = Int(exactly: shadow) else { throw Invalid.settings }
        let settings = ClientPresentationSettings(revision: revision, customGraphics: custom, quality: quality,
            targetFPS: targetFPS, renderScale: scale.doubleValue, maxBufferPixel: maxBufferPixel,
            antiAliasing: antiAliasing, shadowResolution: shadowResolution, expandPhotography: expand)
        try settings.validate()
        return settings
    }

    private func validate() throws {
        guard revision >= 0, Self.qualities.contains(quality), Self.frameRates.contains(targetFPS),
              renderScale.isFinite, (0.25...2).contains(renderScale),
              (256...4096).contains(maxBufferPixel), maxBufferPixel % 2 == 0,
              Self.antiAliasingModes.contains(antiAliasing), Self.shadowSizes.contains(shadowResolution) else {
            throw Invalid.settings
        }
    }

    func encoded() throws -> Data {
        try validate()
        return try JSONSerialization.data(withJSONObject: ["schema": 1, "revision": revision,
            "custom_graphics": customGraphics, "quality": quality, "target_fps": targetFPS,
            "render_scale": renderScale, "max_buffer_pixel": maxBufferPixel, "anti_aliasing": antiAliasing,
            "shadow_resolution": shadowResolution, "expand_photography": expandPhotography], options: .sortedKeys)
    }

    static func load(from file: URL) -> Loaded {
        do {
            let attributes = try FileManager.default.attributesOfItem(atPath: file.path)
            guard attributes[.type] as? FileAttributeType == .typeRegular else { throw Invalid.settings }
            let input = try FileHandle(forReadingFrom: file)
            defer { try? input.close() }
            let data = try input.read(upToCount: maximumBytes + 1) ?? Data()
            return Loaded(settings: try decode(data), invalid: false)
        } catch let error as CocoaError where error.code == .fileReadNoSuchFile {
            return Loaded(settings: .defaults, invalid: false)
        } catch {
            // Do not replace a damaged file until a user changes a control.
            return Loaded(settings: .defaults, invalid: true)
        }
    }

    func saving(to file: URL, nowMilliseconds: Int64? = nil) throws -> ClientPresentationSettings {
        guard revision < Int64.max else { throw Invalid.revisionExhausted }
        let now: Int64
        if let supplied = nowMilliseconds {
            now = max(0, supplied)
        } else {
            let milliseconds = Date().timeIntervalSince1970 * 1000
            guard milliseconds.isFinite, milliseconds < Double(Int64.max) else { throw Invalid.revisionExhausted }
            now = Int64(max(0, milliseconds))
        }
        var next = self
        next.revision = max(revision + 1, now)
        let data = try next.encoded()
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: file, options: .atomic)
        return next
    }
}

/// Independent playback preference; never part of the graphics wire schema.
struct ClientPlaybackSettings: Equatable {
    static let filename = "client-playback.json"
    static let maximumBytes = 8192
    static let defaults = ClientPlaybackSettings()
    var revision: Int64 = 0
    var waitForOrientation = true

    enum Invalid: Error { case settings, revisionExhausted }
    struct Loaded { let settings: ClientPlaybackSettings; let invalid: Bool }

    static func decode(_ data: Data) throws -> ClientPlaybackSettings {
        guard !data.isEmpty, data.count <= maximumBytes,
              let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(object.keys) == ["schema", "revision", "wait_for_orientation"],
              ClientPresentationSettings.integer(object["schema"]) == 1,
              let revision = ClientPresentationSettings.integer(object["revision"]), revision >= 0,
              let wait = object["wait_for_orientation"] as? NSNumber,
              CFGetTypeID(wait) == CFBooleanGetTypeID(),
              let source = String(data: data, encoding: .utf8) else { throw Invalid.settings }
        let members = try NSRegularExpression(pattern: #"(?:^|[,{])\s*"(?:\\.|[^"\\])*"\s*:"#)
        guard members.numberOfMatches(in: source, range: NSRange(source.startIndex..., in: source)) == 3 else {
            throw Invalid.settings
        }
        return ClientPlaybackSettings(revision: revision, waitForOrientation: wait.boolValue)
    }

    func encoded() throws -> Data {
        guard revision >= 0 else { throw Invalid.settings }
        return try JSONSerialization.data(withJSONObject: ["schema": 1, "revision": revision,
            "wait_for_orientation": waitForOrientation], options: .sortedKeys)
    }

    static func load(from file: URL) -> Loaded {
        do {
            let attributes = try FileManager.default.attributesOfItem(atPath: file.path)
            guard attributes[.type] as? FileAttributeType == .typeRegular else { throw Invalid.settings }
            let input = try FileHandle(forReadingFrom: file)
            defer { try? input.close() }
            return Loaded(settings: try decode(input.read(upToCount: maximumBytes + 1) ?? Data()), invalid: false)
        } catch let error as CocoaError where error.code == .fileReadNoSuchFile {
            return Loaded(settings: .defaults, invalid: false)
        } catch { return Loaded(settings: .defaults, invalid: true) }
    }

    func saving(to file: URL, nowMilliseconds: Int64? = nil) throws -> ClientPlaybackSettings {
        guard revision >= 0, revision < Int64.max else { throw Invalid.revisionExhausted }
        let now: Int64
        if let supplied = nowMilliseconds { now = max(0, supplied) }
        else {
            let milliseconds = Date().timeIntervalSince1970 * 1000
            guard milliseconds.isFinite, milliseconds < Double(Int64.max) else { throw Invalid.revisionExhausted }
            now = Int64(max(0, milliseconds))
        }
        var next = self
        next.revision = max(revision + 1, now)
        let data = try next.encoded()
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: file, options: .atomic)
        return next
    }
}

enum ClientPresentationFeedback: Equatable {
    case waiting, savedWaiting, applied, disabled, unsupported, waitingForScene, initializationFailed
    case invalidFile, saveFailed

    static func observed(running: Bool, settings: ClientPresentationSettings, client: [String: Any]?,
                         invalidFile: Bool = false, saveFailed: Bool = false) -> ClientPresentationFeedback {
        if saveFailed { return .saveFailed }
        if invalidFile { return .invalidFile }
        let pending: ClientPresentationFeedback = settings.revision > 0 ? .savedWaiting : .waiting
        guard running, let client = client, ClientPresentationSettings.integer(client["bridge_version"]) == 1,
              let revision = ClientPresentationSettings.integer(client["revision"]), revision >= 0,
              let state = client["status"] as? String else { return pending }
        switch state {
        case "applied": return revision == settings.revision ? .applied : pending
        case "disabled": return revision == settings.revision ? .disabled : pending
        case "unsupported": return .unsupported
        case "waiting_for_scene": return .waitingForScene
        case "init_failed": return .initializationFailed
        default: return pending
        }
    }

    var message: String {
        switch self {
        case .waiting: return "원본 설정 · 그래픽 지원 게임의 응답 대기"
        case .savedWaiting: return "설정 저장됨 · 게임의 적용 확인 대기"
        case .applied: return "게임에서 현재 설정의 적용을 확인했습니다."
        case .disabled: return "게임에서 원본 화면 설정 사용을 확인했습니다."
        case .unsupported: return "현재 게임 또는 화면 배치에서는 이 설정을 적용할 수 없습니다."
        case .waitingForScene: return "게임에서 설정 수신 · 촬영·360 화면 적용 확인 대기"
        case .initializationFailed: return "게임의 화면 설정 초기화에 실패했습니다."
        case .invalidFile: return "저장된 설정을 읽지 못해 기본값을 표시합니다. 설정을 바꾸면 새로 저장합니다."
        case .saveFailed: return "화면 설정을 저장하지 못했습니다. 이전 설정을 유지합니다."
        }
    }

    var confirmed: Bool { self == .applied || self == .disabled }
    var failed: Bool { self == .unsupported || self == .initializationFailed || self == .invalidFile || self == .saveFailed }
}

/// Main-actor callers supply monotonic uptime; a stalled engine gets one request.
struct ClientPresentationPolling {
    private(set) var outstanding = false
    private(set) var lastStatusUptime: TimeInterval?

    mutating func beginRequest() -> Bool {
        guard !outstanding else { return false }
        outstanding = true
        return true
    }

    mutating func received(at uptime: TimeInterval) {
        outstanding = false
        lastStatusUptime = uptime.isFinite ? uptime : nil
    }

    func fresh(at uptime: TimeInterval) -> Bool {
        guard uptime.isFinite, let received = lastStatusUptime else { return false }
        let elapsed = uptime - received
        return elapsed >= 0 && elapsed <= 5
    }

    mutating func reset() { outstanding = false; lastStatusUptime = nil }
}
