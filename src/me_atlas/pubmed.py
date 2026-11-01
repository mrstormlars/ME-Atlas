"""PubMed fetch: search, download, cache and parse.

Command line::

    uv run python -m me_atlas.pubmed fetch --since 2026-01-01 [--until 2026-10-31] [--refresh]
    uv run python -m me_atlas.pubmed fetch --weekly      # last 14 days by entry date
    uv run python -m me_atlas.pubmed fetch --backfill    # the whole literature, no lower date
    uv run python -m me_atlas.pubmed fetch --ids 12345678 23456789 [--refresh]   # exactly these records

Every run except ``--ids`` searches PubMed with the query in ``config/pubmed_query.txt``, also asks which
hits are retracted, downloads the records not yet cached into ``data/cache/pubmed/<pmid>.xml`` and writes
a manifest to ``data/cache/runs/<timestamp>.json``. ``--ids`` downloads only the given PMIDs (no search,
no retraction query), so a card can cite a paper the search query does not find. See ``docs/fetch.md``.

Environment (or ``.env``): ``CONTACT_EMAIL`` (required, sent to NCBI) and ``NCBI_API_KEY`` (optional,
raises the rate limit from 3 to 10 requests per second).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict

from me_atlas.cards import StudyId
from me_atlas.http import RateLimiter, get_with_retries, load_dotenv

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL_NAME = "me-atlas"
RATE_LIMIT_NO_KEY = 3
RATE_LIMIT_WITH_KEY = 10
FETCH_BATCH_SIZE = 200
# PubMed's ESearch returns at most this many ids per search; larger result sets are split by date.
MAX_UIDS = 9999
RETRACTION_FILTER = '"Retracted Publication"[Publication Type]'
WEEKLY_DAYS = 14
EARLIEST_ENTRY_DATE = dt.date(1900, 1, 1)

DEFAULT_CACHE_ROOT = Path("data/cache")
DEFAULT_QUERY_FILE = Path("config/pubmed_query.txt")


class PubMedError(Exception):
    """A request to NCBI failed for good, or the response could not be understood."""


class ParseError(PubMedError):
    """A PubMed XML record is not in the expected shape."""


# ---------------------------------------------------------------------------
# Parsed record
# ---------------------------------------------------------------------------


class PubMedRecord(BaseModel):
    """One PubMed article, reduced to the fields later steps rely on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: StudyId  # "pmid:<digits>", the id used in cards
    pmid: str
    doi: str | None
    title: str
    abstract: str | None
    journal: str | None
    year: int | None
    authors: list[str]
    publication_types: list[str]
    mesh_terms: list[str]
    retracted: bool
    entry_date: str | None  # ISO date (the PubMed "entrez" history date)


_YEAR_RE = re.compile(r"\b(1[89]\d\d|20\d\d)\b")


def _text(elem: ET.Element | None) -> str:
    """All text inside an element (including inline markup such as <i>), whitespace collapsed."""
    if elem is None:
        return ""
    return " ".join("".join(elem.itertext()).split())


def _abstract(article: ET.Element) -> str | None:
    parts: list[str] = []
    for node in article.findall("Abstract/AbstractText"):
        body = _text(node)
        if not body:
            continue
        label = (node.get("Label") or "").strip()
        parts.append(f"{label}: {body}" if label else body)
    return "\n".join(parts) or None


def _year(article: ET.Element) -> int | None:
    pub_date = article.find("Journal/JournalIssue/PubDate")
    if pub_date is not None:
        year = _text(pub_date.find("Year"))
        if year.isdigit():
            return int(year)
        match = _YEAR_RE.search(_text(pub_date.find("MedlineDate")))
        if match:
            return int(match.group(1))
    return None


def _authors(article: ET.Element) -> list[str]:
    names: list[str] = []
    for author in article.findall("AuthorList/Author"):
        collective = _text(author.find("CollectiveName"))
        if collective:
            names.append(collective)
            continue
        name = " ".join(p for p in (_text(author.find("LastName")), _text(author.find("Initials"))) if p)
        name = name or _text(author.find("ForeName"))
        if name:
            names.append(name)
    return names


