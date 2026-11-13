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
* C5 the case-definition quote appears verbatim in the stated source (abstract or cached full text)
* C6 (warning) ``n_patients`` and ``n_controls`` appear as numbers in the abstract or cached full text
* C7 a DOI-only study id that is not a preprint cannot be checked yet
* C8 ``preprint`` on the card agrees with the PubMed record (publication type "Preprint")

A ``doi:`` study with ``preprint: true`` is checked against the cached Europe PMC preprint record with that DOI
(``<cache>/europepmc/preprints/``): C1 (no record), C2, C3, C5 (abstract of the record, or the full text through
the shared ``<pmcid>.xml`` cache) and C6.
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from me_atlas.cards import CHANGELOG_NAME, CardValidationError, Study, load_card
from me_atlas.europepmc import (
    EuropePmcCache,
    EuropePmcError,
    PreprintRecord,
    article_text,
    is_placeholder_fulltext,
    pmc_page_text,
    read_cached_lookup,
    read_cached_preprints,
)
from me_atlas.pubmed import DEFAULT_CACHE_ROOT, ParseError, PubMedRecord, RawCache

ERROR = "ERROR"
WARNING = "WARNING"


@dataclass(frozen=True)
class CitationIssue:
    """One finding: which file and study, which check, error or warning, and what to do."""

    file: str
    study: str
    code: str  # C1..C8, or LOAD when the file could not be read as a card
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


def preprint_fetch_hint(doi: str) -> str:
    return f"uv run python -m me_atlas.europepmc preprint {doi}"


def pmcpage_fetch_hint(pmid: str) -> str:
    return f"uv run python -m me_atlas.europepmc pmcpage --card <card.yaml> {pmid}"


class CacheReader:
    """Reads and remembers cached records for one run."""

    def __init__(self, root: Path):
        self.pubmed = RawCache(root)
        self.epmc = EuropePmcCache(root)
        self._records: dict[str, PubMedRecord | str] = {}
        self._fulltexts: dict[str, str | tuple[str]] = {}
        self._preprints: dict[str, list[PreprintRecord]] | None = None

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

    issues += _check_quote(study, record.abstract, full, "PubMed", issue)
    issues += _check_sample_sizes(study, record.abstract, full, issue)
    return issues


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
    return issues


def _check_quote(study, abstract, full, record_name, issue) -> list[CitationIssue]:
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
    return [
        issue(
            "C5",
            ERROR,
            "case_definition_quote has no case_definition_source (abstract or fulltext) to check it against",
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


def check_file(path: Path, cache: CacheReader) -> list[CitationIssue]:
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
    return issues


def check_paths(paths: Sequence[Path], cache_root: Path) -> tuple[int, list[CitationIssue]]:
    """Check files and directories. Returns (number of files checked, all issues)."""
    cache = CacheReader(cache_root)
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
        issues += check_file(f, cache)
    return len(files), issues


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m me_atlas.citations", description="Mechanical citation check.")
    sub = parser.add_subparsers(dest="command", required=True)
    chk = sub.add_parser("check", help="check studies on cards and drafts against the cached records (offline)")
    chk.add_argument("paths", nargs="*", type=Path, help="files or directories (default: cards/ and drafts/)")
    chk.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_ROOT, help="default: %(default)s")
    args = parser.parse_args(argv)

    paths = args.paths or [p for p in (Path("cards"), Path("drafts")) if p.is_dir()]
    count, issues = check_paths(paths, args.cache_dir)
    for item in issues:
        print(item)
    errors = sum(i.level == ERROR for i in issues)
    warnings = sum(i.level == WARNING for i in issues)
    print(f"{'FAILED' if errors else 'OK'}: {count} file(s) checked, {errors} error(s), {warnings} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
