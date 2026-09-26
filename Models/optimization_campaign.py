"""Bounded host-only experiment bookkeeping. Does not fit or score models."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import statistics

from run_float_experiments import atomic


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def select_rounds(state):
    """Apply the campaign's predeclared rule, never consulting test metrics."""
    rows = state['rounds']
    if state.get('selection_metric', 'val_loss') == 'val_loss':
        return min(rows, key=lambda r: r['mean_val_loss'])
    baseline = rows[0]
    tolerance = state['selection_guards']['macro_f1_max_drop']
    for row in rows:
        reasons = []
        if row['mean_val_macro_f1'] < baseline['mean_val_macro_f1'] - tolerance:
            reasons.append('macro-F1 below baseline guard')
        for label in ('FIST', 'PALM'):
            if row['personal_correct_total'][label] < baseline['personal_correct_total'][label]:
                reasons.append(f'personal {label} recall below baseline guard')
        row.update(eligible=not reasons, guard_failures=reasons)
    eligible = [row for row in rows if row['eligible']]
    return min(eligible, key=lambda r: (-r['val_correct_total'], -r['mean_val_macro_f1'], r['mean_val_loss']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'retry', 'record', 'freeze', 'finish'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--name')
    parser.add_argument('--recipe')
    parser.add_argument('--reason')
    parser.add_argument('--selection-metric', choices=('val_loss', 'val_accuracy'), default=None,
                        help='Set only at campaign creation; immutable thereafter')
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / 'campaign_state.json'
    state = read(state_path) if state_path.exists() else dict(status='preparing', rounds=[], max_improvements=3)
    if not state_path.exists():
        state['selection_metric'] = args.selection_metric or 'val_loss'
        if state['selection_metric'] == 'val_accuracy':
            state['selection_guards'] = dict(macro_f1_max_drop=.01,
                                            personal_recall_no_drop=['FIST', 'PALM'],
                                            reference='first completed three-seed baseline')
    elif args.selection_metric and args.selection_metric != state.get('selection_metric', 'val_loss'):
        raise ValueError('selection rule cannot change within a campaign')
    if args.action in ('prepare', 'retry'):
        if not args.name or Path(args.name).name != args.name or not args.recipe or not args.reason:
            parser.error('prepare needs a direct-child name, recipe, and evidence-based reason')
        if len(state['rounds']) >= 4 or state.get('status') in ('frozen', 'completed'):
            raise ValueError('campaign bound reached or candidate already frozen')
        if args.action == 'retry':
            previous = state['rounds'][-1]
            failure = read(root / previous['name'] / 'experiment_status.json')
            if failure['status'] != 'failed' or failure['test_evaluated']:
                raise ValueError('retry is only for a failed unscored technical attempt')
            previous.update(status='technical_failed', failure=failure['message'])
            state.setdefault('failed_attempts', []).append(previous)
            state['rounds'].pop()
        if any(r['status'] != 'validation_completed' for r in state['rounds']):
            raise ValueError('previous round is not completed')
        if (root / args.name).exists():
            raise FileExistsError('preserve existing round')
        source = root / 'sources' / args.name
        source.mkdir(parents=True, exist_ok=False)
        for path in Path(__file__).parent.glob('*.py'):
            shutil.copy2(path, source / path.name)
        state['rounds'].append(dict(name=args.name, recipe=args.recipe, reason=args.reason, status='running',
                                    prepared_at=datetime.now(timezone.utc).isoformat()))
        state.update(active_round=args.name, status='running', message=f'{args.name}：{args.recipe}。{args.reason}')
    elif args.action == 'record':
        row = state['rounds'][-1]
        directory = root / row['name']
        result = read(directory / 'experiment_status.json')
        if result['status'] != 'validation_completed' or result['test_evaluated']:
            raise ValueError('round must complete with test unscored')
        if list(directory.glob('*/final_test_report.json')):
            raise ValueError('test was scored during improvement')
        source = root / 'sources' / row['name']
        for run in result['completed_runs']:
            report = read(directory / run['run_id'] / 'training_report.json')
            if report['config'].get('checkpoint_metric', 'val_loss') != state.get('selection_metric', 'val_loss'):
                raise ValueError('checkpoint rule does not match campaign selection rule')
            for name, sha in report['code_sha256'].items():
                if hashlib.sha256((source / name).read_bytes()).hexdigest() != sha:
                    raise ValueError('training code changed after round was prepared')
        if not (directory / 'source_snapshot').exists():
            shutil.copytree(source, directory / 'source_snapshot')
        row.update(status='validation_completed', selected_run=result['selected_run'],
                   mean_val_loss=statistics.mean(r['selected_val_loss'] for r in result['completed_runs']),
                   mean_val_accuracy=statistics.mean(r['validation']['accuracy'] for r in result['completed_runs']),
                   mean_val_macro_f1=statistics.mean(r['validation']['macro_f1'] for r in result['completed_runs']))
        if state.get('selection_metric') == 'val_accuracy':
            reports = [read(directory / r['run_id'] / 'training_report.json') for r in result['completed_runs']]
            if len(reports) != 3 or {r['config']['seed'] for r in reports} != {20260918, 42, 20260919}:
                raise ValueError('accuracy campaign requires all three fixed seeds')
            supports = [r['validation']['sample_count'] for r in reports]
            if supports != [200, 200, 200]:
                raise ValueError('accuracy campaign must use the unchanged full 200-image validation split')
            row['val_correct_total'] = sum(r['validation']['sample_count'] - r['validation']['errors'] for r in reports)
            row['personal_correct_total'] = {}
            for label, expected_support in (('FIST', 8), ('PALM', 2)):
                items = [r['source_groups']['validation']['personal_board_capture']['per_class'][label] for r in reports]
                if any(item['support'] != expected_support for item in items):
                    raise ValueError('personal validation support changed')
                row['personal_correct_total'][label] = sum(item['support'] - item['errors'] for item in items)
            row['mean_personal_recall'] = {
                label: statistics.mean(r['source_groups']['validation']['personal_board_capture']['per_class'][label]['recall'] for r in reports)
                for label in ('FIST', 'PALM')}
        best = select_rounds(state)
        for candidate in state['rounds']:
            candidate['decision'] = ('当前最优方案' if best is candidate else
                                     '未通过基线保护条件，保留记录' if candidate.get('eligible') is False else
                                     f'未优于 {best["name"]}，保留记录')
        criterion = '三种子平均验证准确率及预定保护条件' if state.get('selection_metric') == 'val_accuracy' else '三种子平均验证损失'
        state.update(best_round=best['name'], status='reviewing', message=f'{row["name"]}完成：按{criterion}，当前最优为{best["name"]}；本轮测试未评分。')
    elif args.action == 'freeze':
        if state['status'] != 'reviewing' or (root / 'final_selection.json').exists():
            raise ValueError('finish validation reviews before freezing; never overwrite selection')
        best = select_rounds(state)
        for row in state['rounds']:
            audit = read(root / row['name'] / 'full_parameter_audit.json')
            if audit['status'] != 'passed' or audit.get('test_evaluated') is not False:
                raise ValueError('round lacks clean validation audit')
        chosen = read(root / best['name'] / 'frozen_candidate.json')
        rule = ('maximum mean validation accuracy over three seeds subject to baseline macro-F1 and personal FIST/PALM recall guards; ties higher macro-F1, lower CE, earlier round; within round accuracy, F1, lower CE, run_id'
                if state.get('selection_metric') == 'val_accuracy' else
                'minimum mean validation loss over three fixed seeds; ties retain earlier round; within round minimum validation loss')
        frozen = dict(selected_round=best['name'], selected_run=chosen['selected_run'],
                      rule=rule, selection_metric=state.get('selection_metric', 'val_loss'),
                      selection_guards=state.get('selection_guards'),
                      frozen_at=datetime.now(timezone.utc).isoformat(), candidate=chosen,
                      rounds=state['rounds'], manifest_sha256=chosen['manifest_sha256'],
                      test_use_note='one final score in this campaign; historical tests existed, exploratory only')
        atomic(root / 'final_selection.json', frozen)
        state.update(status='frozen', active_round=best['name'], message='改进结束，最终方案与权重哈希已冻结，接下来只评分最终候选一次。')
    else:
        if state['status'] != 'frozen':
            raise ValueError('candidate must be frozen before final scoring')
        frozen = read(root / 'final_selection.json')
        directory = root / frozen['selected_round']
        final = read(directory / frozen['selected_run'] / 'final_test_report.json')
        all_tests = list(root.glob('round*/*/final_test_report.json'))
        if len(all_tests) != 1 or final['model_files_sha256'] != frozen['candidate']['saved_model_files_sha256']:
            raise ValueError('not a single frozen-model score')
        if final['manifest_sha256'] != frozen['manifest_sha256']:
            raise ValueError('scored a different dataset')
        if final['quantization_performed'] or final['validated_for_business']:
            raise ValueError('final report violates host-only float scope')
        if list(root.rglob('*.tflite')) or list(root.rglob('c_backend')):
            raise ValueError('unexpected quantized/exported artifact')
        if datetime.fromisoformat(final['evaluated_at']) <= datetime.fromisoformat(frozen['frozen_at']):
            raise ValueError('test precedes campaign selection')
        result = read(directory / 'experiment_status.json')
        result.update(status='completed', test_evaluated=True, final_test=final['metrics'], source_groups=final['source_groups'],
                      message='全部改进完成，最终候选已评分；仅浮点探索，未量化、未部署。')
        atomic(directory / 'experiment_status.json', result)
        state.update(status='completed', final_test=final['metrics'], message='改进与单次最终评分已完成；未量化、未安装、未操作板卡。')
    state['updated_at'] = datetime.now(timezone.utc).isoformat()
    atomic(state_path, state)
    print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
