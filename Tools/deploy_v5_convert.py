"""Convert the immutable user-approved student; train-only PTQ, no fitting/tuning."""
import os
os.environ['TF_CPP_MIN_LOG_LEVEL']='2'
os.environ['TF_USE_LEGACY_KERAS']='1'
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import hashlib,json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT.parent/'Gesture_Model_Package'
OUT=ROOT/'Build/deployment-v5/model'
OUT.mkdir(parents=True,exist_ok=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(PACKAGE/'model/best.weights.h5')=='bbdfcfd5fdae7788649a7208d0d465290a7c0bf54a4cc5790da0ac3620054e6c'
assert sha(PACKAGE/'dataset/dataset_manifest.json')=='9a6901c2e2063deaf0c37cf1fc3a7c96513448122ddbe33cbd0d9cc64161e215'
sys.path.insert(0,str(PACKAGE/'model/source_snapshot'))
from random_dataset import read_training_dataset
from dataset import LABELS
print('Reading and verifying all package samples through archived preprocessing...',flush=True)
report,tensors=read_training_dataset(PACKAGE/'dataset/dataset_manifest.json')
x=np.frombuffer(b''.join(tensors),dtype=np.int8).reshape(-1,96,96,1)
np.save(OUT/'inputs.npy',x)
y=np.array([LABELS.index(r['label']) for r in report['samples']])
splits=np.array([r['split'] for r in report['samples']])
np.save(OUT/'labels.npy',y)
(OUT/'dataset-review.json').write_text(json.dumps(report,indent=2))
import tensorflow as tf
print('TensorFlow',tf.__version__,'train-only calibration',int((splits=='train').sum()),flush=True)
float_x=(x.astype(np.int16)+128).astype(np.float32)
model=tf.saved_model.load(str(PACKAGE/'model/saved_model'))
signature=model.signatures['serving_default']
print(signature.structured_input_signature,signature.structured_outputs,flush=True)
float_logits=[]
for start in range(0,len(x),32):
    float_logits.extend(next(iter(signature(tf.constant(float_x[start:start+32])).values())).numpy())
float_logits=np.array(float_logits)
np.save(OUT/'float_logits.npy',float_logits)
converter=tf.lite.TFLiteConverter.from_saved_model(str(PACKAGE/'model/saved_model'))
converter.optimizations=[tf.lite.Optimize.DEFAULT]
def representative():
    for i in np.flatnonzero(splits=='train'):
        yield [float_x[i:i+1]]
converter.representative_dataset=representative
converter.target_spec.supported_ops=[tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter.inference_input_type=tf.int8
converter.inference_output_type=tf.int8
converted=converter.convert()
path=OUT/'gesture_v5_int8.tflite'
if path.exists():assert path.read_bytes()==converted,'Refusing to replace different candidate'
else:path.write_bytes(converted)
print('FROZEN',sha(path),len(converted),flush=True)
interpreter=tf.lite.Interpreter(model_path=str(path),num_threads=1,
    experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
interpreter.allocate_tensors()
inp=interpreter.get_input_details()[0];out=interpreter.get_output_details()[0]
si,zi=inp['quantization'];so,zo=out['quantization']
quantized=np.clip(np.rint(float_x/si+zi),-128,127).astype(np.int8)
np.save(OUT/'quantized_inputs.npy',quantized)
actual=np.empty((len(x),7),dtype=np.int8)
for i in range(len(x)):
    interpreter.set_tensor(inp['index'],quantized[i:i+1]);interpreter.invoke()
    actual[i]=interpreter.get_tensor(out['index'])[0]
np.save(OUT/'tflite_logits.npy',actual)
metrics={}
for split in ['train','validation','test']:
    mask=splits==split;f=float_logits[mask].argmax(1);q=actual[mask].argmax(1)
    metrics[split]={'count':int(mask.sum()),'float_correct':int((f==y[mask]).sum()),
                    'int8_correct':int((q==y[mask]).sum()),'top1_agreement':int((f==q).sum())}
record={'model_sha256':sha(path),'weights_sha256':sha(PACKAGE/'model/best.weights.h5'),
        'input_shape':inp['shape'].tolist(),'input_scale':si,'input_zero':zi,
        'output_shape':out['shape'].tolist(),'output_scale':so,'output_zero':zo,
        'labels':LABELS,'calibration':'all 1400 train samples, immutable preprocessing; no validation/test calibration',
        'metrics':metrics,'scope':'single frozen PTQ conversion comparison, no retraining or parameter search; historical non-independent test'}
(OUT/'conversion.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record,indent=2),flush=True)
