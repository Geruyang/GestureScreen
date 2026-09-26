"""模型工具软件测试。所有合成图仅用于算法/门禁验证，不是模型准确率数据。"""
from __future__ import annotations

import ctypes as ct
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dataset import LABELS, PREPROCESS_VERSION, flip_label, preprocess, read_dataset
from model_package import contract_errors


class Frame(ct.Structure):
    _fields_ = [("data", ct.POINTER(ct.c_uint8)), ("data_size", ct.c_size_t),
                ("width", ct.c_uint32), ("height", ct.c_uint32),
                ("stride_bytes", ct.c_size_t), ("byte_order", ct.c_int)]


class Stats(ct.Structure):
    _fields_ = [("pixel_count", ct.c_uint32), ("dark_pixels", ct.c_uint32), ("bright_pixels", ct.c_uint32),
                ("dark_permille", ct.c_uint16), ("bright_permille", ct.c_uint16),
                ("mean_y", ct.c_uint8), ("min_y", ct.c_uint8), ("max_y", ct.c_uint8), ("acceptable", ct.c_uint8)]


class DatasetTests(unittest.TestCase):
    def test_colors_and_quality(self):
        for pixel, expected in ((0, 0), (65535, 255), (0xF800, 77), (0x07E0, 149), (0x001F, 29)):
            for order, byteorder in (("msb_first", "big"), ("lsb_first", "little")):
                data = pixel.to_bytes(2, byteorder) * (320 * 240)
                tensor, stats = preprocess(data, order)
                self.assertEqual(tensor, bytes([(expected - 128) & 255]) * 9216)
                self.assertEqual(stats["mean_y"], expected)
                self.assertEqual(stats["acceptable"], int(pixel not in (0, 65535)))

    def test_bad_frame_arguments(self):
        data = bytes(320 * 240 * 2)
        for args in ((data[:-1], "msb_first", 640), (data, "unknown", 640), (data, "msb_first", 639),
                     (data, "msb_first", True), (data, "msb_first", 2**64)):
            with self.assertRaises(ValueError):
                preprocess(*args)

    def test_directional_augmentation(self):
        self.assertEqual([flip_label(i) for i in range(7)], [1, 0, 2, 3, 4, 5, 6])

    def test_manifest_rejections(self):
        with tempfile.TemporaryDirectory(prefix="gs-model-dataset-test-") as directory:
            root = Path(directory)
            file = root / "a.rgb565"
            data = b"\x7b\xef" * (320 * 240)
            file.write_bytes(data)
            row = dict(file=file.name, sha256=hashlib.sha256(data).hexdigest(), session="s1", label="FIST",
                       split="train", byte_order="msb_first", sensor_profile="synthetic_test_fixture",
                       exposure_profile="synthetic_test_fixture", width=320, height=240, stride_bytes=640, capture_ms=1)
            manifest = dict(schema_version=1, preprocessing=PREPROCESS_VERSION, samples=[row])
            path = root / "manifest.json"

            def write():
                path.write_text(json.dumps(manifest), encoding="utf-8")

            write()
            report, tensors = read_dataset(path, complete=False)
            self.assertEqual(len(tensors), 1)
            self.assertEqual(report["counts"]["train"]["FIST"], 1)
            with self.assertRaisesRegex(ValueError, "seven classes"):
                read_dataset(path)
            row["sha256"] = "bad"
            write()
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                read_dataset(path, complete=False)
            row["sha256"] = hashlib.sha256(data).hexdigest()
            manifest["samples"].append({**row, "split": "test"})
            write()
            with self.assertRaisesRegex(ValueError, "session leakage"):
                read_dataset(path, complete=False)
            manifest["samples"][-1] = {**row, "session": "s2"}
            write()
            with self.assertRaisesRegex(ValueError, "duplicate source"):
                read_dataset(path, complete=False)
            file2 = root / "b.rgb565"
            file2.write_bytes(data)
            manifest["samples"][-1]["file"] = file2.name
            write()
            with self.assertRaisesRegex(ValueError, "duplicate raw frame"):
                read_dataset(path, complete=False)
            changed = b"\x01\x01" + data[2:]  # ROI外字节变化不能掩盖同一训练张量。
            file2.write_bytes(changed)
            manifest["samples"][-1].update(split="test", sha256=hashlib.sha256(changed).hexdigest())
            write()
            with self.assertRaisesRegex(ValueError, "tensor leakage"):
                read_dataset(path, complete=False)

    def test_empty_template_cannot_train(self):
        with self.assertRaisesRegex(ValueError, "no real samples"):
            read_dataset(Path(__file__).resolve().parents[1] / "dataset_manifest.example.json")

    @unittest.skipUnless(os.environ.get("GS_PREPROCESS_DLL"), "set GS_PREPROCESS_DLL for actual C/Python comparison")
    def test_fifty_frames_against_actual_c(self):
        library = ct.CDLL(os.environ["GS_PREPROCESS_DLL"])
        function = library.gs_preprocess_rgb565
        function.argtypes = [ct.POINTER(Frame), ct.POINTER(ct.c_int8), ct.c_size_t, ct.c_void_p, ct.POINTER(Stats)]
        function.restype = ct.c_int
        rng = random.Random(20260915)
        for index in range(50):
            stride = 640 + (index % 3) * 8
            data = rng.randbytes(stride * 239 + 640)
            byteorder = index % 2
            tensor, measured = preprocess(data, "lsb_first" if byteorder else "msb_first", stride)
            source = (ct.c_uint8 * len(data)).from_buffer_copy(data)
            frame = Frame(source, len(data), 320, 240, stride, byteorder)
            output, stats = (ct.c_int8 * 9216)(), Stats()
            status = function(ct.byref(frame), output, 9216, None, ct.byref(stats))
            self.assertEqual(status, 0 if measured["acceptable"] else 4)
            self.assertEqual(bytes(output), tensor, f"tensor mismatch, synthetic case {index}")
            self.assertEqual({name: getattr(stats, name) for name, _ in Stats._fields_}, measured)


class ContractTests(unittest.TestCase):
    def test_real_source_five_class_audit_rejected(self):
        audit = Path(__file__).resolve().parents[1] / "validation/source_five_class_audit.json"
        if not audit.exists():
            self.skipTest("run actual source audit first")
        report = json.loads(audit.read_text(encoding="utf-8"))
        self.assertTrue(any("[1,7]" in text for text in contract_errors(report)))
        report["outputs"][0]["shape"] = [1, 7]  # metadata checker fixture, not a model file
        self.assertEqual(contract_errors(report), [])
        report["inputs"][0]["scales"] = [.5]
        self.assertTrue(any("quantization" in text for text in contract_errors(report)))
        report["inputs"][0]["scales"] = [1.0]
        report["outputs"][0]["scales"] = [float("nan")]
        self.assertTrue(any("finite" in text for text in contract_errors(report)))


if __name__ == "__main__":
    unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
