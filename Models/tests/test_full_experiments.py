"""Exercise manager full mode without spawning a real training process."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_float_experiments as manager


class FullExperimentTests(unittest.TestCase):
    def test_three_full_runs_validation_selection_then_one_test(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            manifest = work / 'manifest.json'
            manifest.write_text(json.dumps(dict(split_method='image-wise seeded class-stratified random shuffle',
                                                samples=[dict(label='FIST', split=s) for s in ('train', 'validation', 'test')])))
            sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
            root = work / 'runs'
            commands = []
            losses = {20260918: 1.5, 42: 1.3, 20260919: 1.4}

            class FakeTrainingProcess:
                pid = 12345
                def __init__(self, command, **kwargs):
                    commands.append(command)
                    self.command = command
                def wait(self):
                    output = Path(self.command[self.command.index('--output') + 1])
                    output.mkdir()
                    seed = int(self.command[self.command.index('--seed') + 1])
                    (output / 'best.weights.h5').write_bytes(str(seed).encode())
                    report = dict(dataset=dict(manifest_sha256=sha), quantization_performed=False, test_evaluated=False,
                                  selected_stage='full', trainability=dict(all_gradient_parameters_trainable=True,
                                  batchnorm_training_enabled=True), batchnorm_unchanged=False,
                                  selected_val_loss=losses[seed], validation=dict(accuracy=.5, macro_f1=.4),
                                  model_files_sha256={}, code_sha256={})
                    (output / 'training_report.json').write_text(json.dumps(report))
                    return 0

            def fake_evaluation(command, **kwargs):
                commands.append(command)
                chosen = json.loads((root / 'frozen_candidate.json').read_text())
                self.assertEqual(chosen['selected_run'], 'FULL-seed42')
                self.assertTrue(all('--evaluate-final' not in c for c in commands[:-1]))
                output = Path(command[command.index('--output') + 1])
                (output / 'final_test_report.json').write_text(json.dumps(dict(metrics=dict(accuracy=.5), source_groups={})))
                return 0

            arguments = ['manager', '--root', str(root), '--manifest', str(manifest), '--mode', 'full', '--dashboard-port', '8772']
            with patch.object(sys, 'argv', arguments), patch.object(manager.subprocess, 'Popen', FakeTrainingProcess), patch.object(manager.subprocess, 'call', fake_evaluation):
                manager.main()
            self.assertEqual(len(commands), 4)
            for command in commands[:3]:
                self.assertNotIn('--pretrained', command)
                self.assertEqual(command[command.index('--experiment') + 1], 'FULL')
                self.assertEqual(command[command.index('--full-epochs') + 1], '90')
                self.assertEqual(float(command[command.index('--full-lr') + 1]), .0001)
                self.assertEqual(command[command.index('--full-optimizer') + 1], 'adam')
                self.assertEqual(float(command[command.index('--full-weight-decay') + 1]), 0.)
                self.assertEqual(command[command.index('--full-class-weight') + 1], 'none')
                self.assertEqual(command[command.index('--checkpoint-metric') + 1], 'val_loss')
                self.assertEqual(command[command.index('--augmentation-profile') + 1], 'flip')
                self.assertEqual(float(command[command.index('--personal-sampling-factor') + 1]), 1.)
                self.assertEqual(float(command[command.index('--ema-decay') + 1]), 0.)
                self.assertNotIn('--teacher-model',command)
                self.assertEqual(float(command[command.index('--distillation-temperature')+1]),3.)
                self.assertEqual(float(command[command.index('--distillation-alpha')+1]),.5)
                self.assertEqual(float(command[command.index('--dropout') + 1]), .1)
            state = json.loads((root / 'experiment_status.json').read_text(encoding='utf-8'))
            spec = json.loads((root / 'run_spec.json').read_text(encoding='utf-8'))
            self.assertEqual(state['status'], 'completed')
            self.assertEqual(state['selected_run'], 'FULL-seed42')
            self.assertEqual(state['head_epochs'], 0)
            self.assertEqual(spec['finetune_epochs'], 0)
            self.assertFalse(spec['batchnorm_frozen'])
            self.assertEqual(spec['dropout'],.1)
            self.assertEqual(spec['full_optimizer'],'adam')
            self.assertEqual(spec['full_weight_decay'],0.)
            self.assertEqual(spec['full_class_weight'],'none')
            self.assertEqual(spec['checkpoint_metric'],'val_loss')
            self.assertEqual(spec['augmentation_profile'],'flip')
            self.assertEqual(spec['personal_sampling_factor'],1.)
            self.assertEqual(spec['ema_decay'],0.)
            self.assertEqual(spec['teacher_models'],[])
            self.assertIsNone(spec['pretrained'])
            self.assertIsNone(state['pretrained'])
            self.assertEqual(state['dropout'],.1)
            self.assertEqual(spec['dashboard_url'], 'http://127.0.0.1:8772/')
            self.assertFalse(state['quantization_performed'])

    def test_defer_final_test_stops_after_validation_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            manifest=work/'manifest.json'
            manifest.write_text(json.dumps(dict(split_method='random',samples=[
                dict(label='FIST',split=s) for s in ('train','validation','test')])))
            sha=hashlib.sha256(manifest.read_bytes()).hexdigest()
            root=work/'runs'
            pretrained=work/'pretrained-model'
            pretrained.mkdir()
            teachers=[]
            for number in range(3):
                teacher=work/f'teacher-{number}'
                teacher.mkdir()
                (teacher/'saved_model.pb').write_bytes(f'teacher-{number}'.encode())
                teachers.append(teacher)
            commands=[]

            class FakeTrainingProcess:
                pid=12345
                def __init__(self,command,**kwargs):
                    commands.append(command)
                    self.command=command
                def wait(self):
                    output=Path(self.command[self.command.index('--output')+1])
                    output.mkdir()
                    seed=int(self.command[self.command.index('--seed')+1])
                    (output/'best.weights.h5').write_bytes(str(seed).encode())
                    report=dict(dataset=dict(manifest_sha256=sha),quantization_performed=False,
                                test_evaluated=False,selected_stage='full',
                                trainability=dict(all_gradient_parameters_trainable=True,
                                                  batchnorm_training_enabled=True),
                                batchnorm_unchanged=False,selected_val_loss={20260918:1.5,42:1.3,20260919:1.4}[seed],
                                checkpoint_best_epoch=3,
                                checkpoint_selection=dict(metric='val_accuracy',epoch=3,metrics=dict(
                                    val_correct_count={20260918:99,42:101,20260919:100}[seed],
                                    val_accuracy={20260918:.495,42:.505,20260919:.5}[seed],
                                    val_macro_f1=.4,val_loss={20260918:1.5,42:1.3,20260919:1.4}[seed])),
                                validation=dict(accuracy=.5,macro_f1=.4),
                                source_groups=dict(validation=dict(personal_board_capture=dict(per_class={}))),
                                model_files_sha256={},code_sha256={})
                    (output/'training_report.json').write_text(json.dumps(report))
                    return 0

            arguments=['manager','--root',str(root),'--manifest',str(manifest),'--mode','full',
                       '--pretrained',str(pretrained),
                       '--full-epochs','200','--full-lr-schedule','warmup_cosine',
                       '--full-optimizer','adamw','--full-weight-decay','.01',
                       '--full-class-weight','sqrt_inverse',
                       '--checkpoint-metric','val_accuracy','--augmentation-profile','photo',
                       '--personal-sampling-factor','2',
                       '--ema-decay','.999',
                       *[value for teacher in teachers for value in ('--teacher-model',str(teacher))],
                       '--distillation-temperature','3','--distillation-alpha','.5',
                       '--dropout','.3',
                       '--early-stopping-start-epoch','151','--early-stopping-min-delta','.001',
                       '--early-stopping-patience','15','--defer-final-test']
            with patch.object(sys,'argv',arguments),patch.object(manager.subprocess,'Popen',FakeTrainingProcess), \
                 patch.object(manager.subprocess,'call') as final_call:
                manager.main()
            final_call.assert_not_called()
            self.assertEqual(len(commands),3)
            self.assertTrue(all('--evaluate-final' not in command for command in commands))
            self.assertTrue(all(Path(command[command.index('--pretrained')+1]) == pretrained.resolve()
                                for command in commands))
            self.assertTrue(all(command[command.index('--full-epochs')+1]=='200' for command in commands))
            self.assertTrue(all(command[command.index('--full-optimizer')+1]=='adamw' for command in commands))
            self.assertTrue(all(float(command[command.index('--full-weight-decay')+1])==.01 for command in commands))
            self.assertTrue(all(command[command.index('--full-class-weight')+1]=='sqrt_inverse' for command in commands))
            self.assertTrue(all(command[command.index('--checkpoint-metric')+1]=='val_accuracy' for command in commands))
            self.assertTrue(all(command[command.index('--augmentation-profile')+1]=='photo' for command in commands))
            self.assertTrue(all(float(command[command.index('--personal-sampling-factor')+1])==2 for command in commands))
            self.assertTrue(all(float(command[command.index('--ema-decay')+1])==.999 for command in commands))
            for command in commands:
                actual_teachers=[Path(command[index+1]) for index,value in enumerate(command)
                                 if value == '--teacher-model']
                self.assertEqual(actual_teachers,[teacher.resolve() for teacher in teachers])
            self.assertTrue(all(float(command[command.index('--dropout')+1])==.3 for command in commands))
            state=json.loads((root/'experiment_status.json').read_text(encoding='utf-8'))
            spec=json.loads((root/'run_spec.json').read_text(encoding='utf-8'))
            self.assertEqual(state['status'],'validation_completed')
            self.assertFalse(state['test_evaluated'])
            self.assertEqual(state['selected_run'],'FULL-seed42')
            self.assertTrue(spec['defer_final_test'])
            self.assertEqual(spec['full_lr_schedule'],'warmup_cosine')
            self.assertEqual(spec['dropout'],.3)
            self.assertEqual(spec['full_optimizer'],'adamw')
            self.assertEqual(spec['full_weight_decay'],.01)
            self.assertEqual(spec['full_class_weight'],'sqrt_inverse')
            self.assertEqual(spec['checkpoint_metric'],'val_accuracy')
            self.assertEqual(spec['augmentation_profile'],'photo')
            self.assertEqual(spec['personal_sampling_factor'],2.)
            self.assertEqual(spec['ema_decay'],.999)
            self.assertEqual(state['ema_decay'],.999)
            self.assertEqual([Path(row['path']) for row in spec['teacher_models']],
                             [teacher.resolve() for teacher in teachers])
            self.assertTrue(all(row['files_sha256'] for row in spec['teacher_models']))
            self.assertEqual(Path(spec['pretrained']),pretrained.resolve())
            self.assertEqual(Path(state['pretrained']),pretrained.resolve())
            self.assertEqual(state['checkpoint_metric'],'val_accuracy')
            self.assertIn('personal_board_capture',state['completed_runs'][0]['source_groups']['validation'])
            self.assertEqual(state['full_class_weight'],'sqrt_inverse')
            self.assertEqual(state['dropout'],.3)
            self.assertEqual(spec['early_stopping_start_epoch'],151)
            self.assertFalse((root/'final-evaluation.log').exists())
            self.assertFalse(any(root.rglob('final_test_report.json')))

    def test_manager_rejects_nonfinite_and_out_of_range_dropout(self):
        for value in ('nan','inf','-inf','-0.01','1','1.01'):
            with self.subTest(value=value),patch.object(sys,'argv',[
                    'manager','--root','unused-root','--manifest','unused-manifest.json',f'--dropout={value}']):
                with self.assertRaises(SystemExit) as caught:
                    manager.main()
                self.assertEqual(caught.exception.code,2)

    def test_manager_rejects_full_class_weight_in_staged_mode(self):
        with patch.object(sys,'argv',['manager','--root','unused-root','--manifest','unused-manifest.json',
                                      '--mode','staged','--full-class-weight','sqrt_inverse']):
            with self.assertRaises(SystemExit) as caught:
                manager.main()
        self.assertEqual(caught.exception.code,2)

    def test_manager_rejects_invalid_full_optimizer_decay_pairs(self):
        cases = [('adam','.01'),('adamw','0'),('adamw','nan'),('adamw','-0.1')]
        for optimizer,decay in cases:
            with self.subTest(optimizer=optimizer,decay=decay),patch.object(sys,'argv',[
                    'manager','--root','unused-root','--manifest','unused-manifest.json','--mode','full',
                    '--full-optimizer',optimizer,'--full-weight-decay',decay]):
                with self.assertRaises(SystemExit) as caught:
                    manager.main()
                self.assertEqual(caught.exception.code,2)

    def test_manager_training_variants_are_full_only_and_factor_is_positive(self):
        cases = [
            ['--mode','staged','--checkpoint-metric','val_accuracy'],
            ['--mode','staged','--augmentation-profile','photo'],
            ['--mode','staged','--augmentation-profile','geometry'],
            ['--mode','staged','--personal-sampling-factor','2'],
            ['--mode','staged','--ema-decay','.999'],
            ['--mode','full','--personal-sampling-factor','0'],
            ['--mode','full','--personal-sampling-factor','inf'],
            ['--mode','full','--ema-decay','1'],
            ['--mode','full','--ema-decay','nan'],
            ['--mode','full','--teacher-model','missing-one'],
            ['--mode','full','--distillation-temperature','2'],
        ]
        for extra in cases:
            with self.subTest(extra=extra), patch.object(sys,'argv',[
                    'manager','--root','unused-root','--manifest','unused-manifest.json',*extra]):
                with self.assertRaises(SystemExit) as caught:
                    manager.main()
                self.assertEqual(caught.exception.code,2)

    def test_output_collision_preserves_history_without_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps(dict(samples=[])))
            original = manifest.read_bytes()
            with patch.object(sys, 'argv', ['manager', '--root', str(root), '--manifest', str(manifest), '--mode', 'full']), patch.object(manager.subprocess, 'Popen') as process:
                with self.assertRaisesRegex(ValueError, 'new/empty'):
                    manager.main()
            process.assert_not_called()
            self.assertEqual(manifest.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
