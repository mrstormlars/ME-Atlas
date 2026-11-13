"""Tests for the causal map page (map.html) and for the card pages staying unchanged. Fictional cards and content only;
no network, no AI. The Norwegian side is tested in test_site_languages.py.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from test_site import (
    REPO_ROOT,
    Node,
    Site,
    built,
    external_resource_refs,
    make_card,
    norm,
    page,
    parse,
    write_card,
    write_yaml,
)

MAP_SYMPTOMS = [{"id": "fatigue", "name": "Fictional fatigue", "sources": ["pmid:00000005", "doi:10.0000/fictional.5"]}]
MAP_QUESTIONS = [
    {"id": "own", "layer": "mechanism", "text": "What keeps the fictional widget signal low?", "editorial": True},
    {"id": "asked", "layer": "trigger", "text": "What starts the fictional change?", "asked_by": ["pmid:00000006"]},
]


def map_link(to: str, text: str, support: str = "proposed", sources=("pmid:00000001",)) -> dict:
    return {"to": to, "support": support, "text": text, "sources": list(sources)}


def map_content(root: Path, symptoms=MAP_SYMPTOMS, questions=MAP_QUESTIONS) -> Path:
    """The real fixed texts (the templates need them) plus fictional symptoms and questions, never the real ones."""
    folder = root / "content"
    for part in ("i18n", "methods"):
        shutil.copytree(REPO_ROOT / "content" / part, folder / part)
    if symptoms is not None:
        write_yaml(folder / "symptoms.yaml", symptoms)
    if questions is not None:
        write_yaml(folder / "open-questions.yaml", questions)
    return folder


def map_cards() -> list[dict]:
    root = make_card(
        "root-idea",
        "Fictional root idea",
        2,
        layer="predisposition",
        links=[
            map_link("middle-idea", "A fictional review proposes that the root idea feeds the middle idea."),
            map_link("symptom:fatigue", "A fictional review links the root idea to fatigue."),
        ],
    )
    middle = make_card(
        "middle-idea",
        "Fictional middle idea",
        1,
        layer="mechanism",
        links=[
            map_link(
                "symptom:fatigue",
                "A fictional study of 40 patients measured both and found them related.",
                "associated",
                ["pmid:00000002", "pmid:00000001"],
            )
        ],
    )
    loose = make_card("loose-idea", "Fictional loose idea", 0)
    return [root, middle, loose]


@pytest.fixture
def proj(tmp_path) -> Site:
    return Site(tmp_path)


@pytest.fixture
def map_site(proj, tmp_path) -> Site:
    content = map_content(tmp_path)
    for card in map_cards():
        write_card(proj.cards, card)
    assert proj.build(content_dir=content).errors == []
    return proj


def layer_headings(doc: Node) -> list[Node]:
    return [h for h in doc.find_all("h2") if (h.get("id") or "").startswith("layer-")]


def section_of(doc: Node, node_id: str) -> str | None:
    """The id of the layer heading that precedes the element with this id on the map page."""
    heading = None
    for node in doc.find("main").walk():
        if node.tag == "h2" and (node.get("id") or "").startswith("layer-"):
            heading = node.get("id")
        if node.get("id") == node_id:
            return heading
    raise AssertionError(node_id)


# --- the page ---


def test_the_map_page_is_built_in_both_languages_with_the_navigation_entry_after_what_changed(map_site):
    out = map_site.out
    assert (out / "map.html").is_file() and (out / "nb" / "map.html").is_file()
    doc = page(out, "map.html")
    assert norm(doc.find("h1").text()) == "Causal map"
    labels = [norm(a.text()) for a in doc.find("nav").find_all("a")]
    assert labels.index("Causal map") == labels.index("What changed") + 1
    current = [a for a in doc.find("nav").find_all("a") if a.get("aria-current")]
    assert [norm(a.text()) for a in current] == ["Causal map"]


def test_the_map_intro_says_second_view_own_scale_and_several_conditions(map_site):
    intro = norm(page(map_site.out, "map.html").find("main").find_all("p")[0].text())
    assert "second view" in intro
    assert "graded on its own scale" in intro or "on its own scale" in intro
    assert "ME/CFS may be several conditions with different triggers that meet further downstream" in intro


def test_the_map_has_a_section_per_layer_and_one_for_cards_not_yet_placed(map_site):
    headings = layer_headings(page(map_site.out, "map.html"))
    assert [h.get("id") for h in headings] == [
        "layer-predisposition",
        "layer-trigger",
        "layer-mechanism",
        "layer-dysfunction",
        "layer-symptom",
        "layer-unplaced",
    ]
    assert [norm(h.text()) for h in headings] == [
        "Predisposition",
        "Trigger",
        "Perpetuating mechanism",
        "Measurable dysfunction",
        "Symptom",
        "Not yet placed",
    ]


def test_every_card_is_listed_under_its_layer_as_a_link_to_its_page(map_site):
    doc = page(map_site.out, "map.html")
    assert section_of(doc, "card-root-idea") == "layer-predisposition"
    assert section_of(doc, "card-middle-idea") == "layer-mechanism"
    assert section_of(doc, "card-loose-idea") == "layer-unplaced"
    heading = doc.find("article", id="card-middle-idea").find("h3")
    assert heading.find("a").get("href") == "hypotheses/middle-idea.html"
    assert norm(heading.text()) == "Fictional middle idea"


def test_the_not_yet_placed_section_is_left_out_when_every_card_has_a_layer(proj, tmp_path):
    content = map_content(tmp_path)
    write_card(proj.cards, make_card("placed", "Fictional placed", 1, layer="trigger"))
    assert proj.build(content_dir=content).errors == []
    assert page(proj.out, "map.html").find("h2", id="layer-unplaced") is None


def test_a_link_is_a_sentence_with_the_support_label_and_numbered_references_to_the_study_anchors(map_site):
    doc = page(map_site.out, "map.html")
    items = doc.find("article", id="card-middle-idea").find_all("li")
    assert len(items) == 1
    sentence = norm(items[0].text())
    assert "A fictional study of 40 patients measured both and found them related. — associated [1] [2]" in sentence
    refs = items[0].find_all("a", "ref")
    assert [a.get("href") for a in refs] == [
        "hypotheses/middle-idea.html#study-pmid:00000002",
        "hypotheses/middle-idea.html#study-pmid:00000001",
    ]
    card_page = page(map_site.out, "hypotheses/middle-idea.html")
    for a in refs:
        assert card_page.find(id=a.get("href").split("#")[1]) is not None  # the anchor exists on the card page


def test_each_support_step_has_its_own_label(proj, tmp_path):
    content = map_content(tmp_path)
    links = [
        map_link("symptom:fatigue", "One.", "proposed"),
        map_link("question:own", "Two.", "associated"),
        map_link("question:asked", "Three.", "directional", ["pmid:00000002"]),
    ]
    write_card(proj.cards, make_card("labels", "Fictional labels", 1, layer="trigger", links=links))
    assert proj.build(content_dir=content).errors == []
    items = page(proj.out, "map.html").find("article", id="card-labels").find_all("li")
    assert [norm(li.text()).split(": ", 1)[1].split(" [")[0] for li in items] == [
        "One. — proposed",
        "Two. — associated",
        "Three. — direction supported",
    ]


def test_a_link_names_its_target_and_points_at_it(map_site):
    doc = page(map_site.out, "map.html")
    first, second = doc.find("article", id="card-root-idea").find_all("li")
    assert norm(first.text()).startswith("To Fictional middle idea: ")
    assert first.find("a").get("href") == "hypotheses/middle-idea.html"
    assert norm(second.text()).startswith("To Fictional fatigue: ")
    assert second.find("a").get("href") == "#symptom-fatigue"
    assert doc.find(id="symptom-fatigue") is not None


def test_a_card_with_no_links_says_so(map_site):
    article = page(map_site.out, "map.html").find("article", id="card-loose-idea")
    assert "No links from this hypothesis yet." in norm(article.text())


def test_symptom_nodes_show_the_name_and_link_their_sources_to_pubmed_and_doi(map_site):
    node = page(map_site.out, "map.html").find(id="symptom-fatigue")
    assert norm(node.text()).startswith("Fictional fatigue")
    assert [a.get("href") for a in node.find_all("a")] == [
        "https://pubmed.ncbi.nlm.nih.gov/00000005/",
        "https://doi.org/10.0000/fictional.5",
    ]


def test_an_editorial_question_is_labelled_as_the_teams_own_and_a_sourced_one_says_where_it_was_asked(map_site):
    doc = page(map_site.out, "map.html")
    own = doc.find(id="question-own")
    assert "What keeps the fictional widget signal low?" in norm(own.text())
    assert "This project's own question, not asked in a publication" in norm(own.text()) and "Asked in" not in norm(
        own.text()
    )
    asked = doc.find(id="question-asked")
    assert "Asked in: pmid:00000006" in norm(asked.text())
    assert asked.find("a").get("href") == "https://pubmed.ncbi.nlm.nih.gov/00000006/"
    assert "own question" not in norm(asked.text())
    assert section_of(doc, "question-own") == "layer-mechanism"
    assert section_of(doc, "question-asked") == "layer-trigger"


def test_the_convergence_lists_print_the_counts(map_site):
    doc = page(map_site.out, "map.html")
    assert norm(doc.find("h2", id="common-mechanisms").text()) == "Candidate common mechanisms"
    assert norm(doc.find("h2", id="roots").text()) == "Candidate roots"
    lists = [n for n in doc.find("main").children if isinstance(n, Node) and "map-convergence" in n.classes]
    assert [norm(li.text()) for li in lists[0].find_all("li")] == [
        "Fictional fatigue — 2 incoming links from different hypotheses"
    ]
    assert [norm(li.text()) for li in lists[1].find_all("li")] == ["Fictional root idea — 2 links out"]


def test_the_convergence_lists_are_empty_when_nothing_converges(proj):
    out = built(proj, make_card("lonely", "Fictional lonely", 1))
    assert norm(page(out, "map.html").text()).count("None yet.") == 2


def test_the_map_page_draws_only_inline_svg_and_loads_nothing_external(map_site):
    html = (map_site.out / "map.html").read_text(encoding="utf-8")
    doc = parse(html)
    assert doc.find_all("svg")
    assert not any(doc.find_all(tag) for tag in ("canvas", "img", "object", "embed"))
    assert external_resource_refs(html) == []


# --- inputs ---


def test_without_the_content_files_the_map_still_builds_with_no_symptom_or_question_nodes(proj, tmp_path):
    content = map_content(tmp_path, symptoms=None, questions=None)
    write_card(proj.cards, make_card("a-card", "Fictional a card", 1, layer="trigger"))
    assert proj.build(content_dir=content).errors == []
    doc = page(proj.out, "map.html")
    assert doc.find(cls="map-symptoms") is None and doc.find(cls="map-question") is None
    assert "Nothing is placed in this layer yet." in norm(doc.text())


def test_entries_marked_todo_verify_are_left_out_of_the_page_with_a_warning(proj, tmp_path):
    content = map_content(
        tmp_path, symptoms=[*MAP_SYMPTOMS, {"id": "pending", "name": "Fictional pending symptom", "todo": "verify"}]
    )
    write_card(proj.cards, make_card("a-card", "Fictional a card", 1, layer="trigger"))
    result = proj.build(content_dir=content)
    assert result.errors == []
    assert "Fictional pending symptom" not in (proj.out / "map.html").read_text(encoding="utf-8")
    assert any("symptom:pending" in w for w in result.warnings)


def test_a_link_to_nothing_stops_the_build_with_its_rule_id(proj, tmp_path):
    content = map_content(tmp_path)
    write_card(proj.cards, make_card("a-card", "Fictional a card", 1, links=[map_link("no-such-card", "Broken.")]))
    result = proj.build(content_dir=content)
    assert any("[M2]" in e and "no-such-card" in e for e in result.errors)
    assert not proj.out.exists()


def test_an_invalid_content_file_stops_the_build(proj, tmp_path):
    content = map_content(tmp_path, symptoms=[{"id": "x", "name": "Fictional x"}])
    write_card(proj.cards, make_card("a-card", "Fictional a card", 1))
    result = proj.build(content_dir=content)
    assert any("[M6]" in e for e in result.errors) and not proj.out.exists()


def test_a_draft_may_link_to_a_published_card(proj, tmp_path):
    content = map_content(tmp_path)
    write_card(proj.cards, make_card("published-idea", "Fictional published idea", 1, layer="trigger"))
    draft = make_card(
        "draft-idea", "Fictional draft idea", 1, layer="mechanism", links=[map_link("published-idea", "Fictional.")]
    )
    write_card(proj.drafts, draft)
    assert proj.build(drafts=True, content_dir=content).errors == []
    assert "To Fictional published idea" in norm(page(proj.out, "map.html").text())


# --- the card pages do not change ---


def card_page(proj: Site, card: dict, content: Path) -> str:
    write_card(proj.cards, card)
    assert proj.build(content_dir=content).errors == []
    return (proj.out / "hypotheses" / f"{card['slug']}.html").read_text(encoding="utf-8")


def test_a_card_page_without_links_has_no_map_related_section(proj, tmp_path):
    content = map_content(tmp_path)
    html = card_page(proj, make_card("plain", "Fictional plain", 2), content)
    doc = parse(html)
    assert "Causal map" not in [norm(h.text()) for h in doc.find_all("h2")]
    assert not doc.find_all(cls="map-links") and not doc.find_all(cls="map-card")
    assert "layer-" not in html and "direction supported" not in html


def test_a_card_page_with_a_layer_and_links_is_identical_to_the_same_card_without_them(proj, tmp_path):
    content = map_content(tmp_path)
    plain = card_page(proj, make_card("same", "Fictional same", 2), content)
    link = map_link("symptom:fatigue", "A fictional link to fatigue.", "associated", ["pmid:00000001", "pmid:00000002"])
    linked = make_card("same", "Fictional same", 2, layer="mechanism", links=[link])
    assert card_page(proj, linked, content) == plain


# --- the drawing on the page ---


def drawing_of(node: Node) -> Node:
    svg = node.find("svg")
    assert svg is not None
    return svg


def drawn_nodes(svg: Node) -> dict[str, Node]:
    return {a.get("data-key"): a for a in svg.find_all("a") if "node" in a.classes}


def drawn_links(svg: Node) -> list[Node]:
    return [p for p in svg.find_all("path") if "link" in p.classes]


def test_the_whole_map_is_an_open_details_above_the_lists_with_the_localised_summary(map_site):
    doc = page(map_site.out, "map.html")
    details = doc.find("details", cls="map-whole")
    assert details is not None and "open" in details.attrs
    assert norm(details.find("summary").text()) == "Show the whole map"
    assert details.find("figure") is not None and details.find("svg") is not None
    order = [n for n in doc.find("main").walk() if n is details or n.get("id") == "layer-predisposition"]
    assert order[0] is details
    assert page(map_site.out, "nb/map.html").find("details", cls="map-whole").find("summary").text().strip() == (
        "Vis hele kartet"
    )


def test_the_whole_drawing_has_every_node_and_every_link_of_the_page_once(map_site):
    svg = drawing_of(page(map_site.out, "map.html").find("details", cls="map-whole"))
    nodes = drawn_nodes(svg)
    assert set(nodes) == {
        "root-idea",
        "middle-idea",
        "loose-idea",
        "symptom:fatigue",
        "question:own",
        "question:asked",
    }
    assert sorted((p.get("data-from"), p.get("data-to")) for p in drawn_links(svg)) == [
        ("middle-idea", "symptom:fatigue"),
        ("root-idea", "middle-idea"),
        ("root-idea", "symptom:fatigue"),
    ]
    assert nodes["root-idea"].get("href") == "hypotheses/root-idea.html"
    doc = page(map_site.out, "map.html")
    for key in ("symptom:fatigue", "question:own", "question:asked"):
        target = nodes[key].get("href")
        assert target.startswith("#") and doc.find(id=target[1:]) is not None


def test_a_neighbourhood_drawing_sits_under_each_card_with_a_link_and_not_under_one_without(map_site):
    doc = page(map_site.out, "map.html")
    middle = drawing_of(doc.find("article", id="card-middle-idea"))
    assert sorted((p.get("data-from"), p.get("data-to")) for p in drawn_links(middle)) == [
        ("middle-idea", "symptom:fatigue"),
        ("root-idea", "middle-idea"),
    ]
    assert doc.find("article", id="card-root-idea").find("svg") is not None
    assert doc.find("article", id="card-loose-idea").find("svg") is None


def test_the_page_has_no_duplicate_ids_with_many_drawings(map_site):
    for name in ("map.html", "nb/map.html"):
        ids = [n.get("id") for n in page(map_site.out, name).walk() if n.get("id")]
        assert len(ids) == len(set(ids)), name


def test_convergence_markers_on_the_page_match_the_lists(map_site):
    nodes = drawn_nodes(drawing_of(page(map_site.out, "map.html").find("details", cls="map-whole")))
    assert [norm(t.text()) for t in nodes["symptom:fatigue"].find_all("text", cls="marker")] == ["2 in"]
    assert [norm(t.text()) for t in nodes["root-idea"].find_all("text", cls="marker")] == ["2 out"]
    assert nodes["middle-idea"].find_all("text", cls="marker") == []


def test_the_contested_word_is_drawn_for_a_contested_card_only(proj, tmp_path):
    content = map_content(tmp_path)
    write_card(proj.cards, make_card("disputed", "Fictional disputed", 2, contested_rungs=[2], layer="mechanism"))
    write_card(proj.cards, make_card("settled", "Fictional settled", 2, layer="mechanism"))
    assert proj.build(content_dir=content).errors == []
    nodes = drawn_nodes(drawing_of(page(proj.out, "map.html").find("details", cls="map-whole")))
    assert "Contested" in nodes["disputed"].text()
    assert "Contested" not in nodes["settled"].text()
    assert "Level 2" in nodes["settled"].text()


def test_the_legend_explains_the_three_line_styles_and_the_node_types(map_site):
    legend = page(map_site.out, "map.html").find("div", cls="map-legend")
    samples = legend.find_all("svg")
    assert len(samples) == 3
    assert [bool(s.find("line").get("stroke-dasharray")) for s in samples] == [True, False, False]
    text = norm(legend.text())
    for phrase in ("Proposed link", "Associated link", "Direction supported", "open question", "symptom"):
        assert phrase in text


def test_the_stylesheet_scrolls_the_figure_not_the_page_and_styles_focus_and_the_script_closes_it_on_narrow_screens():
    css = (REPO_ROOT / "src" / "me_atlas" / "static" / "site.css").read_text(encoding="utf-8")
    figure = next(r for r in css.split("}") if r.strip().startswith(".map-figure {"))
    assert "overflow-x: auto" in figure
    assert ".node:focus-visible" in css
    js = (REPO_ROOT / "src" / "me_atlas" / "static" / "site.js").read_text(encoding="utf-8")
    assert "details.map-whole" in js and "max-width: 40em" in js


def test_the_whole_map_figure_breaks_out_of_the_text_column_up_to_the_window_width():
    css = (REPO_ROOT / "src" / "me_atlas" / "static" / "site.css").read_text(encoding="utf-8")
    rule = next(r for r in css.split("}") if ".map-whole .map-figure {" in r)
    assert "width: max-content" in rule and "max-width: calc(100vw - 2rem)" in rule
    assert "left: 50%" in rule and "translateX(-50%)" in rule


def test_the_script_handles_the_chain_on_hover_focus_touch_and_escape_and_the_css_dims_only_when_focusing():
    js = (REPO_ROOT / "src" / "me_atlas" / "static" / "site.js").read_text(encoding="utf-8")
    for needle in (
        "mouseenter",
        "focusin",
        "focusout",
        "'touch'",
        "Escape",
        "is-focusing",
        "on-chain",
        "data-chain-links",
    ):
        assert needle in js, needle
    css = (REPO_ROOT / "src" / "me_atlas" / "static" / "site.css").read_text(encoding="utf-8")
    dim = [r for r in css.split("}") if "opacity: .2" in r]
    assert "drawing.addEventListener('mouseleave', restore)" in js  # leaving the whole drawing clears
    assert "node.addEventListener('mouseleave'" not in js  # leaving a box does not
    assert len(dim) == 1 and ".is-focusing" in dim[0] and ":not(.on-chain)" in dim[0]


def test_the_legend_has_the_chain_line_in_both_languages_and_the_svg_carries_chains(map_site):
    en = page(map_site.out, "map.html")
    assert "Point at or focus a box" in norm(en.find("div", cls="map-legend").text())
    assert "Pek på eller tab til en boks" in norm(
        page(map_site.out, "nb/map.html").find("div", cls="map-legend").text()
    )
    nodes = drawn_nodes(drawing_of(en.find("details", cls="map-whole")))
    assert set(nodes["root-idea"].get("data-chain").split()) == {"root-idea", "middle-idea", "symptom:fatigue"}
    assert nodes["loose-idea"].get("data-chain") == "loose-idea"
    assert all(
        a.get("data-chain") is None for a in drawn_nodes(drawing_of(en.find("article", id="card-middle-idea"))).values()
    )


def test_from_40em_the_whole_map_scales_down_to_its_figure_and_never_up():
    css = (REPO_ROOT / "src" / "me_atlas" / "static" / "site.css").read_text(encoding="utf-8")
    media = next(r for r in css.splitlines() if r.startswith("@media (min-width: 40em) { .map-whole .map-figure svg"))
    assert "max-width: 100%" in media and "height: auto" in media
    assert "width: 100%" not in media.replace("max-width: 100%", "")  # width 100% would scale it up
