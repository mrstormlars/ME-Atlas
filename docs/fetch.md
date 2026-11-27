# PubMed fetch

`src/me_atlas/pubmed.py` downloads ME/CFS papers from PubMed, keeps the raw responses, and parses them into records. Every bibliographic fact on a card (PMID, title, year, DOI, publication type, retraction) must trace back to one of these cached records. Plan: `docs/plan-fetch-script.md`.

## Setup

Put your contact email in `.env` (see `.env.example`):

- `CONTACT_EMAIL` is required. It is sent to NCBI with every request, as their usage policy asks. A run without it stops with an error.
- `NCBI_API_KEY` is optional. With a key the client makes up to 10 requests per second, without it up to 3.

## Running it

```bash
uv run python -m me_atlas.pubmed fetch --backfill            # the whole literature, once
uv run python -m me_atlas.pubmed fetch --weekly              # records entered in the last 14 days
uv run python -m me_atlas.pubmed fetch --since 2026-01-01 [--until 2026-06-30]
uv run python -m me_atlas.pubmed fetch --weekly --refresh    # download again even if cached
uv run python -m me_atlas.pubmed fetch --ids 12345678 23456789   # exactly these records
uv run python -m me_atlas.pubmed query-diff --term "CFS/ME" --term "post-viral fatigue syndrome"   # recall check
uv run python -m me_atlas.pubmed query-diff --cited-in drafts            # cited ids the query does not return
```

`--ids` takes one or more PMIDs (digits, or `pmid:<digits>`) and cannot be combined with `--since`, `--weekly`, `--backfill` or `--until`. It downloads exactly those records by EFetch, skipping any already cached unless `--refresh` is given. It runs **no search and no retraction query**, and does not read the query file. Use it for a paper a card cites that the search query does not find (for example a long COVID paper that does not mention ME/CFS), and to fix an error from the citation check (`docs/citation-check.md`). The manifest records `mode: "ids"` and the `ids` asked for, with counts and `new_pmids`, `missing_pmids` and `unparsable_pmids`.

`query-diff` checks whether the query misses ME/CFS papers (plan: `docs/plan-wider-sources.md`, part A). It never changes the query and feeds nothing to the pipeline.

