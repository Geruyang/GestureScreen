"""Convert actual C-rendered RGB565 frames to viewable PNG; no layout synthesis."""
from pathlib import Path
import struct
import json
import hashlib
from PIL import Image
root = Path(__file__).resolve().parents[1]
output = root / 'Build/agent-team/round8/executor/images'
output.mkdir(parents=True, exist_ok=True)
images = {}
for path in (root / 'Build/host').glob('ui-*.rgb565'):
    raw = path.read_bytes()
    assert len(raw) == 800 * 480 * 2
    rgb = bytearray()
    for (pixel,) in struct.iter_unpack('<H', raw):
        r, g, b = pixel >> 11, (pixel >> 5) & 63, pixel & 31
        rgb.extend(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)))
    target = output / (path.stem + '.png')
    Image.frombytes('RGB', (800, 480), bytes(rgb)).save(target)
    images[target.name] = {
        'actual_C_renderer': True,
        'raw_rgb565_sha256': hashlib.sha256(raw).hexdigest(),
        'png_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
        'resolution': [800, 480],
        'fixture_source': 'Tests/test_ui_render.c',
        'timing': 'capture age 200ms and inference 180ms are synthetic host display fields, NOT measured MCU timing',
        'recognition': ('Real desktop ROI numerical oracle: argmax fist .7085, rejected as UNCERTAIN by .90/.20 debug thresholds'
                        if 'uncertain' in path.stem else
                        ('IDENTIFIED fist 99% is a synthetic host reader UI fixture, NOT a model/accuracy/hardware result'
                         if 'reader' in path.stem else
                         'IDENTIFIED palm 97% is a synthetic host UI fixture, NOT a model/accuracy/hardware result')),
    }
    print(target)
(output / 'image-manifest.json').write_text(json.dumps({
    'scope': 'Actual C-rendered UI review images, not hardware or accuracy acceptance',
    'real_ROI_input': 'Tests/fixtures/static_model_input_486.bin',
    'real_ROI_input_sha256': hashlib.sha256((root / 'Tests/fixtures/static_model_input_486.bin').read_bytes()).hexdigest(),
    'images': images}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
