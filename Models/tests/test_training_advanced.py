"""Small synthetic tests for optional EMA/KD helpers; never fits a real model."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model_package import tensorflow
from training_advanced import (EmaCandidate, distillation_loss_terms,
                               install_distillation_train_step, make_ema_callback,
                               validate_distillation, validate_ema_decay)


class EmaCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tf = tensorflow()
        import tf_keras as keras
        cls.keras = keras

    def make_model(self):
        keras = self.keras
        inputs = keras.Input((2,), name="input")
        values = keras.layers.Dense(2, use_bias=True, kernel_initializer="ones",
                                    bias_initializer="zeros", name="dense")(inputs)
        values = keras.layers.BatchNormalization(name="bn")(values)
        return keras.Model(inputs, values)

    def test_decay_validation(self):
        self.assertEqual(validate_ema_decay(0), 0.)
        self.assertEqual(validate_ema_decay(.999), .999)
        for value in (-.1, 1, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_ema_decay(value)

    def test_shadow_updates_trainables_and_borrows_current_bn_state(self):
        model = self.make_model()
        ema = EmaCandidate(model, self.tf, .5)
        original = [value.numpy().copy() for value in model.trainable_variables]
        for value in model.trainable_variables:
            value.assign(value + 2.)
        online = [value.numpy().copy() for value in model.trainable_variables]
        ema.update()
        moving_mean = next(value for value in model.non_trainable_variables
                           if value.name.endswith("/moving_mean:0"))
        moving_mean.assign([7., 9.])
        with ema.candidate_scope():
            for actual, before in zip(model.trainable_variables, original):
                self.assertTrue((actual.numpy() == before + 1.).all())
            self.assertEqual(moving_mean.numpy().tolist(), [7., 9.])
        for actual, expected in zip(model.trainable_variables, online):
            self.assertTrue((actual.numpy() == expected).all())
        self.assertEqual(ema.update_count, 1)

    def test_atomic_checkpoint_contains_ema_and_bn_candidate_and_restores_online(self):
        model = self.make_model()
        ema = EmaCandidate(model, self.tf, .5)
        for value in model.trainable_variables:
            value.assign(value + 4.)
        online = [value.numpy().copy() for value in model.trainable_variables]
        ema.update()
        moving_mean = next(value for value in model.non_trainable_variables
                           if value.name.endswith("/moving_mean:0"))
        moving_mean.assign([3., 5.])
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "selected.weights.h5"
            ema.save_candidate_atomic(checkpoint)
            for actual, expected in zip(model.trainable_variables, online):
                self.assertTrue((actual.numpy() == expected).all())
            for value in model.weights:
                value.assign(self.tf.zeros_like(value))
            model.load_weights(str(checkpoint))
            for actual, before in zip(model.trainable_variables, online):
                self.assertTrue((actual.numpy() == before - 2.).all())
            self.assertEqual(moving_mean.numpy().tolist(), [3., 5.])

    def test_callback_updates_and_loss_checkpoint_uses_candidate(self):
        model = self.make_model()
        ema = EmaCandidate(model, self.tf, .5)
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "full.best.weights.h5"
            callback = make_ema_callback(self.keras, ema, checkpoint, "val_loss")
            callback.set_model(model)
            for value in model.trainable_variables:
                value.assign(value + 2.)
            callback.on_train_batch_end(0)
            callback.on_test_begin()
            callback.on_test_end()
            callback.on_epoch_end(0, {"val_loss": 1.})
            first = checkpoint.read_bytes()
            callback.on_epoch_end(1, {"val_loss": 1.1})
            self.assertEqual(checkpoint.read_bytes(), first)
            self.assertEqual(ema.update_count, 1)

    def test_distillation_contract_is_exactly_three_teachers_t3_alpha_half(self):
        paths, temperature, alpha = validate_distillation(['a','b','c'],3,.5)
        self.assertEqual(paths,['a','b','c'])
        self.assertEqual((temperature,alpha),(3.,.5))
        for paths,temperature,alpha in [(['a'],3,.5),(['a','a','c'],3,.5),
                                        (['a','b','c'],2,.5),(['a','b','c'],3,.4),
                                        ([],2,.5)]:
            with self.subTest(paths=paths,temperature=temperature,alpha=alpha), \
                    self.assertRaises(ValueError):
                validate_distillation(paths,temperature,alpha)

    def test_distillation_class_weight_changes_only_hard_ce_not_kl(self):
        tf,keras=self.tf,self.keras
        labels=tf.constant([0,1])
        student=tf.constant([[.2,-.1],[-.3,.4]],dtype=tf.float32)
        teachers=[tf.constant([[1.,0.],[0.,1.]],dtype=tf.float32),
                  tf.constant([[2.,0.],[0.,2.]],dtype=tf.float32),
                  tf.constant([[3.,0.],[0.,3.]],dtype=tf.float32)]
        first=distillation_loss_terms(tf,keras,labels,student,teachers,
                                      tf.constant([1.,1.]),3.,.5)
        second=distillation_loss_terms(tf,keras,labels,student,teachers,
                                       tf.constant([4.,1.]),3.,.5)
        self.assertEqual(float(first['kl']),float(second['kl']))
        self.assertNotEqual(float(first['hard_ce']),float(second['hard_ce']))
        self.assertAlmostEqual(float(first['total']),
                               .5*float(first['hard_ce'])+4.5*float(first['kl']),places=6)
        expected=sum((tf.nn.softmax(logits/3.,axis=-1) for logits in teachers))/3.
        self.assertTrue((abs(first['teacher_mean_probability']-expected)<1e-7).numpy().all())

    def test_focal_hard_term_preserves_kl_and_downweights_easy_examples(self):
        tf,keras=self.tf,self.keras
        labels=tf.constant([0,1])
        student=tf.constant([[4.,-4.],[-.2,.2]],dtype=tf.float32)
        teachers=[tf.constant([[1.,0.],[0.,1.]],dtype=tf.float32) for _ in range(3)]
        ce=distillation_loss_terms(tf,keras,labels,student,teachers,
                                   tf.constant([1.,1.]),3.,.5,'sparse_ce',2.)
        focal=distillation_loss_terms(tf,keras,labels,student,teachers,
                                      tf.constant([1.,1.]),3.,.5,'focal',2.)
        self.assertAlmostEqual(float(ce['kl']),float(focal['kl']),places=7)
        self.assertLess(float(focal['hard_label_loss']),float(ce['hard_label_loss']))
        self.assertAlmostEqual(float(focal['hard_ce']),float(ce['hard_ce']),places=7)

    def test_distillation_step_updates_only_student_and_restores_structure(self):
        tf,keras=self.tf,self.keras
        def dense_model(name,scale):
            inputs=keras.Input((2,),name=f'{name}_input')
            outputs=keras.layers.Dense(2,use_bias=False,name=f'{name}_dense')(inputs)
            model=keras.Model(inputs,outputs,name=name)
            model.layers[-1].set_weights([
                tf.constant([[scale,0.],[0.,scale]],dtype=tf.float32).numpy()])
            return model
        student=dense_model('student',.2)
        teachers=[dense_model(f'teacher_{number}',float(number+1)) for number in range(3)]
        before_json=student.to_json()
        before_student=[weight.numpy().copy() for weight in student.weights]
        before_teachers=[[weight.numpy().copy() for weight in teacher.weights]
                         for teacher in teachers]
        student.compile(optimizer=keras.optimizers.Adam(.01),
                        loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True),
                        metrics=['accuracy'])
        restore,epoch_metrics=install_distillation_train_step(
            student,tf,keras,teachers,3.,.5)
        values=student.train_on_batch(tf.constant([[1.,0.],[0.,1.]]),
                                      tf.constant([0,1]),
                                      sample_weight=tf.constant([2.,1.]),
                                      return_dict=True)
        self.assertIn('distillation_kl',values)
        restore()
        self.assertNotIn('train_step',student.__dict__)
        self.assertEqual(student.to_json(),before_json)
        self.assertTrue(any(not (actual.numpy()==before).all()
                            for actual,before in zip(student.weights,before_student)))
        for teacher,before in zip(teachers,before_teachers):
            self.assertTrue(all((actual.numpy()==expected).all()
                                for actual,expected in zip(teacher.weights,before)))
            self.assertFalse(teacher.trainable)

    def test_distillation_epoch_diagnostics_weight_batches_and_reset(self):
        student=self.make_model()
        teachers=[self.make_model() for _ in range(3)]
        student.compile(optimizer=self.keras.optimizers.Adam(.01),
                        loss=self.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
                        metrics=['accuracy'])
        restore,tracker=install_distillation_train_step(
            student,self.tf,self.keras,teachers,3.,.5)
        tracker.on_epoch_begin(0)
        tracker.on_train_batch_end(0,dict(loss=1.,hard_label_loss=2.,hard_ce=2.,distillation_kl=.2,
                                          distillation_batch_size=3))
        tracker.on_train_batch_end(1,dict(loss=5.,hard_label_loss=6.,hard_ce=6.,distillation_kl=1.,
                                          distillation_batch_size=1))
        epoch={"distillation_batch_size":99}
        tracker.on_epoch_end(0,epoch)
        self.assertEqual(epoch,dict(loss=2.,hard_label_loss=3.,hard_ce=3.,distillation_kl=.4))
        tracker.on_epoch_begin(1)
        tracker.on_train_batch_end(0,dict(loss=7.,hard_label_loss=8.,hard_ce=8.,distillation_kl=.5,
                                          distillation_batch_size=2))
        next_epoch={}
        tracker.on_epoch_end(1,next_epoch)
        self.assertEqual(next_epoch,dict(loss=7.,hard_label_loss=8.,hard_ce=8.,distillation_kl=.5))
        restore()


if __name__ == "__main__":
    unittest.main()
