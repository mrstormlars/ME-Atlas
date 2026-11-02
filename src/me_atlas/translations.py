"""Card translations: sidecar files, the mechanical check, and the merge of translator output.

``translations/<lang>/<slug>.yaml`` holds the translatable text of one card (English is authoritative)::

    slug: <slug>
    items:
      name: {text: ..., source_hash: <sha256 of the English name>}
      core_claim: {text: ..., sources: [pmid:..], source_hash: ...}
      level_reason[0]: {...}
      studies[pmid:12345678].finding: {text: ..., source_hash: ...}

Item names (locators) are listed by ``english_items``. Levels, badges, roles, numbers, ids and quotes are never copied
into a sidecar: the page takes them from the English card. An item is

- **fresh**: its ``source_hash`` matches the English text and every check passes; the page shows it;
- **stale**: the English text changed after the translation was made; the page shows English with a note;
- **missing**: no translation yet; English with a note;
- **invalid**: the hash matches but a check fails (sources, numbers, PMIDs, banned words); English with a note, and
  ``check`` exits non-zero.

Command line::

    uv run python -m me_atlas.translations check [--lang nb]
    uv run python -m me_atlas.translations apply <slug> <translated.json> [--card FILE] [--review FILE] [--lang nb]

See ``docs/translation.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from me_atlas import cards as cardlib
from me_atlas.cards import _BANNED_NB_RE, _BANNED_RE, Card, NonEmptyStr, Slug, SourcedText, StudyId
from me_atlas.i18n import DEFAULT_LANGUAGE

DEFAULT_DIR = Path("translations")
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
# Like V10 for English: these two texts may not carry a banned word, in either language.
BANNED_CHECKED = ("core_claim", "early_signals[")


class TranslationError(Exception):
    """A sidecar, agent file or option that cannot be used (printed, exit code 1)."""


# ---------------------------------------------------------------------------
# The English side: what can be translated
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnglishItem:
    locator: str
    text: str
    sources: list[str] | None  # None: this kind of item has no sources (name, finding)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def english_items(card: Card) -> dict[str, EnglishItem]:
    """Every translatable item of a card, in page order, by locator."""
    out: dict[str, EnglishItem] = {}

    def add(locator: str, text: str, sources: list[str] | None) -> None:
        out[locator] = EnglishItem(locator, text, sources)

    def add_sourced(locator: str, item: SourcedText) -> None:
        add(locator, item.text, list(item.sources))

    def add_reason(locator: str, reason: SourcedText | list[SourcedText] | None) -> None:
        if reason is not None:
            for i, p in enumerate(cardlib.paragraphs(reason)):
                add_sourced(f"{locator}[{i}]", p)

    add("name", card.name, None)
    add_sourced("core_claim", card.core_claim)
    add_reason("level_reason", card.level_reason)
    if card.contested:
        add_reason("contested_reason", card.contested.reason)
    add_reason("badge_reasons.diagnostic_marker", card.badges.diagnostic_marker.reason)
    add_reason("badge_reasons.explains_pem", card.badges.explains_pem.reason)
    for i, s in enumerate(card.subgroups):
        add_sourced(f"subgroups[{i}]", s)
    for i, s in enumerate(card.early_signals):
        add_sourced(f"early_signals[{i}]", s)
    for study in card.studies:
        add(f"studies[{study.id}].finding", study.finding, None)
    return out


# ---------------------------------------------------------------------------
# The sidecar file
# ---------------------------------------------------------------------------


class TItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: NonEmptyStr
    source_hash: Sha256
    sources: list[StudyId] | None = None


class TFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: Slug
    items: dict[str, TItem] = Field(default_factory=dict)


def load_sidecar(path: Path) -> TFile:
    """Read and schema-check one sidecar; raises TranslationError."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TranslationError(f"{path}: cannot read file: {exc}") from exc
    except yaml.YAMLError as exc:
        raise TranslationError(f"{path}: invalid YAML: {str(exc).splitlines()[0] if str(exc) else exc}") from exc
    if not isinstance(raw, dict):
        raise TranslationError(f"{path}: top level must be a mapping with 'slug' and 'items'")
    try:
        tf = TFile.model_validate(raw)
    except ValidationError as exc:
        lines = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise TranslationError(f"{path}: " + "; ".join(lines)) from exc
    if tf.slug != path.stem:
        raise TranslationError(f"{path}: slug '{tf.slug}' must equal the file name '{path.stem}'")
    return tf