- `--term T` (repeatable): searches `"T"[Title/Abstract] NOT (<query>)`, prints the hit count, and downloads up to `--sample N` (default 20) of the hits into `data/cache/pubmed/` (cached records are not downloaded again). The sample is the first N ids in PubMed's default order, which is roughly newest entry date first (see "Which records are sampled"). A term with no hits is reported as 0 and downloads nothing. PubMed warnings (for example a phrase not found) are printed and stored.
- `--ids PMID ...` and/or `--cited-in DIR` (every `pmid:<digits>` in the YAML files under `DIR`): asks PubMed which of those ids the query returns, by searching the query restricted to them (`(<query>) AND (id[uid] OR ...)`, 100 ids per request), and lists the ids it does not return. This checks PMIDs only; a study id of another kind (`doi:`) cannot be checked this way.
- It needs `CONTACT_EMAIL` like `fetch` (exit 2 without it, no request made) and uses the same rate limit. Options: `--query-file`, `--cache-dir`.
- Output: one JSON file `data/cache/query-diff/<timestamp>.json` per run, never under `runs/` (the pipeline reads manifests there). Fields: `timestamp`, `query_file`, `query`, `query_hits` (the current query's total), `order`, `sample`, `terms` (per term: `term`, `search`, `count`, `sample_size`, `sample_pmids`, `warnings`) and, when ids were given, `ids_check` (`ids`, `inside_count`, `outside`, `warnings`).

Dates are PubMed *entry dates* (the day a record entered PubMed), not publication dates. Weekly runs overlap by a week on purpose: a missed week is caught, and cached records are skipped.

Optional: `--query-file` (default `config/pubmed_query.txt`) and `--cache-dir` (default `data/cache`).

## What a run does

1. Searches PubMed with the query in `config/pubmed_query.txt` for the date window. If a result set is larger than the 9,999 ids ESearch can return, it is split by entry date until every part fits.
2. Runs the retraction query: the same query plus `"Retracted Publication"[Publication Type]`, **without the date window**. Retractions usually arrive long after a paper entered PubMed, and old papers are the ones cards cite.
3. Downloads (EFetch XML, 200 ids per request) every PMID from the two searches that is not cached yet. A cached copy of a paper that the retraction query says is retracted, but whose copy is not marked retracted, is downloaded again.
4. Writes the manifest.

The weekly pipeline's `prepare` also re-fetches the records of every study the cards and drafts cite (`fetch --ids ... --refresh`), because an `ErratumIn` link added to PubMed after a record was cached is seen only in a new copy, and then fetches any erratum those records list that is not cached (`docs/pipeline.md`, "What `prepare` selects").

Nothing is filtered at fetch time. Reviews, editorials and letters are fetched and their publication types recorded; deciding what counts as evidence belongs to classification.

The client retries HTTP 429, 5xx and network errors up to 4 times with exponential backoff (1, 2, 4, 8 seconds; a `Retry-After` header is honoured), then fails with an error that says how many attempts were made. Other 4xx errors fail at once.

## The query, and why

The query lives in `config/pubmed_query.txt`, so it can be reviewed and changed in a pull request. Lines starting with `#` are comments.

- **Block 1:** the MeSH heading "Fatigue Syndrome, Chronic", or the phrases "myalgic encephalomyelitis", "chronic fatigue syndrome", "ME/CFS", "CFS/ME" (added 2026-11-13, see the recall check below) or "systemic exertion intolerance disease" in title or abstract.
- **Block 2:** long COVID terms (MeSH "Post-Acute COVID-19 Syndrome", "long COVID", "post-COVID", "post-acute sequelae of SARS-CoV-2", "PASC") **AND** an ME/CFS term anywhere in the record. Long COVID alone is much larger than ME/CFS and outside v1 scope; this clause only catches the overlap studies that the long COVID label on a card needs. Its ME/CFS side uses "All Fields", so it also finds records where ME/CFS appears only in author keywords or MeSH.

**The MeSH headings were checked on 2026-10-31** against live PubMed: "Fatigue Syndrome, Chronic" alone gave 6,810 hits and "Post-Acute COVID-19 Syndrome" alone 5,524, with no warnings. Re-check them whenever the query changes. PubMed reports phrases it could not find (`phrasesnotfound`); these are printed as warnings and stored in the manifest.

### Recall check, 2026-11-13

Run on 2026-11-13 with `query-diff`; nothing here changes the query. Result files: `data/cache/query-diff/20261113T100024Z.json` (cited ids) and `data/cache/query-diff/20261113T100033Z.json` (terms). Both give the same hit count for the current query.

**Hit count of the current query on 2026-11-13: 9,403** (`config/pubmed_query.txt` as it was before the change recorded below, no date window).

#### Cited studies the query does not return

`drafts/` cites 279 distinct `pmid:` ids. No other kind of study id (for example `doi:`) is cited in `drafts/`, so every cited study could be checked. The query was asked for each id (`query AND id[uid]`, in batches of 100). It returned 279 of them; **0 are outside the query**.

So no cited study is outside the query: there is no non-ME source and no ME/CFS paper the query should have caught among them, and step 1 of the plan surfaced no extra candidate term. The cited-but-outside table is empty. This says nothing about papers nobody has cited yet, which is what the term check below is for.

#### Candidate terms

Search string per term: `"term"[Title/Abstract] NOT (<current query>)`. The "added" count is every record that string finds; the sample is up to 20 of them, taken in PubMed's default order (see "Which records are sampled" below). "About ME/CFS" counts the sampled records judged *yes* from title and abstract only; *unclear* and *no* are counted separately. PubMed gave no warnings for any term.

| Term | Search string | Added | Sample | About ME/CFS (yes) | Unclear | No |
|---|---|---|---|---|---|---|
| CFS/ME | `"CFS/ME"[Title/Abstract] NOT (<current query>)` | 9 | 9 | 7 | 1 | 1 |
| post-viral fatigue syndrome | `"post-viral fatigue syndrome"[Title/Abstract] NOT (<current query>)` | 21 | 20 | 0 | 8 | 12 |
| postviral fatigue syndrome | `"postviral fatigue syndrome"[Title/Abstract] NOT (<current query>)` | 14 | 14 | 0 | 10 | 4 |
| post-infectious fatigue syndrome | `"post-infectious fatigue syndrome"[Title/Abstract] NOT (<current query>)` | 4 | 4 | 0 | 0 | 4 |
| chronic fatigue immune dysfunction syndrome | `"chronic fatigue immune dysfunction syndrome"[Title/Abstract] NOT (<current query>)` | 2 | 2 | 0 | 1 | 1 |

`<current query>` stands for the full text of `config/pubmed_query.txt` joined into one line, as stored in the `query` field of the result file, which also holds each exact search string.

#### Precision sample

Judged from the cached title and abstract only (`data/cache/pubmed/<pmid>.xml`), not from the full text and not from MeSH headings. *yes*: the record is about ME/CFS (names it as its subject). *unclear*: the record is about a related or historical label (post-viral fatigue syndrome) or names ME/CFS only in passing, so the abstract alone does not settle it. *no*: another subject. Records marked "no abstract" are judged from the title and say so. "Correction notice" and "corrigendum" are notices attached to a paper, not studies.

**CFS/ME** (9 added, sample 9)

| PMID | Year | Title | About ME/CFS? | Reason |
|---|---|---|---|---|
| 41556825 | 2026 | [CFS/ME – from hysteria to a biomedical disease]. | yes | CFS/ME in the title; no abstract, judged from the title |
| 40042023 | 2025 | [CFS/ME patients are being heard and many benefit from available treatments]. | yes | CFS/ME in the title; no abstract, judged from the title |
| 37226008 | 2024 | Correction to: Anxiety in children with CFS/ME. | yes | correction notice for a paper on CFS/ME in the title; no abstract, judged from the title |
| 37165393 | 2023 | Correction: The impact of CFS/ME on employment and productivity in the UK: a cross-sectional study based on the CFS/ME national outcomes database. | yes | correction notice for a paper on CFS/ME in the title; no abstract, judged from the title |
| 36867709 | 2023 | The Evaluation of Health Care Services for Children and Adolescents With Post-COVID-19 Condition: Protocol for a Prospective Longitudinal Study. | no | protocol on post-COVID-19 condition in children; ME/CFS is not in the abstract text (why PubMed matched is not established) |
| 36800963 | 2023 | Correction: Defining the minimally clinically important difference of the SF-36 physical function subscale for paediatric CFS/ME: triangulation using three different methods. | yes | correction notice for a paper on CFS/ME in the title; no abstract, judged from the title |
| 29750068 | 2017 | Current treatment approaches for paediatric CFS/ME. | yes | CFS/ME in the title; no abstract, judged from the title |
| 28436348 | 2017 | Same, Same But Different? Cognitive Behavioural Treatment Approaches for Paediatric CFS/ME and Depression - CORRIGENDUM. | yes | corrigendum for a paper on paediatric CFS/ME in the title; no abstract, judged from the title |
| 20639288 | 2010 | Long-term persistence after acute Q fever of non-infective Coxiella burnetii cell components, including antigens. | unclear | study of Coxiella persistence after Q fever; the abstract calls Q fever fatigue syndrome "Q fever associated CFS/ME in the literature" but the subject is bacterial remnants |

**post-viral fatigue syndrome** (21 added, sample 20)

| PMID | Year | Title | About ME/CFS? | Reason |
|---|---|---|---|---|
| 42850025 | 2026 | Trends in long COVID and post-viral fatigue in children in primary care in England. | unclear | long COVID and PVFS consultations in children; ME/CFS not named |
| 42401313 | 2026 | Chronic stress primes TLR3-mediated systemic inflammation to produce persistent post-viral fatigue syndrome-like symptoms in mice. | no | mouse model of PVFS-like symptoms; ME/CFS not named |
| 42278343 | 2026 | Fibromyalgia: A Multifactorial Pain Disorder. | no | fibromyalgia review; no ME/CFS or fatigue-syndrome term in the text |
| 41281561 | 2025 | Does C1 esterase inhibitor play a role in post COVID-19 neurological symptoms? A randomized, double-blind, placebo-controlled, crossover, proof-of-concept study. | no | long COVID trial in people with SARS-CoV-2 post-viral fatigue syndrome; ME/CFS not named |
| 41013344 | 2025 | Medical complexity and healthcare utilization among patients attending three U.S. post-COVID clinics. | no | post-COVID clinics chart review; PVFS only as a recorded diagnosis |
| 37669378 | 2023 | Systems-level temporal immune-metabolic profile in Crimean-Congo hemorrhagic fever virus infection. | no | Crimean-Congo haemorrhagic fever |
| 35455008 | 2022 | Post-COVID-19 Condition: Where Are We Now? | no | post-COVID-19 condition review; PVFS mentioned as a comparison |
| 34341436 | 2021 | A cardiovascular magnetic resonance imaging-based pilot study to assess coronary microvascular disease in COVID-19 patients. | no | cardiac MRI in post-COVID patients |
| 34183705 | 2021 | Follow-up of COVID-19 recovered patients with mild disease. | no | follow-up of mild COVID-19; PVFS mentioned in the conclusion |
| 16438145 | 2005 | Survey on the management of dengue infection in Sri Lanka: opinions of physicians and pediatricians. | no | dengue management survey |
| 21851317 | 2003 | Infection and the elite athlete: a review. | no | infection in athletes; PVFS named as a possible complication |
| 8189405 | 1994 | 'Maybe it's a virus?': beliefs about viruses, symptom attributional style and psychological health. | no | beliefs about viruses; PVFS named as an example |
| 1467580 | 1992 | The role of nuclear medicine in neurology and psychiatry. | no | nuclear medicine review; PVFS in a list of applications |
| 2540242 | 1989 | Active Epstein-Barr virus infection in post-viral fatigue syndrome. | unclear | patients with PVFS studied for EBV; ME/CFS not named |
| 2854300 | 1988 | The epidemiology of post viral fatigue syndrome. | unclear | epidemiology of PVFS; ME/CFS not named |
| 3074289 | 1988 | Post-infectious disease syndrome. | unclear | review of evidence for a post-viral fatigue syndrome; ME/CFS not named |
| 27415482 | 1988 | Enterovirus Infection. | unclear | news item on enterovirus in PVFS patients; ME/CFS not named |
| 3368176 | 1988 | You and me--post-viral fatigue syndrome. | unclear | PVFS in the title; no abstract, judged from the title; ME/CFS not named |
| 3054638 | 1988 | A brief review of the immune system and its function in relation to: PVFS, non-antibody mediated allergy, autoimmunity and immune deficiency. | unclear | PVFS is one topic of an immune-system review; ME/CFS not named |
| 3505695 | 1987 | An investigation of patients presenting with multiple physical complaints using the illness behaviour questionnaire. | unclear | PVFS patients are one of three groups compared; ME/CFS not named |

**postviral fatigue syndrome** (14 added, sample 14)

| PMID | Year | Title | About ME/CFS? | Reason |
|---|---|---|---|---|
| 36359586 | 2022 | Ultrasonography Assessment Based on Muscle Thickness and Echo Intensity in Post-Polio Patients. | no | post-polio ultrasound study |
| 8390713 | 1993 | High yield production of an inactivated coxsackie B3 adjuvant vaccine with protective effect against experimental myocarditis. | no | enterovirus vaccine; postviral fatigue syndrome named in passing |
| 1661330 | 1991 | Human herpesvirus-6: the latest human herpes virus. | no | human herpesvirus-6 review; postviral fatigue syndrome named in passing |
| 2565511 | 1989 | VP-1 antigen in chronic postviral fatigue syndrome. | unclear | VP-1 antigen in chronic postviral fatigue syndrome (title); no abstract, judged from the title; ME/CFS not named |
| 2537551 | 1989 | [The postviral fatigue syndrome (PVS)--a chronic exhaustion syndrome. Is it possible to prove virus infection?]. | unclear | postviral fatigue syndrome, proof of virus infection (title, German); no abstract, judged from the title; ME/CFS not named |
| 3147070 | 1988 | Brainstorming the postviral fatigue syndrome. | unclear | postviral fatigue syndrome in the title; no abstract, judged from the title; ME/CFS not named |
| 2847520 | 1988 | Complications following coxsackievirus B infection. | no | coxsackievirus B complications; postviral fatigue syndrome named in passing |
| 3173539 | 1988 | [Tiring induced by viruses--postviral fatigue syndrome]. | unclear | postviral fatigue syndrome in the title; no abstract, judged from the title; ME/CFS not named |
| 2898669 | 1988 | Interferon production in postviral fatigue syndrome. | unclear | postviral fatigue syndrome in the title; no abstract, judged from the title; ME/CFS not named |
| 3133071 | 1988 | Postviral fatigue syndrome. | unclear | postviral fatigue syndrome in the title; no abstract, judged from the title; ME/CFS not named |
| 3130143 | 1988 | Postviral fatigue syndrome. | unclear | postviral fatigue syndrome in the title; no abstract, judged from the title; ME/CFS not named |
| 2892990 | 1988 | Chronic enterovirus infection in patients with postviral fatigue syndrome. | unclear | 76 patients with postviral fatigue syndrome and controls (enterovirus); ME/CFS not named |
| 2880043 | 1987 | Postviral fatigue syndrome. | unclear | postviral fatigue syndrome in the title; no abstract, judged from the title; ME/CFS not named |
| 2993423 | 1985 | The postviral fatigue syndrome--an analysis of the findings in 50 cases. | unclear | 50 patients with postviral fatigue syndrome; ME/CFS not named |

**post-infectious fatigue syndrome** (4 added, sample 4)

| PMID | Year | Title | About ME/CFS? | Reason |
|---|---|---|---|---|
| 40004921 | 2025 | Course of General Fatigue in Patients with Post-COVID-19 Conditions Who Were Prescribed Hochuekkito: A Single-Center Exploratory Pilot Study. | no | long COVID Kampo study; post-infectious fatigue syndrome used as a class label |
| 37398713 | 2023 | Mechanisms and Severity of Exercise Intolerance Following COVID-19 and Similar Viral Infections: A Comparative Review. | no | exercise intolerance after COVID-19, comparative review |
| 32520958 | 2020 | Molecular detection of Coxiella burnetii in livestock farmers and cattle from Magdalena Medio in Antioquia, Colombia. | no | Coxiella in farmers and cattle |
| 32503444 | 2020 | Objective cognitive performance and subjective complaints in patients with chronic Q fever or Q fever fatigue syndrome. | no | Q fever fatigue syndrome cognition study; ME/CFS not named |

**chronic fatigue immune dysfunction syndrome** (2 added, sample 2)

| PMID | Year | Title | About ME/CFS? | Reason |
|---|---|---|---|---|
| 30116169 | 2018 | Cytotoxic Profiling of Endogenous Metabolites Relevant to Chronic Fatigue Immune Dysfunction Syndrome (CFIDS) on p53 Variant Human Colon Carcinoma Cell Lines. | unclear | names CFIDS in the title, but the experiments are on colon carcinoma cell lines |
| 9630736 | 1998 | The detoxification enzyme systems. | no | detoxification enzymes review; CFIDS in a list of diseases |

#### Outcome (the proposal put to the founder)

- **"CFS/ME": proposed.** 7 of the 9 added records are about ME/CFS by their title. They are mostly short records (correction notices and items with no abstract) whose only ME/CFS wording is the form "CFS/ME", which the query's phrases ("ME/CFS", "chronic fatigue syndrome") do not match. The gain is small (9 records in all).
- **"post-viral fatigue syndrome" and "postviral fatigue syndrome": not proposed on the plan's criterion** (most of the sample about ME/CFS): no sampled record names ME/CFS. The sampled records are either about other subjects that mention the term in passing, or about "post-viral fatigue syndrome" as a label itself, mostly from 1985 to 1993 (8 and 10 records marked *unclear*). Whether that older label should count as ME/CFS literature is a question for the founder; this check cannot settle it from titles and abstracts. "post-viral fatigue syndrome" (PubMed matches it with and without the hyphen) also adds recent long COVID papers that use the label, and one record of its 21 (the 21st in PubMed's order) was not sampled.
- **"post-infectious fatigue syndrome" and "chronic fatigue immune dysfunction syndrome": not proposed.** The samples are about other conditions (long COVID, Q fever, a cell-line study, an enzyme review) or one unclear record; all 4 and 2 added records were sampled.
- **Nothing is missed among the cited studies:** the query returns all 279.

