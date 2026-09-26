"""Replay labeled-intent onsite sequences, keeping them excluded from training."""
from pathlib import Path
import argparse
import collections
import ctypes as C
import json
import hashlib
import struct
import numpy as np
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'Build/deployment-v12-20260922'
LABELS=['POINT_LEFT','POINT_RIGHT','FIST','PALM','V_SIGN','UNKNOWN']
def main():
    parser=argparse.ArgumentParser();parser.add_argument('capture',type=Path);parser.add_argument('--intended',choices=LABELS,required=True)
    args=parser.parse_args();meta=json.loads((WORK/'model/conversion.json').read_text())
    pp=C.CDLL(str(WORK/'host/preprocess.dll')).check_frame
    pp.argtypes=[C.c_void_p,C.c_uint,C.c_uint,C.c_int,C.c_void_p]
    lib=C.CDLL(str(WORK/'host/gs_network.dll'));lib.stai_gs_network_get_context_size.restype=C.c_uint32
    ctx=C.create_string_buffer(lib.stai_gs_network_get_context_size());arena=C.create_string_buffer(58624)
    lib.stai_gs_network_init.argtypes=[C.c_void_p];assert lib.stai_gs_network_init(ctx)==0
    def setter(name,address):
        fn=getattr(lib,'stai_gs_network_set_'+name);fn.argtypes=[C.c_void_p,C.POINTER(C.c_void_p),C.c_uint32]
        assert fn(ctx,(C.c_void_p*1)(address),1)==0
    setter('activations',C.addressof(arena));lib.stai_gs_network_run.argtypes=[C.c_void_p,C.c_int]
    x=np.zeros(27648,dtype=np.int8);out=np.zeros(12,dtype=np.int8)
    setter('inputs',x.ctypes.data);setter('outputs',out.ctypes.data)
    rows=[]
    for path in sorted((args.capture/'usb').glob('raw-*')):
        raw=path.read_bytes();assert len(raw)==153600
        status=pp(raw,len(raw),640,0,x.ctypes.data);assert status in (0,4)
        assert lib.stai_gs_network_run(ctx,1)==0
        logits=out[:6].astype(float)*meta['output_scale'];scores=np.exp(logits-logits.max());scores/=scores.sum()
        top=int(scores.argmax());best=float(scores[top]);margin=best-float(np.sort(scores)[-2])
        rows.append(dict(file=path.name,sha256=hashlib.sha256(raw).hexdigest(),top1=LABELS[top],confidence=best,margin=margin,
            scores=scores.tolist(),logits=out[:6].tolist(),target_confirmed=top<5 and best>=.9 and margin>=.2,
            neutral_clear=top==5 and best>=.95,quality_status=status))
    report=dict(intended=args.intended,frames=len(rows),top1_counts=dict(collections.Counter(r['top1'] for r in rows)),
        intended_top1=sum(r['top1']==args.intended for r in rows),target_confirmed=sum(r['target_confirmed'] for r in rows),
        neutral_clear=sum(r['neutral_clear'] for r in rows),rows=rows,
        scope='Fixed v12 host replay of USB images; intended poses need visual review; USB and SWD not assumed same frame.')
    trace=args.capture/'trace';report['endpoints']={}
    for phase in ('before','after'):
        p=trace/f'diagnostics-{phase}-g_gs_static_diag.bin'
        if not p.exists():continue
        raw=p.read_bytes();assert len(raw)==364
        v=struct.unpack('<7I6fI',raw[:56]);app=struct.unpack('<43I',(trace/f'diagnostics-{phase}-g_gs_diag.bin').read_bytes())
        report['endpoints'][phase]=dict(static_status=v[0],class_index=v[1],frame_id=v[2],capture_ms=v[3],inference_ms=v[4],
            confidence_permille=v[5],margin_permille=v[6],scores=list(v[7:13]),scores_valid=v[13],gui_generation=app[29],
            gui_mode=app[30],gui_page=app[31],gui_selected=app[32],gui_playing=app[33],gesture_state=app[34],healthy=app[41],fatal=app[42])
    if (trace/'decoded.json').exists():
        decoded=json.loads((trace/'decoded.json').read_text());initial=decoded['after_first_snapshot']['initial_published_sequence']
        fresh={r['sequence']:r for s in decoded['samples'] for r in s['records'] if 0<((r['sequence']-initial)&0xffffffff)<0x80000000}
        report['trace_window']=decoded['after_first_snapshot']
        report['state_transitions']=dict(collections.Counter(f"{r['gesture_state_before']}->{r['gesture_state_after']}" for r in fresh.values()))
        report['commands']=[r for r in fresh.values() if 'command' in r['outcomes']]
    (args.capture/'review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2))
if __name__=='__main__':main()
