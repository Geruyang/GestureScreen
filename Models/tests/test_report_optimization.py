"""Report generation uses recorded dataset facts rather than legacy constants."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import report_optimization as reporter


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class OptimizationReportTests(unittest.TestCase):
    def test_v5_counts_are_read_from_frozen_run_spec(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'campaign'
            round_dir = root / 'round0'
            run_dir = round_dir / 'FULL-seed42'
            output = root / 'RESULTS.md'
            counts = {
                'train': {'A': 1000, 'B': 400},
                'validation': {'A': 150, 'B': 50},
                'test': {'A': 300, 'B': 100},
            }
            write(root / 'campaign_state.json', {
                'status': 'completed',
                'failed_attempts': [{'name': 'round0-failed',
                                     'failure': 'synthetic disk interruption'}],
                'rounds': [{'name': 'round0', 'recipe': 'baseline', 'reason': 'fixed recipe',
                            'mean_val_loss': .5, 'mean_val_accuracy': .7,
                            'mean_val_macro_f1': .6, 'decision': '当前最优方案'}],
            })
            write(root / 'final_selection.json', {
                'selected_round': 'round0', 'selected_run': 'FULL-seed42',
                'manifest_sha256': 'manifest-sha',
                'candidate': {'weights_sha256': 'weights-sha'},
            })
            write(round_dir / 'final_parameter_audit.json', {'status': 'passed'})
            write(round_dir / 'run_spec.json', {'dataset_context': {
                'manifest_sha256': 'manifest-sha', 'class_counts': counts,
                'split_method': 'image-wise seeded class-stratified random shuffle',
            }})
            write(run_dir / 'training_report.json', {
                'config': {'seed': 42},
                'stage_details': {'full': {'completed_epochs': 165, 'best_epoch': 55,
                                            'stopping_reason': 'delayed val_loss patience 15'}},
                'selected_val_loss': .4,
                'validation': {'accuracy': .75, 'macro_f1': .7},
                'trainability': {'trainable_parameters': 214727},
                'batchnorm_layer_count': 27,
                'changed_backbone_layers': [str(i) for i in range(54)],
            })
            per_class = {'A': {'support': 300, 'recall': .8, 'precision': .7, 'f1': .75},
                         'B': {'support': 100, 'recall': .6, 'precision': .7, 'f1': .65}}
            write(run_dir / 'final_test_report.json', {'metrics': {
                'sample_count': 400, 'errors': 100, 'accuracy': .75,
                'macro_f1': .7, 'balanced_accuracy': .7, 'per_class': per_class,
            }})
            with patch.object(sys, 'argv', ['report', '--root', str(root), '--output', str(output)]):
                reporter.main()
            text = output.read_text(encoding='utf-8')
            self.assertIn('数据2000张：1400训练/200验证/400测试', text)
            self.assertIn('200张验证集仍有限', text)
            self.assertIn('`round0-failed`：synthetic disk interruption', text)
            self.assertIn('历史数据和测试指标曾用于数据开发与扩充', text)
            self.assertNotIn('数据894张', text)
            self.assertNotIn('89张验证集', text)
            self.assertNotIn('numpy.float32', text)
            self.assertNotIn('同一测试集', text)
            state_path = root / 'campaign_state.json'
            state = json.loads(state_path.read_text(encoding='utf-8'))
            state['selection_metric'] = 'val_accuracy'
            state['target_accuracy'] = .85
            write(state_path, state)
            accuracy_output = root / 'ACCURACY_RESULTS.md'
            with patch.object(sys, 'argv', ['report', '--root', str(root), '--output', str(accuracy_output)]):
                reporter.main()
            accuracy_text = accuracy_output.read_text(encoding='utf-8')
            self.assertIn('保存验证准确率最高的权重', accuracy_text)
            self.assertIn('本人FIST/PALM各自平均召回不下降', accuracy_text)
            self.assertNotIn('保存全程最低验证损失权重', accuracy_text)
            self.assertNotIn('三种子平均最优验证交叉熵', accuracy_text)
            self.assertIn('本轮单模型整体测试目标 85%：**未达到**', accuracy_text)

    def test_manifest_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root / 'campaign_state.json', {'status': 'completed'})
            write(root / 'final_selection.json', {'selected_round': 'round0',
                                                   'manifest_sha256': 'frozen'})
            write(root / 'round0' / 'final_parameter_audit.json', {'status': 'passed'})
            write(root / 'round0' / 'run_spec.json', {'dataset_context': {
                'manifest_sha256': 'different', 'class_counts': {}}})
            with patch.object(sys, 'argv', ['report', '--root', str(root),
                                            '--output', str(root / 'RESULTS.md')]):
                with self.assertRaisesRegex(ValueError, 'different manifests'):
                    reporter.main()


if __name__ == '__main__':
    unittest.main()
