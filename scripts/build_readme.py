#!/usr/bin/env python3
"""Generate README.md from papers.yaml and templates/README.header.md.

Usage:
    python scripts/build_readme.py            # writes README.md
    python scripts/build_readme.py --check    # exit 1 if README.md is out of date (used in CI)
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PAPERS = ROOT / "papers.yaml"
TEMPLATE = ROOT / "templates" / "README.header.md"
README = ROOT / "README.md"
ABSTRACTS = ROOT / "data" / "abstracts.json"

REQUIRED = ("id", "title", "authors", "year", "venue", "category")
LAYOUTS = {"method", "benchmark", "plain", "model"}


# ----------------------------------------------------------------------------- helpers
def github_slug(text: str) -> str:
    """Approximate GitHub's heading -> anchor algorithm."""
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]+", "", text)  # drop punctuation (keeps letters, digits, _, -, space)
    return text.replace(" ", "-")


def cell(s: str | None) -> str:
    if not s:
        return ""
    return str(s).replace("|", "\\|").replace("\n", " ").strip()


def paper_link(p: dict) -> str:
    if p.get("arxiv"):
        return f"https://arxiv.org/abs/{p['arxiv']}"
    return p.get("url") or ""


def links(p: dict) -> str:
    out = []
    if p.get("arxiv"):
        out.append(f"[arXiv](https://arxiv.org/abs/{p['arxiv']})")
    elif p.get("url"):
        out.append(f"[Paper]({p['url']})")
    if p.get("code"):
        out.append(f"[Code]({p['code']})")
    if p.get("corpus_url"):
        out.append(f"[Corpus]({p['corpus_url']})")
    return " · ".join(out)


ABSTRACT_CACHE: dict = {}


def abstract_of(p: dict) -> str:
    """Abstract text from data/abstracts.json (keyed by arXiv id, else by entry id), or ''."""
    rec = ABSTRACT_CACHE.get(p.get("arxiv") or "") or ABSTRACT_CACHE.get(p["id"]) or {}
    return re.sub(r"\s+", " ", rec.get("abstract", "")).strip()


def title_cell(p: dict, label_key: str = "title") -> str:
    url = paper_link(p)
    title = cell(p[label_key])
    head = f"[{title}]({url})" if url else title
    out = f"{head}<br><sub>{cell(p.get('authors'))}</sub>"
    badges = tag_badges(p)
    if badges:
        out += f"<br>{badges}"
    abstract = abstract_of(p)
    if abstract:
        out += f"<details><summary><sub>Abstract</sub></summary><sub>{cell(html.escape(abstract, quote=False))}</sub></details>"
    return out


def arxiv_month(p: dict) -> str:
    a = p.get("arxiv") or ""
    m = re.match(r"^(\d{2})(\d{2})\.\d{4,5}$", a)
    if m:
        return f"20{m.group(1)}-{m.group(2)}"
    return str(p.get("year", ""))


TAGS: dict = {}


def badge(tag: str, value: str) -> str:
    """A flat shields.io badge, coloured per papers.yaml `tags`."""
    spec = (TAGS.get(tag) or {}).get("values", {}).get(value)
    if not spec:
        return f"`{value}`"
    label = (TAGS[tag].get("label") or tag).lower()
    enc = lambda x: x.replace("-", "--").replace("_", "__").replace(" ", "_")
    return f"![{label}: {value}](https://img.shields.io/badge/{enc(label)}-{enc(value)}-{spec['color']}?style=flat-square)"


def tag_badges(p: dict) -> str:
    if not (p.get("level") or p.get("access")):
        return ""
    return " ".join(badge(t, p[t]) for t in ("level", "access", "domain") if p.get(t))


def render_legend() -> str:
    lines = ["| Tag | Meaning |", "|---|---|"]
    for tag, spec in TAGS.items():
        for value, v in spec.get("values", {}).items():
            lines.append(f"| {badge(tag, value)} | {cell(v.get('meaning'))} |")
    return "\n".join(lines)


