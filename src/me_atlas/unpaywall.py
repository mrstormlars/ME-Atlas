"""Open PDF copies found through Unpaywall: lookup, download, text, word-for-word quote matching, founder's check.

Command line::

    uv run python -m me_atlas.unpaywall fetch --card PATH [PMID...] [--refresh] [--cache-dir DIR]
    uv run python -m me_atlas.unpaywall casedef --card PATH [PMID...] [--refresh] [--cache-dir DIR]
    uv run python -m me_atlas.unpaywall pending [--card PATH]...
    uv run python -m me_atlas.unpaywall confirm --card PATH PMID

The DOI of a ``pmid:`` study is read from its cached PubMed record, never from the card. Unpaywall
(``GET https://api.unpaywall.org/v2/<doi>?email=<CONTACT_EMAIL>``) names the open copies; only a PDF of a published or
an accepted version, not hosted by PubMed Central or Europe PMC, is downloaded, through the generic client of
``me_atlas.resources`` (robots.txt, one request a second per host, no cookies, nothing worked around). The PDF must
carry the PubMed title in its first two pages. The text goes to ``data/cache/unpaywall/pdf/`` (gitignored, never
redistributed). ``CONTACT_EMAIL`` is sent to Unpaywall only and is never written to any file.

A quote from a PDF passes only if it is found word for word (``citations.normalise_quote``), with each line-break
hyphen read either as removed or as a hyphen. Every ``fulltext_pdf`` quote also needs the founder's confirmation in
``confirmations/pdf-quotes.yaml``; only the founder runs ``confirm``. See ``docs/plan-unpaywall-pdf.md`` and
``docs/fetch.md``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import io
import json
import os
import re
import sys
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote as url_quote
from urllib.parse import urlsplit

import httpx
import yaml

from me_atlas.cards import load_card
from me_atlas.europepmc import CaseDefinitionCandidate, _candidates
from me_atlas.http import RateLimiter, get_with_retries, load_dotenv
from me_atlas.pubmed import DEFAULT_CACHE_ROOT, ParseError, PubMedRecord, RawCache
from me_atlas.resources import Fetcher
from me_atlas.trials import USER_AGENT

API_URL = "https://api.unpaywall.org/v2/"
LOOKUP_MAX_AGE_DAYS = 7
MAX_PDF_BYTES = 30 * 1024 * 1024
MIN_TEXT_CHARS = 50  # fewer letters and digits than this in the whole PDF: no text layer (a scan), not used
TITLE_PAGES = 2
DEFAULT_CONFIRMATIONS = Path("confirmations/pdf-quotes.yaml")
SOURCE = "fulltext_pdf"
EXTRACTOR = "pdfminer.six"

# A PDF host that is never used: PubMed Central answers automated requests with a bot check, and Europe PMC's own text
# is read as XML.
REJECTED_HOSTS = ("ncbi.nlm.nih.gov", "europepmc.org", "ebi.ac.uk")
ACCEPTED_VERSIONS = ("publishedVersion", "acceptedVersion")  # in this order; submittedVersion is never used

LINE_BREAK_HYPHEN = "\ue000"  # marks a hyphen at the end of a line between letters (private-use character)
SLASH_BREAK = "\ue001"  # a line break right after a slash: read as nothing or as a space
PAGE_BREAK = "\f"
_REFERENCE_HEADINGS = frozenset({"references", "bibliography", "literature cited"})
_LINE_BREAK_HYPHEN_RE = re.compile(r"(?<=[^\W\d_])[-\u2010][ \t]*\n[ \t]*(?=[^\W\d_])")
_SLASH_BREAK_RE = re.compile(r"/[ \t]*\n[ \t]*(?=\S)")
_SOFT_HYPHEN_BREAK_RE = re.compile(r"\u00ad[ \t]*\n[ \t]*")
_KEY_SAFE = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._-")


def normalise_quote(text: str) -> str:
    """``citations.normalise_quote`` (imported on use: ``citations`` imports this module)."""
    from me_atlas.citations import normalise_quote as normalise

    return normalise(text)


class UnpaywallError(Exception):
    """A request or a step failed; the message says what (and never holds the contact address)."""


# ---------------------------------------------------------------------------
# Cache layout
# ---------------------------------------------------------------------------


def cache_key(doi: str) -> str:
    """The lowercase DOI with every character outside ``[a-z0-9._-]`` percent-encoded (UTF-8 bytes, upper-case hex)."""
    out: list[str] = []
    for char in doi.strip().lower():
        if char in _KEY_SAFE:
            out.append(char)
        else:
            out.extend(f"%{byte:02X}" for byte in char.encode("utf-8"))
    return "".join(out)


class UnpaywallCache:
    """``<root>/unpaywall/<key>.json`` (the raw answer) and ``<root>/unpaywall/pdf/<key>.{pdf,txt,meta.json}``."""

    def __init__(self, root: Path = DEFAULT_CACHE_ROOT):
        self.dir = Path(root) / "unpaywall"
        self.pdf_dir = self.dir / "pdf"

    def answer_path(self, doi: str) -> Path:
        return self.dir / f"{cache_key(doi)}.json"

    def pdf_path(self, doi: str) -> Path:
        return self.pdf_dir / f"{cache_key(doi)}.pdf"

    def text_path(self, doi: str) -> Path:
        return self.pdf_dir / f"{cache_key(doi)}.txt"

    def meta_path(self, doi: str) -> Path:
        return self.pdf_dir / f"{cache_key(doi)}.meta.json"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


@dataclass(frozen=True)
class CachedPdf:
    """The extracted text of a cached PDF copy and its metadata."""

    text: str
    meta: dict[str, Any]


def read_cached_pdf(root: Path, doi: str) -> CachedPdf | None:
    """The cached text and meta of the PDF of ``doi``, or None when there is no (readable) cached PDF text."""
    cache = UnpaywallCache(root)
    try:
        text = cache.text_path(doi).read_text(encoding="utf-8")
        meta = json.loads(cache.meta_path(doi).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return CachedPdf(text, meta) if isinstance(meta, dict) else None


def pubmed_doi_and_title(root: Path, pmid: str) -> tuple[str | None, str] | None:
    """(DOI, title) of the cached PubMed record of ``pmid``; None when there is no readable record."""
    try:
        record: PubMedRecord = RawCache(root).read_record(pmid)
    except (OSError, ParseError):
        return None
    return (record.doi or None), record.title


# ---------------------------------------------------------------------------
# Choosing a copy
# ---------------------------------------------------------------------------


def _host_rejected(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in REJECTED_HOSTS)


def choose_locations(answer: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The ``oa_locations`` worth trying, in order. Only a location with a PDF address, of a published or accepted
    version, whose PDF host is not PubMed Central or Europe PMC. ``oa_locations_embargoed`` is never read. Order:
    publishedVersion before acceptedVersion, publisher before repository, ``is_best`` first, then Unpaywall's order."""
    locations = answer.get("oa_locations")
    if not isinstance(locations, list):
        return []
    ranked: list[tuple[tuple[int, int, int, int], dict[str, Any]]] = []
    for index, loc in enumerate(locations):
        if not isinstance(loc, dict):
            continue
        url = loc.get("url_for_pdf")
        if not isinstance(url, str) or urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).netloc:
            continue
        version = loc.get("version")
        if version not in ACCEPTED_VERSIONS or _host_rejected(url):
            continue
        host_rank = {"publisher": 0, "repository": 1}.get(loc.get("host_type"), 2)
        ranked.append(
            ((ACCEPTED_VERSIONS.index(version), host_rank, 0 if loc.get("is_best") is True else 1, index), loc)
        )
    return [loc for _, loc in sorted(ranked, key=lambda item: item[0])]


