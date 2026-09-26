"""Optional advanced float-training helpers; no dataset or test access."""
from contextlib import contextmanager
import math
import os
from types import MethodType


def validate_ema_decay(value):
    """Return a normalized EMA decay, rejecting values without useful semantics."""
    value = float(value)
    if not math.isfinite(value) or value < 0 or value >= 1:
        raise ValueError("EMA decay must be finite and satisfy 0 <= decay < 1")
    return value


class EmaCandidate:
    """Maintain EMA trainables while always borrowing the online BN moving state.

    The helper is deliberately not attached to the Keras model, so its shadow
    variables cannot become SavedModel inputs, outputs, or inference weights.
    """
    def __init__(self, model, tf, decay):
        self.model = model
        self.tf = tf
        self.decay = validate_ema_decay(decay)
        if self.decay == 0:
            raise ValueError("EmaCandidate requires a non-zero decay")
        self.trainable_variables = list(model.trainable_variables)
        if not self.trainable_variables:
            raise ValueError("EMA requires trainable model variables")
        self.trainable_names = [variable.name for variable in self.trainable_variables]
        if len(self.trainable_names) != len(set(self.trainable_names)):
            raise ValueError("EMA trainable variable names are not unique")
        self.shadow = [tf.Variable(variable.read_value(), trainable=False,
                                   name=f"ema_shadow_{number}")
                       for number, variable in enumerate(self.trainable_variables)]
        self.bn_state_variables = [variable for variable in model.non_trainable_variables
                                   if variable.name.endswith(("/moving_mean:0", "/moving_variance:0"))]
        self.bn_state_names = [variable.name for variable in self.bn_state_variables]
        self.update_count = 0
        self._online_backup = None

    def update(self):
        one_minus_decay = 1.0 - self.decay
        for shadow, online in zip(self.shadow, self.trainable_variables):
            shadow.assign(self.decay * shadow + one_minus_decay * online)
        self.update_count += 1

    def activate(self):
        if self._online_backup is not None:
            raise RuntimeError("EMA candidate is already active")
        self._online_backup = [self.tf.identity(variable) for variable in self.trainable_variables]
        for online, shadow in zip(self.trainable_variables, self.shadow):
            online.assign(shadow)

    def restore(self):
        if self._online_backup is None:
            raise RuntimeError("EMA candidate is not active")
        backup, self._online_backup = self._online_backup, None
        for online, value in zip(self.trainable_variables, backup):
            online.assign(value)

    @contextmanager
    def candidate_scope(self):
        self.activate()
        try:
            yield self.model
        finally:
            self.restore()

    def save_candidate_atomic(self, checkpoint):
        checkpoint = checkpoint.resolve()
        temporary = checkpoint.with_name(checkpoint.name.replace(
            ".weights.h5", ".pending.weights.h5"))
        if temporary == checkpoint:
            raise ValueError("EMA checkpoint must end in .weights.h5")
        try:
            with self.candidate_scope():
                self.model.save_weights(str(temporary))
            os.replace(temporary, checkpoint)
        finally:
            if temporary.exists():
                temporary.unlink()

    def evidence(self):
        return dict(enabled=True, decay=self.decay,
                    shadow_update_unit="optimizer_step",
                    shadow_trainable_weight_names=self.trainable_names,
                    shadow_trainable_weight_count=len(self.trainable_names),
                    bn_state_policy="current_online_moving_state_copied_with_each_epoch_candidate",
                    bn_moving_state_names=self.bn_state_names,
                    bn_moving_state_count=len(self.bn_state_names),
                    validation_model="ema_trainables_plus_current_online_bn_state",
                    checkpoint_model="ema_trainables_plus_current_online_bn_state",
                    early_stopping_model="ema_trainables_plus_current_online_bn_state",
                    finalization="load_selected_checkpoint_only_no_final_shadow_overwrite",
                    shadow_update_count=int(self.update_count))


def make_ema_callback(keras, ema, checkpoint, checkpoint_metric):
    """Swap EMA trainables in only for Keras validation and EMA loss snapshots."""
    class EmaCallback(keras.callbacks.Callback):
        def __init__(self):
            super().__init__()
            self.best_val_loss = math.inf

        def on_train_batch_end(self, batch, logs=None):
            ema.update()

        def on_test_begin(self, logs=None):
            ema.activate()

        def on_test_end(self, logs=None):
            ema.restore()

        def on_epoch_end(self, epoch, logs=None):
            logs = logs or {}
            if checkpoint_metric == "val_loss":
                value = float(logs["val_loss"])
                if value < self.best_val_loss:
                    ema.save_candidate_atomic(checkpoint)
                    self.best_val_loss = value

    return EmaCallback()


def validate_distillation(teacher_paths, temperature, alpha):
    """Validate the registered three-teacher distillation contract."""
    temperature = float(temperature)
    alpha = float(alpha)
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("distillation temperature must be finite and positive")
    if not math.isfinite(alpha) or not 0 <= alpha <= 1:
        raise ValueError("distillation alpha must be finite and satisfy 0 <= alpha <= 1")
    paths = list(teacher_paths or [])
    if paths and len(paths) != 3:
        raise ValueError("distillation requires exactly three teacher models")
    if len({str(path) for path in paths}) != len(paths):
        raise ValueError("distillation teacher model paths must be distinct")
    if not paths and (temperature != 3.0 or alpha != .5):
        raise ValueError("distillation temperature/alpha require teacher models")
    if paths and (temperature != 3.0 or alpha != .5):
        raise ValueError("the registered distillation recipe requires temperature 3 and alpha .5")
    return paths, temperature, alpha


