"""Catalogue of ME/CFS data resources: fetch of each resource's own pages, drafting files, data file, validator.

Command line::

    uv run python -m me_atlas.resources fetch [--offline] [--date YYYY-MM-DD]
    uv run python -m me_atlas.resources import-saved --lead ID --page main|access --url URL --saved YYYY-MM-DD
    uv run python -m me_atlas.resources plan [--changed] [--date YYYY-MM-DD]
    uv run python -m me_atlas.resources record-draft --run DIR
    uv run python -m me_atlas.resources record-review --run DIR
    uv run python -m me_atlas.resources reliability --run DIR
    uv run python -m me_atlas.resources check [--cache]
    uv run python -m me_atlas.resources links

A resource is not evidence. The source of an entry in ``registry/resources.yaml`` is the resource's own public page,
stored in ``data/cache/resources/``. Every value other than ``not_stated`` carries a quote that code has found in the
stored text of the page it names. An AI agent proposes values and quotes; a review agent checks them; only
``record-review`` writes the data file. When a host refuses an automated request, ``import-saved`` stores a copy the
founder saved by hand from a browser (``data/hand-saved/resources/<lead id>/main.html``, ``access.html``) in the same
cache folder as a fetched page, marked ``obtained: hand_saved``; nothing is done by code to get past a bot check or a
login. See ``docs/fetch.md``, ``docs/pipeline.md``, ``docs/site.md`` and
``docs/plan-data-catalogue.md``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.robotparser
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
import yaml

from me_atlas.http import RateLimiter, get_with_retries
from me_atlas.trials import USER_AGENT

MAX_PER_SECOND = 1
MAX_REDIRECTS = 5
MIN_TEXT_CHARS = 200
RELIABILITY_MAX_REJECT_SHARE = 5  # rejects * 5 <= total

DEFAULT_LEADS_FILE = Path("registry/resource-leads.yaml")
DEFAULT_DATA_FILE = Path("registry/resources.yaml")
DEFAULT_RELIABILITY_FILE = Path("registry/resources-reliability.yaml")
DEFAULT_CACHE_DIR = Path("data/cache/resources")
DEFAULT_SAVED_DIR = Path("data/hand-saved/resources")
DEFAULT_PIPELINE_DIR = Path("data/pipeline")

PAGES = ("main", "access")
PAGE_FILES = {"main": "main", "access": "access"}
OBTAINED = ("fetched", "hand_saved")

# Enumerations (functional spec, source rule for data resources).
CATEGORIES = ("data", "register")
HOLDS = ("genotypes", "questionnaires", "biospecimens", "molecular", "clinical", "sensor")
ACCESS = ("open_download", "registration", "application", "not_stated")
COVERS = ("me_cfs", "me_cfs_and_long_covid")
NOT_STATED = "not_stated"
EXCLUSION_REASONS = (
    "no_me_cfs_data",
    "no_outside_access",
    "no_access_statement",
    "long_covid_only",
    "not_a_resource",
)
FETCH_STATUSES = (
    "ok",
    "robots_disallowed",
    "robots_unavailable",
    "blocked",
    "not_html",
    "no_text",
    "network_error",
    "not_cached",
)  # plus http_<code>

# A bot check is told from its visible (extracted) text, a login wall from a real password input element on a page
# with little text; CSS, scripts, attribute values and JSON never count. The fetch never tries to get past either.
BLOCK_PHRASES = (
    "just a moment",
    "verify you are human",
    "checking your browser",
    "enable javascript and cookies to continue",
)
SHORT_PAGE_CHARS = 1000
BLOCKED_HTTP = (401, 403, 429)

DRAFT_ENTRY_KEYS = (
    "id",
    "include",
    "language",
    "category",
    "name",
    "operator",
    "countries",
    "holds",
    "access",
    "covers",
)
DRAFT_EXCLUSION_KEYS = ("id", "include", "reason", "quote", "page")
QUOTED_FIELDS = ("name", "operator", "countries", "access", "covers")
ENTRY_FIELDS = (
    "id",
    "name",
    "operator",
    "countries",
    "url",
    "access_url",
    "checked",
    "category",
    "holds",
    "access",
    "covers",
    "language",
    "source",
    "text_hash",
    "quotes",
)
OPTIONAL_ENTRY_FIELDS = ("hand_saved",)
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
HASH = re.compile(r"^[0-9a-f]{64}$")
LANGUAGE = re.compile(r"^[a-z]{2}$")


class ResourcesError(Exception):
    """A fetch, a file or a step failed; the message says what and where."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _write_json(path: Path, doc: Any) -> None:
    _atomic_write(path, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ResourcesError(f"{path}: cannot read: {exc}") from exc


def _is_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parts = urlsplit(value)
    return parts.scheme in ("http", "https") and bool(parts.netloc) and " " not in value


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_dir(date: str, root: Path = DEFAULT_PIPELINE_DIR) -> Path:
    return root / date / "resources"


def cache_dir_of(cache_root: Path, day: str, lead_id: str) -> Path:
    return cache_root / day / lead_id


# ---------------------------------------------------------------------------
# Text: extraction (code, standard library) and the quote comparison
# ---------------------------------------------------------------------------

_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "head", "svg"})
_BREAK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "body", "br", "dd", "details", "div", "dl", "dt", "fieldset",
        "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main",
        "nav", "ol", "p", "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    }
)  # fmt: skip
_QUOTE_FOLD = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"', "”": '"', "„": '"', "‟": '"'})


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BREAK_TAGS:
            self.parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BREAK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BREAK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def extract_text(html: str) -> str:
    """The visible text of a page: script, style and head dropped, whitespace collapsed."""
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    return " ".join("".join(parser.parts).split())


def normalise(text: str) -> str:
    """Unicode NFKC, straight and curly quotes folded, whitespace collapsed: the form in which a quote is looked for."""
    folded = unicodedata.normalize("NFKC", text).translate(_QUOTE_FOLD)
    return " ".join(folded.split())


def quote_in_text(quote: str, text: str) -> bool:
    needle = normalise(quote)
    return bool(needle) and needle in normalise(text)


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


