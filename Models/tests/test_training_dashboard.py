import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

module = Path(__file__).resolve().parents[1] / 'training_dashboard.py'
spec = importlib.util.spec_from_file_location('training_dashboard', module)
dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)


class DashboardTests(unittest.TestCase):
    def test_campaign_follows_only_direct_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'round0').mkdir()
            (root / 'campaign_state.json').write_text(json.dumps({'active_round': 'round0'}), encoding='utf-8')
            value = dashboard.snapshot(root)
            self.assertEqual(value['campaign']['active_round'], 'round0')
            self.assertEqual(value['runs'], [])
            (root / 'campaign_state.json').write_text(json.dumps({'active_round': '../escape'}), encoding='utf-8')
            with self.assertRaises(ValueError):
                dashboard.snapshot(root)

    def test_empty_root_has_no_fabricated_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            value = dashboard.snapshot(Path(directory))
            self.assertEqual(value['runs'], [])
            self.assertEqual(value['summary'], {})

    def test_real_state_and_root_log_are_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / 'E0-seed42'
            run.mkdir()
            (run / 'progress.json').write_text(json.dumps({'status': 'running', 'epoch': 2}), encoding='utf-8')
            (root / 'E0-seed42.console.log').write_text('actual test fixture log', encoding='utf-8')
            (root / 'experiment_status.json').write_text(json.dumps({'status': 'running'}), encoding='utf-8')
            value = dashboard.snapshot(root)
            self.assertEqual(value['runs'][0]['epoch'], 2)
            self.assertEqual(value['runs'][0]['run_id'], 'E0-seed42')
            self.assertEqual(value['runs'][0]['log_tail'], 'actual test fixture log')
            self.assertEqual(value['summary']['status'], 'running')

    def test_invalid_run_json_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / 'broken'
            run.mkdir()
            (run / 'progress.json').write_text('{', encoding='utf-8')
            self.assertEqual(dashboard.snapshot(root)['runs'], [])

    def test_manager_failure_overrides_stale_child_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / 'E0-seed42'
            run.mkdir()
            (run / 'progress.json').write_text(json.dumps({'status': 'running'}), encoding='utf-8')
            (root / 'experiment_status.json').write_text(json.dumps(
                {'status': 'failed', 'active_run': 'E0-seed42', 'message': 'Actual manager failure'}), encoding='utf-8')
            result = dashboard.snapshot(root)['runs'][0]
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['message'], 'Actual manager failure')


if __name__ == '__main__':
    unittest.main()
