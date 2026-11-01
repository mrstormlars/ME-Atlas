"""The weekly pipeline: the steps that code can do. Classification, drafting and review are Claude Code
subagents (``.claude/agents/``) driven by ``/ukentlig``; this module prepares their input, validates their
output, applies their operations and builds the report and the pull request.

Command line::

    uv run python -m me_atlas.pipeline prepare [--since YYYY-MM-DD]
    uv run python -m me_atlas.pipeline record-classification
    uv run python -m me_atlas.pipeline context <slug> <pmid>
    uv run python -m me_atlas.pipeline apply <slug> <ops file> [--round 1|2]
    uv run python -m me_atlas.pipeline record-review <slug> <pmid> [--round 1|2]
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

from me_atlas import cards, citations, europepmc, pubmed
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
    tier,
)

DEFAULT_PIPELINE_DIR = Path("data/pipeline")
DEFAULT_SPEC = Path("docs/ME-Atlas-functional-spec.md")
# The full text goes into the context file up to this many characters; the file says so when it cuts.
FULLTEXT_CHAR_BUDGET = 60_000
MAX_ROUNDS = 2
BASE_BRANCH = "main"

Pmid = Annotated[str, StringConstraints(pattern=r"^\d+$")]


class PipelineError(Exception):
    """A step cannot continue; the message says what to fix."""


# ---------------------------------------------------------------------------
# Schemas of the agent output files
# ---------------------------------------------------------------------------


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Classification(_M):
    pmid: Pmid
    cards: list[Slug]
    article_type: Literal["original", "review", "other"]
    new_hypothesis: NonEmptyStr | None
    reason: NonEmptyStr


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


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------

Fetch = Callable[[Sequence[str]], int]

PAPER_FIELDS = ("id", "pmid", "doi", "title", "abstract", "journal", "year", "publication_types", "entry_date")


def read_ledger(cfg: Config) -> dict[str, str]:
    """PMID to the date of the run that processed it. Empty if no run has finished ``report`` yet."""
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
        processed[paper["pmid"]] = date
    _write_json(cfg.ledger_path, {"processed": dict(sorted(processed.items(), key=lambda kv: int(kv[0])))})
    return len(papers)


def prepare(
    cfg: Config,
    *,
    since: dt.date | None,
    date: dt.date,
    fetch: Fetch,
    force: bool = False,
    reprocess: bool = False,
) -> dict[str, Any]:
    """Fetch, then write papers.json, cards.json and prepare.json. Returns the summary.

    Selects the papers in the fetch window, cached or not, that no earlier finished run has processed
    (the ledger), unless ``reprocess``. Retracted papers are never selected.
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
        dumped = record.model_dump()
        papers.append({name: dumped[name] for name in PAPER_FIELDS})

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
    papers = {p["pmid"]: p for p in _read_json(cfg.f("papers.json"))}
    slugs = {c["slug"] for c in _read_json(cfg.f("cards.json"))}

    problems: list[str] = []
    seen: set[str] = set()
    for i, item in enumerate(parsed.papers):
        where = f"papers[{i}] (pmid {item.pmid})"
        if item.pmid not in papers:
            problems.append(f"{where}: not one of this run's papers")
        if item.pmid in seen:
            problems.append(f"{where}: classified more than once")
        seen.add(item.pmid)
        for slug in item.cards:
            if slug not in slugs:
                problems.append(f"{where}: unknown card slug '{slug}' (cards: {', '.join(sorted(slugs)) or 'none'})")
    missing = sorted(set(papers) - seen, key=int)
    if missing:
        problems.append(f"papers not classified: {', '.join(missing)}")
    if problems:
        raise PipelineError(f"{path} is not valid:\n" + "\n".join(problems))

    matches, stopped, new_hypotheses = [], [], []
    for item in parsed.papers:
        if item.new_hypothesis:
            new_hypotheses.append({"pmid": item.pmid, "hypothesis": item.new_hypothesis, "reason": item.reason})
        if item.article_type != "original":
            stopped.append({"pmid": item.pmid, "why": f"article type: {item.article_type}"})
        elif not item.cards:
            stopped.append({"pmid": item.pmid, "why": "matches no card"})
        else:
            matches += [{"slug": slug, "pmid": item.pmid} for slug in item.cards]
    result = {"matches": matches, "stopped": stopped, "new_hypotheses": new_hypotheses}
    _write_json(cfg.f("matches.json"), result)
    _log(cfg, {"event": "record-classification", "matches": len(matches), "stopped": len(stopped)})
    return result


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FullTextResult:
    xml: bytes | None
    note: str


FullTextLoader = Callable[[str], FullTextResult]


