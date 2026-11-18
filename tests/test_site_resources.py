"""Tests for the data-resources page, its links and the dataset files (contract S1-S4, E1, E2).

Fictional cards and entries in tmp_path; no network, no LLM."""

from __future__ import annotations

import csv
import io
import json
import re

import pytest
import yaml
from test_resources import context, good_draft, named
from test_site import EN, I18N_DIR, Site, make_card, page, write_card

from me_atlas import export, i18n, resources

DAY = "2026-11-18"


MAIN_URL = "https://example.test/biobank"
HELD = {"quote": "It holds blood samples", "page": "main"}


def make_entry(lid: str, name: str, category: str = "data", **over) -> dict:
    entry = resources.build_entry(context() | {"id": lid}, named(good_draft(), lid))
    entry["name"] = name
    entry.update(over)
    if category == "register":
        entry["category"], entry["holds"] = "register", []
    entry["quotes"]["holds"] = {h: dict(HELD) for h in entry["holds"]}
    for field in ("operator", "countries", "access"):
        if entry[field] == "not_stated":
            entry["quotes"][field]["quote"] = ""
    return entry


ENTRIES = [
    make_entry("zeta-bank", "Zeta fictional biobank", holds=["biospecimens"], access="open_download"),
    make_entry(
        "alpha-bank",
        "Alpha fictional cohort",
        covers="me_cfs_and_long_covid",
        countries=["Freedonia", "Elbonia"],
        holds=["biospecimens", "genotypes"],
    ),
    make_entry(
        "beta-bank", "Beta fictional cohort", language="de", operator="Institut Beispiel", countries="not_stated"
    ),
    make_entry("omega-register", "Omega fictional register", "register", access="not_stated"),
    make_entry("delta-register", "Delta fictional register", "register", access="not_stated", language="nb"),
]


def resources_site(tmp_path, *, passed: bool | None, entries=None) -> Site:
    proj = Site(tmp_path)
    write_card(proj.cards, make_card("first-idea", "Fictional first idea", 2))
    registry = tmp_path / "registry"
    registry.mkdir()
    chosen = ENTRIES if entries is None else entries
    data = {"checked": DAY if chosen else None, "entries": sorted(chosen, key=lambda e: e["id"])}
    assert resources.check_data(data) == []
    (registry / "resources.yaml").write_text(resources.dump_data(data), encoding="utf-8")
    if passed is not None:
        (registry / "resources-reliability.yaml").write_text(yaml.safe_dump({"passed": passed}), encoding="utf-8")
    return proj


def build(proj: Site):
    result = proj.build()
    assert result.errors == []
    return proj.out


def read_csv(out) -> list[dict[str, str]]:
    text = (out / "data" / "resources.csv").read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text, newline="")))


def hrefs(doc) -> list[str]:
    return [a.get("href") for a in doc.find_all("a")]


def rows_of(doc, table_id: str) -> list[list[str]]:
    table = doc.find("table", id=table_id)
    if table is None:
        return []
    return [
        [c.text().strip() for c in [tr.find("th")] + tr.find_all("td")] for tr in table.find("tbody").find_all("tr")
    ]


# --- S1: the gate ----------


@pytest.mark.parametrize("passed", [None, False])
def test_without_a_passed_reliability_file_there_is_no_page_no_link_and_no_published_entry(tmp_path, passed):
    out = build(resources_site(tmp_path, passed=passed))
    assert not (out / "resources.html").exists() and not (out / "nb" / "resources.html").exists()
    for rel in ("index.html", "gaps.html", "data.html", "nb/index.html", "nb/gaps.html", "nb/data.html"):
        doc = page(out, rel)
        assert not any("resources.html" in h for h in hrefs(doc)), rel
        assert doc.find(cls="resources-line") is None, rel
    assert read_csv(out) == []
    data = json.loads((out / "data" / "me-atlas.json").read_text(encoding="utf-8"))
    assert data["resources"] == [] and data["dataset"]["resources_checked"] is None


def test_a_passed_file_with_no_entry_builds_no_page_either(tmp_path):
    out = build(resources_site(tmp_path, passed=True, entries=[]))
    assert not (out / "resources.html").exists() and not (out / "nb" / "resources.html").exists()
    assert not any("resources.html" in h for h in hrefs(page(out, "gaps.html")))


