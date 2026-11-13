"""Europe PMC full text, on demand, and a finder for case-definition sentences.

Command line::

    uv run python -m me_atlas.europepmc fulltext <pmid>...
    uv run python -m me_atlas.europepmc casedef <pmid>...
    uv run python -m me_atlas.europepmc casedef --card drafts/<slug>.yaml
    uv run python -m me_atlas.europepmc pmcpage --card drafts/<slug>.yaml <pmid>...

``fulltext`` looks each PMID up in Europe PMC and downloads the full-text XML of records that have a real
body into ``data/cache/europepmc/<pmcid>.xml`` (the lookup itself is cached as ``<pmid>.json``; a negative
lookup is asked again after ``LOOKUP_MAX_AGE_DAYS``). The PMC id may come from Europe PMC or from the cached
PubMed record. Statuses: ``open_access``, ``pdf_only`` (the XML is only a note that the text is a PDF; nothing
is cached), ``pmc_no_xml`` (a PMC id is known and the full-text request answers HTTP 404), ``not_open_access``
and ``not_found`` (no PMC id known). No PDF is downloaded or parsed. ``casedef`` does the same and then prints
the sentences of the methods section (or, if the article has none, of the whole body) that name a case
definition, and, marked ``[exclusion]``, sentences that exclude people with the illness. The finder only
returns candidates: which definition a sentence means, and what goes on a card, is a human or agent
judgement. Full text stays in the gitignored cache.

``pmcpage`` is for a cited study that has no open-access full text but is free to read on PubMed Central
(the cached lookup gives a PMCID and ``inPMC`` "Y"; founder ruling 2026-11-08). It fetches the article page
``https://pmc.ncbi.nlm.nih.gov/articles/<pmcid>/`` once, on demand, for PMIDs named on the command line that
are ``pmid:`` studies on the given card or draft, never in bulk and never from a publisher site, and caches
it as ``<pmcid>.html``. Only the abstract and main article body are read (no reference list, navigation or
scripts); the page is used to find and check the case-definition sentence and sample sizes. A page is cached
only if its ``citation_pmid`` is the PMID asked for and it has a main article body. Redirects are not
followed, so a moved page is an error rather than a request to another site.

Environment (or ``.env``): ``CONTACT_EMAIL`` (required, sent in the User-Agent header).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import httpx

from me_atlas.cards import load_card
from me_atlas.http import RateLimiter, get_with_retries, load_dotenv
from me_atlas.pubmed import ParseError, parse_xml

# Endpoint URLs of the Europe PMC REST API. Confirmed against the live service on 2026-10-31 (plan step 7):
# lookups and fullTextXML worked for 18 PMIDs cited on the first two draft cards.
EPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EPMC_FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
# The free-to-read article page on PubMed Central (see the module docstring for the rule on its use).
PMC_PAGE_URL = "https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
# Search for one PubMed record by its PMID (source MED); the JSON "lite" result carries pmcid and isOpenAccess.
EPMC_SEARCH_QUERY = "EXT_ID:{pmid} AND SRC:MED"
EPMC_SEARCH_PARAMS: dict[str, str | int] = {"format": "json", "resultType": "lite", "pageSize": 5}

TOOL_NAME = "me-atlas"
RATE_LIMIT = 3
DEFAULT_CACHE_ROOT = Path("data/cache")

_PMCID_RE = re.compile(r"^PMC\d+$")

# A cached lookup that found no open-access full text is asked again when its file is older than this:
# Europe PMC can gain the PMC id or the full text after the first answer.
LOOKUP_MAX_AGE_DAYS = 7

# Statuses of a ``get_fulltext`` result.
STATUS_OPEN_ACCESS = "open_access"
STATUS_NOT_OPEN_ACCESS = "not_open_access"
STATUS_NOT_FOUND = "not_found"
STATUS_PDF_ONLY = "pdf_only"
STATUS_PMC_NO_XML = "pmc_no_xml"

# A "full text" whose body is only a note that the real text is a PDF (seen for a preprint on 2026-11-13).
_PLACEHOLDER_MAX_CHARS = 1000
_PLACEHOLDER_MARKER = "available as a pdf"


class EuropePmcError(Exception):
    """A request to Europe PMC failed for good, or the response could not be understood."""


class FullTextNotFoundError(EuropePmcError):
    """The full-text request answered HTTP 404 (not retried): Europe PMC has no full-text XML for that PMC id."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class EuropePmcClient:
    """Minimal Europe PMC REST client: polite, rate limited (3 requests/s), with retries."""

    def __init__(
        self,
        email: str,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 4,
        backoff: float = 1.0,
        search_url: str = EPMC_SEARCH_URL,
        fulltext_url: str = EPMC_FULLTEXT_URL,
        pmc_page_url: str = PMC_PAGE_URL,
    ):
        if not email:
            raise ValueError("an email address is required for Europe PMC requests")
        self.email = email
        self.max_retries = max_retries
        self.backoff = backoff
        self.search_url = search_url
        self.fulltext_url = fulltext_url
        self.pmc_page_url = pmc_page_url
        self._sleep = sleep
        self._limiter = RateLimiter(RATE_LIMIT, clock, sleep)
        self._http = httpx.Client(
            transport=transport,
            timeout=60.0,
            headers={"User-Agent": f"{TOOL_NAME}/0.1 (mailto:{email})"},
        )

    def close(self) -> None:
        self._http.close()

    def _get(self, url: str, params: Mapping[str, str | int] | None, label: str) -> httpx.Response:
        return get_with_retries(
            self._http,
            url,
            params=params,
            limiter=self._limiter,
            sleep=self._sleep,
            max_retries=self.max_retries,
            backoff=self.backoff,
            label=label,
            error=EuropePmcError,
        )

    def search_pmid(self, pmid: str) -> bytes:
        """The raw JSON search response for one PMID."""
        params = {"query": EPMC_SEARCH_QUERY.format(pmid=pmid), **EPMC_SEARCH_PARAMS}
        return self._get(self.search_url, params, f"Europe PMC search for pmid:{pmid}").content

    def fetch_fulltext(self, pmcid: str) -> bytes:
        """The raw full-text XML for one open-access PMCID."""
        if not _PMCID_RE.match(pmcid):
            raise EuropePmcError(f"not a PMCID: {pmcid!r}")
        try:
            return self._get(self.fulltext_url.format(pmcid=pmcid), None, f"Europe PMC full text for {pmcid}").content
        except EuropePmcError as exc:
            if getattr(exc, "status_code", None) == 404:
                raise FullTextNotFoundError(str(exc)) from exc
            raise

    def fetch_pmc_page(self, pmcid: str) -> bytes:
        """The raw HTML of the PMC article page for one PMCID."""
        if not _PMCID_RE.match(pmcid):
            raise EuropePmcError(f"not a PMCID: {pmcid!r}")
        return self._get(self.pmc_page_url.format(pmcid=pmcid), None, f"PMC article page for {pmcid}").content


