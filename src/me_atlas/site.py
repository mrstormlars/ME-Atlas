"""Static site generator.

Builds plain HTML from approved cards (and, with ``--drafts``, drafts) into a directory::

    uv run python -m me_atlas.site build [--drafts] [--out build]

Pages: front page, one page per hypothesis, glossary, what changed, causal map, gaps, methods, data. English is written
at the top of the output directory and every other language in ``content/i18n/`` in a folder of its own
(``build/nb/``). ``data/`` (shared) holds the open data and the citation files (``me_atlas.export``).
No external fonts, scripts or styles; every page works from ``file://``. See ``docs/site.md``, ``docs/translation.md``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup, escape

from me_atlas import cards as cardlib
from me_atlas import export, i18n, last_run, map_draw, translations, trials
from me_atlas import map as maplib
from me_atlas.cards import Card, ChangeLogEntry, SourcedText, Study
from me_atlas.glossary import (
    Glossary,
    GlossaryEntry,
    GlossaryError,
    LocalEntry,
    LocalisedGlossary,
    load_glossary,
    load_local_glossary,
    localise,
)

PACKAGE_DIR = Path(__file__).parent
TEMPLATE_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"
DEFAULT_CONTENT_DIR = PACKAGE_DIR.parents[1] / "content"
DEFAULT_CARD_FORMAT = PACKAGE_DIR.parents[1] / "docs" / "card-format.md"
BUILD_MARKER = ".me-atlas-build"
DEFAULT_LANGUAGE = i18n.DEFAULT_LANGUAGE
LANGUAGE_STORAGE_KEY = "me-atlas-lang"
REPO_URL = "https://github.com/mrstormlars/ME-Atlas"
REPO_ISSUES_URL = REPO_URL + "/issues/new/choose"

# Case definitions: glossary term for the label (or None) and flag key (see _macros.html). The labels are in the
# string files (case.<id>); the flags' words are flag.no_pem and flag.broad.
CASE_DEFINITION_META: dict[str, tuple[str | None, str | None]] = {
    "CCC": ("Canadian Consensus Criteria", None),
    "ICC": ("International Consensus Criteria", None),
    "IOM2015": ("IOM 2015 criteria", None),
    "Fukuda": ("Fukuda criteria", "no_pem"),
    "Holmes1988": ("Holmes 1988 criteria", "no_pem"),
    "CDC_unspecified": ("CDC", "no_pem"),
    "Oxford": ("Oxford criteria", "broad"),
    "unverified": (None, None),
    "none": (None, None),
    "other": (None, None),
}


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
    out = [card.core_claim, *cardlib.paragraphs(card.level_reason)]
    if card.contested:
        out += cardlib.paragraphs(card.contested.reason)
    for badge in (card.badges.diagnostic_marker, card.badges.explains_pem):
        if badge.reason is not None:
            out += cardlib.paragraphs(badge.reason)
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
        self.lookup = glossary.lookup()  # how a template names a term: by its English spelling
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

    def __init__(
        self,
        marker: Marker,
        href: str,
        title: str,
        refs: dict[str, int] | None = None,
        *,
        fallback: frozenset[int] = frozenset(),
        untranslated_note: str | None = None,
        source_label: str = "Source {n}",
        sources_label: str = "Sources: ",
    ):
        self.marker = marker
        self.href = href  # path of this page relative to the root of its language
        self.title = title
        self.refs = refs or {}
        self.fallback = fallback  # id() of the English texts and studies shown instead of a translation
        self.untranslated_note = untranslated_note
        self.source_label = source_label
        self.sources_label = sources_label
        self.used: list[GlossaryEntry] = []
        self._seen: set[str] = set()

    # -- glossary ---------------------------------------------------------

    def _button(self, entry: GlossaryEntry, text: str) -> Markup:
        slug = self.marker.slugs[entry.key]
        return Markup(
            '<span class="term-wrap"><button type="button" class="term" id="use-{slug}" '
            'aria-describedby="tip-{slug}">{text}</button></span>'
        ).format(slug=slug, text=text)

    def _claim(self, entry: GlossaryEntry, text: str) -> Markup:
        """Mark this occurrence if it is the first of the term on the page; otherwise plain text."""
        if entry.key in self._seen:
            return escape(text)
        self._seen.add(entry.key)
        self.used.append(entry)
        return self._button(entry, text)

    def term(self, key: str, text: str | None = None) -> Markup:
        """Explicit marking of a template label (used through the ``gloss`` macro)."""
        entry = self.marker.lookup.get(key)
        if entry is None:
            raise SiteError(f"template uses '{key}', which is not in the glossary")
        return self._claim(entry, text or (entry.term if isinstance(entry, LocalEntry) else key))

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

    def _english(self, source: object, html: Markup) -> Markup:
        """English text on a page of another language is marked lang="en", so a screen reader pronounces it right."""
        if id(source) in self.fallback:
            return Markup('<span lang="en">{}</span>').format(html)
        return html

    def _note(self, source: object) -> Markup:
        """The short note after a text that is shown in English because its translation is not usable."""
        if id(source) in self.fallback and self.untranslated_note:
            return Markup(' <span class="untranslated">{}</span>').format(self.untranslated_note)
        return Markup("")

    def sourced(self, item: SourcedText) -> Markup:
        links = Markup(" ").join(
            Markup('<a class="ref" href="#{anchor}" aria-label="{label}">[{n}]</a>').format(
                anchor=study_anchor(source),
                n=self.refs[source],
                label=self.source_label.replace("{n}", str(self.refs[source])),
            )
            for source in sorted(item.sources, key=self.refs.__getitem__)
        )
        refs = (
            Markup('<span class="refs"><span class="sr">{}</span>{}</span>').format(self.sources_label, links)
            if links
            else ""
        )
        return Markup("{} {}{}").format(self._english(item, self.mark(item.text)), refs, self._note(item))

    def plain(self, item: object, text: str) -> Markup:
        """Text of a translatable item without references (the map page puts them after the support label)."""
        return self._english(item, self.mark(text))

    def note(self, item: object) -> Markup:
        return self._note(item)

    def ref_to(self, href: str, n: int) -> Markup:
        """A numbered reference to an anchor on another page."""
        return Markup('<a class="ref" href="{href}" aria-label="{label}">[{n}]</a>').format(
            href=href, n=n, label=self.source_label.replace("{n}", str(n))
        )

    def finding(self, study: Study) -> Markup:
        return self._english(study, self.mark(study.finding)) + self._note(study)


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


@dataclass
class BuildResult:
    written: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # glossary terms no page uses
    translation_warnings: list[str] = field(default_factory=list)  # stale, left-out and missing translations
    errors: list[str] = field(default_factory=list)
    unused_terms: list[str] = field(default_factory=list)


def _environment(content_dir: Path) -> Environment:
    return Environment(
        loader=ChoiceLoader([FileSystemLoader(TEMPLATE_DIR), FileSystemLoader(content_dir)]),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def _unpublished_cards(cards_dir: Path, drafts_dir: Path | None) -> dict[str, str]:
    """Slug -> name of the cards that exist only in ``drafts/``. The public build shows a link to one of them as
    text, not as a link (docs/map.md). The name is the draft's own; a draft that does not load gets its slug."""
    if drafts_dir is not None:
        return {}  # a draft build builds the drafts, so nothing is unpublished
    folder = cards_dir.parent / "drafts"
    if not folder.is_dir():
        return {}
    published = {p.stem for p in cardlib._yaml_files(cards_dir)} if cards_dir.is_dir() else set()
    found: dict[str, str] = {}
    for path in cardlib._yaml_files(folder):
        if path.stem in published:
            continue
        try:
            found[path.stem] = cardlib.load_card(path).name
        except cardlib.CardValidationError:
            found[path.stem] = path.stem.replace("-", " ")
    return found


