"""Install v5 ST-generated network with bounded original-layer progress hooks."""
from pathlib import Path
import hashlib,json,shutil,re
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'Build/deployment-v5'
SRC=WORK/'generated';DST=ROOT/'Middlewares/ST/AI';GEN=DST/'Generated'
meta=json.loads((WORK/'model/conversion.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(WORK/'model/gesture_v5_int8.tflite')==meta['model_sha256']
assert meta['input_scale']==1 and meta['input_zero']==-128 and meta['output_shape']==[1,7]
code=(SRC/'gs_network.c').read_text()
code=code.replace('#include "gs_network.h"','#include "gs_network.h"\n#include "gs_cubeai_backend.h"')
sizes=[18432,18432,36864,9216,18432,18432,18432,4608,9216,9216,9216,2304,
       4608,4608,4608,4608,4608,4608,4608,4608,4608,4608,4608,1152,2304,2304,2304,256,7]
assert len(sizes)==29
for i,count in enumerate(sizes):
    name=f'pool_{i}' if i==27 else f'conv2d_{i}'
    marker=f'  /* LITE_KERNEL_SECTION END {name} */'
    assert code.count(marker)==1,name
    code=code.replace(marker,marker+f'\n  if (!gs_cubeai_layer_done({i}U, {count}U)) {{ return STAI_ERROR_GENERIC; }}')
for p in SRC.glob('*.h'):shutil.copy2(p,GEN/p.name)
shutil.copy2(SRC/'gs_network_data.c',GEN/'gs_network_data.c')
(GEN/'gs_network.c').write_text(code)
m={'tool':'ST Edge AI Core 4.0.1-20581 / STM32CubeAI 12.0.1-RC2',
   'model_sha256':meta['model_sha256'],'approved_weights_sha256':meta['weights_sha256'],
   'instrumentation':'29 layer-end hooks; unchanged kernels/weights',
   'generated_source_sha256':{p.name:sha(p) for p in SRC.glob('*') if p.suffix in ('.c','.h')},
   'files':{p.relative_to(DST).as_posix():sha(p) for p in DST.rglob('*') if p.is_file() and p.name!='manifest.json'}}
(DST/'manifest.json').write_text(json.dumps(m,indent=2))
print('Installed approved v5 seven-class generated model.')
