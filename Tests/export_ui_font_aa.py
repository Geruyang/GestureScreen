"""Build licensed, native-size 4-bit Noto Sans SC glyphs for the reader."""
from pathlib import Path
import json
import re
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / 'Assets/fonts/NotoSansSC-VF.ttf'
SOURCE = (ROOT / 'Modules/Ui/Src/gs_ui_render.c').read_text(encoding='utf-8')
PACKAGE = json.loads((ROOT / 'Assets/content/package.json').read_text(encoding='utf-8'))

def visible(chars):
    return {ch for ch in chars if ch.isprintable() and ord(ch) >= 0x20}

ui_chars = visible(''.join(re.findall(r'"([^"\n]*)"', SOURCE)) + '0123456789/V·：')
body_chars = set()
for book in PACKAGE['collections']:
    ui_chars.update(visible(book['title'] + book.get('author', '')))
    for page in book['pages']:
        ui_chars.update(visible(page['title']))
        body_chars.update(visible(page['body']))
glyph24 = sorted(ui_chars | body_chars, key=ord)
glyph32 = sorted(ui_chars, key=ord)

def glyph(ch, size, rows, offset):
    font = ImageFont.truetype(str(FONT), size)
    font.set_variation_by_axes([450])
    bbox = font.getbbox(ch, anchor='la')
    if bbox[0] < -1 or bbox[2] > size + 1 or bbox[1] + offset < 0 or bbox[3] + offset > rows:
        raise ValueError(f'Glyph outside {size}x{rows}: U+{ord(ch):04X} {bbox}')
    canvas = Image.new('L', (size, rows))
    ImageDraw.Draw(canvas).text((0, offset), ch, font=font, fill=255, anchor='la')
    samples = list(canvas.get_flattened_data())
    if not any(samples) and ch != ' ':
        raise ValueError(f'Blank glyph U+{ord(ch):04X}')
    alpha = [(v * 15 + 127) // 255 for v in samples]
    packed = [(alpha[i] << 4) | alpha[i+1] for i in range(0, len(alpha), 2)]
    advance = max(1, min(size, round(font.getlength(ch))))
    return advance, packed

def table(name, chars, size, rows, offset):
    data = []
    for ch in chars:
        advance, packed = glyph(ch, size, rows, offset)
        data.append(f'    {{0x{ord(ch):04X}U,{advance}U,{{' + ','.join(f'0x{v:02X}U' for v in packed) + '}},')
    return [f'typedef struct {{ uint16_t code; uint8_t advance; uint8_t pixels[{size*rows//2}]; }} gs_aa_glyph_{size}_t;',
            f'static const gs_aa_glyph_{size}_t {name}[] = {{', *data, '};', '']

lines = ['/* Generated from NotoSansSC-VF.ttf under SIL OFL 1.1; see Assets/fonts/OFL.txt. */',
         '#ifndef GS_UI_FONT_AA_SUBSET_H', '#define GS_UI_FONT_AA_SUBSET_H']
lines += table('gs_font24', glyph24, 24, 28, -2)
lines += table('gs_font32', glyph32, 32, 38, -2)
lines += ['#endif', '']
OUT = ROOT / 'Modules/Ui/Inc/gs_ui_font_aa_subset.h'
OUT.write_text('\n'.join(lines), encoding='utf-8')
print(f'{len(glyph24)} 24px, {len(glyph32)} 32px glyphs; {len(glyph24)*336+len(glyph32)*608} bitmap bytes')
