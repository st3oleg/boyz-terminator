"""Hardware-free checks for CSI MJPEG frame parsing."""

import unittest

from modules.csi_camera import extract_jpegs


class CSIFrameParsingTests(unittest.TestCase):
    def test_split_jpeg_markers_and_multiple_frames(self):
        buffer = bytearray()
        self.assertEqual(extract_jpegs(buffer, b"noise\xff"), [])
        self.assertEqual(extract_jpegs(buffer, b"\xd8first\xff"), [])
        self.assertEqual(
            extract_jpegs(buffer, b"\xd9extra\xff\xd8second\xff\xd9"),
            [b"\xff\xd8first\xff\xd9", b"\xff\xd8second\xff\xd9"],
        )
        self.assertEqual(buffer, b"")

    def test_incomplete_oversized_frame_is_discarded(self):
        buffer = bytearray()
        self.assertEqual(extract_jpegs(buffer, b"\xff\xd8" + b"x" * (4 * 1024 * 1024)), [])
        self.assertEqual(buffer, b"")


if __name__ == "__main__":
    unittest.main()
