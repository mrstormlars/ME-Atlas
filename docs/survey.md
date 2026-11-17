# Survey of the cached literature

Reference for `src/me_atlas/survey.py`. Plan and reasons: `docs/plan-hypothesis-and-link-survey.md`.

The whole PubMed query is cached in `data/cache/pubmed/`. The survey mines it, offline, for two things: themes (MeSH headings) that no card covers, and pairs of cards whose themes appear together in the same records. **Code counts and sorts; an agent reads only a shortlist; a candidate becomes a card only through the pipeline, where the auditor decides a new hypothesis against the inclusion rule (spec section 6); the founder decides the inclusion rule, the scope and removal.** Nothing here writes to `cards/`, `drafts/`, `content/` or `translations/`, and nothing sets a level, badge, layer or link. The only tracked output is `docs/pm/candidates.md`, written by `record-candidates`.

## Commands

```bash
uv run python -m me_atlas.survey check-themes
uv run python -m me_atlas.survey themes [--suggest SLUG | --context HEADING [--limit N]]
uv run python -m me_atlas.survey pairs [--unlinked] [--context SLUG-A SLUG-B [--limit N]]
uv run python -m me_atlas.survey record-candidates FILE --context CONTEXT-FILE
```

Options (with defaults) where a subcommand needs them: `--cache data/cache/pubmed`, `--cards cards`, `--drafts drafts` (a draft replaces the card with the same slug, as in `me_atlas.map`), `--themes config/card_themes.yaml`, `--stoplist config/survey_stoplist.txt`, `--out data/pipeline/<today>-survey`, `--candidates docs/pm/candidates.md`. All subcommands are offline. Cached records are read only through `pubmed.parse_xml`; a file that does not parse is counted and reported on stderr, and the run goes on.

| Subcommand | What it does |
|---|---|
| `check-themes` | Validates the theme file against the cards. Exit 0 or 1. |
| `themes` | Counts the MeSH headings over all cached records, drops the stoplist and the headings claimed by a card, and prints the rest by number of original studies: records, reviews (publication type `Review`), letters, comments and case reports, originals, originals since 2016, newest year, domain, near cards. Writes `<out>/themes.json` (the same fields and the sorted PMIDs per heading). |
| `themes --by-domain [--per-domain K]` | The balanced selection (default K = 3): for each survey domain in file order, its top K headings by original studies; then the non-survey domains with their heading counts; then every heading among the top 60 by original studies that has no domain. |
| `themes --suggest SLUG` | The MeSH headings of the cached records the card cites (its `pmid:` studies), by count, as a start for the card's theme entry. Cited PMIDs that are not cached are named on stderr. Stoplisted headings are marked. |
| `themes --context HEADING` | Writes `<out>/context/<heading-slug>.md` (see "Context files"). |
| `pairs` | For every pair of cards: the cached records that match both, as original studies and reviews, the newest year, and the link status (`a->b`, `b->a`, `both`, `none`) read from the cards' `links`. Sorted by original studies, then by slug pair. `--unlinked` prints only `none` pairs. Writes `<out>/pairs.json` with the PMIDs per pair. |
| `pairs --context A B` | Writes `<out>/context/<a>--<b>.md` for the records that match both cards, each marked `cited by: <slug>` or `cited by: neither`. |
| `record-candidates` | Checks an agent's candidate file and records it in `docs/pm/candidates.md` (see "Candidates"). |

An **original study** is a record with none of the publication types `Review`, `Systematic Review`, `Meta-Analysis`, `Letter`, `Comment`, `Editorial`, `Case Reports`. The census `originals` column counts these; `originals_recent` counts those with year `RECENT_FROM_YEAR` (2016) or later, which shows whether a theme is still studied (a heading that is mostly old, such as XMRV, falls sharply).

## Files

- `config/card_themes.yaml`: the theme file (below).
- `config/survey_domains.yaml`: the domain file (below).
- `config/survey_stoplist.txt`: generic MeSH headings the census ignores (demographics, study design and statistics, countries, questionnaires and scales, health-services headings, the disease headings themselves). One heading per line, `#` comments, blank lines ignored, matching ignores case. A heading that names a possible cause or mechanism does not belong here.
- `data/pipeline/<date>-survey/`: `themes.json`, `pairs.json`, `context/*.md` and the agent's `candidates/*.json`. Generated, not committed.
- `docs/pm/candidates.md`: the tracked candidate list, committed.

## Theme file