def dump_sidecar(tf: TFile, order: Sequence[str]) -> str:
    """YAML text, items in the order of the English card, with unknown locators last."""
    ordered = [k for k in order if k in tf.items] + [k for k in tf.items if k not in order]
    items: dict[str, Any] = {}
    for k in ordered:
        item = tf.items[k]
        entry: dict[str, Any] = {"text": item.text}
        if item.sources is not None:
            entry["sources"] = list(item.sources)
        entry["source_hash"] = item.source_hash
        items[k] = entry
    return yaml.safe_dump({"slug": tf.slug, "items": items}, sort_keys=False, allow_unicode=True, width=120)


# ---------------------------------------------------------------------------
# Mechanical checks of a translated text against its English source
# ---------------------------------------------------------------------------

_IDS = re.compile(r"pmid:\d+|doi:\S+", re.IGNORECASE)
_EN_THOUSANDS = re.compile(r"\b\d{1,3}(?:,\d{3})+\b")
_SPACE_THOUSANDS = re.compile(r"\b\d{1,3}(?:[   ]\d{3})+\b")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def pmids(text: str) -> set[str]:
    return set(re.findall(r"pmid:(\d+)", text, re.IGNORECASE))


def numbers(text: str, lang: str) -> list[str]:
    """The numbers in a text, in order of occurrence, written one way. Identifiers (pmid:, doi:) are left out; they have
    their own check.

    English: ``1,200`` is a thousand-separated number and ``.`` is the decimal point. Other languages: ``,`` is the
    decimal point (``0,5`` is 0.5). In both, a space between a digit and a group of exactly three digits is a thousands
    separator (``1 200``)."""
    text = _IDS.sub(" ", text)
    if lang == DEFAULT_LANGUAGE:
        text = _EN_THOUSANDS.sub(lambda m: m.group(0).replace(",", ""), text)
    text = _SPACE_THOUSANDS.sub(lambda m: re.sub(r"[   ]", "", m.group(0)), text)
    if lang != DEFAULT_LANGUAGE:
        text = _DECIMAL_COMMA.sub(".", text)
    return [format(Decimal(n).normalize(), "f") for n in _NUMBER.findall(text)]


def check_item(english: EnglishItem, item: TItem, lang: str) -> list[str]:
    """Problems of a translated item whose hash matches the English text (empty: it passes)."""
    problems: list[str] = []
    if english.sources is None:
        if item.sources is not None:
            problems.append("has a 'sources' list, but this item has none on the English card")
    elif item.sources is None:
        problems.append(f"'sources' is missing; the English item cites {english.sources}")
    elif item.sources != english.sources:
        problems.append(f"sources {item.sources} differ from the English {english.sources}")
    if pmids(item.text) != pmids(english.text):
        problems.append(f"PMIDs differ: English {sorted(pmids(english.text))}, translation {sorted(pmids(item.text))}")
    en_numbers, tr_numbers = numbers(english.text, DEFAULT_LANGUAGE), numbers(item.text, lang)
    if en_numbers != tr_numbers:
        problems.append(
            f"numbers differ (same numbers, same count of each, same order are required): "
            f"English {en_numbers}, translation {tr_numbers}"
        )
    if english.locator.startswith(BANNED_CHECKED):
        for pattern in (_BANNED_RE, _BANNED_NB_RE):
            problems += [f"banned word '{m.group(0)}'" for m in pattern.finditer(item.text)]
    return problems


@dataclass(frozen=True)
class ItemResult:
    locator: str
    status: Literal["fresh", "stale", "missing", "invalid"]
    problems: tuple[str, ...] = ()


@dataclass
class CardCheck:
    slug: str
    has_file: bool
    items: dict[str, ItemResult] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)  # items the English card does not have
    sidecar: TFile | None = None

    def of(self, status: str) -> list[ItemResult]:
        return [r for r in self.items.values() if r.status == status]

    def fresh_item(self, locator: str) -> TItem | None:
        if self.sidecar is not None and locator in self.items and self.items[locator].status == "fresh":
            return self.sidecar.items[locator]
        return None


