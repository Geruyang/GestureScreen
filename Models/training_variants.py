"""Deterministic FULL-training variants; no dataset, model, or hardware I/O."""
from __future__ import annotations

import hashlib
import json
import math


PERSONAL_SOURCE = "personal_board_capture"
AUGMENTATION_PROFILES = ("flip", "photo", "geometry", "photo_geometry",
                         "targeted_hard_classes")
CHECKPOINT_METRICS = ("val_loss", "val_accuracy")


def checkpoint_selection_key(entry, metric):
    """Return a max() key; earlier epoch wins exact ties."""
    epoch = int(entry["epoch"])
    if metric == "val_loss":
        return (-float(entry["val_loss"]), -epoch)
    if metric == "val_accuracy":
        # Integer correct_count is the exact primary accuracy key. Fall back
        # only for historical/unit-test records that predate this field.
        primary = int(entry["val_correct_count"]) if "val_correct_count" in entry else float(entry["val_accuracy"])
        return (primary, float(entry["val_macro_f1"]),
                -float(entry["val_loss"]), -epoch)
    raise ValueError(f"unsupported checkpoint metric: {metric}")


def select_checkpoint_entry(entries, metric):
    if not entries:
        raise ValueError("checkpoint selection needs at least one epoch")
    return max(entries, key=lambda entry: checkpoint_selection_key(entry, metric))


def augmentation_evidence(profile):
    if profile not in AUGMENTATION_PROFILES:
        raise ValueError(f"unsupported augmentation profile: {profile}")
    targeted = profile == "targeted_hard_classes"
    photo = profile in ("photo", "photo_geometry") or targeted
    geometry = profile in ("geometry", "photo_geometry") or targeted
    return {
        "profile": profile,
        "pipeline_order": ["horizontal_flip", "photo", "geometry", "blur"],
        "applied_split": "train",
        "validation_augmented": False,
        "raw_or_inference_preprocessing_changed": False,
        "flip": {"probability": .5, "horizontal_only": True,
                 "swap_point_left_right_target": True,
                 "rng_stream": "SeedSequence(seed,epoch,batch,2701)"},
        "photo": {"enabled": photo, "probability": .8 if photo else 0.0,
                  "contrast_range": [.85, 1.15], "contrast_center": 127.5,
                  "brightness_range": [-15.0, 15.0], "clip_range": [0.0, 255.0],
                  "rng_stream": "SeedSequence(seed,epoch,batch,3701)"},
        "geometry": {"enabled": geometry, "probability": .8 if geometry else 0.0,
                     "translation_pixels": [-4.0, 4.0], "isotropic_scale": [.95, 1.05],
                     "rotation_degrees": [-8.0, 8.0], "interpolation": "bilinear",
                     "boundary": "edge", "vertical_flip": False, "right_angle_rotation": False,
                     "rng_stream": "SeedSequence(seed,epoch,batch,4701)"},
        "targeted": {
            "enabled": targeted,
            "labels": ["POINT_LEFT", "POINT_RIGHT", "PALM", "V_SIGN", "OTHER"],
            "photo_probability": {"targeted": .9, "other": .7},
            "contrast_range": [.8, 1.2],
            "brightness_range": [-18.0, 18.0],
            "geometry_probability": {"targeted": .9, "other": .75},
            "translation_pixels": [-5.0, 5.0],
            "isotropic_scale": [.95, 1.08],
            "rotation_degrees": [-10.0, 10.0],
            "blur_probability": {"targeted": .2, "other": .1},
            "blur_kernel": "separable [1,2,1]/4 with edge padding",
            "rng_streams": ["SeedSequence(seed,epoch,batch,3701)",
                            "SeedSequence(seed,epoch,batch,4701)",
                            "SeedSequence(seed,epoch,batch,5703)"],
        },
        "deterministic_per_seed_epoch_batch": True,
        "independent_rng_streams": True,
    }


def _bilinear_affine_edge(image, translate_x, translate_y, scale, rotation_degrees):
    """Inverse-map one HWC image with bilinear interpolation and edge padding."""
    import numpy as np
    height, width, channels = image.shape
    yy, xx = np.meshgrid(np.arange(height, dtype=np.float64),
                         np.arange(width, dtype=np.float64), indexing="ij")
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    out_x = xx - center_x - float(translate_x)
    out_y = yy - center_y - float(translate_y)
    radians = math.radians(float(rotation_degrees))
    cosine, sine = math.cos(radians), math.sin(radians)
    source_x = (cosine * out_x + sine * out_y) / float(scale) + center_x
    source_y = (-sine * out_x + cosine * out_y) / float(scale) + center_y
    source_x = np.clip(source_x, 0.0, width - 1.0)
    source_y = np.clip(source_y, 0.0, height - 1.0)
    x0 = np.floor(source_x).astype(np.int64)
    y0 = np.floor(source_y).astype(np.int64)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    wx = (source_x - x0)[..., None]
    wy = (source_y - y0)[..., None]
    top = image[y0, x0, :] * (1.0 - wx) + image[y0, x1, :] * wx
    bottom = image[y1, x0, :] * (1.0 - wx) + image[y1, x1, :] * wx
    return (top * (1.0 - wy) + bottom * wy).reshape(height, width, channels).astype(np.float32)


