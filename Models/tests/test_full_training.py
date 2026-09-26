"""Actual Keras graph checks: all parameters have gradients; BN updates in fit."""
import hashlib
import inspect
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('TF_USE_LEGACY_KERAS', '1')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import train_random_split as trainer
from train_random_split import (DelayedEarlyStoppingState, configure_trainability,
                                 adamw_exclusion_variables, build_seven_class_model,
                                 finite_float_or_none, make_full_optimizer, trainability_audit,
                                 moderate_class_weights, warmup_cosine_learning_rate)
from verify_full_training_run import (verify_distillation, verify_ema,
                                      verify_full_class_weights, verify_full_optimizer)
from training_advanced import EmaCandidate
from train import load_backbone


class FullTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tensorflow as tf
        import tf_keras as keras
        cls.tf, cls.keras = tf, keras

    def make_model(self):
        keras = self.keras
        keras.utils.set_random_seed(42)
        inputs = keras.Input((4, 4, 1))
        value = keras.layers.Conv2D(3, 1, name='test_conv', kernel_initializer=keras.initializers.GlorotUniform(seed=42))(inputs)
        value = keras.layers.BatchNormalization(name='test_bn')(value)
        backbone = keras.Model(inputs, value, name='nested_backbone')
        backbone.trainable = False
        outputs = keras.layers.Dense(7, kernel_initializer=keras.initializers.GlorotUniform(seed=42))(keras.layers.GlobalAveragePooling2D()(backbone(inputs)))
        return keras.Model(inputs, outputs), backbone

    def test_kd_teachers_deserialize_before_training_seed_and_student_build(self):
        source = inspect.getsource(trainer.train_float)
        teacher_load = source.index('teacher = keras.models.load_model')
        training_seed = source.index('keras.utils.set_random_seed(args.seed)')
        student_build = source.index('model=build_seven_class_model')
        self.assertLess(teacher_load, training_seed)
        self.assertLess(training_seed, student_build)
        self.assertNotIn('_SEED_GENERATOR', source)

    def test_full_mode_enables_nested_layers_and_all_gradients(self):
        model, backbone = self.make_model()
        audit = configure_trainability(model, backbone, self.keras, full=True)
        self.assertTrue(audit['all_gradient_parameters_trainable'])
        self.assertTrue(audit['batchnorm_training_enabled'])
        self.assertEqual(audit['excluded_gradient_weights'], [])
        with self.tf.GradientTape() as tape:
            logits = model(self.tf.reshape(self.tf.range(64, dtype=self.tf.float32), (4, 4, 4, 1)), training=True)
            loss = self.keras.losses.sparse_categorical_crossentropy([0, 1, 2, 3], logits, from_logits=True)
            loss = self.tf.reduce_mean(loss)
        gradients = tape.gradient(loss, model.trainable_weights)
        self.assertTrue(all(g is not None for g in gradients))
        bn = backbone.get_layer('test_bn')
        self.assertIn(id(bn.gamma), {id(w) for w in model.trainable_weights})
        self.assertIn(id(bn.beta), {id(w) for w in model.trainable_weights})
        self.assertNotIn(id(bn.moving_mean), {id(w) for w in model.trainable_weights})

    def test_training_step_changes_conv_bn_and_head_not_validation(self):
        import numpy as np
        model, backbone = self.make_model()
        configure_trainability(model, backbone, self.keras, full=True)
        before = {layer.name: [w.copy() for w in layer.get_weights()] for layer in model.submodules if layer.weights}
        model.compile(optimizer=self.keras.optimizers.Adam(.0001),
                      loss=self.keras.losses.SparseCategoricalCrossentropy(from_logits=True))
        x = np.arange(64, dtype=np.float32).reshape(4, 4, 4, 1)
        model.train_on_batch(x, np.arange(4))
        for layer in model.submodules:
            if layer.weights:
                self.assertTrue(any(not np.array_equal(a, b) for a, b in zip(before[layer.name], layer.get_weights())))
        bn_before = [w.copy() for w in backbone.get_layer('test_bn').get_weights()]
        model.predict(x, verbose=0)
        model.evaluate(x, np.arange(4), verbose=0)
        self.assertTrue(all(np.array_equal(a, b) for a, b in zip(bn_before, backbone.get_layer('test_bn').get_weights())))

    def test_full_audit_rejects_reintroduced_freeze(self):
        model, backbone = self.make_model()
        configure_trainability(model, backbone, self.keras, full=True)
        backbone.get_layer('test_bn').trainable = False
        with self.assertRaisesRegex(ValueError, 'excludes optimizer parameters'):
            trainability_audit(model, self.keras, require_full=True)

    def test_configured_dropout_rate_preserves_graph_shape_and_parameter_count(self):
        def backbone():
            inputs=self.keras.Input((4,4,1))
            outputs=self.keras.layers.Conv2D(3,1,name='dropout_test_conv',
                    kernel_initializer=self.keras.initializers.GlorotUniform(seed=42))(inputs)
            return self.keras.Model(inputs,outputs,name='dropout_test_backbone')
        default_model=build_seven_class_model(backbone(),self.keras,42)
        tuned_model=build_seven_class_model(backbone(),self.keras,42,.3)
        self.assertEqual(default_model.get_layer('project_seeded_dropout').rate,.1)
        self.assertEqual(tuned_model.get_layer('project_seeded_dropout').rate,.3)
        self.assertEqual(default_model.output_shape,tuned_model.output_shape)
        self.assertEqual(default_model.count_params(),tuned_model.count_params())

    def test_trainer_rejects_nonfinite_and_out_of_range_dropout(self):
        for value in ('nan','inf','-inf','-0.01','1','1.01'):
            with self.subTest(value=value),patch.object(sys,'argv',[
                    'trainer','unused-manifest.json','--output','unused-output',f'--dropout={value}']):
                with self.assertRaises(SystemExit) as caught:
                    trainer.main()
                self.assertEqual(caught.exception.code,2)

    def test_full_class_weight_is_explicit_and_full_only(self):
        with patch.object(sys,'argv',['trainer','unused-manifest.json','--output','unused-output',
                                      '--experiment','E1','--full-class-weight','sqrt_inverse']):
            with self.assertRaises(SystemExit) as caught:
                trainer.main()
        self.assertEqual(caught.exception.code,2)

    def test_full_optimizer_decay_pairs_are_strict(self):
        cases = [('adam','.01'),('adamw','0'),('adamw','nan'),('adamw','-0.1')]
        for optimizer,decay in cases:
            with self.subTest(optimizer=optimizer,decay=decay),patch.object(sys,'argv',[
                    'trainer','unused-manifest.json','--output','unused-output','--experiment','FULL',
                    '--full-optimizer',optimizer,'--full-weight-decay',decay]):
                with self.assertRaises(SystemExit) as caught:
                    trainer.main()
                self.assertEqual(caught.exception.code,2)

    def test_training_variants_are_full_only_and_factor_is_positive(self):
        cases = [
            ['--experiment','E1','--checkpoint-metric','val_accuracy'],
            ['--experiment','E1','--augmentation-profile','photo'],
            ['--experiment','E1','--augmentation-profile','geometry'],
            ['--experiment','E1','--personal-sampling-factor','2'],
            ['--experiment','E1','--ema-decay','.999'],
            ['--experiment','FULL','--personal-sampling-factor','0'],
            ['--experiment','FULL','--personal-sampling-factor','nan'],
            ['--experiment','FULL','--ema-decay','1'],
            ['--experiment','FULL','--ema-decay','nan'],
            ['--experiment','FULL','--teacher-model','only-one'],
            ['--experiment','FULL','--distillation-temperature','2'],
        ]
        for extra in cases:
            with self.subTest(extra=extra), patch.object(sys,'argv',[
                    'trainer','unused-manifest.json','--output','unused-output',*extra]):
                with self.assertRaises(SystemExit) as caught:
                    trainer.main()
                self.assertEqual(caught.exception.code,2)

    def test_adamw_excludes_actual_bn_and_bias_variables_before_build(self):
        import numpy as np
        model, backbone = self.make_model()
        configure_trainability(model, backbone, self.keras, full=True)
        optimizer, evidence = make_full_optimizer(model, self.keras, .1, 'adamw', .01)
        excluded = adamw_exclusion_variables(model, self.keras)
        excluded_ids = {id(weight) for weight in excluded}
        expected_excluded = {weight.name for weight in model.trainable_weights
                             if weight.name.endswith(('/gamma:0','/beta:0','/bias:0'))}
        self.assertEqual(set(evidence['excluded_from_weight_decay_names']), expected_excluded)
        self.assertEqual({weight.name for weight in excluded}, expected_excluded)
        self.assertTrue(all(not optimizer._use_weight_decay(weight) for weight in excluded))
        self.assertTrue(all(optimizer._use_weight_decay(weight) for weight in model.trainable_weights
                            if id(weight) not in excluded_ids))
        before = {id(weight): weight.numpy().copy() for weight in model.trainable_weights}
        optimizer.apply_gradients([(self.tf.zeros_like(weight),weight) for weight in model.trainable_weights])
        for weight in model.trainable_weights:
            expected = before[id(weight)] if id(weight) in excluded_ids else before[id(weight)] * (1 - .1 * .01)
            self.assertTrue(np.allclose(weight.numpy(),expected,rtol=1e-6,atol=1e-7),weight.name)
        with self.assertRaisesRegex(ValueError,'before the optimizer is built'):
            optimizer.exclude_from_weight_decay(var_list=excluded)

    def test_adamw_zero_decay_matches_reviewed_adam_one_step(self):
        import numpy as np
        first = self.tf.Variable([1.,-2.],name='adam_equivalence_first')
        second = self.tf.Variable([1.,-2.],name='adam_equivalence_second')
        gradient = self.tf.constant([.25,-.5])
        common = dict(learning_rate=.003,beta_1=.9,beta_2=.999,epsilon=1e-7,amsgrad=False)
        adam = self.keras.optimizers.Adam(adaptive_epsilon=False,**common)
        adamw = self.keras.optimizers.AdamW(weight_decay=0.,**common)
        adam.apply_gradients([(gradient,first)])
        adamw.apply_gradients([(gradient,second)])
        self.assertTrue(np.array_equal(first.numpy(),second.numpy()))

    def test_optimizer_evidence_verifier_is_strict_and_legacy_compatible(self):
        model, backbone = self.make_model()
        configure_trainability(model, backbone, self.keras, full=True)
        _, evidence = make_full_optimizer(model, self.keras, .0003, 'adamw', .01)
        report = dict(config=dict(full_optimizer='adamw',full_weight_decay=.01),
                      optimizer=evidence,
                      trainability=dict(trainable_weight_names=[w.name for w in model.trainable_weights]))
        detail = dict(optimizer=evidence)
        self.assertEqual(verify_full_optimizer(dict(full_optimizer='adamw',full_weight_decay=.01),report,detail),
                         'adamw')
        damaged = dict(evidence)
        damaged['decayed_weight_names'] = damaged['decayed_weight_names'][:-1]
        report['optimizer'] = damaged
        with self.assertRaisesRegex(ValueError,'top-level and stage|partition'):
            verify_full_optimizer(dict(full_optimizer='adamw',full_weight_decay=.01),report,detail)
        legacy = dict(config={},trainability=dict(trainable_weight_names=[]))
        self.assertEqual(verify_full_optimizer(dict(optimizer='Adam'),legacy,{}),'adam')

    def test_ema_evidence_verifier_is_strict_and_legacy_compatible(self):
        model, backbone = self.make_model()
        configure_trainability(model, backbone, self.keras, full=True)
        ema = EmaCandidate(model, self.tf, .999)
        ema.update_count = 2
        evidence = ema.evidence()
        report = dict(config=dict(ema_decay=.999,batch_size=2,smoke_samples_per_class=0),
                      dataset=dict(samples=[dict(split='train') for _ in range(4)]),
                      trainability=dict(trainable_weight_names=[w.name for w in model.trainable_weights]),
                      batchnorm_layer_count=1,ema=evidence)
        detail = dict(completed_epochs=1,ema=evidence)
        entries = [dict(evaluation_model='ema_trainables_plus_current_online_bn_state',
                        online_val_loss=.5)]
        self.assertEqual(verify_ema(dict(ema_decay=.999),report,detail,entries),.999)
        damaged = dict(evidence)
        damaged['bn_state_policy'] = 'ema_twice'
        report['ema'] = damaged
        detail['ema'] = damaged
        with self.assertRaisesRegex(ValueError,'semantics'):
            verify_ema(dict(ema_decay=.999),report,detail,entries)
        self.assertEqual(verify_ema({},dict(config={},ema=None),dict(ema=None),[]),0.)

    def test_distillation_evidence_verifier_hashes_teachers_and_semantics(self):
        from train import source_hashes
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            records=[]
            for number in range(3):
                teacher=root/f'teacher-{number}'
                teacher.mkdir()
                (teacher/'saved_model.pb').write_bytes(bytes([number]))
                records.append(dict(path=str(teacher),files_sha256=source_hashes(teacher)))
            evidence=dict(enabled=True,teacher_count=3,teacher_models=records,
                temperature=3.,alpha_hard_ce=.5,alpha_kl=.5,
                teacher_ensemble='uniform_mean_softmax_logits_over_three_teachers',
                train_input='same_augmented_batch_as_student_after_horizontal_flip',
                teacher_output_label_handling='no_post_inference_left_right_swap',
                hard_target='post_augmentation_target_with_left_right_swap_for_horizontal_flip',
                class_weight_scope='hard_ce_only',kl_class_weighted=False,
                validation_loss='unweighted_student_hard_cross_entropy',teacher_training=False,
                epoch_diagnostic_aggregation='sample_count_weighted_mean_reset_each_epoch',
                teacher_deserialization='keras_load_model_compile_false_before_training_seed',
                training_seed_reset_after_teacher_load=True,
                student_all_parameters_trainable=True,teacher_attached_to_student=False,
                saved_model_contains_teacher=False,train_step_restored=True,
                student_weight_count=83,teacher_weight_counts=[83,83,83],
                student_structure_unchanged=True,student_structure_sha256_before='same',
                student_structure_sha256_after='same')
            spec=dict(teacher_models=records,distillation_temperature=3.,distillation_alpha=.5)
            report=dict(config=dict(teacher_model=[row['path'] for row in records],
                                    distillation_temperature=3.,distillation_alpha=.5),
                        distillation=evidence)
            detail=dict(distillation=evidence)
            entries=[dict(train_objective='hard_ce_plus_temperature_squared_kl',
                          train_hard_ce=.8,train_distillation_kl=.1)]
            self.assertTrue(verify_distillation(spec,report,detail,entries))
            (Path(records[0]['path'])/'saved_model.pb').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'teacher changed'):
                verify_distillation(spec,report,detail,entries)
        self.assertFalse(verify_distillation({},dict(config={},distillation=None),
                                             dict(distillation=None),[]))

    def test_verifier_recomputes_sqrt_weights_from_train_labels(self):
        import numpy as np
        counts = [84,63,224,280,287,280,182]
        samples = [dict(label=label,split='train') for label,count in zip(trainer.LABELS,counts)
                   for _ in range(count)]
        labels = np.array([i for i,count in enumerate(counts) for _ in range(count)],dtype=np.int64)
        weights = moderate_class_weights(labels).tolist()
        report = dict(config=dict(full_class_weight='sqrt_inverse'),
                      dataset=dict(samples=samples),train_class_weights=weights,
                      class_weighting=dict(mode='sqrt_inverse',source_split='train',
                                           weights=weights,validation_weighted=False))
        self.assertEqual(verify_full_class_weights(dict(full_class_weight='sqrt_inverse'),report),
                         'sqrt_inverse')
        report['train_class_weights'][0] += .1
        with self.assertRaisesRegex(ValueError,'do not match train labels'):
            verify_full_class_weights(dict(full_class_weight='sqrt_inverse'),report)

    def test_verifier_accepts_legacy_unweighted_report(self):
        samples = [dict(label=label,split='train') for label in trainer.LABELS]
        report = dict(config={},dataset=dict(samples=samples),train_class_weights=[1.]*7)
        self.assertEqual(verify_full_class_weights({},report),'none')

    def test_warmup_cosine_boundaries(self):
        self.assertAlmostEqual(warmup_cosine_learning_rate(1,200),1e-5)
        self.assertAlmostEqual(warmup_cosine_learning_rate(5,200),1e-4)
        middle=warmup_cosine_learning_rate(100,200)
        self.assertGreater(middle,1e-6)
        self.assertLess(middle,1e-4)
        self.assertAlmostEqual(warmup_cosine_learning_rate(200,200),1e-6)

    def test_uninitialized_keras_best_is_json_safe(self):
        self.assertIsNone(finite_float_or_none(float('inf')))
        self.assertIsNone(finite_float_or_none(float('nan')))
        self.assertEqual(finite_float_or_none(1.25),1.25)

    def test_delayed_early_stopping_cannot_stop_before_epoch_165(self):
        state=DelayedEarlyStoppingState(start_epoch=151,min_delta=.001,patience=15)
        for epoch in range(1,151):
            snapshot=state.update(epoch,1.0)
            self.assertFalse(snapshot['stop_triggered'])
            self.assertEqual(snapshot['wait'],0)
        for epoch in range(151,165):
            self.assertFalse(state.update(epoch,1.0)['stop_triggered'])
        final=state.update(165,1.0)
        self.assertTrue(final['stop_triggered'])
        self.assertEqual(final['stopped_epoch'],165)

    def test_min_delta_accumulates_against_last_significant_best(self):
        state=DelayedEarlyStoppingState(start_epoch=151,min_delta=.001,patience=15)
        for epoch in range(1,151):
            state.update(epoch,1.0)
        self.assertEqual(state.update(151,.9996)['wait'],1)
        self.assertEqual(state.update(152,.9991)['wait'],2)
        improved=state.update(153,.9989)
        self.assertEqual(improved['wait'],0)
        self.assertAlmostEqual(improved['significant_best_val_loss'],.9989)

    def test_exact_min_delta_counts_as_cumulative_improvement(self):
        state=DelayedEarlyStoppingState(start_epoch=151,min_delta=.001,patience=15)
        for epoch in range(1,151):
            state.update(epoch,1.0)
        improved=state.update(151,1.0-.001)
        self.assertEqual(improved['wait'],0)
        self.assertAlmostEqual(improved['significant_best_val_loss'],.999)

    def test_checkpoint_improvement_is_not_limited_by_early_stop_delta(self):
        state=DelayedEarlyStoppingState(start_epoch=151,min_delta=.001,patience=15)
        for epoch in range(1,151):
            state.update(epoch,1.0)
        snapshot=state.update(151,.9996)
        checkpoint=self.keras.callbacks.ModelCheckpoint('unused.weights.h5',monitor='val_loss',
                                                         save_best_only=True,save_weights_only=True)
        self.assertTrue(checkpoint.monitor_op(.9996,1.0))
        self.assertEqual(snapshot['wait'],1)
        self.assertAlmostEqual(snapshot['significant_best_val_loss'],1.0)

    def test_00_reviewed_actual_backbone_has_no_disconnected_gradient_parameters(self):
        import numpy as np
        project = Path(__file__).resolve().parents[3]
        pretrained = project / 'artifacts/model_audit/arm_openmv/pretrained/model'
        tf, keras, backbone = load_backbone(pretrained)
        saved_sha = hashlib.sha256((pretrained / 'saved_model.pb').read_bytes()).hexdigest()
        logits = keras.layers.Conv2D(7, 1, kernel_initializer=keras.initializers.GlorotUniform(seed=42))(backbone.output)
        model = keras.Model(backbone.input, keras.layers.Flatten()(logits))
        audit = configure_trainability(model, backbone, keras, full=True)
        self.assertTrue(audit['all_gradient_parameters_trainable'])
        self.assertEqual(len([l for l in backbone.layers if isinstance(l, keras.layers.BatchNormalization)]), 27)
        x = np.random.default_rng(42).uniform(0, 255, (2, 96, 96, 1)).astype(np.float32)
        with tf.GradientTape() as tape:
            values = model(x, training=True)
            loss = tf.reduce_mean(keras.losses.sparse_categorical_crossentropy([0, 1], values, from_logits=True))
        gradients = tape.gradient(loss, model.trainable_weights)
        self.assertTrue(all(g is not None for g in gradients))
        self.assertTrue(all(bool(tf.reduce_all(tf.math.is_finite(g))) for g in gradients))
        self.assertEqual(hashlib.sha256((pretrained / 'saved_model.pb').read_bytes()).hexdigest(), saved_sha)


if __name__ == '__main__':
    unittest.main()
