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

Nothing is filtered at fetch time. Reviews, editorials and letters are fetched and their publication types recorded; deciding what counts as evidence belongs to classification.

The client retries HTTP 429, 5xx and network errors up to 4 times with exponential backoff (1, 2, 4, 8 seconds; a `Retry-After` header is honoured), then fails with an error that says how many attempts were made. Other 4xx errors fail at once.

## The query, and why

The query lives in `config/pubmed_query.txt`, so it can be reviewed and changed in a pull request. Lines starting with `#` are comments.

- **Block 1:** the MeSH heading "Fatigue Syndrome, Chronic", or the phrases "myalgic encephalomyelitis", "chronic fatigue syndrome", "ME/CFS" or "systemic exertion intolerance disease" in title or abstract.
- **Block 2:** long COVID terms (MeSH "Post-Acute COVID-19 Syndrome", "long COVID", "post-COVID", "post-acute sequelae of SARS-CoV-2", "PASC") **AND** an ME/CFS term anywhere in the record. Long COVID alone is much larger than ME/CFS and outside v1 scope; this clause only catches the overlap studies that the long COVID label on a card needs. Its ME/CFS side uses "All Fields", so it also finds records where ME/CFS appears only in author keywords or MeSH.

**The MeSH headings were checked on 2026-10-31** against live PubMed: "Fatigue Syndrome, Chronic" alone gave 6,810 hits and "Post-Acute COVID-19 Syndrome" alone 5,524, with no warnings. Re-check them whenever the query changes. PubMed reports phrases it could not find (`phrasesnotfound`); these are printed as warnings and stored in the manifest.

### Recall check, 2026-11-13

Run on 2026-11-13 with `query-diff`; nothing here changes the query. Result files: `data/cache/query-diff/20261113T100024Z.json` (cited ids) and `data/cache/query-diff/20261113T100033Z.json` (terms). Both give the same hit count for the current query.

**Hit count of the current query on 2026-11-13: 9,403** (the unchanged `config/pubmed_query.txt`, no date window).

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

#### Outcome (a proposal awaiting the founder's ruling, not a decision)

- **"CFS/ME": proposed.** 7 of the 9 added records are about ME/CFS by their title. They are mostly short records (correction notices and items with no abstract) whose only ME/CFS wording is the form "CFS/ME", which the query's phrases ("ME/CFS", "chronic fatigue syndrome") do not match. The gain is small (9 records in all).
- **"post-viral fatigue syndrome" and "postviral fatigue syndrome": not proposed on the plan's criterion** (most of the sample about ME/CFS): no sampled record names ME/CFS. The sampled records are either about other subjects that mention the term in passing, or about "post-viral fatigue syndrome" as a label itself, mostly from 1985 to 1993 (8 and 10 records marked *unclear*). Whether that older label should count as ME/CFS literature is a question for the founder; this check cannot settle it from titles and abstracts. "post-viral fatigue syndrome" (PubMed matches it with and without the hyphen) also adds recent long COVID papers that use the label, and one record of its 21 (the 21st in PubMed's order) was not sampled.
- **"post-infectious fatigue syndrome" and "chronic fatigue immune dysfunction syndrome": not proposed.** The samples are about other conditions (long COVID, Q fever, a cell-line study, an enzyme review) or one unclear record; all 4 and 2 added records were sampled.
- **Nothing is missed among the cited studies:** the query returns all 279.

If the founder accepts a term, the query change goes in its own pull request with the hit count before (9,403 on this date) and after, and `docs/fetch.md` is updated there.

#### Which records are sampled

The sample is the first N ids of ESearch's default ordering, with no `sort` parameter. A live check on 2026-11-13 of the current query (first 100 ids, then their cached entry dates) showed the default order is roughly newest entry date first (the day the record entered PubMed): of 99 parsed records, 97 of 98 neighbouring pairs were in non-increasing entry-date order, and one pair was not (42551185, entered 2026-08-04, before 42568470, entered 2026-08-08). One id (42877512) did not appear in the EFetch response and was left out. The same query with `sort=pub_date` returned a different order (publication date; a paper's publication date can lie well after its entry date), and `sort=most recent` is not a valid ESearch sort (PubMed warned "Unknown sort schema 'most recent' ignored" and used the default). So "most recent" here means newest entry date, as elsewhere in this project, and only approximately. For every term with 20 or fewer added records the sample is all of them.

## Where the output goes

Both are under `data/cache/`, which is gitignored and reproducible.

- `data/cache/pubmed/<pmid>.xml`: the raw `<PubmedArticle>` XML for one record.
- `data/cache/runs/<timestamp>.json` (UTC, e.g. `20261031T120000Z.json`): the manifest. This is what the next pipeline step reads.

Manifest fields: `query`, `query_file`, `window` (mode, since, until; the date type is always the entry date), `retraction_query`, `refresh`, `counts` (window hits, retraction hits, requested, fetched, new, skipped as cached, missing, unparsable), `new_pmids`, `window_pmids` (every hit of the window search, cached or not; the weekly pipeline selects from these), `retracted_pmids` (every hit of the retraction query, on every run), `newly_flagged_retracted_pmids` (cached copies that turned out to be retracted), `missing_pmids` (asked for but not returned by PubMed), `unparsable_pmids` (cached, but could not be parsed; look at them) and `warnings`.

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

## Tests

`tests/test_pubmed.py` uses hand-made fictional records in `tests/fixtures/pubmed/` (PMIDs 90000001 to 90000008; the `query-diff` tests use generated copies of one of them) and `httpx.MockTransport`. No network, no real sleeping (the rate limiter takes a fake clock). A live check against the real PubMed is a manual step, recorded in the pull request.
