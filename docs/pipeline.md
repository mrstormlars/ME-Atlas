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
| 1 | `prepare [--since] [--reprocess]` | code | `papers.json` (papers in the fetch window that no earlier run processed), `cards.json` (slug, name, core claim), `prepare.json` (counts, newly retracted PMIDs cited on a card) |
| 2 | `paper-classifier` agent, then `record-classification` | haiku, code | `classify.json`, then `matches.json` (card/paper pairs to draft, papers stopped, possible new hypotheses) |
| 3 | `context <slug> <pmid>`, then `card-drafter` agent | code, sonnet | `context/<slug>-<pmid>.md`, `ops/<slug>-<pmid>-r<N>.json` |
| 4 | `apply <slug> <ops> [--round N]` | code | `checks/...-r<N>.json`, `applied/<slug>-<pmid>-r<N>/<slug>.yaml` and `changes.diff` |
| 5 | `card-reviewer` agent (pipeline mode), then `record-review <slug> <pmid> [--round N]` | opus, code | `review/<slug>-<pmid>-r<N>.json` |
| 6 | `translation-plan [--lang nb]`, then `card-translator` agent, `card-reviewer` agent (translation mode) and `translations apply` | code, sonnet, opus, code | `final/<slug>.yaml`, `translate/<slug>.json`, `translation-plan.json`, `translated/<slug>.json`, `translation-review/<slug>.json`; writes `translations/nb/<slug>.yaml` |
| 7 | `report` | code | `report.md` |
| 8 | `pr [--dry-run] [--no-pr]` | code | copies accepted results into `drafts/`, branch `pipeline/<date>`, commit, push, `gh pr create` with `report.md` as the description |

`log.jsonl` in the run directory records each `prepare`, `apply`, `record-classification` and `record-review` call. The whole directory is gitignored (`data/pipeline/`); the founder uses it to judge the agents' error rate before ending the calibration period.

By default each command after `prepare` works on the newest run in `data/pipeline/`. Options on every command: `--run-dir`, `--pipeline-dir`, `--cards-dir`, `--drafts-dir`, `--cache-dir`, `--spec`, `--translations-dir`. `prepare` also takes `--date` (the name of the run directory, default today) and `--force` (start a run of the same date again).

## What `prepare` selects

The papers in the fetch window (`window_pmids` of the run manifest, cached or not) that no earlier run has processed, minus any that are marked retracted. "Processed" is kept in a ledger, `data/pipeline/processed.json` (gitignored, shared by all runs: PMID to the date of the run). Only `report` writes to it, so a run that is aborted before `report` can be repeated and selects the same papers again. `prepare --reprocess` ignores the ledger. `prepare` prints how many papers it selected and how many it skipped as already processed. Retracted papers are never selected, and a newly retracted paper that a card cites is still flagged whatever the ledger says. A newly retracted paper that a card cites is listed in the report; it is the founder's decision how the card changes (spec section 3: a retracted study is removed from the evidence and the level re-assessed).

## The context file

`context/<slug>-<pmid>.md` is the only thing the drafter and the reviewer read about the paper. It holds: the card as it is now; spec section 3, the evidence ladder; the paper's PubMed record and abstract; the Europe PMC full text when the paper is open access, without its reference list; and sentences from the full text that may name a case definition. The full text is cut at `FULLTEXT_CHAR_BUDGET` (60,000 characters, a constant in `pipeline.py`); the file says `TRUNCATED` with both numbers when it cuts, and says so when there is no full text. It contains nothing the drafter wrote.

## Operations

The drafter writes a list of operations, not a card (`operations.py`). All keys are checked; an unknown key, an unknown field name, a duplicate study id, a paragraph index out of range or an `add_study` without a case-definition quote for a recognised definition is rejected with a message, and nothing is changed.

| Operation | Tier | What it does |
| --- | --- | --- |
| `add_study` | 1 | Appends a study (all Study fields; the id must be the paper itself). |
| `add_paragraph` | 1 | Appends a sourced paragraph to `level_reason`, `contested.reason`, `badges.*.reason`, `subgroups` or `early_signals`. |
| `replace_paragraph` | 1 | Replaces paragraph `index` of such a field. |
| `propose` | 2 | Sets the level, the contested mark or a badge, with the complete new reason. |

