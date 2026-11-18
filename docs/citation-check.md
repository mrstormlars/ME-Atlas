# Citation check

`src/me_atlas/citations.py` checks the bibliographic facts on every card and draft against the records fetched from PubMed and Europe PMC. It is code, not AI: it does the mechanical part of step 3 in the review model (functional spec, section 6). Together with the card validator (every sentence has a source that is listed on the card) it makes credibility rule 1 checkable: no title, year, quote or sample size from memory. Plan: `docs/plan-citation-check.md`.

## Running it

```bash
uv run python -m me_atlas.citations check                    # cards/ and drafts/
uv run python -m me_atlas.citations check drafts/ cards/some-card.yaml [--cache-dir data/cache]
```

The check is **offline**. It reads only `data/cache/pubmed/<pmid>.xml`, `data/cache/europepmc/<pmid>.json` and `data/cache/europepmc/<pmcid>.xml` (and, for preprints, `data/cache/europepmc/preprints/PPR<digits>.json`), and never makes a request. It is separate from `cards validate` because the cache is gitignored: the validator can run on GitHub, this check runs locally (and later in the weekly pipeline). It does not refresh anything; retraction status is what the cached record says, and the weekly fetch is what updates it.

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
| **C7** DOI-only id | A `doi:` study id without `preprint: true` is an error: "cite by PMID". | Find the PMID and use `pmid:<digits>`. DOI-only ids cannot be checked yet, except preprints (below). |
| **C8** Preprint flag | A `pmid:` study whose cached PubMed record has the publication type "Preprint" must have `preprint: true`; a study with `preprint: true` must have a record with that type. | Set or remove `preprint: true`. |
| **C9** Group supported (**warning**) | A study with a non-null `group` and a usable record (the PubMed record, or the cached Europe PMC preprint record of a `preprint: true` study) must name at least one author of that record in `group`. See "Group matching (C9)" below. A record with no authors gives no issue. | Take the names in `group` from the author list of the record (the `- authors:` line of the context file), or leave `group` out. |
| **C10** Numbers in free text (**warning** on `cards/` and `drafts/` as they stand, **error** on newly applied text) | Every numeral in a free-text item occurs in a source that item cites, or equals the `year`, `n_patients` or `n_controls` of one. See "Numbers in free text" below. | Use the number the cited record gives, cite the record that has it, or remove the claim. A sum or difference needs its derivation: `78 (= 40 + 38)`. |
| **C11** Author statements (**warning** on `cards/` and `drafts/` as they stand, **error** on newly applied text) | A statement about authors does not contradict the cached author lists. Four cases: (a) a free-text item that states a count of shared authors, citing two or more studies with a cached author list, where the count is outside [exact, loose] for every pair of them; (b) a free-text item that says studies share no authors or are independent groups, where every pair of the studies it cites shares an author by exact name; (c) a `group` that says `first author <Name>` or `last author <Name>` where the record's first (last) author is not that name; (d) a `group` that says `<Name> also on <pmid>` where that record has a cached author list that lacks the name. See "Author statements (C11)" below. | Use the author facts in the context (computed from the records), or remove the statement. |
| **C12** Erratum on the card (**warning**) | A `pmid:` study whose cached PubMed record lists an erratum (`ErratumIn` link) must have a study on the same card with the erratum's id, with or without `corrects`. A study that is not cached, or a record with no erratum link, gives no issue. | Add the erratum as a study with `corrects: <study id>`, `role: context`, `case_definition: none` (rule V17), through the pipeline; the weekly `prepare` lists it under `errata_on_cards`. |
| **C13** Bibliographic fields | A study that has `authors`, `journal` or `doi` must have the same value as the cached PubMed record (authors: the same names in the same order; `doi`: `null` when the record has none). Each field present is compared on its own, and the error names the field. A study without the fields is not checked. | Fill them from the record: `uv run python -m me_atlas.citations bibliography --write`. Never edit them by hand. |

When there is no usable record (C1), the other checks for that study are skipped. A DOI-only study without `preprint: true` gets only C7.

## Preprints