def _doi(citation: ET.Element, pubmed_data: ET.Element | None) -> str | None:
    if pubmed_data is not None:
        for node in pubmed_data.findall("ArticleIdList/ArticleId"):
            if node.get("IdType") == "doi" and _text(node):
                return _text(node)
    for node in citation.findall("Article/ELocationID"):
        if node.get("EIdType") == "doi" and _text(node):
            return _text(node)
    return None


def _entry_date(pubmed_data: ET.Element | None) -> str | None:
    if pubmed_data is None:
        return None
    for node in pubmed_data.findall("History/PubMedPubDate"):
        if node.get("PubStatus") != "entrez":
            continue
        try:
            return dt.date(
                int(_text(node.find("Year"))), int(_text(node.find("Month"))), int(_text(node.find("Day")))
            ).isoformat()
        except ValueError:
            return None
    return None


def parse_article(article: ET.Element) -> PubMedRecord:
    """Parse one ``<PubmedArticle>`` element. Raises ParseError if it is not a usable record."""
    citation = article.find("MedlineCitation")
    art = citation.find("Article") if citation is not None else None
    if citation is None or art is None:
        raise ParseError(f"not a PubmedArticle with MedlineCitation/Article (root <{article.tag}>)")
    pmid = _text(citation.find("PMID"))
    if not pmid.isdigit():
        raise ParseError(f"PMID is missing or not numeric: {pmid!r}")
    title = _text(art.find("ArticleTitle"))
    if not title:
        raise ParseError(f"pmid:{pmid} has no article title")
    pubmed_data = article.find("PubmedData")

    publication_types = [t for t in (_text(n) for n in art.findall("PublicationTypeList/PublicationType")) if t]
    # Retracted: the "Retracted Publication" type, or a "retraction in" link to the notice. The notice
    # itself ("Retraction of Publication", RefType "RetractionOf") is not a retracted study.
    retracted = "Retracted Publication" in publication_types or any(
        n.get("RefType") == "RetractionIn" for n in citation.findall("CommentsCorrectionsList/CommentsCorrections")
    )
    mesh_terms = [t for t in (_text(n) for n in citation.findall("MeshHeadingList/MeshHeading/DescriptorName")) if t]

    return PubMedRecord(
        id=f"pmid:{pmid}",
        pmid=pmid,
        doi=_doi(citation, pubmed_data),
        title=title,
        abstract=_abstract(art),
        journal=_text(art.find("Journal/Title")) or _text(art.find("Journal/ISOAbbreviation")) or None,
        year=_year(art),
        authors=_authors(art),
        publication_types=publication_types,
        mesh_terms=mesh_terms,
        retracted=retracted,
        entry_date=_entry_date(pubmed_data),
    )


