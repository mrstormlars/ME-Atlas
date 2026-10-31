# Decisions

Append-only, newest first. One entry per ruling: date, decision, why.

## 2026-10-31 — Repository setup

- Python with `uv`, `ruff` and `pytest`; static site generated from card files, no database.
- Approved cards live in `cards/`, AI drafts in `drafts/`; only the editorial team moves content between them.
- Agent roles adapted from Kunnskapsbanken in a lean form: prosjektleder, brainstorm, orchestrator → worker → evaluator, plus a domain `card-reviewer` that fact-checks citations.