A `doi:` study with `preprint: true` is checked against the cached Europe PMC preprint record with that DOI (`data/cache/europepmc/preprints/PPR<digits>.json`, DOI compared case-insensitively), by the same normalisation as above:

- **C1**: no cached record. The hint is `uv run python -m me_atlas.europepmc preprint <doi>`.
- **C2** title and **C3** year against the record (`pubYear`).
- **C5**: the quote must be verbatim in the record's abstract (HTML tags such as `<h4>` removed) or, with source `fulltext`, in the cached full text. Full text is the shared `<pmcid>.xml` cache, with the PMC id taken from the preprint record; the hint is `europepmc preprint <doi> --fulltext`. A placeholder (PDF note) is not full text.
- **C6** (warning): sample sizes in the abstract or the cached full text.

C4 does not apply (the record carries no retraction marker). The status of a preprint is not peer review; V15 in `docs/card-format.md` keeps it out of levels, badges, contested marks and links.

## Normalisation

Exactly this, nothing looser. Anything else that differs is a mismatch.

- **Title (C2).** Unicode NFKC; whitespace collapsed; case folded; one trailing period removed; and the square brackets that wrap the whole title removed (PubMed writes `[Title in English].` for translated papers), but only when there is no other square bracket inside them, so `[Foo] and [bar]` stays as it is. Brackets inside a title are kept. Both the card title and the record title are normalised the same way and then compared.
- **Quote (C5).** Unicode NFKC; whitespace collapsed; curly and low/reversed quote marks (`‘ ’ “ ”`, and U+201A, U+201B, U+201E, U+201F) read as straight; the hyphen, non-breaking hyphen, figure dash, en dash, em dash, horizontal bar and minus sign (U+2010 to U+2015, U+2212) read as the ASCII hyphen. The normalised quote must occur as a substring of the normalised source text. Case, punctuation and wording are not touched.
- **Number (C6).** A whole number: `1234` also matches `1,234` and `1 234` (a space, no-break space or thin space). It must not be part of a longer number, so 48 is not found in `148`, `1,048`, `.48`, `0.48`, `3.48` or `48.5`.

- **Group (C9).** Author names and `group` text are both put through Unicode NFKD with combining marks removed (so `Gómez` equals `Gomez`). A record author `<last> <initials>` (the initials are capital letters) is named in `group` when the text has the last name (case folded), then whitespace (a comma may precede it), then the first initial (case folded), then only further capital initials, with optional dots or spaces between them, ending at a word boundary. `Ponting C`, `Ponting CP`, `Ponting C.P.` and `Ponting C P` all name the record author `Ponting CP` (and `Ponting C`); `Ponting Cox` and `Smith Anna` do not name `Ponting C` or `Smith AB`. A collective (group) author, and a name with no initials, is named only by its full name as whole words, case folded (`Long Covid Cons` does not name `Long COVID Consortium`). Other names in `group` (cross-references such as "same group as ...") are allowed; only "no author of the record is named" is an issue.

## Numbers in free text (C10)

Founder ruling 2026-11-15 (`docs/pm/DECISIONS.md`, the valve entry, "Numbers"). **Plainly: the check verifies that a number occurs in a cited source, not that it is attached to the right thing.** `40` may be the number of controls in the source and the number of patients on the card; the check passes it. A person or the review agent still reads the sentence against the record.

**What is checked.** Every free-text item of a card, the same list the valve and the translations use (`translations.english_items`, without the card `name`): `core_claim`, each paragraph of `level_reason`, the contested reason and the two badge reasons, `subgroups`, `early_signals`, link texts and each study's `finding`. A paragraph's sources are its own `sources`; a study's `finding` has none and cites its own study. A numeral passes when it is found (a) in the cached text of at least one of those sources: the PubMed title and abstract and, when cached, the full text (for a preprint: the Europe PMC record and full text), or (b) equals the `year`, `n_patients` or `n_controls` of a cited study (the only numeric study fields). Same offline cache as the other checks. A cited source with no cached record offers no numbers.