def _gaussian_blur_3x3_edge(image):
    """Apply a small deterministic separable blur without changing shape or range."""
    import numpy as np
    horizontal = np.pad(image, ((0, 0), (1, 1), (0, 0)), mode="edge")
    horizontal = (horizontal[:, :-2, :] + 2.0 * horizontal[:, 1:-1, :] +
                  horizontal[:, 2:, :]) * .25
    vertical = np.pad(horizontal, ((1, 1), (0, 0), (0, 0)), mode="edge")
    return ((vertical[:-2, :, :] + 2.0 * vertical[1:-1, :, :] +
             vertical[2:, :, :]) * .25).astype(np.float32)


def augment_training_batch(images, targets, profile, seed, epoch, batch_number, flip_label):
    """Apply deterministic train-only augmentation without touching caller arrays."""
    import numpy as np
    augmentation_evidence(profile)
    result = np.asarray(images, dtype=np.float32).copy()
    output_targets = np.asarray(targets).copy()
    flip_rng = np.random.default_rng(np.random.SeedSequence([seed, epoch, batch_number, 2701]))
    flips = flip_rng.random(len(result)) < .5
    result[flips] = result[flips, :, ::-1, :]
    output_targets[flips] = [flip_label(int(label)) for label in output_targets[flips]]

    targeted_profile = profile == "targeted_hard_classes"
    targeted_labels = np.isin(output_targets, (0, 1, 3, 4, 5))

    if profile in ("photo", "photo_geometry", "targeted_hard_classes"):
        photo_rng = np.random.default_rng(np.random.SeedSequence([seed, epoch, batch_number, 3701]))
        probability = np.where(targeted_labels, .9, .7) if targeted_profile else .8
        apply = photo_rng.random(len(result)) < probability
        contrast = photo_rng.uniform(.8 if targeted_profile else .85,
                                     1.2 if targeted_profile else 1.15, len(result))
        brightness = photo_rng.uniform(-18.0 if targeted_profile else -15.0,
                                       18.0 if targeted_profile else 15.0, len(result))
        for number in np.flatnonzero(apply):
            result[number] = np.clip((result[number] - 127.5) * contrast[number] +
                                     127.5 + brightness[number], 0.0, 255.0)

    if profile in ("geometry", "photo_geometry", "targeted_hard_classes"):
        geometry_rng = np.random.default_rng(np.random.SeedSequence([seed, epoch, batch_number, 4701]))
        probability = np.where(targeted_labels, .9, .75) if targeted_profile else .8
        apply = geometry_rng.random(len(result)) < probability
        extent = 5.0 if targeted_profile else 4.0
        translate_x = geometry_rng.uniform(-extent, extent, len(result))
        translate_y = geometry_rng.uniform(-extent, extent, len(result))
        scale = geometry_rng.uniform(.95, 1.08 if targeted_profile else 1.05, len(result))
        rotation = geometry_rng.uniform(-10.0 if targeted_profile else -8.0,
                                        10.0 if targeted_profile else 8.0, len(result))
        for number in np.flatnonzero(apply):
            result[number] = _bilinear_affine_edge(
                result[number], translate_x[number], translate_y[number],
                scale[number], rotation[number])
    if targeted_profile:
        blur_rng = np.random.default_rng(np.random.SeedSequence([seed, epoch, batch_number, 5703]))
        probability = np.where(targeted_labels, .2, .1)
        apply = blur_rng.random(len(result)) < probability
        for number in np.flatnonzero(apply):
            result[number] = _gaussian_blur_3x3_edge(result[number])
        result = np.clip(result, 0.0, 255.0)
    return result, output_targets


def _covered_sample(pool, count, rng):
    """Sample without replacement first, then at most one repeated pass."""
    import numpy as np
    pool = np.asarray(pool, dtype=np.int64)
    if count < 0 or count > 2 * len(pool):
        raise ValueError("requested source sample count exceeds per-image repeat cap 2")
    if count == 0:
        return np.empty(0, dtype=np.int64)
    first = rng.permutation(pool)
    if count <= len(pool):
        return first[:count]
    second = rng.permutation(pool)
    return np.concatenate([first, second[:count-len(pool)]])


