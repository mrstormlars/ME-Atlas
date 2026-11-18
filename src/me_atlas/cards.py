"""Evidence card data model, loader and validator.

Cards live in ``cards/<slug>.yaml``, drafts in ``drafts/<slug>.yaml`` (same schema) and the public
change log in ``cards/changelog.yaml``. See ``docs/card-format.md`` for the field reference and the
plain-English rules V1-V17.

Command line::

    uv run python -m me_atlas.cards validate [paths...] [--content DIR] [--cards DIR]

With no paths, ``cards/`` and ``drafts/`` (relative to the current directory) are validated. Every
error in every file is reported; the exit code is non-zero if there is at least one.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Discriminator, Field, StrictInt, StringConstraints, Tag, ValidationError

CHANGELOG_NAME = "changelog.yaml"

# Case definitions accepted at every rung (functional spec section 3). Oxford, other, none and unverified are not.
STRICT_CASE_DEFINITIONS = frozenset({"CCC", "ICC", "IOM2015", "Fukuda", "Holmes1988", "CDC_unspecified"})
# Named definitions: a study that records one must also record where it was read and the quoted sentence (V13).
RECOGNISED_CASE_DEFINITIONS = frozenset({"CCC", "ICC", "IOM2015", "Fukuda", "Holmes1988", "CDC_unspecified", "Oxford"})
# Rank for the comparable-quality rule (spec section 3): CCC, ICC and IOM 2015 above Fukuda, Holmes 1988 and
# "CDC criteria, version not stated" (all equal), which are above Oxford. Not a rung criterion; nothing else is ranked.
CASE_DEFINITION_RANK = {
    "CCC": 3,
    "ICC": 3,
    "IOM2015": 3,
    "Fukuda": 2,
    "Holmes1988": 2,
    "CDC_unspecified": 2,
    "Oxford": 1,
    "other": 0,
    "none": 0,
    "unverified": 0,
}
CONTROLLED_DESIGNS = frozenset({"controlled", "intervention_controlled"})

_TODO_RE = re.compile(r"\bTODO\b", re.IGNORECASE)
BANNED_WORDS = ("promising", "breakthrough", "cure", "hope", "proven")
# Whole words, with plain plural / past / adjective forms (e.g. "cured", "hopeful").
_BANNED_RE = re.compile(
    r"\b(promising|breakthroughs?|cure[sd]?|hope[sd]?|hopeful|proven)\b",
    re.IGNORECASE,
)
# The Norwegian (bokmål) equivalents, for the glossary, translated card text and the string files. "bevisst" (conscious)
# is deliberately not matched; "påvist" (detected) is an ordinary finding word and is not matched either.
BANNED_WORDS_NB = ("lovende", "gjennombrudd", "kur", "håp", "bevist")
_BANNED_NB_RE = re.compile(
    r"\b(lovende|gjennombrudd(?:et|ene)?|kur(?:en|er|ene|ert|ere|erte)?|håp(?:et|e|er|a)?|håpefull(?:e|t)?|bevist(?:e)?)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Models (rule V1: schema)
# ---------------------------------------------------------------------------

StudyId = Annotated[str, StringConstraints(pattern=r"^(pmid:\d+|doi:10\.\S+)$")]
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
Url = Annotated[str, StringConstraints(pattern=r"^https?://\S+$")]
Doi = Annotated[str, StringConstraints(pattern=r"^10\.\S+$")]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourcedText(_Model):
    """Free text plus the ids of the studies that support it. Never a bare string."""

    text: NonEmptyStr
    sources: list[StudyId]


def _reason_form(value: object) -> str | None:
    """Which form a reason is written in: one sourced text (a mapping) or a list of them (paragraphs)."""
    if isinstance(value, (dict, SourcedText)):
        return _SINGLE_TAG
    if isinstance(value, list):
        return _PARAGRAPHS_TAG
    return None


_SINGLE_TAG = "sourced_text"
_PARAGRAPHS_TAG = "paragraphs"
# One sourced text, or a non-empty list of them (paragraphs, each with its own sources).
Reason = Annotated[
    Annotated[SourcedText, Tag(_SINGLE_TAG)]
    | Annotated[Annotated[list[SourcedText], Field(min_length=1)], Tag(_PARAGRAPHS_TAG)],
    Discriminator(_reason_form),
]


def paragraphs(reason: SourcedText | list[SourcedText]) -> list[SourcedText]:
    """The paragraphs of a reason: a single sourced text is one paragraph."""
    return list(reason) if isinstance(reason, list) else [reason]


def reason_sources(reason: SourcedText | list[SourcedText] | None) -> list[str]:
    """Every source id cited anywhere in a reason, paragraph by paragraph, in order."""
    return [src for p in paragraphs(reason) for src in p.sources] if reason is not None else []


SUPPORT_LEVELS = ("proposed", "associated", "directional")
LAYERS = ("predisposition", "trigger", "mechanism", "dysfunction")
# Study properties that keep a link at "proposed": a review-type design, or a case definition that is not recognised
# for the ladder (Oxford-only evidence stays at step 1; spec section 3, "Causal map and links").
WEAK_LINK_CASE_DEFINITIONS = frozenset({"none", "other", "unverified", "Oxford"})


class Link(SourcedText):
    """A causal link from this card to another card, a symptom (``symptom:<id>``) or an open question
    (``question:<id>``). Graded on its own scale, never on the card's evidence ladder."""

    to: NonEmptyStr
    support: Literal["proposed", "associated", "directional"]