`config/card_themes.yaml` maps each card slug to the MeSH headings and terms that card covers:

```yaml
gut-microbiome:
  mesh: [Gastrointestinal Microbiome, Dysbiosis]   # 1 to 6 headings
  terms: [microbiome, microbiota]                  # 0 to 4 terms, whole words, any case
```

A record matches a card when one of the card's `mesh` headings is among its MeSH headings, or one of its `terms` occurs in the title or abstract as a whole word (not inside a longer word). Quote a heading that contains a comma (`"Endothelium, Vascular"`). The loader reports an error (exit 1) for a slug that is not a card in `cards/` or `drafts/`, a card without an entry, a `mesh` list with 0 or more than 6 items, more than 4 `terms`, an empty string, or an unknown key. A heading claimed by two cards is a warning that names both. Every card needs an entry, so a new card adds one in the same pull request. Start from `themes --suggest <slug>` and keep only the headings that are about the hypothesis. The file is reviewed in a pull request like `config/pubmed_query.txt`.

## Domain file

`config/survey_domains.yaml` is an ordered mapping `domain-key -> {label, survey, headings}`. The survey domains, in this order, are `immune`, `nervous_system`, `energy_metabolism`, `circulation_autonomic`, `infection`, `genetics_epigenetics` and `psychological_behavioural`: they hold mechanism headings, and `themes --by-domain` picks the top headings of each, so that a list sorted by count alone is not filled by one area. The non-survey domains (`survey: false`) are counted and never selected: `related_conditions` (other diagnoses ME/CFS is compared with or co-occurs with, psychiatric diagnoses included), `symptom_measures` (symptom and function measures such as Pain, Sleep, Cognition, Exercise), `treatment`, `reaction_to_illness` (coping with the illness, a reaction to it and not a cause) and `refuted` (headings of refuted hypotheses, listed with the reason and sources in `docs/pm/excluded-hypotheses.md`). `psychological_behavioural` holds headings of psychological or behavioural causal models. The loader reports an error (exit 1) naming the heading or key for a heading in two domains, an unknown key, a heading that is also on the stoplist and a heading in a card's `mesh` list. A heading with no domain is `unassigned`; `--by-domain` lists every unassigned heading among the top 60, which must be none on the real cache, so new headings are assigned in the pull request that makes them frequent. Treatment headings live in the `treatment` domain, not on the stoplist, so that they stay visible to the domains.

## Near coverage

A card entry in `config/card_themes.yaml` may have `related: [..]` (0 to 8 headings): census headings that stay in the census but sit near the card, for example Mitochondria near the energy card. Such a heading shows the cards that name it in the `near` column (sorted), and `themes --context` writes a "Near existing cards" block first, with each card's slug, name and core claim read from the card file (a draft replaces the card). The `hypothesis-surveyor` reads that block and sets `fits_existing_card` to one of those slugs when the records belong on that card. A related heading may not be in any card's `mesh` list or on the stoplist.

## Core pair matching

A record **matches** a card (as above) by any of its MeSH headings or a term in the title or abstract. It **core-matches** a card when one of the card's `mesh` headings is a major topic of the record (`PubMedRecord.mesh_major`: the descriptor, or one of its qualifiers, is marked major in PubMed) or one of the card's `terms` is in the title. `pairs` prints, per pair, `core` (original studies that core-match both cards), `originals` (original studies that match both cards in any way), reviews and the newest year, and sorts by `core`, then `originals`, then slug pair. A pair with `core` 0 and some originals is labelled `mentions only`: the two themes appear in the same records but neither is a main subject. `pairs.json` holds the core PMIDs. `pairs --context` lists the core-matching records first, each marked `match: core`, then the rest, under the same limit and budget.

## Context files

`themes --context` and `pairs --context` write the one file an agent reads. It lists the records with PMID, title, year, publication types, MeSH headings and abstract: reviews first, then original studies, newest first (in a pair file, core-matching records come before both). Letters, comments, case reports and records without an abstract come last, by title only. The file stops at `--limit N` records (default 40) or at `SURVEY_CHAR_BUDGET` characters, whichever comes first, and states at the top how many matching records were left out.

## Agent rule

The `hypothesis-surveyor` agent (`.claude/agents/hypothesis-surveyor.md`, sonnet, tools Read and Write) reads only the context file it is given, spec sections 2 and 3, and the list of card slugs and names. **It cites only PMIDs that are in the context file, never from memory**, and writes only its proposal under `data/pipeline/<date>-survey/candidates/`. `link-drafter` may be given the records from `pairs --context` in the same way. Code enforces the rule: `record-candidates` refuses a file with a PMID that is not in the context file.

