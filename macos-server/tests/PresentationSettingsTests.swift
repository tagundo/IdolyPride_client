import Foundation

@main
struct PresentationSettingsTests {
    static var checks = 0
    enum Failure: Error { case assertion(String) }

    static func expect(_ condition: @autoclosure () throws -> Bool, _ label: String) throws {
        checks += 1
        if try !condition() { throw Failure.assertion(label) }
    }

    static func rejected(_ label: String, _ action: () throws -> Void) throws {
        do { try action() }
        catch { checks += 1; return }
        throw Failure.assertion("Expected rejection: " + label)
    }

    static func changed(_ key: String, _ value: Any) throws -> Data {
        var object = try JSONSerialization.jsonObject(with: ClientPresentationSettings.defaults.encoded()) as! [String: Any]
        object[key] = value
        return try JSONSerialization.data(withJSONObject: object, options: .sortedKeys)
    }

    static func codec() throws {
        let original = try ClientPresentationSettings.defaults.encoded()
        try expect(try ClientPresentationSettings.decode(original) == .defaults, "defaults round trip")
        let object = try JSONSerialization.jsonObject(with: original) as! [String: Any]
        try expect(Set(object.keys) == ["schema", "revision", "custom_graphics", "quality", "target_fps",
            "render_scale", "max_buffer_pixel", "anti_aliasing", "shadow_resolution", "expand_photography"], "exact wire fields")
        let text = String(decoding: original, as: UTF8.self)
        for field in ["schema", "revision", "quality", "target_fps", "max_buffer_pixel", "anti_aliasing", "shadow_resolution"] {
            let number = (object[field] as! NSNumber).stringValue
            let old = "\"" + field + "\":" + number
            let changed = text.replacingOccurrences(of: old, with: old + ".0")
            try expect(changed != text, "fractional fixture changed")
            try rejected("fractional integer " + field) { _ = try ClientPresentationSettings.decode(Data(changed.utf8)) }
        }
        for (key, value) in [("custom_graphics", 1 as Any), ("expand_photography", "false" as Any),
                ("quality", true as Any), ("revision", -1 as Any), ("schema", 2 as Any), ("target_fps", 45 as Any),
                ("quality", 50 as Any), ("anti_aliasing", 3 as Any), ("shadow_resolution", 999 as Any),
                ("render_scale", true as Any), ("render_scale", 0.24 as Any), ("render_scale", 2.01 as Any),
                ("max_buffer_pixel", 255 as Any), ("max_buffer_pixel", 257 as Any), ("max_buffer_pixel", 4098 as Any)] {
            try rejected("invalid " + key) { _ = try ClientPresentationSettings.decode(try changed(key, value)) }
        }
        var custom = ClientPresentationSettings.defaults
        custom.renderScale = 0.625
        custom.maxBufferPixel = 2000
        try expect(try ClientPresentationSettings.decode(custom.encoded()) == custom, "valid backend values preserved")
        try rejected("unknown key") { _ = try ClientPresentationSettings.decode(try changed("audience", true)) }
        var missing = object
        missing.removeValue(forKey: "quality")
        try rejected("missing field") {
            _ = try ClientPresentationSettings.decode(JSONSerialization.data(withJSONObject: missing))
        }
        for extra in ["\"schema\":1,", "\"\\u0073chema\":1,"] {
            let duplicate = "{" + extra + String(text.dropFirst())
            try rejected("duplicate field") { _ = try ClientPresentationSettings.decode(Data(duplicate.utf8)) }
        }
        try rejected("oversized") { _ = try ClientPresentationSettings.decode(Data(repeating: 32, count: 8193)) }
        try rejected("empty") { _ = try ClientPresentationSettings.decode(Data()) }
        try rejected("array") { _ = try ClientPresentationSettings.decode(Data("[]".utf8)) }
        let overflow = text.replacingOccurrences(of: "\"revision\":0", with: "\"revision\":9223372036854775808")
        try rejected("revision overflow") { _ = try ClientPresentationSettings.decode(Data(overflow.utf8)) }
    }

