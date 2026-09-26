"""Float-only exploratory training. Never converts, exports C, installs or flashes."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone

from dataset import LABELS, flip_label
from random_dataset import read_random_dataset, read_training_dataset, RISK
from train import load_backbone, source_hashes
from training_variants import (AUGMENTATION_PROFILES, CHECKPOINT_METRICS, PERSONAL_SOURCE,
                               augment_training_batch, augmentation_evidence,
                               checkpoint_selection_key, epoch_training_indexes,
                               sampling_evidence, select_checkpoint_entry)
from training_advanced import (EmaCandidate, install_distillation_train_step,
                               make_ema_callback,
                               validate_distillation, validate_ema_decay)


def atomic_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    # Windows readers may temporarily hold the destination without share-delete.
    # Retry only rename permission conflicts, for < 1 second total; preserve
    # the existing complete JSON and pending UTF-8 temporary on final failure.
    delays = (.01, .02, .04, .08, .1, .1, .1, .1, .1, .1, .1)
    for attempt in range(len(delays) + 1):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == len(delays):
                raise
            time.sleep(delays[attempt])


def classification_metrics(truth, predicted):
    import numpy as np
    confusion = np.zeros((7, 7), dtype=np.int64)
    for actual, guess in zip(truth, predicted):
        confusion[int(actual), int(guess)] += 1
    support = confusion.sum(axis=1)
    predicted_count = confusion.sum(axis=0)
    correct = np.diag(confusion)
    precision = np.divide(correct, predicted_count, out=np.zeros(7), where=predicted_count != 0)
    recall = np.divide(correct, support, out=np.zeros(7), where=support != 0)
    f1 = np.divide(2 * precision * recall, precision + recall, out=np.zeros(7), where=precision + recall != 0)
    total = int(confusion.sum())
    return dict(confusion=confusion.tolist(), sample_count=total, errors=total-int(correct.sum()),
                accuracy=float(correct.sum()/total) if total else None, macro_f1=float(f1.mean()),
                balanced_accuracy=float(recall.mean()), per_class={label: dict(precision=float(precision[i]),
                recall=float(recall[i]), f1=float(f1[i]), support=int(support[i]),
                errors=int(support[i]-correct[i])) for i, label in enumerate(LABELS)})


def moderate_class_weights(labels):
    import numpy as np
    counts = np.bincount(labels, minlength=7)
    if np.any(counts == 0):
        raise ValueError("training needs every class")
    weights = np.sqrt(len(labels)/(7*counts))
    weights /= (weights * counts).sum()/len(labels)
    return weights.astype(np.float32)


def adamw_exclusion_variables(model, keras):
    """Return actual trainable BN gamma/beta and bias objects, once each."""
    trainable_ids = {id(weight) for weight in model.trainable_weights}
    excluded = []
    seen = set()

    def add(weight):
        if weight is not None and id(weight) in trainable_ids and id(weight) not in seen:
            seen.add(id(weight))
            excluded.append(weight)

    for layer in model.submodules:
        if isinstance(layer, keras.layers.BatchNormalization):
            add(layer.gamma)
            add(layer.beta)
        add(getattr(layer, "bias", None))
    return excluded


def make_full_optimizer(model, keras, learning_rate, name="adam", weight_decay=0.0):
    """Build optimizer configuration without building its slot variables."""
    if name not in ("adam", "adamw"):
        raise ValueError(f"unsupported FULL optimizer: {name}")
    if not math.isfinite(weight_decay) or (name == "adam" and weight_decay != 0) or (name == "adamw" and weight_decay <= 0):
        raise ValueError("Adam requires zero decay; AdamW requires finite positive decay")
    common = dict(learning_rate=learning_rate, beta_1=.9, beta_2=.999,
                  epsilon=1e-7, amsgrad=False)
    if name == "adam":
        optimizer = keras.optimizers.Adam(adaptive_epsilon=False, **common)
        excluded = []
        decayed = []
    else:
        optimizer = keras.optimizers.AdamW(weight_decay=weight_decay, **common)
        excluded = adamw_exclusion_variables(model, keras)
        # This must precede model.compile / optimizer.build. Actual variable
        # identities are used rather than regex-based name matching.
        optimizer.exclude_from_weight_decay(var_list=excluded)
        excluded_ids = {id(weight) for weight in excluded}
        decayed = [weight for weight in model.trainable_weights if id(weight) not in excluded_ids]
    all_names = [weight.name for weight in model.trainable_weights]
    excluded_names = [weight.name for weight in excluded]
    decayed_names = [weight.name for weight in decayed]
    if len(all_names) != len(set(all_names)):
        raise ValueError("trainable weight names must be unique for optimizer evidence")
    excluded_name_set = set(excluded_names)
    decayed_name_set = set(decayed_names)
    expected_partition = set(all_names) if name == "adamw" else set()
    if excluded_name_set & decayed_name_set or excluded_name_set | decayed_name_set != expected_partition:
        raise ValueError("optimizer decay partition is incomplete")
    evidence = dict(name=name, class_name=type(optimizer).__name__, weight_decay=float(weight_decay),
                    beta_1=float(optimizer.beta_1), beta_2=float(optimizer.beta_2),
                    epsilon=float(optimizer.epsilon), amsgrad=bool(optimizer.amsgrad),
                    excluded_from_weight_decay_names=excluded_names,
                    decayed_weight_names=decayed_names,
                    excluded_from_weight_decay_count=len(excluded_names),
                    decayed_weight_count=len(decayed_names),
                    trainable_weight_count=len(all_names),
                    exclusion_uses_actual_variables=(name == "adamw"),
                    decay_is_decoupled=(name == "adamw"))
    return optimizer, evidence


def warmup_cosine_learning_rate(epoch, total_epochs, peak_lr=.0001,
                                warmup_start_lr=.00001, min_lr=.000001,
                                warmup_epochs=5):
    """Return the learning rate for a one-based epoch."""
    if not 1 <= epoch <= total_epochs:
        raise ValueError("epoch must be within 1..total_epochs")
    if total_epochs < warmup_epochs or warmup_epochs < 2:
        raise ValueError("warmup cosine needs at least two warmup epochs")
    if epoch <= warmup_epochs:
        fraction = (epoch - 1) / (warmup_epochs - 1)
        return float(warmup_start_lr + fraction * (peak_lr - warmup_start_lr))
    fraction = (epoch - warmup_epochs) / (total_epochs - warmup_epochs)
    return float(min_lr + .5 * (peak_lr - min_lr) * (1 + math.cos(math.pi * fraction)))


def finite_float_or_none(value):
    value=float(value)
    return value if math.isfinite(value) else None


def normalize_training_history(history):
    """Convert only Keras' numeric History payload to strict JSON scalars."""
    if not isinstance(history, dict):
        raise TypeError("Keras history must be a dict")
    normalized={}
    for name, values in history.items():
        if not isinstance(name, str) or not isinstance(values, (list, tuple)):
            raise TypeError("Keras history must map string names to numeric sequences")
        if any(isinstance(value, bool) for value in values):
            raise TypeError("Keras history values must be numeric, not bool")
        normalized[name]=[float(value) for value in values]
    return normalized


