"""Project-local Tcl/Tk runtime setup for the desktop reader.

The bundled Codex Python runtime has Tcl/Tk DLLs but its Tcl search path is
not usable from the workspace.  Call ``configure()`` before importing
``tkinter``.  The copied scripts live under Build/capture-client and do not
modify system or global Python installation files.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys


def configure() -> tuple[Path, Path]:
    project = Path(__file__).resolve().parents[1]
    root = project / "Build" / "capture-client" / "tcl"
    tcl = root / "tcl8.6"
    tk = root / "tk8.6"
    source_root = Path(sys.base_prefix) / "tcl"
    source_tcl, source_tk = source_root / "tcl8.6", source_root / "tk8.6"
    root.mkdir(parents=True, exist_ok=True)
    for source, target in ((source_tcl, tcl), (source_tk, tk)):
        entry = target / ("init.tcl" if target.name == "tcl8.6" else "tk.tcl")
        if entry.is_file():
            continue
        if not source.is_dir():
            raise FileNotFoundError(f"runtime source is missing: {source}")
        # Merge into the project copy without deleting unrelated existing data.
        shutil.copytree(source, target, dirs_exist_ok=True)
    if not (tcl / "init.tcl").is_file():
        raise FileNotFoundError(f"project Tcl runtime is missing: {tcl / 'init.tcl'}")
    if not (tk / "tk.tcl").is_file():
        raise FileNotFoundError(f"project Tk runtime is missing: {tk / 'tk.tcl'}")
    os.environ["TCL_LIBRARY"] = str(tcl)
    os.environ["TK_LIBRARY"] = str(tk)
    return tcl, tk


if __name__ == "__main__":
    tcl_dir, tk_dir = configure()
    print(f"TCL_LIBRARY={tcl_dir}")
    print(f"TK_LIBRARY={tk_dir}")
    import tkinter as tk

    root = tk.Tk()
    print(f"Tk {root.tk.call('info', 'patchlevel')} usable")
    root.destroy()
