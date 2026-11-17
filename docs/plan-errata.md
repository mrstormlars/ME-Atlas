# Plan: errata and corrections to a cited paper

Status: ruled A(a), B(a), C(a) and built on `feat/errata-path` (section 3 as written; the check is C12, the validator rule V17).

## 1. The gap

Retractions are handled: `pubmed.py` marks a record retracted (publication type "Retracted Publication" or a `RetractionIn` link), every fetch runs a retraction query and re-fetches stale cached records, citation check C4 fails a retracted citation, and the weekly report lists a newly retracted paper a card cites, after which the founder decides how the card changes (`docs/pipeline.md`, "What `prepare` selects"). A published erratum or correction to a cited study is not detected, not reported, and has no defined place in the card format (`docs/pm/STATUS.md`, "To build or fix" and "Format backlog").

## 2. What the records carry (checked 2026-11-17)

Counted in the 281 cached PubMed records (`data/cache/pubmed/*.xml` of the main checkout) with a parser, not from memory:

- `MedlineCitation/CommentsCorrectionsList/CommentsCorrections` elements with `RefType`: `CommentIn` 42, `ErratumIn` 4, `ErratumFor` 2, `UpdateOf` 2, `CommentOn` 1. Each carries the linked `PMID` and a `RefSource` string (journal, date, DOI).
- `PublicationType` "Published Erratum" (UI D016425) on 2 records: the erratum notices themselves.
- No `RetractionIn`, expression-of-concern or republication link occurs in the cache. PubMed defines further `RefType` values; which ones exist is to be checked against the NLM DTD before any is handled, not assumed.
- The test fixtures (`tests/fixtures/pubmed/`) have no `ErratumIn` or `ErratumFor`.

The four `ErratumIn` links, against the published cards:

| Corrected study | Erratum | On the cards today |
|---|---|---|
| pmid:41834684 (white-matter NII study) | pmid:42227214 | Erratum is a study entry on `neuroinflammation` (role `context`, `case_definition: none`), cited next to the study in a sentence, with a comment saying what it corrects. (`brain-and-brainstem-mri-changes` names the study in YAML comments only, not as a study.) |
| pmid:40703261 (daratumumab pilot) | pmid:40901516 | Named in a YAML comment on `autoimmunity-autoantibodies-b-cells` only ("TODO: verify what it corrects"); not a study entry. |
| pmid:28694809 (cytotoxic lymphocyte phenotype) | pmid:30915066 | Not on `reduced-nk-cell-function`, which cites the study. Erratum not cached. |
| pmid:21777306 (ICC criteria paper) | pmid:28929634 | Not cited by any card. |

So the format can already cite an erratum, as a study entry with role `context`; what is missing is a machine-readable link to the study it corrects, a check that finds a missing one, and a path that brings it to the drafter. The two `UpdateOf` links point from a journal article to its earlier preprint; they are not corrections and are out of scope.

A cached record is fetched once. An `ErratumIn` link added to PubMed after the record was cached is not seen unless the record is fetched again: detection needs a re-fetch of the cited records, as the retraction query does for retractions.

## 3. Smallest path (recommended)

1. **Parse.** `PubmedRecord` gains `errata` (the PMIDs of `ErratumIn` links) and `erratum_for` (of `ErratumFor`). Offline tests with two new recorded fixtures.
2. **Re-fetch cited records.** Each weekly `prepare` re-fetches the PubMed records of the studies the published cards cite (276 distinct PMIDs on 2026-11-17: a few batched efetch requests within the NCBI rate limit) and fetches any erratum notice not yet cached. Written to the cache as a normal fetch, recorded in the manifest.
3. **Card format.** An optional study field `corrects: <study id>` on the erratum's own study entry. Validator: the target is a study on the same card; an entry with `corrects` has role `context`, `design: other`, `case_definition: none`, and is not a source of `level_reason`, `contested.reason` or a badge reason (as V15 does for preprints). Optional, so no card has to change in the same pull request; `neuroinflammation` is brought in line through the pipeline.
4. **Check.** New citation check C12 (warning): a cited study whose record lists an erratum that is not a study entry on the card. With today's cache it fires on `autoimmunity-autoantibodies-b-cells` and `reduced-nk-cell-function`.
5. **Surface in the weekly run.** `prepare` lists each erratum of a cited study that is not on the card (`errata_on_cards`), and puts the pair (erratum, card) into the run as a fixed pair, without the classifier: the drafter gets the erratum record, its full text when free (an erratum abstract is usually empty) and the corrected study's card entry, and may propose `add_study` for the erratum with `corrects` plus the operations it implies on the text. Then the normal review, and audit for whatever tier the operations have. The report lists the pairs.
6. **Docs.** `docs/card-format.md` (field, validator rule), `docs/citation-check.md` (C12), `docs/pipeline.md` ("What `prepare` selects", the report), `docs/fetch.md` (the re-fetch).

Estimate: one worker round, perhaps two; the largest part is step 5.

## 4. Options where a ruling is needed

**A. Who decides the card change.** (a) The pipeline: drafter → review → audit, as for a new paper (recommended: an erratum is published text about a cited study, and the audit already guards every level, badge and link move). (b) As retractions: the report lists it and the founder decides. Retractions went to the founder because a retracted study leaves the evidence; an erratum usually corrects a detail.

**B. Can an erratum move a level, a badge or the contested mark.** (a) Yes, but only by changing the corrected study (its numbers, its role, its finding); the erratum itself never counts as a study for the ladder and is never a source of a level or badge reason (recommended: the evidence is still the corrected study, now read as corrected). (b) No: an erratum may only change text; a level move waits for the founder. (c) Yes, and the erratum may stand as a source of the level reason.

**C. Other notices.** Expressions of concern and "corrected and republished" notices have no case in the cache. (a) Out of scope until one occurs; the parser records unknown `RefType` values in the manifest so the first one is seen (recommended). (b) Treat an expression of concern like a retraction now.

## 5. Ruling asked

Recommendation: A(a), B(a), C(a). With that ruling the path in section 3 can be built as one pull request; with A(b) step 5 shrinks to a report line, as for retractions.