class Contested(_Model):
    rungs: Annotated[list[StrictInt], Field(min_length=1)]
    reason: Reason


class Badge(_Model):
    value: bool
    reason: Reason | None


class Badges(_Model):
    diagnostic_marker: Badge
    explains_pem: Badge


class WorkingOnIt(_Model):
    name: NonEmptyStr
    url: Url


class LastChecked(_Model):
    date: dt.date
    by: Literal["ai_pair", "ai_audit", "founder"]


class Study(_Model):
    id: StudyId
    title: NonEmptyStr
    year: int
    # Bibliographic fields, copied by code from the fetched PubMed record (``citations bibliography``, or when the
    # pipeline adds a study). Absent means not yet filled; ``doi: null`` means the record has no DOI. Not evidence.
    authors: list[NonEmptyStr] | None = None
    journal: NonEmptyStr | None = None
    doi: Doi | None = None
    cohort: Literal["me_cfs", "long_covid"]
    case_definition: Literal[
        "CCC", "ICC", "IOM2015", "Fukuda", "Holmes1988", "CDC_unspecified", "Oxford", "other", "none", "unverified"
    ]
    case_definition_source: Literal["abstract", "fulltext"] | None
    case_definition_quote: NonEmptyStr | None
    design: Literal["controlled", "uncontrolled", "intervention_controlled", "other"]
    n_patients: Annotated[int, Field(ge=0)] | None
    n_controls: Annotated[int, Field(ge=0)] | None
    measures_pem: bool
    preregistered: bool | None
    role: Literal["supports", "contradicts", "early_signal", "context"]
    direction: Literal["lower", "higher", "no_difference", "mixed", "not_applicable"]
    finding: NonEmptyStr
    group: NonEmptyStr | None = None
    preprint: bool = False  # a preprint (id "doi:..."): not peer reviewed; early signal only (rule V15)
    corrects: StudyId | None = None  # an erratum or correction: the id of the study on this card it corrects (V17)


class Card(_Model):
    slug: Slug
    name: NonEmptyStr
    core_claim: SourcedText
    level: Annotated[int, Field(strict=True, ge=0, le=5)]
    level_reason: Reason
    contested: Contested | None
    badges: Badges
    subgroups: list[SourcedText]
    working_on_it: list[WorkingOnIt]
    early_signals: list[SourcedText]
    studies: list[Study]
    last_checked: LastChecked
    layer: Literal["predisposition", "trigger", "mechanism", "dysfunction"] | None = None
    links: list[Link] = []

    @property
    def long_covid(self) -> bool:
        """Derived: true if any cited study has a long COVID cohort (not stored on the card)."""
        return any(s.cohort == "long_covid" for s in self.studies)

    @property
    def hatched_rungs(self) -> list[int]:
        """Derived: the rungs drawn as the contested (hatched) segment."""
        return sorted(self.contested.rungs) if self.contested else []