class DelayedEarlyStoppingState:
    """State machine for delayed early stopping with cumulative min_delta."""
    def __init__(self, start_epoch=1, min_delta=0.0, patience=5):
        self.start_epoch = start_epoch
        self.min_delta = min_delta
        self.patience = patience
        self.reference_best_val_loss = None
        self.significant_best_val_loss = None
        self.wait = 0
        self.stop_triggered = False
        self.stopped_epoch = None

    def update(self, epoch, val_loss):
        value = float(val_loss)
        if epoch < self.start_epoch:
            if self.reference_best_val_loss is None or value < self.reference_best_val_loss:
                self.reference_best_val_loss = value
                self.significant_best_val_loss = value
            return self.snapshot(epoch)
        if self.significant_best_val_loss is None:
            self.reference_best_val_loss = value
            self.significant_best_val_loss = value
            return self.snapshot(epoch)
        improved = (value < self.significant_best_val_loss if self.min_delta == 0 else
                    value <= self.significant_best_val_loss - self.min_delta)
        if improved:
            self.significant_best_val_loss = value
            self.wait = 0
        else:
            self.wait += 1
        if self.wait >= self.patience:
            self.stop_triggered = True
            self.stopped_epoch = epoch
        return self.snapshot(epoch)

    def snapshot(self, epoch=None):
        return dict(rule="delayed_cumulative_absolute_min_delta", monitor="val_loss",
                    start_epoch=self.start_epoch, min_delta=self.min_delta,
                    patience=self.patience, active=bool(epoch is not None and epoch >= self.start_epoch),
                    reference_best_val_loss=self.reference_best_val_loss,
                    significant_best_val_loss=self.significant_best_val_loss,
                    wait=self.wait, stop_triggered=self.stop_triggered,
                    stopped_epoch=self.stopped_epoch)


def make_delayed_early_stopping(keras, state):
    class DelayedEarlyStopping(keras.callbacks.Callback):
        def on_epoch_end(self, epoch, logs=None):
            logs = logs or {}
            if "val_loss" not in logs:
                raise ValueError("delayed early stopping requires val_loss")
            state.update(epoch + 1, logs["val_loss"])
            if state.stop_triggered:
                self.model.stop_training = True
    return DelayedEarlyStopping()


def configure_trainability(model, backbone, keras, full=False):
    """Full mode never freezes a layer, including nested models and BatchNorm."""
    if full:
        for layer in [model, *model.submodules]:
            layer.trainable = True
    else:
        for layer in backbone.layers:
            layer.trainable = False
    return trainability_audit(model, keras, require_full=full)


def build_seven_class_model(backbone, keras, seed, dropout=.1):
    """Attach the existing seeded Dropout/1x1-convolution seven-class head."""
    features=keras.layers.Dropout(dropout,seed=seed,name="project_seeded_dropout")(backbone.output)
    logits=keras.layers.Conv2D(7,1,name="project_seven_class_logits",
                kernel_initializer=keras.initializers.GlorotUniform(seed=seed))(features)
    return keras.Model(backbone.input,keras.layers.Flatten(name="project_seven_logits")(logits),
                       name="gesture_seven")


def trainability_audit(model, keras, require_full=False):
    import numpy as np
    layers = [layer for layer in model.submodules if isinstance(layer, keras.layers.Layer)]
    bn = [layer for layer in layers if isinstance(layer, keras.layers.BatchNormalization)]
    state_ids = {id(w) for layer in bn for w in (layer.moving_mean, layer.moving_variance)}
    excluded = [w.name for w in model.non_trainable_weights if id(w) not in state_ids]
    frozen = sorted({layer.name for layer in layers if layer.weights and not layer.trainable})
    result = dict(all_gradient_parameters_trainable=not excluded and not frozen,
                  frozen_weight_layers=frozen, excluded_gradient_weights=excluded,
                  trainable_parameters=sum(int(np.prod(w.shape)) for w in model.trainable_weights),
                  non_trainable_state_parameters=sum(int(np.prod(w.shape)) for w in model.non_trainable_weights),
                  trainable_weight_names=[w.name for w in model.trainable_weights],
                  batchnorm_training_enabled=all(layer.trainable for layer in bn),
                  batchnorm_state_note="moving_mean / moving_variance are EMA state, not optimizer parameters; updated by training batches when BN is trainable")
    if require_full and not result['all_gradient_parameters_trainable']:
        raise ValueError(f"Full training excludes optimizer parameters: {result}")
    return result


class Progress:
    def __init__(self, output, config):
        self.path = output / "progress.json"
        self.started = time.monotonic()
        self.value = dict(status="running", stage="checking_data", epoch=0, stage_epochs=0,
                          global_epoch=0, train_loss=None, train_accuracy=None, val_loss=None,
                          val_accuracy=None, val_macro_f1=None, elapsed_seconds=0, history=[],
                          message="Checking all raw hashes, quality and exact tensor duplicates; no test scoring.", config=config)
        self.update()

    def update(self, **values):
        self.value.update(values)
        self.value.update(elapsed_seconds=round(time.monotonic()-self.started, 3),
                          updated_at=datetime.now(timezone.utc).isoformat())
        atomic_json(self.path, self.value)


def arrays(report, tensors):
    import numpy as np
    x = np.frombuffer(b"".join(tensors), dtype=np.int8).reshape(-1, 96, 96, 1).astype(np.int16)
    return (x+128).astype(np.float32), np.array([LABELS.index(r["label"]) for r in report["samples"]], dtype=np.int64)