def _check_inputs(
    cards_dir: Path,
    drafts_dir: Path | None,
    glossary_path: Path,
    today: dt.date,
    content_dir: Path,
    unpublished: Collection[str] = (),
) -> tuple[list[str], Glossary | None]:
    problems: list[str] = []
    paths: list[Path] = [cards_dir]
    if drafts_dir is not None:
        if drafts_dir.is_dir():
            # A change log in drafts/ is not an input: drafts never reach the "what changed" page.
            paths += sorted(p for p in drafts_dir.glob("*.yaml") if p.name != cardlib.CHANGELOG_NAME)
        else:
            problems.append(f"{drafts_dir}: path does not exist")
    _, issues = cardlib.validate_paths(
        paths, today, content_dir=content_dir, cards_dir=cards_dir, extra_known_slugs=unpublished
    )
    problems += [str(i) for i in issues]
    glossary: Glossary | None = None
    try:
        glossary = load_glossary(glossary_path)
    except GlossaryError as exc:
        problems += exc.problems
    return problems, glossary


def _load_strings(i18n_dir: Path, glossary: Glossary) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Every language's string file, English first. A key missing from a language is a problem that names it."""
    problems: list[str] = []
    files = sorted(Path(i18n_dir).glob("*.yaml")) if Path(i18n_dir).is_dir() else []
    if not any(f.stem == DEFAULT_LANGUAGE for f in files):
        return {}, [f"{Path(i18n_dir) / (DEFAULT_LANGUAGE + '.yaml')}: the reference language file is missing"]
    strings: dict[str, dict[str, str]] = {}
    for f in files:
        try:
            strings[f.stem] = i18n.load_strings(f)
        except i18n.I18nError as exc:
            problems += exc.problems
    reference = strings.get(DEFAULT_LANGUAGE)
    if reference is None:
        return {}, problems
    for code, loaded in strings.items():
        if code != DEFAULT_LANGUAGE:
            problems += i18n.compare(reference, loaded, code, file=str(Path(i18n_dir) / f"{code}.yaml"))
        for key, text in loaded.items():
            for pattern in (cardlib._BANNED_RE, cardlib._BANNED_NB_RE):
                problems += [f"{code}.yaml: banned word '{m.group(0)}' in key '{key}'" for m in pattern.finditer(text)]
    lookup = glossary.lookup()
    for key, text in reference.items():
        problems += [
            f"{DEFAULT_LANGUAGE}.yaml: key '{key}' marks '{term}', which is not in the glossary"
            for term in sorted(i18n.glossary_keys(text))
            if term not in lookup
        ]
    ordered = {DEFAULT_LANGUAGE: strings[DEFAULT_LANGUAGE]}
    ordered.update({c: s for c, s in sorted(strings.items()) if c != DEFAULT_LANGUAGE})
    return ordered, problems


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


