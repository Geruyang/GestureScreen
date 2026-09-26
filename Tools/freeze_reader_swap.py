"""Freeze the FIST/V reader action swap without touching the original release."""
from pathlib import Path
import hashlib
import json
import shutil

root = Path(__file__).resolve().parents[1]
bundle = root / 'Build/reader-20260922'
baseline = bundle / 'release'
release = bundle / 'release-swap'
report = bundle / 'firmware-swap'
release.mkdir(parents=True, exist_ok=True)
report.mkdir(parents=True, exist_ok=True)


def digest(path: Path) -> dict[str, str | int]:
    data = path.read_bytes()
    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


# The existing approved reader release supplies immutable model/runtime input.
reference = json.loads((baseline / 'source-manifest.json').read_text(encoding='utf-8'))
protected = ('Middlewares/ST/AI/', 'Modules/StaticRecognition/', 'Modules/Vision/')
rows = []
for item in reference['files']:
    name = item['path']
    if not name.startswith(protected):
        continue
    actual = digest(root / name)['sha256']
    rows.append({'path': name, 'baseline_sha256': item['sha256'],
                 'current_sha256': actual, 'passed': actual == item['sha256']})
if not rows or not all(row['passed'] for row in rows):
    raise SystemExit('Frozen model/runtime/preprocessing hash check failed')
model_check = {'passed': True, 'checked_files': len(rows),
               'baseline': 'release/source-manifest.json', 'files': rows}
(report / 'model-hash-check.json').write_text(
    json.dumps(model_check, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

for extension in ('axf', 'hex', 'map'):
    shutil.copy2(root / f'MDK-ARM/Objects/GestureScreen.{extension}',
                 release / f'GestureScreen.{extension}')
shutil.copy2(root / 'Build/keil-build.log', release / 'keil-build.log')

sources = [
    'Modules/Gesture/Src/gs_gesture.c',
    'Modules/Ui/Src/gs_ui.c',
    'Modules/Ui/Src/gs_ui_render.c',
    'Modules/Ui/Inc/gs_ui_font_subset.h',
    'Tests/test_gesture_ui.c',
    'Tools/export_reader_screenshots.py',
    'Tools/verify.py',
    'Tools/freeze_reader_swap.py',
]
artifacts = [
    'release-swap/GestureScreen.axf',
    'release-swap/GestureScreen.hex',
    'release-swap/GestureScreen.map',
    'release-swap/keil-build.log',
    'screenshots-swap/shelf.png',
    'screenshots-swap/catalog.png',
    'screenshots-swap/reading.png',
    'firmware-swap/model-hash-check.json',
]
manifest = {
    'identity': 'reader-20260922-fist-v-swap-host-frozen',
    'hardware_flashing': False,
    'base_release_hex_sha256': digest(baseline / 'GestureScreen.hex')['sha256'],
    'source_files': {name: digest(root / name) for name in sources},
    'artifact_files': {name: digest(bundle / name) for name in artifacts},
}
(report / 'manifest.json').write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Swap HEX SHA256:', manifest['artifact_files']['release-swap/GestureScreen.hex']['sha256'])
print('Protected model/runtime/preprocessing files:', len(rows))