# ---------------------------------------------------------------------------
# Cache and lookup
# ---------------------------------------------------------------------------


class EuropePmcCache:
    """Raw search responses at ``<root>/europepmc/<pmid>.json``, full text at ``<root>/europepmc/<pmcid>.xml``."""

    def __init__(self, root: Path = DEFAULT_CACHE_ROOT):
        self.dir = Path(root) / "europepmc"

    def lookup_path(self, pmid: str) -> Path:
        if not pmid.isdigit():
            raise ValueError(f"PMID must be digits, got {pmid!r}")
        return self.dir / f"{pmid}.json"

    def fulltext_path(self, pmcid: str) -> Path:
        if not _PMCID_RE.match(pmcid):
            raise ValueError(f"PMCID must look like PMC123, got {pmcid!r}")
        return self.dir / f"{pmcid}.xml"

    def page_path(self, pmcid: str) -> Path:
        if not _PMCID_RE.match(pmcid):
            raise ValueError(f"PMCID must look like PMC123, got {pmcid!r}")
        return self.dir / f"{pmcid}.html"

    def write(self, path: Path, content: bytes) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


@dataclass(frozen=True)
class Lookup:
    """What Europe PMC says about one PMID. ``status``: open_access, not_open_access or not_found.

    ``in_pmc`` is Europe PMC's ``inPMC`` flag: the article is on PubMed Central, open access or not.
    """

    pmid: str
    status: str
    pmcid: str | None
    in_pmc: bool = False

    @property
    def open_access(self) -> bool:
        return self.status == "open_access"


def parse_lookup(pmid: str, raw: bytes | str) -> Lookup:
    """Read a search response. No hit → not_found; a PMCID with isOpenAccess "Y" → open_access."""
    try:
        data = json.loads(raw)
        hits = data["resultList"]["result"]
    except (ValueError, KeyError, TypeError) as exc:
        raise EuropePmcError(f"unreadable Europe PMC search response for pmid:{pmid}") from exc
    mine = [h for h in hits if isinstance(h, dict) and str(h.get("pmid") or h.get("id")) == pmid]
    if not mine:
        return Lookup(pmid, "not_found", None)
    hit = mine[0]
    pmcid = str(hit.get("pmcid") or "") or None
    if pmcid and not _PMCID_RE.match(pmcid):
        raise EuropePmcError(f"pmid:{pmid}: unexpected PMCID {pmcid!r} in the Europe PMC response")
    in_pmc = hit.get("inPMC") == "Y"
    if pmcid and hit.get("isOpenAccess") == "Y":
        return Lookup(pmid, "open_access", pmcid, in_pmc)
    return Lookup(pmid, "not_open_access", pmcid, in_pmc)