class ChangeLogEntry(_Model):
    date: dt.date
    card: Slug
    change: NonEmptyStr
    reason: NonEmptyStr
    sources: list[StudyId]
    tier: StrictInt  # whole number only (V1); allowed values 1-3 are checked as rule V11
    # Who decided the change: the AI drafting and review pair (tier 1 only), the AI auditor, the founder (an
    # overrule, logged as a correction) or, later, an expert reviewer.
    decided_by: Literal["ai_pair", "ai_audit", "founder", "expert"]


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Issue:
    """One validation error: which rule, in which file, at which field path."""

    rule: str
    file: str
    path: str
    message: str

    def __str__(self) -> str:
        where = self.path or "(whole file)"
        return f"{self.file}: {where}: [{self.rule}] {self.message}"


class CardValidationError(Exception):
    def __init__(self, issues: Sequence[Issue]):
        self.issues = list(issues)
        super().__init__("\n".join(str(i) for i in self.issues))


def _format_loc(loc: Sequence[str | int]) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out


def _schema_issues(exc: ValidationError, file: str) -> list[Issue]:
    # The form tags of a reason are internal: paths read "level_reason[1].sources", not "level_reason.paragraphs.1...".
    hidden = {_SINGLE_TAG, _PARAGRAPHS_TAG}
    return [
        Issue("V1", file, _format_loc([p for p in err["loc"] if p not in hidden]), err["msg"]) for err in exc.errors()
    ]


# ---------------------------------------------------------------------------
# Cross-field rules V2-V10 on a parsed card
# ---------------------------------------------------------------------------


def _paragraphs_at(path: str, reason: SourcedText | list[SourcedText]) -> Iterator[tuple[str, SourcedText]]:
    """A single sourced text keeps its path; paragraphs get an index, so errors point at the right one."""
    if isinstance(reason, list):
        for i, p in enumerate(reason):
            yield f"{path}[{i}]", p
    else:
        yield path, reason


def _sourced_texts(card: Card) -> Iterator[tuple[str, SourcedText]]:
    yield "core_claim", card.core_claim
    yield from _paragraphs_at("level_reason", card.level_reason)
    if card.contested:
        yield from _paragraphs_at("contested.reason", card.contested.reason)
    for name in ("diagnostic_marker", "explains_pem"):
        reason = getattr(card.badges, name).reason
        if reason is not None:
            yield from _paragraphs_at(f"badges.{name}.reason", reason)
    for i, t in enumerate(card.subgroups):
        yield f"subgroups[{i}]", t
    for i, t in enumerate(card.early_signals):
        yield f"early_signals[{i}]", t
    for i, link in enumerate(card.links):
        yield f"links[{i}]", link


def _v15_cited_texts(card: Card) -> Iterator[tuple[str, SourcedText]]:
    """The texts where a preprint may not be cited: every sourced text except ``early_signals``."""
    yield "core_claim", card.core_claim
    yield from _paragraphs_at("level_reason", card.level_reason)
    if card.contested:
        yield from _paragraphs_at("contested.reason", card.contested.reason)
    for name in ("diagnostic_marker", "explains_pem"):
        reason = getattr(card.badges, name).reason
        if reason is not None:
            yield from _paragraphs_at(f"badges.{name}.reason", reason)
    for i, t in enumerate(card.subgroups):
        yield f"subgroups[{i}]", t
    for i, link in enumerate(card.links):
        yield f"links[{i}]", link


