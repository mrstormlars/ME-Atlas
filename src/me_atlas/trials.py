"""Registered ongoing studies (ClinicalTrials.gov): fetch, data file, validator, mapping files and reliability test.

Command line::

    uv run python -m me_atlas.trials fetch [--offline] [--date YYYY-MM-DD]
    uv run python -m me_atlas.trials check [--cache]
    uv run python -m me_atlas.trials map-plan [--ids NCT... | --ids-file FILE] [--date YYYY-MM-DD]
    uv run python -m me_atlas.trials record-mapping --run DIR
    uv run python -m me_atlas.trials record-review --run DIR
    uv run python -m me_atlas.trials sample --seed S [--n 50] [--out FILE]
    uv run python -m me_atlas.trials reliability --run DIR --seed S

A registered study is not evidence. Every field of an entry in ``registry/trials.yaml`` that comes from the registry is
copied by code from the fetched record (``data/cache/clinicaltrials/``); the only thing a model decides is which cards a
study bears on (``hypotheses``), and that is written only from a validated review file (``record-review``).
See ``docs/fetch.md``, ``docs/pipeline.md``, ``docs/site.md`` and ``docs/plan-trial-registry.md``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sys
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import yaml

from me_atlas import cards as cardlib
from me_atlas.http import RateLimiter, get_with_retries

API_URL = "https://clinicaltrials.gov/api/v2/studies"
USER_AGENT = "me-atlas-research-client"
PAGE_SIZE = 1000
MAX_PER_SECOND = 1
STUDY_URL = "https://clinicaltrials.gov/study/{nct_id}"

# The two searches (query.cond). Checked against the live API on 2026-11-18; see docs/fetch.md.
SEARCHES: dict[str, str] = {
    "me_cfs": '"chronic fatigue syndrome" OR "myalgic encephalomyelitis"',
    "long_covid": (
        '"long COVID" OR "post COVID-19 condition" OR "post-COVID syndrome" OR "post-COVID-19 syndrome" '
        'OR "post-COVID condition" OR (PASC AND COVID)'
    ),
}

ONGOING_STATUSES = frozenset({"RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION"})
KNOWN_STATUSES = ONGOING_STATUSES | {
    "COMPLETED",
    "TERMINATED",
    "WITHDRAWN",
    "SUSPENDED",
    "UNKNOWN",
    "AVAILABLE",
    "NO_LONGER_AVAILABLE",
    "TEMPORARILY_NOT_AVAILABLE",
    "APPROVED_FOR_MARKETING",
    "WITHHELD",
}
KNOWN_STUDY_TYPES = frozenset({"INTERVENTIONAL", "OBSERVATIONAL", "EXPANDED_ACCESS"})
MAPPING_STATES = ("not_mapped", "accepted", "rejected")
BATCH_SIZE = 20
RELIABILITY_MAX_REJECT_SHARE = 5  # rejects * 5 <= total

DEFAULT_DATA_FILE = Path("registry/trials.yaml")
DEFAULT_RELIABILITY_FILE = Path("registry/reliability.yaml")
DEFAULT_CACHE_DIR = Path("data/cache/clinicaltrials")
DEFAULT_PIPELINE_DIR = Path("data/pipeline")
DEFAULT_CARDS_DIR = Path("cards")

# The fields code copies from a registry record, in the order the data file writes them.
COPIED_FIELDS = ("title", "study_type", "status", "countries", "enrollment", "start_date", "last_update")
ENTRY_FIELDS = (
    "nct_id",
    *COPIED_FIELDS,
    "searches",
    "hypotheses",
    "mapping",
    "mapping_source",
)
NCT_PATTERN_LENGTH = 11


class TrialsError(Exception):
    """A fetch, a file or a step failed; the message says what and where."""


# ---------------------------------------------------------------------------
# Parsing a registry record (code copies, nothing is written about a study)
# ---------------------------------------------------------------------------


def _get(raw: Mapping[str, Any], *path: str) -> Any:
    node: Any = raw
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return node


def copied_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    """The copied fields of one raw API record. ``nct_id`` plus ``COPIED_FIELDS``; raises ``TrialsError`` when the
    record has no registry number, title, status or study type."""
    proto = "protocolSection"
    nct = _get(raw, proto, "identificationModule", "nctId")
    title = _get(raw, proto, "identificationModule", "briefTitle")
    status = _get(raw, proto, "statusModule", "overallStatus")
    study_type = _get(raw, proto, "designModule", "studyType")
    if not (isinstance(nct, str) and nct and isinstance(title, str) and title):
        raise TrialsError("a record has no nctId or briefTitle")
    if not (isinstance(status, str) and isinstance(study_type, str)):
        raise TrialsError(f"{nct}: the record has no overallStatus or studyType")
    locations = _get(raw, proto, "contactsLocationsModule", "locations") or []
    countries = sorted({loc["country"] for loc in locations if isinstance(loc, Mapping) and loc.get("country")})
    info = _get(raw, proto, "designModule", "enrollmentInfo")
    enrollment = None
    if isinstance(info, Mapping) and info.get("count") is not None:
        enrollment = {"count": info["count"], "type": info.get("type")}
    return {
        "nct_id": nct,
        "title": title,
        "study_type": study_type,
        "status": status,
        "countries": countries,
        "enrollment": enrollment,
        "start_date": _get(raw, proto, "statusModule", "startDateStruct", "date"),
        "last_update": _get(raw, proto, "statusModule", "lastUpdatePostDateStruct", "date"),
    }


def context_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    """What a mapping batch holds per study, copied by code (contract M1)."""
    proto = "protocolSection"
    interventions = _get(raw, proto, "armsInterventionsModule", "interventions") or []
    return {
        "nct_id": _get(raw, proto, "identificationModule", "nctId"),
        "brief_title": _get(raw, proto, "identificationModule", "briefTitle"),
        "official_title": _get(raw, proto, "identificationModule", "officialTitle"),
        "conditions": _get(raw, proto, "conditionsModule", "conditions") or [],
        "keywords": _get(raw, proto, "conditionsModule", "keywords") or [],
        "brief_summary": _get(raw, proto, "descriptionModule", "briefSummary"),
        "study_type": _get(raw, proto, "designModule", "studyType"),
        "interventions": [
            {"type": i.get("type"), "name": i.get("name")} for i in interventions if isinstance(i, Mapping)
        ],
        "observational_model": _get(raw, proto, "designModule", "designInfo", "observationalModel"),
    }


# ---------------------------------------------------------------------------
# Cache: data/cache/clinicaltrials/<fetch date>/<search>-<page>.json
# ---------------------------------------------------------------------------


def _page_path(cache_dir: Path, day: str, search: str, page: int) -> Path:
    return cache_dir / day / f"{search}-{page:03d}.json"


def _write_page(path: Path, response: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8", newline="\n")


def _read_page(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TrialsError(f"{path}: cannot read the cached response: {exc}") from exc
    if not isinstance(data, dict):
        raise TrialsError(f"{path}: the cached response is not a JSON object")
    return data


def cached_records(cache_dir: Path, day: str, search: str) -> list[dict[str, Any]]:
    """The raw records of one search on one fetch date, in the order the pages hold them. Follows the chain of pages
    from page 1 until a page has no ``nextPageToken``."""
    records: list[dict[str, Any]] = []
    page = 1
    while True:
        path = _page_path(cache_dir, day, search, page)
        if not path.is_file():
            raise TrialsError(f"{path}: the cached page is missing")
        response = _read_page(path)
        studies = response.get("studies")
        if not isinstance(studies, list):
            raise TrialsError(f"{path}: the cached response has no 'studies' list")
        records += studies
        if not response.get("nextPageToken"):
            return records
        page += 1


def latest_cache_records(cache_dir: Path) -> dict[str, dict[str, Any]]:
    """Registry number -> the raw record of the newest cached fetch that holds it (every date folder, oldest first)."""
    found: dict[str, dict[str, Any]] = {}
    if not cache_dir.is_dir():
        return found
    for day_dir in sorted(p for p in cache_dir.iterdir() if p.is_dir()):
        for page in sorted(day_dir.glob("*.json")):
            response = _read_page(page)
            for record in response.get("studies") or []:
                nct = _get(record, "protocolSection", "identificationModule", "nctId")
                if isinstance(nct, str):
                    found[nct] = record
    return found


# ---------------------------------------------------------------------------
# Fetch (F1-F4)
# ---------------------------------------------------------------------------


def _fetch_search(
    http: httpx.Client,
    name: str,
    query: str,
    *,
    cache_dir: Path,
    day: str,
    limiter: RateLimiter,
    sleep: Callable[[float], None],
    max_retries: int,
    backoff: float,
) -> list[dict[str, Any]]:
    """All records of one search, every page written to the cache before it is parsed."""
    records: list[dict[str, Any]] = []
    token: str | None = None
    page = 1
    total: int | None = None
    while True:
        params: dict[str, str | int] = {"query.cond": query, "pageSize": PAGE_SIZE, "countTotal": "true"}
        if token:
            params["pageToken"] = token
        response = get_with_retries(
            http,
            API_URL,
            params=params,
            limiter=limiter,
            sleep=sleep,
            max_retries=max_retries,
            backoff=backoff,
            label=f"ClinicalTrials.gov search '{name}' page {page}",
            error=TrialsError,
        )
        try:
            body = response.json()
        except ValueError as exc:
            raise TrialsError(f"search '{name}' page {page}: the response is not JSON") from exc
        if not isinstance(body, dict):
            raise TrialsError(f"search '{name}' page {page}: the response is not a JSON object")
        _write_page(_page_path(cache_dir, day, name, page), body)
        studies = body.get("studies")
        if not isinstance(studies, list):
            raise TrialsError(f"search '{name}' page {page}: the response has no 'studies' list")
        records += studies
        if page == 1:
            total = body.get("totalCount")
        token = body.get("nextPageToken")
        if not token:
            break
        page += 1
    if isinstance(total, int) and total != len(records):
        raise TrialsError(f"search '{name}': the registry reports {total} studies but {len(records)} were received")
    return records


def merge_fetch(
    data: Mapping[str, Any] | None, results: Mapping[str, Sequence[Mapping[str, Any]]], day: str
) -> dict[str, Any]:
    """The new data file from the old one (or None) and the raw records of each search.

    Copied fields are replaced by the latest record. ``hypotheses``, ``mapping`` and ``mapping_source`` of a known
    study are kept. A study the fetch did not return keeps its last values with ``searches`` set to ``[]``: it is no
    longer in the registry's result and is not listed (D5)."""
    old = {e["nct_id"]: e for e in (data or {}).get("studies", [])}
    seen: dict[str, dict[str, Any]] = {}
    for name, records in results.items():
        for raw in records:
            fields = copied_fields(raw)
            entry = seen.setdefault(fields["nct_id"], {**fields, "searches": []})
            entry.update(fields)
            if name not in entry["searches"]:
                entry["searches"].append(name)
    entries: dict[str, dict[str, Any]] = {}
    for nct, entry in old.items():
        entries[nct] = {**entry, "searches": []}
    for nct, fields in seen.items():
        previous = old.get(nct)
        keep = (
            {k: previous[k] for k in ("hypotheses", "mapping", "mapping_source")}
            if previous
            else {"hypotheses": [], "mapping": "not_mapped", "mapping_source": None}
        )
        fields["searches"] = [n for n in SEARCHES if n in fields["searches"]]
        entries[nct] = {k: ({**fields, **keep})[k] for k in ENTRY_FIELDS}
    ordered = [{k: entries[n][k] for k in ENTRY_FIELDS} for n in sorted(entries)]
    return {"fetched": day, "searches": dict(SEARCHES), "studies": ordered}


