"""Install hash-bound generated v12 model with retained cancellation hooks."""
from pathlib import Path
import hashlib
import json
import re
import shutil

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'Build/deployment-v12-20260922'
OUTPUTS=[18432,18432,36864,9216,18432,18432,18432,4608,9216,9216,9216,2304,4608,4608,4608,4608,4608,4608,4608,4608,4608,4608,4608,1152,2304,2304,2304,256,6]
NAMES=[f'conv2d_{i}' for i in range(2,29)]+['pool_29','gemm_30']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    generated=WORK/'generated';destination=ROOT/'Middlewares/ST/AI/Generated'
    comparison=json.loads((WORK/'host/comparison.json').read_text())
    conversion=json.loads((WORK/'model/conversion.json').read_text())
    assert conversion['weight_sha256']=='72db45f37036530652ef07e19ad20e6ce94552027d0fc81a9987c074f6c5c4be'
    assert conversion['model_sha256']==sha(WORK/'model/gesture_v12_int8.tflite')
    assert comparison['metrics']['validation']['cubeai_correct']==294
    assert comparison['activation_bytes']==58624
    for name,digest in comparison['generated_sha256'].items():assert sha(generated/name)==digest,name
    text=(generated/'gs_network.c').read_text()
    observed=re.findall(r'/\* LITE_KERNEL_SECTION END (\w+) \*/',text)
    wanted=['eltwise_0','eltwise_1']
    for i,name in enumerate(NAMES):
        if 1<=i<=25 and i%2==1:wanted.append(name+'_pad_before')
        wanted.append(name)
    assert observed==wanted,(observed,wanted)
    text=text.replace('#include "gs_network.h"','#include "gs_network.h"\n#include <stdbool.h>\nextern bool gs_cubeai_layer_done(size_t layer, uint32_t outputs);',1)
    for index,(name,size) in enumerate(zip(NAMES,OUTPUTS)):
        marker=f'  /* LITE_KERNEL_SECTION END {name} */'
        assert text.count(marker)==1
        text=text.replace(marker,marker+f'\n  if (!gs_cubeai_layer_done({index}U, {size}U)) {{ return STAI_ERROR_GENERIC; }}')
    assert text.count('gs_cubeai_layer_done(')==30
    backup=WORK/'before-install-generated';backup.mkdir(exist_ok=True)
    files=['gs_network.c','gs_network.h','gs_network_data.c','gs_network_data.h','gs_network_details.h','LICENSE.txt']
    destination.mkdir(exist_ok=True)
    for name in files:
        if (destination/name).exists() and not (backup/name).exists():shutil.copy2(destination/name,backup/name)
        if name=='gs_network.c':(destination/name).write_text(text,encoding='utf-8')
        else:shutil.copy2(generated/name,destination/name)
    record=dict(hook_names=NAMES,hook_outputs=OUTPUTS,input_normalization='Two generated eltwise kernels precede the first conv callback; their work remains inside inference budget.',
        generated_sha256={name:sha(destination/name) for name in files},backend_sha256=sha(ROOT/'Modules/StaticRecognition/Src/gs_cubeai_backend.c'),
        conversion_sha256=sha(WORK/'model/conversion.json'),model_sha256=conversion['model_sha256'])
    (WORK/'install.json').write_text(json.dumps(record,indent=2),encoding='utf-8');print(json.dumps(record,indent=2))
if __name__=='__main__':main()