def is_placeholder_fulltext(xml: bytes | str) -> bool:
    """True if a JATS article is not full text: no body text, or only a short note that it is a PDF.

    The note is a body under 1,000 characters that contains "available as a PDF" (any case). Both the
    lookup and the citation check use this, so a placeholder is never read as the text of a paper.
    """
    root = _parse_article(xml)
    body = root if root.tag == "body" else root.find(".//body")
    text = _text(body)
    if not text:
        return True
    return len(text) < _PLACEHOLDER_MAX_CHARS and _PLACEHOLDER_MARKER in text.lower()


@dataclass(frozen=True)
class FullText:
    """Result of ``get_fulltext``.

    ``status``: open_access (``path`` holds real full text), pdf_only (the XML is a placeholder or has no body,
    nothing cached), pmc_no_xml (a PMC id is known, Europe PMC has no full-text XML for it), not_open_access or
    not_found (no PMC id known). ``pmcid`` is the PMC id used, from the lookup or from PubMed.
    """

    lookup: Lookup
    path: Path | None  # cached XML, only for real full text
    requests_made: int  # HTTP requests this call made (0 when everything came from the cache)
    status: str = STATUS_NOT_FOUND
    pmcid: str | None = None


def _lookup_is_stale(path: Path, lookup: Lookup, now: Callable[[], float]) -> bool:
    if lookup.open_access:
        return False
    return now() - path.stat().st_mtime > LOOKUP_MAX_AGE_DAYS * 86400


def get_fulltext(
    client: EuropePmcClient,
    cache: EuropePmcCache,
    pmid: str,
    *,
    refresh: bool = False,
    pmcid: str | None = None,
    now: Callable[[], float] = time.time,
) -> FullText:
    """Look the PMID up (cached) and make sure real full text is cached when there is any.

    ``pmcid`` is the PMC id from the PubMed record, for when Europe PMC's own record does not carry it yet.
    A cached lookup is requested again when ``refresh`` is set, or when it found no open-access full text and
    its file is older than ``LOOKUP_MAX_AGE_DAYS`` (``now`` is the clock, for tests). When a PMC id is known
    but the lookup gives no open-access record, the full-text XML is requested once per call. The XML is cached
    as ``<pmcid>.xml`` only when it has a real body; a placeholder gives ``pdf_only`` and nothing is written,
    and HTTP 404 gives ``pmc_no_xml``. No PDF is downloaded.
    """
    requests = 0
    lookup_path = cache.lookup_path(pmid)
    raw: bytes | None = None
    if lookup_path.is_file() and not refresh:
        raw = lookup_path.read_bytes()
        if _lookup_is_stale(lookup_path, parse_lookup(pmid, raw), now):
            raw = None
    if raw is None:
        raw = client.search_pmid(pmid)
        requests += 1
        parse_lookup(pmid, raw)  # raises before anything unreadable is cached
        cache.write(lookup_path, raw)
    lookup = parse_lookup(pmid, raw)
    known = lookup.pmcid or pmcid
    if known is None:
        return FullText(lookup, None, requests, lookup.status, None)
    xml_path = cache.fulltext_path(known)
    if xml_path.is_file() and not refresh:
        try:
            if not is_placeholder_fulltext(xml_path.read_bytes()):
                return FullText(lookup, xml_path, requests, STATUS_OPEN_ACCESS, known)
        except EuropePmcError:
            pass  # an unreadable cached file is requested again
    try:
        content = client.fetch_fulltext(known)
    except FullTextNotFoundError:
        return FullText(lookup, None, requests + 1, STATUS_PMC_NO_XML, known)
    requests += 1
    if is_placeholder_fulltext(content):  # also raises before anything unreadable is cached
        return FullText(lookup, None, requests, STATUS_PDF_ONLY, known)
    cache.write(xml_path, content)
    return FullText(lookup, xml_path, requests, STATUS_OPEN_ACCESS, known)


