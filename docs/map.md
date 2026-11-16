# Causal map

Reference for the founder and for agents. Code: `src/me_atlas/map.py` (content files, link targets, graph, report), the `layer` and `links` fields and rules M1, M3-M5 in `src/me_atlas/cards.py`, the page in `src/me_atlas/templates/map.html`. Plan: `docs/plan-causal-map.md`. The layers and the link rubric are in `docs/ME-Atlas-functional-spec.md` section 3, "Causal map and links"; the card fields and rules M1-M6 are in `docs/card-format.md`. Where this page and the spec differ, the spec wins.

## What is built

- Cards may carry a `layer` and a list of `links` (sourced, on a three-step scale of their own).
- Two small content files hold the symptom nodes and the open-question nodes.
- `cards validate` checks all of it; `map report` prints the layers, the links and two convergence lists; the site builds a `map.html` page in English and Norwegian (lists, and the drawing described under "The drawing").
- A `link-drafter` agent proposes a layer and links for one card; `card-reviewer` has a map mode that checks them. Setting a layer and adding a link are tier 2 changes that the independent auditor decides (CLAUDE.md rule 2, functional spec section 6); the founder may overrule as a logged correction.

## Commands

```bash
uv run python -m me_atlas.cards validate drafts/        # every rule, including M2 and M6
uv run python -m me_atlas.map report                    # cards/ only
uv run python -m me_atlas.map report --drafts           # a draft replaces the card with the same slug
uv run python -m me_atlas.map report --cards DIR --content DIR
uv run python -m me_atlas.site build --drafts           # build/map.html and build/nb/map.html
```

`cards validate` also takes `--content DIR` (default `content/`) and `--cards DIR` (default `cards/`), both relative to the current directory.

The report prints, per layer in plan order (predisposition, trigger, perpetuating mechanism, measurable dysfunction) and then "Not yet placed", each card with its links out as `-> <target name> [<support>] (sources)`; then the symptom nodes and the open questions; then **Candidate common mechanisms** (nodes with two or more incoming links from different cards, with the count) and **Candidate roots** (cards with two or more links out, with the count); then the gap lists, each heading with its count and `  none` when empty: **Symptoms with no link**; **Symptoms linked only at step 1** (per symptom the number of hypotheses and one `<- card (slug)` line per source card); **Links not yet tested in patients** (the number of links at step `proposed`, per target `-> target (key)` and per link `<- card [proposed] (sources)`); **What the next rung requires** (per level present, 5 down to 0, `Level k: <rung name>`, the cards, ` — contested at rung(s) r` where the card has a contested mark, and `next: <next rung name>` for levels 0-4); and **Hypotheses with no links yet**. It is offline and calls no AI. If any input is invalid it prints the validation errors to stderr and exits 1, with no report. Convergence is counted, never judged: nobody writes "the common cause is".

## Content files

Both are optional. Absent means no symptom nodes and no question nodes, and the build still succeeds.

`content/symptoms.yaml`: a list of

```yaml
- id: fictional-fatigue            # lower-case words joined by hyphens, unique
  name: Fictional fatigue
  sources: [pmid:00000001]         # the case-definition document(s) that list the symptom; non-empty
```

`content/open-questions.yaml`: a list of

```yaml
- id: what-keeps-it-going          # unique
  layer: mechanism                 # predisposition, trigger, mechanism, dysfunction or symptom
  text: What keeps the fictional signal low?
  asked_by: [pmid:00000002]        # a publication that asks the question ...
  # editorial: true                # ... or the project's own question; exactly one of the two
```

An entry may say `todo: verify` instead of `sources` or `asked_by`/`editorial`. It is valid, but it is left out of the build and the report and printed as a warning, and a link to it is an M2 error. Use it when a case-definition document cannot be fetched and cached; nothing is cited from memory.

Translations (Norwegian): `content/symptoms.nb.yaml` is a list of `{id, name}` and `content/open-questions.nb.yaml` a list of `{id, text}`. Every `id` must exist in the English file. An entry with no translation shows the English with the usual note "This part is not translated yet." Link texts are card text and go through the card sidecars like the rest (`translations/nb/<slug>.yaml`, locator `links[<index>]`, in card order); `pipeline translation-plan` lists a new link item as `reason: new`, and `card-translator` translates it. See `docs/translation.md`.

## How link targets resolve (rule M2)

A link's `to` resolves when it is

1. a card slug in the **resolution set**, or
2. `symptom:<id>` for an entry of `content/symptoms.yaml`, or
3. `question:<id>` for an entry of `content/open-questions.yaml`.