# ----------------------------------------------------------------------------- validation
def validate(data: dict) -> list[str]:
    errors: list[str] = []
    cats = {c["key"]: c for c in data.get("categories", [])}
    for c in cats.values():
        if c.get("layout", "method") not in LAYOUTS:
            errors.append(f"category {c['key']}: unknown layout {c.get('layout')}")
    seen_ids: set[str] = set()
    seen_arxiv: set[str] = set()
    for p in data.get("papers", []):
        pid = p.get("id", "<missing id>")
        for k in REQUIRED:
            if not p.get(k) and p.get(k) != 0:
                errors.append(f"{pid}: missing field '{k}'")
        if pid in seen_ids:
            errors.append(f"duplicate id: {pid}")
        seen_ids.add(pid)
        a = (p.get("arxiv") or "").strip()
        if a:
            if not re.match(r"^\d{4}\.\d{4,5}$", a):
                errors.append(f"{pid}: malformed arXiv id '{a}' (use YYMM.NNNNN without version)")
            if a in seen_arxiv:
                errors.append(f"{pid}: duplicate arXiv id {a}")
            seen_arxiv.add(a)
        elif not p.get("url"):
            errors.append(f"{pid}: needs either 'arxiv' or 'url'")
        if p.get("category") not in cats:
            errors.append(f"{pid}: unknown category '{p.get('category')}'")
        for tag in ("level", "access", "domain"):
            allowed = set((data.get("tags", {}).get(tag) or {}).get("values", {}))
            if p.get(tag) and allowed and p[tag] not in allowed:
                errors.append(f"{pid}: {tag} must be one of {sorted(allowed)} (declare new values under `tags:` first)")
    return errors