def read_cached_lookup(cache: EuropePmcCache, pmid: str) -> Lookup | None:
    """The cached lookup for a PMID, or None if none is cached. Never makes a request.

    Raises EuropePmcError if the cached file cannot be read.
    """
    path = cache.lookup_path(pmid)
    if not path.is_file():
        return None
    return parse_lookup(pmid, path.read_bytes())


@dataclass(frozen=True)
class PmcPage:
    """Result of ``get_pmc_page``. ``outcome``: open_access, no_pmcid, not_in_pmc, cached or fetched."""

    lookup: Lookup
    outcome: str
    path: Path | None  # cached page, only for cached / fetched
    requests_made: int


def get_pmc_page(client: EuropePmcClient, cache: EuropePmcCache, pmid: str, *, refresh: bool = False) -> PmcPage:
    """Cache the PMC article page of one PMID, if it has no open-access full text but is free to read on PMC.

    Looks the PMID up first (cached, like ``get_fulltext``). Nothing is requested for an open-access record
    (use ``get_fulltext``), for one without a PMCID, or for one whose ``inPMC`` is not "Y". A page already
    cached is not requested again unless ``refresh`` is set. A page is cached only if it parses.
    """
    requests = 0
    lookup_path = cache.lookup_path(pmid)
    if lookup_path.is_file() and not refresh:
        raw = lookup_path.read_bytes()
    else:
        raw = client.search_pmid(pmid)
        requests += 1
        parse_lookup(pmid, raw)
        cache.write(lookup_path, raw)
    lookup = parse_lookup(pmid, raw)
    if lookup.open_access:
        return PmcPage(lookup, "open_access", None, requests)
    if lookup.pmcid is None:
        return PmcPage(lookup, "no_pmcid", None, requests)
    if not lookup.in_pmc:
        return PmcPage(lookup, "not_in_pmc", None, requests)
    path = cache.page_path(lookup.pmcid)
    if path.is_file() and not refresh:
        return PmcPage(lookup, "cached", path, requests)
    content = client.fetch_pmc_page(lookup.pmcid)
    requests += 1
    parse_pmc_page(content, pmid)  # raises before anything unusable is cached
    cache.write(path, content)
    return PmcPage(lookup, "fetched", path, requests)


# ---------------------------------------------------------------------------
# Full text parsing and the case-definition finder
# ---------------------------------------------------------------------------


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _parse_article(content: bytes | str) -> ET.Element:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise EuropePmcError(f"unreadable full-text XML: {exc}") from exc
    for elem in root.iter():  # drop XML namespaces so tag names can be compared plainly
        elem.tag = _local(elem.tag)
    return root


def _text(elem: ET.Element | None) -> str:
    return " ".join("".join(elem.itertext()).split()) if elem is not None else ""


# Markup that runs on inside a line of text: no space is put between it and the text around it.
_INLINE_TAGS = frozenset(
    {
        "italic",
        "bold",
        "sup",
        "sub",
        "sc",
        "underline",
        "monospace",
        "roman",
        "sans-serif",
        "overline",
        "strike",
        "xref",
        "ext-link",
        "uri",
        "named-content",
        "styled-content",
        "inline-formula",
        "email",
        "i",
        "b",
        "em",
        "strong",
        "tt",
    }
)


def _flow_text(elem: ET.Element, out: list[str]) -> None:
    if elem.tag == "ref-list":
        return
    block = elem.tag not in _INLINE_TAGS
    if block:
        out.append(" ")
    if elem.text:
        out.append(elem.text)
    for child in elem:
        _flow_text(child, out)
        if child.tail:
            out.append(child.tail)
    if block:
        out.append(" ")


def article_text(xml: bytes | str) -> str:
    """The plain text of a JATS full-text article (front matter and body), whitespace collapsed.

    Block elements (paragraphs, titles, table cells) are separated by a space; inline markup such as
    ``<italic>`` or ``<sub>`` is not, so "CO<sub>2</sub>" reads "CO2". The reference list is left out.
    """
    root = _parse_article(xml)
    out: list[str] = []
    _flow_text(root, out)
    return " ".join("".join(out).split())


_METHODS_TITLE_RE = re.compile(
    r"method|^\W*(?:\d+[.\s]*)?(?:study\s+)?(?:participants|subjects|patients|population|design)\b", re.IGNORECASE
)
_METHODS_TYPE_RE = re.compile(r"method|subjects|participants", re.IGNORECASE)


def _is_methods(sec: ET.Element) -> bool:
    return bool(
        _METHODS_TYPE_RE.search(sec.get("sec-type") or "") or _METHODS_TITLE_RE.search(_text(sec.find("title")))
    )


