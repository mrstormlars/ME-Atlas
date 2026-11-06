# Plan: the drawn causal map

November 6, 2026 · For `/orchestrator`. Follows `docs/plan-causal-map.md`, whose data, rubric and list page are built and merged; the first mapping is done (16 cards, 17 links, 14 symptom nodes, 4 open questions). This plan only draws what is already there.

## Why

The list page (`map.html`) states every placement and every link, but a reader has to hold the chain in their head. A drawing shows at a glance where each hypothesis sits, which ones feed which, where tracks meet, and where the boxes are still empty. It adds no new claims: everything drawn is a node or link that the list page already states, with the same sources.

## Design decisions (defaults; the founder confirms or adjusts after seeing the first result)

1. **Built at build time as inline SVG, by Python, with no JavaScript library and no new dependency.** The site stays static and works without JavaScript. Same input, same drawing (deterministic layout, tested).

2. **Layers as horizontal bands, top to bottom:** predisposition, trigger, perpetuating mechanism, measurable dysfunction, symptom. Reading direction follows the chain from root to experience. Each band is labelled with its name and its question ("Who is vulnerable?" …). Within a band, nodes are ordered to reduce crossing lines (a few rounds of the simple barycentre method: order each band by the mean position of its neighbours). No force-directed or random layout.

3. **What a node looks like.**
   - A card: a box with its short name and its evidence level as on the front page (same level colours and the number), linking to the card page. Contested cards keep their contested mark.
   - A symptom: a plain box with the symptom name. Symptoms with no incoming link are drawn muted, not hidden, so the gaps are visible.
   - An open question: an empty box with a dashed border and "?" before the question, labelled as a question (and as the editorial team's own where it is).
   - An empty band (today: trigger) still shows its band and its open question.

4. **What a link looks like** (fixed by decision 2 of the causal-map plan): step 1 proposed = dashed thin, step 2 associated = solid thin, step 3 direction supported = solid thick; an arrowhead at the downstream end. Line style, not colour, carries the step, so the map reads in greyscale and for colour-blind readers. A legend explains the three styles and the node types.

5. **Convergence is shown, not judged.** Nodes on the "candidate common mechanism" and "candidate root" lists get a small marker with the count ("3 links in"), matching the lists below the drawing. No node is drawn larger or highlighted as "the cause".

6. **Reading one node.** Hovering or focusing a node (keyboard Tab) dims everything except that node and its direct links (CSS only; a few lines of `site.js` at most, and the map is complete without it). Each node is a real link, so the keyboard order follows the bands.

7. **Narrow screens (below about 40em, phones).** The whole map does not fit a 375 px screen legibly, and sideways panning is hard work for readers with little energy. On narrow screens the page shows the list view first (as today) and, under each card in the list, a small **neighbourhood drawing**: the card in the middle, what links into it above, what it links to below, with the same line styles. The full drawing is shown from about 40em up, and offered on phones behind a "Show the whole map" toggle that opens it in a scrollable frame. Neighbourhood drawings are generated the same way as the full map, so there is one drawing code path.

8. **The list stays the text alternative.** The SVG has a `<title>` and a short `<desc>` and points to the lists; every fact in the drawing is also in the text. The references (the numbered sources) stay in the list, not in the drawing.

9. **Both languages.** Node names, band labels, the legend and the question texts come from the same localised sources as the list page; a text with no translation falls back to English with the usual note in the list (not inside the drawing, where it would not fit).

10. **The card pages and the front page do not change.** Whether to add a neighbourhood drawing to each card page is a later decision, after the founder has seen it on the map page.

## Steps

1. Layout module (`src/me_atlas/map_draw.py` or a section of `map.py`): from the existing graph, compute band positions and node order (barycentre, fixed number of rounds, ties broken by slug), box sizes from text length with line wrapping, and edge paths (straight or one-bend curves between bands; links within a band and loops drawn as a curve to the side). Pure functions, no I/O.
2. SVG rendering: nodes, edges with the three line styles and arrowheads, band labels, legend, convergence markers, `<title>`/`<desc>`, CSS classes per node type and support step. Uses the site's colour tokens (light and dark).
3. Neighbourhood drawing for one card, from the same layout and rendering code.
4. Page: `map.html` and `nb/map.html` get the full drawing above the lists (from about 40em), the neighbourhood drawing under each card in the list, and the "Show the whole map" toggle on narrow screens. Hover/focus dimming in CSS. String keys in both i18n files (legend, toggle, band questions).
5. Tests (offline, fictional cards): see "Done when".
6. Live check in the built-in browser at 375 px and desktop, light and dark, keyboard only, on the draft build; screenshots to the founder before merge. Then `docs/map.md` and STATUS updated.

## Done when

- [ ] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` pass; no new dependency; no external script.
- [ ] On fictional cards: every node and every link of the graph appears exactly once in the full SVG; each link has the class of its support step, and a `proposed` link is dashed, an `associated` link solid and a `directional` link thicker (tested on the SVG).
- [ ] The layout is deterministic (two builds give byte-identical SVG) and no two node boxes overlap (bounding-box test, including a band with ten or more nodes).
- [ ] A symptom with no incoming link is drawn with the muted class; an open question with the question class; a band with no card still appears with its label.
- [ ] Convergence markers appear on exactly the nodes in the two convergence lists, with the same counts.
- [ ] Every card node links to its card page; `nb/map.html` uses Norwegian band labels, legend and node names where translated.
- [ ] A neighbourhood drawing exists for every card in the list and contains exactly that card's incoming and outgoing links.
- [ ] Live check at 375 px and desktop, light and dark, keyboard: no horizontal page scroll, the toggle works, focus is visible; screenshots shown to the founder.
- [ ] `docs/map.md` describes the drawing; STATUS updated.

## Out of scope

- Zoom and pan, drag to rearrange, filtering by support step or by subgroup, animations.
- Any JavaScript graph library or layout engine (Graphviz, D3, Cytoscape).
- Drawings on the card pages or the front page (decision 10).
- New nodes, links, levels or wording: the drawing shows the content exactly as the founder has ruled it.
- Printing or exporting the map as an image.

## For the founder to confirm (defaults taken in this plan)

- Bands top to bottom (root at the top, symptoms at the bottom).
- Evidence level shown in each card box with the front page's colours.
- On phones: lists with a small neighbourhood drawing per card, and the whole map behind a toggle.
- Symptoms without links shown muted rather than hidden.
