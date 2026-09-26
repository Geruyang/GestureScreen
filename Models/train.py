"""从公开真实预训练主干微调七类、全 int8 导出；需要真实会话清单。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from dataset import LABELS, read_dataset, flip_label
from model_package import tensorflow, write_candidate


def load_backbone(saved_model: Path):
    """丢弃原训练包装器/随机翻转及五类头，仅提取实际 MobileNet 特征图。"""
    tf = tensorflow()
    import tf_keras as keras
    source = keras.models.load_model(str(saved_model), compile=False)
    matches = []
    for layer in [source, *source.submodules]:
        if isinstance(layer, keras.Model):
            try:
                head = layer.get_layer("conv_preds")
            except ValueError:
                continue
            if tuple(layer.input_shape[1:]) == (96, 96, 1) and tuple(head.input.shape[1:]) == (1, 1, 256):
                matches.append((layer, head))
    # submodules may include source; deduplicate by actual object identity.
    matches = list({id(model): (model, head) for model, head in matches}.values())
    if len(matches) != 1:
        raise ValueError("source graph does not match reviewed 96x96 MobileNet conv_preds contract")
    model, head = matches[0]
    # 原 Dropout 未固定 seed；剥离后在新头前明确设定，兼容 Python 3.12。
    feature = head.input
    producer = feature._keras_history.layer
    if isinstance(producer, keras.layers.Dropout):
        feature = producer.input
    backbone = keras.Model(model.input, feature, name="public_pretrained_features")
    return tf, keras, backbone


def source_hashes(saved_model: Path):
    return {str(p.relative_to(saved_model)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(saved_model.rglob("*")) if p.is_file()}


def train(args):
    # 先核对真实采集，不允许空模板触发训练、复制原五类标签或临时制造七类图片。
    report, tensors = read_dataset(args.manifest)
    if report["debug_quality_rejected"]:
        raise ValueError("dataset contains debug-quality failures; review captures/exposure before training")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("output directory must be new or empty to protect previous experiment")
    import numpy as np
    tf, keras, backbone = load_backbone(args.pretrained)
    keras.utils.set_random_seed(args.seed)
    tf.config.experimental.enable_op_determinism()
    x = np.frombuffer(b"".join(tensors), dtype=np.int8).reshape(-1, 96, 96, 1).astype(np.int16)
    x = (x + 128).astype(np.uint8)
    labels = np.array([LABELS.index(row["label"]) for row in report["samples"]], dtype=np.int64)
    split_indexes = {s: np.array([i for i, row in enumerate(report["samples"]) if row["split"] == s])
                     for s in ("train", "validation", "calibration", "test")}
    rng = np.random.default_rng(args.seed)

    class Batches(keras.utils.Sequence):
        def __init__(self, split, augment=False):
            self.indexes = split_indexes[split].copy()
            self.augment = augment

        def __len__(self):
            return (len(self.indexes) + args.batch_size - 1) // args.batch_size

        def __getitem__(self, index):
            indices = self.indexes[index * args.batch_size:(index + 1) * args.batch_size]
            images, targets = x[indices].astype(np.float32), labels[indices].copy()
            if self.augment:
                flips = rng.random(len(indices)) < .5
                images[flips] = images[flips, :, ::-1, :]
                targets[flips] = [flip_label(int(y)) for y in targets[flips]]
            return images, targets

        def on_epoch_end(self):
            if self.augment:
                rng.shuffle(self.indexes)

    features = keras.layers.Dropout(.1, seed=args.seed, name="project_seeded_dropout")(backbone.output)
    logits = keras.layers.Conv2D(7, 1, name="project_seven_class_logits",
                                kernel_initializer=keras.initializers.GlorotUniform(seed=args.seed))(features)
    logits = keras.layers.Flatten(name="project_seven_logits")(logits)
    model = keras.Model(backbone.input, logits, name="gesture_seven")
    for layer in backbone.layers:
        layer.trainable = False
    args.output.mkdir(parents=True, exist_ok=True)
    checkpoint = args.output / "best.weights.h5"

    def fit(epochs, rate):
        model.compile(optimizer=keras.optimizers.Adam(rate),
                      loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True), metrics=["accuracy"])
        callbacks = [keras.callbacks.ModelCheckpoint(str(checkpoint), monitor="val_loss", save_best_only=True,
                                                    save_weights_only=True),
                     keras.callbacks.EarlyStopping(monitor="val_loss", patience=5, restore_best_weights=True)]
        history = model.fit(Batches("train", True), validation_data=Batches("validation"),
                            epochs=epochs, callbacks=callbacks, workers=1, use_multiprocessing=False)
        model.load_weights(str(checkpoint))
        return history.history

    histories = {"head": fit(args.head_epochs, args.head_lr)}
    if args.finetune_epochs:
        head_weights = model.get_weights()
        head_validation_loss = float(model.evaluate(Batches("validation"), verbose=0)[0])
        for layer in backbone.layers[-args.unfreeze_layers:]:
            # BatchNorm 保持原统计，避免小型本人数据集破坏移动平均。
            layer.trainable = not isinstance(layer, keras.layers.BatchNormalization)
        histories["finetune"] = fit(args.finetune_epochs, args.finetune_lr)
        if float(model.evaluate(Batches("validation"), verbose=0)[0]) > head_validation_loss:
            model.set_weights(head_weights)
            histories["selected_stage"] = "head (fine-tuning did not improve validation loss)"
        else:
            histories["selected_stage"] = "finetune"
    model.save(str(args.output / "saved_model"), include_optimizer=False)
    reviewed_source = Path(__file__).resolve().parents[2] / "artifacts/model_audit/arm_openmv/pretrained/model"
    if args.pretrained.resolve() == reviewed_source.resolve():
        shutil.copyfile(reviewed_source.parents[1] / "LICENSE", args.output / "PRETRAINED_LICENSE.txt")
    results = {"tensorflow": tf.__version__, "tf_keras": keras.__version__, "labels": LABELS,
               "source_files_sha256": source_hashes(args.pretrained), "dataset": report,
               "history": histories, "arguments": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
               "validated_for_business": False}

    # 量化代表集仅来自 train；calibration 独立用于未来时间状态机/拒识阈值调整。
    representative = split_indexes["train"].copy()
    rng.shuffle(representative)
    representative = representative[:args.representative_limit]

    def representative_dataset():
        for index in representative:
            yield [x[index:index + 1].astype(np.float32)]

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    converter.representative_dataset = representative_dataset
    model_path = args.output / "gesture_seven.int8.tflite"
    model_path.write_bytes(converter.convert())
    results["representative_files"] = [report["samples"][int(i)]["file"] for i in representative]
    # 真实导出输入 scale/zp 可能不满足固定 C 预处理；严格拒绝而不改写元数据。
    try:
        audit = write_candidate(model_path, args.output, model_id=args.model_id, kind="int8_logits")
        results["export_contract_errors"] = []
    except ValueError as error:
        results["export_contract_errors"] = [str(error)]
        (args.output / "training_report.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        raise
    from export_c import export
    try:
        results["c_export"] = export(model_path, args.output / "c_backend", model_id=args.model_id)
    except ValueError as error:
        results["c_export_errors"] = [str(error)]
        (args.output / "training_report.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        raise
    interpreter = tf.lite.Interpreter(model_path=str(model_path),
                                    experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    interpreter.allocate_tensors()
    inp, out = interpreter.get_input_details()[0], interpreter.get_output_details()[0]
    # 测试集只在训练及最佳 epoch 选择完成后使用；输出混淆矩阵便于发现 EMPTY/OTHER 混淆。
    confusion = np.zeros((7, 7), dtype=np.int64)
    for index in split_indexes["test"]:
        quantized = (x[index:index + 1].astype(np.int16) - 128).astype(np.int8)
        interpreter.set_tensor(inp["index"], quantized)
        interpreter.invoke()
        predicted = int(interpreter.get_tensor(out["index"])[0].argmax())
        confusion[labels[index], predicted] += 1
    results.update(tflite_audit=audit, test_confusion=confusion.tolist(),
                   test_accuracy=float(confusion.trace() / confusion.sum()),
                   test_scope="offline captured image classification; no temporal-state-machine or board acceptance")
    (args.output / "training_report.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    if getattr(args, "install", False):
        from install_model import install
        install(args.output / "c_backend", Path(__file__).resolve().parents[1])
    print(json.dumps({"output": str(args.output), "test_accuracy": results["test_accuracy"],
                      "validated_for_business": False}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--pretrained", type=Path, default=Path(__file__).resolve().parents[2] / "artifacts/model_audit/arm_openmv/pretrained/model")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--head-epochs", type=int, default=20)
    parser.add_argument("--finetune-epochs", type=int, default=10)
    parser.add_argument("--unfreeze-layers", type=int, default=12)
    parser.add_argument("--head-lr", type=float, default=.001)
    parser.add_argument("--finetune-lr", type=float, default=.00001)
    parser.add_argument("--representative-limit", type=int, default=500)
    parser.add_argument("--install", action="store_true", help="训练导出成功后安装到Keil工程；不放开业务门禁")
    args = parser.parse_args()
    if min(args.batch_size, args.head_epochs, args.unfreeze_layers, args.representative_limit) <= 0 or args.finetune_epochs < 0:
        parser.error("batch/epochs/layers/representative counts invalid")
    if not 0 < args.head_lr < 1 or not 0 < args.finetune_lr < 1:
        parser.error("learning rates must be in (0,1)")
    try:
        train(args)
    except (ValueError, OSError, ImportError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"Training unavailable/rejected: {error}\n")


if __name__ == "__main__":
    main()
