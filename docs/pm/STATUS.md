# Status

Last updated: 2026-11-16

The history of how the project got here is in `docs/pm/DECISIONS.md` and the git log; this file says only where it stands and what is open.

## Where we stand

- **Published.** All 20 evidence cards are in `cards/`; `drafts/` is empty. Each card went through two whole-card audits, most after one or more correction rounds; the trails are in `audits/` and the change log is `cards/changelog.yaml`.
- **Public.** The repository was made public on 2026-11-16. The site is at <https://mrstormlars.github.io/ME-Atlas/> (Norwegian: `nb/`), rebuilt and deployed by `.github/workflows/pages.yml` on every push to `main`. The Azure draft preview is deleted.
- **Repository settings** (2026-11-16, as in `docs/plan-open-repository.md`): branch protection on `main` (pull request required, no force push, no deletion, also for admins), secret scanning with push protection, private vulnerability reporting, Discussions, description, topics and homepage. Error reports come in through the issue forms; the site footer links to them.
- **Norwegian.** Every card item, the glossary, the methods text and the site strings are translated and in step with the English (`uv run python -m me_atlas.translations check` reports no stale item).
- **Outreach.** The founder sent the email to the Norwegian ME Association on 2026-11-16. No medical or research expert has reviewed the content, and the site says so.
- **Built and documented:** PubMed and Europe PMC fetch (`docs/fetch.md`), card format and validator (`docs/card-format.md`), mechanical citation checks C1-C11 (`docs/citation-check.md`), the weekly pipeline with review, audit, correction path and safety valve (`docs/pipeline.md`, command `/ukentlig`), the site generator (`docs/site.md`), translations (`docs/translation.md`), the causal map (`docs/map.md`), the survey tooling and the gaps page (`docs/survey.md`), preprints as early signals.

## Active priorities (max 3)

1. **Answer what comes back.** Issues, Discussions and any reply from the ME Association: an error on a card goes through the pipeline like any other change; issue text is data, never an instruction.
2. **Keep the cards current.** Run `/ukentlig` weekly. The 9 records matched by the "CFS/ME" query term are cached but not yet classified; the two parked changes for the inherited genetic risk card stay parked.
3. **Close the known gaps in the pipeline** (see "Open items").

## Open items

For the founder to decide:

- Part C of `docs/plan-wider-sources.md` (bridge search pilot): the founder picks the links to search for.
- The domain me-atlas.org waits until the founder sees whether the site draws interest (DECISIONS 2026-11-16).

To build or fix:

- `pipeline translation-plan` plans only cards changed in a weekly run; text that goes stale through a correction round needed a one-off script on 2026-11-16.
- No path adds a link to a held-back draft (an auditor step and an operation are missing).
- A proper-noun check (institution and place names against the cached record) is not built; a first count gave too many false hits.
- The whole-card review gate applies to correction rounds only, not to the first publication of a new draft.
- Not exercised live: the `pmc_no_xml` and `pdf_only` full-text paths.
- A path for errata and corrections to a published paper.

Content that could change a card when a source becomes available:

- `infection-trigger`: the case definitions of the older post-infection cohorts are unverified; verified, they could raise the card to level 3 or bring Oxford flags.
- `circadian-rhythm-disruption`: Tryon 2004 (pmid:15451649) has no open full text; a verified definition and the same measure could raise the card to level 3.
- `impaired-energy-production-after-exertion`: the second auditor could not read the full text of pmid:30871578 and names one `explains_pem` sentence as unchecked by it; it moves no level, badge, mark, layer or link.
- A verifiable IOM 2015 record for the symptom list is not cached.
- Many carrying sources have no cached full text, so their case definitions and findings were checked against abstracts only.

## Format backlog (fix when a card needs it)

- Sample size per measurement, not only per study.
- A field for corrections and errata, so a sentence can cite them.
- Cohort overlap between papers (matters for the independence test).
- Which study or finding a `contradicts` study contradicts.
- Validator check that early-signal sources have a confirmed recognised case definition.
