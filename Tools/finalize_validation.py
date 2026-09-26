"""Record actual build resources, final firmware/source hashes and existing test evidence."""
from pathlib import Path
import hashlib, json, re
from datetime import datetime
root = Path(__file__).resolve().parents[1]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
build = (root/'Build/keil-build.log').read_text(encoding='utf-8-sig')
assert '0 Error(s), 0 Warning(s)' in build
mapping = (root/'MDK-ARM/Objects/GestureScreen.map').read_text()
rom = int(re.search(r'Total ROM Size .*?([0-9]+) \(',mapping)[1])
ram = int(re.search(r'Total RW  Size .*?([0-9]+) \(',mapping)[1])
firmware = {s:root/f'MDK-ARM/Objects/GestureScreen.{s}' for s in ['axf','hex','map']}
sources = sorted(p for base in ['App','BSP','Modules','Core'] for p in (root/base).rglob('*') if p.suffix in ('.c','.h'))
assert all(firmware['axf'].stat().st_mtime >= p.stat().st_mtime for p in sources), 'Firmware older than source'
sources += [root/'GestureScreen.ioc',root/'MDK-ARM/GestureScreen.uvprojx']
record = {
 'generated_at':datetime.now().astimezone().isoformat(),
 'target':'STM32F429IGT6 / Embedfire Challenger V1 / 800x480 RGB',
 'toolchain':'CubeMX 6.18.1 / CubeF4 1.28.3 / Keil 5.43 / AC6.24',
 'build':{'errors':0,'warnings':0,'rom_bytes':rom,'rw_zi_bytes':ram},
 'artifacts':{s:{'path':p.relative_to(root).as_posix(),'sha256':sha(p),'bytes':p.stat().st_size} for s,p in firmware.items()},
 'source_sha256':{p.relative_to(root).as_posix():sha(p) for p in sources},
 'test_evidence': {
  'host_suites':{'count':4,'path':'Build/host','scope':'portable buffer, gesture/UI, preprocess/AI gates, synthetic end-to-end'},
  'capture_http':{'count':17,'path':'Build/video-clips-20260916/capture-tests.log','scope':'localhost HTTP, post-clip labels, AVI structure/naming, restart recovery and synthetic RGB565 frames'},
  'capture_browser':json.loads((root.parent/'output/playwright/capture-video-ui-validation-20260916.json').read_text()),
  'ethernet':{'groups':8,'path':'Build/video-clips-20260916/ethernet-protocol.log','scope':'actual C client under HAL/lwIP mocks plus real localhost capture server 201/200/409/429'},
  'models':{p.name:json.loads(p.read_text()) for p in (root/'Models/validation').glob('*.json')}
 },
 'hardware_connected':False,'hardware_validated':False,'personal_dataset_available':False,
 'seven_class_business_model_installed':False,
 'limitations':['No MCU execution, camera frame, LCD scan or physical Ethernet validation',
                'Synthetic vectors test numerical/software correctness, not seven-class accuracy or MCU timing',
                'Browser UI flow used synthetic local frames; no WPS playback or real camera frames']}
destination=root/'Build/completion-20260915/final-validation.json'
destination.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'{destination}\nROM={rom} RW+ZI={ram}\nHEX SHA256={record["artifacts"]["hex"]["sha256"]}')
