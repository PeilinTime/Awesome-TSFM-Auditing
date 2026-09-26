"""Minimal arXiv API client (no third-party dependencies).

API docs: https://info.arxiv.org/help/api/user-manual.html
Be polite: arXiv asks for no more than one request every 3 seconds.
"""
from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

API = "https://export.arxiv.org/api/query"
HOSTS = [API, "https://arxiv.org/api/query"]  # alternated between retries
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
USER_AGENT = "Awesome-TSFM-Auditing/1.0 (https://github.com/PeilinTime/Awesome-TSFM-Auditing)"
RETRY_CODES = {406, 429, 500, 502, 503, 504}
BACKOFF = [5, 15, 30, 60]  # seconds between attempts (~2 min worst case per request)
OAI = "https://oaipmh.arxiv.org/oai"
OAI_NS = {"oai": "http://www.openarchives.org/OAI/2.0/", "ax": "http://arxiv.org/OAI/arXiv/"}
_LAST_CALL = 0.0


@dataclass
class Entry:
    arxiv_id: str  # without version
    version: int
    title: str
    authors: list[str]
    abstract: str
    published: str  # YYYY-MM-DD of v1
    updated: str  # YYYY-MM-DD of latest version
    categories: list[str] = field(default_factory=list)
    comment: str = ""

    @property
    def url(self) -> str:
        return f"https://arxiv.org/abs/{self.arxiv_id}"


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


class ArxivAPIError(RuntimeError):
    """The API answered with an error entry (malformed query, etc.)."""


def parse_feed(xml_text: str) -> list[Entry]:
    root = ET.fromstring(xml_text)
    out: list[Entry] = []
    for e in root.findall("atom:entry", NS):
        raw_id = _clean(e.findtext("atom:id", default="", namespaces=NS))
        if "api/errors" in raw_id:
            raise ArxivAPIError(_clean(e.findtext("atom:summary", default="", namespaces=NS)) or raw_id)
        m = re.search(r"/abs/([^v]+)(?:v(\d+))?$", raw_id)
        if not m:
            continue
        out.append(
            Entry(
                arxiv_id=m.group(1),
                version=int(m.group(2) or 1),
                title=_clean(e.findtext("atom:title", default="", namespaces=NS)),
                authors=[_clean(a.findtext("atom:name", default="", namespaces=NS)) for a in e.findall("atom:author", NS)],
                abstract=_clean(e.findtext("atom:summary", default="", namespaces=NS)),
                published=_clean(e.findtext("atom:published", default="", namespaces=NS))[:10],
                updated=_clean(e.findtext("atom:updated", default="", namespaces=NS))[:10],
                categories=[c.get("term", "") for c in e.findall("atom:category", NS)],
                comment=_clean(e.findtext("arxiv:comment", default="", namespaces=NS)),
            )
        )
    return out