def live_fulltext_loader(cache_dir: Path) -> FullTextLoader:
    """Look the paper up in Europe PMC (cached) and read its open-access full text, if there is one."""

    def load(pmid: str) -> FullTextResult:
        env = {**load_dotenv(), **os.environ}
        email = (env.get("CONTACT_EMAIL") or "").strip()
        if not email:
            return FullTextResult(None, "CONTACT_EMAIL is not set, so no full text was requested")
        client = europepmc.EuropePmcClient(email)
        try:
            result = europepmc.get_fulltext(client, europepmc.EuropePmcCache(cache_dir), pmid)
        except europepmc.EuropePmcError as exc:
            return FullTextResult(None, f"Europe PMC request failed: {exc}")
        finally:
            client.close()
        if result.path is None:
            return FullTextResult(
                None, f"no open full text (Europe PMC: {europepmc.STATUS_TEXT[result.lookup.status]})"
            )
        return FullTextResult(result.path.read_bytes(), f"Europe PMC open access, {result.lookup.pmcid}")

    return load


def spec_section_3(spec_path: Path) -> str:
    try:
        text = spec_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PipelineError(f"cannot read the functional spec {spec_path}: {exc}") from exc
    match = re.search(r"^## 3\. .*?(?=^## 4\. )", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise PipelineError(f"{spec_path} has no section '## 3.' followed by '## 4.'")
    return match.group(0).strip()


def build_context(
    cfg: Config, slug: str, pmid: str, loader: FullTextLoader, *, budget: int = FULLTEXT_CHAR_BUDGET
) -> str:
    """The one file the drafting and review agents read about a card and a paper. No drafter output in it."""
    base = _base_card(cfg, slug)
    _load_card(base)
    record = _record(cfg, pmid)
    full = loader(pmid)

    parts = [
        f"# Context: card `{slug}` and paper `pmid:{pmid}`",
        "",
        "Everything the drafting and review steps may rely on is in this file. Cite only the studies already on "
        f"the card and `pmid:{pmid}`. If something is not here, write TODO: verify.",
        "",
        f"## 1. The card now (`{base}`)",
        "",
        "```yaml",
        base.read_text(encoding="utf-8").rstrip("\n"),
        "```",
        "",
        "## 2. The rubric (functional spec section 3)",
        "",
        spec_section_3(cfg.spec_path),
        "",
        "## 3. The paper's PubMed record",
        "",
        f"- id: `{record.id}`",
        f"- title: {record.title}",
        f"- journal: {record.journal or 'not stated'}",
        f"- year: {record.year if record.year is not None else 'not stated'}",
        f"- doi: {record.doi or 'not stated'}",
        f"- publication types: {', '.join(record.publication_types) or 'not stated'}",
        f"- retracted: {'yes' if record.retracted else 'no'}",
        "",
        "Abstract:",
        "",
        record.abstract or "(the record has no abstract)",
        "",
        "## 4. Full text",
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
        parts += ["## 5. Sentences that may name a case definition (verbatim from the full text)", ""]
        if candidates:
            parts += [f"- [{c.section}] {c.sentence}" for c in candidates]
            parts.append("")
            parts.append("These only suggest; which definition a sentence means is for the drafter to decide.")
        else:
            parts.append("None found.")
        parts.append("")
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def _pmid_from_name(path: Path) -> str | None:
    match = re.search(r"-(\d+)-r\d+$", path.stem)
    return match.group(1) if match else None


def _citation_rows(issues: Sequence[citations.CitationIssue]) -> list[dict[str, str]]:
    return [{"study": i.study, "code": i.code, "level": i.level, "message": i.message} for i in issues]


def apply_ops_file(cfg: Config, slug: str, ops_path: Path, n: int) -> dict[str, Any]:
    """Validate and apply one ops file to a copy of the card; run the validator and the citations check.

    Writes ``checks/<slug>-<pmid>-r<n>.json`` and, when the operations applied, ``applied/<slug>-<pmid>-r<n>/``
    with the new card and a diff. The draft in ``drafts/`` is never touched. Returns the checks record.
    """
    pmid = _pmid_from_name(ops_path)
    ops: OpsFile | None = None
    ops_errors: list[str] = []
    raw: Any = None
    try:
        raw = _read_json(ops_path)
        ops = parse_ops(raw)
        pmid = ops.paper.removeprefix("pmid:") if ops.paper.startswith("pmid:") else pmid
        if ops.card != slug:
            ops_errors.append(f"the ops file is for card '{ops.card}', not '{slug}'")
    except (PipelineError, OperationError) as exc:
        ops_errors.append(str(exc))
        if pmid is None and isinstance(raw, dict):
            candidate = str(raw.get("paper", "")).removeprefix("pmid:")
            pmid = candidate if candidate.isdigit() else None
    if pmid is None:
        raise PipelineError("cannot tell which paper the ops file is for; " + "; ".join(ops_errors))

    result: dict[str, Any] = {
        "card": slug,
        "paper": f"pmid:{pmid}",
        "round": n,
        "ops_file": str(ops_path),
        "ops_errors": ops_errors,
        "validator": [],
        "citations": [],
        "applied": None,
        "diff": None,
        "no_change": False,
        "tiers": {"1": 0, "2": 0},
    }
    base = _base_card(cfg, slug)
    base_text = base.read_text(encoding="utf-8")

    new_text: str | None = None
    if ops is not None and not ops_errors:
        result["tiers"] = {str(t): sum(tier(o) == t for o in ops.operations) for t in (1, 2)}
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
        _count, validator_issues = cards.validate_paths([card_path])
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
    if review.paper != f"pmid:{pmid}":
        problems.append(f"paper is '{review.paper}', expected 'pmid:{pmid}'")
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
    pmid: str
    status: Literal["accepted", "no_change", "parked", "skipped"]
    note: str
    rounds: list[Round] = field(default_factory=list)

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
        slug, pmid = match["slug"], match["pmid"]
        rounds = [r for n in range(1, MAX_ROUNDS + 1) if (r := _load_round(cfg, slug, pmid, n))]
        outcome = Outcome(slug, pmid, "skipped", "", rounds)
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
            o.note = "conflicts with " + "; ".join(f"pmid:{p.pmid} on {' '.join(map(str, t))}" for p, t in others)
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


def _window_text(prep: dict[str, Any]) -> str:
    if prep.get("since"):
        return f"the fetch window since {prep['since']}"
    return "the weekly fetch window (the last 14 days)"


def build_report(cfg: Config) -> str:
    prep = _read_json(cfg.f("prepare.json"))
    papers = _read_json(cfg.f("papers.json"))
    classify = _read_json(cfg.f("matches.json")) if cfg.f("matches.json").exists() else None
    classified = _read_json(cfg.f("classify.json")) if cfg.f("classify.json").exists() else {"papers": []}
    outcomes = collect_outcomes(cfg)
    by_status = {s: [o for o in outcomes if o.status == s] for s in ("accepted", "no_change", "parked", "skipped")}

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
        for f in by_severity(last.review.findings):
            where = "the card" if f.operation is None else f"operation {f.operation}"
            notes.append(f"reviewer note ({f.severity}) on {where}: {f.problem}")
        touched: list[list[str]] = []
        for op in last.ops.operations:
            target = tier2 if tier(op) == 2 else tier1
            target.append(f"- **{o.slug}**, from {_paper_line(cfg, o.pmid)}: {describe_op(op, base)}")
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
        f"{len(by_status['skipped'])} skipped, {len(by_status['no_change'])} with no change proposed.",
        "",
        "Draft changes only. Nothing here is published; merging this pull request puts the drafts on `main`, "
        "and moving a card into `cards/` is a separate founder decision.",
        "",
        "## Proposed changes",
        "",
        "### Tier 2: the founder decides (level, contested mark, badge)",
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
            lines.append(f"- **{o.slug}**, from {_paper_line(cfg, o.pmid)}: {o.note}")
            for r in o.rounds:
                if r.review and r.review.verdict == "reject":
                    for f in by_severity(r.review.findings):
                        where = "card" if f.operation is None else f"operation {f.operation}"
                        fix = f" Suggested fix: {f.fix}" if f.fix else ""
                        lines.append(f"  - round {r.n}, {where} ({f.severity}): {f.problem}{fix}")
            last = o.last
            if last is not None and last.ops is not None:
                base = base_data(o.slug)
                for op in last.ops.operations:
                    lines.append(f"  - proposed (round {last.n}): {describe_op(op, base)}")
    else:
        lines.append("None.")
    lines += ["", "## Possible new hypotheses", ""]
    hyp = classify["new_hypotheses"] if classify else []
    if hyp:
        lines.append("No card is drafted for these. They are listed so the founder can decide whether to add one.")
        lines.append("")
        lines += [f"- {_paper_line(cfg, h['pmid'])}: {h['hypothesis']} ({h['reason']})" for h in hyp]
    else:
        lines.append("None.")
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
    skipped = [f"- **{o.slug}**, {_paper_line(cfg, o.pmid)}: {o.note}" for o in by_status["skipped"]]
    skipped += [
        f"- {_paper_line(cfg, s['pmid'])}: stopped, {s['why']}" for s in (classify["stopped"] if classify else [])
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
        titles = {p["pmid"]: p["title"] for p in papers}
        for item in classified["papers"]:
            lines.append(
                f"| pmid:{item['pmid']} {_cell(titles.get(item['pmid'], ''))} | {item['article_type']} | "
                f"{', '.join(item['cards']) or '-'} | {_cell(item['reason'])} |"
            )
    else:
        lines.append("None classified.")
    return "\n".join(lines) + "\n"


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
    for o in sorted((o for o in outcomes if o.status == "accepted"), key=lambda o: (o.slug, int(o.pmid))):
        assert o.last is not None and o.last.ops is not None
        text = result.get(o.slug) or _base_card(cfg, o.slug).read_text(encoding="utf-8")
        try:
            result[o.slug] = apply_operations(text, o.last.ops, validate=False)
        except OperationError as exc:
            raise PipelineError(
                f"{o.slug}: accepted operations for pmid:{o.pmid} no longer apply together: {exc}"
            ) from exc
    for slug, text in result.items():
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{slug}.yaml"
            path.write_text(text, encoding="utf-8", newline="\n")
            issues = cards.validate_card_file(path)
        if issues:
            raise PipelineError(f"{slug}: the combined result does not validate:\n" + "\n".join(map(str, issues)))
    return result


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
    if not step(["git", "commit", "-m", message]):
        return 1
    if no_pr:
        out(f"Committed on branch {branch}; not pushed and no pull request (--no-pr).")
        return 0
    if not step(["git", "push", "-u", "origin", branch]):
        return 1
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
            str(report_path),
        ]
    ):
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
    ctx.add_argument("pmid", type=_pmid_arg)

    app = sub.add_parser("apply", parents=[common], help="apply an operations file to a copy of the card and check it")
    app.add_argument("slug")
    app.add_argument("ops", type=Path)
    app.add_argument("--round", type=int, choices=range(1, MAX_ROUNDS + 1), default=1)

    rev = sub.add_parser("record-review", parents=[common], help="validate a review file")
    rev.add_argument("slug")
    rev.add_argument("pmid", type=_pmid_arg)
    rev.add_argument("--round", type=int, choices=range(1, MAX_ROUNDS + 1), default=1)

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


def main(
    argv: Sequence[str] | None = None,
    *,
    fetch: Fetch | None = None,
    fulltext: FullTextLoader | None = None,
    runner: Runner | None = None,
    today: dt.date | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """Entry point. The fetch, the full-text loader and the subprocess runner are given by tests."""
    args = _build_parser().parse_args(argv)
    date: dt.date | None = None
    try:
        if args.command == "prepare":
            date = args.date or today or dt.date.today()
            run_dir = args.run_dir or args.pipeline_dir / date.isoformat()
        else:
            run_dir = args.run_dir or _latest_run(args.pipeline_dir)
        cfg = Config(run_dir, args.cards_dir, args.drafts_dir, args.cache_dir, args.spec, args.pipeline_dir)
        return _dispatch(args, cfg, fetch, fulltext, runner, date, out)
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _dispatch(
    args: argparse.Namespace,
    cfg: Config,
    fetch: Fetch | None,
    fulltext: FullTextLoader | None,
    runner: Runner | None,
    date: dt.date | None,
    out: Callable[[str], None],
) -> int:
    if args.command == "prepare":
        assert date is not None
        summary = prepare(
            cfg, since=args.since, date=date, fetch=fetch or pubmed.main, force=args.force, reprocess=args.reprocess
        )
        out(f"run directory: {cfg.run_dir}")
        out(
            f"{summary['selected']} paper(s) selected, {summary['skipped_processed']} skipped as already processed; "
            f"{len(summary['excluded_retracted'])} retracted (excluded)"
        )
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
        text = build_context(cfg, args.slug, args.pmid, loader)
        path = cfg.f("context", f"{args.slug}-{args.pmid}.md")
        _write_text(path, text)
        out(str(path))
        return 0
    if args.command == "apply":
        result = apply_ops_file(cfg, args.slug, args.ops, args.round)
        for line in result["ops_errors"]:
            out(f"operations error: {line}")
        for line in result["validator"]:
            out(f"validator: {line}")
        for row in result["citations"]:
            if row["level"] == citations.ERROR and not row["preexisting"]:
                out(f"citations: {row['study']}: {row['code']} ERROR: {row['message']}")
        for row in result["citations"]:
            if row["level"] == citations.ERROR and row["preexisting"]:
                out(f"citations (already on the card, not blocking): {row['study']}: {row['code']}: {row['message']}")
        out(f"checks: {cfg.checks_path(args.slug, result['paper'].removeprefix('pmid:'), args.round)}")
        if result["passed"]:
            out("PASSED" + (" (no change proposed)" if result["no_change"] else f"; applied card: {result['applied']}"))
            return 0
        out("FAILED")
        return 1
    if args.command == "record-review":
        review = record_review(cfg, args.slug, args.pmid, args.round)
        out(f"review recorded: {review.verdict}, {len(review.findings)} finding(s)")
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
