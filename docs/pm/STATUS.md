# Status

Last updated: 2026-11-01

## Where we stand

Repository set up (structure, Claude Code roles, Python tooling). Functional specification and front-page mockup done. Card data model done: YAML + pydantic validator in `src/me_atlas/cards.py`, reference in `docs/card-format.md`. PubMed fetch script done: `src/me_atlas/pubmed.py`, query in `config/pubmed_query.txt`, reference in `docs/fetch.md`; live check passed 2026-10-31 (whole query 9,392 hits, about 400 per year). Card format v2 done (case definition provenance, `direction`, `group`, Holmes 1988): `docs/card-format.md`. Europe PMC full-text client and case-definition finder done and live-checked: `src/me_atlas/europepmc.py`. Mechanical citation check done (C1-C7, offline, `src/me_atlas/citations.py`, reference in `docs/citation-check.md`); `pubmed fetch --ids` added for papers outside the search query. Two draft cards in `drafts/` re-graded with full-text case definitions and checked by `card-reviewer`; founder accepted their levels on 2026-11-01 (reduced NK cell function 3, contested at rung 3; neuroinflammation 2). Nothing is in `cards/` yet. Static site generator built (`src/me_atlas/site.py`, glossary in `content/glossary.yaml`, reference in `docs/site.md`); live-checked 2026-11-01 (375 px and desktop, keyboard and glossary explanations) and the glossary, methods text and rendered cards revised after a `card-reviewer` pass.

## Active priorities (max 3)

1. Founder decisions raised by the site review (below), then the draft card text they need.

## Open founder decisions (from the site review, 2026-11-01)

- Spec section 3 says level 2 needs a "strict, recognised" case definition, while Fukuda is accepted at every rung and the NK draft is at level 3 on Fukuda studies. Proposed: "recognised case definition".
- Studies citing "CDC criteria" without naming the version (three on the NK draft) render as "other definition". Proposed: a format value for it, treated like Fukuda and Holmes 1988 and flagged "does not require PEM".
- Draft text missing: a reason for the NK "Explains PEM: no" badge; a "not contested" reason on the neuroinflammation card.
- `last_checked.by` on both drafts says `ai_pair`, but the AI review pair is not running and the founder accepted the levels.
- Sources per sentence: the NK level reason ends with 11 references in one block (also in the format backlog below).

## Parked

- AI classification and extraction (after the fetch script works).
- Domain me-atlas.org — decide whether to register.

## Format backlog (from the first two cards; fix when a card needs it)

- Sample size per measurement, not only per study.
- A field for corrections and errata, so a sentence can cite them.
- Cohort overlap between papers (matters for the independence test).
- Which study or finding a `contradicts` study contradicts.
- Validator check that early-signal sources have a confirmed recognised case definition.
- Sources per sentence or clause in long sourced texts.
