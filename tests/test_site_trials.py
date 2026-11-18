"""Tests for the registered-studies page, the card-page line and the dataset files (contract S1-S6, E1, E2).

Fictional cards and registry entries in tmp_path; no network, no LLM."""

from __future__ import annotations

import csv
import io
import json
import re

import pytest
import yaml
from test_site import EN, I18N_DIR, Site, make_card, page, write_card

from me_atlas import export, i18n, trials

DAY = "2026-11-18"


def study(nct: str, title: str, hypotheses=(), mapping=None, **over) -> dict:
    base = {
        "nct_id": nct,
        "title": title,
        "study_type": "OBSERVATIONAL",
        "status": "RECRUITING",
        "countries": ["Norway"],
        "enrollment": {"count": 100, "type": "ESTIMATED"},
        "start_date": "2025-03",
        "last_update": "2026-10-01",
        "searches": ["me_cfs"],
        "hypotheses": list(hypotheses),
        "mapping": mapping or ("accepted" if hypotheses else "not_mapped"),
        "mapping_source": "data/pipeline/2026-11-18/trials/review-1.json" if hypotheses else None,
    }
    base.update(over)
    return base


ENTRIES = [
    study("NCT90000001", "Fictional study one", ["first-idea", "second-idea"], study_type="INTERVENTIONAL"),
    study("NCT90000002", "Fictional study two", ["first-idea"], countries=["Germany", "Norway"]),
    study("NCT90000003", "Fictional study three", ["second-idea"], status="NOT_YET_RECRUITING", enrollment=None),
    study("NCT90000004", "Fictional completed study", ["first-idea"], status="COMPLETED"),
    study("NCT90000005", "Fictional unmatched study"),
    study("NCT90000006", "Fictional rejected mapping", mapping="rejected"),
    study("NCT90000007", "Fictional absent study", ["first-idea"], searches=[]),
    study("NCT90000008", "Fictional accepted for no card", mapping="accepted"),
]


def registry_site(tmp_path, *, passed: bool | None, entries=None) -> Site:
    proj = Site(tmp_path)
    write_card(proj.cards, make_card("first-idea", "Zeta fictional idea", 2))
    write_card(proj.cards, make_card("second-idea", "Alpha fictional idea", 1))
    registry = tmp_path / "registry"
    registry.mkdir()
    data = {
        "fetched": DAY,
        "searches": dict(trials.SEARCHES),
        "studies": sorted(entries or ENTRIES, key=lambda e: e["nct_id"]),
    }
    (registry / "trials.yaml").write_text(trials.dump_data(data), encoding="utf-8")
    if passed is not None:
        (registry / "reliability.yaml").write_text(yaml.safe_dump({"passed": passed}), encoding="utf-8")
    return proj


def build(proj: Site):
    result = proj.build()
    assert result.errors == []
    return proj.out


def read_trials_csv(out) -> list[dict[str, str]]:
    text = (out / "data" / "trials.csv").read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text, newline="")))


def nav_hrefs(doc) -> list[str]:
    return [a.get("href") for a in doc.find("nav").find_all("a")]


# --- S1: the gate -------------------------------------------------------------------


@pytest.mark.parametrize("passed", [None, False])
def test_without_a_passed_reliability_file_there_is_no_page_no_line_no_link_but_the_data_holds_the_list(
    tmp_path, passed
):
    out = build(registry_site(tmp_path, passed=passed))
    assert not (out / "trials.html").exists() and not (out / "nb" / "trials.html").exists()
    for rel in ("index.html", "nb/index.html", "hypotheses/first-idea.html", "nb/hypotheses/first-idea.html"):
        doc = page(out, rel)
        assert not any("trials.html" in h for h in nav_hrefs(doc)), rel
        assert doc.find(cls="trials-line") is None, rel
    rows = read_trials_csv(out)
    assert len(rows) == len(ENTRIES)
    data = json.loads((out / "data" / "me-atlas.json").read_text(encoding="utf-8"))
    assert len(data["trials"]) == len(ENTRIES) and data["dataset"]["trials_fetched"] == DAY


