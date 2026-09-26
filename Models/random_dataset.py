"""Explicit image-random three-split reader; original strict reader is unchanged."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from dataset import LABELS, PREPROCESS_VERSION, preprocess

SPLITS = ("train", "validation", "test")
UNIFORM_METHOD = "image-wise seeded uniform random shuffle"
STRATIFIED_METHOD = "image-wise seeded class-stratified random shuffle"
SESSION_METHOD = "whole_session_exhaustive_count_then_class_error"
RISK = ("Image-wise random split permits related sessions/near-duplicate frames across splits. "
        "Scores are exploratory, not independent-session, new-user or board acceptance.")


def read_random_dataset(manifest_path: Path, *, expected_counts=None):
    manifest_path = manifest_path.resolve()
    content = manifest_path.read_bytes()
    manifest = json.loads(content)
    if manifest.get("schema_version") != 1 or manifest.get("preprocessing") != PREPROCESS_VERSION:
        raise ValueError("unsupported schema/preprocessing")
    method = manifest.get("split_method")
    if method not in (UNIFORM_METHOD, STRATIFIED_METHOD, SESSION_METHOD):
        raise ValueError("explicit image-wise random split declaration required")
    if method == STRATIFIED_METHOD and manifest.get("split_ratios") != dict(train=7, validation=1, test=2):
        raise ValueError("stratified random split requires explicit 7:1:2 ratios")
    if method == SESSION_METHOD and manifest.get("split_ratios") != dict(train=8, validation=2, test=2):
        raise ValueError("session split requires explicit 8:2:2 ratios")
    samples = manifest.get("samples")
    if not isinstance(samples, list) or not 0 < len(samples) <= 100000:
        raise ValueError("invalid sample count")
    root = manifest_path.parent
    paths, raw_hashes, tensor_hashes = set(), {}, {}
    sessions, counts = defaultdict(set), {s: Counter() for s in SPLITS}
    tensors, checked = [], []
    for number, row in enumerate(samples, 1):
        if row.get('excluded'):
            raise ValueError('excluded sample in training manifest')
        for key in ("file", "sha256", "session", "label", "split", "byte_order", "sensor_profile", "exposure_profile"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"sample {number}: missing {key}")
        if row["label"] not in LABELS or row["split"] not in SPLITS:
            raise ValueError(f"sample {number}: invalid label/split")
        if row.get("width") != 320 or row.get("height") != 240:
            raise ValueError(f"sample {number}: expected full 320x240")
        if type(row.get("capture_ms")) is not int or row["capture_ms"] < 0:
            raise ValueError(f"sample {number}: invalid capture_ms")
        source = (root / row["file"]).resolve()
        if not source.is_relative_to(root) or source in paths:
            raise ValueError(f"sample {number}: unsafe/duplicate source path")
        paths.add(source)
        if source.stat().st_size > 1048576 * 240:
            raise ValueError("frame too large")
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != row["sha256"].lower():
            raise ValueError(f"sample {number}: raw SHA-256 mismatch")
        if digest in raw_hashes:
            raise ValueError(f"duplicate raw frame: {row['file']} and {raw_hashes[digest]}")
        raw_hashes[digest] = row["file"]
        tensor, quality = preprocess(data, row["byte_order"], row.get("stride_bytes", 640))
        tensor_digest = hashlib.sha256(tensor).hexdigest()
        if tensor_digest in tensor_hashes:
            raise ValueError(f"duplicate preprocessed tensor: {row['file']} and {tensor_hashes[tensor_digest]}")
        tensor_hashes[tensor_digest] = row["file"]
        if not quality["acceptable"]:
            raise ValueError(f"debug quality rejected: {row['file']}")
        if row.get("preview_file"):
            preview = (root / row["preview_file"]).resolve()
            if not preview.is_relative_to(root):
                raise ValueError("unsafe preview path")
            if hashlib.sha256(preview.read_bytes()).hexdigest() != row.get("preview_sha256"):
                raise ValueError(f"preview SHA-256 mismatch: {row['file']}")
        counts[row["split"]][row["label"]] += 1
        sessions[row["session"]].add(row["split"])
        checked.append({**row, "input_sha256": tensor_digest, "quality": quality})
        tensors.append(tensor)
    if method == SESSION_METHOD:
        for field in ('session', 'session_id', 'clip_id'):
            memberships = defaultdict(set)
            for row in checked:
                if row.get(field):
                    memberships[row[field]].add(row['split'])
            if any(len(v) > 1 for v in memberships.values()):
                raise ValueError(f'{field} leakage across splits')
        if any(r['split'] != 'train' for r in checked if r.get('source') == 'licensed_external_image' or r.get('merge_origin') == 'new_capture'):
            raise ValueError('external/new capture training-only policy violated')
    if any(set(c) != set(LABELS) for c in counts.values()):
        raise ValueError("each of the three splits must contain all seven labels")
    totals = {s: sum(c.values()) for s, c in counts.items()}
    if method == STRATIFIED_METHOD:
        for label in LABELS:
            support = sum(counts[s][label] for s in SPLITS)
            for split, ratio in manifest["split_ratios"].items():
                # Each count must be floor/ceil of its fractional class target.
                target, remainder = divmod(support * ratio, 10)
                if counts[split][label] not in {target, target + bool(remainder)}:
                    raise ValueError(f"stratified class count outside rounding bounds: {split}/{label}")
    if expected_counts is not None and totals != expected_counts:
        raise ValueError(f"split totals changed: {totals}")
    near_pairs = None
    audit_path = root / "split_audit.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if audit.get("manifest_sha256") != hashlib.sha256(content).hexdigest():
            raise ValueError("split audit manifest hash mismatch")
        near_pairs = audit.get("cross_split_known_near_duplicate_pairs")
    return dict(manifest_sha256=hashlib.sha256(content).hexdigest(), sample_count=len(checked),
                split_method=method, split_ratios=manifest.get("split_ratios"),
                counts={s: dict(c) for s, c in counts.items()}, split_totals=totals,
                samples=checked, session_count=len(sessions), session_isolated=method == SESSION_METHOD,
                sessions_crossing_splits=sum(len(v) > 1 for v in sessions.values()),
                cross_split_known_near_duplicate_pairs=near_pairs,
                raw_exact_duplicates=0, input_exact_duplicates=0,
                warning=manifest.get('evaluation_note', RISK) if method == SESSION_METHOD else RISK,
                validated_for_business=False), tensors


def read_training_dataset(manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    method = manifest['split_method']
    expected = None if method == SESSION_METHOD else manifest.get('split_counts', dict(train=560, validation=80, test=160))
    return read_random_dataset(manifest_path, expected_counts=expected)
