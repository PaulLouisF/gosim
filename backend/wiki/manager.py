"""
Read, write, update, and delete wiki markdown pages.
Each page is a markdown file with YAML frontmatter.
Maintains index.md and log.md automatically.
"""
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from models.schemas import Source, ConfidenceTier

WIKI_PATH = Path(os.getenv("WIKI_PATH", "./obsidian-vault/wiki"))
RAW_PATH = Path(os.getenv("RAW_PATH", "./obsidian-vault/raw"))
UPLOADS_PATH = Path(os.getenv("UPLOADS_PATH", "./obsidian-vault/uploads"))


def init_vault():
    """Create vault folder structure if it doesn't exist."""
    for p in [WIKI_PATH, RAW_PATH, UPLOADS_PATH]:
        p.mkdir(parents=True, exist_ok=True)
    if not (WIKI_PATH / "index.md").exists():
        write_index([])
    if not (WIKI_PATH / "log.md").exists():
        (WIKI_PATH / "log.md").write_text("# Sensei Wiki — Operation Log\n\n")


def concept_to_filename(concept: str) -> str:
    return re.sub(r'[^\w\s-]', '', concept).strip().replace(' ', '_') + ".md"


def write_wiki_page(concept: str, content: str, sources: list[Source],
                     confidence: float, tier: ConfidenceTier) -> str:
    """Write or overwrite a wiki concept page."""
    filename = concept_to_filename(concept)
    filepath = WIKI_PATH / filename

    source_list = "\n".join([
        f"  - title: \"{s.title}\"\n"
        f"    url: \"{s.url or s.file_path}\"\n"
        f"    confidence: {s.final_confidence}\n"
        f"    tier: {s.confidence_tier}"
        for s in sources
    ])

    frontmatter = f"""---
concept: {concept}
confidence: {confidence}
confidence_tier: {tier}
last_updated: {datetime.now().isoformat()}
sources:
{source_list}
---

"""
    full_content = frontmatter + content
    filepath.write_text(full_content, encoding="utf-8")

    append_log(f"compile | {concept} | confidence={confidence:.2f} | "
               f"sources={len(sources)}")
    rebuild_index()
    return str(filepath)


def read_wiki_page(concept: str) -> Optional[str]:
    filename = concept_to_filename(concept)
    filepath = WIKI_PATH / filename
    if filepath.exists():
        return filepath.read_text(encoding="utf-8")
    return None


def append_note_to_page(concept: str, note: str, source: str = "voice_note") -> bool:
    """Append a voice note to an existing wiki page."""
    content = read_wiki_page(concept)
    if not content:
        return False
    filename = concept_to_filename(concept)
    filepath = WIKI_PATH / filename
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    note_block = f"\n\n> **Note ({timestamp}):** {note}\n> *Source: {source}*\n"
    filepath.write_text(content + note_block, encoding="utf-8")
    append_log(f"note | {concept} | {note[:60]}...")
    return True


def insert_into_section(concept: str, section: str, text: str) -> bool:
    """Insert text at the end of a named section in a wiki page.
    Falls back to append if section not found."""
    content = read_wiki_page(concept)
    if not content:
        return False
    filename = concept_to_filename(concept)
    filepath = WIKI_PATH / filename

    # Find the heading line (## Section or ### Section, case-insensitive)
    lines = content.split("\n")
    insert_at = None
    section_lower = section.lower().strip()
    for i, line in enumerate(lines):
        if re.match(r"^#{1,4}\s+", line):
            heading_text = re.sub(r"^#{1,4}\s+", "", line).strip().lower()
            if heading_text == section_lower:
                insert_at = i
                break

    if insert_at is None:
        # Section not found — append to end
        return append_note_to_page(concept, text)

    # Find the end of this section (next heading or EOF)
    end_at = len(lines)
    for i in range(insert_at + 1, len(lines)):
        if re.match(r"^#{1,4}\s+", lines[i]):
            end_at = i
            break

    # Insert a clean sentence at the end of the section (before the next heading)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.insert(end_at, f"\n{text}  *(added {timestamp})*\n")
    filepath.write_text("\n".join(lines), encoding="utf-8")
    append_log(f"section_edit | {concept} | {section} | {text[:60]}")
    return True


