"""Keep the real client's anonymous title-screen order in native app QA."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("qa_emulator.py")
spec = importlib.util.spec_from_file_location("android_bootstrap_qa", SCRIPT)
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)


class BootstrapOrderTests(unittest.TestCase):
    def test_refund_term_is_anonymous_before_any_auth_login(self):
        schema = object()
        check = SimpleNamespace(keepAliveTimeMilliseconds=60000)
        term = SimpleNamespace(endDatetime=qa.LOCAL_REFUND_DATE, startDatetime=qa.LOCAL_REFUND_DATE,
                               shopInvalidStartDatetime=0)
        login = SimpleNamespace(gameAuthToken="local-fixture")
        with patch.object(qa, "rpc", side_effect=[check, term, login]) as call:
            self.assertEqual(qa.bootstrap(schema, 50051), (check, login))
        self.assertEqual([entry.args[2] for entry in call.call_args_list],
                         ["/api.System/Check", "/api.Refund/GetTerm", "/api.Auth/Login"])
        self.assertTrue(all(entry.args == (schema, 50051, entry.args[2]) and not entry.kwargs
                            for entry in call.call_args_list))

    def test_active_refund_or_open_financial_shop_stops_before_login(self):
        for dates in ((0, 0, 0), (qa.LOCAL_REFUND_DATE, qa.LOCAL_REFUND_DATE, qa.LOCAL_REFUND_DATE)):
            with self.subTest(dates=dates):
                term = SimpleNamespace(endDatetime=dates[0], startDatetime=dates[1], shopInvalidStartDatetime=dates[2])
                with patch.object(qa, "rpc", side_effect=[object(), term]) as call:
                    with self.assertRaisesRegex(RuntimeError, "Anonymous Refund.GetTerm"):
                        qa.bootstrap(object(), 50051)
                self.assertEqual(call.call_count, 2)


if __name__ == "__main__":
    unittest.main()
