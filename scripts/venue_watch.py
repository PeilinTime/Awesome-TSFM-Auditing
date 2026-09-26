#!/usr/bin/env python3
"""Propose venue updates for papers whose venue is still "arXiv <year>".

    python scripts/venue_watch.py             # rewrite venues in papers.yaml, write data/venue_report.md
    python scripts/venue_watch.py --dry-run   # print the proposals, change nothing

For every entry with an arXiv id and a venue starting with "arXiv", the current arXiv record is
fetched (search API first, OAI-PMH GetRecord when the API rejects the client). A venue is proposed
from the record's journal-ref field, or from an acceptance note in the comments field ("Accepted at
ICLR 2026", "To appear in NeurIPS 2025 (spotlight)", ...). Comments that only mention a submission
("under review at ...", "submitted to ...") are ignored. The proposals are applied to papers.yaml and
summarised in data/venue_report.md; the monthly workflow turns that into a pull request for review.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arxiv_api  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PAPERS = ROOT / "papers.yaml"
REPORT = ROOT / "data" / "venue_report.md"

# canonical name -> pattern (case-insensitive, matched on word boundaries)
VENUES = {
    "NeurIPS": r"neurips|nips|neural information processing systems",
    "ICML": r"icml|international conference on machine learning",
    "ICLR": r"iclr|international conference on learning representations",
    "AAAI": r"aaai",
    "IJCAI": r"ijcai",
    "KDD": r"\bkdd\b|sigkdd",
    "WWW": r"\bwww\b|the web conference",
    "CIKM": r"cikm",
    "WSDM": r"wsdm",
    "SDM": r"\bsdm\b",
    "ICDE": r"icde",
    "SIGMOD": r"sigmod",
    "VLDB": r"vldb",
    "ACL": r"\bacl\b|association for computational linguistics",
    "EMNLP": r"emnlp",
    "NAACL": r"naacl",
    "COLING": r"coling",
    "COLM": r"\bcolm\b|conference on language modeling",
    "AISTATS": r"aistats",
    "UAI": r"\buai\b",
    "ECML-PKDD": r"ecml",
    "CVPR": r"cvpr",
    "ICCV": r"iccv",
    "ECCV": r"eccv",
    "IEEE S&P": r"ieee s&p|symposium on security and privacy|\boakland\b",
    "ACM CCS": r"\bccs\b|computer and communications security",
    "USENIX Security": r"usenix security",
    "NDSS": r"ndss",
    "SaTML": r"satml",
    "CSF": r"\bcsf\b",
    "TMLR": r"\btmlr\b|transactions on machine learning research",
    "JMLR": r"\bjmlr\b|journal of machine learning research",
    "TKDE": r"\btkde\b|transactions on knowledge and data engineering",
    "TPAMI": r"\btpami\b|pattern analysis and machine intelligence",
    "TIFS": r"\btifs\b|information forensics and security",
    "TNNLS": r"\btnnls\b",
    "ACML": r"\bacml\b",
    "MLSys": r"mlsys",
    "Nature": r"\bnature\b",
}
ACCEPTED = re.compile(r"accept|to appear|appears? in|published|camera[- ]ready|proceedings|oral|spotlight|poster|main conference|findings", re.I)
NOT_ACCEPTED = re.compile(r"under review|submitted|in submission|rejected|withdrawn|preprint only", re.I)
YEAR = re.compile(r"(20\d{2})|'(\d{2})\b")


def venue_from_text(text: str, fallback_year: int | None) -> tuple[str, str] | None:
    """Return (venue string, matched venue name) or None."""
    t = text.strip()
    if not t:
        return None
    for name, pat in VENUES.items():
        m = re.search(pat, t, re.I)
        if not m:
            continue
        window = t[max(0, m.start() - 40): m.end() + 40]
        ym = YEAR.search(window)
        year = ym.group(1) or ("20" + ym.group(2)) if ym else (str(fallback_year) if fallback_year else "")
        venue = f"{name} {year}".strip()
        if re.search(r"findings", window, re.I) and name in {"ACL", "EMNLP", "NAACL"}:
            venue = f"Findings of {venue}"
        elif re.search(r"workshop", window, re.I):
            venue = f"{venue} Workshop"
        return venue, name
    return None


def propose(entry: arxiv_api.Entry, paper: dict) -> tuple[str, str] | None:
    """(new venue, evidence) if the record supports one, else None."""
    if entry.journal_ref:
        got = venue_from_text(entry.journal_ref, None)
        if got:
            return got[0], f"journal-ref: {entry.journal_ref}"
        return re.sub(r"\s+", " ", entry.journal_ref)[:80], f"journal-ref: {entry.journal_ref}"
    c = entry.comment
    if c and ACCEPTED.search(c) and not NOT_ACCEPTED.search(c):
        got = venue_from_text(c, None)
        if got:
            return got[0], f"comments: {c}"
    return None


def fetch(arxiv_id: str, api_ok: list[bool]) -> arxiv_api.Entry | None:
    if api_ok[0]:
        try:
            e = arxiv_api.fetch_by_id(arxiv_id)
            if e:
                return e
        except Exception as ex:  # noqa: BLE001
            api_ok[0] = False
            print(f"  search API failed ({type(ex).__name__}); using OAI-PMH from now on", file=sys.stderr)
    return arxiv_api.oai_get_record(arxiv_id)


def set_venue(text: str, pid: str, new_venue: str) -> str:
    """Replace the venue line inside one entry of papers.yaml, keeping everything else byte-identical."""
    m = re.search(rf'(?ms)^  - id: {re.escape(pid)}\n(.*?)(?=^  - id: |^  # -{{20,}}|\Z)', text)
    assert m, pid
    block = m.group(0)
    new_block, n = re.subn(r'(?m)^(    venue: )"[^"\n]*"', lambda mm: f'{mm.group(1)}"{new_venue}"', block, count=1)
    assert n == 1, f"venue line not found for {pid}"
    return text[:m.start()] + new_block + text[m.end():]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    text = PAPERS.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    todo = [p for p in data["papers"] if p.get("arxiv") and str(p.get("venue", "")).lower().startswith("arxiv")]
    print(f"{len(todo)} paper(s) still listed as arXiv-only", file=sys.stderr)

    api_ok = [True]
    changes: list[tuple[dict, str, str]] = []
    failed: list[str] = []
    for p in todo:
        try:
            e = fetch(p["arxiv"], api_ok)
        except Exception as ex:  # noqa: BLE001
            failed.append(f"{p['arxiv']} ({type(ex).__name__})")
            continue
        if e is None:
            failed.append(p["arxiv"])
            continue
        got = propose(e, p)
        if got:
            changes.append((p, got[0], got[1]))
            print(f"  {p['id']}: {p['venue']} -> {got[0]}   [{got[1][:90]}]", file=sys.stderr)

    today = dt.date.today().isoformat()
    lines = [f"# Venue check {today}", "",
             f"Checked {len(todo)} arXiv-only entries; {len(changes)} proposed update(s); {len(failed)} fetch failure(s).", ""]
    if changes:
        lines += ["| Entry | Current | Proposed | Evidence (arXiv record) |", "|---|---|---|---|"]
        for p, v, ev in changes:
            lines.append(f"| `{p['id']}` ([{p['arxiv']}](https://arxiv.org/abs/{p['arxiv']})) | {p['venue']} | **{v}** | {ev.replace('|', '/')} |")
        lines += ["", "Venue names are derived from free-text arXiv comments; check each one before merging, and edit the `venue:` line in `papers.yaml` on this branch if the wording should differ."]
    if failed:
        lines += ["", "Could not fetch: " + ", ".join(failed)]
    report = "\n".join(lines) + "\n"

    if args.dry_run:
        print(report)
        return 0
    for p, v, _ in changes:
        text = set_venue(text, p["id"], v)
    PAPERS.write_text(text, encoding="utf-8")
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    gh_out = __import__("os").environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"count={len(changes)}\ndate={today}\n")
    print(f"[done] {len(changes)} venue update(s) written", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
