"""Record successfully completed check_all.ps1 software evidence and input hashes."""
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
out = root / 'Build/usb-validation'
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def read_log(p):
    data = p.read_bytes()
    return data.decode('utf-16' if data[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig')
def tests(path, expected):
    text = read_log(root / path)
    assert re.search(rf'Ran {expected} tests\b', text) and re.search(r'^OK\s*$', text, re.M)
    return {'count': expected, 'log': path, 'sha256': sha(root/path)}

def ethernet_tests():
    directory = root / 'Build/ethernet-validation'
    evidence = json.loads((directory / 'protocol-result.json').read_text(encoding='utf-8'))
    expected = dict(control=200, created=201, duplicate=200, rate_limit=429, epoch_changed=409)
    assert evidence['statuses'] == expected and evidence['stored_records'] == 1
    assert evidence['hardware_contacted'] is False
    assert evidence['request_bytes'] > 153600
    assert evidence['source_sha256']
    for relative, digest in evidence['source_sha256'].items():
        source = root / relative
        assert sha(source) == digest, f'Ethernet evidence source changed: {source}'
        assert (directory / 'protocol-result.json').stat().st_mtime >= source.stat().st_mtime
    state = read_log(directory / 'state_test-run.log')
    protocol = read_log(directory / 'protocol-run.log')
    assert len(re.findall(r'^PASS ', state, re.M)) == 8
    assert 'All production-state-machine mock tests passed' in state
    assert 'PASS actual firmware headers + 153600-byte body' in protocol
    for status in expected.values():
        assert f'PASS actual HostTools HTTP status={status} ' in protocol
    paths = ('state_test-build.log', 'parser_bridge-build.log', 'state_test-run.log',
             'protocol-run.log', 'protocol-result.json', 'firmware_request.bin',
             'control.http', 'created.http', 'duplicate.http', 'rate_limit.http', 'epoch_changed.http')
    return dict(mock_groups=8, protocol_statuses=expected, stored_records=1,
                scope=evidence['scope'], hardware_contacted=False,
                source_sha256=evidence['source_sha256'],
                evidence={name: dict(path=(directory/name).relative_to(root).as_posix(),
                                    sha256=sha(directory/name), bytes=(directory/name).stat().st_size)
                          for name in paths})

build = read_log(root/'Build/keil-build.log')
assert '0 Error(s), 0 Warning(s)' in build
mapping = (root/'MDK-ARM/Objects/GestureScreen.map').read_text()
rom = int(re.search(r'Total ROM Size .*?([0-9]+) \(', mapping)[1])
ram = int(re.search(r'Total RW  Size .*?([0-9]+) \(', mapping)[1])
files = sorted(p for base in ('App','BSP','Modules','Core','USB_DEVICE','HostTools','Models','Tools','Tests','Debug')
               for p in (root/base).rglob('*') if p.suffix in ('.c','.h','.py','.ps1','.cfg','.gdb','.html','.js','.cjs','.txt')
               and not any(x in ('__pycache__','captures','validation') for x in p.relative_to(root/base).parts))
py_files = [p for p in files if p.suffix == '.py']
for p in py_files:
    ast.parse(p.read_text(encoding='utf-8-sig'), filename=str(p))
artifacts = {s: root/f'MDK-ARM/Objects/GestureScreen.{s}' for s in ('axf','hex','map')}
for p in files:
    if p.suffix in ('.c','.h') and p.relative_to(root).parts[0] in ('App','BSP','Modules','Core','USB_DEVICE'):
        assert artifacts['axf'].stat().st_mtime >= p.stat().st_mtime, f'Firmware older than {p}'
files += [root/'GestureScreen.ioc',root/'MDK-ARM/GestureScreen.uvprojx',root/'MDK-ARM/GestureScreen.sct']
files += sorted(p for p in (root/'Middlewares/ST/AI').rglob('*') if p.is_file())
ioc = dict(line.split('=',1) for line in (root/'GestureScreen.ioc').read_text().splitlines() if '=' in line)
sdk = Path(ioc['ProjectManager.CustomerFirmwarePackage'].replace('\\:',':').replace('\\\\','\\'))
vendor_usb = {}
for p in sorted((root/'Middlewares/ST/STM32_USB_Device_Library').rglob('*')):
    if p.suffix not in ('.c','.h'):
        continue
    relative = p.relative_to(root)
    assert (sdk/relative).is_file() and sha(p) == sha(sdk/relative), f'USB SDK source differs: {p}'
    vendor_usb[relative.as_posix()] = sha(p)
analysis = read_log(out/'static-analysis.log')
assert '0 files with diagnostics' in analysis
host_suites = re.findall(r"Name\s*=\s*'(test_[^']+)'", read_log(root/'Tools/test_host.ps1'))
assert host_suites and len(host_suites) == len(set(host_suites))
for name in host_suites:
    log = root/f'Build/host/{name}-run.log'
    assert log.stat().st_size > 0 and ('PASS' in read_log(log) or 'passed' in read_log(log))
record = dict(generated_at=datetime.now().astimezone().isoformat(),
              target='EmbedFire Challenger V1 / STM32F429IGT6 / 800x480 RGB',
              build=dict(errors=0,warnings=0,rom_bytes=rom,rw_zi_bytes=ram,log='Build/keil-build.log'),
              artifacts={s: dict(path=p.relative_to(root).as_posix(),sha256=sha(p),bytes=p.stat().st_size)
                         for s,p in artifacts.items()},
              source_sha256={p.relative_to(root).as_posix():sha(p) for p in files},
              unmodified_usb_sdk_source_sha256=vendor_usb,
              tests=dict(host_suites=len(host_suites),capture_http=tests('Build/capture-tests/http.log',26),
                         usb=tests('Build/capture-tests/usb.log',18),ethernet=ethernet_tests(),
                         ui_groups=4,models=tests('Build/model-tools/tests.log',7),
                         c_python_wire_sha256=sha(out/'c-sender.bin'),python_syntax_files=len(py_files),
                         static_analysis=analysis.strip(),firedap_config='Parsed offline; 1000 kHz; no target init'),
              hardware_contacted=False,hardware_validated=False,personal_dataset_available=False,
              seven_class_business_model_installed=False,
              limitations=['Synthetic tests do not validate USB electrical timing/throughput, DCMI or LTDC.',
                           'Ethernet HAL/lwIP mocks and localhost exchange do not validate physical PHY/DMA timing or real TCP conditions.',
                           'Static analysis covers application/BSP/modules/Core/USB_DEVICE; no exhaustive third-party audit.',
                           'No target execution, personal gesture accuracy or on-board stack/performance evidence.'])
(out/'validation.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'Python syntax passed for {len(py_files)} files. Recorded {out / "validation.json"}')
