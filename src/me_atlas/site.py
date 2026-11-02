"""Static site generator.

Builds plain HTML from approved cards (and, with ``--drafts``, drafts) into a directory::

    uv run python -m me_atlas.site build [--drafts] [--out build]

Pages: front page, one page per hypothesis, glossary, what changed, methods. English is written at the top of the
output directory and every other language in ``content/i18n/`` in a folder of its own (``build/nb/``). No external
fonts, scripts or styles; every page works from ``file://``. See ``docs/site.md`` and ``docs/translation.md``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup, escape

from me_atlas import cards as cardlib
from me_atlas import i18n, translations
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
BUILD_MARKER = ".me-atlas-build"
DEFAULT_LANGUAGE = i18n.DEFAULT_LANGUAGE
LANGUAGE_STORAGE_KEY = "me-atlas-lang"

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


@dataclass
class _Rendered:
    pages: dict[str, str]  # path relative to the output directory
    uses: dict[str, list[tuple[str, str]]]
    warnings: list[str]


def _translation_warnings(code: str, slug: str, check: translations.CardCheck) -> list[str]:
    out = [f"[{code}] {m}" for m in check.errors]
    out += [
        f"[{code}] {slug}: {r.locator} is stale (the English text changed after it was translated)"
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
        auto = {"lroot": "../" * depth, "root": "../" * (depth + (0 if default else 1)), "built": shared.built}

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
        )
    render("changes.html", "changes.html", txt0["page.changes"], entries=shared.entries, names=names)
    render(
        "methods.html",
        "methods.html",
        txt0["page.methods"],
        methods_fragment=fragment,
        methods_note=txt0["untranslated.methods"] if methods_fallback else None,
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
) -> BuildResult:
    """Build the site in every language that has a file in ``i18n_dir``. If any input fails validation nothing is
    written and ``errors`` says why.

    The Norwegian glossary is looked for next to the English one (``glossary.nb.yaml``), card translations in
    ``translations_dir/<lang>/`` (default: ``translations/`` next to ``cards/``) and the methods text in
    ``content_dir/methods/<lang>.html``. Whatever is missing falls back to English, with a note on the page.
    """
    today = today or dt.date.today()
    cards_dir, out_dir, glossary_path = Path(cards_dir), Path(out_dir), Path(glossary_path)
    drafts_dir = Path(drafts_dir) if drafts_dir is not None else None
    content_dir = Path(content_dir) if content_dir is not None else DEFAULT_CONTENT_DIR
    i18n_dir = Path(i18n_dir) if i18n_dir is not None else content_dir / "i18n"
    translations_dir = Path(translations_dir) if translations_dir is not None else cards_dir.parent / "translations"
    result = BuildResult()

    problems, glossary = _check_inputs(cards_dir, drafts_dir, glossary_path, today)
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
    if problems:
        result.errors = problems
        return result

    published = {c.slug: c for c in cardlib.load_cards(cards_dir)}
    by_slug = dict(published)
    if drafts_dir is not None:
        by_slug.update({c.slug: c for c in cardlib.load_cards(drafts_dir)})  # a draft replaces its card

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
    b.add_argument("--content-dir", type=Path, default=Path("content"), help=argparse.SUPPRESS)
    b.add_argument("--i18n-dir", type=Path, default=None, help=argparse.SUPPRESS)
    b.add_argument("--translations-dir", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    result = build(
        args.cards_dir,
        args.out,
        args.glossary,
        drafts_dir=args.drafts_dir if args.drafts else None,
        content_dir=args.content_dir,
        i18n_dir=args.i18n_dir,
        translations_dir=args.translations_dir,
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