def _v17_reason_texts(card: Card) -> Iterator[tuple[str, SourcedText]]:
    """The texts that carry a level, a contested mark or a badge: an erratum is not a source of these."""
    yield from _paragraphs_at("level_reason", card.level_reason)
    if card.contested:
        yield from _paragraphs_at("contested.reason", card.contested.reason)
    for name in ("diagnostic_marker", "explains_pem"):
        reason = getattr(card.badges, name).reason
        if reason is not None:
            yield from _paragraphs_at(f"badges.{name}.reason", reason)


def case_definition_rank(case_definition: str) -> int:
    """Rank of a case definition for the comparable-quality rule; higher is stricter."""
    return CASE_DEFINITION_RANK[case_definition]


def _supports_level2(study: Study) -> bool:
    return (
        study.role == "supports"
        and study.design in CONTROLLED_DESIGNS
        and study.case_definition in STRICT_CASE_DEFINITIONS
    )


# Who may have last checked a card that is published in cards/ (rule V16). A draft may say "ai_pair".
PUBLISHED_LAST_CHECKED_BY = ("ai_audit", "founder")


def check_card(card: Card, file_stem: str, *, published: bool = False) -> list[tuple[str, str, str]]:
    """Return (rule, field path, message) for every cross-field rule the card breaks.

    ``published`` is true for a card file in ``cards/`` (not a draft): rule V16 applies to it.
    """
    found: list[tuple[str, str, str]] = []
    by_id = {s.id: s for s in card.studies}

    # V12 (reported on the second and later occurrences)
    seen: set[str] = set()
    for i, st in enumerate(card.studies):
        if st.id in seen:
            found.append(("V12", f"studies[{i}].id", f"study id '{st.id}' appears more than once in this card"))
        seen.add(st.id)

    # V2
    if card.slug != file_stem:
        found.append(("V2", "slug", f"slug '{card.slug}' must equal the file name '{file_stem}'"))

    for path, text in _sourced_texts(card):
        # V3
        for i, src in enumerate(text.sources):
            if src not in by_id:
                found.append(("V3", f"{path}.sources[{i}]", f"source '{src}' is not in this card's studies"))
        # V4
        if not text.sources and not (path.split("[")[0] == "level_reason" and card.level == 0):
            found.append(("V4", f"{path}.sources", "needs at least one source"))

    # V5
    if card.level >= 2 and not any(_supports_level2(s) for s in card.studies):
        found.append(
            (
                "V5",
                "level",
                "level 2 or higher needs a supporting controlled study "
                "(case definition CCC, ICC, IOM2015, Fukuda, Holmes1988 or CDC_unspecified)",
            )
        )

    # V6
    if card.level >= 4 and not any(
        s.role == "supports" and s.design == "intervention_controlled" for s in card.studies
    ):
        found.append(("V6", "level", "level 4 or higher needs a supporting intervention_controlled study"))

    # V7
    pem = card.badges.explains_pem
    if pem.value:
        cited = [by_id[x] for x in reason_sources(pem.reason) if x in by_id]
        if not any(_supports_level2(s) and s.measures_pem for s in cited):
            found.append(
                (
                    "V7",
                    "badges.explains_pem",
                    "explains_pem: true needs a cited supporting study that measures PEM and is level-2-eligible "
                    "(controlled design, CCC/ICC/IOM2015/Fukuda/Holmes1988/CDC_unspecified)",
                )
            )

    # V8
    if card.contested:
        cited_ids = reason_sources(card.contested.reason)
        if not any(x in by_id and by_id[x].role == "contradicts" for x in cited_ids):
            found.append(("V8", "contested.reason", "must cite at least one study with role 'contradicts'"))
        for i, rung in enumerate(card.contested.rungs):
            if not 1 <= rung <= card.level:
                found.append(
                    ("V8", f"contested.rungs[{i}]", f"rung {rung} must lie within 1..{card.level} (the level)")
                )

    # V9
    for i, s in enumerate(card.studies):
        if s.case_definition in ("none", "unverified") and s.role in ("supports", "contradicts"):
            found.append(
                (
                    "V9",
                    f"studies[{i}].case_definition",
                    f"a study with case_definition '{s.case_definition}' cannot be '{s.role}'",
                )
            )

    # V13
    for i, s in enumerate(card.studies):
        base_path = f"studies[{i}]"
        if s.case_definition == "unverified":
            if s.case_definition_source is not None:
                found.append(("V13", f"{base_path}.case_definition_source", "must be null while 'unverified'"))
            if s.case_definition_quote is not None:
                found.append(("V13", f"{base_path}.case_definition_quote", "must be null while 'unverified'"))
            continue
        if s.case_definition_source is None:
            found.append(
                (
                    "V13",
                    f"{base_path}.case_definition_source",
                    f"case_definition '{s.case_definition}' needs a source (abstract or fulltext)",
                )
            )
        if s.case_definition in RECOGNISED_CASE_DEFINITIONS and s.case_definition_quote is None:
            found.append(
                (
                    "V13",
                    f"{base_path}.case_definition_quote",
                    f"case_definition '{s.case_definition}' needs the verbatim sentence from the source",
                )
            )

    # V14: a TODO marker belongs in a YAML comment, not in text a reader sees
    reader_facing = [("name", card.name)]
    reader_facing += [(f"{path}.text", text.text) for path, text in _sourced_texts(card)]
    for i, st in enumerate(card.studies):
        for field in ("title", "finding", "group", "case_definition_quote"):
            value = getattr(st, field)
            if value is not None:
                reader_facing.append((f"studies[{i}].{field}", value))
    for path, value in reader_facing:
        if _TODO_RE.search(value):
            found.append(("V14", path, "contains a TODO marker; settle it or move it to a YAML comment"))

    # V15: a preprint is an early signal and nothing else; it cannot carry a level, a contested mark, a badge or a link
    for i, s in enumerate(card.studies):
        if s.preprint and s.role != "early_signal":
            found.append(
                (
                    "V15",
                    f"studies[{i}].role",
                    f"a preprint study can only have role 'early_signal', not '{s.role}'",
                )
            )
    preprint_ids = {s.id for s in card.studies if s.preprint}
    for path, text in _v15_cited_texts(card):
        for i, src in enumerate(text.sources):
            if src in preprint_ids:
                found.append(
                    (
                        "V15",
                        f"{path}.sources[{i}]",
                        f"preprint study '{src}' cannot be cited here, only in early_signals",
                    )
                )

    # V17: an erratum entry (`corrects`) points at another study on the card, is context only and sets no level,
    # contested mark or badge
    corrects_ids = {s.id for s in card.studies if s.corrects is not None}
    for i, s in enumerate(card.studies):
        if s.corrects is None:
            continue
        if s.corrects == s.id:
            found.append(("V17", f"studies[{i}].corrects", "a study cannot correct itself"))
        elif s.corrects not in by_id:
            found.append(("V17", f"studies[{i}].corrects", f"'{s.corrects}' is not a study on this card"))
        if s.role != "context" or s.case_definition != "none":
            found.append(
                (
                    "V17",
                    f"studies[{i}]",
                    "a study with 'corrects' must have role 'context' and case_definition 'none'",
                )
            )
    for path, text in _v17_reason_texts(card):
        for i, src in enumerate(text.sources):
            if src in corrects_ids:
                found.append(
                    (
                        "V17",
                        f"{path}.sources[{i}]",
                        f"erratum study '{src}' cannot be a source of a level, contested or badge reason",
                    )
                )

    # V16: a card in cards/ was last checked by the auditor or the founder, never by the review pair alone
    if published and card.last_checked.by not in PUBLISHED_LAST_CHECKED_BY:
        found.append(
            (
                "V16",
                "last_checked.by",
                f"a card in cards/ must have last_checked.by 'ai_audit' or 'founder', not '{card.last_checked.by}'",
            )
        )

    # M3, M4 (M1 is the schema's `layer` enum; M2 needs the other cards and lives in me_atlas.map)
    seen_to: set[str] = set()
    for i, link in enumerate(card.links):
        if link.to == card.slug:
            found.append(("M3", f"links[{i}].to", f"a card cannot link to itself ('{link.to}')"))
        if link.to in seen_to:
            found.append(("M4", f"links[{i}].to", f"the target '{link.to}' is linked more than once on this card"))
        seen_to.add(link.to)

    # M5
    for i, link in enumerate(card.links):
        if link.support == "proposed":
            continue
        cited = [by_id[x] for x in link.sources if x in by_id]
        if cited and not any(
            s.design != "other" and s.case_definition not in WEAK_LINK_CASE_DEFINITIONS for s in cited
        ):
            found.append(
                (
                    "M5",
                    f"links[{i}].support",
                    f"support '{link.support}' needs a study in an ME/CFS cohort with a recognised case definition "
                    "(not a review, not Oxford-only); these sources only support 'proposed'",
                )
            )

    # V10
    scanned = [("core_claim.text", card.core_claim.text)]
    scanned += [(f"early_signals[{i}].text", t.text) for i, t in enumerate(card.early_signals)]
    for path, text in scanned:
        for m in _BANNED_RE.finditer(text):
            found.append(("V10", path, f"banned word '{m.group(0)}'"))

    return found