def test_a_project_without_a_resources_file_builds_without_the_page_and_with_an_empty_csv(tmp_path):
    proj = Site(tmp_path)
    write_card(proj.cards, make_card("first-idea", "Fictional first idea", 2))
    out = build(proj)
    assert not (out / "resources.html").exists()
    assert read_csv(out) == []
    assert (out / "data" / "resources.csv").read_text(encoding="utf-8").startswith("id,name,operator,")


def test_a_passed_file_builds_the_page_in_both_languages_linked_from_gaps_and_data_but_not_the_navigation(tmp_path):
    out = build(resources_site(tmp_path, passed=True))
    for prefix in ("", "nb/"):
        assert (out / f"{prefix}resources.html").is_file()
        for rel in ("gaps.html", "data.html"):
            doc = page(out, prefix + rel)
            assert hrefs(doc.find("main")).count("resources.html") == 1, (prefix, rel)
            assert doc.find(cls="resources-line") is not None
        for rel in ("index.html", "gaps.html", "resources.html", "hypotheses/first-idea.html"):
            nav = page(out, prefix + rel).find("nav")
            assert not any("resources.html" in h for h in hrefs(nav)), (prefix, rel)
        assert hrefs(page(out, prefix + "index.html").find("main")).count("resources.html") == 0


def test_an_invalid_resources_file_stops_the_build_and_names_the_entry(tmp_path):
    bad = make_entry("bad-entry", "Bad", access="free")
    proj = Site(tmp_path)
    write_card(proj.cards, make_card("first-idea", "Fictional first idea", 2))
    (tmp_path / "registry").mkdir()
    data = {"checked": DAY, "entries": [bad]}
    (tmp_path / "registry" / "resources.yaml").write_text(resources.dump_data(data), encoding="utf-8")
    result = proj.build()
    assert result.errors and "bad-entry" in result.errors[0] and "access" in result.errors[0]
    assert not proj.out.exists()


def test_a_reliability_file_that_cannot_be_read_stops_the_build(tmp_path):
    proj = resources_site(tmp_path, passed=None)
    (tmp_path / "registry" / "resources-reliability.yaml").write_text("passed: maybe\n", encoding="utf-8")
    assert proj.build().errors


# --- S2, S3: the page ----------


def test_two_tables_sorted_by_name_with_only_the_fields_of_each_category(tmp_path):
    doc = page(build(resources_site(tmp_path, passed=True)), "resources.html")
    data_rows = rows_of(doc, "resources-data-table")
    assert [r[0] for r in data_rows] == [
        "Alpha fictional cohort",
        "Beta fictional cohort",
        "Zeta fictional biobank",
    ]
    assert [r[0] for r in rows_of(doc, "resources-register-table")] == [
        "Delta fictional register",
        "Omega fictional register",
    ]
    heads = [th.text().strip() for th in doc.find("table", id="resources-data-table").find("thead").find_all("th")]
    assert heads == [
        EN[f"resources.col.{k}"] for k in ("name", "operator", "countries", "holds", "access", "covers", "checked")
    ]
    heads = [th.text().strip() for th in doc.find("table", id="resources-register-table").find("thead").find_all("th")]
    assert heads == [EN[f"resources.col.{k}"] for k in ("name", "operator", "countries", "checked")]


def test_cells_are_data_file_values_with_enums_through_the_label_table_and_not_stated_labelled(tmp_path):
    doc = page(build(resources_site(tmp_path, passed=True)), "resources.html")
    rows = {r[0]: r for r in rows_of(doc, "resources-data-table")}
    assert rows["Alpha fictional cohort"] == [
        "Alpha fictional cohort",
        "Imaginary Institute of Medicine",
        "Freedonia, Elbonia",
        "Biospecimens, Genotypes",
        "Application",
        "ME/CFS and long COVID",
        DAY,
    ]
    assert rows["Zeta fictional biobank"][3:6] == ["Biospecimens", "Open download", "ME/CFS"]
    assert rows["Beta fictional cohort"][2] == "not stated"
    link = doc.find("table", id="resources-data-table").find("tbody").find_all("tr")[0].find("th").find("a")
    assert link.get("href") == MAIN_URL