## Candidates

`record-candidates` checks the agent's file, and writes nothing if anything fails (exit 1, each problem named): only known keys; every PMID in `cohort_studies` and `reviews` appears in the context file; `case_definition_in_abstract` is one of `Fukuda`, `CCC`, `ICC`, `IOM2015`, `Oxford`, `Holmes1988`, `CDC_unspecified`, `unverified`, `none`, `other`; `fits_existing_card` is `null` or a known slug; none of the banned words in `name`, `mechanism`, `finding`, `why`. On success it writes or updates one `##` section per candidate under "# Candidates" (or one bullet under "# Gaps on existing cards" when `fits_existing_card` is set), with the source heading, record counts, the cohort studies with their abstract-level case definition, the reviews, "Meets inclusion rule on abstracts: yes/no", `Status` and `Date`. Running the same file twice leaves the file unchanged. When an entry is updated, its `Status` line and first `Date` stay as they were, so a status set by hand is not lost. Statuses: `candidate`, `to draft`, `drafted as <slug>`, `declined: <reason>`.

Case definitions in a candidate were read from abstracts only. Full-text verification happens when a card is drafted (`docs/drafting-checklist.md`).

## Bridge search pilot

The bridge search pilot (`docs/pm/bridge-pilot.md`, queries in `config/bridge_pilot.yaml`) asks, for a relation A → B between two cards, whether a systematic review outside ME/CFS reports it. It lives in `me_atlas.bridge` and is run as `survey bridge`. Unlike the commands above it uses the network (PubMed), so it needs `CONTACT_EMAIL` (and optionally `NCBI_API_KEY`) in `.env` or the environment; without `CONTACT_EMAIL` it exits non-zero and makes no request.

```bash
uv run python -m me_atlas.survey bridge run [--config config/bridge_pilot.yaml] [--cards cards] [--cache-dir data/cache/bridge] [--out data/pipeline/<today>-bridge-pilot] [--screened-from COUNTS-FILE] [--ends config/bridge_ends.yaml]
uv run python -m me_atlas.survey bridge validate FILE --context CONTEXT-FILE [--cache-dir data/cache/bridge]
```

**`bridge run`** runs each question's two arms (`general`, `long_covid`) through `pubmed.PubMedClient` and applies the screening limit of 40 (protocol point 4): an arm with at most 40 hits is screened in full; with more, its `restricted` query is run and its first 40 ids in PubMed's default order are screened; if the restricted query returns 0, the first 40 ids of the unrestricted query are screened. For `long_covid` the `originals_count` query is run for its count only; no record is fetched. Records not yet cached are fetched and stored as raw XML under `<cache-dir>/pubmed/<pmid>.xml` (default `data/cache/bridge/`, apart from the ME/CFS cache `data/cache/pubmed/`, so the census and the weekly pipeline do not see them); cached records are not fetched again. It writes nothing to `cards/`, `drafts/`, `content/`, `translations/` or `docs/`.

Files under `<out>` (generated, not committed):

- `counts.json`: per question and arm, the query run, total count, restricted query and count (or null), originals query and count (long COVID arm only), the rule that picked the screened ids (`all`, `restricted`, `fallback_unrestricted`), the screened PMIDs, any PubMed warnings, the PMIDs that were screened but could not be listed (`not_listed_pmids`), and the run date.
- `context/<question-id>-<arm>.md`: the one file the agent reads, written also when no record was screened. The header gives `Question:`, `Arm:`, the A and B slugs and card names, the query, the counts and the rule; then every screened record in full (`## pmid:<digits>`, title, year, publication types, MeSH headings, abstract). There is no character budget: a record is never cut for length. A screened record that is not in the cache or cannot be read is named in the header line "Screened but not listed".
- `surveys/<question-id>-<arm>.json`: written by the agent, not by `run`.

**Pilot 2 options** (protocol: `docs/pm/bridge-pilot.md`, "Pilot 2: protocol").

