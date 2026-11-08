# Plan: hypothesis and link survey of the fetched literature

November 8, 2026 · For `/orchestrator`. Direction agreed with the founder in a brainstorm the same day: mine the ME/CFS literature we already hold (A: themes without a card, B: links between the cards) before looking anywhere else. Sources outside the ME/CFS literature are out of scope here (see "Out of scope").

## Why

The whole PubMed query has been fetched and cached (9,366 records on 2026-11-08, of which 1,571 are reviews), but only the weekly window is ever classified, and the classifier can do no more than mention a possible new hypothesis in the report. The 17 draft cards were chosen by hand from the plan's candidate list and the founder's knowledge of the field. The 23 links came from two passes over a handful of reviews; four cards (brain MRI, endothelial dysfunction, NK cell function, tryptophan) have no link at all.

A quick offline count of MeSH headings over the cache shows themes with many records and no card (cytokines 203, skeletal muscle 100, autonomic nervous system 96, mitochondria 91, circadian rhythm 66, gene expression profiling 62, T lymphocytes 49), and the same records can tell us which pairs of hypotheses have been measured in the same patients. Both questions can be answered mostly by code, with an agent reading only a shortlist, and nothing cited from memory.

## Design decisions (brainstorm 2026-11-08, accepted by the founder)

1. **Code counts, an agent reads, the founder decides.** Two offline commands over the cache do the sorting: a theme census (A) and a pair co-mention search (B). An agent reads only the records the code selected and writes a proposal file; code validates that every id in a proposal is one the agent was given. Nothing is written to `cards/` or `drafts/` by this work.

2. **No knowledge graph, no embeddings, no new dependency.** MeSH headings (already parsed into `PubMedRecord.mesh_terms`) plus a few title/abstract terms per card are the whole matching method. It is explainable in one sentence on the methods page and reproducible from the cache.

3. **A theme file maps each card to the headings and terms it covers**: `config/card_themes.yaml`, reviewed in a pull request like the search query, so that "covered by a card" and "pair of cards" mean the same thing in both commands. The card format does not change. A first draft of each card's entry is suggested by code from the MeSH headings of the studies the card already cites, so the themes are grounded in the card's own sources, then edited by hand.

4. **v1 stays at 15 to 20 cards.** The census ends in a tracked candidate list, `docs/pm/candidates.md` (spec section 2: ideas may be tracked internally as candidates), not in new cards. The founder picks at most three candidates to draft now, through the existing manual card process (`docs/drafting-checklist.md`, `card-reviewer`, founder ruling). The rest wait, with their counts and ids, for a later version. A refuted or historical hypothesis that the census surfaces (XMRV, 119 records) is listed like any other; whether a contradicted hypothesis deserves a card is the founder's call.

5. **The inclusion rule is applied at two depths.** The surveying agent judges a candidate on abstracts only: it reports which records are cohort studies and which of them name a recognised case definition in the abstract, marks the rest `unverified`, and says whether the candidate meets the rule on that evidence. Full-text verification of case definitions happens only when a card is drafted, as for every card today.

6. **Links come out of the same process as the first mapping.** The pair search selects the records; `link-drafter` proposes, `card-reviewer` (map mode) checks, the founder rules, and the Norwegian items go through `card-translator`. `link-drafter` is widened from "cached review records" to "cached records" (reviews or original studies), because a study that measured both ends in the same patients is what step 2 of the link rubric needs. The link rubric in spec section 3 does not change.

7. **Priority stays with the weekly pipeline.** The live check of `/ukentlig` (STATUS priority 1) is not displaced by this plan; the survey is a one-off pass that the weekly run can later repeat on its window (out of scope here).

## What the commands do

Package module `src/me_atlas/survey.py`, command `uv run python -m me_atlas.survey <subcommand>`, offline, reads only `data/cache/pubmed/` (and `config/`), writes under `data/pipeline/<date>-survey/`. Records are parsed with the existing `pubmed.parse_xml`.

### `themes` (A)