def load_leads(path: Path) -> list[dict[str, Any]]:
    """The leads of ``registry/resource-leads.yaml``: ``id``, ``url`` and optionally ``access_url``, nothing else."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ResourcesError(f"{path}: cannot read the leads file: {exc}") from exc
    problems = check_leads(data)
    if problems:
        raise ResourcesError("\n".join(f"{path}: {p}" for p in problems))
    return [dict(lead) for lead in data["leads"]]


def check_leads(data: Any) -> list[str]:
    if not isinstance(data, Mapping) or set(data) != {"leads"} or not isinstance(data["leads"], list):
        return ["the file must be a mapping with one key, 'leads', holding a list"]
    problems: list[str] = []
    seen: set[str] = set()
    for index, lead in enumerate(data["leads"]):
        if not isinstance(lead, Mapping):
            problems.append(f"lead {index}: not a mapping")
            continue
        lid = lead.get("id")
        where = lid if isinstance(lid, str) and lid else f"lead {index}"
        extra = sorted(set(lead) - {"id", "url", "access_url"})
        if extra:
            problems.append(f"{where}: unknown field(s) {', '.join(map(str, extra))}")
        if not isinstance(lid, str) or not SLUG.match(lid):
            problems.append(f"{where}: id must be a kebab-case slug")
        elif lid in seen:
            problems.append(f"{where}: duplicate id")
        else:
            seen.add(lid)
        if not _is_url(lead.get("url")):
            problems.append(f"{where}: url must be an http or https address")
        if "access_url" in lead and lead["access_url"] is not None and not _is_url(lead["access_url"]):
            problems.append(f"{where}: access_url must be an http or https address")
    return problems


def page_urls(lead: Mapping[str, Any]) -> dict[str, str]:
    urls = {"main": lead["url"]}
    if lead.get("access_url"):
        urls["access"] = lead["access_url"]
    return urls


# ---------------------------------------------------------------------------
# Fetching: robots, rate limit, redirects, statuses (F2-F5)
# ---------------------------------------------------------------------------


@dataclass
class Page:
    """The outcome of fetching one page."""

    status: str
    http_status: int | None = None
    final_url: str | None = None
    content_type: str | None = None
    body: bytes | None = None
    text: str | None = None  # the extracted text, only when a body was received


def _error_status(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    match = re.search(r"HTTP (\d{3})", str(exc))
    return int(match.group(1)) if match else None


class _PasswordFinder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "input" and any(k == "type" and (v or "").strip().lower() == "password" for k, v in attrs):
            self.found = True

    handle_startendtag = handle_starttag


def has_password_input(html: str) -> bool:
    finder = _PasswordFinder()
    finder.feed(html)
    finder.close()
    return finder.found


def classify(http_status: int, content_type: str, body: bytes, decoded: str, text: str) -> str:
    """The status of a received page (F5). ``ok`` only for HTTP 200, HTML and at least 200 characters of text."""
    if http_status in BLOCKED_HTTP:
        return "blocked"
    is_html = "html" in content_type.lower()
    if is_html and len(text) < SHORT_PAGE_CHARS:
        lowered = text.lower()
        if any(phrase in lowered for phrase in BLOCK_PHRASES) or has_password_input(decoded):
            return "blocked"
    if http_status != 200:
        return f"http_{http_status}"
    if not is_html:
        return "not_html"
    if len(text) < MIN_TEXT_CHARS:
        return "no_text"
    return "ok"


class Fetcher:
    """One HTTP client with robots.txt, at most one request a second per host and redirects followed by hand (every
    hop is checked against its own host's robots file). Never retries with other headers, never keeps cookies."""

    def __init__(
        self,
        http: httpx.Client | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 2,
        backoff: float = 2.0,
    ) -> None:
        self._own = http is None
        self.http = http or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60.0, follow_redirects=False)
        self._clock = clock
        self._sleep = sleep
        self._max_retries = max_retries
        self._backoff = backoff
        self._limiters: dict[str, RateLimiter] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | str] = {}

    def close(self) -> None:
        if self._own:
            self.http.close()

    def _limiter(self, host: str) -> RateLimiter:
        if host not in self._limiters:
            self._limiters[host] = RateLimiter(MAX_PER_SECOND, clock=self._clock, sleep=self._sleep)
        return self._limiters[host]

    def _get(self, url: str) -> tuple[httpx.Response, str]:
        """GET following redirects by hand; returns the response and the final URL. Raises ``ResourcesError``."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            response = get_with_retries(
                self.http,
                current,
                params=None,
                limiter=self._limiter(urlsplit(current).netloc),
                sleep=self._sleep,
                max_retries=self._max_retries,
                backoff=self._backoff,
                label=f"GET {current}",
                error=ResourcesError,
            )
            location = response.headers.get("location")
            if response.status_code in (301, 302, 303, 307, 308) and location:
                current = urljoin(current, location)
                if not _is_url(current):
                    raise ResourcesError(f"GET {url}: redirect to {location!r}, which is not an http address")
                gate = self.robots_status(current)
                if gate != "allowed":
                    raise _RobotsRefusalError(gate)
                continue
            return response, current
        raise ResourcesError(f"GET {url}: more than {MAX_REDIRECTS} redirects")

    def robots_status(self, url: str) -> str:
        """``allowed``, ``robots_disallowed`` or ``robots_unavailable`` for this URL under the generic User-Agent."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._robots[origin] = self._read_robots(origin)
        entry = self._robots[origin]
        if isinstance(entry, str):
            return entry
        return "allowed" if entry.can_fetch(USER_AGENT, url) else "robots_disallowed"

    def _read_robots(self, origin: str) -> urllib.robotparser.RobotFileParser | str:
        parser = urllib.robotparser.RobotFileParser()
        url = f"{origin}/robots.txt"
        for _ in range(MAX_REDIRECTS + 1):
            try:
                response = get_with_retries(
                    self.http,
                    url,
                    params=None,
                    limiter=self._limiter(urlsplit(url).netloc),
                    sleep=self._sleep,
                    max_retries=self._max_retries,
                    backoff=self._backoff,
                    label=f"robots.txt of {origin}",
                    error=ResourcesError,
                )
            except ResourcesError as exc:
                code = getattr(exc, "status_code", None)
                if isinstance(code, int) and 400 <= code < 500:
                    parser.allow_all = True
                    return parser
                return "robots_unavailable"
            location = response.headers.get("location")
            if response.status_code in (301, 302, 303, 307, 308) and location:
                url = urljoin(url, location)
                if not _is_url(url):
                    return "robots_unavailable"
                continue
            if response.status_code >= 300:
                return "robots_unavailable"
            parser.parse(response.text.splitlines())
            parser.modified()
            return parser
        return "robots_unavailable"  # a loop, or more than MAX_REDIRECTS hops (RFC 9309)

    def fetch(self, url: str) -> Page:
        gate = self.robots_status(url)
        if gate != "allowed":
            return Page(status=gate)
        try:
            response, final_url = self._get(url)
        except _RobotsRefusalError as refusal:
            return Page(status=refusal.status)
        except ResourcesError as exc:
            code = _error_status(exc)
            if code is None:
                return Page(status="network_error")
            return Page(status="blocked" if code in BLOCKED_HTTP else f"http_{code}", http_status=code)
        content_type = response.headers.get("content-type", "")
        body = response.content
        decoded = response.text
        text = extract_text(decoded) if "html" in content_type.lower() else ""
        status = classify(response.status_code, content_type, body, decoded, text)
        return Page(
            status=status,
            http_status=response.status_code,
            final_url=final_url,
            content_type=content_type,
            body=body,
            text=text,
        )


