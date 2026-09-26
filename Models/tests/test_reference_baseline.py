import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reference_baseline import initialize, digest


class ReferenceBaselineTests(unittest.TestCase):
    def test_copy_is_explicit_reference_and_excludes_historical_test(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / 'historical'
            source.mkdir()
            manifest = base / 'manifest.json'
            manifest.write_text('{}', encoding='utf-8')
            def write(path, value):
                path.write_text(json.dumps(value), encoding='utf-8')
            write(source/'full_parameter_audit.json', {'status':'passed'})
            write(source/'experiment_status.json', {'test_evaluated':True,'selected_run':'FULL-seed20260918',
                                                   'final_test':{'accuracy':.7825}})
            write(source/'final_parameter_audit.json', {'historical':True})
            for seed in (20260918, 42, 20260919):
                directory=source/f'FULL-seed{seed}'
                directory.mkdir()
                (directory/'best.weights.h5').write_bytes(b'weights')
                write(directory/'final_test_report.json', {'historical':True})
                report=dict(dataset={'manifest_sha256':digest(manifest)},
                            config={'checkpoint_metric':'val_accuracy','seed':seed},
                            best_weights_sha256=digest(directory/'best.weights.h5'),
                            model_files_sha256={},code_sha256={},selected_val_loss=.7,
                            validation={'sample_count':200,'errors':40,'accuracy':.8,'macro_f1':.82},
                            source_groups={'validation':{'personal_board_capture':{'per_class':{
                                'FIST':{'support':8,'errors':3,'recall':.625},
                                'PALM':{'support':2,'errors':0,'recall':1.0}}}}})
                write(directory/'training_report.json', report)
            before={p.relative_to(source):digest(p) for p in source.rglob('*') if p.is_file()}
            state=initialize(source,base/'campaign',manifest)
            self.assertEqual(state['rounds'][0]['personal_correct_total'], {'FIST':15,'PALM':6})
            self.assertTrue(state['rounds'][0]['reused_baseline'])
            self.assertEqual(state['rounds'][0]['val_correct_total'],480)
            copied=base/'campaign'/'round0-reference'
            self.assertFalse(list(copied.rglob('final_test_report.json')))
            self.assertFalse((copied/'final_parameter_audit.json').exists())
            provenance=json.loads((copied/'reference_provenance.json').read_text(encoding='utf-8'))
            self.assertFalse(provenance['new_fit_performed'])
            self.assertTrue(provenance['historical_test_used'])
            self.assertEqual(before,{p.relative_to(source):digest(p) for p in source.rglob('*') if p.is_file()})
            with self.assertRaises(FileExistsError):
                initialize(source,base/'campaign',manifest)


if __name__=='__main__':
    unittest.main()
