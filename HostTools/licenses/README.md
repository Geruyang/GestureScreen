# Gesture Studio portable package: third-party license inventory

This directory is bundled inside `GestureStudio.exe` and extracted with its other
application assets. `FETCHED_SOURCES.json` records the official URL and SHA-256
of each downloaded text. The package also includes the installed wheels'
`*.dist-info` metadata and license files through the PyInstaller specification.

| Component in this build | Installed version and stated license | Included text |
| --- | --- | --- |
| PySide6, PySide6 Essentials, PySide6 Addons, shiboken6 | 6.8.3; wheel metadata: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | `LGPL-3.0.txt`, `GPL-3.0.txt`, wheel metadata |
| Qt WebEngine and Chromium | Qt 6.8 licensing and third-party terms | `QtWebEngine-6.8-third-party.html`, `Chromium-BSD.txt`, `LGPL-2.1.txt` for applicable listed components |
| LiteRT (`ai-edge-litert`) | 2.2.0; wheel metadata: Apache 2.0 | `Apache-2.0.txt`, wheel metadata |
| pyserial | 3.5; wheel metadata: BSD | `pyserial-BSD-3-Clause.txt` from its v3.5 tag, wheel metadata |
| NumPy, Pillow | 2.5.3, 12.3.0; wheel metadata includes their license declarations | Original wheel `dist-info/licenses` files |
| PyInstaller bootloader | 6.11.1; GPLv2-or-later with its bundling exception | `PyInstaller-COPYING.txt`, wheel metadata |
| Python runtime | Bundled interpreter's Python Software Foundation terms | `Python-PSF-LICENSE.txt` copied from the build interpreter |

Qt licensing information and source access are published at
<https://doc.qt.io/qt-6.8/licensing.html> and
<https://code.qt.io/cgit/qt/>. Qt WebEngine's component notice list is published
at <https://doc.qt.io/qt-6.8/qtwebengine-licensing.html> and preserved here as
`QtWebEngine-6.8-third-party.html`. Chromium source and license are available at
<https://chromium.googlesource.com/chromium/src/>. Gesture Studio uses the LGPL
option for the Qt components and packages them as separate shared libraries.
Recipients should be able to replace those LGPL libraries, subject to the
conditions in the license. This inventory supplies license texts and source
locations; it is not a legal determination of every distribution obligation.

The official STM32Cube.AI host runtime is not included. The app carries the
frozen project's TFLite model and project-built preprocess library, with their
identity recorded in `model/manifest.json`.
