"""Tests for C10, the number check on free text (docs/citation-check.md, "Numbers in free text").

Fictional records and cards in tmp_path; no network, no LLM.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from test_citations import PMID, add_fulltext, add_record, make_study, write_card

from me_atlas import citations
from me_atlas.citations import (
    ERROR,
    WARNING,
    canonical_number,
    free_text_numerals,
    source_number_tokens,
)

OTHER = "90000002"
ABSTRACT = (
    "BACKGROUND: Fictional background.\n"
    "RESULTS: Of 1,234 fictional patients aged 18-65, 26 percent had a lower score (p=0.03, 95% CI -0.8 to 2.5). "
    "Twelve fictional controls were also seen."
)


def numerals(text: str) -> list[str]:
    return free_text_numerals(text)[0]


# --- normalisation ------------------------------------------------------------------------------------------


def test_thousands_separators_read_the_same():
    assert canonical_number("9,392") == canonical_number("9392") == "9392"
    assert "9392" in source_number_tokens("In all 9,392 people and 9 392 more.")
    assert "9392" in source_number_tokens("9 392 people")
    assert numerals("a cohort of 9,392 people") == ["9392"]


def test_decimals_with_and_without_the_leading_zero_read_the_same():
    assert canonical_number(".05") == canonical_number("0.05") == "0.05"
    assert numerals("p=.05") == ["0.05"] and numerals("p=0.05") == ["0.05"]
    assert canonical_number("0.50") != canonical_number("0.5")  # trailing zeros are kept


def test_a_leading_comparison_sign_is_ignored():
    assert numerals("p<0.05, p≤0.01, n>40, n=40") == ["0.05", "0.01", "40"]


def test_percentages_match_with_a_sign_a_space_or_a_word():
    assert numerals("26%") == numerals("26 %") == ["26"]
    for source in ("26%", "26 %", "26 percent"):
        assert "26" in source_number_tokens(f"found in {source} of patients")


def test_ranges_and_pairs_are_checked_at_each_end():
    for text in ("18-65", "18–65", "18 to 65", "18 and 65"):
        assert numerals(f"aged {text}") == ["18", "65"]


def test_minus_signs_are_ignored_and_only_the_size_is_checked():
    assert numerals("a change of −0.8 and -2.5") == ["0.8", "2.5"]
    assert "0.8" in source_number_tokens("a change of -0.8")


@pytest.mark.parametrize(
    "text",
    [
        "see pmid:12345678 and doi:10.1234/abc.5678",
        "the paper PMC1234567 and PPR9876",
        "Smith et al. (2019) found nothing",
        "Fukuda 1994 and the 2015 IOM criteria",
        "ICD code G93.3 and U09.9",
        "the COMPASS-31 score, IL-6, CD4 and SF-36 and COVID-19",
        "3-hydroxykynurenine and 5-HT",
        "level 3 and rungs 2 and 3 of the ladder",
        "the 3rd and 21st",
    ],
)
def test_names_ids_citation_years_rubric_numbers_and_ordinals_are_skipped(text):
    assert numerals(text) == []


def test_a_year_in_prose_and_a_plain_quantity_are_checked():
    assert numerals("in 2019, 40 patients and 6 months") == ["2019", "40", "6"]


def test_word_numbers_in_the_card_are_not_checked_but_the_source_counts_both_forms():
    assert numerals("two studies and twelve patients and half of them") == []
    assert "12" in source_number_tokens("Twelve fictional controls")
    assert "20" in source_number_tokens("twenty participants")


# --- derivations --------------------------------------------------------------------------------------------


def test_a_derivation_that_holds_vouches_for_the_result_and_checks_the_operands():
    assert free_text_numerals("78 (= 40 + 38) patients in all") == (["40", "38"], [])
    assert free_text_numerals("a gain of 12 (= 50 - 38)") == (["50", "38"], [])
    assert free_text_numerals("1,234 (= 1,000 + 234)")[1] == []


def test_a_derivation_that_does_not_hold_is_reported():
    _, problems = free_text_numerals("79 (= 40 + 38) patients in all")
    assert len(problems) == 1 and "79" in problems[0] and "78" in problems[0]


def test_a_derivation_that_is_not_a_sum_or_difference_is_reported():
    _, problems = free_text_numerals("2 (= 40 / 20)")
    assert len(problems) == 1 and "not a sum or difference" in problems[0]


def test_a_derived_number_without_a_marker_is_an_ordinary_numeral():
    assert numerals("78 patients in all") == ["78"]


# --- the check against cited sources ------------------------------------------------------------------------


def plain(pmid: str = PMID, **over: object) -> dict:
    """A study with no quote, no sample size and a finding without numbers: nothing else to check."""
    fields = dict(
        case_definition="unverified",
        case_definition_source=None,
        case_definition_quote=None,
        n_patients=None,
        n_controls=None,
        finding="A fictional result.",
    )
    return make_study(pmid, **{**fields, **over})


def card_path(tmp_path: Path, studies: list[dict], *, claim: str, sources: list[str], finding: str | None = None):
    path = write_card(tmp_path / "drafts", studies)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["core_claim"] = {"text": claim, "sources": sources}
    if finding is not None:
        data["studies"][0]["finding"] = finding
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    root = tmp_path / "cache"
    add_record(root, PMID, abstract=ABSTRACT)
    add_record(root, OTHER, title="Fictional second study.", abstract="RESULTS: A fictional 777 patients were seen.")
    return root


def c10(tmp_path: Path, cache: Path, *, level: str = WARNING, **kwargs):
    path = card_path(tmp_path, kwargs.pop("studies", [plain()]), **kwargs)
    _, issues = citations.check_paths([path], cache, level)
    return [i for i in issues if i.code == "C10"]


def test_numbers_found_in_the_cited_abstract_pass(tmp_path, cache):
    claim = "Of 1,234 patients aged 18-65, 26% scored lower (p<0.03; 12 controls)."
    assert c10(tmp_path, cache, claim=claim, sources=[f"pmid:{PMID}"], finding="A study found 26% lower scores.") == []


def test_a_number_only_in_an_uncited_source_fails(tmp_path, cache):
    studies = [
        plain(),
        plain(OTHER, id=f"pmid:{OTHER}", title="Fictional second study."),
    ]
    found = c10(tmp_path, cache, studies=studies, claim="A fictional 777 patients were seen.", sources=[f"pmid:{PMID}"])
    assert [i.code for i in found] == ["C10"] and "777" in found[0].message and f"pmid:{PMID}" in found[0].message
    assert (
        c10(tmp_path, cache, studies=studies, claim="A fictional 777 patients were seen.", sources=[f"pmid:{OTHER}"])
        == []
    )


def test_a_structured_field_of_a_cited_study_counts(tmp_path, cache):
    study = plain(n_patients=555, n_controls=444, year=2021)
    claim = "A study of 555 patients and 444 controls, published in 2021."
    assert c10(tmp_path, cache, studies=[study], claim=claim, sources=[f"pmid:{PMID}"]) == []
    assert (
        len(
            c10(
                tmp_path,
                cache,
                studies=[plain()],
                claim=claim,
                sources=[f"pmid:{PMID}"],
            )
        )
        == 2
    )


def test_a_study_finding_cites_its_own_study(tmp_path, cache):
    found = c10(
        tmp_path, cache, claim="A fictional sentence.", sources=[f"pmid:{PMID}"], finding="A study of 9999 people."
    )
    assert [i.study for i in found] == [f"studies[pmid:{PMID}].finding"] and "9999" in found[0].message


def test_the_full_text_counts_as_the_source(tmp_path, cache):
    claim = "Fictional enrolment: 77 fictional patients."
    assert len(c10(tmp_path, cache, claim=claim, sources=[f"pmid:{PMID}"])) == 1
    add_fulltext(cache, PMID)
    assert c10(tmp_path, cache, claim=claim, sources=[f"pmid:{PMID}"]) == []


def test_a_word_in_the_source_matches_the_digits_in_the_card(tmp_path, cache):
    assert c10(tmp_path, cache, claim="12 controls were seen.", sources=[f"pmid:{PMID}"]) == []


def test_the_level_is_a_warning_by_default_and_an_error_where_asked(tmp_path, cache):
    claim = "A fictional 31337 patients."
    assert [i.level for i in c10(tmp_path, cache, claim=claim, sources=[f"pmid:{PMID}"])] == [WARNING]
    assert [i.level for i in c10(tmp_path, cache, level=ERROR, claim=claim, sources=[f"pmid:{PMID}"])] == [ERROR]


def test_a_failing_number_in_a_card_does_not_fail_the_command_line_check(tmp_path, cache, capsys):
    path = card_path(tmp_path, [plain()], claim="31337 fictional.", sources=[f"pmid:{PMID}"])
    assert citations.main(["check", str(path), "--cache-dir", str(cache)]) == 0
    assert "C10 WARNING" in capsys.readouterr().out


def test_the_issue_does_not_depend_on_the_index_of_the_paragraph(tmp_path, cache):
    path = card_path(
        tmp_path,
        [plain()],
        claim="A fictional sentence.",
        sources=[f"pmid:{PMID}"],
    )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    bad = {"text": "A fictional 31337 patients.", "sources": [f"pmid:{PMID}"]}
    data["level_reason"] = [bad]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    first = [i for i in citations.check_paths([path], cache)[1] if i.code == "C10"]
    data["level_reason"] = [{"text": "Another fictional sentence.", "sources": [f"pmid:{PMID}"]}, bad]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    second = [i for i in citations.check_paths([path], cache)[1] if i.code == "C10"]
    assert [(i.study, i.message) for i in first] == [(i.study, i.message) for i in second] and len(first) == 1


def test_a_derivation_in_a_card_is_checked_against_the_sources(tmp_path, cache):
    sources = [f"pmid:{PMID}"]
    studies = [plain()]
    assert c10(tmp_path, cache, studies=studies, claim="1,246 (= 1,234 + 12) patients in all.", sources=sources) == []
    wrong = c10(tmp_path, cache, studies=studies, claim="1,247 (= 1,234 + 12) patients in all.", sources=sources)
    assert len(wrong) == 1 and "wrong" in wrong[0].message