def _index_sha256(indexes):
    payload = json.dumps([int(index) for index in indexes], separators=(",", ":")).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def epoch_training_indexes(base_indexes, labels, sources, label_names,
                           personal_factor, seed, epoch):
    """Return deterministic indexes and a complete sampling audit for one epoch."""
    import numpy as np
    if not math.isfinite(personal_factor) or personal_factor <= 0:
        raise ValueError("personal sampling factor must be finite and positive")
    base = np.asarray(base_indexes, dtype=np.int64)
    labels = np.asarray(labels)
    sources = np.asarray(sources, dtype=object)
    if personal_factor == 1.0:
        selected = base.copy()
        np.random.default_rng(np.random.SeedSequence([seed, epoch, 1701])).shuffle(selected)
        policy = "legacy_no_replacement_shuffle"
    else:
        pieces = []
        for label, _name in enumerate(label_names):
            class_pool = base[labels[base] == label]
            personal = class_pool[sources[class_pool] == PERSONAL_SOURCE]
            external = class_pool[sources[class_pool] != PERSONAL_SOURCE]
            denominator = personal_factor * len(personal) + len(external)
            if denominator <= 0:
                raise ValueError(f"empty class pool for {_name}")
            personal_target = int(round(len(class_pool) * personal_factor * len(personal) / denominator))
            external_target = len(class_pool) - personal_target
            personal_rng = np.random.default_rng(
                np.random.SeedSequence([seed, epoch, label, 5701]))
            external_rng = np.random.default_rng(
                np.random.SeedSequence([seed, epoch, label, 5702]))
            pieces.extend((_covered_sample(personal, personal_target, personal_rng),
                           _covered_sample(external, external_target, external_rng)))
        selected = np.concatenate(pieces)
        np.random.default_rng(np.random.SeedSequence([seed, epoch, 6701])).shuffle(selected)
        policy = "per_class_source_weighted_coverage_first"

    occurrences = np.bincount(selected, minlength=len(labels))
    selected_labels = labels[selected]
    selected_sources = sources[selected]
    class_counts = {name: int(np.sum(selected_labels == label))
                    for label, name in enumerate(label_names)}
    source_counts = {str(source): int(np.sum(selected_sources == source))
                     for source in sorted(set(selected_sources.tolist()))}
    source_class_counts = {
        name: {str(source): int(np.sum((selected_labels == label) & (selected_sources == source)))
               for source in sorted(set(selected_sources.tolist()))}
        for label, name in enumerate(label_names)
    }
    audit = {"epoch": int(epoch) + 1, "sample_count": int(len(selected)),
             "unique_index_count": int(np.count_nonzero(occurrences)),
             "maximum_index_repeats": int(occurrences.max()) if len(occurrences) else 0,
             "index_sha256": _index_sha256(selected), "class_counts": class_counts,
             "source_counts": source_counts, "source_class_counts": source_class_counts,
             "policy": policy}
    if len(selected) != len(base) or any(class_counts[name] != int(np.sum(labels[base] == label))
                                         for label, name in enumerate(label_names)):
        raise ValueError("personal sampling changed epoch length or original class counts")
    if audit["maximum_index_repeats"] > 2:
        raise ValueError("personal sampling exceeded per-image repeat cap 2")
    return selected, audit


def sampling_evidence(base_indexes, labels, sources, label_names, personal_factor):
    """Describe source weighting without constructing a training epoch."""
    import numpy as np
    base = np.asarray(base_indexes, dtype=np.int64)
    labels = np.asarray(labels)
    sources = np.asarray(sources, dtype=object)
    original = {}
    targets = {}
    for label, name in enumerate(label_names):
        class_pool = base[labels[base] == label]
        personal_count = int(np.sum(sources[class_pool] == PERSONAL_SOURCE))
        external_count = int(len(class_pool) - personal_count)
        if personal_factor == 1.0:
            target = personal_count
        else:
            denominator = personal_factor * personal_count + external_count
            if denominator <= 0:
                raise ValueError(f"empty class pool for {name}")
            target = int(round(len(class_pool) * personal_factor * personal_count / denominator))
            if target > 2 * personal_count or len(class_pool)-target > 2 * external_count:
                raise ValueError(f"personal sampling factor violates repeat cap for {name}")
        original[name] = {"personal": personal_count, "external": external_count,
                          "total": int(len(class_pool))}
        targets[name] = {"personal": target, "external": int(len(class_pool)-target),
                         "total": int(len(class_pool))}
    return {"personal_factor": float(personal_factor), "personal_source": PERSONAL_SOURCE,
            "applied_split": "train", "validation_or_test_resampled": False,
            "epoch_sample_count": int(len(base)), "preserve_original_class_counts": True,
            "coverage_before_repeat": True, "maximum_repeats_per_index_per_epoch": 2,
            "shuffle_rng_independent_from_augmentation": True,
            "factor_one_legacy_compatible": personal_factor == 1.0,
            "original_source_class_counts": original, "target_source_class_counts": targets}