def parse_xml(xml: str | bytes) -> PubMedRecord:
    """Parse the XML of one cached record (a ``<PubmedArticle>`` or a set holding one)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ParseError(f"invalid XML: {exc}") from exc
    if root.tag == "PubmedArticleSet":
        articles = root.findall("PubmedArticle")
        if len(articles) != 1:
            raise ParseError(f"expected one PubmedArticle in the set, found {len(articles)}")
        root = articles[0]
    return parse_article(root)


# ---------------------------------------------------------------------------
# Rate limiting and the HTTP client
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    count: int
    ids: list[str]
    webenv: str | None = None
    query_key: str | None = None
    warnings: list[str] = field(default_factory=list)


class PubMedClient:
    """Minimal NCBI E-utilities client: polite, rate limited, with retries."""

    def __init__(
        self,
        email: str,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 4,
        backoff: float = 1.0,
        base_url: str = EUTILS,
    ):
        if not email:
            raise ValueError("an email address is required for NCBI requests")
        self.email = email
        self.api_key = api_key or None
        self.max_retries = max_retries
        self.backoff = backoff
        self.base_url = base_url
        self._sleep = sleep
        self._limiter = RateLimiter(RATE_LIMIT_WITH_KEY if self.api_key else RATE_LIMIT_NO_KEY, clock, sleep)
        self._http = httpx.Client(transport=transport, timeout=60.0)

    def close(self) -> None:
        self._http.close()

    def _params(self, extra: Mapping[str, str | int]) -> dict[str, str | int]:
        params: dict[str, str | int] = {"db": "pubmed", "tool": TOOL_NAME, "email": self.email, **extra}
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def _get(self, endpoint: str, extra: Mapping[str, str | int]) -> httpx.Response:
        """GET with rate limiting; retries 429, 5xx and transport errors with exponential backoff."""
        return get_with_retries(
            self._http,
            f"{self.base_url}/{endpoint}",
            params=self._params(extra),
            limiter=self._limiter,
            sleep=self._sleep,
            max_retries=self.max_retries,
            backoff=self.backoff,
            label=endpoint,
            error=PubMedError,
        )

    def search(self, term: str, *, mindate: dt.date | None = None, maxdate: dt.date | None = None) -> SearchResult:
        """ESearch with the history server. Dates filter on the entry date (EDAT)."""
        extra: dict[str, str | int] = {
            "term": term,
            "retmode": "json",
            "usehistory": "y",
            "retmax": MAX_UIDS,
        }
        if mindate or maxdate:
            extra["datetype"] = "edat"
            extra["mindate"] = (mindate or EARLIEST_ENTRY_DATE).strftime("%Y/%m/%d")
            extra["maxdate"] = (maxdate or dt.date.today()).strftime("%Y/%m/%d")
        response = self._get("esearch.fcgi", extra)
        try:
            data = response.json()
            result = data["esearchresult"]
        except (ValueError, KeyError) as exc:
            raise PubMedError(f"unreadable ESearch response: {response.text[:200]!r}") from exc
        problem = data.get("error") or result.get("ERROR")
        if problem:
            raise PubMedError(f"ESearch error: {problem}")
        warnings = []
        for key in ("warninglist", "errorlist"):
            for kind, items in (result.get(key) or {}).items():
                if items:
                    warnings.append(f"{kind}: {', '.join(str(i) for i in items)}")
        return SearchResult(
            count=int(result["count"]),
            ids=[str(i) for i in result.get("idlist", [])],
            webenv=result.get("webenv"),
            query_key=result.get("querykey"),
            warnings=warnings,
        )

    def search_all(self, term: str, *, mindate: dt.date | None = None, maxdate: dt.date | None = None) -> SearchResult:
        """Like ``search`` but returns every id, splitting by entry date if over the ESearch cap."""
        first = self.search(term, mindate=mindate, maxdate=maxdate)
        if first.count <= len(first.ids):
            return first
        lo = mindate or EARLIEST_ENTRY_DATE
        hi = maxdate or dt.date.today()
        ids: dict[str, None] = {}
        warnings = list(first.warnings)
        self._collect_split(term, lo, hi, ids, warnings)
        if len(ids) < first.count:
            warnings.append(f"split search found {len(ids)} ids but the full search reported {first.count}")
        return SearchResult(first.count, list(ids), first.webenv, first.query_key, warnings)

    def _collect_split(self, term: str, lo: dt.date, hi: dt.date, ids: dict[str, None], warnings: list[str]) -> None:
        part = self.search(term, mindate=lo, maxdate=hi)
        if part.count <= len(part.ids):
            ids.update(dict.fromkeys(part.ids))
            return
        if lo >= hi:
            raise PubMedError(f"{part.count} hits on the single entry date {lo}; cannot split further")
        mid = lo + (hi - lo) // 2
        self._collect_split(term, lo, mid, ids, warnings)
        self._collect_split(term, mid + dt.timedelta(days=1), hi, ids, warnings)

    def fetch_batch(self, pmids: Sequence[str]) -> bytes:
        """EFetch the XML for up to FETCH_BATCH_SIZE PMIDs."""
        response = self._get("efetch.fcgi", {"id": ",".join(pmids), "retmode": "xml"})
        return response.content

    def fetch_articles(self, pmids: Sequence[str]) -> Iterator[ET.Element]:
        """EFetch in batches and yield each ``<PubmedArticle>`` element."""
        for i in range(0, len(pmids), FETCH_BATCH_SIZE):
            content = self.fetch_batch(pmids[i : i + FETCH_BATCH_SIZE])
            try:
                root = ET.fromstring(content)
            except ET.ParseError as exc:
                raise PubMedError(f"unreadable EFetch response: {exc}") from exc
            if root.tag != "PubmedArticleSet":
                raise PubMedError(f"unexpected EFetch response (root <{root.tag}>)")
            yield from root.findall("PubmedArticle")


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class RawCache:
    """Raw PubMed XML per PMID at ``<root>/pubmed/<pmid>.xml``; run manifests at ``<root>/runs/``."""

    def __init__(self, root: Path = DEFAULT_CACHE_ROOT):
        self.root = Path(root)
        self.pubmed_dir = self.root / "pubmed"
        self.runs_dir = self.root / "runs"

    def path(self, pmid: str) -> Path:
        if not pmid.isdigit():
            raise ValueError(f"PMID must be digits, got {pmid!r}")
        return self.pubmed_dir / f"{pmid}.xml"

    def has(self, pmid: str) -> bool:
        return self.path(pmid).is_file()

    def write(self, pmid: str, article: ET.Element) -> None:
        self.pubmed_dir.mkdir(parents=True, exist_ok=True)
        article.tail = None
        xml = ET.tostring(article, encoding="unicode")
        self.path(pmid).write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n{xml}\n', encoding="utf-8")

    def read_record(self, pmid: str) -> PubMedRecord:
        """Parse the cached record. Raises ParseError if the file is unusable, FileNotFoundError if absent."""
        return parse_xml(self.path(pmid).read_bytes())

    def write_manifest(self, manifest: Mapping[str, object], timestamp: str) -> Path:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path = self.runs_dir / f"{timestamp}.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# Query and run
# ---------------------------------------------------------------------------


def read_query(path: Path) -> str:
    """Read the search query from a config file. Lines starting with ``#`` are comments."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise PubMedError(f"cannot read query file {path}: {exc}") from exc
    query = " ".join(
        stripped for line in text.splitlines() if (stripped := line.strip()) and not stripped.startswith("#")
    )
    if not query:
        raise PubMedError(f"query file {path} is empty")
    return query


