# CLAUDE.md

## What this project is

ME Atlas is a continuously updated, evidence-graded overview of the serious hypotheses about what causes ME/CFS and long COVID. A weekly Python pipeline fetches new papers, AI classifies them and drafts card updates, and a human editorial team approves every change before it is published to a static website.

- **The plan:** `docs/ME-Atlas-v1-plan.md` — purpose, v1 scope, evidence card fields, draft status scale, pipeline, principles, open questions.
- **Where we stand:** `docs/pm/STATUS.md` (current priorities). **Rulings:** `docs/pm/DECISIONS.md` (append-only).
- Read STATUS.md before starting work. Do not build for the long-term vision (other diseases, "all suffering") — v1 only.

## Credibility rules (non-negotiable)

Credibility is the product. The readers are patients and carers with little energy and researchers who will check the sources. These rules come before features.

1. **Never cite from memory.** Every PMID, DOI, title, author, year, sample size and case definition in `cards/` or `drafts/` must come from a record fetched from PubMed / Europe PMC (or a cached copy in `data/cache/`) — not from model knowledge. If something cannot be verified, write `TODO: verify` and say so. A hallucinated reference is the single most damaging failure this project can have.
2. **AI drafts, humans decide what matters.** Publication follows the tiered review model in `docs/ME-Atlas-functional-spec.md` section 6. Code and agents write to `drafts/`; only the pipeline's tier 1 path (mechanical checks passed, drafting and review agents agree, calibration period ended by founder ruling in DECISIONS.md) may publish without a human. Setting or changing a `status_level`, badge or contested mark, adding or removing a hypothesis, and resolving parked disputes are founder decisions. In chat sessions, move content into `cards/` only when the founder explicitly asks.
3. **No treatment advice.** Describe findings, never recommend. Early signals are labelled as unreplicated. Neutral wording: "a study of n=… found …", not "X causes ME".
4. **Grade only against the published rubric** (the evidence ladder in `docs/ME-Atlas-functional-spec.md` section 3). Do not invent criteria. Always record the case definition (e.g. Fukuda, CCC, ICC, IOM 2015, Oxford) — Oxford-only cohorts are broad and must be flagged.
5. **Every claim links to its source.** No unsourced sentence in a card.

## Layout

```
cards/        Approved evidence cards, one file per hypothesis — the published source of truth
drafts/       AI-drafted card updates awaiting human review
content/      Site text kept apart from code: the shared glossary (content/glossary.yaml)
data/cache/   Raw API responses (gitignored, reproducible)
src/me_atlas/ Python package: fetch → classify → extract → draft → site
tests/        Offline tests; fixtures/ holds recorded API responses
docs/         Plan, rubric and methods; docs/pm/ for status and decisions
build/        Generated static site (gitignored)
```

The card data model (YAML vs JSON, field names) is not decided yet — it is the first item in the plan's next steps. Record the ruling in DECISIONS.md.

## Commands

```bash
uv sync                      # install deps into .venv
uv run pytest                # tests (offline, fast)
uv run ruff check . --fix    # lint
uv run ruff format .         # format
```

## Engineering rules

- Python 3.12+, managed with `uv`. Prefer the standard library and existing deps; a new dependency is justified in the commit message.
- **Tests never touch the network or an LLM.** Mock HTTP and model calls; use recorded responses in `tests/fixtures/`.
- **External APIs:** respect rate limits (NCBI: 3 req/s, 10 with an API key), send a contact email, cache raw responses in `data/cache/`.
- **AI steps run as Claude Code subagents** defined in `.claude/agents/`, with the model in each agent's frontmatter and the prompt in the repo — never inline in pipeline logic. Every AI output that ends up in a draft keeps the source id it was derived from. No direct API calls (no `anthropic` calls, no API key) while the project runs on the subscription; Python does the rest as `me_atlas.pipeline` subcommands.
- **Secrets** live in `.env` (see `.env.example`), never in code or git.
- **Simple over clever:** v1 is a static site with no database, no accounts, no money handling.
- **Diff scope:** change what the task needs, nothing "while I was in there".

## Workflow

- Roles: `/prosjektleder` (overview and course, Norwegian), `/brainstorm` (explore, then write a plan into `docs/`), `/orchestrator` (contract + plan → `worker` implements → `evaluator` grades). `card-reviewer` checks evidence content against the credibility rules.
- **Never let one context both plan and grade.** The evaluator gets the contract and the diff, not the plan's reasoning.
- **Write the contract first:** "done" as a short list of checkable clauses before any code.
- **Keep state on disk, not in context:** decisions in DECISIONS.md, status in STATUS.md, plans in `docs/`.
- **Restart rather than patch:** after three failed attempts at the same thing, stop and report.
- **Git:** `main` is the published state. Never push to `main` — work on `feat/…`, `fix/…`, `docs/…` or `chore/…` branches and merge via PR on GitHub (`mrstormlars/ME-Atlas`, private). The `.githooks/pre-push` hook enforces this locally (enable per clone: `git config core.hooksPath .githooks`); never bypass it with `--no-verify`.

## Language

Speak Norwegian with the founder. Code and repository documents are in English. Site content is written in English, which is authoritative; reviewed translations (Norwegian first) are published alongside it (`docs/translation.md`).
