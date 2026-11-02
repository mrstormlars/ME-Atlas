"""Shared glossary: model, loader and validation.

``content/glossary.yaml`` is a list of ``{term, aliases, explanation}``. It is the only source of explanations:
the glossary page and every in-page explanation are rendered from it (functional spec section 5).

Rules: terms and aliases are unique across the whole file (exact spelling), the explanation is not empty and at
most ``MAX_EXPLANATION`` characters, and none of the card banned words appears anywhere in an entry.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from me_atlas.cards import _BANNED_NB_RE, _BANNED_RE

MAX_EXPLANATION = 200

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class GlossaryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: NonEmptyStr
    aliases: list[NonEmptyStr] = []
    explanation: NonEmptyStr

    @property
    def surfaces(self) -> list[str]:
        """Every spelling that identifies this entry: the term first, then the aliases."""
        return [self.term, *self.aliases]

    @property
    def key(self) -> str:
        """The English term that identifies the entry in every language (anchors and templates use it)."""
        return self.term


class LocalEntry(GlossaryEntry):
    """An entry of a translated glossary (``content/glossary.<lang>.yaml``). ``en`` names the English term it
    translates; ``term``, ``aliases`` and ``explanation`` are in the other language."""

    en: NonEmptyStr

    @property
    def key(self) -> str:
        return self.en


class GlossaryError(Exception):
    def __init__(self, problems: Sequence[str]):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


def _slugify(term: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-") or "term"


@dataclass(frozen=True)
class Glossary:
    """The entries of one language. For a translated glossary ``english`` also maps every English spelling to the
    entry that stands for it, so English text left on a Norwegian page is still marked."""

    entries: tuple[GlossaryEntry, ...]
    english: tuple[tuple[str, GlossaryEntry], ...] = ()

    def by_surface(self) -> dict[str, GlossaryEntry]:
        """Spelling -> entry, for marking text. The language's own spellings win over English ones."""
        return {**dict(self.english), **{s: e for e in self.entries for s in e.surfaces}}

    def lookup(self) -> dict[str, GlossaryEntry]:
        """English spelling -> entry: how a template names a term, in every language."""
        return dict(self.english) if self.english else self.by_surface()

    def slugs(self) -> dict[str, str]:
        """Key (the English term) -> anchor slug, unique within the glossary."""
        out: dict[str, str] = {}
        used: set[str] = set()
        for e in self.entries:
            slug = base = _slugify(e.key)
            n = 2
            while slug in used:
                slug = f"{base}-{n}"
                n += 1
            used.add(slug)
            out[e.key] = slug
        return out


@dataclass(frozen=True)
class LocalisedGlossary:
    """A language's glossary: the translated entries where there are any, the English ones elsewhere."""

    glossary: Glossary
    untranslated: frozenset[str]  # keys of the entries that fall back to English

    @property
    def none_translated(self) -> bool:
        return len(self.untranslated) == len(self.glossary.entries)


def localise(base: Glossary, local: Sequence[LocalEntry]) -> LocalisedGlossary:
    """Merge a translated glossary over the English one. Entries are in the English order; a term with no
    translation keeps its English entry and is listed in ``untranslated``."""
    by_key = {e.en: e for e in local}
    entries: list[GlossaryEntry] = [by_key.get(e.term, e) for e in base.entries]
    english = tuple((s, by_key.get(e.term, e)) for e in base.entries for s in e.surfaces)
    untranslated = frozenset(e.term for e in base.entries if e.term not in by_key)
    return LocalisedGlossary(Glossary(tuple(entries), english), untranslated)


def _banned(text: str, banned_in: Sequence[re.Pattern[str]]) -> list[str]:
    return [m.group(0) for pattern in banned_in for m in pattern.finditer(text)]


def validate_entries(
    raw: object,
    file: str = "glossary",
    *,
    model: type[GlossaryEntry] = GlossaryEntry,
    banned_in: Sequence[re.Pattern[str]] = (_BANNED_RE,),
) -> tuple[list[GlossaryEntry], list[str]]:
    """Return the parsed entries and every problem found (an entry that fails the schema is skipped)."""
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], [f"{file}: top level must be a list of entries"]
    problems: list[str] = []
    entries: list[GlossaryEntry] = []
    for i, item in enumerate(raw):
        try:
            entries.append(model.model_validate(item))
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"])
                problems.append(f"{file}: entry [{i}] {loc}: {err['msg']}")

    seen: dict[str, str] = {}
    for e in entries:
        for kind, surface in [("term", e.term), *[("alias", a) for a in e.aliases]]:
            if surface in seen:
                problems.append(f"{file}: duplicate {kind} '{surface}' (already used by '{seen[surface]}')")
            else:
                seen[surface] = e.term
        if len(e.explanation) > MAX_EXPLANATION:
            problems.append(
                f"{file}: explanation of '{e.term}' is {len(e.explanation)} characters; the limit is {MAX_EXPLANATION}"
            )
        for field, text in [("term", e.term), *[("alias", a) for a in e.aliases], ("explanation", e.explanation)]:
            for word in _banned(text, banned_in):
                problems.append(f"{file}: banned word '{word}' in the {field} of '{e.term}'")
    return entries, problems


def _read_raw(path: Path) -> object:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GlossaryError([f"{path}: cannot read file: {exc}"]) from exc
    except yaml.YAMLError as exc:
        detail = str(exc).splitlines()[0] if str(exc) else "invalid YAML"
        raise GlossaryError([f"{path}: invalid YAML: {detail}"]) from exc


def load_glossary(path: Path) -> Glossary:
    """Load and validate the glossary file; raises GlossaryError listing every problem."""
    path = Path(path)
    entries, problems = validate_entries(_read_raw(path), str(path))
    if problems:
        raise GlossaryError(problems)
    return Glossary(tuple(entries))


def load_local_glossary(path: Path, base: Glossary) -> list[LocalEntry]:
    """Load a translated glossary (Norwegian). Same rules as the English one, with the banned words of both
    languages, plus: ``en`` must be a term of the English glossary and used once. Entries may be missing; a term
    without an entry falls back to English (see ``localise``). Raises GlossaryError listing every problem."""
    path = Path(path)
    parsed, problems = validate_entries(
        _read_raw(path), str(path), model=LocalEntry, banned_in=(_BANNED_RE, _BANNED_NB_RE)
    )
    entries = [e for e in parsed if isinstance(e, LocalEntry)]
    english = {e.term for e in base.entries}
    seen: set[str] = set()
    for e in entries:
        if e.en not in english:
            problems.append(f"{path}: '{e.term}': 'en' is '{e.en}', which is not a term of the English glossary")
        if e.en in seen:
            problems.append(f"{path}: the English term '{e.en}' is translated more than once")
        seen.add(e.en)
    if problems:
        raise GlossaryError(problems)
    return entries
