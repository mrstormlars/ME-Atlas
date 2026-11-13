"""The weekly pipeline: the steps that code can do. Classification, drafting and review are Claude Code
subagents (``.claude/agents/``) driven by ``/ukentlig``; this module prepares their input, validates their
output, applies their operations and builds the report and the pull request.

Command line::

    uv run python -m me_atlas.pipeline prepare [--since YYYY-MM-DD]
    uv run python -m me_atlas.pipeline record-classification
    uv run python -m me_atlas.pipeline context <slug> <pmid>
    uv run python -m me_atlas.pipeline apply <slug> <ops file> [--round 1|2]
    uv run python -m me_atlas.pipeline record-review <slug> <pmid> [--round 1|2]
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
import os
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
    Nothing is proposed: the list only tells the founder that a published version now exists.
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


def prepare(
    cfg: Config,
    *,
    since: dt.date | None,
    date: dt.date,
    fetch: Fetch,
    preprint_search: PreprintSearch,
    force: bool = False,
    reprocess: bool = False,
) -> dict[str, Any]:
    """Fetch, then write papers.json, cards.json and prepare.json. Returns the summary.

    Selects the papers in the fetch window, cached or not, that no earlier finished run has processed
    (the ledger), unless ``reprocess``. Retracted papers are never selected. ``preprint_search`` finds the
    preprints first indexed in the same window; those that survive the de-duplication (``PREPRINT_DROP_REASONS``)
    are added to papers.json as ``doi:`` papers with no PMID. A failed search fails the step before anything is
    written.
    """
    if cfg.f("papers.json").exists() and not force:
        raise PipelineError(f"{cfg.run_dir} already holds a run; use --force to start it again or --date for another")
    runs = cfg.cache_dir / "runs"
    before = {p.name for p in runs.glob("*.json")} if runs.is_dir() else set()
    argv = ["fetch", "--since", since.isoformat()] if since else ["fetch", "--weekly"]
    code = fetch([*argv, "--cache-dir", str(cfg.cache_dir)])
    if code != 0:
        raise PipelineError(f"the PubMed fetch failed (exit code {code}); nothing was prepared")
    fresh = sorted(p for p in runs.glob("*.json") if p.name not in before) if runs.is_dir() else []
    if not fresh:
        raise PipelineError(f"the PubMed fetch wrote no new run manifest in {runs}")
    manifest = _read_json(fresh[-1])

    window_since = since or date - dt.timedelta(days=pubmed.WEEKLY_DAYS)
    try:
        found_preprints = list(preprint_search(window_since, date))
    except europepmc.EuropePmcError as exc:
        raise PipelineError(f"the preprint search failed ({exc}); nothing was prepared") from exc

    cache = pubmed.RawCache(cfg.cache_dir)
    papers: list[dict[str, Any]] = []
    excluded_retracted: list[str] = []
    unreadable: list[str] = []
    in_window = list(dict.fromkeys(manifest.get("window_pmids", manifest.get("new_pmids", []))))
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
        "mode": "since" if since else "weekly",
        "manifest": str(fresh[-1]),
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

    new_errors = [r for r in result["citations"] if r["level"] == citations.ERROR and not r["preexisting"]]
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

    @property
    def last(self) -> Round | None:
        return self.rounds[-1] if self.rounds else None


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


def collect_outcomes(cfg: Config) -> list[Outcome]:
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
    accepted = [o for o in outcomes if o.status == "accepted" and o.last is not None and o.last.ops is not None]
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
        if r["level"] == "ERROR" and not r.get("preexisting")
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
    if prep.get("since"):
        return f"the fetch window since {prep['since']}"
    return "the weekly fetch window (the last 14 days)"


def _preprint_intro(prep: dict[str, Any]) -> list[str]:
    counts = (prep.get("preprints") or {}).get("counts")
    if not counts:
        return []
    dropped = ", ".join(f"{n} {reason}" for reason, n in counts["dropped"].items() if n) or "none dropped"
    return [
        "",
        f"Preprints (Europe PMC): {counts['found']} found, {counts['offered']} offered to the classifier "
        f"({dropped}). A preprint can only be an early signal and is never drafted automatically.",
    ]


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
        last = o.last
        assert last is not None and last.ops is not None and last.review is not None
        base = base_data(o.slug)
        notes = [f"review: accept (round {last.n})"]
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
        f"Proposed changes: {len(by_status['accepted'])} accepted by the reviewer, {len(by_status['parked'])} parked, "
        f"{len(by_status['skipped'])} skipped, {len(by_status['withdrawn'])} rejected and then withdrawn by the "
        f"drafter, {len(by_status['no_change'])} with no change proposed.",
        *_preprint_intro(prep),
        "",
        "Draft changes only. Nothing here is published; merging this pull request puts the drafts on `main`, "
        "and moving a card into `cards/` is a separate founder decision.",
        "",
        "## Proposed changes",
        "",
        "### Tier 2: the founder decides (level, contested mark, badge, anything about a preprint)",
        "",
        *(tier2 or ["None."]),
        "",
        "### Tier 1: factual additions (calibration period: the founder approves these too)",
        "",
        *(tier1 or ["None."]),
        "",
        "## Parking lot",
        "",
    ]
    if by_status["parked"]:
        lines.append(
            "Changes the reviewer still rejected after two rounds, or that never passed. Not applied. "
            "The founder decides."
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
            "The reviewer's findings and what the drafter proposed are kept here so the founder can see why."
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
        lines.append("No card is drafted for these. They are listed so the founder can decide whether to add one.")
        lines.append("")
        lines += [f"- {_ref_line(cfg, h, papers)}: {h['hypothesis']} ({h['reason']})" for h in hyp]
    else:
        lines.append("None.")
    lines += ["", "## Preprints on cards with a published version", ""]
    published = prep.get("preprints_published", [])
    if published:
        lines.append(
            "A study marked `preprint: true` whose Europe PMC record links to a published article. Nothing is "
            "proposed; the founder decides whether the published paper replaces the preprint."
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


def final_card_texts(cfg: Config, outcomes: Sequence[Outcome]) -> dict[str, str]:
    """The text of each card after all its accepted operation files, applied in order of paper."""
    result: dict[str, str] = {}
    for o in sorted((o for o in outcomes if o.status == "accepted"), key=lambda o: (o.slug, _ledger_order(o.pmid))):
        assert o.last is not None and o.last.ops is not None
        text = result.get(o.slug) or _base_card(cfg, o.slug).read_text(encoding="utf-8")
        try:
            result[o.slug] = apply_operations(text, o.last.ops, validate=False)
        except OperationError as exc:
            raise PipelineError(
                f"{o.slug}: accepted operations for {o.paper_id} no longer apply together: {exc}"
            ) from exc
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
        f"The report continues in {n - 1} comment(s) below.\n",
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
            parts.append(chunk + ("" if chunk.endswith("\n") else "\n") + first)
        else:
            parts.append(header + chunk)
    return parts


def run_pr(cfg: Config, *, dry_run: bool, no_pr: bool, runner: Runner, out: Callable[[str], None] = print) -> int:
    prep = _read_json(cfg.f("prepare.json"))
    report = build_report(cfg)
    report_path = cfg.f("report.md")
    _write_text(report_path, report)
    outcomes = collect_outcomes(cfg)
    texts = final_card_texts(cfg, outcomes)
    if not texts:
        out(f"No accepted changes this run; nothing to commit. The report is {report_path}.")
        return 0
    branch = f"pipeline/{prep['date']}"
    title = f"Weekly pipeline {prep['date']}: {len(texts)} draft card update(s)"
    targets = {slug: cfg.drafts_dir / f"{slug}.yaml" for slug in sorted(texts)}
    message = (
        f"{title}\n\nAI-drafted from new PubMed papers and checked by the review agent; "
        "see the pull request for the report. Drafts only, nothing is published."
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
    if not step(["git", "add", "--", *map(str, targets.values())]):
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
    common.add_argument("--run-dir", type=Path, help="default: the newest run in --pipeline-dir")
    common.add_argument("--cards-dir", type=Path, default=Path("cards"), help="default: %(default)s")
    common.add_argument("--drafts-dir", type=Path, default=Path("drafts"), help="default: %(default)s")
    common.add_argument("--cache-dir", type=Path, default=Path("data/cache"), help="default: %(default)s")
    common.add_argument("--spec", type=Path, default=DEFAULT_SPEC, help="default: %(default)s")
    common.add_argument("--translations-dir", type=Path, default=translations.DEFAULT_DIR, help="default: %(default)s")

    parser = argparse.ArgumentParser(prog="python -m me_atlas.pipeline", description="The weekly pipeline.")
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare", parents=[common], help="fetch new papers and create the run directory")
    prep.add_argument("--since", type=_date, metavar="YYYY-MM-DD", help="fetch from this entry date (default: weekly)")
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
    runs = sorted(p for p in pipeline_dir.glob("*") if (p / "papers.json").is_file()) if pipeline_dir.is_dir() else []
    if not runs:
        raise PipelineError(f"no run in {pipeline_dir}; start one with `prepare`")
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
        )
        out(f"run directory: {cfg.run_dir}")
        out(
            f"{summary['selected']} paper(s) selected, {summary['skipped_processed']} skipped as already processed; "
            f"{len(summary['excluded_retracted'])} retracted (excluded)"
        )
        counts = summary["preprints"]["counts"]
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
            if row["level"] == citations.ERROR and not row["preexisting"]:
                out(f"citations: {row['study']}: {row['code']} ERROR: {row['message']}")
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