def _paragraphs(elem: ET.Element) -> list[str]:
    return [t for t in (_text(p) for p in elem.iter("p")) if t]


def _outermost_methods(parent: ET.Element) -> list[ET.Element]:
    found: list[ET.Element] = []
    for child in parent:
        if child.tag != "sec":
            continue
        if _is_methods(child):
            found.append(child)
        else:
            found += _outermost_methods(child)
    return found


_ABBREVIATION_END_RE = re.compile(r"(?:\b(?:et al|e\.g|i\.e|vs|Dr|Prof|Fig|Figs|No|approx|ca|cf)|\b[A-Z])\.$")
_SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"'])")


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences, not breaking after common abbreviations ("et al.", "e.g.")."""
    sentences: list[str] = []
    for piece in _SENTENCE_BREAK_RE.split(text.strip()):
        if sentences and _ABBREVIATION_END_RE.search(sentences[-1]):
            sentences[-1] = f"{sentences[-1]} {piece}"
        elif piece:
            sentences.append(piece)
    return sentences


# Wordings that name a case definition. These only select sentences for a reader; they are not a mapping
# to the card's case_definition values, and several (CDC, "case definition") name no particular definition.
CASE_DEFINITION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bFukuda\b",
        r"\bHolmes\b",
        r"\b(?:1994|1988)\b[^.]{0,60}\b(?:CDC|Centers? for Disease Control)\b",
        r"\b(?:CDC|Centers? for Disease Control)\b[^.]{0,60}\b(?:1994|1988)\b",
        r"\bCDC\b",
        r"\bCenters? for Disease Control\b",
        r"\bCanadian (?:Consensus|case|criteria|clinical)",
        r"\bCarruthers\b",
        r"\bCCC\b",
        r"\bInternational Consensus Criteria\b",
        r"\bICC\b",
        r"\bInstitute of Medicine\b",
        r"\bIOM\b",
        r"\bSEID\b",
        r"\bsystemic exertion intolerance\b",
        # "Oxford" as a case definition, not as an affiliation, publisher, place or vendor.
        r"(?<!University of )(?<!Univ\. of )(?<!Univ of )\bOxford\b"
        r"(?!\s+(?:University|Instruments|Nanopore|Immunotec|Biomedica|Brookes|Press)\b)"
        r"(?!,\s*(?:UK|U\.K\.|United Kingdom|England)\b)",
        r"\bSharpe\b",
        r"\bcase definitions?\b",
        r"\bdiagnostic criteria\b",
        r"\bmet (?:the )?(?:\w+ ){0,3}criteria\b",
        r"\bdiagnosed (?:according|using|with|by|based)\b",
    )
)


# A sentence that excludes people with the illness itself: both an exclusion wording and the illness must be
# there. Whether ME/CFS was what the study excluded is for the reader to check; the finder only lists it.
EXCLUSION_WORDING = re.compile(r"\bexclu(?:d\w*|sion\w*)\b", re.IGNORECASE)
ILLNESS_WORDING = re.compile(r"\b(?:ME/CFS|CFS|chronic fatigue syndrome|myalgic encephalomyelitis)\b", re.IGNORECASE)


@dataclass(frozen=True)
class CaseDefinitionCandidate:
    """A sentence that may name a case definition, or may exclude people with the illness.

    ``sentence`` is verbatim (whitespace collapsed). ``kind`` is "definition" (a case-definition wording) or
    "exclusion" (an exclusion wording together with the illness); a sentence that is both gives two candidates.
    """

    section: str  # title of the section the sentence is in ("body" for text outside any titled section)
    scope: str  # "methods" if found in a methods section, "body" if the article has none and the body was used
    sentence: str
    matched: tuple[str, ...]  # the matched wording as it appears in the sentence
    kind: str = "definition"


def _candidates(section: str, scope: str, paragraphs: Sequence[str]) -> list[CaseDefinitionCandidate]:
    out: list[CaseDefinitionCandidate] = []
    for paragraph in paragraphs:
        for sentence in split_sentences(paragraph):
            matched: list[str] = []
            for pattern in CASE_DEFINITION_PATTERNS:
                matched += [m.group(0) for m in pattern.finditer(sentence)]
            if matched:
                out.append(CaseDefinitionCandidate(section, scope, sentence, tuple(dict.fromkeys(matched))))
            excluding = [m.group(0) for m in EXCLUSION_WORDING.finditer(sentence)]
            illness = [m.group(0) for m in ILLNESS_WORDING.finditer(sentence)]
            if excluding and illness:
                words = tuple(dict.fromkeys(excluding + illness))
                out.append(CaseDefinitionCandidate(section, scope, sentence, words, "exclusion"))
    return out


def find_case_definitions(xml: bytes | str) -> list[CaseDefinitionCandidate]:
    """Candidate case-definition sentences from a JATS full-text article.

    Looks in the methods section(s); if the article has none, in the whole body. Returns candidates with
    their section and the verbatim sentence; it never decides which definition a sentence means.
    """
    root = _parse_article(xml)
    body = root if root.tag == "body" else root.find(".//body")
    if body is None:
        return []
    methods = _outermost_methods(body)
    if methods:
        found: list[CaseDefinitionCandidate] = []
        for sec in methods:
            found += _candidates(_text(sec.find("title")) or "methods", "methods", _paragraphs(sec))
        return found
    found = []
    loose = [t for t in (_text(p) for p in body.findall("p")) if t]
    found += _candidates("body", "body", loose)
    for sec in body.findall("sec"):
        found += _candidates(_text(sec.find("title")) or "body", "body", _paragraphs(sec))
    return found


# ---------------------------------------------------------------------------
# PMC article page (HTML)
# ---------------------------------------------------------------------------

_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"})
_SKIPPED_TAGS = frozenset({"script", "style", "noscript", "template", "nav", "header", "footer", "svg", "button"})
_HTML_INLINE_TAGS = frozenset(
    {"a", "abbr", "b", "bdi", "bdo", "cite", "code", "em", "i", "mark", "q", "s", "small", "span", "strong"}
    | {"sub", "sup", "u", "var", "kbd", "samp", "time"}
)
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[_Node | str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def iter(self):
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.iter()


class _TreeBuilder(HTMLParser):
    """A forgiving HTML tree: unmatched end tags are ignored, unclosed tags are closed by their parent's end."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root")
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, {k: v or "" for k, v in attrs})
        self._stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._stack[-1].children.append(_Node(tag, {k: v or "" for k, v in attrs}))

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        self._stack[-1].children.append(data)


