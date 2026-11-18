"""Tests for the bibliographic fields of a study (authors, journal, doi): the model, the C13 check, the filling
command, the operations that add a study, the exports and .zenodo.json. Fictional records; offline."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from test_citations import PMID, add_record, make_study, write_card
from test_export import read_bib
from test_operations import NEW_STUDY, PAPER, card_text, ops

from me_atlas import cards as cardlib
from me_atlas import citations, export, pubmed, site
from me_atlas.operations import apply_operations, cached_records, parse_ops

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTHORS = ["Fictionalsen A", "Van Der Test B", "Madeup C"]
JOURNAL = "Fictional Journal"


def add_bib_record(root: Path, pmid: str = PMID, doi: str | None = "10.9999/fictional.1", **kw) -> None:
    """A fictional record with three authors (one with a multi-part surname), a journal and, optionally, a DOI."""
    add_record(root, pmid, authors=(("Fictionalsen", "A"), ("Van Der Test", "B"), ("Madeup", "C")), **kw)
    if doi:
        path = root / "pubmed" / f"{pmid}.xml"
        tag = f'<ELocationID EIdType="doi">{doi}</ELocationID></Article>'.encode()
        path.write_bytes(path.read_bytes().replace(b"</Article>", tag))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "cache"
    add_bib_record(r)
    return r


def bib_study(**over) -> dict:
    return make_study(**{"authors": list(AUTHORS), "journal": JOURNAL, "doi": "10.9999/fictional.1", **over})


def issues(tmp_path: Path, root: Path, study: dict) -> list[citations.CitationIssue]:
    card = write_card(tmp_path / "drafts", [study])
    return citations.check_paths([card], root)[1]


# --- B1 / B2: the model -----


def test_the_record_fixture_gives_the_authors_and_journal_the_tests_expect(root):
    record = pubmed.RawCache(root).read_record(PMID)
    assert (record.authors, record.journal, record.doi) == (AUTHORS, JOURNAL, "10.9999/fictional.1")


def test_a_study_without_the_fields_still_validates_and_a_filled_one_does_too():
    plain = cardlib.Study.model_validate(make_study())
    assert (plain.authors, plain.journal, plain.doi) == (None, None, None)
    assert not {"authors", "journal", "doi"} & plain.model_fields_set
    filled = cardlib.Study.model_validate(bib_study())
    assert filled.authors == AUTHORS and filled.doi == "10.9999/fictional.1"
    assert cardlib.Study.model_validate(make_study(doi=None)).doi is None


@pytest.mark.parametrize(
    "over",
    [{"doi": "11.1000/x"}, {"doi": "doi:10.1000/x"}, {"authors": ["A", ""]}, {"authors": "A B"}, {"journal": ""}],
)
def test_the_fields_reject_wrong_values(over):
    with pytest.raises(ValidationError):
        cardlib.Study.model_validate(make_study(**over))


def test_unknown_study_fields_are_still_refused():
    with pytest.raises(ValidationError):
        cardlib.Study.model_validate(make_study(publisher="x"))


# --- B5: C13 -----


def test_c13_a_matching_study_passes_and_a_study_without_the_fields_passes(tmp_path, root):
    assert issues(tmp_path, root, bib_study()) == []
    assert issues(tmp_path, root, make_study()) == []


def test_c13_a_wrong_journal_is_an_error_naming_the_field(tmp_path, root):
    found = [i for i in issues(tmp_path, root, bib_study(journal="Another Journal")) if i.code == "C13"]
    assert len(found) == 1 and found[0].level == citations.ERROR and "journal" in found[0].message


def test_c13_one_wrong_author_is_an_error_naming_the_field(tmp_path, root):
    wrong = [AUTHORS[0], "Van Der Test X", AUTHORS[2]]
    found = [i for i in issues(tmp_path, root, bib_study(authors=wrong)) if i.code == "C13"]
    assert len(found) == 1 and found[0].level == citations.ERROR and "authors" in found[0].message
    # The same names in another order are also a mismatch: record order is part of the field.
    assert [i for i in issues(tmp_path, root, bib_study(authors=AUTHORS[::-1])) if i.code == "C13"]


def test_c13_a_doi_that_differs_from_the_record_is_an_error_and_null_against_a_doi_too(tmp_path, root):
    for doi in ("10.9999/other", None):
        found = [i for i in issues(tmp_path, root, bib_study(doi=doi)) if i.code == "C13"]
        assert len(found) == 1 and "doi" in found[0].message
    # A record with no DOI: null matches, a DOI does not.
    add_bib_record(root, "90000002", doi=None)
    ok = bib_study(doi=None, id="pmid:90000002")
    assert [i for i in issues(tmp_path, root, ok) if i.code == "C13"] == []
    assert [i for i in issues(tmp_path, root, bib_study(id="pmid:90000002")) if i.code == "C13"]


# --- B3: the filling command -----

CARD_TEXT = """\
# A comment at the top.
slug: fictional-card
studies:
  # --- supports ---
  - id: pmid:90000001
    title: Fictional study.
    year: 2021
    # a comment inside a study
    cohort: me_cfs
    finding: A finding.
  - id: pmid:90000002
    title: Fictional study two.
    year: 2020
    cohort: me_cfs
    finding: Another.
  - id: doi:10.1101/fictional
    title: A preprint.
    year: 2026
    preprint: true