def language_prefix(code: str) -> str:
    """Folder of a language inside the output directory: none for English."""
    return "" if code == DEFAULT_LANGUAGE else f"{code}/"


def page_url(code: str, href: str, from_code: str, from_href: str) -> str:
    """Relative URL from page ``from_href`` of language ``from_code`` to page ``href`` of language ``code``."""
    depth = from_href.count("/") + (0 if from_code == DEFAULT_LANGUAGE else 1)
    return "../" * depth + language_prefix(code) + href


def persistence_script(code: str, href: str, codes: Sequence[str]) -> str:
    """The inline script of one page. With a language stored in localStorage that is not the page's own, the reader
    goes to the same page in the stored language (``location.replace``, so Back is not trapped). Choosing a language
    through the selector stores it. Every storage access is inside try/catch: no storage, no redirect, no error."""
    targets = {c: page_url(c, href, code, href) for c in codes}
    mapping = json.dumps(targets, separators=(",", ":")).replace("</", "<\\/")
    return (
        f"(function(){{var KEY={json.dumps(LANGUAGE_STORAGE_KEY)},HERE={json.dumps(code)},TO={mapping};"
        "try{var s=localStorage.getItem(KEY);"
        "if(s&&s!==HERE&&Object.prototype.hasOwnProperty.call(TO,s)){location.replace(TO[s]);}}catch(e){}"
        'try{document.addEventListener("click",function(ev){try{'
        'var a=ev.target&&ev.target.closest&&ev.target.closest("a[data-lang]");'
        'if(a){localStorage.setItem(KEY,a.getAttribute("data-lang"));}}catch(e){}});}catch(e){}'
        "})();"
    )


@dataclass
class _Shared:
    """Everything the languages have in common while a build runs."""

    env: Environment
    content_dir: Path
    strings: dict[str, dict[str, str]]
    glossary: Glossary
    local_glossaries: dict[str, list[LocalEntry]]
    sidecars: dict[str, dict[str, translations.TFile]]
    cards: list[Card]  # sorted, drafts applied
    published: dict[str, Card]
    entries: list[ChangeLogEntry]
    drafts: bool
    built: str
    unpublished: dict[str, str] = field(default_factory=dict)  # slug -> name of the draft-only cards
    map_content: maplib.MapContent = field(default_factory=maplib.MapContent)
    map_local: dict[str, tuple[dict[str, str], dict[str, str]]] = field(default_factory=dict)
    registry: dict | None = None  # registry/trials.yaml, validated; None when the project has no registry file
    trials_on: bool = False  # registry/reliability.yaml says passed: true (contract S1)
    last_run: dict | None = None  # content/last-run.yaml, validated; None when missing or invalid (no line is shown)


@dataclass
class _Rendered:
    pages: dict[str, str]  # path relative to the output directory
    uses: dict[str, list[tuple[str, str]]]
    warnings: list[str]


@dataclass(frozen=True)
class MapText:
    """A name or text on the map page; ``english`` is true when a page of another language shows the English."""

    text: str
    english: bool = False


@dataclass(frozen=True)
class LinkView:
    link: object  # the Link as this language shows it (a Link, kept opaque for the page's fallback marking)
    support: str
    target: MapText
    target_href: str
    refs: tuple[tuple[int, str], ...]  # (number, href on the card page)
    unpublished: bool = False  # the target is a draft-only card: shown as text, with no href


@dataclass(frozen=True)
class CardView:
    slug: str
    name: str
    name_in_english: bool
    links: tuple[LinkView, ...]
    drawing: Markup | None = None  # the neighbourhood drawing, when the card has a link in or out


@dataclass(frozen=True)
class SymptomView:
    id: str
    name: MapText
    sources: tuple[str, ...]


@dataclass(frozen=True)
class QuestionView:
    id: str
    text: MapText
    asked_by: tuple[str, ...]
    editorial: bool


@dataclass(frozen=True)
class SectionView:
    key: str  # a layer, or maplib.UNPLACED
    cards: tuple[CardView, ...]
    symptoms: tuple[SymptomView, ...]
    questions: tuple[QuestionView, ...]


@dataclass(frozen=True)
class LegendView:
    samples: dict[str, Markup]  # support step -> inline SVG sample of its line style


@dataclass(frozen=True)
class ConvergenceView:
    name: MapText
    href: str
    count: int


@dataclass(frozen=True)
class _Namer:
    """Names, hrefs and reference numbers of the map's nodes and links in one language; the map page and the gaps
    page both use it, so they show the same names and the same numbers."""

    default: bool
    graph: maplib.Graph
    by_slug: dict[str, translations.LocalCard]
    local_names: dict[str, str]
    local_texts: dict[str, str]
    unpublished: dict[str, str] = field(default_factory=dict)

    def local(self, table: dict[str, str], key: str, english: str) -> MapText:
        if self.default:
            return MapText(english)
        return MapText(table[key], False) if key in table else MapText(english, True)

    def name_of(self, key: str) -> MapText:
        node = self.graph.nodes[key]
        if node.kind == "card":
            lc = self.by_slug[key]
            return MapText(lc.card.name, lc.name_fallback and not self.default)
        return self.local(self.local_names if node.kind == "symptom" else self.local_texts, key, node.name)

    def href_of(self, key: str) -> str:
        node = self.graph.nodes[key]
        if node.kind == "card":
            return f"hypotheses/{key}.html"
        return "#" + key.replace(":", "-")

    def link_refs(self, slug: str) -> dict[int, tuple[tuple[int, str], ...]]:
        """Link index -> (number, href on the card page) for the links of a card, numbered in order of first citation
        across the card's links."""
        numbers: dict[str, int] = {}
        out: dict[int, tuple[tuple[int, str], ...]] = {}
        for i, link in enumerate(self.by_slug[slug].card.links):
            if link.to not in self.graph.nodes and link.to not in self.unpublished:
                continue
            for source in link.sources:
                numbers.setdefault(source, len(numbers) + 1)
            out[i] = tuple(
                (numbers[x], f"hypotheses/{slug}.html#{study_anchor(x)}")
                for x in sorted(link.sources, key=numbers.__getitem__)
            )
        return out


