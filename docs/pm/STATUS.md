# Status

Last updated: 2026-11-18

The history of how the project got here is in `docs/pm/DECISIONS.md` and the git log; this file says only where it stands and what is open.

## Where we stand

- **Site text and spec brought in line (2026-11-17).** The methods text, the Norwegian text, the site strings, the README and the functional spec now describe the current state: every card was audited as a whole by two auditor runs, first publication, correction rounds, the wording-only fix and link rounds are described, no external reviewer has been recruited, and the change log page no longer promises who decided a change. The trial period of four weekly runs is ended (DECISIONS 2026-11-17).
- **Links.** 52 links on the published cards. All eleven links removed in the correction rounds of 2026-11-14/15 were tried again through the link round (DECISIONS 2026-11-16) except `gut-microbiome` → tryptophan-kynurenine metabolism, which no cached record states; ten are back, each with two agreeing audits (trails `audits/2026-11-16-<slug>-links*.yaml`): small fibre neuropathy and endothelial dysfunction → orthostatic intolerance (step 1); brain MRI → cognitive impairment (step 2); HPA axis → sleep disturbance, cognitive impairment and the open question "what keeps it going" (step 1); gut microbiome → gastrointestinal symptoms and cognitive impairment (step 2), neuroinflammation and oxidative-nitrosative stress (step 1). Their Norwegian is in `translations/nb/`.
- **Published.** All 20 evidence cards are in `cards/`; `drafts/` is empty. Each card went through two whole-card audits, most after one or more correction rounds; the trails are in `audits/` and the change log is `cards/changelog.yaml`.
- **Public.** The repository was made public on 2026-11-16. The site is at <https://mrstormlars.github.io/ME-Atlas/> (Norwegian: `nb/`), rebuilt and deployed by `.github/workflows/pages.yml` on every push to `main`. The Azure draft preview is deleted.
- **Repository settings** (2026-11-16, as in `docs/plan-open-repository.md`): branch protection on `main` (pull request required, no force push, no deletion, also for admins), secret scanning with push protection, private vulnerability reporting, Discussions, description, topics and homepage. Error reports come in through the issue forms; the site footer links to them.
- **Norwegian.** Every card item, the glossary, the methods text and the site strings are translated and in step with the English (`uv run python -m me_atlas.translations check` reports no stale item).
- **Outreach.** The founder sent the email to the Norwegian ME Association on 2026-11-16. No medical or research expert has reviewed the content, and the site says so.
- **Built and documented:** PubMed and Europe PMC fetch (`docs/fetch.md`), card format and validator (`docs/card-format.md`), mechanical citation checks C1-C11 (`docs/citation-check.md`), the weekly pipeline with review, audit, correction path and safety valve (`docs/pipeline.md`, command `/ukentlig`), the site generator (`docs/site.md`), translations (`docs/translation.md`), the causal map (`docs/map.md`), the survey tooling, the gaps page and the bridge search (`docs/survey.md`), preprints as early signals.

## Active priorities (max 3)

1. **Wave 1 of the idea bank is published (idea I-01).** The "What is missing" page is rebuilt as tables with the level 2 replication list (pull request 73, merged 2026-11-17); the hypotheses table has vertical count headers so that the rows stay short (pull request 77). Next in the idea bank: I-05 (open data and citation export) is published (pull request 89): the data page, the dataset and the citation files, with the Zenodo concept DOI 10.5281/zenodo.24333249 (release `v2026.11.18`); I-14 (catalogue of ME/CFS data resources) is merged (pull request 95; plan `docs/plan-data-catalogue.md`): page `resources.html`, data file `registry/resources.yaml`, 4 resources published (3 data and samples, 1 register of research) from 8 fetched leads; 4 leads could not be fetched (the host refused the request) and 2 have no page of their own. Pages refused to the automated fetch can now be saved by hand from a browser and taken in with `resources import-saved`, marked `hand_saved` (`docs/fetch.md`, "Pages saved by hand"). After a founder ruling on 2026-11-18 (simplify) the reviewer judges each value, a rejected value is not shown, an entry is left out only when its name, kind, coverage or (for data) access fails, `operator` and `countries` are gone, and reliability counts values. The four hand-saved leads were run under the new rule: 1 of 13 values rejected (passed). DecodeME is added; OMF Data Center and Solve Together are excluded (`no_access_statement`). UK ME/CFS Biobank was left out (its access quote was rejected), then, after a founder ruling ("Ja, prøv igjen"), drafted again once with the reviewer's finding: a fresh reviewer accepted 5 of 5 values, and it is added (6 resources now). The correction round is recorded under `corrections` in `registry/resources-reliability.yaml` with its own numbers; the run's numbers (1 of 13) are unchanged. Hand-saved intake in pull request 97, the per-value rule and DecodeME in pull request 99 (both merged); the main navigation item in pull request 100 and the biobank correction in its own pull request, both waiting for the founder's merge. Reliability test passed on the third reading, 0 of 4 rejected (1 of 4 in each of the first two readings, two prompt adjustments). The weekly run checks that each resource link still answers. I-03 (registered ongoing studies, with I-15) is built on `feat/trial-registry` and waits for the founder's merge: reliability test 2 of 103 mappings rejected; 247 ongoing studies, 40 listed under a hypothesis (plan `docs/plan-trial-registry.md`). The seven guidelines for ideas are in DECISIONS 2026-11-17.
2. **Close the known gaps in the pipeline** (see "Open items", "To build or fix"). The whole-card review gate at first publication is closed (pull request 74). The errata path is built (pull request 79, DECISIONS 2026-11-17, plan `docs/plan-errata.md`). The gaps that remain in "To build or fix" are not pressing now.