#### Ruling and query change, 2026-11-13

The founder accepted "CFS/ME" on 2026-11-13. `"CFS/ME"[Title/Abstract]` was added to block 1 of `config/pubmed_query.txt`; block 2 is unchanged. The four other terms ("post-viral fatigue syndrome", "postviral fatigue syndrome", "post-infectious fatigue syndrome", "chronic fatigue immune dysfunction syndrome") were tested and not accepted (founder: "Bare CFS/ME").

On the two post-viral terms, if every *unclear* record were counted as about ME/CFS: the hyphenated "post-viral fatigue syndrome" would still not meet the criterion (8 of 20 sampled), while "postviral fatigue syndrome" would (10 of 14).

- **Hit count before:** 9,403. **After:** 9,412 (both on 2026-11-13, no date window), a gain of 9, equal to the added-record count measured above.
- After the change, `"CFS/ME"[Title/Abstract] NOT (query)` returns 0 records (result file `data/cache/query-diff/20261113T100810Z.json`).
- The 9 records are not fetched into the pipeline by this change; a later fetch run picks them up by its own date window or a backfill.
- The MeSH headings of the query are unchanged and were not re-counted on this date.

#### Which records are sampled

The sample is the first N ids of ESearch's default ordering, with no `sort` parameter. A live check on 2026-11-13 of the current query (first 100 ids, then their cached entry dates) showed the default order is roughly newest entry date first (the day the record entered PubMed): of 99 parsed records, 97 of 98 neighbouring pairs were in non-increasing entry-date order, and one pair was not (42551185, entered 2026-08-04, before 42568470, entered 2026-08-08). One id (42877512) did not appear in the EFetch response and was left out. The same query with `sort=pub_date` returned a different order (publication date; a paper's publication date can lie well after its entry date), and `sort=most recent` is not a valid ESearch sort (PubMed warned "Unknown sort schema 'most recent' ignored" and used the default). So "most recent" here means newest entry date, as elsewhere in this project, and only approximately. For every term with 20 or fewer added records the sample is all of them.