def delete_source_from_page(concept: str, source_url: str) -> bool:
    """Remove a source reference from a wiki page frontmatter."""
    content = read_wiki_page(concept)
    if not content:
        return False
    updated = re.sub(
        rf'  - title:.*?\n(?:    .*?\n)*.*?{re.escape(source_url)}.*?\n(?:    .*?\n)*',
        '', content
    )
    filename = concept_to_filename(concept)
    (WIKI_PATH / filename).write_text(updated, encoding="utf-8")
    append_log(f"remove_source | {concept} | {source_url}")
    return True


def delete_wiki_page(concept: str) -> bool:
    filename = concept_to_filename(concept)
    filepath = WIKI_PATH / filename
    if filepath.exists():
        filepath.unlink()
        rebuild_index()
        append_log(f"delete | {concept}")
        return True
    return False


def list_wiki_pages() -> list[dict]:
    pages = []
    for f in WIKI_PATH.glob("*.md"):
        if f.name in ("index.md", "log.md"):
            continue
        content = f.read_text(encoding="utf-8")
        concept_match = re.search(r'^concept:\s*(.+)$', content, re.MULTILINE)
        conf_match = re.search(r'^confidence:\s*(.+)$', content, re.MULTILINE)
        tier_match = re.search(r'^confidence_tier:\s*(.+)$', content, re.MULTILINE)
        pages.append({
            "concept": concept_match.group(1).strip() if concept_match else f.stem,
            "confidence": float(conf_match.group(1).strip()) if conf_match else 0.5,
            "tier": tier_match.group(1).strip() if tier_match else "medium",
            "file": str(f),
        })
    return pages


def _extract_summary(content: str) -> str:
    """Extract a one-line summary from wiki page content (skip frontmatter + headers)."""
    # Strip YAML frontmatter
    body = re.sub(r'^---.*?---\s*', '', content, flags=re.DOTALL).strip()
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith('#') and not line.startswith('[[') and len(line) > 20:
            return line[:160].rstrip('.,;') + '.'
    return ""


def rebuild_index():
    """Rebuild index.md with rich per-page summaries for the Karpathy LLM Wiki pattern."""
    pages = list_wiki_pages()
    lines = [
        "# Sensei Wiki — Index\n\n",
        f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*  \n",
        f"*{len(pages)} concept pages*\n\n",
        "---\n\n",
    ]

    # Group by topic prefix if page names share a common parenthetical topic
    # Otherwise list all pages with summaries
    for p in sorted(pages, key=lambda x: x["concept"]):
        fn_stem = concept_to_filename(p["concept"])[:-3]  # strip .md
        raw_content = read_wiki_page(p["concept"]) or ""
        summary = _extract_summary(raw_content)
        tier_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(p["tier"], "⚪")
        summary_str = f" — {summary}" if summary else ""
        lines.append(f"- [[{fn_stem}]] {tier_icon}{summary_str}\n")

    lines.append("\n")
    (WIKI_PATH / "index.md").write_text("".join(lines), encoding="utf-8")


def append_log(entry: str):
    log_path = WIKI_PATH / "log.md"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n## [{timestamp}] {entry}\n")


def get_index_content() -> str:
    index_path = WIKI_PATH / "index.md"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return ""


def save_raw_source(title: str, content: str, source_id: str) -> str:
    """Save a raw source to raw/ folder (immutable)."""
    filename = re.sub(r'[^\w\s-]', '', title)[:50].strip().replace(' ', '_')
    filepath = RAW_PATH / f"{source_id}_{filename}.md"
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


def write_index(pages: list):
    """Write an empty index.md."""
    content = "# Sensei Wiki — Index\n\n*No pages yet.*\n"
    (WIKI_PATH / "index.md").write_text(content, encoding="utf-8")
