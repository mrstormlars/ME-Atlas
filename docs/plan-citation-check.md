# Plan: mechanical citation check

November 1, 2026 · For `/orchestrator`

## Why

Credibility rule 1 says every bibliographic fact on a card comes from a fetched record, never from memory. So far that has been checked only by hand, by the drafting agents and `card-reviewer`. Spec section 6, step 3 asks for a check in code, not AI: every cited id exists in a fetched record, and title, year, sample size and case definition match it. Together with the existing validator (V3/V4: every sentence has a source that is listed on the card), this check completes step 3. No change may be published automatically (tier 1) until it exists, and it should run before the site generator shows cards to anyone.

## Design decisions (from brainstorm, 2026-11-01, accepted by the founder)

1. **Separate command, offline.** `uv run python -m me_atlas.citations check [paths]`, default `cards/` and `drafts/`. It reads only the cache (`data/cache/pubmed/`, `data/cache/europepmc/`) and never makes a network request. It is separate from `cards validate` because the cache is gitignored, so the citation check cannot run on GitHub as the validator can; it runs locally and later in the weekly pipeline.
2. **Checks per study** (errors unless marked):
   - **C1 Record exists.** A `pmid:` id has a cached PubMed record. If missing: error naming the command that fetches it (`pubmed fetch --ids <pmid>`).
   - **C2 Title matches** the record after normalisation: Unicode NFKC, whitespace collapsed, case folded, one trailing period removed, and the square brackets PubMed puts around translated titles removed. Nothing else is tolerated.
   - **C3 Year matches** the record exactly. A record without a year is an error ("record has no year; check by hand").
   - **C4 Not retracted** (`retracted: true` in the record is an error).
   - **C5 Case-definition quote is verbatim** in the stated source: `abstract` → the PubMed abstract; `fulltext` → the cached Europe PMC full text (all article text, front matter and body). Matching normalises whitespace, NFKC, curly/straight quotes and the hyphen/en dash/em dash/minus sign family; nothing else. `fulltext` with no cached full text is an error naming `europepmc fulltext <pmid>`. Studies without a quote (`unverified`, `none`, `other`) skip C5.
   - **C6 Sample size appears (warning only).** Each non-null `n_patients` and `n_controls` appears as a whole number (word boundaries; `1,234` and `1 234` also match `1234`) in the abstract or the cached full text. Not found → warning, not error: a number may be written as a word, be a sum of cohorts or belong to one measurement only, so a human looks.
   - **C7 DOI-only ids are an error** for now ("cite by PMID; DOI-only ids cannot be checked yet"). Every current study has a PMID.
3. **Output** like the validator: one line per issue with file, study id (and field), level (`ERROR`/`WARNING`) and message; a summary line with counts. Exit 1 if any error, 0 otherwise (warnings alone exit 0). All issues in all files are reported in one run.
4. **Fetch by id.** `pubmed fetch` gains `--ids <pmid>...`, mutually exclusive with `--since` / `--weekly` / `--backfill`: it fetches exactly those PMIDs by EFetch (respecting the cache and `--refresh`), so a card can cite a paper outside the search query (for example a long COVID paper that does not mention ME/CFS). It writes a run manifest with the mode and ids. It does not run the search or the retraction query.
5. **Reuse, don't duplicate.** Use `parse_xml` from `pubmed.py` and the cache paths and lookup parsing from `europepmc.py`. A small helper that returns the plain text of a cached full-text XML may be added to `europepmc.py`.

## Steps

1. `pubmed fetch --ids` with tests (mocked HTTP): fetches only the given ids, skips cached ones, re-fetches with `--refresh`, writes a manifest; combining `--ids` with `--since` is a usage error.
2. `src/me_atlas/citations.py`: normalisation helpers, checks C1–C7, report, CLI.
3. Tests `tests/test_citations.py` with fictional fixtures: a fictional card or draft plus a fictional cache directory built in `tmp_path` (fictional PMIDs such as 90000001, titles starting "Fictional", fictional PMCIDs). No network, no LLM.
4. Live check (manual, not in pytest): run `citations check` on both drafts. Record errors and warnings per study in the PR description.
5. If the live check finds errors in the drafts: fix only the mechanical field (title, year or quote) from the cached record, in the same PR, each fix listed in the PR description. Do not change level, role, direction, badges, contested, finding or any sourced text; if an error cannot be fixed that way, stop and report it.
6. Short `docs/citation-check.md` (what each check does, the normalisation, how to fix each error, why sample size is only a warning). Mention `--ids` in `docs/fetch.md`. DECISIONS entry (offline separate command, C1–C7, sample size as warning, DOI-only as error, `--ids`). STATUS: citation check done; next is the site generator.

## Done when

- [ ] `uv run pytest` passes, `uv run ruff check .` and `uv run ruff format --check .` clean; no test touches the network.
- [ ] Each of C1–C5 and C7 has a test whose input fails it, and the report names that check, the file and the study id.
- [ ] C2 tests: a title differing only by case, whitespace, trailing period or translation brackets passes; a title differing by one word fails.
- [ ] C5 tests: a quote differing only by whitespace, quote style or dash style passes; a quote with one changed word fails; a quote present in the full text but not the abstract fails when the source is `abstract`; `fulltext` with no cached full text fails with a message naming the fetch command.
- [ ] C6 tests: a number present as digits (including `1,234`) gives no warning; a missing number gives a warning and exit code 0.
- [ ] The CLI exits 0 on a fictional card that passes, 1 on one with an error, and reports every issue in one run.
- [ ] `fetch --ids` tests from step 1 pass.
- [ ] Running the check makes no HTTP request (tested with a transport that fails on any request, or by not constructing a client at all).
- [ ] The live check ran on both drafts; its result is in the PR description; both drafts end with no errors, and `git diff drafts/` shows only fixes to title, year or quote, each listed in the PR description.
- [ ] No new dependencies; `data/cache/` stays gitignored; nothing added to `cards/`.

## Out of scope

- Sources named only in YAML comments (for example the correction pmid:42227214).
- A corrections and errata field, cohort overlap, per-measurement sample size (format backlog in STATUS).
- Checking author names in `group`, or the `finding` text against the source.
- Refreshing retraction status (the weekly fetch does that; this check reads what is cached).
- Running in GitHub Actions, scheduling, AI classification, the site generator.
