# Plan: the gaps page ("What is missing")

Brainstorm 2026-11-08. For `/orchestrator`.

## Goal

The site should help readers see **which connections are under-studied** and **where the next study would matter**, without ranking hypotheses or saying what is promising. Everything on the page is derived mechanically from fields the cards already have (`level`, `contested`, `layer`, `links[].support`) and from the symptom list; nothing is scored, weighted or judged. The founder decides what is promising; the page shows the gaps and lets the reader draw their own conclusion.

This replaces the idea of a third ranking ("number of symptoms explained, weighted by link step"). That number was rejected in the brainstorm: today it would measure how thorough the one review we happened to cache was, it saturates over a graph with loops, and the weights would have no source. `docs/map.md` keeps "weighting or scoring of nodes beyond the counts" out of scope.

## What the page shows

A new page `gaps.html` (English) and `nb/gaps.html` (Norwegian), in the navigation after "Causal map". Title: "What is missing". Short intro: the lists are counts of what the cards do not yet contain; a gap is not a finding, and an absent link means nobody has mapped it here yet, not that there is none.

Four lists, in this order:

1. **Symptoms with no link to any hypothesis.** The ICC symptom nodes with zero incoming links (7 of 14 today: neurosensory and motor disturbances, susceptibility to infections, genitourinary, sensitivities, respiratory, thermostatic instability, temperature intolerance). Each with the documents that list it, as on the map page.
2. **Symptoms linked only at step 1.** Symptoms whose incoming links are all `proposed`: suggested in the literature, never measured together with the hypothesis in a patient cohort. Each symptom with the hypotheses that point to it (today for example neurocognitive impairment: five hypotheses, none above step 1).
3. **Links not yet tested in patients.** Every link at step `proposed`, grouped by target node (card, symptom or open question), each as the link sentence with its source numbers as on the map page. This is the list a researcher looking for an unstudied pair would read. One sentence of context from the rubric: step 2 requires a study with a recognised case definition that measured both ends in the same patients.
4. **What the next rung requires.** Every hypothesis card grouped by its current level, with the ladder's requirement for the next rung quoted from the functional spec section 3 (one sentence per rung, as i18n strings), and the contested mark where present ("contested at rung 3: a study with a recognised definition found otherwise"). Level 2 cards uncontested read, in effect, "one controlled study in a defined cohort; no independent replication yet". No other text per card. Level 5 cards are listed without a requirement.

Also a small count line at the top of lists 1-3 and a closing line "Hypotheses with no links yet: …" (brain and brainstem MRI today), mirroring "Not yet placed".

Wording rules for the page: no "promising", "needs funding", "should be studied", "most", "best"; no ordering within a list other than the map's plan order and alphabetical. Every item carries the same sources as its card or node does elsewhere on the site; the page adds no new claim.

## Tooling

- `uv run python -m me_atlas.map report [--drafts]` prints the same four lists after "Candidate roots" (offline, no AI), so the editorial team and the survey (`docs/survey.md`) can use them without building the site. The symptom gap list is the natural input for the next `survey pairs` run; wiring it in is a follow-up, not this plan.
- Functions live in `src/me_atlas/map.py` next to `common_mechanisms` and `candidate_roots` (for example `unlinked_symptoms`, `proposed_only_symptoms`, `proposed_links`, `cards_by_level`, `unlinked_cards`). `site.py` gets the view in `_map_views` or a sibling, and a `gaps.html` template.
- Strings in `content/i18n/en.yaml` and `nb.yaml`: page title, intro, list headings and intros, the six rung requirement sentences, the contested sentence, the count lines. The Norwegian strings are written in the same PR and checked in review, like the other string files (`docs/translation.md`). Symptom names and link sentences are already translated (content files and card sidecars); no new translation step.

## Documents to update

- `docs/ME-Atlas-functional-spec.md` section 4: a "Gaps page" entry (shows / does not show), and in section 3 under "Causal map and links" one sentence: gaps are counted, not judged, like convergence.
- `docs/map.md`: the new report section and the page; move "weighting or scoring of nodes beyond the counts" from out of scope to a stated principle (it stays out).
- `docs/site.md`: the page in the page list.
- `docs/pm/DECISIONS.md`: the founder's ruling (below) and the rejection of the weighted score, with the why.
- `docs/pm/STATUS.md`: one line.

## Contract ("done" is)

1. `gaps.html` and `nb/gaps.html` build, are reachable from the navigation on every page in both languages, and contain the four lists above with counts that equal `map report --drafts` for the same input.
2. The page has no sentence without a source except the page's own intro, headings and the rubric sentences (which cite the methods page / spec section).
3. `map report` prints the four lists; a card set with no gaps prints "none" under each heading, as the convergence lists do.
4. Offline tests cover: a symptom with no incoming link, a symptom with only proposed links next to one with an associated link, a proposed link grouped under its target, a card at each level 0-5 with and without a contested mark, a card with no links; and that the page builds in both languages with no missing string.
5. No change to the card format, the validator, the drawn map or the card pages. Levels, layers and links untouched.
6. None of the banned words above appears in the strings; `ruff check` and `ruff format` clean; `pytest` green.
7. Spec, `docs/map.md`, `docs/site.md`, STATUS and DECISIONS updated as listed.

## Out of scope

- Any score, weight, sum or ranking of hypotheses from the map (rejected; see DECISIONS).
- Indirect reach ("explains X through Y"). If ever wanted, only through chains where every link is at least step 2, which is empty today.
- A symptom-by-hypothesis matrix (brainstormed as an alternative; can be a later plan if list 2 and 3 turn out not to be enough).
- Feeding the symptom gaps into `survey pairs` automatically.
- Gaps inside a card (missing full texts, unverified case definitions): those stay in `docs/pm/candidates.md` and the per-card notes.
- Contested marks on links, subgroup maps, anything on the front page.

## Founder ruling needed before implementation

- The gaps page as described: a fourth list view, counted not judged, no scoring. Default: yes.
- List 4 ("What the next rung requires"): keep, or drop it to lists 1-3 if listing cards by level reads as a ranking. Default: keep; it rearranges the front page's own information with the rubric's wording and adds nothing.
- Page name "What is missing" (Norwegian: "Hva mangler"). Default: yes.
