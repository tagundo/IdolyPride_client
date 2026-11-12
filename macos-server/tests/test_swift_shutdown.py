"""Execute the actual shutdown methods in a Foundation-only policy harness.

No AppKit, real child signals, user files, or Mac execution is required. A Swift
compiler is optional in the cloud; the test runs on a Swift-enabled host/CI.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("swiftc") is None, reason="Swift compiler unavailable")
def test_actual_swift_command_writer_never_waits_for_a_full_pipe(tmp_path):
    app = (Path(__file__).parents[1] / "App.swift").read_text()
    method = "    static func nonblockingWrite(" + app.split("    private static func nonblockingWrite(", 1)[1].split("\n    func start()", 1)[0]
    source = r'''
import Foundation
#if os(Linux)
import Glibc
#else
import Darwin
#endif
struct Writer {
''' + method + r'''
}
signal(SIGPIPE,SIG_IGN)
var descriptors:[Int32]=[0,0]
assert(pipe(&descriptors)==0)
let reader=descriptors[0], writer=descriptors[1]
defer { close(reader);close(writer) }
let flags=fcntl(writer,F_GETFL)
assert(fcntl(writer,F_SETFL,flags|O_NONBLOCK)==0)
assert(fcntl(reader,F_SETFL,fcntl(reader,F_GETFL)|O_NONBLOCK)==0)
var chunk=[UInt8](repeating:65,count:512)
var total=0
while true {
    let n=chunk.withUnsafeBytes { write(writer,$0.baseAddress,$0.count) }
    if n<0 { assert(errno==EAGAIN || errno==EWOULDBLOCK);break }
    total+=n
}
let start=ProcessInfo.processInfo.systemUptime
assert(!Writer.nonblockingWrite(Data("status\n".utf8),fileDescriptor:writer))
assert(ProcessInfo.processInfo.systemUptime-start<0.1)
var received=0
while true {
    let n=chunk.withUnsafeMutableBytes { read(reader,$0.baseAddress,$0.count) }
    if n<0 { assert(errno==EAGAIN || errno==EWOULDBLOCK);break }
    received+=n
}
assert(received==total) // Full-pipe failure appended no partial command.
assert(!Writer.nonblockingWrite(Data(repeating:66,count:513),fileDescriptor:writer))
assert(Writer.nonblockingWrite(Data("quit\n".utf8),fileDescriptor:writer))
let n=chunk.withUnsafeMutableBytes { read(reader,$0.baseAddress,$0.count) }
assert(n==5 && Array(chunk.prefix(5))==Array("quit\n".utf8))
assert(fcntl(writer,F_SETFL,flags)==0)
assert(!Writer.nonblockingWrite(Data("status\n".utf8),fileDescriptor:writer))
print("SWIFT_NONBLOCKING_PIPE_PASS")
'''
    path = tmp_path / "policy.swift"; path.write_text(source)
    executable = tmp_path / "policy"
    subprocess.run([shutil.which("swiftc"), str(path), "-o", str(executable)], check=True, capture_output=True, timeout=30)
    result = subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=3)
    assert result.stdout.strip() == "SWIFT_NONBLOCKING_PIPE_PASS"


@pytest.mark.skipif(shutil.which("swiftc") is None, reason="Swift compiler unavailable")
def test_swift_shutdown_does_not_wait_for_pipe_and_coalesces_requests(tmp_path):
    app=(Path(__file__).parents[1]/"App.swift").read_text()
    # Exercise the production methods themselves, rather than a translated
    # model. Replace only their surrounding UI/process objects with test doubles.
    methods="    func shutdown("+app.split("    func shutdown(",1)[1].split(
        "\n}\n\n@MainActor\nfinal class AppDelegate",1)[0]
    before=r'''
import Foundation
import Dispatch
#if os(Linux)
import Glibc
#else
import Darwin
#endif

let writeRelease=DispatchSemaphore(value:0)
let handlerRelease=DispatchSemaphore(value:0)
final class Handle {
    let blockWrite:Bool
    let blockHandler:Bool
    init(write:Bool=false,handler:Bool=false) { blockWrite=write;blockHandler=handler }
    var readabilityHandler: (() -> Void)? {
        get { nil }
        set { if blockHandler { handlerRelease.wait() } }
    }
    func write(contentsOf data:Data) throws { if blockWrite { writeRelease.wait() } }
    func close() throws {}
}
final class TestPipe {
    let fileHandleForWriting=Handle(write:true)
    let fileHandleForReading=Handle(handler:true)
}
final class Child {
    private let lock=NSLock()
    private var alive=true
    var isRunning:Bool { lock.lock();defer { lock.unlock() };return alive }
    func exited() { lock.lock();alive=false;lock.unlock() }
    func terminate() { assertionFailure("Grace period should not be reached") }
    // Never a valid process/group on supported hosts, even if a test fails.
    var processIdentifier:Int32 { -Int32.max }
}
final class Harness {
    var shutdownRequested=false, shutdownFinished=false
    var shutdownCompletions:[() -> Void]=[]
    var busy=false,canStop=true,status=""
    var presentationClient:[String:Any]?
    var statusTimer:Timer?
    var child:Child?=Child()
    var input:TestPipe?=TestPipe(), output:TestPipe?=TestPipe(), errors:TestPipe?=TestPipe()
    func checkpoint(_ value:String) {}
    func updatePresentationFeedback() {}
    func send(_ value:String) { try? input?.fileHandleForWriting.write(contentsOf:Data()) }
'''
    after=r'''
}
let model=Harness()
var callbacks=0
DispatchQueue.global().asyncAfter(deadline:.now()+2) {
    fputs("Swift shutdown policy timed out\n",stderr);exit(3)
}
let completion={
    callbacks+=1
    if callbacks==2 {
        assert(model.shutdownFinished)
        // A completed shutdown may finish a later request immediately.
        model.shutdown { callbacks+=1 }
        assert(callbacks==3)
        writeRelease.signal();handlerRelease.signal();handlerRelease.signal()
        print("SWIFT_SHUTDOWN_POLICY_PASS")
        exit(0)
    }
}
let start=ProcessInfo.processInfo.systemUptime
model.shutdown(completion)
model.shutdown(completion)
assert(callbacks==0) // Duplicate Quit must not complete before owned cleanup.
assert(ProcessInfo.processInfo.systemUptime-start<0.2) // Full pipe cannot block UI.
DispatchQueue.global().asyncAfter(deadline:.now()+0.1) { model.child?.exited() }
dispatchMain()
'''
    source=tmp_path/"ShutdownPolicy.swift";source.write_text(before+methods+after)
    binary=tmp_path/"shutdown-policy"
    subprocess.run([shutil.which("swiftc"),"-swift-version","5",str(source),"-o",str(binary)],
                   check=True,capture_output=True,timeout=30)
    result=subprocess.run([str(binary)],check=True,capture_output=True,text=True,timeout=3)
    assert "SWIFT_SHUTDOWN_POLICY_PASS" in result.stdout
