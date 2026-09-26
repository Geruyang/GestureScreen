"""Offline official host-runtime and preprocessing checks for frozen v7."""
from pathlib import Path
import ctypes as C
import hashlib
import json
import re
import subprocess
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'Build/deployment-new-model-20260920'
GEN, HOST = WORK / 'generated', WORK / 'host'
GCC = ROOT.parent / 'STAI/4.0/Utilities/windows/mingw64/bin/gcc.exe'
LIBDIR = ROOT / 'Build/cubeai-migration/validate-work/inspector_gs_network/workspace/lib/static'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    HOST.mkdir(parents=True, exist_ok=True)
    conversion = json.loads((WORK / 'model/conversion.json').read_text())
    samples = json.loads((WORK / 'model/dataset-review.json').read_text())['samples']
    x = np.load(WORK / 'model/quantized_inputs.npy')
    reference = np.load(WORK / 'model/tflite_logits.npy')
    floats = np.load(WORK / 'model/float_logits.npy')
    y = np.load(WORK / 'model/labels.npy')
    if not (x.shape == (2420, 96, 96, 1) and reference.shape == (2420, 7)):
        raise RuntimeError('deploy_candidate_host.py:33 contract failed')
    generated_hashes = {p.name: sha(p) for p in GEN.glob('gs_network*') if p.is_file()}
    dll = HOST / 'gs_network.dll'
    subprocess.run([str(GCC), '-shared', '-O2', '-std=c99',
        '-I' + str(ROOT / 'Middlewares/ST/AI/Inc'), '-I' + str(GEN),
        str(GEN / 'gs_network.c'), str(GEN / 'gs_network_data.c'),
        '-L' + str(LIBDIR), '-lruntime', '-lst_cmsis_nn', '-lcmsis-nn', '-lm', '-o', str(dll)], check=True)
    header = (GEN / 'gs_network.h').read_text()
    arena_size = int(re.search(r'ACTIVATIONS_SIZE_BYTES\s+\((\d+)\)', header)[1])
    out_bytes = int(re.search(r'STAI_GS_NETWORK_OUT_SIZE_BYTES\s+\((\d+)\)', header)[1])
    if not (arena_size <= 65536 and out_bytes >= 7):
        raise RuntimeError('deploy_candidate_host.py:43 contract failed')
    lib = C.CDLL(str(dll))
    get_size = lib.stai_gs_network_get_context_size
    get_size.restype = C.c_uint32
    ctx = C.create_string_buffer(get_size())
    arena = C.create_string_buffer(arena_size)
    init = lib.stai_gs_network_init
    init.argtypes = [C.c_void_p]
    if not (init(ctx) == 0):
        raise RuntimeError('deploy_candidate_host.py:51 contract failed')

    def setter(name, address):
        fn = getattr(lib, 'stai_gs_network_set_' + name)
        fn.argtypes = [C.c_void_p, C.POINTER(C.c_void_p), C.c_uint32]
        if not (fn(ctx, (C.c_void_p * 1)(address), 1) == 0):
            raise RuntimeError('deploy_candidate_host.py:56 contract failed')

    setter('activations', C.addressof(arena))
    run = lib.stai_gs_network_run
    run.argtypes = [C.c_void_p, C.c_int]
    out = np.zeros(out_bytes, dtype=np.int8)
    actual = np.empty_like(reference)
    for i, row in enumerate(x):
        setter('inputs', row.ctypes.data)
        setter('outputs', out.ctypes.data)
        if not (run(ctx, 1) == 0):
            raise RuntimeError('deploy_candidate_host.py:66 contract failed')
        actual[i] = out[:7]
    np.save(HOST / 'cubeai_logits.npy', actual)
    metrics = {}
    for split in ('train', 'validation', 'test'):
        mask = np.array([r['split'] == split for r in samples])
        fp, tp, cp = floats[mask].argmax(1), reference[mask].argmax(1), actual[mask].argmax(1)
        metrics[split] = {'count': int(mask.sum()), 'float_correct': int((fp == y[mask]).sum()),
            'tflite_correct': int((tp == y[mask]).sum()), 'cubeai_correct': int((cp == y[mask]).sum()),
            'cubeai_tflite_top1_agreement': int((cp == tp).sum()),
            'cubeai_float_top1_agreement': int((cp == fp).sum()),
            'per_class_cubeai': {label: {'support': int((y[mask] == j).sum()),
                'correct': int(((y[mask] == j) & (cp == j)).sum())}
                for j, label in enumerate(conversion['labels'])}}
    comparison = {'dll_sha256': sha(dll), 'samples': len(x), 'activation_bytes': arena_size,
        'verifier_source_sha256': sha(Path(__file__)),
        'input_artifacts_sha256': {name: sha(WORK / 'model' / name) for name in
            ('conversion.json', 'dataset-review.json', 'quantized_inputs.npy',
             'tflite_logits.npy', 'float_logits.npy', 'labels.npy')},
        'host_libraries_sha256': {p.name: sha(p) for p in LIBDIR.glob('*.a')},
        'max_logit_delta': int(np.abs(actual.astype(np.int16) - reference.astype(np.int16)).max()),
        'metrics': metrics, 'generated_sha256': generated_hashes,
        'scope': 'Fixed-candidate offline conversion regression using official host runtime; not on-board or live gesture acceptance.'}
    write_json(HOST / 'comparison.json', comparison)
    print(json.dumps(comparison, indent=2), flush=True)
    # Independently execute the current production C preprocessor on original raw bytes.
    bridge = HOST / 'preprocess_bridge.c'
    bridge.write_text('#include "gs_preprocess.h"\n'
        'int check_frame(const unsigned char *raw, unsigned bytes, unsigned stride, int order, signed char *out) {'
        ' gs_rgb565_frame_t f={raw,bytes,320,240,stride,(gs_rgb565_byte_order_t)order};'
        ' return gs_preprocess_rgb565(&f,out,9216,0,0); }\n')
    pp_dll = HOST / 'preprocess.dll'
    subprocess.run([str(GCC), '-shared', '-O2', '-I' + str(ROOT / 'Modules/Vision/Inc'),
        str(bridge), str(ROOT / 'Modules/Vision/Src/gs_preprocess.c'), '-o', str(pp_dll)], check=True)
    pp = C.CDLL(str(pp_dll)).check_frame
    pp.argtypes = [C.c_void_p, C.c_uint, C.c_uint, C.c_int, C.c_void_p]
    expected_inputs = np.load(WORK / 'model/inputs.npy')
    output = np.zeros(9216, dtype=np.int8)
    dataset_root = Path(conversion['dataset_manifest']).parent
    rejects = 0
    for i, row in enumerate(samples):
        source = dataset_root / row['file']
        raw = source.read_bytes()
        if not (hashlib.sha256(raw).hexdigest() == row['sha256']):
            raise RuntimeError('deploy_candidate_host.py:104 contract failed')
        status = pp(raw, len(raw), row.get('stride_bytes', 640), int(row['byte_order'] == 'lsb_first'), output.ctypes.data)
        if not (status in (0, 4)):
            raise RuntimeError('deploy_candidate_host.py:106 contract failed')
        if not (np.array_equal(output, expected_inputs[i].reshape(-1))):
            raise RuntimeError('deploy_candidate_host.py:107 contract failed')
        rejects += int(status == 4)
    for name, expected in generated_hashes.items():
        if not (sha(GEN / name) == expected):
            raise RuntimeError('deploy_candidate_host.py:110 contract failed')
    result = {'samples': len(x), 'byte_exact': True, 'quality_rejects': rejects,
        'production_source_sha256': sha(ROOT / 'Modules/Vision/Src/gs_preprocess.c'),
        'scope': 'Original frozen-training reader versus current production C, all 2420 stored raw frames; no live capture.'}
    write_json(HOST / 'preprocessing.json', result)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