# ---------------------------------------------------------------------------
# Text: extraction, cleaning, the matcher
# ---------------------------------------------------------------------------


def extract_pdf_pages(data: bytes) -> list[str]:
    """The raw text of every page, in pdfminer's layout order (boxes, so two columns are read column by column)."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTTextContainer

    pages: list[str] = []
    for layout in extract_pages(io.BytesIO(data), laparams=LAParams()):
        pages.append("".join(el.get_text() for el in layout if isinstance(el, LTTextContainer)))
    return pages


def clean_pages(raw_pages: Sequence[str]) -> tuple[str, bool]:
    """The text of a PDF as stored: NFKC, soft hyphens removed, the reference list cut, a line-end hyphen between
    letters marked (``LINE_BREAK_HYPHEN``), line breaks and whitespace collapsed, one form feed between pages.
    Returns the text and whether a reference list was cut."""
    pages: list[str] = []
    for raw in raw_pages:
        page = unicodedata.normalize("NFKC", raw)
        page = _SOFT_HYPHEN_BREAK_RE.sub("", page).replace("­", "")
        pages.append(page.replace("\r\n", "\n").replace("\r", "\n"))
    total = sum(len(p) + 1 for p in pages)
    cut: tuple[int, int] | None = None  # (page index, line index) of the last reference heading
    offset = 0
    cut_offset = 0
    for pi, page in enumerate(pages):
        position = offset
        for li, line in enumerate(page.split("\n")):
            if line.strip().lower() in _REFERENCE_HEADINGS:
                cut, cut_offset = (pi, li), position
            position += len(line) + 1
        offset += len(page) + 1
    cut_applied = cut is not None and cut_offset * 2 > total
    if cut_applied and cut is not None:
        pi, li = cut
        pages = pages[: pi + 1]
        pages[pi] = "\n".join(pages[pi].split("\n")[:li])
    cleaned = []
    for page in pages:
        marked = _SLASH_BREAK_RE.sub("/" + SLASH_BREAK, page)
        marked = _LINE_BREAK_HYPHEN_RE.sub(LINE_BREAK_HYPHEN, marked)
        cleaned.append(" ".join(marked.split()))
    return PAGE_BREAK.join(cleaned), cut_applied


def has_text_layer(text: str) -> bool:
    return len(re.findall(r"[^\W_]", text)) >= MIN_TEXT_CHARS


def _reduce(text: str) -> str:
    """Lowercase letters and digits only (NFKC first): line breaks, hyphenation and ligatures do not matter."""
    return "".join(c for c in unicodedata.normalize("NFKC", text).lower() if c.isascii() and c.isalnum())


def title_in_first_pages(title: str, text: str) -> bool:
    """Whether the PubMed title is in the text of the first two pages (both reduced to lowercase letters and digits)."""
    wanted = _reduce(title)
    head = join_markers("".join(text.split(PAGE_BREAK)[:TITLE_PAGES]))
    return bool(wanted) and wanted in _reduce(head)


def join_markers(page: str) -> str:
    """The page with every line-break marker read as nothing (what candidate sentences and the context show)."""
    return page.replace(LINE_BREAK_HYPHEN, "").replace(SLASH_BREAK, "")


def _variants(page: str) -> tuple[str, ...]:
    """Every reading of a page: each line-break hyphen as nothing or "-", each slash line break as nothing or a
    space. No other whitespace becomes flexible."""
    hyphens = ("", "-") if LINE_BREAK_HYPHEN in page else ("",)
    slashes = ("", " ") if SLASH_BREAK in page else ("",)
    return tuple(page.replace(LINE_BREAK_HYPHEN, h).replace(SLASH_BREAK, sl) for h in hyphens for sl in slashes)


def quote_page(quote: str, text: str) -> int | None:
    """The 1-based number of the first page on which ``quote`` is found word for word, else None. Both sides go
    through ``normalise_quote``; each line-break hyphen is read as removed or as a hyphen (two texts). A quote is
    looked for page by page: a sentence broken by a page break does not match."""
    needle = normalise_quote(quote)
    if not needle:
        return None
    for number, page in enumerate(text.split(PAGE_BREAK), start=1):
        if any(needle in normalise_quote(variant) for variant in _variants(page)):
            return number
    return None


def quote_in_pdf_text(quote: str, text: str) -> bool:
    return quote_page(quote, text) is not None


def pdf_candidates(text: str) -> list[tuple[int, CaseDefinitionCandidate]]:
    """Sentences that may name a case definition or exclude people with the illness, with their page number. Taken
    from the text with line-break hyphens removed, so a copied sentence matches."""
    found: list[tuple[int, CaseDefinitionCandidate]] = []
    for number, page in enumerate(text.split(PAGE_BREAK), start=1):
        found += [(number, c) for c in _candidates("body", "body", [join_markers(page)])]
    return found


# ---------------------------------------------------------------------------
# The finder
# ---------------------------------------------------------------------------


@dataclass
class CopyResult:
    """The outcome for one study. ``status`` is ``ok`` or why no copy is used."""

    pmid: str
    status: str
    doi: str | None = None
    message: str = ""
    attempts: list[tuple[str, str]] = field(default_factory=list)  # (pdf url, outcome) in the order tried
    meta: dict[str, Any] | None = None
    text: str | None = None
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.text is not None


class CopyFinder:
    """Looks up and downloads open PDF copies for cited ``pmid:`` studies. Without ``email`` only the cache is read:
    a request that would be needed is refused (``no_contact_email``) and nothing is requested. Clients are made on
    the first request."""

    def __init__(
        self,
        root: Path = DEFAULT_CACHE_ROOT,
        email: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
        fetcher: Fetcher | None = None,
    ):
        self.root = Path(root)
        self.cache = UnpaywallCache(self.root)
        self.email = (email or "").strip() or None
        self._transport = transport
        self._clock = clock
        self._sleep = sleep
        self._now = now
        self._fetcher = fetcher
        self._api: httpx.Client | None = None
        self._pdf_client: httpx.Client | None = None
        self._limiter: RateLimiter | None = None
        self.requests = 0

    def close(self) -> None:
        if self._api is not None:
            self._api.close()
        if self._fetcher is not None:
            self._fetcher.close()
        if self._pdf_client is not None:
            self._pdf_client.close()

    def _today(self) -> str:
        return dt.datetime.fromtimestamp(self._now(), tz=dt.UTC).date().isoformat()

    def _scrub(self, text: str) -> str:
        return text.replace(self.email, "[contact address]") if self.email else text

    def _lookup(self, doi: str) -> dict[str, Any]:
        """One Unpaywall request. A 404 is ``{"me_atlas_status": "not_in_unpaywall"}``. Raises ``UnpaywallError``."""
        assert self.email
        if self._api is None:
            self._api = httpx.Client(
                transport=self._transport, headers={"User-Agent": USER_AGENT}, timeout=60.0, follow_redirects=True
            )
            self._limiter = RateLimiter(1, clock=self._clock, sleep=self._sleep)
        assert self._limiter is not None
        url = API_URL + url_quote(doi, safe="/:;()")
        self.requests += 1
        try:
            response = get_with_retries(
                self._api,
                url,
                params={"email": self.email},
                limiter=self._limiter,
                sleep=self._sleep,
                max_retries=2,
                backoff=2.0,
                label=f"Unpaywall lookup of {doi}",
                error=UnpaywallError,
            )
        except UnpaywallError as exc:
            if getattr(exc, "status_code", None) == 404:
                return {"me_atlas_status": "not_in_unpaywall"}
            raise UnpaywallError(self._scrub(str(exc))) from None
        try:
            answer = response.json()
        except ValueError:
            raise UnpaywallError(f"Unpaywall lookup of {doi}: the answer is not JSON") from None
        if not isinstance(answer, dict):
            raise UnpaywallError(f"Unpaywall lookup of {doi}: the answer is not a JSON object")
        return answer

    def _answer(self, doi: str, refresh: bool) -> dict[str, Any]:
        path = self.cache.answer_path(doi)
        if path.is_file() and not refresh:
            age = self._now() - path.stat().st_mtime
            if age <= LOOKUP_MAX_AGE_DAYS * 86400:
                try:
                    cached = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(cached, dict):
                        return cached
                except ValueError:
                    pass
        answer = self._lookup(doi)
        _write_text(path, self._scrub(json.dumps(answer, indent=2, ensure_ascii=False)) + "\n")
        return answer

    def _download(self, url: str) -> tuple[str, bytes | None, str | None]:
        """(status, body, final URL): ``ok`` only for HTTP 200 and a body that starts with ``%PDF-``."""
        if self._fetcher is None:
            client = httpx.Client(
                transport=self._transport, headers={"User-Agent": USER_AGENT}, timeout=60.0, follow_redirects=False
            )
            self._pdf_client = client
            self._fetcher = Fetcher(client, clock=self._clock, sleep=self._sleep)
        page = self._fetcher.fetch_raw(url)
        if page.status != "received":
            return page.status, None, page.final_url
        body = page.body or b""
        if page.http_status != 200:
            return f"http_{page.http_status}", None, page.final_url
        if len(body) > MAX_PDF_BYTES:
            return "too_large", None, page.final_url
        if not body.startswith(b"%PDF-"):
            return "not_pdf", None, page.final_url
        return "ok", body, page.final_url

    def cached(self, pmid: str, doi: str) -> CopyResult | None:
        found = read_cached_pdf(self.root, doi)
        if found is None:
            return None
        return CopyResult(pmid, "ok", doi, meta=found.meta, text=found.text, from_cache=True)

    def find(self, pmid: str, *, refresh: bool = False) -> CopyResult:
        info = pubmed_doi_and_title(self.root, pmid)
        if info is None:
            return CopyResult(pmid, "no_pubmed_record", message="no readable cached PubMed record")
        doi, title = info
        if not doi:
            return CopyResult(pmid, "no_doi", message="the PubMed record has no DOI")
        if not refresh and (hit := self.cached(pmid, doi)) is not None:
            return hit
        if not self.email:
            return CopyResult(
                pmid, "no_contact_email", doi, message="CONTACT_EMAIL is not set (see .env.example); nothing requested"
            )
        try:
            answer = self._answer(doi, refresh)
        except UnpaywallError as exc:
            return CopyResult(pmid, "unpaywall_error", doi, message=str(exc))
        if answer.get("me_atlas_status") == "not_in_unpaywall":
            return CopyResult(pmid, "not_in_unpaywall", doi)
        locations = choose_locations(answer)
        if not locations:
            return CopyResult(pmid, "no_oa_pdf", doi, message="no published or accepted PDF copy outside PMC")
        result = CopyResult(pmid, "", doi)
        for loc in locations:
            url = loc["url_for_pdf"]
            outcome, body, final_url = self._download(url)
            if body is not None:
                try:
                    pages = extract_pdf_pages(body)
                except Exception:  # pdfminer raises many kinds of errors on a damaged file
                    outcome = "unreadable_pdf"
                else:
                    text, cut = clean_pages(pages)
                    if not has_text_layer(text):
                        outcome = "no_text"
                    elif not title_in_first_pages(title, text):
                        outcome = "title_not_found"
                    else:
                        meta = self._store(doi, pmid, loc, final_url or url, body, text, len(pages), cut)
                        result.attempts.append((url, "ok"))
                        result.status, result.meta, result.text = "ok", meta, text
                        return result
            result.attempts.append((url, outcome))
        result.status = result.attempts[0][1]
        return result

    def _store(
        self, doi: str, pmid: str, loc: Mapping[str, Any], final_url: str, body: bytes, text: str, pages: int, cut: bool
    ) -> dict[str, Any]:
        meta = {
            "doi": doi,
            "pmid": pmid,
            "pdf_url": loc["url_for_pdf"],
            "final_url": final_url,
            "landing_page_url": loc.get("url_for_landing_page"),
            "host_type": loc.get("host_type"),
            "version": loc.get("version"),
            "license": loc.get("license"),
            "fetched": self._today(),
            "sha256": hashlib.sha256(body).hexdigest(),
            "extractor": {"name": EXTRACTOR, "version": importlib.metadata.version(EXTRACTOR)},
            "pages": pages,
            "reference_list_cut": cut,
        }
        _write_bytes(self.cache.pdf_path(doi), body)
        _write_text(self.cache.text_path(doi), text)
        _write_text(self.cache.meta_path(doi), json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
        return meta


# ---------------------------------------------------------------------------
# Founder's confirmations
# ---------------------------------------------------------------------------


def load_confirmations(path: Path) -> list[dict[str, Any]]:
    """The entries of the confirmations file ([] when the file is missing). Raises ``UnpaywallError`` if unreadable."""
    path = Path(path)
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise UnpaywallError(f"{path}: cannot read the confirmations file: {exc}") from exc
    if data is None:
        return []
    if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
        raise UnpaywallError(f"{path}: the confirmations file must be a list of entries")
    return data


def is_confirmed(entries: Sequence[Mapping[str, Any]], study_id: str, quote: str, sha256: str | None) -> bool:
    """An entry has the same study id and the same quote (after ``normalise_quote``) and, when the PDF is cached
    (``sha256`` given), the same ``pdf_sha256``."""
    wanted = normalise_quote(quote)
    for entry in entries:
        if entry.get("study") != study_id or entry.get("field") != "case_definition_quote":
            continue
        if normalise_quote(str(entry.get("quote") or "")) != wanted:
            continue
        if sha256 is not None and entry.get("pdf_sha256") != sha256:
            continue
        return True
    return False


def _render_entry(entry: Mapping[str, Any]) -> str:
    return yaml.safe_dump([dict(entry)], sort_keys=False, allow_unicode=True, width=120)


def append_confirmation(path: Path, entry: Mapping[str, Any]) -> None:
    """Append one entry; existing entries are never edited. A file that holds only ``[]`` (and comments) gets the
    entry in place of the ``[]``. Refuses (and writes nothing) if the result would change an existing entry."""
    path = Path(path)
    before = load_confirmations(path)
    text = path.read_text(encoding="utf-8") if path.is_file() else "[]\n"
    lines = text.splitlines()
    live = [i for i, line in enumerate(lines) if line.strip() and not line.lstrip().startswith("#")]
    block = _render_entry(entry).rstrip("\n").splitlines()
    if live and [lines[i].strip() for i in live] == ["[]"]:
        lines[live[0] : live[0] + 1] = block
        new = "\n".join(lines) + "\n"
    else:
        new = text.rstrip("\n") + "\n" + "\n".join(block) + "\n"
    after = yaml.safe_load(new)
    if not isinstance(after, list) or after[:-1] != before or after[-1] != dict(entry):
        raise UnpaywallError(f"{path}: refused, the edit would change an existing entry")
    _write_text(path, new)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _pmid(text: str) -> str:
    value = text.removeprefix("pmid:")
    if not value.isdigit():
        raise argparse.ArgumentTypeError(f"not a PMID (digits, optionally 'pmid:' first): {text!r}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m me_atlas.unpaywall", description="Open PDF copies via Unpaywall.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("fetch", "find and cache the open PDF copy of cited studies"),
        ("casedef", "fetch, then show sentences that may name a case definition, with page numbers"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("pmids", nargs="*", type=_pmid, metavar="PMID")
        cmd.add_argument("--card", type=Path, required=True, help="the card or draft that cites these PMIDs")
        cmd.add_argument("--refresh", action="store_true", help="ask again even if cached")
        cmd.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_ROOT, help="default: %(default)s")
    pend = sub.add_parser("pending", help="list fulltext_pdf quotes without the founder's confirmation")
    pend.add_argument("--card", type=Path, action="append", help="card or draft (repeatable; default: all)")
    pend.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_ROOT, help="default: %(default)s")
    pend.add_argument("--confirmations", type=Path, default=DEFAULT_CONFIRMATIONS, help="default: %(default)s")
    conf = sub.add_parser("confirm", help="THE FOUNDER ONLY: record that a fulltext_pdf quote was checked by hand")
    conf.add_argument("pmid", type=_pmid, metavar="PMID")
    conf.add_argument("--card", type=Path, required=True)
    conf.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_ROOT, help="default: %(default)s")
    conf.add_argument("--confirmations", type=Path, default=DEFAULT_CONFIRMATIONS, help="default: %(default)s")
    return parser


def _pdf_studies(card_path: Path) -> list[Any]:
    """The studies of a card or draft that have source ``fulltext_pdf`` and a quote."""
    return [s for s in load_card(card_path).studies if s.case_definition_source == SOURCE and s.case_definition_quote]


def _doi_of(root: Path, study_id: str) -> str | None:
    if not study_id.startswith("pmid:"):
        return None
    info = pubmed_doi_and_title(root, study_id.removeprefix("pmid:"))
    return info[0] if info else None


def _line(result: CopyResult) -> str:
    if result.ok and result.meta:
        where = "cached" if result.from_cache else "fetched"
        return (
            f"pmid:{result.pmid}  ok ({where})  {result.meta.get('version')}  {result.meta.get('host_type')}  "
            f"{result.meta.get('pdf_url')}"
        )
    line = f"pmid:{result.pmid}  {result.status}"
    if result.message:
        line += f"  {result.message}"
    if result.attempts:
        line += "  [" + "; ".join(f"{url}: {outcome}" for url, outcome in result.attempts) + "]"
    return line


def _fetch_main(args, env, transport, clock, sleep, now) -> int:
    try:
        card = load_card(args.card)
    except Exception as exc:  # CardValidationError lists every problem; show it as is
        print(f"error: cannot read {args.card}: {exc}", file=sys.stderr)
        return 1
    on_card = [s.id.removeprefix("pmid:") for s in card.studies if s.id.startswith("pmid:")]
    pmids = list(dict.fromkeys(args.pmids)) or on_card
    stray = [p for p in pmids if p not in on_card]
    if stray:
        print(
            f"error: {', '.join(f'pmid:{p}' for p in stray)} is not a pmid: study on {args.card}; "
            "this command fetches only articles cited on the card or draft it is given. Nothing was requested.",
            file=sys.stderr,
        )
        return 1
    if env is None:
        env = {**load_dotenv(), **os.environ}
    finder = CopyFinder(
        args.cache_dir, env.get("CONTACT_EMAIL"), transport=transport, clock=clock, sleep=sleep, now=now
    )
    exit_code = 0
    try:
        for pmid in pmids:
            result = finder.find(pmid, refresh=args.refresh)
            print(_line(result))
            if result.status == "no_contact_email":
                exit_code = max(exit_code, 2)
            elif result.status == "unpaywall_error":
                exit_code = max(exit_code, 1)
            if args.command == "casedef" and result.ok and result.text is not None:
                found = pdf_candidates(result.text)
                if result.meta and result.meta.get("reference_list_cut") is False:
                    print(
                        "  note: no reference-list heading was found; the whole text was searched, "
                        "so a candidate may come from the reference list"
                    )
                print(f"  {len(found)} candidate sentence(s)")
                for page, c in found:
                    mark = " [exclusion]" if c.kind == "exclusion" else ""
                    print(f"  [p. {page}]{mark} {c.sentence}")
                    print(f"    matched: {', '.join(c.matched)}")
    finally:
        finder.close()
    return exit_code


def _default_cards() -> list[Path]:
    paths: list[Path] = []
    for folder in (Path("cards"), Path("drafts")):
        if folder.is_dir():
            paths += sorted(p for p in folder.glob("*.yaml") if p.name != "changelog.yaml")
    return paths


def _pending_main(args) -> int:
    try:
        entries = load_confirmations(args.confirmations)
    except UnpaywallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    count = 0
    for path in args.card or _default_cards():
        try:
            studies = _pdf_studies(path)
        except Exception as exc:
            print(f"error: cannot read {path}: {exc}", file=sys.stderr)
            return 1
        for study in studies:
            doi = _doi_of(args.cache_dir, study.id)
            cached = read_cached_pdf(args.cache_dir, doi) if doi else None
            sha = cached.meta.get("sha256") if cached else None
            if is_confirmed(entries, study.id, study.case_definition_quote, sha):
                continue
            count += 1
            meta = cached.meta if cached else {}
            page = quote_page(study.case_definition_quote, cached.text) if cached else None
            print(f"{path}  {study.id}")
            print(f"  quote: {study.case_definition_quote}")
            print(f"  page: {page if page is not None else 'not found in the cached text'}")
            for key in ("pdf_url", "landing_page_url", "version", "host_type"):
                print(f"  {key}: {meta.get(key) or 'not cached'}")
    return 1 if count else 0


def _confirm_main(args, now) -> int:
    try:
        studies = _pdf_studies(args.card)
    except Exception as exc:
        print(f"error: cannot read {args.card}: {exc}", file=sys.stderr)
        return 1
    study = next((s for s in studies if s.id == f"pmid:{args.pmid}"), None)
    if study is None:
        print(
            f"error: pmid:{args.pmid} is not a study on {args.card} with case_definition_source {SOURCE} and a quote",
            file=sys.stderr,
        )
        return 1
    doi = _doi_of(args.cache_dir, study.id)
    cached = read_cached_pdf(args.cache_dir, doi) if doi else None
    if cached is None:
        print(
            f"error: no cached PDF text for pmid:{args.pmid}; run "
            f"`uv run python -m me_atlas.unpaywall fetch --card {args.card} {args.pmid}` first",
            file=sys.stderr,
        )
        return 1
    page = quote_page(study.case_definition_quote, cached.text)
    if page is None:
        print(
            "error: the card's quote is not found word for word in the cached PDF text; nothing recorded",
            file=sys.stderr,
        )
        return 1
    try:
        entries = load_confirmations(args.confirmations)
        sha = cached.meta.get("sha256")
        if is_confirmed(entries, study.id, study.case_definition_quote, sha):
            print(f"pmid:{args.pmid} is already confirmed for this quote and this PDF; nothing added")
            return 0
        meta = cached.meta
        entry = {
            "study": study.id,
            "field": "case_definition_quote",
            "quote": study.case_definition_quote,
            "pdf_sha256": sha,
            "pdf_url": meta.get("pdf_url"),
            "landing_page_url": meta.get("landing_page_url"),
            "version": meta.get("version"),
            "host_type": meta.get("host_type"),
            "page": page,
            "confirmed_by": "founder",
            "confirmed_on": dt.datetime.fromtimestamp(now(), tz=dt.UTC).date().isoformat(),
        }
        append_confirmation(args.confirmations, entry)
    except UnpaywallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"confirmed pmid:{args.pmid} (page {page}) in {args.confirmations}")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
) -> int:
    for stream in (sys.stdout, sys.stderr):  # a console that cannot encode a character must not stop the run
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = _build_parser().parse_args(argv)
    if args.command in ("fetch", "casedef"):
        return _fetch_main(args, env, transport, clock, sleep, now)
    if args.command == "pending":
        return _pending_main(args)
    return _confirm_main(args, now)


if __name__ == "__main__":
    raise SystemExit(main())
