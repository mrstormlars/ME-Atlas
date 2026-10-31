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
```

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

## Where the output goes

Both are under `data/cache/`, which is gitignored and reproducible.

- `data/cache/pubmed/<pmid>.xml`: the raw `<PubmedArticle>` XML for one record.
- `data/cache/runs/<timestamp>.json` (UTC, e.g. `20261031T120000Z.json`): the manifest. This is what the next pipeline step reads.

Manifest fields: `query`, `query_file`, `window` (mode, since, until; the date type is always the entry date), `retraction_query`, `refresh`, `counts` (window hits, retraction hits, requested, fetched, new, skipped as cached, missing, unparsable), `new_pmids`, `retracted_pmids` (every hit of the retraction query, on every run), `newly_flagged_retracted_pmids` (cached copies that turned out to be retracted), `missing_pmids` (asked for but not returned by PubMed), `unparsable_pmids` (cached, but could not be parsed; look at them) and `warnings`.

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

`tests/test_pubmed.py` uses hand-made fictional records in `tests/fixtures/pubmed/` (PMIDs 90000001 to 90000008) and `httpx.MockTransport`. No network, no real sleeping (the rate limiter takes a fake clock). A live check against the real PubMed is a manual step, recorded in the pull request.
