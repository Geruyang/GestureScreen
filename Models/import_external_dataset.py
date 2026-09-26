"""Build a traceable 800-frame RGB565 dataset from personal and licensed sources.

The original personal manifest is never modified.  HANDS subject ZIP files are
read with HTTP range requests so only the central directory and selected RGB
frames are downloaded.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import io
import json
import re
import shutil
import struct
import sys
import urllib.request
import uuid
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from PIL import Image, ImageCms, ImageOps
from PIL import ImageDraw


LABELS = ["POINT_LEFT", "POINT_RIGHT", "FIST", "PALM", "V_SIGN", "OTHER", "EMPTY"]
HANDS_COLUMNS = ["Horiz_HBL", "Horiz_HFL", "Horiz_HBR", "Horiz_HFR"]
HANDS_MAP = {
    "Horiz_HBL": "POINT_RIGHT",
    "Horiz_HFL": "POINT_LEFT",
    "Horiz_HBR": "POINT_LEFT",
    "Horiz_HFR": "POINT_RIGHT",
}
HANDS_SUBJECTS = {
    1: {
        "zip_url": "https://data.mendeley.com/public-files/datasets/ndrczc35bt/files/74194129-e9c8-41f5-a3a2-7c25bd838b5e/file_downloaded",
        "zip_size": 1360295597,
        "zip_sha256": "d836f19d24484a37a5397dcc473bc7345cfb5ac4f1ef0f0b5be60f479e815834",
    },
    2: {
        "zip_url": "https://data.mendeley.com/public-files/datasets/ndrczc35bt/files/2b75386e-0f21-4132-9e9f-4901106d4396/file_downloaded",
        "zip_size": 1420184877,
        "zip_sha256": "036349efd9ad445d20ad422ede9685db56c94d779f963ca3e87eee702aef1056",
    },
    3: {
        "zip_url": "https://data.mendeley.com/public-files/datasets/ndrczc35bt/files/7f45eb77-2369-42dd-b8c3-003c666a612b/file_downloaded",
        "zip_size": 1473257353,
        "zip_sha256": "16ac83feeb0a0efee178dede3902889f98594a44b0cfbd2218cf88b2e4508fab",
    },
    4: {
        "zip_url": "https://data.mendeley.com/public-files/datasets/ndrczc35bt/files/1424f31b-73c1-4642-bba6-ed8958ecbd8e/file_downloaded",
        "zip_size": 1292028752,
        "zip_sha256": "73bd69c69798f0ad7d8ef4c109c3122c9499b96dd269192ad9beff4a28409277",
    },
    5: {
        "zip_url": "https://data.mendeley.com/public-files/datasets/ndrczc35bt/files/301ea9de-a70a-4e68-8a6f-7d2a9c972353/file_downloaded",
        "zip_size": 1453310587,
        "zip_sha256": "a5505245062b7b64a11b8b990928cf46f9b3c75a88c322dcdf582bbf1b80156e",
    },
}

EXTERNAL_TOTALS = {
    "POINT_LEFT": 77,
    "POINT_RIGHT": 94,
    "FIST": 88,
    "PALM": 85,
    "V_SIGN": 87,
    "OTHER": 72,
    "EMPTY": 0,
}
HAGRID_SIMPLE = {"fist": "FIST", "palm": "PALM", "peace": "V_SIGN"}
HAGRID_OTHER = ["no_gesture", "like", "dislike", "ok", "rock", "call", "four"]
PERSONAL_SPLITS = {
    "fff8dd71ae6a44249bd60335acefdd73": "train",
    "4c42e9dfdfe148e582c291639c73ef36": "validation",
    "738945bc612744faa98a61c31c5d2845": "test",
    "82dc4d8823cc4c58a5fde2600e586d8d": "calibration",
}


class HTTPRangeFile(io.RawIOBase):
    """Small seekable reader backed by cached HTTP byte ranges."""

    def __init__(self, url: str, size: int, block_size: int = 1 << 20):
        self.url = url
        self.size = size
        self.block_size = block_size
        self.position = 0
        self.blocks: dict[int, bytes] = {}

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            position = offset
        elif whence == io.SEEK_CUR:
            position = self.position + offset
        elif whence == io.SEEK_END:
            position = self.size + offset
        else:
            raise ValueError("invalid whence")
        if position < 0:
            raise ValueError("negative seek")
        self.position = min(position, self.size)
        return self.position

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)

    def read(self, size=-1):
        if size is None or size < 0:
            size = self.size - self.position
        size = min(size, self.size - self.position)
        if size <= 0:
            return b""
        output = bytearray()
        while size:
            block = self.position // self.block_size
            within = self.position % self.block_size
            if block not in self.blocks:
                start = block * self.block_size
                end = min(self.size, start + self.block_size) - 1
                request = urllib.request.Request(
                    self.url,
                    headers={
                        "Range": f"bytes={start}-{end}",
                        "User-Agent": "Mozilla/5.0 GestureScreenDatasetBuilder/1.0",
                    },
                )
                with urllib.request.urlopen(request, timeout=120) as response:
                    payload = response.read()
                expected = end - start + 1
                if len(payload) != expected:
                    raise OSError(f"short HTTP range: expected {expected}, received {len(payload)}")
                self.blocks[block] = payload
            chunk = self.blocks[block][within : within + size]
            if not chunk:
                break
            output.extend(chunk)
            self.position += len(chunk)
            size -= len(chunk)
        return bytes(output)


def inspect_hands(subject: int, pattern: str | None):
    item = HANDS_SUBJECTS[subject]
    remote = HTTPRangeFile(item["zip_url"], item["zip_size"])
    with zipfile.ZipFile(remote) as archive:
        names = archive.namelist()
    if pattern:
        names = [name for name in names if re.search(pattern, name, re.IGNORECASE)]
    print(json.dumps({"subject": subject, "entries": len(names), "names": names[:300]}, indent=2))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_bbox(value: str) -> tuple[int, int, int, int] | None:
    numbers = [int(item) for item in re.findall(r"-?\d+", value)]
    if len(numbers) != 4 or numbers == [0, 0, 0, 0]:
        return None
    return tuple(numbers)


def crop_around_bbox(image: Image.Image, bbox: tuple[float, float, float, float], context: float = 2.8):
    x, y, width, height = bbox
    center_x, center_y = x + width / 2, y + height / 2
    crop_width = max(width * context, height * context * 4 / 3)
    crop_height = crop_width * 3 / 4
    # Keep the annotated hand centered in the firmware ROI.  Clamping this
    # window to source boundaries can shift the entire hand outside the ROI.
    # Pillow pads out-of-source pixels with black; the crop box records this.
    left = center_x - crop_width / 2
    top = center_y - crop_height / 2
    box = (int(round(left)), int(round(top)), int(round(left + crop_width)), int(round(top + crop_height)))
    return image.crop(box), list(box)


def normalize_image(source: bytes, bbox: tuple[float, float, float, float]):
    with Image.open(io.BytesIO(source)) as opened:
        image = ImageOps.exif_transpose(opened)
        if image.info.get("icc_profile"):
            try:
                profile = ImageCms.ImageCmsProfile(io.BytesIO(image.info["icc_profile"]))
                image = ImageCms.profileToProfile(image, profile, ImageCms.createProfile("sRGB"), outputMode="RGB")
            except (OSError, ValueError):
                image = image.convert("RGB")
        else:
            image = image.convert("RGB")
        cropped, crop_box = crop_around_bbox(image, bbox)
        resized = cropped.resize((320, 240), Image.Resampling.LANCZOS)
    return resized, crop_box


def rgb565_be(image: Image.Image) -> bytes:
    output = bytearray(320 * 240 * 2)
    position = 0
    for red, green, blue in image.getdata():
        value = ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
        output[position] = value >> 8
        output[position + 1] = value & 255
        position += 2
    return bytes(output)


def decode_rgb565(data: bytes) -> Image.Image:
    pixels = []
    for position in range(0, len(data), 2):
        value = (data[position] << 8) | data[position + 1]
        red, green, blue = (value >> 11) & 31, (value >> 5) & 63, value & 31
        pixels.append(((red << 3) | (red >> 2), (green << 2) | (green >> 4), (blue << 3) | (blue >> 2)))
    image = Image.new("RGB", (320, 240))
    image.putdata(pixels)
    return image


def write_external_frame(output: Path, label: str, split: str, session: str, source_bytes: bytes,
                         bbox: tuple[float, float, float, float], provenance: dict, index: int):
    normalized, crop_box = normalize_image(source_bytes, bbox)
    raw = rgb565_be(normalized)
    record_id = uuid.uuid5(uuid.NAMESPACE_URL, provenance["source_item_id"]).hex
    relative = Path("external") / label / f"{record_id}.rgb565"
    preview_relative = relative.with_suffix(".png")
    target = output / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    decode_rgb565(raw).save(output / preview_relative)
    provenance = {**provenance, "original_sha256": sha256_bytes(source_bytes),
                  "crop_box_source_pixels": crop_box, "converter_version": "gesture-external-import-v1",
                  "rgb565_quantization": "r>>3,g>>2,b>>3;big-endian;no-dither"}
    return {
        "record_id": record_id,
        "file": relative.as_posix(),
        "preview_file": preview_relative.as_posix(),
        "sha256": sha256_bytes(raw),
        "session": session,
        "session_id": session,
        "label": label,
        "split": split,
        "sensor_profile": "external_still_import_v1",
        "exposure_profile": "not_applicable_external_still",
        "capture_ms": 0,
        "capture_ms_kind": "not_available_external_still",
        "width": 320,
        "height": 240,
        "stride_bytes": 640,
        "byte_order": "msb_first",
        "pixel_format": "RGB565_BE",
        "device_id": session,
        "frame_id": index,
        "annotation_epoch": 0,
        "excluded": False,
        "source": "licensed_external_image",
        "label_provenance": "source_annotation_plus_mapping_review",
        "provenance": provenance,
    }


def spaced(items: list, count: int):
    if len(items) < count:
        raise ValueError(f"not enough candidates: {len(items)} < {count}")
    if count == 1:
        return [items[len(items) // 2]]
    return [items[round(index * (len(items) - 1) / (count - 1))] for index in range(count)]


def hands_candidates(annotation_path: Path):
    result = defaultdict(list)
    with annotation_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        for row in reader:
            basename = PurePosixPath(row["rgb"].replace("\\", "/")).name
            for source_label in HANDS_COLUMNS:
                bbox = parse_bbox(row[source_label])
                if bbox:
                    result[source_label].append((basename, bbox))
    for source_label in result:
        result[source_label].sort(key=lambda item: int(re.match(r"\d+", item[0]).group()))
    return result


def extract_hands(output: Path, cache: Path):
    allocations = {
        1: {"POINT_LEFT": 18, "POINT_RIGHT": 23},
        2: {"POINT_LEFT": 18, "POINT_RIGHT": 22},
        3: {"POINT_LEFT": 18, "POINT_RIGHT": 22},
        4: {"POINT_LEFT": 18, "POINT_RIGHT": 22},
        5: {"POINT_LEFT": 5, "POINT_RIGHT": 5},
    }
    def extract_subject(subject, targets):
        subject_rows = []
        item = HANDS_SUBJECTS[subject]
        candidates = hands_candidates(cache / f"Subject{subject}.txt")
        remote = HTTPRangeFile(item["zip_url"], item["zip_size"])
        with zipfile.ZipFile(remote) as archive:
            names = {PurePosixPath(name).name: name for name in archive.namelist() if name.lower().endswith("_color.png")}
            for label, count in targets.items():
                source_labels = [key for key, mapped in HANDS_MAP.items() if mapped == label]
                first_count = count // 2
                source_counts = [first_count, count - first_count]
                selected = []
                for source_label, source_count in zip(source_labels, source_counts):
                    selected.extend((source_label, value) for value in spaced(candidates[source_label], source_count))
                for source_label, (basename, bbox) in selected:
                    if basename not in names:
                        raise ValueError(f"Subject{subject}: {basename} is absent from ZIP")
                    source_bytes = archive.read(names[basename])
                    split = "calibration" if subject == 5 else "train"
                    session = f"hands-subject-{subject}"
                    provenance = {
                        "dataset": "HANDS static hand-gestures",
                        "dataset_version": "1",
                        "doi": "10.17632/ndrczc35bt.1",
                        "source_page_url": "https://data.mendeley.com/datasets/ndrczc35bt/1",
                        "asset_url": item["zip_url"],
                        "asset_sha256": item["zip_sha256"],
                        "source_item_id": f"hands-v1-subject-{subject}-{basename}-{source_label}",
                        "source_label": source_label,
                        "subject_id": f"subject-{subject}",
                        "license_spdx": "CC-BY-4.0",
                        "license_url": "https://creativecommons.org/licenses/by/4.0/",
                        "attribution": "Nuzzi, Pasinetti, Pagani, Coffetti, Sansoni (2021), HANDS",
                        "mapping_rule_id": f"hands-{source_label}-to-{label}",
                        "source_bbox_xywh": list(bbox),
                    }
                    subject_rows.append(write_external_frame(output, label, split, session, source_bytes,
                                                              bbox, provenance, len(subject_rows)))
        print(f"HANDS Subject{subject}: {sum(targets.values())} selected", flush=True)
        return subject_rows

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(extract_subject, subject, targets)
                   for subject, targets in allocations.items()]
        for future in futures:
            rows.extend(future.result())
    return rows


def hagrid_candidates(root: Path, annotations: dict, source_class: str):
    result = []
    for path in sorted((root / source_class).glob("*.jpg")):
        item_id = path.stem
        annotation = annotations[source_class].get(item_id)
        if not annotation:
            continue
        boxes = []
        for label, box in zip(annotation.get("labels", []), annotation.get("bboxes", [])):
            if label == source_class:
                boxes.append(box)
        if not boxes:
            continue
        box = max(boxes, key=lambda value: value[2] * value[3])
        with Image.open(path) as image:
            width, height = image.size
        bbox = (box[0] * width, box[1] * height, box[2] * width, box[3] * height)
        result.append({"path": path, "item_id": item_id, "user_id": annotation["user_id"], "bbox": bbox})
    return result


def extract_hagrid(output: Path, root: Path):
    annotations = json.loads((root / "annotations.json").read_text(encoding="utf-8"))
    quotas = {"FIST": 88, "PALM": 85, "V_SIGN": 87, "OTHER": 72}
    pools = {key: hagrid_candidates(root, annotations, key) for key in HAGRID_SIMPLE}
    other_pool = []
    per_other = [11, 11, 10, 10, 10, 10, 10]
    for source_class, count in zip(HAGRID_OTHER, per_other):
        other_pool.extend({**item, "source_class": source_class} for item in spaced(hagrid_candidates(root, annotations, source_class), count))
    pools["OTHER"] = other_pool

    calibration_users = set()
    calibration = defaultdict(list)
    for label in ("FIST", "PALM", "V_SIGN", "OTHER"):
        source_pool = pools[{"FIST": "fist", "PALM": "palm", "V_SIGN": "peace"}.get(label, "OTHER")]
        for item in source_pool:
            if item["user_id"] not in calibration_users:
                calibration[label].append(item)
                calibration_users.add(item["user_id"])
                if len(calibration[label]) == 5:
                    break
        if len(calibration[label]) != 5:
            raise ValueError(f"cannot select five unique calibration users for {label}")

    rows = []
    simple_reverse = {value: key for key, value in HAGRID_SIMPLE.items()}
    for label, total in quotas.items():
        key = simple_reverse.get(label, "OTHER")
        source_pool = pools[key]
        chosen_calibration = calibration[label]
        chosen_ids = {item["item_id"] for item in chosen_calibration}
        train_pool = [item for item in source_pool if item["item_id"] not in chosen_ids and item["user_id"] not in calibration_users]
        chosen_train = spaced(train_pool, total - 5)
        for split, chosen in (("calibration", chosen_calibration), ("train", chosen_train)):
            for item in chosen:
                source_class = item.get("source_class", key)
                source_bytes = item["path"].read_bytes()
                session = f"hagrid-user-{item['user_id']}"
                provenance = {
                    "dataset": "HaGRID 100-image-per-class convenience subset",
                    "dataset_version": "HaGRIDv2-derived subset snapshot 2026-09-18",
                    "source_page_url": "https://github.com/hukenovs/hagrid",
                    "mirror_url": "https://huggingface.co/datasets/GestureDetectionConnoisseurs/hagrid_subsets",
                    "source_item_id": f"hagrid-{item['item_id']}-{source_class}",
                    "source_label": source_class,
                    "subject_id": item["user_id"],
                    "license_id": "HaGRID custom attribution/share-alike-like license",
                    "license_url": "https://github.com/hukenovs/hagrid/blob/master/LICENSE",
                    "attribution": "Kapitanov et al., HaGRID",
                    "mapping_rule_id": f"hagrid-{source_class}-to-{label}",
                    "source_bbox_xywh": [round(value, 4) for value in item["bbox"]],
                }
                rows.append(write_external_frame(output, label, split, session, source_bytes,
                                                 item["bbox"], provenance, len(rows)))
    print(f"HaGRID: {len(rows)} selected", flush=True)
    return rows


def copy_personal(output: Path, manifest_path: Path):
    sys.path.insert(0, str(Path(__file__).parent))
    from dataset import read_dataset

    report, _ = read_dataset(manifest_path, complete=False)
    rejected = set(report["debug_quality_rejected"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = []
    for sample in manifest["samples"]:
        if sample["file"] in rejected:
            continue
        session = sample["session"]
        if session not in PERSONAL_SPLITS:
            raise ValueError(f"unknown personal session {session}")
        relative = Path("personal") / Path(sample["file"])
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest_path.parent / sample["file"], target)
        copied = {**sample, "file": relative.as_posix(), "split": PERSONAL_SPLITS[session]}
        if sample.get("preview_file"):
            preview_relative = Path("personal") / Path(sample["preview_file"])
            preview_target = output / preview_relative
            preview_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(manifest_path.parent / sample["preview_file"], preview_target)
            copied["preview_file"] = preview_relative.as_posix()
        copied["provenance"] = {
            "dataset": "personal OV2640 board capture",
            "source_manifest": str(manifest_path),
            "source_item_id": sample["record_id"],
            "original_sha256": sample["sha256"],
            "license_id": "user-owned capture",
        }
        rows.append(copied)
    return rows, sorted(rejected)


def build_dataset(personal_manifest: Path, hagrid_root: Path, hands_cache: Path, output: Path):
    raise ValueError("HANDS Horiz is not verified as single-index pointing; final build disabled pending reviewed RGB-NHG replacement")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory must be empty or absent: {output}")
    output.mkdir(parents=True, exist_ok=True)
    personal, rejected = copy_personal(output, personal_manifest.resolve())
    hands = extract_hands(output, hands_cache.resolve())
    hagrid = extract_hagrid(output, hagrid_root.resolve())
    samples = personal + hands + hagrid
    counts = Counter(row["label"] for row in samples)
    split_counts = {split: Counter(row["label"] for row in samples if row["split"] == split)
                    for split in ("train", "validation", "calibration", "test")}
    if len(personal) != 297 or len(hands) != 171 or len(hagrid) != 332 or len(samples) != 800:
        raise ValueError(f"unexpected totals personal={len(personal)}, hands={len(hands)}, hagrid={len(hagrid)}")
    expected = {"POINT_LEFT": 124, "POINT_RIGHT": 124, "FIST": 124, "PALM": 124,
                "V_SIGN": 124, "OTHER": 125, "EMPTY": 55}
    if dict(counts) != expected:
        raise ValueError(f"unexpected class totals: {dict(counts)}")
    manifest = {
        "schema_version": 1,
        "preprocessing": "rgb565-roi192-gray96-v1",
        "note": "Derived training dataset; original 308-frame personal manifest is preserved. Eleven near-black EMPTY frames are excluded here only.",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "samples": samples,
        "provenance_summary": {
            "personal_manifest": str(personal_manifest.resolve()),
            "personal_manifest_sha256": sha256_bytes(personal_manifest.read_bytes()),
            "personal_declared": 308,
            "personal_included": 297,
            "personal_quality_excluded": rejected,
            "external_included": 503,
            "external_sources": ["HANDS v1 (171)", "HaGRID subset (332)"],
            "class_counts": dict(counts),
            "split_counts": {key: dict(value) for key, value in split_counts.items()},
        },
    }
    (output / "dataset_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "SOURCES.md").write_text(
        "# External source attribution\n\n"
        "- HANDS v1, DOI 10.17632/ndrczc35bt.1, CC BY 4.0. Authors: Cristina Nuzzi, Simone Pasinetti, Roberto Pagani, Gabriele Coffetti, Giovanna Sansoni. Cropped/resized and RGB565-quantized.\n"
        "- HaGRID, Kapitanov et al. Convenience subset mirrored by GestureDetectionConnoisseurs. The upstream custom attribution/share-alike-like license is preserved in per-sample provenance; cropped/resized and RGB565-quantized.\n"
        "- Personal OV2640 captures remain user-owned. The source manifest was not modified.\n",
        encoding="utf-8",
    )
    print(json.dumps({"samples": len(samples), "counts": dict(counts),
                      "splits": {key: dict(value) for key, value in split_counts.items()},
                      "quality_excluded": len(rejected)}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect_parser = sub.add_parser("inspect-hands")
    inspect_parser.add_argument("--subject", type=int, default=1, choices=sorted(HANDS_SUBJECTS))
    inspect_parser.add_argument("--pattern")
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--personal-manifest", type=Path, required=True)
    build_parser.add_argument("--hagrid-root", type=Path, required=True)
    build_parser.add_argument("--hands-cache", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    hagrid_parser = sub.add_parser("stage-hagrid")
    hagrid_parser.add_argument("--hagrid-root", type=Path, required=True)
    hagrid_parser.add_argument("--output", type=Path, required=True)
    probe_parser = sub.add_parser("probe-videos")
    probe_parser.add_argument("--root", type=Path, required=True)
    probe_parser.add_argument("--output", type=Path, required=True)
    audit_parser = sub.add_parser("audit-candidates")
    audit_parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect-hands":
        inspect_hands(args.subject, args.pattern)
    elif args.command == "build":
        build_dataset(args.personal_manifest, args.hagrid_root, args.hands_cache, args.output)
    elif args.command == "stage-hagrid":
        args.output.mkdir(parents=True, exist_ok=True)
        rows = extract_hagrid(args.output, args.hagrid_root)
        (args.output / "candidate_rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    elif args.command == "probe-videos":
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Build" / "dataset-import-deps"))
        import cv2
        args.output.mkdir(parents=True, exist_ok=True)
        for label in ("point_left", "point_right"):
            paths = sorted((args.root / label).rglob("*.mp4"))
            selected = spaced(paths, 16)
            sheet = Image.new("RGB", (4 * 320, 4 * 340), "white")
            draw = ImageDraw.Draw(sheet)
            for index, path in enumerate(selected):
                cap = cv2.VideoCapture(str(path))
                count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                cap.set(cv2.CAP_PROP_POS_FRAMES, count // 2)
                okay, frame = cap.read()
                cap.release()
                if not okay:
                    raise ValueError(f"video decode failed {path}")
                im = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                im.save(args.output / (path.stem + ".png"))
                x, y = index % 4 * 320, index // 4 * 340
                sheet.paste(im.resize((320,320)), (x,y))
                draw.text((x,y+320), path.stem, fill="black")
            sheet.save(args.output / (label + "-sheet.jpg"))
    elif args.command == "audit-candidates":
        from dataset import read_dataset
        rows = json.loads((args.root / "candidate_rows.json").read_text(encoding="utf-8"))
        manifest = {"schema_version": 1, "preprocessing": "rgb565-roi192-gray96-v1", "samples": rows,
                    "status": "candidate_only_not_final_training_manifest"}
        manifest_path = args.root / "candidate_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        report, _ = read_dataset(manifest_path, complete=False)
        (args.root / "candidate_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        for start in range(0, len(rows), 48):
            batch = rows[start:start+48]
            sheet = Image.new("RGB", (8*160, 6*144), "white")
            draw = ImageDraw.Draw(sheet)
            for index, row in enumerate(batch):
                x,y = index%8*160,index//8*144
                with Image.open(args.root / row["preview_file"]) as im:
                    draw.rectangle((x,y,x+159,y+119), outline="gray")
                    sheet.paste(im.resize((160,120)),(x,y))
                draw.rectangle((x+32,y+12,x+128,y+108), outline="cyan")
                draw.text((x,y+120), f'{start+index}: {row["label"]}', fill="black")
            sheet.save(args.root / f'review-{start//48+1:02d}.jpg')
        print(json.dumps({key: value for key,value in report.items() if key!="samples"},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
