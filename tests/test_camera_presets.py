"""Checks for the five EMEET exposure levels and device-specific limits."""

import unittest

from modules.camera_presets import CAMERA_IMAGE_PRESETS, fit_control_to_range, current_control_value


class CameraPresetTests(unittest.TestCase):
    def test_five_levels_progress_from_dark_to_bright(self):
        keys = ["night_plus", "night", "balanced", "daylight", "sunlight"]
        self.assertEqual(len(CAMERA_IMAGE_PRESETS), 5)
        exposures = [CAMERA_IMAGE_PRESETS[key]["exposure"] for key in keys]
        self.assertEqual(exposures, sorted(exposures, reverse=True))

    def test_clamps_to_camera_range_and_step(self):
        controls = """exposure_time_absolute 0x009a0902 (int) : min=10 max=500 step=5 default=80 value=80
gain 0x00980913 (int) : min=0 max=20 step=2 default=0 value=0"""
        self.assertEqual(fit_control_to_range(controls, "exposure_time_absolute", 600), 500)
        self.assertEqual(fit_control_to_range(controls, "exposure_time_absolute", 5), 10)
        self.assertEqual(fit_control_to_range(controls, "exposure_time_absolute", 43), 40)
        self.assertEqual(fit_control_to_range(controls, "gain", 30), 20)

    def test_reads_back_applied_values(self):
        output = "exposure_time_absolute: 10\ngain: 20\n"
        self.assertEqual(current_control_value(output, "exposure_time_absolute"), 10)
        self.assertEqual(current_control_value(output, "gain"), 20)


if __name__ == "__main__":
    unittest.main()
