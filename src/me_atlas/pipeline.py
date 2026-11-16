"""The weekly pipeline: the steps that code can do. Classification, drafting and review are Claude Code
subagents (``.claude/agents/``) driven by ``/ukentlig``; this module prepares their input, validates their
output, applies their operations and builds the report and the pull request.

Command line::

    uv run python -m me_atlas.pipeline prepare [--since YYYY-MM-DD]
    uv run python -m me_atlas.pipeline record-classification
    uv run python -m me_atlas.pipeline context <slug> <pmid>
    uv run python -m me_atlas.pipeline apply <slug> <ops file> [--round 1|2|L|C<k>]
    uv run python -m me_atlas.pipeline record-review <slug> <pmid> [--round 1|2|L|C<k>]
    uv run python -m me_atlas.pipeline correction-plan <slug> --out DIR
    uv run python -m me_atlas.pipeline card-review-plan <slug> --round C<k> [--pre | --revised[2-4]] --out DIR
    uv run python -m me_atlas.pipeline record-review <slug> --card-review --round C<k> [--pre | --revised[2-4]]
        --run-dir DIR
    uv run python -m me_atlas.pipeline audit-plan <slug> <pmid> | --card <slug> [--out DIR]
    uv run python -m me_atlas.pipeline record-audit <slug> <pmid> [--second] | --card <slug> --file PATH
    uv run python -m me_atlas.pipeline audit-sample [--seed S]
    uv run python -m me_atlas.pipeline translation-plan [--lang nb]
    uv run python -m me_atlas.pipeline report
    uv run python -m me_atlas.pipeline pr [--dry-run] [--no-pr]
    uv run python -m me_atlas.pipeline content-paths [--base main] [--head HEAD]

Everything is kept in ``data/pipeline/<date>/`` (gitignored): see ``docs/pipeline.md`` for the layout.
No step here calls an AI. Tests inject the fetch, the full-text loader and the subprocess runner.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import difflib
import hashlib
import json
import math
import os
import random
import re
import shlex
import shutil
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
    CORRECTION_ONLY_OPS,
    AddParagraph,
    AddSentence,
    AddStudy,
    OperationError,
    OpsFile,
    Propose,
    RemoveLink,
    RemoveParagraph,
    ReplaceParagraph,
    UpdateStudy,
    apply_operations,
    parse_ops,
    tiers,
)

DEFAULT_PIPELINE_DIR = Path("data/pipeline")
DEFAULT_SPEC = Path("docs/ME-Atlas-functional-spec.md")
# The full text goes into the context file up to this many characters; the file says so when it cuts.
FULLTEXT_CHAR_BUDGET = 60_000
MAX_ROUNDS = 2
# The one redraft after an auditor's accept_lower (E3): files carry "L" where a round carries 1 or 2. It counts neither
# as round 1 nor as round 2 and allows no further round.
REDRAFT = "L"
# The correction of a held-back draft (rounds C1, C2, ...): at most this many rounds per card (contract A3).
MAX_CORRECTION_ROUNDS = 1
# Logged exceptions (DECISIONS 2026-11-15: two cards stranded on the sequence of the 2026-11-14 path, each gets round
# C2; DECISIONS 2026-11-15/16: the seven last held-back drafts get one more round, `oxidative-nitrosative-stress` its
# third). Not a general reopen mechanism: every other slug keeps MAX_CORRECTION_ROUNDS.
REOPENED_ROUNDS = {
    "oxidative-nitrosative-stress": 3,
    "small-fibre-neuropathy": 2,
    # DECISIONS 2026-11-15/16 ("one new round for each of the seven"): one more round each, under the new path.
    "mast-cell-activation": 2,
    # DECISIONS 2026-11-16 (one added sentence; one more round for the last two cards): a third round for the first;
    # `herpesvirus-reactivation` keeps its unused round C2 (below).
    # DECISIONS 2026-11-16 (up to three check retries per round): a fourth round (C4) for the same card.
    # DECISIONS 2026-11-16 (three rubric clarifications): a fifth round (C5) for it, and a third (C3) for
    # `herpesvirus-reactivation`.
    "impaired-energy-production-after-exertion": 5,
    "brain-and-brainstem-mri-changes": 2,
    "orthostatic-intolerance-cerebral-blood-flow": 2,
    "hpa-axis-cortisol": 2,
    "herpesvirus-reactivation": 3,
}
# The safety valve for wording-only findings (DECISIONS 2026-11-15, "A safety valve for wording-only findings"): the
# stages of a correction attempt that can open it, in order. A key names the valve of one stage of one attempt
# (``correction-review``, ``card-review-revised``, ``audit``): the audits belong to the last attempt, so ``audit`` has
# no attempt suffix.
VALVE_STAGES = ("correction-review", "card-review", "audit")
# A logged exception (DECISIONS 2026-11-15, the `orthostatic-intolerance-cerebral-blood-flow` point): its two audit
# records of round C1 predate the classification, so a card-reviewer classifies them once; if every finding is wording,
# the audit-stage valve may run on that closed round. The value is the round. No other slug can use this.
CLASSIFICATION_EXCEPTION = {"orthostatic-intolerance-cerebral-blood-flow": 1}
# Check retries of a correction round (DECISIONS 2026-11-16): a failed attempt may be applied again this many times per
# round, shared by the round's attempts; the failed tries are kept as ``...-attempt<i>``.
MAX_CHECK_RETRIES = 3
# The attempts of a correction round, in order: the first, then up to MAX_REVISIONS revised attempts, each after a
# reject at the correction review or the whole-card review (DECISIONS 2026-11-15/16: while the decisive findings fall).
# Tags of files: C1, C1-revised, C1-revised2, ... C1-revised<MAX_REVISIONS>.
MAX_REVISIONS = 4
ATTEMPT_SUFFIXES = tuple("" if i == 0 else "-revised" if i == 1 else f"-revised{i}" for i in range(MAX_REVISIONS + 1))
# The regex group for the suffix of an attempt tag or file name (the first attempt has none).
ATTEMPT_RE = "(?:" + "|".join(re.escape(x) for x in ATTEMPT_SUFFIXES[1:]) + ")?"
Round_ = int | str
# A rubric excerpt in an audit record must be at least this long after normalisation (contract decision D5).
MIN_RUBRIC_CHARS = 20
BASE_BRANCH = "main"

Pmid = Annotated[str, StringConstraints(pattern=r"^\d+$")]
# A preprint with no PMID is named by its DOI: "doi:10.xxxx/..." (the study id it would have on a card).
PreprintId = Annotated[str, StringConstraints(pattern=r"^doi:10\.\S+$")]


class PipelineError(Exception):
    """A step cannot continue; the message says what to fix."""


# The free-text items a wording finding may name, in the translation-key style (``translations.english_items``): a
# sourced text of the card or a study's finding. Nothing else is free text: a level, a badge, a link's support, a case
# definition, a study's role or any number is structured, and a finding about one is decisive.
FREE_TEXT_TARGET = re.compile(
    r"^(?:core_claim"
    r"|(?:level_reason|contested_reason|subgroups|early_signals|badge_reasons\.(?:diagnostic_marker|explains_pem))\[\d+\]"
    r"|links\[\d+\](?:\.reason)?"
    r"|studies\[(?:pmid:\d+|doi:\S+)\]\.finding)$"
)


# What a finding of the correction path names, beyond the free-text items: the structured parts of a card (DECISIONS
# 2026-11-15/16: a correction touches only what a finding names). ``studies[<id>]`` alone, or with a field.
STRUCTURED_TARGET = re.compile(
    r"^(?:level|contested|badges\.(?:diagnostic_marker|explains_pem)|layer|links\[\d+\]"
    r"|studies\[(?:pmid:\d+|doi:\S+)\](?:\.[a-z_]+)?)$"
)


def valid_target(target: str) -> bool:
    """Whether ``target`` is one a finding of the correction path may name (free text, or a structured part)."""
    return FREE_TEXT_TARGET.match(target) is not None or STRUCTURED_TARGET.match(target) is not None


def is_correction_round(n: object) -> bool:
    """Whether a round value is a correction round: ``C1``, ``C2``, ..."""
    return isinstance(n, str) and re.fullmatch(r"C[1-9]\d*", n) is not None


def max_correction_rounds(slug: str) -> int:
    """How many correction rounds ``slug`` may have: ``REOPENED_ROUNDS`` for the two named cards, else the default."""
    return REOPENED_ROUNDS.get(slug, MAX_CORRECTION_ROUNDS)


def attempt_tag(n: str, revision: int = 0) -> str:
    """The tag of attempt ``revision`` (0 = the first) of round ``n`` (``C1``): ``C1``, ``C1-revised``,
    ``C1-revised2``, ... ``C1-revised<MAX_REVISIONS>``."""
    if not 0 <= revision <= MAX_REVISIONS:
        raise PipelineError(f"a round has at most {MAX_REVISIONS} revised attempts, not {revision}")
    return n + ATTEMPT_SUFFIXES[revision]


def _attempt_flag(tag: str) -> str:
    """The command-line flag that names attempt ``tag`` (with a leading space), empty for the first attempt."""
    found = re.search(r"-(revised\d?)$", tag)
    return f" --{found.group(1)}" if found else ""


def _add_revision_flags(parser: argparse.ArgumentParser, what: str) -> None:
    """``--revised``, ``--revised2``, ... ``--revised<MAX_REVISIONS>`` (at most one), read as ``args.revision``."""
    group = parser.add_mutually_exclusive_group()
    for i in range(1, MAX_REVISIONS + 1):
        group.add_argument(
            ATTEMPT_SUFFIXES[i].replace("-", "--", 1),
            dest="revision",
            action="store_const",
            const=i,
            default=0,
            help=f"{what}: revised attempt {i} of the round",
        )


def correction_number(n: str) -> int:
    """The k of ``C<k>`` (also of ``C<k>-revised<i>``, ``C<k>-pre`` and ``...-attempt1``)."""
    match = re.match(r"C([1-9]\d*)", n)
    assert match is not None, n
    return int(match.group(1))


def _round_tag(redraft: bool | str | None) -> str:
    """The part of a file name that names the round of an audit: ``-L`` (the redraft), ``-C1`` (a correction)."""
    if not redraft:
        return ""
    return f"-{REDRAFT}" if redraft is True else f"-{redraft}"


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


def _class_problem(klass: str | None, target: str | None) -> str | None:
    """A wording finding needs a target that names a free-text item (``FREE_TEXT_TARGET``)."""
    if klass == "wording" and (target is None or not FREE_TEXT_TARGET.match(target)):
        return (
            f"a wording finding needs a target naming a free-text item (core_claim, level_reason[n], "
            f"contested_reason[n], badge_reasons.<badge>[n], subgroups[n], early_signals[n], links[n], "
            f"studies[<id>].finding); got {target!r}"
        )
    return None


class _Classified(_M):
    """A finding or an audit part that says whether resolving it is `decisive` or `wording` (the safety valve).

    ``class`` is read as ``klass``. A record written before the valve has none: it reads as unclassified, which means
    the normal path."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    klass: Literal["decisive", "wording", "none"] | None = Field(default=None, alias="class")
    target: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _wording_target(self) -> _Classified:
        if (problem := _class_problem(self.klass, self.target)) is not None:
            raise ValueError(problem)
        return self


class Finding(_Classified):
    operation: Annotated[int, Field(strict=True, ge=0)] | None
    severity: Literal["must_fix", "advisory"]
    problem: NonEmptyStr
    fix: NonEmptyStr | None = None
    # The parts of the card the finding is about (the correction path: a must_fix needs them, `record-review`).
    targets: list[NonEmptyStr] | None = None

    @model_validator(mode="after")
    def _valid_targets(self) -> Finding:
        if bad := [t for t in self.targets or [] if not valid_target(t)]:
            raise ValueError(
                f"targets {bad!r} are not valid targets (docs/pipeline.md, 'Correcting a held-back draft')"
            )
        return self

    @model_validator(mode="after")
    def _no_none_class(self) -> Finding:
        if self.klass == "none":
            raise ValueError("a finding is `decisive` or `wording`; `none` is for an audit part that supports the card")
        return self


def _finding_dicts(findings: Sequence[Finding]) -> list[dict[str, Any]]:
    """Findings as written to a trail: the class, target and targets only when the finding has them."""
    out = []
    for f in findings:
        d = f.model_dump(mode="json", by_alias=True)
        extra = {k: v for k in ("class", "target", "targets") if (v := d.pop(k)) is not None}
        out.append(d | extra)
    return out


class AuditTargets(_M):
    """The targets of one objecting audit part, in the numbering of the draft (the ``--pre`` review fills them)."""

    record: NonEmptyStr
    part: Annotated[int, Field(strict=True, ge=0)]
    targets: Annotated[list[NonEmptyStr], Field(min_length=1)]

    @model_validator(mode="after")
    def _valid_targets(self) -> AuditTargets:
        if bad := [t for t in self.targets if not valid_target(t)]:
            raise ValueError(f"targets {bad!r} are not valid targets")
        return self


class ReviewFile(_M):
    card: Slug
    paper: StudyId | None = None  # None only in the review of a whole-card redraft (round L)
    verdict: Literal["accept", "reject"]
    findings: list[Finding]
    audit_targets: list[AuditTargets] | None = None  # only the `--pre` review of a correction round
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


class AuditPart(_Classified):
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

    def audit_context_path(self, slug: str, key: str | None = None, redraft: bool | str = False) -> Path:
        """``audit-context/<slug>-<key>.md`` for a change; ``audit-context/<slug>.md`` for a whole-card audit.

        The audit of the redraft (round L) adds ``-L`` to the name, that of a correction round ``-C<k>``."""
        return self.f("audit-context", f"{_stem(slug, key)}{_round_tag(redraft)}.md")

    def audit_path(self, slug: str, key: str | None, second: bool = False, redraft: bool | str = False) -> Path:
        """The record the auditor writes for a change; the consistency run writes ``...-second.yaml``.

        The audit of the redraft (round L) is ``<slug>-<key>-L.yaml`` (whole card: ``<slug>-L.yaml``); that of a
        correction round ``<slug>-C<k>.yaml``."""
        name = f"{_stem(slug, key)}{_round_tag(redraft)}{'-second' if second else ''}.yaml"
        return self.f("audit", name)

    def correction_context_path(self, slug: str, k: int) -> Path:
        """What `correction-plan` writes for the drafter: ``correction-context/<slug>-C<k>.md``."""
        return self.f("correction-context", f"{slug}-C{k}.md")

    def card_review_context_path(self, slug: str, n: str) -> Path:
        """What `card-review-plan` writes for the card-reviewer: ``card-review-context/<slug>-C<k>[-revised].md``."""
        return self.f("card-review-context", f"{slug}-{n}.md")

    def card_review_path(self, slug: str, n: str) -> Path:
        """The whole-card review of a correction attempt: ``review/<slug>-card-C<k>[-revised].json``."""
        return self.f("review", f"{slug}-card-{n}.json")

    def valve_path(self, slug: str, key: str, ending: str = ".json") -> Path:
        """The files of the valve of one stage: ``valve/<slug>-<key>.json`` (the fix operations) and ``-check.json``
        (the fix check); the text the operations give is ``valve_text_path``."""
        return self.f("valve", f"{slug}-{key}{ending}")

    def valve_text_path(self, slug: str, key: str) -> Path:
        """The text a valve fix gives: ``valve/<slug>-<key>/<slug>.yaml``, named for the card as the validator wants."""
        return self.f("valve", f"{slug}-{key}", f"{slug}.yaml")

    def valve_context_path(self, slug: str, key: str) -> Path:
        """What `valve-check-plan` writes for the card-reviewer: ``valve-check-context/<slug>-<key>.md``."""
        return self.f("valve-check-context", f"{slug}-{key}.md")

    def redraft_context_path(self, slug: str, key: str | None = None) -> Path:
        """What `redraft-plan` writes for the drafter: ``redraft-context/<slug>-<key>.md`` (whole card: no key)."""
        return self.f("redraft-context", f"{_stem(slug, key)}.md")

    @property
    def ledger_path(self) -> Path:
        """Which papers earlier runs have processed (gitignored, shared by all runs)."""
        return self.pipeline_dir / "processed.json"

    def f(self, *parts: str) -> Path:
        return self.run_dir.joinpath(*parts)

    def ops_path(self, slug: str, pmid: str | None, n: Round_) -> Path:
        return self.f("ops", f"{_stem(slug, pmid)}-r{n}.json")

    def checks_path(self, slug: str, pmid: str | None, n: Round_) -> Path:
        return self.f("checks", f"{_stem(slug, pmid)}-r{n}.json")

    def review_path(self, slug: str, pmid: str | None, n: Round_) -> Path:
        return self.f("review", f"{_stem(slug, pmid)}-r{n}.json")

    def applied_dir(self, slug: str, pmid: str | None, n: Round_) -> Path:
        return self.f("applied", f"{_stem(slug, pmid)}-r{n}")


def _stem(slug: str, key: str | None) -> str:
    """``<slug>-<key>`` for a pair; ``<slug>`` alone for a whole-card redraft (no paper, no key)."""
    return f"{slug}-{key}" if key else slug


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
    match = re.search(r"-(\d+|PPR\d+)-r(?:\d+|L)$", path.stem)
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


def redraft_ops_problems(ops: OpsFile, accepted_level: int | None, paper: str | None) -> list[str]:
    """E4: what a redraft (round L) operations file may hold. Empty when it holds nothing else.

    Only ``propose`` operations: exactly one on ``level``, whose value is the auditor's ``accepted_level``, plus at
    most one each on ``contested`` and the two badges. Its ``paper`` is the original paper (None for a whole card).
    """
    found: list[str] = []
    if ops.paper != paper:
        found.append(
            f"a redraft names {'paper ' + repr(paper) if paper else 'no paper'}, this file names {ops.paper!r}"
        )
    targets: list[str] = []
    for i, op in enumerate(ops.operations):
        if not isinstance(op, Propose):
            found.append(f"operations[{i}] is {op.op}: a redraft may hold propose operations only")
        else:
            targets.append(op.target)
    levels = [op for op in ops.operations if isinstance(op, Propose) and op.target == "level"]
    if len(levels) != 1:
        found.append(f"a redraft needs exactly one propose on level, found {len(levels)}")
    elif accepted_level is None or levels[0].value != accepted_level:
        found.append(f"the level proposed is {levels[0].value}, but the auditor accepted level {accepted_level}")
    if len(set(targets)) != len(targets):
        found.append("a redraft proposes each target (level, contested, badge) at most once")
    return found


def _check_applied(
    cfg: Config, slug: str, base: Path, base_text: str, new_text: str, out_dir: Path, result: dict[str, Any]
) -> None:
    """Write the applied card and its diff against ``base_text``, then run the card validator and the citations check
    on it; the findings go into ``result``."""
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
    _count, cite_issues = citations.check_paths([card_path], cfg.cache_dir, citations.ERROR)
    with tempfile.TemporaryDirectory() as tmp:
        baseline_path = Path(tmp) / f"{slug}.yaml"
        baseline_path.write_text(base_text, encoding="utf-8", newline="\n")
        _count, base_issues = citations.check_paths([baseline_path], cfg.cache_dir, citations.ERROR)
    known = {(i.study, i.code, i.message) for i in base_issues}
    rows = _citation_rows(cite_issues)
    for row in rows:
        row["preexisting"] = (row["study"], row["code"], row["message"]) in known
    result["citations"] = rows


def _new_errors(result: dict[str, Any]) -> list[dict[str, Any]]:
    """The citation findings of ``result`` that fail a check: new ones that are errors, and a new C9."""
    return [
        r for r in result["citations"] if not r["preexisting"] and (r["level"] == citations.ERROR or r["code"] == "C9")
    ]


def _finish_checks(cfg: Config, result: dict[str, Any], ops_errors: list[str], pmid: str | None, n: Round_) -> None:
    """Decide ``passed`` from the findings in ``result``, write ``checks/...json`` and log the call."""
    # A C9 issue (the group names no author of the record) is only a warning in `citations check`, but a new one
    # fails the pair here, so a drafter cannot add an author name that the record does not support.
    new_errors = _new_errors(result)
    result["citation_errors"] = len(new_errors)
    result["passed"] = not ops_errors and not result["validator"] and not new_errors
    _write_json(cfg.checks_path(result["card"], pmid, n), result)
    _log(
        cfg,
        {"event": "apply", "card": result["card"], "paper": result["paper"], "round": n, "passed": result["passed"]},
    )


def correction_ops_problems(ops: OpsFile, draft_level: int) -> list[str]:
    """A2: what the operations file of a correction round may hold. Empty when it holds nothing else.

    No paper; at least one operation; only ``replace_paragraph``, ``remove_paragraph``, ``update_study``,
    ``remove_link``, ``propose`` and ``add_sentence`` (see `add_sentence_problems`); a ``propose`` on ``level`` only
    to a value lower than the draft's, on a badge only to false, on ``contested`` freely. Nothing that adds a study or
    a paragraph: a correction removes or weakens a claim and adds only the one sentence an audit part asks for.
    """
    found: list[str] = []
    if ops.paper is not None:
        found.append(f"a correction names no paper, this file names {ops.paper!r}")
    if not ops.operations:
        found.append("a correction needs at least one operation")
    for i, op in enumerate(ops.operations):
        if isinstance(op, (AddStudy, AddParagraph)):
            found.append(
                f"operations[{i}] is {op.op}: a correction may hold replace_paragraph, remove_paragraph, "
                "update_study, remove_link, propose and add_sentence only (it adds no study and no paragraph)"
            )
        elif isinstance(op, Propose):
            if op.target == "level" and not (isinstance(op.value, int) and op.value < draft_level):
                found.append(
                    f"operations[{i}] proposes level {op.value}: a correction may only lower the level "
                    f"(the draft's is {draft_level})"
                )
            elif op.target in ("diagnostic_marker", "explains_pem") and op.value is not False:
                found.append(
                    f"operations[{i}] proposes {op.target} {op.value}: a correction may only set a badge to false"
                )
    return found


def objecting_audit_parts(cfg: Config, slug: str, before: int | None = None) -> list[tuple[str, int, AuditPart, str]]:
    """The objecting parts of the valid whole-card audit records the correction answers: (record file name, part
    index, part, the decision of the record). Objecting = the record does not accept and the part is not classed
    ``none`` (a part that supports the card). An invalid or unreadable record has no parts. With ``before`` k, the
    records of round ``C<k>`` and later (written after the step 0 review) are left out."""
    found: list[tuple[str, int, AuditPart, str]] = []
    for path in whole_card_audit_files(cfg, slug):
        if path.name.endswith("-invalid.yaml"):
            continue
        later = re.search(r"-C([1-9]\d*)(?:-second)?\.yaml$", path.name)
        if before is not None and later and int(later.group(1)) >= before:
            continue
        try:
            audit = AuditRecord.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (OSError, yaml.YAMLError, ValidationError):
            continue
        if audit.decision == "accept":
            continue
        found += [(path.name, i, part, audit.decision) for i, part in enumerate(audit.parts) if part.klass != "none"]
    return found


def _correction_op_targets(card: cards.Card, ops: OpsFile) -> tuple[list[str | None], dict[str, list[int]]]:
    """The target of each operation of a correction, in the numbering of the draft ``card`` (an earlier
    ``remove_paragraph`` does not shift a later index, as in `_valve_op_targets`), and for each paragraph field (the
    translation-key prefix) and for ``links`` the draft indices still there after the operations. A correction never
    adds a paragraph or a link, so that list maps the numbering of its applied text back to the draft's. An
    operation that does not resolve (an index out of range, an unknown link) has the target None: applying it fails
    by itself."""
    present: dict[str, list[int]] = {}
    links_left = list(range(len(card.links)))
    targets: list[str | None] = []
    for op in ops.operations:
        target: str | None = None
        if isinstance(op, (ReplaceParagraph, RemoveParagraph)):
            prefix = _TARGET_PREFIX[op.field]
            left = present.setdefault(prefix, list(range(len(_field_paras(card, op.field)))))
            if op.index < len(left):
                original = left[op.index]
                target = prefix if op.field == "core_claim" else f"{prefix}[{original}]"
                if isinstance(op, RemoveParagraph) and op.field != "core_claim":
                    del left[op.index]
        elif isinstance(op, UpdateStudy):
            target = f"studies[{op.id}]"
        elif isinstance(op, RemoveLink):
            index = next((i for i, link in enumerate(card.links) if link.to == op.to), None)
            if index is not None:
                target = f"links[{index}]"
                if index in links_left:
                    links_left.remove(index)
        elif isinstance(op, Propose):
            target = op.target if op.target in ("level", "contested") else f"badges.{op.target}"
        targets.append(target)
    return targets, present | {"links": links_left}


_INDEXED_TARGET = re.compile(
    r"^(core_claim|level_reason|contested_reason|subgroups|early_signals|badge_reasons\.\w+|links)\[(\d+)\](.*)$"
)


def _map_to_draft(target: str, survivors: dict[str, list[int]]) -> str | None:
    """A target in the numbering of an attempt's applied text, in the draft's numbering; None when it names a
    paragraph or link that is not in the draft's list (nothing is allowed then)."""
    match = _INDEXED_TARGET.match(target)
    if match is None or match.group(1) not in survivors:
        return target
    left, index = survivors[match.group(1)], int(match.group(2))
    return f"{match.group(1)}[{left[index]}]{match.group(3)}" if index < len(left) else None


