# Weekly pipeline

How new papers reach the draft cards. Plan: `docs/plan-weekly-pipeline.md`. Code: `src/me_atlas/pipeline.py` (the steps code can do) and `src/me_atlas/operations.py` (what the drafter may change). Rules: functional spec section 6.

If this page and the code disagree, the code is right and this page is a bug.

## How to run it

In a Claude Code session in the repository, type:

```
/ukentlig                          # the last 14 days
/ukentlig --since 2026-10-01       # a longer window
/ukentlig --no-pr                  # everything except pushing and opening the pull request
```

The command (`.claude/commands/ukentlig.md`) drives the stages below. AI work is done by four subagents on the subscription: no API key and no `anthropic` calls. Nothing is published. The result is a pull request; merging it puts the drafts on `main`, and moving a card into `cards/` is a separate founder decision. The calibration period (spec section 6) continues: the founder approves every change.

## Stages

| # | Command | Who | Output in `data/pipeline/<date>/` |
| --- | --- | --- | --- |
| 1 | `prepare [--since] [--reprocess]` | code | `papers.json` (papers in the fetch window that no earlier run processed, and preprints that survive de-duplication), `cards.json` (slug, name, core claim), `prepare.json` (counts, newly retracted PMIDs cited on a card, the preprint counts and every dropped preprint with its reason, cards that cite a preprint with a published version) |
| 2 | `paper-classifier` agent, then `record-classification` | haiku, code | `classify.json`, then `matches.json` (card/paper pairs to draft, papers stopped, possible new hypotheses) |
| 3 | `context <slug> <key>`, then `card-drafter` agent | code, sonnet | `context/<slug>-<key>.md`, `ops/<slug>-<key>-r<N>.json` |
| 4 | `apply <slug> <ops> [--round N]` | code | `checks/...-r<N>.json`, `applied/<slug>-<key>-r<N>/<slug>.yaml` and `changes.diff` |
| 5 | `card-reviewer` agent (pipeline mode), then `record-review <slug> <key> [--round N]` | opus, code | `review/<slug>-<key>-r<N>.json` |
| 6 | `translation-plan [--lang nb]`, then `card-translator` agent, `card-reviewer` agent (translation mode) and `translations apply` | code, sonnet, opus, code | `final/<slug>.yaml`, `translate/<slug>.json`, `translation-plan.json`, `translated/<slug>.json`, `translation-review/<slug>.json`; writes `translations/nb/<slug>.yaml` |
| 7 | `report` | code | `report.md` |
| 8 | `pr [--dry-run] [--no-pr]` | code | copies accepted results into `drafts/`, branch `pipeline/<date>`, commit, push, `gh pr create` with `report.md` as the description |

`log.jsonl` in the run directory records each `prepare`, `apply`, `record-classification` and `record-review` call. The whole directory is gitignored (`data/pipeline/`); the founder uses it to judge the agents' error rate before ending the calibration period.

By default each command after `prepare` works on the newest run in `data/pipeline/`. Options on every command: `--run-dir`, `--pipeline-dir`, `--cards-dir`, `--drafts-dir`, `--cache-dir`, `--spec`, `--translations-dir`. `prepare` also takes `--date` (the name of the run directory, default today) and `--force` (start a run of the same date again).

## What `prepare` selects

The papers in the fetch window (`window_pmids` of the run manifest, cached or not) that no earlier run has processed, minus any that are marked retracted. "Processed" is kept in a ledger, `data/pipeline/processed.json` (gitignored, shared by all runs: PMID to the date of the run). Only `report` writes to it, so a run that is aborted before `report` can be repeated and selects the same papers again. `prepare --reprocess` ignores the ledger. `prepare` prints how many papers it selected and how many it skipped as already processed. Retracted papers are never selected, and a newly retracted paper that a card cites is still flagged whatever the ledger says. A newly retracted paper that a card cites is listed in the report; it is the founder's decision how the card changes (spec section 3: a retracted study is removed from the evidence and the level re-assessed).

## Preprints

`prepare` also searches Europe PMC for preprints first indexed in the same window (`config/europepmc_preprint_query.txt`; the facts about the API and the cache are in `docs/fetch.md`, "Preprints (Europe PMC)"). The search is a function that tests inject, like the PubMed fetch; a failed search fails `prepare` before anything is written. Each preprint is dropped for the first matching reason, and `prepare.json` lists every drop under `preprints.dropped` (PPR id, DOI, reason and details) with `preprints.counts` (found, dropped per reason, offered):

