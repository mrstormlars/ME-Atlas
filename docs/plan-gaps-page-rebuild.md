# Plan: rebuild the "What is missing" page, with the replication list (idea I-01)

Follows `docs/plan-gaps-page.md` (the page as first built) and idea I-01 in `docs/pm/IDEAS.md`. Agreed with the founder in a brainstorm on 2026-11-17 (DECISIONS 2026-11-17, "Idea bank"). To be handed to `/orchestrator`.

## Why

The built page is about 4,600 words. About 3,200 of them are the section "Links not yet tested in patients", which prints the full text of 38 links that the causal map page already shows. The founder finds the page too crowded with text and wants tables and charts before prose, links to the cards and no text copied from them. The replication list of idea I-01 belongs on this page.

The idea bank described I-01 as "findings at level 2 that lack one independent replication". That cannot be derived by count: of the 11 cards at level 2, several have five or six supporting studies from different groups and still stand at level 2. The reason is in each card's `level_reason`, which is 300 to 1,200 words, and no card has a short field that says what is missing. So this plan shows the level 2 cards with counts from structured fields and a link to the reason on the card, and writes no new sentence about any card.

## Goal

`gaps.html` (and `nb/gaps.html`) becomes a page of tables and small charts, derived by code from `cards/` and the map content, with no card text on it. Target: about 1,200 words or fewer in the English build, the glossary explanations at the foot included.

## The page after the change

1. **At a glance** (`#gaps-summary`): unchanged.
2. **Hypotheses by level** (`#gaps-next-rung`, the id is kept so existing links hold): one table, one row per card, grouped by level from 0 to 5, within a level sorted by name. Columns:
   - hypothesis: the card name as a link to the card page;
   - level: number and rung name;
   - contested: the contested rungs, or empty;
   - supporting studies: number of studies with `role: supports`;
   - research groups: number of distinct non-empty `group` labels among those studies; when any supporting study has no `group`, the cell says so (for example "3, 2 studies with no group stated") and never counts a missing label as a group;
   - contradicting studies: number of studies with `role: contradicts`;
   - links: number of links out of the card (0 replaces the old list "Hypotheses with no links yet").

   Above the table, once, what each next rung requires, taken from the existing strings `rung.<n>.name` and `rung.<n>.meaning`; not repeated per card.
3. **The replication list** is the level 2 group of that table, with its own heading and id (`#gaps-level-2`) and the heading text "Level 2: not yet repeated by an independent group" (the meaning of rung 3 in the rubric, spec section 3). Each row's level cell links to the reason on the card page. The intro says in one sentence that the counts are counts of studies on the card, not a judgement of which finding is closest to replication, and that the reason for the level is on the card.
4. **Links not yet tested in patients** (`#gaps-untested-links`): one table, one row per link at step 1, sorted by target then source. Columns: from (card link), to (target link), support step. No link text, no reference numbers; the row links to the place on the map page where the link is shown with its text and sources. The count above the table stays.
5. **Removed:** the two lists "Symptoms with no link to any hypothesis" and "Symptoms linked only at step 1" (the summary table in section 1 already marks both), and the list "Hypotheses with no links yet" (now a column). The summary's "see" links point to what remains.

## Steps

1. **Contract first**, as checkable clauses, from "Done" below.
2. **Card page anchor.** Give the level-reason heading in `src/me_atlas/templates/card.html` a stable id (for example `level-reason`), so the table can link to it. No other change to the card page.
3. **View model.** In `src/me_atlas/site.py`, replace `GapLevel`/`GapCard` and the untested-link structures with what the tables need (counts per card, link rows without `LinkView` text). Counting helpers that are not about presentation go in `src/me_atlas/map.py` beside `cards_by_level`, and `map report` keeps printing the same counts as the page.
4. **Template and styles.** Rewrite `src/me_atlas/templates/gaps.html` sections 2 to 5 as above; reuse the `gaps-table` class and the existing stacked-cell behaviour on narrow screens (`data-label`). No JavaScript.
5. **Strings.** New and changed strings in `content/i18n/en.yaml`; remove the strings that are no longer used. Norwegian in `content/i18n/nb.yaml` through the translation path in `docs/translation.md`, checked by the `card-reviewer` in translation mode; `uv run python -m me_atlas.translations check` reports no stale item.
6. **Tests.** Update `tests/test_site_gaps.py` (offline, fixtures): the table rows and counts for a fixture set of cards; a supporting study with no `group` is reported, not counted; no link text and no `level_reason` text appears on the page; the level 2 group has its heading and id; anchors `#gaps-next-rung` and `#gaps-untested-links` still exist; both languages build.
7. **Documents.** Update the `gaps.html` row in `docs/site.md`, the gaps section of `docs/survey.md` if it names the lists, `docs/pm/IDEAS.md` (I-01 to `in progress`, then `done` when merged) and `docs/pm/STATUS.md`.
8. **Evaluator**, with the contract and the diff only. One branch (`feat/gaps-page-rebuild`), one pull request; the founder merges.

## Done

- The English `gaps.html` built from the published cards is about 1,200 words or fewer, measured as visible text.
- No sentence from any card's `core_claim`, `level_reason`, `contested.reason`, link text or study `finding` appears on the page; card names and rung names are the only card-derived text.
- Every number on the page is computed from `cards/` and the map content at build time, and equals what `map report` prints for the same lists.
- All 11 level 2 cards (as of 2026-11-17) appear in the level 2 group, each linking to the level reason on its card page.
- The page ranks nothing: rows are ordered by level and name (links: by target and source), and no wording says which hypothesis or replication is most promising, cheapest or closest.
- Norwegian is complete and in step; `uv run pytest` and `uv run ruff check .` pass; no file in `cards/`, `drafts/` or `translations/nb/` card content changes.

## Out of scope

- A new card field with one sentence on what is missing for the next level. If the table proves too terse, that is its own round: the sentence would be drafted, reviewed and audited for each card like any other card text.
- Ranking replications by cost or feasibility; judging which finding of a card is the one to replicate.
- Any new data source or AI reading step; ideas I-03, I-05, I-08 and I-14.
- Changes to the causal map page, the front page or the rubric.

## Open points for the orchestrator to settle in the contract

- Where on the map page a link row points: the existing anchor of the link's target, unless a per-link anchor already exists.
- Whether the `group` labels on the published cards are filled consistently enough for the "research groups" column to be honest. If many supporting studies have no label, show the column with the "no group stated" note as specified; do not fill labels in this change.
