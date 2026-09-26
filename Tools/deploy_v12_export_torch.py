"""Freeze selected v12 weights and train/validation inference inputs, no training."""
from pathlib import Path
import hashlib
import json
import sys
import shutil
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
GS = ROOT / 'GestureScreen'
WORK = GS / 'Build/deployment-v12-20260922'
CAMPAIGN = GS / 'Build/models/custom-2671/v12-improve-v1'
SOURCE = CAMPAIGN / 'source'
sys.path[:0] = [str(SOURCE), str(ROOT / 'custom_dataset/tools')]
from v12_six_class_model import SixClassMobileNetV1, evaluate_six
from v12_camera_data import read_rgb_dataset, LABELS
from train_student_rgb565_arch_ablation_torch_v9 import resize_view, deterministic, cuda_device

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    work = WORK / 'model'; work.mkdir(parents=True, exist_ok=True)
    selected = json.loads((CAMPAIGN / 'SELECTED_CANDIDATE.json').read_text())
    checkpoint = Path(selected['checkpoint'])
    assert sha(checkpoint) == selected['weights_sha256'] == '72db45f37036530652ef07e19ad20e6ce94552027d0fc81a9987c074f6c5c4be'
    manifest = ROOT / 'custom_dataset/v12_six_class_unknown_2671/dataset_manifest.json'
    assert sha(manifest) == selected['manifest_sha256']
    shutil.copy2(checkpoint, work / 'best.pt')
    shutil.copy2(CAMPAIGN / 'SELECTED_CANDIDATE.json', work / 'source-selection.json')
    state = torch.load(checkpoint, map_location='cpu', weights_only=True)
    np.savez(work / 'torch-weights.npz', **{k:v.numpy() for k,v in state.items()})
    deterministic(20260919); device = cuda_device()
    model = SixClassMobileNetV1(.25, 96, False).to(device)
    model.load_state_dict(state); model.eval()
    rows, frames = read_rgb_dataset(manifest, ('train', 'validation'))
    inputs = np.stack([resize_view(frame, 96) for frame in frames])
    labels = np.array([LABELS.index(r['label']) for r in rows], dtype=np.int64)
    logits, _, _ = evaluate_six(model, inputs, labels, 16, device)
    mask = np.array([r['split']=='validation' for r in rows])
    original = np.load(checkpoint.parent / 'selected_validation_logits.npy')
    assert np.array_equal(logits[mask], original), float(np.abs(logits[mask]-original).max())
    assert int((logits[mask].argmax(1)==labels[mask]).sum()) == 292
    np.save(work / 'inputs-u8.npy', inputs)
    np.save(work / 'labels.npy', labels)
    np.save(work / 'torch-logits.npy', logits)
    record = dict(labels=LABELS, samples=rows, weight_sha256=sha(checkpoint), manifest=str(manifest),
                  manifest_sha256=sha(manifest), input_shape=list(inputs.shape), test_opened=False,
                  calibration_split='train', validation_correct=292, validation_reload_exact=True,
                  torch_version=torch.__version__, device=str(device), source_hashes={p.name:sha(p) for p in SOURCE.glob('*.py')})
    (work / 'export.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in record.items() if k not in ('samples','source_hashes')}, indent=2), flush=True)

if __name__ == '__main__': main()
