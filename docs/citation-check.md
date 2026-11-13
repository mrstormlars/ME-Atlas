# Citation check

`src/me_atlas/citations.py` checks the bibliographic facts on every card and draft against the records fetched from PubMed and Europe PMC. It is code, not AI: it does the mechanical part of step 3 in the review model (functional spec, section 6). Together with the card validator (every sentence has a source that is listed on the card) it makes credibility rule 1 checkable: no title, year, quote or sample size from memory. Plan: `docs/plan-citation-check.md`.

## Running it

```bash
uv run python -m me_atlas.citations check                    # cards/ and drafts/
uv run python -m me_atlas.citations check drafts/ cards/some-card.yaml [--cache-dir data/cache]
```

The check is **offline**. It reads only `data/cache/pubmed/<pmid>.xml`, `data/cache/europepmc/<pmid>.json` and `data/cache/europepmc/<pmcid>.xml`, and never makes a request. It is separate from `cards validate` because the cache is gitignored: the validator can run on GitHub, this check runs locally (and later in the weekly pipeline). It does not refresh anything; retraction status is what the cached record says, and the weekly fetch is what updates it.

Output is one line per issue, then a summary:

```
drafts\x.yaml: pmid:12345678: C3 ERROR: year 2019 differs from the PubMed record (2020)
FAILED: 2 file(s) checked, 1 error(s), 0 warning(s)
```

Every issue in every file is reported in one run. The exit code is 1 if there is at least one error and 0 otherwise (warnings alone exit 0). A file that cannot be loaded as a card (bad YAML, schema or validator error) is reported as a `LOAD ERROR` line and the other files are still checked. The change log is skipped.

## The checks

Each study on the card is checked. Errors unless marked.

| Code | What is checked | How to fix it |
|---|---|---|
| **C1** Record exists | A `pmid:` study id has a cached, readable PubMed record. | Run the command the error names: `uv run python -m me_atlas.pubmed fetch --ids <pmid>` (add `--refresh` if the cached file is unreadable). Works for papers outside the search query too. |
| **C2** Title | The title equals the record's title after normalisation. | Copy the title from the cached record (the message prints both). |
| **C3** Year | The year equals the record's year exactly. A record without a year is an error ("check by hand"). | Copy the year from the record; if the record has none, look the paper up by hand. |
| **C4** Not retracted | The cached record is not marked retracted. | The card cites a retracted paper. This is an editorial decision, not a typo: report it. |
| **C5** Quote is verbatim | `case_definition_quote` appears in the source named in `case_definition_source`: `abstract` is the PubMed abstract, `fulltext` is the cached full text: the Europe PMC open-access XML if there is one, otherwise the cached PMC article page (see below). Either way it is the front matter or abstract and the body, without the reference list. `fulltext` with no cached full text is an error. Studies without a quote (`unverified`, `none`, `other`) skip this check. | Copy the sentence from the abstract or full text. If the full text is not cached: `uv run python -m me_atlas.europepmc fulltext <pmid>`, or, when the study has no open full text but Europe PMC says it is free to read on PubMed Central (`inPMC` Y), `uv run python -m me_atlas.europepmc pmcpage --card <card.yaml> <pmid>`. If the record has no open full text, the quote cannot be checked mechanically: a person checks it and the source is changed to what can be verified. If the sentence is only in the full text, set the source to `fulltext`. |
| **C6** Sample size (**warning**) | `n_patients` and `n_controls`, when not null, appear as a whole number in the abstract or in the cached full text (open-access XML or cached PMC page). | Look at the paper. Fix the number if it is wrong; leave it if the warning is explained (below). |
| **C7** DOI-only id | A `doi:` study id is an error: "cite by PMID". | Find the PMID and use `pmid:<digits>`. DOI-only ids cannot be checked yet. |

When there is no usable record (C1), the other checks for that study are skipped. A DOI-only study gets only C7.

## Normalisation

Exactly this, nothing looser. Anything else that differs is a mismatch.

