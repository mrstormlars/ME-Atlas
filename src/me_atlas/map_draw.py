"""The drawn causal map: a layout from a ``map.Graph`` and the SVG strings for it.

Pure functions, no I/O, no new dependency, no random numbers: the same input gives byte-identical SVG. Labels and
localised strings are passed in (``NodeInfo``, ``Strings``), so this module does not know about languages.

- ``render_full`` draws every node and every link, in bands from predisposition (top) to symptom (bottom).
- ``render_neighbourhood`` draws one card with what links into it above and what it links to below.

Both use the same ``_draw``. See ``docs/map.md``, section "The drawing".
"""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from me_atlas import map as maplib

ROUNDS = 4  # barycentre rounds
EMPTY_BAND_H = 28
MAX_NAME_LINES = 3
MAX_QUESTION_LINES = 1000  # a question is never cut short
DASH = "6 4"

# Line style per support step: set as attributes in the SVG, so it holds without the stylesheet.
LINK_STYLES: dict[str, dict[str, str]] = {
    "proposed": {"stroke-width": "1.5", "stroke-dasharray": DASH},
    "associated": {"stroke-width": "1.5"},
    "directional": {"stroke-width": "3.5"},
}


@dataclass(frozen=True)
class NodeInfo:
    """What the drawing needs to know about one node, already localised."""

    label: str  # the full name (a card), the symptom name or the question text
    href: str  # relative to the page: a card page, or "#symptom-<id>" / "#question-<id>"
    level: int | None = None  # cards only
    contested: bool = False  # cards only
    english: bool = False  # the label is English on a page of another language


@dataclass(frozen=True)
class Strings:
    bands: Mapping[str, str]  # layer key (and "unplaced") -> label
    level: str  # "Level {n}"
    contested: str
    count_in: str  # "{n} in"
    count_out: str  # "{n} out"
    supports: Mapping[str, str]  # support step -> label, used in the title of a link
    title: str
    desc: str
    near_title: str = "{name}"  # "Links of {name}"


@dataclass(frozen=True)
class Style:
    cols: int
    box_w: int
    gutter: int  # least width of the vertical gutter between two columns
    outer: int  # least width of the gutter at each side of the grid
    lane: int  # distance between two links in one gutter or channel
    row_gap: int  # least height of the channel between two rows of one band
    band_gap: int  # space between two bands
    label_h: int  # height of a band's label strip, 0 for no band labels
    top: int  # space above the first band
    name_lines: int = 3  # most lines of a card name
    font: int = 16  # px
    line: int = 20  # px between text lines
    pad_x: int = 8
    pad_y: int = 6
    char_w: float = 8.5  # a generous average width of a character at this font size
    base: int = 15  # baseline of the first text line below the top of a box
    edge: int = 14  # space between a channel's edge and its first lane
    slack: int = 16  # a gutter is this much wider than its lanes need
    band_pad: int = 10  # space below the last row of a band
    label_y: int = 24  # baseline of a band label below the top of the band
    rect_pad: int = 8  # how far a band's rectangle reaches past the boxes

    @property
    def chars(self) -> int:
        return int((self.box_w - 2 * self.pad_x) / self.char_w)


# The whole map is an overview at 12 px; the neighbourhood drawings keep 16 px (docs/map.md, "The drawing").
FULL = Style(
    cols=5,
    box_w=150,
    gutter=30,
    outer=15,
    lane=5,
    row_gap=30,
    band_gap=18,
    label_h=27,
    top=6,
    font=12,
    line=15,
    pad_x=6,
    pad_y=5,
    char_w=6.4,
    base=11,
    edge=11,
    slack=10,
    band_pad=8,
    label_y=18,
    rect_pad=6,
)
NEAR = Style(cols=2, box_w=124, gutter=28, outer=12, lane=5, row_gap=40, band_gap=0, label_h=0, top=8, name_lines=4)


