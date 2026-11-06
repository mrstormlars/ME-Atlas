"""Tests for the drawn causal map (me_atlas.map_draw). Fictional nodes only; no network, no AI.

The drawing is parsed back as XML and the geometry is checked, so a broken layout fails here, not only in a browser.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from me_atlas import map as maplib
from me_atlas import map_draw as md

NS = {"s": "http://www.w3.org/2000/svg"}
BANDS = {
    "predisposition": "Predisposition",
    "trigger": "Trigger",
    "mechanism": "Mechanism",
    "dysfunction": "Dysfunction",
    "symptom": "Symptom",
    "unplaced": "Not yet placed",
}
STRINGS = md.Strings(
    bands=BANDS,
    level="Level {n}",
    contested="Contested",
    count_in="{n} in",
    count_out="{n} out",
    supports={"proposed": "proposed", "associated": "associated", "directional": "direction supported"},
    title="Causal map title",
    desc="The lists below hold the same content, with sources.",
    near_title="Links of {name}",
)


def make_graph(nodes: list[maplib.Node], links: list[tuple[str, str, str]]) -> maplib.Graph:
    g = maplib.Graph()
    for n in nodes:
        g.nodes[n.key] = n
    for i, (a, b, support) in enumerate(links):
        e = maplib.Edge(a, i, b, support, ("pmid:00000001",), f"text {i}")
        g.out.setdefault(a, []).append(e)
        g.incoming.setdefault(b, []).append(e)
    return g


def card(key: str, name: str, layer: str) -> maplib.Node:
    return maplib.Node(key, "card", name, layer)


def infos(g: maplib.Graph, *, contested=(), english=()) -> dict[str, md.NodeInfo]:
    out = {}
    for k, n in g.nodes.items():
        href = f"hypotheses/{k}.html" if n.kind == "card" else "#" + k.replace(":", "-")
        out[k] = md.NodeInfo(n.name, href, 2 if n.kind == "card" else None, k in contested, k in english)
    return out


def sample_graph() -> maplib.Graph:
    nodes = [
        card("root", "Fictional root idea (a long name in brackets that must be cut)", "predisposition"),
        card("mid-a", "Fictional middle idea A", "mechanism"),
        card("mid-b", "Fictional middle idea B", "mechanism"),
        card("dys", "Fictional dysfunction", "dysfunction"),
        maplib.Node("symptom:fatigue", "symptom", "Fictional fatigue", "symptom"),
        maplib.Node("symptom:loose", "symptom", "Fictional loose symptom", "symptom"),
        maplib.Node("question:q", "question", "What starts the fictional change?", "trigger"),
    ]
    links = [
        ("root", "mid-a", "proposed"),
        ("root", "mid-b", "associated"),
        ("mid-a", "dys", "directional"),
        ("mid-b", "dys", "proposed"),
        ("dys", "symptom:fatigue", "associated"),
        ("dys", "question:q", "proposed"),
    ]
    return make_graph(nodes, links)


def many_graph(n: int) -> maplib.Graph:
    nodes = [card(f"c{i:02d}", f"Fictional card number {i} with a rather long name", "mechanism") for i in range(n)]
    nodes.append(card("top", "Fictional top", "predisposition"))
    nodes.append(maplib.Node("symptom:s", "symptom", "Fictional symptom", "symptom"))
    links = [("top", f"c{i:02d}", "proposed") for i in range(0, n, 2)]
    links += [(f"c{i:02d}", "symptom:s", "associated") for i in range(n)]
    links += [("c03", "c01", "associated"), ("c00", "top", "proposed")]  # a link inside a band, and a loop
    return make_graph(nodes, links)


def parse_svg(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def q(el: ET.Element, path: str) -> list[ET.Element]:
    return el.findall(path, NS)


def classes(el: ET.Element) -> set[str]:
    return set((el.get("class") or "").split())


def node_links(root: ET.Element) -> dict[str, ET.Element]:
    return {a.get("data-key"): a for a in q(root, ".//s:a") if "node" in classes(a)}


def box_of(a: ET.Element) -> tuple[float, float, float, float]:
    r = a.find("s:rect", NS)
    return (float(r.get("x")), float(r.get("y")), float(r.get("width")), float(r.get("height")))


def texts(a: ET.Element) -> list[str]:
    return [t.text or "" for t in q(a, "s:text")]


def band_labels(g: maplib.Graph) -> list[str]:
    root = parse_svg(md.render_full(g, infos(g), STRINGS))
    return [t.text for t in q(root, ".//s:text") if "band-label" in classes(t)]


def path_points(d: str, step: float = 2.0) -> list[tuple[float, float]]:
    """Dense points along a path made of M, L and Q commands (every ``step`` px at most)."""
    out: list[tuple[float, float]] = []
    cur = (0.0, 0.0)
    for cmd, args in re.findall(r"([MLQ])([^MLQ]*)", d):
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", args)]
        pts = list(zip(nums[0::2], nums[1::2], strict=True))
        if cmd == "M":
            cur = pts[0]
            out.append(cur)
        elif cmd == "L":
            end = pts[0]
            n = max(1, int(max(abs(end[0] - cur[0]), abs(end[1] - cur[1])) / step) + 1)
            out += [(cur[0] + (end[0] - cur[0]) * k / n, cur[1] + (end[1] - cur[1]) * k / n) for k in range(1, n + 1)]
            cur = end
        else:
            (cx, cy), (ex, ey) = pts
            for k in range(1, 9):
                t = k / 8
                u = 1 - t
                out.append((u * u * cur[0] + 2 * u * t * cx + t * t * ex, u * u * cur[1] + 2 * u * t * cy + t * t * ey))
            cur = (ex, ey)
    return out


def segments_of(d: str) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """The straight stretches of a path (the rounded corners are left out)."""
    segs = []
    cur = (0.0, 0.0)
    for cmd, args in re.findall(r"([MLQ])([^MLQ]*)", d):
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", args)]
        end = (nums[-2], nums[-1])
        if cmd == "L":
            segs.append((cur, end))
        cur = end
    return segs


def link_paths(root: ET.Element) -> list[ET.Element]:
    return [p for p in q(root, ".//s:path") if "link" in classes(p)]


def support_of(p: ET.Element) -> str:
    return next(c for c in classes(p) if c.startswith("link-"))[5:]


# --- D3: determinism ---


def test_the_same_input_gives_byte_identical_svg():
    g = sample_graph()
    assert md.render_full(g, infos(g), STRINGS) == md.render_full(sample_graph(), infos(g), STRINGS)
    first = md.render_neighbourhood(g, "dys", infos(g), STRINGS, "n")
    assert first == md.render_neighbourhood(sample_graph(), "dys", infos(g), STRINGS, "n")


# --- D2: bands ---


def test_the_five_bands_are_drawn_with_their_labels_even_when_empty_and_top_to_bottom():
    g = make_graph([card("only", "Fictional only", "mechanism")], [])
    assert band_labels(g) == ["Predisposition", "Trigger", "Mechanism", "Dysfunction", "Symptom"]
    root = parse_svg(md.render_full(g, infos(g), STRINGS))
    ys = [float(t.get("y")) for t in q(root, ".//s:text") if "band-label" in classes(t)]
    assert ys == sorted(ys) and len(set(ys)) == 5


def test_not_yet_placed_is_a_band_only_when_a_card_has_no_layer():
    assert "Not yet placed" not in band_labels(make_graph([card("a", "Fictional a", "mechanism")], []))
    labels = band_labels(make_graph([card("a", "Fictional a", maplib.UNPLACED)], []))
    assert labels[-1] == "Not yet placed" and len(labels) == 6


def test_a_question_sits_in_the_band_of_its_layer():
    g = sample_graph()
    root = parse_svg(md.render_full(g, infos(g), STRINGS))
    bands = {t.text: float(t.get("y")) for t in q(root, ".//s:text") if "band-label" in classes(t)}
    qy = box_of(node_links(root)["question:q"])[1]
    assert bands["Trigger"] < qy < bands["Mechanism"]


# --- D3/D4: rows, overlap, viewBox ---


def test_no_boxes_overlap_all_lie_inside_the_viewbox_and_a_row_holds_at_most_five():
    g = many_graph(13)
    root = parse_svg(md.render_full(g, infos(g), STRINGS))
    vb = [float(v) for v in root.get("viewBox").split()]
    assert vb[:2] == [0, 0]
    assert float(root.get("width")) == vb[2] and float(root.get("height")) == vb[3]
    boxes = [box_of(a) for a in node_links(root).values()]
    assert len(boxes) == len(g.nodes)
    for x, y, w, h in boxes:
        assert x >= 0 and y >= 0 and x + w <= vb[2] and y + h <= vb[3]
    for i, (x1, y1, w1, h1) in enumerate(boxes):
        for x2, y2, w2, h2 in boxes[i + 1 :]:
            assert x1 + w1 <= x2 or x2 + w2 <= x1 or y1 + h1 <= y2 or y2 + h2 <= y1
    rows: dict[float, int] = {}
    for i in range(13):
        y = box_of(node_links(root)[f"c{i:02d}"])[1]
        rows[y] = rows.get(y, 0) + 1
    assert sorted(rows.values()) == [3, 5, 5]


def test_text_is_never_smaller_than_16_px():
    g = many_graph(6)
    root = parse_svg(md.render_full(g, infos(g), STRINGS))
    sizes = {float(t.get("font-size")) for t in q(root, ".//s:text")}
    assert sizes and min(sizes) >= 16


def test_wrap_cuts_on_word_boundaries_and_marks_what_it_cuts_off():
    lines = md.wrap("word " * 40, 20, 3)
    assert len(lines) == 3 and lines[-1].endswith("…") and all(len(x) <= 20 for x in lines)
    assert len(md.wrap("word " * 40, 20, 1000)) > 3
    assert md.wrap("Neuroinflammation", 14, 3) == ["Neuroinflamma-", "tion"]
    assert md.wrap("aa Neuroinflammation", 14, 3) == ["aa", "Neuroinflamma-", "tion"]
    assert md.wrap("short name", 20, 3) == ["short name"]
    assert md.wrap("aaa bbb ccc", 7, 3) == ["aaa bbb", "ccc"]


# --- D5: card boxes ---


def test_a_card_box_has_the_short_name_at_most_three_lines_the_level_and_the_full_name_in_title():
    g = sample_graph()
    a = node_links(parse_svg(md.render_full(g, infos(g), STRINGS)))["root"]
    assert a.find("s:title", NS).text.startswith("Fictional root idea (a long name")
    lines = [t.text for t in q(a, "s:text") if "node-label" in classes(t)]
    assert " ".join(lines) == "Fictional root idea" and len(lines) <= 3
    assert [t.text for t in q(a, "s:text") if "node-level" in classes(t)] == ["Level 2"]
    assert a.get("href") == "hypotheses/root.html"


def test_short_name_cuts_at_the_first_bracket_only():
    assert md.short_name("Name (with brackets) (and more)") == "Name"
    assert md.short_name("Plain name") == "Plain name"


def test_the_contested_word_is_on_a_contested_card_and_not_on_an_uncontested_one():
    g = sample_graph()
    nodes = node_links(parse_svg(md.render_full(g, infos(g, contested={"mid-a"}), STRINGS)))
    assert "Contested" in texts(nodes["mid-a"])
    assert "Contested" not in texts(nodes["mid-b"])
    assert not any("Contested" in t for t in texts(nodes["symptom:fatigue"]))


# --- D6: node classes ---


def test_node_classes_and_only_a_symptom_without_incoming_link_is_muted():
    g = sample_graph()
    nodes = node_links(parse_svg(md.render_full(g, infos(g), STRINGS)))
    assert classes(nodes["root"]) == {"node", "node-card"}
    assert classes(nodes["symptom:fatigue"]) == {"node", "node-symptom"}  # has an incoming link: not muted
    assert classes(nodes["symptom:loose"]) == {"node", "node-symptom", "node-muted"}
    assert classes(nodes["question:q"]) == {"node", "node-question"}


def test_a_question_box_is_dashed_starts_with_a_question_mark_and_a_symptom_box_is_not_dashed():
    g = sample_graph()
    nodes = node_links(parse_svg(md.render_full(g, infos(g), STRINGS)))
    assert nodes["question:q"].find("s:rect", NS).get("stroke-dasharray")
    assert texts(nodes["question:q"])[0].startswith("?")
    assert nodes["symptom:fatigue"].find("s:rect", NS).get("stroke-dasharray") is None
    assert nodes["symptom:fatigue"].get("href") == "#symptom-fatigue"
    assert nodes["question:q"].get("href") == "#question-q"


def test_a_node_shown_in_english_carries_lang_en_and_others_do_not():
    g = sample_graph()
    nodes = node_links(parse_svg(md.render_full(g, infos(g, english={"symptom:fatigue"}), STRINGS)))
    assert nodes["symptom:fatigue"].get("lang") == "en"
    assert nodes["root"].get("lang") is None


# --- D7: links ---


def test_every_edge_appears_once_with_its_class_endpoints_and_arrowhead():
    g = sample_graph()
    root = parse_svg(md.render_full(g, infos(g), STRINGS))
    paths = link_paths(root)
    got = sorted((p.get("data-from"), p.get("data-to"), p.get("data-index")) for p in paths)
    want = sorted((e.source, e.target, str(e.index)) for edges in g.out.values() for e in edges)
    assert got == want
    marker_ids = {m.get("id") for m in q(root, ".//s:marker")}
    for p in paths:
        assert support_of(p) in md.LINK_STYLES
        assert p.get("marker-end")[5:-1] in marker_ids


def test_line_style_is_set_in_the_svg_dashed_for_proposed_solid_for_associated_thick_for_directional():
    g = sample_graph()
    by_support = {support_of(p): p for p in link_paths(parse_svg(md.render_full(g, infos(g), STRINGS)))}
    assert by_support["proposed"].get("stroke-dasharray")
    assert by_support["associated"].get("stroke-dasharray") is None
    assert by_support["directional"].get("stroke-dasharray") is None
    assert float(by_support["directional"].get("stroke-width")) > float(by_support["associated"].get("stroke-width"))


# --- D8: convergence markers ---


def test_markers_are_on_exactly_the_nodes_of_the_convergence_lists_with_the_same_counts():
    g = sample_graph()
    nodes = node_links(parse_svg(md.render_full(g, infos(g), STRINGS)))
    want_in = {n.key: f"{c} in" for n, c in maplib.common_mechanisms(g)}
    want_out = {n.key: f"{c} out" for n, c in maplib.candidate_roots(g)}
    assert want_in == {"dys": "2 in"} and want_out == {"root": "2 out", "dys": "2 out"}
    for key, a in nodes.items():
        assert [t.text for t in q(a, "s:text") if "marker-in" in classes(t)] == (
            [want_in[key]] if key in want_in else []
        )
        assert [t.text for t in q(a, "s:text") if "marker-out" in classes(t)] == (
            [want_out[key]] if key in want_out else []
        )
    # one link in and one out: in neither list, so no marker at all
    assert not any("marker" in classes(t) for t in q(nodes["mid-a"], "s:text"))


# --- D9: accessibility ---


def test_the_svg_is_a_group_with_title_and_desc_and_every_node_is_a_link():
    g = sample_graph()
    root = parse_svg(md.render_full(g, infos(g), STRINGS, "x"))
    assert root.get("role") == "group"
    assert root.find("s:title", NS).text == "Causal map title"
    assert "lists below" in root.find("s:desc", NS).text
    assert root.get("aria-labelledby") == "x-title x-desc"
    assert all(a.get("href") for a in node_links(root).values()) and len(node_links(root)) == len(g.nodes)


def test_the_legend_sample_shows_each_line_style():
    assert "stroke-dasharray" in md.legend_sample("proposed")
    assert "stroke-dasharray" not in md.legend_sample("associated")
    assert 'stroke-width="3.5"' in md.legend_sample("directional")


# --- D10: neighbourhood ---


def test_the_neighbourhood_holds_exactly_the_cards_incoming_and_outgoing_edges():
    g = sample_graph()
    root = parse_svg(md.render_neighbourhood(g, "dys", infos(g), STRINGS, "near-dys"))
    got = sorted((p.get("data-from"), p.get("data-to")) for p in link_paths(root))
    assert got == sorted([("mid-a", "dys"), ("mid-b", "dys"), ("dys", "symptom:fatigue"), ("dys", "question:q")])
    nodes = node_links(root)
    assert set(nodes) == {"dys", "mid-a", "mid-b", "symptom:fatigue", "question:q"}
    ys = {k: box_of(a)[1] for k, a in nodes.items()}
    assert ys["mid-a"] < ys["dys"] < ys["symptom:fatigue"]  # incoming above, outgoing below
    assert root.find("s:title", NS).text == "Links of Fictional dysfunction"


def test_the_neighbourhood_fits_375_px_and_holds_at_most_three_per_row():
    nodes = [card("hub", "Fictional hub", "mechanism")]
    links = []
    for i in range(7):
        nodes.append(card(f"in{i}", f"Fictional incoming number {i}", "predisposition"))
        nodes.append(card(f"out{i}", f"Fictional outgoing number {i}", "dysfunction"))
        links += [(f"in{i}", "hub", "proposed"), ("hub", f"out{i}", "associated")]
    links.append(("hub", "in0", "proposed"))  # a loop: in0 is both above and below
    g = make_graph(nodes, links)
    root = parse_svg(md.render_neighbourhood(g, "hub", infos(g), STRINGS, "near-hub"))
    width = float(root.get("width"))
    assert width <= 340
    rows: dict[float, int] = {}
    for a in node_links(root).values():
        x, y, w, _ = box_of(a)
        rows[y] = rows.get(y, 0) + 1
        assert x >= 0 and x + w <= width
    assert max(rows.values()) <= 3
    assert len(link_paths(root)) == 15
    assert_routing_is_clean(root)


def test_a_card_with_no_links_has_no_neighbourhood():
    g = sample_graph()
    assert md.has_links(g, "dys") and not md.has_links(g, "symptom:loose")


def test_ids_differ_between_drawings_so_a_page_with_many_has_no_duplicate_ids():
    g = sample_graph()
    a = parse_svg(md.render_neighbourhood(g, "dys", infos(g), STRINGS, "near-dys"))
    b = parse_svg(md.render_neighbourhood(g, "root", infos(g), STRINGS, "near-root"))
    assert {m.get("id") for m in q(a, ".//s:marker")}.isdisjoint({m.get("id") for m in q(b, ".//s:marker")})


# --- D16, D17: routing ---


def routed_graph() -> maplib.Graph:
    """Several bands, rows of 5, links that skip a band, links between far columns, upward links and loops."""
    nodes = []
    for i in range(7):
        nodes.append(card(f"p{i}", f"Fictional predisposition {i}", "predisposition"))
    for i in range(11):
        nodes.append(card(f"m{i:02d}", f"Fictional mechanism {i}", "mechanism"))
    for i in range(6):
        nodes.append(card(f"d{i}", f"Fictional dysfunction {i}", "dysfunction"))
    for i in range(14):
        nodes.append(maplib.Node(f"symptom:s{i:02d}", "symptom", f"Fictional symptom {i}", "symptom"))
    nodes.append(maplib.Node("question:t", "question", "Fictional trigger question?", "trigger"))
    links = []
    for i in range(7):
        links.append((f"p{i}", f"m{(i * 3) % 11:02d}", "proposed"))
        links.append((f"p{i}", f"d{i % 6}", "associated"))  # skips the trigger band
    links.append(("p0", "question:t", "proposed"))
    links.append(("p6", "question:t", "proposed"))
    for i in range(11):
        links.append((f"m{i:02d}", f"d{(i * 5) % 6}", "directional" if i % 3 == 0 else "proposed"))
        links.append((f"m{i:02d}", f"symptom:s{(i * 7) % 14:02d}", "associated"))
    for i in range(6):
        for j in (0, 4, 9):
            links.append((f"d{i}", f"symptom:s{(i * 2 + j) % 14:02d}", "associated"))
    links.append(("d2", "m01", "proposed"))  # upward
    links.append(("m02", "m09", "associated"))  # inside one band, across rows
    links.append(("m03", "m04", "proposed"))  # inside one row
    links.append(("m04", "m03", "proposed"))  # a loop
    links.append(("d0", "p0", "proposed"))  # upward over two bands
    return make_graph(nodes, links)


def overlap(a1, b1, a2, b2) -> float:
    """Length of the stretch two straight segments share when both lie on one vertical or one horizontal line."""
    if a1[0] == b1[0] == a2[0] == b2[0]:
        lo, hi = max(min(a1[1], b1[1]), min(a2[1], b2[1])), min(max(a1[1], b1[1]), max(a2[1], b2[1]))
    elif a1[1] == b1[1] == a2[1] == b2[1]:
        lo, hi = max(min(a1[0], b1[0]), min(a2[0], b2[0])), min(max(a1[0], b1[0]), max(a2[0], b2[0]))
    else:
        return 0.0
    return max(0.0, hi - lo)


def assert_routing_is_clean(root: ET.Element) -> None:
    boxes = {k: box_of(a) for k, a in node_links(root).items()}
    vb_w, vb_h = float(root.get("width")), float(root.get("height"))
    segs = []
    for p in link_paths(root):
        a, b = p.get("data-from"), p.get("data-to")
        for x, y in path_points(p.get("d")):
            assert 0 <= x <= vb_w and 0 <= y <= vb_h, (a, b)
            for key, (bx, by, bw, bh) in boxes.items():
                if key not in (a, b):
                    assert not (bx - 4 < x < bx + bw + 4 and by - 4 < y < by + bh + 4), f"{a} -> {b} crosses {key}"
        segs.append((p, segments_of(p.get("d"))))
    for i, (p1, s1) in enumerate(segs):
        for p2, s2 in segs[i + 1 :]:
            for a1, b1 in s1:
                for a2, b2 in s2:
                    assert overlap(a1, b1, a2, b2) <= 8, (p1.get("data-from"), p1.get("data-to"), p2.get("data-from"))


def test_no_link_passes_through_a_box_or_lies_on_another_link_in_the_full_drawing():
    g = routed_graph()
    root = parse_svg(md.render_full(g, infos(g), STRINGS))
    assert len(link_paths(root)) == len({(e.source, e.index) for es in g.out.values() for e in es})
    assert_routing_is_clean(root)
    boxes = [box_of(a) for a in node_links(root).values()]
    for i, (x1, y1, w1, h1) in enumerate(boxes):
        for x2, y2, w2, h2 in boxes[i + 1 :]:
            assert x1 + w1 <= x2 or x2 + w2 <= x1 or y1 + h1 <= y2 or y2 + h2 <= y1


def test_the_checker_finds_a_link_through_a_box_and_two_links_on_top_of_each_other():
    bad = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400">'
        '<a class="node node-card" data-key="a"><rect x="10" y="10" width="50" height="30"/></a>'
        '<a class="node node-card" data-key="b"><rect x="10" y="200" width="50" height="30"/></a>'
        '<a class="node node-card" data-key="c"><rect x="10" y="100" width="50" height="30"/></a>'
        '<path class="link link-proposed" data-from="a" data-to="b" d="M35,40 L35,200"/></svg>'
    )
    with pytest.raises(AssertionError, match="crosses c"):
        assert_routing_is_clean(parse_svg(bad))
    assert overlap((5, 0), (5, 50), (5, 20), (5, 90)) == 30
    assert overlap((5, 0), (5, 50), (6, 20), (6, 90)) == 0


def test_the_gutters_between_columns_and_rows_are_at_least_28_px():
    g = routed_graph()
    boxes = [box_of(a) for a in node_links(parse_svg(md.render_full(g, infos(g), STRINGS))).values()]
    for i, (x1, y1, w1, h1) in enumerate(boxes):
        for x2, y2, w2, h2 in boxes[i + 1 :]:
            if y1 < y2 + h2 and y2 < y1 + h1:  # same row
                assert x2 - (x1 + w1) >= 28 or x1 - (x2 + w2) >= 28
            if x1 < x2 + w2 and x2 < x1 + w1:  # same column
                assert y2 - (y1 + h1) >= 28 or y1 - (y2 + h2) >= 28


def test_links_into_one_box_use_ports_at_least_4_px_apart():
    g = routed_graph()
    root = parse_svg(md.render_full(g, infos(g), STRINGS))
    ends: dict[str, list[float]] = {}
    for p in link_paths(root):
        ends.setdefault(p.get("data-to"), []).append(path_points(p.get("d"))[-1][0])
    assert any(len(v) > 1 for v in ends.values())
    for v in ends.values():
        v = sorted(v)
        assert all(b - a >= 4 for a, b in zip(v, v[1:], strict=False))


def test_a_self_link_or_a_repeated_edge_is_drawn_once_in_the_neighbourhood():
    g = make_graph([card("a", "Fictional a", "mechanism")], [("a", "a", "proposed")])
    root = parse_svg(md.render_neighbourhood(g, "a", infos(g), STRINGS, "d"))
    assert len(link_paths(root)) == 1


# --- D18, D19 ---


def test_linked_symptoms_come_before_unlinked_ones():
    nodes = [card("c", "Fictional c", "mechanism")]
    nodes += [maplib.Node(f"symptom:s{i:02d}", "symptom", f"Fictional symptom {i}", "symptom") for i in range(12)]
    linked = {f"symptom:s{i:02d}" for i in (3, 5, 7, 11)}
    g = make_graph(nodes, [("c", k, "associated") for k in sorted(linked)])
    root = parse_svg(md.render_full(g, infos(g), STRINGS))
    pos = {k: (box_of(a)[1], box_of(a)[0]) for k, a in node_links(root).items() if k.startswith("symptom:")}
    assert max(pos[k] for k in linked) < min(pos[k] for k in pos if k not in linked)
    muted = {k for k, a in node_links(root).items() if "node-muted" in classes(a)}
    assert muted == set(pos) - linked


def test_a_long_question_is_never_truncated_but_a_card_name_is_capped():
    text = "What is the longest question that the fictional editorial team could possibly ask, and does it end?"
    g = make_graph(
        [
            maplib.Node("question:long", "question", text, "trigger"),
            card("c", "Fictional " + "word " * 30, "mechanism"),
        ],
        [],
    )
    nodes = node_links(parse_svg(md.render_full(g, infos(g), STRINGS)))
    shown = " ".join(t.text for t in q(nodes["question:long"], "s:text"))
    assert shown == "? " + text and "…" not in shown
    card_lines = [t.text for t in q(nodes["c"], "s:text") if "node-label" in classes(t)]
    assert len(card_lines) == 3 and card_lines[-1].endswith("…")


def test_a_long_word_in_a_neighbourhood_box_is_hyphenated_across_lines_without_an_ellipsis():
    word = "abcdefghijklmnopqrstuvwxy"  # 25 letters
    g = make_graph(
        [card("a", f"Fictional {word}", "mechanism"), card("b", "Fictional b", "dysfunction")], [("a", "b", "proposed")]
    )
    root = parse_svg(md.render_neighbourhood(g, "a", infos(g), STRINGS, "d"))
    lines = [t.text for t in q(node_links(root)["a"], "s:text") if "node-label" in classes(t)]
    assert "…" not in "".join(lines) and len(lines) <= 4
    assert "".join(x.rstrip("-") for x in lines).replace(" ", "") == "Fictional" + word
    assert any(x.endswith("-") for x in lines)
    # over the cap the ellipsis is only at the end of the last line
    g = make_graph(
        [card("a", "Fictional " + "w" * 120, "mechanism"), card("b", "B", "dysfunction")], [("a", "b", "proposed")]
    )
    root = parse_svg(md.render_neighbourhood(g, "a", infos(g), STRINGS, "d"))
    lines = [t.text for t in q(node_links(root)["a"], "s:text") if "node-label" in classes(t)]
    assert len(lines) == 4 and lines[-1].endswith("…") and not any("…" in x for x in lines[:-1])


# --- D22: chains ---


def edges_of(g: maplib.Graph) -> list[maplib.Edge]:
    return [e for es in g.out.values() for e in es]


def ids(g: maplib.Graph, pairs: set[tuple[str, str]]) -> set[str]:
    return {md.link_id(e) for e in edges_of(g) if (e.source, e.target) in pairs}


def test_the_chain_of_the_middle_of_a_straight_line_is_the_whole_line_and_both_links():
    g = make_graph([card(k, k, "mechanism") for k in "abc"], [("a", "b", "proposed"), ("b", "c", "proposed")])
    nodes, links = md.chain(edges_of(g), "b")
    assert nodes == {"a", "b", "c"} and links == ids(g, {("a", "b"), ("b", "c")})
    nodes, _ = md.chain(edges_of(g), "c")
    assert nodes == {"a", "b", "c"}  # ancestors at any depth


def test_a_sibling_branch_is_not_on_the_chain():
    g = make_graph([card(k, k, "mechanism") for k in "abc"], [("a", "b", "proposed"), ("a", "c", "proposed")])
    nodes, links = md.chain(edges_of(g), "b")
    assert nodes == {"a", "b"} and "c" not in nodes
    assert links == ids(g, {("a", "b")})


def test_a_link_from_an_ancestor_to_a_descendant_that_skips_the_node_is_not_on_the_chain():
    # a -> b -> c, a -> c, x -> c: focus b lights a, b, c and the links a->b and b->c only
    g = make_graph(
        [card(k, k, "mechanism") for k in "abcx"],
        [("a", "b", "proposed"), ("b", "c", "proposed"), ("a", "c", "proposed"), ("x", "c", "proposed")],
    )
    nodes, links = md.chain(edges_of(g), "b")
    assert nodes == {"a", "b", "c"}
    assert links == ids(g, {("a", "b"), ("b", "c")})


def test_links_between_two_descendants_and_between_two_ancestors_are_lit():
    down = make_graph(
        [card(k, k, "mechanism") for k in "FABC"],
        [("F", "A", "proposed"), ("A", "B", "proposed"), ("B", "C", "proposed")],
    )
    assert md.chain(edges_of(down), "F") == (frozenset("FABC"), ids(down, {("F", "A"), ("A", "B"), ("B", "C")}))
    up = make_graph(
        [card(k, k, "mechanism") for k in "FABC"],
        [("C", "B", "proposed"), ("B", "A", "proposed"), ("A", "F", "proposed")],
    )
    assert md.chain(edges_of(up), "F") == (frozenset("FABC"), ids(up, {("C", "B"), ("B", "A"), ("A", "F")}))


def test_a_sibling_of_the_node_and_its_link_stay_dimmed():
    g = make_graph([card(k, k, "mechanism") for k in "AFS"], [("A", "F", "proposed"), ("A", "S", "proposed")])
    nodes, links = md.chain(edges_of(g), "F")
    assert nodes == {"A", "F"} and links == ids(g, {("A", "F")})


def test_every_lit_box_has_a_lit_path_to_the_node_and_every_lit_link_has_both_ends_lit():
    graphs = [
        make_graph(
            [card(k, k, "mechanism") for k in "abcdefg"],
            [
                ("a", "b", "proposed"),
                ("b", "c", "proposed"),
                ("a", "c", "proposed"),
                ("c", "d", "proposed"),
                ("d", "b", "proposed"),  # a loop b -> c -> d -> b
                ("e", "c", "proposed"),
                ("c", "f", "proposed"),
                ("e", "f", "proposed"),
                ("g", "a", "proposed"),
            ],
        ),
        routed_graph(),
        sample_graph(),
    ]
    for g in graphs:
        edges = edges_of(g)
        by_id = {md.link_id(e): e for e in edges}
        for focus in g.nodes:
            nodes, links = md.chain(edges, focus)
            assert focus in nodes
            lit = [by_id[i] for i in links]
            assert all(e.source in nodes and e.target in nodes for e in lit)
            forward, backward = {focus}, {focus}
            for _ in g.nodes:
                forward |= {e.target for e in lit if e.source in forward}
                backward |= {e.source for e in lit if e.target in backward}
            assert nodes == forward | backward, (focus, nodes, forward, backward)


def test_a_loop_ends_and_a_node_without_links_is_its_own_chain():
    g = make_graph([card(k, k, "mechanism") for k in "abz"], [("a", "b", "proposed"), ("b", "a", "proposed")])
    nodes, links = md.chain(edges_of(g), "a")
    assert nodes == {"a", "b"} and len(links) == 2
    assert md.chain(edges_of(g), "z") == (frozenset({"z"}), frozenset())


def test_the_full_svg_carries_the_chain_of_every_node_and_the_neighbourhood_does_not():
    g = sample_graph()
    root = parse_svg(md.render_full(g, infos(g), STRINGS))
    for key, a in node_links(root).items():
        nodes, links = md.chain(edges_of(g), key)
        assert set(a.get("data-chain").split()) == nodes
        assert set(a.get("data-chain-links").split()) == links
    assert {p.get("data-link") for p in link_paths(root)} == {md.link_id(e) for e in edges_of(g)}
    assert node_links(root)["symptom:loose"].get("data-chain") == "symptom:loose"
    assert node_links(root)["symptom:loose"].get("data-chain-links") == ""
    near = parse_svg(md.render_neighbourhood(g, "dys", infos(g), STRINGS, "d"))
    assert all(a.get("data-chain") is None for a in node_links(near).values())
