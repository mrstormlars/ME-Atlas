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
