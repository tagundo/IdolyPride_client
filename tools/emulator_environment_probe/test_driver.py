import unittest
from run_probe import (PACKAGE, REDROID_GUEST, TRANSLATED_GUEST, guest_properties,
                       scoped_crash_log, validate_report)


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

    def test_crash_capture_excludes_other_apps(self):
        log = ("11-10 01:02:03.001 123 124 F libc : Fatal signal 4\n"
               "11-10 01:02:03.002 900 900 F DEBUG : *** *** ***\n"
               "11-10 01:02:03.003 900 900 F DEBUG : pid: 123, tid: 124 >>> " + PACKAGE + " <<<\n"
               "11-10 01:02:03.004 900 900 F DEBUG : #00 pc 000000\n"
               "11-10 01:02:04.001 901 901 F DEBUG : *** *** ***\n"
               "11-10 01:02:04.002 901 901 F DEBUG : pid: 999 >>> other.app <<<\n"
               "11-10 01:02:04.003 901 901 F DEBUG : unrelated private text\n")
        result = scoped_crash_log(log, "123")
        self.assertIn("Fatal signal 4", result)
        self.assertIn("#00 pc", result)
        self.assertNotIn("other.app", result)
        self.assertNotIn("unrelated private text", result)

    def test_prior_probe_pid_cannot_supply_current_crash(self):
        log = ("11-10 01:02:03.002 900 900 F DEBUG : *** *** ***\n"
               "11-10 01:02:03.003 900 900 F DEBUG : pid: 122, tid: 124 >>> " + PACKAGE + " <<<\n")
        self.assertEqual("", scoped_crash_log(log, "123"))


class GuestTests(unittest.TestCase):
    def test_default_guest_records_the_unchanged_emulator_properties(self):
        self.assertEqual(("ro.build.version.sdk", "ro.product.cpu.abilist", "ro.dalvik.vm.native.bridge",
                          "ro.hardware.egl", "ro.boot.qemu.avd_name", "ro.build.version.incremental"),
                         guest_properties(TRANSLATED_GUEST))

    def test_redroid_records_its_native_gpu_and_codec_stack(self):
        names = guest_properties(REDROID_GUEST)
        self.assertEqual(guest_properties(TRANSLATED_GUEST), names[:6])
        for name in ("ro.hardware", "ro.product.device", "ro.hardware.vulkan", "ro.hardware.gralloc",
                     "ro.boot.redroid_gpu_mode", "debug.stagefright.ccodec", "sys.use_memfd"):
            self.assertIn(name, names)
        with self.assertRaises(ValueError):
            guest_properties("cuttlefish")

    def test_pass_gate_is_identical_for_every_guest(self):
        # The guest only changes recorded identity, never validate_report.
        self.assertTrue(validate_report(successful()))


if __name__ == "__main__":
    unittest.main()
