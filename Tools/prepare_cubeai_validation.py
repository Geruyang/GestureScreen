"""Prepare existing fixed vectors and TFLite-reference outputs; no training."""
from pathlib import Path
import hashlib
import json
import os

os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')
import numpy as np
import tensorflow as tf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'Build/cubeai-migration/validation-inputs'
MODEL = ROOT.parent / 'artifacts/model_audit/arm_openmv/model.tflite'
EXPECTED_MODEL = 'd8a8ab8d3b87d80a7e027ccd1f6933b3ba7ac4a3eb1d3c038f8a1129cf788566'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    assert sha(MODEL) == EXPECTED_MODEL, 'Original model identity changed'
    fixtures = ROOT / 'Tests/fixtures'
    packed = fixtures / 'int8_original_50.bin'
    assert packed.stat().st_size == 50 * 9216
    inputs = [x.copy() for x in np.frombuffer(packed.read_bytes(), dtype=np.int8).reshape(50, 96, 96, 1)]
    sources = [{'kind': 'original_synthetic', 'path': str(packed), 'sha256': sha(packed), 'index': i} for i in range(50)]
    for frame in (486, 490, 494):
        p = fixtures / f'static_model_input_{frame}.bin'
        assert p.stat().st_size == 9216
        inputs.append(np.frombuffer(p.read_bytes(), dtype=np.int8).reshape(96, 96, 1))
        sources.append({'kind': 'saved_real', 'path': str(p), 'sha256': sha(p), 'frame': frame})
    manifest = ROOT / 'Build/agent-team/round12c/release/validation-baseline/saved-input-manifest.json'
    saved = json.loads(manifest.read_text(encoding='utf-8-sig'))
    assert len(saved) == 10
    for row in saved:
        p = Path(row['input_path'])
        assert p.stat().st_size == 9216 and sha(p) == row['input_sha256']
        inputs.append(np.frombuffer(p.read_bytes(), dtype=np.int8).reshape(96, 96, 1))
        sources.append({'kind': 'saved_real', 'path': str(p), 'sha256': sha(p), 'frame': row['frame_id']})
    interpreter = tf.lite.Interpreter(model_path=str(MODEL), experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    interpreter.allocate_tensors()
    inp, = interpreter.get_input_details()
    out, = interpreter.get_output_details()
    assert inp['shape'].tolist() == [1, 96, 96, 1] and inp['dtype'] == np.int8
    assert tuple(inp['quantization']) == (1.0, -128)
    assert out['dtype'] == np.int8 and int(np.prod(out['shape'])) == 5
    outputs = []
    for x in inputs:
        interpreter.set_tensor(inp['index'], x[np.newaxis])
        interpreter.invoke()
        outputs.append(interpreter.get_tensor(out['index']).reshape(5))
    OUT.mkdir(parents=True, exist_ok=True)
    np.save(OUT / 'inputs.npy', np.stack(inputs))
    np.save(OUT / 'reference_logits.npy', np.stack(outputs))
    report = {'model': str(MODEL), 'model_sha256': sha(MODEL), 'reference': 'TFLite BUILTIN_REF',
              'tensorflow_version': tf.__version__, 'samples': len(inputs), 'sources': sources,
              'input_shape': inp['shape'].tolist(), 'input_quantization': list(inp['quantization']),
              'output_shape': out['shape'].tolist(), 'output_quantization': list(out['quantization']),
              'inputs_sha256': sha(OUT / 'inputs.npy'), 'outputs_sha256': sha(OUT / 'reference_logits.npy'),
              'scope': 'Fixed regression vectors, not training or accuracy validation; CubeAI not executed by this script'}
    (OUT / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'sources'}, indent=2))

if __name__ == '__main__':
    main()
