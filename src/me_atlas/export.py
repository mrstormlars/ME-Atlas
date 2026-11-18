"""Open data and citation export: the cards as one JSON file, four CSV files and per-card BibTeX and RIS files.

Pure functions: cards and map content in, text out. Nothing is looked up, nothing is read from ``data/cache/`` and no
text is written about any card; the files hold what the cards hold (credibility rule 1). The site build writes the
result to ``data/`` (``me_atlas.site``). See ``docs/site.md``; the fields are defined in ``docs/card-format.md`` only.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from me_atlas import map as maplib
from me_atlas.cards import Card, Study

SITE_URL = "https://mrstormlars.github.io/ME-Atlas/"
REPO_URL = "https://github.com/mrstormlars/ME-Atlas"
LICENCE_ID = "CC-BY-4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
TITLE = "ME Atlas: evidence cards on the causes of ME/CFS and long COVID"

RIGHTS_NOTE = "Article titles and sentences quoted from papers stay with their rights holders and are not relicensed."
LANGUAGE_NOTE = (
    "The data is in English only. English is authoritative. The Norwegian translations are in the repository under "
    "translations/nb/ and are not part of this download."
)
REVIEW_STATEMENT = (
    "The content, including every evidence level, is drafted, checked and decided by AI tools. "
    "No medical or research expert has reviewed it."
)
DESCRIBES_NOTE = "The data describes the state of the evidence. It gives no treatment advice."

# File names under data/, in the order the README and the data page list them.
DATA_FILES = (
    "me-atlas.json",
    "hypotheses.csv",
    "studies.csv",
    "links.csv",
    "trials.csv",
    "resources.csv",
    "card-format.md",
    "README.txt",
)
CITATIONS_DIR = "citations"

HYPOTHESES_COLUMNS = (
    "slug",
    "name",
    "level",
    "layer",
    "contested_rungs",
    "diagnostic_marker",
    "explains_pem",
    "supporting_studies",
    "contradicting_studies",
    "other_studies",
    "links_out",
    "long_covid",
)
STUDIES_COLUMNS = (
    "card",
    "id",
    "title",
    "year",
    "authors",
    "journal",
    "doi",
    "cohort",
    "case_definition",
    "case_definition_source",
    "case_definition_quote",
    "design",
    "n_patients",
    "n_controls",
    "measures_pem",
    "preregistered",
    "role",
    "direction",
    "finding",
    "group",
    "preprint",
    "corrects",
)
LINKS_COLUMNS = ("source", "target", "target_kind", "target_name", "support", "text", "sources")
TRIALS_COLUMNS = (
    "nct_id",
    "title",
    "study_type",
    "status",
    "countries",
    "enrollment_count",
    "enrollment_type",
    "start_date",
    "last_update",
    "searches",
    "hypotheses",
    "mapping",
    "mapping_source",
)
RESOURCES_COLUMNS = (
    "id",
    "name",
    "operator",
    "countries",
    "url",
    "access_url",
    "checked",
    "category",
    "holds",
    "access",
    "covers",
    "language",
    "source",
    "name_quote",
    "name_page",
    "operator_quote",
    "operator_page",
    "countries_quote",
    "countries_page",
    "access_quote",
    "access_page",
    "covers_quote",
    "covers_page",
    "holds_quotes",
)


DATASET_DOI = "10.5281/zenodo.24333249"  # the Zenodo concept DOI: it points to every archived version
DATASET_DOI_URL = f"https://doi.org/{DATASET_DOI}"


def citation_text(built: str) -> str:
    """How to cite the dataset: ends with the concept DOI as a link."""
    return f"ME Atlas contributors ({built[:4]}). {TITLE}. Version {built}. {SITE_URL} {DATASET_DOI_URL}"


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------


def _target_kind(target: str) -> str:
    if target.startswith(maplib.SYMPTOM_PREFIX):
        return "symptom"
    if target.startswith(maplib.QUESTION_PREFIX):
        return "question"
    return "card"


def counts(cards: Sequence[Card], graph: maplib.Graph) -> dict[str, int]:
    """The numbers the data holds: cards, study rows (studies summed over cards), distinct study ids and links.
    Links are the graph's edges, the same as the gaps page counts."""
    return {
        "cards": len(cards),
        "study_rows": sum(len(c.studies) for c in cards),
        "distinct_studies": len({s.id for c in cards for s in c.studies}),
        "links": sum(len(edges) for edges in graph.out.values()),
    }


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def dataset_json(
    cards: Sequence[Card],
    content: maplib.MapContent,
    *,
    built: str,
    draft_preview: bool,
    trials: Sequence[Mapping[str, Any]] = (),
    trials_fetched: str | None = None,
    resources: Sequence[Mapping[str, Any]] = (),
    resources_checked: str | None = None,
) -> tuple[str, dict[str, int]]:
    """The text of ``me-atlas.json`` and its counts. ``trials`` are the entries of ``registry/trials.yaml``, all of
    them (matched or not, ongoing or not), as the registry file holds them; ``trials_fetched`` is the fetch date.
    ``resources`` are the published entries of ``registry/resources.yaml`` (none unless its reliability test passed)
    and ``resources_checked`` the run date of that file."""
    ordered = sorted(cards, key=lambda c: c.slug)
    graph = maplib.build_graph(ordered, content)
    numbers = counts(ordered, graph)
    doc: dict[str, Any] = {
        "dataset": {
            "title": TITLE,
            "version": built,
            "site_url": SITE_URL,
            "repository_url": REPO_URL,
            "doi": DATASET_DOI,
            "doi_url": DATASET_DOI_URL,
            "licence": LICENCE_ID,
            "licence_url": LICENCE_URL,
            "rights_note": RIGHTS_NOTE,
            "citation": citation_text(built),
            "language_note": LANGUAGE_NOTE,
            "review_statement": REVIEW_STATEMENT,
            "draft_preview": draft_preview,
            "counts": numbers,
            "trials_fetched": trials_fetched,
            "resources_checked": resources_checked,
        },
        "cards": [c.model_dump(mode="json") for c in ordered],
        "symptoms": [{"id": s.id, "name": s.name} for s in content.symptoms],
        "questions": [{"id": q.id, "text": q.text} for q in content.questions],
        "trials": [dict(t) for t in trials],
        "resources": [dict(r) for r in resources],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n", numbers


# ---------------------------------------------------------------------------
# CSV (UTF-8, RFC 4180: CRLF line ends, quotes where needed, header row)
# ---------------------------------------------------------------------------


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "; ".join(_cell(v) for v in value)
    return str(value)


def _csv(columns: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return out.getvalue()


def hypotheses_csv(cards: Sequence[Card], content: maplib.MapContent) -> str:
    ordered = sorted(cards, key=lambda c: c.slug)
    graph = maplib.build_graph(ordered, content)
    rows = []
    for c in ordered:
        rows.append(
            (
                c.slug,
                c.name,
                c.level,
                c.layer,
                c.hatched_rungs,
                c.badges.diagnostic_marker.value,
                c.badges.explains_pem.value,
                sum(s.role == "supports" for s in c.studies),
                sum(s.role == "contradicts" for s in c.studies),
                sum(s.role in ("context", "early_signal") for s in c.studies),
                len(graph.out.get(c.slug, [])),
                c.long_covid,
            )
        )
    return _csv(HYPOTHESES_COLUMNS, rows)


def studies_csv(cards: Sequence[Card]) -> str:
    rows = []
    for c in sorted(cards, key=lambda c: c.slug):
        for s in c.studies:
            fields = s.model_dump(mode="json")
            rows.append((c.slug, *(fields[name] for name in STUDIES_COLUMNS[1:])))
    return _csv(STUDIES_COLUMNS, rows)


def links_csv(cards: Sequence[Card], content: maplib.MapContent) -> str:
    ordered = sorted(cards, key=lambda c: c.slug)
    graph = maplib.build_graph(ordered, content)
    rows = []
    for c in ordered:
        for e in graph.out.get(c.slug, []):
            rows.append(
                (e.source, e.target, _target_kind(e.target), graph.nodes[e.target].name, e.support, e.text, e.sources)
            )
    return _csv(LINKS_COLUMNS, rows)


def trials_csv(entries: Sequence[Mapping[str, Any]]) -> str:
    """One row per registered study of ``registry/trials.yaml``: every entry, matched or not, ongoing or not."""
    rows = []
    for e in entries:
        enrol = e["enrollment"] or {}
        rows.append(
            (
                e["nct_id"],
                e["title"],
                e["study_type"],
                e["status"],
                e["countries"],
                enrol.get("count"),
                enrol.get("type"),
                e["start_date"],
                e["last_update"],
                e["searches"],
                e["hypotheses"],
                e["mapping"],
                e["mapping_source"],
            )
        )
    return _csv(TRIALS_COLUMNS, rows)


def resources_csv(entries: Sequence[Mapping[str, Any]]) -> str:
    """One row per published entry of ``registry/resources.yaml``; list fields joined with ``; ``; the quotes and the
    page each came from are columns."""
    rows = []
    for e in entries:
        q = e["quotes"]
        held = [f"{hold} ({item['page']}): {item['quote']}" for hold, item in q["holds"].items()]
        rows.append(
            (
                e["id"],
                e["name"],
                e["operator"],
                e["countries"],
                e["url"],
                e["access_url"],
                e["checked"],
                e["category"],
                e["holds"],
                e["access"],
                e["covers"],
                e["language"],
                e["source"],
                q["name"]["quote"],
                q["name"]["page"],
                q["operator"]["quote"],
                q["operator"]["page"],
                q["countries"]["quote"],
                q["countries"]["page"],
                q["access"]["quote"],
                q["access"]["page"],
                q["covers"]["quote"],
                q["covers"]["page"],
                held,
            )
        )
    return _csv(RESOURCES_COLUMNS, rows)


# ---------------------------------------------------------------------------
# Citation files
# ---------------------------------------------------------------------------

_BIB_ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "%": r"\%",
    "&": r"\&",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_BIB_SPECIAL = re.compile("[" + re.escape("".join(_BIB_ESCAPES)) + "]")


def bib_escape(text: str) -> str:
    """Escape the BibTeX special characters ``{ } % & $ # _ ~ ^ \\`` and fold line breaks to spaces."""
    return _BIB_SPECIAL.sub(lambda m: _BIB_ESCAPES[m.group(0)], " ".join(text.split()))


def bib_key(study_id: str) -> str:
    """``pmid:12345678`` becomes ``pmid12345678``; a character a BibTeX key cannot hold becomes ``_``."""
    return re.sub(r"[^A-Za-z0-9._/+-]", "_", study_id.replace(":", "", 1))


def bib_person(name: str) -> str:
    """One author name for the ``author`` field, in braces so a multi-part surname stays one name."""
    return "{" + bib_escape(name) + "}"


def bibtex(cards_studies: Sequence[Study], url_of: Callable[[str], str]) -> str:
    """One entry per study, in the given order. A study with ``authors`` and ``journal`` is an ``@article`` with the
    author names joined by `` and ``, the journal and the DOI (when it has one); any other study is a ``@misc`` with
    title, year and link only, as the card holds nothing more."""
    entries = []
    for s in cards_studies:
        kind, _, value = s.id.partition(":")
        article = bool(s.authors) and bool(s.journal)
        lines = [f"@{'article' if article else 'misc'}{{{bib_key(s.id)},"]
        if article:
            assert s.authors and s.journal
            lines.append(f"  author = {{{' and '.join(bib_person(a) for a in s.authors)}}},")
        lines.append(f"  title = {{{bib_escape(s.title)}}},")
        if article:
            assert s.journal
            lines.append(f"  journal = {{{bib_escape(s.journal)}}},")
        lines += [f"  year = {{{s.year}}},"]
        if article and s.doi and kind != "doi":
            lines.append(f"  doi = {{{s.doi}}},")
        lines.append(f"  url = {{{url_of(s.id)}}},")
        if kind == "pmid":
            lines.append(f"  note = {{PMID: {value}}}")
        else:
            lines.append(f"  doi = {{{value}}}")
        lines.append("}")
        entries.append("\n".join(lines) + "\n")
    return "\n".join(entries)


def ris(cards_studies: Sequence[Study], url_of: Callable[[str], str]) -> str:
    """One RIS record per study, in the given order, with CRLF line ends as the RIS specification requires.
    A study with bibliographic fields also gets one ``AU`` line per author, ``JO`` and ``DO``."""
    lines: list[str] = []
    for s in cards_studies:
        kind, _, value = s.id.partition(":")
        lines.append(f"TY  - {'UNPB' if s.preprint else 'JOUR'}")
        lines += [f"AU  - {' '.join(a.split())}" for a in s.authors or []]
        lines.append(f"TI  - {' '.join(s.title.split())}")
        if s.journal:
            lines.append(f"JO  - {' '.join(s.journal.split())}")
        lines.append(f"PY  - {s.year}")
        if s.doi:
            lines.append(f"DO  - {s.doi}")
        lines += [
            f"UR  - {url_of(s.id)}",
            f"AN  - PMID:{value}" if kind == "pmid" else f"DO  - {value}",
            "ER  - ",
            "",
        ]
    return "".join(line + "\r\n" for line in lines)


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------


def readme(*, built: str, draft_preview: bool) -> str:
    """The text of ``README.txt``. The fields are defined in ``card-format.md`` only; nothing is repeated here."""
    lines = ["ME Atlas open data", "=================="]
    if draft_preview:
        lines += ["", "DRAFT PREVIEW: this data was built with the drafts included. It is not the published data."]
    lines += [
        "",
        f"Version (build date): {built}",
        f"Site: {SITE_URL}",
        f"Repository: {REPO_URL}",
        f"DOI: {DATASET_DOI_URL}",
        f"Licence: {LICENCE_ID} ({LICENCE_URL})",
        RIGHTS_NOTE,
        "",
        "What this is",
        "------------",
        "The evidence cards of the site, derived by code from the cards the site shows and from the map content "
        "(symptoms and open questions). No text is written about any card.",
        LANGUAGE_NOTE,
        REVIEW_STATEMENT,
        DESCRIBES_NOTE,
        "",
        "How to cite",
        "-----------",
        citation_text(built),
        "",
        "Files",
        "-----",
        "me-atlas.json    The dataset block, every card with all its fields, the symptoms and the open questions.",
        "hypotheses.csv   One row per card: level, layer, contested rungs, badges, study and link counts.",
        "studies.csv      One row per study per card, with every study field.",
        "links.csv        One row per link between cards, symptoms and open questions.",
        "trials.csv       One row per registered study (ClinicalTrials.gov): status and the cards it bears on.",
        "                 A registered study is not evidence and is on no card; fields are copied from the registry.",
        "resources.csv    One row per listed data resource (ME/CFS datasets, registries, biobanks): what it holds,",
        "                 how it is accessed, and the quote from its own page that supports each value.",
        "                 A resource is not evidence; every value is copied from the resource's page.",
        "card-format.md   The meaning of every field. This is the only field definition.",
        "README.txt       This file.",
        "citations/       One BibTeX file (.bib) and one RIS file (.ris) per card, one entry per study.",
        "                 They hold the authors, title, journal, year, DOI and link of each study.",
        "",
        "Lists inside a CSV cell are joined with '; '. CSV is UTF-8 with a header row.",
        "The meaning of every field is in card-format.md.",
    ]
    return "\n".join(lines) + "\n"
