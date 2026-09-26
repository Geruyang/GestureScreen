"""Copy an audited historical validation baseline with explicit provenance; never train."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import statistics
from datetime import datetime, timezone

from run_float_experiments import atomic


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def initialize(source, root, manifest):
    source, root = source.resolve(), root.resolve()
    if root.exists():
        raise FileExistsError('New campaign root must not exist')
    sha = digest(manifest)
    audit = read(source / 'full_parameter_audit.json')
    if audit['status'] != 'passed':
        raise ValueError('Historical validation audit failed')
    old_state = read(source / 'experiment_status.json')
    reports = []
    for seed in (20260918, 42, 20260919):
        directory = source / f'FULL-seed{seed}'
        report = read(directory / 'training_report.json')
        if report['dataset']['manifest_sha256'] != sha or report['config']['checkpoint_metric'] != 'val_accuracy':
            raise ValueError('Baseline data or selection contract mismatch')
        if report['validation']['sample_count'] != 200 or report['config']['seed'] != seed:
            raise ValueError('Incomplete baseline')
        if digest(directory / 'best.weights.h5') != report['best_weights_sha256']:
            raise ValueError('Baseline weights changed')
        for name, expected in report['model_files_sha256'].items():
            if digest(directory / 'saved_model' / name) != expected:
                raise ValueError('Baseline SavedModel changed')
        for name, expected in report['code_sha256'].items():
            if digest(source / 'source_snapshot' / name) != expected:
                raise ValueError('Baseline source changed')
        reports.append(report)
    name = 'round0-reference'
    destination = root / name
    # Deliberately do not copy historical final test or final-test audit.
    shutil.copytree(source, destination,
                    ignore=shutil.ignore_patterns('final_test_report.json', 'final_parameter_audit.json'))
    copied_hashes = {p.relative_to(destination).as_posix(): digest(p)
                     for p in destination.rglob('*') if p.is_file()}
    if any(digest(source / rel) != value for rel, value in copied_hashes.items()):
        raise ValueError('Baseline copy mismatch')
    provenance = dict(original_round=str(source), manifest_sha256=sha,
                      imported_at=datetime.now(timezone.utc).isoformat(),
                      new_fit_performed=False, historical_test_used=bool(old_state['test_evaluated']),
                      note='Historical reports, weights, SavedModels, logs and source snapshot retained byte-for-byte; config.output refers to original runs. Only copied experiment_status is marked as a reference, with its original hash retained below. Not new training and not an unseen dataset.',
                      original_files_sha256=copied_hashes)
    atomic(destination / 'reference_provenance.json', provenance)
    state = dict(old_state)
    state.pop('final_test', None)
    state.pop('source_groups', None)
    state.update(status='validation_completed', test_evaluated=False, active_run=None,
                 historical_test_evaluated=bool(old_state['test_evaluated']),
                 reused_baseline=True, manager_pid=None,
                 message='历史验证基线引用，未重新训练；原模型历史测试已使用，当前副本未重新评分。')
    atomic(destination / 'experiment_status.json', state)
    row = dict(name=name, recipe='Historical R3: flip + personal factor2 (reused, no new fit)',
               reason='Audited historical three-seed validation baseline, not newly trained.',
               status='validation_completed', reused_baseline=True, reference_root=str(source),
               selected_run=old_state['selected_run'],
               mean_val_loss=statistics.mean(r['selected_val_loss'] for r in reports),
               mean_val_accuracy=statistics.mean(r['validation']['accuracy'] for r in reports),
               mean_val_macro_f1=statistics.mean(r['validation']['macro_f1'] for r in reports),
               val_correct_total=sum(200-r['validation']['errors'] for r in reports),
               personal_correct_total={}, mean_personal_recall={}, eligible=True,
               decision='历史基线，未重新训练')
    for label, support in (('FIST', 8), ('PALM', 2)):
        items = [r['source_groups']['validation']['personal_board_capture']['per_class'][label] for r in reports]
        if any(item['support'] != support for item in items):
            raise ValueError('Personal validation support changed')
        row['personal_correct_total'][label] = sum(item['support']-item['errors'] for item in items)
        row['mean_personal_recall'][label] = statistics.mean(item['recall'] for item in items)
    campaign = dict(status='reviewing', selection_metric='val_accuracy', max_improvements=3,
                    target_accuracy=.85, target_scope='single-model exploratory final test; not independent acceptance',
                    selection_guards=dict(macro_f1_max_drop=.01, personal_recall_no_drop=['FIST','PALM'],
                                          reference='audited historical R3, 15/24 FIST and 6/6 PALM'),
                    rounds=[row], active_round=name, best_round=name,
                    message='历史验证基线已核验引用，未重新训练；准备最多三项新改进。')
    atomic(root / 'campaign_state.json', campaign)
    return campaign


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(initialize(args.source, args.root, args.manifest), ensure_ascii=False, indent=2))
