"""Long-form public pages (guides) kept as markdown files under app/content_pages/.

Each file starts with a header block of `Key: value` lines (Slug, Title tag, Meta description,
Published as YYYY-MM-DD, H1), a blank line, then the body. The body uses a deliberately small markdown subset:
`##` headings, paragraphs, `-` and `1.` lists, a pipe table, **bold**, *italic* and links.
Everything is HTML-escaped before the inline rules run, and links are limited to site paths
and https URLs, so a page file cannot inject markup or a javascript: link."""
import html
from datetime import date, datetime, timezone
import re
from pathlib import Path

CONTENT_DIR = Path(__file__).resolve().parent / "content_pages"

_LINK = re.compile(r"\[([^\]]+)\]\((/[^)\s]*|https://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")


def _inline(text: str) -> str:
    text = html.escape(text, quote=True)
    text = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    return _ITALIC.sub(r"<em>\1</em>", text)


def _table(lines: list) -> str:
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    rows = [r for r in rows if not all(set(c) <= set("-: ") for c in r)]
    head, body = rows[0], rows[1:]
    out = ["<div class=\"cp-table\"><table><thead><tr>"]
    out += [f"<th>{_inline(c)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for r in body:
        out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def render_body(markdown: str) -> str:
    out, para, i = [], [], 0
    lines = markdown.split("\n")

    def flush():
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            flush()
        elif line.startswith("## "):
            flush()
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("|"):
            flush()
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                block.append(lines[i])
                i += 1
            out.append(_table(block))
            continue
        elif re.match(r"(- |\d+\. )", line):
            flush()
            ordered = line[0].isdigit()
            items = []
            while i < len(lines) and re.match(r"(- |\d+\. )", lines[i]):
                items.append(re.sub(r"^(- |\d+\. )", "", lines[i].rstrip()))
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(t)}</li>" for t in items) + f"</{tag}>")
            continue
        else:
            para.append(line.strip())
        i += 1
    flush()
    return "\n".join(out)


def _load(path: Path) -> dict:
    head, _, body = path.read_text(encoding="utf-8").partition("\n\n")
    meta = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip()
    return {
        "slug": meta["slug"].lstrip("/"),
        "title": meta["title tag"],
        "description": meta["meta description"],
        "h1": meta["h1"],
        "published": date.fromisoformat(meta["published"]),
        "body_html": render_body(body),
    }


def load_pages() -> dict:
    """slug -> page, read once at import. Adding a page means adding a file and restarting."""
    pages = {}
    for path in sorted(CONTENT_DIR.glob("*.md")):
        page = _load(path)
        pages[page["slug"]] = page
    return pages


PAGES = load_pages()


def is_live(page: dict, preview: bool = False) -> bool:
    """A page goes live on its Published date (UTC) and not before, so a batch can be released
    a day apart without a deploy each. `preview` shows everything, for the staging host."""
    return preview or page["published"] <= datetime.now(timezone.utc).date()
