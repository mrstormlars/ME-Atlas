"""Tests for the open data and citation export (me_atlas.export and the data/ folder of the build).

Cards are fictional; the build runs in tmp_path. No network, no LLM.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
from pathlib import Path

import pytest
import yaml
from test_site import REPO_ROOT, TODAY, Site, add_study, base, make_card, norm, page, write_card
from test_site_gaps import QUESTIONS, SYMPTOMS
from test_site_map import map_content, map_link

from me_atlas import cards as cardlib
from me_atlas import export, site
from me_atlas import map as maplib

ODD_TITLE = "Fictional {braces} with 50% of widgets & gadgets $5 #1 a_b ~c ^d \\e"


def fictional_cards() -> list[dict]:
    first = make_card(
        "first-idea",
        "Fictional first idea",
        3,
        contested_rungs=[3],
        layer="mechanism",
        links=[
            map_link("symptom:s-assoc", 'A fictional study, "quoted", measured both.', "associated", ["pmid:00000002"]),
            map_link("second-idea", "A fictional review proposes a link.", "proposed", ["pmid:00000001"]),
        ],
    )
    first["studies"][0]["title"] = ODD_TITLE
    first["studies"][1]["group"] = "Fictional group; Fictional institute"
    second = make_card("second-idea", "Second fictional idea, with a comma", 1)
    second["badges"]["explains_pem"] = {"value": False, "reason": None}
    return [first, second]


@pytest.fixture
def data_site(tmp_path) -> Site:
    proj = Site(tmp_path)
    content = map_content(tmp_path, SYMPTOMS, QUESTIONS)
    for card in fictional_cards():
        write_card(proj.cards, card)
    result = proj.build(content_dir=content)
    assert result.errors == []
    return proj


def read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"), newline="")))


def loaded(cards_data: list[dict]) -> list[cardlib.Card]:
    return [cardlib.Card.model_validate(c) for c in cards_data]


# --- a small BibTeX and RIS reader, so the tests check the files and not the writer -----


def read_bib(text: str) -> list[tuple[str, str, dict[str, str]]]:
    """Entries as (type, key, fields). Braces must balance; a backslash-escaped brace is not counted."""
    entries = []
    pos = 0
    while True:
        at = text.find("@", pos)
        if at < 0:
            return entries
        m = re.compile(r"@(\w+)\{([^,\s]+),\n").match(text, at)
        assert m, text[at : at + 40]
        depth, i = 1, m.end()
        while depth:
            ch = text[i]
            if ch == "\\":
                i += 2
                continue
            depth += {"{": 1, "}": -1}.get(ch, 0)
            i += 1
        body = text[m.end() : i - 1]
        fields: dict[str, str] = {}
        for line in body.strip().splitlines():
            f = re.fullmatch(r"\s*(\w+) = \{(.*)\},?", line)
            assert f, line
            fields[f.group(1)] = f.group(2)
        entries.append((m.group(1), m.group(2), fields))
        pos = i


def read_ris(text: str) -> list[list[tuple[str, str]]]:
    assert "\n" not in text.replace("\r\n", "")  # every line end is CRLF
    records: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] | None = None
    for line in text.split("\r\n"):
        if not line:
            continue
        m = re.fullmatch(r"([A-Z][A-Z0-9])  - (.*)", line)
        assert m, repr(line)
        tag, value = m.groups()
        if current is None:
            assert tag == "TY", line  # every record starts with TY
            current = []
        current.append((tag, value))
        if tag == "ER":
            records.append(current)
            current = None
    assert current is None  # every record ends with ER
    return records


# --- BibTeX ---


def study(sid: str, **over) -> cardlib.Study:
    return cardlib.Study.model_validate(add_study(base(), sid, "CCC", **over))


def test_bibtex_escapes_the_special_characters_in_a_title_so_the_entry_parses():
    s = study("pmid:00000007", title=ODD_TITLE)
    text = export.bibtex([s], site.study_url)
    ((typ, key, fields),) = read_bib(text)
    assert (typ, key) == ("misc", "pmid00000007")
    assert fields["title"] == (
        r"Fictional \{braces\} with 50\% of widgets \& gadgets \$5 \#1 a\_b "
        r"\textasciitilde{}c \textasciicircum{}d \textbackslash{}e"
    )
    # Negative input: nothing in the title is left unescaped.
    assert re.search(r"(?<!\\)[%&$#_~^]", fields["title"]) is None
    assert re.search(r"(?<!\\)[{}]", fields["title"].replace(r"\textasciitilde{}", "").replace(r"{}", "")) is None


def test_bibtex_has_one_entry_per_study_in_order_with_the_expected_fields_and_no_author_or_journal():
    a, b = study("pmid:00000011"), study("doi:10.0000/fictional.1", title="Second", year=2020)
    entries = read_bib(export.bibtex([a, b], site.study_url))
    assert [e[1] for e in entries] == ["pmid00000011", "doi10.0000/fictional.1"]
    assert entries[0][2] == {
        "title": a.title,
        "year": "2006",
        "url": "https://pubmed.ncbi.nlm.nih.gov/00000011/",
        "note": "PMID: 00000011",
    }
    assert entries[1][2] == {
        "title": "Second",
        "year": "2020",
        "url": "https://doi.org/10.0000/fictional.1",
        "doi": "10.0000/fictional.1",
    }
    assert all("author" not in e[2] and "journal" not in e[2] for e in entries)


def test_bibtex_of_a_card_without_studies_is_empty():
    assert export.bibtex([], site.study_url) == ""


# --- RIS ---


def test_ris_has_one_record_per_study_with_crlf_and_the_expected_tags():
    a = study("pmid:00000011")
    p = study("doi:10.0000/fictional.2", title="A preprint", preprint=True, role="early_signal")
    text = export.ris([a, p], site.study_url)
    records = read_ris(text)
    assert records[0] == [
        ("TY", "JOUR"),
        ("TI", a.title),
        ("PY", "2006"),
        ("UR", "https://pubmed.ncbi.nlm.nih.gov/00000011/"),
        ("AN", "PMID:00000011"),
        ("ER", ""),
    ]
    assert records[1] == [
        ("TY", "UNPB"),
        ("TI", "A preprint"),
        ("PY", "2006"),
        ("UR", "https://doi.org/10.0000/fictional.2"),
        ("DO", "10.0000/fictional.2"),
        ("ER", ""),
    ]
    assert text.endswith("ER  - \r\n\r\n")


def test_the_ris_reader_rejects_a_record_without_er_and_a_bad_tag():
    with pytest.raises(AssertionError):
        read_ris("TY  - JOUR\r\nTI  - x\r\n")
    with pytest.raises(AssertionError):
        read_ris("TY  - JOUR\r\nT  - x\r\nER  - \r\n")
    with pytest.raises(AssertionError):
        read_ris("TI  - x\r\nER  - \r\n")


# --- the built data folder -----


def test_the_build_writes_the_data_folder_next_to_static_and_not_per_language(data_site):
    out = data_site.out
    for name in export.DATA_FILES:
        assert (out / "data" / name).is_file(), name
    assert not (out / "nb" / "data").exists()
    for slug in ("first-idea", "second-idea"):
        for ext in ("bib", "ris"):
            assert (out / "data" / "citations" / f"{slug}.{ext}").is_file()
    assert (out / "static").is_dir()


def test_card_format_is_a_byte_copy_of_the_document(data_site):
    copy = (data_site.out / "data" / "card-format.md").read_bytes()
    assert copy == (REPO_ROOT / "docs" / "card-format.md").read_bytes()


def test_a_missing_card_format_document_stops_the_build_and_writes_nothing(tmp_path):
    proj = Site(tmp_path)
    write_card(proj.cards, make_card("first-idea", "Fictional first idea", 2))
    result = proj.build(card_format=tmp_path / "nope.md")
    assert result.errors and "card-format" in result.errors[0]
    assert not proj.out.exists()


def test_the_json_holds_every_card_field_the_dataset_block_and_the_map_content(data_site):
    doc = json.loads((data_site.out / "data" / "me-atlas.json").read_text(encoding="utf-8"))
    assert [c["slug"] for c in doc["cards"]] == ["first-idea", "second-idea"]
    for c in doc["cards"]:
        assert list(c) == list(cardlib.Card.model_fields)
        assert all(list(s) == list(cardlib.Study.model_fields) for s in c["studies"])
    assert doc["cards"][0]["studies"][0]["title"] == ODD_TITLE  # unescaped: only the BibTeX is escaped
    ds = doc["dataset"]
    assert ds["version"] == TODAY.isoformat()
    assert ds["licence"] == "CC-BY-4.0" and ds["licence_url"].startswith("https://creativecommons.org/")
    assert ds["draft_preview"] is False
    assert "No medical or research expert has reviewed" in ds["review_statement"]
    assert "English is authoritative" in ds["language_note"] and "translations/nb/" in ds["language_note"]
    assert "rights holders" in ds["rights_note"]
    assert ds["citation"] == export.citation_text(TODAY.isoformat())
    assert doc["symptoms"][0] == {"id": "s-none", "name": "Fictional unlinked symptom"}
    assert doc["questions"] == [{"id": "own", "text": "What keeps the fictional signal low?"}]


def test_counts_equal_the_csv_row_counts(data_site):
    data = data_site.out / "data"
    counts = json.loads((data / "me-atlas.json").read_text(encoding="utf-8"))["dataset"]["counts"]
    studies = read_csv(data / "studies.csv")
    assert counts == {
        "cards": len(read_csv(data / "hypotheses.csv")),
        "study_rows": len(studies),
        "distinct_studies": len({r["id"] for r in studies}),
        "links": len(read_csv(data / "links.csv")),
    }
    assert counts["cards"] == 2 and counts["links"] == 2
    # Both cards cite the same studies: rows are summed over cards, the distinct count is not.
    assert counts["study_rows"] == 2 * len(base()["studies"])
    assert counts["distinct_studies"] == len(base()["studies"])


def test_counts_of_cards_and_links_equal_what_the_gaps_page_shows(data_site):
    doc = page(data_site.out, "gaps.html")
    text = norm(doc.text())
    counts = json.loads((data_site.out / "data" / "me-atlas.json").read_text(encoding="utf-8"))["dataset"]["counts"]
    assert counts["links"] == int(re.search(r"All links on the causal map: (\d+)\.", text).group(1))
    assert counts["cards"] == sum(int(n) for n in re.findall(r"Cards: (\d+)", text))
    assert counts["cards"] == len(doc.find("table", cls="gaps-counts").find("tbody").find_all("tr"))


def test_hypotheses_csv_has_one_row_per_card_with_levels_badges_and_counts(data_site):
    rows = {r["slug"]: r for r in read_csv(data_site.out / "data" / "hypotheses.csv")}
    first = rows["first-idea"]
    assert list(first) == list(export.HYPOTHESES_COLUMNS)
    assert (first["level"], first["layer"], first["contested_rungs"]) == ("3", "mechanism", "3")
    assert first["links_out"] == "2" and first["long_covid"] == "true"
    assert rows["second-idea"]["name"] == "Second fictional idea, with a comma"  # RFC 4180 quoting round-trips
    assert rows["second-idea"]["explains_pem"] == "false" and rows["second-idea"]["layer"] == ""
    assert rows["second-idea"]["contested_rungs"] == ""


def test_studies_csv_has_one_row_per_study_per_card_with_every_study_field(data_site):
    rows = read_csv(data_site.out / "data" / "studies.csv")
    assert list(rows[0]) == ["card", *cardlib.Study.model_fields]
    assert list(export.STUDIES_COLUMNS) == ["card", *cardlib.Study.model_fields]
    mine = [r for r in rows if r["card"] == "first-idea"]
    assert len(mine) == len(base()["studies"])
    assert mine[0]["title"] == ODD_TITLE
    assert mine[1]["group"] == "Fictional group; Fictional institute"
    assert mine[0]["preprint"] == "false" and mine[0]["preregistered"] in ("true", "false", "")


def test_links_csv_has_the_target_kind_and_name_and_joins_sources(data_site):
    rows = read_csv(data_site.out / "data" / "links.csv")
    by_target = {r["target"]: r for r in rows}
    assert by_target["symptom:s-assoc"]["target_kind"] == "symptom"
    assert by_target["symptom:s-assoc"]["target_name"] == "Fictional associated symptom"
    assert by_target["symptom:s-assoc"]["text"] == 'A fictional study, "quoted", measured both.'
    assert by_target["second-idea"]["target_kind"] == "card"
    assert by_target["second-idea"]["target_name"] == "Second fictional idea, with a comma"
    assert by_target["second-idea"]["support"] == "proposed"
    assert by_target["second-idea"]["sources"] == "pmid:00000001"
    raw = (data_site.out / "data" / "links.csv").read_bytes()
    assert raw.count(b"\r\n") == len(rows) + 1 and not raw.startswith(b"\xef\xbb\xbf")


def test_the_built_bib_and_ris_files_parse_and_hold_one_entry_per_study_in_card_order(data_site):
    card = fictional_cards()[0]
    ids = [s["id"] for s in card["studies"]]
    bib = read_bib((data_site.out / "data" / "citations" / "first-idea.bib").read_text(encoding="utf-8"))
    assert [e[1] for e in bib] == [i.replace(":", "") for i in ids]
    assert bib[0][2]["title"].startswith(r"Fictional \{braces\} with 50\% of widgets \& gadgets")
    ris = read_ris((data_site.out / "data" / "citations" / "first-idea.ris").read_bytes().decode("utf-8"))
    expected = [("AN", f"PMID:{i[5:]}") if i.startswith("pmid:") else ("DO", i[4:]) for i in ids]
    assert [next(kv for kv in r if kv[0] in ("AN", "DO")) for r in ris] == expected
    assert dict(ris[0])["TI"] == ODD_TITLE  # RIS needs no escaping


# --- pages and links -----


def hrefs(doc) -> list[str]:
    return [a.get("href") for a in doc.find_all("a")]


@pytest.mark.parametrize("prefix", ["", "nb/"])
def test_every_card_page_links_to_its_two_citation_files_and_the_data_page(data_site, prefix):
    out = data_site.out
    for slug in ("first-idea", "second-idea"):
        rel = f"{prefix}hypotheses/{slug}.html"
        doc = page(out, rel)
        heading = [h for h in doc.find_all("h2") if norm(h.text()) in ("Studies", "Studier")][0]
        siblings = heading.parent.children
        after = siblings[siblings.index(heading) + 1 :]
        para = next(n for n in after if hasattr(n, "classes") and "data-links" in n.classes)
        links = hrefs(para)
        depth = "../" * rel.count("/")
        assert links[:2] == [f"{depth}data/citations/{slug}.bib", f"{depth}data/citations/{slug}.ris"]
        for href in links:
            target = (out / rel).parent / href.split("#")[0]
            assert target.resolve().exists(), (rel, href)
        assert links[2] == "../data.html"


@pytest.mark.parametrize("prefix", ["", "nb/"])
def test_every_page_footer_links_to_the_data_page_and_the_nav_does_not(data_site, prefix):
    out = data_site.out
    pages = [p for p in (out / prefix.rstrip("/") if prefix else out).glob("**/*.html")]
    if not prefix:
        pages = [p for p in pages if p.relative_to(out).parts[0] != "nb"]
    assert len(pages) >= 7
    for path in pages:
        rel = path.relative_to(out).as_posix()
        doc = page(out, rel)
        footer_links = hrefs(doc.find("footer"))
        up = "../" * (path.relative_to(out / prefix.rstrip("/") if prefix else out).as_posix().count("/"))
        assert f"{up}data.html" in footer_links, rel
        assert "data.html" not in " ".join(hrefs(doc.find("nav"))), rel


@pytest.mark.parametrize("prefix", ["", "nb/"])
def test_the_data_page_lists_every_file_and_one_line_per_card_and_all_its_links_resolve(data_site, prefix):
    out = data_site.out
    rel = f"{prefix}data.html"
    doc = page(out, rel)
    up = "../" if prefix else ""
    links = hrefs(doc.find("main"))
    for name in export.DATA_FILES:
        assert f"{up}data/{name}" in links, name
    for slug in ("first-idea", "second-idea"):
        assert f"{up}data/citations/{slug}.bib" in links and f"{up}data/citations/{slug}.ris" in links
    assert len(doc.find("ul", cls="data-citations").find_all("li")) == 2
    for href in links:
        if href.startswith("http"):
            continue
        assert ((out / rel).parent / href).resolve().exists(), href
    text = norm(doc.find("main").text())
    assert "CC BY 4.0" in text and export.citation_text(TODAY.isoformat()) in text
    assert "card-format.md" in text


def test_the_data_page_says_what_the_data_is_in_each_language(data_site):
    en = norm(page(data_site.out, "data.html").find("main").text())
    assert "English only" in en and "No medical or research expert has reviewed" in en
    assert "gives no treatment advice" in en and "derived by code" in en
    nb = norm(page(data_site.out, "nb/data.html").find("main").text())
    assert "bare på engelsk" in nb and "Ingen medisinsk eller forskningsfaglig ekspert" in nb
    assert "ingen behandlingsråd" in nb
    assert page(data_site.out, "data.html").find("h1").text() == "Download the data"
    assert page(data_site.out, "nb/data.html").find("h1").text() == "Last ned dataene"


# --- the README and the draft preview -----


def test_the_readme_gives_date_licence_citation_and_one_line_per_file_and_points_to_card_format(data_site):
    text = (data_site.out / "data" / "README.txt").read_text(encoding="utf-8")
    assert TODAY.isoformat() in text and "CC-BY-4.0" in text and export.citation_text(TODAY.isoformat()) in text
    for name in export.DATA_FILES:
        assert len([ln for ln in text.splitlines() if ln.startswith(name)]) == 1, name
    assert "citations/" in text and "card-format.md" in text
    assert "DRAFT PREVIEW" not in text


def test_a_public_build_is_not_a_draft_preview_and_a_drafts_build_is_marked_in_json_and_readme(tmp_path):
    proj = Site(tmp_path)
    write_card(proj.cards, make_card("first-idea", "Fictional first idea", 2))
    write_card(proj.drafts, make_card("draft-only", "Fictional draft only idea", 0))
    assert proj.build().errors == []
    public = json.loads((proj.out / "data" / "me-atlas.json").read_text(encoding="utf-8"))
    assert public["dataset"]["draft_preview"] is False
    assert [c["slug"] for c in public["cards"]] == ["first-idea"]
    assert "DRAFT PREVIEW" not in (proj.out / "data" / "README.txt").read_text(encoding="utf-8")
    assert not (proj.out / "data" / "citations" / "draft-only.bib").exists()
    assert proj.build(drafts=True).errors == []
    draft = json.loads((proj.out / "data" / "me-atlas.json").read_text(encoding="utf-8"))
    assert draft["dataset"]["draft_preview"] is True
    assert [c["slug"] for c in draft["cards"]] == ["draft-only", "first-idea"]
    assert "DRAFT PREVIEW" in (proj.out / "data" / "README.txt").read_text(encoding="utf-8")
    assert (proj.out / "data" / "citations" / "draft-only.bib").exists()
    assert "draft preview" in norm(page(proj.out, "data.html").find("main").text())


def test_the_data_files_and_the_data_pages_have_no_doi_and_no_zenodo(data_site):
    out = data_site.out
    texts = [
        p.read_bytes().decode("utf-8") for p in sorted((out / "data").rglob("*")) if p.is_file() and p.suffix != ".md"
    ]
    texts += [(out / "data.html").read_text(encoding="utf-8"), (out / "nb" / "data.html").read_text(encoding="utf-8")]
    texts.append((REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    assert len(texts) > 6
    for text in texts:
        assert "10.5281" not in text
        assert "zenodo" not in text.lower()


# --- CITATION.cff -----


def test_citation_cff_is_valid_yaml_with_the_required_keys_and_no_doi():
    cff = yaml.safe_load((REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    for key in ("cff-version", "message", "title", "authors"):
        assert key in cff, key
    assert cff["cff-version"] == "1.2.0"
    assert cff["authors"] == [{"name": "ME Atlas contributors"}]
    assert cff["repository-code"] == export.REPO_URL and cff["url"] == export.SITE_URL
    assert cff["license"] == "CC-BY-4.0"
    assert "doi" not in cff and "identifiers" not in cff
    en = yaml.safe_load((REPO_ROOT / "content" / "i18n" / "en.yaml").read_text(encoding="utf-8"))
    lead = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", lambda m: m.group(1) or "", en["index.lead"])
    assert cff["abstract"] == lead
    assert not (REPO_ROOT / ".zenodo.json").exists()


# --- the export functions on their own -----


def test_counts_function_counts_rows_distinct_studies_and_graph_links():
    cards = loaded(fictional_cards())
    content = maplib.MapContent(symptoms=(maplib.Symptom(id="s-assoc", name="X", sources=["pmid:00000005"]),))
    graph = maplib.build_graph(cards, content)
    n = export.counts(cards, graph)
    assert n == {
        "cards": 2,
        "study_rows": 2 * len(base()["studies"]),
        "distinct_studies": len(base()["studies"]),
        "links": 2,
    }


def test_bib_key_replaces_the_colon_and_characters_a_key_cannot_hold():
    assert export.bib_key("pmid:123") == "pmid123"
    assert export.bib_key("doi:10.1000/a b,c{d}") == "doi10.1000/a_b_c_d_"


def test_dataset_json_uses_the_build_date_as_version():
    text, n = export.dataset_json([], maplib.MapContent(), built=dt.date(2027, 1, 2).isoformat(), draft_preview=False)
    doc = json.loads(text)
    assert doc["dataset"]["version"] == "2027-01-02" and doc["cards"] == [] and n["cards"] == 0
    assert doc["dataset"]["citation"].startswith("ME Atlas contributors (2027).")
