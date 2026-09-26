#!/usr/bin/env python3
"""Fill data/abstracts.json with the abstract of every arXiv paper in papers.yaml.

    python scripts/fetch_abstracts.py            # fetch the missing ones
    python scripts/fetch_abstracts.py --refresh  # re-fetch everything

Abstracts are stored separately from papers.yaml (keyed by arXiv id, or by entry id for papers
without an arXiv version) so that the list itself stays readable. README.md folds them under
each title. Papers without an arXiv id are left alone: add their abstract to the JSON by hand.
The arXiv search API is tried first; when it rejects the client (it intermittently answers
HTTP 406 to automated requests) the OAI-PMH GetRecord endpoint is used instead.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arxiv_api  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PAPERS = ROOT / "papers.yaml"
ABSTRACTS = ROOT / "data" / "abstracts.json"


API_DOWN = False  # once the search API has rejected us, go straight to OAI-PMH for the rest of the run


def fetch(arxiv_id: str):
    global API_DOWN
    if not API_DOWN:
        try:
            e = arxiv_api.fetch_by_id(arxiv_id)
            if e and e.abstract:
                return e, "api"
        except Exception as ex:  # noqa: BLE001
            API_DOWN = True
            print(f"  search API failed for {arxiv_id}: {type(ex).__name__}: {str(ex)[:80]}; using OAI-PMH from now on", file=sys.stderr)
    e = arxiv_api.oai_get_record(arxiv_id)
    return (e, "oai") if e and e.abstract else (None, "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-fetch abstracts that are already stored")
    args = ap.parse_args()

    data = yaml.safe_load(PAPERS.read_text(encoding="utf-8"))
    store = json.loads(ABSTRACTS.read_text(encoding="utf-8")) if ABSTRACTS.exists() else {}
    todo = [p for p in data["papers"] if p.get("arxiv") and (args.refresh or p["arxiv"] not in store)]
    print(f"{len(todo)} abstract(s) to fetch", file=sys.stderr)
    ok = failed = 0
    for p in todo:
        e, src = fetch(p["arxiv"])
        if e is None:
            failed += 1
            print(f"  FAILED {p['arxiv']} ({p['id']})", file=sys.stderr)
            continue
        store[p["arxiv"]] = {"title": e.title, "abstract": e.abstract, "source": src}
        ok += 1
        print(f"  {p['arxiv']} ({p['id']}) via {src}", file=sys.stderr)
        ABSTRACTS.parent.mkdir(exist_ok=True)
        ABSTRACTS.write_text(json.dumps(store, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    missing = [p["id"] for p in data["papers"] if (p.get("arxiv") or p["id"]) not in store]
    print(f"fetched {ok}, failed {failed}, still missing: {missing}", file=sys.stderr)
    return 1 if failed and ok == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
