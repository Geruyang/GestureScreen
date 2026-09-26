"""Class rounding, image-wise RNG, compatibility and reversible commit checks."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dataset import LABELS, PREPROCESS_VERSION
from random_dataset import STRATIFIED_METHOD, read_random_dataset
from stratified_split_custom_dataset import (RATIOS, SPLITS, TOTALS, allocate_counts,
                                             apply_split, assignments, contained, prepare)

CLASS_TOTALS = dict(zip(LABELS, (73, 59, 120, 120, 117, 202, 109)))
EXPECTED = dict(zip(LABELS, ((51, 7, 15), (41, 6, 12), (84, 12, 24),
                            (84, 12, 24), (82, 12, 23), (142, 20, 40), (76, 11, 22))))


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def fake_preprocess(raw, *args):
    return raw * 2304, dict(acceptable=True)


class StratifiedTests(unittest.TestCase):
    def make_fixture(self, workspace):
        dataset = workspace / "custom_dataset"
        source = workspace / "GestureScreen/Datasets/gesture-800-v1"
        order = list(range(800))
        random.Random(42).shuffle(order)
        old_splits = {i: "train" if rank < 560 else "validation" if rank < 640 else "test"
                      for rank, i in enumerate(order)}
        rows = []
        for label, count in CLASS_TOTALS.items():
            for _ in range(count):
                i = len(rows)
                split = old_splits[i]
                raw, png = i.to_bytes(4, "big"), b"fixture PNG" + i.to_bytes(4, "big")
                filename = f"{i:04d}_{i}"
                file = f"rgb565/{split}/{label}/{filename}.rgb565"
                preview = f"{split}/{label}/{filename}.png"
                for path, content in ((dataset / file, raw), (dataset / preview, png)):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                rows.append(dict(record_id=str(i), file=file, preview_file=preview,
                    sha256=hashlib.sha256(raw).hexdigest(), preview_sha256=hashlib.sha256(png).hexdigest(),
                    session="SHARED_REAL_VIDEO", clip_id="KEEP_THIS_CLIP", label=label, split=split,
                    width=320, height=240, stride_bytes=640, byte_order="msb_first", capture_ms=i,
                    sensor_profile="test", exposure_profile="test", source="fixture"))
        manifest = dict(schema_version=1, preprocessing=PREPROCESS_VERSION,
                        split_method="image-wise seeded uniform random shuffle", samples=rows)
        save_json(dataset / "dataset_manifest.json", manifest)
        save_json(dataset / "split_audit.json", {"historical": True})
        (dataset / "README.md").write_text("old README", encoding="utf-8")
        (dataset / "training_results.md").write_text("preserve old results", encoding="utf-8")
        save_json(source / "dataset_manifest.json", manifest)
        save_json(source / "near_duplicate_candidates.json", [{"first": 0, "second": 1}])
        return dataset, manifest

    def test_exact_totals_and_optimal_current_rounding(self):
        allocation = allocate_counts(CLASS_TOTALS, TOTALS)
        for label in LABELS:
            self.assertEqual(tuple(allocation[label][s] for s in SPLITS), EXPECTED[label])
            self.assertEqual(sum(allocation[label].values()), CLASS_TOTALS[label])
        self.assertEqual({s: sum(allocation[l][s] for l in LABELS) for s in SPLITS}, TOTALS)

    def test_integer_targets_are_exact_and_nonintegers_floor_or_ceil(self):
        allocation = allocate_counts(CLASS_TOTALS, TOTALS)
        for label, support in CLASS_TOTALS.items():
            for split, ratio in RATIOS.items():
                floor, remainder = divmod(support * ratio, 10)
                self.assertIn(allocation[label][split], (floor, floor + bool(remainder)))
        exact = allocate_counts(dict.fromkeys(LABELS, 100), dict(train=490, validation=70, test=140))
        self.assertTrue(all(v == dict(train=70, validation=10, test=20) for v in exact.values()))

    def test_assignment_is_seeded_image_wise_not_video_grouped(self):
        rows = [dict(label=label, session="ONE_VIDEO", clip_id="ONE_CLIP")
                for label, count in CLASS_TOTALS.items() for _ in range(count)]
        allocation = allocate_counts(CLASS_TOTALS, TOTALS)
        first = assignments(rows, 20260918, allocation)
        self.assertEqual(first, assignments(rows, 20260918, allocation))
        self.assertNotEqual(first, assignments(rows, 42, allocation))
        self.assertEqual(Counter(first.values()), TOTALS)
        self.assertEqual(set(first.values()), set(SPLITS))
        for label in LABELS:
            self.assertEqual(Counter(first[i] for i, r in enumerate(rows) if r["label"] == label), allocation[label])

    def test_mismatched_totals_and_unsafe_paths_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "disagree"):
            allocate_counts(CLASS_TOTALS, dict(train=561, validation=80, test=160))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for relative in ("..", "../outside", "."):
                with self.assertRaisesRegex(ValueError, "strictly inside"):
                    contained(root, relative)

    def test_prepare_is_read_only_and_unlisted_files_block_moves(self):
        with tempfile.TemporaryDirectory() as temp:
            dataset, _ = self.make_fixture(Path(temp))
            before = (dataset / "dataset_manifest.json").read_bytes()
            _, _, plan = prepare(dataset, 20260918)
            self.assertEqual(plan["class_counts"]["validation"]["PALM"], 12)
            self.assertEqual(before, (dataset / "dataset_manifest.json").read_bytes())
            (dataset / "train/unlisted.txt").write_text("user file", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unlisted"):
                prepare(dataset, 20260918)

    def test_apply_archives_previous_data_and_preserves_all_samples(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            dataset, original = self.make_fixture(workspace)
            old_bytes = (dataset / "dataset_manifest.json").read_bytes()
            with patch("random_dataset.preprocess", fake_preprocess):
                result = apply_split(dataset, 20260918, workspace)
                report, _ = read_random_dataset(dataset / "dataset_manifest.json", expected_counts=TOTALS)
            archive = Path(result["archive"])
            self.assertEqual((archive / "dataset_manifest.json").read_bytes(), old_bytes)
            self.assertEqual(report["counts"], result["class_counts"])
            current = json.loads((dataset / "dataset_manifest.json").read_text())["samples"]
            for old, new in zip(original["samples"], current):
                for field in ("record_id", "label", "sha256", "preview_sha256", "session", "clip_id"):
                    self.assertEqual(old[field], new[field])
                self.assertEqual((archive / old["file"]).read_bytes(), (dataset / new["file"]).read_bytes())
            self.assertEqual((dataset / "training_results.md").read_text(), "preserve old results")
            self.assertEqual(len(list(dataset.glob("rgb565/**/*.rgb565"))), 800)
            self.assertEqual(sum(len(list((dataset / s).rglob("*.png"))) for s in SPLITS), 800)
            self.assertEqual(report["sessions_crossing_splits"], 1)
            self.assertEqual(apply_split(dataset, 20260918, workspace)["status"], "already_applied")

    def test_commit_failure_restores_previous_folders_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            dataset, _ = self.make_fixture(workspace)
            before = {name: (dataset / name).read_bytes() for name in ("dataset_manifest.json", "README.md", "split_audit.json")}
            with patch("random_dataset.preprocess", fake_preprocess), patch(
                    "stratified_split_custom_dataset.os.replace", side_effect=PermissionError("fixture lock")):
                with self.assertRaisesRegex(PermissionError, "fixture lock"):
                    apply_split(dataset, 20260918, workspace)
            for name, content in before.items():
                self.assertEqual((dataset / name).read_bytes(), content)
            prepare(dataset, 20260918)  # Old manifest and its 1600 files still agree.

    def test_stratified_reader_requires_ratios_and_checks_class_rounding(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            dataset, _ = self.make_fixture(workspace)
            with patch("random_dataset.preprocess", fake_preprocess):
                apply_split(dataset, 20260918, workspace)
                path = dataset / "dataset_manifest.json"
                manifest = json.loads(path.read_text())
                del manifest["split_ratios"]
                save_json(path, manifest)
                with self.assertRaisesRegex(ValueError, "ratios"):
                    read_random_dataset(path)
                manifest["split_ratios"] = RATIOS
                for row in manifest["samples"]:
                    if row["label"] == "POINT_LEFT" and row["split"] == "validation":
                        row["split"] = "train"
                        break
                save_json(path, manifest)
                with self.assertRaisesRegex(ValueError, "rounding bounds"):
                    read_random_dataset(path)


if __name__ == "__main__":
    unittest.main()
