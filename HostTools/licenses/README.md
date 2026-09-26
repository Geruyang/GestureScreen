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
option for the Qt components. The released PyInstaller **one-file** executable
extracts its bundled shared libraries to a temporary directory at runtime;
the release does not provide a persistent external Qt DLL directory for direct
replacement. The application source, pinned dependencies, and `studio.spec`
are provided so recipients can install a compatible modified Qt build and
rebuild the application; see [source build steps](../README.md). This rebuild
path has not been tested with a modified Qt build. The license texts and source
locations above remain authoritative; this inventory is not a legal
determination of every distribution obligation.

The official STM32Cube.AI host runtime is not included. The app carries the
frozen project's TFLite model and project-built preprocess library, with their
identity recorded in `model/manifest.json`.
