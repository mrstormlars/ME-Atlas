# Survey of the cached literature

Reference for `src/me_atlas/survey.py`. Plan and reasons: `docs/plan-hypothesis-and-link-survey.md`.

The whole PubMed query is cached in `data/cache/pubmed/`. The survey mines it, offline, for two things: themes (MeSH headings) that no card covers, and pairs of cards whose themes appear together in the same records. **Code counts and sorts; an agent reads only a shortlist; the founder decides.** Nothing here writes to `cards/`, `drafts/`, `content/` or `translations/`, and nothing sets a level, badge, layer or link. The only tracked output is `docs/pm/candidates.md`, written by `record-candidates`.

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