def distillation_loss_terms(tf, keras, labels, student_logits, teacher_logits,
                            class_weights, temperature=3.0, alpha=.5,
                            hard_label_loss="sparse_ce", focal_gamma=2.0):
    """Compute the exact registered per-sample hard-CE plus ensemble-KL loss."""
    if len(teacher_logits) != 3:
        raise ValueError("distillation loss requires exactly three teacher logits tensors")
    temperature = tf.cast(temperature, student_logits.dtype)
    alpha = tf.cast(alpha, student_logits.dtype)
    hard_per_sample = keras.losses.sparse_categorical_crossentropy(
        labels, student_logits, from_logits=True)
    class_weights = tf.cast(class_weights, hard_per_sample.dtype)
    hard_ce = tf.reduce_mean(hard_per_sample * class_weights)
    if hard_label_loss == "sparse_ce":
        hard_loss = hard_ce
    elif hard_label_loss == "focal":
        gamma = tf.cast(focal_gamma, hard_per_sample.dtype)
        probability = tf.nn.softmax(student_logits, axis=-1)
        true_probability = tf.gather(probability, tf.cast(labels, tf.int32),
                                     axis=1, batch_dims=1)
        focal_factor = tf.pow(tf.maximum(1.0 - true_probability, 0.0), gamma)
        hard_loss = tf.reduce_mean(hard_per_sample * focal_factor * class_weights)
    else:
        raise ValueError(f"unsupported hard-label loss: {hard_label_loss}")
    teacher_probabilities = [tf.nn.softmax(logits / temperature, axis=-1)
                             for logits in teacher_logits]
    teacher_mean = tf.add_n(teacher_probabilities) / tf.cast(
        len(teacher_probabilities), student_logits.dtype)
    teacher_mean = tf.stop_gradient(teacher_mean)
    teacher_log = tf.math.log(tf.maximum(
        teacher_mean, tf.cast(keras.backend.epsilon(), teacher_mean.dtype)))
    student_log = tf.nn.log_softmax(student_logits / temperature, axis=-1)
    kl_per_sample = tf.reduce_sum(teacher_mean * (teacher_log - student_log), axis=-1)
    kl = tf.reduce_mean(kl_per_sample)
    total = alpha * hard_loss + (1.0 - alpha) * temperature * temperature * kl
    return dict(total=total, hard_label_loss=hard_loss, hard_ce=hard_ce, kl=kl,
                teacher_mean_probability=teacher_mean)


def install_distillation_train_step(model, tf, keras, teachers,
                                    temperature=3.0, alpha=.5,
                                    hard_label_loss="sparse_ce", focal_gamma=2.0):
    """Install a train-only KD step and return a one-shot restoration function."""
    if len(teachers) != 3:
        raise ValueError("distillation train step requires exactly three teachers")
    for teacher in teachers:
        teacher.trainable = False
    had_instance_method = "train_step" in model.__dict__
    previous = model.__dict__.get("train_step")

    def train_step(self, data):
        inputs, labels, class_weights = keras.utils.unpack_x_y_sample_weight(data)
        if class_weights is None:
            class_weights = tf.ones_like(labels, dtype=tf.float32)
        teacher_logits = [teacher(inputs, training=False) for teacher in teachers]
        with tf.GradientTape() as tape:
            student_logits = self(inputs, training=True)
            terms = distillation_loss_terms(
                tf, keras, labels, student_logits, teacher_logits,
                class_weights, temperature, alpha, hard_label_loss, focal_gamma)
        gradients = tape.gradient(terms["total"], self.trainable_variables)
        if any(gradient is None for gradient in gradients):
            missing = [variable.name for variable, gradient in
                       zip(self.trainable_variables, gradients) if gradient is None]
            raise ValueError(f"distillation disconnected student gradients: {missing}")
        self.optimizer.apply_gradients(zip(gradients, self.trainable_variables))
        self.compiled_metrics.update_state(labels, student_logits)
        values = {metric.name: metric.result() for metric in self.metrics}
        values.update(loss=terms["total"], hard_label_loss=terms["hard_label_loss"],
                      hard_ce=terms["hard_ce"],
                      distillation_kl=terms["kl"],
                      distillation_batch_size=tf.shape(labels)[0])
        return values

    model.train_step = MethodType(train_step, model)
    restored = False

    def restore():
        nonlocal restored
        if restored:
            raise RuntimeError("distillation train_step was already restored")
        if had_instance_method:
            model.train_step = previous
        else:
            delattr(model, "train_step")
        model.train_function = None
        restored = True

    class DistillationEpochMetrics(keras.callbacks.Callback):
        """Replace last-batch KD diagnostics with sample-weighted epoch means."""
        def __init__(self):
            super().__init__()
            self.reset()

        def reset(self):
            self.sample_count = 0
            self.weighted = {name: 0.0 for name in
                             ("loss", "hard_label_loss", "hard_ce", "distillation_kl")}

        def on_epoch_begin(self, epoch, logs=None):
            self.reset()

        def on_train_batch_end(self, batch, logs=None):
            logs = logs or {}
            size = int(logs["distillation_batch_size"])
            if size <= 0:
                raise ValueError("distillation batch size must be positive")
            self.sample_count += size
            for name in self.weighted:
                self.weighted[name] += float(logs[name]) * size

        def on_epoch_end(self, epoch, logs=None):
            if self.sample_count <= 0:
                raise ValueError("distillation epoch contained no training samples")
            logs = logs if logs is not None else {}
            for name, total in self.weighted.items():
                logs[name] = total / self.sample_count
            logs.pop("distillation_batch_size", None)

    return restore, DistillationEpochMetrics()