def retraction_term(query: str) -> str:
    return f"({query}) AND {RETRACTION_FILTER}"


@dataclass(frozen=True)
class Window:
    mode: str  # "since", "weekly" or "backfill"
    since: dt.date | None
    until: dt.date | None


def _pmid_sort(pmids: Sequence[str] | set[str]) -> list[str]:
    return sorted(pmids, key=int)


def run_fetch(
    client: PubMedClient,
    query: str,
    window: Window,
    cache: RawCache,
    *,
    refresh: bool = False,
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    query_file: str = "",
) -> tuple[dict[str, object], Path]:
    """Search, run the retraction query, download what is missing and write the manifest.

    The window search finds papers by entry date. The retraction query is the same query plus the
    "Retracted Publication" filter and is deliberately NOT limited by the window: a retraction
    usually comes long after the paper entered PubMed, and it is the old papers cards may cite.
    """
    started = now()
    window_result = client.search_all(query, mindate=window.since, maxdate=window.until)
    retraction_result = client.search_all(retraction_term(query))

    window_pmids = set(window_result.ids)
    retracted_pmids = set(retraction_result.ids)

    # A cached record is stale if the retraction query says it is retracted but the copy is not.
    stale_retracted: set[str] = set()
    for pmid in retracted_pmids:
        if not cache.has(pmid):
            continue
        try:
            if not cache.read_record(pmid).retracted:
                stale_retracted.add(pmid)
        except ParseError:
            stale_retracted.add(pmid)

    wanted = window_pmids | retracted_pmids
    already_cached = {p for p in wanted if cache.has(p)}
    to_fetch = wanted if refresh else (wanted - already_cached) | stale_retracted

    fetched: set[str] = set()
    unparsable: list[str] = []
    newly_flagged: list[str] = []
    for article in client.fetch_articles(_pmid_sort(to_fetch)):
        pmid = _text(article.find("MedlineCitation/PMID"))
        if not pmid.isdigit():
            continue
        cache.write(pmid, article)
        fetched.add(pmid)
        try:
            record = parse_article(article)
        except ParseError:
            unparsable.append(pmid)
            continue
        if pmid in stale_retracted and record.retracted:
            newly_flagged.append(pmid)
    missing = to_fetch - fetched
    new_pmids = fetched - already_cached

    def iso(d: dt.date | None) -> str | None:
        return d.isoformat() if d else None

    manifest: dict[str, object] = {
        "timestamp": started.isoformat(),
        "query_file": query_file,
        "query": query,
        "window": {"mode": window.mode, "datetype": "edat", "since": iso(window.since), "until": iso(window.until)},
        "retraction_query": retraction_term(query),
        "refresh": refresh,
        "counts": {
            "window_hits": window_result.count,
            "retraction_hits": retraction_result.count,
            "requested": len(to_fetch),
            "fetched": len(fetched),
            "new": len(new_pmids),
            "skipped_cached": len(wanted - to_fetch),
            "missing": len(missing),
            "unparsable": len(unparsable),
        },
        "new_pmids": _pmid_sort(new_pmids),
        "retracted_pmids": _pmid_sort(retracted_pmids),
        "newly_flagged_retracted_pmids": _pmid_sort(newly_flagged),
        "missing_pmids": _pmid_sort(missing),
        "unparsable_pmids": _pmid_sort(unparsable),
        "warnings": window_result.warnings + retraction_result.warnings,
    }
    timestamp = started.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return manifest, cache.write_manifest(manifest, timestamp)


