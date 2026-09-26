"""Report recorded campaign results, never predict or train."""
import argparse
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.output.exists():
        raise FileExistsError('preserve reports')
    state = read(root / 'campaign_state.json')
    frozen = read(root / 'final_selection.json')
    audit = read(root / frozen['selected_round'] / 'final_parameter_audit.json')
    if state['status'] != 'completed' or audit['status'] != 'passed':
        raise ValueError('complete and audit before reporting')
    spec = read(root / frozen['selected_round'] / 'run_spec.json')
    dataset = spec['dataset_context']
    if dataset['manifest_sha256'] != frozen['manifest_sha256']:
        raise ValueError('run specification and frozen selection use different manifests')
    class_counts = dataset['class_counts']
    split_counts = {split: sum(class_counts[split].values())
                    for split in ('train', 'validation', 'test')}
    sample_count = sum(split_counts.values())
    chosen_dir = root / frozen['selected_round'] / frozen['selected_run']
    final = read(chosen_dir / 'final_test_report.json')
    training = read(chosen_dir / 'training_report.json')
    metrics = final['metrics']
    accuracy_selection = state.get('selection_metric', 'val_loss') == 'val_accuracy'
    reference_count = sum(bool(row.get('reused_baseline')) for row in state['rounds'])
    checkpoint_note = ('- 保存验证准确率最高的权重；同准确率依次比较宏F1、较低交叉熵、更早epoch。早停仍独立监控val_loss；无量化、C导出、安装、板卡操作。'
                       if accuracy_selection else '- 保存全程最低验证损失权重；无量化、C导出、安装、板卡操作。')
    selection_note = ('主排名规则训练前固定为三种子平均所选验证准确率，先满足相对本轮基线的保护条件：宏F1下降不超过0.01、本人FIST/PALM各自平均召回不下降；并列依次取更高宏F1、更低交叉熵、更早方案。配置内按验证准确率、宏F1、较低交叉熵、run_id选种子。不使用测试集挑模型。'
                      if accuracy_selection else '主排名规则预先固定为三种子平均最优验证交叉熵；相同保留较早方案，方案内部以最低验证损失选种子。宏F1与逐类召回率用于解释，不事后更换排名规则。')
    lines = ['# 200轮训练与最多三轮改进：实际结果', '',
             '本报告仅引用已保存的真实训练/验证日志与最终一次测试报告，不重复评分。', '',
             '## 固定条件', '',
             f"- 数据{sample_count}张：{split_counts['train']}训练/{split_counts['validation']}验证/{split_counts['test']}测试；划分方式：`{dataset.get('split_method', '未记录')}`；数据、标签、划分及预处理未改变。",
             f"- 全参数训练，{training['trainability']['trainable_parameters']}个梯度参数；{training['batchnorm_layer_count']}层BN训练开启，{len(training['changed_backbone_layers'])}个主干权重层实际更新。",
             '- 每个新增方案三个相同种子串行运行，最多200轮；151轮起启用早停，delta=0.001、patience=15。',
             (f'- 本轮引用{reference_count}组历史三种子基线，不重复训练、不计为本轮新fit；reference_provenance.json保留原路径及哈希，历史test已使用。' if reference_count else '- 本轮基线与候选均为实际新训练。'),
             checkpoint_note, '',
             '## 方案比较（只用验证集）', '',
             '| 轮次 | 方案 | 平均验证损失 | 平均验证准确率 | 平均宏F1 |',
             '|---|---|---:|---:|---:|']
    for row in state['rounds']:
        lines.append(f"| {row['name']} | {row['recipe']} | {row['mean_val_loss']:.6f} | {row['mean_val_accuracy']:.2%} | {row['mean_val_macro_f1']:.4f} |")
    lines += ['', selection_note, '',
              '## 各轮证据与结果', '']
    if state.get('failed_attempts'):
        lines += ['技术重试说明：', '']
        for attempt in state['failed_attempts']:
            name = attempt.get('name', '未命名尝试')
            failure = attempt.get('failure', '未记录失败原因')
            lines.append(f"- `{name}`：{failure}。该尝试标记为技术失败，不计入配置比较，也不用于选模。")
        lines.append('')
    for row in state['rounds']:
        lines += [f"### {row['name']}", '', row['reason'], '',
                  '| 种子 | 实际轮数 | 选定轮数 | 所选权重验证损失 | 验证准确率 | 宏F1 | 停止原因 |',
                  '|---|---:|---:|---:|---:|---:|---|']
        for path in sorted((root / row['name']).glob('FULL-*/training_report.json')):
            report = read(path)
            detail = report['stage_details']['full']
            selected_epoch = detail.get('checkpoint_best_epoch', detail['best_epoch'])
            lines.append(f"| {report['config']['seed']} | {detail['completed_epochs']} | {selected_epoch} | {report['selected_val_loss']:.6f} | {report['validation']['accuracy']:.2%} | {report['validation']['macro_f1']:.4f} | {detail['stopping_reason']} |")
        lines += ['', f"决策：{row['decision']}。", '']
    lines += ['## 最终候选与单次测试', '',
              f"最终方案：`{frozen['selected_round']}`；模型：`{frozen['selected_run']}`。", '',
              f"测试正确 {metrics['sample_count']-metrics['errors']}/{metrics['sample_count']}，准确率 **{metrics['accuracy']:.2%}**，宏F1 **{metrics['macro_f1']:.4f}**，平均类别召回率 {metrics['balanced_accuracy']:.2%}。", '',
              '| 类别 | 数量 | 召回率 | 精确率 | F1 |', '|---|---:|---:|---:|---:|']
    for label, result in metrics['per_class'].items():
        lines.append(f"| {label} | {result['support']} | {result['recall']:.2%} | {result['precision']:.2%} | {result['f1']:.4f} |")
    if 'target_accuracy' in state:
        target = state['target_accuracy']
        verdict = '达到' if metrics['accuracy'] >= target else '未达到'
        lines += ['', f"本轮单模型整体测试目标 {target:.0%}：**{verdict}**。该结论仅指现有测试集点估计，不是独立验收。", '']
    lines += ['', '## 产物与限制', '',
              f"- SavedModel：`{chosen_dir / 'saved_model'}`", f"- 权重SHA256：`{frozen['candidate']['weights_sha256']}`", f"- manifest SHA256：`{frozen['manifest_sha256']}`", f"- 冻结选择：`{root / 'final_selection.json'}`", f"- 最终审计：`{root / frozen['selected_round'] / 'final_parameter_audit.json'}`", '',
              '多agent将实现、原始日志核查、独立分析与主agent决策分开；只有主agent启动训练，未并发争用训练资源。', '',
              f"本次改进过程中未评分测试集，最终方案冻结后只评分一次；但历史数据和测试指标曾用于数据开发与扩充，v5又是图片级重新划分，相关帧可能跨越训练、验证和测试集。因此成绩只能是探索结果，不是独立未见会话、新人泛化或实板识别验收。{split_counts['validation']}张验证集仍有限，多次方案选择也有验证集适配风险。", '',
              '下一步需由用户决定是否开展独立场景验证及后续部署；本次未量化或烧录。', '']
    args.output.write_text('\n'.join(lines), encoding='utf-8')
    print(args.output)


if __name__ == '__main__':
    main()
