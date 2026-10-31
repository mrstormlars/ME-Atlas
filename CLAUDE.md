# CLAUDE.md

## What this project is

ME Atlas is a continuously updated, evidence-graded overview of the serious hypotheses about what causes ME/CFS and long COVID. A weekly Python pipeline fetches new papers, AI classifies them and drafts card updates, and a human editorial team approves every change before it is published to a static website.

- **The plan:** `docs/ME-Atlas-v1-plan.md` — purpose, v1 scope, evidence card fields, draft status scale, pipeline, principles, open questions.
- **Where we stand:** `docs/pm/STATUS.md` (current priorities). **Rulings:** `docs/pm/DECISIONS.md` (append-only).
- Read STATUS.md before starting work. Do not build for the long-term vision (other diseases, "all suffering") — v1 only.

## Credibility rules (non-negotiable)

Credibility is the product. The readers are patients and carers with little energy and researchers who will check the sources. These rules come before features.

1. **Never cite from memory.** Every PMID, DOI, title, author, year, sample size and case definition in `cards/` or `drafts/` must come from a record fetched from PubMed / Europe PMC (or a cached copy in `data/cache/`) — not from model knowledge. If something cannot be verified, write `TODO: verify` and say so. A hallucinated reference is the single most damaging failure this project can have.
2. **AI drafts, humans decide.** Code and agents write to `drafts/` only. Moving content into `cards/`, setting or changing a `status_level`, and setting `last_reviewed` are editorial acts: do them only when the founder explicitly asks in chat.
3. **No treatment advice.** Describe findings, never recommend. Early signals are labelled as unreplicated. Neutral wording: "a study of n=… found …", not "X causes ME".
4. **Grade only against the published rubric** (currently the status scale in the plan). Do not invent criteria. Always record the case definition (e.g. Fukuda, CCC, ICC, IOM 2015, Oxford) — Oxford-only cohorts are broad and must be flagged.
5. **Every claim links to its source.** No unsourced sentence in a card.

## Layout

```
cards/        Approved evidence cards, one file per hypothesis — the published source of truth
drafts/       AI-drafted card updates awaiting human review
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
- **LLM calls go through one module** with model ids and token budgets in config — never inline in pipeline logic. Every LLM output that ends up in a draft keeps the source id it was derived from.
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

Speak Norwegian with the founder. Code, repository documents and site content are in English.
