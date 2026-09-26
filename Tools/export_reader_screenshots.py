"""Convert the host C renderer's 800x480 RGB565 snapshots to review PNGs."""
from pathlib import Path
import argparse
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument('--variant', choices=('screenshots', 'screenshots-swap'), default='screenshots')
parser.add_argument('--output-dir', type=Path)
parser.add_argument('--with-hint', action='store_true')
parser.add_argument('--direction-hints', action='store_true')
parser.add_argument('--selection-states', action='store_true')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
source = root / 'Build/host'
output = args.output_dir if args.output_dir is not None else root / 'Build/reader-20260922' / args.variant
output.mkdir(parents=True, exist_ok=True)
width, height = 800, 480
for name in ('shelf', 'catalog', 'reading') + (('hint',) if args.with_hint else ()) + \
        (('direction-left', 'direction-right') if args.direction_hints else ()) + \
        (('shelf-selected2', 'catalog-selected2') if args.selection_states else ()):
    raw = (source / f'reader-{name}.rgb565').read_bytes()
    if len(raw) != width * height * 2:
        raise SystemExit(f'Invalid RGB565 frame: {name}')
    rgb = bytearray(width * height * 3)
    for pixel in range(width * height):
        color = raw[pixel * 2] | (raw[pixel * 2 + 1] << 8)
        rgb[pixel * 3] = ((color >> 11) & 31) * 255 // 31
        rgb[pixel * 3 + 1] = ((color >> 5) & 63) * 255 // 63
        rgb[pixel * 3 + 2] = (color & 31) * 255 // 31
    Image.frombytes('RGB', (width, height), bytes(rgb)).save(output / f'{name}.png')
    print(output / f'{name}.png')
