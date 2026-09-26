"""Isolated synthetic proof of stop/finish, selection, and saved-history counts.

No production data, USB port, firmware probe, or fixed HTTP port is used.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "HostTools"))
from capture_server import ApiError  # noqa: E402
from managed_capture import ManagedCaptureStore  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def raw_frame(number):
    color = (((number * 3) & 31) << 11) | (((number * 5) & 63) << 5) | ((number * 7) & 31)
    return color.to_bytes(2, "big") * (320 * 240)


class SelectionWorkflowTests(unittest.TestCase):
    OWNER = "a" * 32
    OTHER = "b" * 32

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="selection-workflow-")
        self.root = Path(self.tmp.name)
        self.clock = Clock()
        self.store = ManagedCaptureStore(self.root, clock=self.clock, max_frames=50)
        self.store.workspace_action({"action": "open", "owner": self.OWNER})
        self.session_id = self.new("合成一")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def new(self, name):
        self.store.session_action({"action": "new", "name": name, "split": "train",
                                   "sensor_profile": "synthetic", "exposure_profile": "synthetic"})
        return self.store.current["session_id"]

    def start(self):
        result = self.store.clip_action({"action": "start", "fps": 5, "label": "POINT_LEFT",
                                         "duration_seconds": 60, "selection_count": 5})
        return result["active_clip"]["clip_id"]

    def upload(self, number):
        self.clock.advance(0.25)
        ticket = self.store.begin({"device_id": "synthetic-board", "frame_id": number,
                                   "capture_ms": 1000 + number * 250, "epoch": self.store.epoch})
        try:
            status, _ = self.store.commit(ticket, raw_frame(number))
            self.assertEqual(status, 201)
        finally:
            self.store.release(ticket)

    def wait_processed(self, clip_id, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.store.state()
            pending = next((row for row in state["pending_clips"] if row["clip_id"] == clip_id), None)
            if pending is None or not pending.get("processing"):
                return state, pending
            time.sleep(0.02)
        self.fail("synthetic clip did not finish processing")

    def test_early_finish_selects_then_save_and_export_have_five_samples(self):
        clip_id = self.start()
        for number in range(1, 9):
            self.upload(number)
        during = self.store.state()
        self.assertEqual((during["total"], during["included"]), (8, 0))
        self.store.clip_action({"action": "finish"})
        state, pending = self.wait_processed(clip_id)
        self.assertIsNone(pending)
        self.assertEqual((state["total"], state["included"]), (8, 5))
        self.assertEqual(self.store.clips[clip_id]["selected_record_ids"].__len__(), 5)
        self.store.session_action({"action": "save"})
        saved = self.store.state()
        self.assertEqual((saved["total"], saved["included"]), (8, 5))
        self.assertEqual((saved["history_total"], saved["history_included"]), (8, 5))
        exported = self.store.export("current")
        manifest = json.loads(Path(exported["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["samples"]), 5)
        self.store.workspace_action({"action": "close", "owner": self.OWNER})
        self.store.workspace_action({"action": "open", "owner": self.OTHER})
        new_view = self.store.state()
        self.assertEqual((new_view["total"], new_view["included"]), (0, 0))
        self.assertEqual((new_view["history_total"], new_view["history_included"]), (8, 5))
        history_export = self.store.export("history")
        self.assertEqual(history_export["sample_count"], 5)

    def test_inflight_old_epoch_frame_cannot_join_finished_selection(self):
        clip_id = self.start()
        for number in range(1, 6):
            self.upload(number)
        self.clock.advance(0.25)
        late = self.store.begin({"device_id": "synthetic-board", "frame_id": 6,
                                 "capture_ms": 2500, "epoch": self.store.epoch})
        try:
            self.store.clip_action({"action": "finish"})
            self.assertTrue(self.store.state()["pending_clips"][0]["processing"])
            with self.assertRaises(ApiError) as failure:
                self.store.commit(late, raw_frame(6))
            self.assertEqual(failure.exception.status, 409)
        finally:
            self.store.release(late)
        state, pending = self.wait_processed(clip_id)
        self.assertIsNone(pending)
        self.assertEqual((state["total"], state["included"]), (5, 5))

    def test_empty_finish_shows_recoverable_processing_error(self):
        clip_id = self.start()
        self.store.clip_action({"action": "finish"})
        state, pending = self.wait_processed(clip_id)
        self.assertIsNotNone(pending)
        self.assertTrue(pending.get("processing_error"))
        self.assertEqual((state["total"], state["included"]), (0, 0))
        self.assertEqual(list(self.root.rglob("*.avi")), [])
        self.store.clip_action({"action": "discard", "clip_id": clip_id})
        self.assertEqual(self.store.state()["pending_clips"], [])

    def test_new_session_cancels_waiting_finish_without_ghost_error(self):
        clip_id = self.start()
        late = self.store.begin({"device_id": "synthetic-board", "frame_id": 1,
                                 "capture_ms": 1001, "epoch": self.store.epoch})
        try:
            self.store.clip_action({"action": "finish"})
            self.assertTrue(self.store.state()["pending_clips"][0]["processing"])
            old_folder = self.root / "sessions" / self.session_id
            next_id = self.new("合成二")
            self.assertFalse(old_folder.exists())
            self.assertNotEqual(next_id, self.session_id)
            with self.assertRaises(ApiError):
                self.store.commit(late, raw_frame(1))
        finally:
            self.store.release(late)
        time.sleep(0.1)
        state = self.store.state()
        self.assertEqual(state["pending_clips"], [])
        self.assertEqual(state["last_error"], "")
        self.assertEqual((state["total"], state["included"]), (0, 0))

    def test_timer_expiry_uses_same_automatic_selection(self):
        clip_id = self.start()
        for number in range(1, 7):
            self.upload(number)
        self.store._finish_timed_clip(clip_id)
        state, pending = self.wait_processed(clip_id)
        self.assertIsNone(pending)
        self.assertEqual((state["total"], state["included"]), (6, 5))


if __name__ == "__main__":
    unittest.main()
