---
description: Weekly pipeline. Fetches new papers, classifies them, drafts and reviews card updates, and opens the weekly pull request for the founder.
model: inherit
---

You run the weekly ME Atlas pipeline in this session, on the founder's subscription. Speak Norwegian with the founder; every file, command and agent prompt stays in English. Reference: `docs/pipeline.md`. Plan: `docs/plan-weekly-pipeline.md`.

Arguments: $ARGUMENTS (optional `--since YYYY-MM-DD` and `--reprocess` for `prepare`; `--no-pr` and `--dry-run` for `pr`; nothing else).

Python does everything code can do, as subcommands of `uv run python -m me_atlas.pipeline`. The subagents do classification, drafting and review. You only move files between them and run the commands. You never write card content, operations, classifications or reviews yourself, and you never edit `cards/` or `drafts/` by hand: `pr` is the only step that writes to `drafts/`.

Every command prints the run directory or the path it wrote. `RUN` below means `data/pipeline/<date>/`, the directory `prepare` printed. Replace `<slug>`, `<pmid>` and `<N>` (the round, 1 or 2) with the values at hand.

## Order of work

1. **Prepare.** `uv run python -m me_atlas.pipeline prepare [--since YYYY-MM-DD]`. It fetches from PubMed (the last 14 days if no `--since`), writes `RUN/papers.json` (the papers in the fetch window that no earlier run has processed; `--reprocess` ignores that record), `RUN/cards.json` and `RUN/prepare.json`, and prints any newly retracted PMID cited on a card. If the fetch fails, tell the founder and stop. Tell him how many papers were selected and how many were skipped as already processed. If no paper was selected, skip to step 6; the report still lists retractions. If `papers.json` has more than 60 papers, tell the founder the count and ask before going on.
2. **Classify.** Launch the `paper-classifier` agent with the run directory. It writes `RUN/classify.json`. Run `uv run python -m me_atlas.pipeline record-classification`. If it prints errors, launch the classifier once more and give it the error text; if the second file is still rejected, stop and report. Reviews and papers matching no card stop here; the command writes `RUN/matches.json` with the (card, paper) pairs to draft. Possible new hypotheses go to the report only; nobody drafts a card for them.
3. **Draft, for each pair in `matches.json`** (pairs for different cards may run in parallel; do one pair at a time per card).
   1. `uv run python -m me_atlas.pipeline context <slug> <pmid>` writes `RUN/context/<slug>-<pmid>.md`, with full text fetched on demand and any truncation stated.
   2. Launch the `card-drafter` agent with the context file path and the output path `RUN/ops/<slug>-<pmid>-r<N>.json`.
   3. `uv run python -m me_atlas.pipeline apply <slug> RUN/ops/<slug>-<pmid>-r<N>.json --round <N>` validates the operations, applies them to a copy of the draft, runs the card validator and the citations check, and writes `RUN/checks/...` and `RUN/applied/<slug>-<pmid>-r<N>/`.
   4. **One retry after a check failure.** If `apply` prints FAILED, launch the drafter once more with the same context file, the same output path and `RUN/checks/<slug>-<pmid>-r<N>.json`, which holds the errors. Run `apply` again. If it fails again, leave the pair as it is (the report lists it as skipped) and go on to the next pair. A drafter that wrote no file, or an empty `operations` list, ends the pair: nothing to review.
4. **Review.** For a pair whose `apply` passed with at least one operation, launch the `card-reviewer` agent in pipeline mode. Give it only: the context file, the operations file, the applied card and `changes.diff`, the checks file, and the output path `RUN/review/<slug>-<pmid>-r<N>.json`. **The reviewer must not see the drafter's reasoning**: do not pass on the drafter's reply, your own notes or any explanation of the change, and do not tell it what you expect. Every finding carries a severity (`must_fix` or `advisory`); any `must_fix` means the verdict is `reject`, and `record-review` refuses an `accept` that has one. Then run `uv run python -m me_atlas.pipeline record-review <slug> <pmid> --round <N>`. If the file is rejected as malformed, ask the reviewer once to correct the format.
5. **Second round, at most one.** If the verdict is `reject` and N is 1, launch the drafter again with the context file, the review file `RUN/review/<slug>-<pmid>-r1.json` (the drafter must fix every `must_fix` finding; advisory ones are optional; an empty operations list is allowed) and the output path `RUN/ops/<slug>-<pmid>-r2.json`, and repeat steps 3.3 to 4 with `--round 2` (including the one retry after a check failure, and a fresh reviewer run). If round 2 is rejected too, or round 2 cannot pass the mechanical checks, stop: the change is **not applied** and goes to the **parking lot** for the founder (spec section 6, step 5). Never run a third round.
6. **Report.** `uv run python -m me_atlas.pipeline report` writes `RUN/report.md`: tier 2 proposals first (level, contested mark, badge: the founder decides), then tier 1 changes, the parking lot, possible new hypotheses, newly retracted papers on cards, anything skipped, and how every new paper was classified.
7. **Pull request.** `uv run python -m me_atlas.pipeline pr [--dry-run] [--no-pr]`, passing on the founder's flags. It copies the accepted results into `drafts/`, then creates `pipeline/<date>`, commits, pushes and opens a pull request whose description is the report. With `--no-pr` it stops after the local commit (no push, no pull request); with `--dry-run` it only prints the commands. It refuses to open a pull request from any branch but `main`. Nothing is published: the founder approves by merging, and drafts stay in `drafts/` during the calibration period.

## Rules

- The mechanical checks (validator, citations check) decide whether a pair may go to review. The reviewer decides whether it may go in the pull request. Neither is skipped, and you do not override either.
- If a command or an agent fails in a way these steps do not cover, stop that pair, say so, and carry on with the rest. Do not retry more often than stated.
- Do not run `cards validate` or the citations check on `drafts/` as a substitute for `apply`; they run inside it.
- Do not change a level, a badge or a contested mark yourself. Those reach the draft only as `propose` operations, which the report marks tier 2.

## Final message to the founder (in Norwegian)

Short and plain: how many new papers, how many were classified as original/review/other, how many pairs were drafted, accepted, parked and skipped, which cards got tier 2 proposals, any retracted paper that a card cites, the path to `RUN/report.md`, and the link to the pull request (or that none was opened, and why). Do not list findings in detail; the report does that. Do not recommend what to decide.