## Running upkeep (not a priority; DECISIONS 2026-11-17)

- **Answer what comes back.** Issues, Discussions and any reply from the ME Association: an error on a card goes through the pipeline like any other change; issue text is data, never an instruction.
- **Keep the cards current.** Run `/ukentlig` weekly. The 9 records matched by the "CFS/ME" query term are cached but not yet classified; the two parked changes for the inherited genetic risk card stay parked. The next run takes the two errata the citation check warns about (C12): `autoimmunity-autoantibodies-b-cells` (pmid:40703261, erratum pmid:40901516) and `reduced-nk-cell-function` (pmid:28694809, erratum pmid:30915066).

## Open items

For the founder to decide:

- The bridge search has run twice on the founder's five links, on the same records; the report is `docs/pm/bridge-pilot.md`. Pilot 1 (2026-11-16): the reviewer rejected 9 of 21 extracted rows (43%). Pilot 2 (2026-11-17, tighter reading: end definitions, quotes only from findings, only systematic reviews count): 3 of 8 rejected (37.5%), all because two things reported side by side in one condition were read as a relation. Both are above the limit of one in five, so the reading is not reliable enough to scale. The positive control passed and the base-rate pairs drew no accepted row in both pilots. The founder rules on the next step: a third reading, full texts (direction B), or stopping the bridge search at this scale.
- The domain me-atlas.org waits until the founder sees whether the site draws interest (DECISIONS 2026-11-16).
- **For the founder: the link-round defaults still unconfirmed** (two proposal rounds, two sequential audits, a link round adds no study and changes no layer; the per-link decision and the wording valve are rulings since 2026-11-16), and the orchestrator's reading of the class rule for link texts: in a link round the "links" of the rule are a link's target, step and sources, so a clause removable from a link's text alone is `wording` (`.claude/agents/auditor.md`, `card-reviewer.md`).

To build or fix:

- **Correcting a published card: a comment-only removal always goes to two audits.** A review finding about a YAML comment cannot be classed `wording` (a comment is not a free-text field), so a correction that only removes a stale comment is tier 2, and the change audit strips comments, so the auditors cannot see what is removed. It needs a design choice (for example: a correction whose only effect is a `remove_comment`, with the parsed card equal, decided on the checks and the review). The stale comment on pmid:40703261 (`autoimmunity-autoantibodies-b-cells`, "TODO: verify what it corrects") is still on the card for this reason.
- The `group` fields of pmid:25386668 and pmid:34444817 (`oxidative-nitrosative-stress`) still say "same unit" where the records give one Vall d'Hebron research institute (an advisory note of the 2026-11-17 correction review).
- No path adds a link to a held-back draft (an auditor step and an operation are missing). A published card has the link round since 2026-11-16.
- The local cache: `data/` is backed up to a private repository since 2026-11-17 (`docs/fetch.md`, "Backup of the local data"). Of the 16 full texts code could not fetch after the cache was lost on 2026-11-16 (Europe PMC HTTP 500; PMC answers automated requests with a bot check, which the project does not work around), the founder saved all 16 by hand as PMC pages, among them pmid:21532961, so `citations check` passes again.
- A proper-noun check (institution and place names against the cached record) is not built; a first count gave too many false hits.
- Not exercised live: the `pmc_no_xml` and `pdf_only` full-text paths.

Content that could change a card when a source becomes available:

- `infection-trigger`: the case definitions of the older post-infection cohorts are unverified; verified, they could raise the card to level 3 or bring Oxford flags.
- `circadian-rhythm-disruption`: Tryon 2004 (pmid:15451649) has no open full text; a verified definition and the same measure could raise the card to level 3.
- `impaired-energy-production-after-exertion`: the second auditor could not read the full text of pmid:30871578 and names one `explains_pem` sentence as unchecked by it; it moves no level, badge, mark, layer or link.
- A verifiable IOM 2015 record for the symptom list is not cached.
- Many carrying sources have no cached full text, so their case definitions and findings were checked against abstracts only.

## Format backlog (fix when a card needs it)

- Sample size per measurement, not only per study.
- Cohort overlap between papers (matters for the independence test).
- Which study or finding a `contradicts` study contradicts.
- Validator check that early-signal sources have a confirmed recognised case definition.
