"""Preview isolation: synthetic input only, never opens a USB port."""
import sys
from pathlib import Path
import tempfile
import unittest
import zlib
import struct
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "HostTools"))
from capture_server import CaptureStore, ApiError, rgb565_to_png, FRAME_BYTES
from usb_capture import USBReceiver, Frame


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 100.0
        self.store = CaptureStore(Path(self.tmp.name), clock=lambda: self.now)
        self.owner = "a" * 32
        self.raw = b"\x84\x10" * (FRAME_BYTES // 2)

    def tearDown(self):
        self.tmp.cleanup()

    def begin_preview(self):
        self.store.preview_action(dict(action="start", owner=self.owner))
        return self.store.begin(dict(epoch=self.store.epoch, device_id="test", frame_id=1, capture_ms=10))

    def test_preview_never_saves_or_requires_session(self):
        ticket = self.begin_preview()
        self.assertEqual(self.store.commit(ticket, self.raw)[1], dict(ok=True, preview_only=True))
        self.store.release(ticket)
        self.assertEqual(self.store.records, {})
        self.assertEqual(list(Path(self.tmp.name).rglob("*")), [])
        self.assertIsNone(self.store.current)
        self.assertEqual(self.store.preview_status()["sequence"], 1)

    def test_expired_preview_rejects_inflight(self):
        ticket = self.begin_preview()
        self.now += 16
        self.assertIn(b"enabled=0", self.store.control())
        with self.assertRaises(ApiError):
            self.store.commit(ticket, self.raw)
        self.store.release(ticket)

    def test_stop_rejects_inflight(self):
        ticket = self.begin_preview()
        self.store.preview_action(dict(action="stop", owner=self.owner))
        with self.assertRaises(ApiError):
            self.store.commit(ticket, self.raw)
        self.store.release(ticket)

    def test_owner_cannot_be_stolen(self):
        self.store.preview_action(dict(action="start", owner=self.owner))
        for action in ("start", "keep", "stop"):
            with self.assertRaises(ApiError):
                self.store.preview_action(dict(action=action, owner="b" * 32))

    def test_epoch_change_invalidates_cached_image(self):
        ticket = self.begin_preview()
        self.store.commit(ticket, self.raw)
        self.store.release(ticket)
        self.assertIsNotNone(self.store.preview_png)
        self.store.session_action(dict(action="new", name="test", split="train", sensor_profile="test", exposure_profile="test"))
        self.assertIsNone(self.store.preview_png)

    def test_recording_transition_rejects_old_preview(self):
        ticket = self.begin_preview()
        self.store.release(ticket)
        self.store.session_action(dict(action="new", name="synthetic", split="calibration",
                                      sensor_profile="test", exposure_profile="test"))
        self.store.clip_action(dict(action="start", fps=5))
        with self.assertRaises(ApiError):
            self.store.commit(ticket, self.raw)
        self.assertIn(b"enabled=1", self.store.control())
        self.store.preview_action(dict(action="stop", owner=self.owner))
        self.assertIn(b"enabled=1", self.store.control())
        self.store.clip_action(dict(action="stop"))

    def test_usb_preview_counter_not_saved_or_duplicate(self):
        self.store.preview_action(dict(action="start", owner=self.owner))
        receiver = USBReceiver(self.store, "synthetic", serial_factory=lambda **_: None, api_error_type=ApiError)
        frame = Frame(dict(epoch=self.store.epoch, device_id="test", frame_id=1, capture_ms=10), self.raw)
        receiver.accept(frame)
        status = receiver.snapshot()
        self.assertEqual((status["previewed"], status["saved"], status["duplicates"]), (1, 0, 0))
        self.assertFalse(self.store.pending)

    def test_lut_all_65536_colors_pixel_exact(self):
        # Every RGB565 value occurs at least once; compare decoded PNG pixels
        # against the original bit-replication formula, not another lookup.
        raw = b"".join(struct.pack(">H", v % 65536) for v in range(76800))
        png = rgb565_to_png(raw)
        offset, payload = 8, b""
        while offset < len(png):
            length = struct.unpack(">I", png[offset:offset+4])[0]
            if png[offset+4:offset+8] == b"IDAT":
                payload += png[offset+8:offset+8+length]
            offset += length + 12
        pixels = zlib.decompress(payload)
        for i in range(76800):
            v = i % 65536
            r, g, b = v >> 11, (v >> 5) & 63, v & 31
            start = (i // 320) * 961 + 1 + (i % 320) * 3
            self.assertEqual(pixels[start:start+3], bytes(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))))


if __name__ == "__main__":
    unittest.main()