def _map_views(
    code: str,
    local_cards: Sequence[translations.LocalCard],
    english_cards: Sequence[Card],
    content: maplib.MapContent,
    local_names: dict[str, str],
    local_texts: dict[str, str],
    draw_strings: map_draw.Strings,
    unpublished: dict[str, str] | None = None,
) -> tuple[list[SectionView], list[ConvergenceView], list[ConvergenceView], Markup]:
    """The map page as one language shows it. Structure and counts come from the English cards; link texts and names
    come from the translated cards, symptom names and question texts from the language's content files. The last
    value is the drawing of the whole map; each card view carries its own neighbourhood drawing."""
    default = code == DEFAULT_LANGUAGE
    graph = maplib.build_graph(english_cards, content)
    by_slug = {lc.card.slug: lc for lc in local_cards}
    unpublished = unpublished or {}
    namer = _Namer(default, graph, by_slug, local_names, local_texts, unpublished)
    local, name_of, href_of = namer.local, namer.name_of, namer.href_of

    english_by_slug = {c.slug: c for c in english_cards}
    info: dict[str, map_draw.NodeInfo] = {}
    for key in graph.nodes:
        label = name_of(key)
        card = english_by_slug.get(key)
        info[key] = map_draw.NodeInfo(
            label.text,
            href_of(key),
            card.level if card else None,
            bool(card and card.contested),
            label.english,
        )

    sections: list[SectionView] = []
    for layer in (*maplib.LAYER_ORDER, maplib.UNPLACED):
        cards_here: list[CardView] = []
        for node in graph.in_layer(layer, "card"):
            lc = by_slug[node.key]
            refs_of = namer.link_refs(node.key)
            views: list[LinkView] = []
            for i, link in enumerate(lc.card.links):
                if i in refs_of and link.to in unpublished:
                    # A draft-only target: its name as text, no page, no edge (docs/map.md).
                    target = MapText(unpublished[link.to], not default)
                    views.append(LinkView(link, link.support, target, "", refs_of[i], unpublished=True))
                elif i in refs_of:
                    views.append(LinkView(link, link.support, name_of(link.to), href_of(link.to), refs_of[i]))
            near = (
                Markup(map_draw.render_neighbourhood(graph, node.key, info, draw_strings, f"near-{node.key}"))
                if map_draw.has_links(graph, node.key)
                else None
            )
            cards_here.append(CardView(node.key, lc.card.name, lc.name_fallback and not default, tuple(views), near))
        symptoms = tuple(
            SymptomView(s.id, local(local_names, maplib.SYMPTOM_PREFIX + s.id, s.name), tuple(s.sources))
            for s in content.symptoms
            if layer == "symptom"
        )
        questions = tuple(
            QuestionView(
                q.id, local(local_texts, maplib.QUESTION_PREFIX + q.id, q.text), tuple(q.asked_by), q.editorial
            )
            for q in content.questions
            if q.layer == layer
        )
        if layer == maplib.UNPLACED and not cards_here:
            continue
        sections.append(SectionView(layer, tuple(cards_here), symptoms, questions))

    def convergence(found: list[tuple[maplib.Node, int]]) -> list[ConvergenceView]:
        return [ConvergenceView(name_of(n.key), href_of(n.key), count) for n, count in found]

    whole = Markup(map_draw.render_full(graph, info, draw_strings, "map-whole"))
    return sections, convergence(maplib.common_mechanisms(graph)), convergence(maplib.candidate_roots(graph)), whole


@dataclass(frozen=True)
class GapRow:
    """One hypothesis in the gaps page's table: its name and page, and the counts of ``maplib.card_counts``."""

    slug: str
    name: MapText
    href: str
    level: int
    contested_rungs: tuple[int, ...]
    supporting: int
    groups: int
    no_group: int
    contradicting: int
    links: int


@dataclass(frozen=True)
class GapLinkRow:
    """One link at step ``proposed``: no link text; the source's article on the map page shows it."""

    source: MapText
    source_href: str
    source_slug: str
    target: MapText
    target_href: str
    support: str


@dataclass(frozen=True)
class SummarySymptom:
    id: str
    name: MapText
    counts: tuple[int, ...]  # incoming links per support step, in cardlib.SUPPORT_LEVELS order
    no_link: bool


@dataclass(frozen=True)
class SummaryLevel:
    level: int
    count: int
    contested: int
    rest: int  # the largest level's count less this one's: the empty part of the bar


