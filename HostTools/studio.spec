# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

root = Path(SPECPATH)
project = root.parent
datas, binaries, hiddenimports = [], [], []
datas += collect_data_files('PySide6', includes=['resources/**', 'translations/**'])
binaries += collect_dynamic_libs('PySide6')
hiddenimports += collect_submodules('PySide6.QtWebEngineCore') + collect_submodules('PySide6.QtWebEngineWidgets')
datas += collect_data_files('ai_edge_litert')
binaries += collect_dynamic_libs('ai_edge_litert')
hiddenimports += collect_submodules('ai_edge_litert.interpreter')
hiddenimports += collect_submodules('numpy._core')
hiddenimports += ['capture_server', 'managed_capture', 'usb_capture', 'model_runtime']
datas += [(str(root / 'web'), 'web'), (str(root / 'model'), 'model'),
          (str(root / 'licenses'), 'licenses')]
for distribution in ('PySide6', 'PySide6_Essentials', 'PySide6_Addons', 'shiboken6',
                     'ai-edge-litert', 'numpy', 'pillow', 'pyserial', 'pyinstaller'):
    datas += copy_metadata(distribution)
a = Analysis([str(root / 'studio_client.py')], pathex=[str(root)], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=['tensorflow', 'torch'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='GestureStudio',
          console=False, onefile=True)
