"""Turn the reviewed public-domain reader source into bounded firmware pages."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Assets/content/reader_source.json"
DEST = ROOT / "Assets/content/package.json"
MAX_CHARS = 108
BREAK_AFTER = "。！？；"
NO_LINE_START = "、。，；：？！ ”"


def rendered_lines(body: str) -> int:
    """Mirror the C renderer's 728px, 2x glyph advances and punctuation hold."""
    index = 0
    lines = 0
    while index < len(body):
        used = 0
        start = index
        while index < len(body):
            advance = (12 if ord(body[index]) < 128 else 18) * 2
            if used + advance > 728:
                break
            if used and index + 1 < len(body) and body[index + 1] in NO_LINE_START:
                next_advance = (12 if ord(body[index + 1]) < 128 else 18) * 2
                if used + advance + next_advance > 728:
                    break
            used += advance
            index += 1
        if index == start or body[start] in NO_LINE_START:
            raise ValueError("Reader page wraps at forbidden punctuation")
        lines += 1
    return lines


def pages(body: str) -> list[str]:
    result = []
    for paragraph in body.splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        while len(paragraph) > MAX_CHARS:
            cut = max((i + 1 for i, ch in enumerate(paragraph[: MAX_CHARS + 1])
                       if ch in BREAK_AFTER), default=0)
            if cut < MAX_CHARS // 2:
                cut = MAX_CHARS
            result.append(paragraph[:cut])
            paragraph = paragraph[cut:]
        if paragraph:
            result.append(paragraph)
    return result


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    books = source["books"]
    if len(books) != 3:
        raise ValueError("Reader expects exactly three reviewed books")
    collections = []
    for book in books:
        if book.get("license") != "Public domain" or not book.get("source"):
            raise ValueError("Each book needs public-domain source metadata")
        chunks = pages(book["body"])
        if not 1 <= len(chunks) <= 32 or "".join(chunks) != book["body"].replace("\n", ""):
            raise ValueError("Page split lost or duplicated text")
        if any(rendered_lines(chunk) > 6 for chunk in chunks):
            raise ValueError("Reader page exceeds six physical text lines")
        collections.append({
            "title": book["title"], "author": book["author"],
            "source": book["source"], "license": book["license"],
            "pages": [{"title": f"第{i + 1}页", "body": chunk}
                      for i, chunk in enumerate(chunks)],
        })
    DEST.write_text(json.dumps({"schema_version": 1,
                                "version": "reader-20260922-v1",
                                "collections": collections},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Reader pages:", ", ".join(f"{item['title']} {len(item['pages'])}" for item in collections))


if __name__ == "__main__":
    main()