def dump_data(data: Mapping[str, Any]) -> str:
    return yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True, width=120)


def load_data(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TrialsError(f"{path}: cannot read the registry file: {exc}") from exc
    if not isinstance(data, dict):
        raise TrialsError(f"{path}: the top level must be a mapping")
    if isinstance(data.get("fetched"), dt.date):
        data["fetched"] = data["fetched"].isoformat()
    return data


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def run_fetch(
    data_file: Path,
    cache_dir: Path,
    *,
    day: str,
    offline: bool = False,
    http: httpx.Client | None = None,
    limiter: RateLimiter | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_retries: int = 4,
    backoff: float = 2.0,
) -> dict[str, Any]:
    """Fetch both searches (or read them from the cache with ``offline``) and write the data file. Nothing is
    written to the data file unless every page of both searches was received."""
    results: dict[str, list[dict[str, Any]]] = {}
    if offline:
        for name in SEARCHES:
            results[name] = cached_records(cache_dir, day, name)
    else:
        client = http or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120.0, follow_redirects=True)
        try:
            gate = limiter or RateLimiter(MAX_PER_SECOND)
            for name, query in SEARCHES.items():
                results[name] = _fetch_search(
                    client,
                    name,
                    query,
                    cache_dir=cache_dir,
                    day=day,
                    limiter=gate,
                    sleep=sleep,
                    max_retries=max_retries,
                    backoff=backoff,
                )
        finally:
            if http is None:
                client.close()
    old = load_data(data_file) if data_file.is_file() else None
    merged = merge_fetch(old, results, day)
    _atomic_write(data_file, dump_data(merged))
    return merged