class _RobotsRefusalError(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


def _meta(url: str, page: Page, day: str, obtained: str = "fetched") -> dict[str, Any]:
    return {
        "requested_url": url,
        "final_url": page.final_url,
        "http_status": page.http_status,
        "content_type": page.content_type,
        "fetched": day,
        "status": page.status,
        "obtained": obtained,
    }


def store_page(directory: Path, key: str, url: str, page: Page, day: str, obtained: str = "fetched") -> None:
    """Write the raw body, the metadata and the text of a page. The metadata is always written."""
    directory.mkdir(parents=True, exist_ok=True)
    if page.body is not None:
        (directory / f"{key}.html").write_bytes(page.body)
    if page.text is not None:
        (directory / f"{key}.txt").write_text(page.text, encoding="utf-8", newline="\n")
    _write_json(directory / f"{key}.meta.json", _meta(url, page, day, obtained))


def read_meta(directory: Path, key: str) -> dict[str, Any] | None:
    path = directory / f"{key}.meta.json"
    if not path.is_file():
        return None
    data = _load_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("status"), str):
        raise ResourcesError(f"{path}: not a page metadata file")
    return data


def obtained_of(meta: Mapping[str, Any] | None) -> str:
    """How a stored page was obtained; a meta file without the key reads as ``fetched``."""
    return "hand_saved" if meta and meta.get("obtained") == "hand_saved" else "fetched"


def hand_saved_pages(directory: Path, keys: Sequence[str]) -> list[str]:
    """The sorted page keys of a lead whose stored meta says ``hand_saved``."""
    return sorted(k for k in keys if obtained_of(read_meta(directory, k)) == "hand_saved")


# ---------------------------------------------------------------------------
# Pages saved by hand
# ---------------------------------------------------------------------------

