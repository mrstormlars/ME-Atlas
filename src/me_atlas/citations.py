"""Mechanical citation check: cards and drafts against the cached PubMed and Europe PMC records.

Command line::

    uv run python -m me_atlas.citations check [paths...] [--cache-dir data/cache]

With no paths, ``cards/`` and ``drafts/`` are checked. The check is offline: it reads only
``<cache>/pubmed/<pmid>.xml``, ``<cache>/europepmc/<pmid>.json`` and ``<cache>/europepmc/<pmcid>.xml`` (else the
PMC article page ``<pmcid>.html``); the PMC id is the lookup's, else the PubMed record's. A cached XML that is
only a PDF placeholder is not full text. The check
never makes a network request. Missing records are fetched by hand with the command the error names.

Checks per study (errors unless marked); the reference is ``docs/citation-check.md``:

* C1 a cached PubMed record exists for a ``pmid:`` id
* C2 the title matches the record
* C3 the year matches the record
* C4 the record is not marked retracted
* C5 the case-definition quote appears verbatim in the stated source (abstract, cached full text or, for
  ``fulltext_pdf``, the cached text of the open PDF copy)
* C6 (warning) ``n_patients`` and ``n_controls`` appear as numbers in the abstract or cached full text
* C7 a DOI-only study id that is not a preprint cannot be checked yet
* C8 ``preprint`` on the card agrees with the PubMed record (publication type "Preprint")
* C9 (warning) a non-null ``group`` names at least one author of the record (last name and first initial)
* C10 every numeral in a free-text item occurs in a source the item cites, or equals a structured field of one
  (a warning, an error where ``numbers_level`` is ERROR: the checks of newly applied texts)
* C11 a statement about authors that the cached author lists contradict: a stated count of shared authors, "no
  shared authors" / "independent groups" for studies that share authors, a ``group`` naming the first or last
  author wrongly, or "<name> also on <pmid>" where the name is not on that record (a warning, an error at the
  level of C10)
* C12 (warning) a cited ``pmid:`` study whose cached record lists an erratum (PubMed "ErratumIn") that is not a study
  on the same card
* C13 ``authors``, ``journal`` and ``doi`` of a study that has them equal the cached PubMed record; the error names
  the field
* C14 a study with ``case_definition_source: fulltext_pdf`` has the founder's confirmation of its quote in
  ``confirmations/pdf-quotes.yaml`` (same study id, same quote, and the same SHA-256 when the PDF is cached)

A ``doi:`` study with ``preprint: true`` is checked against the cached Europe PMC preprint record with that DOI
(``<cache>/europepmc/preprints/``): C1 (no record), C2, C3, C5 (abstract of the record, or the full text through
the shared ``<pmcid>.xml`` cache) and C6.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from me_atlas.cards import CHANGELOG_NAME, CardValidationError, Study, load_card
from me_atlas.europepmc import (
    EuropePmcCache,
    EuropePmcError,
    PreprintRecord,
    article_references,
    article_text,
    is_placeholder_fulltext,
    pmc_page_references,
    pmc_page_text,
    read_cached_lookup,
    read_cached_preprints,
)
from me_atlas.operations import scalar
from me_atlas.pubmed import DEFAULT_CACHE_ROOT, ParseError, PubMedRecord, RawCache
from me_atlas.translations import english_items
from me_atlas.unpaywall import (
    DEFAULT_CONFIRMATIONS,
    CachedPdf,
    UnpaywallError,
    is_confirmed,
    load_confirmations,
    quote_in_pdf_text,
    read_cached_pdf,
)

ERROR = "ERROR"
WARNING = "WARNING"


@dataclass(frozen=True)
class CitationIssue:
    """One finding: which file and study, which check, error or warning, and what to do."""

    file: str
    study: str
    code: str  # C1..C14, or LOAD when the file could not be read as a card
    level: str  # ERROR or WARNING
    message: str

    def __str__(self) -> str:
        return f"{self.file}: {self.study}: {self.code} {self.level}: {self.message}"


# ---------------------------------------------------------------------------
# Normalisation. Exactly what docs/citation-check.md states, nothing looser.
# ---------------------------------------------------------------------------

_QUOTE_TABLE = {
    **dict.fromkeys(map(ord, "‘’‚‛"), "'"),
    **dict.fromkeys(map(ord, "“”„‟"), '"'),
}
# hyphen U+2010, non-breaking hyphen U+2011, figure dash U+2012, en dash U+2013, em dash U+2014,
# horizontal bar U+2015 and minus sign U+2212, all read as the ASCII hyphen
_DASH_TABLE = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")


def _collapse(text: str) -> str:
    return " ".join(text.split())


def normalise_title(title: str) -> str:
    """NFKC, whitespace collapsed, case folded, one trailing period removed, translation brackets removed.

    PubMed writes the title of a translated article as ``[Title in English].``; the brackets that wrap
    the whole title are removed, but only when the title has no other square bracket inside them
    (``[Foo] and [bar]`` is left as it is). Brackets inside a title are kept.
    """
    text = _collapse(unicodedata.normalize("NFKC", title)).casefold()
    text = text.removesuffix(".")
    if text.startswith("[") and text.endswith("]") and not {"[", "]"} & set(text[1:-1]):
        text = text[1:-1]
    return _collapse(text)


def normalise_quote(text: str) -> str:
    """NFKC, whitespace collapsed, curly quotes read as straight, hyphen/dash/minus family read as '-'.

    Case, punctuation and wording are NOT touched.
    """
    return _collapse(unicodedata.normalize("NFKC", text).translate(_QUOTE_TABLE).translate(_DASH_TABLE))


def number_pattern(n: int) -> re.Pattern[str]:
    """A whole-number matcher. 1234 also matches ``1,234`` and ``1 234``.

    The digits must not be part of a longer number: no digit directly before or after, no ``.`` directly
    before (as in .48, 0.48 or 3.48), no ``digit,`` before (as in 1,148) and no ``.digit`` / ``,digit``
    after (as in 48.5).
    """
    digits = str(n)
    groups: list[str] = []
    while digits:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    body = r"(?:,|\s)?".join(groups)
    return re.compile(rf"(?<!\d)(?<!\.)(?<!\d,){body}(?!\d)(?![.,]\d)")


# ---------------------------------------------------------------------------
# Reading the cache (never the network)
# ---------------------------------------------------------------------------


def pubmed_fetch_hint(pmid: str) -> str:
    return f"uv run python -m me_atlas.pubmed fetch --ids {pmid}"


def fulltext_fetch_hint(pmid: str) -> str:
    return f"uv run python -m me_atlas.europepmc fulltext {pmid}"


def pdf_fetch_hint(pmid: str) -> str:
    return f"uv run python -m me_atlas.unpaywall fetch --card <card> {pmid}"


def preprint_fetch_hint(doi: str) -> str:
    return f"uv run python -m me_atlas.europepmc preprint {doi}"


def pmcpage_fetch_hint(pmid: str) -> str:
    return f"uv run python -m me_atlas.europepmc pmcpage --card <card.yaml> {pmid}"


class CacheReader:
    """Reads and remembers cached records for one run."""

    def __init__(self, root: Path, confirmations: Path | None = None):
        self.root = Path(root)
        self.confirmations_path = Path(confirmations) if confirmations is not None else DEFAULT_CONFIRMATIONS
        self._confirmations: list[dict] | str | None = None
        self.pubmed = RawCache(root)
        self.epmc = EuropePmcCache(root)
        self._records: dict[str, PubMedRecord | str] = {}
        self._fulltexts: dict[str, str | tuple[str]] = {}
        self._preprints: dict[str, list[PreprintRecord]] | None = None
        self._number_tokens: dict[str, set[str] | None] = {}

    def preprint(self, doi: str) -> PreprintRecord | None:
        """The cached Europe PMC preprint record with this DOI (case-insensitive), or None."""
        if self._preprints is None:
            self._preprints = {}
            for r in read_cached_preprints(self.epmc):
                if r.doi:
                    self._preprints.setdefault(r.doi.lower(), []).append(r)
        found = self._preprints.get(doi.removeprefix("doi:").lower(), [])
        if len(found) > 1:
            ids = " and ".join(r.ppr_id for r in found)
            raise EuropePmcError(f"two cached preprint records have the DOI {doi}: {ids}; decide which one is meant")
        return found[0] if found else None

    def preprint_fulltext(self, record: PreprintRecord) -> str | tuple[str]:
        """The plain text of the cached full text of a preprint, or a 1-tuple holding the reason there is none.

        The PMC id is the one in the preprint record; the XML is the shared ``<pmcid>.xml`` cache.
        """
        hint = f"`{preprint_fetch_hint(record.doi or record.ppr_id)} --fulltext`"
        if record.pmcid is None:
            return ("no cached full text (the Europe PMC preprint record has no PMC id)",)
        try:
            path = self.epmc.fulltext_path(record.pmcid)
            if not path.is_file():
                return (f"no cached full text ({record.pmcid} is not in the cache); run {hint}",)
            content = path.read_bytes()
            if is_placeholder_fulltext(content):
                return (f"no cached full text ({record.pmcid} has only a PDF placeholder in Europe PMC, not read)",)
            return article_text(content)
        except (EuropePmcError, OSError) as exc:
            return (f"cached full text is unreadable ({exc}); refresh it with {hint} --refresh",)

    def pdf(self, record: PubMedRecord) -> CachedPdf | tuple[str]:
        """The cached text and meta of the open PDF copy of this record's DOI, or a 1-tuple holding the reason."""
        hint = f"`{pdf_fetch_hint(record.pmid)}`"
        if not record.doi:
            return ("no cached PDF text (the PubMed record has no DOI)",)
        found = read_cached_pdf(self.root, record.doi)
        if found is None:
            return (f"no cached PDF text; run {hint}",)
        return found

    def confirmations(self) -> list[dict] | str:
        """The entries of the founder's confirmations file, or a string saying why it cannot be read."""
        if self._confirmations is None:
            try:
                self._confirmations = load_confirmations(self.confirmations_path)
            except UnpaywallError as exc:
                self._confirmations = str(exc)
        return self._confirmations

    def record(self, pmid: str) -> PubMedRecord | str:
        """The parsed record, or a string saying what is wrong: 'missing' or 'unreadable: <why>'."""
        if pmid not in self._records:
            try:
                self._records[pmid] = self.pubmed.read_record(pmid)
            except FileNotFoundError:
                self._records[pmid] = "missing"
            except (ParseError, OSError) as exc:
                self._records[pmid] = f"unreadable: {exc}"
        return self._records[pmid]

    def fulltext(self, pmid: str) -> str | tuple[str]:
        """The plain text of the cached full text, or a 1-tuple holding the reason there is none."""
        if pmid not in self._fulltexts:
            self._fulltexts[pmid] = self._read_fulltext(pmid)
        return self._fulltexts[pmid]

    def references(self, pmid: str) -> list[str]:
        """The reference entries of the cached full text (the same file ``fulltext`` reads: XML first, then the PMC
        page), or an empty list when there is none or it cannot be read."""
        try:
            lookup = read_cached_lookup(self.epmc, pmid)
            record = self.record(pmid)
            pmcid = lookup.pmcid if lookup else None
            if pmcid is None and isinstance(record, PubMedRecord) and record.pmcid:
                pmcid = record.pmcid
            if pmcid is None:
                return []
            path = self.epmc.fulltext_path(pmcid)
            if path.is_file():
                content = path.read_bytes()
                if not is_placeholder_fulltext(content):
                    return article_references(content)
            page = self.epmc.page_path(pmcid)
            if page.is_file():
                return pmc_page_references(page.read_bytes())
        except (EuropePmcError, OSError, ValueError):
            pass
        return []

    def _read_fulltext(self, pmid: str) -> str | tuple[str]:
        hint = f"`{fulltext_fetch_hint(pmid)}`"
        page_hint = f"`{pmcpage_fetch_hint(pmid)}`"
        reading_page = False
        try:
            lookup = read_cached_lookup(self.epmc, pmid)
            record = self.record(pmid)
            # The PMC id from Europe PMC, else the one in the PubMed record (Europe PMC can lack it for a while).
            pmcid = lookup.pmcid if lookup else None
            from_pubmed = False
            if pmcid is None and isinstance(record, PubMedRecord) and record.pmcid:
                pmcid, from_pubmed = record.pmcid, True
            if lookup is None and pmcid is None:
                return (f"no cached full text (no Europe PMC lookup cached); run {hint}",)
            if pmcid is None:
                return (
                    f"no cached full text (Europe PMC: {lookup.status.replace('_', ' ')}); {hint} cannot download it",
                )
            placeholder = False
            path = self.epmc.fulltext_path(pmcid)
            if path.is_file():
                content = path.read_bytes()
                if not is_placeholder_fulltext(content):
                    return article_text(content)
                placeholder = True  # not full text: a note that the text is a PDF, or no body at all
            page = self.epmc.page_path(pmcid)
            if page.is_file():
                reading_page = True
                return pmc_page_text(page.read_bytes())
            if placeholder:
                return (f"no cached full text ({pmcid} has only a PDF placeholder in Europe PMC, which is not read)",)
            if from_pubmed or (lookup is not None and lookup.open_access):
                return (f"no cached full text ({pmcid} is not in the cache); run {hint}",)
            reason = f"no cached full text (Europe PMC: {lookup.status.replace('_', ' ')}); {hint} cannot download it"
            if lookup.in_pmc:
                reason += (
                    f". It is free to read on PubMed Central: run {page_hint} (with the card or draft that cites it)"
                )
            return (reason,)
        except (EuropePmcError, OSError) as exc:
            retry = page_hint if reading_page else hint
            return (f"cached full text is unreadable ({exc}); refresh it with {retry} --refresh",)


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def check_study(file: str, study: Study, cache: CacheReader) -> list[CitationIssue]:
    """All issues for one study. C7 for DOI-only ids; otherwise C1-C6 against the cached record.

    A ``doi:`` study with ``preprint: true`` is checked against the cached preprint record instead; a ``pmid:``
    study also gets C8 (its ``preprint`` flag against the PubMed record).
    """

    def issue(code: str, level: str, message: str) -> CitationIssue:
        return CitationIssue(file, study.id, code, level, message)

    if study.id.startswith("doi:") and study.preprint:
        return _check_preprint(study, cache, issue)
    if not study.id.startswith("pmid:"):
        return [issue("C7", ERROR, "DOI-only study ids cannot be checked yet; cite the study by PMID (pmid:<digits>)")]
    pmid = study.id.removeprefix("pmid:")

    record = cache.record(pmid)
    if isinstance(record, str):
        if record == "missing":
            return [issue("C1", ERROR, f"no cached PubMed record; fetch it with `{pubmed_fetch_hint(pmid)}`")]
        return [
            issue(
                "C1",
                ERROR,
                f"cached PubMed record is {record}; fetch it again with `{pubmed_fetch_hint(pmid)} --refresh`",
            )
        ]

    issues: list[CitationIssue] = []

    if normalise_title(study.title) != normalise_title(record.title):
        issues.append(
            issue("C2", ERROR, f"title differs from the PubMed record. Card: {study.title!r}. Record: {record.title!r}")
        )

    if record.year is None:
        issues.append(issue("C3", ERROR, "record has no year; check by hand"))
    elif study.year != record.year:
        issues.append(issue("C3", ERROR, f"year {study.year} differs from the PubMed record ({record.year})"))

    if record.retracted:
        issues.append(issue("C4", ERROR, "the PubMed record is marked retracted"))

    if record.preprint and not study.preprint:
        issues.append(
            issue("C8", ERROR, 'the PubMed record has publication type "Preprint", but the study lacks preprint: true')
        )
    elif study.preprint and not record.preprint:
        issues.append(
            issue("C8", ERROR, 'preprint: true, but the PubMed record does not have publication type "Preprint"')
        )

    def full() -> str | tuple[str]:
        return cache.fulltext(record.pmid)

    issues += _check_bibliography(study, record, issue)
    issues += _check_quote(study, record.abstract, full, "PubMed", issue, pdf=lambda: cache.pdf(record))
    issues += _check_pdf_confirmation(study, record, cache, issue)
    issues += _check_sample_sizes(study, record.abstract, full, issue)
    issues += _check_group(study, record.authors, "PubMed", issue)
    return issues


