"""Europe PMC full text, on demand, and a finder for case-definition sentences.

Command line::

    uv run python -m me_atlas.europepmc fulltext <pmid>...
    uv run python -m me_atlas.europepmc casedef <pmid>...
    uv run python -m me_atlas.europepmc casedef --card drafts/<slug>.yaml

``fulltext`` looks each PMID up in Europe PMC and, for open-access records, downloads the full-text XML
into ``data/cache/europepmc/<pmcid>.xml`` (the lookup itself is cached as ``<pmid>.json``). ``casedef``
does the same and then prints the sentences of the methods section (or, if the article has none, of the
whole body) that name a case definition. The finder only returns candidates: which definition a sentence
means, and what goes on a card, is a human or agent judgement. Full text stays in the gitignored cache.

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
from dataclasses import dataclass
from pathlib import Path

import httpx

from me_atlas.cards import load_card
from me_atlas.http import RateLimiter, get_with_retries, load_dotenv

# Endpoint URLs of the Europe PMC REST API. Confirmed against the live service on 2026-10-31 (plan step 7):
# lookups and fullTextXML worked for 18 PMIDs cited on the first two draft cards.
EPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EPMC_FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
# Search for one PubMed record by its PMID (source MED); the JSON "lite" result carries pmcid and isOpenAccess.
EPMC_SEARCH_QUERY = "EXT_ID:{pmid} AND SRC:MED"
EPMC_SEARCH_PARAMS: dict[str, str | int] = {"format": "json", "resultType": "lite", "pageSize": 5}

TOOL_NAME = "me-atlas"
RATE_LIMIT = 3
DEFAULT_CACHE_ROOT = Path("data/cache")

_PMCID_RE = re.compile(r"^PMC\d+$")


class EuropePmcError(Exception):
    """A request to Europe PMC failed for good, or the response could not be understood."""


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
    ):
        if not email:
            raise ValueError("an email address is required for Europe PMC requests")
        self.email = email
        self.max_retries = max_retries
        self.backoff = backoff
        self.search_url = search_url
        self.fulltext_url = fulltext_url
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
        return self._get(self.fulltext_url.format(pmcid=pmcid), None, f"Europe PMC full text for {pmcid}").content


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

    def write(self, path: Path, content: bytes) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


@dataclass(frozen=True)
class Lookup:
    """What Europe PMC says about one PMID. ``status``: open_access, not_open_access or not_found."""

    pmid: str
    status: str
    pmcid: str | None

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
    if pmcid and hit.get("isOpenAccess") == "Y":
        return Lookup(pmid, "open_access", pmcid)
    return Lookup(pmid, "not_open_access", pmcid)


@dataclass(frozen=True)
class FullText:
    lookup: Lookup
    path: Path | None  # cached XML, only for open access
    requests_made: int  # HTTP requests this call made (0 when everything came from the cache)


def get_fulltext(client: EuropePmcClient, cache: EuropePmcCache, pmid: str, *, refresh: bool = False) -> FullText:
    """Look the PMID up (cached) and, if the record is open access, make sure its full text is cached.

    Nothing is requested for a record that is not open access, and nothing already cached is requested
    again unless ``refresh`` is set.
    """
    requests = 0
    lookup_path = cache.lookup_path(pmid)
    if lookup_path.is_file() and not refresh:
        raw = lookup_path.read_bytes()
    else:
        raw = client.search_pmid(pmid)
        requests += 1
        parse_lookup(pmid, raw)  # raises before anything unreadable is cached
        cache.write(lookup_path, raw)
    lookup = parse_lookup(pmid, raw)
    if not lookup.open_access or lookup.pmcid is None:
        return FullText(lookup, None, requests)
    xml_path = cache.fulltext_path(lookup.pmcid)
    if refresh or not xml_path.is_file():
        content = client.fetch_fulltext(lookup.pmcid)
        requests += 1
        _parse_article(content)  # raises before anything unreadable is cached
        cache.write(xml_path, content)
    return FullText(lookup, xml_path, requests)


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
        r"\bOxford\b",
        r"\bSharpe\b",
        r"\bcase definitions?\b",
        r"\bdiagnostic criteria\b",
        r"\bmet (?:the )?(?:\w+ ){0,3}criteria\b",
        r"\bdiagnosed (?:according|using|with|by|based)\b",
    )
)


@dataclass(frozen=True)
class CaseDefinitionCandidate:
    """A sentence that may name a case definition. ``sentence`` is verbatim (whitespace collapsed)."""

    section: str  # title of the section the sentence is in ("body" for text outside any titled section)
    scope: str  # "methods" if found in a methods section, "body" if the article has none and the body was used
    sentence: str
    matched: tuple[str, ...]  # the matched wording as it appears in the sentence


def _candidates(section: str, scope: str, paragraphs: Sequence[str]) -> list[CaseDefinitionCandidate]:
    out: list[CaseDefinitionCandidate] = []
    for paragraph in paragraphs:
        for sentence in split_sentences(paragraph):
            matched: list[str] = []
            for pattern in CASE_DEFINITION_PATTERNS:
                matched += [m.group(0) for m in pattern.finditer(sentence)]
            if matched:
                out.append(CaseDefinitionCandidate(section, scope, sentence, tuple(dict.fromkeys(matched))))
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
# Command line
# ---------------------------------------------------------------------------

STATUS_TEXT = {
    "open_access": "open access",
    "not_open_access": "no open full text",
    "not_found": "not found in Europe PMC",
}


def _pmid(text: str) -> str:
    value = text.removeprefix("pmid:")
    if not value.isdigit():
        raise argparse.ArgumentTypeError(f"not a PMID (digits, optionally 'pmid:' first): {text!r}")
    return value


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
                result = get_fulltext(client, cache, pmid, refresh=args.refresh)
                line = f"pmid:{pmid}  {STATUS_TEXT[result.lookup.status]}"
                if result.lookup.pmcid:
                    line += f"  {result.lookup.pmcid}"
                if args.command == "fulltext":
                    print(line + (f"  {result.path}" if result.path else ""))
                    continue
                candidates = find_case_definitions(result.path.read_bytes()) if result.path else []
                if result.path:
                    line += f"  {len(candidates)} candidate sentence(s)"
                print(line)
                for c in candidates:
                    print(f"  [{c.section}{'' if c.scope == 'methods' else ', body'}] {c.sentence}")
                    print(f"    matched: {', '.join(c.matched)}")
            except EuropePmcError as exc:
                print(f"pmid:{pmid}  error: {exc}", file=sys.stderr)
                exit_code = 1
    finally:
        client.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