def _finding_targets(review: ReviewFile | None) -> list[str]:
    """The targets of the ``must_fix`` findings of a review."""
    return [t for f in (review.findings if review else []) if f.severity == "must_fix" for t in f.targets or []]


def pre_targets(review: ReviewFile | None) -> set[str]:
    """What the audits and the step-0 review name, in the draft's numbering: the ``audit_targets`` of the ``--pre``
    review and the targets of its ``must_fix`` findings."""
    found = set(_finding_targets(review))
    for entry in (review.audit_targets if review else None) or []:
        found |= set(entry.targets)
    return found


def allowed_targets(cfg: Config, slug: str, tag: str, draft_card: cards.Card) -> set[str]:
    """The targets a correction attempt ``tag`` may change, in the draft's numbering: those of the step-0 review and,
    for a revised attempt, the targets of every ``must_fix`` finding of the reviews of the earlier attempts of the
    round, mapped from that attempt's applied numbering back to the draft's."""
    base = _round_base(tag)
    allowed = pre_targets(_load_card_review(cfg, slug, f"{base}-pre"))
    index = ATTEMPT_SUFFIXES.index(tag[len(base) :])
    for earlier in (base + suffix for suffix in ATTEMPT_SUFFIXES[:index]):
        r = _load_round(cfg, slug, "", earlier)
        survivors = _correction_op_targets(draft_card, r.ops)[1] if r is not None and r.ops is not None else {}
        for review in (r.review if r is not None else None, _load_card_review(cfg, slug, earlier)):
            allowed |= {m for t in _finding_targets(review) if (m := _map_to_draft(t, survivors)) is not None}
    return allowed


def _target_permitted(op: Any, target: str, allowed: set[str]) -> bool:
    """Whether a target a finding names permits operation ``op`` on ``target``: the target itself; for
    ``update_study`` a target of one of its fields; for ``remove_link`` the link's reason; for a badge ``propose``
    a paragraph of that badge's reason."""
    if target in allowed:
        return True
    if isinstance(op, UpdateStudy):
        return any(a.startswith(target + ".") for a in allowed)
    if isinstance(op, RemoveLink):
        return f"{target}.reason" in allowed
    if isinstance(op, Propose) and target.startswith("badges."):
        return any(a.startswith(f"badge_reasons.{op.target}[") for a in allowed)
    return False


def sentence_targets(card: cards.Card, tied: Sequence[str]) -> list[str]:
    """The items an ``add_sentence`` for an audit part may go to: each target the part is tied to (its own ``target``,
    its ``audit_targets``) and, for a structured one, the free-text item where the card explains it, in the draft's
    numbering: ``layer`` and ``level`` the last paragraph of ``level_reason``, ``contested`` the last of
    ``contested_reason`` (if any), ``badges.<b>`` the last of ``badge_reasons.<b>`` (if any), ``studies[<id>]`` and
    ``studies[<id>].<field>`` that study's ``finding``. Links stay out."""
    found: list[str] = []
    for target in tied:
        found.append(target)
        mapped = None
        if target in ("layer", "level"):
            mapped = ("level_reason", len(cards.paragraphs(card.level_reason)))
        elif target == "contested" and card.contested:
            mapped = ("contested_reason", len(cards.paragraphs(card.contested.reason)))
        elif target in ("badges.diagnostic_marker", "badges.explains_pem"):
            key = target.replace("badges.", "badge_reasons.")
            mapped = (key, len(_field_paras(card, target + ".reason")))
        elif m := re.match(r"^(studies\[[^\]]+\])(?:\.\w+)?$", target):
            found.append(m.group(1) + ".finding")
        if mapped and mapped[1]:
            found.append(f"{mapped[0]}[{mapped[1] - 1}]")
    return list(dict.fromkeys(found))


def add_sentence_problems(cfg: Config, slug: str, tag: str, ops: OpsFile, draft_card: cards.Card) -> list[str]:
    """S2: the ``add_sentence`` operations of attempt ``tag`` that the ruling of DECISIONS 2026-11-16 does not allow.

    Each must answer (a) an objecting part of an audit record the round answers (`objecting_audit_parts`), cite
    (b) only sources that part quotes and that are studies on the card, go (c) to the part's own ``target`` or to a
    target the step 0 review gives that part in ``audit_targets``, state no number that the part's quotes of those
    sources lack, and be (d) the only one for that part in the file. The free-text target and the one-sentence rule
    are the operation's own validation."""
    sentences = [(i, op) for i, op in enumerate(ops.operations) if isinstance(op, AddSentence)]
    if not sentences:
        return []
    base = _round_base(tag)
    parts = {(name, i): part for name, i, part, _d in objecting_audit_parts(cfg, slug, correction_number(tag))}
    pre = _load_card_review(cfg, slug, f"{base}-pre")
    given = {(e.record, e.part): set(e.targets) for e in (pre.audit_targets if pre is not None else None) or []}
    on_card = {study.id for study in draft_card.studies}
    seen: set[tuple[str, int]] = set()
    found: list[str] = []
    for i, op in sentences:
        key = (op.answers.record, op.answers.part)
        part = parts.get(key)
        if part is None:
            found.append(
                f"operations[{i}] answers {key[0]} part {key[1]}, which is not an objecting part of an audit record "
                "this round answers"
            )
            continue
        quoted = {e.source for e in part.evidence}
        if bad := [x for x in op.sources if x not in quoted or x not in on_card]:
            found.append(
                f"operations[{i}] cites {', '.join(bad)}, which that audit part does not quote (or the card does not "
                "cite)"
            )
        tied = [*([part.target] if part.target else []), *sorted(given.get(key, set()))]
        if op.target not in sentence_targets(draft_card, tied):
            found.append(
                f"operations[{i}] adds a sentence to {op.target}, which is neither the target of that audit part nor "
                "one the step 0 review gives it in audit_targets, nor the item that explains one of them"
            )
        numerals, numeral_problems = citations.free_text_numerals(op.text)
        quote_tokens = citations.source_number_tokens(
            " ".join(e.quote for e in part.evidence if e.source in op.sources)
        )
        found += [f"operations[{i}]: {problem}" for problem in numeral_problems]
        if missing := [n for n in dict.fromkeys(numerals) if n not in quote_tokens]:
            found.append(
                f"operations[{i}] states the number(s) {', '.join(missing)}, which are not in the quotes of that audit "
                "part for the sentence's sources"
            )
        if key in seen:
            found.append(f"operations[{i}] is a second added sentence for {key[0]} part {key[1]}: one per audit part")
        seen.add(key)
    return found


def correction_target_problems(cfg: Config, slug: str, tag: str, ops: OpsFile, draft_card: cards.Card) -> list[str]:
    """B3: the operations of attempt ``tag`` that change something no finding names (empty when none). An
    ``add_sentence`` has no target here: it is allowed only through `add_sentence_problems`."""
    allowed = allowed_targets(cfg, slug, tag, draft_card)
    targets, _survivors = _correction_op_targets(draft_card, ops)
    return [
        f"operations[{i}] changes {t}, which no finding names"
        for i, (op, t) in enumerate(zip(ops.operations, targets, strict=True))
        if t is not None and not _target_permitted(op, t, allowed)
    ] + add_sentence_problems(cfg, slug, tag, ops, draft_card)


def _draft_problem(cfg: Config, slug: str, base: str) -> str | None:
    """R8: the revised attempt applies to the draft the first attempt was applied to. Checked from what exists: the
    first attempt's operations applied to the draft must give its applied text, and a trail of the round in
    ``audits/`` must carry the draft's sha256. None when no check fails."""
    draft_path = cfg.drafts_dir / f"{slug}.yaml"
    draft_bytes = draft_path.read_bytes()
    first = _load_round(cfg, slug, "", base)
    applied = cfg.applied_dir(slug, None, base) / f"{slug}.yaml"
    if first is not None and first.ops is not None and applied.is_file():
        try:
            same = apply_operations(draft_bytes.decode("utf-8"), first.ops, validate=False) == applied.read_text(
                encoding="utf-8"
            )
        except OperationError:
            same = False
        if not same:
            return "the draft is not the one the first attempt was applied to (it changed since)"
    for path in correction_trails(cfg, slug):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if (
            isinstance(data, dict)
            and data.get("round") == correction_number(base)
            and data.get("draft_sha256") != _sha256(draft_bytes)
        ):
            return f"the draft is not the one {path.name} records (its sha256 differs)"
    return None


def _load_card_review(cfg: Config, slug: str, tag: str) -> ReviewFile | None:
    """The valid whole-card review of a correction attempt (``tag`` is ``C1`` or ``C1-revised``), or None."""
    path = cfg.card_review_path(slug, tag)
    if not path.is_file():
        return None
    try:
        review = ReviewFile.model_validate(_read_json(path))
    except (PipelineError, ValidationError):
        return None
    if review.card != slug or review.paper is not None:
        return None
    if tag.endswith("-pre") and _correction_review_target_problems(cfg, slug, review, True, tag):
        return None  # the step 0 review counts only when `record-review` would accept it (targets, audit_targets)
    return review


Reject = tuple[str, int]  # (kind of reject, number of decisive must_fix findings)


def _decisive_count(findings: Any) -> int:
    """How many ``must_fix`` findings (``Finding`` objects or trail dicts) are ``decisive`` or have no class."""
    count = 0
    for f in findings or []:
        severity, klass = (f.get("severity"), f.get("class")) if isinstance(f, dict) else (f.severity, f.klass)
        count += severity == "must_fix" and klass in ("decisive", None)
    return count


def _reject(cfg: Config, slug: str, tag: str) -> Reject | None:
    """How attempt ``tag`` was rejected: (``"correction review"``, decisive findings of that review), or
    (``"whole-card review"``, ...) when the correction review accepted and the whole-card review rejected; None when
    it was not rejected (or has no valid review yet, or the reject is wording only and goes through the valve)."""
    r = _load_round(cfg, slug, "", tag)
    if r is None or r.review is None:
        return None
    if r.review.verdict == "reject":
        if _review_valve_findings(r.review) is None:
            return "correction review", _decisive_count(r.review.findings)
        if not _valve_passed(cfg, slug, _valve_key("correction-review", tag)):
            return None  # a wording-only reject goes through the valve, not a revised attempt
    card_review = _load_card_review(cfg, slug, tag)
    if card_review is None or card_review.verdict != "reject":
        return None
    if _review_valve_findings(card_review) is not None:
        return None
    return "whole-card review", _decisive_count(card_review.findings)


# Written into every trail by the code of DECISIONS 2026-11-15/16: the round ran under the falling-decisive-count rule.
# A round whose trails lack it ran under the one-revision-per-kind rule (at most three attempts) and stays as it was.
REVISION_RULE = "falling-decisive"


def _revision_state(rejects: Sequence[Reject | None], falling: bool = True) -> tuple[bool, str | None]:
    """The rejects of the attempts of a round so far (the last attempt last): (whether the next attempt is open, why
    the round ends). Open when fewer than ``MAX_REVISIONS`` revisions exist and the last attempt was rejected, and
    either no earlier attempt was rejected by the same review, or the decisive findings of this reject are fewer than
    those of the most recent earlier reject of that review (DECISIONS 2026-11-15/16). The reason is None when the last
    attempt was not rejected at all."""
    if not rejects or rejects[-1] is None:
        return False, None
    kind, count = rejects[-1]
    if not falling:  # a round run before the rule: one revision per kind, at most -revised2
        used = any(r is not None and r[0] == kind for r in rejects[:-1])
        return (False, "the revision of that kind is used") if used or len(rejects) >= 3 else (True, None)
    if len(rejects) - 1 >= MAX_REVISIONS:
        return False, f"all {MAX_REVISIONS} revisions are used"
    earlier = [r[1] for r in rejects[:-1] if r is not None and r[0] == kind]
    if not earlier or count < earlier[-1]:
        return True, None
    return False, f"the decisive findings did not fall ({earlier[-1]}, then {count})"


def _revision_pending(rejects: Sequence[Reject | None]) -> bool:
    return _revision_state(rejects)[0]


def _revision_problem(cfg: Config, slug: str, base: str, tag: str) -> str | None:
    """Why attempt ``tag`` (``C1-revised``, ``C1-revised2``, ...) may not be made, or None: the attempts before it
    must each have been rejected, and the decisive findings must have fallen at each reject of a kind seen before."""
    index = ATTEMPT_SUFFIXES.index(tag[len(base) :])
    earlier = [base + suffix for suffix in ATTEMPT_SUFFIXES[:index]]
    rejects = [_reject(cfg, slug, t) for t in earlier]
    for j, t in enumerate(earlier):
        if rejects[j] is None:
            review = _load_round(cfg, slug, "", t)
            if review is not None and review.review is not None and _review_valve_findings(review.review) is not None:
                return f"the reject of {t} is wording only: it goes through the valve (`valve-apply`), not a revision"
            first = "first attempt's review" if j == 0 else f"review of {t}"
            return (
                f"the attempt {tag} needs the {first} of round {base}, and it must say reject "
                "(the correction review, or the whole-card review of that attempt)"
            )
        pending, why = _revision_state(rejects[: j + 1])
        if not pending:
            return (
                f"round {base} ends after the {rejects[j][0]} reject of {t} ({why}): "
                f"the round ends with no audit, there is no attempt {tag}"
            )
    return None


def _pending_flag(cfg: Config, slug: str, base: str) -> str | None:
    """The flag of the revised attempt that round ``base`` is waiting for (``--revised``, ``--revised2``, ...), or
    None when the last attempt was not rejected, or the revision is not open (`_revision_state`)."""
    chain = _attempt_chain(cfg, slug, base)
    if not _revision_pending([_reject(cfg, slug, t) for t in chain]):
        return None
    return _attempt_flag(base + ATTEMPT_SUFFIXES[len(chain)]).strip()


def _attempt_chain(cfg: Config, slug: str, base: str) -> list[str]:
    """The attempts of round ``base`` that have an ops file, in order (``C1``, ``C1-revised``, ...)."""
    chain: list[str] = []
    for suffix in ATTEMPT_SUFFIXES:
        if not cfg.ops_path(slug, None, base + suffix).is_file():
            break
        chain.append(base + suffix)
    return chain