- **Title (C2).** Unicode NFKC; whitespace collapsed; case folded; one trailing period removed; and the square brackets that wrap the whole title removed (PubMed writes `[Title in English].` for translated papers), but only when there is no other square bracket inside them, so `[Foo] and [bar]` stays as it is. Brackets inside a title are kept. Both the card title and the record title are normalised the same way and then compared.
- **Quote (C5).** Unicode NFKC; whitespace collapsed; curly and low/reversed quote marks (`‘ ’ “ ”`, and U+201A, U+201B, U+201E, U+201F) read as straight; the hyphen, non-breaking hyphen, figure dash, en dash, em dash, horizontal bar and minus sign (U+2010 to U+2015, U+2212) read as the ASCII hyphen. The normalised quote must occur as a substring of the normalised source text. Case, punctuation and wording are not touched.
- **Number (C6).** A whole number: `1234` also matches `1,234` and `1 234` (a space, no-break space or thin space). It must not be part of a longer number, so 48 is not found in `148`, `1,048`, `.48`, `0.48`, `3.48` or `48.5`.

## Why sample size is only a warning

A number on a card can be right and still not appear as digits: the paper may write it as a word ("forty-eight"), the card may give the sum of two cohorts, or the number may belong to one measurement in a larger study (the card format records the number in the measurement that bears on the finding). A hard error would send people to "fix" correct numbers. A warning makes a person look, and the check stays quiet when the number is found. A warning never changes the exit code. If the full text is not cached, the check can only see the abstract and the message says so.

## Not checked

Author names in `group`; the `finding` text against the source; sources named only in YAML comments; corrections and errata; cohort overlap; whether a retraction happened after the last fetch.

## Placeholder full text, and the PMC id from PubMed

A cached `<pmcid>.xml` is full text only if it has a real body. Europe PMC sometimes serves a placeholder for a preprint: a body of under 1,000 characters that says the full text is available as a PDF, or an article with no body text. The check never reads such a file as full text. C5 with `fulltext` then reports that there is no cached full text (the message says the file is a PDF placeholder), and C6 looks at the abstract only. The same test (`europepmc.is_placeholder_fulltext`) is used when the full text is fetched, so a placeholder is not written to the cache. No PDF is downloaded or read. `europepmc fulltext` and `casedef` print the status with the PMC id: `PMC record, full text is a PDF only (not read)` or `PMC record, no full-text XML in Europe PMC`. They read the PMC id from the cached PubMed record when Europe PMC has none. `casedef` and `pmcpage` mark sentences that may exclude people with the illness with `[exclusion]`.

The PMC id used to find `<pmcid>.xml` and `<pmcid>.html` is the one in the cached Europe PMC lookup. When the lookup has none (Europe PMC can lack the id for a while after PubMed has it), the check uses the `pmcid` of the cached PubMed record. This is still offline.

## The TODO rule is not a citation check

"TODO" in text a reader sees (the card name, any sourced text, a study's `finding`) is the card validator's rule V14 (`docs/card-format.md`), not a citation check. Run `uv run python -m me_atlas.cards validate`. This check does not look for it.

## Tests

`tests/test_citations.py` builds a fictional cache (PMIDs 9000000x, titles starting "Fictional", fictional PMCIDs) and fictional cards in a temporary directory. A test makes any HTTP client construction or request fail, to show the check stays offline.

## Free-to-read PMC pages as full text

Some cited studies are free to read on PubMed Central but are not in its open-access subset, so Europe PMC has no full-text XML for them. For such a study (the cached Europe PMC lookup has a PMCID and `inPMC` "Y"; founder ruling 2026-11-08) `uv run python -m me_atlas.europepmc pmcpage --card <card.yaml> <pmid>...` fetches the article page `https://pmc.ncbi.nlm.nih.gov/articles/<PMCID>/` once and caches it as `data/cache/europepmc/<PMCID>.html`. The limits:

- On demand, one PMID per request, only for `pmid:` studies on the card or draft named on the command line; never in bulk and never from a publisher site. PMC asks that its site is not crawled; reading one cited article, cached once, is not crawling.
- The page is cached only if its `citation_pmid` equals the PMID asked for and it has a main article body. Otherwise nothing is written.
- Only the abstract and main article body are read (no reference list, navigation, header, footer or scripts). The page is used to find and check the case-definition sentence (C5) and sample sizes (C6). A card quotes at most that one sentence.
- On the card it is `case_definition_source: fulltext`. The check prefers the open-access XML when both are cached, and stays offline.