def _check_bibliography(study: Study, record: PubMedRecord, issue) -> list[CitationIssue]:
    """C13: the bibliographic fields a study has equal the cached record. A field the study lacks is not checked."""
    found = {"authors": record.authors, "journal": record.journal, "doi": record.doi or None}
    return [
        issue("C13", ERROR, f"{name} differs from the PubMed record. Card: {getattr(study, name)!r}. Record: {want!r}")
        for name, want in found.items()
        if name in study.model_fields_set and getattr(study, name) != want
    ]


_TAG_RE = re.compile(r"<[^>]+>")


def _check_preprint(study: Study, cache: CacheReader, issue) -> list[CitationIssue]:
    """C1-C3, C5 and C6 for a ``doi:`` preprint study, against the cached Europe PMC preprint record."""
    doi = study.id.removeprefix("doi:")
    try:
        record = cache.preprint(doi)
    except EuropePmcError as exc:
        return [issue("C1", ERROR, str(exc))]
    if record is None:
        return [issue("C1", ERROR, f"no cached Europe PMC preprint record; fetch it with `{preprint_fetch_hint(doi)}`")]
    issues: list[CitationIssue] = []
    if normalise_title(study.title) != normalise_title(record.title):
        issues.append(
            issue(
                "C2",
                ERROR,
                f"title differs from the Europe PMC preprint record. Card: {study.title!r}. Record: {record.title!r}",
            )
        )
    if record.year is None:
        issues.append(issue("C3", ERROR, "record has no year; check by hand"))
    elif study.year != record.year:
        issues.append(
            issue("C3", ERROR, f"year {study.year} differs from the Europe PMC preprint record ({record.year})")
        )
    # Europe PMC abstracts can carry HTML headings (<h4>); they are not part of the text a quote is taken from.
    abstract = _collapse(_TAG_RE.sub(" ", record.abstract)) if record.abstract else None

    def full() -> str | tuple[str]:
        return cache.preprint_fulltext(record)

    issues += _check_quote(study, abstract, full, "Europe PMC preprint", issue)
    issues += _check_sample_sizes(study, abstract, full, issue)
    issues += _check_group(study, record.authors, "Europe PMC preprint", issue)
    return issues


