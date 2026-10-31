# Status

Last updated: 2026-10-31

## Where we stand

Repository set up (structure, Claude Code roles, Python tooling). Functional specification and front-page mockup done. Card data model done: YAML + pydantic validator in `src/me_atlas/cards.py`, reference in `docs/card-format.md`. PubMed fetch script done: `src/me_atlas/pubmed.py`, query in `config/pubmed_query.txt`, reference in `docs/fetch.md`; live check passed 2026-10-31 (whole query 9,392 hits, about 400 per year). No real cards yet.

## Active priorities (max 3)

1. Hand-write 2–3 cards from fetched records to test the format (run a backfill first).
2. Mechanical citation check against fetched records.

## Parked

- AI classification and extraction (after the fetch script works).
- Static site generator (after the card format has survived real cards).
- Domain me-atlas.org — decide whether to register.
