import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from test_random_training import RandomTrainingTests
from random_dataset import read_training_dataset, SESSION_METHOD


class SessionTrainingTests(RandomTrainingTests):
    def test_uniform_dynamic_counts_without_session_or_source_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            path, manifest = self.make_dataset(Path(temp))
            manifest['split_counts'] = dict(train=7, validation=7, test=7)
            for row in manifest['samples']:
                row['source'] = 'licensed_external_image'
            path.write_text(json.dumps(manifest))
            with patch('random_dataset.preprocess', self.preprocess):
                report, _ = read_training_dataset(path)
            self.assertFalse(report['session_isolated'])
            self.assertEqual(report['sample_count'], 21)

    def fixture(self, root):
        path, manifest = self.make_dataset(root)
        manifest.update(split_method=SESSION_METHOD, split_ratios=dict(train=8, validation=2, test=2))
        for row in manifest['samples']:
            row.update(session=row['split'], session_id=row['split'], clip_id=row['file'])
        path.write_text(json.dumps(manifest))
        return path, manifest

    def test_session_mode_dynamic_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            path, _ = self.fixture(Path(temp))
            with patch('random_dataset.preprocess', self.preprocess):
                report, tensors = read_training_dataset(path)
            self.assertTrue(report['session_isolated'])
            self.assertEqual(report['sample_count'], 21)

    def test_session_leakage_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path, manifest = self.fixture(Path(temp))
            manifest['samples'][-1]['session_id'] = 'train'
            path.write_text(json.dumps(manifest))
            with patch('random_dataset.preprocess', self.preprocess), self.assertRaisesRegex(ValueError, 'leakage'):
                read_training_dataset(path)

    def test_external_holdout_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path, manifest = self.fixture(Path(temp))
            manifest['samples'][-1]['source'] = 'licensed_external_image'
            path.write_text(json.dumps(manifest))
            with patch('random_dataset.preprocess', self.preprocess), self.assertRaisesRegex(ValueError, 'training-only'):
                read_training_dataset(path)
