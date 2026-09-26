"""CubeMX 生成后重新集成自编模块，仅依赖 Python 标准库。"""
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
project = ROOT / 'MDK-ARM/GestureScreen.uvprojx'
tree = ET.parse(project)
target = tree.find('./Targets/Target')
assert target is not None and target.findtext('TargetName') == 'GestureScreen'

# CubeF4 旧版 MDK 生成器默认选择仅适配 AC5 的 RVDS 端口。
# AC6 使用同一已安装内核中的原版 GCC/ARM_CM4F 端口（GNU 汇编语法）。
ioc = dict(line.split('=', 1) for line in (ROOT / 'GestureScreen.ioc').read_text(encoding='utf-8').splitlines() if '=' in line)
sdk = Path(ioc['ProjectManager.CustomerFirmwarePackage'].replace('\\:', ':').replace('\\\\', '\\'))
portable = Path('Middlewares/Third_Party/FreeRTOS/Source/portable')
for filename in ['port.c', 'portmacro.h']:
    destination = ROOT / portable / 'GCC/ARM_CM4F' / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sdk / portable / 'GCC/ARM_CM4F' / filename, destination)
for node in tree.iter():
    if node.text and '/RVDS/ARM_CM4F' in node.text:
        node.text = node.text.replace('/RVDS/ARM_CM4F', '/GCC/ARM_CM4F')
    if node.text and '\\RVDS\\ARM_CM4F' in node.text:
        node.text = node.text.replace('\\RVDS\\ARM_CM4F', '\\GCC\\ARM_CM4F')

def set_text(parent, name, value):
    node = parent.find(name)
    if node is None:
        node = ET.SubElement(parent, name)
    node.text = value

# 明确选用本工程已安装的 MDK 5.43 / AC 6.24 工具链。
set_text(target, 'pCCUsed', '6240000::V6.24::ARMCLANG')
set_text(target, 'uAC6', '1')
common = target.find('./TargetOption/TargetCommonOption')
set_text(common, 'Cpu', 'IRAM(0x20000000-0x2002FFFF) IRAM2(0x10000000-0x1000FFFF) IROM(0x08000000-0x080FFFFF) CLOCK(168000000) FPU2 CPUTYPE("Cortex-M4")')
set_text(common, 'OutputDirectory', '.\\Objects\\')
set_text(common, 'ListingPath', '.\\Listings\\')
linker = target.find('./TargetOption/TargetArmAds/LDads')
set_text(linker, 'umfTarg', '0')
set_text(linker, 'useFile', '1')
set_text(linker, 'ScatterFile', '.\\GestureScreen.sct')
groups = target.find('Groups')
for group in list(groups):
    if (group.findtext('GroupName') or '').startswith('GestureScreen/'):
        groups.remove(group)

include_dirs = []
for base in [ROOT / 'App', ROOT / 'BSP', *sorted((ROOT / 'Modules').glob('*'))]:
    if (base / 'Inc').is_dir():
        include_dirs.append('../' + (base / 'Inc').relative_to(ROOT).as_posix())
    sources = sorted((base / 'Src').glob('*.c'))
    if not sources:
        continue
    group = ET.SubElement(groups, 'Group')
    ET.SubElement(group, 'GroupName').text = 'GestureScreen/' + base.name
    files = ET.SubElement(group, 'Files')
    for source in sources:
        entry = ET.SubElement(files, 'File')
        ET.SubElement(entry, 'FileName').text = source.name
        ET.SubElement(entry, 'FileType').text = '1'
        ET.SubElement(entry, 'FilePath').text = '../' + source.relative_to(ROOT).as_posix()

control = target.find('./TargetOption/TargetArmAds/Cads/VariousControls')
cubeai = ROOT / 'Middlewares/ST/AI'
assert (cubeai / 'manifest.json').is_file(), 'Run Tools/install_cubeai_generated.py first'
include_dirs += ['../Middlewares/ST/AI/Inc', '../Middlewares/ST/AI/Generated']
group = ET.SubElement(groups, 'Group')
ET.SubElement(group, 'GroupName').text = 'GestureScreen/STM32CubeAI'
files = ET.SubElement(group, 'Files')
for source in [*sorted((cubeai / 'Generated').glob('*.c')), *sorted((cubeai / 'Lib').glob('*.lib'))]:
    entry = ET.SubElement(files, 'File')
    ET.SubElement(entry, 'FileName').text = source.name
    ET.SubElement(entry, 'FileType').text = '4' if source.suffix == '.lib' else '1'
    ET.SubElement(entry, 'FilePath').text = '../' + source.relative_to(ROOT).as_posix()
defines = (control.findtext('Define') or '').split(',')
set_text(control, 'Define', ','.join(dict.fromkeys(defines + ['GS_STATIC_USE_CUBEAI=1'])))
existing = (control.findtext('IncludePath') or '').split(';')
set_text(control, 'IncludePath', ';'.join(dict.fromkeys(existing + include_dirs)))
set_text(control, 'MiscControls', '-std=c99 -Wall -Wextra')
ET.indent(tree, space='  ')
tree.write(project, encoding='utf-8', xml_declaration=True)
subprocess.run([sys.executable, str(ROOT / 'Tools/integrate_lwip.py')], check=True)
print('Integrated modules; ARM Compiler 6.24; 1 MiB Flash / 192 KiB ordinary SRAM.')
