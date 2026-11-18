# Idea bank

Last updated: 2026-11-17

Ideas for how AI can help ME/CFS research, inside or outside what ME Atlas is today. An idea here is not a commitment: work starts only when the founder picks an idea and `/brainstorm` writes a plan for it in `docs/`. Current priorities stay in `STATUS.md`.

## How to use this file

- One row per idea. The id is permanent; a dropped idea keeps its row and gets status `dropped`.
- Score = effect × feasibility, each 1 to 5. The table is sorted by score, then by id, with parked ideas last.
- Status: `idea`, `planned` (a plan exists in `docs/`), `in progress`, `done`, `parked`, `dropped`.
- The scores are proposals by the AI (2026-11-17) until the founder confirms or changes them.

**Effect** (on ME research, not on the site):

| Score | Meaning |
| --- | --- |
| 1 | A convenience for people who already use the site |
| 3 | Helps researchers or funders do their existing work better |
| 5 | Could change which studies are done or funded, or produce new knowledge |

**Feasibility** (the inverse of cost, counting dependence on others and risk to credibility):

| Score | Meaning |
| --- | --- |
| 5 | Days of work, with the existing pipeline and data we already hold |
| 3 | Weeks: new data sources, or a new AI reading step that needs its own reliability test |
| 1 | Needs an expert partner or restricted data, or conflicts with a v1 principle |

## Ideas

