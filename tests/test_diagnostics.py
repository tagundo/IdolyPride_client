"""Boundaries and concurrency for untrusted local client diagnostics."""
from concurrent.futures import ThreadPoolExecutor
import json
import unittest

from idoly_local.diagnostics import ClientDiagnostics


def body(events, **overrides):
    result = {"schema": 1, "source": "android-game", "events": events}
    result.update(overrides)
    return json.dumps(result).encode()


def exception(**overrides):
    result = {"kind": "exception", "type": "NullReferenceException",
              "frames": ["Solis.OutGame.HomeTopScreenPresenter.SetHomeEnterData"]}
    result.update(overrides)
    return result


def status(code="collector_started", **overrides):
    result = {"kind": "status", "code": code}
    result.update(overrides)
    return result


class ClientDiagnosticsTests(unittest.TestCase):
    def test_exception_batch_produces_canonical_safe_log_and_snapshot(self):
        logs = []
        receiver = ClientDiagnostics(logs.append)
        events = [status(), status("logcat_started"), exception()]
        result = receiver.receive(body(events))
        expected = "게임 예외: NullReferenceException @ Solis.OutGame.HomeTopScreenPresenter.SetHomeEnterData"
        self.assertEqual(result, {"accepted": 3, "summary": expected})
        self.assertEqual(logs, ["게임 진단 수집 시작", "게임 로그 수집 시작", expected])
        state = receiver.status()
        self.assertEqual(state["received_events"], 3)
        self.assertEqual(state["events"], events)
        self.assertEqual(state["latest_exception"], events[-1])
        self.assertEqual(state["progress"], {"stage": "unity_exception", "summary": expected})
        self.assertTrue(state["collector_started"])
        self.assertTrue(state["logcat_running"])
        self.assertEqual(json.loads(json.dumps(state)), state)

    def test_fixed_statuses_track_latest_observations_and_stop(self):
        receiver = ClientDiagnostics()
        self.assertEqual(receiver.status()["progress"]["stage"], "waiting_for_client")
        receiver.receive(body([status("shader_warmup_wait")]))
        self.assertTrue(receiver.status()["shader_warmup_wait"])
        self.assertEqual(receiver.status()["summary"], "셰이더 준비 완료 대기 중")
        receiver.receive(body([status("logcat_started"), status("logcat_stopped")]))
        self.assertFalse(receiver.status()["logcat_running"])
        self.assertEqual(receiver.status()["progress"]["stage"], "collector_stopped")
        # No completion signal exists in schema 1: seeing another event does not
        # establish that shader warmup finished.
        self.assertTrue(receiver.status()["shader_warmup_wait"])

    def test_static_compiler_frames_and_qualified_exception_types_are_allowed(self):
        frames = ["Solis.SolisInitializer+<StartShaderWarmUpAsync>d__15.MoveNext",
                  "Solis.OutGame.HomeTopScreenPresenter+<>c.<HomeEnterAsync>b__78_0",
                  "Cysharp.Threading.Tasks.CompilerServices.AsyncUniTaskMethodBuilder`1.SetException"]
        receiver = ClientDiagnostics()
        receiver.receive(body([exception(type="System.NullReferenceException", frames=frames),
                               exception(type="NativeError", frames=[])]))
        self.assertEqual(receiver.status()["events"][0]["frames"], frames)
        self.assertEqual(receiver.status()["summary"], "게임 예외: NativeError")

    def test_rejects_arbitrary_text_fields_and_nonstatic_frames(self):
        bad_events = [
            exception(message="sensitive"), exception(url="https://example.com"),
            exception(type="NullReferenceException: sensitive"), exception(type="arbitrary"),
            exception(type="오류Exception"), exception(type="Exception\n"),
            exception(frames=["Solis.Home.Enter(user=secret)"]),
            exception(frames=["Solis.Home.Enter [0x1234]"]),
            exception(frames=["/private/user/Home.Enter"]),
            exception(frames=["https://example.com"]),
            exception(frames=["Solis.Home.Enter\nsecret"]),
            exception(frames=["StandaloneMethod"]),
            status(message="sensitive"), status("unknown"),
            {"kind": "asset", "name": "actor-shader"}, {}, None,
        ]
        for event in bad_events:
            with self.subTest(event=event), self.assertRaises(ValueError):
                ClientDiagnostics().receive(body([event]))

    def test_envelope_is_exact_and_schema_is_not_boolean(self):
        payloads = [body([status()], schema=True), body([status()], schema=2),
                    body([status()], source="ios-game"), body([status()], time=123),
                    body([],), body([status()] * 33), body("status"),
                    b'[]', b'{"schema":1,"source":"android-game"}']
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                ClientDiagnostics().receive(payload)

    def test_body_parser_rejects_oversize_malformed_and_duplicate_fields(self):
        valid = body([status()])
        payloads = [b"", b" " * 32769, b"\xff", b"{", valid.decode(),
                    b'{"schema":1,"schema":1,"source":"android-game","events":[]}',
                    b'{"schema":NaN,"source":"android-game","events":[]}',
                    b'{"schema":1,"source":"android-game","events":[' + b'[' * 2000 + b']' * 2000 + b']}',
                    body([status()]).replace(b'"kind": "status"', b'"kind":"status","kind":"status"')]
        for payload in payloads:
            with self.subTest(payload=str(payload)[:80]), self.assertRaises(ValueError):
                ClientDiagnostics().receive(payload)
        # The limit includes whitespace and is measured before JSON decoding.
        padded = valid + b" " * (32768 - len(valid))
        self.assertEqual(ClientDiagnostics().receive(padded)["accepted"], 1)

    def test_frame_count_lengths_and_field_types_are_bounded(self):
        good_frame = "A." + "b" * 190
        receiver = ClientDiagnostics()
        receiver.receive(body([exception(type="A" * 119 + "Exception", frames=[good_frame] * 16)]))
        bad = [exception(type="A" * 120 + "Exception"),
               exception(frames=[good_frame + "b"]), exception(frames=[good_frame] * 17),
               exception(type=123), exception(frames="Solis.Home.Enter"),
               exception(frames=[123]), status(code=[])]
        for event in bad:
            with self.subTest(event=event), self.assertRaises(ValueError):
                receiver.receive(body([event]))

    def test_bad_batch_is_atomic_and_does_not_call_callback(self):
        logs = []
        receiver = ClientDiagnostics(logs.append)
        receiver.receive(body([status()]))
        before = receiver.status()
        with self.assertRaises(ValueError):
            receiver.receive(body([exception(), status("unknown")]))
        self.assertEqual(receiver.status(), before)
        self.assertEqual(logs, ["게임 진단 수집 시작"])

    def test_ring_evicts_old_events_and_snapshots_do_not_alias_state(self):
        receiver = ClientDiagnostics()
        receiver.receive(body([exception()]))
        for _ in range(7):
            receiver.receive(body([status("logcat_started")] * 32))
        state = receiver.status()
        self.assertEqual(state["received_events"], 225)
        self.assertEqual(state["stored_events"], 200)
        self.assertEqual(state["events"], [status("logcat_started")] * 200)
        self.assertIsNotNone(state["latest_exception"])
        state["latest_exception"]["frames"].clear()
        state["events"].clear()
        state["progress"]["summary"] = "changed"
        self.assertEqual(receiver.status()["latest_exception"], exception())
        self.assertEqual(receiver.status()["stored_events"], 200)

    def test_concurrent_receives_keep_bounded_consistent_event_count(self):
        receiver = ClientDiagnostics()
        payload = body([status("logcat_started")] * 8)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(receiver.receive, [payload] * 40))
        self.assertTrue(all(result["accepted"] == 8 for result in results))
        self.assertEqual(receiver.status()["received_events"], 320)
        self.assertEqual(receiver.status()["stored_events"], 200)

    def test_callback_failures_are_isolated_and_callback_can_read_status(self):
        observed = []
        receiver = None

        def callback(_message):
            observed.append(receiver.status()["received_events"])
            raise RuntimeError("UI unavailable")

        receiver = ClientDiagnostics(callback)
        self.assertEqual(receiver.receive(body([status()]))["accepted"], 1)
        self.assertEqual(observed, [1])
        with self.assertRaises(ValueError):
            ClientDiagnostics("not callable")


if __name__ == "__main__":
    unittest.main()