**Severity.** `citations check` reports C10 as a **warning** on `cards/` and `drafts/` (it never changes the exit code there; the existing text is counted, not edited to pass, until the founder rules). It is an **error** where text is newly applied: `pipeline apply` for weekly pairs, correction rounds (`--round C<k>`) and `valve-apply`, because those call the check with `numbers_level=ERROR`. As for other errors, a C10 problem the text already had before the change (same kind of item, same words around the number) is `preexisting` and does not block. The issue names the kind of item (`level_reason`, not the paragraph's index) and quotes a few words around the number, so removing an earlier paragraph does not turn an old problem into a new one.

**Normalisation** (each with one example):

- Thousands separators: `9,392` equals `9392`, also `9 392` in a source.
- Decimals: `0.05` equals `.05`. Trailing zeros are kept: `0.50` is not `0.5`.
- A leading `<`, `>`, `≤`, `≥` or `=` is ignored: `p<0.05` checks `0.05`.
- Percentages: `26%` checks `26`; the source may say `26%`, `26 %` or `26 percent`. The unit is not compared.
- Ranges and pairs: `18-65`, `18–65`, `18 to 65`, `18 and 65` check `18` and `65` separately.
- Minus signs and negative numbers: `-0.8` and `−0.8` check `0.8`. The sign is not compared.
- A number inside a name or an identifier is skipped. The skip patterns: `pmid:`, `doi:`, `pmcid:` and `PPR` ids and any DOI; `PMC<digits>`; a year in a citation string (`Smith et al. (2019)`, `Smith (2019)`, `Fukuda 1994`, `2015 IOM criteria`, `2003 Canadian ...`); letters directly followed by digits (`COMPASS-31`, `IL-6`, `CD4`, `SF-36`, `COVID-19`, `IOM2015`, ICD codes such as `G93.3`); a digit before a capital (`5-HT`); a chemical prefix (`3-hydroxykynurenine`).
- Rubric numbers: `level 3`, `rungs 2 and 3`, `step 1` refer to the rubric, not to a source, and are skipped. Only 0 to 5 counts (the rungs); a joined number outside that range (`level 3 and 47`, `step 2 to 47`) or followed by a counted noun (`level 3, 4 patients`) is still checked.
- Ordinals (`3rd`, `21st`) are skipped.

**Word numbers.** In the card, numbers written as words (`two`, `twelve`, `half`) are **not checked**: `one` and `two` are too common as plain words (`one study`) for a low-noise rule. The source side counts both forms: a source that writes `twelve`, `Thirty`, `twenty-eight` or `forty two` (one to ninety-nine, hyphen or space, any case) matches `12`, `30`, `28` or `42` on the card. `hundred` forms are not read.

**Derived numbers.** A sum or difference of numbers from the record is not found in any record, so it fails unless it carries its derivation. The form is a marker right after the number, `78 (= 40 + 38) patients` or `12 (= 50 - 38)`: the arithmetic must hold, and each operand is an ordinary numeral that must itself be in a cited source or a structured field. Only `+` and `-` of plain numbers are evaluated; a ratio, a percentage computed from counts or any other expression is not allowed (write the numbers the record gives). A marker whose arithmetic is wrong, or which is not a sum or difference, is an issue. This form is a proposal for the founder to confirm.

**Proper nouns (assessed, not built).** A check that city, country and institution names in free text occur in a cited record was tried over `cards/` and `drafts/` (assessment in the task notes): it was left out because the cached records hold no affiliations and the abstracts rarely name a country, so most hits are claims the check cannot verify rather than wrong ones, and names such as `Institute of Medicine` or `UK` (for `United Kingdom`) are false hits. The review agent's checklist (group and place names that are not in the records) covers it.

## Author statements (C11)

Founder ruling 2026-11-15/16 (`docs/pm/DECISIONS.md`, "Author facts by code"). **Plainly: C11 reports a statement the cached author lists contradict. It does not verify that a statement is true, and when in doubt it reports nothing.** The author facts are computed from the cached records only (`citations.author_facts`): the authors of each study that has a cached author list, the first and last author with the first affiliation of each (a PubMed record only; a preprint record gives authors only), and for every pair of studies the authors they share by two matches. `exact` is the same name after the C9 normalisation (NFKD, combining marks removed, case folded); `loose` is the same last name and the same first initial (never fewer than `exact`). The facts are written as a section "Author facts" into the correction context, every whole-card review context (also `--pre`) and the valve fix-check context, so the drafter and the reviewers read the same numbers the check uses.

**Severity and level.** The same as C10: a **warning** in `citations check` over `cards/` and `drafts/` (the exit code is not changed; existing text is counted, not edited to pass), an **error** for every applied text (weekly pairs, correction rounds, `valve-apply`), and a problem the text already had before the change (same kind of item or study, same words) is `preexisting` and does not block. The issue is keyed by the kind of item (or the study id) and the words, never by a paragraph's index.

**Patterns.** Text is read with whitespace collapsed, case ignored.

- **(a) a count.** `share(s|d) [exactly] N [of their|the] (co-)authors`; `N shared|common (co-)authors`; `N (co-)authors in common`. N is a numeral or a word from one to twenty. Not read: a number preceded by `at least`, `at most`, `more than`, `fewer than`, `less than`, `over`, `under`, `up to`, `about`, `around`, `roughly`, `approximately`, `nearly`, `almost`, `only` or `just`; a count followed by `with the|a|an|that|this|its|their|those|these` (the study it is counted against is then named in words and may not be cited in the item). The item must cite at least two studies with a cached author list; the count is reported when it lies outside [exact, loose] for every pair of them.
- **(b) none shared.** `no (co-)authors (are|were) shared`; `share(s|d|ing) no (co-)authors`; `no shared (co-)authors`; `no (co-)authors in common`; `no author overlap`; `independent [research] groups` (plural only, and not followed by `of`). Not read when the phrase is followed by `with` (`no authors are shared with the earlier study`: the study named may not be cited in the item; not for `independent groups`), or when `not`, `never`, `nor`, `neither`, `partly`, `partially`, `largely`, `barely`, `hardly`, `unlikely`, `whether`, `if` or `n't` occurs in the 30 characters before. Reported only when the item cites at least two studies with a cached author list and every pair of them shares at least one `exact` author.
- **(c) position.** In a study's `group`: `first author` or `last author` followed by a capitalised name (a name after an optional `Dr` or `Prof`). The name is the text up to the next `;`, `(` or `)`, at most 40 characters. It is reported when it names neither the record's first (last) author by the C9 rule nor, as a whole word, that author's last name. `first author at ...`, `first author, same institute`, `affiliation from first author` and `first author's ...` are not claims.
- **(d) also on.** In a study's `group`: `<names> also on <pmid> [and <pmid>]`, the names being the text since the last `;`, `(` or `)`, split at `and`, `&` and commas, each name read as `<Last> <INITIALS>` (capitalised words, then one to three capital letters; any other piece is not read). A name is reported when the record of that PMID has a cached author list and no author there has that last name and first initial (or is named by the C9 rule). The record need not be on the card.

**Not checked.** A claim about a study the item does not cite (a count against `the Swedish study`, or against a study named only in words); `lead author`, `senior author`, `corresponding author`; `same group as ...` and `overlapping cohort`; positional words in free text (`the first author of ...`); a name written in another order than `<Last> <initials>` in (d); affiliations and place names (the first affiliation is shown to the reader, not compared); a study with no cached author list, and a preprint record with none; collective authors beyond the full-name match; that two authors with the same last name and initial are the same person (`loose` is a looser reading, not an identity); and whether a statement that passes is true.

## Group matching (C9)

C9 checks only that `group` is anchored in the record: it does not check the affiliation, and it does not check that the named person is the last author. It is a warning in `citations check`, so a run over `cards/` and `drafts/` never fails because of it. In `pipeline apply` a C9 issue on the applied copy that the card did not already have (same study, code and message before the change) fails the pair and is counted with the citation errors; a C9 issue already on the card is marked `preexisting` and does not block. The reason: a drafter that adds a study may only name authors the record supports.

## Why sample size is only a warning

A number on a card can be right and still not appear as digits: the paper may write it as a word ("forty-eight"), the card may give the sum of two cohorts, or the number may belong to one measurement in a larger study (the card format records the number in the measurement that bears on the finding). A hard error would send people to "fix" correct numbers. A warning makes a person look, and the check stays quiet when the number is found. A warning never changes the exit code. If the full text is not cached, the check can only see the abstract and the message says so.

## Not checked

Author names in `group` beyond C9 and C11; the `finding` text against the source; sources named only in YAML comments; an erratum that is not a PubMed link (C12 reads the `ErratumIn` links of the cached records only); cohort overlap beyond the shared-author counts of C11; whether a retraction happened after the last fetch.

## Placeholder full text, and the PMC id from PubMed

A cached `<pmcid>.xml` is full text only if it has a real body. Europe PMC sometimes serves a placeholder for a preprint: a body of under 1,000 characters that says the full text is available as a PDF, or an article with no body text. The check never reads such a file as full text. C5 with `fulltext` then reports that there is no cached full text (the message says the file is a PDF placeholder), and C6 looks at the abstract only. The same test (`europepmc.is_placeholder_fulltext`) is used when the full text is fetched, so a placeholder is not written to the cache. No PDF is downloaded or read. `europepmc fulltext` and `casedef` print the status with the PMC id: `PMC record, full text is a PDF only (not read)` or `PMC record, no full-text XML in Europe PMC`. They read the PMC id from the cached PubMed record when Europe PMC has none. `casedef` and `pmcpage` mark sentences that may exclude people with the illness with `[exclusion]`.

The PMC id used to find `<pmcid>.xml` and `<pmcid>.html` is the one in the cached Europe PMC lookup. When the lookup has none (Europe PMC can lack the id for a while after PubMed has it), the check uses the `pmcid` of the cached PubMed record. This is still offline.

## The TODO rule is not a citation check

"TODO" in text a reader sees (the card name, any sourced text, a study's `finding`) is the card validator's rule V14 (`docs/card-format.md`), not a citation check. Run `uv run python -m me_atlas.cards validate`. This check does not look for it.

## Filling the bibliographic fields

`uv run python -m me_atlas.citations bibliography [--cache-dir DIR] [--write] [paths...]` copies `authors`, `journal` and `doi` from the cached PubMed record onto every `pmid:` study of the cards (default `cards/`). Without `--write` it only reports what it would change. It inserts three lines after the study's `year:` line (or replaces them if they are there) and changes nothing else: no other line, comment or ordering; it refuses a file where the edit would change anything but the three fields. A study with no cached record, a record with no journal, or a `doi:` study is listed as left unchanged. It never touches the network.

## Tests

`tests/test_citations.py` (preprint tests use fictional records in `tests/fixtures/europepmc/preprint_page1.json`) builds a fictional cache (PMIDs 9000000x, titles starting "Fictional", fictional PMCIDs) and fictional cards in a temporary directory. A test makes any HTTP client construction or request fail, to show the check stays offline.

## Free-to-read PMC pages as full text

Some cited studies are free to read on PubMed Central but are not in its open-access subset, so Europe PMC has no full-text XML for them. For such a study (the cached Europe PMC lookup has a PMCID and `inPMC` "Y"; founder ruling 2026-11-08) `uv run python -m me_atlas.europepmc pmcpage --card <card.yaml> <pmid>...` fetches the article page `https://pmc.ncbi.nlm.nih.gov/articles/<PMCID>/` once and caches it as `data/cache/europepmc/<PMCID>.html`. The limits:

- On demand, one PMID per request, only for `pmid:` studies on the card or draft named on the command line; never in bulk and never from a publisher site. PMC asks that its site is not crawled; reading one cited article, cached once, is not crawling.
- The page is cached only if its `citation_pmid` equals the PMID asked for and it has a main article body. Otherwise nothing is written.
- Only the abstract and main article body are read (no reference list, navigation, header, footer or scripts). The page is used to find and check the case-definition sentence (C5) and sample sizes (C6). A card quotes at most that one sentence.
- On the card it is `case_definition_source: fulltext`. The check prefers the open-access XML when both are cached, and stays offline.