# ---------------------------------------------------------------------------
# Validator (D3, D4)
# ---------------------------------------------------------------------------


def known_slugs(cards_dir: Path) -> set[str]:
    return {p.stem for p in Path(cards_dir).glob("*.yaml") if p.name != cardlib.CHANGELOG_NAME}


def check_data(data: Any, slugs: Collection[str]) -> list[str]:
    """Problems of a data file, each naming the entry. An empty list means the file is valid."""
    problems: list[str] = []
    if not isinstance(data, Mapping):
        return ["the top level must be a mapping"]
    for key in ("fetched", "searches", "studies"):
        if key not in data:
            problems.append(f"missing top-level field '{key}'")
    if problems:
        return problems
    searches = data["searches"]
    if not isinstance(searches, Mapping) or not all(isinstance(v, str) for v in searches.values()):
        problems.append("'searches' must map each search name to its query string")
        searches = {}
    studies = data["studies"]
    if not isinstance(studies, list):
        return [*problems, "'studies' must be a list"]
    previous = None
    seen: set[str] = set()
    for index, entry in enumerate(studies):
        if not isinstance(entry, Mapping):
            problems.append(f"entry {index}: not a mapping")
            continue
        nct = entry.get("nct_id")
        where = f"{nct}" if isinstance(nct, str) and nct else f"entry {index}"
        missing = [f for f in ENTRY_FIELDS if f not in entry]
        if missing:
            problems.append(f"{where}: missing field(s) {', '.join(missing)}")
            continue
        extra = [f for f in entry if f not in ENTRY_FIELDS]
        if extra:
            problems.append(f"{where}: unknown field(s) {', '.join(extra)}")
        if not isinstance(nct, str) or not nct:
            problems.append(f"{where}: nct_id must be a non-empty string")
            continue
        if nct in seen:
            problems.append(f"{where}: duplicate registry number")
        elif previous is not None and nct < previous:
            problems.append(f"{where}: registry numbers are not sorted (after {previous})")
        seen.add(nct)
        previous = nct if previous is None or nct > previous else previous
        if not entry["title"] or not isinstance(entry["title"], str):
            problems.append(f"{where}: title must be a non-empty string")
        if entry["status"] not in KNOWN_STATUSES:
            problems.append(f"{where}: unknown status {entry['status']!r}")
        if entry["study_type"] not in KNOWN_STUDY_TYPES:
            problems.append(f"{where}: unknown study type {entry['study_type']!r}")
        countries = entry["countries"]
        if not isinstance(countries, list) or countries != sorted(set(countries)):
            problems.append(f"{where}: countries must be a sorted list without duplicates")
        enrol = entry["enrollment"]
        if enrol is not None and not (isinstance(enrol, Mapping) and set(enrol) == {"count", "type"}):
            problems.append(f"{where}: enrollment must be null or hold count and type")
        names = entry["searches"]
        if not isinstance(names, list) or any(n not in searches for n in names):
            problems.append(f"{where}: searches must be a list of the search names")
        hyps = entry["hypotheses"]
        if not isinstance(hyps, list):
            problems.append(f"{where}: hypotheses must be a list")
            continue
        unknown = [h for h in hyps if h not in slugs]
        if unknown:
            problems.append(f"{where}: unknown card slug(s) in hypotheses: {', '.join(map(str, unknown))}")
        if len(set(map(str, hyps))) != len(hyps):
            problems.append(f"{where}: hypotheses repeats a card")
        if entry["mapping"] not in MAPPING_STATES:
            problems.append(f"{where}: mapping must be one of {', '.join(MAPPING_STATES)}")
        elif hyps and entry["mapping"] != "accepted":
            problems.append(f"{where}: hypotheses is not empty but mapping is {entry['mapping']!r}, not 'accepted'")
    return problems