@dataclass(frozen=True)
class SummaryStep:
    step: str
    count: int


@dataclass(frozen=True)
class GapsSummary:
    symptoms: tuple[SummarySymptom, ...]
    steps: tuple[SummaryStep, ...]
    total: int
    levels: tuple[SummaryLevel, ...]  # levels 0 to 5, each present


@dataclass(frozen=True)
class GapsView:
    rows: tuple[GapRow, ...]  # level 0 up to 5, by name within a level
    untested: tuple[GapLinkRow, ...]  # by target, then source
    summary: GapsSummary


def _gaps_view(
    code: str,
    local_cards: Sequence[translations.LocalCard],
    english_cards: Sequence[Card],
    content: maplib.MapContent,
    local_names: dict[str, str],
    local_texts: dict[str, str],
) -> GapsView:
    """The gaps page as one language shows it: the counts of ``me_atlas.map`` with the map page's names. Order and
    numbers come from the English cards, so both languages show the same rows."""
    graph = maplib.build_graph(english_cards, content)
    by_slug = {lc.card.slug: lc for lc in local_cards}
    namer = _Namer(code == DEFAULT_LANGUAGE, graph, by_slug, local_names, local_texts)
    prefix = maplib.SYMPTOM_PREFIX

    rows = tuple(
        GapRow(
            r.slug,
            namer.name_of(r.slug),
            namer.href_of(r.slug),
            r.level,
            r.contested_rungs,
            r.supporting,
            r.groups,
            r.no_group,
            r.contradicting,
            r.links,
        )
        for r in maplib.card_counts(english_cards, graph)
    )
    untested = tuple(
        GapLinkRow(
            namer.name_of(e.source),
            namer.href_of(e.source),
            e.source,
            namer.name_of(e.target),
            namer.href_of(e.target),
            e.support,
        )
        for e in maplib.untested_links(graph)
    )
    per_symptom, totals = maplib.step_counts(graph)
    steps = cardlib.SUPPORT_LEVELS
    summary_symptoms = tuple(
        SummarySymptom(
            key.removeprefix(prefix),
            namer.name_of(key),
            tuple(by_step[s] for s in steps),
            not any(by_step.values()),
        )
        for key, by_step in per_symptom.items()
    )
    all_links = sum(totals.values())
    summary_steps = tuple(SummaryStep(s, totals[s]) for s in steps)
    in_level = {k: [r for r in rows if r.level == k] for k in range(6)}
    biggest = max((len(v) for v in in_level.values()), default=0)
    summary_levels = tuple(
        SummaryLevel(
            k,
            len(in_level[k]),
            sum(bool(r.contested_rungs) for r in in_level[k]),
            biggest - len(in_level[k]),
        )
        for k in range(6)
    )
    summary = GapsSummary(summary_symptoms, summary_steps, all_links, summary_levels)
    return GapsView(rows, untested, summary)


def _translation_warnings(code: str, slug: str, check: translations.CardCheck) -> list[str]:
    out = [f"[{code}] {m}" for m in check.errors]
    out += [f"[{code}] {slug}: {loc} is obsolete (the English item was removed)" for loc in check.obsolete]
    out += [
        f"[{code}] {slug}: {r.locator} is stale ({r.problems[0] if r.problems else translations.STALE_TEXT})"
        for r in check.of("stale")
    ]
    out += [f"[{code}] {slug}: {r.locator} left out: {p}" for r in check.of("invalid") for p in r.problems]
    missing = check.of("missing")
    if check.has_file and missing:
        out.append(f"[{code}] {slug}: {len(missing)} of {len(check.items)} item(s) not translated yet")
    return out