# ---------------------------------------------------------------------------
# Loading and validation of single files
# ---------------------------------------------------------------------------


def _read_yaml(path: Path) -> tuple[object, list[Issue]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Issue("IO", str(path), "", f"cannot read file: {exc}")]
    try:
        return yaml.safe_load(text), []
    except yaml.YAMLError as exc:
        return None, [Issue("YAML", str(path), "", f"invalid YAML: {str(exc).splitlines()[0] if str(exc) else exc}")]


def _parse_card(path: Path, *, published: bool = False) -> tuple[Card | None, list[Issue]]:
    """Parse and fully validate one card/draft file. Card is None if anything failed.

    ``published`` marks a file in ``cards/``, where rule V16 (``last_checked.by``) also applies.
    """
    data, issues = _read_yaml(path)
    if issues:
        return None, issues
    file = str(path)
    if not isinstance(data, dict):
        return None, [Issue("V1", file, "", "top level must be a mapping of card fields")]
    try:
        card = Card.model_validate(data)
    except ValidationError as exc:
        return None, _schema_issues(exc, file)
    issues = [Issue(rule, file, p, msg) for rule, p, msg in check_card(card, path.stem, published=published)]
    return (None if issues else card), issues


def validate_card_file(path: Path) -> list[Issue]:
    return _parse_card(Path(path))[1]


