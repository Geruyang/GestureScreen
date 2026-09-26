"""把受支持的实际全 int8 TFLite 静态链导出为无需 CubeAI 的 C 参考后端。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess

from model_package import tensorflow, write_candidate


def quantized_multiplier(value):
    fraction, shift = math.frexp(value)
    multiplier = int(math.floor(fraction * (1 << 31) + .5))
    if multiplier == 1 << 31:
        multiplier //= 2
        shift += 1
    if shift < -31:
        return 0, 0
    if not -31 <= shift <= 30:
        raise ValueError("unsupported requantization shift")
    return multiplier, shift


def read_graph(path):
    tensorflow()
    import numpy as np
    from tensorflow.lite.python import schema_py_generated as schema
    data = path.read_bytes()
    if len(data) < 8 or data[4:8] != b"TFL3":
        raise ValueError("not a TFLite FlatBuffer")
    model = schema.Model.GetRootAsModel(data, 0)
    if model.Version() != 3 or model.SubgraphsLength() != 1:
        raise ValueError("requires TFLite schema3 and one static subgraph")
    graph = model.Subgraphs(0)
    if graph.InputsLength() != 1 or graph.OutputsLength() != 1:
        raise ValueError("requires one input/output")

    def tensor(index, dtype):
        item = graph.Tensors(index)
        if item.Type() != dtype or item.IsVariable() or item.Sparsity() is not None:
            raise ValueError(f"tensor {index}: unsupported dtype/variable/sparsity")
        shape = [int(x) for x in item.ShapeAsNumpy()]
        if any(x <= 0 or x > 1024 for x in shape) or math.prod(shape) > 1048576:
            raise ValueError(f"tensor {index}: invalid/oversized shape")
        quant = item.Quantization()
        if quant is None or quant.DetailsType() != 0:
            raise ValueError(f"tensor {index}: missing/unsupported quantization")
        scales, zeros = list(quant.ScaleAsNumpy()), list(quant.ZeroPointAsNumpy())
        if not scales or len(zeros) != len(scales) or any(not math.isfinite(x) or x <= 0 for x in scales):
            raise ValueError(f"tensor {index}: invalid quantization")
        return item, shape, [float(x) for x in scales], [int(x) for x in zeros], quant.QuantizedDimension()

    def activation(index):
        item, shape, scales, zeros, _ = tensor(index, schema.TensorType.INT8)
        if len(scales) != 1 or not -128 <= zeros[0] <= 127:
            raise ValueError("activations require per-tensor int8 quantization")
        return item, shape, scales[0], zeros[0]

    first = int(graph.Inputs(0))
    _, initial_shape, initial_scale, initial_zero = activation(first)
    if initial_shape != [1, 96, 96, 1] or initial_scale != 1 or initial_zero != -128:
        raise ValueError("input differs from fixed gs_preprocess int8 contract")
    previous = first
    layers = []
    operations = []
    for number in range(graph.OperatorsLength()):
        operation = graph.Operators(number)
        opcode = model.OperatorCodes(operation.OpcodeIndex())
        code = max(opcode.BuiltinCode(), opcode.DeprecatedBuiltinCode())
        if opcode.CustomCode() is not None or operation.OutputsLength() != 1 or int(operation.Inputs(0)) != previous:
            raise ValueError(f"operator {number}: custom/multiple output/nonlinear graph unsupported")
        _, input_shape, input_scale, input_zero = activation(previous)
        out_index = int(operation.Outputs(0))
        _, output_shape, output_scale, output_zero = activation(out_index)
        if code == schema.BuiltinOperator.RESHAPE:
            if math.prod(input_shape) != math.prod(output_shape) or (input_scale, input_zero) != (output_scale, output_zero):
                raise ValueError("reshape must preserve element count and quantization")
            previous = out_index
            operations.append("RESHAPE(no-copy)")
            continue
        if len(input_shape) != 4 or len(output_shape) != 4 or input_shape[0] != 1 or output_shape[0] != 1:
            raise ValueError("only batch1 NHWC kernels supported")
        ih, iw, ic = input_shape[1:]
        oh, ow, oc = output_shape[1:]
        table = operation.BuiltinOptions()
        if table is None:
            raise ValueError("missing builtin options")
        if code == schema.BuiltinOperator.CONV_2D:
            option, kind = schema.Conv2DOptions(), 1
        elif code == schema.BuiltinOperator.DEPTHWISE_CONV_2D:
            option, kind = schema.DepthwiseConv2DOptions(), 2
        elif code == schema.BuiltinOperator.AVERAGE_POOL_2D:
            option, kind = schema.Pool2DOptions(), 3
        else:
            raise ValueError(f"operator {number}: unsupported builtin {code}")
        option.Init(table.Bytes, table.Pos)
        stride_h, stride_w = option.StrideH(), option.StrideW()
        if kind != 3 and (option.DilationHFactor() != 1 or option.DilationWFactor() != 1):
            raise ValueError("dilation other than1 unsupported")
        if kind == 2 and (option.DepthMultiplier() != 1 or ic != oc):
            raise ValueError("only depth_multiplier=1 supported")
        if kind == 3:
            if operation.InputsLength() != 1 or ic != oc or (input_scale, input_zero) != (output_scale, output_zero):
                raise ValueError("average pool requires equal input/output quantization and channels")
            kh, kw = option.FilterHeight(), option.FilterWidth()
            weights = bias = multipliers = shifts = None
        else:
            if operation.InputsLength() != 3:
                raise ValueError("convolution requires explicit constant weights and bias")
            w, w_shape, w_scales, w_zeros, w_dim = tensor(int(operation.Inputs(1)), schema.TensorType.INT8)
            b, b_shape, b_scales, b_zeros, _ = tensor(int(operation.Inputs(2)), schema.TensorType.INT32)
            if len(w_shape) != 4 or w_shape[0] != (oc if kind == 1 else 1) or w_shape[3] != (ic if kind == 1 else oc):
                raise ValueError("unexpected convolution filter layout")
            if (len(w_scales) not in (1, oc) or any(w_zeros) or (len(w_scales) > 1 and w_dim != (0 if kind == 1 else 3))
                    or b_shape != [oc] or any(b_zeros) or len(b_scales) not in (1, oc)):
                raise ValueError("unsupported per-channel weights/bias quantization")
            kh, kw = w_shape[1:3]
            weights = np.frombuffer(model.Buffers(w.Buffer()).DataAsNumpy().tobytes(), dtype=np.int8)
            bias = np.frombuffer(model.Buffers(b.Buffer()).DataAsNumpy().tobytes(), dtype="<i4")
            if len(weights) != math.prod(w_shape) or len(bias) != oc:
                raise ValueError("constant buffer length mismatch")
            multipliers, shifts = [], []
            for channel in range(oc):
                ws, bs = w_scales[channel if len(w_scales) > 1 else 0], b_scales[channel if len(b_scales) > 1 else 0]
                if not math.isclose(bs, input_scale * ws, rel_tol=1e-5, abs_tol=1e-12):
                    raise ValueError("bias scale differs from input_scale*weight_scale")
                multiplier, shift = quantized_multiplier(input_scale * ws / output_scale)
                # 保守上界覆盖任意int8输入、所有padding；避免C有符号累加/左移溢出。
                if kind == 1:
                    channel_weights = weights.reshape(oc, kh, kw, ic)[channel]
                else:
                    channel_weights = weights.reshape(kh, kw, oc)[:, :, channel]
                bound = max(abs(-128 - input_zero), abs(127 - input_zero)) * int(np.abs(channel_weights.astype(np.int32)).sum()) + abs(int(bias[channel]))
                if bound * (1 << max(shift, 0)) > 2147483647:
                    raise ValueError("int32 accumulator/requantization overflow bound exceeded")
                multipliers.append(multiplier)
                shifts.append(shift)
        if min(kh, kw, stride_h, stride_w) <= 0 or max(kh, kw, stride_h, stride_w) > 96:
            raise ValueError("invalid kernel/stride")
        if option.Padding() == schema.Padding.SAME:
            expected = ((ih + stride_h - 1) // stride_h, (iw + stride_w - 1) // stride_w)
            pad_h = max((oh - 1) * stride_h + kh - ih, 0) // 2
            pad_w = max((ow - 1) * stride_w + kw - iw, 0) // 2
        elif option.Padding() == schema.Padding.VALID:
            expected = ((ih - kh) // stride_h + 1, (iw - kw) // stride_w + 1)
            pad_h = pad_w = 0
        else:
            raise ValueError("unknown padding")
        if expected != (oh, ow):
            raise ValueError("declared output shape inconsistent with kernel")
        fused = option.FusedActivationFunction()
        amin, amax = -128, 127
        if fused in (schema.ActivationFunctionType.RELU, schema.ActivationFunctionType.RELU6):
            amin = max(-128, output_zero)
            if fused == schema.ActivationFunctionType.RELU6:
                amax = min(127, int(math.floor(6 / output_scale + .5)) + output_zero)
        elif fused != schema.ActivationFunctionType.NONE:
            raise ValueError("only NONE/RELU/RELU6 fused activation supported")
        dimensions = [ih, iw, ic, oh, ow, oc, kh, kw, stride_h, stride_w, pad_h, pad_w]
        layers.append(dict(dimensions=dimensions, quant=[input_zero, output_zero, amin, amax], kind=kind,
                           weights=weights, bias=bias, multipliers=multipliers, shifts=shifts))
        operations.append({1: "CONV_2D", 2: "DEPTHWISE_CONV_2D", 3: "AVERAGE_POOL_2D"}[kind])
        previous = out_index
    if previous != graph.Outputs(0) or not layers:
        raise ValueError("graph output is not end of supported chain")
    _, final_shape, _, _ = activation(previous)
    return layers, operations, math.prod(final_shape)


def export(model_path, output, *, model_id="candidate", reference_five=False):
    layers, operations, count = read_graph(model_path)
    if count != (5 if reference_five else 7):
        raise ValueError("output count differs from explicitly selected reference/business shape")
    slot = max(math.prod(layer["dimensions"][3:6]) for layer in layers)
    if slot * 2 + 9216 + 1024 > 114688:
        raise ValueError("reference workspace + input + management reserve exceeds112KiB")
    output.mkdir(parents=True, exist_ok=True)
    if not reference_five:
        write_candidate(model_path, output, model_id=model_id, kind="int8_logits")
    lines = ["/* Generated from actual TFLite weights; do not edit or relabel. */", '#include "gs_ai_int8_backend.h"']
    if not reference_five:
        lines.append('#include "gs_model_metadata_candidate.h"')
    stored_bytes = 0

    def array(name, values, ctype, width):
        nonlocal stored_bytes
        values = [str(int(v)) for v in values]
        stored_bytes += len(values) * width
        lines.append(f"static const {ctype} {name}[] = {{")
        lines.extend("    " + ",".join(values[start:start + 24]) + "," for start in range(0, len(values), 24))
        lines.append("};")

    entries = []
    for index, layer in enumerate(layers):
        names = []
        for field, ctype, width in (("weights", "int8_t", 1), ("bias", "int32_t", 4),
                                   ("multipliers", "int32_t", 4), ("shifts", "int8_t", 1)):
            name = f"gs_layer_{index}_{field}"
            if layer[field] is None:
                names.append("NULL")
            else:
                array(name, layer[field], ctype, width)
                names.append(name)
        entries.append("    {" + ",".join(str(x) for x in layer["dimensions"] + layer["quant"] + [layer["kind"]]) + "," + ",".join(names) + "},")
    lines.append("static const gs_int8_layer_t gs_layers[] = {")
    lines.extend(entries)
    lines.append("};")
    lines.append(f"static const gs_int8_model_t gs_network = {{gs_layers,{len(layers)}U,9216U,{count}U,{slot}U}};")
    lines.append(f"static int8_t gs_workspace[{slot * 2}];")
    lines.append("const gs_int8_model_t *gs_model_network(void) { return &gs_network; }")
    lines.append(f"gs_ai_status_t gs_model_raw_run(const int8_t *input, int8_t *output) {{ return gs_int8_execute(&gs_network,input,9216U,output,{count}U,gs_workspace,sizeof(gs_workspace)); }}")
    if not reference_five:
        lines.extend(["static gs_int8_context_t gs_runtime = {&gs_network,gs_workspace,sizeof(gs_workspace)};",
                      "static const gs_ai_backend_t gs_candidate = {&gs_model_metadata_candidate,gs_int8_backend_infer,&gs_runtime};",
                      "const gs_ai_backend_t *gs_model_candidate_backend(void) { return &gs_candidate; }"])
    (output / "gs_model_weights.c").write_text("\n".join(lines) + "\n", encoding="utf-8")
    header = ('#ifndef GS_MODEL_WEIGHTS_H\n#define GS_MODEL_WEIGHTS_H\n#include "gs_ai_int8_backend.h"\n'
              'const gs_int8_model_t *gs_model_network(void);\n'
              'gs_ai_status_t gs_model_raw_run(const int8_t *input, int8_t *output);\n')
    if not reference_five:
        header += 'const gs_ai_backend_t *gs_model_candidate_backend(void);\n'
    (output / "gs_model_weights.h").write_text(header + '#endif\n', encoding="utf-8")
    # F429每个描述符按52B conservatively核算；最终Keil map是实际占用证据。
    flash_estimate = stored_bytes + len(layers) * 52 + 128
    if flash_estimate > 327680:
        raise ValueError("generated constant asset estimate exceeds320KiB")
    report = dict(model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(), operations=operations,
                  output_count=count, workspace_bytes=slot * 2, input_bytes=9216,
                  constant_array_bytes=stored_bytes, constant_flash_estimate_bytes=flash_estimate,
                  reference_five_class_only=reference_five, validated_for_business=False,
                  runtime="portable_scalar_int8_reference", performance="not measured on STM32F429")
    license_path = model_path.parent / "PRETRAINED_LICENSE.txt"
    if reference_five and report["model_sha256"] == "d8a8ab8d3b87d80a7e027ccd1f6933b3ba7ac4a3eb1d3c038f8a1129cf788566":
        license_path = Path(__file__).resolve().parents[2] / "artifacts/model_audit/arm_openmv/LICENSE"
    if license_path.exists():
        shutil.copyfile(license_path, output / "PRETRAINED_LICENSE.txt")
        report["pretrained_license"] = "PRETRAINED_LICENSE.txt"
    generated = ["gs_model_weights.c", "gs_model_weights.h"]
    if not reference_five:
        generated.append("gs_model_metadata_candidate.h")
    report["generated_files_sha256"] = {
        filename: hashlib.sha256((output / filename).read_bytes()).hexdigest() for filename in generated
    }
    (output / "c_export_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-id", default="unaccepted-candidate")
    parser.add_argument("--reference-five-class", action="store_true", help="仅离线数值基准；不生成gs_ai业务后端")
    parser.add_argument("--install", action="store_true", help="校验七类候选后复制到工程Modules/Vision并执行integrate.py；业务仍关闭")
    args = parser.parse_args()
    if args.install and args.reference_five_class:
        parser.error("five-class reference cannot be installed")
    try:
        print(json.dumps(export(args.model, args.output, model_id=args.model_id, reference_five=args.reference_five_class), indent=2))
        if args.install:
            from install_model import install
            print(json.dumps(install(args.output, Path(__file__).resolve().parents[1]), indent=2))
    except (ValueError, OSError, ImportError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"C export rejected: {error}\n")


if __name__ == "__main__":
    main()
