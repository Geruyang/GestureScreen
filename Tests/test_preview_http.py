"""End-to-end local HTTP preview tests, synthetic frames and temporary storage."""
import sys
from pathlib import Path
import tempfile
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "HostTools"))
from capture_server import CaptureStore, CaptureHTTPServer
from capture_client import CaptureAPI


class PreviewHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CaptureStore(Path(self.tmp.name))
        self.server = CaptureHTTPServer(("127.0.0.1", 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
        self.thread.start()
        self.api = CaptureAPI(f"http://127.0.0.1:{self.server.server_address[1]}")
        self.api.request("/api/state")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.tmp.cleanup()

    def test_http_preview_sequence_and_empty(self):
        self.assertEqual(self.api.request("/api/preview.png?after=0")[0], 204)
        self.api.request("/api/preview", dict(action="start", owner="a"*32))
        ticket = self.store.begin(dict(epoch=self.store.epoch, device_id="synthetic", frame_id=5, capture_ms=100))
        self.store.commit(ticket, b"\x84\x10"*76800)
        self.store.release(ticket)
        code, headers, png = self.api.request("/api/preview.png?after=0")
        self.assertEqual(code, 200)
        self.assertEqual(headers["X-Frame-ID"], "5")
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertEqual(self.api.request("/api/preview.png?after=1")[0], 204)
        self.assertEqual(self.api.request("/api/state")["total"], 0)
        self.api.request("/api/preview", dict(action="stop", owner="a"*32))

    def test_preview_control_requires_token(self):
        self.api.token = "invalid"
        with self.assertRaises(RuntimeError):
            self.api.request("/api/preview", dict(action="start", owner="a"*32))
        self.assertFalse(self.store.preview_status()["enabled"])

    def test_bad_sequence_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.api.request("/api/preview.png?after=NaN")


if __name__ == "__main__":
    unittest.main()