The resolution set for a card slug is the card files `cards validate` was given (a directory counts as all its `*.yaml` files, the change log excepted), **plus every card file in `cards/`** (the `--cards` directory) **when at least one directory was given**. So `cards validate drafts/` lets a draft link to a published card; `cards validate drafts/one.yaml` alone resolves against that one file only. The site build and `map report` validate exactly the cards they build together (published cards, with drafts replacing the cards of the same slug), so a link must resolve within that set. A file that fails its own validation still counts for resolution (by its file name), so one broken card does not make every link to it fail as well.

**Public build and unpublished cards.** The public site build (no `--drafts`) builds `cards/` only, but a published card may link to a card that exists only in `drafts/` (held back after review or audit). Such a target counts as known, so it is not an M2 error. It is not a node: the map page shows the link as the target's name (the draft's `name`, or the slug with spaces if the draft does not load) followed by "(not yet published)", with the usual support label and numbered references, but with no `href`, and no edge is drawn or counted. A target in neither `cards/` nor `drafts/` is still an M2 error. With `--drafts` the draft is built and the link is an ordinary link.

Not checked by code: that the cited study really measured both ends in the same patients, that it was an ME/CFS cohort (M5 looks at design and case definition only), that temporal order, an intervention or a mediation analysis is there. The `card-reviewer` map mode checks that.

## The page