def test_the_page_names_register_countries_and_dates_and_shows_not_stated_for_a_missing_access(tmp_path):
    doc = page(build(resources_site(tmp_path, passed=True)), "resources.html")
    register = rows_of(doc, "resources-register-table")
    assert register[0][1:] == ["Imaginary Institute of Medicine", "Freedonia", DAY]


def test_name_operator_and_countries_carry_lang_where_the_entry_language_differs_from_the_page(tmp_path):
    out = build(resources_site(tmp_path, passed=True))
    en = page(out, "resources.html").find("table", id="resources-data-table")
    beta = [tr for tr in en.find("tbody").find_all("tr") if "Beta" in tr.text()][0]
    assert beta.find("th").get("lang") == "de" and beta.find_all("td")[0].get("lang") == "de"
    assert beta.find_all("td")[1].get("lang") is None  # "not stated" is the page's own word
    alpha = [tr for tr in en.find("tbody").find_all("tr") if "Alpha" in tr.text()][0]
    assert alpha.find("th").get("lang") is None
    nb = page(out, "nb/resources.html")
    alpha_nb = [
        tr for tr in nb.find("table", id="resources-data-table").find("tbody").find_all("tr") if "Alpha" in tr.text()
    ][0]
    assert alpha_nb.find("th").get("lang") == "en"
    delta_nb = [
        tr
        for tr in nb.find("table", id="resources-register-table").find("tbody").find_all("tr")
        if "Delta" in tr.text()
    ][0]
    assert delta_nb.find("th").get("lang") is None  # an entry in Norwegian on the Norwegian page


def test_the_page_is_translated_and_labels_come_from_the_norwegian_table(tmp_path):
    nb = page(build(resources_site(tmp_path, passed=True)), "nb/resources.html")
    assert nb.find("h1").text() == "Dataressurser for ME/CFS-forskning"
    rows = {r[0]: r for r in rows_of(nb, "resources-data-table")}
    assert rows["Zeta fictional biobank"][3:6] == ["Biologiske prøver", "Åpen nedlasting", "ME/CFS"]
    assert rows["Beta fictional cohort"][2] == "ikke oppgitt"


def test_the_intro_states_the_source_rule_and_the_page_has_no_quote_script_or_contact_details(tmp_path):
    out = build(resources_site(tmp_path, passed=True))
    html = (out / "resources.html").read_text(encoding="utf-8")
    main = page(out, "resources.html").find("main")
    text = " ".join(main.text().split())
    assert "holds no patient data" in text
    assert "taken from the resource's own page" in text
    assert "not an invitation" in text and "not evidence" in text and "changes no evidence level" in text
    assert "no treatment advice" in text
    assert main.find("script") is None and "mailto:" not in html and "@" not in html
    for entry in ENTRIES:  # no quote text on the page
        for item in (entry["quotes"]["name"], entry["quotes"]["operator"], entry["quotes"]["covers"]):
            assert item["quote"] not in text


def test_an_empty_category_shows_no_table(tmp_path):
    only_data = [e for e in ENTRIES if e["category"] == "data"]
    doc = page(build(resources_site(tmp_path, passed=True, entries=only_data)), "resources.html")
    assert doc.find("table", id="resources-register-table") is None
    assert doc.find("table", id="resources-data-table") is not None
    second = tmp_path / "two"
    second.mkdir()
    only_registers = [e for e in ENTRIES if e["category"] == "register"]
    doc = page(build(resources_site(second, passed=True, entries=only_registers)), "resources.html")
    assert doc.find("table", id="resources-data-table") is None
    assert doc.find("table", id="resources-register-table") is not None


# --- E1, E2: the dataset and the numbers agree ----------


