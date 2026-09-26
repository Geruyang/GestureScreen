"""Conservative six-line fit check for every shipped reader body page."""
import json
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = json.loads((ROOT / 'Assets/content/package.json').read_text(encoding='utf-8'))
WIDTH = 690
MAX_LINES = 6
MAX_GLYPH_ADVANCE = 24  # native 24px subset; ASCII is narrower
NO_LINE_START = set('、。，；：？！”')

def wrap(body):
    lines = []
    current = ''
    for index, char in enumerate(body):
        if char == '\r':
            continue
        if char == '\n':
            lines.append(current)
            current = ''
            continue
        next_char = body[index + 1] if index + 1 < len(body) else ''
        if current and ((len(current) + 1) * MAX_GLYPH_ADVANCE > WIDTH or
                (next_char in NO_LINE_START and
                 (len(current) + 2) * MAX_GLYPH_ADVANCE > WIDTH)):
            lines.append(current)
            current = ''
        current += char
    if current:
        lines.append(current)
    return lines

report = []
for book in PACKAGE['collections']:
    for page in book['pages']:
        lines = wrap(page['body'])
        assert len(lines) <= MAX_LINES, (book['title'], page['title'], len(lines))
        assert all(not line or line[0] not in NO_LINE_START for line in lines), (book['title'], page['title'])
        assert ''.join(lines) == page['body'].replace('\n', '').replace('\r', '')
        report.append({'book': book['title'], 'page': page['title'],
                       'body_characters': len(page['body']), 'conservative_lines': len(lines)})
assert len(report) == 15
result = {'passed': True, 'page_count': len(report),
          'max_conservative_lines': max(row['conservative_lines'] for row in report),
          'pages': report}
parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path)
args = parser.parse_args()
output = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding='utf-8')
print(f"PASS: {len(report)} pages, at most {result['max_conservative_lines']} conservative lines")