def _strip_marks(text: str) -> str:
    """NFKD with the combining marks removed, whitespace collapsed; case is kept."""
    decomposed = unicodedata.normalize("NFKD", text)
    return _collapse("".join(c for c in decomposed if not unicodedata.combining(c)))


def author_in_group(author: str, group: str) -> bool:
    """Whether the group text names this record author (docs/citation-check.md, C9).

    Both texts go through NFKD with combining marks removed. A record author ``<last> <initials>`` (initials are
    capital letters) is named when the group has the last name (case folded), then whitespace (a comma may precede
    it), then the first initial, then only further capital initials (dots or spaces between them are fine), as whole
    words: ``Ponting C``, ``Ponting CP``, ``Ponting C.P.`` and ``Ponting C P`` name ``Ponting CP``; ``Ponting Cox``
    does not. A collective author, and a name with no initials, is named only by its full name as whole words
    (case folded).
    """
    text = _strip_marks(group)
    name = _strip_marks(author)
    if not name:
        return False
    last, _, initials = name.rpartition(" ")
    if not last or not re.fullmatch(r"[^\W\d_]+", initials) or not initials.isupper():
        # a collective author (or a name with no initials): its full name, whole words, case folded
        return re.search(rf"(?<!\w)(?i:{re.escape(name)})(?!\w)", text) is not None
    first = re.escape(initials[0])
    personal = re.compile(rf"(?<!\w)(?i:{re.escape(last)}),?\s+(?i:{first})(?:[.\s]*[A-Z](?!\w))*\.?(?!\w)")
    return personal.search(text) is not None


def _check_group(study, authors, record_name, issue) -> list[CitationIssue]:
    """C9 (warning): a ``group`` that names no author of the record. A record without authors gives no issue."""
    if study.group is None or not authors:
        return []
    if any(author_in_group(a, study.group) for a in authors):
        return []
    shown = ", ".join(authors[:6]) + (f", ... ({len(authors)} in all)" if len(authors) > 6 else "")
    return [
        issue(
            "C9",
            WARNING,
            f"group {study.group!r} names no author of the {record_name} record (authors: {shown}); "
            "check the names against the record",
        )
    ]


def _check_quote(study, abstract, full, record_name, issue, pdf=None) -> list[CitationIssue]:
    quote = study.case_definition_quote
    if quote is None:
        return []
    wanted = normalise_quote(quote)
    source = study.case_definition_source
    if source == "abstract":
        if abstract is None:
            return [issue("C5", ERROR, f"source is the abstract but the {record_name} record has no abstract")]
        if wanted not in normalise_quote(abstract):
            return [issue("C5", ERROR, f"case_definition_quote is not verbatim in the {record_name} abstract")]
        return []
    if source == "fulltext":
        text = full()
        if isinstance(text, tuple):
            return [issue("C5", ERROR, text[0])]
        if wanted not in normalise_quote(text):
            return [issue("C5", ERROR, "case_definition_quote is not verbatim in the cached full text")]
        return []
    if source == "fulltext_pdf":
        found = pdf() if pdf is not None else ("a fulltext_pdf quote is checked for studies with a PubMed record only",)
        if isinstance(found, tuple):
            return [issue("C5", ERROR, found[0])]
        if not quote_in_pdf_text(quote, found.text):
            return [issue("C5", ERROR, "case_definition_quote is not verbatim in the cached PDF text")]
        return []
    return [
        issue(
            "C5",
            ERROR,
            "case_definition_quote has no case_definition_source (abstract, fulltext or fulltext_pdf) "
            "to check it against",
        )
    ]


