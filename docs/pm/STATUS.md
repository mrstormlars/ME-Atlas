# Status

Last updated: 2026-11-01

## Where we stand

Repository set up (structure, Claude Code roles, Python tooling). Functional specification and front-page mockup done. Card data model done: YAML + pydantic validator in `src/me_atlas/cards.py`, reference in `docs/card-format.md`. PubMed fetch script done: `src/me_atlas/pubmed.py`, query in `config/pubmed_query.txt`, reference in `docs/fetch.md`; live check passed 2026-10-31 (whole query 9,392 hits, about 400 per year). Card format v2 done (case definition provenance, `direction`, `group`, Holmes 1988): `docs/card-format.md`. Europe PMC full-text client and case-definition finder done and live-checked: `src/me_atlas/europepmc.py`. Mechanical citation check done (C1-C7, offline, `src/me_atlas/citations.py`, reference in `docs/citation-check.md`); `pubmed fetch --ids` added for papers outside the search query. Two draft cards in `drafts/` re-graded with full-text case definitions and checked by `card-reviewer`; founder accepted their levels on 2026-11-01 (reduced NK cell function 3, contested at rung 3; neuroinflammation 2). Third draft card `drafts/impaired-energy-production-after-exertion.yaml` (15 studies, two `card-reviewer` rounds); founder ruled on 2026-11-01: level 3, contested at rung 3, Explains PEM no (PEM badge rule clarified in spec section 3). Fourth and fifth draft cards: `drafts/autoimmunity-autoantibodies-b-cells.yaml` (founder ruled level 3, rung 4 settled by the larger rituximab trial; Germain 2025 to be verified once its full text can be cached) and `drafts/gut-microbiome.yaml` (level 3, not contested). Nothing is in `cards/` yet. Weekly pipeline built (`src/me_atlas/operations.py`, `src/me_atlas/pipeline.py`, agents `paper-classifier`, `card-drafter` and the pipeline section of `card-reviewer`, command `/ukentlig`, reference `docs/pipeline.md`, lessons in `docs/drafting-checklist.md`); tested offline, live check pending. Static site generator built (`src/me_atlas/site.py`, glossary in `content/glossary.yaml`, reference in `docs/site.md`); live-checked 2026-11-01 (375 px and desktop, keyboard and glossary explanations) and the glossary, methods text and rendered cards revised after a `card-reviewer` pass.

## Active priorities (max 3)

1. Live check of the weekly pipeline: `/ukentlig --since <30 days back> --no-pr`, then a fresh `card-reviewer` on the resulting draft changes, before any pull request is opened.

Done 2026-11-01: rulings from the site review (level 2 needs a recognised case definition; `CDC_unspecified` accepted like Fukuda; reasons may be split into paragraphs with their own sources; `last_checked.by` stays `ai_pair`). Both drafts updated: CDC studies re-labelled, long reasons split per source, NK "Explains PEM" reason added, neuroinflammation states why the PET study does not contest level 2, and pmid:7983659 named in the NK contested reason. Levels unchanged.

## Parked

- AI classification and extraction (after the fetch script works).
- Domain me-atlas.org — decide whether to register.

## Format backlog (from the first two cards; fix when a card needs it)

- Sample size per measurement, not only per study.
- A field for corrections and errata, so a sentence can cite them.
- Cohort overlap between papers (matters for the independence test).
- Which study or finding a `contradicts` study contradicts.
- Validator check that early-signal sources have a confirmed recognised case definition.
