"""Managed capture data-safety regressions using only synthetic workspace files."""

from __future__ import annotations

import hashlib
import http.client
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
ANALYSIS = PROJECT / "Build/reader-polish-20260922/analysis"
ANALYSIS.mkdir(parents=True, exist_ok=True)
sys.dont_write_bytecode = True
sys.path.insert(0, str(PROJECT / "HostTools"))

from capture_server import ApiError, CaptureHTTPServer, FRAME_BYTES  # noqa: E402
from managed_capture import DataDirectoryLock, ManagedCaptureStore  # noqa: E402
from usb_capture import USBReceiver  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def gray_frame():
    return b"\x84\x10" * (320 * 240)


class ManagedCaptureTests(unittest.TestCase):
    OWNER = "a" * 32
    OTHER = "b" * 32

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="managed-capture-test-", dir=ANALYSIS)).resolve()
        self.assertEqual(self.root.parent, ANALYSIS.resolve())
        self.clock = FakeClock()
        self.store = ManagedCaptureStore(self.root, max_frames=30, clock=self.clock)

    def tearDown(self):
        self.store.close()
        # Recursive cleanup is restricted to our generated direct child only.
        self.assertEqual(self.root.parent, ANALYSIS.resolve())
        self.assertTrue(self.root.name.startswith("managed-capture-test-"))
        shutil.rmtree(self.root)

    def open(self, owner=None):
        return self.store.workspace_action({"action": "open", "owner": owner or self.OWNER})

    def new(self):
        self.store.session_action({"action": "new", "name": "合成测试",
                                   "split": "train", "sensor_profile": "synthetic",
                                   "exposure_profile": "synthetic"})
        return self.store.current["session_id"]

    def one_frame(self, frame_id=1):
        self.store.clip_action({"action": "start", "fps": 2})
        raw = gray_frame()
        ticket = self.store.begin({"device_id": "test_board", "frame_id": frame_id,
                                   "capture_ms": 1000 + frame_id, "epoch": self.store.epoch})
        try:
            status, response = self.store.commit(ticket, raw)
            self.assertEqual(status, 201)
        finally:
            self.store.release(ticket)
        self.store.clip_action({"action": "stop"})
        clip_id = next(iter(self.store.pending_clips))
        self.store.clip_action({"action": "label", "clip_id": clip_id, "label": "PALM"})
        return response["record_id"]

    def test_temporary_new_close_and_retained_history(self):
        self.open()
        first = self.new()
        record = self.one_frame()
        original = self.root / self.store.records[record]["file"]
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        self.assertEqual(self.store.state()["total"], 1)
        self.store.session_action({"action": "save"})
        self.assertTrue(original.is_file())
        self.assertEqual(self.store.state()["history_total"], 1)
        second = self.new()
        self.assertNotEqual(first, second)
        self.assertEqual(self.store.state()["total"], 0)
        self.assertEqual(self.store.state()["history_total"], 1)
        self.store.workspace_action({"action": "close", "owner": self.OWNER})
        self.assertFalse((self.root / "sessions" / second).exists())
        self.assertTrue(original.is_file())
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), digest)
        self.assertEqual(self.store.history()["total"], 1)

    def test_only_marked_direct_child_is_removable_and_history_read_only(self):
        self.open()
        saved = self.new()
        record = self.one_frame()
        self.store.session_action({"action": "save"})
        with self.assertRaises(ValueError):
            self.store._remove_temporary_folder(saved)
        self.assertTrue((self.root / "sessions" / saved).exists())
        with self.assertRaises(ValueError):
            self.store._remove_temporary_folder("../" + saved)
        with self.assertRaises(ApiError):
            self.store.annotate({"record_id": record, "label": "FIST"})
        self.assertTrue((self.root / "sessions" / saved).exists())

    def test_second_window_cannot_close_or_learn_owner(self):
        self.open()
        temp = self.new()
        folder = self.root / "sessions" / temp
        second = self.open(self.OTHER)
        self.assertFalse(second["editable"])
        self.store.workspace_action({"action": "close", "owner": self.OTHER})
        self.assertTrue(folder.is_dir())
        public = json.dumps(self.store.state(), ensure_ascii=False)
        self.assertNotIn(self.OWNER, public)

    def test_lease_expiration_freezes_without_deleting_and_rejects_late_frame(self):
        self.open()
        temp = self.new()
        self.store.clip_action({"action": "start", "fps": 2})
        old_epoch = self.store.epoch
        ticket = self.store.begin({"device_id": "test_board", "frame_id": 1,
                                   "capture_ms": 1001, "epoch": old_epoch})
        self.clock.advance(16)
        try:
            with self.store.lock:
                self.store._expire()
            self.assertTrue((self.root / "sessions" / temp).is_dir())
            self.assertNotEqual(self.store.epoch, old_epoch)
            self.assertFalse(self.store.active)
            with self.assertRaises(ApiError):
                self.store.commit(ticket, gray_frame())
        finally:
            self.store.release(ticket)

        recovered = self.store.workspace_action({"action": "keep", "owner": self.OWNER})
        self.assertTrue(recovered["editable"])
        self.assertTrue((self.root / "sessions" / temp).is_dir())

    def test_failed_new_session_does_not_destroy_previous_staging(self):
        self.open()
        previous = self.new()
        folder = self.root / "sessions" / previous
        with patch("managed_capture.atomic_json", side_effect=OSError("synthetic disk full")):
            with self.assertRaises(OSError):
                self.new()
        self.assertTrue(folder.is_dir())
        self.assertEqual(self.store.current["session_id"], previous)

    def test_same_window_reopen_after_lease_expiry_keeps_staging(self):
        self.open()
        previous = self.new()
        folder = self.root / "sessions" / previous
        self.clock.advance(16)
        with self.store.lock:
            self.store._expire()
        reopened = self.store.workspace_action({"action": "open", "owner": self.OWNER})
        self.assertTrue(reopened["editable"])
        self.assertTrue(folder.is_dir())
        self.assertEqual(self.store.current["session_id"], previous)

    def test_restart_load_does_not_delete_marked_staging(self):
        session_id = "c" * 32
        folder = self.root / "sessions" / session_id
        folder.mkdir(parents=True)
        (folder / "frames").mkdir()
        (folder / "clips").mkdir()
        (folder / "session.json").write_text(json.dumps({
            "session_id": session_id, "split": "train", "name": "恢复",
            "sensor_profile": "synthetic", "exposure_profile": "synthetic",
            "lifecycle": self.store.TEMP_MARKER}), encoding="utf-8")
        second = ManagedCaptureStore(self.root, max_frames=30, clock=self.clock)
        try:
            self.assertTrue(folder.is_dir())
            self.assertIn(session_id, second.sessions)
        finally:
            # Avoid a graceful-close deletion before checking the restart itself.
            second._stopped.set()
            second._janitor.join(timeout=2)

    def test_saved_history_survives_normal_restart(self):
        self.open()
        saved = self.new()
        record = self.one_frame()
        self.store.session_action({"action": "save"})
        filename = self.root / self.store.records[record]["file"]
        digest = hashlib.sha256(filename.read_bytes()).hexdigest()
        self.store.close()
        self.store = ManagedCaptureStore(self.root, max_frames=30, clock=self.clock)
        self.assertIn(saved, self.store.sessions)
        self.assertEqual(self.store.history()["total"], 1)
        self.assertEqual(hashlib.sha256(filename.read_bytes()).hexdigest(), digest)

    def test_unretained_export_cannot_leave_dangling_manifest(self):
        self.open()
        self.new()
        self.one_frame()
        with self.assertRaises(ApiError):
            self.store.export()
        self.assertFalse((self.root / "dataset_manifest.json").exists())

    def test_export_at_data_root_is_readable_by_training_loader(self):
        self.open()
        self.new()
        record = self.one_frame()
        self.store.session_action({"action": "save"})
        first = self.store.export()
        first_path = Path(first["manifest"])
        self.assertEqual(first_path.parent, self.root)
        self.assertEqual(first["sample_count"], 1)
        self.assertEqual((first_path.parent / self.store.records[record]["file"]).stat().st_size, FRAME_BYTES)
        second = self.store.export()
        self.assertNotEqual(first["manifest"], second["manifest"])
        self.assertTrue(first_path.is_file())
        spec = importlib.util.spec_from_file_location("gs_managed_capture_dataset", PROJECT / "Models/dataset.py")
        dataset = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dataset)
        report, tensors = dataset.read_dataset(first_path, complete=False)
        self.assertEqual(report["sample_count"], 1)
        self.assertEqual(len(tensors[0]), 9216)
        self.store.workspace_action({"action": "close", "owner": self.OWNER})
        self.assertTrue(first_path.is_file())
        self.assertTrue((first_path.parent / self.store.records[record]["file"]).is_file())

    def test_directory_lock_is_exclusive(self):
        first = DataDirectoryLock(self.root)
        try:
            with self.assertRaises(RuntimeError):
                DataDirectoryLock(self.root)
        finally:
            first.close()
        next_owner = DataDirectoryLock(self.root)
        next_owner.close()

    def test_http_mutation_requires_current_owner(self):
        self.open()
        server = CaptureHTTPServer(("127.0.0.1", 0), self.store, read_timeout=0.6)
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        worker.start()
        def post(owner):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            try:
                payload = json.dumps({"action": "new", "owner": owner, "name": "HTTP 合成",
                                      "split": "train", "sensor_profile": "synthetic",
                                      "exposure_profile": "synthetic"}).encode()
                conn.request("POST", "/api/session", payload, {
                    "Content-Type": "application/json", "X-UI-Token": self.store.ui_token})
                response = conn.getresponse()
                return response.status, response.read()
            finally:
                conn.close()
        try:
            status, _ = post(self.OTHER)
            self.assertEqual(status, 409)
            self.assertIsNone(self.store.current)
            status, content = post(self.OWNER)
            self.assertEqual(status, 200, content)
            self.assertIsNotNone(self.store.current)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_http_live_recognition_schema_and_freshness(self):
        server = CaptureHTTPServer(("127.0.0.1", 0), self.store, read_timeout=0.6)
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        worker.start()
        def live():
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            try:
                conn.request("GET", "/api/live")
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                return json.loads(response.read())
            finally:
                conn.close()
        try:
            row = dict(frame_id=41, class_index=2, class_name="FIST", label="握拳",
                       confidence=0.95, margin=0.7, qualified=True, quality_ok=True,
                       epoch=self.store.epoch, sequence=self.store.preview_sequence,
                       received=self.clock())
            self.store.recognition_result = row
            got = live()["recognition"]
            self.assertEqual({k: got[k] for k in ("frame_id", "class_index", "class_name", "label", "qualified")},
                             dict(frame_id=41, class_index=2, class_name="FIST", label="握拳", qualified=True))
            self.assertNotIn("received", got)
            self.clock.advance(0.301)
            self.assertIsNone(live()["recognition"])
            self.clock.advance(-0.301)
            row["epoch"] += 1
            self.assertIsNone(live()["recognition"])
            row["epoch"] = self.store.epoch
            row["sequence"] += 1
            self.assertIsNone(live()["recognition"])
            row["sequence"] = self.store.preview_sequence
            row.update(class_index=5, class_name="UNKNOWN", label=None,
                       confidence=0.98, margin=0.8, qualified=False)
            self.assertIsNone(live()["recognition"]["label"])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_usb_auto_port_requires_one_stm32_cdc(self):
        target = SimpleNamespace(device="COM7", vid=0x0483, pid=0x5740)
        debugger = SimpleNamespace(device="COM5", vid=0x1FC9, pid=0x5601)
        other = SimpleNamespace(device="COM8", vid=0x1234, pid=0x5678)
        for ports, expected in (([debugger, other], None),
                                ([debugger, target, other], "COM7"),
                                ([target, SimpleNamespace(device="COM9", vid=0x0483, pid=0x5740)], None)):
            opened = []
            receiver = USBReceiver(self.store, "auto", serial_factory=lambda port, **kwargs: opened.append(port),
                                   api_error_type=ApiError)
            def stop_now(*args):
                receiver.stop_event.set()
                return True
            with patch("serial.tools.list_ports.comports", return_value=ports), \
                 patch.object(receiver.stop_event, "wait", side_effect=stop_now):
                if expected is not None:
                    class FakeLink:
                        def __enter__(self):
                            receiver.stop_event.set()
                            return self
                        def __exit__(self, *_):
                            return False
                        def reset_input_buffer(self):
                            pass
                    receiver.factory = lambda port, **kwargs: (opened.append(port), FakeLink())[1]
                receiver.run()
            self.assertEqual(opened, [expected] if expected else [])
            if expected is None:
                self.assertIsNone(receiver.connected_port)


if __name__ == "__main__":
    unittest.main()
