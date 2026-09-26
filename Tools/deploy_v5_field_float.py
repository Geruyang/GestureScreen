"""Diagnose captured frames against the approved float model; never fit or tune."""
import os
os.environ['TF_CPP_MIN_LOG_LEVEL']='2'
os.environ['TF_USE_LEGACY_KERAS']='1'
from pathlib import Path
import argparse,ctypes as C,hashlib,json
import numpy as np
import tensorflow as tf

a=argparse.ArgumentParser();a.add_argument('captures',nargs='+',type=Path);args=a.parse_args()
root=Path(__file__).resolve().parents[1];package=root.parent/'Gesture_Model_Package'
weights_sha=hashlib.sha256((package/'model/best.weights.h5').read_bytes()).hexdigest()
if weights_sha!='bbdfcfd5fdae7788649a7208d0d465290a7c0bf54a4cc5790da0ac3620054e6c':
    raise ValueError('Approved weights identity mismatch')
pre=C.CDLL(str(root/'Build/deployment-v5/host/preprocess.dll'))
pre.check_frame.argtypes=[C.c_void_p,C.c_uint,C.c_uint,C.c_int,C.c_void_p]
model=tf.saved_model.load(str(package/'model/saved_model')).signatures['serving_default']
labels=['POINT_LEFT','POINT_RIGHT','FIST','PALM','V_SIGN','OTHER','EMPTY']
for capture in args.captures:
    rows=[]
    for path in sorted(capture.glob('frame-*.rgb565')):
        raw=path.read_bytes()
        if len(raw)!=153600:raise ValueError(str(path))
        buf=C.create_string_buffer(raw);tensor=np.zeros(9216,dtype=np.int8)
        quality=pre.check_frame(buf,len(raw),640,0,tensor.ctypes.data)
        x=(tensor.astype(np.int16)+128).astype(np.float32).reshape(1,96,96,1)
        logits=next(iter(model(tf.constant(x)).values())).numpy()[0].astype(np.float64)
        prob=np.exp(logits-logits.max());prob/=prob.sum()
        rows.append({'file':path.name,'raw_sha256':hashlib.sha256(raw).hexdigest(),
                     'preprocess_status':quality,'logits':logits.tolist(),
                     'scores':prob.tolist(),'top1':labels[int(prob.argmax())]})
    result={'scope':'approved float model diagnostic only; no fitting, no threshold changes',
            'approved_weights_sha256':weights_sha,'class_order':labels,'frames':rows}
    (capture/'offline-float-diagnostic.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'capture':str(capture),'predictions':[
        {'file':r['file'],'top1':r['top1'],'score':max(r['scores'])} for r in rows]},indent=2))