| Id | Idea | Effect | Feas. | Score | Status | Note |
| --- | --- | --- | --- | --- | --- | --- |
| I-01 | **Replication list.** Findings at level 2 that lack one independent replication to reach level 3, as a list for researchers and funders. | 4 | 4 | 16 | done | Built from the cards and the gaps page. Ranking by cost of the replication is the hard part and can come later. Wave 1 (DECISIONS 2026-11-17): done together with a rebuild of the "What is missing" page, after a `/brainstorm` plan. |
| I-03 | **Trial registry tracking.** Ongoing studies per hypothesis, and finished studies with no published result. | 4 | 4 | 16 | in progress | Ongoing studies built, waiting for the founder's merge (branch `feat/trial-registry`, plan `docs/plan-trial-registry.md`): ClinicalTrials.gov API v2, `registry/trials.yaml`, the page `trials.html` (English and Norwegian), a count line per card, `trials.csv` in the dataset, a weekly step in `/ukentlig`. New agent `trial-mapper` (sonnet), checked by `card-reviewer` in registry mode. Reliability test 2026-11-18: 2 of 103 mappings rejected (1.9%). First full run: 247 ongoing studies, 40 matched to a card, 199 to none, 8 mappings rejected. Finished studies with no published result stay out of scope (their own round with their own reliability test). |
| I-14 | **Data catalogue.** Which ME/CFS datasets, registries and biobanks exist, what they hold, and how a researcher gets access. | 4 | 4 | 16 | in progress | Merged in pull request 95 (plan `docs/plan-data-catalogue.md`): the page `resources.html`, the data file `registry/resources.yaml`, `resources.csv` in the dataset; 4 resources from 8 fetched leads (reliability passed, 0 of 4 entries rejected). Pull request 97 (merged): pages refused to the automated fetch are saved by hand and marked so. Pull request 99: per-value review and reliability, no operator or countries (founder ruling 2026-11-18); DecodeME added from a hand-saved page (1 of 13 values rejected), UK ME/CFS Biobank left out (access quote rejected), OMF Data Center and Solve Together excluded (no access statement). No link to hypotheses in this round (founder ruling). |
| I-05 | **Open data and citation export.** Cards and links as a downloadable dataset with a DOI; BibTeX/RIS per card. | 3 | 5 | 15 | done | Built in pull request 89 (plan `docs/plan-open-data-export.md`): `data/` with JSON and CSV, BibTeX and RIS per card, the data page. Zenodo concept DOI 10.5281/zenodo.24333249 (release `v2026.11.18`, 2026-11-18). Since 2026-11-18 every study carries authors, journal and DOI, copied by code from the fetched PubMed record (founder ruling in chat; check C13). |
| I-02 | **Funding map.** Who funds which hypothesis, set against its evidence level. | 4 | 3 | 12 | idea | Several grant databases, each with its own format; grants must be sorted by hypothesis. In the long-term vision of the v1 plan; no donations involved. |
| I-08 | **Funder briefs.** One page per gap: what is missing and which design would move the level. | 4 | 3 | 12 | idea | Depends on I-01. Sending them is the founder's work; no expert has reviewed the content, which limits the weight they carry. |
| I-09 | **Burden against funding.** Research funding per DALY for ME/CFS compared with other diseases, from published figures. | 3 | 4 | 12 | idea | Such comparisons have been published before (to verify), so the new value is keeping it current and visible. |
| I-11 | **Researchers from neighbouring fields.** Find groups whose method fits an untested gap and send them a concrete brief. | 4 | 3 | 12 | idea | Finding them is cheap (PubMed). The contact is the founder's work and the response is uncertain. |
| I-15 | **Studies that are recruiting**, per country. | 3 | 4 | 12 | in progress | Covered by I-03 as far as the plan goes: the page shows recruitment status and countries as copied registry facts, with no list of its own per country, no filters and no contact details (plan `docs/plan-trial-registry.md`, out of scope). |
| I-13 | **Reanalysis of open datasets.** Preregistered secondary analyses of data that are already open. | 5 | 2 | 10 | idea | The largest possible effect, but a result nobody qualified has checked is worth little and can do harm. Needs a research partner; the site makes no claim of discovery, so this is a separate project. |
| I-04 | **Quality barometer.** Share of studies per year with a strict case definition, a PEM requirement, controls, preregistration. | 3 | 3 | 9 | idea | Cheap for the studies on the cards, but that sample is skewed. The whole literature needs full texts, which we often lack. |
| I-18 | **Data-sharing barometer.** For each study on a card: are the raw data deposited, and where? | 3 | 3 | 9 | idea | Feeds I-14. Needs the data availability statement, so full text. |
| I-07 | **More languages.** | 2 | 4 | 8 | idea | The translation path exists; each language needs its own check. Helps patients more than research. |
| I-12 | **Living meta-analyses.** Effect sizes extracted and pooled per hypothesis. | 4 | 2 | 8 | idea | Needs an academic co-author and a reliable extraction of numbers from full text. |
| I-17 | **The atlas as a tool for researchers' AI assistants** (for example an MCP server over the cards). | 2 | 4 | 8 | idea | Depends on I-05. |
| I-06 | **Falsification table.** Per card: which observation would weaken the hypothesis, and has it been tested? | 3 | 2 | 6 | idea | Only what a source states can be cited, and reading relations across papers failed the bridge pilot twice. |
| I-10 | **Call monitor.** Watch open funding calls and match them to gaps. | 2 | 3 | 6 | idea | Researchers already follow their calls; many sources have no API. |
| I-16 | **Protocol template for ME/CFS studies.** Recommended case definition, PEM measure, common outcome set. | 3 | 2 | 6 | idea | Carries weight only with expert authority behind it; common data elements may already exist (to verify). |
| I-19 | **Our own bank of pooled raw data.** | 5 | 1 | 5 | parked | Patient-level data need consent, ethics approval, an access committee and secure storage. Existing banks do this already; I-14 and I-13 are our part of it. |
| I-21 | **AI-generated new hypotheses.** | 2 | 3 | 6 | parked | The site makes no claim of discovery, and nothing untested can be graded. |
| I-20 | **Drug candidates in silico** (gene → target → existing drug). | 4 | 1 | 4 | parked | Too close to treatment advice (credibility rule 3). |
| I-22 | **Collecting patient data or money ourselves** (wearables, crowdfunding). | 4 | 1 | 4 | parked | Against "no accounts, no database, no money handling". Point to those who already do it. |

## Existing data banks

The leads are in `registry/resource-leads.yaml` (URLs only, never a source); the published entries, each value with its quote from the resource's own stored page, are in `registry/resources.yaml`. Leads not in the data file, with the reason, are listed in the description of the pull request that built I-14.
