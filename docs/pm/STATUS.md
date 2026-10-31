# Status

Last updated: 2026-10-31

## Where we stand

Repository set up (structure, Claude Code roles, Python tooling). Functional specification and front-page mockup done. Card data model done: YAML + pydantic validator in `src/me_atlas/cards.py`, reference in `docs/card-format.md`. No real cards and no pipeline code yet.

## Active priorities (max 3)

1. First PubMed / Europe PMC fetch script (cached raw responses, rate limits, contact email).
2. Write 2–3 cards by hand from fetched records to test the format.
3. Mechanical citation check against fetched records.

## Parked

- AI classification and extraction (after the fetch script works).
- Static site generator (after the card format has survived real cards).
- Domain me-atlas.org — decide whether to register.