def _check_pdf_confirmation(study, record: PubMedRecord, cache: CacheReader, issue) -> list[CitationIssue]:
    """C14: a ``fulltext_pdf`` quote needs the founder's confirmation (same study, same quote, same PDF)."""
    if study.case_definition_source != "fulltext_pdf" or study.case_definition_quote is None:
        return []
    entries = cache.confirmations()
    if isinstance(entries, str):
        return [issue("C14", ERROR, entries)]
    cached = read_cached_pdf(cache.root, record.doi) if record.doi else None
    sha = cached.meta.get("sha256") if cached else None
    if is_confirmed(entries, study.id, study.case_definition_quote, sha):
        return []
    if is_confirmed(entries, study.id, study.case_definition_quote, None):
        why = "the founder confirmed this quote for a different PDF (the SHA-256 differs)"
    else:
        why = "no founder confirmation for this quote"
    return [
        issue(
            "C14",
            ERROR,
            f"{why}; the founder checks the sentence in the PDF and runs "
            f"`uv run python -m me_atlas.unpaywall confirm --card <card> {study.id.removeprefix('pmid:')}`",
        )
    ]


def _check_sample_sizes(study, abstract, full, issue) -> list[CitationIssue]:
    sizes = [("n_patients", study.n_patients), ("n_controls", study.n_controls)]
    sizes = [(name, n) for name, n in sizes if n is not None]
    if not sizes:
        return []
    texts: list[str] = []
    if abstract:
        texts.append(abstract)
    full_note = "the abstract"
    fulltext = full()
    if isinstance(fulltext, str):
        texts.append(fulltext)
        full_note = "the abstract or the cached full text"
    else:
        full_note = "the abstract (no cached full text)"
    issues: list[CitationIssue] = []
    for name, n in sizes:
        pattern = number_pattern(n)
        if not any(pattern.search(t) for t in texts):
            issues.append(
                issue(
                    "C6",
                    WARNING,
                    f"{name} {n} does not appear as a number in {full_note}; check by hand "
                    "(it may be written as a word, be a sum of cohorts or belong to one measurement)",
                )
            )
    return issues


# ---------------------------------------------------------------------------
# C10: numbers in free text (docs/citation-check.md, "Numbers in free text")
# ---------------------------------------------------------------------------