def _parse_html(content: bytes | str) -> _Node:
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    builder = _TreeBuilder()
    builder.feed(text)
    builder.close()
    return builder.root


def _is_skipped(node: _Node) -> bool:
    return node.tag in _SKIPPED_TAGS or "ref-list" in node.classes


def _html_flow(node: _Node, out: list[str]) -> None:
    if _is_skipped(node):
        return
    block = node.tag not in _HTML_INLINE_TAGS
    if block:
        out.append(" ")
    for child in node.children:
        if isinstance(child, str):
            out.append(child)
        else:
            _html_flow(child, out)
    if block:
        out.append(" ")


def _html_text(node: _Node) -> str:
    out: list[str] = []
    _html_flow(node, out)
    return " ".join("".join(out).split())


def _page_pmids(root: _Node) -> list[str]:
    return [
        n.attrs.get("content", "") for n in root.iter() if n.tag == "meta" and n.attrs.get("name") == "citation_pmid"
    ]


def _html_article_parts(root: _Node, pmid: str) -> tuple[_Node, list[_Node]]:
    """Validate a PMC page and return its main article body and any abstract section outside the body."""
    ids = _page_pmids(root)
    if not ids:
        raise EuropePmcError("the PMC page has no citation_pmid meta tag; it is not an article page")
    if pmid not in ids:
        raise EuropePmcError(f"the PMC page is for pmid:{ids[0]}, not pmid:{pmid}")
    bodies = [n for n in root.iter() if n.tag == "section" and "main-article-body" in n.classes]
    if not bodies:
        raise EuropePmcError("the PMC page has no main article body (section class main-article-body)")
    body = bodies[0]
    if not _html_text(body):
        raise EuropePmcError("the main article body of the PMC page has no text")
    inside = {id(n) for n in body.iter()}
    abstracts = [n for n in root.iter() if n.tag == "section" and "abstract" in n.classes and id(n) not in inside]
    return body, abstracts


def parse_pmc_page(content: bytes | str, pmid: str) -> None:
    """Raise EuropePmcError unless the page is the article page of ``pmid`` with a main article body."""
    _html_article_parts(_parse_html(content), pmid)


def pmc_page_text(content: bytes | str) -> str:
    """The plain text of a cached PMC article page: abstract and main article body, whitespace collapsed.

    The reference list, navigation, header, footer and scripts are left out. Block elements are separated by
    a space; inline markup is not, so a footnote link reads "CFS1", as in ``article_text``.
    """
    root = _parse_html(content)
    ids = _page_pmids(root)
    body, abstracts = _html_article_parts(root, ids[0] if ids else "")
    return " ".join(" ".join(_html_text(n) for n in [*abstracts, body]).split())


