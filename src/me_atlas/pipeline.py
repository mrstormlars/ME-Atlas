"""The weekly pipeline: the steps that code can do. Classification, drafting and review are Claude Code
subagents (``.claude/agents/``) driven by ``/ukentlig``; this module prepares their input, validates their
output, applies their operations and builds the report and the pull request.

Command line::

    uv run python -m me_atlas.pipeline prepare [--since YYYY-MM-DD]
    uv run python -m me_atlas.pipeline record-classification
    uv run python -m me_atlas.pipeline context <slug> <pmid>
    uv run python -m me_atlas.pipeline apply <slug> <ops file> [--round 1|2]
    uv run python -m me_atlas.pipeline record-review <slug> <pmid> [--round 1|2]
    uv run python -m me_atlas.pipeline audit-plan <slug> <pmid> | --card <slug> [--out DIR]
    uv run python -m me_atlas.pipeline record-audit <slug> <pmid> [--second] | --card <slug> --file PATH
    uv run python -m me_atlas.pipeline audit-sample [--seed S]
    uv run python -m me_atlas.pipeline translation-plan [--lang nb]
    uv run python -m me_atlas.pipeline report
    uv run python -m me_atlas.pipeline pr [--dry-run] [--no-pr]

Everything is kept in ``data/pipeline/<date>/`` (gitignored): see ``docs/pipeline.md`` for the layout.
No step here calls an AI. Tests inject the fetch, the full-text loader and the subprocess runner.
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import math
import os
import random
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from me_atlas import cards, citations, europepmc, pubmed, translations
from me_atlas.cards import CHANGELOG_NAME, NonEmptyStr, Slug, StudyId
from me_atlas.http import load_dotenv
from me_atlas.operations import (
    AddParagraph,
    AddStudy,
    OperationError,
    OpsFile,
    Propose,
    ReplaceParagraph,
    apply_operations,
    parse_ops,
    tiers,
)

DEFAULT_PIPELINE_DIR = Path("data/pipeline")
DEFAULT_SPEC = Path("docs/ME-Atlas-functional-spec.md")
# The full text goes into the context file up to this many characters; the file says so when it cuts.
FULLTEXT_CHAR_BUDGET = 60_000
MAX_ROUNDS = 2
# Each cited record's full text goes into an audit context file up to this many characters; the file says so
# when it cuts. (A card cites many studies, so the budget per record is lower than for the drafting context.)
AUDIT_FULLTEXT_CHAR_BUDGET = 12_000
# A rubric excerpt in an audit record must be at least this long after normalisation (contract decision D5).
MIN_RUBRIC_CHARS = 20
BASE_BRANCH = "main"

Pmid = Annotated[str, StringConstraints(pattern=r"^\d+$")]
# A preprint with no PMID is named by its DOI: "doi:10.xxxx/..." (the study id it would have on a card).
PreprintId = Annotated[str, StringConstraints(pattern=r"^doi:10\.\S+$")]


class PipelineError(Exception):
    """A step cannot continue; the message says what to fix."""


# ---------------------------------------------------------------------------
# Schemas of the agent output files
# ---------------------------------------------------------------------------


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Classification(_M):
    """One paper's classification. Names the paper by exactly one of ``pmid`` (a PubMed paper) or ``id``
    (a ``doi:`` preprint that has no PMID, as in papers.json)."""

    pmid: Pmid | None = None
    id: PreprintId | None = None
    cards: list[Slug]
    article_type: Literal["original", "review", "other"]
    new_hypothesis: NonEmptyStr | None
    reason: NonEmptyStr

    @model_validator(mode="after")
    def _one_key(self) -> Classification:
        if (self.pmid is None) == (self.id is None):
            raise ValueError("name the paper by exactly one of 'pmid' or 'id'")
        return self

    @property
    def key(self) -> str:
        """The paper's key in this run: its PMID, or its ``doi:`` id."""
        return self.pmid if self.pmid is not None else str(self.id)


class ClassifyFile(_M):
    papers: list[Classification]


SEVERITY_ORDER = {"must_fix": 0, "advisory": 1}


class Finding(_M):
    operation: Annotated[int, Field(strict=True, ge=0)] | None
    severity: Literal["must_fix", "advisory"]
    problem: NonEmptyStr
    fix: NonEmptyStr | None = None


class ReviewFile(_M):
    card: Slug
    paper: StudyId
    verdict: Literal["accept", "reject"]
    findings: list[Finding]
    # The reviewer's one-line reason to list the paper under "Not on the card" in the card header (optional).
    not_on_card: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _reject_needs_a_finding(self) -> ReviewFile:
        if self.verdict == "reject" and not self.findings:
            raise ValueError("a reject verdict needs at least one finding saying what is wrong")
        if self.verdict == "accept" and any(f.severity == "must_fix" for f in self.findings):
            raise ValueError("accept with must_fix findings is not allowed; verdict must be reject")
        return self


AUDIT_DECISIONS = ("accept", "reject", "accept_lower")


class AuditEvidence(_M):
    source: StudyId
    quote: NonEmptyStr


class AuditPart(_M):
    decision_part: NonEmptyStr
    rubric: NonEmptyStr
    evidence: list[AuditEvidence]


class AuditRecord(_M):
    """What the auditor writes: one decision on one change (``paper`` set) or on a whole card (``paper`` absent)."""

    card: Slug
    paper: StudyId | None = None
    decision: Literal["accept", "reject", "accept_lower"]
    accepted_level: Annotated[int, Field(strict=True, ge=0, le=5)] | None = None
    parts: Annotated[list[AuditPart], Field(min_length=1)]
    reasons_summary: NonEmptyStr
    would_change: NonEmptyStr

    @model_validator(mode="after")
    def _level_and_summary(self) -> AuditRecord:
        if self.decision == "accept_lower" and self.accepted_level is None:
            raise ValueError("accept_lower needs accepted_level (0-5, lower than the proposed or current level)")
        if self.decision != "accept_lower" and self.accepted_level is not None:
            raise ValueError("accepted_level is only for accept_lower")
        if "\n" in self.reasons_summary:
            raise ValueError("reasons_summary must be one line")
        return self


def by_severity(findings: list[Finding]) -> list[Finding]:
    """must_fix findings first, otherwise in the reviewer's order."""
    return sorted(findings, key=lambda f: SEVERITY_ORDER[f.severity])