- Counts MeSH descriptors over every cached record. Drops the headings in `config/survey_stoplist.txt` (generic headings: Humans, Female, study-design headings, countries, psychometrics and so on; one per line, comments allowed) and the headings claimed by any card in `config/card_themes.yaml`.
- Prints the remaining headings by count with, per heading, the number of records, how many are reviews (publication type `Review`), how many are letters, comments or case reports, and the newest year. Writes `themes.json` with the same data plus the PMIDs per heading.
- `--suggest <slug>` prints, for one card, the MeSH headings of the records that card cites (ids read from the card file), by count, as a starting point for its `card_themes.yaml` entry.
- `--context <heading> [--limit N]` writes `context/<heading-slug>.md`: title, year, publication types, MeSH headings and abstract of up to N records with that heading, reviews first and then original studies newest first, within a character budget (a constant, like `FULLTEXT_CHAR_BUDGET` in the pipeline). The file says how many records were left out. Letters, comments and records without an abstract are listed by title only.

### `pairs` (B)

- For every unordered pair of cards in `card_themes.yaml`, finds the cached records that match both cards: a record matches a card when one of the card's MeSH headings is among its `mesh_terms`, or one of its terms occurs in title or abstract (case-insensitive, whole word).
- Prints the pairs by number of matching original studies (non-review records), each with the counts (original studies, reviews), whether a link between the two cards already exists in either direction (read from `drafts/` and `cards/`, drafts replacing cards of the same slug) and the newest year. `--unlinked` shows only pairs with no link. Writes `pairs.json` with the PMIDs per pair.
- `--context <slug-a> <slug-b> [--limit N]` writes `context/<slug-a>--<slug-b>.md` like `themes --context`, for the records matching both cards. It names, at the top, which of the two cards already cites each record.

### `record-candidates`

- Reads an agent's candidate file for one heading (shape below), checks it (every PMID is in that heading's context file, every key is known, text has none of the banned words), and appends or updates the entry in `docs/pm/candidates.md`. Refuses a file with an unknown PMID and prints why.

## The agent

A new agent, `.claude/agents/hypothesis-surveyor.md` (model: sonnet; tools: Read, Write), with the same shape of rules as `link-drafter`: read only the context file it is given, spec sections 2 and 3, and the list of existing card slugs and names; cite only ids in the context file; never from memory; no treatment advice; no banned words; write only the proposal file under `data/pipeline/<date>-survey/candidates/`. It writes one JSON object per heading:

```json
{
  "heading": "Cytokines",
  "candidates": [
    {
      "name": "Altered cytokine profile",
      "mechanism": "One plain sentence saying what the hypothesis claims goes wrong.",
      "fits_existing_card": null,
      "cohort_studies": [
        {"pmid": "00000000", "case_definition_in_abstract": "Fukuda", "n": 40, "finding": "one sentence"},
        {"pmid": "00000001", "case_definition_in_abstract": "unverified", "n": null, "finding": "one sentence"}
      ],
      "reviews": ["00000002"],
      "meets_inclusion_rule_on_abstracts": true,
      "why": "For the founder: which record(s) carry the inclusion rule and what is uncertain."
    }
  ]
}
```

- One heading may yield zero, one or several candidates (a heading such as "Cytokines" may hold two distinct hypotheses).
- `fits_existing_card` is a slug when the records belong on an existing card rather than a new one (then the entry is a gap on that card, and `candidates.md` lists it under "Gaps on existing cards" for the weekly pipeline or a manual pass to pick up), otherwise `null`.
- `case_definition_in_abstract` uses the card format's values (`Fukuda`, `CCC`, `ICC`, `IOM2015`, `Oxford`, `Holmes1988`, `CDC_unspecified`, `unverified`, `none`), read from the abstract only.

`docs/pm/candidates.md` has one section per candidate: name, the heading(s) it came from, record counts, the cohort studies with their abstract-level case definition, the reviews, `meets inclusion rule on abstracts: yes/no`, status (`candidate`, `to draft`, `drafted as <slug>`, `declined: <reason>`) and the date. A second section, "Gaps on existing cards", lists the `fits_existing_card` findings. The weekly report's "possible new hypotheses" items are added to this file by hand when the founder reads the report; the file is the one place for candidates.

## Steps

