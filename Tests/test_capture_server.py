"""HTTP 级采集验证。仅使用临时目录与合成色块，不充当真实相机/手势验收。"""
from __future__ import annotations

import hashlib
import http.client
import importlib.util
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import zlib

PROJECT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(PROJECT / "HostTools"))
from capture_server import (ApiError, CaptureHTTPServer, CaptureStore, FRAME_BYTES,
                            MAX_AVI_FRAMES, rgb565_to_png, select_diverse_records,
                            write_rgb565_avi)


def frame(seed=0):
    # 灰度附近色块，避免黑/白调试质量阈值；种子保持原图哈希不同。
    result = bytearray(b"\x84\x10" * (320 * 240))
    result[0:2] = bytes((seed & 255, (seed + 37) & 255))
    return bytes(result)


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self):
        self.value += 1


class CaptureHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="gs-capture-test-")
        self.clock = FakeClock()
        self.store = CaptureStore(Path(self.directory.name), max_frames=100, clock=self.clock)
        self.server = CaptureHTTPServer(("127.0.0.1", 0), self.store, read_timeout=0.6)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.address = f"127.0.0.1:{self.port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        # 在途测试会主动排空；其他 HTTP 调用均完整读回。
        self.directory.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            content = response.read()
            return response.status, content, dict(response.getheaders())
        finally:
            connection.close()

    def ui(self, path, data):
        return self.request("POST", path, json.dumps(data).encode(),
                            {"Content-Type": "application/json", "X-UI-Token": self.store.ui_token})

    def action(self, action, **extra):
        status, content, _ = self.ui("/api/session", dict(action=action, **extra))
        self.assertEqual(status, 200, content)
        return json.loads(content)

    def clip(self, action, **extra):
        status, content, _ = self.ui("/api/clip", dict(action=action, **extra))
        self.assertEqual(status, 200, content)
        return json.loads(content)

    def start(self, label="PALM", split="train"):
        self.action("new", name="HTTP 测试会话", split=split,
                    sensor_profile="synthetic_test_only", exposure_profile="synthetic_test_only")
        self.default_label = label
        return self.clip("start", fps=2)

    def finish_clip(self, label=None):
        stopped = self.clip("stop")
        self.wait_released()
        clip_id = stopped["pending_clips"][0]["clip_id"]
        return self.clip("label", clip_id=clip_id, label=label or self.default_label)

    def frame_headers(self, frame_id=1, **overrides):
        result = {"Content-Type": "application/octet-stream", "Content-Length": str(FRAME_BYTES),
                  "X-Device-ID": "board_01", "X-Frame-ID": str(frame_id), "X-Capture-Ms": "1234",
                  "X-Width": "320", "X-Height": "240", "X-Pixel-Format": "RGB565_BE",
                  "X-Control-Epoch": str(self.store.epoch)}
        result.update(overrides)
        return result

    def upload(self, seed=1, frame_id=1, **overrides):
        return self.request("POST", "/api/frames", frame(seed), self.frame_headers(frame_id, **overrides))

    def wait_released(self):
        deadline = time.monotonic() + 2
        while self.store.pending and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.store.pending)

    def test_control_is_simple_ascii_and_defaults_paused(self):
        status, content, headers = self.request("GET", "/api/control")
        self.assertEqual(status, 200)
        self.assertEqual(content, f"enabled=0\ninterval_ms=500\nepoch={self.store.epoch}\n".encode("ascii"))
        self.assertTrue(headers["Content-Type"].startswith("text/plain"))
        self.assertEqual(self.upload()[0], 409)
        self.assertEqual(self.store.records, {})

    def test_save_preview_sha_manifest_and_training_reader(self):
        self.start()
        raw = frame(19)
        status, content, _ = self.upload(19)
        self.assertEqual(status, 201, content)
        sample_id = json.loads(content)["record_id"]
        row = self.store.records[sample_id]
        self.assertEqual(self.store.path(row["file"]).read_bytes(), raw)
        self.assertEqual(row["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual((row["byte_order"], row["width"], row["height"], row["stride_bytes"]), ("msb_first", 320, 240, 640))
        self.assertEqual(self.request("GET", f"/media/{sample_id}.png")[0], 200)
        self.assertEqual(self.request("GET", f"/media/{sample_id}.rgb565")[1], raw)
        labeled = self.finish_clip()
        self.assertEqual(labeled["recent_clips"][0]["label"], "PALM")
        clip = next(iter(self.store.clips.values()))
        avi = self.store.path(clip["video_file"])
        self.assertTrue(avi.name.startswith("PALM_张开手掌_"))
        payload = avi.read_bytes()
        self.assertEqual(payload[:4], b"RIFF")
        self.assertEqual(struct.unpack_from("<I", payload, 4)[0], len(payload) - 8)
        self.assertEqual(payload[8:12], b"AVI ")
        self.assertIn(b"movi", payload[:512])
        self.assertIn(b"idx1", payload[-128:])
        avih = payload.index(b"avih")
        self.assertEqual(struct.unpack_from("<I", payload, avih + 8 + 16)[0], 1)
        movi = payload.index(b"movi") + 4
        self.assertEqual(payload[movi:movi + 4], b"00db")
        self.assertEqual(struct.unpack_from("<I", payload, movi + 4)[0], 320 * 240 * 3)
        self.assertEqual(self.request("GET", f"/video/{clip['clip_id']}")[1], payload)
        status, content, _ = self.ui("/api/export", {})
        self.assertEqual(status, 200, content)
        manifest_path = Path(json.loads(content)["manifest"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["samples"][0]["file"], row["file"])
        self.assertEqual(manifest["samples"][0]["session"], row["session_id"])
        self.assertEqual(manifest["samples"][0]["label"], "PALM")
        self.assertEqual(manifest["clips"][0]["video_file"], clip["video_file"])
        # 与模型团队的实际公开读取接口对照，不复制其验证实现。
        spec = importlib.util.spec_from_file_location("gs_capture_test_dataset", PROJECT / "Models" / "dataset.py")
        dataset = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dataset)
        report, tensors = dataset.read_dataset(manifest_path, complete=False)
        self.assertEqual(report["sample_count"], 1)
        self.assertEqual(len(tensors[0]), 9216)
        self.assertEqual(self.request("GET", "/api/export")[0], 200)

    def test_rgb565_big_endian_png_color_and_dimensions(self):
        raw = b"\xf8\x00\x07\xe0\x00\x1f" + b"\x00\x00" * (320 * 240 - 3)
        png = rgb565_to_png(raw)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        position, compressed = 8, b""
        while position < len(png):
            size = struct.unpack(">I", png[position:position + 4])[0]
            kind, payload = png[position + 4:position + 8], png[position + 8:position + 8 + size]
            crc = struct.unpack(">I", png[position + 8 + size:position + 12 + size])[0]
            self.assertEqual(crc, zlib.crc32(kind + payload) & 0xFFFFFFFF)
            if kind == b"IHDR":
                self.assertEqual(struct.unpack(">II", payload[:8]), (320, 240))
            if kind == b"IDAT":
                compressed += payload
            position += 12 + size
        pixels = zlib.decompress(compressed)
        self.assertEqual(pixels[:10], b"\x00\xff\x00\x00\x00\xff\x00\x00\x00\xff")
        self.assertEqual(len(pixels), 240 * 961)

    def test_bounds_path_traversal_format_and_integer_headers(self):
        self.start()
        cases = [({"X-Width": "319"}, 415), ({"X-Pixel-Format": "RGB565_LE"}, 415),
                 ({"Content-Length": "153601"}, 413), ({"Content-Length": "3"}, 400),
                 ({"X-Device-ID": "../../overwrite"}, 400), ({"X-Frame-ID": "4294967296"}, 400),
                 ({"X-Capture-Ms": "-1"}, 400), ({"Content-Type": "text/plain"}, 415),
                 ({"Transfer-Encoding": "chunked"}, 400)]
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                status, content, _ = self.request("POST", "/api/frames", b"", self.frame_headers(**overrides))
                self.assertEqual(status, expected, content)
        for path in ("/../../Models/model_contract.json", "/media/%2e%2e%2fsecret.png", "/api/frames?offset=-1", "/api/frames?limit=999"):
            self.assertIn(self.request("GET", path)[0], (400, 404))
        self.assertEqual(len(self.store.records), 0)

    def test_duplicate_content_and_identity_are_not_saved_twice(self):
        self.start()
        self.assertEqual(self.upload(1)[0], 201)
        self.wait_released()
        status, content, _ = self.upload(1)
        self.assertEqual(status, 200, content)
        self.assertTrue(json.loads(content)["duplicate"])
        self.assertEqual(self.upload(2)[0], 409)
        self.clock.advance()
        status, content, _ = self.upload(1, frame_id=2)
        self.assertEqual(status, 201, content)
        self.assertEqual(len(self.store.records), 2)
        rows = list(self.store.records.values())
        self.assertEqual(rows[1]["training_duplicate_of"], rows[0]["record_id"])
        self.finish_clip()
        self.assertFalse(rows[0]["excluded"])
        self.assertTrue(rows[1]["excluded"])

    def test_cross_session_duplicate_restart_is_independent_of_uuid_order(self):
        for session_id in ("f" * 32, "0" * 32):
            with patch("capture_server.uuid.uuid4", return_value=SimpleNamespace(hex=session_id)):
                self.action("new", name="反向会话顺序", split="train",
                            sensor_profile="synthetic_test_only", exposure_profile="synthetic_test_only")
            self.clip("start", fps=2)
            self.clock.advance()
            self.assertEqual(self.upload(41)[0], 201)
            self.finish_clip("PALM")
            self.action("stop")
        restored = CaptureStore(Path(self.directory.name), max_frames=100)
        self.assertEqual(len(restored.records), 2)
        self.assertEqual(restored.state()["included"], 1)
        duplicate = next(row for row in restored.records.values() if row.get("training_duplicate_of"))
        self.assertEqual(restored.records[duplicate["training_duplicate_of"]]["sha256"], duplicate["sha256"])

    def test_long_clip_journal_remains_bounded_and_recovers_membership(self):
        self.store.max_frames = 600
        self.start()
        raw = frame(42)
        preview = rgb565_to_png(raw)
        # Test journal scale, not repeated color conversion; files remain genuine RGB565/PNG.
        with patch("capture_server.rgb565_to_png", return_value=preview):
            for index in range(500):
                self.clock.advance()
                ticket = self.store.begin(dict(device_id="board_01", frame_id=index,
                                                capture_ms=index * 500, epoch=self.store.epoch))
                try:
                    self.assertEqual(self.store.commit(ticket, raw)[0], 201)
                finally:
                    self.store.release(ticket)
        stopped = self.clip("stop")
        clip_id = stopped["pending_clips"][0]["clip_id"]
        self.clip("discard", clip_id=clip_id)
        journal = self.store.path(f"sessions/{self.store.current['session_id']}/frames.jsonl")
        self.assertLessEqual(max(map(len, journal.read_bytes().splitlines(keepends=True))), 16384)
        restored = CaptureStore(Path(self.directory.name), max_frames=600)
        self.assertEqual(restored.clips[clip_id]["record_ids"], self.store.clips[clip_id]["record_ids"])
        self.assertEqual(restored.pending_clips, {})

    def test_avi_capacity_is_checked_before_disk_io_and_capture_remains_labelable(self):
        target = Path(self.directory.name) / "oversize.avi"
        with self.assertRaises(ApiError) as oversize:
            write_rgb565_avi(target, [Path("not-read.rgb565")] * (MAX_AVI_FRAMES + 1), 200)
        self.assertEqual(oversize.exception.status, 413)
        self.assertFalse(target.exists())
        with patch("capture_server.MAX_AVI_FRAMES", 2):
            self.start()
            self.assertEqual(self.upload(1, frame_id=1)[0], 201)
            self.clock.advance()
            self.assertEqual(self.upload(2, frame_id=2)[0], 201)
            self.assertIn(b"enabled=0", self.store.control())
            self.clock.advance()
            self.assertEqual(self.upload(3, frame_id=3)[0], 409)
            self.finish_clip()
        self.assertEqual(next(iter(self.store.clips.values()))["record_ids"], self.store.order)

    def test_pagination_slice_preserves_newest_first_at_boundaries(self):
        self.store.order = [f"{index:032x}" for index in range(100)]
        self.store.records = {key: dict(record_id=key) for key in self.store.order}
        for offset, limit in ((0, 30), (30, 30), (95, 10), (100, 30), (999, 30)):
            expected = list(reversed(self.store.order))[offset:offset + limit]
            self.assertEqual([row["record_id"] for row in self.store.page(offset, limit)["samples"]], expected)

    def test_manual_annotation_cannot_reinclude_a_training_duplicate(self):
        self.start()
        self.assertEqual(self.upload(17, frame_id=1)[0], 201)
        self.clock.advance()
        self.assertEqual(self.upload(17, frame_id=2)[0], 201)
        self.finish_clip()
        duplicate = self.store.records[self.store.order[1]]
        status, content, _ = self.ui("/api/annotate", dict(record_id=duplicate["record_id"],
                                                         label="FIST", excluded=False))
        self.assertEqual(status, 409, content)
        self.assertTrue(duplicate["excluded"])
        self.assertEqual(duplicate["label"], "PALM")
        self.assertEqual(self.ui("/api/annotate", dict(record_id=duplicate["record_id"],
                                                      label="FIST", excluded=True))[0], 200)
        self.assertEqual(self.store.export()["sample_count"], 1)
        restored = CaptureStore(Path(self.directory.name), max_frames=100)
        self.assertEqual(restored.export()["sample_count"], 1)

    def test_legacy_clip_and_duplicate_annotation_recover_safely(self):
        self.start()
        self.assertEqual(self.upload(18, frame_id=1)[0], 201)
        self.clock.advance()
        self.assertEqual(self.upload(18, frame_id=2)[0], 201)
        self.finish_clip()
        session_id = self.store.current["session_id"]
        clip = next(iter(self.store.clips.values()))
        journal = self.store.path(f"sessions/{session_id}/frames.jsonl")
        # Historical legacy list form and an old unsafe annotation, confined to temp fixture.
        events = [json.loads(line) for line in journal.read_bytes().splitlines()]
        events[-1] = clip
        events.append(dict(type="annotation", record_id=self.store.order[1], label="FIST",
                           excluded=False, at="2026-09-16T00:00:00+00:00"))
        journal.write_bytes(b"".join((json.dumps(event).encode() + b"\n") for event in events))
        restored = CaptureStore(Path(self.directory.name), max_frames=100)
        self.assertEqual(restored.clips[clip["clip_id"]]["record_ids"], self.store.order)
        self.assertTrue(restored.records[self.store.order[1]]["excluded"])
        self.assertEqual(restored.export()["sample_count"], 1)

    def test_invalid_duplicate_reference_still_rejected_after_deferred_validation(self):
        self.start()
        self.assertEqual(self.upload(19)[0], 201)
        self.wait_released()
        row = dict(self.store.records[self.store.order[0]], training_duplicate_of="0" * 32)
        journal = self.store.path(f"sessions/{row['session']}/frames.jsonl")
        journal.write_bytes((json.dumps(dict(type="frame", sample=row)).encode() + b"\n"))
        with self.assertRaisesRegex(ValueError, "invalid duplicate reference"):
            CaptureStore(Path(self.directory.name), max_frames=100)

    def test_paused_upload_returns_http_error_reliably(self):
        for index in range(30):
            status, content, _ = self.upload(index, frame_id=index)
            self.assertEqual(status, 409, content)
        self.assertFalse(self.store.pending)

    def test_sampling_rate_and_maximum_frames(self):
        self.start()
        self.assertEqual(self.upload(1)[0], 201)
        self.wait_released()
        with self.assertRaises(ApiError) as limited:
            self.store.begin(dict(device_id="board_01", frame_id=2, capture_ms=1234, epoch=self.store.epoch))
        self.assertEqual(limited.exception.status, 429)
        self.clock.advance()
        self.assertEqual(self.upload(2, frame_id=2)[0], 201)
        self.finish_clip()
        self.assertEqual(self.ui("/api/clip", {"action": "start", "fps": 99})[0], 400)
        self.store.max_frames = 2
        self.assertIn(b"enabled=0\n", self.request("GET", "/api/control")[1])
        self.assertEqual(self.ui("/api/clip", {"action": "start", "fps": 2})[0], 409)

    def test_timed_clip_keeps_full_video_and_exports_only_diverse_subset(self):
        self.action("new", name="一分钟差异抽帧", split="train",
                    sensor_profile="synthetic_test_only", exposure_profile="synthetic_test_only")
        started = self.clip("start", fps=5, label="FIST", duration_seconds=60, selection_count=5)
        self.assertEqual(started["active_clip"]["label"], "FIST")
        self.assertEqual(started["active_clip"]["duration_seconds"], 60)
        self.assertTrue(started["active_clip"]["auto_stop_at"])
        for index in range(10):
            self.clock.advance()
            self.assertEqual(self.upload(index + 30, frame_id=index + 1)[0], 201)
        clip_id = started["active_clip"]["clip_id"]
        self.store._finish_timed_clip(clip_id)  # deterministic simulation of the 60-second deadline
        labeled = self.store.state()
        self.assertFalse(labeled["active"])
        self.assertEqual(labeled["pending_clips"], [])
        clip = self.store.clips[clip_id]
        self.assertEqual(clip["label"], "FIST")
        self.assertEqual(len(clip["record_ids"]), 10)
        self.assertEqual(len(clip["selected_record_ids"]), 5)
        self.assertEqual(labeled["recent_clips"][0]["selected_count"], 5)
        self.assertEqual(sum(not row["excluded"] for row in self.store.records.values()), 5)
        manifest = json.loads(Path(self.store.export()["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["samples"]), 5)
        self.assertEqual(len(manifest["clips"][0]["record_ids"]), 10)
        self.assertEqual(len(manifest["clips"][0]["selected_record_ids"]), 5)
        restored = CaptureStore(Path(self.directory.name), max_frames=100)
        self.assertEqual(restored.state()["included"], 5)

    def test_diverse_selection_keeps_temporal_anchors_and_visual_outlier(self):
        records, record_ids = {}, []
        for index in range(6):
            key = f"{index:032x}"
            relative = f"candidate-{index}.rgb565"
            payload = (b"\xff\xff" if index == 2 else b"\x00\x00") * (320 * 240)
            (Path(self.directory.name) / relative).write_bytes(payload)
            records[key] = {"file": relative}
            record_ids.append(key)
        selected = select_diverse_records(record_ids, records,
                                          lambda relative: Path(self.directory.name) / relative, 3)
        self.assertEqual(selected, [record_ids[0], record_ids[2], record_ids[-1]])

    def test_clip_stop_requires_post_label_and_rejects_stale_epoch(self):
        self.start()
        old_epoch = self.store.epoch
        self.assertEqual(self.upload()[0], 201)
        changed = self.clip("stop")
        self.assertFalse(changed["active"])
        self.assertEqual(changed["included"], 0)
        self.assertEqual(self.ui("/api/export", {})[0], 409)
        self.assertEqual(self.upload(**{"X-Control-Epoch": str(old_epoch)})[0], 409)
        clip_id = changed["pending_clips"][0]["clip_id"]
        self.clip("label", clip_id=clip_id, label="EMPTY")
        self.assertEqual(next(iter(self.store.records.values()))["label"], "EMPTY")
        self.assertEqual(next(iter(self.store.records.values()))["label_provenance"], "manual_post_clip_label")

    def test_empty_clip_must_be_discarded_and_does_not_create_video(self):
        self.start()
        stopped = self.clip("stop")
        clip_id = stopped["pending_clips"][0]["clip_id"]
        self.assertEqual(self.ui("/api/clip", {"action": "label", "clip_id": clip_id, "label": "PALM"})[0], 409)
        discarded = self.clip("discard", clip_id=clip_id)
        self.assertEqual(discarded["pending_clips"], [])
        self.assertEqual(list(Path(self.directory.name).rglob("*.avi")), [])

    def test_unlabeled_clip_recovers_after_restart_and_can_be_labeled(self):
        self.start(label="V_SIGN", split="validation")
        self.assertEqual(self.upload(44)[0], 201)
        stopped = self.clip("stop")
        clip_id = stopped["pending_clips"][0]["clip_id"]
        restored = CaptureStore(Path(self.directory.name), max_frames=100)
        self.assertFalse(restored.active)
        self.assertIsNone(restored.current)
        self.assertEqual(restored.state()["pending_clips"][0]["clip_id"], clip_id)
        restored.clip_action({"action": "label", "clip_id": clip_id, "label": "V_SIGN"})
        exported = restored.export()
        manifest = json.loads(Path(exported["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["samples"][0]["label"], "V_SIGN")
        self.assertTrue(restored.path(manifest["clips"][0]["video_file"]).is_file())

    def test_same_gesture_clips_use_monotonic_names(self):
        self.start(label="FIST")
        self.assertEqual(self.upload(20)[0], 201)
        self.finish_clip("FIST")
        self.clock.advance()
        self.clip("start", fps=2)
        self.assertEqual(self.upload(21, frame_id=2)[0], 201)
        self.finish_clip("FIST")
        names = sorted(path.name for path in Path(self.directory.name).rglob("*.avi"))
        self.assertEqual(names, ["FIST_握拳_0001.avi", "FIST_握拳_0002.avi"])

    def test_in_flight_frame_crossing_clip_stop_is_discarded(self):
        self.start()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.putrequest("POST", "/api/frames")
        for key, value in self.frame_headers().items():
            connection.putheader(key, value)
        connection.endheaders()
        connection.send(frame(1)[:100])
        deadline = time.monotonic() + 1
        while not self.store.pending and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(self.store.pending)
        self.clip("stop")
        connection.send(frame(1)[100:])
        response = connection.getresponse()
        self.assertEqual(response.status, 409, response.read())
        connection.close()
        self.wait_released()
        self.assertEqual(len(self.store.records), 0)
        self.assertEqual(list(Path(self.directory.name).rglob("*.rgb565")), [])

    def test_truncated_disconnect_and_timeout_release_device(self):
        self.start()
        raw_headers = ("POST /api/frames HTTP/1.0\r\n" + "\r\n".join(f"{k}: {v}" for k, v in self.frame_headers().items()) + "\r\n\r\n").encode()
        with socket.create_connection(("127.0.0.1", self.port), timeout=2) as connection:
            connection.sendall(raw_headers + b"short")
            connection.shutdown(socket.SHUT_WR)
            self.assertIn(b" 400 ", connection.recv(4096))
        self.wait_released()
        with socket.create_connection(("127.0.0.1", self.port), timeout=2) as connection:
            connection.sendall(raw_headers + b"short")
            self.assertIn(b" 408 ", connection.recv(4096))
        self.wait_released()
        self.assertEqual(len(self.store.records), 0)
        self.assertEqual(self.upload()[0], 201)

    def test_duplicate_length_headers_rejected(self):
        self.start()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        connection.putrequest("POST", "/api/frames")
        for key, value in self.frame_headers().items():
            connection.putheader(key, value)
        connection.putheader("Content-Length", str(FRAME_BYTES))
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 400, response.read())
        connection.close()
        self.assertEqual(len(self.store.records), 0)

    def test_ui_origin_token_and_assets(self):
        status, page, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("手势采集工作室".encode(), page)
        self.assertNotIn(b'id="selection-count"', page)
        self.assertIn("导出采集清单".encode(), page)
        self.assertEqual(self.request("GET", "/app.js")[0], 200)
        self.assertEqual(self.request("GET", "/style.css")[0], 200)
        self.assertEqual(self.request("GET", "/capture.css")[0], 200)
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "malicious.example"})[0], 403)
        headers = {"Content-Type": "application/json", "X-UI-Token": self.store.ui_token, "Origin": "http://other.example"}
        self.assertEqual(self.request("POST", "/api/export", b"{}", headers)[0], 403)
        self.assertEqual(self.request("POST", "/api/export", b"{}", {"Content-Type": "application/json"})[0], 403)
        self.assertEqual(self.request("POST", "/api/export", b"{" + b" " * 4096,
                                      {"Content-Type": "application/json", "X-UI-Token": self.store.ui_token})[0], 413)

    def test_annotations_exclusion_persistence_and_session_split(self):
        self.start(label="FIST", split="test")
        status, content, _ = self.upload(10)
        self.assertEqual(status, 201)
        record_id = json.loads(content)["record_id"]
        self.assertEqual(self.ui("/api/annotate", dict(record_id=record_id, label="OTHER", excluded=True))[0], 409)
        self.finish_clip("FIST")
        self.assertEqual(self.ui("/api/annotate", dict(record_id=record_id, label="OTHER", excluded=True))[0], 200)
        self.assertEqual(self.ui("/api/export", {})[0], 200)
        exported = json.loads(self.store.path("dataset_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(exported["samples"], [])
        self.assertTrue(self.store.path(self.store.records[record_id]["file"]).is_file())
        self.action("stop")
        self.start(label="PALM", split="train")
        self.clock.advance()
        self.assertEqual(self.upload(11, frame_id=1)[0], 201)
        self.finish_clip("PALM")
        restored = CaptureStore(Path(self.directory.name), max_frames=100)
        self.assertFalse(restored.active)
        self.assertIsNone(restored.current)
        self.assertEqual(len(restored.records), 2)
        self.assertEqual(len(restored.clips), 2)
        self.assertTrue(restored.records[record_id]["excluded"])
        self.assertEqual(restored.records[record_id]["label"], "OTHER")
        self.assertEqual(restored.records[record_id]["split"], "test")
        self.assertEqual(len({row["session"] for row in restored.records.values()}), 2)
        page = json.loads(self.request("GET", "/api/frames?offset=1&limit=1")[1])
        self.assertEqual(page["samples"][0]["record_id"], record_id)

    def test_same_device_concurrent_upload_is_rejected(self):
        self.start()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        connection.putrequest("POST", "/api/frames")
        for key, value in self.frame_headers().items():
            connection.putheader(key, value)
        connection.endheaders()
        connection.send(b"head")
        deadline = time.monotonic() + 1
        while not self.store.pending and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(self.upload(2, frame_id=2)[0], 429)
        connection.close()
        self.wait_released()
        self.assertEqual(len(self.store.records), 0)

    def test_storage_failure_pauses_without_exporting_partial_frame(self):
        self.start()
        with patch.object(self.store, "_journal", side_effect=OSError("simulated full disk")):
            status, content, _ = self.upload()
        self.assertEqual(status, 503, content)
        self.wait_released()
        self.assertFalse(self.store.active)
        self.assertEqual(len(self.store.records), 0)
        self.assertEqual(list(Path(self.directory.name).rglob("*.rgb565")), [])
        self.assertEqual(list(Path(self.directory.name).rglob("*.png")), [])

    def test_repeated_busy_rejection_preserves_http_status(self):
        self.start()
        ticket = self.store.begin(dict(device_id="test-board", frame_id=1,
                                       capture_ms=2, epoch=self.store.epoch))
        try:
            # A full body may already be in the Windows TCP receive queue when
            # rejected. Closing with unread data must not reset the response.
            for frame_id in range(2, 32):
                self.assertEqual(self.upload(frame_id=frame_id, **{"X-Device-ID": "test-board"})[0], 429)
        finally:
            self.store.release(ticket)
        self.assertFalse(self.store.pending)
        self.assertEqual(len(self.store.records), 0)


if __name__ == "__main__":
    unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