def check_against_cache(data: Mapping[str, Any], records: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Every copied field of every entry compared with the newest cached raw record that holds the study."""
    problems: list[str] = []
    for entry in data.get("studies", []):
        nct = entry.get("nct_id")
        raw = records.get(nct)
        if raw is None:
            problems.append(f"{nct}: no cached record")
            continue
        fresh = copied_fields(raw)
        for field in COPIED_FIELDS:
            if entry.get(field) != fresh[field]:
                problems.append(
                    f"{nct}: field '{field}' is {entry.get(field)!r} but the cached record has {fresh[field]!r}"
                )
    return problems


# ---------------------------------------------------------------------------
# Listing: what the site shows
# ---------------------------------------------------------------------------


def is_ongoing(entry: Mapping[str, Any]) -> bool:
    return entry["status"] in ONGOING_STATUSES


def is_listed(entry: Mapping[str, Any]) -> bool:
    """Ongoing, in the latest fetch, mapping accepted, at least one card."""
    return (
        is_ongoing(entry) and bool(entry["searches"]) and entry["mapping"] == "accepted" and bool(entry["hypotheses"])
    )


def listed_by_card(data: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Card slug -> its listed studies, sorted by registry number."""
    out: dict[str, list[dict[str, Any]]] = {}
    for entry in data["studies"]:
        if is_listed(entry):
            for slug in entry["hypotheses"]:
                out.setdefault(slug, []).append(entry)
    return {slug: sorted(rows, key=lambda e: e["nct_id"]) for slug, rows in out.items()}


def unlisted_ongoing(data: Mapping[str, Any]) -> int:
    """Ongoing studies of the latest fetch that are not listed."""
    return sum(1 for e in data["studies"] if is_ongoing(e) and e["searches"] and not is_listed(e))


def load_reliability(path: Path) -> bool:
    """True only when the file exists and says ``passed: true``. A file that cannot be read is an error."""
    path = Path(path)
    if not path.is_file():
        return False
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TrialsError(f"{path}: cannot read the reliability file: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("passed"), bool):
        raise TrialsError(f"{path}: must be a mapping with a true or false 'passed'")
    return data["passed"]


# ---------------------------------------------------------------------------
# Mapping files (M1-M3)
# ---------------------------------------------------------------------------


def run_dir(date: str, root: Path = DEFAULT_PIPELINE_DIR) -> Path:
    return root / date / "trials"


def map_plan(
    data: Mapping[str, Any],
    records: Mapping[str, Mapping[str, Any]],
    cards: Sequence[cardlib.Card],
    out: Path,
    *,
    ids: Sequence[str] | None = None,
) -> list[Path]:
    """Write ``cards.json`` and ``batch-<n>.json`` (at most 20 studies each) into ``out``. Selects ongoing studies of
    the latest fetch with ``mapping: not_mapped``, or the given registry numbers."""
    by_id = {e["nct_id"]: e for e in data["studies"]}
    if ids is not None:
        wanted = sorted(set(ids))
        unknown = [i for i in wanted if i not in by_id]
        if unknown:
            raise TrialsError(f"not in the data file: {', '.join(unknown)}")
    else:
        wanted = [
            n for n, e in sorted(by_id.items()) if is_ongoing(e) and e["searches"] and e["mapping"] == "not_mapped"
        ]
    missing = [n for n in wanted if n not in records]
    if missing:
        raise TrialsError(f"no cached record for: {', '.join(missing)} (run 'trials fetch' first)")
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    cards_json = [{"slug": c.slug, "name": c.name, "core_claim": c.core_claim.text} for c in cards]
    path = out / "cards.json"
    path.write_text(json.dumps(cards_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    written.append(path)
    for n, start in enumerate(range(0, len(wanted), BATCH_SIZE), start=1):
        batch = [context_fields(records[i]) for i in wanted[start : start + BATCH_SIZE]]
        path = out / f"batch-{n}.json"
        path.write_text(json.dumps(batch, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        written.append(path)
    return written


def _load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TrialsError(f"{path}: cannot read: {exc}") from exc


def batch_numbers(run: Path) -> list[int]:
    numbers = []
    for p in Path(run).glob("batch-*.json"):
        stem = p.stem.removeprefix("batch-")
        if stem.isdigit():
            numbers.append(int(stem))
    return sorted(numbers)


def _batch_ids(run: Path, n: int) -> list[str]:
    batch = _load_json(run / f"batch-{n}.json")
    if not isinstance(batch, list):
        raise TrialsError(f"{run / f'batch-{n}.json'}: must be a list")
    return [str(item.get("nct_id")) for item in batch]


def _rows(path: Path, expected: Sequence[str], allowed_keys: Sequence[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """The rows of a map or review file and the problems: not a list, a row that is not an object, extra keys, a
    missing, repeated or extra registry number."""
    problems: list[str] = []
    data = _load_json(path)
    if not isinstance(data, list):
        return [], [f"{path}: must be a list with one object per study"]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            problems.append(f"{path}: item {i} is not an object")
            continue
        nct = row.get("nct_id")
        if not isinstance(nct, str):
            problems.append(f"{path}: item {i} has no nct_id")
            continue
        extra = sorted(set(row) - set(allowed_keys))
        if extra:
            problems.append(f"{path}: {nct}: extra key(s) {', '.join(extra)}")
        if nct in seen:
            problems.append(f"{path}: {nct} appears more than once")
            continue
        seen.add(nct)
        if nct not in expected:
            problems.append(f"{path}: {nct} is not in the batch")
        rows.append(row)
    problems += [f"{path}: {n} is missing" for n in expected if n not in seen]
    return rows, problems


def validate_mapping(run: Path, n: int, slugs: Collection[str]) -> tuple[list[dict[str, Any]], list[str]]:
    path = run / f"map-{n}.json"
    if not path.is_file():
        return [], [f"{path}: the mapping file is missing"]
    rows, problems = _rows(path, _batch_ids(run, n), ("nct_id", "cards", "reason"))
    for row in rows:
        nct = row["nct_id"]
        cards = row.get("cards")
        if not isinstance(cards, list) or not all(isinstance(c, str) for c in cards):
            problems.append(f"{path}: {nct}: 'cards' must be a list of slugs")
            continue
        unknown = [c for c in cards if c not in slugs]
        if unknown:
            problems.append(f"{path}: {nct}: unknown card slug(s) {', '.join(unknown)}")
        if len(set(cards)) != len(cards):
            problems.append(f"{path}: {nct}: 'cards' repeats a slug")
        reason = row.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            problems.append(f"{path}: {nct}: 'reason' must be one non-empty sentence")
    return rows, problems


def validate_review(run: Path, n: int) -> tuple[list[dict[str, Any]], list[str]]:
    path = run / f"review-{n}.json"
    if not path.is_file():
        return [], [f"{path}: the review file is missing"]
    rows, problems = _rows(path, _batch_ids(run, n), ("nct_id", "verdict", "finding"))
    for row in rows:
        nct = row["nct_id"]
        verdict = row.get("verdict")
        finding = row.get("finding")
        if verdict not in ("accept", "reject"):
            problems.append(f"{path}: {nct}: verdict must be 'accept' or 'reject'")
        elif verdict == "reject" and not (isinstance(finding, str) and finding.strip()):
            problems.append(f"{path}: {nct}: a reject needs a finding")
        elif verdict == "accept" and "finding" in row:
            problems.append(f"{path}: {nct}: an accept has no finding")
    return rows, problems


def record_mapping(run: Path, slugs: Collection[str]) -> list[str]:
    """Validate every ``map-<n>.json`` of the run. Writes nothing: the mapping reaches the data file only through
    ``record-review``."""
    numbers = batch_numbers(run)
    if not numbers:
        return [f"{run}: no batch files"]
    problems: list[str] = []
    for n in numbers:
        problems += validate_mapping(run, n, slugs)[1]
    return problems


def record_review(data: Mapping[str, Any], run: Path, slugs: Collection[str]) -> tuple[dict[str, Any], list[str]]:
    """The data file with the accepted mappings written in (D2), or the problems. Needs a valid mapping file and a
    valid review file for every batch of the run; nothing is applied unless all of them are valid."""
    numbers = batch_numbers(run)
    if not numbers:
        return dict(data), [f"{run}: no batch files"]
    problems: list[str] = []
    decided: list[tuple[str, list[str], str, str]] = []
    for n in numbers:
        map_rows, p = validate_mapping(run, n, slugs)
        problems += p
        review_rows, p = validate_review(run, n)
        problems += p
        if p or not map_rows:
            continue
        cards_of = {r["nct_id"]: r["cards"] for r in map_rows}
        for row in review_rows:
            nct = row["nct_id"]
            if nct in cards_of:
                decided.append((nct, cards_of[nct], row["verdict"], f"{run.as_posix()}/review-{n}.json"))
    by_id = {e["nct_id"]: e for e in data["studies"]}
    problems += [f"{nct}: not in the data file" for nct, *_ in decided if nct not in by_id]
    if problems:
        return dict(data), problems
    studies = [dict(e) for e in data["studies"]]
    index = {e["nct_id"]: e for e in studies}
    for nct, cards, verdict, source in decided:
        entry = index[nct]
        if verdict == "accept":
            entry["hypotheses"] = sorted(cards)
            entry["mapping"] = "accepted"
        else:
            entry["hypotheses"] = []
            entry["mapping"] = "rejected"
        entry["mapping_source"] = source
    return {**data, "studies": studies}, []


# ---------------------------------------------------------------------------
# Sample and reliability (M4, M5)
# ---------------------------------------------------------------------------


def sample_ids(data: Mapping[str, Any], seed: int, n: int = 50) -> list[str]:
    """All ongoing ``me_cfs`` studies of the latest fetch plus ``n`` ongoing ``long_covid``-only studies, drawn with
    ``random.Random(seed)`` from the studies sorted by registry number. Sorted."""
    ongoing = [e for e in data["studies"] if is_ongoing(e) and e["searches"]]
    me = [e["nct_id"] for e in ongoing if "me_cfs" in e["searches"]]
    lc_only = sorted(e["nct_id"] for e in ongoing if "me_cfs" not in e["searches"])
    drawn = random.Random(seed).sample(lc_only, min(n, len(lc_only)))
    return sorted({*me, *drawn})


def reliability_passed(total: int, rejects: int) -> bool:
    """At most one mapping in five rejected: ``rejects * 5 <= total``. No mapping at all is not a pass."""
    return total > 0 and rejects * RELIABILITY_MAX_REJECT_SHARE <= total


def reliability(data: Mapping[str, Any], run: Path, seed: int | None, today: str) -> tuple[dict[str, Any], list[str]]:
    """The numbers of a run's review files, or the problems."""
    numbers = batch_numbers(run)
    if not numbers:
        return {}, [f"{run}: no batch files"]
    by_id = {e["nct_id"]: e for e in data["studies"]}
    problems: list[str] = []
    verdicts: list[tuple[str, str]] = []
    for n in numbers:
        rows, p = validate_review(run, n)
        problems += p
        verdicts += [(r["nct_id"], r["verdict"]) for r in rows]
    problems += [f"{nct}: not in the data file" for nct, _ in verdicts if nct not in by_id]
    if problems:
        return {}, problems
    total = len(verdicts)
    rejects = sum(v == "reject" for _, v in verdicts)
    per_search: dict[str, dict[str, Any]] = {}
    for name in SEARCHES:
        mine = [v for nct, v in verdicts if name in by_id[nct]["searches"]]
        r = sum(v == "reject" for v in mine)
        per_search[name] = {"total": len(mine), "rejects": r, "reject_rate": round(r / len(mine), 4) if mine else None}
    result = {
        "date": today,
        "sample_seed": seed,
        "run": run.as_posix(),
        "total": total,
        "rejects": rejects,
        "reject_rate": round(rejects / total, 4) if total else None,
        "per_search": per_search,
        "passed": reliability_passed(total, rejects),
    }
    return result, []


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m me_atlas.trials", description="Registered ongoing studies.")
    parser.add_argument("--data-file", type=Path, default=DEFAULT_DATA_FILE, help=argparse.SUPPRESS)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--cards-dir", type=Path, default=DEFAULT_CARDS_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--reliability-file", type=Path, default=DEFAULT_RELIABILITY_FILE, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="fetch both searches, cache the pages, write registry/trials.yaml")
    fetch.add_argument("--offline", action="store_true", help="read the cached pages of --date, make no request")
    fetch.add_argument("--date", default=None, help="fetch date, YYYY-MM-DD (default: today)")

    check = sub.add_parser("check", help="validate registry/trials.yaml")
    check.add_argument("--cache", action="store_true", help="also compare every copied field with the cached record")

    plan = sub.add_parser("map-plan", help="write the context batches for the mapping agent")
    plan.add_argument("--ids", nargs="+", default=None, help="map exactly these registry numbers")
    plan.add_argument("--ids-file", type=Path, default=None, help="a file with one registry number per line")
    plan.add_argument("--date", default=None, help="run date for data/pipeline/<date>/trials (default: today)")
    plan.add_argument("--out", type=Path, default=None, help="output directory (default: the run directory)")

    for name, text in (
        ("record-mapping", "validate the map-<n>.json files of a run"),
        ("record-review", "validate the review files and write hypotheses and mapping to the data file"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--run", type=Path, required=True, help="the run directory (data/pipeline/<date>/trials)")

    samp = sub.add_parser("sample", help="the reliability sample: all ongoing me_cfs plus n long_covid-only")
    samp.add_argument("--seed", type=int, required=True)
    samp.add_argument("--n", type=int, default=50)
    samp.add_argument("--out", type=Path, default=None, help="write the registry numbers to this file")

    rel = sub.add_parser("reliability", help="compute the reject rate of a run and write registry/reliability.yaml")
    rel.add_argument("--run", type=Path, required=True)
    rel.add_argument("--seed", type=int, required=True, help="the seed of the sample the run mapped")
    return parser


def _slugs(args: argparse.Namespace) -> set[str]:
    return known_slugs(args.cards_dir)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    today = dt.date.today().isoformat()
    try:
        return _run(args, today)
    except TrialsError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace, today: str) -> int:
    cmd = args.command
    if cmd == "fetch":
        day = args.date or today
        merged = run_fetch(args.data_file, args.cache_dir, day=day, offline=args.offline)
        ongoing = [e for e in merged["studies"] if e["searches"] and is_ongoing(e)]
        print(
            f"OK: {len(merged['studies'])} studies in {args.data_file.as_posix()} "
            f"({len(ongoing)} ongoing), fetched {day}"
        )
        return 0
    data = load_data(args.data_file) if args.data_file.is_file() else None
    if data is None:
        raise TrialsError(f"{args.data_file}: no registry file (run 'trials fetch' first)")
    if cmd == "check":
        problems = check_data(data, _slugs(args))
        if args.cache:
            problems += check_against_cache(data, latest_cache_records(args.cache_dir))
        for p in problems:
            print(p, file=sys.stderr)
        if problems:
            print(f"FAILED: {len(problems)} problem(s) in {args.data_file.as_posix()}", file=sys.stderr)
            return 1
        print(f"OK: {len(data['studies'])} studies, {args.data_file.as_posix()} is valid")
        return 0
    if cmd == "map-plan":
        ids = args.ids
        if args.ids_file is not None:
            ids = [*(ids or []), *args.ids_file.read_text(encoding="utf-8").split()]
        out = args.out or run_dir(args.date or today)
        cards = cardlib.load_cards(args.cards_dir)
        records = latest_cache_records(args.cache_dir)
        written = map_plan(data, records, cards, out, ids=ids)
        for path in written:
            print(path.as_posix())
        print(f"OK: {len(written) - 1} batch file(s) in {out.as_posix()}")
        return 0
    if cmd == "record-mapping":
        problems = record_mapping(args.run, _slugs(args))
        for p in problems:
            print(p, file=sys.stderr)
        if problems:
            print(f"FAILED: {len(problems)} problem(s); the mapping was not accepted", file=sys.stderr)
            return 1
        print(f"OK: {len(batch_numbers(args.run))} mapping file(s) are valid")
        return 0
    if cmd == "record-review":
        new, problems = record_review(data, args.run, _slugs(args))
        for p in problems:
            print(p, file=sys.stderr)
        if problems:
            print(f"FAILED: {len(problems)} problem(s); {args.data_file.as_posix()} is unchanged", file=sys.stderr)
            return 1
        _atomic_write(args.data_file, dump_data(new))
        accepted = sum(e["mapping"] == "accepted" for e in new["studies"])
        rejected = sum(e["mapping"] == "rejected" for e in new["studies"])
        print(f"OK: {accepted} accepted, {rejected} rejected mapping(s) in {args.data_file.as_posix()}")
        return 0
    if cmd == "sample":
        ids = sample_ids(data, args.seed, args.n)
        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text("\n".join(ids) + "\n", encoding="utf-8", newline="\n")
            print(f"OK: {len(ids)} registry numbers written to {args.out.as_posix()}")
        else:
            print("\n".join(ids))
        return 0
    if cmd == "reliability":
        result, problems = reliability(data, args.run, args.seed, today)
        for p in problems:
            print(p, file=sys.stderr)
        if problems:
            print(f"FAILED: {len(problems)} problem(s); no reliability file written", file=sys.stderr)
            return 1
        _atomic_write(args.reliability_file, yaml.safe_dump(result, sort_keys=False))
        print(
            f"{'PASSED' if result['passed'] else 'NOT PASSED'}: {result['rejects']} reject(s) of {result['total']} "
            f"({result['reject_rate']}); written to {args.reliability_file.as_posix()}"
        )
        return 0
    raise TrialsError(f"unknown command {cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
