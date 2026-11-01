# Plan: weekly pipeline

November 1, 2026 · For `/orchestrator`

## Why

Five draft cards now exist, each drafted by hand with AI agents and checked by `card-reviewer`. About 8 new ME/CFS papers enter PubMed each week. Spec section 6 describes how they should reach the cards: fetch, classify, draft, mechanical checks, an independent review agent, a second round, and the founder's weekly list or parking lot. This plan builds that flow for existing cards only.

## Design decisions (from brainstorm, 2026-11-01, accepted by the founder)

1. **AI runs in a Claude Code session on the founder's Max subscription, not through the Anthropic API.** The founder starts the run by typing `/ukentlig` in a Claude Code session. Python does everything that code can do; Claude Code subagents do classification, drafting and review, as they have done for the five hand-drafted cards. No API key, no `anthropic` calls, nothing to install.
   - This replaces the CLAUDE.md rule "LLM calls go through one module with model ids and token budgets in config" for as long as the project runs on the subscription: model choice lives in each agent's frontmatter in `.claude/agents/`, and the agents' prompts are files in the repo. Every AI output still keeps the source ids it was derived from. CLAUDE.md and DECISIONS are updated to say so.
2. **Updates existing cards only.** New papers are matched against the hypotheses that have a card in `cards/` or `drafts/`. A paper that fits none but may describe a new hypothesis is listed in the weekly report; no new card is drafted. Newly retracted papers cited on any card are listed in the report.
3. **The founder's weekly list is a pull request.** The run creates a branch `pipeline/<date>`, writes the proposed changes to `drafts/`, commits them, and opens a PR whose description is the weekly report. The founder approves by merging. Nothing is published; drafts stay in `drafts/` (calibration period, spec section 6).
4. **The drafter proposes changes; code applies them.** The drafting agent writes a list of operations as JSON, not a whole card: `add_study` (all Study fields, with the verbatim case-definition quote), `add_paragraph` / `replace_paragraph` on a sourced-text field, and `propose` for a level, contested or badge change. Python validates the operations against a schema and applies them, so text the agent did not touch cannot change. `propose` operations are marked tier 2 in the report; everything else is tier 1.
5. **Three agents, two models.**
   - `paper-classifier` (new, `model: haiku`): reads title, abstract, publication types and each card's name and core claim; writes `{pmid, cards: [slug], article_type: original | review | other, new_hypothesis: str | null, reason}` per paper.
   - `card-drafter` (new, `model: sonnet`): reads a context file Python assembles (the card YAML, the spec section 3 rubric, the paper's PubMed record and, when open access, its Europe PMC full text without references) and writes the operations file. Read-only except for its own output file under the run directory.
   - `card-reviewer` (existing, `model: opus`): reviews the applied result against the sources. It is given the context file, the operations and the resulting card text, never the drafter's reasoning, and writes `{verdict: accept | reject, findings: [{operation, problem, fix}]}` to a file. Different model from the drafter, per spec section 6 step 4.
6. **Built-in lessons from the five hand-drafted cards.** `docs/drafting-checklist.md` lists the errors the reviews found again and again: within-group change described as a between-group difference; derived numbers printed as reported; quality criteria beyond the rubric's three; a quote used for something it does not say; an earlier study called a repeat of a later one; association described as cause; unreplicated findings not labelled; a paragraph whose sources differ from the studies its sentences rest on; measurement n confused with study n. Both the drafter and the reviewer read it.
7. **Flow per run** (the `/ukentlig` command drives it; each Python step is a subcommand of `uv run python -m me_atlas.pipeline`):
   1. `prepare [--since YYYY-MM-DD]`: run `pubmed fetch --weekly` (or `--since`), create `data/pipeline/<date>/`, write `papers.json` (new papers with record fields) and `cards.json` (slug, name, core claim), and list newly retracted PMIDs cited on any card.
   2. Classifier agent → `classify.json`. Python `record-classification` validates it. Reviews and papers matching no card stop here.
   3. For each (card, paper) match: `context <slug> <pmid>` fetches full text on demand and writes `context/<slug>-<pmid>.md`. Drafter agent → `ops/<slug>-<pmid>.json`.
   4. `apply <slug> <ops file>`: validate the operations, apply them to a copy of the draft, run the card validator and the citations check, and write the result and check output. On failure the drafter gets one retry with the errors.
   5. Reviewer agent → `review/<slug>-<pmid>.json`. On reject the drafter gets one revised attempt (steps 3–5 again). Still rejected → not applied; recorded for the parking lot.
   6. `report`: builds `report.md` from the run directory. `pr`: copies accepted results into `drafts/`, creates the branch, commits, pushes and opens the PR (`--no-pr` and `--dry-run` supported).
8. **Run record.** `data/pipeline/<date>/` (gitignored) keeps every input file, every agent output, check results and verdicts. The founder uses it to judge the agents' error rate before ending the calibration period.
9. **Weekly report**: new papers and how each was classified; per card the proposed changes with tier, sources and review verdict, tier 2 proposals first; the parking lot; possible new hypotheses; newly retracted papers on cards; anything skipped (no full text, check failure, agent error).

## Steps

1. Operations: pydantic models for the operation list and a function that applies them to a card and returns the new YAML (keeping comments where the YAML library allows; otherwise state the limit), with tests for each operation, including invalid ones (unknown field, paragraph index out of range, duplicate study id).
2. `src/me_atlas/pipeline.py` subcommands `prepare`, `record-classification`, `context`, `apply`, `report`, `pr`, with schemas for the agent output files. Tests with fixture files in `tests/fixtures/pipeline/` (fictional papers and agent outputs); no network, no AI.
3. Agents and command: `.claude/agents/paper-classifier.md`, `.claude/agents/card-drafter.md`, an addition to `card-reviewer.md` for the pipeline output format (keeping its current use intact), `.claude/commands/ukentlig.md` that runs the flow, with the two-round rule and the parking lot spelled out. `docs/drafting-checklist.md`.
4. Docs: `docs/pipeline.md` (how to run, stages, run record, how to read the report); CLAUDE.md engineering rule on LLM calls amended per decision 1; DECISIONS entry; STATUS.
5. Live check (manual): the orchestrator runs `/ukentlig` with `--since` 30 days back and `--no-pr`, and reports papers fetched, classified, drafted, accepted and parked. It then sends the resulting draft changes to a fresh `card-reviewer` run and reports both to the founder before any PR is opened.

## Done when

- [ ] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` pass; no test touches the network or an AI.
- [ ] Operation tests: each operation applies correctly; invalid operations are rejected with a clear error and leave the card unchanged; text not named in an operation is byte-identical after applying.
- [ ] Subcommand tests with fixtures: `prepare` lists only new papers and flags a newly retracted paper cited on a card; `record-classification` rejects a malformed file; `context` drops the reference list and states any truncation; `apply` runs the validator and citations check and reports failures; `report` lists tier 2 proposals first, the parking lot, possible new hypotheses and retractions; `pr --dry-run` prints the git and `gh` commands without running them.
- [ ] The context file given to the reviewer contains no drafter reasoning (tested on the assembled files).
- [ ] The three agent files exist with the stated models and tools; the drafter can write only under `data/pipeline/`; `/ukentlig` documents the two-round rule and the parking lot.
- [ ] CLAUDE.md, DECISIONS, STATUS and `docs/pipeline.md` updated.
- [ ] The live check ran once with `--no-pr`; its numbers and the fresh `card-reviewer` result are reported to the founder.
- [ ] No new dependencies; `data/pipeline/` is gitignored; nothing added to `cards/`.

## Out of scope

- The Anthropic API; scheduling; running without a Claude Code session.
- Drafting new hypothesis cards; processing the backlog of ~9,400 cached papers.
- Hosting or publishing the site, moving drafts to `cards/`, ending the calibration period.
- Reader-reported corrections (spec section 6 step 9).