def load_card(path: Path) -> Card:
    """Load one card or draft; raises CardValidationError listing every problem."""
    card, issues = _parse_card(Path(path))
    if card is None:
        raise CardValidationError(issues)
    return card


def _parse_changelog(path: Path, today: dt.date) -> tuple[list[ChangeLogEntry] | None, list[Issue]]:
    data, issues = _read_yaml(path)
    if issues:
        return None, issues
    file = str(path)
    if data is None:
        return [], []
    if not isinstance(data, list):
        return None, [Issue("V1", file, "", "top level must be a list of change-log entries")]
    entries: list[ChangeLogEntry] = []
    issues = []
    for i, raw in enumerate(data):
        try:
            entries.append(ChangeLogEntry.model_validate(raw))
        except ValidationError as exc:
            issues += [
                Issue(r.rule, r.file, f"[{i}]" + ("." + r.path if r.path else ""), r.message)
                for r in _schema_issues(exc, file)
            ]
    if issues:
        return None, issues
    for i, e in enumerate(entries):
        if not (path.parent / f"{e.card}.yaml").is_file():
            issues.append(Issue("V11", file, f"[{i}].card", f"no card '{e.card}.yaml' next to the change log"))
        if e.tier not in (1, 2, 3):
            issues.append(Issue("V11", file, f"[{i}].tier", f"tier must be 1, 2 or 3, got {e.tier}"))
        if e.date > today:
            issues.append(Issue("V11", file, f"[{i}].date", f"date {e.date} is in the future"))
    return (None if issues else entries), issues


