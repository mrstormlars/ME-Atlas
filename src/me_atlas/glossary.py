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

from me_atlas.cards import _BANNED_RE

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


class GlossaryError(Exception):
    def __init__(self, problems: Sequence[str]):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


def _slugify(term: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-") or "term"


@dataclass(frozen=True)
class Glossary:
    entries: tuple[GlossaryEntry, ...]

    def by_surface(self) -> dict[str, GlossaryEntry]:
        return {s: e for e in self.entries for s in e.surfaces}

    def slugs(self) -> dict[str, str]:
        """Term -> anchor slug, unique within the glossary."""
        out: dict[str, str] = {}
        used: set[str] = set()
        for e in self.entries:
            slug = base = _slugify(e.term)
            n = 2
            while slug in used:
                slug = f"{base}-{n}"
                n += 1
            used.add(slug)
            out[e.term] = slug
        return out


def validate_entries(raw: object, file: str = "glossary") -> tuple[list[GlossaryEntry], list[str]]:
    """Return the parsed entries and every problem found (an entry that fails the schema is skipped)."""
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], [f"{file}: top level must be a list of entries"]
    problems: list[str] = []
    entries: list[GlossaryEntry] = []
    for i, item in enumerate(raw):
        try:
            entries.append(GlossaryEntry.model_validate(item))
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
            for m in _BANNED_RE.finditer(text):
                problems.append(f"{file}: banned word '{m.group(0)}' in the {field} of '{e.term}'")
    return entries, problems


def load_glossary(path: Path) -> Glossary:
    """Load and validate the glossary file; raises GlossaryError listing every problem."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GlossaryError([f"{path}: cannot read file: {exc}"]) from exc
    except yaml.YAMLError as exc:
        detail = str(exc).splitlines()[0] if str(exc) else "invalid YAML"
        raise GlossaryError([f"{path}: invalid YAML: {detail}"]) from exc
    entries, problems = validate_entries(raw, str(path))
    if problems:
        raise GlossaryError(problems)
    return Glossary(tuple(entries))
