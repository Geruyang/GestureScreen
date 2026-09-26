"""User-requested image-wise seeded random 560/80/160 dataset split."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import random
import shutil

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'GestureScreen/Datasets/gesture-800-v1'
OUTPUT = ROOT / 'custom_dataset'
SEED = 20260918


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source_bytes = (SOURCE / 'dataset_manifest.json').read_bytes()
    source = json.loads(source_bytes)
    rows = source['samples']
    assert len(rows) == 800
    # Resume only our existing copied dataset, never an unrelated directory.
    existing = None
    if OUTPUT.exists():
        existing = json.loads((OUTPUT / 'dataset_manifest.json').read_text(encoding='utf-8'))['samples']
        assert len(existing) == 800
        assert all(a['record_id'] == b['record_id'] and a['sha256'] == b['sha256']
                   for a, b in zip(rows, existing))
        for row in existing:
            for key in ('file', 'preview_file'):
                path = (OUTPUT / row[key]).resolve()
                assert path.is_relative_to(OUTPUT.resolve()) and path.is_file()
    else:
        OUTPUT.mkdir()
    order = list(range(800))
    random.Random(SEED).shuffle(order)
    assignment = {i: ('train' if rank < 560 else 'validation' if rank < 640 else 'test')
                  for rank, i in enumerate(order)}
    samples = []
    counts = defaultdict(Counter)
    raw_hashes, png_hashes = set(), set()
    session_splits = defaultdict(set)
    for i, original in enumerate(rows):
        split = assignment[i]
        row = dict(original)
        name = f'{i + 1:04d}_{original["record_id"]}'
        targets = {'file': Path('rgb565') / split / original['label'] / f'{name}.rgb565',
                   'preview_file': Path(split) / original['label'] / f'{name}.png'}
        for key, relative in targets.items():
            src = (SOURCE / original[key]).resolve()
            assert src.is_relative_to(SOURCE.resolve())
            target = OUTPUT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if existing:
                current = OUTPUT / existing[i][key]
                assert digest(current) == digest(src)
                if current != target:
                    assert not target.exists()
                    shutil.move(str(current), str(target))
            else:
                assert not target.exists()
                shutil.copy2(src, target)
            assert digest(target) == digest(src)
        raw_hash = digest(OUTPUT / targets['file'])
        png_hash = digest(OUTPUT / targets['preview_file'])
        assert raw_hash == original['sha256'] and raw_hash not in raw_hashes and png_hash not in png_hashes
        raw_hashes.add(raw_hash)
        png_hashes.add(png_hash)
        row.update(split=split, file=targets['file'].as_posix(), preview_file=targets['preview_file'].as_posix(),
                   original_split=original['split'], original_file=original['file'], preview_sha256=png_hash)
        if 'video_file' in row:
            row['source_video_file'] = row.pop('video_file')
        samples.append(row)
        counts[split][row['label']] += 1
        session_splits[row['session']].add(split)
    totals = {split: sum(counts[split].values()) for split in ('train', 'validation', 'test')}
    assert totals == {'train': 560, 'validation': 80, 'test': 160}
    assert all(len(counts[split]) == 7 for split in totals)
    assert len(list(OUTPUT.glob('*/**/*.png'))) == 800
    assert len(list((OUTPUT / 'rgb565').rglob('*.rgb565'))) == 800
    manifest = {**source, 'split_method': 'image-wise seeded uniform random shuffle', 'random_seed': SEED,
                'samples': samples}
    manifest_path = OUTPUT / 'dataset_manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    pairs = json.loads((SOURCE / 'near_duplicate_candidates.json').read_text())
    cross_near = sum(assignment[p['first']] != assignment[p['second']] for p in pairs)
    audit = {'sample_count': 800, 'png_count': 800, 'rgb565_count': 800, 'random_seed': SEED,
             'split_method': manifest['split_method'], 'split_totals': totals,
             'class_counts': {k: dict(v) for k, v in counts.items()},
             'source_manifest_sha256': hashlib.sha256(source_bytes).hexdigest(),
             'manifest_sha256': digest(manifest_path), 'all_copied_files_hash_verified': True,
             'raw_exact_duplicates': 0, 'png_exact_duplicates': 0,
             'sessions_crossing_splits': sum(len(v) > 1 for v in session_splits.values()),
             'cross_split_known_near_duplicate_pairs': cross_near,
             'session_isolated': False, 'validated_for_business': False,
             'warning': 'Image-wise random split requested by user. Related frames can cross splits; not an independent-session accuracy benchmark. Existing training tools require session isolation and calibration, so this manifest is not directly accepted by them.'}
    (OUTPUT / 'split_audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    if not (OUTPUT / 'licenses').exists():
        shutil.copytree(SOURCE / 'licenses', OUTPUT / 'licenses')
    labels = ('POINT_LEFT', 'POINT_RIGHT', 'FIST', 'PALM', 'V_SIGN', 'OTHER', 'EMPTY')
    table = '\n'.join('| ' + label + ' | ' + ' | '.join(str(counts[s][label]) for s in totals) + ' |' for label in labels)
    (OUTPUT / 'README.md').write_text(
        '# Custom gesture dataset\n\n'
        '按用户要求，以图片为单位随机打乱后分配，随机种子 20260918。'
        '训练集 560 张、验证集 80 张、测试集 160 张，严格为 7:1:2。所有集合均包含七类。\n\n'
        '`train/<类别>/`、`validation/<类别>/`、`test/<类别>/` 保存 PNG 图像。'
        '`rgb565/` 是同一批 800 张图像的固件格式副本，不是额外样本。'
        '`dataset_manifest.json` 保存来源、标签、分区和许可；`split_audit.json` 保存核验结果。\n\n'
        '| 类别 | train | validation | test |\n| --- | ---: | ---: | ---: |\n' + table + '\n\n'
        f'注意：随机按图片划分使 {audit["sessions_crossing_splits"]} 个会话跨集合，'
        f'已知近重复候选有 {cross_near} 对跨集合，可能高估识别准确率。此划分不是独立会话测试。'
        '现有训练工具要求会话隔离和 calibration 分区，因此不能直接通过其完整训练检查；'
        '本次未修改训练工具或启动训练。\n\n'
        '原始数据集未修改，未增广、未丢弃、未重标注。来源和许可说明见 '
        '`../GestureScreen/Datasets/gesture-800-v1/README.md`，HaGRID 许可全文保留于 `licenses/`。\n', encoding='utf-8')
    assert (SOURCE / 'dataset_manifest.json').read_bytes() == source_bytes
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
