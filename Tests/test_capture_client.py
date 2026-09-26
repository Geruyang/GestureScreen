"""Native-client lifecycle regressions without a display or physical camera."""
import sys
from pathlib import Path
import queue
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"HostTools"))
from capture_client import CaptureClient


class ClientLifecycleTests(unittest.TestCase):
    def test_service_restart_resets_cursor_and_observation(self):
        client = CaptureClient.__new__(CaptureClient)
        client.stop = threading.Event()
        client.observing = True
        client.owner = "a"*32
        client.events = queue.Queue()
        client.images = queue.Queue(maxsize=1)
        state_count, preview_paths = 0, []

        def request(path, data=None):
            nonlocal state_count
            if path == "/api/state":
                state_count += 1
                return dict(ui_token="old" if state_count == 1 else "new", capabilities=["live_preview_v1"])
            if path == "/api/preview":
                return {}
            preview_paths.append(path)
            if len(preview_paths) == 2:
                client.stop.set()
            return 200, {"X-Frame-Sequence":"10" if len(preview_paths)==1 else "1",
                         "X-Frame-ID":"1", "X-Control-Epoch":"100"}, b"synthetic"

        client.api = SimpleNamespace(request=request)
        with patch("capture_client.time.monotonic", side_effect=[100.,102.]):
            client.poll()
        self.assertEqual(preview_paths, ["/api/preview.png?after=0"]*2)
        self.assertFalse(client.observing)
        self.assertEqual(client.images.get_nowait()[-1], "new")

    def test_close_cannot_race_pending_start_request(self):
        client = CaptureClient.__new__(CaptureClient)
        client.busy = True
        messages = []
        client.message = SimpleNamespace(set=messages.append)
        client.root = SimpleNamespace(destroy=lambda: self.fail("must not destroy during pending POST"))
        client.close()
        self.assertEqual(len(messages), 1)
        self.assertIn("等待", messages[0])


if __name__ == "__main__":
    unittest.main()
