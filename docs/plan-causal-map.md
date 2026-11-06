# Plan: causal map — from possible root causes to symptoms

November 6, 2026 · For `/orchestrator`. Concept and data first; the drawn map is a later plan.

## Why

The sixteen hypotheses sit at different depths of one causal chain, but the front page shows them side by side as if they competed for the same place. "Impaired energy production after exertion" is the physiology of PEM, almost a symptom; "inherited genetic risk" is a predisposition. A map gives every hypothesis a *place* in the chain in addition to its evidence level, shows which hypotheses feed which, makes gaps visible as open questions that researchers can take up, and lets common upstream causes of the different tracks be found by counting, not by opinion. The founder accepted the concept on 2026-11-06; details may be adjusted once the first result is visible.

## Design decisions (brainstorm 2026-11-06, accepted by the founder)

1. **Five layers, root to experience.** Every node sits in exactly one layer:

   | Layer | Key | The question it answers |
   | --- | --- | --- |
   | Predisposition | `predisposition` | Who is vulnerable? |
   | Trigger | `trigger` | What starts it? |
   | Perpetuating mechanism | `mechanism` | Why does it not resolve? |
   | Measurable dysfunction | `dysfunction` | What goes wrong in the body? |
   | Symptom | `symptom` | What does the patient experience? |

   The first four layers hold hypothesis cards. The symptom layer is not hypotheses: it is a fixed list taken from the accepted case definitions (IOM 2015 and CCC), each symptom sourced to the case-definition document that lists it. A card that could sit in two layers (herpesvirus reactivation as trigger *or* consequence of immune dysfunction) gets one layer and a link that expresses the other reading; the ambiguity is information and is written out, not hidden.

2. **Two different claims, two different scales.** The existing evidence ladder (spec section 3) stays as it is and keeps grading the card: "this abnormality is present and replicated in patients, and the evidence that it is causal has come this far". A **link** between two nodes grades a narrower claim, "A drives B in ME/CFS patients", on its own three-step scale, added to the spec as a published rubric before it is used:

   | Step | Key | Drawn as | Requires |
   | --- | --- | --- | --- |
   | 1 Proposed | `proposed` | dashed, thin | A peer-reviewed source (a review counts) that states the link. Not studied directly in patients. |
   | 2 Associated | `associated` | solid, thin | A study in an ME/CFS cohort with a recognised case definition that measured both ends in the same patients and reports a relation between them. |
   | 3 Direction supported | `directional` | solid, thick | In patients: temporal order (A before B), an intervention on A that changes B, or a mediation analysis; a review alone never reaches this step. |

   Case-definition rules are the ladder's (Oxford-only evidence stays at step 1). A link never raises a card's level. A study that measured both ends and found no relation is recorded as a `context` study and the link text says so; links have no contested mark in v1.

3. **No link without a source, at every step.** "Proposed by [review]" is a source; the editorial team's own reasoning is not. Links may run both ways and form loops (vicious circles are a common shape of ME/CFS hypotheses); a tree is not forced.

4. **Open questions as empty boxes.** An open-question node is a question, never a claim: "What keeps the immune activation going? — unknown". At most one per layer to begin with (founder may add more). It is sourced to a publication that asks the question, or marked `editorial` and shown as the team's own question.

5. **Convergence is counted, not judged.** A node with two or more incoming links from different cards is listed as a *candidate common mechanism*; a node with two or more outgoing links as a *candidate root*. The site and the report print the counts and the lists; nobody writes "the common cause is".

6. **Setting a card's layer and adding or changing a link are founder decisions**, like status levels and badges (CLAUDE.md rule 2). Agents draft, `card-reviewer` checks, the founder rules; recorded in DECISIONS.

7. **The map is a second view.** The bar chart keeps answering "how far has the evidence come"; the map answers "where in the chain does this belong". The page text says that ME/CFS may be several conditions with different triggers that meet downstream, and that the map does not assume one chain.

8. **Data lives on the cards; no new store.** The symptom list and the open questions are small content files, like the glossary.

## Data model

Card fields (`drafts/` and `cards/`, validated by `me_atlas.cards`):

```yaml
layer: mechanism            # predisposition | trigger | mechanism | dysfunction
links:
  - to: endothelial-dysfunction        # a card slug, symptom:<id> or question:<id>
    support: associated                # proposed | associated | directional
    text: A fictional study measured both in the same patients and found them related.
    sources: [pmid:00000002]           # ids in this card's studies, as for every sourced text
```