# ----------------------------------------------------------------------------- rendering
def h(text) -> str:
    """Escape text for an HTML cell and render the little markdown we use in notes (`code`, *em*, **strong**)."""
    t = html.escape(re.sub(r"\s+", " ", str(text or "")).strip(), quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", t)
    return t


def html_links(p: dict) -> str:
    out = []
    if p.get("arxiv"):
        out.append(f'<a href="https://arxiv.org/abs/{p["arxiv"]}">arXiv</a>')
    elif p.get("url"):
        out.append(f'<a href="{html.escape(p["url"])}">Paper</a>')
    if p.get("code"):
        out.append(f'<a href="{html.escape(p["code"])}">Code</a>')
    if p.get("corpus_url"):
        out.append(f'<a href="{html.escape(p["corpus_url"])}">Corpus</a>')
    return " · ".join(out)


def html_badges(p: dict) -> str:
    if not (p.get("level") or p.get("access")):
        return ""
    imgs = []
    for tag in ("level", "access", "domain"):
        v = p.get(tag)
        spec = (TAGS.get(tag) or {}).get("values", {}).get(v) if v else None
        if not spec:
            continue
        label = (TAGS[tag].get("label") or tag).lower()
        enc = lambda x: x.replace("-", "--").replace("_", "__").replace(" ", "_")
        imgs.append(f'<img alt="{label}: {v}" src="https://img.shields.io/badge/{enc(label)}-{enc(v)}-{spec["color"]}?style=flat-square">')
    return " ".join(imgs)


def html_paper_cell(p: dict) -> str:
    url = paper_link(p)
    title = h(p["title"])
    head = f'<a href="{html.escape(url)}">{title}</a>' if url else title
    out = f"{head}<br><sub>{h(p.get('authors'))}</sub>"
    badges = html_badges(p)
    if badges:
        out += f"<br>{badges}"
    return out


def html_abstract_row(p: dict, ncols: int) -> str:
    abstract = abstract_of(p)
    if not abstract:
        return ""
    return f'<tr><td colspan="{ncols}"><details><summary><sub>Abstract</sub></summary><sub>{h(abstract)}</sub></details></td></tr>'


LAYOUTS_HTML = {
    # layout: (header cells with width hints, row-builder)
    "method": (
        ['<th width="5%">Year</th>', '<th width="30%">Paper</th>', '<th width="8%">Venue</th>',
         '<th width="24%">Signal</th>', '<th width="26%">Transfer to TSFMs</th>', '<th width="7%">Links</th>'],
        lambda p: [str(p["year"]), html_paper_cell(p), h(p["venue"]), h(p.get("signal")), h(p.get("transfer") or p.get("note")), html_links(p)],
    ),
    "model": (
        ['<th width="7%">arXiv v1</th>', '<th width="10%">Model</th>', '<th width="26%">Paper</th>', '<th width="8%">Venue</th>',
         '<th width="24%">Documented pretraining corpus</th>', '<th width="17%">Output / note</th>', '<th width="8%">Links</th>'],
        lambda p: [arxiv_month(p), f"<strong>{h(p.get('model') or p['title'])}</strong>", html_paper_cell(p), h(p["venue"]), h(p.get("corpus")), h(p.get("note")), html_links(p)],
    ),
    "benchmark": (
        ['<th width="5%">Year</th>', '<th width="34%">Paper</th>', '<th width="9%">Venue</th>', '<th width="44%">Leakage handling / note</th>', '<th width="8%">Links</th>'],
        lambda p: [str(p["year"]), html_paper_cell(p), h(p["venue"]), h(p.get("note") or p.get("transfer")), html_links(p)],
    ),
    "plain": (
        ['<th width="5%">Year</th>', '<th width="34%">Paper</th>', '<th width="9%">Venue</th>', '<th width="44%">Takeaway</th>', '<th width="8%">Links</th>'],
        lambda p: [str(p["year"]), html_paper_cell(p), h(p["venue"]), h(p.get("note") or p.get("transfer")), html_links(p)],
    ),
}


def render_table(layout: str, papers: list[dict]) -> str:
    """One HTML table per section. HTML (rather than a markdown table) lets the abstract sit in a
    full-width collapsible row under each entry. No blank lines inside: a blank line would end
    the HTML block for the markdown renderer."""
    headers, row = LAYOUTS_HTML.get(layout, LAYOUTS_HTML["plain"])
    n = len(headers)
    lines = ["<table>", "<thead><tr>" + "".join(headers) + "</tr></thead>", "<tbody>"]
    for p in papers:
        cells = "".join(f"<td>{c}</td>" for c in row(p))
        lines.append(f"<tr>{cells}</tr>")
        ab = html_abstract_row(p, n)
        if ab:
            lines.append(ab)
    lines += ["</tbody>", "</table>"]
    return "\n".join(lines)


def build(data: dict) -> str:
    global TAGS, ABSTRACT_CACHE
    TAGS = data.get("tags") or {}
    ABSTRACT_CACHE = json.loads(ABSTRACTS.read_text(encoding="utf-8")) if ABSTRACTS.exists() else {}
    cats = data["categories"]
    papers = data["papers"]
    by_cat: dict[str, list[dict]] = {c["key"]: [] for c in cats}
    for p in papers:
        by_cat[p["category"]].append(p)

    def sort_key(p: dict):
        # newest first; within a year keep arXiv order (roughly chronological), then title
        return (-int(p["year"]), -(int(p["arxiv"].replace(".", "")) if p.get("arxiv") else 0), p["title"].lower())

    toc_lines, sections = [], []
    for c in cats:
        ps = sorted(by_cat[c["key"]], key=sort_key)
        if not ps:
            continue
        heading = f"{c['emoji']} {c['title']}" if c.get("emoji") else c["title"]
        # explicit anchor (the category key) so links do not depend on how GitHub slugs emoji headings
        toc_lines.append(f"- [{heading}](#{c['key']}) ({len(ps)})")
        block = [f'<a id="{c["key"]}"></a>', f"## {heading}", ""]
        if c.get("description"):
            block += [c["description"].strip(), ""]
        block += [render_table(c.get("layout", "method"), ps), ""]
        sections.append("\n".join(block))

    template = TEMPLATE.read_text(encoding="utf-8")
    out = (
        template.replace("{{TOC}}", "\n".join(toc_lines))
        .replace("{{LEGEND}}", render_legend())
        .replace("{{SECTIONS}}", "\n".join(sections).rstrip() + "\n")
        .replace("{{N_PAPERS}}", str(len(papers)))
        .replace("{{DATE}}", dt.date.today().isoformat())
        .replace("{{REPO}}", data.get("repo", "OWNER/REPO"))
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if README.md differs from the generated output (ignores the date badge)")
    args = ap.parse_args()

    data = yaml.safe_load(PAPERS.read_text(encoding="utf-8"))
    errors = validate(data)
    if errors:
        print("papers.yaml has problems:", file=sys.stderr)
        for e in errors:
            print("  -", e, file=sys.stderr)
        return 1

    out = build(data)
    if args.check:
        strip = lambda s: re.sub(r"updated-\d{4}-\d{2}-\d{2}", "updated-DATE", s)
        current = README.read_text(encoding="utf-8") if README.exists() else ""
        if strip(current) != strip(out):
            print("README.md is out of date — run: python scripts/build_readme.py", file=sys.stderr)
            return 1
        print("README.md is up to date.")
        return 0

    README.write_text(out, encoding="utf-8")
    print(f"Wrote {README.relative_to(ROOT)} ({len(data['papers'])} papers, {sum(1 for c in data['categories'])} categories)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