1. `config/survey_stoplist.txt` and the `themes` command with its tests (fictional cached records in `tests/fixtures/`: a stoplisted heading is dropped, a card-claimed heading is dropped, counts and review split are right, `--suggest` lists the headings of a card's cited records, `--context` respects the limit and budget and orders reviews first).
2. `config/card_themes.yaml` for all 17 draft cards: run `themes --suggest` per card, edit by hand, 2 to 6 MeSH headings and 0 to 4 terms per card. Validation: every slug exists in `drafts/` or `cards/`, no heading claimed by two cards unless both say so in a comment (print a warning, not an error).
3. The `pairs` command with tests (a record matching two fictional cards is counted for that pair; an existing link in either direction is detected; `--unlinked` filters; `--context` names which card cites which record).
4. The `hypothesis-surveyor` agent, the `record-candidates` command with tests (unknown PMID refused, banned word refused, update of an existing entry), and `docs/pm/candidates.md` created with its two sections empty.
5. Widen `link-drafter`'s description and reading list from review records to records; one sentence in `docs/map.md`.
6. `docs/survey.md` reference (commands, files, the rule that nothing is cited outside the context file); STATUS updated. Spec section 2 gets one sentence saying where candidates are tracked.
7. **First survey run (after the code is merged, a separate PR):** `themes --by-domain` over the cache; the founder picks the headings to read (default: the selection of `themes --by-domain` with K = 3, the top 3 headings of each survey domain); `themes --context` and `hypothesis-surveyor` per heading; `record-candidates`; the founder marks at most three as `to draft`. `pairs --unlinked`; the founder picks the pairs (default: the 20 pairs with most core matches, and every pair that includes one of the four unlinked cards); `pairs --context`, `link-drafter` per upstream card, `card-reviewer` map mode, founder rulings in DECISIONS, translation of new items. Drafting the chosen cards follows as its own work, one card at a time, through the existing manual process.

## Done when

- [ ] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` pass; no test touches the network or an AI; no new dependency.
- [ ] `uv run python -m me_atlas.survey themes` on the cache prints uncovered headings with counts and review split and writes `themes.json`; `--suggest <slug>` works for every draft card; `--context` writes a file within the budget (tested on fixtures).
- [ ] `uv run python -m me_atlas.survey pairs` prints every card pair with counts and link status and writes `pairs.json`; `--unlinked` and `--context` work (tested on fixtures).
- [ ] `record-candidates` refuses a PMID not in the context file and a banned word, and updates `docs/pm/candidates.md` idempotently (tested).
- [ ] `config/card_themes.yaml` covers all 17 cards and validates; `config/survey_stoplist.txt` exists with a comment saying what belongs there.
- [ ] `hypothesis-surveyor` exists with the reading restrictions and the file shape above; `link-drafter` accepts records of any publication type.
- [ ] `docs/survey.md`, `docs/map.md` sentence, spec section 2 sentence, STATUS: written. No card, draft, level, link or layer changed by this PR.
- [ ] Step 7 is a separate PR after this one, so the code is reviewed apart from the surveyed content.

## Out of scope

- **Sources outside the ME/CFS literature** (general microbiome, immunology or metabolism research used to propose a link between two cards). The link rubric grades "A drives B in ME/CFS patients", and a source from another population states only "A drives B"; using it needs a founder ruling in DECISIONS first (a separate marking such as "proposed from research outside ME/CFS", only between two existing cards, only where the ME/CFS literature has no source). Candidate for a later plan once A and B have shown what the ME/CFS literature alone yields.
- Widening the PubMed query (long COVID alone, fibromyalgia, POTS and other related conditions).
- Embeddings, clustering, topic models or any method beyond MeSH headings and whole-word terms.
- Drafting the candidate cards themselves (follows per card through the existing process); more than 20 cards in v1.
- Running the survey inside `/ukentlig` (repeat `pairs` on the weekly window; feed `new_hypothesis` items into `candidates.md` automatically). Later, once the one-off run has shown the shape of the output.
- Changing the evidence ladder, the link rubric, any level, badge, contested mark, layer or link.

## For the founder to confirm (defaults taken in this plan)

- `docs/pm/candidates.md` as the tracked candidate list, committed to the repository, with the statuses above.
- Defaults for the first run: the headings chosen by `themes --by-domain` with K = 3 (the top 3 uncovered headings by original studies in each of the seven survey domains, so the list is not dominated by psychiatric and older headings); the 20 pairs with most core matches (card heading as major topic, or term in the title) plus every pair involving an unlinked card; at most three candidates drafted now.
- The surveyor runs on sonnet and reads abstracts only; full texts are fetched only when a card is drafted.