# ---------------------------------------------------------------------------
# Paths and small helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    run_dir: Path
    cards_dir: Path = Path("cards")
    drafts_dir: Path = Path("drafts")
    cache_dir: Path = Path("data/cache")
    spec_path: Path = DEFAULT_SPEC
    pipeline_dir: Path = DEFAULT_PIPELINE_DIR
    translations_dir: Path = translations.DEFAULT_DIR
    audits_dir: Path = Path("audits")

    @property
    def card_format_path(self) -> Path:
        """``docs/card-format.md``, next to the functional spec."""
        return self.spec_path.parent / "card-format.md"

    def audit_context_path(self, slug: str, key: str | None = None) -> Path:
        """``audit-context/<slug>-<key>.md`` for a change; ``audit-context/<slug>.md`` for a whole-card audit."""
        return self.f("audit-context", f"{slug}-{key}.md" if key else f"{slug}.md")

    def audit_path(self, slug: str, key: str, second: bool = False) -> Path:
        """The record the auditor writes for a change; the consistency run writes ``...-second.yaml``."""
        return self.f("audit", f"{slug}-{key}{'-second' if second else ''}.yaml")

    @property
    def ledger_path(self) -> Path:
        """Which papers earlier runs have processed (gitignored, shared by all runs)."""
        return self.pipeline_dir / "processed.json"

    def f(self, *parts: str) -> Path:
        return self.run_dir.joinpath(*parts)

    def ops_path(self, slug: str, pmid: str, n: int) -> Path:
        return self.f("ops", f"{slug}-{pmid}-r{n}.json")

    def checks_path(self, slug: str, pmid: str, n: int) -> Path:
        return self.f("checks", f"{slug}-{pmid}-r{n}.json")

    def review_path(self, slug: str, pmid: str, n: int) -> Path:
        return self.f("review", f"{slug}-{pmid}-r{n}.json")

    def applied_dir(self, slug: str, pmid: str, n: int) -> Path:
        return self.f("applied", f"{slug}-{pmid}-r{n}")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PipelineError(f"{path} does not exist") from exc
    except (OSError, ValueError) as exc:
        raise PipelineError(f"{path} is not readable JSON: {exc}") from exc


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _log(cfg: Config, event: dict[str, Any]) -> None:
    with (cfg.f("log.jsonl")).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _pydantic_lines(exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        out.append(f"{loc}: {err['msg']}" if loc else err["msg"])
    return out


def card_files(cfg: Config) -> dict[str, Path]:
    """Slug to file for every card in cards/ and drafts/. A draft is the newer text, so it wins."""
    found: dict[str, Path] = {}
    for directory in (cfg.cards_dir, cfg.drafts_dir):
        if directory.is_dir():
            for path in sorted(directory.glob("*.yaml")):
                if path.name != CHANGELOG_NAME:
                    found[path.stem] = path
    return found


def _base_card(cfg: Config, slug: str) -> Path:
    path = card_files(cfg).get(slug)
    if path is None:
        raise PipelineError(f"no card or draft '{slug}' in {cfg.cards_dir}/ or {cfg.drafts_dir}/")
    return path


def _load_card(path: Path) -> cards.Card:
    try:
        return cards.load_card(path)
    except cards.CardValidationError as exc:
        raise PipelineError(f"{path} does not validate; fix it before running the pipeline:\n{exc}") from exc


def _cited_pmids(cfg: Config) -> dict[str, list[str]]:
    """PMID to the slugs of the cards that cite it."""
    cited: dict[str, list[str]] = {}
    for slug, path in card_files(cfg).items():
        for study in _load_card(path).studies:
            if study.id.startswith("pmid:"):
                cited.setdefault(study.id.removeprefix("pmid:"), []).append(slug)
    return cited


def _record(cfg: Config, pmid: str) -> pubmed.PubMedRecord:
    try:
        return pubmed.RawCache(cfg.cache_dir).read_record(pmid)
    except FileNotFoundError as exc:
        raise PipelineError(
            f"no cached PubMed record for pmid:{pmid}; "
            f"fetch it with `uv run python -m me_atlas.pubmed fetch --ids {pmid}`"
        ) from exc
    except pubmed.ParseError as exc:
        raise PipelineError(f"the cached record for pmid:{pmid} is unreadable: {exc}") from exc


def _run_papers(cfg: Config) -> list[dict[str, Any]]:
    return _read_json(cfg.f("papers.json")) if cfg.f("papers.json").exists() else []


def resolve_paper(cfg: Config, text: str) -> tuple[str, str]:
    """A paper named on the command line as ``<pmid>``, ``pmid:<pmid>``, ``doi:<doi>`` or ``PPR<digits>``.

    Returns (key, paper id): the key names the run files (the PMID digits, or the PPR id of a DOI-only preprint),
    the paper id is ``pmid:<digits>`` or ``doi:<doi>``. A ``doi:`` or PPR id must be a preprint with no PMID in
    this run's papers.json.
    """
    t = text.strip()
    digits = t.removeprefix("pmid:")
    if digits.isdigit():
        return digits, f"pmid:{digits}"
    if re.fullmatch(r"PPR\d+", t):
        found = [p for p in _run_papers(cfg) if p.get("ppr_id") == t and not p.get("pmid")]
    elif t.lower().startswith("doi:"):
        found = [p for p in _run_papers(cfg) if not p.get("pmid") and p["id"].lower() == t.lower()]
    else:
        raise PipelineError(f"not a paper: {text!r} (use a PMID, pmid:<pmid>, doi:<doi> or a PPR id)")
    if not found:
        raise PipelineError(f"{t} is not a DOI-only preprint of this run ({cfg.f('papers.json')})")
    return found[0]["ppr_id"], found[0]["id"]


def _paper_id_of_key(cfg: Config, key: str) -> str:
    """``pmid:<digits>`` for a PMID key, the ``doi:`` id of the preprint for a PPR key."""
    return f"pmid:{key}" if key.isdigit() else resolve_paper(cfg, key)[1]


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------

Fetch = Callable[[Sequence[str]], int]
# Called with the first and last day of the fetch window; returns the preprints first indexed in it.
PreprintSearch = Callable[[dt.date, dt.date], Sequence[europepmc.PreprintRecord]]

PAPER_FIELDS = (
    "id",
    "pmid",
    "doi",
    "title",
    "abstract",
    "journal",
    "year",
    "publication_types",
    "entry_date",
    "preprint",
)
# Why a preprint was not offered, in the order the reasons are tried (docs/pipeline.md).
PREPRINT_DROP_REASONS = ("published", "in_pubmed", "duplicate_doi", "superseded", "no_doi", "processed")


def paper_key(paper: dict[str, Any]) -> str:
    """The key of a papers.json entry in the ledger: its PMID, or the PPR id of a preprint with no PMID."""
    return paper["pmid"] or paper["ppr_id"]


def _ledger_order(key: str) -> tuple[int, int, str]:
    """PMIDs first, in numeric order (the order of a ledger written before preprints), then PPR ids."""
    return (0, int(key), "") if key.isdigit() else (1, 0, key)


def read_ledger(cfg: Config) -> dict[str, str]:
    """PMID (or PPR id of a preprint) to the date of the run that processed it. Empty if no run has finished
    ``report`` yet."""
    if not cfg.ledger_path.exists():
        return {}
    data = _read_json(cfg.ledger_path)
    if not isinstance(data, dict) or not isinstance(data.get("processed"), dict):
        raise PipelineError(f'{cfg.ledger_path} is not a ledger (expected {{"processed": {{pmid: date}}}})')
    return data["processed"]


def record_processed(cfg: Config) -> int:
    """Add this run's papers to the ledger. Called by ``report`` only, so an aborted run can be repeated."""
    date = _read_json(cfg.f("prepare.json"))["date"]
    processed = read_ledger(cfg)
    papers = _read_json(cfg.f("papers.json"))
    for paper in papers:
        processed[paper_key(paper)] = date
    _write_json(cfg.ledger_path, {"processed": dict(sorted(processed.items(), key=lambda kv: _ledger_order(kv[0])))})
    return len(papers)


def _pubmed_dois(cache: pubmed.RawCache) -> dict[str, str]:
    """Lower-cased DOI to PMID for every readable record in the PubMed cache (this run's window is in it)."""
    found: dict[str, str] = {}
    for path in sorted(cache.pubmed_dir.glob("*.xml")) if cache.pubmed_dir.is_dir() else []:
        try:
            record = pubmed.parse_xml(path.read_bytes())
        except (OSError, pubmed.ParseError):
            continue
        if record.doi:
            found.setdefault(record.doi.lower(), record.pmid)
    return found


def _ppr_number(ppr_id: str) -> int:
    return int(ppr_id.removeprefix("PPR"))


def _kept_per_doi(
    records: Sequence[europepmc.PreprintRecord], *, cache: pubmed.RawCache, pubmed_dois: dict[str, str]
) -> dict[str, str]:
    """Lower-cased DOI to the PPR id kept when several records share it: the highest version number, then the
    highest PPR number. Only records not already dropped as ``published`` or ``in_pubmed`` are compared."""
    kept: dict[str, europepmc.PreprintRecord] = {}
    for r in records:
        if not r.doi or _early_drop(r, cache=cache, pubmed_dois=pubmed_dois) is not None:
            continue
        best = kept.get(r.doi.lower())
        rank = (r.version_number or 0, _ppr_number(r.ppr_id))
        if best is None or rank > (best.version_number or 0, _ppr_number(best.ppr_id)):
            kept[r.doi.lower()] = r
    return {doi: r.ppr_id for doi, r in kept.items()}


def _early_drop(
    r: europepmc.PreprintRecord, *, cache: pubmed.RawCache, pubmed_dois: dict[str, str]
) -> dict[str, Any] | None:
    """The ``published`` and ``in_pubmed`` reasons."""
    row: dict[str, Any] = {"ppr_id": r.ppr_id, "doi": r.doi}
    if r.published:
        links = [
            {"pmid": link.pmid, "in_pubmed_cache": cache.has(link.pmid), "note": link.note} for link in r.published
        ]
        return {**row, "reason": "published", "published": links}
    if r.doi and r.doi.lower() in pubmed_dois:
        return {**row, "reason": "in_pubmed", "pmid": pubmed_dois[r.doi.lower()]}
    return None


def _drop_reason(
    r: europepmc.PreprintRecord,
    *,
    cache: pubmed.RawCache,
    pubmed_dois: dict[str, str],
    kept: dict[str, str],
    found_ids: set[str],
    ledger: dict[str, str],
) -> dict[str, Any] | None:
    """Why a preprint is not offered (the first of ``PREPRINT_DROP_REASONS`` that applies), or None."""
    row: dict[str, Any] = {"ppr_id": r.ppr_id, "doi": r.doi}
    if (early := _early_drop(r, cache=cache, pubmed_dois=pubmed_dois)) is not None:
        return early
    if r.doi and kept.get(r.doi.lower()) not in (None, r.ppr_id):
        return {**row, "reason": "duplicate_doi", "kept": kept[r.doi.lower()]}
    newer = [v for v in r.versions if r.version_number is not None and v.number > r.version_number]
    if any(v.ppr_id in found_ids for v in newer):
        return {**row, "reason": "superseded", "superseded_by": [v.ppr_id for v in newer if v.ppr_id in found_ids]}
    if not r.doi:
        return {**row, "reason": "no_doi"}
    if r.ppr_id in ledger:
        return {**row, "reason": "processed", "date": ledger[r.ppr_id]}
    return None


def _preprint_paper(r: europepmc.PreprintRecord) -> dict[str, Any]:
    """A preprint with no PMID as a papers.json entry: ``id`` ``doi:<doi>``, ``pmid`` null, ``preprint`` true."""
    return {
        "id": r.id,
        "pmid": None,
        "doi": r.doi,
        "title": r.title,
        "abstract": r.abstract,
        "journal": r.server,
        "year": r.year,
        "publication_types": ["Preprint"],
        "entry_date": r.first_index_date,
        "preprint": True,
        "ppr_id": r.ppr_id,
    }


def _preprints_with_published_version(cfg: Config, found: Sequence[europepmc.PreprintRecord]) -> list[dict[str, Any]]:
    """Studies marked ``preprint: true`` on a card or draft whose preprint record has a "Preprint of" link.

    The record is this run's search result with the DOI, else the cached one (``europepmc preprint <doi>``).
    Nothing is proposed: the list only tells the reader that a published version now exists.
    """
    fresh = {r.doi.lower(): r for r in found if r.doi}
    cache = europepmc.EuropePmcCache(cfg.cache_dir)
    rows: list[dict[str, Any]] = []
    for slug, path in card_files(cfg).items():
        for study in _load_card(path).studies:
            if not (study.preprint and study.id.startswith("doi:")):
                continue
            doi = study.id.removeprefix("doi:")
            try:
                record = fresh.get(doi.lower()) or europepmc.read_cached_preprint(cache, doi)
            except europepmc.EuropePmcError:
                continue  # two cached records with this DOI: the citation check reports it (C1)
            for link in record.published if record else ():
                rows.append({"card": slug, "study": study.id, "pmid": link.pmid, "note": link.note})
    return rows


def read_ids_file(path: Path) -> list[str]:
    """PMIDs from a file, one per line; a ``pmid:`` prefix is allowed, blank lines and ``#`` comments are ignored."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise PipelineError(f"cannot read the ids file {path}: {exc}") from exc
    found: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        value = line.split("#", 1)[0].strip()
        if not value:
            continue
        value = value.removeprefix("pmid:").strip()
        if not value.isdigit():
            raise PipelineError(
                f"{path}, line {number}: not a PMID (digits, optionally 'pmid:' first): {line.strip()!r}"
            )
        found.append(value)
    if not found:
        raise PipelineError(f"the ids file {path} holds no PMID")
    return found


def prepare(
    cfg: Config,
    *,
    since: dt.date | None,
    date: dt.date,
    fetch: Fetch,
    preprint_search: PreprintSearch,
    force: bool = False,
    reprocess: bool = False,
    ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Fetch, then write papers.json, cards.json and prepare.json. Returns the summary.

    With ``ids`` (PMIDs given by the caller) there is no fetch window: only the listed ids that are not cached are
    fetched (``fetch --ids``), papers.json holds exactly the listed records whatever their entry date, the ledger and
    retraction rules are those of a window run, and no preprint search is made.

    Selects the papers in the fetch window, cached or not, that no earlier finished run has processed
    (the ledger), unless ``reprocess``. Retracted papers are never selected. ``preprint_search`` finds the
    preprints first indexed in the same window; those that survive the de-duplication (``PREPRINT_DROP_REASONS``)
    are added to papers.json as ``doi:`` papers with no PMID. A failed search fails the step before anything is
    written.
    """
    if cfg.f("papers.json").exists() and not force:
        raise PipelineError(f"{cfg.run_dir} already holds a run; use --force to start it again or --date for another")
    cache = pubmed.RawCache(cfg.cache_dir)
    given = list(dict.fromkeys(ids)) if ids is not None else None
    manifest_path: Path | None = None
    if given is not None:
        manifest: dict[str, Any] = {}
        missing = [p for p in given if not cache.has(p)]
        if missing:
            code = fetch(["fetch", "--ids", *missing, "--cache-dir", str(cfg.cache_dir)])
            if code != 0:
                raise PipelineError(f"the PubMed fetch failed (exit code {code}); nothing was prepared")
        window_since = date
        found_preprints: list[europepmc.PreprintRecord] = []  # no preprint search in this mode
    else:
        runs = cfg.cache_dir / "runs"
        before = {p.name for p in runs.glob("*.json")} if runs.is_dir() else set()
        argv = ["fetch", "--since", since.isoformat()] if since else ["fetch", "--weekly"]
        code = fetch([*argv, "--cache-dir", str(cfg.cache_dir)])
        if code != 0:
            raise PipelineError(f"the PubMed fetch failed (exit code {code}); nothing was prepared")
        fresh = sorted(p for p in runs.glob("*.json") if p.name not in before) if runs.is_dir() else []
        if not fresh:
            raise PipelineError(f"the PubMed fetch wrote no new run manifest in {runs}")
        manifest_path = fresh[-1]
        manifest = _read_json(manifest_path)

        window_since = since or date - dt.timedelta(days=pubmed.WEEKLY_DAYS)
        try:
            found_preprints = list(preprint_search(window_since, date))
        except europepmc.EuropePmcError as exc:
            raise PipelineError(f"the preprint search failed ({exc}); nothing was prepared") from exc

    papers: list[dict[str, Any]] = []
    excluded_retracted: list[str] = []
    unreadable: list[str] = []
    in_window = (
        given if given is not None else list(dict.fromkeys(manifest.get("window_pmids", manifest.get("new_pmids", []))))
    )
    ledger = {} if reprocess else read_ledger(cfg)
    skipped_processed = [p for p in in_window if p in ledger]
    for pmid in (p for p in in_window if p not in ledger):
        try:
            record = cache.read_record(pmid)
        except (FileNotFoundError, pubmed.ParseError):
            unreadable.append(pmid)
            continue
        if record.retracted:
            excluded_retracted.append(pmid)
            continue
        dumped = {**record.model_dump(), "preprint": record.preprint}
        papers.append({name: dumped[name] for name in PAPER_FIELDS})

    pubmed_dois = _pubmed_dois(cache)
    found_ids = {r.ppr_id for r in found_preprints}
    kept = _kept_per_doi(found_preprints, cache=cache, pubmed_dois=pubmed_dois)
    dropped: list[dict[str, Any]] = []
    for r in found_preprints:
        why = _drop_reason(r, cache=cache, pubmed_dois=pubmed_dois, kept=kept, found_ids=found_ids, ledger=ledger)
        if why is None:
            papers.append(_preprint_paper(r))
        else:
            dropped.append(why)
    preprint_summary = {
        "searched": given is None,
        "since": window_since.isoformat(),
        "until": date.isoformat(),
        "counts": {
            "found": len(found_preprints),
            "dropped": {reason: sum(d["reason"] == reason for d in dropped) for reason in PREPRINT_DROP_REASONS},
            "offered": len(found_preprints) - len(dropped),
        },
        "dropped": dropped,
    }

    summaries = []
    for slug, path in card_files(cfg).items():
        card = _load_card(path)
        summaries.append(
            {
                "slug": slug,
                "name": card.name,
                "core_claim": card.core_claim.text,
                "level": card.level,
                "file": str(path),
                "kind": "draft" if path.parent == cfg.drafts_dir else "card",
            }
        )

    cited = _cited_pmids(cfg)
    flagged = set(manifest.get("newly_flagged_retracted_pmids", [])) | (
        set(manifest.get("new_pmids", [])) & set(manifest.get("retracted_pmids", []))
    )
    if given is not None:
        flagged = set(excluded_retracted)
    retractions = []
    for pmid in sorted(flagged & set(cited), key=int):
        try:
            title = cache.read_record(pmid).title
        except (FileNotFoundError, pubmed.ParseError):
            title = None
        retractions.append({"pmid": pmid, "title": title, "cards": sorted(cited[pmid])})

    summary = {
        "date": date.isoformat(),
        "since": since.isoformat() if since else None,
        "mode": "ids" if given is not None else "since" if since else "weekly",
        "ids": given,
        "manifest": str(manifest_path) if manifest_path else None,
        "in_window": len(in_window),
        "selected": len(papers),
        "skipped_processed": len(skipped_processed),
        "reprocess": reprocess,
        "excluded_retracted": excluded_retracted,
        "unreadable_records": unreadable,
        "retractions_on_cards": retractions,
        "counts": manifest.get("counts", {}),
        "preprints": preprint_summary,
        "preprints_published": _preprints_with_published_version(cfg, found_preprints),
    }
    _write_json(cfg.f("papers.json"), papers)
    _write_json(cfg.f("cards.json"), summaries)
    _write_json(cfg.f("prepare.json"), summary)
    _log(cfg, {"event": "prepare", **{k: summary[k] for k in ("date", "mode", "selected", "skipped_processed")}})
    return summary


# ---------------------------------------------------------------------------
# record-classification
# ---------------------------------------------------------------------------


def record_classification(cfg: Config, path: Path | None = None) -> dict[str, Any]:
    """Validate classify.json against papers.json and cards.json; on success write matches.json."""
    path = path or cfg.f("classify.json")
    raw = _read_json(path)
    try:
        parsed = ClassifyFile.model_validate(raw)
    except ValidationError as exc:
        raise PipelineError(f"{path} is malformed:\n" + "\n".join(_pydantic_lines(exc))) from exc
    # A PubMed paper is keyed by its PMID; a preprint with no PMID by its "doi:" id.
    papers = {paper["pmid"] or paper["id"]: paper for paper in _read_json(cfg.f("papers.json"))}
    slugs = {c["slug"] for c in _read_json(cfg.f("cards.json"))}

    problems: list[str] = []
    seen: set[str] = set()
    for i, item in enumerate(parsed.papers):
        where = f"papers[{i}] (pmid {item.pmid})" if item.pmid is not None else f"papers[{i}] (id {item.id})"
        if item.key not in papers:
            problems.append(f"{where}: not one of this run's papers")
        if item.key in seen:
            problems.append(f"{where}: classified more than once")
        seen.add(item.key)
        for slug in item.cards:
            if slug not in slugs:
                problems.append(f"{where}: unknown card slug '{slug}' (cards: {', '.join(sorted(slugs)) or 'none'})")
    missing = sorted(set(papers) - seen, key=_ledger_order)
    if missing:
        problems.append(f"papers not classified: {', '.join(missing)}")
    if problems:
        raise PipelineError(f"{path} is not valid:\n" + "\n".join(problems))

    matches, stopped, new_hypotheses = [], [], []
    for item in parsed.papers:
        # The paper's name in the output: {"pmid": ...} for a PubMed paper, {"id": "doi:..."} for a preprint.
        ref = {"pmid": item.pmid} if item.pmid is not None else {"id": item.id}
        if item.new_hypothesis:
            new_hypotheses.append({**ref, "hypothesis": item.new_hypothesis, "reason": item.reason})
        if item.article_type != "original":
            stopped.append({**ref, "why": f"article type: {item.article_type}"})
        elif not item.cards:
            stopped.append({**ref, "why": "matches no card"})
        else:  # a pair is named by the paper's pmid, or by the doi: id of a preprint with no PMID
            matches += [{"slug": slug, **ref} for slug in item.cards]
    result = {"matches": matches, "stopped": stopped, "new_hypotheses": new_hypotheses}
    _write_json(cfg.f("matches.json"), result)
    _log(
        cfg,
        {
            "event": "record-classification",
            "matches": len(matches),
            "stopped": len(stopped),
        },
    )
    return result


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FullTextResult:
    xml: bytes | None
    note: str


# Called with the PMID and, when the cached PubMed record has one, its PMC id; for a DOI-only preprint with its PPR
# id, its PMC id and ``preprint=<its Europe PMC record>``.
FullTextLoader = Callable[..., FullTextResult]


def fulltext_note(status: str, pmcid: str | None) -> str:
    """What the context file says about the full text of a paper, by the status ``get_fulltext`` gave."""
    if status == europepmc.STATUS_OPEN_ACCESS:
        return f"Europe PMC open access, {pmcid}"
    if status == europepmc.STATUS_PDF_ONLY:
        return f"a PMC record exists ({pmcid}), but its full text is a PDF only and it was not read"
    if status == europepmc.STATUS_PMC_NO_XML:
        return f"a PMC record exists ({pmcid}), and Europe PMC has no full-text XML for it"
    return f"no open full text (Europe PMC: {europepmc.STATUS_TEXT[status]})"


def live_fulltext_loader(cache_dir: Path) -> FullTextLoader:
    """Look the paper up in Europe PMC (cached) and read its open-access full text, if there is one."""

    def load(
        pmid: str | None, pmcid: str | None = None, *, preprint: europepmc.PreprintRecord | None = None
    ) -> FullTextResult:
        env = {**load_dotenv(), **os.environ}
        email = (env.get("CONTACT_EMAIL") or "").strip()
        if not email:
            return FullTextResult(None, "CONTACT_EMAIL is not set, so no full text was requested")
        client = europepmc.EuropePmcClient(email)
        try:
            result = europepmc.get_fulltext(
                client, europepmc.EuropePmcCache(cache_dir), pmid, pmcid=pmcid, preprint=preprint
            )
        except europepmc.EuropePmcError as exc:
            return FullTextResult(None, f"Europe PMC request failed: {exc}")
        finally:
            client.close()
        note = fulltext_note(result.status, result.pmcid)
        if result.path is None:
            return FullTextResult(None, note)
        return FullTextResult(result.path.read_bytes(), note)

    return load


def spec_section(spec_path: Path, number: int) -> str:
    """Section ``number`` of the functional spec (from its ``## N.`` heading up to ``## N+1.``)."""
    try:
        text = spec_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PipelineError(f"cannot read the functional spec {spec_path}: {exc}") from exc
    match = re.search(rf"^## {number}\. .*?(?=^## {number + 1}\. )", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise PipelineError(f"{spec_path} has no section '## {number}.' followed by '## {number + 1}.'")
    return match.group(0).strip()


def _demote_headings(markdown: str) -> str:
    """One heading level down, so a spec excerpt never adds a level-2 heading to the context file."""
    lines, in_fence = [], False
    for line in markdown.split(chr(10)):
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and re.match(r"#{1,5} ", line):
            line = "#" + line
        lines.append(line)
    return chr(10).join(lines)


PREPRINT_RULE = (
    "**This paper is a preprint.** It may only be added to the card as a study with `preprint: true` and "
    "`role: early_signal`, and it may never be cited in a level reason, a contested reason, a badge "
    "reason or a link."
)
_TAG_RE = re.compile(r"<[^>]+>")


def _preprint_record(cfg: Config, key: str) -> europepmc.PreprintRecord:
    """The cached Europe PMC record of a DOI-only preprint of this run (by PPR id); an error names the command."""
    doi = _paper_id_of_key(cfg, key).removeprefix("doi:")
    try:
        record = europepmc.read_cached_preprint(europepmc.EuropePmcCache(cfg.cache_dir), doi)
    except europepmc.EuropePmcError as exc:
        raise PipelineError(str(exc)) from exc
    if record is None:
        raise PipelineError(
            f"no cached Europe PMC preprint record for doi:{doi}; "
            f"cache it with `uv run python -m me_atlas.europepmc preprint {doi}`"
        )
    return record


def build_context(
    cfg: Config, slug: str, key: str, loader: FullTextLoader, *, budget: int = FULLTEXT_CHAR_BUDGET
) -> str:
    """The one file the drafting and review agents read about a card and a paper. No drafter output in it.

    ``key`` is a PMID, or the PPR id of a DOI-only preprint, whose context is built only from its cached
    Europe PMC record and its full text (through ``get_fulltext``).
    """
    base = _base_card(cfg, slug)
    _load_card(base)
    if key.isdigit():
        record = _record(cfg, key)
        paper_id = f"pmid:{key}"
        full = loader(key, record.pmcid)
        record_lines = [
            "## 4. The paper's PubMed record",
            "",
            f"- id: `{record.id}`",
            f"- title: {record.title}",
            f"- authors: {', '.join(record.authors) or 'not stated'}",
            f"- journal: {record.journal or 'not stated'}",
            f"- year: {record.year if record.year is not None else 'not stated'}",
            f"- doi: {record.doi or 'not stated'}",
            f"- publication types: {', '.join(record.publication_types) or 'not stated'}",
            f"- retracted: {'yes' if record.retracted else 'no'}",
            *(
                [
                    "- preprint: yes (PubMed marks this record as a preprint). It is not peer reviewed.",
                    "",
                    PREPRINT_RULE,
                ]
                if record.preprint
                else []
            ),
            "",
            "Abstract:",
            "",
            record.abstract or "(the record has no abstract)",
        ]
    else:
        pre = _preprint_record(cfg, key)
        paper_id = pre.id
        full = loader(pre.ppr_id, pre.pmcid, preprint=pre)
        abstract = " ".join(_TAG_RE.sub(" ", pre.abstract).split()) if pre.abstract else None
        record_lines = [
            "## 4. The paper's Europe PMC preprint record",
            "",
            f"- id: `{paper_id}`",
            f"- Europe PMC id: {pre.ppr_id}",
            f"- title: {pre.title}",
            f"- authors: {', '.join(pre.authors) or 'not stated'}",
            f"- server: {pre.server or 'not stated'}",
            f"- year: {pre.year if pre.year is not None else 'not stated'}",
            f"- first indexed: {pre.first_index_date or 'not stated'}",
            f"- version: {pre.version_number if pre.version_number is not None else 'not stated'}",
            "- preprint: yes (not peer reviewed)",
            "",
            PREPRINT_RULE,
            "",
            "The case definition comes from the abstract or the full text below; if neither states it, use "
            "`unverified`. Nothing else describes this paper.",
            "",
            "Abstract:",
            "",
            abstract or "(the record has no abstract)",
        ]
    inclusion = _demote_headings(spec_section(cfg.spec_path, 2))
    rubric = _demote_headings(spec_section(cfg.spec_path, 3))

    parts = [
        f"# Context: card `{slug}` and paper `{paper_id}`",
        "",
        "Everything the drafting and review steps may rely on is in this file. Cite only the studies already on "
        f"the card and `{paper_id}`. If something is not here, write TODO: verify.",
        "",
        f"## 1. The card now (`{base}`)",
        "",
        "```yaml",
        base.read_text(encoding="utf-8").rstrip("\n"),
        "```",
        "",
        "## 2. The inclusion rule (functional spec section 2)",
        "",
        inclusion,
        "",
        "## 3. The rubric (functional spec section 3)",
        "",
        rubric,
        "",
        *record_lines,
        "",
        "## 5. Full text",
        "",
    ]
    if full.xml is None:
        parts += [
            f"No full text is available: {full.note}. Work from the abstract only; a case definition that "
            "the abstract does not state is `unverified`.",
            "",
        ]
    else:
        text = europepmc.article_text(full.xml)
        total = len(text)
        parts.append(f"Source: {full.note}. The reference list is left out.")
        if total > budget:
            parts.append(
                f"TRUNCATED: the first {budget} of {total} characters follow; the rest of the full text was left out."
            )
        else:
            parts.append(f"Not truncated ({total} characters).")
        parts += ["", text[:budget], ""]
        candidates = europepmc.find_case_definitions(full.xml)
        definitions = [c for c in candidates if c.kind == "definition"]
        exclusions = [c for c in candidates if c.kind == "exclusion"]
        parts += ["## 6. Sentences found in the full text (verbatim)", ""]
        parts += ["### Sentences that may name a case definition", ""]
        if definitions:
            parts += [f"- [{c.section}] {c.sentence}" for c in definitions]
            parts += ["", "These only suggest; which definition a sentence means is for the drafter to decide."]
        else:
            parts.append("None found.")
        parts += ["", "### Sentences that may exclude people with the illness", ""]
        if exclusions:
            parts += [f"- [{c.section}] {c.sentence}" for c in exclusions]
            parts += [
                "",
                "Check whether ME/CFS itself was what the study excluded. A cohort that excluded people with "
                "ME/CFS is not an ME/CFS cohort.",
            ]
        else:
            parts.append("None found.")
        parts.append("")
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def _pmid_from_name(path: Path) -> str | None:
    """The paper key in an ops file name ``<slug>-<key>-r<N>``: a PMID, or the PPR id of a DOI-only preprint."""
    match = re.search(r"-(\d+|PPR\d+)-r\d+$", path.stem)
    return match.group(1) if match else None


def _citation_rows(issues: Sequence[citations.CitationIssue]) -> list[dict[str, str]]:
    return [{"study": i.study, "code": i.code, "level": i.level, "message": i.message} for i in issues]


def _group_warnings(base_text: str, ops: OpsFile) -> list[str]:
    """One warning for each added study without a ``group`` when every study already on the card has one.

    ``group`` is optional in the card format, so this never fails a pair. A base card with no studies, or one
    where any study lacks a group, gives no warning.
    """
    try:
        studies = (yaml.safe_load(base_text) or {}).get("studies") or []
    except yaml.YAMLError:
        return []
    if not studies or not all(isinstance(s, dict) and s.get("group") for s in studies):
        return []
    return [
        f"study {op.study.id} has no group, but every study already on the card has one"
        for op in ops.operations
        if isinstance(op, AddStudy) and not op.study.group
    ]


def apply_ops_file(cfg: Config, slug: str, ops_path: Path, n: int) -> dict[str, Any]:
    """Validate and apply one ops file to a copy of the card; run the validator and the citations check.

    Writes ``checks/<slug>-<pmid>-r<n>.json`` and, when the operations applied, ``applied/<slug>-<pmid>-r<n>/``
    with the new card and a diff. The draft in ``drafts/`` is never touched. Returns the checks record.
    """
    pmid = _pmid_from_name(ops_path)  # the paper key: a PMID, or a PPR id
    ops: OpsFile | None = None
    ops_errors: list[str] = []
    raw: Any = None
    paper_id: str | None = None
    try:
        raw = _read_json(ops_path)
        ops = parse_ops(raw)
        if ops.paper.startswith("pmid:"):
            pmid = ops.paper.removeprefix("pmid:")
        else:
            try:
                pmid, paper_id = resolve_paper(cfg, ops.paper)
            except PipelineError as exc:
                ops_errors.append(str(exc))
        if ops.card != slug:
            ops_errors.append(f"the ops file is for card '{ops.card}', not '{slug}'")
    except (PipelineError, OperationError) as exc:
        ops_errors.append(str(exc))
        if pmid is None and isinstance(raw, dict):
            candidate = str(raw.get("paper", "")).removeprefix("pmid:")
            pmid = candidate if candidate.isdigit() else None
    if pmid is None:
        raise PipelineError("cannot tell which paper the ops file is for; " + "; ".join(ops_errors))
    if paper_id is None:
        paper_id = ops.paper if ops is not None and ops.paper.startswith("doi:") else f"pmid:{pmid}"

    result: dict[str, Any] = {
        "card": slug,
        "paper": paper_id,
        "key": pmid,
        "round": n,
        "ops_file": str(ops_path),
        "ops_errors": ops_errors,
        "validator": [],
        "citations": [],
        "applied": None,
        "diff": None,
        "no_change": False,
        "tiers": {"1": 0, "2": 0},
        "warnings": [],
    }
    base = _base_card(cfg, slug)
    base_text = base.read_text(encoding="utf-8")

    new_text: str | None = None
    if ops is not None and not ops_errors:
        try:
            base_data = yaml.safe_load(base_text)
        except yaml.YAMLError:
            base_data = None
        op_tiers = tiers(ops, base_data if isinstance(base_data, dict) else None)
        result["tiers"] = {str(t): op_tiers.count(t) for t in (1, 2)}
        result["warnings"] = _group_warnings(base_text, ops)
        if not ops.operations:
            result["no_change"] = True
        else:
            try:
                new_text = apply_operations(base_text, ops, validate=False)
            except OperationError as exc:
                ops_errors.append(str(exc))

    if new_text is not None:
        out_dir = cfg.applied_dir(slug, pmid, n)
        card_path = out_dir / f"{slug}.yaml"
        _write_text(card_path, new_text)
        diff = "".join(
            difflib.unified_diff(
                base_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"{base}",
                tofile=f"applied/{slug}.yaml",
            )
        )
        _write_text(out_dir / "changes.diff", diff)
        result["applied"] = str(card_path)
        result["diff"] = str(out_dir / "changes.diff")
        # The copy sits alone in applied/; link targets (M2) resolve against the cards and drafts of the run.
        link_targets = {
            p.stem
            for directory in (cfg.drafts_dir, cfg.cards_dir)
            if directory.is_dir()
            for p in directory.glob("*.yaml")
            if p.name != CHANGELOG_NAME
        }
        _count, validator_issues = cards.validate_paths([card_path], extra_known_slugs=link_targets)
        result["validator"] = [str(i) for i in validator_issues]
        _count, cite_issues = citations.check_paths([card_path], cfg.cache_dir)
        with tempfile.TemporaryDirectory() as tmp:
            baseline_path = Path(tmp) / f"{slug}.yaml"
            baseline_path.write_text(base_text, encoding="utf-8", newline="\n")
            _count, base_issues = citations.check_paths([baseline_path], cfg.cache_dir)
        known = {(i.study, i.code, i.message) for i in base_issues}
        rows = _citation_rows(cite_issues)
        for row in rows:
            row["preexisting"] = (row["study"], row["code"], row["message"]) in known
        result["citations"] = rows

    # A C9 issue (the group names no author of the record) is only a warning in `citations check`, but a new one
    # fails the pair here, so a drafter cannot add an author name that the record does not support.
    new_errors = [
        r for r in result["citations"] if not r["preexisting"] and (r["level"] == citations.ERROR or r["code"] == "C9")
    ]
    result["citation_errors"] = len(new_errors)
    result["passed"] = not ops_errors and not result["validator"] and not new_errors
    _write_json(cfg.checks_path(slug, pmid, n), result)
    _log(cfg, {"event": "apply", "card": slug, "paper": result["paper"], "round": n, "passed": result["passed"]})
    return result


# ---------------------------------------------------------------------------
# record-review
# ---------------------------------------------------------------------------


def record_review(cfg: Config, slug: str, pmid: str, n: int) -> ReviewFile:
    path = cfg.review_path(slug, pmid, n)
    raw = _read_json(path)
    try:
        review = ReviewFile.model_validate(raw)
    except ValidationError as exc:
        raise PipelineError(f"{path} is malformed:\n" + "\n".join(_pydantic_lines(exc))) from exc
    problems = []
    if review.card != slug:
        problems.append(f"card is '{review.card}', expected '{slug}'")
    expected = _paper_id_of_key(cfg, pmid)
    if review.paper != expected:
        problems.append(f"paper is '{review.paper}', expected '{expected}'")
    ops_path = cfg.ops_path(slug, pmid, n)
    count: int | None = None
    try:
        count = len(parse_ops(_read_json(ops_path)).operations)
    except (PipelineError, OperationError) as exc:
        problems.append(f"the ops file {ops_path} the review belongs to is not usable: {exc}")
    if count is not None:
        for i, finding in enumerate(review.findings):
            if finding.operation is not None and finding.operation >= count:
                problems.append(
                    f"findings[{i}].operation {finding.operation} is out of range ({count} operation(s), from 0)"
                )
    if problems:
        raise PipelineError(f"{path} is not valid:\n" + "\n".join(problems))
    _log(cfg, {"event": "record-review", "card": slug, "paper": review.paper, "round": n, "verdict": review.verdict})
    return review


# ---------------------------------------------------------------------------
# The audit: audit-plan, record-audit, audit-sample
# ---------------------------------------------------------------------------

_RECORD_HEADING = re.compile(r"^### Record: (\S+)$", re.MULTILINE)


def _last_applied_round(cfg: Config, slug: str, key: str) -> int:
    """The last round of a pair that has an applied result (``applied/<slug>-<key>-r<N>/``)."""
    for n in range(MAX_ROUNDS, 0, -1):
        if (cfg.applied_dir(slug, key, n) / f"{slug}.yaml").is_file():
            return n
    raise PipelineError(f"no applied result for {slug} and {key}; run `apply` first")


def _cached_preprint(cfg: Config, doi: str) -> europepmc.PreprintRecord:
    try:
        record = europepmc.read_cached_preprint(europepmc.EuropePmcCache(cfg.cache_dir), doi)
    except europepmc.EuropePmcError as exc:
        raise PipelineError(str(exc)) from exc
    if record is None:
        raise PipelineError(
            f"no cached Europe PMC preprint record for doi:{doi}; "
            f"cache it with `uv run python -m me_atlas.europepmc preprint {doi}`"
        )
    return record


def _audit_record_lines(cfg: Config, study_id: str, loader: FullTextLoader, budget: int) -> list[str]:
    """One cited record for the audit context: its fields, abstract and (when cached) full text."""
    lines = [f"### Record: {study_id}", ""]
    if study_id.startswith("pmid:"):
        pmid = study_id.removeprefix("pmid:")
        record = _record(cfg, pmid)
        full = loader(pmid, record.pmcid)
        lines += [
            f"- title: {record.title}",
            f"- authors: {', '.join(record.authors) or 'not stated'}",
            f"- journal: {record.journal or 'not stated'}",
            f"- year: {record.year if record.year is not None else 'not stated'}",
            f"- doi: {record.doi or 'not stated'}",
            f"- publication types: {', '.join(record.publication_types) or 'not stated'}",
            f"- retracted: {'yes' if record.retracted else 'no'}",
            "",
            "Abstract:",
            "",
            record.abstract or "(the record has no abstract)",
        ]
    else:
        pre = _cached_preprint(cfg, study_id.removeprefix("doi:"))
        full = loader(pre.ppr_id, pre.pmcid, preprint=pre)
        abstract = " ".join(_TAG_RE.sub(" ", pre.abstract).split()) if pre.abstract else None
        lines += [
            f"- title: {pre.title}",
            f"- authors: {', '.join(pre.authors) or 'not stated'}",
            f"- server: {pre.server or 'not stated'}",
            f"- year: {pre.year if pre.year is not None else 'not stated'}",
            "- preprint: yes (not peer reviewed)",
            "",
            "Abstract:",
            "",
            abstract or "(the record has no abstract)",
        ]
    lines += ["", "Full text:", ""]
    if full.xml is None:
        lines.append(f"No full text is available: {full.note}.")
    else:
        text = europepmc.article_text(full.xml)
        lines.append(f"Source: {full.note}. The reference list is left out.")
        if len(text) > budget:
            lines.append(f"TRUNCATED: the first {budget} of {len(text)} characters follow; the rest was left out.")
        else:
            lines.append(f"Not truncated ({len(text)} characters).")
        lines += ["", text[:budget]]
    lines.append("")
    return lines


def build_audit_context(
    cfg: Config,
    slug: str,
    key: str | None,
    loader: FullTextLoader,
    *,
    budget: int = AUDIT_FULLTEXT_CHAR_BUDGET,
) -> str:
    """The one file the auditor reads: the diff, the card, the cited cached records, the rubric and the card format.

    ``key`` names a change in this run (the diff of its last round); ``None`` is a whole-card audit (the card file
    takes the diff's place). Nothing the drafter or the reviewer wrote, and no earlier audit, is in it.
    """
    base = _base_card(cfg, slug)
    base_card = _load_card(base)
    base_text = base.read_text(encoding="utf-8").rstrip("\n")
    study_ids = [s.id for s in base_card.studies]
    if key is not None:
        paper_id = _paper_id_of_key(cfg, key)
        n = _last_applied_round(cfg, slug, key)
        applied = cfg.applied_dir(slug, key, n)
        diff = (applied / "changes.diff").read_text(encoding="utf-8")
        study_ids += [s.id for s in _load_card(applied / f"{slug}.yaml").studies]
        subject = f"card `{slug}` and the change from paper `{paper_id}` (round {n})"
        change_section = [
            "## 1. The proposed change (the diff of the card)",
            "",
            "```diff",
            diff.rstrip("\n"),
            "```",
        ]
        card_section = [f"## 2. The card as it stands (`{base}`)", "", "```yaml", base_text, "```"]
    else:
        subject = f"the whole card `{slug}`"
        change_section = [
            "## 1. The card to audit (a whole-card audit: the card file is the proposal)",
            "",
            "```yaml",
            base_text,
            "```",
        ]
        card_section = [
            f"## 2. The card as it stands (`{base}`)",
            "",
            "This is a whole-card audit: the card as it stands is the file in section 1.",
        ]
    ids = list(dict.fromkeys(study_ids))
    records: list[str] = []
    for study_id in ids:
        try:
            records += _audit_record_lines(cfg, study_id, loader, budget)
        except PipelineError:
            records += [
                f"### Not cached: {study_id}",
                "",
                "No cached record. It cannot be cited in an audit record, and nothing here can be said about it.",
                "",
            ]
    try:
        card_format = cfg.card_format_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PipelineError(f"cannot read the card format {cfg.card_format_path}: {exc}") from exc
    parts = [
        f"# Audit context: {subject}",
        "",
        "This is everything you may rely on. Cite only the records in section 3, by the id in their heading, and "
        "quote them word for word. Name a rubric clause by copying text from sections 4 or 5.",
        "",
        *change_section,
        "",
        *card_section,
        "",
        "## 3. Cited records",
        "",
        *(records or ["The card cites no study.", ""]),
        "## 4. The inclusion rule (functional spec section 2)",
        "",
        _demote_headings(spec_section(cfg.spec_path, 2)),
        "",
        "## 5. The rubric (functional spec section 3)",
        "",
        _demote_headings(spec_section(cfg.spec_path, 3)),
        "",
        "## 6. The card format (docs/card-format.md)",
        "",
        _demote_headings(_demote_headings(card_format.strip())),
        "",
    ]
    return "\n".join(parts)


def _context_record_ids(context: str) -> set[str]:
    """The ids of the records in section 3 of an audit context file."""
    start = context.find("\n## 3. Cited records")
    end = context.find("\n## 4. ", start)
    if start < 0 or end < 0:
        return set()
    return {m.group(1).lower() for m in _RECORD_HEADING.finditer(context[start:end])}


def _record_quote_text(reader: citations.CacheReader, study_id: str) -> str | None:
    """Title, abstract and cached full text of a study, for the verbatim quote check; None if no cached record."""
    pieces: list[str] = []
    if study_id.startswith("pmid:"):
        record = reader.record(study_id.removeprefix("pmid:"))
        if isinstance(record, str):
            return None
        pieces += [record.title, record.abstract or ""]
        full = reader.fulltext(record.pmid)
    else:
        try:
            pre = reader.preprint(study_id)
        except europepmc.EuropePmcError:
            return None
        if pre is None:
            return None
        pieces += [pre.title, _TAG_RE.sub(" ", pre.abstract) if pre.abstract else ""]
        full = reader.preprint_fulltext(pre)
    if isinstance(full, str):
        pieces.append(full)
    return "\n".join(pieces)


def _proposed_level(cfg: Config, slug: str, key: str | None) -> int:
    """The level an accept_lower must be below: the level in the last applied result of a change, or the card's own."""
    path = (
        cfg.applied_dir(slug, key, _last_applied_round(cfg, slug, key)) / f"{slug}.yaml"
        if key is not None
        else _base_card(cfg, slug)
    )
    return _load_card(path).level


def validate_audit_record(
    cfg: Config, raw: Any, *, slug: str, key: str | None, source: Path, context_path: Path
) -> AuditRecord:
    """Check an audit record against its context file and the cache; raise PipelineError listing every problem.

    Checked: the schema; the card and paper are the ones audited; ``accepted_level`` is below the proposed (or
    current) level; every evidence ``source`` is a record in the context file and every ``quote`` is found word for
    word (the narrow normalisation of the citation check) in that record's cached text; every part's ``rubric`` is
    a verbatim excerpt (at least ``MIN_RUBRIC_CHARS`` characters) of functional spec section 2 or 3.
    """
    try:
        record = AuditRecord.model_validate(raw)
    except ValidationError as exc:
        raise PipelineError(f"{source} is malformed:\n" + "\n".join(_pydantic_lines(exc))) from exc
    try:
        context = context_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PipelineError(
            f"no audit context file {context_path}; run `audit-plan` first ({exc.__class__.__name__})"
        ) from exc
    problems: list[str] = []
    if record.card != slug:
        problems.append(f"card is '{record.card}', expected '{slug}'")
    expected_paper = _paper_id_of_key(cfg, key) if key is not None else None
    if record.paper != expected_paper:
        problems.append(
            f"paper is {record.paper!r}, expected "
            + (f"'{expected_paper}'" if expected_paper else "no paper (a whole-card audit)")
        )
    if record.decision == "accept_lower":
        ceiling = _proposed_level(cfg, slug, key)
        if record.accepted_level is not None and record.accepted_level >= ceiling:
            problems.append(f"accepted_level {record.accepted_level} must be lower than the level {ceiling}")
    cited = _context_record_ids(context)
    reader = citations.CacheReader(cfg.cache_dir)
    texts: dict[str, str | None] = {}
    rubric_texts = [citations.normalise_quote(spec_section(cfg.spec_path, n)) for n in (2, 3)]
    for i, part in enumerate(record.parts):
        rubric = citations.normalise_quote(part.rubric)
        if len(rubric) < MIN_RUBRIC_CHARS:
            problems.append(f"parts[{i}].rubric is shorter than {MIN_RUBRIC_CHARS} characters")
        elif not any(rubric in text for text in rubric_texts):
            problems.append(
                f"parts[{i}].rubric is not found word for word in functional spec section 2 or 3: {part.rubric!r}"
            )
        for j, ev in enumerate(part.evidence):
            where = f"parts[{i}].evidence[{j}]"
            if ev.source.lower() not in cited:
                problems.append(f"{where}.source {ev.source} is not a record in the context file {context_path.name}")
                continue
            if ev.source not in texts:
                texts[ev.source] = _record_quote_text(reader, ev.source)
            text = texts[ev.source]
            if text is None:
                problems.append(f"{where}: no cached record for {ev.source} to check the quote against")
            elif citations.normalise_quote(ev.quote) not in citations.normalise_quote(text):
                problems.append(f"{where}.quote is not found word for word in the cached record of {ev.source}")
    if problems:
        raise PipelineError(f"{source} is not valid:\n" + "\n".join(problems))
    return record


def load_audit(cfg: Config, slug: str, key: str, *, second: bool = False) -> tuple[AuditRecord | None, str | None]:
    """The valid audit record of a change, or (None, why it is missing or invalid)."""
    path = cfg.audit_path(slug, key, second)
    if not path.is_file():
        return None, f"no audit record {path.name}"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        record = validate_audit_record(
            cfg, raw, slug=slug, key=key, source=path, context_path=cfg.audit_context_path(slug, key)
        )
    except yaml.YAMLError as exc:
        return None, f"{path.name} is not valid YAML: {str(exc).splitlines()[0]}"
    except PipelineError as exc:
        return None, str(exc).replace("\n", "; ")
    return record, None


def record_audit(
    cfg: Config,
    slug: str,
    key: str | None,
    *,
    second: bool = False,
    file: Path | None = None,
    out_dir: Path | None = None,
) -> AuditRecord:
    """Validate the record the auditor wrote and log it. A change is ``slug`` and ``key`` (the file is
    ``audit/<slug>-<key>.yaml``, or ``...-second.yaml``); a whole card is ``slug`` with ``key`` None and ``file``."""
    if key is not None:
        path = file or cfg.audit_path(slug, key, second)
        context_path = cfg.audit_context_path(slug, key)
    else:
        if file is None:
            raise PipelineError("a whole-card audit needs --file PATH (the record the auditor wrote)")
        path = file
        context_path = (out_dir or cfg.run_dir) / "audit-context" / f"{slug}.md"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PipelineError(f"{path} does not exist") from exc
    except (OSError, yaml.YAMLError) as exc:
        raise PipelineError(f"{path} is not readable YAML: {exc}") from exc
    record = validate_audit_record(cfg, raw, slug=slug, key=key, source=path, context_path=context_path)
    if key is not None:
        _log(
            cfg,
            {
                "event": "record-audit",
                "card": slug,
                "paper": record.paper,
                "second": second,
                "decision": record.decision,
            },
        )
    return record


def _is_level_change(ops: OpsFile) -> bool:
    return any(isinstance(op, Propose) and op.target == "level" for op in ops.operations)


def audit_eligible(cfg: Config, outcomes: Sequence[Outcome]) -> list[Outcome]:
    """Contract decision D1: the pairs that go to the auditor, sorted by card and paper."""
    return sorted(
        (o for o in outcomes if o.status == "accepted" and o.audit_required),
        key=lambda o: (o.slug, _ledger_order(o.pmid)),
    )


def audit_sample(cfg: Config, seed: str | None = None) -> dict[str, Any]:
    """Which audited pairs need a second audit; written to ``audit-sample.json``.

    Every pair with a ``propose`` on ``level``, plus one in five of the others (rounded up when there are any),
    chosen with ``random.Random(seed)``. The seed is the run date unless given (decision D6).
    """
    if seed is None:
        seed = str(_read_json(cfg.f("prepare.json"))["date"])
    eligible = audit_eligible(cfg, collect_outcomes(cfg, gate=False))
    level = [o for o in eligible if o.last is not None and o.last.ops is not None and _is_level_change(o.last.ops)]
    others = [o for o in eligible if o not in level]
    picked = random.Random(seed).sample(others, math.ceil(len(others) / 5)) if others else []
    chosen = sorted(
        [(o, "level_change") for o in level] + [(o, "one_in_five") for o in picked],
        key=lambda pair: (pair[0].slug, _ledger_order(pair[0].pmid)),
    )
    result = {
        "seed": seed,
        "audited": len(eligible),
        "pairs": [{"card": o.slug, "key": o.pmid, "paper": o.paper_id, "why": why} for o, why in chosen],
    }
    _write_json(cfg.f("audit-sample.json"), result)
    _log(cfg, {"event": "audit-sample", "seed": seed, "audited": len(eligible), "sampled": len(chosen)})
    return result


def _sampled_keys(cfg: Config) -> set[tuple[str, str]]:
    path = cfg.f("audit-sample.json")
    if not path.is_file():
        return set()
    try:
        return {(p["card"], p["key"]) for p in _read_json(path).get("pairs", [])}
    except (PipelineError, KeyError, TypeError, AttributeError):
        return set()


def _differs(first: AuditRecord, second: AuditRecord) -> bool:
    return (first.decision, first.accepted_level) != (second.decision, second.accepted_level)


def _gate(cfg: Config, o: Outcome, sampled: set[tuple[str, str]]) -> None:
    """Set the audit state of a pair the reviewer accepted and that needs an audit (D1, D2, D3).

    The pair is applied only when a valid first record says ``accept`` and, when the pair is in the consistency
    sample (or changes a level, which is always sampled), a valid second record also says ``accept``.
    """
    assert o.last is not None and o.last.ops is not None
    o.sampled = (o.slug, o.pmid) in sampled or _is_level_change(o.last.ops)
    o.audit, why = load_audit(cfg, o.slug, o.pmid)
    if o.audit is None:
        o.audit_state, o.audit_note = "missing", f"no valid audit record: {why}"
        return
    if o.sampled:
        o.second, why2 = load_audit(cfg, o.slug, o.pmid, second=True)
        if o.second is not None:
            o.second_differs = _differs(o.audit, o.second)
    if o.audit.decision == "reject":
        o.audit_state = "rejected"
    elif o.audit.decision == "accept_lower":
        o.audit_state = "lower"
    elif o.sampled and o.second is None:
        o.audit_state, o.audit_note = "missing", f"the consistency check needs a valid second audit: {why2}"
    elif o.second_differs:
        o.audit_state = "differs"
    else:
        o.audit_state = "accepted"


# ---------------------------------------------------------------------------
# Outcomes and the report
# ---------------------------------------------------------------------------


@dataclass
class Round:
    n: int
    ops: OpsFile | None
    ops_problem: str | None
    checks: dict[str, Any] | None
    review: ReviewFile | None


@dataclass
class Outcome:
    slug: str
    pmid: str  # the paper key: a PMID, or the PPR id of a DOI-only preprint
    status: Literal["accepted", "no_change", "withdrawn", "parked", "skipped"]
    note: str
    rounds: list[Round] = field(default_factory=list)
    paper_id: str = ""  # "pmid:<digits>" or "doi:<doi>"
    # The audit gate (decision D1): a pair the reviewer accepted that has a tier 2 operation needs the auditor.
    audit_required: bool = False
    audit: AuditRecord | None = None
    second: AuditRecord | None = None  # the consistency run, when the pair is sampled
    sampled: bool = False
    second_differs: bool = False
    audit_state: Literal["not_required", "accepted", "rejected", "lower", "missing", "differs"] = "not_required"
    audit_note: str = ""

    @property
    def last(self) -> Round | None:
        return self.rounds[-1] if self.rounds else None

    @property
    def applied(self) -> bool:
        """Whether the pair's operations are applied: reviewer accepted, and the audit gate (if any) passed."""
        return self.status == "accepted" and self.audit_state in ("not_required", "accepted")


def _load_round(cfg: Config, slug: str, pmid: str, n: int) -> Round | None:
    ops_path = cfg.ops_path(slug, pmid, n)
    if not ops_path.exists():
        return None
    ops: OpsFile | None = None
    problem: str | None = None
    try:
        ops = parse_ops(_read_json(ops_path))
    except (PipelineError, OperationError) as exc:
        problem = str(exc)
    checks = _read_json(cfg.checks_path(slug, pmid, n)) if cfg.checks_path(slug, pmid, n).exists() else None
    review = None
    if cfg.review_path(slug, pmid, n).exists():
        try:
            review = ReviewFile.model_validate(_read_json(cfg.review_path(slug, pmid, n)))
        except (PipelineError, ValidationError):
            review = None
    return Round(n, ops, problem, checks, review)


def collect_outcomes(cfg: Config, *, gate: bool = True) -> list[Outcome]:
    """One outcome per (card, paper) pair of ``matches.json``.

    With ``gate`` (the default) a pair that needs an audit is applied only when its audit records say ``accept``
    (``Outcome.applied``); ``gate=False`` leaves the audit state alone, which ``audit-sample`` uses to find the
    pairs that need one.
    """
    matches = _read_json(cfg.f("matches.json"))["matches"] if cfg.f("matches.json").exists() else []
    outcomes = []
    for match in matches:
        slug = match["slug"]
        if "pmid" in match:
            pmid, paper_id = match["pmid"], f"pmid:{match['pmid']}"
        else:  # a DOI-only preprint: its file-name key is the PPR id from papers.json
            pmid, paper_id = resolve_paper(cfg, match["id"])
        rounds = [r for n in range(1, MAX_ROUNDS + 1) if (r := _load_round(cfg, slug, pmid, n))]
        outcome = Outcome(slug, pmid, "skipped", "", rounds, paper_id)
        last = outcome.last
        rejected_before = any(r.review and r.review.verdict == "reject" for r in rounds)
        if last is None:
            outcome.note = "no operations file: the drafter did not write one"
        elif last.ops is None or last.checks is None or not last.checks.get("passed"):
            if last.ops is None:
                why = f"the operations file is invalid: {last.ops_problem}"
            elif last.checks is None:
                why = "the operations were never applied (no check result)"
            else:
                why = "the mechanical checks failed: " + _check_failure_summary(last.checks)
            outcome.status = "parked" if rejected_before else "skipped"
            outcome.note = why
        elif not last.ops.operations:
            earlier = [r for r in rounds[:-1] if r.review and r.review.verdict == "reject"]
            if earlier:
                outcome.status = "withdrawn"
                outcome.note = (
                    f"the reviewer rejected the change in round {earlier[-1].n}; "
                    f"the drafter then proposed no change in round {last.n}"
                )
            else:
                outcome.status, outcome.note = "no_change", "the drafter proposed no change"
        elif last.review is None:
            outcome.status = "parked" if rejected_before else "skipped"
            outcome.note = "no review was recorded"
        elif last.review.verdict == "accept":
            outcome.status, outcome.note = "accepted", f"accepted in round {last.n}"
        else:
            outcome.status = "parked"
            outcome.note = (
                f"rejected in round {last.n}"
                if last.n == MAX_ROUNDS
                else f"rejected in round {last.n}; no second attempt was recorded"
            )
        outcomes.append(outcome)
    sampled = _sampled_keys(cfg)
    for o in outcomes:
        if o.status == "accepted":
            assert o.last is not None and o.last.ops is not None
            base = yaml.safe_load(_base_card(cfg, o.slug).read_text(encoding="utf-8"))
            o.audit_required = 2 in tiers(o.last.ops, base if isinstance(base, dict) else None)
            if o.audit_required and gate:
                _gate(cfg, o, sampled)
    _park_conflicts(outcomes)
    return outcomes


def _targets(ops: OpsFile) -> set[tuple[Any, ...]]:
    """What an accepted operation file overwrites: a replaced paragraph or a proposed setting."""
    found: set[tuple[Any, ...]] = set()
    for op in ops.operations:
        if isinstance(op, ReplaceParagraph):
            found.add(("replace_paragraph", op.field, op.index))
        elif isinstance(op, Propose):
            found.add(("propose", op.target))
    return found


def _park_conflicts(outcomes: list[Outcome]) -> None:
    """Two accepted papers on one card that overwrite the same target: neither is applied; both are parked."""
    accepted = [o for o in outcomes if o.applied and o.last is not None and o.last.ops is not None]
    for o in accepted:
        others = [
            (p, t)
            for p in accepted
            if p is not o and p.slug == o.slug
            for t in sorted(_targets(o.last.ops) & _targets(p.last.ops), key=str)  # type: ignore[union-attr]
        ]
        if others:
            o.status = "conflict"  # type: ignore[assignment]
            o.note = "conflicts with " + "; ".join(f"{p.paper_id} on {' '.join(map(str, t))}" for p, t in others)
    for o in outcomes:
        if o.status == "conflict":
            o.status = "parked"
            o.note = "not applied, " + o.note


def _check_failure_summary(checks: dict[str, Any]) -> str:
    bits = list(checks.get("ops_errors", [])) + list(checks.get("validator", []))
    bits += [
        f"{r['study']} {r['code']}: {r['message']}"
        for r in checks.get("citations", [])
        if (r["level"] == "ERROR" or r.get("code") == "C9") and not r.get("preexisting")
    ]
    return "; ".join(b.replace("\n", " ") for b in bits) or "unknown"


def describe_op(op: Any, base: dict[str, Any]) -> str:
    if isinstance(op, AddStudy):
        s = op.study
        return (
            f"Add study `{s.id}` ({s.case_definition}, {s.design}, role {s.role}, n={s.n_patients}/{s.n_controls}): "
            f"{s.finding}"
        )
    if isinstance(op, AddParagraph):
        return f"Add a paragraph to `{op.field}` (sources {', '.join(op.sources)}): {op.text}"
    if isinstance(op, ReplaceParagraph):
        return f"Replace paragraph {op.index} of `{op.field}` (sources {', '.join(op.sources)}): {op.text}"
    assert isinstance(op, Propose)
    paragraphs = " ".join(f"{p.text} [{', '.join(p.sources)}]" for p in op.reason or [])
    if op.target == "level":
        head = f"Propose level {base.get('level')} -> {op.value}"
    elif op.target == "contested":
        head = (
            "Propose removing the contested mark"
            if op.value is None
            else f"Propose a contested mark on rungs {op.value}"
        )
    else:
        old = base.get("badges", {}).get(op.target, {}).get("value")
        head = f"Propose badge `{op.target}`: {old} -> {op.value}"
    return f"{head}. {paragraphs}".strip()


def _paper_line(cfg: Config, pmid: str) -> str:
    try:
        title = pubmed.RawCache(cfg.cache_dir).read_record(pmid).title
    except (FileNotFoundError, pubmed.ParseError):
        title = "(title not in the cache)"
    return f"[pmid:{pmid}](https://pubmed.ncbi.nlm.nih.gov/{pmid}/) {title}"


def _outcome_line(cfg: Config, o: Outcome) -> str:
    """The paper of a (card, paper) pair for the report: a PubMed link, or for a DOI-only preprint a link to
    ``https://doi.org/<doi>`` with the title from the cached Europe PMC record."""
    if o.pmid.isdigit():
        return _paper_line(cfg, o.pmid)
    doi = o.paper_id.removeprefix("doi:")
    try:
        record = europepmc.read_cached_preprint(europepmc.EuropePmcCache(cfg.cache_dir), doi)
    except europepmc.EuropePmcError:
        record = None
    paper = next((p for p in _run_papers(cfg) if p.get("ppr_id") == o.pmid), None)
    title = record.title if record else (paper["title"] if paper else "(title not in the cache)")
    return f"[{o.paper_id}](https://doi.org/{doi}) {title} (preprint, not peer reviewed)"


def _ref_line(cfg: Config, ref: dict[str, Any], papers: Sequence[dict[str, Any]]) -> str:
    """A report line for a paper named by ``{"pmid": ...}`` (PubMed) or ``{"id": "doi:..."}`` (a preprint)."""
    if "pmid" in ref:
        return _paper_line(cfg, ref["pmid"])
    paper = next((p for p in papers if p["id"] == ref["id"]), None)
    doi = ref["id"].removeprefix("doi:")
    title = paper["title"] if paper else "(title not in papers.json)"
    return f"[{ref['id']}](https://doi.org/{doi}) {title} (preprint, not peer reviewed)"


def _preexisting_problems(cfg: Config) -> list[tuple[str, str, str, str]]:
    """Citation errors that were already on a card, from every check result of this run, once each."""
    found: dict[tuple[str, str, str, str], None] = {}
    folder = cfg.f("checks")
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        checks = _read_json(path)
        for row in checks.get("citations", []):
            if row["level"] == citations.ERROR and row.get("preexisting"):
                found[(checks["card"], row["study"], row["code"], row["message"])] = None
    return list(found)


def _cell(text: object) -> str:
    return str(text).replace("|", "/").replace(chr(10), " ")


def _rejection_lines(o: Outcome) -> list[str]:
    """Report lines for the rejecting reviews of a pair: the reviewer's reason for "not on the card", then every
    finding with its severity (must_fix first), problem and suggested fix in full."""
    lines: list[str] = []
    rejecting = [r for r in o.rounds if r.review and r.review.verdict == "reject"]
    reasons = [r.review.not_on_card for r in rejecting if r.review and r.review.not_on_card]
    if reasons:
        lines.append(f"  - not on the card: {reasons[-1]}")
    for r in rejecting:
        assert r.review is not None
        for f in by_severity(r.review.findings):
            where = "card" if f.operation is None else f"operation {f.operation}"
            fix = f" Suggested fix: {f.fix}" if f.fix else ""
            lines.append(f"  - round {r.n}, {where} ({f.severity}): {f.problem}{fix}")
    return lines


def _window_text(prep: dict[str, Any]) -> str:
    if prep.get("mode") == "ids":
        return "the papers given by id (not a fetch window)"
    if prep.get("since"):
        return f"the fetch window since {prep['since']}"
    return "the weekly fetch window (the last 14 days)"


def _preprint_intro(prep: dict[str, Any]) -> list[str]:
    counts = (prep.get("preprints") or {}).get("counts")
    rule = (
        "A preprint can only be an early signal, and any change that adds or cites one is tier 2 (the auditor decides)."
    )
    if (prep.get("preprints") or {}).get("searched") is False:
        return ["", f"Preprints (Europe PMC): no preprint search was made (the papers were given by id). {rule}"]
    if not counts:
        return []
    dropped = ", ".join(f"{n} {reason}" for reason, n in counts["dropped"].items() if n) or "none dropped"
    return [
        "",
        f"Preprints (Europe PMC): {counts['found']} found, {counts['offered']} offered to the classifier "
        f"({dropped}). {rule}",
    ]


def _audit_section(cfg: Config, outcomes: Sequence[Outcome]) -> list[str]:
    """The report sections "Auditor decisions" and "Disputes (card unchanged)" (spec section 6)."""
    needing = audit_eligible(cfg, outcomes)
    audited = [o for o in needing if o.audit is not None]
    lines = ["## Auditor decisions", ""]
    if not needing:
        lines.append("None. No change in this run needed an audit.")
    for o in needing:
        who = f"**{o.slug}**, from {_outcome_line(cfg, o)}"
        if o.audit is None:
            lines.append(f"- {who}: not applied, no valid audit record ({o.audit_note})")
            continue
        extra = f" (accepted level: {o.audit.accepted_level})" if o.audit.decision == "accept_lower" else ""
        second = ""
        if o.second is not None:
            second = f"; second audit: {o.second.decision}" + (" (differs)" if o.second_differs else "")
        elif o.sampled:
            second = "; second audit: " + (f"not valid ({o.audit_note})" if o.audit_note else "none recorded")
        lines.append(f"- {who}: {o.audit.decision}{extra}: {o.audit.reasons_summary}{second}")
    if audited:
        sampled = [o for o in audited if o.sampled]
        second_done = [o for o in sampled if o.second is not None]
        differed = [o for o in second_done if o.second_differs]
        lines += [
            "",
            f"Consistency check: {len(second_done)} of {len(sampled)} sampled decisions decided a second time; "
            f"{len(differed)} differed.",
        ]
    lines += ["", "## Disputes (card unchanged)", ""]
    disputes: list[str] = []
    for o in outcomes:
        if o.status == "parked":
            disputes.append(f"- **{o.slug}**, from {_outcome_line(cfg, o)}: parked ({o.note}); see the parking lot")
    for o in audited:
        assert o.audit is not None
        who = f"**{o.slug}**, from {_outcome_line(cfg, o)}"
        if o.audit_state == "rejected":
            disputes.append(f"- {who}: the auditor rejected the change: {o.audit.reasons_summary}")
        elif o.audit_state == "lower":
            disputes.append(
                f"- {who}: the auditor accepts level {o.audit.accepted_level} only, so nothing is applied: "
                f"{o.audit.reasons_summary}"
            )
        elif o.audit_state == "differs" and o.second is not None:
            disputes.append(f"- {who}: the second audit decided {o.second.decision}, the first accept: not applied")
        if o.second_differs and o.audit_state in ("rejected", "lower") and o.second is not None:
            disputes.append(
                f"- {who}: the second audit decided {o.second.decision}, a different verdict from the first"
            )
    lines += disputes or ["None."]
    return lines


def build_report(cfg: Config) -> str:
    prep = _read_json(cfg.f("prepare.json"))
    papers = _read_json(cfg.f("papers.json"))
    classify = _read_json(cfg.f("matches.json")) if cfg.f("matches.json").exists() else None
    classified = _read_json(cfg.f("classify.json")) if cfg.f("classify.json").exists() else {"papers": []}
    outcomes = collect_outcomes(cfg)
    by_status = {
        s: [o for o in outcomes if o.status == s] for s in ("accepted", "no_change", "withdrawn", "parked", "skipped")
    }

    def base_data(slug: str) -> dict[str, Any]:
        return yaml.safe_load(_base_card(cfg, slug).read_text(encoding="utf-8"))

    tier2: list[str] = []
    tier1: list[str] = []
    for o in by_status["accepted"]:
        if not o.applied:
            continue  # held back by the audit: listed under "Auditor decisions" and "Disputes"
        last = o.last
        assert last is not None and last.ops is not None and last.review is not None
        base = base_data(o.slug)
        notes = [f"review: accept (round {last.n})"]
        if o.audit is not None:
            notes.append(f"audit: {o.audit.decision}")
        warnings = sum(1 for r in (last.checks or {}).get("citations", []) if r["level"] == citations.WARNING)
        if warnings:
            notes.append(f"{warnings} citation-check warning(s), see checks/")
        notes += [f"warning: {w}" for w in (last.checks or {}).get("warnings", [])]
        for f in by_severity(last.review.findings):
            where = "the card" if f.operation is None else f"operation {f.operation}"
            notes.append(f"reviewer note ({f.severity}) on {where}: {f.problem}")
        touched: list[list[str]] = []
        op_tiers = tiers(last.ops, base)
        for op, op_tier in zip(last.ops.operations, op_tiers, strict=True):
            target = tier2 if op_tier == 2 else tier1
            target.append(f"- **{o.slug}**, from {_outcome_line(cfg, o)}: {describe_op(op, base)}")
            if not any(target is t for t in touched):
                touched.append(target)
        for target in touched:
            target.append("  - " + "; ".join(notes))

    lines = [
        f"# Weekly pipeline report {prep['date']}",
        "",
        f"{prep['selected']} paper(s) selected from {_window_text(prep)} "
        f"({prep['skipped_processed']} skipped as already processed by an earlier run). "
        f"Proposed changes: {len(by_status['accepted'])} accepted by the reviewer "
        f"({sum(o.applied for o in by_status['accepted'])} applied after the audit gate), "
        f"{len(by_status['parked'])} parked, "
        f"{len(by_status['skipped'])} skipped, {len(by_status['withdrawn'])} rejected and then withdrawn by the "
        f"drafter, {len(by_status['no_change'])} with no change proposed.",
        *_preprint_intro(prep),
        "",
        "Changes applied by the pipeline: the mechanical checks passed, the review agent accepted, and every tier 2 "
        "change was accepted by the auditor (functional spec section 6). A dispute leaves the card unchanged. "
        "The founder merges this pull request as an operational step (trial period: four weekly runs, the "
        "decisions read after the fact).",
        "",
        "## Proposed changes",
        "",
        "### Tier 2: decided by the auditor (level, contested mark, badge, layer, link, anything about a preprint)",
        "",
        *(tier2 or ["None."]),
        "",
        "### Tier 1: factual additions (applied on the checks and the review)",
        "",
        *(tier1 or ["None."]),
        "",
        *_audit_section(cfg, outcomes),
        "",
        "## Parking lot",
        "",
    ]
    if by_status["parked"]:
        lines.append(
            "Changes the reviewer still rejected after two rounds, or that never passed. Not applied, and not "
            "sent to the auditor. The card is unchanged."
        )
        lines.append("")
        for o in by_status["parked"]:
            lines.append(f"- **{o.slug}**, from {_outcome_line(cfg, o)}: {o.note}")
            lines += _rejection_lines(o)
            last = o.last
            if last is not None and last.ops is not None:
                base = base_data(o.slug)
                for op in last.ops.operations:
                    lines.append(f"  - proposed (round {last.n}): {describe_op(op, base)}")
    else:
        lines.append("None.")
    lines += ["", "## Rejected by the reviewer, then withdrawn", ""]
    if by_status["withdrawn"]:
        lines.append(
            "The reviewer rejected the change, and the drafter then proposed nothing. Nothing is applied. "
            "The reviewer's findings and what the drafter proposed are kept here so a reader can see why."
        )
        lines.append("")
        for o in by_status["withdrawn"]:
            lines.append(f"- **{o.slug}**, from {_outcome_line(cfg, o)}: {o.note}")
            lines += _rejection_lines(o)
            base = base_data(o.slug)
            for r in o.rounds[:-1]:
                if r.review and r.review.verdict == "reject" and r.ops is not None:
                    lines += [f"  - proposed (round {r.n}): {describe_op(op, base)}" for op in r.ops.operations]
    else:
        lines.append("None.")
    lines += ["", "## Possible new hypotheses", ""]
    hyp = classify["new_hypotheses"] if classify else []
    if hyp:
        lines.append("No card is drafted for these. They are listed only; no step drafts a card for them.")
        lines.append("")
        lines += [f"- {_ref_line(cfg, h, papers)}: {h['hypothesis']} ({h['reason']})" for h in hyp]
    else:
        lines.append("None.")
    lines += ["", "## Preprints on cards with a published version", ""]
    published = prep.get("preprints_published", [])
    if published:
        lines.append(
            "A study marked `preprint: true` whose Europe PMC record links to a published article. Nothing is "
            "proposed; whether the published paper replaces the preprint is not decided here."
        )
        lines.append("")
        lines += [
            f"- **{row['card']}**, {row['study']}: published as [pmid:{row['pmid']}]"
            f"(https://pubmed.ncbi.nlm.nih.gov/{row['pmid']}/)" + (f" ({row['note']})" if row.get("note") else "")
            for row in published
        ]
    else:
        lines.append("None.")
    lines += _translation_section(cfg)
    lines += ["", "## Retracted papers cited on cards", ""]
    retractions = prep["retractions_on_cards"]
    if retractions:
        lines += [
            f"- [pmid:{r['pmid']}](https://pubmed.ncbi.nlm.nih.gov/{r['pmid']}/) {r['title'] or ''} "
            f"is newly marked retracted and is cited on: {', '.join(r['cards'])}. "
            "The level of each card must be re-assessed."
            for r in retractions
        ]
    else:
        lines.append("None.")
    lines += ["", "## Skipped", ""]
    skipped = [f"- **{o.slug}**, {_outcome_line(cfg, o)}: {o.note}" for o in by_status["skipped"]]
    skipped += [
        f"- {_ref_line(cfg, s, papers)}: stopped, {s['why']}" for s in (classify["stopped"] if classify else [])
    ]
    skipped += [f"- {_paper_line(cfg, p)}: retracted, not classified" for p in prep["excluded_retracted"]]
    skipped += [f"- pmid:{p}: the cached record could not be read" for p in prep["unreadable_records"]]
    lines += skipped or ["None."]
    lines += ["", "## Pre-existing problems on cards", ""]
    old = _preexisting_problems(cfg)
    if old:
        lines.append(
            "Citation-check errors the cards already had. They do not block a new paper, but they are not fixed."
        )
        lines.append("")
        lines += [f"- **{slug}**, {study}: {code}: {message}" for slug, study, code, message in old]
    else:
        lines.append("None.")
    lines += ["", "## New papers and how each was classified", ""]
    if classified["papers"]:
        lines += ["| Paper | Type | Cards | Reason |", "| --- | --- | --- | --- |"]
        titles = {p["pmid"] or p["id"]: p["title"] for p in papers}
        for item in classified["papers"]:
            key = item.get("pmid") or item["id"]
            label = f"pmid:{key}" if item.get("pmid") else key
            lines.append(
                f"| {label} {_cell(titles.get(key, ''))} | {item['article_type']} | "
                f"{', '.join(item['cards']) or '-'} | {_cell(item['reason'])} |"
            )
    else:
        lines.append("None classified.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# translation-plan
# ---------------------------------------------------------------------------


def translation_plan(cfg: Config, lang: str = "nb") -> dict[str, Any]:
    """Which translated items the accepted changes of this run made stale, and what the translator has to do.

    For every card with an accepted change that already has a translation file, compares the file with the card as it
    will be after the change (written to ``final/<slug>.yaml``) and lists the items to translate in
    ``translate/<slug>.json``: items made stale, items the change added, and any that were already stale, missing or
    invalid. A card with no translation file is listed but not planned: its first translation is a manual run.
    Nothing here calls an AI.
    """
    texts = final_card_texts(cfg, collect_outcomes(cfg))
    sidecars, problems = translations.load_language(cfg.translations_dir, lang)
    if problems:
        raise PipelineError("a translation file cannot be read:\n" + "\n".join(problems))
    plan: dict[str, Any] = {"lang": lang, "cards": [], "untranslated_cards": []}
    for slug, text in sorted(texts.items()):
        final_path = cfg.f("final", f"{slug}.yaml")
        _write_text(final_path, text)
        sidecar = sidecars.get(slug)
        if sidecar is None:
            plan["untranslated_cards"].append(slug)
            continue
        before = translations.check_card(_load_card(_base_card(cfg, slug)), sidecar, lang)
        after_card = _load_card(final_path)
        after = translations.check_card(after_card, sidecar, lang)
        english = translations.english_items(after_card)
        items = []
        for locator, result in after.items.items():
            if result.status == "fresh":
                continue
            was = before.items.get(locator)
            if was is None:
                reason = "new"  # the change added this item
            elif was.status == "fresh":
                reason = "made_stale"
            else:
                reason = f"already_{result.status}"
            previous = sidecar.items.get(locator)
            items.append(
                {
                    "item": locator,
                    "reason": reason,
                    "english": english[locator].text,
                    "sources": english[locator].sources,
                    "previous_translation": previous.text if previous else None,
                }
            )
        plan["cards"].append({"slug": slug, "file": str(final_path), "items": items})
        _write_json(
            cfg.f("translate", f"{slug}.json"), {"slug": slug, "lang": lang, "card": str(final_path), "items": items}
        )
    _write_json(cfg.f("translation-plan.json"), plan)
    _log(cfg, {"event": "translation-plan", "lang": lang, "cards": len(plan["cards"])})
    return plan


def _translation_section(cfg: Config) -> list[str]:
    """Report lines for the translation plan of this run, or none if the plan step was not run."""
    path = cfg.f("translation-plan.json")
    if not path.exists():
        return []
    plan = _read_json(path)
    lines = ["", f"## Translations ({plan['lang']})", ""]
    if not plan["cards"] and not plan["untranslated_cards"]:
        return [*lines, "None."]
    for entry in plan["cards"]:
        made_stale = [i["item"] for i in entry["items"] if i["reason"] == "made_stale"]
        added = [i["item"] for i in entry["items"] if i["reason"] == "new"]
        other = len(entry["items"]) - len(made_stale) - len(added)
        lines.append(
            f"- **{entry['slug']}**: {len(entry['items'])} item(s) to translate; made stale by accepted changes: "
            f"{', '.join(made_stale) or 'none'}; added by accepted changes: {', '.join(added) or 'none'}; "
            f"already stale or missing: {other}."
        )
    if plan["untranslated_cards"]:
        lines.append(
            "- Not translated yet (the first translation of a card is a manual run): "
            + ", ".join(plan["untranslated_cards"])
            + "."
        )
    return lines


# ---------------------------------------------------------------------------
# pr
# ---------------------------------------------------------------------------

Runner = Callable[[Sequence[str]], tuple[int, str]]


def subprocess_runner(cmd: Sequence[str]) -> tuple[int, str]:
    done = subprocess.run(list(cmd), capture_output=True, text=True, check=False)
    return done.returncode, (done.stdout + done.stderr).strip()


_LAST_CHECKED_BLOCK = re.compile(r"^last_checked:[ \t]*\n((?:[ \t]+\S[^\n]*(?:\n|$))+)", re.MULTILINE)


def _set_last_checked(text: str, date: str, by: str) -> str:
    """Set ``last_checked`` (block style, as every card writes it) to ``date`` and ``by``, leaving other lines alone."""
    match = _LAST_CHECKED_BLOCK.search(text)
    if match is None:
        raise PipelineError("the card has no block-style last_checked to update")
    block = match.group(1)
    new, n_date = re.subn(r"^([ \t]+date:)[^\n]*", rf"\g<1> {date}", block, flags=re.MULTILINE)
    new, n_by = re.subn(r"^([ \t]+by:)[^\n]*", rf"\g<1> {by}", new, flags=re.MULTILINE)
    if n_date != 1 or n_by != 1:
        raise PipelineError("last_checked must have one date and one by line")
    return text[: match.start(1)] + new + text[match.end(1) :]


def _target_in_cards(cfg: Config, slug: str) -> bool:
    """Whether the card file the pipeline works on (and writes) is in ``cards/`` rather than ``drafts/``."""
    return cards.in_directory(_base_card(cfg, slug), cfg.cards_dir)


def final_card_texts(cfg: Config, outcomes: Sequence[Outcome]) -> dict[str, str]:
    """The text of each card after all its applied operation files, applied in order of paper.

    A pair is applied when the reviewer accepted it and, if it has a tier 2 operation, the audit gate passed
    (``Outcome.applied``). On a card in ``cards/``, an audited change also sets ``last_checked`` to the run date
    with ``by: ai_audit`` (decision D4); a tier 1 only change leaves it as it is.
    """
    result: dict[str, str] = {}
    audited: set[str] = set()
    for o in sorted((o for o in outcomes if o.applied), key=lambda o: (o.slug, _ledger_order(o.pmid))):
        assert o.last is not None and o.last.ops is not None
        if o.audit_required:
            audited.add(o.slug)
        text = result.get(o.slug) or _base_card(cfg, o.slug).read_text(encoding="utf-8")
        try:
            result[o.slug] = apply_operations(text, o.last.ops, validate=False)
        except OperationError as exc:
            raise PipelineError(
                f"{o.slug}: accepted operations for {o.paper_id} no longer apply together: {exc}"
            ) from exc
    for slug in sorted(audited):
        if _target_in_cards(cfg, slug):
            result[slug] = _set_last_checked(result[slug], str(_read_json(cfg.f("prepare.json"))["date"]), "ai_audit")
    for slug, text in result.items():
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{slug}.yaml"
            path.write_text(text, encoding="utf-8", newline="\n")
            issues = cards.validate_card_file(path)
        if issues:
            raise PipelineError(f"{slug}: the combined result does not validate:\n" + "\n".join(map(str, issues)))
    return result


GITHUB_BODY_LIMIT = 65_536  # characters GitHub accepts in a pull request body or comment


def _part_notes(n: int, k: int) -> tuple[str, str]:
    """The line added to part 1 and the line added at the top of part k (of n)."""
    return (
        f"\nThe report continues in {n - 1} comment(s) below.\n",
        f"Report, part {k} of {n}\n",
    )


def _pack_report(report: str, budget: int) -> list[str]:
    """Cut at the start of '## ' lines; an oversized section is cut at line boundaries, a huge line hard-cut."""
    sections: list[str] = []
    for line in report.splitlines(keepends=True):
        if line.startswith("## ") or not sections:
            sections.append(line)
        else:
            sections[-1] += line
    units: list[str] = []
    for section in sections:
        if len(section) <= budget:
            units.append(section)
            continue
        for line in section.splitlines(keepends=True):
            units.extend(line[i : i + budget] for i in range(0, len(line), budget))
    chunks: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + len(unit) > budget:
            chunks.append(current)
            current = ""
        current += unit
    if current:
        chunks.append(current)
    return chunks


def split_report(report: str, limit: int = GITHUB_BODY_LIMIT) -> list[str]:
    """Split a report into parts of at most ``limit`` characters, each with its note line.

    Part 1 ends with a line saying the report continues in comments; every later part starts with
    "Report, part k of n". Removing those lines and joining the parts gives the report back.
    """
    if len(report) <= limit:
        return [report]
    n = 2
    while True:
        reserve = max(len(_part_notes(n, 1)[0]), len(_part_notes(n, n)[1]))
        chunks = _pack_report(report, limit - reserve)
        if len(chunks) <= n:
            break
        n = len(chunks)
    n = len(chunks)
    parts = []
    for k, chunk in enumerate(chunks, start=1):
        first, header = _part_notes(n, k)
        if k == 1:
            parts.append(chunk + first)
        else:
            parts.append(header + chunk)
    return parts


# The agents run on model aliases, so the trailer cannot name a model version.
COMMIT_TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>"


def _op_headline(op: Any, base: dict[str, Any]) -> str:
    """A short, one-line change-log text for one operation (no card text)."""
    if isinstance(op, AddStudy):
        return f"Added study {op.study.id}"
    if isinstance(op, AddParagraph):
        return f"Added a paragraph to {op.field}"
    if isinstance(op, ReplaceParagraph):
        return f"Replaced paragraph {op.index} of {op.field}"
    assert isinstance(op, Propose)
    if op.target == "level":
        return f"Proposed level {base.get('level')} -> {op.value}"
    if op.target == "contested":
        return "Removed the contested mark" if op.value is None else f"Set a contested mark on rungs {op.value}"
    return f"Set badge {op.target} to {op.value}"


def _op_sources(op: Any) -> list[str]:
    if isinstance(op, AddStudy):
        return [op.study.id]
    if isinstance(op, (AddParagraph, ReplaceParagraph)):
        return list(op.sources)
    assert isinstance(op, Propose)
    return [s for p in op.reason or [] for s in p.sources]


def changelog_update(cfg: Config, outcomes: Sequence[Outcome], date: str) -> tuple[Path, str] | None:
    """The new text of ``cards/changelog.yaml``: one entry per applied pair whose card is in ``cards/`` (D4).

    ``decided_by`` is ``ai_audit`` for an audited pair and ``ai_pair`` for a tier 1 only pair. None when no entry is
    due. The text is checked with the change-log validator before it is returned.
    """
    entries: list[dict[str, Any]] = []
    for o in sorted((o for o in outcomes if o.applied), key=lambda o: (o.slug, _ledger_order(o.pmid))):
        if not _target_in_cards(cfg, o.slug):
            continue
        assert o.last is not None and o.last.ops is not None
        base = yaml.safe_load(_base_card(cfg, o.slug).read_text(encoding="utf-8"))
        ops = o.last.ops.operations
        sources = list(dict.fromkeys([o.paper_id, *(s for op in ops for s in _op_sources(op))]))
        if o.audit is not None:
            reason, decided_by = o.audit.reasons_summary, "ai_audit"
        else:
            reason = f"Mechanical checks passed and the review agent accepted round {o.last.n}; no audit was needed."
            decided_by = "ai_pair"
        entries.append(
            {
                "date": dt.date.fromisoformat(date),
                "card": o.slug,
                "change": "; ".join(_op_headline(op, base) for op in ops),
                "reason": reason,
                "sources": sources,
                "tier": 2 if o.audit_required else 1,
                "decided_by": decided_by,
            }
        )
    if not entries:
        return None
    path = cfg.cards_dir / CHANGELOG_NAME
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    dumped = yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100)
    keep = existing.strip() not in ("", "[]")
    text = (existing.rstrip("\n") + "\n" + dumped) if keep else dumped
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / CHANGELOG_NAME
        log.write_text(text, encoding="utf-8", newline="\n")
        for entry in yaml.safe_load(text):
            (Path(tmp) / f"{entry['card']}.yaml").write_text("", encoding="utf-8")
        issues = cards.validate_changelog_file(log, today=dt.date.fromisoformat(date))
    if issues:
        raise PipelineError("the new change-log entries do not validate:\n" + "\n".join(map(str, issues)))
    return path, text


def audit_copies(cfg: Config, outcomes: Sequence[Outcome], date: str) -> list[tuple[Path, Path]]:
    """(record in the run, file in ``audits/``) for every valid audit record of this run.

    ``audits/<date>-<slug>-<key>.yaml`` (the consistency run adds ``-second``); a whole-card record in
    ``audit/<slug>.yaml`` becomes ``audits/<date>-<slug>.yaml``.
    """
    copies: list[tuple[Path, Path]] = []
    for o in outcomes:
        if o.audit is not None:
            copies.append((cfg.audit_path(o.slug, o.pmid), cfg.audits_dir / f"{date}-{o.slug}-{o.pmid}.yaml"))
        if o.second is not None:
            copies.append(
                (cfg.audit_path(o.slug, o.pmid, True), cfg.audits_dir / f"{date}-{o.slug}-{o.pmid}-second.yaml")
            )
    folder = cfg.f("audit")
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(raw, dict) or raw.get("paper") is not None or raw.get("card") != path.stem:
            continue
        try:
            validate_audit_record(
                cfg, raw, slug=path.stem, key=None, source=path, context_path=cfg.audit_context_path(path.stem)
            )
        except PipelineError:
            continue
        copies.append((path, cfg.audits_dir / f"{date}-{path.stem}.yaml"))
    return copies


def run_pr(cfg: Config, *, dry_run: bool, no_pr: bool, runner: Runner, out: Callable[[str], None] = print) -> int:
    prep = _read_json(cfg.f("prepare.json"))
    report = build_report(cfg)
    report_path = cfg.f("report.md")
    _write_text(report_path, report)
    outcomes = collect_outcomes(cfg)
    texts = final_card_texts(cfg, outcomes)
    copies = audit_copies(cfg, outcomes, str(prep["date"]))
    changelog = changelog_update(cfg, outcomes, str(prep["date"]))
    if not texts and not copies:
        out(f"No accepted changes this run; nothing to commit. The report is {report_path}.")
        return 0
    branch = f"pipeline/{prep['date']}"
    title = f"Weekly pipeline {prep['date']}: {len(texts)} draft card update(s)"
    if copies:
        title += f", {len(copies)} audit record(s)"
    targets = {slug: _base_card(cfg, slug) for slug in sorted(texts)}
    message = (
        f"{title}\n\nAI-drafted from new PubMed papers, checked by the review agent and, for tier 2 changes, "
        "decided by the auditor; see the pull request for the report."
        f"\n\n{COMMIT_TRAILER}"
    )

    def step(cmd: list[str]) -> bool:
        out("$ " + shlex.join(cmd))
        if dry_run:
            return True
        code, output = runner(cmd)
        if code != 0:
            out(f"error: command failed with exit code {code}\n{output}")
            return False
        return True

    if not dry_run and not no_pr:
        out("$ git rev-parse --abbrev-ref HEAD")
        code, head = runner(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if code != 0 or head.strip() != BASE_BRANCH:
            out(f"error: a pull request is cut from '{BASE_BRANCH}', but the current branch is '{head.strip()}'")
            return 1
    elif dry_run:
        out("$ git rev-parse --abbrev-ref HEAD   # must print " + BASE_BRANCH + " unless --no-pr")

    if not step(["git", "switch", "-c", branch]):
        return 1
    for slug, target in targets.items():
        out(f"write {target}")
        if not dry_run:
            _write_text(target, texts[slug])
    if changelog is not None:
        out(f"write {changelog[0]}")
        if not dry_run:
            _write_text(changelog[0], changelog[1])
    for source, dest in copies:
        out(f"write {dest}")
        if not dry_run:
            _write_text(dest, source.read_text(encoding="utf-8"))
    staged = [*targets.values(), *([changelog[0]] if changelog else []), *(dest for _src, dest in copies)]
    if staged and not step(["git", "add", "--", *map(str, staged)]):
        return 1
    if cfg.translations_dir.is_dir() and not step(["git", "add", "--", str(cfg.translations_dir)]):
        return 1
    if not step(["git", "commit", "-m", message]):
        return 1
    if no_pr:
        out(f"Committed on branch {branch}; not pushed and no pull request (--no-pr).")
        return 0
    if not step(["git", "push", "-u", "origin", branch]):
        return 1
    parts = split_report(report, GITHUB_BODY_LIMIT)
    body_path = report_path
    if len(parts) > 1:
        part_paths = [cfg.f(f"report-part-{k}.md") for k in range(1, len(parts) + 1)]
        for path, text in zip(part_paths, parts, strict=True):
            _write_text(path, text)
        body_path = part_paths[0]
    if not step(
        [
            "gh",
            "pr",
            "create",
            "--base",
            BASE_BRANCH,
            "--head",
            branch,
            "--title",
            title,
            "--body-file",
            str(body_path),
        ]
    ):
        return 1
    for path in part_paths[1:] if len(parts) > 1 else []:
        if not step(["gh", "pr", "comment", branch, "--body-file", str(path)]):
            return 1
    return 0


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _date(text: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {text!r}") from exc


def _pmid_arg(text: str) -> str:
    value = text.removeprefix("pmid:")
    if not value.isdigit():
        raise argparse.ArgumentTypeError(f"not a PMID (digits, optionally 'pmid:' first): {text!r}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--pipeline-dir", type=Path, default=DEFAULT_PIPELINE_DIR, help="default: %(default)s")
    common.add_argument(
        "--run-dir",
        type=Path,
        help="default: the newest folder in --pipeline-dir named exactly YYYY-MM-DD that holds papers.json "
        "(a folder with any other name is never chosen by default)",
    )
    common.add_argument("--cards-dir", type=Path, default=Path("cards"), help="default: %(default)s")
    common.add_argument("--drafts-dir", type=Path, default=Path("drafts"), help="default: %(default)s")
    common.add_argument("--cache-dir", type=Path, default=Path("data/cache"), help="default: %(default)s")
    common.add_argument("--spec", type=Path, default=DEFAULT_SPEC, help="default: %(default)s")
    common.add_argument("--translations-dir", type=Path, default=translations.DEFAULT_DIR, help="default: %(default)s")
    common.add_argument("--audits-dir", type=Path, default=Path("audits"), help="default: %(default)s")

    parser = argparse.ArgumentParser(prog="python -m me_atlas.pipeline", description="The weekly pipeline.")
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare", parents=[common], help="fetch new papers and create the run directory")
    source = prep.add_mutually_exclusive_group()
    source.add_argument(
        "--since", type=_date, metavar="YYYY-MM-DD", help="fetch from this entry date (default: weekly)"
    )
    source.add_argument(
        "--ids",
        nargs="+",
        type=pubmed._pmid_arg,
        metavar="PMID",
        help="classify exactly these PMIDs (no fetch window, no preprint search; only uncached ids are fetched)",
    )
    source.add_argument(
        "--ids-file",
        type=Path,
        metavar="PATH",
        help="like --ids, with one PMID per line (a 'pmid:' prefix is allowed; blank lines and # comments are ignored)",
    )
    prep.add_argument("--date", type=_date, metavar="YYYY-MM-DD", help="name of the run directory (default: today)")
    prep.add_argument("--force", action="store_true", help="overwrite an existing run of the same date")
    prep.add_argument("--reprocess", action="store_true", help="ignore the ledger of papers earlier runs processed")

    sub.add_parser("record-classification", parents=[common], help="validate classify.json")

    ctx = sub.add_parser("context", parents=[common], help="write the context file for one card and one paper")
    ctx.add_argument("slug")
    ctx.add_argument("pmid", metavar="paper", help="a PMID, pmid:<pmid>, doi:<doi> or a PPR id (a DOI-only preprint)")

    app = sub.add_parser("apply", parents=[common], help="apply an operations file to a copy of the card and check it")
    app.add_argument("slug")
    app.add_argument("ops", type=Path)
    app.add_argument("--round", type=int, choices=range(1, MAX_ROUNDS + 1), default=1)

    rev = sub.add_parser("record-review", parents=[common], help="validate a review file")
    rev.add_argument("slug")
    rev.add_argument("pmid", metavar="paper", help="a PMID, pmid:<pmid>, doi:<doi> or a PPR id (a DOI-only preprint)")
    rev.add_argument("--round", type=int, choices=range(1, MAX_ROUNDS + 1), default=1)

    aplan = sub.add_parser(
        "audit-plan", parents=[common], help="write the auditor's context file for one change or one whole card"
    )
    aplan.add_argument("slug", nargs="?")
    aplan.add_argument("pmid", nargs="?", metavar="paper", help="a PMID, pmid:<pmid>, doi:<doi> or a PPR id")
    aplan.add_argument("--card", metavar="SLUG", help="audit the whole card instead of one change")
    aplan.add_argument("--out", type=Path, help="with --card: write <OUT>/audit-context/<slug>.md (default: the run)")

    arec = sub.add_parser("record-audit", parents=[common], help="validate an audit record")
    arec.add_argument("slug", nargs="?")
    arec.add_argument("pmid", nargs="?", metavar="paper", help="a PMID, pmid:<pmid>, doi:<doi> or a PPR id")
    arec.add_argument("--card", metavar="SLUG", help="a whole-card audit (needs --file)")
    arec.add_argument("--file", type=Path, help="with --card: the record the auditor wrote")
    arec.add_argument("--second", action="store_true", help="the consistency run (audit/<slug>-<key>-second.yaml)")
    arec.add_argument("--out", type=Path, help="with --card: the folder audit-plan --out wrote to")

    asam = sub.add_parser("audit-sample", parents=[common], help="choose the pairs that need a second audit")
    asam.add_argument("--seed", help="default: the run date (YYYY-MM-DD)")

    plan = sub.add_parser(
        "translation-plan", parents=[common], help="list the translated items the accepted changes made stale"
    )
    plan.add_argument("--lang", default="nb", help="default: %(default)s")

    sub.add_parser("report", parents=[common], help="write report.md")

    pr = sub.add_parser(
        "pr", parents=[common], help="copy accepted results into drafts/, branch, commit, push, open a PR"
    )
    pr.add_argument("--dry-run", action="store_true", help="print the commands; change nothing")
    pr.add_argument("--no-pr", action="store_true", help="branch and commit locally; do not push or open a PR")
    return parser


def _latest_run(pipeline_dir: Path) -> Path:
    """The newest folder of ``pipeline_dir`` named exactly as an ISO date (YYYY-MM-DD) that holds ``papers.json``.

    A folder with any other name (``2026-11-13-livecheck``, ``nb-first-run``) is never the default; use ``--run-dir``.
    """

    def is_date(name: str) -> bool:
        try:
            return dt.date.fromisoformat(name).isoformat() == name
        except ValueError:
            return False

    runs = (
        sorted(p for p in pipeline_dir.iterdir() if is_date(p.name) and (p / "papers.json").is_file())
        if pipeline_dir.is_dir()
        else []
    )
    if not runs:
        raise PipelineError(
            f"no run in {pipeline_dir} whose folder is named YYYY-MM-DD and holds papers.json; "
            "start one with `prepare`, or name the folder with `--run-dir`"
        )
    return runs[-1]


def live_preprint_search(cache_dir: Path) -> PreprintSearch:
    """Search Europe PMC for preprints (cached under ``<cache>/europepmc/preprints/``)."""

    def search(since: dt.date, until: dt.date) -> Sequence[europepmc.PreprintRecord]:
        env = {**load_dotenv(), **os.environ}
        email = (env.get("CONTACT_EMAIL") or "").strip()
        if not email:
            raise europepmc.EuropePmcError("CONTACT_EMAIL is not set")
        client = europepmc.EuropePmcClient(email)
        try:
            return client.search_preprints(since, until, cache=europepmc.EuropePmcCache(cache_dir))
        finally:
            client.close()

    return search


def main(
    argv: Sequence[str] | None = None,
    *,
    fetch: Fetch | None = None,
    preprint_search: PreprintSearch | None = None,
    fulltext: FullTextLoader | None = None,
    runner: Runner | None = None,
    today: dt.date | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """Entry point. The fetch, the preprint search, the full-text loader and the subprocess runner are given by
    tests."""
    args = _build_parser().parse_args(argv)
    date: dt.date | None = None
    try:
        if args.command == "prepare":
            date = args.date or today or dt.date.today()
            run_dir = args.run_dir or args.pipeline_dir / date.isoformat()
        elif args.command in ("audit-plan", "record-audit") and args.card and args.out and not args.run_dir:
            run_dir = args.out  # a whole-card audit outside a weekly run
        else:
            run_dir = args.run_dir or _latest_run(args.pipeline_dir)
        cfg = Config(
            run_dir,
            args.cards_dir,
            args.drafts_dir,
            args.cache_dir,
            args.spec,
            args.pipeline_dir,
            args.translations_dir,
            args.audits_dir,
        )
        return _dispatch(args, cfg, fetch, preprint_search, fulltext, runner, date, out)
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _dispatch(
    args: argparse.Namespace,
    cfg: Config,
    fetch: Fetch | None,
    preprint_search: PreprintSearch | None,
    fulltext: FullTextLoader | None,
    runner: Runner | None,
    date: dt.date | None,
    out: Callable[[str], None],
) -> int:
    if args.command == "prepare":
        assert date is not None
        summary = prepare(
            cfg,
            since=args.since,
            date=date,
            fetch=fetch or pubmed.main,
            preprint_search=preprint_search or live_preprint_search(cfg.cache_dir),
            force=args.force,
            reprocess=args.reprocess,
            ids=args.ids if args.ids_file is None else read_ids_file(args.ids_file),
        )
        out(f"run directory: {cfg.run_dir}")
        out(
            f"{summary['selected']} paper(s) selected, {summary['skipped_processed']} skipped as already processed; "
            f"{len(summary['excluded_retracted'])} retracted (excluded)"
        )
        counts = summary["preprints"]["counts"]
        if summary["mode"] == "ids":
            out("preprints: no preprint search was made (papers given by id)")
        else:
            out(
                f"preprints: {counts['found']} found, {counts['offered']} offered "
                f"(dropped: {', '.join(f'{n} {r}' for r, n in counts['dropped'].items())})"
            )
        for row in summary["preprints_published"]:
            out(f"preprint on {row['card']} now published: {row['study']} -> pmid:{row['pmid']}")
        for r in summary["retractions_on_cards"]:
            out(f"RETRACTED and cited on {', '.join(r['cards'])}: pmid:{r['pmid']}")
        return 0
    if args.command == "record-classification":
        result = record_classification(cfg)
        out(
            f"classification recorded: {len(result['matches'])} card/paper match(es), "
            f"{len(result['stopped'])} stopped, "
            f"{len(result['new_hypotheses'])} possible new hypothesis(es)"
        )
        return 0
    if args.command == "context":
        loader = fulltext or live_fulltext_loader(cfg.cache_dir)
        key, _paper = resolve_paper(cfg, args.pmid)
        text = build_context(cfg, args.slug, key, loader)
        path = cfg.f("context", f"{args.slug}-{key}.md")
        _write_text(path, text)
        out(str(path))
        return 0
    if args.command == "apply":
        result = apply_ops_file(cfg, args.slug, args.ops, args.round)
        for line in result["ops_errors"]:
            out(f"operations error: {line}")
        for line in result["validator"]:
            out(f"validator: {line}")
        for line in result["warnings"]:
            out(f"warning: {line}")
        for row in result["citations"]:
            if (row["level"] == citations.ERROR or row["code"] == "C9") and not row["preexisting"]:
                out(f"citations: {row['study']}: {row['code']} {row['level']}: {row['message']}")
        for row in result["citations"]:
            if row["level"] == citations.ERROR and row["preexisting"]:
                out(f"citations (already on the card, not blocking): {row['study']}: {row['code']}: {row['message']}")
        out(f"checks: {cfg.checks_path(args.slug, result['key'], args.round)}")
        if result["passed"]:
            out("PASSED" + (" (no change proposed)" if result["no_change"] else f"; applied card: {result['applied']}"))
            return 0
        out("FAILED")
        return 1
    if args.command == "record-review":
        key, _paper = resolve_paper(cfg, args.pmid)
        review = record_review(cfg, args.slug, key, args.round)
        out(f"review recorded: {review.verdict}, {len(review.findings)} finding(s)")
        return 0
    if args.command == "audit-plan":
        loader = fulltext or live_fulltext_loader(cfg.cache_dir)
        if args.card:
            if args.slug or args.pmid:
                raise PipelineError("give either <slug> <paper> or --card <slug>, not both")
            text = build_audit_context(cfg, args.card, None, loader)
            path = (args.out or cfg.run_dir) / "audit-context" / f"{args.card}.md"
        else:
            if not (args.slug and args.pmid):
                raise PipelineError("give <slug> <paper>, or --card <slug>")
            key, _paper = resolve_paper(cfg, args.pmid)
            text = build_audit_context(cfg, args.slug, key, loader)
            path = cfg.audit_context_path(args.slug, key)
        _write_text(path, text)
        out(str(path))
        return 0
    if args.command == "record-audit":
        if args.card:
            if args.slug or args.pmid:
                raise PipelineError("give either <slug> <paper> or --card <slug> --file PATH, not both")
            record = record_audit(cfg, args.card, None, second=args.second, file=args.file, out_dir=args.out)
        else:
            if not (args.slug and args.pmid):
                raise PipelineError("give <slug> <paper>, or --card <slug> --file PATH")
            key, _paper = resolve_paper(cfg, args.pmid)
            record = record_audit(cfg, args.slug, key, second=args.second, file=args.file)
        level = f" (accepted level {record.accepted_level})" if record.accepted_level is not None else ""
        out(f"audit recorded: {record.decision}{level}, {len(record.parts)} part(s)")
        return 0
    if args.command == "audit-sample":
        sample = audit_sample(cfg, args.seed)
        out(
            f"{len(sample['pairs'])} of {sample['audited']} audited pair(s) need a second audit (seed {sample['seed']})"
        )
        for pair in sample["pairs"]:
            out(f"  {pair['card']} {pair['key']}: {pair['why']}")
        out(str(cfg.f("audit-sample.json")))
        return 0
    if args.command == "translation-plan":
        plan = translation_plan(cfg, args.lang)
        for entry in plan["cards"]:
            made_stale = [i["item"] for i in entry["items"] if i["reason"] == "made_stale"]
            out(
                f"{entry['slug']}: {len(entry['items'])} item(s) to translate, "
                f"{len(made_stale)} made stale by accepted changes"
            )
            for item in entry["items"]:
                out(f"  {item['reason']}: {item['item']}")
        for slug in plan["untranslated_cards"]:
            out(f"{slug}: no translation file yet (first translation is a manual run); not planned")
        out(f"plan: {cfg.f('translation-plan.json')}")
        return 0
    if args.command == "report":
        path = cfg.f("report.md")
        _write_text(path, build_report(cfg))
        out(str(path))
        out(f"ledger updated: {record_processed(cfg)} paper(s) marked processed in {cfg.ledger_path}")
        return 0
    return run_pr(cfg, dry_run=args.dry_run, no_pr=args.no_pr, runner=runner or subprocess_runner, out=out)


if __name__ == "__main__":
    raise SystemExit(main())
