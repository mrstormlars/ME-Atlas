# Plan: open PDF copies through Unpaywall (full text, option B)

November 27, 2026 · For `/orchestrator`

## Why

Full text today comes only from Europe PMC open-access XML and from free-to-read PMC pages (`docs/citation-check.md`). Of the 110 studies that carry a level, badge, contested mark or link on the 20 cards, 38 have their case definition from the abstract only, and 93 context studies are unverified. Many of these papers have a legal open copy elsewhere: on the publisher's site (gold, hybrid, bronze) or in an institutional repository (green), usually as a PDF. Unpaywall indexes those copies by DOI.

**Founder ruling (2026-11-27):** PDF reading is allowed when it gives access to more sources. It replaces the rule "No PDF is ever downloaded or parsed" (`docs/pipeline.md`, full-text note; `docs/plan-fulltext-and-format-v2.md`, out of scope). Where a fact read from a PDF is critical for a level, badge, contested mark or case definition, the founder checks that exact fact in the source by hand. That check is a narrow, explicit step (below), not a general review.

## What Unpaywall says (read 2026-11-27 from its own pages)

From `unpaywall.org/products/api`, `unpaywall.org/data-format` and `unpaywall.org/legal/terms-of-service` (last revised 5 November 2020):

- **Endpoint.** `GET https://api.unpaywall.org/v2/<doi>?email=<address>`. The email parameter is how a request is authenticated; it is required. Version 2 is the only version supported. The search endpoint was retired on 18 September 2026 (410 Gone); it is not used.
- **Limit.** "Please limit use to 100,000 calls per day." No per-second limit is stated. This project sends at most one request a second (our own choice, far below the stated limit) and only for studies cited on a card or draft.
- **Terms.** The free API is licensed for use; automated use is allowed where the terms permit it, and the REST API is the product offered for programmatic access. Unpaywall's data must not be republished without consent, so the cached responses stay in the gitignored cache and are never redistributed. Unpaywall "makes no representations regarding the ownership, license rights, reliability, accuracy, or completeness" of the publications it points to, and third parties may restrict how their copies are used: so a PDF is cached locally only, never redistributed, and a card quotes at most the one sentence that states the case definition (as with the XML today).
- **DOI object** (used fields): `doi` (always lowercase), `is_oa`, `oa_status` (gold, hybrid, bronze, green, closed), `best_oa_location`, `oa_locations`, `oa_locations_embargoed` (beta; locations not yet available), `title`, `year`, `updated`.
- **OA location** (used fields): `url_for_pdf` (null when no PDF is known), `url_for_landing_page`, `url` (the PDF if there is one, otherwise the landing page), `host_type` (`publisher` or `repository`; preprint servers count as repositories), `version` (`submittedVersion`: not yet peer reviewed; `acceptedVersion`: peer reviewed, without publisher formatting; `publishedVersion`: the version of record), `license` (null when unknown or not an OA licence), `is_best`. `evidence` and the location's `updated` are deprecated and not read.
- **Unknown DOI.** The documentation does not state what the API returns; the implementation treats HTTP 404 as "not in Unpaywall" and the live check records what actually comes back.

The email is `CONTACT_EMAIL` from `.env`. It is sent to Unpaywall only, as the parameter its documentation requires, and never written to the cache, a report, a log line or git. Without it, cached data is read and no request is made.

## Design

### 1. Which copies are accepted

For a `pmid:` study on a card or draft, the DOI is taken from the cached PubMed record (not from the card, not from model knowledge). No DOI there: status `no_doi`, nothing requested.

From the Unpaywall answer, the locations in `oa_locations` are tried, and only those where all hold:

- `url_for_pdf` is not null (a landing page is not followed or scraped);
- `version` is `publishedVersion` or `acceptedVersion`. A `submittedVersion` is not peer reviewed and its wording can differ from the published paper, so it is never used for a published study;
- the PDF host is not PubMed Central or Europe PMC (`ncbi.nlm.nih.gov` and its subdomains, `europepmc.org`, `ebi.ac.uk`): PMC answers automated requests with a bot check, and Europe PMC's own text is already read as XML.

`oa_locations_embargoed` is never read. Order: `publishedVersion` before `acceptedVersion`; within a version, `publisher` before `repository`; then `is_best` first; then the order Unpaywall gives. The first location that yields a usable PDF is used; every attempt and its outcome is recorded.

The version, `host_type`, `license`, the PDF URL and the landing page URL of the copy used are stored with the PDF and carried into every place the quote is shown, so it is always known whether a quote came from the version of record or from an accepted manuscript.

### 2. Downloading

