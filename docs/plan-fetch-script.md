# Plan: PubMed fetch script

October 31, 2026 · For `/orchestrator`

## Goal

A command that fetches ME/CFS papers from PubMed, caches the raw responses in `data/cache/`, and parses them into records that later steps (hand-written cards, the mechanical citation check, AI classification) can rely on. Every bibliographic fact on a card must be traceable to one of these cached records.

## Design decisions (from brainstorm, 2026-10-31)

1. **PubMed only in this task.** PubMed is the canonical source for PMIDs, titles, publication types and retraction flags. Europe PMC adds preprints (excluded by the inclusion rule) and full-text links (not needed yet). It is added later if a concrete need appears.
2. **Search query lives in a config file**, `config/pubmed_query.txt`, not in code, so it can be reviewed and changed in a PR. Starting query: ME/CFS by MeSH heading plus title/abstract terms (myalgic encephalomyelitis, chronic fatigue syndrome, ME/CFS, systemic exertion intolerance disease), **plus long COVID papers only when they also mention ME/CFS terms**. Long COVID alone is far larger than ME/CFS and out of v1 scope; the AND clause catches the overlap studies the long COVID label needs. The MeSH headings must be checked against the live MeSH database on the first live run (step 6), not taken on trust.
3. **Fetch everything once, then weekly.** A backfill of the full ME/CFS literature is cheap (fetching costs requests, not money; classification cost comes later and is controlled there). Weekly runs fetch by entry date for the last 14 days and de-duplicate by PMID, so a missed week is caught.
4. **Retractions every run.** Each run also queries retracted publications within the same search and flags them, so a card citing a later-retracted study can be caught (spec section 3: a retracted study is removed and the level re-assessed).
5. **No filtering at fetch time.** Reviews, editorials and letters are fetched and their publication types recorded. Deciding what counts as evidence belongs to classification, not fetching.
6. **Storage:** raw XML per PMID at `data/cache/pubmed/<pmid>.xml` (gitignored, reproducible), and one run manifest per run at `data/cache/runs/<timestamp>.json` (query, date window, counts, new PMIDs, retracted PMIDs). The manifest is what the next pipeline step reads.
7. **Polite client.** `httpx`, NCBI `tool` and `email` parameters from `CONTACT_EMAIL`, optional `NCBI_API_KEY`; at most 3 requests/s without a key and 10 with; ids fetched in batches; retry with backoff on 429 and 5xx; a cached PMID is not re-fetched unless asked.

## Parsed record (fields)

`pmid`, `doi` (or null), `title`, `abstract` (or null), `journal`, `year`, `authors` (list of display names, as given by PubMed), `publication_types`, `mesh_terms`, `retracted` (bool, from publication type), `entry_date`. The record's id is formatted as `pmid:<digits>` to match `StudyId` in `src/me_atlas/cards.py`.

## Steps

1. HTTP client module `src/me_atlas/pubmed.py`: search (ESearch with history server) and fetch (EFetch XML) with rate limiting, retries, contact parameters and API key from the environment. The rate limiter is testable without sleeping (injectable clock).
2. Parser: PubMed XML → record dataclass or pydantic model. Handle missing abstract, missing DOI, structured abstracts (labelled sections joined), year from `MedlineDate` when `Year` is absent, and the retraction publication type.
3. Cache: write raw XML per PMID; read from cache when present; `--refresh` forces re-fetch.
4. Run command: `uv run python -m me_atlas.pubmed fetch --since YYYY-MM-DD [--until YYYY-MM-DD] [--refresh]`, plus `--weekly` (last 14 days) and `--backfill` (no lower date). Each run also runs the retraction query and writes a manifest.
5. Tests in `tests/test_pubmed.py` with **hand-made fictional fixtures** in `tests/fixtures/pubmed/` that follow the PubMed XML structure (fictional PMIDs such as 90000001, titles starting with "Fictional"). The HTTP layer is mocked (`httpx.MockTransport`). No network.
6. **Live check (manual, not in pytest):** the orchestrator runs one small live query (`--since` the last 30 days) with the founder's `.env`, reports the hit count, and checks that the MeSH headings in the query exist (non-zero hits for each heading alone). The result and the date are recorded in the PR description. If `.env` lacks `CONTACT_EMAIL`, stop and ask the founder.
7. Short `docs/fetch.md`: what the command does, the query and why, where the output goes. DECISIONS entry (PubMed only, query in config, long COVID AND clause, full backfill, retraction check). STATUS: fetch done; next is hand-writing 2–3 cards from fetched records.

## Done when

- [ ] `uv run pytest` passes and `uv run ruff check .` reports nothing; tests make no network calls.
- [ ] The parser test covers: a normal record; no abstract; no DOI; a structured abstract; a `MedlineDate` year; a retracted record (`retracted: true`). A record with none of the retraction markers parses as `retracted: false`.
- [ ] A rate-limit test shows that without an API key no more than 3 requests start within any one second, and with a key no more than 10.
- [ ] A retry test shows a 429 then 200 succeeds, and repeated 500s fail with a clear error after the retry limit.
- [ ] A cache test shows a cached PMID is not re-requested, and is re-requested with `--refresh`.
- [ ] Every request carries `tool` and `email`; a run without `CONTACT_EMAIL` set exits non-zero with a message naming the variable.
- [ ] A run writes a manifest with query, window, counts, new PMIDs and retracted PMIDs (tested with mocks).
- [ ] The query is read from `config/pubmed_query.txt`; changing that file changes the request (tested).
- [ ] The live check (step 6) was run once and its hit counts are in the PR description.
- [ ] `data/cache/` stays gitignored; `cards/` and `drafts/` gain no files; no new dependencies.

## Out of scope

- Europe PMC, preprints and full text.
- AI classification, extraction or drafting.
- Scheduling the weekly run (cron or GitHub Actions).
- The mechanical citation check against cards (next task, uses these records).
- Writing real cards.
- Fetching long COVID literature beyond papers that also mention ME/CFS.
