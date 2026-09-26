"""Run ArmClang's static analyzer over all application/BSP/module C sources.
Does not modify source or use hardware. Reports cannot prove race/timing safety.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--compiler', default=os.environ.get('ARMCLANG') or shutil.which('armclang') or 'armclang',
                    help='Arm Compiler 6 executable; defaults to ARMCLANG or PATH')
parser.add_argument('--include-generated',action='store_true',
                    help='Also analyze Core and USB_DEVICE; suppress template unused-parameter warnings there.')
args=parser.parse_args()
project=root/'MDK-ARM/GestureScreen.uvprojx'
tree=ET.parse(project)
control=tree.find('.//Cads/VariousControls')
flags=['--target=arm-arm-none-eabi','-mcpu=cortex-m4','-mfpu=fpv4-sp-d16',
       '-mfloat-abi=hard','-std=c99','-Wall','-Wextra','--analyze',
       '-Xanalyzer','-analyzer-output=text']
for item in control.findtext('Define').split(','):
    flags+=['-D'+item]
for item in control.findtext('IncludePath').split(';'):
    flags+=['-I',str((project.parent/item.replace('\\','/')).resolve())]
out=root/'Build/static-analysis'
out.mkdir(parents=True,exist_ok=True)
bases=('App','BSP','Modules','Core','USB_DEVICE') if args.include_generated else ('App','BSP','Modules')
files=[p for base in bases for p in sorted((root/base).rglob('*.c'))]
failed=[]
for source in files:
    extra=['-Wno-unused-parameter'] if source.relative_to(root).parts[0] in ('Core','USB_DEVICE') else []
    result=subprocess.run([args.compiler,*flags,*extra,str(source)],capture_output=True,text=True,encoding='utf-8',errors='replace')
    log=out/(source.stem+'.log')
    log.write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode or 'warning:' in result.stderr or 'error:' in result.stderr:
        failed.append(source)
        print(source.relative_to(root),result.stderr)
print(f'Analyzed {len(files)} C files ({", ".join(bases)}); {len(failed)} files with diagnostics. Logs: {out}')
raise SystemExit(bool(failed))