def check_card(card: Card, sidecar: TFile | None, lang: str) -> CardCheck:
    """Compare a sidecar (or none) with the English card, item by item."""
    english = english_items(card)
    result = CardCheck(card.slug, sidecar is not None, sidecar=sidecar)
    have = sidecar.items if sidecar is not None else {}
    for locator in have:
        if locator not in english:
            result.errors.append(f"{card.slug}: item '{locator}' does not exist on the English card")
    for locator, en in english.items():
        item = have.get(locator)
        if item is None:
            result.items[locator] = ItemResult(locator, "missing")
        elif item.source_hash != text_hash(en.text):
            result.items[locator] = ItemResult(locator, "stale")
        else:
            problems = check_item(en, item, lang)
            result.items[locator] = ItemResult(locator, "invalid" if problems else "fresh", tuple(problems))
    return result


# ---------------------------------------------------------------------------
# The card as a language shows it
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LocalCard:
    """The English card with every fresh translated text put in its place. ``fallback`` holds ``id()`` of the English
    objects (sourced texts, studies) that stayed English because their translation is stale, missing or invalid."""

    card: Card
    fallback: frozenset[int]
    name_fallback: bool
    has_file: bool


def localise_card(card: Card, check: CardCheck) -> LocalCard:
    fallback: set[int] = set()

    def sourced(locator: str, item: SourcedText) -> SourcedText:
        fresh = check.fresh_item(locator)
        if fresh is None:
            fallback.add(id(item))
            return item
        return item.model_copy(update={"text": fresh.text})

    def reason(locator: str, value: Any) -> Any:
        if value is None:
            return None
        new = [sourced(f"{locator}[{i}]", p) for i, p in enumerate(cardlib.paragraphs(value))]
        return new if isinstance(value, list) else new[0]

    name = check.fresh_item("name")
    update: dict[str, Any] = {
        "name": name.text if name else card.name,
        "core_claim": sourced("core_claim", card.core_claim),
        "level_reason": reason("level_reason", card.level_reason),
        "badges": card.badges.model_copy(
            update={
                key: getattr(card.badges, key).model_copy(
                    update={"reason": reason(f"badge_reasons.{key}", getattr(card.badges, key).reason)}
                )
                for key in ("diagnostic_marker", "explains_pem")
            }
        ),
        "subgroups": [sourced(f"subgroups[{i}]", s) for i, s in enumerate(card.subgroups)],
        "early_signals": [sourced(f"early_signals[{i}]", s) for i, s in enumerate(card.early_signals)],
    }
    if card.contested:
        update["contested"] = card.contested.model_copy(
            update={"reason": reason("contested_reason", card.contested.reason)}
        )
    studies = []
    for study in card.studies:
        fresh = check.fresh_item(f"studies[{study.id}].finding")
        if fresh is None:
            fallback.add(id(study))
            studies.append(study)
        else:
            studies.append(study.model_copy(update={"finding": fresh.text}))
    update["studies"] = studies
    return LocalCard(card.model_copy(update=update), frozenset(fallback), name is None, check.has_file)


# ---------------------------------------------------------------------------
# Loading sidecars next to the English cards
# ---------------------------------------------------------------------------


def load_language(translations_dir: Path, lang: str) -> tuple[dict[str, TFile], list[str]]:
    """Every sidecar of a language by slug, and the schema problems of those that could not be read."""
    folder = Path(translations_dir) / lang
    found: dict[str, TFile] = {}
    problems: list[str] = []
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        try:
            found[path.stem] = load_sidecar(path)
        except TranslationError as exc:
            problems.append(str(exc))
    return found, problems


def pending(check: CardCheck) -> list[ItemResult]:
    """The items a translator has to do: stale, missing and invalid ones, in page order."""
    return [r for r in check.items.values() if r.status != "fresh"]


# ---------------------------------------------------------------------------
# Translator output and review files (the shapes the agents write)
# ---------------------------------------------------------------------------


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TranslatedItem(_M):
    item: NonEmptyStr
    text: NonEmptyStr