_CHARSET = re.compile(rb"""<meta[^>]+?charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.IGNORECASE)


def decode_saved(body: bytes) -> str:
    """Decode a saved page: the charset its own ``<meta charset>`` or ``http-equiv`` declares, else UTF-8; a body that
    does not decode falls back to UTF-8 with replacement."""
    match = _CHARSET.search(body[:4096])
    if match:
        try:
            return body.decode(match.group(1).decode("ascii"))
        except (LookupError, UnicodeDecodeError):
            pass
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("utf-8", errors="replace")


def import_saved(
    leads: Sequence[Mapping[str, Any]],
    cache_root: Path,
    saved_root: Path,
    *,
    lead_id: str,
    page_key: str,
    url: str,
    saved: str,
    today: str,
) -> str:
    """Store a page the founder saved by hand exactly as a fetched page is stored, marked ``hand_saved``. Returns the
    status. Raises ``ResourcesError`` before anything is written when the request does not hold."""
    lead = next((entry for entry in leads if entry["id"] == lead_id), None)
    if lead is None:
        raise ResourcesError(f"lead {lead_id!r} is not in the leads file")
    if page_key not in PAGES:
        raise ResourcesError(f"page must be one of {', '.join(PAGES)}")
    urls = page_urls(lead)
    if page_key not in urls:
        raise ResourcesError(f"lead {lead_id!r} has no access_url, so it has no 'access' page")
    if url != urls[page_key]:
        raise ResourcesError(f"--url must be exactly the lead's address for '{page_key}': {urls[page_key]}")
    if not _is_date(saved):
        raise ResourcesError(f"--saved {saved!r} is not a date (YYYY-MM-DD)")
    if saved > today:
        raise ResourcesError(f"--saved {saved} is later than today ({today})")
    source = saved_root / lead_id / f"{PAGE_FILES[page_key]}.html"
    if not source.is_file():
        raise ResourcesError(f"{source.as_posix()}: the saved page is missing")
    directory = cache_dir_of(cache_root, saved, lead_id)
    if (directory / f"{page_key}.meta.json").exists():
        raise ResourcesError(
            f"{directory.as_posix()}: a page '{page_key}' is already stored for {saved}; not overwritten"
        )
    body = source.read_bytes()
    decoded = decode_saved(body)
    text = extract_text(decoded)
    status = classify(200, "text/html", body, decoded, text)
    page = Page(status=status, http_status=None, final_url=url, content_type="text/html", body=body, text=text)
    store_page(directory, page_key, url, page, saved, obtained="hand_saved")
    return status


def run_fetch(
    leads: Sequence[Mapping[str, Any]],
    cache_root: Path,
    out: Path,
    *,
    day: str,
    offline: bool = False,
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    """Fetch (or, offline, read from the cache) both pages of every lead and write ``fetch-report.json`` into
    ``out``. Returns the report."""
    report: dict[str, Any] = {"date": day, "leads": {}, "fetchable": []}
    own = None
    if not offline and fetcher is None:
        own = fetcher = Fetcher()
    try:
        for lead in leads:
            directory = cache_dir_of(cache_root, day, lead["id"])
            statuses: dict[str, str] = {}
            for key, url in page_urls(lead).items():
                if offline:
                    meta = read_meta(directory, key)
                    statuses[key] = meta["status"] if meta else "not_cached"
                else:
                    kept = read_meta(directory, key)
                    if kept is not None and obtained_of(kept) == "hand_saved":
                        statuses[key] = kept["status"]  # a page saved by hand is never fetched over
                        continue
                    assert fetcher is not None
                    page = fetcher.fetch(url)
                    store_page(directory, key, url, page, day)
                    statuses[key] = page.status
            report["leads"][lead["id"]] = statuses
            if all(s == "ok" for s in statuses.values()):
                report["fetchable"].append(lead["id"])
    finally:
        if own is not None:
            own.close()
    _write_json(out / "fetch-report.json", report)
    return report


# ---------------------------------------------------------------------------
# Plan (A1)
# ---------------------------------------------------------------------------


def stored_text(cache_root: Path, day: str, lead_id: str, key: str) -> str:
    path = cache_dir_of(cache_root, day, lead_id) / f"{key}.txt"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ResourcesError(f"{path}: the stored text is missing: {exc}") from exc


def run_plan(
    leads: Sequence[Mapping[str, Any]],
    cache_root: Path,
    out: Path,
    *,
    day: str,
    data: Mapping[str, Any] | None = None,
    changed_only: bool = False,
) -> list[Path]:
    """One ``context-<id>.json`` per fetchable lead (text copied by code). With ``changed_only`` only the leads whose
    stored text differs from the text their published entry was drafted from."""
    report_path = out / "fetch-report.json"
    if not report_path.is_file():
        raise ResourcesError(f"{report_path}: no fetch report (run 'resources fetch' first)")
    report = _load_json(report_path)
    fetchable = set(report.get("fetchable", []))
    published = {e["id"]: e for e in (data or {}).get("entries", [])}
    written: list[Path] = []
    for lead in leads:
        lid = lead["id"]
        if lid not in fetchable:
            continue
        urls = page_urls(lead)
        pages = {key: stored_text(cache_root, day, lid, key) for key in urls}
        if changed_only:
            old = published.get(lid)
            if old is not None and old.get("text_hash") == {k: text_hash(t) for k, t in pages.items()}:
                continue
        path = out / f"context-{lid}.json"
        _write_json(
            path,
            {
                "id": lid,
                "url": lead["url"],
                "access_url": lead.get("access_url"),
                "fetched": day,
                "pages": pages,
                "hand_saved": hand_saved_pages(cache_dir_of(cache_root, day, lid), list(urls)),
            },
        )
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# Drafts (A2, A3)
# ---------------------------------------------------------------------------


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_quoted(
    where: str,
    item: Any,
    pages: Mapping[str, str],
    allowed: Sequence[str] | None,
    kind: str,
) -> list[str]:
    """One ``{value, quote, page}`` object. ``kind`` is 'enum', 'text' or 'list' (the value type)."""
    if not isinstance(item, dict):
        return [f"{where}: must be an object with value, quote and page"]
    problems: list[str] = []
    if set(item) != {"value", "quote", "page"}:
        extra = sorted(set(item) - {"value", "quote", "page"})
        missing = sorted({"value", "quote", "page"} - set(item))
        if missing:
            problems.append(f"{where}: missing key(s) {', '.join(missing)}")
        if extra:
            problems.append(f"{where}: extra key(s) {', '.join(extra)}")
        return problems
    value, quote, page = item["value"], item["quote"], item["page"]
    if page not in pages:
        problems.append(f"{where}.page: {page!r} is not one of the context's pages ({', '.join(pages)})")
    if kind == "enum":
        if value not in (allowed or ()):
            problems.append(f"{where}.value: unknown value {value!r}")
    elif kind == "text":
        if not _is_nonempty_str(value):
            problems.append(f"{where}.value: must be a non-empty string")
    elif (
        kind == "list"
        and value != NOT_STATED
        and not (isinstance(value, list) and value and all(_is_nonempty_str(v) for v in value))
    ):
        problems.append(f"{where}.value: must be a non-empty list of names, or 'not_stated'")
    if not isinstance(quote, str):
        problems.append(f"{where}.quote: must be a string")
        return problems
    if value == NOT_STATED:
        if quote.strip():
            problems.append(f"{where}.quote: a 'not_stated' value has an empty quote")
    elif not quote.strip():
        problems.append(f"{where}.quote: a value other than 'not_stated' needs a quote")
    elif page in pages and not quote_in_text(quote, pages[page]):
        problems.append(f"{where}.quote: not found in the stored text of page '{page}': {quote!r}")
    return problems


def validate_draft(draft: Any, context: Mapping[str, Any]) -> list[str]:
    """Problems of one draft against its context file, each naming the id and the field."""
    lid = context["id"]
    if not isinstance(draft, dict):
        return [f"{lid}: the draft must be a JSON object"]
    pages: Mapping[str, str] = context["pages"]
    problems: list[str] = []
    if draft.get("id") != lid:
        problems.append(f"{lid}: id is {draft.get('id')!r}, not the context's id")
    include = draft.get("include")
    if include is False:
        keys = DRAFT_EXCLUSION_KEYS
    elif include is True:
        keys = DRAFT_ENTRY_KEYS
    else:
        return [*problems, f"{lid}: include must be true or false"]
    missing = [k for k in keys if k not in draft]
    extra = [k for k in draft if k not in keys]
    if missing:
        problems.append(f"{lid}: missing key(s) {', '.join(missing)}")
    if extra:
        problems.append(f"{lid}: extra key(s) {', '.join(extra)}")
    if missing:
        return problems
    if include is False:
        if draft["reason"] not in EXCLUSION_REASONS:
            problems.append(f"{lid}: reason: unknown value {draft['reason']!r}")
        problems += _check_quoted(
            f"{lid}: exclusion", {"value": "x", "quote": draft["quote"], "page": draft["page"]}, pages, None, "text"
        )
        return problems
    if not isinstance(draft["language"], str) or not LANGUAGE.match(draft["language"]):
        problems.append(f"{lid}: language: must be a two-letter ISO 639-1 code")
    if draft["category"] not in CATEGORIES:
        problems.append(f"{lid}: category: unknown value {draft['category']!r}")
    problems += _check_quoted(f"{lid}: name", draft["name"], pages, None, "text")
    problems += _check_quoted(f"{lid}: operator", draft["operator"], pages, None, "text")
    if isinstance(draft["name"], dict) and draft["name"].get("value") == NOT_STATED:
        problems.append(f"{lid}: name: an entry needs a stated name")
    problems += _check_quoted(f"{lid}: countries", draft["countries"], pages, None, "list")
    problems += _check_quoted(f"{lid}: access", draft["access"], pages, ACCESS, "enum")
    problems += _check_quoted(f"{lid}: covers", draft["covers"], pages, COVERS, "enum")
    holds = draft["holds"]
    if not isinstance(holds, list):
        problems.append(f"{lid}: holds: must be a list")
        holds = []
    seen: set[Any] = set()
    for i, item in enumerate(holds):
        problems += _check_quoted(f"{lid}: holds[{i}]", item, pages, HOLDS, "enum")
        value = item.get("value") if isinstance(item, dict) else None
        if value in seen:
            problems.append(f"{lid}: holds[{i}]: {value!r} is listed twice")
        seen.add(value)
        if isinstance(item, dict) and item.get("value") == NOT_STATED:
            problems.append(f"{lid}: holds[{i}]: 'not_stated' is not a holds value")
    if draft["category"] == "register" and holds:
        problems.append(f"{lid}: holds: a register has no holds")
    if draft["category"] == "data":
        if not holds:
            problems.append(f"{lid}: holds: a data entry needs at least one holds value")
        if isinstance(draft["access"], dict) and draft["access"].get("value") == NOT_STATED:
            problems.append(f"{lid}: access: a data entry needs a stated access")
    return problems


def _load_context(run: Path, lid: str) -> dict[str, Any]:
    ctx = _load_json(run / f"context-{lid}.json")
    if not isinstance(ctx, dict) or not isinstance(ctx.get("pages"), dict) or ctx.get("id") != lid:
        raise ResourcesError(f"{run / f'context-{lid}.json'}: not a context file")
    return ctx


def context_ids(run: Path) -> list[str]:
    return sorted(p.stem.removeprefix("context-") for p in Path(run).glob("context-*.json"))


def record_draft(run: Path) -> list[str]:
    """Validate every draft of the run. Writes nothing."""
    ids = context_ids(run)
    if not ids:
        return [f"{run}: no context files"]
    problems: list[str] = []
    for lid in ids:
        path = run / f"draft-{lid}.json"
        if not path.is_file():
            problems.append(f"{lid}: the draft file {path} is missing")
            continue
        problems += validate_draft(_load_json(path), _load_context(run, lid))
    return problems


# ---------------------------------------------------------------------------
# Reviews (A4-A6)
# ---------------------------------------------------------------------------


def validate_review(review: Any, lid: str) -> list[str]:
    if not isinstance(review, dict):
        return [f"{lid}: the review must be a JSON object"]
    problems: list[str] = []
    extra = sorted(set(review) - {"id", "verdict", "finding"})
    if extra:
        problems.append(f"{lid}: extra key(s) {', '.join(extra)}")
    if review.get("id") != lid:
        problems.append(f"{lid}: id is {review.get('id')!r}")
    verdict = review.get("verdict")
    if verdict not in ("accept", "reject"):
        problems.append(f"{lid}: verdict must be 'accept' or 'reject'")
    elif verdict == "reject" and not _is_nonempty_str(review.get("finding")):
        problems.append(f"{lid}: a reject needs a finding")
    elif verdict == "accept" and "finding" in review:
        problems.append(f"{lid}: an accept has no finding")
    return problems


def _decisions(run: Path) -> tuple[list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]], list[str]]:
    """(id, context, draft, review) for every context of the run, and the problems."""
    problems = record_draft(run)
    rows: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    if any(p.endswith("no context files") for p in problems):
        return rows, problems
    for lid in context_ids(run):
        path = run / f"review-{lid}.json"
        if not path.is_file():
            problems.append(f"{lid}: the review file {path} is missing")
            continue
        review = _load_json(path)
        found = validate_review(review, lid)
        problems += found
        if not found and (run / f"draft-{lid}.json").is_file():
            rows.append((lid, _load_context(run, lid), _load_json(run / f"draft-{lid}.json"), review))
    return rows, problems


def _source_pages(draft: Mapping[str, Any]) -> list[str]:
    used: set[str] = set()
    for field in QUOTED_FIELDS:
        if draft[field]["value"] != NOT_STATED or draft[field]["quote"]:
            used.add(draft[field]["page"])
    for item in draft["holds"]:
        used.add(item["page"])
    return [p for p in PAGES if p in used]


def build_entry(context: Mapping[str, Any], draft: Mapping[str, Any]) -> dict[str, Any]:
    """The data-file entry of an accepted, validated draft. Code adds ``url``, ``access_url``, ``checked``, ``source``
    and ``text_hash``; the values and quotes are the drafter's."""
    pages = context["pages"]
    urls = {"main": context["url"], "access": context.get("access_url")}
    quotes: dict[str, Any] = {f: {"quote": draft[f]["quote"], "page": draft[f]["page"]} for f in QUOTED_FIELDS}
    quotes["holds"] = {h["value"]: {"quote": h["quote"], "page": h["page"]} for h in draft["holds"]}
    entry = {
        "id": draft["id"],
        "name": draft["name"]["value"],
        "operator": draft["operator"]["value"],
        "countries": draft["countries"]["value"],
        "url": context["url"],
        "access_url": context.get("access_url"),
        "checked": context["fetched"],
        "category": draft["category"],
        "holds": sorted(h["value"] for h in draft["holds"]),
        "access": draft["access"]["value"],
        "covers": draft["covers"]["value"],
        "language": draft["language"],
        "source": [urls[p] for p in _source_pages(draft)],
        "text_hash": {k: text_hash(t) for k, t in pages.items()},
        "quotes": quotes,
    }
    hand_saved = [k for k in PAGES if k in (context.get("hand_saved") or []) and k in pages]
    if hand_saved:
        entry["hand_saved"] = hand_saved
    return entry


def record_review(data: Mapping[str, Any] | None, run: Path, today: str) -> tuple[dict[str, Any], list[str]]:
    """The data file with the accepted entries written in, or the problems. Needs a valid draft and a valid review
    for every context of the run; nothing is applied unless all are valid. An entry of the file whose lead has an
    accepted exclusion in this run is removed; every other entry is kept."""
    rows, problems = _decisions(run)
    if problems:
        return dict(data or {}), problems
    entries = {e["id"]: e for e in (data or {}).get("entries", [])}
    for lid, context, draft, review in rows:
        if review["verdict"] != "accept":
            continue
        if draft["include"]:
            entries[lid] = build_entry(context, draft)
        else:
            entries.pop(lid, None)
    ordered = [entries[i] for i in sorted(entries)]
    return {"checked": today, "entries": ordered}, []


def reliability_passed(total: int, rejects: int) -> bool:
    """At most one output in five rejected: ``rejects * 5 <= total``. No output at all is not a pass."""
    return total > 0 and rejects * RELIABILITY_MAX_REJECT_SHARE <= total


def reliability(run: Path, today: str) -> tuple[dict[str, Any], list[str]]:
    """The numbers of a run: every reviewed drafter output, proposed inclusions and proposed exclusions."""
    rows, problems = _decisions(run)
    if problems:
        return {}, problems
    split = {"included": [0, 0], "excluded": [0, 0]}
    for _, _, draft, review in rows:
        key = "included" if draft["include"] else "excluded"
        split[key][0] += 1
        split[key][1] += review["verdict"] == "reject"
    total = len(rows)
    rejects = split["included"][1] + split["excluded"][1]
    return {
        "date": today,
        "run": run.as_posix(),
        "total": total,
        "rejects": rejects,
        "reject_rate": round(rejects / total, 4) if total else None,
        "included": {"total": split["included"][0], "rejects": split["included"][1]},
        "excluded": {"total": split["excluded"][0], "rejects": split["excluded"][1]},
        "passed": reliability_passed(total, rejects),
    }, []


# ---------------------------------------------------------------------------
# Data file: load, dump, validator (D1-D3)
# ---------------------------------------------------------------------------


def dump_data(data: Mapping[str, Any]) -> str:
    return yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True, width=120)


