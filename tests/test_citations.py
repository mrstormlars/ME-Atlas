"""Tests for the mechanical citation check.

Fictional PMIDs (9000000x), titles starting "Fictional" and fictional PMCIDs. The cache is built in tmp_path;
no network, no LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape

import httpx
import pytest
import yaml

from me_atlas import citations, europepmc, pubmed
from me_atlas.citations import normalise_quote, normalise_title, number_pattern

PMID = "90000001"
TITLE = "Fictional study of a made-up marker in a made-up cohort."
ABSTRACT = (
    "BACKGROUND: Fictional background text.\n"
    "METHODS: Forty-eight fictional patients, 48 in total, who met the Fukuda criteria – as published – "
    "were compared with 1,234 fictional controls."
)
QUOTE = "Forty-eight fictional patients, 48 in total, who met the Fukuda criteria"
FULLTEXT_ONLY_SENTENCE = "All fictional participants fulfilled the Canadian Consensus Criteria."
PMCID = "PMC9000001"


# --- building a fictional cache and fictional cards -------------------------


def add_record(
    root: Path,
    pmid: str = PMID,
    *,
    title: str | None = TITLE,
    year: int | None = 2021,
    abstract: str | None = ABSTRACT,
    retracted: bool = False,
    pmcid: str | None = None,
    authors: tuple[tuple[str, str], ...] = (),
    collective: tuple[str, ...] = (),
    errata: tuple[str, ...] = (),
) -> None:
    """Write a fictional PubMed record to <root>/pubmed/<pmid>.xml (with the article's PMC id if ``pmcid``)."""
    pub_date = f"<PubDate><Year>{year}</Year></PubDate>" if year is not None else "<PubDate></PubDate>"
    paragraphs = ""
    if abstract is not None:
        for part in abstract.split("\n"):
            label, _, body = part.partition(": ")
            paragraphs += f'<AbstractText Label="{label}">{escape(body)}</AbstractText>'
    types = "<PublicationType>Retracted Publication</PublicationType>" if retracted else ""
    xml = (
        f'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID Version="1">{pmid}</PMID><Article>'
        f"<Journal><JournalIssue>{pub_date}</JournalIssue><Title>Fictional Journal</Title></Journal>"
        f"<ArticleTitle>{escape(title or '')}</ArticleTitle>"
        f"<Abstract>{paragraphs}</Abstract>"
        f"<PublicationTypeList><PublicationType>Journal Article</PublicationType>{types}</PublicationTypeList>"
        "</Article>"
        + (
            "<CommentsCorrectionsList>"
            + "".join(
                f'<CommentsCorrections RefType="ErratumIn"><PMID Version="1">{e}</PMID></CommentsCorrections>'
                for e in errata
            )
            + "</CommentsCorrectionsList>"
            if errata
            else ""
        )
        + "</MedlineCitation>"
        + (
            f'<PubmedData><ArticleIdList><ArticleId IdType="pmc">{pmcid}</ArticleId></ArticleIdList></PubmedData>'
            if pmcid
            else ""
        )
        + "</PubmedArticle></PubmedArticleSet>"
    )
    if abstract is None:
        xml = xml.replace("<Abstract></Abstract>", "")
    if authors or collective:
        people = "".join(
            f"<Author><LastName>{escape(last)}</LastName><Initials>{escape(initials)}</Initials></Author>"
            for last, initials in authors
        ) + "".join(f"<Author><CollectiveName>{escape(name)}</CollectiveName></Author>" for name in collective)
        xml = xml.replace("<Abstract>", f"<AuthorList>{people}</AuthorList><Abstract>", 1)
        if abstract is None:
            xml = xml.replace("<PublicationTypeList>", f"<AuthorList>{people}</AuthorList><PublicationTypeList>", 1)
    folder = root / "pubmed"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{pmid}.xml").write_text(xml, encoding="utf-8")


def add_fulltext(
    root: Path,
    pmid: str = PMID,
    pmcid: str = PMCID,
    paragraphs: tuple[str, ...] = (FULLTEXT_ONLY_SENTENCE, "Fictional enrolment: 77 fictional patients."),
    *,
    open_access: bool = True,
) -> None:
    """Write a fictional Europe PMC lookup and (if open access) its full text."""
    folder = root / "europepmc"
    folder.mkdir(parents=True, exist_ok=True)
    hit = {"id": pmid, "source": "MED", "pmid": pmid, "pmcid": pmcid, "isOpenAccess": "Y" if open_access else "N"}
    (folder / f"{pmid}.json").write_text(json.dumps({"hitCount": 1, "resultList": {"result": [hit]}}), encoding="utf-8")
    if open_access:
        body = "".join(f"<p>{escape(p)}</p>" for p in paragraphs)
        (folder / f"{pmcid}.xml").write_text(
            "<article><front><article-meta><title-group><article-title>Fictional article"
            f"</article-title></title-group></article-meta></front><body><sec><title>Methods</title>{body}</sec>"
            "</body><back><ref-list><ref><mixed-citation>Fictional reference with 999 patients."
            "</mixed-citation></ref></ref-list></back></article>",
            encoding="utf-8",
        )


PAGE_PMCID = "PMC9000005"
PAGE_REFERENCE_SENTENCE = "Fictional reference cites the Holmes criteria."


def add_page(root: Path, pmid: str = PMID, pmcid: str = PAGE_PMCID, *, in_pmc: bool = True, body: str = "") -> None:
    """A fictional lookup (not open access) and a cached PMC article page for it."""
    folder = root / "europepmc"
    folder.mkdir(parents=True, exist_ok=True)
    hit = {"id": pmid, "source": "MED", "pmid": pmid, "pmcid": pmcid, "isOpenAccess": "N"}
    hit["inPMC"] = "Y" if in_pmc else "N"
    (folder / f"{pmid}.json").write_text(json.dumps({"hitCount": 1, "resultList": {"result": [hit]}}), encoding="utf-8")
    body = body or f"<p>{FULLTEXT_ONLY_SENTENCE} Fictional enrolment: 77 fictional patients.</p>"
    (folder / f"{pmcid}.html").write_text(
        f'<html><head><meta name="citation_pmid" content="{pmid}"></head><body><header>Fictional 4321</header>'
        f'<section class="body main-article-body"><section id="s1"><h2>Methods</h2>{body}</section>'
        f'<section class="ref-list"><p>{PAGE_REFERENCE_SENTENCE} Fictional cohort of 999 patients.</p></section>'
        "</section></body></html>",
        encoding="utf-8",
    )


def make_study(pmid: str = PMID, **over: object) -> dict:
    study: dict = {
        "id": f"pmid:{pmid}",
        "title": TITLE,
        "year": 2021,
        "cohort": "me_cfs",
        "case_definition": "Fukuda",
        "case_definition_source": "abstract",
        "case_definition_quote": QUOTE,
        "design": "controlled",
        "n_patients": 48,
        "n_controls": 1234,
        "measures_pem": False,
        "preregistered": None,
        "role": "context",
        "direction": "not_applicable",
        "finding": "A study of n=48 patients found a fictional result.",
    }
    study.update(over)
    return study


def write_card(directory: Path, studies: list[dict], slug: str = "fictional-card") -> Path:
    """Write a fictional draft that passes the card validator (level 0, every sentence sourced)."""
    directory.mkdir(parents=True, exist_ok=True)
    first = studies[0]["id"]
    sourced = {"text": "A fictional sentence.", "sources": [first]}
    card = {
        "slug": slug,
        "name": "Fictional card",
        "core_claim": sourced,
        "level": 0,
        "level_reason": {"text": "Fictional: nothing yet.", "sources": []},
        "contested": None,
        "badges": {
            "diagnostic_marker": {"value": False, "reason": None},
            "explains_pem": {"value": False, "reason": None},
        },
        "subgroups": [],
        "working_on_it": [],
        "early_signals": [],
        "studies": studies,
        "last_checked": {"date": "2026-11-01", "by": "ai_pair"},
    }
    path = directory / f"{slug}.yaml"
    path.write_text(yaml.safe_dump(card, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    root = tmp_path / "cache"
    add_record(root)
    return root


def run(tmp_path: Path, cache_root: Path, studies: list[dict], capsys) -> tuple[int, list[str]]:
    """Check one fictional card and return (exit code, printed lines)."""
    card = write_card(tmp_path / "drafts", studies)
    code = citations.main(["check", str(card), "--cache-dir", str(cache_root)])
    return code, capsys.readouterr().out.splitlines()


def issue_lines(lines: list[str], code: str) -> list[str]:
    return [line for line in lines if f": {code} " in line]


def check(tmp_path: Path, cache_root: Path, study: dict) -> list[citations.CitationIssue]:
    card = write_card(tmp_path / "drafts", [study])
    return citations.check_paths([card], cache_root)[1]


# --- a fully passing study --------------------------------------------------


def test_a_matching_study_has_no_issues(tmp_path, cache):
    assert check(tmp_path, cache, make_study()) == []


# --- C1 ----------------------------------------------------------------------


def test_c1_study_with_no_cached_record_is_an_error_naming_the_fetch_command(tmp_path, cache, capsys):
    code, lines = run(tmp_path, cache, [make_study("90000002", id="pmid:90000002")], capsys)
    c1 = issue_lines(lines, "C1")
    assert code == 1 and len(c1) == 1
    assert "ERROR" in c1[0] and "pmid:90000002" in c1[0] and "fictional-card.yaml" in c1[0]
    assert "pubmed fetch --ids 90000002" in c1[0]


def test_c1_unreadable_cached_record_is_an_error(tmp_path, cache):
    (cache / "pubmed" / f"{PMID}.xml").write_text("<PubmedArticleSet><oops", encoding="utf-8")
    issues = check(tmp_path, cache, make_study())
    assert [(i.code, i.level) for i in issues] == [("C1", "ERROR")]
    assert "unreadable" in issues[0].message and f"pubmed fetch --ids {PMID} --refresh" in issues[0].message


# --- C2 ----------------------------------------------------------------------


def test_c2_title_differing_by_one_word_is_an_error(tmp_path, cache, capsys):
    code, lines = run(
        tmp_path, cache, [make_study(title="Fictional study of a made-up biomarker in a made-up cohort.")], capsys
    )
    c2 = issue_lines(lines, "C2")
    assert code == 1 and len(c2) == 1 and "ERROR" in c2[0] and f"pmid:{PMID}" in c2[0]


@pytest.mark.parametrize(
    "title",
    [
        "FICTIONAL STUDY OF A MADE-UP MARKER IN A MADE-UP COHORT.",  # case
        "  Fictional   study of a made-up\nmarker in a made-up cohort.  ",  # whitespace
        "Fictional study of a made-up marker in a made-up cohort",  # trailing period missing on the card
        "[Fictional study of a made-up marker in a made-up cohort].",  # translation brackets
    ],
)
def test_c2_case_whitespace_trailing_period_and_brackets_do_not_matter(tmp_path, cache, title):
    assert [i for i in check(tmp_path, cache, make_study(title=title)) if i.code == "C2"] == []


def test_c2_brackets_on_the_record_side_are_removed_too(tmp_path, cache):
    add_record(cache, title="[Fictional Studie in English].")
    assert (
        check(
            tmp_path,
            cache,
            make_study(
                title="Fictional studie in English",
                n_patients=None,
                n_controls=None,
                case_definition_quote=None,
                case_definition="unverified",
                case_definition_source=None,
            ),
        )
        == []
    )


def test_c2_nothing_else_is_tolerated():
    base = "fictional study"
    assert normalise_title("Fictional study.") == base
    assert normalise_title("Fictional study..") != base  # only ONE trailing period
    assert normalise_title("Fictional, study") != base
    assert normalise_title("Fictional-study") != base
    assert normalise_title("Fictional study [sic]") != base  # inner brackets are kept
    # outer brackets are removed only when no other bracket is inside them
    assert normalise_title("[Fictional study]") == base
    assert normalise_title("[Fictional] and [study]") == "[fictional] and [study]"
    assert normalise_title("[Fictional [sic] study].") == "[fictional [sic] study]"


# --- C3 ----------------------------------------------------------------------


def test_c3_year_off_by_one_is_an_error(tmp_path, cache, capsys):
    code, lines = run(tmp_path, cache, [make_study(year=2022)], capsys)
    c3 = issue_lines(lines, "C3")
    assert code == 1 and len(c3) == 1 and "ERROR" in c3[0] and "2022" in c3[0] and "2021" in c3[0]


def test_c3_record_without_a_year_is_an_error(tmp_path, cache):
    add_record(cache, year=None)
    issues = [i for i in check(tmp_path, cache, make_study()) if i.code == "C3"]
    assert [(i.level, "no year" in i.message) for i in issues] == [("ERROR", True)]


# --- C4 ----------------------------------------------------------------------


def test_c4_retracted_record_is_an_error(tmp_path, cache, capsys):
    add_record(cache, retracted=True)
    code, lines = run(tmp_path, cache, [make_study()], capsys)
    c4 = issue_lines(lines, "C4")
    assert code == 1 and len(c4) == 1 and "ERROR" in c4[0] and f"pmid:{PMID}" in c4[0]


# --- C12 ---------------------------------------------------------------------

ERRATUM = "90000021"


def c12(tmp_path, cache, studies, capsys):
    code, lines = run(tmp_path, cache, studies, capsys)
    return code, issue_lines(lines, "C12")


def test_c12_an_erratum_that_is_not_a_study_on_the_card_is_a_warning(tmp_path, cache, capsys):
    add_record(cache, errata=(ERRATUM,))
    code, found = c12(tmp_path, cache, [make_study()], capsys)
    assert len(found) == 1 and "WARNING" in found[0] and f"pmid:{PMID}" in found[0] and f"pmid:{ERRATUM}" in found[0]
    assert code == 0  # a warning never fails the check


@pytest.mark.parametrize("corrects", [True, False])
def test_c12_an_erratum_that_is_a_study_on_the_card_gives_no_warning(tmp_path, cache, capsys, corrects):
    add_record(cache, errata=(ERRATUM,))
    add_record(cache, ERRATUM, title="Fictional erratum.")
    over: dict = {"id": f"pmid:{ERRATUM}", "title": "Fictional erratum.", "case_definition": "none"}
    over["case_definition_quote"] = None
    if corrects:
        over["corrects"] = f"pmid:{PMID}"
    _, found = c12(tmp_path, cache, [make_study(), make_study(ERRATUM, **over)], capsys)
    assert found == []


def test_c12_a_study_whose_record_lists_no_erratum_gives_no_warning(tmp_path, cache, capsys):
    _, found = c12(tmp_path, cache, [make_study()], capsys)
    assert found == []


# --- C5 ----------------------------------------------------------------------


def test_c5_quote_with_one_changed_word_is_an_error(tmp_path, cache, capsys):
    changed = QUOTE.replace("fictional", "imagined")
    code, lines = run(tmp_path, cache, [make_study(case_definition_quote=changed)], capsys)
    c5 = issue_lines(lines, "C5")
    assert code == 1 and len(c5) == 1 and "ERROR" in c5[0] and "abstract" in c5[0]


@pytest.mark.parametrize(
    "quote",
    [
        "Forty-eight   fictional\npatients, 48 in total,  who met the Fukuda criteria",  # whitespace
        "Forty‐eight fictional patients, 48 in total, who met the Fukuda criteria",  # hyphen U+2010
        "Forty–eight fictional patients, 48 in total, who met the Fukuda criteria",  # en dash
        "Forty—eight fictional patients, 48 in total, who met the Fukuda criteria",  # em dash
        "Forty−eight fictional patients, 48 in total, who met the Fukuda criteria",  # minus sign
        "who met the Fukuda criteria - as published -",  # ASCII hyphen for the abstract's en dashes
    ],
)
def test_c5_whitespace_and_dash_style_do_not_matter(tmp_path, cache, quote):
    assert [i for i in check(tmp_path, cache, make_study(case_definition_quote=quote)) if i.code == "C5"] == []


def test_c5_curly_and_straight_quotes_do_not_matter(tmp_path, cache):
    add_record(cache, abstract="METHODS: Patients met the “Fukuda” criteria and the clinician’s review.")
    quote = 'Patients met the "Fukuda" criteria and the clinician\'s review.'
    assert [i for i in check(tmp_path, cache, make_study(case_definition_quote=quote)) if i.code == "C5"] == []
    # and the other way round: straight in the record, curly on the card
    add_record(cache, abstract='METHODS: Patients met the "Fukuda" criteria and the clinician\'s review.')
    curly = "Patients met the “Fukuda” criteria and the clinician’s review."
    assert [i for i in check(tmp_path, cache, make_study(case_definition_quote=curly)) if i.code == "C5"] == []


def test_c5_nothing_else_is_tolerated():
    assert normalise_quote("Fukuda criteria") != normalise_quote("fukuda criteria")  # case matters
    assert normalise_quote("met criteria.") != normalise_quote("met criteria")  # punctuation matters
    assert normalise_quote("a b") == "a b"


def test_c5_quote_only_in_the_full_text_fails_when_the_source_is_the_abstract(tmp_path, cache):
    add_fulltext(cache)
    study = make_study(case_definition="CCC", case_definition_quote=FULLTEXT_ONLY_SENTENCE)
    issues = [i for i in check(tmp_path, cache, study) if i.code == "C5"]
    assert [i.level for i in issues] == ["ERROR"] and "abstract" in issues[0].message


def test_c5_the_same_quote_passes_when_the_source_is_the_full_text(tmp_path, cache):
    add_fulltext(cache)
    study = make_study(
        case_definition="CCC", case_definition_source="fulltext", case_definition_quote=FULLTEXT_ONLY_SENTENCE
    )
    assert [i for i in check(tmp_path, cache, study) if i.code == "C5"] == []


def test_c5_fulltext_source_with_one_changed_word_is_an_error(tmp_path, cache):
    add_fulltext(cache)
    study = make_study(
        case_definition="CCC",
        case_definition_source="fulltext",
        case_definition_quote=FULLTEXT_ONLY_SENTENCE.replace("fulfilled", "failed"),
    )
    issues = [i for i in check(tmp_path, cache, study) if i.code == "C5"]
    assert [i.level for i in issues] == ["ERROR"] and "full text" in issues[0].message


def test_c5_fulltext_source_with_no_cached_full_text_names_the_fetch_command(tmp_path, cache, capsys):
    study = make_study(case_definition_source="fulltext")
    code, lines = run(tmp_path, cache, [study], capsys)
    c5 = issue_lines(lines, "C5")
    assert code == 1 and len(c5) == 1 and "ERROR" in c5[0]
    assert f"europepmc fulltext {PMID}" in c5[0]


def test_c5_fulltext_source_when_europe_pmc_has_no_open_text_is_an_error(tmp_path, cache):
    add_fulltext(cache, open_access=False)
    issues = [i for i in check(tmp_path, cache, make_study(case_definition_source="fulltext")) if i.code == "C5"]
    assert [i.level for i in issues] == ["ERROR"] and "not open access" in issues[0].message


def test_c5_fulltext_source_with_unreadable_full_text_is_an_error(tmp_path, cache):
    add_fulltext(cache)
    (cache / "europepmc" / f"{PMCID}.xml").write_text("<article><oops", encoding="utf-8")
    issues = [i for i in check(tmp_path, cache, make_study(case_definition_source="fulltext")) if i.code == "C5"]
    assert [i.level for i in issues] == ["ERROR"] and "unreadable" in issues[0].message


def test_c5_abstract_source_with_no_abstract_is_an_error(tmp_path, cache):
    add_record(cache, abstract=None)
    issues = [i for i in check(tmp_path, cache, make_study()) if i.code == "C5"]
    assert [i.level for i in issues] == ["ERROR"] and "no abstract" in issues[0].message


@pytest.mark.parametrize("case_definition", ["unverified", "none", "other"])
def test_c5_studies_without_a_quote_skip_the_check(tmp_path, cache, case_definition):
    study = make_study(case_definition=case_definition, case_definition_source=None, case_definition_quote=None)
    assert [i for i in check(tmp_path, cache, study) if i.code == "C5"] == []


# --- C6 ----------------------------------------------------------------------


def test_c6_numbers_present_as_digits_give_no_warning(tmp_path, cache):
    assert [i for i in check(tmp_path, cache, make_study(n_patients=48, n_controls=1234)) if i.code == "C6"] == []


@pytest.mark.parametrize("form", ["1,234", "1 234", "1 234", "1234"])
def test_c6_thousands_forms_match_the_plain_number(tmp_path, cache, form):
    add_record(cache, abstract=f"RESULTS: There were {form} fictional controls.")
    study = make_study(
        n_patients=None,
        n_controls=1234,
        case_definition_quote=None,
        case_definition="unverified",
        case_definition_source=None,
        finding="A fictional result.",
    )
    assert check(tmp_path, cache, study) == []


def test_c6_missing_number_is_a_warning_and_the_exit_code_stays_zero(tmp_path, cache, capsys):
    code, lines = run(tmp_path, cache, [make_study(n_patients=51)], capsys)
    c6 = issue_lines(lines, "C6")
    assert code == 0 and len(c6) == 1 and "WARNING" in c6[0] and "n_patients 51" in c6[0]
    assert lines[-1].startswith("OK") and "0 error(s), 1 warning(s)" in lines[-1]


def test_c6_a_number_inside_a_longer_number_does_not_count(tmp_path, cache):
    add_record(cache, abstract="RESULTS: There were 148 fictional patients, 3.48 units and 1,048 visits and 48.5 days.")
    study = make_study(
        n_patients=48,
        n_controls=None,
        case_definition_quote=None,
        case_definition="unverified",
        case_definition_source=None,
    )
    issues = check(tmp_path, cache, study)
    assert [(i.code, i.level) for i in issues] == [("C6", "WARNING")]


def test_c6_the_cached_full_text_counts_but_the_reference_list_does_not(tmp_path, cache):
    add_fulltext(cache)  # the full text says 77 in the body and 999 only in its reference list
    study = make_study(n_patients=77, n_controls=999)
    c6 = [i for i in check(tmp_path, cache, study) if i.code == "C6"]
    assert [("n_controls 999" in i.message) for i in c6] == [True]


def test_c6_null_sizes_are_not_checked(tmp_path, cache):
    study = make_study(n_patients=None, n_controls=None)
    assert [i for i in check(tmp_path, cache, study) if i.code == "C6"] == []


def test_number_pattern_directly():
    assert number_pattern(48).search("n = 48.")
    assert number_pattern(48).search("48, 52 and 60")
    assert not number_pattern(48).search("148")
    assert not number_pattern(48).search("480")
    assert not number_pattern(48).search("p = .48")
    assert not number_pattern(48).search("0.48")
    assert number_pattern(48).search("a,48")  # a comma after a non-digit is not part of a number
    assert number_pattern(1234).search("1,234") and number_pattern(1234).search("1 234")
    assert not number_pattern(234).search("1,234")  # part of a longer number


# --- C7 ----------------------------------------------------------------------


def test_c7_doi_only_study_id_is_an_error(tmp_path, cache, capsys):
    doi_study = make_study(id="doi:10.9999/fictional.0001")
    code, lines = run(tmp_path, cache, [doi_study], capsys)
    c7 = issue_lines(lines, "C7")
    assert code == 1 and len(c7) == 1 and "ERROR" in c7[0] and "doi:10.9999/fictional.0001" in c7[0]
    assert "PMID" in c7[0]
    assert len(lines) == 2, "only C7 and the summary: no other check runs on a DOI-only id"


# --- the command line --------------------------------------------------------


def test_cli_passing_card_exits_zero(tmp_path, cache, capsys):
    code, lines = run(tmp_path, cache, [make_study()], capsys)
    assert code == 0
    assert lines == ["OK: 1 file(s) checked, 0 error(s), 0 warning(s)"]


def test_cli_reports_every_issue_of_every_file_in_one_run(tmp_path, cache, capsys):
    add_record(cache, "90000002", title="Fictional second study.", year=2020, retracted=True)
    first = write_card(
        tmp_path / "drafts",
        [
            make_study(year=2000, n_patients=51),  # C3 + C6
            make_study(
                "90000002",
                title="Fictional other title.",
                year=2020,
                case_definition_quote="Not in it.",
                n_patients=None,
                n_controls=None,
            ),  # C2 + C4 + C5
            make_study("90000003"),  # C1
        ],
        slug="fictional-one",
    )
    second = write_card(tmp_path / "drafts", [make_study(id="doi:10.9999/fictional.0002")], slug="fictional-two")
    code = citations.main(["check", str(first), str(second), "--cache-dir", str(cache)])
    lines = capsys.readouterr().out.splitlines()
    assert code == 1
    found = sorted(line.split(": ")[2].split(" ")[0] for line in lines[:-1])
    assert found == ["C1", "C2", "C3", "C4", "C5", "C6", "C7"]
    assert lines[-1] == "FAILED: 2 file(s) checked, 6 error(s), 1 warning(s)"
    for line in lines[:-1]:
        assert line.startswith(("drafts", str(tmp_path))) or "fictional-" in line  # file named on every line


def test_cli_checks_a_directory_and_skips_the_change_log(tmp_path, cache, capsys):
    write_card(tmp_path / "drafts", [make_study()])
    (tmp_path / "drafts" / "changelog.yaml").write_text("- not: a card\n", encoding="utf-8")
    assert citations.main(["check", str(tmp_path / "drafts"), "--cache-dir", str(cache)]) == 0
    assert capsys.readouterr().out.strip() == "OK: 1 file(s) checked, 0 error(s), 0 warning(s)"


def test_cli_default_paths_are_cards_and_drafts(tmp_path, cache, capsys, monkeypatch):
    write_card(tmp_path / "cards", [make_study()], slug="fictional-a")
    write_card(tmp_path / "drafts", [make_study(year=1999)], slug="fictional-b")
    monkeypatch.chdir(tmp_path)
    assert citations.main(["check", "--cache-dir", str(cache)]) == 1
    out = capsys.readouterr().out
    assert "fictional-b.yaml" in out and "2 file(s) checked" in out


def test_cli_a_card_that_does_not_load_is_an_error_not_a_crash(tmp_path, cache, capsys):
    broken = tmp_path / "drafts" / "fictional-broken.yaml"
    broken.parent.mkdir()
    broken.write_text("slug: fictional-broken\nname: [unclosed\n", encoding="utf-8")
    invalid = tmp_path / "drafts" / "fictional-invalid.yaml"
    invalid.write_text("slug: fictional-invalid\n", encoding="utf-8")
    good = write_card(tmp_path / "drafts", [make_study(year=1999)], slug="fictional-good")
    code = citations.main(
        ["check", str(broken), str(invalid), str(good), str(tmp_path / "nope.yaml"), "--cache-dir", str(cache)]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert out.count("LOAD ERROR") >= 3
    assert "fictional-broken.yaml" in out and "fictional-invalid.yaml" in out and "nope.yaml" in out
    assert "C3 ERROR" in out, "the loadable card is still checked in the same run"


def test_cli_cache_dir_defaults_to_data_cache():
    assert Path("data/cache") == citations.DEFAULT_CACHE_ROOT


# --- offline -----------------------------------------------------------------


def test_the_check_never_builds_an_http_client_or_makes_a_request(tmp_path, cache, capsys, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("the citation check must not touch the network")

    monkeypatch.setattr(httpx.Client, "__init__", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)
    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr(pubmed.PubMedClient, "__init__", boom)
    monkeypatch.setattr(europepmc.EuropePmcClient, "__init__", boom)

    add_fulltext(cache)
    studies = [
        make_study(),  # all checks, nothing to fetch
        make_study("90000002", id="pmid:90000002"),  # missing record: reported, not fetched
        make_study(case_definition_source="fulltext", case_definition_quote=FULLTEXT_ONLY_SENTENCE, id=f"pmid:{PMID}"),
    ]
    studies[2]["id"] = "pmid:90000003"  # a different id: no lookup cached, full text is not fetched
    code, lines = run(tmp_path, cache, studies, capsys)
    assert code == 1
    assert issue_lines(lines, "C1")


# --- plain text of a full-text article -----------------------------------------


def test_article_text_joins_blocks_with_a_space_but_not_inline_markup():
    xml = (
        "<article><front><article-title>Fictional title</article-title></front><body>"
        "<p>CO<sub>2</sub> was <italic>not</italic> measured.</p><p>Second paragraph.</p>"
        "<p>Cited<xref>1</xref>.</p></body><back><ref-list><ref>Fictional 12345</ref></ref-list></back></article>"
    )
    assert europepmc.article_text(xml) == ("Fictional title CO2 was not measured. Second paragraph. Cited1.")


# --- the cached PMC article page as full text -------------------------------


def test_c5_passes_on_a_quote_in_the_body_of_a_cached_pmc_page(tmp_path, cache):
    add_page(cache)
    study = make_study(case_definition_source="fulltext", case_definition_quote=FULLTEXT_ONLY_SENTENCE)
    assert [i for i in check(tmp_path, cache, study) if i.code == "C5"] == []


def test_c5_fails_on_a_quote_that_is_only_in_the_reference_list_of_the_page(tmp_path, cache):
    add_page(cache)
    study = make_study(case_definition_source="fulltext", case_definition_quote=PAGE_REFERENCE_SENTENCE)
    c5 = [i for i in check(tmp_path, cache, study) if i.code == "C5"]
    assert [i.level for i in c5] == ["ERROR"] and "not verbatim in the cached full text" in c5[0].message


def test_c6_finds_a_number_in_the_page_but_not_one_in_its_reference_list(tmp_path, cache):
    add_page(cache)
    study = make_study(n_patients=77, n_controls=999)
    c6 = [i for i in check(tmp_path, cache, study) if i.code == "C6"]
    assert [("n_controls 999" in i.message) for i in c6] == [True]


def test_the_open_access_xml_is_preferred_over_a_cached_page(tmp_path, cache):
    add_page(cache)
    (cache / "europepmc" / f"{PAGE_PMCID}.xml").write_text(
        "<article><body><p>Fictional xml text only.</p></body></article>", encoding="utf-8"
    )
    study = make_study(case_definition_source="fulltext", case_definition_quote=FULLTEXT_ONLY_SENTENCE)
    c5 = [i for i in check(tmp_path, cache, study) if i.code == "C5"]
    assert [i.level for i in c5] == ["ERROR"]  # the quote is only in the page, which is not read


def test_c5_without_a_cached_page_names_pmcpage_when_the_record_is_in_pmc(tmp_path, cache):
    add_page(cache)
    (cache / "europepmc" / f"{PAGE_PMCID}.html").unlink()
    c5 = [i for i in check(tmp_path, cache, make_study(case_definition_source="fulltext")) if i.code == "C5"]
    assert [i.level for i in c5] == ["ERROR"]
    assert "europepmc pmcpage --card" in c5[0].message and "not open access" in c5[0].message


def test_c5_without_a_cached_page_does_not_name_pmcpage_when_the_record_is_not_in_pmc(tmp_path, cache):
    add_page(cache, in_pmc=False)
    (cache / "europepmc" / f"{PAGE_PMCID}.html").unlink()
    c5 = [i for i in check(tmp_path, cache, make_study(case_definition_source="fulltext")) if i.code == "C5"]
    assert [i.level for i in c5] == ["ERROR"] and "pmcpage" not in c5[0].message


def test_c5_with_an_unreadable_cached_page_is_an_error_naming_pmcpage_refresh(tmp_path, cache):
    add_page(cache)
    (cache / "europepmc" / f"{PAGE_PMCID}.html").write_text("<html>no article</html>", encoding="utf-8")
    c5 = [i for i in check(tmp_path, cache, make_study(case_definition_source="fulltext")) if i.code == "C5"]
    assert [i.level for i in c5] == ["ERROR"]
    assert "unreadable" in c5[0].message and "pmcpage" in c5[0].message and "--refresh" in c5[0].message


# --- a placeholder is not full text (B5), and the PMC id from PubMed (B6) --------

PLACEHOLDER_PARAGRAPHS = ("Full text is available as a PDF.", "Fictional enrolment: 77 fictional patients.")


def test_c5_a_placeholder_xml_is_not_full_text(tmp_path, cache):
    add_fulltext(cache, paragraphs=PLACEHOLDER_PARAGRAPHS)
    study = make_study(case_definition_source="fulltext", case_definition_quote=PLACEHOLDER_PARAGRAPHS[0])
    c5 = [i for i in check(tmp_path, cache, study) if i.code == "C5"]
    assert [i.level for i in c5] == ["ERROR"]
    assert "no cached full text" in c5[0].message and "PDF" in c5[0].message


def test_the_reader_reports_no_cached_full_text_for_a_placeholder(cache):
    add_fulltext(cache, paragraphs=PLACEHOLDER_PARAGRAPHS)
    result = citations.CacheReader(cache).fulltext(PMID)
    assert isinstance(result, tuple) and "PDF" in result[0]


def test_c6_sees_the_abstract_only_when_the_xml_is_a_placeholder(tmp_path, cache):
    add_fulltext(cache, paragraphs=PLACEHOLDER_PARAGRAPHS)
    c6 = [i for i in check(tmp_path, cache, make_study(n_patients=77)) if i.code == "C6"]
    assert [("n_patients 77" in i.message) for i in c6] == [True]


def add_lookup_without_pmcid(root: Path) -> None:
    hit = {"id": PMID, "source": "MED", "pmid": PMID, "isOpenAccess": "N", "inPMC": "N"}
    (root / "europepmc").mkdir(parents=True, exist_ok=True)
    (root / "europepmc" / f"{PMID}.json").write_text(
        json.dumps({"hitCount": 1, "resultList": {"result": [hit]}}), encoding="utf-8"
    )


def test_a_cached_xml_is_found_through_the_pubmed_records_pmc_id_when_the_lookup_has_none(tmp_path, cache):
    add_record(cache, pmcid=PMCID)
    add_lookup_without_pmcid(cache)
    (cache / "europepmc" / f"{PMCID}.xml").write_text(
        f"<article><body><sec><title>Methods</title><p>{FULLTEXT_ONLY_SENTENCE}</p></sec></body></article>",
        encoding="utf-8",
    )
    study = make_study(case_definition_source="fulltext", case_definition_quote=FULLTEXT_ONLY_SENTENCE)
    assert [i for i in check(tmp_path, cache, study) if i.code == "C5"] == []


def test_without_a_pmc_id_in_either_place_the_lookup_without_pmcid_gives_no_full_text(tmp_path, cache):
    add_lookup_without_pmcid(cache)
    (cache / "europepmc" / f"{PMCID}.xml").write_text(
        f"<article><body><p>{FULLTEXT_ONLY_SENTENCE}</p></body></article>", encoding="utf-8"
    )
    study = make_study(case_definition_source="fulltext", case_definition_quote=FULLTEXT_ONLY_SENTENCE)
    c5 = [i for i in check(tmp_path, cache, study) if i.code == "C5"]
    assert [i.level for i in c5] == ["ERROR"]


def test_the_pubmed_pmc_id_with_no_cached_xml_names_the_fetch_command(tmp_path, cache):
    add_record(cache, pmcid=PMCID)
    add_lookup_without_pmcid(cache)
    c5 = [i for i in check(tmp_path, cache, make_study(case_definition_source="fulltext")) if i.code == "C5"]
    assert [i.level for i in c5] == ["ERROR"]
    assert PMCID in c5[0].message and f"europepmc fulltext {PMID}" in c5[0].message


# --- preprints: a doi: study with preprint: true, and C8 ----------------------


def check_pp(tmp_path: Path, cache_root: Path, study: dict) -> list[citations.CitationIssue]:
    """Check ``study`` on a card that also has an ordinary study to carry the core claim (V15: a preprint cannot);
    return only the issues of ``study``."""
    add_record(cache_root, "90000050")
    card = write_card(tmp_path / "drafts", [make_study("90000050"), study])
    return [i for i in citations.check_paths([card], cache_root)[1] if i.study == study["id"]]


PREPRINT_FIXTURES = Path(__file__).parent / "fixtures" / "europepmc"
PREPRINT_DOI = "10.99999/fictional.2026.001"
PREPRINT_PMCID = "PMC9000010"
PREPRINT_QUOTE = "Patients met the 1994 Fukuda criteria."
PREPRINT_TITLE = "A fictional preprint of widget signalling in a made-up ME/CFS cohort"


def add_preprint(
    root: Path, index: int = 0, *, abstract: str | None = None, authors: tuple[tuple[str, str], ...] = ()
) -> None:
    """Cache one fictional Europe PMC preprint record (from the recorded-shape fixture) as the search would."""
    page = json.loads((PREPRINT_FIXTURES / "preprint_page1.json").read_text(encoding="utf-8"))
    result = page["resultList"]["result"][index]
    if abstract is not None:
        result["abstractText"] = abstract
    if authors:
        result["authorList"] = {"author": [{"lastName": last, "initials": ini} for last, ini in authors]}
    folder = root / "europepmc" / "preprints"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{result['id']}.json").write_text(json.dumps(result), encoding="utf-8")


def preprint_study(**over: object) -> dict:
    fields: dict = {
        "id": f"doi:{PREPRINT_DOI}",
        "title": PREPRINT_TITLE,
        "year": 2026,
        "case_definition_quote": PREPRINT_QUOTE,
        "n_patients": 40,
        "n_controls": 35,
        "role": "early_signal",
        "preprint": True,
    }
    return make_study(**{**fields, **over})


def test_a_correctly_cited_preprint_passes_against_the_cached_europe_pmc_record(tmp_path, cache):
    add_preprint(cache)
    assert check_pp(tmp_path, cache, preprint_study()) == []


def test_a_preprint_with_a_wrong_title_fails_c2(tmp_path, cache):
    add_preprint(cache)
    issues = check_pp(tmp_path, cache, preprint_study(title="A fictional preprint of something else entirely"))
    assert [i.code for i in issues] == ["C2"]
    assert "Europe PMC preprint record" in issues[0].message


def test_a_preprint_with_a_wrong_year_fails_c3(tmp_path, cache):
    add_preprint(cache)
    issues = check_pp(tmp_path, cache, preprint_study(year=2025))
    assert [(i.code, i.level) for i in issues] == [("C3", "ERROR")]


def test_a_preprint_with_a_wrong_doi_fails_c1_and_names_the_command_to_fetch_it(tmp_path, cache):
    add_preprint(cache)
    wrong = "10.99999/fictional.2026.999"
    issues = check_pp(tmp_path, cache, preprint_study(id=f"doi:{wrong}"))
    assert [i.code for i in issues] == ["C1"]
    assert f"europepmc preprint {wrong}" in issues[0].message


def test_the_doi_of_a_preprint_is_compared_case_insensitively(tmp_path, cache):
    add_preprint(cache)
    assert check_pp(tmp_path, cache, preprint_study(id=f"doi:{PREPRINT_DOI.upper()}")) == []


def test_a_preprint_case_definition_quote_must_be_verbatim_in_the_record_abstract_c5(tmp_path, cache):
    add_preprint(cache)
    issues = check_pp(tmp_path, cache, preprint_study(case_definition_quote="Patients met the 1988 Holmes criteria."))
    assert [i.code for i in issues] == ["C5"]


def test_a_preprint_quote_from_the_full_text_is_read_through_the_shared_pmcid_xml_cache(tmp_path, cache):
    add_preprint(cache)
    sentence = "Fictional participants fulfilled the Oxford criteria."
    folder = cache / "europepmc"
    (folder / f"{PREPRINT_PMCID}.xml").write_text(
        f"<article><body><sec><title>Methods</title><p>{sentence}</p></sec></body></article>", encoding="utf-8"
    )
    study = preprint_study(case_definition="Oxford", case_definition_source="fulltext", case_definition_quote=sentence)
    assert check_pp(tmp_path, cache, study) == []
    wrong = preprint_study(case_definition_source="fulltext", case_definition_quote="Never in the text.")
    assert [i.code for i in check_pp(tmp_path, cache, wrong)] == ["C5"]


def test_a_preprint_full_text_quote_with_no_cached_text_names_the_fetch_command(tmp_path, cache):
    add_preprint(cache)
    issues = check_pp(tmp_path, cache, preprint_study(case_definition_source="fulltext"))
    assert [i.code for i in issues] == ["C5"]
    assert f"europepmc preprint {PREPRINT_DOI} --fulltext" in issues[0].message


def test_a_preprint_sample_size_missing_from_the_abstract_is_a_c6_warning(tmp_path, cache):
    add_preprint(cache)
    issues = check_pp(tmp_path, cache, preprint_study(n_patients=41))
    assert [(i.code, i.level) for i in issues] == [("C6", "WARNING")]


def test_a_doi_study_that_is_not_a_preprint_still_gets_c7_even_when_a_preprint_record_is_cached(tmp_path, cache):
    add_preprint(cache)
    issues = check_pp(tmp_path, cache, preprint_study(preprint=False))
    assert [i.code for i in issues] == ["C7"]


def mark_pubmed_record_as_preprint(root: Path, pmid: str = PMID) -> None:
    path = root / "pubmed" / f"{pmid}.xml"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            "<PublicationType>Journal Article</PublicationType>",
            "<PublicationType>Journal Article</PublicationType><PublicationType>Preprint</PublicationType>",
        ),
        encoding="utf-8",
    )


def test_c8_a_pubmed_preprint_cited_without_preprint_true_is_an_error(tmp_path, cache):
    mark_pubmed_record_as_preprint(cache)
    issues = check_pp(tmp_path, cache, make_study())
    assert [(i.code, i.level) for i in issues] == [("C8", "ERROR")]
    assert "lacks preprint: true" in issues[0].message


def test_c8_preprint_true_on_a_study_whose_pubmed_record_is_not_a_preprint_is_an_error(tmp_path, cache):
    issues = check_pp(tmp_path, cache, make_study(role="early_signal", preprint=True))
    assert [(i.code, i.level) for i in issues] == [("C8", "ERROR")]
    assert "does not have publication type" in issues[0].message


def test_c8_a_pubmed_preprint_marked_preprint_true_passes(tmp_path, cache):
    mark_pubmed_record_as_preprint(cache)
    assert check_pp(tmp_path, cache, make_study(role="early_signal", preprint=True)) == []


def test_two_cached_preprint_records_with_one_doi_are_reported_as_c1_naming_both(tmp_path, cache):
    add_preprint(cache)
    folder = cache / "europepmc" / "preprints"
    first = json.loads((folder / "PPR9000001.json").read_text(encoding="utf-8"))
    (folder / "PPR9000099.json").write_text(json.dumps({**first, "id": "PPR9000099"}), encoding="utf-8")
    issues = check_pp(tmp_path, cache, preprint_study())
    assert [i.code for i in issues] == ["C1"]
    assert "PPR9000001 and PPR9000099" in issues[0].message


# --- C9: the group names an author of the record ------------------------------

SMITH_JONES = (("Smith", "AB"), ("Jones", "C"))


def c9(issues: list[citations.CitationIssue]) -> list[citations.CitationIssue]:
    return [i for i in issues if i.code == "C9"]


def test_c9_a_group_naming_no_author_of_the_record_is_a_warning(tmp_path):
    root = tmp_path / "cache"
    add_record(root, authors=SMITH_JONES)
    found = c9(check(tmp_path, root, make_study(group="Ponting CP, Oxford")))
    assert [(i.level, i.study) for i in found] == [(citations.WARNING, f"pmid:{PMID}")]
    assert "Smith AB" in found[0].message and "Jones C" in found[0].message


def test_c9_a_group_naming_an_author_plus_a_cross_reference_is_supported(tmp_path):
    root = tmp_path / "cache"
    add_record(root, authors=SMITH_JONES)
    assert c9(check(tmp_path, root, make_study(group="Jones C, Leeds (same group as Ponting CP, 123)"))) == []


@pytest.mark.parametrize(
    "group", ["Smith A, Leeds", "Smith AB", "smith AB", "Leeds (Smith A.B.)", "Smith A B, Leeds", "Smith, A"]
)
def test_c9_the_first_initial_is_enough_and_case_does_not_matter(tmp_path, group):
    root = tmp_path / "cache"
    add_record(root, authors=SMITH_JONES)
    assert c9(check(tmp_path, root, make_study(group=group))) == []


def test_c9_accents_are_ignored_in_both_directions(tmp_path):
    root = tmp_path / "cache"
    add_record(root, authors=(("Gomez-Esteban", "JC"),))
    assert c9(check(tmp_path, root, make_study(group="Gómez-Esteban JC, Bilbao"))) == []
    add_record(root, authors=(("Gómez-Esteban", "JC"),))
    assert c9(check(tmp_path, root, make_study(group="Gomez-Esteban J, Bilbao"))) == []


def test_c9_a_last_name_alone_or_inside_a_longer_word_is_not_a_match(tmp_path):
    root = tmp_path / "cache"
    add_record(root, authors=SMITH_JONES)
    assert len(c9(check(tmp_path, root, make_study(group="Smithson AB, Leeds")))) == 1
    assert len(c9(check(tmp_path, root, make_study(group="Smith, Leeds")))) == 1
    assert len(c9(check(tmp_path, root, make_study(group="Smith Z, Leeds")))) == 1


@pytest.mark.parametrize("group", ["Smith Anna, Leeds", "Smith Ab, Leeds", "Smith Alice B, Leeds"])
def test_c9_lowercase_letters_after_the_first_initial_are_not_initials(tmp_path, group):
    root = tmp_path / "cache"
    add_record(root, authors=(("Smith", "AB"), ("Ponting", "C")))
    assert len(c9(check(tmp_path, root, make_study(group=group)))) == 1
    assert len(c9(check(tmp_path, root, make_study(group="Ponting Cox, Oxford")))) == 1


def test_c9_a_collective_author_needs_its_full_name_not_a_prefix_or_the_initials_shape(tmp_path):
    root = tmp_path / "cache"
    add_record(root, authors=(), collective=("Long COVID Consortium",))
    assert len(c9(check(tmp_path, root, make_study(group="Long Covid Cons, Leeds")))) == 1
    assert c9(check(tmp_path, root, make_study(group="the long covid consortium, Leeds"))) == []


def test_c9_a_collective_author_is_matched_by_its_full_name(tmp_path):
    root = tmp_path / "cache"
    add_record(root, authors=(), collective=("Fictional Long COVID Consortium",))
    assert c9(check(tmp_path, root, make_study(group="the Fictional Long COVID Consortium"))) == []
    assert len(c9(check(tmp_path, root, make_study(group="Ponting CP")))) == 1


def test_c9_a_record_without_authors_gives_no_issue(tmp_path):
    root = tmp_path / "cache"
    add_record(root)
    assert c9(check(tmp_path, root, make_study(group="Ponting CP, Oxford"))) == []


def test_c9_a_study_without_a_group_is_not_checked(tmp_path):
    root = tmp_path / "cache"
    add_record(root, authors=SMITH_JONES)
    assert c9(check(tmp_path, root, make_study())) == []


def test_c9_does_not_make_the_check_fail(tmp_path, capsys):
    root = tmp_path / "cache"
    add_record(root, authors=SMITH_JONES)
    code, lines = run(tmp_path, root, [make_study(group="Ponting CP")], capsys)
    assert code == 0 and len(issue_lines(lines, "C9")) == 1 and lines[-1].startswith("OK:")


def test_c9_applies_to_a_cached_preprint_record(tmp_path):
    root = tmp_path / "cache"
    add_preprint(root, authors=SMITH_JONES)
    assert len(c9(check_pp(tmp_path, root, preprint_study(group="Ponting CP, Oxford")))) == 1
    assert c9(check_pp(tmp_path, root, preprint_study(group="Jones C, Leeds"))) == []
