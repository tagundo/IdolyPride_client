// Read-only PlayCover host capability probe. No app installation, GUI capture,
// TCC prompts, security-setting changes, game code or account access.
import Foundation
import Darwin
import Metal
import CoreGraphics
import ApplicationServices
import SystemConfiguration

private func sysctlString(_ name: String) -> String? {
    var size = 0
    guard sysctlbyname(name, nil, &size, nil, 0) == 0, size > 0, size < 4096 else { return nil }
    var value = [CChar](repeating: 0, count: size)
    guard sysctlbyname(name, &value, &size, nil, 0) == 0 else { return nil }
    return String(cString: value)
}

private func sysctlInteger(_ name: String) -> Int32? {
    var value: Int32 = 0
    var size = MemoryLayout<Int32>.size
    return sysctlbyname(name, &value, &size, nil, 0) == 0 ? value : nil
}

private func command(_ executable: String, _ arguments: [String]) -> (Int32?, String) {
    let process = Process(), pipe = Pipe(), finished = DispatchSemaphore(value: 0)
    process.executableURL = URL(fileURLWithPath: executable)
    process.arguments = arguments
    process.standardOutput = pipe
    process.standardError = FileHandle.nullDevice
    process.terminationHandler = { _ in finished.signal() }
    do { try process.run() } catch { return (nil, "unavailable") }
    guard finished.wait(timeout: .now() + 2) == .success else {
        process.terminate()
        return (nil, "timed_out")
    }
    let data = pipe.fileHandleForReading.readDataToEndOfFile().prefix(512)
    return (process.terminationStatus, String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines))
}

private final class CompileResult: @unchecked Sendable {
    var library: MTLLibrary?
    var pipeline: MTLRenderPipelineState?
    let finished = DispatchSemaphore(value: 0)
}