| Reason | Meaning |
| --- | --- |
| `published` | it has a "Preprint of" link to a PubMed record (the PMID, whether it is in the PubMed cache, and the link's note are listed) |
| `in_pubmed` | its DOI (case-insensitive) is the DOI of a record in this run's PubMed window or in the PubMed cache |
| `superseded` | a higher version, whose PPR id is in the same search, exists |
| `duplicate_doi` | several records share this DOI (case-insensitive); the one with the highest version number, then the highest PPR number, is kept and the others are dropped (judged after `published` and `in_pubmed`; the row names the one kept) |
| `no_doi` | no DOI, so it cannot be cited |
| `processed` | the ledger has its PPR id (unless `--reprocess`) |

Survivors are added to `papers.json` after the PubMed papers: `id` `doi:<doi>`, `pmid` null, `preprint` true, `ppr_id`, `journal` the preprint server, `publication_types` ["Preprint"] and `entry_date` the first index date. Every PubMed paper also has `preprint` (true for a PubMed record with the publication type "Preprint", such as pmid:42996068; that record keeps its PMID and flows as any other paper). The ledger holds a preprint under its PPR id, in the same file; PMIDs come first, in numeric order, so a ledger written before preprints reads unchanged.

A classification names its paper by exactly one of `pmid` or `id` (`doi:<doi>`, for a preprint with no PMID); both, neither, an unknown id, a repeated paper and a missing paper are rejected. A DOI-only preprint that matches a card goes into `matches` as `{slug, id}` (a PubMed pair is `{slug, pmid}`) and is drafted, checked and reviewed like any other pair, with the differences below. A preprint that PubMed also holds is a PubMed paper; its context file says it is a preprint and that it can only be added with `preprint: true` and `role: early_signal`.

**The paper key.** Every file of a pair is named `<slug>-<key>…` (`context/`, `ops/`, `checks/`, `review/`, `applied/`). The key is the PMID digits for a PubMed paper (unchanged) and the PPR id (`PPR<digits>`) for a DOI-only preprint, read from `papers.json`. `context`, `apply` and `record-review` take the paper as `<pmid>`, `pmid:<pmid>`, `doi:<doi>` or the PPR id and resolve it against this run's `papers.json`; a `doi:` or PPR id that is not a DOI-only preprint of this run is an error naming it. In an ops file and a review file the paper is `doi:<doi>`.

**Context for a DOI-only preprint.** Built only from its cached Europe PMC record (`europepmc preprint <doi>` caches it; without it `context` stops and names the DOI and that command): id, Europe PMC id, title, server, year, first index date, version, abstract (HTML tags removed), the preprint rule, and the note that the case definition comes from the abstract or the full text, otherwise `unverified`. Full text goes through `get_fulltext(..., preprint=record)` with the same status notes as for a PubMed paper, and the same case-definition sentence lists when there is text.

**Apply, review, report.** An ops file whose `paper` is `doi:<doi>` is checked like any other (validator including V15, citation check against the cached preprint record: C1, C2, C3, C5, C6); its `add_study` must have `preprint: true`, and every operation in it is tier 2. `record-review` expects `paper: "doi:<doi>"` for that pair. The report links the paper to `https://doi.org/<doi>` with the title from the cached record. Conflict parking and the final card text treat the pair as any other.

A study marked `preprint: true` on a card or draft whose cached preprint record (or this run's search result) has a "Preprint of" link is listed in `prepare.json` under `preprints_published` and in the report under "Preprints on cards with a published version". No operation is written; the founder decides.

**Tier 2.** An operation that adds a study with `preprint: true`, or cites a study marked `preprint: true` (on the card or in the same file) in its sources, is tier 2; so is every operation of an ops file whose paper is a `doi:` preprint (the founder approves), until the founder rules otherwise. `apply` counts it in `tiers` and the report lists it under tier 2.

## The context file

`context/<slug>-<pmid>.md` is the only thing the drafter and the reviewer read about the paper. It holds six sections, numbered 1 to 6 with no number repeated: (1) the card as it is now; (2) the inclusion rule (spec section 2); (3) the rubric, the evidence ladder (spec section 3); (4) the paper's PubMed record and abstract; (5) the Europe PMC full text when the paper has open full text, without its reference list; (6) sentences from the full text, in two lists under their own labels: sentences that may name a case definition, and sentences that may exclude people with the illness (an exclusion wording together with ME/CFS, CFS or the illness's full name). The second list tells the reader to check whether ME/CFS itself was what the study excluded. The spec excerpts keep their text, but their headings are one level lower, so the only level-2 headings are the six above. If the spec has no section 2 followed by section 3, `context` stops with a message. "Oxford" in a sentence counts as a case definition only when it is not an affiliation, publisher, place or vendor ("University of Oxford", "Oxford University Press", "Oxford, UK", "Oxford Instruments").

The full text note depends on what Europe PMC gave. The PMC id from the cached PubMed record is passed on, because Europe PMC can lack it for a while. `open_access`: the XML has a real body and is used. `pdf_only`: a PMC record exists (with its id), but its full text is a PDF only and it was not read; nothing is cached. `pmc_no_xml`: a PMC record exists (with its id) and Europe PMC has no full-text XML for it. With no PMC id anywhere the file says there is no open full text. A cached lookup that found no open full text is asked again after 7 days (`LOOKUP_MAX_AGE_DAYS`). No PDF is ever downloaded or parsed. The full text is cut at `FULLTEXT_CHAR_BUDGET` (60,000 characters, a constant in `pipeline.py`); the file says `TRUNCATED` with both numbers when it cuts, and says so when there is no full text. It contains nothing the drafter wrote.

## Operations

The drafter writes a list of operations, not a card (`operations.py`). All keys are checked; an unknown key, an unknown field name, a duplicate study id, a paragraph index out of range or an `add_study` without a case-definition quote for a recognised definition is rejected with a message, and nothing is changed.

| Operation | Tier | What it does |
| --- | --- | --- |
| `add_study` | 1 (2 with `preprint: true`) | Appends a study (all Study fields; the id must be the paper itself). `preprint` is written only when true. |
| `add_paragraph` | 1 (2 if it cites a preprint study) | Appends a sourced paragraph to `level_reason`, `contested.reason`, `badges.*.reason`, `subgroups` or `early_signals`. |
| `replace_paragraph` | 1 (2 if it cites a preprint study) | Replaces paragraph `index` of such a field. |
| `propose` | 2 | Sets the level, the contested mark or a badge, with the complete new reason. |

**How operations are applied.** As text splices, not through a YAML library, because round-tripping would lose this repository's comments and folded text. Only the lines of the named field are replaced or inserted; every other line stays byte-identical. After each operation the edited text is parsed again and compared with the same change made on the parsed data; any difference stops the run. Limits: a field written in flow style on one line, and CRLF line endings, are refused with a message; comments inside a field that is rewritten (a `propose` reason, one replaced paragraph) are lost, comments elsewhere stay. Adding a paragraph to a reason written as a single sourced text turns it into a list of two paragraphs, keeping the first one's words.

## Checks and the two rounds

`apply` never touches `drafts/`. It applies the operations to a copy, then runs the card validator (`cards validate`) and the citations check (`citations check`) on that copy and writes both results. A citation error that the card already had before the change is marked `preexisting` and does not fail the pair; warnings (C6) never do. A "TODO" in the name, a sourced text or a study's `finding` fails the pair through the validator rule V14. `group` stays optional, but when every study already on the card has a `group` and an added study has none, `apply` adds one line to the `warnings` list of the checks record for that study and prints it as `warning: ...`. A warning never changes `passed` or the exit code. It is shown in the report next to the reviewer notes of an accepted pair. Because the copy sits alone, a link from it to another card (rule M2) is resolved against the card files in `--drafts-dir` and `--cards-dir`; a link to a slug found in neither fails the check.

- A failed check: the drafter gets one retry with the errors. Still failing: the pair is skipped and the report says why.
- A passed check goes to the reviewer. The reviewer reads the context file, the operations and the applied result, never the drafter's reasoning (the operations file has no field for any).
- The reviewer gives every finding a severity. `must_fix`: wrong against the sources, the rubric or the checklist; a TODO or internal note in reader-facing text; a field missing that the card's other studies have; a study outside the card's scope; a missing limit that changes how a reader would read the result. `advisory`: wording that does not change meaning. Any `must_fix` means `reject`; `record-review` refuses an `accept` with a `must_fix` finding. A `reject` with only advisory findings is allowed.
- Reviewer says `reject`: the drafter gets one revised attempt (round 2) with the review. Rejected again, or the second attempt cannot pass the checks: **parking lot**. The change is not applied. Never a third round. If round 2 passes the checks with no operations after a rejection in round 1, the drafter has withdrawn the change: the pair is `withdrawn`, not `no_change`, and the report keeps the reviewer's findings and what was proposed in round 1. Nothing is applied for it, and `pr` and `translation-plan` write nothing for it. A review file may carry an optional `not_on_card`, one non-empty line: the reviewer's reason to list the paper in the card header's "Not on the card" list (set when a `must_fix` finding says the study is outside the card's scope or stated exclusions). `record-review` refuses an empty string. The report prints it on its own line for the pair.
- `accept`: the pair goes into the pull request. If two accepted papers touch one card, `pr` applies their operations in turn to the draft and validates the combined result. If two accepted papers overwrite the same target (the same `replace_paragraph` field and index, or the same `propose` target), neither is applied and both go to the parking lot; other papers on the card are still applied.