def _heading(sec: _Node) -> str:
    for child in sec.children:
        if isinstance(child, _Node) and child.tag in _HEADING_TAGS:
            return _html_text(child)
    return ""


def _html_paragraphs(node: _Node) -> list[str]:
    out: list[str] = []

    def walk(n: _Node) -> None:
        if _is_skipped(n):
            return
        if n.tag == "p":
            t = _html_text(n)
            if t:
                out.append(t)
            return
        for c in n.children:
            if isinstance(c, _Node):
                walk(c)

    walk(node)
    return out


def _html_sections(parent: _Node) -> list[_Node]:
    return [c for c in parent.children if isinstance(c, _Node) and c.tag == "section" and "abstract" not in c.classes]


def _html_outermost_methods(parent: _Node) -> list[_Node]:
    found: list[_Node] = []
    for child in _html_sections(parent):
        if _METHODS_TITLE_RE.search(_heading(child)):
            found.append(child)
        else:
            found += _html_outermost_methods(child)
    return found


def find_case_definitions_in_page(content: bytes | str) -> list[CaseDefinitionCandidate]:
    """Candidate case-definition sentences from a cached PMC article page (same rules as the XML finder).

    Looks in the methods sections of the main article body (the abstract is left to PubMed); if there are
    none, in the whole body. Never decides which definition a sentence means.
    """
    root = _parse_html(content)
    ids = _page_pmids(root)
    body, _ = _html_article_parts(root, ids[0] if ids else "")
    methods = _html_outermost_methods(body)
    found: list[CaseDefinitionCandidate] = []
    if methods:
        for sec in methods:
            found += _candidates(_heading(sec) or "methods", "methods", _html_paragraphs(sec))
        return found
    loose = [t for t in (_html_text(c) for c in body.children if isinstance(c, _Node) and c.tag == "p") if t]
    found += _candidates("body", "body", loose)
    for sec in _html_sections(body):
        found += _candidates(_heading(sec) or "body", "body", _html_paragraphs(sec))
    return found


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

STATUS_TEXT = {
    "open_access": "open access",
    "not_open_access": "no open full text",
    "not_found": "not found in Europe PMC",
    "pdf_only": "PMC record, full text is a PDF only (not read)",
    "pmc_no_xml": "PMC record, no full-text XML in Europe PMC",
}


def _cached_pubmed_pmcid(cache: EuropePmcCache, pmid: str) -> str | None:
    """The PMC id in the cached PubMed record of ``pmid``, or None (no record, or one that cannot be read)."""
    path = cache.dir.parent / "pubmed" / f"{pmid}.xml"
    try:
        return parse_xml(path.read_bytes()).pmcid
    except (OSError, ParseError):
        return None


PMC_OUTCOME_TEXT = {
    "open_access": "open access; use `fulltext`, nothing fetched",
    "no_pmcid": "no PMCID in Europe PMC; nothing fetched",
    "not_in_pmc": "not in PubMed Central (inPMC is not Y); nothing fetched",
    "cached": "free to read on PMC (page already cached)",
    "fetched": "free to read on PMC (page fetched)",
}


def _pmid(text: str) -> str:
    value = text.removeprefix("pmid:")
    if not value.isdigit():
        raise argparse.ArgumentTypeError(f"not a PMID (digits, optionally 'pmid:' first): {text!r}")
    return value


def _print_candidates(candidates: Sequence[CaseDefinitionCandidate]) -> None:
    for c in candidates:
        mark = " [exclusion]" if c.kind == "exclusion" else ""
        print(f"  [{c.section}{'' if c.scope == 'methods' else ', body'}]{mark} {c.sentence}")
        print(f"    matched: {', '.join(c.matched)}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m me_atlas.europepmc", description="Europe PMC full-text tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("fulltext", "look PMIDs up and cache open-access full text"),
        ("casedef", "show sentences in the methods section that name a case definition"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("pmids", nargs="*", type=_pmid, metavar="PMID")
        if name == "casedef":
            cmd.add_argument("--card", type=Path, help="read every pmid: study id from this card or draft")
        cmd.add_argument("--refresh", action="store_true", help="request again even if cached")
        cmd.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_ROOT, help="default: %(default)s")
    pmc = sub.add_parser(
        "pmcpage", help="cache the free-to-read PMC page of cited PMIDs, show case-definition candidates"
    )
    pmc.add_argument("pmids", nargs="+", type=_pmid, metavar="PMID")
    pmc.add_argument("--card", type=Path, required=True, help="the card or draft that cites these PMIDs")
    pmc.add_argument("--refresh", action="store_true", help="request again even if cached")
    pmc.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_ROOT, help="default: %(default)s")
    return parser