- The generic client of `docs/fetch.md` ("Resource fetch"): User-Agent `me-atlas-research-client`, no name, address or `.env` value, no cookies, no other headers tried; `robots.txt` read for that User-Agent before any request to a host, and every redirect hop checked against its own host's robots file; at most one request a second per host. The existing fetcher in `me_atlas.resources` is reused, not copied.
- A response is a PDF only when it is HTTP 200 and its body starts with `%PDF-`. Anything else (an HTML page, a bot check, a login, a cookie wall, HTTP 401/403/429) is reported with the same statuses as a resource page (`blocked`, `not_pdf`, `http_<code>`, `robots_disallowed`, `robots_unavailable`, `network_error`), nothing is cached, and the next location is tried. A bot check, a login or a paywall is never worked around: no retry with other headers, no browser, no cookies.
- A body over 30 MB is not kept (`too_large`).
- **Identity check.** The PDF is the paper only if the paper's title from the cached PubMed record is found in the text of its first two pages (both reduced to lowercase letters and digits, so line breaks, hyphenation and ligatures do not matter). Otherwise `title_not_found`: nothing cached, next location. This guards against a repository that serves the wrong file.
- **Cache** (gitignored, never redistributed): `data/cache/unpaywall/<key>.json` (the raw Unpaywall answer), and for a usable PDF `data/cache/unpaywall/pdf/<key>.pdf`, `<key>.txt` (the extracted text, one form feed between pages) and `<key>.meta.json` (DOI, PMID, PDF URL, final URL, landing page URL, `host_type`, `version`, `license`, fetch date, SHA-256 of the PDF, extractor name and version). `<key>` is the lowercase DOI with every character outside `[a-z0-9._-]` percent-encoded. A cached answer with no usable copy is asked again after 7 days (as `LOOKUP_MAX_AGE_DAYS`); a cached PDF is not requested again unless `--refresh` is given.

### 3. Text extraction

**Library: `pdfminer.six`** (MIT licence, pure Python, no compiled parts). Its layout analysis groups text into boxes and orders two-column pages column by column, which is what a sentence search needs. `pypdf` (BSD) is lighter but orders multi-column text less reliably; `PyMuPDF` is AGPL, which does not fit an MIT project. The new dependency is justified in the commit message.

Extraction: `pdfminer.high_level.extract_text` per page with default layout parameters. Then, in this order: Unicode NFKC (resolves the ligatures ﬁ, ﬂ, ﬀ and full-width forms); soft hyphens (U+00AD) removed; a hyphen at the end of a line, between two letters, is marked as a *line-break hyphen*; line breaks become spaces; whitespace is collapsed. Running headers, footers and page numbers stay in the text: a sentence broken by them, or by a column or page break, simply does not match, which is the safe outcome.

The reference list is cut off: the text ends at the last line that is only "References", "Bibliography" or "Literature cited" (any case), when that line is in the second half of the document. If there is no such line, the whole text is kept and the record says so.

### 4. Matching a quote word for word

A quote from a PDF passes only if it is found in the extracted text under the existing narrow normalisation (`citations.normalise_quote`: NFKC, whitespace collapsed, curly quotes and dashes read as straight, nothing else), with one addition for the PDF: each line-break hyphen may be read either as nothing ("Fu-|kuda" → "Fukuda") or as a hyphen ("follow-|up" → "follow-up"). Concretely the check builds two texts, one with every line-break hyphen removed and one with every line-break hyphen kept, and the quote must be in one of them. A quote that matches in neither is not usable: it cannot be put on a card with source `fulltext_pdf`. No fuzzy matching, no word skipping, no OCR. A scanned PDF with no text layer gives no text (`no_text`) and is not used.

The candidate sentences shown to an agent or the founder are taken from the first text (line-break hyphens removed) and split with the existing `split_sentences`, so a copied sentence always matches.

### 5. Where it plugs in

- **New module `src/me_atlas/unpaywall.py`** with the client, the location choice, the download, the extraction, the matcher and a command line:
  - `uv run python -m me_atlas.unpaywall fetch --card <card or draft> [PMID...] [--refresh]`: for every `pmid:` study on the card (or the PMIDs given, which must be on it), look up the DOI, choose and fetch a copy, print one line per study with the outcome, the version and the host type;
  - `uv run python -m me_atlas.unpaywall casedef --card <card or draft> [PMID...]`: as `fetch`, then print the sentences that may name a case definition or exclude people with the illness, found with the same finder as `europepmc casedef` (whole text, scope `body`, `[exclusion]` marks), each with its page number;
  - `pending` and `confirm`, the founder's step (section 6).
  Like `pmcpage`, it only ever acts on studies cited on the card or draft it is given. It is a separate command, not a fallback inside `europepmc casedef`, so that `europepmc.py` is not changed (a parallel session works there) and so that every PDF request is asked for explicitly.
