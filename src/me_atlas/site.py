"""Static site generator.

Builds plain HTML from approved cards (and, with ``--drafts``, drafts) into a directory::

    uv run python -m me_atlas.site build [--drafts] [--out build]

Pages: front page, one page per hypothesis, glossary, what changed, methods. No external fonts, scripts or
styles; every page works from ``file://``. See ``docs/site.md``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup, escape

from me_atlas import cards as cardlib
from me_atlas.cards import Card, ChangeLogEntry, SourcedText, Study
from me_atlas.glossary import Glossary, GlossaryEntry, GlossaryError, load_glossary

PACKAGE_DIR = Path(__file__).parent
TEMPLATE_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"
BUILD_MARKER = ".me-atlas-build"

DRAFT_BANNER = "Draft preview — not published"

# Plain-language rung names (functional spec section 3).
RUNG_NAMES = (
    "Proposed",
    "First signs",
    "Backed in a defined group",
    "Repeated by others",
    "Tested by intervention",
    "Causal case built",
)

# What each rung means, copied word for word from the "What it means" column of spec section 3. A test compares them.
RUNG_MEANINGS = (
    "An idea with a reasoned argument, but no direct patient data yet.",
    "One or more small or uncontrolled studies point towards it.",
    "A controlled study in patients with a strict, recognised case definition supports it.",
    "An independent group has reproduced the finding in a separate cohort.",
    "Changing the proposed factor changes the outcome in a controlled experiment, so the link goes beyond association.",
    "Several independent lines of evidence, including experimental evidence, together meet most of the "
    "Bradford Hill criteria, with no unresolved major contradiction.",
)

# Case definitions in plain words: label, glossary term for the label (or None), flag key (see _macros.html).
CASE_DEFINITION_LABELS: dict[str, tuple[str, str | None, str | None]] = {
    "CCC": ("Canadian Consensus Criteria (CCC)", "Canadian Consensus Criteria", None),
    "ICC": ("International Consensus Criteria (ICC)", "International Consensus Criteria", None),
    "IOM2015": ("IOM 2015 criteria", "IOM 2015 criteria", None),
    "Fukuda": ("Fukuda criteria", "Fukuda criteria", "no_pem"),
    "Holmes1988": ("Holmes 1988 criteria", "Holmes 1988 criteria", "no_pem"),
    "Oxford": ("Oxford criteria", "Oxford criteria", "broad"),
    "unverified": ("case definition not yet checked", None, None),
    "none": ("no case definition stated", None, None),
    "other": ("other definition", None, None),
}

DESIGN_LABELS = {
    "controlled": "Controlled",
    "uncontrolled": "Uncontrolled",
    "intervention_controlled": "Intervention, controlled",
    "other": "Other design",
}

DIRECTION_LABELS = {
    "lower": "Lower in patients",
    "higher": "Higher in patients",
    "no_difference": "No difference",
    "mixed": "Mixed",
    "not_applicable": "Not applicable",
}

BY_LABELS = {"ai_pair": "the AI review pair", "founder": "the founder"}


class SiteError(Exception):
    """A problem that stops the build (printed, exit code 1)."""


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


def study_url(study_id: str) -> str:
    """PubMed link for a pmid: id, doi.org link for a doi: id."""
    kind, _, value = study_id.partition(":")
    if kind == "pmid":
        return f"https://pubmed.ncbi.nlm.nih.gov/{value}/"
    return f"https://doi.org/{quote(value, safe='/()-._~:;')}"


def study_anchor(study_id: str) -> str:
    return f"study-{study_id}"


def solid_to(card: Card) -> int:
    """Highest rung of the unbroken run from rung 0 that is not contested."""
    return min(card.hatched_rungs) - 1 if card.contested else card.level


def sort_cards(cards: Sequence[Card]) -> list[Card]:
    """Furthest along first; ties alphabetically by name (spec section 4)."""
    return sorted(cards, key=lambda c: (-c.level, c.name.casefold(), c.slug))


def split_studies(card: Card) -> dict[str, list[Study]]:
    return {
        "supports": [s for s in card.studies if s.role == "supports"],
        "contradicts": [s for s in card.studies if s.role == "contradicts"],
        "other": [s for s in card.studies if s.role in ("context", "early_signal")],
    }


def sourced_texts_in_page_order(card: Card) -> list[SourcedText]:
    """The sourced texts in the order the card page renders them; reference numbers follow this order."""
    out = [card.core_claim, card.level_reason]
    if card.contested:
        out.append(card.contested.reason)
    for badge in (card.badges.diagnostic_marker, card.badges.explains_pem):
        if badge.reason is not None:
            out.append(badge.reason)
    out += card.subgroups
    out += card.early_signals
    return out


def number_sources(card: Card) -> dict[str, int]:
    """Study id -> reference number, numbered in order of first citation on the page."""
    numbers: dict[str, int] = {}
    for text in sourced_texts_in_page_order(card):
        for source in text.sources:
            numbers.setdefault(source, len(numbers) + 1)
    return numbers


# ---------------------------------------------------------------------------
# Glossary marking
# ---------------------------------------------------------------------------


class Marker:
    """Finds glossary terms in text. Whole word, case-sensitive; the longest of overlapping matches wins."""

    def __init__(self, glossary: Glossary):
        self.glossary = glossary
        self.by_surface = glossary.by_surface()
        self.slugs = glossary.slugs()
        self._patterns = [
            (surface, re.compile(r"(?<!\w)" + re.escape(surface) + r"(?!\w)")) for surface in self.by_surface
        ]

    def find(self, text: str) -> list[tuple[int, int, GlossaryEntry]]:
        candidates = [
            (m.start(), m.end(), self.by_surface[surface])
            for surface, pattern in self._patterns
            for m in pattern.finditer(text)
        ]
        candidates.sort(key=lambda c: (-(c[1] - c[0]), c[0]))
        accepted: list[tuple[int, int, GlossaryEntry]] = []
        for start, end, entry in candidates:
            if all(end <= a_start or start >= a_end for a_start, a_end, _ in accepted):
                accepted.append((start, end, entry))
        return sorted(accepted, key=lambda a: a[0])


class Page:
    """State of one page while it renders: glossary terms used, reference numbers."""

    def __init__(self, marker: Marker, href: str, title: str, refs: dict[str, int] | None = None):
        self.marker = marker
        self.href = href  # path of this page relative to the site root
        self.title = title
        self.refs = refs or {}
        self.used: list[GlossaryEntry] = []
        self._seen: set[str] = set()

    # -- glossary ---------------------------------------------------------

    def _button(self, entry: GlossaryEntry, text: str) -> Markup:
        slug = self.marker.slugs[entry.term]
        return Markup(
            '<span class="term-wrap"><button type="button" class="term" id="use-{slug}" '
            'aria-describedby="tip-{slug}">{text}</button></span>'
        ).format(slug=slug, text=text)

    def _claim(self, entry: GlossaryEntry, text: str) -> Markup:
        """Mark this occurrence if it is the first of the term on the page; otherwise plain text."""
        if entry.term in self._seen:
            return escape(text)
        self._seen.add(entry.term)
        self.used.append(entry)
        return self._button(entry, text)

    def term(self, key: str, text: str | None = None) -> Markup:
        """Explicit marking of a template label (used through the ``gloss`` macro)."""
        entry = self.marker.by_surface.get(key)
        if entry is None:
            raise SiteError(f"template uses '{key}', which is not in the glossary")
        return self._claim(entry, text or key)

    def mark(self, text: str) -> Markup:
        """Escape text, marking the first occurrence on the page of each glossary term in it."""
        out: list[Markup | str] = []
        pos = 0
        for start, end, entry in self.marker.find(text):
            out.append(escape(text[pos:start]))
            out.append(self._claim(entry, text[start:end]))
            pos = end
        out.append(escape(text[pos:]))
        return Markup("").join(out)

    # -- sourced text -------------------------------------------------------

    def sourced(self, item: SourcedText) -> Markup:
        links = Markup(" ").join(
            Markup('<a class="ref" href="#{anchor}" aria-label="Source {n}">[{n}]</a>').format(
                anchor=study_anchor(source), n=self.refs[source]
            )
            for source in sorted(item.sources, key=self.refs.__getitem__)
        )
        refs = Markup('<span class="refs"><span class="sr">Sources: </span>{}</span>').format(links) if links else ""
        return Markup("{} {}").format(self.mark(item.text), refs)

    def finding(self, study: Study) -> Markup:
        return self.mark(study.finding)


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


@dataclass
class BuildResult:
    written: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    unused_terms: list[str] = field(default_factory=list)


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def _check_inputs(
    cards_dir: Path, drafts_dir: Path | None, glossary_path: Path, today: dt.date
) -> tuple[list[str], Glossary | None]:
    problems: list[str] = []
    paths: list[Path] = [cards_dir]
    if drafts_dir is not None:
        if drafts_dir.is_dir():
            # A change log in drafts/ is not an input: drafts never reach the "what changed" page.
            paths += sorted(p for p in drafts_dir.glob("*.yaml") if p.name != cardlib.CHANGELOG_NAME)
        else:
            problems.append(f"{drafts_dir}: path does not exist")
    _, issues = cardlib.validate_paths(paths, today)
    problems += [str(i) for i in issues]
    glossary: Glossary | None = None
    try:
        glossary = load_glossary(glossary_path)
    except GlossaryError as exc:
        problems += exc.problems
    return problems, glossary


def _prepare_output(out_dir: Path) -> None:
    """Clear a previous build. Refuses to delete a directory that is not one."""
    if out_dir.exists():
        if not out_dir.is_dir():
            raise SiteError(f"{out_dir} exists and is not a directory")
        if any(out_dir.iterdir()) and not (out_dir / BUILD_MARKER).is_file():
            raise SiteError(f"{out_dir} is not empty and is not a previous ME Atlas build; not deleting it")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    (out_dir / BUILD_MARKER).write_text("Generated by me_atlas.site; safe to delete.\n", encoding="utf-8", newline="\n")


def build(
    cards_dir: Path,
    out_dir: Path,
    glossary_path: Path,
    *,
    drafts_dir: Path | None = None,
    today: dt.date | None = None,
) -> BuildResult:
    """Build the site. If any input fails validation nothing is written and ``errors`` says why."""
    today = today or dt.date.today()
    cards_dir, out_dir, glossary_path = Path(cards_dir), Path(out_dir), Path(glossary_path)
    drafts_dir = Path(drafts_dir) if drafts_dir is not None else None
    result = BuildResult()

    problems, glossary = _check_inputs(cards_dir, drafts_dir, glossary_path, today)
    if problems or glossary is None:
        result.errors = problems
        return result

    published = {c.slug: c for c in cardlib.load_cards(cards_dir)}
    by_slug = dict(published)
    if drafts_dir is not None:
        by_slug.update({c.slug: c for c in cardlib.load_cards(drafts_dir)})  # a draft replaces its card
    all_cards = sort_cards(list(by_slug.values()))

    changelog_path = cards_dir / cardlib.CHANGELOG_NAME
    entries: list[ChangeLogEntry] = cardlib.load_changelog(changelog_path, today) if changelog_path.is_file() else []
    entries = [e for _, e in sorted(enumerate(entries), key=lambda ie: (ie[1].date, ie[0]), reverse=True)]

    env = _environment()
    marker = Marker(glossary)
    show_drafts = drafts_dir is not None
    base_ctx = {
        "drafts": show_drafts,
        "draft_banner": DRAFT_BANNER,
        "built": today.isoformat(),
        "rung_names": RUNG_NAMES,
        "rung_meanings": RUNG_MEANINGS,
        "solid_to": solid_to,
        "study_url": study_url,
        "study_anchor": study_anchor,
        "case_labels": CASE_DEFINITION_LABELS,
        "design_labels": DESIGN_LABELS,
        "direction_labels": DIRECTION_LABELS,
        "by_labels": BY_LABELS,
    }

    pages: dict[str, str] = {}
    uses: dict[str, list[tuple[str, str]]] = {}

    def render(template: str, href: str, title: str, refs: dict[str, int] | None = None, **ctx: object) -> None:
        page = Page(marker, href, title, refs)
        root = "../" * href.count("/")
        html = env.get_template(template).render(
            page=page, root=root, title=title, current=href, slugs=marker.slugs, **base_ctx, **ctx
        )
        pages[href] = html
        for entry in page.used:
            uses.setdefault(entry.term, []).append((title, href))

    try:
        render("index.html", "index.html", "Front page", cards=all_cards)
        for card in all_cards:
            render(
                "card.html",
                f"hypotheses/{card.slug}.html",
                card.name,
                refs=number_sources(card),
                card=card,
                groups=split_studies(card),
            )
        render(
            "changes.html",
            "changes.html",
            "What changed",
            entries=entries,
            names={s: c.name for s, c in published.items()},  # never a draft's name
        )
        render("methods.html", "methods.html", "Methods")
    except SiteError as exc:
        result.errors = [str(exc)]
        return result

    used_terms = [e for e in glossary.entries if e.term in uses]
    used_terms.sort(key=lambda e: e.term.casefold())
    result.unused_terms = sorted((e.term for e in glossary.entries if e.term not in uses), key=str.casefold)
    result.warnings = [f"glossary term '{t}' is not used on any page" for t in result.unused_terms]
    render("glossary.html", "glossary.html", "Glossary", terms=used_terms, uses=uses)

    try:
        _prepare_output(out_dir)
    except SiteError as exc:
        result.errors = [str(exc)]
        return result

    for href, html in sorted(pages.items()):
        target = out_dir / href
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8", newline="\n")
        result.written.append(target)
    for source in sorted(STATIC_DIR.iterdir()):
        target = out_dir / "static" / source.name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(source.read_bytes())
        result.written.append(target)
    return result


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m me_atlas.site", description="ME Atlas static site generator.")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="build the static site")
    b.add_argument("--drafts", action="store_true", help="also build the cards in drafts/ (marked as a draft preview)")
    b.add_argument("--out", type=Path, default=Path("build"), help="output directory (default: build)")
    b.add_argument("--cards-dir", type=Path, default=Path("cards"), help=argparse.SUPPRESS)
    b.add_argument("--drafts-dir", type=Path, default=Path("drafts"), help=argparse.SUPPRESS)
    b.add_argument("--glossary", type=Path, default=Path("content/glossary.yaml"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    result = build(
        args.cards_dir,
        args.out,
        args.glossary,
        drafts_dir=args.drafts_dir if args.drafts else None,
    )
    for error in result.errors:
        print(error, file=sys.stderr)
    if result.errors:
        print(f"FAILED: {len(result.errors)} problem(s); nothing was built", file=sys.stderr)
        return 1
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for path in result.written:
        print(path.as_posix())
    print(f"OK: {len(result.written)} file(s) written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
