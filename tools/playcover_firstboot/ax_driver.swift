// Bounded native AX observation and explicit inputs on an ephemeral CI Mac.
// No text-field values, credential input, permission prompts or setting changes.
import Foundation
import Cocoa
import ApplicationServices
import CoreGraphics
import ScreenCaptureKit

private enum DriverError: Error { case invalid(String) }
private func pump(_ seconds: Double) {
    let until = Date(timeIntervalSinceNow: seconds)
    while Date() < until { RunLoop.current.run(until: min(until, Date(timeIntervalSinceNow: 0.02))) }
}
private func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var result: CFTypeRef?
    return AXUIElementCopyAttributeValue(element, name as CFString, &result) == .success ? result : nil
}
private func string(_ element: AXUIElement, _ name: String) -> String {
    guard let value = attribute(element, name) as? String else { return "" }
    return String(value.prefix(512))
}
private func flag(_ element: AXUIElement, _ name: String) -> Bool? {
    attribute(element, name) as? Bool
}
private func frame(_ element: AXUIElement) -> CGRect? {
    guard let position = attribute(element, kAXPositionAttribute), let size = attribute(element, kAXSizeAttribute),
          CFGetTypeID(position) == AXValueGetTypeID(), CFGetTypeID(size) == AXValueGetTypeID() else { return nil }
    var point = CGPoint.zero, extent = CGSize.zero
    guard AXValueGetValue(position as! AXValue, .cgPoint, &point),
          AXValueGetValue(size as! AXValue, .cgSize, &extent),
          point.x.isFinite, point.y.isFinite, extent.width.isFinite, extent.height.isFinite,
          extent.width > 0, extent.height > 0 else { return nil }
    return CGRect(origin: point, size: extent)
}
private func rectangle(_ value: CGRect?) -> Any {
    guard let value = value, !value.isNull, !value.isEmpty else { return NSNull() }
    return [Double(value.minX), Double(value.minY), Double(value.width), Double(value.height)]
}
private func actions(_ element: AXUIElement) -> [String] {
    var result: CFArray?
    guard AXUIElementCopyActionNames(element, &result) == .success else { return [] }
    return Array((result as? [String] ?? []).prefix(16))
}

private struct Observation {
    let element: AXUIElement
    let path: String
    let role: String
    let subrole: String
    let labels: [String]
    let enabled: Bool?
    let visible: Bool
    let visibleFrame: CGRect?
    let actions: [String]
}
private final class Scan {
    let deadline = ProcessInfo.processInfo.systemUptime + 6
    var count = 0
    var truncated = false
    var observations: [Observation] = []
    func node(_ element: AXUIElement, path: String, depth: Int, windowTitle: String,
              clip: CGRect, ancestorVisible: Bool) -> [String: Any]? {
        guard count < 400, depth <= 12, ProcessInfo.processInfo.systemUptime < deadline else {
            truncated = true
            return nil
        }
        count += 1
        let role = string(element, kAXRoleAttribute), subrole = string(element, kAXSubroleAttribute)
        let title = string(element, kAXTitleAttribute), description = string(element, kAXDescriptionAttribute)
        let identifier = string(element, kAXIdentifierAttribute)
        // Read a value only for non-editable static text. Never inspect text fields.
        let staticText = role == kAXStaticTextRole ? string(element, kAXValueAttribute) : ""
        let enabled = flag(element, kAXEnabledAttribute), bounds = frame(element)
        let hidden = flag(element, "AXHidden") == true || flag(element, kAXMinimizedAttribute) == true
        let clipped = bounds.map { $0.intersection(clip) }
        let visible = ancestorVisible && !hidden && clipped.map { !$0.isNull && !$0.isEmpty } == true
        let supported = actions(element)
        observations.append(Observation(element: element, path: path, role: role, subrole: subrole,
            labels: [title, description, staticText].filter { !$0.isEmpty }, enabled: enabled,
            visible: visible, visibleFrame: clipped, actions: supported))
        var output: [String: Any] = ["path": path, "role": role, "subrole": subrole,
            "title": title, "description": description, "identifier": identifier,
            "static_text": staticText, "enabled": enabled.map { $0 as Any } ?? NSNull(),
            "visible": visible, "frame": rectangle(bounds), "visible_frame": rectangle(clipped),
            "window_title": windowTitle, "actions": supported]
        let children = attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? []
        var descendants: [[String: Any]] = []
        for (index, child) in children.prefix(400).enumerated() {
            if let value = node(child, path: path + "." + String(index), depth: depth + 1,
                windowTitle: windowTitle, clip: clipped ?? clip,
                ancestorVisible: ancestorVisible && !hidden) { descendants.append(value) }
            if truncated { break }
        }
        output["children"] = descendants
        return output
    }
}

