"""Exact tensor transfer to Keras followed by fixed train-only int8 PTQ."""
import os
os.environ['TF_USE_LEGACY_KERAS'] = '1'
from pathlib import Path
import hashlib
import json
import numpy as np
import tensorflow as tf

WORK = Path(__file__).resolve().parents[1] / 'Build/deployment-v12-20260922/model'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    weights = np.load(WORK / 'torch-weights.npz')
    export = json.loads((WORK / 'export.json').read_text())
    data = np.load(WORK / 'inputs-u8.npy'); y = np.load(WORK / 'labels.npy')
    train = np.array([r['split']=='train' for r in export['samples']])
    val = ~train
    inputs = tf.keras.Input(shape=(96,96,3), batch_size=1, dtype=tf.float32, name='rgb96')
    x = tf.keras.layers.Rescaling(1/127.5, -1)(inputs)
    def block(x, name, stride, depthwise=False):
        w = weights[name+'.conv.weight']
        if depthwise:
            layer = tf.keras.layers.DepthwiseConv2D(w.shape[-1], strides=stride, padding='same', use_bias=False)
            x = layer(x); layer.set_weights([w.transpose(2,3,0,1)])
        else:
            layer = tf.keras.layers.Conv2D(w.shape[0], w.shape[-1], strides=stride, padding='same', use_bias=False)
            x = layer(x); layer.set_weights([w.transpose(2,3,1,0)])
        bn = tf.keras.layers.BatchNormalization(epsilon=1e-3, trainable=False)
        x = bn(x, training=False)
        bn.set_weights([weights[name+'.bn.'+key] for key in ('weight','bias','running_mean','running_var')])
        return tf.keras.layers.ReLU(max_value=6)(x)
    x = block(x, 'stem', 2)
    for i,stride in enumerate((1,2,1,2,1,2,1,1,1,1,1,2,1)):
        x = block(x, f'blocks.{i}.depthwise', stride, True)
        x = block(x, f'blocks.{i}.pointwise', 1)
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    dense = tf.keras.layers.Dense(6); outputs = dense(x)
    dense.set_weights([weights['classifier.weight'].T, weights['classifier.bias']])
    model = tf.keras.Model(inputs, outputs)
    assert model.count_params() == sum(weights[k].size for k in weights if not k.endswith('num_batches_tracked'))
    reference = np.load(WORK / 'torch-logits.npy')
    floating = np.concatenate([model(data[i:i+16].astype(np.float32), training=False).numpy() for i in range(0,len(data),16)])
    error = float(np.abs(floating-reference).max())
    assert error < 0.001, error
    assert np.array_equal(floating.argmax(1), reference.argmax(1)), 'Float conversion changed top1'
    np.save(WORK / 'keras-logits.npy', floating)
    model.save(str(WORK / 'saved_model'), include_optimizer=False)
    converter = tf.lite.TFLiteConverter.from_saved_model(str(WORK / 'saved_model'))
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = lambda: ([data[i:i+1].astype(np.float32)] for i in np.flatnonzero(train))
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8; converter.inference_output_type = tf.int8
    model_path = WORK / 'gesture_v12_int8.tflite'
    model_path.write_bytes(converter.convert())
    interpreter = tf.lite.Interpreter(model_path=str(model_path),num_threads=1,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    interpreter.allocate_tensors(); inp=interpreter.get_input_details()[0]; out=interpreter.get_output_details()[0]
    si,zi=inp['quantization']; so,zo=out['quantization']
    assert inp['shape'].tolist()==[1,96,96,3] and (si,zi)==(1.0,-128),(inp['shape'],si,zi)
    assert out['shape'].tolist()==[1,6]
    quantized = (data.astype(np.int16)-128).astype(np.int8)
    np.save(WORK / 'quantized-inputs.npy',quantized)
    actual = np.empty((len(data),6),dtype=np.int8)
    for i in range(len(data)):
        interpreter.set_tensor(inp['index'],quantized[i:i+1]); interpreter.invoke()
        actual[i]=interpreter.get_tensor(out['index'])[0]
    np.save(WORK / 'tflite-logits.npy',actual)
    record=dict(weight_sha256=export['weight_sha256'],model_sha256=sha(model_path),model_bytes=model_path.stat().st_size,
        labels=export['labels'],keras_torch_max_abs=error,float_top1_agreement=len(data),samples=len(data),
        calibration_train_count=int(train.sum()),test_opened=False,input_scale=si,input_zero_point=zi,
        output_scale=so,output_zero_point=zo,validation_count=int(val.sum()),
        float_validation_correct=int((floating[val].argmax(1)==y[val]).sum()),
        tflite_validation_correct=int((actual[val].argmax(1)==y[val]).sum()),
        validation_top1_agreement=int((actual[val].argmax(1)==floating[val].argmax(1)).sum()))
    (WORK / 'conversion.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record,indent=2),flush=True)

if __name__ == '__main__': main()
