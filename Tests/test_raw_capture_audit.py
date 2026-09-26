"""Independent synthetic audit of the raw-only capture contract.

Uses a disposable directory and never opens a camera, USB port, production
history, model assets, or a fixed HTTP port.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import shutil
import sys
import tempfile
import time
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "HostTools"))
from capture_server import ApiError  # noqa: E402
from managed_capture import ManagedCaptureStore  # noqa: E402


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def frame(value):
    return value.to_bytes(2, "big") * (320 * 240)


class RawCaptureAudit(unittest.TestCase):
    OWNER = "a" * 32

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="raw-capture-audit-")
        self.root = Path(self.temporary.name)
        self.clock = Clock()
        self.store = ManagedCaptureStore(self.root, clock=self.clock, raw_capture_only=True)
        self.store.workspace_action({"action": "open", "owner": self.OWNER})
        self.store.session_action({"action": "new", "split": "train", "name": "synthetic",
                                   "sensor_profile": "synthetic", "exposure_profile": "synthetic"})
        self.session_id = self.store.current["session_id"]

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def start(self):
        state = self.store.clip_action({"action": "start", "fps": 5,
                                        "label": "POINT_LEFT", "duration_seconds": 60,
                                        "selection_count": 5})
        return state["active_clip"]["clip_id"]

    def upload(self, frame_id, value):
        self.clock.advance(0.25)
        ticket = self.store.begin({"device_id": "synthetic-board", "frame_id": frame_id,
                                   "capture_ms": frame_id * 250, "epoch": self.store.epoch})
        try:
            status, response = self.store.commit(ticket, frame(value))
            self.assertEqual(status, 201)
            return response["record_id"]
        finally:
            self.store.release(ticket)

    def wait_finished(self, clip_id):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = self.store.state()
            pending = next((c for c in state["pending_clips"] if c["clip_id"] == clip_id), None)
            if pending is None:
                return state
            if pending.get("processing_error"):
                self.fail(pending["processing_error"])
            time.sleep(0.02)
        self.fail("clip did not finish")

    def test_all_committed_frames_and_repeated_pixels_survive_video_and_raw_export(self):
        clip_id = self.start()
        records = [self.upload(1, 0xF800), self.upload(2, 0x07E0),
                   self.upload(3, 0x07E0), self.upload(4, 0x001F),
                   self.upload(5, 0x0000), self.upload(6, 0xFFFF)]
        self.assertEqual(len(set(records)), 6)
        self.store.clip_action({"action": "finish"})
        state = self.wait_finished(clip_id)
        self.assertEqual((state["total"], state["included"], state["exportable_total"]), (6, 0, 6))
        clip = self.store.clips[clip_id]
        self.assertTrue(clip["capture_only"])
        self.assertEqual(clip["record_ids"], records)
        self.assertNotIn("selected_record_ids", clip)
        self.assertEqual(len(list((self.root / "sessions" / self.session_id / "frames").glob("*.rgb565"))), 6)
        self.assertEqual(len(list((self.root / "sessions" / self.session_id / "frames").glob("*.png"))), 6)
        for record in records:
            row = self.store.records[record]
            self.assertTrue(row["excluded"])
            data = (self.root / row["file"]).read_bytes()
            self.assertEqual((len(data), hashlib.sha256(data).hexdigest()), (153600, row["sha256"]))
        self.assertEqual(self.store.records[records[2]]["training_duplicate_of"], records[1])
        video = (self.root / clip["video_file"]).read_bytes()
        self.assertEqual(video[:4], b"RIFF")
        self.assertEqual(video.count(b"00db"), 12)  # 6 media chunks + 6 AVI index entries
        pos = video.index(b"avih")
        self.assertEqual(struct.unpack_from("<I", video, pos + 8 + 16)[0], 6)
        self.store.session_action({"action": "save"})
        result = self.store.export("current")
        manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(result["sample_count"], 6)
        self.assertEqual((manifest["purpose"], manifest["training_ready"]), ("raw_capture_unreviewed", False))
        self.assertEqual([r["record_id"] for r in manifest["samples"]], records)
        self.assertTrue(all(r["excluded"] and r["review_status"] == "unreviewed" for r in manifest["samples"]))
        self.assertEqual(len(manifest["clips"]), 1)

    def test_reopen_replays_capture_only_exclusion_and_keeps_saved_files(self):
        clip_id = self.start()
        record = self.upload(1, 0xF800)
        self.store.clip_action({"action": "finish"})
        self.wait_finished(clip_id)
        self.store.session_action({"action": "save"})
        raw_path = self.root / self.store.records[record]["file"]
        digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        self.store.close()
        self.store = ManagedCaptureStore(self.root, clock=self.clock, raw_capture_only=True)
        self.assertTrue(self.store.records[record]["excluded"])
        self.assertTrue(self.store.clips[clip_id]["capture_only"])
        self.assertEqual(hashlib.sha256(raw_path.read_bytes()).hexdigest(), digest)
        self.assertEqual((self.store.state()["history_total"], self.store.state()["history_included"]), (1, 0))

    def test_raw_mode_refuses_training_qualification_through_annotation(self):
        clip_id = self.start()
        record = self.upload(1, 0xF800)
        self.store.clip_action({"action": "finish"})
        self.wait_finished(clip_id)
        with self.assertRaises(ApiError) as error:
            self.store.annotate({"record_id": record, "label": "POINT_LEFT", "excluded": False})
        self.assertEqual(error.exception.status, 409)
        self.assertTrue(self.store.records[record]["excluded"])

    def test_entire_capture_folder_can_move_without_rewriting_media_paths(self):
        clip_id = self.start()
        record = self.upload(1, 0xF800)
        self.store.clip_action({"action": "finish"})
        self.wait_finished(clip_id)
        self.store.session_action({"action": "save"})
        exported = Path(self.store.export("current")["manifest"])
        manifest_bytes = exported.read_bytes()
        self.store.close()
        with tempfile.TemporaryDirectory(prefix="moved location-") as destination:
            moved = Path(destination) / "中文位置" / "captures"
            shutil.copytree(self.root, moved)
            restored = ManagedCaptureStore(moved, raw_capture_only=True)
            try:
                self.assertEqual(restored.state()['history_total'], 1)
                row = restored.records[record]
                self.assertFalse(Path(row['file']).is_absolute())
                self.assertFalse(Path(row['video_file']).is_absolute())
                self.assertEqual(hashlib.sha256((moved / row['file']).read_bytes()).hexdigest(), row['sha256'])
                self.assertTrue((moved / row['video_file']).is_file())
                self.assertEqual((moved / exported.name).read_bytes(), manifest_bytes)
                self.assertEqual(restored.export('history')['sample_count'], 1)
            finally:
                restored.close()

    def test_legacy_saved_session_and_training_manifest_bytes_remain_unchanged(self):
        # Create a legacy retained session in the same disposable root, then
        # exercise the new raw-only workflow without rewriting prior material.
        self.store.workspace_action({"action": "close", "owner": self.OWNER})
        self.store.close()
        legacy = ManagedCaptureStore(self.root, clock=self.clock, raw_capture_only=False)
        try:
            legacy.workspace_action({"action": "open", "owner": self.OWNER})
            legacy.session_action({"action": "new", "split": "train", "name": "legacy",
                                   "sensor_profile": "synthetic", "exposure_profile": "synthetic"})
            old_session = legacy.current["session_id"]
            legacy.clip_action({"action": "start", "fps": 5, "label": "POINT_LEFT",
                                "duration_seconds": 60, "selection_count": 5})
            for index in range(1, 7):
                self.clock.advance(0.25)
                ticket = legacy.begin({"device_id": "synthetic-board", "frame_id": index,
                                       "capture_ms": index * 250, "epoch": legacy.epoch})
                try:
                    legacy.commit(ticket, frame(0x1000 + index))
                finally:
                    legacy.release(ticket)
            legacy.clip_action({"action": "finish"})
            deadline = time.monotonic() + 10
            while legacy.state()["pending_clips"] and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertFalse(legacy.state()["pending_clips"])
            legacy.session_action({"action": "save"})
            old_manifest = Path(legacy.export("current")["manifest"])
            legacy_rows = json.loads(old_manifest.read_text(encoding="utf-8"))
            self.assertEqual(len(legacy_rows["samples"]), 5)
            self.assertNotIn("purpose", legacy_rows)
            self.assertTrue(all(not row["excluded"] for row in legacy_rows["samples"]))
            old_files = list((self.root / "sessions" / old_session).rglob("*")) + [old_manifest]
            prior = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in old_files if p.is_file()}
        finally:
            legacy.close()
        self.store = ManagedCaptureStore(self.root, clock=self.clock, raw_capture_only=True)
        self.store.workspace_action({"action": "open", "owner": self.OWNER})
        self.store.session_action({"action": "new", "split": "train", "name": "raw",
                                   "sensor_profile": "synthetic", "exposure_profile": "synthetic"})
        clip_id = self.start()
        self.upload(7, 0xF800)
        self.store.clip_action({"action": "finish"})
        self.wait_finished(clip_id)
        self.store.session_action({"action": "save"})
        self.store.export("current")
        self.assertEqual({name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in prior}, prior)


if __name__ == "__main__":
    unittest.main()
