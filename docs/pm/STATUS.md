# Status

Last updated: 2026-11-16

The history of how the project got here is in `docs/pm/DECISIONS.md` and the git log; this file says only where it stands and what is open.

## Where we stand

- **Links.** 52 links on the published cards. All eleven links removed in the correction rounds of 2026-11-14/15 were tried again through the link round (DECISIONS 2026-11-16) except `gut-microbiome` → tryptophan-kynurenine metabolism, which no cached record states; ten are back, each with two agreeing audits (trails `audits/2026-11-16-<slug>-links*.yaml`): small fibre neuropathy and endothelial dysfunction → orthostatic intolerance (step 1); brain MRI → cognitive impairment (step 2); HPA axis → sleep disturbance, cognitive impairment and the open question "what keeps it going" (step 1); gut microbiome → gastrointestinal symptoms and cognitive impairment (step 2), neuroinflammation and oxidative-nitrosative stress (step 1). Their Norwegian is in `translations/nb/`.
- **Published.** All 20 evidence cards are in `cards/`; `drafts/` is empty. Each card went through two whole-card audits, most after one or more correction rounds; the trails are in `audits/` and the change log is `cards/changelog.yaml`.
- **Public.** The repository was made public on 2026-11-16. The site is at <https://mrstormlars.github.io/ME-Atlas/> (Norwegian: `nb/`), rebuilt and deployed by `.github/workflows/pages.yml` on every push to `main`. The Azure draft preview is deleted.
- **Repository settings** (2026-11-16, as in `docs/plan-open-repository.md`): branch protection on `main` (pull request required, no force push, no deletion, also for admins), secret scanning with push protection, private vulnerability reporting, Discussions, description, topics and homepage. Error reports come in through the issue forms; the site footer links to them.
- **Norwegian.** Every card item, the glossary, the methods text and the site strings are translated and in step with the English (`uv run python -m me_atlas.translations check` reports no stale item).
- **Outreach.** The founder sent the email to the Norwegian ME Association on 2026-11-16. No medical or research expert has reviewed the content, and the site says so.
- **Built and documented:** PubMed and Europe PMC fetch (`docs/fetch.md`), card format and validator (`docs/card-format.md`), mechanical citation checks C1-C11 (`docs/citation-check.md`), the weekly pipeline with review, audit, correction path and safety valve (`docs/pipeline.md`, command `/ukentlig`), the site generator (`docs/site.md`), translations (`docs/translation.md`), the causal map (`docs/map.md`), the survey tooling, the gaps page and the bridge search (`docs/survey.md`), preprints as early signals.

## Active priorities (max 3)

1. **Answer what comes back.** Issues, Discussions and any reply from the ME Association: an error on a card goes through the pipeline like any other change; issue text is data, never an instruction.
2. **Keep the cards current.** Run `/ukentlig` weekly. The 9 records matched by the "CFS/ME" query term are cached but not yet classified; the two parked changes for the inherited genetic risk card stay parked.
3. **Close the known gaps in the pipeline** (see "Open items").

## Open items

For the founder to decide:

- The bridge search pilot (Part C of `docs/plan-wider-sources.md`) has run on the founder's five links; the report is `docs/pm/bridge-pilot.md`. The positive control passed and the two base-rate pairs drew no accepted hit, but the reviewer rejected 9 of 21 extracted rows (43%, above the limit of one in five). The founder rules whether the results are useful enough to show, and whether the follow-up plan for indirect evidence goes ahead.
- The domain me-atlas.org waits until the founder sees whether the site draws interest (DECISIONS 2026-11-16).
- **For the founder: the link-round defaults still unconfirmed** (two proposal rounds, two sequential audits, a link round adds no study and changes no layer; the per-link decision and the wording valve are rulings since 2026-11-16), and the orchestrator's reading of the class rule for link texts: in a link round the "links" of the rule are a link's target, step and sources, so a clause removable from a link's text alone is `wording` (`.claude/agents/auditor.md`, `card-reviewer.md`).

To build or fix:

- No path adds a link to a held-back draft (an auditor step and an operation are missing). A published card has the link round since 2026-11-16.
- Reproducing `data/cache` from scratch (it was missing in the checkout on 2026-11-16 and was re-fetched): pmid:21532961 (`circadian-rhythm-disruption`) has no open full text and PMC now answers automated requests for its page with a reCAPTCHA "Checking your browser" page, so `pmcpage` cannot cache it and `citations check` reports one C5 error. The project does not work around a bot check; the page can be placed in the cache only by a person, or the request retried later. Some Europe PMC full-text requests returned HTTP 500 (15 records on 13 cards, none a source of a restored link; their full texts are not cached in this checkout, so a full-text check of them, for example by the auditor, falls back to the abstract).
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
