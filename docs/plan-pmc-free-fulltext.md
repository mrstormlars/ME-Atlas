# Plan: free-to-read PMC article pages as a full-text source

Founder ruling 2026-11-08 ("Ja, lag en regel"), after the circadian card: a study whose article is free to read on PubMed Central but is not in the open-access subset could not be checked, although anyone can read it. Example: Rahman 2011 (pmid:21532961, PMC3079947). Europe PMC's `fullTextXML` returns HTTP 500 for it, NCBI EFetch returns only the front matter, and Unpaywall lists only the PMC page.

## The rule (recorded in DECISIONS.md)

- When Europe PMC has no open-access full text for a PMID that a card or draft cites, and the cached Europe PMC lookup gives a PMCID with `inPMC` "Y", the article page `https://pmc.ncbi.nlm.nih.gov/articles/<PMCID>/` may be fetched: on demand, one PMID per call, only for PMIDs on the card or draft named on the command line, never in bulk, never from a publisher site.
- The page is stored in the gitignored cache like other full text. It is used only to find and check the case-definition sentence (C5) and sample sizes (C6). A card quotes at most that one sentence, as with open-access text.
- On the card it counts as `case_definition_source: fulltext` (a cached full text that the citation check reads). No format change.
- Why: PMC asks that its website not be crawled or bulk-downloaded; one cited article at a time, cached once, is reading, not crawling. The credibility rule still holds, because the sentence is checked mechanically against a cached copy.

## Contract (what "done" means)

1. `uv run python -m me_atlas.europepmc pmcpage --card <card.yaml> <pmid>...` exists. Every PMID given must be a `pmid:` study on that card, or the command stops before any request with an error naming it. It uses the cached Europe PMC lookup (fetching it first if missing, like `fulltext`).
2. For each PMID: if the lookup is open access, it says to use `fulltext` and fetches nothing. If there is no PMCID or `inPMC` is not "Y", it says so and fetches nothing. Otherwise it fetches the PMC article page once (cached: no request if `<cache>/europepmc/<PMCID>.html` exists, unless `--refresh`), with the same User-Agent (contact email), rate limiter and retries as the Europe PMC client.
3. A fetched page is only written to the cache if it parses: it has a `citation_pmid` meta tag equal to the PMID asked for, and a `<section class="... main-article-body ...">` with text. Otherwise the error says why and nothing is written.
4. `article_text` has a counterpart for the cached page: the plain text of the abstract and the main article body, without the reference list, navigation, header, footer or scripts, with whitespace collapsed. The case-definition finder (`casedef`) and `pmcpage` print candidate sentences from the page's methods sections the same way as for XML (sections whose heading matches the existing methods test).
5. `citations check`: for `case_definition_source: fulltext` (C5) and for C6, the cached full text is the open-access XML when it exists, otherwise the cached PMC page. Messages that say "no cached full text" name `pmcpage` as a way to get it when the lookup has a PMCID with `inPMC` "Y". The check stays offline.
6. Tests (offline, fictional fixtures only, `httpx.MockTransport`, fake clock): the card guard; open-access and not-in-PMC records fetch nothing; a good page is cached and its text excludes the reference list; a page with the wrong `citation_pmid` or no article body is not cached; the cache is used on a second call; C5 passes on a quote that is in a cached page body and fails on one that is only in its reference list; C6 finds a number in the page.
7. Docs: `docs/fetch.md` or the module docstring, `docs/citation-check.md` and `docs/card-format.md` (the `fulltext` source) say what the page source is and its limits. `uv run pytest -q` and `uv run ruff check .` pass; `ruff format` applied to changed files.

Out of scope: any card change, Unpaywall integration, other repositories, PDFs.

## Notes for the implementer

- Module: `src/me_atlas/europepmc.py` (client, cache, parsing, CLI) and `src/me_atlas/citations.py` (`CacheReader._read_fulltext`). Standard library `html.parser` for parsing; no new dependency.
- The lookup JSON already carries `inPMC` (see a cached `data/cache/europepmc/<pmid>.json`). `parse_lookup` and `Lookup` need it, or a status such as `free_in_pmc`; keep the existing statuses' meaning.
- Real page structure (observed 2026-11-08 on PMC3079947): `<meta name="citation_pmid" content="...">`; `<section class="abstract" id="abstract1">`; `<section class="body main-article-body">` holding `<section id="secN">` with `<h2>`/`<h3>` headings and `<p>` paragraphs; tables in `<section class="tw xbox ...">`; references in `<section id="ref-list1" class="ref-list">` (inside or after the body: exclude it either way). Footnote citations appear as superscript links inside the text, e.g. "criteria for CFS<sup><a ...>1</a></sup>", which flattens to "CFS1" in plain text, the same as the Europe PMC XML path does. Fixtures must be fictional (ids 9000000x, titles starting "Fictional").