def _render_language(code: str, shared: _Shared) -> _Rendered:
    strings = shared.strings[code]
    default = code == DEFAULT_LANGUAGE
    prefix = language_prefix(code)
    codes = list(shared.strings)
    warnings: list[str] = []

    localised = (
        LocalisedGlossary(shared.glossary, frozenset())
        if default
        else localise(shared.glossary, shared.local_glossaries.get(code, []))
    )
    marker = Marker(localised.glossary)

    # The cards as this language shows them: translated where a fresh translation exists, English elsewhere.
    local_cards: list[translations.LocalCard] = []
    no_file: list[str] = []
    for card in shared.cards:
        if default:
            local_cards.append(translations.LocalCard(card, frozenset(), False, True))
            continue
        check = translations.check_card(card, shared.sidecars.get(code, {}).get(card.slug), code)
        local_cards.append(translations.localise_card(card, check))
        if check.has_file:
            warnings += _translation_warnings(code, card.slug, check)
        else:
            no_file.append(card.slug)
    built_slugs = {c.slug for c in shared.cards}
    for slug in sorted(set(shared.sidecars.get(code, {})) - built_slugs):
        warnings.append(f"[{code}] {slug}: a translation file exists but this build has no English card '{slug}'")
    if no_file:
        warnings.append(f"[{code}] {len(no_file)} card(s) have no translation file yet: {', '.join(no_file)}")
    names = {s: c.name for s, c in shared.published.items()}
    if not default:
        for slug, card in shared.published.items():
            fresh = translations.check_card(card, shared.sidecars.get(code, {}).get(slug), code).fresh_item("name")
            if fresh is not None:
                names[slug] = fresh.text

    fragment = f"methods/{code}.html"
    methods_fallback = False
    if not (shared.content_dir / fragment).is_file():
        if default:
            raise SiteError(f"{shared.content_dir / fragment}: the English methods text is missing")
        fragment, methods_fallback = f"methods/{DEFAULT_LANGUAGE}.html", True

    pages: dict[str, str] = {}
    uses: dict[str, list[tuple[str, str]]] = {}

    def render(
        template: str,
        href: str,
        title: str,
        refs: dict[str, int] | None = None,
        *,
        fallback: frozenset[int] = frozenset(),
        note: str | None = None,
        **ctx: object,
    ) -> None:
        depth = href.count("/")
        page = Page(
            marker,
            href,
            title,
            refs,
            fallback=fallback,
            untranslated_note=note,
            source_label=strings["ref.source"],
            sources_label=strings["ref.sources"],
        )
        auto = {
            "lroot": "../" * depth,
            "root": "../" * (depth + (0 if default else 1)),
            "built": shared.built,
            "repo": REPO_URL,
            "repo_issues": REPO_ISSUES_URL,
        }

        def txt(key: str) -> str:
            try:
                return strings[key]
            except KeyError as exc:
                raise SiteError(f"{code}.yaml: missing key '{key}'") from exc

        def t(key: str, **values: object) -> Markup:
            try:
                return i18n.render(strings, key, page.term, {**auto, "english_url": english_url, **values})
            except i18n.I18nError as exc:
                raise SiteError(f"{code}.yaml: {'; '.join(exc.problems)}") from exc

        english_url = page_url(DEFAULT_LANGUAGE, href, code, href)
        others = [
            {"code": c, "name": shared.strings[c][i18n.LANGUAGE_NAME_KEY], "url": page_url(c, href, code, href)}
            for c in codes
            if c != code
        ]
        alternates = [(c, page_url(c, href, code, href)) for c in codes]
        alternates.append(("x-default", english_url))
        rung_names = tuple(txt(f"rung.{i}.name") for i in range(6))
        rung_meanings = tuple(txt(f"rung.{i}.meaning") for i in range(6))
        html = shared.env.get_template(template).render(
            page=page,
            title=title,
            current=href,
            slugs=marker.slugs,
            lang=code,
            default_lang=DEFAULT_LANGUAGE,
            default_url=english_url,
            drafts=shared.drafts,
            alternates=alternates,
            others=others,
            persistence_js=Markup(persistence_script(code, href, codes)),
            txt=txt,
            t=t,
            trials_on=shared.trials_on,
            last_run=shared.last_run,
            rung_names=rung_names,
            rung_meanings=rung_meanings,
            solid_to=solid_to,
            study_url=study_url,
            study_anchor=study_anchor,
            paragraphs=cardlib.paragraphs,
            case_meta=CASE_DEFINITION_META,
            **auto,
            **ctx,
        )
        pages[prefix + href] = html
        for entry in page.used:
            uses.setdefault(entry.key, []).append((title, href))

    txt0 = strings
    listed = trials.listed_by_card(shared.registry) if shared.trials_on and shared.registry else {}
    render("index.html", "index.html", txt0["page.front"], cards=[lc.card for lc in local_cards])
    for lc in local_cards:
        card = lc.card
        card_note: str | None = None
        part_note: str | None = None
        if not default:
            if not lc.has_file:
                card_note = txt0["untranslated.card"]
            else:
                part_note = txt0["untranslated.part"]
                card_note = part_note if lc.name_fallback else None
        render(
            "card.html",
            f"hypotheses/{card.slug}.html",
            card.name,
            refs=number_sources(card),
            fallback=lc.fallback,
            note=part_note,
            card=card,
            card_note=card_note,
            name_in_english=lc.name_fallback and not default,
            groups=split_studies(card),
            preprint_ids=frozenset(s.id for s in card.studies if s.preprint),
            trials_count=len(listed.get(card.slug, [])) if shared.trials_on else 0,
        )
    render("changes.html", "changes.html", txt0["page.changes"], entries=shared.entries, names=names)
    local_names, local_texts = shared.map_local.get(code, ({}, {}))
    draw_strings = map_draw.Strings(
        bands={k: txt0[f"layer.{k}"] for k in (*maplib.LAYER_ORDER, maplib.UNPLACED)},
        level=txt0["map.draw.level"],
        contested=txt0["map.draw.contested"],
        count_in=txt0["map.draw.in"],
        count_out=txt0["map.draw.out"],
        supports={k: txt0[f"support.{k}"] for k in map_draw.LINK_STYLES},
        title=txt0["map.draw.title"],
        desc=txt0["map.draw.desc"],
        near_title=txt0["map.draw.near_title"],
    )
    sections, common, roots, whole = _map_views(
        code, local_cards, shared.cards, shared.map_content, local_names, local_texts, draw_strings, shared.unpublished
    )
    gaps = _gaps_view(code, local_cards, shared.cards, shared.map_content, local_names, local_texts)
    legend = LegendView({k: Markup(map_draw.legend_sample(k)) for k in map_draw.LINK_STYLES})
    render(
        "map.html",
        "map.html",
        txt0["page.map"],
        fallback=frozenset().union(*(lc.fallback for lc in local_cards)),
        note=txt0["untranslated.part"] if not default else None,
        sections=sections,
        common=common,
        roots=roots,
        whole=whole,
        legend=legend,
    )
    render(
        "gaps.html",
        "gaps.html",
        txt0["page.gaps"],
        fallback=frozenset().union(*(lc.fallback for lc in local_cards)),
        note=txt0["untranslated.part"] if not default else None,
        gaps=gaps,
        legend=legend,
    )
    if shared.trials_on and shared.registry is not None:
        card_names = {lc.card.slug: lc.card.name for lc in local_cards}
        groups = sorted(
            ((slug, card_names[slug], rows) for slug, rows in listed.items() if slug in card_names),
            key=lambda g: (i18n.sort_key(code, g[1]), g[0]),
        )
        render(
            "trials.html",
            "trials.html",
            txt0["page.trials"],
            fetched=shared.registry["fetched"],
            groups=groups,
            distinct=len({r["nct_id"] for _, _, rows in groups for r in rows}),
            not_listed=trials.unlisted_ongoing(shared.registry),
            study_link=trials.STUDY_URL,
            name_fallback=frozenset(),
        )
    render(
        "methods.html",
        "methods.html",
        txt0["page.methods"],
        methods_fragment=fragment,
        methods_note=txt0["untranslated.methods"] if methods_fallback else None,
    )

    render(
        "data.html",
        "data.html",
        txt0["page.data"],
        cards=[lc.card for lc in local_cards],
        data_files=export.DATA_FILES,
        citation=export.citation_text(shared.built),
        licence_url=export.LICENCE_URL,
        doi=export.DATASET_DOI,
        doi_url=export.DATASET_DOI_URL,
    )

    used_terms = [e for e in localised.glossary.entries if e.key in uses]
    used_terms.sort(key=lambda e: i18n.sort_key(code, e.term))
    glossary_note = txt0["untranslated.glossary"] if (not default and localised.none_translated) else None
    render(
        "glossary.html",
        "glossary.html",
        txt0["page.glossary"],
        terms=used_terms,
        uses=uses,
        glossary_note=glossary_note,
        untranslated_terms=frozenset() if glossary_note else localised.untranslated,
    )
    return _Rendered(pages, uses, warnings)


