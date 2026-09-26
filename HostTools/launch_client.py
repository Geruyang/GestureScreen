"""Project shortcut for the portable web-identical Gesture Studio client."""
from pathlib import Path
import subprocess
import sys


def launch():
    here = Path(__file__).resolve().parent
    executable = here.parent / 'Build/reader-clean-exit-20260923/dist/GestureStudio.exe'
    command = [str(executable)] if executable.is_file() else [sys.executable, str(here / 'studio_client.py')]
    return subprocess.Popen(command, cwd=str(here))


if __name__ == '__main__':
    launch()