last_checked:
  date: 2026-11-01
"""


def test_fill_bibliography_adds_only_the_three_lines_after_year_and_lists_the_rest(root):
    result = citations.fill_bibliography(CARD_TEXT, citations.CacheReader(root))
    assert result.filled == ["pmid:90000001"]
    assert [sid for sid, _ in result.skipped] == ["pmid:90000002", "doi:10.1101/fictional"]
    assert dict(result.skipped)["pmid:90000002"].startswith("record missing")
    added = [
        "    authors: [Fictionalsen A, Van Der Test B, Madeup C]",
        "    journal: Fictional Journal",
        "    doi: 10.9999/fictional.1",
    ]
    old, new = CARD_TEXT.split("\n"), result.text.split("\n")
    assert new == old[:7] + added + old[7:]  # nothing else moved, no comment lost
    data = yaml.safe_load(result.text)
    first = data["studies"][0]
    assert (first["authors"], first["journal"], first["doi"]) == (AUTHORS, JOURNAL, "10.9999/fictional.1")
    assert "authors" not in data["studies"][1] and "authors" not in data["studies"][2]


def test_fill_bibliography_twice_changes_nothing_the_second_time(root):
    reader = citations.CacheReader(root)
    once = citations.fill_bibliography(CARD_TEXT, reader)
    twice = citations.fill_bibliography(once.text, reader)
    assert twice.text == once.text and twice.filled == [] and twice.unchanged == ["pmid:90000001"]


def test_fill_bibliography_replaces_a_wrong_value_and_writes_null_for_a_record_without_doi(tmp_path):
    r = tmp_path / "c"
    add_bib_record(r, doi=None)
    wrong = CARD_TEXT.replace("    year: 2021\n", "    year: 2021\n    journal: Wrong\n    doi: 10.1/x\n")
    result = citations.fill_bibliography(wrong, citations.CacheReader(r))
    assert result.filled == ["pmid:90000001"]
    first = yaml.safe_load(result.text)["studies"][0]
    assert first["journal"] == JOURNAL and first["doi"] is None and "doi: null" in result.text
    assert result.text.count("journal:") == 1


def test_the_command_reports_without_write_and_writes_with_write(tmp_path, root, capsys):
    card = tmp_path / "cards" / "fictional-card.yaml"
    card.parent.mkdir()
    card.write_bytes(CARD_TEXT.encode())
    args = ["bibliography", str(card), "--cache-dir", str(root)]
    assert citations.main(args) == 0
    out = capsys.readouterr().out
    assert "would fill pmid:90000001" in out and "LEFT UNCHANGED pmid:90000002" in out
    assert "doi:10.1101/fictional" in out and "left unchanged" in out
    assert card.read_bytes() == CARD_TEXT.encode()  # nothing written
    assert citations.main([*args, "--write"]) == 0
    assert "authors:" in card.read_text(encoding="utf-8")
    assert b"\r" not in card.read_bytes()


# --- B4: a study the pipeline adds arrives filled -----


def test_a_study_added_by_an_operations_file_gets_the_fields_from_its_record(tmp_path):
    r = tmp_path / "cache"
    add_bib_record(r, PAPER.removeprefix("pmid:"))
    raw = {"card": "fictional-pipeline-card", "paper": PAPER, "operations": [{"op": "add_study", "study": NEW_STUDY}]}
    filled = parse_ops(copy.deepcopy(raw), cached_records(r))
    new = apply_operations(card_text(), filled, validate=False)
    study = next(s for s in yaml.safe_load(new)["studies"] if s["id"] == PAPER)
    assert (study["authors"], study["journal"], study["doi"]) == (AUTHORS, JOURNAL, "10.9999/fictional.1")
    assert "authors: [Fictionalsen A, Van Der Test B, Madeup C]" in new
    # Without a lookup, or with the record not cached, the study is added as before, without the fields.
    for lookup in (None, cached_records(tmp_path / "empty")):
        plain = apply_operations(card_text(), parse_ops(copy.deepcopy(raw), lookup), validate=False)
        added = next(s for s in yaml.safe_load(plain)["studies"] if s["id"] == PAPER)
        assert "authors" not in added and "journal" not in added and "doi" not in added
    assert ops(raw["operations"][0]).operations  # the plain parse is unchanged


# --- B8-B10: exports -----


def filled_study() -> cardlib.Study:
    return cardlib.Study.model_validate(bib_study())


def test_bibtex_an_article_for_a_filled_study_and_a_misc_for_an_unfilled_one():
    entries = read_bib(
        export.bibtex([filled_study(), cardlib.Study.model_validate(make_study("90000002"))], site.study_url)
    )
    (t1, k1, f1), (t2, k2, f2) = entries
    assert (t1, k1) == ("article", "pmid90000001") and (t2, k2) == ("misc", "pmid90000002")
    assert f1["author"] == "{Fictionalsen A} and {Van Der Test B} and {Madeup C}"
    assert f1["journal"] == JOURNAL and f1["doi"] == "10.9999/fictional.1" and f1["note"] == "PMID: 90000001"
    assert f1["year"] == "2021" and f1["url"] == "https://pubmed.ncbi.nlm.nih.gov/90000001/"
    assert "author" not in f2 and "journal" not in f2 and "doi" not in f2


def test_bibtex_without_a_doi_has_no_doi_line_and_names_and_journals_are_escaped():
    s = cardlib.Study.model_validate(make_study(authors=["O'Test & Co {x}"], journal="Fictional_Journal 50%", doi=None))
    ((typ, _, fields),) = read_bib(export.bibtex([s], site.study_url))
    assert typ == "article" and "doi" not in fields
    assert fields["author"] == r"{O'Test \& Co \{x\}}" and fields["journal"] == r"Fictional\_Journal 50\%"


def test_bibtex_with_authors_but_no_journal_stays_misc():
    s = cardlib.Study.model_validate(make_study(authors=["A B"]))
    assert read_bib(export.bibtex([s], site.study_url))[0][0] == "misc"


def test_ris_has_one_au_line_per_author_jo_and_do_and_is_unchanged_without_the_fields():
    text = export.ris([filled_study()], site.study_url)
    lines = text.split("\r\n")
    assert lines[:2] == ["TY  - JOUR", "AU  - Fictionalsen A"] and lines.count("AU  - Madeup C") == 1
    assert [x for x in lines if x.startswith("AU")] == [f"AU  - {a}" for a in AUTHORS]
    assert f"JO  - {JOURNAL}" in lines and "DO  - 10.9999/fictional.1" in lines and "AN  - PMID:90000001" in lines
    plain = export.ris([cardlib.Study.model_validate(make_study())], site.study_url).split("\r\n")
    assert not [x for x in plain if x.startswith(("AU", "JO", "DO"))]


def test_studies_csv_has_authors_journal_and_doi_columns_and_joins_authors_with_a_semicolon():
    assert export.STUDIES_COLUMNS[:6] == ("card", "id", "title", "year", "authors", "journal")
    assert export.STUDIES_COLUMNS[6] == "doi"
    assert export._cell(AUTHORS) == "Fictionalsen A; Van Der Test B; Madeup C"
    assert export._cell(None) == ""


def test_the_json_carries_the_fields_through_the_card_model():
    dumped = filled_study().model_dump(mode="json")
    assert dumped["authors"] == AUTHORS and dumped["journal"] == JOURNAL and dumped["doi"] == "10.9999/fictional.1"
    assert cardlib.Study.model_validate(make_study()).model_dump(mode="json")["authors"] is None


def test_readme_and_data_page_strings_no_longer_say_the_cards_hold_no_authors_or_journal():
    readme = export.readme(built="2027-01-02", draft_preview=False)
    assert "hold no authors" not in readme and "authors, title, journal" in readme
    for lang in ("en", "nb"):
        text = (REPO_ROOT / "content" / "i18n" / f"{lang}.yaml").read_text(encoding="utf-8")
        intro = yaml.safe_load(text)["data.cite.intro"]
        assert "forfattere, tittel, tidsskrift" in intro if lang == "nb" else "the authors, the title" in intro
        assert "hold no authors" not in intro and "ikke forfattere" not in intro


# --- B12: .zenodo.json and CITATION.cff -----


def test_zenodo_json_is_a_dataset_and_agrees_with_citation_cff():
    zenodo = json.loads((REPO_ROOT / ".zenodo.json").read_text(encoding="utf-8"))
    cff = yaml.safe_load((REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    assert zenodo["upload_type"] == "dataset"
    assert zenodo["title"] == cff["title"] == export.TITLE
    assert zenodo["license"].lower() == cff["license"].lower()
    assert [c["name"] for c in zenodo["creators"]] == [a["name"] for a in cff["authors"]]
    assert zenodo["description"] == cff["abstract"] and zenodo["keywords"] == cff["keywords"]


def test_the_agreement_test_would_notice_a_different_title():
    zenodo = json.loads((REPO_ROOT / ".zenodo.json").read_text(encoding="utf-8"))
    cff = yaml.safe_load((REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    zenodo["title"] += " (changed)"
    assert zenodo["title"] != cff["title"]
