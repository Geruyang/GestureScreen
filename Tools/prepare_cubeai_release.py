"""Freeze current build and derive bounded debugging plans; never contacts target."""
from pathlib import Path
import hashlib, json, shutil, struct
ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT/'Build/cubeai-migration'
REL = WORK/'release'
HERE = WORK/'analysis'
REL.mkdir(exist_ok=True)
HERE.mkdir(exist_ok=True)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
artifacts = {}
for ext,folder in [('hex','Objects'),('axf','Objects'),('map','Objects')]:
    src=ROOT/f'MDK-ARM/{folder}/GestureScreen.{ext}'
    dst=REL/src.name
    if dst.exists():
        assert sha(dst)==sha(src), 'Frozen release exists with different content'
    else:
        shutil.copy2(src,dst)
    artifacts[ext]={'path':str(dst),'sha256':sha(dst),'bytes':dst.stat().st_size}
memory={};base=0
for line in (REL/'GestureScreen.hex').read_text().splitlines():
    r=bytes.fromhex(line[1:]);assert sum(r)%256==0
    n,addr,kind=r[0],int.from_bytes(r[1:3],'big'),r[3]
    if kind==4:base=int.from_bytes(r[4:-1],'big')<<16
    elif kind==0:
        for i,b in enumerate(r[4:-1]):
            a=base+addr+i
            assert 0x08000000<=a<0x08100000 and a not in memory
            memory[a]=b
assert min(memory)==0x08000000
end=max(memory)+1
payload=bytes(memory.get(a,255) for a in range(0x08000000,end))
assert len(memory)==len(payload)
(HERE/'expected-flash.bin').write_bytes(payload)
msp,reset=struct.unpack_from('<II',payload)
review={'artifacts':artifacts,'hex_contiguous_span_bytes':len(payload),
        'hex_address_range':['0x08000000',f'0x{end:08x}'],
        'expected_flash_sha256':hashlib.sha256(payload).hexdigest(),
        'vectors':{'msp':hex(msp),'reset':hex(reset)}}
(HERE/'final-review.json').write_text(json.dumps(review,indent=2))
old=ROOT/'Build/agent-team/round12c/analysis'
code=(old/'extract_postfix_layout.py').read_text()
code=code.replace('P=HERE.parents[3]',f'P=Path({str(ROOT)!r})')
code=code.replace("P/'Build/agent-team/round12c/release'",f'Path({str(REL)!r})')
code=code.replace("P/'Build/agent-team/round12b/analysis/postfix-layout.json'",f'Path({str(old / "postfix-layout.json")!r})')
code=code.replace('offline_frozen_round12c_no_target','offline_frozen_cubeai_no_target')
code=code.replace('Full exact frozen round12c HEX', 'Full exact frozen Cube.AI HEX')
(HERE/'extract_postfix_layout.py').write_text(code)
exec(compile(code,str(HERE/'extract_postfix_layout.py'),'exec'),{'__file__':str(HERE/'extract_postfix_layout.py')})
code=(ROOT/'Build/agent-team/round7/analysis/prepare_postfix_runtime.py').read_text()
code=code.replace('round7','cubeai-migration').replace('Independently audited','Main-agent reviewed')
code=code.replace('Three sequential snapshots','Ten sequential snapshots')
code=code.replace("('usb','g_gs_usb_diag'),('uwtick','uwTick')", "('usb','g_gs_usb_diag'),('static','g_gs_static_diag'),('preview','g_gs_preview_diag'),('uwtick','uwTick')")
code=code.replace('range(1,4)','range(1,11)').replace('groups[:6]','groups[:8]')
code=code.replace('$sample <= 3','$sample <= 10').replace('$sample < 3','$sample < 10')
(HERE/'prepare_postfix_runtime.py').write_text(code)
exec(compile(code,str(HERE/'prepare_postfix_runtime.py'),'exec'),{'__file__':str(HERE/'prepare_postfix_runtime.py')})
flash='gdb_port disabled\ntcl_port disabled\ntelnet_port disabled\nbindto 127.0.0.1\ninit\nreset halt\ngs_verify_chip\nprogram {'+str(REL/'GestureScreen.hex')+'} verify reset exit\n'
(HERE/'flash.tcl').write_text(flash)
sources={p.relative_to(ROOT).as_posix():sha(p) for folder in ['App','BSP','Modules','Core','USB_DEVICE','Middlewares/ST/AI']
         for p in (ROOT/folder).rglob('*') if p.is_file()}
(REL/'release-manifest.json').write_text(json.dumps({'artifacts':artifacts,'source_sha256':sources},indent=2))
shutil.copy2(ROOT/'Build/keil-build.log',REL/'keil-build.log')
shutil.copy2(ROOT/'Build/usb-validation/validation.json',REL/'software-validation.json')
print(json.dumps(artifacts,indent=2))