## Translations

Stage 6, after the reviews and before the report, keeps the Norwegian text in step with the accepted English changes. Details, file shapes and the checks are in `docs/translation.md`. `translation-plan` takes each card with an accepted change and a file in `translations/nb/`, builds the card as it will be after the change (`final/<slug>.yaml`) and lists, in `translate/<slug>.json`, the items that need translating: `made_stale` (the English of a translated item changed), `new` (the change added the item), `already_stale`, `already_missing` or `already_invalid` (not caused by this run). A card with no translation file is listed under `untranslated_cards` and not planned: its first translation is a manual run. The translator writes `translated/<slug>.json`; the reviewer writes `translation-review/<slug>.json` without seeing the translator's reasoning; `translations apply` merges what passed the mechanical check and the review into `translations/nb/<slug>.yaml`; one second attempt for what was left out; the rest stays English on the site with a note. `pr` stages `translations/` with the drafts. A translation carries no level, badge or contested mark, so none of this is a tier decision.

## Reading the report

`report.md` (also the pull request description), in this order:

1. **Tier 2**, the founder decides: proposed level, contested mark or badge changes, and anything that adds or cites a preprint, each with the new reason, sources and the review verdict.
2. **Tier 1**: added studies and paragraphs.
3. **Parking lot**: changes still rejected after two rounds, with the reviewer's findings (severity shown, `must_fix` first) and what the drafter proposed. Accepted changes show the reviewer's remaining notes with their severity in the same way, and any `group` warnings from `apply`. The parking lot also shows `not_on_card` when the reviewer set it.
4. **Rejected by the reviewer, then withdrawn**: pairs where round 1 was rejected and round 2 proposed nothing. For each: the round of the rejection, every finding of the rejecting review (severity shown, `must_fix` first, problem and suggested fix in full), what the drafter proposed in the rejected round, and the reviewer's `not_on_card` line when there is one. `None.` when there is no such pair. The summary sentence at the top counts these pairs on their own.
5. **Possible new hypotheses**: papers that fit no card. No card is drafted.
6. **Preprints on cards with a published version** (see "Preprints"). A preprint pair that was drafted is in the tier lists above, always tier 2.
7. **Retracted papers cited on cards.**
8. **Skipped**: failed checks, no operations file, no review, papers stopped as reviews or off-topic.
9. **Pre-existing problems on cards**: citation-check errors the card already had (they do not block a new paper).
10. A table of every new paper and how it was classified.

When stage 6 ran, a **Translations** section sits between the parking lot / new hypotheses and the retraction list: per card, the items made stale by accepted changes, the items the changes added and how many were already stale or missing, and the cards with no translation yet.

## `pr`

`pr --dry-run` prints the `git` and `gh` commands and the files it would write, and runs nothing. `pr` checks that the current branch is `main`, creates `pipeline/<date>`, writes the accepted cards into `drafts/`, commits only those files and the `translations/` folder when there is one, pushes and runs `gh pr create --body-file report.md`. `pr --no-pr` creates the branch and the commit and stops there. With no accepted change it does nothing. The `.githooks/pre-push` hook still forbids pushing to `main`.

## Tests

`tests/test_operations.py` and `tests/test_pipeline.py`, with fictional papers and agent outputs in `tests/fixtures/pipeline/`. The fetch, the preprint search, the full-text loader and the subprocess runner are injected; no test touches the network, an AI or git.
