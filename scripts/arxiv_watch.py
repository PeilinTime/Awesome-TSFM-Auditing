#!/usr/bin/env python3
"""Weekly arXiv watch for Awesome-TSFM-Auditing.

1. Queries the arXiv API with keyword combinations (time series x auditing, and
   foundation-model auditing methods that may transfer to time series). If the arXiv
   search API is unavailable (it intermittently answers HTTP 406 to automated clients),
   falls back to harvesting arXiv's OAI-PMH feed for the cs/stat sets, and then to OpenAlex.
2. Keeps submissions inside the look-back window (default: since the last run,
   with a 3-day overlap; 60 days on the first run).
3. Removes anything already listed in papers.yaml or already proposed (data/seen.json).
4. Scores relevance by keyword hits, assigns Tier A (time-series specific) or
   Tier B (foundation-model auditing; check transferability), and writes
   candidates/<date>.md, the body of the review pull request.

Nothing is added to the list automatically; a human merges the PR after review.

Usage:
    python scripts/arxiv_watch.py                 # normal run (writes candidates/, data/)
    python scripts/arxiv_watch.py --days 30       # explicit look-back window
    python scripts/arxiv_watch.py --dry-run       # print the report, write nothing
    python scripts/arxiv_watch.py --fixture f.xml # parse a saved Atom feed instead of calling arXiv (tests)
    python scripts/arxiv_watch.py --source oai    # force one source: api | oai | openalex
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arxiv_api  # noqa: E402
import openalex_api  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PAPERS = ROOT / "papers.yaml"
SEEN = ROOT / "data" / "seen.json"
STATE = ROOT / "data" / "state.json"
LAST_RUN = ROOT / "data" / "last_run.json"
CANDIDATES = ROOT / "candidates"

CATS = "(cat:cs.LG OR cat:cs.CL OR cat:cs.CR OR cat:cs.AI OR cat:stat.ML OR cat:cs.DB)"
TS = '(abs:"time series" OR abs:"time-series" OR ti:"time series" OR ti:forecasting)'
FM = '(abs:"foundation model" OR abs:"foundation models" OR abs:"language model" OR abs:"language models" OR abs:LLM OR abs:LLMs)'
AUDIT_STRONG = (
    '(abs:"membership inference" OR abs:"pretraining data" OR abs:"pre-training data" OR '
    'abs:"training data detection" OR abs:"data contamination" OR abs:"benchmark contamination" OR '
    'abs:"test set contamination" OR abs:"dataset inference" OR abs:"data leakage" OR abs:"information leakage")'
)
AUDIT_WEAK = '(abs:memorization OR abs:memorisation OR abs:"lookahead bias" OR abs:"look-ahead bias" OR abs:contamination OR abs:leakage OR abs:auditing)'

# (name, query): each query is run once per watch
QUERIES = [
    ("ts x audit (strong)", f"{TS} AND {AUDIT_STRONG} AND {CATS}"),
    ("ts x audit (weak)", f"{TS} AND {AUDIT_WEAK} AND {CATS}"),
    ("tsfm x leakage/eval", f'(abs:"time series foundation" OR abs:"time-series foundation" OR abs:TSFM OR abs:TSFMs) AND (abs:leakage OR abs:contamination OR abs:memorization OR abs:audit OR abs:auditing OR abs:benchmark) AND {CATS}'),
    ("fm x membership/pretraining-data", f'(abs:"membership inference" OR abs:"pretraining data detection" OR abs:"pre-training data detection" OR abs:"training data detection" OR abs:"dataset inference") AND {FM} AND {CATS}'),
]

# OpenAlex full-text queries (fallback source; quotes and AND/OR are supported)
OPENALEX_QUERIES = [
    ("openalex: ts x audit", '"time series" AND ("membership inference" OR "data contamination" OR "pretraining data" OR "pre-training data" OR "training data detection" OR "dataset inference" OR "information leakage" OR "data leakage" OR memorization)'),
    ("openalex: tsfm", '("time series foundation model" OR "time series foundation models") AND (leakage OR contamination OR memorization OR audit OR auditing OR benchmark)'),
    ("openalex: fm x membership", '("foundation model" OR "language model" OR "language models") AND ("membership inference" OR "pretraining data detection" OR "pre-training data detection" OR "training data detection" OR "dataset inference")'),
]
OAI_SETS = ("cs", "stat")

# keyword scoring (lower-cased substring matches on title + abstract; title hits count double)
TS_TERMS = ["time series", "time-series", "forecasting", "forecaster", "temporal data", "sequence model"]
FM_TERMS = ["foundation model", "language model", "llm", "pretrained", "pre-trained", "pretraining", "pre-training"]
AUDIT_TERMS = {
    "membership inference": 3, "pretraining data detection": 3, "pre-training data detection": 3,
    "detecting pretraining data": 3, "detecting pre-training data": 3, "detect pretraining data": 3, "detect pre-training data": 3,
    "training data identification": 3,
    "training data detection": 3, "dataset inference": 3, "data contamination": 3, "benchmark contamination": 3,
    "test set contamination": 3, "pretraining data": 2, "pre-training data": 2, "contamination": 2,
    "information leakage": 2, "data leakage": 2, "leakage-free": 2, "leakage": 1,
    "memorization": 1, "memorisation": 1, "lookahead bias": 2, "look-ahead bias": 2, "auditing": 1, "audit": 1,
    "provenance": 1, "watermark": 1, "copyright": 1, "unlearning": 1,
}
# generic words that also occur in unrelated contexts (cloud contamination, leakage current, financial audit ...):
# on their own they qualify a time-series paper only when a foundation/pretrained-model term is present too
WEAK_TERMS = {"contamination", "leakage", "audit", "auditing", "provenance"}
# Tier B is restricted to the pretraining-data auditing vocabulary. Benchmark contamination detection for
# LLM evaluation (prompt-based tests) is out of scope and is deliberately not matched here.
STRONG_FOR_TIER_B = {
    "membership inference", "pretraining data detection", "pre-training data detection", "training data detection",
    "detecting pretraining data", "detecting pre-training data", "detect pretraining data", "detect pre-training data",
    "training data identification", "dataset inference",
}


def _hits(text: str, terms) -> list[str]:
    hits = [t for t in terms if t in text]
    # drop terms that are substrings of a longer matched term ("contamination" vs "data contamination")
    return [t for t in hits if not any(t != u and t in u for u in hits)]


def score(e: arxiv_api.Entry) -> dict:
    title, abstract = e.title.lower(), e.abstract.lower()
    text = title + " " + abstract
    ts = _hits(text, TS_TERMS)
    fm = _hits(text, FM_TERMS)
    audit = _hits(text, AUDIT_TERMS)
    s = 0.0
    for t in audit:
        s += AUDIT_TERMS[t] * (2 if t in title else 1)
    s += sum(2 if t in title else 1 for t in ts)
    s += 0.5 * len(fm)
    strong = [t for t in audit if t not in WEAK_TERMS]
    if ts and (strong or (audit and fm)):
        tier = "A"
    elif fm and (set(audit) & STRONG_FOR_TIER_B):
        tier = "B"
    else:
        tier = None
    return {"tier": tier, "score": round(s, 1), "matched": sorted(set(ts + audit))}


def first_submitted_in_window(arxiv_id: str, since: dt.date) -> bool:
    """New-style ids encode the month of the first version (YYMM.NNNNN): use it to drop old papers
    that merely received a new version inside the window (the OAI feed reports the latest version date)."""
    m = re.match(r"^(\d{2})(\d{2})\.\d{4,5}$", arxiv_id)
    if not m:
        return True
    return (2000 + int(m.group(1)), int(m.group(2))) >= (since.year, since.month)


def load_listed_ids() -> set[str]:
    data = yaml.safe_load(PAPERS.read_text(encoding="utf-8"))
    return {p["arxiv"] for p in data.get("papers", []) if p.get("arxiv")}


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def fmt_authors(names: list[str]) -> str:
    return ", ".join(names[:3]) + (", et al." if len(names) > 3 else "")


def render_report(date: dt.date, since: dt.date, tiers: dict[str, list], stats: dict) -> str:
    lines = [
        f"# arXiv watch: {date.isoformat()}",
        "",
        f"Window: **{since.isoformat()} → {date.isoformat()}** · queries: {stats['queries']} · fetched: {stats['fetched']} · "
        f"in window: {stats['in_window']} · already listed/seen: {stats['dropped_seen']} · off-topic: {stats['dropped_offtopic']} · "
        f"**new candidates: {stats['new']}** (Tier A: {len(tiers['A'])}, Tier B: {len(tiers['B'])})",
        "",
        "Review checklist: does the paper audit/attack/evaluate the *training data* of a time-series model, or is it an LLM/ML method "
        "whose signal (loss, likelihood, embeddings, gradients, fine-tuning) a TSFM can provide? If yes, accept with",
        "",
        "```bash",
        "python scripts/add_paper.py <arXiv-id> --category <category-key>   # then fill in the transfer/note line",
        "python scripts/build_readme.py",
        "```",
        "",
    ]
    titles = {
        "A": "Tier A: time-series specific",
        "B": "Tier B: pretraining-data auditing methods for foundation models (check transferability)",
    }
    for tier in ("A", "B"):
        items = tiers[tier]
        lines += [f"## {titles[tier]} ({len(items)})", ""]
        if not items:
            lines += ["_none this week_", ""]
            continue
        for i, (e, sc) in enumerate(items, 1):
            if i > 25:  # keep the PR body readable
                lines.append(f"- [{e.arxiv_id}]({e.url}) {e.title} (score {sc['score']})")
                continue
            abstract = e.abstract if len(e.abstract) <= 700 else e.abstract[:700].rsplit(" ", 1)[0] + " …"
            lines += [
                f"### {i}. {e.title}",
                "",
                f"**arXiv:** [{e.arxiv_id}]({e.url}) · **submitted:** {e.published} · **categories:** {', '.join(e.categories)} · "
                f"**score:** {sc['score']} · **matched:** {', '.join(sc['matched'])}",
                "",
                f"**Authors:** {fmt_authors(e.authors)}" + (f" · **Comment:** {e.comment}" if e.comment else ""),
                "",
                f"> {abstract}",
                "",
            ]
        lines.append("")
    lines += ["---", "_Generated by `scripts/arxiv_watch.py`. Nothing is added to the list without review._", ""]
    return "\n".join(lines)


def fetch_source(src: str, since: dt.date, max_results: int) -> tuple[list[arxiv_api.Entry], list[dict]]:
    """Fetch candidate entries from one source. Returns (entries, per-query log)."""
    log: list[dict] = []
    out: list[arxiv_api.Entry] = []
    if src == "api":
        for name, q in QUERIES:
            try:
                res = arxiv_api.search(q, max_results=max_results)
            except Exception as ex:  # noqa: BLE001
                msg = f"{type(ex).__name__}: {ex}"[:300]
                print(f"[warn] query failed: {name}: {msg}", file=sys.stderr)
                log.append({"name": f"api: {name}", "results": 0, "error": msg})
                if not out:  # the API is evidently down for this run; do not burn the retry ladder on every query
                    break
                continue
            newest = max((e.published for e in res), default="")
            print(f"[query] {name}: {len(res)} results (newest {newest})", file=sys.stderr)
            log.append({"name": f"api: {name}", "results": len(res), "newest": newest})
            out.extend(res)
    elif src == "oai":
        try:
            res = arxiv_api.oai_harvest(since.isoformat(), sets=OAI_SETS)
        except Exception as ex:  # noqa: BLE001
            msg = f"{type(ex).__name__}: {ex}"[:300]
            print(f"[warn] OAI-PMH harvest failed: {msg}", file=sys.stderr)
            log.append({"name": f"oai: sets {','.join(OAI_SETS)} from {since}", "results": 0, "error": msg})
            return out, log
        # keep new submissions only (OAI 'from' also returns older papers that were merely updated)
        res = [e for e in res if e.published >= since.isoformat()]
        newest = max((e.published for e in res), default="")
        print(f"[query] OAI-PMH: {len(res)} records created since {since} (newest {newest})", file=sys.stderr)
        log.append({"name": f"oai: sets {','.join(OAI_SETS)} from {since}", "results": len(res), "newest": newest})
        out.extend(res)
    elif src == "openalex":
        for name, q in OPENALEX_QUERIES:
            try:
                res = openalex_api.search(q, since.isoformat())
            except Exception as ex:  # noqa: BLE001
                msg = f"{type(ex).__name__}: {ex}"[:300]
                print(f"[warn] query failed: {name}: {msg}", file=sys.stderr)
                log.append({"name": name, "results": 0, "error": msg})
                continue
            newest = max((e.published for e in res), default="")
            print(f"[query] {name}: {len(res)} results (newest {newest})", file=sys.stderr)
            log.append({"name": name, "results": len(res), "newest": newest})
            out.extend(res)
    return out, log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None, help="look-back window in days (default: since last run + 3 days; 60 on first run)")
    ap.add_argument("--max-results", type=int, default=150, help="max results fetched per query")
    ap.add_argument("--dry-run", action="store_true", help="print the report and write nothing")
    ap.add_argument("--fixture", type=Path, default=None, help="parse a saved Atom XML feed instead of calling the arXiv API")
    ap.add_argument("--source", choices=["auto", "api", "oai", "openalex"], default="auto", help="data source (auto = api, then OAI-PMH, then OpenAlex)")
    args = ap.parse_args()

    today = dt.date.today()
    state = load_json(STATE, {})
    if args.days is not None:
        since = today - dt.timedelta(days=args.days)
    elif state.get("last_run"):
        since = dt.date.fromisoformat(state["last_run"]) - dt.timedelta(days=3)
    else:
        since = today - dt.timedelta(days=60)

    listed = load_listed_ids()
    seen = load_json(SEEN, {"proposed": {}, "skipped": {}})
    seen.setdefault("proposed", {})
    seen.setdefault("skipped", {})
    seen_ids = set(seen["proposed"]) | set(seen["skipped"])

    # ---- fetch
    entries: dict[str, arxiv_api.Entry] = {}
    fetched = 0
    query_log: list[dict] = []
    source_used = ""
    if args.fixture:
        for e in arxiv_api.parse_feed(args.fixture.read_text(encoding="utf-8")):
            entries.setdefault(e.arxiv_id, e)
            fetched += 1
        n_queries = 1
        source_used = "fixture"
        query_log.append({"name": f"fixture {args.fixture.name}", "results": fetched})
    else:
        order = ["api", "oai", "openalex"] if args.source == "auto" else [args.source]
        n_queries = 0
        for src in order:
            got, log = fetch_source(src, since, args.max_results)
            query_log += log
            n_queries += len(log)
            if got:
                for e in got:
                    entries.setdefault(e.arxiv_id, e)
                fetched = len(got)
                source_used = src
                break
            print(f"[warn] source '{src}' returned nothing; trying the next one", file=sys.stderr)
        if fetched == 0:
            # every source failed; do not advance the window, make the job fail visibly
            print("[error] no results from any source; see data/last_run.json / job summary for details", file=sys.stderr)
            _job_summary("arXiv watch failed", query_log)
            if not args.dry_run:
                _write_last_run("failed", today, since, query_log)
            return 1

    # ---- filter
    in_window = [
        e for e in entries.values()
        if e.published and dt.date.fromisoformat(e.published) >= since and first_submitted_in_window(e.arxiv_id, since)
    ]
    fresh = [e for e in in_window if e.arxiv_id not in listed and e.arxiv_id not in seen_ids]
    tiers: dict[str, list] = {"A": [], "B": []}
    offtopic = 0
    for e in fresh:
        sc = score(e)
        if sc["tier"] is None:
            offtopic += 1
            continue
        tiers[sc["tier"]].append((e, sc))
    for t in tiers.values():
        t.sort(key=lambda x: (-x[1]["score"], x[0].published), reverse=False)
    new = len(tiers["A"]) + len(tiers["B"])

    stats = {
        "source": source_used, "queries": n_queries, "fetched": fetched, "in_window": len(in_window),
        "dropped_seen": len(in_window) - len(fresh), "dropped_offtopic": offtopic, "new": new,
    }
    report = render_report(today, since, tiers, stats)
    print(report if args.dry_run else f"[done] {stats}", file=sys.stdout if args.dry_run else sys.stderr)

    if args.dry_run:
        return 0

    # ---- write outputs
    CANDIDATES.mkdir(exist_ok=True)
    report_path = CANDIDATES / f"{today.isoformat()}.md"
    proposed_now = {e.arxiv_id for e, _ in tiers["A"] + tiers["B"]}
    if new:
        report_path.write_text(report, encoding="utf-8")
        for aid in proposed_now:
            seen["proposed"][aid] = today.isoformat()
    # off-topic items are not recorded: the window only overlaps the previous run by 3 days,
    # so re-scoring them is cheap, and the seen list stays small (proposed candidates only).
    seen["skipped"] = {}
    SEEN.parent.mkdir(exist_ok=True)
    SEEN.write_text(json.dumps(seen, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    STATE.write_text(json.dumps({"last_run": today.isoformat(), "last_candidates": new}, indent=1) + "\n", encoding="utf-8")
    _write_last_run("ok", today, since, query_log, stats)

    # ---- GitHub Actions outputs
    _job_summary(f"arXiv watch: {new} new candidates (window {since.isoformat()} → {today.isoformat()})", query_log, stats)
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"count={new}\n")
            f.write(f"date={today.isoformat()}\n")
            f.write(f"report={report_path.relative_to(ROOT) if new else ''}\n")
    return 0


def _write_last_run(status: str, today: dt.date, since: dt.date, query_log: list[dict], stats: dict | None = None) -> None:
    """Diagnostics of the most recent run (committed by the workflow so they can be inspected without the logs)."""
    LAST_RUN.parent.mkdir(exist_ok=True)
    LAST_RUN.write_text(
        json.dumps({"status": status, "date": today.isoformat(), "window_since": since.isoformat(), "queries": query_log, "stats": stats or {}}, indent=1) + "\n",
        encoding="utf-8",
    )


def _job_summary(title: str, query_log: list[dict], stats: dict | None = None) -> None:
    """Write a short table to the GitHub Actions job summary (no-op outside Actions)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [f"### {title}", "", "| query | results | newest | error |", "|---|---|---|---|"]
    for q in query_log:
        lines.append(f"| {q['name']} | {q.get('results', 0)} | {q.get('newest', '')} | {q.get('error', '')} |")
    if stats:
        lines += ["", "`" + json.dumps(stats) + "`"]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
