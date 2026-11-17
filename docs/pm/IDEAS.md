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
| I-03 | **Trial registry tracking.** Ongoing studies per hypothesis, and finished studies with no published result. | 4 | 4 | 16 | idea | Registries have open APIs (to verify). Sorting by hypothesis reuses the paper classifier. Finding "no published result" is harder than listing ongoing studies. |
| I-14 | **Data catalogue.** Which ME/CFS datasets, registries and biobanks exist, what they hold, and how a researcher gets access; linked from the hypotheses they bear on. | 4 | 4 | 16 | idea | The data banks exist but are scattered (see "Existing data banks"). We describe and link; we hold no patient data. |
| I-05 | **Open data and citation export.** Cards and links as a downloadable dataset with a DOI; BibTeX/RIS per card. | 3 | 5 | 15 | idea | The cards are already YAML. The content is already under CC BY 4.0 (`LICENSE-CONTENT`, since 2026-11-16), so no licence decision blocks it; a DOI needs a Zenodo account of the founder's. |
| I-02 | **Funding map.** Who funds which hypothesis, set against its evidence level. | 4 | 3 | 12 | idea | Several grant databases, each with its own format; grants must be sorted by hypothesis. In the long-term vision of the v1 plan; no donations involved. |
| I-08 | **Funder briefs.** One page per gap: what is missing and which design would move the level. | 4 | 3 | 12 | idea | Depends on I-01. Sending them is the founder's work; no expert has reviewed the content, which limits the weight they carry. |
| I-09 | **Burden against funding.** Research funding per DALY for ME/CFS compared with other diseases, from published figures. | 3 | 4 | 12 | idea | Such comparisons have been published before (to verify), so the new value is keeping it current and visible. |
| I-11 | **Researchers from neighbouring fields.** Find groups whose method fits an untested gap and send them a concrete brief. | 4 | 3 | 12 | idea | Finding them is cheap (PubMed). The contact is the founder's work and the response is uncertain. |
| I-15 | **Studies that are recruiting**, per country. | 3 | 4 | 12 | idea | Falls out of I-03 almost for free. Must stay a plain list: no advice to take part. |
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

## Existing data banks (web search, 2026-11-17)

Found by web search, not fetched through the pipeline. Each entry must be checked against its own source before it appears on the site (I-14).

- **mapMECFS** (NIH-funded, hosted by RTI International): portal for sharing and downloading molecular datasets from ME/CFS studies; open to researchers after registration. <https://mapmecfs.org/about>
- **searchMECFS** (same centre): finding and requesting biospecimens and de-identified clinical data. <https://www.nih.gov/advancing-mecfs-research/announcements/research-tools-mecfs-related-data-biospecimens-now-available>
- **DecodeME**: genotype and questionnaire data and DNA samples, on application to a data access committee. <https://www.decodeme.org.uk/researcher-access>
- **UK ME/CFS Biobank**: samples and data from patients, a multiple sclerosis comparison group and healthy controls. <https://www.frontiersin.org/articles/10.3389/fneur.2018.01026/full>
- **German registry and biobank (MECFS-R, MECFS-Bio)**: clinical and laboratory data from the centres in Berlin and Munich. <https://pubmed.ncbi.nlm.nih.gov/38892879/>
- **OMF ME/CFS Data Center** (Open Medicine Foundation). <https://www.omf.ngo/data-sharing-in-the-omf-me-cfs-data-center/>
- **Solve Together** (started by Solve M.E.): patient-reported, wearable and health record data from US adults. <https://solvecfs.org/research/solve-together/>
- **Norwegian thematic research register and biobank** at Oslo University Hospital: named in published studies; current status and access not found. TODO: verify.
- **ME/CFS Research Register** (ME/CFS Research Foundation, Hamburg): a register of research projects, groups and publications, not of raw data; covers Germany, Austria, Switzerland, the Netherlands, Norway and Iceland. <https://mrr.mecfs-research.org/en>

No new data bank announced in 2026 was found.
