# Decisions

Append-only, newest first. One entry per ruling: date, decision, why.

## 2026-10-31 — Card data model

- Cards are YAML, one file per hypothesis (`cards/<slug>.yaml`), validated by pydantic models in `src/me_atlas/cards.py`. Why: YAML reads well in a pull request diff and allows comments; pydantic and PyYAML were already dependencies.
- Studies are listed inline on each card, with no shared registry. A study cited by two cards appears twice; the later citation check compares both against the fetched record. Every free-text field is `{text, sources}`, so "every claim links to its source" is checkable.
- Drafts use the same schema as cards (`drafts/<slug>.yaml`); the change is the diff against the card. No separate patch format.
- Derived, not stored: the long COVID label (any cited long COVID cohort), the hatched contested segment (`contested.rungs`) and ranking (`level`).
- One change log, `cards/changelog.yaml`, an append-only list of entries (date, card, change, reason, sources, tier).
- Twelve mechanical rules (V1–V12) are enforced by `uv run python -m me_atlas.cards validate`; reference in `docs/card-format.md`. Plan: `docs/plan-card-data-model.md`.

## 2026-10-31 — Tiered AI review and open questions

- Review runs mostly on AI: a drafting agent and an independent review agent, with mechanical citation checks in code. Two failed rounds send a change to a parking lot for the founder. Tier 1 changes (new study on a card, factual text) may publish automatically after a calibration period; levels, badges, contested marks and new hypotheses always need the founder. CLAUDE.md rule 2 amended to match. Why: no medical reviewer yet; keeps the founder's workload small while a human still decides everything that moves the chart.
- No external reviewer before launch; recruit after showing the site publicly. The site says openly that content is AI-reviewed, not expert-reviewed.
- Oxford-only evidence capped at level 1; Fukuda flagged "does not require PEM". PEM badge needs a study that measures PEM directly. Contested = same or stricter case definition, controlled, at least half the sample size. Early signals on cards only, fixed wording. Long COVID label on the card. v1 stands alone from MEpedia.
- Details: `docs/ME-Atlas-functional-spec.md` sections 3, 6 and 8.

## 2026-10-31 — Front page and evidence display

- Front page is a pipeline chart: one bar per hypothesis against the status scale, ranked as "furthest along", never "most promising". Contested evidence shown on the bar. No momentum or paper-count metric. Why: honest, familiar format; volume is not evidence.
- One axis (causal evidence) plus two card badges: validated diagnostic marker, explains PEM. Treatment success alone is not proof of cause. Why: easier to read than three tracks, and scientifically accurate.
- v1 covers ME/CFS; long COVID is marked where evidence overlaps. No subgroup filtering in v1. Why: keep scope small.
- Site is in English, plain language; technical terms explained from one shared glossary on hover, tap and focus. Why: international audience with limited energy.
- Details and next steps: `docs/plan-functional-spec.md`.

## 2026-10-31 — Repository setup

- Python with `uv`, `ruff` and `pytest`; static site generated from card files, no database.
- Approved cards live in `cards/`, AI drafts in `drafts/`; only the editorial team moves content between them.
- Agent roles adapted from Kunnskapsbanken in a lean form: prosjektleder, brainstorm, orchestrator → worker → evaluator, plus a domain `card-reviewer` that fact-checks citations.
