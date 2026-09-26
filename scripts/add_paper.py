#!/usr/bin/env python3
"""Append a paper stub to papers.yaml from its arXiv id.

    python scripts/add_paper.py 2410.10880 --category llm-finetune
    python scripts/add_paper.py 2410.10880 --category llm-finetune --domain llm --level sample --access white-box \
        --code https://github.com/... --transfer "LoRA-fine-tune the TSFM on post-release series ..."

Fetches title / authors / year from the arXiv API, writes a YAML block at the end of papers.yaml,
and prints it so you can fill in the remaining fields. Run scripts/build_readme.py afterwards.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arxiv_api  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PAPERS = ROOT / "papers.yaml"
ABSTRACTS = ROOT / "data" / "abstracts.json"


def slugify(title: str, arxiv_id: str) -> str:
    words = re.findall(r"[a-z0-9]+", title.lower())
    stop = {"a", "an", "the", "of", "for", "in", "on", "to", "and", "with", "via", "from", "is", "are", "by", "large", "language", "models", "model"}
    words = [w for w in words if w not in stop][:4]
    return "-".join(words) or arxiv_id.replace(".", "-")


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("arxiv_id", help="arXiv id, e.g. 2410.10880 (version suffix is ignored)")
    ap.add_argument("--category", required=True, help="category key from papers.yaml")
    ap.add_argument("--id", dest="slug", default=None, help="entry id (default: derived from the title)")
    ap.add_argument("--domain", default=None, choices=["ts", "llm", "ml"])
    ap.add_argument("--level", default="", choices=["", "sample", "dataset", "both"])
    ap.add_argument("--access", default="", choices=["", "black-box", "grey-box", "white-box"])
    ap.add_argument("--venue", default=None, help='override venue (default: "arXiv <year>")')
    ap.add_argument("--code", default="")
    ap.add_argument("--signal", default="")
    ap.add_argument("--transfer", default="")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    data = yaml.safe_load(PAPERS.read_text(encoding="utf-8"))
    cats = {c["key"] for c in data["categories"]}
    if args.category not in cats:
        print(f"unknown category '{args.category}'. Known keys: {', '.join(sorted(cats))}", file=sys.stderr)
        return 2
    arxiv_id = re.sub(r"v\d+$", "", args.arxiv_id.strip())
    if any(p.get("arxiv") == arxiv_id for p in data["papers"]):
        print(f"{arxiv_id} is already in papers.yaml", file=sys.stderr)
        return 1

    e = arxiv_api.fetch_by_id(arxiv_id)
    if e is None:
        print(f"arXiv id {arxiv_id} not found", file=sys.stderr)
        return 1

    slug = args.slug or slugify(e.title, arxiv_id)
    existing = {p["id"] for p in data["papers"]}
    base, n = slug, 2
    while slug in existing:
        slug, n = f"{base}-{n}", n + 1

    year = int(e.published[:4])
    authors = ", ".join(e.authors[:3]) + (", et al." if len(e.authors) > 3 else "")
    domain = args.domain or ("ts" if "time series" in (e.title + e.abstract).lower() or "time-series" in (e.title + e.abstract).lower() else "llm")
    layout = next(c.get("layout", "method") for c in data["categories"] if c["key"] == args.category)

    lines = [
        "",
        f"  - id: {slug}",
        f"    title: {q(e.title)}",
        f"    authors: {q(authors)}",
        f"    year: {year}",
        f"    venue: {q(args.venue or ('arXiv ' + str(year)))}",
        f"    arxiv: {q(arxiv_id)}",
        f"    code: {q(args.code)}",
        f"    category: {args.category}",
        f"    domain: {domain}",
    ]
    if layout == "method":
        lines += [
            f"    level: {args.level}".rstrip(),
            f"    access: {args.access}".rstrip(),
            f"    signal: {q(args.signal)}",
            f"    transfer: {q(args.transfer)}",
        ]
    elif layout == "model":
        lines += [
            f"    model: {q('')}",
            f"    corpus: {q('')}",
            f"    corpus_url: {q('')}",
            f"    note: {q(args.note)}",
        ]
    else:
        lines += [f"    note: {q(args.note or args.transfer)}"]
    block = "\n".join(lines) + "\n"

    text = PAPERS.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    PAPERS.write_text(text + block, encoding="utf-8")

    # keep the abstract so README.md can fold it under the title
    if e.abstract:
        store = json.loads(ABSTRACTS.read_text(encoding="utf-8")) if ABSTRACTS.exists() else {}
        store[arxiv_id] = {"title": e.title, "abstract": e.abstract, "source": "api"}
        ABSTRACTS.parent.mkdir(exist_ok=True)
        ABSTRACTS.write_text(json.dumps(store, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(block)
    print(f"Appended to {PAPERS.relative_to(ROOT)}. Fill in the empty fields, then run: python scripts/build_readme.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