`map.html` (and `nb/map.html`), after "What changed" in the navigation: an introduction (a second view; links are hypotheses graded on their own scale; ME/CFS may be several conditions with different triggers that meet downstream), one section per layer plus "Not yet placed" when a card has no layer, each card as a link to its page with its links written as sentences `<text> — <support label> [n]` (the numbers refer to the card page's study anchors), the symptom nodes with the documents that list them, the open questions (with the publication that asks them, or "This project's own question, not asked in a publication"), and the two convergence lists with counts. The card pages do not change.

## The gaps page

`gaps.html` (and `nb/gaps.html`, "What is missing" / "Hva mangler"), after "Causal map" in the navigation: the same five gap lists as the report, with the same counts, as sections `gaps-unlinked-symptoms`, `gaps-step1-symptoms`, `gaps-untested-links`, `gaps-next-rung` and `gaps-unlinked-cards`. Symptoms and links are shown as on the map page (the numbers on a link are the map page's numbers for that card); the next-rung sentences are the existing `rung.<k>.name` and `rung.<k>.meaning` strings. The lists live in `me_atlas.map` (`unlinked_symptoms`, `proposed_only_symptoms`, `proposed_links`, `unlinked_cards`, `cards_by_level`). The page adds no claim: gaps are counted, never judged. Plan: `docs/plan-gaps-page.md`.

Above the lists, a section `gaps-summary` ("At a glance" / "Kort oppsummert") shows the same data as three counted figures: a table of incoming links per symptom by support step (`gaps-summary-symptoms`, one mark per link in the map's line vocabulary, rows with no link marked in muted text), one bar of all links by step (`gaps-summary-links`) and the hypotheses by level 0 to 5 with the contested count (`gaps-summary-levels`). All numbers are text; the bars and marks are aria-hidden; nothing is ordered by count. The per-step counts come from `me_atlas.map.step_counts`.

## The drawing

`src/me_atlas/map_draw.py` (pure functions, no I/O, no dependency) turns the graph into inline SVG at build time. It draws only what the lists already state; every fact in the drawing is also in the text, with its sources. Same input, same bytes.

- **Bands**, top to bottom: predisposition, trigger, perpetuating mechanism, measurable dysfunction, symptom, and "Not yet placed" only when a card has no layer. All five bands are drawn with their label even when empty. Open questions sit in the band of their layer.
- **Rows and order:** at most 5 boxes per row (a longer band wraps onto more rows). Order within a band is a fixed number (4) of barycentre rounds, ties broken by node key. After the barycentre rounds a node with more links to earlier bands goes into an earlier row, so in the symptom band linked symptoms come before unlinked ones. Boxes in a row share one height, computed from the wrapped text.
- **Size:** the SVG has `width`/`height` equal to its viewBox in px. The whole map is an overview: its text is 12 px, with boxes, gutters, lanes and gaps scaled to match (about 900 px wide at most for five columns). The neighbourhood drawings keep 16 px text; the lists and those drawings carry the readable text (founder ruling 2026-11-06). From 40em the whole-map SVG shrinks to fit its figure (`max-width: 100%; height: auto`) and is never scaled up; below 40em it keeps its natural size and the figure scrolls sideways inside itself (`overflow-x: auto` on `.map-figure`); the page does not. The whole-map figure leaves the text column: as wide as the drawing, at most the window less 1rem each side, centred.
- **Card box:** the name up to the first " (" on at most 3 lines (4 in a neighbourhood drawing; a word longer than a line is broken with a hyphen, and "…" appears only at the end of the last line when the name needs more lines; the full name in the node's title), a line "Level n", and the contested word when the card is contested. A question box grows to as many lines as needed; it is never cut short. A card box links to the card page. Symptom and question boxes link to their entries in the lists on the same page. A symptom with no incoming link is drawn muted (`node-muted`); a question has a dashed border and starts with "?". A node shown in English on a page of another language has `lang="en"`.
- **Links (channel routing):** boxes sit on a column grid with gutters of at least 28 px between columns and rows. A link leaves the bottom of its source, runs in the horizontal channel below that row to the vertical gutter beside the target's column, along the gutter to the channel above the target's row, across, and into the top of the target, with rounded corners. Upward links and loops use the same gutters. No link passes through a box other than its own two. Links that would share a stretch get separate lanes (8 px apart in the full drawing), and several links at one box use separate ports along its edge, so none lies on another. Channels and gutters grow to fit their lanes. One `<path class="link link-<support>">` per link, with `data-from`/`data-to`, an arrowhead at the downstream end and the line style as SVG attributes: proposed dashed thin, associated solid thin, direction supported solid thick. Band labels are drawn after the links, with a halo, so a link behind one never hides it.
- **Convergence:** the nodes on the "candidate common mechanism" list carry "n in", the nodes on the "candidate roots" list "n out", with the same counts as the lists. Counted, not judged: nothing is drawn larger or highlighted.
- **Accessibility:** `role="group"`, a `<title>` and a `<desc>` that points to the lists; every node is a link, so it is reachable with Tab and has a visible `:focus-visible` style. An HTML legend under the drawing explains the line styles (with inline samples) and the node types.
- **Page:** the whole map is in `<details class="map-whole" open>` above the lists; `site.js` closes it on load below 40em, and without JavaScript it stays open. Under each card in the list that has a link in or out there is a neighbourhood drawing (incoming above, the card, outgoing below; two boxes per row as a choice within the limit of three, at most 340 px wide; card names up to 4 lines) made by the same code.
- **Languages:** band labels, level and contested words, markers, legend and title come from the string files (`map.draw.*`, `map.legend.*`); names come from the same localised sources as the lists.
- **Chain highlighting (whole-map drawing only):** pointing at or focusing a box dims everything that is not on its chain: the box, every box it reaches by following links forward and every box that reaches it, at any depth, and the links between them (with D the descendants and the box, U the ancestors and the box, a link A to B is on the chain when A and B are both in D or both in U, so every lit box has a lit path to the box; loops end because each box is visited once). `map_draw.chain` computes the sets at build time and writes them as `data-chain` and `data-chain-links` on each box; `site.js` only toggles classes (`is-focusing` on the SVG, `on-chain` on boxes and links) on mouseenter/focusin, keeps the chain when the pointer moves off a box onto an empty part (no flicker), and clears when the pointer leaves the whole drawing, on focusout, on Escape or on a click outside the boxes; the CSS dims what lacks `on-chain` to 20 % opacity. On a touch screen the first tap on a box shows its chain and keeps it, a second tap on the same box follows its link, and a tap elsewhere or Escape clears. Without JavaScript nothing is dimmed. The neighbourhood drawings do not do this.

## Agents

- `.claude/agents/link-drafter.md` (sonnet) reads one card and the cached records (reviews or original studies) it is given and writes a proposal `{slug, layer, links: [{to, support, text, sources, why}]}` under `data/pipeline/<date>/map/`. It may cite only ids in the card's studies or in the records it was given. `uv run python -m me_atlas.survey pairs --context <slug-a> <slug-b>` can supply it with the cached records that match both cards (`docs/survey.md`).
- `.claude/agents/card-reviewer.md`, "Map mode", checks each proposed link against the cited sources and the rubric and writes a verdict with findings, in the same shape as translation mode.

## Out of scope

- A pipeline subcommand that merges the proposals into a draft, and a way to set or change a layer through the pipeline. A layer is still copied into a draft by hand (the founder, or a chat session at the founder's request), and only once the auditor has accepted it. Links of a published card are added by a link round (`link-apply` ... `link-publish`: map review, two sequential audits, change log and trail; `docs/pipeline.md`, "Adding links to a published card (link round)"), which does not change the layer.
- Contested marks on links, subgroup-specific maps and automatic link proposals from the weekly run.
- A principle that stays: nodes and gaps are counted, never weighted, scored or ranked (no "number of symptoms explained" score, no weights on link steps).
- Done 2026-11-06: the first mapping (16 cards placed, 17 links, symptom list from the ICC 2011, four editorial open questions); rulings in DECISIONS. Done 2026-11-06: a second pass with the review full texts as plain text with numbered paragraphs (`data/pipeline/2026-11-06-map-pass2/reviews/`), six more proposed links. Still open: a verifiable IOM 2015 or CCC record for the symptom list. The drawn map (built, see "The drawing") had its own plan: `docs/plan-drawn-map.md`.