def test_a_project_without_a_registry_builds_without_the_page_and_with_an_empty_trials_file(tmp_path):
    proj = Site(tmp_path)
    write_card(proj.cards, make_card("first-idea", "Fictional first idea", 2))
    out = build(proj)
    assert not (out / "trials.html").exists()
    assert read_trials_csv(out) == []
    assert (out / "data" / "trials.csv").read_text(encoding="utf-8").startswith("nct_id,title,")
    assert json.loads((out / "data" / "me-atlas.json").read_text(encoding="utf-8"))["trials"] == []


def test_a_passed_reliability_file_builds_the_page_in_both_languages_with_a_nav_link_and_card_lines(tmp_path):
    out = build(registry_site(tmp_path, passed=True))
    for prefix in ("", "nb/"):
        assert (out / f"{prefix}trials.html").is_file()
        for rel in ("index.html", "hypotheses/first-idea.html", "trials.html"):
            hrefs = nav_hrefs(page(out, prefix + rel))
            assert hrefs.count(("../" if "/" in rel else "") + "trials.html") == 1, (prefix, rel)
        assert page(out, f"{prefix}hypotheses/first-idea.html").find(cls="trials-line") is not None


def test_an_invalid_registry_file_stops_the_build_and_names_the_entry(tmp_path):
    proj = registry_site(tmp_path, passed=True, entries=[study("NCT90000001", "x", ["no-such-card"])])
    result = proj.build()
    assert result.errors and "NCT90000001" in result.errors[0] and "no-such-card" in result.errors[0]
    assert not proj.out.exists()


def test_a_reliability_file_that_cannot_be_read_stops_the_build(tmp_path):
    proj = registry_site(tmp_path, passed=None)
    (tmp_path / "registry" / "reliability.yaml").write_text("passed: maybe\n", encoding="utf-8")
    assert proj.build().errors


# --- S2-S4: the page -------------------------------------------------------------------


def tables(doc) -> dict[str, list[list[str]]]:
    """Section id -> rows of cells (the registry number cell first)."""
    out = {}
    for section in doc.find("main").find_all("section"):
        rows = []
        for tr in section.find("tbody").find_all("tr"):
            cells = [tr.find("th")] + tr.find_all("td")
            rows.append([c.text().strip() for c in cells])
        out[section.get("id")] = rows
    return out


def test_one_table_per_hypothesis_sorted_by_name_rows_by_registry_number_and_only_listed_studies(tmp_path):
    out = build(registry_site(tmp_path, passed=True))
    doc = page(out, "trials.html")
    sections = doc.find("main").find_all("section")
    # Alpha (second-idea) before Zeta (first-idea): name order, not slug order
    assert [s.get("id") for s in sections] == ["trials-second-idea", "trials-first-idea"]
    rows = tables(doc)
    assert [r[0] for r in rows["trials-first-idea"]] == ["NCT90000001", "NCT90000002"]
    assert [r[0] for r in rows["trials-second-idea"]] == ["NCT90000001", "NCT90000003"]
    text = doc.find("main").text()
    for hidden in ("NCT90000004", "NCT90000005", "NCT90000006", "NCT90000007", "NCT90000008"):
        assert hidden not in text


def test_the_columns_are_the_copied_fields_with_a_link_to_the_registry_record(tmp_path):
    out = build(registry_site(tmp_path, passed=True))
    doc = page(out, "trials.html")
    section = doc.find("section", id="trials-first-idea")
    heads = [th.text().strip() for th in section.find("thead").find_all("th")]
    assert heads == [
        EN["trials.col.id"],
        EN["trials.col.title"],
        EN["trials.col.type"],
        EN["trials.col.status"],
        EN["trials.col.countries"],
        EN["trials.col.enrolment"],
    ]
    first = section.find("tbody").find_all("tr")[0]
    link = first.find("th").find("a")
    assert link.get("href") == "https://clinicaltrials.gov/study/NCT90000001"
    cells = [td.text().strip() for td in first.find_all("td")]
    assert cells == ["Fictional study one", "Interventional", "Recruiting", "Norway", "100 (estimated)"]
    second = section.find("tbody").find_all("tr")[1]
    assert [td.text().strip() for td in second.find_all("td")][3] == "Germany, Norway"
    third = page(out, "trials.html").find("section", id="trials-second-idea").find_all("tr")[-1]
    assert [td.text().strip() for td in third.find_all("td")][4] == EN["trials.none"]