def wrap(text: str, width: int, max_lines: int) -> list[str]:
    """Greedy wrap on word boundaries. A word longer than a line is broken with a hyphen. Text beyond the last line
    ends in an ellipsis, only there."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        if len(word) > width:  # a long word is broken with a hyphen, never cut off
            if cur:
                lines.append(cur)
                cur = ""
            while len(word) > width:
                lines.append(word[: width - 1] + "-")
                word = word[width - 1 :]
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= width:
            cur += " " + word
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        lines[-1] = (last if len(last) < width else last[: width - 1]) + "…"
    return lines or [""]


def short_name(name: str) -> str:
    """The card name up to the first ' ('."""
    return name.split(" (", 1)[0]


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def _n(value: float) -> str:
    s = f"{value:.1f}"
    return s[:-2] if s.endswith(".0") else s


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


@dataclass
class _Box:
    key: str
    kind: str
    lines: list[str]
    meta: str | None
    contested: str | None
    count_in: str | None
    count_out: str | None
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    row: int = 0
    st: Style | None = None

    @property
    def n_lines(self) -> int:
        extra = (
            (self.meta is not None)
            + (self.contested is not None)
            + (self.count_in is not None or self.count_out is not None)
        )
        return len(self.lines) + int(extra)

    @property
    def natural_h(self) -> float:
        return self.n_lines * self.st.line + 2 * self.st.pad_y


@dataclass(frozen=True)
class _Band:
    key: str
    label: str | None
    nodes: tuple[str, ...]


def _order(bands: Sequence[_Band], neighbours: Mapping[str, set[str]]) -> list[list[str]]:
    """Barycentre ordering: a fixed number of down-and-up sweeps; ties broken by node key."""
    order = [sorted(b.nodes) for b in bands]
    band_of = {k: i for i, keys in enumerate(order) for k in keys}

    def fraction() -> dict[str, float]:
        return {k: (i + 0.5) / len(keys) for keys in order for i, k in enumerate(keys)}

    for _ in range(ROUNDS):
        for sweep in (range(len(order)), range(len(order) - 1, -1, -1)):
            for bi in sweep:
                pos = fraction()
                keys = order[bi]

                def bary(k: str, pos=pos, bi=bi) -> tuple[float, str]:
                    others = [pos[o] for o in neighbours.get(k, ()) if o in band_of and band_of[o] != bi]
                    return (sum(others) / len(others) if others else pos[k], k)

                order[bi] = sorted(keys, key=bary)
    # linked nodes before unlinked ones: the more links to earlier bands, the earlier the row (stable otherwise)
    for bi in range(len(order)):

        def up(k: str, bi: int = bi) -> int:
            return len({o for o in neighbours.get(k, ()) if o in band_of and band_of[o] < bi})

        order[bi] = sorted(order[bi], key=lambda k: -up(k))
    return order


def _box_for(key: str, g: maplib.Graph, info: Mapping[str, NodeInfo], s: Strings, st: Style) -> _Box:
    node = g.nodes[key]
    i = info[key]
    if node.kind == "card":
        lines = wrap(short_name(i.label), st.chars, st.name_lines)
        meta = s.level.format(n=i.level) if i.level is not None else None
        contested = s.contested if i.contested else None
    else:
        text = ("? " if node.kind == "question" else "") + i.label
        lines = wrap(text, st.chars, MAX_QUESTION_LINES if node.kind == "question" else MAX_NAME_LINES)
        meta = contested = None
    return _Box(key, node.kind, lines, meta, contested, None, None, st=st)


def _sign(v: float) -> int:
    return (v > 0) - (v < 0)


def _rounded(points: list[tuple[float, float]], radius: float = 6.0) -> str:
    """A polyline with rounded corners as an SVG path (L and Q commands only)."""
    pts: list[tuple[float, float]] = []
    for p in points:
        if not pts or abs(p[0] - pts[-1][0]) > 0.05 or abs(p[1] - pts[-1][1]) > 0.05:
            pts.append(p)
    d = f"M{_n(pts[0][0])},{_n(pts[0][1])}"
    for i in range(1, len(pts) - 1):
        (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
        l1, l2 = abs(x1 - x0) + abs(y1 - y0), abs(x2 - x1) + abs(y2 - y1)  # segments are horizontal or vertical
        r = min(radius, l1 / 2, l2 / 2)
        ax, ay = x1 - r * _sign(x1 - x0), y1 - r * _sign(y1 - y0)
        bx, by = x1 + r * _sign(x2 - x1), y1 + r * _sign(y2 - y1)
        d += f" L{_n(ax)},{_n(ay)} Q{_n(x1)},{_n(y1)} {_n(bx)},{_n(by)}"
    d += f" L{_n(pts[-1][0])},{_n(pts[-1][1])}"
    return d


def _colour(intervals: Sequence[tuple[float, float, int]], gap: float) -> dict[int, int]:
    """Greedy lane assignment: intervals (lo, hi, id) that overlap, or come closer than ``gap``, get different lanes."""
    ends: list[float] = []
    lane_of: dict[int, int] = {}
    for lo, hi, ident in sorted(intervals):
        for lane, end in enumerate(ends):
            if lo >= end + gap:
                ends[lane] = hi
                lane_of[ident] = lane
                break
        else:
            ends.append(hi)
            lane_of[ident] = len(ends) - 1
    return lane_of


@dataclass
class _Route:
    edge: maplib.Edge
    rs: int
    rt: int
    cs: int
    ct: int
    direct: bool  # the target row is the next row below: one channel, no vertical gutter
    gutter: int = 0
    vlane: int = 0
    sx: float = 0.0
    tx: float = 0.0
    vx: float = 0.0


def _draw(
    g: maplib.Graph,
    info: Mapping[str, NodeInfo],
    s: Strings,
    st: Style,
    bands: Sequence[_Band],
    edges: Sequence[maplib.Edge],
    uid: str,
    title: str,
    highlight: bool = False,
) -> str:
    """Channel routing: boxes sit on a column grid; every link leaves the bottom of its source, runs in the horizontal
    channel below that row to a vertical gutter beside the target's column, along the gutter to the channel above the
    target's row, across, and into the top of the target. Links that would share a stretch of a channel or a gutter
    get separate lanes, and links at one box get separate ports, so no link crosses a box or lies on another."""
    unique: dict[tuple[str, int], maplib.Edge] = {}
    for e in edges:
        unique.setdefault((e.source, e.index), e)
    edges = list(unique.values())
    present = {k for b in bands for k in b.nodes}
    neighbours: dict[str, set[str]] = {}
    for e in edges:
        neighbours.setdefault(e.source, set()).add(e.target)
        neighbours.setdefault(e.target, set()).add(e.source)
    order = _order(bands, neighbours)

    in_counts = {n.key: c for n, c in maplib.common_mechanisms(g)}
    out_counts = {n.key: c for n, c in maplib.candidate_roots(g)}
    boxes: dict[str, _Box] = {}
    for k in sorted(present):
        b = _box_for(k, g, info, s, st)
        if k in in_counts:
            b.count_in = s.count_in.format(n=in_counts[k])
        if k in out_counts:
            b.count_out = s.count_out.format(n=out_counts[k])
        boxes[k] = b

    # rows of at most st.cols nodes on a column grid
    rows_of_band = [[keys[i : i + st.cols] for i in range(0, len(keys), st.cols)] for keys in order]
    used_cols = max([len(r) for rows in rows_of_band for r in rows] or [1])
    col_of: dict[str, int] = {}
    n_rows = 0
    for rows in rows_of_band:
        for r in rows:
            for c, k in enumerate(r):
                boxes[k].row = n_rows
                col_of[k] = c
            n_rows += 1

    # 1. each link: its rows, its columns and the vertical gutter it uses
    routes: list[_Route] = []
    for e in edges:
        rs, rt = boxes[e.source].row, boxes[e.target].row
        cs, ct = col_of[e.source], col_of[e.target]
        route = _Route(e, rs, rt, cs, ct, direct=rt - 1 == rs)
        route.gutter = ct if cs <= ct else ct + 1
        routes.append(route)

    # 2. lanes in the vertical gutters (intervals of channel numbers), then the width of each gutter
    gutter_lanes = [0] * (used_cols + 1)
    for gi in range(used_cols + 1):
        mine = [
            (min(r.rs, r.rt - 1), max(r.rs, r.rt - 1), i)
            for i, r in enumerate(routes)
            if not r.direct and r.gutter == gi
        ]
        lane_of = _colour(mine, 0.5)
        for _lo, _hi, i in mine:
            routes[i].vlane = lane_of[i]
        gutter_lanes[gi] = 1 + max(lane_of.values()) if lane_of else 0
    gutter_w = [
        max(st.outer if gi in (0, used_cols) else st.gutter, gutter_lanes[gi] * st.lane + st.slack)
        for gi in range(used_cols + 1)
    ]
    gutter_left: list[float] = []
    x = 0.0
    for gi in range(used_cols + 1):
        gutter_left.append(x)
        x += gutter_w[gi] + (st.box_w if gi < used_cols else 0)
    width = x

    for r in routes:
        if not r.direct:
            n = gutter_lanes[r.gutter]
            r.vx = gutter_left[r.gutter] + (gutter_w[r.gutter] - (n - 1) * st.lane) / 2 + r.vlane * st.lane
    for k, b in boxes.items():
        b.x, b.w = gutter_left[col_of[k]] + gutter_w[col_of[k]], float(st.box_w)

    # 3. ports along the bottom (leaving) and top (arriving) edges, ordered by where the link goes next
    ports: dict[tuple[str, str], list[tuple[float, int]]] = {}
    for i, r in enumerate(routes):
        sc = boxes[r.edge.source].x + st.box_w / 2
        tc = boxes[r.edge.target].x + st.box_w / 2
        ports.setdefault((r.edge.source, "bottom"), []).append((tc if r.direct else r.vx, i))
        ports.setdefault((r.edge.target, "top"), []).append((sc if r.direct else r.vx, i))
    for (key, side), entries in ports.items():
        entries.sort()
        b = boxes[key]
        step = min(20.0, (b.w - 32) / max(1, len(entries) - 1))
        for n, (_, i) in enumerate(entries):
            px = b.x + b.w / 2 + (n - (len(entries) - 1) / 2) * step
            if side == "bottom":
                routes[i].sx = px
            else:
                routes[i].tx = px

    # 4. lanes in the horizontal channels: leaving links first, then direct ones, then arriving ones
    #    (channel k lies below row k; channel -1 above the first row)
    segments: dict[int, dict[str, list[tuple[float, float, int]]]] = {}
    for i, r in enumerate(routes):
        if r.direct:
            segs = [(r.rs, "direct", min(r.sx, r.tx), max(r.sx, r.tx))]
        else:
            segs = [
                (r.rs, "leave", min(r.sx, r.vx), max(r.sx, r.vx)),
                (r.rt - 1, "arrive", min(r.vx, r.tx), max(r.vx, r.tx)),
            ]
        for ch, group, lo, hi in segs:
            segments.setdefault(ch, {}).setdefault(group, []).append((lo, hi, i))
    lane_index: dict[tuple[int, str, int], int] = {}
    channel_lanes: dict[int, int] = {}
    for ch, groups in segments.items():
        offset = 0
        for group in ("leave", "direct", "arrive"):
            mine = groups.get(group, [])
            lane_of = _colour(mine, 4.0)
            for _lo, _hi, i in mine:
                lane_index[(ch, group, i)] = offset + lane_of[i]
            offset += 1 + max(lane_of.values()) if lane_of else 0
        channel_lanes[ch] = offset

    def needed(ch: int) -> float:
        return st.edge + max(channel_lanes.get(ch, 0) - 1, 0) * st.lane + st.edge

    # 5. vertical layout: a channel is as high as its lanes need
    y = float(st.top)
    channel_start: dict[int, float] = {-1: 0.0}
    min_next = needed(-1)
    band_rects: list[tuple[str, str | None, float, float]] = []
    row_no = 0
    for bi, band in enumerate(bands):
        top = max(y, min_next - st.label_h)
        y = top + st.label_h
        rows = rows_of_band[bi]
        if not rows:
            y += EMPTY_BAND_H
        for ri, r in enumerate(rows):
            h = max(boxes[k].natural_h for k in r)
            y = max(y, min_next)
            for k in r:
                boxes[k].y, boxes[k].h = y, h
            y += h
            channel_start[row_no] = y
            min_next = y + needed(row_no)
            if ri < len(rows) - 1:
                y = max(y + st.row_gap, min_next)
            row_no += 1
        band_bottom = y + st.band_pad
        band_rects.append((band.key, band.label, top, band_bottom))
        y = band_bottom + st.band_gap
    height = max(y - st.band_gap, min_next) + st.top

    def lane_y(ch: int, group: str, i: int) -> float:
        return channel_start[ch] + st.edge + lane_index[(ch, group, i)] * st.lane

    paths: list[str] = []
    for i, r in enumerate(routes):
        e = r.edge
        sb, tb = boxes[e.source], boxes[e.target]
        p0 = (r.sx, sb.y + sb.h)
        p_end = (r.tx, tb.y)
        if r.direct and abs(r.sx - r.tx) < 0.5:
            pts = [p0, p_end]
        elif r.direct:
            yl = lane_y(r.rs, "direct", i)
            pts = [p0, (r.sx, yl), (r.tx, yl), p_end]
        else:
            yd, ya = lane_y(r.rs, "leave", i), lane_y(r.rt - 1, "arrive", i)
            pts = [p0, (r.sx, yd), (r.vx, yd), (r.vx, ya), (r.tx, ya), p_end]
        attrs = " ".join(f'{k}="{v}"' for k, v in LINK_STYLES[e.support].items())
        label = f"{info[e.source].label} → {info[e.target].label}: {s.supports.get(e.support, e.support)}"
        paths.append(
            f'<path class="link link-{_esc(e.support)}" data-from="{_esc(e.source)}" data-to="{_esc(e.target)}" '
            f'data-index="{e.index}" data-link="{_esc(link_id(e))}" d="{_rounded(pts)}" '
            f'fill="none" stroke="currentColor" {attrs} '
            f'marker-end="url(#{uid}-arrow)"><title>{_esc(label)}</title></path>'
        )

    left = gutter_left[0] + gutter_w[0]
    right_edge = gutter_left[used_cols]
    out: list[str] = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" class="map-svg" role="group" '
        f'aria-labelledby="{uid}-title {uid}-desc" width="{_n(width)}" height="{_n(height)}" '
        f'viewBox="0 0 {_n(width)} {_n(height)}">'
    )
    out.append(f'<title id="{uid}-title">{_esc(title)}</title><desc id="{uid}-desc">{_esc(s.desc)}</desc>')
    out.append(
        f'<defs><marker id="{uid}-arrow" class="arrowhead" viewBox="0 0 10 10" refX="10" refY="5" '
        f'markerWidth="10" markerHeight="10" markerUnits="userSpaceOnUse" orient="auto">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs>'
    )
    labelled = [(key, label, top, bottom) for key, label, top, bottom in band_rects if label is not None]
    for key, _label, top, bottom in labelled:
        out.append(
            f'<rect class="band-box band-{_esc(key)}" x="{_n(left - st.rect_pad)}" y="{_n(top)}" '
            f'width="{_n(right_edge - left + 2 * st.rect_pad)}" height="{_n(bottom - top)}" rx="8"/>'
        )
    out.append('<g class="links">' + "".join(paths) + "</g>")
    # the labels come after the links, with a halo, so a link passing behind one never hides it
    for _key, label, top, _bottom in labelled:
        out.append(
            f'<text class="band-label" x="{_n(left + 4)}" y="{_n(top + st.label_y)}" '
            f'font-size="{st.font}">{_esc(label)}</text>'
        )
    out.append('<g class="nodes">')
    for key in sorted(present):
        keys = None
        if highlight:
            nodes_on, links_on = chain(edges, key)
            keys = (" ".join(sorted(nodes_on)), " ".join(sorted(links_on)))
        out.append(_node_svg(g, boxes[key], info[key], keys))
    out.append("</g></svg>")
    return "".join(out)


def link_id(e: maplib.Edge) -> str:
    return f"{e.source}#{e.index}"


def chain(edges: Sequence[maplib.Edge], key: str) -> tuple[frozenset[str], frozenset[str]]:
    """The chain of a node: the node, every node it reaches by following links forward (descendants) and every node
    that reaches it (ancestors), at any depth. With D the descendants and the node, U the ancestors and the node, a link
    A->B is on the chain when A and B are both in D or both in U, so every lit box has a lit path to the node.
    Returns (node keys, link ids)."""

    def reach(forward: bool) -> set[str]:
        seen = {key}
        todo = [key]
        while todo:
            k = todo.pop()
            for e in edges:
                a, b = (e.source, e.target) if forward else (e.target, e.source)
                if a == k and b not in seen:
                    seen.add(b)
                    todo.append(b)
        return seen

    down, up = reach(True), reach(False)
    links = {
        link_id(e) for e in edges if (e.source in down and e.target in down) or (e.source in up and e.target in up)
    }
    return frozenset(down | up), frozenset(links)


def _node_svg(g: maplib.Graph, b: _Box, i: NodeInfo, chain_keys: tuple[str, str] | None = None) -> str:
    muted = b.kind == "symptom" and not g.incoming.get(b.key)
    cls = f"node node-{b.kind}" + (" node-muted" if muted else "")
    lang = ' lang="en"' if i.english else ""
    parts = [
        f'<a class="{cls}" href="{_esc(i.href)}" data-key="{_esc(b.key)}"{lang}'
        + (
            f' data-chain="{_esc(chain_keys[0])}" data-chain-links="{_esc(chain_keys[1])}"'
            if chain_keys is not None
            else ""
        )
        + ">",
        f"<title>{_esc(i.label)}</title>",
        f'<rect class="node-box" x="{_n(b.x)}" y="{_n(b.y)}" width="{_n(b.w)}" height="{_n(b.h)}" rx="6"'
        + (f' stroke-dasharray="{DASH}"' if b.kind == "question" else "")
        + "/>",
    ]
    st = b.st
    y = b.y + st.pad_y + st.base
    tx = b.x + st.pad_x
    for line in b.lines:
        parts.append(f'<text class="node-label" x="{_n(tx)}" y="{_n(y)}" font-size="{st.font}">{_esc(line)}</text>')
        y += st.line
    if b.meta is not None:
        parts.append(f'<text class="node-level" x="{_n(tx)}" y="{_n(y)}" font-size="{st.font}">{_esc(b.meta)}</text>')
        y += st.line
    if b.contested is not None:
        parts.append(
            f'<text class="node-contested" x="{_n(tx)}" y="{_n(y)}" font-size="{st.font}">{_esc(b.contested)}</text>'
        )
        y += st.line
    if b.count_in is not None:
        parts.append(
            f'<text class="marker marker-in" x="{_n(tx)}" y="{_n(y)}" font-size="{st.font}">{_esc(b.count_in)}</text>'
        )
    if b.count_out is not None:
        parts.append(
            f'<text class="marker marker-out" x="{_n(b.x + b.w - st.pad_x)}" y="{_n(y)}" text-anchor="end" '
            f'font-size="{st.font}">{_esc(b.count_out)}</text>'
        )
    parts.append("</a>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# The two drawings
# ---------------------------------------------------------------------------


def _all_edges(g: maplib.Graph) -> list[maplib.Edge]:
    return [e for source in sorted(g.out) for e in g.out[source]]


def render_full(g: maplib.Graph, info: Mapping[str, NodeInfo], s: Strings, uid: str = "map") -> str:
    """Every node and every link, in bands: the five layers always, 'not yet placed' only when a card has no layer."""
    layers = [*maplib.LAYER_ORDER]
    if g.in_layer(maplib.UNPLACED):
        layers.append(maplib.UNPLACED)
    bands = [_Band(layer, s.bands[layer], tuple(n.key for n in g.in_layer(layer))) for layer in layers]
    return _draw(g, info, s, FULL, bands, _all_edges(g), uid, s.title, highlight=True)


def render_neighbourhood(g: maplib.Graph, key: str, info: Mapping[str, NodeInfo], s: Strings, uid: str) -> str:
    """One card in the middle, the nodes that link into it above and the nodes it links to below."""
    ins = g.incoming.get(key, [])
    outs = g.out.get(key, [])
    above = sorted({e.source for e in ins})
    below = sorted({e.target for e in outs} - set(above))
    bands = [
        _Band("in", None, tuple(above)),
        _Band("self", None, (key,)),
        _Band("out", None, tuple(below)),
    ]
    bands = [b for b in bands if b.nodes]
    return _draw(g, info, s, NEAR, bands, [*ins, *outs], uid, s.near_title.format(name=info[key].label))


def has_links(g: maplib.Graph, key: str) -> bool:
    return bool(g.incoming.get(key) or g.out.get(key))


def legend_sample(support: str) -> str:
    """A small inline SVG showing one line style, for the legend."""
    attrs = " ".join(f'{k}="{v}"' for k, v in LINK_STYLES[support].items())
    return (
        f'<svg class="legend-sample legend-{_esc(support)}" aria-hidden="true" focusable="false" width="48" '
        f'height="16" viewBox="0 0 48 16"><line x1="2" y1="8" x2="46" y2="8" stroke="currentColor" {attrs}/></svg>'
    )
