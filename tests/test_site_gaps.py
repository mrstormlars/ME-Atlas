"""Tests for the gaps page (gaps.html, nb/gaps.html). Fictional cards and content only; no network, no AI."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_site import Node, Site, make_card, norm, page, write_card
from test_site_map import map_content, map_link

from me_atlas import cards as cardlib
from me_atlas import i18n
from me_atlas import map as maplib
from me_atlas.cards import _BANNED_NB_RE, _BANNED_RE

REPO_I18N = Path(__file__).resolve().parents[1] / "content" / "i18n"

SYMPTOMS = [
    {"id": "s-none", "name": "Fictional unlinked symptom", "sources": ["pmid:00000005"]},
    {"id": "s-assoc", "name": "Fictional associated symptom", "sources": ["pmid:00000005"]},
    {"id": "s-prop", "name": "Fictional proposed-only symptom", "sources": ["doi:10.0000/fictional.5"]},
    {"id": "s-mixed", "name": "Fictional mixed symptom", "sources": ["pmid:00000005"]},
]
QUESTIONS = [{"id": "own", "layer": "mechanism", "text": "What keeps the fictional signal low?", "editorial": True}]
BANNED_ON_PAGE = ("promising", "hopeful", "needs funding", "should be studied", "most", "best", "priority")


def cards() -> list[dict]:
    """Six cards at levels 0-5, plus a lonely one. lvl-3 is contested."""
    return [
        make_card(
            "lvl-0",
            "Fictional level 0 idea",
            0,
            layer="trigger",
            links=[
                map_link("symptom:s-prop", "A fictional review proposes a link.", "proposed", ["pmid:00000001"]),
                map_link("question:own", "A fictional review raises the question.", "proposed", ["pmid:00000002"]),
            ],
        ),
        make_card(
            "lvl-1",
            "Fictional level 1 idea",
            1,
            layer="mechanism",
            links=[
                map_link("symptom:s-prop", "A fictional case report suggests a link.", "proposed", ["pmid:00000002"]),
                map_link("symptom:s-mixed", "A fictional review proposes another.", "proposed", ["pmid:00000001"]),
                map_link("lvl-0", "A fictional review proposes a card link.", "proposed", ["pmid:00000003"]),
            ],
        ),
        make_card(
            "lvl-2",
            "Fictional level 2 idea",
            2,
            layer="mechanism",
            links=[
                map_link("symptom:s-assoc", "A fictional study measured both.", "associated", ["pmid:00000002"]),
                map_link("symptom:s-mixed", "A fictional study measured both too.", "associated", ["pmid:00000002"]),
            ],
        ),
        make_card("lvl-3", "Fictional level 3 idea", 3, contested_rungs=[3]),
        make_card("lvl-4", "Fictional level 4 idea", 4),
        make_card("lvl-5", "Fictional level 5 idea", 5),
        make_card("lonely", "Fictional lonely idea", 0),
    ]


@pytest.fixture
def gaps_site(tmp_path) -> Site:
    proj = Site(tmp_path)
    content = map_content(tmp_path, SYMPTOMS, QUESTIONS)
    for card in cards():
        write_card(proj.cards, card)
    result = proj.build(content_dir=content)
    assert result.errors == []
    proj.content_dir = content
    return proj


def section(doc: Node, section_id: str) -> list[Node]:
    """The elements of the main text after this h2 and before the next one."""
    out: list[Node] = []
    inside = False
    for node in doc.find("main").walk():
        if node.tag == "h2":
            inside = node.get("id") == section_id
            continue
        if inside:
            out.append(node)
    return out


def section_text(doc: Node, section_id: str) -> str:
    return norm(" ".join(n.text() for n in section(doc, section_id) if n.tag in ("p", "li")))


def items(doc: Node, section_id: str) -> list[str]:
    return [norm(n.text()) for n in section(doc, section_id) if n.tag == "li"]


# --- the page ---


def test_the_page_is_built_in_both_languages_with_the_navigation_entry_after_the_causal_map(gaps_site):
    out = gaps_site.out
    assert (out / "gaps.html").is_file() and (out / "nb" / "gaps.html").is_file()
    nb = i18n.load_strings(REPO_I18N / "nb.yaml")
    for rel, h1, before, after in (
        ("gaps.html", "What is missing", "Causal map", "Methods"),
        ("nb/gaps.html", "Hva mangler", nb["page.map"], nb["page.methods"]),
    ):
        doc = page(out, rel)
        assert norm(doc.find("h1").text()) == h1
        labels = [norm(a.text()) for a in doc.find("nav").find_all("a")]
        assert labels.index(h1) == labels.index(before) + 1
        assert labels.index(after) == labels.index(h1) + 1
        current = [a for a in doc.find("nav").find_all("a") if a.get("aria-current")]
        assert [norm(a.text()) for a in current] == [h1]
    for rel in ("map.html", "nb/map.html", "index.html"):
        nav = page(out, rel).find("nav")
        assert any((a.get("href") or "").endswith("gaps.html") for a in nav.find_all("a")), rel
        assert not [
            a for a in nav.find_all("a") if a.get("aria-current") and (a.get("href") or "").endswith("gaps.html")
        ]


def test_the_five_sections_have_their_ids(gaps_site):
    doc = page(gaps_site.out, "gaps.html")
    assert [h.get("id") for h in doc.find_all("h2")] == [
        None,  # the summary heading; its section carries the id
        "gaps-unlinked-symptoms",
        "gaps-step1-symptoms",
        "gaps-untested-links",
        "gaps-next-rung",
        "gaps-unlinked-cards",
    ]


# --- lists 1 and 2 ---


def test_list_1_shows_a_symptom_with_no_link_and_not_one_with_an_associated_link(gaps_site):
    doc = page(gaps_site.out, "gaps.html")
    listed = items(doc, "gaps-unlinked-symptoms")
    assert len(listed) == 1
    assert listed[0].startswith("Fictional unlinked symptom")
    assert "Listed in: pmid:00000005" in listed[0]
    assert "Fictional associated symptom" not in " ".join(listed)
    link = [n for n in section(doc, "gaps-unlinked-symptoms") if n.tag == "li"][0].find("a")
    assert link.get("href") == "map.html#symptom-s-none"


def test_list_2_shows_a_proposed_only_symptom_with_its_hypotheses_and_not_one_that_also_has_an_associated_link(
    gaps_site,
):
    doc = page(gaps_site.out, "gaps.html")
    listed = items(doc, "gaps-step1-symptoms")
    assert len(listed) == 1
    assert listed[0].startswith("Fictional proposed-only symptom")
    assert "Listed in: doi:10.0000/fictional.5" in listed[0]
    assert "Linked from: Fictional level 1 idea, Fictional level 0 idea" in listed[0]
    li = [n for n in section(doc, "gaps-step1-symptoms") if n.tag == "li"][0]
    hrefs = [a.get("href") for a in li.find_all("a")]
    assert "hypotheses/lvl-0.html" in hrefs and "hypotheses/lvl-1.html" in hrefs
    assert "Fictional mixed symptom" not in " ".join(listed)


# --- list 3 ---


def test_list_3_groups_a_proposed_link_under_its_target_with_the_maps_reference_numbers(gaps_site):
    out = gaps_site.out
    doc = page(out, "gaps.html")
    nodes = section(doc, "gaps-untested-links")
    heads = [h for h in nodes if h.tag == "h3"]
    # node order: cards first, then symptoms, then questions
    assert [norm(h.text()) for h in heads] == [
        "Fictional level 0 idea",
        "Fictional proposed-only symptom",
        "Fictional mixed symptom",
        "What keeps the fictional signal low?",
    ]
    assert heads[0].find("a").get("href") == "hypotheses/lvl-0.html"
    assert heads[1].find("a").get("href") == "map.html#symptom-s-prop"
    assert heads[3].find("a").get("href") == "map.html#question-own"
    lists = [n for n in nodes if n.tag == "ul"]
    prop = [norm(li.text()) for li in lists[1].find_all("li")]
    assert prop[1].startswith("From Fictional level 0 idea: A fictional review proposes a link. — proposed [1]")
    assert prop[0].startswith("From Fictional level 1 idea: A fictional case report suggests a link. — proposed [1]")
    # lvl-1 cites pmid:00000002 first, then 00000001: the second link carries number 2, as on the map page
    gap_li = lists[2].find_all("li")[0]
    assert norm(gap_li.text()).endswith("— proposed [2]")
    gap_refs = [a.get("href") for a in gap_li.find_all("a", "ref")]
    assert gap_refs == ["hypotheses/lvl-1.html#study-pmid:00000001"]
    map_items = page(out, "map.html").find("article", id="card-lvl-1").find_all("li")
    on_map = [li for li in map_items if "proposes another." in li.text()]
    assert len(on_map) == 1
    assert norm(on_map[0].text()).endswith("— proposed [2]")
    assert [a.get("href") for a in on_map[0].find_all("a", "ref")] == gap_refs


def test_list_3_has_the_rubric_sentence_and_no_associated_link(gaps_site):
    doc = page(gaps_site.out, "gaps.html")
    text = section_text(doc, "gaps-untested-links")
    assert "Step 2 requires a study with a recognised case definition that measured both ends" in text
    assert "A fictional study measured both" not in text


# --- list 4 ---


def test_list_4_has_a_group_for_each_level_and_a_next_rung_sentence_for_levels_0_to_4_only(gaps_site):
    doc = page(gaps_site.out, "gaps.html")
    nodes = section(doc, "gaps-next-rung")
    heads = [norm(n.text()) for n in nodes if n.tag == "h3"]
    assert heads == [
        "Level 5: Causal case built",
        "Level 4: Tested by intervention",
        "Level 3: Repeated by others",
        "Level 2: Backed in a defined group",
        "Level 1: First signs",
        "Level 0: Proposed",
    ]
    sentences = [norm(n.text()) for n in nodes if n.tag == "p" and "The next rung" in n.text()]
    assert len(sentences) == 5
    assert sentences[0].startswith("The next rung, Causal case built, requires: Several independent lines")
    assert sentences[4].startswith("The next rung, First signs, requires: One or more small or uncontrolled")
    # the level 5 group is followed directly by the level 4 heading: no requirement sentence in between
    between = []
    seen = False
    for n in nodes:
        if n.tag == "h3" and "Level 5" in n.text():
            seen = True
            continue
        if seen and n.tag == "h3":
            break
        if seen and n.tag == "p":
            between.append(n)
    assert between == []


def test_list_4_marks_a_contested_card_and_only_that_card(gaps_site):
    doc = page(gaps_site.out, "gaps.html")
    li = [n for n in section(doc, "gaps-next-rung") if n.tag == "li"]
    contested = [norm(n.text()) for n in li if "contested" in n.text()]
    assert contested == ["Fictional level 3 idea This hypothesis is contested at rung 3; the reason is on its card."]
    assert len(li) == 7
    links = {norm(n.find("a").text()): n.find("a").get("href") for n in li}
    assert links["Fictional level 5 idea"] == "hypotheses/lvl-5.html"


# --- list 5 ---


def test_list_5_shows_a_card_with_no_links_and_not_a_linked_one(gaps_site):
    doc = page(gaps_site.out, "gaps.html")
    listed = items(doc, "gaps-unlinked-cards")
    assert "Fictional lonely idea" in listed
    assert "Fictional level 0 idea" not in listed  # it links out and is linked to
    assert "Fictional level 2 idea" not in listed


# --- the counts equal the report ---


def test_the_counts_on_the_page_equal_the_map_report(gaps_site):
    loaded = [cardlib.load_card(p) for p in sorted(gaps_site.cards.glob("*.yaml"))]
    content, _ = maplib.load_content(gaps_site.content_dir)
    report = maplib.render_report(maplib.build_graph(loaded, content), loaded)
    doc = page(gaps_site.out, "gaps.html")
    for heading, section_id in (
        ("Symptoms with no link", "gaps-unlinked-symptoms"),
        ("Symptoms linked only at step 1", "gaps-step1-symptoms"),
        ("Links not yet tested in patients", "gaps-untested-links"),
        ("Hypotheses with no links yet", "gaps-unlinked-cards"),
    ):
        reported = int(re.search(rf"^{heading} \((\d+)\)$", report, re.M).group(1))
        assert f"Count: {reported}" in section_text(doc, section_id), heading
    level_lines = re.findall(r"^  Level (\d): ", report, re.M)
    assert level_lines == ["5", "4", "3", "2", "1", "0"]
    assert len([n for n in section(doc, "gaps-next-rung") if n.tag == "h3"]) == len(level_lines)


# --- wording ---


def test_no_banned_word_in_the_gaps_strings_and_only_the_quoted_rung_meaning_on_the_page_has_one(gaps_site):
    pattern = re.compile(r"\b(" + "|".join(BANNED_ON_PAGE) + r")\b", re.I)
    for name in ("en.yaml", "nb.yaml"):
        for key, value in i18n.load_strings(REPO_I18N / name).items():
            if key.startswith(("gaps.", "page.gaps")):
                assert not pattern.search(value), (key, value)
                assert not _BANNED_RE.search(value) and not _BANNED_NB_RE.search(value), key
    text = page(gaps_site.out, "gaps.html").find("main").text()
    found = {m.group(0).lower() for m in pattern.finditer(text)}
    # The existing string rung.5.meaning, quoted as the next rung of level 4, says "most of the Bradford Hill criteria".
    assert found <= {"most"}


def test_the_norwegian_page_shows_the_norwegian_strings(gaps_site):
    doc = page(gaps_site.out, "nb/gaps.html")
    nb = i18n.load_strings(REPO_I18N / "nb.yaml")
    assert [norm(h.text()) for h in doc.find_all("h2")] == [
        nb["gaps.summary.h2"],
        nb["gaps.unlinked_symptoms.h2"],
        nb["gaps.step1_symptoms.h2"],
        nb["gaps.untested.h2"],
        nb["gaps.next_rung.h2"],
        nb["gaps.unlinked_cards.h2"],
    ]
    text = norm(doc.find("main").text())
    assert "Antall: 1" in text
    assert nb["gaps.untested.rubric"] in text
    assert "Neste trinn, Første tegn, krever:" in text
    assert "omstridt på trinn 3" in text
    assert "What is missing" not in text and "contested at rung" not in text
    summary = norm(doc.find("section", id="gaps-summary").text())
    for key in (
        "gaps.summary.symptoms.caption",
        "gaps.summary.none",
        "gaps.summary.links.h3",
        "gaps.summary.levels.h3",
    ):
        assert nb[key] in summary, key
    assert nb["gaps.summary.levels.contested"].format(n=1) in summary
    assert "At a glance" not in summary and "no link yet" not in summary


# --- the summary ("At a glance") ---


def summary(rel: str, site: Site) -> Node:
    node = page(site.out, rel).find("section", id="gaps-summary")
    assert node is not None
    return node


def table_rows(sec: Node) -> dict[str, Node]:
    table = sec.find("table")
    return {norm(r.find("th").text()): r for r in table.find("tbody").find_all("tr")}


def cell_counts(row: Node) -> list[str]:
    """The count text of the three step cells, without the aria-hidden marks."""
    return [norm(td.text(frozenset({"marks"}))) for td in row.find_all("td")]


def test_the_summary_comes_after_the_intro_and_before_the_first_list_with_three_blocks_in_order(gaps_site):
    for rel in ("gaps.html", "nb/gaps.html"):
        doc = page(gaps_site.out, rel)
        main = list(doc.find("main").walk())
        sec = doc.find("section", id="gaps-summary")
        ids = [d.get("id") for d in sec.find_all("div") if d.get("id")]
        assert ids == ["gaps-summary-symptoms", "gaps-summary-links", "gaps-summary-levels"], rel
        assert sec.find("h2") is not None
        intro = next(n for n in main if n.tag == "p")
        first_list = next(n for n in main if n.tag == "h2" and n.get("id") == "gaps-unlinked-symptoms")
        assert main.index(intro) < main.index(sec) < main.index(first_list), rel


def test_symptom_table_has_a_caption_one_row_per_symptom_in_order_and_links_to_the_map(gaps_site):
    sec = summary("gaps.html", gaps_site)
    table = sec.find("table")
    assert table.find("caption") is not None
    head = table.find("thead").find_all("th")
    assert [norm(th.text()) for th in head] == ["Symptom", "proposed", "associated", "direction supported"]
    # the map's own line sample sits in each step header, hidden from screen readers
    samples = [th.find("svg") for th in head[1:]]
    assert all(s is not None and s.get("aria-hidden") == "true" for s in samples)
    assert samples[0].find("line").get("stroke-dasharray") and not samples[1].find("line").get("stroke-dasharray")
    assert samples[2].find("line").get("stroke-width") == "3.5"
    rows = list(table_rows(sec))
    assert [r.removesuffix(" no link yet") for r in rows] == [s["name"] for s in SYMPTOMS]
    assert table.find("tbody").find_all("tr")[0].find("a").get("href") == "map.html#symptom-s-none"


def test_a_symptom_with_no_link_is_marked_and_one_with_an_associated_link_is_not_and_shows_1(gaps_site):
    rows = table_rows(summary("gaps.html", gaps_site))
    none = rows["Fictional unlinked symptom no link yet"]
    assert "gaps-row-none" in none.classes
    assert cell_counts(none) == ["0", "0", "0"]
    assoc = rows["Fictional associated symptom"]
    assert "gaps-row-none" not in assoc.classes
    assert cell_counts(assoc) == ["0", "1", "0"]
    assert "no link yet" not in assoc.text()
    assert cell_counts(rows["Fictional mixed symptom"]) == ["1", "1", "0"]
    assert cell_counts(rows["Fictional proposed-only symptom"]) == ["2", "0", "0"]
    # one mark per link, styled by step, and hidden from screen readers
    marks = rows["Fictional proposed-only symptom"].find_all("span", "mk")
    assert len(marks) == 2
    assert all(m.parent.get("aria-hidden") == "true" for m in marks)
    assert all("mk-proposed" in m.classes for m in marks)


def test_the_link_bar_omits_a_step_with_no_links_but_the_text_says_0(gaps_site):
    sec = summary("gaps.html", gaps_site).find("div", id="gaps-summary-links")
    bar = sec.find("div", "gaps-linkbar")
    assert bar.get("aria-hidden") == "true"
    segments = [s for s in bar.find_all("span")]
    kinds = [next(c for c in s.classes if c.startswith("mk-") and c != "mk-seg") for s in segments]
    assert kinds == ["mk-proposed", "mk-associated"]  # no directional segment
    assert [s.get("style") for s in segments] == ["flex-grow: 5", "flex-grow: 2"]
    assert [norm(li.text()) for li in sec.find_all("li")] == ["proposed: 5", "associated: 2", "direction supported: 0"]
    assert "All links on the causal map: 7." in norm(sec.text())
    assert sec.find("a").get("href") == "#gaps-untested-links"


@pytest.fixture
def gaps_site_no_level_4(tmp_path) -> Site:
    proj = Site(tmp_path)
    content = map_content(tmp_path, SYMPTOMS, QUESTIONS)
    for card in cards():
        if card["slug"] != "lvl-4":
            write_card(proj.cards, card)
    assert proj.build(content_dir=content).errors == []
    return proj


def level_items(site: Site, rel: str = "gaps.html") -> list[Node]:
    return summary(rel, site).find("div", id="gaps-summary-levels").find_all("li")


def test_the_level_block_shows_all_six_levels_in_ladder_order_and_a_level_without_a_card_shows_0(
    gaps_site_no_level_4,
):
    lis = level_items(gaps_site_no_level_4)
    assert len(lis) == 6
    texts = [norm(li.text()) for li in lis]
    assert [t.split(" ")[:2] for t in texts] == [["Level", str(k)] for k in range(6)]
    assert [norm(li.find("strong").text()) for li in lis] == [
        "Cards: 2",
        "Cards: 1",
        "Cards: 1",
        "Cards: 1",
        "Cards: 0",
        "Cards: 1",
    ]
    assert "Proposed" in texts[0] and "Causal case built" in texts[5]
    assert lis[4].find("span", "gl-fill") is None  # no bar for 0
    assert all(li.find("span", "gl-fill") is not None for i, li in enumerate(lis) if i != 4)
    assert "1 contested" in texts[3]
    assert not any("contested" in t for i, t in enumerate(texts) if i != 3)
    block = summary("gaps.html", gaps_site_no_level_4).find("div", id="gaps-summary-levels")
    assert block.find("a").get("href") == "#gaps-next-rung"


def test_the_summary_numbers_equal_the_lists(gaps_site):
    doc = page(gaps_site.out, "gaps.html")
    sec = summary("gaps.html", gaps_site)
    rows = list(table_rows(sec).values())
    unlinked = [r for r in rows if "gaps-row-none" in r.classes]
    assert len(unlinked) == len(items(doc, "gaps-unlinked-symptoms")) == 1
    proposed_only = [r for r in rows if cell_counts(r)[0] != "0" and cell_counts(r)[1:] == ["0", "0"]]
    assert len(proposed_only) == len(items(doc, "gaps-step1-symptoms")) == 1
    links = sec.find("div", id="gaps-summary-links")
    proposed_total = int(norm(links.find_all("li")[0].text()).split(": ")[1])
    listed = [li for n in section(doc, "gaps-untested-links") if n.tag == "ul" for li in n.find_all("li")]
    assert proposed_total == len(listed) == 5
    per_level: dict[int, int] = {}
    level = -1
    for n in section(doc, "gaps-next-rung"):
        if n.tag == "h3":
            level = int(norm(n.text()).split(":")[0].split(" ")[1])
            per_level[level] = 0
        elif n.tag == "li":
            per_level[level] += 1
    shown = {k: int(norm(li.find("strong").text()).split(": ")[1]) for k, li in enumerate(level_items(gaps_site))}
    assert shown == {k: per_level.get(k, 0) for k in range(6)}


def test_the_summary_has_no_judging_word(gaps_site):
    pattern = re.compile(r"\b(" + "|".join(BANNED_ON_PAGE) + r")\b", re.I)
    for rel in ("gaps.html", "nb/gaps.html"):
        assert not pattern.search(summary(rel, gaps_site).text()), rel