def validate_changelog_file(path: Path, today: dt.date | None = None) -> list[Issue]:
    return _parse_changelog(Path(path), today or dt.date.today())[1]


def load_changelog(path: Path, today: dt.date | None = None) -> list[ChangeLogEntry]:
    entries, issues = _parse_changelog(Path(path), today or dt.date.today())
    if entries is None:
        raise CardValidationError(issues)
    return entries


def load_cards(directory: Path) -> list[Card]:
    """Load every valid card in a directory (cards/ or drafts/), skipping the change log."""
    return [load_card(p) for p in _yaml_files(Path(directory))]


def _yaml_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob("*.yaml") if p.name != CHANGELOG_NAME)


# ---------------------------------------------------------------------------
# Validating paths and the command line
# ---------------------------------------------------------------------------


def in_directory(path: Path, directory: Path) -> bool:
    """Whether the file sits directly in ``directory`` (compared as resolved paths)."""
    try:
        return path.resolve().parent == directory.resolve()
    except OSError:
        return False


def validate_paths(
    paths: Sequence[Path],
    today: dt.date | None = None,
    *,
    content_dir: Path | None = None,
    cards_dir: Path | None = None,
    extra_known_slugs: Collection[str] = (),
) -> tuple[int, list[Issue]]:
    """Validate files and directories. Returns (number of files checked, all issues).

    Besides the per-file rules this runs the causal-map rules that need more than one file: M2 (every link target
    exists; the resolution set is the card files given plus, when a directory is given, ``cards_dir``, plus
    ``extra_known_slugs``) and M6 (the content files in ``content_dir``). Defaults: ``cards/`` and ``content/``
    relative to the current directory.
    """
    from me_atlas import map as maplib  # imported here: me_atlas.map imports this module

    today = today or dt.date.today()
    content_dir = Path(content_dir) if content_dir is not None else Path("content")
    cards_dir = Path(cards_dir) if cards_dir is not None else Path("cards")
    files: list[Path] = []
    issues: list[Issue] = []
    any_directory = False
    for p in map(Path, paths):
        if p.is_dir():
            any_directory = True
            files += sorted(p.glob("*.yaml"))
        elif p.is_file():
            files.append(p)
        else:
            issues.append(Issue("IO", str(p), "", "path does not exist"))
    parsed: list[tuple[str, Card]] = []
    for f in files:
        if f.name == CHANGELOG_NAME:
            issues += validate_changelog_file(f, today)
        else:
            card, file_issues = _parse_card(f, published=in_directory(f, cards_dir))
            issues += file_issues
            if card is not None:
                parsed.append((str(f), card))
    content, content_issues = maplib.load_content(content_dir)
    issues += content_issues
    known = {f.stem for f in files if f.name != CHANGELOG_NAME} | set(extra_known_slugs)
    if any_directory and cards_dir.is_dir():
        known |= {f.stem for f in _yaml_files(cards_dir)}
    issues += maplib.check_targets(parsed, known, content)
    content_files = [
        f for f in (content_dir / maplib.SYMPTOMS_FILE, content_dir / maplib.QUESTIONS_FILE) if f.is_file()
    ]
    return len(files) + len(content_files), issues


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m me_atlas.cards", description="Evidence card tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    val = sub.add_parser("validate", help="validate card, draft and change-log files")
    val.add_argument("paths", nargs="*", type=Path, help="files or directories (default: cards/ and drafts/)")
    val.add_argument("--content", type=Path, default=Path("content"), help="default: %(default)s")
    val.add_argument("--cards", type=Path, default=Path("cards"), help="default: %(default)s")
    args = parser.parse_args(argv)

    paths = args.paths or [p for p in (Path("cards"), Path("drafts")) if p.is_dir()]
    count, issues = validate_paths(paths, content_dir=args.content, cards_dir=args.cards)
    for issue in issues:
        print(issue, file=sys.stderr)
    if issues:
        print(f"FAILED: {len(issues)} error(s) in {count} file(s) checked", file=sys.stderr)
        return 1
    print(f"OK: {count} file(s) checked, no errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