def test_the_page_states_the_counts_the_date_and_that_a_study_can_appear_twice(tmp_path):
    out = build(registry_site(tmp_path, passed=True))
    text = " ".join(page(out, "trials.html").find("main").text().split())
    assert "Distinct studies listed: 3." in text  # 01, 02, 03
    assert "more than one hypothesis appears under each" in text
    # ongoing, in the latest fetch, not listed: 05 (not mapped), 06 (rejected), 08 (accepted for no card)
    assert "that are not listed: 3." in text
    assert "downloadable data" in text and "2026-11-18" in text
    assert "not evidence" in text and "no treatment advice" in text


def test_the_page_has_no_script_no_contact_details_and_no_recruiting_list_of_its_own(tmp_path):
    out = build(registry_site(tmp_path, passed=True))
    html = (out / "trials.html").read_text(encoding="utf-8")
    assert "mailto:" not in html and "@" not in html
    main = page(out, "trials.html").find("main")
    assert main.find("script") is None
    assert len(main.find_all("table")) == 2  # one per hypothesis, nothing else


def test_titles_are_shown_in_english_with_lang_en_on_the_norwegian_page_and_the_page_is_translated(tmp_path):
    out = build(registry_site(tmp_path, passed=True))
    nb = page(out, "nb/trials.html")
    assert nb.find("h1").text() == "Registrerte pågående studier"
    first = nb.find("section", id="trials-first-idea").find("tbody").find_all("tr")[0]
    title_cell = first.find_all("td")[0]
    assert title_cell.get("lang") == "en" and title_cell.text().strip() == "Fictional study one"
    assert first.find_all("td")[1].text().strip() == "Intervensjonsstudie"
    assert first.find("th").find("a").get("href") == "https://clinicaltrials.gov/study/NCT90000001"
    en = page(out, "trials.html")
    assert en.find("section", id="trials-first-idea").find("td").get("lang") is None


def test_an_empty_list_says_so_and_still_counts_the_unlisted(tmp_path):
    out = build(registry_site(tmp_path, passed=True, entries=[study("NCT90000005", "Fictional unmatched study")]))
    doc = page(out, "trials.html")
    assert doc.find("main").find("table") is None
    text = " ".join(doc.find("main").text().split())
    assert EN["trials.empty"] in text and "Distinct studies listed: 0." in text and "not listed: 1." in text
    assert page(out, "hypotheses/first-idea.html").find(cls="trials-line") is None


# --- S5 and E2: the numbers agree ---------------------------------------------------------


def line_number(doc) -> int | None:
    line = doc.find(cls="trials-line")
    return None if line is None else int(re.search(r"(\d+)", line.text()).group(1))


@pytest.mark.parametrize("prefix", ["", "nb/"])
def test_listed_rows_per_card_the_card_page_line_and_the_csv_agree(tmp_path, prefix):
    out = build(registry_site(tmp_path, passed=True))
    doc = page(out, f"{prefix}trials.html")
    rows_per_card = {sid.removeprefix("trials-"): len(r) for sid, r in tables(doc).items()}
    csv_rows = read_trials_csv(out)
    for slug in ("first-idea", "second-idea"):
        from_csv = sum(
            1
            for r in csv_rows
            if r["status"] in trials.ONGOING_STATUSES
            and r["mapping"] == "accepted"
            and r["searches"]  # in the latest fetch
            and slug in [h.strip() for h in r["hypotheses"].split(";")]
        )
        card_doc = page(out, f"{prefix}hypotheses/{slug}.html")
        assert rows_per_card[slug] == line_number(card_doc) == from_csv, slug
        link = card_doc.find(cls="trials-line").find("a")
        assert link.get("href") == f"../trials.html#trials-{slug}"
    assert rows_per_card == {"first-idea": 2, "second-idea": 2}