def apply_correction_ops(cfg: Config, slug: str, ops_path: Path, n: str, *, revision: int = 0) -> dict[str, Any]:
    """`apply --round C<k> [--revised[2-4]]`: apply a correction's operations, check them (A2, A4).

    Writes ``checks/<slug>-rC<k>.json`` and ``applied/<slug>-rC<k>/`` as for other rounds. After failed checks the
    attempt may be applied again while the round has used fewer than ``MAX_CHECK_RETRIES`` retries (shared by its
    attempts); each failed try's ops, checks and errors files are kept as ``...-attempt<i>``, and a failed try writes
    ``checks/<slug>-rC<k>-errors.md`` (`_check_errors_text`) for the drafter.
    After a review reject the drafter gets a revised attempt (``--revised``, ``--revised2``, ...,
    files ``...-rC<k>-revised<i>...``) while fewer than ``MAX_REVISIONS`` exist and the decisive findings fell since
    the last reject of the same review (`_revision_state`). The draft in ``drafts/`` is never touched.
    """
    base = n
    n = attempt_tag(base, revision)
    k = correction_number(n)
    draft = cfg.drafts_dir / f"{slug}.yaml"
    if (cfg.cards_dir / f"{slug}.yaml").exists():
        raise PipelineError(f"{cfg.cards_dir / f'{slug}.yaml'} exists: only a held-back draft can be corrected")
    if not draft.is_file():
        raise PipelineError(f"no draft {draft} to correct")
    used, _open = correction_round_state(cfg, slug)
    if k != used + 1 or k > max_correction_rounds(slug):
        raise PipelineError(
            f"correction round {base} is not allowed: the next round is C{used + 1}, "
            f"and a card gets at most {max_correction_rounds(slug)} correction round(s)"
        )
    expected = cfg.ops_path(slug, None, n)
    if ops_path.resolve() != expected.resolve():
        raise PipelineError(f"the ops file of correction round {n} must be {expected}")
    if n != base:
        if problem := _revision_problem(cfg, slug, base, n):
            raise PipelineError(problem)
        if problem := _draft_problem(cfg, slug, base):
            raise PipelineError(problem)
    checks_file = cfg.checks_path(slug, None, n)
    kept = _kept_tries(cfg, slug, n)
    attempt = kept + 1  # the try of this attempt tag (the next one when its checks failed)
    if checks_file.exists():
        if _read_json(checks_file).get("passed"):
            raise PipelineError(f"correction round {n} passed its checks; it is not applied a second time")
        if _check_retries_used(cfg, slug, base) >= MAX_CHECK_RETRIES:
            raise PipelineError(
                f"all {MAX_CHECK_RETRIES} check retries of round {base} are used: a further try after failed "
                "checks is refused, the round ends"
            )
        # the last try failed; keep its record (and its errors file), this is the next try
        checks_file.replace(cfg.checks_path(slug, None, f"{n}-attempt{attempt}"))
        errors_file = _errors_path(cfg, slug, n)
        if errors_file.exists():
            errors_file.replace(_errors_path(cfg, slug, f"{n}-attempt{attempt}"))
        shutil.rmtree(cfg.applied_dir(slug, None, n), ignore_errors=True)
        attempt += 1

    ops: OpsFile | None = None
    ops_errors: list[str] = []
    draft_text = draft.read_text(encoding="utf-8")
    try:
        ops = parse_ops(_read_json(ops_path))
        if ops.card != slug:
            ops_errors.append(f"the ops file is for card '{ops.card}', not '{slug}'")
        draft_card = _load_card(draft)
        ops_errors += correction_ops_problems(ops, draft_card.level)
        ops_errors += correction_target_problems(cfg, slug, n, ops, draft_card)
    except (PipelineError, OperationError) as exc:
        ops_errors.append(str(exc))
    result: dict[str, Any] = {
        "card": slug,
        "paper": None,
        "key": None,
        "round": n,
        "attempt": attempt,
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
    new_text: str | None = None
    if ops is not None and not ops_errors:
        op_tiers = tiers(ops, yaml.safe_load(draft_text))
        result["tiers"] = {str(t): op_tiers.count(t) for t in (1, 2)}
        try:
            new_text = apply_operations(draft_text, ops, validate=False)
        except OperationError as exc:
            ops_errors.append(str(exc))
        else:
            if new_text == draft_text:
                ops_errors.append("the correction changes nothing: the applied text equals the draft")
                new_text = None
    if new_text is not None:
        _check_applied(cfg, slug, draft, draft_text, new_text, cfg.applied_dir(slug, None, n), result)
    _finish_checks(cfg, result, ops_errors, None, n)
    if not result["passed"]:
        used = _check_retries_used(cfg, slug, base)
        left = MAX_CHECK_RETRIES - used
        errors_file = _errors_path(cfg, slug, n)
        _write_text(errors_file, _check_errors_text(cfg, slug, base, n, result, left))
        result["errors_file"] = str(errors_file)
        if left > 0 and ops_path.is_file():
            # the drafter rewrites the ops file for the retry; keep this one
            shutil.copyfile(ops_path, cfg.ops_path(slug, None, f"{n}-attempt{attempt}"))
    return result


def _kept_tries(cfg: Config, slug: str, tag: str) -> int:
    """How many failed tries of attempt ``tag`` are kept as ``<tag>-attempt<i>`` checks files (each is one retry)."""
    return sum(1 for i in range(1, MAX_CHECK_RETRIES + 1) if cfg.checks_path(slug, None, f"{tag}-attempt{i}").exists())


def _check_retries_used(cfg: Config, slug: str, base: str) -> int:
    """The check retries round ``base`` has used, over all its attempts (a file ``...-attempt1`` of a round run under
    the one-retry rule counts as one)."""
    return sum(_kept_tries(cfg, slug, base + suffix) for suffix in ATTEMPT_SUFFIXES)


def _errors_path(cfg: Config, slug: str, tag: str) -> Path:
    path = cfg.checks_path(slug, None, tag)
    return path.with_name(f"{path.stem}-errors.md")


_OPS_LOCATION = re.compile(r"operations\[\d+\]")
_VALIDATOR_LINE = re.compile(r"^.+?\.yaml: (?P<path>.*?): \[[^\]]+\] ", re.DOTALL)


def _check_errors_text(cfg: Config, slug: str, base: str, tag: str, result: dict[str, Any], left: int) -> str:
    """``checks/<slug>-r<tag>-errors.md``: every error that failed the try (ops problems, validator issues, new
    citation errors), as rule, location and the message of the checks file; no warnings, no preexisting problems."""
    rows: list[tuple[str, str, str]] = []
    for message in result["ops_errors"]:
        found = _OPS_LOCATION.search(message)
        rows.append(("ops", found.group(0) if found else "(the ops file)", message))
    for message in result["validator"]:
        found = _VALIDATOR_LINE.match(message)
        rows.append(("validator", found.group("path") if found else "(see the message)", message))
    for row in _new_errors(result):
        rows.append((row["code"], row["study"], row["message"]))
    lines = [
        f"# Check errors of {cfg.checks_path(slug, None, tag).name}",
        "",
        "These errors made the checks fail. Fix exactly these and change nothing else.",
        (
            f"Check retries left in round {base}: {left} of {MAX_CHECK_RETRIES}."
            if left > 0
            else f"Check retries left in round {base}: none (all {MAX_CHECK_RETRIES} are used)."
        ),
        "",
    ]
    for i, (rule, location, message) in enumerate(rows, 1):
        lines += [f"{i}. rule: {rule}", f"   location: {location}", "   message: " + message.replace("\n", "\n   ")]
    return "\n".join(lines) + "\n"


def apply_ops_file(
    cfg: Config,
    slug: str,
    ops_path: Path,
    n: Round_,
    *,
    audit_file: Path | None = None,
    revision: int = 0,
) -> dict[str, Any]:
    """Validate and apply one ops file to a copy of the card; run the validator and the citations check.

    Writes ``checks/<slug>-<pmid>-r<n>.json`` and, when the operations applied, ``applied/<slug>-<pmid>-r<n>/``
    with the new card and a diff. The draft in ``drafts/`` is never touched. Returns the checks record.

    Round ``L`` (the redraft after an auditor's ``accept_lower``) applies on top of the last applied round of the
    pair, enforces E4 (`redraft_ops_problems`) against the first audit's ``accepted_level`` and diffs the result
    against the card. A whole-card redraft names no paper (``audit_file`` is then the first audit's record).
    """
    if revision and not is_correction_round(n):
        raise PipelineError("--revised, --revised2, ... are only for a correction round (--round C<k>)")
    if is_correction_round(n):
        return apply_correction_ops(cfg, slug, ops_path, str(n), revision=revision)
    redraft = n == REDRAFT
    pmid = _pmid_from_name(ops_path)
    ops: OpsFile | None = None
    ops_errors: list[str] = []
    raw: Any = None
    paper_id: str | None = None
    whole_card = False
    try:
        raw = _read_json(ops_path)
        ops = parse_ops(raw)
        if ops.paper is None:
            whole_card = redraft
            pmid = None
            if not redraft:
                ops_errors.append("the ops file names no paper (only the redraft of a whole-card audit may)")
        elif ops.paper.startswith("pmid:"):
            pmid = ops.paper.removeprefix("pmid:")
        else:
            try:
                pmid, paper_id = resolve_paper(cfg, ops.paper)
            except PipelineError as exc:
                ops_errors.append(str(exc))
        if ops.card != slug:
            ops_errors.append(f"the ops file is for card '{ops.card}', not '{slug}'")
        ops_errors += [
            f"operations[{i}] is {op.op}: only a correction round (--round C<k>) may use it"
            for i, op in enumerate(ops.operations)
            if op.op in CORRECTION_ONLY_OPS
        ]
        ops_errors += [
            f"operations[{i}] is replace_paragraph of core_claim: only a correction round (--round C<k>) may use it"
            for i, op in enumerate(ops.operations)
            if isinstance(op, ReplaceParagraph) and op.field == "core_claim"
        ]
    except (PipelineError, OperationError) as exc:
        ops_errors.append(str(exc))
        if redraft and isinstance(raw, dict) and raw.get("paper") is None:
            whole_card, pmid = True, None
        elif pmid is None and isinstance(raw, dict):
            candidate = str(raw.get("paper", "")).removeprefix("pmid:")
            pmid = candidate if candidate.isdigit() else None
    if pmid is None and not whole_card:
        raise PipelineError("cannot tell which paper the ops file is for; " + "; ".join(ops_errors))
    if redraft and (cfg.checks_path(slug, pmid, REDRAFT).exists() or cfg.applied_dir(slug, pmid, REDRAFT).exists()):
        # At most one redraft: an existing round L is a hard stop, never overwritten.
        raise PipelineError("round L already exists for this pair; there is no further round")
    if paper_id is None and pmid is not None:
        paper_id = ops.paper if ops is not None and (ops.paper or "").startswith("doi:") else f"pmid:{pmid}"

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
    start_text = base_text  # what the operations are applied to: the card, or in round L the last applied round

    if redraft and ops is not None and not ops_errors:
        audit_record: AuditRecord | None = None
        why = "no audit record"
        if whole_card:
            if audit_file is None:
                why = "a whole-card redraft needs the first audit's record (--audit PATH)"
            else:
                try:
                    audit_record = validate_audit_record(
                        cfg,
                        yaml.safe_load(audit_file.read_text(encoding="utf-8")),
                        slug=slug,
                        key=None,
                        source=audit_file,
                        context_path=cfg.audit_context_path(slug),
                    )
                except (OSError, yaml.YAMLError, PipelineError) as exc:
                    why = "; ".join(str(exc).splitlines())
        else:
            assert pmid is not None
            audit_record, why = load_audit(cfg, slug, pmid)
        if audit_record is None or audit_record.decision != "accept_lower":
            found = audit_record.decision if audit_record is not None else why
            ops_errors.append(f"a redraft needs a valid audit record that says accept_lower; found: {found}")
        else:
            ops_errors += redraft_ops_problems(ops, audit_record.accepted_level, None if whole_card else paper_id)
        if not whole_card and not ops_errors:
            assert pmid is not None
            try:
                previous = _last_applied_round(cfg, slug, pmid)
            except PipelineError as exc:
                ops_errors.append(str(exc))
            else:
                start_text = (cfg.applied_dir(slug, pmid, previous) / f"{slug}.yaml").read_text(encoding="utf-8")

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
                new_text = apply_operations(start_text, ops, validate=False)
            except OperationError as exc:
                ops_errors.append(str(exc))

    if new_text is not None:
        _check_applied(cfg, slug, base, base_text, new_text, cfg.applied_dir(slug, pmid, n), result)
    _finish_checks(cfg, result, ops_errors, pmid, n)
    return result


# ---------------------------------------------------------------------------
# record-review
# ---------------------------------------------------------------------------


def _missing_target_problems(card: cards.Card, where: str, targets: Sequence[str]) -> list[str]:
    """The targets that name something ``card`` does not have: an indexed item out of range, a study id not on the
    card. ``level``, ``contested``, the badges and ``layer`` always exist."""
    counts = {
        "core_claim": 1,
        "level_reason": len(cards.paragraphs(card.level_reason)),
        "contested_reason": len(cards.paragraphs(card.contested.reason)) if card.contested else 0,
        "badge_reasons.diagnostic_marker": len(_field_paras(card, "badges.diagnostic_marker.reason")),
        "badge_reasons.explains_pem": len(_field_paras(card, "badges.explains_pem.reason")),
        "subgroups": len(card.subgroups),
        "early_signals": len(card.early_signals),
        "links": len(card.links),
    }
    ids = {study.id for study in card.studies}
    found = []
    for target in dict.fromkeys(targets):
        if (m := _INDEXED_TARGET.match(target)) and m.group(1) != "core_claim":
            n = counts[m.group(1)]
            if int(m.group(2)) >= n:
                found.append(f"target {target} does not exist in {where}: {m.group(1)} has {n} item(s)")
        elif (m := re.match(r"^studies\[([^\]]+)\]", target)) and m.group(1) not in ids:
            found.append(f"target {target} does not exist in {where}: study {m.group(1)} is not on the card")
    return found


def _correction_review_target_problems(cfg: Config, slug: str, review: ReviewFile, pre: bool, tag: str) -> list[str]:
    """B1, B2: every ``must_fix`` of a correction-path review carries ``targets`` (and a ``target`` is one of them);
    the ``--pre`` review holds ``audit_targets`` for exactly the objecting parts of the audit records, no other.
    Every target names something that exists: in the draft for the ``--pre`` review, in the applied text of the
    attempt for a correction review or a whole-card review."""
    k = correction_number(tag)
    problems = [
        f"findings[{i}] is a must_fix without `targets`: name the parts of the card it is about (a non-empty list)"
        for i, f in enumerate(review.findings)
        if f.severity == "must_fix" and not f.targets
    ]
    problems += [
        f"findings[{i}].target {f.target!r} is not one of its `targets`"
        for i, f in enumerate(review.findings)
        if f.target is not None and f.targets and f.target not in f.targets
    ]
    text_path = cfg.drafts_dir / f"{slug}.yaml" if pre else cfg.applied_dir(slug, None, tag) / f"{slug}.yaml"
    if text_path.is_file():
        try:
            on_card = _load_card(text_path)
        except (OSError, PipelineError, ValidationError, yaml.YAMLError):
            on_card = None
        if on_card is not None:
            named = [t for f in review.findings for t in f.targets or []]
            named += [t for e in review.audit_targets or [] for t in e.targets]
            where = "the draft" if pre else f"the applied text of {tag}"
            problems += _missing_target_problems(on_card, where, named)
    if not pre:
        if review.audit_targets is not None:
            problems.append("`audit_targets` belongs to the --pre review only")
        return problems
    expected = {(name, i) for name, i, _part, _decision in objecting_audit_parts(cfg, slug, k)}
    seen: set[tuple[str, int]] = set()
    for j, entry in enumerate(review.audit_targets or []):
        key = (entry.record, entry.part)
        if key not in expected:
            problems.append(f"audit_targets[{j}] ({entry.record} part {entry.part}) is not an objecting audit part")
        elif key in seen:
            problems.append(f"audit_targets[{j}] repeats {entry.record} part {entry.part}")
        seen.add(key)
    problems += [
        f"audit_targets has no entry for {name} part {i}: give its targets" for name, i in sorted(expected - seen)
    ]
    return problems


def record_review(
    cfg: Config, slug: str, pmid: str | None, n: Round_, *, card_review: bool = False, pre: bool = False
) -> ReviewFile:
    """Validate a review file. With ``card_review`` it is the whole-card review of a correction attempt
    (``review/<slug>-card-C<k>[-revised|-revised2].json``, no paper). With ``pre`` (``n`` is ``C<k>-pre``) it is the
    whole-card review of the unchanged draft before the correction: there is no ops file, so no finding names an
    operation."""
    path = cfg.card_review_path(slug, str(n)) if card_review else cfg.review_path(slug, pmid, n)
    raw = _read_json(path)
    try:
        review = ReviewFile.model_validate(raw)
    except ValidationError as exc:
        raise PipelineError(f"{path} is malformed:\n" + "\n".join(_pydantic_lines(exc))) from exc
    problems = []
    if review.card != slug:
        problems.append(f"card is '{review.card}', expected '{slug}'")
    expected = _paper_id_of_key(cfg, pmid) if pmid is not None else None
    if review.paper != expected:
        problems.append(f"paper is {review.paper!r}, expected {expected!r}")
    ops_path = cfg.ops_path(slug, pmid, n)
    count: int | None = None
    if pre:
        for i, finding in enumerate(review.findings):
            if finding.operation is not None:
                problems.append(f"findings[{i}].operation must be null: there are no operations before the correction")
    else:
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
    if not pre and re.fullmatch(rf"C[1-9]\d*{ATTEMPT_RE}", str(n)):  # a correction review: the valve needs the class
        problems += [
            f"findings[{i}] is a must_fix without `class`: say `decisive` or `wording` (and a `target` for wording)"
            for i, finding in enumerate(review.findings)
            if finding.severity == "must_fix" and finding.klass is None
        ]
    if pre or re.fullmatch(rf"C[1-9]\d*{ATTEMPT_RE}", str(n)):
        problems += _correction_review_target_problems(cfg, slug, review, pre, str(n))
    if problems:
        raise PipelineError(f"{path} is not valid:\n" + "\n".join(problems))
    event = {"event": "record-review", "card": slug, "paper": review.paper, "round": n, "verdict": review.verdict}
    _log(cfg, event | ({"card_review": True} if card_review else {}) | ({"pre": True} if pre else {}))
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


ABSTRACT_ONLY_NOTE = "Abstract only (not a carrier of the level, a badge or the contested mark)."
FULLTEXT_NOT_CACHED_NOTE = (
    "FULL TEXT NOT CACHED: only the abstract is given. A statement on the card that is not in this abstract may "
    "stand in the full text; it cannot be checked here."
)


def carrier_ids(card: cards.Card) -> set[str]:
    """E1: the study ids cited in ``level_reason``, ``contested.reason`` and the reason of each badge.

    These are the sources that carry the level, a badge or the contested mark; the auditor gets their full text.
    """
    found: list[str] = cards.reason_sources(card.level_reason)
    if card.contested is not None:
        found += cards.reason_sources(card.contested.reason)
    found += cards.reason_sources(card.badges.diagnostic_marker.reason)
    found += cards.reason_sources(card.badges.explains_pem.reason)
    return set(found)


def _audit_record_lines(cfg: Config, study_id: str, loader: FullTextLoader, carrier: bool) -> list[str]:
    """One cited record for the audit context: its fields and abstract; for a carrier (E1) also its full text, uncut.

    A study that is not a carrier gets the abstract only (the full text is not even loaded). A carrier with no cached
    full text gets the abstract and the statement ``FULLTEXT_NOT_CACHED_NOTE`` (E2).
    """
    lines = [f"### Record: {study_id}", ""]
    if study_id.startswith("pmid:"):
        pmid = study_id.removeprefix("pmid:")
        record = _record(cfg, pmid)
        full = loader(pmid, record.pmcid) if carrier else None
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
        full = loader(pre.ppr_id, pre.pmcid, preprint=pre) if carrier else None
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
    if not carrier:
        lines.append(ABSTRACT_ONLY_NOTE)
    elif full is None or full.xml is None:
        lines.append(FULLTEXT_NOT_CACHED_NOTE)
        if full is not None:
            lines.append(f"(Why: {full.note}.)")
    else:
        text = europepmc.article_text(full.xml)
        lines.append(f"Source: {full.note}. The reference list is left out.")
        lines.append(f"Not truncated ({len(text)} characters).")
        lines += ["", text]
    lines.append("")
    return lines


def strip_yaml_comments(text: str) -> str:
    """The YAML without its comments, in a stable form: parsed and dumped again.

    Comments in a card carry earlier drafter and reviewer reasoning and earlier rulings, which the auditor must not
    see. Parsing drops every comment (full-line or trailing) and keeps a ``#`` that is part of a value.
    """
    return yaml.safe_dump(
        yaml.safe_load(text), sort_keys=False, allow_unicode=True, default_flow_style=False, width=100
    ).rstrip("\n")


def build_audit_context(
    cfg: Config,
    slug: str,
    key: str | None,
    loader: FullTextLoader,
    *,
    redraft: bool = False,
    card_text_from: Path | None = None,
) -> str:
    """The one file the auditor reads: the diff, the card, the cited cached records, the rubric and the card format.

    ``key`` names a change in this run (the diff of its last round); ``None`` is a whole-card audit (the card file
    takes the diff's place). With ``redraft`` the change is the one redraft (round L) after an ``accept_lower``: the
    diff of its applied result against the card (E5). Nothing the drafter or the reviewer wrote, and no earlier
    audit, is in it.

    ``card_text_from`` (a whole-card audit only) takes the card text from that file instead of the card file, and
    nothing else changes: the context is built exactly as for the card file, so it does not show that the text is a
    correction. The card is still named by the card file's path.
    """
    base = _base_card(cfg, slug)
    source = card_text_from if card_text_from is not None and key is None and not redraft else base
    base_card = _load_card(source)
    base_text = strip_yaml_comments(source.read_text(encoding="utf-8"))
    study_ids = [s.id for s in base_card.studies]
    carriers = carrier_ids(base_card)
    if key is not None or redraft:
        paper_id = _paper_id_of_key(cfg, key) if key is not None else None
        n: Round_ = REDRAFT if redraft else _last_applied_round(cfg, slug, key or "")
        applied = cfg.applied_dir(slug, key, n)
        if not (applied / f"{slug}.yaml").is_file():
            raise PipelineError(f"no applied result in {applied}; run `apply` first")
        # The diff is built from the comment-free texts, not read from changes.diff (which shows comments).
        applied_text = strip_yaml_comments((applied / f"{slug}.yaml").read_text(encoding="utf-8"))
        diff = "".join(
            difflib.unified_diff(
                (base_text + "\n").splitlines(keepends=True),
                (applied_text + "\n").splitlines(keepends=True),
                fromfile=f"{base}",
                tofile=f"applied/{slug}.yaml",
            )
        )
        applied_card = _load_card(applied / f"{slug}.yaml")
        study_ids += [s.id for s in applied_card.studies]
        carriers = carrier_ids(applied_card)  # E1: the carriers of the card once the change is in
        what = f"the change from paper `{paper_id}`" if paper_id else "the redraft of the whole card"
        subject = f"card `{slug}` and {what} (round {n})"
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
            records += _audit_record_lines(cfg, study_id, loader, study_id in carriers)
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


def _abstract_only_ids(context: str) -> set[str]:
    """The ids of the records in section 3 that the context gives as abstract only (not carriers, E1)."""
    start = context.find("\n## 3. Cited records")
    end = context.find("\n## 4. ", start)
    if start < 0 or end < 0:
        return set()
    found: set[str] = set()
    for block in re.split(r"(?m)^(?=### )", context[start:end]):
        match = _RECORD_HEADING.match(block)
        if match and ABSTRACT_ONLY_NOTE in block:
            found.add(match.group(1).lower())
    return found


def _record_quote_text(reader: citations.CacheReader, study_id: str, *, abstract_only: bool = False) -> str | None:
    """Title, abstract and cached full text of a study, for the verbatim quote check; None if no cached record.

    With ``abstract_only`` (a record the context gave as abstract only) the full text is left out: the auditor was
    not shown it, so a quote from it cannot be checked against what it read.
    """
    pieces: list[str] = []
    if study_id.startswith("pmid:"):
        record = reader.record(study_id.removeprefix("pmid:"))
        if isinstance(record, str):
            return None
        pieces += [record.title, record.abstract or ""]
        full = None if abstract_only else reader.fulltext(record.pmid)
    else:
        try:
            pre = reader.preprint(study_id)
        except europepmc.EuropePmcError:
            return None
        if pre is None:
            return None
        pieces += [pre.title, _TAG_RE.sub(" ", pre.abstract) if pre.abstract else ""]
        full = None if abstract_only else reader.preprint_fulltext(pre)
    if isinstance(full, str):
        pieces.append(full)
    return "\n".join(pieces)


def _proposed_level(cfg: Config, slug: str, key: str | None, redraft: bool | str = False) -> int:
    """The level an accept_lower must be below: the level in the last applied result of a change (the redraft's
    applied result in round L, the corrected card's in a correction round), or the card's own for a whole-card
    audit."""
    if redraft:
        path = cfg.applied_dir(slug, key, REDRAFT if redraft is True else redraft) / f"{slug}.yaml"
    elif key is not None:
        path = cfg.applied_dir(slug, key, _last_applied_round(cfg, slug, key)) / f"{slug}.yaml"
    else:
        path = _base_card(cfg, slug)
    return _load_card(path).level


def _sibling(path: Path, ending: str) -> Path:
    """``<name>.yaml`` to ``<name><ending>`` beside it (``.invalid-1.yaml``, ``.retry.md``)."""
    return path.with_name(path.stem + ending)


def _retry_problem(source: Path, record: AuditRecord) -> str | None:
    """B3: a record written after a format retry may not change the answer of the invalid one beside it."""
    invalid = _sibling(source, ".invalid-1.yaml")
    if not invalid.is_file():
        return None
    try:
        earlier = yaml.safe_load(invalid.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(earlier, dict) or earlier.get("decision") not in AUDIT_DECISIONS:
        return None
    if earlier["decision"] != record.decision:
        return (
            f"a format retry cannot change the answer: the invalid record decided {earlier['decision']}, "
            f"this one decides {record.decision}"
        )
    level = earlier.get("accepted_level")
    if level is not None and level != record.accepted_level:
        return (
            f"a format retry cannot change the answer: the invalid record accepted level {level}, "
            f"this one {record.accepted_level}"
        )
    return None


def _class_problems(record: AuditRecord) -> list[str]:
    """The valve's classification of a new audit record of a correction round (V1)."""
    objecting = [p for p in record.parts if p.klass in ("decisive", "wording")]
    if record.decision == "reject":
        found = [
            f"parts[{i}] has no `class`: say `decisive`, `wording` or `none` (a part that supports the card)"
            for i, part in enumerate(record.parts)
            if part.klass is None
        ]
        if not objecting and not found:
            found.append("a reject needs at least one part with class `decisive` or `wording`")
        return found
    if objecting:
        return [f"a record that decides {record.decision} has no objecting part: leave `class` out or use `none`"]
    return []


def validate_audit_record(
    cfg: Config,
    raw: Any,
    *,
    slug: str,
    key: str | None,
    source: Path,
    context_path: Path,
    redraft: bool | str = False,
    require_class: bool = False,
) -> AuditRecord:
    """Check an audit record against its context file and the cache; raise PipelineError listing every problem.

    Checked: the schema; the card and paper are the ones audited; ``accepted_level`` is below the proposed (or
    current) level; every evidence ``source`` is a record in the context file and every ``quote`` is found word for
    word (the narrow normalisation of the citation check) in that record's cached text; every part's ``rubric`` is
    a verbatim excerpt (at least ``MIN_RUBRIC_CHARS`` characters) of functional spec section 2 or 3. With
    ``require_class`` (a new record of a correction round) every part of a ``reject`` says ``class`` (``decisive``,
    ``wording`` or ``none`` for a part that supports the card) with at least one objecting part, and an ``accept``
    has no objecting part; a record written before the valve is read without it, as unclassified.
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
        ceiling = _proposed_level(cfg, slug, key, redraft)
        if record.accepted_level is not None and record.accepted_level >= ceiling:
            problems.append(f"accepted_level {record.accepted_level} must be lower than the level {ceiling}")
    if require_class:
        problems += _class_problems(record)
    cited = _context_record_ids(context)
    abstract_only = _abstract_only_ids(context)
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
                texts[ev.source] = _record_quote_text(
                    reader, ev.source, abstract_only=ev.source.lower() in abstract_only
                )
            text = texts[ev.source]
            if text is None:
                problems.append(f"{where}: no cached record for {ev.source} to check the quote against")
            elif citations.normalise_quote(ev.quote) not in citations.normalise_quote(text):
                problems.append(f"{where}.quote is not found word for word in the cached record of {ev.source}")
    if not problems and (conflict := _retry_problem(source, record)) is not None:
        problems.append(conflict)
    if problems:
        raise PipelineError(f"{source} is not valid:\n" + "\n".join(problems))
    return record


def _missing_record_note(path: Path) -> str:
    """Why there is no audit record at ``path``: never written, or it failed validation (once or twice)."""
    if _sibling(path, ".invalid-2.yaml").is_file():
        return (
            f"the record {path.name} failed validation twice "
            f"(the format retry is used; {_sibling(path, '.invalid-2.yaml').name})"
        )
    if _sibling(path, ".invalid-1.yaml").is_file():
        return (
            f"the record {path.name} failed validation and no format retry was recorded "
            f"({_sibling(path, '.invalid-1.yaml').name})"
        )
    return f"no audit record {path.name}"


def load_audit(
    cfg: Config, slug: str, key: str, *, second: bool = False, redraft: bool | str = False
) -> tuple[AuditRecord | None, str | None]:
    """The valid audit record of a change (of its redraft, round L, with ``redraft``), or (None, why it is missing
    or invalid)."""
    path = cfg.audit_path(slug, key, second, redraft)
    if not path.is_file():
        return None, _missing_record_note(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        record = validate_audit_record(
            cfg,
            raw,
            slug=slug,
            key=key,
            source=path,
            context_path=cfg.audit_context_path(slug, key, redraft),
            redraft=redraft,
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
    redraft: bool | str = False,
    retry: bool = False,
) -> AuditRecord:
    """Validate the record the auditor wrote and log it. A change is ``slug`` and ``key`` (the file is
    ``audit/<slug>-<key>.yaml``, or ``...-second.yaml``); a whole card is ``slug`` with ``key`` None and ``file``.
    With ``redraft`` the record is the audit of the redraft (round L): ``audit/<slug>-<key>-L.yaml`` and the
    context ``audit-context/<slug>-<key>-L.md``; ``redraft="C1"`` is the audit of correction round C1.

    A record that fails validation is kept as ``<name>.invalid-1.yaml`` and ``<name>.retry.md`` is written (B3): one
    format retry follows (``retry=True``, implied when ``invalid-1`` exists); its failure is final
    (``<name>.invalid-2.yaml``).
    """
    if key is not None:
        path = file or cfg.audit_path(slug, key, second, redraft)
        context_path = cfg.audit_context_path(slug, key, redraft)
    else:
        if file is None:
            raise PipelineError("a whole-card audit needs --file PATH (the record the auditor wrote)")
        path = file
        context_path = (out_dir or cfg.run_dir) / "audit-context" / f"{slug}{_round_tag(redraft)}.md"
    invalid1, invalid2, retry_note = (_sibling(path, e) for e in (".invalid-1.yaml", ".invalid-2.yaml", ".retry.md"))
    if invalid2.exists():
        raise PipelineError(f"{path.name} failed validation twice ({invalid2.name}); the format retry is used")
    if retry and not invalid1.exists():
        raise PipelineError(f"--retry needs an earlier invalid record ({invalid1.name}); there is none")
    retry = retry or invalid1.exists()  # a record rewritten after a failed one is the format retry
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PipelineError(f"{path} does not exist") from exc
    except OSError as exc:
        raise PipelineError(f"{path} is not readable: {exc}") from exc
    try:
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise PipelineError(f"{path} is not readable YAML: {exc}") from exc
        record = validate_audit_record(
            cfg,
            raw,
            slug=slug,
            key=key,
            source=path,
            context_path=context_path,
            redraft=redraft,
            require_class=is_correction_round(redraft),
        )
    except PipelineError as exc:
        if retry:
            path.replace(invalid2)
            raise PipelineError(
                f"{exc}\nThe format retry failed too: the record is kept as {invalid2.name}; final"
            ) from exc
        path.replace(invalid1)
        _write_text(retry_note, _retry_text(path, invalid1, context_path, str(exc)))
        raise PipelineError(
            f"{exc}\nThe record is moved to {invalid1.name}; the instructions for the format retry are in "
            f"{retry_note.name}"
        ) from exc
    if key is not None:
        _log(
            cfg,
            {
                "event": "record-audit",
                "card": slug,
                "paper": record.paper,
                "second": second,
                "round": _round_tag(redraft).removeprefix("-") or None,
                "decision": record.decision,
            },
        )
    return record


def _retry_text(path: Path, invalid: Path, context_path: Path, errors: str) -> str:
    """``<name>.retry.md``: what the auditor reads for its one format retry."""
    return "\n".join(
        [
            f"# Format retry for {path.name}",
            "",
            "The record below did not pass validation. Fix the format only: the decision and the accepted level stay "
            "as they are, and so does your reading of the card. Write the corrected record to "
            f"`{path}` (the same path as before).",
            "",
            f"- audit context: `{context_path}`",
            f"- the invalid record: `{invalid}`",
            "",
            "## Validation errors",
            "",
            "```",
            errors,
            "```",
            "",
        ]
    )


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
    pairs: list[dict[str, Any]] = [
        {"card": o.slug, "key": o.pmid, "paper": o.paper_id, "why": why} for o, why in chosen
    ]
    # A redraft (round L) is a level change: always decided twice. It is listed once its operations file exists.
    pairs += [
        {"card": o.slug, "key": o.pmid, "paper": o.paper_id, "why": "redraft_level_change", "round": REDRAFT}
        for o in eligible
        if cfg.ops_path(o.slug, o.pmid, REDRAFT).is_file()
    ]
    result = {"seed": seed, "audited": len(eligible), "pairs": pairs}
    _write_json(cfg.f("audit-sample.json"), result)
    _log(cfg, {"event": "audit-sample", "seed": seed, "audited": len(eligible), "sampled": len(pairs)})
    return result


def _sampled_keys(cfg: Config) -> set[tuple[str, str]]:
    path = cfg.f("audit-sample.json")
    if not path.is_file():
        return set()
    try:
        return {(p["card"], p["key"]) for p in _read_json(path).get("pairs", []) if not p.get("round")}
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
    n: Round_
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
    # The one redraft (round L) after an accept_lower: what it is and how far it got. Never a further round.
    redraft: Round | None = None
    redraft_state: Literal[
        "not_applicable", "none", "failed_checks", "rejected", "audit_missing", "audit_not_accepted", "accepted"
    ] = "not_applicable"
    redraft_note: str = ""
    redraft_audit: AuditRecord | None = None
    redraft_second: AuditRecord | None = None

    @property
    def last(self) -> Round | None:
        return self.rounds[-1] if self.rounds else None

    @property
    def applied(self) -> bool:
        """Whether the pair's operations are applied: reviewer accepted, and the audit gate (if any) passed."""
        return self.status == "accepted" and (
            self.audit_state in ("not_required", "accepted")
            or (self.audit_state == "lower" and self.redraft_state == "accepted")
        )

    @property
    def final_audit(self) -> AuditRecord | None:
        """The audit record that decided the change: the redraft's when the redraft was accepted, else the first."""
        return self.redraft_audit if self.redraft_state == "accepted" else self.audit

    @property
    def ops_to_apply(self) -> OpsFile:
        """The operations to apply: the last round's, and after an accepted redraft those followed by the redraft's.

        A proposal of the last round on a target the redraft proposes again is dropped (the redraft's replaces it)."""
        assert self.last is not None and self.last.ops is not None
        if self.redraft_state != "accepted" or self.redraft is None or self.redraft.ops is None:
            return self.last.ops
        again = {op.target for op in self.redraft.ops.operations if isinstance(op, Propose)}
        kept = [op for op in self.last.ops.operations if not (isinstance(op, Propose) and op.target in again)]
        return OpsFile(
            card=self.last.ops.card, paper=self.last.ops.paper, operations=[*kept, *self.redraft.ops.operations]
        )


def _load_round(cfg: Config, slug: str, pmid: str, n: Round_) -> Round | None:
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


def _gate_redraft(cfg: Config, o: Outcome) -> None:
    """Set the state of the one redraft (round L) of a pair whose first audit said accept_lower.

    The change is applied only when the redraft passed the mechanical checks (E4 included), the reviewer accepted it
    and its own audit, and the second audit that a level change always gets, both say accept. Anything else leaves
    the card unchanged; there is no further round.
    """
    assert o.audit is not None and o.audit.decision == "accept_lower"
    level = o.audit.accepted_level
    o.redraft = r = _load_round(cfg, o.slug, o.pmid, REDRAFT)
    if o.second_differs:
        o.redraft_state = "none"
        o.redraft_note = "no redraft allowed: the two audits of the change differ"
        return
    if r is None:
        o.redraft_state, o.redraft_note = "none", "no redraft recorded"
        return
    if r.ops is None:
        o.redraft_state, o.redraft_note = "failed_checks", f"redraft failed checks: {r.ops_problem}"
    elif problems := redraft_ops_problems(r.ops, level, o.paper_id):
        o.redraft_state, o.redraft_note = "failed_checks", "redraft failed checks: " + "; ".join(problems)
    elif r.checks is None or not r.checks.get("passed"):
        why = _check_failure_summary(r.checks) if r.checks is not None else "it was never applied (no check result)"
        o.redraft_state, o.redraft_note = "failed_checks", f"redraft failed checks: {why}"
    elif r.review is None:
        o.redraft_state, o.redraft_note = "rejected", "redraft rejected in review: no review was recorded"
    elif r.review.verdict != "accept":
        o.redraft_state, o.redraft_note = "rejected", "redraft rejected in review"
    else:
        first, why = load_audit(cfg, o.slug, o.pmid, redraft=True)
        o.redraft_audit = first
        if first is None:
            o.redraft_state, o.redraft_note = "audit_missing", f"redraft not accepted in audit: no valid record: {why}"
            return
        second, why2 = load_audit(cfg, o.slug, o.pmid, second=True, redraft=True)
        o.redraft_second = second
        if first.decision != "accept":
            o.redraft_state = "audit_not_accepted"
            o.redraft_note = f"redraft not accepted in audit: {first.decision}"
        elif second is None:
            o.redraft_state = "audit_not_accepted"
            o.redraft_note = f"redraft not accepted in audit: the second audit is not valid: {why2}"
        elif second.decision != "accept":
            o.redraft_state = "audit_not_accepted"
            o.redraft_note = f"redraft not accepted in audit: the second audit decided {second.decision}"
        else:
            o.redraft_state, o.redraft_note = "accepted", f"accepted at level {level}"
        return


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
                if o.audit_state == "lower":
                    _gate_redraft(cfg, o)
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
            for t in sorted(_targets(o.ops_to_apply) & _targets(p.ops_to_apply), key=str)
        ]
        if others:
            o.status = "conflict"  # type: ignore[assignment]
            o.note = "conflicts with " + "; ".join(f"{p.paper_id} on {' '.join(map(str, t))}" for p, t in others)
    for o in outcomes:
        if o.status == "conflict":
            o.status = "parked"
            o.note = "not applied, " + o.note


def _check_error_lines(checks: dict[str, Any]) -> list[str]:
    """What failed in a checks record, one line each: operation errors, validator issues, new citation errors."""
    bits = list(checks.get("ops_errors", [])) + list(checks.get("validator", []))
    bits += [
        f"{r['study']} {r['code']}: {r['message']}"
        for r in checks.get("citations", [])
        if (r["level"] == "ERROR" or r.get("code") == "C9") and not r.get("preexisting")
    ]
    return [b.replace("\n", " ") for b in bits]


def _check_failure_summary(checks: dict[str, Any]) -> str:
    return "; ".join(_check_error_lines(checks)) or "unknown"


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
    if isinstance(op, UpdateStudy):
        return f"Update study `{op.id}`: " + ", ".join(f"{k} = {v!r}" for k, v in op.set.items())
    if isinstance(op, RemoveParagraph):
        return f"Remove paragraph {op.index} of `{op.field}`"
    if isinstance(op, RemoveLink):
        return f"Remove the link to `{op.to}`"
    if isinstance(op, AddSentence):
        return f"Add a sentence to `{op.target}` (sources {', '.join(op.sources)}): {op.text}"
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


def _redraft_text(o: Outcome) -> str:
    """One line on the redraft (round L) of a pair whose first audit said accept_lower."""
    if o.redraft_state == "accepted":
        return "accepted (checks passed, review accept, audit accept, second audit accept): the change is applied"
    return f"{o.redraft_note}; the card is unchanged"


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
        if o.audit_state == "lower":
            lines.append(f"  - redraft at level {o.audit.accepted_level} (round L): {_redraft_text(o)}")
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
            if o.redraft_state != "accepted":
                disputes.append(
                    f"- {who}: the auditor accepts level {o.audit.accepted_level} only, so nothing is applied: "
                    f"{o.audit.reasons_summary}; redraft (round L): {o.redraft_note}"
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
        if o.redraft_state == "accepted":
            notes.append(
                f"redraft at level {o.audit.accepted_level if o.audit else '?'} (round L): review accept, "
                "audit accept, second audit accept"
            )
        warnings = sum(1 for r in (last.checks or {}).get("citations", []) if r["level"] == citations.WARNING)
        if warnings:
            notes.append(f"{warnings} citation-check warning(s), see checks/")
        notes += [f"warning: {w}" for w in (last.checks or {}).get("warnings", [])]
        for f in by_severity(last.review.findings):
            where = "the card" if f.operation is None else f"operation {f.operation}"
            notes.append(f"reviewer note ({f.severity}) on {where}: {f.problem}")
        touched: list[list[str]] = []
        applied_ops = o.ops_to_apply
        op_tiers = tiers(applied_ops, base)
        for op, op_tier in zip(applied_ops.operations, op_tiers, strict=True):
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
# redraft-plan: the one redraft after an auditor's accept_lower
# ---------------------------------------------------------------------------


def _redraft_files(cfg: Config, slug: str, key: str | None) -> list[Path]:
    """Every file of a round L that exists for the pair (or whole card)."""
    candidates = [
        cfg.ops_path(slug, key, REDRAFT),
        cfg.checks_path(slug, key, REDRAFT),
        cfg.review_path(slug, key, REDRAFT),
        cfg.applied_dir(slug, key, REDRAFT),
        cfg.audit_path(slug, key, redraft=True),
        cfg.audit_path(slug, key, True, redraft=True),
        cfg.audit_context_path(slug, key, True),
    ]
    return [p for p in candidates if p.exists()]


def _audit_lines(audit: AuditRecord) -> list[str]:
    lines = [f"- decision: {audit.decision}", f"- accepted_level: {audit.accepted_level}", ""]
    for i, part in enumerate(audit.parts, 1):
        lines += [f"### Part {i}: {part.decision_part}", "", f"Rubric clause: {part.rubric}", ""]
        lines += [f"- evidence {e.source}: {e.quote}" for e in part.evidence]
        lines.append("")
    lines += [f"reasons_summary: {audit.reasons_summary}", "", f"would_change: {audit.would_change}"]
    return lines


def build_redraft_context(cfg: Config, slug: str, key: str | None, audit: AuditRecord, loader: FullTextLoader) -> str:
    """What the drafter reads for the redraft (round L): the card the operations apply to, the first audit's
    ``accepted_level``, ``parts`` and ``would_change`` (the drafter is not a judge, E5), the cited records as in an
    audit (carriers in full, the rest as abstracts, E1), the inclusion rule and the rubric, and the limits (E4)."""
    base = _base_card(cfg, slug)
    if key is not None:
        card_path = cfg.applied_dir(slug, key, _last_applied_round(cfg, slug, key)) / f"{slug}.yaml"
        subject = f"card `{slug}`, change from paper `{_paper_id_of_key(cfg, key)}`"
        paper_line = f"`{_paper_id_of_key(cfg, key)}`"
    else:
        card_path = base
        subject = f"the whole card `{slug}`"
        paper_line = "left out (a whole-card redraft names no paper)"
    card = _load_card(card_path)
    carriers = carrier_ids(card)
    records: list[str] = []
    for study_id in dict.fromkeys(s.id for s in card.studies):
        try:
            records += _audit_record_lines(cfg, study_id, loader, study_id in carriers)
        except PipelineError:
            records += [f"### Not cached: {study_id}", "", "No cached record. Do not cite anything about it.", ""]
    level = audit.accepted_level
    parts = [
        f"# Redraft context (round L): {subject}",
        "",
        f"The auditor did not accept this at its level and accepts level {level} only. You write the one redraft "
        f"(round L, at most once) as a JSON operations file. Limits: only `propose` operations; exactly one on "
        f"`level` with `value` {level}, and the complete new `reason` argued at level {level}; optionally one each "
        "on `contested`, `diagnostic_marker` and `explains_pem`, only where the lower level makes the existing "
        f"value inconsistent. No `add_study`, `add_paragraph` or `replace_paragraph`. `paper` is {paper_line}.",
        "",
        "## 1. The card the operations apply to",
        "",
        "```yaml",
        card_path.read_text(encoding="utf-8").rstrip("\n"),
        "```",
        "",
        "## 2. The auditor's decision and reasons",
        "",
        *_audit_lines(audit),
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
    ]
    return "\n".join(parts)


def redraft_plan(
    cfg: Config, slug: str, key: str | None, loader: FullTextLoader, *, audit_file: Path | None = None
) -> Path:
    """Write ``redraft-context/...md`` for the one redraft of a pair (or a whole card) whose audit said accept_lower.

    Refuses when the audit is not a valid ``accept_lower`` (for a pair, also when the second audit differs) and when
    a round L already exists: there is at most one redraft.
    """
    existing = _redraft_files(cfg, slug, key)
    if existing:
        raise PipelineError(
            "a redraft (round L) already exists; there is at most one: " + ", ".join(p.name for p in existing)
        )
    if key is not None:
        match = next((o for o in collect_outcomes(cfg) if (o.slug, o.pmid) == (slug, key)), None)
        if match is None or match.status != "accepted" or not match.audit_required:
            raise PipelineError(f"{slug} and {key} are not an audited pair the reviewer accepted")
        audit = match.audit
        if audit is None:
            raise PipelineError(f"no valid audit record for {slug} and {key}: {match.audit_note}")
        if match.second_differs:
            raise PipelineError("the first and the second audit differ; there is no redraft")
    else:
        if audit_file is None:
            raise PipelineError("a whole-card redraft needs the first audit's record (--audit PATH)")
        try:
            audit = validate_audit_record(
                cfg,
                yaml.safe_load(audit_file.read_text(encoding="utf-8")),
                slug=slug,
                key=None,
                source=audit_file,
                context_path=cfg.audit_context_path(slug),
            )
        except (OSError, yaml.YAMLError) as exc:
            raise PipelineError(f"{audit_file} is not readable: {exc}") from exc
    if audit.decision != "accept_lower" or audit.accepted_level is None:
        raise PipelineError(f"the audit says {audit.decision}, not accept_lower: there is nothing to redraft")
    path = cfg.redraft_context_path(slug, key)
    _write_text(path, build_redraft_context(cfg, slug, key, audit, loader))
    _log(cfg, {"event": "redraft-plan", "card": slug, "paper": audit.paper, "accepted_level": audit.accepted_level})
    return path


# ---------------------------------------------------------------------------
# Correcting a held-back draft: correction-plan and the files of a correction round
# ---------------------------------------------------------------------------

# ``-invalid`` / ``-C<k>-invalid``: the final invalid first record that publish-card copies (S4).
_AUDIT_FILE_SUFFIX = r"(-second|-L|-L-second|-C[1-9]\d*|-C[1-9]\d*-second|-invalid|-C[1-9]\d*-invalid)?"


def _records_of_card(cfg: Config, slug: str, pattern: re.Pattern[str], *, whole_card: bool) -> list[Path]:
    """The files of ``audits/`` whose name matches ``pattern`` and whose ``card`` field is ``slug``.

    Names can collide between slugs (``foo`` and a card ``foo-second``), so the ``card`` field decides. A matching
    file that is not readable YAML, is not a mapping or has no ``card`` is not skipped and not counted: it is an error
    naming the file, so a broken record cannot open a path to audit the draft again.
    """
    found: list[Path] = []
    for path in sorted(cfg.audits_dir.glob("*.yaml")) if cfg.audits_dir.is_dir() else []:
        if not pattern.match(path.name):
            continue
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise PipelineError(f"{path} cannot be read ({str(exc).splitlines()[0]}); fix or remove it first") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("card"), str):
            raise PipelineError(f"{path} is not a record with a `card` field; fix or remove it first")
        if raw["card"] != slug or (whole_card and raw.get("paper") is not None):
            continue  # the record of another card whose slug ends like a suffix, or a pair record
        found.append(path)
    return found


def whole_card_audit_files(cfg: Config, slug: str) -> list[Path]:
    """The whole-card audit records of ``slug`` in ``audits/``: ``<date>-<slug>`` followed by exactly one of the
    known suffixes (``-second``, ``-L``, ``-L-second``, ``-C<k>``, ``-C<k>-second``, ``-invalid``, ``-C<k>-invalid``)
    and ``.yaml``, whose ``card`` is ``slug``. A trail record (``-C<k>-correction``) is not an audit record. A broken
    matching file is an error."""
    pattern = re.compile(rf"^\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(slug)}{_AUDIT_FILE_SUFFIX}\.yaml$")
    return _records_of_card(cfg, slug, pattern, whole_card=True)


def correction_trails(cfg: Config, slug: str) -> list[Path]:
    """The trail records of the correction rounds already recorded for ``slug`` (name and ``card`` field)."""
    pattern = re.compile(rf"^\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(slug)}-C[1-9]\d*-correction\.yaml$")
    return _records_of_card(cfg, slug, pattern, whole_card=False)


def _attempt_trails(cfg: Config, slug: str) -> dict[tuple[int, int], Path]:
    """The trail records of ``slug`` by (round k, attempt index): ``...-C<k>-correction.yaml`` is attempt 0,
    ``...-correction-revised.yaml`` 1, ``...-correction-revised2.yaml`` 2, and so on."""
    pattern = re.compile(rf"^\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(slug)}-C[1-9]\d*-correction({ATTEMPT_RE})\.yaml$")
    found: dict[tuple[int, int], Path] = {}
    for path in _records_of_card(cfg, slug, pattern, whole_card=False):
        suffix = re.search(rf"-correction({ATTEMPT_RE})\.yaml$", path.name)
        assert suffix is not None
        found[(_trail_round(path), ATTEMPT_SUFFIXES.index(suffix.group(1) or ""))] = path
    return found


def _trail_round(path: Path) -> int:
    match = re.search(r"-C([1-9]\d*)-correction", path.name)
    assert match is not None, path.name
    return int(match.group(1))


def _trail_reject(data: Any) -> Reject | None:
    """`_reject` read from a trail record: its review verdict and whole-card review verdict."""
    review = data.get("review") if isinstance(data, dict) else None
    verdict = review.get("verdict") if isinstance(review, dict) else None
    card_review = data.get("card_review") if isinstance(data, dict) else None
    card_verdict = card_review.get("verdict") if isinstance(card_review, dict) else None
    valve = data.get("valve") if isinstance(data, dict) else None
    passed = {
        k for k, v in (valve if isinstance(valve, dict) else {}).items() if isinstance(v, dict) and v.get("passed")
    }
    if verdict == "reject":
        if not _wording_only(review.get("findings")):
            return "correction review", _decisive_count(review.get("findings"))
        if not any(k.startswith("correction-review") for k in passed):
            return None  # a wording-only reject goes through the valve, not a revised attempt
        verdict = "accept"
    if verdict == "accept" and card_verdict == "reject":
        if _wording_only(card_review.get("findings")):
            return None
        return "whole-card review", _decisive_count(card_review.get("findings"))
    return None


def correction_round_state(cfg: Config, slug: str) -> tuple[int, int | None]:
    """R7: (the number of correction rounds used, the number of an open round or None) from the trails in ``audits/``.

    A round is open while its last trail ends in a reject (correction review, or whole-card review after an accepted
    correction review) that opens a revision (`_revision_state`): a further revised attempt is open while fewer than
    ``MAX_REVISIONS`` exist and the decisive findings fell since the last reject of the same kind. Otherwise the
    round is used: accepted, failed checks (no review verdict: no revised attempt is possible), closed with one
    audit record only (a first reject, S1) or none (S4). A round whose trails carry no ``pre_card_review`` was run
    under the 2026-11-14 rules, where any revised trail closes the round (and a trail without ``card_review`` or
    ``audits_run`` reads as before). A trail that does not let code decide counts as used.
    """
    trails = _attempt_trails(cfg, slug)
    used, open_round = 0, None
    for k in sorted({k for k, _i in trails}):
        attempts = sorted(i for kk, i in trails if kk == k)
        data = [yaml.safe_load(trails[(k, i)].read_text(encoding="utf-8")) for i in attempts]
        legacy = not (isinstance(data[0], dict) and "pre_card_review" in data[0])
        rejects = [_trail_reject(d) for d in data]
        # an older round had one revised attempt, whatever the kind
        if legacy:
            pending = rejects[-1] is not None and attempts == [0]
        else:
            falling = any(isinstance(d, dict) and d.get("revision_rule") == REVISION_RULE for d in data)
            pending = _revision_state(rejects, falling)[0]
        if pending:
            open_round = k
        else:
            used += 1
    return used, open_round


def _first_publication_refusal(cfg: Config, slug: str) -> str | None:
    """A9: a draft that already has a whole-card audit record is not audited again unchanged."""
    existing = whole_card_audit_files(cfg, slug)
    if not existing:
        return None
    return (
        f"{slug} already has whole-card audit record(s) in {cfg.audits_dir} "
        f"({', '.join(p.name for p in existing)}). The same draft is not audited again: correct it "
        f'(`correction-plan {slug} --out DIR`, docs/pipeline.md, "Correcting a held-back draft")'
    )


CORRECTION_LIMITS = (
    "Limits of a correction (the code enforces them). The ops file has `paper` null and at least one operation, and "
    "may hold `replace_paragraph`, `remove_paragraph`, `update_study`, `remove_link`, `propose` and `add_sentence` "
    "only. A `propose` "
    "on `level` may only lower the level (the value must be lower than the draft's); a `propose` on a badge may only "
    "set it to false; a `propose` on `contested` may add, change or remove the mark. No `add_study` and no "
    "`add_paragraph`. `update_study` takes `id` and `set` (a map of study fields; not `id`, not `preprint`); a "
    "recognised case definition needs `case_definition_source` and `case_definition_quote`, `unverified` needs both "
    "null. `remove_paragraph` takes `field` and `index` and cannot leave `level_reason` empty, nor "
    "`contested.reason` while the card is contested, nor a true badge without a reason. `remove_link` takes `to`. "
    '`add_sentence` (`target`, `text`, `sources`, `answers`: `{"record": <audit record file>, "part": <index>}`) '
    "appends one sentence to an existing free-text item, only when an objecting audit part expressly asks for a "
    "missing statement (section 9): one sentence, at most one per part, citing only sources that part quotes, saying "
    "no more than its quotes, and only to that part's target or one the step 0 review gives it. "
    "A finding that cannot be resolved from the records shown below is resolved by removing or weakening the claim, "
    "never by adding a fact: do not cite anything that is not in the records of section 4."
)


def _pre_review_lines(review: ReviewFile) -> list[str]:
    """The findings of the whole-card review before drafting, for the correction context."""
    lines = [f"- verdict: {review.verdict}"]
    if not review.findings:
        lines.append("- findings: none")
    for i, finding in enumerate(review.findings, 1):
        lines.append(f"- finding {i} ({finding.severity}): {finding.problem}")
        if finding.targets:
            lines.append(f"  - targets: {', '.join(finding.targets)}")
        if finding.fix:
            lines.append(f"  - fix: {finding.fix}")
    return lines


def _added_sentence_lines(cfg: Config, slug: str, k: int, pre_review: ReviewFile | None) -> list[str]:
    """Section 9 of the correction context: per objecting audit part its quoted evidence and the targets an
    ``add_sentence`` answering it may use (DECISIONS 2026-11-16)."""
    given = {(e.record, e.part): e.targets for e in (pre_review.audit_targets if pre_review else None) or []}
    draft = _load_card(cfg.drafts_dir / f"{slug}.yaml")
    lines = [
        '## 9. Added sentences (the one exception to "delete rather than rewrite")',
        "",
        "Only when an objecting audit part below expressly asks for a missing statement, you may add one sentence "
        "(`add_sentence`) answering it: one sentence, at most one per part, citing only sources that part quotes, "
        "saying no more than its quotes, appended to the part's own target, a target listed for it, or the free-text "
        "item that explains one of them (level and layer: the last `level_reason` paragraph; contested: the last "
        "`contested_reason`; a badge: the last of its reason; a study: its `finding`). Otherwise "
        "remove or weaken.",
        "",
    ]
    parts = objecting_audit_parts(cfg, slug, k)
    if not parts:
        return [*lines, "No objecting audit part: no `add_sentence` is allowed.", ""]
    for name, i, part, _decision in parts:
        tied = [*([part.target] if part.target else []), *given.get((name, i), [])]
        targets = sentence_targets(draft, tied)
        lines += [
            f"### {name}, part {i}",
            "",
            f"- decision_part: {part.decision_part}",
            *[f"- quote: {e.source}: {e.quote}" for e in part.evidence],
            f"- allowed targets: {', '.join(f'`{t}`' for t in targets) or '(none)'}",
            "",
        ]
    return lines


def build_correction_context(
    cfg: Config, slug: str, k: int, loader: FullTextLoader, pre_review: ReviewFile | None = None
) -> str:
    """What the drafter reads for correction round ``k``: the draft, every audit record of it, the cited cached
    records (carriers in full, the rest as abstracts), spec sections 2 and 3, the limits of a correction and the
    findings of the whole-card review of the unchanged draft (``pre_review``)."""
    draft = cfg.drafts_dir / f"{slug}.yaml"
    card = _load_card(draft)
    carriers = carrier_ids(card)
    records: list[str] = []
    for study_id in dict.fromkeys(s.id for s in card.studies):
        try:
            records += _audit_record_lines(cfg, study_id, loader, study_id in carriers)
        except PipelineError:
            records += [
                f"### Not cached: {study_id}",
                "",
                "No cached record. Do not cite anything about it, and take nothing from it into the card.",
                "",
            ]
    audit_parts: list[str] = []
    for path in whole_card_audit_files(cfg, slug):
        audit_parts += [f"### {path.name}", ""]
        if path.name.endswith("-invalid.yaml"):
            audit_parts += ["(this record failed validation twice: it is not a valid audit record)", ""]
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            errors = raw.get("validation_errors") if isinstance(raw, dict) else None
            if errors:
                audit_parts += [
                    "Validation errors:",
                    "",
                    "```",
                    *([errors] if isinstance(errors, str) else errors),
                    "```",
                    "",
                ]
            continue
        try:
            audit = AuditRecord.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            audit_parts += [f"(this record cannot be read: {str(exc).splitlines()[0]})", ""]
            continue
        audit_parts += [*_audit_lines(audit), ""]
    parts = [
        f"# Correction context (round C{k}): the held-back draft `{slug}`",
        "",
        f"The independent audits of this draft did not accept it. You write the correction (round C{k}) "
        f'as a JSON operations file, `ops/{slug}-rC{k}.json`, with `card` "{slug}" and `paper` null. '
        "Answer the audit findings (section 2) and the review findings (section 7) in the same correction. "
        + CORRECTION_LIMITS,
        "",
        "## 1. The draft as it stands",
        "",
        "```yaml",
        draft.read_text(encoding="utf-8").rstrip("\n"),
        "```",
        "",
        "## 2. The audit records of this draft",
        "",
        *audit_parts,
        "## 3. Where the correction is limited",
        "",
        CORRECTION_LIMITS,
        "",
        "Targets the findings name (draft numbering; the code refuses an operation on anything else):",
        "",
        *([f"- `{t}`" for t in sorted(pre_targets(pre_review))] or ["- (none recorded)"]),
        "",
        "A `replace_paragraph` or `remove_paragraph` changes `<field>[i]` (`core_claim` has no index); `update_study` "
        "changes `studies[<id>]` (allowed by `studies[<id>]` or `studies[<id>].<field>`); `remove_link` changes "
        "`links[i]`; a `propose` changes `level`, `contested` or `badges.<badge>` (also allowed by "
        "`badge_reasons.<badge>[n]`). An operation on anything else is refused.",
        "",
        "## 4. Cited records",
        "",
        *(records or ["The card cites no study.", ""]),
        "## 5. The inclusion rule (functional spec section 2)",
        "",
        _demote_headings(spec_section(cfg.spec_path, 2)),
        "",
        "## 6. The rubric (functional spec section 3)",
        "",
        _demote_headings(spec_section(cfg.spec_path, 3)),
        "",
        "## 7. Review findings on the draft as it stands (whole-card review before drafting)",
        "",
        "The card-reviewer read the unchanged draft against its cached sources. Answer these findings like the "
        "audit findings, under the limits of section 3: remove, weaken or relabel a claim, never add a fact.",
        "",
        *(_pre_review_lines(pre_review) if pre_review is not None else ["(no review recorded)"]),
        "",
        citations.author_facts_section(card, citations.CacheReader(cfg.cache_dir)).replace(
            "## Author facts", "## 8. Author facts", 1
        ),
        *_added_sentence_lines(cfg, slug, k, pre_review),
    ]
    return "\n".join(parts)


def correction_plan(cfg: Config, slug: str, loader: FullTextLoader) -> Path:
    """`correction-plan`: write ``correction-context/<slug>-C<k>.md`` for the drafter of a held-back draft.

    Refuses, writing nothing, when the card is already in ``cards/``, the draft is missing, ``audits/`` has no audit
    record of the slug, the round would exceed the card's maximum (``max_correction_rounds``) or the whole-card review
    of the unchanged draft (``card-review-plan --pre``, ``record-review --card-review --pre``) is not recorded in the
    run folder. That review's findings go into the context.
    """
    if (cfg.cards_dir / f"{slug}.yaml").exists():
        raise PipelineError(f"{cfg.cards_dir / f'{slug}.yaml'} exists: only a held-back draft is corrected")
    if not (cfg.drafts_dir / f"{slug}.yaml").is_file():
        raise PipelineError(f"no draft {cfg.drafts_dir / f'{slug}.yaml'} to correct")
    if not whole_card_audit_files(cfg, slug):
        raise PipelineError(f"{cfg.audits_dir} holds no whole-card audit record of {slug}: nothing to correct")
    used, open_round = correction_round_state(cfg, slug)
    if open_round is not None:
        raise PipelineError(
            f"round C{open_round} is open: the revised attempt is pending (apply it with the "
            "`--revised...` flag it is waiting for); a new round is not started"
        )
    k = 1 + used
    if k > max_correction_rounds(slug):
        raise PipelineError(
            f"{slug} has used its {max_correction_rounds(slug)} correction round(s); the card stays held back and is "
            "listed for the founder"
        )
    pre_review = _load_card_review(cfg, slug, f"C{k}-pre")
    if pre_review is None:
        raise PipelineError(
            f"round C{k} has no valid whole-card review of the unchanged draft in {cfg.run_dir}: run "
            f"`card-review-plan {slug} --pre --round C{k} --out DIR`, the card-reviewer, then "
            f"`record-review {slug} --card-review --pre --round C{k} --run-dir DIR`"
        )
    text = build_correction_context(cfg, slug, k, loader, pre_review)
    path = cfg.correction_context_path(slug, k)
    _write_text(path, text)
    _log_card_run(cfg, {"event": "correction-plan", "card": slug, "round": f"C{k}"})
    return path


def _log_card_run(cfg: Config, event: dict[str, Any]) -> None:
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    _log(cfg, event)


def last_attempt_tag(cfg: Config, slug: str, n: str) -> str:
    """R3: the attempt that goes on: the last one that has an ops file (``C<k>-revised2``, ``C<k>-revised``, else the
    first)."""
    chain = _attempt_chain(cfg, slug, n)
    return chain[-1] if chain else n


def _card_review_problem(cfg: Config, slug: str, tag: str) -> str | None:
    """W1: why the whole-card review of correction attempt ``tag`` does not let the attempt go to audit, or None."""
    review = _load_card_review(cfg, slug, tag)
    if review is None:
        return (
            f"correction round {tag} has no valid whole-card review (`card-review-plan {slug} --round "
            f"C{correction_number(tag)}{_attempt_flag(tag)} --out DIR`, the "
            f"card-reviewer, then `record-review --card-review{_attempt_flag(tag)}`)"
        )
    if not _stage_accepted(cfg, slug, tag, "card-review", review):
        return f"the whole-card review rejected correction round {tag}"
    return None


def audit_plan_correction(cfg: Config, slug: str, n: str, loader: FullTextLoader, out_dir: Path | None) -> Path:
    """`audit-plan --card <slug> --round C<k>`: the whole-card audit context of the corrected draft.

    Built by the function that builds the first-publication context, from the applied text of the last attempt (the
    revised one when there is one), so it shows nothing of the correction. Refused unless that attempt's checks passed
    and its review says accept.
    """
    tag = last_attempt_tag(cfg, slug, n)
    checks_file = cfg.checks_path(slug, None, tag)
    if not checks_file.is_file():
        raise PipelineError(f"no checks for correction round {tag} ({checks_file}); run `apply --round {n}` first")
    checks = _read_json(checks_file)
    if not checks.get("passed"):
        raise PipelineError(f"correction round {tag} did not pass its checks: {_check_failure_summary(checks)}")
    r = _load_round(cfg, slug, "", tag)
    if r is None or r.review is None:
        raise PipelineError(f"correction round {tag} has no valid review; run `record-review --round {n}` first")
    if not _stage_accepted(cfg, slug, tag, "correction-review", r.review):
        flag = _pending_flag(cfg, slug, n)
        pending = f" (a revised attempt is pending: apply it with {flag})" if flag else ""
        raise PipelineError(f"the reviewer rejected correction round {tag}; it is not audited{pending}")
    if problem := _card_review_problem(cfg, slug, tag):
        raise PipelineError(problem + "; it is not audited")
    applied = _attempt_text_path(cfg, slug, tag, "audit")  # the applied text, with the wording fixes of the reviews
    if not applied.is_file():
        raise PipelineError(f"no applied text {applied}; run `apply --round {n}` first")
    text = build_audit_context(cfg, slug, None, loader, card_text_from=applied)
    path = (out_dir or cfg.run_dir) / "audit-context" / f"{slug}-{n}.md"
    _write_text(path, text)
    return path


CARD_REVIEW_CHECKLIST = """\
Check the whole corrected card, in this order. A claim the cached records do not support is a `must_fix`.

1. **Case-definition labels.** For each study, compare its `case_definition` label with its cached record: the
   quote named in `case_definition_quote` must be in the record, and the quote must support the label.
2. **Links.** For each link, compare the link text with the cited source as cached. A link whose source, as cached,
   does not state it is a `must_fix`.
3. **Claims.** Compare each claim in `level_reason`, `contested.reason`, the badge reasons and the early signals with
   the sources it cites: numbers, sample sizes, direction of the finding, wording of strength.
4. **Contested mark.** If a cited study of comparable quality contradicts the level, does the card carry a contested
   mark? Say so when it does not.
5. **Names.** Group and place names that are not in the cached records are a `must_fix`.
6. The credibility rules: every sentence sourced, no treatment advice, unreplicated findings labelled.

Write the review file named above: `{"card": "<slug>", "paper": null, "verdict": "accept" | "reject", "findings":
[{"operation": null, "severity": "must_fix" | "advisory", "problem": "...", "fix": "..."}]}`. A `must_fix` means
`reject`. Read only this file and the cached files it names; fetch nothing."""


def _cached_study_files(cfg: Config, study_id: str, reader: citations.CacheReader) -> list[str]:
    """What the card-reviewer may read for one cited study: the cached record file and the full text, if cached."""
    lines: list[str] = []
    pmcid: str | None = None
    if study_id.startswith("pmid:"):
        pmid = study_id.removeprefix("pmid:")
        record = reader.record(pmid)
        if isinstance(record, str):
            return [f"- record: not usable ({record})", "- full text: none cached"]
        lines.append(f"- record: `{reader.pubmed.path(pmid)}`")
        try:
            lookup = europepmc.read_cached_lookup(reader.epmc, pmid)
        except europepmc.EuropePmcError:
            lookup = None
        pmcid = (lookup.pmcid if lookup else None) or record.pmcid
    else:
        try:
            pre = reader.preprint(study_id)
        except europepmc.EuropePmcError as exc:
            return [f"- record: not usable ({exc})", "- full text: none cached"]
        if pre is None:
            return ["- record: not cached", "- full text: none cached"]
        lines.append(f"- record: `{reader.epmc.preprint_path(pre.ppr_id)}`")
        pmcid = pre.pmcid
    text = "none cached"
    if pmcid:
        path = reader.epmc.fulltext_path(pmcid)
        try:
            if path.is_file() and not europepmc.is_placeholder_fulltext(path.read_bytes()):
                text = f"cached, `{path}`"
        except (europepmc.EuropePmcError, OSError):
            pass
    return [*lines, f"- full text: {text}"]


def _pre_audit_target_lines(cfg: Config, slug: str, tag: str) -> list[str]:
    """The objecting parts of the audit records the correction answers, for the ``--pre`` review context: it fills
    ``audit_targets`` with the targets of each part, and gives every ``must_fix`` finding ``targets``."""
    lines = [
        "## 6. Targets (the `--pre` review)",
        "",
        "Every `must_fix` finding carries `targets`: a non-empty list naming the parts of the card it is about "
        "(`core_claim`, `level_reason[n]`, `contested_reason[n]`, `subgroups[n]`, `early_signals[n]`, "
        "`badge_reasons.diagnostic_marker[n]`, `badge_reasons.explains_pem[n]`, `links[n]`, `links[n].reason`, "
        "`studies[<id>].finding`, or a structured part: `level`, `contested`, `badges.diagnostic_marker`, "
        "`badges.explains_pem`, `layer`, `links[n]`, `studies[<id>]`, `studies[<id>].<field>`), numbered as in the "
        'draft of section 1. The review file also holds `"audit_targets": [{"record": "<file>", "part": <i>, '
        '"targets": [...]}]`: one entry for each objecting audit part below, no other.',
        "",
    ]
    parts = objecting_audit_parts(cfg, slug, correction_number(tag))
    if not parts:
        lines += ["No audit record has an objecting part: `audit_targets` is an empty list.", ""]
    for name, i, part, decision in parts:
        lines += [f"### {name}, part {i} (record decision: {decision})", "", f"- decision_part: {part.decision_part}"]
        lines += [f"- evidence: {e.source}: {e.quote}" for e in part.evidence]
        lines.append("")
    return lines


def build_card_review_context(cfg: Config, slug: str, tag: str) -> str:
    """W1: what the card-reviewer reads for the whole-card review of correction attempt ``tag`` (``C1``,
    ``C1-revised`` or ``C1-revised2``): the corrected card (the applied text, comments stripped), for each cited study
    its id, the cached record file and whether a full text is cached, the rubric and the checklist. No full text is
    embedded: the reviewer reads the cached files it needs, so the file is bounded by the number of cited studies.
    For ``C<k>-pre`` the card is the unchanged draft in ``drafts/``: the same context and checklist, before any
    correction."""
    pre = tag.endswith("-pre")
    applied = cfg.drafts_dir / f"{slug}.yaml" if pre else _attempt_text_path(cfg, slug, tag, "card-review")
    card = _load_card(applied)
    reader = citations.CacheReader(cfg.cache_dir)
    studies: list[str] = []
    for study_id in dict.fromkeys(s.id for s in card.studies):
        studies += [f"### {study_id}", "", *_cached_study_files(cfg, study_id, reader), ""]
    parts = [
        f"# Whole-card review context ({'before drafting' if pre else 'correction attempt ' + tag}): `{slug}`",
        "",
        f"You review the whole {'held-back draft, as it stands,' if pre else 'corrected card'} against its cached "
        "sources. Read only this file and the cached files "
        "named in section 2; fetch nothing. Write your review file to "
        f"`{cfg.card_review_path(slug, tag)}`.",
        "",
        f"## 1. The {'draft' if pre else 'corrected card'} (comments removed)",
        "",
        "```yaml",
        strip_yaml_comments(applied.read_text(encoding="utf-8")),
        "```",
        "",
        "## 2. Cited studies and their cached files",
        "",
        *(studies or ["The card cites no study.", ""]),
        "## 3. The rubric (functional spec section 3)",
        "",
        _demote_headings(spec_section(cfg.spec_path, 3)),
        "",
        "## 4. The checklist",
        "",
        CARD_REVIEW_CHECKLIST,
        "",
        citations.author_facts_section(card, reader).replace("## Author facts", "## 5. Author facts", 1),
    ]
    if pre:
        parts += _pre_audit_target_lines(cfg, slug, tag)
    return "\n".join(parts)


def card_review_plan(cfg: Config, slug: str, n: str, *, revision: int = 0, pre: bool = False) -> Path:
    """`card-review-plan <slug> --round C<k> [--revised[2-4] | --pre]`: write the whole-card review context of
    a correction attempt (W1). Refused unless that attempt's checks passed and its correction review says accept; for
    a revised attempt also unless the attempts before it were rejected, each for a kind whose revision was unused.

    With ``pre`` it is the review of the unchanged draft before the correction (``...-C<k>-pre.md``):
    refused unless the card is a held-back draft (no card, a draft, a whole-card audit record) and ``k`` is the next
    round the card may have."""
    if pre:
        if revision:
            raise PipelineError("--pre is the review before drafting: it takes no revised attempt")
        if (cfg.cards_dir / f"{slug}.yaml").exists():
            raise PipelineError(f"{cfg.cards_dir / f'{slug}.yaml'} exists: only a held-back draft is reviewed")
        if not (cfg.drafts_dir / f"{slug}.yaml").is_file():
            raise PipelineError(f"no draft {cfg.drafts_dir / f'{slug}.yaml'} to review")
        if not whole_card_audit_files(cfg, slug):
            raise PipelineError(f"{cfg.audits_dir} holds no whole-card audit record of {slug}: it is not held back")
        used, open_round = correction_round_state(cfg, slug)
        k = correction_number(n)
        if open_round is not None or k != used + 1 or k > max_correction_rounds(slug):
            raise PipelineError(
                f"correction round {n} is not allowed: the next round is C{used + 1}"
                f"{f' (round C{open_round} is open)' if open_round is not None else ''}, "
                f"and {slug} gets at most {max_correction_rounds(slug)} correction round(s)"
            )
        path = cfg.card_review_context_path(slug, f"{n}-pre")
        _write_text(path, build_card_review_context(cfg, slug, f"{n}-pre"))
        return path
    tag = attempt_tag(n, revision)
    checks_file = cfg.checks_path(slug, None, tag)
    if not checks_file.is_file():
        raise PipelineError(f"no checks for correction round {tag} ({checks_file}); run `apply --round {n}` first")
    checks = _read_json(checks_file)
    if not checks.get("passed"):
        raise PipelineError(f"correction round {tag} did not pass its checks: {_check_failure_summary(checks)}")
    r = _load_round(cfg, slug, "", tag)
    if r is None or r.review is None:
        raise PipelineError(f"correction round {tag} has no valid review; run `record-review --round {n}` first")
    if not _stage_accepted(cfg, slug, tag, "correction-review", r.review):
        raise PipelineError(f"the reviewer rejected correction round {tag}; there is nothing to review as a whole")
    if tag != n and (problem := _revision_problem(cfg, slug, n, tag)):
        raise PipelineError(problem)
    if not (cfg.applied_dir(slug, None, tag) / f"{slug}.yaml").is_file():
        raise PipelineError(f"no applied text for correction round {tag}; run `apply --round {n}` first")
    path = cfg.card_review_context_path(slug, tag)
    _write_text(path, build_card_review_context(cfg, slug, tag))
    return path


# ---------------------------------------------------------------------------
# The safety valve for wording-only findings (DECISIONS 2026-11-15)
# ---------------------------------------------------------------------------

_TARGET_PREFIX = {
    "core_claim": "core_claim",
    "level_reason": "level_reason",
    "contested.reason": "contested_reason",
    "badges.diagnostic_marker.reason": "badge_reasons.diagnostic_marker",
    "badges.explains_pem.reason": "badge_reasons.explains_pem",
    "subgroups": "subgroups",
    "early_signals": "early_signals",
}


@dataclass(frozen=True)
class ValveFinding:
    """One wording finding the valve answers: a ``must_fix`` finding of a review or an objecting part of an audit."""

    id: str
    target: str | None
    problem: str
    fix: str | None = None


class FixCheck(_M):
    """The fix check's answer for one finding: does the fix resolve it, and does it add a claim?"""

    finding: NonEmptyStr
    resolves: bool
    new_claim: bool
    reason: NonEmptyStr


class ValveCheck(_M):
    """``valve/<slug>-<key>-check.json``, written by the card-reviewer in its fix-check mode."""

    card: Slug
    fixes: Annotated[list[FixCheck], Field(min_length=1)]

    @property
    def passed(self) -> bool:
        return all(f.resolves and not f.new_claim for f in self.fixes)


def _valve_key(stage: str, tag: str) -> str:
    """The key of the valve of ``stage`` in attempt ``tag``: the stage and the attempt suffix (``card-review-revised``).
    The audits belong to the last attempt, so ``audit`` has no suffix."""
    return stage if stage == "audit" else stage + re.sub(r"^C[1-9]\d*", "", tag)


def _wording_only(findings: Any) -> bool:
    """Whether the ``must_fix`` findings (dicts, as a trail holds them) are there and every one is ``wording``."""
    must = [f for f in findings or [] if isinstance(f, dict) and f.get("severity") == "must_fix"]
    return bool(must) and all(f.get("class") == "wording" for f in must)


def _review_valve_findings(review: ReviewFile | None) -> list[ValveFinding] | None:
    """V3: the ``must_fix`` findings of a rejecting review when there is one and every one is ``wording``, else None
    (the normal path: a revised attempt)."""
    if review is None or review.verdict != "reject":
        return None
    must = [(i, f) for i, f in enumerate(review.findings) if f.severity == "must_fix"]
    if not must or any(f.klass != "wording" for _i, f in must):
        return None
    return [ValveFinding(f"findings[{i}]", f.target, f.problem, f.fix) for i, f in must]


def _read_valve_check(cfg: Config, slug: str, key: str) -> ValveCheck | None:
    path = cfg.valve_path(slug, key, "-check.json")
    try:
        return ValveCheck.model_validate(_read_json(path)) if path.is_file() else None
    except (PipelineError, ValidationError):
        return None


def _valve_passed(cfg: Config, slug: str, key: str) -> bool:
    """The valve of ``key`` was applied and its fix check passed (every fix resolves its finding and adds no claim)."""
    check = _read_valve_check(cfg, slug, key)
    return check is not None and check.passed and cfg.valve_text_path(slug, key).is_file()


def _valve_failure(cfg: Config, slug: str, key: str) -> str:
    check = _read_valve_check(cfg, slug, key)
    if check is None:
        return "no valid fix check was recorded"
    return "; ".join(
        f"{f.finding}: {'does not resolve the finding' if not f.resolves else 'adds a claim'} ({f.reason})"
        for f in check.fixes
        if not f.resolves or f.new_claim
    )


def _stage_accepted(cfg: Config, slug: str, tag: str, stage: str, review: ReviewFile) -> bool:
    """A review (``correction-review`` or ``card-review``) accepted attempt ``tag``: it said accept, or it was a
    wording-only reject whose valve passed its fix check (V3)."""
    return review.verdict == "accept" or (
        _review_valve_findings(review) is not None and _valve_passed(cfg, slug, _valve_key(stage, tag))
    )


def _attempt_text_path(cfg: Config, slug: str, tag: str, upto: str) -> Path:
    """The text of attempt ``tag`` that ``upto`` (a stage) works on: the applied text with the wording fixes of the
    review stages before it (each valve's text)."""
    path = cfg.applied_dir(slug, None, tag) / f"{slug}.yaml"
    for stage in VALVE_STAGES[: VALVE_STAGES.index(upto)]:
        if _valve_passed(cfg, slug, key := _valve_key(stage, tag)):
            path = cfg.valve_text_path(slug, key)
    return path


def _field_paras(card: cards.Card, field_name: str) -> list[cards.SourcedText]:
    if field_name == "core_claim":
        return [card.core_claim]
    if field_name in ("subgroups", "early_signals"):
        return list(getattr(card, field_name))
    reason = (
        card.level_reason
        if field_name == "level_reason"
        else (card.contested.reason if card.contested else None)
        if field_name == "contested.reason"
        else getattr(card.badges, field_name.split(".")[1]).reason
    )
    return cards.paragraphs(reason) if reason is not None else []


def _valve_op_targets(card: cards.Card, ops: OpsFile) -> tuple[list[str | None], list[str]]:
    """The target (translation-key style, in the numbering of the text the fix is applied to) of each operation of a
    valve fix, and what is wrong with the operations themselves: only ``replace_paragraph``, ``remove_paragraph`` and
    ``update_study`` of ``finding``, a replacement citing no source its paragraph does not already cite."""
    targets: list[str | None] = []
    found: list[str] = []
    present: dict[str, list[int]] = {}  # field -> the original index of each paragraph still there
    if ops.paper is not None:
        found.append(f"a valve fix names no paper, this file names {ops.paper!r}")
    if not ops.operations:
        found.append("a valve fix needs at least one operation")
    for i, op in enumerate(ops.operations):
        target = None
        if isinstance(op, (ReplaceParagraph, RemoveParagraph)):
            paras = _field_paras(card, op.field)
            left = present.setdefault(op.field, list(range(len(paras))))
            if op.index >= len(left):
                found.append(f"operations[{i}]: {op.field} has no paragraph {op.index}")
            else:
                original = left[op.index]
                target = _TARGET_PREFIX[op.field] + ("" if op.field == "core_claim" else f"[{original}]")
                if op.field == "core_claim" and isinstance(op, RemoveParagraph):
                    found.append(f"operations[{i}]: core_claim cannot be removed")
                elif isinstance(op, RemoveParagraph):
                    del left[op.index]
                elif not set(op.sources) <= set(paras[original].sources):
                    found.append(f"operations[{i}] cites a source its paragraph does not cite: a fix adds no source")
        elif isinstance(op, UpdateStudy):
            target = f"studies[{op.id}].finding"
            if set(op.set) != {"finding"}:
                found.append(f"operations[{i}] sets {sorted(op.set)}: a valve fix sets `finding` of a study only")
        else:
            found.append(
                f"operations[{i}] is {op.op}: a valve fix may hold replace_paragraph, remove_paragraph and "
                "update_study of `finding` only"
            )
        targets.append(target)
    return targets, found


def _without_free_text(data: dict[str, Any]) -> dict[str, Any]:
    """The card data with every free-text item blanked: what a valve fix must leave exactly as it is."""
    d = copy.deepcopy(data)
    d["level_reason"] = d["subgroups"] = d["early_signals"] = None
    d["core_claim"] = {"text": None, "sources": d["core_claim"]["sources"]}  # the text is free, its sources are not
    if isinstance(d.get("contested"), dict):
        d["contested"]["reason"] = None
    for badge in d["badges"].values():
        badge["reason"] = None
    for study in d["studies"]:
        study["finding"] = None
    return d


def apply_valve(base_text: str, ops: OpsFile, targets: set[str]) -> tuple[str | None, list[str]]:
    """V4, the guard: apply a valve fix to ``base_text`` with the ordinary operation code; (the new text, []) or
    (None, what is wrong). Refused when an operation is not free text, names a target no wording finding names, or the
    result differs from the text in anything but free text (level, badges, contested mark, layer, links, case
    definitions, roles and every other structured study field are compared)."""
    try:
        data = yaml.safe_load(base_text)
        card = cards.Card.model_validate(data)
    except (yaml.YAMLError, ValidationError) as exc:
        return None, [f"the text the fix is applied to is not a card: {str(exc).splitlines()[0]}"]
    op_targets, found = _valve_op_targets(card, ops)
    found += [
        f"operations[{i}] changes {t}, which no wording finding of this stage names"
        for i, t in enumerate(op_targets)
        if t is not None and t not in targets
    ]
    if found:
        return None, found
    try:
        new_text = apply_operations(base_text, ops, validate=False)
    except OperationError as exc:
        return None, [str(exc)]
    if _without_free_text(yaml.safe_load(new_text)) != _without_free_text(data):
        return None, ["the fix changes more than free text (a structured field differs); nothing applied"]
    return new_text, []


def _round_base(tag: str) -> str:
    return f"C{correction_number(tag)}"


def _exception_classes(cfg: Config, slug: str, k: int) -> dict[str, list[tuple[str | None, str | None]]] | None:
    """V8: the classification of the audit records of ``slug``'s round ``k`` that a card-reviewer recorded in
    ``audits/<date>-<slug>-C<k>-classification.yaml``; None for any other slug or round, or when none is recorded."""
    if CLASSIFICATION_EXCEPTION.get(slug) != k:
        return None
    pattern = re.compile(rf"^\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(slug)}-C{k}-classification\.yaml$")
    found = (
        [p for p in sorted(cfg.audits_dir.glob("*.yaml")) if pattern.match(p.name)] if cfg.audits_dir.is_dir() else []
    )
    if not found:
        return None
    try:
        data = AuditClassification.model_validate(yaml.safe_load(found[0].read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise PipelineError(f"{found[0]} cannot be read: {str(exc).splitlines()[0]}") from exc
    return {"first": [(c.klass, c.target) for c in data.first], "second": [(c.klass, c.target) for c in data.second]}


def _record_classes(
    record: AuditRecord, recorded: list[tuple[str | None, str | None]] | None
) -> list[tuple[str | None, str | None]]:
    """The class and target of each part of an audit record: its own, or (a record written before the valve, V8)
    the recorded classification when the record has no class at all and the lengths agree."""
    own = [(p.klass, p.target) for p in record.parts]
    if recorded is not None and len(recorded) == len(own) and all(k is None for k, _t in own):
        return recorded
    return own


def _audit_valve_findings(
    audits: Sequence[tuple[str, AuditRecord, list[tuple[str | None, str | None]]]],
) -> list[ValveFinding] | None:
    """V2: the wording findings of valid audits when the valve is open, else None. Open means: none is an
    ``accept_lower``, one at least is a ``reject``, no objecting part of any is ``decisive`` or unclassified, and
    every reject has an objecting part (so an unclassified record, written before the valve, never opens it)."""
    if not any(r.decision == "reject" for _n, r, _c in audits) or any(
        r.decision == "accept_lower" for _n, r, _c in audits
    ):
        return None
    found: list[ValveFinding] = []
    for name, record, classes in audits:
        for i, (klass, target) in enumerate(classes):
            if klass == "decisive" or (klass is None and record.decision == "reject"):
                return None
            if klass == "wording":
                found.append(ValveFinding(f"{name}.parts[{i}]", target, record.parts[i].decision_part))
        if record.decision == "reject" and not any(k == "wording" for k, _t in classes):
            return None
    return found


def _audit_stage_findings(cfg: Config, slug: str, tag: str) -> list[ValveFinding] | None:
    base = _round_base(tag)
    audits = []
    recorded = _exception_classes(cfg, slug, correction_number(tag))
    for name, second in (("first", False), ("second", True)):
        record, _path, _why = _load_card_audit(cfg, slug, second=second, redraft=base)
        if record is None:
            return None
        audits.append((name, record, _record_classes(record, recorded[name] if recorded else None)))
    return _audit_valve_findings(audits)


def _valve_problem_before(cfg: Config, slug: str, tag: str, stage: str) -> str | None:
    """What stops the valve of ``stage`` from being used on attempt ``tag``: the steps before it must have passed."""
    checks = cfg.checks_path(slug, None, tag)
    if not checks.is_file() or not _read_json(checks).get("passed"):
        return f"correction round {tag} has no passed checks"
    r = _load_round(cfg, slug, "", tag)
    if stage != "correction-review" and (
        r is None or r.review is None or not _stage_accepted(cfg, slug, tag, "correction-review", r.review)
    ):
        return f"the correction review has not accepted {tag}"
    if stage == "audit":
        card_review = _load_card_review(cfg, slug, tag)
        if card_review is None or not _stage_accepted(cfg, slug, tag, "card-review", card_review):
            return f"the whole-card review has not accepted {tag}"
        if tag != last_attempt_tag(cfg, slug, _round_base(tag)):
            return "the audits belong to the last attempt of the round"
    return None


def _valve_findings(cfg: Config, slug: str, tag: str, stage: str) -> list[ValveFinding]:
    """The wording findings the valve of ``stage`` in attempt ``tag`` answers. PipelineError when the valve is not open
    there: the steps before the stage must have passed, and the stage's own verdicts must be a reject (or, for the
    audits, two valid records) with only wording findings."""
    if problem := _valve_problem_before(cfg, slug, tag, stage):
        raise PipelineError(f"the valve is not open at the stage {stage}: {problem}")
    if stage == "audit":
        found = _audit_stage_findings(cfg, slug, tag)
    elif stage == "correction-review":
        r = _load_round(cfg, slug, "", tag)
        found = _review_valve_findings(r.review if r else None)
    else:
        found = _review_valve_findings(_load_card_review(cfg, slug, tag))
    if found is None:
        raise PipelineError(
            f"the valve is not open at the stage {stage} of {tag}: it needs a valid reject (for the audits: two valid "
            "audits, one a reject, neither accept_lower) whose every objecting finding is classified `wording`"
        )
    return found


def _valve_stage_key(cfg: Config, slug: str, stage: str, n: str, revision: int) -> tuple[str, str]:
    """(the attempt tag, the valve key) of a valve command; the round must be one the card may have, or (V8) the closed
    round of the exception."""
    if stage not in VALVE_STAGES:
        raise PipelineError(f"--stage is one of {', '.join(VALVE_STAGES)}")
    if not is_correction_round(n):
        raise PipelineError("a valve belongs to a correction round: --round C<k>")
    k = correction_number(n)
    used, _open = correction_round_state(cfg, slug)
    if not (k == used + 1 and k <= max_correction_rounds(slug)) and not (
        stage == "audit" and k == used and _exception_classes(cfg, slug, k) is not None
    ):
        raise PipelineError(f"correction round {n} is not open for a valve: the next round is C{used + 1}")
    if stage == "audit" and revision:
        raise PipelineError("the audits belong to the last attempt of the round: no --revised for --stage audit")
    tag = last_attempt_tag(cfg, slug, n) if stage == "audit" else attempt_tag(n, revision)
    return tag, _valve_key(stage, tag)


def _read_valve_ops(cfg: Config, slug: str, key: str) -> OpsFile:
    path = cfg.valve_path(slug, key)
    try:
        ops = parse_ops(_read_json(path))
    except OperationError as exc:
        raise PipelineError(f"{path} is not a valid operations file: {exc}") from exc
    if ops.card != slug:
        raise PipelineError(f"{path} is for card '{ops.card}', not '{slug}'")
    return ops


def valve_apply(cfg: Config, slug: str, stage: str, n: str, *, revision: int = 0) -> Path:
    """`valve-apply`: apply ``valve/<slug>-<key>.json`` (the orchestrator's wording fix) to the text of the stage with
    the ordinary operation code, run the card validator and the citations check, and write the result as
    ``valve/<slug>-<key>/<slug>.yaml``. Refused (nothing written) when the valve is not open at the stage, when one
    was applied already (one per stage and attempt), when an operation is not free text or names a target no wording
    finding of the stage names, or when the validator or a new citation error fails."""
    tag, key = _valve_stage_key(cfg, slug, stage, n, revision)
    findings = _valve_findings(cfg, slug, tag, stage)
    text_path = cfg.valve_text_path(slug, key)
    if text_path.exists():
        raise PipelineError(f"{text_path} exists: one valve per stage and attempt")
    ops = _read_valve_ops(cfg, slug, key)
    source = _attempt_text_path(cfg, slug, tag, stage)
    base_text = source.read_text(encoding="utf-8")
    new_text, problems = apply_valve(base_text, ops, {f.target for f in findings if f.target})
    if new_text is None:
        raise PipelineError("the wording fix is refused:\n" + "\n".join(problems))
    result: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as tmp:
        _check_applied(cfg, slug, source, base_text, new_text, Path(tmp), result)
    errors = [
        *result["validator"],
        *(f"citations: {r['study']}: {r['code']}: {r['message']}" for r in _new_errors(result)),
    ]
    if errors:
        raise PipelineError("the wording fix fails the checks:\n" + "\n".join(errors))
    _write_text(text_path, new_text)
    _log(cfg, {"event": "valve-apply", "card": slug, "round": tag, "stage": stage})
    return text_path


def valve_check_plan(cfg: Config, slug: str, stage: str, n: str, *, revision: int = 0) -> Path:
    """`valve-check-plan`: write ``valve-check-context/<slug>-<key>.md`` for the card-reviewer's fix check (V5): each
    finding (problem, fix, target), the text of its target before and after the fix, and the cached records of the
    sources that paragraph cites (named by path, not embedded). Nothing else."""
    tag, key = _valve_stage_key(cfg, slug, stage, n, revision)
    findings = _valve_findings(cfg, slug, tag, stage)
    if not cfg.valve_text_path(slug, key).is_file():
        raise PipelineError(f"no applied wording fix for {key}: run `valve-apply {slug} --stage {stage} ...` first")
    ops = _read_valve_ops(cfg, slug, key)
    base = cards.Card.model_validate(
        yaml.safe_load(_attempt_text_path(cfg, slug, tag, stage).read_text(encoding="utf-8"))
    )
    op_targets, _problems = _valve_op_targets(base, ops)
    before = translations.english_items(base)
    reader = citations.CacheReader(cfg.cache_dir)
    parts = [
        f"# Fix check ({stage}, attempt {tag}): `{slug}`",
        "",
        "A wording fix answers each finding below. For each finding say, from this file and the cached records it "
        "names, whether the fix **resolves** it and whether it **adds a claim** the records do not state. Read only "
        "this file and those cached files; fetch nothing. Write "
        f"`{cfg.valve_path(slug, key, '-check.json')}`: "
        '`{"card": "<slug>", "fixes": [{"finding": "<id>", "resolves": true|false, "new_claim": true|false, '
        '"reason": "one line"}]}`, one entry per finding.',
        "",
    ]
    for f in findings:
        item = before.get(f.target or "")
        sources = (
            list(item.sources or [])
            if item and item.sources
            else ([f.target[8:-9]] if f.target and f.target.startswith("studies[") else [])
        )
        after: list[str] = []
        for op, target in zip(ops.operations, op_targets, strict=True):
            if target != f.target:
                continue
            if isinstance(op, ReplaceParagraph):
                after.append(f"{op.text} (sources: {', '.join(op.sources)})")
            elif isinstance(op, UpdateStudy):
                after.append(str(op.set["finding"]))
            else:
                after.append("(the paragraph is removed)")
        parts += [
            f"## Finding {f.id}",
            "",
            f"- target: `{f.target}`",
            f"- problem: {f.problem}",
            *([f"- fix: {f.fix}"] if f.fix else []),
            f"- before: {item.text if item else '(not found)'}",
            *[f"- after: {a}" for a in after or ["(no operation touches this target)"]],
            "- cited records:",
        ]
        for study_id in dict.fromkeys(sources):
            parts += [f"  - {study_id}", *(f"    {line}" for line in _cached_study_files(cfg, study_id, reader))]
        parts.append("")
    parts.append(citations.author_facts_section(base, reader))
    path = cfg.valve_context_path(slug, key)
    _write_text(path, "\n".join(parts))
    return path


def record_valve_check(cfg: Config, slug: str, stage: str, n: str, *, revision: int = 0) -> ValveCheck:
    """`record-valve-check`: validate ``valve/<slug>-<key>-check.json``: one answer for each finding of the stage, no
    other. Passed means every fix resolves its finding and adds no claim (``ValveCheck.passed``)."""
    tag, key = _valve_stage_key(cfg, slug, stage, n, revision)
    findings = _valve_findings(cfg, slug, tag, stage)
    if not cfg.valve_text_path(slug, key).is_file():
        raise PipelineError(f"no applied wording fix for {key}: run `valve-apply {slug} --stage {stage} ...` first")
    path = cfg.valve_path(slug, key, "-check.json")
    try:
        check = ValveCheck.model_validate(_read_json(path))
    except ValidationError as exc:
        raise PipelineError(f"{path} is malformed:\n" + "\n".join(_pydantic_lines(exc))) from exc
    problems = [f"card is '{check.card}', expected '{slug}'"] if check.card != slug else []
    answered = [f.finding for f in check.fixes]
    problems += [f"no answer for the finding {f.id}" for f in findings if f.id not in answered]
    problems += [
        f"an answer for '{a}', which is no finding of this stage" for a in answered if a not in {f.id for f in findings}
    ]
    problems += [f"the finding {a} is answered twice" for a in dict.fromkeys(answered) if answered.count(a) > 1]
    if problems:
        raise PipelineError(f"{path} is not valid:\n" + "\n".join(problems))
    _log(cfg, {"event": "record-valve-check", "card": slug, "round": tag, "stage": stage, "passed": check.passed})
    return check


def _valve_unfinished(cfg: Config, slug: str, tag: str) -> str | None:
    """V6: a review stage of the last attempt opened the valve and the operator did not finish it (the fix not applied,
    its check missing). A refusal of ``publish-card``, like a missing whole-card review: the round stays open."""
    r = _load_round(cfg, slug, "", tag)
    first = r.review if r is not None else None
    for stage, review in (("correction-review", first), ("card-review", _load_card_review(cfg, slug, tag))):
        if stage == "card-review" and (
            first is None or not _stage_accepted(cfg, slug, tag, "correction-review", first)
        ):
            break
        if review is None or _review_valve_findings(review) is None:
            continue
        key = _valve_key(stage, tag)
        if not cfg.valve_text_path(slug, key).is_file():
            return _unfinished_note("valve fix not applied", slug, stage, tag)
        if _read_valve_check(cfg, slug, key) is None:
            return _unfinished_note("valve check missing", slug, stage, tag)
    return None


def _unfinished_note(what: str, slug: str, stage: str, tag: str) -> str:
    flag = "" if stage == "audit" else _attempt_flag(tag)
    return (
        f"{what}: the {stage} of {tag} opened the valve; run `valve-apply {slug} --stage {stage} --round "
        f"{_round_base(tag)}{flag} --run-dir DIR`, then `valve-check-plan`, the card-reviewer and "
        "`record-valve-check`; the round stays open"
    )


def valve_trail_entries(
    cfg: Config, slug: str, chain: Sequence[str], date: str
) -> list[tuple[str, str, Path, dict[str, Any]]]:
    """V7: (key, attempt tag, destination, data) for every valve applied in the attempts of a round: the
    classification (finding ids, class, target), the fix operations and the fix check, for
    ``audits/<date>-<slug>-C<k>-valve-<key>.yaml``."""
    out = []
    for tag in chain:
        for stage in VALVE_STAGES:
            key = _valve_key(stage, tag)
            if (stage == "audit" and tag != chain[-1]) or not cfg.valve_text_path(slug, key).is_file():
                continue
            try:
                findings = _valve_findings(cfg, slug, tag, stage)
            except PipelineError:
                findings = []
            check = _read_valve_check(cfg, slug, key)
            data = {
                "card": slug,
                "round": correction_number(tag),
                "stage": stage,
                "attempt": tag,
                "classification": [
                    {"finding": f.id, "class": "wording", "target": f.target, "problem": f.problem} for f in findings
                ],
                "operations": _read_json(cfg.valve_path(slug, key)).get("operations"),
                "check": None
                if check is None
                else {"passed": check.passed, "fixes": [f.model_dump(mode="json") for f in check.fixes]},
            }
            out.append((key, tag, cfg.audits_dir / f"{date}-{slug}-{_round_base(tag)}-valve-{key}.yaml", data))
    return out


class AuditClassification(_M):
    """V8: a card-reviewer's one-time classification of the two audit records of a round written before the valve: the
    class (and for wording the target) of each part, in order."""

    card: Slug
    round: Annotated[str, StringConstraints(pattern=r"^C[1-9]\d*$")]
    audit_files: list[NonEmptyStr] = []
    first: list[_Classified]
    second: list[_Classified]


def record_audit_classification(cfg: Config, slug: str, n: str) -> Path:
    """`record-audit-classification` (V8): validate ``valve/<slug>-classification.json`` in the run folder, written by
    the card-reviewer in its "classify existing audit" mode, and record it as
    ``audits/<date>-<slug>-C<k>-classification.yaml`` (the date of the round's first audit record there; never
    overwritten). Only the slugs of ``CLASSIFICATION_EXCEPTION``, and only their round. A classification with a decisive
    finding is recorded too: the valve then stays closed and the card stays held back."""
    if not is_correction_round(n) or CLASSIFICATION_EXCEPTION.get(slug) != correction_number(n):
        raise PipelineError(
            f"no classification exception for {slug} round {n} (DECISIONS 2026-11-15 names "
            + ", ".join(f"{s} round C{k}" for s, k in CLASSIFICATION_EXCEPTION.items())
            + ")"
        )
    path = cfg.f("valve", f"{slug}-classification.json")
    try:
        data = AuditClassification.model_validate(_read_json(path))
    except ValidationError as exc:
        raise PipelineError(f"{path} is malformed:\n" + "\n".join(_pydantic_lines(exc))) from exc
    existing = [p for p in whole_card_audit_files(cfg, slug) if re.search(rf"-{n}(-second)?\.yaml$", p.name)]
    firsts = [p for p in existing if p.name.endswith(f"-{n}.yaml")]
    if not firsts:
        raise PipelineError(f"{cfg.audits_dir} holds no audit record of {slug} round {n} to classify")
    problems = [f"card is '{data.card}', expected '{slug}'"] if data.card != slug else []
    if data.round != n:
        problems.append(f"round is '{data.round}', expected '{n}'")
    for name, second in (("first", False), ("second", True)):
        record, _p, why = _load_card_audit(cfg, slug, second=second, redraft=n)
        classes = data.first if name == "first" else data.second
        if record is None:
            problems.append(f"the {name} audit record of the run folder is not valid: {why}")
            continue
        if len(classes) != len(record.parts) or any(c.klass is None for c in classes):
            problems.append(f"{name} needs one class for each of the {len(record.parts)} part(s) of the record")
            continue
        parts = [
            p.model_copy(update={"klass": c.klass, "target": c.target})
            for p, c in zip(record.parts, classes, strict=True)
        ]
        problems += [f"{name}: {m}" for m in _class_problems(record.model_copy(update={"parts": parts}))]
    if problems:
        raise PipelineError(f"{path} is not valid:\n" + "\n".join(problems))
    dest = cfg.audits_dir / f"{firsts[0].name[:10]}-{slug}-{n}-classification.yaml"
    if dest.exists():
        raise PipelineError(f"{dest} already exists; an audit record is never overwritten")
    dumped = data.model_dump(mode="json", by_alias=True)
    dumped["audit_files"] = [p.name for p in existing]
    for name in ("first", "second"):
        dumped[name] = [{k: v for k, v in c.items() if v is not None} for c in dumped[name]]
    _write_text(dest, yaml.safe_dump(dumped, sort_keys=False, allow_unicode=True, width=100))
    return dest


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
            result[o.slug] = apply_operations(text, o.ops_to_apply, validate=False)
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

# The pipeline marker: a git trailer on every commit `pr` makes. `content-paths` reads it. It is plain text that anyone
# can type, so it is a review aid and not a security boundary (docs/pipeline.md, "The content-path check").
PIPELINE_MARKER_KEY = "ME-Atlas-Pipeline"
PIPELINE_MARKER_VALUE = "weekly-run"
PROTECTED_PATHS = ("cards/", "drafts/", "translations/", "audits/")
_MARKER_LINE = re.compile(rf"^{PIPELINE_MARKER_KEY}: {PIPELINE_MARKER_VALUE} (\d{{4}}-\d{{2}}-\d{{2}})$")


def pipeline_marker(date: str) -> str:
    return f"{PIPELINE_MARKER_KEY}: {PIPELINE_MARKER_VALUE} {date}"


def _op_headline(op: Any, base: dict[str, Any]) -> str:
    """A short, one-line change-log text for one operation (no card text)."""
    if isinstance(op, AddStudy):
        return f"Added study {op.study.id}"
    if isinstance(op, AddParagraph):
        return f"Added a paragraph to {op.field}"
    if isinstance(op, ReplaceParagraph):
        return f"Replaced paragraph {op.index} of {op.field}"
    if isinstance(op, UpdateStudy):
        return f"Updated study {op.id}"
    if isinstance(op, RemoveParagraph):
        return f"Removed paragraph {op.index} of {op.field}"
    if isinstance(op, RemoveLink):
        return f"Removed the link to {op.to}"
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
    if isinstance(op, UpdateStudy):
        return [op.id]
    if isinstance(op, (RemoveParagraph, RemoveLink)):
        return []
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
        ops = o.ops_to_apply.operations
        sources = list(dict.fromkeys([o.paper_id, *(s for op in ops for s in _op_sources(op))]))
        if o.final_audit is not None:
            reason, decided_by = o.final_audit.reasons_summary, "ai_audit"
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
        if o.redraft_audit is not None:
            copies.append(
                (
                    cfg.audit_path(o.slug, o.pmid, redraft=True),
                    cfg.audits_dir / f"{date}-{o.slug}-{o.pmid}-L.yaml",
                )
            )
        if o.redraft_second is not None:
            copies.append(
                (
                    cfg.audit_path(o.slug, o.pmid, True, redraft=True),
                    cfg.audits_dir / f"{date}-{o.slug}-{o.pmid}-L-second.yaml",
                )
            )
    folder = cfg.f("audit")
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(raw, dict) or raw.get("paper") is not None:
            continue
        redraft = raw.get("card") != path.stem and path.stem == f"{raw.get('card')}-L"  # a whole-card redraft's audit
        if raw.get("card") != path.stem and not redraft:
            continue
        slug = str(raw["card"])
        try:
            validate_audit_record(
                cfg,
                raw,
                slug=slug,
                key=None,
                source=path,
                context_path=cfg.audit_context_path(slug, None, redraft),
                redraft=redraft,
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
        f"\n\n{COMMIT_TRAILER}\n{pipeline_marker(str(prep['date']))}"
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
# First publication: a whole-card audit moves a draft into cards/
# ---------------------------------------------------------------------------

PUBLICATION_REPORT = "publication-report.md"
# The four audit records a whole card can have in the run folder: the file suffix and the part of the file name.
_AUDIT_SUFFIXES = (("", False, False), ("-second", True, False), ("-L", False, True), ("-L-second", True, True))


@dataclass
class CardPublication:
    """What `publish-card` decides about one draft: the text to publish (None when held back) and why."""

    slug: str
    date: str
    published: bool
    text: str | None
    reasons: list[str]
    records: dict[str, tuple[Path, AuditRecord]]  # file suffix ("", "-second", "-L", "-L-second") to the valid record
    deciding: AuditRecord | None  # the audit that decided: the first (round-L first audit after a redraft)
    would_text: str | None  # the card text the audits give, for the report (also when held back, if there is one)
    would_level: int | None
    draft_text: str
    round_tag: str | None = None  # "C1" for the publication after a correction round; None for a first publication
    open_round: bool = False  # the last attempt was rejected in review and a revised attempt is pending
    invalid_copy: Path | None = (
        None  # S4: the first record's final invalid copy (``.invalid-2.yaml``) to keep in audits/
    )
    wording_fix: bool = False  # the text published carries a wording fix (the valve passed its check at some stage)


def _load_card_audit(
    cfg: Config, slug: str, *, second: bool, redraft: bool | str
) -> tuple[AuditRecord | None, Path, str | None]:
    """The valid whole-card audit record in the run folder, or (None, path, why it is missing or invalid)."""
    path = cfg.audit_path(slug, None, second, redraft)
    if not path.is_file():
        return None, path, _missing_record_note(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        record = validate_audit_record(
            cfg,
            raw,
            slug=slug,
            key=None,
            source=path,
            context_path=cfg.audit_context_path(slug, None, redraft),
            redraft=redraft,
        )
    except yaml.YAMLError as exc:
        return None, path, f"{path.name} is not valid YAML: {str(exc).splitlines()[0]}"
    except (OSError, PipelineError) as exc:
        return None, path, str(exc).replace("\n", "; ")
    return record, path, None


def _same_audit(a: AuditRecord, b: AuditRecord) -> bool:
    return a.decision == b.decision and a.accepted_level == b.accepted_level


def _card_facts(text: str) -> dict[str, str]:
    """The four things a first publication reports: level, contested mark and the two badge values."""
    data = yaml.safe_load(text)
    contested = data.get("contested")
    rungs = contested.get("rungs") if isinstance(contested, dict) else None
    badges = data.get("badges") or {}

    def badge(name: str) -> str:
        value = (badges.get(name) or {}).get("value")
        return "null" if value is None else str(value).lower()

    return {
        "level": str(data.get("level")),
        "contested": "null" if not rungs else "rungs " + ", ".join(str(r) for r in rungs),
        "diagnostic_marker.value": badge("diagnostic_marker"),
        "explains_pem.value": badge("explains_pem"),
    }


def _fact_differences(draft_text: str, other: dict[str, str]) -> list[tuple[str, str, str]]:
    """(field, draft, other) for every field of ``other`` that differs from the draft."""
    draft = _card_facts(draft_text)
    return [(k, draft[k], v) for k, v in other.items() if draft.get(k) != v]


def _published_card_problems(cfg: Config, slug: str, text: str) -> list[str]:
    """The validator's complaints about ``text`` as a card in ``cards/`` (rule V16 included), for that file only."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "cards"
        folder.mkdir()
        path = folder / f"{slug}.yaml"
        path.write_text(text, encoding="utf-8", newline="\n")
        known = {p.stem for p in (*cfg.cards_dir.glob("*.yaml"), *cfg.drafts_dir.glob("*.yaml"))} | {slug}
        _count, issues = cards.validate_paths(
            [path], cards_dir=folder, content_dir=Path("content"), extra_known_slugs=known
        )
    return [str(i).replace(str(path), f"{slug}.yaml") for i in issues if i.file == str(path)]


def _audit_label(record: AuditRecord) -> str:
    return record.decision if record.accepted_level is None else f"{record.decision} at level {record.accepted_level}"


SEQUENTIAL_REJECT = "the first audit decided reject; no second audit was run (sequential audits)"
FIRST_INVALID_TWICE = "the first audit record failed validation twice; no second audit was run"


def _pair_hold_reasons(
    first: AuditRecord | None,
    second: AuditRecord | None,
    first_why: str | None,
    second_why: str | None,
    *,
    second_run: bool = True,
    first_invalid_final: bool = False,
) -> list[str]:
    """B2: why a pair of audits does not go on, or [] when both are valid and decide the same thing (and that is not
    a reject). The text does not depend on which audit said what: the two decisions are named in alphabetical order,
    without saying which audit gave which.

    Audits run in sequence: with no second audit run at all (``second_run`` False), a valid first ``reject`` is a
    complete outcome (S1), and so is a first record that failed validation twice (``first_invalid_final``, S4).
    A second audit that was run anyway is judged by the order-independent texts below (S2)."""
    if not second_run and second is None:
        if first is not None and first.decision == "reject":
            return [SEQUENTIAL_REJECT]
        if first is None and first_invalid_final:
            return [FIRST_INVALID_TWICE]
    if first is None and second is None:
        return [f"no valid first audit: {first_why}; no valid second audit: {second_why}"]
    if first is None or second is None:
        valid, why = (second, first_why) if first is None else (first, second_why)
        assert valid is not None
        if valid.decision == "reject":
            return [f"one audit decided reject and the other audit record is missing or invalid: {why}"]
        return [f"no valid {'first' if first is None else 'second'} audit: {why}"]
    if first.decision == second.decision == "reject":
        return ["both audits decided reject"]
    if not _same_audit(first, second):
        a, b = sorted((_audit_label(first), _audit_label(second)))
        return [f"the two audits differ: one decided {a}, the other {b}"]
    return []


def _record_started(path: Path) -> bool:
    """Whether an audit was run for ``path``: a record, or an invalid one (after the first or second failure)."""
    return any(p.is_file() for p in (path, _sibling(path, ".invalid-1.yaml"), _sibling(path, ".invalid-2.yaml")))


def _hold_pair(
    pub: CardPublication,
    first_path: Path,
    second_path: Path,
    first: AuditRecord | None,
    second: AuditRecord | None,
    first_why: str | None,
    second_why: str | None,
) -> list[str]:
    """The reasons the first and second audit do not publish (empty when they agree). Sets ``pub.invalid_copy`` when
    the first record failed validation twice and no second audit was run (S4)."""
    second_run = _record_started(second_path)
    invalid = _sibling(first_path, ".invalid-2.yaml")
    final_invalid = first is None and not second_run and invalid.is_file()
    if final_invalid:
        pub.invalid_copy = invalid
    return _pair_hold_reasons(
        first, second, first_why, second_why, second_run=second_run, first_invalid_final=final_invalid
    )


def _pending_retry(path: Path) -> str | None:
    """S4: the first record failed validation once and its format retry is not recorded: publish-card waits."""
    once, twice = _sibling(path, ".invalid-1.yaml"), _sibling(path, ".invalid-2.yaml")
    if once.is_file() and not twice.is_file():
        return (
            f"the first audit record {path.name} failed validation once and its format retry is pending "
            f"({once.name}); record the retry (`record-audit --card ... --retry`) before publish-card"
        )
    return None


def whole_card_outcome(cfg: Config, slug: str, date: str) -> CardPublication:
    """Decide the first publication of a draft from the whole-card audit records in ``cfg.run_dir``.

    ``accept`` from both audits (the first and the second, from a fresh auditor): the draft text with ``last_checked``
    set to ``date`` and ``ai_audit``. ``accept_lower`` from both audits at the same level: the one redraft (round L),
    when it passed E4 and the checks, the reviewer accepted it, it is the result of its operations and both round-L
    audits say ``accept``. Anything else (a reject, a missing or invalid record, two audits that differ, a redraft that
    fails a step) holds the card back with the reasons and no text. The text must also validate as a card in cards/.
    """
    draft_path = cfg.drafts_dir / f"{slug}.yaml"
    draft_text = draft_path.read_text(encoding="utf-8")
    _load_card(draft_path)
    records: dict[str, tuple[Path, AuditRecord]] = {}
    problems: dict[str, str] = {}
    for suffix, second, redraft in _AUDIT_SUFFIXES:
        record, path, why = _load_card_audit(cfg, slug, second=second, redraft=redraft)
        if record is not None:
            records[suffix] = (path, record)
        elif why is not None:
            problems[suffix] = why
    pub = CardPublication(slug, date, False, None, [], records, None, None, None, draft_text)

    def held(reason: str) -> CardPublication:
        pub.reasons.append(reason)
        return pub

    first = records.get("", (None, None))[1]
    second = records.get("-second", (None, None))[1]
    if reasons := _hold_pair(
        pub,
        cfg.audit_path(slug, None, False, False),
        cfg.audit_path(slug, None, True, False),
        first,
        second,
        problems.get(""),
        problems.get("-second"),
    ):
        pub.reasons += reasons
        return pub
    assert first is not None and second is not None
    if first.decision == "reject":  # unreachable: two valid and equal rejects are held back above
        return held("both audits decided reject")
    if first.decision == "accept":
        text = _set_last_checked(draft_text, date, "ai_audit")
        pub.deciding, pub.would_text = first, text
        return _finish(cfg, pub, text)
    level = first.accepted_level
    assert level is not None
    pub.would_level = level
    r = _load_round(cfg, slug, "", REDRAFT)
    if r is None:
        return held("no redraft recorded")
    applied_path = cfg.applied_dir(slug, None, REDRAFT) / f"{slug}.yaml"
    if applied_path.is_file():
        pub.would_text = applied_path.read_text(encoding="utf-8")
    if r.ops is None:
        return held(f"redraft failed checks: {r.ops_problem}")
    if ops_problems := redraft_ops_problems(r.ops, level, None):
        return held("redraft failed checks: " + "; ".join(ops_problems))
    if r.checks is None or not r.checks.get("passed"):
        why = _check_failure_summary(r.checks) if r.checks is not None else "it was never applied (no check result)"
        return held(f"redraft failed checks: {why}")
    if r.review is None:
        return held("redraft rejected in review: no review was recorded")
    if r.review.verdict != "accept":
        return held("redraft rejected in review")
    if not applied_path.is_file():
        return held("redraft failed checks: its applied text is missing")
    try:
        rederived = apply_operations(draft_text, r.ops, validate=False)
    except OperationError as exc:
        return held(f"redraft failed checks: its operations do not apply to the draft: {exc}")
    if rederived != pub.would_text:
        return held("redraft failed checks: its applied text does not match its operations")
    first_l = records.get("-L", (None, None))[1]
    second_l = records.get("-L-second", (None, None))[1]
    if first_l is None:
        return held(f"redraft not accepted in audit: no valid record: {problems['-L']}")
    if first_l.decision != "accept":
        return held(f"redraft not accepted in audit: {first_l.decision}")
    if second_l is None:
        return held(f"redraft not accepted in audit: the second audit is not valid: {problems['-L-second']}")
    if second_l.decision != "accept":
        return held(f"redraft not accepted in audit: the second audit decided {second_l.decision}")
    text = _set_last_checked(pub.would_text, date, "ai_audit")
    pub.deciding = first_l
    return _finish(cfg, pub, text)


def correction_outcome(cfg: Config, slug: str, date: str, tag: str, *, exception: bool = False) -> CardPublication:
    """Decide the publication of a draft after correction round ``tag`` (``C1``) from the round's files only.

    Published only when A2 holds, the checks passed, the review says accept, the applied text is what the operations
    give when applied to the current draft, both audits of the corrected text are valid and say accept, and the text
    validates as a card in ``cards/``. Anything else holds the card back with the reasons and no text; two agreeing
    ``accept_lower`` hold it back too (there is no round L after a correction).

    The safety valve (DECISIONS 2026-11-15): a wording-only reject of a review whose fix check passed counts as an
    accept, and its fix is part of the text; when both audits are valid, neither is ``accept_lower``, one is a reject
    and every objecting part is ``wording``, the card is published with the audit-stage fix when its check passed, and
    held back when it did not (``publish-card`` refuses while the fix or its check is missing). ``exception`` is the
    closed round of ``CLASSIFICATION_EXCEPTION``: only the audit-stage valve can publish it.
    """
    draft_path = cfg.drafts_dir / f"{slug}.yaml"
    draft_text = draft_path.read_text(encoding="utf-8")
    draft_card = _load_card(draft_path)
    records: dict[str, tuple[Path, AuditRecord]] = {}
    problems: dict[str, str] = {}
    for suffix, second in ((f"-{tag}", False), (f"-{tag}-second", True)):
        record, path, why = _load_card_audit(cfg, slug, second=second, redraft=tag)
        if record is not None:
            records[suffix] = (path, record)
        elif why is not None:
            problems[suffix] = why
    pub = CardPublication(slug, date, False, None, [], records, None, None, None, draft_text, tag)

    def held(reason: str) -> CardPublication:
        pub.reasons.append(reason)
        return pub

    attempt = last_attempt_tag(cfg, slug, tag)  # R3: the last revised attempt when there is one

    def rejected(cause: str, review: ReviewFile, stage: str) -> CardPublication:
        """The last attempt was rejected: the round stays open when that kind's revision is unused, else it ends. A
        wording-only reject went through the valve, and its fix check failed."""
        if _review_valve_findings(review) is not None:
            why = _valve_failure(cfg, slug, _valve_key(stage, attempt))
            return held(f"{cause}: the wording fix did not pass its check: {why}")
        chain = _attempt_chain(cfg, slug, tag)
        pending, why = _revision_state([_reject(cfg, slug, t) for t in chain])
        if pending:
            pub.open_round = True
            return held(f"{cause}; the revised attempt is pending (round {tag} is not used yet)")
        return held(f"{cause}; {why or 'no revision is open'}")

    r = _load_round(cfg, slug, "", attempt)
    if r is None:
        return held("no correction recorded: there is no ops file")
    applied_path = cfg.applied_dir(slug, None, attempt) / f"{slug}.yaml"
    if applied_path.is_file():
        pub.would_text = applied_path.read_text(encoding="utf-8")
    limit = (
        f"; all {MAX_CHECK_RETRIES} check retries of the round are used"
        if _check_retries_used(cfg, slug, tag) >= MAX_CHECK_RETRIES
        else ""
    )
    if r.ops is None:
        return held(f"correction failed checks: {r.ops_problem}{limit}")
    if ops_problems := correction_ops_problems(r.ops, draft_card.level) + correction_target_problems(
        cfg, slug, attempt, r.ops, draft_card
    ):
        return held("correction failed checks: " + "; ".join(ops_problems) + limit)
    if r.checks is None or not r.checks.get("passed"):
        why = _check_failure_summary(r.checks) if r.checks is not None else "it was never applied (no check result)"
        return held(f"correction failed checks: {why}{limit}")
    if r.review is None:
        return held("correction rejected in review: no review was recorded")
    if not _stage_accepted(cfg, slug, attempt, "correction-review", r.review):
        return rejected("correction rejected in review", r.review, "correction-review")
    card_review = _load_card_review(cfg, slug, attempt)
    if card_review is None:  # run_publish_card refuses this case before it gets here
        return held("whole-card review missing: no valid whole-card review of the last attempt was recorded")
    if not _stage_accepted(cfg, slug, attempt, "card-review", card_review):
        return rejected("whole-card review rejected", card_review, "card-review")
    if not applied_path.is_file():
        return held("correction failed checks: its applied text is missing")
    try:
        rederived = apply_operations(draft_text, r.ops, validate=False)
    except OperationError as exc:
        return held(f"correction failed checks: its operations do not apply to the draft: {exc}")
    if rederived != pub.would_text:
        return held("correction failed checks: its applied text does not match its operations")
    if rederived == draft_text:
        return held("correction failed checks: the correction changes nothing")
    for stage in VALVE_STAGES[:2]:  # the wording fixes of the review stages, in order (re-derived, as the ops are)
        if _valve_passed(cfg, slug, key := _valve_key(stage, attempt)):
            pub.wording_fix = True
            targets = {f.target for f in _valve_findings(cfg, slug, attempt, stage) if f.target}
            fixed, fix_problems = apply_valve(rederived, _read_valve_ops(cfg, slug, key), targets)
            if fixed is None:
                return held(
                    f"correction failed checks: the wording fix of {stage} is refused: " + "; ".join(fix_problems)
                )
            rederived = fixed
    if rederived != _attempt_text_path(cfg, slug, attempt, "audit").read_text(encoding="utf-8"):
        return held("correction failed checks: a wording fix does not match its operations")
    pub.would_text = rederived
    first = records.get(f"-{tag}", (None, None))[1]
    second = records.get(f"-{tag}-second", (None, None))[1]
    classes = _exception_classes(cfg, slug, correction_number(tag))
    first_alone = [("first", first, _record_classes(first, classes["first"] if classes else None))] if first else []
    unrun = second is None and not _record_started(cfg.audit_path(slug, None, True, tag))
    if unrun and _audit_valve_findings(first_alone):  # a wording-only first reject: the second audit goes on
        raise PipelineError(
            "the first audit rejected on wording only: run the second audit before `publish-card` (sequential audits)"
        )
    found = None
    if first is not None and second is not None:
        found = _audit_valve_findings(
            [
                ("first", first, _record_classes(first, classes["first"] if classes else None)),
                ("second", second, _record_classes(second, classes["second"] if classes else None)),
            ]
        )
    if exception and found is None:
        raise PipelineError(
            f"round {tag} is closed and the wording valve is not open on its audit records (a decisive or unclassified "
            "finding, an accept_lower, or no reject): the card stays held back"
        )
    if found is not None:
        return _audit_valve_outcome(cfg, pub, found, rederived, first, second, attempt)
    if reasons := _hold_pair(
        pub,
        cfg.audit_path(slug, None, False, tag),
        cfg.audit_path(slug, None, True, tag),
        first,
        second,
        problems.get(f"-{tag}"),
        problems.get(f"-{tag}-second"),
    ):
        pub.reasons += reasons
        return pub
    assert first is not None and second is not None
    if first.decision == "accept_lower":
        pub.would_level = first.accepted_level
        return held(
            f"the audits of the corrected draft agree on accept_lower (level {first.accepted_level}); "
            "there is no further redraft after a correction"
        )
    text = _set_last_checked(rederived, date, "ai_audit")
    pub.deciding = first
    return _finish(cfg, pub, text)


def _audit_valve_outcome(
    cfg: Config,
    pub: CardPublication,
    found: list[ValveFinding],
    audited_text: str,
    first: AuditRecord | None,
    second: AuditRecord | None,
    attempt: str,
) -> CardPublication:
    """V6: the audit-stage valve is open. Published with the fix when its check passed; held back, naming the failed
    answers, when it did not; refused (the round stays open) when the fix was not applied or its check is missing."""
    assert first is not None and second is not None
    slug, key = pub.slug, _valve_key("audit", attempt)
    if not cfg.valve_text_path(slug, key).is_file():
        raise PipelineError(_unfinished_note("valve fix not applied", slug, "audit", attempt))
    if (check := _read_valve_check(cfg, slug, key)) is None:
        raise PipelineError(_unfinished_note("valve check missing", slug, "audit", attempt))
    text, problems = apply_valve(audited_text, _read_valve_ops(cfg, slug, key), {f.target for f in found if f.target})
    if text is None or text != cfg.valve_text_path(slug, key).read_text(encoding="utf-8"):
        pub.reasons.append(
            "correction failed checks: the wording fix does not match its operations " + "; ".join(problems)
        )
        return pub
    pub.would_text = text
    pub.deciding = next((r for r in (first, second) if r.decision == "accept"), first)
    if not check.passed:
        pub.reasons.append("the wording fix did not pass its check: " + _valve_failure(cfg, slug, key))
        return pub
    pub.wording_fix = True
    return _finish(cfg, pub, _set_last_checked(text, pub.date, "ai_audit"))


def _finish(cfg: Config, pub: CardPublication, text: str) -> CardPublication:
    """The audits agree: publish ``text`` unless it does not validate as a card in ``cards/``."""
    if issues := _published_card_problems(cfg, pub.slug, text):
        pub.reasons.append("the card to publish does not validate: " + "; ".join(issues))
        return pub
    pub.published, pub.text = True, text
    return pub


def _publication_differences(pub: CardPublication) -> tuple[list[tuple[str, str, str]], str]:
    """The fields that differ between the draft and what is published (or, held back, what the audits give), and a
    note on where the second column comes from."""
    if pub.would_text is not None:
        note = "what is published" if pub.published else "what the audits would give, from the redraft or correction"
        return _fact_differences(pub.draft_text, _card_facts(pub.would_text)), note
    if pub.would_level is not None:
        note = "the level the audits accept; the other fields would come from a redraft that does not exist"
        draft = _card_facts(pub.draft_text)
        return _fact_differences(pub.draft_text, {**draft, "level": str(pub.would_level)}), note
    return [], "the audits give no card text"


def _publication_report(pub: CardPublication) -> str:
    diffs, note = _publication_differences(pub)
    final = _card_facts(pub.text)["level"] if pub.text is not None else None
    after = f" after correction round {correction_number(pub.round_tag)}" if pub.round_tag else ""
    lines = [f"# First publication of {pub.slug}{after}", ""]
    if pub.published:
        lines.append(f"Outcome: published at level {final} ({pub.date}).")
        if pub.wording_fix:
            lines.append("The card is published after a wording fix (the valve); its trail is in `audits/`.")
    else:
        lines.append("Outcome: held back. The draft stays in `drafts/`; no card is written.")
        lines += [f"Held back: {reason}" for reason in pub.reasons]
        if pub.round_tag and not pub.open_round and correction_number(pub.round_tag) >= max_correction_rounds(pub.slug):
            lines.append(
                f"Correction rounds used: {correction_number(pub.round_tag)} of {max_correction_rounds(pub.slug)}; "
                "the card stays held back and is listed for the founder."
            )
    lines += [
        "",
        "## Differences between the draft and what is published" if pub.published else "## What the audits would give",
        "",
    ]
    if not pub.published and (pub.would_text is not None or pub.would_level is not None):
        lines += [f"Source: {note}.", ""]
    if pub.published or pub.would_text is not None or pub.would_level is not None:
        if diffs:
            lines += [
                "| Field | Draft | Published |" if pub.published else "| Field | Draft | Audits |",
                "| --- | --- | --- |",
            ]
            lines += [f"| {_cell(k)} | {_cell(a)} | {_cell(b)} |" for k, a, b in diffs]
        else:
            lines.append("No difference.")
    else:
        lines.append("None: the audits give no card text.")
    lines += ["", "## The audits", ""]
    names = {"": "First audit", "-second": "Second audit", "-L": "First audit of the redraft"}
    names["-L-second"] = "Second audit of the redraft"
    if pub.round_tag:
        names[f"-{pub.round_tag}"] = "First audit of the corrected draft"
        names[f"-{pub.round_tag}-second"] = "Second audit of the corrected draft"
    if not pub.records:
        lines.append("No valid audit record.")
    for suffix, (path, record) in pub.records.items():
        level = f", accepted level {record.accepted_level}" if record.accepted_level is not None else ""
        lines += [
            f"### {names[suffix]} ({path.name})",
            "",
            f"- decision: {record.decision}{level}",
            f"- reasons_summary: {record.reasons_summary}",
            f"- would_change: {record.would_change}",
            "",
        ]
    return "\n".join(lines).rstrip("\n") + "\n"


def publication_changelog(cfg: Config, pub: CardPublication) -> tuple[Path, str]:
    """The new text of ``cards/changelog.yaml`` with the one entry of this first publication; checked before return."""
    assert pub.published and pub.text is not None and pub.deciding is not None
    final = _card_facts(pub.text)
    change = f"First publication at level {final['level']}"
    if pub.round_tag:
        change += f" after correction round {correction_number(pub.round_tag)}"
        if pub.wording_fix:
            change += " and a wording fix"
    names = {"level": "level", "contested": "contested mark", "diagnostic_marker.value": "diagnostic_marker badge"}
    names["explains_pem.value"] = "explains_pem badge"
    for field_name, was, _now in _fact_differences(pub.draft_text, final):
        change += f"; the draft had {names[field_name]} {was}"
    sources = list(dict.fromkeys(ev.source for part in pub.deciding.parts for ev in part.evidence))
    entry = {
        "date": dt.date.fromisoformat(pub.date),
        "card": pub.slug,
        "change": change,
        "reason": pub.deciding.reasons_summary,
        "sources": sources,
        "tier": 2,
        "decided_by": "ai_audit",
    }
    path = cfg.cards_dir / CHANGELOG_NAME
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    dumped = yaml.safe_dump([entry], sort_keys=False, allow_unicode=True, default_flow_style=False, width=100)
    text = (existing.rstrip("\n") + "\n" + dumped) if existing.strip() not in ("", "[]") else dumped
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / CHANGELOG_NAME
        log.write_text(text, encoding="utf-8", newline="\n")
        for card in {e["card"] for e in yaml.safe_load(text)}:
            (Path(tmp) / f"{card}.yaml").write_text("", encoding="utf-8")
        issues = cards.validate_changelog_file(log, today=dt.date.fromisoformat(pub.date))
    if issues:
        raise PipelineError("the new change-log entry does not validate:\n" + "\n".join(map(str, issues)))
    return path, text


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _added_sentences(cfg: Config, slug: str, tag: str) -> list[dict[str, Any]]:
    """S3: the ``add_sentence`` operations of attempt ``tag`` as the trail records them: target, text, the audit part
    answered and the quotes of that part's evidence (the sources and quotes the sentence may rest on)."""
    r = _load_round(cfg, slug, "", tag)
    if r is None or r.ops is None:
        return []
    parts = {(n, i): part for n, i, part, _d in objecting_audit_parts(cfg, slug, correction_number(tag))}
    out = []
    for op in r.ops.operations:
        if isinstance(op, AddSentence):
            part = parts.get((op.answers.record, op.answers.part))
            out.append(
                {
                    "target": op.target,
                    "text": op.text,
                    "answers": {"record": op.answers.record, "part": op.answers.part},
                    "quotes": [{"source": e.source, "quote": e.quote} for e in part.evidence] if part else [],
                }
            )
    return out


def correction_trail(
    cfg: Config, slug: str, tag: str, draft_bytes: bytes, answered: list[Path], audits_run: list[str]
) -> dict[str, Any]:
    """The trail record of a correction round (A8): what the round answered and what it did, in the order of the
    contract; the card, the round, the audit files it answered, the draft's sha256 before the correction, the
    operations, the checks result, the review, the whole-card review (``card_review``, only when one was recorded)
    and ``audits_run``: the audit files copied to ``audits/`` for the last attempt (none for an earlier attempt).
    ``pre_card_review`` is the whole-card review of the unchanged draft (only when one was recorded for the round;
    older trails have none)."""
    ops_file = cfg.ops_path(slug, None, tag)
    operations: Any = None
    try:
        raw = json.loads(ops_file.read_text(encoding="utf-8"))
        operations = raw.get("operations") if isinstance(raw, dict) else None
    except (OSError, ValueError):
        operations = None
    checks_file = cfg.checks_path(slug, None, tag)
    checks: dict[str, Any] = {"passed": None, "errors": ["there is no checks record"]}
    if checks_file.is_file():
        try:
            record = json.loads(checks_file.read_text(encoding="utf-8"))
            checks = {"passed": bool(record.get("passed")), "errors": _check_error_lines(record)}
        except (OSError, ValueError, AttributeError):
            checks = {"passed": None, "errors": ["the checks record is not readable"]}
    review: dict[str, Any] = {"verdict": None, "findings": []}
    r = _load_round(cfg, slug, "", tag)
    if r is not None and r.review is not None:
        review = {"verdict": r.review.verdict, "findings": _finding_dicts(r.review.findings)}
    trail: dict[str, Any] = {
        "card": slug,
        "round": correction_number(tag),
        "revision_rule": REVISION_RULE,
        "answered": [p.name for p in answered],
        "draft_sha256": _sha256(draft_bytes),
    }
    if (pre_review := _load_card_review(cfg, slug, f"C{correction_number(tag)}-pre")) is not None:
        trail["pre_card_review"] = {
            "verdict": pre_review.verdict,
            "findings": _finding_dicts(pre_review.findings),
        }
    trail |= {"operations": operations, "checks": checks, "review": review}
    if added := _added_sentences(cfg, slug, tag):
        trail["added_sentences"] = added
    if (card_review := _load_card_review(cfg, slug, tag)) is not None:
        trail["card_review"] = {
            "verdict": card_review.verdict,
            "findings": _finding_dicts(card_review.findings),
        }
    trail["audits_run"] = audits_run
    return trail


def _write_invalid_copy(src: Path, dest: Path, slug: str) -> None:
    """S4: keep the final invalid first record in ``audits/``. A record that is a whole-card mapping of ``slug`` is
    copied byte for byte; any other (unreadable, no ``card``, another card, a ``paper``) is kept as ``raw_text`` in a
    small record of ``slug``, so that the guard that counts the audit records of a card can read the file."""
    raw_text = src.read_text(encoding="utf-8", errors="replace")
    try:
        raw = yaml.safe_load(raw_text)
    except yaml.YAMLError:
        raw = None
    if isinstance(raw, dict) and raw.get("card") == slug and raw.get("paper") is None:
        shutil.copyfile(src, dest)
        return
    note = "this record failed validation twice and could not be kept as written: its text is in raw_text"
    _write_text(dest, yaml.safe_dump({"card": slug, "note": note, "raw_text": raw_text}, sort_keys=False, width=100))


def run_publish_card(
    cfg: Config,
    slug: str,
    date: str,
    *,
    dry_run: bool,
    out: Callable[[str], None] = print,
    round_: str | None = None,
) -> int:
    """`publish-card`: decide, write ``publication-report.md`` and, when both audits allow it, move the draft into
    ``cards/``. Exit 0 for a decision (published or held back), 1 for a refusal (nothing written).

    With ``round_`` ``C<k>`` the decision is about the draft after that correction round, from the round's files; the
    audit records and a trail record of the round are copied to ``audits/`` whatever the decision.
    """
    card_path = cfg.cards_dir / f"{slug}.yaml"
    draft_path = cfg.drafts_dir / f"{slug}.yaml"
    if card_path.exists():
        raise PipelineError(f"{card_path} already exists; a card is published once")
    if not draft_path.is_file():
        raise PipelineError(f"no draft {draft_path} to publish")
    answered: list[Path] = []
    trails: list[tuple[Path, dict[str, Any]]] = []
    first_suffix = "" if round_ is None else f"-{round_}"

    def audit_copies(pub: CardPublication) -> tuple[list[tuple[Path, Path]], list[tuple[Path, Path]]]:
        """The valid records to copy, and (S4) the final invalid first record."""
        copies = [
            (path, cfg.audits_dir / f"{date}-{slug}{suffix}.yaml") for suffix, (path, _record) in pub.records.items()
        ]
        invalid = [(pub.invalid_copy, cfg.audits_dir / f"{date}-{slug}{first_suffix}-invalid.yaml")]
        return copies, invalid if pub.invalid_copy is not None else []

    if round_ is None:
        pub = whole_card_outcome(cfg, slug, date)
        copies, invalid_copies = audit_copies(pub)
    else:
        if not is_correction_round(round_):
            raise PipelineError(f"publish-card --round takes a correction round (C1, C2, ...), not {round_!r}")
        k = correction_number(round_)
        used, _open = correction_round_state(cfg, slug)
        # V8: the closed round of the classification exception may publish through the audit-stage valve only
        exception = k == used and _exception_classes(cfg, slug, k) is not None
        if not exception and (k != used + 1 or k > max_correction_rounds(slug)):
            raise PipelineError(
                f"correction round {round_} is not allowed: the next round is C{used + 1}, and a card gets at most "
                f"{max_correction_rounds(slug)} correction round(s)"
            )
        if not cfg.ops_path(slug, None, round_).is_file():
            raise PipelineError(f"no correction recorded: {cfg.ops_path(slug, None, round_)} does not exist")
        chain = _attempt_chain(cfg, slug, round_)
        for later in chain[1:]:
            if problem := _revision_problem(cfg, slug, round_, later):
                raise PipelineError(problem)
        if len(chain) > 1 and (problem := _draft_problem(cfg, slug, round_)):
            raise PipelineError(problem)
        answered = [
            p for p in whole_card_audit_files(cfg, slug) if not re.search(rf"-C{k}(-second|-invalid)?\.yaml$", p.name)
        ]
        if (note := _valve_unfinished(cfg, slug, last_attempt_tag(cfg, slug, round_))) is not None:
            raise PipelineError(note)
        pub = correction_outcome(cfg, slug, date, round_, exception=exception)
        copies, invalid_copies = ([], []) if exception else audit_copies(pub)  # the closed round has them already
        audits_run = [dest.name for _src, dest in (*copies, *invalid_copies)]
        draft_bytes = draft_path.read_bytes()
        existing_trails = _attempt_trails(cfg, slug)
        valves = valve_trail_entries(cfg, slug, chain, date)
        trails += [(dest, data) for _key, _tag, dest, data in valves]
        for i, tag in enumerate([] if exception else chain):
            last = i == len(chain) - 1
            trail = correction_trail(cfg, slug, tag, draft_bytes, answered, audits_run if last else [])
            if here := {
                key: {"file": dest.name, "passed": (data["check"] or {}).get("passed")}
                for key, vtag, dest, data in valves
                if vtag == tag
            }:
                trail["valve"] = here
            earlier_path = existing_trails.get((k, i))
            if earlier_path is None:
                name = f"{date}-{slug}-{round_}-correction{ATTEMPT_SUFFIXES[i]}.yaml"
                trails.append((cfg.audits_dir / name, trail))
            elif i > 0 and last:
                raise PipelineError(f"{earlier_path} already exists; an audit record is never overwritten")
            else:
                # R6: an earlier attempt's trail is written once; an existing one (any date) must say the same.
                earlier = yaml.safe_load(earlier_path.read_text(encoding="utf-8"))
                keys = ("card", "round", "draft_sha256", "operations")
                same = isinstance(earlier, dict) and all(earlier.get(x) == trail[x] for x in keys)
                same = same and (earlier.get("review") or {}).get("verdict") == trail["review"]["verdict"]
                if not same:
                    raise PipelineError(
                        f"{earlier_path} exists and differs from attempt {tag} in this run folder; "
                        "an audit record is never overwritten"
                    )
    if round_ is not None:
        attempt = last_attempt_tag(cfg, slug, round_)
        last = _load_round(cfg, slug, "", attempt)
        accepted = (
            last is not None
            and last.review is not None
            and _stage_accepted(cfg, slug, attempt, "correction-review", last.review)
        )
        if accepted and _load_card_review(cfg, slug, attempt) is None:
            # A skipped step of the operator, not an agent decision: it must not use up the round.
            raise PipelineError(
                f"the whole-card review of correction round {attempt} is missing or not valid; run "
                f"`card-review-plan {slug} --round {round_}{_attempt_flag(attempt)} --out DIR`, "
                f"the card-reviewer, then `record-review --card-review{_attempt_flag(attempt)}`; the round stays open"
            )
    if first_suffix not in pub.records and (
        pending := _pending_retry(cfg.audit_path(slug, None, False, round_ or False))
    ):
        raise PipelineError(pending)
    changelog = publication_changelog(cfg, pub) if pub.published else None
    targets = [dest for _src, dest in (*copies, *invalid_copies)] + [dest for dest, _data in trails]
    if not dry_run:
        for dest in targets:
            if dest.exists():
                raise PipelineError(f"{dest} already exists; an audit record is never overwritten")
    if round_ is None and (refusal := _first_publication_refusal(cfg, slug)) is not None:
        raise PipelineError(refusal)
    report = _publication_report(pub)
    _write_text(cfg.f(PUBLICATION_REPORT), report)
    out(report.rstrip("\n"))
    if dry_run:
        out(f"Dry run: only {cfg.f(PUBLICATION_REPORT)} was written.")
        return 0
    if pub.published:
        assert pub.text is not None and changelog is not None
        _write_text(card_path, pub.text)
        draft_path.unlink()
        _write_text(changelog[0], changelog[1])
    for src, dest in copies:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    for src, dest in invalid_copies:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write_invalid_copy(src, dest, slug)
    for dest, data in trails:
        _write_text(dest, yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100))
    out(f"The commit must end with the trailer: {pipeline_marker(date)}")
    return 0


# ---------------------------------------------------------------------------
# Content-path check: protected content paths change only through the pipeline
# ---------------------------------------------------------------------------


def commit_is_marked(message: str) -> bool:
    """True when the last paragraph of a commit message (not its only one) has the exact marker line with a real date.

    The key, the word ``weekly-run`` and the single spaces must match exactly; the date must be a real ISO date.
    """
    paragraphs = [p for p in re.split(r"\n\s*\n", message.strip().replace("\r\n", "\n")) if p.strip()]
    if len(paragraphs) < 2:
        return False
    for line in paragraphs[-1].split("\n"):
        match = _MARKER_LINE.match(line)
        if match:
            try:
                dt.date.fromisoformat(match.group(1))
            except ValueError:
                return False
            return True
    return False


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise PipelineError(f"git {' '.join(args)} failed: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout


def _is_protected(path: str) -> bool:
    return path.startswith(PROTECTED_PATHS)


def check_content_paths(repo: Path, base: str, head: str) -> tuple[list[str], dict[str, list[str]]]:
    """The files changed from the merge base of ``base`` and ``head`` to ``head``, and the offences.

    The offences map each protected file to the unmarked commits that touch it. A non-merge commit in ``base..head``
    without the marker that changes a protected path is an offence; so is a merge commit whose own combined diff (the
    changes taken from neither parent) touches one. A marked commit is never an offence, whatever it changes.
    """
    merge_base = _git(repo, "merge-base", base, head).strip()
    changed = [p for p in _git(repo, "diff", "--name-only", "--no-renames", "-z", merge_base, head).split("\0") if p]
    offences: dict[str, list[str]] = {}
    for sha in _git(repo, "rev-list", "--reverse", f"{base}..{head}").split():
        parents = _git(repo, "show", "-s", "--format=%P", sha).split()
        if len(parents) > 1:  # a merge commit: only what it changes on its own counts, and it cannot carry the marker
            paths = _git(repo, "diff-tree", "-c", "--no-commit-id", "--name-only", "--no-renames", "-r", "-z", sha)
        else:
            if commit_is_marked(_git(repo, "show", "-s", "--format=%B", sha)):
                continue
            paths = _git(repo, "diff-tree", "--root", "--no-commit-id", "--name-only", "--no-renames", "-r", "-z", sha)
        for path in sorted({q for q in paths.split("\0") if q and _is_protected(q)}):
            offences.setdefault(path, []).append(sha)
    return changed, offences


def run_content_paths(repo: Path, base: str, head: str, out: Callable[[str], None] = print) -> int:
    changed, offences = check_content_paths(repo, base, head)
    protected = [q for q in changed if _is_protected(q)]
    out(f"{len(changed)} file(s) changed from the merge base of {base} to {head}; {len(protected)} protected.")
    if not offences:
        if protected:
            out("PASS: every protected path is changed only by commits marked as the pipeline's.")
        else:
            out("PASS: no protected content path is changed.")
        return 0
    out(f"FAIL: protected content paths ({', '.join(PROTECTED_PATHS)}) changed by commits without the marker:")
    for path, shas in sorted(offences.items()):
        out(f"  {path}")
        for sha in shas:
            subject = _git(repo, "show", "-s", "--format=%s", sha).strip()
            out(f"    {sha[:10]} {subject}")
    out(f"The marker is the trailer '{pipeline_marker('YYYY-MM-DD')}' (see docs/pipeline.md).")
    return 1


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _date(text: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {text!r}") from exc


def _round_arg(text: str) -> int | str:
    """A round on the command line: 1, 2, L (the one redraft after an accept_lower) or C<k> (a correction round)."""
    if text.upper() == REDRAFT:
        return REDRAFT
    if text in ("1", "2"):
        return int(text)
    if is_correction_round(text.upper()):
        return text.upper()
    raise argparse.ArgumentTypeError(f"{text!r} is not a round: use 1, 2, {REDRAFT} or C1, C2, ...")


def _audit_round_arg(text: str) -> str:
    """A round of an audit: L or C<k>."""
    value = _round_arg(text)
    if not isinstance(value, str):
        raise argparse.ArgumentTypeError(f"{text!r} is not a round of an audit: use {REDRAFT} or C1, C2, ...")
    return value


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
    app.add_argument(
        "--round", type=_round_arg, default=1, help="1, 2, L (the redraft after accept_lower) or C<k> (a correction)"
    )
    app.add_argument("--audit", type=Path, help="with --round L for a whole card: the first audit's record")
    _add_revision_flags(app, "with --round C<k>")

    rev = sub.add_parser("record-review", parents=[common], help="validate a review file")
    rev.add_argument("slug")
    rev.add_argument(
        "pmid",
        nargs="?",
        metavar="paper",
        help="a PMID, pmid:<pmid>, doi:<doi> or a PPR id (a DOI-only preprint); left out for a whole-card redraft",
    )
    rev.add_argument(
        "--round", type=_round_arg, default=1, help="1, 2, L (the redraft after accept_lower) or C<k> (a correction)"
    )
    _add_revision_flags(rev, "with --round C<k>: the review of")
    rev.add_argument(
        "--pre",
        action="store_true",
        help="with --card-review: the whole-card review of the unchanged draft before drafting",
    )
    rev.add_argument(
        "--card-review",
        action="store_true",
        help="with --round C<k>: the whole-card review (review/<slug>-card-C<k>[-pre|-revised[2-4]].json)",
    )

    aplan = sub.add_parser(
        "audit-plan", parents=[common], help="write the auditor's context file for one change or one whole card"
    )
    aplan.add_argument("slug", nargs="?")
    aplan.add_argument("pmid", nargs="?", metavar="paper", help="a PMID, pmid:<pmid>, doi:<doi> or a PPR id")
    aplan.add_argument("--card", metavar="SLUG", help="audit the whole card instead of one change")
    aplan.add_argument("--out", type=Path, help="with --card: write <OUT>/audit-context/<slug>.md (default: the run)")
    aplan.add_argument(
        "--round",
        type=_audit_round_arg,
        help="L: audit the redraft after an accept_lower; C<k>: audit the corrected draft (with --card)",
    )

    arec = sub.add_parser("record-audit", parents=[common], help="validate an audit record")
    arec.add_argument("slug", nargs="?")
    arec.add_argument("pmid", nargs="?", metavar="paper", help="a PMID, pmid:<pmid>, doi:<doi> or a PPR id")
    arec.add_argument("--card", metavar="SLUG", help="a whole-card audit (needs --file)")
    arec.add_argument("--file", type=Path, help="with --card: the record the auditor wrote")
    arec.add_argument("--second", action="store_true", help="the consistency run (audit/<slug>-<key>-second.yaml)")
    arec.add_argument("--out", type=Path, help="with --card: the folder audit-plan --out wrote to")
    arec.add_argument(
        "--round",
        type=_audit_round_arg,
        help="L: the audit of the redraft after an accept_lower; C<k>: of a correction",
    )
    arec.add_argument(
        "--retry",
        action="store_true",
        help="validate the one format retry of a record that failed validation (the decision may not change)",
    )

    rplan = sub.add_parser(
        "redraft-plan",
        parents=[common],
        help="write the drafter's context for the one redraft after an auditor's accept_lower",
    )
    rplan.add_argument("slug", nargs="?")
    rplan.add_argument("pmid", nargs="?", metavar="paper", help="a PMID, pmid:<pmid>, doi:<doi> or a PPR id")
    rplan.add_argument("--card", metavar="SLUG", help="redraft a whole card (needs --audit)")
    rplan.add_argument("--audit", type=Path, help="with --card: the first audit's record (accept_lower)")
    rplan.add_argument("--out", type=Path, help="with --card: write <OUT>/redraft-context/<slug>.md (default: the run)")

    cplan = sub.add_parser(
        "correction-plan",
        parents=[common],
        help="write the drafter's context for the correction of a held-back draft (--out DIR)",
    )
    cplan.add_argument("slug")
    cplan.add_argument("--out", type=Path, help="write <OUT>/correction-context/<slug>-C<k>.md (default: --run-dir)")

    crplan = sub.add_parser(
        "card-review-plan",
        parents=[common],
        help="write the card-reviewer's context for the whole-card review of a correction attempt (--out DIR)",
    )
    crplan.add_argument("slug")
    crplan.add_argument("--round", type=_audit_round_arg, required=True, help="C<k>: the correction round")
    _add_revision_flags(crplan, "the review of")
    crplan.add_argument(
        "--pre", action="store_true", help="the unchanged held-back draft, before drafting the correction"
    )
    crplan.add_argument(
        "--out",
        type=Path,
        help="write <OUT>/card-review-context/<slug>-C<k>[-pre|-revised[2-4]].md (default: --run-dir)",
    )

    for name, text in (
        (
            "valve-apply",
            "apply the orchestrator's wording fix (valve/<slug>-<key>.json) to a stage's text, with the guard",
        ),
        ("valve-check-plan", "write the card-reviewer's fix-check context for a stage's wording fix"),
        ("record-valve-check", "validate the card-reviewer's fix check of a stage's wording fix"),
    ):
        valve = sub.add_parser(name, parents=[common], help=text + " (--run-dir DIR)")
        valve.add_argument("slug")
        valve.add_argument("--stage", required=True, choices=VALVE_STAGES, help="the stage that opened the valve")
        valve.add_argument("--round", type=_audit_round_arg, required=True, help="C<k>: the correction round")
        _add_revision_flags(valve, "not for --stage audit")

    rac = sub.add_parser(
        "record-audit-classification",
        parents=[common],
        help="record the card-reviewer's classification of the audit records of an exception card (--run-dir DIR)",
    )
    rac.add_argument("slug")
    rac.add_argument("--round", type=_audit_round_arg, required=True, help="C<k>: the correction round")

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

    pc = sub.add_parser(
        "publish-card",
        parents=[common],
        help="first publication: move a draft into cards/ when two whole-card audits allow it (--run-dir DIR)",
    )
    pc.add_argument("slug")
    pc.add_argument("--date", type=_date, metavar="YYYY-MM-DD", help="default: today")
    pc.add_argument("--dry-run", action="store_true", help="write only DIR/publication-report.md")
    pc.add_argument(
        "--round",
        type=_round_arg,
        help="C<k>: publish (or hold back) after correction round C<k>, from that round's files",
    )

    cp = sub.add_parser(
        "content-paths",
        help="fail when a commit without the pipeline marker changes cards/, drafts/, translations/ or audits/",
    )
    cp.add_argument("--base", default=BASE_BRANCH, help="default: %(default)s")
    cp.add_argument("--head", default="HEAD", help="default: %(default)s")
    cp.add_argument("--repo", type=Path, default=Path("."), help="the git repository; default: the current folder")
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


def _use_utf8_console() -> None:
    """B1: the printed reports hold characters (β, ≥) that a cp1252 console cannot write; write UTF-8 instead."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8", errors="replace")


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
    _use_utf8_console()
    args = _build_parser().parse_args(argv)
    date: dt.date | None = None
    try:
        if args.command == "content-paths":
            return run_content_paths(args.repo, args.base, args.head, out)
        if args.command == "prepare":
            date = args.date or today or dt.date.today()
            run_dir = args.run_dir or args.pipeline_dir / date.isoformat()
        elif args.command == "publish-card":
            if not args.run_dir:
                raise PipelineError("publish-card needs --run-dir DIR (the folder audit-plan --card --out made)")
            date = args.date or today or dt.date.today()
            run_dir = args.run_dir
        elif args.command in ("valve-apply", "valve-check-plan", "record-valve-check", "record-audit-classification"):
            if not args.run_dir:
                raise PipelineError(f"{args.command} needs --run-dir DIR (the folder of the correction round)")
            run_dir = args.run_dir
        elif args.command in ("correction-plan", "card-review-plan"):
            if not (args.out or args.run_dir):
                raise PipelineError(f"{args.command} needs --out DIR")
            run_dir = args.out or args.run_dir
        elif (
            args.command in ("audit-plan", "record-audit", "redraft-plan")
            and args.card
            and args.out
            and not args.run_dir
        ):
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
        result = apply_ops_file(cfg, args.slug, args.ops, args.round, audit_file=args.audit, revision=args.revision)
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
        out(f"checks: {cfg.checks_path(args.slug, result['key'] or None, result['round'])}")
        if result["passed"]:
            out("PASSED" + (" (no change proposed)" if result["no_change"] else f"; applied card: {result['applied']}"))
            return 0
        if result.get("errors_file"):
            out(f"errors for the drafter: {result['errors_file']}")
        out("FAILED")
        return 1
    if args.command == "record-review":
        if args.card_review:
            if args.pmid is not None or not is_correction_round(args.round):
                raise PipelineError("--card-review is for a whole card in a correction round: --round C<k>, no paper")
            if args.pre and args.revision:
                raise PipelineError("--pre is the review before drafting: it takes no revised attempt")
            tag = f"{args.round}-pre" if args.pre else attempt_tag(args.round, args.revision)
            review = record_review(cfg, args.slug, None, tag, card_review=True, pre=args.pre)
            out(f"whole-card review recorded: {review.verdict}, {len(review.findings)} finding(s)")
            return 0
        if args.pmid is None:
            if args.round != REDRAFT and not is_correction_round(args.round):
                raise PipelineError(
                    "name the paper (a whole-card review exists only for the redraft, --round L, and for a "
                    "correction, --round C<k>)"
                )
            key = None
        else:
            key, _paper = resolve_paper(cfg, args.pmid)
        if args.pre:
            raise PipelineError("--pre goes with --card-review")
        if args.revision and not is_correction_round(args.round):
            raise PipelineError("--revised, --revised2, ... are only for a correction round (--round C<k>)")
        review = record_review(cfg, args.slug, key, attempt_tag(str(args.round), args.revision))
        out(f"review recorded: {review.verdict}, {len(review.findings)} finding(s)")
        return 0
    if args.command == "audit-plan":
        loader = fulltext or live_fulltext_loader(cfg.cache_dir)
        if args.card:
            if args.slug or args.pmid:
                raise PipelineError("give either <slug> <paper> or --card <slug>, not both")
            if is_correction_round(args.round):
                out(str(audit_plan_correction(cfg, args.card, args.round, loader, args.out)))
                return 0
            if not args.round and (refusal := _first_publication_refusal(cfg, args.card)) is not None:
                raise PipelineError(refusal)
            text = build_audit_context(cfg, args.card, None, loader, redraft=bool(args.round))
            path = (args.out or cfg.run_dir) / "audit-context" / f"{args.card}{'-L' if args.round else ''}.md"
        else:
            if not (args.slug and args.pmid):
                raise PipelineError("give <slug> <paper>, or --card <slug>")
            if is_correction_round(args.round):
                raise PipelineError("a correction round is audited for a whole card only: use --card <slug>")
            key, _paper = resolve_paper(cfg, args.pmid)
            text = build_audit_context(cfg, args.slug, key, loader, redraft=bool(args.round))
            path = cfg.audit_context_path(args.slug, key, bool(args.round))
        _write_text(path, text)
        out(str(path))
        return 0
    if args.command == "record-audit":
        if args.card:
            if args.slug or args.pmid:
                raise PipelineError("give either <slug> <paper> or --card <slug> --file PATH, not both")
            record = record_audit(
                cfg,
                args.card,
                None,
                second=args.second,
                file=args.file,
                out_dir=args.out,
                redraft=args.round or False,
                retry=args.retry,
            )
        else:
            if not (args.slug and args.pmid):
                raise PipelineError("give <slug> <paper>, or --card <slug> --file PATH")
            if is_correction_round(args.round):
                raise PipelineError("a correction round is audited for a whole card only: use --card <slug>")
            key, _paper = resolve_paper(cfg, args.pmid)
            record = record_audit(
                cfg, args.slug, key, second=args.second, file=args.file, redraft=args.round or False, retry=args.retry
            )
        level = f" (accepted level {record.accepted_level})" if record.accepted_level is not None else ""
        out(f"audit recorded: {record.decision}{level}, {len(record.parts)} part(s)")
        return 0
    if args.command == "redraft-plan":
        loader = fulltext or live_fulltext_loader(cfg.cache_dir)
        if args.card:
            if args.slug or args.pmid:
                raise PipelineError("give either <slug> <paper> or --card <slug> --audit PATH, not both")
            path = redraft_plan(cfg, args.card, None, loader, audit_file=args.audit)
        else:
            if not (args.slug and args.pmid):
                raise PipelineError("give <slug> <paper>, or --card <slug> --audit PATH")
            key, _paper = resolve_paper(cfg, args.pmid)
            path = redraft_plan(cfg, args.slug, key, loader)
        out(str(path))
        return 0
    if args.command == "correction-plan":
        loader = fulltext or live_fulltext_loader(cfg.cache_dir)
        out(str(correction_plan(cfg, args.slug, loader)))
        return 0
    if args.command == "card-review-plan":
        if not is_correction_round(args.round):
            raise PipelineError("card-review-plan --round takes a correction round (C1, C2, ...)")
        out(str(card_review_plan(cfg, args.slug, args.round, revision=args.revision, pre=args.pre)))
        return 0
    if args.command in ("valve-apply", "valve-check-plan", "record-valve-check"):
        valve_args = (cfg, args.slug, args.stage, args.round)
        valve_kw = {"revision": args.revision}
        if args.command == "valve-apply":
            out(f"wording fix applied: {valve_apply(*valve_args, **valve_kw)}")
        elif args.command == "valve-check-plan":
            out(str(valve_check_plan(*valve_args, **valve_kw)))
        else:
            check = record_valve_check(*valve_args, **valve_kw)
            out(f"fix check recorded: {'PASSED' if check.passed else 'FAILED'}, {len(check.fixes)} fix(es)")
        return 0
    if args.command == "record-audit-classification":
        out(f"classification recorded: {record_audit_classification(cfg, args.slug, args.round)}")
        return 0
    if args.command == "publish-card":
        assert date is not None
        return run_publish_card(cfg, args.slug, date.isoformat(), dry_run=args.dry_run, out=out, round_=args.round)
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