def run_fetch_ids(
    client: PubMedClient,
    pmids: Sequence[str],
    cache: RawCache,
    *,
    refresh: bool = False,
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
) -> tuple[dict[str, object], Path]:
    """Download exactly these PMIDs (cached ones are skipped unless ``refresh``) and write the manifest.

    No search and no retraction query: the ids come from a person, for example a paper a card cites that
    the search query does not find.
    """
    started = now()
    requested = list(dict.fromkeys(pmids))
    already_cached = {p for p in requested if cache.has(p)}
    to_fetch = set(requested) if refresh else set(requested) - already_cached

    fetched: set[str] = set()
    unparsable: list[str] = []
    for article in client.fetch_articles(_pmid_sort(to_fetch)):
        pmid = _text(article.find("MedlineCitation/PMID"))
        if not pmid.isdigit() or pmid not in to_fetch:
            continue
        cache.write(pmid, article)
        fetched.add(pmid)
        try:
            parse_article(article)
        except ParseError:
            unparsable.append(pmid)
    missing = to_fetch - fetched

    manifest: dict[str, object] = {
        "timestamp": started.isoformat(),
        "mode": "ids",
        "ids": requested,
        "refresh": refresh,
        "counts": {
            "requested": len(to_fetch),
            "fetched": len(fetched),
            "new": len(fetched - already_cached),
            "skipped_cached": len(set(requested) - to_fetch),
            "missing": len(missing),
            "unparsable": len(unparsable),
        },
        "new_pmids": _pmid_sort(fetched - already_cached),
        "missing_pmids": _pmid_sort(missing),
        "unparsable_pmids": _pmid_sort(unparsable),
        "warnings": [],
    }
    timestamp = started.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return manifest, cache.write_manifest(manifest, timestamp)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _pmid_arg(text: str) -> str:
    value = text.removeprefix("pmid:")
    if not value.isdigit():
        raise argparse.ArgumentTypeError(f"not a PMID (digits, optionally 'pmid:' first): {text!r}")
    return value


