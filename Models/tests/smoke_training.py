"""临时合成数据只验证训练/导出程序可执行；销毁权重，绝不产出业务模型。"""
from __future__ import annotations

from argparse import Namespace
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dataset import LABELS, PREPROCESS_VERSION
from train import train


def main():
    project = Path(__file__).resolve().parents[2]
    build = (project / "Build/model-training-test").resolve()
    build.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="synthetic-only-", dir=build) as temp:
        root = Path(temp).resolve()
        if not root.is_relative_to(build):
            raise RuntimeError("test workspace escaped intended build directory")
        rng = random.Random(20260915)
        samples = []
        for split in ("train", "validation", "calibration", "test"):
            for i, label in enumerate(LABELS):
                data = bytearray(rng.randbytes(320 * 240 * 2))
                # 固定值是量化范围测试向量，不宣称来自实际相机或属于七类手势。
                for value, x in ((b"\x00\x00", 64), (b"\xff\xff", 66)):
                    for y in (24, 25):
                        data[y * 640 + x * 2:y * 640 + x * 2 + 4] = value * 2
                file = root / f"{split}_{i}.rgb565"
                file.write_bytes(data)
                samples.append(dict(file=file.name, sha256=hashlib.sha256(data).hexdigest(),
                                    label=label, split=split, session=f"SYNTHETIC_{split}",
                                    sensor_profile="SYNTHETIC_TEST_ONLY", exposure_profile="SYNTHETIC_TEST_ONLY",
                                    width=320, height=240, stride_bytes=640, byte_order="msb_first", capture_ms=i))
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps(dict(schema_version=1, preprocessing=PREPROCESS_VERSION, samples=samples)), encoding="utf-8")
        args = Namespace(manifest=manifest, output=root / "output", seed=20260915,
                         pretrained=project.parent / "artifacts/model_audit/arm_openmv/pretrained/model",
                         model_id="SYNTHETIC_SOFTWARE_TEST_NOT_A_GESTURE_MODEL", batch_size=7,
                         head_epochs=1, finetune_epochs=1, head_lr=.001, finetune_lr=.00001,
                         unfreeze_layers=12, representative_limit=7)
        train(args)
        report = json.loads((args.output / "training_report.json").read_text(encoding="utf-8"))
        audit = report["tflite_audit"]
        subprocess.run([sys.executable, str(Path(__file__).with_name("verify_seven_c.py")),
                        str(args.output / "gesture_seven.int8.tflite"), str(root / "c_export")], check=True)
        evidence = dict(status="software_train_and_export_path_passed", elapsed_seconds=round(time.monotonic() - started, 3),
                        scope="Synthetic fixtures validate software only; accuracy is intentionally omitted; all generated weights destroyed.",
                        tensorflow=audit["tensorflow_version"], source_files_sha256=report["source_files_sha256"],
                        export_inputs=audit["inputs"], export_outputs=audit["outputs"],
                        tensor_dtypes=audit["tensor_dtypes"], c_export_msvc_and_ac6_compilation=True,
                        seven_class_c_numeric_and_closed_gate=True, validated_for_business=False)
        (project / "Models/validation/training_smoke.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print("Synthetic software training/export path passed; temporary models removed.")


if __name__ == "__main__":
    main()
