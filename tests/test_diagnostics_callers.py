"""Validated static caller frames remain visible without replacing raw evidence."""
import json
import pytest

from idoly_local.diagnostics import ClientDiagnostics


def received(frames):
    logs = []
    receiver = ClientDiagnostics(logs.append)
    event = {"kind": "exception", "type": "ArgumentNullException", "frames": frames}
    raw = json.dumps({"schema": 1, "source": "android-game", "events": [event]}).encode()
    return receiver, event, logs, receiver.receive(raw)


@pytest.mark.parametrize("first", [
    "System.Linq.Enumerable.Where",
    "Cysharp.Threading.Tasks.UniTaskCompletionSource.GetResult",
    "UnityEngine.Events.UnityEvent.Invoke",
    "Unity.Collections.NativeArray.Dispose",
    "Google.Protobuf.MessageParser.ParseFrom",
    "Grpc.Core.Internal.AsyncCall.GetResult",
])
def test_framework_entry_exposes_nearest_nonframework_caller_but_preserves_all_frames(first):
    caller = "Solis.OutGame.SomeScreen+<RefreshAsync>d__12.MoveNext"
    frames = [first, "System.Threading.Tasks.Task.ThrowIfExceptional",
              "Cysharp.Threading.Tasks.CompilerServices.AsyncUniTaskMethodBuilder.SetException", caller,
              "Solis.OutGame.LaterCaller.Run"]
    receiver, event, logs, reply = received(frames)
    expected = "게임 예외: ArgumentNullException @ " + caller + " [" + first + "]"
    assert logs == [expected]
    assert reply == {"accepted": 1, "summary": expected}
    full = receiver.status()
    assert full["events"] == [event] and full["latest_exception"] == event
    assert receiver.status(include_events=False)["latest_exception"]["frames"] == frames


@pytest.mark.parametrize("frames,suffix", [
    ([], ""),
    (["System.Linq.Enumerable.Where"], " @ System.Linq.Enumerable.Where"),
    (["System.Linq.Enumerable.Where", "System.Threading.Tasks.Task.Wait",
      "Cysharp.Threading.Tasks.UniTask.GetAwaiter"], " @ System.Linq.Enumerable.Where"),
    (["Solis.Common.RadioButtonView.SetDisabled", "Solis.OutGame.SomeScreen.Open"],
     " @ Solis.Common.RadioButtonView.SetDisabled"),
    (["Systems.Linq.Enumerable.Where", "Solis.OutGame.SomeScreen.Open"],
     " @ Systems.Linq.Enumerable.Where"),
])
def test_missing_caller_or_existing_application_entry_keeps_observed_first_frame(frames, suffix):
    receiver, event, logs, reply = received(frames)
    assert reply["summary"] == "게임 예외: ArgumentNullException" + suffix
    assert receiver.status()["latest_exception"] == event
    assert logs == [reply["summary"]]
