"""Tests for the full-text target list and for pages saved by hand (me_atlas.fulltext).

Fictional PMIDs and PMCIDs; cards and cache are built in tmp_path (helpers from test_citations). No network, no LLM.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from test_citations import (
    PREPRINT_DOI,
    PREPRINT_PMCID,
    add_fulltext,
    add_page,
    add_preprint,
    add_record,
    make_study,
    preprint_study,
    write_card,
)

from me_atlas import fulltext

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "europepmc"

# One pmid per status, so a line in the output names its case.
XML_ABSTRACT = "90000101"  # supports, source abstract, real XML
XML_FULLTEXT = "90000102"  # supports, source fulltext, real XML: not listed
PAGE_CTX = "90000103"  # context, unverified, controlled, measures PEM, page cached
PLACEHOLDER = "90000104"  # supports, source fulltext, XML is a PDF placeholder
OA_UNCACHED = "90000105"  # supports, source fulltext, open access, nothing cached
FREE = "90000106"  # contradicts, source fulltext, not open access, inPMC Y
NOT_IN_PMC = "90000107"  # early_signal, source fulltext, inPMC N
NO_PMCID = "90000108"  # supports, lookup without a PMC id
NO_LOOK = "90000109"  # supports, nothing cached at all
FREE_PUBMED = "90000110"  # supports, no lookup, PMC id only in the PubMed record
REVIEW = "90000111"  # context review, design other, unverified: not listed
NAMED_ONLY = "90000112"  # context, Fukuda, in neither category, but named
UNC = "90000113"  # context, unverified, uncontrolled
INTERV = "90000114"  # context, unverified, intervention_controlled
PAGE_FULLTEXT = "90000115"  # supports, source fulltext, page cached: not listed

SLUG = "fictional-card"


def lookup(root: Path, pmid: str, pmcid: str | None, *, oa: bool = False, in_pmc: bool = False) -> None:
    hit = {
        "id": pmid,
        "source": "MED",
        "pmid": pmid,
        "isOpenAccess": "Y" if oa else "N",
        "inPMC": "Y" if in_pmc else "N",
    }
    if pmcid:
        hit["pmcid"] = pmcid
    folder = root / "europepmc"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{pmid}.json").write_text(json.dumps({"hitCount": 1, "resultList": {"result": [hit]}}), encoding="utf-8")


def build(tmp_path: Path) -> tuple[Path, Path]:
    """The cache and the cards directory of the fixture set, covering every status and category."""
    root = tmp_path / "cache"
    add_fulltext(root, XML_ABSTRACT, "PMC9100001")
    add_fulltext(root, XML_FULLTEXT, "PMC9100002")
    add_page(root, PAGE_CTX, "PMC9100003")
    lookup(root, PLACEHOLDER, "PMC9100004", oa=True, in_pmc=True)
    (root / "europepmc" / "PMC9100004.xml").write_text(
        "<article><body><p>The full text is available as a PDF.</p></body></article>", encoding="utf-8"
    )
    lookup(root, OA_UNCACHED, "PMC9100005", oa=True, in_pmc=True)
    lookup(root, FREE, "PMC9100006", in_pmc=True)
    lookup(root, NOT_IN_PMC, "PMC9100007")
    lookup(root, NO_PMCID, None)
    add_record(root, FREE_PUBMED, pmcid="PMC9100010")
    add_page(root, PAGE_FULLTEXT, "PMC9100015")
    add_preprint(root)  # the fixture's first preprint, with PMC id PMC9000010
    studies = [
        make_study(XML_ABSTRACT, role="supports", case_definition_source="abstract"),
        make_study(XML_FULLTEXT, role="supports", case_definition_source="fulltext"),
        make_study(
            PAGE_CTX,
            case_definition="unverified",
            case_definition_source=None,
            case_definition_quote=None,
            measures_pem=True,
            n_controls=None,
        ),
        make_study(PLACEHOLDER, role="supports", case_definition_source="fulltext"),
        make_study(OA_UNCACHED, role="supports", case_definition_source="fulltext"),
        make_study(FREE, role="contradicts", case_definition_source="fulltext", direction="no_difference"),
        make_study(NOT_IN_PMC, role="early_signal", case_definition_source="fulltext"),
        make_study(NO_PMCID, role="supports", case_definition_source="fulltext"),
        make_study(NO_LOOK, role="supports", case_definition_source="fulltext"),
        make_study(FREE_PUBMED, role="supports", case_definition_source="fulltext"),
        make_study(
            REVIEW,
            case_definition="unverified",
            case_definition_source=None,
            case_definition_quote=None,
            design="other",
        ),
        make_study(NAMED_ONLY),
        make_study(
            UNC,
            case_definition="unverified",
            case_definition_source=None,
            case_definition_quote=None,
            design="uncontrolled",
        ),
        make_study(
            INTERV,
            case_definition="unverified",
            case_definition_source=None,
            case_definition_quote=None,
            design="intervention_controlled",
        ),
        make_study(PAGE_FULLTEXT, role="supports", case_definition_source="fulltext"),
    ]
    studies.append(preprint_study(role="early_signal"))
    write_card(tmp_path / "cards", studies, SLUG)
    return root, tmp_path / "cards"


def config(tmp_path: Path, items: list[dict]) -> Path:
    path = tmp_path / "named.yaml"
    path.write_text(yaml.safe_dump({"named": items}), encoding="utf-8")
    return path


def named_entry(study: str | None, card: str = SLUG, note: str = "A fictional note.") -> dict:
    return {"card": card, "study": study, "note": note}


def run_needs(tmp_path: Path, capsys, items: list[dict] | None = None, *extra: str) -> tuple[int, str, str]:
    root, cards = build(tmp_path) if not (tmp_path / "cards").exists() else (tmp_path / "cache", tmp_path / "cards")
    if items is None:
        items = [named_entry(f"pmid:{NAMED_ONLY}")]
    code = fulltext.main(
        ["needs", "--cards-dir", str(cards), "--config", str(config(tmp_path, items)), "--cache-dir", str(root), *extra]
    )
    out = capsys.readouterr()
    return code, out.out, out.err


def block(output: str, study_id: str) -> str:
    """The text lines of one study (from its id line to the next)."""
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"pmid:{study_id}") or line.startswith(study_id))
    end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i].startswith(" ")), len(lines))
    return "\n".join(lines[start:end])


# --- statuses ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pmid", "status"),
    [
        (XML_ABSTRACT, "fulltext_xml"),
        (PAGE_CTX, "pmc_page"),
        (PLACEHOLDER, "pdf_placeholder"),
        (OA_UNCACHED, "open_access_not_cached"),
        (FREE, "free_on_pmc"),
        (FREE_PUBMED, "free_on_pmc"),
        (NOT_IN_PMC, "pmc_id_not_in_pmc"),
        (NO_PMCID, "no_pmc_id"),
        (NO_LOOK, "no_lookup"),
    ],
)
def test_each_status_is_computed_from_the_cache(tmp_path, capsys, pmid, status):
    code, out, err = run_needs(tmp_path, capsys, [])
    assert code == 0, err
    assert f"status: {status}" in block(out, pmid)


def test_a_placeholder_with_a_cached_page_is_a_page(tmp_path):
    root, cards = build(tmp_path)
    (root / "europepmc" / "PMC9100004.html").write_text(
        '<html><head><meta name="citation_pmid" content="x"></head></html>', encoding="utf-8"
    )
    card = fulltext.load_card(cards / f"{SLUG}.yaml")
    study = next(s for s in card.studies if s.id == f"pmid:{PLACEHOLDER}")
    assert fulltext.study_status(study, fulltext.CacheReader(root)).status == "pmc_page"


def test_preprint_study_takes_its_pmc_id_from_the_preprint_record(tmp_path, capsys):
    _, out, _ = run_needs(tmp_path, capsys, [])
    text = block(out, f"doi:{PREPRINT_DOI}")
    assert "status: open_access_not_cached" in text
    assert f"https://pmc.ncbi.nlm.nih.gov/articles/{PREPRINT_PMCID}/" in text
    assert "europepmc preprint" in text


def test_doi_study_with_no_cached_record_is_no_lookup(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    study = fulltext.Study.model_validate(make_study(id="doi:10.1/none", preprint=True, role="early_signal"))
    assert fulltext.study_status(study, fulltext.CacheReader(root)) == fulltext.FullTextStatus("no_lookup", None)


def test_pdf_only_and_pmc_no_xml_are_never_a_known_status():
    assert "pdf_only" not in fulltext.STATUSES and "pmc_no_xml" not in fulltext.STATUSES


# --- categories ----------------------------------------------------------------


def test_carrying_study_with_source_fulltext_and_cached_xml_is_not_listed(tmp_path, capsys):
    _, out, _ = run_needs(tmp_path, capsys, [])
    assert f"pmid:{XML_FULLTEXT}" not in out


def test_carrying_study_with_source_fulltext_and_a_cached_page_is_not_listed(tmp_path, capsys):
    _, out, _ = run_needs(tmp_path, capsys, [])
    assert f"pmid:{PAGE_FULLTEXT}" not in out


def test_abstract_source_with_cached_xml_is_listed_with_casedef_as_next_step(tmp_path, capsys):
    _, out, _ = run_needs(tmp_path, capsys, [])
    text = block(out, f"pmid:{XML_ABSTRACT}")
    assert "category: carrying: its case definition was read from the abstract" in text
    assert "europepmc casedef" in text
    assert "no full text is cached" not in text


def test_carrying_study_without_full_text_names_that_reason(tmp_path, capsys):
    _, out, _ = run_needs(tmp_path, capsys, [])
    assert "no full text is cached" in block(out, f"pmid:{NO_LOOK}")
    assert "europepmc fulltext " + NO_LOOK in block(out, f"pmid:{NO_LOOK}")


def test_context_review_with_design_other_is_not_listed(tmp_path, capsys):
    _, out, _ = run_needs(tmp_path, capsys, [])
    assert f"pmid:{REVIEW}" not in out


@pytest.mark.parametrize("update", [{"preprint": True}, {"corrects": "pmid:90000101"}])
def test_a_preprint_or_a_correction_is_not_an_unverified_target(update):
    """The card rules (V15, V17) keep these from a valid card, so the rule is tested on the study itself."""
    base = make_study(case_definition="unverified", case_definition_source=None, case_definition_quote=None)
    assert fulltext.unverified_reason(fulltext.Study.model_validate(base)) is not None
    assert fulltext.unverified_reason(fulltext.Study.model_validate(base).model_copy(update=update)) is None


@pytest.mark.parametrize(
    ("pmid", "rung"),
    [(PAGE_CTX, "level 2-3 and the contested mark"), (UNC, "level 1"), (INTERV, "level 4")],
)
def test_unverified_context_study_names_the_rung_it_could_count_towards(tmp_path, capsys, pmid, rung):
    _, out, _ = run_needs(tmp_path, capsys, [])
    assert f"category: unverified: unverified case definition; verified, it could count towards {rung}" in block(
        out, f"pmid:{pmid}"
    )


def test_pem_measuring_unverified_study_names_the_badge_and_what_would_settle(tmp_path, capsys):
    _, out, _ = run_needs(tmp_path, capsys, [])
    text = block(out, f"pmid:{PAGE_CTX}")
    assert "explains_pem badge" in text
    assert "n_controls" in text and "the PEM measurement" in text
    assert "already cached" in text


def test_contradicting_study_asks_for_the_patient_count(tmp_path, capsys):
    _, out, _ = run_needs(tmp_path, capsys, [])
    text = block(out, f"pmid:{FREE}")
    assert "the patient count in the contradicting measurement" in text
    assert "save the PMC page by hand" in text
    assert "https://pmc.ncbi.nlm.nih.gov/articles/PMC9100006/" in text
    assert f"https://pubmed.ncbi.nlm.nih.gov/{FREE}/" in text


def test_status_without_a_route_says_not_free_on_pmc(tmp_path, capsys):
    _, out, _ = run_needs(tmp_path, capsys, [])
    assert "not free on PMC" in block(out, f"pmid:{NOT_IN_PMC}")


# --- named items ---------------------------------------------------------------


def test_named_study_outside_both_categories_is_listed_as_named(tmp_path, capsys):
    code, out, _ = run_needs(tmp_path, capsys)
    assert code == 0
    text = block(out, f"pmid:{NAMED_ONLY}")
    assert "category: named" in text and "named in STATUS.md: A fictional note." in text


def test_named_study_in_a_category_keeps_its_category_and_gets_the_note(tmp_path, capsys):
    _, out, _ = run_needs(tmp_path, capsys, [named_entry(f"pmid:{FREE}")])
    text = block(out, f"pmid:{FREE}")
    assert "category: carrying" in text and "named in STATUS.md: A fictional note." in text
    assert "named in STATUS.md" not in block(out, f"pmid:{NO_LOOK}")


def test_a_null_study_marks_every_listed_study_of_the_card_but_lists_no_more(tmp_path, capsys):
    _, out, _ = run_needs(tmp_path, capsys, [named_entry(None)])
    assert out.count("named in STATUS.md:") == 12  # every study listed by a rule; the named-only one is not added
    assert "named in STATUS.md" in block(out, f"pmid:{NO_LOOK}")
    assert f"pmid:{NAMED_ONLY}" not in out
    assert f"pmid:{REVIEW}" not in out


def test_named_study_not_on_the_card_is_an_error(tmp_path, capsys):
    code, _, err = run_needs(tmp_path, capsys, [named_entry("pmid:99999999")])
    assert code == 1 and "pmid:99999999" in err and "not a study on that card" in err


def test_named_card_that_does_not_exist_is_an_error(tmp_path, capsys):
    code, _, err = run_needs(tmp_path, capsys, [named_entry(None, card="no-such-card")])
    assert code == 1 and "no-such-card" in err


def test_a_malformed_config_is_an_error(tmp_path, capsys):
    root, cards = build(tmp_path)
    bad = tmp_path / "bad.yaml"
    bad.write_text("named: [{card: x}]\n", encoding="utf-8")
    code = fulltext.main(["needs", "--cards-dir", str(cards), "--config", str(bad), "--cache-dir", str(root)])
    assert code == 1 and "exactly the keys" in capsys.readouterr().err


def test_a_card_that_fails_to_load_is_an_error_and_the_others_are_still_listed(tmp_path, capsys):
    root, cards = build(tmp_path)
    (cards / "broken.yaml").write_text("slug: broken\n", encoding="utf-8")
    code = fulltext.main(
        ["needs", "--cards-dir", str(cards), "--config", str(config(tmp_path, [])), "--cache-dir", str(root)]
    )
    out = capsys.readouterr()
    assert code == 1 and "broken.yaml" in out.err
    assert f"pmid:{XML_ABSTRACT}" in out.out


# --- output --------------------------------------------------------------------


def test_summary_counts(tmp_path, capsys):
    _, out, _ = run_needs(tmp_path, capsys)
    summary = out.split("Summary", 1)[1]
    assert "Listed: 13" in summary
    assert "Category named: 1" in summary
    assert "Not listed: 3" in summary
    assert "Status no_pmc_id: 1" in summary


def test_markdown_lists_the_same_studies_as_text(tmp_path, capsys):
    _, text, _ = run_needs(tmp_path, capsys)
    _, md, _ = run_needs(tmp_path, capsys, None, "--markdown")
    ids = [line.split()[0] for line in text.splitlines() if line.startswith(("pmid:", "doi:"))]
    assert len(ids) == 13
    for study_id in ids:
        assert f"`{study_id}`" in md
    assert md.count("\n| `") == len(ids)
    assert "## Summary" in md and "| Not listed | 3 |" in md and f"## {SLUG}" in md


def test_the_real_named_config_names_studies_that_are_on_the_real_cards(tmp_path):
    named = fulltext.load_named(ROOT / "config" / "fulltext_named.yaml")
    assert len(named) == 3
    report = fulltext.build_report(ROOT / "cards", named, tmp_path / "empty-cache")
    assert report.errors == []


# --- import-saved ----------------------------------------------------------------

SAVED_PMID = "90000004"
SAVED_PMCID = "PMC9000004"


@pytest.fixture
def env(tmp_path):
    cache = tmp_path / "cache"
    add_record(cache, SAVED_PMID, pmcid=SAVED_PMCID)
    lookup(cache, SAVED_PMID, SAVED_PMCID, in_pmc=True)
    card = write_card(tmp_path / "drafts", [make_study(SAVED_PMID)], "fictional-saved")
    saved = tmp_path / "saved"
    saved.mkdir()
    (saved / f"{SAVED_PMID}.html").write_bytes((FIXTURES / "PMC9000004.html").read_bytes())
    return tmp_path, card, cache, saved


def run_import(env, pmid: str = SAVED_PMID, card: Path | None = None) -> int:
    _, default_card, cache, saved = env
    return fulltext.main(
        [
            "import-saved",
            "--card",
            str(card or default_card),
            "--pmid",
            pmid,
            "--cache-dir",
            str(cache),
            "--saved-dir",
            str(saved),
        ]
    )


def written(cache: Path) -> list[str]:
    return sorted(p.name for p in (cache / "europepmc").glob("*.html"))


def test_import_saved_stores_the_bytes_unchanged_and_prints_the_candidates(env, capsys):
    _, _, cache, saved = env
    assert run_import(env) == 0
    stored = cache / "europepmc" / f"{SAVED_PMCID}.html"
    assert stored.read_bytes() == (saved / f"{SAVED_PMID}.html").read_bytes()
    out = capsys.readouterr().out
    assert str(stored) in out and "Fukuda" in out


def test_import_saved_takes_an_htm_file_too(env):
    _, _, cache, saved = env
    (saved / f"{SAVED_PMID}.html").rename(saved / f"{SAVED_PMID}.htm")
    assert run_import(env) == 0
    assert written(cache) == [f"{SAVED_PMCID}.html"]


def test_import_saved_uses_the_pubmed_record_when_there_is_no_lookup(env):
    _, _, cache, _ = env
    (cache / "europepmc" / f"{SAVED_PMID}.json").unlink()
    assert run_import(env) == 0


def test_refuses_a_pmid_that_is_not_a_study_on_the_card(env, capsys):
    assert run_import(env, "90000999") == 1
    assert written(env[2]) == [] and "not a pmid: study" in capsys.readouterr().err


def test_refuses_a_pmid_that_is_not_digits(env):
    assert run_import(env, "PMC123") == 1 and written(env[2]) == []


def test_refuses_when_no_file_was_saved(env, capsys):
    (env[3] / f"{SAVED_PMID}.html").unlink()
    assert run_import(env) == 1
    assert written(env[2]) == [] and "no saved page" in capsys.readouterr().err


def test_refuses_when_both_html_and_htm_exist(env, capsys):
    (env[3] / f"{SAVED_PMID}.htm").write_bytes(b"<html></html>")
    assert run_import(env) == 1
    assert written(env[2]) == [] and "both" in capsys.readouterr().err


def test_refuses_when_no_pmc_id_is_known(env, capsys):
    _, _, cache, _ = env
    lookup(cache, SAVED_PMID, None)
    add_record(cache, SAVED_PMID)
    assert run_import(env) == 1
    assert written(cache) == [] and "no PMC id" in capsys.readouterr().err


def test_refuses_when_full_text_xml_is_already_cached(env, capsys):
    _, _, cache, _ = env
    add_fulltext(cache, SAVED_PMID, SAVED_PMCID)
    assert run_import(env) == 1
    assert written(cache) == [] and "already has full text" in capsys.readouterr().err


def test_a_placeholder_xml_does_not_stop_the_import(env):
    _, _, cache, _ = env
    (cache / "europepmc" / f"{SAVED_PMCID}.xml").write_text(
        "<article><body><p>The full text is available as a PDF.</p></body></article>", encoding="utf-8"
    )
    assert run_import(env) == 0


def test_refuses_when_a_page_is_already_cached(env, capsys):
    _, _, cache, _ = env
    existing = cache / "europepmc" / f"{SAVED_PMCID}.html"
    existing.write_text("old", encoding="utf-8")
    assert run_import(env) == 1
    assert existing.read_text(encoding="utf-8") == "old" and "already has a page" in capsys.readouterr().err


def test_refuses_a_page_of_another_article(env, capsys):
    _, _, cache, saved = env
    page = (saved / f"{SAVED_PMID}.html").read_text(encoding="utf-8").replace("90000004", "90000777")
    (saved / f"{SAVED_PMID}.html").write_text(page, encoding="utf-8")
    assert run_import(env) == 1
    assert written(cache) == [] and capsys.readouterr().err.startswith("refused")


def test_refuses_a_page_with_no_article_body(env):
    _, _, cache, saved = env
    (saved / f"{SAVED_PMID}.html").write_text(
        f'<html><head><meta name="citation_pmid" content="{SAVED_PMID}"></head><body><p>Bot check</p></body></html>',
        encoding="utf-8",
    )
    assert run_import(env) == 1 and written(cache) == []