def _looks_like_feed(text: str) -> bool:
    """True if the body is an Atom feed we can use (arXiv sometimes ships a valid feed with a 406 status)."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return False
    return root.tag == "{http://www.w3.org/2005/Atom}feed" and root.find("atom:entry", NS) is not None


def _get(params: dict) -> str:
    """GET with polite pacing and long backoff.

    The arXiv export API intermittently answers 406/429/503 for several minutes at a time,
    to every client, regardless of headers. Treat these like throttling: back off (up to ~8 min)
    and alternate hosts. A 406 body that is itself a valid Atom feed is accepted.
    """
    global _LAST_CALL
    query = urllib.parse.urlencode(params)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    last_error: Exception | None = None
    for attempt, pause in enumerate(BACKOFF):
        host = HOSTS[attempt % len(HOSTS)]
        wait = 3.0 - (time.time() - _LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(host + "?" + query, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                _LAST_CALL = time.time()
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as ex:
            _LAST_CALL = time.time()
            body = ""
            try:
                body = ex.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass
            if ex.code == 406 and _looks_like_feed(body):
                return body
            last_error = ex
            if ex.code not in RETRY_CODES:
                raise
        except Exception as ex:  # noqa: BLE001 — network errors, timeouts
            _LAST_CALL = time.time()
            last_error = ex
        time.sleep(pause)
    raise last_error if last_error else RuntimeError("arXiv API request failed")


def search(query: str, max_results: int = 100, start: int = 0, sort_by: str = "submittedDate") -> list[Entry]:
    """Run one search query (arXiv query syntax) and return parsed entries."""
    xml_text = _get(
        {
            "search_query": query,
            "start": start,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": "descending",
        }
    )
    return parse_feed(xml_text)


def fetch_by_id(arxiv_id: str) -> Entry | None:
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id.strip())
    entries = parse_feed(_get({"id_list": arxiv_id, "max_results": 1}))
    return entries[0] if entries else None


# --------------------------------------------------------------------------- OAI-PMH fallback
def _oai_get(params: dict) -> str:
    """GET against the OAI-PMH endpoint (separate host from the search API), honouring Retry-After on 503."""
    global _LAST_CALL
    headers = {"User-Agent": USER_AGENT, "Accept": "application/xml, text/xml;q=0.9, */*;q=0.8"}
    last_error: Exception | None = None
    for pause in BACKOFF:
        wait = 3.0 - (time.time() - _LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(OAI + "?" + urllib.parse.urlencode(params), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                _LAST_CALL = time.time()
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as ex:
            _LAST_CALL = time.time()
            last_error = ex
            if ex.code not in RETRY_CODES:
                raise
            retry_after = ex.headers.get("Retry-After") if ex.headers else None
            if retry_after and retry_after.isdigit():
                pause = max(pause, min(int(retry_after), 300))
        except Exception as ex:  # noqa: BLE001
            _LAST_CALL = time.time()
            last_error = ex
        time.sleep(pause)
    raise last_error if last_error else RuntimeError("OAI-PMH request failed")


def parse_oai(xml_text: str) -> tuple[list[Entry], str | None]:
    """Parse one ListRecords page of the arXiv OAI-PMH feed. Returns (entries, resumption_token)."""
    root = ET.fromstring(xml_text)
    err = root.find("oai:error", OAI_NS)
    if err is not None:
        code = err.get("code", "")
        if code == "noRecordsMatch":
            return [], None
        raise ArxivAPIError(f"OAI-PMH error {code}: {_clean(err.text)}")
    out: list[Entry] = []
    for rec in root.iterfind(".//oai:record", OAI_NS):
        md = rec.find("oai:metadata/ax:arXiv", OAI_NS)
        if md is None:  # deleted record
            continue
        authors = []
        for a in md.findall("ax:authors/ax:author", OAI_NS):
            fore = _clean(a.findtext("ax:forenames", default="", namespaces=OAI_NS))
            key = _clean(a.findtext("ax:keyname", default="", namespaces=OAI_NS))
            authors.append(f"{fore} {key}".strip())
        out.append(
            Entry(
                arxiv_id=_clean(md.findtext("ax:id", default="", namespaces=OAI_NS)),
                version=1,
                title=_clean(md.findtext("ax:title", default="", namespaces=OAI_NS)),
                authors=authors,
                abstract=_clean(md.findtext("ax:abstract", default="", namespaces=OAI_NS)),
                published=_clean(md.findtext("ax:created", default="", namespaces=OAI_NS))[:10],
                updated=_clean(md.findtext("ax:updated", default="", namespaces=OAI_NS))[:10]
                or _clean(md.findtext("ax:created", default="", namespaces=OAI_NS))[:10],
                categories=_clean(md.findtext("ax:categories", default="", namespaces=OAI_NS)).split(),
                comment=_clean(md.findtext("ax:comments", default="", namespaces=OAI_NS)),
            )
        )
    tok = root.find(".//oai:resumptionToken", OAI_NS)
    token = _clean(tok.text) if tok is not None and tok.text else None
    return out, token


def oai_harvest(since: str, sets: tuple[str, ...] = ("cs", "stat"), max_pages: int = 120) -> list[Entry]:
    """Harvest every record in the given arXiv sets whose datestamp is >= `since` (YYYY-MM-DD).

    Complete (no query syntax involved) but heavier than the search API: ~1000 records per page,
    roughly 1-2k new cs records per day. Callers filter by keywords afterwards.
    """
    out: list[Entry] = []
    for s in sets:
        params: dict = {"verb": "ListRecords", "metadataPrefix": "arXiv", "set": s, "from": since}
        for _ in range(max_pages):
            entries, token = parse_oai(_oai_get(params))
            out.extend(entries)
            if not token:
                break
            params = {"verb": "ListRecords", "resumptionToken": token}
    return out
