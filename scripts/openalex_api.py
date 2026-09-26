"""Minimal OpenAlex client used as a fallback source when the arXiv API is unavailable.

Docs: https://docs.openalex.org/  — free, no key. Set the OPENALEX_MAILTO environment variable
(a contact e-mail) to join the "polite pool", which has better rate limits.
Only works that carry an arXiv id are returned, so results merge with the arXiv sources.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arxiv_api import USER_AGENT, Entry  # noqa: E402

API = "https://api.openalex.org/works"
BACKOFF = [10, 30, 60]
_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.I)
_DOI_RE = re.compile(r"10\.48550/arxiv\.(\d{4}\.\d{4,5})", re.I)
_LAST_CALL = 0.0


def _get(params: dict) -> dict:
    global _LAST_CALL
    mailto = os.environ.get("OPENALEX_MAILTO", "").strip()
    if mailto:
        params = {**params, "mailto": mailto}
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    last_error: Exception | None = None
    for pause in BACKOFF + [0]:
        wait = 1.0 - (time.time() - _LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                _LAST_CALL = time.time()
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as ex:
            _LAST_CALL = time.time()
            last_error = ex
            if ex.code not in {429, 500, 502, 503, 504}:
                raise
        except Exception as ex:  # noqa: BLE001
            _LAST_CALL = time.time()
            last_error = ex
        if pause:
            time.sleep(pause)
    raise last_error if last_error else RuntimeError("OpenAlex request failed")


def _abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        positions.extend((i, word) for i in idxs)
    positions.sort()
    return " ".join(w for _, w in positions)


def _arxiv_id(work: dict) -> str | None:
    doi = work.get("doi") or ""
    m = _DOI_RE.search(doi)
    if m:
        return m.group(1)
    urls = []
    for loc in work.get("locations") or []:
        urls += [loc.get("landing_page_url") or "", loc.get("pdf_url") or ""]
    for u in urls:
        m = _ARXIV_RE.search(u)
        if m:
            return m.group(1)
    return None


def to_entry(work: dict) -> Entry | None:
    aid = _arxiv_id(work)
    if not aid:
        return None
    authors = [(a.get("author") or {}).get("display_name", "") for a in work.get("authorships") or []]
    date = (work.get("publication_date") or "")[:10]
    return Entry(
        arxiv_id=aid,
        version=1,
        title=re.sub(r"\s+", " ", work.get("title") or "").strip(),
        authors=[a for a in authors if a],
        abstract=_abstract(work.get("abstract_inverted_index")),
        published=date,
        updated=date,
        categories=["openalex"],
        comment="",
    )


def search(query: str, since: str, per_page: int = 100, max_pages: int = 3) -> list[Entry]:
    """Full-text search (title/abstract; supports quotes, AND/OR/NOT) for works published on/after `since`."""
    out: list[Entry] = []
    for page in range(1, max_pages + 1):
        data = _get(
            {
                "search": query,
                "filter": f"from_publication_date:{since}",
                "per-page": per_page,
                "page": page,
                "select": "id,doi,title,publication_date,authorships,abstract_inverted_index,locations",
            }
        )
        results = data.get("results") or []
        for w in results:
            e = to_entry(w)
            if e:
                out.append(e)
        if len(results) < per_page:
            break
    return out
