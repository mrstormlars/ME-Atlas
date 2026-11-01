"""Evidence card data model, loader and validator.

Cards live in ``cards/<slug>.yaml``, drafts in ``drafts/<slug>.yaml`` (same schema) and the public
change log in ``cards/changelog.yaml``. See ``docs/card-format.md`` for the field reference and the
plain-English rules V1-V13.

Command line::

    uv run python -m me_atlas.cards validate [paths...]

With no paths, ``cards/`` and ``drafts/`` (relative to the current directory) are validated. Every
error in every file is reported; the exit code is non-zero if there is at least one.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from collections.abc import Iterator, Sequence
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

BANNED_WORDS = ("promising", "breakthrough", "cure", "hope", "proven")
# Whole words, with plain plural / past / adjective forms (e.g. "cured", "hopeful").
_BANNED_RE = re.compile(
    r"\b(promising|breakthroughs?|cure[sd]?|hope[sd]?|hopeful|proven)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Models (rule V1: schema)
# ---------------------------------------------------------------------------

StudyId = Annotated[str, StringConstraints(pattern=r"^(pmid:\d+|doi:10\.\S+)$")]
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
Url = Annotated[str, StringConstraints(pattern=r"^https?://\S+$")]


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
    by: Literal["ai_pair", "founder"]


class Study(_Model):
    id: StudyId
    title: NonEmptyStr
    year: int
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


def case_definition_rank(case_definition: str) -> int:
    """Rank of a case definition for the comparable-quality rule; higher is stricter."""
    return CASE_DEFINITION_RANK[case_definition]


def _supports_level2(study: Study) -> bool:
    return (
        study.role == "supports"
        and study.design in CONTROLLED_DESIGNS
        and study.case_definition in STRICT_CASE_DEFINITIONS
    )


def check_card(card: Card, file_stem: str) -> list[tuple[str, str, str]]:
    """Return (rule, field path, message) for every cross-field rule the card breaks."""
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


def _parse_card(path: Path) -> tuple[Card | None, list[Issue]]:
    """Parse and fully validate one card/draft file. Card is None if anything failed."""
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
    issues = [Issue(rule, file, p, msg) for rule, p, msg in check_card(card, path.stem)]
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


def validate_paths(paths: Sequence[Path], today: dt.date | None = None) -> tuple[int, list[Issue]]:
    """Validate files and directories. Returns (number of files checked, all issues)."""
    today = today or dt.date.today()
    files: list[Path] = []
    issues: list[Issue] = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(p.glob("*.yaml"))
        elif p.is_file():
            files.append(p)
        else:
            issues.append(Issue("IO", str(p), "", "path does not exist"))
    for f in files:
        if f.name == CHANGELOG_NAME:
            issues += validate_changelog_file(f, today)
        else:
            issues += validate_card_file(f)
    return len(files), issues


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m me_atlas.cards", description="Evidence card tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    val = sub.add_parser("validate", help="validate card, draft and change-log files")
    val.add_argument("paths", nargs="*", type=Path, help="files or directories (default: cards/ and drafts/)")
    args = parser.parse_args(argv)

    paths = args.paths or [p for p in (Path("cards"), Path("drafts")) if p.is_dir()]
    count, issues = validate_paths(paths)
    for issue in issues:
        print(issue, file=sys.stderr)
    if issues:
        print(f"FAILED: {len(issues)} error(s) in {count} file(s) checked", file=sys.stderr)
        return 1
    print(f"OK: {count} file(s) checked, no errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