private func render(_ device: MTLDevice) -> [String: Any] {
    let started = ProcessInfo.processInfo.systemUptime
    let deadline = DispatchTime.now() + 8
    let width = 720, height = 1280, grid = 32, triangleCount = 2048
    var result: [String: Any] = ["ok": false, "maximum_total_seconds": 8,
        "texture_size": [width, height], "triangle_count": triangleCount,
        "fragment_iterations": 16, "frames": 0, "game_fps_claimed": false, "mps_required": false]
    func failed(_ stage: String) -> [String: Any] {
        result["failure"] = stage
        result["elapsed_seconds"] = ProcessInfo.processInfo.systemUptime - started
        return result
    }
    let shader = """
    #include <metal_stdlib>
    using namespace metal;
    struct VertexOut { float4 position [[position]]; float2 uv; };
    vertex VertexOut probe_vertex(uint index [[vertex_id]]) {
        const float2 corners[] = {float2(0,0),float2(1,0),float2(0,1),
                                  float2(0,1),float2(1,0),float2(1,1)};
        uint tile = index / 6;
        float2 uv = (float2(tile % 32, tile / 32) + corners[index % 6]) / 32.0;
        VertexOut out; out.position = float4(uv * 2.0 - 1.0,0,1); out.uv = uv;
        return out;
    }
    fragment float4 probe_fragment(VertexOut in [[stage_in]]) {
        float value = in.uv.x * 0.75 + in.uv.y * 0.25;
        for (uint i = 0; i < 16; ++i) { value = fract(value * 1.12345 + 0.12345); }
        return float4(value,0.5,0.75,1);
    }
    """
    let compilation = CompileResult()
    device.makeLibrary(source: shader, options: nil) { library, _ in
        compilation.library = library
        compilation.finished.signal()
    }
    guard compilation.finished.wait(timeout: deadline) == .success,
          let library = compilation.library else { return failed("metal_shader_compile") }
    let descriptor = MTLRenderPipelineDescriptor()
    descriptor.vertexFunction = library.makeFunction(name: "probe_vertex")
    descriptor.fragmentFunction = library.makeFunction(name: "probe_fragment")
    descriptor.colorAttachments[0].pixelFormat = .rgba8Unorm
    let pipelineResult = CompileResult()
    device.makeRenderPipelineState(descriptor: descriptor, options: []) { pipeline, _, _ in
        pipelineResult.pipeline = pipeline
        pipelineResult.finished.signal()
    }
    guard pipelineResult.finished.wait(timeout: deadline) == .success,
          let pipeline = pipelineResult.pipeline else { return failed("metal_render_pipeline") }
    let textureDescriptor = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .rgba8Unorm,
        width: width, height: height, mipmapped: false)
    textureDescriptor.usage = [.renderTarget]
    textureDescriptor.storageMode = .shared
    guard let texture = device.makeTexture(descriptor: textureDescriptor),
          let queue = device.makeCommandQueue() else { return failed("metal_render_resources") }
    result["setup_seconds"] = ProcessInfo.processInfo.systemUptime - started
    let frames = 10
    var frameTimes: [Double] = []
    for index in 0..<frames {
        let frameStarted = ProcessInfo.processInfo.systemUptime
        guard let buffer = queue.makeCommandBuffer() else { return failed("metal_command_buffer") }
        let pass = MTLRenderPassDescriptor()
        pass.colorAttachments[0].texture = texture
        pass.colorAttachments[0].loadAction = .clear
        pass.colorAttachments[0].storeAction = .store
        pass.colorAttachments[0].clearColor = MTLClearColorMake(0, 0, 0, 1)
        guard let encoder = buffer.makeRenderCommandEncoder(descriptor: pass) else { return failed("metal_render_encoder") }
        encoder.setViewport(MTLViewport(originX: 0, originY: 0, width: Double(width), height: Double(height), znear: 0, zfar: 1))
        encoder.setRenderPipelineState(pipeline)
        encoder.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: grid * grid * 6)
        encoder.endEncoding()
        let finished = DispatchSemaphore(value: 0)
        buffer.addCompletedHandler { _ in finished.signal() }
        buffer.commit()
        guard finished.wait(timeout: deadline) == .success, buffer.status == .completed,
              buffer.error == nil else { return failed("metal_render_completion") }
        result["frames"] = index + 1
        frameTimes.append(ProcessInfo.processInfo.systemUptime - frameStarted)
    }
    var pixels = [UInt8](repeating: 0, count: width * height * 4)
    pixels.withUnsafeMutableBytes { bytes in
        texture.getBytes(bytes.baseAddress!, bytesPerRow: width * 4,
            from: MTLRegionMake2D(0, 0, width, height), mipmapLevel: 0)
    }
    let sampleX = width / 2, sampleY = height / 2
    let offset = (sampleY * width + sampleX) * 4
    let actual = Array(pixels[offset..<(offset + 4)])
    var expectedRed = (Float(sampleX) + 0.5) / Float(width) * 0.75
        + (1 - (Float(sampleY) + 0.5) / Float(height)) * 0.25
    for _ in 0..<16 { expectedRed = expectedRed * 1.12345 + 0.12345; expectedRed -= expectedRed.rounded(.down) }
    let expected = [Int((expectedRed * 255).rounded()), 128, 191, 255]
    guard zip(actual, expected).allSatisfy({ abs(Int($0.0) - $0.1) <= 2 }) else {
        return failed("metal_pixel_readback")
    }
    let elapsed = ProcessInfo.processInfo.systemUptime - started
    guard elapsed <= 8 else { return failed("metal_time_budget") }
    let renderSeconds = frameTimes.reduce(0, +)
    let fps = Double(frames) / max(renderSeconds, 0.000001)
    result["ok"] = true
    result["elapsed_seconds"] = elapsed
    result["frame_times_milliseconds"] = frameTimes.map { $0 * 1000 }
    result["render_seconds"] = renderSeconds
    result["synthetic_offscreen_frames_per_second"] = fps
    result["minimum_candidate_fps"] = 30
    result["performance_threshold_passed"] = fps >= 30
    result["pixel_readback_verified"] = true
    return result
}

