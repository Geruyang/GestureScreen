"""Freeze the built reader firmware and its reviewed source inputs; no flashing."""
from pathlib import Path
import hashlib
import json
import shutil

root = Path(__file__).resolve().parents[1]
bundle = root / 'Build/reader-20260922'
release = bundle / 'release'
release.mkdir(parents=True, exist_ok=True)

sources = [
    'App/Src/gs_app.c',
    'BSP/Src/gs_port_board.c',
    'Modules/Gesture/Inc/gs_gesture.h',
    'Modules/Gesture/Src/gs_gesture.c',
    'Modules/Ui/Inc/gs_ui.h',
    'Modules/Ui/Inc/gs_ui_render.h',
    'Modules/Ui/Inc/gs_ui_font_subset.h',
    'Modules/Ui/Src/gs_ui.c',
    'Modules/Ui/Src/gs_ui_render.c',
    'Modules/Content/Src/gs_content_builtin.c',
    'Modules/Content/Src/gs_content_builtin.json',
    'Assets/content/reader_source.json',
    'Assets/content/package.json',
    'Tools/build_reader_content.py',
    'Tools/export_reader_screenshots.py',
    'Tools/freeze_reader.py',
    'Tools/deploy_v5_content.py',
    'Tools/deploy_v5_content_check.py',
    'Tools/verify.py',
    'Tools/test_host.ps1',
    'Tests/export_ui_font.py',
    'Tests/test_reader_ui.c',
    'Tests/test_gesture_ui.c',
    'Tests/test_preview_display.c',
    'Tests/test_ui_render.c',
    'Tests/test_incremental_render.c',
]
artifacts = [
    'release/GestureScreen.axf',
    'release/GestureScreen.hex',
    'release/GestureScreen.map',
    'release/keil-build.log',
    'screenshots/shelf.png',
    'screenshots/catalog.png',
    'screenshots/reading.png',
    'content-check/result.json',
    'content-check/converter-result.json',
    'firmware/RESULTS.md',
]
for extension in ('axf', 'hex', 'map'):
    shutil.copy2(root / f'MDK-ARM/Objects/GestureScreen.{extension}',
                 release / f'GestureScreen.{extension}')
shutil.copy2(root / 'Build/keil-build.log', release / 'keil-build.log')


def digest(path: Path) -> dict[str, str | int]:
    data = path.read_bytes()
    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


manifest = {
    'identity': 'reader-20260922-host-frozen',
    'hardware_flashing': False,
    'screens': ['bookshelf', 'catalog', 'reading'],
    'source_files': {name: digest(root / name) for name in sources},
    'artifact_files': {name: digest(bundle / name) for name in artifacts},
}
(bundle / 'firmware').mkdir(parents=True, exist_ok=True)
(bundle / 'firmware/manifest.json').write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Frozen reader HEX SHA256:', manifest['artifact_files']['release/GestureScreen.hex']['sha256'])
