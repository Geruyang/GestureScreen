"""Synthetic USB protocol/recording regressions; never opens physical hardware."""
from pathlib import Path
import http.client
import json
import struct
import sys
import tempfile
import threading
import unittest
import zlib
import runpy
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "HostTools"))
from usb_capture import FrameDecoder, HEADER, FRAME_BYTES, BUFFER_LIMIT, encode_control, USBReceiver
from capture_server import CaptureHTTPServer, CaptureStore


def packet(raw=None, *, epoch=0xffffffff, frame_id=123, **changes):
    raw = b"\xf8\x00" * (FRAME_BYTES // 2) if raw is None else raw
    fields = dict(magic=b"GSFR", version=1, header_size=48, size=FRAME_BYTES,
                  frame_id=frame_id, capture_ms=0xfffffff0, epoch=epoch,
                  width=320, height=240, pixel_format=1, crc=zlib.crc32(raw),
                  uid0=1, uid1=2, uid2=3)
    fields.update(changes)
    return HEADER.pack(*fields.values()) + raw


class USBTests(unittest.TestCase):
    def state_from_http(self, store, receiver=None):
        server = CaptureHTTPServer(("127.0.0.1", 0), store, usb_receiver=receiver)
        thread = threading.Thread(target=server.serve_forever,
                                  kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        try:
            connection.request("GET", "/api/state")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            return json.loads(response.read())
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_usb_saved_duplicate_rejected_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CaptureStore(Path(tmp))
            store.session_action(dict(action="new", name="diagnostics", split="test",
                                      sensor_profile="synthetic", exposure_profile="synthetic"))
            store.clip_action(dict(action="start", fps=2))
            receiver = USBReceiver(store, "MOCK", serial_factory=lambda **kw: self.fail("no port I/O"))
            frame = receiver.feed(packet(epoch=store.epoch))[0]
            self.assertEqual(receiver.accept(frame), 201)
            self.assertEqual(receiver.accept(frame), 200)
            store.clip_action(dict(action="stop"))
            self.assertEqual(receiver.accept(frame), 409)
            state = self.state_from_http(store, receiver)
            usb = state["usb"]
            self.assertEqual((usb["accepted"], usb["saved"], usb["duplicates"], usb["rejected"]),
                             (2, 1, 1, 1))
            self.assertEqual(state["total"], 1)
            self.assertEqual((usb["port"], usb["state"], usb["connected"]), ("MOCK", "idle", False))
            # A returned snapshot is detached from the receiver's published state.
            usb["accepted"] = -1
            self.assertEqual(receiver.snapshot()["accepted"], 2)

    def test_http_usb_parser_and_disconnect_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CaptureStore(Path(tmp))
            receiver = USBReceiver(store, "MOCK", serial_factory=lambda **kw: self.fail("no port I/O"))
            bad_crc = bytearray(packet())
            bad_crc[1000] ^= 1
            self.assertEqual(receiver.feed(b"noise" + packet(version=2)[:48] + bad_crc), [])
            self.assertEqual(len(receiver.feed(packet())), 1)
            receiver.disconnected(OSError("synthetic disconnect"))
            usb = self.state_from_http(store, receiver)["usb"]
            self.assertEqual((usb["bad_headers"], usb["bad_crc"]), (1, 1))
            self.assertGreater(usb["discarded_bytes"], FRAME_BYTES)
            self.assertEqual(usb["discarded_bytes"], receiver.decoder.discarded_bytes)
            self.assertEqual((usb["state"], usb["connected"], usb["last_error"]),
                             ("disconnected", False, "synthetic disconnect"))
            self.assertEqual(usb["accepted"], 0)

    def test_http_state_without_usb_keeps_existing_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CaptureStore(Path(tmp))
            expected = json.loads(json.dumps(store.state()))
            self.assertEqual(self.state_from_http(store), expected)
            self.assertNotIn("usb", expected)

    def test_usb_snapshot_does_not_wait_for_store_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CaptureStore(Path(tmp))
            store.session_action(dict(action="new", name="in-flight", split="test",
                                      sensor_profile="synthetic", exposure_profile="synthetic"))
            store.clip_action(dict(action="start", fps=2))
            receiver = USBReceiver(store, "MOCK", serial_factory=lambda **kw: self.fail("no port I/O"))
            frame = receiver.feed(packet(epoch=store.epoch))[0]
            entered, finish = threading.Event(), threading.Event()
            original_commit = store.commit
            statuses = []

            def delayed_commit(ticket, raw):
                entered.set()
                if not finish.wait(3):
                    raise RuntimeError("test did not release commit")
                return original_commit(ticket, raw)

            with patch.object(store, "commit", side_effect=delayed_commit):
                writer = threading.Thread(target=lambda: statuses.append(receiver.accept(frame)), daemon=True)
                writer.start()
                try:
                    self.assertTrue(entered.wait(1))
                    state = self.state_from_http(store, receiver)
                    self.assertEqual((state["total"], state["usb"]["accepted"]), (0, 0))
                finally:
                    finish.set()
                    writer.join(timeout=2)
            self.assertFalse(writer.is_alive())
            self.assertEqual(statuses, [201])
            self.assertEqual(receiver.snapshot()["saved"], 1)

    def test_firedap_vcom_is_rejected_without_opening_port(self):
        fake = SimpleNamespace(Serial=lambda *a, **kw: self.fail("must not open fireDAP"))
        ports = SimpleNamespace(comports=lambda: [SimpleNamespace(device="COM3", vid=0x1fc9, pid=0x5601)])
        with patch.dict(sys.modules, {"serial": fake, "serial.tools": SimpleNamespace(),
                                      "serial.tools.list_ports": ports}):
            with self.assertRaisesRegex(ValueError, "fireDAP"):
                USBReceiver(None, "com3")
    def test_control_wire_crc_and_uint32(self):
        p = encode_control(b"enabled=1\ninterval_ms=200\nepoch=4294967295\n", 0xffffffff)
        self.assertEqual(struct.unpack("<4sIIIII", p),
                         (b"GSCT", 1, 200, 0xffffffff, 0xffffffff, zlib.crc32(p[:20])))

    def test_fragmented_and_coalesced(self):
        data = packet() + packet(frame_id=124)
        d = FrameDecoder()
        out = []
        for i in range(0, len(data), 997):
            out.extend(d.feed(data[i:i+997]))
        self.assertEqual([f.metadata["frame_id"] for f in out], [123, 124])
        self.assertEqual(out[0].metadata["device_id"], "usb-000000010000000200000003")
        self.assertEqual(len(d.feed(packet()+packet())), 2)

    def test_split_magic_and_junk(self):
        d = FrameDecoder()
        d.feed(b"noiseGS")
        self.assertEqual(len(d.feed(packet()[2:])), 1)
        self.assertLessEqual(len(d.buffer), 3)

    def test_crc_corruption_recovery(self):
        d = FrameDecoder()
        bad = bytearray(packet())
        bad[1000] ^= 1
        self.assertEqual(len(d.feed(bad+packet())), 1)
        self.assertEqual(d.bad_crc, 1)

    def test_truncated_frame_resync(self):
        d = FrameDecoder()
        stream = packet()[:10000] + packet(frame_id=999)
        frames = d.feed(stream)
        self.assertEqual([f.metadata["frame_id"] for f in frames], [999])

    def test_invalid_header_fields(self):
        for changes in (dict(version=2), dict(size=0xffffffff), dict(width=321),
                        dict(header_size=49), dict(pixel_format=2)):
            d = FrameDecoder()
            result = d.feed(packet(**changes)[:48] + packet())
            self.assertEqual(len(result), 1)
            self.assertGreater(d.bad_headers, 0)

    def test_partial_deadline(self):
        d = FrameDecoder()
        d.feed(packet()[:1000], now=1)
        d.expire(now=5)
        self.assertEqual(d.buffer, b"")
        self.assertEqual(len(d.feed(packet(), now=6)), 1)

    def test_bounded_input(self):
        d = FrameDecoder()
        with self.assertRaises(ValueError):
            d.feed(b"x" * (BUFFER_LIMIT+1))
        self.assertEqual(d.buffer, b"")

    def test_record_label_avi_dataset_and_stop_epoch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CaptureStore(Path(tmp))
            store.session_action(dict(action="new", name="USB synthetic", split="train",
                                      sensor_profile="synthetic", exposure_profile="synthetic"))
            store.clip_action(dict(action="start", fps=2))
            epoch = store.epoch
            receiver = USBReceiver(store, "MOCK", serial_factory=lambda **kw: None)
            frame = FrameDecoder().feed(packet(epoch=epoch))[0]
            self.assertEqual(receiver.accept(frame), 201)
            store.clip_action(dict(action="stop"))
            self.assertEqual(receiver.accept(frame), 409)
            clip_id = next(iter(store.pending_clips))
            store.clip_action(dict(action="label", clip_id=clip_id, label="PALM"))
            manifest = store.export()
            import json
            exported = json.loads((Path(tmp)/"dataset_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(exported["samples"]), 1)
            self.assertTrue(store.path(exported["samples"][0]["video_file"]).is_file())
            self.assertTrue(manifest)
            restored = CaptureStore(Path(tmp))
            self.assertEqual(len(restored.records), 1)
            self.assertFalse(restored.active)

    def test_disconnect_stops_active_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CaptureStore(Path(tmp))
            store.session_action(dict(action="new", name="synthetic", split="test",
                                      sensor_profile="synthetic", exposure_profile="synthetic"))
            store.clip_action(dict(action="start", fps=2))
            epoch = store.epoch
            receiver = USBReceiver(store,"MOCK",serial_factory=lambda **kw: None)
            receiver.disconnected(OSError("synthetic disconnect"))
            self.assertFalse(store.active)
            self.assertIsNone(store.active_clip)
            self.assertEqual(len(store.pending_clips), 1)
            self.assertNotEqual(store.epoch, epoch)

    def test_script_entry_point_uses_its_own_api_error(self):
        # Executing the HTTP service as a script creates a different exception
        # class from importing capture_server; pass that exact class to USB.
        module = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                                   "HostTools/capture_server.py"), run_name="entry_point_test")
        with tempfile.TemporaryDirectory() as tmp:
            store = module["CaptureStore"](Path(tmp))
            receiver = USBReceiver(store, "MOCK", serial_factory=lambda **kw: None,
                                   api_error_type=module["ApiError"])
            self.assertEqual(receiver.accept(FrameDecoder().feed(packet())[0]), 409)
            self.assertEqual(receiver.rejected, 1)

    def test_reset_stops_clip_and_requires_new_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = [0]
            store = CaptureStore(Path(tmp), clock=lambda: clock[0])
            session = dict(action="new", name="reset", split="test",
                           sensor_profile="synthetic", exposure_profile="synthetic")
            store.session_action(session)
            store.clip_action(dict(action="start", fps=2))
            r = USBReceiver(store, "MOCK", serial_factory=lambda **kw: None)
            self.assertEqual(r.accept(FrameDecoder().feed(packet(epoch=store.epoch,
                frame_id=100, capture_ms=5000))[0]), 201)
            clock[0] = 1
            self.assertEqual(r.accept(FrameDecoder().feed(packet(epoch=store.epoch,
                frame_id=1, capture_ms=10))[0]), 409)
            self.assertIsNone(store.active_clip)
            self.assertFalse(store.pending)
            # Merely starting another clip in the same session remains blocked.
            store.clip_action(dict(action="discard", clip_id=next(iter(store.pending_clips))))
            store.clip_action(dict(action="start", fps=2))
            self.assertEqual(r.accept(FrameDecoder().feed(packet(epoch=store.epoch,
                frame_id=101, capture_ms=6000))[0]), 409)
            store.clip_action(dict(action="discard", clip_id=next(iter(store.pending_clips))))
            store.session_action(dict(action="stop"))
            store.session_action(session)
            store.clip_action(dict(action="start", fps=2))
            self.assertEqual(r.accept(FrameDecoder().feed(packet(epoch=store.epoch,
                frame_id=2, capture_ms=20))[0]), 201)

    def test_sequence_wrap_is_forward_and_retry_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = [0]
            store = CaptureStore(Path(tmp), clock=lambda: clock[0])
            store.session_action(dict(action="new", name="wrap", split="test",
                                      sensor_profile="synthetic", exposure_profile="synthetic"))
            store.clip_action(dict(action="start", fps=2))
            r = USBReceiver(store, "MOCK", serial_factory=lambda **kw: None)
            self.assertEqual(r.accept(FrameDecoder().feed(packet(epoch=store.epoch,
                frame_id=0xffffffff, capture_ms=0xfffffff0))[0]), 201)
            clock[0] = 1
            frame = FrameDecoder().feed(packet(epoch=store.epoch, frame_id=0, capture_ms=20))[0]
            self.assertEqual(r.accept(frame), 201)
            self.assertEqual(r.accept(frame), 200)
            self.assertEqual(len(store.records), 2)


if __name__ == "__main__":
    unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