## Preprints (Europe PMC)

Preprints are taken in as labelled early signals (`docs/plan-wider-sources.md`, part B). PubMed holds only some of them, so the weekly `pipeline prepare` also searches Europe PMC. What was checked against live responses on 2026-11-13:

- **Filter.** `SRC:PPR` in the Europe PMC REST search (`https://www.ebi.ac.uk/europepmc/webservices/rest/search`, `format=json`, `resultType=core`) returns only preprints: every hit has `source` "PPR", an id `PPR<digits>`, `pubTypeList.pubType` ["Preprint"] and no `pmid`.
- **Date.** `FIRST_IDATE:[YYYY-MM-DD TO YYYY-MM-DD]` restricts by the date Europe PMC first indexed the record (`firstIndexDate` in the result). It is not the date the preprint was posted (`firstPublicationDate`).
- **Terms.** Title and abstract terms are written `TITLE_ABS:"..."`. The term block is `config/europepmc_preprint_query.txt`: the five title/abstract terms of block 1 of the PubMed query (not its MeSH heading, which preprints do not have), joined by OR. A test fails if the two files list different terms. Code adds ` AND SRC:PPR AND FIRST_IDATE:[since TO until]`. The query `(TITLE_ABS:"myalgic encephalomyelitis" OR TITLE_ABS:"chronic fatigue syndrome" OR TITLE_ABS:"ME/CFS" OR TITLE_ABS:"CFS/ME" OR TITLE_ABS:"systemic exertion intolerance disease") AND SRC:PPR AND FIRST_IDATE:[2026-08-15 TO 2026-11-13]` had `hitCount` 27 on 2026-11-13. The same five terms unfielded (without `TITLE_ABS:`) gave 29; that response is the one used to shape the test fixtures.
- **The published version.** A preprint that has been published carries `commentCorrectionList.commentCorrection[]` entries; the one that links forward has `type` "Preprint of", `source` "MED" and `id` = the PMID of the published article. Its `note` is "CrossRef Pre-print loader" or "Link created based on a title-first author match", so a link can be a title match and not a publisher declaration; the note is kept and shown. The link was present on 57 of 100 ME/CFS preprints first indexed in 2022.
- **Versions.** `versionNumber` and `versionList.version[]` (`id`, `versionNumber`, `firstPublishDate`). Each version is its own PPR record with its own DOI.
- **Full text.** `fullTextIdList.fullTextId` lists the record's own PPR id and, if the text is in PubMed Central, a PMC id; the code takes only an id that looks like `PMC<digits>`. `isOpenAccess` and `inPMC` are read too. Full text goes through `europepmc.get_fulltext`, with the same statuses and the same `<pmcid>.xml` cache as for a PubMed paper.
- **The same paper from both sources.** PubMed marks a preprint with the publication type `<PublicationType UI="D000076942">Preprint</PublicationType>`; the journal title is not used. Example: pmid:42996068 has "Journal Article" and "Preprint" (journal "medRxiv : the preprint server for health sciences", DOI 10.64898/2026.10.19.26365953). Europe PMC has a PPR twin of it, PPR1347206, with no `pmid` and the same DOI. A preprint that PubMed has flows through the pipeline as the PubMed record (it keeps its PMID and is marked `preprint`); the PPR twin is dropped.

