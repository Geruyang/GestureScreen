"""读取实际 TFLite I/O，并生成保持业务门禁关闭的七类候选元数据。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

from dataset import LABELS, PREPROCESS_VERSION


def tensorflow():
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")
    import tensorflow as tf
    return tf


def inspect_model(path: Path):
    """使用已安装运行库解析实际模型，不从模型名推断类别或量化。"""
    tf = tensorflow()
    interpreter = tf.lite.Interpreter(model_path=str(path))
    interpreter.allocate_tensors()

    def tensor(info):
        quant = info["quantization_parameters"]
        return dict(name=info["name"], shape=info["shape"].tolist(),
                    shape_signature=info["shape_signature"].tolist(), dtype=info["dtype"].__name__,
                    scales=quant["scales"].tolist(), zero_points=quant["zero_points"].tolist(),
                    quantized_dimension=int(quant["quantized_dimension"]))

    return dict(model_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                file_bytes=path.stat().st_size, tensorflow_version=tf.__version__,
                inputs=[tensor(t) for t in interpreter.get_input_details()],
                outputs=[tensor(t) for t in interpreter.get_output_details()],
                tensor_dtypes=sorted({t["dtype"].__name__ for t in interpreter.get_tensor_details()}),
                validated_for_business=False)


def contract_errors(report):
    errors = []
    if len(report["inputs"]) != 1 or len(report["outputs"]) != 1:
        return ["requires one input and one output"]
    inp, out = report["inputs"][0], report["outputs"][0]
    if inp["shape"] != [1, 96, 96, 1] or inp["dtype"] != "int8":
        errors.append("input must be [1,96,96,1] int8")
    if inp["scales"] != [1.0] or inp["zero_points"] != [-128]:
        errors.append("input quantization must be scale=1, zero_point=-128; do not relabel exported values")
    if out["shape"] != [1, 7] or out["dtype"] != "int8":
        errors.append("output must be [1,7] int8; source five-class model is not a business model")
    if (len(out["scales"]) != 1 or not math.isfinite(out["scales"][0]) or out["scales"][0] <= 0
            or len(out["zero_points"]) != 1 or not -128 <= out["zero_points"][0] <= 127):
        errors.append("output requires finite positive per-tensor scale and int8 zero point")
    if any(t.startswith("float") or t.startswith("complex") for t in report["tensor_dtypes"]):
        errors.append("float/complex tensors remain; full integer conversion required")
    if report["file_bytes"] > 327680:
        errors.append("TFLite candidate exceeds model asset budget 320 KiB (final C/map still required)")
    return errors


def write_candidate(model_path: Path, output: Path, *, model_id: str, kind: str):
    report = inspect_model(model_path)
    errors = contract_errors(report)
    if errors:
        raise ValueError("; ".join(errors))
    if kind not in ("int8_logits", "int8_probabilities"):
        raise ValueError("declare actual export semantics explicitly")
    if not model_id or any(ord(c) < 32 for c in model_id):
        raise ValueError("model_id must be nonempty printable text")
    out = report["outputs"][0]
    if kind == "int8_probabilities" and out["scales"][0] > 1:
        raise ValueError("probability scale must be <= 1")
    contract = json.loads((Path(__file__).parent / "model_contract.json").read_text(encoding="utf-8"))
    contract.update(model_id=model_id, model_sha256=report["model_sha256"],
                    status="candidate_awaiting_F4_conversion_and_real_acceptance", backend="not_generated",
                    validated_for_business=False)
    contract["output"].update(actual_kind=kind, actual_scale=out["scales"][0], actual_zero_point=out["zero_points"][0])
    output.mkdir(parents=True, exist_ok=True)
    (output / "candidate_contract.json").write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    (output / "tflite_audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    kind_c = "GS_AI_OUTPUT_INT8_LOGITS" if kind == "int8_logits" else "GS_AI_OUTPUT_INT8_PROBABILITIES"
    c = ("/* Actual exported metadata. Candidate only: gs_ai_init must reject business use. */\n"
         "#ifndef GS_MODEL_METADATA_CANDIDATE_H\n#define GS_MODEL_METADATA_CANDIDATE_H\n#include \"gs_ai.h\"\n"
         f"#define GS_MODEL_SHA256 \"{report['model_sha256']}\"\n"
         "static const gs_ai_metadata_t gs_model_metadata_candidate = {\n"
         f"    1U, {json.dumps(model_id, ensure_ascii=True)}, \"{PREPROCESS_VERSION}\",\n"
         "    {1U,96U,96U,1U}, 1.0f, -128, 7U,\n"
         "    {" + ",".join(json.dumps(x) for x in LABELS) + "},\n"
         f"    {kind_c}, {out['scales'][0]:.17e}f, {out['zero_points'][0]},\n"
         "    0U /* No automated command changes this release gate. */\n};\n#endif\n")
    (output / "gs_model_metadata_candidate.h").write_text(c, encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--candidate-dir", type=Path)
    parser.add_argument("--model-id")
    parser.add_argument("--output-kind", choices=("int8_logits", "int8_probabilities"))
    args = parser.parse_args()
    try:
        if args.candidate_dir:
            if not args.model_id or not args.output_kind:
                parser.error("candidate export requires --model-id and --output-kind from training provenance")
            report = write_candidate(args.model, args.candidate_dir, model_id=args.model_id, kind=args.output_kind)
        else:
            report = inspect_model(args.model)
        report["contract_errors"] = contract_errors(report)
        content = json.dumps(report, indent=2) + "\n"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(content, encoding="utf-8")
        print(content)
        return 2 if report["contract_errors"] else 0
    except (ImportError, ValueError, OSError) as error:
        parser.exit(2, f"Model unavailable/rejected: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