    static func files() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("presentation-tests-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent(ClientPresentationSettings.filename)
        let database = directory.appendingPathComponent("state.db")
        let sentinel = Data("synthetic account database must stay untouched".utf8)
        try sentinel.write(to: database)
        let absent = ClientPresentationSettings.load(from: file)
        try expect(!absent.invalid && absent.settings == .defaults, "missing uses defaults")
        let broken = Data("invalid settings".utf8)
        try broken.write(to: file)
        let invalid = ClientPresentationSettings.load(from: file)
        try expect(invalid.invalid && invalid.settings == .defaults, "invalid uses UI defaults")
        try expect(try Data(contentsOf: file) == broken, "load does not replace invalid file")
        var settings = ClientPresentationSettings.defaults
        settings.customGraphics = true
        settings.targetFPS = 60
        settings = try settings.saving(to: file, nowMilliseconds: 100)
        try expect(settings.revision == 100, "clock revision")
        settings = try settings.saving(to: file, nowMilliseconds: 100)
        try expect(settings.revision == 101, "same millisecond increments")
        settings = try settings.saving(to: file, nowMilliseconds: 10)
        try expect(settings.revision == 102, "backward clock increments")
        let reopened = ClientPresentationSettings.load(from: file)
        try expect(!reopened.invalid && reopened.settings == settings, "reopen preserves settings")
        try expect(try Data(contentsOf: database) == sentinel, "database preserved")
        let previous = try Data(contentsOf: file)
        settings.revision = Int64.max
        try rejected("revision exhausted") { _ = try settings.saving(to: file, nowMilliseconds: 100) }
        try expect(try Data(contentsOf: file) == previous, "overflow preserves preferences")
        settings = .defaults
        settings.quality = 999
        try rejected("invalid save") { _ = try settings.saving(to: file, nowMilliseconds: 200) }
        try expect(try Data(contentsOf: file) == previous, "invalid save preserves preferences")
        settings = .defaults
        try rejected("unwritable destination") {
            _ = try settings.saving(to: database.appendingPathComponent("settings.json"), nowMilliseconds: 200)
        }
        try expect(try Data(contentsOf: database) == sentinel, "failed save preserves database")
        try FileManager.default.removeItem(at: file)
        try FileManager.default.createSymbolicLink(at: file, withDestinationURL: database)
        try expect(ClientPresentationSettings.load(from: file).invalid, "symlink rejected")
        try expect(try Data(contentsOf: database) == sentinel, "symlink target preserved")
    }

    static func feedback() throws {
        var settings = ClientPresentationSettings.defaults
        settings.revision = 100
        func report(_ state: String, _ revision: Any = 100) -> [String: Any] {
            ["bridge_version": 1, "revision": revision, "status": state]
        }
        try expect(ClientPresentationFeedback.observed(running: true, settings: settings, client: report("applied")) == .applied, "actual ACK")
        try expect(ClientPresentationFeedback.observed(running: false, settings: settings, client: report("applied")) == .savedWaiting, "stopped clears ACK")
        for revision in [99, 101] {
            try expect(ClientPresentationFeedback.observed(running: true, settings: settings, client: report("applied", revision)) == .savedWaiting, "other revision pending")
            try expect(ClientPresentationFeedback.observed(running: true, settings: settings, client: report("disabled", revision)) == .savedWaiting, "other disabled revision pending")
        }
        try expect(ClientPresentationFeedback.observed(running: true, settings: settings, client: report("disabled")) == .disabled, "original settings ACK")
        for (state, result) in [("unsupported", ClientPresentationFeedback.unsupported),
                ("waiting_for_scene", .waitingForScene), ("init_failed", .initializationFailed)] {
            try expect(ClientPresentationFeedback.observed(running: true, settings: settings, client: report(state, 0)) == result, "non-success last-applied revision visible")
        }
        try expect(ClientPresentationFeedback.observed(running: true, settings: settings, client: report("applied", true)) == .savedWaiting, "boolean revision rejected")
        try expect(ClientPresentationFeedback.observed(running: true, settings: settings, client: nil) == .savedWaiting, "no report pending")
        try expect(ClientPresentationFeedback.observed(running: true, settings: settings, client: report("applied"), invalidFile: true) == .invalidFile, "invalid file visible")
        try expect(ClientPresentationFeedback.observed(running: true, settings: settings, client: report("applied"), saveFailed: true) == .saveFailed, "save failure visible")
    }

    static func polling() throws {
        var polling = ClientPresentationPolling()
        try expect(!polling.fresh(at: 10), "no response is stale")
        try expect(polling.beginRequest(), "first request")
        for _ in 0..<100 { try expect(!polling.beginRequest(), "stalled request remains bounded") }
        polling.received(at: 10)
        try expect(polling.fresh(at: 15), "fresh boundary")
        try expect(!polling.fresh(at: 15.01), "stale response")
        try expect(!polling.fresh(at: 9), "backward timestamp rejected")
        try expect(polling.beginRequest(), "response allows next request")
        polling.received(at: 20)
        try expect(polling.fresh(at: 21), "recovered engine response")
        polling.reset()
        try expect(!polling.fresh(at: 21) && polling.beginRequest(), "reset removes stale observation")
    }

    static func main() throws {
        try codec()
        try files()
        try feedback()
        try polling()
        print("PASS: \(checks) presentation codec, preservation, ACK and polling checks")
    }
}