def build(
    cards_dir: Path,
    out_dir: Path,
    glossary_path: Path,
    *,
    drafts_dir: Path | None = None,
    today: dt.date | None = None,
    content_dir: Path | None = None,
    i18n_dir: Path | None = None,
    translations_dir: Path | None = None,
    card_format: Path | None = None,
    registry_dir: Path | None = None,
) -> BuildResult:
    """Build the site in every language that has a file in ``i18n_dir``. If any input fails validation nothing is
    written and ``errors`` says why.

    The Norwegian glossary is looked for next to the English one (``glossary.nb.yaml``), card translations in
    ``translations_dir/<lang>/`` (default: ``translations/`` next to ``cards/``) and the methods text in
    ``content_dir/methods/<lang>.html``. Whatever is missing falls back to English, with a note on the page.
    ``data/card-format.md`` is a copy of ``card_format`` (default: ``docs/card-format.md`` of the package's repository).
    """
    today = today or dt.date.today()
    cards_dir, out_dir, glossary_path = Path(cards_dir), Path(out_dir), Path(glossary_path)
    drafts_dir = Path(drafts_dir) if drafts_dir is not None else None
    content_dir = Path(content_dir) if content_dir is not None else DEFAULT_CONTENT_DIR
    i18n_dir = Path(i18n_dir) if i18n_dir is not None else content_dir / "i18n"
    translations_dir = Path(translations_dir) if translations_dir is not None else cards_dir.parent / "translations"
    card_format = Path(card_format) if card_format is not None else DEFAULT_CARD_FORMAT
    registry_dir = Path(registry_dir) if registry_dir is not None else cards_dir.parent / "registry"
    result = BuildResult()

    unpublished = _unpublished_cards(cards_dir, drafts_dir)
    if not card_format.is_file():
        result.errors = [f"{card_format}: the card format document is missing (it is copied to data/card-format.md)"]
        return result
    problems, glossary = _check_inputs(cards_dir, drafts_dir, glossary_path, today, content_dir, unpublished)
    if glossary is None:
        result.errors = problems
        return result
    strings, string_problems = _load_strings(i18n_dir, glossary)
    problems += string_problems
    local_glossaries: dict[str, list[LocalEntry]] = {}
    sidecars: dict[str, dict[str, translations.TFile]] = {}
    for code in strings:
        if code == DEFAULT_LANGUAGE:
            continue
        local_path = glossary_path.with_name(f"{glossary_path.stem}.{code}{glossary_path.suffix}")
        if local_path.is_file():
            try:
                local_glossaries[code] = load_local_glossary(local_path, glossary)
            except GlossaryError as exc:
                problems += exc.problems
        sidecars[code], schema_problems = translations.load_language(translations_dir, code)
        problems += schema_problems
    map_content, _ = maplib.load_content(content_dir)  # its problems are already in `problems` (rule M6)
    map_local: dict[str, tuple[dict[str, str], dict[str, str]]] = {}
    for code in strings:
        if code != DEFAULT_LANGUAGE:
            names, texts, local_problems = maplib.load_local_texts(content_dir, code, map_content)
            map_local[code] = (names, texts)
            problems += local_problems
    if problems:
        result.errors = problems
        return result
    map_warnings = [f"map: {w}" for w in maplib.content_warnings(map_content)]

    published = {c.slug: c for c in cardlib.load_cards(cards_dir)}
    by_slug = dict(published)
    if drafts_dir is not None:
        by_slug.update({c.slug: c for c in cardlib.load_cards(drafts_dir)})  # a draft replaces its card

    registry: dict | None = None
    trials_on = False
    try:
        if (registry_dir / "trials.yaml").is_file():
            registry = trials.load_data(registry_dir / "trials.yaml")
            registry_problems = trials.check_data(registry, set(by_slug))
            if registry_problems:
                result.errors = [f"registry/trials.yaml: {p}" for p in registry_problems]
                return result
            trials_on = trials.load_reliability(registry_dir / "reliability.yaml")
    except trials.TrialsError as exc:
        result.errors = [str(exc)]
        return result

    last_run_record, last_run_problems = last_run.load(content_dir / last_run.FILE_NAME, today)
    last_run_warnings = [f"last run: {p}; the page shows no last-run line" for p in last_run_problems]

    changelog_path = cards_dir / cardlib.CHANGELOG_NAME
    entries: list[ChangeLogEntry] = cardlib.load_changelog(changelog_path, today) if changelog_path.is_file() else []
    entries = [e for _, e in sorted(enumerate(entries), key=lambda ie: (ie[1].date, ie[0]), reverse=True)]

    shared = _Shared(
        env=_environment(content_dir),
        content_dir=content_dir,
        strings=strings,
        glossary=glossary,
        local_glossaries=local_glossaries,
        sidecars=sidecars,
        cards=sort_cards(list(by_slug.values())),
        published=published,
        entries=entries,
        drafts=drafts_dir is not None,
        built=today.isoformat(),
        unpublished=unpublished,
        map_content=map_content,
        map_local=map_local,
        registry=registry,
        trials_on=trials_on,
        last_run=last_run_record,
    )
    pages: dict[str, str] = {}
    try:
        for code in strings:
            rendered = _render_language(code, shared)
            pages.update(rendered.pages)
            result.translation_warnings += rendered.warnings
            if code == DEFAULT_LANGUAGE:
                result.unused_terms = sorted(
                    (e.term for e in glossary.entries if e.term not in rendered.uses), key=str.casefold
                )
                result.warnings = [f"glossary term '{t}' is not used on any page" for t in result.unused_terms]
    except SiteError as exc:
        result.errors = [str(exc)]
        result.warnings = []
        result.translation_warnings = []
        return result
    result.warnings += map_warnings + last_run_warnings

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
    result.written += _write_data(out_dir / "data", shared, card_format)
    return result