def _card_pmids(path: Path) -> list[str]:
    card = load_card(path)
    pmids = [s.id.removeprefix("pmid:") for s in card.studies if s.id.startswith("pmid:")]
    skipped = [s.id for s in card.studies if not s.id.startswith("pmid:")]
    if skipped:
        print(f"note: skipping study ids that are not PubMed ids: {', '.join(skipped)}", file=sys.stderr)
    return pmids


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Entry point. ``env`` is given by tests; otherwise ``.env`` and the process environment are used."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    card_path: Path | None = getattr(args, "card", None)
    if args.command == "pmcpage":
        return _pmcpage_main(args, env, transport, clock, sleep)
    if bool(args.pmids) == bool(card_path):
        parser.error("give PMIDs or --card <path> (casedef only), but not both and not neither")
    if env is None:
        env = {**load_dotenv(), **os.environ}
    email = (env.get("CONTACT_EMAIL") or "").strip()
    if not email:
        print(
            "error: CONTACT_EMAIL is not set. Europe PMC asks for a contact address in the User-Agent; "
            "set CONTACT_EMAIL in .env or the environment (see .env.example).",
            file=sys.stderr,
        )
        return 2

    if card_path:
        try:
            pmids = _card_pmids(card_path)
        except Exception as exc:  # CardValidationError lists every problem; show it as is
            print(f"error: cannot read {card_path}: {exc}", file=sys.stderr)
            return 1
    else:
        pmids = list(dict.fromkeys(args.pmids))

    cache = EuropePmcCache(args.cache_dir)
    client = EuropePmcClient(email, transport=transport, clock=clock, sleep=sleep)
    exit_code = 0
    try:
        for pmid in pmids:
            try:
                result = get_fulltext(
                    client, cache, pmid, refresh=args.refresh, pmcid=_cached_pubmed_pmcid(cache, pmid)
                )
                line = f"pmid:{pmid}  {STATUS_TEXT[result.status]}"
                if result.pmcid:
                    line += f"  {result.pmcid}"
                if args.command == "fulltext":
                    print(line + (f"  {result.path}" if result.path else ""))
                    continue
                candidates = find_case_definitions(result.path.read_bytes()) if result.path else []
                if result.path:
                    line += f"  {len(candidates)} candidate sentence(s)"
                print(line)
                _print_candidates(candidates)
            except EuropePmcError as exc:
                print(f"pmid:{pmid}  error: {exc}", file=sys.stderr)
                exit_code = 1
    finally:
        client.close()
    return exit_code


def _pmcpage_main(args, env, transport, clock, sleep) -> int:
    try:
        on_card = _card_pmids(args.card)
    except Exception as exc:  # CardValidationError lists every problem; show it as is
        print(f"error: cannot read {args.card}: {exc}", file=sys.stderr)
        return 1
    pmids = list(dict.fromkeys(args.pmids))
    stray = [p for p in pmids if p not in on_card]
    if stray:
        print(
            f"error: {', '.join(f'pmid:{p}' for p in stray)} is not a pmid: study on {args.card}; "
            "pmcpage fetches only articles cited on the card or draft it is given. Nothing was requested.",
            file=sys.stderr,
        )
        return 1
    if env is None:
        env = {**load_dotenv(), **os.environ}
    email = (env.get("CONTACT_EMAIL") or "").strip()
    if not email:
        print("error: CONTACT_EMAIL is not set (see .env.example).", file=sys.stderr)
        return 2
    cache = EuropePmcCache(args.cache_dir)
    client = EuropePmcClient(email, transport=transport, clock=clock, sleep=sleep)
    exit_code = 0
    try:
        for pmid in pmids:
            try:
                result = get_pmc_page(client, cache, pmid, refresh=args.refresh)
                line = f"pmid:{pmid}  {PMC_OUTCOME_TEXT[result.outcome]}"
                if result.lookup.pmcid:
                    line += f"  {result.lookup.pmcid}"
                if result.path is None:
                    print(line)
                    continue
                candidates = find_case_definitions_in_page(result.path.read_bytes())
                print(f"{line}  {result.path}  {len(candidates)} candidate sentence(s)")
                _print_candidates(candidates)
            except EuropePmcError as exc:
                print(f"pmid:{pmid}  error: {exc}", file=sys.stderr)
                exit_code = 1
    finally:
        client.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