def load_data(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ResourcesError(f"{path}: cannot read the resources file: {exc}") from exc
    if not isinstance(data, dict):
        raise ResourcesError(f"{path}: the top level must be a mapping")
    if isinstance(data.get("checked"), dt.date):
        data["checked"] = data["checked"].isoformat()
    for entry in data.get("entries") or []:
        if isinstance(entry, dict) and isinstance(entry.get("checked"), dt.date):
            entry["checked"] = entry["checked"].isoformat()
    return data


def _is_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def check_data(data: Any) -> list[str]:
    """Problems of a data file, each naming the entry and the field. An empty list means the file is valid."""
    if not isinstance(data, Mapping):
        return ["the top level must be a mapping"]
    problems: list[str] = []
    for key in ("checked", "entries"):
        if key not in data:
            problems.append(f"missing top-level field '{key}'")
    if problems:
        return problems
    entries = data["entries"]
    if not isinstance(entries, list):
        return ["'entries' must be a list"]
    if data["checked"] is not None and not _is_date(data["checked"]):
        problems.append("'checked' must be a date (YYYY-MM-DD) or null")
    if entries and data["checked"] is None:
        problems.append("'checked' is null but there are entries")
    previous: str | None = None
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            problems.append(f"entry {index}: not a mapping")
            continue
        lid = entry.get("id")
        where = lid if isinstance(lid, str) and lid else f"entry {index}"
        missing = [f for f in ENTRY_FIELDS if f not in entry]
        if missing:
            problems.append(f"{where}: missing field(s) {', '.join(missing)}")
            continue
        extra = [f for f in entry if f not in ENTRY_FIELDS and f not in OPTIONAL_ENTRY_FIELDS]
        if extra:
            problems.append(f"{where}: unknown field(s) {', '.join(extra)}")
        if not isinstance(lid, str) or not SLUG.match(lid):
            problems.append(f"{where}: id must be a kebab-case slug")
            continue
        if lid in seen:
            problems.append(f"{where}: id: duplicate id")
        elif previous is not None and lid < previous:
            problems.append(f"{where}: id: ids are not sorted (after {previous})")
        seen.add(lid)
        previous = lid if previous is None or lid > previous else previous
        problems += _check_entry(where, entry)
    return problems


def _check_entry(where: str, entry: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    for field in ("name", "operator"):
        if not _is_nonempty_str(entry[field]):
            problems.append(f"{where}: {field}: must be a non-empty string")
    if entry["name"] == NOT_STATED:
        problems.append(f"{where}: name: an entry needs a stated name")
    countries = entry["countries"]
    if countries != NOT_STATED and not (
        isinstance(countries, list) and countries and all(_is_nonempty_str(c) for c in countries)
    ):
        problems.append(f"{where}: countries: must be a non-empty list of names, or 'not_stated'")
    if not _is_url(entry["url"]):
        problems.append(f"{where}: url: must be an http or https address")
    if entry["access_url"] is not None and not _is_url(entry["access_url"]):
        problems.append(f"{where}: access_url: must be null or an http or https address")
    if not _is_date(entry["checked"]):
        problems.append(f"{where}: checked: must be a date (YYYY-MM-DD)")
    if entry["category"] not in CATEGORIES:
        problems.append(f"{where}: category: unknown value {entry['category']!r}")
    if entry["access"] not in ACCESS:
        problems.append(f"{where}: access: unknown value {entry['access']!r}")
    if entry["covers"] not in COVERS:
        problems.append(f"{where}: covers: unknown value {entry['covers']!r}")
    if not isinstance(entry["language"], str) or not LANGUAGE.match(entry["language"]):
        problems.append(f"{where}: language: must be a two-letter ISO 639-1 code")
    holds = entry["holds"]
    if not isinstance(holds, list) or any(h not in HOLDS for h in holds) or len(set(map(str, holds))) != len(holds):
        problems.append(f"{where}: holds: must be a list of distinct values from {', '.join(HOLDS)}")
        holds = []
    if entry["category"] == "register" and holds:
        problems.append(f"{where}: holds: a register has no holds")
    if entry["category"] == "data":
        if not holds:
            problems.append(f"{where}: holds: a data entry needs at least one holds value")
        if entry["access"] == NOT_STATED:
            problems.append(f"{where}: access: a data entry needs a stated access")
    source = entry["source"]
    if not isinstance(source, list) or not source or not all(_is_url(s) for s in source):
        problems.append(f"{where}: source: must be a non-empty list of page addresses")
    hashes = entry["text_hash"]
    if not isinstance(hashes, Mapping) or "main" not in hashes or set(hashes) - set(PAGES):
        problems.append(f"{where}: text_hash: must map 'main' (and 'access') to a hash")
        hashes = {}
    elif not all(isinstance(h, str) and HASH.match(h) for h in hashes.values()):
        problems.append(f"{where}: text_hash: every hash must be 64 hexadecimal characters")
    if "hand_saved" in entry:
        saved = entry["hand_saved"]
        if not (
            isinstance(saved, list)
            and saved
            and len(set(map(str, saved))) == len(saved)
            and all(isinstance(k, str) and k in PAGES for k in saved)
        ):
            problems.append(f"{where}: hand_saved: must be a non-empty list of distinct page keys ({', '.join(PAGES)})")
        elif hashes and any(k not in hashes for k in saved):
            problems.append(f"{where}: hand_saved: every page key must be a page in text_hash")
    quotes = entry["quotes"]
    if not isinstance(quotes, Mapping):
        return [*problems, f"{where}: quotes: must be a mapping"]
    stated = {
        "name": True,
        "operator": entry["operator"] != NOT_STATED,
        "countries": countries != NOT_STATED,
        "access": entry["access"] != NOT_STATED,
        "covers": True,
    }
    for field in QUOTED_FIELDS:
        problems += _check_quote(where, f"quotes.{field}", quotes.get(field), stated[field], hashes)
    held = quotes.get("holds")
    if not isinstance(held, Mapping):
        problems.append(f"{where}: quotes.holds: must be a mapping of each holds value to its quote")
    else:
        for h in holds:
            problems += _check_quote(where, f"quotes.holds.{h}", held.get(h), True, hashes)
        problems += [f"{where}: quotes.holds.{h}: quote for a value not in holds" for h in held if h not in holds]
    return problems


def _check_quote(where: str, field: str, item: Any, needs_quote: bool, hashes: Mapping[str, Any]) -> list[str]:
    if not isinstance(item, Mapping) or set(item) != {"quote", "page"}:
        return [f"{where}: {field}: must hold exactly a quote and a page"]
    problems: list[str] = []
    if hashes and item["page"] not in hashes:
        problems.append(f"{where}: {field}: page {item['page']!r} is not a stored page of the entry")
    if not isinstance(item["quote"], str):
        problems.append(f"{where}: {field}: quote must be a string")
    elif needs_quote and not item["quote"].strip():
        problems.append(f"{where}: {field}: a value other than 'not_stated' needs a quote")
    elif not needs_quote and item["quote"].strip():
        problems.append(f"{where}: {field}: a 'not_stated' value has an empty quote")
    return problems


def check_against_cache(data: Mapping[str, Any], cache_root: Path) -> list[str]:
    """Every quote of every entry found, after normalisation, in the stored text of its page; every stored text still
    has the hash the entry was written with."""
    problems: list[str] = []
    for entry in data.get("entries", []):
        lid = entry["id"]
        directory = cache_dir_of(cache_root, entry["checked"], lid)
        texts: dict[str, str | None] = {}

        def text_of(page: str, texts: dict[str, str | None] = texts, directory: Path = directory) -> str | None:
            if page not in texts:
                path = directory / f"{page}.txt"
                texts[page] = path.read_text(encoding="utf-8") if path.is_file() else None
            return texts[page]

        for page, expected in entry["text_hash"].items():
            body = text_of(page)
            if body is None:
                problems.append(f"{lid}: page '{page}': no stored text in {directory.as_posix()}")
            elif text_hash(body) != expected:
                problems.append(f"{lid}: page '{page}': the stored text has changed since the entry was written")
        claimed = set(entry.get("hand_saved") or [])
        for page in entry["text_hash"]:
            meta = read_meta(directory, page)
            if meta is None:
                if page in claimed:
                    problems.append(
                        f"{lid}: page '{page}': hand_saved, but no stored metadata in {directory.as_posix()}"
                    )
                continue
            if (obtained_of(meta) == "hand_saved") != (page in claimed):
                problems.append(
                    f"{lid}: page '{page}': hand_saved in the entry disagrees with the stored metadata "
                    f"(obtained: {obtained_of(meta)})"
                )
        items = [(f"quotes.{f}", entry["quotes"][f]) for f in QUOTED_FIELDS]
        items += [(f"quotes.holds.{h}", q) for h, q in entry["quotes"]["holds"].items()]
        for field, item in items:
            if not item["quote"]:
                continue
            body = text_of(item["page"])
            if body is None:
                problems.append(f"{lid}: {field}: page '{item['page']}' is not in the cache")
            elif not quote_in_text(item["quote"], body):
                problems.append(f"{lid}: {field}: quote not found in the stored text of page '{item['page']}'")
    return problems


# ---------------------------------------------------------------------------
# Site and dataset helpers
# ---------------------------------------------------------------------------


def load_reliability(path: Path) -> bool:
    """True only when the file exists and says ``passed: true``. A file that cannot be read is an error."""
    path = Path(path)
    if not path.is_file():
        return False
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ResourcesError(f"{path}: cannot read the reliability file: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("passed"), bool):
        raise ResourcesError(f"{path}: must be a mapping with a true or false 'passed'")
    return data["passed"]


def published_entries(data: Mapping[str, Any] | None, passed: bool) -> list[dict[str, Any]]:
    """The entries the site and the dataset show: none unless the reliability test passed."""
    if not data or not passed:
        return []
    return [dict(e) for e in data["entries"]]


# ---------------------------------------------------------------------------
# Links (U1)
# ---------------------------------------------------------------------------


def run_links(data: Mapping[str, Any], fetcher: Fetcher) -> list[tuple[str, str, str]]:
    """(id, url, what happened) for every ``url`` and ``access_url`` that did not answer HTTP 200."""
    bad: list[tuple[str, str, str]] = []
    for entry in data.get("entries", []):
        for url in (entry["url"], entry.get("access_url")):
            if not url:
                continue
            page = fetcher.fetch(url)
            if page.status in ("robots_disallowed", "robots_unavailable", "network_error"):
                bad.append((entry["id"], url, page.status))
            elif page.http_status != 200:
                bad.append((entry["id"], url, f"HTTP {page.http_status}" if page.http_status else page.status))
    return bad


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m me_atlas.resources", description="Catalogue of data resources.")
    parser.add_argument("--leads-file", type=Path, default=DEFAULT_LEADS_FILE, help=argparse.SUPPRESS)
    parser.add_argument("--data-file", type=Path, default=DEFAULT_DATA_FILE, help=argparse.SUPPRESS)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--pipeline-dir", type=Path, default=DEFAULT_PIPELINE_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--reliability-file", type=Path, default=DEFAULT_RELIABILITY_FILE, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="fetch each lead's pages, store them, write the fetch report")
    fetch.add_argument("--offline", action="store_true", help="read the stored pages of --date, make no request")
    fetch.add_argument("--date", default=None, help="fetch date, YYYY-MM-DD (default: today)")

    saved = sub.add_parser("import-saved", help="store a page saved by hand from a browser, marked hand_saved")
    saved.add_argument("--saved-dir", type=Path, default=DEFAULT_SAVED_DIR, help=argparse.SUPPRESS)
    saved.add_argument("--lead", required=True, help="the lead id")
    saved.add_argument("--page", required=True, choices=PAGES, help="which page of the lead")
    saved.add_argument("--url", required=True, help="the address that was saved; exactly the lead's url or access_url")
    saved.add_argument("--saved", required=True, help="the date the page was saved, YYYY-MM-DD")

    plan = sub.add_parser("plan", help="write one context file per fetchable lead")
    plan.add_argument("--changed", action="store_true", help="only leads whose stored text changed since drafting")
    plan.add_argument("--date", default=None, help="run date, YYYY-MM-DD (default: today)")

    for name, text in (
        ("record-draft", "validate every draft of a run"),
        ("record-review", "validate drafts and reviews and write the accepted entries to the data file"),
        ("reliability", "compute the reject rate of a run and write registry/resources-reliability.yaml"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--run", type=Path, required=True, help="the run directory (data/pipeline/<date>/resources)")

    check = sub.add_parser("check", help="validate registry/resources.yaml")
    check.add_argument("--cache", action="store_true", help="also find every quote in the stored text of its page")

    sub.add_parser("links", help="list the url and access_url that do not answer HTTP 200 (changes no file)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    today = dt.date.today().isoformat()
    try:
        return _run(args, today)
    except ResourcesError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


def _report(problems: list[str], failed: str) -> int:
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        print(f"FAILED: {len(problems)} problem(s); {failed}", file=sys.stderr)
        return 1
    return 0


def _run(args: argparse.Namespace, today: str) -> int:
    cmd = args.command
    if cmd == "fetch":
        day = args.date or today
        leads = load_leads(args.leads_file)
        out = run_dir(day, args.pipeline_dir)
        report = run_fetch(leads, args.cache_dir, out, day=day, offline=args.offline)
        for lid, statuses in report["leads"].items():
            print(f"{lid}: " + ", ".join(f"{k} {v}" for k, v in statuses.items()))
        print(f"OK: {len(report['fetchable'])} of {len(leads)} lead(s) fetchable; report in {out.as_posix()}")
        return 0
    if cmd == "import-saved":
        leads = load_leads(args.leads_file)
        status = import_saved(
            leads,
            args.cache_dir,
            args.saved_dir,
            lead_id=args.lead,
            page_key=args.page,
            url=args.url,
            saved=args.saved,
            today=today,
        )
        where = cache_dir_of(args.cache_dir, args.saved, args.lead).as_posix()
        print(f"{args.lead}: {args.page} {status}; stored in {where}")
        return 0 if status == "ok" else 1
    if cmd == "plan":
        day = args.date or today
        leads = load_leads(args.leads_file)
        data = load_data(args.data_file) if args.data_file.is_file() else None
        out = run_dir(day, args.pipeline_dir)
        written = run_plan(leads, args.cache_dir, out, day=day, data=data, changed_only=args.changed)
        for path in written:
            print(path.as_posix())
        print(f"OK: {len(written)} context file(s) in {out.as_posix()}")
        return 0
    if cmd == "record-draft":
        if _report(record_draft(args.run), "the drafts were not accepted"):
            return 1
        print(f"OK: {len(context_ids(args.run))} draft(s) are valid")
        return 0
    if cmd == "record-review":
        old = load_data(args.data_file) if args.data_file.is_file() else None
        new, problems = record_review(old, args.run, today)
        if _report(problems, f"{args.data_file.as_posix()} is unchanged"):
            return 1
        _atomic_write(args.data_file, dump_data(new))
        print(f"OK: {len(new['entries'])} entries in {args.data_file.as_posix()}")
        return 0
    if cmd == "reliability":
        result, problems = reliability(args.run, today)
        if _report(problems, "no reliability file written"):
            return 1
        _atomic_write(args.reliability_file, yaml.safe_dump(result, sort_keys=False))
        print(
            f"{'PASSED' if result['passed'] else 'NOT PASSED'}: {result['rejects']} reject(s) of {result['total']} "
            f"({result['reject_rate']}); written to {args.reliability_file.as_posix()}"
        )
        return 0
    if cmd == "check":
        if not args.data_file.is_file():
            raise ResourcesError(f"{args.data_file}: no resources file")
        data = load_data(args.data_file)
        problems = check_data(data)
        if args.cache and not problems:
            problems += check_against_cache(data, args.cache_dir)
        if _report(problems, f"in {args.data_file.as_posix()}"):
            return 1
        print(f"OK: {len(data['entries'])} entries, {args.data_file.as_posix()} is valid")
        return 0
    if cmd == "links":
        data = load_data(args.data_file) if args.data_file.is_file() else {"entries": []}
        problems_found = check_data(data)
        if problems_found:
            raise ResourcesError("; ".join(problems_found))
        fetcher = Fetcher()
        try:
            bad = run_links(data, fetcher)
        finally:
            fetcher.close()
        for lid, url, what in bad:
            print(f"{lid}: {url}: {what}")
        print(f"OK: {len(bad)} address(es) did not answer HTTP 200")
        return 0
    raise ResourcesError(f"unknown command {cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
