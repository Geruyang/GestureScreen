"""Independent data-lifecycle regressions in isolated synthetic directories.

No USB port, SWD probe, production HTTP port, or saved history is accessed.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "HostTools"))
from managed_capture import ManagedCaptureStore  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class StudioAuditTests(unittest.TestCase):
    OWNER = "a" * 32
    OTHER = "b" * 32

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="studio-audit-")
        self.root = Path(self.temporary.name)
        self.clock = Clock()
        self.store = ManagedCaptureStore(self.root, clock=self.clock)

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def new(self):
        self.store.workspace_action({"action": "open", "owner": self.OWNER})
        self.store.session_action({"action": "new", "name": "合成隔离审计", "split": "train",
                                   "sensor_profile": "synthetic", "exposure_profile": "synthetic"})
        return self.store.current["session_id"]

    def test_service_shutdown_after_lost_window_preserves_unfinished_staging(self):
        session_id = self.new()
        folder = self.root / "sessions" / session_id
        self.assertTrue(folder.is_dir())
        self.clock.advance(self.store.LEASE_SECONDS + 1)
        with self.store.lock:
            self.store._expire()
        self.assertIsNone(self.store.workspace_owner)
        self.assertTrue(folder.is_dir())  # lease loss only freezes
        self.store.close()  # capture_server finally calls this on idle shutdown
        self.assertTrue(folder.is_dir(), "graceful idle shutdown must not delete unclosed staging")
        self.store = ManagedCaptureStore(self.root, clock=self.clock)
        self.assertIn(session_id, self.store.sessions)
        self.assertTrue(folder.is_dir())
        # A subsequent explicit different-owner open is the authorized cleanup point.
        self.store.workspace_action({"action": "open", "owner": self.OTHER})
        self.assertFalse(folder.exists())

    def test_preview_only_upload_does_not_block_save_or_export(self):
        session_id = self.new()
        self.store.preview_action({"action": "start", "owner": self.OWNER})
        ticket = self.store.begin({"epoch": self.store.epoch, "device_id": "synthetic-board",
                                   "frame_id": 1, "capture_ms": 10})
        self.assertTrue(ticket["preview_only"])
        try:
            saved = self.store.session_action({"action": "save"})
            self.assertTrue(saved["session_saved"])
            self.assertEqual(self.store.sessions[session_id]["lifecycle"], "retained")
            exported = self.store.export("current")
            self.assertTrue(Path(exported["manifest"]).is_file())
            self.assertEqual(exported["sample_count"], 0)
        finally:
            self.store.release(ticket)

    def test_failed_session_metadata_write_cannot_block_next_service_start(self):
        previous_id = self.new()
        previous_folder = self.root / "sessions" / previous_id
        with patch("managed_capture.atomic_json", side_effect=OSError("synthetic disk write failure")):
            with self.assertRaises(OSError):
                self.store.session_action({"action": "new", "name": "第二个合成会话", "split": "train",
                                           "sensor_profile": "synthetic", "exposure_profile": "synthetic"})
        self.assertTrue(previous_folder.is_dir())
        self.store.close()
        # An interrupted directory creation must not make all existing sessions unreadable.
        self.store = ManagedCaptureStore(self.root, clock=self.clock)
        self.assertIn(previous_id, self.store.sessions)
        self.assertTrue(previous_folder.is_dir())


if __name__ == "__main__":
    unittest.main()