def train_float(args):
    import numpy as np
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("output must be new/empty; historical runs will not be overwritten")
    args.output.mkdir(parents=True, exist_ok=True)
    def config_value(value):
        if isinstance(value, Path):
            return str(value.resolve())
        if isinstance(value, (list, tuple)):
            return [config_value(item) for item in value]
        return value
    config = {key: config_value(value) for key, value in vars(args).items()}
    progress = Progress(args.output, config)
    try:
        report, tensors = read_training_dataset(args.manifest)
        x, y = arrays(report, tensors)
        indexes = {s: np.array([i for i,r in enumerate(report["samples"]) if r["split"] == s],dtype=np.int64)
                   for s in ("train", "validation")}
        if args.smoke_samples_per_class:
            for split in indexes:
                indexes[split] = np.array([int(i) for label in range(7) for i in indexes[split][y[indexes[split]] == label][:args.smoke_samples_per_class]])
        tf, keras, backbone = load_backbone(args.pretrained)
        # tf_keras 2.16's Python 3.12-incompatible seeded deserializer calls
        # random.randint(1, 1e9) after set_random_seed() has installed its
        # private SeedGenerator. Deserialize immutable teachers before the
        # training seed is installed, then reset the seed below before any
        # student construction or training randomness is consumed. This is
        # intentionally local to KD and does not patch tf_keras or Python RNG.
        teacher_paths = [Path(path).resolve() for path in getattr(args, "teacher_model", [])]
        teachers = []
        teacher_records = []
        for path in teacher_paths:
            teacher = keras.models.load_model(str(path), compile=False)
            teacher.trainable = False
            teachers.append(teacher)
            teacher_records.append(dict(path=str(path),files_sha256=source_hashes(path)))
        keras.utils.set_random_seed(args.seed)
        tf.config.experimental.enable_op_determinism()
        full = args.experiment == "FULL"
        ema_decay = float(getattr(args, "ema_decay", 0.0))
        # Staged E1 keeps its historical behavior. FULL weighting is never
        # inferred from the experiment name: it requires the explicit option.
        weighted = (args.full_class_weight == "sqrt_inverse" if full else
                    args.experiment == "E1")
        weights = moderate_class_weights(y[indexes["train"]]) if weighted else np.ones(7,dtype=np.float32)
        sources = np.array([row.get("source", "unknown") for row in report["samples"]], dtype=object)
        augmentation_record = augmentation_evidence(args.augmentation_profile if full else "flip")
        sampling_record = sampling_evidence(indexes["train"], y, sources, LABELS,
                                            args.personal_sampling_factor if full else 1.0)

        class Batches(keras.utils.Sequence):
            def __init__(self, split, augment=False):
                self.base_indexes = indexes[split].copy()
                self.indexes = self.base_indexes.copy()
                self.augment = augment
                self.epoch = 0
                self.actual_sampling_by_epoch = {}
                self.requested_batches_by_epoch = {}
                self.shuffle()
            def shuffle(self):
                self.indexes = self.base_indexes.copy()
                self.sampling_audit = None
                if self.augment:
                    factor = args.personal_sampling_factor if full else 1.0
                    self.indexes, self.sampling_audit = epoch_training_indexes(
                        self.base_indexes, y, sources, LABELS, factor, args.seed, self.epoch)
                    self.actual_sampling_by_epoch[self.epoch] = dict(self.sampling_audit)
                    self.requested_batches_by_epoch.setdefault(self.epoch, set())
            def __len__(self): return (len(self.indexes)+args.batch_size-1)//args.batch_size
            def __getitem__(self, number):
                if self.augment:
                    self.requested_batches_by_epoch.setdefault(self.epoch, set()).add(int(number))
                ids = self.indexes[number*args.batch_size:(number+1)*args.batch_size]
                images, targets = x[ids].copy(), y[ids].copy()
                if self.augment:
                    # Keras may probe/prefetch repeatedly; all transforms are a
                    # pure function of seed/epoch/batch and use independent streams.
                    images, targets = augment_training_batch(
                        images, targets, args.augmentation_profile if full else "flip",
                        args.seed, self.epoch, number, flip_label)
                    return images, targets, weights[targets]
                return images, targets
            def on_epoch_end(self):
                self.epoch += 1
                self.shuffle()
            def actual_audit(self, epoch):
                if epoch not in self.actual_sampling_by_epoch:
                    raise ValueError(f"missing actual sampling plan for epoch {epoch+1}")
                audit = dict(self.actual_sampling_by_epoch[epoch])
                requested = sorted(self.requested_batches_by_epoch.get(epoch, set()))
                expected = list(range(len(self)))
                audit.update(requested_batch_numbers=requested,
                             expected_batch_count=len(expected),
                             all_batch_numbers_observed=(requested == expected))
                if requested != expected:
                    raise ValueError(f"training Sequence batch coverage incomplete at epoch {epoch+1}")
                return audit

        model=build_seven_class_model(backbone,keras,args.seed,args.dropout)
        initial_trainability = configure_trainability(model, backbone, keras, full=full)
        distillation_record = None
        if teacher_paths:
            student_structure_sha256 = hashlib.sha256(
                model.to_json().encode("utf-8")).hexdigest()
            for path, teacher in zip(teacher_paths, teachers):
                if (tuple(teacher.input_shape[1:]) != tuple(model.input_shape[1:]) or
                        not isinstance(teacher.output_shape, tuple) or
                        int(teacher.output_shape[-1]) != len(LABELS)):
                    raise ValueError(f"teacher model input/output contract mismatch: {path}")
            student_weight_ids = {id(weight) for weight in model.weights}
            if any(student_weight_ids & {id(weight) for weight in teacher.weights}
                   for teacher in teachers):
                raise ValueError("teacher weights were attached to the student")
            distillation_record = dict(
                enabled=True, teacher_count=len(teachers), teacher_models=teacher_records,
                temperature=float(args.distillation_temperature),
                alpha_hard_ce=float(args.distillation_alpha),
                alpha_kl=float(1.0-args.distillation_alpha),
                teacher_ensemble="uniform_mean_softmax_logits_over_three_teachers",
                train_input="same_augmented_batch_as_student_after_horizontal_flip",
                teacher_output_label_handling="no_post_inference_left_right_swap",
                hard_target="post_augmentation_target_with_left_right_swap_for_horizontal_flip",
                hard_label_loss=args.hard_label_loss,
                focal_gamma=(float(args.focal_gamma) if args.hard_label_loss == "focal" else None),
                loss=("alpha*w_y*(1-p_t)^gamma*CE+(1-alpha)*temperature^2*KL(mean_teacher||student)"
                      if args.hard_label_loss == "focal" else
                      "alpha*w_y*hard_ce+(1-alpha)*temperature^2*KL(mean_teacher||student)"),
                class_weight_scope="hard_ce_only", kl_class_weighted=False,
                validation_loss="unweighted_student_hard_cross_entropy",
                epoch_diagnostic_aggregation="sample_count_weighted_mean_reset_each_epoch",
                teacher_deserialization="keras_load_model_compile_false_before_training_seed",
                training_seed_reset_after_teacher_load=True,
                teacher_training=False, student_all_parameters_trainable=True,
                teacher_attached_to_student=False, saved_model_contains_teacher=False,
                student_weight_count=len(model.weights),
                teacher_weight_counts=[len(teacher.weights) for teacher in teachers],
                student_structure_sha256_before=student_structure_sha256,
                train_step_restored=False)
        bn_layers=[l for l in backbone.layers if isinstance(l,keras.layers.BatchNormalization)]
        bn_before=[w.copy() for layer in bn_layers for w in layer.get_weights()]
        backbone_before = {layer.name: hashlib.sha256(b"".join(w.tobytes() for w in layer.get_weights())).hexdigest()
                           for layer in backbone.layers if layer.weights}
        stage_histories={}
        stage_details={}
        global_offset=0

        def fit(stage, epochs, rate):
            nonlocal global_offset
            checkpoint=args.output/f"{stage}.best.weights.h5"
            checkpoint_metric = args.checkpoint_metric if full else "val_loss"
            checkpoint_best_entry = None
            train_batches = Batches("train",True)
            validation_batches = Batches("validation")
            delayed_state = (DelayedEarlyStoppingState(args.early_stopping_start_epoch,
                             args.early_stopping_min_delta, args.early_stopping_patience)
                             if full else None)
            if full:
                optimizer, optimizer_evidence = make_full_optimizer(
                    model, keras, rate, args.full_optimizer, args.full_weight_decay)
            else:
                optimizer = keras.optimizers.Adam(rate)
                optimizer_evidence = dict(name="adam", class_name=type(optimizer).__name__,
                                          weight_decay=0.0, staged_legacy=True)
            ema_candidate = (EmaCandidate(model, tf, ema_decay)
                             if full and ema_decay else None)
            progress.update(stage=stage,epoch=0,stage_epochs=epochs,train_loss=None,train_accuracy=None,
                            val_loss=None,val_accuracy=None,val_macro_f1=None,val_metrics_epoch=None,batch=0,
                            learning_rate=rate,val_per_class_recall=None,
                            optimizer=optimizer_evidence,
                            ema=(ema_candidate.evidence() if ema_candidate else None),
                            early_stopping=(delayed_state.snapshot() if delayed_state else
                                            dict(rule="keras_patience",monitor="val_loss",patience=5,
                                                 active=True,wait=0,stop_triggered=False,stopped_epoch=None)),
                            trainability=trainability_audit(model, keras, require_full=full))
            model.compile(optimizer=optimizer,loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True),metrics=["accuracy"])
            distillation_install = (install_distillation_train_step(
                model, tf, keras, teachers, args.distillation_temperature,
                args.distillation_alpha, args.hard_label_loss,
                args.focal_gamma) if teachers else None)
            restore_distillation = distillation_install[0] if distillation_install else None
            distillation_metrics_callback = distillation_install[1] if distillation_install else None
            if full and args.full_lr_schedule == "warmup_cosine":
                def schedule(epoch, _current_lr):
                    return warmup_cosine_learning_rate(epoch+1,epochs,rate,
                                                       args.warmup_start_lr,args.warmup_min_lr)
                lr_callback=keras.callbacks.LearningRateScheduler(schedule,verbose=0)
            else:
                lr_callback=None
            early_callback=(make_delayed_early_stopping(keras,delayed_state) if full else
                            keras.callbacks.EarlyStopping(monitor="val_loss",patience=5,
                                                          restore_best_weights=False))

            def early_snapshot(epoch):
                if delayed_state:
                    return delayed_state.snapshot(epoch)
                return dict(rule="keras_patience",monitor="val_loss",patience=5,active=True,
                            wait=int(early_callback.wait),best_val_loss=finite_float_or_none(early_callback.best),
                            stop_triggered=bool(early_callback.stopped_epoch),
                            stopped_epoch=(int(early_callback.stopped_epoch)+1
                                           if early_callback.stopped_epoch else None))

            def current_lr():
                return float(keras.backend.get_value(model.optimizer.learning_rate))

            class Live(keras.callbacks.Callback):
                def on_epoch_begin(self, epoch, logs=None):
                    progress.update(stage=stage,epoch=epoch+1,stage_epochs=epochs,global_epoch=global_offset+epoch+1,
                                    learning_rate=current_lr(),early_stopping=early_snapshot(epoch+1),
                                    message=f"{stage}: epoch {epoch+1}/{epochs}; test remains sealed")
                def on_train_batch_end(self,batch,logs=None):
                    logs=logs or {}
                    progress.update(train_loss=float(logs["loss"]) if "loss" in logs else None,
                                    train_accuracy=float(logs["accuracy"]) if "accuracy" in logs else None,batch=batch+1,
                                    stage_batches=(len(indexes["train"])+args.batch_size-1)//args.batch_size)
                def on_epoch_end(self,epoch,logs=None):
                    nonlocal checkpoint_best_entry
                    logs=logs or {}
                    validation_indexes = indexes["validation"]
                    online_val_loss = None
                    if ema_candidate:
                        online_logits = model.predict(
                            x[validation_indexes], batch_size=args.batch_size, verbose=0)
                        online_val_loss = float(np.mean(
                            keras.losses.sparse_categorical_crossentropy(
                                y[validation_indexes], online_logits, from_logits=True).numpy()))
                        with ema_candidate.candidate_scope():
                            predicted=model.predict(
                                x[validation_indexes],batch_size=args.batch_size,verbose=0).argmax(axis=1)
                    else:
                        predicted=model.predict(
                            x[validation_indexes],batch_size=args.batch_size,verbose=0).argmax(axis=1)
                    metrics=classification_metrics(y[validation_indexes],predicted)
                    logs["val_macro_f1"]=metrics["macro_f1"]
                    per_class_recall={label:metrics["per_class"][label]["recall"] for label in LABELS}
                    personal_mask = sources[validation_indexes] == PERSONAL_SOURCE
                    personal_metrics = classification_metrics(
                        y[validation_indexes][personal_mask], predicted[personal_mask])
                    personal_recall = {label: personal_metrics["per_class"][label]["recall"] for label in LABELS}
                    sampling_audit = train_batches.actual_audit(epoch)
                    entry=dict(stage=stage,epoch=epoch+1,global_epoch=global_offset+epoch+1,
                               learning_rate=current_lr(),val_per_class_recall=per_class_recall,
                               val_correct_count=int(np.sum(predicted == y[validation_indexes])),
                               val_accuracy=float(metrics["accuracy"]),
                               val_confusion=metrics["confusion"],
                               val_personal_sample_count=personal_metrics["sample_count"],
                               val_personal_confusion=personal_metrics["confusion"],
                               val_personal_per_class_recall=personal_recall,
                               val_personal_balanced_accuracy=personal_metrics["balanced_accuracy"],
                               train_sampling=sampling_audit,
                               early_stopping=early_snapshot(epoch+1),
                               **{k:float(logs[k]) for k in ("loss","accuracy","val_loss","val_macro_f1")})
                    if ema_candidate:
                        entry.update(evaluation_model="ema_trainables_plus_current_online_bn_state",
                                     online_val_loss=online_val_loss)
                    if distillation_record:
                        entry.update(train_hard_label_loss=float(logs["hard_label_loss"]),
                                     train_hard_ce=float(logs["hard_ce"]),
                                     train_distillation_kl=float(logs["distillation_kl"]),
                                     train_objective=("focal_plus_temperature_squared_kl"
                                                      if args.hard_label_loss == "focal" else
                                                      "hard_ce_plus_temperature_squared_kl"))
                    if checkpoint_metric == "val_accuracy" and (checkpoint_best_entry is None or
                            checkpoint_selection_key(entry, checkpoint_metric) >
                            checkpoint_selection_key(checkpoint_best_entry, checkpoint_metric)):
                        temporary_checkpoint = checkpoint.with_name(
                            checkpoint.name.replace(".weights.h5", ".pending.weights.h5"))
                        if ema_candidate:
                            ema_candidate.save_candidate_atomic(checkpoint)
                        else:
                            model.save_weights(str(temporary_checkpoint))
                            os.replace(temporary_checkpoint, checkpoint)
                        checkpoint_best_entry = dict(entry)
                    progress.value["history"].append(entry)
                    with (args.output/"epochs.jsonl").open("a",encoding="utf-8") as log_file:
                        log_file.write(json.dumps(entry)+"\n")
                    progress.update(train_loss=entry["loss"],train_accuracy=entry["accuracy"],val_loss=entry["val_loss"],
                                    val_accuracy=entry["val_accuracy"],val_macro_f1=entry["val_macro_f1"],val_metrics_epoch=epoch+1,
                                    learning_rate=entry["learning_rate"],val_per_class_recall=per_class_recall,
                                    val_personal_per_class_recall=personal_recall,
                                    train_sampling=sampling_audit,
                                    early_stopping=entry["early_stopping"],
                                    metric_scope="last_completed_epoch_validation")
            # The checkpoint sees every strict val_loss decrease and is deliberately
            # independent of early stopping's absolute min_delta threshold.
            callbacks=([lr_callback] if lr_callback else [])
            if distillation_metrics_callback:
                callbacks.append(distillation_metrics_callback)
            if ema_candidate:
                callbacks.append(make_ema_callback(
                    keras, ema_candidate, checkpoint, checkpoint_metric))
            if checkpoint_metric == "val_loss" and not ema_candidate:
                callbacks.append(keras.callbacks.ModelCheckpoint(
                    str(checkpoint),monitor="val_loss",save_best_only=True,save_weights_only=True))
            callbacks += [early_callback,Live()]
            try:
                history=model.fit(train_batches,validation_data=validation_batches,epochs=epochs,
                                  callbacks=callbacks,workers=1,use_multiprocessing=False,verbose=2)
            finally:
                if restore_distillation:
                    restore_distillation()
                    distillation_record["train_step_restored"] = True
            stage_entries=[entry for entry in progress.value["history"] if entry["stage"] == stage]
            selected_entry=select_checkpoint_entry(stage_entries, checkpoint_metric)
            if checkpoint_metric == "val_accuracy":
                if checkpoint_best_entry is None or checkpoint_best_entry["epoch"] != selected_entry["epoch"]:
                    raise ValueError("accuracy checkpoint callback diverged from recorded epoch selection")
            model.load_weights(str(checkpoint))
            global_offset+=len(history.history["loss"])
            stage_histories[stage]=normalize_training_history(history.history)
            minimum_val_loss_epoch=int(np.argmin(history.history["val_loss"]))+1
            minimum_val_loss=float(min(history.history["val_loss"]))
            stage_details[stage]=dict(best_epoch=minimum_val_loss_epoch,
                                     minimum_val_loss_epoch=minimum_val_loss_epoch,
                                     minimum_val_loss=minimum_val_loss,
                                     checkpoint_metric=checkpoint_metric,
                                     checkpoint_best_epoch=int(selected_entry["epoch"]),
                                     checkpoint_metrics={key:selected_entry[key] for key in
                                         ("val_correct_count","val_accuracy","val_macro_f1","val_loss")},
                                     completed_epochs=len(history.history["loss"]),max_epochs=epochs,
                                     stopping_reason=((f"delayed val_loss patience {args.early_stopping_patience}"
                                                       if full else "val_loss patience 5")
                                                      if len(history.history["loss"]) < epochs else "epoch cap reached"),
                                     learning_rate_schedule=(args.full_lr_schedule if full else "constant"),
                                     optimizer=optimizer_evidence,
                                     ema=(ema_candidate.evidence() if ema_candidate else None),
                                     distillation=(dict(distillation_record)
                                                   if distillation_record else None),
                                     early_stopping=early_snapshot(len(history.history["loss"])),
                                     trainable_parameters=sum(int(np.prod(w.shape)) for w in model.trainable_weights),
                                     trainability=trainability_audit(model, keras, require_full=full),
                                     checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest())
            selected_evaluation=model.evaluate(validation_batches,verbose=0)
            selected_loss=float(selected_evaluation[0] if isinstance(selected_evaluation,(list,tuple)) else selected_evaluation)
            if not math.isclose(selected_loss, float(selected_entry["val_loss"]), rel_tol=1e-5, abs_tol=1e-6):
                raise ValueError("loaded checkpoint validation loss differs from selected epoch")
            return selected_loss

        head_loss=None
        fine_loss=None
        full_loss=None
        if full:
            selected="full"
            full_loss=fit("full",args.full_epochs,args.full_lr)
        else:
            head_loss=fit("head",args.head_epochs,args.head_lr)
            selected="head"
            head_weights=model.get_weights()
            if args.experiment == "E1" and args.finetune_epochs:
                for layer in backbone.layers[-args.unfreeze_layers:]:
                    layer.trainable=not isinstance(layer,keras.layers.BatchNormalization)
                fine_loss=fit("finetune",args.finetune_epochs,args.finetune_lr)
                if fine_loss < head_loss: selected="finetune"
                else: model.set_weights(head_weights)
        bn_after=[w for layer in bn_layers for w in layer.get_weights()]
        bn_unchanged=all(np.array_equal(a,b) for a,b in zip(bn_before,bn_after))
        if not full and not bn_unchanged:
            raise ValueError("BatchNorm state changed despite freeze")
        if full and bn_layers and bn_unchanged:
            raise ValueError("BatchNorm did not update during full training")
        final_trainability=trainability_audit(model, keras, require_full=full)
        changed_backbone_layers=[layer.name for layer in backbone.layers if layer.weights and
                    hashlib.sha256(b"".join(w.tobytes() for w in layer.get_weights())).hexdigest() != backbone_before[layer.name]]
        progress.update(stage="saving",message="Saving float candidate; no test scoring/conversion/install")
        model.save_weights(str(args.output/"best.weights.h5"))
        model.save(str(args.output/"saved_model"),include_optimizer=False)
        license_path=args.pretrained.parents[1]/"LICENSE"
        if license_path.exists(): shutil.copyfile(license_path,args.output/"PRETRAINED_LICENSE.txt")
        prediction=model.predict(x[indexes["validation"]],batch_size=args.batch_size,verbose=0).argmax(axis=1)
        validation=classification_metrics(y[indexes["validation"]],prediction)
        selected_detail=stage_details[selected]
        selected_checkpoint_metrics=selected_detail["checkpoint_metrics"]
        if (validation["accuracy"] != selected_checkpoint_metrics["val_accuracy"] or
                validation["macro_f1"] != selected_checkpoint_metrics["val_macro_f1"]):
            raise ValueError("saved checkpoint classification metrics differ from selected epoch")
        diagnostic_groups={}
        diagnostic_mistakes={}
        for split in ("train","validation"):
            ids=indexes[split]
            split_logits=model.predict(x[ids],batch_size=args.batch_size,verbose=0)
            guesses=split_logits.argmax(axis=1)
            probabilities=tf.nn.softmax(split_logits).numpy()
            diagnostic_groups[split]={}
            for source in sorted({report["samples"][int(i)].get("source","unknown") for i in ids}):
                mask=np.array([report["samples"][int(i)].get("source","unknown") == source for i in ids])
                diagnostic_groups[split][source]=classification_metrics(y[ids][mask],guesses[mask])
            diagnostic_mistakes[split]=[dict(file=report["samples"][int(i)]["file"],
                 preview_file=report["samples"][int(i)].get("preview_file"),actual=LABELS[int(y[i])],
                 predicted=LABELS[int(guess)],score=float(probabilities[n,guess]),
                 source=report["samples"][int(i)].get("source"))
                 for n,(i,guess) in enumerate(zip(ids,guesses)) if y[i] != guess]
        code_files=[Path(__file__),Path(__file__).with_name("random_dataset.py"),
                    Path(__file__).with_name("dataset.py"),Path(__file__).with_name("train.py"),
                    Path(__file__).with_name("training_variants.py")]
        if ema_decay or teachers:
            code_files.append(Path(__file__).with_name("training_advanced.py"))
        code_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in code_files}
        result=dict(schema_version=1,kind="float_only_random_split_experiment",config=config,labels=LABELS,
                    label_audit_sha256=args.label_audit_sha256,
                    scope="SMOKE SOFTWARE TEST ONLY" if args.smoke_samples_per_class else f"exploratory {report['sample_count']}-image {report['split_method']} training",
                    dataset=report,history=stage_histories,stage_details=stage_details,
                    progress_history=progress.value["history"],selected_stage=selected,
                    head_best_val_loss=head_loss,finetune_best_val_loss=fine_loss,
                    full_best_val_loss=full_loss,
                    selected_val_loss=full_loss if full else (min(head_loss,fine_loss) if fine_loss is not None else head_loss),
                     minimum_val_loss=selected_detail["minimum_val_loss"],
                     minimum_val_loss_epoch=selected_detail["minimum_val_loss_epoch"],
                     checkpoint_best_epoch=selected_detail["checkpoint_best_epoch"],
                     checkpoint_selection=dict(metric=selected_detail["checkpoint_metric"],
                                               epoch=selected_detail["checkpoint_best_epoch"],
                                               metrics=selected_checkpoint_metrics,
                                               tie_break=("maximum validation correct_count, then macro_f1, "
                                                          "then lower unweighted cross-entropy, then earlier epoch"
                                                          if selected_detail["checkpoint_metric"] == "val_accuracy"
                                                          else "minimum unweighted validation cross-entropy, then earlier epoch"),
                                               early_stopping_monitor="val_loss"),
                     validation=validation,source_groups=diagnostic_groups,mistakes=diagnostic_mistakes,
                     train_class_weights=weights.tolist(),batchnorm_unchanged=bn_unchanged,batchnorm_layer_count=len(bn_layers),
                     augmentation=augmentation_record,sampling=sampling_record,
                     sampling_history=[entry["train_sampling"] for entry in progress.value["history"]
                                       if entry["stage"] == selected],
                     class_weighting=dict(mode=(args.full_class_weight if full else
                                                ("staged_e1_sqrt_inverse" if weighted else "none")),
                                          source_split="train" if weighted else None,
                                          weights=weights.tolist(),validation_weighted=False),
                     optimizer=stage_details[selected]["optimizer"],
                     initial_trainability=initial_trainability,trainability=final_trainability,
                    changed_backbone_layers=changed_backbone_layers,
                    batchnorm_before_sha256=hashlib.sha256(b"".join(w.tobytes() for w in bn_before)).hexdigest(),
                    batchnorm_after_sha256=hashlib.sha256(b"".join(w.tobytes() for w in bn_after)).hexdigest(),
                    tensorflow=tf.__version__,tf_keras=keras.__version__,numpy=np.__version__,python=platform.python_version(),
                    devices=[dict(name=d.name,type=d.device_type) for d in tf.config.list_physical_devices()],
                    source_files_sha256=source_hashes(args.pretrained),code_sha256=code_hashes,
                    model_files_sha256=source_hashes(args.output/"saved_model"),
                    best_weights_sha256=hashlib.sha256((args.output/"best.weights.h5").read_bytes()).hexdigest(),
                    test_evaluated=False,quantization_performed=False,c_export_performed=False,installed=False,
                    validated_for_business=False,warning=report['warning'])
        if ema_decay:
            result["ema"] = stage_details[selected]["ema"]
        if distillation_record:
            after = hashlib.sha256(model.to_json().encode("utf-8")).hexdigest()
            distillation_record["student_structure_sha256_after"] = after
            distillation_record["student_structure_unchanged"] = (
                after == distillation_record["student_structure_sha256_before"])
            if not distillation_record["student_structure_unchanged"]:
                raise ValueError("distillation changed the student inference structure")
            result["distillation"] = dict(distillation_record)
            result["stage_details"][selected]["distillation"] = dict(distillation_record)
        atomic_json(args.output/"training_report.json",result)
        progress.update(status="completed",stage="completed",selected_stage=selected,
                        val_loss=result["selected_val_loss"],val_accuracy=validation["accuracy"],val_macro_f1=validation["macro_f1"],
                        val_metrics_epoch=stage_details[selected]["checkpoint_best_epoch"],metric_scope="selected_candidate_validation",
                        message=f"Float training complete: selected {selected}; test sealed")
        print(json.dumps({"output":str(args.output),"selected_stage":selected,"validation":validation,"test_evaluated":False},indent=2))
        return result
    except BaseException as error:
        original_traceback = traceback.format_exc()
        try:
            (args.output/"failure.log").write_text(original_traceback,encoding="utf-8")
        except Exception as reporting_error:
            error.add_note(f"Writing failure.log also failed: {reporting_error}")
        try:
            progress.update(status="failed",message=f"{type(error).__name__}: {error}")
        except Exception as reporting_error:
            error.add_note(f"Reporting failed progress also failed: {reporting_error}")
        raise


