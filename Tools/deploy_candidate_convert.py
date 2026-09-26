"""Freeze and convert the selected v7 model; no training or hardware access."""
import os
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')
os.environ.setdefault('TF_USE_LEGACY_KERAS', '1')
import hashlib
import json
from pathlib import Path
import shutil
import sys
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'Build/deployment-new-model-20260920'
OUT = WORK / 'model'
SOURCE = WORK / 'source-model'
REGISTRY = ROOT.parent / 'custom_dataset/model_releases/LATEST_TRAINING_CANDIDATE.json'
EXPECTED_WEIGHTS = '9f3550723de4b1b59de7cf25b5f78e667c11875a26a8d90e5412be9e89bb8c83'
EXPECTED_MANIFEST = '67fb130498be384d019e038b9b1a2874a4bc93c9072a7119995c62b474c137a0'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def copy_verified(source, destination, expected=None):
    actual = sha(source)
    if expected is not None and actual != expected:
        raise RuntimeError(f'Input SHA mismatch: {source}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha(destination) != actual:
            raise RuntimeError(f'Refusing to overwrite frozen input: {destination}')
    else:
        shutil.copy2(source, destination)
    if sha(destination) != actual:
        raise RuntimeError(f'Copy verification failed: {destination}')
    return actual


def main():
    import numpy as np
    registry = json.loads(REGISTRY.read_text(encoding='utf-8-sig'))
    if not (registry['winner_best_weights_sha256'] == EXPECTED_WEIGHTS):
        raise RuntimeError('deploy_candidate_convert.py:47 contract failed')
    if not (registry['dataset_manifest_sha256'] == EXPECTED_MANIFEST):
        raise RuntimeError('deploy_candidate_convert.py:48 contract failed')
    saved = Path(registry['winner_saved_model'])
    run = saved.parent
    manifest = Path(registry['dataset_manifest'])
    training = json.loads((run / 'training_report.json').read_text(encoding='utf-8-sig'))
    OUT.mkdir(parents=True, exist_ok=True)
    provenance = {}
    for name, expected in training['model_files_sha256'].items():
        provenance['saved_model/' + name] = copy_verified(saved / name, SOURCE / 'saved_model' / name, expected)
    if not (provenance['saved_model/saved_model.pb'] == registry['winner_saved_model_pb_sha256']):
        raise RuntimeError('deploy_candidate_convert.py:57 contract failed')
    for name, source, expected in [
        ('best.weights.h5', Path(registry['winner_best_weights']), EXPECTED_WEIGHTS),
        ('dataset_manifest.json', manifest, EXPECTED_MANIFEST),
        ('training_report.json', run / 'training_report.json', None),
        ('final_test_report.json', run / 'final_test_report.json', None),
        ('candidate_registry.json', REGISTRY, None),
        ('campaign_result.json', Path(registry['campaign_result']), registry['campaign_result_sha256']),
    ]:
        provenance[name] = copy_verified(source, SOURCE / name, expected)
    for name in ('random_dataset.py', 'dataset.py'):
        provenance['reader/' + name] = copy_verified(ROOT / 'Models' / name,
            SOURCE / 'reader' / name, training['code_sha256'][name])
    write_json(SOURCE / 'provenance.json', {'files_sha256': provenance,
        'original_dataset_root': str(manifest.parent), 'weights_sha256': EXPECTED_WEIGHTS,
        'scope': 'Immutable model and metadata copy; dataset images read in place and hash checked.'})
    write_json(SOURCE / 'training_parameters.json', training['config'])
    sys.path.insert(0, str(SOURCE / 'reader'))
    from random_dataset import read_training_dataset
    from dataset import LABELS
    if not (LABELS == training['labels']):
        raise RuntimeError('deploy_candidate_convert.py:77 contract failed')
    print('Checking all 2420 raw frames through the exact training reader...', flush=True)
    report, tensors = read_training_dataset(manifest)
    if not (report['manifest_sha256'] == EXPECTED_MANIFEST):
        raise RuntimeError('deploy_candidate_convert.py:80 contract failed')
    if not (len(tensors) == 2420):
        raise RuntimeError('deploy_candidate_convert.py:81 contract failed')
    # Reader ordering and tensor hashes are compared with the actual training evidence.
    if not ([(r['record_id'], r['input_sha256']) for r in report['samples']] == [
        (r['record_id'], r['input_sha256']) for r in training['dataset']['samples']]):
        raise RuntimeError('deploy_candidate_convert.py:83 contract failed')
    x = np.frombuffer(b''.join(tensors), dtype=np.int8).reshape(-1, 96, 96, 1)
    y = np.array([LABELS.index(r['label']) for r in report['samples']])
    splits = np.array([r['split'] for r in report['samples']])
    if not ([int((splits == s).sum()) for s in ('train', 'validation', 'test')] == [1694, 242, 484]):
        raise RuntimeError('deploy_candidate_convert.py:88 contract failed')
    np.save(OUT / 'inputs.npy', x)
    np.save(OUT / 'labels.npy', y)
    write_json(OUT / 'dataset-review.json', report)
    import tensorflow as tf
    print('TensorFlow', tf.__version__, 'PTQ uses only 1694 train images', flush=True)
    float_x = (x.astype(np.int16) + 128).astype(np.float32)
    model = tf.saved_model.load(str(SOURCE / 'saved_model'))
    signature = model.signatures['serving_default']
    print(signature.structured_input_signature, signature.structured_outputs, flush=True)
    float_logits = np.concatenate([next(iter(signature(tf.constant(float_x[i:i+32])).values())).numpy()
                                   for i in range(0, len(x), 32)])
    if not (float_logits.shape == (2420, 7)):
        raise RuntimeError('deploy_candidate_convert.py:100 contract failed')
    if not (int((float_logits[splits == 'test'].argmax(1) == y[splits == 'test']).sum()) == 415):
        raise RuntimeError('deploy_candidate_convert.py:101 contract failed')
    np.save(OUT / 'float_logits.npy', float_logits)
    converter = tf.lite.TFLiteConverter.from_saved_model(str(SOURCE / 'saved_model'))
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = lambda: ([float_x[i:i+1]] for i in np.flatnonzero(splits == 'train'))
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    converted = converter.convert()
    path = OUT / 'gesture_v7_int8.tflite'
    if path.exists() and path.read_bytes() != converted:
        raise RuntimeError('Refusing to replace a different frozen quantized candidate')
    path.write_bytes(converted)
    print('Frozen TFLite', sha(path), len(converted), flush=True)
    interpreter = tf.lite.Interpreter(model_path=str(path), num_threads=1,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    interpreter.allocate_tensors()
    inp = interpreter.get_input_details()[0]
    out = interpreter.get_output_details()[0]
    si, zi = inp['quantization']
    so, zo = out['quantization']
    # The existing firmware contract must not be silently changed.
    if not (inp['shape'].tolist() == [1, 96, 96, 1] and (si, zi) == (1.0, -128)):
        raise RuntimeError('deploy_candidate_convert.py:123 contract failed')
    if not (out['shape'].tolist() == [1, 7]):
        raise RuntimeError('deploy_candidate_convert.py:124 contract failed')
    quantized = np.clip(np.rint(float_x / si + zi), -128, 127).astype(np.int8)
    if not (np.array_equal(x, quantized)):
        raise RuntimeError('deploy_candidate_convert.py:126 contract failed')
    np.save(OUT / 'quantized_inputs.npy', quantized)
    actual = np.empty((len(x), 7), dtype=np.int8)
    for i in range(len(x)):
        interpreter.set_tensor(inp['index'], quantized[i:i+1])
        interpreter.invoke()
        actual[i] = interpreter.get_tensor(out['index'])[0]
    np.save(OUT / 'tflite_logits.npy', actual)
    metrics = {}
    for split in ('train', 'validation', 'test'):
        mask = splits == split
        fp, qp = float_logits[mask].argmax(1), actual[mask].argmax(1)
        metrics[split] = {'count': int(mask.sum()), 'float_correct': int((fp == y[mask]).sum()),
            'int8_correct': int((qp == y[mask]).sum()), 'top1_agreement': int((fp == qp).sum())}
    record = {'saved_model_pb_sha256': provenance['saved_model/saved_model.pb'],
        'source_provenance_sha256': sha(SOURCE / 'provenance.json'),
        'converter_source_sha256': sha(Path(__file__)), 'model_sha256': sha(path), 'weights_sha256': EXPECTED_WEIGHTS,
        'dataset_manifest': str(manifest), 'dataset_manifest_sha256': EXPECTED_MANIFEST,
        'input_shape': inp['shape'].tolist(), 'input_scale': si, 'input_zero': zi,
        'output_shape': out['shape'].tolist(), 'output_scale': so, 'output_zero': zo,
        'labels': LABELS, 'calibration': 'All 1694 train images only; no validation/test calibration',
        'metrics': metrics, 'tensorflow_version': tf.__version__,
        'scope': 'One fixed PTQ candidate; offline conversion regression only, no fitting, tuning, live gesture or board acceptance.'}
    write_json(OUT / 'conversion.json', record)
    print(json.dumps(record, indent=2), flush=True)


if __name__ == '__main__':
    main()
