"""七类真实 RGB565 数据检查及与固件相同的预处理；不生成或猜测标签。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

LABELS = ["POINT_LEFT", "POINT_RIGHT", "FIST", "PALM", "V_SIGN", "OTHER", "EMPTY"]
SPLITS = ("train", "validation", "calibration", "test")
PREPROCESS_VERSION = "rgb565-roi192-gray96-v1"


def preprocess(data: bytes, byte_order: str, stride_bytes: int = 640):
    """返回实际 int8 张量的 9216 字节表示及缩小前质量统计。"""
    if byte_order not in ("msb_first", "lsb_first"):
        raise ValueError("byte_order must be msb_first or lsb_first")
    if type(stride_bytes) is not int or not 640 <= stride_bytes <= 1048576:
        raise ValueError("stride_bytes must be an integer in [640,1048576]")
    if len(data) < stride_bytes * 239 + 640:
        raise ValueError("RGB565 frame is truncated (full 320x240 frame required)")
    output = bytearray(96 * 96)
    total = dark = bright = 0
    minimum, maximum = 255, 0
    for row in range(96):
        for col in range(96):
            block = 0
            for dy in range(2):
                pos = (24 + row * 2 + dy) * stride_bytes + (64 + col * 2) * 2
                for dx in range(2):
                    first, second = data[pos + dx * 2:pos + dx * 2 + 2]
                    pixel = first * 256 + second if byte_order == "msb_first" else second * 256 + first
                    r, g, b = (pixel >> 11) & 31, (pixel >> 5) & 63, pixel & 31
                    r, g, b = (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)
                    y = (77 * r + 150 * g + 29 * b + 128) >> 8
                    block += y
                    total += y
                    dark += y <= 16
                    bright += y >= 240
                    minimum, maximum = min(minimum, y), max(maximum, y)
            output[row * 96 + col] = (((block + 2) // 4) - 128) & 255
    count = 192 * 192
    stats = dict(pixel_count=count, dark_pixels=dark, bright_pixels=bright,
                 dark_permille=dark * 1000 // count, bright_permille=bright * 1000 // count,
                 mean_y=(total + count // 2) // count, min_y=minimum, max_y=maximum,
                 acceptable=int(dark * 1000 <= 800 * count and bright * 1000 <= 800 * count))
    return bytes(output), stats


def flip_label(label: int) -> int:
    """水平翻转必须交换左右标签；其余类别保持原语义。"""
    if not 0 <= label < len(LABELS):
        raise ValueError("invalid class index")
    return 1 - label if label < 2 else label


def read_dataset(manifest_path: Path, *, complete: bool = True):
    """核对原始文件哈希、会话隔离、全帧和标签；不自动分配数据 split。"""
    manifest_path = manifest_path.resolve()
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema_version") != 1 or manifest.get("preprocessing") != PREPROCESS_VERSION:
        raise ValueError("unsupported dataset schema/preprocessing")
    samples = manifest.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("no real samples supplied")
    if len(samples) > 100000:
        raise ValueError("dataset exceeds 100000-sample in-memory training limit")
    counts = {split: Counter() for split in SPLITS}
    sessions, hashes, paths, tensor_splits = {}, {}, set(), {}
    tensors, rows, quality_rejected = [], [], []
    root = manifest_path.parent
    for number, sample in enumerate(samples, 1):
        if not isinstance(sample, dict):
            raise ValueError(f"sample {number}: expected object")
        for key in ("file", "sha256", "session", "label", "split", "byte_order", "sensor_profile", "exposure_profile"):
            if not isinstance(sample.get(key), str) or not sample[key].strip():
                raise ValueError(f"sample {number}: missing {key}")
        label, split, session = sample["label"], sample["split"], sample["session"]
        if label not in LABELS or split not in SPLITS:
            raise ValueError(f"sample {number}: invalid label or split")
        if session in sessions and sessions[session] != split:
            raise ValueError(f"session leakage: {session} crosses {sessions[session]} and {split}")
        sessions[session] = split
        if sample.get("width") != 320 or sample.get("height") != 240:
            raise ValueError(f"sample {number}: expected 320x240 RGB565")
        if type(sample.get("capture_ms")) is not int or sample["capture_ms"] < 0:
            raise ValueError(f"sample {number}: capture_ms must be nonnegative integer")
        source = (root / sample["file"]).resolve()
        if not source.is_relative_to(root):
            raise ValueError(f"sample {number}: source must stay inside manifest directory")
        if source in paths:
            raise ValueError(f"duplicate source file: {sample['file']}")
        paths.add(source)
        # 限定单帧大小，防止错误的 stride 或路径将视频/磁盘文件载入内存。
        if source.stat().st_size > 1048576 * 240:
            raise ValueError(f"sample {number}: frame is too large")
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != sample["sha256"].lower():
            raise ValueError(f"sample {number}: SHA-256 mismatch")
        if digest in hashes:
            raise ValueError(f"duplicate raw frame (possible leakage): {sample['file']} and {hashes[digest]}")
        hashes[digest] = sample["file"]
        tensor, stats = preprocess(data, sample["byte_order"], sample.get("stride_bytes"))
        tensor_digest = hashlib.sha256(tensor).hexdigest()
        if tensor_digest in tensor_splits and tensor_splits[tensor_digest] != split:
            raise ValueError(f"preprocessed tensor leakage across splits: {sample['file']}")
        tensor_splits[tensor_digest] = split
        if not stats["acceptable"]:
            quality_rejected.append(sample["file"])
        counts[split][label] += 1
        tensors.append(tensor)
        rows.append({**sample, "quality": stats, "input_sha256": tensor_digest})
    missing = {split: [label for label in LABELS if counts[split][label] == 0] for split in SPLITS}
    missing = {split: labels for split, labels in missing.items() if labels}
    if complete and missing:
        raise ValueError(f"each split needs all seven classes; missing {missing}")
    report = dict(schema_version=1, preprocessing=PREPROCESS_VERSION, labels=LABELS,
                  manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(), sample_count=len(rows),
                  session_count=len(sessions), counts={s: dict(c) for s, c in counts.items()},
                  missing=missing, debug_quality_rejected=quality_rejected, samples=rows,
                  validated_for_business=False)
    return report, tensors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true", help="采样阶段只检查已有内容；不允许进入训练")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report, _ = read_dataset(args.manifest, complete=not args.allow_incomplete)
        content = json.dumps(report, ensure_ascii=False, indent=2)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(content + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k != "samples"}, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"Dataset rejected: {error}\n")


if __name__ == "__main__":
    main()