**How operations are applied.** As text splices, not through a YAML library, because round-tripping would lose this repository's comments and folded text. Only the lines of the named field are replaced or inserted; every other line stays byte-identical. After each operation the edited text is parsed again and compared with the same change made on the parsed data; any difference stops the run. Limits: a field written in flow style on one line, and CRLF line endings, are refused with a message; comments inside a field that is rewritten (a `propose` reason, one replaced paragraph) are lost, comments elsewhere stay. Adding a paragraph to a reason written as a single sourced text turns it into a list of two paragraphs, keeping the first one's words.

## Checks and the two rounds

`apply` never touches `drafts/`. It applies the operations to a copy, then runs the card validator (`cards validate`) and the citations check (`citations check`) on that copy and writes both results. A citation error that the card already had before the change is marked `preexisting` and does not fail the pair; warnings (C6) never do.

- A failed check: the drafter gets one retry with the errors. Still failing: the pair is skipped and the report says why.
- A passed check goes to the reviewer. The reviewer reads the context file, the operations and the applied result, never the drafter's reasoning (the operations file has no field for any).
- The reviewer gives every finding a severity. `must_fix`: wrong against the sources, the rubric or the checklist; a TODO or internal note in reader-facing text; a field missing that the card's other studies have; a study outside the card's scope; a missing limit that changes how a reader would read the result. `advisory`: wording that does not change meaning. Any `must_fix` means `reject`; `record-review` refuses an `accept` with a `must_fix` finding. A `reject` with only advisory findings is allowed.
- Reviewer says `reject`: the drafter gets one revised attempt (round 2) with the review. Rejected again, or the second attempt cannot pass the checks: **parking lot**. The change is not applied. Never a third round.
- `accept`: the pair goes into the pull request. If two accepted papers touch one card, `pr` applies their operations in turn to the draft and validates the combined result. If two accepted papers overwrite the same target (the same `replace_paragraph` field and index, or the same `propose` target), neither is applied and both go to the parking lot; other papers on the card are still applied.

## Translations

Stage 6, after the reviews and before the report, keeps the Norwegian text in step with the accepted English changes. Details, file shapes and the checks are in `docs/translation.md`. `translation-plan` takes each card with an accepted change and a file in `translations/nb/`, builds the card as it will be after the change (`final/<slug>.yaml`) and lists, in `translate/<slug>.json`, the items that need translating: `made_stale` (the English of a translated item changed), `new` (the change added the item), `already_stale`, `already_missing` or `already_invalid` (not caused by this run). A card with no translation file is listed under `untranslated_cards` and not planned: its first translation is a manual run. The translator writes `translated/<slug>.json`; the reviewer writes `translation-review/<slug>.json` without seeing the translator's reasoning; `translations apply` merges what passed the mechanical check and the review into `translations/nb/<slug>.yaml`; one second attempt for what was left out; the rest stays English on the site with a note. `pr` stages `translations/` with the drafts. A translation carries no level, badge or contested mark, so none of this is a tier decision.

## Reading the report

`report.md` (also the pull request description), in this order:

1. **Tier 2**, the founder decides: proposed level, contested mark or badge changes, each with the new reason, sources and the review verdict.
2. **Tier 1**: added studies and paragraphs.
3. **Parking lot**: changes still rejected after two rounds, with the reviewer's findings (severity shown, `must_fix` first) and what the drafter proposed. Accepted changes show the reviewer's remaining notes with their severity in the same way.
4. **Possible new hypotheses**: papers that fit no card. No card is drafted.
5. **Retracted papers cited on cards.**
6. **Skipped**: failed checks, no operations file, no review, papers stopped as reviews or off-topic.
7. **Pre-existing problems on cards**: citation-check errors the card already had (they do not block a new paper).
8. A table of every new paper and how it was classified.

When stage 6 ran, a **Translations** section sits between the parking lot / new hypotheses and the retraction list: per card, the items made stale by accepted changes, the items the changes added and how many were already stale or missing, and the cards with no translation yet.

## `pr`

`pr --dry-run` prints the `git` and `gh` commands and the files it would write, and runs nothing. `pr` checks that the current branch is `main`, creates `pipeline/<date>`, writes the accepted cards into `drafts/`, commits only those files and the `translations/` folder when there is one, pushes and runs `gh pr create --body-file report.md`. `pr --no-pr` creates the branch and the commit and stops there. With no accepted change it does nothing. The `.githooks/pre-push` hook still forbids pushing to `main`.

## Tests

`tests/test_operations.py` and `tests/test_pipeline.py`, with fictional papers and agent outputs in `tests/fixtures/pipeline/`. The fetch, the full-text loader and the subprocess runner are injected; no test touches the network, an AI or git.