_UNIT_WORDS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_TEEN_WORDS = [
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS_WORDS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_WORD_NUMBERS = {w: str(i) for i, w in enumerate(_UNIT_WORDS, start=1)}
_WORD_NUMBERS |= {w: str(i) for i, w in enumerate(_TEEN_WORDS, start=10)}
_WORD_NUMBERS |= {w: str(i * 10) for i, w in enumerate(_TENS_WORDS, start=2)}
# One to ninety-nine; a tens word may take a unit after a hyphen or a space (``twenty-eight``, ``forty two``).
# "hundred" forms are not read.
_WORD_NUMBER_RE = re.compile(
    r"\b(?:("
    + "|".join(_TENS_WORDS)
    + r")(?:[-\s]+("
    + "|".join(_UNIT_WORDS)
    + r"))?|("
    + "|".join(_TEEN_WORDS + _UNIT_WORDS)
    + r"))\b",
    re.IGNORECASE,
)


def _word_number(m: re.Match[str]) -> str:
    tens, unit, plain = m.groups()
    if plain:
        return _WORD_NUMBERS[plain.casefold()]
    value = int(_WORD_NUMBERS[tens.casefold()])
    return str(value + int(_WORD_NUMBERS[unit.casefold()])) if unit else str(value)


# Digits attached to letters (IL-6, COVID-19, CD4, COMPASS-31, SF-36, IOM2015, G93.3) or to a following capital
# (5-HT), or to a chemical prefix (3-hydroxykynurenine) are names, not quantities.
_ATTACHED_RE = re.compile(
    r"(?<![\d.])[^\W\d_]+-?\d+(?:\.\d+)?|(?<!\w)\d+-(?=[A-Z]{1,3}\b)"
    r"|(?<![\w.])\d+(?:,\d+)*-(?:hydroxy|methoxy|methyl|amino|nitro|oxo|keto|phospho)\w*"
)
_SOURCE_ID_RE = re.compile(r"\b(?:pmid|doi|pmcid|ppr)\s*:\s*\S+|\b10\.\d{4,9}/\S+|\b(?:PMC|PPR)\d+", re.IGNORECASE)
# A year inside a citation string: "Smith et al. (2019)", "Smith (2019)", "Fukuda 1994".
_CITATION_YEAR_RE = re.compile(
    r"\b[A-Z][\w'-]+(?:\s+et al\.?,?)?\s*\((?:19|20)\d{2}[a-z]?\)"
    r"|\bet al\.?,?\s*\(?(?:19|20)\d{2}[a-z]?\)?"
    r"|\b(?:Fukuda|Holmes|IOM|CCC|ICC|Oxford|CDC|NICE)\s+\(?(?:19|20)\d{2}\)?"
    r"|\b(?:19|20)\d{2}\s+(?:CDC|IOM|Institute of Medicine|Fukuda|Holmes|Canadian|International Consensus|ICC|CCC)\b"
)
# A rung or level of the rubric ("level 3", "rungs 2 and 3"): it refers to the rubric, not to a source.
# Rungs run 0 to 5, so only a number in that range is skipped, also when joined in a list; a joined number
# followed by a counted noun ("level 3, 4 patients") is a count and stays checked.
_RUBRIC_NOUNS = r"(?:patients?|controls?|participants?|people|persons?|women|men|cases?|subjects?|cohorts?|studies|%)"
_RUBRIC_RE = re.compile(
    r"\b(?:levels?|rungs?|steps?)\s+[0-5](?!\d)"
    rf"(?:\s*(?:,|and|or|to|-)\s*[0-5](?![\d%])(?!\s*{_RUBRIC_NOUNS}(?!\w)))*",
    re.IGNORECASE,
)
_ORDINAL_RE = re.compile(r"\b\d+(?:st|nd|rd|th)\b")
_NUMERAL_RE = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|(?<![\w.])\.\d+")
_SPACED_THOUSANDS_RE = re.compile(r"(?<![\d.])\d{1,3}(?:[ \u00a0\u2009\u202f]\d{3})+(?![\d.,]\d)")
# "78 (= 40 + 38)": a number with its derivation right after it; only sums and differences of plain numbers.
_DERIVATION_RE = re.compile(r"(?P<res>\d[\d,]*(?:\.\d+)?)\s*(?:%|percent)?\s*\(=\s*(?P<expr>[^()]*)\)", re.IGNORECASE)
_EXPR_RE = re.compile(r"\d[\d,]*(?:\.\d+)?(?:\s*[+-]\s*\d[\d,]*(?:\.\d+)?)+")


def canonical_number(token: str) -> str:
    """A numeral as compared: no thousands commas, a leading zero for ``.05``, no leading zeros. Sign, ``%`` and
    unit are not part of it; trailing zeros are kept (``0.50`` is not ``0.5``)."""
    whole, dot, frac = token.replace(",", "").partition(".")
    return (whole.lstrip("0") or "0") + dot + frac


def _normalise_numbers_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(_DASH_TABLE)


def _mask(text: str, patterns: Sequence[re.Pattern[str]]) -> str:
    for pattern in patterns:
        text = pattern.sub(" ", text)
    return text


def free_text_numerals(text: str) -> tuple[list[str], list[str]]:
    """(the numerals of ``text`` to check, derivation problems). Numerals are canonical, in order, once each."""
    text = _normalise_numbers_text(text)
    problems: list[str] = []

    def derivation(match: re.Match[str]) -> str:
        expr = match.group("expr")
        if not _EXPR_RE.fullmatch(expr.strip()):
            problems.append(f"the derivation (= {expr.strip()}) is not a sum or difference of plain numbers")
            return " "
        parts = re.findall(r"[+-]?\s*\d[\d,]*(?:\.\d+)?", expr)
        total = Decimal(0)
        for part in parts:
            value = Decimal(part.replace(",", "").replace(" ", "").lstrip("+"))
            total += value
        result = Decimal(match.group("res").replace(",", ""))
        if total != result:
            problems.append(
                f"{match.group('res')} (= {expr.strip()}) is wrong: the operands give {total.normalize():f}"
            )
        return f" {expr} "  # the operands are numerals like any other; the result is vouched for by the sum

    text = _DERIVATION_RE.sub(derivation, text)
    text = _mask(text, [_SOURCE_ID_RE, _CITATION_YEAR_RE, _RUBRIC_RE, _ORDINAL_RE, _ATTACHED_RE])
    seen: dict[str, None] = {}
    for token in _NUMERAL_RE.findall(text):
        seen[canonical_number(token)] = None
    return list(seen), problems


def source_number_tokens(text: str) -> set[str]:
    """Every number a source text states, canonical, plus ``one``..``ninety-nine`` written as words."""
    text = _normalise_numbers_text(text)
    found = {m.group(0) for m in _SPACED_THOUSANDS_RE.finditer(text)}
    tokens = {canonical_number(re.sub(r"[ \u00a0\u2009\u202f]", "", t)) for t in found}
    masked = _mask(text, [_ATTACHED_RE])
    tokens |= {canonical_number(t) for t in _NUMERAL_RE.findall(masked)}
    tokens |= {_word_number(m) for m in _WORD_NUMBER_RE.finditer(masked)}
    return tokens


def _record_text(cache: CacheReader, study_id: str) -> str | None:
    """Title, abstract and cached full text of the record of ``study_id``; None when there is no record."""
    parts: list[str] = []
    if study_id.startswith("pmid:"):
        pmid = study_id.removeprefix("pmid:")
        record = cache.record(pmid)
        if isinstance(record, str):
            return None
        parts += [record.title, record.abstract or ""]
        full = cache.fulltext(pmid)
        if isinstance(full, str):
            parts.append(full)
    elif study_id.startswith("doi:"):
        try:
            preprint = cache.preprint(study_id)
        except EuropePmcError:
            return None
        if preprint is None:
            return None
        parts += [preprint.title, _TAG_RE.sub(" ", preprint.abstract or "")]
        full = cache.preprint_fulltext(preprint)
        if isinstance(full, str):
            parts.append(full)
    else:
        return None
    return "\n".join(parts)


def _source_tokens(cache: CacheReader, card, study_id: str) -> set[str] | None:
    """The numbers a cited study offers: those of its record, and its structured fields (year, n_patients,
    n_controls). None when there is neither a record nor a study on the card."""
    if study_id not in cache._number_tokens:
        text = _record_text(cache, study_id)
        tokens = source_number_tokens(text) if text is not None else None
        for study in card.studies:
            if study.id == study_id:
                tokens = (tokens or set()) | {
                    canonical_number(str(v)) for v in (study.year, study.n_patients, study.n_controls) if v is not None
                }
        cache._number_tokens[study_id] = tokens
    return cache._number_tokens[study_id]


_FINDING_RE = re.compile(r"^studies\[(.+)\]\.finding$")


def check_numbers(file: str, card, cache: CacheReader, level: str = WARNING) -> list[CitationIssue]:
    """C10: every numeral of every free-text item occurs in a source the item cites, or equals a structured field
    of one. A paragraph's sources are its own ``sources``; a study's ``finding`` cites its own study.

    The issue is keyed by the kind of item and the words around the number, not by the paragraph's index, so a
    problem that was on the card before a change is still the same problem after a paragraph is removed.
    """
    issues: list[CitationIssue] = []
    for locator, item in english_items(card).items():
        if locator == "name":
            continue
        kind = re.sub(r"\[\d+\]", "", locator)
        match = _FINDING_RE.match(locator)
        sources = [match.group(1)] if match else list(item.sources or [])
        numerals, problems = free_text_numerals(item.text)
        for problem in problems:
            issues.append(CitationIssue(file, kind, "C10", level, problem))
        available: set[str] = set()
        for source in sources:
            available |= _source_tokens(cache, card, source) or set()
        for numeral in numerals:
            if numeral in available:
                continue
            context = _context(item.text, numeral)
            issues.append(
                CitationIssue(
                    file,
                    kind,
                    "C10",
                    level,
                    f"the number {numeral} ({context}) does not occur in the cited source(s) "
                    f"{', '.join(sources) or '(none)'} nor equal year, n_patients or n_controls of one",
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Author facts (C11 and the contexts of the drafter, the reviewer and the valve)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthorList:
    """The authors of one cached record in record order, with each author's affiliations (may be empty)."""

    authors: tuple[str, ...]
    affiliations: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class SharedAuthors:
    """Two studies and the authors they share: ``exact`` (same name after the C9 normalisation) and ``loose``
    (same last name and same first initial; never fewer than ``exact``)."""

    first: str
    second: str
    exact: int
    loose: int
    names: tuple[str, ...]


def _split_name(name: str) -> tuple[str, str]:
    """(last name, initials) of a record author ``<last> <initials>``; initials are empty for a collective author
    or a name with no initials."""
    last, _, initials = name.rpartition(" ")
    if last and re.fullmatch(r"[^\W\d_]+", initials) and initials.isupper():
        return last, initials
    return name, ""


def exact_author_key(name: str) -> str:
    """The same name after NFKD, marks removed, case folded (the C9 normalisation)."""
    return _strip_marks(name).casefold()


def loose_author_key(name: str) -> tuple[str, str]:
    """Last name and first initial, normalised; a collective author is its full name."""
    last, initials = _split_name(_strip_marks(name))
    return last.casefold(), initials[:1].casefold()


def shared_authors(a: AuthorList, b: AuthorList) -> tuple[int, int, list[str]]:
    """(exact, loose, names): the distinct authors two lists share by each match; ``names`` are the shared authors
    by the loose match, in the spelling of ``a`` (with the other spelling when it differs)."""
    exact_b = {exact_author_key(n): n for n in b.authors}
    loose_b: dict[tuple[str, str], str] = {}
    for n in b.authors:
        loose_b.setdefault(loose_author_key(n), n)
    exact: set[str] = set()
    loose: dict[tuple[str, str], str] = {}
    for n in a.authors:
        if (key := exact_author_key(n)) in exact_b:
            exact.add(key)
        if (lkey := loose_author_key(n)) in loose_b and lkey not in loose:
            other = loose_b[lkey]
            loose[lkey] = n if exact_author_key(other) == exact_author_key(n) else f"{n} (as {other})"
    return len(exact), len(loose), list(loose.values())


def author_facts(lists: Mapping[str, AuthorList]) -> list[SharedAuthors]:
    """The pairs of studies (in the order of ``lists``) that share at least one author by either match."""
    ids = list(lists)
    out: list[SharedAuthors] = []
    for i, first in enumerate(ids):
        for second in ids[i + 1 :]:
            exact, loose, names = shared_authors(lists[first], lists[second])
            if loose:
                out.append(SharedAuthors(first, second, exact, loose, tuple(names)))
    return out


def study_author_list(cache: CacheReader, study_id: str) -> AuthorList | None:
    """The cached author list of a study (PubMed record, or the Europe PMC preprint record), None when the record
    is missing or has no authors."""
    if study_id.startswith("pmid:"):
        record = cache.record(study_id.removeprefix("pmid:"))
        if isinstance(record, str) or not record.authors:
            return None
        affiliations = tuple(tuple(a) for a in record.affiliations)
        if len(affiliations) != len(record.authors):
            affiliations = ()
        return AuthorList(tuple(record.authors), affiliations)
    if study_id.startswith("doi:"):
        try:
            preprint = cache.preprint(study_id)
        except EuropePmcError:
            return None
        return AuthorList(tuple(preprint.authors)) if preprint is not None and preprint.authors else None
    return None


def card_author_lists(card, cache: CacheReader) -> tuple[dict[str, AuthorList], list[str]]:
    """The author lists of the studies on ``card`` that have one, and the ids of those that have none."""
    lists: dict[str, AuthorList] = {}
    missing: list[str] = []
    for study in card.studies:
        found = study_author_list(cache, study.id)
        if found is None:
            missing.append(study.id)
        else:
            lists[study.id] = found
    return lists, missing


_AFFILIATION_CHARS = 160
_NAMES_SHOWN = 12


def _first_last_line(study_id: str, found: AuthorList) -> str:
    def person(i: int) -> str:
        text = found.authors[i]
        affiliations = found.affiliations[i] if found.affiliations else ()
        if affiliations:
            first = affiliations[0]
            text += f" ({first[:_AFFILIATION_CHARS]}{'…' if len(first) > _AFFILIATION_CHARS else ''})"
        return text

    n = len(found.authors)
    last = f"; last author {person(n - 1)}" if n > 1 else ""
    return f"- {study_id}: {n} author(s); first author {person(0)}{last}"


def author_facts_section(card, cache: CacheReader) -> str:
    """The "Author facts" section of a context file, computed from the cached records of the studies on ``card``."""
    lists, missing = card_author_lists(card, cache)
    lines = ["## Author facts (computed by code from the cached records)", ""]
    if lists:
        lines += ["Studies with a cached author list (first and last author, with their first affiliation if any):"]
        lines += [_first_last_line(i, found) for i, found in lists.items()]
    else:
        lines.append("No study on the card has a cached author list.")
    lines.append("")
    pairs = author_facts(lists)
    if pairs:
        lines.append(
            "Pairs of cited studies that share at least one author (exact = same name after normalisation; "
            "loose = same last name and first initial):"
        )
        for p in pairs:
            shown = ", ".join(p.names[:_NAMES_SHOWN]) + (
                f", and {len(p.names) - _NAMES_SHOWN} more" if len(p.names) > _NAMES_SHOWN else ""
            )
            lines.append(f"- {p.first} and {p.second}: {p.exact} exact, {p.loose} loose: {shown}")
        lines.append("Every other pair of cited studies shares no author by name in the records.")
    else:
        lines.append("No pair of cited studies shares an author by name in the records.")
    if missing:
        lines.append(f"No cached author list (these studies are not covered): {', '.join(missing)}.")
    lines += ["", "State authors, shared-author counts and positions only as given here.", ""]
    return "\n".join(lines)


_COUNT_WORDS = "|".join(_UNIT_WORDS + _TEEN_WORDS + ["twenty"])
_N = rf"(?P<n>\d+|{_COUNT_WORDS})"
_AUTHOR = r"(?:co-?)?authors?"
_COUNT_PATTERNS = [
    re.compile(rf"\bshare[sd]?\s+(?:exactly\s+)?{_N}\s+(?:of\s+(?:their|the)\s+)?{_AUTHOR}\b", re.IGNORECASE),
    re.compile(rf"\b{_N}\s+(?:shared|common)\s+{_AUTHOR}\b", re.IGNORECASE),
    re.compile(rf"\b{_N}\s+{_AUTHOR}\s+in\s+common\b", re.IGNORECASE),
]
# before a number, these make it a bound or an estimate, not a count
_NOT_EXACT = re.compile(
    r"(?:at\s+least|at\s+most|more\s+than|fewer\s+than|less\s+than|over|under|up\s+to|about|around|roughly|"
    r"approximately|nearly|almost|only|just)\s+$",
    re.IGNORECASE,
)
_NO_SHARED_PATTERNS = [
    re.compile(rf"\bno\s+{_AUTHOR}\s+(?:are\s+|were\s+)?shared\b", re.IGNORECASE),
    re.compile(rf"\bshar(?:e|es|ed|ing)\s+no\s+{_AUTHOR}\b", re.IGNORECASE),
    re.compile(rf"\bno\s+shared\s+{_AUTHOR}\b", re.IGNORECASE),
    re.compile(rf"\bno\s+{_AUTHOR}\s+in\s+common\b", re.IGNORECASE),
    re.compile(r"\bno\s+author\s+overlap\b", re.IGNORECASE),
    re.compile(r"\bindependent\s+(?:research\s+)?groups\b(?!\s+of\b)", re.IGNORECASE),
]
# before the phrase, these make it a negation or a qualified statement: not checked
_QUALIFIED = re.compile(
    r"\b(?:not|never|nor|neither|partly|partially|largely|barely|hardly|unlikely|whether|if)\b|n[’']t\b",
    re.IGNORECASE,
)
_DESCRIPTIVE_COUNTERPART = re.compile(r"\s+with\s+(?:the|a|an|that|this|its|their|those|these)\b", re.IGNORECASE)
_WITH_COUNTERPART = re.compile(chr(92) + "s+with" + chr(92) + "b", re.IGNORECASE)
_GROUP_POSITION = re.compile(r"\b(?P<pos>first|last)\s+author\b(?![’'])", re.IGNORECASE)
_ALSO_ON = re.compile(r"(?P<names>[^;()]*?)\s+also\s+on\s+(?P<pmids>\d+(?:\s*(?:,|and|&)\s*\d+)*)", re.IGNORECASE)
_PMID_RE = re.compile(r"\d+")


def _count_value(token: str) -> int:
    return (
        int(token)
        if token.isdigit()
        else int(_WORD_NUMBERS[token.casefold()])
        if token.casefold() in _WORD_NUMBERS
        else -1
    )


def _cited_author_lists(
    sources: Sequence[str], cache: CacheReader, memo: dict[str, AuthorList | None]
) -> dict[str, AuthorList]:
    found: dict[str, AuthorList] = {}
    for source in dict.fromkeys(sources):
        if source not in memo:
            memo[source] = study_author_list(cache, source)
        if (got := memo[source]) is not None:
            found[source] = got
    return found


def _pair_counts(lists: Mapping[str, AuthorList]) -> list[tuple[str, str, int, int]]:
    ids = list(lists)
    return [(a, b, *shared_authors(lists[a], lists[b])[:2]) for i, a in enumerate(ids) for b in ids[i + 1 :]]


def _check_free_text_authors(file: str, card, cache: CacheReader, level: str) -> list[CitationIssue]:
    """C11 (a) and (b): a free-text item that states how many authors studies share, or that they share none, against
    the author lists of the studies the item cites. Only items that cite at least two studies with a list."""
    issues: list[CitationIssue] = []
    memo: dict[str, AuthorList | None] = {}
    for locator, item in english_items(card).items():
        if locator == "name" or _FINDING_RE.match(locator) or not item.sources:
            continue
        lists = _cited_author_lists(item.sources, cache, memo)
        if len(lists) < 2:
            continue
        kind = re.sub(r"\[\d+\]", "", locator)
        pairs = _pair_counts(lists)
        shown = "; ".join(f"{a} and {b}: {e} exact, {n} loose" for a, b, e, n in pairs[:6])
        text = " ".join(item.text.split())
        for pattern in _COUNT_PATTERNS:
            for m in pattern.finditer(text):
                if _NOT_EXACT.search(text[: m.start("n")]):
                    continue
                if _DESCRIPTIVE_COUNTERPART.match(text, m.end()):
                    continue  # "shares two authors with the Swedish study": the study named may not be cited here
                value = _count_value(m.group("n"))
                if value < 0 or any(e <= value <= n for _a, _b, e, n in pairs):
                    continue
                issues.append(
                    CitationIssue(
                        file,
                        kind,
                        "C11",
                        level,
                        f"the text says {m.group(0)!r}, but the records of the cited studies give: {shown}",
                    )
                )
        if not all(e >= 1 for _a, _b, e, _n in pairs):
            continue
        for number, pattern in enumerate(_NO_SHARED_PATTERNS):
            for m in pattern.finditer(text):
                if number < len(_NO_SHARED_PATTERNS) - 1 and _WITH_COUNTERPART.match(text, m.end()):
                    continue  # "no authors are shared with the earlier study": the study named may not be cited here
                if _QUALIFIED.search(text[max(0, m.start() - 30) : m.start()]):
                    continue
                issues.append(
                    CitationIssue(
                        file,
                        kind,
                        "C11",
                        level,
                        f"the text says {m.group(0)!r}, but every pair of the cited studies shares at least one "
                        f"author by exact name in the records: {shown}",
                    )
                )
    return issues


def _last_name_in(author: str, text: str) -> bool:
    """Whether the last name (or the collective name) of a record author occurs in ``text`` as whole words."""
    last, _initials = _split_name(_strip_marks(author))
    return re.search(rf"(?<!\w)(?i:{re.escape(last)})(?!\w)", _strip_marks(text)) is not None


def _name_token(token: str) -> str | None:
    """``token`` when it reads as ``<Last> <INITIALS>`` (capitalised words, then 1-3 capital letters), else None."""
    words = token.split()
    if len(words) < 2 or not (words[-1].isalpha() and words[-1].isupper() and len(words[-1]) <= 3):
        return None
    return " ".join(words) if all(w[0].isupper() for w in words[:-1]) else None


def _check_group_authors(file: str, study: Study, cache: CacheReader, level: str) -> list[CitationIssue]:
    """C11 (c) and (d): positions and "also on" claims in a study's ``group`` against the cached author lists."""
    if study.group is None:
        return []
    group = " ".join(study.group.split())
    issues: list[CitationIssue] = []
    own = study_author_list(cache, study.id)
    if own is not None:
        for m in _GROUP_POSITION.finditer(group):
            tail = re.split(r"[;()]", group[m.end() :], maxsplit=1)[0][:40]
            if not re.match(r"\s*(?:(?:Dr|Prof)\.?\s+)?[A-Z]", tail):
                continue  # "first author at ...", "first author, same institute": no name is claimed
            record_author = own.authors[0 if m.group("pos").lower() == "first" else -1]
            if author_in_group(record_author, tail) or _last_name_in(record_author, tail):
                continue
            issues.append(
                CitationIssue(
                    file,
                    study.id,
                    "C11",
                    level,
                    f"group says {m.group(0)}{tail.rstrip()!r} but the {m.group('pos').lower()} author of the "
                    f"record is {record_author}",
                )
            )
    memo: dict[str, AuthorList | None] = {}
    for m in _ALSO_ON.finditer(group):
        tokens = [t.strip() for t in re.split(r"\s+and\s+|\s*&\s*|,\s*", m.group("names").strip())]
        names = [n for t in tokens if (n := _name_token(t)) is not None]
        for pmid in _PMID_RE.findall(m.group("pmids")):
            other = _cited_author_lists([f"pmid:{pmid}"], cache, memo).get(f"pmid:{pmid}")
            if other is None:
                continue
            for name in names:
                probe = AuthorList((name,))
                if shared_authors(probe, other)[1] or any(author_in_group(a, name) for a in other.authors):
                    continue
                issues.append(
                    CitationIssue(
                        file,
                        study.id,
                        "C11",
                        level,
                        f"group says {name!r} is also on {pmid}, but that record's authors do not include that name",
                    )
                )
    return issues


def check_authors(file: str, card, cache: CacheReader, level: str = WARNING) -> list[CitationIssue]:
    """C11: statements about authors against the cached author lists (see docs/citation-check.md). Issues are keyed
    by the kind of item (or the study) and the words, never by a paragraph's index. In doubt nothing is reported."""
    issues = _check_free_text_authors(file, card, cache, level)
    for study in card.studies:
        issues += _check_group_authors(file, study, cache, level)
    return issues


def check_errata(file: str, card, cache: CacheReader) -> list[CitationIssue]:
    """C12 (warning): a cited study whose cached record lists an erratum that is not a study on the card.

    A study that is not cached, or a record without erratum links, gives nothing (C1 reports the missing record)."""
    on_card = {s.id for s in card.studies}
    issues: list[CitationIssue] = []
    for study in card.studies:
        if not study.id.startswith("pmid:"):
            continue
        record = cache.record(study.id.removeprefix("pmid:"))
        if isinstance(record, str):
            continue
        for erratum in record.errata:
            if f"pmid:{erratum}" not in on_card:
                issues.append(
                    CitationIssue(
                        file,
                        study.id,
                        "C12",
                        WARNING,
                        f"the PubMed record lists an erratum, pmid:{erratum}, that is not a study on this card; "
                        "add it as a study with `corrects`",
                    )
                )
    return issues


def _context(text: str, numeral: str) -> str:
    """A few words around the first place ``numeral`` appears in ``text``, for the message."""
    flat = " ".join(text.split())
    for found in _NUMERAL_RE.finditer(_normalise_numbers_text(flat)):
        if canonical_number(found.group(0)) == numeral:
            return "…" + flat[max(0, found.start() - 25) : found.end() + 25].strip() + "…"
    return "…"


def check_file(path: Path, cache: CacheReader, numbers_level: str = WARNING) -> list[CitationIssue]:
    """All issues for one card or draft file. A file that cannot be loaded is one or more LOAD errors."""
    file = str(path)
    try:
        card = load_card(path)
    except CardValidationError as exc:
        return [
            CitationIssue(
                file,
                i.path or "(whole file)",
                "LOAD",
                ERROR,
                f"cannot check, file did not load: [{i.rule}] {i.message}",
            )
            for i in exc.issues
        ]
    issues: list[CitationIssue] = []
    for study in card.studies:
        issues += check_study(file, study, cache)
    issues += check_numbers(file, card, cache, numbers_level)
    issues += check_authors(file, card, cache, numbers_level)
    issues += check_errata(file, card, cache)
    return issues


def check_paths(
    paths: Sequence[Path], cache_root: Path, numbers_level: str = WARNING, confirmations: Path | None = None
) -> tuple[int, list[CitationIssue]]:
    """Check files and directories. Returns (number of files checked, all issues).

    ``numbers_level`` is the level of a C10 issue: WARNING for what is published or drafted already, ERROR for a
    text that has just been applied (a correction round, a valve fix, the weekly pipeline)."""
    cache = CacheReader(cache_root, confirmations)
    files: list[Path] = []
    issues: list[CitationIssue] = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(f for f in p.glob("*.yaml") if f.name != CHANGELOG_NAME)
        elif p.is_file():
            files.append(p)
        else:
            issues.append(CitationIssue(str(p), "(whole file)", "LOAD", ERROR, "path does not exist"))
    for f in files:
        issues += check_file(f, cache, numbers_level)
    return len(files), issues


# ---------------------------------------------------------------------------
# Bibliography: copy authors, journal and doi from the cached records onto the studies
# ---------------------------------------------------------------------------

_STUDY_START = re.compile(r"^(\s*)- id: (\S+)\s*$")
_BIB_LINE = re.compile(r"^\s+(authors|journal|doi): ")


@dataclass(frozen=True)
class BibliographyResult:
    """What ``fill_bibliography`` found in one card file."""

    text: str
    filled: list[str]  # study ids whose fields were added or changed
    unchanged: list[str]  # study ids that already have the right fields
    skipped: list[tuple[str, str]]  # (study id, why it was left as it is)


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _bib_lines(record: PubMedRecord, indent: str) -> list[str]:
    return [
        f"{indent}authors: {scalar(list(record.authors))}",
        f"{indent}journal: {scalar(record.journal)}",
        f"{indent}doi: {scalar(record.doi or None)}",
    ]


def fill_bibliography(text: str, cache: CacheReader) -> BibliographyResult:
    """Set ``authors``, ``journal`` and ``doi`` on every ``pmid:`` study of the card text whose record is cached.

    Line based: the three lines are inserted after the study's ``year:`` line (or replace the lines it already has),
    so no other line, comment or ordering changes. A study whose record is not cached, has no journal in the record
    or is a ``doi:`` study is left as it is and listed in ``skipped``. Offline.
    """
    if "\r" in text:
        raise ValueError("the card file uses CRLF line endings; convert it to LF first")
    lines = text.split("\n")
    top = next((i for i, line in enumerate(lines) if line.rstrip() == "studies:"), None)
    if top is None:
        return BibliographyResult(text, [], [], [])
    starts = [(i, m) for i in range(top + 1, len(lines)) if (m := _STUDY_START.match(lines[i]))]
    # A study block ends at the next study start or at the next top-level key.
    end_of_list = next((i for i in range(top + 1, len(lines)) if lines[i] and lines[i][0] not in " #-"), len(lines))
    filled: list[str] = []
    unchanged: list[str] = []
    skipped: list[tuple[str, str]] = []
    for n in reversed(range(len(starts))):
        first, match = starts[n]
        study_id = match.group(2)
        last = starts[n + 1][0] if n + 1 < len(starts) else end_of_list
        if not study_id.startswith("pmid:"):
            skipped.append((study_id, "a doi: study, left unchanged"))
            continue
        record = cache.record(study_id.removeprefix("pmid:"))
        if isinstance(record, str):
            skipped.append((study_id, f"record {record}"))
            continue
        if not record.journal or not record.journal.strip():
            skipped.append((study_id, "the record has no journal"))
            continue
        field_indent = " " * (len(match.group(1)) + 2)
        block = lines[first:last]
        year_at = next((k for k, line in enumerate(block) if re.match(rf"^{field_indent}year: ", line)), None)
        if year_at is None:
            skipped.append((study_id, "no year: line found in the block"))
            continue
        wanted = _bib_lines(record, field_indent)
        have = [k for k, line in enumerate(block) if _BIB_LINE.match(line) and _indent_of(line) == len(field_indent)]
        if [block[k] for k in have] == wanted:
            unchanged.append(study_id)
            continue
        new_block = [line for k, line in enumerate(block) if k not in have]
        at = next(k for k, line in enumerate(new_block) if re.match(rf"^{field_indent}year: ", line)) + 1
        new_block[at:at] = wanted
        lines[first:last] = new_block
        filled.append(study_id)
    return BibliographyResult("\n".join(lines), filled[::-1], unchanged[::-1], skipped[::-1])


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _bibliography_command(args: argparse.Namespace) -> int:
    paths = args.paths or [Path("cards")]
    files: list[Path] = []
    for p in paths:
        files += sorted(f for f in p.glob("*.yaml") if f.name != CHANGELOG_NAME) if p.is_dir() else [p]
    cache = CacheReader(args.cache_dir)
    total_filled = total_unchanged = total_skipped = 0
    for f in files:
        text = f.read_bytes().decode("utf-8")
        result = fill_bibliography(text, cache)
        if result.text != text:
            reparsed = yaml.safe_load(result.text)
            original = yaml.safe_load(text)
            for s in reparsed["studies"]:
                s.pop("authors", None), s.pop("journal", None), s.pop("doi", None)
            for s in original["studies"]:
                s.pop("authors", None), s.pop("journal", None), s.pop("doi", None)
            if reparsed != original:
                print(f"{f}: refused, the edit would change something other than the three fields", file=sys.stderr)
                return 1
            if args.write:
                f.write_bytes(result.text.encode("utf-8"))
        total_filled += len(result.filled)
        total_unchanged += len(result.unchanged)
        total_skipped += len(result.skipped)
        for sid in result.filled:
            print(f"{f}: {'filled' if args.write else 'would fill'} {sid}")
        for sid, why in result.skipped:
            print(f"{f}: LEFT UNCHANGED {sid}: {why}")
    verb = "filled" if args.write else "would fill"
    print(f"{verb} {total_filled} stud(ies), {total_unchanged} already right, {total_skipped} left unchanged")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m me_atlas.citations", description="Mechanical citation check.")
    sub = parser.add_subparsers(dest="command", required=True)
    chk = sub.add_parser("check", help="check studies on cards and drafts against the cached records (offline)")
    chk.add_argument("paths", nargs="*", type=Path, help="files or directories (default: cards/ and drafts/)")
    chk.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_ROOT, help="default: %(default)s")
    chk.add_argument("--confirmations", type=Path, default=DEFAULT_CONFIRMATIONS, help="default: %(default)s")
    bib = sub.add_parser(
        "bibliography",
        help="copy authors, journal and doi from the cached PubMed records onto the studies of cards (offline)",
    )
    bib.add_argument("paths", nargs="*", type=Path, help="files or directories (default: cards/)")
    bib.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_ROOT, help="default: %(default)s")
    bib.add_argument("--write", action="store_true", help="write the files (default: only report)")
    args = parser.parse_args(argv)

    if args.command == "bibliography":
        return _bibliography_command(args)
    paths = args.paths or [p for p in (Path("cards"), Path("drafts")) if p.is_dir()]
    count, issues = check_paths(paths, args.cache_dir, confirmations=args.confirmations)
    for item in issues:
        print(item)
    errors = sum(i.level == ERROR for i in issues)
    warnings = sum(i.level == WARNING for i in issues)
    print(f"{'FAILED' if errors else 'OK'}: {count} file(s) checked, {errors} error(s), {warnings} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