- **Card format.** `case_definition_source` gains the value `fulltext_pdf`: the quote is from the open PDF copy found through Unpaywall. It follows the same rules as `fulltext` in the validator (V13). `fulltext` keeps its meaning (Europe PMC XML or the cached PMC page). The version is not a card field: it is in the cached meta and, for a confirmed quote, in the confirmation record in git.
- **Citation check.** C5 with source `fulltext_pdf` reads the cached `<key>.txt` of the study's DOI and matches as in section 4; no cached PDF text is an error with the hint `uv run python -m me_atlas.unpaywall fetch --card <card> <pmid>`. C6 and the free-text number check do not read PDF text in this change (they stay as they are). New check **C13** (error): a study with source `fulltext_pdf` must have a matching founder confirmation (section 6).
- **Pipeline `context`.** When Europe PMC gives no usable full text (status `pdf_only`, `pmc_no_xml`, `not_open_access` or `not_found`) and the paper's PubMed record has a DOI, the loader tries Unpaywall as in sections 1 to 3 (requests only with `CONTACT_EMAIL`; without it only the cache is read). With a usable PDF, section 5 of the context file holds the PDF text (same budget and `TRUNCATED` note) with a source line naming Unpaywall, the version, the host type and the PDF URL, and section 6 lists the candidate sentences. The context tells the drafter that a quote from this text takes `case_definition_source: fulltext_pdf` and passes the checks only after the founder has confirmed it. The audit context and `record-audit` are not changed in this step: a carrier whose only full text is a PDF is still given to the auditor as abstract only with the "FULL TEXT NOT CACHED" note, so the auditor stays conservative (follow-up below).
- **Agent prompt.** `.claude/agents/card-drafter.md`: the allowed values of `case_definition_source` gain `fulltext_pdf`, with when to use it.

### 6. The founder's check

Every `fulltext_pdf` quote states a case definition, so every one of them is critical and every one needs the founder's confirmation. No other PDF fact is put on a card as a quote in this change.

- `uv run python -m me_atlas.unpaywall pending [--card PATH]...` (default: every file in `cards/` and `drafts/`) prints a short list: per unconfirmed `fulltext_pdf` quote, the card, the study id, the quote, the page number where code found it, the PDF URL, the landing page URL, the version and the host type. It prints nothing else and exits 0 when the list is empty, 1 otherwise.
- The founder opens the PDF URL, finds the sentence on that page, and checks that it says what the card says. Then the founder runs `uv run python -m me_atlas.unpaywall confirm --card <PATH> <pmid>`. The command refuses unless the quote matches the cached text (section 4). It appends one entry to **`confirmations/pdf-quotes.yaml`** (in git): `study`, `field: case_definition_quote`, `quote`, `pdf_sha256`, `pdf_url`, `landing_page_url`, `version`, `host_type`, `page`, `confirmed_by: founder`, `confirmed_on` (today). An entry is never edited or removed by code.
- **Only the founder runs `confirm`.** No agent and no pipeline step runs it; `docs/pipeline.md` and the orchestrator's instructions say so. Code cannot prove who typed the command; the commit that adds the entry is the founder's, and the record is reviewed in the pull request like everything else.
- C13 passes for a study when an entry has the same study id and the same quote (after `normalise_quote`), and, when the PDF is cached, the same `pdf_sha256`. A changed quote or a different PDF is unconfirmed again.

## Steps

1. Add `pdfminer.six` with `uv add`; record its licence from the installed package metadata.
2. `src/me_atlas/unpaywall.py`: key, cache, client (rate limit 1/s, retries through `http.get_with_retries`), location choice, PDF download through the resources fetcher, identity check, extraction and reference cut, matcher, sentence candidates with page numbers, CLI `fetch`, `casedef`, `pending`, `confirm`.
3. `cards.py`: `fulltext_pdf` in `case_definition_source`, V13 as for `fulltext`.
4. `citations.py`: C5 for `fulltext_pdf`, C13; `docs/citation-check.md` updated.
5. `pipeline.py`: the `context` loader and section 5/6 for PDF text; `docs/pipeline.md` updated (the old "No PDF is ever downloaded or parsed" sentence replaced by the founder ruling and this path).
6. `docs/fetch.md`: a new section "Open PDF copies (Unpaywall)" (setup, terms, statuses, cache). `.claude/agents/card-drafter.md`. `confirmations/pdf-quotes.yaml` created empty (`[]`) with a header comment. `CLAUDE.md` layout gains the `confirmations/` line. DECISIONS entry for the ruling of 2026-11-27 and this design.
7. Tests (offline): recorded and fictional Unpaywall answers and small PDFs generated for the tests in `tests/fixtures/unpaywall/`.
8. Live check by the orchestrator on a handful of real card PMIDs whose case definition is from the abstract or unverified; numbers in the pull request.

## Out of scope

- Any change to a card, draft or translation (the live check only reads and caches).
- Sci-Hub or any source that is not legal open access; landing-page scraping; asking authors for copies.
- `submittedVersion` copies; OCR of scanned PDFs.
- PDF text in C6, the number check, the audit context and `record-audit` (follow-up: the auditor would then see the PDF text of carriers, with the same matcher in `record-audit`).
- Changes to `europepmc.py` (the parallel option A session works there).

## Open questions for the founder

- None blocking. The choice to exclude `submittedVersion` and to require a confirmation for every `fulltext_pdf` quote are the conservative defaults; the founder can loosen either later.
