"""Generate UI-only 16x16 Chinese bits; firmware requires no font loader."""
from pathlib import Path
import json
import re
from PIL import Image, ImageDraw, ImageFont
root = Path(__file__).resolve().parents[1]
font = ImageFont.truetype('C:/Windows/Fonts/simhei.ttf', 16)
chars = set()
for relative in ('Modules/Ui/Src/gs_ui_render.c', 'App/Src/gs_app.c'):
    source = (root / relative).read_text(encoding='utf-8-sig')
    for literal in re.findall(r'"([^"\n]*)"', source):
        chars.update(ch for ch in literal if 0x80 <= ord(ch) <= 0xFFFF and ch.isprintable())
package = json.loads((root / 'Assets/content/package.json').read_text(encoding='utf-8'))
for collection in package['collections']:
    for value in (collection['title'], collection.get('author', '')):
        chars.update(ch for ch in value if 0x80 <= ord(ch) <= 0xFFFF and ch.isprintable())
    for page in collection['pages']:
        for value in (page['title'], page['body']):
            chars.update(ch for ch in value if 0x80 <= ord(ch) <= 0xFFFF and ch.isprintable())
lines = ['/* Generated static monochrome UI glyph subset; no runtime font loading. */',
         'typedef struct { uint16_t code; uint16_t rows[16]; } gs_ui_subset_glyph_t;',
         'static const gs_ui_subset_glyph_t gs_ui_font_subset[] = {']
for ch in sorted(chars):
    image = Image.new('L', (16, 16))
    # Keep each glyph at one ascent-based baseline. Ink-top anchoring moves
    # low Chinese punctuation to the top of a text line.
    left, top, right, bottom = font.getbbox(ch, anchor='la')
    if left < 0 or right > 16 or top < 0 or bottom > 17:
        raise SystemExit(f'Font glyph exceeds the common 16px cell: U+{ord(ch):04X} {ch}')
    ImageDraw.Draw(image).text((0, -1), ch, font=font, fill=255, anchor='la')
    rows = [sum(0x8000 >> x for x in range(16) if image.getpixel((x, y)) >= 96) for y in range(16)]
    if not any(rows):
        raise SystemExit(f'Font has no visible glyph for U+{ord(ch):04X} {ch}')
    lines.append('    {0x%04XU,{%s}}, /* %s */' % (ord(ch), ','.join('0x%04XU' % row for row in rows), ch))
lines += ['};', '']
(root / 'Modules/Ui/Inc/gs_ui_font_subset.h').write_text('\n'.join(lines), encoding='utf-8')
print('Generated', len(chars), 'UI glyphs,', len(chars) * 34, 'data bytes')