def _write_data(data_dir: Path, shared: _Shared, card_format: Path) -> list[Path]:
    """The open data and the citation files, written next to ``static/``; shared by every language."""
    entries = shared.registry["studies"] if shared.registry else []
    fetched = shared.registry["fetched"] if shared.registry else None
    json_text, _ = export.dataset_json(
        shared.cards,
        shared.map_content,
        built=shared.built,
        draft_preview=shared.drafts,
        trials=entries,
        trials_fetched=fetched,
    )
    texts = {
        "me-atlas.json": json_text,
        "hypotheses.csv": export.hypotheses_csv(shared.cards, shared.map_content),
        "studies.csv": export.studies_csv(shared.cards),
        "links.csv": export.links_csv(shared.cards, shared.map_content),
        "trials.csv": export.trials_csv(entries),
        "README.txt": export.readme(built=shared.built, draft_preview=shared.drafts),
    }
    for card in shared.cards:
        texts[f"{export.CITATIONS_DIR}/{card.slug}.bib"] = export.bibtex(card.studies, study_url)
        texts[f"{export.CITATIONS_DIR}/{card.slug}.ris"] = export.ris(card.studies, study_url)
    written: list[Path] = []
    for name, text in sorted(texts.items()):
        target = data_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))  # bytes: CSV and RIS keep their CRLF line ends
        written.append(target)
    target = data_dir / "card-format.md"
    target.write_bytes(card_format.read_bytes())
    written.append(target)
    return written


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
    b.add_argument("--content-dir", type=Path, default=Path("content"), help=argparse.SUPPRESS)
    b.add_argument("--i18n-dir", type=Path, default=None, help=argparse.SUPPRESS)
    b.add_argument("--translations-dir", type=Path, default=None, help=argparse.SUPPRESS)
    b.add_argument("--card-format", type=Path, default=None, help=argparse.SUPPRESS)
    b.add_argument("--registry-dir", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    result = build(
        args.cards_dir,
        args.out,
        args.glossary,
        drafts_dir=args.drafts_dir if args.drafts else None,
        content_dir=args.content_dir,
        i18n_dir=args.i18n_dir,
        translations_dir=args.translations_dir,
        card_format=args.card_format,
        registry_dir=args.registry_dir,
    )
    for error in result.errors:
        print(error, file=sys.stderr)
    if result.errors:
        print(f"FAILED: {len(result.errors)} problem(s); nothing was built", file=sys.stderr)
        return 1
    for warning in [*result.warnings, *result.translation_warnings]:
        print(f"warning: {warning}", file=sys.stderr)
    for path in result.written:
        print(path.as_posix())
    print(f"OK: {len(result.written)} file(s) written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
