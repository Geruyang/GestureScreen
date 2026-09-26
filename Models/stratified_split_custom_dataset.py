"""Repartition the same 800 images by class, with a recoverable previous split.

Default is read-only planning. --apply stages/validates new images, archives the
previous split, then moves individual assets; training outputs stay untouched.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
from itertools import product
import json
import os
from pathlib import Path
import random
import shutil
import time

from dataset import LABELS
from random_dataset import SPLITS, STRATIFIED_METHOD, read_random_dataset

ROOT = Path(__file__).resolve().parents[2]
RATIOS = dict(train=7, validation=1, test=2)
TOTALS = dict(train=560, validation=80, test=160)
ASSET_DIRS = (*SPLITS, "rgb565")
METADATA = ("dataset_manifest.json", "split_audit.json", "README.md")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contained(root, relative):
    root = root.resolve()
    path = (root / relative).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError(f"path must stay strictly inside {root}: {relative}")
    return path


def allocate_counts(class_totals, split_totals):
    """Exact global totals, floor/ceil class counts, least squared rounding error.

    Integer tenths avoid float ties. Dynamic programming is tiny for seven rows;
    ties use lexicographic allocations in the fixed LABELS/SPLITS order.
    """
    if set(class_totals) != set(LABELS) or set(split_totals) != set(SPLITS):
        raise ValueError("seven classes and three splits required")
    if any(type(n) is not int or n <= 0 for n in class_totals.values()):
        raise ValueError("positive integer class totals required")
    if sum(class_totals.values()) != sum(split_totals.values()):
        raise ValueError("class and split totals disagree")
    states = {(0, 0): (0, ())}
    cumulative = 0
    for label in LABELS:
        support = class_totals[label]
        targets = [support * RATIOS[s] for s in SPLITS]
        bounds = [(t // 10, t // 10 + bool(t % 10)) for t in targets]
        options = sorted(set(choice for choice in product(*bounds) if sum(choice) == support))
        next_states = {}
        cumulative += support
        for (train, validation), (cost, history) in states.items():
            for choice in options:
                key = train + choice[0], validation + choice[1]
                test = cumulative - sum(key)
                if any(n > split_totals[s] for n, s in zip((*key, test), SPLITS)):
                    continue
                candidate = cost + sum((10*n-t)**2 for n, t in zip(choice, targets)), history + (choice,)
                if key not in next_states or candidate < next_states[key]:
                    next_states[key] = candidate
        states = next_states
    selected = states.get((split_totals["train"], split_totals["validation"]))
    if selected is None:
        raise ValueError("no allocation satisfies global totals and class rounding bounds")
    return {label: dict(zip(SPLITS, counts)) for label, counts in zip(LABELS, selected[1])}


def assignments(rows, seed, allocation):
    rng = random.Random(seed)
    result = {}
    for label in LABELS:
        indices = [i for i, row in enumerate(rows) if row["label"] == label]
        rng.shuffle(indices)  # No session, video, person or near-pair grouping.
        offset = 0
        for split in SPLITS:
            count = allocation[label][split]
            for index in indices[offset:offset + count]:
                result[index] = split
            offset += count
        if offset != len(indices):
            raise ValueError("allocation does not preserve all class samples")
    return result


def prepare(dataset, seed):
    content = (dataset / "dataset_manifest.json").read_bytes()
    manifest = json.loads(content)
    rows = manifest["samples"]
    if len(rows) != 800 or len({r["record_id"] for r in rows}) != 800:
        raise ValueError("expected 800 unique existing records")
    totals = Counter(r["label"] for r in rows)
    allocation = allocate_counts(totals, TOTALS)
    assignment = assignments(rows, seed, allocation)
    expected_files = set()
    raw_hashes, png_hashes = set(), set()
    for row in rows:
        for field, hash_field, seen in (("file", "sha256", raw_hashes),
                                       ("preview_file", "preview_sha256", png_hashes)):
            path = contained(dataset, row[field])
            allowed = "rgb565" if field == "file" else row["split"]
            if not path.is_relative_to(contained(dataset, allowed)):
                raise ValueError(f"asset outside its managed directory: {row[field]}")
            value = digest(path)
            if value != row[hash_field] or value in seen:
                raise ValueError(f"modified or duplicate existing asset: {row[field]}")
            seen.add(value)
            expected_files.add(path)
    actual_files = {p.resolve() for name in ASSET_DIRS for p in contained(dataset, name).rglob("*") if p.is_file()}
    if actual_files != expected_files:
        raise ValueError("unlisted/missing files in managed directories; refusing to move them")
    plan = dict(sample_count=800, random_seed=seed, split_method=STRATIFIED_METHOD,
                split_ratios=RATIOS, split_totals=TOTALS, class_totals=dict(totals),
                class_counts={s: {label: allocation[label][s] for label in LABELS} for s in SPLITS},
                previous_manifest_sha256=hashlib.sha256(content).hexdigest(),
                changed_assignments=sum(r["split"] != assignment[i] for i, r in enumerate(rows)),
                session_grouping=False, samples_added=0, samples_removed=0, labels_changed=0)
    return manifest, assignment, plan


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def retry_permission(operation, *args):
    for attempt in range(12):
        try:
            return operation(*args)
        except PermissionError:
            if attempt == 11:
                raise
            time.sleep(min(.02 * (attempt + 1), .1))


def readme(plan, audit):
    table = "\n".join("| " + label + " | " + " | ".join(
        str(plan["class_counts"][s][label]) for s in SPLITS) + f" | {plan['class_totals'][label]} |" for label in LABELS)
    return ("# Custom gesture dataset\n\n"
            "2026-09-19 按用户要求改为**按类别分层、图片级随机划分**，每个类别按7:1:2分配，"
            f"不按视频或会话分组。随机种子{plan['random_seed']}；总数严格为560训练／80验证／160测试。\n\n"
            "保留原800张和每类总数，不删图、不复制增广、不重标注。类别总数不能被10整除时，"
            "各格取理论数量的floor/ceil，并在保持总数的条件下最小化舍入平方误差。"
            "这里均衡的是各集合的类别比例，不是让七类总数相等。\n\n"
            "| 类别 | train | validation | test | 合计 |\n| --- | ---: | ---: | ---: | ---: |\n" + table + "\n\n"
            "`train/<类别>/`、`validation/<类别>/`、`test/<类别>/`保存PNG；`rgb565/`是同一批800张的原始格式副本。"
            "清单保留来源、视频、会话、许可和原始哈希；`split_audit.json`保存当前核验与备份位置。\n\n"
            f"旧划分完整备份：[旧数据集]({plan['previous_dataset_archive']}/dataset_manifest.json)。"
            "历史训练/测试指标只对应旧划分；本次未重训，新划分没有新准确率。"
            "图片已用于先前实验，重新划分不会使测试集成为未见的新验收数据。\n\n"
            f"注意：{audit['sessions_crossing_splits']}个会话跨集合，{audit['cross_split_known_near_duplicate_pairs']}对"
            "已知近重复候选跨集合，不能作为独立会话/新用户验收。"
            "`train_random_split.py`兼容这一显式分层随机清单；旧严格会话训练入口不变。\n\n"
            "原始数据集及许可未改，见`../GestureScreen/Datasets/gesture-800-v1/README.md`和`licenses/`。\n")


def apply_split(dataset, seed, workspace=ROOT):
    workspace = workspace.resolve()
    dataset = contained(workspace, dataset.resolve().relative_to(workspace))
    manifest, assignment, plan = prepare(dataset, seed)
    if manifest.get("split_method") == STRATIFIED_METHOD and manifest.get("random_seed") == seed and not plan["changed_assignments"]:
        return dict(status="already_applied", **plan)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    archive = contained(workspace, f"GestureScreen/Datasets/custom-dataset-split-history/image-random-{stamp}")
    stage = contained(workspace, f"GestureScreen/Build/dataset-resplit/stratified-{stamp}")
    if archive.exists() or stage.exists():
        raise FileExistsError("new archive and staging directories required")
    stage.mkdir(parents=True)
    plan["previous_dataset_archive"] = os.path.relpath(archive, dataset).replace("\\", "/")
    rows = []
    sessions = defaultdict(set)
    source_counts = {s: Counter() for s in SPLITS}
    for i, original in enumerate(manifest["samples"]):
        split, label = assignment[i], original["label"]
        row = dict(original, split=split, previous_split=original["split"],
                   previous_file=original["file"], previous_preview_file=original["preview_file"])
        for field, relative in (("file", Path("rgb565") / split / label / Path(original["file"]).name),
                                ("preview_file", Path(split) / label / Path(original["preview_file"]).name)):
            target = contained(stage, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise FileExistsError(target)
            shutil.copy2(contained(dataset, original[field]), target)
            row[field] = relative.as_posix()
        rows.append(row)
        sessions[row["session"]].add(split)
        source_counts[split][row.get("source", "unknown")] += 1
    new_manifest = dict(manifest, samples=rows, split_method=STRATIFIED_METHOD,
                        split_ratios=RATIOS, random_seed=seed, split_revision_date="2026-09-19",
                        previous_manifest_sha256=plan["previous_manifest_sha256"],
                        previous_dataset_archive=plan["previous_dataset_archive"],
                        evaluation_note="Repartition of previously used images; not a fresh unseen test set.")
    write_json(stage / "dataset_manifest.json", new_manifest)
    source_dir = contained(workspace, "GestureScreen/Datasets/gesture-800-v1")
    source_rows = json.loads((source_dir / "dataset_manifest.json").read_text(encoding="utf-8"))["samples"]
    by_id = {r["record_id"]: assignment[i] for i, r in enumerate(rows)}
    if set(by_id) != {r["record_id"] for r in source_rows}:
        raise ValueError("near-pair source records differ from current 800 images")
    pairs = json.loads((source_dir / "near_duplicate_candidates.json").read_text(encoding="utf-8"))
    cross_near = sum(by_id[source_rows[p["first"]]["record_id"]] != by_id[source_rows[p["second"]]["record_id"]] for p in pairs)
    audit = dict(plan, png_count=800, rgb565_count=800,
                 manifest_sha256=digest(stage / "dataset_manifest.json"),
                 source_manifest_sha256=digest(source_dir / "dataset_manifest.json"),
                 source_counts={s: dict(v) for s, v in source_counts.items()},
                 sessions_crossing_splits=sum(len(v) > 1 for v in sessions.values()),
                 cross_split_known_near_duplicate_pairs=cross_near,
                 all_copied_files_hash_verified=True, raw_exact_duplicates=0, png_exact_duplicates=0,
                 session_isolated=False, validated_for_business=False, training_performed=False,
                 class_ratio_rounding="floor/ceil of N_c*(7,1,2)/10; minimum squared error with exact overall totals",
                 warning="Image-level class stratification; related video frames may cross splits. Existing training metrics refer to the archived previous split; new split is not fresh unseen evaluation.")
    write_json(stage / "split_audit.json", audit)
    (stage / "README.md").write_text(readme(plan, audit), encoding="utf-8")
    report, _ = read_random_dataset(stage / "dataset_manifest.json", expected_counts=TOTALS)
    if report["counts"] != plan["class_counts"]:
        raise ValueError("staged class counts do not match plan")
    audit["input_exact_duplicates"] = report["input_exact_duplicates"]
    audit["preprocessing_and_quality_verified"] = True
    write_json(stage / "split_audit.json", audit)
    # Protect against concurrent changes; all resolved move targets stay inside
    # the explicitly named project workspace and archive/staging directories.
    if digest(dataset / "dataset_manifest.json") != plan["previous_manifest_sha256"]:
        raise ValueError("manifest changed while staging; current dataset untouched")
    prepare(dataset, seed)
    archive.mkdir(parents=True)
    for name in (*METADATA, "training_plan.md", "training_results.md", "training_review.md", "accuracy_analysis.md", "TRAINING_RUN.md"):
        if (dataset / name).is_file():
            shutil.copy2(contained(dataset, name), contained(archive, name))
    # Windows can lock a watched directory against rename while its files remain
    # movable. Copy the complete previous assets, and never rename their roots.
    for original in manifest["samples"]:
        for field, hash_field in (("file", "sha256"), ("preview_file", "preview_sha256")):
            target = contained(archive, original[field])
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise FileExistsError(target)
            shutil.copy2(contained(dataset, original[field]), target)
            if digest(target) != original[hash_field]:
                raise ValueError("previous-split archive hash mismatch; current dataset untouched")
    moved = []
    try:
        for original, row in zip(manifest["samples"], rows):
            for field in ("file", "preview_file"):
                current = contained(dataset, original[field])
                target = contained(dataset, row[field])
                if current != target:
                    if target.exists():
                        raise FileExistsError(target)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    retry_permission(current.rename, target)
                    moved.append((current, target))
        for name in METADATA:
            retry_permission(os.replace, contained(stage, name), contained(dataset, name))
        # Every installed image is still byte-identical, with exactly 1600 assets.
        prepare(dataset, seed)
        if digest(dataset / "dataset_manifest.json") != audit["manifest_sha256"]:
            raise ValueError("installed manifest hash mismatch")
    except BaseException:
        for previous, current in reversed(moved):
            retry_permission(current.rename, previous)
        for name in METADATA:
            if (archive / name).is_file():
                shutil.copy2(contained(archive, name), contained(dataset, name))
        raise
    return dict(status="applied", dataset=str(dataset), archive=str(archive), **audit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260918)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    dataset = ROOT / "custom_dataset"
    if args.apply:
        result = apply_split(dataset, args.seed)
    else:
        _, _, result = prepare(dataset, args.seed)
        result = dict(status="read_only_plan", **result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