private struct Snapshot {
    let app: NSRunningApplication
    let scan: Scan
    let tree: [[String: Any]]
    var modalPresent: Bool {
        scan.observations.contains { $0.visible && ($0.role == kAXSheetRole ||
            $0.role == "AXDialog" || $0.role == kAXMenuRole || $0.subrole.contains("Dialog")) }
    }
    func unique(_ label: String, button: Bool) throws -> Observation {
        guard !scan.truncated else { throw DriverError.invalid("AX_tree_incomplete") }
        let candidates = scan.observations.filter { value in
            value.visible && value.labels.contains(label) && value.enabled != false &&
            (!button || (value.role == kAXButtonRole && value.enabled == true && value.actions.contains(kAXPressAction)))
        }
        guard candidates.count == 1, let found = candidates.first,
              let bounds = found.visibleFrame, bounds.width > 1, bounds.height > 1 else {
            throw DriverError.invalid("exact_visible_label_not_unique_" + String(candidates.count))
        }
        return found
    }
}
private func snapshot(_ bundle: String) throws -> Snapshot {
    let applications = NSRunningApplication.runningApplications(withBundleIdentifier: bundle)
    guard applications.count == 1, let application = applications.first else {
        throw DriverError.invalid("bundle_process_not_unique_" + String(applications.count))
    }
    let app = AXUIElementCreateApplication(application.processIdentifier)
    AXUIElementSetMessagingTimeout(app, 0.25)
    guard let windows = attribute(app, kAXWindowsAttribute) as? [AXUIElement] else {
        throw DriverError.invalid("AX_windows_unavailable")
    }
    let scan = Scan(), screen = CGDisplayBounds(CGMainDisplayID())
    if windows.count > 32 { scan.truncated = true }
    var tree: [[String: Any]] = []
    for (index, window) in windows.prefix(32).enumerated() {
        let title = string(window, kAXTitleAttribute)
        if let node = scan.node(window, path: "windows." + String(index), depth: 0,
            windowTitle: title, clip: screen, ancestorVisible: true) { tree.append(node) }
        if scan.truncated { break }
    }
    return Snapshot(app: application, scan: scan, tree: tree)
}

@available(macOS 14.0, *)
private final class CaptureBox: @unchecked Sendable {
    let lock = NSLock()
    private var done = false
    private var image: CGImage?
    private var content: SCShareableContent?
    func finish(image: CGImage? = nil, content: SCShareableContent? = nil) {
        lock.lock(); self.image = image; self.content = content; done = true; lock.unlock()
    }
    func read() -> (Bool, CGImage?, SCShareableContent?) {
        lock.lock(); defer { lock.unlock() }; return (done, image, content)
    }
}
@available(macOS 14.0, *)
private func wait(_ box: CaptureBox, deadline: Double) throws -> (CGImage?, SCShareableContent?) {
    while ProcessInfo.processInfo.systemUptime < deadline {
        let value = box.read()
        if value.0 { return (value.1, value.2) }
        pump(0.02)
    }
    throw DriverError.invalid("screenshot_timeout")
}
@available(macOS 14.0, *)
private func screenshot(_ output: URL) throws {
    guard CGPreflightScreenCaptureAccess() else { throw DriverError.invalid("screen_capture_not_authorized") }
    let deadline = ProcessInfo.processInfo.systemUptime + 10
    let shareable = CaptureBox()
    SCShareableContent.getExcludingDesktopWindows(false, onScreenWindowsOnly: true) { content, _ in
        shareable.finish(content: content)
    }
    guard let content = try wait(shareable, deadline: deadline).1,
          let display = content.displays.first(where: { $0.displayID == CGMainDisplayID() }) else {
        throw DriverError.invalid("screenshot_display_unavailable")
    }
    let filter = SCContentFilter(display: display, excludingWindows: [])
    let configuration = SCStreamConfiguration()
    configuration.width = display.width
    configuration.height = display.height
    configuration.showsCursor = true
    let capture = CaptureBox()
    SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration) { image, _ in
        capture.finish(image: image)
    }
    guard let image = try wait(capture, deadline: deadline).0,
          let data = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]) else {
        throw DriverError.invalid("screenshot_image_unavailable")
    }
    try data.write(to: output, options: .atomic)
}

private func doubleClick(_ bounds: CGRect) throws {
    let point = CGPoint(x: bounds.midX, y: bounds.midY)
    for count in 1...2 {
        guard let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown,
            mouseCursorPosition: point, mouseButton: .left),
              let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp,
            mouseCursorPosition: point, mouseButton: .left) else { throw DriverError.invalid("mouse_event_unavailable") }
        down.setIntegerValueField(.mouseEventClickState, value: Int64(count))
        up.setIntegerValueField(.mouseEventClickState, value: Int64(count))
        down.post(tap: .cghidEventTap); pump(0.02)
        up.post(tap: .cghidEventTap); pump(0.06)
    }
}