**De-duplication in `pipeline prepare`.** The search covers the same window as the PubMed fetch (`--since` to the run date, or the last 14 days). Each record is dropped for the first of these reasons, and every drop is listed in `prepare.json` under `preprints` with its PPR id, DOI and reason; the counts (found, dropped per reason, offered) sit beside the list.

1. `published`: it has a "Preprint of" link to a PubMed record (listed with the PMID, whether that PMID is in the PubMed cache, and the link's note).
2. `in_pubmed`: its DOI (compared case-insensitively) is the DOI of a record in this run's PubMed window or in the PubMed cache.
3. `superseded`: its version list names a higher version whose PPR id is also among this search's records.
4. `no_doi`: it has no DOI.
5. `processed`: an earlier finished run processed it (the ledger, keyed by PPR id), unless `--reprocess`.

The survivors go into `papers.json` as `doi:<doi>` papers with no PMID (see `docs/pipeline.md`). A failed search fails `prepare`.

**Cache layout.** Under `data/cache/europepmc/preprints/`: `search-<since>_<until>-<n>.json` (each raw page of a search), `PPR<digits>.json` (one raw record, whichever search or DOI lookup found it). `uv run python -m me_atlas.europepmc preprint <doi>...` fetches and caches the record of a DOI (`DOI:"<doi>" AND SRC:PPR`), which is how a preprint is cited on a card as a `doi:` study with `preprint: true`; `--fulltext` also looks for its open-access full text.

## Registry fetch (ClinicalTrials.gov)

`uv run python -m me_atlas.trials fetch [--offline] [--date YYYY-MM-DD]` fetches two condition searches from the public API v2 (`https://clinicaltrials.gov/api/v2/studies`, `query.cond`, `pageSize=1000`, `countTotal=true`, `pageToken` paging, all statuses) and writes `registry/trials.yaml`. One request a second at most, the generic User-Agent `me-atlas-research-client`, no key, no name or address sent; retries as for PubMed (`me_atlas.http`).

- `me_cfs`: `"chronic fatigue syndrome" OR "myalgic encephalomyelitis"`.
- `long_covid`: `"long COVID" OR "post COVID-19 condition" OR "post-COVID syndrome" OR "post-COVID-19 syndrome" OR "post-COVID condition" OR (PASC AND COVID)`. The registry expands synonyms in `query.cond` (so "long COVID" also finds "post-acute COVID-19 syndrome"); a bare `PASC` matched unrelated studies and is therefore restricted to studies that also say COVID.

Both searches are fetched in full each week (about three requests). A study returned by both is one entry with both search names. The raw responses are cached before parsing, one file per page: `data/cache/clinicaltrials/<fetch date>/<search>-<page>.json`; a second run with `--offline` reads that cache and makes no request. A failed request (an HTTP error after the retries, a page without `studies`, a `totalCount` that does not match the records received) exits non-zero and leaves `registry/trials.yaml` unchanged. A refresh replaces the copied fields of a known study and keeps its `hypotheses` and `mapping`; a study the fetch no longer returns stays with its last values and an empty `searches` list, and is not listed. `trials check` validates the file; `trials check --cache` compares every copied field with the newest cached record (the cache is local only, so this runs locally before publishing).

First fetch, 2026-11-18: 222 studies for `me_cfs` (53 ongoing), 734 for `long_covid` (211 ongoing), 917 in the union (247 ongoing).

## Resource fetch (data resources)

`uv run python -m me_atlas.resources fetch [--offline] [--date YYYY-MM-DD]` fetches the pages of the leads in `registry/resource-leads.yaml` (per lead `id`, `url`, optional `access_url`; nothing else). Code: `me_atlas.resources`; the plan is `docs/plan-data-catalogue.md`.

- **Client.** Through `me_atlas.http.get_with_retries`, with the generic User-Agent `me-atlas-research-client` (`trials.USER_AGENT`): no name, address or `.env` value, no cookies, no other headers tried. At most one request a second per host. Redirects are followed by hand, and every hop is checked against the robots file of its own host.
- **robots.txt.** The host's `robots.txt` is read (standard library `urllib.robotparser`) for that User-Agent before any page. Disallowed: the page is not fetched, status `robots_disallowed`. `robots.txt` redirects are followed (up to 5 hops, a loop or more hops is `robots_unavailable`); `robots.txt` answering 4xx counts as no rules (allowed); 5xx, a network error or an unreadable answer: not fetched, status `robots_unavailable`.
- **Statuses of a page** (`fetch-report.json`): `ok` only for HTTP 200, a content type with `html` and at least 200 characters of extracted text. Otherwise `http_<code>` (the code after the retries), `not_html`, `no_text`, `blocked` (HTTP 401, 403 or 429, or a page of under 1000 characters of visible text that says one of the phrases in `BLOCK_PHRASES` ("just a moment", "verify you are human", "checking your browser", "enable javascript and cookies to continue") or has a real `<input type=password>` element; CSS, scripts, attribute values and JSON in the source never count), `network_error`, `robots_disallowed`, `robots_unavailable`, and in `--offline` mode `not_cached`. A bot check or a login is never worked around: no retry with other headers, no browser, no cookies.
- **Cache.** `data/cache/resources/<fetch date>/<lead id>/` holds, per page (`main`, and `access` when the lead has an `access_url`), the raw body (`main.html`, `access.html`), `<page>.meta.json` (requested and final URL, HTTP status, content type, fetch date, status, and `obtained`: `fetched`, or `hand_saved` for a page saved by hand, see below) and `<page>.txt`, the visible text extracted by code (standard library `html.parser`; script, style and head dropped, whitespace collapsed). Everything is written before anything reads it. `--offline` reads that folder and makes no request. The cache is local only and gitignored.
- **Report.** `data/pipeline/<date>/resources/fetch-report.json`: lead id to the status of each page, and the list of fetchable leads (every page `ok`). A lead with a page that is not `ok` gets no context file and cannot be published; the report names it.

The drafting, review and data-file steps are in `docs/pipeline.md` ("Data resources").

### Pages saved by hand

Some hosts refuse an automated request (status `blocked`). Code never works around that. Instead the founder saves the page from a browser and stores the copy with `import-saved`; the page then follows the same path as a fetched one and is marked as saved by hand (`obtained: hand_saved` in `<page>.meta.json`, `hand_saved` in the context file and the entry, a marker on the site). Fetched pages carry `obtained: fetched`; a meta file without the key reads as `fetched`.

1. Open the exact address in the table below in a browser and, once the page has loaded fully, use "Save page as" and choose "Webpage, HTML only" (not "complete", not PDF, not a screenshot).
2. Put the file at `data/hand-saved/resources/<lead id>/main.html` (or `main.htm`, which Windows browsers often write), and the second page of a lead with an `access_url` at `data/hand-saved/resources/<lead id>/access.html` (or `.htm`). Only one of the two may exist for a page. The folder is gitignored (the copies are not ours to redistribute; the `data/` backup covers them).
3. For each page: `uv run python -m me_atlas.resources import-saved --lead <lead id> --page main --url <the exact address> --saved <YYYY-MM-DD, the day the page was saved>` (and `--page access` for the second page). The command stores the page in `data/cache/resources/<saved>/<lead id>/` exactly as a fetched page is stored, prints its status (`ok`, `no_text` or `blocked`, by the same rule as a fetched page) and exits 0 only for `ok`. It refuses, and writes nothing, when the lead is not in the leads file, `--page access` is given for a lead with no `access_url`, `--url` is not exactly the lead's address, `--saved` is not a date or is in the future, the file is missing, both `.html` and `.htm` exist for the page, or a page is already stored for that date, lead and page that is `ok` or was itself saved by hand. A stored page from a fetch whose status is not `ok` (for example `blocked`, with no HTML) is not refused: its files are renamed to `<page>.fetch-refused.meta.json` (and `.html`, `.txt` if present) and kept, and the saved page is stored in their place. If a `.fetch-refused.*` file already exists for that page, the command refuses. Nothing reads the `.fetch-refused.*` files as a page.
4. Then the usual path with the same date: `resources fetch --offline --date <saved>`, `resources plan --date <saved>`, the `resource-drafter`, `resources record-draft`, the `card-reviewer` in resource mode, `resources record-review`, `resources reliability`. A later online `resources fetch` for that date never overwrites a page saved by hand: it makes no request for it and reports its stored status.

| Lead id | Page | Address to save | File |
| --- | --- | --- | --- |
| `decodeme` | `main` | https://institute-genetics-cancer.ed.ac.uk/decodeme-the-worlds-largest-mecfs-study/researcher-access | `data/hand-saved/resources/decodeme/main.html` |
| `omf-data-center` | `main` | https://www.omf.ngo/data-sharing-in-the-omf-me-cfs-data-center/ | `data/hand-saved/resources/omf-data-center/main.html` |
| `solve-together` | `main` | https://solvecfs.org/research/solve-together/ | `data/hand-saved/resources/solve-together/main.html` |
| `uk-me-cfs-biobank` | `main` | https://cureme.lshtm.ac.uk/index.php/biobank/ | `data/hand-saved/resources/uk-me-cfs-biobank/main.html` |
| `uk-me-cfs-biobank` | `access` | https://cureme.lshtm.ac.uk/index.php/biobank/apply/ | `data/hand-saved/resources/uk-me-cfs-biobank/access.html` |

For `decodeme`, save exactly the `institute-genetics-cancer.ed.ac.uk` address above; `decodeme.org.uk` must not be used (`import-saved` refuses it, because `--url` must be the lead's own address).

### Full texts saved by hand

A study that is free to read on PubMed Central but has no open-access XML (status `free_on_pmc` in `fulltext needs`, see `docs/fulltext-targets.md`) can be read from a PMC article page saved by hand. The shared rules are those of "Pages saved by hand" above: code never works around a bot check, the folder is gitignored, and the copy is not ours to redistribute.

1. Open `https://pmc.ncbi.nlm.nih.gov/articles/<pmcid>/` (the address `needs` prints) and use "Save page as" ("Webpage, HTML only" or "complete"; either works).
2. Put the file at `data/hand-saved/fulltext/<pmid>.html` (or `.htm`). Only one of the two may exist.
3. `uv run python -m me_atlas.fulltext import-saved --card <card.yaml> --pmid <pmid>`. It copies the file unchanged to `data/cache/europepmc/<pmcid>.html`, where `citations check` and `europepmc casedef` already read it, and prints the case-definition candidates. It makes no request. It refuses, and writes nothing, when the PMID is not a `pmid:` study on the card, the file is missing or both `.html` and `.htm` exist, no PMC id is known from the cached lookup or PubMed record, full-text XML or a page is already cached for that PMC id, or the page is not the article page of that PMID with a main article body.
4. Back up `data/` as described under "Backup of the local data".

## Open PDF copies (Unpaywall)

Many papers have a legal open copy outside PubMed Central, usually a PDF on the publisher's site or in a repository. `uv run python -m me_atlas.unpaywall fetch --card <card or draft> [PMID...] [--refresh]` finds and caches that copy for the `pmid:` studies cited on the card or draft it is given (never for any other paper); `casedef --card ... [PMID...]` does the same and then prints the sentences that may name a case definition or exclude people with the illness (`[exclusion]`), each with its page number. When the cached meta says no reference list was cut, one `note:` line under the study line warns that a candidate may come from the reference list. Output that the console cannot encode is printed with replacement characters instead of stopping the run. Code: `me_atlas.unpaywall`; design: `docs/plan-unpaywall-pdf.md`; the founder's ruling of 2026-11-27 is in `docs/pm/DECISIONS.md`.

- **Setup.** `CONTACT_EMAIL` is needed for any request. It is sent to Unpaywall only, as the `email` parameter its documentation requires, and is never written to the cache, a report or a log. Without it, cached data is read and a needed request is refused (exit 2, nothing requested). Unpaywall asks for at most 100,000 calls a day; this project sends at most one request a second and only for cited studies.
- **Terms.** Unpaywall's data must not be republished without consent, and third parties may restrict how their copies are used. So the answers and the PDFs stay in the gitignored cache, are never redistributed, and a card quotes at most the one sentence that states the case definition.
- **The DOI** is read from the cached PubMed record of the PMID, never from the card. No DOI: status `no_doi`, nothing requested. HTTP 404 from Unpaywall: `not_in_unpaywall`.
- **Which copy.** Only `oa_locations` with a `url_for_pdf` (a landing page is never followed), of version `publishedVersion` or `acceptedVersion` (`submittedVersion` is never used), whose PDF host is not PubMed Central (`ncbi.nlm.nih.gov`), Europe PMC (`europepmc.org`, `ebi.ac.uk`) or a subdomain of them. `oa_locations_embargoed` is ignored. Order: published before accepted, publisher before repository, `is_best` first, then Unpaywall's order. No such location: `no_oa_pdf`. The first location that gives a usable PDF is used; every attempt and its outcome is printed.
- **Download.** The generic client of "Resource fetch" above (`me_atlas.resources.Fetcher`): User-Agent `me-atlas-research-client`, no cookies, no other headers tried, `robots.txt` read before every request and for every redirect hop, one request a second per host. A PDF is HTTP 200 with a body that starts with `%PDF-`; anything else is `blocked` (HTTP 401, 403, 429 or a bot check), `not_pdf`, `http_<code>`, `robots_disallowed`, `robots_unavailable` or `network_error`, nothing is cached, and the next location is tried. Over 30 MB: `too_large`. A bot check, a login or a paywall is never worked around.
- **Identity.** The PDF is used only if the PubMed title (lowercase letters and digits only) is in the text of its first two pages, reduced the same way; otherwise `title_not_found`. A PDF with no text layer (a scan) is `no_text`; a damaged file is `unreadable_pdf`. There is no OCR.
- **Cache** (gitignored): `data/cache/unpaywall/<key>.json` is the raw Unpaywall answer; for a usable PDF `data/cache/unpaywall/pdf/<key>.pdf`, `<key>.txt` (the extracted text, one form feed between pages, a line-end hyphen between letters marked with U+E000) and `<key>.meta.json` (DOI, PMID, PDF URL, final URL, landing page URL, `host_type`, `version`, `license`, fetch date, SHA-256, extractor name and version, pages, whether a reference list was cut). `<key>` is the lowercase DOI with every character outside `[a-z0-9._-]` percent-encoded. A cached answer with no usable copy is asked again after 7 days; a cached PDF is not requested again unless `--refresh` is given.
- **Text.** Extracted with `pdfminer.six` (layout analysis, so two columns read column by column), then Unicode NFKC (ligatures), soft hyphens removed, the reference list cut at the last line that is only "References", "Bibliography" or "Literature cited" when that line is in the second half, line breaks and whitespace collapsed. Running headers and page numbers stay in the text.
- **Quotes.** A quote must be found word for word on one page (`citations.normalise_quote` on both sides), each line-break hyphen read either as removed or as a hyphen, and each line break right after a slash ("CDC/" then "Fukuda", marked U+E001 in the stored text) read either as nothing or as a space. No other whitespace is flexible; a slash followed by a space inside a line does not match without the space. No fuzzy matching. A cached `.txt` written before the slash marker existed lacks it: run `fetch --refresh` for that study to extract it again (the simpler choice; nothing is re-extracted on read). A study that quotes a PDF has `case_definition_source: fulltext_pdf` (`docs/card-format.md`); the citation check C5 reads the cached text and C14 needs the founder's confirmation (`docs/citation-check.md`).
- **The founder's confirmation.** `uv run python -m me_atlas.unpaywall pending [--card PATH]...` lists every `fulltext_pdf` quote without a confirmation (card, study, quote, page, PDF URL, landing page URL, version, host type; exit 0 when none). The founder opens the PDF URL, checks the sentence on that page, and runs `uv run python -m me_atlas.unpaywall confirm --card <card> <pmid>`, which refuses unless the quote matches the cached text and appends one entry to `confirmations/pdf-quotes.yaml` (in git). Only the founder runs `confirm`; no agent and no pipeline step does.

## Where the output goes

Both are under `data/cache/`, which is gitignored and reproducible.

- `data/cache/pubmed/<pmid>.xml`: the raw `<PubmedArticle>` XML for one record.
- `data/cache/runs/<timestamp>.json` (UTC, e.g. `20261031T120000Z.json`): the manifest. This is what the next pipeline step reads.

Manifest fields: `query`, `query_file`, `window` (mode, since, until; the date type is always the entry date), `retraction_query`, `refresh`, `counts` (window hits, retraction hits, requested, fetched, new, skipped as cached, missing, unparsable), `new_pmids`, `window_pmids` (every hit of the window search, cached or not; the weekly pipeline selects from these), `retracted_pmids` (every hit of the retraction query, on every run), `newly_flagged_retracted_pmids` (cached copies that turned out to be retracted), `missing_pmids` (asked for but not returned by PubMed), `unparsable_pmids` (cached, but could not be parsed; look at them) and `warnings`.

## Backup of the local data

`data/cache/` and `data/pipeline/` are not in git and exist only in the working checkout. On 2026-11-16 the cache was deleted by accident when old worktrees were removed; most of it could be re-fetched, but 16 full texts had to be saved by hand because PubMed Central now answers automated requests with a bot check. Since 2026-11-17 the `data/` folder is backed up (founder ruling in DECISIONS):

- A separate git repository tracks `data/` as its work tree. Its git directory lives **beside** the project folder (`../ME-Atlas-data.git`), not inside it, so deleting `data/` or the checkout cannot delete the backup's history.
- It is pushed to a **private** repository of the founder's. It must stay private: the cache holds full texts that are free to read but not free to redistribute.
- Set-up in a clone, once, with `<private-url>` the address of that repository:

  ```bash
  git clone --bare <private-url> ../ME-Atlas-data.git
  git --git-dir=../ME-Atlas-data.git config core.bare false
  git --git-dir=../ME-Atlas-data.git config core.worktree "$(pwd)/data"
  git --git-dir=../ME-Atlas-data.git config core.autocrlf false
  git --git-dir=../ME-Atlas-data.git checkout -f main      # restores data/ from the backup
  ```

- Back up after any run that fetched or wrote under `data/` (add everything, commit if something changed, push):

  ```bash
  git --git-dir=../ME-Atlas-data.git add -A
  git --git-dir=../ME-Atlas-data.git commit -m "Backup <date>"
  git --git-dir=../ME-Atlas-data.git push origin main
  ```

  The founder's clone has this as the local alias `git data-backup`.
- To restore a deleted file or folder: `git --git-dir=../ME-Atlas-data.git checkout -- <path under data/>`.
- Before removing a worktree or any folder in this project, list links inside it (`find <dir> -type l`; on Windows also `dir /AL /S <dir>`) and unlink them first. A junction into `data/` is followed by a recursive delete.

A file missing from the cache is a reason to check that the cache folder is there, not evidence that the record was never fetched.

## The parsed record

`parse_xml()` / `RawCache.read_record()` return a `PubMedRecord`:

| Field | Meaning |
|---|---|
| `id` | `pmid:<digits>`, valid as a card `StudyId` |
| `pmid`, `doi` | `doi` is null when the record has none |
| `title`, `abstract` | abstract is null when absent; structured abstracts are joined as `LABEL: text`, one section per line |
| `journal`, `year` | year comes from `Year`, or from `MedlineDate` (e.g. "2019 Jan-Feb") when `Year` is absent; null if neither has a year |
| `authors` | display names as PubMed gives them, e.g. "Smith AB"; collective authors as named |
| `publication_types`, `mesh_terms` | MeSH descriptors only, no qualifiers |
| `retracted` | true if the record has the "Retracted Publication" type, or a `RetractionIn` link to its retraction notice. The notice itself ("Retraction of Publication") is not marked retracted |
| `entry_date` | the PubMed entry (Entrez) date, ISO format |
| `errata` | PMIDs of the erratum notices that correct this record (`CommentsCorrections` `RefType="ErratumIn"`), in record order, once each; empty when none |
| `erratum_for` | PMIDs of the articles this record is an erratum for (`ErratumFor`); empty when none |
| `other_ref_types` | `CommentsCorrections` `RefType` values the code does not know (known: `CommentIn`, `CommentOn`, `ErratumIn`, `ErratumFor`, `UpdateOf`, `UpdateIn`, `RetractionIn`, `RetractionOf`), so a new kind of notice is seen; empty when none |

## Tests

`tests/test_pubmed.py` uses hand-made fictional records in `tests/fixtures/pubmed/` (PMIDs 90000001 to 90000008, and 90000009, a PubMed preprint; the `query-diff` tests use generated copies of one of them) and `httpx.MockTransport`. No network, no real sleeping (the rate limiter takes a fake clock). A live check against the real PubMed is a manual step, recorded in the pull request.
