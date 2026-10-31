# Plan: Europe PMC full text and card format v2

October 31, 2026 · For `/orchestrator`

## Why

The first two real draft cards (`drafts/reduced-nk-cell-function.yaml`, `drafts/neuroinflammation.yaml`) showed that PubMed abstracts rarely state the case definition. Under the rules, a study without a stated case definition cannot support or contradict a hypothesis, so the largest studies on both cards ended up as background and neither level can be set with confidence. The case definition is normally in the methods section of the full text. The card format also had no honest way to say "not checked yet", which way a background study points, or which research group did a study.

## Goal

1. A command that, for given PMIDs, fetches open-access full text from Europe PMC, caches it, and shows the sentences that name a case definition, so an agent or the founder can record it with a verbatim quote.
2. A small revision of the card format that closes the three gaps found, without adding anything the first cards did not need.

## Part A: Europe PMC full text

Design:
- **On demand, not bulk.** Full text is fetched only for PMIDs cited on a card or draft (or given on the command line), not for all 9,400 cached records.
- **Lookup:** Europe PMC REST search by PubMed id to get the PMCID and the open-access flag; if open access, fetch the full-text XML. Not open access → reported as "no open full text"; the case definition stays unverified.
- **Cache:** `data/cache/europepmc/<pmid>.json` (search result) and `data/cache/europepmc/<pmcid>.xml` (full text). Gitignored like the rest of `data/cache/`.
- **Polite client:** reuse the rate limiter and retry logic from `src/me_atlas/pubmed.py` (move shared parts to a small common module if needed, no behaviour change for PubMed). At most 3 requests/s. Identify with a User-Agent containing `CONTACT_EMAIL`. The exact endpoint paths and parameters must be checked against the live API in the live check, not assumed.
- **Case-definition finder:** extract the methods section (fallback: whole body) and return sentences matching known definitions and their common wordings (Fukuda / 1994 CDC, Holmes / 1988 CDC, Canadian Consensus Criteria, International Consensus Criteria, IOM 2015 / SEID, Oxford). It returns candidates with the section name and the verbatim sentence. It never decides; mapping a sentence to a definition is a human or agent judgement recorded in the card.
- **CLI:** `uv run python -m me_atlas.europepmc fulltext <pmid>...` and `uv run python -m me_atlas.europepmc casedef <pmid>... | --card <path>` (the latter reads all study ids from a card).
- Full text stays in the gitignored cache. Cards quote at most the one sentence that states the case definition.

## Part B: card format v2

Changes to `src/me_atlas/cards.py`, `docs/card-format.md` and the test fixtures:

1. **Case definition provenance.**
   - New enum values: `unverified` (not yet checked) and `Holmes1988` (the 1988 CDC definition).
   - `none` now means "the source was checked and states no case definition".
   - New fields `case_definition_source: abstract | fulltext | null` and `case_definition_quote: str | null` (verbatim sentence from that source).
   - Rules: `unverified` cannot have role `supports` or `contradicts` (as `none` today). Any recognised definition (CCC, ICC, IOM2015, Fukuda, Holmes1988, Oxford) requires a source and a non-empty quote. `none` requires a source. `unverified` requires source and quote to be null.
2. **Direction.** New Study field `direction: lower | higher | no_difference | mixed | not_applicable` (patients compared with controls, on the card's measure). Required. Shown for every role, so background studies still show which way they point.
3. **Research group.** New optional Study field `group: str | null`, a short label taken from the fetched record (for example the last author's name and institution as given in PubMed). Not validated beyond being non-empty when present. Used later for the "independent group" test at level 3.

**Rubric point for the founder (record in DECISIONS):** `Holmes1988` is accepted like Fukuda: allowed at every rung, flagged on the card as "does not require PEM", ranked equal to Fukuda in the comparable-quality rule. Add it to the case-definition table in `docs/ME-Atlas-functional-spec.md` section 3.

## Steps

1. Shared HTTP helpers (rate limiter, retries) usable by both clients; PubMed tests stay green unchanged.
2. `src/me_atlas/europepmc.py`: lookup, full-text fetch, cache, methods-section extraction, case-definition finder, CLI.
3. Tests `tests/test_europepmc.py` with fictional fixtures (fictional PMIDs and PMCIDs, titles starting "Fictional") and `httpx.MockTransport`.
4. Card format v2 in `cards.py` with the rules above; update the valid fixture and add failing tests; update `docs/card-format.md`.
5. Migrate the two drafts mechanically: every study gets `case_definition_source` and `case_definition_quote` from its existing YAML comments where the abstract wording is quoted there, otherwise `unverified`; `direction` from the existing `finding` text; `group: null`. No change to level, contested, badges or wording beyond what the migration needs. Both drafts must validate.
6. Spec section 3 table gains Holmes 1988; DECISIONS entry (format v2, Holmes 1988 ruling, Europe PMC on demand); STATUS update.
7. **Live check (manual, not in pytest):** run `casedef --card` on both drafts. Report per PMID: open access yes/no, candidate sentences found. Record the summary in the PR description.

## Done when

- [ ] `uv run pytest` passes, `uv run ruff check .` clean; no test touches the network.
- [ ] Europe PMC tests cover: open-access hit with full text; not open access (reported, nothing fetched); PMID unknown to Europe PMC; cached result not re-requested; 429 then 200 succeeds.
- [ ] Case-definition finder tests: finds a Fukuda wording, a Canadian Consensus wording and an Oxford wording in a methods section; returns nothing for a methods section without one; falls back to the body when no methods section exists.
- [ ] Format tests, each with an input that fails: `unverified` with role `supports`; `Fukuda` without quote; `Fukuda` without source; `none` without source; `unverified` with a quote; missing `direction`; `direction` outside the enum; empty-string `group`.
- [ ] `Holmes1988` is accepted and treated like Fukuda by V5 and the comparable-quality ranking (tested).
- [ ] Both drafts validate under format v2, and their level, contested and badge values are unchanged (`git diff` shows only migration fields).
- [ ] The live check ran and its per-PMID summary is in the PR description.
- [ ] No new dependencies; `data/cache/` stays gitignored; nothing added to `cards/`.

## Out of scope

- Re-grading the two drafts with full-text case definitions: done afterwards in chat by the drafting agents and `card-reviewer`, then the founder decides levels.
- Bulk full-text download, non-open-access papers, PDF parsing.
- Fields for extra control groups, reviews and meta-analyses, errata, or reasons for "no" badges (noted, not yet needed).
- AI classification, site generator.