let os = ProcessInfo.processInfo.operatingSystemVersion
let architecture = sysctlString("hw.machine") ?? "unknown"
let model = sysctlString("hw.model") ?? "unknown"
let hypervisor = sysctlInteger("kern.hv_vmm_present")
let virtualMachine = hypervisor == 1 || model.lowercased().contains("virtual")
let hypervisorValue: Any
if let flag = hypervisor { hypervisorValue = Int(flag) } else { hypervisorValue = NSNull() }
var report: [String: Any] = ["schema": 1, "capability_probe_only": true,
    "game_installed_or_launched": false, "playcover_installed_or_launched": false,
    "screenshots_taken": false, "tcc_prompt_requested": false, "security_settings_changed": false,
    "android_vm_required": false, "nested_virtualization_required": false,
    "os": ["major": os.majorVersion, "minor": os.minorVersion, "patch": os.patchVersion],
    "architecture": architecture, "hardware_model": model,
    "virtual_machine_detected": virtualMachine,
    "physical_hardware_verified": false,
    "hypervisor_flag": hypervisorValue,
    "physical_memory_bytes": ProcessInfo.processInfo.physicalMemory]
if let disk = try? FileManager.default.attributesOfFileSystem(forPath: "/") {
    report["disk_free_bytes"] = disk[.systemFreeSize] ?? NSNull()
    report["disk_total_bytes"] = disk[.systemSize] ?? NSNull()
}
let framework = "/System/iOSSupport/System/Library/Frameworks/UIKit.framework"
let frameworkPresent = FileManager.default.fileExists(atPath: framework)
report["ios_support_uikit"] = ["framework_directory_present": frameworkPresent,
    "binary_file_present": FileManager.default.fileExists(atPath: framework + "/UIKit"),
    "shared_cache_binary_not_required_for_presence": true]
let accessibility = AXIsProcessTrusted()
let screenCapture = CGPreflightScreenCaptureAccess()
var consoleUID: uid_t = 0, consoleGID: gid_t = 0
let consoleUser = SCDynamicStoreCopyConsoleUser(nil, &consoleUID, &consoleGID) as String?
let consolePresent = consoleUser != nil && consoleUser != "loginwindow" && consoleUser != "_mbsetupuser"
let sameConsoleUser = consolePresent && consoleUID == geteuid()
let windowServer = command("/usr/bin/pgrep", ["-x", "WindowServer"]).0 == 0
report["ui_access"] = ["accessibility_trusted": accessibility, "screen_capture_preflight": screenCapture,
    "console_user_present": consolePresent, "probe_is_console_user": sameConsoleUser,
    "window_server_present": windowServer]
let sip = command("/usr/bin/csrutil", ["status"])
report["sip"] = ["status_read_success": sip.0 == 0, "status": sip.1]
var metalOK = false
var performanceOK = false
if let device = MTLCreateSystemDefaultDevice() {
    let rendered = render(device)
    metalOK = rendered["ok"] as? Bool == true
    performanceOK = rendered["performance_threshold_passed"] as? Bool == true
    report["metal"] = ["device_present": true, "device_name": device.name,
        "low_power": device.isLowPower, "headless": device.isHeadless,
        "unified_memory": device.hasUnifiedMemory,
        "supported_families": ["apple1": device.supportsFamily(.apple1),
            "apple7": device.supportsFamily(.apple7), "apple8": device.supportsFamily(.apple8),
            "mac1": device.supportsFamily(.mac1), "mac2": device.supportsFamily(.mac2),
            "common3": device.supportsFamily(.common3)], "offscreen_render": rendered]
} else {
    report["metal"] = ["device_present": false, "offscreen_render": ["ok": false, "failure": "no_metal_device"]]
}
let requirements: [(String, Bool)] = [("apple_silicon_architecture", architecture == "arm64"),
    ("macos_15_or_later", os.majorVersion >= 15), ("ios_support_uikit_present", frameworkPresent),
    ("native_metal_render_verified", metalOK), ("accessibility_trusted", accessibility),
    ("synthetic_render_minimum_30_fps", performanceOK),
    ("screen_capture_access", screenCapture), ("console_user_matches", sameConsoleUser),
    ("window_server_present", windowServer)]
report["requirements"] = Dictionary(uniqueKeysWithValues: requirements)
report["candidate_eligible"] = requirements.allSatisfy { $0.1 }
report["failed_requirements"] = requirements.filter { !$0.1 }.map { $0.0 }
report["eligibility_scope"] = "candidate_for_PlayCover_smoke_only_not_game_validation"
do {
    let data = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
} catch {
    FileHandle.standardOutput.write(Data("{\"schema\":1,\"candidate_eligible\":false,\"error\":\"report_encoding_failed\"}\n".utf8))
    exit(2)
}