- `--screened-from FILE` (a pilot 1 `counts.json`) makes no ESearch request. Each question's and arm's screened PMIDs, counts, rule and queries are taken from FILE. Before anything is written, each arm's `query` (and `restricted_query` and `originals_query` where FILE has them) is compared with the config character for character; a difference, or a question or arm of the config that FILE lacks, exits 1 with a message naming the question and arm, and no context file is written. Records missing from the cache are fetched with EFetch (`CONTACT_EMAIL` is then required) and named in the output and in `counts.json` (`fetched_pmids`); when none are missing the command needs no `CONTACT_EMAIL` and makes no request. `counts.json` records the source file as `screened_from`. Without this option `run` searches as before.
- `--ends FILE` (`config/bridge_ends.yaml`) loads `ends:` (card slug to definition text) and writes the pilot 2 context files. It exits 1 if the A or B slug of any question has no non-empty definition.

The **pilot 2 context file** has the pilot 1 header plus the line `Pilot: 2` and the lines `Definition of A:` and `Definition of B:`. Each record also has `- meta-analysis (PubMed publication type): yes|no` (yes only if PubMed lists `Meta-Analysis` among the publication types) and `- abstract: structured|unstructured` (structured when at least one `AbstractText` has a non-empty `Label`). A structured abstract is shown one section at a time (`### <label>`), and each finding section carries the marker `[FINDING SECTION]`: its `NlmCategory` is `RESULTS` or `CONCLUSIONS`, or its label (case-insensitive, whitespace collapsed) is one of `RESULTS`, `MAIN RESULTS`, `METHODS AND RESULTS`, `CONCLUSION`, `CONCLUSIONS`, `AUTHORS' CONCLUSIONS`, `REVIEWER'S CONCLUSIONS`, `DISCUSSION AND CONCLUSION`, `INTERPRETATION`. Sections are read from the cached raw XML.

**`bridge validate`** checks the agent's JSON against its context file and the cached records, exits 0 if it is valid and 1 with each problem named otherwise. The schema is the one in `.claude/agents/bridge-surveyor.md`: `question`, `arm` (both must match the context header) and `rows`. It rejects: unknown keys; a PMID that is not in the context file; a PMID listed twice; a screened PMID with no row; a `statement` outside `yes`, `no`, `animal_or_cell_only`; for `yes` rows a missing or invalid `relation` (`present`, `absent`, `inconsistent`), `direction` (`a_to_b`, `b_to_a`, `association`, `not_stated`), `meta_analysis` (true/false), `studies_pooled` (whole number of at least 1, or null), an empty `population` or `quote`; extra keys on `no` and `animal_or_cell_only` rows (only `pmid`, `statement` and an optional `note` are allowed); a banned word (promising, breakthrough, cure, hope, proven) in `population` or `note`; and a `quote` that is not found verbatim in the title or abstract of the cached record. Verbatim matching collapses whitespace only: case, punctuation and wording must match exactly.

**Which schema.** The context file decides: with the line `Pilot: 2` the pilot 2 schema applies, otherwise the pilot 1 schema above (unchanged). In the pilot 2 schema a `yes` row has exactly `pmid`, `statement`, `relation`, `population`, `direction`, `review_kind`, `quote_role`, `quote` and an optional `note`; `meta_analysis` and `studies_pooled` are unknown keys and rejected. Further rejections: `review_kind` missing or outside `systematic`, `narrative`, `not_a_review`; `quote_role` missing or outside `finding`, `background`, `aim`; a `yes` row whose `quote_role` is not `finding`; for a structured abstract, a quote not found verbatim (whitespace collapsed) inside one finding section (a quote from the title, from another section or across two sections is rejected); for an unstructured abstract, a quote not in the title or abstract. `no` and `animal_or_cell_only` rows and all other pilot 1 rejections are as before.

**Agent rule.** The `bridge-surveyor` agent (`.claude/agents/bridge-surveyor.md`, sonnet, tools Read and Write) reads only the context file it is given, writes one row per screened PMID from the title and abstract only, cites only PMIDs in the context file and never from memory, copies the quote verbatim, proposes no link, level, card text or treatment, and writes only to `data/pipeline/<run folder>/surveys/` (the folder that holds the context file's `context/`). For pilot 2 it also judges each end by the `Definition of A/B` lines and quotes only from a marked finding section of a structured abstract. Code enforces the PMID and quote rules through `bridge validate`. A fresh `card-reviewer` then checks every `yes` row against the cached record (protocol point 5).

First run: 2026-11-16, eight questions; results and limitations in `docs/pm/bridge-pilot.md`, section "Results". Second run (pilot 2, same records, tighter reading): 2026-11-17, with `--screened-from data/pipeline/2026-11-16-bridge-pilot/counts.json --ends config/bridge_ends.yaml`; results in the same file, section "Pilot 2: results".
