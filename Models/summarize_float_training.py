"""Verify a completed experiment and write its factual Chinese handoff."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Summary output must be new; preserve historical results')
    root = args.root.resolve()
    state = json.loads((root / 'experiment_status.json').read_text(encoding='utf-8'))
    full = state.get('training_mode') == 'full'
    assert state['status'] == 'completed' and state['test_evaluated']
    freeze = json.loads((root / 'frozen_candidate.json').read_text(encoding='utf-8'))
    chosen = root / state['selected_run']
    report = json.loads((chosen / 'training_report.json').read_text(encoding='utf-8'))
    final = json.loads((chosen / 'final_test_report.json').read_text(encoding='utf-8'))
    assert freeze['selected_run'] == state['selected_run']
    assert freeze['saved_model_files_sha256'] == final['model_files_sha256'] == report['model_files_sha256']
    assert freeze['manifest_sha256'] == final['manifest_sha256']
    assert freeze['frozen_at'] < final['evaluated_at']
    assert len(list(root.glob('*/final_test_report.json'))) == 1
    assert not list(root.rglob('*.tflite')) and not list(root.rglob('c_backend'))
    for file, expected in freeze['saved_model_files_sha256'].items():
        assert hashlib.sha256((chosen / 'saved_model' / file).read_bytes()).hexdigest() == expected
    for row in state['completed_runs']:
        run = root / row['run_id']
        data = json.loads((run / 'training_report.json').read_text(encoding='utf-8'))
        if full:
            assert data['trainability']['all_gradient_parameters_trainable']
            assert data['trainability']['batchnorm_training_enabled']
            assert not data['batchnorm_unchanged']
            assert data['batchnorm_before_sha256'] != data['batchnorm_after_sha256']
            assert set(data['history']) == {'full'}
        else:
            assert data['batchnorm_before_sha256'] == data['batchnorm_after_sha256']
            assert data['batchnorm_unchanged']
        assert not data['quantization_performed'] and not data['c_export_performed'] and not data['installed']
        assert data['dataset']['manifest_sha256'] == freeze['manifest_sha256']
    metric = final['metrics']
    dataset = report['dataset']
    validation_counts = dataset['counts']['validation']
    lines = ['# 本轮浮点训练结果', '',
             '状态：全部预定实验与一次最终随机测试已完成；未量化、未导出 TFLite／C 参数、未安装或烧录。', '',
             f'训练网页：[本机训练现场]({state.get("dashboard_url", "http://127.0.0.1:8770/")})。', '',
             '## 配置与运行', '',
             (f'数据保持560／80／160；从第一轮起所有可训练参数参与训练，无冻结或局部解冻阶段；单阶段上限{state["full_epochs"]} epoch，Adam 1e-4、batch16、早停patience=5。BatchNorm γ/β参与优化，moving mean/variance按训练批次更新。' if full else '数据保持 560／80／160；冻结上限 60 epoch、微调上限 30 epoch，早停 patience=5；实际轮数由早停或上限决定。'), '',
             f'划分方式：`{dataset.get("split_method", "image-wise random split")}`；清单SHA：`{dataset["manifest_sha256"]}`。', '',
             '| 运行 | 全参数实际轮数 | 最佳Epoch | 所选阶段 | 验证损失 | 验证准确率 | 验证 Macro-F1 |' if full else '| 运行 | 冻结实际轮数 | 微调实际轮数 | 所选阶段 | 验证损失 | 验证准确率 | 验证 Macro-F1 |',
             '| --- | ---: | ---: | --- | ---: | ---: | ---: |']
    for row in state['completed_runs']:
        data = json.loads((root / row['run_id'] / 'training_report.json').read_text(encoding='utf-8'))
        histories = data['history']
        count1 = len(histories['full']['loss']) if full else len(histories['head']['loss'])
        count2 = data['stage_details']['full']['best_epoch'] if full else len(histories.get('finetune', {}).get('loss', []))
        lines.append(f'| {row["run_id"]} | {count1} | {count2} | {row["selected_stage"]} | {row["selected_val_loss"]:.6f} | {row["validation"]["accuracy"]:.2%} | {row["validation"]["macro_f1"]:.4f} |')
    lines += ['', ('只运行预先指定的全参数配置和三个种子20260918／42／20260919；不加类权重，仅水平翻转并同步交换左右标签。只按最低无权重验证交叉熵选最终候选，不以测试集选模型。' if full else 'E0／E1 同种子先比较最低无权重验证损失，再对选定配置复跑两个种子；最终按最低验证损失选定模型。E1同时变化类权重和微调，是候选对照，不是单因素消融。'), '',
              '## 最终候选与测试结果', '',
              f'所选模型：`{state["selected_run"]}`。训练结束后先记录候选选择和文件哈希，再评分测试集；此处的文件封存不是训练层冻结。只有该候选生成一份最终测试报告。', '',
              f'- 随机测试：{metric["sample_count"]-metric["errors"]}／{metric["sample_count"]} 正确，Accuracy **{metric["accuracy"]:.2%}**，Macro-F1 **{metric["macro_f1"]:.4f}**，Balanced Accuracy **{metric["balanced_accuracy"]:.2%}**。',
              f'- 验证集：Accuracy {report["validation"]["accuracy"]:.2%}，Macro-F1 {report["validation"]["macro_f1"]:.4f}。', '',
              '| 类别 | 测试数量 | 错误数量 | Precision | Recall | F1 |',
              '| --- | ---: | ---: | ---: | ---: | ---: |']
    for name, row in metric['per_class'].items():
        lines.append(f'| {name} | {row["support"]} | {row["errors"]} | {row["precision"]:.2%} | {row["recall"]:.2%} | {row["f1"]:.4f} |')
    lines += ['', '| 来源 | 测试数量 | 正确数量 | Accuracy |', '| --- | ---: | ---: | ---: |']
    for name, row in final['source_groups'].items():
        lines.append(f'| {name} | {row["sample_count"]} | {row["sample_count"]-row["errors"]} | {row["accuracy"]:.2%} |')
    achieved = metric['accuracy'] >= .9 and metric['macro_f1'] >= .85
    lines += ['', '## 结论与边界', '',
              ('达到方案中随机离线总体指标目标，但仍未通过独立会话和实板验收。' if achieved else '未达到方案中的 Accuracy≥90%、Macro-F1≥0.85 目标。训练流程已完成，但模型识别效果未达标，不适合启用七类业务控制。'), '',
              f'{dataset["sessions_crossing_splits"]}个会话和{dataset["cross_split_known_near_duplicate_pairs"]}对已知近重复候选跨集合，因此上述随机测试指标不能证明新会话、新用户或实板准确率。验证LEFT{validation_counts["POINT_LEFT"]}张、PALM{validation_counts["PALM"]}张。未根据本次测试再改参数；后续验收需新的独立数据。', '',
              '本轮使用重新划分的既有800张，图片曾参与此前开发和评价；这里的测试是探索分区评分，不是全新未见测试。不同划分的总体分数不能作为同一测试集上的严格提升证明。', '',
              (f'全参数审计通过：{report["trainability"]["trainable_parameters"]}个优化器可训练参数、无冻结权重层；{report["batchnorm_layer_count"]}个BatchNorm全部启用训练且状态哈希已改变。moving mean/variance是非梯度EMA状态，不是被排除的可优化参数。全部正式run保存checkpoint、最佳验证选择与进度。预处理保持0～255，本轮未改变标签、划分、阈值或固件。' if full else '27个BatchNorm状态训练前后逐字节哈希一致；全部正式run保存阶段checkpoint、最佳阶段选择与进度。预处理0～255数值域独立核查未发现遗漏归一化。本轮没有改变数据标签、划分、业务阈值或固件。'), '',
              '进度文件写入保留既有的有界权限冲突重试；旧实验及其失败日志不覆盖。', '',
              '后续可审核新的微调范围／学习率对照、目标域独立采集或小型模型重训；本次未擅自启动这些额外实验。', '',
              '## 产物位置', '',
              f'- 浮点 SavedModel：`{chosen / "saved_model"}`',
              f'- 最佳浮点权重：`{chosen / "best.weights.h5"}`',
              f'- 训练报告：`{chosen / "training_report.json"}`',
              f'- 最终测试及错分清单：`{chosen / "final_test_report.json"}`',
              f'- 固定候选记录：`{root / "frozen_candidate.json"}`',
              f'- 所有实验曲线与日志：`{root}`', '',
              '数值检查：SavedModel全部文件与冻结SHA一致，清单SHA一致，冻结时间早于测试评分，仅一份最终测试；本轮输出中无TFLite或C参数。候选仍为 `validated_for_business=false`。', '']
    args.output.write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'summary': str(args.output), 'selected_run': state['selected_run'],
                      'test_accuracy': metric['accuracy'], 'test_macro_f1': metric['macro_f1'],
                      'target_achieved': achieved, 'quantization_performed': False}, indent=2))


if __name__ == '__main__':
    main()