class TranslatedFile(_M):
    slug: Slug
    lang: NonEmptyStr
    items: list[TranslatedItem]


class TranslationFinding(_M):
    item: NonEmptyStr | None  # a locator, or null for the translation as a whole
    severity: Literal["must_fix", "advisory"]
    problem: NonEmptyStr
    fix: NonEmptyStr | None = None


class TranslationReview(_M):
    slug: Slug
    lang: NonEmptyStr
    verdict: Literal["accept", "reject"]
    findings: list[TranslationFinding]

    @model_validator(mode="after")
    def _verdict_matches_findings(self) -> TranslationReview:
        must = any(f.severity == "must_fix" for f in self.findings)
        if self.verdict == "reject" and not self.findings:
            raise ValueError("a reject verdict needs at least one finding saying what is wrong")
        if self.verdict == "accept" and must:
            raise ValueError("accept with must_fix findings is not allowed; verdict must be reject")
        return self


def _read_model(path: Path, model: type[Any]) -> Any:
    try:
        return model.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise TranslationError(f"{path} does not exist") from exc
    except (OSError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            lines = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
            raise TranslationError(f"{path} is malformed: " + "; ".join(lines)) from exc
        raise TranslationError(f"{path} is not readable JSON: {exc}") from exc


@dataclass
class MergeResult:
    sidecar: TFile
    written: list[str]
    left_out: dict[str, list[str]]  # locator -> why


def merge(
    card: Card,
    existing: TFile | None,
    translated: TranslatedFile,
    review: TranslationReview | None,
    lang: str,
) -> MergeResult:
    """Put translated items into a sidecar. Hash and sources are taken from the English card here, never from the
    translator. An item is left out when the reviewer has a must_fix finding on it (or on the whole translation), when
    its locator is not on the English card, or when the mechanical checks fail."""
    english = english_items(card)
    left_out: dict[str, list[str]] = {}
    if translated.slug != card.slug:
        raise TranslationError(f"the translated file is for '{translated.slug}', not '{card.slug}'")
    if translated.lang != lang:
        raise TranslationError(f"the translated file is for language '{translated.lang}', not '{lang}'")
    if review is not None and (review.slug != card.slug or review.lang != lang):
        raise TranslationError(f"the review is for '{review.slug}' ({review.lang}), not '{card.slug}' ({lang})")
    blocked_all = review is not None and any(f.severity == "must_fix" and f.item is None for f in review.findings)
    blocked = {f.item for f in review.findings if f.severity == "must_fix" and f.item} if review is not None else set()
    items = dict(existing.items) if existing else {}
    written: list[str] = []
    seen: set[str] = set()
    for t in translated.items:
        loc = t.item
        if loc in seen:
            left_out.setdefault(loc, []).append("listed more than once in the translated file")
            continue
        seen.add(loc)
        if loc not in english:
            left_out.setdefault(loc, []).append("not an item of the English card")
            continue
        if blocked_all or loc in blocked:
            left_out.setdefault(loc, []).append("the reviewer has a must_fix finding on it")
            continue
        en = english[loc]
        candidate = TItem(
            text=t.text,
            source_hash=text_hash(en.text),
            sources=list(en.sources) if en.sources is not None else None,
        )
        problems = check_item(en, candidate, lang)
        if problems:
            left_out.setdefault(loc, []).extend(problems)
            continue
        items[loc] = candidate
        written.append(loc)
    return MergeResult(TFile(slug=card.slug, items=items), written, left_out)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def english_cards(cards_dir: Path, drafts_dir: Path | None) -> dict[str, Path]:
    """Slug to file; a draft is the newer text, so it wins (as in the pipeline)."""
    found: dict[str, Path] = {}
    for directory in (cards_dir, drafts_dir):
        if directory is not None and Path(directory).is_dir():
            for path in sorted(Path(directory).glob("*.yaml")):
                if path.name != cardlib.CHANGELOG_NAME:
                    found[path.stem] = path
    return found


def run_check(cards_dir: Path, drafts_dir: Path | None, translations_dir: Path, langs: Sequence[str] | None) -> int:
    languages = list(langs) if langs else sorted(p.name for p in Path(translations_dir).glob("*") if p.is_dir())
    cards_by_slug = english_cards(cards_dir, drafts_dir)
    errors = 0
    files = 0
    for lang in languages:
        sidecars, schema_problems = load_language(translations_dir, lang)
        for problem in schema_problems:
            print(f"error: {problem}", file=sys.stderr)
            errors += 1
        for slug, tf in sidecars.items():
            files += 1
            path = cards_by_slug.get(slug)
            if path is None:
                print(f"error: {lang}/{slug}.yaml: there is no English card '{slug}'", file=sys.stderr)
                errors += 1
                continue
            try:
                card = cardlib.load_card(path)
            except cardlib.CardValidationError as exc:
                print(f"error: {path} does not validate:\n{exc}", file=sys.stderr)
                errors += 1
                continue
            result = check_card(card, tf, lang)
            for message in result.errors:
                print(f"error: {lang}: {message}", file=sys.stderr)
                errors += 1
            for r in result.of("invalid"):
                for p in r.problems:
                    print(f"error: {lang}: {slug}: {r.locator}: {p}", file=sys.stderr)
                    errors += 1
            for r in result.of("stale"):
                print(f"stale: {lang}: {slug}: {r.locator} (the English text changed after it was translated)")
            missing = result.of("missing")
            if missing:
                print(f"missing: {lang}: {slug}: {len(missing)} of {len(result.items)} item(s) not translated yet")
    if errors:
        print(f"FAILED: {errors} problem(s) in {files} translation file(s) checked", file=sys.stderr)
        return 1
    print(f"OK: {files} translation file(s) checked, no errors")
    return 0


def run_apply(args: argparse.Namespace) -> int:
    lang = args.lang
    path = args.card or english_cards(args.cards_dir, args.drafts_dir).get(args.slug)
    if path is None:
        raise TranslationError(f"no card or draft '{args.slug}' in {args.cards_dir}/ or {args.drafts_dir}/")
    try:
        card = cardlib.load_card(path)
    except cardlib.CardValidationError as exc:
        raise TranslationError(f"{path} does not validate:\n{exc}") from exc
    translated = _read_model(args.translated, TranslatedFile)
    review = _read_model(args.review, TranslationReview) if args.review else None
    target = Path(args.translations_dir) / lang / f"{args.slug}.yaml"
    existing = load_sidecar(target) if target.is_file() else None
    merged = merge(card, existing, translated, review, lang)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dump_sidecar(merged.sidecar, list(english_items(card))), encoding="utf-8", newline="\n")
    print(f"wrote {target.as_posix()}: {len(merged.written)} item(s) written")
    for loc, reasons in merged.left_out.items():
        for reason in reasons:
            print(f"left out: {loc}: {reason}")
    after = check_card(card, merged.sidecar, lang)
    todo = [r.locator for r in after.items.values() if r.status != "fresh"]
    print(f"{len(todo)} item(s) still fall back to English")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m me_atlas.translations", description="Card translation tools.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--cards-dir", type=Path, default=Path("cards"), help="default: %(default)s")
        p.add_argument("--drafts-dir", type=Path, default=Path("drafts"), help="default: %(default)s")
        p.add_argument("--translations-dir", type=Path, default=DEFAULT_DIR, help="default: %(default)s")

    check = sub.add_parser("check", help="check every translation file against its English card")
    common(check)
    check.add_argument("--lang", action="append", help="a language to check (default: every folder in translations/)")

    apply = sub.add_parser("apply", help="merge a translator's output into translations/<lang>/<slug>.yaml")
    common(apply)
    apply.add_argument("slug")
    apply.add_argument("translated", type=Path, help="the translator's JSON file")
    apply.add_argument(
        "--review", type=Path, help="the reviewer's JSON file; items with a must_fix finding are left out"
    )
    apply.add_argument("--card", type=Path, help="the English card file to translate (default: drafts/ then cards/)")
    apply.add_argument("--lang", default="nb")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return run_check(args.cards_dir, args.drafts_dir, args.translations_dir, args.lang)
        return run_apply(args)
    except TranslationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