@pytest.mark.parametrize("prefix", ["", "nb/"])
def test_row_counts_of_both_tables_equal_the_counts_by_category_in_the_csv_and_the_json(tmp_path, prefix):
    out = build(resources_site(tmp_path, passed=True))
    doc = page(out, f"{prefix}resources.html")
    shown = {
        "data": len(rows_of(doc, "resources-data-table")),
        "register": len(rows_of(doc, "resources-register-table")),
    }
    rows = read_csv(out)
    from_csv = {c: sum(r["category"] == c for r in rows) for c in ("data", "register")}
    data = json.loads((out / "data" / "me-atlas.json").read_text(encoding="utf-8"))
    from_json = {c: sum(r["category"] == c for r in data["resources"]) for c in ("data", "register")}
    assert shown == from_csv == from_json == {"data": 3, "register": 2}


def test_the_csv_has_one_row_per_entry_with_joined_lists_and_the_quotes_as_columns(tmp_path):
    out = build(resources_site(tmp_path, passed=True))
    rows = {r["id"]: r for r in read_csv(out)}
    assert sorted(rows) == sorted(e["id"] for e in ENTRIES)
    assert tuple(next(iter(rows.values()))) == export.RESOURCES_COLUMNS
    alpha = rows["alpha-bank"]
    assert alpha["countries"] == "Freedonia; Elbonia" and alpha["holds"] == "biospecimens; genotypes"
    assert alpha["access_quote"].startswith("granted by application") and alpha["access_page"] == "access"
    assert alpha["name_quote"] == "The Fictional ME/CFS Biobank is operated by" and alpha["name_page"] == "main"
    assert "biospecimens (main): It holds blood samples" in alpha["holds_quotes"]
    assert rows["beta-bank"]["countries"] == "not_stated"
    assert rows["omega-register"]["holds"] == ""


def test_the_json_holds_the_same_entries_and_the_run_date(tmp_path):
    out = build(resources_site(tmp_path, passed=True))
    data = json.loads((out / "data" / "me-atlas.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in data["resources"]] == sorted(e["id"] for e in ENTRIES)
    assert data["resources"][0] == next(e for e in sorted(ENTRIES, key=lambda e: e["id"]))
    assert data["dataset"]["resources_checked"] == DAY


def test_the_data_page_and_the_readme_list_the_resources_file(tmp_path):
    out = build(resources_site(tmp_path, passed=None))
    assert "resources.csv" in export.DATA_FILES
    for prefix in ("", "nb/"):
        links = hrefs(page(out, f"{prefix}data.html").find("main"))
        assert ("../" if prefix else "") + "data/resources.csv" in links
    readme = (out / "data" / "README.txt").read_text(encoding="utf-8")
    assert len([ln for ln in readme.splitlines() if ln.startswith("resources.csv")]) == 1


# --- S4: no invitation, no judgement ----------

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
NEW_KEY = re.compile(r"^(resources\.|page\.resources$|data\.file\.resources\.csv$)")


def test_no_new_string_invites_taking_part_or_judges_and_every_string_has_its_norwegian_counterpart():
    en = i18n.load_strings(I18N_DIR / "en.yaml")
    nb = i18n.load_strings(I18N_DIR / "nb.yaml")
    keys = [k for k in en if NEW_KEY.match(k)]
    assert len(keys) >= 30
    assert [k for k in nb if NEW_KEY.match(k)] == keys  # same keys, same order
    for code, strings, banned in (("en", en, BANNED_EN), ("nb", nb, BANNED_NB)):
        for key in keys:
            text = strings[key].casefold()
            for word in banned:
                assert not re.search(rf"\b{re.escape(word)}", text), f"{code}.yaml {key}: {word!r}"
    assert i18n.compare(en, nb, "nb") == []


def test_no_word_of_the_banned_list_is_on_the_built_page_either_language(tmp_path):
    out = build(resources_site(tmp_path, passed=True))
    for rel, banned in (("resources.html", BANNED_EN), ("nb/resources.html", BANNED_NB)):
        main = page(out, rel).find("main")
        for cell in main.find_all("td") + main.find_all("th"):  # names, operators and countries are the source's words
            cell.children.clear()
        text = main.text().casefold()
        for word in banned:
            assert not re.search(rf"\b{re.escape(word)}", text), f"{rel}: {word!r}"


def test_the_banned_word_scan_would_catch_an_invitation():
    text = "You can join the register and sign up here".casefold()
    assert any(re.search(rf"\b{re.escape(w)}", text) for w in BANNED_EN)
