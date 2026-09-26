"""No-fit numerical tests for deterministic FULL training variants."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dataset import LABELS, flip_label
from training_variants import (augment_training_batch, augmentation_evidence,
                               epoch_training_indexes, sampling_evidence,
                               select_checkpoint_entry)


class TrainingVariantTests(unittest.TestCase):
    def v5_train_arrays(self):
        counts = [84, 63, 224, 280, 287, 280, 182]
        personal = [41, 31, 30, 42, 35, 61, 50]
        labels = []
        sources = []
        for label, (count, personal_count) in enumerate(zip(counts, personal)):
            labels.extend([label] * count)
            sources.extend(['personal_board_capture'] * personal_count)
            sources.extend(['licensed_external_image'] * (count-personal_count))
        return (np.arange(sum(counts), dtype=np.int64), np.asarray(labels, dtype=np.int64),
                np.asarray(sources, dtype=object), counts, personal)

    def test_factor_one_is_exact_legacy_shuffle(self):
        base, labels, sources, _counts, _personal = self.v5_train_arrays()
        actual, audit = epoch_training_indexes(base, labels, sources, LABELS, 1.0, 42, 7)
        expected = base.copy()
        np.random.default_rng(np.random.SeedSequence([42, 7, 1701])).shuffle(expected)
        self.assertTrue(np.array_equal(actual, expected))
        self.assertEqual(audit['maximum_index_repeats'], 1)
        self.assertEqual(audit['policy'], 'legacy_no_replacement_shuffle')

    def test_factor_two_preserves_length_and_class_counts_with_coverage_first(self):
        base, labels, sources, counts, personal = self.v5_train_arrays()
        first, audit = epoch_training_indexes(base, labels, sources, LABELS, 2.0, 20260918, 0)
        second, repeated = epoch_training_indexes(base, labels, sources, LABELS, 2.0, 20260918, 0)
        self.assertTrue(np.array_equal(first, second))
        self.assertEqual(audit, repeated)
        self.assertEqual(len(first), len(base))
        self.assertLessEqual(audit['maximum_index_repeats'], 2)
        self.assertEqual(audit['class_counts'], dict(zip(LABELS, counts)))
        expected_personal = [round(count * 2 * own / (2 * own + count-own))
                             for count, own in zip(counts, personal)]
        for label, target in zip(LABELS, expected_personal):
            self.assertEqual(audit['source_class_counts'][label]['personal_board_capture'], target)
        evidence = sampling_evidence(base, labels, sources, LABELS, 2.0)
        self.assertEqual([evidence['target_source_class_counts'][label]['personal'] for label in LABELS],
                         expected_personal)
        self.assertTrue(evidence['coverage_before_repeat'])

    def test_sampling_rejects_factor_that_cannot_honor_repeat_cap(self):
        base, labels, sources, _counts, _personal = self.v5_train_arrays()
        with self.assertRaisesRegex(ValueError, 'repeat cap'):
            sampling_evidence(base, labels, sources, LABELS, 1000.0)

    def test_flip_profile_is_byte_for_byte_legacy_and_stream_is_profile_independent(self):
        images = np.arange(4 * 4 * 4, dtype=np.float32).reshape(4, 4, 4, 1)
        targets = np.array([0, 1, 2, 3])
        rng = np.random.default_rng(np.random.SeedSequence([42, 3, 5, 2701]))
        flips = rng.random(len(images)) < .5
        expected_images = images.copy()
        expected_targets = targets.copy()
        expected_images[flips] = expected_images[flips, :, ::-1, :]
        expected_targets[flips] = [flip_label(int(label)) for label in expected_targets[flips]]
        actual_images, actual_targets = augment_training_batch(
            images, targets, 'flip', 42, 3, 5, flip_label)
        self.assertTrue(np.array_equal(actual_images, expected_images))
        self.assertTrue(np.array_equal(actual_targets, expected_targets))
        for profile in ('photo', 'geometry', 'photo_geometry', 'targeted_hard_classes'):
            _values, profile_targets = augment_training_batch(
                images, targets, profile, 42, 3, 5, flip_label)
            self.assertTrue(np.array_equal(profile_targets, expected_targets))
        self.assertTrue(np.array_equal(images, np.arange(64, dtype=np.float32).reshape(4,4,4,1)))

    def test_photo_and_geometry_are_deterministic_clipped_and_have_no_black_padding(self):
        images = np.full((12, 12, 12, 1), 100.0, dtype=np.float32)
        targets = np.arange(12) % len(LABELS)
        for profile in ('photo', 'geometry', 'photo_geometry', 'targeted_hard_classes'):
            first = augment_training_batch(images, targets, profile, 9, 2, 1, flip_label)
            second = augment_training_batch(images, targets, profile, 9, 2, 1, flip_label)
            self.assertTrue(np.array_equal(first[0], second[0]))
            self.assertTrue(np.array_equal(first[1], second[1]))
            self.assertGreaterEqual(float(first[0].min()), 0.0)
            self.assertLessEqual(float(first[0].max()), 255.0)
        geometry, _ = augment_training_batch(images, targets, 'geometry', 9, 2, 1, flip_label)
        self.assertTrue(np.allclose(geometry, 100.0))
        evidence = augmentation_evidence('geometry')
        self.assertEqual(evidence['geometry']['boundary'], 'edge')
        self.assertFalse(evidence['geometry']['vertical_flip'])
        self.assertFalse(evidence['photo']['enabled'])

    def test_targeted_profile_is_deterministic_and_records_class_specific_policy(self):
        images = np.arange(7 * 8 * 8, dtype=np.float32).reshape(7, 8, 8, 1)
        targets = np.arange(7, dtype=np.int64)
        first = augment_training_batch(images, targets, 'targeted_hard_classes',
                                       20260918, 2, 3, flip_label)
        second = augment_training_batch(images, targets, 'targeted_hard_classes',
                                        20260918, 2, 3, flip_label)
        self.assertTrue(np.array_equal(first[0], second[0]))
        self.assertTrue(np.array_equal(first[1], second[1]))
        self.assertGreaterEqual(float(first[0].min()), 0.0)
        self.assertLessEqual(float(first[0].max()), 255.0)
        evidence = augmentation_evidence('targeted_hard_classes')
        self.assertTrue(evidence['targeted']['enabled'])
        self.assertIn('OTHER', evidence['targeted']['labels'])
        self.assertIn('blur', evidence['pipeline_order'])

    def test_photo_uses_one_joint_gate_and_contrast_about_127_point_5(self):
        images = np.stack([np.full((3,3,1), value, dtype=np.float32)
                           for value in (20., 80., 140., 220.)])
        targets = np.array([2,2,2,2])
        flipped, _ = augment_training_batch(images, targets, 'flip', 17, 4, 3, flip_label)
        actual, _ = augment_training_batch(images, targets, 'photo', 17, 4, 3, flip_label)
        rng = np.random.default_rng(np.random.SeedSequence([17,4,3,3701]))
        apply = rng.random(len(images)) < .8
        contrast = rng.uniform(.85, 1.15, len(images))
        brightness = rng.uniform(-15., 15., len(images))
        expected = flipped.copy()
        for number in np.flatnonzero(apply):
            expected[number] = np.clip((expected[number]-127.5)*contrast[number] +
                                       127.5+brightness[number], 0., 255.)
        self.assertTrue(np.array_equal(actual, expected))
        self.assertTrue(np.array_equal(actual[~apply], flipped[~apply]))

    def test_accuracy_checkpoint_lexicographic_order(self):
        entries = [
            dict(epoch=1,val_correct_count=150,val_accuracy=.75,val_macro_f1=.70,val_loss=.6),
            dict(epoch=2,val_correct_count=151,val_accuracy=.755,val_macro_f1=.69,val_loss=.7),
            dict(epoch=3,val_correct_count=151,val_accuracy=.755,val_macro_f1=.72,val_loss=.8),
            dict(epoch=4,val_correct_count=151,val_accuracy=.755,val_macro_f1=.72,val_loss=.7),
            dict(epoch=5,val_correct_count=151,val_accuracy=.755,val_macro_f1=.72,val_loss=.7),
        ]
        self.assertEqual(select_checkpoint_entry(entries, 'val_accuracy')['epoch'], 4)
        self.assertEqual(select_checkpoint_entry(entries, 'val_loss')['epoch'], 1)


if __name__ == '__main__':
    unittest.main()