def evaluate_final(args):
    report=json.loads((args.output/"training_report.json").read_text(encoding="utf-8"))
    if report.get("scope") == "SMOKE SOFTWARE TEST ONLY": raise ValueError("smoke models cannot be final candidates")
    if (args.output/"final_test_report.json").exists(): raise ValueError("final test already evaluated; no overwrite")
    if source_hashes(args.output/"saved_model") != report["model_files_sha256"]:
        raise ValueError("frozen SavedModel hash changed")
    data,tensors=read_training_dataset(args.manifest)
    if data["manifest_sha256"] != report["dataset"]["manifest_sha256"]: raise ValueError("manifest changed")
    from model_package import tensorflow
    tf=tensorflow()
    import tf_keras as keras
    import numpy as np
    model=keras.models.load_model(str(args.output/"saved_model"),compile=False)
    x,y=arrays(data,tensors)
    indexes=np.array([i for i,r in enumerate(data["samples"]) if r["split"] == "test"])
    logits=model.predict(x[indexes],batch_size=args.batch_size,verbose=0)
    guesses=logits.argmax(axis=1)
    probabilities=tf.nn.softmax(logits).numpy()
    groups={}
    for name in sorted({data["samples"][int(i)].get("source","unknown") for i in indexes}):
        mask=np.array([data["samples"][int(i)].get("source","unknown") == name for i in indexes])
        groups[name]=classification_metrics(y[indexes][mask],guesses[mask])
    mistakes=[dict(file=data["samples"][int(i)]["file"],preview_file=data["samples"][int(i)].get("preview_file"),
              actual=LABELS[int(y[i])],predicted=LABELS[int(guess)],score=float(probabilities[n,guess]),
              source=data["samples"][int(i)].get("source")) for n,(i,guess) in enumerate(zip(indexes,guesses)) if y[i] != guess]
    metrics=classification_metrics(y[indexes],guesses)
    results=dict(kind="float_final_random_test",model_files_sha256=report["model_files_sha256"],
                 manifest_sha256=data["manifest_sha256"],metrics=metrics,source_groups=groups,mistakes=mistakes,
                 warning=data['warning'],validated_for_business=False,quantization_performed=False,
                 evaluated_at=datetime.now(timezone.utc).isoformat())
    atomic_json(args.output/"final_test_report.json",results)
    print(json.dumps(metrics,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--pretrained",type=Path,default=Path(__file__).resolve().parents[2]/"artifacts/model_audit/arm_openmv/pretrained/model")
    parser.add_argument("--experiment",choices=("E0","E1","FULL"),default="E1")
    parser.add_argument("--seed",type=int,default=20260918)
    parser.add_argument("--batch-size",type=int,default=16)
    parser.add_argument("--dropout",type=float,default=.1)
    parser.add_argument("--head-epochs",type=int,default=60)
    parser.add_argument("--finetune-epochs",type=int,default=30)
    parser.add_argument("--unfreeze-layers",type=int,default=12)
    parser.add_argument("--head-lr",type=float,default=.001)
    parser.add_argument("--finetune-lr",type=float,default=.00001)
    parser.add_argument("--full-epochs",type=int,default=90,help="single stage, all optimizer parameters and BN enabled; cap 200")
    parser.add_argument("--full-lr",type=float,default=.0001,help="Adam peak/constant learning rate")
    parser.add_argument("--full-optimizer",choices=("adam","adamw"),default="adam")
    parser.add_argument("--full-weight-decay",type=float,default=0.0)
    parser.add_argument("--full-class-weight",choices=("none","sqrt_inverse"),default="none",
                        help="FULL-only explicit train weighting; validation remains unweighted")
    parser.add_argument("--checkpoint-metric",choices=CHECKPOINT_METRICS,default="val_loss",
                        help="FULL checkpoint selection; early stopping always monitors val_loss")
    parser.add_argument("--augmentation-profile",choices=AUGMENTATION_PROFILES,default="flip",
                        help="FULL train-only deterministic augmentation")
    parser.add_argument("--personal-sampling-factor",type=float,default=1.0,
                        help="FULL per-class personal-source sampling factor; epoch size/counts stay fixed")
    parser.add_argument("--ema-decay",type=float,default=0.0,
                        help="FULL-only EMA decay; 0 keeps the legacy online-weight path")
    parser.add_argument("--teacher-model",type=Path,action="append",default=[],
                        help="repeat exactly three times for FULL train-only distillation teachers")
    parser.add_argument("--distillation-temperature",type=float,default=3.0)
    parser.add_argument("--distillation-alpha",type=float,default=.5,
                        help="hard-CE coefficient; KL coefficient is 1-alpha")
    parser.add_argument("--hard-label-loss",choices=("sparse_ce","focal"),default="sparse_ce",
                        help="train-only hard-label term; validation remains unweighted sparse CE")
    parser.add_argument("--focal-gamma",type=float,default=2.0)
    parser.add_argument("--label-audit-sha256",default=None,
                        help="optional immutable semantic-label gate hash embedded in the run report")
    parser.add_argument("--full-lr-schedule",choices=("constant","warmup_cosine"),default="constant")
    parser.add_argument("--warmup-start-lr",type=float,default=.00001)
    parser.add_argument("--warmup-min-lr",type=float,default=.000001)
    parser.add_argument("--early-stopping-start-epoch",type=int,default=1)
    parser.add_argument("--early-stopping-min-delta",type=float,default=0.0)
    parser.add_argument("--early-stopping-patience",type=int,default=5)
    parser.add_argument("--smoke-samples-per-class",type=int,default=0,help="software smoke on real train/validation subset; never a final model")
    parser.add_argument("--evaluate-final",action="store_true",help="independent explicit scoring of frozen candidate; no training")
    args=parser.parse_args()
    if not 0 < args.head_epochs <= 60 or not 0 <= args.finetune_epochs <= 30:
        parser.error("authorized stage epoch caps are 60/30")
    if min(args.batch_size,args.unfreeze_layers) <= 0 or args.smoke_samples_per_class < 0:
        parser.error("invalid batch/layer/smoke counts")
    if not math.isfinite(args.dropout) or not 0 <= args.dropout < 1:
        parser.error("dropout must be finite and satisfy 0 <= dropout < 1")
    if not 0 < args.full_epochs <= 200 or not 0 < args.full_lr < 1:
        parser.error("invalid full-training epoch cap or learning rate")
    if (not math.isfinite(args.full_weight_decay) or
            (args.full_optimizer == "adam" and args.full_weight_decay != 0) or
            (args.full_optimizer == "adamw" and args.full_weight_decay <= 0)):
        parser.error("Adam requires --full-weight-decay 0; AdamW requires finite positive decay")
    if args.experiment != "FULL" and args.full_class_weight != "none":
        parser.error("--full-class-weight is valid only with --experiment FULL")
    if args.experiment != "FULL" and (args.full_optimizer != "adam" or args.full_weight_decay != 0):
        parser.error("FULL optimizer options are valid only with --experiment FULL")
    if not math.isfinite(args.personal_sampling_factor) or args.personal_sampling_factor <= 0:
        parser.error("--personal-sampling-factor must be finite and positive")
    try:
        args.ema_decay = validate_ema_decay(args.ema_decay)
    except ValueError as error:
        parser.error(str(error))
    if args.experiment != "FULL" and args.ema_decay != 0:
        parser.error("--ema-decay is valid only with --experiment FULL")
    args.teacher_model = [path.resolve() for path in args.teacher_model]
    try:
        args.teacher_model, args.distillation_temperature, args.distillation_alpha = \
            validate_distillation(args.teacher_model, args.distillation_temperature,
                                  args.distillation_alpha)
    except ValueError as error:
        parser.error(str(error))
    if args.teacher_model and args.experiment != "FULL":
        parser.error("--teacher-model is valid only with --experiment FULL")
    if args.hard_label_loss == "focal" and not args.teacher_model:
        parser.error("focal hard-label loss currently requires distillation teachers")
    if not math.isfinite(args.focal_gamma) or args.focal_gamma <= 0:
        parser.error("focal gamma must be finite and positive")
    if args.label_audit_sha256 is not None:
        value = args.label_audit_sha256.lower()
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            parser.error("label audit SHA-256 must be 64 lowercase/uppercase hex characters")
        args.label_audit_sha256 = value
    for teacher_path in args.teacher_model:
        if not teacher_path.is_dir():
            parser.error(f"teacher model directory does not exist: {teacher_path}")
    if args.experiment != "FULL" and (args.checkpoint_metric != "val_loss" or
            args.augmentation_profile != "flip" or args.personal_sampling_factor != 1.0):
        parser.error("checkpoint/augmentation/personal-sampling variants are valid only with --experiment FULL")
    if args.full_lr_schedule == "warmup_cosine" and not 0 < args.warmup_min_lr <= args.warmup_start_lr <= args.full_lr < 1:
        parser.error("warmup/min learning rates must satisfy 0 < min <= start <= full_lr < 1")
    if args.full_lr_schedule == "warmup_cosine" and args.full_epochs < 5:
        parser.error("warmup_cosine requires at least 5 full epochs")
    if args.early_stopping_start_epoch < 1 or args.early_stopping_min_delta < 0 or args.early_stopping_patience < 1:
        parser.error("invalid delayed early-stopping parameters")
    if not 0 < args.head_lr < 1 or not 0 < args.finetune_lr < 1: parser.error("invalid learning rate")
    try:
        evaluate_final(args) if args.evaluate_final else train_float(args)
    except (Exception,KeyboardInterrupt) as error:
        parser.exit(2,f"Float experiment rejected/failed: {error}\n")


if __name__ == "__main__": main()
