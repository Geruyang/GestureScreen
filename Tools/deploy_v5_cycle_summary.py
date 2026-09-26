"""Summarize matched terminal DWT accounting from 368-byte diagnostic samples."""
from pathlib import Path
import argparse,json,struct
ROOT=Path(__file__).resolve().parents[1]
a=argparse.ArgumentParser();a.add_argument('session',type=Path);a.add_argument('--clock-hz',type=int,default=168000000);args=a.parse_args()
rows=[]
for file in sorted(args.session.glob('sample-*-static.bin')):
 raw=file.read_bytes();assert len(raw)==368,'Requires seven-class 368B layout'
 v=struct.unpack('<92I',raw)
 if v[59]!=1 or v[2]!=v[90]:continue
 rows.append({'file':str(file),'frame_id':v[2],'wall_ms':v[4],'terminal_cycles':v[91],'accounted_ms':v[91]*1000/args.clock_hz})
r={'scope':'matched terminal frame only; task-switch-accounted cycles with ISR attribution, not isolated operator benchmark','session':str(args.session),'clock_hz':args.clock_hz,'samples':rows}
out=ROOT/'Build/deployment-v5/performance';out.mkdir(parents=True,exist_ok=True)
(out/(args.session.name+'.json')).write_text(json.dumps(r,indent=2))
print(json.dumps(r,indent=2))
