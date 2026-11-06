# Causal map

Reference for the founder and for agents. Code: `src/me_atlas/map.py` (content files, link targets, graph, report), the `layer` and `links` fields and rules M1, M3-M5 in `src/me_atlas/cards.py`, the page in `src/me_atlas/templates/map.html`. Plan: `docs/plan-causal-map.md`. The layers and the link rubric are in `docs/ME-Atlas-functional-spec.md` section 3, "Causal map and links"; the card fields and rules M1-M6 are in `docs/card-format.md`. Where this page and the spec differ, the spec wins.

## What is built

- Cards may carry a `layer` and a list of `links` (sourced, on a three-step scale of their own).
- Two small content files hold the symptom nodes and the open-question nodes.
- `cards validate` checks all of it; `map report` prints the layers, the links and two convergence lists; the site builds a `map.html` page in English and Norwegian (lists only, nothing is drawn).
- A `link-drafter` agent proposes a layer and links for one card; `card-reviewer` has a map mode that checks them. Setting a layer and adding a link are founder decisions (CLAUDE.md rule 2).

## Commands

```bash
uv run python -m me_atlas.cards validate drafts/        # every rule, including M2 and M6
uv run python -m me_atlas.map report                    # cards/ only
uv run python -m me_atlas.map report --drafts           # a draft replaces the card with the same slug
uv run python -m me_atlas.map report --cards DIR --content DIR
uv run python -m me_atlas.site build --drafts           # build/map.html and build/nb/map.html
```

`cards validate` also takes `--content DIR` (default `content/`) and `--cards DIR` (default `cards/`), both relative to the current directory.

The report prints, per layer in plan order (predisposition, trigger, perpetuating mechanism, measurable dysfunction) and then "Not yet placed", each card with its links out as `-> <target name> [<support>] (sources)`; then the symptom nodes and the open questions; then **Candidate common mechanisms** (nodes with two or more incoming links from different cards, with the count) and **Candidate roots** (cards with two or more links out, with the count). It is offline and calls no AI. If any input is invalid it prints the validation errors to stderr and exits 1, with no report. Convergence is counted, never judged: nobody writes "the common cause is".

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
  # editorial: true                # ... or the editorial team's own question; exactly one of the two
```

An entry may say `todo: verify` instead of `sources` or `asked_by`/`editorial`. It is valid, but it is left out of the build and the report and printed as a warning, and a link to it is an M2 error. Use it when a case-definition document cannot be fetched and cached; nothing is cited from memory.

Translations (Norwegian): `content/symptoms.nb.yaml` is a list of `{id, name}` and `content/open-questions.nb.yaml` a list of `{id, text}`. Every `id` must exist in the English file. An entry with no translation shows the English with the usual note "This part is not translated yet." Link texts are card text and go through the card sidecars like the rest (`translations/nb/<slug>.yaml`, locator `links[<index>]`, in card order); `pipeline translation-plan` lists a new link item as `reason: new`, and `card-translator` translates it. See `docs/translation.md`.

## How link targets resolve (rule M2)

A link's `to` resolves when it is

1. a card slug in the **resolution set**, or
2. `symptom:<id>` for an entry of `content/symptoms.yaml`, or
3. `question:<id>` for an entry of `content/open-questions.yaml`.

The resolution set for a card slug is the card files `cards validate` was given (a directory counts as all its `*.yaml` files, the change log excepted), **plus every card file in `cards/`** (the `--cards` directory) **when at least one directory was given**. So `cards validate drafts/` lets a draft link to a published card; `cards validate drafts/one.yaml` alone resolves against that one file only. The site build and `map report` validate exactly the cards they build together (published cards, with drafts replacing the cards of the same slug), so a link must resolve within that set. A file that fails its own validation still counts for resolution (by its file name), so one broken card does not make every link to it fail as well.

Not checked by code: that the cited study really measured both ends in the same patients, that it was an ME/CFS cohort (M5 looks at design and case definition only), that temporal order, an intervention or a mediation analysis is there. The `card-reviewer` map mode checks that.

## The page

`map.html` (and `nb/map.html`), after "What changed" in the navigation: an introduction (a second view; links are hypotheses graded on their own scale; ME/CFS may be several conditions with different triggers that meet downstream), one section per layer plus "Not yet placed" when a card has no layer, each card as a link to its page with its links written as sentences `<text> — <support label> [n]` (the numbers refer to the card page's study anchors), the symptom nodes with the documents that list them, the open questions (with the publication that asks them, or "The editorial team's own question"), and the two convergence lists with counts. The card pages do not change.

## Agents

- `.claude/agents/link-drafter.md` (sonnet) reads one card and the cached review records it is given and writes a proposal `{slug, layer, links: [{to, support, text, sources, why}]}` under `data/pipeline/<date>/map/`. It may cite only ids in the card's studies or in the records it was given.
- `.claude/agents/card-reviewer.md`, "Map mode", checks each proposed link against the cited sources and the rubric and writes a verdict with findings, in the same shape as translation mode.

## Out of scope

- A pipeline subcommand that merges the proposals into a draft. For now the founder (or a chat session at the founder's request) copies an accepted layer and links into the draft by hand.
- The drawn map (boxes, arrows, line styles), contested marks on links, subgroup-specific maps, weighting or scoring of nodes beyond the counts, and automatic link proposals from the weekly run.
- Done 2026-11-06: the first mapping (16 cards placed, 17 links, symptom list from the ICC 2011, four editorial open questions); rulings in DECISIONS. Done 2026-11-06: a second pass with the review full texts as plain text with numbered paragraphs (`data/pipeline/2026-11-06-map-pass2/reviews/`), six more proposed links. Still open: a verifiable IOM 2015 or CCC record for the symptom list. The drawn map has its own plan: `docs/plan-drawn-map.md`.