def test_a_card_with_no_listed_study_has_no_line(tmp_path):
    entries = [study("NCT90000001", "Fictional study one", ["first-idea"])]
    out = build(registry_site(tmp_path, passed=True, entries=entries))
    assert line_number(page(out, "hypotheses/first-idea.html")) == 1
    assert page(out, "hypotheses/second-idea.html").find(cls="trials-line") is None


# --- E1: the dataset ---------------------------------------------------------------------------


def test_trials_csv_has_every_entry_matched_or_not_ongoing_or_not_and_joins_hypotheses_with_semicolons(tmp_path):
    out = build(registry_site(tmp_path, passed=True))
    rows = {r["nct_id"]: r for r in read_trials_csv(out)}
    assert sorted(rows) == [e["nct_id"] for e in ENTRIES]
    assert rows["NCT90000001"]["hypotheses"] == "first-idea; second-idea"
    assert rows["NCT90000001"]["enrollment_count"] == "100" and rows["NCT90000001"]["enrollment_type"] == "ESTIMATED"
    assert rows["NCT90000003"]["enrollment_count"] == ""
    assert rows["NCT90000002"]["countries"] == "Germany; Norway"
    assert rows["NCT90000004"]["status"] == "COMPLETED" and rows["NCT90000006"]["mapping"] == "rejected"
    assert tuple(next(iter(rows.values()))) == export.TRIALS_COLUMNS


def test_the_json_holds_the_same_entries_and_the_fetch_date(tmp_path):
    out = build(registry_site(tmp_path, passed=True))
    data = json.loads((out / "data" / "me-atlas.json").read_text(encoding="utf-8"))
    assert [t["nct_id"] for t in data["trials"]] == [e["nct_id"] for e in ENTRIES]
    assert data["trials"][0] == ENTRIES[0] and data["dataset"]["trials_fetched"] == DAY


def test_the_data_page_and_the_readme_list_the_trials_file(tmp_path):
    out = build(registry_site(tmp_path, passed=None))
    assert "trials.csv" in export.DATA_FILES
    for prefix in ("", "nb/"):
        links = [a.get("href") for a in page(out, f"{prefix}data.html").find("main").find_all("a")]
        assert ("../" if prefix else "") + "data/trials.csv" in links
    readme = (out / "data" / "README.txt").read_text(encoding="utf-8")
    assert len([ln for ln in readme.splitlines() if ln.startswith("trials.csv")]) == 1


# --- S6: no invitation, no judgement of an intervention ---------------------------------------------------

BANNED_EN = (
    "join",
    "sign up",
    "enrol now",
    "enroll now",
    "participate",
    "volunteer",
    "contact",
    "promising",
    "effective",
    "recommend",
)
BANNED_NB = ("delta", "meld deg", "lovende", "effektiv", "anbefal")
NEW_KEY = re.compile(r"^(trials\.|card\.trials$|page\.trials$|data\.file\.trials\.csv$)")


def test_no_new_string_invites_taking_part_or_judges_an_intervention():
    for code, banned in (("en", BANNED_EN), ("nb", BANNED_NB)):
        strings = i18n.load_strings(I18N_DIR / f"{code}.yaml")
        keys = [k for k in strings if NEW_KEY.match(k)]
        assert len(keys) >= 25  # every string of the page, the card line, the nav label and the data file
        for key in keys:
            text = strings[key].casefold()
            for word in banned:
                assert not re.search(rf"\b{re.escape(word)}", text), f"{code}.yaml {key}: {word!r}"


def test_no_word_of_the_banned_list_is_on_the_built_page_either_language(tmp_path):
    out = build(registry_site(tmp_path, passed=True))
    for rel, banned in (("trials.html", BANNED_EN), ("nb/trials.html", BANNED_NB)):
        main = page(out, rel).find("main")
        # the studies' own titles are the registry's words and are not part of the page's text
        for td in main.find_all("td"):
            td.children.clear()
        text = main.text().casefold()
        for word in banned:
            assert not re.search(rf"\b{re.escape(word)}", text), f"{rel}: {word!r}"