private func observationReport(bundle: String, mode: String, snapshot: Snapshot?, action: [String: Any]) -> [String: Any] {
    ["schema": 1, "bundle": bundle, "running": snapshot != nil,
     "pid": snapshot.map { $0.app.processIdentifier as Any } ?? NSNull(),
     "frontmost_bundle": NSWorkspace.shared.frontmostApplication?.bundleIdentifier.map { $0 as Any } ?? NSNull(),
     "mode": mode, "tree": snapshot?.tree ?? [], "element_count": snapshot?.scan.count ?? 0,
     "tree_truncated": snapshot?.scan.truncated ?? false,
     "visible_dialog_present": snapshot?.modalPresent ?? false, "action": action,
     "textfield_values_read": false, "credential_input": false,
     "tcc_prompt_requested": false, "security_settings_changed": false,
     "accessibility_trusted": AXIsProcessTrusted(), "screen_capture_preflight": CGPreflightScreenCaptureAccess()]
}

@available(macOS 14.0, *)
private func saveReport(_ value: [String: Any], output: URL) throws {
    var report = value
    let image = output.deletingPathExtension().appendingPathExtension("png")
    do { try screenshot(image); report["screenshot"] = image.path }
    catch { report["screenshot_error"] = String(describing: error) }
    let encoded = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
    try encoded.write(to: output, options: .atomic)
    FileHandle.standardOutput.write(Data((output.path + "\n").utf8))
}

@available(macOS 14.0, *)
private func run() throws {
    let args = Array(CommandLine.arguments.dropFirst())
    func argument(_ name: String) -> String? {
        guard let index = args.firstIndex(of: name), index + 1 < args.count else { return nil }
        return args[index + 1]
    }
    guard let destination = argument("--output"), !destination.isEmpty else {
        throw DriverError.invalid("output_argument_required")
    }
    let mode: String
    let bundle: String
    let label: String?
    if let value = argument("--inspect") { mode = "inspect"; bundle = value; label = nil }
    else if let value = argument("--double-click-label"), let application = argument("--bundle") {
        mode = "double_click_label"; bundle = application; label = value
        guard bundle == "io.playcover.PlayCover" else { throw DriverError.invalid("double_click_requires_PlayCover") }
    } else if let value = argument("--press-label"), let application = argument("--bundle") {
        mode = "press_label"; bundle = application; label = value
    } else { throw DriverError.invalid("supported_mode_required") }
    guard AXIsProcessTrusted() else { throw DriverError.invalid("accessibility_not_authorized") }
    let output = URL(fileURLWithPath: destination)
    try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
    if mode == "inspect", NSRunningApplication.runningApplications(withBundleIdentifier: bundle).isEmpty {
        try saveReport(observationReport(bundle: bundle, mode: mode, snapshot: nil,
            action: ["posted": false]), output: output)
        return
    }
    var observed = try snapshot(bundle)
    var action: [String: Any] = ["posted": false]
    var actionFailure: Error?
    do { if let label = label {
        guard !label.isEmpty, label.count <= 512 else { throw DriverError.invalid("invalid_exact_label") }
        guard CGPreflightScreenCaptureAccess() else { throw DriverError.invalid("screen_capture_not_authorized") }
        if mode == "double_click_label", observed.modalPresent { throw DriverError.invalid("visible_dialog_blocks_game_double_click") }
        let first = try observed.unique(label, button: mode == "press_label")
        guard observed.app.activate(options: [.activateIgnoringOtherApps]) else { throw DriverError.invalid("application_activation_failed") }
        pump(0.25)
        // Re-read the complete tree after activation, immediately before input.
        observed = try snapshot(bundle)
        if mode == "double_click_label", observed.modalPresent { throw DriverError.invalid("visible_dialog_blocks_game_double_click") }
        let fresh = try observed.unique(label, button: mode == "press_label")
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == observed.app.processIdentifier else {
            throw DriverError.invalid("application_not_frontmost_before_input")
        }
        guard first.path == fresh.path, first.role == fresh.role, let bounds = fresh.visibleFrame else {
            throw DriverError.invalid("label_changed_before_input")
        }
        if mode == "double_click_label" { try doubleClick(bounds) }
        else {
            guard AXUIElementPerformAction(fresh.element, kAXPressAction as CFString) == .success else {
                throw DriverError.invalid("AXPress_failed")
            }
        }
        action = ["posted": true, "kind": mode, "label": label, "path": fresh.path,
            "frame": rectangle(bounds), "game_launch_claimed": false]
        pump(0.25)
        observed = try snapshot(bundle)
    } } catch {
        actionFailure = error
        action["error"] = String(describing: error)
        action["refused"] = action["posted"] as? Bool != true
    }
    try saveReport(observationReport(bundle: bundle, mode: mode, snapshot: observed, action: action), output: output)
    if let failure = actionFailure { throw failure }
}

do {
    guard #available(macOS 14.0, *) else { throw DriverError.invalid("macos_14_or_later_required") }
    try run()
}
catch {
    FileHandle.standardError.write(Data(("AX driver: " + String(describing: error) + "\n").utf8))
    exit(1)
}
