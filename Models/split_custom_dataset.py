"""Create an exact 70/10/20 split without separating sessions/known near pairs."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'GestureScreen/Build/dataset-import-deps'))
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix
from dataset import LABELS, read_dataset


def main():
    source = ROOT / 'GestureScreen/Datasets/gesture-800-v1'
    destination = ROOT / 'custom_dataset'
    if destination.exists():
        raise FileExistsError(f'Refusing to overwrite {destination}')
    original = (source / 'dataset_manifest.json').read_bytes()
    manifest = json.loads(original)
    samples = manifest['samples']
    assert len(samples) == 800
    parent = list(range(800))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(b)] = find(a)

    sessions = {}
    for i, sample in enumerate(samples):
        if sample['session'] in sessions:
            union(i, sessions[sample['session']])
        else:
            sessions[sample['session']] = i
    pairs = json.loads((source / 'near_duplicate_candidates.json').read_text())
    for pair in pairs:
        union(pair['first'], pair['second'])
    groups = defaultdict(list)
    for i in range(800):
        groups[find(i)].append(i)
    groups = list(groups.values())
    splits = ('train', 'validation', 'test')
    totals = (560, 80, 160)
    ratios = (.7, .1, .2)
    class_total = Counter(s['label'] for s in samples)
    n = len(groups)
    binary_count = n * 3
    variable_count = binary_count + 42
    # One assignment/group, exact overall counts, then class deviations.
    matrix = lil_matrix((n + 3 + 21, variable_count))
    low = np.zeros(n + 24)
    high = np.zeros(n + 24)
    objective = np.zeros(variable_count)
    for g, indices in enumerate(groups):
        counts = Counter(samples[i]['label'] for i in indices)
        for s in range(3):
            col = g * 3 + s
            matrix[g, col] = 1
            matrix[n + s, col] = len(indices)
            for label_index, label in enumerate(LABELS):
                matrix[n + 3 + s * 7 + label_index, col] = counts[label]
        low[g] = high[g] = 1
    for s in range(3):
        low[n + s] = high[n + s] = totals[s]
        for k, label in enumerate(LABELS):
            offset = s * 7 + k
            row = n + 3 + offset
            matrix[row, binary_count + offset * 2] = 1
            matrix[row, binary_count + offset * 2 + 1] = -1
            low[row] = high[row] = class_total[label] * ratios[s]
            objective[binary_count + offset * 2:binary_count + offset * 2 + 2] = 1 / class_total[label]
    result = milp(objective, integrality=np.r_[np.ones(binary_count), np.zeros(42)],
                  bounds=Bounds(np.zeros(variable_count), np.r_[np.ones(binary_count), np.full(42, np.inf)]),
                  constraints=LinearConstraint(matrix.tocsr(), low, high),
                  options={'time_limit': 45, 'mip_rel_gap': .01})
    if result.x is None:
        raise RuntimeError(f'No feasible session-isolated split: {result.message}')
    assignments = {}
    for g, indices in enumerate(groups):
        values = result.x[g * 3:g * 3 + 3]
        assert abs(max(values) - 1) < 1e-5
        for i in indices:
            assignments[i] = splits[int(np.argmax(values))]
    assert Counter(assignments.values()) == dict(zip(splits, totals))
    assert all(assignments[p['first']] == assignments[p['second']] for p in pairs)
    destination.mkdir()
    rows = []
    png_hashes = set()
    for i, sample in enumerate(samples):
        row = dict(sample)
        split, label = assignments[i], sample['label']
        name = f'{i + 1:04d}_{sample["record_id"]}'
        png = Path(split) / label / f'{name}.png'
        raw = Path('rgb565') / split / label / f'{name}.rgb565'
        for key, target in (('preview_file', png), ('file', raw)):
            src = (source / sample[key]).resolve()
            assert src.is_relative_to(source.resolve())
            dst = destination / target
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            assert hashlib.sha256(src.read_bytes()).digest() == hashlib.sha256(dst.read_bytes()).digest()
        png_digest = hashlib.sha256((destination / png).read_bytes()).hexdigest()
        assert png_digest not in png_hashes
        png_hashes.add(png_digest)
        row.update(split=split, file=raw.as_posix(), preview_file=png.as_posix(), preview_sha256=png_digest,
                   original_split=sample['split'], original_file=sample['file'])
        if 'video_file' in row:
            row['source_video_file'] = row.pop('video_file')
        rows.append(row)
    output = {**manifest, 'samples': rows}
    manifest_path = destination / 'dataset_manifest.json'
    manifest_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    audit, _ = read_dataset(manifest_path, complete=False)
    assert audit['sample_count'] == 800 and not audit['debug_quality_rejected']
    assert set(audit['missing']) == {'calibration'}
    assert len(list(destination.glob('*/**/*.png'))) == 800
    shutil.copytree(source / 'licenses', destination / 'licenses')
    audit.update(source_manifest_sha256=hashlib.sha256(original).hexdigest(),
                 split_totals=dict(zip(splits, totals)), group_count=n,
                 known_near_duplicate_pairs=len(pairs), cross_split_known_near_pairs=0,
                 split_method='session + known dHash<=3 connected groups; exact totals; class-balance MILP',
                 optimizer_status=str(result.message), png_count=800, raw_count=800,
                 calibration_required_by_existing_training_pipeline=True)
    (destination / 'split_audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    table = '\n'.join(f'| {label} | ' + ' | '.join(str(audit['counts'][s].get(label, 0)) for s in splits) + ' |'
                      for label in LABELS)
    (destination / 'README.md').write_text(
        '# Custom gesture dataset\n\n'
        '800 张 RGB PNG 图像，train/validation/test = 560/80/160（7:1:2）。\n\n'
        '`train/<类别>/`、`validation/<类别>/`、`test/<类别>/` 是图像目录；'
        '`rgb565/` 保存同一批图像的固件原始格式，不是额外样本。'
        '`dataset_manifest.json` 保留标签、来源与许可信息。\n\n'
        '| 类别 | train | validation | test |\n| --- | ---: | ---: | ---: |\n' + table + '\n\n'
        '按原始会话及已发现的近重复候选连通组划分，组不跨分区；'
        '总数量严格满足比例，类别比例尽量接近，未丢弃、增广或重标注图像。'
        '此检查不证明不存在所有未发现的近重复或主体身份泄漏，也不代表识别准确率验收。\n\n'
        '原始数据集和个人采集清单未修改。来源与许可详情见 '
        '`../GestureScreen/Datasets/gesture-800-v1/README.md`，HaGRID 许可副本位于 `licenses/`。\n\n'
        '按用户要求只有三个分区，没有 calibration。现有工程训练工具要求单独的 '
        'calibration 分区：部署量化前需从训练集另划校准集，不应使用测试集调参或校准。\n', encoding='utf-8')
    assert (source / 'dataset_manifest.json').read_bytes() == original
    print(json.dumps({'path': str(destination), 'counts': audit['counts'], 'totals': audit['split_totals'],
                      'png_count': 800, 'raw_count': 800, 'cross_split_known_near_pairs': 0}, indent=2))


if __name__ == '__main__':
    main()
