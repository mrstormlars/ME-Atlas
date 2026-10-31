# Status

Last updated: 2026-10-31

## Where we stand

Repository set up (structure, Claude Code roles, Python tooling). Functional specification and front-page mockup done. Card data model done: YAML + pydantic validator in `src/me_atlas/cards.py`, reference in `docs/card-format.md`. PubMed fetch script done: `src/me_atlas/pubmed.py`, query in `config/pubmed_query.txt`, reference in `docs/fetch.md`; live check passed 2026-10-31 (whole query 9,392 hits, about 400 per year). Card format v2 done (case definition provenance, `direction`, `group`, Holmes 1988): `docs/card-format.md`. Europe PMC full-text client and case-definition finder written and tested offline: `src/me_atlas/europepmc.py`; its endpoint URLs are not yet confirmed against the live service. Two draft cards exist in `drafts/` (reduced NK cell function, neuroinflammation), migrated to format v2; nothing is in `cards/` yet.

## Active priorities (max 3)

1. Live check of the Europe PMC commands (`casedef --card` on both drafts), then re-grade the two drafts with full-text case definitions (drafting agents and `card-reviewer`, then the founder decides levels).
2. Mechanical citation check against fetched records.

## Parked

- AI classification and extraction (after the fetch script works).
- Static site generator (after the card format has survived real cards).
- Domain me-atlas.org — decide whether to register.
