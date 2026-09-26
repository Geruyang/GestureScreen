"""Regression checks for the explicitly authorized float-only experimental path."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
from argparse import Namespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dataset import LABELS, PREPROCESS_VERSION, flip_label
from random_dataset import read_random_dataset
from train_random_split import (Progress, arrays, atomic_json, classification_metrics,
                                evaluate_final, moderate_class_weights,
                                normalize_training_history, train_float)


class RandomTrainingTests(unittest.TestCase):
    def make_dataset(self,root):
        rows=[]
        for n in range(21):
            raw=bytes([n])*32
            name=f"{n}.rgb565"
            (root/name).write_bytes(raw)
            rows.append(dict(file=name,sha256=hashlib.sha256(raw).hexdigest(),session="REAL_SESSION_SHARED",
                             label=LABELS[n%7],split=("train","validation","test")[n//7],
                             byte_order="msb_first",sensor_profile="test",exposure_profile="test",
                             width=320,height=240,capture_ms=n))
        manifest=dict(schema_version=1,preprocessing=PREPROCESS_VERSION,
                      split_method="image-wise seeded uniform random shuffle",samples=rows)
        path=root/"manifest.json"
        path.write_text(json.dumps(manifest),encoding="utf-8")
        return path,manifest

    def preprocess(self,raw,*args):
        return raw[:1]*9216,dict(acceptable=1)

    def test_cross_session_is_explicit_and_original_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path,manifest=self.make_dataset(Path(temp))
            with patch("random_dataset.preprocess",self.preprocess):
                report,tensors=read_random_dataset(path)
            self.assertFalse(report["session_isolated"])
            self.assertEqual(report["sessions_crossing_splits"],1)
            self.assertEqual({r["session"] for r in report["samples"]},{"REAL_SESSION_SHARED"})
            self.assertEqual(len(tensors),21)

    def test_random_declaration_required(self):
        with tempfile.TemporaryDirectory() as temp:
            path,manifest=self.make_dataset(Path(temp))
            del manifest["split_method"]
            path.write_text(json.dumps(manifest),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"declaration"):
                read_random_dataset(path)

    def test_sha_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            path,manifest=self.make_dataset(Path(temp))
            manifest["samples"][0]["sha256"]="0"*64
            path.write_text(json.dumps(manifest),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"SHA-256"):
                read_random_dataset(path)

    def test_tensor_duplicate_rejected_even_with_unique_raw(self):
        with tempfile.TemporaryDirectory() as temp:
            path,_=self.make_dataset(Path(temp))
            with patch("random_dataset.preprocess",return_value=(b"x"*9216,dict(acceptable=1))):
                with self.assertRaisesRegex(ValueError,"duplicate preprocessed"):
                    read_random_dataset(path)

    def test_raw_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            path,manifest=self.make_dataset(root)
            (root/"1.rgb565").write_bytes((root/"0.rgb565").read_bytes())
            manifest["samples"][1]["sha256"]=manifest["samples"][0]["sha256"]
            path.write_text(json.dumps(manifest),encoding="utf-8")
            with patch("random_dataset.preprocess",self.preprocess):
                with self.assertRaisesRegex(ValueError,"duplicate raw"):
                    read_random_dataset(path)

    def test_gray_numeric_domain_and_flip(self):
        import numpy as np
        report={"samples":[{"label":"POINT_LEFT"}]}
        tensor=(bytes([128,255,0,127])*2304)
        x,y=arrays(report,[tensor])
        self.assertEqual(x.dtype,np.float32)
        self.assertEqual(x.ravel()[:4].tolist(),[0.,127.,128.,255.])
        self.assertEqual([flip_label(i) for i in range(7)],[1,0,2,3,4,5,6])

    def test_class_weights_normalize_by_training_samples(self):
        import numpy as np
        y=np.array([0,0,0,1,2,3,4,5,6])
        w=moderate_class_weights(y)
        self.assertAlmostEqual(float(w[y].mean()),1.,places=6)
        self.assertGreater(w[1],w[0])

    def test_metrics_and_progress_atomic(self):
        m=classification_metrics(list(range(7)),list(range(7)))
        self.assertEqual(m["macro_f1"],1.)
        self.assertEqual(m["errors"],0)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            p=Progress(root,{"experiment":"test"})
            p.update(stage="head",epoch=1)
            saved=json.loads((root/"progress.json").read_text())
            self.assertEqual(saved["epoch"],1)
            self.assertIsNone(saved["val_accuracy"])
            self.assertFalse((root/"progress.json.tmp").exists())

    def test_numpy_float32_learning_rate_history_writes_strict_json(self):
        import numpy as np
        history=normalize_training_history({"loss":[np.float32(1.25)],
                                            "lr":[np.float32(1e-5),np.float32(1e-4)]})
        self.assertTrue(all(type(value) is float for values in history.values() for value in values))
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"training_report.json"
            atomic_json(path,{"history":{"full":history}})
            saved=json.loads(path.read_text(encoding="utf-8"))
        self.assertAlmostEqual(saved["history"]["full"]["lr"][0],1e-5)

    def test_history_normalization_does_not_hide_unsupported_values(self):
        with self.assertRaises((TypeError,ValueError)):
            normalize_training_history({"lr":[{"unexpected":"object"}]})

    def test_float_only_no_converter_export_install(self):
        source=(Path(__file__).resolve().parents[1]/"train_random_split.py").read_text(encoding="utf-8")
        for forbidden in ("TFLiteConverter","converter.convert", "from export_c", "from install_model", ".tflite"):
            self.assertNotIn(forbidden,source)
        self.assertIn("test_evaluated=False",source)
        self.assertIn("--evaluate-final",source)
        self.assertIn('metric_scope="selected_candidate_validation"',source)

    def test_smoke_cannot_unlock_final_test(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/"training_report.json").write_text(json.dumps({"scope":"SMOKE SOFTWARE TEST ONLY"}),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"smoke"):
                evaluate_final(Namespace(output=root))
            self.assertFalse((root/"final_test_report.json").exists())

    def test_output_collision_rejected_before_loading_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/"existing.txt").write_text("preserve",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"new/empty"):
                train_float(Namespace(output=root))
            self.assertEqual((root/"existing.txt").read_text(),"preserve")

    def test_atomic_json_retries_two_permission_conflicts(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"progress.json"
            import os
            real_replace=os.replace
            attempts=[]
            def replace(source,target):
                attempts.append((source,target))
                if len(attempts) < 3: raise PermissionError("transient reader lock")
                return real_replace(source,target)
            with patch("train_random_split.os.replace",side_effect=replace),patch("train_random_split.time.sleep") as sleep:
                atomic_json(path,{"message":"真实进度"})
            self.assertEqual(len(attempts),3)
            self.assertEqual(sleep.call_count,2)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["message"],"真实进度")
            self.assertFalse(path.with_name("progress.json.tmp").exists())

    def test_atomic_json_persistent_permission_conflict_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"progress.json"
            atomic_json(path,{"status":"old"})
            original=PermissionError("persistent lock")
            with patch("train_random_split.os.replace",side_effect=original) as replace,patch("train_random_split.time.sleep") as sleep:
                with self.assertRaises(PermissionError) as caught:
                    atomic_json(path,{"status":"pending"})
            self.assertIs(caught.exception,original)
            self.assertEqual(replace.call_count,12)
            self.assertLess(sum(c.args[0] for c in sleep.call_args_list),2.)
            self.assertEqual(json.loads(path.read_text())["status"],"old")
            self.assertEqual(json.loads(path.with_name("progress.json.tmp").read_text())["status"],"pending")

    def test_atomic_json_other_errors_not_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("train_random_split.os.replace",side_effect=OSError("disk error")) as replace,patch("train_random_split.time.sleep") as sleep:
                with self.assertRaisesRegex(OSError,"disk error"):
                    atomic_json(Path(temp)/"progress.json",{})
            self.assertEqual(replace.call_count,1)
            sleep.assert_not_called()

    def test_progress_reporting_failure_preserves_original_training_error(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/"run"
            original=ValueError("original dataset/train failure")
            fake_progress=Mock()
            fake_progress.update.side_effect=PermissionError("reporting lock")
            with patch("train_random_split.Progress",return_value=fake_progress),patch("train_random_split.read_training_dataset",side_effect=original):
                with self.assertRaises(ValueError) as caught:
                    train_float(Namespace(output=output,manifest=Path(temp)/"manifest.json"))
            self.assertIs(caught.exception,original)
            self.assertIn("original dataset/train failure",(output/"failure.log").read_text())
            self.assertTrue(any("Reporting failed progress" in note for note in original.__notes__))


if __name__ == "__main__": unittest.main()
