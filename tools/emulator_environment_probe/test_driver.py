import unittest
from run_probe import validate_report


def successful():
    return {"schema": 1, "synthetic_only": True, "stage": "complete",
            "conversion": {"ok": True},
            "graphics": {"ok": True,
                         "vertex_vec4_300": {"link": True, "active_vec4_array_size": 300},
                         "fragment_vec4_300": {"link": True, "active_vec4_array_size": 300}}}


class GateTests(unittest.TestCase):
    def test_complete_report_passes(self):
        self.assertTrue(validate_report(successful()))

    def test_preconversion_graphics_cannot_pass(self):
        report = successful()
        report["stage"] = "conversion_begin"
        report.pop("conversion")
        self.assertFalse(validate_report(report))

    def test_context_and_claimed_limits_are_insufficient(self):
        for key in ("vertex_vec4_300", "fragment_vec4_300"):
            report = successful()
            report["graphics"]["max_vertex_uniform_vectors"] = 4096
            report["graphics"]["max_fragment_uniform_vectors"] = 4096
            report["graphics"][key]["link"] = False
            self.assertFalse(validate_report(report))

    def test_optimized_out_or_missing_uniforms_cannot_pass(self):
        for key in ("vertex_vec4_300", "fragment_vec4_300"):
            for size in (0, 1, 299, None):
                report = successful()
                report["graphics"][key]["active_vec4_array_size"] = size
                self.assertFalse(validate_report(report))

    def test_malformed_or_failed_report_cannot_pass(self):
        for report in (None, {}, [], {"schema": 1},
                       {**successful(), "graphics": []},
                       {**successful(), "conversion": {"ok": False}}):
            self.assertFalse(validate_report(report))


if __name__ == "__main__":
    unittest.main()
