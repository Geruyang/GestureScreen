"""Install pinned ST output and runtime; add only layer-boundary cooperative hooks."""
from pathlib import Path
import hashlib
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'Build/cubeai-migration/generated'
SDK = ROOT.parent / 'STAI/4.0'
DST = ROOT / 'Middlewares/ST/AI'
GEN = DST / 'Generated'
MODEL = ROOT.parent / 'artifacts/model_audit/arm_openmv/model.tflite'
assert hashlib.sha256(MODEL.read_bytes()).hexdigest() == 'd8a8ab8d3b87d80a7e027ccd1f6933b3ba7ac4a3eb1d3c038f8a1129cf788566'
GEN.mkdir(parents=True, exist_ok=True)
for p in SRC.glob('*.h'):
    shutil.copy2(p, GEN / p.name)
shutil.copy2(SRC / 'gs_network_data.c', GEN / 'gs_network_data.c')
code = (SRC / 'gs_network.c').read_text()
code = code.replace('#include "gs_network.h"', '#include "gs_network.h"\n#include "gs_cubeai_backend.h"')
# Only complete original layers, not ST padding helpers, report progress.
layers = re.findall(r'^    \{(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),',
                    (ROOT / 'Modules/StaticRecognition/Src/gs_static_weights.c').read_text(), re.M)
assert len(layers) == 29
for i, dims in enumerate(layers):
    name = f'pool_{i}' if i == 27 else f'conv2d_{i}'
    marker = f'  /* LITE_KERNEL_SECTION END {name} */'
    assert code.count(marker) == 1, name
    count = int(dims[3]) * int(dims[4]) * int(dims[5])
    code = code.replace(marker, marker + f'\n  if (!gs_cubeai_layer_done({i}U, {count}U)) {{ return STAI_ERROR_GENERIC; }}')
(GEN / 'gs_network.c').write_text(code)
shutil.copytree(SDK / 'Middlewares/ST/AI/Inc', DST / 'Inc', dirs_exist_ok=True)
(DST / 'Lib').mkdir(exist_ok=True)
lib = SDK / 'Middlewares/ST/AI/Lib/MDK/ARMCortexM4/NetworkRuntime1201_CM4_Keil.lib'
shutil.copy2(lib, DST / 'Lib' / lib.name)
shutil.copy2(SDK / 'Middlewares/ST/AI/LICENSE.txt', DST / 'LICENSE.txt')
shutil.copy2(SDK / 'Package_license.html', DST / 'Package_license.html')
manifest = {'tool': 'ST Edge AI Core 4.0.1-20581 / STM32CubeAI 12.0.1-RC2',
            'model_sha256': hashlib.sha256(MODEL.read_bytes()).hexdigest(),
            'generated_source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in SRC.glob('*') if p.suffix in ('.c', '.h')},
            'instrumentation': '29 original-layer completion hooks; kernels and weights unchanged',
            'files': {p.relative_to(DST).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in DST.rglob('*') if p.is_file() and p.name != 'manifest.json'}}
(DST / 'manifest.json').write_text(json.dumps(manifest, indent=2))
print('Installed generated network, CM4 runtime, licenses and 29 cooperative hooks.')