- `layer` is required on every card. `links` is a list, may be empty, and lives on the upstream card only.
- A source that is only evidence for a link (a review proposing it; a study that measured both ends) is entered in `studies` with `role: context` and the usual fields (`case_definition: none`, `design: other` for a review), so the citation check (C1–C7) covers it and it is shown on the card page in the context group.
- `content/symptoms.yaml`: id, name, and for each listed case definition the source id of its document. `content/open-questions.yaml`: id, layer, question text, `asked_by` (source ids) or `editorial: true`. Both are validated like the glossary. If a case-definition document cannot be fetched and cached (IOM 2015 is a report, CCC a journal article), the entry says `TODO: verify` and is left out of the build until resolved; nothing is cited from memory.
- Validation rules (new ids, M1–): `to` resolves to an existing card, symptom or question; no link to itself; `support` in the enum; every link has at least one source; an `associated` or `directional` link cites at least one study with a cohort and a recognised case definition that is not a review; `layer` present and in the enum. The reviewer checks what the code cannot (that the cited study really measured both ends, that temporal order or intervention is there).
- Link texts, symptom names and question texts are translatable items in `translations/nb/`, with the same mechanical check as card text; until translated they fall back to English with the usual note.

## Steps

1. Spec and docs: add a "Causal links" section to `docs/ME-Atlas-functional-spec.md` (section 3, after "Contested evidence") with the layer table and the three-step rubric; extend `docs/card-format.md`. DECISIONS entry for the rubric and for the rule that layer and links are founder decisions.
2. Model and validation: `layer`, `links`, the two content files, rules M1–, tests with fictional cards (every negative input named in the rules fails with its rule id).
3. Report: `uv run python -m me_atlas.map report` prints, per layer, each node with its links out (support, references) and the convergence lists of decision 5. Offline, no AI.
4. Site: a plain `map.html` in both languages, layers as sections, every node with its links written as sentences with the support label and numbered references, the convergence lists, and the "may be several conditions" sentence. Lists only, nothing drawn. Navigation entry, string keys in both `i18n` files.
5. Agent: a `link-drafter` agent (sonnet) that reads one card and proposes its layer and links out from the card's own studies and from reviews it is given (fetched and cached by the pipeline first), writing to `drafts/`; `card-reviewer` gets a map mode that checks each link against its sources and the rubric. Translation step: the new items are listed by `pipeline translation-plan` and go through `card-translator`.
6. First mapping (manual, after the code is merged, a separate PR): symptom list and open questions written and sourced; `link-drafter` on all 16 cards; `card-reviewer` on every card; the founder rules on every layer and every link; Norwegian translation of the new items. Nothing is published to `cards/`.
7. `docs/map.md` reference; STATUS updated.

## Done when

- [ ] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` pass; no test touches the network or an AI; no new dependency.
- [ ] A card without `layer`, with an unknown `layer`, a link to a slug that does not exist, a self-link, a link without sources, and an `associated` link whose only source is a review each fail validation with their rule id (tested).
- [ ] `map report` on fictional cards prints the layers, the links and the two convergence lists; a node with two incoming links from different cards appears as a candidate common mechanism and one with two outgoing links as a candidate root (tested).
- [ ] `map.html` exists in `build/` and `build/nb/`, lists every card under its layer, every link as a sentence with support label and working references, and the symptom and open-question nodes; an `editorial` question is labelled as the team's own (tested on the built HTML).
- [ ] The English front page and card pages are unchanged in content except for what this plan adds (tested on a fictional card).
- [ ] Spec, card-format, DECISIONS and `docs/map.md` written; CLAUDE.md rule 2 lists layer and links among founder decisions.
- [ ] Step 6 is a separate PR after this one, so the code is reviewed apart from the mapped content.

## Out of scope

- The drawn map (boxes, arrows, line styles, layout, mobile behaviour): its own plan after the founder has seen the first mapped content as lists. Decision 2 fixes only what each step will be drawn as.
- Contested marks on links; subgroup-specific maps; weighting or scoring of nodes beyond the counts in decision 5.
- Automatic link proposals from the weekly pipeline (when a new paper measures two mapped nodes in the same patients). Later, once the first mapping has settled the shape.
- Changing the evidence ladder or any card's level.

## For the founder to confirm (defaults taken in this plan)

- Five layers, with mechanism and dysfunction kept apart (the hardest split to apply, the most useful for the root-cause search).
- Symptoms from IOM 2015 and CCC, each sourced to its document.
- Three link steps; step 1 needs a published source.
