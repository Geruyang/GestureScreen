"""Read-only numerical/file integrity audit; never fits, predicts or accesses hardware."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path

from dataset import LABELS
from train_random_split import classification_metrics, moderate_class_weights
from train import source_hashes
from training_variants import (PERSONAL_SOURCE, augmentation_evidence,
                               epoch_training_indexes, sampling_evidence,
                               select_checkpoint_entry)


def check(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def verify_full_class_weights(spec, report):
    """Recompute FULL train-only weights; old reports default to unweighted."""
    import numpy as np
    mode = spec.get('full_class_weight') or 'none'
    check(mode in ('none', 'sqrt_inverse'), 'unsupported full class-weight mode')
    check((report['config'].get('full_class_weight') or 'none') == mode,
          'class-weight config mismatch')
    train_labels = np.array([LABELS.index(row['label']) for row in report['dataset']['samples']
                             if row['split'] == 'train'], dtype=np.int64)
    expected = (moderate_class_weights(train_labels) if mode == 'sqrt_inverse'
                else np.ones(len(LABELS), dtype=np.float32))
    actual = np.asarray(report['train_class_weights'], dtype=np.float32)
    check(actual.shape == expected.shape and np.allclose(actual, expected, rtol=1e-7, atol=1e-7),
          'train class weights do not match train labels')
    evidence = report.get('class_weighting')
    if evidence is None:
        check(mode == 'none', 'weighted run lacks class-weight evidence')
    else:
        check(evidence.get('mode') == mode, 'class-weight evidence mode mismatch')
        check(evidence.get('source_split') == ('train' if mode == 'sqrt_inverse' else None),
              'class weights were not recorded as train-only')
        recorded = np.asarray(evidence.get('weights'), dtype=np.float32)
        check(recorded.shape == expected.shape and np.allclose(recorded, expected, rtol=1e-7, atol=1e-7),
              'class-weight evidence values mismatch')
        check(evidence.get('validation_weighted') is False, 'validation must remain unweighted')
    return mode


def verify_full_optimizer(spec, report, detail):
    """Strict optimizer/decay audit with compatibility for historical Adam."""
    name = (spec.get('full_optimizer') or spec.get('optimizer') or 'adam').lower()
    if name == 'adamw':
        expected_decay = spec.get('full_weight_decay')
        check(isinstance(expected_decay, (int, float)) and expected_decay > 0,
              'AdamW requires positive recorded weight decay')
    else:
        check(name == 'adam', 'unsupported FULL optimizer')
        expected_decay = spec.get('full_weight_decay') or 0.0
        check(expected_decay == 0, 'Adam must not use weight decay')
    config_name = (report['config'].get('full_optimizer') or 'adam').lower()
    config_decay = report['config'].get('full_weight_decay') or 0.0
    check(config_name == name and config_decay == expected_decay, 'optimizer config mismatch')
    evidence = report.get('optimizer')
    stage_evidence = detail.get('optimizer')
    if evidence is None or stage_evidence is None:
        check(name == 'adam' and expected_decay == 0 and evidence is None and stage_evidence is None,
              'non-legacy optimizer evidence missing')
        return name
    check(evidence == stage_evidence, 'top-level and stage optimizer evidence differ')
    check(evidence.get('name') == name and evidence.get('weight_decay') == expected_decay,
          'optimizer evidence recipe mismatch')
    check(evidence.get('beta_1') == .9 and evidence.get('beta_2') == .999 and
          evidence.get('epsilon') == 1e-7 and evidence.get('amsgrad') is False,
          'optimizer defaults differ from reviewed Adam settings')
    excluded = evidence.get('excluded_from_weight_decay_names', [])
    decayed = evidence.get('decayed_weight_names', [])
    check(len(excluded) == len(set(excluded)) and len(decayed) == len(set(decayed)),
          'duplicate optimizer weight evidence')
    trainable = report['trainability']['trainable_weight_names']
    check(evidence.get('trainable_weight_count') == len(trainable), 'trainable weight count mismatch')
    if name == 'adam':
        check(not excluded and not decayed and
              evidence.get('excluded_from_weight_decay_count') == 0 and
              evidence.get('decayed_weight_count') == 0,
              'Adam unexpectedly records decay variables')
        return name
    expected_excluded = {weight for weight in trainable if weight.endswith(('/gamma:0', '/beta:0', '/bias:0'))}
    expected_decayed = set(trainable) - expected_excluded
    check(set(excluded) == expected_excluded and set(decayed) == expected_decayed,
          'AdamW excluded/decayed variable partition mismatch')
    check(not expected_excluded & expected_decayed and expected_excluded | expected_decayed == set(trainable),
          'AdamW variable partition is incomplete')
    check(all(weight.endswith(('/kernel:0', '/depthwise_kernel:0')) for weight in expected_decayed),
          'AdamW decay includes a non-kernel weight')
    check(evidence.get('excluded_from_weight_decay_count') == len(expected_excluded) and
          evidence.get('decayed_weight_count') == len(expected_decayed), 'AdamW decay counts mismatch')
    check(evidence.get('exclusion_uses_actual_variables') is True and
          evidence.get('decay_is_decoupled') is True, 'AdamW implementation evidence missing')
    return name


def verify_training_variants(spec, report, detail):
    """Audit optional checkpoint, augmentation, sampling and personal metrics."""
    import math
    import numpy as np
    checkpoint_metric = spec.get('checkpoint_metric') or 'val_loss'
    profile = spec.get('augmentation_profile') or 'flip'
    personal_factor = spec.get('personal_sampling_factor') or 1.0
    config = report['config']
    check((config.get('checkpoint_metric') or 'val_loss') == checkpoint_metric,
          'checkpoint metric config mismatch')
    check((config.get('augmentation_profile') or 'flip') == profile,
          'augmentation profile config mismatch')
    check((config.get('personal_sampling_factor') or 1.0) == personal_factor,
          'personal sampling factor config mismatch')
    entries = [entry for entry in report['progress_history'] if entry['stage'] == 'full']
    expected_checkpoint = select_checkpoint_entry(entries, checkpoint_metric)
    minimum_entry = min(entries, key=lambda entry: (float(entry['val_loss']), int(entry['epoch'])))
    selection = report.get('checkpoint_selection')
    if selection is None:
        check(checkpoint_metric == 'val_loss', 'non-legacy checkpoint evidence missing')
        check(detail['best_epoch'] == minimum_entry['epoch'], 'legacy checkpoint epoch mismatch')
    else:
        check(selection.get('metric') == checkpoint_metric and
              selection.get('epoch') == expected_checkpoint['epoch'], 'checkpoint selection mismatch')
        check(report.get('checkpoint_best_epoch') == detail.get('checkpoint_best_epoch') ==
              expected_checkpoint['epoch'], 'checkpoint best epoch mismatch')
        check(detail.get('checkpoint_metric') == checkpoint_metric,
              'stage checkpoint metric mismatch')
        expected_metrics = {key:expected_checkpoint[key] for key in
                            ('val_correct_count','val_accuracy','val_macro_f1','val_loss')}
        check(selection.get('metrics') == detail.get('checkpoint_metrics') == expected_metrics,
              'checkpoint metrics mismatch')
        check(report.get('minimum_val_loss_epoch') == detail.get('minimum_val_loss_epoch') ==
              minimum_entry['epoch'], 'minimum validation-loss epoch mismatch')
        check(math.isclose(report.get('minimum_val_loss'), float(minimum_entry['val_loss']),
                           rel_tol=1e-9, abs_tol=1e-9) and
              math.isclose(detail.get('minimum_val_loss'), float(minimum_entry['val_loss']),
                           rel_tol=1e-9, abs_tol=1e-9), 'minimum validation loss mismatch')
        check(math.isclose(report['selected_val_loss'], float(expected_checkpoint['val_loss']),
                           rel_tol=1e-5, abs_tol=1e-6), 'selected checkpoint CE mismatch')
        check(report['validation']['accuracy'] == expected_checkpoint['val_accuracy'] and
              report['validation']['macro_f1'] == expected_checkpoint['val_macro_f1'],
              'selected checkpoint classification metrics mismatch')

    new_evidence = any(key in spec for key in
                       ('checkpoint_metric','augmentation_profile','personal_sampling_factor'))
    recorded_augmentation = report.get('augmentation')
    if recorded_augmentation is None:
        check(not new_evidence and profile == 'flip', 'augmentation evidence missing')
    else:
        check(recorded_augmentation == augmentation_evidence(profile),
              'augmentation evidence mismatch')

    labels = np.array([LABELS.index(row['label']) for row in report['dataset']['samples']], dtype=np.int64)
    sources = np.array([row.get('source','unknown') for row in report['dataset']['samples']], dtype=object)
    train_indexes = np.array([i for i,row in enumerate(report['dataset']['samples'])
                              if row['split'] == 'train'], dtype=np.int64)
    expected_sampling = sampling_evidence(train_indexes, labels, sources, LABELS, personal_factor)
    recorded_sampling = report.get('sampling')
    if recorded_sampling is None:
        check(not new_evidence and personal_factor == 1.0, 'sampling evidence missing')
    else:
        check(recorded_sampling == expected_sampling, 'sampling configuration evidence mismatch')
        history = report.get('sampling_history')
        check(isinstance(history, list) and len(history) == detail['completed_epochs'],
              'sampling history length mismatch')
        check(history == [entry.get('train_sampling') for entry in entries],
              'sampling history differs from epoch log')
        for epoch, actual in enumerate(history):
            _indexes, expected = epoch_training_indexes(
                train_indexes, labels, sources, LABELS, personal_factor,
                int(report['config']['seed']), epoch)
            batch_count = (len(train_indexes) + int(report['config']['batch_size']) - 1) // int(report['config']['batch_size'])
            expected.update(requested_batch_numbers=list(range(batch_count)),
                            expected_batch_count=batch_count,
                            all_batch_numbers_observed=True)
            check(actual == expected, f'train sampling mismatch at epoch {epoch+1}')

    expected_personal_count = sum(row['split'] == 'validation' and
                                  row.get('source','unknown') == PERSONAL_SOURCE
                                  for row in report['dataset']['samples'])
    expected_validation_count = sum(row['split'] == 'validation'
                                    for row in report['dataset']['samples'])
    validation_confusions = all('val_confusion' in entry for entry in entries)
    if not validation_confusions:
        check(not new_evidence, 'validation confusion epoch evidence missing')
    else:
        for entry in entries:
            confusion = np.asarray(entry['val_confusion'], dtype=np.int64)
            check(confusion.shape == (len(LABELS),len(LABELS)) and
                  np.all(confusion >= 0) and int(confusion.sum()) == expected_validation_count,
                  'invalid validation confusion')
            correct = int(np.diag(confusion).sum())
            support = confusion.sum(axis=1)
            predicted_count = confusion.sum(axis=0)
            precision = np.divide(np.diag(confusion), predicted_count,
                                  out=np.zeros(len(LABELS)), where=predicted_count != 0)
            recall = np.divide(np.diag(confusion), support,
                               out=np.zeros(len(LABELS)), where=support != 0)
            f1 = np.divide(2*precision*recall, precision+recall,
                           out=np.zeros(len(LABELS)), where=precision+recall != 0)
            check(entry['val_correct_count'] == correct and
                  entry['val_accuracy'] == correct/expected_validation_count,
                  'validation accuracy evidence mismatch')
            check(math.isclose(entry['val_macro_f1'], float(f1.mean()),
                               rel_tol=1e-12, abs_tol=1e-12),
                  'validation macro-F1 evidence mismatch')
            check(all(math.isclose(entry['val_per_class_recall'][label], float(recall[number]),
                                   rel_tol=1e-12, abs_tol=1e-12)
                      for number,label in enumerate(LABELS)),
                  'validation per-class recall evidence mismatch')
    personal_fields = all('val_personal_confusion' in entry for entry in entries)
    if not personal_fields:
        check(not new_evidence, 'personal validation epoch evidence missing')
    else:
        for entry in entries:
            confusion = np.asarray(entry['val_personal_confusion'], dtype=np.int64)
            check(confusion.shape == (len(LABELS),len(LABELS)) and np.all(confusion >= 0),
                  'invalid personal validation confusion')
            support = confusion.sum(axis=1)
            recall = np.divide(np.diag(confusion), support, out=np.zeros(len(LABELS)), where=support != 0)
            recorded_recall = entry['val_personal_per_class_recall']
            check(entry['val_personal_sample_count'] == expected_personal_count == int(confusion.sum()),
                  'personal validation sample count mismatch')
            check(set(recorded_recall) == set(LABELS) and
                  all(math.isclose(recorded_recall[label], float(recall[number]),
                                   rel_tol=1e-12, abs_tol=1e-12)
                      for number,label in enumerate(LABELS)), 'personal validation recall mismatch')
            check(math.isclose(entry['val_personal_balanced_accuracy'], float(recall.mean()),
                               rel_tol=1e-12, abs_tol=1e-12),
                  'personal validation balanced accuracy mismatch')
    return checkpoint_metric, profile, float(personal_factor), expected_checkpoint


def verify_ema(spec, report, detail, entries):
    """Audit the optional EMA candidate without loading or predicting a model."""
    import math
    decay = float(spec.get('ema_decay') or 0.0)
    check(math.isfinite(decay) and 0 <= decay < 1, 'invalid EMA decay')
    check(float(report['config'].get('ema_decay') or 0.0) == decay, 'EMA config mismatch')
    evidence = report.get('ema')
    stage_evidence = detail.get('ema')
    if decay == 0:
        check(evidence is None and stage_evidence is None, 'legacy run unexpectedly used EMA')
        return decay
    check(evidence == stage_evidence and isinstance(evidence, dict),
          'EMA top-level/stage evidence missing or inconsistent')
    check(evidence.get('enabled') is True and evidence.get('decay') == decay,
          'EMA evidence recipe mismatch')
    trainable_names = report['trainability']['trainable_weight_names']
    shadow_names = evidence.get('shadow_trainable_weight_names')
    check(shadow_names == trainable_names and
          evidence.get('shadow_trainable_weight_count') == len(trainable_names),
          'EMA shadow does not cover every trainable weight in model order')
    bn_names = evidence.get('bn_moving_state_names')
    check(isinstance(bn_names, list) and len(bn_names) == len(set(bn_names)) ==
          evidence.get('bn_moving_state_count') == 2 * report['batchnorm_layer_count'],
          'EMA BN moving-state evidence is incomplete')
    check(all(name.endswith(('/moving_mean:0', '/moving_variance:0')) for name in bn_names),
          'EMA BN state includes an unexpected variable')
    candidate = 'ema_trainables_plus_current_online_bn_state'
    check(evidence.get('shadow_update_unit') == 'optimizer_step' and
          evidence.get('bn_state_policy') ==
          'current_online_moving_state_copied_with_each_epoch_candidate' and
          evidence.get('validation_model') == evidence.get('checkpoint_model') ==
          evidence.get('early_stopping_model') == candidate and
          evidence.get('finalization') ==
          'load_selected_checkpoint_only_no_final_shadow_overwrite',
          'EMA candidate semantics differ from the registered plan')
    train_count = sum(row['split'] == 'train' for row in report['dataset']['samples'])
    smoke_limit = int(report['config'].get('smoke_samples_per_class') or 0)
    if smoke_limit:
        train_count = min(train_count, smoke_limit * len(LABELS))
    expected_updates = ((train_count + int(report['config']['batch_size']) - 1) //
                        int(report['config']['batch_size'])) * detail['completed_epochs']
    check(evidence.get('shadow_update_count') == expected_updates,
          'EMA shadow update count differs from optimizer-step count')
    check(all(entry.get('evaluation_model') == candidate and
              isinstance(entry.get('online_val_loss'), (int, float)) and
              math.isfinite(entry['online_val_loss'])
              for entry in entries), 'EMA epoch diagnostics/evaluation identity missing')
    return decay


def verify_distillation(spec, report, detail, entries):
    """Audit train-only KD configuration and immutable external teachers."""
    teacher_specs = spec.get('teacher_models') or []
    config_paths = report['config'].get('teacher_model') or []
    evidence = report.get('distillation')
    stage_evidence = detail.get('distillation')
    if not teacher_specs:
        check(not config_paths and evidence is None and stage_evidence is None,
              'legacy/non-KD run unexpectedly records distillation')
        return False
    check(len(teacher_specs) == 3 and len({row.get('path') for row in teacher_specs}) == 3,
          'distillation requires three distinct recorded teachers')
    check(config_paths == [row['path'] for row in teacher_specs],
          'distillation trainer paths differ from run spec')
    check(report['config'].get('distillation_temperature') ==
          spec.get('distillation_temperature') and
          report['config'].get('distillation_alpha') == spec.get('distillation_alpha'),
          'distillation trainer scalars differ from run spec')
    check(evidence == stage_evidence and isinstance(evidence, dict),
          'distillation top-level/stage evidence missing or inconsistent')
    check(evidence.get('enabled') is True and evidence.get('teacher_count') == 3 and
          evidence.get('teacher_models') == teacher_specs,
          'distillation teacher evidence mismatch')
    check(spec.get('distillation_temperature') == evidence.get('temperature') == 3.0 and
          spec.get('distillation_alpha') == evidence.get('alpha_hard_ce') == .5 and
          evidence.get('alpha_kl') == .5,
          'distillation temperature/alpha differs from registered recipe')
    check(evidence.get('teacher_ensemble') ==
          'uniform_mean_softmax_logits_over_three_teachers' and
          evidence.get('train_input') ==
          'same_augmented_batch_as_student_after_horizontal_flip' and
          evidence.get('teacher_output_label_handling') ==
          'no_post_inference_left_right_swap' and
          evidence.get('hard_target') ==
          'post_augmentation_target_with_left_right_swap_for_horizontal_flip',
          'distillation input/label semantics mismatch')
    check(evidence.get('class_weight_scope') == 'hard_ce_only' and
          evidence.get('kl_class_weighted') is False and
          evidence.get('validation_loss') == 'unweighted_student_hard_cross_entropy' and
          evidence.get('epoch_diagnostic_aggregation') ==
          'sample_count_weighted_mean_reset_each_epoch',
          'distillation class-weight or validation semantics mismatch')
    check(evidence.get('teacher_deserialization') ==
          'keras_load_model_compile_false_before_training_seed' and
          evidence.get('training_seed_reset_after_teacher_load') is True,
          'distillation teacher-load compatibility evidence missing')
    check(evidence.get('teacher_training') is False and
          evidence.get('student_all_parameters_trainable') is True and
          evidence.get('teacher_attached_to_student') is False and
          evidence.get('saved_model_contains_teacher') is False and
          evidence.get('train_step_restored') is True,
          'distillation model ownership/trainability evidence mismatch')
    check(isinstance(evidence.get('student_weight_count'), int) and
          evidence['student_weight_count'] > 0 and
          isinstance(evidence.get('teacher_weight_counts'), list) and
          len(evidence['teacher_weight_counts']) == 3 and
          all(isinstance(count, int) and count > 0
              for count in evidence['teacher_weight_counts']),
          'distillation model weight-count evidence missing')
    check(evidence.get('student_structure_unchanged') is True and
          evidence.get('student_structure_sha256_before') ==
          evidence.get('student_structure_sha256_after'),
          'distillation changed student inference structure')
    import math
    check(all(entry.get('train_objective') ==
              'hard_ce_plus_temperature_squared_kl' and
              isinstance(entry.get('train_hard_ce'), (int, float)) and
              math.isfinite(entry['train_hard_ce']) and
              isinstance(entry.get('train_distillation_kl'), (int, float)) and
              math.isfinite(entry['train_distillation_kl']) and
              entry['train_distillation_kl'] >= 0
              for entry in entries), 'distillation epoch loss diagnostics missing')
    for teacher in teacher_specs:
        path = Path(teacher['path'])
        check(path.is_dir() and source_hashes(path) == teacher.get('files_sha256'),
              f'distillation teacher changed: {path}')
    return True


def verify(root, manifest):
    state, spec, chosen = [read(root / name) for name in ('experiment_status.json', 'run_spec.json', 'frozen_candidate.json')]
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    deferred = state['status'] == 'validation_completed' and not state['test_evaluated']
    check(deferred or (state['status'] == 'completed' and state['test_evaluated']), 'experiment not completed')
    check(spec['training_mode'] == state['training_mode'] == 'full', 'not a full training experiment')
    check(spec['head_epochs'] == spec['finetune_epochs'] == 0 and not spec['batchnorm_frozen'], 'inactive stage or BN freeze')
    check(0 < spec['full_epochs'] <= 200 and 0 < spec['full_lr'] < 1, 'unexpected recipe')
    check((spec.get('full_class_weight') or 'none') in ('none', 'sqrt_inverse'), 'unexpected class-weight recipe')
    for key, legacy_default in (('checkpoint_metric','val_loss'),
                                ('augmentation_profile','flip'),
                                ('personal_sampling_factor',1.0),
                                ('ema_decay',0.0)):
        check((state.get(key) if state.get(key) is not None else legacy_default) ==
              (spec.get(key) if spec.get(key) is not None else legacy_default),
              f'{key} differs between state and run spec')
    check((state.get('teacher_models') or []) == (spec.get('teacher_models') or []),
          'teacher models differ between state and run spec')
    check((state.get('distillation_temperature') if state.get('distillation_temperature') is not None else 3.0) ==
          (spec.get('distillation_temperature') if spec.get('distillation_temperature') is not None else 3.0) and
          (state.get('distillation_alpha') if state.get('distillation_alpha') is not None else .5) ==
          (spec.get('distillation_alpha') if spec.get('distillation_alpha') is not None else .5),
          'distillation scalars differ between state and run spec')
    expected_runs = {f'FULL-seed{seed}' for seed in (20260918, 42, 20260919)}
    check({row['run_id'] for row in state['completed_runs']} == expected_runs and len(state['completed_runs']) == 3, 'unexpected runs')
    rows = []
    for run_id in sorted(expected_runs):
        directory = root / run_id
        report = read(directory / 'training_report.json')
        check(report['dataset']['manifest_sha256'] == manifest_sha, 'mixed manifest')
        check(report['config']['experiment'] == 'FULL' and report['selected_stage'] == 'full', 'staged run included')
        check(set(report['history']) == set(report['stage_details']) == {'full'}, 'non-full phase present')
        for audit in (report['initial_trainability'], report['trainability'], report['stage_details']['full']['trainability']):
            check(audit['all_gradient_parameters_trainable'] and audit['batchnorm_training_enabled'], 'excluded parameters')
            check(not audit['frozen_weight_layers'] and not audit['excluded_gradient_weights'], 'frozen weights')
            check(audit['trainable_parameters'] == 214727, 'unexpected optimizer parameter count')
        check(report['batchnorm_layer_count'] == 27 and not report['batchnorm_unchanged'], 'BN did not update')
        check(report['batchnorm_before_sha256'] != report['batchnorm_after_sha256'], 'BN hash unchanged')
        check(len(report['changed_backbone_layers']) == 54, 'some reviewed backbone weight layers unchanged')
        check(not any(report[name] for name in ('quantization_performed', 'c_export_performed', 'installed', 'test_evaluated', 'validated_for_business')), 'scope violation')
        history, detail = report['history']['full'], report['stage_details']['full']
        best_epoch = min(range(len(history['val_loss'])), key=lambda i: history['val_loss'][i]) + 1
        check(detail['best_epoch'] == best_epoch and detail['completed_epochs'] == len(history['loss']), 'history / best epoch mismatch')
        check(best_epoch <= detail['completed_epochs'] <= detail['max_epochs'] == spec['full_epochs'], 'invalid epoch count')
        check(report['config']['full_lr'] == spec['full_lr'], 'peak learning rate mismatch')
        check(report['config'].get('dropout', .1) == spec.get('dropout', .1), 'dropout mismatch')
        check(0 <= spec.get('dropout', .1) < 1, 'invalid dropout')
        class_weight_mode = verify_full_class_weights(spec, report)
        optimizer_name = verify_full_optimizer(spec, report, detail)
        checkpoint_metric, augmentation_profile, personal_factor, checkpoint_entry = \
            verify_training_variants(spec, report, detail)
        ema_decay = verify_ema(spec, report, detail,
                               [entry for entry in report['progress_history']
                                if entry['stage'] == 'full'])
        distilled = verify_distillation(spec, report, detail,
                                         [entry for entry in report['progress_history']
                                          if entry['stage'] == 'full'])
        if spec.get('full_lr_schedule') == 'warmup_cosine':
            import math
            from math import isclose
            entries = report['progress_history']
            for entry in entries:
                epoch = entry['epoch']
                peak = spec['full_lr']
                start = spec['warmup_start_lr']
                floor = spec['warmup_min_lr']
                expected_lr = start + (peak-start)*(epoch-1)/4 if epoch <= 5 else floor + .5*(peak-floor)*(1+math.cos(math.pi*(epoch-5)/(spec['full_epochs']-5)))
                check(isclose(entry['learning_rate'], expected_lr, rel_tol=1e-6, abs_tol=1e-11), 'learning rate schedule mismatch')
                check(set(entry['val_per_class_recall']) == set(report['labels']), 'missing validation class recall')
            reference = float('inf')
            wait = 0
            stop_at = None
            first = spec['early_stopping_start_epoch']
            for epoch, value in enumerate(history['val_loss'], 1):
                if epoch < first:
                    reference = min(reference, value)
                elif value <= reference - spec['early_stopping_min_delta']:
                    reference, wait = value, 0
                else:
                    wait += 1
                    if wait >= spec['early_stopping_patience']:
                        stop_at = epoch
                        break
            check(stop_at is None or stop_at == detail['completed_epochs'], 'early stop trace mismatch')
            check(detail['completed_epochs'] == spec['full_epochs'] or stop_at == detail['completed_epochs'], 'stopped before patience')
        if checkpoint_metric == 'val_loss':
            check(abs(report['selected_val_loss'] - min(history['val_loss'])) < 1e-5,
                  'candidate loss does not match best checkpoint')
        check(hashlib.sha256((directory / 'full.best.weights.h5').read_bytes()).hexdigest() == detail['checkpoint_sha256'], 'stage checkpoint changed')
        check(hashlib.sha256((directory / 'best.weights.h5').read_bytes()).hexdigest() == report['best_weights_sha256'], 'best weights changed')
        check(source_hashes(directory / 'saved_model') == report['model_files_sha256'], 'SavedModel changed')
        expected_code = {'train_random_split.py', 'random_dataset.py', 'dataset.py', 'train.py'}
        if any(key in spec for key in ('checkpoint_metric','augmentation_profile','personal_sampling_factor')):
            expected_code.add('training_variants.py')
        if ema_decay:
            expected_code.add('training_advanced.py')
        if distilled:
            expected_code.add('training_advanced.py')
        check(set(report['code_sha256']) == expected_code, 'incomplete training source hashes')
        if spec['full_epochs'] == 200:
            check((root / 'source_snapshot').is_dir(), '200-epoch experiment requires frozen source snapshot')
        for name, sha in report['code_sha256'].items():
            code_root = root / 'source_snapshot' if (root / 'source_snapshot').exists() else Path(__file__).parent
            check(hashlib.sha256((code_root / name).read_bytes()).hexdigest() == sha, 'training code changed')
        rows.append(dict(run_id=run_id, epochs=detail['completed_epochs'], best_epoch=best_epoch,
                         trainable_parameters=report['trainability']['trainable_parameters'], bn_training=True,
                         full_class_weight=class_weight_mode,
                         optimizer=optimizer_name,
                         checkpoint_metric=checkpoint_metric,
                         checkpoint_best_epoch=int(checkpoint_entry['epoch']),
                         checkpoint_val_correct_count=checkpoint_entry.get('val_correct_count'),
                         augmentation_profile=augmentation_profile,
                         personal_sampling_factor=personal_factor,
                         ema_decay=ema_decay,
                         distillation=distilled,
                         backbone_changed_layers=54, selected_val_loss=report['selected_val_loss'],
                         validation_accuracy=report['validation']['accuracy'], validation_macro_f1=report['validation']['macro_f1']))
    checkpoint_metric = spec.get('checkpoint_metric') or 'val_loss'
    if checkpoint_metric == 'val_accuracy':
        expected_choice = min(rows, key=lambda row: (-int(row['checkpoint_val_correct_count']),
                              -row['validation_macro_f1'], row['selected_val_loss'], row['run_id']))['run_id']
    else:
        expected_choice = min(rows, key=lambda row: (row['selected_val_loss'], row['run_id']))['run_id']
    check(state['selected_run'] == chosen['selected_run'] == expected_choice,
          'selection does not follow recorded validation rule')
    final_paths = list(root.glob('*/final_test_report.json'))
    if deferred:
        check(not final_paths, 'deferred round scored test')
        check(not list(root.rglob('*.tflite')) and not list(root.rglob('c_backend')), 'unrequested export')
        return dict(status='passed', scope='host-only validation/artifact audit; no test scoring',
                    root=str(root), manifest_sha256=manifest_sha, runs=rows, selected_run=expected_choice,
                    test_evaluated=False, quantization_performed=False, installed=False)
    check(len(final_paths) == 1 and final_paths[0].parent.name == expected_choice, 'more than one final test')
    final = read(final_paths[0])
    report = read(final_paths[0].parent / 'training_report.json')
    check(final['manifest_sha256'] == chosen['manifest_sha256'] == manifest_sha, 'final manifest mismatch')
    check(final['model_files_sha256'] == chosen['saved_model_files_sha256'] == report['model_files_sha256'], 'scored model mismatch')
    check(chosen['weights_sha256'] == report['best_weights_sha256'], 'chosen weights mismatch')
    check(datetime.fromisoformat(chosen['frozen_at']) < datetime.fromisoformat(final['evaluated_at']), 'selection not recorded before test')
    truth, guesses = [], []
    for actual, counts in enumerate(final['metrics']['confusion']):
        for guess, count in enumerate(counts):
            truth.extend([actual] * count)
            guesses.extend([guess] * count)
    recomputed = classification_metrics(truth, guesses)
    check(recomputed == final['metrics'] == state['final_test'], 'final metrics inconsistent with confusion matrix')
    expected_test = sum(s['split'] == 'test' for s in read(manifest)['samples'])
    check(recomputed['sample_count'] == expected_test, 'wrong test sample count')
    check(not list(root.rglob('*.tflite')) and not list(root.rglob('c_backend')), 'unrequested export')
    check(not final['quantization_performed'] and not final['validated_for_business'], 'final scope violation')
    return dict(status='passed', scope='host-only full-training artifact / arithmetic audit; no additional scoring',
                root=str(root), manifest_sha256=manifest_sha, runs=rows, selected_run=expected_choice,
                test_metrics=recomputed, single_final_test=True, quantization_performed=False, installed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Audit output must be new; preserve evidence')
    result = verify(args.root.resolve(), args.manifest.resolve())
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=result['status'], selected_run=result['selected_run'], output=str(args.output)), ensure_ascii=False))


if __name__ == '__main__':
    main()
