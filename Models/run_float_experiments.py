"""Serial training jobs, validation-only selection, then one frozen float test."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from training_variants import AUGMENTATION_PROFILES, CHECKPOINT_METRICS
from training_advanced import validate_distillation, validate_ema_decay


def directory_hashes(directory):
    return {str(path.relative_to(directory)).replace('\\', '/'):
            hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob('*')) if path.is_file()}


def atomic(path, content):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding='utf-8')
    for attempt in range(12):
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            if attempt == 11:
                raise
            time.sleep(min(.01 * (attempt + 1), .1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--pretrained', type=Path,
                        help='optional pretrained model directory forwarded to every training run')
    parser.add_argument('--dashboard-port', type=int, default=8770)
    parser.add_argument('--mode', choices=('staged', 'full'), default='staged')
    parser.add_argument('--full-epochs', type=int, default=90)
    parser.add_argument('--full-lr', type=float, default=.0001)
    parser.add_argument('--full-optimizer', choices=('adam', 'adamw'), default='adam')
    parser.add_argument('--full-weight-decay', type=float, default=0.0)
    parser.add_argument('--full-class-weight', choices=('none', 'sqrt_inverse'), default='none')
    parser.add_argument('--checkpoint-metric', choices=CHECKPOINT_METRICS, default='val_loss')
    parser.add_argument('--augmentation-profile', choices=AUGMENTATION_PROFILES, default='flip')
    parser.add_argument('--personal-sampling-factor', type=float, default=1.0)
    parser.add_argument('--ema-decay', type=float, default=0.0)
    parser.add_argument('--teacher-model', type=Path, action='append', default=[])
    parser.add_argument('--distillation-temperature', type=float, default=3.0)
    parser.add_argument('--distillation-alpha', type=float, default=.5)
    parser.add_argument('--dropout', type=float, default=.1)
    parser.add_argument('--full-lr-schedule', choices=('constant', 'warmup_cosine'), default='constant')
    parser.add_argument('--warmup-start-lr', type=float, default=.00001)
    parser.add_argument('--warmup-min-lr', type=float, default=.000001)
    parser.add_argument('--early-stopping-start-epoch', type=int, default=1)
    parser.add_argument('--early-stopping-min-delta', type=float, default=0.0)
    parser.add_argument('--early-stopping-patience', type=int, default=5)
    parser.add_argument('--defer-final-test', action='store_true',
                        help='freeze validation-selected candidate without opening the test split')
    args = parser.parse_args()
    if not 1 <= args.dashboard_port <= 65535:
        parser.error('dashboard port must be 1..65535')
    if not 0 < args.full_epochs <= 200 or not 0 < args.full_lr < 1:
        parser.error('invalid full-training epoch cap / learning rate')
    if (not math.isfinite(args.full_weight_decay) or
            (args.full_optimizer == 'adam' and args.full_weight_decay != 0) or
            (args.full_optimizer == 'adamw' and args.full_weight_decay <= 0)):
        parser.error('Adam requires --full-weight-decay 0; AdamW requires finite positive decay')
    if not math.isfinite(args.dropout) or not 0 <= args.dropout < 1:
        parser.error('dropout must be finite and satisfy 0 <= dropout < 1')
    if args.full_lr_schedule == 'warmup_cosine' and not 0 < args.warmup_min_lr <= args.warmup_start_lr <= args.full_lr < 1:
        parser.error('warmup/min learning rates must satisfy 0 < min <= start <= full_lr < 1')
    if args.full_lr_schedule == 'warmup_cosine' and args.full_epochs < 5:
        parser.error('warmup_cosine requires at least 5 full epochs')
    if args.early_stopping_start_epoch < 1 or args.early_stopping_min_delta < 0 or args.early_stopping_patience < 1:
        parser.error('invalid delayed early-stopping parameters')
    if args.mode != 'full' and args.full_class_weight != 'none':
        parser.error('--full-class-weight is valid only with --mode full')
    if args.mode != 'full' and (args.full_optimizer != 'adam' or args.full_weight_decay != 0):
        parser.error('FULL optimizer options are valid only with --mode full')
    if not math.isfinite(args.personal_sampling_factor) or args.personal_sampling_factor <= 0:
        parser.error('--personal-sampling-factor must be finite and positive')
    try:
        args.ema_decay = validate_ema_decay(args.ema_decay)
    except ValueError as error:
        parser.error(str(error))
    if args.mode != 'full' and args.ema_decay != 0:
        parser.error('--ema-decay is valid only with --mode full')
    teacher_paths = [path.resolve() for path in args.teacher_model]
    try:
        teacher_paths, args.distillation_temperature, args.distillation_alpha = \
            validate_distillation(teacher_paths, args.distillation_temperature,
                                  args.distillation_alpha)
    except ValueError as error:
        parser.error(str(error))
    if teacher_paths and args.mode != 'full':
        parser.error('--teacher-model is valid only with --mode full')
    for teacher_path in teacher_paths:
        if not teacher_path.is_dir():
            parser.error(f'teacher model directory does not exist: {teacher_path}')
    if args.mode != 'full' and (args.checkpoint_metric != 'val_loss' or
            args.augmentation_profile != 'flip' or args.personal_sampling_factor != 1.0):
        parser.error('checkpoint/augmentation/personal-sampling variants are valid only with --mode full')
    root = args.root.resolve()
    manifest_path = args.manifest.resolve()
    pretrained_path = args.pretrained.resolve() if args.pretrained is not None else None
    if pretrained_path is not None and not pretrained_path.is_dir():
        parser.error(f'pretrained model directory does not exist: {pretrained_path}')
    teacher_records = [dict(path=str(path), files_sha256=directory_hashes(path))
                       for path in teacher_paths]
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    expected_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    from collections import Counter
    split_counts = {s: dict(Counter(r['label'] for r in manifest['samples'] if r['split'] == s))
                    for s in ('train', 'validation', 'test')}
    dataset_context = dict(manifest_sha256=expected_manifest_sha256,
                           split_method=manifest.get('split_method'), class_counts=split_counts,
                           evaluation_note=manifest.get('evaluation_note'),
                           manifest=str(manifest_path), exploratory=True)
    if root.exists() and any(root.iterdir()):
        raise ValueError('Experiment root must be new/empty; do not overwrite jobs')
    root.mkdir(parents=True, exist_ok=True)
    full = args.mode == 'full'
    state = {'status': 'running', 'message': (f'准备全参数三种子训练；仅浮点，按{args.checkpoint_metric}选模型。' if full else '准备 E0 / E1 对照；仅浮点训练，测试暂不解封。'),
             'completed_runs': [], 'quantization_performed': False, 'validated_for_business': False,
             'head_epochs': 0 if full else 60, 'finetune_epochs': 0 if full else 30, 'test_evaluated': False,
             'dataset_context': dataset_context, 'manager_pid': os.getpid(),
             'pretrained': str(pretrained_path) if pretrained_path is not None else None,
             'training_mode': args.mode, 'full_epochs': args.full_epochs if full else None,
             'full_lr_schedule': args.full_lr_schedule if full else None,
             'full_optimizer': args.full_optimizer if full else None,
             'full_weight_decay': args.full_weight_decay if full else None,
             'full_class_weight': args.full_class_weight if full else None,
             'checkpoint_metric': args.checkpoint_metric if full else None,
             'augmentation_profile': args.augmentation_profile if full else None,
             'personal_sampling_factor': args.personal_sampling_factor if full else None,
             'ema_decay': args.ema_decay if full else None,
             'teacher_models': teacher_records if full else [],
             'distillation_temperature': args.distillation_temperature if full else None,
             'distillation_alpha': args.distillation_alpha if full else None,
             'dropout': args.dropout,
             'defer_final_test': args.defer_final_test,
             'dashboard_url': f'http://127.0.0.1:{args.dashboard_port}/'}
    run_spec = dict(dataset_context=dataset_context,
           head_epochs=0 if full else 60, finetune_epochs=0 if full else 30, batch_size=16, patience=5,
           initial_seed=20260918, additional_seeds=[42, 20260919],
           head_lr=None if full else .001, finetune_lr=None if full else .00001, unfreeze_layers=None if full else 12,
           training_mode=args.mode, full_epochs=args.full_epochs if full else None,
           pretrained=str(pretrained_path) if pretrained_path is not None else None,
           optimizer=args.full_optimizer if full else None, dropout=args.dropout, full_lr=args.full_lr if full else None,
           full_optimizer=args.full_optimizer if full else None,
           full_weight_decay=args.full_weight_decay if full else None,
           full_class_weight=args.full_class_weight if full else None,
           checkpoint_metric=args.checkpoint_metric if full else None,
           augmentation_profile=args.augmentation_profile if full else None,
           personal_sampling_factor=args.personal_sampling_factor if full else None,
           ema_decay=args.ema_decay if full else None,
           teacher_models=teacher_records if full else [],
           distillation_temperature=args.distillation_temperature if full else None,
           distillation_alpha=args.distillation_alpha if full else None,
           full_lr_schedule=args.full_lr_schedule if full else None,
           warmup_start_lr=args.warmup_start_lr if full else None,
           warmup_min_lr=args.warmup_min_lr if full else None,
           early_stopping_start_epoch=args.early_stopping_start_epoch if full else None,
           early_stopping_min_delta=args.early_stopping_min_delta if full else None,
           early_stopping_patience=args.early_stopping_patience if full else 5,
           defer_final_test=args.defer_final_test,batchnorm_frozen=not full,
           quantization_performed=False,installed=False,dashboard_url=state['dashboard_url'])
    atomic(root / 'run_spec.json', run_spec)
    expected_run_spec_sha256=hashlib.sha256((root/'run_spec.json').read_bytes()).hexdigest()
    state['run_spec_sha256']=expected_run_spec_sha256

    def assert_run_spec_unchanged():
        actual=hashlib.sha256((root/'run_spec.json').read_bytes()).hexdigest()
        if actual != expected_run_spec_sha256:
            raise ValueError('run_spec.json changed while manager was running; hot configuration changes are rejected')

    def publish(**values):
        state.update(values, updated_at=datetime.now(timezone.utc).isoformat())
        atomic(root / 'experiment_status.json', state)

    def run(experiment, seed):
        name = f'{experiment}-seed{seed}'
        output = root / name
        assert_run_spec_unchanged()
        if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != expected_manifest_sha256:
            raise ValueError('Dataset manifest changed before experiment launch')
        if any(directory_hashes(Path(record['path'])) != record['files_sha256']
               for record in teacher_records):
            raise ValueError('Teacher SavedModel changed before experiment launch')
        publish(active_run=name, message=(f'正在训练 {name}：全部参数及BN参与训练，上限{args.full_epochs}轮，保留早停；不以测试选模型。' if full else f'正在训练 {name}：冻结上限60 / 微调上限30，保留早停；测试封存。'))
        # The trainer requires an empty directory, so console log lives in root
        # until the subprocess creates its output directory itself.
        log = root / f'{name}.console.log'
        command = [sys.executable, '-u', str(Path(__file__).with_name('train_random_split.py')),
                   str(args.manifest.resolve()), '--output', str(output), '--experiment', experiment,
                   '--seed', str(seed), '--head-epochs', '60', '--finetune-epochs', '30', '--batch-size', '16',
                   '--dropout', str(args.dropout)]
        if pretrained_path is not None:
            command += ['--pretrained', str(pretrained_path)]
        if full:
            command += ['--full-epochs',str(args.full_epochs),'--full-lr',str(args.full_lr),
                        '--full-optimizer',args.full_optimizer,
                        '--full-weight-decay',str(args.full_weight_decay),
                        '--full-class-weight',args.full_class_weight,
                        '--checkpoint-metric',args.checkpoint_metric,
                        '--augmentation-profile',args.augmentation_profile,
                        '--personal-sampling-factor',str(args.personal_sampling_factor),
                        '--ema-decay',str(args.ema_decay),
                        '--full-lr-schedule',args.full_lr_schedule,
                        '--warmup-start-lr',str(args.warmup_start_lr),'--warmup-min-lr',str(args.warmup_min_lr),
                        '--early-stopping-start-epoch',str(args.early_stopping_start_epoch),
                        '--early-stopping-min-delta',str(args.early_stopping_min_delta),
                        '--early-stopping-patience',str(args.early_stopping_patience)]
            for teacher_path in teacher_paths:
                command += ['--teacher-model',str(teacher_path)]
            command += ['--distillation-temperature',str(args.distillation_temperature),
                        '--distillation-alpha',str(args.distillation_alpha)]
        with log.open('w', encoding='utf-8') as stream:
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
            publish(training_pid=process.pid)
            code = process.wait()
        if output.exists():
            shutil_copy(log, output / 'console.log')
        if code:
            raise RuntimeError(f'{name} failed, exit {code}; see {log}')
        report = json.loads((output / 'training_report.json').read_text(encoding='utf-8'))
        if report['dataset']['manifest_sha256'] != expected_manifest_sha256:
            raise ValueError('Dataset manifest changed between experiments; comparison rejected')
        assert not report['quantization_performed'] and not report['test_evaluated']
        if full:
            assert report['selected_stage'] == 'full'
            assert report['trainability']['all_gradient_parameters_trainable']
            assert report['trainability']['batchnorm_training_enabled']
            assert not report['batchnorm_unchanged']
        assert not list(output.rglob('*.tflite')) and not (output / 'c_backend').exists()
        state['completed_runs'].append({'run_id': name, 'experiment': experiment, 'seed': seed,
                                       'selected_val_loss': report['selected_val_loss'],
                                       'checkpoint_best_epoch': report.get('checkpoint_best_epoch'),
                                       'checkpoint_selection': report.get('checkpoint_selection'),
                                       'validation': report['validation'], 'selected_stage': report['selected_stage'],
                                       'distillation': report.get('distillation'),
                                       'source_groups': {'validation': report.get('source_groups', {}).get('validation', {})}})
        publish()
        return report

    try:
        publish()
        if full:
            selected_experiment = 'FULL'
            run('FULL', 20260918)
        else:
            e0 = run('E0', 20260918)
            e1 = run('E1', 20260918)
            selected_experiment = 'E1' if e1['selected_val_loss'] < e0['selected_val_loss'] else 'E0'
        publish(selected_experiment=selected_experiment,
                message=(f'{args.checkpoint_metric}规则固定 {selected_experiment}，追加两个种子复跑；不使用测试选配置。'
                         if full else f'验证损失选定 {selected_experiment}，追加两个种子复跑；不使用测试选配置。'))
        run(selected_experiment, 42)
        run(selected_experiment, 20260919)
        candidates = [r for r in state['completed_runs'] if r['experiment'] == selected_experiment]
        assert_run_spec_unchanged()
        if full and args.checkpoint_metric == 'val_accuracy':
            def accuracy_key(row):
                metrics = row['checkpoint_selection']['metrics']
                return (-int(metrics['val_correct_count']), -float(metrics['val_macro_f1']),
                        float(metrics['val_loss']), row['run_id'])
            selected = min(candidates, key=accuracy_key)
            selection_rule = ('maximum validation correct_count, then macro_f1, then lower unweighted '
                              'cross-entropy, then run_id lexical tie-break; no test selection')
        else:
            selected = min(candidates, key=lambda r: (r['selected_val_loss'], r['run_id']))
            selection_rule = 'minimum unweighted validation cross-entropy, then run_id lexical tie-break; no test selection'
        name = selected['run_id']
        output = root / name
        # Persist model choice before test data is scored.
        chosen_report = json.loads((output / 'training_report.json').read_text(encoding='utf-8'))
        frozen = {'selected_run': name, 'selected_experiment': selected_experiment,
                  'selection_rule': selection_rule,
                  'checkpoint_metric': args.checkpoint_metric if full else 'val_loss',
                  'frozen_at': datetime.now(timezone.utc).isoformat(),
                  'weights_sha256': hashlib.sha256((output / 'best.weights.h5').read_bytes()).hexdigest(),
                  'saved_model_files_sha256': chosen_report['model_files_sha256'],
                  'manifest_sha256': chosen_report['dataset']['manifest_sha256'],
                  'code_sha256': chosen_report['code_sha256']}
        atomic(root / 'frozen_candidate.json', frozen)
        if args.defer_final_test:
            publish(selected_run=name,status='validation_completed',active_run=None,training_pid=None,
                    test_evaluated=False,
                    message=f'验证选择已完成并冻结候选 {name}；按配置保持测试集封存。')
            return
        publish(selected_run=name, status='evaluating', message=f'候选 {name} 已选定并记录哈希，正在进行一次浮点探索测试；无量化。')
        assert_run_spec_unchanged()
        command = [sys.executable, '-u', str(Path(__file__).with_name('train_random_split.py')),
                   str(args.manifest.resolve()), '--output', str(output), '--evaluate-final', '--batch-size', '16']
        with (root / 'final-evaluation.log').open('w', encoding='utf-8') as log:
            code = subprocess.call(command, stdout=log, stderr=subprocess.STDOUT)
        if code:
            raise RuntimeError(f'Final evaluation failed: {code}')
        final = json.loads((output / 'final_test_report.json').read_text(encoding='utf-8'))
        publish(status='completed', active_run=None, training_pid=None, test_evaluated=True,
                final_test=final['metrics'], source_groups=final['source_groups'],
                message=f'浮点训练完成；候选 {name}；随机测试 {final["metrics"]["accuracy"]:.1%}，此结果不是独立会话实板验收。未量化或安装。')
    except BaseException as error:
        publish(status='failed', message=f'{type(error).__name__}: {error}')
        raise


def shutil_copy(source, target):
    import shutil
    shutil.copy2(source, target)


if __name__ == '__main__':
    main()