def _date(text: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {text!r}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m me_atlas.pubmed", description="PubMed fetch tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="search PubMed (or fetch given ids), cache new records, write a run manifest")
    mode = fetch.add_mutually_exclusive_group(required=True)
    mode.add_argument("--since", type=_date, metavar="YYYY-MM-DD", help="fetch records entered on or after this date")
    mode.add_argument("--weekly", action="store_true", help=f"shorthand for the last {WEEKLY_DAYS} days")
    mode.add_argument("--backfill", action="store_true", help="fetch the whole literature (no lower date)")
    mode.add_argument(
        "--ids",
        nargs="+",
        type=_pmid_arg,
        metavar="PMID",
        help="fetch exactly these records (no search, no retraction query)",
    )
    fetch.add_argument(
        "--until", type=_date, metavar="YYYY-MM-DD", help="with --since: last entry date (default today)"
    )
    fetch.add_argument("--refresh", action="store_true", help="re-download records even if cached")
    fetch.add_argument("--query-file", type=Path, default=DEFAULT_QUERY_FILE, help="default: %(default)s")
    fetch.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_ROOT, help="default: %(default)s")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    today: dt.date | None = None,
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
) -> int:
    """Entry point. ``env`` is given by tests; otherwise ``.env`` and the process environment are used."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.until and args.since is None:
        parser.error("--until can only be used with --since")
    if env is None:
        env = {**load_dotenv(), **os.environ}

    email = (env.get("CONTACT_EMAIL") or "").strip()
    if not email:
        print(
            "error: CONTACT_EMAIL is not set. NCBI requires a contact email; set CONTACT_EMAIL in .env "
            "or the environment (see .env.example).",
            file=sys.stderr,
        )
        return 2

    if args.ids:
        return _main_ids(args, email, env, transport, clock, sleep, now)

    today = today or dt.date.today()
    if args.weekly:
        window = Window("weekly", today - dt.timedelta(days=WEEKLY_DAYS), today)
    elif args.backfill:
        window = Window("backfill", None, None)
    else:
        window = Window("since", args.since, args.until or today)

    client = PubMedClient(
        email, (env.get("NCBI_API_KEY") or "").strip() or None, transport=transport, clock=clock, sleep=sleep
    )
    try:
        query = read_query(args.query_file)
        manifest, path = run_fetch(
            client,
            query,
            window,
            RawCache(args.cache_dir),
            refresh=args.refresh,
            now=now,
            query_file=str(args.query_file),
        )
    except PubMedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    counts = manifest["counts"]
    assert isinstance(counts, dict)
    print(f"window hits: {counts['window_hits']}, retraction hits: {counts['retraction_hits']}")
    print(f"fetched {counts['fetched']} ({counts['new']} new), skipped {counts['skipped_cached']} cached")
    for key in ("missing_pmids", "unparsable_pmids"):
        if manifest[key]:
            print(f"warning: {key}: {', '.join(manifest[key])}", file=sys.stderr)  # type: ignore[arg-type]
    for warning in manifest["warnings"]:  # type: ignore[attr-defined]
        print(f"warning: PubMed says {warning}", file=sys.stderr)
    print(f"manifest: {path}")
    return 0


def _main_ids(
    args: argparse.Namespace,
    email: str,
    env: Mapping[str, str],
    transport: httpx.BaseTransport | None,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    now: Callable[[], dt.datetime],
) -> int:
    client = PubMedClient(
        email, (env.get("NCBI_API_KEY") or "").strip() or None, transport=transport, clock=clock, sleep=sleep
    )
    try:
        manifest, path = run_fetch_ids(client, args.ids, RawCache(args.cache_dir), refresh=args.refresh, now=now)
    except PubMedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
    counts = manifest["counts"]
    assert isinstance(counts, dict)
    print(f"fetched {counts['fetched']} ({counts['new']} new), skipped {counts['skipped_cached']} cached")
    for key in ("missing_pmids", "unparsable_pmids"):
        if manifest[key]:
            print(f"warning: {key}: {', '.join(manifest[key])}", file=sys.stderr)  # type: ignore[arg-type]
    print(f"manifest: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
